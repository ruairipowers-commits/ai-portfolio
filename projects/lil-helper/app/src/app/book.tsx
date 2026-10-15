// lilhelper://book?code=… (a shared recipe book link) opens Share and import with the code filled in.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

export default function BookLink() {
  const { code } = useLocalSearchParams<{ code?: string }>();
  useEffect(() => { router.replace({ pathname: "/house/book", params: code ? { code } : {} } as never); }, []);
  return <View />;
}
