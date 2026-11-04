"""
Genera una página HTML autocontenida con la biblioteca del usuario, para
compartir (enviar el archivo o subirlo a GitHub Pages → URL pública). Sin
backend ni dependencias externas más allá de las imágenes de portada (remotas).

v2.16: pestañas «Anime», «Manga» (si hay) y «No Anime», y el anime agrupado en
carpetas por franquicia, igual que en la pantalla principal de Miraru.

Función pura y testeable: render_share_html(animes, media, perfil, stats, franquicias).
"""
from __future__ import annotations

import html
from typing import Optional

import stats_util

_ESTADOS = {
    "viendo": "Viendo", "watching": "Viendo",
    "completado": "Completado", "completed": "Completado",
    "pendiente": "Pendiente", "pending": "Pendiente", "plan": "Pendiente",
    "pausa": "En pausa", "paused": "En pausa",
    "abandonado": "Abandonado", "dropped": "Abandonado",
}
_CLASES = {"Viendo": "st-v", "Completado": "st-c", "Pendiente": "st-p",
           "En pausa": "st-z", "Abandonado": "st-a"}


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _estado(e) -> str:
    return _ESTADOS.get(str(e or "").lower(), str(e or "").capitalize())


def _img(imagen: str) -> str:
    return (f'<img loading="lazy" src="{_esc(imagen)}" alt="">'
            if imagen else '<div class="noimg"></div>')


def _card(titulo: str, imagen: str, estado: str, extra: str, manga: bool = False) -> str:
    est = _estado(estado)
    clase = _CLASES.get(est, "")
    if manga and est == "Viendo":
        est = "Leyendo"
    return (
        f'<div class="card" data-t="{_esc(str(titulo).casefold())}">'
        f'<div class="thumb">{_img(imagen)}</div>'
        f'<div class="meta"><div class="t">{_esc(titulo)}</div>'
        f'<div class="s"><i class="dot {clase}"></i>{_esc(est)}{_esc(extra)}</div></div></div>'
    )


def _extra_anime(a: dict) -> str:
    cap = str(a.get("capitulos") or "").strip()
    if cap and cap not in ("?", "película"):
        return f" · {cap} {'caps' if (a.get('tipo') or 'anime') == 'manga' else 'eps'}"
    return " · película" if cap == "película" else ""


def _carpeta(f: dict, idx: int) -> str:
    miembros = f.get("animes") or []
    nombre = f.get("nombre", "")
    portada = next((m.get("imagen") for m in miembros if m.get("imagen")), "")
    completos = sum(1 for m in miembros if _estado(m.get("estado_usuario")) == "Completado")
    buscable = " ".join([str(nombre)] + [str(m.get("nombre", "")) for m in miembros]).casefold()
    dentro = "".join(_card(m.get("nombre", ""), m.get("imagen", ""), m.get("estado_usuario", ""),
                           _extra_anime(m), (m.get("tipo") or "anime") == "manga") for m in miembros)
    return (
        f'<button type="button" class="card carpeta" data-c="{idx}" data-t="{_esc(buscable)}"'
        f' aria-label="{_esc(nombre)}: {len(miembros)} títulos">'
        f'<div class="thumb">{_img(portada)}<span class="kind">📁 {len(miembros)}</span></div>'
        f'<div class="meta"><div class="t">{_esc(nombre)}</div>'
        f'<div class="s">{len(miembros)} títulos · {completos} completado{"" if completos == 1 else "s"}</div></div></button>'
        f'<template id="c{idx}"><h2>{_esc(nombre)}</h2><div class="grid">{dentro}</div></template>'
    )


def render_share_html(
    animes: list[dict],
    media: list[dict],
    perfil: Optional[dict] = None,
    stats: Optional[dict] = None,
    franquicias: Optional[list[dict]] = None,
) -> str:
    perfil = perfil or {}
    nombre = perfil.get("nombre_usuario") or "Mi biblioteca"
    st = stats or stats_util.stats_globales(animes, media)

    # ── Anime y manga (v2.16.2: el manga en su pestaña): carpetas y sueltos ──
    def _es_manga(a):
        return (a.get("tipo") or "anime") == "manga"
    mangas = [a for a in animes if _es_manga(a)]
    animes = [a for a in animes if not _es_manga(a)]
    if franquicias is None:
        franquicias = [{"nombre": a.get("nombre", ""), "animes": [a]} for a in animes + mangas]
    anime_html, manga_html = [], []
    for i, f in enumerate(franquicias):
        miembros = f.get("animes") or []
        if not miembros:
            continue
        dest = manga_html if _es_manga(miembros[0]) else anime_html
        if len(miembros) > 1:
            dest.append(_carpeta(f, i))
        else:
            a = miembros[0]
            dest.append(_card(a.get("nombre", ""), a.get("imagen", ""),
                              a.get("estado_usuario", ""), _extra_anime(a), _es_manga(a)))
    if not anime_html:
        anime_html = ['<p class="vacio">Todavía no hay anime.</p>']

    # ── Series y películas (no anime) ──
    series = [m for m in media if (m.get("tipo") or "pelicula") != "pelicula"]
    pelis = [m for m in media if (m.get("tipo") or "pelicula") == "pelicula"]

    def _media_cards(lst):
        return "".join(_card(m.get("titulo", ""), m.get("imagen", ""), m.get("estado_usuario", ""),
                             f" · {m.get('anio')}" if m.get("anio") else "") for m in lst)

    otros_html = ""
    if series:
        otros_html += (f'<h2 class="sec">Series <span>{len(series)}</span></h2>'
                       f'<div class="grid">{_media_cards(series)}</div>')
    if pelis:
        otros_html += (f'<h2 class="sec">Películas <span>{len(pelis)}</span></h2>'
                       f'<div class="grid">{_media_cards(pelis)}</div>')
    if not otros_html:
        otros_html = '<p class="vacio">Todavía no hay series ni películas.</p>'

    def metric(v, l):
        return f'<div class="metric"><b>{_esc(v)}</b><span>{_esc(l)}</span></div>'

    tab_manga = panel_manga = ""
    if mangas:
        tab_manga = ('<button class="tab" role="tab" aria-selected="false" aria-controls="p-manga" '
                     f'data-p="p-manga">📖 Manga<span>{len(mangas)}</span></button>\n    ')
        panel_manga = ('<section class="panel" id="p-manga" role="tabpanel" hidden>'
                       f'<div class="grid">{"".join(manga_html)}</div></section>\n')

    metrics = "".join([
        metric(st["animes"], "anime"),
        metric(st["series"], "series"),
        metric(st["peliculas"], "películas"),
        metric(st["total_episodios"], "episodios"),
        metric(st["horas_totales"], "horas"),
    ] + ([metric(st.get("mangas", 0), "manga")] if st.get("mangas") else []))

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(nombre)} — Miraru</title>
<style>
:root{{--bg:#0a0812;--card:#181426;--card2:#110e1c;--line:#2b2542;--fg:#edecf4;--muted:#a49dc0;--accent:#7c3aed;--light:#c4b1ff}}
*{{box-sizing:border-box;margin:0}}
body{{background:var(--bg);color:var(--fg);font-family:Inter,'Segoe UI',system-ui,sans-serif;min-height:100vh;
  background-image:radial-gradient(800px circle at 10% 0%,rgba(124,58,237,.14),transparent 45%),
  radial-gradient(700px circle at 95% 5%,rgba(217,70,239,.08),transparent 42%)}}
.wrap{{max-width:1120px;margin:0 auto;padding:40px 20px 60px}}
header{{text-align:center;margin-bottom:18px}}
h1{{font-size:32px;font-weight:800;letter-spacing:-.5px;text-wrap:balance}}
.by{{color:var(--muted);font-size:13px;margin-top:6px}}
.metrics{{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin:22px 0 4px}}
.metric{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 18px;min-width:96px;text-align:center}}
.metric b{{display:block;font-size:22px;font-weight:800;font-variant-numeric:tabular-nums}}
.metric span{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.barra{{position:sticky;top:0;z-index:5;display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:12px 0 16px;margin-bottom:6px;
  background:linear-gradient(var(--bg) 75%,transparent)}}
.tabs{{display:flex;gap:4px;padding:4px;background:var(--card2);border:1px solid var(--line);border-radius:12px}}
.tab{{border:0;cursor:pointer;padding:9px 16px;border-radius:9px;background:transparent;color:var(--muted);
  font-family:inherit;font-size:14px;font-weight:600;transition:background .2s,color .2s}}
.tab:hover{{color:var(--fg)}}
.tab span{{opacity:.75;font-weight:500;margin-left:6px;font-variant-numeric:tabular-nums}}
.tab[aria-selected=true]{{background:var(--accent);color:#fff}}
.tab:focus-visible,.carpeta:focus-visible,.cerrar:focus-visible,.buscar:focus-visible{{outline:2px solid var(--light);outline-offset:2px}}
.buscar{{flex:1;min-width:180px;max-width:320px;margin-left:auto;padding:10px 14px;border-radius:11px;border:1px solid var(--line);
  background:var(--card2);color:var(--fg);font-family:inherit;font-size:14px}}
.buscar::placeholder{{color:var(--muted)}}
.panel[hidden]{{display:none}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:20px 16px;padding-top:10px}}
.card{{display:block;width:100%;text-align:left;font:inherit;color:inherit;padding:0;background:var(--card);
  border:1px solid #221d33;border-radius:13px;overflow:hidden}}
.thumb{{position:relative;aspect-ratio:3/4;background:#221d33}}
.thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
.noimg{{width:100%;height:100%;background:linear-gradient(135deg,#1c1830,#2b2542)}}
.kind{{position:absolute;top:8px;left:8px;z-index:3;font-size:11px;font-weight:700;background:var(--accent);color:#fff;
  border-radius:99px;padding:3px 9px}}
.carpeta{{position:relative;cursor:pointer;overflow:visible;border-color:rgba(124,58,237,.45);
  transition:transform .25s cubic-bezier(.22,1,.36,1)}}
.carpeta::before,.carpeta::after{{content:"";position:absolute;left:8px;right:8px;top:-5px;height:20px;border-radius:12px 12px 0 0;
  background:#3b2f63;border:1px solid rgba(124,58,237,.5);border-bottom:0;z-index:-1;transition:transform .25s cubic-bezier(.22,1,.36,1)}}
.carpeta::before{{left:16px;right:16px;top:-10px;background:#2a2147}}
.carpeta:hover{{transform:translateY(-3px)}}
.carpeta:hover::before{{transform:translateY(-3px)}}
.carpeta .thumb{{border-radius:12px 12px 0 0;overflow:hidden}}
.grid{{isolation:isolate}}
.meta{{padding:8px 10px 10px}}
.meta .t{{font-size:12.5px;font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.meta .s{{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);margin-top:4px}}
.dot{{width:7px;height:7px;border-radius:50%;background:var(--muted);flex-shrink:0}}
.st-v{{background:#38bdf8}}.st-c{{background:#34d399}}.st-p{{background:#fbbf24}}.st-z{{background:#a78bfa}}.st-a{{background:#fb7185}}
h2.sec{{font-size:14px;font-weight:700;color:var(--light);text-transform:uppercase;letter-spacing:.05em;margin:26px 0 12px}}
h2.sec:first-child{{margin-top:4px}}
h2.sec span{{color:var(--muted);font-weight:500}}
.vacio{{color:var(--muted);text-align:center;padding:40px 0}}
.oculto{{display:none!important}}
.fondo{{position:fixed;inset:0;z-index:20;background:rgba(6,4,12,.72);backdrop-filter:blur(6px);display:grid;place-items:center;padding:16px;
  animation:f .25s cubic-bezier(.22,1,.36,1)}}
.caja{{position:relative;width:min(900px,100%);max-height:88vh;overflow:auto;background:var(--card);border:1px solid var(--line);
  border-radius:20px;padding:22px;animation:s .45s cubic-bezier(.16,1,.3,1)}}
.caja h2{{font-size:20px;margin:0 44px 16px 0;text-wrap:balance}}
.cerrar{{position:absolute;top:14px;right:14px;width:34px;height:34px;border:0;border-radius:10px;background:transparent;color:var(--muted);font-size:21px;cursor:pointer}}
.cerrar:hover{{background:rgba(255,255,255,.06);color:var(--fg)}}
@keyframes f{{from{{opacity:0}}}}
@keyframes s{{from{{opacity:0;transform:translateY(12px)}}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
@media (max-width:520px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.buscar{{max-width:none;margin-left:0}}.tab{{padding:9px 11px;font-size:13px}}}}
footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:34px}}
footer a{{color:var(--light);text-decoration:none}}
</style></head>
<body><div class="wrap">
<header><h1>{_esc(nombre)}</h1><div class="by">Mi biblioteca en Miraru</div>
<div class="metrics">{metrics}</div></header>
<div class="barra">
  <div class="tabs" role="tablist">
    <button class="tab" role="tab" aria-selected="true" aria-controls="p-anime" data-p="p-anime">🎌 Anime<span>{len(animes)}</span></button>
    {tab_manga}<button class="tab" role="tab" aria-selected="false" aria-controls="p-otros" data-p="p-otros">🎬 No Anime<span>{len(series) + len(pelis)}</span></button>
  </div>
  <input class="buscar" type="search" placeholder="Buscar un título…" aria-label="Buscar un título">
</div>
<section class="panel" id="p-anime" role="tabpanel"><div class="grid">{''.join(anime_html)}</div></section>
{panel_manga}<section class="panel" id="p-otros" role="tabpanel" hidden>{otros_html}</section>
<footer>Generado con <a href="https://github.com/lucasusamentiaga/anime-tracker">Miraru</a></footer>
</div>
<script>
(function(){{
  var tabs=[].slice.call(document.querySelectorAll('.tab'));
  tabs.forEach(function(t){{t.addEventListener('click',function(){{
    tabs.forEach(function(o){{o.setAttribute('aria-selected',o===t?'true':'false');document.getElementById(o.dataset.p).hidden=o!==t;}});
  }});}});
  var q=document.querySelector('.buscar');
  q.addEventListener('input',function(){{
    var v=q.value.trim().toLowerCase();
    document.querySelectorAll('.panel .grid > .card').forEach(function(c){{
      c.classList.toggle('oculto',!!v&&(c.dataset.t||'').indexOf(v)<0);
    }});
  }});
  document.addEventListener('click',function(e){{
    var c=e.target.closest('.carpeta'); if(!c) return;
    var tpl=document.getElementById('c'+c.dataset.c); if(!tpl) return;
    var f=document.createElement('div'); f.className='fondo';
    var caja=document.createElement('div'); caja.className='caja';
    caja.setAttribute('role','dialog'); caja.setAttribute('aria-modal','true');
    var x=document.createElement('button'); x.className='cerrar'; x.type='button';
    x.setAttribute('aria-label','Cerrar'); x.textContent='×';
    caja.appendChild(x); caja.appendChild(tpl.content.cloneNode(true));
    f.appendChild(caja); document.body.appendChild(f);
    function fuera(){{f.remove();document.removeEventListener('keydown',esc);c.focus();}}
    function esc(ev){{if(ev.key==='Escape')fuera();}}
    x.onclick=fuera; f.addEventListener('click',function(ev){{if(ev.target===f)fuera();}});
    document.addEventListener('keydown',esc); x.focus();
  }});
}})();
</script>
</body></html>"""
