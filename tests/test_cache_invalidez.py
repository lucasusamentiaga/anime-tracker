"""
Test de invalidación de caché (_lista_cache) tras cada endpoint que muta animes.

database.py cachea la lista completa en `_lista_cache` (y la versión ligera del
grid en `_slim_cache`) y las invalida con `_invalidar_cache()` en cada helper de
escritura. El riesgo es que una ruta muten por vía propia (SQL directo o helper
sin invalidar): la siguiente petición GET /api/animes devolvería el estado viejo
y la UI mostraría datos fantasma hasta reiniciar.

El pin es FUNCIONAL en vez de intrusivo: en TODOS los pins se calienta la caché
leyendo el listado ANTES de mutar (en las creaciones además se comprueba que el
nombre nuevo aún no está en ese listado calentado), se muta por HTTP y se exige
que el listado SIGUIENTE refleje el cambio. Si la invalidación se rompe (p. ej.
Task 8 reestructura main.py), el test falla sin conocer variable alguna de
database.py: el listado siguiente devolvería el estado viejo y la UI mostraría
datos fantasma hasta reiniciar.

rutas auditadas (todas pasan por un helper que llama a _invalidar_cache()):
  POST   /api/animes                     → db.guardar_anime
  POST   /api/manga                      → db.guardar_anime
  POST   /api/animes/restore             → db.guardar_anime
  PATCH  /api/animes/{nombre}            → db.actualizar_anime
  PATCH  /api/animes/{nombre}/nota       → db.actualizar_anime
  POST   /api/animes/{nombre}/favorito   → db.actualizar_anime
  POST   /api/animes/{nombre}/notif      → db.actualizar_anime
  POST   /api/animes/{nombre}/plus1      → db.actualizar_anime
  DELETE /api/animes/{nombre}            → db.eliminar_anime
  POST   /api/grupos                     → db.asignar_grupo
  POST   /api/import/bulk                → db.guardar_anime
  POST   /api/import/mal-xml             → db.guardar_anime
  POST   /api/import/anilist             → db.guardar_anime
  PATCH  /api/mobile/animes/{nombre}     → db.actualizar_anime
  POST   /api/mobile/animes/{nombre}/plus1 → db.actualizar_anime
  POST   /api/anilist/pull · resolve-ids · animeav1/*/pull → _invalidar_cache
         explícito en main.py (mutan fuera de los helpers, vía anilist_sync/
         animeav1_sync); cubren red, no se pinan aquí.
Además, a nivel de helper: db.refrescar_metadata_anime y db.fusionar_animes
(ambos llaman a _invalidar_cache) y db.watch_folder usa db.actualizar_anime.

No se pinnan (no alimentan el listado cacheado): escrituras de historial,
ep_log, notas por episodio y config/tags, y media (usa su propia
_invalidar_media_cache). El único SQL directo contra animes fuera de los
helpers está en migrations.completar_episodios_vistos, y ya invalida la caché
explícitamente en migrations.py:267 (auditado; esa función ya tiene test en
tests/test_metadatos.py).
"""
from __future__ import annotations

import os
import tempfile
import types

# main.py inicializa la BD en el startup; aislar en un tmp escribible ANTES de
# importar (copiado del patrón de tests/test_api.py y tests/test_database.py).
_TMP = tempfile.mkdtemp(prefix="miraru_cache_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "cache.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
# Sin hilos de fondo (ver conftest y main._sin_hilos_de_fondo).
os.environ.setdefault("MIRARU_SIN_HILOS_FONDO", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database as db  # noqa: E402
import main  # noqa: E402


@pytest.fixture
def client():
    """Cliente HTTP sobre la app, con las tablas vacías al terminar."""
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c
    with db.get_conn() as conn:
        for t in ("animes", "media", "ep_log", "historial", "episode_notes"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM config")
    # La limpieza de arriba es SQL directo y no pasa por los helpers:
    # invalidar a mano para que el siguiente test parta de caché fría.
    db._invalidar_cache()


def _sembrar(client, nombre, **extra):
    """Crea un anime SIN red usando el endpoint de 'Deshacer' (restore)."""
    data = {"nombre": nombre, "capitulos": "12"}
    data.update(extra)
    r = client.post("/api/animes/restore", json=data)
    assert r.status_code == 200, r.text


def _calentar(client):
    """Lee el listado completo una vez: si la caché funciona, esta lectura
    queda guardada y la siguiente devolvería el estado ANTES de mutar."""
    return client.get("/api/animes").json()["animes"]


def _por_nombre(client, nombre):
    return next(a for a in _calentar(client) if a["nombre"] == nombre)


# ── Mutaciones que refleja GET /api/animes ────────────────────────────────────

def test_patch_actualiza_el_listado(client):
    """PATCH /api/animes/{nombre} → el listado siguiente ya ve 'completado'."""
    _sembrar(client, "Hawk")
    assert _por_nombre(client, "Hawk")["estado_usuario"] == "pendiente"
    r = client.patch("/api/animes/Hawk", json={"estado_usuario": "completado"})
    assert r.status_code == 200, r.text
    a = _por_nombre(client, "Hawk")
    assert a["estado_usuario"] == "completado"


def test_patch_nota_rapida_refleja_notas_en_el_listado(client):
    """PATCH .../nota: 'notas' no está en el slim pero sí en el listado."""
    _sembrar(client, "W")
    _calentar(client)
    r = client.patch("/api/animes/W/nota", json={"nota": "capítulo 10 brutal"})
    assert r.status_code == 200, r.text
    assert _por_nombre(client, "W")["notas"] == "capítulo 10 brutal"


def test_favorito_del_endpoint_sale_en_el_listado(client):
    _sembrar(client, "F")
    _calentar(client)
    r = client.post("/api/animes/F/favorito")
    assert r.status_code == 200 and r.json()["favorito"] is True
    assert _por_nombre(client, "F")["favorito"] == 1


def test_notif_del_endpoint_sale_en_el_listado(client):
    _sembrar(client, "N")
    _calentar(client)
    r = client.post("/api/animes/N/notif")
    assert r.status_code == 200 and r.json()["notif_activa"] is True
    assert _por_nombre(client, "N")["notif_activa"] == 1


def test_plus1_incrementa_episodios_vistos_en_el_listado(client):
    _sembrar(client, "P", episodios_vistos=3)
    _calentar(client)
    r = client.post("/api/animes/P/plus1")
    assert r.status_code == 200 and r.json()["episodios_vistos"] == 4
    assert _por_nombre(client, "P")["episodios_vistos"] == 4


def test_delete_quita_el_anime_del_listado(client):
    _sembrar(client, "D1")
    _sembrar(client, "D2")
    nombres = {a["nombre"] for a in _calentar(client)}
    assert nombres == {"D1", "D2"}
    r = client.delete("/api/animes/D1")
    assert r.status_code == 200
    assert {a["nombre"] for a in _calentar(client)} == {"D2"}


def test_grupos_cambia_grupo_en_el_listado(client):
    _sembrar(client, "G1")
    _sembrar(client, "G2")
    _calentar(client)
    r = client.post("/api/grupos", json={"nombres": ["G1", "G2"], "grupo": "saga X"})
    assert r.status_code == 200 and r.json()["cambiados"] == 2
    for a in _calentar(client):
        assert a["grupo"] == "saga X"


# ── Creaciones que refleja GET /api/animes ────────────────────────────────────

# Datos de scraper falsos suficientes para db.guardar_anime (usa data.get(...)),
# como tipo SimpleNamespace: el endpoint hace resultado.__dict__.copy().
def _scraper_bruto(nombre):
    return types.SimpleNamespace(
        nombre=nombre, fuente="anilist", capitulos="12", imagen="http://img",
        genero=["Acción"], sinopsis="...", estado_anime="Finalizado",
        estado_usuario="pendiente", anilist_id=42, tipo="anime",
    )


def test_post_animes_crea_y_sale_en_el_listado(client, monkeypatch):
    """POST /api/animes con la búsqueda falseada (sin red)."""
    # _buscar_con_fallback es asíncrona: el sustituto también lo debe ser.
    async def _fallback_fake(texto, fuente):
        return _scraper_bruto("Scratched"), "anilist"

    monkeypatch.setattr(main, "_buscar_con_fallback", _fallback_fake)
    monkeypatch.setattr(main, "_enrich_needs", lambda data: (False, False))
    monkeypatch.setattr(main, "_find_anime_image", lambda nombre: None)
    # Caché calentada ANTES de crear: sin el anime. Si guardar_anime dejara de
    # invalidar, el listado siguiente seguiría siendo este listado viejo.
    assert not any(a["nombre"] == "Scratched" for a in _calentar(client))
    r = client.post("/api/animes", json={"nombre": "Scratched"})
    assert r.status_code == 200, r.text
    assert _por_nombre(client, "Scratched")["anilist_id"] == 42


def test_post_manga_crea_y_sale_en_el_listado(client, monkeypatch):
    """POST /api/manga usando un SCRAPERS falseado con buscar_manga."""
    fake = types.SimpleNamespace(
        buscar_manga=lambda nombre: _scraper_bruto(nombre))
    monkeypatch.setattr(main, "SCRAPERS", {"anilist": fake})
    assert not any(a["nombre"] == "MangaMania" for a in _calentar(client))
    r = client.post("/api/manga", json={"nombre": "MangaMania"})
    assert r.status_code == 200, r.text
    m = _por_nombre(client, "MangaMania")
    assert m["tipo"] == "manga"


def test_import_bulk_guarda_y_sale_en_el_listado(client, monkeypatch):
    """POST /api/import/bulk con scraper falso: los nombres pedidos entran."""
    fake = types.SimpleNamespace(
        buscar=lambda nombre: _scraper_bruto(nombre))
    monkeypatch.setattr(main, "SCRAPERS", {"anilist": fake})
    assert not any(a["nombre"] == "Bulk1" for a in _calentar(client))
    r = client.post("/api/import/bulk", json={"texto": "Bulk1\nBulk2"})
    assert r.status_code == 200, r.text
    assert r.json()["añadidos"] == ["Bulk1", "Bulk2"]
    assert _por_nombre(client, "Bulk1")["anilist_id"] == 42


def test_import_mal_xml_guarda_y_sale_en_el_listado(client, monkeypatch):
    """POST /api/import/mal-xml: sin scrapers el XML entra tal cual."""
    monkeypatch.setattr(main, "SCRAPERS", {})
    xml = (b"<myanimelist><anime><series_title>Clannad</series_title>"
           b"<my_status>On-Hold</my_status><my_score>9</my_score>"
           b"<my_watched_episodes>12</my_watched_episodes></anime></myanimelist>")
    assert not any(a["nombre"] == "Clannad" for a in _calentar(client))
    r = client.post("/api/import/mal-xml",
                    files={"file": ("export.xml", xml, "text/xml")})
    assert r.status_code == 200, r.text
    assert r.json()["añadidos"] == 1
    a = _por_nombre(client, "Clannad")
    assert a["estado_usuario"] == "pausa"
    assert a["episodios_vistos"] == 12 and a["puntuacion"] == 9.0


def test_import_anilist_guarda_y_sale_en_el_listado(client, monkeypatch):
    """POST /api/import/anilist con _anilist falseado (GraphQL enlatado)."""
    respuesta = {"MediaListCollection": {"lists": [{
        "name": "Watching",
        "entries": [{
            "status": "CURRENT", "score": 9, "progress": 5,
            "media": {
                "title": {"romaji": "ImportAni"},
                "coverImage": {"large": "http://img"},
                "genres": ["Comedia"],
                "episodes": 24, "description": "<p>divertido</p>",
                "status": "RELEASING", "siteUrl": "http://x",
            },
        }],
    }]}}
    monkeypatch.setattr(
        main, "_anilist", lambda query, variables, timeout=20: respuesta)
    assert not any(a["nombre"] == "ImportAni" for a in _calentar(client))
    r = client.post("/api/import/anilist", json={"username": "fan"})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True, body
    assert body["añadidos"] == 1
    a = _por_nombre(client, "ImportAni")
    assert a["estado_usuario"] == "viendo" and a["episodios_vistos"] == 5


def test_restore_devuelve_el_anime_al_listado_calentado(client):
    """Flujo 'Deshacer' con la caché ya calentada: borrar → leer el listado
    (sin el anime) → restaurar desde el JSON que guardó el frontend (no hay
    fichero de copia: el body del POST ES la copia). Si restore no invalidara,
    la lectura siguiente seguiría viendo el estado pre-restauración."""
    datos = {"nombre": "Undo", "capitulos": "12",
             "estado_usuario": "completado", "episodios_vistos": 9}
    assert client.post("/api/animes/restore", json=datos).status_code == 200
    assert client.delete("/api/animes/Undo").status_code == 200
    # Caché calentada SIN el anime borrado
    assert not any(a["nombre"] == "Undo" for a in _calentar(client))
    r = client.post("/api/animes/restore", json=datos)
    assert r.status_code == 200, r.text
    a = _por_nombre(client, "Undo")
    assert a["estado_usuario"] == "completado" and a["episodios_vistos"] == 9


# ── Endpoints móviles (mismo helper, pero por la ruta móvil) ─────────────────

@pytest.fixture
def sin_token_movil(monkeypatch):
    """El test no va a por el PIN: se salta la dependencia de token."""
    monkeypatch.setattr(main, "_require_auth", lambda request: None)


def test_mobile_patch_actualiza_el_listado(client, sin_token_movil):
    _sembrar(client, "M")
    _calentar(client)
    r = client.patch("/api/mobile/animes/M", json={"estado_usuario": "viendo"})
    assert r.status_code == 200, r.text
    assert _por_nombre(client, "M")["estado_usuario"] == "viendo"


def test_mobile_plus1_actualiza_el_listado(client, sin_token_movil):
    _sembrar(client, "MP", episodios_vistos=2)
    _calentar(client)
    r = client.post("/api/mobile/animes/MP/plus1")
    assert r.status_code == 200, r.text
    assert _por_nombre(client, "MP")["episodios_vistos"] == 3


# ── El grid slim comparte invalidación ───────────────────────────────────────

def test_listado_slim_tambien_se_invalida(client):
    """_slim_cache se limpia junto a _lista_cache: más1 y PATCH se reflejan."""
    _sembrar(client, "S", episodios_vistos=1)

    def slim(nombre):
        return next(a for a in client.get("/api/animes/slim").json()["animes"]
                    if a["nombre"] == nombre)

    assert slim("S")["episodios_vistos"] == 1
    r = client.post("/api/animes/S/plus1")
    assert r.status_code == 200
    assert slim("S")["episodios_vistos"] == 2
    client.patch("/api/animes/S", json={"estado_usuario": "completado"})
    assert slim("S")["estado_usuario"] == "completado"


# ── Mutaciones a nivel de helper (sin endpoint HTTP o en trabajo de fondo) ────

def test_refrescar_metadata_anime_invalida_la_cache(db):
    """db.refrescar_metadata_anime (usado por POST /api/animes/refrescar, que
    muta en un trabajo de fondo): el refresco sale en el siguiente listar."""
    db.guardar_anime({"nombre": "Refresco", "capitulos": "200"})
    # Calentar la caché con el valor viejo
    antes = [a for a in db.listar_animes() if a["nombre"] == "Refresco"]
    assert antes[0]["capitulos"] == "200"
    ok, _ = db.refrescar_metadata_anime("Refresco", {"capitulos": "301"})
    assert ok
    despues = [a for a in db.listar_animes() if a["nombre"] == "Refresco"]
    assert despues[0]["capitulos"] == "301"


def test_fusionar_animes_invalida_la_cache(db):
    """db.fusionar_animes (sin endpoint HTTP hoy): el descartado desaparece del
    listado calentado."""
    db.guardar_anime({"nombre": "Fusion A", "puntuacion": 7.0})
    db.guardar_anime({"nombre": "Fusion B", "puntuacion": 9.0})
    nombres_antes = {a["nombre"] for a in db.listar_animes()
                     if a["nombre"].startswith("Fusion ")}
    assert nombres_antes == {"Fusion A", "Fusion B"}   # caché calentada
    ok, _ = db.fusionar_animes("Fusion A", "Fusion B")
    assert ok
    nombres = {a["nombre"] for a in db.listar_animes()
               if a["nombre"].startswith("Fusion ")}
    assert nombres == {"Fusion A"}
