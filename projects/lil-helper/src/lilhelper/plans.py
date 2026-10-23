"""Plans: what each subscription unlocks, decided on the server (never by the app).

Two kinds of plan, on two different things:
  household  free | family | beta          the family's own app. `beta` (every household made before plans existed,
                                          and every household made while sign-up needs a code) has all of Family.
  chef       none | chef_solo | chef_studio  Dinner Peace Pro, on the chef's own account: Solo runs up to 3 client
                                          households, Studio any number and adds the cross-household features.

A household with a chef on an active Pro plan in it gets Family free (the chef's clients never pay). Invited family
members never pay either: only the admin's (or the chef's) subscription counts.

Plans are set by an admin command (`helper plans set`) or, in production, by the RevenueCat webhook
(`/api/billing/revenuecat`) after an App Store / Play purchase. `plan_until` (UTC ISO) ends a plan; a lapsed plan
falls back to free / none, and nothing is deleted.

Safety features are never behind a plan: allergen and pet-toxicity rules run for everyone.
"""
from __future__ import annotations

import datetime as dt

TIERS = {
    "free": {"kind": "household", "rank": 0, "label": "Family Free", "monthly": 0.0, "yearly": 0.0,
             "blurb": "A 7-day plan, an aisle-sorted list, recipes and every allergy rule"},
    "family": {"kind": "household", "rank": 1, "label": "Dinner Peace Family", "monthly": 4.99, "yearly": 39.0,
               "blurb": "Plan up to 12 weeks, cook from what you have, fridge calendars, store hand-offs"},
    "beta": {"kind": "household", "rank": 1, "label": "Beta (all of Family)", "monthly": 0.0, "yearly": 0.0,
             "blurb": "Every Family feature while DinnerPeace is in beta"},
    "none": {"kind": "chef", "rank": 0, "label": "No Pro plan", "monthly": 0.0, "yearly": 0.0, "clients": 1,
             "blurb": "Join one client household to look around"},
    "chef_solo": {"kind": "chef", "rank": 1, "label": "Chef Solo", "monthly": 29.0, "yearly": 290.0, "clients": 3,
                  "blurb": "Up to 3 client homes: cockpit, dossiers, containers, reheat labels, voice logging"},
    "chef_studio": {"kind": "chef", "rank": 2, "label": "Chef Studio", "monthly": 59.0, "yearly": 590.0,
                    "clients": None,
                    "blurb": "Unlimited homes, one shopping trip across them, card routing and invoices, "
                             "coverage packs, your branding"},
}

# feature → the lowest plan that has it
FEATURES = {
    # the family app
    "plan_ahead": "family", "cookfrom": "family", "print": "family", "bulk": "family",
    # Dinner Peace Pro
    "cockpit": "chef_solo", "dossier": "chef_solo", "containers": "chef_solo", "reheat": "chef_solo",
    "voice_log": "chef_solo", "client_ledger": "chef_solo", "chef_clients": "chef_solo",
    "batch_trip": "chef_studio", "card_routing": "chef_studio", "invoices": "chef_studio",
    "coverage": "chef_studio", "branding": "chef_studio",
}
FEATURE_NAMES = {
    "plan_ahead": "Planning more than a week ahead", "cookfrom": "Cook from what I have", "print": "Fridge calendars",
    "bulk": "Import and export", "cockpit": "The chef cockpit", "dossier": "Client dossiers",
    "containers": "The container log", "reheat": "Reheat cards", "voice_log": "Voice logging",
    "client_ledger": "Client budgets and receipts", "chef_clients": "Client households (free family app for each)",
    "batch_trip": "One shopping trip across homes", "card_routing": "Card routing", "invoices": "Client invoices",
    "coverage": "Coverage packs", "branding": "Your branding on labels",
}
HOUSEHOLD_PLANS = tuple(k for k, v in TIERS.items() if v["kind"] == "household")
CHEF_PLANS = tuple(k for k, v in TIERS.items() if v["kind"] == "chef")


class PlanError(Exception):
    def __init__(self, feature: str, needed: str, message: str | None = None):
        self.feature, self.needed = feature, needed
        super().__init__(message or f"{FEATURE_NAMES.get(feature, feature)} is part of {TIERS[needed]['label']}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _active(plan: str | None, until: str | None, fallback: str) -> str:
    if not plan or plan not in TIERS:
        return fallback
    if until and until < _now():
        return fallback
    return plan


def new_household_plan(signup_mode: str) -> str:
    """Open (App Store) sign-up starts on Free; households made with a sign-up code or an invitation are beta."""
    return "free" if signup_mode == "open" else "beta"


# ---------------------------------------------------------------- reading plans
def chef_plan(con, uid: str) -> str:
    r = con.execute("SELECT chef_plan, chef_plan_until FROM users WHERE id = ?", (uid,)).fetchone()
    return _active(r["chef_plan"], r["chef_plan_until"], "none") if r else "none"


def own_household_plan(con, hid: str) -> str:
    r = con.execute("SELECT plan, plan_until FROM households WHERE id = ?", (hid,)).fetchone()
    return _active(r["plan"], r["plan_until"], "free") if r else "free"


def household_plan(con, hid: str) -> dict:
    """The plan that applies to a household: its own, or Family through a chef on an active Pro plan."""
    own = own_household_plan(con, hid)
    via = None
    if TIERS[own]["rank"] < TIERS["family"]["rank"]:
        for r in con.execute("SELECT user_id FROM members WHERE household_id = ? AND role = 'chef'", (hid,)):
            if chef_plan(con, r["user_id"]) != "none":
                via = r["user_id"]
                break
    return {"plan": "family" if via else own, "own": own, "via_chef": bool(via)}


def has(plan: str, feature: str) -> bool:
    need = FEATURES[feature]
    return TIERS[plan]["kind"] == TIERS[need]["kind"] and TIERS[plan]["rank"] >= TIERS[need]["rank"]


def require_household(con, hid: str, feature: str) -> None:
    if not has(household_plan(con, hid)["plan"], feature):
        raise PlanError(feature, FEATURES[feature])


def require_chef(con, uid: str, feature: str) -> str:
    p = chef_plan(con, uid)
    if not has(p, feature):
        raise PlanError(feature, FEATURES[feature])
    return p


def client_limit(plan: str) -> int | None:
    return TIERS[plan].get("clients")


def chef_client_ids(con, uid: str) -> list[str]:
    return [r["household_id"] for r in con.execute(
        "SELECT m.household_id FROM members m JOIN households h ON h.id = m.household_id "
        "WHERE m.user_id = ? AND m.role = 'chef' AND h.status = 'active' ORDER BY m.joined", (uid,))]


def check_new_client(con, uid: str) -> None:
    """Before a chef joins or creates another client household."""
    p = chef_plan(con, uid)
    cap = client_limit(p)
    if cap is not None and len(chef_client_ids(con, uid)) >= cap:
        nxt = "chef_solo" if p == "none" else "chef_studio"
        raise PlanError("chef_clients", nxt, f"{TIERS[p]['label']} runs up to {cap} client household"
                        f"{'s' if cap != 1 else ''}; {TIERS[nxt]['label']} runs "
                        f"{'up to 3' if nxt == 'chef_solo' else 'any number'}")


# ---------------------------------------------------------------- changing plans
def set_chef_plan(con, uid: str, plan: str, until: str | None = None) -> None:
    if plan not in CHEF_PLANS:
        raise ValueError(f"chef plans are {', '.join(CHEF_PLANS)}")
    con.execute("UPDATE users SET chef_plan = ?, chef_plan_until = ? WHERE id = ?", (plan, until, uid))
    con.commit()


def set_household_plan(con, hid: str, plan: str, until: str | None = None) -> None:
    if plan not in HOUSEHOLD_PLANS:
        raise ValueError(f"household plans are {', '.join(HOUSEHOLD_PLANS)}")
    con.execute("UPDATE households SET plan = ?, plan_until = ? WHERE id = ?", (plan, until, hid))
    con.commit()


# RevenueCat entitlement id → our plan (set the same ids in the RevenueCat dashboard)
ENTITLEMENTS = {"family": "family", "chef_solo": "chef_solo", "chef_studio": "chef_studio"}
ENDS = {"EXPIRATION"}
STARTS = {"INITIAL_PURCHASE", "RENEWAL", "PRODUCT_CHANGE", "UNCANCELLATION", "NON_RENEWING_PURCHASE",
          "SUBSCRIPTION_EXTENDED", "TEMPORARY_ENTITLEMENT_GRANT"}


def apply_revenuecat(con, event: dict) -> dict:
    """One RevenueCat webhook event → plan changes. app_user_id is our user id (the app logs in to RevenueCat with
    it). A cancellation keeps the plan to the end of the paid period (expiration_at_ms); EXPIRATION ends it."""
    uid = str(event.get("app_user_id") or "")
    kind = event.get("type", "")
    ents = [ENTITLEMENTS[e] for e in (event.get("entitlement_ids") or []) if e in ENTITLEMENTS]
    if not ents or not con.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
        return {"applied": False, "reason": "unknown user or entitlement"}
    exp = event.get("expiration_at_ms")
    until = (dt.datetime.fromtimestamp(int(exp) / 1000, dt.timezone.utc).isoformat(timespec="seconds")
             if exp else None)
    if kind not in STARTS | ENDS | {"CANCELLATION", "BILLING_ISSUE"}:
        return {"applied": False, "reason": f"ignored {kind}"}
    best_chef = max((e for e in ents if e in CHEF_PLANS), key=lambda p: TIERS[p]["rank"], default=None)
    changed = []
    if best_chef:
        set_chef_plan(con, uid, "none" if kind in ENDS else best_chef, None if kind in ENDS else until)
        changed.append(("chef", "none" if kind in ENDS else best_chef))
    if "family" in ents:
        for r in con.execute("SELECT household_id FROM members WHERE user_id = ? AND role = 'admin'", (uid,)).fetchall():
            set_household_plan(con, r["household_id"], "free" if kind in ENDS else "family",
                               None if kind in ENDS else until)
            changed.append((r["household_id"], "free" if kind in ENDS else "family"))
    return {"applied": True, "changed": changed}


def catalog() -> dict:
    """For the paywall: every tier, its prices and what it unlocks."""
    out = {}
    for k, t in TIERS.items():
        if k in ("beta", "none"):
            continue
        out[k] = {**t, "features": [FEATURE_NAMES[f] for f, need in FEATURES.items() if has(k, f)]}
    return out
