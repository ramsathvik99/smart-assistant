@echo off
title Smart Assistant
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set PYTHONPATH=

cd /d "C:\Users\Ram Sathvik\OneDrive\Desktop\smart_assistant"
call venv\Scripts\activate

echo [ASSISTANT] Starting Smart Assistant...
python assistant.py
echo [ASSISTANT] Exited.
pause
