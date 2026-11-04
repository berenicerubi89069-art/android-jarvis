#!/usr/bin/env python3
"""
JARVIS Bridge Server
====================
Lightweight HTTP bridge that exposes local system actions to the JARVIS UI.
Runs on http://127.0.0.1:8888 using only the Python standard library.

Usage:
    python jarvis_bridge.py      (with console)
    pythonw jarvis_bridge.py     (silent / no console)
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

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

HOST = os.environ.get("JARVIS_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("JARVIS_BRIDGE_PORT", "8888"))
VERSION = "2.0-universal"


def _is_android() -> bool:
    """Detecta si se ejecuta en Android (Termux o entorno Android nativo)."""
    return (
        os.path.exists("/data/data/com.termux")
        or hasattr(sys, "getandroidapilevel")
        or "android" in platform.uname().release.lower()
        or bool(os.environ.get("TERMUX_VERSION"))
    )


def _get_desktop_dir() -> str:
    user_home = os.path.expanduser("~")
    if _is_android():
        # En Android / Termux, usar storage accesible
        for candidate in [
            os.path.join(user_home, "storage", "shared"),
            os.path.join(user_home, "storage", "downloads"),
            user_home,
        ]:
            if os.path.isdir(candidate):
                return candidate
        return user_home

    onedrive_desktop = os.path.join(user_home, "OneDrive", "Desktop")
    if os.path.isdir(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(user_home, "Desktop")


def _resolve_path(raw_path: str) -> str:
    if not raw_path or raw_path.strip().lower() in (
        "desktop", "escritorio", "desktop/", "escritorio/", "almacenamiento", "storage"
    ):
        return _get_desktop_dir()
    norm = raw_path.replace("\\", "/")
    if norm.lower().startswith(("desktop/", "escritorio/")):
        sub = norm.split("/", 1)[1]
        return os.path.join(_get_desktop_dir(), sub)
    return os.path.abspath(raw_path)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class JarvisBridgeHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for the JARVIS bridge."""

    # Suppress default stderr logging when running under pythonw
    def log_message(self, fmt, *args):
        try:
            super().log_message(fmt, *args)
        except Exception:
            pass

    # -- CORS helpers -------------------------------------------------------
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._set_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- HTTP verbs ---------------------------------------------------------
    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send_json({
                "status": "ok",
                "service": "jarvis_bridge",
                "version": VERSION,
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path.rstrip("/") != "/action":
            self._send_json({"error": "Not found"}, 404)
            return

        # Read body
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            payload = json.loads(raw) if raw else {}
        except Exception as exc:
            self._send_json({"success": False, "error": f"Invalid JSON: {exc}"}, 400)
            return

        action = payload.get("action", "")
        params = payload.get("params", {})

        # Dispatch to the appropriate handler
        dispatch = {
            "list_files": self._action_list_files,
            "read_file": self._action_read_file,
            "write_file": self._action_write_file,
            "open_item": self._action_open_item,
            "system_diagnostics": self._action_system_diagnostics,
            "calendar_today": self._action_calendar_today,
            "calendar_upcoming": self._action_calendar_upcoming,
            "calendar_create": self._action_calendar_create,
            "calendar_search": self._action_calendar_search,
            "calendar_delete": self._action_calendar_delete,
        }

        handler = dispatch.get(action)
        if handler is None:
            self._send_json({
                "success": False,
                "error": f"Unknown action: {action!r}",
                "available": list(dispatch.keys()),
            }, 400)
            return

        try:
            result = handler(params)
            self._send_json(result)
        except Exception as exc:
            self._send_json({
                "success": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }, 500)

    # -- Action implementations ---------------------------------------------
    @staticmethod
    def _action_list_files(params: dict) -> dict:
        target = _resolve_path(params.get("path", ""))

        if not os.path.isdir(target):
            return {"success": False, "error": f"Directory not found: {target}"}

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
                files.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(follow_symlinks=False),
                    "size": 0,
                })

        return {"success": True, "path": target, "files": files}

    @staticmethod
    def _action_read_file(params: dict) -> dict:
        filename = params.get("filename", "")
        if not filename:
            return {"success": False, "error": "Missing 'filename' parameter"}

        filepath = _resolve_path(filename)
        if not os.path.isfile(filepath):
            return {"success": False, "error": f"File not found: {filepath}"}

        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        return {"success": True, "filename": filepath, "content": content}

    @staticmethod
    def _action_write_file(params: dict) -> dict:
        filename = params.get("filename", "")
        content = params.get("content", "")
        if not filename:
            return {"success": False, "error": "Missing 'filename' parameter"}

        filepath = _resolve_path(filename)
        # Create parent directories if needed
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as fh:
            bytes_written = fh.write(content)

        return {"success": True, "filename": filepath, "bytes_written": bytes_written}

    @staticmethod
    def _action_open_item(params: dict) -> dict:
        target = params.get("target", "")
        if not target:
            return {"success": False, "error": "Missing 'target' parameter"}

        # Soporte multiplataforma: Windows, Android (Termux), Linux, macOS
        try:
            if hasattr(os, "startfile"):
                os.startfile(target)  # Windows
            elif shutil.which("termux-open"):
                subprocess.Popen(["termux-open", target])
            elif shutil.which("termux-open-url") and (target.startswith("http://") or target.startswith("https://")):
                subprocess.Popen(["termux-open-url", target])
            elif shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", target])
            elif shutil.which("open"):
                subprocess.Popen(["open", target])
            elif shutil.which("am"):
                subprocess.Popen(["am", "start", "-a", "android.intent.action.VIEW", "-d", target])
            else:
                return {"success": False, "error": "No hay lanzador de archivos disponible para este sistema operativo."}
            return {"success": True, "opened": target}
        except Exception as exc:
            return {"success": False, "error": f"Fallo al abrir {target}: {exc}"}

    @staticmethod
    def _action_system_diagnostics(_params: dict) -> dict:
        disk = shutil.disk_usage(os.path.expanduser("~"))
        diagnostics = {
            "success": True,
            "os": platform.system(),
            "release": platform.release(),
            "processor": platform.processor() or platform.machine(),
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "is_android": _is_android(),
        }

        # Diagnósticos adicionales en Android Termux si termux-battery-status está disponible
        if _is_android() and shutil.which("termux-battery-status"):
            try:
                proc = subprocess.run(
                    ["termux-battery-status"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if proc.returncode == 0:
                    battery_data = json.loads(proc.stdout)
                    diagnostics["battery_percentage"] = battery_data.get("percentage")
                    diagnostics["battery_status"] = battery_data.get("status")
                    diagnostics["battery_temperature"] = battery_data.get("temperature")
            except Exception:
                pass

        return diagnostics

    @staticmethod
    def _action_calendar_today(_params: dict) -> dict:
        try:
            cal = _get_calendar()
            events = cal.get_today_events()
            formatted = cal.format_events_list(events, "Compromisos de Hoy")
            return {"success": True, "events": events, "formatted": formatted}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _action_calendar_upcoming(params: dict) -> dict:
        try:
            cal = _get_calendar()
            max_results = int(params.get("max_results", 10))
            events = cal.get_upcoming_events(max_results=max_results)
            formatted = cal.format_events_list(events, "Próximos Eventos")
            return {"success": True, "events": events, "formatted": formatted}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _action_calendar_create(params: dict) -> dict:
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

    @staticmethod
    def _action_calendar_search(params: dict) -> dict:
        try:
            cal = _get_calendar()
            query = params.get("query", "")
            max_results = int(params.get("max_results", 10))
            events = cal.search_events(query=query, max_results=max_results)
            formatted = cal.format_events_list(events, f"Búsqueda: {query}")
            return {"success": True, "events": events, "formatted": formatted}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _action_calendar_delete(params: dict) -> dict:
        try:
            cal = _get_calendar()
            event_id = params.get("event_id", "")
            if not event_id:
                return {"success": False, "error": "Parámetro 'event_id' requerido."}
            ok = cal.delete_event(event_id)
            return {"success": ok}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Server entry-point
# ---------------------------------------------------------------------------
def main():
    banner = rf"""
╔══════════════════════════════════════════════════╗
║           J.A.R.V.I.S.  BRIDGE  v{VERSION}            ║
║──────────────────────────────────────────────────║
║  HTTP server  ·  http://{HOST}:{PORT}            ║
║  Status       ·  ONLINE                          ║
║  Endpoints    ·  GET /health  |  POST /action    ║
╚══════════════════════════════════════════════════╝
"""
    try:
        print(banner)
    except Exception:
        pass  # pythonw has no console

    server = ThreadingHTTPServer((HOST, PORT), JarvisBridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Ensure silent exit when launched via pythonw
        with open(os.path.join(os.path.dirname(__file__), "jarvis_bridge_error.log"), "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
