// Your account: switch household, delete your account (as the App Store requires, right in the app), or, for the
// admin, delete the household and everything in it.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { api, Me } from "@/lib/api";
import { Button, ErrorText, Field, Header, LinkRow, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function Account() {
  const [me, setMe] = useState<Me | null>(null);
  const [confirmAcct, setConfirmAcct] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  useFocusEffect(useCallback(() => { api.me().then(setMe).catch(setError); }, []));
  const cur = me?.current;
  return (
    <Screen>
      <Header title="Account" />
      <View style={s.card}>
        <Text style={s.body}>{me?.user.email}</Text>
        <Text style={s.muted}>Signed in with an emailed link; there's no password to forget.</Text>
      </View>
      {(me?.households.length ?? 0) > 0 ? (
        <View style={s.card}>
          <Text style={s.h2}>Households</Text>
          {me!.households.map((h) => (
            <LinkRow key={h.household_id} icon={h.household_id === cur?.household_id ? "✅" : "🏠"} title={h.name}
              sub={h.role} onPress={async () => {
                try { await api.switchHousehold(h.household_id); router.replace("/"); } catch (e) { setError(e); }
              }} />
          ))}
          <Button kind="ghost" title="Start another household" onPress={() => router.push("/welcome" as never)} />
        </View>
      ) : null}
      {cur?.role === "admin" ? (
        <View style={s.card}>
          <Text style={s.h2}>Delete this household</Text>
          <Text style={s.muted}>Removes its plans, recipes, spending and settings for everyone. Type its name to confirm.</Text>
          <Field label="Household name" value={name} onChangeText={setName} placeholder={cur.name} />
          <Button kind="ghost" title="Delete the household" disabled={name.trim() !== cur.name} onPress={async () => {
            try { await api.deleteHousehold(name); router.replace("/welcome"); } catch (e) { setError(e); }
          }} />
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>Delete my account</Text>
        <Text style={s.muted}>Removes you from every household. A household with nobody left in it is deleted too; if
          you're its only admin, another adult becomes admin.</Text>
        <Button kind="ghost" title={confirmAcct ? "Tap again to delete my account" : "Delete my account"} onPress={async () => {
          if (!confirmAcct) { setConfirmAcct(true); return; }
          try { await api.deleteAccount(); router.replace("/signin"); } catch (e) { setError(e); }
        }} />
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
