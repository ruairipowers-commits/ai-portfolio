// One person: details (admin), their own likes and dislikes (themselves), invite to the app, remove.
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api, DAY_SHORT, DAYS, Person, PersonIn, RecipeRow, Role } from "@/lib/api";
import { Button, Chips, ErrorText, Field, Header, NumberField, Pill, Saved, Screen, Toggle } from "@/components/ui";
import { s } from "@/lib/theme";

const BLANK: PersonIn = { name: "", age_band: "adult", allergies: [], diet: [], portion: 1, likes: [], dislikes: [],
  home: [...DAYS], can_cook: true };

export default function PersonScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const isNew = id === "new";
  const [p, setP] = useState<PersonIn>(BLANK);
  const [row, setRow] = useState<Person | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [me, setMe] = useState("");
  const [cat, setCat] = useState<{ allergens: string[]; diets: string[] }>({ allergens: [], diets: [] });
  const [recipes, setRecipes] = useState<RecipeRow[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.settings().then((v) => setCat(v.catalogs)).catch(() => {});
    api.recipes().then((r) => setRecipes(r.recipes)).catch(() => {});
    api.people().then((r) => {
      setRole(r.role); setMe(r.me);
      const x = r.people.find((q) => q.id === id);
      if (x) {
        const { id: _i, role: _r, signed_up: _s, invited: _v, last_seen: _l, ...rest } = x;
        setRow(x); setP({ ...BLANK, ...rest }); setEmail(x.email ?? "");
      }
    }).catch(setError);
  }, [id]);

  const admin = role === "admin";
  const age = ageOf(p.birthday ?? "");
  const teen = age != null ? age >= 12 && age < 18 : !!row?.teen;
  const self = id === me;
  const canEdit = admin || isNew;

  async function save() {
    setBusy(true); setError(null); setSavedAt(null);
    try {
      const body = { ...p, email: email || undefined };
      if (isNew) {
        const r = await api.addPerson(body);
        router.replace({ pathname: "/house/person", params: { id: r.added } } as never);
      } else { await api.savePerson(id, body); setSavedAt(Date.now()); }
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function invite() {
    setBusy(true); setError(null);
    try { const r = await api.invite(id, email); setMsg(`Invite sent to ${r.invited} (as ${r.role}). The link works for 14 days.`); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function remove() {
    setBusy(true); setError(null);
    try { await api.removePerson(id); router.back(); } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const recipeOpts = recipes.map((r) => ({ id: r.id, label: r.name }));
  return (
    <Screen>
      <Header title={isNew ? "Add someone" : p.name || "Person"} />
      {row ? <View style={s.row}><Pill text={row.teen ? `teen${row.role === "adult" ? " · can approve" : ""}` : row.role} />{row.signed_up ? <Pill text="using the app" />
        : row.invited ? <Pill text="invited" tone="amber" /> : null}</View> : null}
      {canEdit ? (
        <View style={s.card}>
          <Field label="Name" value={p.name} onChangeText={(name) => setP({ ...p, name })} />
          <Field label="Birthday" value={p.birthday ?? ""} autoCapitalize="none" placeholder="e.g. 2014-03-07 (or 03-07)"
            onChangeText={(birthday) => {
              const a = ageOf(birthday);
              setP({ ...p, birthday: birthday || undefined, ...(a != null ? { age: a, age_band: a < 12 ? "kid" : "adult",
                admin: a < 18 ? false : p.admin } : {}) });
            }}
            hint={age != null ? `${age} · ${age < 12 ? "child (under 12)" : age < 18 ? "teen: adult portions" : "adult"} · no jobs on their birthday`
              : "With a full date, child (under 12) or adult follows from it. Birthdays show up in Special occasions."} />
          {age == null ? <>
            <Chips multi={false} options={[{ id: "adult", label: "Adult" }, { id: "kid", label: "Child (under 12)" }]} value={p.age_band}
              onChange={([v]) => setP({ ...p, age_band: v as "adult" | "kid", admin: v === "kid" ? false : p.admin,
                age: v === "kid" ? p.age ?? 8 : undefined })} />
            {p.age_band === "kid" ? <NumberField label="Age" value={p.age ?? 8} min={0} max={11}
              onChange={(a) => setP({ ...p, age: a })} /> : null}
          </> : null}
          <Chips label="Allergies" options={cat.allergens} value={p.allergies} onChange={(allergies) => setP({ ...p, allergies })} />
          <Chips label="Diet" options={cat.diets} value={p.diet} onChange={(diet) => setP({ ...p, diet })} />
          <NumberField label="Portion (1 = an adult's)" step={0.1} min={0.2} max={3} value={p.portion}
            onChange={(portion) => setP({ ...p, portion })} />
          <Chips label="Home for dinner" options={DAYS.map((d) => ({ id: d, label: DAY_SHORT[d] }))} value={p.home}
            onChange={(home) => setP({ ...p, home })} />
          {p.age_band === "adult" ? <>
            <Toggle label="Can cook dinner" value={!!p.can_cook} onChange={(can_cook) => setP({ ...p, can_cook })} />
            {teen ? <Toggle label="Can approve plans and spending" hint="Teens (12–17) can't unless you allow it. Admins must be 18+."
              value={!!p.can_approve} onChange={(can_approve) => setP({ ...p, can_approve })} />
              : <Toggle label="Household admin" hint="Can change settings and invite people. There's always at least one."
                value={!!p.admin} onChange={(a) => setP({ ...p, admin: a })} />}
          </> : null}
          <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address"
            hint="For inviting them to the app and the weekly email." />
        </View>
      ) : (
        <View style={s.card}>
          <Text style={s.body}>{p.age_band === "kid" ? `Age ${row?.age_now ?? p.age ?? "?"}` : teen ? `Teen, ${row?.age_now ?? ""}` : "Adult"}
            {p.allergies?.length ? ` · allergic to ${p.allergies.join(", ")}` : ""}</Text>
          <Text style={s.muted}>Home for dinner: {(p.home ?? []).map((d) => DAY_SHORT[d]).join(", ")}</Text>
        </View>
      )}
      {canEdit || self ? (
        <View style={s.card}>
          <Chips label="Favourites (birthday meals and occasions use these first)" options={recipeOpts} value={p.likes} onChange={(likes) => setP({ ...p, likes })} />
          <Chips label="Rather not" options={recipeOpts} value={p.dislikes} onChange={(dislikes) => setP({ ...p, dislikes })} />
        </View>
      ) : null}
      {canEdit || self ? <Button title={isNew ? "Add" : "Save"} busy={busy} onPress={save} disabled={!p.name.trim()} /> : null}
      <Saved at={savedAt} />
      {admin && !isNew && !row?.signed_up ? (
        <View style={s.card}>
          <Text style={s.h2}>Invite to the app</Text>
          <Text style={s.muted}>{p.age_band === "kid" ? "Kids see the plan and their jobs and can rate meals." :
            "Adults can plan, swap, approve the week and shop."}</Text>
          <Button kind="ghost" title={row?.invited ? "Send the invite again" : "Send invite"} busy={busy}
            disabled={!email.includes("@")} onPress={invite} />
          {msg ? <Text style={s.muted}>{msg}</Text> : null}
        </View>
      ) : null}
      {admin && !isNew && !self ? <Button kind="ghost" busy={busy}
        title={confirm ? `Tap again to remove ${p.name}` : `Remove ${p.name} from the household`}
        onPress={() => (confirm ? remove() : setConfirm(true))} /> : null}
      <ErrorText error={error} />
    </Screen>
  );
}

function ageOf(b: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(b.trim());
  if (!m) return null;
  const t = new Date();
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || y < 1900) return null;
  const a = t.getFullYear() - y - ((t.getMonth() + 1 < mo || (t.getMonth() + 1 === mo && t.getDate() < d)) ? 1 : 0);
  return a >= 0 && a < 121 ? a : null;
}
