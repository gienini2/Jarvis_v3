@echo off
title Jarvis Chat
cd /d C:\Users\Usuario\jarvis
set PYTHONUTF8=1

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no encuentro .venv\Scripts\python.exe -- ejecuta esto desde C:\Users\Usuario\jarvis
    pause
    exit /b 1
)

echo Comprobando Ollama (embeddings/RAG + LLM local de reserva)...
ollama list >nul 2>&1 || (echo ERROR: Ollama no responde & pause & exit /b 1)

echo Ollama OK -- el LLM principal lo elige el router (Groq/NVIDIA/local)
echo.
.venv\Scripts\python.exe -m scripts.chat
echo.
echo (sesion terminada -- avisos de fondo, si los hubo, en logs\chat.log)
pause
