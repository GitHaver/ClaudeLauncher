@echo off
rem Launch the Claude Launcher GUI.
rem On first run this bootstraps a local virtual environment (.venv) and
rem installs dependencies into it, so the app always runs against a known-good
rem interpreter regardless of what Python is on PATH. Subsequent runs just
rem launch straight away, windowless.
rem
rem NOTE: the bootstrap steps are written with goto labels rather than one big
rem parenthesised if-block on purpose. Inside a ( ... ) block cmd expands
rem %PYCMD% at parse time (before :find_python has run), which would launch an
rem empty command. Flat, label-based flow expands variables at execution time.
setlocal
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VPYW=%VENV%\Scripts\pythonw.exe"

if exist "%VPY%" goto :launch

rem --- First run: create the venv and install dependencies ------------------
echo First run: creating virtual environment...
call :find_python
if errorlevel 1 goto :no_python

"%PYCMD%" -m venv "%VENV%"
if errorlevel 1 goto :venv_fail

echo Installing dependencies...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :deps_fail

rem --- Launch, windowless (pythonw always exists inside a venv) --------------
:launch
if exist "%VPYW%" (
    start "" "%VPYW%" "%~dp0main.py"
) else (
    start "" "%VPY%" "%~dp0main.py"
)
exit /b 0

rem --------------------------------------------------------------------------
:find_python
rem Locate a bootstrap interpreter. Prefer the Windows "py" launcher, then a
rem bare python / python3. Sets PYCMD on success.
where py >nul 2>&1
if not errorlevel 1 ( set "PYCMD=py" & exit /b 0 )
where python >nul 2>&1
if not errorlevel 1 ( set "PYCMD=python" & exit /b 0 )
where python3 >nul 2>&1
if not errorlevel 1 ( set "PYCMD=python3" & exit /b 0 )
exit /b 1

:no_python
echo.
echo ERROR: Could not find Python on your PATH ^(tried py, python, python3^).
echo Install Python 3.8+ from https://www.python.org/downloads/ and make sure
echo the "py" launcher or "python" works in a new terminal, then run this again.
goto :fail

:venv_fail
echo.
echo ERROR: Failed to create the virtual environment.
goto :fail

:deps_fail
echo.
echo ERROR: Failed to install dependencies.
echo Delete the .venv folder and try again once you have a network connection.
goto :fail

:fail
echo.
pause
exit /b 1
