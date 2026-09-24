"""
discord_presence.py — Estado enriquecido en Discord ("Viendo el ep. 12 de X").

Totalmente opcional y silencioso:
  - Si `pypresence` no está instalado, o Discord no se está ejecutando, o el
    usuario lo desactivó, todo se convierte en no-ops. Nunca rompe la app.
  - Requiere un Application ID de Discord (el usuario lo pega en Ajustes).

La lógica de formato es pura y testeable; la conexión está aislada detrás de
`_conectar()` para poder testear sin Discord.
"""
from __future__ import annotations

import threading
import time

import database as db
from core import log

# Estado del módulo (protegido por lock: lo tocan el event loop y los hilos)
_lock = threading.Lock()
_rpc = None                      # cliente pypresence, o None
_ultimo_fallo = 0.0              # para no reintentar conectar en bucle
_REINTENTO_S = 120.0


def activado() -> bool:
    """Solo si el usuario lo activó Y configuró un Application ID."""
    return bool(db.get_config("discord_enabled") == "1" and db.get_config("discord_app_id"))


def formatear_estado(anime: dict) -> dict:
    """Construye los textos del Rich Presence. Función pura (testeable).

    details = qué está viendo; state = progreso. Discord recorta a ~128 chars.
    """
    nombre = (anime.get("nombre") or "Algo").strip()
    vistos = int(anime.get("episodios_vistos") or 0)
    caps_raw = str(anime.get("capitulos") or "").strip().lower()
    es_pelicula = "pel" in caps_raw

    if es_pelicula:
        state = "Película"
    elif vistos > 0:
        total = "".join(c for c in caps_raw if c.isdigit())
        state = f"Episodio {vistos}" + (f" de {total}" if total else "")
    else:
        state = "Empezando"

    return {
        "details": nombre[:128],
        "state": state[:128],
        "large_image": "logo",          # asset subido en el portal de Discord
        "large_text": "Miraru",
    }


def _conectar():
    """Devuelve un cliente conectado o None. No lanza nunca."""
    global _rpc, _ultimo_fallo
    if _rpc is not None:
        return _rpc
    if time.time() - _ultimo_fallo < _REINTENTO_S:
        return None                      # backoff: Discord no está abierto
    try:
        from pypresence import Presence  # import perezoso: dependencia opcional
        app_id = db.get_config("discord_app_id") or ""
        if not app_id:
            return None
        cli = Presence(app_id)
        cli.connect()
        _rpc = cli
        log.info("Discord Rich Presence conectado")
        return _rpc
    except Exception as e:                # pypresence ausente, Discord cerrado…
        _ultimo_fallo = time.time()
        log.debug("Discord presence no disponible: %s", e)
        return None


def actualizar(anime: dict) -> bool:
    """Publica el estado. Devuelve True si se envió. Nunca lanza."""
    if not activado():
        return False
    with _lock:
        cli = _conectar()
        if cli is None:
            return False
        try:
            cli.update(**formatear_estado(anime))
            return True
        except Exception as e:
            log.debug("Discord update falló: %s", e)
            _limpiar_cliente()
            return False


def limpiar() -> None:
    """Borra el estado (al cerrar la app o desactivar la opción)."""
    with _lock:
        global _rpc
        if _rpc is None:
            return
        try:
            _rpc.clear()
            _rpc.close()
        except Exception:
            pass
        _rpc = None


def _limpiar_cliente() -> None:
    global _rpc, _ultimo_fallo
    _rpc = None
    _ultimo_fallo = time.time()
