"""
Qué se ve desde la red local cuando el modo móvil está activo.

El guard de LAN dejaba pasar todo lo que no empezara por `/api/`, así que
`/docs`, `/redoc` y `/openapi.json` quedaban abiertos: cualquiera en el mismo
WiFi podía abrir la documentación interactiva y llevarse el mapa completo de la
API — rutas, parámetros y esquemas — sin token.

Aquí se fija el contrato:
  - documentación: solo desde este ordenador,
  - páginas HTML: accesibles (no llevan datos),
  - datos bajo /api/: siempre con token.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="miraru_lan_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "lan.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import database as db  # noqa: E402
import main  # noqa: E402

DOCS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


@pytest.fixture
def modo_movil():
    """Activa el modo móvil mientras dure el test."""
    with TestClient(main.app, client=("127.0.0.1", 1)):
        db.set_config("mobile_enabled", "1")
    yield
    with TestClient(main.app, client=("127.0.0.1", 1)):
        db.set_config("mobile_enabled", "0")


@pytest.fixture
def remoto():
    """Otro equipo de la WiFi (p. ej. el móvil)."""
    with TestClient(main.app, client=("192.168.1.77", 5000)) as c:
        yield c


@pytest.fixture
def local():
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c


@pytest.mark.parametrize("ruta", DOCS)
def test_la_documentacion_no_se_publica_a_la_lan(modo_movil, remoto, ruta):
    r = remoto.get(ruta)
    # 404 y no 401: no hay motivo para confirmar que esas rutas existen.
    assert r.status_code == 404, f"{ruta} visible desde la LAN"


@pytest.mark.parametrize("ruta", DOCS)
def test_la_documentacion_sigue_disponible_en_este_pc(modo_movil, local, ruta):
    assert local.get(ruta).status_code == 200


def test_las_paginas_html_siguen_sirviendose_a_la_lan(modo_movil, remoto):
    """El móvil necesita cargar /app; los datos ya los protege el token."""
    assert remoto.get("/app").status_code == 200


def test_los_datos_siguen_exigiendo_token(modo_movil, remoto):
    assert remoto.get("/api/animes").status_code == 401


def test_sin_modo_movil_no_hay_bloqueo(local):
    """Con el modo móvil apagado el servidor solo escucha en 127.0.0.1, así que
    el guard no debe estorbar."""
    assert local.get("/docs").status_code == 200
    assert local.get("/api/animes").status_code == 200


# ── Caché con TTL por entrada ────────────────────────────────────────────────

def test_la_cache_respeta_el_ttl_de_cada_entrada():
    main._cache_set("corta", "a", ttl=0.05)
    main._cache_set("larga", "b", ttl=60)
    assert main._cache_get("corta") == "a"

    import time
    time.sleep(0.08)

    assert main._cache_get("corta") is None, "la entrada corta debería haber caducado"
    assert main._cache_get("larga") == "b", "la entrada larga no debe caducar con ella"


def test_la_cache_usa_el_ttl_por_defecto_si_no_se_indica():
    main._cache_set("porDefecto", "x")
    assert main._cache_get("porDefecto") == "x"
    guardado = main._search_cache["porDefecto"]
    assert guardado[2] == main._CACHE_TTL
