"""
themes_api.py — Openings y endings vía AnimeThemes.moe (API pública y gratuita).

Devuelve enlaces directos a vídeo (webm) de cada OP/ED, para poder escucharlos
desde la ficha del anime sin salir de Miraru.

El parseo está separado de la red para poder testearlo sin internet.
Docs: https://api-docs.animethemes.moe
"""
from __future__ import annotations

API = "https://api.animethemes.moe/anime"

# Pedimos solo lo que usamos: nombre, temas, canción y vídeos.
INCLUDE = "animethemes.song,animethemes.animethemeentries.videos"


def _orden(slug: str) -> tuple[int, int]:
    """Ordena OP1, OP2… antes que ED1, ED2… (y numéricamente, no alfabéticamente:
    de lo contrario 'OP10' quedaría antes que 'OP2')."""
    s = (slug or "").upper()
    tipo = 0 if s.startswith("OP") else (1 if s.startswith("ED") else 2)
    num = "".join(c for c in s if c.isdigit())
    return (tipo, int(num) if num else 0)


def parsear(payload: dict, limite: int = 12) -> list[dict]:
    """Extrae los temas de la respuesta de AnimeThemes. Nunca lanza.

    Estructura: anime[] → animethemes[] → {slug, song, animethemeentries[] → videos[]}
    """
    out: list[dict] = []
    try:
        animes = (payload or {}).get("anime") or []
        if not animes:
            return []
        for tema in (animes[0].get("animethemes") or []):
            slug = (tema.get("slug") or "").upper()
            cancion = (tema.get("song") or {}) or {}
            # El primer vídeo disponible de la primera entrada sirve
            enlace = ""
            for entrada in (tema.get("animethemeentries") or []):
                for video in (entrada.get("videos") or []):
                    if video.get("link"):
                        enlace = video["link"]
                        break
                if enlace:
                    break
            if not enlace:
                continue           # sin vídeo no aporta nada
            out.append({
                "slug":   slug or "?",
                "tipo":   "OP" if slug.startswith("OP") else ("ED" if slug.startswith("ED") else "OTRO"),
                "titulo": (cancion.get("title") or "").strip(),
                "artista": ", ".join(
                    a.get("name", "") for a in (cancion.get("artists") or []) if a.get("name")
                ),
                "video":  enlace,
            })
    except Exception:
        return []
    out.sort(key=lambda t: _orden(t["slug"]))
    return out[:limite]
