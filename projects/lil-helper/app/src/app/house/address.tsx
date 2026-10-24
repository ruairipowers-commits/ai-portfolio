// The household's home address: typed, or filled from this phone's location (it asks first). Chefs you hire see it;
// in "Find a chef" other people only ever see your town.
import { useEffect, useState } from "react";
import { Platform, View } from "react-native";
import { Text } from "@/components/text";
import { Address, v6 } from "@/lib/api";
import { Button, ErrorText, Field, Header, Pill, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

async function locate(): Promise<{ lat: number; lon: number }> {
  if (Platform.OS === "web") {
    return new Promise((ok, fail) => {
      const g = (globalThis as { navigator?: Navigator }).navigator?.geolocation;
      if (!g) return fail(new Error("This browser can't share its location; type the address instead."));
      g.getCurrentPosition((p) => ok({ lat: p.coords.latitude, lon: p.coords.longitude }),
        () => fail(new Error("Location wasn't allowed; type the address instead.")), { timeout: 15000 });
    });
  }
  const Location = await import("expo-location");
  const perm = await Location.requestForegroundPermissionsAsync();
  if (!perm.granted) throw new Error("Location wasn't allowed; type the address instead.");
  const p = await Location.getCurrentPositionAsync({});
  return { lat: p.coords.latitude, lon: p.coords.longitude };
}

async function nativeReverse(lat: number, lon: number): Promise<Address> {
  if (Platform.OS === "web") return {};
  try {
    const Location = await import("expo-location");
    const [r] = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lon });
    if (!r) return {};
    return { line1: [r.streetNumber, r.street].filter(Boolean).join(" "), city: r.city ?? r.subregion ?? "",
      state: (r.region ?? "").length === 2 ? r.region! : "", zip: (r.postalCode ?? "").slice(0, 5) };
  } catch { return {}; }
}

export default function AddressScreen() {
  const [a, setA] = useState<Address>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { v6.address().then((r) => setA(r.address)).catch(setError); }, []);
  const set = (p: Partial<Address>) => setA({ ...a, ...p });
  async function useLocation() {
    setBusy(true); setError(null); setMsg(null);
    try {
      const pt = await locate();
      let found = await nativeReverse(pt.lat, pt.lon);
      if (!found.city) found = (await v6.reverse(pt.lat, pt.lon)).address ?? {};
      setA({ ...a, ...Object.fromEntries(Object.entries(found).filter(([, v]) => v)), lat: pt.lat, lon: pt.lon, source: "location" });
      setMsg(found.city ? "Filled from your location: check it, then save." : "Got your location; type the street and town, then save.");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function save() {
    setError(null);
    try { setA((await v6.saveAddress(a)).address); setMsg("Saved"); } catch (e) { setError(e); }
  }
  return (
    <Screen>
      <Header title="Home address" />
      <Button kind="ghost" title="📍 Use my location" onPress={useLocation} busy={busy} />
      <View style={s.card}>
        <Field label="Street" value={a.line1 ?? ""} onChangeText={(v) => set({ line1: v, lat: undefined, lon: undefined, source: "typed" })} placeholder="12 Orchard Lane" />
        <Field label="Apartment, unit (optional)" value={a.line2 ?? ""} onChangeText={(v) => set({ line2: v })} />
        <Field label="Town or city" value={a.city ?? ""} onChangeText={(v) => set({ city: v })} placeholder="Westport" />
        <View style={s.row}>
          <View style={{ flex: 1 }}><Field label="State" value={a.state ?? ""} maxLength={2} autoCapitalize="characters"
            onChangeText={(v) => set({ state: v.toUpperCase() })} placeholder="CT" /></View>
          <View style={{ flex: 1 }}><Field label="ZIP" value={a.zip ?? ""} maxLength={10} keyboardType="number-pad"
            onChangeText={(v) => set({ zip: v })} placeholder="06880" /></View>
        </View>
        {a.lat != null ? <Text style={s.muted}>📍 Located ({a.lat.toFixed(3)}, {a.lon?.toFixed(3)})</Text> : null}
      </View>
      <Text style={s.muted}>Your chef sees the full address. People searching for households only see your town and
        roughly how far away you are.</Text>
      <Button title="Save address" onPress={save} disabled={!a.city && !a.zip} />
      {msg ? <Pill text={msg} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}
