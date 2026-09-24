"""Tests del parser de AnimeThemes (openings/endings). No toca la red."""
from __future__ import annotations

import themes_api

PAYLOAD = {
    "anime": [{
        "name": "Cowboy Bebop",
        "animethemes": [
            {
                "slug": "ED1",
                "song": {"title": "The Real Folk Blues",
                         "artists": [{"name": "Mai Yamane"}]},
                "animethemeentries": [
                    {"videos": [{"link": "https://v.animethemes.moe/ed1.webm"}]}
                ],
            },
            {
                "slug": "OP2",
                "song": {"title": "Tank! (v2)", "artists": []},
                "animethemeentries": [
                    {"videos": [{"link": "https://v.animethemes.moe/op2.webm"}]}
                ],
            },
            {
                "slug": "OP10",
                "song": {"title": "Décimo"},
                "animethemeentries": [{"videos": [{"link": "https://v.animethemes.moe/op10.webm"}]}],
            },
            {
                "slug": "OP1",
                "song": {"title": "Tank!", "artists": [{"name": "Seatbelts"}]},
                "animethemeentries": [
                    {"videos": []},                                     # sin vídeo aquí…
                    {"videos": [{"link": "https://v.animethemes.moe/op1.webm"}]},  # …pero sí aquí
                ],
            },
            {   # sin ningún vídeo → debe descartarse
                "slug": "OP3",
                "song": {"title": "Sin vídeo"},
                "animethemeentries": [{"videos": []}],
            },
        ],
    }]
}


def test_extrae_temas_con_video():
    t = themes_api.parsear(PAYLOAD)
    assert len(t) == 4                       # OP3 descartado por no tener vídeo
    assert all(x["video"] for x in t)


def test_ordena_ops_antes_que_eds_y_numericamente():
    slugs = [x["slug"] for x in themes_api.parsear(PAYLOAD)]
    # OP10 no debe colarse antes que OP2 (orden numérico, no alfabético)
    assert slugs == ["OP1", "OP2", "OP10", "ED1"]


def test_extrae_titulo_y_artista():
    t = themes_api.parsear(PAYLOAD)
    op1 = next(x for x in t if x["slug"] == "OP1")
    assert op1["titulo"] == "Tank!"
    assert op1["artista"] == "Seatbelts"
    assert op1["tipo"] == "OP"


def test_busca_video_en_entradas_posteriores():
    """La primera entrada puede no tener vídeo; debe seguir buscando."""
    op1 = next(x for x in themes_api.parsear(PAYLOAD) if x["slug"] == "OP1")
    assert op1["video"].endswith("op1.webm")


def test_tipo_ed_detectado():
    ed = next(x for x in themes_api.parsear(PAYLOAD) if x["slug"] == "ED1")
    assert ed["tipo"] == "ED" and ed["artista"] == "Mai Yamane"


def test_payload_vacio_o_invalido_no_lanza():
    assert themes_api.parsear({}) == []
    assert themes_api.parsear({"anime": []}) == []
    assert themes_api.parsear(None) == []
    assert themes_api.parsear({"anime": [{"animethemes": None}]}) == []


def test_respeta_el_limite():
    assert len(themes_api.parsear(PAYLOAD, limite=2)) == 2
