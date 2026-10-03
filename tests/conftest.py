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

# ── Los tests NUNCA tocan la base de datos real ──────────────────────────────
# Incidente real (v2.12): `import launcher` (test_instalacion) hace
# os.environ.update(ANIME_DB_PATH=<carpeta del proyecto>/anime_tracker.db).
# Ejecutando test_validacion ANTES que test_instalacion, la limpieza de
# test_validacion (DELETE FROM animes…) se hizo sobre la lista real y la vació.
# Ahora todo arranca apuntando a una carpeta temporal y, antes de cada test, se
# comprueba que nada ha vuelto a apuntar a la BD del proyecto.
import tempfile  # noqa: E402

_BD_SEGURA = Path(tempfile.mkdtemp(prefix="miraru_tests_"))
os.environ.setdefault("ANIME_APP_DIR", str(_BD_SEGURA))
os.environ.setdefault("ANIME_DB_PATH", str(_BD_SEGURA / "anime_tracker.db"))


def _apunta_al_proyecto(ruta: str | None) -> bool:
    if not ruta:
        return True       # sin variable, database.py usaría la carpeta del proyecto
    try:
        return Path(ruta).resolve().is_relative_to(ROOT)
    except (OSError, ValueError):
        return False


@pytest.fixture(autouse=True)
def _nunca_la_bd_real():
    if (_apunta_al_proyecto(os.environ.get("ANIME_DB_PATH"))
            or _apunta_al_proyecto(os.environ.get("ANIME_APP_DIR"))):
        os.environ["ANIME_APP_DIR"] = str(_BD_SEGURA)
        os.environ["ANIME_DB_PATH"] = str(_BD_SEGURA / "anime_tracker.db")
        import database
        with database._pool_lock:
            for c in database._conn_pool:
                try:
                    c.close()
                except Exception:
                    pass
            database._conn_pool.clear()
        database.init_db()
    yield
    assert not _apunta_al_proyecto(os.environ.get("ANIME_DB_PATH")), \
        "Un test ha dejado ANIME_DB_PATH apuntando a la base de datos real"


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
