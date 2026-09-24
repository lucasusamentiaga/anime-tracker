"""Crunchyroll scraper — API pública v2 con token anónimo en caché."""
from __future__ import annotations

import re
import time
from typing import Optional

from . import net
from .base import AnimeData, BaseScraper

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
SEARCH_API = "https://www.crunchyroll.com/content/v2/discover/search"
TOKEN_URL  = "https://www.crunchyroll.com/auth/v1/token"

# Session con reintentos (antes se usaba requests.get/post suelto, sin reintentos)
_session = net.make_session()

_tok: dict = {"v": None, "exp": 0.0}


def _get_token() -> Optional[str]:
    if _tok["v"] and time.time() < _tok["exp"]:
        return _tok["v"]
    try:
        r = _session.post(
            TOKEN_URL,
            headers={"User-Agent": UA, "Authorization": "Basic Y3Jfd2ViOg==",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_id"},
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            _tok["v"] = d.get("access_token")
            _tok["exp"] = time.time() + d.get("expires_in", 300) - 30
            return _tok["v"]
    except Exception as _e:
        import logging
        logging.getLogger("crunchyroll").debug("Token fetch failed: %s", _e)
    return None


class CrunchyrollScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "crunchyroll"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            tok = _get_token()
            hdrs = {"User-Agent": UA, "Accept": "application/json"}
            if tok:
                hdrs["Authorization"] = f"Bearer {tok}"

            resp = _session.get(
                SEARCH_API,
                params={"q": nombre, "n": 6, "type": "series", "locale": "es-ES"},
                headers=hdrs, timeout=15,
            )
            if resp.status_code not in (200, 206):
                return None

            items = []
            for grp in resp.json().get("data", []):
                items.extend(grp.get("items", []))
            if not items:
                return None

            a    = items[0]
            meta = a.get("series_metadata") or a

            titulo = re.sub(r"\s*\((Dub|Sub|[A-Z]{2})\)\s*$", "", a.get("title", nombre)).strip()

            # Imagen de mayor resolución disponible
            imagen = ""
            for key in ("poster_tall", "poster_wide", "thumbnail"):
                arr = a.get("images", {}).get(key) or []
                flat = arr[0] if arr and isinstance(arr[0], list) else arr
                if flat:
                    best = max(flat, key=lambda x: x.get("width", 0), default=None)
                    if best and best.get("source"):
                        imagen = best["source"]
                        break

            n_ep = meta.get("episode_count") or 0
            caps: int | str = int(n_ep) if n_ep else "?"
            estado = "En emisión" if meta.get("is_simulcast") else "Finalizado"
            generos = meta.get("genres") or []
            sinopsis = (a.get("description") or "")[:500]

            return AnimeData(
                nombre=titulo, capitulos=caps, imagen=imagen,
                genero=generos if isinstance(generos, list) else [],
                sinopsis=sinopsis, fuente=self.nombre_fuente, estado_anime=estado,
            )
        except Exception:
            return None
