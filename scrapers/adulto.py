"""Filtro de contenido para adultos (v2.14.1).

Miraru se publica en la Microsoft Store con una clasificación por edades, y
la certificación de la 2.14 avisó de que el contenido que puede mostrar no
casaba con ella: las búsquedas de AniList, Kitsu y Jikan podían devolver
fichas hentai (portadas y sinopsis incluidas). Desde esta versión ninguna
búsqueda, saga, novedad ni recomendación muestra contenido marcado como
"solo adultos" en su fuente.

Qué cuenta como adulto, según lo que publica cada fuente:
  * AniList: `isAdult: true`.
  * Kitsu: `nsfw: true` o `ageRating: "R18"`.
  * Jikan / MyAnimeList: `rating` "Rx - Hentai", o los géneros
    explícitos "Hentai" / "Erotica".
  * Cualquier fuente: los géneros "Hentai" o "Erotica".

"Ecchi" NO es contenido para adultos (es la etiqueta de series como Mushoku
Tensei o High School DxD, con clasificación +16), así que no se filtra.

Funciones puras: no tocan la red y están cubiertas por tests.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

GENEROS_ADULTOS = frozenset({"hentai", "erotica", "erótica", "erotico", "erótico"})


def _como_dict(x: Any) -> dict:
    if isinstance(x, dict):
        return x
    return getattr(x, "__dict__", None) or {}


def _nombres(generos: Any) -> list[str]:
    if not generos:
        return []
    if isinstance(generos, str):
        return [g.strip() for g in generos.split(",")]
    out = []
    for g in generos:
        if isinstance(g, dict):
            g = g.get("name") or g.get("title") or ""
        out.append(str(g or "").strip())
    return out


def es_adulto(x: Any) -> bool:
    """True si la ficha (dict de una API o AnimeData) es contenido para adultos."""
    if x is None:
        return False
    d = _como_dict(x)
    attrs = d.get("attributes") if isinstance(d.get("attributes"), dict) else {}
    for fuente in (d, attrs):
        if fuente.get("isAdult") is True or fuente.get("adulto") is True or fuente.get("nsfw") is True:
            return True
        rating = str(fuente.get("rating") or fuente.get("ageRating") or "").strip().lower()
        if rating.startswith("rx") or rating == "r18":
            return True
    for clave in ("genres", "genero", "generos", "explicit_genres"):
        if any(n.lower() in GENEROS_ADULTOS for n in _nombres(d.get(clave))):
            return True
    return False


def filtrar(items: Iterable[Any]) -> list:
    """La lista sin las fichas para adultos (conserva el orden)."""
    return [i for i in (items or []) if not es_adulto(i)]


def sin_adultos(resultado: Any) -> Any:
    """None si `resultado` es para adultos; si no, el propio resultado."""
    return None if es_adulto(resultado) else resultado
