"""Tests de CRUD, migraciones, índices y borrado en cascada."""
from __future__ import annotations

import sqlite3


def test_init_creates_schema_and_indexes(db, app_dir):
    """init_db debe crear las tablas y los índices nuevos de v2."""
    con = sqlite3.connect(app_dir / "test.db")
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"animes", "config", "historial"} <= tables

    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()}
    assert {
        "idx_animes_lista",
        "idx_animes_favorito",
        "idx_animes_estado",
        "idx_hist_nombre",
    } <= idx


def test_get_config_many_batch(db):
    """get_config_many lee varias claves en una sola conexión y omite las ausentes."""
    db.set_config("a", "1")
    db.set_config("b", "2")
    out = db.get_config_many(["a", "b", "no_existe"])
    assert out == {"a": "1", "b": "2"}
    assert db.get_config_many([]) == {}


def test_guardar_y_obtener_anime(db):
    ok, msg = db.guardar_anime({
        "nombre": "Cowboy Bebop",
        "fuente": "anilist",
        "genero": ["Action", "Sci-Fi"],
        "capitulos": 26,
    })
    assert ok, msg
    a = db.obtener_anime("Cowboy Bebop")
    assert a is not None
    assert a["nombre"] == "Cowboy Bebop"
    assert a["fuente"] == "anilist"
    assert a["genero"] == "Action, Sci-Fi"
    assert a["lista_personalizada"] == "principal"  # default


def test_guardar_duplicado_devuelve_duplicado(db):
    ok, _ = db.guardar_anime({"nombre": "X"})
    assert ok
    ok, msg = db.guardar_anime({"nombre": "X"})
    assert not ok and msg == "duplicado"


def test_actualizar_anime_solo_campos_permitidos(db):
    db.guardar_anime({"nombre": "Y"})
    ok, _ = db.actualizar_anime("Y", {
        "estado_usuario": "viendo",
        "puntuacion": 9.5,
        "nombre": "INTENTO_RENOMBRAR",   # debe ignorarse
        "fuente": "INTENTO",              # idem
    })
    assert ok
    a = db.obtener_anime("Y")
    assert a["estado_usuario"] == "viendo"
    assert a["puntuacion"] == 9.5
    # No se renombró ni cambió fuente
    assert db.obtener_anime("INTENTO_RENOMBRAR") is None


def test_actualizar_inexistente(db):
    ok, msg = db.actualizar_anime("NoExiste", {"estado_usuario": "viendo"})
    assert not ok and msg == "no encontrado"


def test_cascade_delete_limpia_historial_y_tags(db):
    """v2: eliminar_anime borra historial y tags asociados."""
    db.guardar_anime({"nombre": "Z"})
    db.actualizar_anime("Z", {"estado_usuario": "viendo"})  # crea historial
    db.set_config("tags:Z", "shounen,ova")
    assert db.get_historial("Z"), "precondición: hay historial"
    assert db.get_config("tags:Z") == "shounen,ova"

    ok, _ = db.eliminar_anime("Z")
    assert ok
    assert db.obtener_anime("Z") is None
    assert db.get_historial("Z") == [], "historial NO limpiado tras delete"
    assert db.get_config("tags:Z") is None, "tags NO limpiados tras delete"


def test_listar_favoritos_ordena_por_puntuacion(db):
    db.guardar_anime({"nombre": "A"})
    db.guardar_anime({"nombre": "B"})
    db.guardar_anime({"nombre": "C"})
    db.actualizar_anime("A", {"favorito": 1, "puntuacion": 7.0})
    db.actualizar_anime("B", {"favorito": 1, "puntuacion": 9.5})
    db.actualizar_anime("C", {"favorito": 0, "puntuacion": 10.0})
    favs = db.listar_favoritos()
    assert [f["nombre"] for f in favs] == ["B", "A"]  # C excluido, B primero


def test_listar_por_lista(db):
    db.guardar_anime({"nombre": "P1"})
    db.guardar_anime({"nombre": "P2"})
    db.actualizar_anime("P2", {"lista_personalizada": "quiero_ver"})
    principal = db.listar_por_lista("principal")
    quiero = db.listar_por_lista("quiero_ver")
    assert {a["nombre"] for a in principal} == {"P1"}
    assert {a["nombre"] for a in quiero} == {"P2"}


def test_buscar_animes_parcial_case_insensitive(db):
    db.guardar_anime({"nombre": "Attack on Titan"})
    db.guardar_anime({"nombre": "One Piece"})
    res = db.buscar_animes("attack")
    assert len(res) == 1 and res[0]["nombre"] == "Attack on Titan"


def test_manga_volumenes_crud(db):
    """Guardar manga con volumenes_totales y actualizar volumenes_leidos."""
    db.guardar_anime({
        "nombre": "One Piece Manga",
        "tipo": "manga",
        "capitulos": "1120",
        "volumenes_totales": 109,
    })
    a = db.obtener_anime("One Piece Manga")
    assert a["tipo"] == "manga"
    assert a["volumenes_totales"] == 109
    assert a["volumenes_leidos"] == 0

    ok, _ = db.actualizar_anime("One Piece Manga", {"volumenes_leidos": 50})
    assert ok
    a = db.obtener_anime("One Piece Manga")
    assert a["volumenes_leidos"] == 50

    # refrescar_metadata puede actualizar volumenes_totales
    ok, _ = db.refrescar_metadata_anime("One Piece Manga", {"volumenes_totales": 110})
    assert ok
    a = db.obtener_anime("One Piece Manga")
    assert a["volumenes_totales"] == 110


def test_manga_volumenes_en_slim(db):
    """listar_animes_slim devuelve volumenes_totales y volumenes_leidos."""
    db.guardar_anime({
        "nombre": "Naruto Manga",
        "tipo": "manga",
        "volumenes_totales": 72,
        "volumenes_leidos": 30,
    })
    slim = db.listar_animes_slim()
    m = next(a for a in slim if a["nombre"] == "Naruto Manga")
    assert m["volumenes_totales"] == 72
    assert m["volumenes_leidos"] == 30


def test_config_set_get(db):
    assert db.get_config("noexiste") is None
    db.set_config("k", "v1")
    assert db.get_config("k") == "v1"
    db.set_config("k", "v2")
    assert db.get_config("k") == "v2"


def test_activar_wal_reintenta_si_la_bd_esta_bloqueada(monkeypatch):
    import database

    llamadas = {"n": 0}

    class Conn:
        def execute(self, sql):
            llamadas["n"] += 1
            if llamadas["n"] < 3:
                raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("time.sleep", lambda s: None)
    database._activar_wal(Conn())
    assert llamadas["n"] == 3
