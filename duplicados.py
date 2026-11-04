"""Animes repetidos en la lista (v2.16.1).

El mismo anime podía entrar varias veces con nombres distintos según de dónde
llegara: «Attack on Titan» (AniList), «Shingeki no Kyojin» (AnimeFLV) y
«Attack on Titan: The Final Season Part 2» (Kitsu)… Todos acaban con el mismo
`anilist_id`, que es lo que delata que son el mismo.

Pero un `anilist_id` puede estar mal resuelto (p. ej. «Hajime no Ippo», 75
episodios, apuntaba a «Hajime no Ippo: Rising»). Fusionar a ciegas borraría un
anime de verdad, así que solo se juntan los que AniList confirma: el nombre
guardado es uno de sus títulos o sinónimos y el número de episodios cuadra.
Lo dudoso se queda como está.
"""
from __future__ import annotations

import logging
import re
import unicodedata

import database as db

log = logging.getLogger("miraru.duplicados")

_Q_TITULOS = """
query ($ids: [Int], $page: Int) {
  Page(page: $page, perPage: 50) {
    media(id_in: $ids) { id type format episodes
      title { romaji english native } synonyms }
  }
}
"""

# Entre dos nombres de fuentes distintas no importa la puntuación ni lo que
# vaya entre paréntesis («Black Clover (TV)»).
_PARENTESIS = re.compile(r"\([^)]*\)")


# Palabras que cada fuente pone o quita a su gusto («Season», «The», «Movie»)
# y ordinales escritos de mil formas («2nd Season» = «Season 2» = «2»).
_RELLENO = {"season", "the", "movie", "tv", "gekijouban", "series", "temporada"}
_ORDINALES = {"1st": "1", "2nd": "2", "3rd": "3", "first": "1", "second": "2", "third": "3",
              "fourth": "4", "fifth": "5", "sixth": "6", "seventh": "7", "ii": "2", "iii": "3"}


def clave(t: str) -> str:
    t = _PARENTESIS.sub(" ", unicodedata.normalize("NFKC", t or "")).casefold()
    t = re.sub(r"[^\w]+", " ", t)
    out = []
    for w in t.split():
        w = _ORDINALES.get(w, w)
        m = re.fullmatch(r"(\d+)(st|nd|rd|th)", w)
        if m:
            w = m.group(1)
        if w not in _RELLENO:
            out.append(w)
    return "".join(out)


def titulos_anilist(ids: list[int], post) -> dict[int, dict]:
    """{id: media} con títulos, sinónimos, formato y episodios de AniList."""
    out: dict[int, dict] = {}
    ids = sorted({int(i) for i in ids if i})
    for i in range(0, len(ids), 50):
        trozo = ids[i:i + 50]
        datos = post(_Q_TITULOS, {"ids": trozo, "page": 1}) or {}
        for m in ((datos.get("Page") or {}).get("media") or []):
            if m and m.get("id"):
                out[int(m["id"])] = m
    return out


def _eps_exactos(capitulos, media: dict) -> bool:
    m = re.fullmatch(r"\s*(\d+)\s*", str(capitulos or ""))
    return bool(m and media.get("episodes") and int(m.group(1)) == media["episodes"])


def _casa_titulo(nombre: str, media: dict, capitulos=None) -> bool:
    t = media.get("title") or {}
    variantes = [clave(v) for v in (t.get("romaji"), t.get("english"), t.get("native"),
                                    *(media.get("synonyms") or [])) if v]
    k = clave(nombre)
    if not k:
        return False
    if k in variantes:
        return True
    # «Mashiba vs. Kimura» = «Mashiba vs Kimura - Shikei Shikkou»: un título es
    # el principio del otro. Solo si además los episodios coinciden exactos
    # («Hajime no Ippo», 75, NO es «Hajime no Ippo: Rising», 25).
    return len(k) >= 12 and _eps_exactos(capitulos, media) and any(
        v.startswith(k) or k.startswith(v) for v in variantes if len(v) >= 12)


def _casan_episodios(capitulos, media: dict) -> bool:
    caps = str(capitulos or "").strip().lower()
    eps = media.get("episodes")
    if caps in ("", "?") or not eps:
        return True                                   # sin dato: no descarta
    if "pel" in caps:
        return media.get("format") == "MOVIE" or eps == 1
    m = re.match(r"(\d+)", caps)
    if not m:
        return True
    n = int(m.group(1))
    return n == eps or (caps.endswith("+") and n <= eps)


def _prioridad(a: dict) -> tuple:
    """Cuál se queda: el de AniList (nombre y datos más fiables), luego el que
    tenga más cosas tuyas (grupo, nota, puntuación, episodios)."""
    return ((a.get("fuente") or "") == "anilist", bool((a.get("grupo") or "").strip()),
            a.get("puntuacion") is not None, bool((a.get("notas") or "").strip()),
            int(a.get("episodios_vistos") or 0), -int(a.get("id") or 0))


def planificar(animes: list[dict], info: dict[int, dict]) -> list[tuple[str, list[str]]]:
    """[(se_queda, [se_funden…])] solo con lo que AniList confirma. Puro."""
    grupos: dict[tuple, list[dict]] = {}
    for a in animes:
        aid = int(a.get("anilist_id") or 0)
        if aid:
            grupos.setdefault((aid, a.get("tipo") or "anime"), []).append(a)
    plan = []
    for (aid, _tipo), miembros in grupos.items():
        if len(miembros) < 2 or aid not in info:
            continue
        media = info[aid]
        buenos = [a for a in miembros
                  if (_casa_titulo(a["nombre"], media, a.get("capitulos")) or (a.get("fuente") == "anilist"))
                  and _casan_episodios(a.get("capitulos"), media)]
        if len(buenos) < 2:
            continue
        buenos.sort(key=_prioridad, reverse=True)
        plan.append((buenos[0]["nombre"], [a["nombre"] for a in buenos[1:]]))
    return plan


def _fusionar(queda: str, otro: str) -> bool:
    ok, _ = db.fusionar_animes(queda, otro)
    if ok:
        # Lo que se guarda por nombre fuera de la tabla: que siga apuntando bien.
        import json
        for clave_cfg in ("animeav1_ids", "notif_last_seen"):
            try:
                d = json.loads(db.get_config(clave_cfg) or "{}")
                if isinstance(d, dict) and otro in d:
                    v = d.pop(otro)
                    d.setdefault(queda, v)
                    db.set_config(clave_cfg, json.dumps(d, ensure_ascii=False))
            except (ValueError, TypeError):
                pass
    return ok


def fusionar_repetidos(post) -> dict:
    """Junta los repetidos (mismo nombre normalizado, o mismo anime en AniList
    confirmado). Devuelve {fusionados, grupos, detalle}. Nunca lanza."""
    hechos: list[str] = []
    try:
        # 1) Mismo nombre salvo mayúsculas y signos («One-Punch Man»).
        for grupo in db.buscar_duplicados():
            for otro in grupo[1:]:
                if _fusionar(grupo[0], otro):
                    hechos.append(f"{otro} → {grupo[0]}")
        # 2) Mismo anilist_id con AniList confirmándolo.
        animes = db.listar_animes()
        ids = {}
        for a in animes:
            aid = int(a.get("anilist_id") or 0)
            if aid:
                ids[aid] = ids.get(aid, 0) + 1
        repetidos = [i for i, n in ids.items() if n > 1]
        if repetidos:
            info = titulos_anilist(repetidos, post)
            for queda, fuera in planificar(animes, info):
                for otro in fuera:
                    if _fusionar(queda, otro):
                        hechos.append(f"{otro} → {queda}")
    except Exception as e:  # noqa: BLE001
        log.warning("duplicados: %s", e)
    if hechos:
        log.info("Repetidos fusionados: %d", len(hechos))
    return {"fusionados": len(hechos), "detalle": hechos[:200]}
