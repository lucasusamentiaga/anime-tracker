"""
TMDB scraper — busca películas y series (no-anime) en The Movie Database (API v3).

Requiere una API key gratuita de https://www.themoviedb.org/settings/api
La clave se guarda en la tabla config (key='tmdb_api_key') y se pasa a cada llamada.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import net

BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w500"

# Session reutilizable: pooling + reintentos con backoff
_session = net.make_session()

# Mapas de género estáticos de TMDB (rara vez cambian) — para resultados de búsqueda
# que solo traen genre_ids. Al pedir detalle, TMDB devuelve los nombres directamente.
_GENRES_MOVIE = {
    28: "Acción", 12: "Aventura", 16: "Animación", 35: "Comedia", 80: "Crimen",
    99: "Documental", 18: "Drama", 10751: "Familia", 14: "Fantasía", 36: "Historia",
    27: "Terror", 10402: "Música", 9648: "Misterio", 10749: "Romance",
    878: "Ciencia ficción", 10770: "Película de TV", 53: "Suspense", 10752: "Bélica",
    37: "Western",
}
_GENRES_TV = {
    10759: "Acción y Aventura", 16: "Animación", 35: "Comedia", 80: "Crimen",
    99: "Documental", 18: "Drama", 10751: "Familia", 10762: "Infantil",
    9648: "Misterio", 10763: "Noticias", 10764: "Reality", 10765: "Sci-Fi y Fantasía",
    10766: "Telenovela", 10767: "Talk show", 10768: "Guerra y Política", 37: "Western",
}


@dataclass
class MediaData:
    titulo: str
    tipo: str = "pelicula"          # 'pelicula' | 'serie'
    tmdb_id: int = 0
    imagen: str = ""
    sinopsis: str = ""
    genero: list = field(default_factory=list)
    anio: str = ""
    duracion: int = 0               # minutos (película) o nº episodios totales (serie)
    temporadas: int = 0
    estado_media: str = ""
    puntuacion_tmdb: float = 0.0


def _img(path: Optional[str]) -> str:
    return (IMG_BASE + path) if path else ""


def validar_key(api_key: str) -> bool:
    """Comprueba si una API key (v3) es válida llamando a /authentication.
    Devuelve True solo si TMDB responde 200 con success=true."""
    if not api_key or not api_key.strip():
        return False
    try:
        resp = _session.get(
            f"{BASE}/authentication",
            params={"api_key": api_key.strip()},
            timeout=10,
        )
        return resp.status_code == 200 and bool(resp.json().get("success"))
    except Exception:
        return False


def buscar(query: str, api_key: str, limit: int = 20, lang: str = "es-ES") -> list[MediaData]:
    """Busca películas y series a la vez (TMDB /search/multi).

    Devuelve una lista de MediaData (vacía si no hay clave, error de red, o
    sin resultados). Ignora resultados de tipo 'person'.
    """
    if not api_key or not query.strip():
        return []
    try:
        resp = _session.get(
            f"{BASE}/search/multi",
            params={
                "api_key": api_key,
                "query": query.strip(),
                "language": lang,
                "include_adult": "false",
                "page": 1,
            },
            timeout=12,
        )
        resp.raise_for_status()
    except Exception:
        return []

    out: list[MediaData] = []
    for item in resp.json().get("results", []):
        mt = item.get("media_type")
        if mt == "movie":
            out.append(MediaData(
                titulo=item.get("title", "") or item.get("original_title", ""),
                tipo="pelicula",
                tmdb_id=item.get("id", 0),
                imagen=_img(item.get("poster_path")),
                sinopsis=item.get("overview", ""),
                genero=[_GENRES_MOVIE[g] for g in item.get("genre_ids", []) if g in _GENRES_MOVIE],
                anio=(item.get("release_date") or "")[:4],
                puntuacion_tmdb=round(float(item.get("vote_average") or 0), 1),
            ))
        elif mt == "tv":
            out.append(MediaData(
                titulo=item.get("name", "") or item.get("original_name", ""),
                tipo="serie",
                tmdb_id=item.get("id", 0),
                imagen=_img(item.get("poster_path")),
                sinopsis=item.get("overview", ""),
                genero=[_GENRES_TV[g] for g in item.get("genre_ids", []) if g in _GENRES_TV],
                anio=(item.get("first_air_date") or "")[:4],
                puntuacion_tmdb=round(float(item.get("vote_average") or 0), 1),
            ))
        # 'person' u otros → ignorar
        if len(out) >= limit:
            break
    return out


def detalle(tmdb_id: int, tipo: str, api_key: str, lang: str = "es-ES") -> Optional[MediaData]:
    """Detalle completo de una película o serie: duración/episodios,
    géneros nombrados, estado. Devuelve None si falla."""
    if not api_key:
        return None
    endpoint = "movie" if tipo == "pelicula" else "tv"
    try:
        resp = _session.get(
            f"{BASE}/{endpoint}/{int(tmdb_id)}",
            params={"api_key": api_key, "language": lang},
            timeout=12,
        )
        resp.raise_for_status()
        d = resp.json()
    except Exception:
        return None

    if tipo == "pelicula":
        return MediaData(
            titulo=d.get("title", "") or d.get("original_title", ""),
            tipo="pelicula",
            tmdb_id=int(tmdb_id),
            imagen=_img(d.get("poster_path")),
            sinopsis=d.get("overview", ""),
            genero=[g["name"] for g in d.get("genres", [])],
            anio=(d.get("release_date") or "")[:4],
            duracion=int(d.get("runtime") or 0),
            estado_media=d.get("status", ""),
            puntuacion_tmdb=round(float(d.get("vote_average") or 0), 1),
        )
    return MediaData(
        titulo=d.get("name", "") or d.get("original_name", ""),
        tipo="serie",
        tmdb_id=int(tmdb_id),
        imagen=_img(d.get("poster_path")),
        sinopsis=d.get("overview", ""),
        genero=[g["name"] for g in d.get("genres", [])],
        anio=(d.get("first_air_date") or "")[:4],
        duracion=int(d.get("number_of_episodes") or 0),
        temporadas=int(d.get("number_of_seasons") or 0),
        estado_media=d.get("status", ""),
        puntuacion_tmdb=round(float(d.get("vote_average") or 0), 1),
    )


def tendencias(api_key: str, lang: str = "es-ES", limit: int = 20) -> list[MediaData]:
    """Películas y series en tendencia esta semana (TMDB /trending/all/week).
    Para descubrimiento: qué ver ahora. Ignora 'person'."""
    if not api_key:
        return []
    try:
        resp = _session.get(
            f"{BASE}/trending/all/week",
            params={"api_key": api_key, "language": lang},
            timeout=12,
        )
        resp.raise_for_status()
    except Exception:
        return []
    out: list[MediaData] = []
    for item in resp.json().get("results", []):
        mt = item.get("media_type")
        if mt == "movie":
            out.append(MediaData(
                titulo=item.get("title", "") or item.get("original_title", ""),
                tipo="pelicula", tmdb_id=item.get("id", 0),
                imagen=_img(item.get("poster_path")), sinopsis=item.get("overview", ""),
                genero=[_GENRES_MOVIE[g] for g in item.get("genre_ids", []) if g in _GENRES_MOVIE],
                anio=(item.get("release_date") or "")[:4],
                puntuacion_tmdb=round(float(item.get("vote_average") or 0), 1),
            ))
        elif mt == "tv":
            out.append(MediaData(
                titulo=item.get("name", "") or item.get("original_name", ""),
                tipo="serie", tmdb_id=item.get("id", 0),
                imagen=_img(item.get("poster_path")), sinopsis=item.get("overview", ""),
                genero=[_GENRES_TV[g] for g in item.get("genre_ids", []) if g in _GENRES_TV],
                anio=(item.get("first_air_date") or "")[:4],
                puntuacion_tmdb=round(float(item.get("vote_average") or 0), 1),
            ))
        if len(out) >= limit:
            break
    return out
