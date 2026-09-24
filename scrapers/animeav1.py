"""
AnimeAV1 scraper — requests + BeautifulSoup, sin Selenium.
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from . import net
from .base import AnimeData, BaseScraper

HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}
BASE = "https://www.animeav1.com"


class AnimeAV1Scraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "animeav1"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            s = net.make_session(HEADERS_HTTP)

            # Buscar
            resp = s.get(
                BASE,
                params={"s": nombre},
                timeout=15,
            )
            soup = BeautifulSoup(resp.text, "html.parser")

            # Primer resultado
            primer = soup.select_one("article.post h2 a, .search-result a, h2.entry-title a")
            if not primer:
                return None

            url_anime = primer.get("href", "")
            if not url_anime:
                return None

            resp2 = s.get(url_anime, timeout=15)
            if resp2.status_code != 200:
                return None

            soup2 = BeautifulSoup(resp2.text, "html.parser")

            # Título
            titulo_el = soup2.select_one("h1.entry-title, h1.anime-title, h1")
            titulo = titulo_el.text.strip() if titulo_el else nombre

            # Imagen
            img_el = soup2.select_one("img.thumbnail, div.anime-cover img, .entry-content img")
            imagen = ""
            if img_el:
                src = img_el.get("src", "")
                imagen = src if src.startswith("http") else BASE + src

            # Géneros
            generos = [
                a.text.strip()
                for a in soup2.select("a[rel='category tag'], .genres a, .tags a")
            ]

            # Sinopsis
            desc_el = soup2.select_one("div.sinopsis, div.entry-content p, .description")
            sinopsis = desc_el.text.strip()[:500] if desc_el else ""

            # Episodios
            capitulos: int | str = 0
            ep_text = soup2.get_text()
            nums = re.findall(r"(?:episodios?|eps?)[:\s]+(\d+)", ep_text, re.I)
            if nums:
                n = int(nums[0])
                if n > 0:
                    capitulos = n

            if not capitulos:
                ep_links = soup2.select("a[href*='episodio'], a[href*='episode'], .ep-list a")
                if ep_links:
                    capitulos = len(ep_links)

            if not capitulos:
                capitulos = "?"

            return AnimeData(
                nombre=titulo,
                capitulos=capitulos,
                imagen=imagen,
                genero=generos,
                sinopsis=sinopsis,
                fuente=self.nombre_fuente,
                estado_anime="Desconocido",
            )
        except Exception:
            return None
