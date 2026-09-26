"""
Web Push (push_web.py + routers/push.py), Service Worker con alcance "/" y
daemon de notificaciones (email y/o push, sin repetir avisos tras reiniciar).
"""
from __future__ import annotations

import json

import pytest

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc",
       "keys": {"p256dh": "BPUB", "auth": "AUTH"}}


@pytest.fixture
def pw(db, monkeypatch):
    import push_web
    monkeypatch.setattr(push_web, "db", db)
    return push_web


class _Resp:
    def __init__(self, status):
        self.status_code = status


class _Err(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = _Resp(status)


def test_clave_publica_estable_y_formato(pw):
    if not pw.DISPONIBLE:
        pytest.skip("pywebpush no instalado")
    k1, k2 = pw.clave_publica(), pw.clave_publica()
    assert k1 == k2                         # se genera una vez y se guarda
    assert "=" not in k1 and len(k1) == 87  # base64url de 65 bytes (punto sin comprimir)


def test_suscribir_valida_y_deduplica(pw):
    assert pw.suscribir({"endpoint": "http://inseguro", "keys": SUB["keys"]}) is False
    assert pw.suscribir({"endpoint": SUB["endpoint"]}) is False
    assert pw.suscribir(SUB) is True
    assert pw.suscribir(SUB) is True
    assert pw.num_suscripciones() == 1
    assert pw.desuscribir(SUB["endpoint"]) is True
    assert pw.num_suscripciones() == 0


def test_enviar_borra_caducadas(pw):
    otra = {**SUB, "endpoint": SUB["endpoint"] + "2"}
    pw.suscribir(SUB); pw.suscribir(otra)
    llamadas = []

    def fake(subscription_info, data, **kw):
        llamadas.append(json.loads(data))
        if subscription_info["endpoint"].endswith("2"):
            raise _Err(410)
    assert pw.enviar("T", "B", tag="x", _webpush=fake) == (1, 1)
    assert pw.num_suscripciones() == 1
    assert llamadas[0]["title"] == "T" and llamadas[0]["tag"] == "x"


def test_enviar_error_temporal_no_borra(pw):
    pw.suscribir(SUB)

    def fake(**kw):
        raise _Err(500)
    assert pw.enviar("T", _webpush=fake) == (0, 0)
    assert pw.num_suscripciones() == 1


# ── Endpoints ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db, monkeypatch):
    from fastapi.testclient import TestClient

    import main
    import push_web
    monkeypatch.setattr(push_web, "db", db)
    return TestClient(main.app, client=("127.0.0.1", 1))


def test_endpoints_push(client):
    import push_web
    if push_web.DISPONIBLE:
        assert len(client.get("/api/push/vapid").json()["key"]) == 87
    assert client.post("/api/push/subscribe", json={"endpoint": "x"}).status_code == 400
    assert client.post("/api/push/subscribe", json=SUB).json()["suscripciones"] == 1
    assert client.get("/api/push/status").json()["suscripciones"] == 1
    assert client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).json()["borrada"]
    assert client.post("/api/push/test").status_code == 400      # sin suscripciones


def test_service_worker_en_raiz_con_alcance(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["service-worker-allowed"] == "/"
    assert "javascript" in r.headers["content-type"]
    assert "addEventListener('push'" in r.text


# ── Daemon de notificaciones ─────────────────────────────────────────────────

def test_daemon_push_sin_email_y_sin_repetir(db, monkeypatch):
    import main
    import push_web
    monkeypatch.setattr(push_web, "db", db)
    db.guardar_anime({"nombre": "Frieren", "capitulos": "28", "episodios_vistos": 10,
                      "notif_activa": 1, "estado_usuario": "viendo"})
    db.set_config("email_notif", "")
    push_web.suscribir(SUB)
    enviados = []
    monkeypatch.setattr(push_web, "enviar", lambda *a, **k: enviados.append((a, k)) or (1, 0))
    monkeypatch.setattr(main, "_fetch_ultimos_episodios",
                        lambda animes: {"Frieren": {"total": 28, "next_ep": 0, "next_at": 0}})
    emails = []
    monkeypatch.setattr(main, "_notif_enviar_nuevo_disponible", lambda *a: emails.append(a))
    assert main._comprobar_nuevos_episodios() == [("Frieren", 28)]
    assert len(enviados) == 1 and emails == []
    assert "18 episodios" in enviados[0][0][1]
    # "reinicio": lo avisado está en config, no en memoria → no se repite
    assert main._comprobar_nuevos_episodios() == []
    assert len(enviados) == 1


def test_daemon_sin_email_ni_push_no_consulta(db, monkeypatch):
    import main
    import push_web
    monkeypatch.setattr(push_web, "db", db)
    db.guardar_anime({"nombre": "X", "notif_activa": 1})
    db.set_config("email_notif", "")
    monkeypatch.setattr(main, "_fetch_ultimos_episodios",
                        lambda a: (_ for _ in ()).throw(AssertionError("no debía consultar")))
    assert main._comprobar_nuevos_episodios() == []
