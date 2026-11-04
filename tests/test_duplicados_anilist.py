"""v2.16.1: el mismo anime con nombres de fuentes distintas se junta, pero
solo si AniList lo confirma (un anilist_id mal resuelto no borra nada)."""
import duplicados

INFO = {
    16498: {"id": 16498, "format": "TV", "episodes": 25, "synonyms": ["AoT"],
            "title": {"romaji": "Shingeki no Kyojin", "english": "Attack on Titan", "native": "進撃の巨人"}},
    131681: {"id": 131681, "format": "TV", "episodes": 12, "synonyms": [],
             "title": {"romaji": "Shingeki no Kyojin: The Final Season Part 2",
                       "english": "Attack on Titan Final Season Part 2", "native": ""}},
    19647: {"id": 19647, "format": "TV", "episodes": 25, "synonyms": ["Hajime no Ippo 3"],
            "title": {"romaji": "Hajime no Ippo: Rising", "english": "Hajime No Ippo: The Fighting! - Rising -"}},
    97962: {"id": 97962, "format": "SPECIAL", "episodes": 3, "synonyms": ["Kimi no Na wa."],
            "title": {"romaji": "Suntory Minami Alps no Tennen Mizu"}},
    265: {"id": 265, "format": "OVA", "episodes": 1, "synonyms": [],
          "title": {"romaji": "Hajime no Ippo: Mashiba vs Kimura - Shikei Shikkou"}},
}


def A(nombre, aid, fuente="animeflv", caps="12", **kw):
    return {"nombre": nombre, "anilist_id": aid, "fuente": fuente, "capitulos": caps, "tipo": "anime", **kw}


def test_junta_los_confirmados_y_se_queda_el_de_anilist():
    plan = duplicados.planificar([
        A("Shingeki no Kyojin", 16498, caps="25"),
        A("Attack on Titan", 16498, fuente="anilist", caps="25"),
        A("Attack on Titan: The Final Season Part 2", 131681, fuente="kitsu"),
        A("Shingeki no Kyojin: The Final Season Part 2", 131681),
        A("Attack on Titan Final Season Part 2", 131681, fuente="anilist"),
    ], INFO)
    d = dict(plan)
    assert d["Attack on Titan"] == ["Shingeki no Kyojin"]
    assert sorted(d["Attack on Titan Final Season Part 2"]) == [
        "Attack on Titan: The Final Season Part 2", "Shingeki no Kyojin: The Final Season Part 2"]


def test_no_junta_lo_dudoso():
    plan = duplicados.planificar([
        # «Hajime no Ippo» (75) con el id de «Rising» (25): id mal resuelto.
        A("Hajime no Ippo", 19647, fuente="kitsu", caps="75"),
        A("Hajime No Ippo: The Fighting! - Rising -", 19647, fuente="kitsu", caps="25"),
        # La película con el id de un anuncio que la tiene de sinónimo.
        A("Kimi no Na wa.", 97962, fuente="kitsu", caps="película"),
        A("Suntory Minami Alps no Tennen Mizu", 97962, fuente="anilist", caps="3"),
    ], INFO)
    assert plan == []


def test_principio_del_titulo_con_episodios_exactos():
    plan = duplicados.planificar([
        A("Hajime no Ippo: Mashiba vs. Kimura", 265, fuente="kitsu", caps="1"),
        A("Hajime no Ippo: The Fighting! - Mashiba vs Kimura", 265, fuente="anilist", caps="1"),
    ], INFO)
    assert plan == [("Hajime no Ippo: The Fighting! - Mashiba vs Kimura", ["Hajime no Ippo: Mashiba vs. Kimura"])]


def test_clave_ignora_relleno_y_ordinales():
    assert duplicados.clave("Yofukashi no Uta 2nd Season") == duplicados.clave("Yofukashi no Uta Season 2")
    assert duplicados.clave("Black Clover (TV)") == duplicados.clave("Black Clover")
    assert duplicados.clave("Boku no Hero Academia 2nd Season") != duplicados.clave("My Hero Academia: Vigilantes Season 2")


def test_fusion_real_en_la_bd(db, monkeypatch):
    db.guardar_anime(A("Attack on Titan", 16498, fuente="anilist", caps="25", episodios_vistos=25,
                       estado_usuario="completado"))
    with db.get_conn() as c:      # entró antes de la protección por id
        c.execute("INSERT INTO animes(nombre,fuente,capitulos,anilist_id,tipo,episodios_vistos,estado_usuario,puntuacion)"
                  " VALUES ('Shingeki no Kyojin','animeflv','25',16498,'anime',25,'completado',9)")
    db._invalidar_cache()
    r = duplicados.fusionar_repetidos(lambda q, v: {"Page": {"media": [INFO[16498]]}})
    assert r["fusionados"] == 1
    a = db.obtener_anime("Attack on Titan")
    assert a and a["puntuacion"] == 9 and db.obtener_anime("Shingeki no Kyojin") is None


# ── v2.16.3 ──────────────────────────────────────────────────────────────────

def _media(i, fmt, eps, romaji, english=None, syn=()):
    return {"id": i, "format": fmt, "episodes": eps,
            "title": {"romaji": romaji, "english": english, "native": None}, "synonyms": list(syn)}


def test_sin_id_se_junta_con_su_titulo_de_anilist():
    animes = [{"nombre": "Chitose Is in the Ramune Bottle", "anilist_id": 5, "capitulos": "13", "fuente": "anilist"},
              {"nombre": "Chitose-kun wa Ramune Bin no Naka", "anilist_id": 0, "capitulos": "13", "fuente": "animeflv"}]
    info = {5: _media(5, "TV", 13, "Chitose-kun wa Ramune Bin no Naka", "Chitose Is in the Ramune Bottle")}
    assert duplicados.planificar_sin_id(animes, info) == [
        ("Chitose Is in the Ramune Bottle", ["Chitose-kun wa Ramune Bin no Naka"])]


def test_sin_id_la_serie_no_acaba_dentro_de_su_pelicula():
    # En AniList «Gotoubun no Hanayome» es sinónimo de la PELÍCULA.
    animes = [{"nombre": "5-toubun no Hanayome Movie", "anilist_id": 9, "capitulos": "película"},
              {"nombre": "Gotoubun no Hanayome", "anilist_id": 0, "capitulos": "?"}]
    info = {9: _media(9, "MOVIE", 1, "Gotoubun no Hanayome Movie", syn=["Gotoubun no Hanayome"])}
    assert duplicados.planificar_sin_id(animes, info) == []
    animes[1]["capitulos"] = "12"
    assert duplicados.planificar_sin_id(animes, info) == []


def test_sin_id_ambiguo_no_se_toca():
    animes = [{"nombre": "A", "anilist_id": 1, "capitulos": "12"}, {"nombre": "B", "anilist_id": 2, "capitulos": "12"},
              {"nombre": "Baki", "anilist_id": 0, "capitulos": "12"}]
    info = {1: _media(1, "TV", 12, "Baki"), 2: _media(2, "TV", 12, "X", syn=["Baki"])}
    assert duplicados.planificar_sin_id(animes, info) == []


def test_por_kitsu_junta_o_apunta_el_id(monkeypatch):
    apuntados = {}
    monkeypatch.setattr(duplicados.db, "actualizar_anime", lambda n, c: apuntados.update({n: c}) or (True, ""))
    animes = [{"nombre": "AoT Special 1", "anilist_id": 146984, "capitulos": "1", "fuente": "anilist"},
              {"nombre": "Attack on Titan: The Final Season - Final Chapters Part 1", "anilist_id": 0, "capitulos": "1",
               "fuente": "kitsu"},
              {"nombre": "Isekai Ojisan", "anilist_id": 0, "capitulos": "?", "fuente": "animeflv"}]
    info = {146984: _media(146984, "SPECIAL", 1, "Shingeki no Kyojin: Kanketsu-hen Zenpen")}
    ids = {"Attack on Titan: The Final Season - Final Chapters Part 1": 146984, "Isekai Ojisan": 141019}
    plan = duplicados._por_kitsu(animes, info, lambda n: ids.get(n, 0))
    assert plan == [("AoT Special 1", ["Attack on Titan: The Final Season - Final Chapters Part 1"])]
    assert apuntados == {"Isekai Ojisan": {"anilist_id": 141019}}
