import { useEffect, useState, useCallback, useRef } from "react";
import { View, Text, FlatList, Image, RefreshControl, Pressable, Modal, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { fetchAnimes, plus1, patchAnime, type Anime, type CamposAnime } from "../../lib/api";
import { cacheAnimes, cachedAnimes } from "../../lib/db";

// Mismos estados válidos que el servidor (ESTADOS_VALIDOS en main.py)
const ESTADOS = ["pendiente", "viendo", "completado", "pausa", "abandonado"] as const;

export default function Biblioteca() {
  const [items, setItems] = useState<Anime[]>([]);
  const [offline, setOffline] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Anime abierto en la hoja de acciones (sigue el nombre, no el snapshot,
  // para que la ficha reaccione a los cambios optimistas de la lista).
  const [abierto, setAbierto] = useState<string | null>(null);
  // Mutex de escritura: no pisar cambios optimistas concurrentes.
  const escribiendo = useRef(false);

  const load = useCallback(async () => {
    try {
      const list = await fetchAnimes();
      setItems(list);
      setOffline(false);
      cacheAnimes(list).catch(() => {});
    } catch {
      // Sin conexión / sin token → mostrar la última caché local
      setItems(await cachedAnimes());
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Nunca silencioso: 401/token caducado → pista de Ajustes; fallo de red → WiFi.
  function alertaEscritura(e: unknown) {
    const msg = e instanceof Error ? e.message : "";
    if (msg === "no-auth") {
      Alert.alert(
        "Sesión caducada",
        "El token expiró o el modo móvil se desactivó en el PC. Ve a la pestaña Ajustes y reconecta con tu PIN."
      );
    } else if (msg === "net") {
      Alert.alert("Sin conexión", "No se pudo hablar con el PC. Comprueba que estás en el mismo WiFi y reintenta.");
    } else {
      Alert.alert("Error", "El PC rechazó el cambio" + (msg ? " (" + msg + ")" : "") + ".");
    }
  }

  async function aplicarCampos(anime: Anime, cambios: CamposAnime, revertir: Partial<Anime>) {
    if (escribiendo.current) return;
    escribiendo.current = true;
    const nombre = anime.nombre;
    setItems((its) => its.map((a) => (a.nombre === nombre ? { ...a, ...cambios } : a)));
    try {
      await patchAnime(nombre, cambios);
    } catch (e) {
      setItems((its) => its.map((a) => (a.nombre === nombre ? { ...a, ...revertir } : a)));
      alertaEscritura(e);
    } finally {
      escribiendo.current = false;
    }
  }

  async function aplicarPlus1(anime: Anime) {
    if (escribiendo.current) return;
    escribiendo.current = true;
    const nombre = anime.nombre;
    setItems((its) =>
      its.map((a) => (a.nombre === nombre ? { ...a, episodios_vistos: (a.episodios_vistos ?? 0) + 1 } : a))
    );
    try {
      const r = await plus1(nombre);
      const nuevos = r?.episodios_vistos;
      if (typeof nuevos === "number") {
        setItems((its) => its.map((a) => (a.nombre === nombre ? { ...a, episodios_vistos: nuevos } : a)));
      }
    } catch (e) {
      setItems((its) =>
        its.map((a) => (a.nombre === nombre ? { ...a, episodios_vistos: anime.episodios_vistos } : a))
      );
      alertaEscritura(e);
    } finally {
      escribiendo.current = false;
    }
  }

  const abiertoAnime = items.find((a) => a.nombre === abierto) ?? null;
  const puntuacion = abiertoAnime?.puntuacion ?? 0;

  return (
    <SafeAreaView className="flex-1 bg-bg">
      <View className="px-4 pt-2 pb-3 flex-row items-center justify-between">
        <Text className="text-fg text-2xl font-bold">Miraru</Text>
        {offline && <Text className="text-muted text-xs">sin conexión</Text>}
      </View>
      <FlatList
        data={items}
        keyExtractor={(a) => a.nombre}
        numColumns={3}
        contentContainerStyle={{ padding: 8 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            tintColor="#c4b1ff"
            onRefresh={async () => {
              setRefreshing(true);
              await load();
              setRefreshing(false);
            }}
          />
        }
        renderItem={({ item }) => (
          <Pressable
            className="flex-1 m-1 rounded-xl overflow-hidden bg-card border border-border"
            onPress={() => setAbierto(item.nombre)}
            onLongPress={() => aplicarPlus1(item)}
          >
            {item.imagen ? (
              <Image source={{ uri: item.imagen }} className="w-full aspect-[3/4]" />
            ) : (
              <View className="w-full aspect-[3/4] bg-card2" />
            )}
            <Text numberOfLines={2} className="text-fg text-[11px] px-1.5 py-1">
              {item.nombre}
            </Text>
          </Pressable>
        )}
        ListEmptyComponent={
          <Text className="text-muted text-center mt-20 px-6">
            Sin datos. Ve a Ajustes y conecta con tu PC (mismo WiFi).
          </Text>
        }
      />

      <Modal visible={abiertoAnime !== null} transparent animationType="slide" onRequestClose={() => setAbierto(null)}>
        <Pressable className="flex-1 bg-black/60 justify-end" onPress={() => setAbierto(null)}>
          <Pressable className="bg-card border-t border-border rounded-t-3xl px-5 pt-5 pb-8">
            <Text numberOfLines={2} className="text-fg text-lg font-bold pr-6">
              {abiertoAnime?.nombre ?? ""}
            </Text>
            <Text className="text-muted text-xs mt-1">
              {(abiertoAnime?.episodios_vistos ?? 0)} / {abiertoAnime?.capitulos ?? "?"} capítulos
            </Text>

            <Pressable
              className="bg-accent rounded-xl py-3 mt-4 items-center active:opacity-80"
              onPress={() => abiertoAnime && aplicarPlus1(abiertoAnime)}
            >
              <Text className="text-white font-bold">+1 episodio</Text>
            </Pressable>

            <Text className="text-muted text-xs uppercase mt-5 mb-2">Estado</Text>
            <View className="flex-row flex-wrap">
              {ESTADOS.map((est) => {
                const activo = abiertoAnime?.estado_usuario === est;
                return (
                  <Pressable
                    key={est}
                    className={
                      "mr-2 mb-2 rounded-full px-3 py-2 border " +
                      (activo ? "bg-accent border-accent" : "bg-card2 border-border")
                    }
                    onPress={() =>
                      abiertoAnime &&
                      abiertoAnime.estado_usuario !== est &&
                      aplicarCampos(abiertoAnime, { estado_usuario: est }, { estado_usuario: abiertoAnime.estado_usuario })
                    }
                  >
                    <Text className={(activo ? "text-white" : "text-fg") + " text-xs"}>{est}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text className="text-muted text-xs uppercase mt-3 mb-2">Puntuación</Text>
            <View className="flex-row items-center">
              <Pressable
                className="bg-card2 border border-border rounded-lg w-10 h-10 items-center justify-center"
                disabled={puntuacion <= 0}
                onPress={() =>
                  abiertoAnime &&
                  aplicarCampos(
                    abiertoAnime,
                    { puntuacion: Math.max(0, puntuacion - 1) },
                    { puntuacion: abiertoAnime.puntuacion }
                  )
                }
              >
                <Text className={puntuacion <= 0 ? "text-muted" : "text-fg"}>−</Text>
              </Pressable>
              <Text className="text-fg text-lg font-bold w-14 text-center">
                {abiertoAnime?.puntuacion ?? "—"}
              </Text>
              <Pressable
                className="bg-card2 border border-border rounded-lg w-10 h-10 items-center justify-center"
                disabled={puntuacion >= 10}
                onPress={() =>
                  abiertoAnime &&
                  aplicarCampos(
                    abiertoAnime,
                    { puntuacion: Math.min(10, puntuacion + 1) },
                    { puntuacion: abiertoAnime.puntuacion }
                  )
                }
              >
                <Text className={puntuacion >= 10 ? "text-muted" : "text-fg"}>+</Text>
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}
