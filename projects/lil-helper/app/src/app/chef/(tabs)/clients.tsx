// Client households, in priority order, with this week's spend against each budget. Add a client here.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { ChefHome, DAY_SHORT, pro } from "@/lib/api";
import { Button, ErrorText, money, Pill, Screen } from "@/components/ui";
import { clock, ProBadge } from "@/components/chef";
import { c, s } from "@/lib/theme";

export default function Clients() {
  const [h, setH] = useState<ChefHome | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { pro.home().then(setH).catch(setError); }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const full = h && h.client_limit != null && h.clients.length >= h.client_limit;
  return (
    <Screen onRefresh={load}>
      <View style={s.between}>
        <Text style={s.h1}>Clients</Text>
        {h ? <ProBadge text={`${h.clients.length}${h.client_limit != null ? ` / ${h.client_limit}` : ""} HOMES`} /> : null}
      </View>
      {h?.clients.map((cl) => {
        const over = cl.budget != null && cl.spent_this_week > cl.budget;
        return (
          <Pressable key={cl.household_id} style={s.card} accessibilityRole="button"
            onPress={() => router.push({ pathname: "/chef/client", params: { id: cl.household_id } } as never)}>
            <View style={s.between}>
              <Text style={s.h2}>{cl.name}</Text>
              <Text style={{ color: c.pro, fontWeight: "900" }}>#{cl.priority}</Text>
            </View>
            <Text style={s.muted}>{cl.visits.length ? cl.visits.map((v) => `${DAY_SHORT[v.day]} ${clock(v.arrive)}–${clock(v.leave)}`).join(" · ")
              : "No visit days yet: open to set them"}</Text>
            <View style={[s.row, { flexWrap: "wrap" }]}>
              <Pill text={cl.billing === "client_card_on_file" ? "client's card" : "your card → invoice"} tone="pro" />
              {cl.budget != null ? <Pill text={`${money(cl.spent_this_week)} of ${money(cl.budget)} this week`}
                tone={over ? "red" : "green"} /> : null}
            </View>
          </Pressable>);
      })}
      {h && !h.clients.length ? (
        <View style={s.card}>
          <Text style={s.h2}>No clients yet</Text>
          <Text style={s.muted}>Set up a household for each family you cook for. They get Dinner Peace free: what you cooked,
            what's in their fridge, and how to reheat it.</Text>
        </View>) : null}
      {full ? (
        <View style={[s.card, { backgroundColor: c.proSoft }]}>
          <Text style={s.body}>{h!.label} runs up to {h!.client_limit} homes.</Text>
          <Button kind="pro" title="See Chef Studio" onPress={() => router.push({ pathname: "/plans", params: { focus: "chef_studio" } } as never)} />
        </View>) : <Button kind="pro" title="Add a client household" onPress={() => router.push("/chef/new-client" as never)} />}
      <ErrorText error={error} />
    </Screen>
  );
}
