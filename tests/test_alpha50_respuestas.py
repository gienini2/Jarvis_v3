"""
tests/test_alpha50_respuestas.py
Respuestas de Telegram a Alpha50 con y sin el prefijo "/alpha50".

Ejecutar:  .venv\\Scripts\\python.exe -m unittest tests.test_alpha50_respuestas -v

Caso real (01/11/2026): el bot pidió a las 07:00 las métricas que Garmin no
trajo y la respuesta "/alpha50 58/98/equilibrado/54/100.5", enviada pasadas las
2 h, devolvió el menú de ayuda: la pregunta pendiente ya había caducado. Ahora la
pregunta de métricas vale todo el día (el resto sigue caducando a las 2 h).
Además "equilibrado" (la palabra que propone el propio bot) no puntuaba como VFC buena.

Sin red: BD SQLite temporal, sin Garmin, sin relay. El decisor asíncrono se
captura en vez de ejecutarse.
"""
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "alpha50"))   # imports planos entre agentes
sys.path.insert(0, str(ROOT))

# El scheduler importa estas libs a nivel de módulo; si no están instaladas
# (entorno de CI mínimo) basta un stub: estos tests no programan ni envían nada.
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
import scheduler                   # noqa: E402


class TestRespuestasAlpha50(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "alpha50_test.db")
        self._orig = {m: m.DB_PATH for m in (cron, decisor, metrica, scheduler)}
        for m in self._orig:
            m.DB_PATH = db
        cron.init_db()
        metrica.init_db()
        cron.iniciar_programa("Intermedio", 1)

        self.decisor_llamado = []
        self._orig_async = scheduler._ejecutar_decisor_async
        scheduler._ejecutar_decisor_async = lambda m: self.decisor_llamado.append(m)

    def tearDown(self):
        scheduler._ejecutar_decisor_async = self._orig_async
        for m, p in self._orig.items():
            m.DB_PATH = p
        self.tmp.cleanup()

    def _pendiente_metricas(self):
        scheduler._sesion_update(esperando="metricas_faltantes", contexto={
            "metricas_garmin": {"fuente": "garmin", "estres_promedio": 25},
            "faltan": ["body_battery", "sueno", "hrv", "fc_reposo", "peso"],
        })

    def test_metricas_con_prefijo_se_registran(self):
        self._pendiente_metricas()
        r = scheduler.alpha50_intent_handler("/alpha50 58/98/equilibrado/54/100.5")
        self.assertIn("Métricas completadas", r)
        self.assertEqual(len(self.decisor_llamado), 1)
        m = self.decisor_llamado[0]["metricas"]
        self.assertEqual((m["body_battery"], m["sueno_score"], m["hrv_status"],
                          m["fc_reposo"], m["peso_kg"]), (58, 98, "equilibrado", 54, 100.5))
        self.assertIsNone(scheduler._sesion_get()["esperando"])

    def test_sin_prefijo_alpha50_no_responde(self):
        # Diseño desde 25/10: solo mensajes que empiezan por /alpha50
        self._pendiente_metricas()
        self.assertIsNone(scheduler.alpha50_intent_handler("58 / 98 / equilibrado / 54 / 100,5"))

    def _envejecer_sesion(self, horas):
        con = sqlite3.connect(scheduler.DB_PATH)
        con.execute("UPDATE alpha50_sesion SET actualizado="
                    "datetime('now','localtime',?) WHERE id=1", (f"-{horas} hours",))
        con.commit()
        con.close()

    def test_pregunta_de_metricas_no_caduca_a_las_2h(self):
        from datetime import datetime
        if datetime.now().hour < 5:
            self.skipTest("a esta hora, 5 h atrás es otro día")
        self._pendiente_metricas()
        self._envejecer_sesion(5)
        r = scheduler.alpha50_intent_handler("/alpha50 58/98/equilibrado/54/100.5")
        self.assertIn("Métricas completadas", r)

    def test_pregunta_de_metricas_de_ayer_caduca(self):
        self._pendiente_metricas()
        self._envejecer_sesion(30)
        self.assertIsNone(scheduler._sesion_get()["esperando"])

    def test_otras_preguntas_caducan_a_las_2h(self):
        scheduler._sesion_update(esperando="opcion_cardio", contexto={})
        self._envejecer_sesion(3)
        self.assertIsNone(scheduler._sesion_get()["esperando"])

    def test_subcomando_con_metricas_pendientes(self):
        self._pendiente_metricas()
        self.assertIn("Alpha50 — Semana", scheduler.alpha50_intent_handler("/alpha50 semana"))

    def test_prefijo_con_nombre_de_bot(self):
        self._pendiente_metricas()
        r = scheduler.alpha50_intent_handler("/alpha50@JarvisBot 58/98/equilibrado/54/100.5")
        self.assertIn("Métricas completadas", r)

    def test_subcomando_con_prefijo(self):
        r = scheduler.alpha50_intent_handler("/alpha50 estado")
        self.assertIn("Alpha50 — Hoy", r)

    def test_prefijo_solo_da_ayuda(self):
        self.assertIn("Comandos disponibles", scheduler.alpha50_intent_handler("/alpha50"))

    def test_prefijo_sin_nada_pendiente_da_ayuda(self):
        r = scheduler.alpha50_intent_handler("/alpha50 58/98")
        self.assertIn("Comandos disponibles", r)

    def test_mensaje_ajeno_no_es_alpha50(self):
        self.assertIsNone(scheduler.alpha50_intent_handler("qué tiempo hace mañana"))

    def test_vfc_equilibrado_puntua_como_balanced(self):
        base = {"body_battery": 58, "sueno_score": 98, "fc_reposo": 54, "estres_promedio": 25}
        a = metrica.calcular_indice({**base, "hrv_status": "equilibrado"})
        b = metrica.calcular_indice({**base, "hrv_status": "balanced"})
        self.assertEqual(a["puntos"]["hrv"], 90)
        self.assertEqual(a["indice"], b["indice"])


if __name__ == "__main__":
    unittest.main()
