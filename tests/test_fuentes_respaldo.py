"""Tests del respaldo de fuentes (Kitsu) — sin tocar la red.

Cubre las funciones puras y el parseo de un payload JSON:API real recortado.
El respaldo existe porque AniList devolvió 403 durante días y la app se quedaba
en blanco culpando a la conexión del usuario.
"""
from unittest.mock import patch

import fuentes_respaldo as fr

# ── Deducción de plataforma a partir de la URL ────────────────────────────────

def test_plataforma_reconoce_los_servicios_principales():
    assert fr.plataforma_desde_url("https://www.crunchyroll.com/one-piece") == "Crunchyroll"
    assert fr.plataforma_desde_url("https://www.netflix.com/title/80107103") == "Netflix"
    assert fr.plataforma_desde_url("https://www.primevideo.com/detail/x") == "Amazon Prime Video"
    assert fr.plataforma_desde_url("https://www.disneyplus.com/series/y") == "Disney Plus"


def test_plataforma_es_insensible_a_mayusculas():
    assert fr.plataforma_desde_url("HTTPS://WWW.NETFLIX.COM/AA") == "Netflix"


def test_plataforma_desconocida_o_vacia_no_revienta():
    assert fr.plataforma_desde_url("https://ejemplo.org/anime") == ""
    assert fr.plataforma_desde_url("") == ""
    assert fr.plataforma_desde_url(None) == ""


# ── Traducción de géneros AniList -> categorías Kitsu ─────────────────────────

def test_genero_traduce_los_casos_que_no_coinciden():
    assert fr.genero_a_categoria("Sci-Fi") == "science-fiction"
    assert fr.genero_a_categoria("Slice of Life") == "slice-of-life"


def test_genero_normaliza_el_resto():
    assert fr.genero_a_categoria("Action") == "action"
    assert fr.genero_a_categoria("  Fantasy ") == "fantasy"
    assert fr.genero_a_categoria("") == ""


# ── Puntuación: Kitsu da 0-100 en texto, la app usa 0-10 ──────────────────────

def test_puntuacion_convierte_la_escala():
    assert fr._puntuacion({"averageRating": "84.45"}) == 8.4


def test_puntuacion_tolera_valores_ausentes_o_basura():
    assert fr._puntuacion({}) == 0.0
    assert fr._puntuacion({"averageRating": None}) == 0.0
    assert fr._puntuacion({"averageRating": "no-es-un-numero"}) == 0.0


# ── Parseo del payload (forma real de Kitsu, recortada) ──────────────────────

PAYLOAD = {
    "data": [
        {
            "id": "1",
            "attributes": {
                "canonicalTitle": "One Piece",
                "posterImage": {"large": "https://img/op.jpg"},
                "episodeCount": 1100,
                "averageRating": "85.0",
                "synopsis": "<b>Piratas</b> buscando un tesoro",
                "status": "current",
                "slug": "one-piece",
                "userCount": 50000,
            },
            "relationships": {
                "streamingLinks": {"data": [{"id": "s1"}, {"id": "s2"}]},
                "categories": {"data": [{"id": "c1"}]},
            },
        },
        {
            "id": "2",
            "attributes": {
                "canonicalTitle": "Solo en Netflix",
                "posterImage": {"medium": "https://img/n.jpg"},
                "episodeCount": None,
                "averageRating": "70.0",
                "synopsis": "",
                "status": "current",
                "slug": "solo-netflix",
                "userCount": 10,
            },
            "relationships": {
                "streamingLinks": {"data": [{"id": "s3"}]},
                "categories": {"data": []},
            },
        },
    ],
    "included": [
        {"id": "s1", "type": "streamingLinks",
         "attributes": {"url": "https://www.crunchyroll.com/one-piece"}},
        {"id": "s2", "type": "streamingLinks",
         "attributes": {"url": "https://www.hulu.com/one-piece"}},
        {"id": "s3", "type": "streamingLinks",
         "attributes": {"url": "https://www.netflix.com/title/1"}},
        {"id": "c1", "type": "categories", "attributes": {"title": "Adventure"}},
    ],
}


def test_novedades_mapea_a_la_forma_que_espera_el_frontend():
    with patch.object(fr, "_get", return_value=PAYLOAD):
        items = fr.novedades("all")

    assert len(items) == 2
    op = next(i for i in items if i["nombre"] == "One Piece")
    # Mismas claves que produce _fetch_novedades con AniList
    assert set(op) == {"nombre", "imagen", "generos", "estado", "capitulos",
                       "puntuacion", "plataformas", "sinopsis", "proximo_ep"}
    assert op["imagen"] == "https://img/op.jpg"
    assert op["capitulos"] == 1100
    assert op["puntuacion"] == 8.5
    assert op["plataformas"] == ["Crunchyroll", "Hulu"]
    assert op["generos"] == ["Adventure"]
    assert "<b>" not in op["sinopsis"]          # el HTML se limpia
    assert op["proximo_ep"] is None


def test_novedades_filtra_por_plataforma():
    with patch.object(fr, "_get", return_value=PAYLOAD):
        assert [i["nombre"] for i in fr.novedades("netflix")] == ["Solo en Netflix"]
        assert [i["nombre"] for i in fr.novedades("crunchyroll")] == ["One Piece"]


def test_novedades_sin_episodios_conocidos_usa_interrogante():
    with patch.object(fr, "_get", return_value=PAYLOAD):
        n = next(i for i in fr.novedades("netflix"))
    assert n["capitulos"] == "?"


def test_recomendaciones_excluye_lo_que_ya_tiene_el_usuario():
    with patch.object(fr, "_get", return_value=PAYLOAD):
        recos = fr.recomendaciones(["Action"], existentes={"one piece"})
    assert [r["nombre"] for r in recos] == ["Solo en Netflix"]


def test_recomendaciones_devuelve_la_forma_esperada():
    with patch.object(fr, "_get", return_value=PAYLOAD):
        recos = fr.recomendaciones(["Action"], existentes=set())
    assert set(recos[0]) == {"nombre", "imagen", "genero", "sinopsis", "episodios",
                             "puntuacion_global", "estado_anime", "link", "trending"}
    assert recos[0]["nombre"] == "One Piece"     # ordenado por userCount
    assert recos[0]["estado_anime"] == "En emisión"


def test_ficha_por_titulo_devuelve_las_claves_de_anilist_por_ids():
    with patch.object(fr, "_get", return_value=PAYLOAD):
        ficha = fr.ficha_por_titulo("One Piece")
    assert set(ficha) == {"imagen", "sinopsis", "episodios", "puntuacion_global",
                          "link", "estado_anime"}
    assert ficha["imagen"] == "https://img/op.jpg"


def test_ficha_por_titulo_sin_resultados_devuelve_vacio():
    with patch.object(fr, "_get", return_value={"data": []}):
        assert fr.ficha_por_titulo("no existe este anime") == {}
