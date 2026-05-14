"""
launcher.py — Punto de entrada del .exe.

Fix crítico: importa main.py con importlib.util.spec_from_file_location
en lugar de 'from main import app', para evitar el error
'No module named main' en PyInstaller --onedir.
"""
from __future__ import annotations

import multiprocessing
multiprocessing.freeze_support()

import os
import sys
import io
import time
import socket
import sqlite3 as _sqlite3
import threading
import webbrowser
import traceback
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────────────
FROZEN     = getattr(sys, "frozen", False)
FROZEN_DIR = Path(sys._MEIPASS) if FROZEN else Path(__file__).parent
APP_DIR    = Path(sys.executable).parent if FROZEN else Path(__file__).parent

LOG_FILE = APP_DIR / "anime_tracker.log"

# CWD = APP_DIR (donde están DB, credentials, config)
os.chdir(APP_DIR)

# sys.path: FROZEN_DIR primero para que los imports funcionen
for p in [str(FROZEN_DIR), str(FROZEN_DIR / "scrapers")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Env vars para todos los módulos
os.environ.update({
    "ANIME_FROZEN_DIR": str(FROZEN_DIR),
    "ANIME_APP_DIR":    str(APP_DIR),
    "ANIME_DB_PATH":    str(APP_DIR / "anime_tracker.db"),
})

HOST_LOCAL   = "127.0.0.1"   # solo PC
HOST_NETWORK = "0.0.0.0"    # red local (móvil)
PORT = 8765

def _get_host() -> str:
    """Si el usuario activó el acceso móvil, escuchar en todas las interfaces."""
    # Leer directamente del fichero config (antes de que main.py cargue la BD)
    db_path = APP_DIR / "anime_tracker.db"
    if not db_path.exists():
        return HOST_LOCAL
    try:
        con = _sqlite3.connect(str(db_path), timeout=3)
        row = con.execute("SELECT value FROM config WHERE key='mobile_enabled'").fetchone()
        con.close()
        return HOST_NETWORK if (row and row[0] == "1") else HOST_LOCAL
    except Exception:
        return HOST_LOCAL

HOST = HOST_LOCAL  # se actualiza en main() antes de arrancar

# ── Stdout/stderr seguros (son None en --noconsole) ───────────────────────────
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()


# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Red ───────────────────────────────────────────────────────────────────────
def puerto_en_uso(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def esperar_servidor(timeout: float = 40.0) -> bool:
    fin = time.time() + timeout
    while time.time() < fin:
        if puerto_en_uso(PORT):
            return True
        time.sleep(0.3)
    return False


# ── Servidor ──────────────────────────────────────────────────────────────────
_server_error: str = ""
_server_ready  = threading.Event()   # señal cuando uvicorn está listo
_server_failed = threading.Event()   # señal cuando falla al arrancar


def _load_app():
    """
    Carga la FastAPI app desde main.py usando importlib.
    Esto funciona aunque main.py esté en FROZEN_DIR/_internal/ o en FROZEN_DIR.
    """
    import importlib.util

    # Buscar main.py en posibles ubicaciones
    # En PyInstaller --onedir, FROZEN_DIR ya ES _internal/
    # así que main.py debería estar directamente en FROZEN_DIR
    candidates = [
        FROZEN_DIR / "main.py",
        APP_DIR / "_internal" / "main.py",
        APP_DIR / "main.py",
        FROZEN_DIR.parent / "main.py",
    ]
    main_path = None
    for c in candidates:
        if c.exists():
            main_path = c
            break

    if main_path is None:
        raise FileNotFoundError(
            f"No se encontró main.py.\n"
            f"Buscado en:\n" + "\n".join(str(c) for c in candidates)
        )

    log(f"Candidatos buscados: {[str(c) for c in candidates]}")
    log(f"Cargando main.py desde: {main_path}")
    spec = importlib.util.spec_from_file_location("main", str(main_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["main"] = module
    spec.loader.exec_module(module)
    return module.app


def _run_server():
    global _server_error
    try:
        import logging
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="a")],
        )

        log("Importando uvicorn…")
        import uvicorn

        log("Cargando app FastAPI…")
        app = _load_app()

        log(f"Arrancando servidor en {HOST}:{PORT}")
        _server_ready.set()   # señalizar que uvicorn está a punto de arrancar
        uvicorn.run(
            app,
            host=HOST,    # 127.0.0.1 o 0.0.0.0 según configuración
            port=PORT,
            log_config=None,
            log_level="warning",
            reload=False,
            access_log=False,
        )
    except Exception:
        _server_error = traceback.format_exc()
        log(f"ERROR en servidor:\n{_server_error}")
        _server_failed.set()   # señalizar fallo para que main() no espere timeout


def iniciar_servidor_hilo():
    t = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    t.start()
    return t


# ── UI de error ───────────────────────────────────────────────────────────────
def mostrar_error(titulo: str, msg: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(titulo, msg)
        root.destroy()
    except Exception:
        log(f"ERROR (sin GUI): {msg}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global HOST   # debe declararse antes de cualquier lectura o escritura

    try:
        LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass

    log("Anime Tracker iniciando…")
    log(f"FROZEN_DIR = {FROZEN_DIR}")
    log(f"APP_DIR    = {APP_DIR}")
    log(f"sys.path   = {sys.path[:4]}")

    # Si ya hay instancia corriendo, abrir navegador y salir
    if puerto_en_uso(PORT):
        log("Puerto en uso — abriendo navegador")
        webbrowser.open(f"http://{HOST}:{PORT}")
        return

    # Actualizar HOST según configuración antes de arrancar
    HOST = _get_host()
    if HOST == HOST_NETWORK:
        # Detectar IP local para mostrarla en el log y guardarla para la APK
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            log(f"Modo red activado — IP local: {local_ip}:{PORT}")
            # Guardar IP en BD para que la UI la muestre al usuario
            try:
                con = _sqlite3.connect(str(APP_DIR / "anime_tracker.db"), timeout=3)
                con.execute("INSERT INTO config(key,value) VALUES('network_host',?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (f"{local_ip}:{PORT}",))
                con.commit(); con.close()
            except Exception:
                pass
        except Exception:
            log("No se pudo detectar IP local")
    else:
        log("Modo local (solo PC)")

    hilo = iniciar_servidor_hilo()

    # Esperar hasta que el servidor señalice inicio o fallo (máx 40s)
    # _server_ready se activa justo antes de uvicorn.run()
    # _server_failed se activa si hay una excepción
    started = _server_ready.wait(timeout=10)
    if not started or _server_failed.is_set():
        mostrar_error(
            "Error al iniciar Anime Tracker",
            f"El servidor no pudo arrancar:\n\n{_server_error[:600]}\n\n"
            f"Log completo:\n{LOG_FILE}"
        )
        sys.exit(1)

    if not esperar_servidor(timeout=40):
        mostrar_error(
            "Anime Tracker — Tiempo agotado",
            f"El servidor no respondió en 40 segundos.\n\n"
            f"{_server_error[:400] or 'Sin detalles.'}\n\n"
            f"Log: {LOG_FILE}"
        )
        sys.exit(1)

    log("Servidor listo — abriendo navegador")
    webbrowser.open(f"http://{HOST}:{PORT}")

    try:
        while hilo.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        log("Cerrando…")


if __name__ == "__main__":
    main()
