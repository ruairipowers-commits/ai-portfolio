// Dinner Peace Pro: the chef's tabs. Next (what do I do next?), Clients, Shop, Ledger, More.
import Tabs from "expo-router/js-tabs";
import { Text } from "@/components/text";
import { c } from "@/lib/theme";

const icon = (glyph: string) => ({ focused }: { focused: boolean }) =>
  <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{glyph}</Text>;

export default function ChefTabs() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: c.pro, tabBarInactiveTintColor: c.muted,
      tabBarLabelStyle: { fontFamily: "Nunito_700Bold" },
      tabBarStyle: { backgroundColor: c.parchment, borderTopColor: c.line } }}>
      <Tabs.Screen name="index" options={{ title: "Next", tabBarIcon: icon("🧑‍🍳") }} />
      <Tabs.Screen name="clients" options={{ title: "Clients", tabBarIcon: icon("🏡") }} />
      <Tabs.Screen name="shop" options={{ title: "Shop", tabBarIcon: icon("🛒") }} />
      <Tabs.Screen name="ledger" options={{ title: "Ledger", tabBarIcon: icon("💳") }} />
      <Tabs.Screen name="more" options={{ title: "More", tabBarIcon: icon("⚙️") }} />
    </Tabs>
  );
}
