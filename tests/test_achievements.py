"""Tests de logros/emblemas (módulo puro achievements.py — no importa main)."""
from __future__ import annotations

import achievements


def _unlocked(stats):
    r = achievements.evaluar_logros(stats)
    return {l["id"] for l in r["logros"] if l["unlocked"]}, r


def test_biblioteca_vacia_no_desbloquea_nada():
    ids, r = _unlocked({})
    assert ids == set()
    assert r["desbloqueados"] == 0
    assert r["total"] == len(achievements.LOGROS)


def test_primer_paso_y_coleccionista():
    ids, _ = _unlocked({"total": 10})
    assert "primer_paso" in ids and "coleccionista" in ids
    assert "bibliotecario" not in ids  # requiere 50


def test_maraton_y_sin_frenos_por_episodios():
    ids, _ = _unlocked({"total": 1, "episodios": 1000})
    assert "maratoniano" in ids and "sin_frenos" in ids


def test_rachas():
    ids, _ = _unlocked({"racha_max": 30})
    assert "en_racha" in ids and "imparable" in ids
    ids2, _ = _unlocked({"racha_max": 7})
    assert "en_racha" in ids2 and "imparable" not in ids2


def test_omnivoro_requiere_los_tres_tipos():
    assert "omnivoro" not in _unlocked({"animes": 5, "series": 2})[0]
    assert "omnivoro" in _unlocked({"animes": 1, "series": 1, "peliculas": 1})[0]


def test_no_crashea_con_claves_faltantes_o_none():
    r = achievements.evaluar_logros({"total": None, "episodios": "x"})
    assert isinstance(r["desbloqueados"], int)


def test_estructura_de_salida():
    r = achievements.evaluar_logros({"total": 1})
    lg = r["logros"][0]
    assert {"id", "nombre", "desc", "emblema", "tier", "unlocked"} <= set(lg)
