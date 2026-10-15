// This week: the plan by day, one-tap swaps, nights off and who's out, buying ahead on sales, and Approve. The approve
// button sends how long you spent here, which is the "time" half of the savings report.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, DAY_NAME, DAYS, Entry, NIGHT_NAME, NightOut, Week } from "@/lib/api";
import { useWeek } from "@/lib/useWeek";
import { Button, Chips, ErrorText, money, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const MEAL_ICON: Record<string, string> = { breakfast: "🥣", lunch: "🥪", dinner: "🍽️", leftovers: "🥡" };
const NIGHT_ICON: Record<string, string> = { leftovers: "🥡", takeout: "🛵", eat_out: "🍝", freezer: "🧊" };

export default function ThisWeek() {
  const params = useLocalSearchParams<{ day?: string; week?: string }>();
  const [wk, setWk] = useState<string | undefined>(params.week ? String(params.week) : undefined);
  useEffect(() => { if (params.week) setWk(String(params.week)); }, [params.week]);
  const { week, setWeek, error, setError, loading, reload } = useWeek(wk);
  const go = (n: number) => {
    const base = new Date(`${week?.week_of ?? wk ?? new Date().toISOString().slice(0, 10)}T12:00:00`);
    if (!week) base.setDate(base.getDate() - ((base.getDay() + 6) % 7));
    base.setDate(base.getDate() + 7 * n);
    setWk(base.toISOString().slice(0, 10));
  };
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [role, setRole] = useState<string>("adult");
  const [me, setMe] = useState<string>("");
  const opened = useRef(Date.now());
  useEffect(() => { if (params.day) setOpen(String(params.day)); }, [params.day]);
  useEffect(() => { api.me().then((m) => { setRole(m.current?.role ?? "adult"); setMe(m.current?.person_id ?? ""); }).catch(() => {}); }, []);
  const approved = week?.status === "approved";
  const adult = role !== "kid";

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key); setError(null);
    try { const w = await fn(); if (w && typeof w === "object" && "plan" in w) setWeek(w as Week); else if (w) await reload(); }
    catch (e) { setError(e); } finally { setBusy(null); }
  }

  if (!week) {
    return (
      <Screen refreshing={loading} onRefresh={reload}>
        <Text style={s.h1}>{wk ? weekTitle(wk) : "This week"}</Text>
        <View style={s.card}>
          <Text style={s.body}>No plan yet. Lil'Helper drafts one on Saturday morning, or you can ask for it now.</Text>
          {adult ? <Button title="Plan this week" busy={busy === "draft"} onPress={() => run("draft", () => api.draft(wk))} /> : null}
        </View>
        <View style={s.row}>
          <View style={{ flex: 1 }}><Button kind="ghost" title="◀ Last week" onPress={() => go(-1)} /></View>
          <View style={{ flex: 1 }}><Button kind="ghost" title="Next week ▶" onPress={() => go(1)} /></View>
        </View>
        <ErrorText error={error} />
      </Screen>
    );
  }

  const opt = week.options[week.choice];
  const over = week.plan.flags.find((f) => f.startsWith("over_budget_by_"));
  const notes = week.plan.flags.filter((f) => !f.startsWith("over_budget_by_") && !f.startsWith("chores:"));
  const outNet = week.eating_out.reduce((a, n) => a + n.net, 0);
  const ahead = week.extras.buy_ahead ?? [];
  const added = new Set((week.extras.buy_ahead_added ?? []).map((a) => a.ingredient));
  return (
    <Screen refreshing={loading} onRefresh={reload}>
      <View style={s.between}>
        <Text style={s.h1}>{weekTitle(week.week_of)}</Text>
        {approved ? <Pill text={`Approved by ${week.people[week.approved_by ?? ""] ?? "you"}`} /> : <Pill text="Draft" tone="amber" />}
      </View>
      <View style={[s.card, { flexDirection: "row", justifyContent: "space-between" }]}>
        <Stat label="Groceries" value={money(opt?.total)} />
        {week.eating_out.length ? <Stat label="Nights out" value={money(outNet)} /> : null}
        <Stat label="Saved" value={money(week.savings?.dollars_saved)} />
      </View>
      {over ? <View style={[s.card, { backgroundColor: c.amberSoft }]}><Text style={s.body}>
        Over budget by ${over.split("_").pop()}. Swap a pricier meal, or change the budget under Home.</Text></View> : null}
      {notes.length ? <View style={s.card}>{notes.slice(0, 4).map((f) => <Text key={f} style={s.muted}>ℹ️ {f.replace(/_/g, " ")}</Text>)}</View> : null}
      {DAYS.map((d) => {
        const meals = week.plan.entries.filter((e) => e.day === d);
        const special = week.plan.special_nights[d];
        const out = week.eating_out.find((n) => n.day === d);
        const isOpen = open === d;
        return (
          <View key={d} style={[s.card, isOpen && { borderColor: c.green }]}>
            <Pressable onPress={() => setOpen(isOpen ? null : d)} style={s.between} accessibilityRole="button"
              accessibilityLabel={`${DAY_NAME[d]}: change the night or who's home`}>
              <Text style={s.h2}>{DAY_NAME[d]} <Text style={s.muted}>{week.dinner_times[d]}</Text></Text>
              <Text style={s.muted}>{(week.away[d] ?? []).length ? `${week.away[d].length} out · ` : ""}{isOpen ? "Done" : "Change"}</Text>
            </Pressable>
            {meals.map((e) => <MealRow key={e.meal} e={e} week={week} adult={adult} approved={approved}
              busy={busy === `${d}${e.meal}`}
              onSwap={() => run(`${d}${e.meal}`, () => api.swap(d, e.meal, wk))}
              onChange={() => router.push({ pathname: "/house/change", params: { day: d, meal: e.meal, week: week.week_of } } as never)}
              onUndo={() => run(`${d}${e.meal}`, () => api.revert(d, e.meal, wk))}
              onOutcome={(o, n) => run(`${d}${e.meal}`, () => api.outcome(d, e.meal, o, n, wk))}
              onParts={() => router.push({ pathname: "/house/parts", params: { day: d, meal: e.meal, week: week.week_of } } as never)} />)}
            {special && !out ? <Text style={s.body}>{NIGHT_ICON[special] ?? "•"} {NIGHT_NAME[special] ?? special} night
              {special === "leftovers" ? <Text style={s.muted}> — eat up what's in the fridge</Text> : null}</Text> : null}
            {out ? <NightOutRow n={out} /> : null}
            {week.pets.flatMap((p) => p.extras.filter((x) => x.day === d).map((x) =>
              <Text key={p.name + x.item} style={s.muted}>🐕 {p.name}: a little plain {x.item.toLowerCase()} — {x.how}</Text>))}
            {isOpen ? <DayEditor week={week} day={d} adult={adult} me={me} busy={busy}
              onNight={(k) => run(`n${d}`, () => api.night(d, k, wk))}
              onAway={(pid, away) => run(`a${d}${pid}`, () => api.away(d, pid, away, wk))} /> : null}
          </View>
        );
      })}
      {ahead.length && adult ? (
        <View style={s.card}>
          <Text style={s.h2}>Buy ahead while it's cheap</Text>
          <Text style={s.muted}>On sale now, needed in the next few weeks, and there's room for it.</Text>
          {ahead.map((a) => (
            <View key={a.ingredient} style={s.between}>
              <View style={{ flex: 1 }}>
                <Text style={s.body}>{a.packs} × {a.name} <Text style={s.muted}>at {a.store_name}</Text></Text>
                <Text style={s.muted}>save {money(a.saving)} · needed {a.needed_on} · {a.keep === "freeze" ? "freeze it" : `keeps in the ${a.keep}`}</Text>
              </View>
              {added.has(a.ingredient) ? <Pill text="On the list" /> :
                <Pressable style={[s.ghost, { paddingVertical: 6 }]} onPress={() => run(`ah${a.ingredient}`, () => api.ahead([a.ingredient], wk))}>
                  <Text style={s.ghostText}>{busy === `ah${a.ingredient}` ? "…" : "Add"}</Text></Pressable>}
            </View>
          ))}
        </View>
      ) : null}
      <View style={s.row}>
        <View style={{ flex: 1 }}><Button kind="ghost" title="◀ Last week" onPress={() => go(-1)} /></View>
        <View style={{ flex: 1 }}><Button kind="ghost" title="Next week ▶" onPress={() => go(1)} /></View>
      </View>
      {!approved && adult ? (
        <Button title="Approve the week" busy={busy === "approve"}
          onPress={() => run("approve", () => api.approve((Date.now() - opened.current) / 1000, week.choice, wk))} />
      ) : approved ? <Text style={[s.muted, { textAlign: "center" }]}>Shopping lists are ready in the Shopping tab.
        Tap a day to change a night or say who's out.</Text> : null}
      <ErrorText error={error} />
    </Screen>
  );
}

function weekTitle(weekOf: string) {
  const d = new Date(`${weekOf}T12:00:00`);
  const now = new Date(); now.setHours(12, 0, 0, 0);
  const mon = new Date(now); mon.setDate(now.getDate() - ((now.getDay() + 6) % 7));
  const n = Math.round((d.getTime() - mon.getTime()) / (7 * 86400000));
  return n === 0 ? "This week" : n === 1 ? "Next week" : n === -1 ? "Last week"
    : `Week of ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return <View style={{ alignItems: "center", flex: 1 }}>
    <Text style={[s.h2, { fontSize: 19 }]}>{value}</Text><Text style={s.muted}>{label}</Text></View>;
}

const STATE: Record<string, { label: string; tone: "green" | "amber" | "red" }> = {
  planned: { label: "Planned", tone: "amber" }, today: { label: "Today", tone: "green" },
  to_confirm: { label: "How did it go?", tone: "red" }, finished: { label: "Finished", tone: "green" },
  leftovers: { label: "Leftovers", tone: "amber" }, freezer: { label: "Some frozen", tone: "green" },
  skipped: { label: "Skipped", tone: "amber" },
};

function MealRow({ e, week, adult, approved, busy, onSwap, onChange, onUndo, onOutcome, onParts }: { e: Entry; week: Week;
  adult: boolean; approved: boolean; busy: boolean; onSwap: () => void; onChange: () => void; onUndo: () => void;
  onOutcome: (outcome: string, frozen: number) => void; onParts: () => void }) {
  const kind = e.kind ?? "cook";
  const who = e.cook ? week.people[e.cook] : null;
  const [open, setOpen] = useState(false);
  const [frozen, setFrozen] = useState(e.frozen || e.to_freeze || 2);
  const st = e.state ?? "planned";
  const past = approved && st !== "planned";
  const detail = kind === "leftovers" ? `from ${DAY_NAME[e.prep_day]}'s dinner` : kind === "freezer" ? "from the freezer"
    : `${e.active} min hands-on · ${e.meal === "lunch" ? "lunchbox" : `${e.servings} serving${e.servings === 1 ? "" : "s"}`} · ~${money(e.est_cost)}`
      + (e.prep_day !== e.day ? ` · cook ${DAY_NAME[e.prep_day]}` : "");
  const label = st === "freezer" ? `${e.frozen} frozen` : STATE[st]?.label ?? st;
  return (
    <View style={{ paddingVertical: 4, gap: 4 }}>
      <View style={s.between}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={s.body}>{MEAL_ICON[e.meal] ?? "•"} {e.name}</Text>
          <Text style={s.muted}>{detail}</Text>
          <View style={[s.row, { flexWrap: "wrap" }]}>
            {approved ? <Pressable onPress={() => past && setOpen(!open)} disabled={!past}
              accessibilityLabel={`${e.name}: ${label}${past ? ", tap to say what happened" : ""}`}>
              <Pill text={label + (past ? " ▾" : "")} tone={STATE[st]?.tone ?? "amber"} /></Pressable> : null}
            {who && e.meal === "dinner" ? <Pill text={`${who} cooks`} /> : null}
            {e.to_freeze && st !== "freezer" ? <Pill text={`+${e.to_freeze} for the freezer`} tone="amber" /> : null}
          </View>
          {(e.parts ?? []).filter((p) => p.kind !== "cook" || p.recipe !== e.recipe).map((p, i) => (
            <Text key={i} style={s.muted}>{p.kind === "leftovers" ? "🥡" : p.kind === "ready" ? "🥫" : "🍳"} {p.name ?? p.food ?? p.recipe}
              {p.eaters?.length ? ` · ${p.eaters.map((x) => week.people[x] ?? x).join(", ")}` : ""}</Text>))}
          {e.original ? (
            <Text style={s.muted}>Changed from {e.original.name} · {adult ? <Text style={{ color: c.red, fontWeight: "700" }}
              onPress={onUndo} accessibilityRole="button">Undo</Text> : null}</Text>
          ) : null}
        </View>
        {adult && kind === "cook" ? (
          <View style={{ gap: 4 }}>
            <Pressable onPress={onChange} disabled={busy} style={[s.ghost, { paddingVertical: 6 }]} accessibilityLabel={`Change ${e.name}`}>
              <Text style={s.ghostText}>{busy ? "…" : "Change"}</Text>
            </Pressable>
            <Pressable onPress={onParts} disabled={busy} style={[s.ghost, { paddingVertical: 6 }]}
              accessibilityLabel={`Split ${e.name} into parts`}><Text style={s.ghostText}>Split</Text></Pressable>
            {!approved ? <Pressable onPress={onSwap} disabled={busy} style={[s.ghost, { paddingVertical: 6 }]}
              accessibilityLabel={`Swap ${e.name} for another idea`}><Text style={s.ghostText}>Swap</Text></Pressable> : null}
          </View>
        ) : null}
      </View>
      {open ? (
        <View style={{ gap: 6, borderTopWidth: 1, borderTopColor: c.line, paddingTop: 6 }}>
          <Text style={s.label}>What happened?</Text>
          <View style={s.wrap}>
            {[["finished", "All eaten"], ["leftovers", "Leftovers in the fridge"], ["skipped", "Didn't make it"]].map(([k, l]) => (
              <Pressable key={k} style={[s.chip, st === k && { backgroundColor: c.greenSoft, borderColor: c.green }]}
                onPress={() => { onOutcome(k, 0); setOpen(false); }}><Text style={s.chipText}>{l}</Text></Pressable>))}
          </View>
          <View style={s.row}>
            <Pressable style={[s.chip, st === "freezer" && { backgroundColor: c.greenSoft, borderColor: c.green }]}
              onPress={() => { onOutcome("freezer", frozen); setOpen(false); }}>
              <Text style={s.chipText}>Froze {frozen} portion{frozen === 1 ? "" : "s"}</Text></Pressable>
            <Pressable style={s.chip} onPress={() => setFrozen(Math.max(0.5, frozen - 0.5))}><Text style={s.chipText}>−</Text></Pressable>
            <Pressable style={s.chip} onPress={() => setFrozen(frozen + 0.5)}><Text style={s.chipText}>+</Text></Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

function NightOutRow({ n }: { n: NightOut }) {
  return (
    <View style={{ gap: 2 }}>
      <Text style={s.body}>{NIGHT_ICON[n.kind]} {NIGHT_NAME[n.kind]} <Text style={s.muted}>budget {money(n.budget)}
        {n.credit ? ` − ${money(n.credit)} ${n.credit_name}` : ""} · about {money(n.per_person)} each</Text></Text>
      {n.card ? <Text style={s.muted}>💳 Pay with {n.card_name}{n.rewards ? ` (${money(n.rewards)} back)` : ""}</Text> : null}
    </View>
  );
}

function DayEditor({ week, day, adult, me, busy, onNight, onAway }: { week: Week; day: string; adult: boolean; me: string;
  busy: string | null; onNight: (k: string) => void; onAway: (pid: string, away: boolean) => void }) {
  const night = week.plan.special_nights[day] ?? "cook";
  const away = new Set(week.away[day] ?? []);
  const people = Object.entries(week.people).filter(([pid]) => (week.home[pid] ?? DAYS).includes(day));
  return (
    <View style={{ gap: 8, borderTopWidth: 1, borderTopColor: c.line, paddingTop: 8 }}>
      {adult ? <Chips label={busy === `n${day}` ? "Changing…" : "Tonight"} multi={false} value={night}
        options={Object.keys(NIGHT_NAME).map((k) => ({ id: k, label: NIGHT_NAME[k] }))}
        onChange={([k]) => k !== night && onNight(k)} /> : null}
      <Text style={s.label}>Home for dinner</Text>
      <View style={s.wrap}>
        {people.map(([pid, name]) => {
          const home = !away.has(pid);
          const can = adult || pid === me;
          return (
            <Pressable key={pid} disabled={!can} onPress={() => onAway(pid, home)}
              accessibilityRole="checkbox" accessibilityState={{ checked: home }}
              style={[s.chip, home && { backgroundColor: c.greenSoft, borderColor: c.green }, !can && { opacity: 0.5 }]}>
              <Text style={[s.chipText, home && { color: c.green }]}>{home ? "✓ " : "✗ "}{name}</Text>
            </Pressable>
          );
        })}
      </View>
      {week.status === "approved" ? <Text style={s.muted}>The shopping's done, so dinner stays as planned; anything
        unused stays in the pantry for later.</Text> : <Text style={s.muted}>The plan and shopping list update right away.</Text>}
    </View>
  );
}
