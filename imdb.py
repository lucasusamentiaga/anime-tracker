"""Nota de IMDb para los animes (v2.16.1).

IMDb no tiene API gratuita, pero publica cada día sus notas en un archivo
(datasets.imdbws.com/title.ratings.tsv.gz, uso personal y no comercial). Lo que
falta es saber qué ficha de IMDb es cada anime: eso lo da Wikidata, que enlaza
el id de AniList (P8729) y el de MyAnimeList (P4086) con el de IMDb (P345).

Una vez por semana, en segundo plano, se bajan las dos cosas y se guarda solo
lo que hace falta (unas 6 000 notas, ~150 KB) en la carpeta de datos. Después
todo es local: ninguna búsqueda espera a IMDb.

IMDb puntúa la serie entera, no cada temporada: si una temporada no tiene
ficha propia, lleva la nota de su saga (no las películas, que tienen la suya).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("miraru.imdb")

URL_NOTAS = "https://datasets.imdbws.com/title.ratings.tsv.gz"
URL_WIKIDATA = "https://query.wikidata.org/sparql"
UA = "Miraru (https://github.com/lucasusamentiaga/anime-tracker)"
CADA = 7 * 86400
_ARCHIVO = "imdb_notas.json"

_mem: dict = {"datos": None, "ruta": None}
_lock = threading.Lock()


def _ruta(app_dir: Path) -> Path:
    return Path(app_dir) / _ARCHIVO


def cargar(app_dir: Path) -> dict:
    """{"al": {anilist_id: tconst}, "mal": {...}, "notas": {tconst: [nota, votos]}, "ts": …}"""
    with _lock:
        if _mem["datos"] is not None and _mem["ruta"] == str(app_dir):
            return _mem["datos"]
        try:
            d = json.loads(_ruta(app_dir).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("al", {})
        d.setdefault("mal", {})
        d.setdefault("notas", {})
        _mem.update(datos=d, ruta=str(app_dir))
        return d


def nota(datos: dict, anilist_id=0, id_mal=0):
    """(nota, votos, tconst) o None."""
    t = datos["al"].get(str(int(anilist_id or 0))) or datos["mal"].get(str(int(id_mal or 0)))
    n = datos["notas"].get(t) if t else None
    return (n[0], n[1], t) if n else None


def _sparql(prop: str, s) -> dict[str, str]:
    r = s.get(URL_WIKIDATA, params={"query": f"SELECT ?id ?imdb WHERE {{ ?i wdt:{prop} ?id; wdt:P345 ?imdb }}"},
              headers={"Accept": "text/csv", "User-Agent": UA}, timeout=90)
    r.raise_for_status()
    out = {}
    for fila in csv.DictReader(io.StringIO(r.text)):
        i, t = (fila.get("id") or "").strip(), (fila.get("imdb") or "").strip()
        if i.isdigit() and t.startswith("tt"):
            out.setdefault(i, t)
    return out


def actualizar(app_dir: Path, s=None) -> dict:
    """Baja Wikidata + notas de IMDb y lo guarda. Devuelve un resumen."""
    import requests
    s = s or requests.Session()
    al = _sparql("P8729", s)
    mal = _sparql("P4086", s)
    quiero = set(al.values()) | set(mal.values())
    notas: dict[str, list] = {}
    with s.get(URL_NOTAS, headers={"User-Agent": UA}, timeout=120, stream=True) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        with gzip.GzipFile(fileobj=r.raw) as gz:
            for linea in io.TextIOWrapper(gz, encoding="utf-8"):
                t, _, resto = linea.partition("\t")
                if t in quiero:
                    media, _, votos = resto.rstrip("\n").partition("\t")
                    try:
                        notas[t] = [float(media), int(votos)]
                    except ValueError:
                        pass
    datos = {"al": al, "mal": mal, "notas": notas, "ts": time.time()}
    tmp = _ruta(app_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, separators=(",", ":")), encoding="utf-8")
    tmp.replace(_ruta(app_dir))
    with _lock:
        _mem.update(datos=datos, ruta=str(app_dir))
    log.info("IMDb: %d animes enlazados, %d notas", len(al) + len(mal), len(notas))
    return {"enlaces": len(al) + len(mal), "notas": len(notas)}


def caducado(app_dir: Path) -> bool:
    d = cargar(app_dir)
    return time.time() - float(d.get("ts") or 0) > CADA


def notas_biblioteca(datos: dict, animes: list[dict], franquicias: list[dict] | None = None,
                     id_mal: dict | None = None) -> dict[str, float]:
    """{nombre: nota} para la lista. Las temporadas sin ficha propia llevan la
    de su saga (la ficha con más votos de la saga); las películas no."""
    id_mal = id_mal or {}
    out: dict[str, float] = {}
    votos: dict[str, int] = {}
    for a in animes:
        if (a.get("tipo") or "anime") == "manga":
            continue        # IMDb puntúa series y películas, no manga
        n = nota(datos, a.get("anilist_id"), id_mal.get(str(a.get("anilist_id") or 0)))
        if n:
            out[a["nombre"]] = n[0]
            votos[a["nombre"]] = n[1]
    for g in franquicias or []:
        miembros = g.get("animes") or []
        # La de la serie: entre las de la saga, la ficha con más votos (una OVA
        # o un especial con ficha propia no deben marcar la nota de todo).
        con = [m["nombre"] for m in miembros if m["nombre"] in out
               and "pel" not in str(m.get("capitulos") or "").lower()]
        if not con:
            continue
        base = out[max(con, key=lambda k: votos.get(k, 0))]
        for m in miembros:
            if m["nombre"] not in out and "pel" not in str(m.get("capitulos") or "").lower():
                out[m["nombre"]] = base
    return out
