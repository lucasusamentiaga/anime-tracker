// Guía de bienvenida: cada paso se comprueba solo y se pone en verde.
const $ = id => document.getElementById(id);

function poner(id, estado, texto) {
  const p = $(id);
  p.classList.remove('ok', 'mal', 'espera');
  p.classList.add(estado);
  p.querySelector('.estado').textContent = texto;
}

async function base() {
  const {puerto = 8765} = await chrome.storage.local.get('puerto');
  return `http://127.0.0.1:${puerto}`;
}

async function comprobarMiraru() {
  const b = await base();
  $('abrir-miraru').href = b + '/app';
  try {
    const r = await fetch(b + '/api/health', {cache: 'no-store'});
    const d = await r.json();
    poner('p-miraru', 'ok', `Conectado con Miraru ${d.version || ''}. Perfecto.`);
    $('abrir-miraru').textContent = 'Abrir Miraru';
  } catch (_) {
    poner('p-miraru', 'mal', 'No encuentro Miraru. Ábrelo en tu PC (como siempre) y esto se pondrá en verde solo.');
  }
}

async function comprobarAnimeAV1() {
  try {
    const r = await fetch('https://animeav1.com/cuenta/listas/__data.json', {credentials: 'include', cache: 'no-store'});
    if (r.status === 401 || r.status === 403) {
      poner('p-av1', 'mal', 'No has iniciado sesión. Entra en AnimeAV1 con tu cuenta (sin ella el botón «Marcar como visto» no guarda nada).');
      return;
    }
    const j = await r.json();
    const error = (j.nodes || []).some(n => n && n.type === 'error') || j.type === 'error' || j.type === 'redirect';
    if (!r.ok || error) {
      poner('p-av1', 'mal', 'No has iniciado sesión. Entra en AnimeAV1 con tu cuenta.');
    } else {
      poner('p-av1', 'ok', 'Sesión iniciada. Perfecto.');
    }
  } catch (_) {
    poner('p-av1', 'espera', 'No he podido comprobarlo. Si ya entras en AnimeAV1 con tu cuenta, está bien.');
  }
}

function pintarResultado(u) {
  if (!u || !u.nombre) return;
  $('resultado').hidden = false;
  $('r-nombre').textContent = u.nombre;
  const total = parseInt(u.capitulos, 10);
  $('r-ep').textContent = 'Episodio ' + (u.episodio ?? '?') + (total > 0 ? ' de ' + total : '');
  const fr = total > 0 ? Math.min(1, (u.episodio || 0) / total) : 1;
  requestAnimationFrame(() => requestAnimationFrame(() => { $('r-barra').style.transform = `scaleX(${fr})`; }));
  if (u.imagen) { $('r-portada').src = u.imagen; $('r-portada').hidden = false; } else { $('r-portada').hidden = true; }
  poner('p-prueba', 'ok', '¡Ya está! A partir de ahora, cada episodio que marques en AnimeAV1 aparecerá en Miraru.');
  document.body.classList.add('celebra');
}

comprobarMiraru();
comprobarAnimeAV1();
setInterval(comprobarMiraru, 3000);
setInterval(comprobarAnimeAV1, 8000);
// Si la prueba se hizo antes de abrir esta página, también cuenta.
chrome.storage.local.get('ultimo').then(({ultimo}) => pintarResultado(ultimo));
chrome.storage.onChanged.addListener((c, area) => {
  if (area === 'local' && c.ultimo) pintarResultado(c.ultimo.newValue);
});
