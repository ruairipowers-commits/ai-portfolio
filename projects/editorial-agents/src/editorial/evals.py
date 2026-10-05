"""The eval gate (EVAL-01/02/03): golden cases for the scout and for the editor's checklist.

    editorial eval [--alias classifier-candidate]

Scout cases run the whole scout on the recorded fixtures and check what happened to specific candidates (an
injection attempt must be escalated, a near-copy of a published post must not reach the queue) and that the queue is
full and varied. Editor cases run the checklist on golden drafts with planted faults. The gate: every must-catch case
caught (recall 1.0) and the clean draft passes.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from . import review, scout, telemetry
from .config import ROOT, settings
from .llm import Classifier
from .store import Store
from .textsim import Space, cosine


def run(alias: str | None = None) -> dict:
    gs = yaml.safe_load((ROOT / "evals" / "golden_set.yaml").read_text())
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "eval.sqlite")
        corpus = str(ROOT / "fixtures" / "corpus.json")
        scout.run(store, scout.fixture_getter(), corpus=corpus, classifier=Classifier(alias) if alias else None,
                  now=scout.FIXTURE_NOW)
        queue = store.queue()
        for case in gs["scout"]:
            t = store.topic(case["topic_id"])
            got = t["status"] if t else "missing"
            ok = got in case["expect_status"]
            results.append({"id": case["id"], "kind": "scout", "passed": ok, "expected": case["expect_status"],
                            "got": got, "why": case["why"]})
        size = settings()["queue"]["size"]
        sp = Space([scout.rank.text_of(t) for t in queue])
        vecs = [sp.vec(scout.rank.text_of(t)) for t in queue]
        worst = max((cosine(a, b) for i, a in enumerate(vecs) for b in vecs[i + 1:]), default=0.0)
        results.append({"id": "queue-full", "kind": "scout", "passed": len(queue) == size, "expected": size,
                        "got": len(queue), "why": "NFR-2: the queue always holds N topics"})
        results.append({"id": "queue-varied", "kind": "scout", "passed": worst <= settings()["queue"]["max_similarity"],
                        "expected": f"≤ {settings()['queue']['max_similarity']}", "got": round(worst, 3),
                        "why": "NFR-3: no two queue topics too similar"})
    published = scout.published_texts(str(ROOT / "fixtures" / "corpus.json"))
    for case in gs["editor"]:
        d = ROOT / "evals" / "drafts"
        r = review.review(d / case["draft"], d / "sources" / case["sources"], published)
        failed = {c["criterion"] for c in r["checks"] if not c["passed"]}
        want = set(case.get("must_fail", []))
        ok = (want <= failed) if want else not failed
        results.append({"id": case["id"], "kind": "editor", "passed": ok,
                        "expected": sorted(want) or "all checks pass", "got": sorted(failed) or "all pass",
                        "why": case["why"]})
    passed = all(r["passed"] for r in results)
    telemetry.record("eval", event_type="eval", status="pass" if passed else "fail", items=len(results),
                     detail={"passed": sum(r["passed"] for r in results), "cases": len(results)})
    return {"passed": passed, "results": results}
