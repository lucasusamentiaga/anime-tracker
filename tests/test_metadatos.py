"""
Reglas de actualización segura de metadatos (metadatos.cambios_seguros) y su
uso en el refresco en emisión (cada 12h) y en el refresco manual.

Regresiones: se sobrescribía "1179+" con "?" y portadas de AniList con las de
anime-planet (que suelen ser de otra serie).
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

import metadatos
import migrations

AL = "https://s4.anilist.co/file/anilistcdn/media/anime/cover/x.jpg"
AP = "https://cdn.anime-planet.com/anime/primary/road-of-naruto.webp"
FLV = "https://www3.animeflv.net/uploads/animes/covers/1.jpg"
KITSU = "https://media.kitsu.app/anime/poster_images/1/large.jpg"


def _n(**kw):
    base = {"capitulos": "?", "imagen": "", "sinopsis": "", "genero": [],
            "estado_anime": "", "anilist_id": 0, "volumenes_totales": 0}
    base.update(kw)
    return NS(**base)


def test_no_pone_interrogante_sobre_numero_conocido():
    assert "capitulos" not in metadatos.cambios_seguros({"capitulos": "1179+"}, _n(capitulos="?"))


def test_actualiza_numero_conocido():
    assert metadatos.cambios_seguros({"capitulos": "12"}, _n(capitulos=13))["capitulos"] == "13"


@pytest.mark.parametrize("actual, nueva, cambia", [
    (AL, AP, False),        # nunca a anime-planet
    (AL, FLV, False),       # nunca a animeflv
    (AL, KITSU, False),     # no se cambia AniList por otra que no sea AniList
    (AP, KITSU, True),      # poco fiable → cualquiera fiable
    ("", KITSU, True),
    (KITSU, AL, True),      # AniList siempre es bienvenida
    (AL, AL + "?v2", True),
])
def test_reglas_de_portada(actual, nueva, cambia):
    c = metadatos.cambios_seguros({"imagen": actual}, _n(imagen=nueva))
    assert ("imagen" in c) is cambia


def test_estado_desconocido_no_sobrescribe():
    assert "estado_anime" not in metadatos.cambios_seguros(
        {"estado_anime": "En emisión"}, _n(estado_anime="Desconocido"))


def test_anilist_id_solo_si_falta():
    assert metadatos.cambios_seguros({"anilist_id": 0}, _n(anilist_id=5))["anilist_id"] == 5
    assert "anilist_id" not in metadatos.cambios_seguros({"anilist_id": 9}, _n(anilist_id=5))


def test_genero_lista_se_une_con_coma_espacio():
    assert metadatos.cambios_seguros({"genero": ""}, _n(genero=["A", "B"]))["genero"] == "A, B"


# ── Refresco en emisión (migrations) ─────────────────────────────────────────

class _DB:
    def __init__(self, animes):
        self.animes, self.updates = animes, {}
    def listar_animes(self):
        return self.animes
    def refrescar_metadata_anime(self, n, c):
        self.updates[n] = c
        return True, "ok"


class _AL:
    def __init__(self, by_id=None, by_name=None):
        self.by_id, self.by_name, self.id_calls = by_id or {}, by_name or {}, []
    def buscar_por_ids(self, ids, media_type="ANIME"):
        self.id_calls.append(list(ids))
        return {i: self.by_id[i] for i in ids if i in self.by_id}
    def buscar(self, n, media_type="ANIME"):
        return self.by_name.get(n)


def test_emision_no_estropea_one_piece(monkeypatch):
    db = _DB([{"nombre": "One Piece", "capitulos": "1179+", "estado_anime": "En emisión",
               "imagen": AL, "fuente": "animeplanet", "anilist_id": 0}])
    ap = NS(buscar=lambda n: _n(capitulos="?", imagen=AP, estado_anime="En emisión"))
    monkeypatch.setattr(migrations, "db", db)
    monkeypatch.setattr(migrations, "SCRAPERS", {"animeplanet": ap})
    migrations.refrescar_en_emision(sleep=0)
    assert db.updates == {}


def test_emision_usa_lote_por_id(monkeypatch):
    db = _DB([{"nombre": "OP", "capitulos": "1179+", "estado_anime": "En emisión",
               "imagen": AL, "anilist_id": 21, "fuente": "animeplanet"}])
    al = _AL(by_id={21: _n(capitulos="1180+", imagen=AL, estado_anime="En emisión", anilist_id=21)})
    monkeypatch.setattr(migrations, "db", db)
    monkeypatch.setattr(migrations, "SCRAPERS", {"anilist": al})
    assert migrations.refrescar_en_emision(sleep=0) == 1
    assert al.id_calls == [[21]]
    assert db.updates["OP"] == {"capitulos": "1180+"}


# ── Refresco manual (main._refrescar_todo) ───────────────────────────────────

@pytest.fixture
def main_mod(db, monkeypatch):
    import main
    calls = []
    monkeypatch.setattr(main.db, "refrescar_metadata_anime",
                        lambda n, c: (calls.append((n, c)), (True, "ok"))[1])
    main._calls = calls
    return main


def test_refresco_manual_por_id_y_por_nombre(main_mod):
    animes = [
        {"nombre": "A", "capitulos": "?", "imagen": AP, "anilist_id": 1},
        {"nombre": "B", "capitulos": "12", "imagen": AL, "anilist_id": 0},
        {"nombre": "C", "capitulos": "12", "imagen": AL, "anilist_id": 0},
    ]
    al = _AL(by_id={1: _n(capitulos=24, imagen=AL, anilist_id=1)},
             by_name={"B": _n(capitulos=12, imagen=AL, anilist_id=2)})
    estado: dict = {}
    main_mod._refrescar_todo(animes, estado, anilist=al, sleep=lambda s: None)
    assert estado["total"] == 3 and estado["hechos"] == 3
    assert estado["actualizados"] == 2 and estado["fallidos"] == ["C"]
    assert ("A", {"capitulos": "24", "imagen": AL}) in main_mod._calls
    assert ("B", {"anilist_id": 2}) in main_mod._calls


def test_endpoint_refrescar_vuelve_al_momento(main_mod, monkeypatch):
    import threading

    from fastapi.testclient import TestClient
    evento = threading.Event()

    def lento(animes, estado, **kw):
        estado.update(total=len(animes))
        evento.wait(5)
    monkeypatch.setattr(main_mod, "_refrescar_todo", lento)
    main_mod._refresco_estado.clear(); main_mod._refresco_estado["en_curso"] = False
    c = TestClient(main_mod.app, client=("127.0.0.1", 1))
    r1 = c.post("/api/animes/refrescar", json={}).json()
    assert r1["iniciado"] is True
    assert c.get("/api/refrescar/estado").json()["en_curso"] is True
    r2 = c.post("/api/animes/refrescar", json={}).json()
    assert r2["iniciado"] is False            # no lanza dos a la vez
    evento.set()
    for _ in range(50):
        if not c.get("/api/refrescar/estado").json()["en_curso"]:
            break
        __import__("time").sleep(0.05)
    assert c.get("/api/refrescar/estado").json()["en_curso"] is False
