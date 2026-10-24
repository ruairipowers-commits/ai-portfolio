// The owner console (only for DinnerPeace's owner): list prices per plan, monthly and yearly (with the yearly saving),
// price changes on a date, every subscription and what it renews at — keep its price (grandfather), move to the list
// price (upcharge), or a custom price — and the renewals coming up. Wide screens show it in two columns.
import { useCallback, useEffect, useState } from "react";
import { Pressable, useWindowDimensions, View } from "react-native";
import { Text } from "@/components/text";
import { OwnerView, PriceRow, Subscription, v6 } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, money, NumberField, Pill, Screen } from "@/components/ui";
import { Stat } from "@/components/chef";
import { c, s } from "@/lib/theme";

const POLICY = { grandfather: "Keep their price", current_price: "List price at renewal", custom: "Custom price" } as const;

function PriceCard({ p, onSaved, onError }: { p: PriceRow; onSaved: () => void; onError: (e: unknown) => void }) {
  const [monthly, setMonthly] = useState(p.monthly);
  const [mode, setMode] = useState<"discount" | "yearly">("discount");
  const [disc, setDisc] = useState(p.savings_pct);
  const [yearly, setYearly] = useState(p.yearly);
  const [when, setWhen] = useState("");
  const y = mode === "discount" ? Math.round(monthly * 12 * (1 - disc / 100) * 100) / 100 : yearly;
  return (
    <View style={s.card}>
      <View style={s.between}>
        <Text style={s.h2}>{p.label}</Text>
        <Pill text={`${p.subscribers} active`} tone="pro" />
      </View>
      <Text style={s.body}>Now: <Text style={{ fontWeight: "900" }}>{money(p.monthly)}</Text>/mo · {money(p.yearly)}/yr
        <Text style={s.muted}> (saves {p.savings_pct}%)</Text></Text>
      {p.scheduled ? <Pill tone="amber" text={`From ${p.scheduled.effective.slice(0, 10)}: ${money(p.scheduled.monthly)}/mo · ${money(p.scheduled.yearly)}/yr`} /> : null}
      <NumberField label="Monthly price" prefix="$" step={1} value={monthly} onChange={setMonthly} max={10000} />
      <Chips multi={false} value={mode} options={[{ id: "discount", label: "Yearly = discount on 12 months" }, { id: "yearly", label: "Set the yearly price" }]}
        onChange={(v) => setMode(v[0] as "discount" | "yearly")} />
      {mode === "discount" ? <NumberField label="Yearly discount (%)" step={5} value={disc} onChange={setDisc} max={99} />
        : <NumberField label="Yearly price" prefix="$" step={10} value={yearly} onChange={setYearly} max={120000} />}
      <Text style={s.muted}>Yearly: {money(y)} ({monthly ? Math.round(100 * (1 - y / (12 * monthly))) : 0}% off 12 months)</Text>
      <Field label="Starts (YYYY-MM-DD, blank = now)" value={when} onChangeText={setWhen} placeholder="2026-12-01" />
      <Button kind="pro" title="Save price" onPress={async () => {
        try {
          await v6.setPrice(p.plan, { monthly, ...(mode === "discount" ? { annual_discount_pct: disc } : { yearly }),
            ...(when ? { effective: `${when}T00:00:00` } : {}) });
          onSaved();
        } catch (e) { onError(e); }
      }} />
      <View style={s.row}>
        <Button kind="ghost" title="Grandfather everyone" onPress={async () => { await v6.bulk(p.plan, "grandfather"); onSaved(); }} />
        <Button kind="ghost" title="All to list price" onPress={async () => { await v6.bulk(p.plan, "current_price"); onSaved(); }} />
      </View>
    </View>
  );
}

function SubRow({ x, onSaved, onError }: { x: Subscription; onSaved: () => void; onError: (e: unknown) => void }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(x.custom_price ?? x.price);
  const save = async (b: Parameters<typeof v6.editSub>[1]) => { try { await v6.editSub(x.id, b); onSaved(); } catch (e) { onError(e); } };
  return (
    <View style={{ paddingVertical: 8, borderTopWidth: 1, borderTopColor: c.line, gap: 4 }}>
      <Pressable onPress={() => setOpen(!open)} style={s.between} accessibilityRole="button">
        <View style={{ flex: 1 }}>
          <Text style={[s.body, { fontWeight: "800" }]}>{x.who.name} <Text style={s.muted}>{x.who.email}</Text></Text>
          <Text style={s.muted}>{x.plan.replace("_", " ")} · {x.interval} · {x.source} · renews {x.renews.slice(0, 10)}</Text>
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={s.body}>{money(x.price)} → <Text style={{ fontWeight: "900", color: x.change > 0 ? c.pro : x.change < 0 ? c.primary : c.ink }}>{money(x.next_price)}</Text></Text>
          <Text style={s.muted}>{POLICY[x.policy]}</Text>
        </View>
      </Pressable>
      {open ? (
        <View style={{ gap: 6 }}>
          <Chips multi={false} value={x.policy} options={Object.entries(POLICY).map(([id, label]) => ({ id, label }))}
            onChange={(v) => v[0] === "custom" ? save({ policy: "custom", custom_price: custom }) : save({ policy: v[0] })} />
          {x.policy === "custom" ? <View style={s.row}>
            <View style={{ flex: 1 }}><NumberField label="Custom renewal price" prefix="$" step={1} value={custom} onChange={setCustom} max={10000} /></View>
            <Button kind="ghost" title="Set" onPress={() => save({ custom_price: custom })} />
          </View> : null}
          <View style={s.row}>
            <Button kind="ghost" title={x.interval === "monthly" ? "Switch to yearly" : "Switch to monthly"}
              onPress={() => save({ interval: x.interval === "monthly" ? "yearly" : "monthly" })} />
            {x.status === "active" ? <Button kind="ghost" title="Cancel at renewal" onPress={() => save({ status: "cancelled" })} /> : null}
          </View>
          {x.source === "revenuecat" ? <Text style={[s.muted, { color: c.pro }]}>App Store subscriber: the App Store charges its own price. Mirror this in App Store Connect.</Text> : null}
        </View>) : null}
    </View>
  );
}

export default function Owner() {
  const { width } = useWindowDimensions();
  const wide = width >= 1000;
  const [d, setD] = useState<OwnerView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [email, setEmail] = useState("");
  const [plan, setPlan] = useState("chef_solo");
  const [interval, setInterval] = useState("monthly");
  const [source, setSource] = useState("comp");
  const [filter, setFilter] = useState("all");
  const load = useCallback(() => { v6.owner().then((x) => { setD(x); setError(null); }).catch(setError); }, []);
  useEffect(() => { load(); }, [load]);
  const subs = (d?.subscriptions ?? []).filter((x) => filter === "all" || x.plan === filter);
  return (
    <Screen onRefresh={load} wide>
      <Header title="Owner console" />
      {d ? <View style={[s.row, { flexWrap: "wrap" }]}>
        <Stat value={String(d.totals.active)} label="active subscriptions" />
        <Stat value={money(d.totals.monthly_revenue)} label="a month (yearly spread)" />
        <Stat value={String(d.totals.grandfathered)} label="grandfathered" />
        <Stat value={String(d.totals.price_rises_next_30_days)} label="price rises in 30 days" />
      </View> : null}
      <View style={wide ? { flexDirection: "row", gap: 16, alignItems: "flex-start" } : { gap: 12 }}>
        <View style={wide ? { flex: 1, gap: 12 } : { gap: 12 }}>
          <Text style={s.label}>Prices</Text>
          {d?.prices.map((p) => <PriceCard key={p.plan} p={p} onSaved={load} onError={setError} />)}
          <Text style={s.muted}>{d?.store_note}</Text>
        </View>
        <View style={wide ? { flex: 1.3, gap: 12 } : { gap: 12 }}>
          <Text style={s.label}>Subscriptions</Text>
          <View style={s.card}>
            <Chips multi={false} value={filter} options={[{ id: "all", label: "All" }, { id: "family", label: "Family" },
              { id: "chef_solo", label: "Chef Solo" }, { id: "chef_studio", label: "Chef Studio" }]} onChange={(v) => setFilter(v[0])} />
            {subs.map((x) => <SubRow key={x.id} x={x} onSaved={load} onError={setError} />)}
            {!subs.length ? <Text style={s.muted}>No subscriptions yet.</Text> : null}
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Give someone a plan</Text>
            <Field label="Their email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />
            <Chips multi={false} value={plan} options={[{ id: "family", label: "Family" }, { id: "chef_solo", label: "Chef Solo" },
              { id: "chef_studio", label: "Chef Studio" }]} onChange={(v) => setPlan(v[0])} />
            <Chips multi={false} value={interval} options={["monthly", "yearly"]} onChange={(v) => setInterval(v[0])} />
            <Chips multi={false} value={source} options={[{ id: "comp", label: "Free (comp)" }, { id: "admin", label: "Paid outside the app" },
              { id: "trial", label: "Trial" }]} onChange={(v) => setSource(v[0])} />
            <Button kind="pro" title="Start subscription" disabled={!email.includes("@")} onPress={async () => {
              try { await v6.newSub({ email: email.trim(), plan, interval, source, policy: "current_price" }); setEmail(""); load(); }
              catch (e) { setError(e); }
            }} />
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Renewing in the next 30 days</Text>
            {d?.renewals.map((x) => <Text key={x.id} style={s.body}>{x.renews.slice(0, 10)} · {x.who.name} · {money(x.price)} → {money(x.next_price)}</Text>)}
            {!d?.renewals.length ? <Text style={s.muted}>None.</Text> : null}
            <Text style={s.muted}>Subscribers whose price goes up get an email 30 days before.</Text>
            <Button kind="ghost" title="Run due renewals now" onPress={async () => { await v6.renewNow(); load(); }} />
          </View>
          <View style={s.card}>
            <Text style={s.h2}>History</Text>
            {d?.history.slice(0, 15).map((h, i) => <Text key={i} style={s.muted}>{h.ts.slice(0, 16).replace("T", " ")} · {h.event} · {h.by}</Text>)}
          </View>
        </View>
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
