"""
personajes_api.py — Personajes y actores de voz (seiyuus) vía Jikan v4.

Da a la ficha del anime el acabado de las apps comerciales: caras de los
protagonistas y quién los dobla.

El parseo va separado de la red para poder testearlo sin internet.
Docs: https://docs.api.jikan.moe  (endpoint /anime/{id}/characters)
"""
from __future__ import annotations

BUSCAR = "https://api.jikan.moe/v4/anime"
PERSONAJES = "https://api.jikan.moe/v4/anime/{mal_id}/characters"

# Orden de preferencia del idioma del doblaje: el japonés es el relevante para
# anime; el resto solo se usa si no hay seiyuu japonés.
_IDIOMAS = ("Japanese", "Spanish", "English")


def _mejor_voz(voices: list) -> dict:
    """Elige el actor de voz más relevante entre los idiomas disponibles."""
    if not voices:
        return {}
    por_idioma = {}
    for v in voices:
        idioma = (v.get("language") or "").strip()
        if idioma and idioma not in por_idioma:
            por_idioma[idioma] = v
    for idioma in _IDIOMAS:
        if idioma in por_idioma:
            return por_idioma[idioma]
    return voices[0]


def parsear(payload: dict, limite: int = 12) -> list[dict]:
    """Extrae personajes de la respuesta de Jikan. Nunca lanza.

    Estructura: data[] → {character:{name,images}, role, voice_actors[]}
    Se prioriza a los personajes principales (role == "Main").
    """
    out: list[dict] = []
    try:
        for item in (payload or {}).get("data") or []:
            per = item.get("character") or {}
            nombre = (per.get("name") or "").strip()
            if not nombre:
                continue
            imgs = (per.get("images") or {}).get("jpg") or {}
            voz = _mejor_voz(item.get("voice_actors") or [])
            persona = voz.get("person") or {}
            v_imgs = (persona.get("images") or {}).get("jpg") or {}
            out.append({
                "nombre":       nombre,
                "rol":          (item.get("role") or "").strip(),   # Main / Supporting
                "imagen":       imgs.get("image_url") or "",
                "seiyuu":       (persona.get("name") or "").strip(),
                "seiyuu_img":   v_imgs.get("image_url") or "",
                "idioma":       (voz.get("language") or "").strip(),
            })
    except Exception:
        return []
    # Principales primero, conservando el orden original dentro de cada grupo
    out.sort(key=lambda p: 0 if p["rol"].lower() == "main" else 1)
    return out[:limite]


def primer_mal_id(payload: dict) -> int:
    """Saca el mal_id del primer resultado de una búsqueda en Jikan. 0 si no hay."""
    try:
        datos = (payload or {}).get("data") or []
        return int(datos[0].get("mal_id") or 0) if datos else 0
    except Exception:
        return 0
