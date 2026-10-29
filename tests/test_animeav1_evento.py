"""AnimeAV1 → Miraru al instante (extensión del navegador).

La extensión ve el POST /api/user/library {"mediaId", "episode"} que hace
animeav1.com al pulsar «Marcar como visto» y lo manda a /api/animeav1/evento.
Sin red: la ficha de AnimeAV1 y AniList se simulan.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scrapers.base import AnimeData

ROOT = Path(__file__).resolve().parent.parent
H = {"X-Miraru-Extension": "1"}


@pytest.fixture
def cliente(db):
    import main
    importlib.reload(main)
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c, main


def _eps_log(db, n):
    with db.get_conn() as c:
        return [r[0] for r in c.execute("SELECT episodio FROM ep_log WHERE nombre=? ORDER BY episodio", (n,))]


def test_sin_la_cabecera_de_la_extension_no_se_acepta(cliente):
    c, _ = cliente
    assert c.post("/api/animeav1/evento", json={"mediaId": 1, "episode": 1}).status_code == 403


def test_marcar_visto_actualiza_por_titulo_y_recuerda_el_id(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": "Sousou no Frieren", "capitulos": "28", "episodios_vistos": 4})
    r = c.post("/api/animeav1/evento", headers=H, json={
        "mediaId": 77, "episode": 5, "slug": "sousou-no-frieren",
        "titulo": "Sousou no Frieren Episodio 5 Sub Español Online en HD - AnimeAV1"})
    assert r.status_code == 200, r.text
    assert r.json()["accion"] == "actualizado"
    a = db.obtener_anime("Sousou no Frieren")
    assert a["episodios_vistos"] == 5 and a["estado_usuario"] == "viendo"
    assert _eps_log(db, "Sousou no Frieren") == [5]           # cuenta en el mapa de actividad
    import animeav1_sync
    assert animeav1_sync._ids()["Sousou no Frieren"] == 77
    # Siguiente evento: ya va por el id, aunque no venga título
    c.post("/api/animeav1/evento", headers=H, json={"mediaId": 77, "episode": 6})
    assert db.obtener_anime("Sousou no Frieren")["episodios_vistos"] == 6


def test_desmarcar_baja_el_episodio(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": "Dandadan", "capitulos": "12", "episodios_vistos": 3})
    import animeav1_sync
    animeav1_sync.recordar_id("Dandadan", 9)
    c.post("/api/animeav1/evento", headers=H, json={"mediaId": 9, "episode": 4})
    c.post("/api/animeav1/evento", headers=H, json={"mediaId": 9, "episode": 3})   # «no visto»
    assert db.obtener_anime("Dandadan")["episodios_vistos"] == 3
    assert _eps_log(db, "Dandadan") == []


def test_un_episodio_atrasado_no_baja_el_progreso(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": "Dandadan", "capitulos": "12", "episodios_vistos": 10,
                      "estado_usuario": "viendo"})
    import animeav1_sync
    animeav1_sync.recordar_id("Dandadan", 9)
    r = c.post("/api/animeav1/evento", headers=H, json={"mediaId": 9, "episode": 2})
    assert r.json()["accion"] == "sin cambios"
    assert db.obtener_anime("Dandadan")["episodios_vistos"] == 10


def test_ultimo_episodio_lo_completa(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": "Dandadan", "capitulos": "12", "episodios_vistos": 11,
                      "estado_usuario": "viendo"})
    import animeav1_sync
    animeav1_sync.recordar_id("Dandadan", 9)
    c.post("/api/animeav1/evento", headers=H, json={"mediaId": 9, "episode": 12})
    assert db.obtener_anime("Dandadan")["estado_usuario"] == "completado"
    c.post("/api/animeav1/evento", headers=H, json={"mediaId": 9, "episode": 11})   # desmarcar
    a = db.obtener_anime("Dandadan")
    assert a["episodios_vistos"] == 11 and a["estado_usuario"] == "viendo"


def test_anime_nuevo_se_anade(cliente, db, monkeypatch):
    c, main = cliente
    from scrapers import animeav1 as av1
    monkeypatch.setattr(av1, "obtener_media", lambda slug, s=None: {
        "id": 5, "title": "Kusuriya no Hitorigoto", "malId": 54492, "aka": {}})

    class AL:
        def buscar_por_mal(self, mal):
            return AnimeData(nombre="The Apothecary Diaries", capitulos=24, imagen="", genero=[],
                             sinopsis="", fuente="anilist", estado_anime="", anilist_id=161645)
    import scrapers.anilist
    monkeypatch.setattr(scrapers.anilist, "AniListScraper", AL)
    r = c.post("/api/animeav1/evento", headers=H, json={"mediaId": 5, "episode": 1, "slug": "kusuriya"})
    assert r.json()["accion"] == "añadido"
    a = db.obtener_anime("The Apothecary Diaries")
    assert a["episodios_vistos"] == 1 and a["estado_usuario"] == "viendo" and a["anilist_id"] == 161645
    assert c.get("/api/animeav1/extension").json()["ultimo"]["nombre"] == "The Apothecary Diaries"


def test_la_lista_avisa_de_cambios(cliente, db):
    c, _ = cliente
    v1 = c.get("/api/biblioteca/version").json()["v"]
    db.guardar_anime({"nombre": "Dandadan"})
    assert c.get("/api/biblioteca/version").json()["v"] != v1


def test_titulo_de_pestana():
    import animeav1_sync as s
    assert s.titulo_de_pestana("Sousou no Frieren Episodio 1 Sub Español Online en HD - AnimeAV1") == "Sousou no Frieren"
    assert s.titulo_de_pestana("One Piece - AnimeAV1") == "One Piece"


def test_extension_descargable_y_coherente(cliente):
    c, _ = cliente
    r = c.get("/api/animeav1/extension.zip")
    assert r.status_code == 200
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nombres = set(z.namelist())
    assert {"miraru-animeav1/manifest.json", "miraru-animeav1/background.js",
            "miraru-animeav1/popup.html", "miraru-animeav1/iconos/128.png"} <= nombres
    m = json.loads(z.read("miraru-animeav1/manifest.json"))
    assert m["manifest_version"] == 3 and "webRequest" in m["permissions"]
    bg = z.read("miraru-animeav1/background.js").decode()
    # La extensión manda la cabecera que exige el servidor y a la ruta correcta.
    assert "X-Miraru-Extension" in bg and "/api/animeav1/evento" in bg
    assert "https://animeav1.com/api/user/library" in bg
