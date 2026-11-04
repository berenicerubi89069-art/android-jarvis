@echo off
setlocal
cd /d "%~dp0"
title J.A.R.V.I.S. // Master System
color 0B

echo ========================================================
echo       J.A.R.V.I.S. - SISTEMA OPERATIVO TACTICO
echo ========================================================
echo.

echo [*] Verificando entorno previo...
taskkill /F /IM pythonw.exe >nul 2>&1

set "PY=python"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) else if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
)

"%PY%" "%~dp0jarvis_main.py" %*
if errorlevel 1 (
    echo.
    echo [ADVERTENCIA] El sistema se detuvo con codigo de error.
    pause
)
