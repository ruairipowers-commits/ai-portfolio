// The welcome wizard: a new household in a few minutes. Each step saves as you go (so you can stop and come back),
// and every step after the first can be skipped and changed later under Home → Settings.
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api, DAY_SHORT, DAYS, Me, Person, PersonIn } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { LoopCard, TripsEditor } from "@/components/house";
import { Button, Chips, ErrorText, Field, NumberField, Pill, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

const STEPS = ["Welcome", "Your household", "Who's in it", "Dinners", "Nights off", "Stores and money", "Kitchen",
  "Shopping trips", "Stay in the loop", "First plan"] as const;

const deviceZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York"; }
  catch { return "America/New_York"; } };

export default function Welcome() {
  const [step, setStep] = useState(0);
  const [me, setMe] = useState<Me | null>(null);
  const [signup, setSignup] = useState("invite");
  useEffect(() => {
    api.me().then((m) => { setMe(m); setSignup(m.signup); if (m.current) setStep(2); }).catch(() => {});
  }, []);
  const next = () => setStep((n) => Math.min(n + 1, STEPS.length - 1));
  const back = () => setStep((n) => Math.max(n - (n === 2 && me?.current ? 0 : 1), 0));

  return (
    <Screen>
      <View style={s.between}>
        <Text style={s.h1}>{STEPS[step]}</Text>
        <Text style={s.muted}>{step + 1} of {STEPS.length}</Text>
      </View>
      <View style={{ height: 6, backgroundColor: c.line, borderRadius: 3 }}>
        <View style={{ height: 6, width: `${((step + 1) / STEPS.length) * 100}%`, backgroundColor: c.green, borderRadius: 3 }} />
      </View>
      {step === 0 ? <Intro me={me} signup={signup} onNext={next} /> : null}
      {step === 1 ? <CreateHousehold me={me} signup={signup} onDone={() => api.me().then(setMe).then(next)} /> : null}
      {step >= 2 ? <SettingsSteps step={step} next={next} /> : null}
      {step > 0 && step < STEPS.length - 1 ? (
        <View style={s.row}>
          <View style={{ flex: 1 }}><Button kind="ghost" title="Back" onPress={back} /></View>
          {step >= 3 ? <View style={{ flex: 1 }}><Button kind="ghost" title="Skip for now" onPress={next} /></View> : null}
        </View>
      ) : null}
    </Screen>
  );
}

function Intro({ me, signup, onNext }: { me: Me | null; signup: string; onNext: () => void }) {
  return (
    <>
      <View style={s.card}>
        <Text style={s.body}>Lil'Helper plans your family's week of meals around who's home, allergies, what's on
          special and your budget; splits the shopping across stores; and shares the cooking and clean-up fairly.</Text>
        <Text style={s.muted}>Signed in as {me?.user.email ?? "…"}</Text>
      </View>
      <View style={s.card}>
        <View style={s.between}><Text style={s.h2}>Lil'Helper Family</Text><Pill text="Beta: free" /></View>
        <Text style={s.body}>One household, everyone in it, unlimited plans, calendar and push updates.</Text>
        <Text style={s.muted}>Subscriptions start with the App Store release; you'll be asked before anything is
          charged, and you can cancel in your App Store settings. {signup === "invite"
            ? "During the beta, starting a household needs a sign-up code."
            : signup === "closed" ? "New households are paused right now; ask someone to invite you." : ""}</Text>
      </View>
      <View style={s.card}>
        <Text style={s.muted}>Joining someone else's household? Ask them to invite you from Home → People; the email
          link brings you straight in.</Text>
      </View>
      <Button title="Start my household" onPress={onNext} disabled={signup === "closed"} />
    </>
  );
}

function CreateHousehold({ me, signup, onDone }: { me: Me | null; signup: string; onDone: () => void }) {
  const [name, setName] = useState("");
  const [you, setYou] = useState(me?.user.name ?? "");
  const [code, setCode] = useState("");
  const [tz, setTz] = useState(deviceZone());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function create() {
    setBusy(true); setError(null);
    try {
      await api.createHousehold({ name, your_name: you, signup_code: code || undefined, timezone: tz });
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <View style={s.card}>
      <Field label="Household name" placeholder="The Powers house" value={name} onChangeText={setName} />
      <Field label="Your first name" placeholder="as the family calls you" value={you} onChangeText={setYou} />
      <Field label="Time zone" value={tz} onChangeText={setTz} autoCapitalize="none"
        hint="Dinner times, reminders and the calendar use this." />
      {signup === "invite" ? <Field label="Sign-up code" value={code} onChangeText={setCode} autoCapitalize="none" /> : null}
      <Text style={s.muted}>You'll be the household's admin: you add people, invite them and change settings.</Text>
      <Button title="Create household" busy={busy} onPress={create}
        disabled={!name.trim() || !you.trim() || (signup === "invite" && !code.trim())} />
      <ErrorText error={error} />
    </View>
  );
}

function SettingsSteps({ step, next }: { step: number; next: () => void }) {
  const set = useSettings();
  const [ready, setReady] = useState(-1);
  // each step starts from the settings as they are now (earlier steps changed them)
  useEffect(() => { set.reload().then(() => setReady(step)); }, [step]);
  if (!set.view || ready !== step) return <><Text style={s.muted}>Loading…</Text><ErrorText error={set.error} /></>;
  const body = {
    2: <PeopleStep next={next} />,
    3: <DinnersStep set={set} next={next} />,
    4: <NightsStep set={set} next={next} />,
    5: <MoneyStep set={set} next={next} />,
    6: <KitchenStep set={set} next={next} />,
    7: <TripsStep set={set} next={next} />,
    8: <LoopStep next={next} />,
    9: <FirstPlan />,
  }[step];
  return <>{body}<ErrorText error={set.error} /></>;
}

type S = ReturnType<typeof useSettings>;

// ---- people: add, set kid/adult, allergies, invite
function PeopleStep({ next }: { next: () => void }) {
  const [people, setPeople] = useState<Person[]>([]);
  const [allergens, setAllergens] = useState<string[]>([]);
  const [p, setP] = useState<PersonIn>({ name: "", age_band: "adult", allergies: [], can_cook: true });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const load = () => api.people().then((r) => setPeople(r.people)).catch(setError);
  useEffect(() => { load(); api.settings().then((v) => setAllergens(v.catalogs.allergens)).catch(() => {}); }, []);

  async function add() {
    setBusy(true); setError(null);
    try {
      const r = await api.addPerson({ ...p, email: email || undefined, can_cook: p.age_band === "adult" && p.can_cook });
      if (email) await api.invite(r.added, email);
      setP({ name: "", age_band: "adult", allergies: [], can_cook: true }); setEmail("");
      await load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <>
      <View style={s.card}>
        {people.map((x) => <Text key={x.id} style={s.body}>{x.age_band === "kid" ? "🧒" : "🧑"} {x.name}
          <Text style={s.muted}>  {x.role}{x.allergies?.length ? ` · allergic to ${x.allergies.join(", ")}` : ""}
            {x.invited ? " · invited" : ""}</Text></Text>)}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Add someone</Text>
        <Field label="Name" value={p.name} onChangeText={(name) => setP({ ...p, name })} />
        <Chips multi={false} options={[{ id: "adult", label: "Adult" }, { id: "kid", label: "Child" }]}
          value={p.age_band} onChange={([v]) => setP({ ...p, age_band: v as "adult" | "kid", age: v === "kid" ? p.age ?? 8 : undefined })} />
        {p.age_band === "kid" ? <NumberField label="Age" value={p.age ?? 8} min={0} max={17}
          onChange={(age) => setP({ ...p, age })} hint="Used for kid-friendly jobs and kid chef nights." /> : null}
        <Chips label="Allergies" options={allergens} value={p.allergies} onChange={(allergies) => setP({ ...p, allergies })} />
        {p.age_band === "adult" ? <Toggle label="Can cook dinner" value={!!p.can_cook}
          onChange={(can_cook) => setP({ ...p, can_cook })} /> : null}
        <Field label="Email to invite them (optional)" value={email} onChangeText={setEmail} autoCapitalize="none"
          keyboardType="email-address" hint={p.age_band === "kid" ? "Kids can see the plan and rate meals; they can't approve or buy." : "They'll get a link that brings them into this household."} />
        <Button kind="ghost" title={email ? "Add and invite" : "Add"} busy={busy} disabled={!p.name.trim()} onPress={add} />
        <ErrorText error={error} />
      </View>
      <Button title="Next" onPress={next} />
    </>
  );
}

// ---- dinners: which days, what time, who's usually home
function DinnersStep({ set, next }: { set: S; next: () => void }) {
  const { st } = set;
  const [days, setDays] = useState<string[]>(st.meals?.dinner?.days ?? [...DAYS]);
  const [time, setTime] = useState<string>(st.dinner_times?.default ?? "18:00");
  const [people, setPeople] = useState<Person[]>([]);
  useEffect(() => { api.people().then((r) => setPeople(r.people)).catch(set.setError); }, []);
  async function save() {
    const meals = { ...(st.meals ?? {}), dinner: { ...(st.meals?.dinner ?? { eaters: "all" }), days } };
    if (!(await set.save("meals", meals))) return;
    if (!(await set.save("dinner_times", { ...(st.dinner_times ?? {}), default: time }))) return;
    for (const p of people) {
      const { id, role: _r, signed_up: _s, invited: _i, last_seen: _l, ...rest } = p;
      await api.savePerson(id, rest);
    }
    next();
  }
  return (
    <>
      <View style={s.card}>
        <Chips label="Plan dinner on" options={DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }))} value={days}
          onChange={setDays} />
        <Field label="Usual dinner time" value={time} onChangeText={setTime} placeholder="18:00"
          hint="24-hour, like 18:00. Change single days later in Settings → Dinners." />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Who's usually home for dinner</Text>
        <Text style={s.muted}>Lil'Helper cooks for whoever's home. You can mark someone out for a night any week.</Text>
        {people.map((p, i) => (
          <Chips key={p.id} label={p.name} options={DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }))}
            value={p.home ?? [...DAYS]} onChange={(home) => setPeople(people.map((x, j) => j === i ? { ...x, home } : x))} />
        ))}
      </View>
      <Button title="Save and continue" busy={set.busy} onPress={save} disabled={!/^\d{1,2}:\d{2}$/.test(time)} />
    </>
  );
}

// ---- takeout, eating out, leftovers nights
function NightsStep({ set, next }: { set: S; next: () => void }) {
  const { st } = set;
  const [nights, setNights] = useState<Record<string, string>>(st.meals?.special_nights ?? {});
  const [eo, setEo] = useState(st.eating_out ?? { takeout: { budget: 50, service: "uber_eats" },
    eat_out: { budget: 80, service: "restaurant" } });
  async function save() {
    if (!(await set.save("meals", { ...st.meals, special_nights: nights }))) return;
    if (await set.save("eating_out", eo)) next();
  }
  const kinds = ["cook", "leftovers", "takeout", "eat_out", "freezer"];
  return (
    <>
      <View style={s.card}>
        <Text style={s.muted}>Any regular nights you don't cook? Pick for each day (most families leave these on Cook).</Text>
        {DAYS.map((d) => (
          <Chips key={d} label={DAY_SHORT[d]} multi={false}
            options={kinds.map((k) => ({ id: k, label: k === "eat_out" ? "eat out" : k }))}
            value={nights[d] ?? "cook"} onChange={([k]) => {
              const n = { ...nights }; if (k === "cook") delete n[d]; else n[d] = k; setNights(n);
            }} />
        ))}
      </View>
      <View style={s.card}>
        <NumberField label="Takeout budget per night" prefix="$" step={5} value={eo.takeout?.budget}
          onChange={(budget) => setEo({ ...eo, takeout: { ...eo.takeout, budget } })} />
        <NumberField label="Eating out budget per night" prefix="$" step={5} value={eo.eat_out?.budget}
          onChange={(budget) => setEo({ ...eo, eat_out: { ...eo.eat_out, budget } })} />
      </View>
      <Button title="Save and continue" busy={set.busy} onPress={save} />
    </>
  );
}

// ---- stores, memberships, cards, budget, cost per serving
function MoneyStep({ set, next }: { set: S; next: () => void }) {
  const { st, cat } = set;
  const [stores, setStores] = useState<string[]>(st.stores ?? []);
  const [home, setHome] = useState<string>(st.home_store ?? stores[0]);
  const [mem, setMem] = useState<string[]>(st.memberships ?? []);
  const [cards, setCards] = useState<string[]>(st.cards ?? []);
  const [budget, setBudget] = useState<number>(st.household?.budget_per_week ?? 200);
  const [cost, setCost] = useState(st.cost_per_serving ?? { min: 0, max: 6 });
  async function save() {
    for (const [k, v] of [["stores", stores], ["home_store", stores.includes(home) ? home : stores[0]],
      ["memberships", mem], ["cards", cards], ["household", { ...st.household, budget_per_week: budget }],
      ["cost_per_serving", cost]] as const) {
      if (!(await set.save(k, v))) return;
    }
    next();
  }
  return (
    <>
      <View style={s.card}>
        <Chips label="Where you shop" options={(cat?.stores ?? []).map((x) => ({ id: x.id, label: x.name }))}
          value={stores} onChange={setStores} />
        <Chips label="Your usual store" multi={false} value={home}
          options={(cat?.stores ?? []).filter((x) => stores.includes(x.id)).map((x) => ({ id: x.id, label: x.name }))}
          onChange={([v]) => setHome(v)} />
        <Chips label="Memberships" options={(cat?.memberships ?? []).map((x) => ({ id: x.id, label: x.name }))}
          value={mem} onChange={setMem} />
        <Chips label="Cards you pay with" options={(cat?.cards ?? []).map((x) => ({ id: x.id, label: x.name }))}
          value={cards} onChange={setCards} />
        <Text style={s.muted}>Card names only, to pick the best card for each order. Never a card number.</Text>
      </View>
      <View style={s.card}>
        <NumberField label="Weekly grocery budget" prefix="$" step={10} value={budget} onChange={setBudget} />
        <NumberField label="Dinner cost per serving, at most" prefix="$" step={0.5} value={cost.max}
          onChange={(max) => setCost({ ...cost, max })} />
        <NumberField label="…and at least (0 for no minimum)" prefix="$" step={0.5} value={cost.min}
          onChange={(min) => setCost({ ...cost, min })} />
      </View>
      <Button title="Save and continue" busy={set.busy} onPress={save} disabled={!stores.length} />
    </>
  );
}

// ---- fridge, freezer, kid chef
function KitchenStep({ set, next }: { set: S; next: () => void }) {
  const { st } = set;
  const [sto, setSto] = useState(st.storage ?? { fridge_l: 500, freezer_l: 200, fill_target: 0.8 });
  const [fm, setFm] = useState(st.freezer_meals ?? { cook_extra: false, keep: 2 });
  const [kc, setKc] = useState<Record<string, string>>(st.kid_chef ?? {});
  const kids = Object.entries(st.people ?? {}).filter(([, p]: [string, any]) => p.age_band === "kid" && (p.age ?? 8) >= 6);
  async function save() {
    if (!(await set.save("storage", sto))) return;
    if (!(await set.save("freezer_meals", fm))) return;
    if (kids.length && !(await set.save("kid_chef", kc))) return;
    next();
  }
  return (
    <>
      <View style={s.card}>
        <Text style={s.muted}>Roughly how big are your fridge and freezer? A typical family fridge is about 500 L with a
          200 L freezer. Lil'Helper only buys ahead (sales, bulk packs) what will fit.</Text>
        <NumberField label="Fridge (litres)" step={25} value={sto.fridge_l} onChange={(fridge_l) => setSto({ ...sto, fridge_l })} />
        <NumberField label="Freezer (litres)" step={25} value={sto.freezer_l} onChange={(freezer_l) => setSto({ ...sto, freezer_l })} />
        <Toggle label="Cook extra for the freezer" hint="Doubles a freezes-well dinner now and then, for busy nights."
          value={!!fm.cook_extra} onChange={(cook_extra) => setFm({ ...fm, cook_extra })} />
      </View>
      {kids.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Kid chef night</Text>
          <Text style={s.muted}>A child cooks dinner (something simple for their age), with an adult nearby.</Text>
          {kids.map(([pid, p]: [string, any]) => (
            <Chips key={pid} label={p.name} multi={false}
              options={[{ id: "", label: "No" }, ...DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }))]}
              value={Object.entries(kc).find(([, v]) => v === pid)?.[0] ?? ""}
              onChange={([d]) => { const n = Object.fromEntries(Object.entries(kc).filter(([, v]) => v !== pid));
                if (d) n[d] = pid; setKc(n); }} />
          ))}
        </View>
      ) : null}
      <Button title="Save and continue" busy={set.busy} onPress={save} />
    </>
  );
}

function TripsStep({ set, next }: { set: S; next: () => void }) {
  return (
    <>
      <View style={s.card}>
        <Text style={s.muted}>When do you usually shop? Add your regular trips and orders, and each one gets its own
          list (fresh things on the trip closest to when they're cooked). Or skip, and Lil'Helper picks the cheapest
          way each week.</Text>
      </View>
      <TripsEditor set={set} onSaved={next} />
    </>
  );
}

function LoopStep({ next }: { next: () => void }) {
  return <><LoopCard /><Button title="Next" onPress={next} /></>;
}

function FirstPlan() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <>
      <View style={s.card}>
        <Text style={s.body}>All set. Lil'Helper drafts next week every Saturday morning; an adult looks it over,
          swaps anything, and approves. Nothing is ever bought for you.</Text>
      </View>
      <Button title="Plan this week now" busy={busy} onPress={async () => {
        setBusy(true); setError(null);
        try { await api.draft(); router.replace("/"); } catch (e) { setError(e); } finally { setBusy(false); }
      }} />
      <Button kind="ghost" title="Go to the app" onPress={() => router.replace("/")} />
      <ErrorText error={error} />
    </>
  );
}
