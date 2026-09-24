"""
Tests de la auto-reparacion del bug historico "cap=200 fantasma" (v2.6.3).

El codigo ya no clampa a 200, pero las entradas guardadas antes de v2.6.2 aun
tienen capitulos="200". migrations.migrar_cap200() las repara: re-consulta la
fuente (con fallback) y deja "?" si es irresoluble. Nunca debe quedar un 200
falso tras la migracion.

Se testea contra migrations.py (modulo ligero) — no contra main — para no
arrastrar FastAPI ni init_db.
"""
from __future__ import annotations

import pytest

import migrations


class _Res:
    def __init__(self, caps):
        self.capitulos = caps
        self.imagen = "http://img"
        self.sinopsis = "sinopsis"
        self.genero = ["Accion"]


class _ScraperOK:
    def __init__(self, caps):
        self.caps = caps
    def buscar(self, nombre):
        return _Res(self.caps)


class _ScraperFail:
    def buscar(self, nombre):
        return None


class _FakeDB:
    """Imita la interfaz de database.py que usa migrar_cap200."""
    def __init__(self, animes, cfg=None):
        self._animes = animes
        self._cfg = dict(cfg or {})
        self.updates = {}
    def get_config(self, k):
        return self._cfg.get(k)
    def set_config(self, k, v):
        self._cfg[k] = v
    def listar_animes(self):
        return self._animes
    def refrescar_metadata_anime(self, nombre, cambios):
        self.updates[nombre] = cambios
        return True, "ok"


def _patch(monkeypatch, db, scrapers):
    monkeypatch.setattr(migrations, "db", db)
    monkeypatch.setattr(migrations, "SCRAPERS", scrapers)


def test_cap200_se_reemplaza_por_numero_real(monkeypatch):
    db = _FakeDB([{"nombre": "One Piece", "fuente": "anilist", "capitulos": "200"}])
    _patch(monkeypatch, db, {"anilist": _ScraperOK(1130)})
    migrations.migrar_cap200(sleep=0)
    assert db.updates["One Piece"]["capitulos"] == "1130"


def test_cap200_usa_fallback_si_falla_la_fuente_original(monkeypatch):
    db = _FakeDB([{"nombre": "X", "fuente": "animeflv", "capitulos": "200"}])
    _patch(monkeypatch, db, {"animeflv": _ScraperFail(), "anilist": _ScraperOK(24)})
    migrations.migrar_cap200(sleep=0)
    assert db.updates["X"]["capitulos"] == "24"


def test_cap200_irresoluble_pasa_a_interrogante(monkeypatch):
    db = _FakeDB([{"nombre": "Y", "fuente": "anilist", "capitulos": "200"}])
    _patch(monkeypatch, db, {"anilist": _ScraperFail()})
    migrations.migrar_cap200(sleep=0)
    assert db.updates["Y"]["capitulos"] == "?"


def test_cap200_sin_afectados_no_hace_nada(monkeypatch):
    db = _FakeDB([{"nombre": "W", "capitulos": "12"}])
    _patch(monkeypatch, db, {"anilist": _ScraperOK(12)})
    resumen = migrations.migrar_cap200(sleep=0)
    assert db.updates == {}
    assert resumen["revisados"] == 0


def test_cap200_es_idempotente(monkeypatch):
    """Tras reparar, los animes ya no tienen 200: la segunda pasada no toca nada."""
    animes = [{"nombre": "Z", "fuente": "anilist", "capitulos": "200"}]
    db = _FakeDB(animes)
    _patch(monkeypatch, db, {"anilist": _ScraperOK(12)})

    migrations.migrar_cap200(sleep=0)
    assert db.updates["Z"]["capitulos"] == "12"

    # Simular que la reparación quedó guardada y volver a pasar
    animes[0]["capitulos"] = "12"
    db.updates.clear()
    resumen = migrations.migrar_cap200(sleep=0)
    assert db.updates == {}
    assert resumen["revisados"] == 0


# ── Regresión: el bug del flag "ya migrado" ──────────────────────────────────

def test_cap200_repara_datos_que_llegan_despues(monkeypatch):
    """REGRESIÓN de un fallo real.

    Había un flag `cap200_migrado`. Al arrancar con la biblioteca vacía no
    encontraba nada que reparar y marcaba la migración como terminada PARA
    SIEMPRE. Cuando después llegaban datos afectados —importando una instalación
    antigua, restaurando una copia o sincronizando— la reparación ya no volvía a
    ejecutarse: 180 animes se quedaron mintiendo sobre sus episodios.
    """
    animes = []
    db = _FakeDB(animes)
    _patch(monkeypatch, db, {"anilist": _ScraperOK(1130)})

    # Primer arranque: biblioteca vacía, no hay nada que hacer
    migrations.migrar_cap200(sleep=0)
    assert db.updates == {}

    # Llegan datos afectados (importación de la instalación vieja)
    animes.append({"nombre": "One Piece", "fuente": "anilist", "capitulos": "200"})

    # Segundo arranque: TIENE que repararlos
    migrations.migrar_cap200(sleep=0)
    assert db.updates.get("One Piece", {}).get("capitulos") == "1130", \
        "la migración no volvió a ejecutarse con los datos importados"


def test_cap200_no_destruye_datos_si_fallan_todas_las_fuentes(monkeypatch):
    """Con la red caída, poner '?' en todo borraría episodios correctos.

    Mejor dejarlo como está y reintentar en el próximo arranque.
    """
    animes = [{"nombre": f"A{i}", "fuente": "anilist", "capitulos": "200"}
              for i in range(40)]
    db = _FakeDB(animes)
    _patch(monkeypatch, db, {"anilist": _ScraperFail()})

    resumen = migrations.migrar_cap200(sleep=0)

    assert resumen["abortado"] is True
    # Solo se rindió con unos pocos antes de detectar el patrón; ni de lejos todos.
    assert len(db.updates) < 10, f"marcó {len(db.updates)} como '?' con la red caída"


def test_cap200_un_fallo_aislado_si_pasa_a_interrogante(monkeypatch):
    """Si el resto se resuelve bien, un fallo suelto SÍ es un 200 falso."""
    animes = [{"nombre": f"OK{i}", "fuente": "anilist", "capitulos": "200"}
              for i in range(8)]
    animes.append({"nombre": "Raro", "fuente": "inexistente", "capitulos": "200"})
    db = _FakeDB(animes)

    class SoloConocidos:
        def buscar(self, nombre):
            return _Res(24) if nombre.startswith("OK") else None

    _patch(monkeypatch, db, {"anilist": SoloConocidos()})

    resumen = migrations.migrar_cap200(sleep=0)

    assert resumen["abortado"] is False
    assert db.updates["Raro"]["capitulos"] == "?"
    assert db.updates["OK0"]["capitulos"] == "24"


# ── Refresco automático de series en emisión ─────────────────────────────────

class _ResEstado:
    def __init__(self, caps, estado="En emisión", imagen="http://img"):
        self.capitulos = caps
        self.estado_anime = estado
        self.imagen = imagen
        self.sinopsis = ""
        self.genero = []


class _ScraperEstado:
    def __init__(self, caps, estado="En emisión"):
        self._r = _ResEstado(caps, estado)
    def buscar(self, nombre):
        return self._r


def test_refresco_emision_actualiza_episodios_que_crecen(monkeypatch):
    db = _FakeDB([{"nombre": "Frieren", "fuente": "anilist",
                   "capitulos": "12", "estado_anime": "En emisión", "imagen": "http://img"}])
    monkeypatch.setattr(migrations, "db", db)
    monkeypatch.setattr(migrations, "SCRAPERS", {"anilist": _ScraperEstado(13)})
    n = migrations.refrescar_en_emision(sleep=0)
    assert n == 1
    assert db.updates["Frieren"]["capitulos"] == "13"


def test_refresco_emision_marca_finalizado(monkeypatch):
    db = _FakeDB([{"nombre": "S", "fuente": "anilist",
                   "capitulos": "24", "estado_anime": "En emisión", "imagen": "http://img"}])
    monkeypatch.setattr(migrations, "db", db)
    monkeypatch.setattr(migrations, "SCRAPERS", {"anilist": _ScraperEstado(24, "Finalizado")})
    migrations.refrescar_en_emision(sleep=0)
    assert db.updates["S"]["estado_anime"] == "Finalizado"


def test_refresco_emision_ignora_no_en_emision(monkeypatch):
    db = _FakeDB([{"nombre": "Done", "fuente": "anilist",
                   "capitulos": "24", "estado_anime": "Finalizado", "imagen": "http://img"}])
    monkeypatch.setattr(migrations, "db", db)
    monkeypatch.setattr(migrations, "SCRAPERS", {"anilist": _ScraperEstado(99)})
    n = migrations.refrescar_en_emision(sleep=0)
    assert n == 0 and db.updates == {}
