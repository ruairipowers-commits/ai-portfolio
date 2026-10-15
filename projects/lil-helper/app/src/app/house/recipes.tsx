// Recipes: the household's own first, then the built-in book. Tap to see one; add your own with the + button.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { api, RecipeRow } from "@/lib/api";
import { Button, Chips, ErrorText, Header, LinkRow, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

const MONTH = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Recipes() {
  const [rows, setRows] = useState<RecipeRow[]>([]);
  const [search, setSearch] = useState("");
  const [meal, setMeal] = useState("dinner");
  const [error, setError] = useState<unknown>(null);
  useFocusEffect(useCallback(() => { api.recipes({ meal }).then((r) => setRows(r.recipes)).catch(setError); }, [meal]));
  const shown = rows.filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()));
  const mine = shown.filter((r) => r.source === "household");
  const book = shown.filter((r) => r.source !== "household");
  const sub = (r: RecipeRow) => [`${r.active} min hands-on`, r.season_months?.length ? r.season_months.map((m) => MONTH[m]).join(" ") : "",
    r.want?.times ? `${r.want.times}× every ${r.want.per_weeks ?? 4} weeks` : "",
    r.kid_min_age ? `kids ${r.kid_min_age}+ can make` : "", r.credit ? `from ${r.credit}` : ""].filter(Boolean).join(" · ");
  const open = (id: string) => router.push({ pathname: "/house/recipe", params: { id } } as never);
  return (
    <Screen>
      <Header title="Recipes" />
      <Chips multi={false} options={["dinner", "lunch", "breakfast"]} value={meal} onChange={([m]) => setMeal(m)} />
      <TextInput style={s.input} placeholder="Search" value={search} onChangeText={setSearch} />
      <Button title="Add your own recipe" onPress={() => open("new")} />
      <View style={s.row}>
        <View style={{ flex: 1 }}><Button kind="ghost" title="🔎 From the web" onPress={() => router.push("/house/recipe-web" as never)} /></View>
        <View style={{ flex: 1 }}><Button kind="ghost" title="Share · import" onPress={() => router.push("/house/book" as never)} /></View>
      </View>
      {mine.length ? <View style={s.card}><Text style={s.h2}>Yours</Text>
        {mine.map((r) => <LinkRow key={r.id} icon="⭐" title={r.name} sub={sub(r)} onPress={() => open(r.id)} />)}</View> : null}
      <View style={s.card}><Text style={s.h2}>The book</Text>
        {book.map((r) => <LinkRow key={r.id} icon="📗" title={r.name} sub={sub(r)} onPress={() => open(r.id)} />)}</View>
      <ErrorText error={error} />
    </Screen>
  );
}
