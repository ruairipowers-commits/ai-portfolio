// One recipe. Built-in ones are read-only (you can copy one to make it yours); your own you can edit: ingredients in
// your words ("2 cups rice"), steps, the months it's in season, and how often you'd like it.
import * as Linking from "expo-linking";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { api, ApiError, DAY_NAME, RecipeIn } from "@/lib/api";
import { takeDraft } from "@/lib/handoff";
import { Button, Chips, ErrorText, Field, Header, NumberField, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

type Line = { text: string; qty: string; unit: string; hint?: string; id?: string };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const UNITS = ["", "each", "lb", "oz", "cup", "tbsp", "tsp", "g", "kg", "ml", "can", "slice"];
const blank: RecipeIn = { name: "", meal: "dinner", serves: 4, active: 20, total: 30, ingredients: [], instructions: [],
  tags: [], season_months: [], want: {}, kid_min_age: 0, notes: "" };

export default function RecipeScreen() {
  const params = useLocalSearchParams<{ id: string; useFor?: string }>();
  const id = params.id;
  const [useFor, setUseFor] = useState<string | undefined>(params.useFor ? String(params.useFor) : undefined);
  const [note, setNote] = useState<string | null>(null);
  const [r, setR] = useState<RecipeIn>(blank);
  const [lines, setLines] = useState<Line[]>([{ text: "", qty: "1", unit: "" }]);
  const [steps, setSteps] = useState("");
  const [source, setSource] = useState("household");
  const [allergens, setAllergens] = useState<string[]>([]);
  const [warning, setWarning] = useState<string | null>(null);
  const [unknown, setUnknown] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [styles, setStyles] = useState<string[]>([]);
  const editable = id === "new" || source === "household";

  useEffect(() => {
    api.settings().then((v) => setStyles(v.catalogs.styles)).catch(() => {});
    if (id === "new") {
      const got = takeDraft();
      if (got) {
        const d = got.draft;
        if (got.useFor) setUseFor(got.useFor);
        setR({ ...blank, ...d, ingredients: [], want: d.want ?? {}, season_months: d.season_months ?? [] });
        setLines(d.ingredients.map((i) => ({ text: i.text ?? "", qty: String(i.qty), unit: i.unit ?? "",
          hint: i.line && i.line.toLowerCase() !== (i.text ?? "").toLowerCase() ? i.line : undefined })));
        setSteps((d.instructions ?? []).join("\n"));
        setUnknown(d.unknown ?? []);
        setNote([d.note, d.check_amounts?.length ? `Check these amounts: ${d.check_amounts.join("; ")}` : ""]
          .filter(Boolean).join(" ") || null);
      }
      return;
    }
    api.recipe(id).then((x) => {
      const serves = 4;
      setSource(x.source); setAllergens(x.allergens);
      setR({ name: x.name, meal: x.meal, serves, active: x.active, total: x.total, ingredients: [],
        instructions: x.instructions ?? [], tags: x.tags ?? [], season_months: x.season_months ?? [], want: x.want ?? {},
        kid_min_age: x.kid_min_age ?? 0, notes: x.notes ?? "", credit: x.credit ?? "", url: x.url ?? "",
        meals: x.meals ?? [x.meal], kcal: x.kcal ?? 0 });
      setLines(x.ingredients.map((i) => ({ text: i.name, qty: String(Math.round(i.per_serving * serves * 100) / 100), unit: i.unit,
        id: i.ingredient })));
      setSteps((x.instructions ?? []).join("\n"));
    }).catch(setError);
  }, [id]);

  async function save(copy = false) {
    setBusy(true); setError(null); setUnknown([]); setWarning(null);
    const body: RecipeIn = { ...r, name: copy ? `${r.name} (ours)` : r.name,
      ingredients: lines.filter((l) => l.text.trim() && parseFloat(l.qty) > 0)
        .map((l) => ({ text: l.text.trim(), qty: parseFloat(l.qty), unit: l.unit || undefined })),
      instructions: steps.split("\n").map((x) => x.trim()).filter(Boolean) };
    try {
      const out = await api.saveRecipe(body, id !== "new" && !copy ? id : undefined);
      setAllergens(out.allergens); setWarning(out.warning);
      if (useFor && !out.warning) {
        const [day, meal, wk] = useFor.split(":");
        await api.change(day, meal, out.saved, wk || undefined);
        router.replace("/plan" as never);
        return;
      }
      if (id === "new" || copy) router.replace({ pathname: "/house/recipe", params: { id: out.saved } } as never);
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { unknown?: string[] } | undefined) : undefined;
      if (d?.unknown) setUnknown(d.unknown);
      setError(e);
    } finally { setBusy(false); }
  }

  async function addIngredient(name: string, unit: string, cat: string) {
    try { await api.addIngredient({ name, unit, cat, allergens: [] }); setUnknown(unknown.filter((u) => u !== name)); setError(null); }
    catch (e) { setError(e); }
  }

  const setLine = (i: number, l: Partial<Line>) => setLines(lines.map((x, j) => j === i ? { ...x, ...l } : x));
  return (
    <Screen>
      <Header title={id === "new" ? "New recipe" : r.name || "Recipe"} />
      {useFor ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>Saving puts it on
        {" "}{DAY_NAME[useFor.split(":")[0]]}'s {useFor.split(":")[1]} (you can undo that from This week).</Text></View> : null}
      {note ? <View style={[s.card, { backgroundColor: c.amberSoft }]}><Text style={s.body}>{note}</Text></View> : null}
      {allergens.length ? <View style={[s.card, { backgroundColor: c.amberSoft }]}><Text style={s.body}>Contains: {allergens.join(", ")}</Text>
        {warning ? <Text style={s.body}>{warning}</Text> : null}</View> : null}
      <View style={s.card}>
        <Field label="Name" value={r.name} editable={editable} onChangeText={(name) => setR({ ...r, name })} />
        <Chips label="Good for" options={["breakfast", "lunch", "dinner"]} value={r.meals?.length ? r.meals : [r.meal]}
          onChange={(meals) => editable && meals.length && setR({ ...r, meals, meal: meals.includes(r.meal) ? r.meal : meals[0] })} />
        <NumberField label="Makes servings" value={r.serves} min={1} max={40} onChange={(serves) => setR({ ...r, serves })} />
        <NumberField label="Hands-on minutes" step={5} min={1} max={300} value={r.active} onChange={(active) => setR({ ...r, active })} />
        <NumberField label="Total minutes" step={5} min={1} max={1440} value={r.total} onChange={(total) => setR({ ...r, total })} />
        <NumberField label="Calories per serving (0 = don't know)" step={10} min={0} max={5000} value={r.kcal ?? 0}
          onChange={(kcal) => setR({ ...r, kcal })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Ingredients</Text>
        <Text style={s.muted}>Amounts for {r.serves} servings, in everyday words.</Text>
        {lines.map((l, i) => (
          <View key={i} style={[s.row, { flexWrap: "wrap" }]}>
            <TextInput style={[s.input, { width: 64 }]} keyboardType="decimal-pad" value={l.qty} editable={editable}
              onChangeText={(qty) => setLine(i, { qty })} />
            <TextInput style={[s.input, { width: 72 }]} placeholder="unit" autoCapitalize="none" value={l.unit} editable={editable}
              onChangeText={(unit) => setLine(i, { unit })} />
            <TextInput style={[s.input, { flex: 1, minWidth: 140 }]} placeholder="ingredient" value={l.text} editable={editable}
              onChangeText={(text) => setLine(i, { text })} />
            {editable ? <Pressable onPress={() => setLines(lines.filter((_, j) => j !== i))}><Text style={{ color: c.red, fontSize: 18 }}>✕</Text></Pressable> : null}
            {l.hint ? <Text style={[s.muted, { width: "100%" }]}>from: {l.hint}</Text> : null}
            {l.id ? <Pressable onPress={() => router.push({ pathname: "/house/ingredient", params: { id: l.id! } } as never)}>
              <Text style={s.muted}>🏷️</Text></Pressable> : null}
          </View>
        ))}
        {editable ? <Button kind="ghost" title="Add an ingredient" onPress={() => setLines([...lines, { text: "", qty: "1", unit: "" }])} /> : null}
        <Text style={s.muted}>Units: {UNITS.filter(Boolean).join(", ")}</Text>
      </View>
      {unknown.length ? (
        <View style={[s.card, { backgroundColor: c.amberSoft }]}>
          <Text style={s.body}>Lil'Helper doesn't know these yet. Add them as your own ingredients (you can set prices later):</Text>
          {unknown.map((u) => <NewIngredient key={u} name={u} onAdd={addIngredient} />)}
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>Cooking steps</Text>
        <TextInput style={[s.input, { minHeight: 120, textAlignVertical: "top" }]} multiline editable={editable}
          placeholder="One step per line" value={steps} onChangeText={setSteps} />
      </View>
      <View style={s.card}>
        <Chips label="In season (none = all year)" options={MONTHS.map((m, i) => ({ id: String(i + 1), label: m }))}
          value={r.season_months.map(String)} onChange={(v) => editable && setR({ ...r, season_months: v.map(Number).sort((a, b) => a - b) })} />
        <Text style={s.label}>How often would you like it?</Text>
        <Chips multi={false} options={[{ id: "0", label: "Whenever" }, { id: "1", label: "Once a month" },
          { id: "2", label: "Twice a month" }, { id: "4", label: "Every week" }]}
          value={String(r.want?.times ?? 0)} onChange={([t]) => editable && setR({ ...r, want: t === "0" ? {} : { times: Number(t), per_weeks: 4 } })} />
        <Chips label="Style" options={styles} value={r.tags} onChange={(tags) => editable && setR({ ...r, tags })} />
        <NumberField label="Kids can make it from age (0 = not for kid chefs)" max={18} value={r.kid_min_age}
          onChange={(kid_min_age) => setR({ ...r, kid_min_age })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Source</Text>
        {editable ? <>
          <Field label="Where it's from" value={r.credit ?? ""} onChangeText={(credit) => setR({ ...r, credit })}
            placeholder="blank: your name" hint="A person, a cookbook, a website — shown with the recipe." />
          <Field label="Link (optional)" value={r.url ?? ""} onChangeText={(url) => setR({ ...r, url })} autoCapitalize="none"
            placeholder="https://…" />
        </> : <Text style={s.body}>{r.credit || "Lil'Helper"}</Text>}
        {r.url ? <Button kind="ghost" title="Open the original recipe" onPress={() => Linking.openURL(r.url!)} /> : null}
      </View>
      {editable ? <Button title={useFor ? "Save and put it on the plan" : "Save recipe"} busy={busy} onPress={() => save()} disabled={r.name.trim().length < 2} />
        : <Button kind="ghost" title="Copy to my recipes" busy={busy} onPress={() => save(true)} />}
      {editable && id !== "new" ? <Button kind="ghost" title="Remove this recipe" onPress={async () => {
        try { await api.removeRecipe(id); router.back(); } catch (e) { setError(e); } }} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}

function NewIngredient({ name, onAdd }: { name: string; onAdd: (name: string, unit: string, cat: string) => void }) {
  const [unit, setUnit] = useState("each");
  const [cat, setCat] = useState("pantry");
  return (
    <View style={{ gap: 4, paddingVertical: 4 }}>
      <Text style={s.h2}>{name}</Text>
      <Chips multi={false} options={["each", "lb", "oz", "cup", "tbsp", "can", "slice"]} value={unit} onChange={([u]) => setUnit(u)} />
      <Chips multi={false} options={["produce", "meat", "fish", "dairy", "bakery", "deli", "pantry", "frozen"]} value={cat}
        onChange={([x]) => setCat(x)} />
      <Button kind="ghost" title={`Add “${name}”`} onPress={() => onAdd(name, unit, cat)} />
    </View>
  );
}
