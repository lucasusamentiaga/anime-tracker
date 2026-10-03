"""
AnimeAV1 (animeav1.com) — lectura de su API de datos, sin raspar HTML.

La web antigua era un WordPress en www.animeav1.com; hoy es una app SvelteKit
en animeav1.com y el dominio con «www» ya no existe, así que el scraper viejo
devolvía siempre None. Cada página de SvelteKit expone sus datos en
`<ruta>/__data.json` con el formato «devalue» (un array plano donde los objetos
guardan índices a otras posiciones); `hidratar` lo reconstruye.

Rutas que usamos:
  /catalogo/__data.json?search=<texto>  → resultados de búsqueda
  /media/<slug>/__data.json             → ficha (id, malId, episodios, fechas…)
  /cuenta/listas/__data.json            → listas de la persona (requiere sesión)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from . import net
from .base import AnimeData, BaseScraper

BASE = "https://animeav1.com"
CDN = "https://cdn.animeav1.com"
HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# status de AnimeAV1: FINISHED 0, NOT_AIRED_YET 1, AIRING 2
_ESTADO_ANIME = {0: "Finalizado", 1: "Próximamente", 2: "En emisión"}


class ErrorAnimeAV1(Exception):
    """La web respondió con un error (p. ej. 401 sin sesión)."""

    def __init__(self, mensaje: str, status: int = 0):
        super().__init__(mensaje)
        self.status = status


def hidratar(valores: list) -> Any:
    """Reconstruye un valor serializado con «devalue» (SvelteKit)."""
    cache: dict[int, Any] = {}

    def h(i):
        if not isinstance(i, int) or isinstance(i, bool):
            return i
        if i < 0:            # -1 undefined, -2 hueco, -3 NaN, -4/-5 ±Infinity, -6 -0
            return None
        if i in cache:
            return cache[i]
        v = valores[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str):          # tipo especial: ["Date", "…"]
                etiqueta = v[0]
                if etiqueta in ("Set",):
                    r: Any = [h(x) for x in v[1:]]
                elif etiqueta == "Map":
                    r = {h(v[k]): h(v[k + 1]) for k in range(1, len(v) - 1, 2)}
                elif etiqueta == "null":             # objeto sin prototipo
                    r = {v[k]: h(v[k + 1]) for k in range(1, len(v) - 1, 2)}
                elif etiqueta == "BigInt":
                    r = int(v[1])
                else:                                # Date, RegExp, URL…
                    r = v[1] if len(v) > 1 else None
                cache[i] = r
                return r
            out: list = []
            cache[i] = out
            out.extend(h(x) for x in v)
            return out
        if isinstance(v, dict):
            obj: dict = {}
            cache[i] = obj
            for k, x in v.items():
                obj[k] = h(x)
            return obj
        cache[i] = v
        return v

    return h(0) if valores else None


def leer_datos(respuesta_json: dict) -> dict:
    """Junta en un dict los datos de todos los nodos de una página. Si algún
    nodo es un error (p. ej. 401 «No autorizado»), lanza ErrorAnimeAV1."""
    if respuesta_json.get("type") == "redirect":
        raise ErrorAnimeAV1("Redirección: " + str(respuesta_json.get("location")), 302)
    juntos: dict = {}
    for nodo in respuesta_json.get("nodes") or []:
        if not nodo:
            continue
        if nodo.get("type") == "error":
            err = nodo.get("error") or {}
            raise ErrorAnimeAV1(err.get("message") or "Error de AnimeAV1",
                                int(nodo.get("status") or 500))
        if nodo.get("type") == "data":
            valor = hidratar(nodo.get("data") or [])
            if isinstance(valor, dict):
                juntos.update(valor)
    return juntos


def sesion(cookie: str = ""):
    s = net.make_session(HEADERS_HTTP)
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def pagina(ruta: str, params: dict | None = None, s=None, timeout: int = 20) -> dict:
    s = s or sesion()
    ruta = "/" + ruta.strip("/")
    url = BASE + (ruta if ruta != "/" else "") + "/__data.json"
    resp = s.get(url, params=params or {}, timeout=timeout)
    if resp.status_code != 200:
        raise ErrorAnimeAV1(f"HTTP {resp.status_code}", resp.status_code)
    return leer_datos(resp.json())


def portada(media_id) -> str:
    return f"{CDN}/covers/{media_id}.jpg" if media_id not in (None, "") else ""


def _clave(texto: str) -> str:
    t = unicodedata.normalize("NFKC", texto or "").casefold()
    return re.sub(r"[^\w]+", "", t)


def buscar_medias(texto: str, s=None) -> list[dict]:
    datos = pagina("catalogo", {"search": texto}, s=s)
    return [r for r in (datos.get("results") or []) if isinstance(r, dict)]


def obtener_media(slug: str, s=None) -> Optional[dict]:
    datos = pagina(f"media/{slug}", s=s)
    m = datos.get("media")
    return m if isinstance(m, dict) else None


def elegir_resultado(texto: str, resultados: list[dict]) -> Optional[dict]:
    """El resultado cuyo título coincide; si ninguno coincide exactamente, el
    primero de tipo TV (AnimeAV1 ordena por relevancia)."""
    if not resultados:
        return None
    clave = _clave(texto)
    for r in resultados:
        if _clave(r.get("title") or "") == clave:
            return r
    for r in resultados:
        if r.get("categoryId") == 1:
            return r
    return resultados[0]


def a_anime_data(m: dict) -> AnimeData:
    categoria = ((m.get("category") or {}).get("slug") or "").lower()
    eps = m.get("episodesCount") or 0
    if "pelicula" in categoria or "movie" in categoria:
        capitulos: int | str = "película"
    elif isinstance(eps, int) and eps > 0:
        capitulos = f"{eps}+" if m.get("status") == 2 else eps
    else:
        capitulos = "?"
    return AnimeData(
        nombre=m.get("title") or m.get("slug") or "",
        capitulos=capitulos,
        imagen=portada(m.get("id")),
        genero=[g.get("name") for g in (m.get("genres") or [])
                if isinstance(g, dict) and g.get("name")],
        sinopsis=(m.get("synopsis") or "")[:500],
        fuente="animeav1",
        estado_anime=_ESTADO_ANIME.get(m.get("status"), "Desconocido"),
    )


class AnimeAV1Scraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "animeav1"

    def buscar_por_slug(self, slug: str) -> Optional[AnimeData]:
        try:
            m = obtener_media(slug)
            return a_anime_data(m) if m else None
        except Exception:
            return None

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            s = sesion()
            elegido = elegir_resultado(nombre, buscar_medias(nombre, s=s))
            if not elegido or not elegido.get("slug"):
                return None
            m = obtener_media(elegido["slug"], s=s)
            return a_anime_data(m) if m else None
        except Exception:
            return None
