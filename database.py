"""
Base de datos SQLite local.
Toda la información de usuario se guarda aquí.
Google Sheets es sincronización opcional.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# ── Caché en memoria de listar_animes() ─────────────────────────────────────────
# listar_animes() se llama ~15 veces por render (stats, recomendaciones, perfil,
# wrapped...). Cachear la lista completa e invalidar en cada mutación evita releer
# toda la tabla repetidamente. Thread-safe porque los endpoints corren en el
# executor y el middleware en el event loop.
_lista_cache: Optional[list[dict]] = None
_lista_cache_lock = threading.Lock()

def _invalidar_cache() -> None:
    global _lista_cache, _slim_cache
    with _lista_cache_lock:
        _lista_cache = None
        _slim_cache = None

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
CREATE TABLE IF NOT EXISTS ep_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL,
    episodio  INTEGER NOT NULL,
    fecha     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(nombre, episodio)
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
CREATE TABLE IF NOT EXISTS episode_notes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL,
    episodio  INTEGER NOT NULL,
    nota      TEXT NOT NULL DEFAULT '',
    fecha     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(nombre, episodio)
);
CREATE TABLE IF NOT EXISTS media (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo          TEXT NOT NULL,
    tipo            TEXT NOT NULL DEFAULT 'pelicula',
    tmdb_id         INTEGER DEFAULT 0,
    imagen          TEXT DEFAULT '',
    sinopsis        TEXT DEFAULT '',
    genero          TEXT DEFAULT '',
    anio            TEXT DEFAULT '',
    duracion        INTEGER DEFAULT 0,
    temporadas      INTEGER DEFAULT 0,
    estado_media    TEXT DEFAULT '',
    estado_usuario  TEXT DEFAULT 'pendiente',
    puntuacion      REAL,
    puntuacion_tmdb REAL DEFAULT 0,
    episodios_vistos INTEGER DEFAULT 0,
    favorito        INTEGER DEFAULT 0,
    rewatches       INTEGER DEFAULT 0,
    notas           TEXT DEFAULT '',
    creado_en       TEXT DEFAULT (datetime('now')),
    UNIQUE(titulo, tipo)
);
"""


@contextmanager
def get_conn():
    """Conexión a la BD que se cierra sola al salir del `with`.

    Antes devolvía la conexión cruda. El detalle que se escapaba: en sqlite3,
    `with conexion:` NO cierra nada — solo abre una transacción y hace commit o
    rollback al salir. Así que cada uno de los 32 puntos de uso dejaba un
    fichero abierto para siempre. En un servidor encendido durante horas eso son
    cientos de descriptores colgando, y con WAL cada conexión mantiene además su
    propia vista de los ficheros -wal y -shm.

    Se conserva la semántica transaccional (el `with conn` de dentro), así que
    quien la usa no cambia: `with get_conn() as conn:` sigue funcionando igual.
    """
    conn = _get_pooled_conn()
    try:
        with conn:              # commit al salir bien, rollback si hay excepción
            yield conn
    finally:
        _return_conn(conn)


# ── Pool de conexiones ────────────────────────────────────────────────────────
# Reutilizar conexiones evita el overhead de abrir/cerrar SQLite en cada request.
_conn_pool: list[sqlite3.Connection] = []
_pool_lock = threading.Lock()
_POOL_MAX = 4


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")   # 8 MB de cache por conexión
    conn.execute("PRAGMA mmap_size=67108864")  # 64 MB mmap — lectura más rápida
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _get_pooled_conn() -> sqlite3.Connection:
    with _pool_lock:
        if _conn_pool:
            return _conn_pool.pop()
    return _make_conn()


def _return_conn(conn: sqlite3.Connection):
    with _pool_lock:
        if len(_conn_pool) < _POOL_MAX:
            _conn_pool.append(conn)
            return
    conn.close()


def drain_pool():
    """Cierra y descarta todas las conexiones del pool.

    Necesario en tests que cambian ANIME_DB_PATH entre módulos: las conexiones
    cacheadas apuntan al fichero antiguo y no verían la nueva BD.
    """
    with _pool_lock:
        while _conn_pool:
            _conn_pool.pop().close()


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
        # v2: índices para acelerar filtros frecuentes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_animes_lista    ON animes(lista_personalizada)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_animes_favorito ON animes(favorito)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_animes_estado   ON animes(estado_usuario)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_nombre     ON historial(nombre)")
        # v2.2: índices para ep_log (consultas por anime y por fecha para heatmap)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eplog_nombre    ON ep_log(nombre)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eplog_fecha     ON ep_log(fecha)")
        # v6: tabla media (películas y series no-anime, vía TMDB)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tipo      ON media(tipo)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_estado    ON media(estado_usuario)")
        # v7: migración de columnas nuevas en media (rewatches, fechas)
        media_cols = [r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()]
        for col, definition in [
            ("rewatches",    "INTEGER DEFAULT 0"),
            ("fecha_inicio", "TEXT DEFAULT ''"),
            ("fecha_fin",    "TEXT DEFAULT ''"),
        ]:
            if col not in media_cols:
                conn.execute(f"ALTER TABLE media ADD COLUMN {col} {definition}")

        conn.execute("PRAGMA user_version = 7")  # v7: media rewatches/fechas

# ── Config ────────────────────────────────────────────────────────────────────

def get_config(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM config WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None


def get_config_many(keys: list[str]) -> dict:
    """Lee varias claves de config en UNA sola conexión (evita abrir una por
    clave). Devuelve {key: value} solo con las que existen."""
    keys = list(keys or [])
    if not keys:
        return {}
    placeholders = ",".join("?" * len(keys))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT key, value FROM config WHERE key IN ({placeholders})", tuple(keys)
        ).fetchall()
    return {r["key"]: r["value"] for r in rows}


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


# ── Animes CRUD ───────────────────────────────────────────────────────────────

def listar_animes() -> list[dict]:
    global _lista_cache
    with _lista_cache_lock:
        if _lista_cache is not None:
            return _lista_cache
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM animes ORDER BY creado_en DESC"
        ).fetchall()
        result = [dict(r) for r in rows]
    with _lista_cache_lock:
        _lista_cache = result
    return result


# Columnas que el grid necesita (sin sinopsis, notas y campos pesados)
_SLIM_COLS = (
    "id, nombre, fuente, capitulos, imagen, genero, estado_anime, "
    "estado_usuario, puntuacion, episodios_vistos, temporada, "
    "lista_personalizada, favorito, notif_activa, fecha_inicio, fecha_fin"
)
_slim_cache: Optional[list[dict]] = None


def listar_animes_slim() -> list[dict]:
    """Versión ligera para el grid — excluye sinopsis y notas."""
    global _slim_cache
    with _lista_cache_lock:
        if _slim_cache is not None:
            return _slim_cache
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_SLIM_COLS} FROM animes ORDER BY creado_en DESC"
        ).fetchall()
        result = [dict(r) for r in rows]
    with _lista_cache_lock:
        _slim_cache = result
    return result


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
        _invalidar_cache()
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
    _invalidar_cache()
    # Registrar cambio de estado en historial
    if "estado_usuario" in campos:
        registrar_historial(nombre, campos["estado_usuario"])
    return True, "ok"


def refrescar_metadata_anime(nombre: str, campos: dict) -> tuple[bool, str]:
    """Como actualizar_anime pero para campos de la FUENTE (no del usuario).
    Permite refrescar capitulos/imagen/sinopsis/genero/estado_anime sin tocar
    el progreso del usuario (estado_usuario, puntuacion, episodios_vistos, etc.)."""
    allowed = {"capitulos", "imagen", "sinopsis", "genero", "estado_anime", "fuente"}
    campos = {k: v for k, v in campos.items() if k in allowed}
    if not campos:
        return False, "sin campos válidos"
    sets   = ", ".join(f"{k}=?" for k in campos)
    values = list(campos.values()) + [nombre]
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE animes SET {sets} WHERE nombre=?", values)
        if cur.rowcount == 0:
            return False, "no encontrado"
    _invalidar_cache()
    return True, "ok"


def eliminar_anime(nombre: str) -> tuple[bool, str]:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM animes WHERE nombre=?", (nombre,))
        if cur.rowcount == 0:
            return False, "no encontrado"
        # Limpiar datos derivados del anime — historial, tags y ep_log.
        # (No hay FK CASCADE porque historial/ep_log guardan por nombre y los
        # tags viven en la tabla config con prefijo "tags:{nombre}")
        conn.execute("DELETE FROM historial WHERE nombre=?", (nombre,))
        conn.execute("DELETE FROM ep_log    WHERE nombre=?", (nombre,))
        conn.execute("DELETE FROM config    WHERE key=?",    (f"tags:{nombre}",))
    _invalidar_cache()
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
                # localtime por coherencia con ep_log y con el wrapped por año
                "INSERT INTO historial(nombre, estado, fecha, nota) VALUES(?,?,datetime('now','localtime'),?)",
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


# ── Episode log (v2.2) ────────────────────────────────────────────────────────
# Cada vez que el usuario marca "+1 episodio" guardamos (anime, episodio, fecha)
# para poder pintar el heatmap, calcular streaks y derivar wrapped real.

def log_episode(nombre: str, episodio: int):
    """Registra que el usuario vio el episodio N del anime. Idempotente: si ya
    está registrado (UNIQUE), lo ignora — no actualizamos la fecha porque la
    primera vez es la que importa para el heatmap."""
    if not nombre or episodio <= 0:
        return
    try:
        with get_conn() as conn:
            conn.execute(
                # 'localtime': el resto de la app (rachas, heatmap, wrapped)
                # compara con date.today(), que es LOCAL. Guardar en UTC hacía
                # que lo visto de noche contara como el día anterior y rompiera
                # la racha sin motivo.
                "INSERT OR IGNORE INTO ep_log(nombre, episodio, fecha) "
                "VALUES(?, ?, datetime('now','localtime'))",
                (nombre, episodio),
            )
    except Exception:
        pass  # no crashear por logs


def ep_log_heatmap(dias: int = 365) -> list[dict]:
    """Devuelve [{fecha: 'YYYY-MM-DD', count: N}, ...] para los últimos N días.
    Solo días con actividad — el frontend rellena los huecos. `dias<=0` → []."""
    dias = int(dias)
    if dias <= 0:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date(fecha) AS d, COUNT(*) AS c "
            "FROM ep_log "
            "WHERE fecha >= datetime('now','localtime', ?) "
            "GROUP BY d "
            "ORDER BY d",
            (f"-{dias} days",),
        ).fetchall()
        return [{"fecha": r["d"], "count": r["c"]} for r in rows]


def ep_log_streak() -> dict:
    """Calcula racha actual y la más larga en días con al menos 1 ep visto."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date(fecha) AS d FROM ep_log ORDER BY d DESC"
        ).fetchall()
    if not rows:
        return {"actual": 0, "max": 0, "ultimo_dia": None}
    import datetime as _dt
    days = [_dt.date.fromisoformat(r["d"]) for r in rows]
    today = _dt.date.today()
    # Racha actual: días consecutivos terminando en hoy o ayer
    actual = 0
    if days[0] in (today, today - _dt.timedelta(days=1)):
        actual = 1
        prev = days[0]
        for d in days[1:]:
            if (prev - d).days == 1:
                actual += 1
                prev = d
            else:
                break
    # Racha máxima: iterar todo
    max_streak = 1
    cur = 1
    for i in range(1, len(days)):
        if (days[i - 1] - days[i]).days == 1:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 1
    return {"actual": actual, "max": max_streak, "ultimo_dia": days[0].isoformat()}


def ep_log_spans(min_eps: int = 2) -> list[dict]:
    """Para cada anime con al menos `min_eps` episodios loggeados, devuelve el
    primer y último día de visionado y cuántos episodios se vieron. Sirve para
    calcular 'cuánto tardaste en completar X'. Ordenado por días descendente."""
    min_eps = max(1, int(min_eps))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT nombre, MIN(date(fecha)) AS primer, MAX(date(fecha)) AS ultimo, "
            "COUNT(*) AS c "
            "FROM ep_log GROUP BY nombre HAVING c >= ?",
            (min_eps,),
        ).fetchall()
    import datetime as _dt
    out = []
    for r in rows:
        try:
            d0 = _dt.date.fromisoformat(r["primer"])
            d1 = _dt.date.fromisoformat(r["ultimo"])
            dias = (d1 - d0).days
        except (ValueError, TypeError):
            dias = 0
        out.append({
            "nombre": r["nombre"], "primer": r["primer"], "ultimo": r["ultimo"],
            "episodios": int(r["c"] or 0), "dias": dias,
        })
    out.sort(key=lambda x: -x["dias"])
    return out


def ep_log_total(dias: Optional[int] = None) -> int:
    """Total de episodios vistos (loggeados) en los últimos N días (o todos)."""
    if dias is not None and int(dias) <= 0:
        return 0
    with get_conn() as conn:
        if dias is None:
            row = conn.execute("SELECT COUNT(*) AS c FROM ep_log").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM ep_log WHERE fecha >= datetime('now','localtime', ?)",
                (f"-{int(dias)} days",),
            ).fetchone()
        return int(row["c"] or 0)


# ── Notas por episodio ────────────────────────────────────────────────────────

def guardar_nota_episodio(nombre: str, episodio: int, nota: str) -> bool:
    """Guarda o actualiza la nota de un episodio concreto. Devuelve True si ok."""
    if not nombre or episodio <= 0:
        return False
    nota = (nota or "").strip()
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO episode_notes(nombre, episodio, nota) VALUES(?, ?, ?) "
                "ON CONFLICT(nombre, episodio) DO UPDATE SET nota=excluded.nota, "
                "fecha=datetime('now','localtime')",
                (nombre, episodio, nota),
            )
        return True
    except Exception:
        return False


def obtener_notas_episodio(nombre: str) -> list[dict]:
    """Devuelve todas las notas de un anime ordenadas por episodio."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT episodio, nota, fecha FROM episode_notes "
            "WHERE nombre = ? AND nota != '' ORDER BY episodio",
            (nombre,),
        ).fetchall()
    return [dict(r) for r in rows]


def obtener_nota_episodio(nombre: str, episodio: int) -> Optional[str]:
    """Devuelve la nota de un episodio concreto o None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT nota FROM episode_notes WHERE nombre = ? AND episodio = ?",
            (nombre, episodio),
        ).fetchone()
    return row["nota"] if row else None


def borrar_nota_episodio(nombre: str, episodio: int) -> bool:
    """Borra la nota de un episodio. Devuelve True si existía."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM episode_notes WHERE nombre = ? AND episodio = ?",
                (nombre, episodio),
            )
        return cur.rowcount > 0
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════════════════
# MEDIA (películas y series no-anime, vía TMDB) — v6
# ════════════════════════════════════════════════════════════════════════════════

# Caché en memoria de listar_media() con invalidación en cada mutación.
_media_cache: Optional[list[dict]] = None
_media_cache_lock = threading.Lock()


def _invalidar_media_cache() -> None:
    global _media_cache
    with _media_cache_lock:
        _media_cache = None


def listar_media() -> list[dict]:
    global _media_cache
    with _media_cache_lock:
        if _media_cache is not None:
            return _media_cache
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM media ORDER BY creado_en DESC").fetchall()
        result = [dict(r) for r in rows]
    with _media_cache_lock:
        _media_cache = result
    return result


def guardar_media(data: dict) -> tuple[bool, str]:
    """Guarda una película o serie. `data` viene del scraper TMDB."""
    import json
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        return False, "sin título"
    tipo = data.get("tipo") or "pelicula"
    if tipo not in ("pelicula", "serie"):
        tipo = "pelicula"
    genero = data.get("genero") or []
    if isinstance(genero, list):
        genero = json.dumps(genero, ensure_ascii=False)
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO media
                   (titulo, tipo, tmdb_id, imagen, sinopsis, genero, anio,
                    duracion, temporadas, estado_media, puntuacion_tmdb)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    titulo, tipo, int(data.get("tmdb_id") or 0),
                    data.get("imagen", ""), data.get("sinopsis", ""), genero,
                    data.get("anio", ""), int(data.get("duracion") or 0),
                    int(data.get("temporadas") or 0), data.get("estado_media", ""),
                    float(data.get("puntuacion_tmdb") or 0),
                ),
            )
        _invalidar_media_cache()
        return True, "ok"
    except sqlite3.IntegrityError:
        return False, "duplicado"
    except Exception as e:
        return False, str(e)


def obtener_media(media_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (int(media_id),)).fetchone()
        return dict(row) if row else None


def actualizar_media(media_id: int, campos: dict) -> tuple[bool, str]:
    allowed = {"estado_usuario", "puntuacion", "episodios_vistos", "favorito", "notas", "rewatches"}
    campos = {k: v for k, v in campos.items() if k in allowed}
    if not campos:
        return False, "sin campos válidos"
    sets = ", ".join(f"{k}=?" for k in campos)
    values = list(campos.values()) + [int(media_id)]
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE media SET {sets} WHERE id=?", values)
        if cur.rowcount == 0:
            return False, "no encontrado"
    _invalidar_media_cache()
    return True, "ok"


def eliminar_media(media_id: int) -> tuple[bool, str]:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM media WHERE id=?", (int(media_id),))
        if cur.rowcount == 0:
            return False, "no encontrado"
    _invalidar_media_cache()
    return True, "ok"
