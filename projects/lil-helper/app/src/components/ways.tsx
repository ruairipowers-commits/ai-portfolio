// The ways to decide what to eat, as big friendly tiles (Today and the Cook tab).
import { router } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { c, s } from "@/lib/theme";

export const WAYS = [
  { icon: "🗓️", title: "Make a plan", sub: "A week or months ahead, and stick to it", to: "/house/plan-ahead", bg: "#E6F4E1" },
  { icon: "✨", title: "Vibe cooking", sub: "Your time, your mood, ideas now", to: "/house/vibe", bg: "#FFF3D6" },
  { icon: "🧺", title: "What I've got", sub: "Use up what's in the kitchen", to: "/house/cookfrom", bg: "#FDE7E3" },
  { icon: "🎉", title: "Special occasion", sub: "Birthdays, holidays, parties", to: "/house/occasions", bg: "#EDE7FB" },
  { icon: "🥣", title: "Weekly buffet", sub: "Portions on hand, no daily recipe", to: "/house/buffet", bg: "#E3F1FB" },
  { icon: "🎲", title: "Surprise me", sub: "Anything from the book", to: "/house/surprise", bg: "#FFF8EC" },
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
