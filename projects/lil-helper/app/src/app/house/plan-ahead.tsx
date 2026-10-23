// Make a plan: draft the coming weeks (up to three months) in one go, look them over, and stick to them. Each week
// can still be changed or approved on the Week tab; nothing is bought until a week is approved.
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { api } from "@/lib/api";
import { Button, Chips, ErrorText, Header, money, Pill, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function PlanAhead() {
  const [weeks, setWeeks] = useState(4);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.planAhead>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function go() {
    setBusy(true); setError(null);
    try { setRes(await api.planAhead(weeks)); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <Screen>
      <Header title="Make a plan" />
      <View style={s.card}>
        <Text style={s.body}>Plan the coming weeks now and stick with it. Weeks that already have a plan are kept as
          they are. Favourites, seasons, the freezer and your budget are all taken into account.</Text>
        <Chips label="How far ahead" multi={false} value={String(weeks)} onChange={([w]) => setWeeks(Number(w))}
          options={[{ id: "1", label: "1 week" }, { id: "2", label: "2 weeks" }, { id: "4", label: "A month" },
            { id: "8", label: "2 months" }, { id: "12", label: "3 months" }]} />
        <Button title={`Plan ${weeks === 1 ? "the week" : `${weeks} weeks`}`} busy={busy} onPress={go} />
      </View>
      {res?.weeks.map((w) => (
        <Pressable key={w.week_of} onPress={() => router.push({ pathname: "/plan", params: { week: w.week_of } } as never)}
          style={s.card} accessibilityRole="button">
          <View style={s.between}>
            <Text style={s.h2}>Week of {new Date(`${w.week_of}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</Text>
            <Pill text={w.status === "approved" ? "approved" : "draft"} tone={w.status === "approved" ? "green" : "amber"} />
          </View>
          <Text style={s.muted}>{w.dinners.join(" · ")}</Text>
          <Text style={s.body}>About {money(w.total)} of groceries ›</Text>
        </Pressable>
      ))}
      <ErrorText error={error} />
    </Screen>
  );
}
