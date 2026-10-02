"""FR-2/3/4, OBS-02, SEC-04: entitlements, refusals, verification, injection, budgets, kill switch."""
import json
import os
from pathlib import Path

import pytest



def test_cited_answer(m, built):
    r = m.answer.ask(built, "What was Halvorsen Robotics' revenue in fiscal 2025?", "public-analyst")
    assert r["status"] == "answered" and "4.82 billion" in r["answer"]
    c = r["citations"][0]
    assert c["doc_id"] == "halv-2025-annual" and c["page"] == 3 and c["verbatim"]


def test_entitlement_filter_before_ranking(m, built):
    ok = m.answer.ask(built, "What is Northbridge's price target on Halvorsen Robotics?", "equity-analyst")
    no = m.answer.ask(built, "What is Northbridge's price target on Halvorsen Robotics?", "public-analyst")
    assert ok["status"] == "answered" and "$148" in ok["answer"]
    assert no["status"] == "refused" and "148" not in no["refusal_reason"]
    assert all(c["entitlement"] == "public" for c in no["context"])
    assert no["excluded_entitlement"] > 0


def test_licence_barred_document_never_reaches_model(m, built):
    r = m.answer.ask(built, "What does Kestrel Research say about Corvane Pharmaceuticals?", "portfolio-manager")
    assert r["status"] == "refused" and "licence forbids AI processing" in r["refusal_reason"]
    assert not any(c["doc_id"] == "kestrel-crvn-2026q2" for c in r["context"])


def test_hidden_instructions_have_no_effect(m, built):
    r = m.answer.ask(built, "How does Aldgate rate Brightwater Utilities?", "portfolio-manager")
    assert r["status"] == "answered" and "Neutral" in r["answer"] and "250" not in r["answer"]


def test_runtime_screen_catches_what_quarantine_missed(m, project, monkeypatch):
    import yaml

    cfg = project / "config" / "settings.yaml"
    raw = yaml.safe_load(cfg.read_text())
    raw["ingest"]["quarantine_suspicious"] = False
    cfg.write_text(yaml.safe_dump(raw))
    s = m.store.Settings.load()
    m.cli.reset_corpus(s)
    m.ingest.ingest(s, full=True)
    r = m.answer.ask(s, "How does Aldgate rate Brightwater Utilities strong buy price target?", "portfolio-manager", top_k=10)
    assert "injection_text_dropped" in r["flags"]
    assert all("Ignore all prior instructions" not in c["text"] for c in r["context"])


def test_no_answer_refused(m, built):
    for q in ("What is Halvorsen Robotics' dividend policy?", "What was Apple's revenue last year?"):
        assert m.answer.ask(built, q, "public-analyst")["status"] == "refused"


def test_fabricated_or_unsupported_answers_become_refusals(m, built):
    ctx = [{"chunk_id": "c1", "text": "Revenue was $4.82 billion in fiscal 2025.", "doc_id": "d", "title": "t",
            "page": 1, "section": ""}]
    res = {"flags": [], "status": "refused", "refusal_reason": ""}
    m.answer._check(res, '{"answer": "Revenue was $9.99 billion.", "citations": [{"chunk_id": "c1", "quote": "Revenue was $9.99 billion"}]}',
           ctx, built)
    assert res["status"] == "refused" and "unverified" in res["flags"]
    res = {"flags": [], "status": "refused", "refusal_reason": ""}
    m.answer._check(res, '{"answer": "Revenue was $9.99 billion.", "citations": [{"chunk_id": "c1", "quote": "Revenue was $4.82 billion in fiscal 2025."}]}',
           ctx, built)
    assert res["status"] == "refused" and "unsupported" in res["flags"]
    res = {"flags": [], "status": "refused", "refusal_reason": ""}
    m.answer._check(res, "Sure! The answer is 4.82", ctx, built)
    assert "invalid_output" in res["flags"]


def test_supported_ratio_checks_numbers(m):
    ratio, rows = m.guardrails.supported_ratio("Revenue was $4.82 billion in fiscal 2025.", ["Revenue was $4.82 billion in fiscal 2025."])
    assert ratio == 1.0
    ratio, _ = m.guardrails.supported_ratio("Revenue was $5.00 billion in fiscal 2025.", ["Revenue was $4.82 billion in fiscal 2025."])
    assert ratio == 0.0


def test_budget_blocks_unpriced_model(m, built):
    r = m.answer.ask(built, "What was Halvorsen Robotics' revenue in fiscal 2025?", "public-analyst", alias="claude-sonnet")
    assert r["status"] == "refused" and "blocked" in r["flags"]


def test_embedding_change_requires_reindex(m, built, monkeypatch):
    reg = m.llm.Registry(m.store.ROOT / "config" / "models.yaml")
    reg.set_alias("embed-primary", "bedrock-titan-embed-v2")
    with pytest.raises(m.answer.IndexMismatch):
        m.answer.ask(built, "What was Halvorsen Robotics' revenue in fiscal 2025?", "public-analyst")


def test_kill_switch_blocks_and_is_logged(m, built, console):
    console.update(enabled=False, reason="provider incident", changed_by="head-of-risk")
    m.telemetry._state_cache = (0.0, None)
    with pytest.raises(m.telemetry.WorkflowDisabled, match="provider incident"):
        m.answer.ask(built, "What was Halvorsen Robotics' revenue in fiscal 2025?", "public-analyst")
    m.telemetry.flush()
    blocked = [e for e in console["events"] if e["status"] == "blocked"]
    assert len(blocked) == 1 and blocked[0]["flags"] == ["kill_switch"]


def test_telemetry_records_runs_without_question_text(m, built):
    m.answer.ask(built, "What was Halvorsen Robotics' revenue in fiscal 2025?", "public-analyst", actor="ana")
    from conftest import read_spool

    ev = [e for e in read_spool(Path(os.environ["GOVERNANCE_SPOOL"])) if e["event_type"] == "ask"][-1]
    assert ev["actor"] == "ana" and ev["model"] == "mock-extractive" and ev["cost_usd"] > 0 and ev["records_in"] == 5
    assert "Halvorsen" not in json.dumps(ev["detail"]) and "question_sha" in ev["detail"]
