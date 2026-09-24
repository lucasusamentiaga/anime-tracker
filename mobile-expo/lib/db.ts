// Caché local offline-first con expo-sqlite. La app funciona sin conexión
// mostrando la última biblioteca sincronizada desde el PC.
import * as SQLite from "expo-sqlite";
import type { Anime } from "./api";

let _db: SQLite.SQLiteDatabase | null = null;

async function db(): Promise<SQLite.SQLiteDatabase> {
  if (_db) return _db;
  _db = await SQLite.openDatabaseAsync("miraru.db");
  await _db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS animes_cache (
      nombre TEXT PRIMARY KEY,
      imagen TEXT,
      capitulos TEXT,
      estado_usuario TEXT,
      episodios_vistos INTEGER,
      puntuacion REAL,
      genero TEXT,
      estado_anime TEXT,
      favorito INTEGER
    );
  `);
  return _db;
}

export async function cacheAnimes(list: Anime[]): Promise<void> {
  const d = await db();
  await d.withTransactionAsync(async () => {
    await d.execAsync("DELETE FROM animes_cache");
    for (const a of list) {
      await d.runAsync(
        `INSERT OR REPLACE INTO animes_cache
         (nombre,imagen,capitulos,estado_usuario,episodios_vistos,puntuacion,genero,estado_anime,favorito)
         VALUES (?,?,?,?,?,?,?,?,?)`,
        [
          a.nombre, a.imagen || "", String(a.capitulos ?? ""),
          a.estado_usuario || "", a.episodios_vistos || 0, a.puntuacion ?? null,
          a.genero || "", a.estado_anime || "", a.favorito || 0,
        ]
      );
    }
  });
}

export async function cachedAnimes(): Promise<Anime[]> {
  const d = await db();
  return await d.getAllAsync<Anime>("SELECT * FROM animes_cache ORDER BY nombre");
}
