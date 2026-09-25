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

# Enriquecimiento de la ficha (no crítico): 1 reintento y timeout corto. Con
# los 3 reintentos por defecto y timeout 12s, una API caída (AnimeThemes a
# veces) dejaba la petición colgada ~53s.
_session = net.make_session({"User-Agent": "Miraru/2.8"}, total=1, backoff=0.3)
_TIMEOUT = 8
_cache: dict[str, list] = {}
_cache_personajes: dict[str, list] = {}
_lock = threading.Lock()
_CACHE_MAX = 200


def _buscar_temas(nombre: str) -> list[dict] | None:
    """Bloqueante: se ejecuta en el executor. None = error (no se cachea)."""
    try:
        r = _session.get(
            themes_api.API,
            params={"filter[name]": nombre, "include": themes_api.INCLUDE},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        return themes_api.parsear(r.json())
    except Exception as e:
        log.warning("animethemes '%s': %s", nombre, e)
        return None


@router.get("/{nombre:path}/themes")
async def temas_anime(nombre: str):
    """Openings y endings con enlace de vídeo directo."""
    clave = nombre.strip().lower()
    with _lock:
        if clave in _cache:
            return {"temas": _cache[clave], "cacheado": True}

    loop = asyncio.get_running_loop()
    temas = await loop.run_in_executor(executor, _buscar_temas, nombre)
    if temas is None:
        # Fallo de red/API: no cachear, para reintentar la próxima vez
        return {"temas": [], "cacheado": False, "error": True}

    with _lock:
        # Cache con tope: evita crecer sin límite en bibliotecas grandes
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[clave] = temas
    return {"temas": temas, "cacheado": False}


def _buscar_personajes(nombre: str) -> list[dict] | None:
    """Bloqueante: busca el anime en Jikan y luego pide su reparto.

    Son dos llamadas porque Jikan indexa los personajes por mal_id, no por
    nombre. Al ir cacheado, el coste se paga una sola vez por anime.
    None = error de red/API (no se cachea); [] = no hay personajes.
    """
    try:
        r = _session.get(personajes_api.BUSCAR,
                         params={"q": nombre, "limit": 1, "sfw": "true"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        mal_id = personajes_api.primer_mal_id(r.json())
        if not mal_id:
            return []
        r2 = _session.get(personajes_api.PERSONAJES.format(mal_id=mal_id), timeout=_TIMEOUT)
        if r2.status_code != 200:
            return None
        return personajes_api.parsear(r2.json())
    except Exception as e:
        log.warning("personajes '%s': %s", nombre, e)
        return None


@router.get("/{nombre:path}/personajes")
async def personajes_anime(nombre: str):
    """Personajes principales con su actor de voz (seiyuu)."""
    clave = nombre.strip().lower()
    with _lock:
        if clave in _cache_personajes:
            return {"personajes": _cache_personajes[clave], "cacheado": True}

    loop = asyncio.get_running_loop()
    personajes = await loop.run_in_executor(executor, _buscar_personajes, nombre)
    if personajes is None:
        return {"personajes": [], "cacheado": False, "error": True}

    with _lock:
        if len(_cache_personajes) >= _CACHE_MAX:
            _cache_personajes.clear()
        _cache_personajes[clave] = personajes
    return {"personajes": personajes, "cacheado": False}
