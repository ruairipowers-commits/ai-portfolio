// lilhelper://week?day=… (from a push or a calendar event) lands on the Week tab.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

export default function WeekLink() {
  const params = useLocalSearchParams();
  useEffect(() => { router.replace({ pathname: "/plan" as never, params }); }, []);
  return <View />;
}
