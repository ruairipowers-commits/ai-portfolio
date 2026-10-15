// Reports: what food costs (per week, meal and person, planned against spent), time (cooking, shopping, planning),
// calories planned per person per day, and who did which jobs.
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { Activity, api, CostReport, JOB_NAME } from "@/lib/api";
import { Chips, ErrorText, Header, money, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const TABS = [{ id: "cost", label: "💵 Costs" }, { id: "time", label: "⏱️ Time" }, { id: "kcal", label: "🔥 Calories" },
  { id: "jobs", label: "🧽 Jobs" }];
const short = (w: string) => new Date(`${w}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const hrs = (m: number) => (m >= 90 ? `${(m / 60).toFixed(1)} h` : `${Math.round(m)} min`);

function Bar({ value, max, color = c.green }: { value: number; max: number; color?: string }) {
  return <View style={{ height: 8, backgroundColor: c.line, borderRadius: 4 }}>
    <View style={{ height: 8, width: `${Math.min(100, (value / Math.max(1, max)) * 100)}%`, backgroundColor: color, borderRadius: 4 }} />
  </View>;
}

export default function Report() {
  const [tab, setTab] = useState("cost");
  const [weeks, setWeeks] = useState(8);
  const [r, setR] = useState<CostReport | null>(null);
  const [a, setA] = useState<Activity | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    setError(null);
    api.activity(weeks).then(setA).catch(setError);
    api.costReport(weeks).then(setR).catch(() => setR(null));   // kids can't see costs
  }, [weeks]);
  const max = Math.max(1, ...(r?.weeks.map((w) => Math.max(w.total, w.actual?.groceries ?? 0)) ?? [1]));
  const tmax = Math.max(1, ...(a?.weeks.map((w) => w.cooking_minutes + w.shopping_minutes + w.planning_minutes) ?? [1]));
  const jmax = Math.max(1, ...(a?.chores.map((x) => x.total) ?? [1]));
  return (
    <Screen>
      <Header title="Reports" />
      <Chips multi={false} options={TABS.filter((t) => t.id !== "cost" || r)} value={tab} onChange={([t]) => setTab(t)} />
      <Chips multi={false} options={[{ id: "4", label: "4 weeks" }, { id: "8", label: "8 weeks" }, { id: "13", label: "3 months" },
        { id: "26", label: "6 months" }]} value={String(weeks)} onChange={([w]) => setWeeks(Number(w))} />

      {tab === "cost" && r ? <>
        <View style={s.card}>{r.analysis.map((x, i) => <Text key={i} style={s.body}>• {x}</Text>)}</View>
        <View style={s.card}>
          <Text style={s.h2}>By week</Text>
          {r.weeks.map((w) => (
            <View key={w.week_of} style={{ gap: 3 }}>
              <View style={s.between}><Text style={s.body}>{short(w.week_of)}</Text><Text style={s.body}>{money(w.total)}
                {w.actual ? <Text style={s.muted}>  spent {money(w.actual.groceries)}</Text> : null}</Text></View>
              <Bar value={w.total} max={max} />
              {w.actual ? <Bar value={w.actual.groceries} max={max} color={w.actual.groceries > w.total ? c.red : c.amber} /> : null}
              <Text style={s.muted}>groceries {money(w.food_bill)} (meals used {money(w.food_used)}, stocked up {money(w.stock_change)}) ·
                nights out {money(w.eating_out)} · pet {money(w.pet_food)}</Text>
            </View>))}
          <Text style={s.muted}>Green: planned. Amber or red: recorded spending (Money).</Text>
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

      {tab === "time" && a ? <View style={s.card}>
        <Text style={s.h2}>{hrs(a.minutes.cooking)} cooking · {hrs(a.minutes.shopping)} shopping</Text>
        {a.weeks.map((w) => (
          <View key={w.week_of} style={{ gap: 3 }}>
            <View style={s.between}><Text style={s.body}>{short(w.week_of)}</Text>
              <Text style={s.muted}>🍳 {hrs(w.cooking_minutes)} · 🛒 {hrs(w.shopping_minutes)} · 🗓️ {hrs(w.planning_minutes)}</Text></View>
            <Bar value={w.cooking_minutes + w.shopping_minutes + w.planning_minutes} max={tmax} />
          </View>))}
        <Text style={s.muted}>Cooking is hands-on time from the recipes; shopping from your trips; planning is time
          spent in the app before approving.</Text>
      </View> : null}

      {tab === "kcal" && a ? <View style={s.card}>
        <Text style={s.h2}>Planned per day, on average</Text>
        {a.kcal.map((k) => <View key={k.person} style={{ gap: 3 }}>
          <View style={s.between}><Text style={s.body}>{k.person}</Text><Text style={s.body}>{k.avg_per_day_planned} kcal</Text></View>
          <Bar value={k.avg_per_day_planned} max={Math.max(...a.kcal.map((x) => x.avg_per_day_planned), 1)} color={c.amber} />
        </View>)}
        <Text style={s.muted}>{a.note}</Text>
      </View> : null}

      {tab === "jobs" && a ? <View style={s.card}>
        <Text style={s.h2}>Who did what</Text>
        {a.chores.sort((x, y) => y.total - x.total).map((p) => (
          <View key={p.person} style={{ gap: 3 }}>
            <View style={s.between}><Text style={s.body}>{p.person}</Text><Text style={s.body}>{p.total} jobs</Text></View>
            <Bar value={p.total} max={jmax} />
            <Text style={s.muted}>{Object.entries(p.jobs).map(([j, n]) => `${JOB_NAME[j] ?? j} ${n}`).join(" · ")}</Text>
          </View>))}
        {!a.chores.length ? <Text style={s.muted}>No approved weeks yet.</Text> : null}
      </View> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
