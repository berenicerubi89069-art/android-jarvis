@echo off
title Detener JARVIS
color 0C
echo ========================================================
echo       DETENIENDO TODOS LOS PROCESOS DE JARVIS
echo ========================================================
echo.
echo Cerrando instancias de Python y Pythonw en segundo plano...
taskkill /F /IM python.exe /IM pythonw.exe >nul 2>&1
echo.
echo [OK] Todos los procesos de JARVIS han sido detenidos limpiamente.
echo.
pause
