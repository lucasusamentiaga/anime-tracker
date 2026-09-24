"""
routers/media.py — Películas y series no-anime (TMDB).

Extraído de main.py para bajar el tamaño del monolito. No importa main.py:
la infraestructura compartida (executor) vive en core.py.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db
from core import executor
from i18n import get_lang
from scrapers import tmdb as tmdb_scraper

router = APIRouter(prefix="/api/media", tags=["media"])


# ── Modelos ───────────────────────────────────────────────────────────────────

class MediaBuscarRequest(BaseModel):
    query: str


class MediaAddRequest(BaseModel):
    tmdb_id: int
    tipo: str = "pelicula"


class MediaUpdateRequest(BaseModel):
    estado_usuario:   Optional[str]   = None
    puntuacion:       Optional[float] = None
    episodios_vistos: Optional[int]   = None
    favorito:         Optional[int]   = None
    notas:            Optional[str]   = None
    rewatches:        Optional[int]   = None


class TmdbKeyRequest(BaseModel):
    api_key: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tmdb_key() -> str:
    return db.get_config("tmdb_api_key") or ""


def _tmdb_lang() -> str:
    """Mapea el idioma de la app al código ISO de TMDB."""
    return {"es": "es-ES", "en": "en-US", "fr": "fr-FR", "de": "de-DE"}.get(get_lang(), "es-ES")


# ── Endpoints ─────────────────────────────────────────────────────────────────
# OJO con el orden: las rutas literales (/tmdb-key, /stats, /tendencias) van
# ANTES que las paramétricas (/{media_id}) para que no las capturen.

@router.get("/tmdb-key")
async def get_tmdb_key():
    """Devuelve solo si hay clave configurada (no la clave en sí)."""
    return {"configured": bool(_tmdb_key())}


@router.post("/tmdb-key")
async def set_tmdb_key(req: TmdbKeyRequest):
    """Valida la clave contra TMDB antes de guardarla. Si es inválida, no la
    guarda y avisa — así el usuario detecta al momento si copió el campo erróneo
    (p.ej. el token de lectura largo en vez de la 'Clave de la API' corta)."""
    key = (req.api_key or "").strip()
    if not key:
        db.set_config("tmdb_api_key", "")
        return {"ok": True, "configured": False, "valid": False}
    loop = asyncio.get_running_loop()
    valid = await loop.run_in_executor(executor, tmdb_scraper.validar_key, key)
    if valid:
        db.set_config("tmdb_api_key", key)
    return {"ok": True, "configured": valid, "valid": valid}


@router.get("/stats")
async def media_stats():
    items = db.listar_media()
    pelis  = [m for m in items if m.get("tipo") == "pelicula"]
    series = [m for m in items if m.get("tipo") == "serie"]
    return {
        "total": len(items),
        "peliculas": len(pelis),
        "series": len(series),
        "completadas": len([m for m in items if m.get("estado_usuario") == "completado"]),
        "viendo": len([m for m in items if m.get("estado_usuario") == "viendo"]),
        "pendientes": len([m for m in items if m.get("estado_usuario") == "pendiente"]),
    }


@router.get("/tendencias")
async def tendencias_media():
    """v2.6: películas y series en tendencia esta semana (descubrimiento)."""
    key = _tmdb_key()
    if not key:
        return {"ok": False, "mensaje": "no_key"}
    loop = asyncio.get_running_loop()
    resultados = await loop.run_in_executor(executor, tmdb_scraper.tendencias, key, _tmdb_lang())
    if not resultados:
        return {"ok": False, "mensaje": "Sin tendencias"}
    return {"ok": True, "resultados": [r.__dict__ for r in resultados]}


@router.post("/buscar")
async def buscar_media(req: MediaBuscarRequest):
    """Busca películas y series en TMDB. Devuelve todos los resultados."""
    key = _tmdb_key()
    if not key:
        return {"ok": False, "mensaje": "no_key"}
    loop = asyncio.get_running_loop()
    resultados = await loop.run_in_executor(
        executor, tmdb_scraper.buscar, req.query, key, 20, _tmdb_lang())
    if not resultados:
        return {"ok": False, "mensaje": "Sin resultados"}
    return {"ok": True, "resultados": [r.__dict__ for r in resultados]}


@router.get("")
async def listar_media_endpoint():
    return {"media": db.listar_media()}


@router.post("")
async def guardar_media_endpoint(req: MediaAddRequest):
    """Añade una película/serie: pide el detalle completo a TMDB y la guarda."""
    key = _tmdb_key()
    if not key:
        raise HTTPException(400, "No hay API key de TMDB configurada")
    tipo = req.tipo if req.tipo in ("pelicula", "serie") else "pelicula"
    loop = asyncio.get_running_loop()
    detalle = await loop.run_in_executor(
        executor, tmdb_scraper.detalle, req.tmdb_id, tipo, key, _tmdb_lang())
    if not detalle:
        raise HTTPException(404, "No se pudo obtener el detalle desde TMDB")
    ok, msg = db.guardar_media(detalle.__dict__)
    if not ok:
        raise HTTPException(409 if msg == "duplicado" else 500, msg)
    return {"ok": True, "media": detalle.__dict__}


@router.patch("/{media_id}")
async def actualizar_media_endpoint(media_id: int, req: MediaUpdateRequest):
    campos = {k: v for k, v in
              (req.model_dump() if hasattr(req, "model_dump") else req.dict()).items()
              if v is not None}
    if not campos:
        raise HTTPException(400, "No hay campos para actualizar")
    ok, msg = db.actualizar_media(media_id, campos)
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True}


@router.delete("/{media_id}")
async def eliminar_media_endpoint(media_id: int):
    ok, msg = db.eliminar_media(media_id)
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True}
