"""
routes/estadisticas.py — Estadísticas y descubrimiento: /api/stats, qué-veo, aleatorio,
heatmap/streak/completion/continuar, wrapped, timeline, novedades,
recomendaciones y calendario.

Extraído de main.py. Las llamadas a AniList van via `main._anilist` /
`main._anilist_con_error` (viven en main y los tests las parchean ahí).
"""

from __future__ import annotations

import asyncio
import datetime
import logging as _logging
import random
import re
import time as _time
from collections import Counter
from typing import Optional

from fastapi import APIRouter

import database as db
import main  # circular a propósito: nombres de main se leen al servir
from core import executor

router = APIRouter()

# Mismo objeto que main._sync_log (getLogger devuelve el singleton del nombre)
_sync_log = _logging.getLogger("anime_tracker")

@router.get("/api/animes/random")
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

@router.get("/api/que-veo")
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
# ── Estadísticas ──────────────────────────────────────────────────────────────

@router.get("/api/stats")
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
# ── Novedades — animes recientes de plataformas ───────────────────────────────

_novedades_cache: dict = {}
_NOVEDADES_TTL = 3600  # 1 hora

@router.get("/api/novedades")
async def get_novedades(plataforma: str = "all"):
    """Novedades y estrenos de Netflix, Crunchyroll, etc. via AniList."""
    cache_key = f"novedades:{plataforma}"
    cached = main._cache_get(cache_key)
    if cached:
        return cached

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _fetch_novedades, plataforma)
    main._cache_set(cache_key, result)
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
        data, fallo = main._anilist_con_error(query, {"page": 1, "perPage": 50}, timeout=15)
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
# ── ep_log endpoints (v2.2) ───────────────────────────────────────────────────

@router.get("/api/heatmap")
async def heatmap(dias: int = 365):
    """Heatmap estilo GitHub contributions. Devuelve solo días con actividad —
    el frontend rellena los huecos."""
    dias = max(1, min(int(dias), 730))
    return {"dias": db.ep_log_heatmap(dias), "total": db.ep_log_total(dias), "rango": dias}


@router.get("/api/streak")
async def streak():
    """Racha actual y máxima en días con al menos 1 ep visto."""
    return db.ep_log_streak()


@router.get("/api/stats/completion")
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


@router.get("/api/continuar")
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
# ── Recomendaciones (AniList trending filtrado por géneros del usuario) ────────

@router.get("/api/recomendaciones")
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
        data, fallo = main._anilist_con_error(query, {"genres": top_genres}, timeout=15)
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
        data = main._anilist(query, {"ids": ids}, timeout=15)
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
    guardado = main._cache_get(clave)
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
        for (anime_id, _t), relleno in zip(faltan, rellenos, strict=True):
            if isinstance(relleno, dict) and relleno.get("imagen"):
                datos.setdefault(anime_id, {}).update(relleno)
                recuperadas += 1
        if recuperadas:
            aviso = ("AniList no está disponible, así que algunas portadas "
                     "vienen de Kitsu.")

    # Solo se cachea si se consiguió algo: guardar un resultado vacío dejaría la
    # pantalla sin portadas durante 12 h por un corte de red de un segundo.
    if any(f.get("imagen") for f in datos.values()):
        main._cache_set(clave, (datos, aviso), ttl=_TTL_FICHAS_GATEWAY)
    return datos, aviso


@router.get("/api/recomendaciones/principiante")
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
    base = gateway_anime.recomendar_principiante(
        top_genres,
        excluir_ids=[a.get("anilist_id") for a in animes],
        excluir_claves={db.clave_nombre(a.get("nombre") or "") for a in animes},
        clave=db.clave_nombre,
    )

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

@router.get("/api/calendario")
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

        data = main._anilist(query, variables, timeout=20)
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
# ── Historial timeline ────────────────────────────────────────────────────────

@router.get("/api/historial/timeline")
async def historial_timeline():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM historial ORDER BY fecha DESC LIMIT 200").fetchall()
    return {"eventos": [dict(r) for r in rows], "total": len(rows)}
# ── Wrapped — resumen anual del usuario ──────────────────────────────────────

@router.get("/api/stats/wrapped")
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
