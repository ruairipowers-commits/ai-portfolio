// One shared view of "this week" across the tabs, reloaded when a screen comes into focus.
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { api, ApiError, Week } from "./api";

export function useWeek() {
  const [week, setWeek] = useState<Week | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWeek(await api.week());
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setWeek(null);
      else setError(e);
    } finally {
      setLoading(false);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  return { week, setWeek, error, setError, loading, reload: load };
}
