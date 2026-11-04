"""v2.16.1: anime y manga, cada uno en su sitio."""
import importlib

from fastapi.testclient import TestClient

import franquicias as fq


def test_anime_y_manga_de_la_misma_obra_no_comparten_caja():
    animes = [{"nombre": "Attack on Titan", "tipo": "anime"},
              {"nombre": "Attack on Titan Season 2", "tipo": "anime"},
              {"nombre": "Attack on Titan", "tipo": "manga"}]
    grupos = fq.agrupar_franquicias(animes)
    por_tipo = sorted(sorted(a["tipo"] for a in g["animes"]) for g in grupos)
    assert por_tipo == [["anime", "anime"], ["manga"]]


def test_estadisticas_de_anime_sin_capitulos_de_manga(db):
    import main
    importlib.reload(main)
    db.guardar_anime({"nombre": "Frieren", "capitulos": "28", "episodios_vistos": 10, "estado_usuario": "viendo"})
    db.guardar_anime({"nombre": "One Piece", "tipo": "manga", "capitulos": "1100", "episodios_vistos": 900,
                      "estado_usuario": "viendo"})
    d = TestClient(main.app, client=("127.0.0.1", 1)).get("/api/stats").json()
    assert d["total"] == 1 and d["total_episodes"] == 10
    assert d["mangas"] == 1 and d["capitulos_manga"] == 900


def test_avisos_de_lo_que_ves_en_emision_sin_campanita(db, monkeypatch):
    import main
    importlib.reload(main)
    db.guardar_anime({"nombre": "Beerus", "estado_usuario": "viendo", "estado_anime": "En emisión",
                      "episodios_vistos": 2, "anilist_id": 1})
    db.guardar_anime({"nombre": "Acabado", "estado_usuario": "viendo", "estado_anime": "Finalizado",
                      "episodios_vistos": 2, "anilist_id": 2})
    assert [a["nombre"] for a in db.listar_con_notif()] == ["Beerus"]
    monkeypatch.setattr(main, "_fetch_ultimos_episodios",
                        lambda animes: {"Beerus": {"total": 0, "next_ep": 5, "next_at": 9e12}})
    d = TestClient(main.app, client=("127.0.0.1", 1)).get("/api/notif/check").json()
    assert d["pendientes"][0]["siguiente"] == 3 and d["pendientes"][0]["ultimo_emitido"] == 4
