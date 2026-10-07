import { ReactNode } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { c, s } from "@/lib/theme";

export function Screen({ children, refreshing, onRefresh }: { children: ReactNode; refreshing?: boolean;
  onRefresh?: () => void }) {
  return (
    <SafeAreaView style={s.screen} edges={["top"]}>
      <ScrollView contentContainerStyle={s.pad}
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined}>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Button({ title, onPress, disabled, busy, kind = "primary" }: { title: string; onPress: () => void;
  disabled?: boolean; busy?: boolean; kind?: "primary" | "ghost" }) {
  const primary = kind === "primary";
  return (
    <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled || busy}
      style={({ pressed }) => [primary ? s.btn : s.ghost, { opacity: disabled ? 0.45 : pressed ? 0.8 : 1 }]}>
      {busy ? <ActivityIndicator color={primary ? "#fff" : c.ink} />
        : <Text style={primary ? s.btnText : s.ghostText}>{title}</Text>}
    </Pressable>
  );
}

export function Pill({ text, tone = "green" }: { text: string; tone?: "green" | "red" | "amber" }) {
  const bg = tone === "green" ? c.greenSoft : tone === "red" ? c.redSoft : c.amberSoft;
  const fg = tone === "green" ? c.green : tone === "red" ? c.red : c.amber;
  return <View style={[s.pill, { backgroundColor: bg }]}><Text style={{ color: fg, fontSize: 12, fontWeight: "700" }}>{text}</Text></View>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <View style={[s.card, { backgroundColor: c.redSoft, borderColor: c.redSoft }]}>
    <Text style={[s.body, { color: c.red }]}>{error instanceof Error ? error.message : String(error)}</Text>
  </View>;
}

export const money = (n: number | null | undefined) => (n == null ? "—" : `$${n.toFixed(2)}`);
