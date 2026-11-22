# Alpha50 en Figaro

Alpha50 pasa del PC a Figaro, que está siempre encendido. Así el brief de las
07:00 sale aunque el PC esté suspendido o sin Tailscale.

## Cómo queda

```
Figaro (systemd)
  alpha50.service  ── 07:00 ──► Garmin Connect ──► relay /notify (localhost) ──► Telegram
     ▲  API :10005 (IP Tailscale, cabecera X-Alpha50-Key)
     │
  jarvis-relay ◄── "/alpha50 ..." desde Telegram   (ya no pasa por el PC)

PC (JarvisAPI)
  ALPHA50_URL en .env ──► historial, pestaña Alpha50 de la web y "/alpha50" del chat local
  Alpha50Scheduler: desactivado
```

- **Datos** (BD, plan, sesión de Garmin): viven en `/opt/alpha50/alpha50/` de Figaro.
  La copia del PC queda congelada y solo sirve de respaldo.
- **Hora**: el servicio fija `TZ=Europe/Madrid`. Figaro va en UTC y sin esto el brief
  saldría a las 08:00 o a las 09:00.
- **Sin `ALPHA50_URL`** en el `.env` del PC, Jarvis usa Alpha50 en local como antes.

## Migrar (una vez)

En el PC, en PowerShell **como administrador**:

```powershell
cd C:\Users\Usuario\jarvis
git pull
powershell -ExecutionPolicy Bypass -File deploy\alpha50_figaro\migrar_desde_pc.ps1
```

El script:
1. Comprueba el SSH a `figaro` y que el `relay.py` desplegado es el conocido.
2. Para `Alpha50Scheduler` en el PC.
3. Sube a Figaro el código, los datos, la sesión de Garmin y un `.env` generado
   con tus credenciales del `.env` del PC y una clave nueva para la API.
4. Ejecuta `instalar.sh`: crea el venv con las mismas versiones que el PC, instala
   el servicio `alpha50` y cambia el relay para que envíe `/alpha50` al servicio.
   Antes guarda copias `.bak` del relay y de su `.env`.
5. Comprueba la API desde el PC. Si todo va bien, desactiva `Alpha50Scheduler`,
   añade `ALPHA50_URL`/`ALPHA50_API_KEY` al `.env` del PC (copia en
   `.env.bak.alpha50`) y reinicia JarvisAPI. Si algo falla, vuelve a arrancar
   Alpha50 en el PC y no cambia nada más.

Se puede repetir para actualizar el código. Si Figaro ya tiene BD, no la pisa.

## Comprobar

- Telegram: `/alpha50 estado`
- Logs: `ssh figaro journalctl -u alpha50 -f`
- Mañana a las 07:00 debe llegar el brief aunque el PC esté apagado.

## Actualizar el código más adelante

Vuelve a ejecutar `migrar_desde_pc.ps1`. Actualiza el código y el relay y conserva
los datos de Figaro.

## Volver atrás

En Figaro:
```bash
systemctl disable --now alpha50
cd /opt/jarvis-relay && cp relay.py.bak.<fecha> relay.py && cp .env.bak.<fecha> .env
systemctl restart jarvis-relay
```
En el PC:
- Quita `ALPHA50_URL` y `ALPHA50_API_KEY` del `.env`.
- Ejecuta `nssm set Alpha50Scheduler Start SERVICE_AUTO_START`, luego
  `nssm start Alpha50Scheduler` y por último `nssm restart JarvisAPI`.
- Si quieres conservar lo registrado mientras tanto, copia antes la BD de Figaro al PC:
  `scp figaro:/opt/alpha50/alpha50/alpha50_cronologia.db alpha50\`.
