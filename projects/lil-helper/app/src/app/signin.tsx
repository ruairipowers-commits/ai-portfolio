// Sign in with a one-time link: type your email, tap the link in the email (it opens the app via lilhelper://signin),
// or paste the link here. Only adults in the household can sign in; kids just see the fridge calendar.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Image, Text, TextInput, View } from "react-native";
import { api, serverUrl, setServerUrl } from "@/lib/api";
import { Button, ErrorText, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

export default function SignIn() {
  const params = useLocalSearchParams<{ token?: string }>();
  const [email, setEmail] = useState("");
  const [link, setLink] = useState("");
  const [server, setServer] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { serverUrl().then(setServer); }, []);
  useEffect(() => { if (params.token) finish(String(params.token)); }, [params.token]);

  async function finish(token: string) {
    setBusy(true); setError(null);
    try {
      await api.verify(token);
      router.replace("/");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function request() {
    setBusy(true); setError(null);
    try {
      await setServerUrl(server);
      setMsg((await api.requestLink(email)).message);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  return (
    <Screen>
      <View style={{ alignItems: "center", gap: 8, marginTop: 24 }}>
        <Image source={require("../../assets/icon.png")} style={{ width: 96, height: 96, borderRadius: 22 }} />
        <Text style={[s.h1, { fontSize: 30 }]}><Text style={{ color: c.red }}>Lil’</Text><Text style={{ color: c.green }}>Helper</Text></Text>
        <Text style={s.muted}>plan · shop · share the cooking</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Sign in</Text>
        <TextInput style={s.input} placeholder="your email" autoCapitalize="none" keyboardType="email-address"
          autoComplete="email" value={email} onChangeText={setEmail} />
        <Button title="Email me a sign-in link" onPress={request} busy={busy} disabled={!email.includes("@")} />
        {msg ? <Text style={s.muted}>{msg}</Text> : null}
      </View>
      <View style={s.card}>
        <Text style={s.muted}>Opened the email on another device? Paste the link:</Text>
        <TextInput style={s.input} placeholder="lilhelper://signin?token=…" autoCapitalize="none" value={link}
          onChangeText={setLink} />
        <Button kind="ghost" title="Use this link" disabled={!link.includes("token=")}
          onPress={() => finish(decodeURIComponent(link.split("token=")[1] ?? ""))} />
      </View>
      <View style={s.card}>
        <Text style={s.muted}>Your household's server</Text>
        <TextInput style={s.input} autoCapitalize="none" value={server} onChangeText={setServer} />
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
