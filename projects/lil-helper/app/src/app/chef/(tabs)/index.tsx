// "What do I do next?": today's priority kitchen, its next step and hazards, the next store stop and which card to
// use, then the rest of today's homes and the week ahead. One glance between kitchens; everything else is a tap away.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, ScrollView, useWindowDimensions, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Text } from "@/components/text";
import { Cockpit, DAY_SHORT, Kitchen, pro } from "@/lib/api";
import { Button, ErrorText, money, Pill } from "@/components/ui";
import { clock, greet, Hazard, ProBadge, VoiceFab } from "@/components/chef";
import { c, s, shadow } from "@/lib/theme";

function Hero({ k }: { k: Kitchen }) {
  const open = () => router.push({ pathname: "/chef/client", params: { id: k.household_id } } as never);
  return (
    <View style={[s.card, { padding: 18, gap: 10, borderColor: c.sageLight }]}>
      <View style={s.between}>
        <Text style={s.label}>Now · priority kitchen</Text>
        <Pill text={`${clock(k.arrive)} – ${clock(k.leave)}`} tone="pro" />
      </View>
      <Pressable onPress={open} accessibilityRole="button" accessibilityLabel={`Open ${k.name}`}>
        <Text style={[s.h1, { fontSize: 26 }]}>{k.name}</Text>
        <Text style={s.muted}>{k.dishes.length ? `${k.ready} of ${k.dishes.length} dishes ready` : "No dishes planned"}
          {" · "}covers {k.covers.map((d) => DAY_SHORT[d]).join(", ")}</Text>
      </Pressable>
      {k.dishes.length ? (
        <View style={{ height: 8, backgroundColor: c.primarySoft, borderRadius: 4, overflow: "hidden" }}>
          <View style={{ width: `${(100 * k.ready) / k.dishes.length}%`, height: 8, backgroundColor: c.primary }} />
        </View>) : null}
      <View style={{ backgroundColor: c.primarySoft, borderRadius: 18, padding: 14, gap: 2 }}>
        <Text style={[s.label, { color: c.primary }]}>Next up</Text>
        <Text style={{ fontSize: 18, fontWeight: "900", color: c.primaryDark }}>{k.next}</Text>
      </View>
      {k.hazards.map((h) => <Hazard key={h} text={h} />)}
      {k.expiring.length ? <Pill text={`Use soon: ${k.expiring.join(", ")}`} tone="amber" /> : null}
      <View style={[s.row, { flexWrap: "wrap" }]}>
        <Pressable style={s.ghost} onPress={() => router.push({ pathname: "/chef/client", params: { id: k.household_id, tab: "reheat" } } as never)}>
          <Text style={s.ghostText}>🔥 Reheating card</Text></Pressable>
        <Pressable style={s.ghost} onPress={() => router.push({ pathname: "/chef/client", params: { id: k.household_id, tab: "fridge" } } as never)}>
          <Text style={s.ghostText}>🧊 Log leftovers</Text></Pressable>
        <Pressable style={s.ghost} onPress={() => router.push({ pathname: "/chef/voice", params: { household: k.household_id } } as never)}>
          <Text style={s.ghostText}>🎙️ Voice note</Text></Pressable>
      </View>
    </View>
  );
}

export default function ChefNext() {
  const { width } = useWindowDimensions();
  const [d, setD] = useState<Cockpit | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try { setD(await pro.cockpit()); setError(null); } catch (e) { setError(e); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const later = d ? d.kitchens.filter((k) => k.household_id !== d.now?.household_id && !k.done) : [];
  const earlier = d ? d.kitchens.filter((k) => k.done) : [];
  return (
    <SafeAreaView style={s.screen} edges={["top"]}>
      <ScrollView contentContainerStyle={[s.pad, { paddingBottom: 110 }, width > 900 && { width: 860, alignSelf: "center", paddingTop: 28 }]}>
        <View style={s.between}>
          <View style={{ flex: 1 }}>
            <Text style={[s.h1, { fontSize: 26 }]}>{greet(d?.chef ?? "")}</Text>
            <Text style={s.muted}>{d ? `${d.homes_today} ${d.homes_today === 1 ? "home" : "homes"} today` : loading ? "Loading…" : ""}</Text>
          </View>
          <ProBadge text={d?.studio ? "STUDIO" : "PRO"} />
        </View>

        {d?.now ? <Hero k={d.now} /> : d ? (
          <View style={s.card}>
            <Text style={s.h2}>{earlier.length ? "Done for today 🌿" : "No kitchens today"}</Text>
            <Text style={s.muted}>{d.clients.length ? (earlier.length ? "Log anything you missed below; your next visits are further down." :
              "Your next visits are below. Set visit days on each client.") : "Add your first client household to get started."}</Text>
            {!d.clients.length ? <Button kind="pro" title="Add a client" onPress={() => router.push("/chef/new-client" as never)} /> : null}
          </View>) : null}

        {d?.next_stop ? (
          <Pressable onPress={() => router.push("/chef/shop" as never)} style={[s.card, { backgroundColor: c.proSoft, borderColor: "#E5DFD6" }]}>
            <Text style={[s.label, { color: c.pro }]}>Next store stop</Text>
            <Text style={s.h2}>🛒 {d.next_stop.store} · {d.next_stop.items} items</Text>
            {d.next_stop.pay.map((p, i) => (
              <Text key={i} style={s.body}>💳 Pay with <Text style={{ fontWeight: "800" }}>{p.with}</Text> · {money(p.total)}
                {p.note ? <Text style={s.muted}> · {p.note}</Text> : null}</Text>))}
          </Pressable>) : d && d.studio ? (
          <Pressable onPress={() => router.push("/chef/shop" as never)} style={[s.card, { backgroundColor: c.proSoft, borderColor: "#E5DFD6" }]}>
            <Text style={s.h2}>🛒 Plan today's shopping run</Text>
            <Text style={s.muted}>One trip across every home you visit next, split by home and routed to your best card.</Text>
          </Pressable>) : null}

        {later.length ? <Text style={s.label}>Later today</Text> : null}
        {later.map((k) => (
          <Pressable key={k.household_id} style={s.card}
            onPress={() => router.push({ pathname: "/chef/client", params: { id: k.household_id } } as never)}>
            <View style={s.between}>
              <Text style={s.h2}>{k.name}</Text>
              <Text style={s.muted}>{clock(k.arrive)}</Text>
            </View>
            <Text style={s.muted}>{k.ready} of {k.dishes.length} dishes ready · {k.next}</Text>
            {k.hazard ? <Pill text={`⚠ ${k.hazard}`} tone="red" /> : null}
          </Pressable>))}

        {earlier.length ? <Text style={s.label}>Earlier today</Text> : null}
        {earlier.map((k) => (
          <Pressable key={k.household_id} style={[s.card, { opacity: 0.85 }]}
            onPress={() => router.push({ pathname: "/chef/client", params: { id: k.household_id } } as never)}>
            <View style={s.between}>
              <Text style={s.h2}>{k.name}</Text>
              <Text style={s.muted}>{clock(k.arrive)}–{clock(k.leave)}</Text>
            </View>
            <Text style={s.muted}>{k.ready} of {k.dishes.length} dishes logged{k.ready < k.dishes.length ? " · log the rest by voice" : ""}</Text>
          </Pressable>))}

        {d && d.clients.length ? <Text style={s.label}>Your clients</Text> : null}
        {d && d.clients.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingRight: 8 }}>
            {d.clients.map((cl) => (
              <Pressable key={cl.household_id} onPress={() => router.push({ pathname: "/chef/client", params: { id: cl.household_id } } as never)}
                style={[{ width: 168, backgroundColor: c.card, borderRadius: 20, borderWidth: 1, borderColor: c.line, padding: 14, gap: 4 }, shadow]}>
                <Text style={{ fontSize: 11, fontWeight: "900", color: c.pro }}>#{cl.priority}</Text>
                <Text style={s.h2} numberOfLines={1}>{cl.name}</Text>
                <Text style={s.muted} numberOfLines={1}>{cl.visits.length ? cl.visits.map((v) => `${DAY_SHORT[v.day]} ${clock(v.arrive)}`).join(" · ") : "no visit days yet"}</Text>
                <Text style={s.muted}>{cl.billing === "client_card_on_file" ? "Client's card" : "Your card → invoice"}</Text>
              </Pressable>))}
          </ScrollView>) : null}

        {d && d.upcoming.length ? (
          <View style={s.card}>
            <Text style={s.h2}>This week</Text>
            {d.upcoming.map((u, i) => (
              <View key={i} style={s.between}>
                <Text style={s.body}>{new Date(`${u.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</Text>
                <Text style={s.muted}>{u.name} · {clock(u.arrive)}</Text>
              </View>))}
          </View>) : null}
        <ErrorText error={error} />
      </ScrollView>
      {d ? <VoiceFab household={d.now?.household_id} /> : null}
    </SafeAreaView>
  );
}
