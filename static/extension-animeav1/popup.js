const $ = id => document.getElementById(id);

function hace(ms) {
  const s = Math.round((Date.now() - ms) / 1000);
  if (s < 60) return 'hace un momento';
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return new Date(ms).toLocaleDateString();
}

async function pintar() {
  const {puerto = 8765, ultimo, cola = []} = await chrome.storage.local.get(['puerto', 'ultimo', 'cola']);
  $('puerto').value = puerto;
  const base = `http://127.0.0.1:${puerto}`;
  $('abrir').href = base + '/app';

  const caja = $('estado');
  try {
    const r = await fetch(base + '/api/health', {cache: 'no-store'});
    const d = await r.json();
    caja.className = 'estado ok';
    $('estado-txt').textContent = `Conectado con Miraru ${d.version || ''}`;
  } catch (_) {
    caja.className = 'estado mal';
    $('estado-txt').textContent = 'Miraru está cerrado. Ábrelo y lo pendiente se apuntará solo.';
  }

  if (ultimo && ultimo.nombre) {
    const que = ultimo.accion === 'añadido' ? 'Añadido a tu lista' : 'Apuntado';
    const ep = ultimo.episodio != null ? ` · episodio ${ultimo.episodio}` : '';
    $('ultimo').innerHTML = '';
    const t = document.createElement('div');
    t.textContent = `✓ ${que}: ${ultimo.nombre}${ep}`;
    const g = document.createElement('div');
    g.className = 'gris';
    g.textContent = hace(ultimo.cuando);
    $('ultimo').append(t, g);
  }
  $('cola').textContent = cola.length ? `${cola.length} pendiente(s) de enviar a Miraru` : '';
  $('reintentar').hidden = !cola.length;
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
pintar();
