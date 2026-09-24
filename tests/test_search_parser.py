"""
Tests del parser de búsqueda con operadores de v2.2.

El parser vive en JS (templates/index.html) pero las reglas son simples
y reproducibles. Aquí replicamos la lógica en Python como espejo, igual
que test_auth.py hace con el PIN. Si el contrato cambia en JS, este test
debe actualizarse — sirve de spec ejecutable.
"""
from __future__ import annotations

import re

_OPS = {
    "genre": "genre", "genero": "genre",
    "source": "source", "fuente": "source",
    "status": "status", "estado": "status",
    "list": "list", "lista": "list",
    "eps": "eps", "episodios": "eps",
    "score": "score", "puntuacion": "score",
    "fav": "fav", "favorito": "fav",
}


def parse(raw):
    """Réplica del _parseSearch JS."""
    tokens = re.findall(r'(?:[^\s"]+|"[^"]*")+', raw or "")
    ops = {"free": []}
    for tok in tokens:
        m = re.match(r"^([a-záé]+):(.*)$", tok, re.IGNORECASE)
        if m:
            key = _OPS.get(m.group(1).lower())
            val = re.sub(r'^"(.*)"$', r'\1', m.group(2))
            if key:
                if key in ("eps", "score"):
                    cm = re.match(r"^(>=|<=|>|<|=)?(\d+(?:\.\d+)?)$", val)
                    if cm:
                        ops[key] = {"op": cm.group(1) or "=", "n": float(cm.group(2))}
                else:
                    ops.setdefault(key, []).append(val.lower())
                continue
        ops["free"].append(re.sub(r'^"(.*)"$', r'\1', tok).lower())
    return ops


def _cmp(a, op, b):
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "=": a == b}[op]


def matches(a, q):
    if not q or (not q["free"] and len(q) == 1):
        return True
    for f in q["free"]:
        if f not in a["nombre"].lower():
            return False
    if "genre" in q:
        gens = (a.get("genero") or "").lower()
        for g in q["genre"]:
            if g not in gens:
                return False
    if q.get("source") and (a.get("fuente") or "").lower() not in q["source"]:
        return False
    if q.get("status") and (a.get("estado_usuario") or "").lower() not in q["status"]:
        return False
    if q.get("list") and (a.get("lista_personalizada") or "").lower() not in q["list"]:
        return False
    if "eps" in q:
        try: n = int(a.get("capitulos") or 0)
        except (ValueError, TypeError): return False
        if not _cmp(n, q["eps"]["op"], q["eps"]["n"]): return False
    if "score" in q:
        try: s = float(a.get("puntuacion") or 0)
        except (ValueError, TypeError): return False
        if not _cmp(s, q["score"]["op"], q["score"]["n"]): return False
    if "fav" in q:
        want = any(v in ("1", "true", "sí", "si") for v in q["fav"])
        if bool(a.get("favorito")) != want:
            return False
    return True


# ── Parser ────────────────────────────────────────────────────────────────────

def test_parse_solo_texto_libre():
    assert parse("naruto") == {"free": ["naruto"]}


def test_parse_genre_operator():
    q = parse("genre:action")
    assert q["genre"] == ["action"] and q["free"] == []


def test_parse_genero_es():
    assert parse("genero:accion")["genre"] == ["accion"]


def test_parse_eps_con_operador():
    assert parse("eps:>20")["eps"] == {"op": ">", "n": 20.0}
    assert parse("eps:<=12")["eps"] == {"op": "<=", "n": 12.0}
    assert parse("eps:13")["eps"] == {"op": "=", "n": 13.0}


def test_parse_combinado():
    q = parse("naruto genre:action eps:>20 score:>=8 fav:1")
    assert q["free"] == ["naruto"]
    assert q["genre"] == ["action"]
    assert q["eps"]["op"] == ">" and q["eps"]["n"] == 20.0
    assert q["score"]["op"] == ">=" and q["score"]["n"] == 8.0
    assert q["fav"] == ["1"]


def test_parse_valor_con_comillas():
    q = parse('genre:"slice of life"')
    assert q["genre"] == ["slice of life"]


# ── Matcher ───────────────────────────────────────────────────────────────────

NARUTO = {
    "nombre": "Naruto", "fuente": "anilist", "estado_usuario": "viendo",
    "genero": "Action, Shounen, Adventure", "capitulos": "220",
    "puntuacion": 8.5, "favorito": 1, "lista_personalizada": "principal",
}
SOL = {
    "nombre": "Sol Levante", "fuente": "kitsu", "estado_usuario": "completado",
    "genero": "Drama", "capitulos": "1", "puntuacion": 6.0,
    "favorito": 0, "lista_personalizada": "completados",
}


def test_match_libre():
    assert matches(NARUTO, parse("naru"))
    assert not matches(SOL, parse("naru"))


def test_match_genre():
    assert matches(NARUTO, parse("genre:action"))
    assert not matches(SOL, parse("genre:action"))


def test_match_eps_comparator():
    assert matches(NARUTO, parse("eps:>20"))
    assert not matches(SOL, parse("eps:>20"))


def test_match_score():
    assert matches(NARUTO, parse("score:>=8"))
    assert not matches(SOL, parse("score:>=8"))


def test_match_fav():
    assert matches(NARUTO, parse("fav:1"))
    assert not matches(SOL, parse("fav:1"))
    assert matches(SOL, parse("fav:0"))


def test_match_combinado():
    """Naruto cumple TODO el query compuesto."""
    q = parse("genre:action eps:>20 score:>=8 fav:1")
    assert matches(NARUTO, q)
    assert not matches(SOL, q)


def test_match_genre_multiple():
    """Si hay dos `genre:X`, el anime debe tenerlos TODOS."""
    q = parse("genre:action genre:shounen")
    assert matches(NARUTO, q)
    assert not matches(SOL, q)
