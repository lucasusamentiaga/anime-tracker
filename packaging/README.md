# Packaging & distribución de Miraru

Objetivo: que el usuario dé **el mínimo de pasos**. De más fácil a más trabajo de tu parte:

| Forma | Pasos del usuario | Trabajo tuyo (una vez) |
|---|---|---|
| `Miraru-Portable.exe` | Descargar + doble clic | Ninguno (ya lo publica el workflow) |
| `Miraru-Setup.exe` | Descargar + Instalar | Ninguno (ya lo publica el workflow) |
| Scoop | `scoop install miraru` | Publicar el manifiesto en un bucket |
| winget | `winget install Miraru` | Enviar el manifiesto a winget-pkgs |

Los `.exe` los compila y publica solo `.github/workflows/release.yml` al empujar un tag (`git tag v2.7.0 && git push --tags`).

## Scoop

`scoop/miraru.json` es la plantilla. Tiene `checkver`+`autoupdate`, así que un bucket
mantiene versión y hash al día solos.

Para publicar:
1. Crea un repo `scoop-miraru` (un "bucket").
2. Copia `scoop/miraru.json` dentro.
3. Sustituye `hash` por el SHA256 real del `.exe` (o deja que el bot de autoupdate lo rellene en la primera actualización).

Tus usuarios:
```powershell
scoop bucket add miraru https://github.com/lucasusamentiaga/scoop-miraru
scoop install miraru
```

Calcular el hash a mano (PowerShell):
```powershell
(Get-FileHash Miraru-Portable.exe -Algorithm SHA256).Hash
```

## winget (`winget install Miraru`)

La forma más cómoda es **WinGet Releaser**, una GitHub Action que usa Komac para
crear y enviar el manifiesto a la winget-pkgs community repo en cada release.

Configuración (una vez):
1. Haz un fork de `microsoft/winget-pkgs`.
2. Crea un PAT clásico con scope `public_repo` y guárdalo como secret `WINGET_TOKEN`.
3. Primera versión: súbela a mano con `wingetcreate new` o `komac` (crea el identificador `Lucasusamentiaga.Miraru`).
4. A partir de ahí, añade este job a un workflow que corra tras publicar la Release:

```yaml
  winget:
    runs-on: windows-latest
    needs: build-windows
    if: startsWith(github.ref, 'refs/tags/')
    steps:
      - uses: vedantmgoyal9/winget-releaser@v2
        with:
          identifier: Lucasusamentiaga.Miraru
          installers-regex: 'Miraru-Setup\.exe$'
          token: ${{ secrets.WINGET_TOKEN }}
```

Alternativa por CLI (cross-platform): `komac update Lucasusamentiaga.Miraru --version 2.7.0 --urls <url-del-setup.exe>`.

## Firma de código (quitar el aviso de SmartScreen)

El aviso «editor desconocido» al instalar aparece porque el `.exe` no está firmado
(Authenticode). Es lo que más frena a quien descarga la app.

**El workflow ya está preparado**: `release.yml` incluye un paso de firma que se
**salta solo** mientras no haya certificado, así que hoy funciona sin tocar nada.
Para activarlo solo tienes que añadir dos secretos al repositorio.

### Paso 1 — Conseguir un certificado

Esto es lo único que no se puede automatizar: hay que comprarlo y validar identidad.

| Opción | Coste orientativo | Notas |
|---|---|---|
| **Azure Trusted Signing** | ~2 $/mes + uso | La opción moderna de Microsoft. Sin HSM físico. Requiere identidad verificada (empresa o particular con 3+ años de historial). **Recomendada.** |
| Certificado OV (Sectigo, DigiCert…) | ~200-400 $/año | Desde 2023 exige almacenamiento en HSM/token físico, lo que complica firmar desde CI. |
| Certificado EV | ~400-600 $/año | Da reputación inmediata en SmartScreen, pero es el más caro y engorroso. |
| **No firmar** | 0 € | Lo que hay ahora. El usuario pulsa *Más información → Ejecutar de todas formas*. |

> Aviso honesto: aunque firmes, SmartScreen puede seguir avisando hasta que el
> ejecutable acumule reputación (descargas sin incidencias). Con certificado EV la
> reputación es inmediata; con OV/Trusted Signing tarda un tiempo.

### Paso 2 — Cargar el certificado en GitHub

Con el `.pfx` en la mano, conviértelo a base64 y guárdalo como secreto:

```powershell
# Windows (PowerShell)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("miraru.pfx")) | Set-Clipboard
```
```bash
# macOS / Linux
base64 -w0 miraru.pfx
```

En *Settings → Secrets and variables → Actions* crea:

| Secreto | Contenido |
|---|---|
| `WINDOWS_CERT_BASE64` | el texto base64 del `.pfx` |
| `WINDOWS_CERT_PASSWORD` | la contraseña del `.pfx` |

Nada más. El siguiente `git push --tags` firmará ambos ejecutables, **verificará
la firma** y fallará el build si no valida (mejor eso que publicar algo roto).

> El `.pfx` solo existe en el runner durante el build y se borra al terminar.
> **Nunca** lo añadas al repositorio: gitleaks está en el CI justo para eso.

### Comprobar la firma en local

```powershell
Get-AuthenticodeSignature .\Miraru-Setup.exe | Format-List
```

## Fuentes
- WinGet Releaser (Action que usa Komac): https://github.com/marketplace/actions/winget-releaser
- Komac (creador de manifiestos winget): https://github.com/russellbanks/Komac
- Enviar manifiesto a winget-pkgs: https://learn.microsoft.com/en-us/windows/package-manager/package/repository
- winget-create (`wingetcreate`): https://github.com/microsoft/winget-create
