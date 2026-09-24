from __future__ import annotations

from typing import Optional

from . import net
from .base import AnimeData, BaseScraper

# Session reutilizable para connection pooling (clave en importación masiva)
_session = net.make_session()   # con reintentos + backoff (ver scrapers/net.py)


ANILIST_API = "https://graphql.anilist.co"

QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    title { romaji english native }
    episodes
    format
    coverImage { large }
    genres
    description(asHtml: false)
    status
  }
}
"""


class AniListScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "anilist"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            resp = _session.post(
                ANILIST_API,
                json={"query": QUERY, "variables": {"search": nombre}},
                headers={"User-Agent": "AnimeTracker/2.6.2", "Accept": "application/json",
                         "Accept-Encoding": "identity"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            media = data.get("data", {}).get("Media")
            if not media:
                return None

            title = (
                media["title"].get("english")
                or media["title"].get("romaji")
                or nombre
            )
            episodes = media.get("episodes") or 0
            # Anime format puede ser MOVIE, TV, OVA, SPECIAL, ONA, MUSIC...
            fmt = (media.get("format") or "").upper()
            if fmt == "MOVIE":
                capitulos: int | str = "película"
            elif episodes > 0:
                capitulos = episodes
            else:
                capitulos = "?"  # desconocido (en emisión sin total, sin estrenar...)

            status_map = {
                "FINISHED": "Finalizado",
                "RELEASING": "En emisión",
                "NOT_YET_RELEASED": "Sin estrenar",
                "CANCELLED": "Cancelado",
                "HIATUS": "En pausa",
            }

            return AnimeData(
                nombre=title,
                capitulos=capitulos,
                imagen=media["coverImage"].get("large", ""),
                genero=media.get("genres", []),
                sinopsis=(media.get("description") or "")[:500],
                fuente=self.nombre_fuente,
                estado_anime=status_map.get(media.get("status", ""), "Desconocido"),
            )
        except Exception:
            return None
