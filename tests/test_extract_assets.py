"""Tests de extracción de assets inline a archivos estáticos.

Garantiza que templates/index.html no lleve CSS inline (<style>) y que cada
archivo CSS extraído bajo static/ esté referenciado mediante <link>, servido
con 200 vía el mount de FastAPI (/static).
"""
from __future__ import annotations

import os
import re

import pytest

# Igual que test_api.py: aislamos ANIME_FROZEN_DIR por si acaso, aunque estos
# tests solo leen HTML/CSS y no tocan la BD.
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(BASE_DIR, "templates")
STATIC = os.path.join(BASE_DIR, "static")

# Archivos CSS extraídos del index.html (Task 2). Si Task 3 añade más,
# se apunta aquí y el resto de tests se adaptan solos.
_CSS_EXTRAIDOS = ["index_page.css"]


@pytest.fixture()
def cliente():
    """Cliente HTTP de FastAPI con lifespan completo (startup BD)."""
    with TestClient(main.app) as c:
        yield c


def _leer_index() -> str:
    with open(os.path.join(TEMPLATES, "index.html"), encoding="utf-8") as f:
        return f.read()


def test_index_sin_estilos_inline():
    """El index no puede llevar <style> inline: todo el CSS vive en static/.

    Regresión del HTML monolítico: impedía cachear el CSS por separado del
    contenido y generaba páginas enormes de ~5000 líneas.
    """
    html = _leer_index()
    assert "<style" not in html.lower(), "index.html aún contiene <style> inline"


def test_index_referencia_cada_css_extraido():
    """Cada CSS extraído bajo static/ debe estar enlazado en index.html."""
    html = _leer_index()
    # Enlaces <link rel="stylesheet" href="/static/...css"> del HTML.
    enlaces = set(re.findall(r'href="(/static/[^"]+\.css)"', html))
    for nombre in _CSS_EXTRAIDOS:
        href = f"/static/{nombre}"
        assert href in enlaces, f"index.html no referencia {href}"
        assert os.path.isfile(os.path.join(STATIC, nombre)), f"falta {nombre}"


def test_orden_cascada_preservado():
    """index_page.css debe cargar ANTES que theme.css (orden original).

    En el HTML original el bloque <style> iba primero y theme.css después;
    si se invierte el orden, las mismas reglas cambian de ganador por cascada.
    """
    html = _leer_index()
    pos_pagina = html.find('href="/static/index_page.css"')
    pos_tema = html.find('href="/static/theme.css"')
    assert pos_pagina != -1 and pos_tema != -1
    assert pos_pagina < pos_tema, "index_page.css debe preceder a theme.css"


@pytest.mark.parametrize("css", _CSS_EXTRAIDOS)
def test_css_servido_200(cliente, css):
    """El mount /static sirve cada CSS extraído con 200 y texto CSS."""
    resp = cliente.get(f"/static/{css}")
    assert resp.status_code == 200
    assert "text/css" in resp.headers.get("content-type", "")


def test_index_servido_y_enlaza_css(cliente):
    """GET / devuelve el HTML servido (FileResponse) y enlaza el CSS extraído."""
    resp = cliente.get("/app")
    assert resp.status_code == 200
    assert 'href="/static/index_page.css"' in resp.text
