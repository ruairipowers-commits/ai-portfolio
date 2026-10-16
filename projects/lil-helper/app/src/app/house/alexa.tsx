// Alexa: link your Amazon Alexa to DinnerPeace with a one-time code, then "Alexa, ask DinnerPeace what's for dinner".
import * as Clipboard from "expo-clipboard";
import { useCallback, useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "@/lib/api";
import { Button, ErrorText, Header, Pill, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const SAY = ["what's for dinner?", "what's on the shopping list?", "what are my jobs?", "I have chicken, rice and broccoli",
  "I have 30 minutes and want something cozy", "surprise me", "we have 3 portions of overnight oats left",
  "dinner was all gone", "rate dinner 5 stars"];

export default function Alexa() {
  const [st, setSt] = useState<Awaited<ReturnType<typeof api.alexa>> | null>(null);
  const [code, setCode] = useState<{ code: string; minutes: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => { api.alexa().then(setSt).catch(setError); }, []);
  useEffect(load, [load]);
  return (
    <Screen>
      <Header title="Alexa" />
      <View style={s.card}>
        <View style={s.between}><Text style={s.h2}>🔊 DinnerPeace on Alexa</Text>
          {st?.links.length ? <Pill text="Linked" /> : <Pill text="Not linked" tone="amber" />}</View>
        <Text style={s.muted}>Say “Alexa, ask DinnerPeace…”</Text>
        {SAY.map((x) => <Text key={x} style={s.body}>• {x}</Text>)}
        <Text style={s.muted}>Alexa answers for you (your jobs, your household). It can't buy anything; a week planned by
          voice waits for an adult to approve it here.</Text>
      </View>
      {st && !st.configured ? <View style={[s.card, { backgroundColor: c.amberSoft }]}><Text style={s.body}>The skill isn't set up
        on this server yet. Whoever runs your DinnerPeace server can follow docs/alexa.md (about 20 minutes, once).</Text></View> : null}
      <View style={s.card}>
        <Text style={s.h2}>Link your Alexa</Text>
        <Text style={s.muted}>1. Get a code here. 2. In the Alexa app: More → Skills & Games → DinnerPeace → Enable, and
          type the code when asked. Codes work once, for ten minutes.</Text>
        {code ? <View style={{ alignItems: "center", gap: 4 }}>
          <Text selectable style={{ fontSize: 34, fontWeight: "800", letterSpacing: 6, color: c.ink }}>{code.code}</Text>
          <Text style={s.muted}>good for {code.minutes} minutes</Text>
          <Button kind="ghost" title="Copy" onPress={() => Clipboard.setStringAsync(code.code)} />
        </View> : null}
        <Button title={code ? "Get a new code" : "Get a code"} onPress={async () => {
          try { setCode(await api.alexaCode()); } catch (e) { setError(e); } }} />
      </View>
      {st?.links.length ? <View style={s.card}>
        <Text style={s.muted}>Linked {st.links.length === 1 ? "once" : `${st.links.length} times`}
          {st.links[0].last_used ? `, last used ${st.links[0].last_used.slice(0, 10)}` : ""}.</Text>
        <Button kind="ghost" title="Unlink Alexa" onPress={async () => {
          try { await api.alexaUnlink(); setCode(null); load(); } catch (e) { setError(e); } }} />
      </View> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
