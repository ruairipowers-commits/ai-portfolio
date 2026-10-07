"""Streamlit demo for Lil'Helper. Run: `helper ui`. The family's real app is the phone app (app/); this page shows the
same engine on a fictional family so anyone can try it.

1 · Input: the household (fictional), the week, budget, weeknight prep limit, how to shop, and try-to-break-it inputs.
2 · Run: specials + checked recipe ideas → meal plan (solver) → dog's week → shopping list → split across stores →
    jobs rota → savings.
3 · Output: the menu (swap a meal, approve as an adult — the human step), shopping by store with hand-offs, jobs,
    the dog, savings against a stated baseline, fridge PDFs / calendar / email, and the eval and audit view.
"""
from __future__ import annotations

import datetime as dt
import json
import time

import pandas as pd
import streamlit as st

from lilhelper import ai, catalog, demo, evals, outputs, safety, store, telemetry, week
from lilhelper.config import DAYS, ROOT, Settings, load_household
from lilhelper.prices import PriceBook

st.set_page_config(page_title="Lil'Helper", page_icon="🍎", layout="wide")
demo.activate_streamlit(ROOT)          # hosted demo: this visitor's own sandbox (no-op locally)
s = Settings.load()

DAY = dict(zip(DAYS, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
WEEKS = [dt.date(2026, 10, 5) + dt.timedelta(weeks=i) for i in range(8)]
JOB = outputs.JOB_LABEL
FLYER_INJECTION = (ROOT / "data" / "flyers" / "stop-and-shop-week.txt").read_text()   # fictional; has a $0.09 typo
                                                                                     # and an instruction line

# ------------------------------------------------------------------ header
demo.banner(st, ROOT, "Lil'Helper")
c1, c2 = st.columns([1, 9])
c1.image(str(ROOT / "brand" / "icon-1024.png"), width=72)
c2.title("Lil'Helper")
st.caption("Plans the week's meals, splits the shopping across stores by price and specials, shares the cooking and "
           "cleanup, and feeds the dog too. A solver does the choosing; a model only suggests recipes, reads flyers "
           "and writes one-line notes. Nothing is bought without a person. Fictional family, synthetic prices, "
           "offline mock model.")
demo.sidebar(st, ROOT)
gov = telemetry.start_streamlit_session(st, ROOT)

with st.expander("How this works / what to try", expanded=False):
    st.markdown("""
1. **Input** — the Rivera family is fictional: two adults, kids of 9 (peanut allergy) and 4, and Maple, a 25 kg dog.
   Pick a week, set a budget and how long weeknight cooking may take, and how you'd like to shop.
2. **Run** — a solver picks meals that fit everyone's allergies and diets, the prep limits, variety, the season and
   this week's specials; the shopping list is split across Whole Foods, Trader Joe's, Costco and Stop & Shop by
   price, fees, memberships and card credits; jobs are shared fairly.
3. **Output** — swap any meal (the rest of the week stays put), then **approve as an adult**. Only then does the
   shopping hand-off appear.

Try to break it: read a flyer with an instruction hidden in it, offer the dog grapes or "garlic chicken", or set a
budget too small to feed everyone.""")

# ------------------------------------------------------------------ 1 · input
st.header("1 · Input")
h = load_household()
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("The household (fictional)")
    ppl = pd.DataFrame([{"Who": p.name, "Age": str(p.age or "adult"), "Allergies": ", ".join(p.allergies) or "—",
                         "Likes": ", ".join(x.replace("_", " ") for x in p.likes[:2]) or "—",
                         "Cooks": "yes" if p.can_cook else ""} for p in h.people.values()])
    st.dataframe(ppl, hide_index=True, width="stretch")
    for p in h.pets.values():
        st.caption(f"🐕 {p.name}: {p.weight_kg} kg, {p.food['cups_per_day']} cups/day of {p.food['brand']}; "
                   f"plain extras from dinner capped at 10% of daily calories.")
    meals = h.meals
    st.caption("Plans: dinner every night (Thursday is leftovers), weekend breakfasts, a lunchbox on school days. "
               "Stores: Whole Foods, Trader Joe's (in store only), Costco, Stop & Shop.")
with right:
    st.subheader("This week")
    wk = st.selectbox("Week of", WEEKS, format_func=lambda d: d.strftime("%b %-d, %Y"), key="week")
    budget = st.number_input("Grocery budget for the week ($, incl. the dog)", 80, 600,
                             int(h.info.get("budget_per_week", 260)), step=10, key="budget")
    weeknight = st.slider("Weeknight hands-on cooking, max minutes", 10, 60, int(h.prep_limit("mon")), 5,
                          key="weeknight")
    choice = st.radio("How to shop", ["balanced", "cheapest", "fastest"], horizontal=True, key="choice",
                      help="balanced trades trips against fees at $20/hour of your time; cheapest ignores your "
                           "time; fastest values it highly")
    ideas = st.toggle("Let the model suggest 2 new recipes (they must pass every rule)", value=True, key="ideas")

st.subheader("Try to break it")
b1, b2, b3 = st.columns(3)
with b1:
    st.markdown("**A store flyer with an instruction in it**")
    flyer_text = st.text_area("Flyer text (as if read from a photo)", FLYER_INJECTION, height=130, key="flyer")
    read_flyer = st.button("Read this flyer", key="read_flyer")
with b2:
    st.markdown("**Something for Maple**")
    dog_try = st.text_input("Offer the dog…", "garlic chicken", key="dog_try")
    vet = st.text_input("Your vet said to avoid", "", key="vet", placeholder="e.g. sweet potato")
    if dog_try:
        pet = next(iter(h.pets.values()))
        pet.vet_notes = vet
        v = safety.dog_item(catalog.get(), pet, dog_try)
        (st.success if v.ok else st.error)(f"{dog_try}: " + ("OK as a plain extra" if v.ok else "; ".join(v.reasons)))
with b3:
    st.markdown("**A budget that's too small**")
    st.caption("Set the budget above to $120 and run: the plan says it can't fit instead of quietly dropping meals.")
    if st.button("Reset demo", help="Back to the default week; clears your session's plans"):
        import shutil
        shutil.rmtree(demo.current() or ROOT / "warehouse", ignore_errors=True) if demo.current() else \
            shutil.rmtree(ROOT / "warehouse", ignore_errors=True)
        for k in list(st.session_state):
            if not k.startswith("_governance"):
                del st.session_state[k]
        st.rerun()

if read_flyer:
    pb = PriceBook(h, wk)
    try:
        res = ai.read_flyer(ai.AIContext.make(s), h, catalog.get(), pb, "stop_and_shop", text=flyer_text)
        st.session_state["flyer_res"] = res
    except telemetry.WorkflowDisabled as e:
        st.error(str(e))
if fr := st.session_state.get("flyer_res"):
    if "instruction_on_flyer" in fr.flags:
        st.warning("This flyer contains text that looks like an instruction. It was read as data and ignored; "
                   "nothing on a flyer can change the rules.")
    st.dataframe(pd.DataFrame([{"Flyer line": i["text"], "Price": i["price_text"], "Matched": i["ingredient"] or "—",
                                "Status": i["status"].replace("_", " "), "Why": "; ".join(i["why"])}
                               for i in fr.items]), hide_index=True, width="stretch")
    st.caption("Specials only count after a person confirms them (in the phone app). A price far below normal is "
               "flagged as a likely typo.")

# ------------------------------------------------------------------ 2 · run
st.header("2 · Run")


def _household():
    hh = load_household()
    hh.raw["household"]["budget_per_week"] = budget
    for d in ("mon", "tue", "wed"):
        hh.raw["prep_minutes"][d] = weeknight
    return hh


if st.button("Plan the week", type="primary"):
    with st.status("Planning…", expanded=False) as stt:
        try:
            r = week.draft(wk, h=_household(), ideas=ideas, choice=choice, actor="demo visitor")
            st.session_state["res"] = r
            st.session_state["t_shown"] = time.time()
            stt.update(label=f"Done · {len(r.plan.entries)} meals · ${r.split.total:.2f} · {r.ms} ms", state="complete")
        except telemetry.WorkflowDisabled as e:
            stt.update(label="Stopped", state="error")
            st.error(str(e))

r = st.session_state.get("res")
if not r:
    st.info("Press **Plan the week** to see the menu, the shopping split, jobs and savings.")
    st.stop()

# ------------------------------------------------------------------ 3 · output
st.header("3 · Output")
con = store.connect()
rec = store.get_week(con, r.week_of.isoformat()) or {}
approved = rec.get("status") == "approved"
sav = rec.get("savings") or (r.savings.to_dict() if r.savings else {})
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Meals planned", len(r.plan.entries))
m2.metric(f"Groceries ({r.choice})", f"${r.split.total:.2f}",
          f"{r.split.total - budget:+.2f} vs budget", delta_color="inverse")
m3.metric("Saved vs one store", f"${sav.get('dollars_saved', 0):.2f}",
          help="Same list at your home store's regular prices in one trip (the baseline)")
m4.metric("Time saved this week", f"{sav.get('minutes_saved', 0):.0f} min",
          help="Planning before (your estimate) minus minutes spent approving, plus store minutes before minus after")
m5.metric("Status", "approved" if approved else "draft")
for f in r.flags:
    if f.startswith("over_budget"):
        st.warning(f"Over budget by ${f.rsplit('_', 1)[1]}. The plan says so rather than dropping meals; "
                   "try cheaper staples, a bigger batch night, or a higher budget.")
    elif f.startswith("chores"):
        st.warning(f)

tabs = st.tabs(["Menu", "Shopping", "Jobs", "Maple 🐕", "Savings", "Fridge & calendar", "Eval & audit"])

with tabs[0]:
    rows = []
    for d in DAYS:
        for meal in ("breakfast", "lunch", "dinner"):
            e = r.plan.at(d, meal)
            if e:
                rows.append({"Day": DAY[d], "Meal": meal, "Dish": e.name, "Servings": f"{e.servings:g}",
                             "Hands-on": f"{e.active} min", "Est. cost": f"${e.est_cost:.2f}",
                             "Why": r.notes.get((d, meal), "")})
        if d in r.plan.special_nights:
            rows.append({"Day": DAY[d], "Meal": "dinner", "Dish": f"{r.plan.special_nights[d]} night", "Servings": "",
                         "Hands-on": "", "Est. cost": "", "Why": "eat up what's in the fridge"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=min(560, 38 * len(rows) + 40))
    if r.ideas and r.ideas.rejected:
        for x in r.ideas.rejected:
            st.caption(f"❌ Model idea rejected: **{x['name']}** — {'; '.join(x['why'])}")
    if r.ideas and r.ideas.accepted:
        st.caption("✅ New this week (passed every rule): " + ", ".join(x.name for x in r.ideas.accepted))
    st.subheader("Your call")
    slots = [(e.day, e.meal) for e in r.plan.entries]
    sc1, sc2, sc3 = st.columns([3, 2, 2])
    slot = sc1.selectbox("Swap a meal (everything else stays put)", slots,
                         format_func=lambda x: f"{DAY[x[0]]} {x[1]}: {r.plan.at(*x).name}", key="slot",
                         disabled=approved)
    if sc2.button("Swap it", disabled=approved):
        st.session_state["res"] = week.swap(r.week_of, slot[0], slot[1], h=_household(), choice=r.choice,
                                            actor="demo visitor")
        st.rerun()
    if sc3.button("Approve as Dana (adult)", type="primary", disabled=approved):
        secs = time.time() - st.session_state.get("t_shown", time.time())
        week.approve(r.week_of, "dana", secs, r.choice)
        st.rerun()
    if approved:
        st.success(f"Approved by {h.people[rec['approved_by']].name if rec.get('approved_by') in h.people else rec.get('approved_by')}. The shopping hand-offs are ready.")

with tabs[1]:
    opt = pd.DataFrame([{"Option": k, "Total": f"${v.total:.2f}", "Your time": f"{v.minutes} min",
                         "Stores": ", ".join(f"{o.store_name} ({o.mode.replace('_', ' ')})" for o in v.orders)}
                        for k, v in r.options.items()])
    st.dataframe(opt, hide_index=True, width="stretch")
    for o in r.split.orders:
        credits = f", credits \\${o.credits:.2f}" if o.credits else ""
        mode = o.mode.replace("_", " ")
        with st.expander(f"{o.store_name} · {mode} · \\${o.total:.2f} ({len(o.lines)} items{credits})",
                         expanded=len(r.split.orders) == 1):
            st.dataframe(pd.DataFrame([{"Item": ln.name, "Brand": ln.brand, "Packs": ln.packs,
                                        "Each": f"${ln.price_each:.2f}", "Special": "★" if ln.special else ""}
                                       for ln in o.lines]), hide_index=True, width="stretch")
            if not approved:
                st.caption("🔒 Hand-off appears after an adult approves the week.")
            elif o.handoff == "instacart":
                st.caption("Hand-off: an Instacart shopping-list link (needs the server's Instacart key). Payload:")
                st.json(o.payload, expanded=False)
            elif o.handoff == "amazon":
                st.caption("Hand-off: a list to share to the Amazon / Whole Foods app or Reminders.")
                st.code("\n".join(o.payload.get("items", [])))
            else:
                st.caption("Hand-off: an aisle-ordered list" + (" for the store's own app." if o.mode != "in_store"
                                                                 else " for the trip."))
                st.code("\n".join(o.payload.get("aisle_ordered", [])))
    if r.split.unavailable:
        st.caption("Not sold at any enabled store: " + ", ".join(r.split.unavailable))

with tabs[2]:
    grid = {}
    for a in r.chores:
        grid.setdefault(JOB.get(a.job, a.job), {})[DAY[a.day]] = a.name
    st.dataframe(pd.DataFrame(grid).T.reindex(columns=[DAY[d] for d in DAYS]).fillna(""), width="stretch")
    st.caption("Load this week (cook 3, dishes 2, others 1): " +
               ", ".join(f"{h.people[k].name} {v}" for k, v in r.chore_load.items() if k in h.people) +
               ". Fair over a rolling 4 weeks; the 4-year-old only gets age-appropriate jobs.")

with tabs[3]:
    for p in r.pets:
        st.markdown(f"**{p.name}** needs {p.food_needed:.0f} cups this week; {p.food_on_hand:.0f} on hand.")
        bag = next(iter(h.pets.values())).food
        nice = {"dog_food": lambda q: f"{q:g} cups of {bag['brand']} ({q / bag['bag_cups']:g} bag)",
                "dog_treats": lambda q: f"{q:g} treats"}
        st.markdown("Restock with the groceries: " + (", ".join(nice.get(k, lambda q, k=k: f"{q:g} {k}")(v)
                                                               for k, v in p.restock.items()) or "nothing this week"))
        if p.extras:
            st.dataframe(pd.DataFrame([{"Day": DAY[x["day"]], "Extra": x["item"], "Amount": f"{x['amount']} {x['unit']}",
                                        "kcal": x["kcal"], "From": x["from"], "How": x["how"]} for x in p.extras]),
                         hide_index=True, width="stretch")
        for b in p.blocked:
            st.error(f"{DAY[b['day']]}: not for {p.name} — {b['item']} ({'; '.join(b['why'])})")
        for n in p.notes:
            st.caption(n)

with tabs[4]:
    if sav:
        a, b, c = st.columns(3)
        a.metric("Dollars", f"${sav['dollars_saved']:.2f} saved",
                 f"${sav['plan_dollars']:.2f} vs ${sav['baseline_dollars']:.2f}", delta_color="off")
        b.metric("Time", f"{sav['minutes_saved']:.0f} min saved",
                 f"planning {sav['planning_after']} vs {sav['planning_before']} min; shopping {sav['plan_minutes']} vs "
                 f"{sav['baseline_minutes']} min", delta_color="off")
        c.metric("Satisfaction", f"{sav['rating']}/5" if sav.get("rating") else "after meals",
                 "rated in the app after each meal", delta_color="off")
        st.caption(f"Specials saved \\${sav['specials_saved']:.2f}; memberships and cards \\${sav['credits']:.2f}. "
                   "Baseline: the same list at the home store's regular prices in one trip. " +
                   " ".join(sav.get("notes", [])))
    st.caption("Run `helper simulate --weeks 8` for eight weeks with simulated meal feedback: portions learn from "
               "what's left over, and the report tracks dollars, minutes and ratings week by week.")

with tabs[5]:
    if rec:
        hh = load_household()
        d1, d2, d3 = st.columns(3)
        d1.download_button("Weekly fridge calendar (PDF)", outputs.week_pdf(hh, rec), f"week-{r.week_of}.pdf",
                           "application/pdf")
        weeks_all = [store.get_week(con, x["week_of"]) for x in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
        d2.download_button("Monthly calendar (PDF)", outputs.month_pdf(hh, r.week_of.year, r.week_of.month,
                                                                       [w for w in weeks_all if w]),
                           f"month-{r.week_of:%Y-%m}.pdf", "application/pdf")
        d3.download_button("Calendar feed (.ics)", outputs.ics(hh, [w for w in weeks_all if w]), "meals.ics",
                           "text/calendar")
        st.caption("In the real app the calendar is a feed you subscribe to once in Google Calendar; it updates itself.")
        st.subheader("Sunday email (preview)")
        st.components.v1.html(outputs.email_html(hh, rec, {}, r.notes), height=520, scrolling=True)

with tabs[6]:
    st.markdown("**Model calls this run** (counts and cost only — no names are sent; kids are \"kid (9)\")")
    st.dataframe(pd.DataFrame([c.__dict__ for c in r.calls]), hide_index=True, width="stretch")
    if st.button("Run the eval gate"):
        rep = evals.run()
        st.session_state["eval"] = rep
    if rep := st.session_state.get("eval"):
        st.write("EVAL GATE:", "✅ PASS" if rep["passed"] else "❌ FAIL")
        st.json(rep["metrics"], expanded=False)
        st.dataframe(pd.DataFrame([{"Case": c["id"], "Passed": "✅" if c["passed"] else "❌", "Detail": c.get("detail", "")}
                                   for c in rep["cases"]]), hide_index=True, width="stretch")
    st.markdown("**Audit trail** (who approved, swapped and confirmed)")
    st.dataframe(pd.DataFrame([dict(x) for x in con.execute("SELECT ts, actor, action, detail FROM audit ORDER BY ts DESC LIMIT 20")]),
                 hide_index=True, width="stretch")
con.close()
