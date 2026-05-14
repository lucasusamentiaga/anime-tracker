# Anime Tracker — App Móvil Android

## Cómo funciona

La app de PC ya es un servidor HTTP (FastAPI). La app móvil se conecta a él por la red WiFi local usando la IP de tu PC. **No hay servidor externo, no hay datos en la nube** — todo va directo PC ↔ móvil en tu red.

```
[ Android ] ──WiFi──► [ PC :8765 ] ──► [ SQLite DB ]
                              │
                              └──► [ Google Sheets ] (opcional)
```

## Opción A — APK en 5 minutos con Capacitor (recomendada)

### Requisitos (instalar una vez)
- Node.js 18+ → https://nodejs.org
- Android Studio → https://developer.android.com/studio
- JDK 17 (incluido en Android Studio)

### Pasos

```bash
# 1. Instalar Capacitor CLI
npm install -g @capacitor/cli

# 2. En la carpeta anime-tracker/mobile/
cd anime-tracker/mobile
npm init -y
npm install @capacitor/core @capacitor/android @capacitor/app @capacitor/status-bar

# 3. Inicializar proyecto
npx cap init "Anime Tracker" "com.animetracker.mobile" --web-dir .

# 4. Añadir plataforma Android
npx cap add android

# 5. Copiar la web al proyecto Android
npx cap sync android

# 6. Abrir en Android Studio para compilar el APK
npx cap open android
```

En Android Studio:
- **Build → Build Bundle(s) / APK(s) → Build APK(s)**
- El `.apk` estará en `android/app/build/outputs/apk/debug/app-debug.apk`

### capacitor.config.json (crear en mobile/)
```json
{
  "appId": "com.animetracker.mobile",
  "appName": "Anime Tracker",
  "webDir": ".",
  "server": {
    "androidScheme": "http",
    "cleartext": true
  },
  "android": {
    "allowMixedContent": true,
    "backgroundColor": "#0f0f13"
  }
}
```

### AndroidManifest.xml — permisos necesarios
Añadir en `android/app/src/main/AndroidManifest.xml` dentro de `<manifest>`:
```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE"/>
```

Y dentro de `<application>`:
```xml
android:usesCleartextTraffic="true"
```
(necesario para conectar a HTTP local sin HTTPS)

---

## Opción B — Modo PWA (sin compilar, más simple)

Si no quieres compilar una APK, puedes usar la app directamente en Chrome:

1. En el PC, activa el acceso móvil desde la app (botón 📱)
2. En el móvil, abre Chrome y navega a `http://IP_DEL_PC:8765/app`
3. Chrome → menú ⋮ → **Añadir a pantalla de inicio**

Esto crea un acceso directo que se comporta como una app. La desventaja es que requiere Chrome abierto y la URL exacta.

---

## Uso — conectar el móvil

### En el PC
1. Abre la app → botón **📱** (cabecera)
2. Define un PIN de 4-8 dígitos y pulsa **Activar**
3. **Reinicia** la app de PC (cierra y vuelve a abrir)
4. Verás la IP de tu PC: `192.168.x.x:8765`

### En el móvil
1. Abre Anime Tracker Mobile
2. Introduce la IP del PC y el PIN
3. Pulsa **Conectar**
4. A partir de ahora se reconecta automáticamente

---

## Sincronización PC ↔ Móvil

Cuando modificas algo en el móvil (estado, episodios, notas), el cambio se guarda **inmediatamente** en la BD del PC via la API. Cuando vuelves a la lista en PC, los cambios ya están ahí.

Para ver en el móvil los cambios hechos en PC, pulsa el botón **⟳** (recargar).

**Sincronización en tiempo real (opcional):** La app actual hace polling manual. Para sincronización automática, se puede añadir un `setInterval(() => cargarAnimes(), 30000)` al JS de la APK.

---

## Estructura de archivos

```
anime-tracker/
├── mobile/
│   ├── index.html          ← La app móvil completa (HTML/CSS/JS)
│   ├── capacitor.config.json
│   ├── package.json
│   └── android/            ← Generado por Capacitor
└── ...
```

---

## Seguridad

- El PIN se guarda como **SHA-256** en la BD, nunca en texto claro
- Los tokens de sesión duran **30 días** y se invalidan al cambiar el PIN
- Solo funciona en **red local** (no expuesto a internet)
- Si quieres acceso desde fuera de casa, usa una VPN (WireGuard, Tailscale)
