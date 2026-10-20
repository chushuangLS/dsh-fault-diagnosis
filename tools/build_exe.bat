@echo off
rem Build the desktop app into a distributable folder.
rem ASCII only: cmd.exe misreads UTF-8 Chinese in .bat files,
rem and the output folder name is Chinese, so we clear the whole dist dir
rem instead of referencing that name here.
cd /d "%~dp0.."

echo.
echo === Build desktop app (folder build) ===
echo.

where python >nul 2>&1
if not %errorlevel%==0 (
    echo [FAIL] python not found in PATH
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if not %errorlevel%==0 (
    echo PyInstaller not found, installing ...
    python -m pip install pyinstaller
)

echo Cleaning old output ...
if exist dist rmdir /s /q dist
if exist build\build_onedir rmdir /s /q build\build_onedir

python -m PyInstaller --noconfirm --distpath dist --workpath build tools\build_onedir.spec
if errorlevel 1 (
    echo.
    echo [FAIL] build failed
    pause
    exit /b 1
)

echo.
echo Copying current data\ into the bundle ...
python tools\bundle_data.py
if errorlevel 1 (
    echo [WARN] data copy failed, the app will start with empty data
)

echo.
echo === Done ===
echo Output folder: dist\
echo Ship the WHOLE folder, not just the exe inside it.
echo.
pause
