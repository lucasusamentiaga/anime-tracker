"""
routes/movil.py — Endpoints de la app móvil: ping/descubrimiento, auth por PIN y CRUD
autenticado con token.

Extraído de main.py. OJO: el estado de
sesión (tokens, PIN, rate-limiter) y _require_auth viven en main y los
tests los parchean ahí → se accede siempre via `main.X`.
"""

from __future__ import annotations

import re
import time as _time
from collections import Counter

from fastapi import APIRouter, HTTPException, Request

import database as db
import main  # circular a propósito: nombres de main se leen al servir
import sheets_sync
from core import VERSION
from main import ActualizarRequest, PinRequest  # noqa: E402

router = APIRouter()


# ── API Móvil ────────────────────────────────────────────────────────────────

@router.get("/api/mobile/ping")
async def mobile_ping():
    """El móvil usa esto para descubrir el servidor en la red local.

    `app` conserva el identificador histórico a propósito: las apps móviles ya
    instaladas comprueban exactamente ese valor y cambiarlo las dejaría sin
    poder conectar. El nombre actual va en `name`."""
    return {"app": "AnimeTracker", "name": "Miraru", "version": VERSION, "ok": True}

@router.post("/api/mobile/auth")
async def mobile_auth(req: PinRequest, request: Request):
    """Autenticación con PIN de 4-8 dígitos configurado en PC. Rate-limited por IP."""
    ip = main._client_ip(request)
    ok, motivo = main._auth_rate_check(ip)
    if not ok:
        raise HTTPException(429, motivo)

    stored_pin = db.get_config("mobile_pin")
    if not stored_pin:
        raise HTTPException(403, "El PIN móvil no está configurado. Actívalo en Ajustes de la app de PC.")

    if not main._check_pin(req.pin, stored_pin):
        main._auth_record_fail(ip)
        raise HTTPException(403, "PIN incorrecto.")

    main._auth_record_ok(ip)
    token = main._gen_token()
    main._mobile_tokens[token] = _time.time() + main._TOKEN_TTL
    return {"ok": True, "token": token, "expira_en": int(_time.time() + main._TOKEN_TTL)}

@router.post("/api/mobile/set-pin")
async def set_mobile_pin(req: PinRequest):
    """Configura el PIN. Protegido por el middleware: en modo móvil exige
    loopback o token válido (en v1 cualquiera en LAN podía cambiarlo)."""
    pin = req.pin.strip()
    if not (4 <= len(pin) <= 8) or not pin.isdigit():
        raise HTTPException(400, "El PIN debe tener entre 4 y 8 dígitos.")
    db.set_config("mobile_pin", main._hash_pin(pin))
    # Invalidar todos los tokens existentes al cambiar PIN
    main._mobile_tokens.clear()
    return {"ok": True}

@router.get("/api/mobile/status")
async def mobile_status():
    """Estado del acceso móvil — sin auth para que el setup de PC funcione."""
    pin_set = bool(db.get_config("mobile_pin"))
    return {
        "pin_configurado": pin_set,
        "tokens_activos":  len(main._mobile_tokens),
        "network_host":    db.get_config("network_host") or "",
    }

# ── Endpoints móvil autenticados (misma lógica que PC pero con auth) ─────────

@router.get("/api/mobile/animes")
async def mobile_listar(request: Request):
    main._require_auth(request)
    return {"animes": db.listar_animes()}

@router.patch("/api/mobile/animes/{nombre:path}")
async def mobile_actualizar(nombre: str, req: ActualizarRequest, request: Request):
    main._require_auth(request)
    campos = {k: v for k, v in (req.model_dump() if hasattr(req, "model_dump") else req.dict()).items() if v is not None}
    if not campos:
        raise HTTPException(400, "Sin campos")
    ok, msg = db.actualizar_anime(nombre, campos)
    if not ok:
        raise HTTPException(404, msg)
    cfg = main._get_sheets_config()
    if cfg:
        anime_dict = db.obtener_anime(nombre)
        if anime_dict:
            main._sync_bg(sheets_sync.update_anime_row, anime_dict, cfg[0], cfg[1])
    return {"ok": True}

@router.post("/api/mobile/animes/{nombre:path}/plus1")
async def mobile_plus1(nombre: str, request: Request):
    main._require_auth(request)
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevos = (anime.get("episodios_vistos") or 0) + 1
    db.actualizar_anime(nombre, {"episodios_vistos": nuevos})
    cfg = main._get_sheets_config()
    if cfg:
        updated = db.obtener_anime(nombre)
        if updated:
            main._sync_bg(sheets_sync.update_anime_row, updated, cfg[0], cfg[1])
    return {"ok": True, "episodios_vistos": nuevos}

@router.get("/api/mobile/stats")
async def mobile_stats(request: Request):
    main._require_auth(request)
    # Reutilizar la misma lógica que el endpoint de estadísticas de PC
    animes = db.listar_animes()
    by_state: dict = {}
    scores = []
    total_eps = 0
    genres: Counter = Counter()
    for a in animes:
        st = a.get("estado_usuario", "pendiente")
        by_state[st] = by_state.get(st, 0) + 1
        if a.get("puntuacion"):
            scores.append(float(a["puntuacion"]))
        # Mismo criterio que /api/stats: un anime "completado" cuenta todos sus
        # capitulos aunque nunca se incrementara episodios_vistos a mano.
        caps_raw    = str(a.get("capitulos") or "").strip().lower()
        es_pelicula = "pel" in caps_raw
        nums        = re.findall(r"\d+", caps_raw)
        caps_total  = int(nums[0]) if nums else 0
        ep_vistos   = int(a.get("episodios_vistos") or 0)
        completado  = st in ("completado", "completed")
        if es_pelicula:
            if completado or ep_vistos > 0:
                total_eps += 1
        else:
            total_eps += max(ep_vistos, caps_total) if completado else ep_vistos
        for g in (a.get("genero") or "").split(","):
            g = g.strip()
            if g: genres[g] += 1
    return {
        "total": len(animes),
        "total_episodes": total_eps,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "by_state": by_state,
        "top_generos": [g for g, _ in genres.most_common(5)],
    }

@router.post("/api/mobile/enable")
async def enable_mobile(req: PinRequest):
    """Activa el modo red y configura el PIN en un solo paso."""
    pin = req.pin.strip()
    if not (4 <= len(pin) <= 8) or not pin.isdigit():
        raise HTTPException(400, "PIN debe tener 4-8 dígitos.")
    db.set_config("mobile_pin", main._hash_pin(pin))
    db.set_config("mobile_enabled", "1")
    main._mobile_tokens.clear()
    return {
        "ok": True,
        "mensaje": "Reinicia la app para activar el acceso de red.",
        "network_host": db.get_config("network_host") or "desconocido (reinicia primero)",
    }

@router.post("/api/mobile/disable")
async def disable_mobile():
    """Desactiva el modo red y limpia tokens."""
    db.set_config("mobile_enabled", "0")
    db.set_config("mobile_pin", "")
    main._mobile_tokens.clear()
    return {"ok": True, "mensaje": "Acceso móvil desactivado. Reinicia la app."}
