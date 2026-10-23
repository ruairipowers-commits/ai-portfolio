// Shopping for the next visits. Solo: each home's list. Studio: one trip across homes — the stops, each checkout and
// the card to pay with, bulk lines split by home — then mark each checkout paid to put it on the ledger.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { ChefShopping, Checkout, pro, Trip } from "@/lib/api";
import { Button, Chips, ErrorText, money, Pill, Screen } from "@/components/ui";
import { ProBadge } from "@/components/chef";
import { c, s } from "@/lib/theme";

function CheckoutCard({ co, store, trip, onPaid }: { co: Checkout; store: string; trip?: Trip; onPaid?: () => void }) {
  const [open, setOpen] = useState(false);
  const chef = co.paid_by === "chef";
  return (
    <View style={{ borderTopWidth: 1, borderTopColor: c.line, paddingTop: 8, gap: 6 }}>
      <Pressable onPress={() => setOpen(!open)} style={s.between} accessibilityRole="button">
        <View style={{ flex: 1 }}>
          <Text style={[s.body, { fontWeight: "800" }]}>{chef ? `💳 ${co.card_name}` : `🏦 ${co.household_name}'s card`}</Text>
          <Text style={s.muted}>{chef ? `${co.card_note}${co.rewards ? ` · earns ${money(co.rewards)}` : ""}` : "Separate checkout"}
            {" · "}{co.lines.length} items</Text>
        </View>
        <Text style={s.h2}>{money(co.total)} {open ? "▾" : "▸"}</Text>
      </Pressable>
      <View style={[s.row, { flexWrap: "wrap" }]}>
        {co.per_home.map((h) => <Pill key={h.household_id} tone="pro" text={`${h.name}: ${money(h.amount)}`} />)}
      </View>
      {open ? co.lines.map((ln) => (
        <View key={ln.ingredient + ln.brand} style={{ paddingVertical: 3 }}>
          <View style={s.between}>
            <Text style={[s.body, { flex: 1 }]}>{ln.packs} × {ln.name} <Text style={s.muted}>({ln.brand}, {ln.pack} {ln.unit})</Text></Text>
            <Text style={s.body}>{money(ln.cost)}</Text>
          </View>
          {ln.bulk || ln.shares.length > 1 ? <Text style={[s.muted, { color: c.pro }]}>
            {ln.bulk ? "Bulk split: " : "Split: "}{ln.shares.map((x) => `${x.name} ${x.pct}% (${money(x.cost)})`).join(" · ")}</Text> : null}
        </View>)) : null}
      {trip?.id && !co.recorded ? (
        <Button kind="ghost" title={chef ? "Paid: add to the ledger" : "Done: they paid"} onPress={async () => {
          await pro.paid(trip.id!, { store, paid_by: co.paid_by, household_id: co.household_id }); onPaid?.();
        }} />) : co.recorded ? <Pill text={`Recorded ${money(co.actual ?? co.total)}`} /> : null}
    </View>
  );
}

export default function ChefShop() {
  const [days, setDays] = useState("3");
  const [d, setD] = useState<ChefShopping | null>(null);
  const [trip, setTrip] = useState<Trip | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (n = Number(days)) => {
    setBusy(true);
    try { setD(await pro.shopping(n)); setError(null); } catch (e) { setError(e); } finally { setBusy(false); }
  }, [days]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const t = trip ?? d?.trip ?? null;
  async function start() {
    setBusy(true);
    try { setTrip(await pro.saveTrip(Number(days))); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function refreshTrip() { if (trip?.id) setTrip(await pro.trip(trip.id)); }
  return (
    <Screen refreshing={busy} onRefresh={() => load()}>
      <View style={s.between}>
        <Text style={s.h1}>Shopping run</Text>
        {d ? <ProBadge text={d.studio ? "ONE TRIP" : "PER HOME"} /> : null}
      </View>
      <Chips options={[{ id: "1", label: "Today" }, { id: "2", label: "2 days" }, { id: "3", label: "3 days" }, { id: "7", label: "A week" }]}
        value={days} multi={false} onChange={(v) => { setDays(v[0]); setTrip(null); load(Number(v[0])); }} />
      {t ? (
        <>
          <View style={[s.card, { backgroundColor: c.proSoft, borderColor: "#E5DFD6" }]}>
            <Text style={[s.label, { color: c.pro }]}>{trip?.id ? "Trip started" : "Proposed route"}</Text>
            <Text style={s.h2}>{t.stops.length} {t.stops.length === 1 ? "stop" : "stops"} · {money(t.total)} · about {t.minutes} min</Text>
            <Text style={s.body}>Rewards on your cards: <Text style={{ fontWeight: "800" }}>{money(t.rewards)}</Text>
              {t.bulk_lines ? ` · ${t.bulk_lines} bulk ${t.bulk_lines === 1 ? "line" : "lines"} split between homes` : ""}</Text>
            <View style={[s.row, { flexWrap: "wrap" }]}>
              {t.homes.map((h) => <Pill key={h.household_id} tone="pro" text={`${h.name}: ${money(h.amount)}${h.billing === "client_card_on_file" ? " (their card)" : ""}`} />)}
            </View>
            {t.flags.map((f) => <Text key={f} style={s.muted}>⚠️ {f}</Text>)}
            {!trip?.id ? <Button kind="pro" title="Start this trip" onPress={start} busy={busy} /> : null}
          </View>
          {t.stops.map((st, i) => (
            <View key={st.store} style={s.card}>
              <View style={s.between}>
                <Text style={s.h2}>{i + 1}. {st.store_name}</Text>
                <Text style={s.muted}>{money(st.total)}</Text>
              </View>
              {st.checkouts.map((co, j) => <CheckoutCard key={j} co={co} store={st.store} trip={trip ?? undefined} onPaid={refreshTrip} />)}
            </View>))}
          {trip?.id ? <Button kind="ghost" title="See the ledger" onPress={() => router.push("/chef/ledger" as never)} /> : null}
        </>) : null}
      {d && !d.studio ? (
        <>
          {d.per_home.map((h) => (
            <View key={h.household_id} style={s.card}>
              <Text style={s.h2}>{h.name}</Text>
              <Text style={s.muted}>Visits {h.visits.join(", ")}</Text>
              {h.items.map((it, i) => <Text key={i} style={s.body}>• {it.qty} {it.unit} {it.name}{it.brand ? <Text style={{ color: c.pro, fontWeight: "800" }}> ({it.brand})</Text> : null}</Text>)}
            </View>))}
          <View style={[s.card, { backgroundColor: c.proSoft }]}>
            <Text style={s.body}>Chef Studio turns these into one trip: lines merged across homes, bulk packs split by home, and the best card at each stop.</Text>
            <Button kind="pro" title="See Chef Studio" onPress={() => router.push({ pathname: "/plans", params: { focus: "chef_studio" } } as never)} />
          </View>
        </>) : null}
      {d && !d.per_home.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Nothing to buy</Text>
          <Text style={s.muted}>No planned meals for your next visits, or their pantries cover them. Set visit days and plan their weeks.</Text>
        </View>) : null}
      <ErrorText error={error} />
    </Screen>
  );
}
