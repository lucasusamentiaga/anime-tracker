"""
v2.14.1 — Filtro de contenido para adultos y búsqueda por sinónimo.

La certificación de la Microsoft Store (23/10/2026) rechazó la 2.14 porque el
contenido que la app puede mostrar no casaba con su clasificación por edades:
las búsquedas devolvían fichas hentai. Estos tests fijan que ninguna fuente
(AniList, Kitsu, Jikan, MAL) ni ningún camino (búsqueda, ids, saga, novedades,
recomendaciones) deja pasar contenido marcado como "solo adultos".

También cubre el bug de "Demon Slayer" → "Onigiri": AniList prioriza un
sinónimo exacto de una serie casi desconocida sobre el título real.

Sin red: todo con HTTP mockeado.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrapers import adulto
from scrapers.base import AnimeData

ROOT = Path(__file__).resolve().parent.parent


def _resp(body):
    r = MagicMock()
    r.status_code = 200
    r.ok = True
    r.raise_for_status = lambda: None
    r.json = lambda: body
    return r


# ── es_adulto ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ficha", [
    {"isAdult": True},                                         # AniList
    {"attributes": {"nsfw": True}},                            # Kitsu
    {"attributes": {"ageRating": "R18"}},                      # Kitsu
    {"rating": "Rx - Hentai"},                                 # Jikan
    {"explicit_genres": [{"name": "Hentai"}]},                 # Jikan
    {"genres": ["Hentai", "Romance"]},                         # cualquier fuente
    {"genero": ["Erotica"]},
    {"genero": "Drama, Hentai"},
    {"adulto": True},                                          # marca interna
])
def test_es_adulto_reconoce_cada_fuente(ficha):
    assert adulto.es_adulto(ficha)


@pytest.mark.parametrize("ficha", [
    None, {}, {"isAdult": False}, {"genres": ["Ecchi", "Fantasy"]},
    {"rating": "R+ - Mild Nudity"}, {"attributes": {"ageRating": "R", "nsfw": False}},
])
def test_ecchi_y_clasificaciones_normales_no_son_adultas(ficha):
    assert not adulto.es_adulto(ficha)


def test_es_adulto_acepta_animedata():
    d = AnimeData(nombre="x", capitulos=1, imagen="", genero=["Hentai"], sinopsis="",
                  fuente="animeflv", estado_anime="")
    assert adulto.es_adulto(d)
    d.genero = ["Action"]
    assert not adulto.es_adulto(d)


def test_filtrar_conserva_el_orden():
    items = [{"id": 1}, {"id": 2, "isAdult": True}, {"id": 3}]
    assert [i["id"] for i in adulto.filtrar(items)] == [1, 3]


# ── Todas las fuentes pasan por el filtro ─────────────────────────────────────

def test_todas_las_fuentes_estan_protegidas():
    from scrapers import SCRAPERS
    for nombre, s in SCRAPERS.items():
        assert hasattr(s.buscar, "__wrapped__"), f"{nombre}.buscar sin filtro de adultos"


def test_proteger_descarta_resultado_adulto():
    from scrapers import _proteger

    class Falso:
        nombre_fuente = "x"

        def buscar(self, nombre):
            d = AnimeData(nombre=nombre, capitulos=1, imagen="", genero=[], sinopsis="",
                          fuente="x", estado_anime="")
            if nombre == "malo":
                d.__dict__["adulto"] = True
            return d

        def buscar_por_ids(self, ids):
            return {i: {"isAdult": i == 2} for i in ids}

    s = _proteger(Falso())
    assert s.buscar("malo") is None
    assert s.buscar("bueno").nombre == "bueno"
    assert list(s.buscar_por_ids([1, 2, 3])) == [1, 3]


# ── AniList ──────────────────────────────────────────────────────────────────

def test_consultas_de_busqueda_de_anilist_piden_solo_no_adultos():
    from scrapers import anilist
    for q in (anilist.QUERY, anilist.QUERY_CANDIDATOS, anilist.QUERY_FRANQUICIA_BUSCAR):
        assert "isAdult: false" in q
    for q in (anilist.QUERY_IDS, anilist.QUERY_MAL, anilist.QUERY_FRANQUICIA_IDS):
        assert "isAdult" in q   # se pide el campo para poder descartarlo


def test_main_pide_novedades_y_recomendaciones_sin_adultos():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "sort: POPULARITY_DESC, isAdult: false" in src      # Novedades
    assert "genre_in:$genres, isAdult:false" in src            # Recomendaciones
    assert "Media(search: $search, type: ANIME, isAdult: false)" in src  # portadas
    assert "mr or adulto.es_adulto(mr)" in src                 # "similares"


def test_anilist_id_adulto_no_entra_pegando_la_url():
    from scrapers import SCRAPERS
    body = {"data": {"Page": {"media": [
        {"id": 7, "isAdult": True, "title": {"romaji": "H", "english": None, "native": ""},
         "episodes": 2, "format": "OVA", "coverImage": {"large": ""}, "genres": ["Hentai"],
         "description": "", "status": "FINISHED"},
        {"id": 8, "isAdult": False, "title": {"romaji": "Ok", "english": "Ok", "native": ""},
         "episodes": 12, "format": "TV", "coverImage": {"large": ""}, "genres": ["Drama"],
         "description": "", "status": "FINISHED"},
    ]}}}
    with patch("scrapers.anilist._session.post", return_value=_resp(body)):
        r = SCRAPERS["anilist"].buscar_por_ids([7, 8])
    assert list(r) == [8]


def test_saga_de_anilist_sin_entradas_adultas():
    from scrapers import anilist

    def m(i, adult=False, rels=()):
        return {"id": i, "isAdult": adult, "title": {"romaji": f"S{i}", "english": None},
                "episodes": 12, "format": "TV", "type": "ANIME", "coverImage": {"large": ""},
                "genres": [], "status": "FINISHED", "startDate": {"year": 2000 + i},
                "relations": {"edges": [{"relationType": "SEQUEL", "node": {"id": r, "type": "ANIME"}}
                                        for r in rels]}}

    def post(query, variables):
        return {"Page": {"media": [m(1, rels=[2]), m(2, adult=True, rels=[3]), m(3)]}}

    saga = anilist.franquicia("S1", post=post)
    assert [e["anilist_id"] for e in saga] == [1, 3]


# ── "Demon Slayer" ya no es "Onigiri" ──────────────────────────────────────────

def _media(i, titulo, pop):
    return {"id": i, "isAdult": False, "popularity": pop,
            "title": {"romaji": titulo, "english": titulo, "native": ""},
            "episodes": 26, "format": "TV", "coverImage": {"large": ""}, "genres": [],
            "description": "", "status": "FINISHED"}


def test_sinonimo_exacto_no_gana_a_la_serie_real():
    from scrapers import SCRAPERS
    onigiri = _media(21612, "Onigiri", 9084)
    kny = _media(101922, "Demon Slayer: Kimetsu no Yaiba", 1009304)
    respuestas = [_resp({"data": {"Media": onigiri}}),
                  _resp({"data": {"Page": {"media": [onigiri, kny]}}})]
    with patch("scrapers.anilist._session.post", side_effect=respuestas) as p:
        r = SCRAPERS["anilist"].buscar("Demon Slayer")
    assert r.nombre == "Demon Slayer: Kimetsu no Yaiba"
    assert p.call_count == 2


def test_si_el_titulo_casa_no_hay_segunda_peticion():
    from scrapers import SCRAPERS
    with patch("scrapers.anilist._session.post",
               return_value=_resp({"data": {"Media": _media(1, "Attack on Titan", 900000)}})) as p:
        r = SCRAPERS["anilist"].buscar("attack on titan")
    assert r.nombre == "Attack on Titan"
    assert p.call_count == 1


def test_sinonimo_de_una_serie_popular_se_respeta():
    """Si el resultado por sinónimo ya es el más popular, se queda."""
    from scrapers import SCRAPERS
    snk = _media(16498, "Shingeki no Kyojin", 900000)
    otro = _media(5, "Attack on Titan Junior High", 50000)
    respuestas = [_resp({"data": {"Media": snk}}),
                  _resp({"data": {"Page": {"media": [snk, otro]}}})]
    with patch("scrapers.anilist._session.post", side_effect=respuestas):
        r = SCRAPERS["anilist"].buscar("Attack on Titan")
    assert r.nombre == "Shingeki no Kyojin"


# ── Kitsu, Jikan y MAL ───────────────────────────────────────────────────────

def _kitsu(i, titulo, **extra):
    return {"id": str(i), "attributes": dict({"canonicalTitle": titulo, "titles": {},
            "synopsis": "", "episodeCount": 12, "posterImage": {}, "status": "finished",
            "subtype": "TV"}, **extra)}


def test_kitsu_salta_resultados_nsfw():
    from scrapers import SCRAPERS
    body = {"data": [_kitsu(1, "Malo", nsfw=True), _kitsu(2, "Peor", ageRating="R18"),
                     _kitsu(3, "Bueno", ageRating="PG")]}
    with patch("scrapers.kitsu._session.get", return_value=_resp(body)):
        r = SCRAPERS["kitsu"].buscar("x")
    assert r.nombre == "Bueno"


def test_kitsu_pide_los_campos_de_edad():
    from scrapers import kitsu
    assert "nsfw,ageRating" in kitsu._CAMPOS


def _jikan(i, titulo, rating="PG-13 - Teens 13 or older", **extra):
    return dict({"mal_id": i, "title": titulo, "rating": rating, "episodes": 12, "type": "TV",
                 "status": "Finished Airing", "images": {}, "genres": []}, **extra)


@pytest.mark.parametrize("fuente,modulo", [("jikan", "scrapers.jikan"), ("mal", "scrapers.mal")])
def test_jikan_y_mal_saltan_rx_y_generos_explicitos(fuente, modulo):
    from scrapers import SCRAPERS
    body = {"data": [_jikan(1, "Malo", rating="Rx - Hentai"),
                     _jikan(2, "Peor", explicit_genres=[{"name": "Erotica"}]),
                     _jikan(3, "Bueno")]}
    with patch(f"{modulo}._session.get", return_value=_resp(body)) as g:
        r = SCRAPERS[fuente].buscar("x")
    assert r.nombre == "Bueno"
    assert g.call_args.kwargs["params"]["sfw"] is True


def test_respaldo_de_kitsu_filtra_novedades_y_recomendaciones():
    import fuentes_respaldo as fr
    payload = {"data": [_kitsu(1, "Malo", nsfw=True), _kitsu(2, "Bueno")], "included": []}
    with patch.object(fr, "_get", return_value=payload):
        assert [n["nombre"] for n in fr.novedades()] == ["Bueno"]
        assert [n["nombre"] for n in fr.recomendaciones(["action"], set())] == ["Bueno"]


def test_saga_por_sinonimo_elige_la_serie_popular():
    from scrapers import anilist

    def m(i, titulo, pop):
        return {"id": i, "isAdult": False, "popularity": pop,
                "title": {"romaji": titulo, "english": titulo}, "episodes": 12, "format": "TV",
                "type": "ANIME", "coverImage": {"large": ""}, "genres": [], "status": "FINISHED",
                "startDate": {"year": 2019}, "relations": {"edges": []}}

    def post(query, variables):
        return {"Page": {"media": [m(1, "Onigiri", 9000), m(2, "Demon Slayer: Kimetsu no Yaiba", 1000000)]}}

    saga = anilist.franquicia("Demon Slayer", post=post)
    assert [e["anilist_id"] for e in saga if e["raiz"]] == [2]


def test_que_veo_traduce_la_razon():
    import i18n_ui
    pats = [p for p, _ in i18n_ui.PATTERNS]
    assert r"^ya llevas (\d+) eps$" in pats and r"^(\d+) eps restantes$" in pats
    m = i18n_ui.ui_para("en")["map"]
    for k in ("Compactar", "Sin vistas guardadas", "Color de acento", "Épico", "Marcar siguiente episodio visto"):
        assert k in m, k
