"""AnimePlanet scraper — requests + BeautifulSoup. https://www.anime-planet.com"""
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional
from .base import BaseScraper, AnimeData

BASE = "https://www.anime-planet.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class AnimePlanetScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "animeplanet"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})

            # Búsqueda en el listado
            resp = s.get(f"{BASE}/anime/all", params={"name": nombre}, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Primer resultado
            link_el = soup.select_one(
                "ul.cardDeck li.card a[href*='/anime/'], "
                "div.cardDeck div.card a[href*='/anime/']"
            )
            if not link_el:
                # Intentar con slug directo
                slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower().strip()).strip("-")
                resp2 = s.get(f"{BASE}/anime/{slug}", timeout=15)
                if resp2.status_code == 200:
                    return self._parse(BeautifulSoup(resp2.text, "html.parser"), nombre)
                return None

            href = link_el.get("href", "")
            url  = href if href.startswith("http") else BASE + href
            resp3 = s.get(url, timeout=15)
            if resp3.status_code != 200:
                return None
            return self._parse(BeautifulSoup(resp3.text, "html.parser"), nombre)

        except Exception:
            return None

    def _parse(self, soup: BeautifulSoup, fallback: str) -> Optional[AnimeData]:
        try:
            t_el   = soup.select_one("h1[itemprop='name'], h1.title")
            titulo = t_el.get_text(strip=True) if t_el else fallback

            img_el = soup.select_one("img.mainImg, img[itemprop='image']")
            imagen = ""
            if img_el:
                src = img_el.get("src") or img_el.get("data-src") or ""
                imagen = src if src.startswith("http") else (BASE + src if src else "")

            d_el   = soup.select_one("div[itemprop='description'], p.synopsis")
            sinopsis = d_el.get_text(strip=True)[:500] if d_el else ""

            generos = [a.get_text(strip=True) for a in soup.select("span[itemprop='genre'] a, div.tags a")][:8]

            # Episodios
            caps: int | str = "?"
            ep_text = soup.find(string=re.compile(r"Eps:"))
            if ep_text:
                nums = re.findall(r"\d+", str(ep_text.parent))
                if nums:
                    n = int(nums[0])
                    caps = min(n, 200) if n > 0 else "película"
            if soup.find(string=re.compile(r"^Movie$", re.I)):
                caps = "película"

            st_el  = soup.select_one("span.Status, div.status span")
            estado = st_el.get_text(strip=True) if st_el else "Desconocido"

            return AnimeData(
                nombre=titulo, capitulos=caps, imagen=imagen,
                genero=generos, sinopsis=sinopsis,
                fuente=self.nombre_fuente, estado_anime=estado,
            )
        except Exception:
            return None
