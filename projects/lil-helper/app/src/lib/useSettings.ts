// The household's settings, loaded when a settings screen comes into focus. `save(section, value)` writes one
// section (the server validates it, and only the admin may write); the screen shows "Saved" or the server's reason.
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { api, Settings, SettingsView } from "./api";

export function useSettings() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setView(await api.settings()); setError(null); } catch (e) { setError(e); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = useCallback(async (section: string, value: unknown) => {
    setBusy(true); setError(null); setSavedAt(null);
    try {
      const r = await api.patchSetting(section, value);
      setView((v) => v ? { ...v, version: r.version, settings: { ...v.settings, [section]: r.value } } : v);
      setSavedAt(Date.now());
      return true;
    } catch (e) { setError(e); return false; } finally { setBusy(false); }
  }, []);

  const st: Settings = view?.settings ?? {};
  return { view, st, role: view?.role, me: view?.me, cat: view?.catalogs, error, setError, savedAt, busy, save,
    reload: load, isAdmin: view?.role === "admin" };
}
