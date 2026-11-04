"""
Logros / emblemas de Miraru (gamificación).

Idea portada de la app de nutrición (sistema de emblemas + rachas). Lógica pura
y testeable: evaluar_logros(stats) decide qué está desbloqueado. main.py solo
construye el dict `stats` desde la BD y llama aquí.
"""
from __future__ import annotations


# Cada logro: id, nombre, descripción, emblema (id del SVG en static/emblems/),
# tier (bronce/plata/oro para el color) y cond (predicado sobre el dict stats).
def _L(id_, nombre, desc, emblema, tier, cat, metrica, meta):
    """Logro de umbral: se desbloquea cuando stats[metrica] >= meta. Saber la
    métrica y la meta permite enseñar el progreso (42/50) de los bloqueados."""
    return {"id": id_, "nombre": nombre, "desc": desc, "emblema": emblema, "tier": tier,
            "cat": cat, "metrica": metrica, "meta": meta,
            "cond": lambda s, m=metrica, n=meta: s[m] >= n}


# Categorías, en el orden en que se enseñan.
CATEGORIAS = [("biblioteca", "Biblioteca"), ("visionado", "Visionado"),
              ("constancia", "Constancia"), ("gusto", "Gusto"), ("rango", "Rango ninja")]

LOGROS = [
    _L("primer_paso",   "Primer paso",   "Añade tu primer título",          "spark", "bronce", "biblioteca", "total", 1),
    _L("coleccionista", "Coleccionista", "10 títulos en tu biblioteca",     "shelf", "bronce", "biblioteca", "total", 10),
    _L("bibliotecario", "Bibliotecario", "50 títulos en tu biblioteca",     "shelf", "oro",    "biblioteca", "total", 50),
    {"id": "omnivoro", "nombre": "Omnívoro", "desc": "Ten anime, series y películas",
     "emblema": "trio", "tier": "oro", "cat": "biblioteca", "metrica": None, "meta": 3,
     "cond": lambda s: s["animes"] >= 1 and s["series"] >= 1 and s["peliculas"] >= 1},
    _L("primer_final",  "Primer final",  "Completa tu primer título",       "check", "bronce", "visionado", "completados", 1),
    _L("rematador",     "Rematador",     "Completa 10 títulos",             "check", "plata",  "visionado", "completados", 10),
    _L("veterano",      "Incansable",     "Completa 50 títulos",             "check", "plata",  "visionado", "completados", 50),
    _L("maestro",       "Maestro",       "Completa 100 títulos",            "crown", "oro",    "visionado", "completados", 100),
    _L("maratoniano",   "Maratoniano",   "100 episodios vistos",            "flame", "plata",  "visionado", "episodios", 100),
    _L("sin_frenos",    "Sin frenos",    "1000 episodios vistos",           "flame", "oro",    "visionado", "episodios", 1000),
    _L("centenario",    "Centenario",    "100 horas de visionado",          "clock", "oro",    "visionado", "horas", 100),
    _L("cinefilo",      "Cinéfilo",      "Completa 10 películas",           "film",  "plata",  "visionado", "pelis_completadas", 10),
    _L("en_racha",      "En racha",      "7 días seguidos viendo algo",     "streak", "plata", "constancia", "racha_max", 7),
    _L("imparable",     "Imparable",     "30 días seguidos viendo algo",    "streak", "oro",   "constancia", "racha_max", 30),
    _L("fiel",          "Fiel",          "Abre Miraru 7 días seguidos",     "streak", "plata", "constancia", "racha_apertura_max", 7),
    _L("devoto",        "Devoto",        "Abre Miraru 30 días seguidos",    "flame", "oro",    "constancia", "racha_apertura_max", 30),
    _L("critico",       "Crítico",       "Puntúa 20 títulos",               "star",  "plata",  "gusto", "puntuados", 20),
    _L("cronista",      "Cronista",      "Puntúa 100 títulos",              "star",  "oro",    "gusto", "puntuados", 100),
    _L("enamorado",     "Enamorado",     "Marca 10 títulos como favoritos", "heart", "plata",  "gusto", "favoritos", 10),
    # ── Rangos ninja (por horas): se enseñan como una línea de rangos, no en
    # la cuadrícula, pero cuentan como logros (y dan su XP).
    _L("genin",  "Genin",  "10 horas vistas — tu camino ninja empieza",     "kunai",    "bronce", "rango", "horas", 10),
    _L("chunin", "Chūnin", "50 horas vistas — ya dominas las misiones",     "shuriken", "plata",  "rango", "horas", 50),
    _L("jonin",  "Jōnin",  "150 horas vistas — élite entre los ninja",      "scroll",   "plata",  "rango", "horas", 150),
    _L("sannin", "Sannin", "500 horas vistas — ninja legendario",           "katana",   "oro",    "rango", "horas", 500),
    _L("hokage", "Hokage", "1000 horas vistas — líder supremo de la aldea", "hokage",   "oro",    "rango", "horas", 1000),
]

# Claves que el predicado puede usar; se rellenan a 0 si faltan.
_KEYS = ("total", "animes", "series", "peliculas", "episodios", "completados",
         "pelis_completadas", "puntuados", "horas", "racha_max", "racha_actual",
         "favoritos", "racha_apertura_max")


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _norm(stats: dict) -> dict:
    return {k: _num(stats.get(k)) for k in _KEYS}


def _actual(lg: dict, s: dict) -> float:
    if lg.get("metrica"):
        return s[lg["metrica"]]
    if lg["id"] == "omnivoro":
        return sum(1 for k in ("animes", "series", "peliculas") if s[k] >= 1)
    return 0


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
        meta = lg.get("meta") or 1
        actual = min(_actual(lg, s), meta)
        out.append({
            "id": lg["id"], "nombre": lg["nombre"], "desc": lg["desc"],
            "emblema": lg["emblema"], "tier": lg["tier"], "cat": lg.get("cat", "biblioteca"),
            "unlocked": unlocked, "meta": meta,
            "actual": int(actual) if float(actual).is_integer() else round(actual, 1),
            "progreso": 1.0 if unlocked else round(min(0.99, actual / meta), 3),
        })
    return {"logros": out, "desbloqueados": desbloqueados, "total": len(LOGROS),
            "categorias": [{"id": c, "nombre": n} for c, n in CATEGORIAS]}


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
