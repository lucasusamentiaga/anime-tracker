const $ = id => document.getElementById(id);

function hace(ms) {
  const s = Math.round((Date.now() - ms) / 1000);
  if (s < 60) return 'hace un momento';
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return new Date(ms).toLocaleDateString();
}

const limpiarTitulo = t => (t || '').replace(/\s*-\s*AnimeAV1\s*$/i, '').replace(/\s+Episodio\s+\d+.*$/i, '');

async function pintar() {
  const {puerto = 8765, ultimo, historial = [], cola = [], fallos = []} =
    await chrome.storage.local.get(['puerto', 'ultimo', 'historial', 'cola', 'fallos']);
  $('puerto').value = puerto;
  const base = `http://127.0.0.1:${puerto}`;
  $('abrir').href = base + '/app';

  let abierto = false;
  try {
    const r = await fetch(base + '/api/health', {cache: 'no-store'});
    const d = await r.json();
    abierto = true;
    $('pastilla').className = 'pastilla ok';
    $('pastilla-txt').textContent = 'Miraru ' + (d.version || '');
  } catch (_) {
    $('pastilla').className = 'pastilla mal';
    $('pastilla-txt').textContent = 'Cerrado';
  }
  $('cerrado').hidden = abierto;

  $('pendientes').hidden = !cola.length;
  $('pendientes').textContent = cola.length === 1
    ? '1 episodio esperando a Miraru: se apuntará al abrirlo.'
    : `${cola.length} episodios esperando a Miraru: se apuntarán al abrirlo.`;
  $('reintentar').hidden = !(cola.length && abierto);

  // Último fallo, solo si es más reciente que el último acierto.
  const f = fallos[0];
  const conFallo = f && (!ultimo || f.cuando > ultimo.cuando);
  $('fallo').hidden = !conFallo;
  if (conFallo) $('fallo').textContent = `⚠ No se pudo apuntar «${limpiarTitulo(f.titulo)}»: ${f.motivo}`;

  if (ultimo && ultimo.nombre) {
    $('vacio').hidden = true;
    $('ultimo').hidden = false;
    $('u-etq').textContent = ultimo.accion === 'añadido' ? '＋ Añadido a tu lista' :
      ultimo.estado === 'completado' ? '🏁 ¡Completado!' : '✓ Apuntado en Miraru';
    $('u-nombre').textContent = ultimo.nombre;
    const total = parseInt(ultimo.capitulos, 10);
    $('u-ep').textContent = 'Episodio ' + (ultimo.episodio ?? '?') + (total > 0 ? ' de ' + total : '');
    $('u-barra').style.width = total > 0 ? Math.min(100, Math.round((ultimo.episodio || 0) / total * 100)) + '%' : '100%';
    $('u-cuando').textContent = hace(ultimo.cuando);
    if (ultimo.imagen) { $('u-img').src = ultimo.imagen; $('u-img').hidden = false; } else $('u-img').hidden = true;
  }

  const antes = historial.slice(1, 5);
  $('hist').hidden = !antes.length;
  $('hist').querySelectorAll('div').forEach(d => d.remove());
  antes.forEach(h => {
    const fila = document.createElement('div');
    const a = document.createElement('span'); a.textContent = h.nombre;
    const b = document.createElement('span'); b.textContent = 'ep ' + (h.episodio ?? '?') + ' · ' + hace(h.cuando);
    fila.append(a, b);
    $('hist').appendChild(fila);
  });
}

$('puerto').addEventListener('change', async e => {
  const n = Number(e.target.value);
  if (n > 0 && n < 65536) await chrome.storage.local.set({puerto: n});
  pintar();
});
$('reintentar').addEventListener('click', async () => {
  await chrome.runtime.sendMessage('reintentar');
  pintar();
});
$('guia').addEventListener('click', () => chrome.tabs.create({url: chrome.runtime.getURL('bienvenida.html')}));
chrome.storage.onChanged.addListener((_c, area) => { if (area === 'local') pintar(); });
pintar();
