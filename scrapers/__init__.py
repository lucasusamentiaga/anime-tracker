from __future__ import annotations

import importlib
import sys

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

for _name, _module, _cls in _to_load:
    try:
        mod = importlib.import_module(_module, package=__name__)
        SCRAPERS[_name] = getattr(mod, _cls)()
    except Exception as _e:
        print(f"[AnimeTracker] Scraper '{_name}' no disponible: {_e}", file=sys.stderr)

__all__ = ["BaseScraper", "AnimeData", "SCRAPERS"]
