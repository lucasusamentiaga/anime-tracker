"""Trabajos largos en segundo plano con progreso (v2.12)."""
from __future__ import annotations

import threading
import time

import trabajos


def _esperar(tid, estado, maximo=5):
    fin = time.time() + maximo
    while time.time() < fin:
        if trabajos.estado(tid)["estado"] == estado:
            return trabajos.estado(tid)
        time.sleep(0.02)
    raise AssertionError(trabajos.estado(tid))


def test_cuenta_el_progreso_y_guarda_el_resultado():
    def f(p):
        p.total(3)
        for i in range(3):
            p.avanzar(1, f"paso {i}")
        return {"hecho": True}
    t = _esperar(trabajos.lanzar("prueba-ok", f), "terminado")
    assert (t["hechos"], t["total"], t["porcentaje"], t["resultado"]) == (3, 3, 100, {"hecho": True})


def test_no_lanza_dos_del_mismo_tipo_a_la_vez_y_se_puede_cancelar():
    seguir = threading.Event()

    def f(p):
        p.total(100)
        while True:
            seguir.wait(0.01)
            p.avanzar()
    a = trabajos.lanzar("prueba-larga", f)
    assert trabajos.lanzar("prueba-larga", f) == a
    assert trabajos.cancelar(a)
    _esperar(a, "cancelado")


def test_un_error_se_informa():
    def f(p):
        raise RuntimeError("sesión caducada")
    t = _esperar(trabajos.lanzar("prueba-error", f), "error")
    assert "caducada" in t["error"]


def test_endpoints(app_dir):
    import importlib

    from fastapi.testclient import TestClient

    import database
    importlib.reload(database)
    database.init_db()
    import main
    c = TestClient(main.app)
    assert c.get("/api/trabajos/noexiste").status_code == 404
    tid = trabajos.lanzar("prueba-endpoint", lambda p: {"ok": 1})
    _esperar(tid, "terminado")
    assert c.get(f"/api/trabajos/{tid}").json()["resultado"] == {"ok": 1}
