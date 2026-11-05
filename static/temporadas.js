// Miraru — etiquetas de temporada para las carpetas de saga (v2.16.3).
//
// Antes cada entrada que no era película se numeraba T1, T2, T3… en el orden de
// la carpeta: Attack on Titan salía con «T11» cuando la serie tiene 4
// temporadas (la 3 y la final en dos partes, más OVAs y especiales). Ahora la
// etiqueta sale del propio nombre: «T3», «T3 P2», «Final», «Final P2»,
// «Final Esp. 1», «OVA»… y, si el nombre no dice nada (los arcos de Demon
// Slayer, «Lost Girls»), su subtítulo.
//
// miraruTemporadas(animes, nombreDeLaCarpeta) → {etiquetas: [..mismo orden..], temporadas: N, extras: N}
(function (raiz) {
  'use strict';
  const ROMANOS = {ii: 2, iii: 3, iv: 4, v: 5, vi: 6, vii: 7, viii: 8, ix: 9};

  const esPeli = a => /pel/i.test(String(a.capitulos || ''));

  function numTemporada(n) {
    let m = n.match(/\b(?:season|temporada|saison|staffel)\s*(\d+)/i)
         || n.match(/\b(\d+)(?:st|nd|rd|th)\s+season\b/i)
         || n.match(/\bS(\d+)\b/);
    if (m) return +m[1];
    m = n.match(/\b(second|third|fourth|fifth)\s+season\b/i);
    if (m) return {second: 2, third: 3, fourth: 4, fifth: 5}[m[1].toLowerCase()];
    m = n.match(/\s(II|III|IV|V|VI|VII|VIII|IX)(?=\s*$|\s*[:\-–(])/);
    if (m) return ROMANOS[m[1].toLowerCase()];
    return 0;
  }

  function numParte(n) {
    const m = n.match(/\b(?:part|parte|cour)\s*(\d+)/i) || n.match(/\b(\d+)(?:st|nd|rd|th)\s+(?:part|cour)\b/i);
    return m ? +m[1] : 0;
  }

  // Palabras comunes al principio de todos los nombres de la carpeta.
  function prefijoComun(nombres) {
    const ws = nombres.map(n => n.split(/\s+/));
    if (!ws.length) return 0;
    let k = 0;
    while (ws.every(w => w[k] !== undefined && w[k].toLowerCase() === ws[0][k].toLowerCase())) k++;
    return k;
  }

  function subtitulo(nombre, prefijo, base) {
    // Se quita lo más largo que se pueda: el nombre de la carpeta o las
    // palabras que comparten todas («Demon Slayer: Kimetsu no Yaiba …»).
    const cands = [];
    if (base && nombre.toLowerCase().startsWith(base.toLowerCase()) && nombre.length > base.length) {
      cands.push(nombre.slice(base.length));
    }
    if (prefijo) cands.push(nombre.split(/\s+/).slice(prefijo).join(' '));
    let s = cands.filter(c => c.replace(/[\s:：\-–—]/g, '')).sort((x, y) => x.length - y.length)[0] || '';
    if (!s.replace(/[\s:：\-–—]/g, '')) {
      const i = nombre.search(/[:：]/);
      s = i >= 0 ? nombre.slice(i + 1) : nombre;
    }
    s = s.replace(/^[\s:：\-–—]+/, '').replace(/[\s:：\-–—]+$/, '').replace(/\s+Arc$/i, '').trim();
    return s.length > 22 ? s.slice(0, 21).trimEnd() + '…' : s;
  }

  function miraruTemporadas(animes, base) {
    const lista = animes || [];
    const nombres = lista.filter(a => !esPeli(a)).map(a => String(a.nombre || ''));
    const pref = nombres.length > 1 ? prefijoComun(nombres) : 0;
    const etiquetas = [];
    const claves = new Set();
    let extras = 0, primeraSinMarca = true;
    for (const a of lista) {
      // NFKC: «Date A Live Ⅲ» (un solo carácter) pasa a «III».
      const n = String(a.nombre || '').normalize('NFKC');
      if (esPeli(a)) { etiquetas.push('🎬'); continue; }
      const caps = parseInt(a.capitulos, 10) || 0;
      const t = numTemporada(n), p = numParte(n);
      const fin = /\bfinal\s+(?:season|chapters?)\b|\bthe\s+final\b/i.test(n);
      const esp = n.match(/\bspecials?\b\s*(\d+)?/i);
      const ova = /\b(?:OVA|OAD|ONA)\b/i.test(n);
      let et, clave = null;
      if (fin) {
        et = 'Final' + (esp ? ' Esp.' + (esp[1] ? ' ' + esp[1] : '') : p ? ' P' + p : '');
        clave = 'final';
      } else if (esp) {
        et = 'Esp.' + (esp[1] ? ' ' + esp[1] : '');
      } else if (ova) {
        et = 'OVA';
      } else if (t) {
        et = 'T' + t + (p ? ' P' + p : '');
        clave = 't' + t;
      } else if (p) {
        // «TO THE TOP Part 2»: la parte 2 de esa temporada, no una nueva.
        const sinParte = n.replace(/\s*\b(?:part|parte|cour)\s*\d+|\s*\b\d+(?:st|nd|rd|th)\s+(?:part|cour)\b/ig, '');
        const sub = sinParte.toLowerCase() === (base || '').toLowerCase() ? '' : subtitulo(sinParte, pref, base);
        et = (sub && sub !== sinParte ? sub + ' ' : '') + 'P' + p;
        clave = sub ? 'sub:' + sub : 'p';
      } else if (primeraSinMarca && (caps === 0 || caps > 4)) {
        et = 'T1';
        clave = 't1';
        primeraSinMarca = false;
      } else {
        et = subtitulo(n, pref, base) || 'Extra';
        // Un arco largo (Demon Slayer) es una temporada; 2-3 capítulos, un extra.
        if (caps === 0 || caps > 4) clave = 'sub:' + et;
      }
      if (clave) claves.add(clave); else extras++;
      etiquetas.push(et);
    }
    return {etiquetas, temporadas: claves.size, extras};
  }

  raiz.miraruTemporadas = miraruTemporadas;
  if (typeof module !== 'undefined') module.exports = miraruTemporadas;
})(typeof window !== 'undefined' ? window : globalThis);
