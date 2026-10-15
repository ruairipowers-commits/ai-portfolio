// Stores, memberships, cards and budget. Card names only (benefits come from the server's card list, each with the
// date it was last checked); never a card number.
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { AdminNote, Button, Chips, ErrorText, Header, money, NumberField, Saved, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

type Best = Awaited<ReturnType<typeof api.cards>>;

export default function Stores() {
  const set = useSettings();
  const { st, cat, isAdmin, role } = set;
  const [stores, setStores] = useState<string[]>([]);
  const [home, setHome] = useState("");
  const [mem, setMem] = useState<string[]>([]);
  const [cards, setCards] = useState<string[]>([]);
  const [budget, setBudget] = useState(200);
  const [hour, setHour] = useState(20);
  const [cost, setCost] = useState<{ min: number; max: number }>({ min: 0, max: 6 });
  const [best, setBest] = useState<Best | null>(null);
  useEffect(() => {
    if (!set.view) return;
    setStores(st.stores ?? []); setHome(st.home_store ?? ""); setMem(st.memberships ?? []); setCards(st.cards ?? []);
    setBudget(st.household?.budget_per_week ?? 200); setHour(st.household?.time_value_per_hour ?? 20);
    setCost({ min: st.cost_per_serving?.min ?? 0, max: st.cost_per_serving?.max ?? 6 });
    if (role !== "kid") api.cards().then(setBest).catch(() => {});
  }, [set.view?.version]);

  async function save() {
    const hs = stores.includes(home) ? home : stores[0];
    for (const [k, v] of [["stores", stores], ["home_store", hs], ["memberships", mem], ["cards", cards],
      ["household", { ...st.household, budget_per_week: budget, time_value_per_hour: hour }],
      ["cost_per_serving", cost]] as const) {
      if (!(await set.save(k, v))) return;
    }
    api.cards().then(setBest).catch(() => {});
  }
  return (
    <Screen>
      <Header title="Stores, cards and budget" />
      <AdminNote role={role} />
      <View style={s.card}>
        <Chips label="Where you shop" options={(cat?.stores ?? []).map((x) => ({ id: x.id, label: x.name }))} value={stores} onChange={setStores} />
        <Chips label="Your usual store (the savings baseline)" multi={false} value={home}
          options={(cat?.stores ?? []).filter((x) => stores.includes(x.id)).map((x) => ({ id: x.id, label: x.name }))}
          onChange={([v]) => setHome(v)} />
        <Chips label="Memberships" options={(cat?.memberships ?? []).map((x) => ({ id: x.id, label: x.name }))} value={mem} onChange={setMem} />
        <Text style={s.muted}>Prime brings Whole Foods member deals; Instacart+ and Amazon's grocery subscription waive
          delivery fees over their minimums; Costco needs a membership.</Text>
        <Chips label="Cards" options={(cat?.cards ?? []).map((x) => ({ id: x.id, label: x.name }))} value={cards} onChange={setCards} />
      </View>
      <View style={s.card}>
        <NumberField label="Weekly grocery budget" prefix="$" step={10} value={budget} onChange={setBudget} />
        <NumberField label="Dinner cost per serving, at most" prefix="$" step={0.5} value={cost.max} onChange={(max) => setCost({ ...cost, max })} />
        <NumberField label="…at least (0 for none)" prefix="$" step={0.5} value={cost.min} onChange={(min) => setCost({ ...cost, min })} />
        <NumberField label="An hour of your time is worth" prefix="$" step={5} value={hour} onChange={setHour}
          hint="Used to weigh an extra trip against a delivery fee." />
      </View>
      {isAdmin ? <Button title="Save" busy={set.busy} disabled={!stores.length} onPress={save} /> : null}
      <Saved at={set.savedAt} />
      {best?.best.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Which card where</Text>
          {best.best.map((b) => <Text key={b.store + b.mode} style={s.body}>{b.store} <Text style={s.muted}>{b.mode.replace("_", " ")}</Text>
            {"  "}{b.card} <Text style={s.muted}>({money(b.per_100)} back per $100 · {b.note})</Text></Text>)}
          {best.cards.some((c) => !c.verified) ? <Text style={s.muted}>Some card benefits haven't been checked
            recently; confirm them with your card issuer.</Text> : null}
        </View>
      ) : null}
      <ErrorText error={set.error} />
    </Screen>
  );
}
