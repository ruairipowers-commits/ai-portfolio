// A household as the chef may see it: the public card always; the food passport once the family shares it; the street,
// gate code and how to get in only while a trial is booked or you work for them. Propose a trial from here.
import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { passport, PassportView, pretty } from "@/lib/api";
import { Button, ErrorText, Field, Header, Pill, Screen } from "@/components/ui";
import { Hazard } from "@/components/chef";
import { c, s } from "@/lib/theme";

export default function ChefHousehold() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [v, setV] = useState<PassportView | null>(null);
  const [when, setWhen] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { passport.view(id).then((x) => { setV(x); setError(null); }).catch(setError); }, [id]);
  useEffect(() => { load(); }, [load]);
  const e = v?.engagement;
  const move = (status: string, ok: string, at?: string) => async () => {
    try { await passport.move(e!.id, status, at); setMsg(ok); load(); } catch (x) { setError(x); }
  };
  return (
    <Screen onRefresh={load}>
      <Header title={v?.passport?.household_name || `A household in ${v?.public.city ?? "your area"}`} />
      {e ? <Pill text={`status: ${e.status.replace("_", " ")}`} tone={e.status === "active" ? "green" : "amber"} /> : null}
      <View style={s.card}>
        <Text style={s.h2}>📍 {v?.public.city}{v?.public.state ? `, ${v.public.state}` : ""}</Text>
        {v?.location ? (
          <View style={{ gap: 2 }}>
            <Text style={s.body}>{v.location.street}{v.location.unit ? `, ${v.location.unit}` : ""}, {v.location.city} {v.location.state} {v.location.zip}</Text>
            {v.location.gate_code ? <Text style={s.body}>🔑 Gate / door code: <Text style={{ fontWeight: "900" }}>{v.location.gate_code}</Text></Text> : null}
            {v.location.access_notes ? <Text style={s.muted}>{v.location.access_notes}</Text> : null}
          </View>) : <Text style={s.muted}>🔒 The street and gate code appear once a trial is booked.</Text>}
      </View>
      {v?.passport ? (
        <View style={s.card}>
          <Text style={s.h2}>🛂 Food passport</Text>
          {v.passport.people.filter((p) => p.allergies.length).map((p) => <Hazard key={p.first_name} text={`${p.first_name}${p.child ? " (child)" : ""}: ${p.allergies.map(pretty).join(", ").toLowerCase()}`} />)}
          {v.passport.people.map((p, i) => <Text key={i} style={s.body}>{p.first_name}{p.child && p.age ? ` (${p.age})` : ""}
            <Text style={s.muted}>{p.likes.length ? `  ·  loves ${p.likes.join(", ")}` : ""}{p.dislikes.length ? `  ·  won't eat ${p.dislikes.join(", ")}` : ""}</Text></Text>)}
          {Object.keys(v.passport.brands).length ? <Text style={s.muted}>Brands: {Object.entries(v.passport.brands).map(([k, b]) => `${k}: ${b}`).join(" · ")}</Text> : null}
          {v.passport.kitchen_notes ? <Text style={s.muted}>Kitchen: {v.passport.kitchen_notes}</Text> : null}
        </View>) : <View style={s.card}><Text style={s.muted}>🔒 The family hasn't shared their food passport with you yet.</Text></View>}
      {e?.status === "inquiry" ? (
        <View style={[s.card, { backgroundColor: c.proSoft }]}>
          <Text style={s.h2}>Propose a trial</Text>
          <Field label="When (YYYY-MM-DDTHH:MM)" value={when} onChangeText={setWhen} placeholder="2026-11-03T16:00" />
          <Button kind="pro" title="Book the trial" disabled={!when} onPress={move("trial_scheduled", "Trial booked", when)} />
          <Button kind="ghost" title="Not a fit: decline" onPress={move("declined", "Declined")} />
        </View>) : null}
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
