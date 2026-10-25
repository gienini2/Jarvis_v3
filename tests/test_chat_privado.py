"""Prueba de resumir_chat / redactar_como_yo con una base FALSA (no toca tus chats reales).
Ejecutar: python tests/test_chat_privado.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import chat_private as cp, privacy, tools

checks = []


def check(name, ok):
    checks.append(ok)
    print(f"  [{'OK' if ok else 'FALLO'}] {name}")


now = datetime.now()
CHAT = [(now - timedelta(hours=h), h % 2 == 0, f"mensaje de prueba numero {h} largo suficiente") for h in range(20, 0, -1)]


def fake_query(sql, args=(), fetch="all", commit=False):
    if "ORDER BY e.embedding" in sql:
        return [("asi escribo yo",)]
    if "AND de_mi" in sql or "WHERE de_mi" in sql:
        return [(t,) for _, mine, t in CHAT if mine]
    return list(reversed(CHAT)) if "DESC" in sql else CHAT


cp.contacts._query = fake_query
cp.contacts.find = lambda name: [{"id": 7, "nombre": "Marta"}] if name.lower() == "marta" else ([{"id": 1, "nombre": "Luis A"}, {"id": 2, "nombre": "Luis B"}] if name == "luis" else [])
cp.embed = lambda text: [0.1] * 768

result = cp.resumir_chat("marta", 30)
check("resumir_chat marca el turno como privado y trae el chat", result["_privado"] is True and "mensaje de prueba" in result["chat"] and result["persona"] == "Marta")
check("el chat devuelto cabe en el limite", len(result["chat"]) <= cp.MAX_CHARS)
check("varios parecidos: pregunta en vez de adivinar", "varios" in cp.resumir_chat("luis") and "_privado" not in cp.resumir_chat("luis"))
check("sin contacto: lo dice", "nota" in cp.resumir_chat("nadie"))

draft = cp.redactar_como_yo("marta", "quedar el sabado")
check("redactar_como_yo es privado y da ejemplos, estilo y contacto_id", draft["_privado"] and draft["como_le_escribo"] and draft["contacto_id"] == 7 and draft["como_escribo_en_situaciones_parecidas"] == ["asi escribo yo"])
check("los rasgos de estilo son agregados, no mensajes", "longitud_media_caracteres" in draft["rasgos_de_mi_estilo"] and "mensaje de prueba" not in str(draft["rasgos_de_mi_estilo"]))
check("sin intencion, responde al ultimo mensaje", "responder al ultimo mensaje" in cp.redactar_como_yo("marta")["intencion"])

check("las dos herramientas estan registradas y son privadas", all(n in tools.FUNCTIONS and n in privacy.PRIVATE_TOOLS for n in ("resumir_chat", "redactar_como_yo")))
check("el resultado de ambas activa el modo local", privacy.is_private("otra_herramienta", result))

print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
sys.exit(0 if all(checks) else 1)
