"""La caché de listar_animes() nunca guarda una lista vieja.

Carrera que había: un hilo empieza a leer la tabla, otro hace +1 (que invalida
la caché) y el primero guarda su lectura ya vieja. El +1 "desaparecía" de la
biblioteca hasta la siguiente mutación.
"""
from __future__ import annotations

import contextlib

import pytest


def _anime(nombre):
    return {"nombre": nombre, "fuente": "anilist", "genero": [], "capitulos": 12}


@pytest.mark.parametrize("funcion", ["listar_animes", "listar_animes_slim", "listar_media"])
def test_lectura_que_cruza_una_escritura_no_se_cachea(db, monkeypatch, funcion):
    db.guardar_anime(_anime("Frieren"))
    invalidar = db._invalidar_media_cache if funcion == "listar_media" else db._invalidar_cache
    real = db.get_conn

    @contextlib.contextmanager
    def conn_con_escritura_en_medio():
        with real() as c:
            yield c
        # Justo después de leer (antes de guardar en caché) otro hilo escribe.
        monkeypatch.setattr(db, "get_conn", real)
        invalidar()

    invalidar()
    monkeypatch.setattr(db, "get_conn", conn_con_escritura_en_medio)
    getattr(db, funcion)()
    lista_cache = {"listar_animes": db._lista_cache, "listar_animes_slim": db._slim_cache,
                   "listar_media": db._media_cache}[funcion]
    assert lista_cache is None, "guardó en caché una lectura anterior a la escritura"


def test_sin_escrituras_la_caché_sí_se_usa(db):
    db.guardar_anime(_anime("Frieren"))
    a = db.listar_animes()
    assert db.listar_animes() is a
    db.guardar_anime(_anime("Dandadan"))
    b = db.listar_animes()
    assert b is not a and {x["nombre"] for x in b} == {"Frieren", "Dandadan"}


def test_mas_uno_se_ve_al_momento(db):
    db.guardar_anime(_anime("Frieren"))
    db.listar_animes(), db.listar_animes_slim()
    db.actualizar_anime("Frieren", {"episodios_vistos": 5})
    assert db.obtener_anime("Frieren")["episodios_vistos"] == 5
    assert next(x for x in db.listar_animes() if x["nombre"] == "Frieren")["episodios_vistos"] == 5
    assert next(x for x in db.listar_animes_slim() if x["nombre"] == "Frieren")["episodios_vistos"] == 5



def test_franquicias_se_actualizan_aunque_python_reutilice_el_id(db, monkeypatch):
    """/api/franquicias usaba id(lista) como versión. Si la lista nueva ocupaba
    la memoria de la vieja (mismo id), devolvía las cajas de antes."""
    import importlib

    from fastapi.testclient import TestClient

    import main
    importlib.reload(main)
    db.guardar_anime(_anime("Frieren"))
    misma = list(db.listar_animes_slim())
    monkeypatch.setattr(db, "listar_animes_slim", lambda: misma)   # siempre el mismo id
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        assert "Dandadan" not in c.get("/api/franquicias").text
        db.guardar_anime(_anime("Dandadan"))          # invalida la caché
        misma.insert(0, dict(misma[0], nombre="Dandadan", id=999))
        assert "Dandadan" in c.get("/api/franquicias").text
