"""
routers/push.py — Endpoints de Web Push (ver push_web.py).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import push_web
from core import executor

router = APIRouter(prefix="/api/push", tags=["push"])


class _Endpoint(BaseModel):
    endpoint: str


@router.get("/vapid")
async def vapid_publica():
    """Clave pública para pushManager.subscribe(). 503 si falta pywebpush."""
    loop = asyncio.get_running_loop()
    clave = await loop.run_in_executor(executor, push_web.clave_publica)
    if not clave:
        raise HTTPException(503, "Web Push no disponible (falta pywebpush)")
    return {"key": clave}


@router.post("/subscribe")
async def suscribir(sub: dict):
    if not push_web.suscribir(sub):
        raise HTTPException(400, "Suscripción no válida")
    return {"ok": True, "suscripciones": push_web.num_suscripciones()}


@router.post("/unsubscribe")
async def desuscribir(req: _Endpoint):
    return {"ok": True, "borrada": push_web.desuscribir(req.endpoint)}


@router.get("/status")
async def estado():
    return {"disponible": push_web.DISPONIBLE,
            "suscripciones": push_web.num_suscripciones()}


@router.post("/test")
async def prueba():
    """Envía un aviso de prueba a todas las suscripciones."""
    if not push_web.num_suscripciones():
        raise HTTPException(400, "No hay ningún navegador suscrito")
    loop = asyncio.get_running_loop()
    ok, borradas = await loop.run_in_executor(
        executor, lambda: push_web.enviar(
            "Miraru", "Las notificaciones funcionan aunque cierres la pestaña.",
            tag="miraru-test"))
    return {"ok": ok > 0, "enviadas": ok, "caducadas": borradas}
