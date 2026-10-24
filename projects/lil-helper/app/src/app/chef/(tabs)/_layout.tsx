// Dinner Peace Pro: the chef's tabs. Next (what do I do next?), Clients, Shop, Ledger, More.
import Tabs from "expo-router/js-tabs";
import { useWindowDimensions } from "react-native";
import { Text } from "@/components/text";
import { c } from "@/lib/theme";

const icon = (glyph: string) => ({ focused }: { focused: boolean }) =>
  <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{glyph}</Text>;

export default function ChefTabs() {
  const wide = useWindowDimensions().width >= 900;   // desktop and tablets: tabs down the side
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarPosition: wide ? "left" : "bottom", tabBarVariant: wide ? "material" : "uikit",
      tabBarLabelPosition: wide ? "beside-icon" : undefined, tabBarActiveTintColor: c.pro, tabBarInactiveTintColor: c.muted,
      tabBarLabelStyle: { fontFamily: "Nunito_700Bold" },
      tabBarStyle: { backgroundColor: c.parchment, borderTopColor: c.line, ...(wide ? { width: 230 } : {}) } }}>
      <Tabs.Screen name="index" options={{ title: "Next", tabBarIcon: icon("🧑‍🍳") }} />
      <Tabs.Screen name="clients" options={{ title: "Clients", tabBarIcon: icon("🏡") }} />
      <Tabs.Screen name="shop" options={{ title: "Shop", tabBarIcon: icon("🛒") }} />
      <Tabs.Screen name="ledger" options={{ title: "Ledger", tabBarIcon: icon("💳") }} />
      <Tabs.Screen name="more" options={{ title: "More", tabBarIcon: icon("⚙️") }} />
    </Tabs>
  );
}
