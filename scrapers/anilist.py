from __future__ import annotations

from typing import Optional

from . import net
from .base import AnimeData, BaseScraper

# Session reutilizable para connection pooling (clave en importación masiva)
_session = net.make_session()   # con reintentos + backoff (ver scrapers/net.py)


ANILIST_API = "https://graphql.anilist.co"

QUERY = """
query ($search: String, $type: MediaType!) {
  Media(search: $search, type: $type) {
    id
    title { romaji english native }
    episodes
    chapters
    volumes
    format
    coverImage { large }
    genres
    description(asHtml: false)
    status
    nextAiringEpisode { episode }
  }
}
"""

_STATUS_MAP = {
    "FINISHED": "Finalizado",
    "RELEASING": "En emisión",
    "NOT_YET_RELEASED": "Sin estrenar",
    "CANCELLED": "Cancelado",
    "HIATUS": "En pausa",
}


def _parse_media(media: dict, nombre: str, fuente: str,
                 media_type: str = "ANIME") -> Optional[AnimeData]:
    """Convierte un resultado de AniList en AnimeData (anime o manga)."""
    title = (
        media["title"].get("english")
        or media["title"].get("romaji")
        or nombre
    )
    fmt = (media.get("format") or "").upper()
    is_manga = media_type == "MANGA"

    if is_manga:
        chapters = media.get("chapters") or 0
        capitulos: int | str = chapters if chapters > 0 else "?"
    else:
        episodes = media.get("episodes") or 0
        if fmt == "MOVIE":
            capitulos = "película"
        elif episodes > 0:
            capitulos = episodes
        else:
            # Para anime en emisión, usar nextAiringEpisode para saber
            # cuántos episodios han salido hasta ahora
            nae = media.get("nextAiringEpisode") or {}
            next_ep = nae.get("episode") or 0
            capitulos = f"{next_ep - 1}+" if next_ep > 1 else "?"

    return AnimeData(
        nombre=title,
        capitulos=capitulos,
        imagen=media["coverImage"].get("large", ""),
        genero=media.get("genres", []),
        sinopsis=(media.get("description") or "")[:500],
        fuente=fuente,
        estado_anime=_STATUS_MAP.get(media.get("status", ""), "Desconocido"),
        anilist_id=media.get("id", 0),
        tipo="manga" if is_manga else "anime",
        volumenes_totales=media.get("volumes") or 0,
    )


class AniListScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "anilist"

    def buscar(self, nombre: str, media_type: str = "ANIME") -> Optional[AnimeData]:
        try:
            resp = _session.post(
                ANILIST_API,
                json={"query": QUERY, "variables": {"search": nombre, "type": media_type}},
                headers={"User-Agent": "AnimeTracker/2.9.0", "Accept": "application/json",
                         "Accept-Encoding": "identity"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            media = data.get("data", {}).get("Media")
            if not media:
                return None

            return _parse_media(media, nombre, self.nombre_fuente, media_type)
        except Exception:
            return None

    def buscar_manga(self, nombre: str) -> Optional[AnimeData]:
        """Búsqueda específica de manga en AniList."""
        return self.buscar(nombre, media_type="MANGA")
