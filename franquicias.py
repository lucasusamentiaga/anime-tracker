"""
franquicias.py — Agrupa animes en franquicias por similitud de nombre.

Ejemplos: "Date A Live", "Date A Live II", "Date A Live III" → franquicia "Date A Live"
          "Shingeki no Kyojin", "Shingeki no Kyojin Season 2" → franquicia "Shingeki no Kyojin"

Lógica pura, sin BD ni I/O.
"""
from __future__ import annotations

import re

# Patrones que indican "temporada N" o secuela — se eliminan para hallar el base.
_SEASON_RE = re.compile(
    r"""(?x)
    # Trailing season markers
    (?:
        \s*[:：]\s*.*$                       # subtítulo tras : (ej. ": The Final Season")
      | \s+(?:Season|Temporada)\s+\d+       # Season 2, Temporada 3
      | \s+S\d+                              # S2, S03
      | \s+Part\s+\d+                        # Part 2
      | \s+Parte\s+\d+                       # Parte 2
      | \s+Cour\s+\d+                        # Cour 2
      | \s+\d+(?:st|nd|rd|th)\s+Season       # 2nd Season
      | \s+(?:I{2,4}V?|VI{0,3})(?:\s|$)     # Roman numerals II, III, IV, V, VI
      | \s+(?:Shin|Zoku|Shin'?)(?:\s|$)      # Shin / Zoku (continuation)
      | \s+\d+$                              # trailing number: "Title 2"
    )
    """,
    re.IGNORECASE,
)

# Para extraer un número de temporada del nombre (para ordenar dentro de franquicia)
_ORDER_RE = re.compile(
    r"""(?x)
      Season\s+(\d+)
    | Temporada\s+(\d+)
    | S(\d+)
    | (\d+)(?:st|nd|rd|th)\s+Season
    | Part\s+(\d+)
    | Parte\s+(\d+)
    | Cour\s+(\d+)
    | \b(IX|IV|VI{0,3}|I{1,3})\b  # Roman
    | \s+(\d+)$                    # trailing number
    """,
    re.IGNORECASE,
)

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
           "VIII": 8, "IX": 9}


def _base_name(nombre: str) -> str:
    """Extrae el nombre base quitando indicadores de temporada."""
    base = _SEASON_RE.sub("", nombre).strip()
    # Si quedó vacío (todo era modificadores), usar el original
    return base if base else nombre


def _season_order(nombre: str) -> int:
    """Extrae un número de orden de temporada para sorting."""
    m = _ORDER_RE.search(nombre)
    if not m:
        return 0
    for g in m.groups():
        if g is None:
            continue
        g = g.strip()
        if g in _ROMAN:
            return _ROMAN[g]
        if g.isdigit():
            return int(g)
        # Roman numeral uppercase
        upper = g.upper()
        if upper in _ROMAN:
            return _ROMAN[upper]
    return 0


def agrupar_franquicias(animes: list[dict]) -> list[dict]:
    """Agrupa una lista de animes en franquicias.

    Devuelve lista de dicts:
      {
        "nombre": str (nombre de la franquicia),
        "imagen": str (portada del primer título),
        "animes": [anime_dict, ...],  # ordenados por temporada
        "total_eps": int,
        "vistos": int,
        "estados": {estado: count},
      }
    Franquicias con un solo anime se devuelven igual (el frontend
    las muestra como card normal).
    """
    # 1. Agrupar por base normalizada
    grupos: dict[str, list[dict]] = {}
    for a in animes:
        base = _base_name(a.get("nombre", ""))
        key = base.lower().strip()
        if key not in grupos:
            grupos[key] = []
        grupos[key].append(a)

    # 2. Construir resultado
    resultado = []
    for _key, members in grupos.items():
        # Ordenar miembros por season order, luego por nombre
        members.sort(key=lambda a: (_season_order(a["nombre"]), a["nombre"]))
        first = members[0]

        total_eps = 0
        vistos = 0
        estados: dict[str, int] = {}
        for a in members:
            caps = str(a.get("capitulos") or "").strip().lower()
            nums = re.findall(r"\d+", caps)
            total_eps += int(nums[0]) if nums else 0
            vistos += int(a.get("episodios_vistos") or 0)
            est = a.get("estado_usuario", "pendiente")
            estados[est] = estados.get(est, 0) + 1

        resultado.append({
            "nombre": _base_name(first["nombre"]),
            "imagen": first.get("imagen", ""),
            "animes": members,
            "count": len(members),
            "total_eps": total_eps,
            "vistos": vistos,
            "estados": estados,
        })

    # Ordenar franquicias por nombre
    resultado.sort(key=lambda f: f["nombre"].lower())
    return resultado
