---
name: miraru-log
description: "Registro completo del proyecto Miraru (app de seguimiento de anime, FastAPI + SQLite + HTML/JS). Úsalo siempre que trabajes en Miraru: añadir features, arreglar bugs, tocar la base de datos, modificar el arranque, cambiar templates, escribir tests o tomar cualquier decisión de arquitectura. Contiene el historial de bugs arreglados, reglas del proyecto, arquitectura clave y pendientes conocidos."
---

# Miraru — Registro de desarrollo del proyecto

Este documento es el historial completo de decisiones, bugs arreglados, mejoras aplicadas y patrones establecidos en el desarrollo de **Miraru** (app de seguimiento de anime, FastAPI + SQLite + HTML/CSS/JS sin frameworks).

---

## Identidad del proyecto

- **Nombre**: Miraru
- **Versión actual**: 2.9.1
- **Stack**: Python 3.13, FastAPI, uvicorn, SQLite (WAL), HTML/CSS/JS vanilla
- **Puerto**: `127.0.0.1:8765`
- **Carpeta**: `C:\Users\lukit\Desktop\Claude Code\Anime Tracker\anime-tracker`
- **Arranque**: `Miraru.vbs` → `launcher.py` → `main.py`
- **Fuentes de datos**: AniList (principal), Jikan v4 / MAL, Kitsu (JSON:API), AnimeFLV (scraper)
- **Base de datos**: `anime_tracker.db` (SQLite WAL, ~336 animes importados de instalación anterior)
- **Service Worker**: `miraru-v26` — incrementar al desplegar cambios en templates/assets

---

## Reglas de trabajo (no negociables)

1. **Nunca crear archivos en el escritorio** — todo va en la carpeta del proyecto.
2. **VERSION en un único lugar**: `core.py`. `main.py` hace `from core import VERSION`. `build.py` lee `core.py` con regex.
3. **Un solo `ThreadPoolExecutor`**: en `core.py`, `executor = ThreadPoolExecutor(max_workers=12)`. `main.py` hace `from core import executor`.
4. **Archivos temporales de diagnóstico** (como `_inspeccion.py`) deben borrarse tras su uso.

---

## Arquitectura clave

### Arranque (doble clic)
```
Miraru.vbs (busca Python, instala deps si faltan, todo sin ventana)
  → launcher.py (inicia uvicorn en hilo daemon, abre navegador)
    → main.py (FastAPI app, _lifespan con startup/shutdown)
```
- Lanzador único: `Miraru.vbs` hace todo (buscar Python en venv/py/PATH/rutas conocidas, instalar deps, arrancar). No hay .bat.
- Si algo falla, muestra un MsgBox con el error y guarda detalle en `arranque.log`
- `launcher.py` abre el navegador automáticamente cuando el puerto está listo
- Si uvicorn falla, `_server_failed` event muestra un diálogo de error con tkinter
- Race condition corregida: el loop de espera comprueba `_server_failed` cada 300ms en lugar de esperar 40s en silencio

### Base de datos (`database.py`)
- **`get_conn()`** es un `@contextmanager` — cierra la conexión siempre en el `finally`. Antes usaba `with sqlite3.Connection` que solo gestiona transacciones, NO cierra. 32 usos × muchas peticiones = cientos de file descriptors abiertos (bug crítico).
- WAL activado en `init_db()` con `PRAGMA journal_mode=WAL`
- **Backup seguro**: usa `sqlite3.Connection.backup()` en lugar de `zipfile.write(db_path)`. El método directo copia el `.db` sin el contenido del `.wal`, perdiendo potencialmente horas de cambios.
- **Tablas**: `animes` (con columnas `tipo`, `volumenes_leidos`, `anilist_id`), `config`, `historial`, `ep_log`, `episode_notes`, `media`
- **`episode_notes`**: tabla para notas por episodio (nombre, episodio, nota, fecha). UPSERT con `ON CONFLICT(nombre, episodio)`.

### Backups (`main.py`)
- **Regla de oro**: SIEMPRE usar `sqlite3.Connection.backup()`, nunca `zipfile.write(db_path)`. Aplica tanto a `/api/backup` como a `_crear_backup_disco()`.
- `_crear_backup_disco()`: auto-backup cada 24h. Lee `ANIME_APP_DIR` en runtime (igual que el endpoint) — no usar `APP_DIR` hardcoded.
- `/api/backup`: backup manual. Retención automática de 10 backups.
- `_crear_backup_disco`: retención configurable (por defecto 7 backups).
- `/api/backups` (listar): también lee `ANIME_APP_DIR` en runtime.

### Migraciones (`migrations.py`)
- **`Cortocircuito`**: circuit breaker para fuentes de scraping. Tras N fallos seguidos (umbral=3), esa fuente se aparta. Un acierto reinicia el contador. Evita que AniList en 403 bloquee la migración 8 reintentos × 200 animes.
- **`migrar_cap200()`**: repara animes con `capitulos='200'` heredados del bug de la v<2.6.2. Sin flag de "ya migrado" — la propia query es la condición de parada. El flag anterior causó que 180 animes quedaran eternamente en 200 ep tras una importación.
- **`refrescar_en_emision()`**: actualiza episodios/estado de series en emisión cada 12h.

### Puntuaciones externas (`main.py`)
- **`/api/animes/{nombre}/scores`**: consulta AniList, MAL (Jikan v4), y Kitsu en paralelo. Devuelve scores normalizados a 0-10.
  - AniList: `averageScore` 0-100 → ÷ 10
  - MAL/Jikan: `score` ya en 1-10
  - Kitsu: `averageRating` string "83.41" → float ÷ 10
  - Cada fuente con try/except independiente para que una falle sin romper las otras.
  - Cacheado 30 min (`scores:{titulo}`).
  - Incluye la puntuación del usuario si la tiene.
- **`_fetch_score_anilist()`**, **`_fetch_score_mal()`**, **`_fetch_score_kitsu()`**: funciones individuales por fuente.
- **UI**: score chips con barras de progreso en el modal de edición (`cargarScoresModal()`).

### Motor de decisión "¿Qué veo?" (`main.py`)
- **`/api/que-veo`**: recomienda un anime de la biblioteca según estado, ánimo, y minutos disponibles.
  - Filtra: excluye completados y abandonados.
  - Prioriza "viendo" sobre "pendiente".
  - Ánimos: accion, comedia, drama, romance, terror, fantasia, scifi, misterio, slice_of_life — mapeados a géneros.
  - Minutos: estima duración restante (eps × 24 min).
  - Devuelve: `anime`, `razon`, `animo`, `animos_disponibles`.
- **UI**: modal `#modal-queveo` con selector de ánimo y campo de minutos.

### Notas por episodio
- **`episode_notes`** table: `nombre TEXT, episodio INTEGER, nota TEXT, fecha TEXT, PRIMARY KEY(nombre, episodio)`.
- **CRUD**: `guardar_nota_episodio()`, `obtener_notas_episodio()`, `obtener_nota_episodio()`, `borrar_nota_episodio()`.
- **Endpoints**: `GET/POST /api/animes/{nombre}/notas-episodio/{ep}`, `DELETE /api/animes/{nombre}/notas-episodio/{ep}`.
- **Plus1 con nota**: `POST /api/animes/{nombre}/plus1?nota=...` guarda nota automáticamente.
- **UI**: sección `<details>` en el modal de edición con listado de notas e input para añadir.

### Watch folder (auto-detección de episodios)
- **`watch_folder.py`**: watchdog que monitoriza una carpeta de descargas. Parsea nombres de archivo con regex (`[SubGroup] Name - 05`, `S01E05`, `EP1050`, `Name - 12`).
- **`_buscar_coincidencia()`**: fuzzy matching con `difflib.SequenceMatcher` contra la biblioteca.
- **Endpoints**: `GET /api/watch-folder/status`, `POST /api/watch-folder/start`, `POST /api/watch-folder/stop`, `GET /api/watch-folder/log`.
- **UI**: modal `#modal-watchfolder` con indicador de estado, input de ruta, botones start/stop, log de actividad. Botón 📂 en header.

### Sync bidireccional AniList (`anilist_sync.py`)
- **Connect**: OAuth vía `POST /api/anilist/connect` con access_token.
- **Pull**: `POST /api/anilist/pull` importa la lista de AniList → biblioteca local.
- **Push**: `POST /api/anilist/push` exporta la biblioteca local → AniList.
- **Resolve IDs**: `POST /api/anilist/resolve-ids` busca AniList IDs para animes sin vincular.
- **Auto-push**: al editar un anime (progreso, puntuación, estado), se hace push automático si AniList está conectado.
- **UI**: modal AniList en index.html con connect/disconnect, pull/push, resolve IDs, indicador en header.

### Tracking de manga
- **Tabla**: columna `tipo` ("anime"/"manga") y `volumenes_leidos` en `animes`.
- **Scraper**: `buscar_manga()` en `scrapers/anilist.py` usa AniList con `type:MANGA`.
- **API**: `POST /api/manga` para añadir manga (ruta separada de anime).
- **UI**: selector de tipo (anime/manga) en búsqueda, badges 📖, labels adaptados ("caps" vs "eps", "Capítulos leídos" vs "Episodios vistos").

### Franquicias (`franquicias.py`)
- **`agrupar_franquicias()`**: agrupa animes por nombre base (quitando Season N, Part N, II/III/IV, Movie, OVA, Special, Recap, subtítulos tras `:`).
- **`_base_name()`**: aplica regex `_SEASON_RE` iterativamente (hasta 5 pases) para nombres compuestos como "Title Movie 2: Subtitle".
- **`_season_order()`**: ordena miembros dentro de franquicia por número de temporada.
- **UI**: cards colapsables de franquicia con botón "Compactar todo".

### Enriquecimiento automático (daemon `_start_enrich_unknown_eps`)
- Arranca 60s después del startup, busca todos los animes con `capitulos="?"` y los enriquece vía AniList (rate limit 1s).
- También repara portadas: si la imagen es de AnimeFLV o está vacía, la reemplaza con la de AniList.
- Complementa los fallbacks en `POST /api/animes` (al añadir) y `POST /api/animes/refrescar` (al refrescar manualmente).

### Recomendaciones (`/api/recomendaciones`)
- Filtra por triple check: título en inglés, título en romaji, y AniList ID — para no recomendar animes ya en la biblioteca.
- AniList trending como fuente principal, Kitsu como fallback.
- `_recomendaciones_respaldo()`: usa `fuentes_respaldo.recomendaciones()` cuando AniList no responde.

### Seguridad (`main.py`)
- **LAN guard** (`_RUTAS_SOLO_LOCAL`): bloquea `/docs`, `/redoc`, `/openapi.json` desde IPs externas con 404 (no 403, para no revelar que existen).
- **CORS** restringido a localhost + subredes LAN privadas (192.168.x, 10.x, 172.16-31.x) + Capacitor/Ionic para PWA móvil.
- **`/api/apagar`**: solo accesible desde `127.0.0.1`/`::1`. Limpia Discord presence y llama `os._exit(0)` con 0.6s de retardo.
- **`ImportRequest`**: `texto: str = Field(..., max_length=500_000)` — límite de 500 KB para prevenir DoS en el endpoint de importación.

### Validación de datos (`main.py`)
- `ActualizarRequest` con Pydantic v2: `puntuacion: Field(ge=0, le=10)`, `episodios_vistos: Field(ge=0)`, `@field_validator` para `estado_usuario` (normaliza aliases inglés→español).
- SQL injection en database.py: **NO es un riesgo** — los nombres de columnas en los UPDATE dinámicos están whitelisteados en `allowed`, y los valores van con `?` parametrizado.

### Búsqueda (`main.py`)
- `_buscar_con_fallback`: timeout global `_TIMEOUT_BUSQUEDA_TOTAL = 30s` con `asyncio.wait_for`.
- Race condition en búsquedas concurrentes: resuelta con `nuevaPeticion()`/`esVigente()` (contador de petición por pantalla).
- Debounce en la búsqueda del index: `clearTimeout + setTimeout(400ms)`.
- **Autocomplete**: dropdown `#autocomplete-drop` con `oninput` que busca en la biblioteca local.

### Portadas / imágenes
- **`window.miraruPortada(img, url)`** en `customize.js`: helper centralizado para asignar src con fallback al placeholder.
- **`referrerpolicy="no-referrer"`**: añadido globalmente via `<meta name="referrer" content="no-referrer">` insertado por `customize.js` al inicio.
- Imágenes de animeflv.net dan 403 cuando el Referer no es su propio dominio.

### Caché
- Cache de búsquedas: `_search_cache` con `_cache_lock` (threading.Lock), TTL variable, max 200 entradas.
- Cache de scores: `scores:{titulo}`, TTL 1800s (30 min).
- `_cache_get(key)` / `_cache_set(key, val, ttl)`: patrón unificado con OrderedDict.

### Fuente de respaldo (`fuentes_respaldo.py`)
- Kitsu JSON:API como fallback cuando AniList da 403.
- `plataforma_desde_url()`, `genero_a_categoria()`, `_puntuacion()` (Kitsu usa 0-100, la app usa 0-10).

### HTTP con reintentos (`scrapers/net.py`)
- `make_session()`: `requests.Session` con `urllib3.Retry` (3 reintentos, backoff 0.6s, status_forcelist=[429,500,502,503,504]).
- Centralizado para todos los scrapers. Sin dependencias extra (usa lo que ya trae requests).

### Frontend: patrones de diseño (impeccable product register)

Rediseño completo de botones e interacciones siguiendo los principios del registro de producto:
- **Botones**: sin gradientes en targets pequeños. Solid `var(--accent)` para primarios, transparent para ghost. Transiciones 150-250ms.
- **`focus-visible`**: en todos los elementos interactivos (botones, inputs, selects, cards, score chips, dropdown items). Ring de `outline:2px solid var(--accent)`.
- **`prefers-reduced-motion`**: desactiva transiciones y animaciones en todos los componentes (btn, cards, toasts, dropdowns, inputs, bulk-bar).
- **Sin motion decorativo**: eliminado `translateY` y `scale` de hovers en todas las páginas de producto. Solo la landing page (`menu.html`) conserva motion expresivo (brand surface).
- **Hover de cards**: solo border-color + box-shadow sutil, sin translateY.
- **Hover de botones ghost**: `background:rgba(124,58,237,.08)` + border-color, sin opacity genérico.
- **Progress bars**: color sólido `var(--accent)`, sin gradiente.
- **Consistencia cross-page**: mismo vocabulario de botones en index, peliculas, novedades, recomendaciones, stats, import, mobile, setup.

### Frontend: intervalos y localStorage
- **Timer leak**: cualquier `setInterval` que pueda ejecutarse más de una vez debe guardarse en `window._xxxInterval` y hacer `clearInterval` antes de volver a setear.
- **`localStorage` sin try/catch LANZA en Safari Private / ITP antiguo**: todos los accesos a `localStorage` van envueltos en `try { ... } catch(_) {}`.
- **Patrón de tema en templates**: `try{if(localStorage.getItem('theme')==='light')document.documentElement.dataset.theme='light';}catch(_){}`
- **Fetch en async functions**: todos los `fetch()` del proyecto van dentro de `try { ... } catch(e) { ... }`.

### Service Worker (`static/sw.js`)
- `CACHE_NAME = 'miraru-v26'` — incrementar al desplegar cambios en cualquier template o asset estático.
- NO cachea rutas `/api/` — todas las peticiones API van a la red.
- Estático: stale-while-revalidate (devuelve caché y actualiza en background).

---

## Bugs arreglados (histórico)

| Bug | Causa | Fix |
|-----|-------|-----|
| `.bat` crasheaba al hacer doble clic | `chcp 65001` + caracteres multibyte → cmd perdía posición | Eliminado `.bat`; lógica fusionada en `Miraru.vbs` |
| Botón "Cerrar" de Estadísticas descarga HTML | `window.close()` sobre página normal → descarga | Rediseño del panel como overlay in-page |
| Novedades vacío | AniList 403 → sin fallback | Kitsu como fuente de respaldo |
| Recomendaciones sin portadas | URLs de imagen no cargadas | `miraruPortada` + `referrerpolicy` |
| Conexión leak en `get_conn()` | `with sqlite3.Connection` no cierra | `@contextmanager` con `finally: conn.close()` |
| Backup pierde datos WAL | `zipfile.write(db_path)` copia solo el `.db` | `sqlite3.Connection.backup()` en directorio temporal |
| Dos ThreadPoolExecutors separados | `main.py` y `core.py` cada uno con 6 workers | Unificado en `core.py` con 12 workers |
| Búsqueda cuelga para siempre | Sin timeout en fuente preferida | `asyncio.wait_for` con 30s total |
| Datos inválidos en PATCH | Sin validación → puntuacion=999 se guardaba | Pydantic v2 con `Field(ge=0, le=10)` |
| Migración lenta (6 animes/15min) | AniList 403 × 8 reintentos × cada anime | Circuit breaker `Cortocircuito` |
| `cap200_migrado` flag permanente | Se seteaba con biblioteca vacía → nunca re-ejecutaba | Flag eliminado; la query ES la condición de parada |
| Portadas de animeflv no cargan | Hotlinking protection → 403 cuando Referer = 127.0.0.1 | `<meta name="referrer" content="no-referrer">` global vía customize.js |
| Race condition en launcher | uvicorn falla DESPUÉS de `_server_ready` → espera 40s en silencio | Loop que comprueba `_server_failed` cada 300ms |
| 3 tests de backup fallando en suite | `os.environ` sobreescrito → backup en directorio equivocado | Backup endpoint lee `ANIME_APP_DIR` en runtime |
| `setInterval` leak | Sin referencia almacenada → se acumulan timers | `window._syncInterval` con `clearInterval` previo |
| `localStorage` lanza en Safari Private | `setItem` sin try/catch → SecurityError | Envuelto en `try { ... } catch(_) {}` |
| `ImportRequest` sin límite de tamaño | `texto: str` sin max_length → posible DoS | `Field(..., max_length=500_000)` |
| SW sirve templates viejos | `CACHE_NAME` no actualizado tras cambiar templates | Incrementar siempre al desplegar |
| Auto-backup diario pierde datos WAL | `_crear_backup_disco()` usaba `z.write(db_path)` directo | `sqlite3.Connection.backup()` |
| Motion decorativo inconsistente en botones | Gradientes, translateY, scale en hover → anti-patrón de producto | Rediseño completo con /impeccable: solid colors, focus-visible, reduced-motion |
| Cards con translateY(-4px) en hover | Decorativo sin propósito funcional | Solo border-color + box-shadow sutil |
| Sub-páginas con botones inconsistentes | peliculas, novedades, stats, import, mobile tenían estilos viejos | Todos alineados al nuevo sistema de botones |
| Franquicias: Movie/OVA/Special duplicados | `_base_name()` no eliminaba sufijos Movie/OVA/Special | Regex extendida + aplicación iterativa (hasta 5 pases) |
| AnimeFLV devuelve "?" en episodios | HTML parser no encuentra el bloque de episodios | AniList fallback en 3 niveles: al añadir, al refrescar, daemon al arrancar |
| Recomendaciones sugieren animes ya en lista | Solo comparaba un título (en o ro) | Triple check: título EN + RO + AniList ID |
| Portadas AnimeFLV rotas (403 persistente) | CDN de AnimeFLV cambia URLs o bloquea | Daemon repara automáticamente con imagen de AniList |

---

## Archivos principales y su rol

| Archivo | Rol |
|---------|-----|
| `core.py` | VERSION (fuente única), executor (ThreadPoolExecutor compartido) |
| `main.py` (~3800 líneas) | FastAPI app, endpoints, _lifespan, validación, búsqueda, backups, scores, ¿qué veo?, notas episodio, AniList sync, enrich daemon |
| `database.py` | get_conn() contextmanager, init_db(), CRUD de animes, episode_notes, ep_log |
| `migrations.py` | migrar_cap200(), refrescar_en_emision(), Cortocircuito |
| `fuentes_respaldo.py` | Kitsu API como fallback de AniList |
| `watch_folder.py` | Watchdog: auto-detección de episodios vistos en carpeta de descargas |
| `launcher.py` | Arranque, detección de Python, apertura de navegador, diálogos de error |
| `Miraru.vbs` | Lanzador único (busca Python, deps, arranca sin consola). No hay .bat. |
| `build.py` | Empaquetado PyInstaller; lee VERSION de core.py con regex |
| `scrapers/net.py` | Session HTTP con reintentos automáticos (urllib3.Retry) |
| `scrapers/kitsu.py` | Scraper Kitsu JSON:API |
| `scrapers/jikan.py` | Scraper Jikan v4 (MAL) |
| `scrapers/anilist.py` | Scraper AniList GraphQL (anime + manga), `buscar_manga()` |
| `anilist_sync.py` | Sync bidireccional AniList (connect, pull, push, resolve IDs) |
| `franquicias.py` | Agrupación de temporadas por nombre base (`_base_name`, `_season_order`) |
| `static/customize.js` | Temas, acentos, miraruPortada(), meta referrer no-referrer global |
| `static/sw.js` | Service Worker (CACHE_NAME = 'miraru-v26') — incrementar al desplegar |
| `static/theme.css` | Sistema visual unificado (variables CSS, temas) |
| `templates/index.html` | UI principal; header nav, toolbar, cards, modals, scores, diario, ¿qué veo? |
| `templates/menu.html` | Landing page / navegación principal, botón "Salir" → /api/apagar |
| `templates/peliculas.html` | Películas y series largas |
| `templates/novedades.html` | Novedades de temporada + noticias RSS |
| `templates/recomendaciones.html` | Recomendaciones personalizadas |
| `templates/stats.html` | Estadísticas (KPIs, donut, barras, genre pills, heatmap) |
| `templates/calendario.html` | Calendario de emisiones |
| `templates/import.html` | Importación MAL XML / AniList username |
| `templates/mobile.html` | Acceso móvil (PIN, QR) |
| `templates/setup.html` | Configuración inicial (Google Sheets credentials) |

---

## Tests

- Ubicación: `tests/`
- Suite: **302 tests pasando** (0 fallos)
- Cobertura: backup WAL (API + auto-disco), Cortocircuito, fuentes_respaldo, timeout de búsqueda, validación PATCH, aislamiento de env vars entre tests, ¿qué veo? (5 tests), notas por episodio (7 tests), watch folder parser (8 tests), página compartible (3 tests), scores endpoint (3 tests)
- Comando: `python -m pytest tests/ -v` desde la carpeta del proyecto
- `tests/test_nuevas_features.py`: TestQueVeo, TestNotasEpisodio, TestWatchFolderParser, TestPaginaCompartible, TestWatchFolderAPI, TestScoresEndpoint

---

## Pendientes conocidos

- [ ] Completar la desinstalación de la instalación antigua en `AppData\Local\AnimeTracker`
- [ ] Confirmar que `migrar_cap200()` completa los 170 animes pendientes (corre en background al arrancar)
- [ ] UI para tracking de manga más completa (volúmenes, capítulos leídos, progreso visual)
- [ ] Notificaciones push del navegador (además de email)

---

## Forma de trabajar de Claude en este proyecto

- **No modificar lógica sin entenderla**: siempre leer el archivo antes de editarlo.
- **Tests primero**: cualquier bug arreglado en Python debe tener test que lo reproduzca.
- **Cambios atómicos**: un fix por commit conceptual; no mezclar refactors con fixes.
- **No crear archivos temporales en el escritorio**: solo en la carpeta del proyecto.
- **Verificar con Ruff**: `ruff check .` en los archivos Python modificados antes de dar por terminado.
- **Actualizar este skill**: cada vez que se arregle un bug o se tome una decisión, añadirla a la tabla de bugs y/o a los pendientes.
- **localStorage**: SIEMPRE en try/catch. SIEMPRE. Sin excepciones.
- **setInterval**: SIEMPRE guardar referencia en `window._xxxInterval` y hacer `clearInterval` previo.
- **Backup**: SIEMPRE `sqlite3.Connection.backup()`, NUNCA `zipfile.write(db_path)`.
- **APP_DIR en runtime**: cualquier endpoint o función que acceda a directorios de la app debe leer `os.environ.get("ANIME_APP_DIR", str(APP_DIR))` en tiempo de llamada, nunca usar el `APP_DIR` del módulo directamente.
- **Service Worker**: incrementar `CACHE_NAME` cada vez que se cambien templates o assets.
- **UI / CSS**: seguir el registro de producto impeccable. Sin motion decorativo en hovers. `focus-visible` en todo lo interactivo. `prefers-reduced-motion` en todas las transiciones. Solid colors, no gradientes en botones.
- **Scores**: normalizar siempre a 0-10. AniList ÷ 10, Kitsu ÷ 10, MAL ya viene en 1-10.
- **Caché**: usar `_cache_get`/`_cache_set` con TTL apropiado. No crear caches propios.

---

*Última actualización: 2026-09-24*
