"""Aviso de versión nueva para quien instaló Miraru desde Microsoft Store (v2.12.1).

Se compara con la versión que la Store ofrece de verdad (catálogo público), no con
la release de GitHub: esa sale antes de que Microsoft certifique el paquete.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

CATALOGO = ('{"Products":[{"DisplaySkuAvailabilities":[{"Sku":{"Properties":{"Packages":['
            '{"PackageFullName":"LucasUsamentiaga.Miraru_2.11.4.0_x64__3mgbhj4kf1wv2"},'
            '{"PackageFullName":"LucasUsamentiaga.Miraru_2.13.0.0_x64__3mgbhj4kf1wv2"}]}}}]}]}')


def test_lee_la_version_mas_alta_del_catalogo():
    import main
    assert main.version_en_store(CATALOGO) == "2.13.0"
    assert main.version_en_store("{}") == ""


def test_instalacion_store_compara_con_la_store_y_no_con_github(app_dir, monkeypatch):
    import database
    importlib.reload(database)
    database.init_db()
    import main

    class Resp:
        status_code = 200
        text = CATALOGO

    llamadas = []
    monkeypatch.setattr(main.requests, "get", lambda url, **k: llamadas.append(url) or Resp())
    monkeypatch.setattr(main, "_tipo_instalacion", lambda: "store")
    monkeypatch.setattr(main, "_update_cache", {"ts": 0.0, "data": None})
    monkeypatch.setattr(main, "VERSION", "2.12.0")
    d = TestClient(main.app).get("/api/version/latest").json()
    assert d["instalacion"] == "store" and d["latest"] == "2.13.0" and d["update_available"]
    assert d["url"].startswith("ms-windows-store://pdp/?productid=")
    # La versión sale del catálogo de la Store; el CHANGELOG solo da los titulares.
    assert "displaycatalog.mp.microsoft.com" in llamadas[0]
    assert all("displaycatalog.mp.microsoft.com" in u or u == main._URL_CHANGELOG for u in llamadas)


def test_la_pagina_muestra_el_aviso_y_lo_recuerda_a_los_3_dias():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "templates" / "index.html").read_text(encoding="utf-8")
    trozo = html[html.index("async function comprobarActualizacion"):]
    assert "_avisoActualizacion(d, false)" in trozo
    aviso = html[html.index("function _avisoActualizacion"):]
    assert "aviso_version" in aviso and "_REAVISO_MS" in aviso
    # Store, install.ps1 y .exe tienen cada uno su botón
    for txt in ("Abrir Microsoft Store", "Actualizar ahora", "Descargar la versión nueva"):
        assert txt in aviso


def test_novedades_del_changelog():
    import main
    texto = """# Changelog

## v2.15.0 — Algo

- **Tu lista sobrevive a formatear el PC.** Detalle largo.
- Un punto sin titular que no sale.
- **Guía `nueva`**: más cosas

## v2.14.1 — Otra

- **Viejo**
"""
    assert main.novedades_en_changelog(texto, "2.15.0") == ["Tu lista sobrevive a formatear el PC", "Guía nueva"]
    assert main.novedades_en_changelog(texto, "9.9.9") == []
    real = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    import core
    assert main.novedades_en_changelog(real, core.VERSION), "el CHANGELOG no tiene titulares para esta versión"


def test_aviso_de_novedades_una_vez_por_version(db, monkeypatch):
    import main
    importlib.reload(main)
    c = TestClient(main.app, client=("127.0.0.1", 1))
    db.guardar_anime({"nombre": "Frieren", "lista": "Viendo", "capitulos_vistos": 1})
    d = c.get("/api/aviso-novedades").json()
    assert d["mostrar"] is True and d["versiones"][0]["version"] == main.VERSION
    c.post("/api/aviso-novedades/visto")
    assert c.get("/api/aviso-novedades").json()["mostrar"] is False


def test_novedades_usuario_nuevo_no_las_ve(db):
    import main
    importlib.reload(main)
    c = TestClient(main.app, client=("127.0.0.1", 1))
    assert c.get("/api/aviso-novedades").json()["mostrar"] is False   # lista vacía = recién instalado


def test_novedades_de_versiones_saltadas():
    import novedades
    vs = [n["version"] for n in novedades.pendientes("2.14.1", "2.16.0")]
    assert vs == ["2.16.0", "2.15.0"]
    assert novedades.pendientes("2.16.0", "2.16.0") == []
    assert [n["version"] for n in novedades.pendientes("2.15.0", "2.16.0")] == ["2.16.0"]
    import core
    assert any(n["version"] == core.VERSION for n in novedades.NOVEDADES), "falta la tarjeta de novedades de esta versión"
