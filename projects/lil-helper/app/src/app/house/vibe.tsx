// Vibe cooking: how much time you have and what you're in the mood for → a few ideas, what's missing, and a quick
// order for it. Putting one on tonight's plan works like any other change (Undo on the Week tab).
import * as Clipboard from "expo-clipboard";
import * as Linking from "expo-linking";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, DAY_NAME, DAYS, VibeIdea } from "@/lib/api";
import { Button, Chips, ErrorText, Header, money, NumberField, Screen } from "@/components/ui";
import { MicButton } from "@/components/voice";
import { c, s } from "@/lib/theme";

const MOODS = [["quick", "⚡ Quick"], ["comfort", "🧸 Comfort"], ["cozy", "🔥 Cozy"], ["light", "🥗 Light"],
  ["veggie", "🌱 Veggie"], ["fresh", "🍋 Fresh"], ["kid_pleaser", "🧒 Kids love it"], ["adventurous", "🧭 Something new"],
  ["special", "✨ A bit special"], ["party", "🎉 Party"]];

export default function Vibe() {
  const p = useLocalSearchParams<{ minutes?: string; moods?: string }>();
  const today = DAYS[(new Date().getDay() + 6) % 7];
  const [minutes, setMinutes] = useState(Number(p.minutes) || 45);
  const [moods, setMoods] = useState<string[]>(p.moods ? String(p.moods).split(",").filter(Boolean) : []);
  const [meal, setMeal] = useState("dinner");
  const [have, setHave] = useState("");
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.vibe>> | null>(null);
  const [order, setOrder] = useState<Record<string, Awaited<ReturnType<typeof api.vibeOrder>>>>({});
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  async function go() {
    setBusy("go"); setError(null); setDone(null);
    try { setRes(await api.vibe({ minutes, moods, meal, have })); } catch (e) { setError(e); } finally { setBusy(null); }
  }
  useEffect(() => { if (p.minutes || p.moods) go(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  async function getOrder(i: VibeIdea) {
    setBusy(i.recipe);
    try { const o = await api.vibeOrder(i.recipe, i.servings); setOrder({ ...order, [i.recipe]: o }); }
    catch (e) { setError(e); } finally { setBusy(null); }
  }
  async function use(i: VibeIdea) {
    try { await api.useIdea(i.recipe, today, meal); setDone(`${i.name} is on today's ${meal}.`); } catch (e) { setError(e); }
  }
  return (
    <Screen>
      <Header title="Vibe cooking" />
      <View style={s.card}>
        <NumberField label="Minutes you have (start to table)" step={5} min={10} max={240} value={minutes} onChange={setMinutes} />
        <Chips label="In the mood for" options={MOODS.map(([id, label]) => ({ id, label }))} value={moods} onChange={setMoods} />
        <Chips multi={false} options={["dinner", "lunch", "breakfast"]} value={meal} onChange={([m]) => setMeal(m)} />
        <Text style={s.label}>Anything to use up? (optional)</Text>
        <View style={s.row}>
          <TextInput style={[s.input, { flex: 1 }]} value={have} onChangeText={setHave} placeholder="e.g. spinach, feta" />
          <MicButton onText={setHave} />
        </View>
        <Button title="Give me ideas" busy={busy === "go"} onPress={go} />
      </View>
      {done ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>✓ {done}</Text></View> : null}
      {res?.ideas.map((i) => (
        <View key={i.recipe} style={s.card}>
          <Text style={s.h2}>{i.name}</Text>
          <Text style={s.muted}>{i.total} min · {i.active} hands-on{i.kcal ? ` · ~${i.kcal} kcal` : ""} · {i.why.join(" · ")}</Text>
          {i.missing.length ? <Text style={s.body}>Need: {i.missing.map((m) => m.name).join(", ")}
            <Text style={s.muted}> (~{money(i.missing_cost)})</Text></Text> : <Text style={s.body}>You've got everything 🎉</Text>}
          <View style={s.row}>
            <View style={{ flex: 1 }}><Button title={`Make it ${DAY_NAME[today]}`} onPress={() => use(i)} /></View>
            {i.missing.length ? <View style={{ flex: 1 }}><Button kind="ghost" title="Order what's missing"
              busy={busy === i.recipe} onPress={() => getOrder(i)} /></View> : null}
          </View>
          {order[i.recipe]?.orders.map((o, n) => (
            <View key={n} style={{ gap: 4 }}>
              <Text style={s.body}>{o.store} · {o.mode.replace("_", " ")} · {money(o.total)}</Text>
              <Text style={s.muted}>{o.lines.map((l) => `${l.packs} × ${l.name}`).join(", ")}</Text>
              {o.url ? <Button kind="ghost" title="Open the list in the store's app" onPress={() => Linking.openURL(o.url!)} />
                : <Button kind="ghost" title="Copy the list" onPress={() => Clipboard.setStringAsync(o.share_text)} />}
            </View>))}
          {order[i.recipe]?.note ? <Text style={s.muted}>{order[i.recipe].note}</Text> : null}
        </View>
      ))}
      {res && !res.ideas.length ? <Text style={s.muted}>Nothing fits. Try more minutes or fewer moods.</Text> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
