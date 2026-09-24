"""
Las migraciones no deben insistir con fuentes que están caídas.

Recorren cientos de animes probando las fuentes en serie. Con AniList
devolviendo 403 durante días, cada anime perdía varios segundos en ella —con
sus reintentos y backoff— antes de llegar a una que respondiese. Medido en la
biblioteca real: 6 animes reparados en 15 minutos.

El cortocircuito aparta una fuente tras N fallos seguidos, pero la readmite en
cuanto vuelve a acertar, para no excluir de por vida a una fuente intermitente.
"""
from __future__ import annotations

import migrations


class _Res:
    def __init__(self, caps):
        self.capitulos = caps
        self.imagen = ""
        self.sinopsis = ""
        self.genero = []
        self.estado_anime = ""


class Contadora:
    """Scraper que cuenta cuántas veces la han consultado."""

    def __init__(self, resultado=None):
        self.resultado = resultado
        self.llamadas = 0

    def buscar(self, nombre):
        self.llamadas += 1
        return self.resultado


def test_deja_de_consultar_una_fuente_caida(monkeypatch):
    caida = Contadora(None)
    buena = Contadora(_Res(12))
    monkeypatch.setattr(migrations, "SCRAPERS", {"caida": caida, "buena": buena})

    corto = migrations.Cortocircuito(umbral=3)
    for _ in range(10):
        migrations.buscar_sync_con_fallback("X", "caida", corto)

    # Se la consulta hasta llegar al umbral y luego se aparta.
    assert caida.llamadas == 3, f"siguió consultando la fuente caída ({caida.llamadas} veces)"
    assert buena.llamadas == 10


def test_sin_cortocircuito_se_consultan_todas_siempre(monkeypatch):
    """Comportamiento anterior, conservado para quien no pase `corto`."""
    caida = Contadora(None)
    buena = Contadora(_Res(12))
    monkeypatch.setattr(migrations, "SCRAPERS", {"caida": caida, "buena": buena})

    for _ in range(5):
        migrations.buscar_sync_con_fallback("X", "caida")

    assert caida.llamadas == 5


def test_una_fuente_intermitente_vuelve_a_admitirse(monkeypatch):
    intermitente = Contadora(None)
    monkeypatch.setattr(migrations, "SCRAPERS", {"intermitente": intermitente})

    corto = migrations.Cortocircuito(umbral=3)
    migrations.buscar_sync_con_fallback("X", "intermitente", corto)
    migrations.buscar_sync_con_fallback("X", "intermitente", corto)
    assert not corto.descartada("intermitente")

    # Acierta: el contador se reinicia
    intermitente.resultado = _Res(24)
    migrations.buscar_sync_con_fallback("X", "intermitente", corto)
    assert corto.fallos.get("intermitente", 0) == 0

    # Vuelve a fallar: necesita 3 fallos NUEVOS para apartarse
    intermitente.resultado = None
    for _ in range(2):
        migrations.buscar_sync_con_fallback("X", "intermitente", corto)
    assert not corto.descartada("intermitente")


def test_detecta_que_todas_las_fuentes_estan_caidas(monkeypatch):
    a, b = Contadora(None), Contadora(None)
    monkeypatch.setattr(migrations, "SCRAPERS", {"a": a, "b": b})

    corto = migrations.Cortocircuito(umbral=2)
    assert not corto.todas_caidas()
    for _ in range(2):
        migrations.buscar_sync_con_fallback("X", "a", corto)
    assert corto.todas_caidas()


def test_la_migracion_se_corta_si_todo_esta_caido(monkeypatch):
    """No tiene sentido recorrer 300 animes cuando no responde nadie."""
    animes = [{"nombre": f"A{i}", "fuente": "a", "capitulos": "200"} for i in range(50)]

    class FakeDB:
        def __init__(self):
            self.updates = {}
        def get_config(self, k): return None
        def set_config(self, k, v): pass
        def listar_animes(self): return animes
        def refrescar_metadata_anime(self, nombre, cambios):
            self.updates[nombre] = cambios
            return True, "ok"

    fake = FakeDB()
    caida = Contadora(None)
    monkeypatch.setattr(migrations, "db", fake)
    monkeypatch.setattr(migrations, "SCRAPERS", {"a": caida})

    resumen = migrations.migrar_cap200(sleep=0)

    assert resumen["abortado"] is True
    # Unas pocas consultas, no 50.
    assert caida.llamadas <= 6, f"consultó {caida.llamadas} veces con la fuente caída"
