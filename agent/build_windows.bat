@echo off
REM Usage: build_windows.bat https://api.yourdomain.com
REM Needs on Windows: Python 3.10+, Inno Setup 6 (iscc.exe on PATH or default location)
if "%~1"=="" (
  echo Usage: build_windows.bat https://your-server-url
  exit /b 1
)
echo {"api_url": "%~1"}> build_config.json
pip install certifi pyinstaller pystray pillow || exit /b 1
pyinstaller --onefile --noconsole --clean --name TallySyncAgent --add-data "build_config.json;." --collect-data certifi agent.py || exit /b 1
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC=iscc
%ISCC% installer.iss || exit /b 1
echo.
echo DONE: output\TallySyncSetup.exe  -> copy it to the server's downloads\ folder
