@echo off
cd /d C:\Users\Usuario\jarvis
call .venv\Scripts\activate.bat
uvicorn main:app --host 0.0.0.0 --port 3000