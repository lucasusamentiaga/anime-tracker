"""
Tests del threshold de log_episode en /api/animes/{nombre} PATCH.

v2.3: si subes episodios_vistos mucho de golpe (>3) no loggeamos para no
falsificar el heatmap con timestamps "now" en bulk imports.

No importamos main.py (necesita FastAPI), reproducimos la lógica.
"""
from __future__ import annotations


def _aplicar_delta(db, nombre: str, viejos: int, nuevos: int):
    """Reproduce el bloque de PATCH /api/animes que loggea eps en ep_log."""
    db.actualizar_anime(nombre, {"episodios_vistos": nuevos})
    delta = nuevos - viejos
    if 0 < delta <= 3:
        for ep in range(viejos + 1, nuevos + 1):
            db.log_episode(nombre, ep)


def test_subida_de_1_se_loggea(db):
    db.guardar_anime({"nombre": "A", "episodios_vistos": 5})
    _aplicar_delta(db, "A", 5, 6)
    assert db.ep_log_total() == 1


def test_subida_de_3_se_loggea(db):
    db.guardar_anime({"nombre": "A", "episodios_vistos": 5})
    _aplicar_delta(db, "A", 5, 8)
    assert db.ep_log_total() == 3


def test_subida_de_4_NO_se_loggea(db):
    """4 eps de golpe se considera corrección manual / bulk → no logear."""
    db.guardar_anime({"nombre": "A", "episodios_vistos": 0})
    _aplicar_delta(db, "A", 0, 4)
    assert db.ep_log_total() == 0


def test_subida_de_50_NO_se_loggea(db):
    """Caso típico: importas desde MAL/AniList con 50 eps vistos."""
    db.guardar_anime({"nombre": "A", "episodios_vistos": 0})
    _aplicar_delta(db, "A", 0, 50)
    assert db.ep_log_total() == 0


def test_bajada_NO_loggea(db):
    """Si bajas episodios_vistos (corregir error), no loggea nada."""
    db.guardar_anime({"nombre": "A", "episodios_vistos": 10})
    _aplicar_delta(db, "A", 10, 5)
    assert db.ep_log_total() == 0


def test_sin_cambio_NO_loggea(db):
    db.guardar_anime({"nombre": "A", "episodios_vistos": 5})
    _aplicar_delta(db, "A", 5, 5)
    assert db.ep_log_total() == 0
