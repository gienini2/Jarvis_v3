"""
alpha50/servicio.py -- Alpha50 como servicio en Figaro (siempre encendido).

Un solo proceso con dos partes:
  1. El scheduler de siempre (scheduler.arrancar_scheduler): brief de las 07:00,
     catch-up, sync de Garmin y bronca. Envia a Telegram por el relay local.
  2. Una API HTTP minima (stdlib, sin dependencias) para que:
       - el relay de Figaro le pase los mensajes "/alpha50 ..." de Telegram
         sin depender de que el PC este encendido;
       - Jarvis en el PC consulte el historial (tool query_alpha50_history,
         pestana Alpha50 de la web) y use Alpha50 desde el chat local.

Endpoints (todos menos /health exigen la cabecera X-Alpha50-Key):
  GET  /health                       -> {"status": "ok", "servicio": "alpha50"}
  POST /mensaje   {"texto": "..."}   -> {"respuesta": str | null}
  GET  /historial?dias=14&fecha=     -> get_historial()
  GET  /repaso?dias=7                -> garmin_actividades.repaso()

Arranque (Figaro, systemd alpha50.service):
    /opt/alpha50/venv/bin/python alpha50/servicio.py
Config en /opt/alpha50/.env: ALPHA50_API_KEY, ALPHA50_BIND, ALPHA50_PORT,
RELAY_URL, RELAY_API_KEY, GARMIN_EMAIL, GARMIN_PASSWORD, ALPHA50_HORA.
"""
import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)                     # imports planos entre agentes
sys.path.insert(0, os.path.dirname(BASE_DIR))    # connectors.*, alpha50.*

import scheduler  # noqa: E402  (carga el .env del directorio padre)

API_KEY = os.environ.get("ALPHA50_API_KEY", "")
BIND    = os.environ.get("ALPHA50_BIND", "127.0.0.1")
PORT    = int(os.environ.get("ALPHA50_PORT", "10050"))

# El intent handler toca la sesion en SQLite y lanza hilos: un mensaje a la vez.
_lock_mensajes = threading.Lock()


def _entero(valor, defecto: int, minimo: int, maximo: int) -> int:
    try:
        return max(minimo, min(int(valor), maximo))
    except (TypeError, ValueError):
        return defecto


class Alpha50Handler(BaseHTTPRequestHandler):
    server_version = "Alpha50/1"

    # -- utilidades ---------------------------------------------------------
    def _json(self, codigo: int, cuerpo: dict):
        datos = json.dumps(cuerpo, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _autorizado(self) -> bool:
        if not API_KEY:
            return True   # solo posible ligado a 127.0.0.1 (ver main)
        recibida = self.headers.get("X-Alpha50-Key", "")
        return hmac.compare_digest(recibida, API_KEY)

    def log_message(self, fmt, *args):
        print(f"[Alpha50/http] {self.address_string()} {fmt % args}")

    # -- rutas --------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self._json(200, {"status": "ok", "servicio": "alpha50"})
        if not self._autorizado():
            return self._json(401, {"error": "clave X-Alpha50-Key ausente o incorrecta"})
        q = parse_qs(url.query)

        if url.path == "/historial":
            from history_reader import get_historial
            return self._json(200, get_historial(
                fecha=(q.get("fecha") or [""])[0],
                dias=_entero((q.get("dias") or [14])[0], 14, 1, 90),
            ))
        if url.path == "/repaso":
            from garmin_actividades import repaso
            return self._json(200, repaso(dias=_entero((q.get("dias") or [7])[0], 7, 1, 90)))
        return self._json(404, {"error": "ruta no encontrada"})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._autorizado():
            return self._json(401, {"error": "clave X-Alpha50-Key ausente o incorrecta"})
        if url.path != "/mensaje":
            return self._json(404, {"error": "ruta no encontrada"})
        try:
            largo = int(self.headers.get("Content-Length", "0"))
            cuerpo = json.loads(self.rfile.read(min(largo, 64_000)) or b"{}")
            texto = str(cuerpo.get("texto", ""))
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "JSON invalido; se espera {\"texto\": \"...\"}"})
        try:
            with _lock_mensajes:
                respuesta = scheduler.alpha50_intent_handler(texto)
        except Exception as e:
            print(f"[Alpha50/http] fallo procesando mensaje: {e}")
            return self._json(500, {"error": f"Alpha50 fallo procesando el mensaje: {e}"})
        return self._json(200, {"respuesta": respuesta})


def crear_servidor(bind: str = None, port: int = None) -> ThreadingHTTPServer:
    bind = BIND if bind is None else bind
    port = PORT if port is None else port
    if not API_KEY and bind not in ("127.0.0.1", "localhost"):
        raise SystemExit(
            f"ALPHA50_API_KEY vacia: no expongo la API en {bind}. "
            "Pon una clave en el .env o usa ALPHA50_BIND=127.0.0.1."
        )
    return ThreadingHTTPServer((bind, port), Alpha50Handler)


def main():
    srv = crear_servidor()
    threading.Thread(target=srv.serve_forever, daemon=True, name="alpha50-http").start()
    print(f"[Alpha50] API HTTP en http://{BIND}:{PORT}")
    scheduler.arrancar_scheduler()   # bucle principal (bloquea)


if __name__ == "__main__":
    main()
