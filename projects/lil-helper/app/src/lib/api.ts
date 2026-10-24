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
export type Role = "admin" | "adult" | "kid" | "chef";
export type Membership = { household_id: string; person_id: string; role: Role; name: string; plan?: string };
export type SessionInfo = { session: string; user: { id: string; email: string; name: string }; household: string | null;
  households: Membership[] };
export type HouseholdPlan = { plan: string; own: string; via_chef: boolean };
export type Me = { user: { id: string; email: string; name: string }; households: Membership[];
  current: Membership | null; signup: "invite" | "open" | "closed"; chef_plan?: string; is_chef?: boolean; is_owner?: boolean;
  household_plan?: HouseholdPlan | null };

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

// ---- Dinner Peace Pro (src/lilhelper/pro_api.py)
export type Tier = { kind: "household" | "chef"; rank: number; label: string; monthly: number; yearly: number;
  clients?: number | null; blurb: string; features: string[] };
export type Plans = { tiers: Record<string, Tier>; chef_plan: string; household: HouseholdPlan | null; clients: number;
  client_limit: number | null; billing: "revenuecat" | "admin"; terms_url: string; privacy_url: string };
export type Visit = { day: string; arrive: string; leave: string; covers: string[] };
export type ChefClient = { household_id: string; name: string; priority: number; billing: string; budget: number | null;
  visits: Visit[]; spent_this_week: number };
export type ChefHome = { plan: string; label: string; client_limit: number | null; clients: ChefClient[]; cards: string[];
  stores: string[]; memberships: string[]; branding: { business: string; footer: string; custom: boolean };
  features: Record<string, boolean> };
export type Dish = { day: string; meal: string; name: string; recipe: string; servings: number; ready: boolean };
export type Kitchen = { household_id: string; name: string; arrive: string; leave: string; covers: string[];
  priority: number; dishes: Dish[]; ready: number; next: string; hazard: string | null; hazards: string[];
  containers_in: number; expiring: string[]; shopping: string[]; plan_status: string | null; done?: boolean };
export type Cockpit = { date: string; homes_today: number; kitchens: Kitchen[]; now: Kitchen | null; chef: string;
  plan: string; studio: boolean; trip_id: string | null;
  next_stop: { store: string; items: number; pay: { with: string; note: string; total: number }[] } | null;
  upcoming: { date: string; day: string; household_id: string; name: string; arrive: string }[];
  clients: { household_id: string; name: string; priority: number; billing: string; visits: Visit[] }[] };
export type Container = { id: number; number: number; dish: string; portions: number; location: string; prepared: string;
  use_by: string; days_left: number; warn: string; card: string | null };
export type ReheatCard = { id: string; prepared: string; meal: string; method: string; temp_f: number | null;
  minutes: number; covered: boolean; notes: string; containers: number[]; contains: string[]; steps: string[];
  use_by: string | null };
export type Dossier = { name: string; hazards: { person: string; allergen: string; kid: boolean; text: string }[];
  people: { id: string; name: string; kid: boolean; age: number | null; allergies: string[]; diet: string[];
    likes: string[]; dislikes: string[] }[]; brands: Record<string, string>; allergens: string[];
  budget_per_week: number | null };
export type ClientRecord = { priority: number; billing: string; client_card: string | null; budget: number | null;
  visits: Visit[]; address: string; gate_code: string; access_notes: string; emergency: string; notes: string };
export type ClientDetail = { household_id: string; name: string; dossier: Dossier; client: ClientRecord;
  containers: Container[]; cards: ReheatCard[]; list: { id: number; name: string; qty: number; unit: string }[];
  spent_this_week: number; family_joined: boolean; invites: { email: string; expires: string }[] };
export type VoiceAction = { kind: "toss" | "eaten" | "made" | "reheat" | "shop"; what?: string; match?: string | null;
  dish?: string; portions?: number; containers?: { location: string; portions: number }[]; method?: string;
  temp_f?: number | null; minutes?: number; covered?: boolean; meal?: string | null; item?: string;
  allergens?: string[]; warning?: string };
export type VoicePreview = { household: string | null; household_name: string | null; actions: VoiceAction[];
  unparsed: string[]; flags: string[]; say: string };
export type Share = { household_id: string; name: string; qty: number; cost: number; pct: number };
export type TripLine = { ingredient: string; name: string; brand: string; packs: number; pack: number; unit: string;
  price_each: number; cost: number; special: boolean; bulk: boolean; shares: Share[] };
export type Checkout = { paid_by: "chef" | "client"; household_id: string | null; household_name: string;
  lines: TripLine[]; total: number; card: string | null; card_name: string; card_note: string; rewards: number;
  per_home: { household_id: string; name: string; amount: number }[]; recorded?: boolean; actual?: number };
export type Trip = { id?: string; status?: string; date: string; total: number; rewards: number; bulk_lines: number;
  minutes: number; flags: string[]; unavailable: string[];
  stops: { store: string; store_name: string; total: number; checkouts: Checkout[] }[];
  homes: { household_id: string; name: string; amount: number; billing: string }[] };
export type ChefShopping = { start: string; days: number; studio: boolean; trip: Trip | null;
  per_home: { household_id: string; name: string; visits: string[];
    items: { name: string; qty: number; unit: string; brand: string | null; for: string[] }[] }[] };
export type LedgerRow = { id: number; household_id: string; name: string; date: string; store: string; amount: number;
  card: string; paid_by: string; rewards: number; status: string; note: string; invoice_id: string | null };
export type Ledger = { rows: LedgerRow[]; totals: { pending: number; rewards: number }; names: Record<string, string>;
  budgets: Record<string, { budget: number | null; spent: number }>;
  invoices: { id: string; household_id: string; created: string; total: number; status: string }[] };
export type CoveragePack = { id: string; sub_name: string; sub_email: string; start: string; end: string;
  households: string[]; level: string; created: string; revoked: number; opened: number; url: string };
export type FamilyFridge = { containers: Container[]; cards: ReheatCard[]; chefs: string[]; plan: HouseholdPlan };

export const pro = {
  plans: () => call<Plans>("/api/plans"),
  home: () => call<ChefHome>("/api/chef"),
  settings: (b: Partial<{ cards: string[]; stores: string[]; memberships: string[]; business: string; footer: string }>) =>
    put<ChefHome>("/api/chef/settings", b),
  cockpit: () => call<Cockpit>("/api/chef/cockpit"),
  newClient: (b: { family_name: string; contact_name: string; contact_email?: string; invite?: boolean }) =>
    post<{ household_id: string; invited: string | null }>("/api/chef/clients", b),
  client: (hid: string) => call<ClientDetail>(`/api/chef/clients/${hid}`),
  editClient: (hid: string, b: Partial<ClientRecord>) => put<ClientRecord>(`/api/chef/clients/${hid}`, b),
  addContainer: (hid: string, b: { dish: string; portions: number; location: string; number?: number }) =>
    post<Container>(`/api/chef/clients/${hid}/containers`, b),
  closeContainer: (hid: string, id: number, status: "eaten" | "tossed") =>
    post<{ closed: number }>(`/api/chef/clients/${hid}/containers/${id}/close`, { status }),
  addCard: (hid: string, b: { meal: string; method: string; minutes: number; temp_f?: number | null; covered?: boolean;
    notes?: string; containers?: number[]; confirm?: boolean }) => post<ReheatCard>(`/api/chef/clients/${hid}/reheat`, b),
  cardLink: (hid: string, size: "4x6" | "letter", ids?: string) =>
    post<{ url: string }>(`/api/chef/clients/${hid}/reheat/link${q({ size, ids })}`, {}),
  emailCards: (hid: string, ids?: string) => post<{ sent_to: number }>(`/api/chef/clients/${hid}/reheat/email${q({ ids })}`, {}),
  voice: (text: string, household_id?: string) => post<VoicePreview>("/api/chef/voice", { text, household_id }),
  voiceApply: (household_id: string, actions: VoiceAction[], confirm_allergen = false) =>
    post<{ tossed: string[]; eaten: string[]; containers: Container[]; cards: ReheatCard[]; shopping: unknown[];
      skipped: string[] }>("/api/chef/voice/apply", { household_id, actions, confirm_allergen }),
  shopping: (days = 3) => call<ChefShopping>(`/api/chef/shopping${q({ days })}`),
  saveTrip: (days = 3) => post<Trip>("/api/chef/trips", { days }),
  trip: (id: string) => call<Trip>(`/api/chef/trips/${id}`),
  paid: (id: string, b: { store: string; paid_by: string; household_id?: string | null; actual?: number }) =>
    post<{ ledger: unknown[] }>(`/api/chef/trips/${id}/paid`, b),
  ledger: () => call<Ledger>("/api/chef/ledger"),
  receipt: (b: { household_id: string; store: string; amount: number; card?: string; note?: string }) =>
    post<{ id: number }>("/api/chef/ledger", b),
  invoice: (household_id: string) => post<{ id: string; total: number }>("/api/chef/invoices", { household_id }),
  invoicePaid: (id: string) => post<{ paid: string }>(`/api/chef/invoices/${id}/paid`, {}),
  coverage: () => call<{ packs: CoveragePack[] }>("/api/chef/coverage"),
  newCoverage: (b: { sub_name: string; sub_email: string; start: string; end: string; households: string[];
    level: string; password: string }) => post<CoveragePack>("/api/chef/coverage", b),
  revokeCoverage: (id: string) => del<{ revoked: string }>(`/api/chef/coverage/${id}`),
  fridge: () => call<FamilyFridge>("/api/household/fridge"),
  fridgeDone: (id: number, status: "eaten" | "tossed") => post<{ closed: number }>(`/api/household/fridge/${id}`, { status }),
  inviteChef: (email: string) => post<{ invited: string }>("/api/household/chef-invite", { email }),
};

// ---- v6: wallet, delivery, address, owner console, marketplace
export type EarnRule = { pct?: number; points?: number; program?: string; annual_cap?: number | null };
export type CardCredit = { name: string; monthly: number; applies_to?: string[]; december_extra?: number; used?: number };
export type CardIn = { id?: string; template?: string; name?: string; issuer?: string; network?: string; last4?: string;
  expires?: string; earn?: Record<string, EarnRule>; credit_limit?: number | null; monthly_limit?: number | null;
  stores?: string[]; primary?: boolean; credits?: CardCredit[]; active?: boolean };
export type CardStatus = { id: string; name: string; issuer: string; network: string; last4: string; expires: string;
  expires_in_days: number | null; warn: string; primary: boolean; stores: string[]; active: boolean; template: string;
  credit_limit: number | null; monthly_limit: number | null; month_spent: number; month_left: number | null;
  caps: { category: string; rate: number; spent: number; cap: number | null; left: number | null; pct_used: number | null;
    next_best?: string | null }[]; earn: Record<string, EarnRule>; verified: string; credits: CardCredit[] };
export type Wallet = { cards: CardStatus[]; where: { store: string; store_name: string; mode: string; card: string | null;
  card_name: string; per_100: number; note: string }[];
  templates: { id: string; name: string; issuer: string; network: string; earn: Record<string, EarnRule>;
    credits: CardCredit[]; verified: string }[]; categories: string[]; stores: { id: string; name: string }[];
  services: { id: string; name: string }[] };
export type DeliveryService = { id: string; name: string; kinds: string[]; url: string; note: string; handoff: string;
  on: boolean; membership: { id: string | null; name: string; on: boolean; price_per_month: number | null;
    waive: { minimum?: number } | null; verified: string } };
export type Address = { line1?: string; line2?: string; city?: string; state?: string; zip?: string; lat?: number;
  lon?: number; source?: string };
export type PriceRow = { plan: string; label: string; monthly: number; yearly: number; savings_pct: number;
  effective: string | null; subscribers: number; scheduled: { monthly: number; yearly: number; effective: string } | null;
  history: { monthly: number; yearly: number; effective: string; set_by: string }[] };
export type Subscription = { id: string; kind: "chef" | "household"; subject: string; plan: string;
  interval: "monthly" | "yearly"; price: number; policy: "grandfather" | "current_price" | "custom";
  custom_price: number | null; started: string; renews: string; status: string; source: string; next_price: number;
  change: number; who: { name: string; email: string } };
export type OwnerView = { prices: PriceRow[]; subscriptions: Subscription[]; renewals: Subscription[];
  history: { ts: string; sub: string; event: string; detail: string; by: string }[];
  totals: { active: number; monthly_revenue: number; grandfathered: number; price_rises_next_30_days: number };
  policies: string[]; store_note: string };
export type PublicChef = { uid: string; name: string; business: string; bio: string; cuisines: string[];
  rate_per_visit: number | null; rate_hourly: number | null; place: string; miles: number | null; radius_miles: number;
  full: boolean; clients: number; request?: string | null; your_chef?: boolean };
export type PublicHousehold = { household_id?: string; place: string; miles: number | null; people: number; kids: number;
  allergens: string[]; diets: string[]; budget_per_week: number | null; budget_per_visit: number | null;
  visits_per_week: number | null; cuisines: string[]; note: string; start: string | null; request?: string | null };
export type MeetRequest = { id: string; from_kind: "chef" | "household"; chef_uid: string; hid: string; message: string;
  proposed: string; status: string; created: string; by_uid: string };
export type Listing = { open: boolean; budget_per_week: number | null; budget_per_visit: number | null;
  visits_per_week: number | null; cuisines: string[]; note: string; start: string | null };
export type ChefProfile = { display_name: string; business?: string; bio?: string; cuisines: string[];
  rate_per_visit?: number | null; rate_hourly?: number | null; radius_miles: number; address: Address; listed: boolean;
  accepting: boolean };

export const v6 = {
  wallet: () => call<Wallet>("/api/wallet"),
  saveCards: (cards: (CardIn | string)[]) => put<Wallet>("/api/wallet/cards", { cards }),
  primary: (id: string) => post<Wallet>(`/api/wallet/cards/${id}/primary`, {}),
  delivery: () => call<{ services: DeliveryService[]; takeout_service: string | null }>("/api/delivery"),
  saveDelivery: (b: { services: string[]; memberships: string[]; takeout_service?: string | null }) =>
    put<{ services: DeliveryService[]; takeout_service: string | null }>("/api/delivery", b),
  address: () => call<{ address: Address; geocoder: string | null }>("/api/household/address"),
  saveAddress: (a: Address) => put<{ address: Address }>("/api/household/address", a),
  reverse: (lat: number, lon: number) => call<{ address: Address }>(`/api/geo/reverse${q({ lat, lon })}`),
  owner: () => call<OwnerView>("/api/owner"),
  setPrice: (plan: string, b: { monthly: number; yearly?: number; annual_discount_pct?: number; effective?: string; note?: string }) =>
    put<{ monthly: number; yearly: number }>(`/api/owner/prices/${plan}`, b),
  editSub: (id: string, b: Partial<{ policy: string; custom_price: number; interval: string; plan: string; status: string }>) =>
    put<Subscription>(`/api/owner/subscriptions/${id}`, b),
  bulk: (plan: string, policy: string) => post<{ changed: number }>("/api/owner/subscriptions/bulk", { plan, policy }),
  newSub: (b: { email: string; plan: string; interval: string; source: string; policy: string }) =>
    post<Subscription>("/api/owner/subscriptions", b),
  renewNow: () => post<{ renewed: unknown[] }>("/api/owner/renew", {}),
  listing: () => call<{ listing: Listing; preview: PublicHousehold; has_address: boolean; cuisines: string[] }>("/api/market/listing"),
  saveListing: (b: Partial<Listing>) => put<{ listing: Listing; preview: PublicHousehold; has_address: boolean; cuisines: string[] }>("/api/market/listing", b),
  findChefs: (radius = 25, cuisine?: string) => call<{ chefs: PublicChef[]; place: string }>(`/api/market/chefs${q({ radius, cuisine })}`),
  askChef: (chef_uid: string, message: string, proposed = "") => post<MeetRequest>("/api/market/chef-requests", { chef_uid, message, proposed }),
  householdRequests: () => call<{ requests: (MeetRequest & { chef: PublicChef; contact: { name: string; email: string; business: string } | null })[] }>("/api/market/household-requests"),
  profile: () => call<{ profile: ChefProfile; plan: string; cuisines: string[] }>("/api/market/profile"),
  saveProfile: (b: Partial<ChefProfile>) => put<{ profile: ChefProfile }>("/api/market/profile", b),
  findHouseholds: (radius = 25, cuisine?: string) => call<{ households: PublicHousehold[] }>(`/api/market/households${q({ radius, cuisine })}`),
  askHousehold: (household_id: string, message: string, proposed = "") => post<MeetRequest>("/api/market/requests", { household_id, message, proposed }),
  chefRequests: () => call<{ requests: (MeetRequest & { household: PublicHousehold | null; contact: { household: string; name: string; email: string; place: string } | null })[] }>("/api/market/requests"),
  respond: (id: string, accept: boolean) => post<MeetRequest>(`/api/market/requests/${id}/respond`, { accept }),
  withdraw: (id: string) => del<{ withdrawn: string }>(`/api/market/requests/${id}`),
  hire: (id: string) => post<{ invited: string }>(`/api/market/requests/${id}/hire`, {}),
  myChefs: () => call<{ chefs: { uid: string; name: string; email: string; since: string }[] }>("/api/household/chefs"),
  removeChef: (uid: string) => del<{ removed: string }>(`/api/household/chefs/${uid}`),
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
