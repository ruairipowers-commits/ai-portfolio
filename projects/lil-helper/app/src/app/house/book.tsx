// Your recipe book, in and out: export it as a file, import one, share it with another household by code, or add
// the recipes another household shared with you. Only recipes go — never plans, people or anything else.
import * as DocumentPicker from "expo-document-picker";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, Share, TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, BookImport } from "@/lib/api";
import { Button, ErrorText, Header, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

function summary(r: BookImport) {
  return [`Added ${r.added} recipe${r.added === 1 ? "" : "s"}.`,
    r.skipped_same_name.length ? `Already had: ${r.skipped_same_name.join(", ")}.` : "",
    r.new_ingredients.length ? `New ingredients: ${r.new_ingredients.join(", ")}.` : "",
    r.failed.length ? `Couldn't add: ${r.failed.map((f) => `${f.name} (${f.why})`).join("; ")}.` : ""].filter(Boolean).join(" ");
}

export default function Book() {
  const params = useLocalSearchParams<{ code?: string }>();
  const [code, setCode] = useState(params.code ? String(params.code) : "");
  const [preview, setPreview] = useState<{ household: string; recipes: string[] } | null>(null);
  const [share, setShare] = useState<Awaited<ReturnType<typeof api.shareRecipes>> | null>(null);
  const [paste, setPaste] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const cleanCode = (x: string) => decodeURIComponent((x.match(/code=([^&\s]+)/)?.[1] ?? x).trim());

  async function run(key: string, fn: () => Promise<string | void>) {
    setBusy(key); setError(null); setMsg(null);
    try { const m = await fn(); if (m) setMsg(m); } catch (e) { setError(e); } finally { setBusy(null); }
  }
  useEffect(() => { if (params.code) run("peek", async () => { setPreview(await api.previewShared(cleanCode(String(params.code)))); }); }, [params.code]);

  async function exportBook() {
    const book = await api.exportRecipes();
    const text = JSON.stringify(book, null, 1);
    if (Platform.OS === "web") {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
      a.download = "lilhelper-recipes.json"; a.click();
    } else {
      await Share.share({ title: "Our DinnerPeace recipes", message: text });
    }
    return `Exported ${(book.recipes as unknown[]).length} recipes.`;
  }
  async function importFile() {
    const pick = await DocumentPicker.getDocumentAsync({ type: ["application/json", "text/plain", "*/*"] });
    if (pick.canceled) return;
    const a = pick.assets[0] as { uri: string; file?: File };
    const text = a.file ? await a.file.text() : await (await fetch(a.uri)).text();
    return summary(await api.importRecipes(JSON.parse(text)));
  }

  return (
    <Screen>
      <Header title="Share and import" />
      <View style={s.card}>
        <Text style={s.h2}>Share your recipes with another household</Text>
        <Text style={s.muted}>They get a copy of your own recipes (with who they're from). Your plans, people and
          spending are never shared.</Text>
        <Button title="Make a sharing code" busy={busy === "share"} onPress={() => run("share", async () => setShare(await api.shareRecipes()))} />
        {share ? <>
          <Text selectable style={[s.body, { fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 11 }]}>{share.code}</Text>
          <Button kind="ghost" title="Send the link" onPress={() => Share.share({ message: `Our DinnerPeace recipes: ${share.link}` })} />
          <Text style={s.muted}>{share.note}</Text>
        </> : null}
        <Button kind="ghost" title="Stop sharing (old codes stop working)" busy={busy === "stop"}
          onPress={() => run("stop", async () => { await api.stopSharing(); setShare(null); return "Sharing stopped."; })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Add recipes someone shared with you</Text>
        <TextInput style={s.input} placeholder="Paste their code or link" autoCapitalize="none" value={code} onChangeText={setCode} />
        <Button kind="ghost" title="Look" disabled={code.trim().length < 10} busy={busy === "peek"}
          onPress={() => run("peek", async () => setPreview(await api.previewShared(cleanCode(code))))} />
        {preview ? <>
          <Text style={s.body}>{preview.household}: {preview.recipes.length} recipes</Text>
          <Text style={s.muted}>{preview.recipes.slice(0, 12).join(" · ")}{preview.recipes.length > 12 ? " …" : ""}</Text>
          <Button title="Add them to our book" busy={busy === "imp"}
            onPress={() => run("imp", async () => { const r = await api.importShared(cleanCode(code)); setPreview(null); return summary(r); })} />
        </> : null}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Export and import a file</Text>
        <Button kind="ghost" title="Export our recipes" busy={busy === "exp"} onPress={() => run("exp", exportBook)} />
        <Button kind="ghost" title="Import a recipe file" busy={busy === "file"} onPress={() => run("file", importFile)} />
        <TextInput style={[s.input, { minHeight: 60, textAlignVertical: "top" }]} multiline placeholder="…or paste the file's text"
          value={paste} onChangeText={setPaste} />
        <Button kind="ghost" title="Import the pasted text" disabled={paste.trim().length < 20} busy={busy === "paste"}
          onPress={() => run("paste", async () => summary(await api.importRecipes(JSON.parse(paste))))} />
      </View>
      {msg ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.body}>{msg}</Text></View> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
