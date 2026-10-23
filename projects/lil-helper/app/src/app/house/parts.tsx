// One meal, several parts: cook the planned recipe for some people, while others heat up leftovers, have something
// ready-made, or get a second recipe. Anyone on another part comes off the main recipe (and the shopping list).
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, DAY_NAME, Entry, MealPart, RecipeRow, Week } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, NumberField, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const KIND = [["leftovers", "🥡 Leftovers"], ["ready", "🥫 Something ready"], ["cook", "🍳 Another recipe"]];

export default function Parts() {
  const { day, meal, week: wk } = useLocalSearchParams<{ day: string; meal: string; week?: string }>();
  const [w, setW] = useState<Week | null>(null);
  const [e, setE] = useState<Entry | null>(null);
  const [parts, setParts] = useState<MealPart[]>([]);
  const [recipes, setRecipes] = useState<RecipeRow[]>([]);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api.week(wk).then((x) => {
      setW(x);
      const en = x.plan.entries.find((q) => q.day === day && q.meal === meal) ?? null;
      setE(en);
      setParts((en?.parts ?? []).map(({ kind, eaters, recipe, food, servings }) => ({ kind, eaters, recipe, food, servings })));
    }).catch(setError);
    api.recipes({ meal }).then((r) => setRecipes(r.recipes)).catch(() => {});
  }, [day, meal, wk]);

  const everyone = Object.entries(w?.people ?? {}).filter(([pid]) => (w?.home[pid] ?? []).includes(day) && !(w?.away[day] ?? []).includes(pid));
  const taken = new Set(parts.flatMap((p) => p.eaters ?? []));
  const main = everyone.filter(([pid]) => !taken.has(pid));
  const upd = (i: number, p: Partial<MealPart>) => setParts(parts.map((x, j) => j === i ? { ...x, ...p } : x));

  async function save(list = parts) {
    setBusy(true); setError(null);
    try { await api.parts(day, meal, list.filter((p) => p.eaters?.length || p.servings), wk); router.back(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <Screen>
      <Header title={`${DAY_NAME[day] ?? day} ${meal}`} />
      {e ? <View style={[s.card, { backgroundColor: c.greenSoft }]}>
        <Text style={s.label}>Main</Text>
        <Text style={s.h2}>🍲 {e.original?.name && e.kind !== "cook" ? e.name : e.name}</Text>
        <Text style={s.muted}>{main.length ? `For ${main.map(([, n]) => n).join(", ")}` : "Nobody — everyone is on another part"}</Text>
      </View> : null}
      {parts.map((p, i) => (
        <View key={i} style={s.card}>
          <View style={s.between}><Text style={s.h2}>Part {i + 2}</Text>
            <Pressable onPress={() => setParts(parts.filter((_, j) => j !== i))}><Text style={{ color: c.red }}>Remove</Text></Pressable></View>
          <Chips multi={false} value={p.kind} options={KIND.map(([id, label]) => ({ id, label }))}
            onChange={([kind]) => upd(i, { kind: kind as MealPart["kind"], recipe: kind === "cook" ? p.recipe : undefined })} />
          <Chips label="Who" value={p.eaters ?? []} onChange={(eaters) => upd(i, { eaters })}
            options={everyone.filter(([pid]) => !taken.has(pid) || (p.eaters ?? []).includes(pid)).map(([id, label]) => ({ id, label }))} />
          {p.kind === "cook" ? <>
            <Text style={s.body}>{p.recipe ? `✓ ${recipes.find((r) => r.id === p.recipe)?.name ?? p.recipe}` : "Pick a recipe:"}</Text>
            <TextInput style={s.input} placeholder="Search recipes" value={search} onChangeText={setSearch} />
            <View style={s.wrap}>{recipes.filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase())).slice(0, 10)
              .map((r) => <Pressable key={r.id} style={[s.chip, p.recipe === r.id && { borderColor: c.green, backgroundColor: c.greenSoft }]}
                onPress={() => upd(i, { recipe: r.id })}><Text style={s.chipText}>{r.name}</Text></Pressable>)}</View>
            <NumberField label="Servings to cook (0 = just for them)" min={0} max={40} value={p.servings ?? 0}
              onChange={(servings) => upd(i, { servings: servings || undefined })} />
          </> : <Field label={p.kind === "leftovers" ? "Which leftovers (optional)" : "What (optional)"} value={p.food ?? ""}
            onChangeText={(food) => upd(i, { food })} placeholder={p.kind === "leftovers" ? "e.g. Monday's chili" : "e.g. frozen pizza"} />}
        </View>
      ))}
      {parts.length < 5 ? <Button kind="ghost" title="Add a part" onPress={() => setParts([...parts, { kind: "leftovers", eaters: [] }])} /> : null}
      <Button title="Save" busy={busy} onPress={() => save()}
        disabled={parts.some((p) => p.kind === "cook" && !p.recipe)} />
      {e?.parts?.length ? <Button kind="ghost" title="Back to one meal for everyone" onPress={() => save([])} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
