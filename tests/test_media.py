"""Tests de la tabla media (películas/series no-anime, v6)."""
from __future__ import annotations

import sqlite3


def test_media_table_and_indexes(db, app_dir):
    """init_db debe crear la tabla media y sus índices."""
    con = sqlite3.connect(app_dir / "test.db")
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "media" in tables

    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_media%'"
    ).fetchall()}
    assert {"idx_media_tipo", "idx_media_estado"} <= idx


def test_schema_version_is_7(db, app_dir):
    con = sqlite3.connect(app_dir / "test.db")
    v = con.execute("PRAGMA user_version").fetchone()[0]
    assert v == 7


def test_guardar_y_listar_media(db):
    ok, msg = db.guardar_media({
        "titulo": "Origen", "tipo": "pelicula", "tmdb_id": 27205,
        "genero": ["Acción", "Ciencia ficción"], "anio": "2010",
        "duracion": 148, "estado_media": "Released", "puntuacion_tmdb": 8.4,
    })
    assert ok, msg
    items = db.listar_media()
    assert len(items) == 1
    assert items[0]["titulo"] == "Origen"
    assert items[0]["tipo"] == "pelicula"
    assert items[0]["duracion"] == 148
    # género se serializa a JSON
    assert "Acción" in items[0]["genero"]
    # estado por defecto
    assert items[0]["estado_usuario"] == "pendiente"


def test_media_no_duplicados(db):
    data = {"titulo": "Breaking Bad", "tipo": "serie", "tmdb_id": 1396}
    ok1, _ = db.guardar_media(data)
    ok2, msg2 = db.guardar_media(data)
    assert ok1 is True
    assert ok2 is False
    assert msg2 == "duplicado"


def test_misma_titulo_distinto_tipo_permitido(db):
    """Una peli y una serie con el mismo título pueden coexistir."""
    ok1, _ = db.guardar_media({"titulo": "Fargo", "tipo": "pelicula"})
    ok2, _ = db.guardar_media({"titulo": "Fargo", "tipo": "serie"})
    assert ok1 and ok2
    assert len(db.listar_media()) == 2


def test_actualizar_media(db):
    db.guardar_media({"titulo": "Dune", "tipo": "pelicula"})
    mid = db.listar_media()[0]["id"]
    ok, _ = db.actualizar_media(mid, {"estado_usuario": "completado", "puntuacion": 9.0})
    assert ok
    item = db.obtener_media(mid)
    assert item["estado_usuario"] == "completado"
    assert item["puntuacion"] == 9.0


def test_actualizar_media_rechaza_campos_no_permitidos(db):
    db.guardar_media({"titulo": "Tenet", "tipo": "pelicula"})
    mid = db.listar_media()[0]["id"]
    # tmdb_id no está en la whitelist → no debe colarse
    ok, _ = db.actualizar_media(mid, {"tmdb_id": 999})
    assert ok is False


def test_eliminar_media(db):
    db.guardar_media({"titulo": "Sicario", "tipo": "pelicula"})
    mid = db.listar_media()[0]["id"]
    ok, _ = db.eliminar_media(mid)
    assert ok
    assert db.listar_media() == []
    # eliminar de nuevo → no encontrado
    ok2, msg2 = db.eliminar_media(mid)
    assert ok2 is False


def test_media_cache_se_invalida(db):
    db.guardar_media({"titulo": "Arrival", "tipo": "pelicula"})
    l1 = db.listar_media()
    l2 = db.listar_media()
    assert l1 is l2  # cacheado
    db.guardar_media({"titulo": "Gravity", "tipo": "pelicula"})
    l3 = db.listar_media()
    assert l3 is not l1  # invalidado
    assert len(l3) == 2


def test_media_rewatches_whitelist(db):
    """rewatches debe poder actualizarse (está en la whitelist v7)."""
    db.guardar_media({"titulo": "Interstellar", "tipo": "pelicula"})
    mid = db.listar_media()[0]["id"]
    ok, _ = db.actualizar_media(mid, {"rewatches": 4})
    assert ok
    assert db.obtener_media(mid)["rewatches"] == 4


def test_media_schema_version_7(db, app_dir):
    import sqlite3
    con = sqlite3.connect(app_dir / "test.db")
    v = con.execute("PRAGMA user_version").fetchone()[0]
    assert v == 7
    cols = [r[1] for r in con.execute("PRAGMA table_info(media)").fetchall()]
    assert "rewatches" in cols
