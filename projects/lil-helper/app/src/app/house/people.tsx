// People: everyone in the household, whether they've joined the app, and the way to add or invite someone.
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { api, Person, Role } from "@/lib/api";
import { Button, ErrorText, Header, LinkRow, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function People() {
  const [people, setPeople] = useState<Person[]>([]);
  const [role, setRole] = useState<Role | null>(null);
  const [error, setError] = useState<unknown>(null);
  useFocusEffect(useCallback(() => {
    api.people().then((r) => { setPeople(r.people); setRole(r.role); }).catch(setError);
  }, []));
  return (
    <Screen>
      <Header title="People" />
      <View style={s.card}>
        {people.map((p) => (
          <LinkRow key={p.id} icon={p.age_band === "kid" ? "🧒" : "🧑"} title={p.name}
            sub={[p.role, p.signed_up ? "using the app" : p.invited ? "invited" : "not invited",
              p.allergies?.length ? `allergic to ${p.allergies.join(", ")}` : ""].filter(Boolean).join(" · ")}
            onPress={() => router.push({ pathname: "/house/person", params: { id: p.id } } as never)} />
        ))}
      </View>
      {role === "admin" ? <Button title="Add someone" onPress={() => router.push({ pathname: "/house/person",
        params: { id: "new" } } as never)} /> : null}
      <Text style={s.muted}>Admins change everyone's details and invite people. Adults plan, approve and shop. Kids see
        the plan and their jobs, and rate meals. Everyone can change their own likes and dislikes.</Text>
      <ErrorText error={error} />
    </Screen>
  );
}
