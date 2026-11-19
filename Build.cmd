@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" build_download.py --licenses-only
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name WiFiAudio --add-data "receiver.html;." --add-data "receiver.js;." --add-data "install-driver.ps1;." --add-data ".local/licenses;THIRD_PARTY_LICENSES" --collect-all pyaudiowpatch --collect-all aiortc desktop.py
if errorlevel 1 exit /b 1
echo Built dist\WiFiAudio.exe. This single file includes its runtime and desktop interface.
