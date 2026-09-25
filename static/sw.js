// Nombre de cache versionado: incrementar para invalidar el anterior al
// desplegar, o los PWA instalados seguirian sirviendo la UI vieja desde cache.
// v15 = mejor error-handling en launcher.py (errores a stderr → arranque.log).
// v16 = franquicias (agrupación de temporadas) + optimización rendimiento.
// v17 = limpieza código muerto + optimización global (DB pool, slim API, GZip,
//        chunked render, debounce, CSS containment, cache headers).
// v18 = botón compactar franquicias, fix recomendaciones duplicadas,
//        comprobador anti-duplicados al añadir anime.
// v19 = optimización rendimiento: imágenes /medium/, lazy-load con
//        IntersectionObserver, content-visibility, CSS containment,
//        eliminación animaciones cardIn, reducción event listeners.
// v20 = _thumbUrl en todas las páginas, event delegation en #lista,
//        innerHTML templating en _crearCard (de ~30 createElement a 1 parse).
// v21 = fix onerror infinite loop (img.src=''), fix src='' en modales,
//        meta referrer global, cache avgScore en sort, hoist getElementById.
// v22 = sync bidireccional AniList: backend (anilist_sync.py, 7 endpoints),
//        UI modal en index.html (connect/disconnect, pull/push, resolve IDs),
//        indicador de estado en header, auto-push al editar anime.
// v25 = fix franquicias + refresh fallback + enrichment daemon eps "?"
// v26 = fix recomendaciones (no sugerir animes ya en lista, check por ID +
//        título en/ro), reparación auto portadas AnimeFLV → AniList.
// v27 = rate limit en AniList sync (push_all, resolve_ids), fix fetch sin
//        catch en favorito toggle, fix setInterval leak en anilistConnect().
// v28 = fix "? ep": AniList query ahora pide nextAiringEpisode para obtener
//        eps de series en emisión (ej. One Piece → "1120+"), refrescar_metadata
//        acepta anilist_id, endpoint /refrescar también guarda anilist_id.
// v29 = manga UI mejorada: volúmenes leídos/totales en modal de edición,
//        progreso visual, card muestra vols, PATCH acepta volumenes_leidos,
//        AniList scraper devuelve volumenes_totales desde query.
const CACHE_NAME = 'miraru-v29';
const STATIC_ASSETS = [
  '/',
  '/app',
  '/stats',
  '/calendario',
  '/novedades',
  '/recomendaciones',
  '/peliculas',
  '/import',
  '/mobile',
  '/static/theme.css',
  '/static/customize.js',
  // Tipografias locales: sin esto la app offline pierde su tipografia
  '/static/fonts/inter-latin-400-normal.woff2',
  '/static/fonts/inter-latin-600-normal.woff2',
  '/static/fonts/inter-latin-700-normal.woff2',
  '/static/fonts/space-grotesk-latin-700-normal.woff2',
  '/static/icons.svg',
  '/static/logo.png',
  '/static/logo.svg',
  '/static/icon.ico',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  // addAll falla entero si un asset falla — usamos add() individual con catch
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      Promise.all(STATIC_ASSETS.map(a => cache.add(a).catch(() => null)))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API: siempre red, sin caché. Si falla, JSON offline.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(JSON.stringify({error: 'offline'}), {
          headers: {'Content-Type': 'application/json'}
        })
      )
    );
    return;
  }

  // Estático: stale-while-revalidate (devuelve caché y actualiza en background)
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then(cached => {
      const fetched = fetch(event.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return resp;
      }).catch(() => cached);
      return cached || fetched;
    })
  );
});
