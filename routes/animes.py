"""
routes/animes.py — CRUD de animes: listado, ediciones, notas por episodio, tags,
administración/relaciones, refresco de metadatos y ficha enriquecida.

Extraído de main.py. OJO: _sync_bg/_refrescar_todo/_enviar_notif.../
_fetch_extra/_scores_en_paralelo y el estado del refresco viven en
main (los tests los parchean ahí) → se accede via `main.X`.
"""

from __future__ import annotations

import asyncio
import json
import logging as _logging
import threading
import time as _time

from fastapi import APIRouter, HTTPException

import anilist_sync
import database as db
import main  # circular a propósito: nombres de main se leen al servir
import sheets_sync
from core import executor
from main import ActualizarRequest, EpisodeNoteRequest, GrupoRequest, NotaRequest, TagRequest  # noqa: E402
from scrapers.anilist import ANILIST_MIN_INTERVAL

router = APIRouter()

# Mismo objeto que main._sync_log (getLogger devuelve el singleton del nombre)
_sync_log = _logging.getLogger("anime_tracker")

@router.get("/api/animes/search")
async def buscar_local(q: str = "", limit: int = 20):
    """Búsqueda local rápida por nombre — para autocompletado."""
    if not q.strip():
        return {"animes": []}
    resultados = db.buscar_animes(q.strip(), limit=min(limit, 50))
    return {"animes": resultados}
@router.get("/api/animes")
async def listar_animes():
    return {"animes": db.listar_animes()}
@router.get("/api/animes/slim")
async def listar_animes_slim():
    """Versión ligera — solo campos del grid, sin sinopsis/notas."""
    return {"animes": db.listar_animes_slim()}
# Cache de franquicias — se invalida automáticamente con listar_animes_slim()
# y cuando llegan relaciones nuevas de AniList.
_franquicias_cache: list | None = None
_franquicias_version: tuple = ()
_relaciones_cache: dict | None = None
_relaciones_version = 0


def _relaciones_guardadas() -> dict:
    """{anilist_id (str): [ids de la misma saga]} guardado en config."""
    global _relaciones_cache
    if _relaciones_cache is None:
        try:
            _relaciones_cache = json.loads(db.get_config("anilist_relaciones") or "{}")
            if not isinstance(_relaciones_cache, dict):
                _relaciones_cache = {}
        except Exception:
            _relaciones_cache = {}
    return _relaciones_cache


def _guardar_relaciones(nuevas: dict) -> None:
    global _relaciones_cache, _relaciones_version
    rel = dict(_relaciones_guardadas())
    rel.update({str(k): [int(x) for x in v] for k, v in nuevas.items()})
    db.set_config("anilist_relaciones", json.dumps(rel, separators=(",", ":")))
    _relaciones_cache = rel
    _relaciones_version += 1


def _actualizar_relaciones(animes: list[dict], anilist_mod=None, sleep=None) -> int:
    """Pide a AniList las relaciones (secuelas, precuelas…) de los animes que
    aún no las tienen guardadas, en lotes de 50. Así se agrupan solas sagas
    cuyos títulos no se parecen ("Bunny Girl Senpai" / "Santa Claus")."""
    if anilist_mod is None:
        from scrapers import anilist as anilist_mod
    sleep = sleep or _time.sleep
    hechas = _relaciones_guardadas()
    ids = sorted({int(a.get("anilist_id") or 0) for a in animes
                  if (a.get("tipo") or "anime") == "anime"} - {0}
                 - {int(k) for k in hechas if str(k).isdigit()})
    nuevas = 0
    for i in range(0, len(ids), 50):
        lote = ids[i:i + 50]
        res = anilist_mod.relaciones_por_ids(lote)
        if not res:
            break                      # AniList no responde: otro día
        # Los que no vengan se guardan vacíos para no pedirlos en cada arranque.
        _guardar_relaciones({k: res.get(k, []) for k in lote})
        nuevas += len(lote)
        sleep(ANILIST_MIN_INTERVAL)
    return nuevas
@router.get("/api/franquicias")
async def listar_franquicias():
    global _franquicias_cache, _franquicias_version
    import franquicias as fq_mod
    animes = db.listar_animes_slim()
    v = (id(animes), _relaciones_version)  # cambia al invalidarse la caché de slim
    if _franquicias_cache is None or v != _franquicias_version:
        _franquicias_cache = fq_mod.agrupar_franquicias(animes, _relaciones_guardadas())
        _franquicias_version = v
    return {"franquicias": _franquicias_cache}
@router.post("/api/grupos")
async def asignar_grupo(req: GrupoRequest):
    """v2.13: el usuario crea, renombra o deshace grupos (cajas de franquicia).
    grupo="" vuelve al agrupado automático; "-" deja los animes siempre sueltos."""
    grupo = (req.grupo or "").strip()
    if not req.nombres or len(req.nombres) > 2000:
        raise HTTPException(422, "Elige entre 1 y 2000 animes.")
    cambiados = db.asignar_grupo(req.nombres, grupo)
    return {"ok": True, "cambiados": cambiados, "grupo": grupo}
@router.post("/api/animes/restore")
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
    cfg = main._get_sheets_config()
    if cfg:
        ad = db.obtener_anime(data.get("nombre", ""))
        if ad:
            main._sync_bg(sheets_sync.append_anime, ad, cfg[0], cfg[1])
    return {"ok": True}
@router.post("/api/animes/refrescar")
async def refrescar_metadata(filtro: dict = None):
    """Lanza el refresco de metadatos en segundo plano y vuelve al momento.
    El progreso se consulta en GET /api/refrescar/estado.

    body opcional: {"solo_cap_200": true} → solo los que tienen 200 capítulos."""
    animes = db.listar_animes()
    if filtro and filtro.get("solo_cap_200"):
        animes = [a for a in animes if str(a.get("capitulos")) == "200"]
    with main._refresco_lock:
        if main._refresco_estado.get("en_curso"):
            return {"ok": True, "iniciado": False, **main._refresco_estado}
        main._refresco_estado.clear()
        main._refresco_estado.update(en_curso=True, total=len(animes), hechos=0,
                                actualizados=0, sin_cambios=0, fallidos=[],
                                inicio=_time.time(), fin=None)

    def _run():
        try:
            main._refrescar_todo(animes, main._refresco_estado)
        except Exception as e:
            _sync_log.warning("refresco manual: %s", e)
        finally:
            main._refresco_estado.update(en_curso=False, fin=_time.time())

    threading.Thread(target=_run, daemon=True, name="refresco-manual").start()
    return {"ok": True, "iniciado": True, "total": len(animes)}


@router.get("/api/refrescar/estado")
async def refrescar_estado():
    est = dict(main._refresco_estado)
    est["fallidos"] = list(est.get("fallidos") or [])[:20]
    return est
@router.get("/api/animes/lista/{nombre_lista}")
async def get_animes_lista(nombre_lista: str):
    """Animes de una lista personalizada."""
    return {"animes": db.listar_por_lista(nombre_lista), "lista": nombre_lista}

@router.get("/api/animes/{nombre:path}/historial")
async def get_historial_anime(nombre: str):
    """Devuelve el historial de cambios de estado de un anime."""
    return {"historial": db.get_historial(nombre)}

def _actualizar_discord(anime: dict) -> None:
    """Publica el estado en Discord sin bloquear la respuesta ni fallar nunca."""
    try:
        import discord_presence
        if discord_presence.activado():
            main._sync_bg(discord_presence.actualizar, anime)
    except Exception as e:      # pypresence ausente, etc.
        _sync_log.debug("discord presence: %s", e)


@router.post("/api/animes/{nombre:path}/plus1")
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
    cfg = main._get_sheets_config()
    actualizado = db.obtener_anime(nombre)
    if cfg and actualizado:
        main._sync_bg(sheets_sync.update_anime_row, actualizado, cfg[0], cfg[1])
    # Notificar por email solo si el anime está en emisión Y tiene la campanita
    if actualizado and actualizado.get("estado_anime", "").lower() in ("en emisión", "releasing", "en emision"):
        main._enviar_notif_nuevo_episodio(actualizado, nuevos)
    # Discord Rich Presence (opcional, silencioso si no está configurado)
    if actualizado:
        _actualizar_discord(actualizado)
    return {"ok": True, "episodios_vistos": nuevos}
@router.get("/api/animes/{nombre:path}/notas-episodio")
async def listar_notas_episodio(nombre: str):
    """Devuelve todas las notas escritas por episodio para un anime."""
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    return {"notas": db.obtener_notas_episodio(nombre)}

@router.post("/api/animes/{nombre:path}/notas-episodio/{episodio}")
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

@router.delete("/api/animes/{nombre:path}/notas-episodio/{episodio}")
async def borrar_nota_episodio(nombre: str, episodio: int):
    """Borra la nota de un episodio."""
    db.borrar_nota_episodio(nombre, episodio)
    return {"ok": True}
@router.get("/api/animes/{nombre:path}/tags")
async def get_tags(nombre: str):
    tags_str = db.get_config(f"tags:{nombre}") or ""
    return {"tags": [t.strip() for t in tags_str.split(",") if t.strip()]}

@router.post("/api/animes/{nombre:path}/tags")
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

@router.delete("/api/animes/{nombre:path}/tags/{tag}")
async def del_tag(nombre: str, tag: str):
    tags_str = db.get_config(f"tags:{nombre}") or ""
    tags = [t.strip() for t in tags_str.split(",") if t.strip() and t.strip() != tag]
    db.set_config(f"tags:{nombre}", ",".join(tags))
    return {"ok": True, "tags": tags}
@router.get("/api/suggest")
async def sugerencias(q: str = ""):
    """Autocompletado rápido: lista local + historial de búsquedas."""
    if len(q) < 2:
        return {"sugerencias": []}
    local = db.buscar_animes(q, limit=5)
    return {"sugerencias": [a["nombre"] for a in local]}
@router.get("/api/listas")
async def get_listas():
    return {"listas": db.listar_listas()}

@router.get("/api/favoritos")
async def get_favoritos():
    return {"animes": db.listar_favoritos()}

@router.post("/api/animes/{nombre:path}/favorito")
async def toggle_favorito(nombre: str):
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevo = 0 if anime.get("favorito") else 1
    ok, msg = db.actualizar_anime(nombre, {"favorito": nuevo})
    if not ok:
        raise HTTPException(500, msg)
    cfg = main._get_sheets_config()
    if cfg:
        upd = db.obtener_anime(nombre)
        if upd:
            main._sync_bg(sheets_sync.update_anime_row, upd, cfg[0], cfg[1])
    return {"ok": True, "favorito": bool(nuevo), "nombre": nombre}

@router.post("/api/animes/{nombre:path}/notif")
async def toggle_notif(nombre: str):
    anime = db.obtener_anime(nombre)
    if not anime:
        raise HTTPException(404, "No encontrado")
    nuevo = 0 if anime.get("notif_activa") else 1
    ok, msg = db.actualizar_anime(nombre, {"notif_activa": nuevo})
    if not ok:
        raise HTTPException(500, msg)
    return {"ok": True, "notif_activa": bool(nuevo), "nombre": nombre}
@router.get("/api/animes/{nombre:path}/relacionados")
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
@router.get("/api/animes/{nombre:path}/extra")
async def anime_extra(nombre: str):
    """Datos de AniList que enriquecen la ficha: tráiler, dónde verlo y similares.
    Cacheado 5 min porque cada apertura de ficha lo pediría si no."""
    anime = db.obtener_anime(nombre)
    titulo = anime.get("nombre") if anime else nombre
    aid = int((anime or {}).get("anilist_id") or 0)
    if anime and (anime.get("tipo") or "anime") == "manga":
        aid = 0   # el id es de un manga; la consulta pide ANIME
    ck = f"extra:{aid or titulo.lower().strip()}"
    cached = main._cache_get(ck)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, main._fetch_extra, titulo, aid)
    main._cache_set(ck, result)
    return result
@router.get("/api/animes/{nombre:path}/scores")
async def anime_scores(nombre: str):
    """Puntuaciones de un anime en AniList, MAL y Kitsu + media general.
    Incluye la puntuación del usuario si la tiene. Cacheado 30 min."""
    anime = db.obtener_anime(nombre)
    titulo = anime.get("nombre") if anime else nombre
    ck = f"scores:{titulo.lower().strip()}"
    cached = main._cache_get(ck)
    if cached:
        # Siempre actualizar la nota del usuario (puede haber cambiado)
        if anime:
            cached["usuario"] = anime.get("puntuacion") or None
        return cached
    result = await main._scores_en_paralelo(titulo)
    # Nota del usuario
    result["usuario"] = (anime.get("puntuacion") or None) if anime else None
    # Si ninguna fuente respondió no se cachea: a los 5 min se vuelve a intentar.
    hay_alguna = any(result[f]["score"] is not None or result[f]["url"] for f in ("anilist", "mal", "kitsu"))
    main._cache_set(ck, result, ttl=1800 if hay_alguna else 300)
    return result
@router.patch("/api/animes/{nombre:path}/nota")
async def nota_rapida(nombre: str, req: NotaRequest):
    """Actualiza solo las notas de un anime (desde la tarjeta, sin abrir modal)."""
    ok, msg = db.actualizar_anime(nombre, {"notas": req.nota[:500]})
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True}
@router.patch("/api/animes/{nombre:path}")
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
    if prev:
        ini = campos.get("fecha_inicio", prev.get("fecha_inicio") or "")
        fin = campos.get("fecha_fin", prev.get("fecha_fin") or "")
        if ini and fin and fin < ini and ("fecha_inicio" in campos or "fecha_fin" in campos):
            raise HTTPException(422, "La fecha de fin no puede ser anterior a la de inicio.")
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
        cfg = main._get_sheets_config()
        if cfg:
            main._sync_bg(sheets_sync.update_anime_row, anime_dict, cfg[0], cfg[1])
        if anilist_sync.is_connected() and anime_dict.get("anilist_id"):
            main._sync_bg(anilist_sync.push_anime, anime_dict)
    return {"ok": True}

@router.delete("/api/animes/{nombre:path}")
async def eliminar_anime(nombre: str):
    ok, msg = db.eliminar_anime(nombre)
    if not ok:
        raise HTTPException(404, msg)
    # Sync automático a Sheets en background
    cfg = main._get_sheets_config()
    if cfg:
        main._sync_bg(sheets_sync.delete_anime_row, nombre, cfg[0], cfg[1])
    return {"ok": True}
