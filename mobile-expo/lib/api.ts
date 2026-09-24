// Cliente de la API de Miraru (servidor de escritorio) por LAN.
// Reutiliza los endpoints /api/mobile/* del backend FastAPI existente.
import * as SecureStore from "expo-secure-store";

export type Anime = {
  nombre: string;
  capitulos?: string | number;
  imagen?: string;
  estado_usuario?: string;
  episodios_vistos?: number;
  puntuacion?: number | null;
  genero?: string;
  estado_anime?: string;
  favorito?: number;
};

const HOST_KEY = "miraru_host";
const TOKEN_KEY = "miraru_token";

export async function getHost(): Promise<string> {
  return (await SecureStore.getItemAsync(HOST_KEY)) || "";
}
async function setHost(h: string) {
  await SecureStore.setItemAsync(HOST_KEY, h.trim());
}
async function getToken(): Promise<string> {
  return (await SecureStore.getItemAsync(TOKEN_KEY)) || "";
}
async function setToken(t: string) {
  await SecureStore.setItemAsync(TOKEN_KEY, t);
}

// Normaliza "192.168.1.40" → "http://192.168.1.40:8765"
function base(host: string): string {
  let h = host.trim();
  if (!/^https?:\/\//.test(h)) h = "http://" + h;
  if (!/:\d+$/.test(h)) h = h + ":8765";
  return h;
}

export async function ping(host: string): Promise<boolean> {
  try {
    const r = await fetch(base(host) + "/api/mobile/ping");
    return r.ok;
  } catch {
    return false;
  }
}

export async function login(host: string, pin: string): Promise<boolean> {
  try {
    const r = await fetch(base(host) + "/api/mobile/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    if (!r.ok) return false;
    const d = await r.json();
    if (!d?.token) return false;
    await setHost(host);
    await setToken(d.token);
    return true;
  } catch {
    return false;
  }
}

async function authed(path: string, init: RequestInit = {}): Promise<Response> {
  const host = await getHost();
  const token = await getToken();
  return fetch(base(host) + path, {
    ...init,
    headers: {
      ...(init.headers || {}),
      "X-Mobile-Token": token,
      "Content-Type": "application/json",
    },
  });
}

export async function fetchAnimes(): Promise<Anime[]> {
  const r = await authed("/api/mobile/animes");
  if (!r.ok) throw new Error("no-auth");
  const d = await r.json();
  return (d.animes || []) as Anime[];
}

export async function fetchStats(): Promise<any> {
  const r = await authed("/api/mobile/stats");
  if (!r.ok) throw new Error("no-auth");
  return r.json();
}

export async function plus1(nombre: string): Promise<void> {
  await authed(`/api/mobile/animes/${encodeURIComponent(nombre)}/plus1`, { method: "POST" });
}

export async function patchAnime(nombre: string, campos: Record<string, unknown>): Promise<void> {
  await authed(`/api/mobile/animes/${encodeURIComponent(nombre)}`, {
    method: "PATCH",
    body: JSON.stringify(campos),
  });
}
