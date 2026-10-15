// Speech to text. On the phone it uses the system recogniser (Apple / Google) through expo-speech-recognition; on the
// web build, the browser's own (Chrome, Safari, Edge). Audio goes to the phone's or browser's recogniser, not to
// Lil'Helper; only the words come to the server. If neither exists (e.g. Expo Go), `available()` is false and the
// screens say to use the keyboard's microphone instead.
import { Platform } from "react-native";

type Native = {
  requestPermissionsAsync: () => Promise<{ granted: boolean }>;
  start: (o: Record<string, unknown>) => void;
  stop: () => void;
  abort: () => void;
  addListener: (ev: string, fn: (e: any) => void) => { remove: () => void };  // eslint-disable-line @typescript-eslint/no-explicit-any
};

let native: Native | null | undefined;
function nativeModule(): Native | null {
  if (native !== undefined) return native;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    native = require("expo-speech-recognition").ExpoSpeechRecognitionModule as Native;
  } catch { native = null; }
  return native;
}

function webCtor(): any {  // eslint-disable-line @typescript-eslint/no-explicit-any
  const g = globalThis as any;  // eslint-disable-line @typescript-eslint/no-explicit-any
  return g.SpeechRecognition ?? g.webkitSpeechRecognition ?? null;
}

export function available(): boolean {
  return Platform.OS === "web" ? !!webCtor() : !!nativeModule();
}

export type Listen = { stop: () => void };

/** Listen once. onText gets the words so far (partial results), onDone the final words (or "" if nothing heard). */
export async function listen(onText: (t: string) => void, onDone: (t: string, error?: string) => void): Promise<Listen> {
  let last = "";
  if (Platform.OS === "web") {
    const Ctor = webCtor();
    if (!Ctor) { onDone("", "This browser can't listen. Try Chrome or Safari, or type instead."); return { stop: () => {} }; }
    const rec = new Ctor();
    rec.lang = "en-US"; rec.interimResults = true; rec.continuous = false;
    rec.onresult = (e: any) => {  // eslint-disable-line @typescript-eslint/no-explicit-any
      last = Array.from(e.results).map((r: any) => r[0].transcript).join(" ");  // eslint-disable-line @typescript-eslint/no-explicit-any
      onText(last);
    };
    rec.onerror = (e: { error: string }) => onDone(last, e.error === "not-allowed" ? "Microphone blocked: allow it in the browser." : undefined);
    rec.onend = () => onDone(last);
    rec.start();
    return { stop: () => rec.stop() };
  }
  const m = nativeModule();
  if (!m) { onDone("", "Use the microphone on the keyboard to talk instead."); return { stop: () => {} }; }
  const perm = await m.requestPermissionsAsync();
  if (!perm.granted) { onDone("", "Lil'Helper needs the microphone and speech recognition: turn them on in Settings."); return { stop: () => {} }; }
  let finished = false;
  const subs = [
    m.addListener("result", (e: { results: { transcript: string }[] }) => { last = e.results?.[0]?.transcript ?? last; onText(last); }),
    m.addListener("error", (e: { error: string; message: string }) => {
      if (!finished) { finished = true; cleanup(); onDone(last, e.error === "no-speech" ? undefined : e.message); } }),
    m.addListener("end", () => { if (!finished) { finished = true; cleanup(); onDone(last); } }),
  ];
  function cleanup() { subs.forEach((x) => x.remove()); }
  m.start({ lang: "en-US", interimResults: true, continuous: false, addsPunctuation: true,
    contextualStrings: ["Lil'Helper", "leftovers", "lunchbox", "buffet", "portions"] });
  return { stop: () => m.stop() };
}
