// Talks to the household's own Lil'Helper server. The session token is kept in the phone's secure storage
// (Keychain on iPhone); on the web build it falls back to localStorage. Nothing else is stored on the phone.
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const SESSION = "lilhelper.session";
const SERVER = "lilhelper.server";

async function getItem(key: string): Promise<string | null> {
  if (Platform.OS === "web") {
    try { return globalThis.localStorage?.getItem(key) ?? null; } catch { return null; }
  }
  return SecureStore.getItemAsync(key);
}

async function setItem(key: string, value: string | null): Promise<void> {
  if (Platform.OS === "web") {
    try { value === null ? globalThis.localStorage?.removeItem(key) : globalThis.localStorage?.setItem(key, value); } catch {}
    return;
  }
  if (value === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, value);
}

export async function serverUrl(): Promise<string> {
  const saved = await getItem(SERVER);
  const fromBuild = process.env.EXPO_PUBLIC_API_URL;          // set per build profile in eas.json
  const fromConfig = (Constants.expoConfig?.extra as { apiUrl?: string } | undefined)?.apiUrl;
  return (saved || fromBuild || fromConfig || "http://localhost:8650").replace(/\/$/, "");
}

export const setServerUrl = (url: string) => setItem(SERVER, url.trim() || null);
export const session = () => getItem(SESSION);
export const signOut = () => setItem(SESSION, null);

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await session();
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`${await serverUrl()}${path}`, { ...init, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch {}
    throw new ApiError(res.status, String(msg));
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

// ---- types (mirror src/lilhelper/api.py)
export type Entry = { day: string; meal: string; recipe: string; name: string; servings: number; est_cost: number;
  active: number; prep_day: string; double?: boolean; why?: string[] };
export type Option = { total: number; minutes: number; stores: { store: string; mode: string; total: number }[] };
export type Chore = { day: string; job: string; person: string; name: string };
export type PetWeek = { name: string; restock: Record<string, number>;
  extras: { day: string; item: string; amount: number; unit: string; from: string; how: string }[];
  blocked: { day: string; item: string; why: string[] }[]; notes: string[] };
export type Savings = { dollars_saved: number; baseline_dollars: number; plan_dollars: number; minutes_saved: number;
  planning_before: number; planning_after: number; specials_saved: number; credits: number; rating: number | null };
export type Week = { week_of: string; status: "draft" | "approved"; approved_by?: string;
  plan: { entries: Entry[]; special_nights: Record<string, string>; flags: string[] };
  choice: string; options: Record<string, Option>; chores: Chore[]; pets: PetWeek[]; savings: Savings | null;
  people: Record<string, string> };
export type Order = { store: string; mode: string; handoff: string; total: number; url: string | null; note: string | null;
  share_text?: string; credits: number;
  lines: { name: string; packs: number; brand: string; special: boolean; price: number }[] };
export type Household = { name: string; me: string; calendar_feed: string; budget_per_week: number;
  people: { id: string; name: string; kid: boolean; allergies: string[] }[];
  pets: { id: string; name: string; species: string; food: string }[]; stores: string[] };

export const api = {
  requestLink: (email: string) => post<{ message: string }>("/api/auth/request", { email }),
  verify: async (token: string) => {
    const r = await post<{ session: string; person: string; name: string }>("/api/auth/verify", { token });
    await setItem(SESSION, r.session);
    return r;
  },
  household: () => call<Household>("/api/household"),
  week: (week?: string) => call<Week>(`/api/week${week ? `?week=${week}` : ""}`),
  draft: (week?: string) => post<Week>("/api/week/draft", { week }),
  swap: (day: string, meal: string, week?: string) => post<Week>("/api/week/swap", { week, day, meal }),
  approve: (seconds: number, choice: string, week?: string) =>
    post<Week>("/api/week/approve", { week, seconds, choice }),
  shopping: (week?: string) => call<{ orders: Order[]; choice: string }>(`/api/week/shopping${week ? `?week=${week}` : ""}`),
  swapJob: (day: string, job: string, person: string, week?: string) =>
    post<{ chores: Chore[] }>("/api/jobs/swap", { week, day, job, person }),
  feedback: (day: string, meal: string, eaten: string, rating: number | null, week?: string) =>
    post<{ portions_changed: Record<string, number> }>("/api/feedback", { week, day, meal, eaten, rating }),
  flyer: async (storeId: string, uri: string, week?: string) => {
    const form = new FormData();
    form.append("store_id", storeId);
    if (week) form.append("week", week);
    form.append("image", { uri, name: "flyer.jpg", type: "image/jpeg" } as unknown as Blob);
    return call<{ store: string; flags: string[]; items: { text: string; price: number | null; ingredient: string | null;
      status: string; why: string[] }[] }>("/api/flyer", { method: "POST", body: form });
  },
  confirmSpecials: (storeId: string, items: { ingredient: string; price: number }[], week?: string) =>
    post<{ confirmed: number }>("/api/specials/confirm", { week, store_id: storeId, items }),
  savings: () => call<{ weeks: { week_of: string; dollars_saved: number; minutes_saved: number; rating: number | null }[];
    dollars_saved: number; minutes_saved: number }>("/api/savings"),
};

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export const DAY_NAME: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
  fri: "Friday", sat: "Saturday", sun: "Sunday" };
export const JOB_NAME: Record<string, string> = { cook: "Cook", dishes: "Dishes", set_table: "Set table",
  kid_assistant: "Kid helper", feed_dog: "Feed the dog" };
