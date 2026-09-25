"""Tests del parser de personajes/seiyuus (Jikan). No toca la red."""
from __future__ import annotations

import personajes_api

PAYLOAD = {
    "data": [
        {   # secundario: debe quedar DESPUÉS del principal
            "character": {"name": "Jet Black",
                          "images": {"jpg": {"image_url": "http://img/jet.jpg"}}},
            "role": "Supporting",
            "voice_actors": [
                {"language": "English", "person": {"name": "Beau Billingslea",
                                                   "images": {"jpg": {"image_url": "http://img/beau.jpg"}}}},
                {"language": "Japanese", "person": {"name": "Unshou Ishizuka",
                                                    "images": {"jpg": {"image_url": "http://img/unshou.jpg"}}}},
            ],
        },
        {
            "character": {"name": "Spike Spiegel",
                          "images": {"jpg": {"image_url": "http://img/spike.jpg"}}},
            "role": "Main",
            "voice_actors": [
                {"language": "Japanese", "person": {"name": "Kouichi Yamadera",
                                                    "images": {"jpg": {"image_url": "http://img/kouichi.jpg"}}}},
            ],
        },
        {   # sin actores de voz: debe seguir apareciendo
            "character": {"name": "Ein", "images": {"jpg": {"image_url": "http://img/ein.jpg"}}},
            "role": "Main",
            "voice_actors": [],
        },
        {"character": {"name": ""}, "role": "Main"},   # sin nombre: se descarta
    ]
}


def test_principales_primero():
    p = personajes_api.parsear(PAYLOAD)
    assert [x["nombre"] for x in p] == ["Spike Spiegel", "Ein", "Jet Black"]


def test_descarta_personajes_sin_nombre():
    assert all(x["nombre"] for x in personajes_api.parsear(PAYLOAD))
    assert len(personajes_api.parsear(PAYLOAD)) == 3


def test_prefiere_seiyuu_japones():
    """Jet Black trae inglés primero, pero el relevante en anime es el japonés."""
    jet = next(x for x in personajes_api.parsear(PAYLOAD) if x["nombre"] == "Jet Black")
    assert jet["seiyuu"] == "Unshou Ishizuka"
    assert jet["idioma"] == "Japanese"


def test_extrae_imagenes():
    spike = next(x for x in personajes_api.parsear(PAYLOAD) if x["nombre"] == "Spike Spiegel")
    assert spike["imagen"] == "http://img/spike.jpg"
    assert spike["seiyuu_img"] == "http://img/kouichi.jpg"


def test_personaje_sin_voz_no_rompe():
    ein = next(x for x in personajes_api.parsear(PAYLOAD) if x["nombre"] == "Ein")
    assert ein["seiyuu"] == "" and ein["imagen"] == "http://img/ein.jpg"


def test_payload_invalido_no_lanza():
    assert personajes_api.parsear({}) == []
    assert personajes_api.parsear(None) == []
    assert personajes_api.parsear({"data": None}) == []


def test_respeta_limite():
    assert len(personajes_api.parsear(PAYLOAD, limite=1)) == 1


def test_primer_mal_id():
    assert personajes_api.primer_mal_id({"data": [{"mal_id": 1}, {"mal_id": 5}]}) == 1
    assert personajes_api.primer_mal_id({"data": []}) == 0
    assert personajes_api.primer_mal_id({}) == 0
    assert personajes_api.primer_mal_id({"data": [{}]}) == 0


# ── Endpoints de ficha: los errores de red no se cachean ─────────────────────

def test_error_de_red_no_se_cachea(db, monkeypatch):
    from fastapi.testclient import TestClient

    import main  # noqa: F401  (registra el router)
    from routers import themes as rt
    llamadas = []

    def falla(nombre):
        llamadas.append(nombre)
        return None
    monkeypatch.setattr(rt, "_buscar_temas", falla)
    monkeypatch.setattr(rt, "_buscar_personajes", falla)
    rt._cache.clear(); rt._cache_personajes.clear()
    c = TestClient(main.app, client=("127.0.0.1", 1))
    for _ in range(2):
        assert c.get("/api/animes/Naruto/themes").json() == {"temas": [], "cacheado": False, "error": True}
        assert c.get("/api/animes/Naruto/personajes").json()["error"] is True
    assert len(llamadas) == 4          # se reintenta cada vez, no queda cacheado
    assert "naruto" not in rt._cache and "naruto" not in rt._cache_personajes


def test_resultado_valido_si_se_cachea(db, monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from routers import themes as rt
    monkeypatch.setattr(rt, "_buscar_temas", lambda n: [{"slug": "OP1"}])
    rt._cache.clear()
    c = TestClient(main.app, client=("127.0.0.1", 1))
    assert c.get("/api/animes/Bleach/themes").json()["cacheado"] is False
    assert c.get("/api/animes/Bleach/themes").json()["cacheado"] is True
