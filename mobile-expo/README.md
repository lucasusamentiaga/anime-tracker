# Miraru — app móvil (Expo / React Native)

Scaffold de la app móvil de Miraru. Es **offline-first** (caché local con
expo-sqlite) y se conecta a tu **Miraru de escritorio por la red WiFi**,
reutilizando los endpoints `/api/mobile/*` del backend (no hace falta un
servidor en la nube).

## Stack
Expo (SDK 53) · React Native 0.79 (Nueva Arquitectura) · React 19 · TypeScript ·
expo-router (navegación por archivos) · NativeWind v4 (Tailwind) ·
react-native-reanimated · expo-sqlite (offline) · expo-secure-store (PIN/token) ·
@expo/vector-icons.

## Estructura
```
mobile-expo/
├─ app/
│  ├─ _layout.tsx            # raíz (providers, tema oscuro)
│  └─ (tabs)/
│     ├─ _layout.tsx         # navegación por pestañas
│     ├─ index.tsx           # Biblioteca (grid, pull-to-refresh, +1 ep al mantener)
│     ├─ stats.tsx           # Estadísticas
│     └─ ajustes.tsx         # Conexión con el PC (IP + PIN)
├─ lib/
│  ├─ api.ts                 # cliente de /api/mobile/* (login con PIN → token)
│  └─ db.ts                  # caché offline (expo-sqlite)
├─ assets/                   # icon.png, splash.png (reusa el logo de Miraru)
├─ app.json · eas.json · tailwind.config.js · babel.config.js · metro.config.js
└─ tsconfig.json · global.css
```

## Puesta en marcha
```bash
cd mobile-expo
npm install
npx expo start          # abre en Expo Go (escanea el QR) o emulador
npm run typecheck       # tsc --noEmit
```

## Generar el APK (sin cadena de build local)
```bash
npm i -g eas-cli
eas login
eas build -p android --profile preview     # APK descargable desde expo.dev
```

## Cómo se conecta con tu PC
1. En **Miraru de escritorio**: 📱 Móvil → pon un PIN → Activar → reinicia la app.
2. En el **móvil** (misma WiFi): pestaña **Ajustes** → IP del PC (p. ej.
   `192.168.1.40`) + PIN → **Conectar**.
3. La app guarda un token seguro (expo-secure-store) y cachea tu biblioteca para
   funcionar también **sin conexión**.

## Pendiente / ideas (siguiente iteración)
- Buscar y añadir títulos desde el móvil (endpoints `/api/buscar` + `/api/animes`).
- Logros/emblemas y Wrapped nativos (ya existen en el backend: `/api/achievements`, `/api/stats/global`).
- Notificaciones de nuevos episodios (expo-notifications).
- Sincronización bidireccional con cola de cambios offline.
