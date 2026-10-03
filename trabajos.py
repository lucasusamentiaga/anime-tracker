"""Trabajos largos en segundo plano con progreso (v2.12).

Importar de AniList o de AnimeAV1, subir la lista entera o resolver IDs tarda
minutos (los servicios limitan las peticiones por minuto). Antes la petición
HTTP se quedaba colgada todo ese rato y la interfaz solo decía "Importando…",
sin saber si iba por el 5 % o por el 95 %. Ahora el trabajo corre en un hilo,
cuenta lo que lleva hecho y la página lo consulta para pintar una barra.

Uso:
    tid = trabajos.lanzar("anilist-pull", funcion)   # funcion(progreso) -> dict
    trabajos.estado(tid)  # {"estado": "en_curso"|"terminado"|"error"|"cancelado", ...}
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Optional

log = logging.getLogger("miraru.trabajos")

_trabajos: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_GUARDADOS = 30


class Cancelado(Exception):
    """La persona pulsó «Cancelar»: el trabajo se para en el siguiente paso."""


class Progreso:
    """Lo que recibe la función del trabajo para ir contando."""

    def __init__(self, tid: Optional[str] = None):
        self.tid = tid

    def _set(self, **campos):
        if not self.tid:
            return
        with _lock:
            t = _trabajos.get(self.tid)
            if t is not None:
                t.update(campos)
                t["actualizado"] = time.time()

    def _get(self, campo, defecto=None):
        if not self.tid:
            return defecto
        with _lock:
            return (_trabajos.get(self.tid) or {}).get(campo, defecto)

    def total(self, n: int):
        self._set(total=max(0, int(n)))

    def sumar_total(self, n: int):
        self._set(total=max(0, int(self._get("total", 0) or 0) + int(n)))

    def avanzar(self, n: int = 1, detalle: str = ""):
        if self.cancelado():
            raise Cancelado()
        hechos = int(self._get("hechos", 0) or 0) + n
        campos = {"hechos": hechos}
        if detalle:
            campos["detalle"] = detalle[:160]
        self._set(**campos)

    def detalle(self, texto: str):
        self._set(detalle=(texto or "")[:160])

    def cancelado(self) -> bool:
        return bool(self._get("cancelar", False))


# Progreso que no cuenta nada: lo usan las llamadas antiguas (sin barra).
NULO = Progreso(None)


def _limpiar_viejos():
    terminados = [(t["actualizado"], k) for k, t in _trabajos.items()
                  if t["estado"] != "en_curso"]
    if len(_trabajos) <= _MAX_GUARDADOS:
        return
    for _, k in sorted(terminados)[: len(_trabajos) - _MAX_GUARDADOS]:
        _trabajos.pop(k, None)


def en_curso(tipo: str) -> Optional[str]:
    with _lock:
        for k, t in _trabajos.items():
            if t["tipo"] == tipo and t["estado"] == "en_curso":
                return k
    return None


def lanzar(tipo: str, funcion: Callable[[Progreso], dict]) -> str:
    """Arranca `funcion(progreso)` en un hilo. Si ya hay uno del mismo tipo en
    marcha devuelve ese (pulsar dos veces no lanza dos importaciones)."""
    ya = en_curso(tipo)
    if ya:
        return ya
    tid = uuid.uuid4().hex[:12]
    with _lock:
        _limpiar_viejos()
        _trabajos[tid] = {"id": tid, "tipo": tipo, "estado": "en_curso",
                          "total": 0, "hechos": 0, "detalle": "",
                          "resultado": None, "error": "", "cancelar": False,
                          "inicio": time.time(), "actualizado": time.time()}
    progreso = Progreso(tid)

    def _correr():
        try:
            resultado = funcion(progreso)
            progreso._set(estado="terminado", resultado=resultado)
        except Cancelado:
            progreso._set(estado="cancelado")
        except Exception as e:  # noqa: BLE001 — se informa a la interfaz
            log.exception("Trabajo %s (%s) falló", tid, tipo)
            progreso._set(estado="error", error=str(e)[:300])

    threading.Thread(target=_correr, name=f"trabajo-{tipo}", daemon=True).start()
    return tid


def estado(tid: str) -> Optional[dict]:
    with _lock:
        t = _trabajos.get(tid)
        if t is None:
            return None
        datos = {k: v for k, v in t.items() if k != "cancelar"}
    total = datos.get("total") or 0
    datos["porcentaje"] = (100 if datos["estado"] == "terminado"
                           else int(min(100, datos["hechos"] * 100 / total)) if total else 0)
    return datos


def cancelar(tid: str) -> bool:
    with _lock:
        t = _trabajos.get(tid)
        if t is None or t["estado"] != "en_curso":
            return False
        t["cancelar"] = True
        return True
