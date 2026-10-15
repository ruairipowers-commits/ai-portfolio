// The app's front door: no session → sign in; signed in but not in a household yet → the welcome wizard.
import { router, useSegments } from "expo-router";
import Stack from "expo-router/stack";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { api, ApiError, session, signOut } from "@/lib/api";
import { listenForTaps } from "@/lib/push";

const OPEN = new Set(["signin", "welcome"]);

export default function RootLayout() {
  const segments = useSegments();
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
        if (!me.current) router.replace("/welcome");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { await signOut(); router.replace("/signin"); }
      }
    })();
  }, [segments]);
  useEffect(() => listenForTaps(), []);

  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#FFF8EC" } }} />
    </>
  );
}
