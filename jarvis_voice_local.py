#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Módulo de Voz Local para Windows
==================================================
Sistema de escucha activa por micrófono con reconocimiento de voz (STT),
síntesis de voz (TTS) mediante ``edge-tts`` con voz masculina formal en español
(es-ES-AlvaroNeural), e integración con la API de Google Gemini y el puente OS.

Diseñado con arquitectura híbrida auto-reparable y resiliente para Windows:
- Captura de micrófono: SpeechRecognition / SoundCard (WASAPI nativo).
- STT: faster-whisper / SpeechRecognition (Google STT fallback) / Whisper local.
- TTS: edge-tts (es-ES-AlvaroNeural) reproducido vía playsound3 / PowerShell.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Final

import aiohttp

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger: Final = logging.getLogger("jarvis.voice")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
GEMINI_BASE_URL: Final[str] = "https://generativelanguage.googleapis.com/v1beta"
BRIDGE_HOST: Final[str] = "http://127.0.0.1:8888"
BRIDGE_ACTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[BRIDGE_ACTION:\s*(\{.*?\})\]", re.DOTALL
)
MAX_HISTORY_LENGTH: Final[int] = 10
DEFAULT_TTS_VOICE: Final[str] = "es-ES-AlvaroNeural"
DEFAULT_STT_LANG: Final[str] = "es-MX"
WAKE_WORDS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(jarvis|yarvis|yárvis|llarvis|llárvis|harvis|charvis|yervis|servis|service)\b",
    re.IGNORECASE,
)
CLEAN_WAKE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(oye|hey|hola|ok|okay)?\s*(jarvis|yarvis|yárvis|llarvis|llárvis|harvis|charvis|yervis|servis|service)[,.]?\s*",
    re.IGNORECASE,
)


def _init_colorama():
    try:
        from colorama import Fore, Style, init as colorama_init
        colorama_init(autoreset=True)
        return Fore, Style
    except ImportError:
        class _Stub:
            CYAN = YELLOW = GREEN = RED = MAGENTA = WHITE = RESET = ""
            BRIGHT = NORMAL = RESET_ALL = ""
        return _Stub(), _Stub()


Fore, Style = _init_colorama()


class ConsoleUI:
    BANNER: Final[str] = r"""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║        ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗                  ║
║        ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝                  ║
║        ██║███████║██████╔╝██║   ██║██║███████╗                  ║
║   ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║                  ║
║   ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║                  ║
║    ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝                  ║
║                                                                  ║
║            V O I C E   M O D U L E   v 1.2                      ║
║            Escucha Local · Windows · Gemini API                  ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

    @staticmethod
    def show_banner() -> None:
        print(f"{Fore.CYAN}{ConsoleUI.BANNER}{Style.RESET_ALL}")

    @staticmethod
    def status(state: str, message: str) -> None:
        color_map = {
            "escuchando": Fore.GREEN,
            "procesando": Fore.YELLOW,
            "respondiendo": Fore.CYAN,
            "error": Fore.RED,
            "info": Fore.MAGENTA,
            "sistema": Fore.WHITE,
        }
        color = color_map.get(state.lower(), Fore.WHITE)
        tag = state.upper().center(14)
        print(f"{color}[{tag}]{Style.RESET_ALL} {message}")

    @staticmethod
    def transcription(text: str) -> None:
        print(f"\n{Fore.GREEN}  🎤 USUARIO:{Style.RESET_ALL} {text}")

    @staticmethod
    def response_preview(text: str, max_chars: int = 200) -> None:
        preview = text[:max_chars] + ("..." if len(text) > max_chars else "")
        print(f"{Fore.CYAN}  🤖 JARVIS:{Style.RESET_ALL} {preview}\n")

    @staticmethod
    def farewell() -> None:
        print(f"\n{Fore.CYAN}{'═' * 60}")
        print(f"  Ha sido un placer servirle, Señor.")
        print(f"  Todos los sistemas de voz local han sido desactivados.")
        print(f"  — J.A.R.V.I.S.")
        print(f"{'═' * 60}{Style.RESET_ALL}\n")


def _build_system_instruction() -> str:
    return (
        "Eres J.A.R.V.I.S., el asistente de inteligencia artificial personal "
        "táctico inspirado en el concepto de JARVIS.\n"
        "Tu personalidad es la de un mayordomo de élite: sumamente elegante, "
        "respetuoso, directo, inteligente, culto, refinado y sin rodeos "
        "innecesarios.\n"
        "Hablas y respondes SIEMPRE en español de manera impecable y formal.\n"
        "Te diriges al usuario habitualmente como «Señor».\n\n"
        "NORMAS ESTRICTAS DE RESPUESTA:\n"
        "1. Sé conciso y eficiente. Proporciona soluciones directas.\n"
        "2. Si una tarea no es técnicamente posible, indícalo con honestidad "
        "técnica; jamás inventes ni simules capacidades ficticias.\n"
        "3. El usuario te habla a través del micrófono de su PC Windows; "
        "adapta tus respuestas para que sean naturales al escucharlas en voz "
        "alta. Evita código largo o tablas extensas en respuestas habladas.\n\n"
        "CAPACIDADES DEL PUENTE LOCAL OS (OPCIONAL):\n"
        "Si el usuario te pide interactuar con su computadora, emite una "
        "directiva con la sintaxis exacta:\n"
        '[BRIDGE_ACTION: {"action": "list_files", "params": {"path": ""}}]\n'
        '[BRIDGE_ACTION: {"action": "read_file", "params": {"filename": "nombre"}}]\n'
        '[BRIDGE_ACTION: {"action": "write_file", "params": {"filename": "nombre", "content": "contenido"}}]\n'
        '[BRIDGE_ACTION: {"action": "open_item", "params": {"target": "notepad.exe"}}]\n'
        '[BRIDGE_ACTION: {"action": "system_diagnostics", "params": {}}]\n'
    )


class BridgeClient:
    def __init__(self, base_url: str = BRIDGE_HOST) -> None:
        self._base_url = base_url

    async def health_check(self) -> dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=2),
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
            return {"success": False, "error": str(exc)}


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._system_instruction = _build_system_instruction()

    async def generate(self, history: list[dict[str, str]]) -> str:
        models_to_try = [self._model]
        for fallback in ("gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        contents = [
            {"role": "model" if turn["role"] == "assistant" else "user", "parts": [{"text": turn["text"]}]}
            for turn in history
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": self._system_instruction}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 1500},
        }

        last_error: Exception | None = None
        async with aiohttp.ClientSession() as session:
            for model_name in models_to_try:
                endpoint = (
                    f"{GEMINI_BASE_URL}/models/{model_name}:generateContent?key={self._api_key}"
                )
                try:
                    async with session.post(
                        endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=45)
                    ) as resp:
                        if resp.status != 200:
                            err_txt = await resp.text()
                            last_error = RuntimeError(f"HTTP {resp.status} ({model_name}): {err_txt[:120]}")
                            logger.warning("Modelo %s falló (HTTP %d): %s", model_name, resp.status, err_txt[:120])
                            continue
                        data = await resp.json()

                    candidate = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if candidate:
                        return candidate
                    last_error = RuntimeError(f"Modelo {model_name} devolvió respuesta vacía")
                except Exception as exc:
                    last_error = exc
                    logger.warning("Excepción con modelo %s: %s", model_name, exc)
                    continue

        raise RuntimeError(f"Error en Gemini con todos los modelos: {last_error}")


class JarvisVoiceEngine:
    def __init__(
        self,
        gemini_api_key: str,
        gemini_model: str = "gemini-flash-lite-latest",
        tts_voice: str = DEFAULT_TTS_VOICE,
        wake_word_enabled: bool = True,
    ) -> None:
        self._gemini = GeminiClient(gemini_api_key, gemini_model)
        self._bridge = BridgeClient()
        self._tts_voice = tts_voice
        self._wake_word_enabled = wake_word_enabled
        self._history: list[dict[str, str]] = []
        self._stt_engine: str = "none"
        self._stt_model: Any = None
        self._recognizer: Any = None
        self._temp_dir = Path(tempfile.gettempdir()) / "jarvis_voice"
        self._running = False

    async def initialize(self) -> None:
        ConsoleUI.status("sistema", "Verificando dependencias y hardware de audio...")
        self._temp_dir.mkdir(parents=True, exist_ok=True)

        # 1. Configurar STT con fallback resiliente
        self._init_stt()

        # 2. Configurar Reconocedor y hardware de micrófono (Híbrido)
        import speech_recognition as sr
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold = 250
        self._recognizer.dynamic_energy_threshold = True
        self._recognizer.pause_threshold = 0.8

        self._mic_engine = "none"
        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.6)
                self._mic_engine = "pyaudio"
                ConsoleUI.status("sistema", "✓ Micrófono configurado vía PyAudio.")
        except Exception:
            pass

        if self._mic_engine == "none":
            try:
                import sounddevice as sd
                self._mic_engine = "sounddevice"
                ConsoleUI.status("sistema", "✓ Micrófono configurado vía sounddevice.")
            except Exception:
                pass

        if self._mic_engine == "none":
            self._mic_engine = "winmm"
            ConsoleUI.status("sistema", "✓ Grabador Nativo de Windows (MCI/WASAPI) activado.")

        # 3. Verificar puente local
        bridge_status = await self._bridge.health_check()
        if bridge_status.get("online"):
            ConsoleUI.status("sistema", "✓ Puente local OS en línea (127.0.0.1:8888).")
        else:
            ConsoleUI.status("info", "⚠ Puente local OS no detectado.")

        wake_status = "ACTIVADA" if self._wake_word_enabled else "DESACTIVADA"
        ConsoleUI.status("sistema", f"Palabra de activación: {wake_status}")
        ConsoleUI.status("sistema", f"Voz TTS: {self._tts_voice}")
        ConsoleUI.status("sistema", f"Motor STT activo: {self._stt_engine.upper()}")
        ConsoleUI.status("sistema", "═" * 50)
        ConsoleUI.status("sistema", "✓ Sistemas de voz local JARVIS inicializados.")
        ConsoleUI.status("sistema", "═" * 50)

    def _init_stt(self) -> None:
        # Intentar faster-whisper
        try:
            from faster_whisper import WhisperModel
            self._stt_model = WhisperModel("base", device="cpu", compute_type="int8")
            self._stt_engine = "faster-whisper"
            ConsoleUI.status("sistema", "✓ Motor STT: faster-whisper cargado.")
            return
        except Exception:
            pass

        # Fallback a SpeechRecognition integrado
        try:
            import speech_recognition
            self._stt_engine = "speech_recognition"
            ConsoleUI.status("sistema", "✓ Motor STT: Reconocimiento inteligente nativo activo.")
            return
        except Exception as exc:
            ConsoleUI.status("error", f"Fallo al inicializar STT: {exc}")
            raise SystemExit(1)

    async def listen(self) -> str | None:
        loop = asyncio.get_running_loop()
        try:
            audio_data = await loop.run_in_executor(None, self._capture_mic_audio)
            if not audio_data:
                return None

            if self._stt_engine == "faster-whisper" and self._stt_model:
                wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)
                temp_wav = self._temp_dir / f"mic_{int(time.time() * 1000)}.wav"
                temp_wav.write_bytes(wav_bytes)
                try:
                    segments, _ = self._stt_model.transcribe(str(temp_wav), language="es", beam_size=5)
                    text = " ".join([seg.text.strip() for seg in segments]).strip()
                    return text or None
                finally:
                    temp_wav.unlink(missing_ok=True)
            else:
                # Motor SpeechRecognition directo (rápido y con detección en español)
                lang = os.getenv("JARVIS_STT_LANG", DEFAULT_STT_LANG)
                def _recognize():
                    try:
                        return self._recognizer.recognize_google(audio_data, language=lang)
                    except Exception:
                        if lang != "es-ES":
                            return self._recognizer.recognize_google(audio_data, language="es-ES")
                        return None
                text = await loop.run_in_executor(None, _recognize)
                return text.strip() if text else None
        except Exception:
            return None

    def _capture_mic_audio(self) -> Any:
        import speech_recognition as sr

        # 1. Modo PyAudio (si está disponible)
        if getattr(self, "_mic_engine", "none") == "pyaudio":
            try:
                with sr.Microphone() as source:
                    return self._recognizer.listen(source, timeout=6, phrase_time_limit=14)
            except sr.WaitTimeoutError:
                return None
            except Exception as exc:
                logger.debug("Fallo en PyAudio, usando nativo: %s", exc)

        # 2. Modo sounddevice (si está instalado)
        if getattr(self, "_mic_engine", "none") == "sounddevice":
            try:
                import sounddevice as sd
                rec = sd.rec(int(4.5 * 16000), samplerate=16000, channels=1, dtype="int16")
                sd.wait()
                return sr.AudioData(rec.tobytes(), 16000, 2)
            except Exception as exc:
                logger.debug("Fallo en sounddevice: %s", exc)

        # 3. Modo Nativo de Windows (MCI winmm.dll - Sin dependencias externas)
        return self._capture_native_windows_audio()

    def _capture_native_windows_audio(self) -> Any:
        import ctypes
        import wave
        import speech_recognition as sr

        winmm = ctypes.windll.winmm
        alias = f"jarvis_{int(time.time() * 1000)}"
        temp_wav = self._temp_dir / f"{alias}.wav"
        try:
            winmm.mciSendStringW(f"open new type waveaudio alias {alias}", None, 0, None)
            winmm.mciSendStringW(
                f"set {alias} time format ms bitspersample 16 channels 1 samplespersec 16000",
                None,
                0,
                None,
            )
            winmm.mciSendStringW(f"record {alias}", None, 0, None)
            # Graba en bloques de 4 segundos
            time.sleep(4.0)
            winmm.mciSendStringW(f"stop {alias}", None, 0, None)
            winmm.mciSendStringW(f'save {alias} "{str(temp_wav)}"', None, 0, None)

            if temp_wav.is_file() and temp_wav.stat().st_size > 1000:
                with wave.open(str(temp_wav), "rb") as wf:
                    pcm_data = wf.readframes(wf.getnframes())
                    return sr.AudioData(pcm_data, 16000, 2)
        except Exception as exc:
            logger.debug("Error en grabador nativo winmm: %s", exc)
        finally:
            try:
                winmm.mciSendStringW(f"close {alias}", None, 0, None)
            except Exception:
                pass
            temp_wav.unlink(missing_ok=True)

        return None

    async def think(self, user_text: str) -> str:
        self._history.append({"role": "user", "text": user_text})
        if len(self._history) > MAX_HISTORY_LENGTH:
            self._history = self._history[-MAX_HISTORY_LENGTH:]

        try:
            response = await self._gemini.generate(self._history)
            response = await self._process_bridge_actions(response)
            self._history.append({"role": "assistant", "text": response})
            return response
        except Exception as exc:
            err_msg = f"Señor, se ha producido una anomalía en el procesamiento: {exc}"
            ConsoleUI.status("error", str(exc))
            return err_msg

    async def _process_bridge_actions(self, text: str) -> str:
        match = BRIDGE_ACTION_PATTERN.search(text)
        if not match:
            return text

        try:
            action_data = json.loads(match.group(1))
            action = action_data.get("action", "")
            params = action_data.get("params", {})
            ConsoleUI.status("info", f"Ejecutando acción del puente: {action}")
            result = await self._bridge.execute_action(action, params)

            if result.get("success"):
                notice = self._format_bridge_result(action, result)
            else:
                notice = f"Error en acción del puente: {result.get('error', 'Desconocido')}"
            return text.replace(match.group(0), notice)
        except Exception as exc:
            return text.replace(match.group(0), f"Puente no disponible: {exc}")

    @staticmethod
    def _format_bridge_result(action: str, result: dict[str, Any]) -> str:
        if action == "list_files":
            files = result.get("files", [])
            summary = ", ".join([f['name'] for f in files[:8]])
            return f"Archivos detectados: {summary}."
        elif action == "system_diagnostics":
            return f"Diagnóstico: Sistema {result.get('os')} {result.get('release')}, disco libre {result.get('disk_free_gb')} gigabytes."
        elif action == "open_item":
            return f"Iniciado elemento: {result.get('opened')}."
        return f"Acción {action} completada con éxito."

    async def speak(self, text: str) -> None:
        import edge_tts

        clean = re.sub(r"```[\s\S]*?```", "Código omitido.", text)
        clean = re.sub(r"[*_#`>]", "", clean)
        clean = re.sub(r"\[BRIDGE_ACTION:.*?\]", "", clean, flags=re.DOTALL).strip()
        if not clean:
            return

        temp_mp3 = self._temp_dir / f"tts_{int(time.time() * 1000)}.mp3"
        try:
            comm = edge_tts.Communicate(clean[:1500], self._tts_voice)
            await comm.save(str(temp_mp3))
            await self._play_mp3(temp_mp3)
        except Exception as exc:
            ConsoleUI.status("error", f"Error en síntesis: {exc}")
        finally:
            temp_mp3.unlink(missing_ok=True)

    async def _play_mp3(self, mp3_path: Path) -> None:
        loop = asyncio.get_running_loop()

        def _play():
            try:
                import playsound3
                playsound3.playsound(str(mp3_path))
                return
            except Exception:
                pass

            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(str(mp3_path))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
                pygame.mixer.music.unload()
                return
            except Exception:
                pass

            # Fallback Android / Termux / Linux
            if shutil.which("mpv"):
                try:
                    subprocess.run(["mpv", "--no-video", "--really-quiet", str(mp3_path)], check=True)
                    return
                except Exception:
                    pass
            if shutil.which("termux-media-player"):
                try:
                    subprocess.run(["termux-media-player", "play", str(mp3_path)], check=True)
                    return
                except Exception:
                    pass
            if shutil.which("ffplay"):
                try:
                    subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3_path)], check=True)
                    return
                except Exception:
                    pass
            if shutil.which("mpg123"):
                try:
                    subprocess.run(["mpg123", "-q", str(mp3_path)], check=True)
                    return
                except Exception:
                    pass

            # Fallback nativo de Windows (WMPlayer soporta MP3, a diferencia de SoundPlayer)
            if sys.platform == "win32":
                escaped_path = str(mp3_path).replace("'", "''")
                ps_cmd = (
                    f"$wmp = New-Object -ComObject WMPlayer.OCX; "
                    f"$wmp.URL = '{escaped_path}'; "
                    f"$wmp.controls.play(); "
                    f"while ($wmp.playState -ne 1 -and $wmp.playState -ne 8) {{ Start-Sleep -Milliseconds 100 }}"
                )
                os.system(f'powershell -NoProfile -Command "{ps_cmd}" >nul 2>&1')

        await loop.run_in_executor(None, _play)

    async def run(self) -> None:
        self._running = True
        ConsoleUI.status("escuchando", "Módulo de voz activo. Aguardando instrucciones...")

        while self._running:
            try:
                transcription = await self.listen()
                if not transcription:
                    continue

                if self._wake_word_enabled:
                    lower = transcription.lower().strip()
                    if not WAKE_WORDS_PATTERN.search(lower):
                        ConsoleUI.status("info", f"Audio capturado (sin coincidencia de activación): \"{transcription}\"")
                        continue
                    transcription = CLEAN_WAKE_PATTERN.sub("", transcription).strip()
                    if not transcription:
                        ConsoleUI.status("info", "Palabra de activación detectada. Aguardando orden...")
                        await self.speak("A su servicio, Señor. ¿En qué puedo asistirle?")
                        continue

                ConsoleUI.transcription(transcription)
                ConsoleUI.status("procesando", "Procesando respuesta cognitiva...")
                response = await self.think(transcription)
                ConsoleUI.response_preview(response)
                ConsoleUI.status("respondiendo", "Sintetizando audio...")
                await self.speak(response)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                logger.error("Error en ciclo de escucha: %s", exc)
                await asyncio.sleep(1)

        self._running = False

    def stop(self) -> None:
        self._running = False


def _load_env_file() -> None:
    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parent if base_dir.name == "voice" else base_dir
    env_path = project_root / ".env"
    if not env_path.is_file():
        env_path = base_dir / ".env"
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


async def main() -> None:
    ConsoleUI.show_banner()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        ConsoleUI.status("error", "GEMINI_API_KEY no encontrada en variables de entorno.")
        sys.exit(1)

    model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    voice = os.getenv("JARVIS_TTS_VOICE", DEFAULT_TTS_VOICE)
    wake = os.getenv("JARVIS_WAKE_WORD_ENABLED", "true").lower() in ("true", "1", "si", "yes")

    engine = JarvisVoiceEngine(api_key, model, voice, wake)
    await engine.initialize()
    await engine.speak("Sistemas de voz en línea, Señor. Aguardo sus directivas.")
    await engine.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ConsoleUI.farewell()
