// Cards: add and edit each card (issuer, expiry, rewards and caps, limits, the stores it's for, delivery credits),
// see this year's progress toward each bonus cap, and which card DinnerPeace picks where — including the next best
// one when a card's bonus runs out. Never a card number: names and the last four digits at most.
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { CardIn, CardStatus, EarnRule, pretty, v6, Wallet } from "@/lib/api";
import { Button, Chips, Pair, ErrorText, Field, Header, money, NumberField, Pill, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

const NETWORKS = ["visa", "mastercard", "amex", "discover"];

function toIn(x: CardStatus): CardIn {
  return { id: x.id, template: x.template && x.template !== x.id ? x.template : x.template || undefined, name: x.name,
    issuer: x.issuer, network: x.network, last4: x.last4, expires: x.expires, earn: x.earn, credit_limit: x.credit_limit,
    monthly_limit: x.monthly_limit, stores: x.stores, primary: x.primary, active: x.active,
    credits: x.credits.map(({ used: _u, ...cr }) => cr) };
}

function Bar({ pct, tone }: { pct: number; tone: string }) {
  return (
    <View style={{ height: 8, backgroundColor: c.primarySoft, borderRadius: 4, overflow: "hidden" }}>
      <View style={{ width: `${Math.min(100, Math.round(pct * 100))}%`, height: 8, backgroundColor: tone }} />
    </View>
  );
}

function CardView({ x, onEdit, onPrimary }: { x: CardStatus; onEdit: () => void; onPrimary: () => void }) {
  return (
    <View style={[s.card, !x.active && { opacity: 0.6 }]}>
      <View style={s.between}>
        <View style={{ flex: 1 }}>
          <Text style={s.h2}>💳 {x.name}{x.last4 ? <Text style={s.muted}>  ····{x.last4}</Text> : null}</Text>
          <Text style={s.muted}>{[x.issuer, x.network.toUpperCase(), x.expires ? `exp ${x.expires}` : ""].filter(Boolean).join(" · ")}</Text>
        </View>
        {x.primary ? <Pill text="primary" /> : null}
        {x.warn ? <Pill text={x.warn} tone={x.warn === "expired" ? "red" : "amber"} /> : null}
      </View>
      {x.caps.map((cap) => (
        <View key={cap.category} style={{ gap: 3 }}>
          <View style={s.between}>
            <Text style={s.body}>{pretty(cap.category)} · {(cap.rate * 100).toFixed(cap.rate * 100 % 1 ? 1 : 0)}%</Text>
            <Text style={s.muted}>{cap.cap ? `${money(cap.spent)} of ${money(cap.cap)} this year` : `${money(cap.spent)} this year`}</Text>
          </View>
          {cap.cap ? <Bar pct={cap.pct_used ?? 0} tone={(cap.pct_used ?? 0) >= 1 ? c.red : (cap.pct_used ?? 0) > 0.8 ? c.cheese : c.primary} /> : null}
          {cap.next_best ? <Text style={[s.muted, { color: c.pro }]}>Bonus used up: {cap.next_best} is next best for {pretty(cap.category).toLowerCase()}.</Text> : null}
        </View>))}
      {x.monthly_limit != null || x.credit_limit != null ? (
        <Text style={s.muted}>This month {money(x.month_spent)}{x.month_left != null ? ` · ${money(x.month_left)} left under ${x.monthly_limit != null ? "your monthly limit" : "the credit limit"}` : ""}</Text>) : null}
      {x.stores.length ? <Text style={s.muted}>First choice at: {x.stores.map(pretty).join(", ")}</Text> : null}
      {x.credits.map((cr) => <Text key={cr.name} style={s.muted}>🎟️ {cr.name}: {money(cr.used ?? 0)} of {money(cr.monthly)} used this month
        {cr.applies_to?.length ? ` (${cr.applies_to.map(pretty).join(", ")})` : ""}</Text>)}
      <View style={s.row}>
        <Button kind="ghost" title="Edit" onPress={onEdit} />
        {!x.primary ? <Button kind="ghost" title="Make primary" onPress={onPrimary} /> : null}
      </View>
    </View>
  );
}

function Editor({ w, value, onSave, onCancel, onDelete }: { w: Wallet; value: CardIn; onSave: (c: CardIn) => void;
  onCancel: () => void; onDelete?: () => void }) {
  const [x, setX] = useState<CardIn>(value);
  const set = (p: Partial<CardIn>) => setX({ ...x, ...p });
  const earn = Object.entries(x.earn ?? {});
  const setRule = (cat: string, r: EarnRule | null, rename?: string) => {
    const e = { ...(x.earn ?? {}) };
    delete e[cat];
    if (r) e[rename ?? cat] = r;
    set({ earn: e });
  };
  const fromTemplate = (id: string) => {
    const t = w.templates.find((t) => t.id === id);
    if (t) setX({ ...x, template: id, name: t.name, issuer: t.issuer, network: t.network, earn: t.earn, credits: t.credits });
  };
  return (
    <View style={[s.card, { borderColor: c.sage, borderWidth: 2 }]}>
      <Text style={s.h2}>{value.id ? "Edit card" : "Add a card"}</Text>
      {!value.id ? <Chips label="Start from a known card (rewards filled in)" multi={false} value={x.template ?? null}
        options={w.templates.map((t) => ({ id: t.id, label: t.name }))} onChange={(v) => fromTemplate(v[0])} /> : null}
      <Field label="Name" value={x.name ?? ""} onChangeText={(v) => set({ name: v })} placeholder="Amex Gold" />
      <Field label="Company (issuer)" value={x.issuer ?? ""} onChangeText={(v) => set({ issuer: v })} placeholder="American Express" />
      <Chips label="Network" multi={false} value={x.network ?? null} options={NETWORKS.map((n) => ({ id: n, label: n.toUpperCase() }))}
        onChange={(v) => set({ network: v[0] })} />
      <View style={s.row}>
        <View style={{ flex: 1 }}><Field label="Last 4 (optional)" value={x.last4 ?? ""} maxLength={4} keyboardType="number-pad"
          onChangeText={(v) => set({ last4: v.replace(/\D/g, "") })} /></View>
        <View style={{ flex: 1 }}><Field label="Expires (YYYY-MM)" value={x.expires ?? ""} placeholder="2029-08" maxLength={7}
          onChangeText={(v) => set({ expires: v })} /></View>
      </View>
      <Text style={s.label}>Rewards</Text>
      {earn.map(([cat, r]) => (
        <View key={cat} style={{ gap: 4, paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line }}>
          <Chips multi={false} value={cat} options={w.categories.map((k) => ({ id: k, label: pretty(k) }))}
            onChange={(v) => setRule(cat, r, v[0])} />
          <Pair>
            <NumberField label={r.points != null ? "Points per $1" : "% back"} step={r.points != null ? 1 : 0.5}
              value={r.points != null ? r.points : Math.round((r.pct ?? 0) * 1000) / 10} max={r.points != null ? 20 : 20}
              onChange={(n) => setRule(cat, r.points != null ? { ...r, points: n } : { ...r, pct: n / 100 })} />
            <NumberField label="Yearly cap ($, 0 = none)" step={1000} max={1000000} value={r.annual_cap ?? 0}
              onChange={(n) => setRule(cat, { ...r, annual_cap: n || null })} />
          </Pair>
          <View style={s.row}>
            <Button kind="ghost" title={r.points != null ? "Use % back" : "Use points"} onPress={() =>
              setRule(cat, r.points != null ? { pct: (r.points ?? 1) / 100, annual_cap: r.annual_cap } :
                { points: Math.round((r.pct ?? 0.01) * 100), program: "amex_membership_rewards", annual_cap: r.annual_cap })} />
            <Pressable onPress={() => setRule(cat, null)}><Text style={{ color: c.red, fontWeight: "700" }}>Remove</Text></Pressable>
          </View>
        </View>))}
      <Button kind="ghost" title="+ Add a reward category" onPress={() => {
        const free = w.categories.find((k) => !(x.earn ?? {})[k]) ?? "default";
        setRule(free, { pct: 0.01 });
      }} />
      <Pair>
        <NumberField label="Credit limit ($)" step={500} max={1000000} value={x.credit_limit ?? 0}
          onChange={(n) => set({ credit_limit: n || null })} />
        <NumberField label="Your monthly food limit ($)" step={50} max={100000} value={x.monthly_limit ?? 0}
          onChange={(n) => set({ monthly_limit: n || null })} />
      </Pair>
      <Chips label="Use this card first at (tap in order of preference)" value={x.stores ?? []}
        options={w.stores.map((st) => ({ id: st.id, label: `${(x.stores ?? []).includes(st.id) ? `${(x.stores ?? []).indexOf(st.id) + 1}. ` : ""}${st.name}` }))}
        onChange={(v) => set({ stores: v })} />
      <Text style={s.label}>Delivery and dining credits</Text>
      {(x.credits ?? []).map((cr, i) => (
        <View key={i} style={{ gap: 4, paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line }}>
          <Field label="Credit" value={cr.name} onChangeText={(v) => set({ credits: (x.credits ?? []).map((y, j) => j === i ? { ...y, name: v } : y) })} placeholder="Uber Cash" />
          <NumberField label="Per month ($)" step={5} max={500} value={cr.monthly}
            onChange={(n) => set({ credits: (x.credits ?? []).map((y, j) => j === i ? { ...y, monthly: n } : y) })} />
          <Chips label="Works with" value={cr.applies_to ?? []} options={w.services.map((sv) => ({ id: sv.id, label: sv.name }))}
            onChange={(v) => set({ credits: (x.credits ?? []).map((y, j) => j === i ? { ...y, applies_to: v } : y) })} />
          <Pressable onPress={() => set({ credits: (x.credits ?? []).filter((_, j) => j !== i) })}>
            <Text style={{ color: c.red, fontWeight: "700" }}>Remove credit</Text></Pressable>
        </View>))}
      <Button kind="ghost" title="+ Add a credit" onPress={() => set({ credits: [...(x.credits ?? []), { name: "", monthly: 10, applies_to: [] }] })} />
      <Toggle label="Primary card (your everyday card)" value={!!x.primary} onChange={(v) => set({ primary: v })} />
      <Toggle label="In use" value={x.active !== false} onChange={(v) => set({ active: v })} />
      <Text style={s.muted}>Never the card number: DinnerPeace refuses anything that looks like one.</Text>
      <Button title="Save card" onPress={() => onSave(x)} disabled={!x.name?.trim()} />
      <View style={s.row}>
        <Button kind="ghost" title="Cancel" onPress={onCancel} />
        {onDelete ? <Button kind="ghost" title="Delete card" onPress={onDelete} /> : null}
      </View>
    </View>
  );
}

export default function WalletScreen() {
  const [w, setW] = useState<Wallet | null>(null);
  const [edit, setEdit] = useState<CardIn | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { v6.wallet().then((x) => { setW(x); setError(null); }).catch(setError); }, []);
  useEffect(() => { load(); }, [load]);
  const all = () => (w?.cards ?? []).map(toIn);
  async function save(list: CardIn[]) {
    try {
      if (list.some((k) => k.primary)) {
        const p = list.filter((k) => k.primary).pop();
        list = list.map((k) => ({ ...k, primary: k === p }));
      }
      setW(await v6.saveCards(list)); setEdit(null); setError(null);
    } catch (e) { setError(e); }
  }
  return (
    <Screen onRefresh={load}>
      <Header title="Cards" />
      <Text style={s.muted}>Your cards' rewards, caps and limits decide which card DinnerPeace suggests for each order.
        When a card's bonus for the year runs out, the next best one takes over.</Text>
      {edit ? <Editor w={w!} value={edit} onCancel={() => setEdit(null)}
        onSave={(x) => save(edit.id ? all().map((k) => (k.id === edit.id ? x : k)) : [...all(), x])}
        onDelete={edit.id ? () => save(all().filter((k) => k.id !== edit.id)) : undefined} /> : null}
      {w && !edit ? <Button title="+ Add a card" onPress={() => setEdit({ name: "", network: "visa", earn: { default: { pct: 0.01 } }, stores: [], credits: [] })} /> : null}
      {w?.cards.map((x) => <CardView key={x.id} x={x} onEdit={() => setEdit(toIn(x))}
        onPrimary={async () => { try { setW(await v6.primary(x.id)); } catch (e) { setError(e); } }} />)}
      {w?.where.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Which card where</Text>
          {w.where.map((b) => (
            <View key={b.store + b.mode} style={{ paddingVertical: 4, borderTopWidth: 1, borderTopColor: c.line }}>
              <View style={s.between}>
                <Text style={s.body}>{b.store_name} <Text style={s.muted}>{pretty(b.mode)}</Text></Text>
                <Text style={[s.body, { fontWeight: "800" }]}>{b.card_name} · {money(b.per_100)}/$100</Text>
              </View>
              <Text style={s.muted}>{b.note}</Text>
            </View>))}
        </View>) : null}
      <ErrorText error={error} />
    </Screen>
  );
}
