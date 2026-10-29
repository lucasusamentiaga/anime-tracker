"""«Deshacer» tras borrar devuelve el anime TAL CUAL estaba.

Antes la app restauraba desde los datos ligeros de la lista (/api/animes/slim):
se perdían las notas, la sinopsis, la fecha de alta (el anime saltaba arriba),
el historial de estados, los episodios vistos con fecha (estadísticas y mapa
de actividad) y las etiquetas. Ahora DELETE devuelve una copia completa y
/api/animes/restore la vuelve a poner.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

ROOT_NAME = "Frieren: Beyond Journey’s End"


@pytest.fixture
def cliente(db):
    import main
    importlib.reload(main)
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c


def _preparar(db):
    ok, _ = db.guardar_anime({"nombre": ROOT_NAME, "fuente": "anilist", "capitulos": "28",
                              "sinopsis": "Una elfa maga…", "genero": ["Fantasy"]})
    assert ok
    db.actualizar_anime(ROOT_NAME, {"notas": "mi nota", "episodios_vistos": 3,
                                    "estado_usuario": "viendo", "puntuacion": 9})
    with db.get_conn() as c:
        c.execute("UPDATE animes SET creado_en='2024-01-02 03:04:05' WHERE nombre=?", (ROOT_NAME,))
        c.executemany("INSERT OR IGNORE INTO ep_log (nombre, episodio, fecha) VALUES (?,?,?)",
                      [(ROOT_NAME, i, f"2024-01-0{i} 20:00:00") for i in (1, 2, 3)])
        c.execute("INSERT INTO historial (nombre, estado, fecha, nota) VALUES (?,?,?,?)",
                  (ROOT_NAME, "viendo", "2024-01-01", ""))
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?,?)",
                  (f"tags:{ROOT_NAME}", '["favorita"]'))
    db._invalidar_cache()


def _estado(db):
    with db.get_conn() as c:
        fila = dict(c.execute("SELECT * FROM animes WHERE nombre=?", (ROOT_NAME,)).fetchone())
        fila.pop("id")
        eps = c.execute("SELECT episodio, fecha FROM ep_log WHERE nombre=? ORDER BY episodio",
                        (ROOT_NAME,)).fetchall()
        hist = c.execute("SELECT estado, fecha FROM historial WHERE nombre=?", (ROOT_NAME,)).fetchall()
        tags = c.execute("SELECT value FROM config WHERE key=?", (f"tags:{ROOT_NAME}",)).fetchone()
    return fila, [tuple(e) for e in eps], [tuple(h) for h in hist], tags and tags[0]


def test_borrar_y_deshacer_conserva_todo(cliente, db):
    _preparar(db)
    antes = _estado(db)
    from urllib.parse import quote
    r = cliente.delete("/api/animes/" + quote(ROOT_NAME, safe=""))
    assert r.status_code == 200
    copia = r.json()["copia"]
    assert copia["anime"]["notas"] == "mi nota" and len(copia["ep_log"]) == 3
    assert db.obtener_anime(ROOT_NAME) is None
    r = cliente.post("/api/animes/restore", json=copia)
    assert r.status_code == 200, r.text
    assert _estado(db) == antes


def test_restaurar_dos_veces_es_duplicado(cliente, db):
    _preparar(db)
    from urllib.parse import quote
    copia = cliente.delete("/api/animes/" + quote(ROOT_NAME, safe="")).json()["copia"]
    assert cliente.post("/api/animes/restore", json=copia).status_code == 200
    assert cliente.post("/api/animes/restore", json=copia).status_code == 409


def test_restaurar_formato_antiguo_sigue_funcionando(cliente, db):
    r = cliente.post("/api/animes/restore", json={"nombre": "Dandadan", "capitulos": "12"})
    assert r.status_code == 200
    assert db.obtener_anime("Dandadan")["capitulos"] == "12"


@pytest.mark.parametrize("cuerpo", [{"nombre": 123}, {"anime": {}}, {"anime": {"nombre": "  "}}])
def test_restaurar_datos_malos_da_400(cliente, cuerpo):
    assert cliente.post("/api/animes/restore", json=cuerpo).status_code == 400


def test_borrado_multiple_sin_confirm_y_con_deshacer():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "templates" / "index.html").read_text(encoding="utf-8")
    ini = src.index("async function bulkEliminar")
    cuerpo = src[ini:src.index("\n}\n", ini)]
    assert "confirm(" not in cuerpo
    assert "mostrarUndoSnackbar(" in cuerpo


def test_sin_ventanas_nativas_del_navegador():
    """alert()/confirm()/prompt() no siguen el tema ni se traducen: se usan las
    ventanas propias de static/dialogos.js."""
    import re
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    for f in [*raiz.glob("templates/*.html"), *raiz.glob("static/*.js")]:
        if f.name == "dialogos.js":
            continue
        codigo = re.sub(r"//[^\n]*", "", f.read_text(encoding="utf-8"))
        assert not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", codigo), f.name
        if re.search(r"miraru(Confirmar|Pedir|Aviso)\(", codigo):
            assert "/static/dialogos.js" in codigo, f"{f.name} usa las ventanas sin cargar dialogos.js"
