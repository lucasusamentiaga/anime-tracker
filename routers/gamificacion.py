"""
routers/gamificacion.py — Racha de apertura, XP/niveles, logros y biblioteca
unificada (anime + pelis/series), más los exports sociales.

La lógica pura vive en gamificacion.py, achievements.py, stats_util.py y
share_page.py; aquí solo está el pegamento HTTP.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import achievements
import database as db
import gamificacion
import share_page
import stats_util

router = APIRouter(prefix="/api", tags=["gamificacion"])


def _gami_stats() -> dict:
    """Dict de estado para logros y XP (incluye la racha de apertura diaria)."""
    stats = gamificacion.construir_stats(
        db.listar_animes(), db.listar_media(), db.ep_log_streak())
    stats["racha_apertura_max"] = int(db.get_config("open_streak_max") or 0)
    return stats


@router.get("/stats/global")
async def stats_global():
    """Estadísticas combinadas de TODA la biblioteca: anime + películas + series."""
    return stats_util.stats_globales(db.listar_animes(), db.listar_media())


@router.get("/achievements")
async def get_achievements():
    """Logros/emblemas desbloqueados según tu actividad."""
    return achievements.evaluar_logros(_gami_stats())


@router.post("/streak/checkin")
async def streak_checkin():
    """Apertura diaria: +1 a la racha si es un día nuevo consecutivo (reset si se
    rompe). Idempotente dentro del mismo día; el frontend lo llama al iniciar."""
    cfg = db.get_config_many(["open_last_day", "open_streak_current",
                              "open_streak_max", "open_checkins_total"])
    last = cfg.get("open_last_day") or ""
    cur = int(cfg.get("open_streak_current") or 0)
    mx = int(cfg.get("open_streak_max") or 0)
    tot = int(cfg.get("open_checkins_total") or 0)
    last, cur, mx, tot, sumo = gamificacion.registrar_checkin(last, cur, mx, tot)
    if sumo:
        db.set_config("open_last_day", last)
        db.set_config("open_streak_current", str(cur))
        db.set_config("open_streak_max", str(mx))
        db.set_config("open_checkins_total", str(tot))
    return {"actual": cur, "max": mx, "sumo_hoy": sumo}


@router.get("/gamificacion")
async def gamificacion_estado():
    """Estado completo: nivel, XP (derivada del estado), rachas y logros."""
    stats = _gami_stats()
    logros = achievements.evaluar_logros(stats)
    cfg = db.get_config_many(["open_checkins_total", "open_streak_current", "open_streak_max"])
    checkins = int(cfg.get("open_checkins_total") or 0)
    xp = gamificacion.calcular_xp(stats, checkins, logros["desbloqueados"])
    prog = gamificacion.progreso(xp)
    return {
        "nivel":           prog["nivel"],
        "xp":              prog,
        "racha_apertura":  {"actual": int(cfg.get("open_streak_current") or 0),
                            "max": int(cfg.get("open_streak_max") or 0)},
        "racha_episodios": db.ep_log_streak(),
        "logros":          logros,
        "rango_ninja":     achievements.rango_ninja(stats.get("horas", 0)),
    }


@router.get("/export/share")
async def export_share():
    """Página HTML autocontenida con toda tu biblioteca, lista para compartir
    (enviarla o subirla a GitHub Pages → URL pública)."""
    perfil = {"nombre_usuario": db.get_config("nombre_usuario") or ""}
    html_doc = share_page.render_share_html(db.listar_animes(), db.listar_media(), perfil)
    return HTMLResponse(
        html_doc,
        headers={"Content-Disposition": "attachment; filename=miraru.html"},
    )
