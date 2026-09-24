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

  // ── Botón flotante de apariencia ──────────────────────────────────────────
  // Se auto-inyecta en las páginas que no tengan ya un botón propio
  // (#btn-appearance), para que la personalización esté a un clic en todas.
  function injectFab() {
    if (document.getElementById("btn-appearance")) return;      // ya hay uno en la cabecera
    if (document.getElementById("miraru-fab")) return;
    var b = document.createElement("button");
    b.id = "miraru-fab";
    b.type = "button";
    b.title = "Apariencia (tema, color, densidad)";
    b.setAttribute("aria-label", "Apariencia");
    b.textContent = "🎨";
    b.style.cssText =
      "position:fixed;bottom:70px;right:20px;z-index:60;width:40px;height:40px;border-radius:50%;" +
      "border:1px solid var(--border);background:var(--card);color:var(--fg);font-size:17px;cursor:pointer;" +
      "display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow-md);" +
      "transition:transform .2s cubic-bezier(.16,1,.3,1),box-shadow .2s;opacity:.9";
    b.addEventListener("mouseenter", function () {
      b.style.transform = "scale(1.12) rotate(-8deg)";
      b.style.boxShadow = "var(--shadow-accent)";
      b.style.opacity = "1";
    });
    b.addEventListener("mouseleave", function () {
      b.style.transform = ""; b.style.boxShadow = "var(--shadow-md)"; b.style.opacity = ".9";
    });
    b.addEventListener("click", open);
    document.body.appendChild(b);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectFab);
  } else {
    injectFab();
  }
})();
