# Publicar Miraru en Microsoft Store (gratis)

Microsoft Store firma los paquetes MSIX con su propio certificado: Miraru instalado
desde la Store abre en cualquier Windows, también con el **Control inteligente de
aplicaciones**, y se actualiza solo. Registrarse como desarrollador individual es
gratis (solo pide verificar la identidad con el DNI y un selfie).

Lo técnico ya está hecho: `build_msix.py` crea el paquete y el workflow
`.github/workflows/msix.yml` lo compila, lo instala en un Windows de pruebas, lo abre
y comprueba que funciona. Cada Release lo ejecuta.

## Una sola vez

1. Crea la cuenta de desarrollador en https://storedeveloper.microsoft.com
   (cuenta Microsoft personal → "Individual developer" → verificación con DNI + selfie).
2. En Partner Center: **Aplicaciones y juegos → Nueva aplicación → MSIX o PWA** y
   reserva el nombre **Miraru**.
3. En la app: **Administración de productos → Identidad del producto**. Copia:
   - `Package/Identity/Name`
   - `Package/Identity/Publisher`
   - `Package/Properties/PublisherDisplayName`
4. En GitHub → Settings → Secrets and variables → Actions → **Variables**, crea:
   - `MIRARU_MSIX_NAME` = Package/Identity/Name
   - `MIRARU_MSIX_PUBLISHER` = Package/Identity/Publisher
   - `MIRARU_MSIX_PUBLISHER_NAME` = Package/Properties/PublisherDisplayName
5. GitHub → Actions → **Paquete para Microsoft Store (MSIX)** → Run workflow. Al acabar,
   descarga el artefacto **Miraru-para-Microsoft-Store** (un .zip con `Miraru.msix`).
6. En Partner Center crea el **envío**: precio gratis, disponibilidad, clasificación de
   edad (cuestionario), ficha de la tienda (descripción, capturas de `screenshots/`),
   sube `Miraru.msix` en **Paquetes** y envíalo a certificación.

La capacidad `runFullTrust` (app de escritorio completa) pide una justificación: por
ejemplo *"Miraru es una aplicación de escritorio que arranca un servidor local
(127.0.0.1) y se usa desde el navegador; necesita confianza total para ejecutarse."*

## Cada versión nueva

Tras publicar la Release, descarga el artefacto del workflow y crea un envío nuevo con
el `Miraru.msix` (la versión del paquete sale de `core.py`).

## Detalles

- Dentro del paquete la carpeta del programa es de solo lectura: los datos se guardan en
  `%LOCALAPPDATA%\Miraru` (Windows lo redirige a la carpeta privada del paquete). La
  primera vez se copia la lista de una instalación anterior con el instalador `.exe`.
- La app no muestra el aviso de "nueva versión": la Store la actualiza sola.
- Desinstalar la app de la Store borra su lista: exportarla antes si se quiere guardar.
