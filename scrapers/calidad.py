"""
scrapers/calidad.py — Detección de resultados pobres y relleno de huecos.

Problema real: los scrapers que leen HTML (animeflv, animeplanet, animeav1) se
rompen en cuanto el sitio cambia el CSS. No fallan de forma limpia: devuelven un
AnimeData con el nombre puesto pero SIN episodios, imagen, sinopsis ni géneros.
Como ese objeto es "verdadero", la búsqueda con fallback lo da por bueno y nunca
llega a probar las fuentes con API estructurada.

Aquí se decide si un resultado es demasiado pobre y se rellenan sus huecos con
datos de una fuente fiable, conservando lo que la fuente original sí acertó.

Funciones puras: no tocan la red ni la BD.
"""
from __future__ import annotations

# Campos que hacen útil una ficha. Si faltan casi todos, el resultado no sirve.
_CAMPOS = ("capitulos", "imagen", "sinopsis", "genero")

# Valores que significan "no lo sé" según el campo
_VACIOS = ("", "?", "none", "null", "desconocido")


def _tiene(anime, campo: str) -> bool:
    """True si el campo trae información aprovechable."""
    v = getattr(anime, campo, None)
    if v is None:
        return False
    if isinstance(v, (list, tuple, dict)):
        return len(v) > 0
    return str(v).strip().lower() not in _VACIOS


def puntuar(anime) -> int:
    """Cuántos campos clave trae rellenos (0 a 4). Útil para comparar fuentes."""
    if anime is None:
        return -1
    return sum(1 for c in _CAMPOS if _tiene(anime, c))


def esta_incompleto(anime, minimo: int = 2) -> bool:
    """True si la ficha es demasiado pobre como para darla por buena.

    Con el umbral por defecto basta con 2 de 4 campos: no exigimos perfección,
    solo descartar las fichas huecas que deja un scraper roto.
    """
    return puntuar(anime) < minimo


def fusionar(base, relleno):
    """Devuelve `base` con sus huecos rellenados desde `relleno`.

    Nunca pisa un dato bueno de `base`: la fuente que eligió el usuario manda,
    y la de respaldo solo aporta lo que falta. El nombre y la fuente originales
    se conservan siempre.
    """
    if base is None:
        return relleno
    if relleno is None:
        return base
    for campo in _CAMPOS + ("estado_anime",):
        if not _tiene(base, campo) and _tiene(relleno, campo):
            setattr(base, campo, getattr(relleno, campo))
    return base
