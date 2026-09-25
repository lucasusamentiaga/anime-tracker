"""
_fetch_ultimos_episodios: lookup por anilist_id con Page(id_in).

Regresión: la versión anterior mandaba un alias Media(search:) por nombre y
AniList devolvía 404 a toda la query si un solo título no casaba → ninguna
notificación funcionaba.
"""
from __future__ import annotations

import pytest

from scrapers.base import AnimeData


@pytest.fixture
def main_mod(db, monkeypatch):
    import main
    return main


def _media(i, eps=None, nxt=None, at=0):
    return {"id": i, "episodes": eps,
            "nextAiringEpisode": {"episode": nxt, "airingAt": at} if nxt else None}


def test_usa_id_in_y_mapea_por_nombre(main_mod, monkeypatch):
    llamadas = []

    def fake_anilist(q, v, timeout=15):
        llamadas.append(v)
        return {"Page": {"media": [_media(1, 12), _media(2, None, 8, 999)]}}
    monkeypatch.setattr(main_mod, "_anilist", fake_anilist)
    out = main_mod._fetch_ultimos_episodios(
        [{"nombre": "A", "anilist_id": 1}, {"nombre": "B", "anilist_id": 2},
         {"nombre": "C", "anilist_id": 3}], sleep=lambda s: None)
    assert llamadas == [{"ids": [1, 2, 3]}]
    assert out["A"]["total"] == 12
    assert out["B"] == {"total": 0, "next_ep": 8, "next_at": 999}
    assert "C" not in out            # ID inexistente no rompe el resto


def test_resuelve_y_guarda_id_si_falta(main_mod, monkeypatch):
    class _AL:
        def buscar(self, nombre, media_type="ANIME"):
            return AnimeData(nombre=nombre, capitulos=24, imagen="", genero=[], sinopsis="",
                             fuente="anilist", estado_anime="", anilist_id=42)
    guardados = []
    monkeypatch.setitem(main_mod.SCRAPERS, "anilist", _AL())
    monkeypatch.setattr(main_mod.db, "refrescar_metadata_anime",
                        lambda n, c: (guardados.append((n, c)), (True, "ok"))[1])
    monkeypatch.setattr(main_mod, "_anilist",
                        lambda q, v, timeout=15: {"Page": {"media": [_media(42, 24)]}})
    out = main_mod._fetch_ultimos_episodios(["Black Clover (TV)"], sleep=lambda s: None)
    assert out["Black Clover (TV)"]["total"] == 24
    assert guardados == [("Black Clover (TV)", {"anilist_id": 42})]


def test_limita_resoluciones_por_llamada(main_mod, monkeypatch):
    buscados = []

    class _AL:
        def buscar(self, nombre, media_type="ANIME"):
            buscados.append(nombre)
            return None
    monkeypatch.setitem(main_mod.SCRAPERS, "anilist", _AL())
    monkeypatch.setattr(main_mod, "_anilist", lambda q, v, timeout=15: {})
    main_mod._fetch_ultimos_episodios([f"X{i}" for i in range(10)],
                                      max_resolver=3, sleep=lambda s: None)
    assert len(buscados) == 3


def test_lista_vacia(main_mod):
    assert main_mod._fetch_ultimos_episodios([]) == {}
