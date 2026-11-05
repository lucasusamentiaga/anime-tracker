"""v2.16.1: la extensión manda «Mis Listas» de AnimeAV1 y Miraru las mete sin
repetir nada (ni por nombre ni por el mismo anime de AniList con otro nombre)."""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient

from scrapers.base import AnimeData

H = {"X-Miraru-Extension": "1"}


def _devalue(entradas):
    """Lo que devuelve /cuenta/listas/__data.json (formato «devalue»)."""
    data = [{"libraryEntries": 1}, []]
    for e in entradas:
        i = len(data)
        data.append(None)
        media = {"id": len(data), "slug": len(data) + 1, "title": len(data) + 2, "aka": len(data) + 3, "malId": len(data) + 4}
        data += [e["id"], e["slug"], e["titulo"], {"en": len(data) + 5}, e.get("mal") or 0, e.get("en", "")]
        j = len(data)
        data.append(media)
        data[i] = {"media": j, "status": len(data), "episode": len(data) + 1}
        data += [e["status"], e["episode"]]
        data[1].append(i)
    return {"type": "data", "nodes": [None, {"type": "data", "data": data}]}


@pytest.fixture
def cliente(db, monkeypatch):
    import animeav1_sync
    import main
    importlib.reload(main)
    from scrapers import animeav1 as av1

    class FakeAL:
        @staticmethod
        def buscar_por_mal(mal):
            return {50: AnimeData(nombre="Dandadan", capitulos=12, imagen="", genero=[], sinopsis="",
                                  fuente="anilist", estado_anime="Finalizado", anilist_id=171018)}.get(mal)

    monkeypatch.setattr(animeav1_sync, "_anilist_protegido", lambda: FakeAL)
    monkeypatch.setattr(av1, "obtener_media", lambda slug, s=None: {"malId": {"dandadan": 50, "dan-da-dan": 50}.get(slug)})
    monkeypatch.setattr(animeav1_sync, "PAUSA", 0)
    monkeypatch.setattr(main, "_fusionar_repetidos", lambda: {"fusionados": 0})
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c, main


def _esperar(c):
    for _ in range(100):
        d = c.get("/api/animeav1/listas/estado").json()
        if not d["en_curso"] and d["resultado"]:
            return d["resultado"]
        time.sleep(0.05)
    raise AssertionError("no terminó")


def test_sin_cabecera_no(cliente):
    c, _ = cliente
    assert c.post("/api/animeav1/listas", json={"datos": {}}).status_code == 403


def test_sin_sesion_se_dice(cliente):
    c, _ = cliente
    r = c.post("/api/animeav1/listas", headers=H, json={"datos": {"type": "data", "nodes": [None, {"type": "data", "data": [{"libraryEntries": 1}, []]}]}})
    assert r.status_code == 401


def test_mis_listas_sin_repetidos(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": "Frieren: Beyond Journey’s End", "anilist_id": 154587,
                      "estado_usuario": "viendo", "episodios_vistos": 3, "capitulos": "28"})
    datos = _devalue([
        # Ya lo tienes con otro nombre (AnimeAV1 lo llama en japonés): se actualiza.
        {"id": 1, "slug": "sousou-no-frieren", "titulo": "Sousou no Frieren",
         "en": "Frieren: Beyond Journey’s End", "status": 0, "episode": 10},
        # Nuevo: se añade una vez…
        {"id": 2, "slug": "dandadan", "titulo": "Dandadan", "status": 2, "episode": 12},
        # …aunque AnimeAV1 lo tenga dos veces con otro slug.
        {"id": 3, "slug": "dan-da-dan", "titulo": "Dan Da Dan", "status": 2, "episode": 12},
    ])
    r = c.post("/api/animeav1/listas", headers=H, json={"datos": datos})
    assert r.status_code == 200 and r.json()["total"] == 3
    res = _esperar(c)
    nombres = [a["nombre"] for a in db.listar_animes()]
    assert sorted(nombres) == ["Dandadan", "Frieren: Beyond Journey’s End"], nombres
    assert db.obtener_anime("Frieren: Beyond Journey’s End")["episodios_vistos"] == 10
    assert res["added"] == 1 and res["errors"] == 0


def test_mismo_anilist_id_no_entra_dos_veces(db):
    assert db.guardar_anime({"nombre": "Attack on Titan", "anilist_id": 16498})[0]
    assert db.guardar_anime({"nombre": "Shingeki no Kyojin", "anilist_id": 16498}) == (False, "duplicado")


# ── v2.16.3: estado según lo que llevas visto ────────────────────────────────

def test_estado_inteligente():
    from animeav1_sync import estado_inteligente as ei
    assert ei({"estado": "completado", "episodio": 0}, "12", "Finalizado") == ("completado", 12)
    assert ei({"estado": "pendiente", "episodio": 12}, "12", "Finalizado") == ("completado", 12)
    assert ei({"estado": "pendiente", "episodio": 1}, "película", "Finalizado") == ("completado", 1)
    assert ei({"estado": "pendiente", "episodio": 5}, "12", "Finalizado") == ("viendo", 5)
    # en emisión: aunque vayas al día, sigues viéndolo
    assert ei({"estado": "viendo", "episodio": 8}, "8", "En emisión") == ("viendo", 8)
    assert ei({"estado": "pendiente", "episodio": 8}, "12+", "En emisión") == ("viendo", 8)
    assert ei({"estado": "pausa", "episodio": 3}, "12", "Finalizado") == ("pausa", 3)
    assert ei({"estado": "pendiente", "episodio": 0}, "12", "Finalizado") == ("pendiente", 0)


def test_las_listas_nunca_empeoran_lo_que_tienes(db):
    import animeav1_sync as s
    db.guardar_anime({"nombre": "Frieren", "capitulos": "28", "estado_anime": "Finalizado",
                      "estado_usuario": "completado", "episodios_vistos": 28})
    db.guardar_anime({"nombre": "Dandadan", "capitulos": "12", "estado_anime": "Finalizado",
                      "estado_usuario": "pendiente", "episodios_vistos": 0})
    datos = {"libraryEntries": [
        {"media": {"id": 1, "title": "Frieren"}, "status": 1, "episode": 3},
        {"media": {"id": 2, "title": "Dandadan"}, "status": 1, "episode": 12}]}
    s.pull(datos=datos, anilist=object(), sleep=lambda *_: None)
    assert db.obtener_anime("Frieren")["estado_usuario"] == "completado"
    assert db.obtener_anime("Frieren")["episodios_vistos"] == 28
    d = db.obtener_anime("Dandadan")
    assert d["estado_usuario"] == "completado" and d["episodios_vistos"] == 12
