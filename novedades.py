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
