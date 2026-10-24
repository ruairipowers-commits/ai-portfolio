// Change a planned meal: pick one of your recipes or one from the book, write a new one, or find one on the web.
// Nothing changes until you tap "Use this"; Cancel (or Back) leaves the plan as it was, and Undo on This week puts the
// original back later.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, DAY_NAME, Entry, RecipeRow } from "@/lib/api";
import { Button, Chips, ErrorText, Header, LinkRow, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function ChangeMeal() {
  const { day, meal, week: wk } = useLocalSearchParams<{ day: string; meal: string; week?: string }>();
  const [current, setCurrent] = useState<Entry | null>(null);
  const [rows, setRows] = useState<RecipeRow[]>([]);
  const [search, setSearch] = useState("");
  const [which, setWhich] = useState("all");
  const [pick, setPick] = useState<RecipeRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api.week(wk).then((w) => setCurrent(w.plan.entries.find((e) => e.day === day && e.meal === meal) ?? null)).catch(setError);
    api.recipes({ meal: meal === "leftovers" ? "dinner" : meal }).then((r) => setRows(r.recipes)).catch(setError);
  }, [day, meal, wk]);

  const shown = rows.filter((r) => r.id !== current?.recipe
    && (which === "all" || (which === "mine" ? r.source === "household" : r.source !== "household"))
    && (!search || r.name.toLowerCase().includes(search.toLowerCase())));
  const useFor = `${day}:${meal}${wk ? `:${wk}` : ""}`;

  async function use() {
    if (!pick) return;
    setBusy(true); setError(null);
    try { await api.change(day, meal, pick.id, wk); router.back(); } catch (e) { setError(e); } finally { setBusy(false); }
  }

  return (
    <Screen>
      <Header title={`${DAY_NAME[day] ?? day} ${meal}`} />
      {current ? <View style={s.card}>
        <Text style={s.muted}>Planned now</Text>
        <Text style={s.h2}>{current.name}</Text>
        {current.original ? <Text style={s.muted}>Originally {current.original.name}</Text> : null}
      </View> : null}
      {pick ? (
        <View style={[s.card, { borderColor: c.green }]}>
          <Text style={s.body}>Put <Text style={{ fontWeight: "700" }}>{pick.name}</Text> on {DAY_NAME[day]} instead?</Text>
          <Text style={s.muted}>{pick.active} min hands-on{pick.credit ? ` · ${pick.credit}` : ""}. Everything else stays put;
            you can undo it from This week.</Text>
          <View style={s.row}>
            <View style={{ flex: 1 }}><Button title="Use this" busy={busy} onPress={use} /></View>
            <View style={{ flex: 1 }}><Button kind="ghost" title="Cancel" onPress={() => setPick(null)} /></View>
          </View>
        </View>
      ) : null}
      <View style={s.card}>
        <LinkRow icon="✍️" title="Write a new recipe" sub="It's saved to your book and put on this day"
          onPress={() => router.push({ pathname: "/house/recipe", params: { id: "new", useFor } } as never)} />
        <LinkRow icon="🔎" title="Find one on the web" sub="From sites you like, or anywhere"
          onPress={() => router.push({ pathname: "/house/recipe-web", params: { useFor } } as never)} />
      </View>
      <TextInput style={s.input} placeholder="Search your recipes and the book" value={search} onChangeText={setSearch} />
      <Chips multi={false} options={[{ id: "all", label: "All" }, { id: "mine", label: "Ours" }, { id: "book", label: "The book" }]}
        value={which} onChange={([w]) => setWhich(w)} />
      <View style={s.card}>
        {shown.slice(0, 60).map((r) => <LinkRow key={r.id} icon={r.source === "household" ? "⭐" : "📗"} title={r.name}
          sub={`${r.active} min hands-on${r.credit ? ` · ${r.credit}` : ""}`} onPress={() => setPick(r)} />)}
        {!shown.length ? <Text style={s.muted}>Nothing matches. Write a new one, or find one on the web.</Text> : null}
      </View>
      <Button kind="ghost" title="Cancel — keep the plan as it is" onPress={() => router.back()} />
      <ErrorText error={error} />
    </Screen>
  );
}
