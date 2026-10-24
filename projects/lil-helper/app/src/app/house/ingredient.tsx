// One ingredient: DinnerPeace's indicative prices at your stores, and your own choice — the brand you buy, where,
// and what it costs you. Your choice is used in every plan and shopping list.
import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { api, IngredientDetail, IngredientPref } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, money, NumberField, Saved, Screen, Toggle } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Ingredient() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [d, setD] = useState<IngredientDetail | null>(null);
  const [p, setP] = useState<IngredientPref>({ only_store: true });
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { api.ingredient(id).then((x) => { setD(x); setP({ only_store: true, ...(x.mine ?? {}) }); }).catch(setError); }, [id]);
  async function save() {
    setBusy(true); setError(null); setSavedAt(null);
    try {
      const body = Object.fromEntries(Object.entries(p).filter(([, v]) => v !== "" && v !== undefined && v !== 0)) as IngredientPref;
      await api.setPref(id, body); setSavedAt(Date.now());
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <Screen>
      <Header title={d?.name ?? "Ingredient"} />
      {d ? <>
        <View style={s.card}>
          <Text style={s.muted}>{d.cat} · priced per {d.unit}{d.allergens.length ? ` · contains ${d.allergens.join(", ")}` : ""}</Text>
          {d.used_in.length ? <Text style={s.muted}>In: {d.used_in.slice(0, 6).join(", ")}{d.used_in.length > 6 ? "…" : ""}</Text> : null}
        </View>
        <View style={s.card}>
          <Text style={s.h2}>DinnerPeace's prices</Text>
          {d.book_prices.length ? d.book_prices.map((b, i) => <Text key={i} style={s.body}>{b.store_name} <Text style={s.muted}>
            {b.brand !== "any" ? `${b.brand} · ` : ""}{b.pack} {d.unit} for {money(b.price)}</Text></Text>)
            : <Text style={s.muted}>No price at your stores yet. Set yours below.</Text>}
          <Text style={s.muted}>Indicative shelf prices; specials and your receipts update them.</Text>
        </View>
        <View style={s.card}>
          <Text style={s.h2}>What you buy</Text>
          <Field label="Brand" value={p.brand ?? ""} onChangeText={(brand) => setP({ ...p, brand })} placeholder="e.g. Kerrygold" />
          <Chips label="Where" multi={false} value={p.store ?? ""} onChange={([store]) => setP({ ...p, store: store || undefined })}
            options={[{ id: "", label: "Wherever's cheapest" }, ...d.stores.map((x) => ({ id: x.id, label: x.name }))]} />
          {p.store ? <>
            <NumberField label={`Pack size (${d.unit})`} step={0.5} min={0} max={1000} value={p.pack ?? 0}
              onChange={(pack) => setP({ ...p, pack })} />
            <NumberField label="Price for that pack" step={0.25} min={0} max={1000} prefix="$" value={p.price ?? 0}
              onChange={(price) => setP({ ...p, price })} />
            <Toggle label={`Only buy it at that store`} value={p.only_store !== false} onChange={(only_store) => setP({ ...p, only_store })} />
          </> : null}
          <Button title="Use this in all our meals" busy={busy} onPress={save} />
          <Saved at={savedAt} />
          {d.mine ? <Button kind="ghost" title="Go back to DinnerPeace's choice" onPress={async () => {
            try { await api.clearPref(id); setP({ only_store: true }); setD({ ...d, mine: null }); } catch (e) { setError(e); } }} /> : null}
        </View>
      </> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
