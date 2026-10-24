// What you've spent for each client, the card and its rewards, budgets this week, and invoices (Studio).
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { ChefHome, Ledger, pro } from "@/lib/api";
import { Button, Chips, ErrorText, Field, money, NumberField, Pill, Screen } from "@/components/ui";
import { Stat } from "@/components/chef";
import { c, s } from "@/lib/theme";

export default function LedgerScreen() {
  const [l, setL] = useState<Ledger | null>(null);
  const [home, setHome] = useState<ChefHome | null>(null);
  const [hid, setHid] = useState<string | null>(null);
  const [storeName, setStoreName] = useState("");
  const [amount, setAmount] = useState(0);
  const [card, setCard] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    pro.ledger().then((x) => { setL(x); setError(null); }).catch(setError);
    pro.home().then((h) => { setHome(h); setHid((cur) => cur ?? h.clients[0]?.household_id ?? null); }).catch(() => {});
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const act = (fn: () => Promise<unknown>, ok: string) => async () => {
    setMsg(null); setError(null);
    try { await fn(); setMsg(ok); load(); } catch (e) { setError(e); }
  };
  const pendingFor = (h: string) => l?.rows.filter((r) => r.household_id === h && r.status === "pending" && r.paid_by === "chef")
    .reduce((a, r) => a + r.amount, 0) ?? 0;
  return (
    <Screen onRefresh={load}>
      <Text style={s.h1}>Ledger</Text>
      {l ? <View style={s.row}><Stat value={money(l.totals.pending)} label="to be reimbursed" /><Stat value={money(l.totals.rewards)} label="card rewards" /></View> : null}
      {l && home ? home.clients.map((cl) => {
        const b = l.budgets[cl.household_id];
        const pend = pendingFor(cl.household_id);
        return (
          <View key={cl.household_id} style={s.card}>
            <View style={s.between}>
              <Text style={s.h2}>{cl.name}</Text>
              {b?.budget != null ? <Pill text={`${money(b.spent)} of ${money(b.budget)}`} tone={b.spent > b.budget ? "red" : "green"} /> : null}
            </View>
            <Text style={s.muted}>{pend ? `${money(pend)} not invoiced yet` : "Nothing waiting to invoice"}</Text>
            {pend && home.features.invoices ? <Button kind="pro" title={`Invoice ${money(pend)}`}
              onPress={act(() => pro.invoice(cl.household_id), "Invoice sent")} /> : null}
            {pend && !home.features.invoices ? <Text style={[s.muted, { color: c.pro }]}>Automatic client invoices are part of Chef Studio.</Text> : null}
          </View>);
      }) : null}
      <View style={s.card}>
        <Text style={s.h2}>Add a receipt</Text>
        {home ? <Chips options={home.clients.map((x) => ({ id: x.household_id, label: x.name }))} value={hid} multi={false} onChange={(v) => setHid(v[0])} /> : null}
        <Field label="Store" value={storeName} onChangeText={setStoreName} placeholder="Whole Foods" />
        <NumberField label="Amount" value={amount} onChange={setAmount} step={5} prefix="$" max={10000} />
        <Field label="Card (a name)" value={card} onChangeText={setCard} placeholder="Amex Gold" />
        <Button kind="pro" title="Add" disabled={!hid || !storeName.trim() || amount <= 0}
          onPress={act(() => pro.receipt({ household_id: hid!, store: storeName.trim(), amount, card: card || undefined }), "Added")} />
      </View>
      {l?.invoices.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Invoices</Text>
          {l.invoices.map((iv) => (
            <View key={iv.id} style={[s.between, { paddingVertical: 4 }]}>
              <Text style={[s.body, { flex: 1 }]}>{iv.id} · {l.names[iv.household_id]}</Text>
              <Text style={s.body}>{money(iv.total)} </Text>
              {iv.status === "paid" ? <Pill text="paid" /> : <Button kind="ghost" title="Mark paid" onPress={act(() => pro.invoicePaid(iv.id), "Marked paid")} />}
            </View>))}
        </View>) : null}
      {l?.rows.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Recent</Text>
          {l.rows.slice(0, 30).map((r) => (
            <View key={r.id} style={[s.between, { paddingVertical: 3 }]}>
              <Text style={[s.body, { flex: 1 }]} numberOfLines={1}>{r.date} · {r.name} · {r.store}</Text>
              <Text style={s.body}>{money(r.amount)}</Text>
              <Pill text={r.status} tone={r.status === "pending" ? "amber" : r.status === "invoiced" ? "pro" : "green"} />
            </View>))}
        </View>) : null}
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
