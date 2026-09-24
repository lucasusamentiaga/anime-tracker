"""
watch_folder.py — Auto-detección de episodios vistos.

Vigila una carpeta (ej. Descargas) y cuando aparece un archivo de anime
(mkv, mp4, avi) parsea el nombre para identificar serie y episodio,
y marca +1 automáticamente en la biblioteca si coincide con un anime guardado.

No requiere dependencias externas: usa polling en lugar de watchdog para
máxima compatibilidad en Windows.
"""
from __future__ import annotations

import logging
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import database as db

_log = logging.getLogger("watch_folder")

# Extensiones de video que consideramos "archivo de anime"
_VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".webm", ".m4v"}

# Regex para extraer nombre de serie y episodio de nombres de archivo comunes:
# [SubGroup] Anime Name - 05 [1080p].mkv
# Anime Name S01E05.mkv
# Anime Name - Episode 05.mkv
# Anime Name EP05.mkv
# Anime.Name.-.05.(1080p).mkv
_EP_PATTERNS = [
    # [SubGroup] Name - 05 [quality]
    re.compile(
        r"^\[.*?\]\s*(.+?)\s*[-–]\s*(\d{1,4})\b",
        re.IGNORECASE,
    ),
    # Name - S01E05 o S1E5
    re.compile(
        r"^(.+?)\s*[-–]?\s*S\d{1,2}E(\d{1,4})\b",
        re.IGNORECASE,
    ),
    # Name - EP05 o EP 05
    re.compile(
        r"^(.+?)\s*[-–]?\s*EP\s*(\d{1,4})\b",
        re.IGNORECASE,
    ),
    # Name - 05 (número al final tras separador)
    re.compile(
        r"^(.+?)\s*[-–]\s*(\d{1,4})\s*(?:[\[\(v]|$)",
        re.IGNORECASE,
    ),
    # Name 05 (número suelto al final del nombre limpio)
    re.compile(
        r"^(.+?)\s+(\d{1,3})\s*(?:[\[\(v]|$)",
        re.IGNORECASE,
    ),
]


def _limpiar_nombre(raw: str) -> str:
    """Limpia el nombre extraído del filename: quita tags de calidad, subgroup, etc."""
    # Quitar cosas entre corchetes y paréntesis
    s = re.sub(r"\[.*?\]", "", raw)
    s = re.sub(r"\(.*?\)", "", s)
    # Quitar indicadores de calidad
    s = re.sub(r"\b(1080p|720p|480p|x264|x265|HEVC|AAC|FLAC|BD|Blu-?Ray)\b", "", s, flags=re.IGNORECASE)
    # Puntos y underscores → espacios
    s = s.replace(".", " ").replace("_", " ")
    return s.strip(" -–")


def _parsear_archivo(nombre_archivo: str) -> Optional[tuple[str, int]]:
    """Intenta extraer (nombre_serie, numero_episodio) del nombre de archivo.
    Devuelve None si no puede parsear."""
    stem = Path(nombre_archivo).stem
    for pattern in _EP_PATTERNS:
        m = pattern.search(stem)
        if m:
            nombre_raw = m.group(1)
            ep = int(m.group(2))
            nombre = _limpiar_nombre(nombre_raw)
            if nombre and 1 <= ep <= 9999:
                return (nombre, ep)
    return None


def _buscar_coincidencia(nombre_archivo: str, animes: list[dict]) -> Optional[dict]:
    """Busca el anime de la biblioteca que mejor coincide con el nombre del archivo.
    Devuelve el anime dict o None si no hay match suficiente."""
    if not animes:
        return None
    nombre_lower = nombre_archivo.lower().strip()
    mejor = None
    mejor_ratio = 0.0

    for a in animes:
        anime_nombre = (a.get("nombre") or "").lower().strip()
        if not anime_nombre:
            continue
        # Match exacto (substring)
        if nombre_lower in anime_nombre or anime_nombre in nombre_lower:
            ratio = 0.95
        else:
            ratio = SequenceMatcher(None, nombre_lower, anime_nombre).ratio()
        if ratio > mejor_ratio:
            mejor_ratio = ratio
            mejor = a

    # Umbral mínimo de similitud: 0.6 (60%)
    if mejor_ratio >= 0.6 and mejor:
        return mejor
    return None


# ── Estado del watcher ────────────────────────────────────────────────────────

_watcher_thread: Optional[threading.Thread] = None
_watcher_stop = threading.Event()
_watcher_folder: Optional[str] = None
_watcher_seen: set[str] = set()  # archivos ya procesados
_watcher_log: list[dict] = []    # últimas detecciones (para la UI)
_LOG_MAX = 50


def get_status() -> dict:
    """Devuelve el estado actual del watcher."""
    return {
        "activo": _watcher_thread is not None and _watcher_thread.is_alive(),
        "carpeta": _watcher_folder,
        "archivos_procesados": len(_watcher_seen),
        "log": _watcher_log[-20:],
    }


def get_log() -> list[dict]:
    """Devuelve el log de detecciones recientes."""
    return list(_watcher_log[-_LOG_MAX:])


def _poll_loop(folder: str, interval: float = 15.0):
    """Loop principal: cada `interval` segundos escanea la carpeta."""
    global _watcher_seen
    folder_path = Path(folder)
    _log.info("Watch folder iniciado: %s", folder)

    # Scan inicial: marcar los archivos existentes como ya vistos
    try:
        for f in folder_path.iterdir():
            if f.is_file() and f.suffix.lower() in _VIDEO_EXTS:
                _watcher_seen.add(str(f))
    except Exception as e:
        _log.warning("scan inicial: %s", e)

    while not _watcher_stop.is_set():
        try:
            _check_new_files(folder_path)
        except Exception as e:
            _log.warning("poll error: %s", e)
        _watcher_stop.wait(interval)


def _check_new_files(folder_path: Path):
    """Busca archivos nuevos y procesa los que sean de anime."""
    global _watcher_seen
    try:
        archivos_actuales = set()
        for f in folder_path.iterdir():
            if f.is_file() and f.suffix.lower() in _VIDEO_EXTS:
                archivos_actuales.add(str(f))
    except Exception:
        return

    nuevos = archivos_actuales - _watcher_seen
    if not nuevos:
        return

    animes = db.listar_animes()
    for filepath_str in sorted(nuevos):
        _watcher_seen.add(filepath_str)
        filename = Path(filepath_str).name
        parsed = _parsear_archivo(filename)
        if not parsed:
            _add_log(filename, None, None, "no parseado")
            continue
        nombre_serie, episodio = parsed
        match = _buscar_coincidencia(nombre_serie, animes)
        if not match:
            _add_log(filename, nombre_serie, episodio, "sin coincidencia en biblioteca")
            continue
        # Solo marcar si el episodio es el siguiente al que lleva visto
        anime_nombre = match["nombre"]
        vistos = int(match.get("episodios_vistos") or 0)
        if episodio <= vistos:
            _add_log(filename, anime_nombre, episodio, "ya visto")
            continue
        if episodio > vistos + 3:
            _add_log(filename, anime_nombre, episodio, f"salto grande (llevas ep {vistos})")
            continue
        # Marcar episodio(s) intermedios también si hay salto de 1-2
        for ep in range(vistos + 1, episodio + 1):
            db.actualizar_anime(anime_nombre, {"episodios_vistos": ep})
            db.log_episode(anime_nombre, ep)
        _add_log(filename, anime_nombre, episodio, "marcado")
        _log.info("Auto-detectado: %s ep %d → %s", nombre_serie, episodio, anime_nombre)


def _add_log(archivo: str, anime: Optional[str], episodio: Optional[int], estado: str):
    """Añade una entrada al log de detecciones."""
    import datetime
    _watcher_log.append({
        "archivo": archivo,
        "anime": anime,
        "episodio": episodio,
        "estado": estado,
        "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    if len(_watcher_log) > _LOG_MAX:
        del _watcher_log[:len(_watcher_log) - _LOG_MAX]


def start(folder: str) -> bool:
    """Inicia el watcher en una carpeta. Devuelve False si ya está activo."""
    global _watcher_thread, _watcher_folder, _watcher_seen
    if _watcher_thread and _watcher_thread.is_alive():
        return False
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return False
    _watcher_stop.clear()
    _watcher_folder = str(folder_path)
    _watcher_seen = set()
    _watcher_thread = threading.Thread(
        target=_poll_loop, args=(str(folder_path),),
        daemon=True, name="watch-folder",
    )
    _watcher_thread.start()
    db.set_config("watch_folder", str(folder_path))
    return True


def stop():
    """Para el watcher."""
    global _watcher_thread, _watcher_folder
    _watcher_stop.set()
    if _watcher_thread:
        _watcher_thread.join(timeout=5)
    _watcher_thread = None
    _watcher_folder = None


def auto_start():
    """Si había una carpeta configurada, arranca automáticamente."""
    saved = db.get_config("watch_folder")
    if saved and Path(saved).is_dir():
        start(saved)
