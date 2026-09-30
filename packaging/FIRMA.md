# Firmar los .exe de Miraru con SignPath (gratis para código abierto)

Sin firma, Windows avisa con SmartScreen ("editor desconocido") y, con el **Control
inteligente de aplicaciones**, directamente no deja abrir `Miraru-Setup.exe` ni
`Miraru-Portable.exe`. La instalación con un comando (`install.ps1`) no necesita firma;
esto sirve para que los `.exe` también funcionen en todos los equipos.

Todo lo técnico ya está hecho en el repositorio:

- Los `.exe` llevan nombre de producto (`Miraru`) y versión en sus metadatos (`build.py`).
- La sección **"Política de firma de código / Code signing policy"** del README tiene el
  texto que exige SignPath (atribución, roles y privacidad).
- `release.yml` firma automáticamente en cuanto existan las credenciales (si no, publica
  sin firma como hasta ahora). Firma primero `AnimeTracker.exe` y después empaqueta el
  instalador, para que el `.exe` instalado también vaya firmado.
- Las configuraciones de artefacto para SignPath están en `packaging/signpath/`.

## Lo que tienes que hacer tú (una sola vez)

1. **Verificación en dos pasos en GitHub** (obligatoria para SignPath):
   GitHub → Settings → Password and authentication → Two-factor authentication.
2. **Solicitar el certificado**: https://signpath.org/apply
   - Proyecto: `https://github.com/lucasusamentiaga/anime-tracker`
   - Licencia: MIT. Descarga: la página de Releases.
   - Indica que se compila con GitHub Actions (`.github/workflows/release.yml`).
   La aprobación la decide SignPath Foundation y puede tardar días o semanas.
3. Cuando te aprueben, en **SignPath** (app.signpath.io):
   - Instala la **SignPath GitHub App** en el repositorio (te lo indican en el alta).
   - Crea el proyecto con slug `miraru`.
   - Crea dos **artifact configurations** con slug `app` e `instaladores`, pegando el
     contenido de `packaging/signpath/app.xml` e `instaladores.xml`.
   - Usa la signing policy que te den (normalmente `release-signing`).
   - Crea un **API token** para CI.
4. En **GitHub → Settings → Secrets and variables → Actions**:
   - Secret `SIGNPATH_API_TOKEN` = el token del paso anterior.
   - Variable `SIGNPATH_ORGANIZATION_ID` = el ID de tu organización en SignPath.
   - (Opcional) Variables `SIGNPATH_PROJECT_SLUG` y `SIGNPATH_POLICY_SLUG` si no usas
     `miraru` y `release-signing`.
5. Quita del README la línea "Estado: solicitud a SignPath Foundation en trámite".

A partir de ahí, cada versión nueva (`git tag vX.Y.Z` + push) sale firmada. SignPath te
pedirá aprobar cada firma desde su web: es parte de sus reglas.

## Lo que la firma NO arregla

Dentro de los `.exe` no hay módulos de terceros sin firma que hagan falta para arrancar:
el núcleo usa Pydantic 1 en Python puro (ver `requirements.txt`). Los módulos nativos
opcionales (Web Push, Google Sheets) no se pueden firmar con SignPath (no son nuestros);
si Windows los bloquea, solo se desactiva esa función.
