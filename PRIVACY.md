# Política de privacidad de Miraru / Miraru privacy policy

*Última actualización / Last updated: 1 de noviembre de 2026*

## Español

Miraru es una aplicación de escritorio que funciona en tu propio ordenador. **No tiene
cuentas, ni servidores propios, ni publicidad, ni telemetría.** El autor no recibe
ningún dato tuyo.

**Qué se guarda y dónde.** Tu lista (animes, películas y series, episodios vistos, notas,
puntuaciones) y tu configuración se guardan en tu ordenador, en la base de datos
`anime_tracker.db` de la carpeta de Miraru. Si desinstalas Miraru, se borran (salvo la
copia en la nube, ver abajo, que está en tu propia nube).

**Con quién se conecta Miraru.** Para funcionar, Miraru consulta servicios públicos de
información y envía solo lo necesario para la búsqueda (por ejemplo, el título o el
identificador de un anime), nunca tu lista completa ni datos personales:

- AniList, Jikan (MyAnimeList), Kitsu, AnimeFLV, AnimeAV1, Anime-Planet, Crunchyroll,
  AnimeThemes y TMDB (películas y series): datos de series, portadas, episodios,
  recomendaciones.
- GitHub y Microsoft Store: comprobar si hay una versión nueva de Miraru.

Miraru oculta en las búsquedas el contenido que esas fuentes marcan como solo para
adultos.

**Funciones opcionales que solo se activan si tú las configuras o las aceptas:**

- *Copia en la nube*: si en tu ordenador hay una carpeta de OneDrive, Google Drive,
  Dropbox o iCloud Drive, Miraru guarda en ella (en la carpeta `Miraru`) una copia de tu
  lista para que puedas recuperarla si formateas o cambias de ordenador. Con OneDrive se
  activa sola; puedes elegir otra carpeta o apagarla en ☁ Copia en la nube. La copia
  **no incluye** contraseñas, sesiones ni claves (token de AniList, cookie de AnimeAV1,
  contraseña del correo, PIN del móvil). Esa carpeta la sincroniza tu proveedor de nube
  con tu cuenta; Miraru no envía nada a ningún otro sitio.
- *Sincronizar con AniList*: envía tu lista a tu cuenta de AniList.
- *AnimeAV1*: importar o subir tu lista usando la sesión que copias de tu navegador; se
  guarda solo en tu ordenador y solo se envía a animeav1.com.
- *Extensión del navegador «Miraru × AnimeAV1»*: si la instalas, detecta cuándo pulsas
  «Marcar como visto» en animeav1.com y se lo comunica a Miraru en tu propio ordenador
  (127.0.0.1). No lee tu historial ni otras páginas, y no envía nada a terceros.
- *Google Sheets*: copia tu lista a una hoja de cálculo de tu cuenta de Google.
- *Avisos por correo*: envía correos con el servidor de correo que tú configures.
- *Notificaciones del navegador*: usan el servicio de notificaciones de tu navegador.
- *Discord*: muestra en tu perfil de Discord lo que estás viendo.
- *Acceso desde el móvil*: abre Miraru a otros dispositivos de tu red local, protegido
  con un PIN.

Cada uno de estos servicios tiene su propia política de privacidad.

**Tus derechos.** Todos tus datos están en tu ordenador (y, si la activas, en tu nube):
puedes exportarlos (CSV, JSON), borrarlos o desinstalar Miraru cuando quieras.

**Menores.** Miraru no recoge datos de nadie, tampoco de menores.

**Cambios.** Si esta política cambia, se actualizará la fecha de arriba y se indicará en
las notas de la versión.

**Contacto.** Abre un aviso en https://github.com/lucasusamentiaga/anime-tracker/issues

Ver también los [términos de uso](TERMS.md).

## English

Miraru is a desktop app that runs on your own computer. **It has no accounts, no servers
of its own, no ads and no telemetry.** The author receives no data about you.

**What is stored and where.** Your list (anime, movies and series, watched episodes,
notes, scores) and your settings are stored on your computer, in the `anime_tracker.db`
database inside the Miraru folder. Uninstalling Miraru deletes them (except the cloud
backup, see below, which lives in your own cloud).

**What Miraru connects to.** To work, Miraru queries public information services and
sends only what a search needs (for example an anime title or ID), never your full list or
personal data:

- AniList, Jikan (MyAnimeList), Kitsu, AnimeFLV, AnimeAV1, Anime-Planet, Crunchyroll,
  AnimeThemes and TMDB (movies and series): series data, covers, episodes,
  recommendations.
- GitHub and Microsoft Store: checking for a new version of Miraru.

Miraru hides from searches any content those sources flag as adults-only.

**Optional features, only active if you set them up or accept them:**

- *Cloud backup*: if your computer has a OneDrive, Google Drive, Dropbox or iCloud Drive
  folder, Miraru keeps a copy of your list in it (in a `Miraru` folder) so you can restore
  it after formatting or changing computers. With OneDrive it turns on by itself; you can
  pick another folder or turn it off under ☁ Cloud backup. The backup **does not
  include** passwords, sessions or keys (AniList token, AnimeAV1 cookie, email password,
  phone PIN). That folder is synced by your cloud provider with your account; Miraru sends
  nothing anywhere else.
- *AniList sync*: sends your list to your AniList account.
- *AnimeAV1*: import or upload your list using the session you copy from your browser;
  it is stored only on your computer and only sent to animeav1.com.
- *"Miraru × AnimeAV1" browser extension*: if you install it, it detects when you press
  "Marcar como visto" (mark as watched) on animeav1.com and tells Miraru on your own
  computer (127.0.0.1). It does not read your history or other pages and sends nothing to
  third parties.
- *Google Sheets*: copies your list to a spreadsheet in your Google account.
- *Email alerts*: sent through the mail server you configure.
- *Browser notifications*: your browser's push service.
- *Discord*: shows what you are watching on your Discord profile.
- *Mobile access*: opens Miraru to devices on your local network, protected by a PIN.

Each of these services has its own privacy policy.

**Your rights.** All your data is on your computer (and, if enabled, in your cloud): you
can export it (CSV, JSON), delete it or uninstall Miraru at any time.

**Children.** Miraru collects no data from anyone, including children.

**Changes.** If this policy changes, the date above will be updated and the change noted in
the release notes.

**Contact.** Open an issue at https://github.com/lucasusamentiaga/anime-tracker/issues

See also the [terms of use](TERMS.md).
