@echo off
setlocal
cd /d "%~dp0"
title J.A.R.V.I.S. // Diagnostico de Modulo de Voz
color 0A

echo ========================================================
echo       PRUEBA Y DIAGNOSTICO DE VOZ LOCAL DE JARVIS
echo ========================================================
echo.

set "PY=python"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) else if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
)

echo [*] Ejecutando modulo de voz en primer plano...
"%PY%" "%~dp0jarvis_voice_local.py"
if errorlevel 1 (
    echo.
    echo [ERROR] El modulo de voz se cerro inesperadamente.
    pause
)
