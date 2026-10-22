"""
routes/sincro.py — Sincronización externa: AniList (OAuth + pull/push), AnimeAV1 y el
canal de trabajos largos (/api/trabajos).

Extraído de main.py.
No tiene costuras con main: todo lo que usa (anilist_sync,
animeav1_sync, trabajos, db) son módulos con singleton propio.
"""

from __future__ import annotations

import asyncio
import json

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

import anilist_sync
import animeav1_sync
import database as db
import trabajos
from core import executor
from main import AnimeAV1ConectarRequest  # noqa: E402  (modelo en main)

router = APIRouter()

# ── AniList Sync ─────────────────────────────────────────────────────────────

@router.get("/api/anilist/status")
async def anilist_status():
    return anilist_sync.get_connection_info()


@router.post("/api/anilist/connect")
async def anilist_connect(req: Request):
    """Recibe client_id, client_secret, code y redirect_uri para completar OAuth2."""
    body = await req.json()
    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")
    code = body.get("code", "")
    redirect_uri = body.get("redirect_uri", "")
    if not all([client_id, client_secret, code]):
        raise HTTPException(400, "Faltan client_id, client_secret o code")
    try:
        token_data = anilist_sync.exchange_code(code, client_id, client_secret,
                                                redirect_uri)
        token = token_data.get("access_token", "")
        if not token:
            raise HTTPException(400, "No se recibió access_token")
        viewer = anilist_sync.fetch_viewer(token)
        anilist_sync.save_token(token, viewer["name"], viewer["id"])
        return {"ok": True, "username": viewer["name"], "userid": viewer["id"]}
    except HTTPException:
        raise                      # antes el 400 de arriba acababa como 500
    except requests.HTTPError as e:
        raise HTTPException(400, f"Error OAuth: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/anilist/disconnect")
async def anilist_disconnect():
    anilist_sync.disconnect()
    return {"ok": True}


def _anilist_pull_trabajo(progreso):
    try:
        return anilist_sync.pull_all(progreso)
    finally:
        db._invalidar_cache()


def _anilist_resolver_trabajo(progreso):
    try:
        return anilist_sync.resolve_anilist_ids(progreso=progreso)
    finally:
        db._invalidar_cache()


@router.post("/api/anilist/pull")
async def anilist_pull(fondo: bool = False):
    """Descarga la lista de anime + manga de AniList y sincroniza con la BD local.
    Con ?fondo=1 devuelve {"trabajo": id} al momento (ver /api/trabajos)."""
    if not anilist_sync.is_connected():
        raise HTTPException(400, "No conectado a AniList")
    if fondo:
        return {"trabajo": trabajos.lanzar("anilist-pull", _anilist_pull_trabajo)}
    from core import executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, anilist_sync.pull_all)
    db._invalidar_cache()
    return result


@router.post("/api/anilist/push")
async def anilist_push(fondo: bool = False):
    """Sube todos los animes con anilist_id a AniList."""
    if not anilist_sync.is_connected():
        raise HTTPException(400, "No conectado a AniList")
    if fondo:
        return {"trabajo": trabajos.lanzar("anilist-push", anilist_sync.push_all)}
    from core import executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, anilist_sync.push_all)
    return result


@router.post("/api/anilist/resolve-ids")
async def anilist_resolve_ids(fondo: bool = False):
    """Busca el anilist_id de animes que aún no lo tienen."""
    if fondo:
        return {"trabajo": trabajos.lanzar("anilist-resolve", _anilist_resolver_trabajo)}
    from core import executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, anilist_sync.resolve_anilist_ids)
    db._invalidar_cache()
    return result
# ── Trabajos largos con progreso (v2.12) ─────────────────────────────────────

@router.get("/api/trabajos/{tid}")
async def trabajo_estado(tid: str):
    t = trabajos.estado(tid)
    if t is None:
        raise HTTPException(404, "Ese trabajo ya no existe.")
    return t


@router.post("/api/trabajos/{tid}/cancelar")
async def trabajo_cancelar(tid: str):
    return {"ok": trabajos.cancelar(tid)}
@router.get("/api/animeav1/status")
async def animeav1_status():
    return animeav1_sync.info()


@router.post("/api/animeav1/connect")
async def animeav1_connect(req: AnimeAV1ConectarRequest):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, animeav1_sync.conectar, req.cookie)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo contactar con AnimeAV1: {e}")


@router.post("/api/animeav1/disconnect")
async def animeav1_disconnect():
    animeav1_sync.desconectar()
    return {"ok": True}


def _animeav1_trabajo(funcion):
    def correr(progreso):
        try:
            return funcion(progreso)
        except animeav1_sync.av1.ErrorAnimeAV1 as e:
            if e.status in (401, 403):
                raise RuntimeError("La sesión de AnimeAV1 ha caducado: vuelve a "
                                   "conectar tu cuenta con una cookie nueva.") from e
            raise RuntimeError(f"AnimeAV1 respondió con un error ({e}).") from e
        finally:
            db._invalidar_cache()
    return correr


@router.post("/api/animeav1/pull")
async def animeav1_pull():
    if not animeav1_sync.is_connected():
        raise HTTPException(400, "No conectado a AnimeAV1")
    return {"trabajo": trabajos.lanzar("animeav1-pull", _animeav1_trabajo(animeav1_sync.pull))}


@router.post("/api/animeav1/push")
async def animeav1_push():
    if not animeav1_sync.is_connected():
        raise HTTPException(400, "No conectado a AnimeAV1")
    return {"trabajo": trabajos.lanzar("animeav1-push", _animeav1_trabajo(animeav1_sync.push))}
@router.get("/api/anilist/callback")
async def anilist_callback(code: str = ""):
    """Callback OAuth2 — AniList redirige aquí con ?code=..."""
    if not code:
        return HTMLResponse("<h2>Error: no se recibió código de autorización</h2>")
    # El código va dentro de un <script>: json.dumps lo convierte en un literal
    # JS válido (antes '{code}' se rompía con una comilla) y "</" se escapa para
    # que no pueda cerrar la etiqueta.
    code_js = json.dumps(code[:2048]).replace("</", "<\\/")
    # Devolver una página que envía el code al frontend vía postMessage o JS
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Conectando con AniList...</title>
<style>body{{background:#0f0f13;color:#e2e2e8;font-family:system-ui;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}}
.box{{text-align:center;padding:40px;background:#1a1a24;border-radius:16px;
border:1px solid #2a2a38;max-width:400px}}
h2{{color:#a78bfa;margin-bottom:12px}}p{{color:#6b6b88;font-size:14px}}
</style></head><body><div class="box">
<h2>✅ Conectado con AniList</h2>
<p>Código recibido. Guardando...</p>
<script>
fetch('/api/anilist/connect', {{
  method: 'POST',
  headers: {{'Content-Type': 'application/json'}},
  body: JSON.stringify({{
    code: {code_js},
    client_id: localStorage.getItem('anilist_client_id') || '',
    client_secret: localStorage.getItem('anilist_client_secret') || '',
    redirect_uri: window.location.origin + '/api/anilist/callback'
  }})
}}).then(r => r.json()).then(d => {{
  if (d.ok) {{
    document.querySelector('p').textContent =
      'Conectado como ' + d.username + '. Puedes cerrar esta pestaña.';
  }} else {{
    document.querySelector('p').textContent = 'Error: ' + JSON.stringify(d);
  }}
}}).catch(e => {{
  document.querySelector('p').textContent = 'Error: ' + e.message;
}});
</script></div></body></html>""")
