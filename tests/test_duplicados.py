"""
Duplicados por diferencias de mayúsculas/signos ("One Punch Man" vs
"One-Punch Man") y fusión de pares existentes sin perder progreso.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("a, b", [
    ("One Punch Man", "One-Punch Man"),
    ("Spy x Family", "SPY x FAMILY"),
    ("Haikyuu!!: Riku vs Kuu", "Haikyuu!!: Riku vs. Kuu"),
    ("Ore dake Level Up na Ken: Season 2 - Arise from the Shadow",
     "Ore dake Level Up na Ken Season 2: Arise from the Shadow"),
])
def test_clave_nombre_iguala_variantes(db, a, b):
    assert db.clave_nombre(a) == db.clave_nombre(b)


@pytest.mark.parametrize("a, b", [
    ("Date A Live", "Date A Live Ⅲ"),
    ("Haikyuu!!", "Haikyuu!! Second Season"),
    ("Kaguya-sama", "Kaguya-sama 2"),
])
def test_clave_nombre_distingue_temporadas(db, a, b):
    assert db.clave_nombre(a) != db.clave_nombre(b)


def test_guardar_rechaza_duplicado_normalizado(db):
    assert db.guardar_anime({"nombre": "One Punch Man"}) == (True, "ok")
    assert db.guardar_anime({"nombre": "one-punch man"}) == (False, "duplicado")
    assert db.guardar_anime({"nombre": "One Punch Man 2nd Season"}) == (True, "ok")


def test_buscar_duplicados(db):
    db.guardar_anime({"nombre": "Spy x Family"})
    db.guardar_anime({"nombre": "Otro"})
    with db.get_conn() as c:   # simular BD antigua con duplicado ya dentro
        c.execute("INSERT INTO animes (nombre) VALUES ('SPY x FAMILY')")
    assert db.buscar_duplicados() == [["Spy x Family", "SPY x FAMILY"]]


def test_fusionar_conserva_mejor_progreso_y_referencias(db):
    db.guardar_anime({"nombre": "A", "estado_usuario": "pendiente", "notas": "nota A",
                      "episodios_vistos": 3})
    with db.get_conn() as c:
        c.execute("INSERT INTO animes (nombre, estado_usuario, episodios_vistos, puntuacion,"
                  " favorito, notas, fecha_inicio) VALUES ('a', 'completado', 12, 9, 1,"
                  " 'nota B', '2024-01-01')")
        c.execute("INSERT INTO historial (nombre, estado, fecha) VALUES ('a', 'completado', '2024')")
        c.execute("INSERT INTO ep_log (nombre, episodio) VALUES ('a', 5)")
        c.execute("INSERT INTO ep_log (nombre, episodio) VALUES ('A', 5)")
        c.execute("INSERT INTO config (key, value) VALUES ('tags:a', 'top,rewatch')")
        c.execute("INSERT INTO config (key, value) VALUES ('tags:A', 'top')")
    assert db.fusionar_animes("A", "a") == (True, "ok")
    r = db.obtener_anime("A")
    assert r["estado_usuario"] == "completado" and r["episodios_vistos"] == 12
    assert r["puntuacion"] == 9 and r["favorito"] == 1
    assert "nota A" in r["notas"] and "nota B" in r["notas"]
    assert r["fecha_inicio"] == "2024-01-01"
    assert db.obtener_anime("a") is None
    with db.get_conn() as c:
        assert c.execute("SELECT count(*) FROM historial WHERE nombre='A'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM ep_log WHERE nombre='A'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM ep_log WHERE nombre='a'").fetchone()[0] == 0
        assert c.execute("SELECT value FROM config WHERE key='tags:A'").fetchone()[0] == "top,rewatch"
        assert c.execute("SELECT count(*) FROM config WHERE key='tags:a'").fetchone()[0] == 0


def test_fusionar_no_empeora_el_conservado(db):
    db.guardar_anime({"nombre": "X", "estado_usuario": "completado", "episodios_vistos": 12})
    with db.get_conn() as c:
        c.execute("INSERT INTO animes (nombre, estado_usuario, episodios_vistos) VALUES ('x', 'pendiente', 0)")
    db.fusionar_animes("X", "x")
    r = db.obtener_anime("X")
    assert r["estado_usuario"] == "completado" and r["episodios_vistos"] == 12


def test_fusionar_errores(db):
    assert db.fusionar_animes("Z", "Z") == (False, "mismo anime")
    assert db.fusionar_animes("Z", "Y") == (False, "no encontrado")
