"""
tests/test_alpha50_servicio.py
API HTTP de Alpha50 en Figaro (alpha50/servicio.py) y su cliente en el PC
(alpha50/remoto.py), de extremo a extremo con una BD SQLite temporal.

Ejecutar:  python -m unittest tests.test_alpha50_servicio -v

Sin red exterior: el servidor escucha en 127.0.0.1 en un puerto libre; no se
toca Garmin ni Telegram.
"""
import json
import os
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "alpha50"))
sys.path.insert(0, str(ROOT))

for _mod in ("schedule", "dotenv", "requests"):
    try:
        __import__(_mod)
    except ImportError:
        stub = types.ModuleType(_mod)
        stub.load_dotenv = lambda *a, **k: None
        sys.modules[_mod] = stub

import agente_cronologia as cron   # noqa: E402
import agente_decisor as decisor   # noqa: E402
import agente_metrica as metrica   # noqa: E402
import garmin_actividades as gact  # noqa: E402
import history_reader as hreader   # noqa: E402
import scheduler                   # noqa: E402
import servicio                    # noqa: E402

CLAVE = "clave-de-prueba"


class TestServicioAlpha50(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(cls.tmp.name, "alpha50_test.db")
        cls._orig = {m: m.DB_PATH for m in (cron, decisor, metrica, scheduler, gact, hreader)}
        for m in cls._orig:
            m.DB_PATH = Path(db) if m is hreader else db
        cron.init_db()
        metrica.init_db()
        cron.iniciar_programa("Intermedio", 1)

        cls._orig_key = servicio.API_KEY
        servicio.API_KEY = CLAVE
        cls.srv = servicio.crear_servidor("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        servicio.API_KEY = cls._orig_key
        for m, p in cls._orig.items():
            m.DB_PATH = p
        cls.tmp.cleanup()

    def _pedir(self, ruta, cuerpo=None, clave=CLAVE):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos,
                                     headers={"X-Alpha50-Key": clave,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_sin_clave(self):
        self.assertEqual(self._pedir("/health", clave="")[0], 200)

    def test_sin_clave_rechaza(self):
        self.assertEqual(self._pedir("/historial", clave="mala")[0], 401)
        self.assertEqual(self._pedir("/mensaje", {"texto": "/alpha50 estado"}, clave="")[0], 401)

    def test_mensaje_estado(self):
        codigo, r = self._pedir("/mensaje", {"texto": "/alpha50 estado"})
        self.assertEqual(codigo, 200)
        self.assertIn("Alpha50 — Hoy", r["respuesta"])

    def test_mensaje_ajeno_devuelve_null(self):
        codigo, r = self._pedir("/mensaje", {"texto": "qué tiempo hace"})
        self.assertEqual(codigo, 200)
        self.assertIsNone(r["respuesta"])

    def test_metricas_pendientes_por_http(self):
        llamadas = []
        orig = scheduler._ejecutar_decisor_async
        scheduler._ejecutar_decisor_async = lambda m: llamadas.append(m)
        try:
            scheduler._sesion_update(esperando="metricas_faltantes", contexto={
                "metricas_garmin": {"fuente": "garmin", "body_battery": 70,
                                    "sueno_score": 80, "hrv_status": "balanced",
                                    "fc_reposo": 50, "estres_promedio": 25},
                "faltan": ["peso"],
            })
            codigo, r = self._pedir("/mensaje", {"texto": "/alpha50 98.5"})
        finally:
            scheduler._ejecutar_decisor_async = orig
        self.assertEqual(codigo, 200)
        self.assertIn("Métricas completadas", r["respuesta"])
        self.assertEqual(llamadas[0]["metricas"]["peso_kg"], 98.5)

    def test_historial(self):
        codigo, r = self._pedir("/historial?dias=7")
        self.assertEqual(codigo, 200)
        self.assertEqual(r["programa"]["nivel"], "Intermedio")
        self.assertIsInstance(r["historial"], list)

    def test_json_invalido(self):
        req = urllib.request.Request(self.base + "/mensaje", data=b"{no json",
                                     headers={"X-Alpha50-Key": CLAVE})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_no_expone_sin_clave_fuera_de_localhost(self):
        servicio.API_KEY = ""
        try:
            with self.assertRaises(SystemExit):
                servicio.crear_servidor("0.0.0.0", 0)
        finally:
            servicio.API_KEY = CLAVE

    def test_cliente_remoto_del_pc(self):
        import importlib
        if isinstance(sys.modules.get("requests"), types.ModuleType) and \
                not hasattr(sys.modules["requests"], "post"):
            self.skipTest("requests no instalado")
        remoto = importlib.import_module("alpha50.remoto")
        orig = remoto._config
        remoto._config = lambda: (self.base, CLAVE)
        try:
            self.assertTrue(remoto.activo())
            self.assertIsNone(remoto.mensaje("hola jarvis"))   # ni se envia
            self.assertIn("Alpha50 — Hoy", remoto.mensaje("/alpha50 estado"))
            self.assertEqual(remoto.historial(dias=3)["programa"]["nivel"], "Intermedio")
        finally:
            remoto._config = orig


if __name__ == "__main__":
    unittest.main()
