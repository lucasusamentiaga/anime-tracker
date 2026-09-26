// Miraru — traduce los textos de interfaz escritos en español en las plantillas.
// El diccionario vive en i18n_ui.py y llega por /api/i18n/ui. En español no hace nada.
// Respeta translate="no" y data-no-i18n (útil para títulos de anime o texto del usuario).
(function () {
  'use strict';
  const ATTRS = ['placeholder', 'title', 'aria-label'];
  const NO = '[translate="no"],[data-no-i18n]';
  const SKIP = 'script,style,textarea,code,pre,[contenteditable="true"],' + NO;
  let MAP = null, PATS = [];

  const norm = s => s.replace(/\s+/g, ' ').trim();
  // prefijo de emoji/símbolos  ·  núcleo  ·  sufijo de signos
  const PARTES = /^([^\p{L}\p{N}¿¡"]*)(.*?)([^\p{L}\p{N}"]*)$/u;

  function porPatron(s) {
    for (const [re, tpl] of PATS) if (re.test(s)) return s.replace(re, tpl);
    return null;
  }

  function uno(s) {
    if (MAP[s] !== undefined) return MAP[s];
    const p0 = porPatron(s);
    if (p0 !== null) return p0;
    const m = s.match(PARTES);
    if (!m || !m[2]) return null;
    const resto = m[2] + m[3];
    if (m[1] && MAP[resto] !== undefined) return m[1] + MAP[resto];
    if (MAP[m[2]] !== undefined) return m[1] + MAP[m[2]] + m[3];
    const p = porPatron(resto);
    if (p !== null) return m[1] + p;
    const q = porPatron(m[2]);
    return q !== null ? m[1] + q + m[3] : null;
  }

  function traducir(txt) {
    const s = norm(txt);
    if (!s || !/[A-Za-zÁÉÍÓÚáéíóúñÑ]/.test(s)) return null;
    const r = uno(s);
    if (r !== null) return r;
    for (const sep of [' · ', ' — ']) {
      if (!s.includes(sep)) continue;
      let cambio = false;
      const out = s.split(sep).map(p => { const t = uno(p); if (t !== null) { cambio = true; return t; } return p; });
      if (cambio) return out.join(sep);
    }
    return null;
  }
  window.miraruTraducir = s => (MAP && traducir(s)) || s;

  function texto(n) {
    const p = n.parentElement;
    if (!p || p.closest(SKIP)) return;
    const v = n.nodeValue;
    const t = traducir(v);
    if (t === null) return;
    const lead = v.match(/^\s*/)[0], trail = v.match(/\s*$/)[0];
    const nuevo = lead + t + trail;
    if (nuevo !== v) n.nodeValue = nuevo;
  }

  function atributos(el) {
    if (el.closest(NO)) return;
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const t = traducir(v);
      if (t !== null && t !== v) el.setAttribute(a, t);
    }
  }

  function recorrer(raiz) {
    if (raiz.nodeType === 3) { texto(raiz); return; }
    if (raiz.nodeType !== 1) return;
    const w = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode())) texto(n);
    if (raiz.matches && raiz.matches('[placeholder],[title],[aria-label]')) atributos(raiz);
    raiz.querySelectorAll && raiz.querySelectorAll('[placeholder],[title],[aria-label]').forEach(atributos);
  }

  function titulo() {
    const t = traducir(document.title);
    if (t !== null && t !== document.title) document.title = t;
  }

  async function arrancar() {
    let d;
    try {
      const r = await fetch('/api/i18n/ui', { cache: 'no-store' });
      if (!r.ok) return;
      d = await r.json();
    } catch (_) { return; }
    if (!d || !d.map || !Object.keys(d.map).length) return;
    MAP = d.map;
    PATS = (d.patterns || []).map(([rx, tpl]) => { try { return [new RegExp(rx, 'u'), tpl]; } catch (_) { return null; } })
                             .filter(Boolean);
    document.documentElement.lang = d.lang || document.documentElement.lang;

    const _alert = window.alert.bind(window), _confirm = window.confirm.bind(window);
    window.alert = m => _alert(typeof m === 'string' ? (traducir(m) || m) : m);
    window.confirm = m => _confirm(typeof m === 'string' ? (traducir(m) || m) : m);

    recorrer(document.body); titulo();
    new MutationObserver(muts => {
      for (const m of muts) {
        if (m.type === 'childList') m.addedNodes.forEach(recorrer);
        else if (m.type === 'characterData') texto(m.target);
        else if (m.type === 'attributes') atributos(m.target);
      }
      titulo();
    }).observe(document.body, { childList: true, subtree: true, characterData: true,
                                 attributes: true, attributeFilter: ATTRS });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
})();
