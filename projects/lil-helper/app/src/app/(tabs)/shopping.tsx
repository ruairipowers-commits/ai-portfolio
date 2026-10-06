// Shopping: one list per store, handed to the app that already does it well — an Instacart link, a list shared to
// the Whole Foods app or Reminders, or an aisle-ordered list for Trader Joe's. Lil'Helper never buys anything.
import * as WebBrowser from "expo-web-browser";
import { useCallback, useState } from "react";
import { Share, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { api, ApiError, Order } from "@/lib/api";
import { Button, ErrorText, money, Pill, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Shopping() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [locked, setLocked] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setOrders((await api.shopping()).orders); setLocked(false); }
    catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) { setLocked(true); setOrders(null); }
      else setError(e);
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <Screen refreshing={loading} onRefresh={load}>
      <Text style={s.h1}>Shopping</Text>
      {locked ? <View style={s.card}><Text style={s.body}>🔒 Approve this week's plan first. Nothing goes to a store
        until an adult has said yes.</Text></View> : null}
      {orders?.map((o) => (
        <View key={o.store + o.mode} style={s.card}>
          <View style={s.between}>
            <Text style={s.h2}>{o.store}</Text>
            <Pill text={o.mode.replace("_", " ")} tone={o.mode === "in_store" ? "amber" : "green"} />
          </View>
          <Text style={s.muted}>{o.lines.length} items · {money(o.total)}{o.credits ? ` · credits ${money(o.credits)}` : ""}</Text>
          {o.lines.slice(0, 8).map((ln) => (
            <Text key={ln.name} style={s.body}>{ln.special ? "★ " : "☐ "}{ln.packs} × {ln.name}
              {ln.brand && ln.brand !== o.store ? <Text style={s.muted}> {ln.brand}</Text> : null}</Text>
          ))}
          {o.lines.length > 8 ? <Text style={s.muted}>…and {o.lines.length - 8} more</Text> : null}
          {o.url ? <Button title={`Open in Instacart`} onPress={() => WebBrowser.openBrowserAsync(o.url!)} /> : null}
          {o.share_text ? <Button kind="ghost" title="Share the list (Reminders, Messages…)"
            onPress={() => Share.share({ title: `${o.store} list`, message: o.share_text! })} /> : null}
          {o.note ? <Text style={s.muted}>{o.note}</Text> : null}
        </View>
      ))}
      <ErrorText error={error} />
    </Screen>
  );
}
