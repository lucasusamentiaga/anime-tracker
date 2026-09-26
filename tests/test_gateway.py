"""Tests de recomendaciones para principiantes (módulo puro gateway_anime.py)."""
from __future__ import annotations

import gateway_anime as G


def test_sin_generos_mantiene_orden_curado():
    r = G.recomendar_principiante([])
    assert r["personalizado"] is False
    # El primer pick por defecto es FMA:B (mejor "primer anime")
    assert r["empieza_aqui"]["titulo"].startswith("Fullmetal Alchemist")
    assert len(r["recomendaciones"]) == 12


def test_prioriza_por_genero_favorito():
    # A quien le gusta el romance, "empieza por aquí" debe ser un romance
    r = G.recomendar_principiante(["Romance"])
    assert r["personalizado"] is True
    assert "Romance" in r["empieza_aqui"]["generos"]


def test_deporte_sube_haikyu():
    r = G.recomendar_principiante(["Sports", "Comedy"])
    ids = [a["titulo"] for a in r["recomendaciones"]]
    assert "Haikyu!!" in ids[:3]


def test_generos_desconocidos_no_rompen():
    r = G.recomendar_principiante(["GéneroInventado", ""])
    assert r["empieza_aqui"] is not None
    assert len(r["recomendaciones"]) == 12


def test_todas_las_entradas_tienen_campos():
    for a in G.GATEWAY:
        assert a["id"] and a["titulo"] and a["generos"] and a["motivo"]


def test_limite_respetado():
    r = G.recomendar_principiante(["Action"], limite=5)
    assert len(r["recomendaciones"]) == 5


def test_no_recomienda_lo_que_ya_esta_en_la_lista():
    # Attack on Titan (16498) por ID y Death Note por título
    r = G.recomendar_principiante([], excluir_ids=[16498, 0, None], excluir_claves={"death note"})
    titulos = [a["titulo"] for a in r["recomendaciones"]]
    assert "Attack on Titan" not in titulos and "Death Note" not in titulos
    assert r["empieza_aqui"]["titulo"].startswith("Fullmetal Alchemist")


def test_todo_visto_devuelve_vacio():
    r = G.recomendar_principiante([], excluir_ids=[a["id"] for a in G.GATEWAY])
    assert r["empieza_aqui"] is None and r["recomendaciones"] == []
