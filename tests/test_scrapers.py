"""
Tests de scrapers con HTTP mockeado — no tocan la red.

Validan el contrato AnimeData y el parsing de respuestas conocidas.
Si una API externa cambia su esquema, este test seguirá pasando (es la
realidad de scraping). Cubre lo que SÍ controlamos: que parseamos bien
una respuesta válida y que no crasheamos con una inválida.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ── AniList ───────────────────────────────────────────────────────────────────

ANILIST_RESPONSE = {
    "data": {
        "Media": {
            "title": {"romaji": "Cowboy Bebop", "english": "Cowboy Bebop", "native": ""},
            "episodes": 26,
            "format": "TV",
            "coverImage": {"large": "https://example/cover.jpg"},
            "genres": ["Action", "Sci-Fi"],
            "description": "Space cowboys bounty hunters.",
            "status": "FINISHED",
        }
    }
}


def _mock_resp(status=200, json_body=None):
    r = MagicMock()
    r.status_code = status
    r.raise_for_status = lambda: None if 200 <= status < 400 else (_ for _ in ()).throw(Exception("HTTP"))
    r.json = lambda: json_body or {}
    r.text = json.dumps(json_body) if json_body is not None else ""
    return r


def test_anilist_scraper_parsea_respuesta_valida():
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    with patch("scrapers.anilist._session.post", return_value=_mock_resp(200, ANILIST_RESPONSE)):
        r = s.buscar("Cowboy Bebop")
    assert r is not None
    assert r.nombre == "Cowboy Bebop"
    assert r.capitulos == 26
    assert r.estado_anime == "Finalizado"
    assert "Action" in r.genero
    assert r.fuente == "anilist"


def test_anilist_scraper_devuelve_none_si_no_hay_media():
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    with patch("scrapers.anilist._session.post", return_value=_mock_resp(200, {"data": {"Media": None}})):
        r = s.buscar("xyz inexistente")
    assert r is None


def test_anilist_scraper_pelicula_sin_episodes():
    """Película detectada correctamente por format=MOVIE, no por episodes=0."""
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    body = json.loads(json.dumps(ANILIST_RESPONSE))
    body["data"]["Media"]["episodes"] = 0
    body["data"]["Media"]["format"] = "MOVIE"
    with patch("scrapers.anilist._session.post", return_value=_mock_resp(200, body)):
        r = s.buscar("X")
    assert r.capitulos == "película"


def test_anilist_scraper_devuelve_episodios_reales_incluso_si_son_muchos():
    """Antes el scraper clamp-aba a 200. Ahora debe devolver el número real
    (One Piece tiene >1100 episodios; el cap a 200 falsificaba los datos)."""
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    body = json.loads(json.dumps(ANILIST_RESPONSE))
    body["data"]["Media"]["episodes"] = 1100
    with patch("scrapers.anilist._session.post", return_value=_mock_resp(200, body)):
        r = s.buscar("One Piece")
    assert r.capitulos == 1100


def test_anilist_scraper_marca_pelicula_por_format_no_por_episodios_cero():
    """Si AniList devuelve episodes=null pero format=MOVIE → 'película'.
    Si format no es MOVIE y no hay episodios → '?' (desconocido), NO 'película'."""
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    # Caso 1: película de verdad
    body = json.loads(json.dumps(ANILIST_RESPONSE))
    body["data"]["Media"]["episodes"] = None
    body["data"]["Media"]["format"] = "MOVIE"
    with patch("scrapers.anilist._session.post", return_value=_mock_resp(200, body)):
        r = s.buscar("X")
    assert r.capitulos == "película"
    # Caso 2: anime en emisión sin total conocido
    body["data"]["Media"]["format"] = "TV"
    body["data"]["Media"]["episodes"] = None
    with patch("scrapers.anilist._session.post", return_value=_mock_resp(200, body)):
        r = s.buscar("Y")
    assert r.capitulos == "?"


def test_anilist_scraper_no_explota_en_excepcion():
    from scrapers.anilist import AniListScraper
    s = AniListScraper()
    with patch("scrapers.anilist._session.post", side_effect=ConnectionError("network down")):
        r = s.buscar("X")
    assert r is None


# ── Jikan ─────────────────────────────────────────────────────────────────────

JIKAN_RESPONSE = {
    "data": [{
        "title": "Naruto",
        "title_english": "Naruto",
        "episodes": 220,
        "type": "TV",
        "status": "Finished Airing",
        "images": {"jpg": {"large_image_url": "https://example/naruto.jpg"}},
        "genres": [{"name": "Action"}, {"name": "Shounen"}],
        "themes": [{"name": "Martial Arts"}],
        "synopsis": "Ninja kid.",
        "season": "fall",
        "year": 2002,
    }]
}


def test_jikan_scraper_parsea_temporada():
    from scrapers.jikan import JikanV4Scraper
    s = JikanV4Scraper()
    with patch("scrapers.jikan._session.get", return_value=_mock_resp(200, JIKAN_RESPONSE)):
        r = s.buscar("Naruto")
    assert r is not None
    assert r.nombre == "Naruto"
    assert r.capitulos == 220  # Naruto tiene 220 episodios reales, sin cap
    assert r.estado_anime == "Finalizado"
    assert r.__dict__.get("temporada") == "Otoño 2002"
    assert "Martial Arts" in r.genero  # themes mezclados con genres


def test_jikan_scraper_lista_vacia():
    from scrapers.jikan import JikanV4Scraper
    s = JikanV4Scraper()
    with patch("scrapers.jikan._session.get", return_value=_mock_resp(200, {"data": []})):
        r = s.buscar("nada")
    assert r is None


def test_jikan_scraper_movie():
    from scrapers.jikan import JikanV4Scraper
    s = JikanV4Scraper()
    body = json.loads(json.dumps(JIKAN_RESPONSE))
    body["data"][0]["type"] = "Movie"
    body["data"][0]["episodes"] = 1
    with patch("scrapers.jikan._session.get", return_value=_mock_resp(200, body)):
        r = s.buscar("X")
    assert r.capitulos == "película"


# ── AnimeFLV ────────────────────────────────────────────────────────────────
# Regresión: antes el default de capitulos era "película", así que una serie
# cuya página no exponía el bloque "Episodios" quedaba mal marcada como peli.

def _mock_session(html: str, status: int = 200):
    """Devuelve un objeto tipo requests.Session falso cuyo .get responde html."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_animeflv_serie_no_se_marca_como_pelicula_por_defecto():
    # Serie sin bloque de episodios: debe contar los capitulos listados
    # (ListCaps), nunca caer en pelicula por defecto.
    from scrapers.animeflv import AnimeFLVScraper
    html = """
    <html><body>
      <h1 class="Title">Naruto</h1>
      <nav class="Nvgnrs"><a>Accion</a></nav>
      <span class="fa-tv"></span> En emision
      <ul class="ListCaps"><li>1</li><li>2</li><li>3</li></ul>
    </body></html>
    """
    with patch("scrapers.animeflv._session", return_value=_mock_session(html)):
        r = AnimeFLVScraper().buscar("Naruto")
    assert r is not None
    assert r.capitulos != "película"   # el bug lo marcaba como película
    assert r.capitulos == 3            # cuenta los episodios listados


def test_animeflv_pelicula_detectada_por_tipo():
    """Si la pagina marca Tipo: Pelicula y no hay episodios -> 'pelicula'."""
    from scrapers.animeflv import AnimeFLVScraper
    html = """
    <html><body>
      <h1 class="Title">A Silent Voice</h1>
      <nav class="Nvgnrs"><a>Drama</a></nav>
      <ul class="ListInfo"><li>Tipo: Película</li></ul>
    </body></html>
    """
    with patch("scrapers.animeflv._session", return_value=_mock_session(html)):
        r = AnimeFLVScraper().buscar("A Silent Voice")
    assert r is not None
    assert r.capitulos == "película"


# ── MAL (Jikan) ───────────────────────────────────────────────────────────────

MAL_RESPONSE = {"data": [{
    "title": "Bleach", "title_english": "Bleach", "episodes": 366, "type": "TV",
    "status": "Finished Airing",
    "images": {"jpg": {"large_image_url": "https://example/bleach.jpg"}},
    "genres": [{"name": "Action"}], "synopsis": "Soul reaper.",
}]}


def test_mal_scraper_parsea_respuesta_valida():
    from scrapers.mal import MALScraper
    with patch("scrapers.mal._session.get", return_value=_mock_resp(200, MAL_RESPONSE)):
        r = MALScraper().buscar("Bleach")
    assert r is not None
    assert r.capitulos == 366           # sin cap a 200
    assert r.estado_anime == "Finalizado"
    assert r.fuente == "mal"


def test_mal_scraper_movie():
    from scrapers.mal import MALScraper
    body = json.loads(json.dumps(MAL_RESPONSE))
    body["data"][0]["type"] = "Movie"
    body["data"][0]["episodes"] = 1
    with patch("scrapers.mal._session.get", return_value=_mock_resp(200, body)):
        r = MALScraper().buscar("X")
    assert r.capitulos == "película"


# ── Kitsu ───────────────────────────────────────────────────────────────────

KITSU_RESPONSE = {"data": [{"attributes": {
    "canonicalTitle": "Trigun", "titles": {"en": "Trigun"}, "synopsis": "Vash.",
    "episodeCount": 26, "posterImage": {"large": "https://example/trigun.jpg"},
    "status": "finished", "subtype": "TV",
}}]}


def test_kitsu_scraper_parsea_respuesta_valida():
    from scrapers.kitsu import KitsuScraper
    with patch("scrapers.kitsu._session.get", return_value=_mock_resp(200, KITSU_RESPONSE)):
        r = KitsuScraper().buscar("Trigun")
    assert r is not None
    assert r.nombre == "Trigun"
    assert r.capitulos == 26
    assert r.estado_anime == "Finalizado"


def test_kitsu_scraper_movie_sin_episodios():
    from scrapers.kitsu import KitsuScraper
    body = json.loads(json.dumps(KITSU_RESPONSE))
    body["data"][0]["attributes"]["subtype"] = "movie"
    body["data"][0]["attributes"]["episodeCount"] = None
    with patch("scrapers.kitsu._session.get", return_value=_mock_resp(200, body)):
        r = KitsuScraper().buscar("X")
    assert r.capitulos == "película"


# ── TMDB (pelis/series no-anime) ──────────────────────────────────────────────

TMDB_SEARCH = {"results": [
    {"media_type": "movie", "id": 27205, "title": "Inception", "poster_path": "/p.jpg",
     "overview": "Dreams.", "genre_ids": [28, 878], "release_date": "2010-07-16",
     "vote_average": 8.4},
    {"media_type": "tv", "id": 1399, "name": "Game of Thrones", "poster_path": "/g.jpg",
     "overview": "Throne.", "genre_ids": [18], "first_air_date": "2011-04-17",
     "vote_average": 8.4},
    {"media_type": "person", "id": 1, "name": "Some Actor"},
]}


def test_tmdb_buscar_separa_pelis_y_series_e_ignora_personas():
    from scrapers import tmdb
    with patch("scrapers.tmdb._session.get", return_value=_mock_resp(200, TMDB_SEARCH)):
        res = tmdb.buscar("x", "FAKE_KEY")
    tipos = [m.tipo for m in res]
    assert "pelicula" in tipos and "serie" in tipos
    assert "person" not in tipos and len(res) == 2  # persona ignorada
    inception = next(m for m in res if m.titulo == "Inception")
    assert inception.anio == "2010"
    assert "Acción" in inception.genero


def test_tmdb_buscar_sin_key_devuelve_vacio():
    from scrapers import tmdb
    assert tmdb.buscar("x", "") == []


# ── Registro de scrapers ──────────────────────────────────────────────────────

def test_todos_los_scrapers_estan_registrados():
    from scrapers import SCRAPERS
    esperados = {"anilist", "jikan", "kitsu", "mal", "animeflv",
                 "animeplanet", "animeav1", "crunchyroll"}
    assert esperados <= set(SCRAPERS.keys())


def test_todos_los_scrapers_implementan_buscar():
    from scrapers import SCRAPERS
    from scrapers.base import BaseScraper
    for nombre, s in SCRAPERS.items():
        assert isinstance(s, BaseScraper), f"{nombre} no hereda BaseScraper"
        assert callable(s.buscar)
        assert s.nombre_fuente == nombre
