// Delivery services the household uses (Instacart, DoorDash, Uber Eats, Amazon, Walmart, Grubhub) and their
// memberships. DinnerPeace hands each list to them and counts fee waivers and credits; it never places an order.
import * as WebBrowser from "expo-web-browser";
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { DeliveryService, v6 } from "@/lib/api";
import { Button, Chips, ErrorText, Header, Pill, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function Delivery() {
  const [list, setList] = useState<DeliveryService[]>([]);
  const [on, setOn] = useState<string[]>([]);
  const [mem, setMem] = useState<string[]>([]);
  const [takeout, setTakeout] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const apply = (r: { services: DeliveryService[]; takeout_service: string | null }) => {
    setList(r.services); setOn(r.services.filter((x) => x.on).map((x) => x.id));
    setMem(r.services.filter((x) => x.membership.on).map((x) => x.membership.id!)); setTakeout(r.takeout_service);
  };
  const load = useCallback(() => { v6.delivery().then(apply).catch(setError); }, []);
  useEffect(() => { load(); }, [load]);
  async function save() {
    setMsg(null);
    try { apply(await v6.saveDelivery({ services: on, memberships: mem, takeout_service: takeout })); setMsg("Saved"); }
    catch (e) { setError(e); }
  }
  return (
    <Screen>
      <Header title="Delivery services" />
      <Text style={s.muted}>Turn on the services you use. Shopping lists offer them as ways to get the order, and
        memberships waive delivery fees over their minimums.</Text>
      {list.map((x) => (
        <View key={x.id} style={s.card}>
          <View style={s.between}>
            <Text style={s.h2}>{x.name}</Text>
            <View style={s.row}>{x.kinds.map((k) => <Pill key={k} text={k} tone={k === "takeout" ? "amber" : "green"} />)}</View>
          </View>
          {x.note ? <Text style={s.muted}>{x.note}</Text> : null}
          <Toggle label="We use this" value={on.includes(x.id)} onChange={(v) => setOn(v ? [...on, x.id] : on.filter((y) => y !== x.id))} />
          {x.membership.id ? <Toggle label={`We have ${x.membership.name}`} value={mem.includes(x.membership.id)}
            hint={[x.membership.price_per_month ? `$${x.membership.price_per_month}/month` : "",
              x.membership.waive?.minimum ? `$0 delivery over $${x.membership.waive.minimum}` : "",
              x.membership.verified ? `checked ${x.membership.verified}` : "check your plan's terms"].filter(Boolean).join(" · ")}
            onChange={(v) => setMem(v ? [...mem, x.membership.id!] : mem.filter((y) => y !== x.membership.id))} /> : null}
          <Text style={s.muted}>{x.handoff === "instacart" ? "One-tap list link" : "Share the list, then open the app"}</Text>
          <Button kind="ghost" title={`Open ${x.name}`} onPress={() => WebBrowser.openBrowserAsync(x.url)} />
        </View>))}
      {list.length ? <View style={s.card}>
        <Chips label="Takeout nights order through" multi={false} value={takeout}
          options={list.filter((x) => x.kinds.includes("takeout")).map((x) => ({ id: x.id, label: x.name }))}
          onChange={(v) => setTakeout(v[0])} />
      </View> : null}
      <Button title="Save" onPress={save} />
      {msg ? <Pill text={msg} /> : null}
      <Text style={[s.muted, { color: c.muted }]}>DoorDash, Uber Eats, Walmart and Grubhub don't take shopping lists from
        other apps, so DinnerPeace shares the list for you to paste or follow.</Text>
      <ErrorText error={error} />
    </Screen>
  );
}
