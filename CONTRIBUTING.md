# Contributing to Miraru / Contribuir a Miraru

Thanks for your interest in contributing! / ¡Gracias por tu interés en colaborar!

- English guide below, [guía en español aquí](#gu%C3%ADa-en-espa%C3%B1ol).
- Guía en español abajo, [English guide here](#contributing-to-miraru-english).

---

## Contributing to Miraru (English)

### Development setup

Requirements: Python 3.13 (a 3.10+ runtime works, but the toolchain below pins 3.13.11) and [mise](https://mise.jdx.dev/).

```bash
mise use python@3.13.11          # pin the interpreter (mise.toml already declares it)
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements-dev.txt                 # runtime deps + pytest, ruff, httpx, pyinstaller
```

### Run the app

```bash
python launcher.py
```

The desktop app opens in your browser. `main.py` is the FastAPI entry point used under the hood — the API handlers live in `routes/` (app wiring, middleware and page routes stay in `main.py`) — and `launcher.py` is the recommended entry for development.

### Run the tests

```bash
python -m pytest tests/ -q
```

All tests must pass before a PR. They cover the API (via httpx), scrapers, migrations, sync and the mobile bindings.

### Lint

```bash
python -m ruff check .
```

Ruff is configured in `pyproject.toml` with **line length 110** and a pragmatic rule set (`E F W I UP B C4 SIM`). Run it clean before opening a PR — no new ignores without justification in the PR description.

### Code conventions

1. **Comments in Spanish.** All code comments and docstrings in this codebase are written in Spanish. Keep new comments in Spanish, matching tone and style (see example below).
2. **Line length 110**, enforced by Ruff (`pyproject.toml`).
3. **Pydantic 1 shim pattern.** The project pins `pydantic==1.10.26` (pure-python wheel). Never import Pydantic v2 APIs (`field_validator`, `model_validator`, `ConfigDict`…). Use the existing try/except shim pattern instead:

```python
try:
    from pydantic import field_validator
except ImportError:  # Pydantic 1 (Python puro): el que usa install.ps1
    from pydantic import validator as _validator
```

   If validation logic is needed, follow the compat pattern used in `main.py` (v1/v2 guarded at import time).
4. **No new runtime dependencies without justification.** Every dependency bloats the PyInstaller bundle and triggers Windows Smart App Control friction, because the distributed binaries are **unsigned** (no DLL-signing budget for a hobby project). If a dependency is truly needed: add it to `requirements.txt` with a comment explaining why, and make sure a test proves it.
5. **Configuration over code.** Ruff config lives in `pyproject.toml`; test discovery excludes `venv/`, `dist/`, `mobile-expo/`, etc. Don't add per-file workarounds when a config change is more appropriate.

### Pull request checklist

- [ ] `python -m pytest tests/ -q` passes (full suite, not just affected tests)
- [ ] `python -m ruff check .` is clean
- [ ] New code comments are in Spanish
- [ ] No new runtime dependency, **or** the PR justifies it (PyInstaller size + unsigned-binary constraint)
- [ ] No Pydantic v2 API imports
- [ ] `CHANGELOG.md` updated when user-facing behavior changes
- [ ] Screenshots attached for UI changes

### License

By contributing you agree that your contributions are licensed under the **MIT License** — see [LICENSE](LICENSE).

---

## Guía en español

### Setup de desarrollo

Requisitos: Python 3.13 (funciona cualquier 3.10+, pero la toolchain fija 3.13.11) y [mise](https://mise.jdx.dev/).

```bash
mise use python@3.13.11          # fija el intérprete (mise.toml ya lo declara)
python -m venv .venv && source .venv/bin/activate   # opcional pero recomendado
pip install -r requirements-dev.txt                 # deps de runtime + pytest, ruff, httpx, pyinstaller
```

### Arrancar la app

```bash
python launcher.py
```

La app de escritorio abre en el navegador. `main.py` es el punto de entrada FastAPI por debajo —los handlers del API viven en `routes/` (el cableado de la app, el middleware y las rutas de página se quedan en `main.py`)—; `launcher.py` es la entrada recomendada para desarrollar.

### Ejecutar los tests

```bash
python -m pytest tests/ -q
```

Todos los tests deben pasar antes de abrir un PR. Cubren la API (vía httpx), scrapers, migraciones, sincronización y los bindings del móvil.

### Lint

```bash
python -m ruff check .
```

Ruff está configurado en `pyproject.toml` con **longitud de línea 110** y un conjunto de reglas pragmático (`E F W I UP B C4 SIM`). Debe salir limpio antes del PR — no ignores reglas nuevas sin justificarlo en la descripción.

### Convenciones de código

1. **Comentarios en español.** Todos los comentarios y docstrings del proyecto están en español. Los comentarios nuevos, también, siguiendo el tono del resto:

```python
# Compatibilidad Pydantic v1 y v2
try:
    from pydantic import field_validator
except ImportError:  # Pydantic 1 (Python puro): el que usa install.ps1, sin DLL que firmar
    from pydantic import validator as _validator
```

2. **Longitud de línea 110**, la aplica Ruff (`pyproject.toml`).
3. **Patrón shim de Pydantic 1.** El proyecto fija `pydantic==1.10.26` (wheel en Python puro). Nunca importes APIs de Pydantic v2 (`field_validator`, `model_validator`, `ConfigDict`…). Usa el patrón try/except existente (ver ejemplo arriba y `main.py`, donde la compatibilidad se resuelve en el import).
4. **Sin dependencias nuevas de runtime sin justificar.** Cada dependencia agranda el bundle de PyInstaller y aumenta la fricción de Windows Smart App Control, porque los binarios distribuidos van **sin firmar** (sin presupuesto de firma de DLLs en un proyecto de hobby). Si de verdad hace falta: añádela a `requirements.txt` con un comentario que explique por qué y asegúrate de que un test la cubre.
5. **Configuración antes que código.** La config de Ruff vive en `pyproject.toml`; la búsqueda de tests excluye `venv/`, `dist/`, `mobile-expo/`, etc. Si un cambio de configuración lo resuelve, no añadas parches por archivo.

### Checklist de PR

- [ ] Pasa `python -m pytest tests/ -q` (la suite completa, no solo los tests afectados)
- [ ] `python -m ruff check .` sale limpio
- [ ] Los comentarios nuevos están en español
- [ ] Sin dependencias nuevas de runtime, **o** el PR lo justifica (tamaño del PyInstaller + binarios sin firmar)
- [ ] Sin imports de APIs de Pydantic v2
- [ ] `CHANGELOG.md` actualizado si cambia el comportamiento visible para el usuario
- [ ] Capturas adjuntas si hay cambios de interfaz

### Licencia

Al contribuir aceptas que tus aportaciones se publiquen bajo la **licencia MIT** — ver [LICENSE](LICENSE).
