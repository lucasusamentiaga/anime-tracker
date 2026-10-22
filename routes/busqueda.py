"""
routes/busqueda.py — Búsqueda de animes (fuentes, franquicias, manga) y guardado directo.

Extraído de main.py. OJO: los símbolos que viven en main y que los
tests parchean en el módulo `main` (SCRAPERS, _detect_url,
_buscar_con_fallback, _enrich_needs, _find_anime_image, _sync_bg...)
se referencian SIEMPRE via `main.X` en tiempo de llamada para que el
parche siga siendo visible desde aquí.
"""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException

import database as db
import main  # circular a propósito: nombres de main se leen al servir
import sheets_sync
from core import executor
from main import BuscarRequest  # noqa: E402  (modelos def in main)

router = APIRouter()

@router.get("/api/fuentes")
async def listar_fuentes():
    return {"fuentes": list(main.SCRAPERS.keys())}
@router.post("/api/buscar/franquicia")
async def buscar_franquicia(req: BuscarRequest):
    """v2.13: toda la saga (temporadas, películas, OVAs) del anime buscado,
    sacada de las relaciones de AniList, con lo que ya está en la lista marcado."""
    import franquicias as fq_mod
    from scrapers import anilist as anilist_mod
    q = (req.nombre or "").strip()
    if len(q) < 2 or main._detect_url(q):
        return {"ok": False, "entradas": []}
    ck = f"franquicia:{q.lower()}"
    resp = main._cache_get(ck)
    if not resp:
        loop = asyncio.get_running_loop()
        fuente = "anilist"
        try:
            entradas = await asyncio.wait_for(
                loop.run_in_executor(executor, anilist_mod.franquicia, q), timeout=25)
        except Exception:
            entradas = []
        if not entradas:
            # AniList caído o sin resultados (en oct. 2026 su API estuvo cortada
            # días): las relaciones de Kitsu dan lo mismo.
            from scrapers import kitsu as kitsu_mod
            fuente = "kitsu"
            try:
                entradas = await asyncio.wait_for(
                    loop.run_in_executor(executor, kitsu_mod.franquicia, q), timeout=25)
            except Exception:
                entradas = []
        if not entradas or not saga_casa_con(q, entradas):
            return {"ok": False, "entradas": []}
        raiz = next((e for e in entradas if e["raiz"]), entradas[0])
        series = [e for e in entradas if e["formato"] in ("TV", "TV_SHORT", "ONA")]
        nombre = fq_mod.nombre_comun([fq_mod._base_name(e["nombre"]) for e in (series or entradas)])
        resp = {"ok": True, "nombre": nombre or raiz["nombre"], "fuente": fuente,
                "entradas": entradas}
        main._cache_set(ck, resp)
    # "En tu lista" se calcula siempre (la caché no debe quedarse vieja).
    animes = db.listar_animes_slim()
    ids = {int(a.get("anilist_id") or 0) for a in animes}
    claves = {db.clave_nombre(a.get("nombre", "")) for a in animes}
    def _ya(e):
        if e.get("anilist_id") and e["anilist_id"] in ids:
            return True
        return any(db.clave_nombre(t) in claves for t in [e["nombre"], *(e.get("titulos") or [])])
    entradas = [dict(e, en_lista=_ya(e)) for e in resp["entradas"]]
    return dict(resp, entradas=entradas, resumen=resumen_saga(entradas))
def saga_casa_con(q: str, entradas: list[dict]) -> bool:
    """¿La saga tiene algo que ver con lo buscado? Kitsu devuelve lo más popular
    aunque la búsqueda sea basura ("%%%<>" → Attack on Titan). Basta con que una
    palabra de la búsqueda (3+ letras) se parezca a una de algún título; se
    toleran erratas ("atack on titans")."""
    import difflib
    palabras = [w for w in re.findall(r"\w+", q.casefold()) if len(w) >= 3]
    if not palabras:
        return bool(re.search(r"\w", q))       # "K-On", "86": no hay con qué comparar
    titulos = set()
    for e in entradas:
        for t in [e.get("nombre", ""), *(e.get("titulos") or [])]:
            ws = re.findall(r"\w+", str(t).casefold())
            titulos.update(w for w in ws if len(w) >= 2)
            titulos.add("".join(w[0] for w in ws))      # siglas: "aot", "snk"
    return any(p in titulos or difflib.get_close_matches(p, titulos, n=1, cutoff=0.75)
               for p in palabras)
_FORMATOS_SERIE = ("TV", "TV_SHORT", "ONA")
_MIN_EPISODIO, _MIN_PELICULA = 24, 110


def resumen_saga(entradas: list[dict]) -> dict:
    """Cuántas temporadas, episodios y horas tiene una saga. Numera las
    temporadas (series por orden de estreno) en cada entrada: `temporada`."""
    def _eps(e):
        m = re.match(r"\s*(\d+)", str(e.get("capitulos") or ""))
        return int(m.group(1)) if m else 0

    temporadas = peliculas = extras = episodios = minutos = 0
    incompleto = False
    for e in entradas:
        f = e.get("formato") or ""
        n = _eps(e)
        if f in _FORMATOS_SERIE:
            temporadas += 1
            e["temporada"] = temporadas
            episodios += n
            minutos += n * _MIN_EPISODIO
            # "?" o "12+" (en emisión): el total no es definitivo
            incompleto |= not n or "+" in str(e.get("capitulos"))
        elif f == "MOVIE":
            peliculas += 1
            minutos += _MIN_PELICULA
        else:
            extras += 1
            minutos += n * _MIN_EPISODIO
    tienes = sum(1 for e in entradas if e.get("en_lista"))
    return {"temporadas": temporadas, "episodios": episodios, "peliculas": peliculas,
            "extras": extras, "horas": round(minutos / 60), "incompleto": incompleto,
            "tienes": tienes, "faltan": len(entradas) - tienes}
@router.post("/api/buscar/multi")
async def buscar_multi(req: BuscarRequest):
    """v2.5: busca en TODAS las fuentes en paralelo y devuelve todos los
    resultados encontrados, para que el usuario elija. Si se pega una URL,
    resuelve directo (un solo resultado)."""
    loop = asyncio.get_running_loop()
    if main._detect_url(req.nombre):
        resultado, fuente_usada = await main._resolver_desde_url(req.nombre)
        if resultado:
            return {"ok": True, "resultados": [{"fuente": fuente_usada, "data": resultado.__dict__}]}
        return {"ok": False, "mensaje": "No se pudo resolver la URL"}

    ck = f"multi:{req.nombre.lower().strip()}"
    cached = main._cache_get(ck)
    if cached:
        return cached

    async def _una(f: str):
        try:
            r = await loop.run_in_executor(executor, main.SCRAPERS[f].buscar, req.nombre)
            return (f, r)
        except Exception:
            return (f, None)

    pares = await asyncio.gather(*[_una(f) for f in main.SCRAPERS])
    resultados = [{"fuente": f, "data": r.__dict__} for f, r in pares if r]
    if not resultados:
        return {"ok": False, "mensaje": "No encontrado en ninguna fuente"}
    resp = {"ok": True, "resultados": resultados}
    main._cache_set(ck, resp)
    return resp
@router.post("/api/buscar")
async def buscar_anime(req: BuscarRequest):
    """Busca sin guardar. Usa caché 5 min para no repetir llamadas externas.

    v2.1: si se pega una URL de AniList/MAL/Kitsu/etc., resuelve directo por
    ID/slug — ni búsqueda fuzzy ni fallback en otras fuentes.
    """
    # Atajo por URL
    url_info = main._detect_url(req.nombre)
    if url_info:
        ck = f"url:{req.nombre.strip().lower()}"
        cached = main._cache_get(ck)
        if cached:
            return cached
        resultado, fuente_usada = await main._resolver_desde_url(req.nombre)
        if not resultado:
            return {"ok": False, "mensaje": f"No se pudo resolver la URL ({url_info[0]})"}
        resp = {"ok": True, "data": resultado.__dict__, "fuente_usada": fuente_usada, "via": "url"}
        main._cache_set(ck, resp)
        return resp

    ck = f"{req.fuente}:{req.nombre.lower().strip()}"
    cached = main._cache_get(ck)
    if cached:
        return cached
    resultado, fuente_usada = await main._buscar_con_fallback(req.nombre, req.fuente)
    if not resultado:
        return {"ok": False, "mensaje": "Anime no encontrado"}
    resp = {"ok": True, "data": resultado.__dict__, "fuente_usada": fuente_usada}
    main._cache_set(ck, resp)
    return resp
@router.post("/api/animes")
async def guardar_anime(req: BuscarRequest):
    """Busca y guarda directamente. Acepta URL o nombre."""
    loop = asyncio.get_running_loop()
    # v2.1: si es URL, resolver directo
    if main._detect_url(req.nombre):
        resultado, fuente_usada = await main._resolver_desde_url(req.nombre)
    else:
        resultado, fuente_usada = await main._buscar_con_fallback(req.nombre, req.fuente)
    if not resultado:
        raise HTTPException(404, "Anime no encontrado")

    data = resultado.__dict__.copy()
    # Completar con AniList si falta imagen/episodios, si la portada viene de un
    # host poco fiable (anime-planet/animeflv) o si no hay anilist_id (lo
    # necesitan las notificaciones y el enriquecimiento por lotes).
    need_eps, need_img = main._enrich_needs(data)
    needs_enrichment = need_eps or need_img or not data.get("anilist_id")
    if needs_enrichment and fuente_usada != "anilist" and "anilist" in main.SCRAPERS:
        try:
            alt = await asyncio.wait_for(
                loop.run_in_executor(executor, main.SCRAPERS["anilist"].buscar, data.get("nombre", req.nombre)),
                timeout=10,
            )
            if alt:
                data.update(main._enrich_cambios(data, alt, need_eps, need_img))
        except Exception:
            pass
    elif not data.get("imagen"):
        fallback_img = await loop.run_in_executor(executor, main._find_anime_image, req.nombre)
        if fallback_img:
            data["imagen"] = fallback_img

    if not (data.get("nombre") or "").strip():
        raise HTTPException(400, "El anime no tiene nombre válido")
    if req.grupo and req.grupo.strip():
        data["grupo"] = req.grupo.strip()
    ok, msg = db.guardar_anime(data)
    if not ok:
        raise HTTPException(409 if msg == "duplicado" else 500, msg)

    # Sync automático a Sheets en background
    cfg = main._get_sheets_config()
    if cfg:
        anime_dict = db.obtener_anime(data.get("nombre",""))
        if anime_dict:
            main._sync_bg(sheets_sync.append_anime, anime_dict, cfg[0], cfg[1])

    saved = db.obtener_anime(data.get("nombre","")) or data
    saved["fuente_usada"] = fuente_usada
    return {"ok": True, "data": saved}
# ── Manga ────────────────────────────────────────────────────────────────────

@router.post("/api/buscar/manga")
async def buscar_manga(req: BuscarRequest):
    """Busca manga en AniList."""
    ck = f"manga:{req.nombre.lower().strip()}"
    cached = main._cache_get(ck)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    anilist = main.SCRAPERS.get("anilist")
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
    main._cache_set(ck, resp)
    return resp


@router.post("/api/buscar/manga/multi")
async def buscar_manga_multi(req: BuscarRequest):
    """Busca manga en AniList — múltiples resultados."""
    ck = f"manga_multi:{req.nombre.lower().strip()}"
    cached = main._cache_get(ck)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    anilist = main.SCRAPERS.get("anilist")
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
    main._cache_set(ck, resp)
    return resp


@router.post("/api/manga")
async def guardar_manga(req: BuscarRequest):
    """Busca manga en AniList y lo guarda."""
    loop = asyncio.get_running_loop()
    anilist = main.SCRAPERS.get("anilist")
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
