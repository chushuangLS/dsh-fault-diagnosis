@echo off
setlocal

rem ============================================================
rem  One-click launcher for the machine-room diagnosis assistant
rem  Double-click this file to start the server and open the browser.
rem
rem  NOTE: keep this file ASCII-only.
rem  cmd.exe reads .bat in the system ANSI codepage; mixing UTF-8
rem  Chinese with `chcp` makes cmd lose its place and misparse later
rem  lines. All Chinese output lives in tools\start_server.ps1,
rem  which is saved as UTF-8 with BOM so PowerShell 5.1 reads it right.
rem ============================================================

set "PS1=%~dp0tools\start_server.ps1"

if not exist "%PS1%" (
    echo.
    echo   [X] Startup script not found:
    echo       %PS1%
    echo.
    pause
    exit /b 1
)

rem Prefer PowerShell 7 (pwsh); fall back to the built-in powershell 5.1
where pwsh >nul 2>nul
if %errorlevel%==0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
)

echo.
pause
