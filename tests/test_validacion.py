"""
El PATCH de un anime tiene que rechazar valores imposibles.

`ActualizarRequest` no validaba nada: `puntuacion: 999` y
`episodios_vistos: -50` se guardaban tal cual y corrompían en silencio la nota
media, las horas vistas y el heatmap, que pasaban a dar negativo. Un
`estado_usuario` inventado era peor todavía: se guardaba, pero luego no casaba
con ninguna consulta de estadísticas, así que el anime desaparecía de los
recuentos sin que nada avisara.

La interfaz nunca manda esos valores; el cliente móvil o un fetch a mano sí.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="miraru_valid_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "v.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import database as db  # noqa: E402
import main  # noqa: E402
from scrapers.base import AnimeData  # noqa: E402


class FuenteFalsa:
    """Scraper simulado: los tests no deben depender de la red."""

    def buscar(self, nombre):
        return AnimeData(
            nombre=nombre.strip()[:200] or "Sin nombre",
            capitulos=12, imagen="https://ejemplo/x.jpg", genero=["Action"],
            sinopsis="...", fuente="falsa", estado_anime="Finalizado",
        )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "SCRAPERS", {"anilist": FuenteFalsa()})
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        c.post("/api/animes", json={"nombre": "Cobaya", "fuente": "anilist"})
        yield c
    with db.get_conn() as conn:
        for t in ("animes", "media", "ep_log", "historial"):
            conn.execute(f"DELETE FROM {t}")


# ── Valores fuera de rango ───────────────────────────────────────────────────

@pytest.mark.parametrize("campo,valor", [
    ("puntuacion", 999),         # la escala es 0-10
    ("puntuacion", -5),
    ("episodios_vistos", -50),   # no se pueden ver episodios negativos
    ("favorito", 7),             # es un booleano 0/1
    ("notif_activa", -1),
])
def test_rechaza_valores_imposibles(client, campo, valor):
    r = client.patch("/api/animes/Cobaya", json={campo: valor})
    assert r.status_code == 422, f"{campo}={valor} fue aceptado"


def test_el_valor_rechazado_no_llega_a_la_base_de_datos(client):
    client.patch("/api/animes/Cobaya", json={"puntuacion": 999})
    a = db.obtener_anime("Cobaya")
    assert (a.get("puntuacion") or 0) <= 10


def test_las_estadisticas_no_pueden_dar_negativo(client):
    client.patch("/api/animes/Cobaya", json={"episodios_vistos": -50})
    s = client.get("/api/stats").json()
    assert (s.get("total_episodes") or 0) >= 0
    assert (s.get("total_hours") or 0) >= 0


# ── Estado del usuario ───────────────────────────────────────────────────────

def test_rechaza_un_estado_inventado(client):
    r = client.patch("/api/animes/Cobaya", json={"estado_usuario": "inventado"})
    assert r.status_code == 422


@pytest.mark.parametrize("estado", main.ESTADOS_VALIDOS)
def test_acepta_los_estados_validos(client, estado):
    r = client.patch("/api/animes/Cobaya", json={"estado_usuario": estado})
    assert r.status_code == 200
    assert db.obtener_anime("Cobaya")["estado_usuario"] == estado


@pytest.mark.parametrize("ingles,esperado", [
    ("watching", "viendo"),
    ("completed", "completado"),
    ("pending", "pendiente"),
    ("dropped", "abandonado"),
])
def test_normaliza_los_estados_en_ingles(client, ingles, esperado):
    """Antes convivían "watching" y "viendo" en la misma columna."""
    r = client.patch("/api/animes/Cobaya", json={"estado_usuario": ingles})
    assert r.status_code == 200
    assert db.obtener_anime("Cobaya")["estado_usuario"] == esperado


def test_el_estado_no_distingue_mayusculas(client):
    r = client.patch("/api/animes/Cobaya", json={"estado_usuario": "  Viendo "})
    assert r.status_code == 200
    assert db.obtener_anime("Cobaya")["estado_usuario"] == "viendo"


# ── El camino normal sigue funcionando ───────────────────────────────────────

def test_una_actualizacion_corriente_sigue_pasando(client):
    r = client.patch("/api/animes/Cobaya", json={
        "estado_usuario": "viendo",
        "puntuacion": 8.5,
        "episodios_vistos": 3,
        "favorito": 1,
    })
    assert r.status_code == 200
    a = db.obtener_anime("Cobaya")
    assert a["puntuacion"] == 8.5
    assert a["episodios_vistos"] == 3
    assert a["favorito"] == 1


def test_los_limites_exactos_se_aceptan(client):
    """0 y 10 son válidos: el rango es cerrado, no abierto."""
    assert client.patch("/api/animes/Cobaya", json={"puntuacion": 0}).status_code == 200
    assert client.patch("/api/animes/Cobaya", json={"puntuacion": 10}).status_code == 200
    assert client.patch("/api/animes/Cobaya", json={"episodios_vistos": 0}).status_code == 200
