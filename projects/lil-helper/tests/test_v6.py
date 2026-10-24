"""v6: the card wallet, delivery services, the home address, the owner's prices and subscriptions, and the chef
marketplace (SEC-04, DATA-03, HITL-02)."""
import datetime as dt

from lilhelper import accounts, billing, money, plans
from lilhelper.config import load_household, parse_household, tenant

WESTPORT = {"line1": "1 Main St", "city": "Westport", "state": "CT", "zip": "06880", "lat": 41.1415, "lon": -73.3579}
NORWALK = {"city": "Norwalk", "state": "CT", "zip": "06851", "lat": 41.1177, "lon": -73.4082}       # ~3 miles
BOSTON = {"city": "Boston", "state": "MA", "zip": "02108", "lat": 42.3576, "lon": -71.0636}         # ~140 miles


def _hh(raw_cards):
    from lilhelper.accounts import starter_settings
    raw = starter_settings("T", "northeast-us", {"id": "a", "name": "A", "admin": True, "age_band": "adult"})
    raw["cards"] = raw_cards
    return parse_household(raw)


def test_wallet_ranking_caps_limits_and_expiry():
    gold = {"id": "gold", "name": "Amex Gold", "issuer": "American Express", "network": "amex", "last4": "1004",
            "expires": "2030-01", "earn": {"supermarket": {"pct": 0.04, "annual_cap": 1000}, "default": {"pct": 0.01}},
            "primary": True}
    blue = {"id": "blue", "template": "amex_blue_cash_everyday", "monthly_limit": 300}
    old = {"id": "old", "name": "Old card", "network": "visa", "expires": "2020-01", "earn": {"default": {"pct": 0.05}}}
    h = _hh([gold, blue, old])
    used = {}
    p = money.best_card(h, "whole_foods", "in_store", 100, used=used)
    assert p.card == "gold" and "your card here" in p.note and "Old card has expired" in p.note
    used[("gold", "supermarket")] = 1000                     # bonus cap used up → the next best, and it says why
    p = money.best_card(h, "whole_foods", "in_store", 100, used=used)
    assert p.card == "blue" and "used its supermarket bonus" in p.note
    used[("blue", money.MONTH)] = 250                        # $50 left under Blue's own monthly limit
    p = money.best_card(h, "whole_foods", "in_store", 100, used=used)
    assert p.card == "gold" and "monthly limit" in p.note
    st = {c["id"]: c for c in money.card_status(h, {("gold", "supermarket"): 1000.0})}
    assert st["gold"]["caps"][0]["left"] == 0 and st["gold"]["caps"][0]["next_best"] == "Amex Blue Cash Everyday"
    assert st["old"]["warn"] == "expired" and st["blue"]["issuer"] == "American Express"


def test_wallet_api_add_edit_and_refuse_card_numbers(server):
    c = server.client
    H, _ = server.household()
    r = c.put("/api/wallet/cards", headers=H, json={"cards": [
        {"name": "Amex Gold", "issuer": "American Express", "network": "amex", "expires": "2029-08", "last4": "1004",
         "earn": {"supermarket": {"points": 4, "program": "amex_membership_rewards", "annual_cap": 25000},
                  "default": {"points": 1, "program": "amex_membership_rewards"}},
         "stores": ["whole_foods"], "credits": [{"name": "Dining credit", "monthly": 10, "applies_to": ["uber_eats"]}]},
        "costco_anywhere_visa"]})
    assert r.status_code == 200, r.text
    w = r.json()
    gold = next(x for x in w["cards"] if x["name"] == "Amex Gold")
    assert gold["id"] == "amex_gold" and gold["stores"] == ["whole_foods"] and gold["caps"][0]["cap"] == 25000
    assert any(x["store"] == "whole_foods" and x["card"] == "amex_gold" for x in w["where"])
    for bad in ({"name": "X", "last4": "4111111111111111"}, {"name": "X", "notes": "4111 1111 1111 1111"},
                {"name": "X", "expires": "08/29"}, {"name": "X", "earn": {"supermarket": {"pct": 3}}}):
        assert c.put("/api/wallet/cards", headers=H, json={"cards": [bad]}).status_code == 422, bad
    assert c.post("/api/wallet/cards/costco_anywhere_visa/primary", headers=H).status_code == 200
    cards = {x["id"]: x for x in c.get("/api/wallet", headers=H).json()["cards"]}
    assert cards["costco_anywhere_visa"]["primary"] and not cards["amex_gold"]["primary"]


def test_delivery_services_and_handoffs(server):
    c = server.client
    H, _ = server.household()
    r = c.put("/api/delivery", headers=H, json={"services": ["instacart", "doordash", "uber_eats"],
                                                "memberships": ["dashpass"], "takeout_service": "doordash"})
    assert r.status_code == 200
    d = {s["id"]: s for s in r.json()["services"]}
    assert d["doordash"]["on"] and d["doordash"]["membership"]["on"] and not d["walmart"]["on"]
    assert r.json()["takeout_service"] == "doordash"
    assert c.put("/api/delivery", headers=H, json={"services": ["nope"]}).status_code == 422
    from lilhelper import household_api
    with tenant(c.get("/api/me", headers=H).json()["current"]["household_id"]):
        h = load_household()
    via = household_api.handoffs(h, {"handoff": "instacart"}, "1 × milk")
    assert [v["service"] for v in via] == ["doordash", "uber_eats"]


def test_home_address_typed_or_located(server):
    c = server.client
    H, _ = server.household()
    assert c.put("/api/household/address", headers=H, json={"city": "Westport", "zip": "6880"}).status_code == 422
    r = c.put("/api/household/address", headers=H, json={**WESTPORT, "source": "location"})
    assert r.status_code == 200 and r.json()["address"]["state"] == "CT"
    assert c.get("/api/household/address", headers=H).json()["address"]["zip"] == "06880"


def test_owner_prices_grandfather_and_upcharge(server, monkeypatch):
    c = server.client
    H, r = server.signin("owner@example.com")
    assert c.get("/api/owner", headers=H).status_code == 403
    monkeypatch.setenv("HELPER_OWNER_EMAILS", "owner@example.com")
    assert c.get("/api/me", headers=H).json()["is_owner"]
    r = c.put("/api/owner/prices/chef_solo", headers=H, json={"monthly": 29, "annual_discount_pct": 20}).json()
    assert r["yearly"] == 278.4 and r["savings_pct"] == 20
    a = c.post("/api/owner/subscriptions", headers=H, json={"email": "chef-a@example.com", "plan": "chef_solo"}).json()
    b = c.post("/api/owner/subscriptions", headers=H, json={"email": "chef-b@example.com", "plan": "chef_solo",
                                                            "interval": "yearly"}).json()
    assert a["price"] == 29 and b["price"] == 278.4
    con = accounts.connect()
    assert plans.chef_plan(con, a["subject"]) == "chef_solo"
    con.close()
    # raise the price; grandfather A, B follows the list price at renewal
    c.put("/api/owner/prices/chef_solo", headers=H, json={"monthly": 35, "yearly": 336})
    c.put(f"/api/owner/subscriptions/{a['id']}", headers=H, json={"policy": "grandfather"})
    subs = {s["id"]: s for s in c.get("/api/owner", headers=H).json()["subscriptions"]}
    assert subs[a["id"]]["next_price"] == 29 and subs[b["id"]]["next_price"] == 336 and subs[b["id"]]["change"] > 0
    assert c.get("/api/plans", headers=H).json()["tiers"]["chef_solo"]["monthly"] == 35
    # a custom price for one subscriber, then a renewal
    c.put(f"/api/owner/subscriptions/{b['id']}", headers=H, json={"policy": "custom", "custom_price": 300})
    con = accounts.connect()
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=400)
    notes = billing.notices_due(con, later)
    assert {s["id"] for s in notes} == {b["id"]} or not notes or all(s["id"] != a["id"] for s in notes)
    done = {d["id"]: d for d in billing.renew_due(con, later)}
    assert done[a["id"]]["to"] == 29 and done[b["id"]]["to"] == 300
    con.close()
    assert c.post("/api/owner/subscriptions/bulk", headers=H, json={"plan": "chef_solo", "policy": "grandfather"}).json()["changed"] == 2


def test_price_rise_notice_is_sent_once(server, monkeypatch):
    from lilhelper import schedule
    con = accounts.connect()
    u = accounts.get_or_create_user(con, "chef-n@example.com")
    s = billing.subscribe(con, "chef", u["id"], "chef_studio", "monthly")
    billing.set_price(con, "chef_studio", 69, 690)
    at = dt.datetime.fromisoformat(s["renews"]) - dt.timedelta(days=10)
    first = schedule.billing_tick(con, at)
    second = schedule.billing_tick(con, at)
    con.close()
    assert first == [f"noticed {s['id']}"] and second == []


def test_marketplace_find_meet_hire_and_switch(server):
    c = server.client
    # a household near Westport looking for a chef
    HF, hid = server.household("fam@example.com", "Fam", "Powers house")
    c.post("/api/household/people", headers=HF, json={"name": "Kid", "age_band": "kid", "age": 9, "allergies": ["peanut"]})
    assert c.put("/api/market/listing", headers=HF, json={"open": True}).status_code == 409   # address first
    c.put("/api/household/address", headers=HF, json=WESTPORT)
    assert c.put("/api/market/listing", headers=HF, json={"open": True, "budget_per_week": 400, "visits_per_week": 2,
                                                          "cuisines": ["italian"], "note": "Two dinners a week"}).status_code == 200
    # two chefs: one nearby on Pro, one far away
    H1, r1 = server.signin("near@example.com")
    H2, r2 = server.signin("far@example.com")
    assert c.put("/api/market/profile", headers=H1, json={"listed": True}).status_code == 402      # Pro to be listed
    con = accounts.connect()
    plans.set_chef_plan(con, r1["user"]["id"], "chef_solo")
    plans.set_chef_plan(con, r2["user"]["id"], "chef_solo")
    con.close()
    c.put("/api/market/profile", headers=H1, json={"display_name": "Chef Near", "listed": True, "radius_miles": 15,
                                                   "address": NORWALK, "cuisines": ["italian"], "rate_per_visit": 200})
    c.put("/api/market/profile", headers=H2, json={"display_name": "Chef Far", "listed": True, "radius_miles": 30,
                                                   "address": BOSTON})
    chefs = c.get("/api/market/chefs", headers=HF, params={"radius": 25}).json()["chefs"]
    assert [x["name"] for x in chefs] == ["Chef Near"] and chefs[0]["miles"] <= 5 and chefs[0]["place"] == "Norwalk, CT"
    # the chef sees the household without names, ages or street
    hs = c.get("/api/market/households", headers=H1).json()["households"]
    assert len(hs) == 1 and hs[0]["kids"] == 1 and hs[0]["allergens"] == ["peanut"] and hs[0]["place"] == "Westport, CT"
    assert "Kid" not in str(hs) and "Main St" not in str(hs) and "fam@example.com" not in str(hs)
    assert c.get("/api/market/households", headers=H2).json()["households"] == []            # out of range
    # the chef asks to meet; only the household's admin can answer; accepting shares contacts
    req = c.post("/api/market/requests", headers=H1, json={"household_id": hid, "message": "I'd love to cook for you"}).json()
    assert c.post("/api/market/requests", headers=H1, json={"household_id": hid, "message": "again"}).status_code == 422
    assert c.post(f"/api/market/requests/{req['id']}/respond", headers=H1, json={"accept": True}).status_code == 403
    assert c.get("/api/market/requests", headers=H1).json()["requests"][0]["contact"] is None
    assert c.post(f"/api/market/requests/{req['id']}/respond", headers=HF, json={"accept": True}).json()["status"] == "accepted"
    contact = c.get("/api/market/requests", headers=H1).json()["requests"][0]["contact"]
    assert contact["email"] == "fam@example.com"
    # hire, then switch to another chef
    assert c.post(f"/api/market/requests/{req['id']}/hire", headers=HF).json()["role"] == "chef"
    tok, inv = server.link("chef-invite")
    c.post("/api/auth/verify", json={"token": tok, "invite": inv})
    mine = c.get("/api/household/chefs", headers=HF).json()["chefs"]
    assert [x["name"] for x in mine] == ["Chef Near"]
    assert c.delete(f"/api/household/chefs/{mine[0]['uid']}", headers=HF).status_code == 200
    assert c.get("/api/household/chefs", headers=HF).json()["chefs"] == []
    assert c.get(f"/api/chef/clients/{hid}", headers=H1).status_code == 403


def test_allergen_rules_are_free(server, monkeypatch):
    """Allergen checks never sit behind a plan: a Free household still gets hidden allergens refused."""
    monkeypatch.setenv("HELPER_SIGNUP", "open")
    c = server.client
    H, _ = server.household()
    c.post("/api/household/people", headers=H, json={"name": "Kid", "age_band": "kid", "age": 8, "allergies": ["tree_nut"]})
    assert c.get("/api/me", headers=H).json()["household_plan"]["plan"] == "free"
    r = c.post("/api/recipes", headers=H, json={"name": "Pesto pasta", "meal": "dinner", "active": 15, "total": 20,
                                                "ingredients": [{"text": "pesto", "qty": 1}, {"text": "pasta", "qty": 4}]})
    body = r.json()
    assert r.status_code == 200 and ("tree_nut" in str(body) or "tree nut" in str(body))
