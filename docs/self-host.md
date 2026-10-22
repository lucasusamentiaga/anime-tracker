# 🐳 Autoalojar Miraru con Docker

> **English (summary):** Build the image with `docker build -t miraru .` and run it with
> `docker run -d --name miraru -p 127.0.0.1:8765:8765 -v miraru-data:/data miraru` (port
> published on loopback only). Your library (SQLite database, automatic backups and
> `credentials.json`) lives in the `/data` volume. Change the port with `-e PORT=XXXX`.
> **Warning:** with a **fresh volume there is no PIN**, so everything under `/api/*` is
> open on any port you publish — set the PIN first (see *Activar el PIN*), then publish
> wider, and anything beyond your machine or your home LAN additionally requires TLS in
> front of it (reverse proxy) — see *Seguridad* below. Details follow in the Spanish guide;
> the commands here are language‑independent.

---

## Índice

- [Requisitos](#requisitos)
- [Construir y arrancar](#construir-y-arrancar)
  - [Activar el PIN (volumen nuevo)](#activar-el-pin-volumen-nuevo)
- [Dónde viven los datos](#dónde-viven-los-datos)
- [Actualizar la imagen](#actualizar-la-imagen)
- [Copias de seguridad](#copias-de-seguridad)
- [Seguridad](#seguridad)
- [Resolución de problemas](#resolución-de-problemas)

## Requisitos

- Docker (o un runtime compatible: Podman, nerdctl…).
- Un directorio o volumen para los datos persistidos.

La imagen se basa en **`python:3.13-slim`** (versión fijada a propósito: FastAPI 0.125 +
Pydantic 1.10 no importan en Python ≥ 3.14) e instala **solo `requirements.txt`**, sin
herramientas de desarrollo ni de test. Ejecuta el servidor con un **usuario no root**
(`miraru`, uid 1000).

## Construir y arrancar

```bash
git clone https://github.com/lucasusamentiaga/anime-tracker.git
cd anime-tracker
docker build -t miraru .

# Arrancar (la biblioteca queda en el volumen de Docker `miraru-data`)
# Publicamos el puerto SOLO en loopback del anfitrión (127.0.0.1): es lo seguro
# para la primera puesta en marcha con un volumen aún sin configurar.
docker run -d --name miraru -p 127.0.0.1:8765:8765 -v miraru-data:/data miraru
```

Abre `http://localhost:8765/app` (la primera vez tarda unos segundos: al arrancar se
inicializa la BD y los hilos de fondo; el contenedor espera hasta 30 s antes de dar por
fallido el healthcheck del endpoint `/api/health`).

> ⚠️ **Volumen recién creado = aún no hay PIN.** El control de acceso LAN de Miraru
> (`_lan_auth_guard` en `main.py`) solo exige token cuando la BD ya tiene guardado
> `mobile_enabled='1'`; ese flag vive en la propia BD del volumen, así que con un volumen
> nuevo **toda la API (`/api/*`) queda abierta en el puerto que publiques**. Por eso el
> comando de arriba publica solo en `127.0.0.1`: nadie más que tu PC puede llegar.
> Sigue [Activar el PIN](#activar-el-pin-volumen-nuevo) antes de publicar más (`-p 8765:8765`,
> proxy inverso…).

### Activar el PIN (volumen nuevo)

Con el contenedor publicado en `127.0.0.1:8765`, desde el navegador de tu PC:

1. En `http://localhost:8765/app` abre **📱 Acceso móvil**, elige un PIN y pulsa
   **Activar** (es el mismo flujo que en escritorio).
2. No hace falta reiniciar el contenedor: ya escucha en `0.0.0.0`, y en cada petición
   `_mobile_mode_active` releerá `mobile_enabled` de la BD — al activarlo desde la
   interfaz, los clientes externos ya exigen token.
   Al punto: tu propio navegador también dejará de ser «loopback» para el guardia, porque
   vía `-p` sus peticiones entran con la IP del puente de Docker; si recarga y ve un 401,
   no está roto — la web pedirá el PIN ella sola (`/api/mobile/auth` es ruta pública) y
   seguirá funcionando.

O, sin navegador, con la API que la propia pantalla usa
(`POST /api/mobile/enable` guarda el PIN y `mobile_enabled='1'` en un solo paso; PIN de
4-8 dígitos):

```bash
curl -X POST http://127.0.0.1:8765/api/mobile/enable \
     -H "Content-Type: application/json" -d '{"pin":"1234"}'
```

Compruébalo con `curl http://127.0.0.1:8765/api/mobile/status`
(`"pin_configurado": true`). A partir de aquí puedes republicar el puerto en la LAN
(`docker rm -f miraru && docker run -d --name miraru -p 8765:8765 -v miraru-data:/data miraru`):
la LAN de tu casa es lo máximo que te recomendamos publicar; para más, solo vía proxy con
TLS (ver *Seguridad*).

> Nota escritorio vs contenedor: en escritorio ese endpoint dice «reinicia la app», porque
> el `launcher.py` decide el binding (`127.0.0.1` u `0.0.0.0`) al arrancar. El contenedor
> ya escucha siempre en `0.0.0.0`, así que el cambio de guardia (`_mobile_mode_active`
> lee la BD por petición) surte efecto al instante, sin reiniciar.

**Cambiar el puerto.** El CMD del contenedor lanza

```
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8765}
```

Ajusta ambos lados con un solo valor:

```bash
docker run -d --name miraru -p 127.0.0.1:3000:3000 -e PORT=3000 -v miraru-data:/data miraru
```

> Nota: el bloque `__main__` de `main.py` escucha en `127.0.0.1` (localhost de escritorio).
> El contenedor **no** ejecuta ese bloque: lanza uvicorn a mano con `--host 0.0.0.0` para
> que la web sea accesible desde fuera del contenedor. Así no se toca `main.py` y en tu PC
> el comportamiento sigue siendo el de siempre (solo localhost).
> ⚠️ Por la misma razón, `-e ANIME_PORT=...` en el contenedor **no hace nada** (esa
> variable solo la lee el bloque `__main__`, que aquí no se ejecuta). Usa siempre
> `-e PORT=...`.

**Guardar los datos fuera de Docker.** Si prefieres una carpeta del anfitrión en lugar de
un volumen con nombre (uid 1000 en el contenedor; ajusta permisos si hace falta):

```bash
mkdir -p ~/miraru-data && chown 1000:1000 ~/miraru-data
docker run -d --name miraru -p 127.0.0.1:8765:8765 -v ~/miraru-data:/data miraru
```

## Dónde viven los datos

Todo lo que te importa queda en el volumen `/data`:

| Ruta                  | Qué es                                                     |
|-----------------------|------------------------------------------------------------|
| `/data/anime_tracker.db` | La base de datos SQLite (animes, manga, pelis/series, config) |
| `/data/backups/`      | Copias automáticas diarias (`.zip`, retención de 7 días)   |
| `/data/credentials.json` | Credenciales de Google Sheets, si configuras el sync (opcional) |

Las variables de entorno de la imagen son exactamente las que ya usa la app:
`ANIME_APP_DIR=/data` y `ANIME_DB_PATH=/data/anime_tracker.db` (las que lee
`database.py`); no hay nombres nuevos que aprender.

## Actualizar la imagen

En la misma carpeta del repositorio que usaste en [Construir y arrancar](#construir-y-arrancar):

```bash
cd anime-tracker
git pull
docker build -t miraru .
docker rm -f miraru
docker run -d --name miraru -p 127.0.0.1:8765:8765 -v miraru-data:/data miraru
```

El volumen se conserva: la BD tiene migraciones automáticas al arrancar y los datos no se
tocan al reemplazar el contenedor. Si quieres congelar una versión concreta en vez de
seguir `main`, construye desde un tag:

```bash
docker build -t miraru:vx.y.z https://github.com/lucasusamentiaga/anime-tracker.git#vx.y.z
```

(dentro de la imagen quedan las dependencias de `requirements.txt` de ese tag).

## Copias de seguridad

**Lo más cómodo:** los `.zip` de `/data/backups` que la app crea sola cada 24 h. Sácalos
con `docker cp`:

```bash
docker cp miraru:/data/backups ./mis-backups
```

**Backup SQL manual** (copia coherente del fichero `.db` con `sqlite3.Connection.backup()`,
que captura también lo pendiente del modo WAL — un `cp` directo del fichero podría perder
las escrituras recientes):

```bash
docker exec miraru python -c "
import sqlite3
origen = sqlite3.connect('/data/anime_tracker.db')
copia  = sqlite3.connect('/data/backup_copia.db')
origen.backup(copia); copia.close(); origen.close()
"
docker cp miraru:/data/backup_copia.db ./miraru-$(date +%Y%m%d).db
```

**Restaurar:** dos trampas que hay que cubrir: los ficheros `-wal` / `-shm` del volumen son
restos de la BD **antigua** (hay que borrarlos o SQLite mezclará datos fantasma o dará
error), y conviene que la copia quede propiedad del usuario de la app (uid 1000), no root.
Lo más simple es un contenedor efímero de la misma imagen que deje el volumen a punto
(usa el mismo truco montando tu fichero de backup en solo lectura), con `miraru` parado:

```bash
docker rm -f miraru   # sacar el contenedor del camino (el volumen se conserva)

docker run --rm -v miraru-data:/data \
           -v "$PWD/miraru-20260101.db":/backup.db:ro \
           --user root --entrypoint sh miraru -c '
  rm -f /data/anime_tracker.db-wal /data/anime_tracker.db-shm
  cp /backup.db /data/anime_tracker.db
  chown miraru:miraru /data/anime_tracker.db
'

docker run -d --name miraru -p 127.0.0.1:8765:8765 -v miraru-data:/data miraru
```

> ¿Por qué no `docker stop` + `docker cp` + `docker exec`? Porque `docker exec` **no funciona
> en contenedores parados**: para arreglar el volumen hay que hacerlo desde un contenedor
> temporal (el de arriba), y `docker cp` copia como root (de ahí el `chown` del guion).
> El `docker cp` sí sirve para la dirección contraria (extraer backups de un contenedor
> que corre).

También puedes importar un XML de MyAnimeList / JSON de AniList o CSV desde la propia UI.

## Seguridad

> ⚠️ **Exponer Miraru más allá de tu localhost o tu LAN de casa requiere, como mínimo,
> el PIN de acceso móvil habilitado Y TLS por delante (proxy inverso).** La postura es la
> misma que la del [acceso móvil por WiFi](../README.md#-móvil): úsalo solo en redes de
> confianza.

- **Sin exponer nada:** `docker run` con `-p 127.0.0.1:8765:8765` (publica el puerto solo
  en loopback del anfitrión). Es la opción por defecto recomendada con `-v`.
- **Dentro de tu LAN:** activa primero el PIN — ver [Activar el PIN (volumen
  nuevo)](#activar-el-pin-volumen-nuevo), la misma pantalla **📱 Acceso móvil** de la app
  hace el trabajo; con el modo activado, todas las peticiones `/api/` desde IPs que no
  son loopback exigen token (rate-limit y baneos incluidos). Solo así pasa algo a la red.
- **Internet:** nunca publiques el puerto directamente. Un proxy inverso con TLS
  (Caddy, nginx + certbot, Traefik…), el PIN activado, y restringe el acceso si puedes con
  allowlist o VPN (WireGuard/Tailscale). La app **no cifra el tráfico** por sí misma.
- El healthcheck y el CMD solo hablan con `127.0.0.1` dentro del propio contenedor;
  el CORS ya limita los orígenes de navegador permitidos (localhost/LAN privada y esquemas
  de PWA), pero **de eso no depende la autenticación**: el PIN y el proxy sí.

## Resolución de problemas

- **El contenedor arranca pero `docker ps` lo marca `unhealthy`:** mira los registros con
  `docker logs miraru`; los warnings de la app van por `docker logs` y también al fichero
  `/home/miraru/AnimeTracker/app.log` dentro del contenedor.
- **Puerto ocupado:** usa otro `-p` + `-e PORT=XXXX` como arriba.
- **Permisos al usar carpeta del anfitrión (bind mount):** el contenedor escribe como uid
  1000; `sudo chown -R 1000:1000 ~/miraru-data` (o añade `--user 1000:1000`).
- **Reset completo:** `docker rm -f miraru && docker volume rm miraru-data` (⚠️ borra la
  biblioteca: saca antes un backup).
