"""
connectors/garmin_workouts.py
Construye un workout de carrera de Garmin desde un dia de cardio de Alpha50,
lo sube y lo agenda -> aparece en el reloj y en la agenda de Garmin Connect.

Promovido del prototipo sandbox/garmin_cardio_mvp.py. Reusa la sesion ya
autenticada de alpha50.agente_metrica (sin login extra -> evita el 429).
Por ahora manda solo duraciones; los targets de FC son el paso siguiente.

API NO oficial de Garmin (la misma que la lectura). Todo es reversible: los
workouts se pueden borrar (client.delete_workout).
"""
import re
import logging

log = logging.getLogger("jarvis.garmin_workouts")

RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}
MIN = 60


# ---- parseo de las cadenas de Alpha50 ("10'", "1'30\"", "5x100m // 5x20\"") --

def _a_segundos(txt: str, defecto: int = 0) -> int:
    """'10'' -> 600 ; '1'30\"' -> 90 ; '20\"' -> 20 ; '45' -> 45."""
    if not txt:
        return defecto
    txt = str(txt)
    m = re.search(r"(\d+)\s*'\s*(\d+)?\s*\"?", txt)  # minutos con segundos opcionales
    if m and "'" in txt:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    m = re.search(r"(\d+)\s*\"", txt)                 # solo segundos: 20"
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", txt)
    return int(m.group(1)) if m else defecto


def _parse_series(txt: str):
    """'5x100m // 5x20\"' -> (5, 20)  (n, segundos de trabajo; usa la parte de
    tiempo si existe). '5x100m' -> (5, 0)."""
    if not txt:
        return None
    partes = str(txt).split("//")
    tiempo = partes[1] if len(partes) > 1 else partes[0]
    m = re.search(r"(\d+)\s*x", tiempo)
    n = int(m.group(1)) if m else 1
    return n, _a_segundos(tiempo)


# ---- construccion del workout ---------------------------------------------

def desde_opcion_carrera(op: dict, nombre: str, series_quitar: int = 0):
    """op = dict de la opcion 'carrera' del plan Alpha50. series_quitar aplica la
    reduccion del semaforo (menos repeticiones en dias de series). Devuelve un
    RunningWorkout listo para subir."""
    from garminconnect.workout import (
        RunningWorkout, WorkoutSegment,
        create_warmup_step, create_interval_step, create_recovery_step,
        create_cooldown_step, create_repeat_group,
    )

    calent = _a_segundos(op.get("calentamiento"), 600)
    enfriar = _a_segundos(op.get("descanso_post_continua"), 180)

    orden = 1
    steps = [create_warmup_step(calent, step_order=orden)]
    orden += 1
    total = calent

    if op.get("continua"):
        dur = _a_segundos(op["continua"])
        steps.append(create_interval_step(dur, step_order=orden)); orden += 1
        total += dur

    serie = _parse_series(op.get("series_1"))
    if serie and serie[1] > 0:
        n, trabajo = serie
        n = max(1, n - max(0, series_quitar))   # semaforo: menos repeticiones
        recup = _a_segundos(op.get("descanso_series_1"), 90)
        grupo = create_repeat_group(
            iterations=n,
            workout_steps=[
                create_interval_step(trabajo, step_order=orden),
                create_recovery_step(recup, step_order=orden + 1),
            ],
            step_order=orden,
        )
        steps.append(grupo); orden += 2
        total += n * (trabajo + recup)

    steps.append(create_cooldown_step(enfriar, step_order=orden))
    total += enfriar

    seg = WorkoutSegment(segmentOrder=1, sportType=RUNNING, workoutSteps=steps)
    return RunningWorkout(workoutName=nombre, estimatedDurationInSecs=int(total),
                          workoutSegments=[seg])


# ---- subir + agendar -------------------------------------------------------

def crear_y_agendar(op: dict, nombre: str, fecha_iso: str, series_quitar: int = 0) -> dict:
    """Construye, sube y agenda el workout de carrera para fecha_iso (YYYY-MM-DD).
    Devuelve {ok, workout_id, ...} o {ok: False, error}. No lanza: pensado para
    llamarse desde el flujo de Telegram sin romperlo."""
    try:
        from alpha50.agente_metrica import _get_garmin_client
        wk = desde_opcion_carrera(op, nombre, series_quitar=series_quitar)
        client = _get_garmin_client()
        res = client.upload_running_workout(wk)
        wid = res.get("workoutId")
        client.schedule_workout(wid, fecha_iso)
        log.info(f"[garmin] workout {wid} '{nombre}' agendado {fecha_iso}")
        return {"ok": True, "workout_id": wid, "fecha": fecha_iso}
    except Exception as e:
        log.warning(f"[garmin] no pude subir/agendar '{nombre}': {e}")
        return {"ok": False, "error": str(e)}
