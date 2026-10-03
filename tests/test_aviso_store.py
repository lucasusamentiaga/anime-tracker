"""Aviso de versión nueva para quien instaló Miraru desde Microsoft Store (v2.12.1).

Se compara con la versión que la Store ofrece de verdad (catálogo público), no con
la release de GitHub: esa sale antes de que Microsoft certifique el paquete.
"""
from __future__ import annotations

import importlib

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
    assert all("displaycatalog.mp.microsoft.com" in u for u in llamadas)


def test_la_pagina_muestra_el_aviso_una_vez_por_version():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "templates" / "index.html").read_text(encoding="utf-8")
    trozo = html[html.index("async function comprobarActualizacion"):]
    assert "_avisoVersionStore(d, false)" in trozo
    assert "aviso_store_version" in html[html.index("function _avisoVersionStore"):]
