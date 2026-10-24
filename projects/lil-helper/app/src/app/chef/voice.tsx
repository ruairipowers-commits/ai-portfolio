// The hands-free logger. Say it (or type it) the way you'd tell a colleague; the server turns it into a list of
// changes by rules, you check them, and only then are they saved. Allergens are caught before anything changes.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { ApiError, ChefHome, pro, VoicePreview } from "@/lib/api";
import { Button, Chips, ErrorText, Header, Pill, Screen } from "@/components/ui";
import { Hazard } from "@/components/chef";
import { MicButton } from "@/components/voice";
import { c, s } from "@/lib/theme";

const EXAMPLE = "At the Millers. Chucked the leftover lasagna, made 4 portions of braised short ribs. Freeze two, " +
  "fridge two. Reheat at 350 for 25 minutes covered. They're out of olive oil.";
const ICON = { toss: "🗑️", eaten: "✅", made: "🍲", reheat: "🔥", shop: "🛒" } as const;

export default function VoiceLogger() {
  const { household } = useLocalSearchParams<{ household?: string }>();
  const [home, setHome] = useState<ChefHome | null>(null);
  const [hid, setHid] = useState<string | undefined>(household);
  const [text, setText] = useState("");
  const [p, setP] = useState<VoicePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { pro.home().then(setHome).catch(() => {}); }, []);
  async function preview(t: string) {
    if (!t.trim()) return;
    setBusy(true); setError(null); setDone(null);
    try { const r = await pro.voice(t, hid); setP(r); if (r.household) setHid(r.household); } catch (e) { setError(e); }
    finally { setBusy(false); }
  }
  async function apply(confirm = false) {
    if (!p || !hid) return;
    setBusy(true);
    try {
      const r = await pro.voiceApply(hid, p.actions, confirm);
      const bits = [r.containers.length && `${r.containers.length} container${r.containers.length > 1 ? "s" : ""} (${r.containers.map((b) => `#${b.number}`).join(" ")})`,
        r.cards.length && `${r.cards.length} reheat card`, r.tossed.length && `tossed ${r.tossed.join(", ")}`,
        r.eaten.length && `finished ${r.eaten.join(", ")}`, r.shopping.length && `${r.shopping.length} on their list`].filter(Boolean);
      setDone(`Saved: ${bits.join(" · ") || "nothing to change"}${r.skipped.length ? `. Skipped: ${r.skipped.join("; ")}` : ""}`);
      setP(null); setText("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setError(e); else setError(e);
    } finally { setBusy(false); }
  }
  const allergen = !!p && p.flags.length > 0;
  return (
    <Screen>
      <Header title="Voice note" />
      <View style={[s.card, { borderColor: c.kraftLight, alignItems: "center", gap: 10, paddingVertical: 20 }]}>
        <MicButton size={84} onText={setText} onDone={preview} />
        <Text style={[s.muted, { textAlign: "center" }]}>Tap and talk with messy hands. Or type below.</Text>
        <TextInput style={[s.input, { width: "100%", minHeight: 90 }]} multiline value={text} onChangeText={setText}
          placeholder={EXAMPLE} placeholderTextColor={c.muted} accessibilityLabel="What happened in the kitchen" />
        <Button kind="pro" title="Check it" onPress={() => preview(text || EXAMPLE)} busy={busy} />
      </View>
      {home && home.clients.length > 1 ? (
        <Chips label="Kitchen" options={home.clients.map((x) => ({ id: x.household_id, label: x.name }))} value={hid ?? null}
          multi={false} onChange={(v) => { setHid(v[0]); if (p) setP({ ...p, household: v[0] }); }} />) : null}
      {p ? (
        <View style={s.card}>
          <Text style={s.h2}>{p.household_name ? `For ${p.household_name}` : "Which kitchen?"}</Text>
          <Text style={s.body}>💬 {p.say}</Text>
          {p.actions.map((a, i) => (
            <View key={i} style={[s.row, { paddingVertical: 4 }]}>
              <Text style={{ fontSize: 18 }}>{ICON[a.kind]}</Text>
              <Text style={[s.body, { flex: 1 }]}>
                {a.kind === "made" ? `${a.portions} portions of ${a.dish} → ${a.containers?.map((x) => `${x.portions} ${x.location}`).join(", ")}`
                  : a.kind === "reheat" ? `Reheat card: ${a.method}${a.temp_f ? ` ${a.temp_f}°F` : ""}, ${a.minutes} min${a.covered ? ", covered" : ""}`
                  : a.kind === "shop" ? `Add ${a.item} to their list`
                  : `${a.kind === "toss" ? "Toss" : "Finished"} ${a.what}${a.match ? ` (${a.match})` : " — no container matches"}`}
              </Text>
              {a.warning ? <Pill text={a.warning} tone="amber" /> : null}
            </View>))}
          {p.unparsed.length ? <Text style={s.muted}>Didn't catch: “{p.unparsed.join("”, “")}”</Text> : null}
          {p.flags.map((f) => <Hazard key={f} text={f} />)}
          <Button kind="pro" title={allergen ? "It's right: save with a Contains warning" : "Save all"} busy={busy}
            disabled={!hid || !p.actions.length} onPress={() => apply(allergen)} />
          <Button kind="ghost" title="Start over" onPress={() => setP(null)} />
        </View>) : null}
      {done ? (
        <View style={[s.card, { backgroundColor: c.primarySoft, borderColor: c.sageLight }]}>
          <Text style={s.body}>✅ {done}</Text>
          {hid ? <Button kind="ghost" title="Open their fridge" onPress={() => router.replace({ pathname: "/chef/client", params: { id: hid, tab: "fridge" } } as never)} /> : null}
        </View>) : null}
      <ErrorText error={error} />
    </Screen>
  );
}
