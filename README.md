# ⚡ J.A.R.V.I.S. — Asistente Inteligente Táctico Multimodal
> **Sistema personal de inteligencia artificial inspirado en JARVIS (Iron Man / Mark LXXXV), con soporte táctico completo para Windows, Linux y optimizado para Android.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-orange.svg?logo=google)](https://aistudio.google.com/)
[![Telegram Bot](https://img.shields.io/badge/Mobile-Telegram%20Bot-2CA5E0.svg?logo=telegram)](https://telegram.org/)
[![PWA Ready](https://img.shields.io/badge/Android-PWA%20Ready-3DDC84.svg?logo=android)](https://web.dev/progressive-web-apps/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🌟 Visión General

**J.A.R.V.I.S.** es un ecosistema completo de asistente personal con arquitectura distribuida y multimodal:
1. **Consola Web Táctica (PWA / Mobile First)**: Interfaz futurista Stark con Esfera Holográfica 60 FPS, reconocimiento y síntesis de voz en navegador, base de datos local IndexedDB y gestión de archivos.
2. **Bot de Telegram 24/7**: Acceso desde cualquier smartphone con notas de voz de ida y vuelta (Gemini Multimodal + síntesis con voz española formal de Álvaro Neural), control remoto del sistema operativo y gestión de agenda.
3. **Módulo de Voz Local de Escritorio**: Escucha pasiva con palabra clave ("Jarvis") y respuestas en audio sintético en tiempo real.
4. **Puente Local OS (Bridge)**: Servidor HTTP ligero y multiplataforma que permite a la IA interactuar con el sistema de archivos, consultar estado del equipo (batería, almacenamiento, CPU) y sincronizar Google Calendar.

---

## 📱 ¿Cómo está optimizado para Android?

Este repositorio incluye tres vías de uso móvil optimizadas para el rendimiento y consumo de batería en teléfonos:

### 1. Progressive Web App (PWA) en tu Teléfono
- Compatible con **Google Chrome**, **Firefox** y **Samsung Internet** en Android.
- Al abrir `jarvis.html`, puedes pulsar el menú del navegador y seleccionar **"Instalar aplicación"** o **"Añadir a la pantalla de inicio"**.
- Se ejecuta en **pantalla completa** (sin barra de direcciones), con tema oscuro táctico, soporte para Safe Area / Notch, viewport dinámico (`dvh`) que no se rompe con el teclado virtual, y desbloqueo automático del sintetizador de voz táctil.

### 2. Bot de Telegram con Procesamiento en la Nube
- La app de Telegram en Android es el medio más ligero y eficiente para usar a JARVIS en movilidad.
- **Sin calentamiento ni drenaje de batería**: A diferencia de los modelos pesados de Whisper locales, las notas de voz que envías se procesan directamente con la capacidad multimodal de **Google Gemini** en la nube en milisegundos.
- JARVIS te responde directamente con una **nota de voz** usando la voz neuronal de Álvaro (`es-ES-AlvaroNeural`).

### 3. Ejecución Nativa de Backend en Termux (Android)
- Si deseas ejecutar el servidor o el bot directamente dentro de tu teléfono Android, se incluyen:
  - `setup_termux.sh`: Script de instalación automática de 1 paso.
  - `start_termux.sh`: Lanzador optimizado para arquitectura ARM.
  - `requirements-android.txt`: Dependencias ultra-ligeras sin necesidad de compiladores pesados de C++.
  - Soporte para diagnósticos de batería y comandos nativos (`termux-battery-status`, `termux-open`).

---

## 📁 Estructura del Proyecto

```
JARVIS_Android/
├── jarvis.html               # Consola táctica Web UI (PWA)
├── style.css                 # Estilos tácticos futuristas con soporte móvil
├── app.js                    # Motor cliente JavaScript (IndexedDB, Web Speech, Canvas)
├── manifest.json             # Manifiesto PWA para instalación en Android
├── sw.js                     # Service Worker para ejecución offline y caché
├── jarvis.ico                # Ícono de escritorio
├── jarvis.svg                # Ícono vectorial de alta resolución para móviles
│
├── jarvis_main.py            # Orquestador maestro multiplataforma
├── jarvis_telegram.py        # Bot de Telegram asíncrono con soporte de audio
├── jarvis_bridge.py          # Puente HTTP multiplataforma (Windows / Android / Linux)
├── jarvis_voice_local.py     # Asistente de micrófono local con activación por voz
├── jarvis_calendar.py        # Módulo de integración con Google Calendar API
├── jarvis_bridge_client.py   # Cliente WebSocket para puente nube (opcional)
│
├── Iniciar_JARVIS.bat        # Lanzador para Windows
├── Detener_JARVIS.bat        # Detiene todos los procesos en Windows
├── instalar_dependencias.bat # Instalador de librerías para Windows
├── probar_voz.bat            # Diagnóstico de voz local en Windows
│
├── setup_termux.sh           # Instalador automático para Android (Termux)
├── start_termux.sh           # Lanzador rápido para Android (Termux)
│
├── requirements.txt          # Dependencias universales / PC
├── requirements-android.txt  # Dependencias ligeras para Android
├── .env.example              # Plantilla de variables de entorno (sin secretos)
├── .gitignore                # Reglas estrictas para GitHub (protege tus claves)
├── LICENSE                   # Licencia MIT
└── README.md                 # Documentación del sistema
```

---

## 🚀 Guía de Instalación y Uso

### A. Uso en Windows (PC)

1. **Clonar el repositorio**:
   ```bash
   git clone https://github.com/tu-usuario/tu-repositorio.git
   cd tu-repositorio
   ```

2. **Instalar dependencias**:
   Ejecute con doble clic `instalar_dependencias.bat` o por consola:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar credenciales**:
   - Copie `.env.example` como `.env`:
     ```cmd
     copy .env.example .env
     ```
   - Abra `.env` y coloque su `GEMINI_API_KEY` (gratuita en [Google AI Studio](https://aistudio.google.com/)) y su `TELEGRAM_BOT_TOKEN`.

4. **Iniciar el sistema**:
   - Doble clic en `Iniciar_JARVIS.bat`.
   - Para abrir la consola web táctica, abra `jarvis.html` en Chrome o Edge.

---

### B. Uso en Android (Termux)

1. Descargue e instale **Termux** desde F-Droid o GitHub.
2. Abra Termux y ejecute:
   ```bash
   pkg install git -y
   git clone https://github.com/tu-usuario/tu-repositorio.git
   cd tu-repositorio
   bash setup_termux.sh
   ```
3. Configure su archivo `.env`:
   ```bash
   nano .env
   ```
   *(Pegue su clave de Gemini y token de Telegram; guarde con `Ctrl+O` y salga con `Ctrl+X`)*.
4. Inicie JARVIS en Android:
   ```bash
   bash start_termux.sh
   ```

---

## 🤖 Configuración del Bot de Telegram

1. Inicie una conversación con [@BotFather](https://t.me/BotFather) en Telegram y use `/newbot` para obtener su `TELEGRAM_BOT_TOKEN`.
2. Hable con [@userinfobot](https://t.me/userinfobot) en Telegram para conocer su ID numérico y colóquelo en `TELEGRAM_AUTHORIZED_USER_ID`.
3. Inicie JARVIS: ¡ahora puede enviarle textos o notas de voz a su bot desde cualquier lugar del mundo y JARVIS le responderá con voz y ejecutará sus órdenes!

---

## 🛡️ Seguridad y Subida a GitHub

Este repositorio está preconfigurado para subirse a GitHub con total seguridad:
- El archivo `.gitignore` **bloquea automáticamente** cualquier archivo sensible como `.env`, `credentials.json`, `token.json` o audios temporales.
- **NUNCA** suba su archivo `.env` personal ni sus claves privadas al repositorio.

### Pasos para subir a GitHub:

```bash
git init
git add .
git commit -m "feat: inicializar JARVIS Universal optimizado para PC y Android"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Consulte el archivo [LICENSE](LICENSE) para más detalles.
