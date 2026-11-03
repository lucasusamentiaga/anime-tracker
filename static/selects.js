/* Miraru — desplegables visuales (v2.16).
   Sustituye el aspecto de los <select> de la barra de filtros por un menú
   propio (más grande, con iconos, marca del elegido y teclado completo).
   El <select> de verdad sigue ahí, oculto: el resto del código lo lee y lo
   cambia como siempre (incluido `sel.value = …`), y este menú se entera. */
(function () {
  'use strict';
  if (window.__miraruSelects) return;
  window.__miraruSelects = true;

  var TITULOS = {
    'f-sort': 'Ordenar por', 'f-estado': 'Estado', 'f-fuente': 'Fuente', 'f-lista': 'Lista',
    'f-tipo': 'Tipo', 'inp-tipo': 'Qué buscas', 'inp-fuente': 'Buscar en',
    'edit-estado': 'Estado', 'edit-lista': 'Lista', 'lang-sel': 'Idioma', 'qv-animo': '¿Cómo te sientes?',
    'bulk-estado': 'Cambiar estado', 'bulk-lista': 'Mover a la lista', 'sort-by': 'Ordenar por',
    'filter-estado': 'Estado', 'sel-fuente': 'Fuente'
  };

  // Icono para las opciones que lo pierden al traducirse (el texto lo pone T()).
  var ICONOS = {
    'f-sort': {date: '🕐', name: '🔤', score: '⭐', progress: '📊', inicio: '📅', fin: '🏁', favs: '💛'},
    'f-estado': {'': '📋'},
    'f-tipo': {'': '🗂️'},
    'f-fuente': {'': '🌐'},
    'f-lista': {'': '📂'}
  };
  function icono(sel, o) {
    var m = ICONOS[sel.id];
    return (m && m[o.value]) || (sel.id === 'f-fuente' || sel.id === 'inp-fuente' ? '🔗' : '');
  }

  var CSS = [
    '.msel{position:relative;display:inline-flex;flex:0 0 auto;min-width:0}',
    '.msel>select{position:absolute!important;inset:0;width:100%!important;height:100%!important;opacity:0!important;pointer-events:none!important}',
    '.msel-btn{display:inline-flex;align-items:center;gap:8px;height:34px;max-width:100%;padding:0 10px 0 12px;border-radius:10px;cursor:pointer;',
    ' background:var(--card2);border:1px solid var(--border);color:var(--fg);font:600 13px/1 Inter,system-ui,sans-serif;white-space:nowrap;',
    ' transition:border-color .18s,background .18s,box-shadow .18s}',
    '.msel-btn:hover{border-color:rgba(var(--accent-rgb,124,58,237),.55)}',
    '.msel-btn:focus-visible{outline:2px solid var(--light);outline-offset:2px}',
    '.msel-btn[aria-expanded=true]{border-color:var(--accent);box-shadow:0 0 0 3px rgba(var(--accent-rgb,124,58,237),.18)}',
    '.msel.activo .msel-btn{background:rgba(var(--accent-rgb,124,58,237),.14);border-color:rgba(var(--accent-rgb,124,58,237),.6);color:var(--fg)}',
    '.msel-txt{overflow:hidden;text-overflow:ellipsis;min-width:0}',
    /* Dentro de ventanas y formularios: a lo ancho, como un campo. */
    '.msel.ancho{display:flex;width:100%}',
    '.msel.ancho .msel-btn{width:100%;height:40px;justify-content:space-between;font-weight:500;font-size:14px}',
    '.msel.mini .msel-btn{height:28px;padding:0 6px 0 8px;font-size:11px;border-radius:7px;gap:4px}',
    '.msel.mini .msel-chev{width:11px;height:11px}',
    '.msel-btn:disabled{opacity:.5;cursor:default}',
    '.msel-chev{flex-shrink:0;width:14px;height:14px;color:var(--muted);transition:transform .22s cubic-bezier(.22,1,.36,1)}',
    '.msel-btn[aria-expanded=true] .msel-chev{transform:rotate(180deg);color:var(--light)}',
    '.msel-pan{position:fixed;z-index:var(--z-menu,1300);min-width:200px;max-width:min(340px,calc(100vw - 16px));max-height:min(360px,70vh);overflow-y:auto;',
    ' padding:6px;border-radius:14px;background:var(--card);border:1px solid var(--border);',
    ' box-shadow:0 8px 8px -6px rgba(0,0,0,.45);',
    ' transform-origin:var(--origen,top left);animation:msel-in .18s cubic-bezier(.22,1,.36,1) both;overscroll-behavior:contain}',
    '.msel-pan.arriba{--origen:bottom left}',
    '.msel-tit{padding:8px 10px 6px;font:600 12.5px Inter,system-ui,sans-serif;color:var(--muted)}',
    '.msel-op{display:flex;align-items:center;gap:10px;min-height:38px;padding:0 10px;border-radius:9px;cursor:pointer;',
    ' font:500 14px Inter,system-ui,sans-serif;color:var(--fg);transition:background .12s}',
    '.msel-op .ico{width:22px;text-align:center;font-size:16px;flex-shrink:0;font-family:"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif}',
    '.msel-op .tx{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.msel-op .ok{width:16px;height:16px;flex-shrink:0;color:var(--light);opacity:0}',
    '.msel-op[aria-selected=true]{font-weight:700;color:var(--light)}',
    '.msel-op[aria-selected=true] .ok{opacity:1}',
    '.msel-op.foco{background:rgba(var(--accent-rgb,124,58,237),.16)}',
    '.msel-op[aria-disabled=true]{opacity:.45;cursor:default}',
    '@keyframes msel-in{from{opacity:0;transform:translateY(-4px) scale(.97)}}',
    '.msel-pan.arriba{animation-name:msel-in-up}',
    '@keyframes msel-in-up{from{opacity:0;transform:translateY(4px) scale(.97)}}',
    '@media (prefers-reduced-motion:reduce){.msel-pan{animation:none}.msel-chev{transition:none}}',
    '[data-theme=light] .msel-pan{box-shadow:0 8px 8px -6px rgba(30,20,60,.18)}'
  ].join('\n');

  var CHEV = '<svg class="msel-chev" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>';
  var OK = '<svg class="ok" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
  var desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  var descIdx = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');
  var abierto = null;
  var uid = 0;

  // "📅 Fecha inicio" → ["📅", "Fecha inicio"]
  function partir(txt) {
    var m = /^\s*((?:\p{Extended_Pictographic}|\p{Emoji_Presentation})(?:️|‍(?:\p{Extended_Pictographic}|\p{Emoji_Presentation}))*)\s*(.*)$/u.exec(txt || '');
    return m ? [m[1], m[2]] : ['', (txt || '').trim()];
  }

  function mejorar(sel) {
    if (sel.__msel || !sel.parentNode) return;
    sel.__msel = true;
    var caja = document.createElement('span');
    caja.className = 'msel';
    if (sel.style.maxWidth) caja.style.maxWidth = sel.style.maxWidth;
    if (sel.style.flex) caja.style.flex = sel.style.flex;
    if (sel.style.minWidth) caja.style.minWidth = sel.style.minWidth;
    if (sel.classList.contains('lang-select')) caja.classList.add('mini');
    else if (!sel.closest('.toolbar, .bulk-bar, #bulk-bar') && !sel.classList.contains('bulk-select') &&
             !/^(sort-by|filter-estado)$/.test(sel.id)) caja.classList.add('ancho');
    if (sel.classList.contains('tb2-fija')) caja.classList.add('tb2-fija');
    sel.parentNode.insertBefore(caja, sel);
    caja.appendChild(sel);
    sel.tabIndex = -1;
    sel.setAttribute('aria-hidden', 'true');

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'msel-btn';
    btn.id = 'msel-' + (sel.id || ++uid);
    btn.setAttribute('aria-haspopup', 'listbox');
    btn.setAttribute('aria-expanded', 'false');
    var etiqueta = TITULOS[sel.id] || sel.getAttribute('aria-label') || sel.title || '';
    if (sel.title) btn.title = sel.title;
    btn.innerHTML = '<span class="msel-txt"></span>' + CHEV;
    caja.appendChild(btn);

    function pintar() {
      var op = sel.options[sel.selectedIndex];
      var t = op ? op.textContent.trim() : '';
      if (op && !partir(t)[0] && icono(sel, op)) t = icono(sel, op) + ' ' + t;
      btn.querySelector('.msel-txt').textContent = t;
      btn.setAttribute('aria-label', (etiqueta ? etiqueta + ': ' : '') + t);
      btn.disabled = !!sel.disabled;
      // Filtro aplicado (no es la primera opción "todos") → se resalta.
      caja.classList.toggle('activo', /^f-(estado|fuente|lista|tipo)$/.test(sel.id) && sel.selectedIndex > 0);
    }
    sel.__mselPintar = pintar;

    // `sel.value = x` desde el código no lanza eventos: se intercepta.
    try {
      Object.defineProperty(sel, 'value', {
        configurable: true,
        get: function () { return desc.get.call(sel); },
        set: function (v) { desc.set.call(sel, v); pintar(); }
      });
      Object.defineProperty(sel, 'selectedIndex', {
        configurable: true,
        get: function () { return descIdx.get.call(sel); },
        set: function (v) { descIdx.set.call(sel, v); pintar(); }
      });
    } catch (_) {}
    sel.addEventListener('change', pintar);
    // Opciones que se añaden luego (fuentes, listas) o que se traducen.
    new MutationObserver(pintar).observe(sel, {childList: true, subtree: true, characterData: true});

    btn.addEventListener('click', function () { abierto && abierto.sel === sel ? cerrar(true) : abrir(sel, btn); });
    btn.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); abrir(sel, btn); }
    });
    pintar();
  }

  function abrir(sel, btn) {
    cerrar(false);
    var pan = document.createElement('div');
    pan.className = 'msel-pan';
    pan.setAttribute('role', 'listbox');
    pan.id = btn.id + '-lista';
    btn.setAttribute('aria-controls', pan.id);
    var tit = TITULOS[sel.id];
    if (tit) {
      var h = document.createElement('div'); h.className = 'msel-tit'; h.textContent = tit;
      if (typeof window._tr === 'function') h.textContent = window._tr(tit);
      pan.appendChild(h);
    }
    var ops = [];
    Array.prototype.forEach.call(sel.options, function (o, i) {
      if (o.hidden) return;
      var d = document.createElement('div');
      d.className = 'msel-op';
      d.id = pan.id + '-' + i;
      d.setAttribute('role', 'option');
      d.setAttribute('aria-selected', i === sel.selectedIndex ? 'true' : 'false');
      if (o.disabled) d.setAttribute('aria-disabled', 'true');
      var p = partir(o.textContent);
      if (!p[0]) p[0] = icono(sel, o);
      var ico = document.createElement('span'); ico.className = 'ico'; ico.textContent = p[0]; ico.setAttribute('aria-hidden', 'true');
      var tx = document.createElement('span'); tx.className = 'tx'; tx.textContent = p[1] || p[0];
      d.append(ico, tx);
      d.insertAdjacentHTML('beforeend', OK);
      d.__i = i;
      d.addEventListener('mousedown', function (e) { e.preventDefault(); });
      d.addEventListener('click', function () { if (!o.disabled) elegir(i); });
      d.addEventListener('mousemove', function () { enfocar(ops.indexOf(d), false); });
      pan.appendChild(d);
      ops.push(d);
    });
    document.body.appendChild(pan);
    btn.setAttribute('aria-expanded', 'true');
    abierto = {sel: sel, btn: btn, pan: pan, ops: ops, foco: -1, busca: '', tBusca: 0};
    colocar();
    enfocar(Math.max(0, ops.findIndex(function (d) { return d.__i === sel.selectedIndex; })), true);
    pan.tabIndex = -1;
    pan.focus({preventScroll: true});
    pan.addEventListener('keydown', tecla);
  }

  function colocar() {
    if (!abierto) return;
    var r = abierto.btn.getBoundingClientRect();
    var pan = abierto.pan;
    pan.style.minWidth = Math.max(200, r.width) + 'px';
    var alto = pan.offsetHeight, ancho = pan.offsetWidth;
    var abajo = window.innerHeight - r.bottom - 8;
    var arriba = r.top - 8 >= alto && abajo < alto;
    pan.classList.toggle('arriba', arriba);
    pan.style.top = (arriba ? r.top - alto - 6 : r.bottom + 6) + 'px';
    var x = Math.min(r.left, window.innerWidth - ancho - 8);
    pan.style.left = Math.max(8, x) + 'px';
  }

  function enfocar(k, desplazar) {
    var a = abierto; if (!a || k < 0 || k >= a.ops.length) return;
    if (a.foco >= 0 && a.ops[a.foco]) a.ops[a.foco].classList.remove('foco');
    a.foco = k;
    a.ops[k].classList.add('foco');
    a.pan.setAttribute('aria-activedescendant', a.ops[k].id);
    if (desplazar) a.ops[k].scrollIntoView({block: 'nearest'});
  }

  function elegir(i) {
    var a = abierto; if (!a) return;
    var sel = a.sel;
    var cambia = sel.selectedIndex !== i;
    descIdx.set.call(sel, i);
    if (sel.__mselPintar) sel.__mselPintar();
    cerrar(true);
    if (cambia) {
      sel.dispatchEvent(new Event('input', {bubbles: true}));
      sel.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }

  function tecla(e) {
    var a = abierto; if (!a) return;
    var k = a.foco;
    // Las teclas del menú no deben llegar a los atajos de la página (Enter
    // abría la ficha del anime enfocado, Escape cerraba otras ventanas…).
    if (e.key !== 'Tab') e.stopPropagation();
    if (e.key === 'ArrowDown') { e.preventDefault(); enfocar(Math.min(a.ops.length - 1, k + 1), true); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); enfocar(Math.max(0, k - 1), true); }
    else if (e.key === 'Home') { e.preventDefault(); enfocar(0, true); }
    else if (e.key === 'End') { e.preventDefault(); enfocar(a.ops.length - 1, true); }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (a.ops[k] && a.ops[k].getAttribute('aria-disabled') !== 'true') elegir(a.ops[k].__i); }
    else if (e.key === 'Escape') { e.preventDefault(); cerrar(true); }
    else if (e.key === 'Tab') { cerrar(false); }
    else if (e.key.length === 1 && /\S/.test(e.key)) {
      // Escribir para saltar: "c" → Completado.
      clearTimeout(a.tBusca);
      a.busca += e.key.toLowerCase();
      a.tBusca = setTimeout(function () { if (abierto) abierto.busca = ''; }, 700);
      var j = a.ops.findIndex(function (d) { return d.querySelector('.tx').textContent.toLowerCase().indexOf(a.busca) === 0; });
      if (j >= 0) enfocar(j, true);
    }
  }

  function cerrar(devolverFoco) {
    var a = abierto; if (!a) return;
    abierto = null;
    a.btn.setAttribute('aria-expanded', 'false');
    a.pan.remove();
    if (devolverFoco) a.btn.focus({preventScroll: true});
  }

  document.addEventListener('mousedown', function (e) {
    if (abierto && !abierto.pan.contains(e.target) && !abierto.btn.contains(e.target)) cerrar(false);
  }, true);
  window.addEventListener('resize', function () { cerrar(false); });
  window.addEventListener('scroll', function (e) {
    if (abierto && !abierto.pan.contains(e.target)) colocar();
  }, true);

  function arrancar() {
    // v2.16: todos los desplegables (barra de filtros, ventanas, idioma…),
    // salvo los múltiples o los marcados con data-nativo.
    var sels = document.querySelectorAll('select:not([multiple]):not([data-nativo])');
    Array.prototype.forEach.call(sels, mejorar);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();

  if (!document.getElementById('msel-css')) {
    var st = document.createElement('style'); st.id = 'msel-css'; st.textContent = CSS;
    (document.head || document.documentElement).appendChild(st);
  }
  window.miraruSelects = {mejorar: mejorar, cerrar: cerrar};
})();
