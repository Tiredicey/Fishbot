@echo off
title FishBot Builder
color 0A
cd /d "%~dp0"

echo.
echo  ====================================================
echo   FishBot -- One-Click Build System
echo   All files must be in the same folder as this bat.
echo  ====================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [ERROR] Python not found in PATH.
    echo  Download Python 3.11 from https://python.org/downloads
    echo  Tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

python --version
echo.
echo  Detected folder: %~dp0
echo  Starting build orchestrator...
echo.

python "%~dp0build.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Build failed. See build.log for details.
    echo  Common fixes:
    echo    - Run this .bat as Administrator
    echo    - Delete .fishbot_venv\ and retry
    echo    - Try Python 3.11 from python.org if deps fail
    echo.
    pause
    exit /b 1
)

echo.
echo  Build finished. Press any key to open dist\ folder...
pause >nul
explorer "%~dp0dist"