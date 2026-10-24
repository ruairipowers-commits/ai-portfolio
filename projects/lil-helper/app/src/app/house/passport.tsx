// Your Household Food Passport: what any chef needs to cook safely for you, which chefs can see it, where each chef
// stands (talking, trial booked, working for you, paused, ended), and who has looked at your details. Your street
// and gate code go only to a chef with a trial booked or working for you — never with the passport itself.
import * as WebBrowser from "expo-web-browser";
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { Engagement, passport, pretty } from "@/lib/api";
import { Button, ErrorText, Field, Header, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

type Mine = Awaited<ReturnType<typeof passport.mine>>;
const STATUS: Record<string, string> = { inquiry: "talking", trial_scheduled: "trial booked", active: "working for you",
  paused: "paused", ended: "ended", declined: "declined" };

function EngagementRow({ e, granted, onDone, onError }: { e: Engagement; granted: boolean; onDone: (m: string) => void;
  onError: (x: unknown) => void }) {
  const [when, setWhen] = useState("");
  const go = (status: string, msg: string, at?: string) => async () => {
    try { const r = await passport.move(e.id, status, at); onDone(r.invited ? `${msg}: invitation sent` : msg); } catch (x) { onError(x); }
  };
  const share = async () => {
    try { granted ? await passport.revoke(e.chef_uid) : await passport.grant(e.chef_uid); onDone(granted ? "Passport no longer shared" : "Passport shared"); }
    catch (x) { onError(x); }
  };
  const open = !["ended", "declined"].includes(e.status);
  return (
    <View style={{ paddingVertical: 8, borderTopWidth: 1, borderTopColor: c.line, gap: 6 }}>
      <View style={s.between}>
        <Text style={[s.body, { fontWeight: "800" }]}>🧑‍🍳 {e.name}</Text>
        <Pill text={STATUS[e.status]} tone={e.status === "active" ? "green" : open ? "amber" : "red"} />
      </View>
      {e.trial_at ? <Text style={s.muted}>Trial: {e.trial_at.replace("T", " at ")}</Text> : null}
      <Text style={s.muted}>{["trial_scheduled", "active"].includes(e.status) ? "🔓 Can see your address and gate code" : "🔒 Can't see your address"}
        {" · "}{granted || ["trial_scheduled", "active"].includes(e.status) ? "can see your food passport" : "can't see your food passport"}</Text>
      {open ? (
        <View style={{ gap: 6 }}>
          {["inquiry"].includes(e.status) ? <View style={s.row}>
            <View style={{ flex: 1 }}><Field label="Trial (YYYY-MM-DDTHH:MM)" value={when} onChangeText={setWhen} placeholder="2026-11-03T16:00" /></View>
            <Button kind="ghost" title="Book trial" disabled={!when} onPress={go("trial_scheduled", "Trial booked", when)} />
          </View> : null}
          <View style={[s.row, { flexWrap: "wrap" }]}>
            {e.status !== "active" ? <Button kind="pro" title={e.status === "paused" ? "Resume" : "Hire"} onPress={go("active", "Hired")} /> : null}
            {e.status === "active" ? <Button kind="ghost" title="Pause" onPress={go("paused", "Paused")} /> : null}
            {e.status === "inquiry" ? <Button kind="ghost" title={granted ? "Stop sharing passport" : "Share food passport"} onPress={share} /> : null}
            <Button kind="ghost" title={e.status === "inquiry" ? "Decline" : "End"} onPress={go(e.status === "inquiry" ? "declined" : "ended", "Done")} />
          </View>
        </View>) : null}
    </View>
  );
}

export default function Passport() {
  const [d, setD] = useState<Mine | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { passport.mine().then((x) => { setD(x); setError(null); }).catch(setError); }, []);
  useEffect(() => { load(); }, [load]);
  const p = d?.passport;
  const granted = new Set((d?.grants ?? []).filter((g) => !g.revoked).map((g) => g.chef_uid));
  return (
    <Screen onRefresh={load}>
      <Header title="Food passport" />
      {p ? <View style={s.card}>
        <View style={s.between}><Text style={s.h2}>🛂 {p.household_name}</Text><Pill text={`v ${p.version.slice(0, 6)}`} tone="pro" /></View>
        {p.allergens.length ? <View style={s.wrap}>{p.allergens.map((a) => <Pill key={a} text={`no ${pretty(a).toLowerCase()}`} tone="red" />)}</View> : null}
        {p.people.map((x, i) => (
          <Text key={i} style={s.body}>{x.first_name}{x.child ? ` (child${x.age ? `, ${x.age}` : ""})` : ""}
            <Text style={s.muted}>{[x.allergies.length ? `allergies: ${x.allergies.map(pretty).join(", ")}` : "", x.diet.length ? x.diet.join(", ") : "",
              x.dislikes.length ? `won't eat ${x.dislikes.join(", ")}` : ""].filter(Boolean).map((t) => `  ·  ${t}`).join("")}</Text></Text>))}
        {Object.keys(p.brands).length ? <Text style={s.muted}>Brands: {Object.entries(p.brands).map(([k, v]) => `${k}: ${v}`).join(" · ")}</Text> : null}
        {p.kitchen_notes ? <Text style={s.muted}>Kitchen: {p.kitchen_notes}</Text> : null}
        <Text style={s.muted}>Your passport travels with you: share it with a chef you're talking to, or download it for any chef.</Text>
        <Button kind="ghost" title="⬇️ Download passport" onPress={async () => WebBrowser.openBrowserAsync(await passport.exportUrl())} />
      </View> : null}
      <View style={s.card}>
        <Text style={s.h2}>Chefs</Text>
        {d?.engagements.length ? d.engagements.map((e) => <EngagementRow key={e.id} e={e} granted={granted.has(e.chef_uid)}
          onDone={(m) => { setMsg(m); load(); }} onError={setError} />) : <Text style={s.muted}>No chefs yet. Accept a request in Find a chef to start talking.</Text>}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Who looked</Text>
        {d?.access_log.length ? d.access_log.slice(0, 20).map((a, i) => <Text key={i} style={s.muted}>{a.ts.slice(0, 16).replace("T", " ")} · {a.name} · {a.parts.replace(",", " and ")}</Text>)
          : <Text style={s.muted}>Nobody outside your household has opened your passport or address.</Text>}
      </View>
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
