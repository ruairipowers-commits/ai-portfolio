"""v2 features on the example household: cards and partnerships, spending, receipts, cook-from, forecast, cost reports,
storage and the freezer, specials by channel, leftovers and kid chef nights."""
import datetime as dt

import pytest

from lilhelper import ai, catalog, cookfrom, forecast, money, outputs, reports, spend, storage, store, week
from lilhelper.config import ROOT, Settings, load_household
from lilhelper.prices import PriceBook

W = dt.date(2026, 10, 12)


@pytest.fixture()
def hc(workspace):
    h = load_household()
    c = catalog.for_household(h)
    return h, c, PriceBook(h, W, catalog=c)


CARDS = ["amex_blue_cash_everyday", "amex_platinum", "costco_anywhere_visa"]


def test_best_card_follows_category_caps_and_acceptance(hc):
    h, _, _ = hc
    h.raw["cards"] = CARDS
    wf = money.best_card(h, "whole_foods", "pickup", 100)
    assert wf.card == "amex_blue_cash_everyday" and wf.pct >= 0.03
    full = money.best_card(h, "whole_foods", "pickup", 100, used={(wf.card, wf.category): 6000})
    assert full.earned < wf.earned                       # the cap is spent: falls back to another card or base rate
    cc = money.best_card(h, "costco", "in_store", 100)
    assert cc.card == "costco_anywhere_visa"               # Costco takes Visa only


def test_uber_cash_is_a_monthly_credit(hc):
    h, _, _ = hc
    h.raw["cards"] = CARDS
    amt, note = money.credits_for(h, "uber_eats", dt.date(2026, 10, 9))
    assert amt == 15 and note
    assert money.credits_for(h, "uber_eats", dt.date(2026, 10, 9), already_used=15)[0] == 0
    assert money.credits_for(h, "uber_eats", dt.date(2026, 12, 9))[0] == 35


def test_statement_import_keeps_only_food_and_dedupes(hc):
    h, _, _ = hc
    h.raw["cards"] = CARDS
    con = store.connect()
    text = (ROOT / "data" / "statements" / "amex-2026-10.csv").read_text()
    r = spend.import_statement(con, h, text, "amex_blue_cash_everyday", "dana")
    assert r["imported"] > 0 and r["skipped_not_food"] > 0
    again = spend.import_statement(con, h, text, "amex_blue_cash_everyday", "dana")
    assert again["imported"] == 0                          # same rows twice count once
    cols = {r[1] for r in con.execute("PRAGMA table_info(spend)")}
    assert not cols & {"card_number", "account", "description_raw"}
    s = spend.summary(con, h, dt.date(2026, 10, 5))
    assert s["spent"]["groceries"] == pytest.approx(47.30 + 84.12)          # 5 and 8 Oct
    assert s["spent"]["eat_out"] == pytest.approx(96.80) and s["budget"]["total"] > 0
    assert s["month"]["total"] > s["spent"]["total"]


def test_receipt_flags_instructions_and_strips_card_numbers(hc):
    h, c, pb = hc
    text = (ROOT / "data" / "receipts" / "whole-foods-2026-10-07.txt").read_text()
    ctx = ai.AIContext.make(Settings.load())
    res = ai.read_receipt(ctx, h, c, pb, text=text)
    assert "instruction_on_receipt" in res.flags
    assert res.total and res.items
    assert not any(ai.CARD_NUMBER.search(str(v)) for i in res.items for v in i.values())
    con = store.connect()
    out = spend.confirm_receipt(con, h, res, None, "dana")
    assert out["recorded"] and out["prices_updated"] and con.execute("SELECT COUNT(*) FROM prices_seen").fetchone()[0] > 0


def test_cook_from_what_ive_got(hc):
    h, c, pb = hc
    r = cookfrom.suggest(h, c, pb, text="chicken, rice, broccoli, zorblax", use_pantry=False)
    assert r["ideas"] and "zorblax" in r["not_recognised"]
    top = r["ideas"][0]
    assert top["coverage"] >= 0.25
    people_allergies = h.everyone_allergies()
    for idea in r["ideas"]:
        rec = c.recipes[idea["recipe"]]
        assert not {a for i in rec.ing for a in c.ingredients[i].allergens} & set(people_allergies)


def test_forecast_buys_on_a_trip_before_its_needed(hc):
    h, c, pb = hc
    week.draft(W, ideas=False)
    week.draft(W + dt.timedelta(weeks=1), ideas=False)
    con = store.connect()
    recs = forecast._week_records(con, W, 2)
    con.close()
    common = forecast.common(c, pb, recs)
    assert common
    f = forecast.forecast(h, c, pb, common[0]["ingredient"], W, weeks=2, today=W - dt.timedelta(days=2))
    assert f["need_total"] > 0 and f["uses"]
    first_use = min(u["date"] for u in f["uses"])
    bought = f["buys"] + f["planned_purchases"]
    assert bought and min(b["date"] for b in bought) <= first_use      # bought on a trip before it's needed
    assert f["end_stock"] >= -0.01


def test_cost_report_per_person_meal_week(hc):
    h, c, _ = hc
    week.draft(W, ideas=False)
    week.approve(W, "dana", 60)
    r = reports.cost_report(h, c, end=W, weeks=1)
    row = r["weeks"][-1]
    assert row["food_bill"] > 0 and row["per_person"] and row["meals"]
    assert abs(row["food_bill"] - row["food_used"] - row["stock_change"]) < 0.05
    assert all(m["per_serving"] == pytest.approx(m["cost"] / m["servings"], abs=0.02) for m in row["meals"])
    assert set(r["by_meal"]) >= {"dinner"} and r["analysis"]


def test_cost_range_limits_dinners(hc):
    h, c, _ = hc
    res = week.draft(W, ideas=False)
    hi = h.cost_range("dinner")[1]
    over = [e for e in res.plan.entries if e.meal == "dinner" and e.kind == "cook" and e.per_serving > hi + 0.01]
    assert not over or any("cost" in f for f in res.flags)


def test_leftover_lunches_and_kid_chef(hc):
    h, c, _ = hc
    res = week.draft(W, ideas=False)
    left = [e for e in res.plan.entries if e.kind == "leftovers"]
    assert left and all(e.meal == "leftovers" and e.eaters for e in left)
    kc = h.kid_chef()
    for day, kid in kc.items():
        e = next(e for e in res.plan.entries if e.day == day and e.meal == "dinner")
        assert e.cook == kid and any("kid chef" in w for w in e.why)
        assert not any(kid in w.lower() for w in e.why)      # no child's name in text that goes to the model
        assert c.recipes[e.recipe].kid_min_age is not None


def test_in_store_specials_dont_apply_online(hc):
    h, c, _ = hc
    iid = "broccoli"
    base = PriceBook(h, W, catalog=c)
    shelf = base.regular_unit_at(iid, "whole_foods")
    pack = base.offers(iid, "whole_foods")[0].pack
    sp = [{"store": "whole_foods", "ingredient": iid, "price": round(shelf * 0.5 * pack, 2), "channel": "in_store"}]
    pb = PriceBook(h, W, extra_specials=sp, catalog=c)
    assert pb.offers(iid, "whole_foods", "in_store")[0].unit < shelf
    online = [o.unit for o in base.offers(iid, "whole_foods", "delivery")]
    assert [o.unit for o in pb.offers(iid, "whole_foods", "delivery")] == online   # the in-store deal doesn't reach online


def test_storage_space_limits_buy_ahead(hc):
    h, c, pb = hc
    con = store.connect()
    free = storage.free_space(h, con, c)
    assert set(free) >= {"fridge", "freezer"} and free["freezer"] <= h.storage()["freezer_l"]
    ahead = storage.upcoming(con, c, W, weeks=2)
    picks = storage.buy_ahead(h, c, pb, ahead, {"fridge": 0.0, "freezer": 0.0, "pantry": 0.0})
    assert all(p.litres == 0 for p in picks) or not picks   # no room, nothing bulky bought ahead


def test_calendar_feed_per_person(hc):
    h, c, _ = hc
    week.draft(W, ideas=False)
    week.approve(W, "dana", 60)
    con = store.connect()
    rec = store.get_week(con, W.isoformat())
    feed = outputs.ics(h, [rec], person="dana")
    assert "BEGIN:VEVENT" in feed and "REFRESH-INTERVAL" in feed
    assert all(len(line.encode()) <= 75 for line in feed.split("\r\n"))


def test_forecast_never_suggests_food_that_wont_keep(hc):
    h, c, pb = hc
    h.raw["shopping_sessions"] = [{"day": "sun_before", "time": "10:00", "store": "whole_foods", "mode": "in_store"}]
    for n in range(3):
        week.draft(W + dt.timedelta(weeks=n), h=h, ideas=False)
    for iid in ("salmon", "cod", "chicken_thighs", "spinach"):
        if iid not in c.ingredients:
            continue
        f = forecast.forecast(h, c, pb, iid, W, weeks=3, today=W - dt.timedelta(days=2))
        ing = c.ingredients[iid]
        for b in f["buys"]:
            assert b["keep"] in ("freeze", "too_early") or b["keep"] == ing.storage
            if b["keep"] == "freeze":
                assert ing.freezable


def test_kid_chef_night_survives_the_no_repeat_rule(hc):
    h, c, _ = hc
    for n in range(3):
        res = week.draft(W + dt.timedelta(weeks=n), ideas=False)
        week.approve(W + dt.timedelta(weeks=n), "dana", 30)
        wed = next(e for e in res.plan.entries if e.day == "wed" and e.meal == "dinner")
        assert wed.cook == "leo"
