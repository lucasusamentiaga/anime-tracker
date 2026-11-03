"""v2.16: Google Sheets se sincroniza con un vigilante (lista entera, cuando
lleva unos segundos sin cambiar) en vez de fila a fila."""
import time

import sheets_sync


def test_vigilante_sube_una_vez_tras_quedar_quieta(monkeypatch):
    enviados, resultados = [], []
    monkeypatch.setattr(sheets_sync, "sincronizar_todo",
                        lambda animes, sid, cred: (enviados.append(len(animes)) or (True, "ok")))
    estado = {"gen": 1, "animes": [{"nombre": "A"}]}
    sheets_sync._vig.update(hilo=None, huella=None, parar=False)
    sheets_sync.vigilar(lambda: ("sid", "cred"), lambda: estado["gen"],
                        lambda: estado["animes"], lambda ok, m: resultados.append(ok),
                        espera=0.2, cada=0.05)
    try:
        time.sleep(0.6)
        assert enviados == [1]                      # primer arranque: se envía
        time.sleep(0.4)
        assert enviados == [1]                      # sin cambios: nada más
        estado["gen"] += 1                          # cambia algo que no sale en la hoja
        time.sleep(0.6)
        assert enviados == [1]
        estado["animes"] = [{"nombre": "A"}, {"nombre": "B"}]
        estado["gen"] += 1
        time.sleep(0.6)
        assert enviados == [1, 2]
        assert all(resultados)
    finally:
        sheets_sync._vig["parar"] = True
        time.sleep(0.1)


def test_vigilante_sin_configurar_no_envia(monkeypatch):
    enviados = []
    monkeypatch.setattr(sheets_sync, "sincronizar_todo", lambda *a: enviados.append(1) or (True, ""))
    sheets_sync._vig.update(hilo=None, huella=None, parar=False)
    sheets_sync.vigilar(lambda: None, lambda: 1, lambda: [{"nombre": "A"}], lambda *a: None,
                        espera=0.1, cada=0.05)
    try:
        time.sleep(0.4)
        assert enviados == []
    finally:
        sheets_sync._vig["parar"] = True
        time.sleep(0.1)


def test_vigilante_reintenta_si_falla_y_no_espera_eternamente(monkeypatch):
    intentos = []

    def falla_y_luego_va(animes, sid, cred):
        intentos.append(1)
        return (len(intentos) > 1, "sin internet" if len(intentos) == 1 else "ok")

    monkeypatch.setattr(sheets_sync, "sincronizar_todo", falla_y_luego_va)
    estado = {"gen": 1}
    sheets_sync._vig.update(hilo=None, huella=None, parar=False)
    sheets_sync.vigilar(lambda: ("s", "c"), lambda: estado["gen"], lambda: [{"nombre": "A"}],
                        lambda *a: None, espera=0.2, cada=0.05, maximo=0.5, reintento=0.3)
    try:
        time.sleep(0.5)
        assert len(intentos) == 1                    # primer intento, falla
        time.sleep(0.5)
        assert len(intentos) == 2                    # reintento solo, sin cambios nuevos
        # Cambios sin parar: aun así sube antes de `maximo`.
        sheets_sync._vig["huella"] = None
        fin = time.time() + 0.9
        while time.time() < fin:
            estado["gen"] += 1
            time.sleep(0.05)
        assert len(intentos) >= 3
    finally:
        sheets_sync._vig["parar"] = True
        time.sleep(0.1)
