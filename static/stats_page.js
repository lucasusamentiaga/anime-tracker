let TR = {};
function T(k, vars={}) {
  let txt = TR[k] || k;
  Object.entries(vars).forEach(([key,val]) => { txt = txt.replace(`{${key}}`, val); });
  return txt;
}

function _thumbUrl(url) { return url ? url.replace('/cover/large/', '/cover/medium/') : ''; }

const COLORS = ['#7c3aed','#059669','#d97706','#dc2626','#0891b2','#9333ea','#65a30d'];

function makeBar(label, value, max, color) {
  const pct = max > 0 ? Math.round(value / max * 100) : 0;
  return `<div class="bar-row">
    <span class="bar-label" title="${label}">${label}</span>
    <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
    <span class="bar-count">${value}</span>
  </div>`;
}

function makeAnimeRow(a, showScore=false) {
  // DOM-safe: no innerHTML with user data
  const row = document.createElement('div');
  row.className = 'anime-row';

  const img = document.createElement('img');
  // src="" haría que el navegador se bajase esta misma página como imagen.
  if (a.imagen) { img.src = _thumbUrl(a.imagen); img.loading = 'lazy'; }
  else { img.style.display = 'none'; }
  img.alt = '';
  img.onerror = () => { img.style.display='none'; };
  row.appendChild(img);

  const info = document.createElement('div');
  info.className = 'info';
  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = a.nombre || '';
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = a.fuente || '';
  info.appendChild(name);
  info.appendChild(meta);
  row.appendChild(info);

  if (showScore && a.puntuacion) {
    const sc = document.createElement('span');
    sc.className = 'score-badge';
    sc.textContent = '⭐ ' + a.puntuacion;
    row.appendChild(sc);
  }
  return row;
}

function renderDonut(container, items) {
  const total = items.reduce((s,i) => s + i.value, 0);
  if (!total) { container.innerHTML = ''; return; }

  const SVG = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'donut-svg');
  svg.setAttribute('viewBox', '0 0 100 100');

  const bg = document.createElementNS(SVG, 'circle');
  bg.setAttribute('class', 'donut-bg');
  bg.setAttribute('cx', '50'); bg.setAttribute('cy', '50'); bg.setAttribute('r', '40');
  svg.appendChild(bg);

  const C = 2 * Math.PI * 40;
  let offset = 0;
  items.forEach(it => {
    const len = (it.value / total) * C;
    const seg = document.createElementNS(SVG, 'circle');
    seg.setAttribute('class', 'donut-seg');
    seg.setAttribute('cx', '50'); seg.setAttribute('cy', '50'); seg.setAttribute('r', '40');
    seg.setAttribute('stroke', it.color);
    seg.setAttribute('stroke-dasharray', `${len} ${C - len}`);
    seg.setAttribute('stroke-dashoffset', -offset);
    seg.setAttribute('transform', 'rotate(-90 50 50)');
    seg.setAttribute('stroke-linecap', 'butt');
    svg.appendChild(seg);
    offset += len;
  });

  // Center text
  const ct = document.createElementNS(SVG, 'text');
  ct.setAttribute('class', 'donut-center');
  ct.setAttribute('x', '50'); ct.setAttribute('y', '47');
  ct.textContent = total;
  svg.appendChild(ct);
  const cs = document.createElementNS(SVG, 'text');
  cs.setAttribute('class', 'donut-center-sub');
  cs.setAttribute('x', '50'); cs.setAttribute('y', '60');
  cs.textContent = 'TOTAL';
  svg.appendChild(cs);

  // Legend
  const legend = document.createElement('div');
  legend.className = 'donut-legend';
  items.forEach(it => {
    const row = document.createElement('div');
    row.className = 'donut-legend-item';
    const sw = document.createElement('span'); sw.className = 'swatch'; sw.style.background = it.color;
    const lb = document.createElement('span'); lb.className = 'lbl'; lb.textContent = it.label;
    const pc = document.createElement('span'); pc.className = 'pct';
    pc.textContent = Math.round(it.value / total * 100) + '% (' + it.value + ')';
    row.appendChild(sw); row.appendChild(lb); row.appendChild(pc);
    legend.appendChild(row);
  });

  container.innerHTML = '';
  container.appendChild(svg);
  container.appendChild(legend);
}

async function loadStats() {
  // Idioma
  const lr = await fetch('/api/lang');
  const ld = await lr.json();
  TR = ld.translations || {};

  // Aplicar textos
  document.getElementById('h-stats').textContent    = T('stats_title');
  document.getElementById('lbl-total').textContent  = T('total_animes');
  document.getElementById('lbl-eps').textContent    = T('total_episodes');
  document.getElementById('lbl-score').textContent  = T('avg_score');
  document.getElementById('lbl-genre').textContent  = T('favorite_genre');
  const lblHours = document.getElementById('lbl-hours');
  if (lblHours) lblHours.textContent = T('hours_watched') || 'Horas vistas';
  const lblComp = document.getElementById('lbl-completed');
  if (lblComp) lblComp.textContent = T('completed_count') || 'Completados';
  document.getElementById('lbl-by-state').textContent = T('by_state');
  document.getElementById('lbl-by-src').textContent   = T('by_source');
  document.getElementById('lbl-genres').textContent   = T('genres');
  document.getElementById('lbl-top').textContent      = T('top_rated');
  document.getElementById('lbl-recent').textContent   = T('recently_added');
  // Por id, no por '.back-btn': querySelector coge el PRIMERO con esa clase y
  // desde que existe el botón de compartir ese es el de compartir, no el de
  // volver. Le reescribía la etiqueta a "Cerrar" dejando el href de descarga,
  // así que pulsarlo bajaba un .html en lugar de volver a la lista.
  document.getElementById('btn-volver').textContent = '← ' + T('close');

  // Restore saved theme
  try { if (localStorage.getItem('theme') === 'light') document.documentElement.dataset.theme = 'light'; } catch(_) {}

  const r = await fetch('/api/stats');
  const d = await r.json();

  document.getElementById('k-total').textContent = d.total || 0;
  document.getElementById('k-eps').textContent   = d.total_episodes || 0;
  document.getElementById('k-score').textContent = d.avg_score || '–';
  document.getElementById('k-genre').textContent = d.favorite_genre || '–';

  // Horas vistas: usar el cálculo exacto del backend (incluye películas) si está
  const horas = (d.total_hours != null)
    ? Math.round(d.total_hours)
    : Math.round((d.total_episodes || 0) * 24 / 60);
  document.getElementById('k-hours').textContent = horas;

  // Completados
  const completados = (d.by_state || {}).completado || (d.by_state || {}).completed || 0;
  document.getElementById('k-completed').textContent = completados;

  // Estado — donut chart
  const stateKeys = {
    'pendiente': T('pending'), 'pending': T('pending'),
    'viendo': T('watching'),   'watching': T('watching'),
    'completado': T('completed'), 'completed': T('completed'),
    'abandonado': T('dropped'),   'dropped': T('dropped'),
    'pausa': T('paused'),         'paused': T('paused'),
  };
  const stateEntries = Object.entries(d.by_state || {});
  const stateContainer = document.getElementById('chart-state');
  if (!stateEntries.length) {
    stateContainer.innerHTML = '<div class="empty-state"><div class="icon">📊</div>Sin datos aún</div>';
  } else {
    renderDonut(stateContainer, stateEntries.map(([k,v],i) => ({
      label: stateKeys[k] || k, value: v, color: COLORS[i % COLORS.length],
    })));
  }

  // Fuente
  const srcEntries = Object.entries(d.by_source || {});
  const maxSrc = srcEntries.length ? Math.max(...srcEntries.map(([,v])=>v)) : 1;
  document.getElementById('chart-src').innerHTML = srcEntries.length
    ? srcEntries.map(([k,v],i) => makeBar(k, v, maxSrc, COLORS[i%COLORS.length])).join('')
    : '<p style="color:var(--muted);font-size:13px">Sin datos aún</p>';

  // Géneros — pills coloridas
  const genreEntries = Object.entries(d.genres || {}).sort((a,b) => b[1]-a[1]);
  const genreCloud = document.getElementById('chart-genres');
  genreCloud.innerHTML = '';
  if (!genreEntries.length) {
    genreCloud.innerHTML = '<div class="empty-state"><div class="icon">🎭</div>Sin géneros aún</div>';
  } else {
    genreEntries.slice(0, 20).forEach(([g, count]) => {
      const pill = document.createElement('span');
      pill.className = 'genre-pill';
      const txt = document.createTextNode(g + ' ');
      const cnt = document.createElement('span');
      cnt.className = 'count';
      cnt.textContent = '×' + count;
      pill.appendChild(txt);
      pill.appendChild(cnt);
      genreCloud.appendChild(pill);
    });
  }

  // Top
  // Top rated
  const listTop = document.getElementById('list-top');
  listTop.innerHTML = '';
  if (d.top_rated && d.top_rated.length) {
    d.top_rated.forEach(a => listTop.appendChild(makeAnimeRow(a, true)));
  } else {
    const p = document.createElement('p');
    p.style.cssText = 'color:var(--muted);font-size:13px';
    p.textContent = 'Sin datos aún';
    listTop.appendChild(p);
  }

  // Recientes
  const listRecent = document.getElementById('list-recent');
  listRecent.innerHTML = '';
  if (d.recently_added && d.recently_added.length) {
    d.recently_added.forEach(a => listRecent.appendChild(makeAnimeRow(a)));
  } else {
    const p = document.createElement('p');
    p.style.cssText = 'color:var(--muted);font-size:13px';
    p.textContent = 'Sin datos aún';
    listRecent.appendChild(p);
  }
}

// `loadStats` no tenía try/catch: si /api/stats fallaba (servidor reiniciándose,
// un corte de red), la excepción abortaba la función a medias y la página se
// quedaba con guiones en todos los indicadores, para siempre y sin decir por
// qué. Ahora el fallo se ve y se puede reintentar.
async function arrancarStats() {
  try {
    await loadStats();
  } catch (e) {
    const aviso = document.createElement('div');
    aviso.style.cssText = 'background:var(--card);border:1px solid var(--border);'
      + 'border-radius:12px;padding:18px;margin-bottom:18px;text-align:center';
    const txt = document.createElement('div');
    txt.style.cssText = 'color:var(--muted);font-size:13px;margin-bottom:10px';
    txt.textContent = 'No se pudieron cargar las estadísticas. '
      + (e && e.message ? '(' + e.message + ')' : '');
    const btn = document.createElement('button');
    btn.className = 'back-btn';
    btn.textContent = '↻ Reintentar';
    btn.onclick = () => { aviso.remove(); arrancarStats(); };
    aviso.appendChild(txt);
    aviso.appendChild(btn);
    const main = document.querySelector('main');
    if (main) main.prepend(aviso);
  }
}

arrancarStats();

// v2.4: tiempo hasta completar — derivado de ep_log (primer vs último visionado)
async function loadCompletion() {
  const sec = document.getElementById('completion-section');
  const list = document.getElementById('list-completion');
  if (!sec || !list) return;
  const lbl = document.getElementById('lbl-completion');
  if (lbl) lbl.textContent = '⏱ ' + (TR.completion_title || 'Tiempo hasta completar');
  try {
    const r = await fetch('/api/stats/completion');
    if (!r.ok) return;
    const d = await r.json();
    const items = d.animes || [];
    if (!items.length) return;       // sin datos → la sección queda oculta
    list.innerHTML = '';
    items.forEach(a => {
      const row = document.createElement('div');
      row.className = 'anime-row';
      const img = document.createElement('img');
      // src="" haría que el navegador se bajase esta misma página como imagen.
      if (a.imagen) { img.src = _thumbUrl(a.imagen); img.loading = 'lazy'; }
      else { img.style.display = 'none'; }
      img.alt = '';
      img.onerror = () => { img.style.display = 'none'; };
      row.appendChild(img);
      const info = document.createElement('div');
      info.className = 'info';
      const name = document.createElement('div');
      name.className = 'name';
      name.textContent = a.nombre || '';
      const meta = document.createElement('div');
      meta.className = 'meta';
      const dias = a.dias || 0;
      const span = dias === 0 ? 'en 1 día' : (dias === 1 ? '1 día' : dias + ' días');
      meta.textContent = a.episodios + ' eps · ' + span;
      info.appendChild(name);
      info.appendChild(meta);
      row.appendChild(info);
      const badge = document.createElement('span');
      badge.className = 'score-badge';
      badge.textContent = dias === 0 ? '⚡' : '📅 ' + dias + 'd';
      row.appendChild(badge);
      list.appendChild(row);
    });
    sec.style.display = 'block';
  } catch(_) {}
}
loadCompletion();

// v2.2: Heatmap de actividad estilo GitHub contributions
async function loadHeatmap() {
  const wrap = document.getElementById('heatmap');
  const empty = document.getElementById('heatmap-empty');
  if (!wrap) return;
  try {
    const [hmRes, stRes] = await Promise.all([
      fetch('/api/heatmap?dias=365'),
      fetch('/api/streak'),
    ]);
    const hm = await hmRes.json();
    const st = await stRes.json();

    document.getElementById('streak-actual').textContent = (st.actual || 0) + ' días';
    document.getElementById('streak-max').textContent    = (st.max    || 0) + ' días';
    document.getElementById('heatmap-total').textContent = (hm.total  || 0);

    if (!hm.dias || hm.dias.length === 0) {
      wrap.style.display = 'none';
      empty.style.display = 'block';
      return;
    }

    // Construir 53 semanas x 7 días terminando hoy
    const byDate = Object.fromEntries(hm.dias.map(d => [d.fecha, d.count]));
    const today = new Date();
    today.setHours(0,0,0,0);
    // Buscar el sábado anterior o el día actual (semana terminada)
    const end = new Date(today);
    // Empezamos 52 semanas (364 días) atrás
    const start = new Date(today); start.setDate(start.getDate() - 363);
    // Alinear start al lunes
    while (start.getDay() !== 1) start.setDate(start.getDate() - 1);

    // Calcular máximo para escalar colores
    const maxCount = Math.max(1, ...Object.values(byDate));

    // El heatmap usa el color de acento elegido en Apariencia (customize.js fija
    // --accent-rgb). Antes era violeta fijo e ignoraba la personalización.
    const ACC = (getComputedStyle(document.documentElement)
                  .getPropertyValue('--accent-rgb').trim()) || '124,58,237';
    function colorFor(c) {
      if (!c) return `rgba(${ACC},.06)`;
      const lvl = Math.ceil((c / maxCount) * 4);
      const opacities = [0.22, 0.45, 0.68, 0.95];
      return `rgba(${ACC},${opacities[Math.min(lvl, 4) - 1]})`;
    }

    // Generar SVG (escala mejor que divs)
    const CELL = 12, GAP = 3, OFFSET_LEFT = 28, OFFSET_TOP = 18;
    const weeks = [];
    let curWeek = [];
    let cursor = new Date(start);
    while (cursor <= end) {
      curWeek.push(new Date(cursor));
      if (curWeek.length === 7) { weeks.push(curWeek); curWeek = []; }
      cursor.setDate(cursor.getDate() + 1);
    }
    if (curWeek.length) weeks.push(curWeek);

    const w = OFFSET_LEFT + weeks.length * (CELL + GAP);
    const h = OFFSET_TOP + 7 * (CELL + GAP);
    let svg = `<svg width="${w}" height="${h}" style="display:block">`;

    // Etiquetas de mes (solo cuando el mes cambia)
    let lastMonth = -1;
    weeks.forEach((wk, wi) => {
      const m = wk[0].getMonth();
      if (m !== lastMonth) {
        const lbl = wk[0].toLocaleDateString(undefined, {month: 'short'});
        svg += `<text x="${OFFSET_LEFT + wi*(CELL+GAP)}" y="12" font-size="10" fill="#6b6b88">${lbl}</text>`;
        lastMonth = m;
      }
    });

    // Etiquetas de día de la semana (lun, mié, vie)
    ['L','','M','','V','',''].forEach((d, i) => {
      if (d) svg += `<text x="0" y="${OFFSET_TOP + i*(CELL+GAP) + 10}" font-size="9" fill="#6b6b88">${d}</text>`;
    });

    // v2.2 fix: usar fecha LOCAL, no UTC. `toISOString()` da fecha en UTC,
    // y la BD guarda con `datetime('now')` en hora local → mismatch entre
    // los rects pintados y las fechas reales.
    const localISO = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const da = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${da}`;
    };

    // Celdas
    weeks.forEach((wk, wi) => {
      wk.forEach((day, di) => {
        const iso = localISO(day);
        const c = byDate[iso] || 0;
        const future = day > today;
        const fill = future ? 'transparent' : colorFor(c);
        const title = future
          ? iso
          : (c === 1 ? `${iso}: 1 episodio` : `${iso}: ${c} episodios`);
        svg += `<rect x="${OFFSET_LEFT + wi*(CELL+GAP)}" y="${OFFSET_TOP + di*(CELL+GAP)}" `
             + `width="${CELL}" height="${CELL}" rx="2" fill="${fill}">`
             + `<title>${title}</title></rect>`;
      });
    });

    svg += '</svg>';
    wrap.innerHTML = svg;
    empty.style.display = 'none';
  } catch(e) {
    console.warn('heatmap:', e);
  }
}
loadHeatmap();

// v2.3: exportar "Mi año en anime" como imagen PNG via Canvas
// — sin libs externas. Datos vienen de /api/stats/wrapped (ya existe).
async function exportarWrapped() {
  const btn = event && event.target;
  if (btn) btn.disabled = true;
  try {
    // v2.3: el wrapped ahora filtra por año actual (usa ep_log)
    const yr = new Date().getFullYear();
    const r = await fetch('/api/stats/wrapped?year=' + yr);
    if (!r.ok) throw new Error('No data');
    const d = await r.json();

    const W = 1080, H = 1080;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');

    // Fondo: gradiente morado oscuro
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, '#1e1a30');
    bg.addColorStop(1, '#0a0814');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // Halo decorativo — con el color de acento elegido por el usuario
    const ACC = (getComputedStyle(document.documentElement)
                  .getPropertyValue('--accent-rgb').trim()) || '124,58,237';
    const halo = ctx.createRadialGradient(W/2, 200, 0, W/2, 200, 500);
    halo.addColorStop(0, `rgba(${ACC},.35)`);
    halo.addColorStop(1, `rgba(${ACC},0)`);
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, W, 600);

    // Título (la tarjeta compartible seguía con la marca antigua)
    ctx.fillStyle = `rgba(${ACC},1)`;
    ctx.font = '700 28px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('MIRARU', W/2, 100);

    ctx.fillStyle = '#fff';
    ctx.font = '800 64px "Segoe UI", system-ui, sans-serif';
    ctx.fillText('Mi año en anime', W/2, 200);

    const year = new Date().getFullYear();
    ctx.fillStyle = 'rgba(255,255,255,.5)';
    ctx.font = '400 22px "Segoe UI", system-ui, sans-serif';
    ctx.fillText(String(year), W/2, 240);

    // Stats principales
    const bigStat = (x, y, value, label) => {
      ctx.fillStyle = `rgba(${ACC},1)`;
      ctx.font = '800 86px "Segoe UI", system-ui, sans-serif';
      ctx.fillText(String(value), x, y);
      ctx.fillStyle = 'rgba(255,255,255,.65)';
      ctx.font = '500 18px "Segoe UI", system-ui, sans-serif';
      ctx.fillText(label, x, y + 36);
    };
    bigStat(W*0.20, 380, d.total_animes    || 0, 'Animes');
    bigStat(W*0.50, 380, d.total_episodios || 0, 'Episodios');
    // v2.3: horas con 1 decimal explícito (antes mostraba "0" feo cuando era 0.0)
    const horas = Number(d.horas_estimadas || 0);
    bigStat(W*0.80, 380, horas.toFixed(1).replace('.0', ''), 'Horas');

    // Top géneros (barras)
    const tg = d.top_generos || [];
    ctx.textAlign = 'left';
    ctx.fillStyle = '#fff';
    ctx.font = '700 26px "Segoe UI", system-ui, sans-serif';
    ctx.fillText('Tus géneros favoritos', 80, 540);
    const maxCount = Math.max(1, ...tg.map(g => g.count));
    tg.slice(0, 5).forEach((g, i) => {
      const y = 580 + i * 50;
      ctx.fillStyle = 'rgba(255,255,255,.85)';
      ctx.font = '600 18px "Segoe UI", system-ui, sans-serif';
      ctx.fillText(g.genero, 80, y + 22);
      // Barra
      const barX = 280, barW = W - 280 - 80, h = 22;
      ctx.fillStyle = `rgba(${ACC},.2)`;
      ctx.fillRect(barX, y + 4, barW, h);
      const fill = barW * (g.count / maxCount);
      const grad = ctx.createLinearGradient(barX, 0, barX + fill, 0);
      grad.addColorStop(0, `rgba(${ACC},.75)`);
      grad.addColorStop(1, `rgba(${ACC},1)`);
      ctx.fillStyle = grad;
      ctx.fillRect(barX, y + 4, fill, h);
      ctx.fillStyle = '#fff';
      ctx.font = '700 16px "Segoe UI", system-ui, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(String(g.count), W - 88, y + 22);
      ctx.textAlign = 'left';
    });

    // Top 5 mejor valorados
    const tv = d.mejor_valorados || [];
    ctx.fillStyle = '#fff';
    ctx.font = '700 26px "Segoe UI", system-ui, sans-serif';
    ctx.fillText('Mejor valorados', 80, 880);
    tv.slice(0, 3).forEach((a, i) => {
      const y = 920 + i * 36;
      ctx.fillStyle = '#fbbf24';
      ctx.font = '700 18px "Segoe UI", system-ui, sans-serif';
      ctx.fillText('★ ' + (a.puntuacion || 0).toFixed(1), 80, y);
      ctx.fillStyle = '#fff';
      ctx.font = '500 18px "Segoe UI", system-ui, sans-serif';
      const name = a.nombre.length > 50 ? a.nombre.slice(0, 47) + '…' : a.nombre;
      ctx.fillText(name, 180, y);
    });

    // Pie
    ctx.fillStyle = 'rgba(255,255,255,.3)';
    ctx.font = '400 14px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('github.com/lucasusamentiaga/anime-tracker', W/2, H - 40);

    // Descargar
    const link = document.createElement('a');
    link.download = `mi-año-en-anime-${year}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  } catch(e) {
    alert('No se pudo generar la imagen: ' + (e.message || 'error'));
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Gamificación: nivel + XP + racha de apertura + logros (idea de Brasa/Lumbre).
(async function loadGami(){
  // 1) registrar la apertura de hoy (racha diaria) — idempotente por día
  try { await fetch('/api/streak/checkin', {method:'POST'}); } catch(_){}
  // 2) pintar estado de gamificación
  try{
    const r = await fetch('/api/gamificacion');
    if(!r.ok) return;
    const d = await r.json();
    const gs = document.getElementById('gami-section');
    if(gs){
      const xp = d.xp || {};
      const lvl = d.nivel || 1;
      document.getElementById('gami-level').textContent = 'Nivel ' + lvl;
      document.getElementById('gami-xpbar').style.width = Math.round((xp.progreso||0)*100) + '%';
      document.getElementById('gami-xptext').textContent =
        (xp.xp||0) + ' XP · faltan ' + (xp.falta||0) + ' para nivel ' + (lvl+1);
      const os = (d.racha_apertura||{}).actual || 0;
      document.getElementById('gami-open-streak').textContent = '🔥 ' + os;
      gs.style.display = 'block';
    }
    // Rango ninja
    var rn = d.rango_ninja;
    if(rn){
      var rs = document.getElementById('rango-section');
      if(rs){
        document.getElementById('rango-img').src = '/static/emblems/'+rn.emblema+'.svg';
        document.getElementById('rango-nombre').textContent = rn.nombre;
        document.getElementById('rango-desc').textContent = rn.desc + ' — ' + rn.horas + 'h vistas';
        if(rn.siguiente){
          document.getElementById('rango-bar-wrap').style.display = 'block';
          document.getElementById('rango-bar').style.width = Math.round(rn.progreso*100)+'%';
          document.getElementById('rango-next').textContent =
            'Siguiente: '+rn.siguiente+' ('+rn.siguiente_umbral+'h)';
        }
        rs.style.display = 'block';
      }
    }
    const lg = d.logros || {};
    const grid = document.getElementById('logros-grid');
    const sec  = document.getElementById('logros-section');
    if(grid && sec){
      const cnt = document.getElementById('logros-count');
      if(cnt) cnt.textContent = (lg.desbloqueados||0) + '/' + (lg.total||0);
      // Emblemas conseguidos desde la última visita → se resaltan con un latido
      var vistos = [];
      try { vistos = (JSON.parse(localStorage.getItem('miraru_gami_seen')||'{}').ids) || []; } catch(_) {}
      grid.innerHTML = (lg.logros||[]).map(function(l){
        var nuevo = l.unlocked && vistos.length && vistos.indexOf(l.id) === -1;
        var dim = l.unlocked ? '' : 'opacity:.32;filter:grayscale(1)';
        var glow = l.unlocked ? 'filter:drop-shadow(0 4px 14px rgba(var(--accent-rgb),.5))' : '';
        var col = l.unlocked ? 'var(--light)' : 'var(--muted)';
        var estado = l.unlocked ? '✅' : '🔒';
        return '<div class="logro-item" style="'+dim+'">'
          + '<div class="logro-tip"><div class="tip-name">'+estado+' '+l.nombre+'</div>'
          + '<div class="tip-desc">'+l.desc+'</div></div>'
          + (nuevo ? '<span style="position:absolute;top:-3px;right:6px;background:var(--accent);color:#fff;'
                   + 'font-size:8px;font-weight:800;letter-spacing:.4px;border-radius:99px;padding:2px 6px;'
                   + 'box-shadow:var(--shadow-accent)">NUEVO</span>' : '')
          + '<img class="'+(nuevo?'emblem-new':'')+'" src="/static/emblems/'+l.emblema+'.svg" alt="" width="60" height="60" style="'+glow+'">'
          + '<div style="font-size:10px;margin-top:5px;color:'+col+';font-weight:600;line-height:1.2">'+l.nombre+'</div>'
          + '</div>';
      }).join('');
      sec.style.display = 'block';
    }
  }catch(_){}
})();
