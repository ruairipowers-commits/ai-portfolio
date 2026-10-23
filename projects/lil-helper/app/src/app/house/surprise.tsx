// Surprise me: anything from the recipe book that's safe for the people eating, at random. Spin again if you like.
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { api, DAY_NAME, DAYS } from "@/lib/api";
import { Button, Chips, ErrorText, Header, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function Surprise() {
  const today = DAYS[(new Date().getDay() + 6) % 7];
  const [meal, setMeal] = useState("dinner");
  const [r, setR] = useState<Awaited<ReturnType<typeof api.surprise>> | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function spin(m = meal) {
    setBusy(true); setError(null); setDone(false);
    try { setR(await api.surprise(m, today)); } catch (e) { setError(e); setR(null); } finally { setBusy(false); }
  }
  useEffect(() => { spin(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Screen>
      <Header title="Surprise me" />
      <Chips multi={false} options={["dinner", "lunch", "breakfast"]} value={meal} onChange={([m]) => { setMeal(m); spin(m); }} />
      {r ? (
        <View style={[s.card, { alignItems: "center", padding: 22, backgroundColor: c.card, borderColor: c.amber }]}>
          <Text style={{ fontSize: 44 }}>🎲</Text>
          <Text style={[s.h1, { textAlign: "center" }]}>{r.name}</Text>
          <Text style={s.muted}>{r.total} min · {r.active} hands-on{r.kcal ? ` · ~${r.kcal} kcal` : ""}{r.credit ? ` · ${r.credit}` : ""}</Text>
          <Text style={s.muted}>one of {r.pool} that suit everyone</Text>
        </View>
      ) : null}
      {r?.steps.length ? <View style={s.card}>{r.steps.map((t, i) => <Text key={i} style={s.body}>{i + 1}. {t}</Text>)}</View> : null}
      {done ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>✓ On {DAY_NAME[today]}'s {meal}.
        Undo it from the Week tab.</Text></View> : null}
      <View style={s.row}>
        <View style={{ flex: 1 }}><Button kind="ghost" title="Spin again" busy={busy} onPress={() => spin()} /></View>
        <View style={{ flex: 1 }}><Button title="Let's make it" disabled={!r || done} onPress={async () => {
          try { await api.useIdea(r!.recipe, today, meal); setDone(true); } catch (e) { setError(e); } }} /></View>
      </View>
      {r ? <Button kind="ghost" title="See the recipe" onPress={() => router.push({ pathname: "/house/recipe", params: { id: r.recipe } } as never)} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
