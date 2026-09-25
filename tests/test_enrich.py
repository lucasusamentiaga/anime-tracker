"""
Tests del enriquecimiento AniList (daemon _start_enrich_unknown_eps).

Animes con anilist_id se resuelven por lotes de IDs (1 petición por 50)
en lugar de búsquedas por nombre; los que no tienen ID caen a búsqueda.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scrapers.base import AnimeData


def _ad(caps, img="https://s4.anilist.co/cover.jpg", aid=1, vols=0, tipo="anime"):
    return AnimeData(nombre="x", capitulos=caps, imagen=img, genero=[], sinopsis="",
                     fuente="anilist", estado_anime="Finalizado", anilist_id=aid,
                     tipo=tipo, volumenes_totales=vols)


class _FakeAniList:
    def __init__(self, by_id=None, by_name=None):
        self.by_id = by_id or {}
        self.by_name = by_name or {}
        self.id_calls: list[list[int]] = []
        self.name_calls: list[str] = []

    def buscar_por_ids(self, ids, media_type="ANIME"):
        self.id_calls.append(list(ids))
        return {i: self.by_id[i] for i in ids if i in self.by_id}

    def buscar(self, nombre, media_type="ANIME"):
        self.name_calls.append(nombre)
        return self.by_name.get(nombre)

    def buscar_manga(self, nombre):
        return self.buscar(nombre, "MANGA")


@pytest.fixture
def main_mod(db, monkeypatch):
    import main
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(main.db, "refrescar_metadata_anime",
                        lambda n, c: (calls.append((n, c)), (True, "ok"))[1])
    main._calls = calls
    return main


def test_lote_por_ids_una_sola_peticion(main_mod):
    animes = [{"nombre": f"A{i}", "capitulos": "?", "imagen": "https://x/animeflv/a.jpg",
               "anilist_id": i} for i in range(1, 61)]
    fake = _FakeAniList(by_id={i: _ad(12, aid=i) for i in range(1, 61)})
    eps, imgs = main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None)
    assert eps == 60 and imgs == 60
    assert [len(c) for c in fake.id_calls] == [50, 10]
    assert fake.name_calls == []


def test_sin_id_cae_a_busqueda_por_nombre(main_mod):
    animes = [{"nombre": "Foo", "capitulos": "?", "imagen": "https://ok/img.jpg"}]
    fake = _FakeAniList(by_name={"Foo": _ad("película", aid=77)})
    eps, imgs = main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None)
    assert (eps, imgs) == (1, 0)
    assert main_mod._calls == [("Foo", {"capitulos": "película", "anilist_id": 77})]


def test_no_toca_animes_completos(main_mod):
    animes = [{"nombre": "Ok", "capitulos": "24", "imagen": "https://s4.anilist.co/c.jpg",
               "anilist_id": 5}]
    fake = _FakeAniList()
    assert main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None) == (0, 0)
    assert fake.id_calls == [] and fake.name_calls == []


def test_en_emision_se_actualiza_solo_si_cambia(main_mod):
    animes = [{"nombre": "OP", "capitulos": "1120+", "imagen": "https://ok/i.jpg", "anilist_id": 21},
              {"nombre": "Igual", "capitulos": "50+", "imagen": "https://ok/i.jpg", "anilist_id": 22}]
    fake = _FakeAniList(by_id={21: _ad("1125+", aid=21), 22: _ad("50+", aid=22)})
    eps, _ = main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None)
    assert eps == 1
    assert main_mod._calls == [("OP", {"capitulos": "1125+"})]


def test_no_sobrescribe_con_interrogante_ni_portada_animeflv(main_mod):
    animes = [{"nombre": "B", "capitulos": "?", "imagen": "", "anilist_id": 9}]
    fake = _FakeAniList(by_id={9: _ad("?", img="https://animeflv.net/x.jpg", aid=9)})
    assert main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None) == (0, 0)
    assert main_mod._calls == []


def test_manga_usa_tipo_manga_y_rellena_volumenes(main_mod):
    animes = [{"nombre": "M", "capitulos": "?", "imagen": "https://ok/i.jpg",
               "anilist_id": 30, "tipo": "manga", "volumenes_totales": 0}]
    fake = _FakeAniList(by_id={30: _ad(200, aid=30, vols=20, tipo="manga")})
    orig = fake.buscar_por_ids
    tipos = []
    fake.buscar_por_ids = lambda ids, media_type="ANIME": (tipos.append(media_type), orig(ids))[1]
    main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None)
    assert tipos == ["MANGA"]
    assert main_mod._calls == [("M", {"capitulos": "200", "volumenes_totales": 20})]


# ── Scraper: buscar_por_ids ──────────────────────────────────────────────────

def _resp(body):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = body
    r.raise_for_status.return_value = None
    return r


def test_scraper_buscar_por_ids_parsea_pagina():
    from scrapers.anilist import AniListScraper
    body = {"data": {"Page": {"media": [
        {"id": 1, "title": {"romaji": "A", "english": None}, "episodes": 12, "format": "TV",
         "coverImage": {"large": "https://c/1.jpg"}, "genres": [], "status": "FINISHED"},
        {"id": 2, "title": {"romaji": "B", "english": "Bee"}, "episodes": None, "format": "TV",
         "coverImage": {"large": "https://c/2.jpg"}, "genres": [], "status": "RELEASING",
         "nextAiringEpisode": {"episode": 8}},
    ]}}}
    with patch("scrapers.anilist._session.post", return_value=_resp(body)) as p:
        out = AniListScraper().buscar_por_ids([1, 2])
    assert p.call_count == 1
    assert out[1].capitulos == 12 and out[2].capitulos == "7+"
    assert out[2].nombre == "Bee"


def test_scraper_buscar_por_ids_vacio_y_error():
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    assert s.buscar_por_ids([]) == {}
    with patch("scrapers.anilist._session.post", side_effect=Exception("boom")):
        assert s.buscar_por_ids([1]) == {}


# ── Variantes de título (nombres heredados de AnimeFLV) ──────────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("Black Clover (TV)", "Black Clover"),
    ("Baki (2018)", "Baki"),
    ("Haikyuu!! Movie: Gomisuteba no Kessen", "Haikyuu!! Gomisuteba no Kessen"),
    ("Boku no Hero Academia the Movie 2: Heroes:Rising", "Boku no Hero Academia Heroes:Rising"),
])
def test_candidatos_busqueda(entrada, esperado):
    from scrapers.anilist import candidatos_busqueda
    c = candidatos_busqueda(entrada)
    assert c[0] == entrada and esperado in c


def test_candidatos_titulo_limpio_no_duplica():
    from scrapers.anilist import candidatos_busqueda
    assert candidatos_busqueda("Cowboy Bebop") == ["Cowboy Bebop"]


def test_buscar_reintenta_con_variante_si_404():
    from scrapers.anilist import AniListScraper
    vacio = {"data": {"Media": None}}
    ok = {"data": {"Media": {"id": 3, "title": {"romaji": "Black Clover", "english": None},
                             "episodes": 170, "format": "TV", "coverImage": {"large": "https://c"},
                             "genres": [], "status": "FINISHED"}}}
    with patch("scrapers.anilist._session.post", side_effect=[_resp(vacio), _resp(ok)]) as p:
        r = AniListScraper().buscar("Black Clover (TV)")
    assert r.capitulos == 170 and r.anilist_id == 3
    assert p.call_args_list[1].kwargs["json"]["variables"]["search"] == "Black Clover"


# ── Fallback MyAnimeList → AniList (idMal) ───────────────────────────────────

class _ALconMal(_FakeAniList):
    def __init__(self, by_mal, **kw):
        super().__init__(**kw)
        self.by_mal = by_mal
        self.mal_calls: list[int] = []

    def buscar_por_mal(self, mal_id, media_type="ANIME"):
        self.mal_calls.append(mal_id)
        return self.by_mal.get(mal_id)


class _Jikan:
    def __init__(self, ids):
        self.ids = ids
        self.calls: list[str] = []

    def buscar_mal_id(self, nombre):
        self.calls.append(nombre)
        return self.ids.get(nombre, 0)


def test_resolver_usa_mal_si_anilist_no_encuentra(main_mod):
    al = _ALconMal({38080: _ad(12, aid=103572)})
    jk = _Jikan({"Gotoubun no Hanayome": 38080})
    r = main_mod._resolver_en_anilist("Gotoubun no Hanayome", anilist=al, jikan=jk)
    assert r.anilist_id == 103572 and al.mal_calls == [38080]


def test_resolver_no_llama_a_mal_si_anilist_encuentra(main_mod):
    al = _ALconMal({}, by_name={"Foo": _ad(10, aid=1)})
    jk = _Jikan({})
    assert main_mod._resolver_en_anilist("Foo", anilist=al, jikan=jk).anilist_id == 1
    assert jk.calls == []


def test_resolver_manga_no_usa_mal(main_mod):
    al = _ALconMal({})
    jk = _Jikan({"M": 5})
    assert main_mod._resolver_en_anilist("M", "manga", anilist=al, jikan=jk) is None
    assert jk.calls == []


def test_resolver_mal_sin_resultado(main_mod):
    al = _ALconMal({})
    jk = _Jikan({})
    assert main_mod._resolver_en_anilist("Nada", anilist=al, jikan=jk) is None
    assert al.mal_calls == []


def test_scraper_buscar_por_mal():
    from scrapers.anilist import AniListScraper
    body = {"data": {"Media": {"id": 103572, "title": {"romaji": "5-toubun no Hanayome",
            "english": "The Quintessential Quintuplets"}, "episodes": 12, "format": "TV",
            "coverImage": {"large": "https://c"}, "genres": [], "status": "FINISHED"}}}
    with patch("scrapers.anilist._session.post", return_value=_resp(body)) as p:
        r = AniListScraper().buscar_por_mal(38080)
    assert r.anilist_id == 103572 and r.capitulos == 12
    assert p.call_args.kwargs["json"]["variables"]["mal"] == 38080
    assert AniListScraper().buscar_por_mal(0) is None


def test_jikan_buscar_mal_id():
    from scrapers.jikan import JikanV4Scraper
    r = MagicMock()
    r.json.return_value = {"data": [{"mal_id": 38080}]}
    r.raise_for_status.return_value = None
    with patch("scrapers.jikan._session.get", return_value=r):
        assert JikanV4Scraper().buscar_mal_id("Gotoubun no Hanayome") == 38080
    with patch("scrapers.jikan._session.get", side_effect=Exception("504")):
        assert JikanV4Scraper().buscar_mal_id("x") == 0


def test_candidatos_normaliza_numeral_unicode():
    from scrapers.anilist import candidatos_busqueda
    assert "Date A Live III" in candidatos_busqueda("Date A Live Ⅲ")


def test_portada_anime_planet_se_sustituye(main_mod):
    animes = [{"nombre": "Naruto", "capitulos": "220", "anilist_id": 20,
               "imagen": "https://cdn.anime-planet.com/anime/primary/road-of-naruto-1.webp"}]
    fake = _FakeAniList(by_id={20: _ad(220, img="https://s4.anilist.co/naruto.jpg", aid=20)})
    assert main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None) == (0, 1)
    assert main_mod._calls == [("Naruto", {"imagen": "https://s4.anilist.co/naruto.jpg"})]


def test_portada_kitsu_no_se_toca(main_mod):
    animes = [{"nombre": "K", "capitulos": "12", "anilist_id": 1,
               "imagen": "https://media.kitsu.app/anime/poster_images/1/large.jpg"}]
    fake = _FakeAniList()
    assert main_mod._enriquecer_desde_anilist(animes, fake, sleep=lambda s: None) == (0, 0)
    assert fake.id_calls == []
