// One client household: the dossier (allergies first), the fridge (numbered containers with use-by countdowns),
// reheat cards (4x6 labels, a letter page, or email to the family) and the chef's own setup for the home.
import * as WebBrowser from "expo-web-browser";
import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { api, ApiError, ClientDetail, DAY_SHORT, DAYS, pro, Visit } from "@/lib/api";
import { mode } from "@/lib/mode";
import { Button, Chips, ErrorText, Field, Header, money, NumberField, Pill, Screen, Toggle } from "@/components/ui";
import { clock, Hazard, VoiceFab } from "@/components/chef";
import { c, s } from "@/lib/theme";

const TABS = [{ id: "dossier", label: "Dossier" }, { id: "fridge", label: "Fridge" }, { id: "reheat", label: "Reheat" },
  { id: "setup", label: "Setup" }];
const METHODS = [{ id: "oven", label: "Oven" }, { id: "stovetop", label: "Stovetop" }, { id: "microwave", label: "Microwave" },
  { id: "air_fryer", label: "Air fryer" }];

function Tabs({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <View style={{ flexDirection: "row", backgroundColor: c.parchment, borderRadius: 16, padding: 4, gap: 4 }}>
      {TABS.map((t) => (
        <Pressable key={t.id} onPress={() => onChange(t.id)} accessibilityRole="tab" accessibilityState={{ selected: value === t.id }}
          style={{ flex: 1, paddingVertical: 8, borderRadius: 12, alignItems: "center",
            backgroundColor: value === t.id ? c.card : "transparent" }}>
          <Text style={{ fontWeight: "800", color: value === t.id ? c.pro : c.muted }}>{t.label}</Text>
        </Pressable>))}
    </View>
  );
}

export default function ClientScreen() {
  const { id, tab } = useLocalSearchParams<{ id: string; tab?: string }>();
  const [d, setD] = useState<ClientDetail | null>(null);
  const [t, setT] = useState(tab ?? "dossier");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => { pro.client(id).then((x) => { setD(x); setError(null); }).catch(setError); }, [id]);
  useEffect(() => { load(); }, [load]);
  const run = (fn: () => Promise<unknown>, ok?: string) => async () => {
    setError(null); setMsg(null);
    try { await fn(); if (ok) setMsg(ok); load(); } catch (e) { setError(e); }
  };
  const openFamily = (screen: string) => async () => {
    await api.switchHousehold(id);
    mode.family = true;
    router.push(screen as never);
  };
  if (!d) return <Screen><Header title="Client" /><ErrorText error={error} /></Screen>;
  return (
    <View style={{ flex: 1 }}>
      <Screen onRefresh={load}>
        <Header title={d.name} />
        <Tabs value={t} onChange={setT} />
        {d.dossier.hazards.map((h) => <Hazard key={h.text} text={h.text} />)}
        {t === "dossier" ? <DossierTab d={d} onEdit={openFamily("/house/people")} /> : null}
        {t === "fridge" ? <FridgeTab d={d} run={run} /> : null}
        {t === "reheat" ? <ReheatTab d={d} run={run} onError={setError} /> : null}
        {t === "setup" ? <SetupTab d={d} run={run} onPlan={openFamily("/plan")} onPeople={openFamily("/house/people")} /> : null}
        {msg ? <Pill text={msg} /> : null}
        <ErrorText error={error} />
        <View style={{ height: 80 }} />
      </Screen>
      <VoiceFab household={id} />
    </View>
  );
}

function DossierTab({ d, onEdit }: { d: ClientDetail; onEdit: () => void }) {
  return (
    <>
      <View style={s.card}>
        <Text style={s.h2}>Who you're cooking for</Text>
        {d.dossier.people.map((p) => (
          <View key={p.id} style={{ paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line, gap: 3 }}>
            <View style={s.between}>
              <Text style={[s.body, { fontWeight: "800" }]}>{p.name}{p.kid ? ` · child${p.age ? ` (${p.age})` : ""}` : ""}</Text>
              <View style={s.row}>{p.allergies.map((a) => <Pill key={a} text={a.replace("_", " ")} tone="red" />)}</View>
            </View>
            {p.diet.length ? <Text style={s.muted}>Diet: {p.diet.join(", ")}</Text> : null}
            {p.likes.length ? <Text style={s.muted}>💚 Loves {p.likes.join(", ")}</Text> : null}
            {p.dislikes.length ? <Text style={s.muted}>🙅 Won't eat {p.dislikes.join(", ")}</Text> : null}
          </View>))}
        <Button kind="ghost" title={d.family_joined ? "Their people (the family edits these)" : "Add people and allergies"} onPress={onEdit} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Brands they buy</Text>
        {Object.keys(d.dossier.brands).length ? Object.entries(d.dossier.brands).map(([k, v]) => (
          <Text key={k} style={s.body}>{k}: <Text style={{ fontWeight: "800" }}>{v}</Text></Text>)) :
          <Text style={s.muted}>No brand preferences yet.</Text>}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Your notes</Text>
        <Text style={s.body}>{d.client.notes || "—"}</Text>
        {d.client.access_notes ? <Text style={s.muted}>🔑 {d.client.access_notes}</Text> : null}
        {d.client.emergency ? <Text style={s.muted}>☎️ {d.client.emergency}</Text> : null}
        <Text style={s.muted}>Spent this week: {money(d.spent_this_week)}{d.client.budget != null ? ` of ${money(d.client.budget)}` : ""}</Text>
      </View>
    </>
  );
}

function FridgeTab({ d, run }: { d: ClientDetail; run: (fn: () => Promise<unknown>, ok?: string) => () => void }) {
  const [dish, setDish] = useState("");
  const [portions, setPortions] = useState(2);
  const [loc, setLoc] = useState("fridge");
  return (
    <>
      <View style={s.card}>
        <Text style={s.h2}>In their {d.containers.some((b) => b.location === "freezer") ? "fridge and freezer" : "fridge"}</Text>
        {d.containers.length ? d.containers.map((b) => (
          <View key={b.id} style={[s.between, { paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line }]}>
            <View style={{ flex: 1 }}>
              <Text style={[s.body, { fontWeight: "800" }]}>#{b.number} · {b.dish}</Text>
              <Text style={s.muted}>{b.portions} portions · {b.location} · use by {b.use_by}</Text>
            </View>
            {b.warn ? <Pill text={b.warn} tone={b.days_left < 0 ? "red" : "amber"} /> : <Pill text={`${b.days_left}d`} />}
            <Pressable onPress={run(() => pro.closeContainer(d.household_id, b.id, "eaten"), `#${b.number} marked eaten`)}
              accessibilityLabel={`Mark #${b.number} eaten`} style={{ padding: 6 }}><Text style={{ fontSize: 18 }}>✅</Text></Pressable>
            <Pressable onPress={run(() => pro.closeContainer(d.household_id, b.id, "tossed"), `#${b.number} tossed`)}
              accessibilityLabel={`Toss #${b.number}`} style={{ padding: 6 }}><Text style={{ fontSize: 18 }}>🗑️</Text></Pressable>
          </View>)) : <Text style={s.muted}>No containers logged yet.</Text>}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Pack a container</Text>
        <Field label="Dish" value={dish} onChangeText={setDish} placeholder="Braised short ribs" />
        <NumberField label="Portions" value={portions} onChange={setPortions} min={0.5} max={50} step={1} />
        <Chips options={[{ id: "fridge", label: "🧊 Fridge (4 days)" }, { id: "freezer", label: "❄️ Freezer (60 days)" }]}
          value={loc} multi={false} onChange={(v) => setLoc(v[0])} />
        <Button kind="pro" title="Log it" disabled={!dish.trim()}
          onPress={run(async () => { await pro.addContainer(d.household_id, { dish: dish.trim(), portions, location: loc }); setDish(""); }, "Logged")} />
      </View>
      {d.list.length ? (
        <View style={s.card}>
          <Text style={s.h2}>They're out of</Text>
          <Text style={s.body}>{d.list.map((x) => x.name).join(", ")}</Text>
          <Text style={s.muted}>On your next shopping run for them.</Text>
        </View>) : null}
    </>
  );
}

function ReheatTab({ d, run, onError }: { d: ClientDetail; run: (fn: () => Promise<unknown>, ok?: string) => () => void;
  onError: (e: unknown) => void }) {
  const [meal, setMeal] = useState("");
  const [method, setMethod] = useState("oven");
  const [temp, setTemp] = useState(350);
  const [minutes, setMinutes] = useState(25);
  const [covered, setCovered] = useState(true);
  const [boxes, setBoxes] = useState<string[]>([]);
  const [warn, setWarn] = useState<string | null>(null);
  async function save(confirm = false) {
    try {
      await pro.addCard(d.household_id, { meal: meal.trim(), method, minutes, covered, confirm,
        temp_f: method === "oven" || method === "air_fryer" ? temp : null, containers: boxes.map(Number) });
      setMeal(""); setWarn(null); setBoxes([]);
      run(async () => {}, "Reheat card saved")();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setWarn(e.message); else onError(e);
    }
  }
  const print = (size: "4x6" | "letter") => async () => {
    try { const { url } = await pro.cardLink(d.household_id, size); await WebBrowser.openBrowserAsync(url); }
    catch (e) { onError(e); }
  };
  return (
    <>
      <View style={s.card}>
        <Text style={s.h2}>Cards from the last two weeks</Text>
        {d.cards.length ? d.cards.map((k) => (
          <View key={k.id} style={{ paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line, gap: 2 }}>
            <View style={s.between}>
              <Text style={[s.body, { fontWeight: "800", flex: 1 }]}>{k.meal}</Text>
              <Pill tone="pro" text={k.temp_f ? `${k.temp_f}°F · ${k.minutes} min` : `${k.method} · ${k.minutes} min`} />
            </View>
            <Text style={s.muted}>Made {k.prepared}{k.containers.length ? ` · containers ${k.containers.map((n) => `#${n}`).join(" ")}` : ""}</Text>
            {k.contains.length ? <Pill text={`Contains: ${k.contains.join(", ").replace(/_/g, " ")}`} tone="red" /> : null}
          </View>)) : <Text style={s.muted}>None yet.</Text>}
        {d.cards.length ? (
          <View style={[s.row, { flexWrap: "wrap" }]}>
            <Button kind="ghost" title="🖨️ 4×6 labels" onPress={print("4x6")} />
            <Button kind="ghost" title="📄 Letter page" onPress={print("letter")} />
            <Button kind="ghost" title="✉️ Email the family" onPress={run(() => pro.emailCards(d.household_id), "Emailed")} />
          </View>) : null}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>New reheat card</Text>
        <Field label="Dish" value={meal} onChangeText={setMeal} placeholder="Braised short ribs" />
        <Chips options={METHODS} value={method} multi={false} onChange={(v) => setMethod(v[0])} />
        {method === "oven" || method === "air_fryer" ? <NumberField label="Temperature (°F)" value={temp} onChange={setTemp} step={25} min={150} max={550} /> : null}
        <NumberField label="Minutes" value={minutes} onChange={setMinutes} step={5} min={1} max={240} />
        <Toggle label="Covered" value={covered} onChange={setCovered} />
        {d.containers.length ? <Chips label="Containers" options={d.containers.map((b) => ({ id: String(b.number), label: `#${b.number} ${b.dish}` }))}
          value={boxes} onChange={setBoxes} /> : null}
        {warn ? (
          <View style={{ gap: 8 }}>
            <Hazard text={warn} />
            <Button kind="ghost" title="It's right: save with a Contains warning" onPress={() => save(true)} />
          </View>) : null}
        <Button kind="pro" title="Save card" onPress={() => save(false)} disabled={!meal.trim()} />
      </View>
    </>
  );
}

function SetupTab({ d, run, onPlan, onPeople }: { d: ClientDetail; run: (fn: () => Promise<unknown>, ok?: string) => () => void;
  onPlan: () => void; onPeople: () => void }) {
  const cl = d.client;
  const [visits, setVisits] = useState<Visit[]>(cl.visits);
  const [billing, setBilling] = useState(cl.billing);
  const [card, setCard] = useState(cl.client_card ?? "");
  const [budget, setBudget] = useState(cl.budget ?? 0);
  const [priority, setPriority] = useState(cl.priority);
  const [address, setAddress] = useState(cl.address);
  const [gate, setGate] = useState(cl.gate_code);
  const [access, setAccess] = useState(cl.access_notes);
  const [emergency, setEmergency] = useState(cl.emergency);
  const [notes, setNotes] = useState(cl.notes);
  const setV = (i: number, p: Partial<Visit>) => setVisits(visits.map((v, j) => (j === i ? { ...v, ...p } : v)));
  return (
    <>
      {!d.family_joined ? (
        <View style={[s.card, { backgroundColor: c.proSoft, borderColor: "#E5DFD6" }]}>
          <Text style={s.h2}>The family hasn't joined yet</Text>
          <Text style={s.muted}>{d.invites.length ? `Invitation sent to ${d.invites.map((i) => i.email).join(", ")}.` : "No invitation sent."} Until
            they join, you hold their settings: add their people and allergies, and plan their week.</Text>
          <View style={[s.row, { flexWrap: "wrap" }]}>
            <Button kind="ghost" title="👪 People & allergies" onPress={onPeople} />
            <Button kind="ghost" title="🍎 Their week" onPress={onPlan} />
          </View>
        </View>) : (
        <Button kind="ghost" title="🍎 Open their week (family app)" onPress={onPlan} />)}
      <View style={s.card}>
        <Text style={s.h2}>Visits</Text>
        {visits.map((v, i) => (
          <View key={i} style={{ gap: 6, paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line }}>
            <Chips options={DAYS.map((x) => ({ id: x, label: DAY_SHORT[x] }))} value={v.day} multi={false}
              onChange={(x) => setV(i, { day: x[0], covers: v.covers.includes(x[0]) ? v.covers : [x[0], ...v.covers] })} />
            <View style={s.row}>
              <View style={{ flex: 1 }}><Field label="Arrive" value={v.arrive} onChangeText={(x) => setV(i, { arrive: x })} placeholder="13:30" /></View>
              <View style={{ flex: 1 }}><Field label="Leave" value={v.leave} onChangeText={(x) => setV(i, { leave: x })} placeholder="16:30" /></View>
            </View>
            <Chips label="Cooks for" options={DAYS.map((x) => ({ id: x, label: DAY_SHORT[x] }))} value={v.covers} onChange={(x) => setV(i, { covers: x })} />
            <Pressable onPress={() => setVisits(visits.filter((_, j) => j !== i))}><Text style={{ color: c.red, fontWeight: "700" }}>Remove visit</Text></Pressable>
          </View>))}
        <Button kind="ghost" title="+ Add a visit day" onPress={() => setVisits([...visits, { day: "tue", arrive: "13:30", leave: "16:30", covers: ["tue", "wed"] }])} />
        <Text style={s.muted}>{visits.map((v) => `${DAY_SHORT[v.day]} ${clock(v.arrive || "00:00")}`).join(" · ")}</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Groceries and money</Text>
        <Chips options={[{ id: "chef_card_reimburse", label: "💳 I pay, then invoice" }, { id: "client_card_on_file", label: "🏦 Their card" }]}
          value={billing} multi={false} onChange={(x) => setBilling(x[0])} />
        {billing === "client_card_on_file" ? <Field label="Their card (a name, never the number)" value={card} onChangeText={setCard} placeholder="Davis Amex" /> : null}
        <NumberField label="Weekly grocery budget" value={budget} onChange={setBudget} step={10} prefix="$" max={5000} />
        <NumberField label="Priority (1 = first)" value={priority} onChange={setPriority} step={1} min={1} max={99} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Kitchen access</Text>
        <Field label="Address" value={address} onChangeText={setAddress} />
        <Field label="Gate or door code" value={gate} onChangeText={setGate} />
        <Field label="Access notes" value={access} onChangeText={setAccess} placeholder="Side door; the dog is friendly" />
        <Field label="Emergency contact" value={emergency} onChangeText={setEmergency} />
        <Field label="Kitchen notes" value={notes} onChangeText={setNotes} multiline placeholder="Plates on the second shelf" />
        <Text style={s.muted}>Only you see these. A full-access coverage pack shares them with a backup chef.</Text>
      </View>
      <Button kind="pro" title="Save" onPress={run(() => pro.editClient(d.household_id, { visits, billing, client_card: card || null,
        budget: budget || null, priority, address, gate_code: gate, access_notes: access, emergency, notes }), "Saved")} />
    </>
  );
}
