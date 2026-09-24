"""
La búsqueda multi-fuente tiene que rendirse.

`_buscar_con_fallback` esperaba con `asyncio.wait(...)` SIN timeout a que las 8
fuentes contestaran. Cada scraper lleva su propio timeout, pero si una web
responde lentísimo (o los reintentos con backoff se encadenan), "Añadir anime"
se quedaba girando sin final y sin más salida que recargar la página.

Aquí se fija que el conjunto tiene un plazo y que, agotado, devuelve "no
encontrado" en vez de colgarse.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time

import pytest

_TMP = tempfile.mkdtemp(prefix="miraru_timeout_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "t.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

import main  # noqa: E402

# Los hilos del ThreadPoolExecutor no son demonio: Python espera a que terminen
# al salir. Una espera larga aquí no solo alarga el test, sino que deja pytest
# colgado al final. 3 s bastan para demostrar que el plazo corta antes.
_ESPERA_FUENTE_LENTA = 3


class FuenteColgada:
    """Un scraper que no contesta a tiempo (la web caída del mundo real)."""

    def buscar(self, nombre):
        time.sleep(_ESPERA_FUENTE_LENTA)
        return None


class FuenteRapida:
    def __init__(self, resultado=None):
        self.resultado = resultado

    def buscar(self, nombre):
        return self.resultado


def ficha(nombre: str, fuente: str) -> main.AnimeData:
    """AnimeData mínimo válido (todos los campos son obligatorios)."""
    return main.AnimeData(
        nombre=nombre,
        capitulos=12,
        imagen="https://ejemplo/portada.jpg",
        genero=["Action"],
        sinopsis="…",
        fuente=fuente,
        estado_anime="Finalizado",
    )


@pytest.fixture
def scrapers_falsos(monkeypatch):
    """Sustituye el registro de scrapers; ninguno toca la red."""
    def poner(mapa):
        monkeypatch.setattr(main, "SCRAPERS", mapa)
    return poner


def test_se_rinde_si_ninguna_fuente_contesta(scrapers_falsos, monkeypatch):
    monkeypatch.setattr(main, "_TIMEOUT_BUSQUEDA_TOTAL", 0.4)
    scrapers_falsos({"a": FuenteColgada(), "b": FuenteColgada(), "c": FuenteColgada()})

    t0 = time.time()
    resultado, _fuente = asyncio.run(main._buscar_con_fallback("loquesea", "a"))
    transcurrido = time.time() - t0

    assert resultado is None
    # Sin el plazo se esperaría a las fuentes colgadas enteras.
    assert transcurrido < _ESPERA_FUENTE_LENTA, \
        f"tardó {transcurrido:.1f}s; el plazo no se aplicó"


def test_una_fuente_rapida_gana_sin_esperar_a_las_lentas(scrapers_falsos, monkeypatch):
    """Lo importante del diseño en paralelo: no se paga por la más lenta."""
    resultado_esperado = ficha("Cowboy Bebop", "rapida")
    monkeypatch.setattr(main, "_TIMEOUT_BUSQUEDA_TOTAL", 10)
    monkeypatch.setattr(main, "_rellenar_huecos",
                        _devolver_tal_cual)
    scrapers_falsos({
        "pref":   FuenteRapida(None),      # la preferida no lo tiene
        "lenta":  FuenteColgada(),
        "rapida": FuenteRapida(resultado_esperado),
    })

    t0 = time.time()
    resultado, fuente = asyncio.run(main._buscar_con_fallback("Cowboy Bebop", "pref"))
    transcurrido = time.time() - t0

    assert resultado is not None
    assert fuente == "rapida"
    assert transcurrido < _ESPERA_FUENTE_LENTA, \
        f"esperó a la fuente lenta ({transcurrido:.1f}s)"


async def _devolver_tal_cual(resultado, nombre, fuente):
    return resultado


def test_una_fuente_preferida_rota_no_tumba_la_busqueda(scrapers_falsos, monkeypatch):
    """La preferida se esperaba sin try: si lanzaba, la excepción subía hasta el
    endpoint y el usuario recibía un 500 en lugar del resultado de otra fuente."""
    resultado_esperado = ficha("Monster", "otra")
    monkeypatch.setattr(main, "_rellenar_huecos", _devolver_tal_cual)

    class FuenteRota:
        def buscar(self, nombre):
            raise RuntimeError("la web cambió el HTML")

    scrapers_falsos({"pref": FuenteRota(), "otra": FuenteRapida(resultado_esperado)})

    resultado, fuente = asyncio.run(main._buscar_con_fallback("Monster", "pref"))

    assert resultado is not None, "una fuente rota dejó la búsqueda sin resultado"
    assert fuente == "otra"


def test_una_fuente_preferida_colgada_no_bloquea_a_las_demas(scrapers_falsos, monkeypatch):
    """Antes la preferida se esperaba SIN plazo, así que colgaba toda la búsqueda."""
    resultado_esperado = ficha("Vinland Saga", "otra")
    monkeypatch.setattr(main, "_TIMEOUT_BUSQUEDA_TOTAL", 0.4)
    monkeypatch.setattr(main, "_rellenar_huecos", _devolver_tal_cual)
    scrapers_falsos({"pref": FuenteColgada(), "otra": FuenteRapida(resultado_esperado)})

    t0 = time.time()
    resultado, fuente = asyncio.run(main._buscar_con_fallback("Vinland Saga", "pref"))
    transcurrido = time.time() - t0

    assert transcurrido < _ESPERA_FUENTE_LENTA, \
        f"la fuente preferida colgada bloqueó {transcurrido:.1f}s"
    # Con un plazo tan corto puede no dar tiempo a la otra; lo que importa es
    # que vuelva pronto en vez de quedarse esperando.
    assert resultado is None or fuente == "otra"


def test_la_fuente_preferida_corta_por_lo_sano(scrapers_falsos, monkeypatch):
    """Si la preferida responde, no se consulta a nadie más."""
    resultado_esperado = ficha("Steins;Gate", "pref")
    monkeypatch.setattr(main, "_rellenar_huecos", _devolver_tal_cual)
    llamadas = []

    class Espia:
        def buscar(self, nombre):
            llamadas.append("otra")
            return None

    scrapers_falsos({"pref": FuenteRapida(resultado_esperado), "otra": Espia()})

    resultado, fuente = asyncio.run(main._buscar_con_fallback("Steins;Gate", "pref"))

    assert fuente == "pref"
    assert resultado.nombre == "Steins;Gate"
    assert llamadas == [], "se consultaron otras fuentes sin necesidad"
