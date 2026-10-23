// Shopping trips: your regular trips and orders. Each gets its own list, with fresh food on the trip nearest the day
// it's cooked; the person going gets the list in their calendar and a reminder an hour before.
import { View } from "react-native";
import { Text } from "@/components/text";
import { useSettings } from "@/lib/useSettings";
import { TripsEditor } from "@/components/house";
import { AdminNote, ErrorText, Header, Saved, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Trips() {
  const set = useSettings();
  return (
    <Screen>
      <Header title="Shopping trips" />
      <AdminNote role={set.role} />
      <View style={s.card}>
        <Text style={s.muted}>No trips set? DinnerPeace picks the cheapest mix of stores and pickup or delivery each week.
          "Sun before" is the Sunday before the plan's week starts.</Text>
      </View>
      {set.view ? <TripsEditor key={set.view.version} set={set} /> : null}
      <Saved at={set.savedAt} />
      <ErrorText error={set.error} />
    </Screen>
  );
}
