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


_RE_SXXEYY = re.compile(r"\bS(\d{1,2})E\d{1,4}\b", re.IGNORECASE)
_ROMANOS = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
_RE_TEMP_NOMBRE = re.compile(
    r"\bseason\s*(\d+)|\b(\d+)(?:st|nd|rd|th)\s+season\b|\bs(\d+)\b|\b(ii|iii|iv|vi|v)\b",
    re.IGNORECASE)
# Entradas que no son la serie de TV: una película no recibe "episodio 5".
_RE_NO_SERIE = re.compile(
    r"\b(movie|pel[ií]cula|film|ova|oad|special|specials|campaign|recap|picture drama)\b",
    re.IGNORECASE)


def _temporada_de_archivo(nombre_archivo: str) -> Optional[int]:
    """Temporada indicada en el archivo (S02E05 → 2) o None."""
    m = _RE_SXXEYY.search(Path(nombre_archivo).stem)
    return int(m.group(1)) if m else None


def _temporada_de_nombre(nombre: str) -> Optional[int]:
    """Temporada en un título: 'Season 2', '2nd Season', 'S2', 'II' → 2."""
    m = _RE_TEMP_NOMBRE.search(nombre or "")
    if not m:
        return None
    for g in m.groups()[:3]:
        if g:
            return int(g)
    return _ROMANOS.get((m.group(4) or "").lower())


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (s or "").lower()).split())


def _puntuar(nombre_archivo: str, anime: dict, temporada: Optional[int],
             episodio: Optional[int]) -> float:
    a, b = _norm(nombre_archivo), _norm(anime.get("nombre") or "")
    if not a or not b:
        return 0.0
    if a == b:
        score = 1.0
    elif a in b or b in a:
        # Contención: cuanto más se parecen las longitudes, mejor. Antes era
        # 0.95 fijo y ganaba el PRIMERO de la lista ("Naruto Shippuden" → "Naruto").
        corto, largo = sorted((len(a), len(b)))
        score = 0.7 + 0.3 * corto / largo
    else:
        score = SequenceMatcher(None, a, b).ratio()

    t_anime = _temporada_de_nombre(anime.get("nombre") or "")
    t_arch = temporada or _temporada_de_nombre(nombre_archivo)
    if t_arch and t_arch > 1:
        if t_anime == t_arch:
            score += 0.2
        elif t_anime:
            score -= 0.3
        else:
            score -= 0.1               # entrada sin temporada = la 1ª
    elif t_anime and t_anime > 1:
        score -= 0.15

    if _RE_NO_SERIE.search(anime.get("nombre") or "") and not _RE_NO_SERIE.search(nombre_archivo):
        score -= 0.25
    caps = str(anime.get("capitulos") or "")
    if caps == "película":
        score -= 0.25
    elif episodio and caps.isdigit() and episodio > int(caps) and not caps.endswith("+"):
        score -= 0.2                   # esa entrada no tiene tantos episodios
    if (anime.get("estado_usuario") or "") == "viendo":
        score += 0.05
    return score


def _buscar_coincidencia(nombre_archivo: str, animes: list[dict],
                         temporada: Optional[int] = None,
                         episodio: Optional[int] = None) -> Optional[dict]:
    """Anime de la biblioteca que mejor coincide con el nombre del archivo.

    Tiene en cuenta la temporada (S02E05, 'Season 2'), evita películas/OVAs
    y entradas con menos episodios que el del archivo. None si ninguno llega
    al 60 %."""
    mejor, mejor_score = None, 0.0
    for a in animes or []:
        sc = _puntuar(nombre_archivo, a, temporada, episodio)
        if sc > mejor_score:
            mejor, mejor_score = a, sc
    return mejor if mejor is not None and mejor_score >= 0.6 else None


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
        match = _buscar_coincidencia(nombre_serie, animes,
                                     temporada=_temporada_de_archivo(filename),
                                     episodio=episodio)
        if not match:
            _add_log(filename, nombre_serie, episodio, "sin coincidencia en biblioteca")
            continue
        # Solo marcar si el episodio es el siguiente al que lleva visto
        anime_nombre = match["nombre"]
        vistos = int(match.get("episodios_vistos") or 0)
        caps = str(match.get("capitulos") or "")
        if (match.get("estado_usuario") or "") == "completado":
            _add_log(filename, anime_nombre, episodio, "ya completado")
            continue
        if caps.isdigit() and episodio > int(caps):
            # Numeración continua entre temporadas o archivo de otra entrada:
            # mejor no marcar que sumar episodios que esa entrada no tiene.
            _add_log(filename, anime_nombre, episodio, f"fuera de rango (tiene {caps})")
            continue
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
