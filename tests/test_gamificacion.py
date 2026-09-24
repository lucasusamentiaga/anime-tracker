"""Tests de gamificación (módulo puro gamificacion.py — no importa main)."""
from __future__ import annotations

import gamificacion as G

# ── XP / niveles ──────────────────────────────────────────────────────────────

def test_xp_se_deriva_del_estado():
    stats = {"episodios": 100, "completados": 10, "total": 20}
    xp = G.calcular_xp(stats, checkins=30, logros_desbloqueados=5)
    # 100*2 + 10*25 + 20*5 + 30*10 + 5*50 = 200+250+100+300+250 = 1100
    assert xp == 1100


def test_umbrales_de_nivel():
    assert G.umbral(1) == 0
    assert G.umbral(2) == 100
    assert G.umbral(3) == 300
    assert G.umbral(5) == 1000


def test_progreso_nivel():
    p = G.progreso(1100)
    assert p["nivel"] == 5          # umbral(5)=1000 <= 1100 < umbral(6)=1500
    assert p["xp_nivel"] == 1000 and p["xp_siguiente"] == 1500
    assert p["falta"] == 400
    assert 0 < p["progreso"] < 1


def test_progreso_xp_cero_es_nivel_1():
    p = G.progreso(0)
    assert p["nivel"] == 1 and p["progreso"] == 0.0


def test_calcular_xp_robusto_con_none():
    assert G.calcular_xp({}, None, None) == 0


# ── Racha de apertura ─────────────────────────────────────────────────────────

def test_primer_checkin_inicia_racha():
    last, cur, mx, tot, sumo = G.registrar_checkin("", 0, 0, 0, hoy="2026-06-17")
    assert sumo and cur == 1 and mx == 1 and tot == 1 and last == "2026-06-17"


def test_mismo_dia_no_suma():
    last, cur, mx, tot, sumo = G.registrar_checkin("2026-06-17", 3, 5, 10, hoy="2026-06-17")
    assert not sumo and cur == 3 and tot == 10


def test_dia_consecutivo_incrementa():
    last, cur, mx, tot, sumo = G.registrar_checkin("2026-06-16", 3, 5, 10, hoy="2026-06-17")
    assert sumo and cur == 4 and mx == 5 and tot == 11


def test_dia_consecutivo_actualiza_maximo():
    last, cur, mx, tot, sumo = G.registrar_checkin("2026-06-16", 5, 5, 10, hoy="2026-06-17")
    assert cur == 6 and mx == 6


def test_hueco_rompe_la_racha():
    last, cur, mx, tot, sumo = G.registrar_checkin("2026-06-10", 9, 9, 20, hoy="2026-06-17")
    assert sumo and cur == 1 and mx == 9 and tot == 21


def test_last_day_corrupto_no_crashea():
    last, cur, mx, tot, sumo = G.registrar_checkin("basura", 4, 4, 4, hoy="2026-06-17")
    assert sumo and cur == 1


# ── construir_stats ───────────────────────────────────────────────────────────

def test_construir_stats_normaliza():
    animes = [{"estado_usuario": "completado", "capitulos": "12", "episodios_vistos": 0, "puntuacion": 8}]
    media = [{"tipo": "pelicula", "estado_usuario": "completado", "duracion": 120}]
    s = G.construir_stats(animes, media, {"max": 7, "actual": 2})
    assert s["total"] == 2 and s["completados"] == 2
    # 12 episodios de anime + 1 ítem (película) = 13 unidades unificadas
    assert s["episodios"] == 13 and s["puntuados"] == 1
    assert s["racha_max"] == 7
