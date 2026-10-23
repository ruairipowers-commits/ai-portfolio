// Dinners: which days, what time each day, nights that aren't cooked, and what takeout and eating out cost.
import { useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { DAY_SHORT, DAYS, NIGHT_NAME } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { AdminNote, Button, Chips, ErrorText, Field, Header, NumberField, Saved, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

const TIME = /^([01]?\d|2[0-3]):[0-5]\d$/;

export default function Dinners() {
  const set = useSettings();
  const { st, isAdmin, role } = set;
  const [days, setDays] = useState<string[]>([]);
  const [times, setTimes] = useState<Record<string, string>>({});
  const [nights, setNights] = useState<Record<string, string>>({});
  const [eo, setEo] = useState<Record<string, { budget?: number; service?: string }>>({});
  const [bfast, setBfast] = useState<string[]>([]);
  useEffect(() => {
    if (!set.view) return;
    setDays(st.meals?.dinner?.days ?? [...DAYS]);
    setTimes(st.dinner_times ?? { default: "18:00" });
    setNights(st.meals?.special_nights ?? {});
    setEo(st.eating_out ?? {});
    setBfast(st.meals?.breakfast?.days ?? []);
  }, [set.view?.version]);

  const bad = Object.values(times).some((t) => t && !TIME.test(t));
  async function save() {
    const meals = { ...st.meals, dinner: { ...(st.meals?.dinner ?? { eaters: "all" }), days }, special_nights: nights };
    if (bfast.length) meals.breakfast = { ...(st.meals?.breakfast ?? { eaters: "all" }), days: bfast };
    else delete meals.breakfast;
    const clean = Object.fromEntries(Object.entries(times).filter(([k, v]) => v && (k === "default" || v !== times.default)));
    for (const [k, v] of [["meals", meals], ["dinner_times", clean], ["eating_out", eo]] as const) {
      if (!(await set.save(k, v))) return;
    }
  }
  const kinds = ["cook", "leftovers", "takeout", "eat_out", "freezer"];
  return (
    <Screen>
      <Header title="Dinners" />
      <AdminNote role={role} />
      <View style={s.card}>
        <Chips label="Plan dinner on" options={DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }))} value={days} onChange={setDays} />
        <Chips label="Weekend breakfast too" options={DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }))} value={bfast} onChange={setBfast} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Dinner time</Text>
        <Field label="Usually" value={times.default ?? ""} onChangeText={(v) => setTimes({ ...times, default: v })} placeholder="18:00" />
        <Text style={s.muted}>Different on some days? (leave blank for the usual time)</Text>
        <View style={s.wrap}>
          {DAYS.map((d) => (
            <View key={d} style={{ width: "30%" }}>
              <Field label={DAY_SHORT[d]} value={times[d] ?? ""} placeholder={times.default}
                onChangeText={(v) => setTimes({ ...times, [d]: v })} />
            </View>
          ))}
        </View>
        {bad ? <Text style={[s.muted, { color: "#D7392A" }]}>Times are 24-hour, like 18:30.</Text> : null}
        <Text style={s.muted}>Who's home each night is set per person under People; mark someone out for one night from
          This week.</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Nights off (every week)</Text>
        {DAYS.map((d) => (
          <Chips key={d} label={DAY_SHORT[d]} multi={false} value={nights[d] ?? "cook"}
            options={kinds.map((k) => ({ id: k, label: NIGHT_NAME[k] }))}
            onChange={([k]) => { const n = { ...nights }; if (k === "cook") delete n[d]; else n[d] = k; setNights(n); }} />
        ))}
        <Text style={s.muted}>Leftovers nights eat up what's in the fridge (the plan cooks extra earlier). Freezer nights
          use a meal you froze. Change a single week from This week.</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Takeout and eating out</Text>
        <NumberField label="Takeout, per night" prefix="$" step={5} value={eo.takeout?.budget}
          onChange={(budget) => setEo({ ...eo, takeout: { service: "uber_eats", ...eo.takeout, budget } })} />
        <Chips label="Usually ordered through" multi={false} value={eo.takeout?.service ?? "uber_eats"}
          options={[{ id: "uber_eats", label: "Uber Eats" }, { id: "doordash", label: "DoorDash" }, { id: "restaurant", label: "Direct" }]}
          onChange={([service]) => setEo({ ...eo, takeout: { budget: 50, ...eo.takeout, service } })} />
        <NumberField label="Eating out, per night" prefix="$" step={5} value={eo.eat_out?.budget}
          onChange={(budget) => setEo({ ...eo, eat_out: { service: "restaurant", ...eo.eat_out, budget } })} />
        <Text style={s.muted}>Card credits (like Uber Cash) are taken off, and the best card is suggested.</Text>
      </View>
      {isAdmin ? <Button title="Save" busy={set.busy} disabled={bad || !days.length} onPress={save} /> : null}
      <Saved at={set.savedAt} />
      <ErrorText error={set.error} />
    </Screen>
  );
}
