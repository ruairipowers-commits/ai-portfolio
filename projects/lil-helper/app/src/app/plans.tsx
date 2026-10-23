// Plans: Dinner Peace for families (Free, Family) and Dinner Peace Pro for personal chefs (Solo, Studio). Prices, period
// and renewal terms are on the page itself, with links to Terms and Privacy (App Store Guideline 3.1.2). Purchases go
// through the App Store with the production release; until then a plan is turned on by the server's admin.
import * as WebBrowser from "expo-web-browser";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/text";
import { Plans, pro } from "@/lib/api";
import { Button, ErrorText, Header, Screen } from "@/components/ui";
import { ProBadge } from "@/components/chef";
import { c, s } from "@/lib/theme";

export default function PlansScreen() {
  const { focus } = useLocalSearchParams<{ focus?: string }>();
  const [p, setP] = useState<Plans | null>(null);
  const [who, setWho] = useState<"chef" | "family">(focus?.startsWith("chef") ? "chef" : "family");
  const [yearly, setYearly] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { pro.plans().then((x) => { setP(x); if (!focus && x.chef_plan !== "none") setWho("chef"); }).catch(setError); }, [focus]);
  const ids = who === "chef" ? ["chef_solo", "chef_studio"] : ["free", "family"];
  const current = who === "chef" ? p?.chef_plan : p?.household?.plan === "beta" ? "family" : p?.household?.plan;
  return (
    <Screen>
      <Header title="Plans" />
      <View style={{ flexDirection: "row", backgroundColor: c.parchment, borderRadius: 16, padding: 4 }}>
        {(["family", "chef"] as const).map((k) => (
          <Pressable key={k} onPress={() => setWho(k)} style={{ flex: 1, paddingVertical: 9, borderRadius: 12, alignItems: "center",
            backgroundColor: who === k ? c.card : "transparent" }} accessibilityRole="tab" accessibilityState={{ selected: who === k }}>
            <Text style={{ fontWeight: "800", color: who === k ? (k === "chef" ? c.pro : c.primary) : c.muted }}>
              {k === "chef" ? "For personal chefs" : "For families"}</Text>
          </Pressable>))}
      </View>
      <Pressable onPress={() => setYearly(!yearly)} style={[s.row, { justifyContent: "center" }]} accessibilityRole="switch"
        accessibilityState={{ checked: yearly }}>
        <Text style={[s.body, { fontWeight: yearly ? "400" : "800" }]}>Monthly</Text>
        <View style={{ width: 44, height: 26, borderRadius: 13, backgroundColor: yearly ? c.primary : c.line, padding: 3 }}>
          <View style={{ width: 20, height: 20, borderRadius: 10, backgroundColor: c.card, marginLeft: yearly ? 18 : 0 }} />
        </View>
        <Text style={[s.body, { fontWeight: yearly ? "800" : "400" }]}>Yearly</Text>
      </Pressable>
      {p ? ids.map((id) => {
        const t = p.tiers[id];
        const featured = id === "family" || id === "chef_studio";
        const price = yearly ? t.yearly : t.monthly;
        const mine = current === id;
        return (
          <View key={id} style={[s.card, featured && { borderColor: who === "chef" ? c.kraft : c.sage, borderWidth: 2 }, focus === id && { borderColor: c.pro }]}>
            <View style={s.between}>
              <Text style={s.h2}>{t.label}</Text>
              {mine ? <ProBadge text="YOUR PLAN" /> : featured ? <ProBadge text={who === "chef" ? "MOST CHEFS" : "MOST PEACEFUL"} /> : null}
            </View>
            <Text style={{ fontSize: 32, fontWeight: "900", color: c.ink }}>{price ? `$${price % 1 ? price.toFixed(2) : price}` : "$0"}
              <Text style={s.muted}>{price ? (yearly ? " / year" : " / month") : " forever"}</Text></Text>
            {yearly && price ? <Text style={s.muted}>${(price / 12).toFixed(2)} a month, billed yearly</Text> : null}
            <Text style={s.body}>{t.blurb}</Text>
            {(() => {
              const below = ids[ids.indexOf(id) - 1];
              const prev = below ? new Set(p.tiers[below].features) : new Set<string>();
              const extra = t.features.filter((f) => !prev.has(f));
              return <>
                {below && below !== "free" ? <Text style={[s.body, { fontWeight: "800" }]}>Everything in {p.tiers[below].label}, plus:</Text> : null}
                {extra.map((f) => <Text key={f} style={s.body}>✓ {f}</Text>)}
              </>;
            })()}
            {id === "free" ? <Text style={s.body}>✓ Every allergy and pet-safety rule (never behind a plan)</Text> : null}
            {who === "family" ? <Text style={s.muted}>Free for your family while your personal chef is on Dinner Peace Pro.</Text> : null}
            {!mine && price ? <Button kind={who === "chef" ? "pro" : "primary"} title={current && (p.tiers[current]?.rank ?? 0) > t.rank ? `Switch to ${t.label}` : `Choose ${t.label}`} onPress={() =>
              setNote(p.billing === "revenuecat" ? "Opening the App Store…" :
                "Subscriptions open with the App Store release. During the beta, ask Ruairi to turn this plan on for your account.")} /> : null}
          </View>);
      }) : null}
      {note ? <View style={[s.card, { backgroundColor: c.proSoft }]}><Text style={s.body}>{note}</Text></View> : null}
      <Text style={s.muted}>Subscriptions renew automatically at the price shown until cancelled in your App Store settings,
        at least 24 hours before the period ends. Family members you invite never pay.</Text>
      {p ? <View style={[s.row, { justifyContent: "center" }]}>
        <Button kind="ghost" title="Terms" onPress={() => WebBrowser.openBrowserAsync(p.terms_url)} />
        <Button kind="ghost" title="Privacy" onPress={() => WebBrowser.openBrowserAsync(p.privacy_url)} />
      </View> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
