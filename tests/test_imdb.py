"""Nota de IMDb (imdb.py): búsqueda local y propagación por saga."""
from __future__ import annotations

import imdb

DATOS = {"al": {"1": "tt1", "3": "tt3", "9": "tt9"}, "mal": {"500": "tt2"},
         "notas": {"tt1": [8.0, 1000], "tt2": [9.1, 500000], "tt3": [8.6, 10000], "tt9": [7.2, 900]}}


def test_nota_por_anilist_y_por_mal():
    assert imdb.nota(DATOS, 1) == (8.0, 1000, "tt1")
    assert imdb.nota(DATOS, 2, 500) == (9.1, 500000, "tt2")
    assert imdb.nota(DATOS, 77) is None


def test_saga_toma_la_ficha_con_mas_votos_y_no_toca_peliculas():
    animes = [{"nombre": "Serie", "anilist_id": 2, "capitulos": "25"},
              {"nombre": "OVA", "anilist_id": 3, "capitulos": "3"},
              {"nombre": "T2", "anilist_id": 5, "capitulos": "12"},
              {"nombre": "Peli", "anilist_id": 6, "capitulos": "película"},
              {"nombre": "Peli con ficha", "anilist_id": 9, "capitulos": "película"}]
    fq = [{"animes": [{"nombre": "OVA", "capitulos": "3"}, {"nombre": "Serie", "capitulos": "25"},
                      {"nombre": "T2", "capitulos": "12"}, {"nombre": "Peli", "capitulos": "película"},
                      {"nombre": "Peli con ficha", "capitulos": "película"}]}]
    out = imdb.notas_biblioteca(DATOS, animes, fq, {"2": 500})
    assert out["T2"] == 9.1            # la de la serie, no la de la OVA
    assert out["OVA"] == 8.6           # la suya propia se respeta
    assert "Peli" not in out           # las películas no heredan
    assert out["Peli con ficha"] == 7.2


def test_cargar_sin_archivo(tmp_path):
    imdb._mem.update(datos=None, ruta=None)
    d = imdb.cargar(tmp_path)
    assert d["al"] == {} and d["notas"] == {}


def test_archivo_de_formato_viejo_se_rehace(tmp_path):
    import json
    import time
    (tmp_path / "imdb_notas.json").write_text(json.dumps({"al": {}, "mal": {}, "notas": {}, "ts": time.time()}))
    imdb._mem.update(datos=None, ruta=None)
    assert imdb.caducado(tmp_path)


def test_manga_sin_nota_de_imdb():
    animes = [{"nombre": "M", "anilist_id": 1, "tipo": "manga", "capitulos": "100"}]
    assert imdb.notas_biblioteca(DATOS, animes) == {}
