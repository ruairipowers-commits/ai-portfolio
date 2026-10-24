import Tabs from "expo-router/js-tabs";
import { useWindowDimensions } from "react-native";
import { Text } from "@/components/text";
import { c } from "@/lib/theme";

const icon = (glyph: string) => ({ focused }: { focused: boolean }) =>
  <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{glyph}</Text>;

export default function TabsLayout() {
  const wide = useWindowDimensions().width >= 900;   // desktop and tablets: tabs down the side
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarPosition: wide ? "left" : "bottom", tabBarVariant: wide ? "material" : "uikit",
      tabBarLabelPosition: wide ? "beside-icon" : undefined, tabBarActiveTintColor: c.primary, tabBarInactiveTintColor: c.muted,
      tabBarStyle: { backgroundColor: c.parchment, borderTopColor: c.line, ...(wide ? { width: 230 } : {}) } }}>
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
