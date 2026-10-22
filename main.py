"""
main.py — FastAPI app principal.
Resuelve rutas desde ANIME_FROZEN_DIR (sys._MEIPASS en el .exe).
"""
from __future__ import annotations

# stdlib — sorted alphabetically for clarity
import asyncio
import datetime
import hashlib
import hmac
import json
import logging as _logging
import os
import re
import secrets
import smtplib
import sqlite3
import tempfile
import threading
import time as _time
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from pydantic import field_validator
except ImportError:  # Pydantic 1 (Python puro): el que usa install.ps1, sin DLL que
    # el Control inteligente de aplicaciones de Windows pueda bloquear.
    from pydantic import validator as _validator

    def field_validator(*campos):
        def deco(f):
            f = f.__func__ if isinstance(f, classmethod) else f
            return _validator(*campos, allow_reuse=True)(f)
        return deco

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


def _sin_hilos_de_fondo() -> bool:
    """Los tests ponen MIRARU_SIN_HILOS_FONDO=1: cada test recarga main y, sin
    esto, cada recarga lanzaba otra tanda de hilos de fondo (copias, AniList,
    notificaciones) que segundos después escribían en la BD de OTRO test y
    hacían fallar tests al azar (además de llamar a AniList de verdad)."""
    return os.environ.get("MIRARU_SIN_HILOS_FONDO") == "1"


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
        if not _sin_hilos_de_fondo():
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
    instalacion = _tipo_instalacion()
    # v2.12.1: instalada desde Microsoft Store, lo que cuenta es la versión que la
    # Store ofrece YA (tras certificar), no la de GitHub: la release sale horas o
    # días antes y avisar entonces mandaría a una Store que aún no la tiene.
    comprobar = _check_store_version if instalacion == "store" else _check_github_release
    data = await loop.run_in_executor(executor, comprobar)
    data["instalacion"] = instalacion
    _update_cache["ts"] = now
    _update_cache["data"] = data
    return data


# ── Actualizar con un clic (instalaciones hechas con install.ps1) ─────────────
_URL_INSTALADOR = "https://raw.githubusercontent.com/lucasusamentiaga/anime-tracker/main/install.ps1"
_MARCA_INSTALACION = ".miraru-instalado"   # la escribe install.ps1 (igual que launcher.py)


def _tipo_instalacion() -> str:
    """'ps1' = instalada con install.ps1 (se puede actualizar desde la app),
    'exe' = instalador/portable .exe, 'store' = Microsoft Store (se actualiza solo),
    'codigo' = copia del repositorio."""
    import sys
    if os.environ.get("ANIME_EMPAQUETADO") == "1":
        return "store"
    if getattr(sys, "frozen", False):
        return "exe"
    if os.name == "nt" and (APP_DIR / _MARCA_INSTALACION).exists():
        return "ps1"
    return "codigo"


def _lanzar_actualizador() -> None:
    """Abre una ventana de PowerShell visible que ejecuta el instalador oficial sobre
    esta misma carpeta. El instalador cierra Miraru (/api/apagar), actualiza el código
    sin tocar la lista y vuelve a abrirlo. Solo usa programas firmados (powershell.exe)."""
    import subprocess
    env = dict(os.environ)
    env.update(MIRARU_DESTINO=str(APP_DIR), MIRARU_PAUSA="1", MIRARU_IDIOMA=get_lang() or "es",
               MIRARU_TRAS_ACTUALIZAR="1")
    # MIRARU_SIN_ACCESOS se conserva: si se instaló sin accesos directos, se actualiza igual.
    for k in ("MIRARU_SIN_ABRIR", "MIRARU_ZIP", "MIRARU_FORZAR_PYTHON"):
        env.pop(k, None)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", f"irm {_URL_INSTALADOR} | iex"],
        cwd=tempfile.gettempdir(), env=env,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


# La pestaña que lanzó la actualización consulta esto hasta que Miraru vuelve;
# launcher.py lo mira para no abrir una segunda pestaña (MIRARU_TRAS_ACTUALIZAR).
_pestana_esperando = {"ts": 0.0}


@app.get("/api/actualizacion/espera")
async def actualizacion_espera():
    _pestana_esperando["ts"] = _time.time()
    return {"version": VERSION}


@app.post("/api/actualizar")
async def actualizar(request: Request):
    """Actualiza Miraru a la última versión publicada. Solo desde este ordenador y
    solo si se instaló con install.ps1 (el .exe sin firma no puede actualizarse solo)."""
    if not _is_loopback(_client_ip(request)):
        raise HTTPException(403, "Miraru solo puede actualizarse desde este ordenador.")
    origen = request.headers.get("origin")
    if origen and not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", origen):
        raise HTTPException(403, "Origen no permitido.")
    if _tipo_instalacion() != "ps1":
        raise HTTPException(409, "Esta copia de Miraru no se instaló con el instalador: descarga la nueva versión desde GitHub.")
    _lanzar_actualizador()
    return {"ok": True, "mensaje": "Se ha abierto el actualizador. Miraru se cerrará y volverá a abrirse solo."}


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


STORE_ID = "9PJZK97ZG03G"
STORE_URL_APP = f"ms-windows-store://pdp/?productid={STORE_ID}"
STORE_URL_WEB = f"https://apps.microsoft.com/detail/{STORE_ID}"
_URL_CATALOGO_STORE = ("https://displaycatalog.mp.microsoft.com/v7.0/products"
                       f"?bigIds={STORE_ID}&market=ES&languages=es-es&MS-CV=miraru.0")


def version_en_store(texto_catalogo: str) -> str:
    """Saca la versión publicada del catálogo público de Microsoft Store.
    El JSON trae p. ej. "PackageFullName":"LucasUsamentiaga.Miraru_2.11.4.0_x64__…";
    de ahí sale "2.11.4". Devuelve la más alta si hay varias, o "" si no hay."""
    versiones = re.findall(r'"PackageFullName"\s*:\s*"[^"_]+_(\d+)\.(\d+)\.(\d+)\.\d+_',
                           texto_catalogo or "")
    if not versiones:
        return ""
    return ".".join(str(n) for n in max(tuple(int(x) for x in v) for v in versiones))


def _check_store_version() -> dict:
    base = {"current": VERSION, "latest": None, "update_available": False,
            "url": STORE_URL_APP, "url_web": STORE_URL_WEB, "fuente": "store"}
    try:
        resp = requests.get(_URL_CATALOGO_STORE, timeout=10,
                            headers={"User-Agent": f"Miraru/{VERSION}", "Accept": "application/json"})
        if resp.status_code != 200:
            return {**base, "error": f"HTTP {resp.status_code}"}
        v = version_en_store(resp.text)
        return {**base, "latest": v or None, "name": f"v{v}" if v else "",
                "update_available": bool(v and _is_newer(v, VERSION))}
    except Exception as e:
        return {**base, "error": str(e)[:120]}


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
    if _auto_backup_started or _sin_hilos_de_fondo():
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
    if _cap200_started or _sin_hilos_de_fondo():
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
    if _emision_started or _sin_hilos_de_fondo():
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
    if _enrich_started or _sin_hilos_de_fondo():
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
        # v2.13: relaciones de AniList para agrupar sagas de títulos distintos.
        try:
            n = _actualizar_relaciones(db.listar_animes_slim())
            if n:
                _sync_log.info("Relaciones de AniList de %d animes", n)
        except Exception as e:
            _sync_log.warning("relaciones: %s", e)

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
    if _notif_daemon_started or _sin_hilos_de_fondo():
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
    # v2.13: al añadir una saga entera, todas sus entradas van a este grupo.
    grupo: Optional[str] = Field(default=None, max_length=120)


class GrupoRequest(BaseModel):
    """v2.13: grupos hechos por el usuario. grupo "" = automático, "-" = suelto."""
    nombres: list[str]
    grupo: str = Field(default="", max_length=120)

# Estados que entienden las estadísticas, los filtros y la gamificación.
# Cualquier otro valor se guardaba igual y luego no casaba con ninguna consulta:
# el anime desaparecía de los recuentos sin que nada avisara.
# "pausa" lo usan la UI (editor, filtros), las estadísticas y las importaciones
# de MAL (On-Hold) y AniList (PAUSED); faltaba aquí y elegir "En pausa" en el
# editor daba 422.
ESTADOS_VALIDOS = ("pendiente", "viendo", "completado", "abandonado", "pausa")


FECHA_MINIMA = datetime.date(1917, 1, 1)   # el anime más antiguo conservado


def validar_fecha_vista(v: str) -> str:
    try:
        f = datetime.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        raise ValueError("Fecha no válida: usa el formato AAAA-MM-DD.") from None
    # +1 día: con husos horarios el «hoy» del navegador puede ir por delante.
    if f > datetime.date.today() + datetime.timedelta(days=1):
        raise ValueError("La fecha no puede estar en el futuro.")
    if f < FECHA_MINIMA:
        raise ValueError("La fecha es demasiado antigua (antes de 1917 no había anime).")
    return f.isoformat()


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
    grupo:               Optional[str]   = Field(default=None, max_length=120)

    @field_validator("grupo")
    @classmethod
    def _grupo_sin_espacios(cls, v):
        """"   " se guardaba tal cual; es lo mismo que vacío (automático)."""
        return v.strip() if isinstance(v, str) else v

    @field_validator("fecha_inicio", "fecha_fin")
    @classmethod
    def _fecha_posible(cls, v):
        """v2.12: «Empecé a verlo en 1893» se guardaba sin más. Una fecha de
        visionado tiene que existir y no puede ser anterior al primer anime
        (1917) ni posterior a hoy. "" borra la fecha."""
        if v is None or v == "":
            return v
        return validar_fecha_vista(v)

    @field_validator("estado_usuario")
    @classmethod
    def _estado_conocido(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        # El inglés se aceptaba en otras partes del código; se normaliza aquí
        # para no acabar con "watching" y "viendo" conviviendo en la misma BD.
        equivalencias = {"watching": "viendo", "completed": "completado",
                         "pending": "pendiente", "dropped": "abandonado",
                         "paused": "pausa", "on-hold": "pausa", "on hold": "pausa",
                         "en pausa": "pausa"}
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

@app.get("/api/i18n/ui")
async def get_ui_translations():
    """Textos de interfaz escritos en español en las plantillas → idioma activo (ver i18n_ui.py)."""
    import i18n_ui
    return i18n_ui.ui_para(get_lang())

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
    (re.compile(r"https?://(?:www\.)?kitsu\.(?:io|app)/anime/([\w-]+)"), "slug",      "kitsu"),
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
    """Lookup directo en AniList por ID (añadir pegando una URL de AniList).

    Usa el mismo parser que el resto (scrapers.anilist): antes esta consulta
    propia no pedía nextAiringEpisode (One Piece entraba con "?" episodios) y
    no devolvía el anilist_id, justo el dato que ya teníamos."""
    anilist = SCRAPERS.get("anilist")
    if not anilist or not hasattr(anilist, "buscar_por_ids"):
        return None
    return anilist.buscar_por_ids([int(anime_id)]).get(int(anime_id))


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
        if scraper and hasattr(scraper, "buscar_por_slug"):
            r = await loop.run_in_executor(executor, scraper.buscar_por_slug, valor)
            return r, fuente
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





class ImportRequest(BaseModel):
    texto: str = Field(..., max_length=500_000)  # ~500 KB max, evita DoS
    fuente_preferida: str = "anilist"



# ── Notas por episodio ────────────────────────────────────────────────────────

class EpisodeNoteRequest(BaseModel):
    nota: str = Field("", max_length=2000)



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


class EmailConfigRequest(BaseModel):
    gmail_user: str    # tu@gmail.com
    gmail_app_password: str   # contraseña de app de Google (16 chars)


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


# ── Tags personalizados ───────────────────────────────────────────────────────

class TagRequest(BaseModel):
    tag: str


# ── Listas personalizadas ─────────────────────────────────────────────────────








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


def _fetch_extra(nombre: str, anilist_id: int = 0) -> dict:
    """Trailer + enlaces de streaming + animes similares para un título.
    v2.12: también la fecha de estreno (límite inferior de «Fecha inicio»)."""
    query = """query($search: String, $id: Int) {
      Media(search: $search, id: $id, type: ANIME) {
        siteUrl
        startDate { year month day }
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
    variables = {"id": int(anilist_id)} if anilist_id else {"search": nombre}
    m = _anilist(query, variables, timeout=12).get("Media")
    if not m:
        return {"trailer": "", "streaming": [], "similar": [], "siteUrl": "", "estreno": ""}

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
            "similar": similar[:8], "siteUrl": m.get("siteUrl") or "",
            "estreno": _fecha_anilist(m.get("startDate"))}


def _fecha_anilist(d: Optional[dict]) -> str:
    """{year, month, day} de AniList → "AAAA-MM-DD" (el día/mes que falte, 1)."""
    if not d or not d.get("year"):
        return ""
    try:
        return datetime.date(int(d["year"]), int(d.get("month") or 1),
                             int(d.get("day") or 1)).isoformat()
    except (TypeError, ValueError):
        return ""




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
        s = make_session(total=1, backoff=0.3)
        resp = s.get(
            "https://api.jikan.moe/v4/anime",
            params={"q": nombre, "limit": 3, "sfw": True},
            headers={"User-Agent": f"AnimeTracker/{VERSION}", "Accept-Encoding": "identity"},
            timeout=(4, 8),
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
        s = make_session(total=1, backoff=0.3)
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


_SCORE_VACIO = {"score": None, "score_raw": None, "url": ""}
_SCORES_LIMITE = 12      # segundos como mucho para las tres fuentes juntas


def _combinar_scores(anilist: dict, mal: dict, kitsu: dict) -> dict:
    scores = [s["score"] for s in [anilist, mal, kitsu] if s["score"] is not None]
    media = round(sum(scores) / len(scores), 1) if scores else None
    return {"anilist": anilist, "mal": mal, "kitsu": kitsu, "media": media}


async def _scores_en_paralelo(nombre: str) -> dict:
    """Las tres fuentes a la vez y con un tope total. Antes iban una detrás de
    otra con 3 reintentos: con Jikan inaccesible la ficha esperaba más de 40 s."""
    loop = asyncio.get_running_loop()

    async def _una(fn):
        try:
            return await asyncio.wait_for(loop.run_in_executor(executor, fn, nombre),
                                          timeout=_SCORES_LIMITE)
        except Exception:
            return dict(_SCORE_VACIO)
    a, m, k = await asyncio.gather(_una(_fetch_score_anilist), _una(_fetch_score_mal),
                                   _una(_fetch_score_kitsu))
    return _combinar_scores(a, m, k)


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







# ── Nota rápida desde tarjeta ─────────────────────────────────────────────────

class NotaRequest(BaseModel):
    nota: str



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






# ── AnimeAV1 (v2.12) ─────────────────────────────────────────────────────────

class AnimeAV1ConectarRequest(BaseModel):
    cookie: str = Field(..., min_length=3, max_length=8000)






# ── Routers por dominio (Tarea 7: troceo de main.py) ─────────────────────────
# Los módulos de routes/ llegan aquí al FINAL del fichero a propósito: algunos
# hacen `from main import <modelo>` y el resto referencia símbolos del módulo
# (`main._sync_bg`...), de modo que al servir peticiones ven el módulo ya
# cargado del todo (y los parches de tests sobre `main` siguen visibles).
# Los nombres reexportados a continuación los usan tests directamente sobre
# `main` (test_grupos llama saga_casa_con/resumen_saga/_actualizar_relaciones).
from routes import animes as animes_router  # noqa: E402
from routes import busqueda as busqueda_router  # noqa: E402
from routes import estadisticas as estadisticas_router  # noqa: E402
from routes import importar as importar_router  # noqa: E402
from routes import movil as movil_router  # noqa: E402
from routes import notificaciones as notificaciones_router  # noqa: E402
from routes import sincro as sincro_router  # noqa: E402
from routes.animes import _actualizar_relaciones  # noqa: E402,F401  (reexport: daemon de arranque lo usa)
from routes.busqueda import (
    resumen_saga,  # noqa: E402,F401  (reexport para tests)
    saga_casa_con,  # noqa: E402,F401  (reexport para tests)
)

app.include_router(busqueda_router.router)
app.include_router(animes_router.router)
app.include_router(movil_router.router)
app.include_router(sincro_router.router)
app.include_router(notificaciones_router.router)
app.include_router(estadisticas_router.router)
app.include_router(importar_router.router)

# ── Ejecución directa para desarrollo: `python main.py` ───────────────────────
# Levanta el servidor sin el launcher (no abre navegador). El evento de startup
# se encarga de init_db. Para la experiencia completa de escritorio usa
# `python launcher.py`.
if __name__ == "__main__":
    import uvicorn
    _port = int(os.environ.get("ANIME_PORT", "8765"))
    print(f"Miraru — servidor de desarrollo en http://127.0.0.1:{_port}")
    uvicorn.run(app, host="127.0.0.1", port=_port, log_level="warning")
