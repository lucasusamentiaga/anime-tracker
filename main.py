"""
main.py — FastAPI app principal.
Resuelve rutas desde ANIME_FROZEN_DIR (sys._MEIPASS en el .exe).
"""
from __future__ import annotations

# stdlib — sorted alphabetically for clarity
import asyncio
import csv
import datetime
import hashlib
import hmac
import io
import json
import logging as _logging
import os
import random
import re
import secrets
import smtplib
import sqlite3
import tempfile
import threading
import time as _time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, OrderedDict
from contextlib import asynccontextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape as _esc
from pathlib import Path
from typing import Optional

import requests


# ── Logging persistente en disco ──────────────────────────────────────────────
def _setup_file_logging() -> None:
    """Añade RotatingFileHandler para guardar warnings+ en %APPDATA%/AnimeTracker/app.log"""
    try:
        import logging.handlers as _lh
        log_dir = Path(os.environ.get("APPDATA", Path.home())) / "AnimeTracker"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = _lh.RotatingFileHandler(
            log_dir / "app.log", maxBytes=500_000, backupCount=2, encoding="utf-8"
        )
        fh.setLevel(_logging.WARNING)
        fh.setFormatter(_logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _logging.getLogger().addHandler(fh)
    except Exception:
        pass

_setup_file_logging()

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import anilist_sync
import database as db
import metadatos
import sheets_sync
from i18n import TRANSLATIONS, get_lang, set_lang
from scrapers import SCRAPERS, AnimeData
from scrapers.anilist import ANILIST_MIN_INTERVAL, candidatos_busqueda

# ── Rutas ─────────────────────────────────────────────────────────────────────
FROZEN_DIR    = Path(os.environ.get("ANIME_FROZEN_DIR", Path(__file__).parent))
APP_DIR       = Path(os.environ.get("ANIME_APP_DIR",    Path(__file__).parent))
TEMPLATES_DIR = FROZEN_DIR / "templates"
STATIC_DIR    = FROZEN_DIR / "static"
CREDENTIALS   = APP_DIR / "credentials.json"

# ── Init ──────────────────────────────────────────────────────────────────────
# La inicialización de la BD y la restauración de idioma se hacen al arrancar el
# servidor (ver _lifespan), no al importar el módulo: importar main NO debe tener
# efectos de disco (hace los tests frágiles y puede romper en arranques donde la
# ruta de la BD aún no es escribible).

# La versión vive en core.py y solo ahí; aquí se reexporta para no romper a
# quien haga `from main import VERSION`.
from core import VERSION  # noqa: E402


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Arranque y apagado del servidor.

    Sustituye a `@app.on_event("startup")`, que FastAPI marca como obsoleto.
    Las funciones que llama se definen más abajo en el módulo: no es un problema
    porque Python resuelve los nombres globales en el momento de la llamada, y
    esto se ejecuta cuando el módulo ya está cargado del todo.
    """
    # ── Arranque ──
    db.init_db()
    try:
        set_lang(db.get_config("lang") or "es")
    except Exception:
        pass
    _start_auto_backup_once()
    migrations.completar_episodios_vistos()   # rápido (solo SQL), idempotente
    _start_cap200_fix_once()
    _start_emision_refresh_once()
    _start_enrich_unknown_eps()
    _start_notif_daemon_once()
    # Auto-detección de episodios: arranca si hay carpeta configurada
    try:
        import watch_folder
        watch_folder.auto_start()
    except Exception:
        pass

    yield          # ← aquí el servidor atiende peticiones

    # ── Apagado ──
    # Limpiar el estado de Discord para no dejar "viendo X" colgado al cerrar.
    try:
        import discord_presence
        discord_presence.limpiar()
    except Exception:
        pass


app = FastAPI(title="Miraru", version=VERSION, lifespan=_lifespan)

# CORS — v2: restringido a localhost + LAN privada + esquemas de PWA/Capacitor.
# Antes era "*" → cualquier web visitada por el usuario podía atacar la API local.
_CORS_ORIGINS_RE = (
    r"^(https?://(127\.0\.0\.1|localhost"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?"
    r"|capacitor://localhost"
    r"|ionic://localhost)$"
)
app.add_middleware(GZipMiddleware, minimum_size=500)  # comprimir respuestas > 500B
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_CORS_ORIGINS_RE,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Routers por dominio ───────────────────────────────────────────────────────
# main.py era un monolito de ~2.900 líneas: se va troceando por dominios para
# que cada archivo sea manejable (y quepa en contexto al iterar con la IA).
from routers import gamificacion as gamificacion_router  # noqa: E402
from routers import media as media_router  # noqa: E402  (tras crear `app`)
from routers import noticias as noticias_router  # noqa: E402
from routers import push as push_router  # noqa: E402
from routers import themes as themes_router  # noqa: E402

app.include_router(media_router.router)
app.include_router(gamificacion_router.router)
app.include_router(noticias_router.router)
app.include_router(themes_router.router)
app.include_router(push_router.router)


# ── Middleware: cuando modo móvil está activo, exigir token en LAN ───────────
# Sustituye a la "auth opcional" del v1 que dejaba todos los endpoints abiertos
# en cuanto se activaba el binding 0.0.0.0.
@app.middleware("http")
async def _lan_auth_guard(request: Request, call_next):
    path = request.url.path
    # Preflight CORS — dejarlo pasar siempre para que el CORSMiddleware
    # responda los Access-Control-* sin que nuestro guard se interponga.
    if request.method == "OPTIONS":
        return await call_next(request)
    # Si no estamos en modo móvil, el binding sigue siendo 127.0.0.1: nadie
    # remoto puede llegar aquí. Pasamos directo.
    if not _mobile_mode_active():
        return await call_next(request)

    ip = (request.client.host if request.client else "?") or "?"
    if _is_loopback(ip):
        return await call_next(request)

    # La documentación interactiva de FastAPI se quedaba fuera del guard porque
    # este solo miraba rutas /api/: en modo móvil, cualquiera del WiFi podía
    # abrir /docs y llevarse el mapa completo de la API (rutas, parámetros y
    # esquemas) sin token. 404 en vez de 401 para no confirmar que existen.
    if path in _RUTAS_SOLO_LOCAL:
        return JSONResponse({"detail": "No encontrado"}, status_code=404)

    # Páginas HTML (no /api) — siempre OK: no llevan datos, los piden luego a
    # /api/, que sí exige token.
    if not path.startswith("/api/"):
        return await call_next(request)

    # Cliente remoto + modo móvil activo: solo whitelist o token válido.
    if path in _PUBLIC_LAN_PATHS:
        return await call_next(request)

    token = request.headers.get("X-Mobile-Token") or request.query_params.get("token", "")
    if not _token_valido(token):
        return JSONResponse(
            {"detail": "Acceso desde la red local requiere token válido."},
            status_code=401,
        )
    return await call_next(request)


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    """Cache largo para assets estáticos, corto para API."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        # SVGs, CSS, JS, imágenes — cache 1 semana (SW invalida)
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
async def health():
    """Endpoint trivial para health-check del launcher (sin estado, sin auth)."""
    return {"ok": True, "version": VERSION, "ts": int(_time.time())}


# ── Estado en memoria del último Sheets sync (para el indicador de UI) ───────
# v2.2: protegido con lock — _sync_bg escribe desde threads del executor y
# el endpoint /api/sync/status lee desde el event loop.
_last_sync = {"ts": 0.0, "ok": True, "msg": ""}
_last_sync_lock = threading.Lock()

def _record_sync(ok: bool, msg: str):
    with _last_sync_lock:
        _last_sync["ts"] = _time.time()
        _last_sync["ok"] = ok
        _last_sync["msg"] = (msg or "")[:120]


@app.get("/api/sync/status")
async def sync_status():
    """Devuelve el estado del último sync de Sheets — para el indicador de UI.
    Si nunca se ha sincronizado en esta sesión, ts == 0."""
    with _last_sync_lock:
        snap = dict(_last_sync)
    return {
        "configured": bool(_get_sheets_config()),
        "last_ts":    int(snap["ts"]),
        "last_ok":    bool(snap["ok"]),
        "last_msg":   snap["msg"],
        "seconds_ago": int(_time.time() - snap["ts"]) if snap["ts"] else None,
    }


# ── Update checker contra GitHub Releases ────────────────────────────────────
_update_cache = {"ts": 0.0, "data": None}
_UPDATE_TTL = 6 * 3600   # cachear 6 horas

@app.get("/api/version/latest")
async def latest_version():
    """Consulta GitHub Releases. Cacheado 6h para no spamear la API pública (60 req/h sin token)."""
    now = _time.time()
    if _update_cache["data"] and (now - _update_cache["ts"]) < _UPDATE_TTL:
        return _update_cache["data"]
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(executor, _check_github_release)
    _update_cache["ts"] = now
    _update_cache["data"] = data
    return data


def _check_github_release() -> dict:
    try:
        resp = requests.get(
            "https://api.github.com/repos/lucasusamentiaga/anime-tracker/releases/latest",
            headers={"User-Agent": f"AnimeTracker/{VERSION}", "Accept": "application/vnd.github+json"},
            timeout=8,
        )
        if resp.status_code != 200:
            return {"current": VERSION, "latest": None, "update_available": False, "error": f"HTTP {resp.status_code}"}
        rel = resp.json()
        tag = (rel.get("tag_name") or "").lstrip("v")
        return {
            "current":          VERSION,
            "latest":           tag or None,
            "update_available": bool(tag and _is_newer(tag, VERSION)),
            "url":              rel.get("html_url") or "",
            "name":             rel.get("name") or tag,
            "published_at":     rel.get("published_at") or "",
        }
    except Exception as e:
        return {"current": VERSION, "latest": None, "update_available": False, "error": str(e)[:120]}


def _is_newer(a: str, b: str) -> bool:
    """Compara dos versiones x.y.z. Devuelve True si a > b."""
    def parts(s):
        try:
            return tuple(int(p) for p in re.split(r"[.\-+]", s) if p.isdigit())
        except Exception:
            return (0,)
    return parts(a) > parts(b)


# ── Backup automático diario ─────────────────────────────────────────────────
def _auto_backup_loop():
    """Thread que dispara backup local cada 24h (silencioso). Retención: 7 días."""
    while True:
        try:
            last = float(db.get_config("last_auto_backup") or 0)
            now = _time.time()
            if now - last >= 24 * 3600:
                _crear_backup_disco(retencion=7)
                db.set_config("last_auto_backup", str(now))
        except Exception as e:
            _sync_log.warning("auto backup: %s", e)
        # Comprobar cada 30 minutos
        _time.sleep(30 * 60)


def _crear_backup_disco(retencion: int = 10) -> Optional[str]:
    """Crea backup en disco y poda los antiguos. Devuelve el nombre o None si falla.

    Usa sqlite3.Connection.backup() en lugar de copiar el .db directamente:
    la BD va en modo WAL y los datos recientes viven en el fichero -wal hasta
    el próximo checkpoint; una copia directa los pierde. La API de backup en
    línea de SQLite garantiza una foto coherente incluyendo el WAL.
    """
    try:
        # Leer APP_DIR en runtime (igual que /api/backup) para que los tests
        # que setean ANIME_APP_DIR antes de llamar a esta función lo vean bien.
        _app_dir = Path(os.environ.get("ANIME_APP_DIR", str(APP_DIR)))
        backup_dir = _app_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"anime_tracker_{ts}.zip"
        db_path = Path(os.environ.get("ANIME_DB_PATH", str(_app_dir / "anime_tracker.db")))
        if not db_path.exists():
            return None
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z, \
             tempfile.TemporaryDirectory() as tmp:
                copia = Path(tmp) / "anime_tracker.db"
                origen = sqlite3.connect(str(db_path))
                destino = sqlite3.connect(str(copia))
                try:
                    with destino:
                        origen.backup(destino)
                finally:
                    destino.close()
                    origen.close()
                z.write(copia, "anime_tracker.db")
        backups = sorted(backup_dir.glob("anime_tracker_*.zip"), key=lambda f: f.stat().st_mtime)
        for old in backups[:-retencion]:
            old.unlink(missing_ok=True)
        return backup_path.name
    except Exception as e:
        _sync_log.warning("crear backup disco: %s", e)
        return None


# v2.2: arrancar el thread de auto-backup una sola vez incluso si main.py
# se carga más de una vez (launcher.py usa importlib, tests reload módulos).
_auto_backup_started = False
def _start_auto_backup_once():
    global _auto_backup_started
    if _auto_backup_started:
        return
    _auto_backup_started = True
    threading.Thread(target=_auto_backup_loop, daemon=True, name="auto-backup").start()


# ── v2.6.3: auto-reparación del bug histórico "cap=200 fantasma" ──────────────
# El código ya NO clampa a 200, pero las entradas guardadas antes de v2.6.2 aún
# tienen capitulos="200". En vez de depender de que el usuario lance el refresco
# a mano, lo reparamos solos al arrancar (en segundo plano, una sola vez).
# La lógica vive en migrations.py (módulo ligero, testeable de forma aislada).
import migrations

_cap200_started = False
def _start_cap200_fix_once():
    global _cap200_started
    if _cap200_started:
        return
    _cap200_started = True
    threading.Thread(target=migrations.migrar_cap200, daemon=True, name="cap200-fix").start()


# v2.6.3: refresco periódico de metadatos de series EN EMISIÓN (los episodios
# crecen / pasan a finalizado). Cada 12h, en segundo plano. No toca el progreso.
def _emision_loop():
    while True:
        try:
            migrations.refrescar_en_emision()
        except Exception as e:
            _sync_log.warning("refresco emisión loop: %s", e)
        _time.sleep(12 * 3600)

_emision_started = False
def _start_emision_refresh_once():
    global _emision_started
    if _emision_started:
        return
    _emision_started = True
    # Espera inicial breve para no competir con el arranque ni con cap200-fix.
    def _run():
        _time.sleep(120)
        _emision_loop()
    threading.Thread(target=_run, daemon=True, name="emision-refresh").start()


# ── Enriquecimiento de animes con episodios desconocidos (arranque) ──────────
# Una pasada: busca en AniList los capítulos de animes con "?" eps.
_enrich_started = False

# Compartido con anilist_sync (evita importar main): ver metadatos.py
_resolver_en_anilist = metadatos.resolver_en_anilist


# Portadas que se sustituyen por la de AniList cuando se encuentra:
# - animeflv: hotlinking 403.
# - anime-planet: su scraper toma la primera tarjeta del listado aunque no
#   coincida → Naruto con la de "Road of Naruto", Dragon Ball Daima con
#   "Tokyo Underground", placeholders default-anime-*.png…
_HOSTS_PORTADA_POCO_FIABLE = metadatos.HOSTS_PORTADA_POCO_FIABLE


def _enrich_needs(a: dict) -> tuple[bool, bool]:
    """(necesita_eps, necesita_imagen) para un anime de la lista."""
    caps = str(a.get("capitulos") or "").strip()
    img = (a.get("imagen") or "").strip().lower()
    return (caps in ("?", "") or caps.endswith("+"),
            not img or any(h in img for h in _HOSTS_PORTADA_POCO_FIABLE))


def _enrich_cambios(a: dict, r, need_eps: bool, need_img: bool) -> dict:
    """Campos de fuente a actualizar a partir de un AnimeData de AniList."""
    cambios: dict = {}
    if need_eps and r.capitulos not in ("?", "", None) \
            and str(r.capitulos) != str(a.get("capitulos") or ""):
        cambios["capitulos"] = str(r.capitulos)
    if need_img and r.imagen and not any(
            h in r.imagen.lower() for h in _HOSTS_PORTADA_POCO_FIABLE):
        cambios["imagen"] = r.imagen
    if not a.get("anilist_id") and r.anilist_id:
        cambios["anilist_id"] = r.anilist_id
    if (a.get("tipo") == "manga" and not a.get("volumenes_totales")
            and getattr(r, "volumenes_totales", 0)):
        cambios["volumenes_totales"] = r.volumenes_totales
    return cambios


def _enriquecer_desde_anilist(animes: list[dict], anilist,
                              sleep=_time.sleep) -> tuple[int, int]:
    """Rellena eps desconocidos/en emisión ("?", "", "N+") y repara portadas
    vacías o de AnimeFLV usando AniList.

    Animes con `anilist_id` → lookup por lotes de 50 IDs (1 petición/lote).
    Sin ID → búsqueda por nombre (1 petición/anime). Rate limit ANILIST_MIN_INTERVAL (30 req/min).
    Devuelve (eps_actualizados, portadas_reparadas)."""
    pend = []
    for a in animes:
        ne, ni = _enrich_needs(a)
        if ne or ni:
            pend.append((a, ne, ni))
    eps_fixed = img_fixed = 0

    def _aplicar(a, r, ne, ni):
        nonlocal eps_fixed, img_fixed
        cambios = _enrich_cambios(a, r, ne, ni)
        if not cambios:
            return
        ok, _ = db.refrescar_metadata_anime(a["nombre"], cambios)
        if ok:
            eps_fixed += "capitulos" in cambios
            img_fixed += "imagen" in cambios

    for tipo, mtype in (("anime", "ANIME"), ("manga", "MANGA")):
        con_id = [p for p in pend if p[0].get("anilist_id")
                  and (p[0].get("tipo") or "anime") == tipo]
        for i in range(0, len(con_id), 50):
            lote = con_id[i:i + 50]
            try:
                res = anilist.buscar_por_ids(
                    [int(p[0]["anilist_id"]) for p in lote], media_type=mtype)
            except Exception:
                res = {}
            for a, ne, ni in lote:
                r = res.get(int(a["anilist_id"]))
                if r:
                    _aplicar(a, r, ne, ni)
            sleep(ANILIST_MIN_INTERVAL)

    for a, ne, ni in (p for p in pend if not p[0].get("anilist_id")):
        try:
            r = _resolver_en_anilist(a["nombre"], a.get("tipo") or "anime", anilist=anilist)
            if r:
                _aplicar(a, r, ne, ni)
        except Exception:
            pass
        # hasta una petición por variante del título + la de idMal
        sleep(ANILIST_MIN_INTERVAL * (len(candidatos_busqueda(a["nombre"])) + 1))
    return eps_fixed, img_fixed


_RESOLVER_IDS_POR_ARRANQUE = 40


def _start_enrich_unknown_eps():
    global _enrich_started
    if _enrich_started:
        return
    _enrich_started = True

    def _run():
        _time.sleep(60)  # espera para no competir con el arranque
        anilist = SCRAPERS.get("anilist")
        if not anilist:
            return
        try:
            eps, imgs = _enriquecer_desde_anilist(db.listar_animes(), anilist)
        except Exception as e:
            _sync_log.warning("enrich daemon: %s", e)
            return
        if eps:
            _sync_log.info("Enriquecidos %d animes con eps desconocidos", eps)
        if imgs:
            _sync_log.info("Reparadas %d portadas rotas/animeflv → AniList", imgs)
        # Resolver poco a poco los anilist_id que faltan (notificaciones y
        # refrescos por lotes los necesitan). Tope por arranque para no
        # acaparar el cupo de AniList (30 req/min) que usa también la UI.
        try:
            r = anilist_sync.resolve_anilist_ids(limite=_RESOLVER_IDS_POR_ARRANQUE)
            if r.get("resolved"):
                _sync_log.info("Resueltos %d anilist_id", r["resolved"])
        except Exception as e:
            _sync_log.warning("resolver IDs: %s", e)

    threading.Thread(target=_run, daemon=True, name="enrich-eps").start()


# ── Daemon de notificaciones de nuevos episodios ─────────────────────────────
# Comprueba periódicamente si los animes con notif_activa (campanita) tienen
# episodio nuevo y avisa por email (si hay) y por Web Push (si algún navegador
# está suscrito: llega aunque la pestaña esté cerrada). El último episodio
# avisado se guarda en config para no repetir avisos tras reiniciar (antes
# vivía solo en memoria).

_notif_daemon_started = False
_CFG_NOTIF_VISTO = "notif_last_seen"


def _notif_cargar_visto() -> dict[str, int]:
    try:
        d = json.loads(db.get_config(_CFG_NOTIF_VISTO) or "{}")
        return {str(k): int(v) for k, v in d.items()}
    except Exception:
        return {}


def _comprobar_nuevos_episodios() -> list[tuple[str, int]]:
    """Una pasada del daemon. Devuelve [(nombre, ultimo_emitido)] avisados."""
    import push_web
    activos = db.listar_con_notif()
    email = db.get_config("email_notif") or ""
    hay_push = push_web.num_suscripciones() > 0
    if not activos or not (email or hay_push):
        return []
    info = _fetch_ultimos_episodios(activos)
    visto = _notif_cargar_visto()
    now_ts = _time.time()
    avisados: list[tuple[str, int]] = []
    for a in activos:
        meta = info.get(a["nombre"])
        if not meta:
            continue
        next_ep = meta.get("next_ep") or 0
        next_at = meta.get("next_at") or 0
        if next_ep and next_at > now_ts:
            ultimo_emitido = max(0, int(next_ep) - 1)
        else:
            ultimo_emitido = int(meta.get("total") or 0)
        vistos = int(a.get("episodios_vistos") or 0)
        prev = visto.get(a["nombre"], vistos)
        if ultimo_emitido > vistos and ultimo_emitido > prev:
            visto[a["nombre"]] = ultimo_emitido
            avisados.append((a["nombre"], ultimo_emitido))
            if email:
                _notif_enviar_nuevo_disponible(a, vistos, ultimo_emitido, email)
            if hay_push:
                pendientes = ultimo_emitido - vistos
                try:
                    push_web.enviar(
                        f"📺 {a['nombre']}",
                        f"Episodio {vistos + 1} disponible" if pendientes == 1
                        else f"{pendientes} episodios sin ver (hasta el {ultimo_emitido})",
                        url="/app", tag=f"anime-{a['nombre']}-{ultimo_emitido}",
                        icono=a.get("imagen") or None)
                except Exception as e:
                    _sync_log.warning("push: %s", e)
    if avisados:
        db.set_config(_CFG_NOTIF_VISTO, json.dumps(visto))
    return avisados


def _notif_daemon_loop():
    """Hilo daemon: comprueba nuevos episodios cada 2h (4h si solo hay email)."""
    import push_web
    while True:
        try:
            _comprobar_nuevos_episodios()
        except Exception as e:
            _sync_log.warning("notif daemon: %s", e)
        _time.sleep((2 if push_web.num_suscripciones() else 4) * 3600)


def _notif_enviar_nuevo_disponible(anime: dict, vistos: int, disponible: int, email: str):
    """Envía email avisando de episodio(s) nuevo(s) disponible(s)."""
    nombre_raw = anime.get("nombre", "?")
    # Escapar: nombre/imagen vienen de scrapers externos y van dentro de HTML
    nombre = _esc(nombre_raw)
    imagen = _esc(anime.get("imagen", "") or "", quote=True)
    pendientes = disponible - vistos
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;background:#0a0812;
                color:#edecf4;border-radius:16px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#059669,#34d399);padding:20px 24px">
        <h2 style="margin:0;color:#fff;font-size:20px">{'Nuevo episodio' if pendientes == 1 else f'{pendientes} episodios nuevos'}</h2>
      </div>
      <div style="padding:24px;display:flex;gap:16px">
        {'<img src="'+imagen+'" style="width:80px;height:110px;object-fit:cover;border-radius:8px;flex-shrink:0" />' if imagen else ''}
        <div>
          <h3 style="color:#6ee7b7;margin:0 0 8px">{nombre}</h3>
          <p style="color:#a49dc0;font-size:14px;margin:0 0 8px">
            {'Hay un episodio nuevo esperándote' if pendientes == 1
             else f'Tienes {pendientes} episodios sin ver'}
          </p>
          <p style="color:#a49dc0;font-size:13px;margin:0">
            Tu progreso: ep {vistos} · Disponible hasta ep {disponible}
          </p>
        </div>
      </div>
      <div style="padding:0 24px 20px">
        <p style="color:#4a4a60;font-size:11px;margin:0">Miraru — notificación automática</p>
      </div>
    </div>"""
    subj = f"🆕 {nombre_raw} — {'ep ' + str(disponible) if pendientes == 1 else str(pendientes) + ' eps nuevos'}"
    _sync_bg(_enviar_email, email, subj, html)


def _start_notif_daemon_once():
    global _notif_daemon_started
    if _notif_daemon_started:
        return
    _notif_daemon_started = True
    def _run():
        _time.sleep(300)  # 5 min tras arranque
        _notif_daemon_loop()
    threading.Thread(target=_run, daemon=True, name="notif-daemon").start()


# (El arranque de estos hilos lo orquesta _lifespan, definido arriba.)

# ── Caché de búsquedas — LRU con cap duro (v2) ────────────────────────────────
# Antes: dict sin tope real — solo limpiaba entradas ya expiradas.
_CACHE_TTL = 300
_CACHE_MAX = 200
# (guardado_en, valor, ttl). El TTL va por entrada: 5 minutos vale para una
# búsqueda, pero las portadas de la lista fija de animes para principiantes no
# cambian en meses y recalcularlas cuesta ~3s de peticiones a la red.
_search_cache: OrderedDict[str, tuple[float, object, float]] = OrderedDict()
_cache_lock = threading.Lock()

def _cache_get(key: str):
    with _cache_lock:
        e = _search_cache.get(key)
        if not e:
            return None
        if _time.time() - e[0] >= e[2]:
            _search_cache.pop(key, None)
            return None
        _search_cache.move_to_end(key)
        return e[1]

def _cache_set(key: str, val, ttl: float = _CACHE_TTL):
    with _cache_lock:
        _search_cache[key] = (_time.time(), val, ttl)
        _search_cache.move_to_end(key)
        while len(_search_cache) > _CACHE_MAX:
            _search_cache.popitem(last=False)

# El pool vive en core.py y se comparte con los routers. Antes había DOS pools
# de 6 hilos (uno aquí y otro en core) que se ignoraban: uno podía estar saturado
# mientras el otro estaba ocioso, que es exactamente lo que core.py existe para
# evitar. Se reexporta para no tocar los ~40 usos de `executor` de este módulo.
from core import executor  # noqa: E402


class PinRequest(BaseModel):
    pin: str

class MobileAuthResponse(BaseModel):
    token: str
    expira_en: int  # unix timestamp

# Token de sesión en memoria — se regenera al reiniciar la app
_mobile_tokens: dict[str, float] = {}   # token -> expiry
_TOKEN_TTL = 86400 * 30  # 30 días

# Rate-limit por IP para /api/mobile/auth — evita fuerza bruta del PIN (v2)
_AUTH_WINDOW = 60            # 1 minuto
_AUTH_MAX_TRIES = 5          # máximo 5 intentos por ventana
_AUTH_BAN_AFTER = 20         # tras 20 fallos seguidos: bloqueo más largo
_AUTH_BAN_SECONDS = 600      # 10 minutos
_auth_attempts: dict[str, list[float]] = {}
_auth_bans: dict[str, float] = {}
_auth_lock = threading.Lock()
_auth_last_gc = 0.0          # v2.2: timestamp del último GC del rate limiter
_AUTH_GC_INTERVAL = 600      # purgar IPs sin actividad cada 10 minutos

def _auth_gc(now: float):
    """Purga IPs sin actividad reciente. v2.2: evita memory leak bajo DDoS."""
    global _auth_last_gc
    if now - _auth_last_gc < _AUTH_GC_INTERVAL:
        return
    _auth_last_gc = now
    stale_ips = [
        ip for ip, tries in _auth_attempts.items()
        if not tries or now - max(tries) > _AUTH_WINDOW * 10
    ]
    for ip in stale_ips:
        _auth_attempts.pop(ip, None)
    expired_bans = [ip for ip, until in _auth_bans.items() if now > until]
    for ip in expired_bans:
        _auth_bans.pop(ip, None)

def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "?") or "?"

def _auth_rate_check(ip: str) -> tuple[bool, str]:
    """Devuelve (ok, motivo). Llamar ANTES de validar PIN."""
    now = _time.time()
    with _auth_lock:
        _auth_gc(now)
        ban_until = _auth_bans.get(ip, 0)
        if now < ban_until:
            return False, f"Demasiados intentos. Espera {int(ban_until - now)}s."
        tries = [t for t in _auth_attempts.get(ip, []) if now - t < _AUTH_WINDOW]
        if len(tries) >= _AUTH_MAX_TRIES:
            return False, f"Demasiados intentos. Espera {int(_AUTH_WINDOW - (now - tries[0]))}s."
        return True, "ok"

def _auth_record_fail(ip: str):
    now = _time.time()
    with _auth_lock:
        tries = [t for t in _auth_attempts.get(ip, []) if now - t < _AUTH_WINDOW]
        tries.append(now)
        _auth_attempts[ip] = tries
        # Si acumula muchos fallos en la ventana → ban prolongado
        if len(tries) >= _AUTH_BAN_AFTER:
            _auth_bans[ip] = now + _AUTH_BAN_SECONDS

def _auth_record_ok(ip: str):
    with _auth_lock:
        _auth_attempts.pop(ip, None)
        _auth_bans.pop(ip, None)

# v2.2: lock para proteger _mobile_tokens contra mutación concurrente.
# El middleware corre en el event loop, pero _sync_bg y los endpoints pueden
# modificar el dict desde threads del executor — iterar sin lock daba
# "RuntimeError: dictionary changed size during iteration".
_tokens_lock = threading.Lock()

def _gen_token() -> str:
    return secrets.token_urlsafe(32)

def _token_valido(token: str) -> bool:
    """Verifica el token con comparación en tiempo constante (compare_digest)."""
    if not token:
        return False
    now = _time.time()
    with _tokens_lock:
        # Limpieza perezosa de tokens caducados
        expired = [t for t, exp in _mobile_tokens.items() if now > exp]
        for t in expired:
            _mobile_tokens.pop(t, None)
        # Snapshot para iterar sin riesgo (otra thread podría modificar)
        snapshot = list(_mobile_tokens.items())
    # Bucle explícito a propósito: es código de autenticación y se prefiere que
    # la comparación en tiempo constante quede a la vista antes que un any(...).
    for stored, exp in snapshot:  # noqa: SIM110
        if hmac.compare_digest(stored, token) and now <= exp:
            return True
    return False

# ── Salt persistente para hashing del PIN ────────────────────────────────────
def _pin_salt() -> bytes:
    """Devuelve un salt aleatorio único por instalación. Se genera al primer uso."""
    s = db.get_config("pin_salt")
    if not s:
        s = secrets.token_hex(16)
        db.set_config("pin_salt", s)
    return s.encode()

def _hash_pin(pin: str) -> str:
    """HMAC-SHA256(salt, pin). Reemplaza al SHA256 sin salt de v1."""
    return hmac.new(_pin_salt(), pin.encode(), hashlib.sha256).hexdigest()

def _check_pin(pin: str, stored: str) -> bool:
    """Comparación en tiempo constante. Compatible con BD v1 (sha256 sin salt)."""
    if not stored:
        return False
    # Nuevo formato (HMAC con salt)
    if hmac.compare_digest(_hash_pin(pin), stored):
        return True
    # Fallback v1 — si coincide, migrar al nuevo formato
    legacy = hashlib.sha256(pin.encode()).hexdigest()
    if hmac.compare_digest(legacy, stored):
        db.set_config("mobile_pin", _hash_pin(pin))
        return True
    return False

# ── Autorización ─────────────────────────────────────────────────────────────
def _is_loopback(ip: str) -> bool:
    return ip in ("127.0.0.1", "::1", "localhost")

def _mobile_mode_active() -> bool:
    return db.get_config("mobile_enabled") == "1"

# Endpoints accesibles desde la LAN sin token cuando el modo móvil está activo.
# Todo lo demás bajo /api/ exige token de móvil para clientes no-loopback.
_PUBLIC_LAN_PATHS = {
    "/api/version",
    "/api/mobile/ping",
    "/api/mobile/auth",
    "/api/health",
}

# Útiles para desarrollar en este PC, pero no hay razón para publicarlas a la
# red local: describen la API entera. Solo accesibles desde loopback.
_RUTAS_SOLO_LOCAL = {
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}

def _require_auth(request: Request):
    """Dependencia FastAPI: verifica token de móvil en header o query."""
    token = request.headers.get("X-Mobile-Token") or request.query_params.get("token", "")
    if not _token_valido(token):
        raise HTTPException(401, "Token inválido o expirado. Reconecta la app móvil.")

_sync_log = _logging.getLogger("anime_tracker")

def _sync_bg(fn, *args):
    """Ejecuta sincronización en background sin bloquear la API.

    v2.1: registra el resultado en _last_sync para que la UI pueda mostrar un
    indicador "✓ Sincronizado / ⚠ Error" en lugar de fallar en silencio.
    """
    def _run():
        try:
            result = fn(*args)
            # Las funciones de sheets_sync devuelven (ok, msg). El email no.
            if isinstance(result, tuple) and len(result) == 2:
                ok, msg = result
                _record_sync(bool(ok), str(msg))
            else:
                _record_sync(True, "ok")
        except Exception as e:
            _sync_log.warning("Sheets sync (%s): %s", fn.__name__, e)
            _record_sync(False, str(e)[:120])
    threading.Thread(target=_run, daemon=True).start()

def _get_sheets_config() -> tuple[str, str] | None:
    """Devuelve (spreadsheet_id, credentials_path) si están configurados."""
    sid = db.get_config("spreadsheet_id")
    if not sid:
        return None
    if not CREDENTIALS.exists():
        return None
    return sid, str(CREDENTIALS)

# ── Modelos ───────────────────────────────────────────────────────────────────

class BuscarRequest(BaseModel):
    nombre: str
    fuente: str = "anilist"
    tipo: str = "anime"          # "anime" o "manga"

# Estados que entienden las estadísticas, los filtros y la gamificación.
# Cualquier otro valor se guardaba igual y luego no casaba con ninguna consulta:
# el anime desaparecía de los recuentos sin que nada avisara.
ESTADOS_VALIDOS = ("pendiente", "viendo", "completado", "abandonado")


class ActualizarRequest(BaseModel):
    """Los límites viven aquí, no en el frontend.

    El modelo aceptaba cualquier cosa: `puntuacion: 999` y
    `episodios_vistos: -50` se guardaban tal cual y corrompían en silencio la
    nota media, las horas vistas y el heatmap (que pasaban a dar negativo). La
    interfaz nunca manda eso, pero el cliente móvil, un `fetch` a mano o un
    error de tecleo sí — y el daño quedaba en la base de datos.
    """
    estado_usuario:      Optional[str]   = None
    puntuacion:          Optional[float] = Field(default=None, ge=0, le=10)
    fecha_inicio:        Optional[str]   = None
    fecha_fin:           Optional[str]   = None
    episodios_vistos:    Optional[int]   = Field(default=None, ge=0)
    temporada:           Optional[str]   = None
    lista_personalizada: Optional[str]   = None
    favorito:            Optional[int]   = Field(default=None, ge=0, le=1)
    notif_activa:        Optional[int]   = Field(default=None, ge=0, le=1)
    notas:               Optional[str]   = Field(default=None, max_length=5000)
    volumenes_leidos:    Optional[int]   = Field(default=None, ge=0)

    @field_validator("estado_usuario")
    @classmethod
    def _estado_conocido(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        # El inglés se aceptaba en otras partes del código; se normaliza aquí
        # para no acabar con "watching" y "viendo" conviviendo en la misma BD.
        equivalencias = {"watching": "viendo", "completed": "completado",
                         "pending": "pendiente", "dropped": "abandonado"}
        v = equivalencias.get(v, v)
        if v not in ESTADOS_VALIDOS:
            raise ValueError(
                f"Estado no válido: {v!r}. Debe ser uno de {', '.join(ESTADOS_VALIDOS)}."
            )
        return v

class ConfigRequest(BaseModel):
    spreadsheet_id: str

class SyncRequest(BaseModel):
    spreadsheet_id: Optional[str] = None

class LangRequest(BaseModel):
    lang: str

# Los modelos de películas/series viven ahora en routers/media.py

ANILIST_URL = "https://graphql.anilist.co"

def _anilist(query: str, variables: dict, timeout: int = 15):
    """POST a AniList GraphQL con headers consistentes.

    v2.3: fuerza `Accept-Encoding: identity` para evitar el error
    'Error -3 while decompressing data: incorrect header check'. AniList está
    detrás de Cloudflare y a veces declara un Content-Encoding (gzip/br) que no
    casa con el cuerpo recibido, y requests revienta al descomprimir. Al pedir
    identity, el servidor no comprime y no hay nada que descomprimir. Los
    payloads son de pocos KB, el coste es despreciable.

    Devuelve el objeto `data` del JSON, o {} si falla / status != 200.
    """
    data, _ = _anilist_con_error(query, variables, timeout)
    return data


def _anilist_con_error(query: str, variables: dict, timeout: int = 15) -> tuple:
    """Como `_anilist`, pero además devuelve el motivo del fallo.

    Nació de un incidente real: AniList empezó a responder 403 ("The AniList API
    has been temporarily disabled due to severe stability issues") y, como el
    error se tragaba devolviendo {}, Novedades y Recomendaciones se quedaban en
    blanco diciéndole al usuario que comprobara *su* conexión. Quien llama
    necesita distinguir "no hay resultados" de "la fuente está caída" para poder
    tirar de respaldo y dar un mensaje honesto.

    Devuelve (data, error): error es "" si todo fue bien.
    """
    try:
        resp = requests.post(
            ANILIST_URL,
            json={"query": query, "variables": variables},
            headers={
                "User-Agent": f"AnimeTracker/{VERSION}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            detalle = ""
            try:                       # AniList explica el motivo en el cuerpo
                errores = resp.json().get("errors") or []
                if errores:
                    detalle = f": {errores[0].get('message', '')}"
            except Exception:
                pass
            error = f"AniList HTTP {resp.status_code}{detalle}"
            _sync_log.warning("%s", error)
            return {}, error
        cuerpo = resp.json()
        errores = cuerpo.get("errors") or []
        if errores:
            error = f"AniList: {errores[0].get('message', 'error desconocido')}"
            _sync_log.warning("%s", error)
            return {}, error
        return cuerpo.get("data") or {}, ""
    except Exception as e:
        _sync_log.warning("AniList request: %s", e)
        return {}, f"No se pudo contactar con AniList: {e}"


def _find_anime_image(nombre: str) -> str:
    """Busca imagen de un anime en AniList como fallback cuando el scraper no devuelve una."""
    query = """query($search: String) {
      Media(search: $search, type: ANIME) {
        coverImage { large medium }
        bannerImage
      }
    }"""
    media = _anilist(query, {"search": nombre}, timeout=8).get("Media")
    if media:
        cover = media.get("coverImage") or {}
        return cover.get("large") or cover.get("medium") or media.get("bannerImage") or ""
    return ""

@app.get("/api/version")
async def get_version():
    return {"version": VERSION, "name": "Miraru"}

# ── v6: Películas y Series (TMDB) ─────────────────────────────────────────────
# Los endpoints viven ahora en routers/media.py (ver include_router más abajo).

# ── Páginas ───────────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Icono de la pestaña.

    Los navegadores piden /favicon.ico a la raíz por su cuenta cuando la página
    no declara uno. Aquí no existía esa ruta (404), así que solo se veía el logo
    en las dos páginas que traían <link rel="icon">; en Estadísticas, Novedades y
    demás salía el icono genérico de documento. Ahora todas lo declaran *y*
    existe esta ruta, para que una página futura que se despiste siga saliendo
    bien.
    """
    icono = STATIC_DIR / "icon.ico"
    if not icono.exists():
        raise HTTPException(404, "No hay icono")
    return FileResponse(str(icono), media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Service Worker servido desde la raíz con alcance "/".

    Antes se registraba en /static/sw.js y, sin la cabecera
    Service-Worker-Allowed, su alcance quedaba en /static/: nunca controlaba
    /app ni ninguna página (ni caché offline, ni push, y getRegistration()
    desde /app devolvía undefined). no-cache: el navegador comprueba en cada
    carga si hay versión nueva."""
    sw = STATIC_DIR / "sw.js"
    if not sw.exists():
        raise HTTPException(404, "No hay service worker")
    return FileResponse(str(sw), media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/",
                                 "Cache-Control": "no-cache"})


@app.post("/api/apagar")
async def apagar(request: Request):
    """Cierra Miraru del todo.

    Existe porque la app ya no se lanza con una consola visible: antes se cerraba
    cerrando la ventana negra, y sin ella el servidor se quedaría corriendo de
    fondo para siempre sin forma evidente de pararlo.

    Solo desde este ordenador: en modo red el móvil también llega al servidor, y
    nadie quiere que un tirón de pantalla en el móvil apague el PC.
    """
    ip = _client_ip(request)
    if ip not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "Miraru solo puede apagarse desde este ordenador.")

    def _adios():
        # Margen para que la respuesta HTTP salga antes de morir; si no, el
        # navegador muestra un error de red justo al pulsar "Salir".
        _time.sleep(0.6)
        try:
            import discord_presence
            discord_presence.limpiar()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_adios, daemon=True).start()
    return {"ok": True, "mensaje": "Miraru se está cerrando."}


@app.get("/", response_class=HTMLResponse)
async def menu():
    """Menú principal."""
    return FileResponse(str(TEMPLATES_DIR / "menu.html"))

@app.get("/app", response_class=HTMLResponse)
async def index():
    """App principal de tracking."""
    return FileResponse(str(TEMPLATES_DIR / "index.html"))

@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return FileResponse(str(TEMPLATES_DIR / "setup.html"))

@app.get("/stats", response_class=HTMLResponse)
async def stats_page():
    return FileResponse(str(TEMPLATES_DIR / "stats.html"))

@app.get("/import", response_class=HTMLResponse)
async def import_page():
    return FileResponse(str(TEMPLATES_DIR / "import.html"))

@app.get("/mobile", response_class=HTMLResponse)
async def mobile_page():
    return FileResponse(str(TEMPLATES_DIR / "mobile.html"))

@app.get("/peliculas", response_class=HTMLResponse)
async def peliculas_page():
    """v6: sección de películas y series (no-anime, vía TMDB)."""
    return FileResponse(str(TEMPLATES_DIR / "peliculas.html"))

# ── Idioma ────────────────────────────────────────────────────────────────────

@app.get("/api/lang")
async def get_language():
    return {"lang": get_lang(), "translations": TRANSLATIONS.get(get_lang(), {})}

@app.post("/api/lang")
async def set_language(req: LangRequest):
    if req.lang not in TRANSLATIONS:
        raise HTTPException(400, f"Idioma no soportado: {req.lang}")
    set_lang(req.lang)
    db.set_config("lang", req.lang)
    return {"ok": True, "lang": req.lang}

@app.get("/api/langs")
async def list_languages():
    return {"langs": list(TRANSLATIONS.keys())}

# ── Setup ─────────────────────────────────────────────────────────────────────

@app.post("/api/setup/upload-credentials")
async def upload_credentials(file: UploadFile = File(...)):
    if not (file.filename or "").endswith(".json"):
        raise HTTPException(400, "El archivo debe ser un .json")
    content = await file.read()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON inválido")
    if parsed.get("type") != "service_account":
        raise HTTPException(400, "El archivo no es de una cuenta de servicio de Google")
    CREDENTIALS.write_bytes(content)
    email = parsed.get("client_email", "")
    db.set_config("service_account_email", email)
    return {"ok": True, "email": email}

@app.post("/api/setup/verify")
async def verify_setup(req: ConfigRequest):
    ok, msg = sheets_sync.verificar_credenciales(req.spreadsheet_id, str(CREDENTIALS))
    if not ok:
        raise HTTPException(400, msg)
    db.set_config("spreadsheet_id", req.spreadsheet_id)
    return {"ok": True}

@app.get("/api/setup/status")
async def setup_status():
    return {
        "configured":            db.is_configured(),
        "spreadsheet_id":        db.get_config("spreadsheet_id") or "",
        "service_account_email": db.get_config("service_account_email") or "",
        "lang":                  get_lang(),
    }

# ── Animes ────────────────────────────────────────────────────────────────────

@app.get("/api/fuentes")
async def listar_fuentes():
    return {"fuentes": list(SCRAPERS.keys())}

@app.get("/api/animes/random")
async def anime_aleatorio(estado: str = "pendiente"):
    """Selecciona un anime inteligente basado en géneros favoritos del usuario."""
    todos = db.listar_animes()
    if not todos:
        return {"anime": None, "mensaje": "Lista vacía"}

    # Calcular géneros favoritos a partir de animes completados/bien valorados
    genre_weight: Counter = Counter()
    for a in todos:
        if a.get("estado_usuario") in ("completado","completed","viendo","watching"):
            score_bonus = 2 if (a.get("puntuacion") or 0) >= 8 else 1
            for g in (a.get("genero") or "").split(","):
                g = g.strip()
                if g:
                    genre_weight[g] += score_bonus

    # Candidatos: pendientes (o filtro de estado pedido)
    candidatos = [a for a in todos if a.get("estado_usuario") == (estado or "pendiente")]
    if not candidatos:
        candidatos = todos  # fallback a toda la lista

    if not genre_weight:
        # Sin historial: aleatorio puro
        return {"anime": random.choice(candidatos), "metodo": "aleatorio"}

    # Puntuar candidatos por coincidencia de géneros con los favoritos
    def puntuacion_candidato(anime):
        score = 0
        for g in (anime.get("genero") or "").split(","):
            g = g.strip()
            if g in genre_weight:
                score += genre_weight[g]
        return score + random.uniform(0, 0.5)  # pequeño factor aleatorio para variedad

    # Tomar el top-10 ponderado y elegir aleatoriamente entre ellos
    candidatos_ordenados = sorted(candidatos, key=puntuacion_candidato, reverse=True)
    pool = candidatos_ordenados[:min(10, len(candidatos_ordenados))]
    elegido = random.choice(pool)

    top_generos = [g for g, _ in genre_weight.most_common(3)]
    return {"anime": elegido, "metodo": "inteligente", "basado_en": top_generos}


# ── Motor de decisión "¿Qué veo esta noche?" ────────────────────────────────

# Mapeo de ánimo → géneros prioritarios (se expanden al puntuar candidatos)
_MOOD_GENRES: dict[str, list[str]] = {
    "accion":    ["Action", "Adventure", "Thriller", "Mecha", "Sports"],
    "comedia":   ["Comedy", "Slice of Life", "Parody"],
    "romance":   ["Romance", "Drama", "Shoujo"],
    "terror":    ["Horror", "Thriller", "Psychological", "Mystery"],
    "drama":     ["Drama", "Psychological", "Tragedy"],
    "chill":     ["Slice of Life", "Iyashikei", "Music", "Comedy"],
    "epico":     ["Action", "Fantasy", "Sci-Fi", "Adventure", "Supernatural"],
    "llorar":    ["Drama", "Romance", "Tragedy", "Psychological"],
    "misterio":  ["Mystery", "Thriller", "Psychological", "Suspense"],
    "fantasia":  ["Fantasy", "Supernatural", "Magic", "Isekai"],
}

@app.get("/api/que-veo")
async def que_veo_esta_noche(
    animo: str = "",
    minutos: int = 0,
):
    """Motor de decisión: dado un estado de ánimo y tiempo disponible,
    devuelve UNA recomendación concreta de la biblioteca del usuario.

    Parámetros:
    - animo: accion|comedia|romance|terror|drama|chill|epico|llorar|misterio|fantasia
    - minutos: tiempo disponible (0 = sin filtro). 30 → corto, 60 → medio, 180+ → maratón
    """
    todos = db.listar_animes()
    if not todos:
        return {"anime": None, "mensaje": "Tu biblioteca está vacía"}

    # Candidatos: pendientes o viendo (no completados ni abandonados)
    candidatos = [
        a for a in todos
        if a.get("estado_usuario") in ("pendiente", "viendo", "watching", "pending")
    ]
    if not candidatos:
        return {"anime": None, "mensaje": "No tienes animes pendientes o en progreso"}

    # Filtro por duración si hay restricción de tiempo
    EP_MIN = 24
    if minutos > 0:
        filtrados = []
        for a in candidatos:
            caps_raw = str(a.get("capitulos") or "").strip()
            es_peli = "pel" in caps_raw.lower()
            nums = re.findall(r"\d+", caps_raw)
            caps_total = int(nums[0]) if nums else 0
            vistos = int(a.get("episodios_vistos") or 0)
            restantes = max(1, (caps_total - vistos) if caps_total else 12)
            # ¿Cuántos eps caben en el tiempo disponible?
            eps_posibles = max(1, minutos // EP_MIN)
            if es_peli:
                # Película: cabe si tenemos al menos 90 min
                if minutos >= 80:
                    filtrados.append(a)
            elif restantes <= eps_posibles * 2 or eps_posibles >= 1:
                # Si le quedan pocos eps y caben, o si al menos cabe 1 ep
                filtrados.append(a)
        if filtrados:
            candidatos = filtrados

    # Puntuar por ánimo
    mood_genres = set()
    animo_key = animo.strip().lower().replace("á", "a").replace("é", "e").replace("í", "i")
    if animo_key in _MOOD_GENRES:
        mood_genres = {g.lower() for g in _MOOD_GENRES[animo_key]}

    # Géneros favoritos del usuario (historial)
    genre_weight: Counter = Counter()
    for a in todos:
        if a.get("estado_usuario") in ("completado", "completed", "viendo", "watching"):
            bonus = 2 if (a.get("puntuacion") or 0) >= 8 else 1
            for g in (a.get("genero") or "").split(","):
                g = g.strip()
                if g:
                    genre_weight[g] += bonus

    def _score(anime):
        s = 0.0
        gs = [g.strip() for g in (anime.get("genero") or "").split(",") if g.strip()]
        # Bonus por coincidencia con el ánimo pedido
        for g in gs:
            if g.lower() in mood_genres:
                s += 5
            if g in genre_weight:
                s += genre_weight[g] * 0.3
        # Bonus por puntuación del anime (popularidad)
        punt = float(anime.get("puntuacion") or 0)
        if punt:
            s += punt * 0.5
        # Bonus ligero por estar "viendo" (ya empezaste, es más fácil retomarlo)
        if anime.get("estado_usuario") in ("viendo", "watching"):
            s += 3
        # Variedad: ruido aleatorio para no recomendar siempre lo mismo
        s += random.uniform(0, 2)
        return s

    candidatos.sort(key=_score, reverse=True)
    elegido = candidatos[0]

    # Info extra sobre la recomendación
    caps_raw = str(elegido.get("capitulos") or "").strip()
    nums = re.findall(r"\d+", caps_raw)
    caps_total = int(nums[0]) if nums else 0
    vistos = int(elegido.get("episodios_vistos") or 0)
    restantes = max(0, caps_total - vistos) if caps_total else None
    tiempo_est = (restantes * EP_MIN) if restantes else None

    return {
        "anime": elegido,
        "animo": animo_key if animo_key in _MOOD_GENRES else None,
        "animos_disponibles": list(_MOOD_GENRES.keys()),
        "episodios_restantes": restantes,
        "tiempo_estimado_min": tiempo_est,
        "razon": _generar_razon(elegido, animo_key, mood_genres, genre_weight),
    }


def _generar_razon(anime: dict, animo: str, mood_genres: set, genre_weight: Counter) -> str:
    """Genera una frase corta explicando por qué se recomienda este anime."""
    razones = []
    gs = [g.strip() for g in (anime.get("genero") or "").split(",") if g.strip()]
    matched = [g for g in gs if g.lower() in mood_genres]
    if matched and animo:
        razones.append(f"encaja con tu mood «{animo}» ({', '.join(matched[:2])})")
    if anime.get("estado_usuario") in ("viendo", "watching"):
        vistos = int(anime.get("episodios_vistos") or 0)
        razones.append(f"ya llevas {vistos} eps")
    punt = float(anime.get("puntuacion") or 0)
    if punt >= 8:
        razones.append(f"puntuación alta ({punt})")
    fav_match = [g for g in gs if genre_weight.get(g, 0) >= 3]
    if fav_match and not matched:
        razones.append(f"te gusta {fav_match[0]}")
    return " · ".join(razones) if razones else "variedad: algo diferente"


@app.get("/api/animes/search")
async def buscar_local(q: str = "", limit: int = 20):
    """Búsqueda local rápida por nombre — para autocompletado."""
    if not q.strip():
        return {"animes": []}
    resultados = db.buscar_animes(q.strip(), limit=min(limit, 50))
    return {"animes": resultados}

@app.get("/api/animes")
async def listar_animes():
    return {"animes": db.listar_animes()}


@app.get("/api/animes/slim")
async def listar_animes_slim():
    """Versión ligera — solo campos del grid, sin sinopsis/notas."""
    return {"animes": db.listar_animes_slim()}


# Cache de franquicias — se invalida automáticamente con listar_animes_slim()
_franquicias_cache: list | None = None
_franquicias_version: int = 0


@app.get("/api/franquicias")
async def listar_franquicias():
    global _franquicias_cache, _franquicias_version
    import franquicias as fq_mod
    animes = db.listar_animes_slim()
    v = id(animes)  # id cambia cuando se invalida la cache de slim
    if _franquicias_cache is None or v != _franquicias_version:
        _franquicias_cache = fq_mod.agrupar_franquicias(animes)
        _franquicias_version = v
    return {"franquicias": _franquicias_cache}


# ── Detección de URLs de fuentes conocidas ────────────────────────────────────
# Permite pegar la URL del anime en el buscador y resolver directamente la
# fuente correcta, sin búsqueda fuzzy. Devolvemos (fuente, query) o None.
_URL_PATTERNS = [
    # AniList: https://anilist.co/anime/1234/Slug — usamos el ID para query exacta
    (re.compile(r"https?://(?:www\.)?anilist\.co/anime/(\d+)"),       "anilist_id",   "anilist"),
    # MAL: https://myanimelist.net/anime/1234/Slug — buscamos por ID via Jikan
    (re.compile(r"https?://(?:www\.)?myanimelist\.net/anime/(\d+)"),  "mal_id",       "jikan"),
    # Jikan directo
    (re.compile(r"https?://(?:www\.)?api\.jikan\.moe/v4/anime/(\d+)"),"mal_id",       "jikan"),
    # Kitsu
    (re.compile(r"https?://(?:www\.)?kitsu\.io/anime/([\w-]+)"),      "slug",         "kitsu"),
    # AnimePlanet
    (re.compile(r"https?://(?:www\.)?anime-planet\.com/anime/([\w-]+)"), "slug",      "animeplanet"),
    # AnimeFLV
    (re.compile(r"https?://(?:www\d*\.)?animeflv\.net/anime/([\w-]+)"),  "slug",      "animeflv"),
    # AnimeAV1
    (re.compile(r"https?://(?:www\.)?animeav1\.com/[^/]*/([\w-]+)"),     "slug",      "animeav1"),
    # Crunchyroll: el slug a veces va precedido de /series/<id>/<slug>
    (re.compile(r"https?://(?:www\.)?crunchyroll\.com/[\w-]+(?:/series)?/[\w-]+/?([\w-]*)"),
                                                                        "slug",      "crunchyroll"),
]

def _detect_url(s: str) -> Optional[tuple[str, str, str]]:
    """Si `s` es una URL conocida, devuelve (fuente, tipo, valor). Si no, None."""
    if not s or "://" not in s:
        return None
    for pat, tipo, fuente in _URL_PATTERNS:
        m = pat.search(s.strip())
        if m:
            return fuente, tipo, m.group(1)
    return None


def _buscar_por_anilist_id(anime_id: int) -> Optional[AnimeData]:
    """Lookup directo en AniList por ID (más exacto que search)."""
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        title { romaji english } episodes format coverImage { large }
        genres description(asHtml:false) status
      }
    }"""
    m = _anilist(query, {"id": anime_id}, timeout=10).get("Media")
    if not m:
        return None
    t = m.get("title") or {}
    eps = m.get("episodes") or 0
    fmt = (m.get("format") or "").upper()
    if fmt == "MOVIE":
        caps: int | str = "película"
    elif eps > 0:
        caps = eps
    else:
        caps = "?"
    st_map = {"FINISHED":"Finalizado","RELEASING":"En emisión","NOT_YET_RELEASED":"Sin estrenar",
              "CANCELLED":"Cancelado","HIATUS":"En pausa"}
    return AnimeData(
        nombre=t.get("english") or t.get("romaji") or f"#{anime_id}",
        capitulos=caps,
        imagen=(m.get("coverImage") or {}).get("large", ""),
        genero=m.get("genres") or [],
        sinopsis=(m.get("description") or "")[:500],
        fuente="anilist",
        estado_anime=st_map.get(m.get("status",""), "Desconocido"),
    )


def _buscar_por_mal_id(mal_id: int) -> Optional[AnimeData]:
    """Lookup directo en Jikan por ID."""
    try:
        resp = requests.get(
            f"https://api.jikan.moe/v4/anime/{mal_id}",
            headers={"User-Agent": f"AnimeTracker/{VERSION}", "Accept-Encoding": "identity"},
            timeout=10,
        )
        if not resp.ok:
            return None
        a = resp.json().get("data") or {}
        if not a:
            return None
        eps = a.get("episodes") or 0
        atype = (a.get("type") or "").upper()
        if atype == "MOVIE":
            caps: int | str = "película"
        elif eps > 0:
            caps = int(eps)
        else:
            caps = "?"
        st_map = {"Finished Airing":"Finalizado","Currently Airing":"En emisión","Not yet aired":"Próximamente"}
        return AnimeData(
            nombre=a.get("title_english") or a.get("title") or f"#{mal_id}",
            capitulos=caps,
            imagen=(a.get("images") or {}).get("jpg", {}).get("large_image_url", ""),
            genero=[g["name"] for g in (a.get("genres") or []) if g.get("name")],
            sinopsis=(a.get("synopsis") or "")[:500],
            fuente="jikan",
            estado_anime=st_map.get(a.get("status",""), "Desconocido"),
        )
    except Exception:
        return None


async def _resolver_desde_url(url: str) -> tuple[Optional[AnimeData], str]:
    """Si la entrada es una URL conocida, busca por ID/slug directo en su fuente."""
    info = _detect_url(url)
    if not info:
        return None, ""
    fuente, tipo, valor = info
    loop = asyncio.get_running_loop()
    if tipo == "anilist_id":
        r = await loop.run_in_executor(executor, _buscar_por_anilist_id, int(valor))
        return r, "anilist"
    if tipo == "mal_id":
        r = await loop.run_in_executor(executor, _buscar_por_mal_id, int(valor))
        return r, "jikan"
    if tipo == "slug":
        # Para slugs, pasamos a la búsqueda del scraper específico — son tolerantes a slugs
        scraper = SCRAPERS.get(fuente)
        if scraper:
            r = await loop.run_in_executor(executor, scraper.buscar, valor.replace("-", " "))
            return r, fuente
    return None, fuente


# Fuentes con API estructurada: no dependen del HTML de una web, así que son
# las que usamos para rellenar los huecos de un scraper que se haya roto.
_FUENTES_FIABLES = ("anilist", "jikan", "kitsu", "mal")


async def _rellenar_huecos(resultado, nombre: str, fuente_usada: str):
    """Si la ficha viene pobre, la completa con una fuente de API estructurada.

    Los scrapers que leen HTML (animeflv, animeplanet, animeav1) no fallan de
    forma limpia cuando la web cambia el CSS: devuelven una ficha con el nombre
    pero sin episodios, imagen, sinopsis ni géneros. Como es "verdadera", la
    búsqueda la daba por buena y el usuario acababa guardando una ficha hueca.
    Aquí se detecta y se rellena, conservando lo que la fuente original sí trajo.
    """
    from scrapers import calidad
    if not calidad.esta_incompleto(resultado):
        return resultado
    loop = asyncio.get_running_loop()
    for f in _FUENTES_FIABLES:
        if f == fuente_usada or f not in SCRAPERS:
            continue
        try:
            relleno = await loop.run_in_executor(executor, SCRAPERS[f].buscar, nombre)
        except Exception:
            relleno = None
        if relleno:
            _sync_log.info("Ficha pobre de '%s' completada con '%s' (%s)", fuente_usada, f, nombre)
            return calidad.fusionar(resultado, relleno)
    return resultado


# Plazo máximo para que el conjunto de fuentes conteste. Pasado esto, mejor un
# "no encontrado" honesto que una rueda girando indefinidamente.
_TIMEOUT_BUSQUEDA_TOTAL = 30


async def _buscar_con_fallback(nombre: str, fuente_pref: str) -> tuple[Optional[AnimeData], str]:
    """v2: prueba la fuente preferida primero; si falla, lanza las demás en paralelo
    y se queda con la primera que devuelva resultado. Antes era serial → hasta 80s."""
    loop = asyncio.get_running_loop()
    # Un único plazo para TODA la función, fuente preferida incluida. Esta se
    # esperaba sin límite y sin try: si la fuente elegida se colgaba, la
    # búsqueda entera se colgaba con ella; y si lanzaba una excepción, subía
    # hasta el endpoint como un 500 en vez de caer al resto de fuentes.
    limite = loop.time() + _TIMEOUT_BUSQUEDA_TOTAL

    pref = SCRAPERS.get(fuente_pref)
    if pref:
        r = None
        try:
            r = await asyncio.wait_for(
                loop.run_in_executor(executor, pref.buscar, nombre),
                timeout=max(0.05, limite - loop.time()),
            )
        except asyncio.TimeoutError:
            _sync_log.warning("La fuente preferida %r no respondió a tiempo", fuente_pref)
        except Exception as e:
            _sync_log.warning("La fuente preferida %r falló: %s", fuente_pref, e)
        if r:
            return await _rellenar_huecos(r, nombre, fuente_pref), fuente_pref
    # Resto en paralelo, devolver el primero válido.
    # NB: run_in_executor devuelve un Future (no una corutina), así que se usa
    # asyncio.ensure_future —NO create_task, que exige corutina y lanzaba
    # TypeError, rompiendo el fallback cuando la fuente preferida no tenía el anime.
    fuentes = [f for f in SCRAPERS if f != fuente_pref]
    pending = {
        asyncio.ensure_future(loop.run_in_executor(executor, SCRAPERS[f].buscar, nombre)): f
        for f in fuentes
    }
    # Lo que quede del plazo se reparte entre las demás fuentes. Antes se
    # esperaba a que TODAS contestaran, sin límite: si una web se quedaba
    # colgada, "Añadir anime" giraba para siempre.
    try:
        while pending:
            restante = limite - loop.time()
            if restante <= 0:
                _sync_log.warning("Búsqueda de %r agotó el plazo; fuentes sin responder: %s",
                                  nombre, sorted(pending.values()))
                break
            done, _ = await asyncio.wait(pending.keys(), timeout=restante,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:            # se agotó el plazo esperando
                continue            # el `restante <= 0` de arriba corta el bucle
            for task in done:
                fuente = pending.pop(task)
                try:
                    r = task.result()
                except Exception:
                    r = None
                if r:
                    return await _rellenar_huecos(r, nombre, fuente), fuente
    finally:
        # OJO: cancelar el Future no detiene el hilo del executor, solo deja de
        # esperarlo. El hilo se libera cuando vence el timeout de su petición.
        for task in pending:
            task.cancel()
    return None, fuente_pref


@app.post("/api/buscar/multi")
async def buscar_multi(req: BuscarRequest):
    """v2.5: busca en TODAS las fuentes en paralelo y devuelve todos los
    resultados encontrados, para que el usuario elija. Si se pega una URL,
    resuelve directo (un solo resultado)."""
    loop = asyncio.get_running_loop()
    if _detect_url(req.nombre):
        resultado, fuente_usada = await _resolver_desde_url(req.nombre)
        if resultado:
            return {"ok": True, "resultados": [{"fuente": fuente_usada, "data": resultado.__dict__}]}
        return {"ok": False, "mensaje": "No se pudo resolver la URL"}

    ck = f"multi:{req.nombre.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        return cached

    async def _una(f: str):
        try:
            r = await loop.run_in_executor(executor, SCRAPERS[f].buscar, req.nombre)
            return (f, r)
        except Exception:
            return (f, None)

    pares = await asyncio.gather(*[_una(f) for f in SCRAPERS])
    resultados = [{"fuente": f, "data": r.__dict__} for f, r in pares if r]
    if not resultados:
        return {"ok": False, "mensaje": "No encontrado en ninguna fuente"}
    resp = {"ok": True, "resultados": resultados}
    _cache_set(ck, resp)
    return resp

@app.post("/api/buscar")
async def buscar_anime(req: BuscarRequest):
    """Busca sin guardar. Usa caché 5 min para no repetir llamadas externas.

    v2.1: si se pega una URL de AniList/MAL/Kitsu/etc., resuelve directo por
    ID/slug — ni búsqueda fuzzy ni fallback en otras fuentes.
    """
    # Atajo por URL
    url_info = _detect_url(req.nombre)
    if url_info:
        ck = f"url:{req.nombre.strip().lower()}"
        cached = _cache_get(ck)
        if cached:
            return cached
        resultado, fuente_usada = await _resolver_desde_url(req.nombre)
        if not resultado:
            return {"ok": False, "mensaje": f"No se pudo resolver la URL ({url_info[0]})"}
        resp = {"ok": True, "data": resultado.__dict__, "fuente_usada": fuente_usada, "via": "url"}
        _cache_set(ck, resp)
        return resp

    ck = f"{req.fuente}:{req.nombre.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        return cached
    resultado, fuente_usada = await _buscar_con_fallback(req.nombre, req.fuente)
    if not resultado:
        return {"ok": False, "mensaje": "Anime no encontrado"}
    resp = {"ok": True, "data": resultado.__dict__, "fuente_usada": fuente_usada}
    _cache_set(ck, resp)
    return resp

@app.post("/api/animes")
async def guardar_anime(req: BuscarRequest):
    """Busca y guarda directamente. Acepta URL o nombre."""
    loop = asyncio.get_running_loop()
    # v2.1: si es URL, resolver directo
    if _detect_url(req.nombre):
        resultado, fuente_usada = await _resolver_desde_url(req.nombre)
    else:
        resultado, fuente_usada = await _buscar_con_fallback(req.nombre, req.fuente)
    if not resultado:
        raise HTTPException(404, "Anime no encontrado")

    data = resultado.__dict__.copy()
    # Completar con AniList si falta imagen/episodios, si la portada viene de un
    # host poco fiable (anime-planet/animeflv) o si no hay anilist_id (lo
    # necesitan las notificaciones y el enriquecimiento por lotes).
    need_eps, need_img = _enrich_needs(data)
    needs_enrichment = need_eps or need_img or not data.get("anilist_id")
    if needs_enrichment and fuente_usada != "anilist" and "anilist" in SCRAPERS:
        try:
            alt = await asyncio.wait_for(
                loop.run_in_executor(executor, SCRAPERS["anilist"].buscar, data.get("nombre", req.nombre)),
                timeout=10,
            )
            if alt:
                data.update(_enrich_cambios(data, alt, need_eps, need_img))
        except Exception:
            pass
    elif not data.get("imagen"):
        fallback_img = await loop.run_in_executor(executor, _find_anime_image, req.nombre)
        if fallback_img:
            data["imagen"] = fallback_img

    if not (data.get("nombre") or "").strip():
        raise HTTPException(400, "El anime no tiene nombre válido")
    ok, msg = db.guardar_anime(data)
    if not ok:
        raise HTTPException(409 if msg == "duplicado" else 500, msg)

    # Sync automático a Sheets en background
    cfg = _get_sheets_config()
    if cfg:
        anime_dict = db.obtener_anime(data.get("nombre",""))
        if anime_dict:
            _sync_bg(sheets_sync.append_anime, anime_dict, cfg[0], cfg[1])

    saved = db.obtener_anime(data.get("nombre","")) or data
    saved["fuente_usada"] = fuente_usada
    return {"ok": True, "data": saved}


# ── Manga ────────────────────────────────────────────────────────────────────

@app.post("/api/buscar/manga")
async def buscar_manga(req: BuscarRequest):
    """Busca manga en AniList."""
    ck = f"manga:{req.nombre.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    anilist = SCRAPERS.get("anilist")
    if not anilist:
        return {"ok": False, "mensaje": "Fuente AniList no disponible"}
    try:
        r = await asyncio.wait_for(
            loop.run_in_executor(executor, anilist.buscar_manga, req.nombre),
            timeout=15,
        )
    except (asyncio.TimeoutError, Exception):
        r = None
    if not r:
        return {"ok": False, "mensaje": "Manga no encontrado"}
    resp = {"ok": True, "data": r.__dict__, "fuente_usada": "anilist"}
    _cache_set(ck, resp)
    return resp


@app.post("/api/buscar/manga/multi")
async def buscar_manga_multi(req: BuscarRequest):
    """Busca manga en AniList — múltiples resultados."""
    ck = f"manga_multi:{req.nombre.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    anilist = SCRAPERS.get("anilist")
    if not anilist:
        return {"ok": False, "mensaje": "Fuente AniList no disponible"}
    try:
        r = await asyncio.wait_for(
            loop.run_in_executor(executor, anilist.buscar_manga, req.nombre),
            timeout=15,
        )
    except (asyncio.TimeoutError, Exception):
        r = None
    if not r:
        return {"ok": False, "mensaje": "Manga no encontrado"}
    resp = {"ok": True, "resultados": [{"fuente": "anilist", "data": r.__dict__}]}
    _cache_set(ck, resp)
    return resp


@app.post("/api/manga")
async def guardar_manga(req: BuscarRequest):
    """Busca manga en AniList y lo guarda."""
    loop = asyncio.get_running_loop()
    anilist = SCRAPERS.get("anilist")
    if not anilist:
        raise HTTPException(500, "Fuente AniList no disponible")
    try:
        resultado = await asyncio.wait_for(
            loop.run_in_executor(executor, anilist.buscar_manga, req.nombre),
            timeout=15,
        )
    except (asyncio.TimeoutError, Exception):
        resultado = None
    if not resultado:
        raise HTTPException(404, "Manga no encontrado")
    data = resultado.__dict__.copy()
    data["tipo"] = "manga"
    if not (data.get("nombre") or "").strip():
        raise HTTPException(400, "El manga no tiene nombre válido")
    ok, msg = db.guardar_anime(data)
    if not ok:
        raise HTTPException(409 if msg == "duplicado" else 500, msg)
    saved = db.obtener_anime(data.get("nombre","")) or data
    saved["fuente_usada"] = "anilist"
    return {"ok": True, "data": saved}


# NOTA: las rutas catch-all PATCH/DELETE de /api/animes/{nombre:path} se registran
# MÁS ABAJO (tras las subrutas /nota, /tags/{tag}, etc.). Si se registraran aquí
# —antes que las subrutas— el conversor :path se tragaría rutas como ".../nota" o
# ".../tags/x" (nombre="X/nota") y las rompería. Ver el final de la sección animes.

@app.post("/api/animes/restore")
async def restaurar_anime(data: dict):
    """Re-inserta un anime EXACTAMENTE como estaba (para 'Deshacer' tras borrar).
    A diferencia de POST /api/animes, NO re-consulta la fuente: restaura el
    registro completo recibido (capítulos, imagen, progreso, listas...) sin red,
    así el undo es instantáneo, fiel y funciona sin conexión."""
    if not (data.get("nombre") or "").strip():
        raise HTTPException(400, "Falta el nombre")
    # genero puede venir como lista (JSON) o string; guardar_anime acepta ambos
    ok, msg = db.guardar_anime(data)
    if not ok:
        raise HTTPException(409 if msg == "duplicado" else 500, msg)
    cfg = _get_sheets_config()
    if cfg:
        ad = db.obtener_anime(data.get("nombre", ""))
        if ad:
            _sync_bg(sheets_sync.append_anime, ad, cfg[0], cfg[1])
    return {"ok": True}

# ── Sync ──────────────────────────────────────────────────────────────────────

@app.post("/api/sync")
async def sync_sheets(req: SyncRequest):
    sid = req.spreadsheet_id or db.get_config("spreadsheet_id")
    if not sid:
        raise HTTPException(400, "No hay spreadsheet_id configurado")
    if not CREDENTIALS.exists():
        # Antes caía en sincronizar_todo y devolvía un 500 genérico
        raise HTTPException(400, "Falta credentials.json en la carpeta de la app "
                                 "(Configuración → subir credenciales)")
    animes = db.listar_animes()
    ok, msg = sheets_sync.sincronizar_todo(animes, sid, str(CREDENTIALS))
    _record_sync(ok, msg)
    if not ok:
        # v2: no filtramos tracebacks/internals al cliente
        _sync_log.warning("Sheets sync error: %s", msg)
        raise HTTPException(500, "Error al sincronizar con Google Sheets")
    return {"ok": True, "mensaje": msg}

# ── v2.6.2: refrescar metadatos de animes ya guardados (arregla cap=200 viejo) ─

# ── Refresco manual de metadatos (en segundo plano) ─────────────────────────
# Antes era una petición síncrona que re-consultaba la FUENTE ORIGINAL de cada
# anime sin rate limit: con ~340 animes AniList respondía 429, la petición
# duraba muchos minutos y, peor, sobrescribía portadas buenas de AniList con
# las erróneas de anime-planet y números conocidos con "?".

_refresco_lock = threading.Lock()
_refresco_estado: dict = {"en_curso": False}


def _refrescar_todo(animes: list[dict], estado: dict, anilist=None,
                    sleep=_time.sleep) -> dict:
    """Refresca metadatos de fuente con metadatos.cambios_seguros.

    1) Animes con anilist_id → AniList por lotes de 50 (1 petición/lote).
    2) Resto (o ID no encontrado) → _resolver_en_anilist (búsqueda + MAL) y,
       si nada, la fuente original. Actualiza `estado` con el progreso."""
    anilist = anilist or SCRAPERS.get("anilist")
    estado.update(total=len(animes), hechos=0, actualizados=0,
                  sin_cambios=0, fallidos=[])

    def _aplicar(a, nuevo):
        cambios = metadatos.cambios_seguros(a, nuevo)
        if cambios:
            db.refrescar_metadata_anime(a["nombre"], cambios)
            estado["actualizados"] += 1
        else:
            estado["sin_cambios"] += 1

    pendientes: list[dict] = []
    for tipo, mtype in (("anime", "ANIME"), ("manga", "MANGA")):
        con_id = [a for a in animes if a.get("anilist_id")
                  and (a.get("tipo") or "anime") == tipo]
        for i in range(0, len(con_id), 50):
            lote = con_id[i:i + 50]
            try:
                res = anilist.buscar_por_ids(
                    [int(a["anilist_id"]) for a in lote], media_type=mtype) if anilist else {}
            except Exception:
                res = {}
            for a in lote:
                nuevo = res.get(int(a["anilist_id"]))
                if nuevo:
                    _aplicar(a, nuevo)
                    estado["hechos"] += 1
                else:
                    pendientes.append(a)
            sleep(ANILIST_MIN_INTERVAL)
    pendientes += [a for a in animes if not a.get("anilist_id")]

    for a in pendientes:
        nombre = a["nombre"]
        try:
            nuevo = _resolver_en_anilist(nombre, a.get("tipo") or "anime", anilist=anilist)
            if not nuevo:
                fuente = a.get("fuente") or ""
                if fuente in SCRAPERS and fuente != "anilist":
                    nuevo = SCRAPERS[fuente].buscar(nombre)
            if nuevo:
                _aplicar(a, nuevo)
            else:
                estado["fallidos"].append(nombre)
        except Exception:
            estado["fallidos"].append(nombre)
        estado["hechos"] += 1
        sleep(ANILIST_MIN_INTERVAL * (len(candidatos_busqueda(nombre)) + 1))
    return estado


@app.post("/api/animes/refrescar")
async def refrescar_metadata(filtro: dict = None):
    """Lanza el refresco de metadatos en segundo plano y vuelve al momento.
    El progreso se consulta en GET /api/refrescar/estado.

    body opcional: {"solo_cap_200": true} → solo los que tienen 200 capítulos."""
    animes = db.listar_animes()
    if filtro and filtro.get("solo_cap_200"):
        animes = [a for a in animes if str(a.get("capitulos")) == "200"]
    with _refresco_lock:
        if _refresco_estado.get("en_curso"):
            return {"ok": True, "iniciado": False, **_refresco_estado}
        _refresco_estado.clear()
        _refresco_estado.update(en_curso=True, total=len(animes), hechos=0,
                                actualizados=0, sin_cambios=0, fallidos=[],
                                inicio=_time.time(), fin=None)

    def _run():
        try:
            _refrescar_todo(animes, _refresco_estado)
        except Exception as e:
            _sync_log.warning("refresco manual: %s", e)
        finally:
            _refresco_estado.update(en_curso=False, fin=_time.time())

    threading.Thread(target=_run, daemon=True, name="refresco-manual").start()
    return {"ok": True, "iniciado": True, "total": len(animes)}


@app.get("/api/refrescar/estado")
async def refrescar_estado():
    est = dict(_refresco_estado)
    est["fallidos"] = list(est.get("fallidos") or [])[:20]
    return est


# ── Estadísticas ──────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    animes = db.listar_animes()
    total  = len(animes)

    by_state  = {}
    by_source = {}
    genres    = {}
    scores    = []
    total_eps = 0
    total_min = 0
    EP_MIN    = 24   # duración media de un episodio de anime (min)
    MOVIE_MIN = 95   # duración media de una película (min)

    for a in animes:
        estado = a.get("estado_usuario", "pendiente")
        by_state[estado] = by_state.get(estado, 0) + 1

        fuente = a.get("fuente", "?")
        by_source[fuente] = by_source.get(fuente, 0) + 1

        for g in (a.get("genero") or "").split(","):
            g = g.strip()
            if g:
                genres[g] = genres.get(g, 0) + 1

        if a.get("puntuacion"):
            scores.append(float(a["puntuacion"]))

        # ── Episodios y tiempo vistos ──────────────────────────────────────────
        # Un anime "completado" implica que se vieron TODOS sus capítulos, aunque
        # el usuario nunca incrementara episodios_vistos manualmente.
        caps_raw    = str(a.get("capitulos") or "").strip().lower()
        es_pelicula = "pel" in caps_raw  # "película"
        nums        = re.findall(r"\d+", caps_raw)
        caps_total  = int(nums[0]) if nums else 0
        ep_vistos   = int(a.get("episodios_vistos") or 0)
        completado  = estado in ("completado", "completed")

        # Bug heredado v<2.6.2: animes importados con capitulos="200" falso.
        # migrar_cap200() los corrige en background, pero hasta que corra,
        # excluimos estos datos corruptos del cómputo de episodios/horas.
        cap200_corrupto = (caps_total == 200 and ep_vistos == 0
                          and not es_pelicula)

        if es_pelicula:
            if completado or ep_vistos > 0:
                total_eps += 1
                total_min += MOVIE_MIN
        elif cap200_corrupto:
            pass  # no contar hasta que la migración corrija el dato
        else:
            vistos = max(ep_vistos, caps_total) if completado else ep_vistos
            total_eps += vistos
            total_min += vistos * EP_MIN

    avg_score     = round(sum(scores) / len(scores), 2) if scores else 0
    fav_genre     = max(genres, key=genres.get) if genres else "—"
    top_rated     = sorted(
        [a for a in animes if a.get("puntuacion")],
        key=lambda x: float(x["puntuacion"]),
        reverse=True,
    )[:5]
    recently_added = animes[:8]

    return {
        "total":          total,
        "total_episodes": total_eps,
        "total_hours":    round(total_min / 60, 1),
        "avg_score":      avg_score,
        "favorite_genre": fav_genre,
        "by_state":       by_state,
        "by_source":      by_source,
        "genres":         dict(sorted(genres.items(), key=lambda x: -x[1])[:10]),
        "top_rated":      top_rated,
        "recently_added": recently_added,
    }

# ── Importar desde texto ─────────────────────────────────────────────────────

# Patrones de texto que NO son nombres de anime
NOISE = re.compile(
        r"(https?://|www\.|\.com|\.net|\.org|"
        r"episode|capitulo|cap\.|ep\s?\d|"
        r"copyright|privacy|terms|cookie|"
        r"login|sign\s?in|register|password|"
        r"home|menu|search|settings|profile|"
        r"facebook|twitter|instagram|youtube|"
        r"loading|advertisement|^\d+$|"
        r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$)",
        re.IGNORECASE
    )
class ImportRequest(BaseModel):
    texto: str = Field(..., max_length=500_000)  # ~500 KB max, evita DoS
    fuente_preferida: str = "anilist"

@app.post("/api/import/detect")
async def detectar_animes(req: ImportRequest):
    """
    Recibe texto pegado de una página web (Ctrl+A) y detecta nombres de animes.
    Devuelve lista de candidatos sin guardarlos aún.
    """
    texto = req.texto

    # Limpiar líneas vacías y artefactos comunes de copiar/pegar webs
    lineas = [l.strip() for l in texto.splitlines()]
    lineas = [l for l in lineas if len(l) > 2]

    # Filtrar ruido
    candidatos = []
    vistos = set()
    for linea in lineas:
        if NOISE.search(linea):
            continue
        # Longitud razonable para un título de anime: 3-80 chars
        if not (3 <= len(linea) <= 80):
            continue
        # Ignorar si es solo números o símbolos
        if not re.search(r"[a-zA-Z぀-鿿À-ɏ]", linea):
            continue
        # Desduplicar case-insensitive
        key = linea.lower().strip()
        if key in vistos:
            continue
        vistos.add(key)
        candidatos.append(linea)

    # Limitar a 200 candidatos máximo
    return {"candidatos": candidatos[:200], "total": len(candidatos)}

@app.post("/api/import/bulk")
async def importar_bulk(req: ImportRequest):
    """
    Recibe lista de nombres confirmados y los añade a la BD buscando en las fuentes.
    Devuelve resumen: añadidos, duplicados, no encontrados.
    """
    nombres = [n.strip() for n in req.texto.splitlines() if n.strip()]
    if not nombres:
        raise HTTPException(400, "No hay nombres para importar")
    if len(nombres) > 100:
        raise HTTPException(400, "Máximo 100 animes por importación")

    loop = asyncio.get_running_loop()
    resultados = {"añadidos": [], "duplicados": [], "no_encontrados": []}
    cfg = _get_sheets_config()

    for nombre in nombres:
        # Buscar en fuentes
        prioridad = [req.fuente_preferida] + [f for f in SCRAPERS if f != req.fuente_preferida]
        resultado = None
        for fuente in prioridad:
            scraper = SCRAPERS.get(fuente)
            if not scraper:
                continue
            resultado = await loop.run_in_executor(executor, scraper.buscar, nombre)
            if resultado:
                break

        if not resultado:
            resultados["no_encontrados"].append(nombre)
            continue

        ok, msg = db.guardar_anime(resultado.__dict__)
        if msg == "duplicado":
            resultados["duplicados"].append(nombre)
        elif ok:
            resultados["añadidos"].append(resultado.nombre)
            if cfg:
                anime_dict = db.obtener_anime(resultado.nombre)
                if anime_dict:
                    _sync_bg(sheets_sync.append_anime, anime_dict, cfg[0], cfg[1])
        else:
            resultados["no_encontrados"].append(nombre)

    return resultados

@app.get("/api/animes/lista/{nombre_lista}")
async def get_animes_lista(nombre_lista: str):
    """Animes de una lista personalizada."""
    return {"animes": db.listar_por_lista(nombre_lista), "lista": nombre_lista}

@app.get("/api/animes/{nombre:path}/historial")
async def get_historial_anime(nombre: str):
    """Devuelve el historial de cambios de estado de un anime."""
    return {"historial": db.get_historial(nombre)}

def _actualizar_discord(anime: dict) -> None:
    """Publica el estado en Discord sin bloquear la respuesta ni fallar nunca."""
    try:
        import discord_presence
        if discord_presence.activado():
            _sync_bg(discord_presence.actualizar, anime)
    except Exception as e:      # pypresence ausente, etc.
        _sync_log.debug("discord presence: %s", e)


@app.post("/api/animes/{nombre:path}/plus1")
async def plus_episodio(nombre: str, nota: str = ""):
    """Suma 1 episodio visto directamente desde la tarjeta.
    Parámetro opcional `nota`: texto breve sobre el episodio (diario de watching)."""
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevos = (anime.get("episodios_vistos") or 0) + 1
    ok, msg = db.actualizar_anime(nombre, {"episodios_vistos": nuevos})
    if not ok:
        raise HTTPException(500, msg)
    # v2.2: registrar en ep_log para heatmap/streak/wrapped
    db.log_episode(nombre, nuevos)
    # v2.9: guardar nota del episodio si se proporcionó
    if nota and nota.strip():
        db.guardar_nota_episodio(nombre, nuevos, nota.strip()[:2000])
    # Una sola relectura para Sheets y para el email (antes se consultaba dos veces)
    cfg = _get_sheets_config()
    actualizado = db.obtener_anime(nombre)
    if cfg and actualizado:
        _sync_bg(sheets_sync.update_anime_row, actualizado, cfg[0], cfg[1])
    # Notificar por email solo si el anime está en emisión Y tiene la campanita
    if actualizado and actualizado.get("estado_anime", "").lower() in ("en emisión", "releasing", "en emision"):
        _enviar_notif_nuevo_episodio(actualizado, nuevos)
    # Discord Rich Presence (opcional, silencioso si no está configurado)
    if actualizado:
        _actualizar_discord(actualizado)
    return {"ok": True, "episodios_vistos": nuevos}

# ── Notas por episodio ────────────────────────────────────────────────────────

class EpisodeNoteRequest(BaseModel):
    nota: str = Field("", max_length=2000)

@app.get("/api/animes/{nombre:path}/notas-episodio")
async def listar_notas_episodio(nombre: str):
    """Devuelve todas las notas escritas por episodio para un anime."""
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    return {"notas": db.obtener_notas_episodio(nombre)}

@app.post("/api/animes/{nombre:path}/notas-episodio/{episodio}")
async def guardar_nota_episodio(nombre: str, episodio: int, req: EpisodeNoteRequest):
    """Guarda una nota para un episodio concreto."""
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    if episodio <= 0:
        raise HTTPException(400, "Episodio inválido")
    ok = db.guardar_nota_episodio(nombre, episodio, req.nota)
    if not ok:
        raise HTTPException(500, "Error al guardar la nota")
    return {"ok": True, "episodio": episodio}

@app.delete("/api/animes/{nombre:path}/notas-episodio/{episodio}")
async def borrar_nota_episodio(nombre: str, episodio: int):
    """Borra la nota de un episodio."""
    db.borrar_nota_episodio(nombre, episodio)
    return {"ok": True}


# ── API Móvil ────────────────────────────────────────────────────────────────

@app.get("/api/mobile/ping")
async def mobile_ping():
    """El móvil usa esto para descubrir el servidor en la red local.

    `app` conserva el identificador histórico a propósito: las apps móviles ya
    instaladas comprueban exactamente ese valor y cambiarlo las dejaría sin
    poder conectar. El nombre actual va en `name`."""
    return {"app": "AnimeTracker", "name": "Miraru", "version": VERSION, "ok": True}

@app.post("/api/mobile/auth")
async def mobile_auth(req: PinRequest, request: Request):
    """Autenticación con PIN de 4-8 dígitos configurado en PC. Rate-limited por IP."""
    ip = _client_ip(request)
    ok, motivo = _auth_rate_check(ip)
    if not ok:
        raise HTTPException(429, motivo)

    stored_pin = db.get_config("mobile_pin")
    if not stored_pin:
        raise HTTPException(403, "El PIN móvil no está configurado. Actívalo en Ajustes de la app de PC.")

    if not _check_pin(req.pin, stored_pin):
        _auth_record_fail(ip)
        raise HTTPException(403, "PIN incorrecto.")

    _auth_record_ok(ip)
    token = _gen_token()
    _mobile_tokens[token] = _time.time() + _TOKEN_TTL
    return {"ok": True, "token": token, "expira_en": int(_time.time() + _TOKEN_TTL)}

@app.post("/api/mobile/set-pin")
async def set_mobile_pin(req: PinRequest):
    """Configura el PIN. Protegido por el middleware: en modo móvil exige
    loopback o token válido (en v1 cualquiera en LAN podía cambiarlo)."""
    pin = req.pin.strip()
    if not (4 <= len(pin) <= 8) or not pin.isdigit():
        raise HTTPException(400, "El PIN debe tener entre 4 y 8 dígitos.")
    db.set_config("mobile_pin", _hash_pin(pin))
    # Invalidar todos los tokens existentes al cambiar PIN
    _mobile_tokens.clear()
    return {"ok": True}

@app.get("/api/mobile/status")
async def mobile_status():
    """Estado del acceso móvil — sin auth para que el setup de PC funcione."""
    pin_set = bool(db.get_config("mobile_pin"))
    return {
        "pin_configurado": pin_set,
        "tokens_activos":  len(_mobile_tokens),
        "network_host":    db.get_config("network_host") or "",
    }

# ── Endpoints móvil autenticados (misma lógica que PC pero con auth) ─────────

@app.get("/api/mobile/animes")
async def mobile_listar(request: Request):
    _require_auth(request)
    return {"animes": db.listar_animes()}

@app.patch("/api/mobile/animes/{nombre:path}")
async def mobile_actualizar(nombre: str, req: ActualizarRequest, request: Request):
    _require_auth(request)
    campos = {k: v for k, v in (req.model_dump() if hasattr(req, "model_dump") else req.dict()).items() if v is not None}
    if not campos:
        raise HTTPException(400, "Sin campos")
    ok, msg = db.actualizar_anime(nombre, campos)
    if not ok:
        raise HTTPException(404, msg)
    cfg = _get_sheets_config()
    if cfg:
        anime_dict = db.obtener_anime(nombre)
        if anime_dict:
            _sync_bg(sheets_sync.update_anime_row, anime_dict, cfg[0], cfg[1])
    return {"ok": True}

@app.post("/api/mobile/animes/{nombre:path}/plus1")
async def mobile_plus1(nombre: str, request: Request):
    _require_auth(request)
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevos = (anime.get("episodios_vistos") or 0) + 1
    db.actualizar_anime(nombre, {"episodios_vistos": nuevos})
    cfg = _get_sheets_config()
    if cfg:
        updated = db.obtener_anime(nombre)
        if updated:
            _sync_bg(sheets_sync.update_anime_row, updated, cfg[0], cfg[1])
    return {"ok": True, "episodios_vistos": nuevos}

@app.get("/api/mobile/stats")
async def mobile_stats(request: Request):
    _require_auth(request)
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

@app.post("/api/mobile/enable")
async def enable_mobile(req: PinRequest):
    """Activa el modo red y configura el PIN en un solo paso."""
    pin = req.pin.strip()
    if not (4 <= len(pin) <= 8) or not pin.isdigit():
        raise HTTPException(400, "PIN debe tener 4-8 dígitos.")
    db.set_config("mobile_pin", _hash_pin(pin))
    db.set_config("mobile_enabled", "1")
    _mobile_tokens.clear()
    return {
        "ok": True,
        "mensaje": "Reinicia la app para activar el acceso de red.",
        "network_host": db.get_config("network_host") or "desconocido (reinicia primero)",
    }

@app.post("/api/mobile/disable")
async def disable_mobile():
    """Desactiva el modo red y limpia tokens."""
    db.set_config("mobile_enabled", "0")
    db.set_config("mobile_pin", "")
    _mobile_tokens.clear()
    return {"ok": True, "mensaje": "Acceso móvil desactivado. Reinicia la app."}

# ── Discord Rich Presence (opcional) ──────────────────────────────────────────

class DiscordConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    app_id:  Optional[str]  = None


@app.get("/api/discord")
async def get_discord_config():
    """Estado del Rich Presence: activado, si hay App ID y si pypresence existe."""
    try:
        import pypresence  # noqa: F401
        disponible = True
    except Exception:
        disponible = False
    return {
        "enabled":    db.get_config("discord_enabled") == "1",
        "configured": bool(db.get_config("discord_app_id")),
        "disponible": disponible,   # False → falta `pip install pypresence`
    }


@app.post("/api/discord")
async def set_discord_config(req: DiscordConfigRequest):
    """Guarda la configuración. Al desactivar, limpia el estado en Discord."""
    if req.app_id is not None:
        db.set_config("discord_app_id", req.app_id.strip()[:64])
    if req.enabled is not None:
        db.set_config("discord_enabled", "1" if req.enabled else "0")
        if not req.enabled:
            try:
                import discord_presence
                discord_presence.limpiar()
            except Exception:
                pass
    return {"ok": True,
            "enabled": db.get_config("discord_enabled") == "1",
            "configured": bool(db.get_config("discord_app_id"))}


# ── Perfil de usuario ─────────────────────────────────────────────────────────

class PerfilRequest(BaseModel):
    nombre_usuario: Optional[str] = None
    email_notif:    Optional[str] = None

@app.get("/api/perfil")
async def get_perfil():
    """Devuelve el perfil del usuario guardado."""
    return {
        "nombre_usuario": db.get_config("nombre_usuario") or "",
        "email_notif":    db.get_config("email_notif") or "",
        "avatar_url":     "/api/perfil/avatar",
        "tiene_avatar":   (APP_DIR / "avatar.jpg").exists() or (APP_DIR / "avatar.png").exists(),
    }

@app.post("/api/perfil")
async def set_perfil(req: PerfilRequest):
    """Guarda nombre de usuario y email de notificaciones."""
    if req.nombre_usuario is not None:
        db.set_config("nombre_usuario", req.nombre_usuario.strip()[:50])
    if req.email_notif is not None:
        db.set_config("email_notif", req.email_notif.strip()[:100])
    return {"ok": True}

@app.post("/api/perfil/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """Sube foto de perfil (.jpg o .png)."""
    fname = file.filename or ""
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(400, "Formato no soportado. Usa JPG o PNG.")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB max
        raise HTTPException(400, "La imagen es demasiado grande (máx 5MB).")
    # Guardar como avatar.jpg siempre (sobreescribir anterior)
    dest = APP_DIR / f"avatar.{ext}"
    # Borrar avatar anterior si tiene extensión diferente
    for old_ext in ("jpg", "jpeg", "png", "webp"):
        old = APP_DIR / f"avatar.{old_ext}"
        if old.exists() and old != dest:
            old.unlink(missing_ok=True)
    dest.write_bytes(content)
    db.set_config("avatar_ext", ext)
    return {"ok": True, "url": "/api/perfil/avatar"}

@app.get("/api/perfil/avatar")
async def get_avatar():
    """Devuelve la foto de perfil."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = APP_DIR / f"avatar.{ext}"
        if p.exists():
            media = "image/jpeg" if ext in ("jpg","jpeg") else f"image/{ext}"
            return FileResponse(str(p), media_type=media)
    raise HTTPException(404, "Sin avatar")

# ── Novedades — animes recientes de plataformas ───────────────────────────────

_novedades_cache: dict = {}
_NOVEDADES_TTL = 3600  # 1 hora

@app.get("/api/novedades")
async def get_novedades(plataforma: str = "all"):
    """Novedades y estrenos de Netflix, Crunchyroll, etc. via AniList."""
    cache_key = f"novedades:{plataforma}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _fetch_novedades, plataforma)
    _cache_set(cache_key, result)
    return result

def _fetch_novedades(plataforma: str) -> dict:
    """Obtiene animes en emisión y recientes de AniList."""
    # AniList GraphQL — animes en emisión ordenados por popularidad
    query = """
    query ($page: Int, $perPage: Int) {
      Page(page: $page, perPage: $perPage) {
        media(status: RELEASING, type: ANIME, sort: POPULARITY_DESC) {
          title { english romaji }
          episodes
          coverImage { large }
          genres
          status
          description(asHtml: false)
          averageScore
          studios(isMain: true) { nodes { name } }
          nextAiringEpisode { episode airingAt }
          externalLinks { site url }
        }
      }
    }
    """
    streaming_map = {
        "crunchyroll": ["Crunchyroll"],
        "netflix":     ["Netflix"],
        "amazon":      ["Amazon Prime Video"],
        "disney":      ["Disney Plus"],
        "all":         ["Crunchyroll","Netflix","Amazon Prime Video","Disney Plus","Funimation","HIDIVE"],
    }
    target_sites = streaming_map.get(plataforma, streaming_map["all"])

    try:
        data, fallo = _anilist_con_error(query, {"page": 1, "perPage": 50}, timeout=15)
        medias = (data.get("Page") or {}).get("media", [])
        if not medias:
            # AniList caído (o sin datos) -> Kitsu. Ver fuentes_respaldo.py.
            return _novedades_respaldo(plataforma, fallo)

        resultados = []
        for m in medias:
            # Filtrar por plataforma si se especificó
            if plataforma != "all":
                links = [l.get("site","") for l in (m.get("externalLinks") or [])]
                if not any(s.lower() in " ".join(links).lower() for s in target_sites):
                    continue

            # Plataformas disponibles para este anime
            plats = [l.get("site","") for l in (m.get("externalLinks") or [])
                     if l.get("site","") in streaming_map["all"]]

            title = (m.get("title") or {})
            nombre = title.get("english") or title.get("romaji") or "?"
            next_ep = m.get("nextAiringEpisode")

            resultados.append({
                "nombre":      nombre,
                "imagen":      (m.get("coverImage") or {}).get("large", ""),
                "generos":     m.get("genres", [])[:4],
                "estado":      m.get("status", ""),
                "capitulos":   m.get("episodes") or "?",
                "puntuacion":  (m.get("averageScore") or 0) / 10,
                "plataformas": plats[:4],
                "sinopsis":    (m.get("description") or "")[:300],
                "proximo_ep":  next_ep,
            })

        # Ordenar por puntuación
        resultados.sort(key=lambda x: x["puntuacion"], reverse=True)
        return {"novedades": resultados[:30], "plataforma": plataforma,
                "total": len(resultados), "fuente": "AniList"}

    except Exception as e:
        return _novedades_respaldo(plataforma, str(e)[:200])


def _novedades_respaldo(plataforma: str, motivo: str) -> dict:
    """Kitsu cuando AniList no responde. Nunca lanza: es el último recurso."""
    import fuentes_respaldo
    try:
        items = fuentes_respaldo.novedades(plataforma)
        if not items:
            return {"novedades": [], "plataforma": plataforma, "total": 0,
                    "fuente": "Kitsu",
                    "aviso": (f"AniList no está disponible ({motivo}). "
                              "Se usó Kitsu como respaldo, pero no hay resultados "
                              "para este filtro.") if motivo else ""}
        return {
            "novedades": items[:30],
            "plataforma": plataforma,
            "total": len(items),
            "fuente": "Kitsu",
            "aviso": ("AniList no está disponible ahora mismo, así que estos "
                      "datos vienen de Kitsu. Puede que falte el próximo "
                      "episodio de algunos títulos."),
        }
    except Exception as e:
        _sync_log.warning("Respaldo de novedades (Kitsu): %s", e)
        return {"novedades": [], "plataforma": plataforma, "total": 0,
                "error": f"Ni AniList ni Kitsu respondieron. {motivo or e}"[:250]}

# ── Notificaciones por email (nuevos episodios) ───────────────────────────────

class EmailConfigRequest(BaseModel):
    gmail_user: str    # tu@gmail.com
    gmail_app_password: str   # contraseña de app de Google (16 chars)

@app.post("/api/notif/config-email")
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

@app.get("/api/notif/config-email")
async def get_email_config():
    return {
        "gmail_user":    db.get_config("gmail_user") or "",
        "configurado":   bool(db.get_config("gmail_user") and db.get_config("gmail_app_pass")),
    }

@app.post("/api/notif/test-email")
async def test_email():
    """Envía un email de prueba."""
    ok, msg = _enviar_email_prueba()
    if not ok:
        raise HTTPException(500, msg)
    return {"ok": True, "msg": msg}

def _enviar_email(destinatario: str, asunto: str, cuerpo: str) -> tuple[bool, str]:
    """Envía un email via Gmail SMTP."""
    gmail_user = db.get_config("gmail_user")
    gmail_pass = db.get_config("gmail_app_pass")
    if not gmail_user or not gmail_pass:
        return False, "Email no configurado"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"]    = f"Miraru <{gmail_user}>"
        msg["To"]      = destinatario
        msg.attach(MIMEText(cuerpo, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, destinatario, msg.as_string())
        return True, "Enviado"
    except smtplib.SMTPAuthenticationError:
        return False, "Credenciales Gmail incorrectas. Usa una contraseña de app."
    except Exception as e:
        return False, str(e)[:200]

def _enviar_email_prueba() -> tuple[bool, str]:
    email = db.get_config("email_notif") or db.get_config("gmail_user") or ""
    if not email:
        return False, "Configura el email de destino en tu perfil."
    html = """
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;background:#1a1a24;
                color:#e2e2e8;padding:24px;border-radius:12px">
      <h2 style="color:#a78bfa">🎌 Miraru</h2>
      <p>Este es un email de prueba. Las notificaciones están funcionando correctamente.</p>
    </div>"""
    return _enviar_email(email, "✅ Miraru — Notificaciones activas", html)

def _enviar_notif_nuevo_episodio(anime: dict, num_ep: int):
    """Envía notificación de progreso de un anime en emisión.

    Solo si el usuario activó las notificaciones DE ESE anime (campanita). Antes
    bastaba con tener un email configurado, así que marcar +1 episodio enviaba un
    correo en cada clic —maratonear llenaba la bandeja— e ignoraba por completo
    el interruptor `notif_activa` que existe justo para esto.
    """
    if not anime.get("notif_activa"):
        return
    email = db.get_config("email_notif") or ""
    if not email:
        return
    nombre_raw = anime.get("nombre", "?")
    nombre   = _esc(nombre_raw)
    imagen   = _esc(anime.get("imagen", "") or "", quote=True)
    genero   = _esc(anime.get("genero", "") or "")
    puntuacion = _esc(str(anime.get("puntuacion") or "—"))

    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;background:#0a0812;
                color:#edecf4;border-radius:16px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#7c3aed,#a855f7);padding:20px 24px">
        <h2 style="margin:0;color:#fff;font-size:20px">Progreso registrado</h2>
      </div>
      <div style="padding:24px;display:flex;gap:16px">
        {'<img src="'+imagen+'" style="width:80px;height:110px;object-fit:cover;border-radius:8px;flex-shrink:0" />' if imagen else ''}
        <div>
          <h3 style="color:#c4b1ff;margin:0 0 8px">{nombre}</h3>
          <p style="color:#a49dc0;font-size:13px;margin:0 0 4px">Vas por el episodio <strong style="color:#edecf4">{num_ep}</strong></p>
          <p style="color:#a49dc0;font-size:13px;margin:0 0 4px">Géneros: {genero}</p>
          <p style="color:#a49dc0;font-size:13px;margin:0">Tu puntuación: {puntuacion}</p>
        </div>
      </div>
      <div style="padding:0 24px 20px">
        <p style="color:#4a4a60;font-size:11px;margin:0">Miraru — notificación automática</p>
      </div>
    </div>"""
    _sync_bg(_enviar_email, email, f"📺 {nombre_raw} — episodio {num_ep}", html)

# ── Ruta novedades page ────────────────────────────────────────────────────────

@app.get("/calendario", response_class=HTMLResponse)
async def calendario_page():
    return FileResponse(str(TEMPLATES_DIR / "calendario.html"))

@app.get("/recomendaciones", response_class=HTMLResponse)
async def recomendaciones_page():
    return FileResponse(str(TEMPLATES_DIR / "recomendaciones.html"))

@app.get("/novedades", response_class=HTMLResponse)
async def novedades_page():
    return FileResponse(str(TEMPLATES_DIR / "novedades.html"))

# ── Backup automático ─────────────────────────────────────────────────────────

@app.post("/api/backup")
async def crear_backup(incluir_credenciales: bool = False):
    """Crea un backup ZIP de la BD en APP_DIR/backups/.

    v2: por defecto NO incluye credentials.json (era riesgo de filtración si el
    usuario subía el zip a la nube). Pasar ?incluir_credenciales=1 para incluirlo.
    """
    # Leer APP_DIR en tiempo de ejecución (no al importar) para que los tests
    # que setean ANIME_APP_DIR antes de llamar al endpoint vean la ruta correcta
    # aunque main.py ya estuviera importado por otro test.
    _app_dir = Path(os.environ.get("ANIME_APP_DIR", str(APP_DIR)))
    backup_dir = _app_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"anime_tracker_{ts}.zip"
    db_path = Path(os.environ.get("ANIME_DB_PATH", str(_app_dir / "anime_tracker.db")))
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z:
        if db_path.exists():
            # NO copiar el .db a pelo. La BD va en modo WAL: lo confirmado hace
            # poco vive en el fichero -wal y solo pasa al .db en un checkpoint,
            # así que una copia directa se lleva una foto SIN los cambios
            # recientes (aquí llegó a haber 93 KB de datos fuera del .db) y
            # encima puede quedar inconsistente si pilla un checkpoint a medias.
            # La API de backup en línea de SQLite sí produce una foto coherente
            # y con el WAL incluido, incluso con la app escribiendo a la vez.
            with tempfile.TemporaryDirectory() as tmp:
                copia = Path(tmp) / "anime_tracker.db"
                origen = sqlite3.connect(str(db_path))
                destino = sqlite3.connect(str(copia))
                try:
                    with destino:
                        origen.backup(destino)
                finally:
                    destino.close()
                    origen.close()
                z.write(copia, "anime_tracker.db")
        if incluir_credenciales:
            creds = _app_dir / "credentials.json"
            if creds.exists():
                z.write(creds, "credentials.json")
    # Mantener solo los 10 backups más recientes
    backups = sorted(backup_dir.glob("anime_tracker_*.zip"), key=lambda f: f.stat().st_mtime)
    for old in backups[:-10]:
        old.unlink(missing_ok=True)
    size_kb = backup_path.stat().st_size // 1024
    return {
        "ok": True,
        "archivo": backup_path.name,
        "size_kb": size_kb,
        "incluye_credenciales": incluir_credenciales,
    }

@app.get("/api/backups")
async def listar_backups():
    backup_dir = Path(os.environ.get("ANIME_APP_DIR", str(APP_DIR))) / "backups"
    if not backup_dir.exists():
        return {"backups": []}
    backups = sorted(backup_dir.glob("anime_tracker_*.zip"),
                     key=lambda f: f.stat().st_mtime, reverse=True)
    return {"backups": [
        {"nombre": f.name, "size_kb": f.stat().st_size // 1024,
         "fecha": f.stat().st_mtime}
        for f in backups[:20]
    ]}

# ── Importar desde MAL XML ────────────────────────────────────────────────────

@app.post("/api/import/mal-xml")
async def importar_mal_xml(file: UploadFile = File(...)):
    """Importa lista de animes desde el XML de exportación de MyAnimeList."""
    content = await file.read()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(400, f"XML inválido: {e}")

    status_map = {
        "Watching":     "viendo",
        "Completed":    "completado",
        "On-Hold":      "pausa",
        "Dropped":      "abandonado",
        "Plan to Watch":"pendiente",
    }

    animes_raw = []
    for anime in root.findall(".//anime"):
        title = anime.findtext("series_title","").strip()
        status = anime.findtext("my_status","").strip()
        score = anime.findtext("my_score","0")
        watched = anime.findtext("my_watched_episodes","0")
        if not title:
            continue
        animes_raw.append({
            "nombre": title,
            "estado_usuario": status_map.get(status, "pendiente"),
            "puntuacion": float(score) if score and score != "0" else None,
            "episodios_vistos": int(watched) if watched else 0,
        })

    loop = asyncio.get_running_loop()
    añadidos, duplicados, errores = [], [], []
    cfg = _get_sheets_config()

    for data in animes_raw[:200]:  # máx 200
        # Buscar info completa en AniList
        scraper = SCRAPERS.get("anilist")
        resultado = None
        if scraper:
            resultado = await loop.run_in_executor(executor, scraper.buscar, data["nombre"])

        if resultado:
            d = resultado.__dict__.copy()
            d.update({k: v for k, v in data.items() if v is not None and k != "nombre"})
        else:
            d = {
                "nombre": data["nombre"], "fuente": "mal-import",
                "capitulos": 0, "imagen": "", "genero": [],
                "sinopsis": "", "estado_anime": "",
                **{k: v for k, v in data.items() if v is not None},
            }

        ok, msg = db.guardar_anime(d)
        if msg == "duplicado":
            duplicados.append(data["nombre"])
        elif ok:
            añadidos.append(data["nombre"])
            if cfg:
                ad = db.obtener_anime(data["nombre"])
                if ad:
                    _sync_bg(sheets_sync.append_anime, ad, cfg[0], cfg[1])
        else:
            errores.append(data["nombre"])

    return {
        "ok": True,
        "añadidos": len(añadidos),
        "duplicados": len(duplicados),
        "errores": len(errores),
        "total_procesados": min(len(animes_raw), 200),
        "total_en_archivo": len(animes_raw),
        "omitidos": max(0, len(animes_raw) - 200),
    }

# ── Tags personalizados ───────────────────────────────────────────────────────

class TagRequest(BaseModel):
    tag: str

@app.get("/api/animes/{nombre:path}/tags")
async def get_tags(nombre: str):
    tags_str = db.get_config(f"tags:{nombre}") or ""
    return {"tags": [t.strip() for t in tags_str.split(",") if t.strip()]}

@app.post("/api/animes/{nombre:path}/tags")
async def add_tag(nombre: str, req: TagRequest):
    # "/" no se puede borrar luego: DELETE .../tags/{tag} con %2F se decodifica
    # antes del enrutado y {nombre:path} se traga la barra → 404. Y "," es el
    # separador con que se guardan.
    tag = req.tag.replace("/", "-").replace(",", " ").strip()[:30]
    if not tag:
        raise HTTPException(400, "Tag vacío")
    tags_str = db.get_config(f"tags:{nombre}") or ""
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    if tag not in tags:
        tags.append(tag)
    db.set_config(f"tags:{nombre}", ",".join(tags[:20]))
    return {"ok": True, "tags": tags}

@app.delete("/api/animes/{nombre:path}/tags/{tag}")
async def del_tag(nombre: str, tag: str):
    tags_str = db.get_config(f"tags:{nombre}") or ""
    tags = [t.strip() for t in tags_str.split(",") if t.strip() and t.strip() != tag]
    db.set_config(f"tags:{nombre}", ",".join(tags))
    return {"ok": True, "tags": tags}

# ── Sugerencias de búsqueda ───────────────────────────────────────────────────

@app.get("/api/suggest")
async def sugerencias(q: str = ""):
    """Autocompletado rápido: lista local + historial de búsquedas."""
    if len(q) < 2:
        return {"sugerencias": []}
    local = db.buscar_animes(q, limit=5)
    return {"sugerencias": [a["nombre"] for a in local]}




# ── Listas personalizadas ─────────────────────────────────────────────────────

@app.get("/api/listas")
async def get_listas():
    return {"listas": db.listar_listas()}

@app.get("/api/favoritos")
async def get_favoritos():
    return {"animes": db.listar_favoritos()}

@app.post("/api/animes/{nombre:path}/favorito")
async def toggle_favorito(nombre: str):
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevo = 0 if anime.get("favorito") else 1
    ok, msg = db.actualizar_anime(nombre, {"favorito": nuevo})
    if not ok:
        raise HTTPException(500, msg)
    cfg = _get_sheets_config()
    if cfg:
        upd = db.obtener_anime(nombre)
        if upd:
            _sync_bg(sheets_sync.update_anime_row, upd, cfg[0], cfg[1])
    return {"ok": True, "favorito": bool(nuevo), "nombre": nombre}

@app.post("/api/animes/{nombre:path}/notif")
async def toggle_notif(nombre: str):
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevo = 0 if anime.get("notif_activa") else 1
    ok, msg = db.actualizar_anime(nombre, {"notif_activa": nuevo})
    if not ok:
        raise HTTPException(500, msg)
    return {"ok": True, "notif_activa": bool(nuevo), "nombre": nombre}

@app.get("/api/notif/activas")
async def notif_activas():
    return {"animes": db.listar_con_notif()}


# ── ep_log endpoints (v2.2) ───────────────────────────────────────────────────

@app.get("/api/heatmap")
async def heatmap(dias: int = 365):
    """Heatmap estilo GitHub contributions. Devuelve solo días con actividad —
    el frontend rellena los huecos."""
    dias = max(1, min(int(dias), 730))
    return {"dias": db.ep_log_heatmap(dias), "total": db.ep_log_total(dias), "rango": dias}


@app.get("/api/streak")
async def streak():
    """Racha actual y máxima en días con al menos 1 ep visto."""
    return db.ep_log_streak()


@app.get("/api/stats/completion")
async def stats_completion():
    """'Tiempo hasta completar': combina ep_log (primer/último visionado) con el
    estado del anime. Solo devuelve animes completados con varios eps loggeados —
    para los importados de golpe ep_log está vacío, así que no aparecen."""
    spans = {s["nombre"]: s for s in db.ep_log_spans(min_eps=2)}
    if not spans:
        return {"animes": []}
    out = []
    for a in db.listar_animes():
        s = spans.get(a["nombre"])
        if not s:
            continue
        estado = a.get("estado_usuario", "")
        if estado not in ("completado", "completed"):
            continue
        out.append({
            "nombre":     a["nombre"],
            "imagen":     a.get("imagen") or "",
            "episodios":  s["episodios"],
            "dias":       s["dias"],
            "primer":     s["primer"],
            "ultimo":     s["ultimo"],
        })
    out.sort(key=lambda x: -x["dias"])
    return {"animes": out[:15]}


@app.get("/api/continuar")
async def continuar_viendo():
    """Animes 'viendo' priorizados por actividad reciente del usuario.
    Devuelve los que tienen progreso pero no están completos, ordenados por
    último ep loggeado (o por creado_en si nunca se loggeó nada)."""
    todos = db.listar_animes()
    candidatos = []
    for a in todos:
        estado = a.get("estado_usuario", "")
        if estado not in ("viendo", "watching"):
            continue
        # Excluir los que ya completaron
        try:
            total = int(a.get("capitulos") or 0)
        except (ValueError, TypeError):
            total = 0
        vistos = int(a.get("episodios_vistos") or 0)
        if total and vistos >= total:
            continue
        candidatos.append(a)
    if not candidatos:
        return {"animes": []}
    # Obtener última fecha de ep_log para ordenar
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT nombre, MAX(fecha) AS ultima FROM ep_log GROUP BY nombre"
        ).fetchall()
        last_seen = {r["nombre"]: r["ultima"] for r in rows}
    def _key(a):
        # Prioriza: 1) tiene actividad reciente, 2) creado más reciente
        return (last_seen.get(a["nombre"], "0"), a.get("creado_en") or "0")
    candidatos.sort(key=_key, reverse=True)
    # Enriquecer con next_ep para el botón "ver ep X+1"
    out = []
    for a in candidatos[:12]:
        out.append({
            "nombre":           a["nombre"],
            "imagen":           a.get("imagen") or "",
            "capitulos":        a.get("capitulos"),
            "episodios_vistos": a.get("episodios_vistos") or 0,
            "puntuacion":       a.get("puntuacion"),
            "ultima_vista":     last_seen.get(a["nombre"]),
        })
    return {"animes": out}


@app.get("/api/notif/check")
async def notif_check():
    """v2: devuelve solo animes con notif_activa cuyo último episodio emitido
    sea mayor que episodios_vistos. Antes la UI notificaba CADA 30min a todos
    los animes en emisión, dieran o no nuevo episodio."""
    activos = db.listar_con_notif()
    if not activos:
        return {"pendientes": []}
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(executor, _fetch_ultimos_episodios, activos)

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


_QUERY_ULTIMOS_EPS = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids, type: ANIME) { id episodes nextAiringEpisode { airingAt episode } }
  }
}"""


def _fetch_ultimos_episodios(animes: list, max_resolver: int = 5,
                             sleep=_time.sleep) -> dict:
    """Para cada anime devuelve {nombre: {total, next_ep, next_at}}.

    Antes hacía una query con un alias `Media(search:)` por nombre, pero AniList
    responde 404 a TODA la query si un solo título no casa (p. ej. nombres de
    AnimeFLV como "Black Clover (TV)"): todos los alias volvían null y ninguna
    notificación funcionaba. Ahora:
      1. Animes sin `anilist_id` se resuelven por búsqueda (con variantes de
         título) y se guarda el ID — máx. `max_resolver` por llamada.
      2. Una query `Page(media(id_in:))` por cada 50 IDs; los IDs que no
         existan simplemente no aparecen, sin romper el resto.
    Acepta dicts de anime o nombres sueltos (compatibilidad)."""
    items = [a if isinstance(a, dict) else {"nombre": a} for a in (animes or [])]
    if not items:
        return {}
    anilist = SCRAPERS.get("anilist")
    resueltos = 0
    for a in items:
        if a.get("anilist_id") or not anilist or resueltos >= max_resolver:
            continue
        resueltos += 1
        try:
            r = _resolver_en_anilist(a["nombre"], anilist=anilist)
            if r and r.anilist_id:
                a["anilist_id"] = r.anilist_id
                db.refrescar_metadata_anime(a["nombre"], {"anilist_id": r.anilist_id})
        except Exception:
            pass
        sleep(ANILIST_MIN_INTERVAL)

    por_id: dict[int, list[str]] = {}
    for a in items:
        try:
            aid = int(a.get("anilist_id") or 0)
        except (TypeError, ValueError):
            aid = 0
        if aid:
            por_id.setdefault(aid, []).append(a["nombre"])
    out: dict = {}
    ids = list(por_id)
    try:
        for i in range(0, len(ids), 50):
            data = _anilist(_QUERY_ULTIMOS_EPS, {"ids": ids[i:i + 50]}, timeout=15)
            for m in ((data or {}).get("Page") or {}).get("media") or []:
                if not m or not m.get("id"):
                    continue
                nae = m.get("nextAiringEpisode") or {}
                meta = {
                    "total":   m.get("episodes") or 0,
                    "next_ep": nae.get("episode") or 0,
                    "next_at": nae.get("airingAt") or 0,
                }
                for nombre in por_id.get(int(m["id"]), []):
                    out[nombre] = meta
    except Exception as e:
        _sync_log.warning("_fetch_ultimos_episodios: %s", e)
    return out


# ── Animes relacionados ───────────────────────────────────────────────────────

@app.get("/api/animes/{nombre:path}/relacionados")
async def relacionados(nombre: str):
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    src_genres = {g.strip() for g in (anime.get("genero") or "").split(",") if g.strip()}
    if not src_genres:
        return {"relacionados": [], "base": nombre, "generos": []}
    scored = []
    for a in db.listar_animes():
        if a["nombre"] == nombre:
            continue
        ag = {g.strip() for g in (a.get("genero") or "").split(",") if g.strip()}
        n = len(src_genres & ag)
        if n > 0:
            scored.append((n, a))
    scored.sort(key=lambda x: -x[0])
    return {"relacionados": [a for _, a in scored[:8]], "base": nombre, "generos": sorted(src_genres)}


# ── Datos extra de AniList: trailer, streaming, similares ──────────────────────
# Una sola llamada a AniList sirve para tres cosas que antes no mostrábamos en la
# ficha: el tráiler (YouTube/Dailymotion), las plataformas donde verlo y las
# recomendaciones "a quien le gustó X también vio Y".

def _trailer_url(tr: Optional[dict]) -> str:
    """Construye la URL del tráiler a partir de {site, id} de AniList."""
    if not tr:
        return ""
    site = (tr.get("site") or "").lower()
    vid = tr.get("id") or ""
    if not vid:
        return ""
    if site == "youtube":
        return f"https://www.youtube.com/watch?v={vid}"
    if site == "dailymotion":
        return f"https://www.dailymotion.com/video/{vid}"
    return ""


def _fetch_extra(nombre: str) -> dict:
    """Trailer + enlaces de streaming + animes similares para un título."""
    query = """query($search: String) {
      Media(search: $search, type: ANIME) {
        siteUrl
        trailer { id site thumbnail }
        externalLinks { site url }
        recommendations(sort: RATING_DESC, perPage: 8) {
          nodes { mediaRecommendation {
            title { romaji english }
            coverImage { medium }
            siteUrl averageScore
          } }
        }
      }
    }"""
    m = _anilist(query, {"search": nombre}, timeout=12).get("Media")
    if not m:
        return {"trailer": "", "streaming": [], "similar": [], "siteUrl": ""}

    trailer = _trailer_url(m.get("trailer"))

    # Solo plataformas de streaming reconocibles (no wikis/redes)
    known = {"Crunchyroll", "Netflix", "Amazon Prime Video", "Disney Plus",
             "Funimation", "HIDIVE", "Hulu", "Bilibili TV", "VRV", "Max", "YouTube"}
    streaming = []
    for l in (m.get("externalLinks") or []):
        site = l.get("site") or ""
        url = l.get("url") or ""
        if site in known and url:
            streaming.append({"site": site, "url": url})

    similar = []
    for node in ((m.get("recommendations") or {}).get("nodes") or []):
        mr = node.get("mediaRecommendation")
        if not mr:
            continue
        t = mr.get("title") or {}
        titulo = t.get("english") or t.get("romaji") or ""
        if not titulo:
            continue
        similar.append({
            "nombre": titulo,
            "imagen": (mr.get("coverImage") or {}).get("medium") or "",
            "link": mr.get("siteUrl") or "",
            "puntuacion": round((mr.get("averageScore") or 0) / 10, 1),
        })

    return {"trailer": trailer, "streaming": streaming[:6],
            "similar": similar[:8], "siteUrl": m.get("siteUrl") or ""}


@app.get("/api/animes/{nombre:path}/extra")
async def anime_extra(nombre: str):
    """Datos de AniList que enriquecen la ficha: tráiler, dónde verlo y similares.
    Cacheado 5 min porque cada apertura de ficha lo pediría si no."""
    anime = db.obtener_anime(nombre)
    titulo = anime.get("nombre") if anime else nombre
    ck = f"extra:{titulo.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _fetch_extra, titulo)
    _cache_set(ck, result)
    return result


# ── Puntuaciones externas (AniList, MAL/Jikan, Kitsu) ──────────────────────────

def _fetch_score_anilist(nombre: str) -> dict:
    """AniList: averageScore (0-100) y meanScore (0-100)."""
    query = """query($search: String) {
      Media(search: $search, type: ANIME) {
        averageScore meanScore siteUrl
      }
    }"""
    try:
        data, _ = _anilist_con_error(query, {"search": nombre}, timeout=10)
        m = data.get("Media") or {}
        avg = m.get("averageScore")  # 0-100 o None
        mean = m.get("meanScore")
        score_raw = avg or mean
        return {
            "score": round(score_raw / 10, 1) if score_raw else None,
            "score_raw": score_raw,
            "url": m.get("siteUrl") or "",
        }
    except Exception:
        return {"score": None, "score_raw": None, "url": ""}


def _fetch_score_mal(nombre: str) -> dict:
    """MAL vía Jikan v4: score ya viene en escala 1-10."""
    try:
        from scrapers.net import make_session
        s = make_session()
        resp = s.get(
            "https://api.jikan.moe/v4/anime",
            params={"q": nombre, "limit": 3, "sfw": True},
            headers={"User-Agent": f"AnimeTracker/{VERSION}", "Accept-Encoding": "identity"},
            timeout=12,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
        if not items:
            return {"score": None, "score_raw": None, "url": ""}
        a = items[0]
        sc = a.get("score")  # 1-10 float o None
        return {
            "score": round(sc, 1) if sc else None,
            "score_raw": sc,
            "url": a.get("url") or "",
        }
    except Exception:
        return {"score": None, "score_raw": None, "url": ""}


def _fetch_score_kitsu(nombre: str) -> dict:
    """Kitsu: averageRating viene en escala 0-100."""
    try:
        from scrapers.net import make_session
        s = make_session()
        resp = s.get(
            "https://kitsu.io/api/edge/anime",
            params={
                "filter[text]": nombre,
                "page[limit]": 3,
                "fields[anime]": "canonicalTitle,averageRating,slug",
            },
            headers={
                "User-Agent": f"AnimeTracker/{VERSION}",
                "Accept": "application/vnd.api+json",
                "Accept-Encoding": "identity",
            },
            timeout=12,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
        if not items:
            return {"score": None, "score_raw": None, "url": ""}
        attrs = items[0].get("attributes") or {}
        raw = attrs.get("averageRating")  # "83.41" string or None
        slug = attrs.get("slug") or ""
        score = None
        score_raw = None
        if raw:
            try:
                val = float(raw)
                score_raw = val
                score = round(val / 10, 1)  # → 0-10
            except (ValueError, TypeError):
                pass
        return {
            "score": score,
            "score_raw": score_raw,
            "url": f"https://kitsu.io/anime/{slug}" if slug else "",
        }
    except Exception:
        return {"score": None, "score_raw": None, "url": ""}


def _fetch_scores(nombre: str) -> dict:
    """Consulta las tres fuentes y devuelve scores normalizados a 0-10."""
    anilist = _fetch_score_anilist(nombre)
    mal = _fetch_score_mal(nombre)
    kitsu = _fetch_score_kitsu(nombre)

    # Media ponderada de los scores disponibles
    scores = [s["score"] for s in [anilist, mal, kitsu] if s["score"] is not None]
    media = round(sum(scores) / len(scores), 1) if scores else None

    return {
        "anilist": anilist,
        "mal": mal,
        "kitsu": kitsu,
        "media": media,
    }


@app.get("/api/animes/{nombre:path}/scores")
async def anime_scores(nombre: str):
    """Puntuaciones de un anime en AniList, MAL y Kitsu + media general.
    Incluye la puntuación del usuario si la tiene. Cacheado 30 min."""
    anime = db.obtener_anime(nombre)
    titulo = anime.get("nombre") if anime else nombre
    ck = f"scores:{titulo.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        # Siempre actualizar la nota del usuario (puede haber cambiado)
        if anime:
            cached["usuario"] = anime.get("puntuacion") or None
        return cached
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _fetch_scores, titulo)
    # Nota del usuario
    result["usuario"] = (anime.get("puntuacion") or None) if anime else None
    _cache_set(ck, result, ttl=1800)  # 30 min
    return result


# ── Recomendaciones (AniList trending filtrado por géneros del usuario) ────────

@app.get("/api/recomendaciones")
async def api_recomendaciones():
    animes = db.listar_animes()
    genre_weight: Counter = Counter()
    nombres_existentes = set()
    anilist_ids_existentes = set()
    for a in animes:
        nombres_existentes.add(a["nombre"].lower().strip())
        aid = a.get("anilist_id")
        if aid:
            anilist_ids_existentes.add(int(aid))
    for a in animes:
        if a.get("estado_usuario") in ("completado","completed","viendo","watching"):
            bonus = 2 if (a.get("puntuacion") or 0) >= 8 else 1
            for g in (a.get("genero") or "").split(","):
                g = g.strip()
                if g:
                    genre_weight[g] += bonus
    top_genres = [g for g, _ in genre_weight.most_common(5)]
    if not top_genres:
        top_genres = ["Action", "Adventure", "Fantasy"]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _fetch_recomendaciones, top_genres, nombres_existentes, anilist_ids_existentes)
    return result


def _fetch_recomendaciones(top_genres: list, existentes: set, existentes_ids: set | None = None) -> dict:
    try:
        query = """query($genres: [String]) {
          Page(page:1, perPage:30) {
            media(sort:TRENDING_DESC, type:ANIME, genre_in:$genres,
                  status_in:[RELEASING,NOT_YET_RELEASED,FINISHED]) {
              id title { romaji english }
              description(asHtml:false)
              coverImage { large }
              siteUrl genres episodes status
              averageScore popularity trending
            }
          }
        }"""
        data, fallo = _anilist_con_error(query, {"genres": top_genres}, timeout=15)
        items = (data.get("Page") or {}).get("media", [])
        if not items:
            return _recomendaciones_respaldo(top_genres, existentes, fallo)
        recos = []
        for a in items:
            t = a.get("title") or {}
            titulo_en = (t.get("english") or "").strip()
            titulo_ro = (t.get("romaji") or "").strip()
            titulo = titulo_en or titulo_ro
            # Descartar si CUALQUIER variante del título o ID ya está en la biblioteca
            if titulo_en.lower() in existentes or titulo_ro.lower() in existentes:
                continue
            media_id = a.get("id")
            if existentes_ids and media_id and int(media_id) in existentes_ids:
                continue
            desc = re.sub(r"<[^>]+>", "", (a.get("description") or ""))[:250]
            recos.append({
                "nombre": titulo,
                "imagen": (a.get("coverImage") or {}).get("large") or "",
                "genero": ", ".join(a.get("genres") or []),
                "sinopsis": desc,
                "episodios": a.get("episodes") or "?",
                "puntuacion_global": round((a.get("averageScore") or 0) / 10, 1),
                "estado_anime": {"RELEASING":"En emisión","FINISHED":"Finalizado","NOT_YET_RELEASED":"Próximamente"}.get(a.get("status",""),""),
                "link": a.get("siteUrl") or "",
                "trending": a.get("trending") or 0,
            })
        recos.sort(key=lambda x: -x["trending"])
        return {"recomendaciones": recos[:15], "generos_base": top_genres,
                "fuente": "AniList"}
    except Exception as e:
        _sync_log.warning("Recomendaciones error: %s", e)
        return _recomendaciones_respaldo(top_genres, existentes, str(e)[:200])


def _recomendaciones_respaldo(top_genres: list, existentes: set, motivo: str) -> dict:
    """Kitsu cuando AniList no responde. Nunca lanza."""
    import fuentes_respaldo
    try:
        recos = fuentes_respaldo.recomendaciones(top_genres, existentes)
        return {
            "recomendaciones": recos[:15],
            "generos_base": top_genres,
            "fuente": "Kitsu",
            "aviso": ("AniList no está disponible, así que estas "
                      "recomendaciones vienen de Kitsu.") if recos else "",
        }
    except Exception as e:
        _sync_log.warning("Respaldo de recomendaciones (Kitsu): %s", e)
        return {"recomendaciones": [], "generos_base": top_genres,
                "error": f"Ni AniList ni Kitsu respondieron. {motivo or e}"[:250]}


def _anilist_por_ids(ids: list) -> dict:
    """Enriquece varios animes en UNA sola consulta a AniList (id_in).
    Devuelve {id: {imagen, sinopsis, episodios, puntuacion_global, link, estado_anime}}."""
    if not ids:
        return {}
    try:
        query = """query($ids:[Int]){ Page(page:1, perPage:50){
          media(id_in:$ids, type:ANIME){
            id title{romaji english} description(asHtml:false)
            coverImage{large} siteUrl episodes averageScore status
          } } }"""
        data = _anilist(query, {"ids": ids}, timeout=15)
        out = {}
        for a in (data.get("Page") or {}).get("media", []):
            desc = re.sub(r"<[^>]+>", "", (a.get("description") or ""))[:300]
            out[a.get("id")] = {
                "imagen":            (a.get("coverImage") or {}).get("large") or "",
                "sinopsis":          desc,
                "episodios":         a.get("episodes") or "?",
                "puntuacion_global": round((a.get("averageScore") or 0) / 10, 1),
                "link":              a.get("siteUrl") or "",
                "estado_anime":      {"RELEASING": "En emisión", "FINISHED": "Finalizado",
                                      "NOT_YET_RELEASED": "Próximamente"}.get(a.get("status", ""), ""),
            }
        return out
    except Exception as e:
        _sync_log.warning("AniList por ids: %s", e)
        return {}


_TTL_FICHAS_GATEWAY = 12 * 3600      # portadas de una lista fija: cambian nunca


async def _fichas_gateway(pares: list) -> tuple:
    """Portadas y sinopsis de los animes "puerta de entrada".

    `pares` son (id de AniList, título). Devuelve ({id: ficha}, aviso).

    Se cachea aparte del resto de la respuesta porque es la única parte cara y
    la única que NO depende del usuario: la lista de gateway es fija, solo
    cambia el orden según sus géneros. Sin caché, cada visita a la pantalla
    costaba ~3 s (con AniList caído son 13 búsquedas a Kitsu, una por título).
    """
    if not pares:
        return {}, ""

    clave = "gateway:fichas"
    guardado = _cache_get(clave)
    if guardado is not None:
        return guardado

    loop = asyncio.get_running_loop()
    ids = [i for i, _t in pares]
    datos = await loop.run_in_executor(executor, _anilist_por_ids, ids)

    # Los ids de gateway_anime son de AniList, así que si AniList está caído no
    # hay portadas y la pantalla queda con títulos pero sin imágenes. Kitsu no
    # entiende esos ids: hay que buscar por título, solo para los que falten y
    # en paralelo (en serie serían 13 peticiones encadenadas).
    faltan = [(i, t) for i, t in pares if not (datos.get(i) or {}).get("imagen")]
    aviso = ""
    if faltan:
        import fuentes_respaldo
        tareas = [loop.run_in_executor(executor, fuentes_respaldo.ficha_por_titulo, t)
                  for _i, t in faltan]
        rellenos = await asyncio.gather(*tareas, return_exceptions=True)
        recuperadas = 0
        for (anime_id, _t), relleno in zip(faltan, rellenos):
            if isinstance(relleno, dict) and relleno.get("imagen"):
                datos.setdefault(anime_id, {}).update(relleno)
                recuperadas += 1
        if recuperadas:
            aviso = ("AniList no está disponible, así que algunas portadas "
                     "vienen de Kitsu.")

    # Solo se cachea si se consiguió algo: guardar un resultado vacío dejaría la
    # pantalla sin portadas durante 12 h por un corte de red de un segundo.
    if any(f.get("imagen") for f in datos.values()):
        _cache_set(clave, (datos, aviso), ttl=_TTL_FICHAS_GATEWAY)
    return datos, aviso


@app.get("/api/recomendaciones/principiante")
async def api_reco_principiante():
    """Para quien empieza en el anime: pick 'empieza por aquí' + animes puerta de
    entrada, ordenados por tus géneros favoritos (o un orden curado si aún no
    tienes historial). Enriquecido con portadas/sinopsis de AniList."""
    import gateway_anime
    animes = db.listar_animes()
    genre_weight: Counter = Counter()
    for a in animes:
        if a.get("estado_usuario") in ("completado", "completed", "viendo", "watching"):
            for g in (a.get("genero") or "").split(","):
                g = g.strip()
                if g:
                    genre_weight[g] += 1
    top_genres = [g for g, _ in genre_weight.most_common(5)]
    base = gateway_anime.recomendar_principiante(top_genres)

    # `empieza_aqui` es el mismo objeto que recomendaciones[0], no una copia:
    # sin comprobarlo se enriquecería dos veces (y se buscaría dos veces en Kitsu).
    fichas = list(base["recomendaciones"])
    empieza = base.get("empieza_aqui")
    if empieza is not None and not any(f is empieza for f in fichas):
        fichas.append(empieza)

    datos, aviso = await _fichas_gateway([(a["id"], a["titulo"]) for a in fichas])
    for a in fichas:
        a.update(datos.get(a["id"], {}))
    if aviso:
        base["aviso"] = aviso

    base["generos_base"] = top_genres
    return base


# ── Calendario semanal de episodios ───────────────────────────────────────────

@app.get("/api/calendario")
async def api_calendario():
    animes = db.listar_animes()
    viendo = [a for a in animes if a.get("estado_usuario") in ("viendo","watching")]
    if not viendo:
        return {"dias": {}, "total": 0}
    nombres = [a["nombre"] for a in viendo[:25]]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _fetch_calendario, nombres)
    return result


def _fetch_calendario(nombres: list) -> dict:
    """v2: una sola query con aliases — antes hacía N+1 con sleep(0.4) (10s+ bloqueando)."""
    if not nombres:
        return {"dias": {}, "total": 0}
    try:
        # AniList GraphQL permite alias múltiples en una sola petición.
        # Sanitizamos el alias (debe matchear /^[A-Za-z_][A-Za-z0-9_]*$/).
        partes = []
        variables: dict = {}
        for i, nombre in enumerate(nombres):
            alias = f"a{i}"
            var = f"s{i}"
            variables[var] = nombre
            partes.append(
                f"{alias}: Media(search: ${var}, type: ANIME) {{"
                f"  title {{ romaji english }}"
                f"  nextAiringEpisode {{ airingAt episode }}"
                f"  coverImage {{ medium }}"
                f"  episodes"
                f"}}"
            )
        var_decls = ", ".join(f"${v}: String" for v in variables)
        query = f"query ({var_decls}) {{ {' '.join(partes)} }}"

        data = _anilist(query, variables, timeout=20)
        if not data:
            return {"dias": {}, "total": 0}

        now_ts = _time.time()
        horizon = now_ts + 7 * 86400
        dias: dict = {}
        for i, nombre in enumerate(nombres):
            media = data.get(f"a{i}")
            if not media or not media.get("nextAiringEpisode"):
                continue
            nae = media["nextAiringEpisode"]
            air_ts = nae.get("airingAt") or 0
            # v2: descartar episodios pasados (antes solo verificaba el límite superior)
            if not air_ts or air_ts < now_ts or air_ts >= horizon:
                continue
            ep_num = nae.get("episode", "?")
            dt = datetime.datetime.fromtimestamp(air_ts)
            day_key = dt.strftime("%Y-%m-%d")
            titulo = (
                (media.get("title") or {}).get("english")
                or (media.get("title") or {}).get("romaji")
                or nombre
            )
            dias.setdefault(day_key, []).append({
                "nombre":    titulo,
                "episodio":  ep_num,
                "hora":      dt.strftime("%H:%M"),
                "imagen":    (media.get("coverImage") or {}).get("medium") or "",
                "total_eps": media.get("episodes") or "?",
            })
        # Ordenar episodios de cada día por hora
        for k in dias:
            dias[k].sort(key=lambda e: e["hora"])
        total = sum(len(v) for v in dias.values())
        return {"dias": dict(sorted(dias.items())), "total": total}
    except Exception as e:
        return {"dias": {}, "total": 0, "error": str(e)[:200]}


# ── Importar desde AniList por username ───────────────────────────────────────

@app.post("/api/import/anilist")
async def import_anilist(data: dict):
    username = (data.get("username") or "").strip()
    if not username:
        raise HTTPException(400, "Username requerido")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _import_from_anilist, username)


def _import_from_anilist(username: str) -> dict:
    query = """query($username: String) {
      MediaListCollection(userName: $username, type: ANIME) {
        lists { name entries {
          status score progress
          media {
            title { romaji english }
            coverImage { large }
            genres episodes description(asHtml:false)
            status siteUrl
          }
        }}
      }
    }"""
    try:
        data = _anilist(query, {"username": username}, timeout=20)
        lists = (data.get("MediaListCollection") or {}).get("lists", [])
        if not lists:
            return {"ok": False, "error": "Usuario no encontrado o lista vacía"}
        status_map = {"CURRENT":"viendo","COMPLETED":"completado","PAUSED":"pausa","DROPPED":"abandonado","PLANNING":"pendiente","REPEATING":"viendo"}
        added, skipped = 0, 0
        for lst in lists:
            for entry in (lst.get("entries") or []):
                media = entry.get("media") or {}
                titulo = (media.get("title") or {}).get("english") or (media.get("title") or {}).get("romaji") or ""
                if not titulo: continue
                desc = re.sub(r"<[^>]+>", "", (media.get("description") or ""))[:500]
                anime_data = {
                    "nombre": titulo, "fuente": "anilist",
                    "capitulos": media.get("episodes") or "?",
                    "imagen": (media.get("coverImage") or {}).get("large") or "",
                    "genero": media.get("genres") or [],
                    "sinopsis": desc,
                    "estado_anime": {"RELEASING":"En emisión","FINISHED":"Finalizado","NOT_YET_RELEASED":"Próximamente"}.get(media.get("status",""),""),
                    "estado_usuario": status_map.get(entry.get("status",""), "pendiente"),
                    "puntuacion": (entry.get("score") or 0) if entry.get("score") else None,
                    "episodios_vistos": entry.get("progress") or 0,
                }
                ok, msg = db.guardar_anime(anime_data)
                if ok: added += 1
                else: skipped += 1
        return {"ok": True, "añadidos": added, "omitidos": skipped, "username": username}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Perfil compartible ────────────────────────────────────────────────────────

@app.get("/api/perfil/compartir")
async def perfil_compartible():
    animes = db.listar_animes()
    scored = [a for a in animes if a.get("puntuacion")]
    top5 = sorted(scored, key=lambda x: -(x.get("puntuacion") or 0))[:5]
    genre_cnt: Counter = Counter()
    for a in animes:
        for g in (a.get("genero") or "").split(","):
            g = g.strip()
            if g: genre_cnt[g] += 1
    return {
        "stats": {
            "total": len(animes),
            "completados": len([a for a in animes if a.get("estado_usuario") in ("completado","completed")]),
            "viendo": len([a for a in animes if a.get("estado_usuario") in ("viendo","watching")]),
            "episodios": sum(int(a.get("episodios_vistos") or 0) for a in animes),
            "horas": round(sum(int(a.get("episodios_vistos") or 0) for a in animes) * 24 / 60, 1),
            "puntuacion_media": round(sum(a.get("puntuacion") or 0 for a in scored) / max(1, len(scored)), 1),
        },
        "top5": [{"nombre":a["nombre"],"puntuacion":a.get("puntuacion"),"imagen":a.get("imagen","")} for a in top5],
        "generos": [g for g, _ in genre_cnt.most_common(5)],
    }


@app.get("/api/perfil/compartir/html")
async def perfil_compartible_html():
    """Genera una página HTML autocontenida y bonita con tu perfil de anime,
    lista para compartir o guardar como archivo."""
    data = await perfil_compartible()
    perfil = db.get_config_many(["perfil_nombre", "perfil_bio"])
    nombre_usuario = perfil.get("perfil_nombre", "Otaku")
    bio = perfil.get("perfil_bio", "")
    animes = db.listar_animes()
    # Agrupar por estado
    grupos = {}
    for a in animes:
        est = a.get("estado_usuario", "pendiente")
        grupos.setdefault(est, []).append(a)
    # Generar secciones HTML de la lista
    secciones_html = ""
    estado_labels = {
        "completado": "Completados", "completed": "Completados",
        "viendo": "Viendo", "watching": "Viendo",
        "pendiente": "Pendientes", "pending": "Pendientes",
        "abandonado": "Abandonados", "dropped": "Abandonados",
    }
    estado_order = ["viendo", "watching", "completado", "completed", "pendiente", "pending", "abandonado", "dropped"]
    vistos_estados = set()
    for est in estado_order:
        if est in grupos and est not in vistos_estados:
            label = estado_labels.get(est, est.title())
            vistos_estados.add(est)
            # Dedup labels (viendo/watching, completado/completed)
            items = grupos[est]
            cards = ""
            for a in items[:50]:  # limitar para no crear HTML gigante
                img = a.get("imagen") or ""
                punt = a.get("puntuacion") or ""
                punt_html = f'<span class="score">{punt}</span>' if punt else ""
                eps = ""
                if a.get("episodios_vistos"):
                    cap_t = a.get("capitulos") or "?"
                    eps = f'<span class="eps">Ep {a["episodios_vistos"]}/{cap_t}</span>'
                cards += f'''<div class="card">
                  <img src="{img}" alt="" onerror="this.style.display='none'" loading="lazy"/>
                  <div class="info"><span class="title">{a["nombre"]}</span>{eps}{punt_html}</div>
                </div>\n'''
            secciones_html += f'<h2>{label} <span class="count">({len(items)})</span></h2>\n<div class="grid">{cards}</div>\n'

    stats = data["stats"]
    top5_html = "".join(
        f'<div class="top-card"><img src="{t["imagen"]}" alt="" onerror="this.style.display=\'none\'" />'
        f'<span>{t["nombre"]}</span><span class="sc">{t["puntuacion"]}</span></div>'
        for t in data["top5"]
    )
    generos_html = " · ".join(data["generos"])
    html = f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Perfil de {nombre_usuario} — Miraru</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f0f13;color:#e2e2e8;font-family:"Segoe UI",system-ui,sans-serif;padding:24px}}
.container{{max-width:900px;margin:0 auto}}
.header{{text-align:center;padding:32px 0;border-bottom:1px solid #2a2a38;margin-bottom:24px}}
.header h1{{font-size:28px;color:#c4b5fd;margin-bottom:4px}}
.header p{{color:#6b6b88;font-size:14px}}
.stats{{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin:20px 0}}
.stat{{background:#1a1a24;border:1px solid #2a2a38;border-radius:12px;padding:16px 24px;text-align:center;min-width:120px}}
.stat .n{{font-size:28px;font-weight:700;color:#a78bfa}}
.stat .l{{font-size:11px;color:#6b6b88;text-transform:uppercase;letter-spacing:1px;margin-top:4px}}
.top5{{margin:24px 0}}.top5 h2{{font-size:16px;color:#c4b5fd;margin-bottom:12px}}
.top-card{{display:flex;align-items:center;gap:10px;padding:8px 12px;background:#1a1a24;border-radius:8px;margin-bottom:6px}}
.top-card img{{width:40px;height:56px;object-fit:cover;border-radius:4px;flex-shrink:0}}
.top-card span{{font-size:13px;color:#e2e2e8}}.top-card .sc{{margin-left:auto;color:#fbbf24;font-weight:700}}
.genres{{color:#6b6b88;font-size:13px;margin:12px 0 24px;text-align:center}}
h2{{font-size:18px;color:#a78bfa;margin:28px 0 12px}}.count{{color:#6b6b88;font-weight:400;font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}}
.card{{background:#1a1a24;border:1px solid #2a2a38;border-radius:10px;overflow:hidden}}
.card img{{width:100%;height:180px;object-fit:cover}}
.info{{padding:8px 10px}}.title{{font-size:12px;font-weight:600;display:block;line-height:1.3;margin-bottom:4px}}
.eps{{font-size:11px;color:#6b6b88;display:block}}.score{{font-size:11px;color:#fbbf24;font-weight:600}}
.footer{{text-align:center;color:#3a3a4a;font-size:11px;margin-top:40px;padding-top:20px;border-top:1px solid #1a1a24}}
</style></head><body>
<div class="container">
<div class="header">
  <h1>{nombre_usuario}</h1>
  {'<p>'+bio+'</p>' if bio else ''}
</div>
<div class="stats">
  <div class="stat"><div class="n">{stats['total']}</div><div class="l">Animes</div></div>
  <div class="stat"><div class="n">{stats['completados']}</div><div class="l">Completados</div></div>
  <div class="stat"><div class="n">{stats['viendo']}</div><div class="l">Viendo</div></div>
  <div class="stat"><div class="n">{stats['episodios']}</div><div class="l">Episodios</div></div>
  <div class="stat"><div class="n">{stats['horas']}h</div><div class="l">Horas</div></div>
  <div class="stat"><div class="n">{stats['puntuacion_media']}</div><div class="l">Nota media</div></div>
</div>
<div class="genres">Géneros favoritos: {generos_html}</div>
<div class="top5"><h2>Top 5 mejor valorados</h2>{top5_html}</div>
{secciones_html}
<div class="footer">Generado con Miraru · {datetime.datetime.now().strftime('%d/%m/%Y')}</div>
</div></body></html>"""
    return HTMLResponse(content=html)


# ── Historial timeline ────────────────────────────────────────────────────────

@app.get("/api/historial/timeline")
async def historial_timeline():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM historial ORDER BY fecha DESC LIMIT 200").fetchall()
    return {"eventos": [dict(r) for r in rows], "total": len(rows)}

# ── Exportar JSON completo ────────────────────────────────────────────────────

@app.get("/api/export/json")
async def export_json():
    """Exporta toda la lista como JSON para backup o migración."""
    animes = db.listar_animes()
    content = json.dumps({"version": VERSION, "animes": animes}, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=anime_tracker.json"},
    )


# ── Wrapped — resumen anual del usuario ──────────────────────────────────────

@app.get("/api/stats/wrapped")
async def stats_wrapped(year: Optional[int] = None):
    """Resumen tipo 'año en anime': top géneros, más valorados, completados.

    v2.3: si `year` está presente (o por defecto = año en curso), filtra
    `total_episodios` y `completados` por la actividad real de ese año en
    `ep_log` y `historial`. Antes devolvía totales de toda la vida con la
    etiqueta "Mi año X" → la tarjeta exportable mentía.

    Si `year=0` (o `all`) → comportamiento de toda la vida (legacy).
    """
    animes = db.listar_animes()
    scores = [(a["nombre"], float(a["puntuacion"])) for a in animes if a.get("puntuacion")]
    top_scores = sorted(scores, key=lambda x: -x[1])[:5]

    # Si no se especifica, asumimos año en curso (semántica de "Mi año")
    if year is None:
        year = datetime.datetime.now().year
    use_year = year and year > 0

    # ── Cálculos por año (vía ep_log + historial) ────────────────────────────
    if use_year:
        with db.get_conn() as conn:
            total_eps = int(conn.execute(
                "SELECT COUNT(*) AS c FROM ep_log "
                "WHERE strftime('%Y', fecha) = ?", (str(year),)
            ).fetchone()["c"] or 0)
            # Animes únicos con actividad ese año
            nombres_activos = {r["nombre"] for r in conn.execute(
                "SELECT DISTINCT nombre FROM ep_log WHERE strftime('%Y', fecha) = ?",
                (str(year),)
            ).fetchall()}
            # Completados ESE año = filas de historial con estado completado/completed
            completados_year = int(conn.execute(
                "SELECT COUNT(DISTINCT nombre) AS c FROM historial "
                "WHERE strftime('%Y', fecha) = ? AND estado IN ('completado','completed')",
                (str(year),)
            ).fetchone()["c"] or 0)
        # Top géneros: solo de animes con actividad ese año
        relevantes = [a for a in animes if a["nombre"] in nombres_activos]
        genre_cnt: Counter = Counter()
        for a in relevantes:
            for g in (a.get("genero") or "").split(","):
                g = g.strip()
                if g: genre_cnt[g] += 1
        recientes_year = relevantes[:5]
    else:
        completados_year = sum(1 for a in animes if a.get("estado_usuario") in ("completado","completed"))
        total_eps = sum(int(a.get("episodios_vistos") or 0) for a in animes)
        genre_cnt = Counter()
        for a in animes:
            for g in (a.get("genero") or "").split(","):
                g = g.strip()
                if g: genre_cnt[g] += 1
        recientes_year = animes[:5]

    return {
        "year":            year if use_year else None,
        "total_animes":    len(animes),
        "completados":     completados_year,
        "total_episodios": total_eps,
        "horas_estimadas": round(total_eps * 24 / 60, 1),  # 24 min por episodio
        "top_generos":     [{"genero": g, "count": c} for g, c in genre_cnt.most_common(5)],
        "mejor_valorados": [{"nombre": n, "puntuacion": s} for n, s in top_scores],
        "recientes":       recientes_year,
    }


# ── Nota rápida desde tarjeta ─────────────────────────────────────────────────

class NotaRequest(BaseModel):
    nota: str

@app.patch("/api/animes/{nombre:path}/nota")
async def nota_rapida(nombre: str, req: NotaRequest):
    """Actualiza solo las notas de un anime (desde la tarjeta, sin abrir modal)."""
    ok, msg = db.actualizar_anime(nombre, {"notas": req.nota[:500]})
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True}


# ── Auto-detección de episodios (watch folder) ───────────────────────────────

class WatchFolderRequest(BaseModel):
    carpeta: str = Field(..., max_length=500)

@app.get("/api/watch-folder/status")
async def watch_folder_status():
    """Estado del watcher de carpeta."""
    try:
        import watch_folder
        return watch_folder.get_status()
    except Exception:
        return {"activo": False, "carpeta": None, "archivos_procesados": 0, "log": []}

@app.post("/api/watch-folder/start")
async def watch_folder_start(req: WatchFolderRequest):
    """Inicia la vigilancia de una carpeta para auto-detectar episodios."""
    import watch_folder
    carpeta = req.carpeta.strip()
    if not Path(carpeta).is_dir():
        raise HTTPException(400, f"La carpeta no existe: {carpeta}")
    ok = watch_folder.start(carpeta)
    if not ok:
        raise HTTPException(409, "El watcher ya está activo")
    return {"ok": True, "carpeta": carpeta}

@app.post("/api/watch-folder/stop")
async def watch_folder_stop():
    """Para la vigilancia de carpeta."""
    import watch_folder
    watch_folder.stop()
    return {"ok": True}

@app.get("/api/watch-folder/log")
async def watch_folder_log():
    """Log de archivos detectados recientemente."""
    try:
        import watch_folder
        return {"log": watch_folder.get_log()}
    except Exception:
        return {"log": []}


# ── AniList Sync ─────────────────────────────────────────────────────────────

@app.get("/api/anilist/status")
async def anilist_status():
    return anilist_sync.get_connection_info()


@app.post("/api/anilist/connect")
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
    except requests.HTTPError as e:
        raise HTTPException(400, f"Error OAuth: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/anilist/disconnect")
async def anilist_disconnect():
    anilist_sync.disconnect()
    return {"ok": True}


@app.post("/api/anilist/pull")
async def anilist_pull():
    """Descarga la lista de anime + manga de AniList y sincroniza con la BD local."""
    if not anilist_sync.is_connected():
        raise HTTPException(400, "No conectado a AniList")
    from core import executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, anilist_sync.pull_all)
    db._invalidar_cache()
    return result


@app.post("/api/anilist/push")
async def anilist_push():
    """Sube todos los animes con anilist_id a AniList."""
    if not anilist_sync.is_connected():
        raise HTTPException(400, "No conectado a AniList")
    from core import executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, anilist_sync.push_all)
    return result


@app.post("/api/anilist/resolve-ids")
async def anilist_resolve_ids():
    """Busca el anilist_id de animes que aún no lo tienen."""
    from core import executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, anilist_sync.resolve_anilist_ids)
    db._invalidar_cache()
    return result


@app.get("/api/anilist/callback")
async def anilist_callback(code: str = ""):
    """Callback OAuth2 — AniList redirige aquí con ?code=..."""
    if not code:
        return HTMLResponse("<h2>Error: no se recibió código de autorización</h2>")
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
    code: '{code}',
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


# ── Catch-all de animes (PATCH/DELETE) ────────────────────────────────────────
# IMPORTANTE: se definen AQUÍ, al final, para que se registren DESPUÉS de todas
# las subrutas /api/animes/{nombre:path}/... Con el conversor :path (necesario
# para nombres con '/', p.ej. "Fate/stay night"), si fueran antes se tragarían
# rutas como ".../nota" o ".../tags/x" y las romperían.

@app.patch("/api/animes/{nombre:path}")
async def actualizar_anime(nombre: str, req: ActualizarRequest):
    # Compatibilidad Pydantic v1 y v2
    campos = {k: v for k, v in (req.model_dump() if hasattr(req, "model_dump") else req.dict()).items() if v is not None}
    if not campos:
        raise HTTPException(400, "No hay campos para actualizar")
    # v2.2: si suben episodios_vistos, loggear el ep en ep_log — pero solo si
    # es un incremento PEQUEÑO (1-3 eps de golpe). Si alguien corrige un valor
    # de un golpe (ej. de 0 a 50 tras importar), no falsificamos el heatmap
    # con 50 timestamps "now".
    prev = db.obtener_anime(nombre)
    ok, msg = db.actualizar_anime(nombre, campos)
    if not ok:
        raise HTTPException(404, msg)
    if "episodios_vistos" in campos and prev:
        nuevos = int(campos["episodios_vistos"] or 0)
        viejos = int(prev.get("episodios_vistos") or 0)
        delta = nuevos - viejos
        if 0 < delta <= 3:
            for ep in range(viejos + 1, nuevos + 1):
                db.log_episode(nombre, ep)
    # Sync automático en background (Sheets + AniList)
    anime_dict = db.obtener_anime(nombre)
    if anime_dict:
        cfg = _get_sheets_config()
        if cfg:
            _sync_bg(sheets_sync.update_anime_row, anime_dict, cfg[0], cfg[1])
        if anilist_sync.is_connected() and anime_dict.get("anilist_id"):
            _sync_bg(anilist_sync.push_anime, anime_dict)
    return {"ok": True}

@app.delete("/api/animes/{nombre:path}")
async def eliminar_anime(nombre: str):
    ok, msg = db.eliminar_anime(nombre)
    if not ok:
        raise HTTPException(404, msg)
    # Sync automático a Sheets en background
    cfg = _get_sheets_config()
    if cfg:
        _sync_bg(sheets_sync.delete_anime_row, nombre, cfg[0], cfg[1])
    return {"ok": True}



# ── Exportar CSV ──────────────────────────────────────────────────────────────

@app.get("/api/export/csv")
async def export_csv():
    animes = db.listar_animes()
    output = io.StringIO()
    # Orden canónico — mismo que Google Sheets para consistencia
    fields = [
        "nombre", "fuente", "capitulos", "genero", "estado_anime",
        "estado_usuario", "puntuacion", "episodios_vistos",
        "temporada", "lista_personalizada", "favorito", "notif_activa",
        "fecha_inicio", "fecha_fin", "notas",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(animes)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=anime_tracker.csv"},
    )

@app.get("/api/media/export/json")
async def export_media_json():
    """v2.6: exporta la colección de pelis/series como JSON."""
    return JSONResponse(
        content={"media": db.listar_media()},
        headers={"Content-Disposition": "attachment; filename=peliculas_series.json"},
    )

@app.get("/api/media/export/csv")
async def export_media_csv():
    """v2.6: exporta la colección de pelis/series como CSV."""
    items = db.listar_media()
    output = io.StringIO()
    fields = [
        "titulo", "tipo", "anio", "genero", "estado_media", "estado_usuario",
        "puntuacion", "puntuacion_tmdb", "duracion", "temporadas",
        "episodios_vistos", "rewatches", "favorito", "notas", "tmdb_id",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=peliculas_series.csv"},
    )


# ── Unificación, gamificación y export social ─────────────────────────────────
# Los endpoints viven ahora en routers/gamificacion.py

# ── Ejecución directa para desarrollo: `python main.py` ───────────────────────
# Levanta el servidor sin el launcher (no abre navegador). El evento de startup
# se encarga de init_db. Para la experiencia completa de escritorio usa
# `python launcher.py`.
if __name__ == "__main__":
    import uvicorn
    _port = int(os.environ.get("ANIME_PORT", "8765"))
    print(f"Miraru — servidor de desarrollo en http://127.0.0.1:{_port}")
    uvicorn.run(app, host="127.0.0.1", port=_port, log_level="warning")
