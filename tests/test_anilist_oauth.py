"""
Conexión con AniList (OAuth) sin red: callback, intercambio de código y estados.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    import main
    return TestClient(main.app, client=("127.0.0.1", 1))


def test_callback_escapa_el_codigo(client):
    r = client.get("/api/anilist/callback", params={"code": "abc'</script><b>x"})
    assert r.status_code == 200
    assert "code: \"abc'<\\/script><b>x\"" in r.text      # literal JS válido
    assert "</script><b>" not in r.text.split("<script>", 1)[1].split("</script>")[0]


def test_callback_sin_codigo(client):
    assert "no se recibió" in client.get("/api/anilist/callback").text


def test_connect_ok_guarda_token(client, monkeypatch):
    import anilist_sync
    monkeypatch.setattr(anilist_sync, "exchange_code", lambda *a: {"access_token": "TOK"})
    monkeypatch.setattr(anilist_sync, "fetch_viewer", lambda t: {"id": 7, "name": "Lucas"})
    r = client.post("/api/anilist/connect", json={"client_id": "1", "client_secret": "s", "code": "c"})
    assert r.json() == {"ok": True, "username": "Lucas", "userid": 7}
    assert anilist_sync.is_connected()
    assert client.get("/api/anilist/status").json()["username"] == "Lucas"
    client.post("/api/anilist/disconnect")
    assert not anilist_sync.is_connected()


def test_connect_sin_token_es_400_no_500(client, monkeypatch):
    import anilist_sync
    monkeypatch.setattr(anilist_sync, "exchange_code", lambda *a: {})
    r = client.post("/api/anilist/connect", json={"client_id": "1", "client_secret": "s", "code": "c"})
    assert r.status_code == 400


def test_connect_faltan_datos(client):
    assert client.post("/api/anilist/connect", json={"code": "c"}).status_code == 400


def test_estados_de_anilist_son_validos():
    import anilist_sync
    import main
    for estado in anilist_sync._STATUS_FROM_ANILIST.values():
        assert estado in main.ESTADOS_VALIDOS, estado
