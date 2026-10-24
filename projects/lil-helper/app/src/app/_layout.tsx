// The app's front door: no session → sign in; a personal chef (Dinner Peace Pro) → the chef cockpit; signed in but not
// in a household yet → the welcome wizard. Fonts (Nunito) load before anything is drawn.
import { Nunito_400Regular, Nunito_600SemiBold, Nunito_700Bold, Nunito_800ExtraBold, Nunito_900Black,
  useFonts } from "@expo-google-fonts/nunito";
import { router, useSegments } from "expo-router";
import Stack from "expo-router/stack";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { api, ApiError, session, signOut } from "@/lib/api";
import { mode } from "@/lib/mode";
import { listenForTaps } from "@/lib/push";
import { c } from "@/lib/theme";

const OPEN = new Set(["signin", "welcome", "plans", "owner"]);

export default function RootLayout() {
  const segments = useSegments();
  const [fonts] = useFonts({ Nunito_400Regular, Nunito_600SemiBold, Nunito_700Bold, Nunito_800ExtraBold, Nunito_900Black });
  useEffect(() => {
    (async () => {
      const here = segments[0] ?? "";
      if (!(await session())) {
        if (here !== "signin") router.replace("/signin");
        return;
      }
      if (OPEN.has(here)) return;
      try {
        const me = await api.me();
        const chefOnly = me.is_chef && (!me.current || me.current.role === "chef");
        if (here === "chef") return;
        if (chefOnly && !mode.family) router.replace("/chef" as never);
        else if (!me.current) router.replace("/welcome");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { await signOut(); router.replace("/signin"); }
      }
    })();
  }, [segments]);
  useEffect(() => listenForTaps(), []);
  if (!fonts) return null;

  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }} />
    </>
  );
}
