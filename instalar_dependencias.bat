@echo off
REM ══════════════════════════════════════════════════════════════════
REM  J.A.R.V.I.S. — Instalador de Dependencias Python (Windows)
REM ══════════════════════════════════════════════════════════════════

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   J.A.R.V.I.S. — INSTALADOR DE DEPENDENCIAS        ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no encontrado en el PATH.
    echo  Instale Python 3.10+ marcando 'Add python.exe to PATH' desde https://python.org
    pause
    exit /b 1
)

echo  [1/3] Actualizando pip...
python -m pip install --upgrade pip

echo.
echo  [2/3] Instalando dependencias desde requirements.txt...
python -m pip install -r "%~dp0requirements.txt"

echo.
echo  [3/3] Verificando ffmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  [ADVERTENCIA] ffmpeg NO encontrado en el PATH.     ║
    echo  ║  ffmpeg permite convertir notas de voz OGG/WAV.     ║
    echo  ║  Descarguelo de: https://www.gyan.dev/ffmpeg/builds/  ║
    echo  ╚══════════════════════════════════════════════════════╝
) else (
    echo  [OK] ffmpeg detectado correctamente en el sistema.
)

echo.
echo  ========================================================
echo   Instalacion completada. Copie .env.example como .env
echo   y configure sus claves antes de iniciar el sistema.
echo  ========================================================
pause
