@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --name WiFiAudio --add-data "receiver.html;." --add-data "receiver.js;." --collect-all pyaudiowpatch --collect-all aiortc server.py
if errorlevel 1 exit /b 1
copy /y Start-Meeting.cmd dist\WiFiAudio\Start-Meeting.cmd >nul
copy /y README.md dist\WiFiAudio\README.md >nul
echo Built dist\WiFiAudio\WiFiAudio.exe. Keep its _internal directory beside it.
