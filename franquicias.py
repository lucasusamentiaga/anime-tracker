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
      | \s+(?:The\s+)?Final\s+(?:Season|Chapters?)  # The Final Season / Final Chapters
      | \s+(?:Season|Temporada)\s+\d+       # Season 2, Temporada 3
      | \s+S\d+                              # S2, S03
      | \s+Part\s+\d+                        # Part 2
      | \s+Parte\s+\d+                       # Parte 2
      | \s+Cour\s+\d+                        # Cour 2
      | \s+\d+(?:st|nd|rd|th)\s+Season       # 2nd Season
      | \s+(?:I{2,4}V?|VI{0,3})(?:\s|$)     # Roman numerals II, III, IV, V, VI
      | \s+(?:Shin|Zoku|Shin'?)(?:\s|$)      # Shin / Zoku (continuation)
      | \s+Movie\s+\d+\b                     # Movie 1, Movie 2
      | \s+Movie(?=\s|$|:)                   # Movie (alone or before : )
      | \s+OVA\d*(?=\s|$|:)                  # OVA, OVA2
      | \s+ONA\d*(?=\s|$|:)                  # ONA, ONA2
      | \s+Specials?(?:\s+\d+)?(?=\s|$|:)    # Special, Specials, Special 2
      | \s+Recap(?=\s|$|:)                   # Recap
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
    # Aplicar la regex repetidamente hasta que no haya más cambios
    base = nombre
    for _ in range(5):
        nuevo = _SEASON_RE.sub("", base).strip()
        if nuevo == base:
            break
        base = nuevo
    # Si quedó vacío (todo era modificadores), usar el original
    return base if base else nombre


def _season_order(nombre: str) -> int:
    """Extrae un número de orden de temporada para sorting. "The Final Season"
    (y sus "Part 2") van después de las temporadas numeradas."""
    final = 90 if re.search(r"\bfinal\b", nombre, re.I) else 0
    return final + _numero_temporada(nombre)


def _numero_temporada(nombre: str) -> int:
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


# ── Agrupación ──────────────────────────────────────────────────────────────
# Además del nombre base, dos animes van al mismo grupo si:
#   · uno empieza por el nombre entero del otro ("Masamune-kun's Revenge" y
#     "Masamune-kun's Revenge R");
#   · comparten el principio del título ("Rascal Does Not Dream of Bunny Girl
#     Senpai" / "… of Santa Claus"): ≥4 palabras y ≥60 % de ambos títulos;
#   · AniList dice que están relacionados (secuela, precuela, historia paralela).
# El usuario manda sobre todo esto con el campo `grupo` de cada anime:
#   ""  → automático · "-" → siempre suelto · "<nombre>" → en ese grupo.

GRUPO_SUELTO = "-"

_PALABRAS_VACIAS = {"of", "a", "an", "the", "and", "to", "de", "del", "la", "el",
                    "los", "las", "y", "no", "wa", "ga", "wo", "ni", "in", "on",
                    "with", "for", "&", "x"}


def _palabras(nombre: str) -> list[str]:
    """Palabras normalizadas (minúsculas, solo letras y números)."""
    out = []
    for w in (nombre or "").split():
        k = "".join(ch for ch in w.casefold() if ch.isalnum())
        if k:
            out.append(k)
    return out


def _clave(nombre: str) -> str:
    return " ".join(_palabras(nombre))


def nombre_comun(nombres: list[str]) -> str:
    """Nombre para un grupo de títulos: el principio que comparten (sin palabras
    vacías al final) si tiene al menos 2 palabras; si no, el más corto."""
    nombres = [n.strip() for n in nombres if n and n.strip()]
    if not nombres:
        return ""
    if len(nombres) == 1:
        return nombres[0]
    crudos = [n.split() for n in nombres]
    normal = [[("".join(ch for ch in w.casefold() if ch.isalnum())) for w in c] for c in crudos]
    n = 0
    while all(len(c) > n for c in normal) and len({c[n] for c in normal}) == 1:
        n += 1
    corto = min(range(len(crudos)), key=lambda i: (len(crudos[i]), nombres[i]))
    while n > 0 and normal[corto][n - 1] in _PALABRAS_VACIAS:
        n -= 1
    if n >= 2 or (n >= 1 and n == len(crudos[corto])):
        return " ".join(crudos[corto][:n]).rstrip(" :：-–—,")
    return nombres[corto]


def _misma_saga(a: list[str], b: list[str]) -> bool:
    """¿Dos títulos (ya en palabras normalizadas) son de la misma saga?"""
    if not a or not b:
        return False
    corto, largo = (a, b) if len(a) <= len(b) else (b, a)
    if largo[:len(corto)] == corto:
        # Uno es el comienzo entero del otro: "masamunekuns revenge" + "r".
        return len(corto) >= 2 and len("".join(corto)) >= 6
    n = 0
    while n < len(corto) and a[n] == b[n]:
        n += 1
    return n >= 4 and n / len(a) >= 0.6 and n / len(b) >= 0.6


class _Uniones:
    def __init__(self, n: int):
        self.p = list(range(n))

    def raiz(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def unir(self, i: int, j: int) -> None:
        ri, rj = self.raiz(i), self.raiz(j)
        if ri != rj:
            self.p[max(ri, rj)] = min(ri, rj)


def _ordenar_miembros(members: list[dict]) -> None:
    """Por número de temporada del nombre y, a igualdad, por anilist_id (AniList
    da los ids por orden de alta y las secuelas se dan de alta después: así
    "Bunny Girl Senpai" va antes que "Santa Claus")."""
    members.sort(key=lambda a: (_season_order(a["nombre"]),
                                int(a.get("anilist_id") or 0) or 10**9, a["nombre"]))


def agrupar_franquicias(animes: list[dict],
                        relaciones: dict | None = None) -> list[dict]:
    """Agrupa una lista de animes en franquicias.

    `relaciones`: {anilist_id: [ids relacionados]} (opcional, de AniList).

    Devuelve lista de dicts:
      {
        "nombre": str (nombre de la franquicia),
        "imagen": str (portada del primer título),
        "animes": [anime_dict, ...],  # ordenados por temporada
        "manual": bool (el usuario le puso nombre),
        "total_eps": int, "vistos": int, "estados": {estado: count},
      }
    Franquicias con un solo anime se devuelven igual (el frontend
    las muestra como card normal).
    """
    animes = list(animes)
    n = len(animes)
    uf = _Uniones(n)
    automaticos = [i for i, a in enumerate(animes) if not (a.get("grupo") or "").strip()]

    # 1. Mismo nombre base
    bases = {i: _base_name(animes[i].get("nombre", "")) for i in automaticos}
    palabras = {i: _palabras(bases[i]) for i in automaticos}
    por_base: dict[str, int] = {}
    for i in automaticos:
        k = " ".join(palabras[i]) or animes[i].get("nombre", "").casefold()
        if k in por_base:
            uf.unir(por_base[k], i)
        else:
            por_base[k] = i

    # 2. Mismo comienzo de título (una comparación por base distinta)
    reps = list(por_base.values())
    for x in range(len(reps)):
        for y in range(x + 1, len(reps)):
            i, j = reps[x], reps[y]
            if _misma_saga(palabras[i], palabras[j]):
                uf.unir(i, j)

    # 3. Relaciones de AniList
    if relaciones:
        por_id = {}
        for i in automaticos:
            aid = int(animes[i].get("anilist_id") or 0)
            if aid:
                por_id.setdefault(aid, i)
        for i in automaticos:
            aid = int(animes[i].get("anilist_id") or 0)
            for rel in relaciones.get(aid) or relaciones.get(str(aid)) or []:
                j = por_id.get(int(rel))
                if j is not None:
                    uf.unir(i, j)

    # 4. Grupos: automáticos por componente, manuales por nombre. Si un grupo
    #    automático se llama igual que uno manual, se juntan.
    grupos: dict[str, dict] = {}

    def _meter(clave: str, nombre: str, manual: bool, a: dict) -> None:
        g = grupos.setdefault(clave, {"nombre": nombre, "manual": manual, "animes": []})
        if manual and not g["manual"]:
            g["nombre"], g["manual"] = nombre, True
        g["animes"].append(a)

    componentes: dict[int, list[int]] = {}
    for i in automaticos:
        componentes.setdefault(uf.raiz(i), []).append(i)
    for idxs in componentes.values():
        nombre = nombre_comun(sorted({bases[i] for i in idxs}))
        for i in idxs:
            _meter(_clave(nombre) or f"auto:{idxs[0]}", nombre, False, animes[i])

    for i, a in enumerate(animes):
        g = (a.get("grupo") or "").strip()
        if not g:
            continue
        if g == GRUPO_SUELTO:
            _meter(f"suelto:{i}", a.get("nombre", ""), False, a)
            grupos[f"suelto:{i}"]["suelto"] = True
        else:
            _meter(_clave(g) or f"manual:{g}", g, True, a)

    # 5. Resultado
    resultado = []
    for g in grupos.values():
        members = g["animes"]
        _ordenar_miembros(members)
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
            "nombre": (g["nombre"] if len(members) > 1 or g["manual"] or g.get("suelto")
                       else _base_name(first["nombre"])),
            "imagen": first.get("imagen", ""),
            "animes": members,
            "manual": g["manual"],
            "count": len(members),
            "total_eps": total_eps,
            "vistos": vistos,
            "estados": estados,
        })

    # Ordenar franquicias por nombre
    resultado.sort(key=lambda f: f["nombre"].lower())
    return resultado
