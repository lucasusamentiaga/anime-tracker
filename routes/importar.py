"""
routes/importar.py — Import / Export: detección de texto pegado, importación en lote,
XML de MyAnimeList, importación de AniList por usuario y exportación
JSON/CSV.

Extraído de main.py. OJO: SCRAPERS/_sync_bg/
_get_sheets_config/_import_from_anilist viven en main (los tests los
parchean ahí) → se acceden via `main.X`.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import xml.etree.ElementTree as ET

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

import database as db
import main  # circular a propósito: nombres de main se leen al servir
import sheets_sync
from core import VERSION, executor
from main import ImportRequest  # noqa: E402  (modelo en main)

router = APIRouter()

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
@router.post("/api/import/detect")
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

@router.post("/api/import/bulk")
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
    cfg = main._get_sheets_config()

    for nombre in nombres:
        # Buscar en fuentes
        prioridad = [req.fuente_preferida] + [f for f in main.SCRAPERS if f != req.fuente_preferida]
        resultado = None
        for fuente in prioridad:
            scraper = main.SCRAPERS.get(fuente)
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
                    main._sync_bg(sheets_sync.append_anime, anime_dict, cfg[0], cfg[1])
        else:
            resultados["no_encontrados"].append(nombre)

    return resultados
# ── Importar desde MAL XML ────────────────────────────────────────────────────

@router.post("/api/import/mal-xml")
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
    cfg = main._get_sheets_config()

    for data in animes_raw[:200]:  # máx 200
        # Buscar info completa en AniList
        scraper = main.SCRAPERS.get("anilist")
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
                    main._sync_bg(sheets_sync.append_anime, ad, cfg[0], cfg[1])
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
# ── Importar desde AniList por username ───────────────────────────────────────

@router.post("/api/import/anilist")
async def import_anilist(data: dict):
    username = (data.get("username") or "").strip()
    if not username:
        raise HTTPException(400, "Username requerido")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, main._import_from_anilist, username)
# ── Exportar JSON completo ────────────────────────────────────────────────────

@router.get("/api/export/json")
async def export_json():
    """Exporta toda la lista como JSON para backup o migración."""
    animes = db.listar_animes()
    content = json.dumps({"version": VERSION, "animes": animes}, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=anime_tracker.json"},
    )
# ── Exportar CSV ──────────────────────────────────────────────────────────────

@router.get("/api/export/csv")
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

@router.get("/api/media/export/json")
async def export_media_json():
    """v2.6: exporta la colección de pelis/series como JSON."""
    return JSONResponse(
        content={"media": db.listar_media()},
        headers={"Content-Disposition": "attachment; filename=peliculas_series.json"},
    )

@router.get("/api/media/export/csv")
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
