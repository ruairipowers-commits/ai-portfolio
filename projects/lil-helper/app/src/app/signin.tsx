// Sign in with a one-time link: type your email, tap the link in the email (it opens the app via lilhelper://signin),
// or paste the link here. An invite link carries the household too, so you land straight in it.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Image, TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, serverUrl, setServerUrl } from "@/lib/api";
import { Button, ErrorText, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function SignIn() {
  const params = useLocalSearchParams<{ token?: string; invite?: string }>();
  const [email, setEmail] = useState("");
  const [link, setLink] = useState("");
  const [server, setServer] = useState("");
  const [showServer, setShowServer] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { serverUrl().then(setServer); }, []);
  useEffect(() => { if (params.token) finish(String(params.token), params.invite ? String(params.invite) : undefined); },
    [params.token]);

  async function finish(token: string, invite?: string) {
    setBusy(true); setError(null);
    try {
      const r = await api.verify(token, invite);
      router.replace(r.household ? "/" : "/welcome");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function request() {
    setBusy(true); setError(null);
    try {
      await setServerUrl(server);
      setMsg((await api.requestLink(email)).message);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  function usePasted() {
    const u = link.trim();
    const get = (k: string) => { const m = u.match(new RegExp(`[?&]${k}=([^&]+)`)); return m ? decodeURIComponent(m[1]) : undefined; };
    const token = get("token");
    if (token) finish(token, get("invite"));
  }

  return (
    <Screen>
      <View style={{ alignItems: "center", gap: 8, marginTop: 24 }}>
        <Image source={require("../../assets/icon.png")} style={{ width: 96, height: 96, borderRadius: 24 }} />
        <Text style={[s.h1, { fontSize: 30 }]}>Dinner<Text style={{ color: c.primary }}>Peace</Text></Text>
        <Text style={s.muted}>calm weeknight dinners · and Pro for personal chefs</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Sign in or get started</Text>
        <Text style={s.muted}>New here? Sign in with your email first; the next screen sets up your household.</Text>
        <TextInput style={s.input} placeholder="your email" autoCapitalize="none" keyboardType="email-address"
          autoComplete="email" value={email} onChangeText={setEmail} />
        <Button title="Email me a sign-in link" onPress={request} busy={busy} disabled={!email.includes("@")} />
        {msg ? <Text style={s.muted}>{msg}</Text> : null}
      </View>
      <View style={s.card}>
        <Text style={s.muted}>Opened the email on another device? Paste the link:</Text>
        <TextInput style={s.input} placeholder="lilhelper://signin?token=…" autoCapitalize="none" value={link}
          onChangeText={setLink} />
        <Button kind="ghost" title="Use this link" disabled={!link.includes("token=")} onPress={usePasted} />
      </View>
      {showServer ? (
        <View style={s.card}>
          <Text style={s.muted}>Server (only if you run your own)</Text>
          <TextInput style={s.input} autoCapitalize="none" value={server} onChangeText={setServer} />
        </View>
      ) : <Button kind="ghost" title="Use my own server" onPress={() => setShowServer(true)} />}
      <ErrorText error={error} />
    </Screen>
  );
}
