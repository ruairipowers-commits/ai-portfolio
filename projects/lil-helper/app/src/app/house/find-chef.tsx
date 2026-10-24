// Find a chef: let chefs nearby know you're looking (and what you'd pay), search chefs near your home, ask to meet,
// hire after meeting, and switch chefs. Chefs only see your town, how many people and children (no names), the
// allergens to cook around, and your note — until you accept a request.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { Listing, PublicChef, pretty, v6 } from "@/lib/api";
import { Button, Chips, Pair, ErrorText, Field, Header, money, NumberField, Pill, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

type Reqs = Awaited<ReturnType<typeof v6.householdRequests>>["requests"];

function ChefCard({ x, onAsk }: { x: PublicChef; onAsk: (msg: string) => void }) {
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState(false);
  return (
    <View style={s.card}>
      <View style={s.between}>
        <View style={{ flex: 1 }}>
          <Text style={s.h2}>🧑‍🍳 {x.name}{x.business ? <Text style={s.muted}> · {x.business}</Text> : null}</Text>
          <Text style={s.muted}>{x.place}{x.miles != null ? ` · about ${x.miles} mi` : ""}</Text>
        </View>
        {x.your_chef ? <Pill text="your chef" /> : x.full ? <Pill text="fully booked" tone="amber" /> : null}
      </View>
      {x.bio ? <Text style={s.body}>{x.bio}</Text> : null}
      <View style={s.wrap}>{x.cuisines.map((k) => <Pill key={k} text={pretty(k)} tone="pro" />)}</View>
      <Text style={s.body}>{[x.rate_per_visit != null ? `${money(x.rate_per_visit)} a visit` : "", x.rate_hourly != null ? `${money(x.rate_hourly)} an hour` : ""].filter(Boolean).join(" · ") || "Rates on request"}</Text>
      {x.request ? <Pill text={`request ${x.request}`} tone={x.request === "accepted" ? "green" : "amber"} /> : !x.your_chef ? (
        open ? <View style={{ gap: 6 }}>
          <Field label="Message" value={msg} onChangeText={setMsg} multiline placeholder="Hi! We're a family of four looking for two dinners a week…" />
          <Button kind="pro" title="Ask to meet" disabled={!msg.trim()} onPress={() => onAsk(msg.trim())} />
        </View> : <Button kind="ghost" title="Ask to meet" onPress={() => setOpen(true)} />) : null}
    </View>
  );
}

export default function FindChef() {
  const [lst, setLst] = useState<Listing | null>(null);
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof v6.listing>>["preview"] | null>(null);
  const [cuisines, setCuisines] = useState<string[]>([]);
  const [hasAddr, setHasAddr] = useState(true);
  const [radius, setRadius] = useState("25");
  const [chefs, setChefs] = useState<PublicChef[] | null>(null);
  const [place, setPlace] = useState("");
  const [reqs, setReqs] = useState<Reqs>([]);
  const [mine, setMine] = useState<{ uid: string; name: string; email: string }[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    v6.listing().then((r) => { setLst(r.listing); setPreview(r.preview); setCuisines(r.cuisines); setHasAddr(r.has_address); }).catch(setError);
    v6.householdRequests().then((r) => setReqs(r.requests)).catch(() => {});
    v6.myChefs().then((r) => setMine(r.chefs)).catch(() => {});
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const search = async (r = radius) => {
    setError(null);
    try { const x = await v6.findChefs(Number(r)); setChefs(x.chefs); setPlace(x.place); } catch (e) { setError(e); }
  };
  const act = (fn: () => Promise<unknown>, ok: string) => async () => {
    setError(null); setMsg(null);
    try { await fn(); setMsg(ok); load(); if (chefs) search(); } catch (e) { setError(e); }
  };
  const set = (p: Partial<Listing>) => setLst({ ...(lst as Listing), ...p });
  return (
    <Screen onRefresh={load}>
      <Header title="Find a chef" />
      {!hasAddr ? <View style={[s.card, { backgroundColor: c.proSoft }]}>
        <Text style={s.body}>Add your home address first, so we can find chefs who travel to you.</Text>
        <Button kind="pro" title="Add your address" onPress={() => router.push("/house/address" as never)} />
      </View> : null}
      {mine.length ? <View style={s.card}>
        <Text style={s.h2}>Your chef</Text>
        {mine.map((m) => (
          <View key={m.uid} style={s.between}>
            <Text style={s.body}>🧑‍🍳 {m.name} <Text style={s.muted}>{m.email}</Text></Text>
            <Button kind="ghost" title="Stop working with" onPress={act(() => v6.removeChef(m.uid), `${m.name} no longer has access`)} />
          </View>))}
        <Text style={s.muted}>Switching is fine: hire your new chef below, then stop working with the old one. What they
          logged stays in your fridge list.</Text>
      </View> : null}
      {lst ? <View style={s.card}>
        <Text style={s.h2}>Let chefs know you're looking</Text>
        <Toggle label="We're looking for a personal chef" value={lst.open} onChange={(v) => set({ open: v })} />
        <Pair>
          <NumberField label="Willing to pay a week" prefix="$" step={25} max={10000} value={lst.budget_per_week ?? 0} onChange={(n) => set({ budget_per_week: n || null })} />
          <NumberField label="…or a visit" prefix="$" step={25} max={5000} value={lst.budget_per_visit ?? 0} onChange={(n) => set({ budget_per_visit: n || null })} />
        </Pair>
        <NumberField label="Visits a week" step={1} min={1} max={7} value={lst.visits_per_week ?? 1} onChange={(n) => set({ visits_per_week: n })} />
        <Chips label="Food you like" value={lst.cuisines} options={cuisines.map((k) => ({ id: k, label: pretty(k) }))} onChange={(v) => set({ cuisines: v })} />
        <Field label="A note for chefs" value={lst.note} onChangeText={(v) => set({ note: v })} multiline placeholder="Two weeknight dinners, kid-friendly, we have a dog" />
        {preview ? <Text style={s.muted}>Chefs will see: {preview.place || "your town"} · {preview.people} people ({preview.kids} {preview.kids === 1 ? "child" : "children"})
          {preview.allergens.length ? ` · avoid ${preview.allergens.map(pretty).join(", ").toLowerCase()}` : ""}. No names, no street.</Text> : null}
        <Button kind="pro" title="Save" onPress={act(() => v6.saveListing(lst), "Saved")} />
      </View> : null}
      {reqs.length ? <View style={s.card}>
        <Text style={s.h2}>Requests</Text>
        {reqs.map((r) => (
          <View key={r.id} style={{ paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line, gap: 4 }}>
            <View style={s.between}>
              <Text style={[s.body, { fontWeight: "800" }]}>{r.from_kind === "chef" ? "From" : "To"} {r.chef.name || "a chef"}</Text>
              <Pill text={r.status} tone={r.status === "accepted" ? "green" : r.status === "pending" ? "amber" : "red"} />
            </View>
            <Text style={s.muted}>“{r.message}”</Text>
            {r.contact ? <Text style={s.body}>✉️ {r.contact.name} · {r.contact.email}</Text> : null}
            {r.status === "pending" && r.from_kind === "chef" ? <View style={s.row}>
              <Button kind="pro" title="Accept and share contacts" onPress={act(() => v6.respond(r.id, true), "Accepted")} />
              <Button kind="ghost" title="Decline" onPress={act(() => v6.respond(r.id, false), "Declined")} />
            </View> : null}
            {r.status === "pending" && r.from_kind === "household" ? <Button kind="ghost" title="Withdraw" onPress={act(() => v6.withdraw(r.id), "Withdrawn")} /> : null}
            {r.status === "accepted" ? <Button kind="ghost" title="Trial, hiring and your food passport ›" onPress={() => router.push("/house/passport" as never)} /> : null}
          </View>))}
      </View> : null}
      <View style={s.card}>
        <Text style={s.h2}>Chefs near {place || "you"}</Text>
        <Chips multi={false} value={radius} options={[{ id: "10", label: "10 mi" }, { id: "25", label: "25 mi" }, { id: "50", label: "50 mi" }]}
          onChange={(v) => { setRadius(v[0]); search(v[0]); }} />
        <Button title="Search" onPress={() => search()} disabled={!hasAddr} />
      </View>
      {chefs?.map((x) => <ChefCard key={x.uid} x={x} onAsk={(m) => act(() => v6.askChef(x.uid, m), "Request sent")()} />)}
      {chefs && !chefs.length ? <Text style={s.muted}>No chefs listed within {radius} miles yet.</Text> : null}
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
