import Tabs from "expo-router/js-tabs";
import { Text } from "@/components/text";
import { c } from "@/lib/theme";

const icon = (glyph: string) => ({ focused }: { focused: boolean }) =>
  <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{glyph}</Text>;

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: c.primary, tabBarInactiveTintColor: c.muted,
      tabBarStyle: { backgroundColor: c.parchment, borderTopColor: c.line } }}>
      <Tabs.Screen name="index" options={{ title: "Today", tabBarIcon: icon("🌞") }} />
      <Tabs.Screen name="plan" options={{ title: "Week", tabBarIcon: icon("🍎") }} />
      <Tabs.Screen name="ideas" options={{ title: "Cook", tabBarIcon: icon("🍳") }} />
      <Tabs.Screen name="shopping" options={{ title: "Shopping", tabBarIcon: icon("🛒") }} />
      <Tabs.Screen name="jobs" options={{ title: "Jobs", tabBarIcon: icon("🧽") }} />
      <Tabs.Screen name="settings" options={{ title: "More", tabBarIcon: icon("🏠") }} />
      <Tabs.Screen name="meals" options={{ href: null, title: "Rate" }} />
      <Tabs.Screen name="money" options={{ href: null, title: "Money" }} />
    </Tabs>
  );
}
