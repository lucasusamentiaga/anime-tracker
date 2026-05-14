"""
AnimeFLV scraper.
Usa requests + BeautifulSoup en lugar de Selenium para máxima
compatibilidad dentro del .exe congelado por PyInstaller.
"""
from __future__ import annotations

import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from typing import Optional
from .base import BaseScraper, AnimeData

HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}
BASE = "https://www3.animeflv.net"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS_HTTP)
    return s


def _buscar_por_nombre(nombre: str) -> Optional[str]:
    """Busca en la API de búsqueda de AnimeFLV y devuelve la URL del primer resultado."""
    try:
        s = _session()
        resp = s.get(
            f"{BASE}/browse",
            params={"q": nombre},
            timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        # Primer resultado de la lista
        item = soup.select_one("ul.ListAnimes li a")
        if item:
            return BASE + item["href"]
        return None
    except Exception:
        return None


def _slug_directo(nombre: str) -> str:
    """Genera el slug directamente desde el nombre (funciona para nombres exactos)."""
    limpio = re.sub(r"[:\-\(\)!¡¿?]", "", nombre).strip()
    return limpio.lower().replace(" ", "-")


class AnimeFLVScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "animeflv"

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        s = _session()

        # Intentar primero con slug directo
        slug = _slug_directo(nombre)
        url  = f"{BASE}/anime/{urllib.parse.quote(slug)}"

        try:
            resp = s.get(url, timeout=15)
            if resp.status_code == 404:
                # Fallback: buscar por nombre
                url = _buscar_por_nombre(nombre)
                if not url:
                    return None
                resp = s.get(url, timeout=15)
                if resp.status_code != 200:
                    return None
        except Exception:
            return None

        try:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Título
            titulo_el = soup.select_one("h1.Title")
            titulo = titulo_el.text.strip() if titulo_el else nombre

            # Imagen
            img_el = soup.select_one("div.AnimeCover img, figure.Image img")
            imagen = ""
            if img_el:
                src = img_el.get("src", "")
                imagen = src if src.startswith("http") else BASE + src

            # Géneros
            generos = [a.text.strip() for a in soup.select("nav.Nvgnrs a")]

            # Sinopsis
            desc_el = soup.select_one("div.Description p")
            sinopsis = desc_el.text.strip()[:500] if desc_el else ""

            # Estado
            estado_anime = "Desconocido"
            for span in soup.select("span.fa-tv"):
                sib = span.find_next_sibling(string=True)
                if sib:
                    estado_anime = sib.strip()
                    break
            # Alternativa
            for li in soup.select("ul.ListInfo li"):
                if "Estado" in li.text:
                    val = li.select_one("span:last-child")
                    if val:
                        estado_anime = val.text.strip()
                    break

            # Episodios
            capitulos: int | str = "película"
            tipo_el = soup.find(string=re.compile(r"Tipo", re.I))
            if tipo_el:
                parent = tipo_el.find_parent()
                if parent:
                    tipo_text = parent.get_text().lower()
                    if "película" in tipo_text or "movie" in tipo_text:
                        capitulos = "película"

            ep_el = soup.find(string=re.compile(r"Episodios", re.I))
            if ep_el:
                parent = ep_el.find_parent()
                if parent:
                    nums = re.findall(r"\d+", parent.get_text())
                    if nums:
                        n = int(nums[-1])
                        capitulos = min(n, 200) if n > 0 else "película"

            # Si no encontramos episodios, contar los episodios listados en la página
            if capitulos == "película" or capitulos == 0:
                ep_links = soup.select("ul.ListCaps li")
                if ep_links:
                    capitulos = min(len(ep_links), 200)

            return AnimeData(
                nombre=titulo,
                capitulos=capitulos,
                imagen=imagen,
                genero=generos,
                sinopsis=sinopsis,
                fuente=self.nombre_fuente,
                estado_anime=estado_anime,
            )
        except Exception:
            return None
