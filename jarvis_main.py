#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Orquestador Principal
======================================
Lanza simultáneamente todos los módulos del sistema JARVIS:

1. **Puente Local OS** (jarvis_bridge.py) — HTTP en 127.0.0.1:8888
2. **Bot de Telegram** (jarvis_telegram.py) — Acceso móvil remoto
3. **Módulo de Voz Local** (jarvis_voice_local.py) — Escucha activa por micrófono

Cada módulo se ejecuta en su propio subproceso para garantizar el aislamiento.
El orquestador monitoriza los procesos y permite apagar todo con Ctrl+C.

Variables de entorno: se cargan desde ``.env`` si el archivo existe.

Uso::

    python jarvis_main.py                 -- Lanza todos los módulos
    python jarvis_main.py --no-voice      -- Sin módulo de voz local
    python jarvis_main.py --no-telegram   -- Sin bot de Telegram
    python jarvis_main.py --no-bridge     -- Sin puente local OS

Autor: Sistema JARVIS
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable


def _find_script(subfolder: str, filename: str) -> Path:
    """Busca un script primero en la raíz del proyecto y como alternativa en subcarpeta."""
    p1 = BASE_DIR / filename
    if p1.is_file():
        return p1
    p2 = BASE_DIR / subfolder / filename
    if p2.is_file():
        return p2
    return p1


def _get_modules() -> dict[str, dict[str, Any]]:
    return {
        "bridge": {
            "script": _find_script("bridge", "jarvis_bridge.py"),
            "label": "PUENTE LOCAL OS",
            "flag": "--no-bridge",
        },
        "telegram": {
            "script": _find_script("telegram", "jarvis_telegram.py"),
            "label": "BOT DE TELEGRAM",
            "flag": "--no-telegram",
        },
        "voice": {
            "script": _find_script("voice", "jarvis_voice_local.py"),
            "label": "VOZ LOCAL",
            "flag": "--no-voice",
        },
    }


# ---------------------------------------------------------------------------
# Carga de variables de entorno desde .env
# ---------------------------------------------------------------------------
def load_dotenv(env_path: Path) -> None:
    """Carga variables de entorno desde un archivo .env.

    Soporta el formato ``CLAVE=valor`` y ``CLAVE="valor con espacios"``.
    Ignora líneas vacías y comentarios (``#``).

    Args:
        env_path: Ruta al archivo ``.env``.
    """
    if not env_path.is_file():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            # Ignorar vacías y comentarios
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Eliminar comillas envolventes
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in ('"', "'")
            ):
                value = value[1:-1]

            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
BANNER = r"""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║         J.A.R.V.I.S.  ORCHESTRATOR  v1.0                        ║
║         ─────────────────────────────────                        ║
║         Puente OS · Telegram · Voz Local                         ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------
def main() -> None:
    """Punto de entrada principal del orquestador."""
    parser = argparse.ArgumentParser(
        description="J.A.R.V.I.S. — Orquestador de módulos del sistema."
    )
    parser.add_argument(
        "--no-bridge",
        action="store_true",
        help="No lanzar el puente local OS.",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="No lanzar el bot de Telegram.",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="No lanzar el módulo de voz local.",
    )
    args = parser.parse_args()

    print(BANNER)

    # Cargar .env
    env_path = BASE_DIR / ".env"
    load_dotenv(env_path)
    if env_path.is_file():
        print(f"  [CONFIG] Variables de entorno cargadas desde {env_path}")
    else:
        print(f"  [CONFIG] Archivo .env no encontrado en {BASE_DIR}")
        print(f"           Asegúrese de tener las variables de entorno configuradas.")

    # Determinar módulos a lanzar
    available_modules = _get_modules()
    skip = set()
    if args.no_bridge:
        skip.add("bridge")
    if args.no_telegram:
        skip.add("telegram")
    if args.no_voice:
        skip.add("voice")

    modules_to_launch = {
        k: v for k, v in available_modules.items() if k not in skip
    }

    if not modules_to_launch:
        print("  [ERROR] No hay módulos habilitados para lanzar.")
        sys.exit(1)

    print()
    for key, mod in modules_to_launch.items():
        print(f"  [MÓDULO] {mod['label']:<20s} → {mod['script'].name}")
    print()

    # Lanzar subprocesos
    processes: dict[str, subprocess.Popen] = {}

    for key, mod in modules_to_launch.items():
        script = mod["script"]
        if not script.is_file():
            print(f"  [ADVERTENCIA] Script no encontrado: {script}")
            continue

        try:
            proc = subprocess.Popen(
                [PYTHON, str(script)],
                cwd=str(BASE_DIR),
                env=os.environ.copy(),
                # El módulo de voz necesita stdin/stdout para interactuar
                stdin=sys.stdin if key == "voice" else subprocess.DEVNULL,
                stdout=None,  # Hereda la consola
                stderr=None,
            )
            processes[key] = proc
            print(f"  [LANZADO] {mod['label']} (PID: {proc.pid})")
        except Exception as exc:
            print(f"  [ERROR] No se pudo lanzar {mod['label']}: {exc}")

    if not processes:
        print("  [ERROR] No se pudo lanzar ningún módulo.")
        sys.exit(1)

    print()
    print("  ═══════════════════════════════════════════════════════")
    print("  Todos los módulos están en ejecución.")
    print("  Presione Ctrl+C para detener todos los sistemas.")
    print("  ═══════════════════════════════════════════════════════")
    print()

    # Esperar a que los procesos terminen o Ctrl+C
    try:
        while True:
            # Verificar si algún proceso terminó inesperadamente
            for key, proc in list(processes.items()):
                retcode = proc.poll()
                if retcode is not None:
                    label = modules_to_launch[key]["label"]
                    if retcode == 0:
                        print(f"  [INFO] {label} finalizó normalmente.")
                        del processes[key]
                        continue
                    print(
                        f"  [ALERTA] {label} terminó con código {retcode}. "
                        f"Reiniciando en 5 segundos..."
                    )
                    time.sleep(5)
                    # Reiniciar el módulo
                    try:
                        new_proc = subprocess.Popen(
                            [PYTHON, str(modules_to_launch[key]["script"])],
                            cwd=str(BASE_DIR),
                            env=os.environ.copy(),
                            stdin=(
                                sys.stdin
                                if key == "voice"
                                else subprocess.DEVNULL
                            ),
                            stdout=None,
                            stderr=None,
                        )
                        processes[key] = new_proc
                        print(
                            f"  [REINICIADO] {label} (nuevo PID: {new_proc.pid})"
                        )
                    except Exception as exc:
                        print(f"  [ERROR] No se pudo reiniciar {label}: {exc}")
                        del processes[key]

            if not processes:
                print("  [FATAL] Todos los módulos han fallado.")
                break

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n  [SISTEMA] Señal de interrupción recibida. Deteniendo módulos...")

    # Terminar todos los procesos
    for key, proc in processes.items():
        label = modules_to_launch[key]["label"]
        try:
            proc.terminate()
            proc.wait(timeout=5)
            print(f"  [DETENIDO] {label} (PID: {proc.pid})")
        except subprocess.TimeoutExpired:
            proc.kill()
            print(f"  [FORZADO] {label} (PID: {proc.pid}) terminado forzosamente.")
        except Exception:
            pass

    print()
    print("  ═══════════════════════════════════════════════════════")
    print("  Todos los sistemas JARVIS han sido desactivados.")
    print("  Ha sido un placer servirle, Señor.")
    print("  — J.A.R.V.I.S.")
    print("  ═══════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    main()
