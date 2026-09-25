"""
metadatos.py — Reglas únicas para actualizar metadatos de la FUENTE de un anime
(capítulos, portada, sinopsis, géneros, estado) sin empeorar lo que ya hay.

Nació de dos bugs que se repetían en varios sitios (refresco manual, refresco
de series en emisión cada 12h, enriquecimiento):
  - Se sobrescribían números buenos con "?" cuando la fuente no los sabía
    (One Piece "1179+" → "?").
  - Se sobrescribían portadas de AniList con las de anime-planet (su scraper
    toma la primera tarjeta aunque no coincida → portadas de otra serie) o de
    AnimeFLV (hotlinking 403).

Módulo sin dependencias de main.py para que migrations.py pueda usarlo.
"""
from __future__ import annotations

# Portadas que se consideran poco fiables y se sustituyen cuando hay otra mejor.
HOSTS_PORTADA_POCO_FIABLE = ("animeflv", "anime-planet")

_CAPS_DESCONOCIDOS = ("?", "", "None")
_ESTADOS_DESCONOCIDOS = ("", "Desconocido")


def portada_poco_fiable(url: str | None) -> bool:
    u = (url or "").strip().lower()
    return not u or any(h in u for h in HOSTS_PORTADA_POCO_FIABLE)


def _es_anilist(url: str | None) -> bool:
    return "anilist" in (url or "").lower()


def cambios_seguros(actual: dict, nuevo) -> dict:
    """Campos de fuente a actualizar en `actual` a partir de `nuevo` (AnimeData
    o similar) sin empeorar nada:

    - capitulos: solo si el nuevo es conocido y distinto.
    - imagen: nunca desde un host poco fiable; nunca se cambia una portada de
      AniList por otra que no sea de AniList.
    - sinopsis / genero / estado_anime: solo si el nuevo no está vacío.
    - anilist_id: solo si falta. volumenes_totales: solo si el nuevo es > 0.
    """
    cambios: dict = {}

    caps = getattr(nuevo, "capitulos", None)
    if caps is not None and str(caps) not in _CAPS_DESCONOCIDOS \
            and str(caps) != str(actual.get("capitulos") or ""):
        cambios["capitulos"] = str(caps)

    img_nueva = (getattr(nuevo, "imagen", "") or "").strip()
    img_actual = (actual.get("imagen") or "").strip()
    # Se cambia salvo que la actual sea de AniList y la nueva no.
    mejora = (portada_poco_fiable(img_actual) or _es_anilist(img_nueva)
              or not _es_anilist(img_actual))
    if img_nueva and img_nueva != img_actual and not portada_poco_fiable(img_nueva) and mejora:
        cambios["imagen"] = img_nueva

    sinopsis = (getattr(nuevo, "sinopsis", "") or "").strip()
    if sinopsis and sinopsis != (actual.get("sinopsis") or ""):
        cambios["sinopsis"] = sinopsis

    genero = getattr(nuevo, "genero", None)
    if genero:
        g = ", ".join(genero) if isinstance(genero, (list, tuple)) else str(genero)
        if g and g != (actual.get("genero") or ""):
            cambios["genero"] = g

    estado = (getattr(nuevo, "estado_anime", "") or "").strip()
    if estado not in _ESTADOS_DESCONOCIDOS and estado != (actual.get("estado_anime") or ""):
        cambios["estado_anime"] = estado

    aid = getattr(nuevo, "anilist_id", 0) or 0
    if aid and not actual.get("anilist_id"):
        cambios["anilist_id"] = aid

    vols = getattr(nuevo, "volumenes_totales", 0) or 0
    if vols and vols != (actual.get("volumenes_totales") or 0):
        cambios["volumenes_totales"] = vols

    return cambios


def resolver_en_anilist(nombre: str, tipo: str = "anime", anilist=None, jikan=None):
    """Busca un título en AniList; si no lo encuentra y es anime, prueba vía
    MyAnimeList (Jikan → mal_id → AniList `idMal`). El buscador de AniList no
    reconoce muchos romaji de MAL/AnimeFLV ("Gotoubun no Hanayome", "Isekai
    Ojisan"). Devuelve AnimeData o None. Hasta 4 AniList + 1 Jikan peticiones."""
    from scrapers import SCRAPERS
    anilist = anilist or SCRAPERS.get("anilist")
    if not anilist:
        return None
    if tipo == "manga":
        return anilist.buscar_manga(nombre)
    r = anilist.buscar(nombre)
    if r is not None:
        return r
    jikan = jikan or SCRAPERS.get("jikan")
    if jikan is None or not hasattr(jikan, "buscar_mal_id") \
            or not hasattr(anilist, "buscar_por_mal"):
        return None
    mal_id = jikan.buscar_mal_id(nombre)
    return anilist.buscar_por_mal(mal_id) if mal_id else None
