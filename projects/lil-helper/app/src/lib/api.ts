// Talks to the DinnerPeace server. The session token is kept in the phone's secure storage (Keychain on iPhone);
// on the web build it falls back to localStorage. Nothing else about the household is stored on the phone.
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
  constructor(public status: number, message: string, public detail?: unknown) { super(message); }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await session();
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`${await serverUrl()}${path}`, { ...init, headers });
  if (!res.ok) {
    let msg: string = res.statusText;
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
      if (typeof detail === "string") msg = detail;
      else if (Array.isArray(detail)) msg = detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
      else if (detail && typeof detail === "object" && "message" in detail) msg = String((detail as { message: string }).message);
    } catch {}
    throw new ApiError(res.status, msg, detail);
  }
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return p.length ? `?${p.join("&")}` : "";
};
const post = <T>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) => call<T>(path, { method: "PUT", body: JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) => call<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const del = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "DELETE", body: body === undefined ? undefined : JSON.stringify(body) });

// ---- types (mirror src/lilhelper/api.py)
export type Role = "admin" | "adult" | "kid";
export type Membership = { household_id: string; person_id: string; role: Role; name: string; plan?: string };
export type SessionInfo = { session: string; user: { id: string; email: string; name: string }; household: string | null;
  households: Membership[] };
export type Me = { user: { id: string; email: string; name: string }; households: Membership[];
  current: Membership | null; signup: "invite" | "open" | "closed" };

export type Entry = { day: string; meal: string; recipe: string; name: string; servings: number; est_cost: number;
  active: number; prep_day: string; double?: boolean; why?: string[]; eaters?: string[];
  kind?: "cook" | "leftovers" | "freezer"; cook?: string | null; to_freeze?: number;
  state?: "planned" | "today" | "to_confirm" | "finished" | "leftovers" | "freezer" | "skipped"; date?: string;
  frozen?: number; original?: { recipe: string; name: string } | null; parts?: MealPart[] };
export type MealPart = { kind: "cook" | "leftovers" | "ready"; eaters?: string[]; recipe?: string; food?: string;
  servings?: number; name?: string };
export type Option = { total: number; minutes: number; flags: string[]; storage_used: Record<string, number>;
  stores: { store: string; mode: string; total: number; day?: string | null; time?: string | null; card?: string | null }[] };
export type Chore = { day: string; job: string; person: string; name: string };
export type PetWeek = { name: string; restock: Record<string, number>;
  extras: { day: string; item: string; amount: number; unit: string; from: string; how: string }[];
  blocked: { day: string; item: string; why: string[] }[]; notes: string[] };
export type Savings = { dollars_saved: number; baseline_dollars: number; plan_dollars: number; minutes_saved: number;
  planning_before: number; planning_after: number; specials_saved: number; credits: number; rating: number | null };
export type NightOut = { day: string; kind: "takeout" | "eat_out"; budget: number; service: string; credit: number;
  credit_name: string; card: string | null; card_name: string; rewards: number; net: number; eaters: string[];
  per_person: number };
export type Ahead = { ingredient: string; name: string; store: string; store_name: string; packs: number; pack: number;
  unit: string; price: number; regular: number; saving: number; needed_on: string; for_: string[];
  keep: "pantry" | "fridge" | "freeze"; litres: number; channel: string };
export type Week = { week_of: string; status: "draft" | "approved"; approved_by?: string;
  plan: { entries: Entry[]; special_nights: Record<string, string>; flags: string[] };
  choice: string; options: Record<string, Option>; chores: Chore[]; pets: PetWeek[]; savings: Savings | null;
  eating_out: NightOut[]; extras: { buy_ahead?: Ahead[]; buy_ahead_added?: Ahead[]; storage?: Record<string, number>;
    freezer?: { cook_extra?: { day: string; recipe: string; portions: number }[] } };
  people: Record<string, string>; dinner_times: Record<string, string>; away: Record<string, string[]>; today: string;
  home: Record<string, string[]> };
export type Order = { store: string; mode: string; handoff: string; total: number; url: string | null; note: string | null;
  share_text?: string; credits: number; day?: string | null; time?: string | null; who?: string | null;
  card?: string | null; card_note?: string | null; rewards?: number;
  lines: { name: string; packs: number; brand: string; special: boolean; price: number }[] };

export type Person = { id: string; name: string; age_band: "adult" | "kid"; age?: number; birthday?: string;
  can_approve?: boolean; age_now?: number | null; child?: boolean; teen?: boolean; allergies?: string[];
  diet?: string[]; portion?: number; likes?: string[]; dislikes?: string[]; home?: string[]; can_cook?: boolean;
  email?: string; admin?: boolean; role: Role; signed_up: boolean; invited: boolean; last_seen?: string | null };
export type PersonIn = Omit<Person, "id" | "role" | "signed_up" | "invited" | "last_seen" | "age_now" | "child" | "teen">;
export type Catalogs = { allergens: string[]; diets: string[]; night_kinds: string[]; days: string[]; meals: string[];
  regions: string[]; stores: { id: string; name: string; modes: string[]; needs?: string }[];
  cards: { id: string; name: string; verified: string }[]; memberships: { id: string; name: string }[]; styles: string[] };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Settings = Record<string, any>;
export type SettingsView = { settings: Settings; version: string; role: Role; me: string; catalogs: Catalogs };

export type RecipeRow = { id: string; name: string; meal: string; active: number; total: number; tags: string[];
  source: string; season_months: number[]; want: { times?: number; per_weeks?: number }; kid_min_age?: number | null;
  credit?: string; url?: string; meals?: string[]; kcal?: number | null };
export type RecipeIn = { name: string; meal: string; serves: number; active: number; total: number;
  ingredients: { text?: string; ingredient?: string; qty: number; unit?: string }[]; instructions: string[];
  tags: string[]; season_months: number[]; want: { times?: number; per_weeks?: number }; kid_min_age: number;
  veg?: number; notes?: string; credit?: string; url?: string; meals?: string[]; kcal?: number };
export type RecipeDraft = Omit<RecipeIn, "ingredients"> & { ingredients: { text?: string; ingredient?: string; qty: number; unit?: string;
  line?: string; known?: boolean }[]; unknown?: string[]; check_amounts?: string[]; note?: string };
export type SearchResult = { results: { title: string; url: string; site: string; snippet: string }[];
  search_url: string | null; note?: string; sites: string[] };
export type BookImport = { added: number; skipped_same_name: string[]; failed: { name: string; why: string }[];
  new_ingredients: string[] };
export type Special = { id: number; week_of: string; store: string; ingredient: string; name: string; price: number;
  regular: number | null; channel: string; repeat_weekly: number; note?: string };
export type MoneySummary = { week_of: string; budget: { groceries: number; eating_out: number; total: number };
  planned: { groceries: number; takeout: number; eat_out: number; total: number };
  spent: Record<string, number> & { total: number }; remaining: number; rewards_earned: number;
  month: { spent: Record<string, number>; total: number };
  rows: { id: number; date: string; merchant: string; store: string | null; category: string; amount: number;
    card: string | null; rewards: number; credit: number; source: string }[] };
export type Receipt = { receipt: string; store: string | null; merchant: string; date: string | null; total: number | null;
  items: { text: string; price: number; ingredient: string | null; status: string; shelf_price?: number }[];
  flags: string[]; suggested_card: string | null };
export type CostReport = { weeks: { week_of: string; status: string; food_bill: number; food_used: number;
    stock_change: number; pet_food: number; eating_out: number; total: number; per_person: Record<string, number>;
    meals: { day: string; meal: string; name: string; cost: number; per_serving: number; servings: number }[];
    actual: { groceries: number; takeout?: number; eat_out?: number; total?: number } | null }[];
  people: { person: string; name: string; total: number; per_week: number; per_day: number }[];
  by_meal: Record<string, { meals: number; avg_cost: number; avg_per_serving: number }>; pets: number;
  analysis: string[]; basis: string };
export type Forecast = { ingredient: string; name: string; unit: string; storage: string; keeps_days: number;
  freezable: boolean; on_hand: number; on_hand_frozen: number; need_total: number;
  uses: { date: string; qty: number; meal: string }[];
  planned_purchases: { date: string; qty: number; store: string; mode: string; packs: number; cost: number }[];
  buys: { date: string; trip: string | null; when: string; store: string; mode: string; packs: number; pack: number;
    brand: string; price_each: number; cost: number; special: boolean; for: string;
    keep: "freeze" | "too_early" | string; keep_note: string }[];
  buy_cost: number; end_stock: number;
  prices: { store: string; brand: string; pack: number; price: number; per_unit: number; special: boolean; channel: string }[];
  timeline: { date: string; event: string; stock: number }[]; tips: string[] };
export type Idea = { recipe: string; name: string; meal: string; have: string[]; uses_typed: string[];
  draft: RecipeDraft | null; credit: string;
  missing: { name: string; qty: number; unit: string; est_cost: number }[]; missing_cost: number; coverage: number;
  uses_soon: string[]; active: number; total: number; servings: number; instructions: string[]; why: string[] };
export type Storage = { capacity: { fridge_l: number; freezer_l: number; fill_target?: number };
  used: Record<string, number>; free: Record<string, number>;
  freezer_meals: { id: number; name: string; portions: number; frozen_on: string; use_by: string }[];
  frozen: { ingredient: string; name: string; qty: number; unit: string }[] };
export type Occasion = { id: string; name: string; kind: string; people: string[]; recipe: string | null; tags: string[];
  guests: number; meal: string; date: string };
export type OccasionIn = { name: string; date: string; kind: string; people: string[]; recipe?: string; guests: number;
  tags: string[]; yearly: boolean; meal: string };
export type VibeIdea = { recipe: string; name: string; active: number; total: number; kcal: number | null; servings: number;
  why: string[]; missing: { ingredient: string; name: string; qty: number; unit: string; est_cost: number }[];
  missing_cost: number; credit: string };
export type BuffetItem = { meal: string; recipe: string; name: string; target: number; on_hand: number; cook: number;
  active: number };
export type TodayTask = { kind: "job" | "confirm" | "shop" | "approve" | "buffet"; text: string; day?: string;
  meal?: string; week?: string; items?: number; job?: string };
export type Today = { date: string; day: string; me: string; my_name: string; role: Role;
  meals: { meal: string; name: string; recipe: string; kind?: string; active?: number; cook: string | null; time: string;
    parts: MealPart[] }[];
  my_jobs: TodayTask[]; tasks: TodayTask[]; everyone: { person: string; name: string; jobs: TodayTask[] }[];
  occasions: Occasion[]; birthday: boolean; week_status: string | null };
export type Activity = { weeks: { week_of: string; cooking_minutes: number; shopping_minutes: number;
    planning_minutes: number; kcal_per_day: Record<string, number>; chores: Record<string, Record<string, number>> }[];
  chores: { person: string; jobs: Record<string, number>; total: number }[];
  kcal: { person: string; avg_per_day_planned: number }[]; minutes: { cooking: number; shopping: number }; note: string };
export type IngredientDetail = { id: string; name: string; unit: string; cat: string; allergens: string[]; source: string;
  storage: string; book_prices: { store: string; store_name: string; brand: string; pack: number; price: number }[];
  mine: IngredientPref | null; used_in: string[]; stores: { id: string; name: string }[] };
export type IngredientPref = { brand?: string; store?: string; price?: number; pack?: number; only_store?: boolean };
export type VoiceReply = { intent: string; heard: string; say: string; screen: string | null; params: Record<string, string>;
  data?: { ideas?: string[] } };
export type BulkChanges = Record<string, Partial<Record<"add" | "change" | "remove", string[]>>>;
export type BulkPreview = { token: string; changes: BulkChanges; problems: string[] };
export type CalendarLink = { https: string; webcal: string; google: string; note: string };

export const api = {
  // accounts
  health: () => call<{ ok: boolean; version: string; signup: string }>("/api/health"),
  requestLink: (email: string, invite?: string) => post<{ message: string }>("/api/auth/request", { email, invite }),
  verify: async (token: string, invite?: string) => {
    const r = await post<SessionInfo>("/api/auth/verify", { token, invite });
    await setItem(SESSION, r.session);
    return r;
  },
  me: () => call<Me>("/api/me"),
  switchHousehold: async (household_id: string) => {
    const r = await post<SessionInfo>("/api/session/household", { household_id });
    await setItem(SESSION, r.session);
    return r;
  },
  createHousehold: async (body: { name: string; your_name: string; region?: string; signup_code?: string;
    timezone?: string }) => {
    const r = await post<SessionInfo>("/api/households", body);
    await setItem(SESSION, r.session);
    return r;
  },
  deleteAccount: async () => { const r = await del<{ deleted: boolean }>("/api/account"); await signOut(); return r; },
  deleteHousehold: (confirm: string) => del<{ deleted: boolean }>("/api/household", { confirm }),

  // household settings and people
  settings: () => call<SettingsView>("/api/household/settings"),
  patchSetting: (section: string, value: unknown) =>
    patch<{ saved: boolean; version: string; value: unknown }>(`/api/household/settings/${section}`, { value }),
  people: () => call<{ people: Person[]; pets: Settings; me: string; role: Role }>("/api/household/people"),
  addPerson: (p: PersonIn) => post<{ added: string }>("/api/household/people", p),
  savePerson: (id: string, p: PersonIn) => put<{ saved: string }>(`/api/household/people/${id}`, p),
  removePerson: (id: string) => del<{ removed: string }>(`/api/household/people/${id}`),
  invite: (person_id: string, email: string) =>
    post<{ invited: string; role: Role }>("/api/household/invites", { person_id, email }),

  // the week
  week: (week?: string) => call<Week>(`/api/week${q({ week })}`),
  draft: (week?: string) => post<Week>("/api/week/draft", { week }),
  swap: (day: string, meal: string, week?: string, to?: string) => post<Week>("/api/week/swap", { week, day, meal, to }),
  night: (day: string, kind: string, week?: string) => post<Week>("/api/week/night", { week, day, kind }),
  away: (day: string, person: string, away: boolean, week?: string) =>
    post<Week>("/api/week/away", { week, day, person, away }),
  change: (day: string, meal: string, recipe: string, week?: string) =>
    post<Week & { missing: string[] }>("/api/week/change", { week, day, meal, recipe }),
  revert: (day: string, meal: string, week?: string) => post<Week>("/api/week/revert", { week, day, meal }),
  outcome: (day: string, meal: string, outcome: string, frozen = 0, week?: string) =>
    post<Week>("/api/week/outcome", { week, day, meal, outcome, frozen }),
  ahead: (ingredients: string[], week?: string) => post<{ added: Ahead[] }>("/api/week/ahead", { week, ingredients }),
  approve: (seconds: number, choice: string, week?: string) =>
    post<Week>("/api/week/approve", { week, seconds, choice }),
  shopping: (week?: string) => call<{ orders: Order[]; choice: string }>(`/api/week/shopping${q({ week })}`),
  swapJob: (day: string, job: string, person: string, week?: string) =>
    post<{ chores: Chore[] }>("/api/jobs/swap", { week, day, job, person }),
  feedback: (day: string, meal: string, eaten: string, rating: number | null, week?: string) =>
    post<{ portions_changed: Record<string, number> }>("/api/feedback", { week, day, meal, eaten, rating }),

  // recipes, ingredients, specials
  recipes: (params: { q?: string; meal?: string; mine?: boolean } = {}) =>
    call<{ recipes: RecipeRow[] }>(`/api/recipes${q(params)}`),
  recipe: (id: string) => call<RecipeRow & { ingredients: { ingredient: string; name: string; per_serving: number;
    unit: string }[]; instructions: string[]; allergens: string[]; notes?: string; ing: Record<string, number> }>(
    `/api/recipes/${id}`),
  saveRecipe: (r: RecipeIn, id?: string) =>
    post<{ saved: string; allergens: string[]; warning: string | null }>(`/api/recipes${q({ rid: id })}`, r),
  removeRecipe: (id: string) => del<{ removed: string }>(`/api/recipes/${id}`),
  exportRecipes: () => call<Record<string, unknown>>("/api/recipes/export"),
  importRecipes: (book: unknown) => post<BookImport>("/api/recipes/import", { book }),
  shareRecipes: () => post<{ code: string; link: string; recipes: number; note: string }>("/api/recipes/share", {}),
  stopSharing: () => del<{ stopped: number }>("/api/recipes/share"),
  previewShared: (code: string) => post<{ household: string; recipes: string[]; same: boolean }>("/api/recipes/shared", { code }),
  importShared: (code: string) => post<BookImport>("/api/recipes/import-shared", { code }),
  recipeFromUrl: (url: string) => post<RecipeDraft>("/api/recipes/from-url", { url }),
  searchRecipes: (query: string, site?: string) => call<SearchResult>(`/api/recipes/search${q({ q: query, site })}`),
  ingredients: (search = "") => call<{ ingredients: { id: string; name: string; unit: string; cat: string;
    source: string }[] }>(`/api/ingredients${q({ q: search })}`),
  addIngredient: (b: { name: string; unit: string; cat: string; allergens: string[] }) =>
    post<{ saved: string; allergens: string[] }>("/api/ingredients", b),
  specials: (week?: string) => call<{ specials: Special[] }>(`/api/specials${q({ week })}`),
  addSpecial: (b: { store: string; item?: string; ingredient?: string; price: number; per: "pack" | "unit";
    channel: string; repeat_weekly: boolean; week?: string; note?: string }) =>
    post<{ saved: string; pack: number; unit: string; price: number; regular: number | null; note: string | null }>(
      "/api/specials", b),
  removeSpecial: (id: number) => del<{ removed: number }>(`/api/specials/${id}`),
  flyer: async (storeId: string, uri: string, week?: string) => {
    const form = new FormData();
    form.append("store_id", storeId);
    if (week) form.append("week", week);
    form.append("image", { uri, name: "flyer.jpg", type: "image/jpeg" } as unknown as Blob);
    return call<{ store: string; flags: string[]; items: { text: string; price: number | null; ingredient: string | null;
      status: string; why: string[] }[] }>("/api/flyer", { method: "POST", body: form });
  },
  confirmSpecials: (storeId: string, items: { ingredient: string; price: number }[], channel = "any", week?: string) =>
    post<{ confirmed: number }>("/api/specials/confirm", { week, store_id: storeId, items, channel }),

  // money
  moneySummary: (week?: string) => call<MoneySummary>(`/api/money/summary${q({ week })}`),
  addSpend: (b: { date?: string; amount: number; store?: string; merchant?: string; category: string; card?: string }) =>
    post<{ recorded: boolean }>("/api/money/spend", b),
  removeSpend: (id: number) => del<{ removed: number }>(`/api/money/spend/${id}`),
  statement: async (file: { uri: string; name: string; mimeType?: string; file?: File }, card?: string) => {
    const form = new FormData();
    if (file.file) form.append("file", file.file);
    else form.append("file", { uri: file.uri, name: file.name, type: file.mimeType ?? "text/csv" } as unknown as Blob);
    if (card) form.append("card", card);
    return call<{ imported: number; duplicates: number; skipped_not_food: number; skipped_refunds: number; rows: number }>(
      "/api/money/statement", { method: "POST", body: form });
  },
  receipt: async (src: { uri?: string; text?: string }) => {
    const form = new FormData();
    if (src.text) form.append("text", src.text);
    if (src.uri) form.append("image", { uri: src.uri, name: "receipt.jpg", type: "image/jpeg" } as unknown as Blob);
    return call<Receipt>("/api/money/receipt", { method: "POST", body: form });
  },
  confirmReceipt: (receipt: string, card?: string | null, use_prices = true) =>
    post<{ recorded: boolean; prices_updated: number }>("/api/money/receipt/confirm", { receipt, card, use_prices }),
  cards: () => call<{ cards: { id: string; name: string; network: string; verified: string }[];
    best: { store: string; mode: string; card: string; per_100: number; note: string }[];
    ytd: { card: string; category: string; spent: number }[] }>("/api/money/cards"),
  costReport: (weeks = 8) => call<CostReport>(`/api/reports/cost${q({ weeks })}`),

  // planning helpers
  forecastList: (weeks = 4) => call<{ weeks: number; ingredients: { ingredient: string; name: string; unit: string;
    qty: number; est_cost: number; meals: number }[] }>(`/api/forecast/ingredients${q({ weeks })}`),
  forecast: (ingredient: string, weeks = 4) => call<Forecast>(`/api/forecast${q({ ingredient, weeks })}`),
  cookFrom: (b: { text: string; use_pantry: boolean; meal?: string; day?: string; max_minutes?: number }) =>
    post<{ ideas: Idea[]; matched: string[]; not_recognised: string[]; servings: number; uses_everything: boolean;
      new_recipe: Idea | null; search: string }>("/api/cookfrom", b),
  useIdea: (recipe: string, day: string, meal = "dinner") => post<Week>("/api/cookfrom/use", { recipe, day, meal }),
  storage: () => call<Storage>("/api/storage"),
  addFreezerMeal: (name: string, portions: number) => post<{ added: string }>("/api/storage/freezer", { name, portions }),
  editFreezerMeal: (id: number, b: { name: string; portions: number; use_by?: string }) =>
    put<{ saved: number }>(`/api/storage/freezer/${id}`, b),
  removeFreezerMeal: (id: number) => del<{ removed: number }>(`/api/storage/freezer/${id}`),

  // calendar, push, print, savings
  calendarLink: () => call<CalendarLink>("/api/calendar/link"),
  rotateCalendar: () => post<CalendarLink>("/api/calendar/rotate", {}),
  registerDevice: (token: string, platform: string) => post<{ registered: boolean }>("/api/devices", { token, platform }),
  // v4: occasions, ways to decide, today, reports, ingredients, bulk, voice
  occasions: (days = 60) => call<{ upcoming: Occasion[]; holidays: { id: string; name: string; on: boolean }[];
    occasions: (OccasionIn & { id: string })[] }>(`/api/occasions${q({ days })}`),
  addOccasion: (o: OccasionIn) => post<{ added: string }>("/api/occasions", o),
  removeOccasion: (id: string) => del<{ removed: string }>(`/api/occasions/${id}`),
  occasionIdeas: (b: { people: string[]; tags: string[]; guests: number; meal?: string }) =>
    post<{ servings: number; ideas: (VibeIdea & { est_cost: number; score: number })[] }>("/api/occasions/ideas", b),
  vibe: (b: { minutes: number; moods: string[]; meal?: string; day?: string; people?: string[]; have?: string }) =>
    post<{ meal: string; minutes: number; moods: string[]; servings: number; ideas: VibeIdea[]; not_recognised: string[];
      mood_names: Record<string, string> }>("/api/vibe", b),
  vibeOrder: (recipe: string, servings: number) => post<{ orders: { store: string; mode: string; total: number;
    lines: { name: string; packs: number; brand: string }[]; share_text: string; url: string | null; note?: string }[];
    note?: string }>("/api/vibe/order", { recipe, servings }),
  surprise: (meal = "dinner", day?: string, minutes?: number) => call<{ recipe: string; name: string; active: number;
    total: number; kcal: number | null; credit: string; steps: string[]; pool: number }>(`/api/surprise${q({ meal, day, minutes })}`),
  buffet: () => call<{ config: Record<string, { on: boolean; items: { recipe: string; target: number }[] }>;
    items: BuffetItem[] }>("/api/buffet"),
  setBuffet: (meal: string, on: boolean, items: { recipe: string; target: number }[]) =>
    put<{ config: Record<string, { on: boolean; items: { recipe: string; target: number }[] }>; items: BuffetItem[] }>(
      "/api/buffet", { meal, on, items }),
  buffetCount: (meal: string, recipe: string, on_hand: number) =>
    post<{ items: BuffetItem[] }>("/api/buffet/count", { meal, recipe, on_hand }),
  planAhead: (weeks: number, start?: string) => post<{ weeks: { week_of: string; status: string; dinners: string[];
    total: number | null }[] }>("/api/plan/ahead", { weeks, start }),
  parts: (day: string, meal: string, parts: MealPart[], week?: string) =>
    post<Week>("/api/week/parts", { week, day, meal, parts }),
  today: () => call<Today>("/api/today"),
  activity: (weeks = 8) => call<Activity>(`/api/reports/activity${q({ weeks })}`),
  ingredient: (id: string) => call<IngredientDetail>(`/api/ingredients/${id}`),
  setPref: (id: string, p: IngredientPref) => put<{ saved: string; mine: IngredientPref }>(`/api/ingredients/${id}/pref`, p),
  clearPref: (id: string) => del<{ cleared: string }>(`/api/ingredients/${id}/pref`),
  bulkLink: () => post<{ url: string }>("/api/bulk/link", {}),
  bulkImport: async (file: { uri: string; name: string; mimeType?: string; file?: File }) => {
    const form = new FormData();
    if (file.file) form.append("file", file.file);
    else form.append("file", { uri: file.uri, name: file.name, type: file.mimeType ??
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" } as unknown as Blob);
    return call<BulkPreview>("/api/bulk/import", { method: "POST", body: form });
  },
  bulkConfirm: (token: string) => post<{ applied: boolean; changes: BulkChanges }>("/api/bulk/import/confirm", { token }),
  voice: (text: string) => post<VoiceReply>("/api/voice", { text }),
  alexa: () => call<{ links: { created: string; last_used: string | null }[]; configured: boolean; link_page: string;
    endpoint: string }>("/api/alexa"),
  alexaCode: () => post<{ code: string; minutes: number }>("/api/alexa/code", {}),
  alexaUnlink: () => del<{ removed: number }>("/api/alexa"),

  savings: () => call<{ weeks: { week_of: string; dollars_saved: number; minutes_saved: number; rating: number | null }[];
    dollars_saved: number; minutes_saved: number }>("/api/savings"),
};

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export const DAY_NAME: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
  fri: "Friday", sat: "Saturday", sun: "Sunday", sun_before: "Sunday before", sat_before: "Saturday before" };
export const DAY_SHORT: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri",
  sat: "Sat", sun: "Sun", sun_before: "Sun before", sat_before: "Sat before" };
export const JOB_NAME: Record<string, string> = { cook: "Cook", dishes: "Dishes", set_table: "Set table",
  kid_assistant: "Kid helper", feed_dog: "Feed the dog" };
export const NIGHT_NAME: Record<string, string> = { cook: "Cook", leftovers: "Leftovers", takeout: "Takeout",
  eat_out: "Eat out", freezer: "From the freezer" };
export const MODE_NAME: Record<string, string> = { in_store: "In store", pickup: "Pickup", delivery: "Delivery" };
export const pretty = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (m) => m.toUpperCase());
