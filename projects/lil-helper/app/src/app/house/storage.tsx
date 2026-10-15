// Fridge and freezer: how much space there is (so buying ahead and bulk packs only happen when they fit), what's in
// the freezer, and freezer meals.
import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, Storage } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { AdminNote, Button, ErrorText, Field, Header, NumberField, Pill, Saved, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

function Bar({ label, used, cap }: { label: string; used: number; cap: number }) {
  const pct = cap ? Math.min(1, used / cap) : 0;
  return (
    <View style={{ gap: 4 }}>
      <View style={s.between}><Text style={s.body}>{label}</Text><Text style={s.muted}>{Math.round(used)} of {cap} L</Text></View>
      <View style={{ height: 8, backgroundColor: c.line, borderRadius: 4 }}>
        <View style={{ height: 8, width: `${pct * 100}%`, borderRadius: 4, backgroundColor: pct > 0.85 ? c.amber : c.green }} />
      </View>
    </View>
  );
}

export default function StorageScreen() {
  const set = useSettings();
  const { st, isAdmin, role } = set;
  const [cap, setCap] = useState({ fridge_l: 500, freezer_l: 200, fill_target: 0.8 });
  const [fm, setFm] = useState({ cook_extra: false, keep: 2 });
  const [ahead, setAhead] = useState(3);
  const [now, setNow] = useState<Storage | null>(null);
  const [meal, setMeal] = useState({ name: "", portions: 4 });
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { api.storage().then(setNow).catch(setError); }, []);
  useFocusEffect(load);
  useEffect(() => {
    if (!set.view) return;
    setCap({ fill_target: 0.8, ...st.storage }); setFm({ cook_extra: false, keep: 2, ...st.freezer_meals });
    setAhead(st.plan_ahead_weeks ?? 3);
  }, [set.view?.version]);

  async function save() {
    for (const [k, v] of [["storage", cap], ["freezer_meals", fm], ["plan_ahead_weeks", ahead]] as const) {
      if (!(await set.save(k, v))) return;
    }
    load();
  }
  return (
    <Screen>
      <Header title="Fridge and freezer" />
      {now ? (
        <View style={s.card}>
          <Bar label="Fridge" used={now.used.fridge ?? 0} cap={now.capacity.fridge_l} />
          <Bar label="Freezer" used={now.used.freezer ?? 0} cap={now.capacity.freezer_l} />
          <Text style={s.muted}>Estimated from what the plans bought and used.</Text>
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>In the freezer</Text>
        {now?.freezer_meals.length ? now.freezer_meals.map((m) => role !== "kid" ? (
          <FreezerItem key={m.id} m={m} onSaved={load} onError={setError} />
        ) : <Text key={m.id} style={s.body}>🍲 {m.name}<Text style={s.muted}> · {m.portions} portions · use by {m.use_by}</Text></Text>)
          : <Text style={s.muted}>No meals yet.</Text>}
        {now?.freezer_meals.some((m) => m.use_by && m.use_by <= soon()) ? <Text style={s.muted}>Meals near their use-by go into
          next week's plan first.</Text> : null}
        {now?.frozen.map((f) => <Text key={f.ingredient} style={s.body}>❄️ {f.name} <Text style={s.muted}>{f.qty} {f.unit}</Text></Text>)}
        {role !== "kid" ? <>
          <Field label="Add a meal you froze" value={meal.name} onChangeText={(name) => setMeal({ ...meal, name })} placeholder="Chili" />
          <NumberField label="Portions" value={meal.portions} min={1} max={40} onChange={(portions) => setMeal({ ...meal, portions })} />
          <Button kind="ghost" title="Add to the freezer" disabled={meal.name.trim().length < 2} onPress={async () => {
            try { await api.addFreezerMeal(meal.name, meal.portions); setMeal({ name: "", portions: 4 }); load(); } catch (e) { setError(e); }
          }} />
        </> : null}
      </View>
      <AdminNote role={role} />
      <View style={s.card}>
        <Text style={s.h2}>Space</Text>
        <NumberField label="Fridge (litres)" step={25} value={cap.fridge_l} onChange={(fridge_l) => setCap({ ...cap, fridge_l })} />
        <NumberField label="Freezer (litres)" step={25} value={cap.freezer_l} onChange={(freezer_l) => setCap({ ...cap, freezer_l })} />
        <NumberField label="Fill up to (share of space)" step={0.05} min={0.3} max={1} value={cap.fill_target}
          onChange={(fill_target) => setCap({ ...cap, fill_target })} />
        <Toggle label="Cook extra for the freezer" value={fm.cook_extra} onChange={(cook_extra) => setFm({ ...fm, cook_extra })}
          hint="When a dinner freezes well and there's room." />
        <NumberField label="Keep this many freezer meals" value={fm.keep} max={12} onChange={(keep) => setFm({ ...fm, keep })} />
        <NumberField label="Plan this many weeks ahead" value={ahead} min={1} max={6} onChange={setAhead}
          hint="Lets Lil'Helper buy ahead when something you'll need is on sale, and forecast ingredients." />
      </View>
      {isAdmin ? <Button title="Save" busy={set.busy} onPress={save} /> : null}
      <Saved at={set.savedAt} />
      <ErrorText error={set.error ?? error} />
    </Screen>
  );
}

const soon = () => new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);

function FreezerItem({ m, onSaved, onError }: { m: Storage["freezer_meals"][number]; onSaved: () => void;
  onError: (e: unknown) => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: m.name, portions: m.portions, use_by: m.use_by ?? "" });
  const [confirm, setConfirm] = useState(false);
  const due = m.use_by && m.use_by <= soon();
  return (
    <View style={{ gap: 6, paddingVertical: 4 }}>
      <Pressable onPress={() => setOpen(!open)} style={s.between} accessibilityRole="button" accessibilityLabel={`Edit ${m.name}`}>
        <Text style={[s.body, { flex: 1 }]}>🍲 {m.name}<Text style={s.muted}> · {m.portions} portions · use by {m.use_by}</Text></Text>
        {due ? <Pill text="use soon" tone="red" /> : null}
        <Text style={s.muted}>{open ? "Done" : "Edit"}</Text>
      </Pressable>
      {open ? <>
        <Field label="Name" value={f.name} onChangeText={(name) => setF({ ...f, name })} />
        <NumberField label="Portions" step={0.5} max={40} value={f.portions} onChange={(portions) => setF({ ...f, portions })} />
        <Field label="Use by (YYYY-MM-DD)" value={f.use_by} onChangeText={(use_by) => setF({ ...f, use_by })} autoCapitalize="none" />
        <View style={s.row}>
          <View style={{ flex: 1 }}><Button title="Save" disabled={f.name.trim().length < 2 || !/^\d{4}-\d{2}-\d{2}$/.test(f.use_by)}
            onPress={async () => { try { await api.editFreezerMeal(m.id, f); setOpen(false); onSaved(); } catch (e) { onError(e); } }} /></View>
          <View style={{ flex: 1 }}><Button kind="ghost" title={confirm ? "Tap again to remove" : "Remove"}
            onPress={async () => { if (!confirm) { setConfirm(true); return; }
              try { await api.removeFreezerMeal(m.id); onSaved(); } catch (e) { onError(e); } }} /></View>
        </View>
      </> : null}
    </View>
  );
}
