"""v2.13: cajas de franquicia que el usuario puede cambiar y sagas completas.

Casos reales del usuario: "Rascal Does Not Dream of …" (5 títulos distintos)
y "Masamune-kun's Revenge R" salían sueltos; buscar "attack on titan" solo
ofrecía la primera temporada.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import franquicias as fq
from scrapers import anilist as al

ROOT = Path(__file__).resolve().parents[1]


def _grupos(nombres, **extra):
    animes = [dict({"nombre": n}, **extra.get(n, {})) for n in nombres]
    return {g["nombre"]: [a["nombre"] for a in g["animes"]]
            for g in fq.agrupar_franquicias(animes, extra.get("_rel"))}


# ── Agrupado automático ─────────────────────────────────────────────────────

def test_rascal_y_masamune_se_agrupan():
    g = _grupos([
        "Rascal Does Not Dream of Bunny Girl Senpai", "Rascal Does Not Dream of Santa Claus",
        "Rascal Does Not Dream of a Knapsack Kid", "Rascal Does Not Dream of a Dreaming Girl",
        "Masamune-kun's Revenge", "Masamune-kun's Revenge R"])
    assert len(g["Rascal Does Not Dream"]) == 4
    assert g["Masamune-kun's Revenge"] == ["Masamune-kun's Revenge", "Masamune-kun's Revenge R"]


@pytest.mark.parametrize("a,b", [
    ("A Certain Magical Index", "A Certain Scientific Railgun"),
    ("My Hero Academia", "My Dress-Up Darling"),
    ("Black Clover", "Black Bullet"),
    ("One Piece", "One Punch Man"),
    ("I Was Reincarnated as the 7th Prince so I Can Take My Time Perfecting My Magical Ability",
     "I Was Reincarnated as a Villainess"),
])
def test_titulos_parecidos_de_sagas_distintas_no_se_juntan(a, b):
    assert len(_grupos([a, b])) == 2


def test_final_season_va_despues_de_las_numeradas():
    g = _grupos(["Attack on Titan Final Season", "Attack on Titan Season 2", "Attack on Titan"])
    assert g["Attack on Titan"] == ["Attack on Titan", "Attack on Titan Season 2",
                                    "Attack on Titan Final Season"]


def test_relaciones_de_anilist_juntan_titulos_que_no_se_parecen():
    g = _grupos(["Fate/Zero", "Fate/stay night: Unlimited Blade Works"],
                **{"Fate/Zero": {"anilist_id": 10087},
                   "Fate/stay night: Unlimited Blade Works": {"anilist_id": 19603},
                   "_rel": {"10087": [19603]}})
    assert len(g) == 1


def test_nombre_comun():
    assert fq.nombre_comun(["Rascal Does Not Dream of Santa Claus",
                            "Rascal Does Not Dream of a Knapsack Kid"]) == "Rascal Does Not Dream"
    assert fq.nombre_comun(["Attack on Titan", "Attack on Titan: No Regrets"]) == "Attack on Titan"
    assert fq.nombre_comun(["Fate/Zero", "Fate/stay night"]) == "Fate/Zero"


# ── Grupos del usuario ──────────────────────────────────────────────────────

def test_grupo_manual_manda_y_se_une_al_automatico_del_mismo_nombre():
    g = _grupos(["WITCH WATCH", "Witch Hat Atelier", "Blue Box", "Blue Box Season 2"],
                **{"Witch Hat Atelier": {"grupo": "WITCH WATCH"},
                   "Blue Box Season 2": {"grupo": "-"}})
    assert sorted(g["WITCH WATCH"]) == ["WITCH WATCH", "Witch Hat Atelier"]
    assert g["Blue Box"] == ["Blue Box"]          # el suelto ya no entra
    animes = [{"nombre": "Witch Hat Atelier", "grupo": "Mis brujas"}]
    res = fq.agrupar_franquicias(animes)
    assert res[0]["nombre"] == "Mis brujas" and res[0]["manual"]


@pytest.fixture
def cliente(db):
    import main
    importlib.reload(main)
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c, main


def _alta(db, nombre, **kw):
    ok, _ = db.guardar_anime(dict({"nombre": nombre, "fuente": "test", "capitulos": "12"}, **kw))
    assert ok


def test_api_grupos_crear_renombrar_y_deshacer(cliente, db):
    c, _ = cliente
    for n in ("Fate/Zero", "Fate/stay night", "Steins;Gate"):
        _alta(db, n)
    assert {a["grupo"] for a in db.listar_animes_slim()} == {""}

    r = c.post("/api/grupos", json={"nombres": ["Fate/Zero", "Fate/stay night"], "grupo": "Fate"})
    assert r.status_code == 200 and r.json()["cambiados"] == 2
    fqs = {f["nombre"]: f for f in c.get("/api/franquicias").json()["franquicias"]}
    assert fqs["Fate"]["count"] == 2 and fqs["Fate"]["manual"]

    c.post("/api/grupos", json={"nombres": ["Fate/Zero", "Fate/stay night"], "grupo": "-"})
    fqs = c.get("/api/franquicias").json()["franquicias"]
    assert all(f["count"] == 1 for f in fqs)

    # Desde el editor (PATCH) también se cambia
    assert c.patch("/api/animes/Steins;Gate", json={"grupo": "Fate"}).status_code == 200
    assert db.obtener_anime("Steins;Gate")["grupo"] == "Fate"
    assert c.post("/api/grupos", json={"nombres": [], "grupo": "x"}).status_code == 422


def test_anadir_con_grupo(cliente, db, monkeypatch):
    c, main = cliente
    from scrapers.base import AnimeData

    async def _fake(url):
        return AnimeData(nombre="Attack on Titan Season 2", capitulos=12, imagen="https://s4.anilist.co/x.jpg",
                         genero=["Action"], sinopsis="", fuente="anilist",
                         estado_anime="Finalizado", anilist_id=20958), "anilist"
    monkeypatch.setattr(main, "_resolver_desde_url", _fake)
    r = c.post("/api/animes", json={"nombre": "https://anilist.co/anime/20958", "fuente": "anilist",
                                    "grupo": "Attack on Titan"})
    assert r.status_code == 200
    assert db.obtener_anime("Attack on Titan Season 2")["grupo"] == "Attack on Titan"


# ── Saga completa al buscar ─────────────────────────────────────────────────

def _m(i, titulo, fmt="TV", rels=(), anio=2013, eps=12):
    return {"id": i, "title": {"english": titulo, "romaji": titulo}, "episodes": eps, "format": fmt,
            "type": "ANIME", "coverImage": {"large": f"https://s4.anilist.co/{i}.jpg"}, "genres": [],
            "status": "FINISHED", "startDate": {"year": anio, "month": 4, "day": 1},
            "relations": {"edges": [{"relationType": t, "node": {"id": j, "type": "ANIME"}}
                                    for t, j in rels]}}


def test_franquicia_sigue_las_relaciones_y_pide_lo_que_falta():
    buscar = [_m(1, "Attack on Titan", rels=[("SEQUEL", 2), ("SPIN_OFF", 9)]),
              _m(2, "Attack on Titan Season 2", anio=2017, rels=[("PREQUEL", 1), ("SEQUEL", 3)]),
              _m(9, "Attack on Titan: Junior High", anio=2015),
              _m(7, "Shingeki! Kyojin Chuugakkou MV", fmt="MUSIC")]
    por_ids = [_m(3, "Attack on Titan Season 3", anio=2018, rels=[("PREQUEL", 2), ("SIDE_STORY", 4)]),
               _m(4, "Attack on Titan: Lost Girls", fmt="OVA", anio=2017)]
    llamadas = []

    def post(query, variables):
        llamadas.append(variables)
        if "search" in variables:
            return {"Page": {"media": buscar}}
        return {"Page": {"media": [m for m in por_ids if m["id"] in variables["ids"]]}}

    out = al.franquicia("attack on titan", post=post)
    assert [e["nombre"] for e in out] == ["Attack on Titan", "Attack on Titan Season 2",
                                          "Attack on Titan: Lost Girls", "Attack on Titan Season 3"]
    assert out[0]["raiz"] and out[2]["formato"] == "OVA"
    assert len(llamadas) <= 3


def test_franquicia_nunca_lanza():
    def post(*_a):
        raise RuntimeError("AniList caído")
    assert al.franquicia("x", post=post) == []
    assert al.relaciones_por_ids([1, 2], post=post) == {}


def test_api_buscar_franquicia_marca_lo_que_ya_tienes(cliente, db, monkeypatch):
    c, _ = cliente
    _alta(db, "Attack on Titan", anilist_id=1)
    ents = [{"anilist_id": 1, "nombre": "Attack on Titan", "formato": "TV", "capitulos": 25,
             "estado_anime": "Finalizado", "imagen": "", "genero": [], "anio": 2013, "mes": 4,
             "dia": 7, "raiz": True},
            {"anilist_id": 2, "nombre": "Attack on Titan Season 2", "formato": "TV", "capitulos": 12,
             "estado_anime": "Finalizado", "imagen": "", "genero": [], "anio": 2017, "mes": 4,
             "dia": 1, "raiz": False}]
    monkeypatch.setattr(al, "franquicia", lambda q: ents)
    d = c.post("/api/buscar/franquicia", json={"nombre": "attack on titan zz"}).json()
    assert d["ok"] and d["nombre"] == "Attack on Titan"
    assert [e["en_lista"] for e in d["entradas"]] == [True, False]


def test_relaciones_se_guardan_y_agrupan(cliente, db):
    _, main = cliente
    _alta(db, "Fate/Zero", anilist_id=10087)
    _alta(db, "Fate/stay night: Unlimited Blade Works", anilist_id=19603)

    class FakeAL:
        pedidos = []

        @classmethod
        def relaciones_por_ids(cls, ids):
            cls.pedidos.append(list(ids))
            return {10087: [19603]}

    assert main._actualizar_relaciones(db.listar_animes_slim(), FakeAL, sleep=lambda s: None) == 2
    # La segunda vez no vuelve a preguntar
    assert main._actualizar_relaciones(db.listar_animes_slim(), FakeAL, sleep=lambda s: None) == 0
    assert len(FakeAL.pedidos) == 1
    fqs = TestClient(main.app).get("/api/franquicias").json()["franquicias"]
    assert any(f["count"] == 2 for f in fqs)


def test_la_pagina_tiene_grupos_y_saga():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    for trozo in ("bulkAgrupar()", "/api/buscar/franquicia", 'id="edit-grupo"', "renombrarGrupo(fq)",
                  "deshacerGrupo(fq)", "'/api/grupos'", 'id="modal-grupo"', "sacarDelGrupo(",
                  "addEventListener('drop'", "card.draggable = true"):
        assert trozo in html, trozo


def _k(i, titulo, subtype="TV", rels=(), fecha="2013-04-07", slug=None):
    item = {"id": str(i), "type": "anime",
            "attributes": {"canonicalTitle": titulo, "titles": {"en": titulo}, "subtype": subtype,
                           "episodeCount": 12, "startDate": fecha, "slug": slug or f"s{i}",
                           "posterImage": {"large": f"https://media.kitsu.app/{i}.jpg"}, "status": "finished"},
            "relationships": {"mediaRelationships": {"data": [
                {"type": "mediaRelationships", "id": f"r{i}-{j}"} for _, j in rels]}}}
    incl = [{"type": "mediaRelationships", "id": f"r{i}-{j}", "attributes": {"role": role},
             "relationships": {"destination": {"data": {"type": "anime", "id": str(j)}}}}
            for role, j in rels]
    return item, incl


def test_kitsu_da_la_saga_si_anilist_esta_caido():
    from scrapers import kitsu
    a, ia = _k(1, "Attack on Titan", rels=[("sequel", 2), ("spinoff", 9)])
    b, ib = _k(2, "Attack on Titan Season 2", fecha="2017-04-01", rels=[("prequel", 1), ("sequel", 3)])
    c, ic = _k(3, "Attack on Titan Season 3", fecha="2018-07-22", rels=[("prequel", 2)])
    m, im = _k(4, "Attack on Titan: Chronicle", subtype="movie", fecha="2020-07-17")

    def get(params):
        if "filter[text]" in params:
            return {"data": [a, b, m], "included": ia + ib + im}
        assert params["filter[id]"] == "3"
        return {"data": [c], "included": ic}

    out = kitsu.franquicia("attack on titan", get=get)
    assert [e["nombre"] for e in out] == ["Attack on Titan", "Attack on Titan Season 2",
                                          "Attack on Titan Season 3"]
    assert out[2]["url"] == "https://kitsu.io/anime/s3"
    assert kitsu.franquicia("x", get=lambda p: (_ for _ in ()).throw(RuntimeError())) == []


def test_api_franquicia_usa_kitsu_si_anilist_no_responde(cliente, db, monkeypatch):
    c, _ = cliente
    from scrapers import kitsu
    monkeypatch.setattr(al, "franquicia", lambda q: [])
    monkeypatch.setattr(kitsu, "franquicia", lambda q: [
        {"kitsu_id": "1", "anilist_id": 0, "nombre": "Attack on Titan", "formato": "TV", "capitulos": 25,
         "estado_anime": "", "imagen": "", "genero": [], "anio": 2013, "mes": 4, "dia": 7, "raiz": True,
         "url": "https://kitsu.io/anime/attack-on-titan", "titulos": ["Shingeki no Kyojin"]},
        {"kitsu_id": "2", "anilist_id": 0, "nombre": "Attack on Titan Season 2", "formato": "TV",
         "capitulos": 12, "estado_anime": "", "imagen": "", "genero": [], "anio": 2017, "mes": 4, "dia": 1,
         "raiz": False, "url": "https://kitsu.io/anime/s2", "titulos": []}])
    _alta(db, "Shingeki no Kyojin")
    d = c.post("/api/buscar/franquicia", json={"nombre": "aot kitsu"}).json()
    assert d["fuente"] == "kitsu" and [e["en_lista"] for e in d["entradas"]] == [True, False]


def test_url_de_kitsu_app_se_reconoce():
    import main
    assert main._detect_url("https://kitsu.app/anime/attack-on-titan") == ("kitsu", "slug", "attack-on-titan")


def test_la_pagina_no_usa_prompt_para_los_grupos():
    """Los nombres se piden en una ventana propia con portadas y grupos existentes,
    no con prompt()/confirm() del navegador."""
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    i = html.index("async function renombrarGrupo")
    j = html.index("// Editor: lista de grupos existentes")
    assert "prompt(" not in html[i:j] and "confirm(" not in html[i:j]
