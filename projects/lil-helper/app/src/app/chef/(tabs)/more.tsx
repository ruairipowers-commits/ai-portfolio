// The chef's settings: plan, cards (names only), stores and memberships, label branding (Studio), coverage packs,
// switching into a client's family app, and the account.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { api, ChefHome, pro, signOut } from "@/lib/api";
import { mode } from "@/lib/mode";
import { Button, Chips, ErrorText, Field, LinkRow, Pill, Screen } from "@/components/ui";
import { ProBadge } from "@/components/chef";
import { c, s } from "@/lib/theme";

const CARDS = [{ id: "amex_gold", label: "Amex Gold" }, { id: "amex_blue_cash_everyday", label: "Amex Blue Cash Everyday" },
  { id: "amex_platinum", label: "Amex Platinum" }, { id: "costco_anywhere_visa", label: "Costco Anywhere Visa" }];
const STORES = [{ id: "costco", label: "Costco" }, { id: "whole_foods", label: "Whole Foods" },
  { id: "trader_joes", label: "Trader Joe's" }, { id: "stop_and_shop", label: "Stop & Shop" }];

export default function ChefMore() {
  const [h, setH] = useState<ChefHome | null>(null);
  const [cards, setCards] = useState<string[]>([]);
  const [stores, setStores] = useState<string[]>([]);
  const [business, setBusiness] = useState("");
  const [footer, setFooter] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  useFocusEffect(useCallback(() => {
    pro.home().then((x) => { setH(x); setCards(x.cards); setStores(x.stores); setBusiness(x.branding.business);
      setFooter(x.branding.footer); }).catch(setError);
    api.me().then((m) => setEmail(m.user.email)).catch(() => {});
  }, []));
  useEffect(() => { mode.family = false; }, []);
  const save = (b: Parameters<typeof pro.settings>[0]) => async () => {
    setMsg(null); setError(null);
    try { setH(await pro.settings(b)); setMsg("Saved"); } catch (e) { setError(e); }
  };
  return (
    <Screen>
      <View style={s.between}><Text style={s.h1}>More</Text>{h ? <ProBadge text={h.label.toUpperCase()} /> : null}</View>
      <View style={s.card}>
        <LinkRow icon="✨" title="Your plan" sub={h ? `${h.label}${h.client_limit != null ? ` · up to ${h.client_limit} homes` : " · unlimited homes"}` : ""}
          onPress={() => router.push("/plans" as never)} />
        <LinkRow icon="🧑‍🤝‍🧑" title="Coverage packs" sub="A backup chef's password-protected, expiring brief" onPress={() => router.push("/chef/coverage" as never)} />
        <LinkRow icon="🔎" title="Find households" sub="Your public profile, families nearby, requests to meet" onPress={() => router.push("/chef/find" as never)} />
        <LinkRow icon="🎙️" title="Voice note" sub="Log fridge, reheat cards and their list hands-free" onPress={() => router.push("/chef/voice" as never)} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Your cards</Text>
        <Text style={s.muted}>Names only. The shopping run picks the one that earns the most at each store.</Text>
        <Chips options={CARDS} value={cards} onChange={setCards} />
        <Text style={s.h2}>Where you shop</Text>
        <Chips options={STORES} value={stores} onChange={setStores} />
        <Button kind="pro" title="Save cards and stores" onPress={save({ cards, stores })} disabled={!stores.length} />
      </View>
      <View style={s.card}>
        <View style={s.between}><Text style={s.h2}>Labels and emails</Text>{!h?.features.branding ? <Pill tone="pro" text="Studio" /> : null}</View>
        <Field label="Business name" value={business} onChangeText={setBusiness} placeholder="Ruairi's Kitchen" editable={!!h?.features.branding} />
        <Field label="Footer" value={footer} onChangeText={setFooter} placeholder="Questions? Text Chef Ruairi." editable={!!h?.features.branding} />
        {h?.features.branding ? <Button kind="ghost" title="Save branding" onPress={save({ business, footer })} />
          : <Button kind="pro" title="See Chef Studio" onPress={() => router.push({ pathname: "/plans", params: { focus: "chef_studio" } } as never)} />}
      </View>
      {h?.clients.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Open a client's family app</Text>
          <Text style={s.muted}>See their week, recipes and list as they do (you can't change their admin settings once they've joined).</Text>
          {h.clients.map((cl) => <LinkRow key={cl.household_id} icon="🏡" title={cl.name} onPress={async () => {
            await api.switchHousehold(cl.household_id); mode.family = true; router.replace("/(tabs)" as never);
          }} />)}
        </View>) : null}
      <View style={s.card}>
        <LinkRow icon="⚙️" title="Account" sub={email} onPress={() => router.push("/house/account" as never)} />
        <Button kind="ghost" title="Sign out" onPress={async () => { await signOut(); router.replace("/signin"); }} />
      </View>
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
      <Text style={[s.muted, { textAlign: "center", color: c.spoon }]}>Dinner Peace Pro</Text>
    </Screen>
  );
}
