"""
build.py — Genera AnimeTracker-Setup.exe autocontenido.

El .exe resultante:
  - NO requiere Python instalado en el equipo del usuario
  - Contiene la app completa + Python embebido + todas las dependencias
  - El usuario solo necesita ejecutar AnimeTracker-Setup.exe

Proceso:
  1. Compila la app (launcher + todo) con PyInstaller → dist/AnimeTracker/
  2. Empaqueta esa carpeta en un ZIP dentro de un segundo .exe (el instalador)
  3. El instalador extrae todo, crea accesos directos y lanza la app

Uso (como desarrollador):
  Abrir compilar.bat  →  esperar ~5 min  →  dist/AnimeTracker-Setup.exe listo
"""

import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

ROOT      = Path(__file__).parent.resolve()

# La versión sale de core.py, que es la única fuente de verdad. Se lee del
# fichero en vez de importarlo para que build.py siga funcionando aunque el
# entorno no tenga instaladas las dependencias de la app.
def _leer_version() -> str:
    texto = (ROOT / "core.py").read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', texto, _re.M)
    if not m:
        raise RuntimeError("No se encontró VERSION en core.py")
    return m.group(1)


VERSION   = _leer_version()
DIST      = ROOT / "dist"
BUILD_TMP = ROOT / "_build_tmp"
APP_DIST  = DIST / "AnimeTracker"
SETUP_EXE = DIST / "AnimeTracker-Setup.exe"
SEP       = ";"   # Windows path separator for --add-data

# Módulos propios del proyecto. Antes se enumeraban A MANO en tres listas
# (datas, HIDDEN y validate_sources) y se quedaban atrás: anilist_sync.py,
# watch_folder.py y metadatos.py no entraban en el .exe → ImportError al
# arrancar la versión empaquetada. Ahora se descubren solos.
_NO_EMPAQUETAR = {"build.py", "launcher.py"}   # launcher es el entry point


def modulos_propios() -> list[Path]:
    """Módulos .py de primer nivel que main.py puede importar."""
    return sorted(
        p for p in ROOT.glob("*.py")
        if p.name not in _NO_EMPAQUETAR
        and not p.name.startswith(("_", "test_"))
    )


def _paquete(nombre: str) -> list[str]:
    """['scrapers', 'scrapers.anilist', ...] para un paquete propio."""
    return [nombre] + sorted(
        f"{nombre}.{p.stem}" for p in (ROOT / nombre).glob("*.py")
        if p.stem != "__init__"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def step(n: int, msg: str):
    bar = "─" * 58
    print(f"\n{bar}\n  [{n}] {msg}\n{bar}")


def run(cmd: list, **kw):
    display = " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd)
    print(f"  $ {display}")
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        print(f"\n  ERROR: código {r.returncode}")
        sys.exit(r.returncode)


def check_deps():
    missing = []
    for pkg in ["PyInstaller", "fastapi", "uvicorn", "bs4", "requests",
                "google.auth", "googleapiclient"]:
        try:
            __import__(pkg.split(".")[0])
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n  ERROR: Faltan paquetes: {', '.join(missing)}")
        print(f"  Python: {sys.executable}")
        print("\n  Ejecuta primero:\n    pip install -r requirements.txt")
        sys.exit(1)
    print(f"  Dependencias OK  (Python {sys.version.split()[0]})")


# ── Hidden imports necesarios para el .exe ────────────────────────────────────

HIDDEN = [
    # uvicorn
    "uvicorn", "uvicorn.main", "uvicorn.config", "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    # fastapi / starlette
    "fastapi", "fastapi.applications", "fastapi.routing",
    "starlette", "starlette.applications", "starlette.routing",
    "starlette.staticfiles", "starlette.responses",
    "starlette.middleware", "starlette.middleware.cors",
    "starlette.middleware.base", "starlette.background",
    "starlette.concurrency", "starlette.datastructures",
    "starlette.exceptions", "starlette.types",
    # pydantic
    "pydantic", "pydantic.v1",
    # anyio / h11
    "anyio", "anyio._backends._asyncio", "h11",
    # email
    "email.mime.text", "email.mime.multipart",
    # google
    "google.auth", "google.auth.transport.requests",
    "google.auth.crypt", "google.auth.crypt._python_rsa",
    "google.oauth2", "google.oauth2.service_account",
    "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
    "cachetools", "pyasn1", "rsa",
    # scraping
    "requests", "bs4", "beautifulsoup4",
    # urllib3 / certifi
    "urllib3", "certifi", "charset_normalizer", "idna",
    # std
    "multiprocessing", "sqlite3", "importlib.util",
    "hashlib", "smtplib", "collections",
    "email", "email.mime", "email.mime.text", "email.mime.multipart",
    "xml.etree.ElementTree", "html.parser",
    # bs4 parsers
    "lxml", "html5lib",
    # propios: se añaden abajo, descubiertos automáticamente
]

HIDDEN += [p.stem for p in modulos_propios()] + _paquete("scrapers") + _paquete("routers")


# ── Paso 1: compilar la app principal ─────────────────────────────────────────

def validate_sources():
    """Valida que todos los archivos .py compilan sin errores antes de empaquetar."""
    import py_compile
    to_check = (modulos_propios() + [ROOT / "launcher.py"]
                + list((ROOT / "scrapers").glob("*.py"))
                + list((ROOT / "routers").glob("*.py")))

    failed = []
    for f in to_check:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            failed.append(f"{f.name}: {e}")

    if failed:
        print("\n  ERROR: Los siguientes archivos tienen errores de sintaxis:")
        for err in failed:
            print(f"    ✗ {err}")
        print("\n  Corrige los errores antes de compilar.")
        sys.exit(1)
    print(f"  ✓ {len(to_check)} archivos validados sin errores")


def build_app(onefile: bool = False):
    step(1, f"Compilando la app con PyInstaller ({'portable --onefile' if onefile else '--onedir'})")

    validate_sources()

    for d in [DIST, BUILD_TMP]:
        if d.exists():
            shutil.rmtree(d)

    # Archivos de datos que deben estar en _internal/ del bundle
    datas = [
        (str(ROOT / "templates"),    "templates"),
        (str(ROOT / "static"),       "static"),
        (str(ROOT / "scrapers"),     "scrapers"),
        (str(ROOT / "routers"),      "routers"),   # APIRouter por dominio
        # .py fuente — necesarios para importlib en launcher.py
    ] + [(str(p), ".") for p in modulos_propios()]
    datas_args = []
    for src, dst in datas:
        datas_args += ["--add-data", f"{src}{SEP}{dst}"]

    hidden_args = []
    for h in HIDDEN:
        hidden_args += ["--hidden-import", h]

    icon_args = []
    icon = ROOT / "static" / "icon.ico"
    if icon.exists():
        icon_args = ["--icon", str(icon)]

    run([
        sys.executable, "-m", "PyInstaller",
        "--name",       "Miraru-Portable" if onefile else "AnimeTracker",
        # --onefile: un único .exe portable (descargar + doble clic, sin instalar).
        # --onedir: carpeta (arranque más rápido), que el instalador empaqueta.
        "--onefile" if onefile else "--onedir",
        "--noconsole",       # sin ventana CMD en el usuario final
        "--distpath",   str(DIST),
        "--workpath",   str(BUILD_TMP),
        "--specpath",   str(BUILD_TMP),
        "--additional-hooks-dir", str(ROOT / "hooks"),
        *datas_args,
        *hidden_args,
        *icon_args,
        str(ROOT / "launcher.py"),
    ])

    if onefile:
        exe = DIST / "Miraru-Portable.exe"
        if exe.exists():
            print(f"\n  Portable compilado: {exe.stat().st_size / 1024 / 1024:.0f} MB → {exe}")
    else:
        size = sum(f.stat().st_size for f in APP_DIST.rglob("*") if f.is_file())
        print(f"\n  App compilada: {size / 1024 / 1024:.0f} MB en {APP_DIST}")


# ── Paso 2: código fuente del instalador ─────────────────────────────────────

def _write_installer_source(path: Path):
    """
    Genera el instalador GUI en Python.
    Se compila después como segundo .exe con PyInstaller --onefile.
    El bundle ZIP de la app va embebido dentro.
    """
    code = textwrap.dedent(r'''
        import multiprocessing
        multiprocessing.freeze_support()

        import os, sys, zipfile, threading, ctypes, winreg, subprocess, time
        from pathlib import Path
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox

        # ── Constantes ────────────────────────────────────────────────────────
        BUNDLE_NAME = "_app_bundle.zip"
        LOGO_NAME   = "_logo.png"
        APP_NAME    = "Miraru"
        EXE_NAME    = "AnimeTracker.exe"
        APP_VERSION = "@@VERSION@@"
        REG_KEY     = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\AnimeTracker"

        DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Public")) / "AnimeTracker"

        # ── Traducciones del instalador ───────────────────────────────────────
        TEXTS = {
            "es": {"title":"Instalar Miraru","ver":"Versión {v}",
                   "folder":"Carpeta de instalación:","desktop":"Acceso directo en escritorio",
                   "start":"Agregar al menú inicio","btn":"Instalar","ready":"Listo para instalar.",
                   "killing":"Cerrando versión anterior...","extracting":"Extrayendo archivos ({pct}%)...",
                   "shortcuts":"Creando accesos directos...","reg":"Finalizando instalación...",
                   "done":"Instalación completada.",
                   "ask_open":"Instalación completada.\n¿Abrir Miraru ahora?",
                   "err":"Error de instalación","lang":"Idioma / Language:"},
            "en": {"title":"Install Miraru","ver":"Version {v}",
                   "folder":"Installation folder:","desktop":"Create desktop shortcut",
                   "start":"Add to Start Menu","btn":"Install","ready":"Ready to install.",
                   "killing":"Closing previous version...","extracting":"Extracting files ({pct}%)...",
                   "shortcuts":"Creating shortcuts...","reg":"Finishing installation...",
                   "done":"Installation complete.",
                   "ask_open":"Installation complete.\nOpen Miraru now?",
                   "err":"Installation error","lang":"Idioma / Language:"},
            "fr": {"title":"Installer Miraru","ver":"Version {v}",
                   "folder":"Dossier d'installation :","desktop":"Raccourci sur le bureau",
                   "start":"Ajouter au menu Démarrer","btn":"Installer","ready":"Prêt à installer.",
                   "killing":"Fermeture version précédente...","extracting":"Extraction ({pct}%)...",
                   "shortcuts":"Création des raccourcis...","reg":"Finalisation...",
                   "done":"Installation terminée.",
                   "ask_open":"Installation terminée.\nOuvrir Miraru maintenant ?",
                   "err":"Erreur d'installation","lang":"Idioma / Language:"},
            "de": {"title":"Miraru installieren","ver":"Version {v}",
                   "folder":"Installationsordner:","desktop":"Desktop-Verknüpfung",
                   "start":"Zum Startmenü hinzufügen","btn":"Installieren","ready":"Bereit.",
                   "killing":"Vorherige Version wird geschlossen...","extracting":"Extrahiere ({pct}%)...",
                   "shortcuts":"Verknüpfungen erstellen...","reg":"Abschließen...",
                   "done":"Installation abgeschlossen.",
                   "ask_open":"Installation abgeschlossen.\nMiraru jetzt öffnen?",
                   "err":"Installationsfehler","lang":"Idioma / Language:"},
        }
        _lang = "es"

        def T(k, **kw):
            txt = TEXTS.get(_lang, TEXTS["es"]).get(k, k)
            for key, val in kw.items():
                txt = txt.replace("{" + key + "}", str(val))
            return txt

        # ── Helpers ───────────────────────────────────────────────────────────
        def create_shortcut(target: Path, lnk: Path, icon: Path = None):
            """Create a Windows shortcut using a temp PowerShell script."""
            import tempfile
            lines = [
                '$ws = New-Object -ComObject WScript.Shell',
                f"$s = $ws.CreateShortcut('{lnk}')",
                f"$s.TargetPath = '{target}'",
                f"$s.WorkingDirectory = '{target.parent}'",
            ]
            if icon and icon.exists():
                lines.append(f"$s.IconLocation = '{icon}'")
            lines.append('$s.Save()')
            # Write script to temp file to avoid quote-escaping issues
            ps1 = Path(tempfile.mktemp(suffix='.ps1'))
            ps1.write_text('\n'.join(lines), encoding='utf-8')
            subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                 '-File', str(ps1)],
                capture_output=True, timeout=15,
            )
            ps1.unlink(missing_ok=True)

        def kill_app():
            try:
                r = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True
                )
                if EXE_NAME.lower() in r.stdout.lower():
                    subprocess.run(["taskkill", "/IM", EXE_NAME, "/F"], capture_output=True)
                    time.sleep(2)
            except Exception:
                pass

        def register(install_dir: Path):
            try:
                exe = install_dir / EXE_NAME
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
                    winreg.SetValueEx(k, "DisplayName",     0, winreg.REG_SZ,    APP_NAME)
                    winreg.SetValueEx(k, "DisplayVersion",  0, winreg.REG_SZ,    APP_VERSION)
                    winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ,    str(install_dir))
                    winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,    f'"{exe}" --uninstall')
                    winreg.SetValueEx(k, "DisplayIcon",     0, winreg.REG_SZ,    str(exe))
                    winreg.SetValueEx(k, "Publisher",       0, winreg.REG_SZ,    "Miraru")
                    winreg.SetValueEx(k, "NoModify",        0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(k, "NoRepair",        0, winreg.REG_DWORD, 1)
            except Exception:
                pass

        # ── GUI ───────────────────────────────────────────────────────────────
        class Setup(tk.Tk):
            BG = "#0f0f13"; CARD = "#1a1a24"; FG = "#e2e2e8"
            MUTED = "#6b6b88"; ACC = "#7c3aed"; LIGHT = "#a78bfa"

            def __init__(self):
                super().__init__()
                self.resizable(False, False)
                self.configure(bg=self.BG)
                self.geometry("500x430")
                self._build()
                self._center()
                self._refresh_texts()

            def _center(self):
                self.update_idletasks()
                x = (self.winfo_screenwidth()  - 500) // 2
                y = (self.winfo_screenheight() - 430) // 2
                self.geometry(f"500x430+{x}+{y}")

            def _build(self):
                B, C, F, M, A, L = self.BG, self.CARD, self.FG, self.MUTED, self.ACC, self.LIGHT

                # Logo
                meipass = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
                try:
                    from PIL import Image, ImageTk, ImageDraw
                    img  = Image.open(meipass / LOGO_NAME).convert("RGBA").resize((68, 68))
                    mask = Image.new("L", (68, 68), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 68, 68), fill=255)
                    img.putalpha(mask)
                    self._logo = ImageTk.PhotoImage(img)
                    tk.Label(self, image=self._logo, bg=B).pack(pady=(20, 4))
                except Exception:
                    tk.Label(self, text="🎌", font=("Segoe UI", 30), fg=L, bg=B).pack(pady=(20, 4))

                tk.Label(self, text=APP_NAME, font=("Segoe UI", 19, "bold"), fg=L, bg=B).pack()
                self._ver_lbl = tk.Label(self, font=("Segoe UI", 9), fg=M, bg=B)
                self._ver_lbl.pack(pady=(1, 0))

                # Lang selector
                lang_frm = tk.Frame(self, bg=B)
                lang_frm.pack(pady=(6, 0))
                tk.Label(lang_frm, text="Lang:", font=("Segoe UI", 8), fg=M, bg=B).pack(side="left", padx=(0, 4))
                self._lang_var = tk.StringVar(value=_lang)
                for lc, lf in [("es", "🇪🇸 ES"), ("en", "🇬🇧 EN"), ("fr", "🇫🇷 FR"), ("de", "🇩🇪 DE")]:
                    tk.Radiobutton(lang_frm, text=lf, variable=self._lang_var, value=lc,
                                   font=("Segoe UI", 8), fg=L, bg=B, selectcolor=B,
                                   activebackground=B, command=self._on_lang
                                   ).pack(side="left", padx=3)

                # Card: folder
                card = tk.Frame(self, bg=C, highlightbackground="#2a2a38", highlightthickness=1)
                card.pack(fill="x", padx=24, pady=10)
                self._folder_lbl = tk.Label(card, font=("Segoe UI", 9), fg="#a0a0b8", bg=C)
                self._folder_lbl.pack(anchor="w", padx=12, pady=(10, 2))
                row = tk.Frame(card, bg=C)
                row.pack(fill="x", padx=12, pady=(0, 10))
                self._path = tk.StringVar(value=str(DEFAULT_DIR))
                tk.Entry(row, textvariable=self._path, font=("Segoe UI", 9),
                         bg="#12121a", fg=F, insertbackground=F, relief="flat", bd=4
                         ).pack(side="left", fill="x", expand=True, padx=(0, 8))
                tk.Button(row, text="…", font=("Segoe UI", 9), bg="#3d2d70", fg="#c4b5fd",
                          relief="flat", bd=0, padx=10,
                          command=lambda: self._path.set(
                              filedialog.askdirectory(initialdir=self._path.get()) or self._path.get()
                          )).pack(side="right")

                # Checkboxes
                self._desk = tk.BooleanVar(value=True)
                self._menu = tk.BooleanVar(value=True)
                self._desk_chk = tk.Checkbutton(self, variable=self._desk, font=("Segoe UI", 9),
                                                fg=F, bg=B, selectcolor=C, activebackground=B, activeforeground=F)
                self._desk_chk.pack(anchor="w", padx=24)
                self._menu_chk = tk.Checkbutton(self, variable=self._menu, font=("Segoe UI", 9),
                                                fg=F, bg=B, selectcolor=C, activebackground=B, activeforeground=F)
                self._menu_chk.pack(anchor="w", padx=24)

                # Progress bar (plain, no custom style to avoid TclError)
                self._prog = ttk.Progressbar(self, length=452, mode="determinate")
                self._prog.pack(padx=24, pady=(10, 3))
                self._status = tk.StringVar()
                tk.Label(self, textvariable=self._status, font=("Segoe UI", 8), fg=M, bg=B).pack()

                # Install button
                self._btn = tk.Button(
                    self, font=("Segoe UI", 10, "bold"),
                    bg=A, fg="white", relief="flat", bd=0,
                    padx=22, pady=7, cursor="hand2",
                    command=self._start
                )
                self._btn.pack(pady=(10, 0))

            def _refresh_texts(self):
                global _lang
                _lang = self._lang_var.get()
                self.title(T("title"))
                self._ver_lbl.config(text=T("ver", v=APP_VERSION))
                self._folder_lbl.config(text=T("folder"))
                self._desk_chk.config(text=T("desktop"))
                self._menu_chk.config(text=T("start"))
                self._btn.config(text=T("btn"))
                self._status.set(T("ready"))

            def _on_lang(self):
                self._refresh_texts()

            def _st(self, msg: str, pct: int):
                self._status.set(msg)
                self._prog["value"] = pct
                self.update_idletasks()

            def _start(self):
                self._btn.config(state="disabled")
                threading.Thread(target=self._run, daemon=True).start()

            def _run(self):
                try:
                    idir = Path(self._path.get())

                    self._st(T("killing"), 3)
                    kill_app()

                    idir.mkdir(parents=True, exist_ok=True)

                    meipass = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
                    bundle  = meipass / BUNDLE_NAME
                    if not bundle.exists():
                        raise FileNotFoundError(
                            f"Bundle no encontrado: {bundle}\n"
                            "Vuelve a descargar el instalador."
                        )

                    # Extraer ZIP con barra de progreso real
                    with zipfile.ZipFile(bundle, "r") as z:
                        members = z.namelist()
                        total   = max(len(members), 1)
                        for i, m in enumerate(members):
                            dest = idir / m
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            # Manejo de archivos bloqueados
                            try:
                                with z.open(m) as src, open(dest, "wb") as dst:
                                    dst.write(src.read())
                            except PermissionError:
                                bak = dest.with_suffix(".bak")
                                try:
                                    dest.rename(bak)
                                except Exception:
                                    pass
                                try:
                                    with z.open(m) as src, open(dest, "wb") as dst:
                                        dst.write(src.read())
                                    bak.unlink(missing_ok=True)
                                except Exception:
                                    pass
                            pct = 5 + int((i / total) * 70)
                            if i % 25 == 0:
                                self._st(T("extracting", pct=pct), pct)

                    self._st(T("shortcuts"), 78)
                    exe  = idir / EXE_NAME
                    icon = idir / "_internal" / "static" / "icon.ico"

                    if self._desk.get():
                        desk = Path(os.path.expanduser("~")) / "Desktop"
                        if not desk.exists():
                            desk = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
                        if desk.exists():
                            create_shortcut(exe, desk / f"{APP_NAME}.lnk", icon)

                    if self._menu.get():
                        start = (
                            Path(os.environ.get("APPDATA", ""))
                            / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                        )
                        if start.exists():
                            create_shortcut(exe, start / f"{APP_NAME}.lnk", icon)

                    self._st(T("reg"), 93)
                    register(idir)

                    self._st(T("done"), 100)
                    if messagebox.askyesno(APP_NAME, T("ask_open")):
                        os.startfile(str(exe))
                    self.destroy()

                except Exception as e:
                    messagebox.showerror(T("err"), str(e))
                    self._btn.config(state="normal")
                    self._status.set(T("ready"))
                    self._prog["value"] = 0

        if __name__ == "__main__":
            Setup().mainloop()
    ''').lstrip()

    # La plantilla es una cadena cruda (no f-string), así que la versión se
    # inyecta por sustitución. Antes estaba escrita a mano y se quedó en 2.4.0
    # mientras la app iba por la 2.8: el instalador registraba esa versión falsa
    # en "Programas y características" de Windows.
    code = code.replace("@@VERSION@@", VERSION)
    if "@@VERSION@@" in code:                    # defensa por si cambia el marcador
        raise RuntimeError("No se pudo inyectar la versión en el instalador")

    path.write_text(code, encoding="utf-8")


# ── Paso 3: compilar el instalador ───────────────────────────────────────────

def build_installer():
    step(2, "Empaquetando app como ZIP interno")

    bundle = ROOT / "_app_bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in APP_DIST.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(APP_DIST))
    size = bundle.stat().st_size / 1024 / 1024
    print(f"  Bundle: {size:.1f} MB")

    step(3, "Compilando AnimeTracker-Setup.exe")

    installer_src = ROOT / "_installer_src.py"
    _write_installer_source(installer_src)

    icon_args: list = []
    icon = ROOT / "static" / "icon.ico"
    if icon.exists():
        icon_args = ["--icon", str(icon)]

    logo_args: list = []
    logo = ROOT / "static" / "logo.png"
    if logo.exists():
        logo_args = ["--add-data", f"{logo}{SEP}_logo.png"]

    run([
        sys.executable, "-m", "PyInstaller",
        "--name",     "AnimeTracker-Setup",
        "--onefile",          # UN SOLO .EXE autocontenido
        "--noconsole",
        "--distpath", str(DIST),
        "--workpath", str(BUILD_TMP),
        "--specpath", str(BUILD_TMP),
        "--add-data", f"{bundle}{SEP}.",
        *logo_args,
        *icon_args,
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "PIL.ImageDraw",
        str(installer_src),
    ])

    bundle.unlink(missing_ok=True)
    installer_src.unlink(missing_ok=True)

    size = SETUP_EXE.stat().st_size / 1024 / 1024
    print(f"\n  Instalador: {SETUP_EXE.name}  ({size:.0f} MB)")


# ── Limpieza ──────────────────────────────────────────────────────────────────

def cleanup():
    step(4, "Limpiando temporales")
    for p in [BUILD_TMP, ROOT / "__pycache__"]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for f in ROOT.glob("*.spec"):
        f.unlink(missing_ok=True)
    print("  Listo.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Miraru — Build Script v4.0")
    print(f"  Python: {sys.executable}")
    print(f"  Directorio: {ROOT}\n")

    portable = "--portable" in sys.argv[1:]
    check_deps()
    if portable:
        # Build portable: un único .exe (sin instalador). Para `python build.py --portable`.
        build_app(onefile=True)
        cleanup()
        print(f"\n{'=' * 60}")
        print("  LISTO (portable). Comparte este único archivo:")
        print(f"  {DIST / 'Miraru-Portable.exe'}")
    else:
        build_app()
        build_installer()
        cleanup()
        print(f"\n{'=' * 60}")
        print("  LISTO. Comparte este archivo con tus usuarios:")
        print(f"  {SETUP_EXE}")
    print(f"{'=' * 60}\n")
