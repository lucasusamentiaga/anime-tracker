// Miraru × AnimeAV1 — copia a Miraru, al momento, los episodios que marcas
// como vistos en animeav1.com.
//
// Cómo: la web de AnimeAV1, al pulsar «Marcar como visto», hace
//   POST https://animeav1.com/api/user/library  {"mediaId": 123, "episode": 5}
// La extensión solo OBSERVA esa petición (no la toca ni lee nada más) y, si
// AnimeAV1 contesta bien, se lo cuenta a Miraru en tu PC (127.0.0.1:8765).
// Si Miraru está cerrado, lo guarda y lo manda en cuanto vuelva a abrirse.

const URL_LISTA = 'https://animeav1.com/api/user/library*';
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

chrome.webRequest.onBeforeRequest.addListener(details => {
  if (details.method !== 'POST') return;
  const cuerpo = leerCuerpo(details);
  if (cuerpo) pendientes.set(details.requestId, {cuerpo, tabId: details.tabId});
}, {urls: [URL_LISTA]}, ['requestBody']);

chrome.webRequest.onCompleted.addListener(async details => {
  const p = pendientes.get(details.requestId);
  pendientes.delete(details.requestId);
  if (!p || details.statusCode >= 400) return;
  const ev = {mediaId: Number(p.cuerpo.mediaId)};
  if ('episode' in p.cuerpo) ev.episode = p.cuerpo.episode == null ? 0 : Number(p.cuerpo.episode);
  if ('status' in p.cuerpo && p.cuerpo.status != null) ev.status = Number(p.cuerpo.status);
  if (!('episode' in ev) && !('status' in ev)) return;   // solo nota o puntuación
  try {
    const tab = p.tabId >= 0 ? await chrome.tabs.get(p.tabId) : null;
    const m = tab && tab.url ? tab.url.match(/animeav1\.com\/media\/([^/?#]+)/) : null;
    if (m) ev.slug = decodeURIComponent(m[1]);
    if (tab && tab.title) ev.titulo = tab.title.slice(0, 300);
  } catch (_) { /* la pestaña se cerró: Miraru lo resuelve por el id */ }
  await encolar(ev);
  await enviarCola();
}, {urls: [URL_LISTA]});

chrome.webRequest.onErrorOccurred.addListener(d => pendientes.delete(d.requestId), {urls: [URL_LISTA]});

// ── Cola: nada se pierde si Miraru está cerrado ─────────────────────────────
async function encolar(ev) {
  const {cola = []} = await chrome.storage.local.get('cola');
  // Del mismo anime solo importa lo último que hiciste.
  const nueva = cola.filter(e => e.mediaId !== ev.mediaId || ('status' in e) !== ('status' in ev));
  nueva.push(Object.assign({cuando: Date.now()}, ev));
  await chrome.storage.local.set({cola: nueva.slice(-200)});
}

let enviando = false;
async function enviarCola() {
  if (enviando) return;
  enviando = true;
  try {
    const {cola = []} = await chrome.storage.local.get('cola');
    if (!cola.length) return;
    const base = `http://127.0.0.1:${await puerto()}`;
    const quedan = [];
    for (let i = 0; i < cola.length; i++) {
      const ev = cola[i];
      let r;
      try {
        r = await fetch(base + '/api/animeav1/evento', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Miraru-Extension': '1'},
          body: JSON.stringify(ev),
        });
      } catch (_) {
        // Miraru cerrado: se reintenta luego (alarma cada minuto).
        quedan.push(...cola.slice(i));
        await marcar('!', '#dc2626', 'Miraru está cerrado: se apuntará cuando lo abras');
        break;
      }
      if (r.ok) {
        const d = await r.json().catch(() => ({}));
        await chrome.storage.local.set({ultimo: {cuando: Date.now(), nombre: d.nombre || '',
          episodio: d.episodios_vistos, accion: d.accion || ''}});
        await marcar('✓', '#16a34a', `Apuntado en Miraru: ${d.nombre || ''}`);
      } else if (r.status >= 500 || r.status === 502) {
        quedan.push(ev);           // fallo pasajero: se reintenta
      }
      // 4xx (no encontrado, datos raros): se descarta, no tiene arreglo reintentando
    }
    await chrome.storage.local.set({cola: quedan});
  } finally {
    enviando = false;
  }
}

async function marcar(texto, color, titulo) {
  try {
    await chrome.action.setBadgeBackgroundColor({color});
    await chrome.action.setBadgeText({text: texto});
    await chrome.action.setTitle({title: 'Miraru × AnimeAV1 — ' + titulo});
    if (texto === '✓') setTimeout(() => chrome.action.setBadgeText({text: ''}), 4000);
  } catch (_) { /* nada */ }
}

chrome.alarms.create('reintentar', {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'reintentar') enviarCola(); });
chrome.runtime.onStartup.addListener(enviarCola);
chrome.runtime.onMessage.addListener((msg, _s, responder) => {
  if (msg === 'reintentar') enviarCola().then(() => responder(true));
  return true;
});
