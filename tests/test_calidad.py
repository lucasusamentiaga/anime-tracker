"""
Tests de la capa de calidad de scrapers.

Regresión del patrón real: un scraper HTML roto devuelve una ficha con nombre
pero sin datos, y la búsqueda la daba por buena.
"""
from __future__ import annotations

from scrapers import calidad
from scrapers.base import AnimeData


def _ficha(**kw):
    base = {"nombre": "X", "capitulos": "?", "imagen": "", "genero": [],
            "sinopsis": "", "fuente": "animeflv", "estado_anime": ""}
    base.update(kw)
    return AnimeData(**base)


# ── Detección ─────────────────────────────────────────────────────────────────

def test_ficha_hueca_de_scraper_roto_se_detecta():
    """Exactamente lo que devuelve animeflv cuando el sitio cambia el CSS."""
    assert calidad.esta_incompleto(_ficha()) is True
    assert calidad.puntuar(_ficha()) == 0


def test_ficha_completa_no_se_marca():
    buena = _ficha(capitulos=220, imagen="http://i", sinopsis="Ninja", genero=["Acción"])
    assert calidad.esta_incompleto(buena) is False
    assert calidad.puntuar(buena) == 4


def test_dos_campos_bastan():
    """No exigimos perfección: con episodios e imagen ya es aprovechable."""
    media = _ficha(capitulos=12, imagen="http://i")
    assert calidad.esta_incompleto(media) is False


def test_un_solo_campo_no_basta():
    assert calidad.esta_incompleto(_ficha(imagen="http://i")) is True


def test_interrogante_cuenta_como_vacio():
    """'?' es el 'no lo sé' de los scrapers, no un dato."""
    assert calidad.puntuar(_ficha(capitulos="?")) == 0


def test_none_puntua_negativo():
    assert calidad.puntuar(None) == -1


# ── Fusión ────────────────────────────────────────────────────────────────────

def test_rellena_huecos_sin_pisar_lo_bueno():
    base = _ficha(capitulos=24)                       # esto lo acertó animeflv
    relleno = _ficha(nombre="Otro", fuente="anilist", capitulos=999,
                     imagen="http://cover", sinopsis="Resumen", genero=["Acción"])
    out = calidad.fusionar(base, relleno)
    assert out.capitulos == 24            # NO lo pisa
    assert out.imagen == "http://cover"   # sí rellena el hueco
    assert out.sinopsis == "Resumen"
    assert out.genero == ["Acción"]


def test_conserva_nombre_y_fuente_originales():
    base = _ficha(nombre="Naruto", fuente="animeflv")
    relleno = _ficha(nombre="NARUTO (2002)", fuente="anilist", imagen="http://i")
    out = calidad.fusionar(base, relleno)
    assert out.nombre == "Naruto" and out.fuente == "animeflv"


def test_fusionar_tolera_none():
    b = _ficha(capitulos=12)
    assert calidad.fusionar(None, b) is b
    assert calidad.fusionar(b, None) is b
    assert calidad.fusionar(None, None) is None


def test_ficha_hueca_queda_completa_tras_fusionar():
    """El caso que motiva todo esto: scraper roto + respaldo = ficha usable."""
    rota = _ficha()
    buena = _ficha(fuente="anilist", capitulos=220, imagen="http://i",
                   sinopsis="Ninja", genero=["Acción"], estado_anime="Finalizado")
    out = calidad.fusionar(rota, buena)
    assert calidad.esta_incompleto(out) is False
    assert out.fuente == "animeflv"       # la atribución no cambia
    assert out.estado_anime == "Finalizado"
