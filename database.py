"""
Base de datos SQLite local.
Toda la información de usuario se guarda aquí.
Google Sheets es sincronización opcional.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

# Rutas resueltas de forma lazy para que las env vars del launcher estén disponibles
def _get_db_path() -> Path:
    app_dir = Path(os.environ.get("ANIME_APP_DIR", Path(__file__).parent))
    return Path(os.environ.get("ANIME_DB_PATH", str(app_dir / "anime_tracker.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS historial (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL,
    estado  TEXT NOT NULL,
    fecha   TEXT NOT NULL,
    nota    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS animes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT UNIQUE NOT NULL,
    fuente         TEXT DEFAULT '',
    capitulos      TEXT DEFAULT '',
    imagen         TEXT DEFAULT '',
    genero         TEXT DEFAULT '',
    sinopsis       TEXT DEFAULT '',
    estado_anime   TEXT DEFAULT '',
    estado_usuario      TEXT DEFAULT 'pendiente',
    puntuacion          REAL,
    episodios_vistos    INTEGER DEFAULT 0,
    temporada           TEXT DEFAULT '',
    lista_personalizada TEXT DEFAULT 'principal',
    favorito            INTEGER DEFAULT 0,
    notif_activa        INTEGER DEFAULT 0,
    notas               TEXT DEFAULT '',
    fecha_inicio        TEXT DEFAULT '',
    fecha_fin           TEXT DEFAULT '',
    creado_en           TEXT DEFAULT (datetime('now'))
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        # WAL mode y synchronous=NORMAL — configurar una sola vez al iniciar
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        # Migraciones: añadir columnas nuevas si no existen (BD antigua)
        existing = [r[1] for r in conn.execute("PRAGMA table_info(animes)").fetchall()]
        for col, definition in [
            ("episodios_vistos",    "INTEGER DEFAULT 0"),
            ("notas",               "TEXT DEFAULT ''"),
            ("temporada",           "TEXT DEFAULT ''"),
            ("lista_personalizada", "TEXT DEFAULT 'principal'"),
            ("favorito",            "INTEGER DEFAULT 0"),
            ("notif_activa",        "INTEGER DEFAULT 0"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE animes ADD COLUMN {col} {definition}")


# ── Config ────────────────────────────────────────────────────────────────────

def get_config(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM config WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_config(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO config(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def is_configured() -> bool:
    """True si la BD está inicializada (siempre True tras init_db).
    Google Sheets es opcional — no bloquear la app si no está configurado."""
    return True

def sheets_configured() -> bool:
    """True solo si Google Sheets está configurado con credenciales válidas."""
    app_dir = Path(os.environ.get("ANIME_APP_DIR", Path(__file__).parent))
    return bool(
        get_config("spreadsheet_id") and
        (app_dir / "credentials.json").exists()
    )


# ── Animes CRUD ───────────────────────────────────────────────────────────────

def listar_animes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM animes ORDER BY creado_en DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def obtener_anime(nombre: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM animes WHERE nombre=?", (nombre,)
        ).fetchone()
        return dict(row) if row else None


def guardar_anime(data: dict) -> tuple[bool, str]:
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return False, "nombre vacío"
    genero = data.get("genero", [])
    if isinstance(genero, list):
        genero = ", ".join(genero)
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO animes
                   (nombre, fuente, capitulos, imagen, genero, sinopsis,
                    estado_anime, estado_usuario, puntuacion,
                    episodios_vistos, temporada, lista_personalizada,
                    favorito, notif_activa, notas, fecha_inicio, fecha_fin)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("nombre", ""),
                    data.get("fuente", ""),
                    str(data.get("capitulos", "")),
                    data.get("imagen", ""),
                    genero,
                    data.get("sinopsis", ""),
                    data.get("estado_anime", ""),
                    data.get("estado_usuario", "pendiente"),
                    data.get("puntuacion"),
                    data.get("episodios_vistos") or 0,
                    data.get("temporada", "") or "",
                    data.get("lista_personalizada", "principal") or "principal",
                    1 if data.get("favorito") else 0,
                    1 if data.get("notif_activa") else 0,
                    data.get("notas", "") or "",
                    data.get("fecha_inicio", "") or "",
                    data.get("fecha_fin", "") or "",
                ),
            )
        return True, "ok"
    except sqlite3.IntegrityError:
        return False, "duplicado"
    except Exception as e:
        return False, str(e)


def actualizar_anime(nombre: str, campos: dict) -> tuple[bool, str]:
    allowed = {"estado_usuario","puntuacion","fecha_inicio","fecha_fin","episodios_vistos","notas","temporada","lista_personalizada","favorito","notif_activa"}
    campos  = {k: v for k, v in campos.items() if k in allowed}
    if not campos:
        return False, "sin campos válidos"
    sets   = ", ".join(f"{k}=?" for k in campos)
    values = list(campos.values()) + [nombre]
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE animes SET {sets} WHERE nombre=?", values)
        if cur.rowcount == 0:
            return False, "no encontrado"
    # Registrar cambio de estado en historial
    if "estado_usuario" in campos:
        registrar_historial(nombre, campos["estado_usuario"])
    return True, "ok"


def eliminar_anime(nombre: str) -> tuple[bool, str]:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM animes WHERE nombre=?", (nombre,))
        if cur.rowcount == 0:
            return False, "no encontrado"
    return True, "ok"

def buscar_animes(query: str, limit: int = 20) -> list[dict]:
    """Búsqueda local rápida en la BD por nombre (parcial, case-insensitive)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM animes WHERE nombre LIKE ? ORDER BY creado_en DESC LIMIT ?",
            (f"%{query}%", limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_historial(nombre: str) -> list[dict]:
    """Devuelve el historial de cambios de estado de un anime."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT estado, fecha, nota FROM historial WHERE nombre=? ORDER BY fecha DESC",
            (nombre,)
        ).fetchall()
        return [dict(r) for r in rows]


def registrar_historial(nombre: str, estado: str, nota: str = ""):
    """Guarda un evento de cambio de estado en el historial."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO historial(nombre, estado, fecha, nota) VALUES(?,?,datetime('now'),?)",
                (nombre, estado, nota)
            )
    except Exception:
        pass  # historial es opcional, no crashear

# ── Listas personalizadas / Favoritos / Notificaciones ────────────────────────

def listar_listas() -> list[str]:
    """Listas personalizadas existentes."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT lista_personalizada FROM animes ORDER BY lista_personalizada"
        ).fetchall()
        return [r[0] for r in rows if r[0]]


def listar_favoritos() -> list[dict]:
    """Animes marcados como favoritos, ordenados por puntuación."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM animes WHERE favorito=1 ORDER BY puntuacion DESC, nombre"
        ).fetchall()
        return [dict(r) for r in rows]


def listar_con_notif() -> list[dict]:
    """Animes con notificación de nuevo episodio activa."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM animes WHERE notif_activa=1"
        ).fetchall()
        return [dict(r) for r in rows]


def listar_por_lista(lista: str) -> list[dict]:
    """Animes de una lista personalizada concreta."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM animes WHERE lista_personalizada=? ORDER BY creado_en DESC",
            (lista,)
        ).fetchall()
        return [dict(r) for r in rows]
