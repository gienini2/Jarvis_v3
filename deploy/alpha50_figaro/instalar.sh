#!/usr/bin/env bash
# Instala (o actualiza) Alpha50 en Figaro. Lo lanza migrar_desde_pc.ps1 por SSH,
# como root, despues de subir el paquete a /tmp/alpha50_deploy:
#   codigo/   alpha50/*.py + connectors/garmin_workouts.py
#   relay/    relay.py (version que enruta /alpha50 al servicio local)
#   datos/    alpha50_cronologia.db, *_plan.json, .garmin_session/  (solo en la 1a migracion)
#   deploy/   alpha50.service, requirements*.txt, este script
#   env       el .env de Alpha50
# Idempotente: si /opt/alpha50 ya tiene datos, NO los pisa.
set -euo pipefail

SRC=/tmp/alpha50_deploy
DST=/opt/alpha50
RELAY_DIR=/opt/jarvis-relay
STAMP=$(date +%Y%m%d-%H%M%S)
# El paquete lleva credenciales: se borra pase lo que pase
trap 'rm -rf "$SRC"' EXIT

[ "$(id -u)" = 0 ] || { echo "Ejecuta como root"; exit 1; }
[ -d "$SRC/codigo/alpha50" ] || { echo "No encuentro $SRC/codigo/alpha50"; exit 1; }

echo "== 1. Codigo en $DST"
mkdir -p "$DST/alpha50" "$DST/connectors"
cp "$SRC"/codigo/alpha50/*.py "$DST/alpha50/"
cp "$SRC"/codigo/connectors/garmin_workouts.py "$DST/connectors/"

echo "== 2. Datos (solo si aun no existen en Figaro)"
if [ -f "$DST/alpha50/alpha50_cronologia.db" ]; then
    echo "   $DST ya tiene BD: se conserva la de Figaro (no se copia la del PC)"
else
    cp -a "$SRC"/datos/. "$DST/alpha50/"
    echo "   copiados: $(ls -A "$SRC/datos" | tr '\n' ' ')"
fi

echo "== 3. .env"
install -m 600 "$SRC/env" "$DST/.env"

echo "== 4. Entorno Python"
if [ ! -x "$DST/venv/bin/python" ]; then
    python3 -m venv "$DST/venv" 2>/dev/null || { apt-get update -qq && apt-get install -y -qq python3-venv && python3 -m venv "$DST/venv"; }
fi
REQ="$SRC/deploy/requirements.lock.txt"; [ -s "$REQ" ] || REQ="$SRC/deploy/requirements.txt"
"$DST/venv/bin/pip" install -q --upgrade pip
"$DST/venv/bin/pip" install -q -r "$REQ"

KEY=$(grep -E '^ALPHA50_API_KEY=' "$DST/.env" | cut -d= -f2-)
BIND=$(grep -E '^ALPHA50_BIND=' "$DST/.env" | cut -d= -f2-)
PORT=$(grep -E '^ALPHA50_PORT=' "$DST/.env" | cut -d= -f2-)

echo "== 5. Puerto"
systemctl stop alpha50 2>/dev/null || true      # libera el puerto si ya era nuestro
libre() { ! ss -ltnH "( sport = :$1 )" | grep -q .; }
if ! libre "$PORT"; then
    echo "   el $PORT esta ocupado por: $(ss -ltnpH "( sport = :$PORT )" | head -1)"
    PORT=""
    for p in $(seq 10050 10099); do if libre "$p"; then PORT=$p; break; fi; done
    [ -n "$PORT" ] || { echo "No hay puerto libre entre 10050 y 10099"; exit 1; }
    sed -i "s/^ALPHA50_PORT=.*/ALPHA50_PORT=$PORT/" "$DST/.env"
fi
echo "$PORT" > "$DST/PUERTO"; chmod 644 "$DST/PUERTO"   # lo lee el script del PC
echo "   Alpha50 usara el puerto $PORT"

echo "== 6. Servicio systemd"
install -m 644 "$SRC/deploy/alpha50.service" /etc/systemd/system/alpha50.service
systemctl daemon-reload
systemctl enable alpha50 >/dev/null
systemctl restart alpha50
OK=""
for i in $(seq 1 15); do
    if curl -fsS "http://$BIND:$PORT/health" 2>/dev/null | grep -q '"alpha50"'; then OK=1; break; fi
    sleep 2
done
if [ -z "$OK" ]; then
    echo "!! Alpha50 no responde en http://$BIND:$PORT -- no toco el relay"
    journalctl -u alpha50 -n 25 --no-pager
    systemctl disable --now alpha50 >/dev/null 2>&1 || true
    # Si una instalacion anterior dejo el relay apuntando aqui, devolverlo al PC
    if grep -q '^ALPHA50_URL=' "$RELAY_DIR/.env"; then
        sed -i '/^ALPHA50_URL=/d;/^ALPHA50_API_KEY=/d' "$RELAY_DIR/.env"
        systemctl restart jarvis-relay
        echo "   relay devuelto al PC (sin ALPHA50_URL)"
    fi
    exit 1
fi
echo "   Alpha50 responde"

echo "== 7. Relay: enrutar /alpha50 al servicio local"
cp -a "$RELAY_DIR/relay.py" "$RELAY_DIR/relay.py.bak.$STAMP"
cp -a "$RELAY_DIR/.env" "$RELAY_DIR/.env.bak.$STAMP"
install -m 644 "$SRC/relay/relay.py" "$RELAY_DIR/relay.py"
sed -i '/^ALPHA50_URL=/d;/^ALPHA50_API_KEY=/d' "$RELAY_DIR/.env"
printf 'ALPHA50_URL=http://%s:%s\nALPHA50_API_KEY=%s\n' "$BIND" "$PORT" "$KEY" >> "$RELAY_DIR/.env"
systemctl restart jarvis-relay
echo "   copias: relay.py.bak.$STAMP y .env.bak.$STAMP en $RELAY_DIR"

echo "== 8. Comprobaciones"
sleep 5
systemctl is-active alpha50 jarvis-relay || echo "   !! algun servicio no esta activo"
echo "   hora del servicio: $(TZ=Europe/Madrid date '+%Y-%m-%d %H:%M %Z')"
curl -fsS -H "X-Alpha50-Key: $KEY" -X POST -H 'Content-Type: application/json' \
     -d '{"texto":"/alpha50 estado"}' "http://$BIND:$PORT/mensaje" && echo || echo "   !! /mensaje no responde"
journalctl -u alpha50 -n 10 --no-pager

echo "OK: Alpha50 instalado en Figaro (el paquete de /tmp se borra al salir)."
