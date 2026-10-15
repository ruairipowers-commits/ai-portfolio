"""The app's API: accounts, roles, invites, settings, the week, calendar taps (HITL-02, SEC-01, DATA-03)."""
import re

import pytest

from lilhelper import api

W = "2026-10-19"


def test_signup_needs_a_code_and_no_enumeration(server):
    c = server.client
    a = c.post("/api/auth/request", json={"email": "nobody@example.com"}).json()
    b = c.post("/api/auth/request", json={"email": "ruairi@example.com"}).json()
    assert a == b
    H, r = server.signin("ruairi@example.com")
    assert r["household"] is None and r["households"] == []
    assert c.post("/api/households", headers=H, json={"name": "X", "your_name": "R"}).status_code == 403
    assert c.post("/api/households", headers=H, json={"name": "X", "your_name": "R", "signup_code": "nope"}).status_code == 403
    r = c.post("/api/households", headers=H, json={"name": "X", "your_name": "R", "signup_code": "family2026"})
    assert r.status_code == 200 and r.json()["household"]


def test_open_and_closed_signup(server, monkeypatch):
    monkeypatch.setenv("HELPER_SIGNUP", "open")
    H, _ = server.signin("a@example.com")
    assert server.client.post("/api/households", headers=H, json={"name": "A", "your_name": "A"}).status_code == 200
    monkeypatch.setenv("HELPER_SIGNUP", "closed")
    H, _ = server.signin("a@example.com")
    assert server.client.post("/api/households", headers=H, json={"name": "B", "your_name": "B",
                                                                   "signup_code": "family2026"}).status_code == 403


def test_admin_adds_and_invites_and_roles_hold(server):
    c = server.client
    H, hid = server.household()
    assert c.post("/api/household/people", headers=H, json={"name": "Lili", "can_cook": True,
                                                            "email": "lili@example.com"}).json() == {"added": "lili"}
    c.post("/api/household/people", headers=H, json={"name": "Son", "age_band": "kid", "age": 11,
                                                      "allergies": ["peanut"]})
    assert c.post("/api/household/invites", headers=H, json={"person_id": "lili", "email": "lili@example.com"}).json()["role"] == "adult"
    H2, r2 = server.signin("lili@example.com", invite_tag="invite")
    assert r2["household"] == hid
    s = c.get("/api/household/settings", headers=H2).json()
    assert s["role"] == "adult" and s["me"] == "lili"
    # an adult can't change settings or add people; the admin can
    assert c.patch("/api/household/settings/dinner_times", headers=H2, json={"value": {"default": "18:30"}}).status_code == 403
    assert c.post("/api/household/people", headers=H2, json={"name": "X"}).status_code == 403
    assert c.patch("/api/household/settings/dinner_times", headers=H, json={"value": {"default": "18:30"}}).status_code == 200
    # an adult may edit their own likes, not someone else's details
    assert c.put("/api/household/people/son", headers=H2, json={"name": "Son", "age_band": "kid"}).status_code == 403
    assert c.put("/api/household/people/lili", headers=H2, json={"name": "Lili", "likes": ["chicken_tacos"]}).status_code == 200
    people = {p["id"]: p for p in c.get("/api/household/people", headers=H).json()["people"]}
    assert people["lili"]["signed_up"] and not people["son"]["signed_up"] and people["ruairi"]["role"] == "admin"


def test_settings_are_validated(server):
    c = server.client
    H, _ = server.household()
    bad = [("dinner_times", {"default": "6pm"}),
           ("shopping_sessions", [{"day": "sun_before", "store": "trader_joes", "mode": "delivery"}]),
           ("cards", ["4111 1111 1111 1111"]),
           ("cost_per_serving", {"min": 5, "max": 2})]
    for section, value in bad:
        assert c.patch(f"/api/household/settings/{section}", headers=H, json={"value": value}).status_code == 422, section
    assert c.post("/api/household/people", headers=H, json={"name": "Kid", "age_band": "kid", "admin": True}).status_code == 422
    v = c.get("/api/household/settings", headers=H).json()
    assert c.put("/api/household/settings", headers=H, json={"settings": v["settings"], "version": "stale"}).status_code == 409


def test_households_are_isolated(server):
    c = server.client
    H1, h1 = server.household("one@example.com", "One", "House one")
    H2, h2 = server.household("two@example.com", "Two", "House two")
    c.post("/api/week/draft", headers=H1, json={"week": W})
    assert c.get("/api/week", headers=H2, params={"week": W}).status_code == 404
    # a session can't be pointed at someone else's household
    assert c.post("/api/session/household", headers=H2, json={"household_id": h1}).status_code == 403
    forged = {"Authorization": "Bearer " + api.sign("session", f"{c.get('/api/me', headers=H2).json()['user']['id']}|{h1}", 60)}
    assert c.get("/api/week", headers=forged, params={"week": W}).status_code == 403


def test_week_flow_handoffs_after_approval_and_kids_cant_approve(server):
    c = server.client
    H, hid = server.household()
    c.post("/api/household/people", headers=H, json={"name": "Son", "age_band": "kid", "age": 11, "email": "son@example.com"})
    c.post("/api/household/invites", headers=H, json={"person_id": "son", "email": "son@example.com"})
    Hk, _ = server.signin("son@example.com", invite_tag="invite")
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    assert w["status"] == "draft"
    assert c.get("/api/week/shopping", headers=H, params={"week": W}).status_code == 409
    assert c.post("/api/week/approve", headers=Hk, json={"week": W, "seconds": 10}).status_code == 403
    a = c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 90}).json()
    assert a["status"] == "approved"
    sh = c.get("/api/week/shopping", headers=H, params={"week": W}).json()
    assert sh["orders"] and all(o["url"] is None for o in sh["orders"])
    # kids can still say how a meal went
    e = next(e for e in a["plan"]["entries"] if e["meal"] == "dinner")
    assert c.post("/api/feedback", headers=Hk, json={"week": W, "day": e["day"], "meal": "dinner", "rating": 5}).status_code == 200


def test_nights_and_away(server):
    c = server.client
    H, _ = server.household()
    c.post("/api/household/people", headers=H, json={"name": "Lili", "can_cook": True})
    c.post("/api/week/draft", headers=H, json={"week": W})
    w = c.post("/api/week/night", headers=H, json={"week": W, "day": "fri", "kind": "takeout"}).json()
    assert w["plan"]["special_nights"]["fri"] == "takeout" and not any(
        e["day"] == "fri" and e["meal"] == "dinner" for e in w["plan"]["entries"])
    assert w["eating_out"][0]["budget"] == 50
    w = c.post("/api/week/away", headers=H, json={"week": W, "day": "tue", "person": "lili", "away": True}).json()
    tue = next(e for e in w["plan"]["entries"] if e["day"] == "tue" and e["meal"] == "dinner")
    assert "lili" not in tue["eaters"]


def test_calendar_feed_and_tap_links(server):
    c = server.client
    H, hid = server.household()
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 60})
    link = c.get("/api/calendar/link", headers=H).json()
    path = re.sub(r"^https?://[^/]+", "", link["https"])
    feed = c.get(path)
    assert feed.status_code == 200 and "BEGIN:VCALENDAR" in feed.text
    assert link["webcal"].startswith("webcal://")
    taps = re.findall(r"4★ (https?://\S+?/t/\S+?)(?: |\\n)", feed.text.replace("\r\n ", ""))
    assert taps
    t = re.sub(r"^https?://[^/]+", "", taps[0])
    page = c.get(t)
    assert page.status_code == 200 and "fetch(location.href" in page.text     # recorded by the page, not the GET
    assert c.post(t).json()["ok"]
    # rotating the feed kills the old URL
    c.post("/api/calendar/rotate", headers=H)
    assert c.get(path).status_code == 404
    assert c.get(path.replace(".ics", "x.ics")).status_code == 404


def test_delete_account_and_household(server):
    c = server.client
    H, hid = server.household()
    assert c.request("DELETE", "/api/household", headers=H, json={"confirm": "wrong"}).status_code == 422
    assert c.delete("/api/account", headers=H).json()["households_deleted"] == 1
    assert c.get("/api/me", headers=H).status_code == 401


def test_production_requires_a_secret(monkeypatch):
    monkeypatch.setenv("HELPER_ENV", "production")
    monkeypatch.delenv("HELPER_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        api.sign("session", "x", 60)


def test_signin_is_rate_limited(server):
    for _ in range(5):
        server.client.post("/api/auth/request", json={"email": "spam@example.com"})
    assert server.client.post("/api/auth/request", json={"email": "spam@example.com"}).status_code == 429


def test_custom_recipe_is_planned_and_allergens_warned(server):
    c = server.client
    H, _ = server.household()
    c.post("/api/household/people", headers=H, json={"name": "Son", "age_band": "kid", "age": 11, "allergies": ["peanut"]})
    pad = {"name": "Grandma's peanut noodles", "serves": 4, "kid_min_age": 10,
           "ingredients": [{"ingredient": "peanut_butter", "qty": 0.5, "unit": "cup"},
                           {"text": "pasta", "qty": 1, "unit": "lb"}],
           "instructions": ["Boil", "Toss"], "season_months": [10, 11], "want": {"times": 2, "per_weeks": 4}}
    unknown = c.post("/api/recipes", headers=H, json={**pad, "ingredients": [{"text": "zorblax", "qty": 1}]})
    assert unknown.status_code == 422 and unknown.json()["detail"]["unknown"] == ["zorblax"]
    r = c.post("/api/recipes", headers=H, json=pad).json()
    assert "peanut" in r["allergens"] and r["warning"]
    mine = c.get("/api/recipes", headers=H, params={"mine": True}).json()["recipes"]
    assert [x["id"] for x in mine] == [r["saved"]] and mine[0]["kid_min_age"] == 10
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    assert all(e["recipe"] != r["saved"] for e in w["plan"]["entries"])        # never planned with an allergy at home
    assert c.post("/api/recipes", headers=H, json={**pad, "name": "Bad", "season_months": [13]}).status_code == 422


def test_specials_by_store_and_channel(server):
    c = server.client
    H, _ = server.household()
    bad = c.post("/api/specials", headers=H, json={"week": W, "store": "whole_foods", "ingredient": "broccoli",
                                                    "price": 1.0, "channel": "carrier pigeon"})
    assert bad.status_code == 422
    ok = c.post("/api/specials", headers=H, json={"week": W, "store": "whole_foods", "ingredient": "broccoli",
                                                   "price": 1.0, "channel": "in_store", "repeat_weekly": True})
    assert ok.status_code == 200, ok.text
    sp = c.get("/api/specials", headers=H, params={"week": "2026-10-26"}).json()["specials"]
    assert any(s["ingredient"] == "broccoli" and s["channel"] == "in_store" for s in sp)   # repeats every week


def test_money_reports_forecast_and_cookfrom_endpoints(server):
    c = server.client
    H, _ = server.household()
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 30})
    assert c.post("/api/money/spend", headers=H, json={"date": "2026-10-20", "amount": 42.5, "store": "whole_foods",
                                                       "category": "groceries"}).status_code == 200
    s = c.get("/api/money/summary", headers=H, params={"week": W}).json()
    assert s["spent"]["groceries"] == 42.5
    assert c.get("/api/reports/cost", headers=H, params={"end": W, "weeks": 2}).json()["weeks"]
    ing = c.get("/api/forecast/ingredients", headers=H, params={"start": W, "weeks": 2}).json()["ingredients"]
    assert ing
    f = c.get("/api/forecast", headers=H, params={"ingredient": ing[0]["ingredient"], "start": W, "weeks": 2}).json()
    assert f["need_total"] > 0
    cf = c.post("/api/cookfrom", headers=H, json={"text": "eggs, spinach, cheese"}).json()
    assert cf["ideas"]
    assert c.get("/api/storage", headers=H).status_code == 200


def test_changes_to_an_approved_week_apply_in_place(server):
    c = server.client
    H, _ = server.household()
    c.post("/api/household/people", headers=H, json={"name": "Lili", "can_cook": True})
    c.post("/api/week/draft", headers=H, json={"week": W})
    a = c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 30}).json()
    shop_before = a["options"][a["choice"]]["total"]
    w = c.post("/api/week/night", headers=H, json={"week": W, "day": "wed", "kind": "takeout"}).json()
    assert w["status"] == "approved" and w["plan"]["special_nights"]["wed"] == "takeout"
    assert not any(e["day"] == "wed" and e["meal"] == "dinner" for e in w["plan"]["entries"])
    assert w["eating_out"] and w["options"][w["choice"]]["total"] == shop_before      # shopping untouched
    assert c.post("/api/week/night", headers=H, json={"week": W, "day": "wed", "kind": "cook"}).status_code == 409
    w = c.post("/api/week/away", headers=H, json={"week": W, "day": "thu", "person": "lili", "away": True}).json()
    thu = next(e for e in w["plan"]["entries"] if e["day"] == "thu" and e["meal"] == "dinner")
    assert "lili" not in thu["eaters"] and w["away"] == {"thu": ["lili"]}
    # a later change still works (the refused one left nothing behind)
    assert c.post("/api/week/night", headers=H, json={"week": W, "day": "fri", "kind": "eat_out"}).status_code == 200
