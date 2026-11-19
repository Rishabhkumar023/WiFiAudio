@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --name WiFiAudio --add-data "receiver.html;." --add-data "receiver.js;." --collect-all pyaudiowpatch --collect-all aiortc server.py
if errorlevel 1 exit /b 1
echo Built dist\WiFiAudio\WiFiAudio.exe. Keep its _internal directory beside it.
