"""
Carpeta vigilada: emparejar archivos con la entrada correcta de la biblioteca.

Regresión: el emparejado por contención daba 0.95 fijo y ganaba el PRIMERO de
la lista: "Naruto Shippuden - 100" → Naruto, "Spy x Family S02E05" → una
campaña de la película, "Jujutsu Kaisen S02E10" → otra temporada…
"""
from __future__ import annotations

import pytest

import watch_folder as wf


@pytest.fixture(autouse=True)
def _limpiar_estado_watcher():
    """El log y los archivos vistos del watcher son globales del módulo."""
    yield
    wf._watcher_seen = set()
    wf._watcher_log.clear()


BIBLIO = [
    {"nombre": "Ayataka Spy x Family Movie Campaign Ayataka de Hotto Hitoiki", "capitulos": "1"},
    {"nombre": "Spy x Family Movie: Code: White", "capitulos": "película"},
    {"nombre": "Spy x Family Season 2", "capitulos": "12"},
    {"nombre": "Spy x Family", "capitulos": "12"},
    {"nombre": "Naruto", "capitulos": "220"},
    {"nombre": "Naruto Shippuden", "capitulos": "500"},
    {"nombre": "Jujutsu Kaisen: Shimetsu Kaiyū Zenpen", "capitulos": "12"},
    {"nombre": "Jujutsu Kaisen 0 Movie", "capitulos": "película"},
    {"nombre": "Jujutsu Kaisen 2nd Season", "capitulos": "23"},
    {"nombre": "Jujutsu Kaisen (TV)", "capitulos": "24"},
    {"nombre": "Kimetsu no Yaiba: Mugen Ressha-hen", "capitulos": "7"},
    {"nombre": "Kimetsu no Yaiba", "capitulos": "26"},
    {"nombre": "Shingeki no Kyojin Season 3", "capitulos": "12"},
    {"nombre": "Shingeki no Kyojin", "capitulos": "25"},
    {"nombre": "One Piece", "capitulos": "1179+"},
]


@pytest.mark.parametrize("archivo, esperado", [
    ("[SubsPlease] Spy x Family - 05 (1080p) [ABC].mkv", "Spy x Family"),
    ("Spy x Family S02E05.mkv", "Spy x Family Season 2"),
    ("[SubsPlease] Spy x Family Season 2 - 05 (1080p).mkv", "Spy x Family Season 2"),
    ("Naruto Shippuden - 100.mkv", "Naruto Shippuden"),
    ("Naruto - 050.mkv", "Naruto"),
    ("Jujutsu.Kaisen.S02E10.1080p.WEB.x264.mkv", "Jujutsu Kaisen 2nd Season"),
    ("[SubsPlease] Kimetsu no Yaiba - 05v2 (720p).mkv", "Kimetsu no Yaiba"),
    ("Shingeki no Kyojin S03E05.mkv", "Shingeki no Kyojin Season 3"),
    ("[Erai-raws] One Piece - 1180 [1080p].mkv", "One Piece"),
])
def test_empareja_la_entrada_correcta(archivo, esperado):
    nombre, ep = wf._parsear_archivo(archivo)
    m = wf._buscar_coincidencia(nombre, BIBLIO, temporada=wf._temporada_de_archivo(archivo), episodio=ep)
    assert m and m["nombre"] == esperado


@pytest.mark.parametrize("titulo, t", [
    ("Spy x Family Season 2", 2), ("Boku no Hero Academia 2nd Season", 2),
    ("Overlord III", 3), ("Naruto", None), ("Jujutsu Kaisen (TV)", None),
])
def test_temporada_de_nombre(titulo, t):
    assert wf._temporada_de_nombre(titulo) == t


def test_carpeta_real_marca_y_salvaguardas(db, tmp_path, monkeypatch):
    monkeypatch.setattr(wf, "db", db)
    db.guardar_anime({"nombre": "Frieren", "capitulos": "28", "episodios_vistos": 3,
                      "estado_usuario": "viendo"})
    db.guardar_anime({"nombre": "Shingeki no Kyojin", "capitulos": "25",
                      "episodios_vistos": 25, "estado_usuario": "completado"})
    db.guardar_anime({"nombre": "Dandadan", "capitulos": "12", "episodios_vistos": 10,
                      "estado_usuario": "viendo"})
    wf._watcher_seen = set(); wf._watcher_log.clear()
    for f in ["[SubsPlease] Frieren - 04 (1080p).mkv",      # siguiente → marca
              "[SubsPlease] Frieren - 02 (1080p).mkv",      # ya visto
              "[Judas] Shingeki no Kyojin - S04E28.mkv",    # completado → no toca
              "[SubsPlease] Dandadan - 13 (1080p).mkv",     # fuera de rango (12)
              "notas.txt"]:
        (tmp_path / f).write_bytes(b"")
    wf._check_new_files(tmp_path)
    estados = {e["archivo"]: e["estado"] for e in wf.get_log()}
    assert estados["[SubsPlease] Frieren - 04 (1080p).mkv"] == "marcado"
    assert estados["[SubsPlease] Frieren - 02 (1080p).mkv"] == "ya visto"
    assert estados["[Judas] Shingeki no Kyojin - S04E28.mkv"] == "ya completado"
    assert estados["[SubsPlease] Dandadan - 13 (1080p).mkv"].startswith("fuera de rango")
    assert "notas.txt" not in estados
    assert db.obtener_anime("Frieren")["episodios_vistos"] == 4
    assert db.obtener_anime("Shingeki no Kyojin")["episodios_vistos"] == 25
    assert db.obtener_anime("Dandadan")["episodios_vistos"] == 10
    # un segundo escaneo no reprocesa los mismos archivos
    n = len(wf.get_log())
    wf._check_new_files(tmp_path)
    assert len(wf.get_log()) == n
