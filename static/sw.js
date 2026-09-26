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
// v30 = fix auditoría: try/catch en bulkApply undo, response check en
//        borrarNotaDiario, XSS fix en wfLoadLog, notification badge ordering.
// v31 = notificaciones: notificationclick abre/enfoca Miraru; la página usa
//        registration.showNotification (Chrome Android no admite new Notification).
// v32 = anti-duplicados con clave normalizada (mayúsculas, guiones, puntos).
// v33 = refresco de metadatos en segundo plano con progreso.
// v34 = versión 2.9.0 (manifest.json).
// v35 = alcance "/" (servido desde /sw.js), páginas red-primero, solo mismo
//        origen, y evento 'push' (Web Push: avisos con la pestaña cerrada).
// v36 = textos y lista disponibles sin conexión (API_OFFLINE, red primero).
// v37 = mensaje de PIN unificado en /mobile.
// v38 = versión 2.10.0.
const CACHE_NAME = 'miraru-v38';
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

// GET de la API que se guardan para poder abrir la app sin conexión.
const API_OFFLINE = ['/api/lang', '/api/animes/slim', '/api/animes'];

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
  // Solo peticiones de Miraru: las portadas de AniList/Kitsu y demás CDNs van
  // directas a la red (respuestas opacas, no se pueden cachear bien).
  if (url.origin !== self.location.origin) return;

  // Lecturas imprescindibles para usar la app sin conexión (textos y lista):
  // red primero y, si no hay red, la última respuesta guardada.
  if (event.request.method === 'GET' && API_OFFLINE.includes(url.pathname)) {
    event.respondWith(
      fetch(event.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return resp;
      }).catch(() => caches.match(event.request).then(c => c ||
        new Response(JSON.stringify({error: 'offline'}), {headers: {'Content-Type': 'application/json'}})))
    );
    return;
  }

  // Resto de la API: siempre red, sin caché. Si falla, JSON offline.
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

  if (event.request.method !== 'GET') return;

  // Páginas: red primero (así una actualización se ve al momento) y la caché
  // solo como respaldo sin conexión.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return resp;
      }).catch(() => caches.match(event.request).then(c => c || caches.match('/app')))
    );
    return;
  }

  // Estático: stale-while-revalidate (devuelve caché y actualiza en background)
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

// Clic en una notificación de nuevo episodio → enfocar la pestaña de Miraru
// si ya está abierta; si no, abrir una nueva.
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if (new URL(c.url).origin === self.location.origin && 'focus' in c) return c.focus();
      }
      return self.clients.openWindow ? self.clients.openWindow(url) : undefined;
    })
  );
});

// Web Push: el servidor de Miraru avisa de episodios nuevos aunque la pestaña
// esté cerrada. Payload JSON {title, body, url, tag, icon}.
self.addEventListener('push', event => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; }
  catch (_) { d = { body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(d.title || 'Miraru', {
    body: d.body || '',
    icon: d.icon || '/static/logo.png',
    badge: '/static/logo.png',
    tag: d.tag || undefined,
    data: { url: d.url || '/app' },
  }));
});
