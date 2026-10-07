"""One test per key control. The sample is fictional; the parsers are the ones used on live data."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from launchtracker import analytics as A
from launchtracker import guardrails, reference, summaries, telemetry
from launchtracker.llm import BudgetExceeded
from launchtracker.sources import gcat, ll2, satcat


# ---------------- DATA-01: sources reconciled, provenance kept
def test_every_row_has_a_source_and_fetch_time(env):
    s, con = env
    assert con.execute("select count(*) from launches where source is null or fetched_at is null").fetchone()[0] == 0
    assert con.execute("select count(*) from launches where ll2_id is not null and gcat_tag is null "
                       "and outcome <> 'pending'").fetchone()[0] == 0          # every detailed past launch matched


def test_disagreement_is_kept_not_overwritten(env):
    s, con = env
    d = con.execute("select field, ll2_value, gcat_value from discrepancies").fetchall()
    assert d == [("outcome", "success", "partial")]


def test_match_without_designator_uses_time_and_family():
    t = datetime(2025, 3, 1, 12, tzinfo=timezone.utc)
    l = {"launch_id": "ll2:x", "designator": None, "net": t, "rocket_family": "Taiga", "rocket": "Taiga-2",
         "outcome": "success", "provider": "P", "location": "L"}
    g = {"launch_id": "gcat:2025-010", "gcat_tag": "2025-010", "designator": "2025-010", "net": t + timedelta(minutes=3),
         "rocket": "Taiga-2", "outcome": "success", "payload_mass_kg": 100.0, "provider": "TSA", "location": "Taiga"}
    from launchtracker.load import reconcile
    rows, notes = reconcile([l], [g])
    assert len(rows) == 1 and rows[0]["gcat_tag"] == "2025-010" and not notes


# ---------------- format changes stop the load and say why
def test_gcat_header_change_is_refused():
    with pytest.raises(gcat.FormatChanged, match="missing"):
        gcat.parse("#Tag\tDate\n1\t2\n", False, datetime.now(timezone.utc))


def test_satcat_header_change_is_refused():
    with pytest.raises(satcat.FormatChanged, match="Header is"):
        satcat.parse("A,B\n1,2\n", datetime.now(timezone.utc))


def test_gcat_codes():
    assert gcat.outcome("OS") == "success" and gcat.outcome("OF") == "failure" and gcat.outcome("O50") == "partial"
    assert gcat.parse_date("1957 Oct  4 1928:34") == datetime(1957, 10, 4, 19, 28, 34, tzinfo=timezone.utc)


# ---------------- NFR-2: Launch Library 2 budget, enforced before sending
def test_ll2_budget_refuses_the_16th_request(env):
    s, con = env
    b = ll2.RequestBudget(con, 15)
    for i in range(15):
        b.take(f"https://example/{i}")
    with pytest.raises(ll2.BudgetExhausted):
        b.take("https://example/16")


# ---------------- DATA-04: usage rights
def test_no_licence_no_image(env):
    s, con = env
    lid = con.execute("select launch_id from launches where image_licence = 'Unknown'").fetchone()[0]
    d = A.launch(con, s, lid)["image"]
    assert d["show"] is False and d["link"]
    ok = con.execute("select launch_id from launches where image_licence = 'Own work (generated)' limit 1").fetchone()[0]
    assert A.launch(con, s, ok)["image"]["show"] is True


def test_cost_needs_approval_and_is_never_estimated(env):
    s, con = env
    launch = {"rocket_family": "SLS", "mission_type": "Human Exploration"}
    r = reference.cost_for(con, s, launch)
    assert r["status"] == "NOT_PUBLIC" and r["pending_review"] == ["sls-orion-oig-2021"]
    with pytest.raises(ValueError):
        reference.review(con, "sls-orion-oig-2021", "approved", "  ")          # a named reviewer is required
    reference.review(con, "sls-orion-oig-2021", "approved", "Ruairi")
    r = reference.cost_for(con, s, launch)
    assert r["status"] == "PUBLIC" and r["entry"]["amount_usd"] == 4_100_000_000
    assert s["costs"]["allow_model_estimates"] is False


# ---------------- SEC-02 / SEC-04 / OBS-02: guard
def test_injection_flagged_and_withheld(env):
    s, con = env
    lid = con.execute("select launch_id from launches where mission_description ilike '%ignore the data%'").fetchone()[0]
    r = summaries.mission(con, s, lid)
    assert "injection_suspected" in r.flags and "failed" not in r.text and "cancelled" not in r.text


def test_second_defence_rejects_an_obedient_draft(env):
    s, con = env
    s.raw["guard"]["drop_description_on_injection"] = False
    lid = con.execute("select launch_id from launches where mission_description ilike '%ignore the data%'").fetchone()[0]
    r = summaries.mission(con, s, lid)
    assert not r.accepted and r.source == "template" and "draft_rejected" in r.flags
    assert any("still scheduled" in p for p in r.problems)


def test_numbers_and_citations_are_checked():
    facts = {"launch": {"rocket": "Kestrel 1", "outcome": "success", "net_date": "2026-01-02"}}
    good = guardrails.Summary(subject="x", text="It flew on a Kestrel 1 on 2026-01-02.",
                              citations=[{"field": "launch.rocket", "value": "Kestrel 1"}])
    assert guardrails.check(good, facts) == []
    bad = guardrails.Summary(subject="x", text="It carried 42 satellites and cost $7 million.",
                             citations=[{"field": "launch.rocket", "value": "Condor 9"}])
    p = " ".join(guardrails.check(bad, facts))
    assert "numbers not in the data" in p and "cost" in p and "Condor 9" in p


def test_off_schema_output_is_rejected():
    with pytest.raises(Exception):
        guardrails.parse("Sure! Here is a summary of the launch.")


# ---------------- DATA-03: minimisation
def test_facts_hold_only_what_a_summary_needs(env):
    s, con = env
    lid = con.execute("select launch_id from launches where crewed and outcome = 'success' limit 1").fetchone()[0]
    f = summaries.mission_facts(A.launch(con, s, lid))
    assert "mission_description" not in json.dumps(f) and "image_url" not in json.dumps(f)


# ---------------- COST-01 / COST-02 / OBS-01 / MODEL-04
def test_budget_stops_the_call(env):
    s, con = env
    s.raw["cost"]["max_usd_per_run"] = 0.0
    lid = con.execute("select launch_id from launches limit 1").fetchone()[0]
    with pytest.raises(BudgetExceeded):
        summaries.mission(con, s, lid)


def test_every_call_logged_with_prompt_hash_and_cost(env):
    s, con = env
    lid = con.execute("select launch_id from launches where outcome = 'pending' limit 1").fetchone()[0]
    summaries.mission(con, s, lid)
    r = con.execute("select prompt_version, prompt_sha, cost_usd, input_tokens from audit.ai_calls").fetchone()
    assert r[0] == "mission_summary.v1" and len(r[1]) == 16 and r[2] > 0 and r[3] > 0


# ---------------- kill switch, in the code path
def test_kill_switch_blocks_summaries(env, monkeypatch):
    s, con = env
    monkeypatch.setattr(telemetry, "status", lambda *a, **k: telemetry.Status(False, "test"))
    lid = con.execute("select launch_id from launches limit 1").fetchone()[0]
    with pytest.raises(telemetry.WorkflowDisabled):
        summaries.mission(con, s, lid)


# ---------------- analytics are SQL and agree with themselves
def test_per_year_adds_up(env):
    s, con = env
    for r in A.per_year(con):
        assert r["successes"] + r["failures"] + r["partial"] <= r["launches"]
    total = sum(r["launches"] for r in A.per_year(con))
    assert total == con.execute("select count(*) from launches where outcome <> 'pending'").fetchone()[0]


def test_filters_are_parameterised(env):
    s, con = env
    rows = A.explorer(con, {"provider": ["x'); drop table launches; --"]})
    assert rows == [] and con.execute("select count(*) from launches").fetchone()[0] > 0


# ---------------- live mode without the network: labels follow the data; the refresh stops at its cap and resumes
def test_labels_follow_loaded_data(monkeypatch):
    from launchtracker.config import Settings
    monkeypatch.setenv("LAUNCHES_MODE", "live")
    s = Settings.load()
    assert s.mode == "live" and s.for_data("fixture").mode == "fixture"
    assert s.for_data("fixture").now().isoformat().startswith("2026-10-07T12:00")


def test_live_refresh_stops_at_cap_and_resumes_backfill(env, monkeypatch):
    s, con = env
    calls = []

    def fake(con_, settings, path, params):
        calls.append((path, params.get("offset")))
        return {"results": [{"id": f"x{len(calls)}"}], "next": "more"}

    monkeypatch.setattr(ll2, "get_json", fake)
    recs, used, note = ll2.live_pages(con, s, max_requests=4)
    assert used == 4 and "stopped" in note and len(recs) == 4
    assert calls[2] == ("launches/previous", 0) and calls[3] == ("launches/previous", 1)
    calls.clear()
    ll2.live_pages(con, s, max_requests=3)
    assert calls[2] == ("launches/previous", 2)          # the backfill picks up where it stopped
