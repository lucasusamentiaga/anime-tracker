from __future__ import annotations

import re
import unicodedata
from typing import Optional

from . import net
from .base import AnimeData, BaseScraper

# Session reutilizable para connection pooling (clave en importación masiva)
_session = net.make_session()   # con reintentos + backoff (ver scrapers/net.py)


ANILIST_API = "https://graphql.anilist.co"

# AniList limita a 30 req/min (cabecera X-RateLimit-Limit, 2026). Los bucles
# masivos (sync, enriquecimiento) deben esperar al menos esto entre peticiones.
ANILIST_MIN_INTERVAL = 2.1

_RE_PAREN = re.compile(r"\s*\((?:TV|\d{4})\)\s*", re.I)
_RE_MOVIE = re.compile(r"\s*\b(?:the\s+)?movie(?:\s*\d+)?\s*:?\s*", re.I)


def candidatos_busqueda(nombre: str) -> list[str]:
    """Variantes de un título para reintentar en AniList cuando la búsqueda
    literal no encuentra nada. Pensado para nombres heredados de AnimeFLV:
    "Black Clover (TV)" → "Black Clover"; "Baki (2018)" → "Baki";
    "Haikyuu!! Movie: Gomisuteba no Kessen" → "Haikyuu!! Gomisuteba no Kessen".
    El primer elemento es siempre el original. Sin duplicados."""
    base = (nombre or "").strip()
    out = [base]
    # NFKC: "Date A Live Ⅲ" → "Date A Live III" (AniList no casa el numeral Unicode)
    nfkc = unicodedata.normalize("NFKC", base)
    sin_paren = _RE_PAREN.sub(" ", nfkc).strip()
    sin_movie = re.sub(r"\s{2,}", " ", _RE_MOVIE.sub(" ", sin_paren)).strip(" :-")
    for c in (nfkc, sin_paren, sin_movie):
        if c and c not in out:
            out.append(c)
    return out

QUERY = """
query ($search: String, $type: MediaType!) {
  Media(search: $search, type: $type) {
    id
    title { romaji english native }
    episodes
    chapters
    volumes
    format
    coverImage { large }
    genres
    description(asHtml: false)
    status
    nextAiringEpisode { episode }
  }
}
"""

# Lookup por lotes de IDs (máx. 50 por página en AniList). Una sola petición
# sustituye a N búsquedas por nombre y evita coincidencias erróneas de título.
QUERY_IDS = """
query ($ids: [Int], $type: MediaType!) {
  Page(perPage: 50) {
    media(id_in: $ids, type: $type) {
      id
      title { romaji english native }
      episodes
      chapters
      volumes
      format
      coverImage { large }
      genres
      description(asHtml: false)
      status
      nextAiringEpisode { episode }
    }
  }
}
"""

QUERY_MAL = """
query ($mal: Int, $type: MediaType!) {
  Media(idMal: $mal, type: $type) {
    id
    title { romaji english native }
    episodes
    chapters
    volumes
    format
    coverImage { large }
    genres
    description(asHtml: false)
    status
    nextAiringEpisode { episode }
  }
}
"""

_STATUS_MAP = {
    "FINISHED": "Finalizado",
    "RELEASING": "En emisión",
    "NOT_YET_RELEASED": "Sin estrenar",
    "CANCELLED": "Cancelado",
    "HIATUS": "En pausa",
}


def _parse_media(media: dict, nombre: str, fuente: str,
                 media_type: str = "ANIME") -> Optional[AnimeData]:
    """Convierte un resultado de AniList en AnimeData (anime o manga)."""
    title = (
        media["title"].get("english")
        or media["title"].get("romaji")
        or nombre
    )
    fmt = (media.get("format") or "").upper()
    is_manga = media_type == "MANGA"

    if is_manga:
        chapters = media.get("chapters") or 0
        capitulos: int | str = chapters if chapters > 0 else "?"
    else:
        episodes = media.get("episodes") or 0
        if fmt == "MOVIE":
            capitulos = "película"
        elif episodes > 0:
            capitulos = episodes
        else:
            # Para anime en emisión, usar nextAiringEpisode para saber
            # cuántos episodios han salido hasta ahora
            nae = media.get("nextAiringEpisode") or {}
            next_ep = nae.get("episode") or 0
            capitulos = f"{next_ep - 1}+" if next_ep > 1 else "?"

    return AnimeData(
        nombre=title,
        capitulos=capitulos,
        imagen=media["coverImage"].get("large", ""),
        genero=media.get("genres", []),
        sinopsis=(media.get("description") or "")[:500],
        fuente=fuente,
        estado_anime=_STATUS_MAP.get(media.get("status", ""), "Desconocido"),
        anilist_id=media.get("id", 0),
        tipo="manga" if is_manga else "anime",
        volumenes_totales=media.get("volumes") or 0,
    )


class AniListScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "anilist"

    def buscar(self, nombre: str, media_type: str = "ANIME") -> Optional[AnimeData]:
        """Busca por título; si AniList no encuentra el literal, reintenta con
        las variantes de `candidatos_busqueda` (máx. 2 peticiones extra)."""
        for cand in candidatos_busqueda(nombre):
            r = self._buscar_literal(cand, media_type)
            if r is not None:
                return r
        return None

    def _buscar_literal(self, nombre: str, media_type: str) -> Optional[AnimeData]:
        try:
            resp = _session.post(
                ANILIST_API,
                json={"query": QUERY, "variables": {"search": nombre, "type": media_type}},
                headers={"User-Agent": "AnimeTracker/2.9.0", "Accept": "application/json",
                         "Accept-Encoding": "identity"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            media = data.get("data", {}).get("Media")
            if not media:
                return None

            return _parse_media(media, nombre, self.nombre_fuente, media_type)
        except Exception:
            return None

    def buscar_manga(self, nombre: str) -> Optional[AnimeData]:
        """Búsqueda específica de manga en AniList."""
        return self.buscar(nombre, media_type="MANGA")

    def buscar_por_ids(self, ids: list[int],
                       media_type: str = "ANIME") -> dict[int, AnimeData]:
        """Lookup de hasta 50 IDs de AniList en una sola petición.

        Devuelve {anilist_id: AnimeData}. IDs no encontrados se omiten.
        Nunca lanza: ante error devuelve {}."""
        ids = [int(i) for i in ids if i][:50]
        if not ids:
            return {}
        try:
            resp = _session.post(
                ANILIST_API,
                json={"query": QUERY_IDS,
                      "variables": {"ids": ids, "type": media_type}},
                headers={"User-Agent": "AnimeTracker/2.9.0", "Accept": "application/json",
                         "Accept-Encoding": "identity"},
                timeout=15,
            )
            resp.raise_for_status()
            medias = (((resp.json() or {}).get("data") or {})
                      .get("Page") or {}).get("media") or []
            out: dict[int, AnimeData] = {}
            for m in medias:
                if not m or not m.get("id"):
                    continue
                r = _parse_media(m, "", self.nombre_fuente, media_type)
                if r:
                    out[int(m["id"])] = r
            return out
        except Exception:
            return {}

    def buscar_por_mal(self, mal_id: int,
                       media_type: str = "ANIME") -> Optional[AnimeData]:
        """Lookup exacto en AniList a partir de un ID de MyAnimeList."""
        if not mal_id:
            return None
        try:
            resp = _session.post(
                ANILIST_API,
                json={"query": QUERY_MAL,
                      "variables": {"mal": int(mal_id), "type": media_type}},
                headers={"User-Agent": "AnimeTracker/2.9.0", "Accept": "application/json",
                         "Accept-Encoding": "identity"},
                timeout=10,
            )
            resp.raise_for_status()
            media = ((resp.json() or {}).get("data") or {}).get("Media")
            return _parse_media(media, "", self.nombre_fuente, media_type) if media else None
        except Exception:
            return None


# ── Franquicias (v2.13) ──────────────────────────────────────────────────────
# Relaciones que cuentan como "la misma saga". SPIN_OFF, ALTERNATIVE (remakes),
# SUMMARY (resúmenes) y CHARACTER se quedan fuera: suelen ser otra cosa.
RELACIONES_SAGA = {"SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY"}
FORMATOS_SAGA = {"TV", "TV_SHORT", "ONA", "MOVIE", "OVA", "SPECIAL"}
_MAX_FRANQUICIA = 60

_CAMPOS_FRANQUICIA = """
      id
      title { romaji english native }
      episodes
      format
      type
      coverImage { large }
      genres
      status
      startDate { year month day }
      nextAiringEpisode { episode }
      relations { edges { relationType node { id type } } }
"""

QUERY_FRANQUICIA_BUSCAR = """
query ($search: String) {
  Page(perPage: 30) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {CAMPOS}
  }
}
""".replace("{CAMPOS}", "{" + _CAMPOS_FRANQUICIA + "}")

QUERY_FRANQUICIA_IDS = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids, type: ANIME) {CAMPOS}
  }
}
""".replace("{CAMPOS}", "{" + _CAMPOS_FRANQUICIA + "}")

QUERY_RELACIONES = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids, type: ANIME) {
      id
      relations { edges { relationType node { id type } } }
    }
  }
}
"""


def relacionados_saga(media: dict) -> list[int]:
    """IDs de anime relacionados con `media` como parte de la misma saga."""
    out = []
    for e in ((media.get("relations") or {}).get("edges") or []):
        node = e.get("node") or {}
        if e.get("relationType") in RELACIONES_SAGA and node.get("type") == "ANIME" and node.get("id"):
            out.append(int(node["id"]))
    return out


def _post(query: str, variables: dict, timeout: int = 15) -> dict:
    resp = _session.post(
        ANILIST_API,
        json={"query": query, "variables": variables},
        headers={"User-Agent": "AnimeTracker/2.13", "Accept": "application/json",
                 "Accept-Encoding": "identity"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return (resp.json() or {}).get("data") or {}


def franquicia(nombre: str, post=_post, max_saltos: int = 2) -> list[dict]:
    """Todas las entradas de la saga del anime que mejor casa con `nombre`.

    Una búsqueda (30 resultados con sus relaciones) suele traer ya toda la saga;
    lo que falte se pide por IDs (máx. `max_saltos` peticiones más). Devuelve
    dicts {anilist_id, nombre, formato, capitulos, estado_anime, imagen, genero,
    anio, mes, dia, raiz} ordenados por fecha de estreno; [] si no hay nada.
    Nunca lanza."""
    try:
        medias = ((post(QUERY_FRANQUICIA_BUSCAR, {"search": nombre}).get("Page") or {})
                  .get("media") or [])
    except Exception:
        return []
    medias = [m for m in medias if m and m.get("id")]
    if not medias:
        return []
    por_id = {int(m["id"]): m for m in medias}
    raiz = int(medias[0]["id"])

    visto = {raiz}
    frontera = [raiz]
    saltos = 0
    while frontera and len(visto) < _MAX_FRANQUICIA:
        faltan = []
        siguiente = []
        for i in frontera:
            m = por_id.get(i)
            if m is None:
                faltan.append(i)
                continue
            for j in relacionados_saga(m):
                if j not in visto and len(visto) < _MAX_FRANQUICIA:
                    visto.add(j)
                    siguiente.append(j)
        if faltan:
            if saltos >= max_saltos:
                break
            saltos += 1
            try:
                nuevos = ((post(QUERY_FRANQUICIA_IDS, {"ids": faltan[:50]}).get("Page") or {})
                          .get("media") or [])
            except Exception:
                nuevos = []
            for m in nuevos:
                if m and m.get("id"):
                    por_id[int(m["id"])] = m
            # Los que acaban de llegar se exploran en la siguiente vuelta.
            siguiente = [i for i in faltan if i in por_id] + siguiente
        frontera = siguiente

    out = []
    for i in visto:
        m = por_id.get(i)
        if not m or (m.get("format") or "") not in FORMATOS_SAGA:
            continue
        d = _parse_media(m, "", "anilist")
        if not d:
            continue
        sd = m.get("startDate") or {}
        out.append({
            "anilist_id": i,
            "nombre": d.nombre,
            "formato": m.get("format") or "",
            "capitulos": d.capitulos,
            "estado_anime": d.estado_anime,
            "imagen": d.imagen,
            "genero": d.genero,
            "anio": sd.get("year") or 0,
            "mes": sd.get("month") or 0,
            "dia": sd.get("day") or 0,
            "raiz": i == raiz,
            "url": f"https://anilist.co/anime/{i}",
            "titulos": [t for t in (m.get("title") or {}).values() if t],
        })
    out.sort(key=lambda e: (e["anio"] or 9999, e["mes"] or 99, e["dia"] or 99, e["anilist_id"]))
    return out


def relaciones_por_ids(ids: list[int], post=_post) -> dict[int, list[int]]:
    """{id: [ids de la misma saga]} para hasta 50 animes. {} si falla."""
    ids = [int(i) for i in ids if i][:50]
    if not ids:
        return {}
    try:
        medias = ((post(QUERY_RELACIONES, {"ids": ids}).get("Page") or {})
                  .get("media") or [])
    except Exception:
        return {}
    return {int(m["id"]): relacionados_saga(m) for m in medias if m and m.get("id")}
