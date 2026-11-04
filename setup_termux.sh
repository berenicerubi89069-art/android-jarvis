#!/data/data/com.termux/files/usr/bin/bash
# ══════════════════════════════════════════════════════════════════
# J.A.R.V.I.S. — Instalador Automático para Android (Termux)
# ══════════════════════════════════════════════════════════════════
set -e

echo "╔══════════════════════════════════════════════════════╗"
echo "║   J.A.R.V.I.S. — INSTALACIÓN OPTIMIZADA PARA ANDROID║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

echo "[1/4] Actualizando repositorios y paquetes de Termux..."
pkg update -y && pkg upgrade -y

echo ""
echo "[2/4] Instalando herramientas del sistema (Python, Git, FFmpeg, MPV, Clang)..."
pkg install -y python git ffmpeg mpv termux-api clang libjpeg-turbo || true

echo ""
echo "[3/4] Solicitando permisos de almacenamiento (Acepte el diálogo en pantalla)..."
termux-setup-storage || true

echo ""
echo "[4/4] Instalando dependencias ligeras optimizadas para Android..."
python -m pip install --upgrade pip
if [ -f "requirements-android.txt" ]; then
    python -m pip install -r requirements-android.txt
else
    python -m pip install -r requirements.txt
fi

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo ""
        echo "[AVISO] Se ha creado el archivo .env desde .env.example."
        echo "Por favor, edítelo con: nano .env e ingrese sus claves API."
    fi
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo " ¡Instalación en Android completada exitosamente!"
echo " Para iniciar JARVIS ejecute:"
echo "   bash start_termux.sh"
echo "════════════════════════════════════════════════════════"
