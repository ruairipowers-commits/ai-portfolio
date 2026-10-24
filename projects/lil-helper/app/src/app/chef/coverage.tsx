// Coverage packs (Chef Studio): a backup chef gets a link that opens with a password you send separately, only between
// the dates you set. "Recipes and routines" leaves out addresses and door codes; "Full" includes them.
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import * as Clipboard from "expo-clipboard";
import { Text } from "@/components/text";
import { ChefHome, CoveragePack, pro } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function Coverage() {
  const [home, setHome] = useState<ChefHome | null>(null);
  const [packs, setPacks] = useState<CoveragePack[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [start, setStart] = useState(iso(new Date()));
  const [end, setEnd] = useState(iso(new Date(Date.now() + 2 * 86400000)));
  const [homes, setHomes] = useState<string[]>([]);
  const [level, setLevel] = useState("view_recipes_and_routines");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [made, setMade] = useState<CoveragePack | null>(null);
  const load = useCallback(() => {
    pro.home().then((h) => { setHome(h); setHomes((x) => x.length ? x : h.clients.map((cl) => cl.household_id)); }).catch(setError);
    pro.coverage().then((r) => setPacks(r.packs)).catch(setError);
  }, []);
  useEffect(() => { load(); }, [load]);
  async function create() {
    setError(null);
    try { setMade(await pro.newCoverage({ sub_name: name, sub_email: email, start, end, households: homes, level, password: pw }));
      setPw(""); load(); } catch (e) { setError(e); }
  }
  const names = Object.fromEntries((home?.clients ?? []).map((x) => [x.household_id, x.name]));
  return (
    <Screen>
      <Header title="Coverage packs" />
      <View style={s.card}>
        <Text style={s.h2}>New pack</Text>
        <Field label="Backup chef" value={name} onChangeText={setName} placeholder="Sarah Jenkins" />
        <Field label="Their email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />
        <View style={s.row}>
          <View style={{ flex: 1 }}><Field label="From" value={start} onChangeText={setStart} /></View>
          <View style={{ flex: 1 }}><Field label="To" value={end} onChangeText={setEnd} /></View>
        </View>
        {home ? <Chips label="Kitchens" options={home.clients.map((x) => ({ id: x.household_id, label: x.name }))} value={homes} onChange={setHomes} /> : null}
        <Chips options={[{ id: "view_recipes_and_routines", label: "Recipes and routines" }, { id: "full_operational", label: "Full (with door codes)" }]}
          value={level} multi={false} onChange={(v) => setLevel(v[0])} />
        <Field label="Password (8+ characters)" value={pw} onChangeText={setPw} secureTextEntry
          hint="Send it to them by text, not in the same email as the link." />
        <Button kind="pro" title="Create and email the link" onPress={create} disabled={!name || !email.includes("@") || pw.length < 8 || !homes.length} />
      </View>
      {made ? (
        <View style={[s.card, { backgroundColor: c.primarySoft, borderColor: c.sageLight }]}>
          <Text style={s.body}>✅ Emailed to {made.sub_email}. It opens {made.start} and closes after {made.end}.</Text>
          <Button kind="ghost" title="Copy the link" onPress={() => Clipboard.setStringAsync(made.url)} />
        </View>) : null}
      {packs.map((p) => (
        <View key={p.id} style={s.card}>
          <View style={s.between}>
            <Text style={s.h2}>{p.sub_name}</Text>
            <Pill text={p.revoked ? "revoked" : p.end < iso(new Date()) ? "expired" : "active"} tone={p.revoked || p.end < iso(new Date()) ? "red" : "green"} />
          </View>
          <Text style={s.muted}>{p.start} → {p.end} · {p.households.map((h) => names[h] ?? "—").join(", ")} · opened {p.opened}×</Text>
          {!p.revoked ? <Button kind="ghost" title="Revoke" onPress={async () => { await pro.revokeCoverage(p.id); load(); }} /> : null}
        </View>))}
      <ErrorText error={error} />
    </Screen>
  );
}
