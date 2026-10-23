// Money: this week's budget against what's planned and what's been spent, and three ways to record spending —
// type it in, import a card statement (only food purchases are kept), or read a receipt (photo or emailed text).
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, MoneySummary, Receipt } from "@/lib/api";
import { Button, Chips, ErrorText, Field, LinkRow, money, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const CATS = [{ id: "groceries", label: "Groceries" }, { id: "takeout", label: "Takeout" }, { id: "eat_out", label: "Eating out" },
  { id: "pet", label: "Pet" }];

function Meter({ label, planned, spent, budget }: { label: string; planned: number; spent: number; budget: number }) {
  const top = Math.max(budget, planned, spent, 1);
  return (
    <View style={{ gap: 3 }}>
      <View style={s.between}><Text style={s.body}>{label}</Text>
        <Text style={s.muted}>spent {money(spent)} · planned {money(planned)} · budget {money(budget)}</Text></View>
      <View style={{ height: 10, backgroundColor: c.line, borderRadius: 5 }}>
        <View style={{ position: "absolute", height: 10, width: `${(planned / top) * 100}%`, backgroundColor: c.amberSoft, borderRadius: 5 }} />
        <View style={{ position: "absolute", height: 10, width: `${(spent / top) * 100}%`,
          backgroundColor: spent > budget ? c.red : c.green, borderRadius: 5 }} />
        <View style={{ position: "absolute", left: `${(budget / top) * 100}%`, height: 14, top: -2, width: 2, backgroundColor: c.ink }} />
      </View>
    </View>
  );
}

export default function Money() {
  const [sum, setSum] = useState<MoneySummary | null>(null);
  const [cards, setCards] = useState<{ id: string; name: string }[]>([]);
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);
  const [add, setAdd] = useState({ amount: "", store: "", merchant: "", category: "groceries", card: "" });
  const [stmtCard, setStmtCard] = useState("");
  const [rcText, setRcText] = useState("");
  const [rc, setRc] = useState<Receipt | null>(null);
  const [rcCard, setRcCard] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => {
    api.moneySummary().then(setSum).catch(setError);
    api.settings().then((v) => {
      setCards(v.catalogs.cards.filter((x) => (v.settings.cards ?? []).includes(x.id)));
      setStores(v.catalogs.stores.filter((x) => (v.settings.stores ?? []).includes(x.id)));
    }).catch(() => {});
  }, []);
  useFocusEffect(load);

  async function run(key: string, fn: () => Promise<string | void>) {
    setBusy(key); setError(null); setMsg(null);
    try { const m = await fn(); if (m) setMsg(m); load(); } catch (e) { setError(e); } finally { setBusy(null); }
  }

  const cardOpts = [{ id: "", label: "Not sure" }, ...cards.map((x) => ({ id: x.id, label: x.name }))];
  return (
    <Screen onRefresh={load}>
      <Text style={s.h1}>Money</Text>
      {sum ? (
        <View style={s.card}>
          <View style={s.between}><Text style={s.h2}>Week of {sum.week_of}</Text>
            <Pill text={sum.remaining >= 0 ? `${money(sum.remaining)} left` : `${money(-sum.remaining)} over`}
              tone={sum.remaining >= 0 ? "green" : "red"} /></View>
          <Meter label="Groceries" planned={sum.planned.groceries} spent={sum.spent.groceries ?? 0} budget={sum.budget.groceries} />
          <Meter label="Nights out" planned={sum.planned.takeout + sum.planned.eat_out}
            spent={(sum.spent.takeout ?? 0) + (sum.spent.eat_out ?? 0)} budget={sum.budget.eating_out} />
          <Text style={s.muted}>Card rewards this week {money(sum.rewards_earned)} · credits used {money(sum.spent.credits_used ?? 0)} ·
            this month {money(sum.month.total)}</Text>
          {sum.rows.slice(-6).reverse().map((r) => (
            <View key={r.id} style={s.between}>
              <Text style={[s.body, { flex: 1 }]}>{r.date.slice(5)} {r.merchant} <Text style={s.muted}>{r.category.replace("_", " ")} · {r.source}</Text></Text>
              <Text style={s.body}>{money(r.amount)}</Text>
              <Pressable onPress={() => run("del", async () => { await api.removeSpend(r.id); })}><Text style={{ color: c.red, paddingLeft: 8 }}>✕</Text></Pressable>
            </View>
          ))}
        </View>
      ) : null}
      <LinkRow icon="📊" title="What food costs" sub="Per week, per meal, per person" onPress={() => router.push("/house/report" as never)} />
      <View style={s.card}>
        <Text style={s.h2}>Add spending</Text>
        <Field label="Amount" keyboardType="decimal-pad" placeholder="42.50" value={add.amount} onChangeText={(amount) => setAdd({ ...add, amount })} />
        <Chips multi={false} options={CATS} value={add.category} onChange={([category]) => setAdd({ ...add, category })} />
        {add.category === "groceries" ? <Chips label="Store" multi={false} options={stores.map((x) => ({ id: x.id, label: x.name }))}
          value={add.store} onChange={([store]) => setAdd({ ...add, store })} />
          : <Field label="Where" value={add.merchant} onChangeText={(merchant) => setAdd({ ...add, merchant })} />}
        <Chips label="Card" multi={false} options={cardOpts} value={add.card} onChange={([card]) => setAdd({ ...add, card })} />
        <Button title="Add" busy={busy === "add"} disabled={!(parseFloat(add.amount) > 0)} onPress={() => run("add", async () => {
          await api.addSpend({ amount: parseFloat(add.amount), category: add.category, store: add.store || undefined,
            merchant: add.merchant || undefined, card: add.card || undefined });
          setAdd({ ...add, amount: "", merchant: "" });
        })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Import a card statement</Text>
        <Text style={s.muted}>Download it as CSV from your card's website. Only food purchases are kept (date, store,
          amount); everything else in the file is ignored, and the same purchase is never counted twice.</Text>
        <Chips label="Which card" multi={false} options={cardOpts} value={stmtCard} onChange={([x]) => setStmtCard(x)} />
        <Button kind="ghost" title="Choose the CSV file" busy={busy === "stmt"} onPress={() => run("stmt", async () => {
          const pick = await DocumentPicker.getDocumentAsync({ type: ["text/csv", "text/comma-separated-values", "text/plain", "*/*"] });
          if (pick.canceled) return;
          const a = pick.assets[0];
          const r = await api.statement({ uri: a.uri, name: a.name, mimeType: a.mimeType, file: (a as { file?: File }).file }, stmtCard || undefined);
          return `Imported ${r.imported} food purchases (${r.duplicates} already there, ${r.skipped_not_food} not food).`;
        })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Read a receipt</Text>
        <Text style={s.muted}>A photo, or paste an emailed receipt. You check it before anything is saved; prices it
          finds keep DinnerPeace's price list honest.</Text>
        <Button kind="ghost" title="Choose a receipt photo" busy={busy === "rcp"} onPress={() => run("rcp", async () => {
          const pick = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
          if (pick.canceled) return;
          const r = await api.receipt({ uri: pick.assets[0].uri }); setRc(r); setRcCard(r.suggested_card ?? "");
        })} />
        <TextInput style={[s.input, { minHeight: 70, textAlignVertical: "top" }]} multiline placeholder="…or paste the receipt email here"
          value={rcText} onChangeText={setRcText} />
        <Button kind="ghost" title="Read the pasted text" disabled={rcText.trim().length < 20} busy={busy === "rct"}
          onPress={() => run("rct", async () => { const r = await api.receipt({ text: rcText }); setRc(r); setRcCard(r.suggested_card ?? ""); })} />
        {rc ? (
          <View style={{ gap: 4 }}>
            <Text style={s.body}>{rc.merchant} · {rc.date ?? "no date"} · total {money(rc.total)}</Text>
            {rc.flags.includes("instruction_on_receipt") ? <Text style={s.muted}>⚠️ The receipt had text that looked like an
              instruction to the app. It was ignored.</Text> : null}
            {rc.flags.filter((f) => f !== "instruction_on_receipt").map((f) => <Text key={f} style={s.muted}>⚠️ {f.replace(/_/g, " ")}</Text>)}
            {rc.items.map((i, n) => <Text key={n} style={s.body}>{i.status === "price_update" ? "↻" : "•"} {i.text}
              <Text style={s.muted}> {money(i.price)}{i.ingredient ? ` → ${i.ingredient.replace(/_/g, " ")}` : ""}
              {i.status === "price_update" && i.shelf_price ? ` (list said ${money(i.shelf_price)})` : ""}</Text></Text>)}
            <Chips label="Paid with" multi={false} options={cardOpts} value={rcCard} onChange={([x]) => setRcCard(x)} />
            <Button title="Save this receipt" busy={busy === "rcc"} disabled={rc.total == null} onPress={() => run("rcc", async () => {
              const r = await api.confirmReceipt(rc.receipt, rcCard || null); setRc(null); setRcText("");
              return `Saved. ${r.prices_updated} prices updated.`;
            })} />
          </View>
        ) : null}
      </View>
      <LinkRow icon="💳" title="Cards and budget" sub="Which card where, memberships, cost per serving" onPress={() => router.push("/house/stores" as never)} />
      {msg ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>{msg}</Text></View> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
