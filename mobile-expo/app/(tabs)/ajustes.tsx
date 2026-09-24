import { useState, useEffect } from "react";
import { View, Text, TextInput, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { getHost, login, ping } from "../../lib/api";

export default function Ajustes() {
  const [host, setHostInput] = useState("");
  const [pin, setPin] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    getHost().then(setHostInput);
  }, []);

  async function conectar() {
    setStatus("Conectando…");
    if (!(await ping(host))) {
      setStatus("No se encuentra el PC. ¿Mismo WiFi y modo móvil activado?");
      return;
    }
    const ok = await login(host, pin);
    setStatus(ok ? "✓ Conectado" : "PIN incorrecto o no configurado");
  }

  return (
    <SafeAreaView className="flex-1 bg-bg px-5">
      <Text className="text-fg text-2xl font-bold mt-2 mb-6">Ajustes</Text>

      <Text className="text-muted mb-1 text-xs uppercase">IP del PC</Text>
      <TextInput
        value={host}
        onChangeText={setHostInput}
        autoCapitalize="none"
        keyboardType="url"
        placeholder="192.168.1.40:8765"
        placeholderTextColor="#6b6b88"
        className="bg-card2 border border-border rounded-xl text-fg px-4 py-3 mb-4"
      />

      <Text className="text-muted mb-1 text-xs uppercase">PIN</Text>
      <TextInput
        value={pin}
        onChangeText={setPin}
        keyboardType="number-pad"
        secureTextEntry
        placeholder="4-8 dígitos"
        placeholderTextColor="#6b6b88"
        className="bg-card2 border border-border rounded-xl text-fg px-4 py-3 mb-5"
      />

      <Pressable onPress={conectar} className="bg-accent rounded-xl py-3 items-center active:opacity-80">
        <Text className="text-white font-bold">Conectar</Text>
      </Pressable>

      {!!status && <Text className="text-light text-center mt-4">{status}</Text>}

      <Text className="text-muted text-xs mt-8 leading-5">
        En el PC: abre Miraru → 📱 Móvil → pon un PIN → Activar, y reinicia la app.
        Móvil y PC deben estar en la misma red WiFi.
      </Text>
    </SafeAreaView>
  );
}
