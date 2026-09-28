@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Installation complete. Open Start_App.vbs.
pause
exit /b 0
:fail
echo Installation failed. Check Python and your internet connection, then try again.
pause
exit /b 1
