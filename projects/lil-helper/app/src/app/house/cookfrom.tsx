// Cook from what I've got: type what's in the fridge (or just use the pantry Lil'Helper keeps), get ideas ranked by
// how much they use up, and put one on tonight's plan.
import { useState } from "react";
import { Text, TextInput, View } from "react-native";
import { api, DAY_NAME, DAYS, Idea } from "@/lib/api";
import { Button, Chips, ErrorText, Header, money, NumberField, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function CookFrom() {
  const today = DAYS[(new Date().getDay() + 6) % 7];
  const [text, setText] = useState("");
  const [pantry, setPantry] = useState(true);
  const [meal, setMeal] = useState("dinner");
  const [max, setMax] = useState(45);
  const [day, setDay] = useState<string>(today);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.cookFrom>> | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function go() {
    setBusy(true); setError(null); setDone(null);
    try { setRes(await api.cookFrom({ text, use_pantry: pantry, meal, day, max_minutes: max })); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function use(i: Idea) {
    try { await api.useIdea(i.recipe, day, meal); setDone(`${i.name} is on ${DAY_NAME[day]}'s plan.`); } catch (e) { setError(e); }
  }
  return (
    <Screen>
      <Header title="What I've got" />
      <View style={s.card}>
        <TextInput style={[s.input, { minHeight: 80, textAlignVertical: "top" }]} multiline value={text} onChangeText={setText}
          placeholder="half a chicken, rice, some broccoli, eggs…" />
        <Toggle label="Also use what's in the pantry" value={pantry} onChange={setPantry} />
        <Chips multi={false} options={["dinner", "lunch", "breakfast"]} value={meal} onChange={([m]) => setMeal(m)} />
        <Chips label="For" multi={false} options={DAYS.map((d) => ({ id: d, label: DAY_NAME[d].slice(0, 3) }))} value={day}
          onChange={([d]) => setDay(d)} />
        <NumberField label="Hands-on minutes, at most" step={5} min={5} max={240} value={max} onChange={setMax} />
        <Button title="Find ideas" busy={busy} onPress={go} disabled={!text.trim() && !pantry} />
      </View>
      {res?.not_recognised.length ? <Text style={s.muted}>Didn't recognise: {res.not_recognised.join(", ")}</Text> : null}
      {done ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>✓ {done}</Text></View> : null}
      {res?.ideas.map((i) => (
        <View key={i.recipe} style={s.card}>
          <View style={s.between}><Text style={[s.h2, { flex: 1 }]}>{i.name}</Text>
            <Text style={s.muted}>{Math.round(i.coverage * 100)}% on hand</Text></View>
          <Text style={s.muted}>{i.active} min hands-on · {i.why.join(" · ")}</Text>
          {i.have.length ? <Text style={s.body}>Have: {i.have.join(", ")}</Text> : null}
          {i.missing.length ? <Text style={s.body}>Need: {i.missing.map((m) => m.name).join(", ")}
            <Text style={s.muted}> (~{money(i.missing_cost)})</Text></Text> : null}
          <Button kind="ghost" title={`Make it ${DAY_NAME[day]}`} onPress={() => use(i)} />
        </View>
      ))}
      {res && !res.ideas.length ? <Text style={s.muted}>Nothing fits well. Try adding a few more things, or allow more time.</Text> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
