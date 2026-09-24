"""
Logros / emblemas de Miraru (gamificación).

Idea portada de la app de nutrición (sistema de emblemas + rachas). Lógica pura
y testeable: evaluar_logros(stats) decide qué está desbloqueado. main.py solo
construye el dict `stats` desde la BD y llama aquí.
"""
from __future__ import annotations

# Cada logro: id, nombre, descripción, emblema (id del SVG en static/emblems/),
# tier (bronce/plata/oro para el color) y cond (predicado sobre el dict stats).
LOGROS = [
    {"id": "primer_paso",   "nombre": "Primer paso",   "desc": "Añade tu primer título",
     "emblema": "spark",  "tier": "bronce", "cond": lambda s: s["total"] >= 1},
    {"id": "coleccionista", "nombre": "Coleccionista",  "desc": "10 títulos en tu biblioteca",
     "emblema": "shelf",  "tier": "bronce", "cond": lambda s: s["total"] >= 10},
    {"id": "bibliotecario", "nombre": "Bibliotecario",  "desc": "50 títulos en tu biblioteca",
     "emblema": "shelf",  "tier": "oro",    "cond": lambda s: s["total"] >= 50},
    {"id": "rematador",     "nombre": "Rematador",      "desc": "Completa 10 títulos",
     "emblema": "check",  "tier": "plata",  "cond": lambda s: s["completados"] >= 10},
    {"id": "maratoniano",   "nombre": "Maratoniano",    "desc": "100 episodios vistos",
     "emblema": "flame",  "tier": "plata",  "cond": lambda s: s["episodios"] >= 100},
    {"id": "sin_frenos",    "nombre": "Sin frenos",     "desc": "1000 episodios vistos",
     "emblema": "flame",  "tier": "oro",    "cond": lambda s: s["episodios"] >= 1000},
    {"id": "en_racha",      "nombre": "En racha",       "desc": "7 días seguidos viendo algo",
     "emblema": "streak", "tier": "plata",  "cond": lambda s: s["racha_max"] >= 7},
    {"id": "imparable",     "nombre": "Imparable",      "desc": "30 días seguidos",
     "emblema": "streak", "tier": "oro",    "cond": lambda s: s["racha_max"] >= 30},
    {"id": "cinefilo",      "nombre": "Cinéfilo",       "desc": "Completa 10 películas",
     "emblema": "film",   "tier": "plata",  "cond": lambda s: s["pelis_completadas"] >= 10},
    {"id": "critico",       "nombre": "Crítico",        "desc": "Puntúa 20 títulos",
     "emblema": "star",   "tier": "plata",  "cond": lambda s: s["puntuados"] >= 20},
    {"id": "omnivoro",      "nombre": "Omnívoro",       "desc": "Ten anime, series y películas",
     "emblema": "trio",   "tier": "oro",    "cond": lambda s: s["animes"] >= 1 and s["series"] >= 1 and s["peliculas"] >= 1},
    {"id": "centenario",    "nombre": "Centenario",     "desc": "100 horas de visionado",
     "emblema": "clock",  "tier": "oro",    "cond": lambda s: s["horas"] >= 100},
    {"id": "fiel",          "nombre": "Fiel",           "desc": "Abre Miraru 7 días seguidos",
     "emblema": "streak", "tier": "plata",  "cond": lambda s: s["racha_apertura_max"] >= 7},
    {"id": "devoto",        "nombre": "Devoto",         "desc": "Abre Miraru 30 días seguidos",
     "emblema": "flame",  "tier": "oro",    "cond": lambda s: s["racha_apertura_max"] >= 30},
    {"id": "enamorado",     "nombre": "Enamorado",      "desc": "Marca 10 títulos como favoritos",
     "emblema": "heart",  "tier": "plata",  "cond": lambda s: s["favoritos"] >= 10},
    {"id": "maestro",       "nombre": "Maestro",        "desc": "Completa 100 títulos",
     "emblema": "crown",  "tier": "oro",    "cond": lambda s: s["completados"] >= 100},
    # ── Rangos ninja (por horas de visionado) ────────────────────────────────
    {"id": "genin",    "nombre": "Genin",    "desc": "10 horas vistas — tu camino ninja empieza",
     "emblema": "kunai",    "tier": "bronce", "cond": lambda s: s["horas"] >= 10},
    {"id": "chunin",   "nombre": "Chūnin",   "desc": "50 horas vistas — ya dominas las misiones",
     "emblema": "shuriken", "tier": "plata",  "cond": lambda s: s["horas"] >= 50},
    {"id": "jonin",    "nombre": "Jōnin",    "desc": "150 horas vistas — élite entre los ninja",
     "emblema": "scroll",   "tier": "plata",  "cond": lambda s: s["horas"] >= 150},
    {"id": "sannin",   "nombre": "Sannin",   "desc": "500 horas vistas — ninja legendario",
     "emblema": "katana",   "tier": "oro",    "cond": lambda s: s["horas"] >= 500},
    {"id": "hokage",   "nombre": "Hokage",   "desc": "1000 horas vistas — líder supremo de la aldea",
     "emblema": "hokage",   "tier": "oro",    "cond": lambda s: s["horas"] >= 1000},
]

# Claves que el predicado puede usar; se rellenan a 0 si faltan.
_KEYS = ("total", "animes", "series", "peliculas", "episodios", "completados",
         "pelis_completadas", "puntuados", "horas", "racha_max", "racha_actual",
         "favoritos", "racha_apertura_max")


def _norm(stats: dict) -> dict:
    return {k: stats.get(k, 0) or 0 for k in _KEYS}


def evaluar_logros(stats: dict) -> dict:
    """Devuelve {logros:[...], desbloqueados:N, total:M}. Cada logro lleva
    'unlocked': bool. Nunca lanza aunque falten claves en stats."""
    s = _norm(stats)
    out = []
    desbloqueados = 0
    for lg in LOGROS:
        try:
            unlocked = bool(lg["cond"](s))
        except Exception:
            unlocked = False
        if unlocked:
            desbloqueados += 1
        out.append({
            "id": lg["id"], "nombre": lg["nombre"], "desc": lg["desc"],
            "emblema": lg["emblema"], "tier": lg["tier"], "unlocked": unlocked,
        })
    return {"logros": out, "desbloqueados": desbloqueados, "total": len(LOGROS)}


# ── Rango ninja (basado en horas) ────────────────────────────────────────────
_RANGOS = [
    (1000, "Hokage",  "hokage",  "Líder supremo de la aldea"),
    (500,  "Sannin",  "katana",  "Ninja legendario"),
    (150,  "Jōnin",   "scroll",  "Élite entre los ninja"),
    (50,   "Chūnin",  "shuriken","Dominas las misiones"),
    (10,   "Genin",   "kunai",   "Tu camino ninja empieza"),
    (0,    "Academia","spark",   "Aún en formación"),
]


def rango_ninja(horas: float) -> dict:
    """Devuelve el rango actual y el progreso hacia el siguiente."""
    horas = horas or 0
    for i, (umbral, nombre, emblema, desc) in enumerate(_RANGOS):
        if horas >= umbral:
            # Siguiente rango
            if i > 0:
                sig_umbral, sig_nombre = _RANGOS[i - 1][0], _RANGOS[i - 1][1]
                progreso = (horas - umbral) / (sig_umbral - umbral)
            else:
                sig_umbral, sig_nombre = None, None
                progreso = 1.0
            return {
                "nombre": nombre, "emblema": emblema, "desc": desc,
                "horas": round(horas, 1), "umbral": umbral,
                "siguiente": sig_nombre, "siguiente_umbral": sig_umbral,
                "progreso": min(1.0, round(progreso, 3)),
            }
    return {"nombre": "Academia", "emblema": "spark", "desc": "Aún en formación",
            "horas": 0, "umbral": 0, "siguiente": "Genin",
            "siguiente_umbral": 10, "progreso": 0}
