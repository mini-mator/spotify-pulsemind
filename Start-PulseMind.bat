@echo off
setlocal EnableDelayedExpansion
title PulseMind - One-Click Bootstrap & Launcher
cd /d "%~dp0"

:: 1. If local .venv already exists, launch immediately via pythonw.exe
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "tray.py"
    exit /b 0
)

echo ================================================================
echo   PulseMind - First-Time Local Environment Setup
echo ================================================================

:: 2. Locate a Python 3.10+ interpreter on the machine
set "PY_CMD="
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
    if !ERRORLEVEL! equ 0 set "PY_CMD=py -3"
)

if not defined PY_CMD (
    for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" 2^>nul') do (
        set "PY_CMD="%%P""
    )
)

if not defined PY_CMD (
    python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
    if !ERRORLEVEL! equ 0 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [ERROR] Python 3.10+ was not found on this PC.
    echo Please install Python 3.11 or 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Creating isolated virtual environment (.venv)...
%PY_CMD% -m venv .venv
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/3] Installing PulseMind dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q

echo [3/3] Creating Desktop Shortcut & Launching PulseMind...
".venv\Scripts\python.exe" create_shortcut.py
start "" ".venv\Scripts\pythonw.exe" "tray.py"
echo Done! PulseMind is now running in your Windows System Tray.
timeout /t 3 >nul
