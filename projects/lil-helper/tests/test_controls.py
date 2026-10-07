"""Tests per control this project implements. Offline, mock model, fictional household."""
from __future__ import annotations

import copy
import datetime as dt
import json

import pytest

from lilhelper import ai, catalog, chores, evals, feedback, planner, safety, store, week
from lilhelper.config import DAYS, HouseholdError, Settings, load_household, validate_household
from lilhelper.llm import Budget, BudgetExceeded, Registry, RegistryError
from lilhelper.prices import PriceBook

from conftest import ROOT

WEEK = dt.date(2026, 10, 5)


@pytest.fixture(scope="module")
def ctx():
    h = load_household(ROOT / "config" / "household.example.yaml")
    return h, catalog.get(), Settings.load(), PriceBook(h, WEEK)


# ---------------------------------------------------------------- NFR-1 safety rules a model can't override
def test_hidden_allergen_rejected(ctx):
    """A model idea with satay sauce is caught for the peanut allergy, even though "peanut" isn't in its name."""
    h, c, s, pb = ctx
    assert catalog.words_in("Thai satay noodle bowls", c.hidden["peanut"]) == ["satay"]
    assert catalog.words_in("Basil pesto pasta", c.hidden["tree_nut"]) == ["pesto"]
    ideas = ai.suggest_recipes(ai.AIContext.make(s), h, c, 10, [])
    assert any("satay" in r["name"].lower() and any("peanut" in w for w in r["why"]) for r in ideas.rejected)
    assert not any("peanut" in c.allergens_of(r) for r in ideas.accepted)


def test_plan_never_contains_an_allergen(ctx):
    h, c, s, pb = ctx
    p = planner.plan_week(h, c, pb, s)
    for e in p.entries:
        assert safety.recipe_for(c, c.recipes[e.recipe], h.eaters(e.meal)).ok, e.name


@pytest.mark.parametrize("item", ["grapes", "raisins", "onion", "garlic chicken", "chocolate chips", "xylitol gum"])
def test_dog_toxic_blocked(ctx, item):
    h, c, s, pb = ctx
    assert not safety.dog_item(c, h.pets["maple"], item).ok


def test_vet_note_blocks_plural_forms(ctx):
    h, c, s, pb = ctx
    pet = copy.deepcopy(h.pets["maple"])
    pet.vet_notes = "sweet potato, blueberry"
    assert not safety.dog_item(c, pet, "sweet_potatoes").ok
    assert not safety.dog_item(c, pet, "blueberries").ok
    assert safety.dog_item(c, pet, "carrots").ok


def test_dog_extras_capped_and_safe(workspace):
    r = week.draft(WEEK, ideas=False)
    for p in r.pets:
        for x in p.extras:
            assert x["kcal"] <= 1250 * 0.10 + 1
        assert all(b["why"] for b in p.blocked)


# ---------------------------------------------------------------- SEC-02 outside text is data
def test_flyer_instruction_flagged_and_not_obeyed(ctx):
    h, c, s, pb = ctx
    txt = (ROOT / "data" / "flyers" / "stop-and-shop-week.txt").read_text()    # carries an instruction line
    res = ai.read_flyer(ai.AIContext.make(s), h, c, pb, "stop_and_shop", text=txt)
    assert "instruction_on_flyer" in res.flags
    assert not any(r["status"] == "needs_confirm" and "lunchbox" in r["text"].lower() for r in res.items)
    pb_rows = [r for r in res.items if r["ingredient"] == "peanut_butter"]
    assert all(r["status"] != "needs_confirm" for r in pb_rows)


def test_typo_special_flagged(ctx):
    h, c, s, pb = ctx
    txt = (ROOT / "data" / "flyers" / "stop-and-shop-week.txt").read_text()    # has "$0.09" salmon
    res = ai.read_flyer(ai.AIContext.make(s), h, c, pb, "stop_and_shop", text=txt)
    salmon = [r for r in res.items if r["ingredient"] == "salmon"]
    assert salmon and salmon[0]["status"] == "flagged"


# ---------------------------------------------------------------- SEC-04 schema-checked model output
def test_invalid_model_reply_is_not_used(ctx, monkeypatch):
    h, c, s, pb = ctx
    cx = ai.AIContext.make(s)
    monkeypatch.setattr(cx, "ask", lambda *a, **k: {"items": "not a list"})
    res = ai.read_flyer(cx, h, c, pb, "trader_joes", text="apples $1")
    assert res.items == [] and "schema_invalid" in res.flags


# ---------------------------------------------------------------- DATA-03 minimization
def test_kids_names_never_sent_to_a_model(ctx, monkeypatch):
    h, c, s, pb = ctx
    cx = ai.AIContext.make(s)
    sent = []
    orig = cx.client.complete

    def spy(alias, system, user, max_tokens, fallback_alias=None, images=None):
        sent.append(system + user)
        return orig(alias, system, user, max_tokens, fallback_alias=fallback_alias, images=images)

    monkeypatch.setattr(cx.client, "complete", spy)
    ai.suggest_recipes(cx, h, c, 10, [])
    p = planner.plan_week(h, c, pb, s)
    ai.write_notes(cx, h, p)
    blob = "\n".join(sent)
    assert sent and "Leo" not in blob and "Ivy" not in blob


def test_card_number_refused(ctx):
    h, c, s, pb = ctx
    raw = copy.deepcopy(h.raw)
    raw["cards"] = ["4111 1111 1111 1111"]
    with pytest.raises(HouseholdError):
        validate_household(raw, s)


def test_telemetry_has_no_names_or_dishes(workspace, governance_spool):
    week.draft(WEEK, ideas=True)
    text = governance_spool.read_text()
    for word in ("Dana", "Leo", "Ivy", "Maple", "Rivera", "soup", "taco"):
        assert word not in text


# ---------------------------------------------------------------- HITL-02 a named adult approves; nothing is bought
def test_only_an_adult_can_approve(workspace):
    week.draft(WEEK, ideas=False)
    with pytest.raises(PermissionError):
        week.approve(WEEK, "leo", 60)
    out = week.approve(WEEK, "dana", 60)
    con = store.connect()
    rows = [dict(r) for r in con.execute("SELECT actor, action FROM audit")]
    assert out["approved_by"] == "dana" and {"actor": "dana", "action": "approve"} in rows


def test_swap_keeps_the_rest_of_the_week(workspace):
    r1 = week.draft(WEEK, ideas=False)
    e = r1.plan.at("tue", "dinner")
    r2 = week.swap(WEEK, "tue", "dinner")
    assert r2.plan.at("tue", "dinner").recipe != e.recipe
    for x in r1.plan.entries:
        if (x.day, x.meal) != ("tue", "dinner"):
            assert r2.plan.at(x.day, x.meal).recipe == x.recipe


# ---------------------------------------------------------------- constraints and shopping
def test_prep_limits_and_variety(ctx):
    h, c, s, pb = ctx
    p = planner.plan_week(h, c, pb, s)
    assert all(e.active <= h.prep_limit(e.day) or e.prep_day != e.day for e in p.entries)
    rids = [e.recipe for e in p.entries]
    assert len(rids) == len(set(rids))


def test_budget_too_small_is_said_not_hidden(workspace):
    h = load_household()
    h.raw["household"]["budget_per_week"] = 60
    r = week.draft(WEEK, h=h, ideas=False, save=False)
    full = week.draft(WEEK, ideas=False, save=False)
    assert any(f.startswith("over_budget_by_") for f in r.flags)
    assert len(r.plan.entries) == len(full.plan.entries)


def test_trader_joes_is_always_in_store(workspace):
    h = load_household()
    h.raw["household"]["time_value_per_hour"] = 0
    r = week.draft(WEEK, h=h, ideas=False, save=False, choice="cheapest")
    for sp in r.options.values():
        assert all(o.mode == "in_store" for o in sp.orders if o.store == "trader_joes")


def test_instacart_payload_matches_the_developer_platform(workspace):
    from lilhelper import shopping
    r = week.draft(WEEK, ideas=False, save=False)
    for sp in r.options.values():
        for o in sp.orders:
            if o.handoff == "instacart":
                p = shopping.handoff_payload(o, load_household())
                assert p["link_type"] == "shopping_list" and p["line_items"]
                assert all({"name", "quantity", "unit"} <= set(li) for li in p["line_items"])


# ---------------------------------------------------------------- chores
def test_rota_respects_ages_and_is_fair():
    h = load_household()
    rota, load, gaps = chores.rota(h, [d for d in DAYS if d != "thu"])
    by = {(a.day, a.job): a.person for a in rota}
    assert not gaps
    assert all(by.get((d, "dishes")) != "ivy" for d in DAYS)        # 4-year-old: no dishes
    assert all(by.get((d, "cook")) in ("dana", "sam") for d in DAYS if (d, "cook") in by)
    assert all(by.get((d, "dishes")) != by.get((d, "cook")) for d in DAYS if (d, "dishes") in by)
    assert abs(load["dana"] - load["sam"]) <= 3


# ---------------------------------------------------------------- HITL-03 feedback loop
def test_portions_learn_from_leftovers(workspace):
    s = Settings.load()
    con = store.connect()
    for i in range(3):
        wk = (WEEK + dt.timedelta(weeks=i)).isoformat()
        feedback.record(con, wk, "mon", "dinner", "lentil_soup", "lots_left", 3, "dana")
        feedback.learn(con, s, wk)
    assert store.portions(con)["lentil_soup"] < 0.85
    with pytest.raises(ValueError):
        feedback.record(con, WEEK.isoformat(), "mon", "dinner", "lentil_soup", "half", 3, "dana")


# ---------------------------------------------------------------- MODEL-01 / COST-01 / EVAL-02
def test_registry_refuses_unknown_alias():
    reg = Registry(ROOT / "config" / "models.yaml")
    with pytest.raises(RegistryError):
        reg.resolve("no-such-alias")


def test_budget_guard_stops_spend():
    spec = Registry(ROOT / "config" / "models.yaml").resolve("helper-suggest")
    with pytest.raises(BudgetExceeded):
        Budget(0.10, 100).preflight(spec, "x" * 2000, 100)            # over the per-call token cap
    b = Budget(0.0001, 10_000)
    b.record(0.0001)
    with pytest.raises(BudgetExceeded):
        b.preflight(spec, "hello", 1000)                              # over the per-run spend cap


def test_eval_gate_passes(workspace):
    rep = evals.run()
    failed = [c["id"] for c in rep["cases"] if not c["passed"]]
    assert rep["passed"], failed
    assert rep["metrics"]["must_reject_recall"] == 1.0
