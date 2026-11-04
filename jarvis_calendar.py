#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Módulo de Integración con Google Calendar
=========================================================
Provee capacidades de lectura, creación, búsqueda y gestión de eventos
en Google Calendar utilizando la API oficial de Google y credenciales OAuth 2.0.

Archivos involucrados:
    credentials.json  - Credenciales de aplicación de escritorio descargadas de Google Cloud
    token.json        - Tokens de acceso y refresco generados tras la primera autenticación

Uso CLI:
    python jarvis_calendar.py auth     # Ejecuta la autenticación inicial en navegador
    python jarvis_calendar.py today    # Muestra los eventos de hoy
    python jarvis_calendar.py list     # Muestra los próximos 10 eventos
    python jarvis_calendar.py add "Título" "2026-10-31 15:00" ["2026-10-31 16:00"]
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Intentar importar las librerías de Google
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# Scopes requeridos para lectura y escritura completa en el calendario
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

BASE_DIR = Path(__file__).resolve().parent
# Si está dentro de la subcarpeta integrations/, la raíz del proyecto es el directorio padre
if BASE_DIR.name == "integrations":
    PROJECT_ROOT = BASE_DIR.parent
else:
    PROJECT_ROOT = BASE_DIR

CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
if not CREDENTIALS_FILE.exists() and (BASE_DIR / "credentials.json").exists():
    CREDENTIALS_FILE = BASE_DIR / "credentials.json"

TOKEN_FILE = PROJECT_ROOT / "token.json"
if not TOKEN_FILE.exists() and (BASE_DIR / "token.json").exists():
    TOKEN_FILE = BASE_DIR / "token.json"

logger = logging.getLogger("jarvis.calendar")


class JarvisCalendar:
    """Administrador de Google Calendar para JARVIS."""

    def __init__(
        self,
        credentials_path: Path | str = CREDENTIALS_FILE,
        token_path: Path | str = TOKEN_FILE,
    ) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self._service: Any = None

    def get_service(self, interactive: bool = True) -> Any:
        """Obtiene o inicializa el cliente de servicio de Google Calendar.

        Si las credenciales no existen o expiraron:
        - Si interactive=True: abre el navegador para iniciar sesión.
        - Si interactive=False: intenta refrescar con token.json sin abrir interfaz.
        """
        if not GOOGLE_LIBS_AVAILABLE:
            raise RuntimeError(
                "Las librerías de Google Calendar no están instaladas. "
                "Ejecute: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )

        if self._service is not None:
            return self._service

        creds = None

        # 1. Cargar token existente si está disponible
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            except Exception as exc:
                logger.warning("Error leyendo token.json existente: %s", exc)
                creds = None

        # 2. Refrescar o solicitar nueva autenticación
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info("Refrescando token de acceso de Google Calendar...")
                    creds.refresh(Request())
                except Exception as exc:
                    logger.warning("No se pudo refrescar el token: %s", exc)
                    creds = None

            if not creds:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"No se encontró el archivo de credenciales en: {self.credentials_path}\n"
                        "Por favor asegúrese de colocar 'credentials.json' en la carpeta raíz del proyecto."
                    )

                if not interactive:
                    raise RuntimeError(
                        "Autenticación requerida pero el modo interactivo está deshabilitado. "
                        "Ejecute 'python jarvis_calendar.py auth' primero."
                    )

                logger.info("Iniciando flujo de autorización en navegador...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Guardar token actualizado para futuras sesiones
            try:
                with open(self.token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
                logger.info("Token guardado exitosamente en %s", self.token_path.name)
            except Exception as exc:
                logger.error("No se pudo guardar token.json: %s", exc)

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def get_upcoming_events(self, max_results: int = 10) -> list[dict[str, Any]]:
        """Obtiene los próximos eventos a partir del momento actual."""
        service = self.get_service(interactive=False)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return events_result.get("items", [])

    def get_today_events(self) -> list[dict[str, Any]]:
        """Obtiene todos los eventos programados para el día actual en la zona horaria local."""
        service = self.get_service(interactive=False)
        tz = datetime.datetime.now().astimezone().tzinfo

        today = datetime.datetime.now(tz).date()
        start_of_day = datetime.datetime.combine(today, datetime.time.min).replace(tzinfo=tz)
        end_of_day = datetime.datetime.combine(today, datetime.time.max).replace(tzinfo=tz)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return events_result.get("items", [])

    def get_events_for_date(self, target_date: datetime.date) -> list[dict[str, Any]]:
        """Obtiene todos los eventos para una fecha específica."""
        service = self.get_service(interactive=False)
        tz = datetime.datetime.now().astimezone().tzinfo

        start_of_day = datetime.datetime.combine(target_date, datetime.time.min).replace(tzinfo=tz)
        end_of_day = datetime.datetime.combine(target_date, datetime.time.max).replace(tzinfo=tz)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return events_result.get("items", [])

    def create_event(
        self,
        summary: str,
        start_time: datetime.datetime | str,
        end_time: datetime.datetime | str | None = None,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Crea un nuevo evento en Google Calendar.

        Si end_time no se especifica, por defecto dura 1 hora.
        """
        service = self.get_service(interactive=False)
        tz = datetime.datetime.now().astimezone().tzinfo

        # Normalizar start_time
        if isinstance(start_time, str):
            start_dt = self._parse_datetime(start_time, tz)
        else:
            start_dt = start_time if start_time.tzinfo else start_time.replace(tzinfo=tz)

        # Normalizar end_time
        if end_time is None:
            end_dt = start_dt + datetime.timedelta(hours=1)
        elif isinstance(end_time, str):
            end_dt = self._parse_datetime(end_time, tz)
        else:
            end_dt = end_time if end_time.tzinfo else end_time.replace(tzinfo=tz)

        event_body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_dt.isoformat(),
            },
            "end": {
                "dateTime": end_dt.isoformat(),
            },
        }

        created = (
            service.events()
            .insert(calendarId="primary", body=event_body)
            .execute()
        )
        return created

    def delete_event(self, event_id: str) -> bool:
        """Elimina un evento por su ID."""
        service = self.get_service(interactive=False)
        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            return True
        except HttpError as exc:
            logger.error("Error eliminando evento %s: %s", event_id, exc)
            return False

    def search_events(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Busca eventos por palabra clave en título o descripción."""
        service = self.get_service(interactive=False)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                q=query,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return events_result.get("items", [])

    @staticmethod
    def _parse_datetime(date_str: str, default_tz: Any) -> datetime.datetime:
        """Intenta parsear cadenas de fecha en formatos comunes."""
        clean = date_str.strip()
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.datetime.strptime(clean, fmt)
                return dt.replace(tzinfo=default_tz)
            except ValueError:
                continue

        # Intentar ISO format directo
        try:
            dt = datetime.datetime.fromisoformat(clean)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=default_tz)
            return dt
        except Exception:
            raise ValueError(
                f"No se pudo interpretar el formato de fecha y hora: '{date_str}'. "
                "Use el formato: 'AAAA-MM-DD HH:MM' (p. ej. '2026-10-31 16:30')."
            )

    @staticmethod
    def format_event_for_display(event: dict[str, Any]) -> str:
        """Formatea un evento para presentación en texto o mensaje de Telegram."""
        start_info = event.get("start", {})
        start_str = start_info.get("dateTime") or start_info.get("date") or "Hora no definida"
        summary = event.get("summary", "(Sin título)")
        location = event.get("location")

        # Formatear hora de forma amigable si es ISO
        hora_bonita = start_str
        try:
            if "T" in start_str:
                dt = datetime.datetime.fromisoformat(start_str)
                hora_bonita = dt.strftime("%d/%m %H:%M")
        except Exception:
            pass

        loc_text = f" 📍 {location}" if location else ""
        return f"• [{hora_bonita}] {summary}{loc_text}"

    @classmethod
    def format_events_list(cls, events: list[dict[str, Any]], title: str = "Agenda") -> str:
        """Genera un resumen formateado al estilo J.A.R.V.I.S."""
        if not events:
            return f"📅 *{title}*\n\nSeñor, no hay compromisos registrados para este periodo."

        lines = [f"📅 *{title}*\n"]
        for ev in events:
            lines.append(cls.format_event_for_display(ev))

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Punto de entrada para pruebas en consola (CLI)
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cal = JarvisCalendar()
    args = sys.argv[1:]
    command = args[0].lower() if args else "help"

    if command == "auth":
        print("🔐 Iniciando autenticación con Google Calendar...")
        try:
            cal.get_service(interactive=True)
            print("✅ ¡Autenticación exitosa! El archivo 'token.json' ha sido generado.")
            print("J.A.R.V.I.S. ahora tiene acceso directo a su Google Calendar.")
        except Exception as e:
            print(f"❌ Error durante la autenticación: {e}")

    elif command == "today":
        try:
            events = cal.get_today_events()
            print("\n" + cal.format_events_list(events, "Compromisos de Hoy"))
        except Exception as e:
            print(f"❌ Error al consultar agenda: {e}")

    elif command == "list":
        try:
            events = cal.get_upcoming_events(max_results=10)
            print("\n" + cal.format_events_list(events, "Próximos Eventos"))
        except Exception as e:
            print(f"❌ Error al listar eventos: {e}")

    elif command == "add":
        if len(args) < 3:
            print("Uso: python jarvis_calendar.py add \"Título\" \"AAAA-MM-DD HH:MM\" [\"AAAA-MM-DD HH:MM\"]")
            return
        summary = args[1]
        start_time = args[2]
        end_time = args[3] if len(args) > 3 else None
        try:
            res = cal.create_event(summary=summary, start_time=start_time, end_time=end_time)
            print(f"✅ Evento creado exitosamente:\n• Título: {res.get('summary')}\n• Enlace: {res.get('htmlLink')}")
        except Exception as e:
            print(f"❌ Error al crear evento: {e}")

    else:
        print("""
J.A.R.V.I.S. — Comandos disponibles para Calendar:
  python jarvis_calendar.py auth     -> Autentica tu cuenta de Google y genera token.json
  python jarvis_calendar.py today    -> Muestra los eventos de hoy
  python jarvis_calendar.py list     -> Muestra los próximos 10 eventos
  python jarvis_calendar.py add "Título" "2026-10-31 15:00" ["2026-10-31 16:00"]
""")


if __name__ == "__main__":
    main()
