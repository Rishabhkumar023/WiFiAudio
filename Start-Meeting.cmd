@echo off
cd /d "%~dp0"
if exist "WiFiAudio.exe" (
  "WiFiAudio.exe" --meeting %*
) else (
  ".venv\Scripts\python.exe" server.py --meeting %*
)
pause
