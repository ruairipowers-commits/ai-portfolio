// Jobs: who cooks, does dishes, sets the table, helps in the kitchen and feeds the dog, by day. Tap a name to hand
// the job to someone else who can do it (the server checks ages and who's home).
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, Chore, DAY_NAME, DAYS, Household, JOB_NAME } from "@/lib/api";
import { useWeek } from "@/lib/useWeek";
import { ErrorText, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function Jobs() {
  const { week, error, setError, loading, reload } = useWeek();
  const [hh, setHh] = useState<Household | null>(null);
  const [chores, setChores] = useState<Chore[]>([]);
  useEffect(() => { api.household().then(setHh).catch(() => {}); }, []);
  useEffect(() => { setChores(week?.chores ?? []); }, [week]);

  async function next(a: Chore) {
    if (!hh) return;
    const ids = hh.people.map((p) => p.id);
    for (let i = 1; i < ids.length; i++) {                // try the next person round; the server says who can
      const pid = ids[(ids.indexOf(a.person) + i) % ids.length];
      try { setChores((await api.swapJob(a.day, a.job, pid)).chores); setError(null); return; } catch {}
    }
    setError(new Error(`Nobody else can do ${JOB_NAME[a.job] ?? a.job} on ${DAY_NAME[a.day]}`));
  }

  const load: Record<string, number> = {};
  for (const a of chores) load[a.name] = (load[a.name] ?? 0) + (a.job === "cook" ? 3 : a.job === "dishes" ? 2 : 1);

  return (
    <Screen refreshing={loading} onRefresh={reload}>
      <Text style={s.h1}>Jobs</Text>
      {!week ? <Text style={s.muted}>Jobs appear when there's a plan for the week.</Text> : null}
      {Object.keys(load).length ? (
        <View style={[s.card, s.row, { flexWrap: "wrap" }]}>
          {Object.entries(load).map(([n, v]) => <Text key={n} style={s.body}>{n} <Text style={s.muted}>{v}</Text>   </Text>)}
          <Text style={s.muted}>(cook 3, dishes 2, others 1 — evened out over four weeks)</Text>
        </View>
      ) : null}
      {DAYS.map((d) => {
        const today = chores.filter((a) => a.day === d);
        if (!today.length) return null;
        return (
          <View key={d} style={s.card}>
            <Text style={s.h2}>{DAY_NAME[d]}</Text>
            {today.map((a) => (
              <View key={a.job} style={s.between}>
                <Text style={s.body}>{JOB_NAME[a.job] ?? a.job}</Text>
                <Pressable onPress={() => next(a)} style={[s.ghost, { paddingVertical: 6, minWidth: 90 }]}
                  accessibilityLabel={`${JOB_NAME[a.job]} on ${DAY_NAME[d]}: ${a.name}. Tap to change`}>
                  <Text style={[s.ghostText, { color: c.ink }]}>{a.name} ↻</Text>
                </Pressable>
              </View>
            ))}
          </View>
        );
      })}
      <ErrorText error={error} />
    </Screen>
  );
}
