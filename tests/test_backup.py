"""
La copia de seguridad no puede perder los cambios recientes.

La BD va en modo WAL: las transacciones confirmadas se escriben primero en el
fichero `-wal` y solo pasan al `.db` principal cuando hay un checkpoint. El
backup copiaba el `.db` a pelo con `zipfile.write()`, así que se llevaba una
foto SIN lo último — potencialmente horas de cambios— y encima podía quedar
inconsistente si pillaba un checkpoint a medias.

Es el peor tipo de fallo: silencioso, y solo se descubre el día que necesitas
restaurar. La solución es la API de backup en línea de SQLite, que sí tiene en
cuenta el WAL.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="miraru_backup_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "bk.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import database as db  # noqa: E402
import main  # noqa: E402


@pytest.fixture
def client():
    db.drain_pool()          # descartar conexiones de tests anteriores (otro DB path)
    db.init_db()
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c
    with db.get_conn() as conn:
        conn.execute("DELETE FROM animes")
    db.drain_pool()


def test_el_wal_esta_activo():
    """Si esto cambiara, el resto del fichero deja de tener sentido.

    Hace falta init_db(): el WAL se activa ahí, no al abrir una conexión.
    """
    db.init_db()
    with db.get_conn() as conn:
        modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert modo.lower() == "wal"


def _backup_dir() -> Path:
    """Directorio de backups activo en este momento (puede diferir de _TMP si
    otro módulo de test sobreescribió ANIME_APP_DIR en os.environ antes de que
    pytest importase este archivo)."""
    return Path(os.environ.get("ANIME_APP_DIR", _TMP)) / "backups"


def test_el_backup_incluye_lo_escrito_justo_antes(client):
    """El caso que rompía: guardar y hacer backup sin checkpoint de por medio."""
    db.guardar_anime({
        "nombre": "Recien Anadido", "fuente": "test", "capitulos": "12",
        "imagen": "", "genero": "Action", "sinopsis": "", "estado_anime": "Finalizado",
    })

    r = client.post("/api/backup")
    assert r.status_code == 200
    nombre = r.json()["archivo"]

    zip_path = _backup_dir() / nombre
    assert zip_path.exists()

    # Extraer la BD del zip y comprobar que el anime está
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extract("anime_tracker.db", tmp)
        copia = sqlite3.connect(os.path.join(tmp, "anime_tracker.db"))
        nombres = [r[0] for r in copia.execute("SELECT nombre FROM animes")]
        copia.close()

    assert "Recien Anadido" in nombres, (
        "la copia de seguridad NO contiene el anime guardado justo antes; "
        "se está copiando el .db sin el contenido del WAL"
    )


def test_el_backup_es_una_base_de_datos_integra(client):
    db.guardar_anime({
        "nombre": "Integridad", "fuente": "test", "capitulos": "1",
        "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "Finalizado",
    })
    nombre = client.post("/api/backup").json()["archivo"]
    zip_path = _backup_dir() / nombre

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extract("anime_tracker.db", tmp)
        copia = sqlite3.connect(os.path.join(tmp, "anime_tracker.db"))
        assert copia.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        copia.close()


def test_auto_backup_disco_incluye_wal(client):
    """Regresión: _crear_backup_disco usaba z.write(db_path) directo y perdía el WAL.

    El auto-backup diario debe usar la API de backup en línea de SQLite igual
    que el endpoint /api/backup, para garantizar que los datos recientes (aún
    en el fichero -wal) estén en la copia.
    """
    db.guardar_anime({
        "nombre": "Guardado Para AutoBackup", "fuente": "test", "capitulos": "12",
        "imagen": "", "genero": "Action", "sinopsis": "", "estado_anime": "Finalizado",
    })

    # Llamar directamente a la función interna de auto-backup
    import main as m
    nombre = m._crear_backup_disco(retencion=10)
    assert nombre is not None, "_crear_backup_disco devolvió None"

    zip_path = _backup_dir() / nombre
    assert zip_path.exists(), f"El ZIP no existe: {zip_path}"

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extract("anime_tracker.db", tmp)
        copia = sqlite3.connect(os.path.join(tmp, "anime_tracker.db"))
        nombres = [r[0] for r in copia.execute("SELECT nombre FROM animes")]
        copia.close()

    assert "Guardado Para AutoBackup" in nombres, (
        "_crear_backup_disco no incluye datos del WAL: "
        "usa z.write(db_path) directo en lugar de sqlite3.backup()"
    )


def test_el_backup_no_lleva_credenciales_por_defecto(client):
    """Regresión: subir el zip a la nube no debe filtrar credentials.json."""
    # El credentials.json debe estar en el mismo directorio que la BD activa
    app_dir = Path(os.environ.get("ANIME_APP_DIR", _TMP))
    creds = app_dir / "credentials.json"
    creds.write_text('{"secreto": "no-deberia-salir"}', encoding="utf-8")
    try:
        nombre = client.post("/api/backup").json()["archivo"]
        with zipfile.ZipFile(_backup_dir() / nombre) as z:
            assert "credentials.json" not in z.namelist()
    finally:
        creds.unlink(missing_ok=True)
