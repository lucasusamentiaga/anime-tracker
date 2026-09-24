"""
Estadísticas unificadas: anime + media (películas y series no-anime).

Funciones puras, sin dependencias de FastAPI ni de la BD, para que sean
triviales de testear de forma aislada. main.py solo las invoca con los datos
de db.listar_animes() y db.listar_media().
"""
from __future__ import annotations

import re

EP_MIN = 24      # minutos por episodio de anime/serie
MOVIE_MIN = 95   # minutos por película cuando no se conoce la duración real

_COMPLETADO = ("completado", "completed")


def anime_vistos(a: dict) -> tuple[int, int]:
    """(episodios, minutos) vistos de un anime — misma lógica que /api/stats.
    Un anime completado cuenta TODOS sus capítulos aunque nunca se incrementaran
    los episodios vistos a mano."""
    estado = a.get("estado_usuario", "pendiente")
    caps_raw = str(a.get("capitulos") or "").strip().lower()
    es_pelicula = "pel" in caps_raw
    nums = re.findall(r"\d+", caps_raw)
    caps_total = int(nums[0]) if nums else 0
    ep_man = int(a.get("episodios_vistos") or 0)
    completado = estado in _COMPLETADO
    if es_pelicula:
        return (1, MOVIE_MIN) if (completado or ep_man > 0) else (0, 0)
    # Bug heredado v<2.6.2: capitulos="200" falso en animes importados.
    if caps_total == 200 and ep_man == 0:
        return 0, 0
    vistos = max(ep_man, caps_total) if completado else ep_man
    return vistos, vistos * EP_MIN


def media_vistos(m: dict) -> tuple[int, int]:
    """(items, minutos) de una película o serie de TMDB.
    En la tabla media, `duracion` es minutos para películas y nº de episodios
    para series."""
    estado = m.get("estado_usuario", "pendiente")
    completado = estado in _COMPLETADO
    ep_man = int(m.get("episodios_vistos") or 0)
    dur = int(m.get("duracion") or 0)
    if (m.get("tipo") or "pelicula") == "pelicula":
        if completado or ep_man > 0:
            return 1, (dur or MOVIE_MIN)
        return 0, 0
    # serie: dur = nº de episodios totales
    vistos = max(ep_man, dur) if completado else ep_man
    return vistos, vistos * EP_MIN


def stats_globales(animes: list[dict], media: list[dict]) -> dict:
    """Resumen combinado de TODA la biblioteca (anime + pelis + series)."""
    ae = am = me = mm = 0
    for a in animes:
        e, mi = anime_vistos(a)
        ae += e
        am += mi
    for m in media:
        e, mi = media_vistos(m)
        me += e
        mm += mi
    return {
        "total_titulos":    len(animes) + len(media),
        "animes":           len(animes),
        "media":            len(media),
        "peliculas":        sum(1 for m in media if (m.get("tipo") or "pelicula") == "pelicula"),
        "series":           sum(1 for m in media if m.get("tipo") == "serie"),
        "episodios_anime":  ae,
        "items_media":      me,
        "total_episodios":  ae + me,
        "horas_totales":    round((am + mm) / 60, 1),
        "horas_anime":      round(am / 60, 1),
        "horas_media":      round(mm / 60, 1),
    }
