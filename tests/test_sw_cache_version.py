"""Tests del manifest de cache del Service Worker (static/sw.js).

Dos garantias:
1. index.html y stats.html no llevan JS/CSS inline por encima de un bootstrap
   minimo: los bloques grandes viven en static/ (extraccion Tasks 2 y 3).
2. Direccion inversa a la del Task 2: TODO asset estatico referenciado desde
   esas dos paginas debe figurar en la lista de precache (STATIC_ASSETS) de
   sw.js; si falta, la primera visita sin conexion deja la pagina en blanco.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

# Igual que test_extract_assets.py: aislamos ANIME_FROZEN_DIR por si acaso,
# aunque estos tests solo leen HTML/JS y no tocan la BD.
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(BASE_DIR, "templates")
STATIC = os.path.join(BASE_DIR, "static")

# Bloques inline por encima de este tamanho cuentan como "logica no extraida".
# El bootstrap legitimo que queda (marcador de version en el index: un fetch
# a /api/version) mide ~200 caracteres.
_BOOTSTRAP_MAX = 400

# Assets extraidos que las paginas deben referenciar externamente.
_STATS_PAGE_JS = "stats_page.js"
_STATS_PAGE_CSS = "stats_page.css"


@pytest.fixture()
def cliente():
    """Cliente HTTP de FastAPI con lifespan completo (startup BD)."""
    with TestClient(main.app) as c:
        yield c


def _leer(nombre: str) -> str:
    with open(os.path.join(TEMPLATES, nombre), encoding="utf-8") as f:
        return f.read()


def _leer_sw() -> str:
    with open(os.path.join(STATIC, "sw.js"), encoding="utf-8") as f:
        return f.read()


def _precache_de_sw() -> set[str]:
    """Parsea el array STATIC_ASSETS de sw.js con regex."""
    sw = _leer_sw()
    m = re.search(r"const STATIC_ASSETS = \[(.*?)\];", sw, re.S)
    assert m, "sw.js ya no define STATIC_ASSETS: revisar el formato del manifest"
    return set(re.findall(r"'([^']+)'", m.group(1)))


@pytest.mark.parametrize("pagina", ["index.html", "stats.html"])
def test_pagina_sin_estilos_inline(pagina: str):
    """Ninguna de las dos paginas puede llevar <style> inline: CSS en static/."""
    assert "<style" not in _leer(pagina).lower(), f"{pagina} aun contiene <style>"


# Solo stats: el JS del index sigue inline (no lo extrajo ninguna tarea del
# plan; extraerlo tocaria templates/index.html, fuera del alcance de esta
# tarea). Cuando se extraiga, aniadir index.html a esta parametrizacion.
def test_stats_scripts_son_solo_bootstrap():
    """Los <script> sin src de stats toca medirlos: si supera el bootstrap, sobra logica.

    Regresion del HTML monolitico: cada byte de JS inline se descarga (y se
    reparsea) en cada visita y el SW no puede cachearlo por separado.
    """
    html = _leer("stats.html")
    # <script> exacto, no <script src=...> (ese ya es externo).
    for bloque in re.findall(r"<script>(.*?)</script>", html, re.S):
        assert len(bloque) <= _BOOTSTRAP_MAX, (
            f"stats.html: bloque <script> inline de {len(bloque)} caracteres "
            f"(max { _BOOTSTRAP_MAX}); extraerlo a static/"
        )


def test_stats_referencia_stats_page_js():
    """El JS de estadisticas debe vivir en static/stats_page.js y enlazarse."""
    html = _leer("stats.html")
    src = os.path.join(STATIC, _STATS_PAGE_JS)
    assert os.path.isfile(src), f"falta static/{_STATS_PAGE_JS}"
    enlace = f'/static/{_STATS_PAGE_JS}"'
    assert enlace in html, f"stats.html no referencia {enlace}"

    js = pathlib.Path(src).read_text(encoding="utf-8")
    assert "loadStats" in js and "loadHeatmap" in js, (
        "el JS extraido perdio las funciones principales"
    )


def test_stats_referencia_stats_page_css():
    """El CSS de estadisticas debe vivir en static/stats_page.css y enlazarse."""
    html = _leer("stats.html")
    src = os.path.join(STATIC, _STATS_PAGE_CSS)
    assert os.path.isfile(src), f"falta static/{_STATS_PAGE_CSS}"
    enlace = f'/static/{_STATS_PAGE_CSS}"'
    assert enlace in html, f"stats.html no referencia {enlace}"


def test_sw_cache_version_formato():
    """CACHE_NAME mantiene el formato versionado 'miraru-vN'."""
    sw = _leer_sw()
    m = re.search(r"const CACHE_NAME = '(miraru-v\d+)'", sw)
    assert m, "CACHE_NAME no sigue el formato 'miraru-vN'"


def _assets_referenciados(paginas: list[str]) -> set[str]:
    """Assets /static/... referenciados por atributo en las paginas.

    Se filtran las apariciones dentro de strings de JS que concatenan en
    runtime (contienen ' o +, p. ej. emblemas '/static/emblems/'+id+'.svg'):
    no se pueden precachear por nombre fijo ni se cargan al abrir la pagina.
    """
    refs: set[str] = set()
    for pagina in paginas:
        html = _leer(pagina)
        for _attr, ref in re.findall(r'((?:src|href))="(/static/[^"]+)"', html):
            if "'" in ref or "+" in ref:
                continue
            refs.add(ref)
    return refs


def test_todo_asset_referenciado_esta_en_precache():
    """Direccion inversa: cada /static de index+stats debe estar en sw.js.

    Task 2 dejo fuera esta comprobacion (solo verficaba que lo extraido
    aparecia como <link>): aqui se pinna para que NINGUN asset nuevo escapen
    del precache — si falta, la app offline se queda sin ese archivo.
    """
    precache = _precache_de_sw()
    refs = _assets_referenciados(["index.html", "stats.html"])
    assert refs, "no se detectaron assets: revisar el regex del test"
    faltan = sorted(refs - precache)
    assert not faltan, (
        f"sw.js no precachea assets referenciados por las paginas: {faltan}"
    )


def test_estatica_servida_200(cliente):
    """El mount /static sirve los assets extraidos con el content-type correcto."""
    resp_css = cliente.get("/static/stats_page.css")
    assert resp_css.status_code == 200
    assert "text/css" in resp_css.headers.get("content-type", "")

    resp_js = cliente.get("/static/stats_page.js")
    assert resp_js.status_code == 200
    assert "javascript" in resp_js.headers.get("content-type", "")


def test_get_stats_referencia_assets_extraidos(cliente):
    """GET /stats devuelve la pagina servida (FileResponse) y enlaza lo extraido."""
    resp = cliente.get("/stats")
    assert resp.status_code == 200
    assert 'href="/static/stats_page.css"' in resp.text
    assert 'src="/static/stats_page.js"' in resp.text
    assert "<style" not in resp.text.lower()
