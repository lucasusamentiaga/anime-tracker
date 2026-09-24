"""Tests del Rich Presence de Discord (parte pura + degradación silenciosa)."""
from __future__ import annotations

import discord_presence as dp


def test_formatea_serie_con_progreso():
    e = dp.formatear_estado({"nombre": "Frieren", "capitulos": "28", "episodios_vistos": 12})
    assert e["details"] == "Frieren"
    assert e["state"] == "Episodio 12 de 28"


def test_formatea_serie_sin_total_conocido():
    e = dp.formatear_estado({"nombre": "One Piece", "capitulos": "?", "episodios_vistos": 5})
    assert e["state"] == "Episodio 5"


def test_formatea_pelicula():
    e = dp.formatear_estado({"nombre": "Your Name", "capitulos": "película"})
    assert e["state"] == "Película"


def test_formatea_sin_empezar():
    e = dp.formatear_estado({"nombre": "X", "capitulos": "12", "episodios_vistos": 0})
    assert e["state"] == "Empezando"


def test_nombres_larguisimos_se_recortan():
    e = dp.formatear_estado({"nombre": "A" * 400, "capitulos": "12"})
    assert len(e["details"]) <= 128


def test_no_lanza_con_datos_vacios():
    e = dp.formatear_estado({})
    assert e["details"] and e["state"]


def test_desactivado_no_intenta_conectar(monkeypatch):
    """Si el usuario no lo activó, actualizar() es un no-op silencioso."""
    monkeypatch.setattr(dp.db, "get_config", lambda k: "")
    llamado = []
    monkeypatch.setattr(dp, "_conectar", lambda: llamado.append(1))
    assert dp.actualizar({"nombre": "X"}) is False
    assert llamado == []


def test_activado_pero_sin_discord_no_rompe(monkeypatch):
    """Discord cerrado / pypresence ausente → devuelve False, no excepción."""
    monkeypatch.setattr(dp.db, "get_config",
                        lambda k: "1" if k == "discord_enabled" else "123456")
    monkeypatch.setattr(dp, "_conectar", lambda: None)
    assert dp.actualizar({"nombre": "X", "capitulos": "12"}) is False
