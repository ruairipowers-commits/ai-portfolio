// The ways to decide what to eat, as big friendly tiles (Today and the Cook tab).
import { router } from "expo-router";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { c, s } from "@/lib/theme";

export const WAYS = [
  { icon: "🗓️", title: "Make a plan", sub: "A week or months ahead, and stick to it", to: "/house/plan-ahead", bg: "#EBF2ED" },
  { icon: "✨", title: "Vibe cooking", sub: "Your time, your mood, ideas now", to: "/house/vibe", bg: "#FFF2D9" },
  { icon: "🧺", title: "What I've got", sub: "Use up what's in the kitchen", to: "/house/cookfrom", bg: "#F6EFE6" },
  { icon: "🎉", title: "Special occasion", sub: "Birthdays, holidays, parties", to: "/house/occasions", bg: "#F4EFE6" },
  { icon: "🥣", title: "Weekly buffet", sub: "Portions on hand, no daily recipe", to: "/house/buffet", bg: "#EEF1F2" },
  { icon: "🎲", title: "Surprise me", sub: "Anything from the book", to: "/house/surprise", bg: "#FAF7F2" },
] as const;

export function WayTiles({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[s.wrap, { gap: 10 }]}>
      {WAYS.map((w) => (
        <Pressable key={w.to} accessibilityRole="button" accessibilityLabel={w.title}
          onPress={() => router.push(w.to as never)}
          style={({ pressed }) => [{ width: "48%", flexGrow: 1, backgroundColor: w.bg, borderRadius: 16, padding: compact ? 10 : 14,
            borderWidth: 1, borderColor: c.line, gap: 2, transform: [{ scale: pressed ? 0.97 : 1 }] }]}>
          <Text style={{ fontSize: compact ? 24 : 30 }}>{w.icon}</Text>
          <Text style={s.h2}>{w.title}</Text>
          {!compact ? <Text style={s.muted}>{w.sub}</Text> : null}
        </Pressable>
      ))}
    </View>
  );
}
