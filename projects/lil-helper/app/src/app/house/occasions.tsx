// Special occasions: birthdays (from people's profiles), anniversaries, holidays and your own (soccer pizza party,
// Valentine's day…). Plan one: choose who it's for and how many guests, get ideas (their favourites first), and the
// plan for that day follows it.
import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { api, Occasion, OccasionIn, Person } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, money, NumberField, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

const KINDS = [["custom", "🎉 Party / other"], ["anniversary", "💕 Anniversary"], ["birthday", "🎂 Birthday"],
  ["holiday", "🎊 Holiday"]];
const TAGS = [["festive", "Festive"], ["party", "Crowd-pleaser"], ["special", "A bit special"], ["grill", "Grill"],
  ["kid_friendly", "Kid-friendly"], ["vegetarian", "Vegetarian"]];
const ICON: Record<string, string> = { birthday: "🎂", holiday: "🎊", anniversary: "💕", custom: "🎉", party: "🎉" };
const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function Occasions() {
  const p = useLocalSearchParams<{ focus?: string; date?: string }>();
  const [data, setData] = useState<Awaited<ReturnType<typeof api.occasions>> | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [role, setRole] = useState<string>("kid");
  const [form, setForm] = useState<OccasionIn | null>(null);
  const [ideas, setIdeas] = useState<Awaited<ReturnType<typeof api.occasionIdeas>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => {
    api.occasions(120).then(setData).catch(setError);
    api.people().then((r) => { setPeople(r.people); setRole(r.role); }).catch(() => {});
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (!p.focus || !data) return;
    const o = data.upcoming.find((x) => x.id === p.focus && (!p.date || x.date === p.date));
    if (o) plan(o);
  }, [p.focus, data]);  // eslint-disable-line react-hooks/exhaustive-deps

  const adult = role !== "kid";
  function plan(o?: Occasion) {
    setMsg(null); setIdeas(null);
    setForm({ name: o?.name ?? "", date: o?.date ?? iso(new Date(Date.now() + 7 * 86400000)), kind: o?.kind === "holiday" ? "holiday"
      : o?.kind ?? "custom", people: o?.people ?? [], guests: o?.guests ?? 0, tags: o?.tags ?? ["festive"], yearly: false,
      meal: o?.meal ?? "dinner", recipe: o?.recipe ?? undefined });
  }
  async function getIdeas(f: OccasionIn) {
    setBusy(true);
    try { setIdeas(await api.occasionIdeas({ people: f.people, tags: f.tags, guests: f.guests, meal: f.meal })); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function save() {
    if (!form) return;
    setBusy(true); setError(null);
    try {
      await api.addOccasion(form);
      setMsg(`${form.name} is planned for ${new Date(`${form.date}T12:00:00`).toDateString()}. If that week is still a draft it's been re-planned around it.`);
      setForm(null); setIdeas(null); load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function holiday(id: string, on: boolean) {
    const off = new Set(data?.holidays.filter((h) => !h.on).map((h) => h.id));
    if (on) off.delete(id); else off.add(id);
    try { await api.patchSetting("holidays_off", [...off]); load(); } catch (e) { setError(e); }
  }
  return (
    <Screen>
      <Header title="Special occasions" />
      {msg ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>✓ {msg}</Text></View> : null}
      {form ? (
        <View style={[s.card, { borderColor: c.green }]}>
          <Text style={s.h2}>Plan an occasion</Text>
          <Field label="What" value={form.name} onChangeText={(name) => setForm({ ...form, name })} placeholder="e.g. Soccer pizza party" />
          <Field label="Date" value={form.date} onChangeText={(date) => setForm({ ...form, date })} placeholder="YYYY-MM-DD"
            autoCapitalize="none" />
          <Chips label="Kind" multi={false} value={form.kind} onChange={([kind]) => setForm({ ...form, kind })}
            options={KINDS.map(([id, label]) => ({ id, label }))} />
          <Chips label="Who's it for" value={form.people} onChange={(ps) => setForm({ ...form, people: ps })}
            options={people.map((x) => ({ id: x.id, label: x.name }))} />
          <NumberField label="Guests (besides the household)" min={0} max={60} value={form.guests}
            onChange={(guests) => setForm({ ...form, guests })} />
          <Chips multi={false} options={["dinner", "lunch", "breakfast"]} value={form.meal} onChange={([meal]) => setForm({ ...form, meal })} />
          <Chips label="Feel" value={form.tags} onChange={(tags) => setForm({ ...form, tags })} options={TAGS.map(([id, label]) => ({ id, label }))} />
          <Toggle label="Every year" value={form.yearly} onChange={(yearly) => setForm({ ...form, yearly })} />
          <Button kind="ghost" title="Show ideas" busy={busy} onPress={() => getIdeas(form)} />
          {ideas?.ideas.map((i) => {
            const on = form.recipe === i.recipe;
            return (
              <Pressable key={i.recipe} onPress={() => setForm({ ...form, recipe: on ? undefined : i.recipe })}
                style={[s.card, on && { borderColor: c.green, backgroundColor: c.greenSoft }]}>
                <Text style={s.h2}>{on ? "✓ " : ""}{i.name}</Text>
                <Text style={s.muted}>{i.why.join(" · ")} · {i.servings} servings · ~{money(i.est_cost)}</Text>
              </Pressable>);
          })}
          {ideas && !ideas.ideas.length ? <Text style={s.muted}>No favourites or matching recipes yet; the plan will pick
            something festive.</Text> : null}
          <View style={s.row}>
            <View style={{ flex: 1 }}><Button kind="ghost" title="Cancel" onPress={() => { setForm(null); setIdeas(null); }} /></View>
            <View style={{ flex: 1 }}><Button title="Plan it" busy={busy} disabled={form.name.trim().length < 2 || !/^\d{4}-\d\d-\d\d$/.test(form.date)}
              onPress={save} /></View>
          </View>
        </View>
      ) : adult ? <Button title="Plan a special meal" onPress={() => plan()} /> : null}

      <View style={s.card}>
        <Text style={s.h2}>Coming up</Text>
        {data?.upcoming.length ? data.upcoming.map((o) => (
          <View key={o.id + o.date} style={[s.between, { paddingVertical: 4 }]}>
            <View style={{ flex: 1 }}>
              <Text style={s.body}>{ICON[o.kind] ?? "🎉"} {o.name}</Text>
              <Text style={s.muted}>{new Date(`${o.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
                {o.guests ? ` · +${o.guests} guests` : ""}{o.kind === "birthday" ? " · no jobs that day" : ""}</Text>
            </View>
            {adult ? <Pressable onPress={() => plan(o)} style={[s.ghost, { paddingVertical: 6 }]}><Text style={s.ghostText}>Plan</Text></Pressable> : null}
          </View>)) : <Text style={s.muted}>Nothing in the next four months. Add birthdays in People.</Text>}
      </View>

      {data?.occasions.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Your occasions</Text>
          {data.occasions.map((o) => (
            <View key={o.id} style={s.between}>
              <Text style={[s.body, { flex: 1 }]}>{ICON[o.kind] ?? "🎉"} {o.name} <Text style={s.muted}>{o.date}{o.yearly ? " · yearly" : ""}</Text></Text>
              {adult ? <Pressable onPress={async () => { try { await api.removeOccasion(o.id); load(); } catch (e) { setError(e); } }}>
                <Text style={{ color: c.red }}>Remove</Text></Pressable> : null}
            </View>))}
        </View>
      ) : null}

      <View style={s.card}>
        <Text style={s.h2}>Holidays</Text>
        <Text style={s.muted}>The ones you celebrate get festive ideas in the plan. {role === "admin" ? "" : "Only the admin can change these."}</Text>
        {data?.holidays.map((h) => <Toggle key={h.id} label={h.name} value={h.on}
          onChange={(on) => role === "admin" && holiday(h.id, on)} />)}
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
