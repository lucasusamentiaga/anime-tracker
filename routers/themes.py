"""
routers/themes.py — Enriquecimiento de la ficha de un anime:
  • Openings y endings (AnimeThemes.moe)
  • Personajes y actores de voz (Jikan v4)

Ambos se cachean en memoria: ni los temas ni el reparto de un anime cambian,
así que una vez pedidos no tiene sentido volver a molestar a las APIs.
"""
from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter

import personajes_api
import themes_api
from core import executor, log
from scrapers import net

router = APIRouter(prefix="/api/animes", tags=["ficha"])

_session = net.make_session({"User-Agent": "Miraru/2.8"})
_cache: dict[str, list] = {}
_cache_personajes: dict[str, list] = {}
_lock = threading.Lock()
_CACHE_MAX = 200


def _buscar_temas(nombre: str) -> list[dict]:
    """Bloqueante: se ejecuta en el executor."""
    try:
        r = _session.get(
            themes_api.API,
            params={"filter[name]": nombre, "include": themes_api.INCLUDE},
            timeout=12,
        )
        if r.status_code != 200:
            return []
        return themes_api.parsear(r.json())
    except Exception as e:
        log.warning("animethemes '%s': %s", nombre, e)
        return []


@router.get("/{nombre:path}/themes")
async def temas_anime(nombre: str):
    """Openings y endings con enlace de vídeo directo."""
    clave = nombre.strip().lower()
    with _lock:
        if clave in _cache:
            return {"temas": _cache[clave], "cacheado": True}

    loop = asyncio.get_running_loop()
    temas = await loop.run_in_executor(executor, _buscar_temas, nombre)

    with _lock:
        # Cache con tope: evita crecer sin límite en bibliotecas grandes
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[clave] = temas
    return {"temas": temas, "cacheado": False}


def _buscar_personajes(nombre: str) -> list[dict]:
    """Bloqueante: busca el anime en Jikan y luego pide su reparto.

    Son dos llamadas porque Jikan indexa los personajes por mal_id, no por
    nombre. Al ir cacheado, el coste se paga una sola vez por anime.
    """
    try:
        r = _session.get(personajes_api.BUSCAR,
                         params={"q": nombre, "limit": 1, "sfw": "true"}, timeout=12)
        if r.status_code != 200:
            return []
        mal_id = personajes_api.primer_mal_id(r.json())
        if not mal_id:
            return []
        r2 = _session.get(personajes_api.PERSONAJES.format(mal_id=mal_id), timeout=12)
        if r2.status_code != 200:
            return []
        return personajes_api.parsear(r2.json())
    except Exception as e:
        log.warning("personajes '%s': %s", nombre, e)
        return []


@router.get("/{nombre:path}/personajes")
async def personajes_anime(nombre: str):
    """Personajes principales con su actor de voz (seiyuu)."""
    clave = nombre.strip().lower()
    with _lock:
        if clave in _cache_personajes:
            return {"personajes": _cache_personajes[clave], "cacheado": True}

    loop = asyncio.get_running_loop()
    personajes = await loop.run_in_executor(executor, _buscar_personajes, nombre)

    with _lock:
        if len(_cache_personajes) >= _CACHE_MAX:
            _cache_personajes.clear()
        _cache_personajes[clave] = personajes
    return {"personajes": personajes, "cacheado": False}
