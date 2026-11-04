#!/data/data/com.termux/files/usr/bin/bash
# ══════════════════════════════════════════════════════════════════
# J.A.R.V.I.S. — Lanzador para Android (Termux)
# ══════════════════════════════════════════════════════════════════
cd "$(dirname "$0")"

echo "========================================================"
echo "      J.A.R.V.I.S. - MÓDULO ANDROID (TERMUX)"
echo "========================================================"
echo ""

if [ ! -f ".env" ]; then
    echo "[ALERTA] Archivo .env no encontrado."
    echo "Cree su archivo .env o copie .env.example:"
    echo "  cp .env.example .env && nano .env"
    echo ""
fi

# En Android Termux, el módulo de voz de micrófono físico de PC se desactiva
# por defecto si no hay PyAudio compilado, pero el Bot de Telegram y el Puente OS
# funcionan al 100% recibiendo notas de voz y ejecutando acciones.
echo "[*] Iniciando J.A.R.V.I.S. optimizado para Android..."
python jarvis_main.py --no-voice "$@"
