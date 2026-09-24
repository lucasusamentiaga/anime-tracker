import { useEffect, useState } from "react";
import { View, Text, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { fetchStats } from "../../lib/api";

function Metric({ v, l }: { v: any; l: string }) {
  return (
    <View className="bg-card border border-border rounded-2xl px-5 py-4 m-1 min-w-[100px] items-center">
      <Text className="text-fg text-2xl font-bold">{v ?? "—"}</Text>
      <Text className="text-muted text-[11px] uppercase mt-1">{l}</Text>
    </View>
  );
}

export default function Stats() {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    fetchStats().then(setS).catch(() => setErr(true));
  }, []);

  return (
    <SafeAreaView className="flex-1 bg-bg px-4">
      <Text className="text-fg text-2xl font-bold mt-2 mb-4">Estadísticas</Text>
      {err && <Text className="text-muted">Conecta con tu PC en Ajustes.</Text>}
      {s && (
        <ScrollView contentContainerClassName="flex-row flex-wrap">
          <Metric v={s.total} l="títulos" />
          <Metric v={s.total_episodes} l="episodios" />
          <Metric v={s.avg_score} l="nota media" />
        </ScrollView>
      )}
    </SafeAreaView>
  );
}
