"""Kitsu scraper — API pública JSON de kitsu.io (sin auth requerida)."""
from __future__ import annotations

from typing import Optional

from . import adulto, net
from .base import AnimeData, BaseScraper

# Session reutilizable: pooling + reintentos con backoff
_session = net.make_session()

BASE = "https://kitsu.io/api/edge"
HEADERS = {"User-Agent": "AnimeTracker/2.6.2", "Accept": "application/vnd.api+json",
           "Accept-Encoding": "identity"}

STATUS_MAP = {
    "finished":    "Finalizado",
    "current":     "En emisión",
    "upcoming":    "Próximamente",
    "tba":         "Por confirmar",
    "unreleased":  "Sin publicar",
}


def _a_animedata(item: dict, nombre: str = "") -> Optional[AnimeData]:
    """Un recurso `anime` de Kitsu (JSON:API) → AnimeData."""
    a = (item or {}).get("attributes") or {}
    if not a or adulto.es_adulto(item):
        return None
    titulo = (
        a.get("canonicalTitle")
        or (a.get("titles") or {}).get("en")
        or (a.get("titles") or {}).get("en_jp")
        or nombre
    )
    poster = a.get("posterImage") or {}
    n_ep = a.get("episodeCount") or 0
    subtype = (a.get("subtype") or "").lower()
    if subtype == "movie":
        caps: int | str = "película"
    elif n_ep:
        caps = int(n_ep)
    else:
        caps = "?"
    return AnimeData(
        nombre=titulo, capitulos=caps,
        imagen=poster.get("large") or poster.get("medium") or "",
        genero=[], sinopsis=(a.get("synopsis") or "")[:500],
        fuente="kitsu", estado_anime=STATUS_MAP.get(a.get("status", ""), "Desconocido"),
    )


class KitsuScraper(BaseScraper):

    @property
    def nombre_fuente(self) -> str:
        return "kitsu"

    def buscar_por_slug(self, slug: str) -> Optional[AnimeData]:
        """Lookup exacto por slug (añadir pegando una URL de Kitsu). Antes se
        buscaba el slug como texto y podía entrar otra temporada."""
        try:
            resp = _session.get(
                f"{BASE}/anime",
                params={"filter[slug]": slug, "fields[anime]": (
                    "canonicalTitle,titles,synopsis,episodeCount,posterImage,status,subtype,nsfw,ageRating")},
                headers=HEADERS, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("data", [])
            return _a_animedata(items[0], slug) if items else None
        except Exception:
            return None

    def buscar(self, nombre: str) -> Optional[AnimeData]:
        try:
            resp = _session.get(
                f"{BASE}/anime",
                params={
                    "filter[text]": nombre,
                    "page[limit]": 5,
                    "fields[anime]": (
                        "canonicalTitle,titles,synopsis,"
                        "episodeCount,posterImage,status,subtype,nsfw,ageRating"
                    ),
                },
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            # v2.14.1: nunca contenido para adultos (nsfw / R18).
            items = adulto.filtrar(resp.json().get("data", []))
            if not items:
                return None

            a = items[0]["attributes"]
            titulo = (
                a.get("canonicalTitle")
                or (a.get("titles") or {}).get("en")
                or (a.get("titles") or {}).get("en_jp")
                or nombre
            )
            poster = a.get("posterImage") or {}
            imagen = poster.get("large") or poster.get("medium") or ""
            sinopsis = (a.get("synopsis") or "")[:500]

            n_ep = a.get("episodeCount") or 0
            subtype = (a.get("subtype") or "").lower()
            if subtype == "movie":
                caps: int | str = "película"
            elif n_ep:
                caps = int(n_ep)
            else:
                caps = "?"

            estado = STATUS_MAP.get(a.get("status", ""), "Desconocido")

            return AnimeData(
                nombre=titulo, capitulos=caps, imagen=imagen,
                genero=[], sinopsis=sinopsis,
                fuente=self.nombre_fuente, estado_anime=estado,
            )
        except Exception:
            return None


# ── Franquicias (v2.13): respaldo cuando AniList no responde ─────────────────
# Mismo resultado que scrapers.anilist.franquicia, sacado de las relaciones de
# Kitsu (una búsqueda con las relaciones incluidas + lo que falte por ids).
ROLES_SAGA = {"sequel", "prequel", "side_story", "parent_story", "full_story"}
_FORMATOS = {"TV": "TV", "ONA": "ONA", "OVA": "OVA", "MOVIE": "MOVIE", "SPECIAL": "SPECIAL"}
_CAMPOS = ("canonicalTitle,titles,subtype,episodeCount,startDate,slug,posterImage,"
           "status,nsfw,ageRating,mediaRelationships")


def _get(params: dict) -> dict:
    resp = _session.get(f"{BASE}/anime", params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json() or {}


def _relaciones(payload: dict) -> dict[str, list[str]]:
    """{id anime: [ids de anime de la misma saga]} a partir de `included`."""
    rels = {r["id"]: r for r in payload.get("included") or [] if r.get("type") == "mediaRelationships"}
    out: dict[str, list[str]] = {}
    for item in payload.get("data") or []:
        ids = []
        for ref in (((item.get("relationships") or {}).get("mediaRelationships") or {}).get("data") or []):
            r = rels.get(ref.get("id"))
            if not r or (r.get("attributes") or {}).get("role") not in ROLES_SAGA:
                continue
            dest = ((r.get("relationships") or {}).get("destination") or {}).get("data") or {}
            if dest.get("type") == "anime" and dest.get("id"):
                ids.append(str(dest["id"]))
        out[str(item.get("id"))] = ids
    return out


def franquicia(nombre: str, get=_get, max_saltos: int = 8, maximo: int = 60) -> list[dict]:
    """Saga del anime que mejor casa con `nombre`, según Kitsu. Nunca lanza."""
    comunes = {"include": "mediaRelationships.destination", "fields[anime]": _CAMPOS,
               "fields[mediaRelationships]": "role,destination"}
    try:
        p = get(dict(comunes, **{"filter[text]": nombre, "page[limit]": 20}))
    except Exception:
        return []
    datos = {str(i["id"]): i for i in p.get("data") or [] if i.get("id")}
    if not datos:
        return []
    rel = _relaciones(p)
    raiz = str((p.get("data") or [])[0]["id"])

    visto, frontera, saltos = {raiz}, [raiz], 0
    while frontera and len(visto) < maximo:
        faltan = [i for i in frontera if i not in rel]
        if faltan:
            if saltos >= max_saltos:
                frontera = [i for i in frontera if i in rel]
            else:
                saltos += 1
                try:
                    q = get(dict(comunes, **{"filter[id]": ",".join(faltan[:20]),
                                             "page[limit]": 20}))
                    datos.update({str(i["id"]): i for i in q.get("data") or [] if i.get("id")})
                    rel.update(_relaciones(q))
                except Exception:
                    pass
        siguiente = []
        for i in frontera:
            for j in rel.get(i, []):
                if j not in visto and len(visto) < maximo:
                    visto.add(j)
                    siguiente.append(j)
        frontera = siguiente

    out = []
    for i in visto:
        item = datos.get(i)
        if not item or adulto.es_adulto(item):
            continue
        a = item.get("attributes") or {}
        fmt = _FORMATOS.get((a.get("subtype") or "").upper())
        d = _a_animedata(item)
        if not fmt or not d:
            continue
        fecha = (a.get("startDate") or "")[:10].split("-") + ["", "", ""]
        num = [int(x) if x.isdigit() else 0 for x in fecha[:3]]
        out.append({
            "kitsu_id": i, "anilist_id": 0, "nombre": d.nombre, "formato": fmt,
            "capitulos": d.capitulos, "estado_anime": d.estado_anime, "imagen": d.imagen,
            "genero": [], "anio": num[0], "mes": num[1], "dia": num[2], "raiz": i == raiz,
            "url": f"https://kitsu.io/anime/{a.get('slug') or i}",
            "titulos": [t for t in (a.get("titles") or {}).values() if t],
        })
    out.sort(key=lambda e: (e["anio"] or 9999, e["mes"] or 99, e["dia"] or 99, int(e["kitsu_id"])))
    return out
