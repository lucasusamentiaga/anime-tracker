import { useEffect, useState, useCallback } from "react";
import { View, Text, FlatList, Image, RefreshControl, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { fetchAnimes, plus1, type Anime } from "../../lib/api";
import { cacheAnimes, cachedAnimes } from "../../lib/db";

export default function Biblioteca() {
  const [items, setItems] = useState<Anime[]>([]);
  const [offline, setOffline] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

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
            onLongPress={() => plus1(item.nombre).then(load)}
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
    </SafeAreaView>
  );
}
