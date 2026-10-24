// Find a recipe on the web: search the sites you like (or anywhere), or paste a recipe's link. DinnerPeace reads the
// page's recipe details, fills in sensible settings, and opens it for you to check before it goes in your book (with
// the site's name and a link back).
import * as WebBrowser from "expo-web-browser";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { api, SearchResult } from "@/lib/api";
import { giveDraft } from "@/lib/handoff";
import { Button, Chips, ErrorText, Field, Header, LinkRow, Screen } from "@/components/ui";
import { s } from "@/lib/theme";

export default function RecipeWeb() {
  const params = useLocalSearchParams<{ useFor?: string; q?: string }>();
  const useFor = params.useFor ? String(params.useFor) : undefined;
  const [q, setQ] = useState(params.q ? String(params.q) : "");
  const [sites, setSites] = useState<string[]>([]);
  const [site, setSite] = useState<string>("mine");
  const [newSite, setNewSite] = useState("");
  const [admin, setAdmin] = useState(false);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api.settings().then((v) => { setSites(v.settings.recipe_sources ?? []); setAdmin(v.role === "admin"); }).catch(() => {});
  }, []);

  async function search() {
    setBusy("search"); setError(null);
    try { setRes(await api.searchRecipes(q, site === "mine" ? undefined : site === "any" ? "" : site)); }
    catch (e) { setError(e); } finally { setBusy(null); }
  }
  async function load(url: string) {
    setBusy(url); setError(null);
    try {
      giveDraft(await api.recipeFromUrl(url), useFor);
      router.push({ pathname: "/house/recipe", params: { id: "new", ...(useFor ? { useFor } : {}) } } as never);
    } catch (e) { setError(e); } finally { setBusy(null); }
  }
  async function saveSites(next: string[]) {
    try { await api.patchSetting("recipe_sources", next); setSites(next); setNewSite(""); } catch (e) { setError(e); }
  }

  const siteOpts = [{ id: "mine", label: sites.length ? "My sites" : "Anywhere" }, ...sites.map((x) => ({ id: x, label: x })),
    ...(sites.length ? [{ id: "any", label: "Anywhere" }] : [])];
  return (
    <Screen>
      <Header title="Recipes on the web" />
      <View style={s.card}>
        <Field label="Look for" placeholder="chicken broccoli rice" value={q} onChangeText={setQ} returnKeyType="search"
          onSubmitEditing={search} />
        <Chips label="Where" multi={false} options={siteOpts} value={site} onChange={([x]) => setSite(x)} />
        <Button title="Search" busy={busy === "search"} disabled={!q.trim()} onPress={search} />
      </View>
      {res ? (
        <View style={s.card}>
          {res.results.map((r) => <LinkRow key={r.url} icon="🌐" title={r.title} sub={`${r.site} · ${r.snippet}`}
            onPress={() => load(r.url)} />)}
          {res.search_url ? <>
            <Text style={s.muted}>{res.note}</Text>
            <Button kind="ghost" title="Open the search" onPress={() => WebBrowser.openBrowserAsync(res.search_url!)} />
          </> : null}
          {busy && busy !== "search" ? <Text style={s.muted}>Reading the recipe…</Text> : null}
        </View>
      ) : null}
      <View style={s.card}>
        <Text style={s.h2}>Have a recipe's link?</Text>
        <TextInput style={s.input} placeholder="https://…" autoCapitalize="none" value={link} onChangeText={setLink} />
        <Button title="Add from this link" busy={busy === link && !!link} disabled={!/^https?:\/\//.test(link.trim())}
          onPress={() => load(link.trim())} />
        <Text style={s.muted}>Works with most recipe sites. You check everything before it's saved; the method stays on
          their page, linked from yours.</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Sites you like</Text>
        {sites.length ? <Text style={s.body}>{sites.join(" · ")}</Text> : <Text style={s.muted}>None yet: searches look anywhere.</Text>}
        {admin ? <>
          <TextInput style={s.input} placeholder="marthastewart.com" autoCapitalize="none" value={newSite} onChangeText={setNewSite} />
          <View style={s.row}>
            <View style={{ flex: 1 }}><Button kind="ghost" title="Add site" disabled={!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(newSite.trim().toLowerCase())}
              onPress={() => saveSites([...sites, newSite.trim().toLowerCase().replace(/^www\./, "")])} /></View>
            {sites.length ? <View style={{ flex: 1 }}><Button kind="ghost" title="Clear" onPress={() => saveSites([])} /></View> : null}
          </View>
        </> : <Text style={s.muted}>The household's admin chooses these.</Text>}
      </View>
      <ErrorText error={error} />
    </Screen>
  );
}
