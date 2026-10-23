// Your personal chef: what they left in the fridge (numbered containers, use-by), how to reheat each dish, and
// inviting your chef if they're not here yet. Free on every plan.
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { api, FamilyFridge, Me, pro } from "@/lib/api";
import { Button, ErrorText, Field, Header, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function ChefConnection() {
  const [f, setF] = useState<FamilyFridge | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { pro.fridge().then(setF).catch(setError); api.me().then(setMe).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);
  const admin = me?.current?.role === "admin";
  return (
    <Screen onRefresh={load}>
      <Header title="Your chef" />
      {f?.chefs.length ? <Text style={s.muted}>🧑‍🍳 {f.chefs.join(", ")} cooks for you{f.plan.via_chef ? " · Dinner Peace Family is free while they do" : ""}.</Text> : null}
      <View style={s.card}>
        <Text style={s.h2}>In the fridge</Text>
        {f?.containers.length ? f.containers.map((b) => {
          const card = f.cards.find((k) => k.id === b.card);
          return (
            <View key={b.id} style={{ paddingVertical: 8, borderTopWidth: 1, borderTopColor: c.line, gap: 4 }}>
              <View style={s.between}>
                <Text style={[s.body, { fontWeight: "800", flex: 1 }]}>#{b.number} · {b.dish}</Text>
                {b.warn ? <Pill text={b.warn} tone={b.days_left < 0 ? "red" : "amber"} /> : <Pill text={`${b.days_left} days left`} />}
              </View>
              <Text style={s.muted}>{b.portions} portions · {b.location} · use by {b.use_by}</Text>
              {card ? card.steps.map((st, i) => <Text key={i} style={s.body}>{i + 1}. {st}</Text>) : null}
              {card?.contains.length ? <Pill text={`Contains: ${card.contains.join(", ").replace(/_/g, " ")}`} tone="red" /> : null}
              <View style={s.row}>
                <Button kind="ghost" title="We ate it" onPress={async () => { await pro.fridgeDone(b.id, "eaten"); load(); }} />
                <Button kind="ghost" title="Tossed" onPress={async () => { await pro.fridgeDone(b.id, "tossed"); load(); }} />
              </View>
            </View>);
        }) : <Text style={s.muted}>Nothing logged yet. When your chef packs a container, it shows up here with how to reheat it.</Text>}
      </View>
      {f?.cards.filter((k) => !k.containers.length).map((k) => (
        <View key={k.id} style={s.card}>
          <Text style={s.h2}>🔥 {k.meal}</Text>
          {k.steps.map((st, i) => <Text key={i} style={s.body}>{i + 1}. {st}</Text>)}
        </View>))}
      {admin && !f?.chefs.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Invite your personal chef</Text>
          <Text style={s.muted}>They see your family's allergies, likes and brands, plan with you, and leave reheating
            instructions here. They need Dinner Peace Pro; you don't pay anything extra.</Text>
          <Field label="Their email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />
          <Button title="Send invitation" disabled={!email.includes("@")} onPress={async () => {
            try { await pro.inviteChef(email.trim()); setMsg(`Invitation sent to ${email.trim()}`); setEmail(""); } catch (e) { setError(e); }
          }} />
        </View>) : null}
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
