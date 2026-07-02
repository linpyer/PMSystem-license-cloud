@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" set "PYTHON=python"

echo [1/2] Checking Python files...
"%PYTHON%" -m compileall main.py app
if errorlevel 1 (
    echo Python compile check failed.
    exit /b 1
)

echo [2/2] Building Windows executable with PyInstaller...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onedir ^
    --name "电商打包发货监控溯源系统" ^
    --icon "app\assets\logo.ico" ^
    --add-data "app\assets;app\assets" ^
    --hidden-import sqlite3 ^
    --hidden-import requests ^
    --hidden-import pyttsx3 ^
    --hidden-import pyttsx3.drivers ^
    --hidden-import pyttsx3.drivers.sapi5 ^
    main.py

if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

echo Build completed: dist\电商打包发货监控溯源系统\电商打包发货监控溯源系统.exe
endlocal
