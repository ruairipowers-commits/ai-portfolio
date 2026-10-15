// Weekly buffet: for a meal you don't want a recipe per day (say breakfasts), keep a few things on hand — N portions
// of each — and count what's left once a week before shopping. The plan cooks just enough to get back to N.
import { useCallback, useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { api, BuffetItem, RecipeRow } from "@/lib/api";
import { Button, Chips, ErrorText, Header, NumberField, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

type Cfg = Record<string, { on: boolean; items: { recipe: string; target: number }[] }>;

export default function Buffet() {
  const [cfg, setCfg] = useState<Cfg>({});
  const [items, setItems] = useState<BuffetItem[]>([]);
  const [meal, setMeal] = useState("breakfast");
  const [recipes, setRecipes] = useState<RecipeRow[]>([]);
  const [search, setSearch] = useState("");
  const [edit, setEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => api.buffet().then((r) => { setCfg(r.config); setItems(r.items); }).catch(setError), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.recipes({ meal }).then((r) => setRecipes(r.recipes)).catch(() => {}); }, [meal]);
  const mine = cfg[meal] ?? { on: false, items: [] };
  const setMine = (v: Partial<typeof mine>) => setCfg({ ...cfg, [meal]: { ...mine, ...v } });
  const name = (rid: string) => recipes.find((r) => r.id === rid)?.name ?? items.find((i) => i.recipe === rid)?.name ?? rid;

  async function save() {
    setBusy(true); setError(null);
    try { const r = await api.setBuffet(meal, mine.on, mine.items); setCfg(r.config); setItems(r.items); setEdit(false); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function count(i: BuffetItem, n: number) {
    setItems(items.map((x) => x === i ? { ...x, on_hand: n, cook: Math.max(0, x.target - n) } : x));
    try { const r = await api.buffetCount(i.meal, i.recipe, n); setItems(r.items); } catch (e) { setError(e); }
  }
  const here = items.filter((i) => i.meal === meal);
  return (
    <Screen>
      <Header title="Weekly buffet" />
      <Chips multi={false} options={["breakfast", "lunch", "dinner"]} value={meal} onChange={([m]) => { setMeal(m); setEdit(false); }} />
      {mine.on && !edit ? (
        <View style={s.card}>
          <Text style={s.h2}>What's left?</Text>
          <Text style={s.muted}>Count once a week before shopping. Anyone can update it, by voice too: "we have 3
            portions of overnight oats left".</Text>
          {here.map((i) => (
            <View key={i.recipe} style={{ gap: 2, paddingVertical: 4 }}>
              <View style={s.between}>
                <Text style={[s.body, { flex: 1 }]}>{i.name}</Text>
                <Pressable style={[s.chip, s.step]} onPress={() => count(i, Math.max(0, i.on_hand - 1))}><Text style={s.chipText}>−</Text></Pressable>
                <Text style={[s.h2, { minWidth: 36, textAlign: "center" }]}>{i.on_hand}</Text>
                <Pressable style={[s.chip, s.step]} onPress={() => count(i, i.on_hand + 1)}><Text style={s.chipText}>+</Text></Pressable>
              </View>
              <View style={{ height: 6, backgroundColor: c.line, borderRadius: 3 }}>
                <View style={{ height: 6, width: `${Math.min(100, (i.on_hand / Math.max(1, i.target)) * 100)}%`,
                  backgroundColor: i.on_hand >= i.target ? c.green : c.amber, borderRadius: 3 }} /></View>
              <Text style={s.muted}>{i.cook > 0 ? `This week's plan cooks ${i.cook} to get back to ${i.target}` : `Full (${i.target})`}</Text>
            </View>))}
          <Button kind="ghost" title="Change what's in it" onPress={() => setEdit(true)} />
        </View>
      ) : (
        <View style={s.card}>
          <Toggle label={`Keep ${meal} as a buffet`} value={mine.on} onChange={(on) => setMine({ on })}
            hint={`No ${meal} recipe per day: just keep portions of a few things on hand.`} />
          {mine.items.map((it, n) => (
            <View key={it.recipe} style={{ gap: 4 }}>
              <View style={s.between}><Text style={s.h2}>{name(it.recipe)}</Text>
                <Pressable onPress={() => setMine({ items: mine.items.filter((_, j) => j !== n) })}><Text style={{ color: c.red }}>Remove</Text></Pressable></View>
              <NumberField label="Portions to keep on hand" min={1} max={100} value={it.target}
                onChange={(target) => setMine({ items: mine.items.map((x, j) => j === n ? { ...x, target } : x) })} />
            </View>))}
          <Text style={s.label}>Add</Text>
          <TextInput style={s.input} placeholder="Search recipes" value={search} onChangeText={setSearch} />
          <View style={s.wrap}>
            {recipes.filter((r) => !mine.items.some((i) => i.recipe === r.id) && (!search || r.name.toLowerCase().includes(search.toLowerCase())))
              .slice(0, 12).map((r) => (
                <Pressable key={r.id} style={s.chip} onPress={() => setMine({ items: [...mine.items, { recipe: r.id, target: 6 }] })}>
                  <Text style={s.chipText}>+ {r.name}</Text></Pressable>))}
          </View>
          <Button title="Save" busy={busy} onPress={save} disabled={mine.on && !mine.items.length} />
        </View>
      )}
      <ErrorText error={error} />
    </Screen>
  );
}
