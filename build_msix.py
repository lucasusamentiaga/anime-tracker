"""
Empaqueta Miraru como MSIX para publicarlo en Microsoft Store.

Por qué: el Control inteligente de aplicaciones de Windows 11 bloquea los .exe sin
firma. Microsoft Store firma gratis los paquetes MSIX con su propio certificado, así
que Miraru instalado desde la Store abre en cualquier PC (y se actualiza solo).

Uso (en Windows, después de `python build.py --solo-app`):
    python build_msix.py              -> dist/Miraru.msix (sin firmar: para subirlo a la Store)

La identidad del paquete la da Partner Center al reservar el nombre "Miraru"
(Producto > Identidad del producto). Se pasa por variables de entorno:
    MIRARU_MSIX_NAME            Package/Identity/Name       (p. ej. 12345Lucas.Miraru)
    MIRARU_MSIX_PUBLISHER       Package/Identity/Publisher  (p. ej. CN=ABCD-1234-...)
    MIRARU_MSIX_PUBLISHER_NAME  Package/Properties/PublisherDisplayName
Sin ellas se usa una identidad de pruebas (sirve para instalarlo firmado con un
certificado propio en CI, no para la Store).
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent
APP_DIST = ROOT / "dist" / "AnimeTracker"
LAYOUT = ROOT / "build" / "msix"
SALIDA = ROOT / "dist" / "Miraru.msix"

NOMBRE_PRUEBAS = "Miraru.Pruebas"
EDITOR_PRUEBAS = "CN=MiraruPruebas"

# (archivo, tamaño en px) que pide el manifiesto
LOGOS = [
    ("StoreLogo.png", 50),
    ("Square44x44Logo.png", 44),
    ("Square150x150Logo.png", 150),
    ("Wide310x150Logo.png", (310, 150)),
]


def version_msix() -> str:
    """La Store exige 4 números y el último a 0: 2.11.3 -> 2.11.3.0."""
    texto = (ROOT / "core.py").read_text(encoding="utf-8")
    v = re.search(r'VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)', texto)
    if not v:
        raise SystemExit("No se encontró VERSION en core.py")
    return ".".join(v.groups()) + ".0"


def identidad() -> tuple[str, str, str]:
    return (os.environ.get("MIRARU_MSIX_NAME") or NOMBRE_PRUEBAS,
            os.environ.get("MIRARU_MSIX_PUBLISHER") or EDITOR_PRUEBAS,
            os.environ.get("MIRARU_MSIX_PUBLISHER_NAME") or "lucasusamentiaga")


def generar_manifiesto(nombre: str, editor: str, editor_visible: str, version: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">
  <Identity Name={quoteattr(nombre)} Publisher={quoteattr(editor)} Version="{version}" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>Miraru</DisplayName>
    <PublisherDisplayName>{escape(editor_visible)}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
    <Description>Tu biblioteca de anime: seguimiento, estadisticas y recomendaciones.</Description>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="es-ES" />
    <Resource Language="en-US" />
  </Resources>
  <Applications>
    <Application Id="Miraru" Executable="AnimeTracker.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="Miraru" Description="Tu biblioteca de anime"
        BackgroundColor="transparent"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" />
      </uap:VisualElements>
    </Application>
  </Applications>
  <Capabilities>
    <Capability Name="internetClient" />
    <Capability Name="privateNetworkClientServer" />
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""


def crear_logos(carpeta: Path) -> None:
    from PIL import Image
    carpeta.mkdir(parents=True, exist_ok=True)
    logo = Image.open(ROOT / "static" / "logo.png").convert("RGBA")
    for nombre, tam in LOGOS:
        ancho, alto = (tam, tam) if isinstance(tam, int) else tam
        lienzo = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
        lado = min(ancho, alto)
        icono = logo.resize((lado, lado), Image.LANCZOS)
        lienzo.paste(icono, ((ancho - lado) // 2, (alto - lado) // 2), icono)
        lienzo.save(carpeta / nombre)


def buscar_makeappx() -> str:
    candidatos = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\makeappx.exe"))
    if candidatos:
        return candidatos[-1]
    encontrado = shutil.which("makeappx")
    if encontrado:
        return encontrado
    raise SystemExit("No se encontró makeappx.exe (Windows SDK).")


def main() -> None:
    if not (APP_DIST / "AnimeTracker.exe").exists():
        raise SystemExit(f"Falta {APP_DIST / 'AnimeTracker.exe'}: ejecuta antes python build.py --solo-app")
    nombre, editor, editor_visible = identidad()
    version = version_msix()
    if LAYOUT.exists():
        shutil.rmtree(LAYOUT)
    shutil.copytree(APP_DIST, LAYOUT)
    crear_logos(LAYOUT / "Assets")
    (LAYOUT / "AppxManifest.xml").write_text(
        generar_manifiesto(nombre, editor, editor_visible, version), encoding="utf-8")
    SALIDA.unlink(missing_ok=True)
    subprocess.run([buscar_makeappx(), "pack", "/d", str(LAYOUT), "/p", str(SALIDA), "/o"], check=True)
    print(f"MSIX: {SALIDA} ({SALIDA.stat().st_size / 1024 / 1024:.0f} MB) - {nombre} {version}")
    if nombre == NOMBRE_PRUEBAS:
        print("  (identidad de pruebas: para la Store define MIRARU_MSIX_NAME y MIRARU_MSIX_PUBLISHER)")


if __name__ == "__main__":
    sys.exit(main())
