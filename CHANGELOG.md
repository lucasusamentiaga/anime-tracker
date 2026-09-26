# Changelog

## v2.10.0 — Avisos con la pestaña cerrada, modo sin conexión real y un .exe que arranca

### Avisos de nuevos episodios aunque cierres la pestaña (Web Push)
Con Miraru abierto en segundo plano, los avisos de la campanita llegan como
notificación del sistema aunque no tengas la pestaña abierta. Se activa con el
botón **Avisos**; para comprobarlo, en la paleta de comandos está *Probar
notificación push*. Lo ya avisado se recuerda entre reinicios (antes cada
reinicio repetía los avisos).

### El Service Worker nunca había funcionado
Se registraba en `/static/sw.js` y, sin la cabecera que lo permite, solo
controlaba `/static/`: ninguna página de la app. Ahora controla toda la app:
- **Sin conexión** Miraru abre con tu lista y los textos.
- Las actualizaciones se ven al momento (las páginas van primero a la red).

### El .exe fallaba al arrancar
`build.py` enumeraba los módulos a mano y `anilist_sync.py`, `watch_folder.py`
y `metadatos.py` se habían quedado fuera: la versión empaquetada daba
ImportError. Ahora se descubren solos y un test lo vigila.

### La carpeta vigilada marcaba episodios en el anime equivocado
Con una biblioteca real, la mitad de los archivos típicos iban mal:
"Naruto Shippuden - 100" → Naruto, "Spy x Family S02E05" → una campaña de la
película. Ahora tiene en cuenta la temporada, descarta películas/OVAs y nunca
marca animes completados ni pasa del total de capítulos.

### Más arreglos
- "Refrescar metadatos" ya no cambia tus sinopsis en español por las de AniList.
- Los completados importados tenían 0 episodios vistos (fichas en 0/12).
- AniList: un anime en pausa se importaba con un estado que no existía, y el
  callback de conexión se rompía con ciertos códigos.
- Pool de conexiones a la BD que podía devolver una conexión a otro fichero.
- `MIRARU_NO_BROWSER=1` arranca Miraru sin abrir el navegador.

## v2.9.0 — Datos que ya no se estropean solos, y todo lo nuevo desde la 2.8.4

### Novedades desde la 2.8.4
- **Manga**: tipo anime/manga, volúmenes leídos/totales con barra de progreso.
- **Sync bidireccional con AniList** (conectar, bajar, subir, resolver IDs).
- **Carpeta vigilada**: detecta episodios descargados y los marca.
- Notas por episodio, puntuaciones externas (AniList/MAL/Kitsu), motor
  "¿Qué veo?" y franquicias agrupadas.
- **Notificaciones del navegador** vía Service Worker (funcionan en Chrome
  Android) que comprueban al abrir la app; clic en el aviso → abre Miraru.

### Refrescos que empeoraban los datos
El refresco automático de series en emisión (cada 12 h) y el botón "Refrescar
metadatos" re-consultaban la fuente original y **sobrescribían** lo bueno con lo
malo: "1179+" de One Piece pasaba a "?", y las portadas de AniList se cambiaban
por las de anime-planet, cuyo scraper coge la primera tarjeta del listado aunque
no coincida (Naruto acababa con la de *Road of Naruto*). Ahora hay un único
juego de reglas (`metadatos.py`) que nunca empeora un dato, y se consulta AniList
por ID en lotes de 50. El refresco manual corre en segundo plano con progreso,
en vez de una petición que tardaba muchos minutos y chocaba con el límite de
AniList (30 peticiones/min).

### Notificaciones que no llegaban nunca
La consulta de nuevos episodios pedía todos los títulos en una sola query a
AniList; si **uno** no casaba, AniList devolvía 404 para todos. Bastaba un
nombre estilo AnimeFLV con la campanita activada para que no llegase ningún
aviso, ni por email ni en el navegador. Ahora se consulta por ID.

### Episodios en "?" y portadas rotas
Los 342 animes tenían `anilist_id = 0` y los nombres heredados de AnimeFLV
("Black Clover (TV)", "Baki (2018)") no se encontraban. Ahora la búsqueda prueba
variantes del título y, si no, pasa por MyAnimeList. El arranque resuelve IDs
poco a poco (40 por arranque) y repara portadas de AnimeFLV/anime-planet.

### Duplicados
"One Punch Man" y "One-Punch Man", o "Spy x Family" y "SPY x FAMILY", entraban
como animes distintos. La comprobación ahora ignora mayúsculas y signos (las
temporadas siguen siendo distintas) y los pares existentes se fusionaron sin
perder progreso, notas ni historial.

### Más arreglos
- Openings y personajes: con la API caída la ficha esperaba ~53 s y cacheaba el
  fallo hasta reiniciar. Ahora 8 s como mucho y los errores no se cachean.
- Emails de notificación con los datos escapados.
- Etiquetas con "/" que luego no se podían borrar.
- `/api/sync` sin `credentials.json`: aviso claro en vez de error 500.

## v2.8.4 — Nada fuera de la carpeta, y datos que no se corrompen solos

### Miraru ya no toca el escritorio
- Se retiró la creación del acceso directo. Todo lo de Miraru vive en la carpeta
  del proyecto. Para abrirlo de un clic: clic derecho en `Miraru.vbs` → *Anclar
  a la barra de tareas*.

### La versión estaba escrita en cuatro sitios y los cuatro discrepaban
main.py decía 2.8.0, core.py 2.7.0, el instalador **2.4.0** y el manifest de la
PWA 2.7.0. No era cosmético: el instalador escribía esa versión falsa en el
registro de Windows, y el cliente móvil compara la versión del servidor para
decidir si le sirve. Ahora `core.VERSION` es la única declaración, el instalador
la recibe por sustitución al compilar, y `tests/test_version.py` falla si alguien
vuelve a escribirla a mano.

### Datos que se corrompían en silencio
El PATCH de un anime no validaba nada:
- `puntuacion: 999` y `episodios_vistos: -50` se guardaban tal cual y dejaban la
  nota media, las horas vistas y el heatmap **en negativo**;
- un `estado_usuario` inventado se guardaba pero luego no casaba con ninguna
  consulta de estadísticas: el anime desaparecía de los recuentos sin avisar.

Ahora los rangos están en el modelo (0-10, ≥0, 0/1) y los estados se validan y
se normalizan —`watching` → `viendo`—, que antes convivían en la misma columna.

### La búsqueda podía colgarse para siempre
- `_buscar_con_fallback` esperaba a las 8 fuentes **sin plazo**. Si una web se
  quedaba colgada, "Añadir anime" giraba indefinidamente. Ahora hay un plazo
  global de 30 s.
- La fuente preferida se esperaba **sin timeout y sin `try`**: una fuente lenta
  bloqueaba toda la búsqueda, y una que lanzara excepción devolvía un 500 en vez
  de caer a las demás. Ambos cubiertos por tests.
- **Un solo pool de hilos.** Había dos de 6 (uno en `main`, otro en `core`) que
  se ignoraban: uno podía saturarse con el otro ocioso. Unificado en `core` y
  subido a 12, porque cancelar un Future no detiene el hilo que hay debajo y con
  el pool justo una fuente lenta congelaba la app entera.

### Seguridad
- `/docs`, `/redoc` y `/openapi.json` quedaban fuera del guard de LAN, que solo
  miraba rutas `/api/`. Con el modo móvil activo, cualquiera en el mismo WiFi
  podía abrir la documentación interactiva y llevarse el mapa completo de la API.
  Ahora son solo de loopback (404 desde fuera, para no confirmar que existen).

### Rendimiento
- Las portadas del modo principiante se cachean 12 h: **2,9 s → 2 ms**. Son una
  lista fija, lo único que cambia con el usuario es el orden. La caché admite
  ahora un TTL por entrada.

### Verificación
- **253 tests** (19 nuevos de validación, 13 de LAN, 7 de versión, 5 de plazos).
- Ruff **no estaba instalado en el venv**: las comprobaciones anteriores no
  revisaban nada y devolvían vacío. Instalado; encontró 4 avisos, corregidos.

## v2.8.3 — Sin consola, y con logo en todas las pestañas

- **Se acabó la ventana de cmd.** `Miraru.vbs` es el nuevo punto de entrada:
  lanza el `.bat` de siempre con la ventana oculta, así que no aparece ninguna
  consola. El acceso directo del escritorio apunta ya al `.vbs`. Si el arranque
  falla, en vez de no pasar nada sale un cuadro de diálogo con el detalle.
- **Botón «⏻ Salir» en el menú** + `POST /api/apagar`. Sin consola que cerrar
  hacía falta una forma clara de apagar el servidor; si no, se quedaría
  corriendo de fondo indefinidamente. Solo funciona **desde este ordenador**:
  en modo red el móvil también alcanza el servidor, y no debe poder apagar el PC.
- **El logo desaparecía al salir del menú.** Solo 2 de las 10 páginas traían
  `<link rel="icon">`, y `/favicon.ico` — que el navegador pide por su cuenta
  cuando la página no declara ninguno — daba **404**. Ahora lo declaran las diez
  *y* existe la ruta, para que una página futura que se despiste siga bien.
- `--sin-consola` en el `.bat`: en modo oculto no puede haber ningún `pause`,
  esperaría eternamente una tecla que nadie puede pulsar. Ahora sale con código
  de error y deja que el `.vbs` muestre el aviso.
- 15 tests nuevos (permisos del apagado, favicon en las 10 rutas). **209 en total.**

## v2.8.2 — AniList se cayó y la app se quedó muda

### La causa de fondo
La API de AniList empezó a responder **403 "The AniList API has been temporarily
disabled due to severe stability issues"**. Como `_anilist()` se tragaba el error
devolviendo `{}`, tres pantallas se vaciaron sin decir por qué —  y encima
culpando al usuario ("comprueba tu conexión").

- **Respaldo sobre Kitsu** (`fuentes_respaldo.py`): Novedades, Recomendaciones y
  las portadas del modo principiante siguen funcionando con AniList caído. Kitsu
  entrega los enlaces de streaming en la misma petición, así que **el filtro por
  plataforma sigue vivo** (Netflix, Crunchyroll…). La caché caduca a los 5 min,
  de modo que cuando AniList vuelva la app se reengancha sola.
- **`_anilist_con_error()`**: los fallos dejan de ser silenciosos. Ahora quien
  llama distingue "no hay resultados" de "la fuente está caída", y la interfaz
  dice cuál es la fuente real en vez de insinuar que falla tu internet.
- Las portadas del modo principiante se rellenan buscando por título: los ids de
  `gateway_anime.py` son de AniList y Kitsu no los entiende.

### Bugs de interfaz
- **El botón "Cerrar" de Estadísticas descargaba un HTML.** `querySelector('.back-btn')`
  devuelve el *primero* con esa clase, y desde que existe "Compartir biblioteca"
  ese es el de compartir. Le reescribía la etiqueta a "← Cerrar" dejando intacto
  el `href` de descarga. Ahora se selecciona por id.
- **Noticias mostraba el filtro de plataformas.** Condición de carrera: `init()`
  lanza `cargar('all')` al abrir la página y esa petición tarda; si pulsabas
  Noticias mientras seguía en vuelo, la respuesta tardía machacaba las noticias
  con su "Sin resultados". Cada carga toma ahora un número y solo la más reciente
  puede pintar.
- **`img.src = ''` en 10 sitios.** La cadena vacía se resuelve contra la URL
  actual, así que el navegador se descargaba **la propia página como imagen** por
  cada portada ausente. Nuevo `miraruPortada()` en `customize.js` (el único
  script presente en las 10 páginas) con marcador de posición real.
- Retirado el botón flotante **⌘K** sobre el buscador. El atajo Ctrl+K sigue
  abriendo la paleta igual.
- `querySelector('.plat-btn')` → `[data-p="all"]`: reordenar la barra ya no
  rompería qué botón se marca como activo.

### Verificación
- 14 tests nuevos del respaldo (parseo de un payload JSON:API real, filtrado por
  plataforma, conversión de escala de puntuación). **194 en total**, Ruff limpio,
  110 rutas sin duplicados.

## v2.8.1 — Abrir la app con un doble clic

- **`Miraru.bat`**: doble clic y la app arranca. Busca Python (prioriza el
  `venv/` del proyecto), instala las dependencias que falten la primera vez,
  crea un acceso directo en el escritorio con el icono de la app y lanza el
  servidor abriendo el navegador. Si no hay Python, lo dice y enlaza la descarga
  en lugar de cerrarse de golpe. Se acabó escribir comandos.
- **Fallo de codificación en el lanzador, corregido durante las pruebas.** La
  primera versión llevaba `chcp 65001` y caracteres de recuadro en los
  comentarios. `cmd.exe` lee el `.bat` por desplazamiento de bytes *mientras* lo
  ejecuta, así que cambiar la página de códigos a mitad de archivo le hace
  perder la posición: ejecutaba trozos sueltos de línea (`ot`, `-m`, `el`...) y
  nunca llegaba a arrancar el servidor. El archivo es ahora ASCII puro y sin
  `chcp`, con un comentario que explica por qué debe seguir así.
- Eliminados `miraru_probe.db` y su journal, restos de pruebas anteriores.

## v2.8.0 — Profesionalización: routers, linting, reintentos y offline real

### Bug importante corregido
- **Las rachas se rompían solas.** `ep_log` e `historial` guardaban las fechas en
  UTC, pero las rachas, el heatmap y el Wrapped las comparan con la fecha
  **local**: ver un episodio de noche lo contaba como del día anterior y
  cortaba la racha sin motivo. Ahora todo usa hora local.
- **Bug latente en el parser RSS** (detectado por Ruff): una función anidada
  capturaba la variable del bucle por referencia.

### Arquitectura
- `main.py` deja de ser un monolito: los endpoints se reparten en `routers/`
  (`media`, `gamificacion`, `noticias`) con `APIRouter`, y la infraestructura
  compartida vive en `core.py`. Cada archivo cabe ya en una sesión de trabajo.

### Fiabilidad
- **Reintentos automáticos con backoff** en los 8 scrapers (`scrapers/net.py`).
  Un 503 o un 429 puntual ya no arruina una importación masiva. Sin dependencias
  nuevas: usa el `Retry` de urllib3 que `requests` ya incluye.
- **Fichas huecas de scrapers rotos, corregidas** (`scrapers/calidad.py`). Los
  scrapers que leen HTML no fallan de forma limpia cuando la web cambia el CSS:
  devuelven una ficha con el nombre pero sin episodios, imagen, sinopsis ni
  géneros. Como era "verdadera", la búsqueda la daba por buena y se guardaba una
  entrada vacía. Ahora se detecta y se completa con una fuente de API
  estructurada, conservando el nombre y la fuente que eligió el usuario. Si la
  ficha ya venía completa, no se hace ninguna consulta extra.

### Calidad y seguridad
- **Ruff** configurado (`pyproject.toml`) y en CI. Reglas elegidas para cazar
  bugs, no para imponer estilo; se documenta por qué se ignora `UP045` (Pydantic
  evalúa anotaciones en runtime y el objetivo incluye Python 3.9).
- **gitleaks** en CI: evita que `credentials.json` o claves de TMDB/Gmail acaben
  en el historial, donde una filtración sería irreversible.
- El chequeo de rutas duplicadas del CI ahora cubre también los routers.

### Offline real
- **Tipografías auto-alojadas**: Inter y Space Grotesk se sirven desde
  `/static/fonts` (~190 KB, subset latin). Se eliminaron los 34 enlaces a Google
  Fonts: la app es offline-first y sin internet perdía su tipografía.

### Nuevo
- **Noticias de anime**: pestaña «📰 Noticias» en Novedades que agrega Kudasai,
  Crunchyroll y Anime News Network vía RSS, con caché de 1 hora, imagen
  destacada y antigüedad ("hace 2 h"). Sin dependencias nuevas.
- **Openings y endings** en la ficha del anime (AnimeThemes.moe): botones por
  tema con reproductor integrado. Se carga aparte del resto de la ficha, así que
  si esa API falla no te quedas sin tráiler ni similares.
- **Personajes y seiyuus** en la ficha (Jikan): tira de personajes principales
  con su actor de voz. Al pasar el ratón sobre un personaje se ve la cara de
  quien lo dobla. Prioriza el doblaje japonés, que es el relevante en anime.

### Mantenimiento
- **`on_event` → `lifespan`**: se migró el arranque al mecanismo actual de
  FastAPI (el anterior estaba marcado como obsoleto). De paso se ganó un
  apagado limpio: al cerrar la app se borra el estado de Discord, que antes
  quedaba colgado mostrando "viendo X".
- **Firma del ejecutable preparada**: `release.yml` incluye un paso que firma y
  **verifica** los `.exe`, y que se salta solo mientras no haya certificado. Para
  activarlo basta con añadir dos secretos al repositorio; el proceso, las
  opciones y sus costes están en `packaging/README.md`.
- **Discord Rich Presence** opcional: muestra qué estás viendo. Si Discord no
  está abierto o falta `pypresence`, se desactiva solo sin romper nada.

## v2.7.0 — Miraru: personalización, gamificación y revisión completa

### Identidad
- La app pasa a llamarse **Miraru** (anime + series + películas). Nuevo logo
  (disco con play y arco de progreso) y variantes: `logo.svg`, `logo-lockup.svg`,
  `logo-mono.svg`, `logo-animated.svg`. Favicon y logo PNG regenerados.
- Set de iconos SVG coherente en `static/icons.svg` (trazo uniforme, heredan color).

### Personalización (nuevo)
- Panel de **Apariencia** (botón 🎨 en la cabecera y flotante en el resto de
  páginas): tema claro/oscuro, **8 colores de acento**, densidad (cómoda/compacta),
  esquinas (suaves/medias/rectas), fondo ambiental y animaciones.
- Se aplica antes del primer pintado (sin parpadeo) y persiste en el navegador.
- Todo el sistema visual consume tokens, así que el acento repinta la app entera,
  incluidas las partículas y el brillo del menú de inicio.

### Gamificación
- **Racha de apertura diaria** (+1 por día consecutivo, idempotente).
- **Niveles y XP** derivados de tu actividad, con barra de progreso.
- **16 logros** con emblemas forjados; nuevos: Enamorado (favoritos) y Maestro.
- Celebración animada al subir de nivel y distintivo NUEVO en emblemas recientes.

### Bugs corregidos
- **Búsqueda con fallback rota**: `asyncio.create_task` sobre un Future lanzaba
  `TypeError`, así que si la fuente preferida no tenía el anime la búsqueda
  fallaba (500) en vez de probar las demás fuentes.
- **Conmutador de tema**: requería dos clics tras unificar el sistema de temas.
- **PWA servía la interfaz antigua**: caché del service worker sin invalidar.
- **Desinstalación**: tras el rebrand se creaban accesos "Miraru.lnk" pero se
  borraban "Anime Tracker.lnk" → quedaban huérfanos. Ahora limpia ambos.
- **Cliente móvil**: rechazaba servidores de versiones futuras (comprobaba "2.")
  y no reconocía el nuevo identificador de la app.
- **Modo claro** forzaba índigo fijo e ignoraba el acento elegido.

### Limpieza y optimización
- Eliminadas dos secciones de código muertas en `main.py` y un comentario CSS
  huérfano; `.gitignore` cubre ahora la app móvil.
- Lectura de configuración en lote (`get_config_many`): la pantalla de inicio
  pasa de ~8 conexiones SQLite a 2.
- Branding y paleta actualizados en el cliente móvil y en Capacitor.

## v2.6.2 — BUG GRAVE corregido: cap=200 fantasma

### El bug
Todos los scrapers (anilist, mal, jikan, kitsu, crunchyroll, animeplanet, animeflv, animeav1)
tenian un clamp absurdo `min(episodes, 200)` heredado de version vieja. Resultado:
- One Piece (1100 eps) -> guardado como 200
- Detective Conan (1100 eps) -> guardado como 200
- Naruto Shippuden (500 eps) -> guardado como 200
- Cualquier anime con eps desconocidos -> tambien 200 en algunos casos
- Las estadisticas estaban distorsionadas en consecuencia

### Solucion
- Eliminado el cap de 200 en TODOS los scrapers (8 archivos + 2 sitios en main.py)
- Nueva logica: usar el numero real de episodios; "pelicula" solo cuando la fuente
  marca format=MOVIE (no por episodes=0 como antes); "?" si no se conoce
- Anilist y main.py: query GraphQL ahora pide tambien `format` para deteccion correcta
- Endpoint nuevo `POST /api/animes/refrescar`: re-consulta cada anime para refrescar
  capitulos/imagen/sinopsis/generos SIN tocar tu progreso (estado, puntuacion,
  episodios_vistos, notas, listas, favoritos)
- Funcion `db.refrescar_metadata_anime()` con whitelist separada para campos de fuente
- Boton "🔧 Refrescar metadatos" en la paleta de comandos (Ctrl+K)
- 3 tests nuevos que validan: 1100 eps no se clampan, format=MOVIE -> pelicula,
  episodes=null sin format -> "?" en lugar de "pelicula"

### Como usarlo
Si tienes animes con cap=200 erroneo del bug viejo: Ctrl+K -> "Refrescar metadatos"
o ejecuta `POST /api/animes/refrescar {"solo_cap_200":true}`.


## v2.6.1 — Estadisticas correctas + glow en sub-paginas

### Arreglos
- 🔴 BUG estadisticas: anime marcado como "completado" SIN incrementar episodios manualmente ahora cuenta todos sus capitulos (antes daba 0 episodios y 0 horas)
- Nuevo campo total_hours en /api/stats con calculo exacto (incluye peliculas, 95min)
- Peliculas: si estan completadas, suman 1 episodio + 95 min como pelicula
- 🔴 BUG CSS pre-existente en stats.html: 2 bloques huerfanos sin selector que rompian parte del estilo

### Visual
- Efecto neon (glow violeta-magenta pulsante) en los titulos de las sub-paginas: Estadisticas, Novedades, Calendario, Recomendaciones, Importar y Pelis/Series
- Mismo efecto en el titulo "Anime Tracker" del header de la app, usando drop-shadow (compatible con texto-degradado)
- Respeta prefers-reduced-motion


## v2.6.0 — Descubrimiento, progreso y pulido de Pelis/Series

### Nuevas features (basadas en research de Yamtrack y Watcharr)
- 🔥 **Tendencias / descubrimiento**: boton que trae pelis y series en tendencia de TMDB (resuelve el estado vacio, ayuda a descubrir que ver)
- 📺 **Progreso de episodios por serie**: barra de progreso en la tarjeta + editor de episodios vistos
- 🔁 **Contador de re-visionados** (rewatches), como Yamtrack
- 🔎 **Buscar / ordenar / filtrar tu coleccion**: por titulo, año, nota TMDB, mi puntuacion, estado y favoritos
- ⬇ **Export de pelis/series** a CSV y JSON
- 🎬 **Stats de cine en el menu principal** (contador incluye pelis y series)

### Arreglos
- Bug del boton ⚙️: ya no machaca tu coleccion al abrir ajustes si ya hay clave; muestra panel de gestion (reemplazar / desconectar)
- Idioma de TMDB: ahora sigue el idioma de la app (es/en/fr/de) en vez de español fijo
- Migracion BD v7: columnas rewatches/fechas en media (no rompe BDs existentes)

## v2.5.0 — Pelis/Series + validacion de clave

- Seccion de peliculas y series (no-anime) via TMDB con tabla `media` propia
- Scraper TMDB (busqueda, detalle, validacion de clave, tendencias)
- Validacion de la API key contra TMDB antes de guardar (+ tutorial in-app con los nombres exactos de los campos)
- Boton abajo-izquierda en el menu + acceso desde el header de la app
- 11 tests nuevos de media

### Visual (v2.5.0)
- Refresh: malla de fondo, tipografia Inter, acentos violeta->magenta
- Titulo del menu con efecto neon pulsante
- Boton de Instagram con micro-animacion al hover
- Bug del multi-select arreglado (wiring corria antes de existir el DOM)
- Bug del ESC en el modal de atajos
- Busqueda multi-fuente ("Todas las fuentes")

## Caracteristicas base

- App de escritorio Python + FastAPI + SQLite
- 8 fuentes de busqueda de anime + pelis/series via TMDB
- Estadisticas, heatmap, streaks, calendario, auth PIN, auto-update, backups
- 4 idiomas (ES/EN/FR/DE), modo claro/oscuro, instalador Windows (.exe)
- 74 tests automatizados
