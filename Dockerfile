# ── Miraru — imagen Docker para autoalojar (self-hosting) ─────────────────────
# Guía completa: docs/self-host.md
#
# Python 3.13 fijo: FastAPI 0.125 + Pydantic 1.10.x no importan en Python ≥ 3.14.
# La misma razón la da requirements.txt (Pydantic 1 en wheel "py3-none-any").
FROM python:3.13-slim

# ── ENV replicando los nombres que ya usa el código ───────────────────────────
# ANIME_APP_DIR / ANIME_DB_PATH son exactamente los que lee database.py; así la
# BD, los backups automáticos y credentials.json viven todos dentro de /data
# (el volumen persistente). PYTHONDONTWRITEBYTECODE evita .pyc dispersos.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANIME_APP_DIR=/data \
    ANIME_DB_PATH=/data/anime_tracker.db

WORKDIR /app

# ── Usuario no root ───────────────────────────────────────────────────────────
# El contenedor nunca debe escribir tu BD como root: un uid fijo (1000) hace que
# el volumen sea legible también fuera del contenedor si algún día lo necesitas.
RUN addgroup --system --gid 1000 miraru \
    && adduser --system --uid 1000 --ingroup miraru miraru \
    && mkdir -p /data /app \
    && chown -R miraru:miraru /data /app

# ── Dependencias: SOLO requirements.txt ───────────────────────────────────────
# Capa separada para que la caché de Docker no repita pip install si solo cambia
# el código. requirements-dev.txt queda fuera (en .dockerignore): la imagen no
# lleva herramientas de desarrollo ni de test.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ── Código fuente (lo que .dockerignore deja pasar) ───────────────────────────
COPY --chown=miraru:miraru . .

USER miraru

# Puerto por defecto (decorativo): el que manda es -p del docker run
# y ${PORT:-8765} del CMD.
EXPOSE 8765

# Persistencia: la BD, sus backups automáticos y credentials.json van aquí.
VOLUME ["/data"]

# ── CMD propio en vez de `python main.py` ─────────────────────────────────────
# El bloque __main__ de main.py escucha en 127.0.0.1 (localhost de escritorio),
# así que dentro del contenedor nadie podría conectar. No se toca main.py: se
# lanza uvicorn directamente con --host 0.0.0.0 y el puerto en la variable PORT
# (cámbialo con -e PORT=XXXX; por defecto 8765, como ANIME_PORT en main.py).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8765} --log-level warning"]

# ── Healthcheck reutilizando /api/health (endpoint ya existente, solo stdlib) ─
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request, sys; r = urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8765') + '/api/health', timeout=5); sys.exit(0 if r.status == 200 else 1)"
