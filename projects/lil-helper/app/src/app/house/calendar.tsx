// Calendar and notifications: subscribe once in your own calendar app; it updates itself.
import { useState } from "react";
import { Text, View } from "react-native";
import { api } from "@/lib/api";
import { LoopCard } from "@/components/house";
import { Button, ErrorText, Header, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Calendar() {
  const [n, setN] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  return (
    <Screen>
      <Header title="Calendar" />
      <LoopCard key={n} />
      <View style={s.card}>
        <Text style={s.h2}>What's in it</Text>
        <Text style={s.muted}>Dinner at dinner time with who's cooking and your job; lunches and leftovers; takeout and
          eating-out nights; shopping trips you're on, with the list. In each dinner: ★ Rate, All gone / Some left / Lots
          left, and Change this meal. One tap; nothing else to sign in to.</Text>
        <Text style={s.muted}>Changes you make in the app show up at your calendar's next refresh.</Text>
      </View>
      <Button kind="ghost" title="Make a new private link (stops the old one)" onPress={async () => {
        try { await api.rotateCalendar(); setN(n + 1); setMsg("Done. Subscribe again with the new link, and remove the old calendar."); }
        catch (e) { setError(e); }
      }} />
      {msg ? <Text style={s.muted}>{msg}</Text> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
