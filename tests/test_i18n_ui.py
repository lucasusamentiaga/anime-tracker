"""Diccionario de textos de interfaz (i18n_ui.py) que aplica static/i18n-dom.js."""
from __future__ import annotations

import re

import i18n_ui


def test_cada_entrada_tiene_los_tres_idiomas():
    for es, trad in i18n_ui.UI.items():
        assert len(trad) == len(i18n_ui.LANGS), es
        assert all(t.strip() for t in trad), es


def test_patrones_compilan_y_usan_sus_grupos():
    for rx, plantillas in i18n_ui.PATTERNS:
        c = re.compile(rx)
        for tpl in plantillas:
            usados = {int(g) for g in re.findall(r"\$(\d)", tpl)}
            assert usados <= set(range(1, c.groups + 1)), (rx, tpl)


def _aplicar(lang: str, s: str) -> str | None:
    d = i18n_ui.ui_para(lang)
    if s in d["map"]:
        return d["map"][s]
    for rx, tpl in d["patterns"]:
        if re.search(rx, s):
            return re.sub(rx, re.sub(r"\$(\d)", r"\\\1", tpl), s)
    return None


def test_ejemplos_con_numeros():
    assert _aplicar("en", "3 temporadas") == "3 seasons"
    assert _aplicar("en", "Ep 12 en 5d") == "Ep 12 in 5d"
    assert _aplicar("de", "Completa 10 títulos") == "Schließe 10 Titel ab"
    assert _aplicar("fr", "¿Eliminar Frieren?") == "Supprimer Frieren ?"


def test_espanol_no_traduce_nada():
    assert i18n_ui.ui_para("es") == {"lang": "es", "map": {}, "patterns": []}


def test_claves_normalizadas_sin_colisiones():
    d = i18n_ui.ui_para("en")["map"]
    assert len(d) == len(i18n_ui.UI)
    assert all("  " not in k and k == k.strip() for k in d)
