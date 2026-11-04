/* Miraru — recorrido guiado para quien abre la app por primera vez (v2.16).
   Un foco (todo oscuro menos la pieza que se explica) viaja por la pantalla
   y una tarjeta cuenta para qué sirve cada cosa. Se puede saltar, ir atrás y
   repetir cuando se quiera (botón «?» abajo a la derecha, Ctrl+K o /app#recorrido). */
(function () {
  'use strict';
  if (window.miraruTour) return;

  // sel: un selector o varios (el foco abarca todos los que se vean).
  // Pocos pasos y cada uno con algo que hacer: el primer anime es lo que importa.
  var PASOS = [
    {sel: null, ico: '👋', tit: '¡Bienvenido a Miraru!',
     txt: 'Tu lista de anime, en tu PC y sin cuentas. Te enseño lo importante en un minuto.'},
    {sel: '#inp-nombre', ico: '🔎', tit: 'Añade tu primer anime',
     txt: 'Escribe el nombre (o pega un enlace) y pulsa «+ Añadir». Si tiene más temporadas, te ofrecerá añadir la saga entera.'},
    {sel: '#lista', ico: '📚', tit: 'Tu lista',
     txt: 'Aquí aparecen tus animes, con las sagas agrupadas en carpetas. Pulsa una portada para editarla o +1 para apuntar un episodio.', lado: 'arriba'},
    {sel: '#tb2', ico: '🎛️', tit: 'Busca, filtra y ordena',
     txt: 'Encuentra algo en tu lista, filtra por estado y ordena como quieras.'},
    {sel: '#continuar-wrap', ico: '▶️', tit: 'Continuar viendo',
     txt: 'Lo que tienes a medias, con el siguiente episodio a un clic.'},
    {sel: '.header-nav', ico: '🧭', tit: 'Todo lo demás',
     txt: 'Estadísticas (y tu «Mi año en anime»), estrenos de la semana, calendario, recomendaciones y «No Anime», para tus películas y series.'},
    {sel: '#btn-copia', ico: '☁️', tit: 'Tu lista, a salvo',
     txt: 'Miraru guarda una copia en tu OneDrive, Google Drive o Dropbox. Si formateas el PC, la recuperas con un clic.'},
    {sel: ['#btn-anilist', '#btn-extension'], ico: '🔗', tit: 'Trae tu lista y no apuntes a mano',
     txt: '¿Tu lista está en AniList? Tráela entera de golpe. ¿Ves anime en AnimeAV1? Con su extensión cada episodio se apunta solo.'},
    {sel: 'a[href="/mobile"]', ico: '📱', tit: 'También en el móvil',
     txt: 'Activa el acceso móvil, escanea el QR y usa Miraru desde el sofá (misma WiFi).'},
    // En el móvil todo lo anterior vive tras «☰».
    {sel: '#btn-menu-movil', ico: '☰', tit: 'Más opciones',
     txt: 'Aquí están la copia en la nube, AniList, AnimeAV1, el acceso móvil y los ajustes.'},
    {sel: ['#miraru-ayuda', '#miraru-fab'], ico: '🎨', tit: 'Hazla tuya',
     txt: 'Con 🎨 cambias el color, el tema y la densidad. Con «?» repites este recorrido cuando quieras.', lado: 'arriba'},
    {sel: null, ico: '🎉', tit: '¡Listo!',
     txt: 'Empieza añadiendo un anime que estés viendo.', fin: true}
  ];

  var CSS = [
    '.mtour-capa{position:fixed;inset:0;z-index:var(--z-recorrido,1200);cursor:default}',
    // Se mueve con `translate` (lo hace la GPU); solo el tamaño cambia de ancho/alto.
    '.mtour-foco{position:fixed;top:0;left:0;z-index:calc(var(--z-recorrido,1200) + 1);border-radius:14px;pointer-events:none;',
    ' box-shadow:0 0 0 2px rgba(var(--accent-rgb,124,58,237),.95),0 0 0 100vmax rgba(6,4,12,.74);',
    ' transition:translate .5s cubic-bezier(.16,1,.3,1),width .5s cubic-bezier(.16,1,.3,1),height .5s cubic-bezier(.16,1,.3,1),border-radius .5s}',
    '.mtour-foco::after{content:"";position:absolute;inset:-6px;border-radius:inherit;border:2px solid rgba(var(--accent-rgb,124,58,237),.55);',
    ' animation:mtour-latido 1.8s cubic-bezier(.22,1,.36,1) infinite}',
    '.mtour-foco.centro{box-shadow:0 0 0 100vmax rgba(6,4,12,.74)}',
    '.mtour-foco.centro::after{display:none}',
    '.mtour-tarjeta{position:fixed;top:0;left:0;z-index:calc(var(--z-recorrido,1200) + 2);width:min(360px,calc(100vw - 24px));padding:18px 18px 14px;border-radius:16px;',
    ' background:var(--card,#181426);color:var(--fg,#edecf4);border:1px solid var(--border,#2b2542);font-family:Inter,system-ui,sans-serif;',
    ' transition:translate .5s cubic-bezier(.16,1,.3,1),opacity .25s}',
    '.mtour-tarjeta.grande{width:min(420px,calc(100vw - 24px));padding:26px 24px 18px;text-align:center}',
    '.mtour-cab{display:flex;align-items:center;gap:12px}',
    '.mtour-tarjeta.grande .mtour-cab{flex-direction:column;gap:10px}',
    '.mtour-ico{width:42px;height:42px;flex-shrink:0;display:grid;place-items:center;font-size:22px;border-radius:12px;',
    ' background:rgba(var(--accent-rgb,124,58,237),.16);border:1px solid rgba(var(--accent-rgb,124,58,237),.32)}',
    '.mtour-tarjeta.grande .mtour-ico{width:64px;height:64px;font-size:34px;border-radius:16px}',
    '.mtour-tarjeta h3{margin:0;font:700 17px/1.25 "Space Grotesk",Inter,sans-serif;text-wrap:balance}',
    '.mtour-tarjeta.grande h3{font-size:23px}',
    '.mtour-tarjeta p{margin:10px 0 0;font-size:14px;line-height:1.55;color:var(--muted,#a49dc0);text-wrap:pretty}',
    '.mtour-pie{display:flex;align-items:center;gap:8px;margin-top:16px}',
    '.mtour-tarjeta.grande .mtour-pie{justify-content:center;flex-wrap:wrap}',
    '.mtour-puntos{display:flex;gap:5px;margin-right:auto}',
    '.mtour-tarjeta.grande .mtour-puntos{width:100%;justify-content:center;margin:0 0 8px}',
    '.mtour-puntos i{width:6px;height:6px;border-radius:99px;background:var(--border,#2b2542);transition:width .3s cubic-bezier(.22,1,.36,1),background .3s}',
    '.mtour-puntos i.on{width:18px;background:var(--accent,#7c3aed)}',
    '.mtour-btn{border:0;cursor:pointer;padding:9px 16px;border-radius:10px;font:700 13.5px Inter,system-ui,sans-serif;color:#fff;',
    ' background:var(--accent,#7c3aed);transition:filter .2s,transform .2s cubic-bezier(.22,1,.36,1)}',
    '.mtour-btn:hover{filter:brightness(1.1);transform:translateY(-1px)}',
    '.mtour-btn.sec{background:transparent;color:var(--fg,#edecf4);border:1px solid var(--border,#2b2542)}',
    '.mtour-btn.txt{background:transparent;color:var(--muted,#a49dc0);padding:9px 8px}',
    '.mtour-btn.txt:hover{color:var(--fg,#edecf4);transform:none}',
    '.mtour-btn:focus-visible{outline:2px solid var(--light,#c4b1ff);outline-offset:2px}',
    '.mtour-entra{animation:mtour-entra .45s cubic-bezier(.16,1,.3,1) both}',
    '@keyframes mtour-entra{from{opacity:0;transform:translateY(8px) scale(.98)}}',
    '@keyframes mtour-latido{0%{opacity:.9;transform:scale(1)}70%,100%{opacity:0;transform:scale(1.06)}}',
    '@media (prefers-reduced-motion:reduce){.mtour-foco,.mtour-tarjeta{transition:none}.mtour-foco::after{animation:none}.mtour-entra{animation:none}}'
  ].join('\n');

  function t(s) { return (typeof window._tr === 'function') ? window._tr(s) : s; }
  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = t(txt);
    return e;
  }

  function visible(n) {
    if (!n) return false;
    var r = n.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    var cs = getComputedStyle(n);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    return n.offsetParent !== null || cs.position === 'fixed';
  }

  var estado = null;

  function nodos(p) {
    if (!p.sel) return [];
    return [].concat(p.sel).map(function (q) { return document.querySelector(q); }).filter(visible);
  }

  // Rectángulo que abarca todos los elementos del paso.
  function rect(ns) {
    var r = {top: Infinity, left: Infinity, right: -Infinity, bottom: -Infinity};
    ns.forEach(function (n) {
      var b = n.getBoundingClientRect();
      r.top = Math.min(r.top, b.top); r.left = Math.min(r.left, b.left);
      r.right = Math.max(r.right, b.right); r.bottom = Math.max(r.bottom, b.bottom);
    });
    r.width = r.right - r.left; r.height = r.bottom - r.top;
    return r;
  }

  function pasosValidos() {
    return PASOS.filter(function (p) { return !p.sel || nodos(p).length; });
  }

  function empezar(forzar) {
    if (estado) return;
    if (!document.getElementById('mtour-css')) {
      var st = document.createElement('style'); st.id = 'mtour-css'; st.textContent = CSS;
      document.head.appendChild(st);
    }
    var pasos = pasosValidos();
    var capa = el('div', 'mtour-capa');
    var foco = el('div', 'mtour-foco centro');
    var tarjeta = el('div', 'mtour-tarjeta');
    tarjeta.setAttribute('role', 'dialog');
    tarjeta.setAttribute('aria-modal', 'true');
    tarjeta.setAttribute('aria-live', 'polite');
    capa.addEventListener('click', function (e) { e.stopPropagation(); });
    document.body.append(capa, foco, tarjeta);
    document.body.classList.add('mtour-on');
    estado = {pasos: pasos, i: 0, capa: capa, foco: foco, tarjeta: tarjeta, forzado: !!forzar};
    document.addEventListener('keydown', tecla, true);
    window.addEventListener('resize', recolocar);
    window.addEventListener('scroll', recolocar, true);
    // El primer paso aparece en su sitio (sin viajar desde la esquina).
    foco.style.transition = tarjeta.style.transition = 'none';
    ir(0);
    requestAnimationFrame(function () { requestAnimationFrame(function () { foco.style.transition = tarjeta.style.transition = ''; }); });
  }

  function ir(i) {
    var e = estado; if (!e) return;
    e.i = Math.max(0, Math.min(i, e.pasos.length - 1));
    var p = e.pasos[e.i];
    var ns = nodos(p);
    if (p.sel && !ns.length) {      // desapareció (p. ej. «Continuar viendo» vacío): siguiente
      e.pasos.splice(e.i, 1);
      return ir(e.i);
    }
    pintarTarjeta(p);
    if (ns.length) {
      var r = rect(ns);
      if (r.top < 70 || r.bottom > innerHeight - 40) {
        ns[0].scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth'});
        setTimeout(function () { pintar(p, nodos(p)); }, 380);
        return;
      }
    }
    pintar(p, ns);
  }

  function pintarTarjeta(p) {
    var e = estado, tj = e.tarjeta;
    tj.className = 'mtour-tarjeta mtour-entra' + (p.sel ? '' : ' grande');
    tj.innerHTML = '';
    var cab = el('div', 'mtour-cab');
    var ico = el('span', 'mtour-ico', p.ico); ico.setAttribute('aria-hidden', 'true');
    var h = el('h3', null, p.tit); h.id = 'mtour-tit';
    tj.setAttribute('aria-labelledby', 'mtour-tit');
    cab.append(ico, h);
    var txt = el('p', null, p.txt);
    var pie = el('div', 'mtour-pie');
    var puntos = el('div', 'mtour-puntos');
    puntos.setAttribute('aria-label', t('Paso') + ' ' + (e.i + 1) + ' / ' + e.pasos.length);
    e.pasos.forEach(function (_, k) { var d = el('i'); if (k === e.i) d.className = 'on'; puntos.appendChild(d); });
    pie.appendChild(puntos);
    var principal;
    if (e.i === 0) {
      var saltar = el('button', 'mtour-btn txt', 'Ahora no'); saltar.type = 'button'; saltar.onclick = function () { terminar(); };
      principal = el('button', 'mtour-btn', 'Empezar →');
      pie.append(saltar, principal);
    } else if (p.fin) {
      var atras0 = el('button', 'mtour-btn sec', '←'); atras0.type = 'button'; atras0.setAttribute('aria-label', t('Atrás'));
      atras0.onclick = function () { ir(e.i - 1); };
      principal = el('button', 'mtour-btn', '¡A ver anime!');
      pie.append(atras0, principal);
    } else {
      var salir = el('button', 'mtour-btn txt', 'Saltar'); salir.type = 'button'; salir.onclick = function () { terminar(); };
      var atras = el('button', 'mtour-btn sec', '←'); atras.type = 'button'; atras.setAttribute('aria-label', t('Atrás'));
      atras.onclick = function () { ir(e.i - 1); };
      principal = el('button', 'mtour-btn', 'Siguiente');
      pie.append(salir, atras, principal);
    }
    principal.type = 'button';
    principal.onclick = function () { p.fin ? terminar() : ir(e.i + 1); };
    tj.append(cab, txt, pie);
    setTimeout(function () { try { principal.focus({preventScroll: true}); } catch (_) {} }, 30);
  }

  function pintar(p, ns) {
    var e = estado; if (!e) return;
    var f = e.foco, tj = e.tarjeta;
    if (!ns || !ns.length) {
      f.classList.add('centro');
      f.style.translate = (innerWidth / 2) + 'px ' + (innerHeight / 2) + 'px';
      f.style.width = '0px'; f.style.height = '0px';
      var tw = tj.offsetWidth, th = tj.offsetHeight;
      tj.style.translate = Math.max(12, (innerWidth - tw) / 2) + 'px ' + Math.max(12, (innerHeight - th) / 2) + 'px';
      return;
    }
    f.classList.remove('centro');
    var r = rect(ns), pad = 8;
    var top = Math.max(4, r.top - pad), left = Math.max(4, r.left - pad);
    var w = Math.min(innerWidth - 8 - left, r.width + pad * 2), h = Math.min(innerHeight - 8 - top, r.height + pad * 2);
    f.style.translate = left + 'px ' + top + 'px';
    f.style.width = w + 'px'; f.style.height = h + 'px';
    f.style.borderRadius = (h < 60 ? 12 : 16) + 'px';
    // Tarjeta: debajo si cabe; si no, encima; si tampoco, al lado.
    var tw2 = tj.offsetWidth, th2 = tj.offsetHeight, gap = 14;
    var y, x = Math.min(Math.max(12, r.left + r.width / 2 - tw2 / 2), innerWidth - tw2 - 12);
    var abajo = top + h + gap, arriba = top - gap - th2;
    if (p.lado === 'arriba' && arriba >= 12) y = arriba;
    else if (abajo + th2 <= innerHeight - 12) y = abajo;
    else if (arriba >= 12) y = arriba;
    else {
      y = Math.min(Math.max(12, r.top), innerHeight - th2 - 12);
      x = (r.left > innerWidth / 2) ? Math.max(12, left - tw2 - gap) : Math.min(innerWidth - tw2 - 12, left + w + gap);
    }
    tj.style.translate = x + 'px ' + y + 'px';
  }

  var raf = 0;
  function recolocar() {
    if (!estado) return;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(function () {
      var p = estado.pasos[estado.i];
      pintar(p, nodos(p));
    });
  }

  function tecla(ev) {
    if (!estado) return;
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); terminar(); }
    else if (ev.key === 'ArrowRight') { ev.preventDefault(); ev.stopPropagation(); var p = estado.pasos[estado.i]; p.fin ? terminar() : ir(estado.i + 1); }
    else if (ev.key === 'ArrowLeft') { ev.preventDefault(); ev.stopPropagation(); ir(estado.i - 1); }
    else if (ev.key === 'Tab') {
      // El foco se queda en la tarjeta.
      var f = estado.tarjeta.querySelectorAll('button');
      if (!f.length) return;
      var a = f[0], z = f[f.length - 1];
      if (ev.shiftKey && document.activeElement === a) { ev.preventDefault(); z.focus(); }
      else if (!ev.shiftKey && document.activeElement === z) { ev.preventDefault(); a.focus(); }
      else if (!estado.tarjeta.contains(document.activeElement)) { ev.preventDefault(); a.focus(); }
    }
    else {
      // Que los atajos de la página (Ctrl+K, Enter en una ficha…) no se
      // disparen por detrás; los botones de la tarjeta funcionan igual.
      ev.stopPropagation();
    }
  }

  function terminar() {
    var e = estado; if (!e) return;
    estado = null;
    document.removeEventListener('keydown', tecla, true);
    window.removeEventListener('resize', recolocar);
    window.removeEventListener('scroll', recolocar, true);
    e.capa.remove(); e.foco.remove(); e.tarjeta.remove();
    document.body.classList.remove('mtour-on');
    fetch('/api/recorrido/visto', {method: 'POST'}).catch(function () {});
    var inp = document.getElementById('inp-nombre');
    if (inp && !e.forzado) { try { inp.focus({preventScroll: true}); } catch (_) {} }
  }

  // ¿Es la primera vez? Lo decide el servidor (instalación nueva).
  function arrancar() {
    fetch('/api/recorrido', {cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.mostrar) return;
        var intentos = 0;
        (function esperar() {
          // Que no se pise con otra ventana (copia encontrada, novedades…).
          if (document.querySelector('.modal-bg.open, .mnv-bg, .mdlg-fondo') ||
              (document.getElementById('copia-aviso') || {style: {}}).style.display === 'flex') {
            if (++intentos < 60) setTimeout(esperar, 1500);
            return;
          }
          // Se vuelve a preguntar: mientras esperaba pudo recuperar su lista.
          fetch('/api/recorrido', {cache: 'no-store'})
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d2) { if (d2 && d2.mostrar) empezar(false); })
            .catch(function () {});
        })();
      })
      .catch(function () {});
  }

  window.miraruTour = {empezar: empezar, terminar: terminar};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(arrancar, 1200); });
  else setTimeout(arrancar, 1200);
})();
