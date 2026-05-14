# Changelog

## v1.0.0 — Release inicial

### Funcionalidades
- Lista de anime con 8 fuentes de búsqueda (AniList, Jikan v4, Kitsu, Crunchyroll, AnimeFLV, AnimePlanet, AnimeAV1, MAL)
- Buscador con vista previa en dropdown antes de añadir
- Vista grid de tarjetas y tabla compacta (alternar con ≡)
- Listas personalizadas (Principal, Quiero ver, Completados)
- Favoritos, temporada, puntuación, notas por anime
- Ordenar por nombre, puntuación, progreso, fecha inicio/fin, favoritos
- Drag & drop para mover animes entre listas
- Atajos de teclado: / buscar, Esc cerrar, N nuevo anime, doble-clic +1 episodio
- Estadísticas con donut chart SVG, genre pills, 6 KPIs
- Novedades: próximos episodios y animes en emisión (AniList API)
- Recomendaciones automáticas basadas en géneros favoritos
- Calendario semanal de episodios programados
- Web Notifications toggle on/off para alertas de nuevos episodios
- Google Sheets sync (completamente opcional)
- Acceso móvil vía WiFi local con PIN + token + QR
- PWA instalable con service worker para cache offline
- 4 idiomas: Español, English, Français, Deutsch
- Modo claro (blanco + indigo) y oscuro (negro + morado)
- Importar desde texto, MAL XML o AniList username
- Exportar CSV y JSON
- Imagen fallback automática desde AniList cuando el scraper no devuelve foto

### Técnico
- Python 3.9+ / FastAPI / SQLite
- 64 rutas API, 0 duplicadas
- 8 scrapers con fallback de imagen
- Migraciones automáticas de BD
- PyInstaller --onedir para Windows
- GitHub Actions CI en Python 3.9/3.11/3.12
