"""
Tests del arranque directo (`python main.py`).

El README documenta `python main.py` como la forma de ejecutar el servidor a
mano, y es también el camino del doble clic en desarrollo. Desde la extracción
de rutas a `routes/`, ese camino era distinto de los demás: `uvicorn main:app`
(Docker) y `launcher.py` cargan el módulo ANTES bajo el nombre "main", pero
`python main.py` lo registra como `__main__`. Sin costura, el primer
`import main` dentro de routes/ re-ejecutaba main.py completo con el paquete
routes a medio inicializar → ImportError circular y el servidor nunca llegaba
a abrir puerto.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import pytest

REPOSITORIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor_directo():
    """Arranca `python main.py` tal cual (como __main__) y devuelve el puerto.

    Se mata al terminar: un servidor vivo colgaría toda la suite."""
    puerto = _puerto_libre()
    tmp = tempfile.mkdtemp(prefix="miraru_arranque_")
    env = {
        **os.environ,
        "ANIME_APP_DIR": tmp,
        "ANIME_DB_PATH": os.path.join(tmp, "arranque.db"),
        "ANIME_PORT": str(puerto),
    }
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPOSITORIO, "main.py")],
        cwd=REPOSITORIO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        ultimo_error = b""
        listo = False
        for _ in range(60):
            time.sleep(0.25)
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{puerto}/api/health", timeout=2
                ).close()
                listo = True
                break
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                ultimo_error = str(e).encode()
                if proc.poll() is not None:
                    break
        if not listo:
            cola = proc.communicate(timeout=5)[1] or ultimo_error
            pytest.fail(
                "python main.py no llegó a abrir puerto:\n"
                + cola.decode(errors="replace")[-2000:]
            )
        yield puerto
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_python_main_py_arranca_y_responde(servidor_directo):
    """Regresión del ImportError circular: el arranque directo abre puerto y
    el healthcheck responde 200."""
    with urllib.request.urlopen(
        f"http://127.0.0.1:{servidor_directo}/api/health", timeout=5
    ) as r:
        assert r.status == 200
        cuerpo = r.read().decode()
        assert '"ok":true' in cuerpo
