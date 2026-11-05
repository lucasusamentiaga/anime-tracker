"""Novedades de cada versión: lo que se enseña en la ventana «Novedades» la
primera vez que se abre Miraru tras actualizar.

Cada versión tiene su tarjeta. Quien se salta versiones (p. ej. de la 2.14 a
la 2.16) ve las novedades de todas las que se perdió, la más nueva primero.
"""
from __future__ import annotations

# Para añadir una versión: una entrada nueva ARRIBA del todo.
# icono: emoji · titulo: corto (≤ 40 letras) · texto: una frase.
# accion (opcional): {"texto": "...", "url": "/app#..."} → botón dentro del punto.
NOVEDADES: list[dict] = [
    {
        "version": "2.16.3",
        "titulo": "Menos repetidos y más notas de IMDb",
        "puntos": [
            {"icono": "🧹", "titulo": "Repetidos, también sin identificar",
             "texto": "Miraru junta ahora los animes repetidos aunque uno no estuviera identificado, y lo hace nada más arrancar."},
            {"icono": "⭐", "titulo": "IMDb en casi todo",
             "texto": "La nota sale abajo a la izquierda de cada portada y ahora también en temporadas sin ficha propia (llevan la de su serie)."},
            {"icono": "🔔", "titulo": "Avisos más claros",
             "texto": "El número rojo del botón Avisos son episodios nuevos que aún no has visto."},
            {"icono": "📚", "titulo": "Temporadas de verdad",
             "texto": "Las carpetas dicen «T3 P2», «Final» u «OVA» en vez de numerar cada entrada, y van en orden de emisión."},
            {"icono": "🧩", "titulo": "AnimeAV1 más listo",
             "texto": "Lo que ya viste entero en AnimeAV1 entra como completado y lo que llevas a medias, como viendo."},
        ],
    },
    {
        "version": "2.16.2",
        "titulo": "Anime y manga, cada uno en su sitio",
        "puntos": [
            {"icono": "📖", "titulo": "Pestañas Anime y Manga",
             "texto": "Si tienes manga, arriba de tu lista eliges qué ver: anime, manga o todo. Las cifras de la cabecera van con la pestaña."},
            {"icono": "🔍", "titulo": "Buscar manga de verdad",
             "texto": "Con «📖 Manga» elegido, el buscador encuentra y añade manga (antes podía guardarlo como anime)."},
            {"icono": "🤝", "titulo": "El manga y su anime, juntos sin chocar",
             "texto": "Ya puedes tener el anime y el manga de la misma obra aunque se llamen igual, y AniList no mezcla sus progresos."},
            {"icono": "📊", "titulo": "Horas y logros solo con anime",
             "texto": "Los capítulos leídos dan su propia XP y ya no cuentan como horas de anime ni para tu rango ninja."},
        ],
    },
    {
        "version": "2.16.1",
        "titulo": "Sin repetidos y con nota de IMDb",
        "puntos": [
            {"icono": "🧹", "titulo": "Adiós a los repetidos",
             "texto": "Si un anime estaba dos veces (con nombres distintos según de dónde llegó), Miraru los junta en uno sin perder nada."},
            {"icono": "⭐", "titulo": "Nota de IMDb",
             "texto": "Cada anime lleva su nota de IMDb en una esquina, en tu lista y al buscar."},
            {"icono": "🧩", "titulo": "Tus listas de AnimeAV1",
             "texto": "La extensión trae también lo que tienes en «Mis Listas» de AnimeAV1, sin duplicar nada.",
             "accion": {"texto": "Ver la extensión", "url": "/app#extension"}},
            {"icono": "🏅", "titulo": "Niveles y logros renovados",
             "texto": "Títulos por nivel, de dónde sale tu XP, tu camino ninja y cuánto te falta para cada logro.",
             "accion": {"texto": "Ver mis logros", "url": "/stats#logros-section"}},
            {"icono": "📸", "titulo": "«Mi año en anime», más visual",
             "texto": "La imagen para compartir lleva las portadas de lo que más viste."},
            {"icono": "🎬", "titulo": "«Pelis» ahora es «No Anime»",
             "texto": "Y en Estadísticas puedes pulsar Completados, Viendo ahora o Episodios este año para ver la lista."},
        ],
    },
    {
        "version": "2.16.0",
        "titulo": "Más rápida, más clara y con recorrido guiado",
        "puntos": [
            {"icono": "🧭", "titulo": "Recorrido por la app",
             "texto": "Te enseñamos cada parte de Miraru paso a paso. Repítelo cuando quieras con el botón «?» de abajo a la derecha.",
             "accion": {"texto": "Verlo ahora", "url": "/app#recorrido"}},
            {"icono": "📊", "titulo": "Tu «Mi año en anime»",
             "texto": "Meses, rachas, lo que más viste y una imagen para compartir. Y las estadísticas, con dos cifras nuevas.",
             "accion": {"texto": "Ver mi año", "url": "/stats#mi-ano"}},
            {"icono": "📱", "titulo": "En el móvil, sin instalar nada",
             "texto": "Escanea un QR y Miraru se abre en el navegador de tu móvil (misma WiFi).",
             "accion": {"texto": "Activarlo", "url": "/mobile"}},
            {"icono": "📂", "titulo": "Compartir por carpetas",
             "texto": "Tu biblioteca compartida separa anime de series y películas, con cada saga en su carpeta."},
            {"icono": "✨", "titulo": "Más cómoda",
             "texto": "Un solo menú al buscar, desplegables más claros y la lista ya no salta arriba sola."},
            {"icono": "📗", "titulo": "Google Sheets al día",
             "texto": "Cualquier cambio llega a tu hoja de cálculo sola, también lo que viene de AniList o AnimeAV1."},
        ],
    },
    {
        "version": "2.15.0",
        "titulo": "Tu lista, a salvo en tu nube",
        "puntos": [
            {"icono": "☁️", "titulo": "Copia en la nube automática",
             "texto": "Miraru guarda una copia en tu OneDrive, Google Drive o Dropbox. Si formateas el PC, la recuperas con un clic.",
             "accion": {"texto": "Ver mi copia", "url": "/app#copia"}},
            {"icono": "🧩", "titulo": "Conecta AnimeAV1",
             "texto": "Con la extensión para Chrome, cada episodio que marcas como visto en AnimeAV1 se apunta solo en Miraru.",
             "accion": {"texto": "Cómo se instala", "url": "/app#animeav1"}},
            {"icono": "🔔", "titulo": "Aviso de actualizaciones",
             "texto": "Cuando salga una versión nueva te avisaremos con lo que trae."},
        ],
    },
]


def _clave(v: str) -> tuple:
    out = []
    for p in (v or "0").split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def pendientes(vista: str | None, actual: str, maximo: int = 3) -> list[dict]:
    """Versiones con novedades que el usuario aún no ha visto: más nuevas que
    `vista` y no más nuevas que `actual` (por si el código va por delante)."""
    v0, v1 = _clave(vista or "0"), _clave(actual)
    out = [n for n in NOVEDADES if v0 < _clave(n["version"]) <= v1]
    out.sort(key=lambda n: _clave(n["version"]), reverse=True)
    return out[:maximo]
