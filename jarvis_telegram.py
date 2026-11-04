#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Módulo de Bot de Telegram
==========================================
Bot de Telegram completamente asíncrono que integra el asistente JARVIS
con la API de Google Gemini, transcripción de voz mediante ``faster-whisper``,
síntesis de voz con ``edge-tts`` y el puente local del sistema operativo.

Dependencias externas::

    pip install python-telegram-bot[all] aiohttp faster-whisper edge-tts

Variables de entorno requeridas::

    TELEGRAM_BOT_TOKEN              — Token del bot proporcionado por @BotFather.
    TELEGRAM_AUTHORIZED_USER_ID     — ID numérico del usuario autorizado.
    GEMINI_API_KEY                  — Clave de API de Google Gemini.
    GEMINI_MODEL                    — Modelo de Gemini (por defecto ``gemini-flash-lite-latest``).

Uso::

    python jarvis_telegram.py

Autor: Sistema JARVIS
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Final

import aiohttp
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Configuración de logging estructurado
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger: Final = logging.getLogger("jarvis.telegram")

# ---------------------------------------------------------------------------
# Constantes globales
# ---------------------------------------------------------------------------
BRIDGE_HOST: Final[str] = "http://127.0.0.1:8888"
BRIDGE_ACTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[BRIDGE_ACTION:\s*(\{.*?\})\]", re.DOTALL
)
MAX_HISTORY_LENGTH: Final[int] = 10
EDGE_TTS_VOICE: Final[str] = "es-ES-AlvaroNeural"
WHISPER_MODEL: Final[str] = "base"
WHISPER_LANGUAGE: Final[str] = "es"
GEMINI_BASE_URL: Final[str] = (
    "https://generativelanguage.googleapis.com/v1beta"
)


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent if BASE_DIR.name == "telegram" else BASE_DIR
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _find_ffmpeg() -> str:
    """Localiza el ejecutable de ffmpeg en el sistema evitando problemas de permisos en WindowsApps."""
    which_path = shutil.which("ffmpeg")
    if which_path and os.path.isfile(which_path) and "WindowsApps" not in which_path:
        return which_path

    # Buscar en WinGet Packages
    user_home = Path(os.path.expanduser("~"))
    winget_dir = user_home / "AppData/Local/Microsoft/WinGet/Packages"
    if winget_dir.is_dir():
        for p in winget_dir.glob("**/ffmpeg.exe"):
            if p.is_file():
                return str(p)

    # Buscar en Program Files
    for pf in ("C:/Program Files", "C:/Program Files (x86)"):
        pf_dir = Path(pf)
        if pf_dir.is_dir():
            for p in pf_dir.glob("**/ffmpeg.exe"):
                if p.is_file():
                    return str(p)

    return which_path or "ffmpeg"


def _load_env_file() -> None:
    """Carga variables desde el archivo .env ubicado en la raíz del proyecto."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v

_load_env_file()


# ---------------------------------------------------------------------------
# Dataclass de configuración
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class JarvisConfig:
    """Configuración inmutable del bot cargada desde variables de entorno."""

    bot_token: str
    authorized_user_id: int
    gemini_api_key: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> JarvisConfig:
        """Construye la configuración a partir de variables de entorno.

        Raises:
            SystemExit: Si falta alguna variable de entorno obligatoria.
        """
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        auth_user = os.getenv("TELEGRAM_AUTHORIZED_USER_ID", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

        errores: list[str] = []
        if not bot_token:
            errores.append("TELEGRAM_BOT_TOKEN")
        if not auth_user:
            errores.append("TELEGRAM_AUTHORIZED_USER_ID")
        if not gemini_key:
            errores.append("GEMINI_API_KEY")

        if errores:
            logger.critical(
                "Variables de entorno faltantes: %s", ", ".join(errores)
            )
            sys.exit(1)

        return cls(
            bot_token=bot_token,
            authorized_user_id=int(auth_user),
            gemini_api_key=gemini_key,
            gemini_model=gemini_model,
        )


# ---------------------------------------------------------------------------
# Instrucción de sistema para Gemini (personalidad JARVIS)
# ---------------------------------------------------------------------------
def _build_system_instruction() -> str:
    """Genera la instrucción de sistema replicando la personalidad del app.js."""
    return (
        "Eres J.A.R.V.I.S., el asistente de inteligencia artificial personal "
        "táctico inspirado en el concepto de JARVIS.\n"
        "Tu personalidad es la de un mayordomo de élite: sumamente elegante, "
        "respetuoso, directo, inteligente, culto, refinado y sin rodeos "
        "innecesarios.\n"
        "Hablas y respondes SIEMPRE en español de manera impecable y formal.\n"
        "Te diriges al usuario habitualmente como «Señor».\n\n"
        "NORMAS ESTRICTAS DE RESPUESTA:\n"
        "1. Sé conciso y eficiente. Proporciona soluciones directas con el "
        "código o análisis necesario, evitando introducciones o despedidas "
        "vacías.\n"
        "2. Si una tarea no es técnicamente posible, indícalo claramente con "
        "honestidad técnica; jamás inventes ni simules capacidades ficticias.\n"
        "3. El usuario se comunica contigo a través de Telegram; adapta la "
        "extensión de tus respuestas al formato de mensajería.\n\n"
        "CAPACIDADES DEL PUENTE LOCAL OS Y GOOGLE CALENDAR:\n"
        "Si el usuario te pide expresamente interactuar con su computadora "
        "(listar archivos locales, leer archivos locales, escribir/guardar "
        "archivos locales, abrir programas de Windows o ver diagnósticos del "
        "sistema), o gestionar su Google Calendar (agenda de hoy, próximos eventos, agendar citas), "
        "puedes emitir una directiva en tu respuesta con la siguiente sintaxis exacta:\n"
        '[BRIDGE_ACTION: {"action": "list_files", "params": {"path": ""}}]\n'
        '[BRIDGE_ACTION: {"action": "read_file", "params": {"filename": "nombre_archivo"}}]\n'
        '[BRIDGE_ACTION: {"action": "write_file", "params": {"filename": "nombre_archivo", "content": "contenido"}}]\n'
        '[BRIDGE_ACTION: {"action": "open_item", "params": {"target": "notepad.exe"}}]\n'
        '[BRIDGE_ACTION: {"action": "system_diagnostics", "params": {}}]\n'
        '[BRIDGE_ACTION: {"action": "calendar_today", "params": {}}]\n'
        '[BRIDGE_ACTION: {"action": "calendar_upcoming", "params": {"max_results": 5}}]\n'
        '[BRIDGE_ACTION: {"action": "calendar_create", "params": {"summary": "Título", "start_time": "AAAA-MM-DD HH:MM"}}]\n'
        "La consola procesará automáticamente esta directiva contra el "
        "servidor local seguro si el puente jarvis_bridge.py está activo."
    )


# ---------------------------------------------------------------------------
# Decorador de autorización
# ---------------------------------------------------------------------------
def authorized_only(func):
    """Decorador que restringe el acceso al usuario autorizado.

    Si el usuario no está autorizado, responde con un mensaje formal de
    rechazo con la personalidad de JARVIS.
    """

    @wraps(func)
    async def wrapper(
        self: "JarvisTelegramBot",
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> Any:
        user_id = update.effective_user.id if update.effective_user else None
        if user_id != self.config.authorized_user_id:
            logger.warning(
                "Acceso denegado al usuario no autorizado: %s (%s)",
                update.effective_user.full_name if update.effective_user else "Desconocido",
                user_id,
            )
            await update.message.reply_text(
                "⛔ Lamento informarle que no poseo autorización para "
                "atender solicitudes de usuarios no registrados en mi "
                "protocolo de seguridad.\n\n"
                "Le sugiero contactar al administrador del sistema si "
                "considera que esto es un error.\n\n"
                "— J.A.R.V.I.S.",
            )
            return None
        return await func(self, update, context)

    return wrapper


# ---------------------------------------------------------------------------
# Cliente del puente local
# ---------------------------------------------------------------------------
class BridgeClient:
    """Cliente HTTP asíncrono para el puente local JARVIS (jarvis_bridge.py)."""

    def __init__(self, base_url: str = BRIDGE_HOST) -> None:
        """Inicializa el cliente del puente.

        Args:
            base_url: URL base del servidor del puente.
        """
        self._base_url = base_url

    async def health_check(self) -> dict[str, Any]:
        """Verifica el estado de salud del puente.

        Returns:
            Diccionario con el estado del puente o información del error.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        data["online"] = True
                        return data
                    return {"online": False, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            return {"online": False, "error": str(exc)}

    async def execute_action(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Ejecuta una acción contra el puente local.

        Args:
            action: Nombre de la acción a ejecutar.
            params: Parámetros opcionales de la acción.

        Returns:
            Resultado de la acción o diccionario con información del error.
        """
        payload = {"action": action, "params": params or {}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/action",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    return await resp.json()
        except Exception as exc:
            logger.error("Error ejecutando acción del puente '%s': %s", action, exc)
            return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Cliente de la API REST de Gemini
# ---------------------------------------------------------------------------
class GeminiClient:
    """Cliente HTTP asíncrono para la API REST de Google Gemini."""

    def __init__(self, api_key: str, model: str) -> None:
        """Inicializa el cliente de Gemini.

        Args:
            api_key: Clave de API de Google Gemini.
            model: Identificador del modelo a utilizar.
        """
        self._api_key = api_key
        self._model = model
        self._system_instruction = _build_system_instruction()

    async def generate(
        self, history: list[dict[str, str]]
    ) -> str:
        """Genera una respuesta conversacional usando el historial con reintentos y fallback.

        Args:
            history: Lista de turnos ``{"role": "user"|"model", "text": ...}``.

        Returns:
            Texto de la respuesta generada por el modelo.

        Raises:
            RuntimeError: Si la API devuelve un error o respuesta vacía tras reintentos.
        """
        # Modelos a intentar en orden de prioridad
        models_to_try = [self._model]
        for fallback in ("gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        # Construir los contenidos del historial
        contents: list[dict[str, Any]] = []
        for turn in history:
            role = "model" if turn["role"] == "model" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": turn["text"]}],
            })

        payload = {
            "systemInstruction": {
                "parts": [{"text": self._system_instruction}],
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.6,
                "maxOutputTokens": 3000,
            },
        }

        last_error: Exception | None = None

        async with aiohttp.ClientSession() as session:
            for current_model in models_to_try:
                endpoint = (
                    f"{GEMINI_BASE_URL}/models/{current_model}:generateContent"
                    f"?key={self._api_key}"
                )
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    try:
                        async with session.post(
                            endpoint,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=60),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                try:
                                    candidate = data["candidates"][0]
                                    parts = candidate["content"]["parts"]
                                    return "".join(p.get("text", "") for p in parts)
                                except (KeyError, IndexError) as exc:
                                    logger.error("Respuesta inesperada de Gemini: %s", data)
                                    raise RuntimeError(
                                        "La respuesta de Gemini no contiene datos legibles."
                                    ) from exc

                            error_body = await resp.text()
                            logger.warning(
                                "Gemini (%s) HTTP %d (intento %d/%d): %s",
                                current_model, resp.status, attempt, max_retries, error_body
                            )

                            if resp.status in (503, 429, 500, 502, 504):
                                last_error = RuntimeError(f"HTTP {resp.status}: {error_body}")
                                if attempt < max_retries:
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                                break
                            else:
                                raise RuntimeError(
                                    f"La API de Gemini devolvió estado HTTP {resp.status}."
                                )

                    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        logger.warning(
                            "Error de conexión con Gemini (%s, intento %d/%d): %s",
                            current_model, attempt, max_retries, exc
                        )
                        last_error = exc
                        if attempt < max_retries:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        break

        raise RuntimeError(
            f"No fue posible obtener respuesta de Gemini tras reintentos y modelos de respaldo: {last_error}"
        )

    async def generate_with_audio(
        self,
        history: list[dict[str, str]],
        audio_bytes: bytes,
        mime_type: str = "audio/wav",
    ) -> str:
        """Procesa una nota de voz directamente con la capacidad multimodal de Gemini.

        Gemini escucha el audio directamente, lo transcribe mentalmente y genera
        la respuesta con la personalidad de JARVIS y directivas si aplican.
        """
        models_to_try = [self._model]
        for fallback in ("gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-flash-latest"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        contents: list[dict[str, Any]] = []
        for turn in history[-6:]:
            role = "model" if turn["role"] == "model" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": turn["text"]}],
            })

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        contents.append({
            "role": "user",
            "parts": [
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": audio_b64,
                    }
                },
                {
                    "text": (
                        "El usuario te ha enviado esta nota de voz. "
                        "Escúchala atentamente y responde directamente con tu personalidad de J.A.R.V.I.S. "
                        "NO repitas ni transcribas lo que el usuario dijo. Solo da tu respuesta.\n"
                        "Si el usuario pide interactuar con su computadora o con su calendario, emite la directiva [BRIDGE_ACTION: ...] respectiva."
                    )
                },
            ],
        })

        payload = {
            "systemInstruction": {"parts": [{"text": self._system_instruction}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 3000},
        }

        last_error: Exception | None = None
        async with aiohttp.ClientSession() as session:
            for current_model in models_to_try:
                endpoint = (
                    f"{GEMINI_BASE_URL}/models/{current_model}:generateContent?key={self._api_key}"
                )
                for attempt in range(1, 3):
                    try:
                        async with session.post(
                            endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=45)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                candidates = data.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    text = "".join(p.get("text", "") for p in parts if "text" in p)
                                    if text:
                                        return text
                                break
                            text_err = await resp.text()
                            last_error = RuntimeError(f"HTTP {resp.status}: {text_err[:150]}")
                            if resp.status in (429, 500, 502, 503, 504) and attempt < 2:
                                await asyncio.sleep(2.0)
                                continue
                            break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2:
                            await asyncio.sleep(1.5)
                            continue
                        break

        raise RuntimeError(f"Fallo al procesar audio en Gemini: {last_error}")


# ---------------------------------------------------------------------------
# Motor de voz: transcripción (Whisper) y síntesis (Edge TTS)
# ---------------------------------------------------------------------------
class VoiceEngine:
    """Motor de procesamiento de voz: transcripción y síntesis."""

    def __init__(self) -> None:
        """Inicializa el motor de voz y carga el modelo Whisper."""
        self._whisper_model: Any | None = None
        self._whisper_lock = asyncio.Lock()

    async def _ensure_whisper_loaded(self) -> None:
        """Carga el modelo Whisper de forma diferida y segura para concurrencia."""
        if self._whisper_model is not None:
            return

        async with self._whisper_lock:
            # Doble verificación tras adquirir el bloqueo
            if self._whisper_model is not None:
                return

            logger.info(
                "Cargando modelo faster-whisper '%s'...", WHISPER_MODEL
            )
            # La carga es síncrona; se ejecuta en un hilo para no bloquear
            loop = asyncio.get_running_loop()
            try:
                self._whisper_model = await loop.run_in_executor(
                    None, self._load_whisper_model
                )
                logger.info("Modelo faster-whisper cargado correctamente.")
            except Exception as exc:
                logger.warning("faster-whisper no cargó (%s). Usando motor SpeechRecognition nativo.", exc)
                import speech_recognition as sr
                self._whisper_model = sr.Recognizer()

    @staticmethod
    def _load_whisper_model() -> Any:
        from faster_whisper import WhisperModel
        return WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )

    async def transcribe(self, wav_path: str) -> str:
        await self._ensure_whisper_loaded()
        loop = asyncio.get_running_loop()

        if hasattr(self._whisper_model, "transcribe"):
            segments, _info = await loop.run_in_executor(
                None,
                lambda: self._whisper_model.transcribe(
                    wav_path,
                    language=WHISPER_LANGUAGE,
                    beam_size=5,
                ),
            )
            text_parts: list[str] = await loop.run_in_executor(
                None, lambda: [seg.text.strip() for seg in segments]
            )
            return " ".join(text_parts).strip()
        else:
            import speech_recognition as sr
            def _transcribe():
                with sr.AudioFile(wav_path) as source:
                    audio = self._whisper_model.record(source)
                    return self._whisper_model.recognize_google(audio, language="es-ES")
            try:
                return await loop.run_in_executor(None, _transcribe)
            except Exception as e:
                logger.error("Error transcribiendo audio con SpeechRecognition: %s", e)
                return "No fue posible comprender la nota de voz."

    @staticmethod
    async def synthesize(text: str, output_path: str) -> None:
        """Sintetiza texto a un archivo MP3 usando Edge TTS.

        Args:
            text: Texto a convertir en voz.
            output_path: Ruta absoluta del archivo MP3 de salida.
        """
        import edge_tts  # type: ignore[import-untyped]

        # Limpiar markdown básico para voz más natural
        clean = re.sub(r"```[\s\S]*?```", "Bloque de código omitido.", text)
        clean = re.sub(r"`([^`]+)`", r"\1", clean)
        clean = re.sub(r"[*_#]", "", clean)
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
        clean = clean.strip()

        if not clean:
            clean = "No hay contenido audible para reproducir."

        communicate = edge_tts.Communicate(clean, EDGE_TTS_VOICE)
        await communicate.save(output_path)

    @staticmethod
    async def convert_oga_to_wav(oga_path: str, wav_path: str) -> bool:
        """Convierte un archivo OGA/Audio a WAV usando ffmpeg localizado en el sistema."""
        ffmpeg_bin = _find_ffmpeg()
        try:
            process = await asyncio.create_subprocess_exec(
                ffmpeg_bin,
                "-y",
                "-i", oga_path,
                "-ar", "16000",
                "-ac", "1",
                "-sample_fmt", "s16",
                wav_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await process.communicate()
            if process.returncode != 0:
                logger.warning("ffmpeg return code %d: %s", process.returncode, stderr.decode(errors="replace")[:100])
                return False
            return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0
        except Exception as exc:
            logger.warning("Fallo al ejecutar ffmpeg (%s): %s", ffmpeg_bin, exc)
            return False


# ---------------------------------------------------------------------------
# Bot principal de Telegram
# ---------------------------------------------------------------------------
class JarvisTelegramBot:
    """Bot de Telegram del sistema J.A.R.V.I.S.

    Gestiona comandos, mensajes de texto, notas de voz y la integración
    con Gemini, el puente local y los motores de voz.
    """

    def __init__(self, config: JarvisConfig) -> None:
        """Inicializa el bot con la configuración proporcionada.

        Args:
            config: Configuración inmutable del bot.
        """
        self.config = config
        self._gemini = GeminiClient(config.gemini_api_key, config.gemini_model)
        self._bridge = BridgeClient()
        self._voice = VoiceEngine()
        self._history: dict[int, list[dict[str, str]]] = defaultdict(list)

    # -- Gestión de memoria conversacional ----------------------------------

    def _add_to_history(
        self, user_id: int, role: str, text: str
    ) -> None:
        """Añade un turno al historial conversacional con ventana deslizante.

        Args:
            user_id: Identificador del usuario.
            role: Rol del turno (``"user"`` o ``"model"``).
            text: Contenido textual del turno.
        """
        self._history[user_id].append({"role": role, "text": text})
        # Ventana deslizante: mantener solo los últimos N mensajes
        if len(self._history[user_id]) > MAX_HISTORY_LENGTH:
            self._history[user_id] = self._history[user_id][
                -MAX_HISTORY_LENGTH:
            ]

    def _get_history(self, user_id: int) -> list[dict[str, str]]:
        """Obtiene el historial conversacional del usuario.

        Args:
            user_id: Identificador del usuario.

        Returns:
            Lista de turnos conversacionales.
        """
        return self._history[user_id]

    # -- Procesamiento de acciones del puente --------------------------------

    async def _process_bridge_actions(self, text: str) -> str:
        """Detecta y ejecuta directivas ``[BRIDGE_ACTION: {...}]`` en el texto.

        Cada directiva encontrada se ejecuta contra el puente local y su
        resultado se añade al texto de respuesta.

        Args:
            text: Texto que puede contener directivas de puente.

        Returns:
            Texto original con los resultados de las acciones añadidos.
        """
        matches = BRIDGE_ACTION_PATTERN.findall(text)
        if not matches:
            return text

        result_text = text
        for match_json in matches:
            try:
                action_data = json.loads(match_json)
                action = action_data.get("action", "")
                params = action_data.get("params", {})

                logger.info("Ejecutando acción del puente: %s", action)
                bridge_result = await self._bridge.execute_action(action, params)

                # Formatear el resultado para el usuario
                if action.startswith("calendar_") and bridge_result.get("success") and bridge_result.get("formatted"):
                    result_text += f"\n\n{bridge_result.get('formatted')}"
                elif action.startswith("calendar_") and bridge_result.get("success") and bridge_result.get("event"):
                    ev = bridge_result.get("event", {})
                    result_text += f"\n\n✅ Evento agendado en Google Calendar: *{ev.get('summary')}*"
                else:
                    result_formatted = json.dumps(
                        bridge_result, ensure_ascii=False, indent=2
                    )
                    result_text += (
                        f"\n\n📡 *Resultado del puente — `{action}`*:\n"
                        f"```json\n{result_formatted}\n```"
                    )
            except json.JSONDecodeError:
                logger.warning("JSON inválido en BRIDGE_ACTION: %s", match_json)
                result_text += (
                    "\n\n⚠️ Error: directiva del puente con formato JSON inválido."
                )
            except Exception as exc:
                logger.error("Error procesando BRIDGE_ACTION: %s", exc)
                result_text += (
                    f"\n\n⚠️ Error ejecutando la acción del puente: {exc}"
                )

        return result_text

    # -- Generación de respuesta con Gemini ----------------------------------

    async def _generate_response(
        self, user_id: int, user_text: str
    ) -> str:
        """Envía el texto al modelo Gemini y procesa la respuesta.

        Registra el turno del usuario y del modelo en el historial,
        y ejecuta cualquier acción del puente embebida en la respuesta.

        Args:
            user_id: Identificador del usuario.
            user_text: Mensaje del usuario.

        Returns:
            Texto de la respuesta completa (incluidos resultados del puente).
        """
        self._add_to_history(user_id, "user", user_text)

        try:
            response_text = await self._gemini.generate(
                self._get_history(user_id)
            )
        except RuntimeError as exc:
            logger.error("Error generando respuesta de Gemini: %s", exc)
            response_text = (
                "Lamento informarle, Señor, que he experimentado una "
                f"anomalía al contactar con el núcleo de procesamiento: {exc}"
            )

        # Ejecutar acciones del puente si las hay
        response_text = await self._process_bridge_actions(response_text)

        self._add_to_history(user_id, "model", response_text)
        return response_text

    # -- Envío seguro de mensajes largos ------------------------------------

    @staticmethod
    async def _safe_reply(
        update: Update, text: str, parse_mode: str | None = ParseMode.MARKDOWN
    ) -> None:
        """Envía una respuesta dividiéndola si excede el límite de Telegram.

        Telegram permite un máximo de ~4096 caracteres por mensaje. Este
        método divide el texto en fragmentos seguros.

        Args:
            update: Objeto de actualización de Telegram.
            text: Texto completo a enviar.
            parse_mode: Modo de parseo de Telegram.
        """
        max_len = 4000  # Margen de seguridad bajo el límite de 4096
        if len(text) <= max_len:
            try:
                await update.message.reply_text(
                    text, parse_mode=parse_mode
                )
            except Exception:
                # Reintento sin Markdown si falla el parseo
                await update.message.reply_text(text, parse_mode=None)
            return

        # Dividir por líneas para no cortar a mitad de frase
        chunks: list[str] = []
        current_chunk = ""
        for line in text.split("\n"):
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += ("\n" + line) if current_chunk else line

        if current_chunk:
            chunks.append(current_chunk)

        for chunk in chunks:
            try:
                await update.message.reply_text(
                    chunk, parse_mode=parse_mode
                )
            except Exception:
                await update.message.reply_text(chunk, parse_mode=None)

    # -- Manejadores de comandos --------------------------------------------

    @authorized_only
    async def cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /start — mensaje de bienvenida JARVIS."""
        welcome = (
            "🎩 *J.A.R.V.I.S. — Sistema Táctico en Línea*\n\n"
            "Buenas, Señor. Me encuentro plenamente operativo y a su "
            "entera disposición a través de este canal de Telegram.\n\n"
            "Mis capacidades incluyen:\n"
            "• 💬 Conversación inteligente con memoria contextual\n"
            "• 🎙️ Procesamiento de notas de voz (transcripción y respuesta "
            "por audio)\n"
            "• 🖥️ Control remoto del sistema vía puente local\n"
            "• 🔍 Diagnósticos del sistema\n\n"
            "Escriba /help para consultar los comandos disponibles.\n\n"
            "— *J.A.R.V.I.S.*"
        )
        await self._safe_reply(update, welcome)

    @authorized_only
    async def cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /help — lista de comandos disponibles."""
        help_text = (
            "📋 *Comandos disponibles — J.A.R.V.I.S.*\n\n"
            "• /start — Mensaje de bienvenida e información del sistema\n"
            "• /help — Muestra esta lista de comandos\n"
            "• /agenda [proximos] — Consulta su agenda y eventos de Google Calendar\n"
            "• /evento <título> | <fecha hora> — Programa un evento en Google Calendar\n"
            "• /bridge — Estado del puente local y acciones disponibles\n"
            "• /diagnostics — Ejecuta diagnósticos del sistema\n"
            "• /clear — Limpia el historial de conversación\n\n"
            "También puede:\n"
            "• Enviar *mensajes de texto* para conversar directamente\n"
            "• Enviar *notas de voz* que serán transcritas, procesadas y "
            "respondidas por audio\n\n"
            "— *J.A.R.V.I.S.*"
        )
        await self._safe_reply(update, help_text)

    @authorized_only
    async def cmd_bridge(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /bridge — estado y acciones del puente."""
        await update.message.chat.send_action(ChatAction.TYPING)

        health = await self._bridge.health_check()

        if health.get("online"):
            status_text = (
                "🟢 *Puente Local — EN LÍNEA*\n\n"
                f"• Servicio: `{health.get('service', 'N/A')}`\n"
                f"• Versión: `{health.get('version', 'N/A')}`\n"
                f"• Estado: `{health.get('status', 'N/A')}`\n\n"
                "📡 *Acciones disponibles:*\n"
                "• `list_files` — Listar archivos de un directorio\n"
                "• `read_file` — Leer el contenido de un archivo\n"
                "• `write_file` — Escribir contenido en un archivo\n"
                "• `open_item` — Abrir un programa o archivo\n"
                "• `system_diagnostics` — Diagnósticos del sistema\n\n"
                "Solicíteme estas acciones en lenguaje natural y las "
                "ejecutaré automáticamente."
            )
        else:
            error_detail = health.get("error", "Sin detalles")
            status_text = (
                "🔴 *Puente Local — FUERA DE LÍNEA*\n\n"
                f"• Error: `{error_detail}`\n\n"
                "Asegúrese de que `jarvis_bridge.py` se encuentre en "
                "ejecución en `http://127.0.0.1:8888`."
            )

        await self._safe_reply(update, status_text)

    @authorized_only
    async def cmd_diagnostics(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /diagnostics — diagnósticos del sistema."""
        await update.message.chat.send_action(ChatAction.TYPING)

        result = await self._bridge.execute_action("system_diagnostics")

        if result.get("success"):
            diag_text = (
                "🖥️ *Diagnósticos del Sistema — J.A.R.V.I.S.*\n\n"
                f"• Sistema operativo: `{result.get('os', 'N/A')} "
                f"{result.get('release', '')}`\n"
                f"• Procesador: `{result.get('processor', 'N/A')}`\n"
                f"• Disco libre: `{result.get('disk_free_gb', 'N/A')} GB`\n"
                f"• Disco total: `{result.get('disk_total_gb', 'N/A')} GB`\n"
            )
        else:
            diag_text = (
                "⚠️ *No fue posible obtener los diagnósticos.*\n\n"
                f"Error: `{result.get('error', 'Desconocido')}`\n\n"
                "Verifique que el puente local esté activo ejecutando "
                "`python jarvis_bridge.py`."
            )

        await self._safe_reply(update, diag_text)

    @authorized_only
    async def cmd_clear(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /clear — limpia el historial de conversación."""
        user_id = update.effective_user.id
        self._history[user_id].clear()
        await self._safe_reply(
            update,
            "🧹 Historial de conversación purgado correctamente, Señor. "
            "Estoy listo para una nueva sesión.",
        )

    @authorized_only
    async def cmd_agenda(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /agenda — consulta eventos de Google Calendar."""
        await update.message.chat.send_action(ChatAction.TYPING)
        arg = (context.args[0] if context.args else "").lower()
        act = "calendar_upcoming" if ("prox" in arg or "list" in arg) else "calendar_today"
        res = await self._bridge.execute_action(act, {})
        if res.get("success"):
            formatted = res.get("formatted") or "No se encontraron eventos."
            await self._safe_reply(update, formatted)
        else:
            await self._safe_reply(
                update,
                f"⚠️ Señor, no fue posible consultar el calendario: {res.get('error')}\n\n"
                "Verifique que el puente esté activo y haya ejecutado la vinculación (`conectar_calendario.bat`).",
            )

    @authorized_only
    async def cmd_evento(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador del comando /evento — agenda un nuevo evento en Google Calendar."""
        if not context.args:
            await self._safe_reply(
                update,
                "Señor, indique el título y fecha del evento separados por barra vertical `|`.\n"
                "Ejemplo: `/evento Reunión con cliente | 2026-10-31 16:00`",
            )
            return

        full_text = " ".join(context.args)
        if "|" in full_text:
            parts = full_text.split("|", 1)
            summary = parts[0].strip()
            start_time = parts[1].strip()
        else:
            await self._safe_reply(
                update,
                "Formato incorrecto. Utilice: `/evento <título> | <AAAA-MM-DD HH:MM>`",
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        res = await self._bridge.execute_action("calendar_create", {"summary": summary, "start_time": start_time})
        if res.get("success"):
            ev = res.get("event", {})
            link = ev.get("htmlLink", "")
            await self._safe_reply(
                update,
                f"✅ *Evento programado con éxito, Señor:*\n"
                f"• *Título:* `{summary}`\n"
                f"• *Inicio:* `{start_time}`\n"
                f"• [Ver en Google Calendar]({link})",
            )
        else:
            await self._safe_reply(
                update,
                f"⚠️ Señor, no fue posible agendar el evento: {res.get('error')}",
            )

    # -- Manejadores de mensajes --------------------------------------------

    @authorized_only
    async def handle_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador de mensajes de texto — conversación con Gemini."""
        user_text = update.message.text
        user_id = update.effective_user.id

        if not user_text or not user_text.strip():
            return

        logger.info(
            "Mensaje de texto recibido del usuario %d: %s",
            user_id,
            user_text[:80],
        )

        await update.message.chat.send_action(ChatAction.TYPING)

        response = await self._generate_response(user_id, user_text)
        await self._safe_reply(update, response)

    @authorized_only
    async def handle_voice(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Manejador de notas de voz y archivos de audio — flujo completo de voz a voz."""
        msg = update.message
        voice_or_audio = msg.voice or msg.audio
        if not voice_or_audio:
            return

        user_id = update.effective_user.id
        logger.info("Nota de voz/audio recibida del usuario %d.", user_id)
        await update.message.chat.send_action(ChatAction.RECORD_VOICE)

        tmp_dir = tempfile.mkdtemp(prefix="jarvis_voice_")
        input_ext = ".oga" if msg.voice else ".mp3"
        input_path = os.path.join(tmp_dir, f"voice_input{input_ext}")
        wav_path = os.path.join(tmp_dir, "voice_input.wav")
        mp3_resp_path = os.path.join(tmp_dir, "voice_response.mp3")

        try:
            # 1. Descargar audio de Telegram (con timeouts ampliados para evitar cortes)
            audio_file = await voice_or_audio.get_file(read_timeout=60, write_timeout=60, connect_timeout=30)
            await audio_file.download_to_drive(input_path, read_timeout=60, write_timeout=60, connect_timeout=30)

            # 2. Convertir a WAV si ffmpeg está disponible
            converted = await self._voice.convert_oga_to_wav(input_path, wav_path)
            target_path = wav_path if converted else input_path
            mime_type = "audio/wav" if converted else ("audio/ogg" if msg.voice else "audio/mp3")

            with open(target_path, "rb") as fh:
                audio_bytes = fh.read()

            # 3. Procesar audio con Gemini Multimodal (Directo, preciso y sin cuellos de botella)
            await update.message.chat.send_action(ChatAction.TYPING)
            response = await self._gemini.generate_with_audio(
                self._get_history(user_id), audio_bytes, mime_type
            )

            # 4. Procesar directivas de puente si las hubiera (calendario, SO, etc.)
            response = await self._process_bridge_actions(response)

            # 5. Guardar en memoria
            self._add_to_history(user_id, "user", "[Nota de voz enviada]")
            self._add_to_history(user_id, "model", response)

            # 6. Enviar respuesta: solo nota de voz si se puede sintetizar,
            #    de lo contrario enviar texto como respaldo.
            voice_sent = False
            try:
                await update.message.chat.send_action(ChatAction.RECORD_VOICE)
                await self._voice.synthesize(response, mp3_resp_path)
                if os.path.isfile(mp3_resp_path) and os.path.getsize(mp3_resp_path) > 0:
                    with open(mp3_resp_path, "rb") as audio_fh:
                        await update.message.reply_voice(voice=audio_fh)
                    voice_sent = True
            except Exception as synth_exc:
                logger.warning("No se pudo enviar nota de voz sintetizada: %s", synth_exc)

            # Solo enviar texto si no se pudo enviar la nota de voz
            if not voice_sent:
                await self._safe_reply(update, response)

        except Exception as exc:
            logger.error("Error en flujo de voz: %s", exc, exc_info=True)
            await self._safe_reply(
                update,
                "⚠️ Lamento informarle, Señor, que ocurrió un inconveniente "
                f"al procesar su nota de voz:\n`{exc}`",
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # -- Arranque del bot ---------------------------------------------------

    def run(self) -> None:
        """Configura y ejecuta el bot de Telegram.

        Este método bloquea hasta que se reciba una señal de terminación.
        """
        logger.info("Inicializando J.A.R.V.I.S. Telegram Bot...")
        logger.info("Modelo Gemini: %s", self.config.gemini_model)
        logger.info(
            "Usuario autorizado: %d", self.config.authorized_user_id
        )

        app = (
            Application.builder()
            .token(self.config.bot_token)
            .read_timeout(60.0)
            .write_timeout(60.0)
            .connect_timeout(30.0)
            .pool_timeout(30.0)
            .build()
        )

        # Registrar manejadores de comandos
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("agenda", self.cmd_agenda))
        app.add_handler(CommandHandler("evento", self.cmd_evento))
        app.add_handler(CommandHandler("bridge", self.cmd_bridge))
        app.add_handler(CommandHandler("diagnostics", self.cmd_diagnostics))
        app.add_handler(CommandHandler("clear", self.cmd_clear))

        # Registrar manejadores de mensajes
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text)
        )
        app.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self.handle_voice)
        )

        # Banner de arranque
        banner = (
            "\n"
            "╔══════════════════════════════════════════════════╗\n"
            "║       J.A.R.V.I.S.  TELEGRAM  BOT  v1.0        ║\n"
            "║──────────────────────────────────────────────────║\n"
            "║  Estado       ·  EN LÍNEA                       ║\n"
            f"║  Modelo       ·  {self.config.gemini_model:<29s}║\n"
            "║  Voz TTS      ·  es-ES-AlvaroNeural             ║\n"
            "║  Whisper      ·  base (es)                      ║\n"
            "╚══════════════════════════════════════════════════╝\n"
        )
        logger.info(banner)

        # Ejecutar el bot con polling
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def main() -> None:
    """Función principal de ejecución del bot de Telegram JARVIS."""
    try:
        config = JarvisConfig.from_env()
        bot = JarvisTelegramBot(config)
        bot.run()
    except Exception as exc:
        err_str = str(exc).lower()
        if "conflict" in err_str or "terminated by other getupdates" in err_str:
            print("\n[AVISO] Ya hay otra instancia del bot de Telegram activa. Ejecuta 'Detener_JARVIS.bat' para reiniciar limpiamente.\n")
            sys.exit(0)
        raise


if __name__ == "__main__":
    main()
