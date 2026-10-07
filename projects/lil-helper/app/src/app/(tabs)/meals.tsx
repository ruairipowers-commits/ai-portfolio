// After meals: one tap for how much was eaten, and a star rating. Portions and restocking learn from this, and the
// ratings are the "satisfaction" in the savings report.
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, DAY_NAME, Entry } from "@/lib/api";
import { useWeek } from "@/lib/useWeek";
import { ErrorText, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const EATEN = [["all", "All gone"], ["some_left", "Some left"], ["lots_left", "Lots left"]] as const;

export default function Meals() {
  const { week, error, setError, loading, reload } = useWeek();
  const [done, setDone] = useState<Record<string, { eaten?: string; rating?: number }>>({});

  async function send(e: Entry, eaten: string, rating: number | null) {
    const key = e.day + e.meal;
    setDone((d) => ({ ...d, [key]: { eaten, rating: rating ?? d[key]?.rating } }));
    try { await api.feedback(e.day, e.meal, eaten, rating); setError(null); } catch (err) { setError(err); }
  }

  const meals = (week?.plan.entries ?? []).filter((e) => e.meal !== "lunch");
  return (
    <Screen refreshing={loading} onRefresh={reload}>
      <Text style={s.h1}>After meals</Text>
      <Text style={s.muted}>How much was eaten? Lil'Helper cooks less of what comes back, and more of what doesn't.</Text>
      {week?.status !== "approved" ? <Text style={s.muted}>Approve the week to start giving feedback.</Text> : null}
      {week?.status === "approved" && meals.map((e) => {
        const key = e.day + e.meal;
        const st = done[key] ?? {};
        return (
          <View key={key} style={s.card}>
            <View style={s.between}>
              <Text style={[s.body, { flex: 1 }]}>{DAY_NAME[e.day]} {e.meal}: {e.name}</Text>
              {st.eaten ? <Pill text="Thanks!" /> : null}
            </View>
            <View style={s.row}>
              {EATEN.map(([k, label]) => (
                <Pressable key={k} onPress={() => send(e, k, st.rating ?? null)}
                  style={[s.ghost, { flex: 1, backgroundColor: st.eaten === k ? c.greenSoft : c.card }]}>
                  <Text style={s.ghostText}>{label}</Text>
                </Pressable>
              ))}
            </View>
            <View style={s.row}>
              {[1, 2, 3, 4, 5].map((n) => (
                <Pressable key={n} onPress={() => send(e, st.eaten ?? "all", n)} accessibilityLabel={`${n} stars`}>
                  <Text style={{ fontSize: 26, opacity: (st.rating ?? 0) >= n ? 1 : 0.25 }}>⭐</Text>
                </Pressable>
              ))}
            </View>
          </View>
        );
      })}
      <ErrorText error={error} />
    </Screen>
  );
}
