"""Tests de la tabla ep_log de v2.2 (heatmap, streak, total, cascade delete)."""
from __future__ import annotations

import datetime as dt


def test_log_episode_basico(db):
    db.guardar_anime({"nombre": "A"})
    db.log_episode("A", 1)
    db.log_episode("A", 2)
    db.log_episode("A", 3)
    hm = db.ep_log_heatmap(30)
    # Mismo día → todas las entradas suman al count del día
    assert len(hm) == 1
    assert hm[0]["count"] == 3
    assert db.ep_log_total() == 3


def test_log_episode_idempotente(db):
    """Re-loggear el mismo ep no duplica (UNIQUE)."""
    db.guardar_anime({"nombre": "X"})
    db.log_episode("X", 5)
    db.log_episode("X", 5)
    db.log_episode("X", 5)
    assert db.ep_log_total() == 1


def test_log_episode_ignora_vacio_y_negativo(db):
    db.log_episode("", 1)
    db.log_episode("X", 0)
    db.log_episode("X", -3)
    assert db.ep_log_total() == 0


def test_heatmap_filtra_por_dias(db):
    """ep_log_heatmap(dias) solo devuelve los últimos N días."""
    db.guardar_anime({"nombre": "Y"})
    db.log_episode("Y", 1)
    # Hay actividad hoy → debe aparecer
    hm = db.ep_log_heatmap(1)
    assert len(hm) >= 1
    # 0 días no devuelve nada
    hm0 = db.ep_log_heatmap(0)
    assert hm0 == []


def test_total_por_rango(db):
    db.guardar_anime({"nombre": "Z"})
    for ep in range(1, 6):
        db.log_episode("Z", ep)
    assert db.ep_log_total() == 5
    assert db.ep_log_total(365) == 5
    # v2.2: dias <= 0 devuelve 0 explícitamente
    assert db.ep_log_total(0) == 0
    assert db.ep_log_total(-1) == 0


def test_cascade_delete_borra_eplog(db):
    """v2.2: eliminar el anime borra también su ep_log."""
    db.guardar_anime({"nombre": "Borrame"})
    db.log_episode("Borrame", 1)
    db.log_episode("Borrame", 2)
    assert db.ep_log_total() == 2
    db.eliminar_anime("Borrame")
    assert db.ep_log_total() == 0


def test_ep_log_spans_basico(db):
    """v2.4: ep_log_spans agrupa por anime con primer/último día y nº de eps."""
    db.guardar_anime({"nombre": "Span"})
    for ep in range(1, 6):
        db.log_episode("Span", ep)
    spans = db.ep_log_spans(min_eps=2)
    assert len(spans) == 1
    s = spans[0]
    assert s["nombre"] == "Span"
    assert s["episodios"] == 5
    assert s["dias"] == 0  # todos el mismo día
    assert s["primer"] == s["ultimo"]


def test_ep_log_spans_respeta_min_eps(db):
    """Animes con menos eps que min_eps quedan fuera."""
    db.guardar_anime({"nombre": "Uno"})
    db.log_episode("Uno", 1)
    assert db.ep_log_spans(min_eps=2) == []
    assert len(db.ep_log_spans(min_eps=1)) == 1


def test_streak_sin_actividad(db):
    s = db.ep_log_streak()
    assert s == {"actual": 0, "max": 0, "ultimo_dia": None}


def test_streak_solo_hoy(db):
    """Una sola entrada hoy = racha de 1."""
    db.guardar_anime({"nombre": "S"})
    db.log_episode("S", 1)
    s = db.ep_log_streak()
    assert s["actual"] >= 1
    assert s["max"] >= 1
    assert s["ultimo_dia"] == dt.date.today().isoformat()


def test_heatmap_indices_se_crearon(db, app_dir):
    """v2.2: los índices nuevos de ep_log existen tras init_db."""
    import sqlite3
    con = sqlite3.connect(app_dir / "test.db")
    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_eplog%'"
    ).fetchall()}
    assert {"idx_eplog_nombre", "idx_eplog_fecha"} <= idx
