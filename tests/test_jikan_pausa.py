"""v2.16.3: si Jikan no responde, se deja de llamar un rato."""
import requests

from scrapers import jikan


def test_tras_un_fallo_de_conexion_jikan_se_pausa(monkeypatch):
    llamadas = []

    def falla(*a, **k):
        llamadas.append(1)
        raise requests.ConnectTimeout("bloqueado")

    monkeypatch.setattr(jikan, "_caida_hasta", 0.0)
    monkeypatch.setattr(jikan._session, "get", falla)
    s = jikan.JikanV4Scraper()
    assert s.buscar_mal_id("Isekai Ojisan") == 0
    assert jikan.caida()
    assert s.buscar_mal_id("Gotoubun no Hanayome") == 0 and s.buscar("x") is None
    assert len(llamadas) == 1
