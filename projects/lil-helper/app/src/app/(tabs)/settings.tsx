// Home: the household at a glance, and the way into everything else: people, settings, recipes, specials, the
// calendar, money and planning tools. Admin-only settings are visible to everyone but only the admin can change them.
import * as WebBrowser from "expo-web-browser";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { api, Me, serverUrl, signOut } from "@/lib/api";
import { Button, ErrorText, LinkRow, money, Pill, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [sav, setSav] = useState<Awaited<ReturnType<typeof api.savings>> | null>(null);
  const [base, setBase] = useState("");
  const [error, setError] = useState<unknown>(null);

  useFocusEffect(useCallback(() => {
    serverUrl().then(setBase);
    api.me().then(setMe).catch(setError);
    api.savings().then(setSav).catch(() => {});
  }, []));

  const cur = me?.current;
  const go = (p: string) => () => router.push(p as never);
  const adult = cur?.role !== "kid";
  return (
    <Screen>
      <View style={s.between}>
        <Text style={s.h1}>{cur?.name ?? "Home"}</Text>
        {cur ? <Pill text={cur.role} tone={cur.role === "admin" ? "green" : "amber"} /> : null}
      </View>
      {sav && sav.weeks.length ? (
        <View style={s.card}>
          <Text style={s.h2}>Saved so far</Text>
          <Text style={s.body}>{money(sav.dollars_saved)} and {Math.round(sav.minutes_saved / 60)} hours over {sav.weeks.length} {sav.weeks.length === 1 ? "week" : "weeks"}</Text>
          <Text style={s.muted}>Against buying the same list at your usual store at regular prices in one trip, and your
            own estimate of planning time before Lil'Helper.</Text>
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>Household</Text>
        <LinkRow icon="👪" title="People" sub="Add, invite, allergies, who's home when" onPress={go("/house/people")} />
        <LinkRow icon="🍽️" title="Dinners" sub="Days, times, nights off, takeout and eating out" onPress={go("/house/dinners")} />
        <LinkRow icon="🥗" title="Meal style" sub="Prep time, one-pot nights, kid chef, leftovers for lunch" onPress={go("/house/style")} />
        <LinkRow icon="🛒" title="Stores, cards and budget" sub="Where you shop, memberships, cards, cost per serving" onPress={go("/house/stores")} />
        <LinkRow icon="🗓️" title="Shopping trips" sub="When you shop, where, and who goes" onPress={go("/house/trips")} />
        <LinkRow icon="🧊" title="Fridge and freezer" sub="Space, freezer meals, buying ahead" onPress={go("/house/storage")} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Food</Text>
        <LinkRow icon="🍳" title="Cook from what I've got" sub="Ideas from what's in the kitchen" onPress={go("/house/cookfrom")} />
        <LinkRow icon="📖" title="Recipes" sub="Your own recipes: ingredients, steps, seasons, how often" onPress={go("/house/recipes")} />
        {adult ? <LinkRow icon="🏷️" title="Specials" sub="This week's deals by store, in store or online" onPress={go("/house/specials")} /> : null}
        {adult ? <LinkRow icon="📈" title="Ingredient forecast" sub="How much you'll need, when to buy, where" onPress={go("/house/forecast")} /> : null}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Stay in the loop</Text>
        <LinkRow icon="📅" title="Calendar and notifications" sub="Subscribe in your calendar; push updates" onPress={go("/house/calendar")} />
        <LinkRow icon="🖨️" title="Print this week" onPress={() => WebBrowser.openBrowserAsync(`${base}/api/print/week.pdf`)} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>You</Text>
        {(me?.households.length ?? 0) > 1 ? <LinkRow icon="🔀" title="Switch household" onPress={go("/house/account")} /> : null}
        <LinkRow icon="⚙️" title="Account" sub={me?.user.email} onPress={go("/house/account")} />
        <Button kind="ghost" title="Sign out" onPress={async () => { await signOut(); router.replace("/signin"); }} />
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
