from __future__ import annotations

from typing import Optional

from . import net
from .base import AnimeData, BaseScraper

# Session reutilizable: pooling + reintentos con backoff
_session = net.make_session()


JIKAN_BASE = "https://api.jikan.moe/v4"


class MALScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "mal"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            resp = _session.get(
                f"{JIKAN_BASE}/anime",
                params={"q": nombre, "limit": 1},
                headers={"User-Agent": "AnimeTracker/2.6.2", "Accept-Encoding": "identity"},
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json().get("data", [])
            if not results:
                return None

            anime = results[0]
            episodes = anime.get("episodes") or 0
            atype = (anime.get("type") or "").upper()
            if atype == "MOVIE":
                capitulos: int | str = "película"
            elif episodes > 0:
                capitulos = episodes
            else:
                capitulos = "?"

            status_map = {
                "Finished Airing": "Finalizado",
                "Currently Airing": "En emisión",
                "Not yet aired": "Sin estrenar",
            }

            generos = [g["name"] for g in anime.get("genres", [])]

            return AnimeData(
                nombre=anime.get("title_english") or anime.get("title", nombre),
                capitulos=capitulos,
                imagen=anime.get("images", {}).get("jpg", {}).get("large_image_url", ""),
                genero=generos,
                sinopsis=(anime.get("synopsis") or "")[:500],
                fuente=self.nombre_fuente,
                estado_anime=status_map.get(anime.get("status", ""), "Desconocido"),
            )
        except Exception:
            return None
