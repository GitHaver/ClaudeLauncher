@echo off
rem Run the launcher WITH a console window so tracebacks are visible.
rem Use this when run.bat's window closes unexpectedly and you need the error.
setlocal
cd /d "%~dp0"

set "VPY=%~dp0.venv\Scripts\python.exe"

if not exist "%VPY%" (
    echo Virtual environment not found.
    echo Run run.bat once first to create it, then use this to debug.
    echo.
    pause
    exit /b 1
)

"%VPY%" "%~dp0main.py"
echo.
echo (app exited with code %errorlevel%)
pause
