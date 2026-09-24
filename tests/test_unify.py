"""
Tests de la unificación anime + media: stats globales y página compartible.
Módulos puros (stats_util, share_page) — no importan main.
"""
from __future__ import annotations

import share_page
import stats_util

# ── stats_util ────────────────────────────────────────────────────────────────

def test_anime_completado_cuenta_todos_los_caps():
    eps, mins = stats_util.anime_vistos(
        {"estado_usuario": "completado", "capitulos": "12", "episodios_vistos": 0})
    assert eps == 12 and mins == 12 * 24


def test_anime_viendo_cuenta_solo_vistos():
    eps, _ = stats_util.anime_vistos(
        {"estado_usuario": "viendo", "capitulos": "24", "episodios_vistos": 5})
    assert eps == 5


def test_anime_pelicula_completada_es_un_item():
    eps, mins = stats_util.anime_vistos({"estado_usuario": "completado", "capitulos": "película"})
    assert eps == 1 and mins == stats_util.MOVIE_MIN


def test_media_pelicula_usa_su_duracion_real():
    eps, mins = stats_util.media_vistos(
        {"tipo": "pelicula", "estado_usuario": "completado", "duracion": 148})
    assert eps == 1 and mins == 148


def test_media_serie_completada_cuenta_episodios():
    eps, mins = stats_util.media_vistos(
        {"tipo": "serie", "estado_usuario": "completado", "duracion": 8, "episodios_vistos": 0})
    assert eps == 8 and mins == 8 * 24


def test_stats_globales_combina_todo():
    animes = [
        {"estado_usuario": "completado", "capitulos": "12", "episodios_vistos": 0},
        {"estado_usuario": "viendo", "capitulos": "24", "episodios_vistos": 3},
    ]
    media = [
        {"tipo": "pelicula", "estado_usuario": "completado", "duracion": 120},
        {"tipo": "serie", "estado_usuario": "completado", "duracion": 10},
    ]
    s = stats_util.stats_globales(animes, media)
    assert s["total_titulos"] == 4
    assert s["animes"] == 2 and s["peliculas"] == 1 and s["series"] == 1
    assert s["episodios_anime"] == 12 + 3
    assert s["items_media"] == 1 + 10
    assert s["total_episodios"] == 26
    # horas: anime (15*24) + peli (120) + serie (10*24) = 360+120+240 = 720 min = 12h
    assert s["horas_totales"] == 12.0


def test_stats_globales_vacio_no_crashea():
    s = stats_util.stats_globales([], [])
    assert s["total_titulos"] == 0 and s["horas_totales"] == 0.0


# ── share_page ────────────────────────────────────────────────────────────────

def test_share_html_contiene_titulos_y_es_html():
    animes = [{"nombre": "Frieren", "capitulos": "28", "estado_usuario": "completado", "imagen": ""}]
    media = [{"titulo": "Inception", "tipo": "pelicula", "anio": "2010", "estado_usuario": "completado"}]
    out = share_page.render_share_html(animes, media, perfil={"nombre_usuario": "Lucas"})
    assert out.lstrip().startswith("<!DOCTYPE html>")
    assert "Frieren" in out and "Inception" in out
    assert "Lucas" in out
    assert "ANIME" in out and "PELÍCULA" in out


def test_share_html_escapa_contenido_malicioso():
    out = share_page.render_share_html(
        [{"nombre": "<script>alert(1)</script>", "capitulos": "1", "imagen": ""}], [])
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
