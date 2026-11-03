/* Miraru — ventana «Novedades» tras cada actualización.
   La decide el servidor (/api/aviso-novedades): sale una vez por versión, en
   el menú o en la app (donde abras primero), y si te saltaste versiones
   enseña también lo que trajeron esas. Autocontenida: CSS + DOM propios. */
(function () {
  'use strict';
  if (window.__miraruNovedades) return;
  window.__miraruNovedades = true;

  var CSS = [
    '.mnv-bg{position:fixed;inset:0;z-index:10050;display:grid;place-items:center;padding:16px;',
    ' background:rgba(6,4,12,.62);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);',
    ' animation:mnv-fade .32s cubic-bezier(.22,1,.36,1) both}',
    '.mnv{position:relative;width:min(540px,100%);max-height:min(86vh,760px);display:flex;flex-direction:column;',
    ' background:var(--card,#181426);color:var(--fg,#edecf4);border:1px solid var(--border,#2b2542);',
    ' border-radius:22px;box-shadow:0 30px 80px -20px rgba(0,0,0,.7);overflow:hidden;',
    ' font-family:Inter,system-ui,sans-serif;animation:mnv-in .5s cubic-bezier(.16,1,.3,1) both}',
    '.mnv-cab{position:relative;padding:26px 26px 18px;overflow:hidden}',
    '.mnv-cab::before{content:"";position:absolute;inset:-60% -20% auto;height:220px;',
    ' background:radial-gradient(closest-side,rgba(var(--accent-rgb,124,58,237),.38),transparent);pointer-events:none}',
    '.mnv-cab>*{position:relative}',
    '.mnv-eti{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:700;letter-spacing:.06em;',
    ' text-transform:uppercase;color:var(--light,#c4b1ff)}',
    '.mnv-ver{padding:3px 9px;border-radius:999px;background:rgba(var(--accent-rgb,124,58,237),.22);',
    ' border:1px solid rgba(var(--accent-rgb,124,58,237),.45);color:var(--fg,#edecf4);letter-spacing:0;text-transform:none;',
    ' font-variant-numeric:tabular-nums}',
    '.mnv h2{margin:10px 0 0;font:700 25px/1.18 "Space Grotesk",Inter,sans-serif;letter-spacing:-.01em;text-wrap:balance}',
    '.mnv-sub{margin:8px 0 0;font-size:14px;line-height:1.5;color:var(--muted,#a49dc0);text-wrap:pretty}',
    '.mnv-cuerpo{overflow-y:auto;padding:4px 26px 8px;overscroll-behavior:contain}',
    '.mnv-sep{display:flex;align-items:center;gap:10px;margin:18px 0 6px;font-size:12px;font-weight:700;',
    ' color:var(--muted,#a49dc0);letter-spacing:.04em;text-transform:uppercase}',
    '.mnv-sep::after{content:"";flex:1;height:1px;background:var(--border,#2b2542)}',
    '.mnv-lista{list-style:none;margin:0;padding:0;display:grid;gap:4px}',
    '.mnv-p{display:grid;grid-template-columns:44px 1fr;gap:14px;align-items:start;padding:10px 8px;border-radius:14px;',
    ' animation:mnv-sube .55s cubic-bezier(.16,1,.3,1) both;animation-delay:calc(120ms + var(--i,0) * 55ms);',
    ' transition:background .2s}',
    '.mnv-p:hover{background:rgba(255,255,255,.035)}',
    '.mnv-ico{width:44px;height:44px;display:grid;place-items:center;font-size:22px;border-radius:13px;',
    ' background:rgba(var(--accent-rgb,124,58,237),.14);border:1px solid rgba(var(--accent-rgb,124,58,237),.28)}',
    '.mnv-p strong{display:block;font-size:15px;font-weight:650;line-height:1.3;margin-top:2px}',
    '.mnv-p p{margin:3px 0 0;font-size:13.5px;line-height:1.5;color:var(--muted,#a49dc0);text-wrap:pretty}',
    '.mnv-acc{display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:6px 12px;border-radius:9px;',
    ' font-size:13px;font-weight:600;color:var(--light,#c4b1ff);text-decoration:none;',
    ' background:rgba(var(--accent-rgb,124,58,237),.12);border:1px solid rgba(var(--accent-rgb,124,58,237),.3);',
    ' transition:background .2s,transform .2s cubic-bezier(.22,1,.36,1)}',
    '.mnv-acc:hover{background:rgba(var(--accent-rgb,124,58,237),.24);transform:translateX(2px)}',
    '.mnv-pie{display:flex;align-items:center;gap:10px;padding:16px 26px 22px;border-top:1px solid var(--border-soft,#1e1930)}',
    '.mnv-todo{margin-right:auto;font-size:13px;color:var(--muted,#a49dc0);text-decoration:none}',
    '.mnv-todo:hover{color:var(--fg,#edecf4);text-decoration:underline}',
    '.mnv-ok{border:0;cursor:pointer;padding:11px 22px;border-radius:12px;font:700 14.5px Inter,system-ui,sans-serif;',
    ' color:#fff;background:var(--accent,#7c3aed);box-shadow:0 8px 24px -8px rgba(var(--accent-rgb,124,58,237),.8);',
    ' transition:transform .2s cubic-bezier(.22,1,.36,1),filter .2s}',
    '.mnv-ok:hover{filter:brightness(1.1);transform:translateY(-1px)}',
    '.mnv-ok:focus-visible,.mnv-acc:focus-visible,.mnv-x:focus-visible{outline:2px solid var(--light,#c4b1ff);outline-offset:2px}',
    '.mnv-x{position:absolute;top:14px;right:14px;z-index:2;width:34px;height:34px;border-radius:10px;border:0;cursor:pointer;',
    ' background:transparent;color:var(--muted,#a49dc0);font-size:20px;line-height:1}',
    '.mnv-x:hover{background:rgba(255,255,255,.06);color:var(--fg,#edecf4)}',
    '.mnv-bg.sale{animation:mnv-fade .2s ease-in reverse both}',
    '@keyframes mnv-fade{from{opacity:0}}',
    '@keyframes mnv-in{from{opacity:0;transform:translateY(14px) scale(.98)}}',
    '@keyframes mnv-sube{from{opacity:0;transform:translateY(8px)}}',
    '@media (max-width:520px){.mnv-cab{padding:22px 18px 14px}.mnv-cuerpo{padding:2px 18px 6px}',
    ' .mnv-pie{padding:14px 18px 18px}.mnv h2{font-size:21px}.mnv-todo{display:none}.mnv-ok{flex:1}}',
    '@media (prefers-reduced-motion:reduce){.mnv-bg,.mnv,.mnv-p{animation:none}}'
  ].join('\n');

  function t(s) { return (typeof window._tr === 'function') ? window._tr(s) : s; }
  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = t(txt);
    return e;
  }

  // Otro aviso abierto (modal, recorrido guiado, recuperar copia): espera.
  function ocupado() {
    return !!document.querySelector('.modal-bg.open, .mtour-on, .mdlg-fondo') ||
      (document.getElementById('copia-aviso') || {style: {}}).style.display === 'flex';
  }

  function visto() { fetch('/api/aviso-novedades/visto', {method: 'POST'}).catch(function () {}); }

  function pintar(d) {
    if (!document.getElementById('mnv-css')) {
      var st = document.createElement('style'); st.id = 'mnv-css'; st.textContent = CSS;
      document.head.appendChild(st);
    }
    var vs = d.versiones || [];
    var bg = el('div', 'mnv-bg');
    var box = el('div', 'mnv');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'mnv-tit');

    var x = el('button', 'mnv-x', '×'); x.type = 'button'; x.setAttribute('aria-label', t('Cerrar'));
    var cab = el('div', 'mnv-cab');
    var eti = el('div', 'mnv-eti', 'Novedades');
    eti.appendChild(el('span', 'mnv-ver', 'v' + vs[0].version.replace(/\.0$/, '')));
    var h = el('h2', null, vs[0].titulo); h.id = 'mnv-tit';
    var sub = el('p', 'mnv-sub', vs.length > 1
      ? 'Miraru se ha actualizado. Esto es lo nuevo, y lo que trajeron las versiones que te saltaste.'
      : 'Miraru se ha actualizado. Esto es lo nuevo:');
    cab.append(eti, h, sub);

    var cuerpo = el('div', 'mnv-cuerpo');
    var i = 0;
    vs.forEach(function (v, k) {
      if (k > 0) cuerpo.appendChild(el('div', 'mnv-sep', 'Versión ' + v.version.replace(/\.0$/, '') + ' · ' + v.titulo));
      var ul = el('ul', 'mnv-lista');
      (v.puntos || []).forEach(function (p) {
        var li = el('li', 'mnv-p'); li.style.setProperty('--i', String(Math.min(i++, 10)));
        var ico = el('span', 'mnv-ico', p.icono || '✨'); ico.setAttribute('aria-hidden', 'true');
        var tx = el('div');
        tx.append(el('strong', null, p.titulo), el('p', null, p.texto));
        if (p.accion && p.accion.url) {
          var a = el('a', 'mnv-acc', p.accion.texto); a.href = p.accion.url;
          a.appendChild(el('span', null, '→'));
          a.addEventListener('click', function (ev) {
            cerrar();
            // Ya estamos en esa página: basta con cambiar el #.
            var u = new URL(a.href, location.href);
            if (u.pathname === location.pathname) {
              ev.preventDefault();
              if (location.hash === u.hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
              else location.hash = u.hash;
            }
          });
          tx.appendChild(a);
        }
        li.append(ico, tx); ul.appendChild(li);
      });
      cuerpo.appendChild(ul);
    });

    var pie = el('div', 'mnv-pie');
    var todo = el('a', 'mnv-todo', 'Ver todos los cambios');
    todo.href = 'https://github.com/lucasusamentiaga/anime-tracker/releases'; todo.target = '_blank'; todo.rel = 'noopener';
    var ok = el('button', 'mnv-ok', '¡Genial!'); ok.type = 'button';
    pie.append(todo, ok);

    box.append(x, cab, cuerpo, pie);
    bg.appendChild(box);
    document.body.appendChild(bg);
    var antes = document.activeElement;
    setTimeout(function () { try { ok.focus({preventScroll: true}); } catch (_) {} }, 60);

    var hecho = false;
    function cerrar() {
      if (hecho) return; hecho = true;
      visto();
      document.removeEventListener('keydown', tecla, true);
      bg.classList.add('sale');
      setTimeout(function () { bg.remove(); try { antes && antes.focus && antes.focus(); } catch (_) {} }, 190);
    }
    function tecla(e) {
      if (e.key === 'Escape') { e.preventDefault(); cerrar(); }
      if (e.key === 'Tab') {                       // el foco no se escapa de la ventana
        var f = box.querySelectorAll('a[href],button');
        var a0 = f[0], a1 = f[f.length - 1];
        if (e.shiftKey && document.activeElement === a0) { e.preventDefault(); a1.focus(); }
        else if (!e.shiftKey && document.activeElement === a1) { e.preventDefault(); a0.focus(); }
      }
    }
    document.addEventListener('keydown', tecla, true);
    x.onclick = ok.onclick = cerrar;
    bg.addEventListener('click', function (e) { if (e.target === bg) cerrar(); });
  }

  var intentos = 0;
  function probar(d) {
    if (ocupado()) { if (++intentos < 60) setTimeout(function () { probar(d); }, 2000); return; }
    pintar(d);
  }

  function arrancar() {
    if (/^\/(mobile|setup|share)/.test(location.pathname)) return;
    fetch('/api/aviso-novedades', {cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.mostrar && (d.versiones || []).length) setTimeout(function () { probar(d); }, 1400); })
      .catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
  window.miraruNovedades = { mostrar: function (d) { pintar(d); } };
})();
