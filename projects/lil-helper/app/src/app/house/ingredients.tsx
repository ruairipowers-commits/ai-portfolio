// Ingredients: search anything DinnerPeace knows (and your own), and set your brand, store and price for it.
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api } from "@/lib/api";
import { useSettings } from "@/lib/useSettings";
import { ErrorText, Header, LinkRow, Screen, Toggle } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Ingredients() {
  const set = useSettings();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.ingredients>>["ingredients"]>([]);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { const t = setTimeout(() => api.ingredients(q).then((r) => setRows(r.ingredients)).catch(setError), 200);
    return () => clearTimeout(t); }, [q]);
  const prefs = (set.st.ingredient_prefs ?? {}) as Record<string, { brand?: string; store?: string; price?: number }>;
  const useBook = set.st.use_book?.recipes !== false;
  const mine = rows.filter((r) => prefs[r.id]);
  return (
    <Screen>
      <Header title="Ingredients" />
      <View style={s.card}>
        <Toggle label="Use DinnerPeace's recipe book" value={useBook}
          hint={set.isAdmin ? "Off: plans use only your own recipes. Prices: DinnerPeace's indicative prices are used unless you set your own below."
            : "Only the admin can change this."}
          onChange={(v) => set.isAdmin && set.save("use_book", { ...(set.st.use_book ?? {}), recipes: v })} />
      </View>
      <TextInput style={s.input} placeholder="Search: chicken, milk, rice…" value={q} onChangeText={setQ} autoCapitalize="none" />
      {mine.length ? <View style={s.card}><Text style={s.h2}>Your choices</Text>
        {mine.map((r) => <LinkRow key={r.id} icon="⭐" title={r.name}
          sub={[prefs[r.id].brand, prefs[r.id].store, prefs[r.id].price ? `$${prefs[r.id].price}` : ""].filter(Boolean).join(" · ")}
          onPress={() => router.push({ pathname: "/house/ingredient", params: { id: r.id } } as never)} />)}</View> : null}
      <View style={s.card}>
        {rows.filter((r) => !prefs[r.id]).map((r) => <LinkRow key={r.id} icon={r.source === "household" ? "🏠" : "🥕"} title={r.name}
          sub={`${r.cat} · per ${r.unit}`} onPress={() => router.push({ pathname: "/house/ingredient", params: { id: r.id } } as never)} />)}
      </View>
      <ErrorText error={error ?? set.error} />
    </Screen>
  );
}
