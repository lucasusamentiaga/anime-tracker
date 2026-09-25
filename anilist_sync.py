"""Sincronización bidireccional con AniList.

Flujo OAuth2:
  1. El usuario hace clic en "Conectar AniList" → se abre el navegador
  2. Autoriza la app en AniList → redirige a localhost con ?code=...
  3. Miraru intercambia el code por un access_token (válido 1 año)
  4. Se guarda en config: anilist_token, anilist_username, anilist_userid

Sync:
  - PUSH: al cambiar estado/puntuación/episodios en Miraru → muta en AniList
  - PULL: descarga la lista completa del usuario desde AniList y actualiza local
  - Resolución de conflictos: el dato más reciente gana (Miraru no guarda
    timestamps de cambio; el pull solo actualiza si el anime no se ha tocado
    desde el último sync).
"""

from __future__ import annotations

import logging
import time as _time
from typing import Optional

import requests

import database as db
from scrapers.anilist import ANILIST_MIN_INTERVAL

log = logging.getLogger("miraru.anilist_sync")

ANILIST_API = "https://graphql.anilist.co"
OAUTH_AUTHORIZE = "https://anilist.co/api/v2/oauth/authorize"
OAUTH_TOKEN = "https://anilist.co/api/v2/oauth/token"

# ── Mapeos de estado ─────────────────────────────────────────────────────────

_STATUS_TO_ANILIST = {
    "viendo": "CURRENT",
    "completado": "COMPLETED",
    "pendiente": "PLANNING",
    "abandonado": "DROPPED",
    "pausa": "PAUSED",
}

_STATUS_FROM_ANILIST = {v: k for k, v in _STATUS_TO_ANILIST.items()}
# AniList tiene REPEATING que no tenemos — lo mapeamos a "viendo"
_STATUS_FROM_ANILIST["REPEATING"] = "viendo"


# ── Helpers de config ────────────────────────────────────────────────────────

def get_token() -> Optional[str]:
    return db.get_config("anilist_token")


def is_connected() -> bool:
    return bool(get_token())


def get_connection_info() -> dict:
    """Devuelve info de la conexión actual con AniList."""
    vals = db.get_config_many(["anilist_token", "anilist_username", "anilist_userid"])
    return {
        "connected": bool(vals.get("anilist_token")),
        "username": vals.get("anilist_username", ""),
        "userid": vals.get("anilist_userid", ""),
    }


def save_token(token: str, username: str, userid: int):
    db.set_config("anilist_token", token)
    db.set_config("anilist_username", username)
    db.set_config("anilist_userid", str(userid))


def disconnect():
    db.set_config("anilist_token", "")
    db.set_config("anilist_username", "")
    db.set_config("anilist_userid", "")


# ── OAuth2 ───────────────────────────────────────────────────────────────────

def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str) -> dict:
    """Intercambia un authorization code por un access_token."""
    resp = requests.post(OAUTH_TOKEN, json={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }, headers={"Accept": "application/json"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_viewer(token: str) -> dict:
    """Obtiene el usuario autenticado (id, name)."""
    query = "query { Viewer { id name } }"
    resp = requests.post(ANILIST_API, json={"query": query},
                         headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/json"},
                         timeout=10)
    resp.raise_for_status()
    data = resp.json()
    viewer = data.get("data", {}).get("Viewer", {})
    return {"id": viewer.get("id", 0), "name": viewer.get("name", "")}


# ── PUSH: Miraru → AniList ───────────────────────────────────────────────────

_SAVE_ENTRY = """
mutation ($mediaId: Int!, $status: MediaListStatus, $score: Float,
          $progress: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status,
                     scoreRaw: $score, progress: $progress) {
    id mediaId status score progress
  }
}
"""


def push_anime(anime: dict) -> Optional[dict]:
    """Sube el estado de un anime a AniList.
    Requiere que el anime tenga anilist_id > 0."""
    token = get_token()
    if not token:
        return None
    anilist_id = anime.get("anilist_id") or 0
    if not anilist_id:
        return None

    status = _STATUS_TO_ANILIST.get(anime.get("estado_usuario", ""), "PLANNING")
    score_raw = (anime.get("puntuacion") or 0) * 10  # AniList scoreRaw es 0-100
    progress = anime.get("episodios_vistos") or 0

    variables = {
        "mediaId": anilist_id,
        "status": status,
        "score": score_raw,
        "progress": progress,
    }

    try:
        resp = requests.post(ANILIST_API, json={"query": _SAVE_ENTRY, "variables": variables},
                             headers={"Authorization": f"Bearer {token}",
                                      "Accept": "application/json"},
                             timeout=15)
        resp.raise_for_status()
        data = resp.json()
        entry = data.get("data", {}).get("SaveMediaListEntry")
        log.info("Push %s (anilist:%d) → %s", anime.get("nombre"), anilist_id, status)
        return entry
    except Exception as e:
        log.warning("Error push %s: %s", anime.get("nombre"), e)
        return None


# ── PULL: AniList → Miraru ───────────────────────────────────────────────────

_USER_LIST = """
query ($userId: Int!, $type: MediaType!) {
  MediaListCollection(userId: $userId, type: $type) {
    lists {
      entries {
        mediaId
        status
        score(format: POINT_10_DECIMAL)
        progress
        media {
          id
          title { romaji english }
          episodes
          format
          coverImage { large }
          genres
          description(asHtml: false)
          status
        }
      }
    }
  }
}
"""


def _pull_type(media_type: str = "ANIME") -> dict:
    """Descarga la lista de un tipo (ANIME o MANGA) del usuario de AniList
    y sincroniza con la BD local.

    Returns: {"added": int, "updated": int, "errors": int}
    """
    token = get_token()
    userid = db.get_config("anilist_userid")
    if not token or not userid:
        return {"added": 0, "updated": 0, "errors": 0, "error": "no conectado"}

    tipo_local = "manga" if media_type == "MANGA" else "anime"

    try:
        resp = requests.post(ANILIST_API,
                             json={"query": _USER_LIST,
                                   "variables": {"userId": int(userid), "type": media_type}},
                             headers={"Authorization": f"Bearer {token}",
                                      "Accept": "application/json"},
                             timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("Error pull AniList %s: %s", media_type, e)
        return {"added": 0, "updated": 0, "errors": 1, "error": str(e)}

    collection = data.get("data", {}).get("MediaListCollection", {})
    lists = collection.get("lists", [])

    added = updated = errors = 0

    # Cargar todos los animes/manga locales indexados por anilist_id
    local_by_aid: dict[int, dict] = {}
    local_by_name: dict[str, dict] = {}
    for a in db.listar_animes():
        if a.get("anilist_id"):
            local_by_aid[a["anilist_id"]] = a
        local_by_name[a["nombre"].lower()] = a

    status_map = {
        "FINISHED": "Finalizado", "RELEASING": "En emisión",
        "NOT_YET_RELEASED": "Sin estrenar", "CANCELLED": "Cancelado",
        "HIATUS": "En pausa",
    }

    for lst in lists:
        for entry in lst.get("entries", []):
            try:
                media = entry.get("media", {})
                aid = media.get("id", 0)
                title = (media.get("title", {}).get("english")
                         or media.get("title", {}).get("romaji") or "")
                if not title:
                    continue

                estado = _STATUS_FROM_ANILIST.get(entry.get("status", ""), "pendiente")
                score = entry.get("score") or 0
                progress = entry.get("progress") or 0

                # ¿Ya existe localmente?
                local = local_by_aid.get(aid) or local_by_name.get(title.lower())

                if local:
                    # Actualizar — solo si AniList tiene datos más avanzados
                    cambios: dict = {}
                    if not local.get("anilist_id") and aid:
                        cambios["anilist_id"] = aid
                    # Actualizar progreso si AniList va por delante
                    if progress > (local.get("episodios_vistos") or 0):
                        cambios["episodios_vistos"] = progress
                    # Actualizar puntuación si local no tiene y AniList sí
                    if score and not local.get("puntuacion"):
                        cambios["puntuacion"] = score
                    # Actualizar estado si local está en pendiente y AniList no
                    if local.get("estado_usuario") == "pendiente" and estado != "pendiente":
                        cambios["estado_usuario"] = estado

                    if cambios:
                        db.actualizar_anime(local["nombre"], cambios)
                        updated += 1
                else:
                    # Nuevo — añadir
                    if media_type == "MANGA":
                        chapters = media.get("chapters") or 0
                        capitulos = str(chapters) if chapters > 0 else "?"
                    else:
                        episodes = media.get("episodes") or 0
                        fmt = (media.get("format") or "").upper()
                        if fmt == "MOVIE":
                            capitulos = "película"
                        elif episodes > 0:
                            capitulos = str(episodes)
                        else:
                            capitulos = "?"

                    nuevo = {
                        "nombre": title,
                        "fuente": "anilist",
                        "capitulos": capitulos,
                        "imagen": media.get("coverImage", {}).get("large", ""),
                        "genero": media.get("genres", []),
                        "sinopsis": (media.get("description") or "")[:500],
                        "estado_anime": status_map.get(media.get("status", ""), "Desconocido"),
                        "estado_usuario": estado,
                        "puntuacion": score if score else None,
                        "episodios_vistos": progress,
                        "anilist_id": aid,
                        "tipo": tipo_local,
                    }
                    ok, msg = db.guardar_anime(nuevo)
                    if ok:
                        added += 1
                    else:
                        log.warning("Error añadir %s: %s", title, msg)
                        errors += 1
            except Exception as e:
                log.warning("Error procesando entry: %s", e)
                errors += 1

    log.info("Pull AniList %s: +%d añadidos, ~%d actualizados, %d errores",
             media_type, added, updated, errors)
    return {"added": added, "updated": updated, "errors": errors}


def pull_list() -> dict:
    """Descarga la lista ANIME completa del usuario de AniList."""
    return _pull_type("ANIME")


def pull_manga_list() -> dict:
    """Descarga la lista MANGA completa del usuario de AniList."""
    return _pull_type("MANGA")


def pull_all() -> dict:
    """Descarga anime + manga de AniList."""
    anime = _pull_type("ANIME")
    manga = _pull_type("MANGA")
    return {
        "added": anime["added"] + manga["added"],
        "updated": anime["updated"] + manga["updated"],
        "errors": anime["errors"] + manga["errors"],
    }


# ── Push masivo (sync completo local → AniList) ─────────────────────────────

def push_all() -> dict:
    """Sube TODOS los animes con anilist_id a AniList."""
    token = get_token()
    if not token:
        return {"pushed": 0, "errors": 0, "error": "no conectado"}

    animes = db.listar_animes()
    pushed = errors = 0

    for a in animes:
        if not a.get("anilist_id"):
            continue
        result = push_anime(a)
        if result:
            pushed += 1
        else:
            errors += 1
        _time.sleep(ANILIST_MIN_INTERVAL)  # rate limit: AniList 30 req/min

    log.info("Push all: %d subidos, %d errores", pushed, errors)
    return {"pushed": pushed, "errors": errors}


# ── Resolución de anilist_id para animes existentes ──────────────────────────



def resolve_anilist_ids(limite: int | None = None, sleep=_time.sleep) -> dict:
    """Busca el anilist_id de animes/mangas que aún no lo tienen.

    Usa metadatos.resolver_en_anilist (variantes del título + fallback MAL) y
    el tipo correcto (antes buscaba los mangas como ANIME y solo el título
    literal, así que los nombres de AnimeFLV nunca se resolvían).
    `limite`: máximo de animes a intentar en esta llamada (None = todos)."""
    from metadatos import resolver_en_anilist
    from scrapers.anilist import candidatos_busqueda

    pendientes = [a for a in db.listar_animes() if not a.get("anilist_id")]
    if limite is not None:
        pendientes = pendientes[:limite]
    resolved = errors = 0

    for a in pendientes:
        try:
            r = resolver_en_anilist(a["nombre"], a.get("tipo") or "anime")
            if r and r.anilist_id:
                db.refrescar_metadata_anime(a["nombre"], {"anilist_id": r.anilist_id})
                resolved += 1
        except Exception:
            errors += 1
        # hasta una petición por variante del título + la de idMal
        sleep(ANILIST_MIN_INTERVAL * (len(candidatos_busqueda(a["nombre"])) + 1))

    log.info("Resolve IDs: %d resueltos, %d errores", resolved, errors)
    return {"resolved": resolved, "errors": errors,
            "pendientes": max(0, len(pendientes) - resolved)}
