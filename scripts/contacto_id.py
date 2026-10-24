"""Busca el id de un contacto para rellenar data/whatsapp_mapa.csv. Uso: python scripts/contacto_id.py nombre"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.contacts import find

for person in find(" ".join(sys.argv[1:])) or []:
    print(f'{person["id"]} | {person["nombre"]} | {person["empresa"]} | canales: {", ".join(person["canales"])}')
