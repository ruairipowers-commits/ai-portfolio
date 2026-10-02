"""FR-1..5, DATA-02/03/05, SEC-02, MODEL-05, HITL, OBS-03 against the embedded Postgres."""
import json
import re

import pytest


def test_detection_matches_golden_set_and_explanations_cite_runbooks(m, ready):
    rep = m.evals.run_eval(ready)
    mt = rep["metrics"]
    assert rep["passed"], rep["failures"]
    assert mt["detection_recall"] == 1.0 and mt["detection_precision"] == 1.0
    assert mt["citation_rate"] == 1.0 and mt["unsafe_actions"] == 0 and mt["human_routing"] == 1.0


def test_split_day_explained_from_corporate_action_runbook(m, ready):
    r = m.explain.run_eod(ready, "2026-09-17")
    by = {b["break_type"]: r["explanations"][b["break_id"]] for b in r["breaks"]}
    assert set(by) == {"position_break", "pnl_break"}
    e = by["position_break"]
    assert e["status"] == "explained" and e["runbook_refs"][0].startswith("RB-04")
    assert e["kb_version"] and e["prompt_sha"]
    assert r["alerts"] == 2
    again = m.explain.run_eod(ready, "2026-09-17", reload=False)
    assert again["alerts"] == 0                      # one alert per break, however often the heartbeat runs
    assert again["cost_usd"] == 0 and all("cached" in e["flags"] for e in again["explanations"].values())


def test_heartbeat_time_changes_what_is_late_or_missing(m, ready):
    early = m.explain.run_eod(ready, "2026-09-15", "18:00")
    late = m.explain.run_eod(ready, "2026-09-15", "21:00", reload=False)
    assert [(b["break_type"], b["severity"]) for b in early["breaks"]] == [("missing_file", "critical")]
    assert early["summary"]["nav_signoff"].startswith("blocked")
    assert [(b["break_type"], b["severity"]) for b in late["breaks"]] == [("late_file", "high")]


def test_critical_breaks_always_need_a_human(m, ready):
    r = m.explain.run_eod(ready, "2026-09-18")
    assert r["summary"]["critical"] == 2
    assert all(e["needs_human"] and "critical_needs_human" in e["flags"] for e in r["explanations"].values())


def test_runbook_injection_is_quarantined_and_pii_redacted(m, ready):
    with m.store.connect(ready) as con:
        q = con.execute("select doc_id, text from kb.quarantine").fetchall()
        assert [x["doc_id"] for x in q] == ["RB-10"] and "--force" in q[0]["text"]
        assert not con.execute("select 1 from kb.chunks where text ilike '%%note for ai%%'").fetchone()
        inc = con.execute("select text from kb.chunks where chunk_id = 'INC-2026-024'").fetchone()["text"]
        assert "Okonjo" not in inc and "Calloway" not in inc and "[CLIENT]" in inc and "@calloway" not in inc
        rb15 = " ".join(r["text"] for r in con.execute("select text from kb.chunks where doc_id = 'RB-15'"))
        assert "[REDACTED_EMAIL]" in rb15 and "[REDACTED_PHONE]" in rb15


def test_unsafe_runbook_step_is_blocked_by_policy(m, ready):
    p = next((ready.kb_dir / "runbooks").glob("RB-11-*.md"))
    p.write_text(re.sub(r"(?m)^1\. .*$", "1. Run `eod rerun --all --force` to clear the break.", p.read_text(), count=1))
    stats = m.kb.index(ready)
    assert stats["docs_changed"] == 1                 # incremental: only the edited runbook
    r = m.explain.run_eod(ready, "2026-09-24")
    e = next(e for e in r["explanations"].values() if e["break_type"] == "position_break")
    assert "unsafe_action" in e["flags"] and e["needs_human"]
    assert e["next_step"].startswith("Blocked by policy") and "--force" not in e["next_step"].split("(")[0]


def test_policy_rejects_uncited_and_invented_steps(m, ready):
    brk = {"severity": "high"}
    rb = [{"chunk_id": "RB-01#steps", "text": "1. Confirm whether the file has now arrived."}]
    exp = m.explain.Explanation(likely_cause="x", next_step="Call the vendor CEO at home.", runbook_refs=["RB-99#steps"])
    status, flags, _ = m.explain.check(ready, brk, exp, rb, [])
    assert status == "needs_human" and {"no_runbook_citation", "citation_not_in_context"} <= set(flags)
    exp = m.explain.Explanation(likely_cause="x", next_step="Call the vendor CEO at home.", runbook_refs=["RB-01#steps"])
    assert "step_not_in_runbook" in m.explain.check(ready, brk, exp, rb, [])[1]


def test_fallback_then_degraded_mode(m, ready):
    r = m.explain.run_eod(ready, "2026-09-21", unavailable={"mock-explainer"})
    assert all(e["used_fallback"] and e["model_name"] == "mock-explainer-lite" for e in r["explanations"].values())
    r = m.explain.run_eod(ready, "2026-09-22", unavailable={"mock-explainer", "mock-explainer-lite"}, reload=False)
    e = next(iter(r["explanations"].values()))
    assert e["status"] == "degraded" and e["runbook_refs"] and r["alerts"] == 1


def test_dbt_failure_blocks_explanations(m, ready):
    with m.store.connect(ready) as con:
        con.execute("update raw.prices set close = null where ticker = 'ALPN' and business_date = '2026-09-17'")
        con.commit()
    r = m.explain.run_eod(ready, "2026-09-17", reload=False)
    assert r["status"] == "blocked_dq" and not r["explanations"]


def test_kill_switch(m, ready, console):
    console.update(enabled=False, reason="runbook review in progress", changed_by="head-of-ops")
    m.telemetry._state_cache = (0.0, None)
    with pytest.raises(m.telemetry.WorkflowDisabled):
        m.explain.run_eod(ready, "2026-09-17")


def test_feedback_retention_and_telemetry(m, ready):
    r = m.explain.run_eod(ready, "2026-09-23", actor="dana")
    eid = next(iter(r["explanations"].values()))["explanation_id"]
    m.explain.record_feedback(ready, eid, "wrong", "dana", "it was the GBP file")
    dry = m.retention.apply_retention(ready, days=-1)
    assert dry["tables"]["audit.explanations"]["rows"] >= 2 and not dry["apply"]
    done = m.retention.apply_retention(ready, days=-1, apply=True)
    assert done["tables"]["audit.feedback"]["sha256"]
    with m.store.connect(ready) as con:
        assert con.execute("select count(*) as n from audit.feedback").fetchone()["n"] == 0
    import os
    from pathlib import Path

    from conftest import read_spool

    ev = [e for e in read_spool(Path(os.environ["GOVERNANCE_SPOOL"])) if e["event_type"] == "eod-check"]
    assert ev[0]["actor"] == "dana" and ev[0]["records_out"] == 2 and ev[0]["cost_usd"] > 0 and ev[0]["records_in"] > 0


def test_dag_structure():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "dags" / "eod_heartbeat.py").read_text()
    tree = ast.parse(src)
    tasks = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
             and any(getattr(d, "id", "") == "task" for d in n.decorator_list)}
    assert tasks == {"as_of", "load_feeds", "dbt_build", "explain_and_alert", "send_alerts"}
    assert 'schedule="*/5 17-21 * * 1-5"' in src
