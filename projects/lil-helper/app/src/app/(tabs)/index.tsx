// This week: the plan by day, one-tap swaps, and Approve. The approve button sends how long you spent here, which
// is the "time" half of the savings report.
import { useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, DAY_NAME, DAYS, Entry } from "@/lib/api";
import { useWeek } from "@/lib/useWeek";
import { Button, ErrorText, money, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const MEAL_ICON: Record<string, string> = { breakfast: "🥣", lunch: "🥪", dinner: "🍽️" };

export default function ThisWeek() {
  const { week, setWeek, error, setError, loading, reload } = useWeek();
  const [busy, setBusy] = useState<string | null>(null);
  const opened = useRef(Date.now());
  const approved = week?.status === "approved";

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key); setError(null);
    try { const w = await fn(); if (w && typeof w === "object" && "plan" in w) setWeek(w as never); }
    catch (e) { setError(e); } finally { setBusy(null); }
  }

  if (!week) {
    return (
      <Screen refreshing={loading} onRefresh={reload}>
        <Text style={s.h1}>This week</Text>
        <View style={s.card}>
          <Text style={s.body}>No plan yet. Lil'Helper drafts one on Saturday, or you can ask for it now.</Text>
          <Button title="Plan this week" busy={busy === "draft"} onPress={() => run("draft", () => api.draft())} />
        </View>
        <ErrorText error={error} />
      </Screen>
    );
  }

  const opt = week.options[week.choice];
  const over = week.plan.flags.find((f) => f.startsWith("over_budget_by_"));
  return (
    <Screen refreshing={loading} onRefresh={reload}>
      <View style={s.between}>
        <Text style={s.h1}>This week</Text>
        {approved ? <Pill text={`Approved by ${week.people[week.approved_by ?? ""] ?? "you"}`} /> : <Pill text="Draft" tone="amber" />}
      </View>
      <View style={[s.card, { flexDirection: "row", justifyContent: "space-between" }]}>
        <Stat label="Groceries" value={money(opt?.total)} />
        <Stat label="Saved" value={money(week.savings?.dollars_saved)} />
        <Stat label="Time saved" value={week.savings ? `${Math.round(week.savings.minutes_saved)} min` : "—"} />
      </View>
      {over ? <View style={[s.card, { backgroundColor: c.amberSoft }]}><Text style={s.body}>
        Over budget by ${over.split("_").pop()}. Swap a pricier meal, or raise the budget at home.</Text></View> : null}
      {DAYS.map((d) => {
        const meals = week.plan.entries.filter((e) => e.day === d);
        const special = week.plan.special_nights[d];
        if (!meals.length && !special) return null;
        return (
          <View key={d} style={s.card}>
            <Text style={s.h2}>{DAY_NAME[d]}</Text>
            {meals.map((e) => <MealRow key={e.meal} e={e} locked={approved} busy={busy === `${d}${e.meal}`}
              onSwap={() => run(`${d}${e.meal}`, () => api.swap(d, e.meal))} />)}
            {special ? <Text style={s.muted}>🍲 {special} night — eat up what's in the fridge</Text> : null}
            {week.pets.flatMap((p) => p.extras.filter((x) => x.day === d).map((x) =>
              <Text key={p.name + x.item} style={s.muted}>🐕 {p.name}: a little plain {x.item.toLowerCase()} — {x.how}</Text>))}
          </View>
        );
      })}
      {!approved ? (
        <Button title="Approve the week" busy={busy === "approve"}
          onPress={() => run("approve", () => api.approve((Date.now() - opened.current) / 1000, week.choice))} />
      ) : <Text style={[s.muted, { textAlign: "center" }]}>Shopping lists are ready in the Shopping tab.</Text>}
      <ErrorText error={error} />
    </Screen>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <View style={{ alignItems: "center", flex: 1 }}>
    <Text style={[s.h2, { fontSize: 19 }]}>{value}</Text><Text style={s.muted}>{label}</Text></View>;
}

function MealRow({ e, locked, busy, onSwap }: { e: Entry; locked: boolean; busy: boolean; onSwap: () => void }) {
  return (
    <View style={[s.between, { paddingVertical: 4 }]}>
      <View style={{ flex: 1 }}>
        <Text style={s.body}>{MEAL_ICON[e.meal] ?? "•"} {e.name}</Text>
        <Text style={s.muted}>{e.active} min hands-on · {e.meal === "lunch" ? "lunchbox" : `${e.servings} servings`} · ~{money(e.est_cost)}
          {e.prep_day !== e.day ? ` · cook ${DAY_NAME[e.prep_day]}` : ""}</Text>
      </View>
      {!locked ? (
        <Pressable onPress={onSwap} disabled={busy} style={[s.ghost, { paddingVertical: 6 }]} accessibilityLabel={`Swap ${e.name}`}>
          <Text style={s.ghostText}>{busy ? "…" : "Swap"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
