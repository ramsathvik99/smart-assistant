@echo off
echo ============================================================
echo   SMART ASSISTANT - Live Environment Observer Validation
echo ============================================================
echo.
echo This will start the environment observer validation.
echo.
echo BEFORE pressing enter:
echo   1. Make sure Brave/Chrome is OPEN with YouTube active
echo   2. You should be watching a video (Video A)
echo   3. Keep this window visible alongside your browser
echo.
echo The validator will poll every 3 seconds and show state changes.
echo Switch apps, change videos, come back - it will track everything.
echo Press Ctrl+C when done to see the full history.
echo.
pause

cd /d "%~dp0"
python tools\live_env_validation.py
pause
