// Meal style: hands-on minutes by day, recipe styles to prefer or require (one-pot Mondays, kid-friendly), kid chef
// nights, lunchboxes, and cooking a bit extra for tomorrow's lunch.
import { useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { DAY_SHORT, DAYS } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { AdminNote, Button, Chips, ErrorText, Header, NumberField, Saved, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

type Style = { prefer?: string[]; require?: string[] };

export default function MealStyle() {
  const set = useSettings();
  const { st, cat, isAdmin, role } = set;
  const [prep, setPrep] = useState<Record<string, number>>({});
  const [styles, setStyles] = useState<Record<string, Style>>({});
  const [kc, setKc] = useState<Record<string, string>>({});
  const [lunch, setLunch] = useState<{ days: string[]; eaters: string[] }>({ days: [], eaters: [] });
  const [left, setLeft] = useState<{ extra_portions: number; lunch?: { eaters: string[]; days: string[] } }>({ extra_portions: 0 });
  useEffect(() => {
    if (!set.view) return;
    setPrep(st.prep_minutes ?? {});
    setStyles(st.styles ?? {});
    setKc(st.kid_chef ?? {});
    const l = st.meals?.lunch;
    setLunch({ days: l?.days ?? [], eaters: Array.isArray(l?.eaters) ? l.eaters : [] });
    setLeft({ extra_portions: st.leftovers?.extra_portions ?? 0, lunch: st.leftovers?.lunch });
  }, [set.view?.version]);

  const people = Object.entries(st.people ?? {}) as [string, { name: string; age_band: string; age?: number }][];
  const kids = people.filter(([, p]) => p.age_band === "kid");
  const styleOpts = (cat?.styles ?? []).map((x) => ({ id: x, label: x.replace(/_/g, " ") }));
  const setStyle = (k: string, which: "prefer" | "require", v: string[]) => {
    const cur = { ...(styles[k] ?? {}), [which]: v };
    const n = { ...styles, [k]: cur };
    if (!cur.prefer?.length && !cur.require?.length) delete n[k];
    setStyles(n);
  };

  async function save() {
    const meals = { ...st.meals };
    if (lunch.days.length && lunch.eaters.length) meals.lunch = { ...(st.meals?.lunch ?? { label: "lunchbox" }), ...lunch };
    else delete meals.lunch;
    const lo = { extra_portions: left.extra_portions, ...(left.lunch?.days?.length && left.lunch?.eaters?.length ? { lunch: left.lunch } : {}) };
    for (const [k, v] of [["prep_minutes", prep], ["styles", styles], ["kid_chef", kc], ["meals", meals],
      ["leftovers", lo]] as const) {
      if (!(await set.save(k, v))) return;
    }
  }

  const dayOpts = DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }));
  return (
    <Screen>
      <Header title="Meal style" />
      <AdminNote role={role} />
      <View style={s.card}>
        <Text style={s.h2}>Hands-on time</Text>
        <Text style={s.muted}>The most minutes of chopping and stirring you want each night (simmering doesn't count).</Text>
        <View style={s.wrap}>
          {DAYS.map((d) => <View key={d} style={{ width: "48%" }}>
            <NumberField label={DAY_SHORT[d]} step={5} min={5} max={240} value={prep[d] ?? 60}
              onChange={(n) => setPrep({ ...prep, [d]: n })} /></View>)}
        </View>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Styles</Text>
        <Text style={s.muted}>Prefer: more likely. Require: only these (relaxed, with a note, if nothing fits).</Text>
        {DAYS.map((d) => (
          <View key={d} style={{ gap: 4 }}>
            <Chips label={`${DAY_SHORT[d]} — prefer`} options={styleOpts} value={styles[d]?.prefer ?? []} onChange={(v) => setStyle(d, "prefer", v)} />
            <Chips label={`${DAY_SHORT[d]} — require`} options={styleOpts} value={styles[d]?.require ?? []} onChange={(v) => setStyle(d, "require", v)} />
          </View>
        ))}
        <Chips label="Lunchboxes — prefer" options={styleOpts} value={styles.lunch?.prefer ?? []} onChange={(v) => setStyle("lunch", "prefer", v)} />
      </View>
      {kids.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Kid chef night</Text>
          <Text style={s.muted}>That child cooks dinner: only recipes marked easy enough for their age, with an adult nearby.</Text>
          {kids.map(([pid, p]) => (
            <Chips key={pid} label={`${p.name}${p.age ? ` (${p.age})` : ""}`} multi={false}
              options={[{ id: "", label: "No" }, ...dayOpts]}
              value={Object.entries(kc).find(([, v]) => v === pid)?.[0] ?? ""}
              onChange={([d]) => { const n = Object.fromEntries(Object.entries(kc).filter(([, v]) => v !== pid)); if (d) n[d] = pid; setKc(n); }} />
          ))}
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>Lunchboxes</Text>
        <Chips label="For" options={people.map(([id, p]) => ({ id, label: p.name }))} value={lunch.eaters}
          onChange={(eaters) => setLunch({ ...lunch, eaters })} />
        <Chips label="On" options={dayOpts} value={lunch.days} onChange={(days) => setLunch({ ...lunch, days })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Leftovers</Text>
        <Text style={s.muted}>Cook a bit more at dinner and take it for lunch the next day.</Text>
        <Chips label="Leftover lunch for" options={people.map(([id, p]) => ({ id, label: p.name }))}
          value={left.lunch?.eaters ?? []} onChange={(eaters) => setLeft({ ...left, lunch: { days: left.lunch?.days ?? [], eaters } })} />
        <Chips label="On" options={dayOpts} value={left.lunch?.days ?? []}
          onChange={(days) => setLeft({ ...left, lunch: { eaters: left.lunch?.eaters ?? [], days } })} />
        <NumberField label="Spare portions with every dinner" step={1} max={6} value={left.extra_portions}
          onChange={(extra_portions) => setLeft({ ...left, extra_portions })} />
      </View>
      {isAdmin ? <Button title="Save" busy={set.busy} onPress={save} /> : null}
      <Saved at={set.savedAt} />
      <ErrorText error={set.error} />
    </Screen>
  );
}
