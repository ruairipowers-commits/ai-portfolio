// A new client household: the family's name and the adult who runs it. They're invited by email and get the family
// app free while you're their chef. You can add people and allergies before they join.
import { router } from "expo-router";
import { useState } from "react";
import { Text } from "@/components/text";
import { pro } from "@/lib/api";
import { Button, ErrorText, Field, Header, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function NewClient() {
  const [family, setFamily] = useState("");
  const [contact, setContact] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function save() {
    setBusy(true);
    try {
      const r = await pro.newClient({ family_name: family.trim(), contact_name: contact.trim(),
        contact_email: email.trim() || undefined, invite: !!email.trim() });
      router.replace({ pathname: "/chef/client", params: { id: r.household_id, tab: "setup" } } as never);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <Screen>
      <Header title="New client" />
      <Field label="Family or household name" value={family} onChangeText={setFamily} placeholder="Henderson family" />
      <Field label="Who runs the household" value={contact} onChangeText={setContact} placeholder="Priya Henderson" />
      <Field label="Their email (optional)" value={email} onChangeText={setEmail} placeholder="priya@example.com"
        autoCapitalize="none" keyboardType="email-address"
        hint="They'll get an invitation to Dinner Peace. Until they join, you hold the household's settings." />
      <Text style={s.muted}>Next: their people and allergies, your visit days, and how they pay for groceries.</Text>
      <Button kind="pro" title="Create household" onPress={save} busy={busy} disabled={!family.trim() || !contact.trim()} />
      <ErrorText error={error} />
    </Screen>
  );
}
