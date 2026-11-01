"""Copia en la nube: no perder la lista al formatear el PC."""
from __future__ import annotations

import importlib
import json
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def nube(tmp_path, monkeypatch):
    d = tmp_path / "OneDrive"
    d.mkdir()
    monkeypatch.setenv("OneDrive", str(d))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("COMPUTERNAME", "PC-LUCAS")
    for v in ("OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(v, raising=False)
    return d


@pytest.fixture
def cn(db, nube):
    import copia_nube
    importlib.reload(copia_nube)
    return copia_nube


@pytest.fixture
def cliente(db, nube):
    import main
    importlib.reload(main)
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c


def _lista(db, n=3):
    for i in range(n):
        db.guardar_anime({"nombre": f"Anime {i}", "capitulos": "12", "episodios_vistos": i})


def test_detecta_onedrive_y_guarda_sin_secretos(cn, db, nube):
    _lista(db)
    db.set_config("anilist_token", "SECRETO1")
    db.set_config("animeav1_cookie", "SECRETO2")
    db.set_config("gmail_app_pass", "SECRETO3")
    db.set_config("lang", "es")
    assert cn.carpeta_activa() == nube / "Miraru"
    r = cn.guardar_copia()
    assert r["ok"] and r["animes"] == 3
    f = nube / "Miraru" / "miraru-copia-PC-LUCAS.zip"
    with zipfile.ZipFile(f) as z:
        datos = z.read("anime_tracker.db")
        info = json.loads(z.read("miraru.json"))
    assert b"SECRETO" not in datos
    assert info["animes"] == 3 and info["equipo"] == "PC-LUCAS"


def test_tras_formatear_se_ofrece_y_se_recupera(cliente, db, nube):
    import copia_nube
    _lista(db, 5)
    copia_nube.guardar_copia()
    db.set_config("anilist_token", "TOKEN-VIEJO")
    # «Formatear»: BD nueva y vacía en el mismo PC
    with db.get_conn() as c:
        c.execute("DELETE FROM animes")
        c.execute("DELETE FROM config")
    db._invalidar_cache()
    db.set_config("anilist_token", "TOKEN-NUEVO")
    est = cliente.get("/api/copia").json()
    assert est["lista_vacia"] and est["pendiente"]
    assert est["copias"][0]["animes"] == 5 and est["copias"][0]["este_pc"]
    # Mientras no decides, añadir un anime NO machaca la copia buena
    db.guardar_anime({"nombre": "Nuevo"})
    assert cliente.post("/api/copia/ahora").status_code == 409
    r = cliente.post("/api/copia/recuperar", json={"archivo": est["copias"][0]["archivo"]})
    assert r.status_code == 200, r.text
    nombres = {a["nombre"] for a in db.listar_animes()}
    assert {f"Anime {i}" for i in range(5)} <= nombres
    assert db.get_config("anilist_token") == "TOKEN-NUEVO"     # las claves de este PC se respetan
    assert not cliente.get("/api/copia").json()["pendiente"]
    # Se guardó lo que había antes de recuperar
    assert list((db._get_db_path().parent / "backups").glob("antes_de_recuperar_*.db"))


def test_empezar_de_cero_aparta_la_copia_vieja(cliente, db, nube):
    import copia_nube
    _lista(db, 2)
    copia_nube.guardar_copia()
    with db.get_conn() as c:
        c.execute("DELETE FROM config")
    assert copia_nube.pendiente_de_decidir()
    cliente.post("/api/copia/empezar-de-cero")
    assert not copia_nube.pendiente_de_decidir()
    assert list((nube / "Miraru").glob("*.descartada-*"))
    assert copia_nube.guardar_copia()["ok"]


def test_solo_se_recuperan_copias_encontradas(cliente, tmp_path):
    falsa = tmp_path / "x.zip"
    falsa.write_bytes(b"no")
    assert cliente.post("/api/copia/recuperar", json={"archivo": str(falsa)}).status_code == 404


def test_apagar_y_otra_carpeta(cliente, db, tmp_path):
    import copia_nube
    _lista(db, 1)
    assert cliente.post("/api/copia/carpeta", json={"ruta": "-"}).status_code == 200
    assert copia_nube.carpeta_activa() is None
    otra = tmp_path / "Dropbox"
    otra.mkdir()
    r = cliente.post("/api/copia/carpeta", json={"ruta": str(otra)})
    assert r.status_code == 200 and r.json()["copia"]["ok"]
    assert (otra / "Miraru" / "miraru-copia-PC-LUCAS.zip").exists()
    assert cliente.post("/api/copia/carpeta", json={"ruta": "relativa"}).status_code == 400


def test_dos_pcs_no_se_pisan(cn, db, nube, monkeypatch):
    _lista(db, 1)
    cn.guardar_copia()
    monkeypatch.setenv("COMPUTERNAME", "PORTATIL")
    db.set_config(cn.CLAVE_ULTIMA, "")
    cn.guardar_copia()
    assert {f.name for f in (nube / "Miraru").glob("*.zip")} == {
        "miraru-copia-PC-LUCAS.zip", "miraru-copia-PORTATIL.zip"}


def test_copia_dañada_no_se_recupera(cn, db, nube):
    (nube / "Miraru").mkdir()
    f = nube / "Miraru" / "miraru-copia-OTRO.zip"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("anime_tracker.db", b"esto no es sqlite")
    with pytest.raises(ValueError):
        cn.recuperar(f)


def test_onedrive_sin_sesion_se_avisa(cn, db, nube, monkeypatch):
    """La carpeta OneDrive existe aunque no hayas iniciado sesión: entonces la
    copia no sube a ninguna parte y hay que decírtelo."""
    monkeypatch.setattr(cn, "_cuentas_onedrive", lambda: {str(nube).lower(): False})
    n = cn.detectar_nubes()
    assert n[0]["servicio"] == "OneDrive" and n[0]["sincroniza"] is False
    assert cn.estado()["sincroniza"] is False
    monkeypatch.setattr(cn, "_cuentas_onedrive", lambda: {str(nube).lower(): True})
    assert cn.estado()["sincroniza"] is True


def test_google_drive_unidad_virtual_en_cualquier_idioma(cn, db, tmp_path, monkeypatch):
    """Google Drive para escritorio monta una unidad «Google Drive» (G:) y
    dentro «Mi unidad» con el nombre en el idioma de la cuenta."""
    monkeypatch.delenv("OneDrive")
    unidad = tmp_path / "G"
    (unidad / "Meine Ablage").mkdir(parents=True)
    (unidad / "Geteilte Ablagen").mkdir()
    monkeypatch.setattr(cn, "_unidades_locales", lambda: [str(unidad)])
    monkeypatch.setattr(cn, "_etiqueta_volumen", lambda r: "Google Drive")
    n = cn.detectar_nubes()
    assert n == [{"servicio": "Google Drive", "ruta": str(unidad / "Meine Ablage"), "sincroniza": True}]
    _lista(db, 2)
    assert cn.guardar_copia()["ok"]
    assert (unidad / "Meine Ablage" / "Miraru" / "miraru-copia-PC-LUCAS.zip").exists()


def test_google_drive_nombre_desconocido_y_modo_espejo(cn, tmp_path, monkeypatch):
    monkeypatch.delenv("OneDrive")
    unidad = tmp_path / "H"
    (unidad / "Moje dokumenty Google").mkdir(parents=True)
    (unidad / ".shortcut-targets-by-id").mkdir()
    monkeypatch.setattr(cn, "_unidades_locales", lambda: [str(unidad)])
    monkeypatch.setattr(cn, "_etiqueta_volumen", lambda r: "Google Drive")
    assert [x["ruta"] for x in cn.detectar_nubes()] == [str(unidad / "Moje dokumenty Google")]
    # Modo espejo: carpeta en el perfil
    monkeypatch.setattr(cn, "_unidades_locales", lambda: [])
    home = tmp_path / "home"
    (home / "Mi unidad").mkdir(parents=True)
    assert cn.detectar_nubes()[0]["ruta"] == str(home / "Mi unidad")


def test_dropbox_por_info_json(cn, tmp_path, monkeypatch):
    monkeypatch.delenv("OneDrive")
    caja = tmp_path / "D" / "Dropbox (Empresa)"
    caja.mkdir(parents=True)
    app = tmp_path / "appdata"
    (app / "Dropbox").mkdir(parents=True)
    (app / "Dropbox" / "info.json").write_text(json.dumps({"business": {"path": str(caja)}}))
    monkeypatch.setenv("LOCALAPPDATA", str(app))
    assert cn.detectar_nubes()[0] == {"servicio": "Dropbox", "ruta": str(caja), "sincroniza": None}


def test_onedrive_sin_sesion_va_detras_de_google_drive(cn, nube, tmp_path, monkeypatch):
    monkeypatch.setattr(cn, "_cuentas_onedrive", lambda: {str(nube).lower(): False})
    (tmp_path / "home" / "My Drive").mkdir(parents=True)
    servicios = [x["servicio"] for x in cn.detectar_nubes()]
    assert servicios == ["Google Drive", "OneDrive"]
    assert cn.carpeta_activa().parent.name == "My Drive"
