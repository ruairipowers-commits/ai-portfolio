// Specials: deals you know about, by store, and whether they're in the store, online (pickup or delivery) or both.
// "Every week" for standing deals. Or read a flyer photo; nothing counts until you confirm it.
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, Special } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, money, Pill, Screen, Toggle } from "@/components/ui";
import { c, s } from "@/lib/theme";

type Flyer = Awaited<ReturnType<typeof api.flyer>>;
const CHANNELS = [{ id: "any", label: "Both" }, { id: "in_store", label: "In store only" }, { id: "online", label: "Online only" }];

export default function Specials() {
  const [rows, setRows] = useState<Special[]>([]);
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);
  const [f, setF] = useState({ store: "", item: "", price: "", per: "pack" as "pack" | "unit", channel: "any", repeat: false });
  const [flyer, setFlyer] = useState<Flyer | null>(null);
  const [flyerChannel, setFlyerChannel] = useState("any");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => {
    api.specials().then((r) => setRows(r.specials)).catch(setError);
    api.settings().then((v) => {
      const mine = v.catalogs.stores.filter((x) => (v.settings.stores ?? []).includes(x.id));
      setStores(mine); setF((x) => ({ ...x, store: x.store || mine[0]?.id || "" }));
    }).catch(() => {});
  }, []);
  useFocusEffect(load);

  async function add() {
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await api.addSpecial({ store: f.store, item: f.item, price: parseFloat(f.price), per: f.per,
        channel: f.channel, repeat_weekly: f.repeat });
      setMsg(`Saved: ${r.saved.replace(/_/g, " ")} at ${money(r.price)} for ${r.pack} ${r.unit}` + (r.note ? `. ${r.note}` : ""));
      setF({ ...f, item: "", price: "" }); load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function readFlyer() {
    const pick = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (pick.canceled) return;
    setBusy(true); setError(null);
    try { setFlyer(await api.flyer(f.store, pick.assets[0].uri)); } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const name = (id: string) => stores.find((x) => x.id === id)?.name ?? id;
  return (
    <Screen>
      <Header title="Specials" />
      <View style={s.card}>
        <Text style={s.h2}>This week</Text>
        {rows.length ? rows.map((r) => (
          <View key={r.id} style={s.between}>
            <Text style={[s.body, { flex: 1 }]}>{r.name} <Text style={s.muted}>{name(r.store)} · {money(r.price)}
              {r.regular ? ` (was ${money(r.regular)})` : ""}</Text></Text>
            {r.channel !== "any" ? <Pill text={r.channel === "in_store" ? "in store" : "online"} tone="amber" /> : null}
            {r.repeat_weekly ? <Pill text="weekly" /> : null}
            <Pressable onPress={async () => { await api.removeSpecial(r.id).catch(setError); load(); }}>
              <Text style={{ color: c.red, paddingLeft: 8 }}>✕</Text></Pressable>
          </View>
        )) : <Text style={s.muted}>None yet. Add one below, or read a flyer.</Text>}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Add a special</Text>
        <Chips label="Store" multi={false} options={stores.map((x) => ({ id: x.id, label: x.name }))} value={f.store}
          onChange={([store]) => setF({ ...f, store })} />
        <Field label="What" placeholder="chicken thighs" value={f.item} onChangeText={(item) => setF({ ...f, item })} />
        <Field label="Price" keyboardType="decimal-pad" placeholder="3.99" value={f.price} onChangeText={(price) => setF({ ...f, price })} />
        <Chips multi={false} options={[{ id: "pack", label: "for the pack" }, { id: "unit", label: "per lb / each" }]}
          value={f.per} onChange={([per]) => setF({ ...f, per: per as "pack" | "unit" })} />
        <Chips label="Where it applies" multi={false} options={CHANNELS} value={f.channel} onChange={([channel]) => setF({ ...f, channel })} />
        <Toggle label="Every week" hint="A standing deal; it stays until you remove it." value={f.repeat}
          onChange={(repeat) => setF({ ...f, repeat })} />
        <Button title="Add" busy={busy} onPress={add} disabled={!f.store || !f.item.trim() || !(parseFloat(f.price) > 0)} />
        {msg ? <Text style={s.muted}>{msg}</Text> : null}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>From a flyer</Text>
        <Text style={s.muted}>Pick a photo of {name(f.store) || "a store"}'s flyer. Lil'Helper reads it and matches what it
          can; you confirm.</Text>
        <Button kind="ghost" title="Choose a flyer photo" busy={busy} disabled={!f.store} onPress={readFlyer} />
        {flyer ? (
          <View style={{ gap: 4 }}>
            {flyer.flags.includes("instruction_on_flyer") ? <Text style={s.muted}>⚠️ The flyer had text that looked like
              an instruction to the app. It was ignored.</Text> : null}
            {flyer.items.map((i, n) => <Text key={n} style={s.body}>{i.status === "needs_confirm" ? "✓" : "✗"} {i.text}
              <Text style={s.muted}> {i.price != null ? money(i.price) : ""} {i.why.join("; ")}</Text></Text>)}
            <Chips label="These deals are" multi={false} options={CHANNELS} value={flyerChannel} onChange={([x]) => setFlyerChannel(x)} />
            <Button title="Confirm the ✓ ones" onPress={async () => {
              const ok = flyer.items.filter((i) => i.status === "needs_confirm" && i.ingredient && i.price != null)
                .map((i) => ({ ingredient: i.ingredient!, price: i.price! }));
              try { await api.confirmSpecials(flyer.store, ok, flyerChannel); setFlyer(null); load(); } catch (e) { setError(e); }
            }} />
          </View>
        ) : null}
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
