# Jarvis — AGENTS.md

**La fuente de verdad del proyecto es [`CLAUDE.md`](CLAUDE.md).** Léelo primero.
Este fichero solo recoge lo específico para agentes; todo lo demás (arquitectura,
cascada de LLMs, memoria, dominios, pendientes) vive en CLAUDE.md para no mantener
dos documentos que se desincronizan (era justo el problema que teníamos).

## Reglas rápidas para trabajar en este repo
- Sistema **monousuario** (Juan Pablo). Orientar fixes a lo que le afecta en ejecución.
- Selección de LLM: **config-driven** en `config/providers.json`, router en
  `core/llm_router.py`. Cascada real: **Groq → NVIDIA → Ollama**. No hay Anthropic
  ni Mem0 en el código, por mucho que digan docs antiguos.
- **No hardcodear IDs de modelo.** Leerlos de `providers.json` o `config/settings.py`.
- Tras tocar modelos/proveedores, correr `python scripts/check_models.py` (verifica
  en vivo que los modelos configurados siguen existiendo).
- Python 3.11+, imports absolutos desde la raíz, async/await en FastAPI.
- `.env` nunca al repo. Config vía `config/settings.py` (Pydantic).
- No heredocs en bash (corrupción de terminal). Usar SCP o echo line-by-line.
- Postgres: DB real `jarvis`, conectar con `-h 127.0.0.1`.

## Antes de dar algo por hecho
Muchos comentarios y docs traen fechas y notas de "pendiente de probar en real".
Si vas a afirmar que algo funciona, verifícalo contra el código actual, no contra
la documentación.
