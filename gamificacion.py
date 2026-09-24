"""
Gamificación de Miraru: racha de apertura diaria + experiencia (XP) y niveles.

Lógica pura y testeable. main.py persiste la racha en la tabla config y expone
los endpoints; aquí no se toca la BD.

- XP es DERIVADA del estado actual (no por eventos): así nunca se duplica ni
  necesita migraciones; se recalcula a partir de tus stats + check-ins + logros.
- La racha de apertura sí necesita persistencia (último día, actual, máx, total).
"""
from __future__ import annotations

import datetime

# XP por unidad de cada cosa (derivada del estado actual).
XP = {
    "episodio":   2,    # por episodio visto
    "completado": 25,   # por título completado
    "titulo":     5,    # por título en la biblioteca
    "checkin":    10,   # por día que abres la app (racha)
    "logro":      50,   # por logro desbloqueado
}


def construir_stats(animes: list[dict], media: list[dict], ep_streak: dict) -> dict:
    """Normaliza el estado de la biblioteca al dict que consumen los logros y la XP.
    Pura: importa stats_util (también puro), no toca la BD."""
    import stats_util
    g = stats_util.stats_globales(animes, media)
    comp = lambda x: x.get("estado_usuario") in ("completado", "completed")
    return {
        "total":             g["total_titulos"],
        "animes":            g["animes"],
        "series":            g["series"],
        "peliculas":         g["peliculas"],
        "episodios":         g["total_episodios"],
        "horas":             g["horas_totales"],
        "completados":       sum(1 for a in animes if comp(a)) + sum(1 for m in media if comp(m)),
        "pelis_completadas": sum(1 for m in media if m.get("tipo") == "pelicula" and comp(m)),
        "puntuados":         sum(1 for a in animes if a.get("puntuacion")) + sum(1 for m in media if m.get("puntuacion")),
        "racha_max":         ep_streak.get("max", 0),
        "racha_actual":      ep_streak.get("actual", 0),
        "favoritos":         sum(1 for a in animes if a.get("favorito")) + sum(1 for m in media if m.get("favorito")),
    }


# ── Experiencia y niveles ─────────────────────────────────────────────────────

def calcular_xp(stats: dict, checkins: int, logros_desbloqueados: int) -> int:
    return int(
        (stats.get("episodios", 0) or 0) * XP["episodio"]
        + (stats.get("completados", 0) or 0) * XP["completado"]
        + (stats.get("total", 0) or 0) * XP["titulo"]
        + (checkins or 0) * XP["checkin"]
        + (logros_desbloqueados or 0) * XP["logro"]
    )


def umbral(nivel: int) -> int:
    """XP acumulada necesaria para ALCANZAR ese nivel. Nivel 1 = 0 XP."""
    if nivel <= 1:
        return 0
    return 50 * nivel * (nivel - 1)   # 0,100,300,600,1000,1500,...


def progreso(xp: int) -> dict:
    """Nivel actual y progreso hacia el siguiente a partir de la XP total."""
    xp = max(0, int(xp or 0))
    nivel = 1
    while umbral(nivel + 1) <= xp:
        nivel += 1
    base = umbral(nivel)
    siguiente = umbral(nivel + 1)
    rango = siguiente - base
    return {
        "xp":            xp,
        "nivel":         nivel,
        "xp_nivel":      base,
        "xp_siguiente":  siguiente,
        "falta":         max(0, siguiente - xp),
        "progreso":      round((xp - base) / rango, 3) if rango > 0 else 1.0,
    }


# ── Racha de apertura diaria ──────────────────────────────────────────────────

def registrar_checkin(last_day: str, current: int, maximo: int, total: int,
                      hoy: str | None = None) -> tuple[str, int, int, int, bool]:
    """Procesa la apertura de hoy. Devuelve (last_day, current, max, total, sumo_hoy).
    - Mismo día: no cambia nada (sumo_hoy=False).
    - Día consecutivo: current += 1.
    - Hueco / primer uso: current = 1.
    Idempotente dentro del mismo día."""
    today = hoy or datetime.date.today().isoformat()
    if last_day == today:
        return last_day, current, maximo, total, False
    try:
        ld = datetime.date.fromisoformat(last_day) if last_day else None
    except (ValueError, TypeError):
        ld = None
    td = datetime.date.fromisoformat(today)
    current = current + 1 if (ld and (td - ld).days == 1) else 1
    maximo = max(maximo, current)
    total = (total or 0) + 1
    return today, current, maximo, total, True
