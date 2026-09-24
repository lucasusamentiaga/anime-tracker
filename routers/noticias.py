"""
routers/noticias.py — Feed agregado de noticias de anime (RSS).

Cachea 1 hora en memoria: las noticias no cambian cada minuto y así no se
castiga a los portales ni se bloquea al usuario.
"""
from __future__ import annotations

import asyncio
import threading
import time

from fastapi import APIRouter

import noticias as parser
from core import executor, log
from scrapers import net

router = APIRouter(prefix="/api/noticias", tags=["noticias"])

_TTL = 3600.0                      # 1 hora
_cache: dict = {"ts": 0.0, "data": None}
_lock = threading.Lock()

_session = net.make_session({"User-Agent": "Miraru/2.7 (+https://github.com/lucasusamentiaga/anime-tracker)"})


def _descargar_todo(limite_por_fuente: int = 8) -> list[dict]:
    """Bloqueante: se ejecuta en el executor. Una fuente caída no tumba al resto."""
    todas: list[dict] = []
    for f in parser.FUENTES:
        try:
            r = _session.get(f["url"], timeout=12)
            if r.status_code != 200:
                continue
            todas.extend(parser.parsear_feed(r.text, f["nombre"], limite_por_fuente))
        except Exception as e:
            log.warning("noticias %s: %s", f["id"], e)
    return parser.ordenar_por_fecha(todas)


@router.get("")
async def listar_noticias(refrescar: bool = False):
    """Últimas noticias de Kudasai, Crunchyroll y Anime News Network."""
    ahora = time.time()
    with _lock:
        vigente = _cache["data"] is not None and (ahora - _cache["ts"]) < _TTL
        if vigente and not refrescar:
            return {"noticias": _cache["data"], "cacheado": True,
                    "fuentes": [f["nombre"] for f in parser.FUENTES]}

    loop = asyncio.get_running_loop()
    datos = await loop.run_in_executor(executor, _descargar_todo)

    with _lock:
        # Si todas las fuentes fallaron, conservamos lo último bueno que hubiera
        if datos or _cache["data"] is None:
            _cache["data"] = datos
            _cache["ts"] = ahora
        salida = _cache["data"]

    return {"noticias": salida, "cacheado": False,
            "fuentes": [f["nombre"] for f in parser.FUENTES]}
