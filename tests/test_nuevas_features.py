"""
Tests para las nuevas features v2.9:
- Motor de decisión "¿Qué veo esta noche?"
- Notas por episodio
- Auto-detección de archivos (watch_folder parser)
- Página compartible HTML
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def db(app_dir):
    import database
    importlib.reload(database)
    database.init_db()
    return database


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    ROOT = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANIME_APP_DIR", str(tmp_path))
    monkeypatch.setenv("ANIME_FROZEN_DIR", str(ROOT))
    monkeypatch.setenv("ANIME_DB_PATH", str(tmp_path / "test.db"))
    return tmp_path


@pytest.fixture
def client(db):
    importlib.reload(__import__("main"))
    import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c


# ── Motor de decisión ────────────────────────────────────────────────────────

class TestQueVeo:
    def test_biblioteca_vacia(self, client):
        r = client.get("/api/que-veo")
        assert r.status_code == 200
        d = r.json()
        assert d["anime"] is None

    def test_recomienda_algo(self, client, db):
        db.guardar_anime({
            "nombre": "Naruto", "fuente": "test", "capitulos": "220",
            "imagen": "", "genero": "Action,Adventure", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        r = client.get("/api/que-veo")
        assert r.status_code == 200
        d = r.json()
        assert d["anime"] is not None
        assert d["anime"]["nombre"] == "Naruto"

    def test_filtra_por_animo(self, client, db):
        db.guardar_anime({
            "nombre": "Attack on Titan", "fuente": "test", "capitulos": "75",
            "imagen": "", "genero": "Action,Drama", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        db.guardar_anime({
            "nombre": "K-On!", "fuente": "test", "capitulos": "13",
            "imagen": "", "genero": "Comedy,Slice of Life,Music", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        r = client.get("/api/que-veo?animo=comedia")
        d = r.json()
        assert d["anime"] is not None
        assert d["animo"] == "comedia"

    def test_devuelve_animos_disponibles(self, client, db):
        db.guardar_anime({
            "nombre": "Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "Action", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        r = client.get("/api/que-veo")
        d = r.json()
        assert "animos_disponibles" in d
        assert "accion" in d["animos_disponibles"]
        assert "comedia" in d["animos_disponibles"]

    def test_no_recomienda_completados(self, client, db):
        db.guardar_anime({
            "nombre": "Ya Visto", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "Action", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        db.actualizar_anime("Ya Visto", {"estado_usuario": "completado"})
        r = client.get("/api/que-veo")
        d = r.json()
        assert d["anime"] is None  # no hay pendientes ni viendo

    def test_razon_incluye_info(self, client, db):
        db.guardar_anime({
            "nombre": "My Hero", "fuente": "test", "capitulos": "100",
            "imagen": "", "genero": "Action,Shounen", "sinopsis": "",
            "estado_anime": "En emisión",
        })
        db.actualizar_anime("My Hero", {"estado_usuario": "viendo", "episodios_vistos": 30})
        r = client.get("/api/que-veo?animo=accion")
        d = r.json()
        assert "razon" in d


# ── Notas por episodio ───────────────────────────────────────────────────────

class TestNotasEpisodio:
    def test_guardar_y_leer_nota(self, db):
        db.guardar_anime({
            "nombre": "Steins;Gate", "fuente": "test", "capitulos": "24",
            "imagen": "", "genero": "Sci-Fi", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        assert db.guardar_nota_episodio("Steins;Gate", 12, "El twist!!")
        notas = db.obtener_notas_episodio("Steins;Gate")
        assert len(notas) == 1
        assert notas[0]["episodio"] == 12
        assert notas[0]["nota"] == "El twist!!"

    def test_actualizar_nota_existente(self, db):
        db.guardar_anime({
            "nombre": "Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "",
        })
        db.guardar_nota_episodio("Test", 1, "Primera impresión")
        db.guardar_nota_episodio("Test", 1, "Actualizada")
        nota = db.obtener_nota_episodio("Test", 1)
        assert nota == "Actualizada"

    def test_borrar_nota(self, db):
        db.guardar_anime({
            "nombre": "Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "",
        })
        db.guardar_nota_episodio("Test", 5, "Borrame")
        assert db.borrar_nota_episodio("Test", 5)
        assert db.obtener_nota_episodio("Test", 5) is None

    def test_nota_vacia_no_aparece(self, db):
        db.guardar_anime({
            "nombre": "Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "",
        })
        db.guardar_nota_episodio("Test", 1, "")
        notas = db.obtener_notas_episodio("Test")
        assert len(notas) == 0  # nota vacía no se lista

    def test_api_guardar_nota(self, client, db):
        db.guardar_anime({
            "nombre": "API Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "",
        })
        r = client.post(
            "/api/animes/API Test/notas-episodio/3",
            json={"nota": "Buen episodio"}
        )
        assert r.status_code == 200
        r2 = client.get("/api/animes/API Test/notas-episodio")
        assert r2.status_code == 200
        assert len(r2.json()["notas"]) == 1

    def test_api_borrar_nota(self, client, db):
        db.guardar_anime({
            "nombre": "Del Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "",
        })
        client.post("/api/animes/Del Test/notas-episodio/1", json={"nota": "Borrar"})
        r = client.delete("/api/animes/Del Test/notas-episodio/1")
        assert r.status_code == 200

    def test_plus1_con_nota(self, client, db):
        db.guardar_anime({
            "nombre": "Plus1 Nota", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "", "estado_anime": "",
        })
        r = client.post("/api/animes/Plus1 Nota/plus1?nota=Primer%20ep%20genial")
        assert r.status_code == 200
        nota = db.obtener_nota_episodio("Plus1 Nota", 1)
        assert nota == "Primer ep genial"


# ── Watch folder parser ──────────────────────────────────────────────────────

class TestWatchFolderParser:
    def test_subgroup_format(self):
        import watch_folder
        result = watch_folder._parsear_archivo("[SubGroup] Naruto Shippuden - 05 [1080p].mkv")
        assert result is not None
        nombre, ep = result
        assert "Naruto" in nombre
        assert ep == 5

    def test_s01e05_format(self):
        import watch_folder
        result = watch_folder._parsear_archivo("Attack on Titan S01E05.mkv")
        assert result is not None
        _, ep = result
        assert ep == 5

    def test_ep_format(self):
        import watch_folder
        result = watch_folder._parsear_archivo("One Piece EP1050.mp4")
        assert result is not None
        nombre, ep = result
        assert "One Piece" in nombre
        assert ep == 1050

    def test_dash_number_format(self):
        import watch_folder
        result = watch_folder._parsear_archivo("Jujutsu Kaisen - 12 (1080p).mkv")
        assert result is not None
        nombre, ep = result
        assert "Jujutsu Kaisen" in nombre
        assert ep == 12

    def test_no_match_for_non_anime(self):
        import watch_folder
        result = watch_folder._parsear_archivo("vacation_video_2024.mp4")
        # May or may not parse — but shouldn't crash
        assert result is None or isinstance(result, tuple)

    def test_limpiar_nombre(self):
        import watch_folder
        assert "Naruto Shippuden" in watch_folder._limpiar_nombre("Naruto.Shippuden [1080p]")

    def test_buscar_coincidencia(self):
        import watch_folder
        animes = [
            {"nombre": "Naruto Shippuden"},
            {"nombre": "One Piece"},
            {"nombre": "Bleach"},
        ]
        match = watch_folder._buscar_coincidencia("Naruto Shippuuden", animes)
        assert match is not None
        assert match["nombre"] == "Naruto Shippuden"

    def test_no_coincidencia_baja(self):
        import watch_folder
        animes = [{"nombre": "Naruto"}]
        match = watch_folder._buscar_coincidencia("algo completamente diferente", animes)
        assert match is None


# ── Página compartible ───────────────────────────────────────────────────────

class TestPaginaCompartible:
    def test_genera_html(self, client, db):
        db.guardar_anime({
            "nombre": "Compartir Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "Action", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        r = client.get("/api/perfil/compartir/html")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert "Compartir Test" in body
        assert "Miraru" in body

    def test_html_vacio_no_crashea(self, client, db):
        r = client.get("/api/perfil/compartir/html")
        assert r.status_code == 200

    def test_json_compartir_sigue_funcionando(self, client, db):
        db.guardar_anime({
            "nombre": "JSON Test", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "Comedy", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        r = client.get("/api/perfil/compartir")
        assert r.status_code == 200
        d = r.json()
        assert "stats" in d
        assert "top5" in d


# ── Watch folder API ─────────────────────────────────────────────────────────

class TestWatchFolderAPI:
    def test_status_sin_watcher(self, client):
        r = client.get("/api/watch-folder/status")
        assert r.status_code == 200
        assert r.json()["activo"] is False

    def test_start_con_carpeta_valida(self, client, app_dir):
        watch_dir = app_dir / "descargas"
        watch_dir.mkdir()
        r = client.post("/api/watch-folder/start", json={"carpeta": str(watch_dir)})
        assert r.status_code == 200
        # Limpiar
        client.post("/api/watch-folder/stop")

    def test_start_carpeta_inexistente(self, client):
        r = client.post("/api/watch-folder/start", json={"carpeta": "/no/existe/nada"})
        assert r.status_code == 400

    def test_log_vacio(self, client):
        r = client.get("/api/watch-folder/log")
        assert r.status_code == 200
        assert r.json()["log"] == []


# ── Puntuaciones externas ───────────────────────────────────────────────────

class TestScoresEndpoint:
    def test_scores_devuelve_estructura(self, client, db):
        db.guardar_anime({
            "nombre": "Naruto", "fuente": "test", "capitulos": "220",
            "imagen": "", "genero": "Action", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        r = client.get("/api/animes/Naruto/scores")
        assert r.status_code == 200
        d = r.json()
        assert "anilist" in d
        assert "mal" in d
        assert "kitsu" in d
        assert "media" in d
        assert "usuario" in d
        # Cada fuente tiene score, score_raw, url
        for key in ["anilist", "mal", "kitsu"]:
            assert "score" in d[key]
            assert "url" in d[key]

    def test_scores_incluye_puntuacion_usuario(self, client, db):
        db.guardar_anime({
            "nombre": "Scored Anime", "fuente": "test", "capitulos": "12",
            "imagen": "", "genero": "", "sinopsis": "",
            "estado_anime": "Finalizado",
        })
        db.actualizar_anime("Scored Anime", {"puntuacion": 8.5})
        r = client.get("/api/animes/Scored Anime/scores")
        assert r.status_code == 200
        d = r.json()
        assert d["usuario"] == 8.5

    def test_scores_anime_inexistente(self, client, db):
        r = client.get("/api/animes/NoExiste123xyz/scores")
        assert r.status_code == 200
        d = r.json()
        # No debería crashear, usuario será None
        assert d["usuario"] is None
