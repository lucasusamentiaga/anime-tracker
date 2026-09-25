"""
Tests de endpoints con FastAPI TestClient.

Cubren main.py de extremo a extremo (antes ningún test lo importaba). Incluyen
regresiones de bugs reales:
  - /api/version refleja el rebrand (Miraru).
  - POST /api/animes/restore reinserta el registro EXACTO (fix de "Deshacer").
  - /api/stats cuenta los episodios completos de los animes completados.
  - El conversor :path NO se traga las subrutas (PATCH .../nota, DELETE .../tags/x).
"""
from __future__ import annotations

import os
import tempfile

import pytest

# main.py inicializa la BD en el startup, y el mount del proyecto no soporta
# sqlite WAL; aislamos en un tmp escribible antes de importar.
_TMP = tempfile.mkdtemp(prefix="miraru_api_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "api.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

from fastapi.testclient import TestClient  # noqa: E402

import database as db  # noqa: E402
import main  # noqa: E402


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c
    # limpiar tablas entre tests
    with db.get_conn() as conn:
        for t in ("animes", "media", "ep_log", "historial"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM config WHERE key LIKE 'tags:%'")


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_version_refleja_rebrand_miraru(client):
    assert client.get("/api/version").json()["name"] == "Miraru"


def test_restore_reinserta_registro_exacto(client):
    payload = {
        "nombre": "Frieren", "fuente": "anilist", "capitulos": "28",
        "imagen": "http://img", "genero": "Aventura, Fantasía",
        "estado_anime": "Finalizado", "estado_usuario": "completado",
        "puntuacion": 9.5, "episodios_vistos": 28,
    }
    assert client.post("/api/animes/restore", json=payload).status_code == 200
    a = next(x for x in client.get("/api/animes").json()["animes"] if x["nombre"] == "Frieren")
    assert a["capitulos"] == "28"
    assert a["episodios_vistos"] == 28
    assert a["estado_usuario"] == "completado"
    assert a["puntuacion"] == 9.5


def test_stats_cuenta_completados_con_todos_sus_capitulos(client):
    client.post("/api/animes/restore", json={
        "nombre": "X", "capitulos": "12", "estado_usuario": "completado",
        "episodios_vistos": 0,
    })
    s = client.get("/api/stats").json()
    assert s["total_episodes"] >= 12   # completado cuenta sus 12 aunque vistos=0


def test_stats_no_crashea_con_capitulos_no_numericos(client):
    for caps in ("?", "película", ""):
        client.post("/api/animes/restore", json={
            "nombre": f"A{caps or 'vacio'}", "capitulos": caps,
            "estado_usuario": "completado",
        })
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/stats/wrapped").status_code == 200


def test_nota_no_la_traga_la_ruta_catchall(client):
    """Regresión: PATCH .../nota lo capturaba el catch-all PATCH /{nombre:path}."""
    client.post("/api/animes/restore", json={"nombre": "Naruto", "capitulos": "220"})
    r = client.patch("/api/animes/Naruto/nota", json={"nota": "buenísimo"})
    assert r.status_code == 200
    a = next(x for x in client.get("/api/animes").json()["animes"] if x["nombre"] == "Naruto")
    assert a["notas"] == "buenísimo"


def test_tags_alta_y_baja(client):
    """Regresión: DELETE .../tags/{tag} lo capturaba el catch-all DELETE."""
    client.post("/api/animes/restore", json={"nombre": "Naruto", "capitulos": "220"})
    assert client.post("/api/animes/Naruto/tags", json={"tag": "shounen"}).status_code == 200
    assert "shounen" in client.get("/api/animes/Naruto/tags").json()["tags"]
    assert client.delete("/api/animes/Naruto/tags/shounen").status_code == 200
    assert "shounen" not in client.get("/api/animes/Naruto/tags").json()["tags"]


def test_patch_y_delete_generales_siguen_funcionando(client):
    client.post("/api/animes/restore", json={"nombre": "Bleach", "capitulos": "366"})
    assert client.patch("/api/animes/Bleach", json={"episodios_vistos": 5}).status_code == 200
    assert client.delete("/api/animes/Bleach").status_code == 200
    assert all(x["nombre"] != "Bleach" for x in client.get("/api/animes").json()["animes"])


def test_nombre_con_barra_sigue_resolviendo(client):
    """El conversor :path debe seguir aceptando nombres con '/'."""
    client.post("/api/animes/restore", json={"nombre": "Fate/stay night", "capitulos": "24"})
    r = client.patch("/api/animes/Fate/stay night", json={"episodios_vistos": 2})
    assert r.status_code == 200


def test_plus1_no_envia_email_sin_campanita(client, monkeypatch):
    """Regresión: marcar +1 episodio enviaba un correo en CADA clic a cualquier
    anime en emisión, ignorando el interruptor `notif_activa`. Maratonear
    llenaba la bandeja de entrada."""
    enviados = []
    monkeypatch.setattr(main, "_sync_bg", lambda fn, *a: enviados.append(a))
    db.set_config("email_notif", "yo@ejemplo.com")

    # En emisión pero SIN campanita → no debe enviar nada
    client.post("/api/animes/restore", json={
        "nombre": "Sin campanita", "capitulos": "24",
        "estado_anime": "En emisión", "notif_activa": 0,
    })
    client.post("/api/animes/Sin campanita/plus1")
    assert enviados == []

    # Con la campanita activada → sí notifica
    client.post("/api/animes/restore", json={
        "nombre": "Con campanita", "capitulos": "24",
        "estado_anime": "En emisión", "notif_activa": 1,
    })
    client.post("/api/animes/Con campanita/plus1")
    assert len(enviados) == 1

    db.set_config("email_notif", "")   # no dejar el email puesto para otros tests


def test_lifespan_arranca_y_limpia(monkeypatch):
    """El lifespan (que sustituyó a on_event) debe inicializar la BD, lanzar los
    procesos de fondo y limpiar el estado de Discord al cerrar."""
    import discord_presence

    eventos = []
    monkeypatch.setattr(main, "_start_auto_backup_once", lambda: eventos.append("backup"))
    monkeypatch.setattr(main, "_start_cap200_fix_once", lambda: eventos.append("cap200"))
    monkeypatch.setattr(main, "_start_emision_refresh_once", lambda: eventos.append("emision"))
    monkeypatch.setattr(discord_presence, "limpiar", lambda: eventos.append("discord"))

    with TestClient(main.app) as c:
        assert eventos == ["backup", "cap200", "emision"]
        assert c.get("/api/health").status_code == 200
    # Al salir del contexto se ejecuta el apagado
    assert eventos == ["backup", "cap200", "emision", "discord"]


def test_scraper_roto_devuelve_ficha_hueca_y_se_completa(client, monkeypatch):
    """Regresión: cuando una web cambia el CSS, su scraper devuelve una ficha con
    nombre pero sin datos. Como era 'verdadera', la búsqueda la daba por buena y
    el usuario guardaba una entrada vacía. Ahora se rellena con una fuente de API."""
    from scrapers.base import AnimeData

    class _Roto:
        """Simula animeflv tras un rediseño: encuentra el título y nada más."""
        def buscar(self, n):
            return AnimeData(nombre="Naruto", capitulos="?", imagen="", genero=[],
                             sinopsis="", fuente="animeflv", estado_anime="")

    class _Api:
        def buscar(self, n):
            return AnimeData(nombre="NARUTO", capitulos=220, imagen="http://cover",
                             genero=["Acción"], sinopsis="Ninja", fuente="anilist",
                             estado_anime="Finalizado")

    monkeypatch.setattr(main, "SCRAPERS", {"animeflv": _Roto(), "anilist": _Api()})
    r = client.post("/api/buscar", json={"nombre": "Naruto", "fuente": "animeflv"})
    assert r.status_code == 200
    d = r.json()["data"]
    # Se conserva la fuente y el nombre que eligió el usuario…
    assert r.json()["fuente_usada"] == "animeflv"
    assert d["nombre"] == "Naruto"
    # …pero ya no está hueca
    assert d["capitulos"] == 220
    assert d["imagen"] == "http://cover"
    assert d["genero"] == ["Acción"]


def test_ficha_buena_no_se_toca(client, monkeypatch):
    """Si la fuente preferida trae datos completos, no se consulta a ninguna otra."""
    from scrapers.base import AnimeData

    llamadas = []

    class _Buena:
        def buscar(self, n):
            llamadas.append("animeflv")
            return AnimeData(nombre="Bleach", capitulos=366, imagen="http://i",
                             genero=["Acción"], sinopsis="Shinigami",
                             fuente="animeflv", estado_anime="Finalizado")

    class _NoDeberia:
        def buscar(self, n):
            llamadas.append("anilist")
            return None

    monkeypatch.setattr(main, "SCRAPERS", {"animeflv": _Buena(), "anilist": _NoDeberia()})
    r = client.post("/api/buscar", json={"nombre": "Bleach", "fuente": "animeflv"})
    assert r.status_code == 200
    assert r.json()["data"]["capitulos"] == 366
    assert llamadas == ["animeflv"]        # no hubo consulta de relleno


def test_buscar_usa_fallback_cuando_la_fuente_preferida_falla(client, monkeypatch):
    """Regresión: _buscar_con_fallback usaba create_task sobre un Future (TypeError)
    y la búsqueda reventaba (500) cuando la fuente preferida no tenía el anime.
    Ahora debe caer en otra fuente y devolver el resultado."""
    from scrapers.base import AnimeData

    class _Nada:
        def buscar(self, n):
            return None

    class _Encuentra:
        def buscar(self, n):
            return AnimeData(nombre="Cowboy Bebop", capitulos=26, imagen="", genero=[],
                             sinopsis="", fuente="jikan", estado_anime="Finalizado")

    # fuente preferida (anilist) no encuentra; otra (jikan) sí
    monkeypatch.setattr(main, "SCRAPERS", {"anilist": _Nada(), "jikan": _Encuentra()})
    r = client.post("/api/buscar", json={"nombre": "cowboy bebop zzz", "fuente": "anilist"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["data"]["nombre"] == "Cowboy Bebop"
    assert d["fuente_usada"] == "jikan"


def test_anadir_sustituye_portada_anime_planet_y_guarda_anilist_id(client, monkeypatch):
    """Al añadir, una portada de anime-planet (su scraper coge la primera tarjeta
    aunque no coincida) se sustituye por la de AniList y se guarda anilist_id."""
    from scrapers.base import AnimeData

    async def fake_fallback(nombre, fuente):
        return AnimeData(nombre="Naruto", capitulos=220, fuente="animeplanet",
                         imagen="https://cdn.anime-planet.com/anime/primary/road-of-naruto.webp",
                         genero=[], sinopsis="", estado_anime="Finalizado"), "animeplanet"

    class _AL:
        def buscar(self, n, media_type="ANIME"):
            return AnimeData(nombre="Naruto", capitulos=220, imagen="https://s4.anilist.co/naruto.jpg",
                             genero=[], sinopsis="", fuente="anilist", estado_anime="", anilist_id=20)

    monkeypatch.setattr(main, "_buscar_con_fallback", fake_fallback)
    monkeypatch.setitem(main.SCRAPERS, "anilist", _AL())
    r = client.post("/api/animes", json={"nombre": "Naruto", "fuente": "animeplanet"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["imagen"] == "https://s4.anilist.co/naruto.jpg"
    assert d["anilist_id"] == 20
    assert str(d["capitulos"]) == "220"


def test_tag_con_barra_se_puede_borrar(client):
    client.post("/api/animes/restore", json={"nombre": "Tagueado", "capitulos": "12"})
    r = client.post("/api/animes/Tagueado/tags", json={"tag": "a/b, c"})
    assert r.json()["tags"] == ["a-b  c"]
    assert client.delete("/api/animes/Tagueado/tags/a-b  c").status_code == 200
    assert client.get("/api/animes/Tagueado/tags").json()["tags"] == []


def test_sync_sin_credenciales_da_400_claro(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CREDENTIALS", tmp_path / "no-existe.json")
    r = client.post("/api/sync", json={"spreadsheet_id": "abc"})
    assert r.status_code == 400
    assert "credentials.json" in r.json()["detail"]
