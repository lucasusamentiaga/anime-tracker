"""
fuentes_respaldo.py — Plan B cuando AniList no responde.

Motivo: AniList es la fuente principal de Novedades, Recomendaciones y de las
portadas del modo principiante. En agosto de 2026 su API empezó a devolver
403 "The AniList API has been temporarily disabled due to severe stability
issues", y como `_anilist()` se tragaba el fallo devolviendo {}, la app
mostraba "Sin resultados. Comprueba tu conexión" — culpando al usuario de una
caída ajena. Estas pantallas quedaban en blanco sin explicación.

Aquí vive el respaldo sobre **Kitsu**, que cubre los tres casos y además
entrega los enlaces de streaming en la misma petición (`include=streamingLinks`),
así que el filtro por plataforma de Novedades sigue funcionando degradado.

Las funciones devuelven exactamente la misma forma de diccionario que sus
equivalentes de AniList en main.py, para que el frontend no note el cambio.
`plataforma_desde_url` y `genero_a_categoria` son puras y están cubiertas por
tests sin tocar la red.
"""
from __future__ import annotations

import re

from scrapers.net import make_session

KITSU = "https://kitsu.io/api/edge"

_HEADERS = {
    "Accept": "application/vnd.api+json",
    "User-Agent": "Miraru/2.8.1",
}

# Nombres tal y como los espera el frontend (streaming_map de main.py).
_PLATAFORMAS = (
    ("crunchyroll.com", "Crunchyroll"),
    ("netflix.com",     "Netflix"),
    ("primevideo.com",  "Amazon Prime Video"),
    ("amazon.com",      "Amazon Prime Video"),
    ("amazon.co",       "Amazon Prime Video"),
    ("disneyplus.com",  "Disney Plus"),
    ("hulu.com",        "Hulu"),
    ("funimation.com",  "Funimation"),
    ("hidive.com",      "HIDIVE"),
)

# Lo que manda el frontend (?plataforma=...) -> nombre canónico de la plataforma.
_ALIAS_PLATAFORMA = {
    "crunchyroll": "Crunchyroll",
    "netflix":     "Netflix",
    "amazon":      "Amazon Prime Video",
    "disney":      "Disney Plus",
    "funimation":  "Funimation",
    "hidive":      "HIDIVE",
}

# El vocabulario de géneros de AniList no coincide con los slugs de Kitsu.
_CATEGORIAS = {
    "sci-fi":         "science-fiction",
    "slice of life":  "slice-of-life",
    "mahou shoujo":   "magical-girls",
    "psychological":  "psychological",
    "supernatural":   "supernatural",
}


def plataforma_desde_url(url: str) -> str:
    """Deduce la plataforma de streaming a partir del dominio del enlace.

    Kitsu no da el nombre del servicio, solo la URL, así que se infiere.
    Devuelve "" si el dominio no es de un servicio conocido.
    """
    u = (url or "").lower()
    for dominio, nombre in _PLATAFORMAS:
        if dominio in u:
            return nombre
    return ""


def genero_a_categoria(genero: str) -> str:
    """Traduce un género de AniList al slug de categoría de Kitsu."""
    g = (genero or "").strip().lower()
    if not g:
        return ""
    return _CATEGORIAS.get(g, g.replace(" ", "-"))


def _limpiar(texto: str, limite: int) -> str:
    return re.sub(r"<[^>]+>", "", texto or "")[:limite]


def _puntuacion(attrs: dict) -> float:
    """Kitsu da averageRating como string 0-100; la app usa 0-10."""
    try:
        return round(float(attrs.get("averageRating") or 0) / 10, 1)
    except (TypeError, ValueError):
        return 0.0


def _indexar_incluidos(payload: dict) -> tuple[dict, dict]:
    """Separa el bloque `included` de JSON:API en enlaces y categorías."""
    enlaces, categorias = {}, {}
    for it in payload.get("included") or []:
        attrs = it.get("attributes") or {}
        if it.get("type") == "streamingLinks":
            enlaces[it.get("id")] = attrs.get("url", "")
        elif it.get("type") == "categories":
            categorias[it.get("id")] = attrs.get("title", "")
    return enlaces, categorias


def _relacionados(item: dict, clave: str) -> list:
    rel = ((item.get("relationships") or {}).get(clave) or {}).get("data") or []
    return [r.get("id") for r in rel if isinstance(r, dict)]


def _get(session, path: str, params: dict, timeout: int) -> dict:
    r = session.get(f"{KITSU}/{path}", params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"Kitsu HTTP {r.status_code}")
    return r.json()


def novedades(plataforma: str = "all", timeout: int = 20) -> list[dict]:
    """Animes en emisión ordenados por popularidad, con sus plataformas.

    Misma forma que `_fetch_novedades` de main.py.
    """
    session = make_session(_HEADERS)
    payload = _get(session, "anime", {
        "filter[status]": "current",
        "sort": "-userCount",
        "page[limit]": 20,
        "include": "streamingLinks,categories",
    }, timeout)

    enlaces, categorias = _indexar_incluidos(payload)
    resultados = []

    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        plats = []
        for lid in _relacionados(item, "streamingLinks"):
            nombre_plat = plataforma_desde_url(enlaces.get(lid, ""))
            if nombre_plat and nombre_plat not in plats:
                plats.append(nombre_plat)

        if plataforma and plataforma != "all":
            objetivo = _ALIAS_PLATAFORMA.get(plataforma.lower())
            if objetivo and objetivo not in plats:
                continue

        generos = [categorias[c] for c in _relacionados(item, "categories")
                   if c in categorias]

        resultados.append({
            "nombre":      attrs.get("canonicalTitle") or "?",
            "imagen":      (attrs.get("posterImage") or {}).get("large")
                           or (attrs.get("posterImage") or {}).get("medium") or "",
            "generos":     generos[:4],
            "estado":      "RELEASING",
            "capitulos":   attrs.get("episodeCount") or "?",
            "puntuacion":  _puntuacion(attrs),
            "plataformas": plats[:4],
            "sinopsis":    _limpiar(attrs.get("synopsis"), 300),
            "proximo_ep":  None,      # Kitsu no publica el próximo episodio
        })

    resultados.sort(key=lambda x: -x["puntuacion"])
    return resultados


def recomendaciones(generos: list, existentes: set, timeout: int = 20) -> list[dict]:
    """Animes populares de los géneros dados, excluyendo los que ya tiene.

    Misma forma que `_fetch_recomendaciones` de main.py.
    """
    session = make_session(_HEADERS)
    cats = [genero_a_categoria(g) for g in (generos or []) if g]
    cats = [c for c in cats if c][:3]
    if not cats:
        cats = ["action"]

    params = {
        "filter[categories]": ",".join(cats),
        "sort": "-userCount",
        "page[limit]": 20,
        "include": "categories",
    }
    payload = _get(session, "anime", params, timeout)
    _, categorias = _indexar_incluidos(payload)

    recos = []
    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        titulo = attrs.get("canonicalTitle") or ""
        if not titulo or titulo.lower().strip() in existentes:
            continue
        gens = [categorias[c] for c in _relacionados(item, "categories")
                if c in categorias]
        estado = {"current": "En emisión", "finished": "Finalizado",
                  "upcoming": "Próximamente"}.get(attrs.get("status", ""), "")
        recos.append({
            "nombre":            titulo,
            "imagen":            (attrs.get("posterImage") or {}).get("large")
                                 or (attrs.get("posterImage") or {}).get("medium") or "",
            "genero":            ", ".join(gens[:4]),
            "sinopsis":          _limpiar(attrs.get("synopsis"), 250),
            "episodios":         attrs.get("episodeCount") or "?",
            "puntuacion_global": _puntuacion(attrs),
            "estado_anime":      estado,
            "link":              f"https://kitsu.app/anime/{attrs.get('slug', '')}",
            "trending":          attrs.get("userCount") or 0,
        })

    recos.sort(key=lambda x: -x["trending"])
    return recos


def ficha_por_titulo(titulo: str, timeout: int = 15) -> dict:
    """Busca un anime por título y devuelve portada/sinopsis/episodios.

    Misma forma que los valores de `_anilist_por_ids` de main.py. Se usa para
    rellenar las portadas del modo principiante, cuyos ids son de AniList y por
    tanto no sirven contra Kitsu: hay que buscar por nombre.
    """
    session = make_session(_HEADERS)
    payload = _get(session, "anime", {
        "filter[text]": titulo,
        "page[limit]": 1,
    }, timeout)
    datos = payload.get("data") or []
    if not datos:
        return {}
    attrs = datos[0].get("attributes") or {}
    estado = {"current": "En emisión", "finished": "Finalizado",
              "upcoming": "Próximamente"}.get(attrs.get("status", ""), "")
    return {
        "imagen":            (attrs.get("posterImage") or {}).get("large")
                             or (attrs.get("posterImage") or {}).get("medium") or "",
        "sinopsis":          _limpiar(attrs.get("synopsis"), 300),
        "episodios":         attrs.get("episodeCount") or "?",
        "puntuacion_global": _puntuacion(attrs),
        "link":              f"https://kitsu.app/anime/{attrs.get('slug', '')}",
        "estado_anime":      estado,
    }
