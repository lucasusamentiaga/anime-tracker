/* ============================================================================
   Miraru — Personalización de apariencia (compartida por todas las páginas)

   - Aplica las preferencias ANTES del primer pintado (sin parpadeo).
   - Persiste en localStorage; no necesita backend.
   - Expone window.MiraruTheme = { open, apply, get, set }.
   - Los componentes ya consumen los tokens CSS (--accent, --light…), así que
     cambiar el acento repinta toda la app sin tocar cada regla.
   ============================================================================ */
(function () {
  "use strict";

  // Evitar que el navegador envíe el header Referer al cargar imágenes externas.
  // Sin esto, sitios como animeflv bloquean las portadas con 403 porque detectan
  // que la petición viene de un dominio distinto (hotlinking protection).
  // Se añade aquí (ejecutado en <head>) para cubrir todas las páginas de Miraru.
  if (document.head && !document.querySelector('meta[name="referrer"]')) {
    var _m = document.createElement("meta");
    _m.name = "referrer";
    _m.content = "no-referrer";
    document.head.appendChild(_m);
  }

  var KEY = "miraru_prefs";

  // ── Paletas de acento ─────────────────────────────────────────────────────
  // light = tono claro para texto/realces sobre fondo oscuro
  // ink   = tono oscuro legible para el modo claro (contraste AA)
  var ACCENTS = {
    violeta:   { nombre: "Violeta",   a: "#7c3aed", b: "#a855f7", c: "#d946ef", light: "#c4b1ff", ink: "#5b34d6" },
    indigo:    { nombre: "Índigo",    a: "#4f46e5", b: "#6366f1", c: "#818cf8", light: "#c7d2fe", ink: "#4338ca" },
    cian:      { nombre: "Cian",      a: "#0891b2", b: "#06b6d4", c: "#22d3ee", light: "#a5f3fc", ink: "#0e7490" },
    esmeralda: { nombre: "Esmeralda", a: "#059669", b: "#10b981", c: "#34d399", light: "#a7f3d0", ink: "#047857" },
    ambar:     { nombre: "Ámbar",     a: "#d97706", b: "#f59e0b", c: "#fbbf24", light: "#fde68a", ink: "#b45309" },
    rosa:      { nombre: "Rosa",      a: "#db2777", b: "#ec4899", c: "#f472b6", light: "#fbcfe8", ink: "#be185d" },
    carmesi:   { nombre: "Carmesí",   a: "#dc2626", b: "#ef4444", c: "#f87171", light: "#fecaca", ink: "#b91c1c" },
    pizarra:   { nombre: "Pizarra",   a: "#475569", b: "#64748b", c: "#94a3b8", light: "#cbd5e1", ink: "#334155" }
  };

  var DEFAULTS = {
    theme:   "dark",      // dark | light
    accent:  "violeta",   // clave de ACCENTS
    density: "comodo",    // comodo | compacto
    radius:  "medio",     // suave | medio | recto
    glow:    "on",        // on | off  (fondo ambiental + brillos)
    motion:  "full"       // full | reducido
  };

  function read() {
    var p = {};
    try { p = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { p = {}; }
    // Compatibilidad con la clave antigua 'theme' suelta
    try {
      var legacy = localStorage.getItem("theme");
      if (legacy && !p.theme) p.theme = legacy === "light" ? "light" : "dark";
    } catch (e) {}
    var out = {};
    for (var k in DEFAULTS) out[k] = p[k] || DEFAULTS[k];
    if (!ACCENTS[out.accent]) out.accent = DEFAULTS.accent;
    return out;
  }

  function write(p) {
    try {
      localStorage.setItem(KEY, JSON.stringify(p));
      localStorage.setItem("theme", p.theme);   // compatibilidad con el código existente
    } catch (e) {}
  }

  function hexToRgb(h) {
    var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(h || "");
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [124, 58, 237];
  }
  function rgba(hex, alpha) {
    var c = hexToRgb(hex);
    return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha + ")";
  }

  // ── Aplicar ───────────────────────────────────────────────────────────────
  function apply(p) {
    p = p || read();
    var root = document.documentElement;
    var A = ACCENTS[p.accent] || ACCENTS.violeta;
    var isLight = p.theme === "light";

    root.setAttribute("data-theme", isLight ? "light" : "dark");
    root.setAttribute("data-density", p.density);
    root.setAttribute("data-radius", p.radius);
    root.setAttribute("data-glow", p.glow);
    root.setAttribute("data-motion", p.motion);

    var s = root.style;
    s.setProperty("--accent",  isLight ? A.ink : A.a);
    s.setProperty("--accent2", isLight ? A.a   : A.b);
    s.setProperty("--accent3", A.c);
    s.setProperty("--light",   isLight ? A.ink : A.light);
    s.setProperty("--glow",    rgba(A.b, isLight ? 0.16 : 0.32));
    s.setProperty("--ring",    "0 0 0 3px " + rgba(A.a, isLight ? 0.30 : 0.45));
    s.setProperty("--grad-accent",
      "linear-gradient(135deg," + A.a + " 0%," + A.b + " 50%," + A.c + " 100%)");
    s.setProperty("--grad-accent-soft",
      "linear-gradient(135deg," + rgba(A.a, 0.18) + "," + rgba(A.c, 0.10) + ")");
    s.setProperty("--shadow-accent", "0 10px 34px " + rgba(A.a, isLight ? 0.18 : 0.28));
    s.setProperty("--accent-rgb", hexToRgb(A.a).join(","));
    // Flecha de los <select> teñida con el acento
    var arrow = isLight ? A.ink : A.light;
    s.setProperty("--select-arrow",
      "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='" +
      encodeURIComponent(arrow) + "' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E\")");

    // theme-color del navegador / PWA
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", isLight ? "#ffffff" : A.a);
  }

  // Aplicar YA (evita el flash de tema incorrecto)
  apply();

  // ── Panel de apariencia ───────────────────────────────────────────────────
  function el(tag, css, txt) {
    var e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function segmented(label, valor, opciones, onPick) {
    var wrap = el("div", "margin-bottom:18px");
    wrap.appendChild(el("div",
      "font-size:11px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);margin-bottom:8px",
      label));
    var row = el("div", "display:flex;gap:6px;flex-wrap:wrap");
    opciones.forEach(function (o) {
      var b = el("button", "", o.label);
      var activo = o.v === valor;
      b.type = "button";
      b.style.cssText =
        "flex:1;min-width:84px;padding:9px 10px;border-radius:10px;cursor:pointer;font-size:12px;font-weight:600;" +
        "transition:all .18s cubic-bezier(.16,1,.3,1);" +
        (activo
          ? "background:var(--grad-accent);color:#fff;border:1px solid transparent;box-shadow:var(--shadow-accent)"
          : "background:var(--card2);color:var(--fg);border:1px solid var(--border)");
      b.addEventListener("click", function () { onPick(o.v); });
      row.appendChild(b);
    });
    wrap.appendChild(row);
    return wrap;
  }

  function open() {
    if (document.getElementById("miraru-prefs")) return close();
    var p = read();

    var bg = el("div", "position:fixed;inset:0;z-index:400;background:rgba(4,2,10,.62);" +
      "backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:flex;align-items:center;" +
      "justify-content:center;padding:16px;animation:miraruFade .18s ease");
    bg.id = "miraru-prefs";
    bg.addEventListener("click", function (e) { if (e.target === bg) close(); });

    var box = el("div", "background:var(--card);border:1px solid var(--border);border-radius:18px;" +
      "width:100%;max-width:440px;max-height:88vh;overflow-y:auto;padding:22px;" +
      "box-shadow:0 24px 60px rgba(0,0,0,.5),0 0 0 1px " + rgba(ACCENTS[p.accent].a, .12) + ";" +
      "animation:miraruPop .28s cubic-bezier(.16,1,.3,1)");

    var head = el("div", "display:flex;align-items:center;gap:9px;margin-bottom:20px");
    head.appendChild(el("span", "font-size:19px", "🎨"));
    var h = el("h3", "font-size:17px;font-weight:800;letter-spacing:-.02em;color:var(--fg);flex:1;margin:0", "Apariencia");
    head.appendChild(h);
    var x = el("button", "background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;" +
      "line-height:1;padding:2px 6px;border-radius:8px", "×");
    x.addEventListener("click", close);
    head.appendChild(x);
    box.appendChild(head);

    function rerender() { write(p); apply(p); close(); open(); }

    // Tema
    box.appendChild(segmented("Tema", p.theme, [
      { v: "dark", label: "🌙 Oscuro" }, { v: "light", label: "☀️ Claro" }
    ], function (v) { p.theme = v; rerender(); }));

    // Acento — muestrario de color
    var accWrap = el("div", "margin-bottom:18px");
    accWrap.appendChild(el("div",
      "font-size:11px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);margin-bottom:8px",
      "Color de acento"));
    var grid = el("div", "display:grid;grid-template-columns:repeat(4,1fr);gap:9px");
    Object.keys(ACCENTS).forEach(function (k) {
      var A = ACCENTS[k];
      var b = el("button", "");
      b.type = "button";
      b.title = A.nombre;
      var sel = k === p.accent;
      b.style.cssText =
        "height:46px;border-radius:12px;cursor:pointer;position:relative;" +
        "background:linear-gradient(135deg," + A.a + "," + A.c + ");" +
        "border:2px solid " + (sel ? "var(--fg)" : "transparent") + ";" +
        "transform:scale(" + (sel ? 1.06 : 1) + ");" +
        "box-shadow:" + (sel ? "0 8px 22px " + rgba(A.a, .45) : "0 2px 8px rgba(0,0,0,.25)") + ";" +
        "transition:transform .2s cubic-bezier(.16,1,.3,1),box-shadow .2s";
      if (sel) {
        var chk = el("span", "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;" +
          "color:#fff;font-size:16px;font-weight:800;text-shadow:0 1px 4px rgba(0,0,0,.5)", "✓");
        b.appendChild(chk);
      }
      b.addEventListener("click", function () { p.accent = k; rerender(); });
      grid.appendChild(b);
    });
    accWrap.appendChild(grid);
    accWrap.appendChild(el("div", "font-size:11px;color:var(--muted);margin-top:7px",
      "Acento actual: " + ACCENTS[p.accent].nombre));
    box.appendChild(accWrap);

    // Densidad / Esquinas / Fondo / Movimiento
    box.appendChild(segmented("Densidad", p.density, [
      { v: "comodo", label: "Cómoda" }, { v: "compacto", label: "Compacta" }
    ], function (v) { p.density = v; rerender(); }));

    box.appendChild(segmented("Esquinas", p.radius, [
      { v: "suave", label: "Suaves" }, { v: "medio", label: "Medias" }, { v: "recto", label: "Rectas" }
    ], function (v) { p.radius = v; rerender(); }));

    box.appendChild(segmented("Fondo ambiental", p.glow, [
      { v: "on", label: "Con brillo" }, { v: "off", label: "Plano" }
    ], function (v) { p.glow = v; rerender(); }));

    box.appendChild(segmented("Animaciones", p.motion, [
      { v: "full", label: "Completas" }, { v: "reducido", label: "Reducidas" }
    ], function (v) { p.motion = v; rerender(); }));

    // Restablecer
    var reset = el("button", "width:100%;padding:10px;border-radius:10px;border:1px solid var(--border);" +
      "background:var(--card2);color:var(--muted);font-size:12px;font-weight:600;cursor:pointer;margin-top:4px",
      "↺ Restablecer valores por defecto");
    reset.type = "button";
    reset.addEventListener("click", function () {
      for (var k in DEFAULTS) p[k] = DEFAULTS[k];
      rerender();
    });
    box.appendChild(reset);

    bg.appendChild(box);
    document.body.appendChild(bg);
    document.addEventListener("keydown", esc);
  }

  function esc(e) { if (e.key === "Escape") close(); }

  function close() {
    var n = document.getElementById("miraru-prefs");
    if (n) n.remove();
    document.removeEventListener("keydown", esc);
  }

  window.MiraruTheme = {
    open: open,
    close: close,
    apply: apply,
    get: read,
    set: function (patch) {
      var p = read();
      for (var k in (patch || {})) p[k] = patch[k];
      write(p); apply(p);
    },
    accents: ACCENTS
  };

  // Alternar tema rápido (lo usan los botones 🌙/☀️ existentes)
  window.miraruToggleTheme = function () {
    var p = read();
    p.theme = p.theme === "light" ? "dark" : "light";
    write(p); apply(p);
    return p.theme;
  };

  // ── Portadas sin roturas ──────────────────────────────────────────────────
  // `img.src = ""` NO deja la imagen vacía: la cadena vacía se resuelve contra
  // la URL actual, así que el navegador se descarga LA PROPIA PÁGINA como si
  // fuese una imagen (petición inútil de decenas de KB) y pinta el icono de
  // imagen rota. Pasaba en todas las cuadrículas de la app cada vez que un
  // anime no traía portada — y con AniList caído, eso era siempre.
  // Vive aquí porque customize.js es el único script cargado en las 10 páginas.
  var SIN_PORTADA =
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 2 3'>" +
    "<rect fill='%231a1a24' width='2' height='3'/></svg>";

  window.miraruPortada = function (img, url) {
    if (!img) return img;
    img.referrerPolicy = "no-referrer";
    // Usar resolución media para rendimiento (230px vs 460px, ~75% menos bytes)
    var thumb = url ? url.replace('/cover/large/', '/cover/medium/') : '';
    img.src = thumb || SIN_PORTADA;
    if (!img.alt) img.alt = "";
    img.loading = "lazy";
    img.onerror = function () { img.onerror = null; img.src = SIN_PORTADA; };
    return img;
  };
  window.MIRARU_SIN_PORTADA = SIN_PORTADA;

  // ── Barra flotante: apariencia + redes del autor ──────────────────────────
  // Una sola barra en todas las páginas (antes cada plantilla llevaba sus
  // propios botones de X e Instagram y la de inicio un 🎨 en la cabecera).
  var REDES = [
    {id: "gh", t: "GitHub de Miraru", url: "https://github.com/lucasusamentiaga/anime-tracker", bg: "#24292f",
     svg: '<path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z"/>'},
    {id: "ig", t: "@lucasuazz_ en Instagram", url: "https://www.instagram.com/lucasuazz_/",
     bg: "linear-gradient(135deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)",
     svg: '<path d="M12 2.16c3.2 0 3.58.01 4.85.07 3.25.15 4.77 1.69 4.92 4.92.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.15 3.23-1.66 4.77-4.92 4.92-1.27.06-1.64.07-4.85.07s-3.58-.01-4.85-.07c-3.26-.15-4.77-1.7-4.92-4.92-.06-1.27-.07-1.64-.07-4.85s.01-3.58.07-4.85C2.38 3.92 3.9 2.38 7.15 2.23 8.42 2.17 8.8 2.16 12 2.16zM12 0C8.74 0 8.33.01 7.05.07 2.7.27.27 2.69.07 7.05.01 8.33 0 8.74 0 12s.01 3.67.07 4.95c.2 4.36 2.62 6.78 6.98 6.98 1.28.06 1.69.07 4.95.07s3.67-.01 4.95-.07c4.35-.2 6.78-2.62 6.98-6.98.06-1.28.07-1.69.07-4.95s-.01-3.67-.07-4.95c-.2-4.35-2.62-6.78-6.98-6.98C15.67.01 15.26 0 12 0zm0 5.84a6.16 6.16 0 1 0 0 12.32 6.16 6.16 0 0 0 0-12.32zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.4-11.85a1.44 1.44 0 1 0 0 2.88 1.44 1.44 0 0 0 0-2.88z"/>'},
    {id: "x", t: "@T0ff3_x en X", url: "https://x.com/T0ff3_x", bg: "#000",
     svg: '<path d="M18.24 2.25h3.31l-7.23 8.26 8.5 11.24H16.17l-4.71-6.23-5.4 6.23H2.75l7.73-8.84L1.25 2.25H8.08l4.25 5.62zm-1.16 17.52h1.83L7.08 4.13H5.12z"/>'}
  ];

  function injectDock() {
    if (document.getElementById("miraru-dock")) return;
    var css = document.createElement("style");
    css.textContent =
      "#miraru-dock{position:fixed;right:20px;bottom:20px;z-index:60;display:flex;gap:8px;align-items:center}" +
      "#miraru-dock .md-b{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;color:#fff;" +
      "border:1px solid rgba(255,255,255,.08);cursor:pointer;text-decoration:none;opacity:.88;font-size:17px;" +
      "box-shadow:0 2px 10px rgba(0,0,0,.35);transition:transform .25s cubic-bezier(.16,1,.3,1),opacity .2s}" +
      "#miraru-dock .md-b:hover,#miraru-dock .md-b:focus-visible{transform:translateY(-3px);opacity:1}" +
      "#miraru-dock .md-b svg{width:17px;height:17px;fill:currentColor}" +
      "#miraru-dock .md-ap{background:var(--card,#181426);color:var(--fg,#edecf4);border-color:var(--border,#2b2542)}" +
      "@media (max-width:640px){#miraru-dock .md-red{display:none}#miraru-dock{right:14px;bottom:14px}}" +
      "@media (prefers-reduced-motion:reduce){#miraru-dock .md-b{transition:none}}";
    document.head.appendChild(css);
    var d = document.createElement("div");
    d.id = "miraru-dock";
    var ap = document.createElement("button");
    ap.type = "button";
    ap.className = "md-b md-ap";
    ap.id = "miraru-fab";
    ap.title = "Apariencia (tema, color, densidad)";
    ap.setAttribute("aria-label", "Apariencia");
    ap.textContent = "🎨";
    ap.addEventListener("click", open);
    // v2.16: en la app, «?» repite el recorrido guiado cuando quieras.
    if (location.pathname === "/app") {
      var ay = document.createElement("button");
      ay.type = "button";
      ay.className = "md-b md-ap";
      ay.id = "miraru-ayuda";
      ay.title = "Recorrido por la app";
      ay.setAttribute("aria-label", "Recorrido por la app");
      ay.textContent = "?";
      ay.style.fontWeight = "800";
      ay.addEventListener("click", function () { if (window.miraruTour) window.miraruTour.empezar(true); });
      d.appendChild(ay);
    }
    d.appendChild(ap);
    REDES.forEach(function (r) {
      var a = document.createElement("a");
      a.className = "md-b md-red";
      a.id = r.id + "-btn";
      a.href = r.url; a.target = "_blank"; a.rel = "noopener";
      a.title = r.t; a.setAttribute("aria-label", r.t);
      a.style.background = r.bg;
      a.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + r.svg + "</svg>";
      d.appendChild(a);
    });
    document.body.appendChild(d);
  }

  // ── Sin menú del botón derecho ────────────────────────────────────────────
  // Miraru es una app: el menú del navegador («Inspeccionar», «Ver código»…)
  // no pinta nada. Se deja donde sí hace falta: campos de texto (pegar) y
  // cuando hay texto seleccionado (copiar).
  document.addEventListener("contextmenu", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest("input, textarea, [contenteditable=''], [contenteditable='true']")) return;
    var sel = window.getSelection && window.getSelection();
    if (sel && String(sel).trim()) return;
    e.preventDefault();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectDock);
  } else {
    injectDock();
  }
})();
