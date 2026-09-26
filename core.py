"""
core.py — Infraestructura compartida entre main.py y los routers.

Existe para romper el import circular: los routers necesitan el executor y la
versión, pero no pueden importar main.py (que a su vez los importa a ellos).
Mantener esto pequeño y sin lógica de negocio.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

# ÚNICA fuente de verdad de la versión. Llegó a estar declarada en cuatro
# sitios distintos y los cuatro discrepaban: main.py decía 2.8.0, esto 2.7.0,
# el instalador 2.4.0 y el manifest de la PWA 2.7.0. El instalador escribía esa
# versión falsa en el registro de Windows y el cliente móvil la compara para
# decidir si el servidor le vale. Quien necesite la versión la importa de aquí;
# `tests/test_version.py` vigila que nadie vuelva a declararla por su cuenta.
VERSION = "2.10.1"

# Pool compartido para llamadas bloqueantes (scrapers, Sheets, TMDB) sin
# bloquear el event loop de FastAPI.
#
# 12 y no 6: una sola búsqueda lanza las 8 fuentes en paralelo, así que con 6
# hilos dos ya se quedaban en cola. Y cancelar un Future NO detiene el hilo que
# hay debajo: si una web tarda en responder, ese hilo sigue ocupado hasta que
# vence su timeout. Con el pool justo, un par de búsquedas contra una fuente
# lenta lo agotaban y se congelaba la app entera —estadísticas incluidas—,
# porque todo lo bloqueante pasa por aquí. Son hilos esperando red, no CPU.
executor = ThreadPoolExecutor(max_workers=12, thread_name_prefix="miraru")

log = logging.getLogger("miraru")
