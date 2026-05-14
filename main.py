"""
main.py — FastAPI app principal.
Resuelve rutas desde ANIME_FROZEN_DIR (sys._MEIPASS en el .exe).
"""
from __future__ import annotations

# stdlib — sorted alphabetically for clarity
import asyncio
import collections
from collections import Counter
import csv
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import logging as _logging
import os
import random
import requests
import re
import secrets
import smtplib
import threading
import time as _time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import sheets_sync
from i18n import set_lang, get_lang, t, TRANSLATIONS
from scrapers import SCRAPERS, AnimeData

# ── Rutas ─────────────────────────────────────────────────────────────────────
FROZEN_DIR    = Path(os.environ.get("ANIME_FROZEN_DIR", Path(__file__).parent))
APP_DIR       = Path(os.environ.get("ANIME_APP_DIR",    Path(__file__).parent))
TEMPLATES_DIR = FROZEN_DIR / "templates"
STATIC_DIR    = FROZEN_DIR / "static"
CREDENTIALS   = APP_DIR / "credentials.json"

# ── Init ──────────────────────────────────────────────────────────────────────
db.init_db()

# Restaurar idioma guardado
saved_lang = db.get_config("lang") or "es"
set_lang(saved_lang)

VERSION = "1.0.0"
app = FastAPI(title="Anime Tracker", version=VERSION)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Caché de búsquedas (5 min TTL) ────────────────────────────────────────────
_search_cache: dict = {}
_CACHE_TTL = 300

def _cache_get(key: str):
    e = _search_cache.get(key)
    if e and (_time.time() - e[0]) < _CACHE_TTL:
        return e[1]
    return None

def _cache_set(key: str, val):
    if len(_search_cache) > 200:
        now = _time.time()
        for k in [k for k, (ts, _) in list(_search_cache.items()) if now - ts > _CACHE_TTL]:
            _search_cache.pop(k, None)
    _search_cache[key] = (_time.time(), val)

executor = ThreadPoolExecutor(max_workers=6)


class PinRequest(BaseModel):
    pin: str

class MobileAuthResponse(BaseModel):
    token: str
    expira_en: int  # unix timestamp

# Token de sesión en memoria — se regenera al reiniciar la app
_mobile_tokens: dict[str, float] = {}   # token -> expiry
_TOKEN_TTL = 86400 * 30  # 30 días

def _gen_token() -> str:
    return secrets.token_urlsafe(32)

def _token_valido(token: str) -> bool:
    exp = _mobile_tokens.get(token)
    if exp is None:
        return False
    if _time.time() > exp:
        _mobile_tokens.pop(token, None)
        return False
    return True

def _require_auth(request):
    """Dependencia FastAPI: verifica token de móvil en header o query."""
    token = request.headers.get("X-Mobile-Token") or request.query_params.get("token", "")
    if not _token_valido(token):
        raise HTTPException(401, "Token inválido o expirado. Reconecta la app móvil.")

_sync_log = _logging.getLogger("anime_tracker")

def _sync_bg(fn, *args):
    """Ejecuta sincronización en background sin bloquear la API."""
    def _run():
        try:
            fn(*args)
        except Exception as e:
            _sync_log.warning("Sheets sync (%s): %s", fn.__name__, e)
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

class ActualizarRequest(BaseModel):
    estado_usuario:      Optional[str]   = None
    puntuacion:          Optional[float] = None
    fecha_inicio:        Optional[str]   = None
    fecha_fin:           Optional[str]   = None
    episodios_vistos:    Optional[int]   = None
    temporada:           Optional[str]   = None
    lista_personalizada: Optional[str]   = None
    favorito:            Optional[int]   = None
    notif_activa:        Optional[int]   = None
    notas:               Optional[str]   = None

class ConfigRequest(BaseModel):
    spreadsheet_id: str

class SyncRequest(BaseModel):
    spreadsheet_id: Optional[str] = None

class LangRequest(BaseModel):
    lang: str


def _find_anime_image(nombre: str) -> str:
    """Busca imagen de un anime en AniList como fallback cuando el scraper no devuelve una."""
    try:
        query = """query($search: String) {
          Media(search: $search, type: ANIME) {
            coverImage { large medium }
            bannerImage
          }
        }"""
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"search": nombre}},
            timeout=8,
        )
        if resp.status_code == 200:
            media = resp.json().get("data", {}).get("Media")
            if media:
                cover = media.get("coverImage") or {}
                return cover.get("large") or cover.get("medium") or media.get("bannerImage") or ""
    except Exception:
        pass
    return ""

@app.get("/api/version")
async def get_version():
    return {"version": VERSION, "name": "Anime Tracker"}

# ── Páginas ───────────────────────────────────────────────────────────────────

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

@app.post("/api/buscar")
async def buscar_anime(req: BuscarRequest):
    """Busca sin guardar. Usa caché 5 min para no repetir llamadas externas."""
    ck = f"{req.fuente}:{req.nombre.lower().strip()}"
    cached = _cache_get(ck)
    if cached:
        return cached
    prioridad = [req.fuente] + [f for f in SCRAPERS if f != req.fuente]
    loop = asyncio.get_running_loop()
    for fuente in prioridad:
        scraper = SCRAPERS.get(fuente)
        if not scraper:
            continue
        resultado: Optional[AnimeData] = await loop.run_in_executor(
            executor, scraper.buscar, req.nombre
        )
        if resultado:
            resp = {"ok": True, "data": resultado.__dict__, "fuente_usada": fuente}
            _cache_set(ck, resp)
            return resp
    return {"ok": False, "mensaje": "Anime no encontrado"}

@app.post("/api/animes")
async def guardar_anime(req: BuscarRequest):
    """Busca y guarda directamente."""
    loop = asyncio.get_running_loop()
    prioridad = [req.fuente] + [f for f in SCRAPERS if f != req.fuente]
    resultado: Optional[AnimeData] = None
    fuente_usada = req.fuente
    for fuente in prioridad:
        scraper = SCRAPERS.get(fuente)
        if not scraper:
            continue
        resultado = await loop.run_in_executor(executor, scraper.buscar, req.nombre)
        if resultado:
            fuente_usada = fuente
            break
    if not resultado:
        raise HTTPException(404, "Anime no encontrado")

    data = resultado.__dict__.copy()
    # Si el scraper no devolvió imagen, buscar en AniList como fallback
    if not data.get("imagen"):
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

@app.patch("/api/animes/{nombre:path}")
async def actualizar_anime(nombre: str, req: ActualizarRequest):
    # Compatibilidad Pydantic v1 y v2
    campos = {k: v for k, v in (req.model_dump() if hasattr(req, "model_dump") else req.dict()).items() if v is not None}
    if not campos:
        raise HTTPException(400, "No hay campos para actualizar")
    ok, msg = db.actualizar_anime(nombre, campos)
    if not ok:
        raise HTTPException(404, msg)
    # Sync automático a Sheets en background
    cfg = _get_sheets_config()
    if cfg:
        anime_dict = db.obtener_anime(nombre)
        if anime_dict:
            _sync_bg(sheets_sync.update_anime_row, anime_dict, cfg[0], cfg[1])
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

# ── Sync ──────────────────────────────────────────────────────────────────────

@app.post("/api/sync")
async def sync_sheets(req: SyncRequest):
    sid = req.spreadsheet_id or db.get_config("spreadsheet_id")
    if not sid:
        raise HTTPException(400, "No hay spreadsheet_id configurado")
    animes = db.listar_animes()
    ok, msg = sheets_sync.sincronizar_todo(animes, sid, str(CREDENTIALS))
    if not ok:
        raise HTTPException(500, msg)
    return {"ok": True, "mensaje": msg}

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

        ep_vistos = a.get("episodios_vistos") or 0
        total_eps += int(ep_vistos)

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
    texto: str
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

@app.post("/api/animes/{nombre:path}/plus1")
async def plus_episodio(nombre: str):
    """Suma 1 episodio visto directamente desde la tarjeta."""
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevos = (anime.get("episodios_vistos") or 0) + 1
    ok, msg = db.actualizar_anime(nombre, {"episodios_vistos": nuevos})
    if not ok:
        raise HTTPException(500, msg)
    cfg = _get_sheets_config()
    if cfg:
        updated = db.obtener_anime(nombre)
        if updated:
            _sync_bg(sheets_sync.update_anime_row, updated, cfg[0], cfg[1])
    # Notificar por email si el anime está en emisión
    anime_upd = db.obtener_anime(nombre)
    if anime_upd and anime_upd.get("estado_anime","").lower() in ("en emisión","releasing","en emision"):
        _enviar_notif_nuevo_episodio(anime_upd, nuevos)
    return {"ok": True, "episodios_vistos": nuevos}

# ── API Móvil ────────────────────────────────────────────────────────────────

@app.get("/api/mobile/ping")
async def mobile_ping():
    """El móvil usa esto para descubrir el servidor en la red local."""
    return {"app": "AnimeTracker", "version": "4.0", "ok": True}

@app.post("/api/mobile/auth")
async def mobile_auth(req: PinRequest):
    """Autenticación con PIN de 4-8 dígitos configurado en PC."""
    stored_pin = db.get_config("mobile_pin")
    if not stored_pin:
        raise HTTPException(403, "El PIN móvil no está configurado. Actívalo en Ajustes de la app de PC.")
    # Comparar hash para no guardar el PIN en claro
    pin_hash = hashlib.sha256(req.pin.encode()).hexdigest()
    if not secrets.compare_digest(stored_pin, pin_hash):
        raise HTTPException(403, "PIN incorrecto.")
    token = _gen_token()
    _mobile_tokens[token] = _time.time() + _TOKEN_TTL
    return {"ok": True, "token": token, "expira_en": int(_time.time() + _TOKEN_TTL)}

@app.post("/api/mobile/set-pin")
async def set_mobile_pin(req: PinRequest):
    """Configura el PIN desde la app de PC (sin auth requerida — solo acceso local)."""
    pin = req.pin.strip()
    if not (4 <= len(pin) <= 8) or not pin.isdigit():
        raise HTTPException(400, "El PIN debe tener entre 4 y 8 dígitos.")
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    db.set_config("mobile_pin", pin_hash)
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
        total_eps += int(a.get("episodios_vistos") or 0)
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
    db.set_config("mobile_pin", hashlib.sha256(pin.encode()).hexdigest())
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
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"page": 1, "perPage": 50}},
            headers={"User-Agent": "AnimeTracker/4.0", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        medias = data.get("data", {}).get("Page", {}).get("media", [])

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
        return {"novedades": resultados[:30], "plataforma": plataforma, "total": len(resultados)}

    except Exception as e:
        return {"novedades": [], "error": str(e)[:200], "plataforma": plataforma}

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
        msg["From"]    = f"Anime Tracker <{gmail_user}>"
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
      <h2 style="color:#a78bfa">🎌 Anime Tracker</h2>
      <p>Este es un email de prueba. Las notificaciones están funcionando correctamente.</p>
    </div>"""
    return _enviar_email(email, "✅ Anime Tracker — Notificaciones activas", html)

def _enviar_notif_nuevo_episodio(anime: dict, num_ep: int):
    """Envía notificación cuando hay nuevo episodio de un anime en emisión."""
    email = db.get_config("email_notif") or ""
    if not email:
        return
    nombre   = anime.get("nombre","?")
    imagen   = anime.get("imagen","")
    genero   = anime.get("genero","")
    puntuacion = anime.get("puntuacion") or "—"

    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;background:#0f0f13;
                color:#e2e2e8;border-radius:16px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#7c3aed,#5b21b6);padding:20px 24px">
        <h2 style="margin:0;color:#fff;font-size:20px">🎌 Nuevo episodio disponible</h2>
      </div>
      <div style="padding:24px;display:flex;gap:16px">
        {'<img src="'+imagen+'" style="width:80px;height:110px;object-fit:cover;border-radius:8px;flex-shrink:0" />' if imagen else ''}
        <div>
          <h3 style="color:#a78bfa;margin:0 0 8px">{nombre}</h3>
          <p style="color:#6b6b88;font-size:13px;margin:0 0 4px">Episodio <strong style="color:#e2e2e8">{num_ep}</strong> ya disponible</p>
          <p style="color:#6b6b88;font-size:13px;margin:0 0 4px">Géneros: {genero}</p>
          <p style="color:#6b6b88;font-size:13px;margin:0">Tu puntuación: {puntuacion}</p>
        </div>
      </div>
      <div style="padding:0 24px 20px">
        <p style="color:#4a4a60;font-size:11px;margin:0">Anime Tracker — notificación automática</p>
      </div>
    </div>"""
    _sync_bg(_enviar_email, email, f"📺 Nuevo ep de {nombre} — Episodio {num_ep}", html)

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
async def crear_backup():
    """Crea un backup ZIP de la base de datos en APP_DIR/backups/."""
    backup_dir = APP_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"anime_tracker_{ts}.zip"
    db_path = Path(os.environ.get("ANIME_DB_PATH", str(APP_DIR / "anime_tracker.db")))
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z:
        if db_path.exists():
            z.write(db_path, "anime_tracker.db")
        creds = APP_DIR / "credentials.json"
        if creds.exists():
            z.write(creds, "credentials.json")
    # Mantener solo los 10 backups más recientes
    backups = sorted(backup_dir.glob("anime_tracker_*.zip"), key=lambda f: f.stat().st_mtime)
    for old in backups[:-10]:
        old.unlink(missing_ok=True)
    size_kb = backup_path.stat().st_size // 1024
    return {"ok": True, "archivo": backup_path.name, "size_kb": size_kb}

@app.get("/api/backups")
async def listar_backups():
    backup_dir = APP_DIR / "backups"
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
        "total_procesados": len(animes_raw),
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
    tag = req.tag.strip()[:30]
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



# ── Recomendaciones (AniList trending filtrado por géneros del usuario) ────────

@app.get("/api/recomendaciones")
async def api_recomendaciones():
    animes = db.listar_animes()
    genre_weight: Counter = Counter()
    nombres_existentes = {a["nombre"].lower().strip() for a in animes}
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
    result = await loop.run_in_executor(executor, _fetch_recomendaciones, top_genres, nombres_existentes)
    return result


def _fetch_recomendaciones(top_genres: list, existentes: set) -> dict:
    try:
        query = """query($genres: [String]) {
          Page(page:1, perPage:30) {
            media(sort:TRENDING_DESC, type:ANIME, genre_in:$genres,
                  status_in:[RELEASING,NOT_YET_RELEASED,FINISHED]) {
              title { romaji english }
              description(asHtml:false)
              coverImage { large }
              siteUrl genres episodes status
              averageScore popularity trending
            }
          }
        }"""
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"genres": top_genres}},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"recomendaciones": [], "generos_base": top_genres}
        items = resp.json().get("data", {}).get("Page", {}).get("media", [])
        recos = []
        for a in items:
            titulo = (a.get("title") or {}).get("english") or (a.get("title") or {}).get("romaji") or ""
            if titulo.lower().strip() in existentes:
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
        return {"recomendaciones": recos[:15], "generos_base": top_genres}
    except Exception as e:
        _sync_log.warning("Recomendaciones error: %s", e)
        return {"recomendaciones": [], "generos_base": top_genres, "error": str(e)}


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
    try:
        query = """query($search: String) {
          Media(search: $search, type: ANIME) {
            title { romaji english }
            nextAiringEpisode { airingAt episode timeUntilAiring }
            coverImage { medium }
            episodes
          }
        }"""
        dias = {}
        for nombre in nombres:
            try:
                resp = requests.post(
                    "https://graphql.anilist.co",
                    json={"query": query, "variables": {"search": nombre}},
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue
                media = resp.json().get("data", {}).get("Media")
                if not media or not media.get("nextAiringEpisode"):
                    continue
                nae = media["nextAiringEpisode"]
                air_ts = nae.get("airingAt", 0)
                ep_num = nae.get("episode", "?")
                if air_ts and air_ts < _time.time() + 7 * 86400:
                    dt = datetime.datetime.fromtimestamp(air_ts)
                    day_key = dt.strftime("%Y-%m-%d")
                    titulo = (media.get("title") or {}).get("english") or (media.get("title") or {}).get("romaji") or nombre
                    if day_key not in dias:
                        dias[day_key] = []
                    dias[day_key].append({
                        "nombre": titulo,
                        "episodio": ep_num,
                        "hora": dt.strftime("%H:%M"),
                        "imagen": (media.get("coverImage") or {}).get("medium") or "",
                        "total_eps": media.get("episodes") or "?",
                    })
                _time.sleep(0.4)
            except Exception:
                continue
        total = sum(len(v) for v in dias.values())
        return {"dias": dict(sorted(dias.items())), "total": total}
    except Exception as e:
        return {"dias": {}, "total": 0, "error": str(e)}


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
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"username": username}},
            timeout=20,
        )
        if resp.status_code != 200:
            return {"ok": False, "error": f"AniList HTTP {resp.status_code}"}
        lists = resp.json().get("data",{}).get("MediaListCollection",{}).get("lists",[])
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
    content = json.dumps({"version": "4.0", "animes": animes}, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=anime_tracker.json"},
    )


# ── Anime aleatorio ───────────────────────────────────────────────────────────

# ── Wrapped — resumen anual del usuario ──────────────────────────────────────

@app.get("/api/stats/wrapped")
async def stats_wrapped():
    """Resumen tipo 'año en anime': top géneros, más valorados, completados."""
    animes = db.listar_animes()
    completados = [a for a in animes if a.get("estado_usuario") in ("completado","completed")]
    scores = [(a["nombre"], float(a["puntuacion"])) for a in animes if a.get("puntuacion")]
    top_scores = sorted(scores, key=lambda x: -x[1])[:5]
    genre_cnt: Counter = Counter()
    for a in animes:
        for g in (a.get("genero") or "").split(","):
            g = g.strip()
            if g: genre_cnt[g] += 1
    total_eps = sum(int(a.get("episodios_vistos") or 0) for a in animes)
    return {
        "total_animes":    len(animes),
        "completados":     len(completados),
        "total_episodios": total_eps,
        "horas_estimadas": round(total_eps * 24 / 60, 1),  # 24 min por episodio
        "top_generos":     [{"genero": g, "count": c} for g, c in genre_cnt.most_common(5)],
        "mejor_valorados": [{"nombre": n, "puntuacion": s} for n, s in top_scores],
        "recientes":       animes[:5],
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


# ── Noticias anime (RSS feeds) ────────────────────────────────────────────────





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