"""Location privacy, the Household Food Passport and engagements: who may see a household's street address, gate
code and food passport (SEC-03, SEC-04, DATA-03)."""
import json

import pytest

from lilhelper import accounts, geo, passport, plans

HOME = {"line1": "12 Orchard Lane", "city": "Westport", "state": "CT", "zip": "06880", "lat": 41.14153, "lon": -73.35791,
        "gate_code": "4417#", "access_notes": "Side door, dog is friendly"}
NEAR = {"city": "Norwalk", "state": "CT", "zip": "06851", "lat": 41.1177, "lon": -73.4082}
SECRETS = ("12 Orchard Lane", "Orchard", "4417#", "Side door", "41.14153", "-73.35791", "41.1415", "-73.3579")


# ---------------------------------------------------------------- generate_fuzzy_coordinates
def test_fuzzy_coordinates_are_stable_bounded_and_not_the_home():
    lat, lng = HOME["lat"], HOME["lon"]
    a = passport.generate_fuzzy_coordinates(lat, lng, "house-a")
    assert a == passport.generate_fuzzy_coordinates(lat, lng, "house-a")          # same answer every time
    d = geo.miles((lat, lng), a) * 1609.34
    assert 100 <= d <= 2000, d                                                     # never the house, never far off
    assert a != passport.generate_fuzzy_coordinates(lat, lng, "house-b")           # per household
    # moving a few doors down (same ~1 km cell) changes nothing public
    assert passport.generate_fuzzy_coordinates(lat + 0.0004, lng + 0.0004, "house-a") == a
    assert all(len(str(x).split(".")[1]) <= 3 for x in a)                          # ~100 m precision at most
    with pytest.raises(ValueError):
        passport.generate_fuzzy_coordinates(91, 0, "x")


def test_fuzzy_spread_has_no_bias_toward_the_home():
    lat, lng = HOME["lat"], HOME["lon"]
    pts = [passport.generate_fuzzy_coordinates(lat, lng, f"h{i}") for i in range(400)]
    mlat = sum(p[0] for p in pts) / len(pts)
    mlng = sum(p[1] for p in pts) / len(pts)
    # averaging many households' points lands on the grid cell's centre, not on any one house
    centre = ((int(lat / 0.01) + 0.5) * 0.01, (int(lng / 0.01) - 0.5) * 0.01)
    assert geo.miles((mlat, mlng), centre) < 0.15


# ---------------------------------------------------------------- PassportAccessService over the API
@pytest.fixture()
def world(server):
    """A family with an address and gate code, listed as looking; three Pro chefs; one other family."""
    c = server.client
    HF, hid = server.household("fam@example.com", "Fam", "Powers house")
    c.post("/api/household/people", headers=HF, json={"name": "Ava Powers", "age_band": "kid", "age": 9,
                                                       "allergies": ["tree_nut"]})
    assert c.put("/api/household/address", headers=HF, json=HOME).status_code == 200
    c.put("/api/market/listing", headers=HF, json={"open": True, "budget_per_week": 300})
    chefs = {}
    con = accounts.connect()
    for name in ("hired", "talking", "stranger"):
        H, r = server.signin(f"{name}@example.com")
        plans.set_chef_plan(con, r["user"]["id"], "chef_solo")
        chefs[name] = (H, r["user"]["id"])
    con.close()
    for name, (H, _) in chefs.items():
        c.put("/api/market/profile", headers=H, json={"display_name": name, "listed": True, "address": NEAR})
    HO, other = server.household("other@example.com", "Other", "Other house")
    Hn, _ = server.signin("nobody@example.com")
    return {"c": c, "HF": HF, "hid": hid, "chefs": chefs, "HO": HO, "other": other, "nobody": Hn}


def _leaks(payload) -> list[str]:
    s = json.dumps(payload)
    return [x for x in SECRETS if x in s]


def test_unauthorized_accounts_cannot_read_the_private_address(world):
    c, hid = world["c"], world["hid"]
    H, uid = world["chefs"]["stranger"]
    # a Pro chef with no engagement: public card only, and the location endpoint refuses
    v = c.get(f"/api/passport/{hid}", headers=H).json()
    assert v["location"] is None and v["passport"] is None and v["access"] == {"passport": False, "address": False}
    assert v["public"]["city"] == "Westport" and not _leaks(v)
    assert c.get(f"/api/passport/{hid}/location", headers=H).status_code == 403
    # another household's admin
    assert c.get(f"/api/passport/{hid}/location", headers=world["HO"]).status_code == 403
    assert not _leaks(c.get(f"/api/passport/{hid}", headers=world["HO"]).json())
    # a signed-in account with no household and no plan
    Hn = world["nobody"]
    assert c.get(f"/api/passport/{hid}/location", headers=Hn).status_code == 403
    assert not _leaks(c.get(f"/api/passport/{hid}", headers=Hn).json())
    # marketplace search results and request views never carry the street, gate code or exact point
    hs = c.get("/api/market/households", headers=H).json()["households"]
    assert hs and not _leaks(hs) and hs[0]["miles"] >= 1
    # the family's settings aren't reachable for a chef who isn't a member
    assert c.get("/api/household/settings", headers=H).status_code in (401, 403, 409)


def test_inquiry_and_grant_share_the_passport_but_never_the_address(world):
    c, hid, HF = world["c"], world["hid"], world["HF"]
    H, uid = world["chefs"]["talking"]
    req = c.post("/api/market/requests", headers=H, json={"household_id": hid, "message": "Hello"}).json()
    c.post(f"/api/market/requests/{req['id']}/respond", headers=HF, json={"accept": True})
    v = c.get(f"/api/passport/{hid}", headers=H).json()
    assert v["engagement"]["status"] == "inquiry" and v["passport"] is None and v["location"] is None
    assert c.post("/api/household/passport/grants", headers=HF, json={"chef_uid": uid}).status_code == 200
    v = c.get(f"/api/passport/{hid}", headers=H).json()
    assert v["passport"]["allergens"] == ["tree_nut"] and v["passport"]["people"][1]["first_name"] == "Ava"
    assert v["location"] is None and not _leaks(v)
    assert c.get(f"/api/passport/{hid}/location", headers=H).status_code == 403
    c.delete(f"/api/household/passport/grants/{uid}", headers=HF)
    assert c.get(f"/api/passport/{hid}", headers=H).json()["passport"] is None


def test_address_only_while_trial_scheduled_or_active(world):
    c, hid, HF = world["c"], world["hid"], world["HF"]
    H, uid = world["chefs"]["hired"]
    req = c.post("/api/market/requests", headers=H, json={"household_id": hid, "message": "Hi"}).json()
    c.post(f"/api/market/requests/{req['id']}/respond", headers=HF, json={"accept": True})
    eid = c.get(f"/api/passport/{hid}", headers=H).json()["engagement"]["id"]
    # the chef can propose a trial but can't make themselves active
    assert c.put(f"/api/engagements/{eid}", headers=H, json={"status": "active"}).status_code == 403
    assert c.put(f"/api/engagements/{eid}", headers=H, json={"status": "trial_scheduled"}).status_code == 409   # needs a time
    r = c.put(f"/api/engagements/{eid}", headers=HF, json={"status": "trial_scheduled", "trial_at": "2026-11-03T16:00"})
    assert r.status_code == 200
    loc = c.get(f"/api/passport/{hid}/location", headers=H).json()
    assert loc["street"] == "12 Orchard Lane" and loc["gate_code"] == "4417#"
    # hire → active (the chef gets an invitation); pause hides it again; end removes the chef
    r = c.put(f"/api/engagements/{eid}", headers=HF, json={"status": "active"}).json()
    assert r["status"] == "active" and r["invited"] == "hired@example.com"
    assert c.get(f"/api/passport/{hid}/location", headers=H).status_code == 200
    c.put(f"/api/engagements/{eid}", headers=HF, json={"status": "paused"})
    assert c.get(f"/api/passport/{hid}/location", headers=H).status_code == 403
    assert c.get(f"/api/passport/{hid}", headers=H).json()["location"] is None
    c.put(f"/api/engagements/{eid}", headers=HF, json={"status": "active"})
    c.put(f"/api/engagements/{eid}", headers=HF, json={"status": "ended"})
    assert c.get(f"/api/passport/{hid}/location", headers=H).status_code == 403
    assert c.put(f"/api/engagements/{eid}", headers=HF, json={"status": "active"}).status_code == 409   # ended is final
    # the family sees who read what
    log = c.get("/api/household/passport", headers=HF).json()["access_log"]
    assert any(x["viewer"] == uid and "address" in x["parts"] for x in log)


def test_a_paused_member_chef_loses_the_address_in_settings_too(world, server):
    c, hid, HF = world["c"], world["hid"], world["HF"]
    c.post("/api/household/chef-invite", headers=HF, json={"email": "hired@example.com"})
    tok, inv = server.link("chef-invite")
    r = c.post("/api/auth/verify", json={"token": tok, "invite": inv}).json()
    HC = {"Authorization": f"Bearer {r['session']}"}
    assert c.get("/api/household/settings", headers=HC).json()["settings"]["address"]["line1"] == "12 Orchard Lane"
    con = accounts.connect()
    e = passport.engagement(con, world["chefs"]["hired"][1], hid)
    assert e.status == "active"                                 # accepting the family's invitation = active
    passport.move(con, e.id, "paused")
    con.close()
    s = c.get("/api/household/settings", headers=HC).json()["settings"]
    assert "address" not in s and "access" not in s


def test_the_family_sees_everything_and_can_export_the_passport(world):
    c, HF = world["c"], world["HF"]
    mine = c.get("/api/household/passport", headers=HF).json()
    assert mine["location"]["gate_code"] == "4417#"
    ex = c.get("/api/household/passport/export", headers=HF)
    body = ex.json()
    assert body["format"] == "dinnerpeace-food-passport/1" and body["allergens"] == ["tree_nut"]
    assert not [x for x in ("12 Orchard Lane", "4417#") if x in ex.text]       # portable, but no address in it


def test_engagement_rules():
    from lilhelper.passport import TRANSITIONS
    assert "active" not in TRANSITIONS["ended"] and "active" in TRANSITIONS["paused"]
