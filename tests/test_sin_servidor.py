"""Pestaña abierta con Miraru cerrado (v2.12).

Al apagar el PC con la pestaña abierta, el Service Worker contestaba las
llamadas a la API con un 200 {"error": "offline"}; la página lo tomaba por
datos buenos y se quedaba sin franquicias (todos los animes "sueltos").
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SW = (RAIZ / "static" / "sw.js").read_text(encoding="utf-8")
INDEX = (RAIZ / "templates" / "index.html").read_text(encoding="utf-8")


def test_las_franquicias_se_guardan_para_usarlas_sin_conexion():
    lista = re.search(r"const API_OFFLINE = \[(.*?)\];", SW).group(1)
    assert "'/api/franquicias'" in lista and "'/api/animes/slim'" in lista


def test_sin_servidor_responde_503_y_no_200():
    assert "status: 503" in SW and "X-Miraru-Offline" in SW
    assert "{error: 'offline'}), {headers" not in SW   # el 200 de antes


def test_la_pagina_no_borra_lo_que_tenia_y_avisa():
    cargar = INDEX[INDEX.index("async function cargar()"):]
    cargar = cargar[:cargar.index("\n}\n")]
    assert "Array.isArray(dF.franquicias)" in cargar
    assert "_esSinServidor(rA)" in cargar and "_vigilarServidor()" in cargar
    assert "/api/actualizacion/espera" in INDEX[INDEX.index("function _vigilarServidor"):]
