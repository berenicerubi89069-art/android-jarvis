#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Cliente Puente Local (Laptop)
==============================================
Este script se ejecuta en tu LAPTOP.
Al iniciarse, se conecta de inmediato a tu Servidor Central 24/7 en la Nube
a través de un WebSocket seguro.

En cuanto se conecta:
1. El Servidor y tu Telegram detectan que tu laptop está ONLINE y te avisan.
2. Puedes enviarle órdenes desde Telegram desde cualquier lugar del mundo
   (abrir programas, ver diagnósticos, tomar capturas de pantalla, bloquearla, etc.).
3. Si la laptop se suspende o apaga, el servidor detecta que se desconectó.
"""

from __future__ import annotations

import asyncio
import base64
import getpass
import io
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("jarvis.bridge_client")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent if BASE_DIR.name == "bridge" else BASE_DIR
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _get_calendar():
    try:
        from integrations.jarvis_calendar import JarvisCalendar
        return JarvisCalendar()
    except ImportError:
        from jarvis_calendar import JarvisCalendar
        return JarvisCalendar()

# ---------------------------------------------------------------------------
# Cargar variables de .env
# ---------------------------------------------------------------------------
def _load_env_file() -> None:
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
# Configuración
# ---------------------------------------------------------------------------
def _normalize_ws_url(url: str) -> str:
    url = url.strip()
    if url.startswith("wss:https://"):
        url = "wss://" + url[len("wss:https://"):]
    elif url.startswith("ws:http://"):
        url = "ws://" + url[len("ws:http://"):]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif not url.startswith("ws://") and not url.startswith("wss://"):
        url = "wss://" + url

    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    if not parsed.path or parsed.path == "/":
        url = urlunparse(parsed._replace(path="/ws/bridge"))

    return url

# Si la URL no está en .env, se puede editar aquí o en .env
raw_server_url = os.getenv("JARVIS_SERVER_URL", "ws://127.0.0.1:8888/ws/bridge")
SERVER_WS_URL = _normalize_ws_url(raw_server_url)
BRIDGE_SECRET = os.getenv("BRIDGE_SECRET", "jarvis_secret_key_2026")
RECONNECT_DELAY = 6  # Segundos entre intentos de reconexión


def _get_desktop_dir() -> str:
    user_home = os.path.expanduser("~")
    onedrive_desktop = os.path.join(user_home, "OneDrive", "Desktop")
    if os.path.isdir(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(user_home, "Desktop")


def _resolve_path(raw_path: str) -> str:
    if not raw_path or raw_path.strip().lower() in ("desktop", "escritorio", "desktop/", "escritorio/"):
        return _get_desktop_dir()
    norm = raw_path.replace("\\", "/")
    if norm.lower().startswith(("desktop/", "escritorio/")):
        sub = norm.split("/", 1)[1]
        return os.path.join(_get_desktop_dir(), sub)
    return os.path.abspath(raw_path)


# ---------------------------------------------------------------------------
# Ejecutor de Acciones en Windows
# ---------------------------------------------------------------------------
class WindowsActionExecutor:
    """Ejecuta directivas del sistema operativo en la laptop."""

    @staticmethod
    def open_item(params: dict[str, Any]) -> dict[str, Any]:
        target = params.get("target", "").strip()
        if not target:
            return {"success": False, "error": "Falta el parámetro 'target'"}
        try:
            # Compatibilidad Windows para apps y URLs
            os.startfile(target)
            return {"success": True, "opened": target}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def system_diagnostics(_params: dict[str, Any]) -> dict[str, Any]:
        disk = shutil.disk_usage(os.path.expanduser("~"))
        mem_info = "N/D"
        bateria_info = "N/D"

        # Batería en Windows mediante WMIC / PowerShell
        try:
            ps_bat = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Battery | Select-Object -ExpandProperty EstimatedChargeRemaining"],
                text=True, timeout=3
            ).strip()
            if ps_bat:
                bateria_info = f"{ps_bat}%"
        except Exception:
            pass

        return {
            "success": True,
            "os": platform.system(),
            "release": platform.release(),
            "processor": platform.processor(),
            "user": getpass.getuser(),
            "hostname": socket.gethostname(),
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "battery": bateria_info,
        }

    @staticmethod
    def list_files(params: dict[str, Any]) -> dict[str, Any]:
        target = _resolve_path(params.get("path", ""))

        if not os.path.isdir(target):
            return {"success": False, "error": f"Directorio no encontrado: {target}"}

        files = []
        for entry in os.scandir(target):
            try:
                stat = entry.stat()
                files.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size,
                })
            except OSError:
                files.append({"name": entry.name, "is_dir": entry.is_dir(follow_symlinks=False), "size": 0})

        return {"success": True, "path": target, "files": files}

    @staticmethod
    def read_file(params: dict[str, Any]) -> dict[str, Any]:
        filename = params.get("filename", "")
        if not filename:
            return {"success": False, "error": "Parámetro 'filename' faltante"}

        filepath = _resolve_path(filename)
        if not os.path.isfile(filepath):
            return {"success": False, "error": f"Archivo no encontrado: {filepath}"}

        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        return {"success": True, "filename": filepath, "content": content}

    @staticmethod
    def write_file(params: dict[str, Any]) -> dict[str, Any]:
        filename = params.get("filename", "")
        content = params.get("content", "")
        if not filename:
            return {"success": False, "error": "Parámetro 'filename' faltante"}

        filepath = _resolve_path(filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as fh:
            written = fh.write(content)

        return {"success": True, "filename": filepath, "bytes_written": written}

    @staticmethod
    def lock_workstation(_params: dict[str, Any]) -> dict[str, Any]:
        """Bloquea la pantalla de Windows de forma segura."""
        try:
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
            return {"success": True, "locked": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def run_command(params: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta un comando en PowerShell."""
        cmd = params.get("command", "").strip()
        if not cmd:
            return {"success": False, "error": "Comando vacío"}

        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=25,
            )
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "returncode": res.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "El comando excedió el tiempo límite (25s)"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def screenshot(_params: dict[str, Any]) -> dict[str, Any]:
        """Toma una captura de pantalla completa usando PowerShell nativo (.NET)."""
        tmp_img = os.path.join(tempfile.gettempdir(), f"jarvis_cap_{int(time.time())}.png")
        ps_script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
        $bitmap.Save('{tmp_img.replace('\\', '\\\\')}', [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
        """
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True, timeout=10)
            if os.path.isfile(tmp_img):
                with open(tmp_img, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("ascii")
                try:
                    os.remove(tmp_img)
                except Exception:
                    pass
                return {
                    "success": True,
                    "image_base64": img_b64,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            return {"success": False, "error": "No se generó el archivo de captura"}
        except Exception as exc:
            return {"success": False, "error": f"Fallo al capturar pantalla: {exc}"}

    @staticmethod
    def calendar_today(_params: dict[str, Any]) -> dict[str, Any]:
        try:
            cal = _get_calendar()
            events = cal.get_today_events()
            formatted = cal.format_events_list(events, "Compromisos de Hoy")
            return {"success": True, "events": events, "formatted": formatted}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def calendar_upcoming(params: dict[str, Any]) -> dict[str, Any]:
        try:
            cal = _get_calendar()
            max_results = int(params.get("max_results", 10))
            events = cal.get_upcoming_events(max_results=max_results)
            formatted = cal.format_events_list(events, "Próximos Eventos")
            return {"success": True, "events": events, "formatted": formatted}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def calendar_create(params: dict[str, Any]) -> dict[str, Any]:
        try:
            cal = _get_calendar()
            summary = params.get("summary", "")
            start_time = params.get("start_time", "")
            end_time = params.get("end_time")
            description = params.get("description", "")
            location = params.get("location", "")
            if not summary or not start_time:
                return {"success": False, "error": "Parámetros 'summary' y 'start_time' requeridos."}
            res = cal.create_event(
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
            )
            return {"success": True, "event": res}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def dispatch(cls, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "open_item": cls.open_item,
            "system_diagnostics": cls.system_diagnostics,
            "list_files": cls.list_files,
            "read_file": cls.read_file,
            "write_file": cls.write_file,
            "lock_workstation": cls.lock_workstation,
            "run_command": cls.run_command,
            "screenshot": cls.screenshot,
            "calendar_today": cls.calendar_today,
            "calendar_upcoming": cls.calendar_upcoming,
            "calendar_create": cls.calendar_create,
        }
        handler = handlers.get(action)
        if handler is None:
            return {"success": False, "error": f"Acción desconocida en la laptop: {action}"}
        try:
            return handler(params)
        except Exception as exc:
            return {"success": False, "error": f"Excepción ejecutando {action}: {exc}"}


# ---------------------------------------------------------------------------
# Cliente WebSocket Principal
# ---------------------------------------------------------------------------
async def start_bridge_client() -> None:
    headers = {"X-Bridge-Key": BRIDGE_SECRET}
    client_info = {
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "os": f"{platform.system()} {platform.release()}",
    }

    banner = rf"""
╔════════════════════════════════════════════════════════════════════╗
║             J.A.R.V.I.S.  —  PUENTE LOCAL DE CONTROL               ║
╠════════════════════════════════════════════════════════════════════╣
║  Equipo:   {client_info['hostname']} ({client_info['user']})
║  Servidor: {SERVER_WS_URL}
║  Estado:   Conectando...                                           ║
╚════════════════════════════════════════════════════════════════════╝
"""
    print(banner)

    while True:
        try:
            logger.info("📡 Conectando al servidor central JARVIS en: %s", SERVER_WS_URL)
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    SERVER_WS_URL,
                    headers=headers,
                    heartbeat=25.0,
                    timeout=60.0,
                ) as ws:
                    logger.info("🤝 Conexión establecida. Realizando handshake de seguridad...")
                    # Enviar handshake con info de la laptop
                    await ws.send_json({"client_info": client_info})

                    # Recibir confirmación
                    ack = await ws.receive_json(timeout=8.0)
                    logger.info("🟢 ¡ENLACE CUÁNTICO COMPLETADO! Servidor respondió: %s", ack.get("server"))
                    print("\n[ONLINE] Tu laptop está vinculada con Telegram. Puedes dar órdenes desde tu móvil.\n")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                                msg_id = payload.get("id")
                                action = payload.get("action", "")
                                params = payload.get("params", {})

                                logger.info("⚡ Directiva recibida desde Telegram: %s", action)
                                # Ejecutar en Windows de forma asíncrona en hilo
                                loop = asyncio.get_running_loop()
                                result = await loop.run_in_executor(
                                    None, WindowsActionExecutor.dispatch, action, params
                                )

                                # Devolver respuesta
                                response_payload = {"id": msg_id, "result": result}
                                await ws.send_str(json.dumps(response_payload))
                                logger.info("✔️ Resultado enviado exitosamente al servidor para: %s", action)
                            except Exception as err:
                                logger.error("Error procesando solicitud: %s", err)

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning("Conexión cerrada por el servidor.")
                            break

        except asyncio.CancelledError:
            logger.info("Puente cancelado por el usuario.")
            break
        except Exception as exc:
            logger.warning(
                "⚠️ No se pudo conectar al servidor (%s). Reintentando en %d segundos...",
                exc,
                RECONNECT_DELAY,
            )
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(start_bridge_client())
    except KeyboardInterrupt:
        print("\nPuente local cerrado.")
