# Cómo contribuir a Miraru

¡Gracias por querer ayudar! Miraru es una app pequeña mantenida por una sola persona, así que
lo que más ayuda son los cambios **pequeños, probados y con una explicación clara**.

*English: issues and pull requests in English are welcome too.*

## Antes de empezar

- Para algo más grande que un arreglo, abre antes un **issue** contando la idea. Así no
  trabajas en algo que luego no encaja.
- Los fallos se reportan con: qué hiciste, qué esperabas, qué pasó y tu versión de Miraru
  (abajo a la izquierda en la app).

## Preparar el entorno

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/lucasusamentiaga/anime-tracker.git
cd anime-tracker
pip install -r requirements-dev.txt
python main.py            # http://127.0.0.1:8765
```

## Antes de abrir el pull request

```bash
python -m pytest tests/ -q
ruff check .
```

El CI (GitHub Actions) pasa además estas comprobaciones; si alguna falla, el PR no se puede unir:

| Comprobación | Qué significa para ti |
|---|---|
| `onclick` definidos | Todo `onclick=""` / `onchange=""` de las plantillas llama a una **función** definida (nada de código suelto dentro del atributo). |
| Rutas duplicadas | No declares dos veces la misma ruta de FastAPI. |
| `.bat` en ASCII | Los `.bat` sin tildes ni `chcp` (cmd.exe los rompe). |
| Instalación en Windows | `install.ps1` tiene que seguir funcionando en modo de lenguaje restringido. |

## Reglas del proyecto

- **Los tests nunca tocan la base de datos real** ni la red: usa las *fixtures* `db` y
  `app_dir` de `tests/conftest.py` y simula las peticiones HTTP con `unittest.mock`.
- **Textos de la interfaz**: se escriben en español en las plantillas y su traducción va en
  `i18n_ui.py` (inglés, francés y alemán). Los nombres de anime no se traducen
  (`data-no-i18n`).
- **Nada de contenido para adultos**: cualquier fuente nueva de fichas tiene que pasar por
  `scrapers/adulto.py` (la clasificación por edades de la Microsoft Store depende de ello).
- **Versión**: solo se declara en `core.py` (`VERSION`). Al publicar, sube también
  `static/manifest.json` y `CACHE_NAME` en `static/sw.js`.
- Código y comentarios en español, como el resto del proyecto. Mensajes de commit al estilo
  `fix: …`, `feat: …`, `docs: …`, `test: …`.

## Dónde está cada cosa

| Carpeta / archivo | Contenido |
|---|---|
| `main.py` | Servidor FastAPI y la mayoría de endpoints |
| `routers/` | Endpoints separados por tema (pelis y series, logros, noticias, push, openings) |
| `database.py` | SQLite: tablas, consultas y caché de la biblioteca |
| `scrapers/` | Búsqueda en AniList, MAL/Jikan, Kitsu, AnimeFLV, AnimeAV1… |
| `templates/` | Páginas HTML (Jinja2) |
| `static/` | CSS, JS, iconos y service worker |
| `tests/` | Tests con pytest |

## Licencia

Al contribuir aceptas que tu código se publique bajo la [licencia MIT](LICENSE) del proyecto.
