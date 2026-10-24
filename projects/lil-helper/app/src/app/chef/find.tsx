// Find households (Dinner Peace Pro): your public chef profile, households near you that are looking for a chef and
// what they'd pay, requests to meet, and replies. You see a household's town, size and allergens — names and
// contacts only after they accept.
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { ChefProfile, PublicHousehold, pretty, v6 } from "@/lib/api";
import { Button, Chips, Pair, ErrorText, Field, Header, money, NumberField, Pill, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

type Reqs = Awaited<ReturnType<typeof v6.chefRequests>>["requests"];

function HomeCard({ x, onAsk }: { x: PublicHousehold; onAsk: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  return (
    <View style={s.card}>
      <View style={s.between}>
        <Text style={s.h2}>🏡 {x.place || "Nearby"}{x.miles != null ? <Text style={s.muted}> · about {x.miles} mi</Text> : null}</Text>
        {x.request ? <Pill text={`request ${x.request}`} tone={x.request === "accepted" ? "green" : "amber"} /> : null}
      </View>
      <Text style={s.body}>{x.people} people{x.kids ? ` (${x.kids} ${x.kids === 1 ? "child" : "children"})` : ""}
        {x.visits_per_week ? ` · ${x.visits_per_week} visit${x.visits_per_week > 1 ? "s" : ""} a week` : ""}</Text>
      <Text style={[s.body, { fontWeight: "800", color: c.pro }]}>{[x.budget_per_week ? `${money(x.budget_per_week)} a week` : "",
        x.budget_per_visit ? `${money(x.budget_per_visit)} a visit` : ""].filter(Boolean).join(" · ") || "Budget not stated"}</Text>
      {x.allergens.length ? <View style={s.wrap}>{x.allergens.map((a) => <Pill key={a} text={`no ${pretty(a).toLowerCase()}`} tone="red" />)}</View> : null}
      {x.cuisines.length ? <View style={s.wrap}>{x.cuisines.map((k) => <Pill key={k} text={pretty(k)} tone="pro" />)}</View> : null}
      {x.note ? <Text style={s.muted}>“{x.note}”</Text> : null}
      {!x.request ? (open ? <View style={{ gap: 6 }}>
        <Field label="Message" value={msg} onChangeText={setMsg} multiline placeholder="Hi! I'm a personal chef in town…" />
        <Button kind="pro" title="Send invite to meet" disabled={!msg.trim()} onPress={() => onAsk(msg.trim())} />
      </View> : <Button kind="ghost" title="Invite to meet" onPress={() => setOpen(true)} />) : null}
    </View>
  );
}

export default function FindHouseholds() {
  const [p, setP] = useState<ChefProfile | null>(null);
  const [cuisines, setCuisines] = useState<string[]>([]);
  const [homes, setHomes] = useState<PublicHousehold[] | null>(null);
  const [radius, setRadius] = useState("25");
  const [reqs, setReqs] = useState<Reqs>([]);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    v6.profile().then((r) => { setP(r.profile); setCuisines(r.cuisines); }).catch(setError);
    v6.chefRequests().then((r) => setReqs(r.requests)).catch(() => {});
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const search = async (r = radius) => {
    setError(null);
    try { setHomes((await v6.findHouseholds(Number(r))).households); } catch (e) { setError(e); }
  };
  const act = (fn: () => Promise<unknown>, ok: string) => async () => {
    setError(null); setMsg(null);
    try { await fn(); setMsg(ok); load(); if (homes) search(); } catch (e) { setError(e); }
  };
  const set = (x: Partial<ChefProfile>) => setP({ ...(p as ChefProfile), ...x });
  const addr = p?.address ?? {};
  return (
    <Screen onRefresh={load}>
      <Header title="Find households" />
      {p ? <View style={s.card}>
        <Text style={s.h2}>Your chef profile</Text>
        <Toggle label="Listed: families nearby can find me" value={p.listed} onChange={(v) => set({ listed: v })} />
        <Toggle label="Taking new clients" value={p.accepting} onChange={(v) => set({ accepting: v })} />
        <Field label="Name families see" value={p.display_name} onChangeText={(v) => set({ display_name: v })} />
        <Field label="Business" value={p.business ?? ""} onChangeText={(v) => set({ business: v })} />
        <Field label="About you" value={p.bio ?? ""} onChangeText={(v) => set({ bio: v })} multiline />
        <Chips label="What you cook" value={p.cuisines} options={cuisines.map((k) => ({ id: k, label: pretty(k) }))} onChange={(v) => set({ cuisines: v })} />
        <Pair>
          <NumberField label="Rate a visit" prefix="$" step={25} max={5000} value={p.rate_per_visit ?? 0} onChange={(n) => set({ rate_per_visit: n || null })} />
          <NumberField label="…or an hour" prefix="$" step={5} max={1000} value={p.rate_hourly ?? 0} onChange={(n) => set({ rate_hourly: n || null })} />
        </Pair>
        <View style={s.row}>
          <View style={{ flex: 1 }}><Field label="Town" value={addr.city ?? ""} onChangeText={(v) => set({ address: { ...addr, city: v, lat: undefined, lon: undefined } })} /></View>
          <View style={{ width: 70 }}><Field label="State" value={addr.state ?? ""} maxLength={2} onChangeText={(v) => set({ address: { ...addr, state: v.toUpperCase() } })} /></View>
          <View style={{ width: 100 }}><Field label="ZIP" value={addr.zip ?? ""} maxLength={5} onChangeText={(v) => set({ address: { ...addr, zip: v, lat: undefined, lon: undefined } })} /></View>
        </View>
        <NumberField label="How far you'll travel (miles)" step={5} min={1} max={100} value={p.radius_miles} onChange={(n) => set({ radius_miles: n })} />
        <Button kind="pro" title="Save profile" onPress={act(() => v6.saveProfile(p), "Profile saved")} />
      </View> : null}
      {reqs.length ? <View style={s.card}>
        <Text style={s.h2}>Requests</Text>
        {reqs.map((r) => (
          <View key={r.id} style={{ paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line, gap: 4 }}>
            <View style={s.between}>
              <Text style={[s.body, { fontWeight: "800" }]}>{r.from_kind === "household" ? "From" : "To"} a household in {r.household?.place || "your area"}</Text>
              <Pill text={r.status} tone={r.status === "accepted" ? "green" : r.status === "pending" ? "amber" : "red"} />
            </View>
            <Text style={s.muted}>“{r.message}”</Text>
            {r.contact ? <Text style={s.body}>✉️ {r.contact.household}: {r.contact.name} · {r.contact.email}</Text> : null}
            {r.status === "pending" && r.from_kind === "household" ? <View style={s.row}>
              <Button kind="pro" title="Accept and share contacts" onPress={act(() => v6.respond(r.id, true), "Accepted")} />
              <Button kind="ghost" title="Decline" onPress={act(() => v6.respond(r.id, false), "Declined")} />
            </View> : null}
            {r.status === "pending" && r.from_kind === "chef" ? <Button kind="ghost" title="Withdraw" onPress={act(() => v6.withdraw(r.id), "Withdrawn")} /> : null}
          </View>))}
      </View> : null}
      <View style={s.card}>
        <Text style={s.h2}>Households looking for a chef</Text>
        <Chips multi={false} value={radius} options={[{ id: "10", label: "10 mi" }, { id: "25", label: "25 mi" }, { id: "50", label: "50 mi" }]}
          onChange={(v) => { setRadius(v[0]); search(v[0]); }} />
        <Button kind="pro" title="Search" onPress={() => search()} />
      </View>
      {homes?.map((x) => <HomeCard key={x.household_id} x={x} onAsk={(m) => act(() => v6.askHousehold(x.household_id!, m), "Invitation sent")()} />)}
      {homes && !homes.length ? <Text style={s.muted}>No households looking within {radius} miles yet.</Text> : null}
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
