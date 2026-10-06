// Home: the household, savings so far, the Google Calendar feed, fridge printouts, and a flyer photo for specials.
import * as ImagePicker from "expo-image-picker";
import * as WebBrowser from "expo-web-browser";
import { useCallback, useState } from "react";
import { Share, Text, View } from "react-native";
import { router, useFocusEffect } from "expo-router";
import { api, Household, serverUrl, signOut } from "@/lib/api";
import { Button, ErrorText, money, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

type Flyer = Awaited<ReturnType<typeof api.flyer>>;

export default function Home() {
  const [hh, setHh] = useState<Household | null>(null);
  const [sav, setSav] = useState<Awaited<ReturnType<typeof api.savings>> | null>(null);
  const [base, setBase] = useState("");
  const [flyer, setFlyer] = useState<Flyer | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useFocusEffect(useCallback(() => {
    serverUrl().then(setBase);
    api.household().then(setHh).catch(setError);
    api.savings().then(setSav).catch(() => {});
  }, []));

  async function readFlyer(store: string) {
    const pick = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (pick.canceled) return;
    setBusy(true); setError(null);
    try { setFlyer(await api.flyer(store, pick.assets[0].uri)); } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function confirm(store: string) {
    if (!flyer) return;
    const ok = flyer.items.filter((i) => i.status === "needs_confirm" && i.ingredient && i.price != null)
      .map((i) => ({ ingredient: i.ingredient!, price: i.price! }));
    try { await api.confirmSpecials(store, ok); setFlyer(null); } catch (e) { setError(e); }
  }

  return (
    <Screen>
      <Text style={s.h1}>{hh?.name ?? "Home"}</Text>
      {sav ? (
        <View style={s.card}>
          <Text style={s.h2}>Saved so far</Text>
          <Text style={s.body}>{money(sav.dollars_saved)} and {Math.round(sav.minutes_saved / 60)} hours over {sav.weeks.length} {sav.weeks.length === 1 ? "week" : "weeks"}</Text>
          <Text style={s.muted}>Against buying the same list at your home store, regular prices, one trip; and your own
            estimate of planning time before Lil'Helper.</Text>
        </View>
      ) : null}
      {hh ? (
        <View style={s.card}>
          <Text style={s.h2}>Who's eating</Text>
          {hh.people.map((p) => <Text key={p.id} style={s.body}>{p.kid ? "🧒" : "🧑"} {p.name}
            {p.allergies.length ? <Text style={s.muted}>  allergic to {p.allergies.join(", ")}</Text> : null}</Text>)}
          {hh.pets.map((p) => <Text key={p.id} style={s.body}>🐕 {p.name} <Text style={s.muted}>{p.food}</Text></Text>)}
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>Calendar and fridge</Text>
        <Button kind="ghost" title="Copy the Google Calendar feed link" disabled={!hh}
          onPress={() => Share.share({ message: `${base}${hh?.calendar_feed}` })} />
        <Text style={s.muted}>In Google Calendar: Other calendars → From URL → paste. It updates itself.</Text>
        <Button kind="ghost" title="Print this week" onPress={() => WebBrowser.openBrowserAsync(`${base}/api/print/week.pdf`)} />
        <Button kind="ghost" title="Print this month" onPress={() => WebBrowser.openBrowserAsync(`${base}/api/print/month.pdf`)} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Specials from a flyer</Text>
        <Text style={s.muted}>Pick a photo of a store flyer. Nothing counts until you confirm it.</Text>
        <View style={s.row}>
          {(hh?.stores ?? []).filter((x) => x !== "costco").map((st) =>
            <View key={st} style={{ flex: 1 }}><Button kind="ghost" busy={busy} title={st.replace(/_/g, " ")}
              onPress={() => readFlyer(st)} /></View>)}
        </View>
        {flyer ? (
          <View style={{ gap: 4 }}>
            {flyer.flags.includes("instruction_on_flyer") ? <Text style={s.muted}>⚠️ The flyer had text that looked like
              an instruction. It was ignored.</Text> : null}
            {flyer.items.map((i, n) => <Text key={n} style={s.body}>{i.status === "needs_confirm" ? "✓" : "✗"} {i.text}
              <Text style={s.muted}> {i.price != null ? money(i.price) : ""} {i.why.join("; ")}</Text></Text>)}
            <Button title="Confirm these specials" onPress={() => confirm(flyer.store)} />
          </View>
        ) : null}
      </View>
      <Button kind="ghost" title="Sign out" onPress={async () => { await signOut(); router.replace("/signin"); }} />
      <ErrorText error={error} />
    </Screen>
  );
}
