"""Tests del agregador RSS (módulo puro: no toca la red)."""
from __future__ import annotations

import noticias

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Kudasai</title>
    <item>
      <title>Nuevo anime de &amp;quot;Frieren&amp;quot; anunciado</title>
      <link>https://ejemplo.test/noticia-1</link>
      <description><![CDATA[<p>Un <b>resumen</b> con etiquetas.</p>]]></description>
      <pubDate>Tue, 25 Aug 2026 10:30:00 +0000</pubDate>
      <media:content url="https://ejemplo.test/img1.jpg"/>
    </item>
    <item>
      <title>Segunda noticia</title>
      <link>https://ejemplo.test/noticia-2</link>
      <description>Sin imagen propia &lt;img src="https://ejemplo.test/img2.jpg"&gt; incrustada</description>
      <pubDate>Mon, 24 Aug 2026 09:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


def test_parsea_titulo_link_y_fecha():
    out = noticias.parsear_feed(RSS, fuente="Kudasai")
    assert len(out) == 2
    n = out[0]
    assert "Frieren" in n["titulo"]
    assert n["link"] == "https://ejemplo.test/noticia-1"
    assert n["fuente"] == "Kudasai"
    assert n["fecha"].startswith("2026-08-25")


def test_limpia_html_del_resumen():
    out = noticias.parsear_feed(RSS)
    assert "<b>" not in out[0]["resumen"]
    assert "resumen" in out[0]["resumen"]


def test_extrae_imagen_de_media_content_y_de_img_incrustada():
    out = noticias.parsear_feed(RSS)
    assert out[0]["imagen"] == "https://ejemplo.test/img1.jpg"
    assert out[1]["imagen"] == "https://ejemplo.test/img2.jpg"


def test_xml_invalido_no_lanza():
    assert noticias.parsear_feed("esto no es xml") == []
    assert noticias.parsear_feed("") == []


def test_respeta_el_limite():
    assert len(noticias.parsear_feed(RSS, limite=1)) == 1


def test_ordena_por_fecha_desc_y_sin_fecha_al_final():
    datos = [
        {"titulo": "vieja",  "fecha": "2026-01-01T00:00:00+00:00"},
        {"titulo": "nueva",  "fecha": "2026-08-01T00:00:00+00:00"},
        {"titulo": "sin",    "fecha": ""},
    ]
    orden = [n["titulo"] for n in noticias.ordenar_por_fecha(datos)]
    assert orden == ["nueva", "vieja", "sin"]
