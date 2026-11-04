// Miraru × AnimeAV1 — copia a Miraru, al momento, los episodios que marcas
// como vistos en animeav1.com.
//
// Cómo: la web de AnimeAV1, al pulsar «Marcar como visto», hace
//   POST https://animeav1.com/api/user/library  {"mediaId": 123, "episode": 5}
// La extensión solo OBSERVA esa petición (no la toca ni lee nada más) y, si
// AnimeAV1 contesta bien, se lo cuenta a Miraru en tu PC (127.0.0.1:8765).
// Si Miraru está cerrado, lo guarda y lo manda en cuanto vuelva a abrirse.

const URL_LISTA = 'https://*.animeav1.com/api/user/library*';   // *. incluye animeav1.com
const PUERTO_POR_DEFECTO = 8765;
const pendientes = new Map();       // requestId → cuerpo, hasta saber si fue bien

async function puerto() {
  const {puerto} = await chrome.storage.local.get('puerto');
  return Number(puerto) || PUERTO_POR_DEFECTO;
}

function leerCuerpo(details) {
  const raw = details.requestBody && details.requestBody.raw;
  if (!raw || !raw.length) return null;
  try {
    const bytes = raw.map(p => new Uint8Array(p.bytes || []));
    const total = new Uint8Array(bytes.reduce((n, b) => n + b.length, 0));
    let i = 0;
    for (const b of bytes) { total.set(b, i); i += b.length; }
    const j = JSON.parse(new TextDecoder().decode(total));
    return j && typeof j === 'object' && Number(j.mediaId) > 0 ? j : null;
  } catch (_) { return null; }
}

// Chrome puede dormir la extensión entre que sale la petición y llega la
// respuesta: lo pendiente se guarda también en storage.session.
const clavePend = id => 'pend_' + id;

chrome.webRequest.onBeforeRequest.addListener(details => {
  if (details.method !== 'POST') return;
  const cuerpo = leerCuerpo(details);
  if (!cuerpo) return;
  const p = {cuerpo, tabId: details.tabId};
  pendientes.set(details.requestId, p);
  chrome.storage.session.set({[clavePend(details.requestId)]: p}).catch(() => {});
}, {urls: [URL_LISTA]}, ['requestBody']);

async function sacarPendiente(requestId) {
  let p = pendientes.get(requestId);
  pendientes.delete(requestId);
  const k = clavePend(requestId);
  if (!p) { try { p = (await chrome.storage.session.get(k))[k]; } catch (_) { /* nada */ } }
  chrome.storage.session.remove(k).catch(() => {});
  return p;
}

chrome.webRequest.onCompleted.addListener(async details => {
  const p = await sacarPendiente(details.requestId);
  if (!p || details.statusCode >= 400) return;
  const ev = {mediaId: Number(p.cuerpo.mediaId)};
  if ('episode' in p.cuerpo) ev.episode = p.cuerpo.episode == null ? 0 : Number(p.cuerpo.episode);
  if ('status' in p.cuerpo && p.cuerpo.status != null) ev.status = Number(p.cuerpo.status);
  if (!('episode' in ev) && !('status' in ev)) return;   // solo nota o puntuación
  try {
    const tab = p.tabId >= 0 ? await chrome.tabs.get(p.tabId) : null;
    const m = tab && tab.url ? tab.url.match(/animeav1\.com\/media\/([^/?#]+)(?:\/(\d+))?/) : null;
    if (m) ev.slug = decodeURIComponent(m[1]);
    // En la página del episodio N, «Marcar como visto» manda N y «Marcar como no
    // visto» manda el anterior. Así Miraru sabe si es marcar o desmarcar (y dos
    // clics que llegan desordenados no bajan el progreso).
    if (m && m[2] && 'episode' in ev) ev.accion = ev.episode >= Number(m[2]) ? 'marcar' : 'desmarcar';
    if (tab && tab.title) ev.titulo = tab.title.slice(0, 300);
  } catch (_) { /* la pestaña se cerró: Miraru lo resuelve por el id */ }
  await encolar(ev);
  await enviarCola();
}, {urls: [URL_LISTA]});

chrome.webRequest.onErrorOccurred.addListener(d => { sacarPendiente(d.requestId); }, {urls: [URL_LISTA]});

// ── Cola: nada se pierde si Miraru está cerrado ─────────────────────────────
// Cada evento lleva un id propio. Al enviar se relee la cola y solo se quitan
// los enviados: si marcas otro episodio mientras se envía el anterior, no se
// pierde (antes se sobrescribía la cola y ese segundo clic desaparecía).
const MAX_INTENTOS = 60;            // ~1 h reintentando un fallo del servidor

// Todos los cambios de la cola, de uno en uno: dos clics casi a la vez leían
// la cola vacía a la vez y el segundo pisaba al primero (o al revés).
let candado = Promise.resolve();
function enOrden(fn) {
  const r = candado.then(fn);
  candado = r.catch(() => {});
  return r;
}

function encolar(ev) { return enOrden(() => _encolar(ev)); }
async function _encolar(ev) {
  const {cola = []} = await chrome.storage.local.get('cola');
  ev.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  ev.cuando = Date.now();
  ev.intentos = 0;
  // Del mismo anime solo importa lo último que hiciste.
  const nueva = cola.filter(e => e.mediaId !== ev.mediaId || ('status' in e) !== ('status' in ev));
  nueva.push(ev);
  await chrome.storage.local.set({cola: nueva.slice(-200)});
}

function quitarDeCola(ids, reintentar = []) { return enOrden(() => _quitarDeCola(ids, reintentar)); }
async function _quitarDeCola(ids, reintentar) {
  const {cola = []} = await chrome.storage.local.get('cola');
  const r = new Set(reintentar);
  await chrome.storage.local.set({cola: cola
    .filter(e => !ids.has(e.id) || r.has(e.id))
    .map(e => r.has(e.id) ? Object.assign(e, {intentos: (e.intentos || 0) + 1}) : e)
    .filter(e => (e.intentos || 0) < MAX_INTENTOS)});
}

async function apuntarFallo(ev, motivo) {
  const {fallos = []} = await chrome.storage.local.get('fallos');
  fallos.unshift({cuando: Date.now(), titulo: ev.titulo || ev.slug || ('#' + ev.mediaId),
                  episodio: ev.episode, motivo});
  await chrome.storage.local.set({fallos: fallos.slice(0, 5)});
}

let enviando = null;
function enviarCola() {
  // Si ya se está enviando, se encadena otra vuelta (no se descarta la petición).
  enviando = (enviando || Promise.resolve()).then(enviarUnaVez).catch(() => {});
  return enviando;
}

async function enviarUnaVez() {
  const {cola = []} = await chrome.storage.local.get('cola');
  if (!cola.length) return;
  const base = `http://127.0.0.1:${await puerto()}`;
  const hechos = new Set(), reintentar = [];
  for (const ev of cola) {
    const {id, cuando, intentos, ...cuerpo} = ev;
    let r;
    try {
      r = await fetch(base + '/api/animeav1/evento', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Miraru-Extension': '1'},
        body: JSON.stringify(cuerpo),
      });
    } catch (_) {
      await marcar('!', '#dc2626', 'Miraru está cerrado: se apuntará cuando lo abras');
      break;                       // Miraru cerrado: todo sigue en la cola
    }
    hechos.add(id);
    const d = await r.json().catch(() => ({}));
    if (r.ok) {
      const ultimo = {cuando: Date.now(), nombre: d.nombre || '', episodio: d.episodios_vistos,
        accion: d.accion || '', estado: d.estado || '', imagen: d.imagen || '', capitulos: d.capitulos || ''};
      const {historial = []} = await chrome.storage.local.get('historial');
      await chrome.storage.local.set({ultimo, historial: [ultimo, ...historial.filter(h =>
        !(h.nombre === ultimo.nombre && h.episodio === ultimo.episodio))].slice(0, 8)});
      await marcar('✓', '#16a34a', `Apuntado en Miraru: ${d.nombre || ''}`);
    } else if (r.status >= 500) {
      reintentar.push(id);         // fallo pasajero (AnimeAV1 o AniList no contestan)
    } else {
      // 4xx: no tiene arreglo reintentando. Se avisa en la ventana de la extensión.
      await apuntarFallo(ev, d.detail || ('Error ' + r.status));
      await marcar('?', '#d97706', 'No se pudo apuntar: ' + (d.detail || r.status));
    }
  }
  if (hechos.size) await quitarDeCola(hechos, reintentar);
}

let ultimaMarca = 0;
async function marcar(texto, color, titulo) {
  const yo = ++ultimaMarca;
  try {
    await chrome.action.setBadgeBackgroundColor({color});
    await chrome.action.setBadgeText({text: texto});
    await chrome.action.setTitle({title: 'Miraru × AnimeAV1 — ' + titulo});
    // El ✓ se borra solo; un aviso posterior (! o ?) no lo borra este temporizador.
    if (texto === '✓') setTimeout(() => { if (yo === ultimaMarca) chrome.action.setBadgeText({text: ''}); }, 4000);
  } catch (_) { /* nada */ }
}

// ── v1.4: tus listas de AnimeAV1 («Mis Listas») también van a Miraru ────────
// Se leen con la sesión de tu navegador (como al entrar en «Mis Listas») y se
// mandan a Miraru, que añade lo que falta sin repetir nada y nunca baja tu
// progreso. Solo si han cambiado desde la última vez.
const URL_MIS_LISTAS = 'https://animeav1.com/cuenta/listas/__data.json';

async function huella(texto) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(texto));
  return Array.from(new Uint8Array(h).slice(0, 12)).map(b => b.toString(16).padStart(2, '0')).join('');
}

async function sincronizarListas(forzar = false) {
  const guardar = estado => chrome.storage.local.set({listas: Object.assign({cuando: Date.now()}, estado)});
  let texto;
  try {
    const r = await fetch(URL_MIS_LISTAS, {credentials: 'include', cache: 'no-store'});
    if (r.status === 401 || r.status === 403) { await guardar({estado: 'sin-sesion'}); return 'sin-sesion'; }
    if (!r.ok) { await guardar({estado: 'error', detalle: 'AnimeAV1 ' + r.status}); return 'error'; }
    texto = await r.text();
    const j = JSON.parse(texto);
    const malo = j.type === 'error' || j.type === 'redirect' || (j.nodes || []).some(n => n && n.type === 'error');
    if (malo) { await guardar({estado: 'sin-sesion'}); return 'sin-sesion'; }
  } catch (_) { await guardar({estado: 'error', detalle: 'AnimeAV1 no responde'}); return 'error'; }
  const h = await huella(texto);
  const {listasHuella} = await chrome.storage.local.get('listasHuella');
  if (!forzar && h === listasHuella) { await guardar({estado: 'al-dia'}); return 'al-dia'; }
  try {
    const r = await fetch(`http://127.0.0.1:${await puerto()}/api/animeav1/listas`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Miraru-Extension': '1'},
      body: JSON.stringify({datos: JSON.parse(texto)}),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { await guardar({estado: 'error', detalle: d.detail || ('Miraru ' + r.status)}); return 'error'; }
    await chrome.storage.local.set({listasHuella: h});
    await guardar({estado: 'enviado', total: d.total || 0});
    return 'enviado';
  } catch (_) {
    await guardar({estado: 'miraru-cerrado'});      // se reintenta en la próxima vuelta
    return 'miraru-cerrado';
  }
}

chrome.alarms.create('reintentar', {periodInMinutes: 1});
chrome.alarms.create('listas', {periodInMinutes: 180, delayInMinutes: 1});

// Al instalarla: la guía de bienvenida (comprueba sola que todo está listo).
chrome.runtime.onInstalled.addListener(({reason}) => {
  if (reason === 'install') chrome.tabs.create({url: chrome.runtime.getURL('bienvenida.html')});
  sincronizarListas();
});
chrome.alarms.onAlarm.addListener(a => {
  if (a.name === 'reintentar') enviarCola();
  if (a.name === 'listas') sincronizarListas();
});
chrome.runtime.onStartup.addListener(() => { enviarCola(); sincronizarListas(); });
chrome.runtime.onMessage.addListener((msg, _s, responder) => {
  if (msg === 'reintentar') enviarCola().then(() => responder(true));
  else if (msg === 'listas') sincronizarListas(true).then(responder);
  return true;
});
