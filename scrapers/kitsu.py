"""Kitsu scraper — API pública JSON de kitsu.io (sin auth requerida)."""
from __future__ import annotations

from typing import Optional

from . import net
from .base import AnimeData, BaseScraper

# Session reutilizable: pooling + reintentos con backoff
_session = net.make_session()

BASE = "https://kitsu.io/api/edge"
HEADERS = {"User-Agent": "AnimeTracker/2.6.2", "Accept": "application/vnd.api+json",
           "Accept-Encoding": "identity"}

STATUS_MAP = {
    "finished":    "Finalizado",
    "current":     "En emisión",
    "upcoming":    "Próximamente",
    "tba":         "Por confirmar",
    "unreleased":  "Sin publicar",
}


class KitsuScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "kitsu"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            resp = _session.get(
                f"{BASE}/anime",
                params={
                    "filter[text]": nombre,
                    "page[limit]": 5,
                    "fields[anime]": (
                        "canonicalTitle,titles,synopsis,"
                        "episodeCount,posterImage,status,subtype"
                    ),
                },
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("data", [])
            if not items:
                return None

            a = items[0]["attributes"]
            titulo = (
                a.get("canonicalTitle")
                or (a.get("titles") or {}).get("en")
                or (a.get("titles") or {}).get("en_jp")
                or nombre
            )
            poster = a.get("posterImage") or {}
            imagen = poster.get("large") or poster.get("medium") or ""
            sinopsis = (a.get("synopsis") or "")[:500]

            n_ep = a.get("episodeCount") or 0
            subtype = (a.get("subtype") or "").lower()
            if subtype == "movie":
                caps: int | str = "película"
            elif n_ep:
                caps = int(n_ep)
            else:
                caps = "?"

            estado = STATUS_MAP.get(a.get("status", ""), "Desconocido")

            return AnimeData(
                nombre=titulo, capitulos=caps, imagen=imagen,
                genero=[], sinopsis=sinopsis,
                fuente=self.nombre_fuente, estado_anime=estado,
            )
        except Exception:
            return None
