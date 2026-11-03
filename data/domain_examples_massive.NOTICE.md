# Aviso de atribución

`domain_examples_massive.json` contiene frases seleccionadas del conjunto **MASSIVE**
(FitzGerald et al., 2022, Amazon Science), subconjunto `es-ES`, licencia **CC BY 4.0**
(https://creativecommons.org/licenses/by/4.0/).

- Fuente: https://huggingface.co/datasets/AmazonScience/massive (revisión f039ed54a45079b32092f4af7ff2f9584e09403c)
- Cambios: selección por intención, mapeo a los temas de Jarvis y eliminación de palabras de activación (Alexa, Olly...).
- Se regenera con `python scripts/import_massive.py --extra --per-domain=40`.
