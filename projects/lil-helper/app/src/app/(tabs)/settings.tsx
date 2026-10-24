// More: the household at a glance, and the way into everything else: people, settings, recipes, specials, the
// calendar, money and planning tools. Admin-only settings are visible to everyone but only the admin can change them.
import * as WebBrowser from "expo-web-browser";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/text";
import { api, Me, serverUrl, signOut } from "@/lib/api";
import { Button, ErrorText, LinkRow, money, Pill, Screen } from "@/components/ui";
import { mode } from "@/lib/mode";
import { c, s } from "@/lib/theme";

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
            own estimate of planning time before DinnerPeace.</Text>
        </View>
      ) : null}
      {me?.is_owner ? (
        <View style={s.card}><LinkRow icon="🛠️" title="Owner console" sub="Plan prices, subscriptions, renewals" onPress={go("/owner")} /></View>) : null}
      {me?.is_chef ? (
        <View style={[s.card, { backgroundColor: c.proSoft, borderColor: "#E5DFD6" }]}>
          <LinkRow icon="🧑‍🍳" title="Back to your chef cockpit" sub="Dinner Peace Pro" onPress={() => { mode.family = false;
            router.replace("/chef" as never); }} />
        </View>) : null}
      <View style={s.card}>
        <Text style={s.h2}>Plan</Text>
        <LinkRow icon="✨" title={me?.household_plan?.via_chef ? "Dinner Peace Family (from your chef)" :
          me?.household_plan?.plan === "free" ? "Family Free" : "Dinner Peace Family"} sub="Plans for families and personal chefs"
          onPress={go("/plans")} />
        <LinkRow icon="🧑‍🍳" title="Your personal chef" sub="What's in the fridge, how to reheat it, invite your chef" onPress={go("/house/chef")} />
        <LinkRow icon="🔎" title="Find a chef" sub="Chefs near you, what you'd pay, ask to meet, switch chefs" onPress={go("/house/find-chef")} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Household</Text>
        <LinkRow icon="👪" title="People" sub="Add, invite, birthdays, allergies, who's home when" onPress={go("/house/people")} />
        <LinkRow icon="🎉" title="Special occasions" sub="Birthdays, anniversaries, holidays" onPress={go("/house/occasions")} />
        <LinkRow icon="🍽️" title="Dinners" sub="Days, times, nights off, takeout and eating out" onPress={go("/house/dinners")} />
        <LinkRow icon="🥗" title="Meal style" sub="Prep time, one-pot nights, kid chef, leftovers for lunch" onPress={go("/house/style")} />
        <LinkRow icon="📍" title="Home address" sub="Typed, or from your location" onPress={go("/house/address")} />
        <LinkRow icon="🛒" title="Stores and budget" sub="Where you shop, memberships, cost per serving" onPress={go("/house/stores")} />
        {adult ? <LinkRow icon="💳" title="Cards" sub="Rewards, caps, limits, expiry, credits; which card where" onPress={go("/house/wallet")} /> : null}
        <LinkRow icon="🚚" title="Delivery services" sub="Instacart, DoorDash, Uber Eats, Amazon, Walmart, Grubhub" onPress={go("/house/delivery")} />
        <LinkRow icon="🗓️" title="Shopping trips" sub="When you shop, where, and who goes" onPress={go("/house/trips")} />
        <LinkRow icon="🧊" title="Fridge and freezer" sub="Space, freezer meals, buying ahead" onPress={go("/house/storage")} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Food</Text>
        <LinkRow icon="🍳" title="Cook from what I've got" sub="Ideas from what's in the kitchen" onPress={go("/house/cookfrom")} />
        <LinkRow icon="📖" title="Recipes" sub="Your own recipes: ingredients, steps, seasons, how often" onPress={go("/house/recipes")} />
        <LinkRow icon="🥕" title="Ingredients" sub="Your brand, store and price for anything" onPress={go("/house/ingredients")} />
        <LinkRow icon="🥣" title="Weekly buffet" sub="Portions on hand instead of a recipe a day" onPress={go("/house/buffet")} />
        {adult ? <LinkRow icon="🏷️" title="Specials" sub="This week's deals by store, in store or online" onPress={go("/house/specials")} /> : null}
        {adult ? <LinkRow icon="📈" title="Ingredient forecast" sub="How much you'll need, when to buy, where" onPress={go("/house/forecast")} /> : null}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Reports and money</Text>
        <LinkRow icon="📊" title="Reports" sub="Costs, time, calories, who did which jobs" onPress={go("/house/report")} />
        {adult ? <LinkRow icon="💵" title="Money" sub="Budget, spending, receipts, cards" onPress={go("/money")} /> : null}
        <LinkRow icon="⭐" title="Rate meals" sub="How was it? How much was left?" onPress={go("/meals")} />
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Stay in the loop</Text>
        <LinkRow icon="🔊" title="Alexa" sub="“Alexa, ask DinnerPeace what's for dinner”" onPress={go("/house/alexa")} />
        <LinkRow icon="📅" title="Calendar and notifications" sub="Subscribe in your calendar; push updates" onPress={go("/house/calendar")} />
        <LinkRow icon="🖨️" title="Print this week" onPress={() => WebBrowser.openBrowserAsync(`${base}/api/print/week.pdf`)} />
      </View>
      {cur?.role === "admin" ? <View style={s.card}>
        <Text style={s.h2}>Admin</Text>
        <LinkRow icon="📥" title="Import and export" sub="Everything in one Excel workbook: people, recipes, prices, fridge, freezer"
          onPress={go("/house/bulk")} />
      </View> : null}
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
