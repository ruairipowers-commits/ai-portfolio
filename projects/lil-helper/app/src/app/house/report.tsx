// What food costs: per week, per meal, per person, with the bill and what the meals actually used side by side.
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api, CostReport } from "@/lib/api";
import { Chips, ErrorText, Header, money, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function Report() {
  const [weeks, setWeeks] = useState(8);
  const [r, setR] = useState<CostReport | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { api.costReport(weeks).then(setR).catch(setError); }, [weeks]);
  const max = Math.max(1, ...(r?.weeks.map((w) => w.total) ?? [1]));
  return (
    <Screen>
      <Header title="What food costs" />
      <Chips multi={false} options={[{ id: "4", label: "4 weeks" }, { id: "8", label: "8 weeks" }, { id: "13", label: "3 months" }]}
        value={String(weeks)} onChange={([w]) => setWeeks(Number(w))} />
      {r ? <>
        <View style={s.card}>
          {r.analysis.map((a, i) => <Text key={i} style={s.body}>• {a}</Text>)}
        </View>
        <View style={s.card}>
          <Text style={s.h2}>By week</Text>
          {r.weeks.map((w) => (
            <View key={w.week_of} style={{ gap: 2 }}>
              <View style={s.between}><Text style={s.body}>{w.week_of}</Text><Text style={s.body}>{money(w.total)}
                {w.actual != null ? <Text style={s.muted}>  spent {money(w.actual)}</Text> : null}</Text></View>
              <View style={{ height: 6, width: `${(w.total / max) * 100}%`, backgroundColor: c.green, borderRadius: 3 }} />
              <Text style={s.muted}>groceries {money(w.food_bill)} (meals used {money(w.food_used)}, stocked up {money(w.stock_change)}) ·
                nights out {money(w.eating_out)} · pet {money(w.pet_food)}</Text>
            </View>
          ))}
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Per person</Text>
          {r.people.map((p) => <Text key={p.person} style={s.body}>{p.name} <Text style={s.muted}>{money(p.per_week)}/week · {money(p.per_day)}/day</Text></Text>)}
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Per meal</Text>
          {Object.entries(r.by_meal).map(([m, v]) => <Text key={m} style={s.body}>{m} <Text style={s.muted}>{money(v.avg_cost)} a meal ·
            {" "}{money(v.avg_per_serving)} a serving · {v.meals} meals</Text></Text>)}
        </View>
        <View style={s.card}><Text style={s.muted}>{r.basis}</Text></View>
      </> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
