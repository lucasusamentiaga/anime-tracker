"""Jikan v4 scraper — API REST de MyAnimeList (v4). https://docs.api.jikan.moe/"""
from __future__ import annotations
import re
import requests
from typing import Optional
from .base import BaseScraper, AnimeData

BASE = "https://api.jikan.moe/v4"
HEADERS = {"User-Agent": "AnimeTracker/4.0"}

STATUS_MAP = {
    "Finished Airing":  "Finalizado",
    "Currently Airing": "En emisión",
    "Not yet aired":    "Próximamente",
}
SEASON_ES = {"winter":"Invierno","spring":"Primavera","summer":"Verano","fall":"Otoño"}


class JikanV4Scraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "jikan"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            resp = requests.get(
                f"{BASE}/anime",
                params={"q": nombre, "limit": 5, "sfw": True},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("data", [])
            if not items:
                return None

            a = items[0]
            titulo = a.get("title_english") or a.get("title") or nombre

            images = a.get("images") or {}
            imagen = (
                (images.get("jpg") or {}).get("large_image_url")
                or (images.get("jpg") or {}).get("image_url")
                or ""
            )

            n_ep = a.get("episodes") or 0
            atype = (a.get("type") or "").upper()
            if atype == "MOVIE":
                caps: int | str = "película"
            elif n_ep:
                caps = min(int(n_ep), 200)
            else:
                caps = "?"

            estado = STATUS_MAP.get(a.get("status", ""), a.get("status", "Desconocido"))

            generos = [g["name"] for g in (a.get("genres") or []) if g.get("name")]
            generos += [g["name"] for g in (a.get("themes") or []) if g.get("name")]
            generos = list(dict.fromkeys(g for g in generos if g))[:8]

            sinopsis = re.sub(r"\[Written by MAL Rewrite\]", "", a.get("synopsis") or "").strip()[:500]

            # Temporada
            season = a.get("season") or ""
            year   = a.get("year") or ""
            temporada = (
                f"{SEASON_ES.get(season.lower(), season)} {year}".strip()
                if season and year else ""
            )

            result = AnimeData(
                nombre=titulo, capitulos=caps, imagen=imagen,
                genero=generos, sinopsis=sinopsis,
                fuente=self.nombre_fuente, estado_anime=estado,
            )
            if temporada:
                result.__dict__["temporada"] = temporada
            return result
        except Exception:
            return None
