"""
Fixtures comunes para los tests.

Cada test recibe una BD SQLite aislada en tmp_path y se sobrescriben las
env vars que database.py y main.py leen para localizar el fichero.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """Directorio aislado de la app — DB y avatars viven aquí."""
    monkeypatch.setenv("ANIME_APP_DIR", str(tmp_path))
    monkeypatch.setenv("ANIME_FROZEN_DIR", str(ROOT))
    monkeypatch.setenv("ANIME_DB_PATH", str(tmp_path / "test.db"))
    return tmp_path


@pytest.fixture
def db(app_dir):
    """database.py recargado con la BD aislada inicializada."""
    import database
    importlib.reload(database)
    database.init_db()
    return database


@pytest.fixture(autouse=True)
def _vaciar_pool_bd():
    """database guarda conexiones en un pool. Si un test cambia la ruta de la
    BD (fixture `db`) y otro usa otra, el pool podía devolver una conexión a
    la BD del test anterior → "no such table". En la app real la ruta no
    cambia; esto solo aísla los tests entre sí."""
    yield
    import database
    with database._pool_lock:
        for c in database._conn_pool:
            try:
                c.close()
            except Exception:
                pass
        database._conn_pool.clear()
