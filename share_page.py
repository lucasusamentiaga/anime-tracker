"""
Genera una página HTML autocontenida con la biblioteca del usuario, para
compartir (enviar el archivo o subirlo a GitHub Pages → URL pública). Sin
backend ni dependencias externas más allá de las imágenes de portada (remotas).

Función pura y testeable: render_share_html(animes, media, perfil, stats).
"""
from __future__ import annotations

import html
from typing import Optional

import stats_util


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _card(titulo: str, imagen: str, estado: str, extra: str, badge: str) -> str:
    img = (
        f'<img loading="lazy" src="{_esc(imagen)}" alt="">'
        if imagen else '<div class="noimg"></div>'
    )
    return (
        '<div class="card">'
        f'<div class="thumb">{img}<span class="kind">{_esc(badge)}</span></div>'
        f'<div class="meta"><div class="t">{_esc(titulo)}</div>'
        f'<div class="s">{_esc(estado)}{_esc(extra)}</div></div></div>'
    )


def render_share_html(
    animes: list[dict],
    media: list[dict],
    perfil: Optional[dict] = None,
    stats: Optional[dict] = None,
) -> str:
    perfil = perfil or {}
    nombre = perfil.get("nombre_usuario") or "Mi biblioteca"
    st = stats or stats_util.stats_globales(animes, media)

    cards = []
    for a in animes:
        cap = a.get("capitulos")
        extra = f" · {cap} eps" if cap and str(cap) not in ("?", "película") else (
            " · película" if str(cap) == "película" else ""
        )
        cards.append(_card(a.get("nombre", ""), a.get("imagen", ""),
                           a.get("estado_usuario", ""), extra, "ANIME"))
    for m in media:
        badge = "PELÍCULA" if (m.get("tipo") or "pelicula") == "pelicula" else "SERIE"
        anio = m.get("anio")
        cards.append(_card(m.get("titulo", ""), m.get("imagen", ""),
                           m.get("estado_usuario", ""), f" · {anio}" if anio else "", badge))

    metric = lambda v, l: f'<div class="metric"><b>{_esc(v)}</b><span>{_esc(l)}</span></div>'
    metrics = "".join([
        metric(st["total_titulos"], "títulos"),
        metric(st["total_episodios"], "episodios"),
        metric(st["horas_totales"], "horas"),
        metric(st["animes"], "anime"),
        metric(st["peliculas"], "películas"),
        metric(st["series"], "series"),
    ])

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(nombre)} — Miraru</title>
<style>
:root{{--bg:#0a0812;--card:#181426;--fg:#edecf4;--muted:#a49dc0;--accent:#a855f7}}
*{{box-sizing:border-box;margin:0}}
body{{background:var(--bg);color:var(--fg);font-family:'Segoe UI',system-ui,sans-serif;
  background-image:radial-gradient(800px circle at 10% 0%,rgba(124,58,237,.14),transparent 45%),
  radial-gradient(700px circle at 95% 5%,rgba(217,70,239,.10),transparent 42%);min-height:100vh}}
.wrap{{max-width:1100px;margin:0 auto;padding:40px 20px 60px}}
header{{text-align:center;margin-bottom:28px}}
h1{{font-size:30px;font-weight:800;letter-spacing:-.5px;
  background:linear-gradient(135deg,#c4b1ff,#a855f7,#d946ef);-webkit-background-clip:text;
  background-clip:text;-webkit-text-fill-color:transparent}}
.by{{color:var(--muted);font-size:13px;margin-top:6px}}
.metrics{{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin:22px 0 30px}}
.metric{{background:var(--card);border:1px solid #2b2542;border-radius:14px;padding:12px 18px;
  min-width:92px;text-align:center}}
.metric b{{display:block;font-size:22px;font-weight:800}}
.metric span{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}}
.card{{background:var(--card);border:1px solid #221d33;border-radius:13px;overflow:hidden}}
.thumb{{position:relative;aspect-ratio:3/4;background:#221d33}}
.thumb img{{width:100%;height:100%;object-fit:cover}}
.noimg{{width:100%;height:100%;background:linear-gradient(135deg,#1c1830,#2b2542)}}
.kind{{position:absolute;top:6px;left:6px;font-size:9px;font-weight:700;letter-spacing:.4px;
  background:rgba(10,8,18,.8);color:#c4b1ff;border:1px solid rgba(168,85,247,.35);
  border-radius:99px;padding:2px 7px}}
.meta{{padding:8px 10px 10px}}
.meta .t{{font-size:12px;font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden}}
.meta .s{{font-size:10px;color:var(--muted);margin-top:3px;text-transform:capitalize}}
footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:34px}}
footer a{{color:#c4b1ff;text-decoration:none}}
</style></head>
<body><div class="wrap">
<header><h1>{_esc(nombre)}</h1><div class="by">Mi biblioteca en Miraru</div>
<div class="metrics">{metrics}</div></header>
<div class="grid">{''.join(cards)}</div>
<footer>Generado con <a href="https://github.com/lucasusamentiaga/anime-tracker">Miraru</a> · anime · series · películas</footer>
</div></body></html>"""
