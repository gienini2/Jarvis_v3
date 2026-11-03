"""Informe de modelos en dos grupos (locales / nube) a partir de las evaluaciones y del uso real de las ultimas 24 h.
Uso: python scripts/informe_modelos.py     (escribe tambien data/informe_modelos.md)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import model_report

text = model_report.markdown(model_report.build())
(Path(__file__).resolve().parents[1] / "data" / "informe_modelos.md").write_text(text, encoding="utf-8")
print(text)
