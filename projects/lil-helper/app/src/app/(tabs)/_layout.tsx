import Tabs from "expo-router/js-tabs";
import { Text } from "react-native";
import { c } from "@/lib/theme";

const icon = (glyph: string) => ({ focused }: { focused: boolean }) =>
  <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{glyph}</Text>;

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: c.red, tabBarInactiveTintColor: c.muted,
      tabBarStyle: { backgroundColor: "#FFFDF8", borderTopColor: c.line } }}>
      <Tabs.Screen name="index" options={{ title: "This week", tabBarIcon: icon("🍎") }} />
      <Tabs.Screen name="shopping" options={{ title: "Shopping", tabBarIcon: icon("🛒") }} />
      <Tabs.Screen name="jobs" options={{ title: "Jobs", tabBarIcon: icon("🧽") }} />
      <Tabs.Screen name="meals" options={{ title: "After meals", tabBarIcon: icon("⭐") }} />
      <Tabs.Screen name="settings" options={{ title: "Home", tabBarIcon: icon("🏠") }} />
    </Tabs>
  );
}
