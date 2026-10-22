"""
routes/notificaciones.py — Notificaciones: configuración de email de avisos y consulta de
episodios nuevos por campanita (/api/notif/*).

Extraído de main.py.
Los helpers de envío (_enviar_email y familia) y el fetch de últimos
episodios viven en main porque también los usa el daemon de fondo y
los tests los llaman/parchean ahí → se accede via `main.X`.
"""

from __future__ import annotations

import asyncio
import time as _time

from fastapi import APIRouter, HTTPException

import database as db
import main  # circular a propósito: nombres de main se leen al servir
from core import executor
from main import EmailConfigRequest  # noqa: E402  (modelo en main)

router = APIRouter()

# ── Notificaciones por email (nuevos episodios) ───────────────────────────────
@router.post("/api/notif/config-email")
async def config_email(req: EmailConfigRequest):
    """Guarda credenciales Gmail para notificaciones."""
    if not req.gmail_user.endswith("@gmail.com"):
        raise HTTPException(400, "Solo se admiten cuentas @gmail.com")
    if len(req.gmail_app_password.replace(" ","")) != 16:
        raise HTTPException(400, "La contraseña de app de Gmail tiene 16 caracteres.")
    db.set_config("gmail_user", req.gmail_user.strip())
    # Guardar contraseña ofuscada (no encriptada, solo local)
    db.set_config("gmail_app_pass", req.gmail_app_password.replace(" ",""))
    return {"ok": True}

@router.get("/api/notif/config-email")
async def get_email_config():
    return {
        "gmail_user":    db.get_config("gmail_user") or "",
        "configurado":   bool(db.get_config("gmail_user") and db.get_config("gmail_app_pass")),
    }

@router.post("/api/notif/test-email")
async def test_email():
    """Envía un email de prueba."""
    ok, msg = main._enviar_email_prueba()
    if not ok:
        raise HTTPException(500, msg)
    return {"ok": True, "msg": msg}
@router.get("/api/notif/activas")
async def notif_activas():
    return {"animes": db.listar_con_notif()}
@router.get("/api/notif/check")
async def notif_check():
    """v2: devuelve solo animes con notif_activa cuyo último episodio emitido
    sea mayor que episodios_vistos. Antes la UI notificaba CADA 30min a todos
    los animes en emisión, dieran o no nuevo episodio."""
    activos = db.listar_con_notif()
    if not activos:
        return {"pendientes": []}
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(executor, main._fetch_ultimos_episodios, activos)

    pendientes = []
    now_ts = _time.time()
    for a in activos:
        meta = info.get(a["nombre"])
        if not meta:
            continue
        # nextAiringEpisode.episode es el SIGUIENTE ep; el último emitido es ese-1
        next_ep = meta.get("next_ep") or 0
        next_at = meta.get("next_at") or 0
        # Si hay nextAiringEpisode futuro, el último emitido = next_ep - 1
        # Si no hay (anime terminado), usamos episodes totales
        if next_ep and next_at > now_ts:
            ultimo_emitido = max(0, int(next_ep) - 1)
        else:
            ultimo_emitido = int(meta.get("total") or 0)
        vistos = int(a.get("episodios_vistos") or 0)
        if ultimo_emitido > vistos:
            pendientes.append({
                "nombre":          a["nombre"],
                "imagen":          a.get("imagen") or "",
                "episodios_vistos": vistos,
                "ultimo_emitido":  ultimo_emitido,
                "siguiente":       vistos + 1,
            })
    return {"pendientes": pendientes}
