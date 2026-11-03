"""Copia de tu lista en la nube (v2.15).

Miraru guarda todo en este ordenador. Si se formatea el PC, se restablece de
fábrica o se reinstala Windows, la lista se perdía con él: las copias de
`backups/` viven en la misma carpeta.

Solución sin cuentas ni servidores propios: Miraru deja una copia en una
carpeta que tu propio servicio de nube sincroniza (OneDrive, Google Drive,
Dropbox o iCloud Drive). Al instalar Miraru en un PC nuevo —o en el mismo tras
formatearlo— y entrar con tu cuenta, la copia aparece sola y Miraru ofrece
recuperarla con un clic.

  - Se activa sola si hay OneDrive (lo trae Windows al entrar con cuenta de
    Microsoft); se puede cambiar de carpeta o apagar desde Miraru.
  - La copia NO lleva contraseñas ni sesiones (token de AniList, cookie de
    AnimeAV1, contraseña del correo, PIN…): eso no debe viajar a la nube. Tras
    recuperar, hay que volver a conectarlas.
  - Se escribe al poco de cada cambio y como mucho cada pocos minutos.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Optional

import database as db

log = logging.getLogger("miraru.copia_nube")

NOMBRE_CARPETA = "Miraru"
# Un archivo por ordenador: dos PCs con la misma nube no se pisan la copia.
PREFIJO = "miraru-copia-"
CLAVE_CARPETA = "copia_nube_carpeta"        # "" = sin decidir; "-" = apagada
CLAVE_ULTIMA = "copia_nube_ultima"           # json {ts, animes}

# Lo que nunca sale del ordenador.
_SECRETO = re.compile(r"token|cookie|pass|pin|salt|secret|vapid|api_key|push_subs|credential",
                      re.I)

# Los contadores de cambios vuelven a 0 en cada arranque: con el id de la
# sesión, "lo último copiado" de una sesión anterior nunca parece al día.
_SESION = f"{os.getpid()}-{int(time.time())}"

ESPERA_TRAS_CAMBIO = 90        # s: agrupa varios cambios seguidos en una copia
INTERVALO_REVISION = 30        # s entre comprobaciones del hilo


# ── Dónde ────────────────────────────────────────────────────────────────────

def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def _cuentas_onedrive() -> Optional[dict]:
    """{carpeta en minúsculas: sesión iniciada?} leído del registro de Windows.
    La carpeta OneDrive existe aunque no hayas iniciado sesión (o haya caducado):
    entonces NO sube nada a la nube y la copia daría una falsa seguridad.
    None fuera de Windows."""
    try:
        import winreg
    except ImportError:
        return None
    out: dict = {}
    try:
        raiz = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts")
    except OSError:
        return out
    with raiz:
        i = 0
        while True:
            try:
                nombre = winreg.EnumKey(raiz, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(raiz, nombre) as k:
                    def val(n):
                        try:
                            return winreg.QueryValueEx(k, n)[0]
                        except OSError:
                            return ""
                    carpeta = val("UserFolder")
                    if carpeta:
                        out[str(carpeta).lower()] = bool(val("UserEmail") or val("cid"))
            except OSError:
                continue
    return out


def detectar_nubes() -> list[dict]:
    """Carpetas de nube que hay en este PC; primero las que sincronizan."""
    vistas: set = set()
    out: list[dict] = []
    cuentas = _cuentas_onedrive()

    def poner(nombre: str, ruta) -> None:
        if not ruta:
            return
        p = Path(ruta)
        try:
            if p.is_dir() and str(p).lower() not in vistas:
                vistas.add(str(p).lower())
                sinc = None
                if nombre == "OneDrive" and cuentas is not None:
                    sinc = cuentas.get(str(p).lower(), False)
                out.append({"servicio": nombre, "ruta": str(p), "sincroniza": sinc})
        except OSError:
            pass

    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        poner("OneDrive", os.environ.get(var))
    home = _home()
    for d in sorted(home.glob("OneDrive*")):
        poner("OneDrive", d)
    for ruta in _carpetas_google_drive(home):
        poner("Google Drive", ruta)
    for ruta in _carpetas_dropbox(home):
        poner("Dropbox", ruta)
    poner("iCloud Drive", home / "iCloudDrive")
    # v2.16: más nubes con app de escritorio (crean una carpeta que sincroniza sola).
    for nombre, rutas in (("MEGA", [home / "MEGA", home / "Documents" / "MEGA"]),
                          ("Proton Drive", [home / "Proton Drive"] + sorted(home.glob("Proton Drive*"))),
                          ("Box", [home / "Box"]),
                          ("Nextcloud", [home / "Nextcloud"]),
                          ("Sync.com", [home / "Sync"])):
        for r in rutas:
            poner(nombre, r)
    for raiz in _unidades_locales():                   # pCloud monta P: como unidad
        if _etiqueta_volumen(raiz).lower() == "pcloud drive":
            poner("pCloud", raiz)
    for n in out:
        if n["servicio"] == "Google Drive":
            # Google Drive para escritorio solo monta su unidad (o su carpeta
            # espejo) con la sesión iniciada: si existe, sincroniza.
            n["sincroniza"] = True
    return sorted(out, key=lambda n: n["sincroniza"] is False)   # estable: no cambia el resto


# Nombre de «Mi unidad» en los idiomas más comunes de Google Drive.
_MI_UNIDAD = ("My Drive", "Mi unidad", "Mon Drive", "Meine Ablage", "Il mio Drive",
              "O meu disco", "Meu Drive", "Mijn Drive", "Mój dysk", "Мой диск",
              "マイドライブ", "내 드라이브", "我的雲端硬碟", "我的云端硬盘")
_NO_SON_MI_UNIDAD = {"shared drives", "unidades compartidas", "drives partagés", "geteilte ablagen",
                     "drive condivisi", "computers", "ordenadores", "ordinateurs", "computer",
                     "$recycle.bin", ".shortcut-targets-by-id", "system volume information",
                     ".file-revisions-by-id"}


def _etiqueta_volumen(raiz: str) -> str:
    """Etiqueta de una unidad de Windows («Google Drive» para la de DriveFS)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
            ctypes.c_wchar_p(raiz), buf, 261, None, None, None, None, 0)
        return buf.value if ok else ""
    except Exception:  # noqa: BLE001 — fuera de Windows o unidad no lista
        return ""


def _unidades_locales() -> list[str]:
    """Unidades D:…Z: presentes, sin las de red ni los lectores de CD (una
    unidad de red caída podría dejar la consulta colgada)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        mapa = k32.GetLogicalDrives()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for i in range(3, 26):
        if mapa & (1 << i):
            raiz = f"{chr(65 + i)}:\\"
            if k32.GetDriveTypeW(ctypes.c_wchar_p(raiz)) not in (4, 5):   # 4 red, 5 CD
                out.append(raiz)
    return out


def _carpetas_google_drive(home: Path) -> list[Path]:
    """Google Drive para escritorio monta una unidad virtual (normalmente G:)
    con la etiqueta «Google Drive»; dentro, «Mi unidad» tiene el nombre en el
    idioma de la cuenta. En modo «espejo» es una carpeta en el perfil. También
    la app antigua «Copia de seguridad y sincronización» (~/Google Drive)."""
    out: list[Path] = []
    for raiz in _unidades_locales():
        if _etiqueta_volumen(raiz).lower() != "google drive":
            continue
        try:
            subs = [d for d in Path(raiz).iterdir() if d.is_dir()]
        except OSError:
            continue
        conocida = [d for d in subs if d.name in _MI_UNIDAD]
        otras = [d for d in subs if d.name.lower() not in _NO_SON_MI_UNIDAD]
        out.extend(conocida or otras[:1])
    for nombre in _MI_UNIDAD:
        out.append(home / nombre)                            # modo espejo
        out.append(home / "Google Drive" / nombre)
    out.append(home / "Google Drive")                        # app antigua
    return [p for p in out if p.is_dir()]


def _carpetas_dropbox(home: Path) -> list[Path]:
    """Dropbox apunta su carpeta (personal y de empresa) en info.json."""
    out: list[Path] = []
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")):
        if not base:
            continue
        info = Path(base) / "Dropbox" / "info.json"
        try:
            datos = json.loads(info.read_text(encoding="utf-8"))
            for cuenta in datos.values():
                if isinstance(cuenta, dict) and cuenta.get("path"):
                    out.append(Path(cuenta["path"]))
        except (OSError, ValueError):
            pass
    out.append(home / "Dropbox")
    return [p for p in out if p.is_dir()]


def carpeta_config() -> str:
    return db.get_config(CLAVE_CARPETA) or ""


def carpeta_activa() -> Optional[Path]:
    """La carpeta donde se guarda la copia, o None si está apagada / no hay."""
    c = carpeta_config()
    if c == "-":
        return None
    if c:
        return Path(c)
    nubes = detectar_nubes()
    return Path(nubes[0]["ruta"]) / NOMBRE_CARPETA if nubes else None


def nombre_equipo() -> str:
    n = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "pc"
    return re.sub(r"[^\w-]+", "_", n)[:40] or "pc"


def archivo_copia(carpeta: Path) -> Path:
    return carpeta / f"{PREFIJO}{nombre_equipo()}.zip"


def _servicio_de(ruta: Path) -> str:
    r = str(ruta).lower()
    for n in detectar_nubes():
        if r.startswith(n["ruta"].lower()):
            return n["servicio"]
    return "carpeta"


# ── Escribir la copia ───────────────────────────────────────────────────────

def _foto_sin_secretos(destino: Path) -> int:
    """Foto coherente de la BD (API de backup de SQLite, con el WAL) sin
    claves secretas. Devuelve cuántos animes lleva."""
    origen = sqlite3.connect(str(db._get_db_path()))
    copia = sqlite3.connect(str(destino))
    try:
        with copia:
            origen.backup(copia)
        claves = [r[0] for r in copia.execute("SELECT key FROM config")]
        borrar = [k for k in claves if _SECRETO.search(k)]
        with copia:
            copia.executemany("DELETE FROM config WHERE key=?", [(k,) for k in borrar])
        copia.execute("VACUUM")
        return copia.execute("SELECT COUNT(*) FROM animes").fetchone()[0]
    finally:
        copia.close()
        origen.close()


def _marca() -> list:
    return [_SESION, db._cache_gen, db._media_gen]


def ya_escribio() -> bool:
    """¿Esta instalación ya ha hecho alguna copia (o ha decidido empezar de cero)?"""
    return bool(db.get_config(CLAVE_ULTIMA))


def pendiente_de_decidir(carpeta: Optional[Path] = None) -> bool:
    """Instalación nueva y ya hay una copia con el nombre de este PC (p. ej.
    tras restablecerlo de fábrica): NO se escribe encima hasta que elijas
    recuperarla o empezar de cero. Si no, añadir un solo anime antes de
    recuperar machacaría la copia buena."""
    carpeta = carpeta or carpeta_activa()
    return bool(carpeta) and not ya_escribio() and archivo_copia(carpeta).exists()


def guardar_copia(carpeta: Optional[Path] = None, forzar: bool = False) -> dict:
    carpeta = carpeta or carpeta_activa()
    if carpeta is None:
        return {"ok": False, "motivo": "sin carpeta"}
    if not forzar and pendiente_de_decidir(carpeta):
        return {"ok": False, "motivo": "pendiente"}
    carpeta.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        foto = Path(tmp) / "anime_tracker.db"
        animes = _foto_sin_secretos(foto)
        zip_tmp = Path(tmp) / "copia.zip"
        info = {"app": "Miraru", "formato": 1, "animes": animes,
                "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
                "equipo": nombre_equipo()}
        with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(foto, "anime_tracker.db")
            z.writestr("miraru.json", json.dumps(info, ensure_ascii=False))
        final = archivo_copia(carpeta)
        # Nunca dejar una copia a medias: la anterior se conserva aparte y la
        # nueva entra con un reemplazo atómico.
        if final.exists():
            shutil.copy2(final, final.with_name(final.stem + ".anterior"))
        parcial = final.with_name(final.name + ".tmp")
        shutil.copyfile(zip_tmp, parcial)
        os.replace(parcial, final)
    db.set_config(CLAVE_ULTIMA, json.dumps({"ts": int(time.time()), "animes": animes,
                                            "gen": _marca()}))
    return {"ok": True, "carpeta": str(carpeta), "animes": animes}


def empezar_de_cero() -> None:
    """Elegiste no recuperar: la copia vieja se aparta (no se borra) y desde
    ahora se copia lo de este PC."""
    c = carpeta_activa()
    if c and archivo_copia(c).exists():
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        f = archivo_copia(c)
        os.replace(f, f.with_name(f"{f.stem}.descartada-{ts}"))
    db.set_config(CLAVE_ULTIMA, json.dumps({"ts": 0, "animes": 0, "gen": None}))


# ── Leer / recuperar ─────────────────────────────────────────────────────────

def leer_info(zip_path: Path) -> Optional[dict]:
    try:
        with zipfile.ZipFile(zip_path) as z:
            if "anime_tracker.db" not in z.namelist():
                return None
            info = json.loads(z.read("miraru.json")) if "miraru.json" in z.namelist() else {}
        info["archivo"] = str(zip_path)
        info["ts"] = int(zip_path.stat().st_mtime)
        return info
    except (OSError, ValueError, zipfile.BadZipFile):
        return None


def buscar_copias() -> list[dict]:
    """Copias de Miraru en las nubes de este PC (la más reciente primero)."""
    sitios = []
    c = carpeta_activa()
    if c:
        sitios.append(c)
    for n in detectar_nubes():
        sitios.append(Path(n["ruta"]) / NOMBRE_CARPETA)
    out, vistos = [], set()
    for s in sitios:
        try:
            archivos = sorted(s.glob(PREFIJO + "*.zip")) if s.is_dir() else []
        except OSError:
            archivos = []
        for f in archivos:
            if str(f).lower() in vistos:
                continue
            vistos.add(str(f).lower())
            info = leer_info(f)
            if info:
                info["servicio"] = _servicio_de(s)
                info["este_pc"] = f.name == archivo_copia(s).name
                out.append(info)
    return sorted(out, key=lambda i: i["ts"], reverse=True)


def lista_vacia() -> bool:
    with db.get_conn() as c:
        n = c.execute("SELECT COUNT(*) FROM animes").fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    return n == 0 and m == 0


def recuperar(zip_path: Path) -> dict:
    """Sustituye la lista actual por la de la copia. Antes guarda la actual en
    backups/ por si acaso. Las claves de este PC (sesiones, PIN…) se respetan."""
    info = leer_info(zip_path)
    if not info:
        raise ValueError("No es una copia de Miraru válida")
    vivo = db._get_db_path()
    seguridad = vivo.parent / "backups"
    seguridad.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extract("anime_tracker.db", tmp)
        nueva = Path(tmp) / "anime_tracker.db"
        chk = sqlite3.connect(str(nueva))
        try:
            if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("La copia está dañada")
            chk.execute("SELECT COUNT(*) FROM animes").fetchone()
        except sqlite3.DatabaseError as e:
            raise ValueError("La copia está dañada") from e
        finally:
            chk.close()
        actual = sqlite3.connect(str(vivo))
        try:
            antes = sqlite3.connect(str(seguridad / f"antes_de_recuperar_{ts}.db"))
            with antes:
                actual.backup(antes)
            antes.close()
            secretos = [r for r in actual.execute("SELECT key, value FROM config")
                        if _SECRETO.search(r[0])]
            origen = sqlite3.connect(str(nueva))
            try:
                origen.backup(actual)          # reemplaza el contenido, en caliente
            finally:
                origen.close()
            with actual:
                actual.executemany("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                                   secretos)
        finally:
            actual.close()
    db.drain_pool()
    db.init_db()                               # por si la copia es de una versión anterior
    db._invalidar_cache()
    db._invalidar_media_cache()
    db.set_config(CLAVE_ULTIMA, json.dumps({"ts": 0, "animes": info.get("animes"), "gen": None}))
    return {"ok": True, "animes": info.get("animes"), "fecha": info.get("fecha")}


# ── Automático ───────────────────────────────────────────────────────────────

def estado() -> dict:
    c = carpeta_activa()
    try:
        ultima = json.loads(db.get_config(CLAVE_ULTIMA) or "{}")
    except ValueError:
        ultima = {}
    sinc = None
    if c:
        for n in detectar_nubes():
            if str(c).lower().startswith(n["ruta"].lower()):
                sinc = n["sincroniza"]
    return {"activa": c is not None, "apagada": carpeta_config() == "-",
            "sincroniza": sinc,
            "carpeta": str(c) if c else "", "servicio": _servicio_de(c) if c else "",
            "elegida": bool(carpeta_config()), "ultima": ultima,
            "pendiente": pendiente_de_decidir(c) if c else False,
            "nubes": detectar_nubes()}


_hilo: Optional[threading.Thread] = None


def iniciar_hilo() -> None:
    """Copia al arrancar y después tras cada cambio (con un margen para
    agrupar varios seguidos). No hace nada si no hay carpeta."""
    global _hilo
    if _hilo is not None:
        return

    def bucle():
        visto = None
        cambio_en = 0.0
        while True:
            try:
                gen = _marca()
                if gen != visto:
                    visto, cambio_en = gen, time.time()
                tranquilo = time.time() - cambio_en >= ESPERA_TRAS_CAMBIO
                hecha = json.loads(db.get_config(CLAVE_ULTIMA) or "{}").get("gen")
                if (tranquilo and hecha != gen and carpeta_activa() is not None
                        and not lista_vacia()):
                    guardar_copia()
            except Exception as e:  # noqa: BLE001 — nunca tumbar la app por esto
                log.warning("copia en la nube: %s", e)
            time.sleep(INTERVALO_REVISION)

    _hilo = threading.Thread(target=bucle, daemon=True, name="copia-nube")
    _hilo.start()
