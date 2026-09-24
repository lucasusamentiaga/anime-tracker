"""
La versión debe ser la misma en todas partes.

Llegó a estar escrita a mano en cuatro sitios y los cuatro discrepaban:
main.py 2.8.0, core.py 2.7.0, el instalador 2.4.0 y el manifest de la PWA 2.7.0.
No es cosmético:
  - el instalador escribe su APP_VERSION en el registro de Windows, así que
    "Programas y características" mostraba una versión que no existía;
  - el cliente móvil compara la versión del servidor para decidir si le sirve;
  - el CHANGELOG deja de ser fiable para saber qué tienes instalado.

Ahora `core.VERSION` es la única declaración y el resto la deriva. Este test
vigila que nadie vuelva a escribirla a mano.
"""
from __future__ import annotations

import json
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent

import core  # noqa: E402


def test_formato_de_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", core.VERSION), core.VERSION


def test_main_reexporta_la_de_core():
    import main
    assert main.VERSION == core.VERSION


def test_main_no_declara_su_propia_version():
    """Debe importarla, no escribirla: dos declaraciones vuelven a divergir."""
    texto = (RAIZ / "main.py").read_text(encoding="utf-8")
    assert not re.search(r'^VERSION\s*=\s*["\']', texto, re.M), \
        "main.py vuelve a declarar VERSION; debe importarla de core"


def test_el_manifest_de_la_pwa_coincide():
    datos = json.loads((RAIZ / "static" / "manifest.json").read_text(encoding="utf-8"))
    assert datos["version"] == core.VERSION


def test_el_instalador_usa_el_marcador_y_no_un_numero():
    """build.py sustituye @@VERSION@@ al generar el instalador."""
    texto = (RAIZ / "build.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "@@VERSION@@"' in texto
    assert not re.search(r'APP_VERSION\s*=\s*["\']\d', texto), \
        "El instalador vuelve a llevar la versión escrita a mano"


def test_build_lee_la_version_de_core():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_build_probe", RAIZ / "build.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.VERSION == core.VERSION


def test_el_changelog_documenta_la_version_actual():
    """La versión publicada tiene que tener su entrada; si no, nadie sabe qué
    cambió."""
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    versiones = re.findall(r"^##\s*v(\d+\.\d+\.\d+)", texto, re.M)
    assert versiones, "El CHANGELOG no tiene ninguna entrada con formato ## vX.Y.Z"
    assert versiones[0] == core.VERSION, (
        f"CHANGELOG encabeza {versiones[0]} pero la app es {core.VERSION}"
    )
