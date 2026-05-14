from __future__ import annotations
import requests
from typing import Optional
from .base import BaseScraper, AnimeData


ANILIST_API = "https://graphql.anilist.co"

QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    title { romaji english native }
    episodes
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
            resp = requests.post(
                ANILIST_API,
                json={"query": QUERY, "variables": {"search": nombre}},
                headers={"User-Agent": "AnimeTracker/4.0", "Accept": "application/json"},
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
            capitulos: int | str = episodes if 0 < episodes <= 200 else (200 if episodes > 200 else "película")

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
