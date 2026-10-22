"""
Test de la tabla de rutas de la app (regresión de la división de main.py).

Tarea 7 dividió main.py en routers (routes/*.py). Para garantizar que la
división NO cambia el API público, se capturó a mano el set de rutas
(path, method) que exponía `main.app` ANTES de dividir y se pinned aquí: después
del refactor el conjunto debe ser EXACTAMENTE el mismo (ni una ruta de más,
ni una de menos, ni un método distinto).

Comparación sobre sets (no listas): el orden de registro lo gobiernan los
include_router y no forma parte del contrato; lo que sí se pinza es que
ninguna ruta cambie de path, método o clase de respuesta (las clases no el
test: lo cubre el resto de la suite HTTP).
"""
from __future__ import annotations

import os
import tempfile

# Aislar la BD antes de importar main (patrón de test_api.py / test_validacion).
_TMP = tempfile.mkdtemp(prefix="miraru_route_set_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "route_set.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
# Sin hilos de fondo (ver conftest y main._sin_hilos_de_fondo).
os.environ.setdefault("MIRARU_SIN_HILOS_FONDO", "1")

from fastapi.routing import APIRoute  # noqa: E402
from starlette.routing import Mount  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

import main  # noqa: E402

# Tabla pinned capturada al commit PRE-refactor (main.py monolito). Se incluye
# la montura /static y las rutas automáticas de docs porque forman parte de
# la supercie pública real que ven los clientes.
_RUTAS_PINADAS = {
    ("/", "GET"),
    ("/app", "GET"),
    ("/calendario", "GET"),
    ("/docs", "GET"),
    ("/docs/oauth2-redirect", "GET"),
    ("/favicon.ico", "GET"),
    ("/import", "GET"),
    ("/mobile", "GET"),
    ("/novedades", "GET"),
    ("/openapi.json", "GET"),
    ("/peliculas", "GET"),
    ("/recomendaciones", "GET"),
    ("/redoc", "GET"),
    ("/setup", "GET"),
    ("/stats", "GET"),
    ("/sw.js", "GET"),
    ("/api/achievements", "GET"),
    ("/api/actualizacion/espera", "GET"),
    ("/api/actualizar", "POST"),
    ("/api/anilist/callback", "GET"),
    ("/api/anilist/connect", "POST"),
    ("/api/anilist/disconnect", "POST"),
    ("/api/anilist/pull", "POST"),
    ("/api/anilist/push", "POST"),
    ("/api/anilist/resolve-ids", "POST"),
    ("/api/anilist/status", "GET"),
    ("/api/animeav1/connect", "POST"),
    ("/api/animeav1/disconnect", "POST"),
    ("/api/animeav1/pull", "POST"),
    ("/api/animeav1/push", "POST"),
    ("/api/animeav1/status", "GET"),
    ("/api/animes", "GET"),
    ("/api/animes", "POST"),
    ("/api/animes/lista/{nombre_lista}", "GET"),
    ("/api/animes/random", "GET"),
    ("/api/animes/refrescar", "POST"),
    ("/api/animes/restore", "POST"),
    ("/api/animes/search", "GET"),
    ("/api/animes/slim", "GET"),
    ("/api/animes/{nombre:path}", "DELETE"),
    ("/api/animes/{nombre:path}", "PATCH"),
    ("/api/animes/{nombre:path}/extra", "GET"),
    ("/api/animes/{nombre:path}/favorito", "POST"),
    ("/api/animes/{nombre:path}/historial", "GET"),
    ("/api/animes/{nombre:path}/nota", "PATCH"),
    ("/api/animes/{nombre:path}/notas-episodio", "GET"),
    ("/api/animes/{nombre:path}/notas-episodio/{episodio}", "DELETE"),
    ("/api/animes/{nombre:path}/notas-episodio/{episodio}", "POST"),
    ("/api/animes/{nombre:path}/notif", "POST"),
    ("/api/animes/{nombre:path}/personajes", "GET"),
    ("/api/animes/{nombre:path}/plus1", "POST"),
    ("/api/animes/{nombre:path}/relacionados", "GET"),
    ("/api/animes/{nombre:path}/scores", "GET"),
    ("/api/animes/{nombre:path}/tags", "GET"),
    ("/api/animes/{nombre:path}/tags", "POST"),
    ("/api/animes/{nombre:path}/tags/{tag}", "DELETE"),
    ("/api/animes/{nombre:path}/themes", "GET"),
    ("/api/apagar", "POST"),
    ("/api/backup", "POST"),
    ("/api/backups", "GET"),
    ("/api/buscar", "POST"),
    ("/api/buscar/franquicia", "POST"),
    ("/api/buscar/manga", "POST"),
    ("/api/buscar/manga/multi", "POST"),
    ("/api/buscar/multi", "POST"),
    ("/api/calendario", "GET"),
    ("/api/continuar", "GET"),
    ("/api/discord", "GET"),
    ("/api/discord", "POST"),
    ("/api/export/csv", "GET"),
    ("/api/export/json", "GET"),
    ("/api/export/share", "GET"),
    ("/api/favoritos", "GET"),
    ("/api/franquicias", "GET"),
    ("/api/fuentes", "GET"),
    ("/api/gamificacion", "GET"),
    ("/api/grupos", "POST"),
    ("/api/health", "GET"),
    ("/api/heatmap", "GET"),
    ("/api/historial/timeline", "GET"),
    ("/api/i18n/ui", "GET"),
    ("/api/import/anilist", "POST"),
    ("/api/import/bulk", "POST"),
    ("/api/import/detect", "POST"),
    ("/api/import/mal-xml", "POST"),
    ("/api/lang", "GET"),
    ("/api/lang", "POST"),
    ("/api/langs", "GET"),
    ("/api/listas", "GET"),
    ("/api/manga", "POST"),
    ("/api/media", "GET"),
    ("/api/media", "POST"),
    ("/api/media/buscar", "POST"),
    ("/api/media/export/csv", "GET"),
    ("/api/media/export/json", "GET"),
    ("/api/media/stats", "GET"),
    ("/api/media/tendencias", "GET"),
    ("/api/media/tmdb-key", "GET"),
    ("/api/media/tmdb-key", "POST"),
    ("/api/media/{media_id}", "DELETE"),
    ("/api/media/{media_id}", "PATCH"),
    ("/api/mobile/animes", "GET"),
    ("/api/mobile/animes/{nombre:path}", "PATCH"),
    ("/api/mobile/animes/{nombre:path}/plus1", "POST"),
    ("/api/mobile/auth", "POST"),
    ("/api/mobile/disable", "POST"),
    ("/api/mobile/enable", "POST"),
    ("/api/mobile/ping", "GET"),
    ("/api/mobile/set-pin", "POST"),
    ("/api/mobile/stats", "GET"),
    ("/api/mobile/status", "GET"),
    ("/api/noticias", "GET"),
    ("/api/notif/activas", "GET"),
    ("/api/notif/check", "GET"),
    ("/api/notif/config-email", "GET"),
    ("/api/notif/config-email", "POST"),
    ("/api/notif/test-email", "POST"),
    ("/api/novedades", "GET"),
    ("/api/perfil", "GET"),
    ("/api/perfil", "POST"),
    ("/api/perfil/avatar", "GET"),
    ("/api/perfil/avatar", "POST"),
    ("/api/perfil/compartir", "GET"),
    ("/api/perfil/compartir/html", "GET"),
    ("/api/push/status", "GET"),
    ("/api/push/subscribe", "POST"),
    ("/api/push/test", "POST"),
    ("/api/push/unsubscribe", "POST"),
    ("/api/push/vapid", "GET"),
    ("/api/que-veo", "GET"),
    ("/api/recomendaciones", "GET"),
    ("/api/recomendaciones/principiante", "GET"),
    ("/api/refrescar/estado", "GET"),
    ("/api/setup/status", "GET"),
    ("/api/setup/upload-credentials", "POST"),
    ("/api/setup/verify", "POST"),
    ("/api/stats", "GET"),
    ("/api/stats/completion", "GET"),
    ("/api/stats/global", "GET"),
    ("/api/stats/wrapped", "GET"),
    ("/api/streak", "GET"),
    ("/api/streak/checkin", "POST"),
    ("/api/suggest", "GET"),
    ("/api/sync", "POST"),
    ("/api/sync/status", "GET"),
    ("/api/trabajos/{tid}", "GET"),
    ("/api/trabajos/{tid}/cancelar", "POST"),
    ("/api/version", "GET"),
    ("/api/version/latest", "GET"),
    ("/api/watch-folder/log", "GET"),
    ("/api/watch-folder/start", "POST"),
    ("/api/watch-folder/status", "GET"),
    ("/api/watch-folder/stop", "POST"),
    ("<mount:/static>", "*"),
}


def _pares_reales() -> set[tuple[str, str]]:
    """Extrae (path, método) de la app real. Las monturas entran como
    ("<mount:path>", "*") para poder compararlas también."""
    out: set[tuple[str, str]] = set()
    for r in main.app.routes:
        if isinstance(r, Mount):
            out.add((f"<mount:{r.path}>", "*"))
            continue
        if isinstance(r, APIRoute) or hasattr(r, "methods"):
            for m in r.methods:  # type: ignore[attr-defined]
                if m in ("HEAD", "OPTIONS"):
                    continue
                out.add((r.path, m))
        else:
            out.add((r.path, "*"))
    return out


def test_la_tabla_de_rutas_es_exactamente_la_del_pre_refactor():
    """Ninguna ruta nueva, ninguna desaparecida, ningún método cambiado."""
    reales = _pares_reales()
    faltan = _RUTAS_PINADAS - reales
    sobran = reales - _RUTAS_PINADAS
    assert not faltan, f"Rutas que FALTAN tras la división: {sorted(faltan)}"
    assert not sobran, f"Rutas que SOBRAN tras la división: {sorted(sobran)}"


def test_static_se_monta_con_staticfiles():
    """La montura /static sigue siendo StaticFiles con name='static'."""
    monturas = [r for r in main.app.routes if isinstance(r, Mount)
                and getattr(r, "name", "") == "static"]
    assert len(monturas) == 1
    assert isinstance(monturas[0].app, StaticFiles)
