"""«Todas las fuentes» no espera a una web caída, y otros 500 que no lo eran."""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient

from scrapers.base import AnimeData


@pytest.fixture
def cliente(db):
    import main
    importlib.reload(main)
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c, main


class _Rapida:
    def buscar(self, nombre):
        return AnimeData(nombre=nombre, capitulos=12, imagen="", genero=[], sinopsis="",
                         fuente="rapida", estado_anime="")


class _Colgada:
    def buscar(self, nombre):
        time.sleep(3)
        return None


def test_busqueda_multi_corta_las_fuentes_lentas(cliente, monkeypatch):
    c, main = cliente
    monkeypatch.setattr(main, "SCRAPERS", {"rapida": _Rapida(), "colgada": _Colgada()})
    monkeypatch.setattr(main, "_TIMEOUT_BUSQUEDA_MULTI", 0.5)
    t = time.time()
    r = c.post("/api/buscar/multi", json={"nombre": "Plazo test"}).json()
    assert time.time() - t < 2.5
    assert [x["fuente"] for x in r["resultados"]] == ["rapida"]


def test_reintentos_de_red_cortos():
    from scrapers import net
    r = net.build_retry()
    assert r.connect == 1 and r.read == 1 and r.status == 3


@pytest.mark.parametrize("cuerpo", ["[]", '"x"', "{no json"])
def test_anilist_connect_cuerpo_malo_da_400(cliente, cuerpo):
    c, _ = cliente
    r = c.post("/api/anilist/connect", content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_email_de_prueba_sin_configurar_da_400(cliente):
    c, _ = cliente
    assert c.post("/api/notif/test-email").status_code == 400


def test_endpoints_con_red_no_bloquean_el_servidor():
    """Las que hacen peticiones de red sin await no pueden ser `async def`:
    congelarían todo el servidor mientras esperan."""
    import inspect

    import main
    for f in (main.verify_setup, main.sync_sheets, main.test_email):
        assert not inspect.iscoroutinefunction(f), f.__name__
