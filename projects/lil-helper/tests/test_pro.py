"""Dinner Peace Pro: plans, the chef role, the cockpit, containers, reheat cards, voice notes, the trip across homes,
the ledger and invoices, coverage packs, and billing (SEC-04, HITL-02, DATA-03, EVAL-02)."""
import datetime as dt

import pytest

from lilhelper import accounts, plans, pro
from lilhelper.config import DAYS


def _chef(server, email="chef@example.com", plan="chef_solo"):
    H, r = server.signin(email)
    con = accounts.connect()
    plans.set_chef_plan(con, r["user"]["id"], plan)
    con.close()
    return H, r["user"]["id"]


def _client(server, H, family="Miller family", contact="Jordan", email=None):
    r = server.client.post("/api/chef/clients", headers=H, json={"family_name": family, "contact_name": contact,
                                                                  "contact_email": email, "invite": bool(email)})
    assert r.status_code == 200, r.text
    return r.json()["household_id"]


def _people(hid, people):
    from lilhelper.config import load_household, save_household, tenant
    with tenant(hid):
        raw = load_household().raw
        raw["people"].update(people)
        save_household(raw)


def test_no_plan_sees_the_paywall_and_solo_is_capped(server):
    c = server.client
    H, uid = _chef(server, plan="none")
    r = c.get("/api/chef/cockpit", headers=H)
    assert r.status_code == 402 and r.json()["detail"]["upgrade"] == "chef_solo"
    assert c.post("/api/chef/clients", headers=H, json={"family_name": "A", "contact_name": "A"}).status_code == 402
    con = accounts.connect()
    plans.set_chef_plan(con, uid, "chef_solo")
    con.close()
    for n in range(3):
        _client(server, H, f"Family {n}")
    r = c.post("/api/chef/clients", headers=H, json={"family_name": "Fourth", "contact_name": "D"})
    assert r.status_code == 402 and r.json()["detail"]["upgrade"] == "chef_studio"          # k02
    assert c.get("/api/chef/cockpit", headers=H).status_code == 200
    # Studio-only features are refused on Solo
    assert c.post("/api/chef/trips", headers=H, json={}).status_code == 402
    assert c.post("/api/chef/coverage", headers=H, json={"sub_name": "S", "sub_email": "s@example.com",
                                                         "start": "2026-10-01", "end": "2026-10-02",
                                                         "households": [], "password": "longenough"}).status_code == 402
    assert c.put("/api/chef/settings", headers=H, json={"business": "My Kitchen"}).status_code == 402
    plans_view = c.get("/api/plans", headers=H).json()
    assert plans_view["chef_plan"] == "chef_solo" and plans_view["clients"] == 3 and plans_view["client_limit"] == 3
    assert plans_view["tiers"]["chef_studio"]["monthly"] == 59.0


def test_a_chef_sees_only_their_own_clients(server):
    c = server.client
    H1, _ = _chef(server, "one@example.com")
    H2, _ = _chef(server, "two@example.com")
    h1 = _client(server, H1, "Miller family")
    Hf, hf = server.household("fam@example.com", "Fam", "Not a client")
    for H, hid in ((H2, h1), (H1, hf), (H2, hf)):                                          # k01
        assert c.get(f"/api/chef/clients/{hid}", headers=H).status_code == 403
        assert c.post(f"/api/chef/clients/{hid}/containers", headers=H,
                      json={"dish": "x", "portions": 1}).status_code == 403
        assert c.post("/api/chef/voice", headers=H, json={"text": "made 2 portions of soup",
                                                         "household_id": hid}).status_code == 403
    assert c.get(f"/api/chef/clients/{h1}", headers=H1).status_code == 200
    names = [k["name"] for k in c.get("/api/chef", headers=H2).json()["clients"]]
    assert names == []


def test_chef_holds_the_household_until_the_family_joins(server):
    c = server.client
    H, uid = _chef(server)
    hid = _client(server, H, "Henderson family", "Priya", "priya@example.com")
    # before the family joins, the chef can set it up (add people, allergies)
    sess = c.post("/api/session/household", headers=H, json={"household_id": hid}).json()
    HC = {"Authorization": f"Bearer {sess['session']}"}
    assert c.post("/api/household/people", headers=HC, json={"name": "Mia", "age_band": "kid", "age": 9,
                                                             "allergies": ["dairy"]}).status_code == 200
    # the family's admin accepts the invitation; now settings are theirs
    HF, r = server.signin("priya@example.com", invite_tag="invite")
    assert r["household"] == hid
    assert c.get("/api/household/settings", headers=HF).json()["role"] == "admin"
    assert c.post("/api/household/people", headers=HC, json={"name": "Tom"}).status_code == 403
    assert c.post("/api/week/draft", headers=HC, json={"week": "2026-10-19"}).status_code == 200   # chef plans


def test_a_pro_chef_gives_the_family_the_family_plan(server, monkeypatch):
    monkeypatch.setenv("HELPER_SIGNUP", "open")
    c = server.client
    Hf, hid = server.household("fam@example.com", "Fam", "Family on free")
    assert c.post("/api/cookfrom", headers=Hf, json={"text": "chicken, rice"}).status_code == 402
    assert c.get("/api/me", headers=Hf).json()["household_plan"]["plan"] == "free"
    c.post("/api/household/chef-invite", headers=Hf, json={"email": "chef@example.com"})
    Hc, uid = _chef(server, plan="chef_solo")
    tok, inv = server.link("chef-invite")
    r = c.post("/api/auth/verify", json={"token": tok, "invite": inv}).json()
    assert r["household"] == hid
    me = c.get("/api/me", headers=Hf).json()["household_plan"]
    assert me == {"plan": "family", "own": "free", "via_chef": True}
    assert c.post("/api/cookfrom", headers=Hf, json={"text": "chicken, rice"}).status_code == 200
    # the chef's plan lapses → the family is back on free; nothing is deleted
    con = accounts.connect()
    plans.set_chef_plan(con, uid, "chef_solo", "2020-01-01T00:00:00+00:00")
    con.close()
    assert c.post("/api/cookfrom", headers=Hf, json={"text": "chicken, rice"}).status_code == 402


def test_containers_number_themselves_and_the_family_sees_them(server):
    c = server.client
    H, _ = _chef(server)
    hid = _client(server, H, "Miller family", "Jordan", "jordan@example.com")
    a = c.post(f"/api/chef/clients/{hid}/containers", headers=H, json={"dish": "Short ribs", "portions": 2}).json()
    b = c.post(f"/api/chef/clients/{hid}/containers", headers=H,
               json={"dish": "Short ribs", "portions": 2, "location": "freezer"}).json()
    assert (a["number"], b["number"]) == (1, 2)
    assert b["use_by"] == (dt.date.today() + dt.timedelta(days=60)).isoformat()
    assert c.post(f"/api/chef/clients/{hid}/containers", headers=H,
                  json={"dish": "Soup", "portions": 1, "number": 1}).status_code == 422
    HF, _ = server.signin("jordan@example.com", invite_tag="invite")
    fridge = c.get("/api/household/fridge", headers=HF).json()
    assert [x["number"] for x in fridge["containers"]] == [1, 2] and fridge["chefs"]
    assert c.post(f"/api/household/fridge/{a['id']}", headers=HF, json={"status": "eaten"}).status_code == 200
    # #1 is free again
    nxt = c.post(f"/api/chef/clients/{hid}/containers", headers=H, json={"dish": "Soup", "portions": 1}).json()
    assert nxt["number"] == 1


def test_a_reheat_card_naming_an_allergen_is_refused_until_confirmed(server):
    c = server.client
    H, _ = _chef(server)
    hid = _client(server, H)
    _people(hid, {"ava": {"name": "Ava", "age_band": "kid", "age": 9, "allergies": ["tree_nut"]}})
    card = {"meal": "Almond-crusted chicken", "method": "oven", "temp_f": 375, "minutes": 20}
    r = c.post(f"/api/chef/clients/{hid}/reheat", headers=H, json=card)                     # k04
    assert r.status_code == 409 and "tree nut" in r.json()["detail"]
    assert c.get(f"/api/chef/clients/{hid}", headers=H).json()["cards"] == []
    ok = c.post(f"/api/chef/clients/{hid}/reheat", headers=H, json={**card, "confirm": True}).json()
    assert ok["contains"] == ["tree_nut"] and ok["steps"][0].startswith("Heat the oven to 375")
    r = c.post(f"/api/chef/clients/{hid}/reheat", headers=H, json={"meal": "Chili", "method": "oven", "minutes": 20})
    assert r.status_code == 422                                                            # an oven needs a temperature
    pdf = c.get(f"/api/chef/clients/{hid}/reheat.pdf", headers=H, params={"size": "4x6"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    link = c.post(f"/api/chef/clients/{hid}/reheat/link", headers=H, params={"size": "letter"}).json()["url"]
    got = c.get("/" + link.split("/", 3)[3])
    assert got.status_code == 200 and got.content[:4] == b"%PDF"
    assert c.get("/pro/reheat/forged.pdf").status_code == 401
    assert c.post(f"/api/chef/clients/{hid}/reheat/email", headers=H).status_code == 409    # nobody has an email yet


def test_the_spec_voice_note_becomes_fridge_card_and_list(server):
    c = server.client
    H, _ = _chef(server)
    hid = _client(server, H, "Miller family")
    _client(server, H, "Henderson family")
    c.post(f"/api/chef/clients/{hid}/containers", headers=H, json={"dish": "Lasagna", "portions": 3})
    text = ("At the Millers. Chucked the leftover lasagna from Tuesday, made 4 portions of braised short ribs. "
            "Freeze two, fridge two. Reheat at 350 for 25 minutes covered. They're out of olive oil.")
    p = c.post("/api/chef/voice", headers=H, json={"text": text}).json()
    assert p["household"] == hid and p["household_name"] == "Miller family"
    kinds = [a["kind"] for a in p["actions"]]
    assert kinds == ["toss", "made", "reheat", "shop"] and p["actions"][0]["match"] == "#1 Lasagna"
    # nothing is saved by the preview
    assert len(c.get(f"/api/chef/clients/{hid}", headers=H).json()["containers"]) == 1
    done = c.post("/api/chef/voice/apply", headers=H, json={"household_id": hid, "actions": p["actions"]}).json()
    assert done["tossed"] == ["#1 Lasagna"] and len(done["containers"]) == 2 and len(done["cards"]) == 1
    assert done["cards"][0]["temp_f"] == 350 and done["cards"][0]["covered"] is True
    assert done["shopping"][0]["ingredient"] == "olive_oil"
    detail = c.get(f"/api/chef/clients/{hid}", headers=H).json()
    assert sorted((b["location"], b["portions"]) for b in detail["containers"]) == [("freezer", 2.0), ("fridge", 2.0)]


def test_bulk_lines_split_to_the_cent_and_client_cards_check_out_alone(server):
    H, uid = _chef(server, plan="chef_studio")
    db = pro.chef_db(uid)
    pro.put_setting(db, "stores", ["costco"])
    pro.put_setting(db, "cards", ["costco_anywhere_visa"])
    db.close()
    homes = [{"household_id": "aaaaaa1", "name": "A", "need": {"ground_beef": {"qty": 2.4, "brand": None, "for": []},
                                                              "rice": {"qty": 1.3, "brand": None, "for": []}}},
             {"household_id": "bbbbbb2", "name": "B", "need": {"ground_beef": {"qty": 1.6, "brand": None, "for": []}}},
             {"household_id": "cccccc3", "name": "C", "need": {"ground_beef": {"qty": 1.0, "brand": None, "for": []}}}]
    billing = {"aaaaaa1": "chef_card_reimburse", "bbbbbb2": "chef_card_reimburse", "cccccc3": "client_card_on_file"}
    trip = pro.build_trip(uid, homes, billing, dt.date(2026, 10, 19))
    chef_co = next(co for s in trip["stops"] for co in s["checkouts"] if co["paid_by"] == "chef")
    beef = next(ln for ln in chef_co["lines"] if ln["ingredient"] == "ground_beef")
    assert beef["bulk"] and [s["pct"] for s in beef["shares"]] == [60, 40]                 # k03
    assert round(sum(s["cost"] for s in beef["shares"]), 2) == beef["cost"]
    assert chef_co["card"] == "costco_anywhere_visa" and chef_co["rewards"] > 0
    own = [co for s in trip["stops"] for co in s["checkouts"] if co["paid_by"] == "client"]
    assert len(own) == 1 and own[0]["household_id"] == "cccccc3" and own[0]["per_home"][0]["name"] == "C"
    assert round(sum(h["amount"] for h in trip["homes"]), 2) == trip["total"]
    for total, w in [(31.99, [2.4, 1.6]), (0.05, [1, 1, 1]), (100, [1, 2, 3, 4])]:
        assert round(sum(pro.split_cents(total, w)), 2) == total


def test_trip_ledger_invoice_flow(server):
    c = server.client
    H, uid = _chef(server, plan="chef_studio")
    hid = _client(server, H, "Miller family", "Jordan", "jordan@example.com")
    today = dt.date.today()
    c.put(f"/api/chef/clients/{hid}", headers=H, json={"visits": [{"day": DAYS[today.weekday()], "arrive": "09:00",
                                                                   "leave": "12:00", "covers": DAYS}]})
    sess = c.post("/api/session/household", headers=H, json={"household_id": hid}).json()
    HC = {"Authorization": f"Bearer {sess['session']}"}
    assert c.post("/api/week/draft", headers=HC, json={"week": today.isoformat()}).status_code == 200
    ck = c.get("/api/chef/cockpit", headers=H, params={"clock": "08:00"}).json()
    assert ck["homes_today"] == 1 and ck["now"]["name"] == "Miller family" and ck["now"]["next"].startswith("Cook ")
    trip = c.post("/api/chef/trips", headers=H, json={"days": 2}).json()
    st = trip["stops"][0]
    r = c.post(f"/api/chef/trips/{trip['id']}/paid", headers=H, json={"store": st["store"], "actual": 50.0})
    assert r.status_code == 200 and r.json()["ledger"][0]["amount"] == 50.0
    assert c.post(f"/api/chef/trips/{trip['id']}/paid", headers=H, json={"store": st["store"]}).status_code == 422
    c.post("/api/chef/ledger", headers=H, json={"household_id": hid, "store": "Farm stand", "amount": 12.5})
    assert c.post("/api/chef/ledger", headers=H, json={"household_id": hid, "store": "x", "amount": 1,
                                                       "card": "4111 1111 1111 1111"}).status_code == 422
    led = c.get("/api/chef/ledger", headers=H).json()
    assert led["totals"]["pending"] == 62.5
    inv = c.post("/api/chef/invoices", headers=H, json={"household_id": hid}).json()
    assert inv["total"] == 62.5 and len(inv["lines"]) == 2
    assert c.post("/api/chef/invoices", headers=H, json={"household_id": hid}).status_code == 409
    assert c.post(f"/api/chef/invoices/{inv['id']}/paid", headers=H).status_code == 200
    assert {r["status"] for r in c.get("/api/chef/ledger", headers=H).json()["rows"]} == {"cleared"}


def test_coverage_pack_needs_the_password_and_expires(server):
    c = server.client
    H, uid = _chef(server, plan="chef_studio")
    hid = _client(server, H)
    _people(hid, {"ava": {"name": "Ava", "age_band": "kid", "age": 9, "allergies": ["tree_nut"]}})
    c.put(f"/api/chef/clients/{hid}", headers=H, json={"gate_code": "4417#", "address": "12 Orchard Lane"})
    today = dt.date.today()
    body = {"sub_name": "Sarah Jenkins", "sub_email": "sarah@example.com", "start": today.isoformat(),
            "end": (today + dt.timedelta(days=2)).isoformat(), "households": [hid], "password": "short"}
    assert c.post("/api/chef/coverage", headers=H, json=body).status_code == 422
    pack = c.post("/api/chef/coverage", headers=H, json={**body, "password": "basil-and-thyme"}).json()
    path = pack["url"].split("8650", 1)[-1] if "8650" in pack["url"] else "/" + pack["url"].split("/", 3)[3]
    assert c.post(path, data={"password": "wrong-password"}).status_code == 403                 # k05
    ok = c.post(path, data={"password": "basil-and-thyme"})
    assert ok.status_code == 200 and "tree nut allergy" in ok.text and "4417#" not in ok.text   # view level: no codes
    full = c.post("/api/chef/coverage", headers=H, json={**body, "password": "basil-and-thyme",
                                                         "level": "full_operational"}).json()
    p2 = "/" + full["url"].split("/", 3)[3]
    assert "4417#" in c.post(p2, data={"password": "basil-and-thyme"}).text
    # expired, and revoked
    db = pro.chef_db(uid)
    db.execute('UPDATE coverage SET "end" = ? WHERE id = ?', ((today - dt.timedelta(days=1)).isoformat(), pack["id"]))
    db.commit()
    db.close()
    assert c.post(path, data={"password": "basil-and-thyme"}).status_code == 403
    c.delete(f"/api/chef/coverage/{full['id']}", headers=H)
    assert c.post(p2, data={"password": "basil-and-thyme"}).status_code == 403


def test_revenuecat_webhook_sets_and_ends_plans(server, monkeypatch):
    c = server.client
    H, r = server.signin("chef@example.com")
    uid = r["user"]["id"]
    ev = {"event": {"type": "INITIAL_PURCHASE", "app_user_id": uid, "entitlement_ids": ["chef_studio"],
                    "expiration_at_ms": int((dt.datetime.now() + dt.timedelta(days=30)).timestamp() * 1000)}}
    assert c.post("/api/billing/revenuecat", json=ev).status_code == 503                    # not set up
    monkeypatch.setenv("REVENUECAT_WEBHOOK_AUTH", "Bearer whsec-test")
    assert c.post("/api/billing/revenuecat", json=ev, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/api/billing/revenuecat", json=ev, headers={"Authorization": "Bearer whsec-test"}).json()["applied"]
    assert c.get("/api/plans", headers=H).json()["chef_plan"] == "chef_studio"
    ev["event"]["type"] = "EXPIRATION"
    c.post("/api/billing/revenuecat", json=ev, headers={"Authorization": "Bearer whsec-test"})
    assert c.get("/api/plans", headers=H).json()["chef_plan"] == "none"


def test_client_records_refuse_card_numbers(server):
    H, _ = _chef(server)
    hid = _client(server, H)
    r = server.client.put(f"/api/chef/clients/{hid}", headers=H, json={"client_card": "4111 1111 1111 1111"})
    assert r.status_code == 422
    r = server.client.put(f"/api/chef/clients/{hid}", headers=H, json={"billing": "client_card_on_file",
                                                                        "client_card": "Davis Amex"})
    assert r.status_code == 200 and r.json()["billing"] == "client_card_on_file"


def test_chef_demo_seeds_a_studio_chef(server):
    from lilhelper import chefdemo
    out = chefdemo.seed("demo-chef@example.com")
    assert len(out["clients"]) == 3
    H, _ = server.signin("demo-chef@example.com")
    ck = server.client.get("/api/chef/cockpit", headers=H, params={"clock": "08:00"}).json()
    assert ck["studio"] and ck["homes_today"] == 2 and ck["kitchens"][0]["hazard"]
    shop = server.client.get("/api/chef/shopping", headers=H).json()
    assert shop["trip"]["stops"] and shop["per_home"]
