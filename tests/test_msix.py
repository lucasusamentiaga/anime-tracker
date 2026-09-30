"""Paquete MSIX para Microsoft Store (build_msix.py)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import build_msix

NS = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10"}


def test_version_de_cuatro_numeros_acabada_en_cero():
    v = build_msix.version_msix()
    partes = v.split(".")
    assert len(partes) == 4 and partes[-1] == "0" and all(p.isdigit() for p in partes)


def test_manifiesto_valido_para_la_store():
    xml = build_msix.generar_manifiesto("123Lucas.Miraru", "CN=ABC-123", "Lucas & co", "2.11.4.0")
    raiz = ET.fromstring(xml.encode("utf-8"))
    ident = raiz.find("m:Identity", NS)
    assert ident.get("Name") == "123Lucas.Miraru" and ident.get("Publisher") == "CN=ABC-123"
    app = raiz.find("m:Applications/m:Application", NS)
    assert app.get("Executable") == "AnimeTracker.exe"
    assert app.get("EntryPoint") == "Windows.FullTrustApplication"
    assert "runFullTrust" in xml
    assert raiz.find("m:Properties/m:PublisherDisplayName", NS).text == "Lucas & co"


def test_identidad_de_pruebas_sin_variables(monkeypatch):
    for k in ("MIRARU_MSIX_NAME", "MIRARU_MSIX_PUBLISHER", "MIRARU_MSIX_PUBLISHER_NAME"):
        monkeypatch.delenv(k, raising=False)
    assert build_msix.identidad()[:2] == (build_msix.NOMBRE_PRUEBAS, build_msix.EDITOR_PRUEBAS)
