"""
sandbox/garmin_cardio_mvp.py
MVP (banco de pruebas): traslada un dia de CARDIO de Alpha50 a un workout de
carrera de Garmin, lo sube y lo agenda -> aparece en el reloj (Forerunner 165)
y en la agenda de Garmin Connect.

Reusa la sesion ya autenticada de Jarvis (alpha50.agente_metrica._get_garmin_client),
la misma que lee tus metricas, asi que NO hace login extra (evita el 429).

USO:
  python -m sandbox.garmin_cardio_mvp                 # dry-run: imprime el payload, no sube nada
  python -m sandbox.garmin_cardio_mvp --push          # sube y agenda UN entreno de prueba para manana
  python -m sandbox.garmin_cardio_mvp --list          # lista tus workouts (id + nombre)
  python -m sandbox.garmin_cardio_mvp --delete <id>   # borra un workout (reversible)

OJO: API NO oficial de Garmin (la misma que la lectura). Zona gris de ToS, uso
personal. Todo lo que sube es reversible (--delete).
"""
import sys
from datetime import date, timedelta

from garminconnect.workout import (
    RunningWorkout,
    WorkoutSegment,
    create_warmup_step,
    create_interval_step,
    create_recovery_step,
    create_cooldown_step,
    create_repeat_group,
)

RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}
MIN = 60  # segundos por minuto


def _seg(steps):
    return WorkoutSegment(segmentOrder=1, sportType=RUNNING, workoutSteps=steps)


# ---- mapeo Alpha50 (cardio) -> workout de carrera Garmin --------------------

def run_continua(nombre, calent_min, continua_min, enfriar_min):
    """Dia de carrera continua: calentamiento + rodaje + vuelta a la calma."""
    steps = [
        create_warmup_step(calent_min * MIN, step_order=1),
        create_interval_step(continua_min * MIN, step_order=2),
        create_cooldown_step(enfriar_min * MIN, step_order=3),
    ]
    total = (calent_min + continua_min + enfriar_min) * MIN
    return RunningWorkout(workoutName=nombre, estimatedDurationInSecs=total,
                          workoutSegments=[_seg(steps)])


def run_series(nombre, calent_min, n, trabajo_seg, recup_seg, enfriar_min):
    """Dia de series: calentamiento + N x (trabajo/recuperacion) + enfriamiento.
    Ej. intervalos 30/30 x12 -> run_series(nombre, 10, 12, 30, 30, 5)."""
    bloque = create_repeat_group(
        iterations=n,
        workout_steps=[
            create_interval_step(trabajo_seg, step_order=2),
            create_recovery_step(recup_seg, step_order=3),
        ],
        step_order=2,
    )
    steps = [
        create_warmup_step(calent_min * MIN, step_order=1),
        bloque,
        create_cooldown_step(enfriar_min * MIN, step_order=4),
    ]
    total = calent_min * MIN + n * (trabajo_seg + recup_seg) + enfriar_min * MIN
    return RunningWorkout(workoutName=nombre, estimatedDurationInSecs=int(total),
                          workoutSegments=[_seg(steps)])


def _workout_prueba():
    # rodaje facil, patron Alpha50 Intermedio S1 Lunes (10' + 30' + 3')
    return run_continua("Alpha50 - Rodaje facil (prueba)", 10, 30, 3)


def _client():
    from alpha50.agente_metrica import _get_garmin_client
    return _get_garmin_client()


def main():
    args = sys.argv[1:]

    if "--list" in args:
        for w in _client().get_workouts():
            print(w.get("workoutId"), "-", w.get("workoutName"))
        return

    if "--delete" in args:
        wid = args[args.index("--delete") + 1]
        print("borrado:", _client().delete_workout(wid))
        return

    wk = _workout_prueba()

    if "--push" not in args:
        import json
        print("DRY-RUN (no se sube nada). Payload del workout de prueba:\n")
        print(json.dumps(wk.to_dict(), ensure_ascii=False, indent=2))
        print("\n--> Para subirlo y agendarlo para manana: anade --push")
        return

    client = _client()
    res = client.upload_running_workout(wk)
    wid = res.get("workoutId")
    manana = (date.today() + timedelta(days=1)).isoformat()
    client.schedule_workout(wid, manana)
    print(f"OK. Subido workoutId={wid} y agendado para {manana}.")
    print(f"Deberia aparecer en Garmin Connect y sincronizarse al reloj.")
    print(f"Para borrarlo: python -m sandbox.garmin_cardio_mvp --delete {wid}")


if __name__ == "__main__":
    main()
