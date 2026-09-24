"""
`get_conn()` no debe dejar conexiones abiertas.

`with sqlite3.Connection` NO cierra la conexión: solo abre una transacción y
hace commit o rollback al salir. Como `get_conn()` devolvía la conexión cruda,
cada uno de sus 32 puntos de uso dejaba un fichero abierto. En un servidor que
está horas encendido eso son cientos de descriptores colgando, y con WAL cada
conexión mantiene además su vista del `-shm`/`-wal`.

Se mide con el recolector de basura en vez de con descriptores del sistema
operativo, que no son portables.
"""
from __future__ import annotations

import gc
import os
import sqlite3
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="miraru_conn_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "conn.db")

import database as db  # noqa: E402


def conexiones_vivas() -> int:
    """Conexiones sqlite que siguen utilizables (no cerradas)."""
    gc.collect()
    vivas = 0
    for obj in gc.get_objects():
        if isinstance(obj, sqlite3.Connection):
            try:
                obj.execute("SELECT 1")
                vivas += 1
            except sqlite3.ProgrammingError:
                pass        # ya cerrada, que es lo que queremos
            except Exception:
                pass
    return vivas


@pytest.fixture(autouse=True)
def bd():
    db.init_db()
    yield


def test_get_conn_cierra_al_salir_del_with():
    antes = conexiones_vivas()
    for _ in range(25):
        with db.get_conn() as conn:
            conn.execute("SELECT COUNT(*) FROM animes").fetchone()
    despues = conexiones_vivas()
    assert despues <= antes, (
        f"quedaron {despues - antes} conexiones abiertas tras 25 usos"
    )


def test_get_conn_cierra_tambien_si_hay_excepcion():
    antes = conexiones_vivas()
    for _ in range(10):
        with pytest.raises(sqlite3.OperationalError), db.get_conn() as conn:
            conn.execute("SELECT * FROM tabla_que_no_existe")
    despues = conexiones_vivas()
    assert despues <= antes, (
        f"quedaron {despues - antes} conexiones abiertas tras 10 errores"
    )


def test_los_cambios_se_confirman_al_salir():
    """Cerrar no puede llevarse por delante el commit."""
    db.set_config("prueba_commit", "valor")
    assert db.get_config("prueba_commit") == "valor"


def test_una_excepcion_deshace_los_cambios():
    """La transacción debe seguir funcionando: rollback al fallar."""
    db.set_config("prueba_rollback", "original")
    with pytest.raises(sqlite3.OperationalError), db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?,?)",
            ("prueba_rollback", "cambiado"))
        conn.execute("SELECT * FROM tabla_que_no_existe")
    assert db.get_config("prueba_rollback") == "original"


def test_las_operaciones_normales_siguen_funcionando():
    """Prueba de humo: el cambio no puede romper el uso corriente."""
    ok, _ = db.guardar_anime({
        "nombre": "Prueba Conexiones", "fuente": "test", "capitulos": "12",
        "imagen": "", "genero": "Action", "sinopsis": "", "estado_anime": "Finalizado",
    })
    assert ok
    assert db.obtener_anime("Prueba Conexiones") is not None
    assert any(a["nombre"] == "Prueba Conexiones" for a in db.listar_animes())
    db.eliminar_anime("Prueba Conexiones")
    assert db.obtener_anime("Prueba Conexiones") is None
