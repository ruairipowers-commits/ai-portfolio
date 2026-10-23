// Cook: every way to decide what to eat, plus the recipe book.
import { router } from "expo-router";
import { View } from "react-native";
import { Text } from "@/components/text";
import { LinkRow, Screen } from "@/components/ui";
import { VoiceBar } from "@/components/voice";
import { WayTiles } from "@/components/ways";
import { s } from "@/lib/theme";

export default function Ideas() {
  return (
    <Screen>
      <Text style={s.h1}>What shall we eat?</Text>
      <VoiceBar hint="Try: I have 30 minutes and want something cozy · I have eggs, spinach and cheese" />
      <WayTiles />
      <View style={s.card}>
        <LinkRow icon="📖" title="Recipe book" sub="Yours and DinnerPeace's, with steps and calories"
          onPress={() => router.push("/house/recipes" as never)} />
        <LinkRow icon="🥕" title="Ingredients" sub="Your brand, store and price for anything"
          onPress={() => router.push("/house/ingredients" as never)} />
      </View>
    </Screen>
  );
}
