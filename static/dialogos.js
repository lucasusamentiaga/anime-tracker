/* Miraru — ventanas propias en lugar de alert(), confirm() y prompt().
 *
 * Las del navegador son feas, no siguen el tema, no se traducen, bloquean la
 * página entera y en algunos navegadores muestran "127.0.0.1 dice…". Estas
 * devuelven una promesa:
 *
 *   if (!(await miraruConfirmar('¿Eliminar?', {ok: 'Eliminar', peligro: true}))) return;
 *   const nombre = await miraruPedir('Nombre de la vista:', 'Mi vista');   // null = cancelado
 *   await miraruAviso('Primero pega el texto');
 *
 * Teclado: Enter acepta, Escape cancela. Los textos pasan por el traductor de
 * la interfaz (i18n-dom.js) si está cargado.
 */
(function () {
  'use strict';
  const tr = s => (window.miraruTraducir ? window.miraruTraducir(s) : s);

  function estilos() {
    if (document.getElementById('mdlg-css')) return;
    const st = document.createElement('style');
    st.id = 'mdlg-css';
    st.textContent = `
.mdlg-fondo{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);display:flex;align-items:center;
  justify-content:center;z-index:10000;padding:16px;animation:mdlgIn .12s ease}
.mdlg{background:var(--bg-elev,#100d1c);color:var(--fg,#edecf4);border:1px solid var(--border,#2b2542);
  border-radius:14px;max-width:420px;width:100%;padding:20px;box-shadow:0 18px 50px rgba(0,0,0,.45);
  font:14px/1.5 Inter,system-ui,sans-serif}
.mdlg p{margin:0 0 14px;white-space:pre-line}
.mdlg input{width:100%;box-sizing:border-box;padding:9px 11px;border-radius:9px;margin:0 0 14px;
  border:1px solid var(--border,#2b2542);background:var(--bg,#0a0812);color:inherit;font:inherit}
.mdlg input:focus{outline:2px solid var(--accent,#7c3aed);outline-offset:1px}
.mdlg-bot{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}
.mdlg-bot button{border:1px solid var(--border,#2b2542);background:transparent;color:inherit;
  border-radius:9px;padding:8px 16px;font:600 13px Inter,system-ui,sans-serif;cursor:pointer}
.mdlg-bot .mdlg-ok{background:var(--accent,#7c3aed);border-color:transparent;color:#fff}
.mdlg-bot .mdlg-ok.peligro{background:#dc2626}
@keyframes mdlgIn{from{opacity:0}to{opacity:1}}`;
    document.head.appendChild(st);
  }

  function abrir({texto, conCampo = false, valor = '', ok = 'Aceptar', cancelar = 'Cancelar',
                  soloAceptar = false, peligro = false}) {
    estilos();
    return new Promise(resolve => {
      const previo = document.activeElement;
      const fondo = document.createElement('div');
      fondo.className = 'mdlg-fondo';
      const caja = document.createElement('div');
      caja.className = 'mdlg';
      caja.setAttribute('role', soloAceptar ? 'alertdialog' : 'dialog');
      caja.setAttribute('aria-modal', 'true');
      const p = document.createElement('p');
      p.textContent = tr(texto);
      caja.appendChild(p);
      let campo = null;
      if (conCampo) {
        campo = document.createElement('input');
        campo.value = valor || '';
        campo.maxLength = 200;
        caja.appendChild(campo);
      }
      const bot = document.createElement('div');
      bot.className = 'mdlg-bot';
      const bOk = document.createElement('button');
      bOk.className = 'mdlg-ok' + (peligro ? ' peligro' : '');
      bOk.textContent = tr(ok);
      if (!soloAceptar) {
        const bNo = document.createElement('button');
        bNo.textContent = tr(cancelar);
        bNo.onclick = () => cerrar(false);
        bot.appendChild(bNo);
      }
      bot.appendChild(bOk);
      caja.appendChild(bot);
      fondo.appendChild(caja);

      function cerrar(acepta) {
        document.removeEventListener('keydown', teclas, true);
        fondo.remove();
        if (previo && previo.focus) { try { previo.focus(); } catch (_) { /* nada */ } }
        if (conCampo) resolve(acepta ? campo.value : null);
        else resolve(soloAceptar ? undefined : acepta);
      }
      function teclas(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cerrar(false); }
        else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); cerrar(true); }
      }
      bOk.onclick = () => cerrar(true);
      fondo.addEventListener('mousedown', e => { if (e.target === fondo) cerrar(false); });
      document.addEventListener('keydown', teclas, true);
      document.body.appendChild(fondo);
      (campo || bOk).focus();
      if (campo) campo.select();
    });
  }

  window.miraruConfirmar = (texto, op = {}) => abrir(Object.assign({texto}, op));
  window.miraruPedir = (texto, valor = '', op = {}) =>
    abrir(Object.assign({texto, conCampo: true, valor}, op));
  window.miraruAviso = (texto, op = {}) =>
    abrir(Object.assign({texto, soloAceptar: true}, op));
})();
