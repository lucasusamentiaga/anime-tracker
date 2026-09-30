"""
El .exe empaquetado debe incluir todos los módulos propios.

Regresión: build.py los enumeraba a mano y anilist_sync.py, watch_folder.py y
metadatos.py se quedaron fuera → la versión compilada fallaba al arrancar con
ImportError aunque desde el código funcionase todo.
"""
from __future__ import annotations

import ast
import pathlib

import build

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _imports_locales(archivo: pathlib.Path) -> set[str]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            nombres.add(nodo.module.split(".")[0])
    return {n for n in nombres if (RAIZ / f"{n}.py").exists()}


def test_incluye_los_que_faltaban():
    nombres = {p.name for p in build.modulos_propios()}
    assert {"metadatos.py", "anilist_sync.py", "watch_folder.py"} <= nombres
    assert "build.py" not in nombres and "launcher.py" not in nombres


def test_todo_import_local_de_la_app_se_empaqueta():
    empaquetados = {p.stem for p in build.modulos_propios()}
    for origen in [RAIZ / "main.py", *build.modulos_propios(),
                   *(RAIZ / "routers").glob("*.py")]:
        faltan = _imports_locales(origen) - empaquetados - {"build", "launcher"}
        assert not faltan, f"{origen.name} importa {faltan} y no se empaquetan"


def test_hidden_imports_cubren_paquetes():
    for p in (RAIZ / "scrapers").glob("*.py"):
        if p.stem != "__init__":
            assert f"scrapers.{p.stem}" in build.HIDDEN
    for p in (RAIZ / "routers").glob("*.py"):
        if p.stem != "__init__":
            assert f"routers.{p.stem}" in build.HIDDEN
    assert "metadatos" in build.HIDDEN


def test_instalador_explica_el_bloqueo_de_smart_app_control(tmp_path):
    """WinError 4551 al abrir la app tras instalar: antes salía como
    "Error de instalación" con el texto crudo de Windows."""
    src = tmp_path / "inst.py"
    build._write_installer_source(src)
    codigo = src.read_text(encoding="utf-8")
    ast.parse(codigo)  # el instalador generado es Python válido
    assert "4551" in codigo
    arbol = ast.parse(codigo)
    textos = next(
        ast.literal_eval(n.value) for n in ast.walk(arbol)
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TEXTS"
    )
    for lang in ("es", "en", "fr", "de"):
        assert "\n" in textos[lang]["blocked"], lang


def test_exes_llevan_metadatos_de_producto():
    """SignPath exige el mismo nombre de producto y versión en todos los binarios."""
    import core

    for nombre in ("Miraru-Portable", "AnimeTracker", "AnimeTracker-Setup"):
        texto = build.version_file(nombre, "prueba").read_text(encoding="utf-8")
        assert "StringStruct('ProductName', 'Miraru')" in texto
        assert f"StringStruct('ProductVersion', '{core.VERSION}')" in texto
        assert f"StringStruct('OriginalFilename', '{nombre}.exe')" in texto
    fuente = (RAIZ / "build.py").read_text(encoding="utf-8")
    assert fuente.count('"--version-file"') == 2
