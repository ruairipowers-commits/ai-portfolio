"""v3: change a meal and undo it, day states and outcomes, freezer edits and use-by-first planning, cook-from."""
import datetime as dt

from lilhelper import store, week
from lilhelper.config import tenant

W = "2026-10-19"


def _dinner(w, day):
    return next(e for e in w["plan"]["entries"] if e["day"] == day and e["meal"] == "dinner")


def test_change_a_meal_and_undo_on_draft_and_approved(server):
    c = server.client
    H, _ = server.household()
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    before = _dinner(w, "tue")["recipe"]
    to = "chicken_broccoli_rice" if before != "chicken_broccoli_rice" else "chicken_tacos"
    w = c.post("/api/week/change", headers=H, json={"week": W, "day": "tue", "recipe": to}).json()
    assert _dinner(w, "tue")["recipe"] == to and _dinner(w, "tue")["original"]["recipe"] == before
    # a re-plan (Friday becomes takeout) keeps the person's pick
    w = c.post("/api/week/night", headers=H, json={"week": W, "day": "fri", "kind": "takeout"}).json()
    assert _dinner(w, "tue")["recipe"] == to
    w = c.post("/api/week/revert", headers=H, json={"week": W, "day": "tue"}).json()
    assert _dinner(w, "tue")["recipe"] == before and _dinner(w, "tue")["original"] is None
    assert c.post("/api/week/revert", headers=H, json={"week": W, "day": "tue"}).status_code == 409
    # approved: in place, shopping untouched, says what's missing; undo works too
    a = c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5}).json()
    total = a["options"][a["choice"]]["total"]
    w = c.post("/api/week/change", headers=H, json={"week": W, "day": "wed", "recipe": "fish_tacos"}).json()
    assert _dinner(w, "wed")["recipe"] == "fish_tacos" and w["options"][w["choice"]]["total"] == total
    assert isinstance(w["missing"], list)
    w = c.post("/api/week/revert", headers=H, json={"week": W, "day": "wed"}).json()
    assert _dinner(w, "wed")["recipe"] == _dinner(a, "wed")["recipe"]


def test_changes_respect_allergies(server):
    c = server.client
    H, _ = server.household()
    c.post("/api/household/people", headers=H, json={"name": "Son", "age_band": "kid", "age": 11, "allergies": ["peanut"]})
    c.post("/api/week/draft", headers=H, json={"week": W})
    r = c.post("/api/week/change", headers=H, json={"week": W, "day": "tue", "recipe": "chicken_satay"})
    assert r.status_code == 409 and "peanut" in r.json()["detail"]


def test_states_follow_the_days_and_outcomes_set_freezer_portions(server, monkeypatch):
    c = server.client
    H, hid = server.household()
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    from lilhelper import api
    monkeypatch.setattr(api.week, "today_in", lambda h: dt.date(2026, 10, 21))  # Wednesday (the module the API uses)
    w = c.get("/api/week", headers=H, params={"week": W}).json()
    assert _dinner(w, "mon")["state"] == "to_confirm" and _dinner(w, "wed")["state"] == "today"
    assert _dinner(w, "fri")["state"] == "planned"
    w = c.post("/api/week/outcome", headers=H, json={"week": W, "day": "mon", "outcome": "freezer", "frozen": 3}).json()
    assert _dinner(w, "mon")["state"] == "freezer" and _dinner(w, "mon")["frozen"] == 3
    items = c.get("/api/storage", headers=H).json()["freezer_meals"]
    assert any(m["portions"] == 3 and m["frozen_on"] == "2026-10-19" for m in items)
    # changed my mind: none went in after all
    c.post("/api/week/outcome", headers=H, json={"week": W, "day": "mon", "outcome": "finished"})
    assert not any(m["frozen_on"] == "2026-10-19" for m in c.get("/api/storage", headers=H).json()["freezer_meals"])
    assert c.post("/api/week/outcome", headers=H, json={"week": W, "day": "mon", "outcome": "eaten by dog"}).status_code == 422


def test_freezer_items_edit_and_use_by_first(server):
    c = server.client
    H, hid = server.household()
    c.post("/api/storage/freezer", headers=H, json={"name": "Chili", "portions": 4})
    f = c.get("/api/storage", headers=H).json()["freezer_meals"][0]
    assert c.put(f"/api/storage/freezer/{f['id']}", headers=H,
                 json={"name": "Beef chili", "portions": 5, "use_by": "2026-10-22"}).status_code == 200
    f = c.get("/api/storage", headers=H).json()["freezer_meals"][0]
    assert (f["name"], f["portions"], f["use_by"]) == ("Beef chili", 5, "2026-10-22")
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    fz = [e for e in w["plan"]["entries"] if e.get("kind") == "freezer"]
    assert fz and "Beef chili" in fz[0]["name"]
    assert any("before its use-by" in f for f in w["plan"]["flags"])
    assert c.delete(f"/api/storage/freezer/{f['id']}", headers=H).status_code == 200
    assert c.get("/api/storage", headers=H).json()["freezer_meals"] == []


def test_cook_from_what_ive_got_uses_what_you_typed(server):
    c = server.client
    H, _ = server.household()
    r = c.post("/api/cookfrom", headers=H, json={"text": "half a chicken, rice, half a bag of broccoli",
                                                 "use_pantry": False}).json()
    assert r["ideas"] and all(i["uses_typed"] for i in r["ideas"])
    assert r["ideas"][0]["uses_typed"] == ["half a chicken", "rice", "half a bag of broccoli"]
    r = c.post("/api/cookfrom", headers=H, json={"text": "chicken, cauliflower, quinoa", "use_pantry": False}).json()
    if not r["uses_everything"]:
        assert r["search"]


def test_recipe_from_a_web_page_keeps_source_and_link():
    from lilhelper import catalog, recipebook
    from lilhelper.config import ROOT
    page = (ROOT / "data" / "recipe_pages" / "example-skillet.html").read_text()
    d = recipebook.draft_from_page(catalog.get(), page, "https://example.com/lemony-orzo")
    assert d["name"] == "Lemony Chicken and Orzo Skillet" and d["credit"] == "Example Kitchen"
    assert d["url"] == "https://example.com/lemony-orzo" and d["instructions"] == []      # the method stays at the source
    assert (d["serves"], d["active"], d["total"]) == (4, 15, 40)
    assert "one_pot" in d["tags"] and d["season_months"] == [3, 4, 5] and d["meal"] == "dinner"
    lines = {ln.get("ingredient"): ln for ln in d["ingredients"]}
    assert lines["chicken_thighs"]["qty"] == 1.5 and lines["chicken_thighs"]["unit"] == "lb"
    assert lines["chicken_broth"]["qty"] == 2.5
    assert not any("salt" in ln["text"] for ln in d["ingredients"])
    assert "orzo" in " ".join(d["unknown"])


def test_fetch_refuses_private_addresses():
    import pytest
    from lilhelper import recipebook
    for url in ("http://127.0.0.1:8650/api/health", "http://localhost/", "file:///etc/passwd", "http://10.0.0.5/",
                "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(recipebook.FetchError):
            recipebook.fetch(url)


def test_export_import_and_share_between_households(server):
    c = server.client
    H1, h1 = server.household("one@example.com", "One", "House one")
    c.post("/api/ingredients", headers=H1, json={"name": "orzo", "unit": "cup", "cat": "pantry"})
    r = c.post("/api/recipes", headers=H1, json={"name": "Orzo with peas", "serves": 4, "credit": "",
               "ingredients": [{"text": "orzo", "qty": 1, "unit": "cup"}, {"text": "frozen peas", "qty": 1, "unit": "cup"}]})
    assert r.status_code == 200, r.text
    mine = c.get("/api/recipes", headers=H1, params={"mine": True}).json()["recipes"]
    assert mine[0]["credit"] == "One"                       # defaults to the person who saved it
    book = c.get("/api/recipes/export", headers=H1).json()
    assert book["format"] == "lilhelper-recipes" and book["ingredients"][0]["name"] == "orzo"
    H2, h2 = server.household("two@example.com", "Two", "House two")
    out = c.post("/api/recipes/import", headers=H2, json={"book": book}).json()
    assert out["added"] == 1 and out["new_ingredients"] == ["orzo"]
    assert c.post("/api/recipes/import", headers=H2, json={"book": book}).json()["skipped_same_name"] == ["Orzo with peas"]
    # sharing by code
    H3, _ = server.household("three@example.com", "Three", "House three")
    share = c.post("/api/recipes/share", headers=H1).json()
    assert c.post("/api/recipes/shared", headers=H3, json={"code": share["code"]}).json()["recipes"] == ["Orzo with peas"]
    got = c.post("/api/recipes/import-shared", headers=H3, json={"code": share["code"]}).json()
    assert got["added"] == 1
    r3 = c.get("/api/recipes", headers=H3, params={"mine": True}).json()["recipes"]
    assert r3[0]["credit"] == "One"                         # the original credit travels with it
    c.delete("/api/recipes/share", headers=H1)
    assert c.post("/api/recipes/shared", headers=H3, json={"code": share["code"]}).status_code == 404
    assert c.post("/api/recipes/import", headers=H2, json={"book": {"format": "nope"}}).status_code == 422


def test_recipe_search_without_a_key_gives_a_search_link(server, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    c = server.client
    H, _ = server.household()
    assert c.patch("/api/household/settings/recipe_sources", headers=H, json={"value": ["marthastewart.com"]}).status_code == 200
    assert c.patch("/api/household/settings/recipe_sources", headers=H, json={"value": ["not a site"]}).status_code == 422
    r = c.get("/api/recipes/search", headers=H, params={"q": "chicken broccoli rice"}).json()
    assert r["results"] == [] and "site%3Amarthastewart.com" in r["search_url"]


def test_calendar_shopping_events_carry_the_whole_list_and_open_the_app(server):
    import re
    c = server.client
    H, _ = server.household()
    c.patch("/api/household/settings/shopping_sessions", headers=H,
            json={"value": [{"day": "sun_before", "time": "10:00", "store": "whole_foods", "mode": "in_store"}]})
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    shop = c.get("/api/week/shopping", headers=H, params={"week": W}).json()["orders"]
    link = c.get("/api/calendar/link", headers=H).json()
    feed = c.get(re.sub(r"^https?://[^/]+", "", link["https"])).text.replace("\r\n ", "")
    shop_event = next(ev for ev in feed.split("BEGIN:VEVENT") if "SUMMARY:🛒" in ev)
    n_lines = shop_event.count("☐")
    assert n_lines == sum(len(o["lines"]) for o in shop if o["store"] == "Whole Foods")
    assert "THE LIST" in shop_event and "/open/shopping" in shop_event
    dinner = next(ev for ev in feed.split("BEGIN:VEVENT") if "SUMMARY:🍎" in ev)
    assert "Open in Lil'Helper: http" in dinner and "URL:http" in dinner
    page = c.get("/open/week", params={"day": "tue"})
    assert page.status_code == 200 and "lilhelper://week?day=tue" in page.text
    assert c.get("/open/evil").status_code == 404


def test_birthdays_teens_and_occasions(server, monkeypatch):
    import datetime as dt
    c = server.client
    H, _ = server.household()
    today = dt.date.today()
    teen_bday = today.replace(year=today.year - 14).isoformat()
    kid_bday = f"{today.year - 9}-10-21"            # a Wednesday in the plan week below when the year lines up
    assert c.post("/api/household/people", headers=H, json={"name": "Leo", "birthday": kid_bday}).status_code == 200
    assert c.post("/api/household/people", headers=H, json={"name": "Mia", "birthday": teen_bday, "can_cook": True}).status_code == 200
    ppl = {p["id"]: p for p in c.get("/api/household/people", headers=H).json()["people"]}
    assert ppl["leo"]["child"] and ppl["leo"]["age_band"] == "kid"
    assert ppl["mia"]["teen"] and not ppl["mia"]["child"] and ppl["mia"]["role"] == "kid"      # can't approve by default
    assert c.post("/api/household/people", headers=H, json={"name": "Bad", "birthday": "2050-01-01"}).status_code == 422
    assert c.post("/api/household/people", headers=H, json={"name": "Kidmin", "birthday": kid_bday, "admin": True}).status_code == 422
    # the birthday person's favourite on their birthday, and no jobs for them
    c.put("/api/household/people/leo", headers=H, json={"name": "Leo", "birthday": kid_bday, "likes": ["chicken_tacos"]})
    c.patch("/api/household/settings/occasions", headers=H,
            json={"value": [{"name": "Our anniversary", "date": "10-23", "kind": "anniversary", "tags": ["special"]}]})
    w = c.post("/api/week/draft", headers=H, json={"week": "2026-10-19"}).json()
    occ = w["occasions"]
    assert any(o["kind"] == "anniversary" for o in occ.get("fri", []))
    wed_bday = [o for o in occ.get("wed", []) if o["kind"] == "birthday"]
    assert wed_bday and wed_bday[0]["people"] == ["leo"]
    wed = next(e for e in w["plan"]["entries"] if e["day"] == "wed" and e["meal"] == "dinner")
    assert wed["recipe"] == "chicken_tacos" and "birthday favourite" in wed["why"]
    assert not any(j["day"] == "wed" and j["person"] == "leo" for j in w["chores"])
    up = c.get("/api/occasions", headers=H, params={"days": 366}).json()
    assert any(u["name"] == "Thanksgiving" for u in up["upcoming"])
    assert c.patch("/api/household/settings/occasions", headers=H, json={"value": [{"name": "x", "date": "13-45"}]}).status_code == 422


def test_holiday_dates():
    import datetime as dt
    from lilhelper import occasions
    assert occasions.holiday_date("thanksgiving", 2026) == dt.date(2026, 11, 26)
    assert occasions.holiday_date("easter", 2026) == dt.date(2026, 4, 5)
    assert occasions.holiday_date("mothers_day", 2026) == dt.date(2026, 5, 10)
    assert occasions.holiday_date("memorial_day", 2026) == dt.date(2026, 5, 25)
    assert occasions.yearly_on("2016-02-29", dt.date(2027, 2, 28))


def test_my_brand_store_and_price_for_an_item(server):
    c = server.client
    H, _ = server.household()
    d = c.get("/api/ingredients/broccoli", headers=H).json()
    assert d["book_prices"] and d["mine"] is None and "Garlic chicken, broccoli and rice" in d["used_in"]
    assert c.put("/api/ingredients/broccoli/pref", headers=H, json={"price": 1.0}).status_code == 422
    r = c.put("/api/ingredients/broccoli/pref", headers=H,
              json={"brand": "Farm stand", "store": "trader_joes", "price": 1.25, "pack": 1})
    assert r.status_code == 200, r.text
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/change", headers=H, json={"week": W, "day": "tue", "recipe": "chicken_broccoli_rice"})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    shop = c.get("/api/week/shopping", headers=H, params={"week": W}).json()["orders"]
    lines = [(o["store"], ln) for o in shop for ln in o["lines"] if ln["name"] == "broccoli"]
    assert lines and all(st == "Trader Joe's" and ln["brand"] == "Farm stand" and ln["price"] == 1.25 for st, ln in lines)
    assert c.delete("/api/ingredients/broccoli/pref", headers=H).status_code == 200


def test_a_meal_with_parts(server):
    c = server.client
    H, _ = server.household()
    for n in ("Lili", "Son", "Kid"):
        c.post("/api/household/people", headers=H, json={"name": n, "can_cook": True})
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    tue = _dinner(w, "tue")
    full = tue["servings"]
    w = c.post("/api/week/parts", headers=H, json={"week": W, "day": "tue", "parts": [
        {"kind": "leftovers", "eaters": ["son"], "food": "Monday's pasta"},
        {"kind": "cook", "recipe": "quesadillas", "eaters": ["kid"]}]}).json()
    tue = _dinner(w, "tue")
    assert "son" not in tue["eaters"] and "kid" not in tue["eaters"] and tue["servings"] < full
    kinds = {p["kind"]: p for p in tue["parts"]}
    assert kinds["leftovers"]["name"] == "Monday's pasta" and kinds["cook"]["name"] == "Bean and cheese quesadillas"
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    shop = c.get("/api/week/shopping", headers=H, params={"week": W}).json()["orders"]
    names = {ln["name"] for o in shop for ln in o["lines"]}
    assert "flour tortillas" in names or any("tortilla" in n for n in names)     # the quesadillas are shopped for
    assert c.post("/api/week/parts", headers=H, json={"week": W, "day": "tue", "parts": [{"kind": "dance"}]}).status_code == 422


def test_vibe_occasion_surprise_buffet_and_plan_ahead(server):
    c = server.client
    H, _ = server.household()
    c.post("/api/household/people", headers=H, json={"name": "John", "likes": ["veggie_pizza"]})
    v = c.post("/api/vibe", headers=H, json={"minutes": 30, "moods": ["quick", "veggie"]}).json()
    assert v["ideas"] and all(i["total"] <= 30 for i in v["ideas"])
    assert all("vegetarian" in i["why"] for i in v["ideas"])
    order = c.post("/api/vibe/order", headers=H, json={"recipe": v["ideas"][0]["recipe"], "servings": 2}).json()
    assert order["orders"] or order.get("note")
    occ = c.post("/api/occasions/ideas", headers=H, json={"people": ["john"], "tags": ["party"], "guests": 6}).json()
    assert occ["ideas"][0]["recipe"] == "veggie_pizza" and "John's favourite" in occ["ideas"][0]["why"]
    assert occ["servings"] >= 8
    r = c.post("/api/occasions", headers=H, json={"name": "Soccer pizza party", "date": "2026-10-24", "kind": "party",
                                                  "recipe": "veggie_pizza", "guests": 6})
    assert r.status_code == 200, r.text
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    sat = _dinner(w, "sat")
    assert sat["recipe"] == "veggie_pizza" and "+6 guests" in sat["why"]
    assert any(o["name"] == "Soccer pizza party" for o in w["occasions"]["sat"])
    s1 = c.get("/api/surprise", headers=H, params={"seed": 1}).json()
    assert s1["recipe"] and s1["steps"]
    # breakfast as a buffet: 10 portions of overnight oats, 4 left → cook 6, and no daily breakfast recipes
    c.patch("/api/household/settings/meals", headers=H, json={"value": {
        "dinner": {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "eaters": "all"},
        "breakfast": {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "eaters": "all"}, "special_nights": {}}})
    b = c.put("/api/buffet", headers=H, json={"meal": "breakfast", "items": [{"recipe": "apple_cinnamon_oats", "target": 10}]}).json()
    assert b["items"][0]["cook"] == 10
    b = c.post("/api/buffet/count", headers=H, json={"meal": "breakfast", "recipe": "apple_cinnamon_oats", "on_hand": 4}).json()
    assert b["items"][0]["cook"] == 6
    w = c.post("/api/week/draft", headers=H, json={"week": W}).json()
    assert not any(e["meal"] == "breakfast" for e in w["plan"]["entries"])
    assert w["plan"]["buffet"][0]["cook"] == 6
    ahead = c.post("/api/plan/ahead", headers=H, json={"weeks": 3, "start": W}).json()["weeks"]
    assert len(ahead) == 3 and all(x["dinners"] for x in ahead)


def test_today_and_activity_report(server, monkeypatch):
    import datetime as dt
    from lilhelper import api
    c = server.client
    H, _ = server.household()
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    monkeypatch.setattr(api.week, "today_in", lambda h: dt.date(2026, 10, 21))
    t = c.get("/api/today", headers=H).json()
    assert t["day"] == "wed" and t["meals"] and t["meals"][-1]["meal"] == "dinner"
    assert any(x["kind"] == "confirm" for x in t["tasks"])          # Monday and Tuesday are waiting for an answer
    assert t["my_jobs"]                                              # the only person cooks
    r = c.get("/api/reports/activity", headers=H, params={"end": W, "weeks": 1}).json()
    assert r["weeks"][0]["cooking_minutes"] > 0 and r["kcal"] and r["chores"][0]["total"] >= 7


def test_bulk_workbook_round_trip(server):
    import io
    from openpyxl import load_workbook
    c = server.client
    H, _ = server.household()
    r = c.get("/api/bulk/export", headers=H)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(r.content))
    assert {"People", "Recipes", "Recipe ingredients", "Ingredients", "Freezer", "Occasions"} <= set(wb.sheetnames)
    wb["People"].append(["", "Nana", "1950-05-04", "", "", "dairy", "", 0.8, "sun", "", "", "", "", "", ""])
    wb["Occasions"].append(["", "Nana's visit", "2026-10-25", "party", "nana", "", 4, "festive", "", ""])
    wb["Recipes"].append(["", "Nana's chicken soup", "household", "dinner, lunch", 4, 20, 60, 380, 10, "one_pot", "10, 11, 12",
                          2, "Nana", "", "Simmer the chicken.\nAdd the vegetables.", ""])
    for row in (["Nana's chicken soup", "chicken thighs", 1.5, "lb"], ["Nana's chicken soup", "carrots", 0.5, "lb"],
                ["Nana's chicken soup", "chicken broth", 4, "cup"]):
        wb["Recipe ingredients"].append(row)
    ing = wb["Ingredients"]
    for row in ing.iter_rows(min_row=2):
        if row[0].value == "broccoli":
            row[6].value, row[7].value, row[8].value, row[9].value = "Farm stand", "trader_joes", 1.5, 1
    wb["Freezer"].append(["", "Lasagna", "", 6, "2026-10-01", "2026-12-01", ""])
    wb["Recipes"].append(["", "Mystery stew", "household", "dinner", 4, 20, 60, "", "", "", "", "", "", "", "", ""])
    wb["Recipe ingredients"].append(["Mystery stew", "unobtainium", 1, "each"])
    buf = io.BytesIO()
    wb.save(buf)
    p = c.post("/api/bulk/import", headers=H, files={"file": ("h.xlsx", buf.getvalue())}).json()
    assert "Nana" in p["changes"]["People"]["add"] and "Nana's chicken soup" in p["changes"]["Recipes"]["add"]
    assert "broccoli" in p["changes"]["Ingredients"]["add"] and "Lasagna" in p["changes"]["Freezer"]["add"]
    assert any("unobtainium" in x for x in p["problems"])
    assert c.get("/api/household/people", headers=H).json()["people"].__len__() == 1      # nothing saved yet
    done = c.post("/api/bulk/import/confirm", headers=H, json={"token": p["token"]}).json()
    assert done["applied"] and done["recipes"] == 1
    ppl = {x["name"]: x for x in c.get("/api/household/people", headers=H).json()["people"]}
    assert ppl["Nana"]["birthday"] == "1950-05-04" and ppl["Nana"]["allergies"] == ["dairy"]
    mine = c.get("/api/recipes", headers=H, params={"mine": True}).json()["recipes"]
    soup = next(x for x in mine if x["name"] == "Nana's chicken soup")
    assert soup["meals"] == ["dinner", "lunch"] and soup["kcal"] == 380 and soup["kid_min_age"] == 10
    assert any(m["name"] == "Lasagna" for m in c.get("/api/storage", headers=H).json()["freezer_meals"])
    # an adult who isn't the admin can't
    assert c.post("/api/bulk/import/confirm", headers=H, json={"token": p["token"]}).status_code == 404


def test_voice_commands(server, monkeypatch):
    import datetime as dt
    from lilhelper import api
    c = server.client
    H, _ = server.household()
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    monkeypatch.setattr(api.week, "today_in", lambda h: dt.date(2026, 10, 21))
    say = lambda t: c.post("/api/voice", headers=H, json={"text": t}).json()   # noqa: E731
    r = say("What's for dinner tonight?")
    assert r["intent"] == "whats_for" and "Dinner today is" in r["say"] and r["screen"] == "week"
    assert "things from" in say("what's on the shopping list")["say"]
    r = say("I have half a chicken, rice and half a bag of broccoli")
    assert r["intent"] == "cook_with" and "Garlic chicken, broccoli and rice" in r["say"]
    assert say("dinner was all gone")["say"].startswith("Thanks")
    assert say("rate dinner five stars")["intent"] == "rate"
    assert say("surprise me")["say"].startswith("How about")
    assert say("I've got 20 minutes and want something quick")["intent"] == "vibe"
    assert "didn't catch" in say("sing me a song")["say"]


def test_bulk_download_link(server):
    c = server.client
    H, _ = server.household()
    url = c.post("/api/bulk/link", headers=H).json()["url"]
    path = url.split("localhost:8650", 1)[-1] if "localhost:8650" in url else "/" + url.split("/", 3)[3]
    r = c.get(path)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert c.get(path.replace("/bulk/", "/bulk/x")).status_code == 401
