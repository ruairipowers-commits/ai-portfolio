// Ingredient forecast: pick something the next few weeks' plans use; see how much you'll need, what's on hand, which
// shopping trip to buy it on, how much to buy, and where it's cheapest.
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api, Forecast } from "@/lib/api";
import { Chips, ErrorText, Header, LinkRow, money, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

type Row = Awaited<ReturnType<typeof api.forecastList>>["ingredients"][number];
const date = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

export default function ForecastScreen() {
  const [weeks, setWeeks] = useState(4);
  const [rows, setRows] = useState<Row[]>([]);
  const [f, setF] = useState<Forecast | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    setBusy(true); setF(null);
    api.forecastList(weeks).then((r) => setRows(r.ingredients)).catch(setError).finally(() => setBusy(false));
  }, [weeks]);
  const pick = (id: string) => api.forecast(id, weeks).then(setF).catch(setError);
  return (
    <Screen>
      <Header title="Ingredient forecast" />
      <Chips multi={false} options={[{ id: "2", label: "2 weeks" }, { id: "4", label: "4 weeks" }, { id: "6", label: "6 weeks" }]}
        value={String(weeks)} onChange={([w]) => setWeeks(Number(w))} />
      {f ? (
        <>
          <View style={s.card}>
            <Text style={s.h2}>{f.name}</Text>
            <Text style={s.body}>Need {round(f.need_total)} {f.unit} over {weeks} weeks · on hand {round(f.on_hand + f.on_hand_frozen)} {f.unit}</Text>
            <Text style={s.muted}>Keeps about {f.keeps_days} days in the {f.storage}{f.freezable ? "; freezes well" : ""}.</Text>
          </View>
          <View style={s.card}>
            <Text style={s.h2}>When to buy</Text>
            {f.planned_purchases.map((p, i) => <Text key={`p${i}`} style={s.body}>✓ {date(p.date)}: {p.packs} × {round(p.qty / p.packs)} {f.unit}
              <Text style={s.muted}> at {p.store} ({p.mode.replace("_", " ")}) · already on that list</Text></Text>)}
            {f.buys.map((b, i) => <Text key={`b${i}`} style={s.body}>🛒 {date(b.date)}: {b.packs} × {b.pack} {f.unit}
              <Text style={s.muted}> at {b.store}{b.mode !== "any" ? ` (${b.mode.replace("_", " ")})` : ""} · {money(b.cost)}
              {b.special ? " · on special" : ""} · for {b.for} · {b.keep_note}</Text></Text>)}
            {!f.planned_purchases.length && !f.buys.length ? <Text style={s.muted}>Nothing to buy: what's on hand covers it.</Text> : null}
            <Text style={s.muted}>Left at the end: {round(f.end_stock)} {f.unit}</Text>
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Uses</Text>
            {f.uses.map((u, i) => <Text key={i} style={s.body}>{date(u.date)}: {round(u.qty)} {f.unit} <Text style={s.muted}>{u.meal}</Text></Text>)}
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Prices</Text>
            {f.prices.slice(0, 6).map((p, i) => <Text key={i} style={s.body}>{p.store} <Text style={s.muted}>{p.brand} · {p.pack} {f.unit} for {money(p.price)}
              {" "}({money(p.per_unit)}/{f.unit}){p.special ? " · special" : ""}{p.channel !== "any" ? ` · ${p.channel.replace("_", " ")}` : ""}</Text></Text>)}
            {f.tips.map((t, i) => <Text key={i} style={s.muted}>💡 {t}</Text>)}
          </View>
          <LinkRow icon="↩︎" title="Pick another ingredient" onPress={() => setF(null)} />
        </>
      ) : (
        <View style={s.card}>
          <Text style={s.muted}>{busy ? "Looking at the plans…" : "Most used in the coming weeks:"}</Text>
          {rows.map((r) => <LinkRow key={r.ingredient} icon="🥕" title={r.name}
            sub={`${round(r.qty)} ${r.unit} · ${r.meals} meal${r.meals === 1 ? "" : "s"} · ~${money(r.est_cost)}`} onPress={() => pick(r.ingredient)} />)}
        </View>
      )}
      <ErrorText error={error} />
    </Screen>
  );
}

const round = (n: number) => Math.round(n * 100) / 100;
