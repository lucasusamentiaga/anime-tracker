"""AnimeAV1: lectura de su formato de datos y sincronización de listas (v2.12).

Sin red: una sesión falsa responde como la web real (formato «devalue» de
SvelteKit, visto en /media/<slug>/__data.json y /cuenta/listas/__data.json).
"""
from __future__ import annotations

import json

import pytest

from scrapers import animeav1 as av1


def _devalue(valor):
    """Serializa al formato devalue (array plano con índices) para los tests."""
    vals: list = []

    def enc(v):
        i = len(vals)
        vals.append(None)
        if isinstance(v, dict):
            vals[i] = {k: enc(x) for k, x in v.items()}
        elif isinstance(v, list):
            vals[i] = [enc(x) for x in v]
        else:
            vals[i] = v
        return i

    enc(valor)
    return vals


def _pagina(*datos, error=None):
    nodos = [None, {"type": "data", "data": _devalue({"user": None})}]
    for d in datos:
        nodos.append({"type": "data", "data": _devalue(d)})
    if error:
        nodos.append({"type": "error", "error": {"message": error[1]}, "status": error[0]})
    return {"type": "data", "nodes": nodos}


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d


class SesionFalsa:
    def __init__(self, entradas=None, medias=None, busquedas=None, valida=True):
        self.entradas = entradas or []
        self.medias = medias or {}
        self.busquedas = busquedas or {}
        self.valida = valida
        self.posts: list[dict] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None):
        ruta = url.replace(av1.BASE, "").replace("/__data.json", "")
        if ruta == "/cuenta/listas":
            if not self.valida:
                return Resp(_pagina(error=(401, "No autorizado")))
            return Resp({"type": "data", "nodes": [None,
                {"type": "data", "data": _devalue({"user": {"username": "lucas"}})},
                {"type": "data", "data": _devalue({"libraryEntries": self.entradas})}]})
        if ruta == "/catalogo":
            return Resp(_pagina({"results": self.busquedas.get(params["search"], [])}))
        if ruta.startswith("/media/"):
            m = self.medias.get(ruta[len("/media/"):])
            return Resp(_pagina({"media": m}) if m else _pagina(error=(404, "No existe")))
        return Resp({}, 404)

    def post(self, url, json=None, timeout=None, headers=None):
        self.posts.append(json)
        return Resp({"ok": True})


def test_hidratar_reconstruye_objetos_y_tipos_especiales():
    vals = [{"a": 1, "b": 2, "c": 4}, "hola", [3], 5, ["Date", "2024-01-02T00:00:00Z"]]
    assert av1.hidratar(vals) == {"a": "hola", "b": [5], "c": "2024-01-02T00:00:00Z"}
    assert av1.hidratar([{"x": -1}]) == {"x": None}


def test_leer_datos_lanza_401_si_no_hay_sesion():
    with pytest.raises(av1.ErrorAnimeAV1) as e:
        av1.leer_datos(_pagina(error=(401, "No autorizado")))
    assert e.value.status == 401


def test_ficha_a_anime_data():
    m = {"id": 159, "title": "Sousou no Frieren", "status": 0, "episodesCount": 28,
         "genres": [{"name": "Drama"}], "synopsis": "x", "category": {"slug": "tv-anime"}}
    d = av1.a_anime_data(m)
    assert (d.nombre, d.capitulos, d.estado_anime) == ("Sousou no Frieren", 28, "Finalizado")
    assert d.imagen == "https://cdn.animeav1.com/covers/159.jpg"
    assert av1.a_anime_data({**m, "status": 2}).capitulos == "28+"
    assert av1.a_anime_data({**m, "category": {"slug": "pelicula"}}).capitulos == "película"


def test_elegir_resultado_prefiere_titulo_exacto():
    rs = [{"title": "Konosuba 3: Bonus Stage", "categoryId": 3},
          {"title": "Kono Subarashii Sekai ni Shukufuku wo!", "categoryId": 1}]
    assert av1.elegir_resultado("kono subarashii sekai ni shukufuku wo", rs) is rs[1]


def test_normalizar_cookie_acepta_la_cabecera_entera():
    import animeav1_sync as s
    assert s.normalizar_cookie("cookie: a=1; b=2\n") == "a=1; b=2"
    assert s.normalizar_cookie('"sid=xyz"') == "sid=xyz"
    assert s.normalizar_cookie("sin-igual") == ""


def test_conectar_guarda_la_cookie_y_rechaza_una_mala(db):
    import animeav1_sync as s
    with pytest.raises(ValueError):
        s.conectar("sid=caducada", s=SesionFalsa(valida=False))
    assert not s.is_connected()
    r = s.conectar("cookie: sid=ok", s=SesionFalsa(entradas=[]))
    assert r["usuario"] == "lucas" and s.is_connected()
    assert db.get_config("animeav1_cookie") == "sid=ok"
    s.desconectar()
    assert not s.is_connected()


class AniListFalso:
    def __init__(self, por_mal):
        self.por_mal = por_mal

    def buscar_por_mal(self, mal):
        return self.por_mal.get(mal)


def test_pull_sube_progreso_sin_bajarlo_y_anade_lo_nuevo(db):
    import animeav1_sync as s
    from scrapers.base import AnimeData
    db.guardar_anime({"nombre": "Sousou no Frieren", "capitulos": "28",
                      "estado_usuario": "pendiente", "episodios_vistos": 0})
    db.guardar_anime({"nombre": "Kaiju No. 8", "capitulos": "12",
                      "estado_usuario": "viendo", "episodios_vistos": 9, "anilist_id": 99})
    db.set_config("animeav1_cookie", "sid=ok")
    entradas = [
        {"status": 0, "episode": 5, "media": {"id": 159, "slug": "sousou-no-frieren",
                                              "title": "Sousou no Frieren"}},
        # AnimeAV1 va por detrás (ep 3 < 9): no se baja el progreso.
        {"status": 0, "episode": 3, "media": {"id": 7, "slug": "kaijuu-8-gou", "title": "Kaijuu 8-gou"}},
        {"status": 2, "episode": 12, "media": {"id": 8, "slug": "nuevo", "title": "Nuevo Anime"}},
    ]
    medias = {"kaijuu-8-gou": {"id": 7, "malId": 52588, "title": "Kaijuu 8-gou"},
              "nuevo": {"id": 8, "malId": 1, "title": "Nuevo Anime", "episodesCount": 12,
                        "category": {"slug": "tv-anime"}, "status": 0}}
    al = AniListFalso({52588: AnimeData("Kaiju No. 8", 12, "", [], "", "anilist", "", anilist_id=99),
                       1: None})
    r = s.pull(s=SesionFalsa(entradas=entradas, medias=medias), anilist=al, sleep=lambda *_: None)
    assert r == {"added": 1, "updated": 1, "errors": 0, "total": 3}
    f = db.obtener_anime("Sousou no Frieren")
    assert (f["estado_usuario"], f["episodios_vistos"]) == ("viendo", 5)
    k = db.obtener_anime("Kaiju No. 8")
    assert (k["estado_usuario"], k["episodios_vistos"]) == ("viendo", 9)
    n = db.obtener_anime("Nuevo Anime")
    assert (n["estado_usuario"], n["episodios_vistos"], n["fuente"]) == ("completado", 12, "animeav1")
    assert json.loads(db.get_config("animeav1_ids"))["Kaiju No. 8"] == 7


def test_push_solo_acepta_coincidencias_seguras(db):
    import animeav1_sync as s
    db.guardar_anime({"nombre": "Frieren: Beyond Journey's End", "estado_usuario": "completado",
                      "episodios_vistos": 28, "anilist_id": 154587})
    db.guardar_anime({"nombre": "Anime Inventado", "estado_usuario": "viendo",
                      "episodios_vistos": 2, "anilist_id": 5})
    db.guardar_anime({"nombre": "Ya Igual", "estado_usuario": "viendo", "episodios_vistos": 4})
    db.set_config("animeav1_cookie", "sid=ok")
    ses = SesionFalsa(
        entradas=[{"status": 0, "episode": 4, "media": {"id": 50, "slug": "ya-igual", "title": "Ya Igual"}}],
        busquedas={"Sousou no Frieren": [{"id": "159", "title": "Sousou no Frieren", "slug": "sousou-no-frieren"}],
                   "Inventado Romaji": [{"id": "3", "title": "Otra Cosa", "slug": "otra-cosa"}]},
        medias={"sousou-no-frieren": {"id": 159, "malId": 52991},
                "otra-cosa": {"id": 3, "malId": 11111}})
    titulos = lambda ids, sleep=None: {154587: ("Sousou no Frieren", 52991, "Frieren"),  # noqa: E731
                                       5: ("Inventado Romaji", 777, "")}
    r = s.push(s=ses, sleep=lambda *_: None, titulos_anilist=titulos)
    assert r["pushed"] == 1 and r["skipped"] == 1 and r["not_found"] == 1
    assert {"mediaId": 159, "status": 2} in ses.posts
    assert {"mediaId": 159, "episode": 28} in ses.posts
    assert all(p.get("mediaId") != 3 for p in ses.posts)   # malId distinto: no se toca
