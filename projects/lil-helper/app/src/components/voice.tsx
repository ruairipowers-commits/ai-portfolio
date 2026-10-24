// The microphone. <MicButton> fills any text box by voice; <VoiceBar> is "ask DinnerPeace": say (or type) what you
// want, the server works out what it means (/api/voice), says what it did, and opens the right screen.
import { router } from "expo-router";
import { useRef, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, VoiceReply } from "@/lib/api";
import { available, listen, Listen } from "@/lib/speech";
import { c, s } from "@/lib/theme";

export function MicButton({ onText, onDone, size = 44 }: { onText: (t: string) => void; onDone?: (t: string) => void;
  size?: number }) {
  const [on, setOn] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const h = useRef<Listen | null>(null);
  if (!available()) return null;
  async function toggle() {
    if (on) { h.current?.stop(); return; }
    setMsg(null); setOn(true);
    h.current = await listen(onText, (t, err) => { setOn(false); if (err) setMsg(err); if (t) onDone?.(t); });
  }
  return (
    <View style={{ alignItems: "center" }}>
      <Pressable accessibilityRole="button" accessibilityLabel={on ? "Stop listening" : "Talk"} onPress={toggle}
        style={{ width: size, height: size, borderRadius: size / 2, alignItems: "center", justifyContent: "center",
          backgroundColor: on ? c.carrot : c.primarySoft, borderWidth: 1, borderColor: on ? c.carrot : c.sage }}>
        <Text style={{ fontSize: size * 0.45 }}>{on ? "⏹" : "🎤"}</Text>
      </Pressable>
      {msg ? <Text style={[s.muted, { maxWidth: 160, textAlign: "center" }]}>{msg}</Text> : null}
    </View>
  );
}

const SCREEN: Record<string, string> = { week: "/plan", shopping: "/shopping", jobs: "/jobs", cookfrom: "/house/cookfrom",
  vibe: "/house/vibe", surprise: "/house/surprise", buffet: "/house/buffet" };

export function VoiceBar({ hint = "What's for dinner? · I have chicken and rice · 3 portions of oats left" }: { hint?: string }) {
  const [text, setText] = useState("");
  const [reply, setReply] = useState<VoiceReply | null>(null);
  const [busy, setBusy] = useState(false);
  async function ask(t: string) {
    if (!t.trim()) return;
    setBusy(true);
    try { setReply(await api.voice(t)); setText(""); }
    catch (e) { setReply({ intent: "error", heard: t, say: e instanceof Error ? e.message : String(e), screen: null, params: {} }); }
    finally { setBusy(false); }
  }
  const to = reply?.screen ? SCREEN[reply.screen] : null;
  return (
    <View style={[s.card, { backgroundColor: c.card, borderColor: c.sageLight }]}>
      <View style={s.row}>
        <TextInput style={[s.input, { flex: 1 }]} value={text} onChangeText={setText} placeholder="Ask DinnerPeace…"
          returnKeyType="send" onSubmitEditing={() => ask(text)} editable={!busy} accessibilityLabel="Ask DinnerPeace" />
        <MicButton onText={setText} onDone={ask} />
      </View>
      {!reply ? <Text style={s.muted}>{busy ? "Thinking…" : hint}</Text> : (
        <View style={{ gap: 4 }}>
          <Text style={s.muted}>“{reply.heard}”</Text>
          <Text style={s.body}>💬 {reply.say}</Text>
          {to ? <Pressable onPress={() => router.push({ pathname: to as never, params: reply.params })}>
            <Text style={{ color: c.primary, fontWeight: "700" }}>Open ›</Text></Pressable> : null}
        </View>
      )}
    </View>
  );
}
