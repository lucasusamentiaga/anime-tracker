"""
noticias.py — Agregador de noticias de anime vía RSS.

Sin dependencias nuevas: los feeds son XML y la stdlib ya trae un parser
(xml.etree). feedparser habría añadido peso al .exe para poco más.

La parte pura (parsear XML → lista de dicts) está separada de la de red para
poder testearla sin internet.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Portales en WordPress exponen su feed añadiendo /feed/ a la URL.
FUENTES = [
    {"id": "kudasai",     "nombre": "Kudasai",       "url": "https://somoskudasai.com/feed/"},
    {"id": "crunchyroll", "nombre": "Crunchyroll",   "url": "https://www.crunchyroll.com/news/rss"},
    {"id": "ann",         "nombre": "Anime News Network",
     "url": "https://www.animenewsnetwork.com/all/rss.xml"},
]

_TAGS = re.compile(r"<[^>]+>")


def _limpiar(texto: str, limite: int = 240) -> str:
    """Quita HTML y normaliza espacios de un resumen."""
    if not texto:
        return ""
    txt = html.unescape(_TAGS.sub(" ", texto))
    return re.sub(r"\s+", " ", txt).strip()[:limite]


def _imagen_de_item(item: ET.Element) -> str:
    """La imagen destacada puede venir en varios sitios según el portal."""
    for tag, attr in (
        ("{http://search.yahoo.com/mrss/}content", "url"),
        ("{http://search.yahoo.com/mrss/}thumbnail", "url"),
        ("enclosure", "url"),
    ):
        el = item.find(tag)
        if el is not None and el.get(attr):
            return el.get(attr) or ""
    # Último recurso: primera <img> incrustada en la descripción
    for tag in ("description", "{http://purl.org/rss/1.0/modules/content/}encoded"):
        el = item.find(tag)
        if el is not None and el.text:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', el.text)
            if m:
                return m.group(1)
    return ""


def _fecha_iso(texto: str) -> str:
    """RFC-822 (formato de RSS) → ISO. Cadena vacía si no se puede."""
    if not texto:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(texto.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return ""


def _texto(item: ET.Element, *tags: str) -> str:
    """Primer valor no vacío entre varios tags (RSS y Atom nombran distinto).

    Se define FUERA del bucle a propósito: como función anidada capturaba la
    variable del bucle por referencia, un patrón que rompe en cuanto la llamada
    deja de ser inmediata.
    """
    for t in tags:
        el = item.find(t)
        if el is not None:
            if el.text:
                return el.text
            if el.get("href"):        # Atom: <link href="...">
                return el.get("href") or ""
    return ""


def parsear_feed(xml_text: str, fuente: str = "", limite: int = 12) -> list[dict]:
    """Parsea un RSS/Atom y devuelve noticias normalizadas. Nunca lanza."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out: list[dict] = []
    for item in items[:limite]:
        titulo = _limpiar(_texto(item, "title", "{http://www.w3.org/2005/Atom}title"), 180)
        if not titulo:
            continue
        out.append({
            "titulo":   titulo,
            "link":     _texto(item, "link", "{http://www.w3.org/2005/Atom}link").strip(),
            "resumen":  _limpiar(_texto(item, "description", "{http://www.w3.org/2005/Atom}summary")),
            "imagen":   _imagen_de_item(item),
            "fecha":    _fecha_iso(_texto(item, "pubDate", "{http://www.w3.org/2005/Atom}updated")),
            "fuente":   fuente,
        })
    return out


def ordenar_por_fecha(noticias: list[dict]) -> list[dict]:
    """Más recientes primero; las que no traen fecha van al final."""
    return sorted(noticias, key=lambda n: n.get("fecha") or "", reverse=True)
