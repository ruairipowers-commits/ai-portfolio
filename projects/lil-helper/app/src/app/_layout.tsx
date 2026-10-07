import { router, useSegments } from "expo-router";
import Stack from "expo-router/stack";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { session } from "@/lib/api";

export default function RootLayout() {
  const segments = useSegments();
  useEffect(() => {
    (async () => {
      const signedIn = !!(await session());
      const onSignIn = segments[0] === "signin";
      if (!signedIn && !onSignIn) router.replace("/signin");
    })();
  }, [segments]);

  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#FFF8EC" } }} />
    </>
  );
}
