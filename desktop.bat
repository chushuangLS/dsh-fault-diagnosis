@echo off
rem Machine room diagnosis assistant - desktop window launcher
rem ASCII only on purpose: cmd.exe misreads UTF-8 Chinese in .bat files.
cd /d "%~dp0"

rem pythonw runs without a console window, so the app looks like a real
rem desktop program. Errors go to desktop-error.log instead of the screen.
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0desktop.py"
    exit /b 0
)

rem Fallback: pythonw missing, run with a console so problems stay visible.
python "%~dp0desktop.py"
if errorlevel 1 (
    echo.
    echo Startup failed. See desktop-error.log for details.
    pause
)
