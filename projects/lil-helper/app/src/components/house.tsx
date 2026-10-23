// Pieces shared by the welcome wizard and the Settings screens.
import * as Clipboard from "expo-clipboard";
import * as Linking from "expo-linking";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { api, DAY_SHORT, DAYS } from "@/lib/api";
import { enablePush, PushState, pushState } from "@/lib/push";
import { useSettings } from "@/lib/useSettings";
import { Button, Chips, ErrorText, Field, Pill } from "@/components/ui";
import { c, s } from "@/lib/theme";

type S = ReturnType<typeof useSettings>;

// ---- shopping trips: when, where, how, who
export function TripsEditor({ set, onSaved }: { set: S; onSaved?: () => void }) {
  const { st, cat } = set;
  type Trip = { day: string; time: string; store: string; mode: string; who?: string };
  const [trips, setTrips] = useState<Trip[]>(st.shopping_sessions ?? []);
  const stores = (cat?.stores ?? []).filter((x) => (st.stores ?? []).includes(x.id));
  const adults = Object.entries(st.people ?? {}).filter(([, p]: [string, any]) => p.age_band !== "kid");
  const upd = (i: number, t: Partial<Trip>) => setTrips(trips.map((x, j) => j === i ? { ...x, ...t } : x));
  return (
    <>
      {trips.map((t, i) => {
        const modes = stores.find((x) => x.id === t.store)?.modes ?? ["in_store"];
        return (
          <View key={i} style={s.card}>
            <View style={s.between}><Text style={s.h2}>Trip {i + 1}</Text>
              <Pressable onPress={() => setTrips(trips.filter((_, j) => j !== i))}><Text style={{ color: c.red }}>Remove</Text></Pressable></View>
            <Chips label="Day" multi={false} value={t.day} onChange={([day]) => upd(i, { day })}
              options={["sun_before", ...DAYS].map((d) => ({ id: d, label: DAY_SHORT[d] }))} />
            <Field label="Time" value={t.time} onChangeText={(time) => upd(i, { time })} placeholder="10:00" />
            <Chips label="Store" multi={false} value={t.store} options={stores.map((x) => ({ id: x.id, label: x.name }))}
              onChange={([store]) => upd(i, { store, mode: (stores.find((x) => x.id === store)?.modes ?? ["in_store"])[0] })} />
            <Chips label="How" multi={false} value={t.mode} options={modes.map((m) => ({ id: m, label: m.replace("_", " ") }))}
              onChange={([mode]) => upd(i, { mode })} />
            <Chips label="Who goes" multi={false} value={t.who ?? ""}
              options={[{ id: "", label: "Anyone" }, ...adults.map(([pid, p]: [string, any]) => ({ id: pid, label: p.name }))]}
              onChange={([who]) => upd(i, { who: who || undefined })} />
          </View>
        );
      })}
      <Button kind="ghost" title="Add a trip" disabled={!stores.length}
        onPress={() => setTrips([...trips, { day: "sun_before", time: "10:00", store: stores[0]?.id, mode: stores[0]?.modes[0] ?? "in_store" }])} />
      <Button title="Save trips" busy={set.busy} onPress={async () => {
        if (await set.save("shopping_sessions", trips.map((t) => Object.fromEntries(Object.entries(t).filter(([, v]) => v))))) onSaved?.();
      }} />
    </>
  );
}

// ---- calendar and notifications
export function LoopCard() {
  const [cal, setCal] = useState<Awaited<ReturnType<typeof api.calendarLink>> | null>(null);
  const [push, setPush] = useState<PushState | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { api.calendarLink().then(setCal).catch(setError); pushState().then(setPush); }, []);
  return (
    <>
      <View style={s.card}>
        <Text style={s.h2}>📅 Your DinnerPeace calendar</Text>
        <Text style={s.muted}>Your dinners, jobs, lunches and shopping trips, in your own calendar. Each dinner has
          one-tap links to rate it and say how much is left. {cal?.note}</Text>
        <Button title="Add to Apple Calendar" disabled={!cal} onPress={() => cal && Linking.openURL(cal.webcal)} />
        <Button kind="ghost" title="Add to Google Calendar" disabled={!cal} onPress={() => cal && Linking.openURL(cal.google)} />
        <Button kind="ghost" title={copied ? "Copied ✓" : "Copy the link (Outlook and others)"} disabled={!cal}
          onPress={async () => { if (cal) { await Clipboard.setStringAsync(cal.https); setCopied(true); } }} />
        <Text style={s.muted}>The link is private to you. If it's ever shared by mistake, make a new one in Settings → Calendar.</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>🔔 Notifications</Text>
        <Text style={s.muted}>When next week's plan is ready, when someone changes tonight's dinner, an hour before
          your shopping trip, and a quick "how was dinner?"</Text>
        {push === "on" ? <Pill text="On for this phone" /> : push === "unsupported"
          ? <Text style={s.muted}>Notifications need the app on a phone.</Text>
          : push === "denied" ? <Text style={s.muted}>Turned off in iPhone Settings → DinnerPeace → Notifications.</Text>
          : <Button title="Turn on notifications" onPress={async () => {
            try { setPush(await enablePush()); } catch (e) { setError(e); } }} />}
      </View>
      <ErrorText error={error} />
    </>
  );
}

