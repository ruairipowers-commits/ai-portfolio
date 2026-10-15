// Today: the home screen. What's next for me (the next meal, my jobs, the shopping), what needs an answer, what's
// coming up, and a microphone to ask anything. Kept short on purpose: everything else is a tap away.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, ApiError, JOB_NAME, Today, TodayTask } from "@/lib/api";
import { Button, ErrorText, Pill, Screen } from "@/components/ui";
import { VoiceBar } from "@/components/voice";
import { WayTiles } from "@/components/ways";
import { c, s } from "@/lib/theme";

const JOB_ICON: Record<string, string> = { cook: "👩‍🍳", dishes: "🍽️", set_table: "🍴", kid_assistant: "🧒",
  feed_dog: "🐕" };
const MEAL_ICON: Record<string, string> = { breakfast: "🥣", lunch: "🥪", dinner: "🍲" };
const TASK_ICON: Record<string, string> = { confirm: "💬", shop: "🛒", approve: "✅", buffet: "🥣", job: "🧽" };

function hello(name: string) {
  const h = new Date().getHours();
  return `${h < 12 ? "Good morning" : h < 17 ? "Hi" : "Good evening"}, ${name.split(" ")[0]}`;
}

function nextMeal(meals: Today["meals"]) {
  const now = new Date();
  const mins = now.getHours() * 60 + now.getMinutes();
  const at = (t: string) => { const [h, m] = (t || "18:00").split(":").map(Number); return h * 60 + (m || 0); };
  return meals.find((m) => at(m.time) + 60 >= mins) ?? null;
}

export default function TodayScreen() {
  const [t, setT] = useState<Today | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try { setT(await api.today()); setError(null); }
    catch (e) { if (!(e instanceof ApiError && e.status === 409)) setError(e); }
    finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const next = t ? nextMeal(t.meals) : null;
  const date = t ? new Date(`${t.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) : "";
  const open = (task: TodayTask) => {
    if (task.kind === "confirm") router.push({ pathname: "/plan", params: { day: task.day ?? "" } } as never);
    else if (task.kind === "shop") router.push("/shopping" as never);
    else if (task.kind === "approve") router.push({ pathname: "/plan", params: task.week ? { week: task.week } : {} } as never);
    else if (task.kind === "buffet") router.push("/house/buffet" as never);
    else router.push("/jobs" as never);
  };
  return (
    <Screen refreshing={loading} onRefresh={load}>
      <View>
        <Text style={[s.h1, { fontSize: 28 }]}>{t ? hello(t.my_name) : "Today"} 👋</Text>
        <Text style={s.muted}>{date}</Text>
      </View>
      {t?.birthday ? (
        <View style={[s.card, { backgroundColor: "#FDE7E3", borderColor: c.red, alignItems: "center" }]}>
          <Text style={{ fontSize: 36 }}>🎂🎈</Text>
          <Text style={s.h2}>Happy birthday!</Text>
          <Text style={s.body}>No jobs for you today.</Text>
        </View>
      ) : null}

      {next ? (
        <Pressable onPress={() => router.push({ pathname: "/house/recipe", params: { id: next.recipe } } as never)}
          style={[s.card, { backgroundColor: c.greenSoft, borderColor: c.green, padding: 18 }]}
          accessibilityRole="button" accessibilityLabel={`Up next: ${next.name}. Open the recipe`}>
          <Text style={s.label}>Up next · {next.meal} {next.time ? `at ${next.time}` : ""}</Text>
          <Text style={[s.h1, { fontSize: 26 }]}>{MEAL_ICON[next.meal] ?? "🍽️"} {next.name}</Text>
          <View style={[s.row, { flexWrap: "wrap" }]}>
            {next.cook ? <Pill text={`${next.cook} cooks`} /> : null}
            {next.kind && next.kind !== "cook" ? <Pill text={next.kind === "leftovers" ? "leftovers" : "from the freezer"} tone="amber" /> : null}
            {next.active ? <Pill text={`${next.active} min hands-on`} tone="amber" /> : null}
          </View>
          {next.parts.filter((p) => p.kind !== "cook").map((p, i) => (
            <Text key={i} style={s.muted}>{p.kind === "leftovers" ? "🥡" : "🥫"} {p.name ?? p.food} for {p.eaters?.length ?? 0}</Text>))}
          <Text style={{ color: c.green, fontWeight: "700" }}>See the recipe ›</Text>
        </Pressable>
      ) : t && !t.meals.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Nothing planned today</Text>
          <Text style={s.muted}>Pick a way below, or plan the week.</Text>
          {t.role !== "kid" ? <Button title="Plan the week" onPress={() => router.push("/plan" as never)} /> : null}
        </View>
      ) : null}

      {t && t.my_jobs.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Your jobs</Text>
          <View style={s.wrap}>
            {t.my_jobs.map((j, i) => (
              <Pressable key={i} onPress={() => open(j)} style={[s.chip, { paddingVertical: 10 }]}>
                <Text style={s.chipText}>{j.kind === "job" ? `${JOB_ICON[j.job ?? ""] ?? "🧽"} ${JOB_NAME[j.job ?? ""] ?? j.text}` : `${TASK_ICON[j.kind]} ${j.text}`}</Text>
              </Pressable>))}
          </View>
        </View>
      ) : null}

      {t && t.tasks.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Needs an answer</Text>
          {t.tasks.map((task, i) => (
            <Pressable key={i} onPress={() => open(task)} style={[s.between, { paddingVertical: 6 }]} accessibilityRole="button">
              <Text style={[s.body, { flex: 1 }]}>{TASK_ICON[task.kind] ?? "•"} {task.text}</Text>
              <Text style={[s.muted, { fontSize: 18 }]}>›</Text>
            </Pressable>))}
        </View>
      ) : null}

      <VoiceBar />

      {t && t.everyone.filter((p) => p.person !== t.me).length ? (
        <View style={s.card}>
          <Text style={s.h2}>Everyone today</Text>
          {t.everyone.filter((p) => p.person !== t.me).map((p) => (
            <Text key={p.person} style={s.body}>{p.name} <Text style={s.muted}>
              {p.jobs.map((j) => j.kind === "job" ? `${JOB_ICON[j.job ?? ""] ?? ""} ${JOB_NAME[j.job ?? ""] ?? j.text}` : j.text).join(" · ")}</Text></Text>))}
        </View>
      ) : null}

      {t && t.occasions.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Coming up</Text>
          {t.occasions.map((o) => (
            <Pressable key={o.id + o.date} onPress={() => router.push({ pathname: "/house/occasions", params: { focus: o.id, date: o.date } } as never)}
              style={[s.between, { paddingVertical: 4 }]}>
              <Text style={s.body}>{o.kind === "birthday" ? "🎂" : o.kind === "holiday" ? "🎊" : o.kind === "anniversary" ? "💕" : "🎉"} {o.name}</Text>
              <Text style={s.muted}>{new Date(`${o.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} ›</Text>
            </Pressable>))}
        </View>
      ) : null}

      <Text style={[s.label, { marginTop: 4 }]}>What shall we eat?</Text>
      <WayTiles compact />
      <ErrorText error={error} />
    </Screen>
  );
}
