"""
Crea los accesos directos (.lnk) de Miraru.

Lo usa install.ps1. Con el Control inteligente de aplicaciones de Windows 11
(Smart App Control) PowerShell funciona en modo de lenguaje restringido y no
puede usar WScript.Shell, así que el acceso se crea desde Python con la API de
Windows (IShellLinkW + IPersistFile) llamada con ctypes: sin dependencias.

Uso:  python _acceso_directo.py <carpeta de Miraru> [--sin-escritorio]
El acceso apunta a <carpeta>\\.venv\\Scripts\\pythonw.exe "<carpeta>\\launcher.py":
pythonw.exe está firmado por la Python Software Foundation, así que Windows lo deja abrir.
"""
from __future__ import annotations

import sys
from pathlib import Path

_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_ISHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"

# Posición de cada método en la vtable (orden de la interfaz en ShObjIdl.h / ObjIdl.h)
_QUERY_INTERFACE, _RELEASE = 0, 2
_SET_DESCRIPTION, _SET_WORKING_DIR, _SET_ARGUMENTS = 7, 9, 11
_SET_ICON_LOCATION, _SET_PATH = 17, 20
_PERSIST_SAVE = 6


def crear_lnk(ruta_lnk: Path, destino: str, argumentos: str = "", carpeta: str = "",
              icono: str = "", descripcion: str = "") -> None:
    import ctypes
    from ctypes import POINTER, byref, c_int, c_ulong, c_void_p, wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                    ("d4", ctypes.c_ubyte * 8)]

    ole32 = ctypes.oledll.ole32

    def guid(texto: str) -> GUID:
        g = GUID()
        ole32.CLSIDFromString(texto, byref(g))
        return g

    def metodo(obj: c_void_p, indice: int, restype, *argtypes):
        vtabla = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        prototipo = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
        funcion = prototipo(vtabla[indice])
        return lambda *a: funcion(obj, *a)

    hr = ctypes.HRESULT
    ole32.CoInitialize(None)
    enlace, persist = c_void_p(), c_void_p()
    try:
        ole32.CoCreateInstance(byref(guid(_CLSID_SHELL_LINK)), None, 1,  # CLSCTX_INPROC_SERVER
                               byref(guid(_IID_ISHELL_LINK_W)), byref(enlace))
        metodo(enlace, _SET_PATH, hr, wintypes.LPCWSTR)(destino)
        if argumentos:
            metodo(enlace, _SET_ARGUMENTS, hr, wintypes.LPCWSTR)(argumentos)
        if carpeta:
            metodo(enlace, _SET_WORKING_DIR, hr, wintypes.LPCWSTR)(carpeta)
        if descripcion:
            metodo(enlace, _SET_DESCRIPTION, hr, wintypes.LPCWSTR)(descripcion)
        if icono:
            metodo(enlace, _SET_ICON_LOCATION, hr, wintypes.LPCWSTR, c_int)(icono, 0)
        metodo(enlace, _QUERY_INTERFACE, hr, POINTER(GUID), POINTER(c_void_p))(
            byref(guid(_IID_IPERSIST_FILE)), byref(persist))
        metodo(persist, _PERSIST_SAVE, hr, wintypes.LPCWSTR, wintypes.BOOL)(str(ruta_lnk), True)
    finally:
        for obj in (persist, enlace):
            if obj.value:
                metodo(obj, _RELEASE, c_ulong)()
        ole32.CoUninitialize()


def _carpeta_especial(csidl: int) -> Path | None:
    """Escritorio / menú Inicio reales (el escritorio puede estar en OneDrive)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
            return Path(buf.value)
    except Exception:
        pass
    return None


def crear_accesos(carpeta_app: Path, escritorio: bool = True) -> list[Path]:
    carpeta_app = carpeta_app.resolve()
    pythonw = carpeta_app / ".venv" / "Scripts" / "pythonw.exe"
    launcher = carpeta_app / "launcher.py"
    icono = carpeta_app / "static" / "icon.ico"
    destinos = []
    programas = _carpeta_especial(0x02)          # CSIDL_PROGRAMS (menú Inicio)
    if programas:
        destinos.append(programas / "Miraru.lnk")
    if escritorio:
        mesa = _carpeta_especial(0x10)           # CSIDL_DESKTOPDIRECTORY
        if mesa:
            destinos.append(mesa / "Miraru.lnk")
    creados = []
    for d in destinos:
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            crear_lnk(d, str(pythonw), argumentos=f'"{launcher}"', carpeta=str(carpeta_app),
                      icono=str(icono) if icono.exists() else "",
                      descripcion="Miraru — tu biblioteca de anime")
            creados.append(d)
        except OSError as e:
            print(f"No se pudo crear {d}: {e}")
    return creados


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for hecho in crear_accesos(Path(sys.argv[1]), escritorio="--sin-escritorio" not in sys.argv[2:]):
        print(f"Acceso directo: {hecho}")
