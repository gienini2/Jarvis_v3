"""Autoriza a Jarvis a ENVIAR correo desde tu Gmail personal (permiso minimo: gmail.send).

Lo ejecutas tu, una vez:   python scripts/google_autorizar_usuario.py
Se abre el navegador: entra con tu cuenta personal (GOOGLE_USER_EMAIL) y acepta. Jarvis no podra leer
tu correo, solo enviar. El token se guarda en config/google_user_token.json (fuera de git).
Si Google dice 'app no verificada': Avanzado -> Continuar (es tu propia app). Si dice 'acceso bloqueado',
añade tu cuenta como usuario de prueba en Google Cloud -> Pantalla de consentimiento OAuth.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from google_auth_oauthlib.flow import InstalledAppFlow

from config.settings import settings
from connectors.google_tools import USER_SCOPES


def main():
    flow = InstalledAppFlow.from_client_secrets_file(settings.GOOGLE_CREDENTIALS_FILE, USER_SCOPES)
    creds = flow.run_local_server(port=0, login_hint=settings.GOOGLE_USER_EMAIL, prompt="consent")
    info = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {creds.token}"}, timeout=15).json()
    email = (info.get("email") or "").lower()
    if email != settings.GOOGLE_USER_EMAIL.lower():
        sys.exit(f"Has autorizado la cuenta {email or 'desconocida'}, pero se esperaba {settings.GOOGLE_USER_EMAIL}. No se ha guardado nada.")
    Path(settings.GOOGLE_USER_TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
    print(f"OK: Jarvis puede enviar correo desde {email}. Token guardado en {settings.GOOGLE_USER_TOKEN_FILE}")
    print("Nota: si la app esta en modo 'Pruebas' en Google Cloud, el permiso caduca a los 7 dias; publicala ('En produccion') para que dure.")


if __name__ == "__main__":
    main()
