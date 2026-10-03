"""Sincronización con la lista de AnimeAV1 (v2.12).

AnimeAV1 no tiene una API pública con OAuth como AniList: su web guarda la
lista de cada persona («Mis listas») y la lee/escribe con su propia sesión.
El inicio de sesión lleva un captcha de Cloudflare (Turnstile), así que Miraru
no puede entrar con email y contraseña. En su lugar la persona copia una vez la
cookie de su sesión desde el navegador y Miraru la guarda en su base de datos
local (nunca sale del ordenador salvo hacia animeav1.com).

Lo que usamos de AnimeAV1 (visto en el código de su web):
  GET  /cuenta/listas/__data.json  → {"libraryEntries": [{status, episode, media:{id, slug, title…}}]}
  POST /api/user/library {"mediaId", "status"}   → poner en una lista (-1 = quitar)
  POST /api/user/library {"mediaId", "episode"}  → último episodio visto
Estados: 0 viendo, 1 por ver, 2 completado, 3 en pausa, 4 abandonado.

Criterio al importar (igual que con AniList): nunca se pierde progreso.
  - episodios: solo sube si AnimeAV1 va por delante;
  - estado: se cambia si en Miraru seguía «pendiente», o si AnimeAV1 dice
    «completado» y aquí estaba «viendo».
"""
from __future__ import annotations

import json
import logging
import re
import time as _time
from typing import Optional

import database as db
from scrapers import animeav1 as av1
from trabajos import NULO, Progreso

log = logging.getLogger("miraru.animeav1_sync")

CLAVE_COOKIE = "animeav1_cookie"
CLAVE_USUARIO = "animeav1_usuario"
CLAVE_IDS = "animeav1_ids"          # {nombre en Miraru: id de AnimeAV1}

ESTADO_A_AV1 = {"viendo": 0, "pendiente": 1, "completado": 2, "pausa": 3, "abandonado": 4}
ESTADO_DESDE_AV1 = {v: k for k, v in ESTADO_A_AV1.items()}

PAUSA = 0.35   # entre peticiones a AnimeAV1: no queremos parecer un ataque


# ── Conexión ─────────────────────────────────────────────────────────────────

def normalizar_cookie(texto: str) -> str:
    """Acepta lo que la persona pegue: la cabecera entera («cookie: a=1; b=2»),
    solo los valores o con saltos de línea. Devuelve «a=1; b=2»."""
    t = (texto or "").strip().strip('"').strip("'")
    t = re.sub(r"^\s*cookie\s*:\s*", "", t, flags=re.I)
    partes = [p.strip() for p in re.split(r"[;\r\n]+", t) if p.strip()]
    partes = [p for p in partes if "=" in p and not p.startswith("=")]
    return "; ".join(partes)


def get_cookie() -> str:
    return db.get_config(CLAVE_COOKIE) or ""


def is_connected() -> bool:
    return bool(get_cookie())


def info() -> dict:
    return {"conectado": is_connected(), "usuario": db.get_config(CLAVE_USUARIO) or ""}


def _nombre_usuario(datos: dict) -> str:
    u = datos.get("user")
    if isinstance(u, dict):
        for k in ("username", "name", "displayName", "email"):
            if u.get(k):
                return str(u[k])
    return ""


def _leer_listas(s) -> dict:
    return av1.pagina("cuenta/listas", s=s)


def conectar(cookie: str, s=None) -> dict:
    c = normalizar_cookie(cookie)
    if not c:
        raise ValueError("No parece una cookie: debe tener la forma nombre=valor.")
    s = s or av1.sesion(c)
    try:
        datos = _leer_listas(s)
    except av1.ErrorAnimeAV1 as e:
        if e.status in (401, 403, 302):
            raise ValueError("AnimeAV1 no reconoce esa sesión. Vuelve a copiar la "
                             "cookie con la sesión iniciada.") from e
        raise
    usuario = _nombre_usuario(datos)
    db.set_config(CLAVE_COOKIE, c)
    db.set_config(CLAVE_USUARIO, usuario)
    return {"ok": True, "usuario": usuario,
            "entradas": len(datos.get("libraryEntries") or [])}


def desconectar():
    db.set_config(CLAVE_COOKIE, "")
    db.set_config(CLAVE_USUARIO, "")


# ── Mapa nombre de Miraru ↔ id de AnimeAV1 ───────────────────────────────────

def _ids() -> dict:
    try:
        d = json.loads(db.get_config(CLAVE_IDS) or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _guardar_ids(d: dict):
    db.set_config(CLAVE_IDS, json.dumps(d, ensure_ascii=False))


def _entradas(datos: dict) -> list[dict]:
    out = []
    for e in datos.get("libraryEntries") or []:
        if not isinstance(e, dict):
            continue
        m = e.get("media") if isinstance(e.get("media"), dict) else {}
        mid = m.get("id") or e.get("mediaId")
        if mid in (None, ""):
            continue
        out.append({"id": int(mid), "slug": m.get("slug") or "",
                    "titulo": m.get("title") or "",
                    "aka": m.get("aka") if isinstance(m.get("aka"), dict) else {},
                    "malId": m.get("malId"),
                    "estado": ESTADO_DESDE_AV1.get(e.get("status"), "pendiente"),
                    "episodio": int(e.get("episode") or 0)})
    return out


def _claves_titulos(e: dict) -> set:
    ts = [e.get("titulo") or ""] + [v for v in (e.get("aka") or {}).values() if isinstance(v, str)]
    return {db.clave_nombre(t) for t in ts if t}


# ── Importar (AnimeAV1 → Miraru) ─────────────────────────────────────────────

def pull(progreso: Progreso = NULO, s=None, anilist=None, sleep=_time.sleep) -> dict:
    cookie = get_cookie()
    if not cookie:
        return {"added": 0, "updated": 0, "errors": 0, "error": "no conectado"}
    s = s or av1.sesion(cookie)
    if anilist is None:
        from scrapers.anilist import AniListScraper
        anilist = AniListScraper()
    entradas = _entradas(_leer_listas(s))
    progreso.total(len(entradas))

    locales = db.listar_animes()
    por_nombre = {a["nombre"]: a for a in locales}
    por_clave = {db.clave_nombre(a["nombre"]): a for a in locales}
    por_aid = {a["anilist_id"]: a for a in locales if a.get("anilist_id")}
    ids = _ids()
    por_id_av1 = {v: por_nombre[k] for k, v in ids.items() if k in por_nombre}

    added = updated = errors = 0
    for e in entradas:
        progreso.avanzar(1, e["titulo"])
        try:
            local = por_id_av1.get(e["id"])
            if local is None:
                local = next((por_clave[k] for k in _claves_titulos(e) if k in por_clave), None)
            nuevo_data = None
            if local is None:
                # Sin coincidencia por nombre: buscamos su ficha (trae el id de
                # MyAnimeList) y, por él, el anime exacto en AniList.
                m = av1.obtener_media(e["slug"], s=s) if e["slug"] else None
                sleep(PAUSA)
                mal = (m or {}).get("malId") or e.get("malId")
                al = anilist.buscar_por_mal(int(mal)) if mal else None
                if al and al.anilist_id and al.anilist_id in por_aid:
                    local = por_aid[al.anilist_id]
                elif al:
                    nuevo_data = al
                elif m:
                    nuevo_data = av1.a_anime_data(m)
            if local is not None:
                ids[local["nombre"]] = e["id"]
                cambios: dict = {}
                if e["episodio"] > int(local.get("episodios_vistos") or 0):
                    cambios["episodios_vistos"] = e["episodio"]
                actual = local.get("estado_usuario") or "pendiente"
                if e["estado"] != actual and (
                        actual == "pendiente"
                        or (e["estado"] == "completado" and actual == "viendo")):
                    cambios["estado_usuario"] = e["estado"]
                if cambios:
                    db.actualizar_anime(local["nombre"], cambios)
                    updated += 1
            elif nuevo_data is not None:
                datos = dict(nuevo_data.__dict__)
                datos.update({"estado_usuario": e["estado"],
                              "episodios_vistos": e["episodio"], "tipo": "anime"})
                ok, msg = db.guardar_anime(datos)
                if ok:
                    added += 1
                    ids[datos["nombre"]] = e["id"]
                    por_clave[db.clave_nombre(datos["nombre"])] = datos
                else:
                    errors += 1
                    log.warning("AnimeAV1: no se pudo añadir %s: %s", datos["nombre"], msg)
            else:
                errors += 1
        except av1.ErrorAnimeAV1 as ex:
            if ex.status in (401, 403):
                raise
            errors += 1
        except Exception as ex:  # noqa: BLE001
            log.warning("AnimeAV1: error con %s: %s", e.get("titulo"), ex)
            errors += 1
    _guardar_ids(ids)
    db._invalidar_cache()
    return {"added": added, "updated": updated, "errors": errors, "total": len(entradas)}


# ── Subir (Miraru → AnimeAV1) ────────────────────────────────────────────────

def _titulos_anilist(aids: list[int], sleep=_time.sleep) -> dict:
    """{anilist_id: (romaji, idMal)} en lotes de 50 (una petición por lote)."""
    import requests

    from scrapers.anilist import ANILIST_API, ANILIST_MIN_INTERVAL
    q = """query($ids:[Int]){Page(perPage:50){media(id_in:$ids,type:ANIME){
           id idMal title{romaji english}}}}"""
    out: dict = {}
    for i in range(0, len(aids), 50):
        lote = aids[i:i + 50]
        try:
            r = requests.post(ANILIST_API, json={"query": q, "variables": {"ids": lote}},
                              headers={"Accept": "application/json",
                                       "Accept-Encoding": "identity"}, timeout=20)
            for m in ((r.json().get("data") or {}).get("Page") or {}).get("media") or []:
                t = m.get("title") or {}
                out[m["id"]] = (t.get("romaji") or "", m.get("idMal"), t.get("english") or "")
        except Exception as e:  # noqa: BLE001
            log.warning("AniList (títulos para AnimeAV1): %s", e)
        if i + 50 < len(aids):
            sleep(ANILIST_MIN_INTERVAL)
    return out


def _buscar_id(anime: dict, info_al: Optional[tuple], s, sleep) -> Optional[int]:
    """Busca el anime en AnimeAV1. Solo acepta un resultado seguro: mismo id de
    MyAnimeList, o el mismo título exacto si no lo sabemos."""
    romaji, mal, english = info_al or ("", None, "")
    textos = [t for t in (romaji, anime["nombre"], english) if t]
    vistos: set = set()
    for texto in textos:
        if texto in vistos:
            continue
        vistos.add(texto)
        try:
            resultados = av1.buscar_medias(texto, s=s)
        except av1.ErrorAnimeAV1:
            resultados = []
        sleep(PAUSA)
        claves = {db.clave_nombre(t) for t in textos}
        exactos = [r for r in resultados if db.clave_nombre(r.get("title") or "") in claves]
        candidatos = exactos or resultados[:3]
        for r in candidatos:
            if not mal and r in exactos:
                return int(r["id"])
            if not mal:
                continue
            m = av1.obtener_media(r["slug"], s=s) if r.get("slug") else None
            sleep(PAUSA)
            if m and m.get("malId") and int(m["malId"]) == int(mal):
                return int(m["id"])
    return None


def push(progreso: Progreso = NULO, s=None, sleep=_time.sleep, titulos_anilist=None) -> dict:
    cookie = get_cookie()
    if not cookie:
        return {"pushed": 0, "skipped": 0, "not_found": 0, "errors": 0, "error": "no conectado"}
    s = s or av1.sesion(cookie)
    remotas = {e["id"]: e for e in _entradas(_leer_listas(s))}
    animes = [a for a in db.listar_animes()
              if (a.get("tipo") or "anime") == "anime" and a.get("estado_usuario") in ESTADO_A_AV1]
    progreso.total(len(animes))
    ids = _ids()
    sin_id = [a["anilist_id"] for a in animes
              if a["nombre"] not in ids and a.get("anilist_id")]
    progreso.detalle("Preparando…")
    info_al = (titulos_anilist or _titulos_anilist)(sin_id, sleep=sleep) if sin_id else {}
    por_clave_remota = {}
    for e in remotas.values():
        for k in _claves_titulos(e):
            por_clave_remota.setdefault(k, e["id"])

    pushed = skipped = not_found = errors = 0
    for a in animes:
        progreso.avanzar(1, a["nombre"])
        try:
            mid = ids.get(a["nombre"]) or por_clave_remota.get(db.clave_nombre(a["nombre"]))
            if not mid:
                mid = _buscar_id(a, info_al.get(a.get("anilist_id")), s, sleep)
            if not mid:
                not_found += 1
                continue
            ids[a["nombre"]] = mid
            estado = ESTADO_A_AV1[a["estado_usuario"]]
            vistos = int(a.get("episodios_vistos") or 0)
            r = remotas.get(mid)
            if r and ESTADO_A_AV1.get(r["estado"]) == estado and r["episodio"] == vistos:
                skipped += 1
                continue
            if not r or ESTADO_A_AV1.get(r["estado"]) != estado:
                _post(s, {"mediaId": mid, "status": estado})
                sleep(PAUSA)
            if vistos > 0 and (not r or r["episodio"] != vistos):
                _post(s, {"mediaId": mid, "episode": vistos})
                sleep(PAUSA)
            pushed += 1
        except av1.ErrorAnimeAV1 as ex:
            if ex.status in (401, 403):
                _guardar_ids(ids)
                raise
            errors += 1
        except Exception as ex:  # noqa: BLE001
            log.warning("AnimeAV1: error subiendo %s: %s", a["nombre"], ex)
            errors += 1
    _guardar_ids(ids)
    return {"pushed": pushed, "skipped": skipped, "not_found": not_found,
            "errors": errors, "total": len(animes)}


def _post(s, cuerpo: dict):
    resp = s.post(av1.BASE + "/api/user/library", json=cuerpo, timeout=20,
                  headers={"Origin": av1.BASE, "Referer": av1.BASE + "/cuenta/listas",
                           "Content-Type": "application/json"})
    if resp.status_code in (401, 403):
        raise av1.ErrorAnimeAV1("Sesión de AnimeAV1 caducada", resp.status_code)
    if resp.status_code >= 400:
        raise av1.ErrorAnimeAV1(f"HTTP {resp.status_code}", resp.status_code)
