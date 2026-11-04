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


# ── v2.16.2 ──────────────────────────────────────────────────────────────────

def test_el_manga_y_su_anime_pueden_llamarse_igual(db):
    assert db.guardar_anime({"nombre": "Frieren", "capitulos": "28"})[0]
    manga = {"nombre": "Frieren", "tipo": "manga", "capitulos": "140"}
    assert db.guardar_anime(manga)[0]
    assert manga["nombre"] == "Frieren (Manga)"
    assert db.obtener_anime("Frieren (Manga)")["tipo"] == "manga"
    # Otro manga igual sí es repetido.
    assert db.guardar_anime({"nombre": "Frieren", "tipo": "manga"}) == (False, "duplicado")
    assert db.guardar_anime({"nombre": "FRIEREN"}) == (False, "duplicado")


def test_repetidos_por_nombre_no_mezclan_tipos(db):
    db.guardar_anime({"nombre": "Berserk"})
    db.guardar_anime({"nombre": "Berserk", "tipo": "manga"})
    assert db.buscar_duplicados() == []


def test_stats_globales_y_xp_separan_el_manga():
    import gamificacion
    import stats_util
    animes = [{"nombre": "A", "capitulos": "12", "episodios_vistos": 12, "estado_usuario": "completado"},
              {"nombre": "M", "tipo": "manga", "capitulos": "100", "episodios_vistos": 0,
               "estado_usuario": "completado"}]
    g = stats_util.stats_globales(animes, [])
    assert g["animes"] == 1 and g["mangas"] == 1
    assert g["total_episodios"] == 12 and g["horas_totales"] == round(12 * stats_util.EP_MIN / 60, 1)
    assert g["capitulos_manga"] == 100 and g["total_titulos"] == 2
    st = gamificacion.construir_stats(animes, [], {})
    f = {x["clave"]: x for x in gamificacion.fuentes_xp(st, 0, 0)}
    assert f["capitulo"]["xp"] == 100 and f["episodio"]["cantidad"] == 12
    assert sum(x["xp"] for x in f.values()) == gamificacion.calcular_xp(st, 0, 0)


def test_compartir_pone_el_manga_en_su_pestana():
    import share_page
    html = share_page.render_share_html(
        [{"nombre": "Naruto", "capitulos": "220", "estado_usuario": "viendo"},
         {"nombre": "Naruto (Manga)", "tipo": "manga", "capitulos": "700", "estado_usuario": "viendo"}], [])
    assert 'id="p-manga"' in html and "700 caps" in html and "Leyendo" in html
    sin = share_page.render_share_html([{"nombre": "Naruto", "capitulos": "220"}], [])
    assert 'id="p-manga"' not in sin


def test_aleatorio_y_calendario_sin_manga(db):
    import main
    importlib.reload(main)
    db.guardar_anime({"nombre": "Solo manga", "tipo": "manga", "estado_usuario": "pendiente"})
    c = TestClient(main.app, client=("127.0.0.1", 1))
    assert c.get("/api/animes/random").json().get("anime") is None
    assert c.get("/api/animes/random?tipo=manga").json()["anime"]["nombre"] == "Solo manga"


def test_bajar_el_manga_de_anilist_no_toca_el_anime_del_mismo_nombre(db, monkeypatch):
    import anilist_sync
    db.guardar_anime({"nombre": "Frieren", "capitulos": "28", "episodios_vistos": 5, "estado_usuario": "viendo"})
    db.set_config("anilist_userid", "7")
    monkeypatch.setattr(anilist_sync, "get_token", lambda: "t")

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"MediaListCollection": {"lists": [{"entries": [{
                "status": "CURRENT", "progress": 120, "score": 0,
                "media": {"id": 118586, "title": {"english": "Frieren", "romaji": "Sousou no Frieren"},
                          "chapters": 0, "status": "RELEASING", "genres": [], "coverImage": {}}}]}]}}}

    monkeypatch.setattr(anilist_sync.requests, "post", lambda *a, **k: R())
    r = anilist_sync._pull_type("MANGA")
    assert r["added"] == 1 and r["updated"] == 0
    assert db.obtener_anime("Frieren")["episodios_vistos"] == 5      # el anime, intacto
    m = db.obtener_anime("Frieren (Manga)")
    assert m["tipo"] == "manga" and m["episodios_vistos"] == 120


def test_lo_automatico_de_la_misma_saga_entra_en_tu_caja():
    animes = [{"nombre": "Attack on Titan", "anilist_id": 1, "grupo": "Attack on Titan"},
              {"nombre": "Shingeki no Kyojin OVA", "anilist_id": 2, "grupo": "Attack on Titan"},
              {"nombre": "Shingeki no Kyojin Movie 1", "anilist_id": 3},
              {"nombre": "Shingeki no Kyojin Movie: Final", "anilist_id": 0},
              {"nombre": "Otra cosa", "anilist_id": 9}]
    grupos = {g["nombre"]: [a["nombre"] for a in g["animes"]]
              for g in fq.agrupar_franquicias(animes, {"3": [1]})}
    assert len(grupos["Attack on Titan"]) == 4 and "Otra cosa" not in grupos["Attack on Titan"]
