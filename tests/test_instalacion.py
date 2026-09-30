"""
Instalación sin .exe propios (install.ps1 + _acceso_directo.py).

Existe porque el Control inteligente de aplicaciones de Windows 11 bloquea los
.exe sin firma (WinError 4551). install.ps1 usa Python firmado + el código, y
tiene que funcionar con PowerShell en modo de lenguaje restringido.
"""
from __future__ import annotations

import re
from pathlib import Path

import _acceso_directo
import launcher

RAIZ = Path(__file__).resolve().parent.parent
PS1 = (RAIZ / "install.ps1").read_text(encoding="utf-8")


def test_accesos_directos_usan_pythonw_firmado():
    """El acceso directo abre pythonw.exe (firmado por la PSF), nunca un .exe propio.
    La creación real con IShellLinkW se prueba en Windows (CI: install-windows)."""
    codigo = (RAIZ / "_acceso_directo.py").read_text(encoding="utf-8")
    assert '"pythonw.exe"' in codigo and "launcher.py" in codigo
    assert callable(_acceso_directo.crear_lnk) and callable(_acceso_directo.crear_accesos)


def test_install_ps1_compatible_con_modo_restringido():
    """Con Smart App Control PowerShell no permite .NET, COM ni Add-Type."""
    sin_comentarios = "\n".join(l for l in PS1.splitlines() if not l.lstrip().startswith("#"))
    for prohibido in ("::", "New-Object", "Add-Type", "-ComObject", "[System.", "[Net.", "[IO."):
        assert prohibido not in sin_comentarios, prohibido
    # `exit` cerraría la ventana de PowerShell del usuario al ejecutarse con `| iex`
    assert not re.search(r"^\s*exit\b", sin_comentarios, re.M)
    assert PS1.isascii()  # irm en PowerShell 5.1 puede decodificar mal lo que no es ASCII


def test_install_ps1_verifica_la_firma_de_python():
    assert "Get-AuthenticodeSignature" in PS1 and "Python Software Foundation" in PS1


def test_python_desde_msi_sin_instalador():
    """El instalador python-X-amd64.exe extrae PythonBA.dll (sin firma) y con Smart App
    Control se queda colgado: se usan los .msi firmados con msiexec /a."""
    codigo = "\n".join(l for l in PS1.splitlines() if not l.lstrip().startswith("#"))
    assert "-amd64.exe" not in codigo
    assert "msiexec.exe" in codigo and "'/a'" in codigo
    for m in ("core", "exe", "lib", "tcltk"):
        assert f"'{m}'" in codigo


def test_desinstalar_solo_borra_instalaciones_reales(tmp_path):
    codigo = tmp_path / "a" / "b" / "Miraru"
    codigo.mkdir(parents=True)
    (codigo / "launcher.py").write_text("")
    assert not launcher._es_carpeta_instalada(codigo)        # copia del código: no
    (codigo / launcher.MARCA_INSTALACION).write_text("install.ps1")
    assert launcher._es_carpeta_instalada(codigo)            # instalada con install.ps1
    assert not launcher._es_carpeta_instalada(Path("C:/"))


def test_requirements_de_usuario_sin_herramientas_de_desarrollo():
    usuario = (RAIZ / "requirements.txt").read_text(encoding="utf-8").lower()
    for dev in ("pyinstaller", "pytest", "ruff", "httpx"):
        assert not re.search(rf"^{dev}\b", usuario, re.M), dev
    assert "-r requirements.txt" in (RAIZ / "requirements-dev.txt").read_text(encoding="utf-8")


def test_install_ps1_pensado_para_el_usuario():
    """Pasos numerados, idioma del sistema, registro para soporte, pausa al actualizar
    desde la app y alternativa si la API de GitHub falla (límite de 60 consultas/hora)."""
    assert "$PSUICulture" in PS1 and "MIRARU_IDIOMA" in PS1
    assert "Start-Transcript" in PS1 and "miraru-instalacion.log" in PS1
    assert "MIRARU_PAUSA" in PS1
    assert "/releases/latest" in PS1 and "/releases/tag/" in PS1
    assert "Get-PSDrive" in PS1  # espacio libre antes de empezar
    n = int(re.search(r"\$MiraruEtapas = (\d+)", PS1).group(1))
    assert len(re.findall(r"^\s*Miraru-Etapa '", PS1, re.M)) >= n


def test_tras_actualizar_no_abre_otra_pestana_si_la_de_antes_vuelve(monkeypatch):
    import sys
    import time
    import types
    falso = types.SimpleNamespace(_pestana_esperando={"ts": time.time()})
    monkeypatch.setitem(sys.modules, "main", falso)
    monkeypatch.setenv("MIRARU_TRAS_ACTUALIZAR", "1")
    assert launcher._pestana_ya_abierta(espera=1, paso=0.05)
    # Sin la variable (arranque normal) siempre se abre el navegador.
    assert not launcher._pestana_ya_abierta(espera=1, paso=0.05)


def test_tras_actualizar_abre_pestana_si_la_cerraron(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(_pestana_esperando={"ts": 0.0}))
    monkeypatch.setenv("MIRARU_TRAS_ACTUALIZAR", "1")
    assert not launcher._pestana_ya_abierta(espera=0.3, paso=0.05)


def test_install_ps1_avisa_si_windows_es_de_32_bits():
    assert "PROCESSOR_ARCHITEW6432" in PS1


def test_microsoft_store_trae_la_lista_de_otra_instalacion(tmp_path):
    destino, viejo = tmp_path / "Miraru", tmp_path / "AnimeTracker"
    destino.mkdir()
    viejo.mkdir()
    (viejo / "anime_tracker.db").write_bytes(b"lista")
    (viejo / "credentials.json").write_text("{}")
    assert launcher._traer_datos_de_otra_instalacion(destino, [viejo]) == viejo
    assert (destino / "anime_tracker.db").read_bytes() == b"lista"
    assert (destino / "credentials.json").exists()
    # Nunca pisa una lista que ya existe
    (viejo / "anime_tracker.db").write_bytes(b"otra")
    assert launcher._traer_datos_de_otra_instalacion(destino, [viejo]) is None
    assert (destino / "anime_tracker.db").read_bytes() == b"lista"


def test_fuera_de_un_paquete_msix_no_se_considera_store():
    assert launcher.EMPAQUETADO is False
