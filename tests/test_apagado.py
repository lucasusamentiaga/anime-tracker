"""
Tests del apagado y del favicon.

Contexto: Miraru pasó a arrancar sin ventana de consola (Miraru.vbs), así que
cerrar la ventana negra dejó de ser una opción. `POST /api/apagar` es ahora la
única forma de pararlo, y por eso importa que:
  - solo funcione desde este ordenador (en modo red el móvil también llega al
    servidor, y no debe poder apagar el PC),
  - el camino feliz mate el proceso de verdad.

Ese segundo punto no se puede ejecutar tal cual: mataría a pytest. Se comprueba
que se lanza el hilo de apagado, con `os._exit` parcheado.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

_TMP = tempfile.mkdtemp(prefix="miraru_apagado_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "apagado.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


@pytest.fixture(autouse=True)
def _bd_propia(monkeypatch):
    """Fijar la BD en cada test (no solo al importar el módulo): si antes se
    ejecutó un test con el fixture `db`, la ruta del entorno era otra."""
    monkeypatch.setenv("ANIME_APP_DIR", _TMP)
    monkeypatch.setenv("ANIME_DB_PATH", os.path.join(_TMP, "apagado.db"))
    main.db.init_db()


@pytest.fixture
def client_local():
    """Cliente que se presenta como 127.0.0.1 (el caso normal)."""
    with TestClient(main.app, client=("127.0.0.1", 5000)) as c:
        yield c


@pytest.fixture
def client_remoto():
    """Cliente de otra máquina de la red (p. ej. el móvil)."""
    with TestClient(main.app, client=("192.168.1.55", 5000)) as c:
        yield c


# ── Permisos ──────────────────────────────────────────────────────────────────

def test_apagar_rechaza_a_un_cliente_de_la_red(client_remoto):
    r = client_remoto.post("/api/apagar")
    assert r.status_code == 403
    assert "este ordenador" in r.json()["detail"]


def test_apagar_desde_la_red_no_lanza_ningun_hilo(client_remoto):
    """Rechazar no basta: hay que confirmar que no se programó el suicidio."""
    with patch.object(main.threading, "Thread") as hilo:
        client_remoto.post("/api/apagar")
    hilo.assert_not_called()


# ── Camino feliz (sin matar a pytest) ────────────────────────────────────────

def test_apagar_desde_localhost_responde_ok_y_programa_el_cierre(client_local):
    with patch.object(main.threading, "Thread") as hilo:
        r = client_local.post("/api/apagar")

    assert r.status_code == 200
    assert r.json()["ok"] is True
    hilo.assert_called_once()
    # Debe ser demonio: si no, un apagado a medias dejaría el proceso colgado.
    assert hilo.call_args.kwargs["daemon"] is True


def test_la_rutina_de_apagado_llama_a_os_exit(client_local):
    """Ejecuta el objetivo del hilo de verdad, con os._exit y sleep parcheados."""
    with patch.object(main.threading, "Thread") as hilo:
        client_local.post("/api/apagar")
        objetivo = hilo.call_args.kwargs["target"]

    with patch.object(main.os, "_exit") as salir, \
         patch.object(main._time, "sleep") as dormir:
        objetivo()

    salir.assert_called_once_with(0)
    # La espera antes de morir es lo que permite que salga la respuesta HTTP.
    assert dormir.called


# ── Favicon ───────────────────────────────────────────────────────────────────

def test_favicon_se_sirve_desde_la_raiz(client_local):
    """Los navegadores piden /favicon.ico por su cuenta; antes daba 404 y las
    subpáginas salían con el icono genérico de documento."""
    r = client_local.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/x-icon"
    assert len(r.content) > 0


@pytest.mark.parametrize("ruta", [
    "/", "/app", "/stats", "/novedades", "/calendario",
    "/recomendaciones", "/peliculas", "/import", "/setup", "/mobile",
])
def test_todas_las_paginas_declaran_el_icono(client_local, ruta):
    """Regresión: solo index y peliculas lo traían, así que el logo desaparecía
    al salir del menú."""
    html = client_local.get(ruta).text
    assert '<link rel="icon" href="/static/icon.ico">' in html
