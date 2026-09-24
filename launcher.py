"""
launcher.py — Punto de entrada del .exe.

Fix crítico: importa main.py con importlib.util.spec_from_file_location
en lugar de 'from main import app', para evitar el error
'No module named main' en PyInstaller --onedir.
"""
from __future__ import annotations

import multiprocessing

multiprocessing.freeze_support()

import io
import os
import socket
import sqlite3 as _sqlite3
import sys
import threading
import time
import traceback
import webbrowser
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
# Host con el que SIEMPRE nos conectamos como cliente (comprobar puerto, abrir
# navegador). Aunque uvicorn escuche en 0.0.0.0 (modo móvil), 0.0.0.0 no es una
# dirección válida para *conectar* desde el navegador en Windows — hay que usar
# loopback. Antes se usaba HOST (0.0.0.0) y eso provocaba timeout falso de 40s
# y abría http://0.0.0.0:8765 (que no carga).
CONNECT_HOST = "127.0.0.1"
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
    # Siempre por loopback: aunque el server escuche en 0.0.0.0, conectamos por
    # 127.0.0.1 (0.0.0.0 no es conectable como cliente en Windows).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((CONNECT_HOST, port)) == 0



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
            "No se encontró main.py.\n"
            "Buscado en:\n" + "\n".join(str(c) for c in candidates)
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
        print(f"[SERVER ERROR]\n{_server_error}", file=sys.stderr)
        _server_failed.set()   # señalizar fallo para que main() no espere timeout


def iniciar_servidor_hilo():
    t = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    t.start()
    return t


# ── UI de error ───────────────────────────────────────────────────────────────
def mostrar_error(titulo: str, msg: str):
    # Siempre escribir a stderr para que arranque.log lo capture (VBS redirect)
    print(f"[ERROR] {titulo}: {msg}", file=sys.stderr)
    log(f"ERROR: {titulo}: {msg}")
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(titulo, msg)
        root.destroy()
    except Exception:
        pass  # ya logueado arriba


# ── Desinstalación ─────────────────────────────────────────────────────────────
APP_NAME = "Miraru"
# Nombres antiguos: el instalador previo creaba los accesos como "Anime Tracker.lnk".
# Hay que borrarlos también o quedan huérfanos al desinstalar tras el rebrand.
APP_NAME_LEGACY = ["Anime Tracker"]
# EXE_NAME y REG_KEY conservan el identificador histórico a propósito: cambiarlos
# rompería la desinstalación de las instalaciones ya existentes.
EXE_NAME = "AnimeTracker.exe"
REG_KEY  = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\AnimeTracker"


def _confirm(msg: str, default: bool = True) -> bool:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        ans = messagebox.askyesno(APP_NAME, msg)
        root.destroy()
        return bool(ans)
    except Exception:
        return default


def _info(msg: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(APP_NAME, msg)
        root.destroy()
    except Exception:
        log(msg)


def _uninstall():
    """Maneja `AnimeTracker.exe --uninstall` (lo registra el instalador como
    UninstallString). Antes esto abría la app por error: launcher ignoraba argv
    y arrancaba el servidor en vez de desinstalar."""
    log("Desinstalación solicitada (--uninstall)")
    if not _confirm("¿Desinstalar Miraru?\n\n"
                    "Se eliminarán la aplicación y tus datos locales "
                    "(lista de animes, configuración)."):
        log("Desinstalación cancelada por el usuario")
        return

    # 1) Accesos directos (best-effort)
    shortcut_dirs = [
        Path(os.path.expanduser("~")) / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for d in shortcut_dirs:
        for nombre in [APP_NAME] + APP_NAME_LEGACY:
            try:
                lnk = d / f"{nombre}.lnk"
                if lnk.exists():
                    lnk.unlink()
            except Exception:
                pass

    # 2) Clave de registro (Agregar o quitar programas)
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except Exception:
        pass

    # 3) Carpeta de instalación. No podemos borrar el .exe en ejecución, así que
    #    lanzamos un .bat desacoplado que espera a que cerremos y hace rmdir.
    #    Guardas: solo si parece una instalación real (evita borrados accidentales).
    install_dir = APP_DIR
    safe = (
        (install_dir / EXE_NAME).exists()
        and (install_dir / "_internal").exists()
        and len(install_dir.parts) >= 3            # no borrar raíz de disco
    )
    if safe:
        try:
            import subprocess
            import tempfile
            bat = Path(tempfile.gettempdir()) / "_at_uninstall.bat"
            bat.write_text(
                "@echo off\r\n"
                "ping 127.0.0.1 -n 3 >nul\r\n"          # esperar ~2s a que cierre
                f'rmdir /s /q "{install_dir}"\r\n'
                'del "%~f0"\r\n',
                encoding="utf-8",
            )
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(["cmd", "/c", str(bat)],
                             creationflags=DETACHED_PROCESS, close_fds=True)
        except Exception as e:
            log(f"No se pudo programar el borrado de la carpeta: {e}")
    else:
        log(f"Carpeta no parece instalación válida, no se borra: {install_dir}")

    _info("Miraru se ha desinstalado.")
    sys.exit(0)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global HOST   # debe declararse antes de cualquier lectura o escritura

    try:
        LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass

    # Desinstalación: el instalador registra `AnimeTracker.exe --uninstall`.
    if "--uninstall" in sys.argv[1:]:
        _uninstall()
        return

    log("Miraru iniciando…")
    log(f"FROZEN_DIR = {FROZEN_DIR}")
    log(f"APP_DIR    = {APP_DIR}")
    log(f"sys.path   = {sys.path[:4]}")

    # Si ya hay instancia corriendo, abrir navegador y salir
    if puerto_en_uso(PORT):
        log("Puerto en uso — abriendo navegador")
        webbrowser.open(f"http://{CONNECT_HOST}:{PORT}")
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

    # Esperar hasta que el servidor señalice inicio o fallo (máx 10s)
    # _server_ready se activa justo antes de uvicorn.run()
    # _server_failed se activa si hay una excepción (antes o después de _server_ready)
    started = _server_ready.wait(timeout=10)
    if not started or _server_failed.is_set():
        mostrar_error(
            "Error al iniciar Miraru",
            f"El servidor no pudo arrancar:\n\n{_server_error[:600]}\n\n"
            f"Log completo:\n{LOG_FILE}"
        )
        sys.exit(1)

    # Esperar a que el puerto esté disponible, comprobando también _server_failed
    # (race condition: uvicorn puede fallar DESPUÉS de que _server_ready se active)
    fin = time.time() + 40
    listo = False
    while time.time() < fin:
        if _server_failed.is_set():
            mostrar_error(
                "Error al iniciar Miraru",
                f"El servidor se cerró inesperadamente:\n\n{_server_error[:600]}\n\n"
                f"Log: {LOG_FILE}"
            )
            sys.exit(1)
        if puerto_en_uso(PORT):
            listo = True
            break
        time.sleep(0.3)

    if not listo:
        mostrar_error(
            "Miraru — Tiempo agotado",
            f"El servidor no respondió en 40 segundos.\n\n"
            f"{_server_error[:400] or 'Sin detalles.'}\n\n"
            f"Log: {LOG_FILE}"
        )
        sys.exit(1)

    log("Servidor listo — abriendo navegador")
    webbrowser.open(f"http://{CONNECT_HOST}:{PORT}")

    try:
        while hilo.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        log("Cerrando…")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Capturar cualquier crash inesperado para que arranque.log
        # (VBS redirect de stdout/stderr) NO quede vacío.
        err = traceback.format_exc()
        log(f"CRASH FATAL:\n{err}")
        print(f"CRASH FATAL:\n{err}", file=sys.stderr)
        sys.exit(1)
