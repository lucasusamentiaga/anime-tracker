"""
scrapers/net.py — Sesiones HTTP con reintentos automáticos.

Un timeout puntual o un 503 de AniList/Jikan arruinaba una importación masiva
entera. Aquí se centraliza una `requests.Session` con reintentos y backoff
exponencial para todos los scrapers.

Por qué urllib3.Retry y no tenacity: `requests` ya lo trae, así que no añade
dependencias nuevas (importante para el tamaño del .exe y los hidden-imports de
PyInstaller), y actúa a nivel de transporte, cubriendo por igual a todos.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter

try:                                    # urllib3 v2 y v1 mueven Retry de sitio
    from urllib3.util.retry import Retry
except ImportError:                     # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

# 429 = rate limit (Jikan lo usa mucho), 5xx = caídas temporales.
_STATUS_REINTENTABLES = (429, 500, 502, 503, 504)


def build_retry(total: int = 3, backoff: float = 0.6) -> Retry:
    """backoff 0.6 → esperas de ~0.6s, 1.2s, 2.4s entre intentos."""
    kwargs = {
        "total": total,
        "connect": total,
        "read": total,
        "status": total,
        "backoff_factor": backoff,
        "status_forcelist": _STATUS_REINTENTABLES,
        "raise_on_status": False,
    }
    # `allowed_methods` se llamaba `method_whitelist` en urllib3 < 1.26
    try:
        return Retry(allowed_methods=frozenset(["GET", "POST"]), **kwargs)
    except TypeError:                   # pragma: no cover
        return Retry(method_whitelist=frozenset(["GET", "POST"]), **kwargs)


def make_session(headers: dict | None = None,
                 total: int = 3,
                 backoff: float = 0.6) -> requests.Session:
    """Session con connection pooling + reintentos. Sustituye a requests.Session()."""
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=build_retry(total, backoff),
                          pool_connections=8, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    if headers:
        s.headers.update(headers)
    return s
