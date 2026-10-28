from __future__ import annotations

import importlib
import sys

from . import adulto
from .base import AnimeData, BaseScraper

SCRAPERS: dict[str, BaseScraper] = {}

_to_load = [
    ("anilist",     ".anilist",     "AniListScraper"),
    ("jikan",       ".jikan",       "JikanV4Scraper"),
    ("kitsu",       ".kitsu",       "KitsuScraper"),
    ("mal",         ".mal",         "MALScraper"),
    ("animeflv",    ".animeflv",    "AnimeFLVScraper"),
    ("animeplanet", ".animeplanet", "AnimePlanetScraper"),
    ("animeav1",    ".animeav1",    "AnimeAV1Scraper"),
    ("crunchyroll", ".crunchyroll", "CrunchyrollScraper"),
]

# v2.14.1: ninguna búsqueda devuelve contenido para adultos (ver scrapers/adulto.py).
# Se aplica aquí, una vez, sobre cada método de búsqueda de cada fuente, para
# que ningún camino (búsqueda normal, varias fuentes, URL pegada, enriquecer)
# se lo salte.
_METODOS_UNO = ("buscar", "buscar_manga", "buscar_por_slug", "buscar_por_mal")


def _filtrar_metodo(fn):
    def envuelto(*a, **kw):
        return adulto.sin_adultos(fn(*a, **kw))
    envuelto.__wrapped__ = fn
    envuelto.__name__ = getattr(fn, "__name__", "buscar")
    return envuelto


def _filtrar_por_ids(fn):
    def envuelto(*a, **kw):
        r = fn(*a, **kw) or {}
        return {k: v for k, v in r.items() if not adulto.es_adulto(v)}
    envuelto.__wrapped__ = fn
    envuelto.__name__ = getattr(fn, "__name__", "buscar_por_ids")
    return envuelto


def _proteger(scraper: BaseScraper) -> BaseScraper:
    for m in _METODOS_UNO:
        if hasattr(scraper, m):
            setattr(scraper, m, _filtrar_metodo(getattr(scraper, m)))
    if hasattr(scraper, "buscar_por_ids"):
        scraper.buscar_por_ids = _filtrar_por_ids(scraper.buscar_por_ids)
    return scraper


for _name, _module, _cls in _to_load:
    try:
        mod = importlib.import_module(_module, package=__name__)
        SCRAPERS[_name] = _proteger(getattr(mod, _cls)())
    except Exception as _e:
        print(f"[AnimeTracker] Scraper '{_name}' no disponible: {_e}", file=sys.stderr)

__all__ = ["BaseScraper", "AnimeData", "SCRAPERS"]
