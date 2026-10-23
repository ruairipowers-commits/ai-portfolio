// Pieces shared by the Dinner Peace Pro (chef) screens: the kraft voice button, hazard banners, the Pro badge.
import { router } from "expo-router";
import { useEffect, useRef } from "react";
import { Animated, Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { c, s, shadow } from "@/lib/theme";

export function ProBadge({ text = "PRO" }: { text?: string }) {
  return (
    <View style={[s.pill, { backgroundColor: c.proSoft, borderWidth: 1, borderColor: "#E5DFD6" }]}>
      <Text style={{ color: c.pro, fontSize: 11, fontWeight: "900", letterSpacing: 0.8 }}>{text}</Text>
    </View>
  );
}

export function Hazard({ text }: { text: string }) {
  return (
    <View style={{ backgroundColor: c.redSoft, borderRadius: 14, paddingVertical: 8, paddingHorizontal: 12,
      flexDirection: "row", gap: 8, alignItems: "center" }} accessibilityRole="alert">
      <Text style={{ fontSize: 16 }}>⚠️</Text>
      <Text style={{ color: "#9B2C24", fontWeight: "800", fontSize: 14, flex: 1 }}>{text}</Text>
    </View>
  );
}

/** The hands-free button: a kraft circle with a slow pulse, floating bottom-right. Opens the voice logger. */
export function VoiceFab({ household }: { household?: string }) {
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 1400, useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0, duration: 0, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] });
  const opacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0] });
  return (
    <View style={{ position: "absolute", right: 20, bottom: 24, width: 64, height: 64 }} pointerEvents="box-none">
      <Animated.View pointerEvents="none" style={{ position: "absolute", width: 64, height: 64, borderRadius: 32,
        backgroundColor: c.pro, opacity, transform: [{ scale }] }} />
      <Pressable accessibilityRole="button" accessibilityLabel="Voice note: say what you cooked, packed or need"
        onPress={() => router.push({ pathname: "/chef/voice", params: household ? { household } : {} } as never)}
        style={({ pressed }) => [{ width: 64, height: 64, borderRadius: 32, backgroundColor: pressed ? "#6F5130" : c.pro,
          alignItems: "center", justifyContent: "center" }, shadow]}>
        <Text style={{ fontSize: 28 }}>🎙️</Text>
      </Pressable>
    </View>
  );
}

export function Stat({ value, label }: { value: string; label: string }) {
  return (
    <View style={{ flex: 1, backgroundColor: c.card, borderRadius: 18, borderWidth: 1, borderColor: c.line, padding: 12 }}>
      <Text style={{ fontSize: 22, fontWeight: "900", color: c.ink }}>{value}</Text>
      <Text style={s.muted}>{label}</Text>
    </View>
  );
}

export const greet = (name: string) => {
  const h = new Date().getHours();
  const first = (name || "").replace(/^chef\s*/i, "").split(" ")[0];
  return `${h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"}, Chef${first ? " " + first : ""}`;
};

export const clock = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${ampm}`;
};
