"""El +1: tope en el total, registro de actividad coherente y móvil igual que PC."""
from __future__ import annotations

import importlib
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

N = "Dandadan"


@pytest.fixture
def cliente(db):
    import main
    importlib.reload(main)
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c, main


def _eps_log(db):
    with db.get_conn() as c:
        return [r[0] for r in c.execute("SELECT episodio FROM ep_log WHERE nombre=? ORDER BY episodio", (N,))]


def test_plus1_no_pasa_del_total(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": N, "capitulos": "2", "episodios_vistos": 1})
    assert c.post(f"/api/animes/{N}/plus1").json()["episodios_vistos"] == 2
    r = c.post(f"/api/animes/{N}/plus1")
    assert r.status_code == 409
    assert db.obtener_anime(N)["episodios_vistos"] == 2
    assert _eps_log(db) == [2]


@pytest.mark.parametrize("total", ["12+", "?", ""])
def test_plus1_sin_tope_si_el_total_no_es_definitivo(cliente, db, total):
    c, _ = cliente
    db.guardar_anime({"nombre": N, "capitulos": total, "episodios_vistos": 30})
    assert c.post(f"/api/animes/{N}/plus1").status_code == 200


def test_deshacer_plus1_quita_el_episodio_del_registro(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": N, "capitulos": "12", "episodios_vistos": 3})
    c.post(f"/api/animes/{N}/plus1")
    assert _eps_log(db) == [4]
    c.patch("/api/animes/" + quote(N), json={"episodios_vistos": 3})
    assert _eps_log(db) == []


def test_bajar_a_cero_no_borra_la_historia_antigua(cliente, db):
    c, _ = cliente
    db.guardar_anime({"nombre": N, "capitulos": "12", "episodios_vistos": 5})
    with db.get_conn() as con:
        con.executemany("INSERT INTO ep_log (nombre, episodio, fecha) VALUES (?,?,?)",
                        [(N, i, "2025-01-01 20:00:00") for i in range(1, 6)])
    c.patch("/api/animes/" + quote(N), json={"episodios_vistos": 0})   # empezar un rewatch
    assert _eps_log(db) == [1, 2, 3, 4, 5]


def test_plus1_del_movil_cuenta_igual(cliente, db, monkeypatch):
    c, main = cliente
    db.guardar_anime({"nombre": N, "capitulos": "1", "episodios_vistos": 0})
    monkeypatch.setattr(main, "_require_auth", lambda request: None)
    assert c.post(f"/api/mobile/animes/{N}/plus1").json()["episodios_vistos"] == 1
    assert _eps_log(db) == [1]
    assert c.post(f"/api/mobile/animes/{N}/plus1").status_code == 409


def test_plus1_sube_a_anilist_si_esta_conectado(cliente, db, monkeypatch):
    c, main = cliente
    db.guardar_anime({"nombre": N, "capitulos": "12", "episodios_vistos": 0, "anilist_id": 171018})
    subidos = []
    monkeypatch.setattr(main.anilist_sync, "is_connected", lambda: True)
    monkeypatch.setattr(main, "_sync_bg", lambda fn, *a: subidos.append((fn, a)))
    c.post(f"/api/animes/{N}/plus1")
    assert any(fn is main.anilist_sync.push_anime for fn, _ in subidos)
