// Bulk import and export (admin): everything the planner uses — household, people, occasions, recipes, ingredients
// with your brands, stores and prices, the fridge, pantry and freezer — in one Excel workbook. Edit it in Excel or
// Google Sheets, upload it, check what would change, then confirm. Nothing changes until you confirm.
import * as DocumentPicker from "expo-document-picker";
import * as Linking from "expo-linking";
import { useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { api, BulkChanges, BulkPreview } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { AdminNote, Button, ErrorText, Header, Screen } from "@/components/ui";
import { c, s } from "@/lib/theme";

const VERB = { add: "add", change: "change", remove: "remove" } as const;

function Changes({ changes }: { changes: BulkChanges }) {
  const sheets = Object.entries(changes);
  if (!sheets.length) return <Text style={s.body}>No changes: the workbook matches what's saved.</Text>;
  return <>{sheets.map(([sheet, acts]) => (
    <View key={sheet} style={{ gap: 2 }}>
      <Text style={s.h2}>{sheet}</Text>
      {(Object.keys(VERB) as (keyof typeof VERB)[]).filter((k) => acts[k]?.length).map((k) => (
        <Text key={k} style={s.body}>{VERB[k]} {acts[k]!.length}: <Text style={s.muted}>{acts[k]!.slice(0, 8).join(", ")}
          {acts[k]!.length > 8 ? ` and ${acts[k]!.length - 8} more` : ""}</Text></Text>))}
    </View>))}</>;
}

export default function Bulk() {
  const set = useSettings();
  const [preview, setPreview] = useState<BulkPreview | null>(null);
  const [done, setDone] = useState<BulkChanges | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  async function run(k: string, fn: () => Promise<void>) {
    setBusy(k); setError(null);
    try { await fn(); } catch (e) { setError(e); } finally { setBusy(null); }
  }
  return (
    <Screen>
      <Header title="Import and export" />
      <AdminNote role={set.role} />
      <View style={s.card}>
        <Text style={s.h2}>1. Download</Text>
        <Text style={s.muted}>One workbook with a sheet each for the household, people (birthdays, allergies, portions),
          occasions, your recipes and their ingredients (meals, calories, prep time, the age a kid can make it),
          ingredients (your brand, store and price), the fridge and pantry, and the freezer. The first sheet explains each
          column. DinnerPeace's own recipes are listed for reference and can't be changed.</Text>
        <Button title="Download the workbook" busy={busy === "dl"} disabled={!set.isAdmin}
          onPress={() => run("dl", async () => { const { url } = await api.bulkLink(); await Linking.openURL(url); })} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>2. Upload your changes</Text>
        <Text style={s.muted}>Add rows, edit them, or put "yes" in a row's remove column. You'll see what would change first.</Text>
        <Button kind="ghost" title="Choose the edited workbook" busy={busy === "up"} disabled={!set.isAdmin}
          onPress={() => run("up", async () => {
            setDone(null); setPreview(null);
            const pick = await DocumentPicker.getDocumentAsync({ type: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "*/*"] });
            if (pick.canceled) return;
            const a = pick.assets[0];
            setPreview(await api.bulkImport({ uri: a.uri, name: a.name, mimeType: a.mimeType, file: (a as { file?: File }).file }));
          })} />
      </View>
      {preview ? (
        <View style={[s.card, { borderColor: c.green }]}>
          <Text style={s.h2}>3. Check and confirm</Text>
          <Changes changes={preview.changes} />
          {preview.problems.length ? <View style={[s.card, { backgroundColor: c.amberSoft }]}>
            <Text style={s.body}>Skipped (fix these in the workbook and upload again):</Text>
            {preview.problems.slice(0, 20).map((p, i) => <Text key={i} style={s.muted}>• {p}</Text>)}
          </View> : null}
          <View style={s.row}>
            <View style={{ flex: 1 }}><Button kind="ghost" title="Cancel" onPress={() => setPreview(null)} /></View>
            <View style={{ flex: 1 }}><Button title="Save these changes" busy={busy === "ok"} disabled={!Object.keys(preview.changes).length}
              onPress={() => run("ok", async () => { const r = await api.bulkConfirm(preview.token); setDone(r.changes); setPreview(null); })} /></View>
          </View>
        </View>
      ) : null}
      {done ? <View style={[s.card, { backgroundColor: c.greenSoft }]}><Text style={s.h2}>✓ Saved</Text><Changes changes={done} />
        <Text style={s.muted}>Draft plans pick these up the next time they're made or changed.</Text></View> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
