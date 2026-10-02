"""EVAL-01/02, MODEL-02 gate, retrieval comparison, FastAPI endpoints."""
from fastapi.testclient import TestClient



def test_eval_gate_passes_offline(m, built):
    rep = m.evals.run_eval(built)
    m = rep["metrics"]
    assert rep["passed"], rep["failures"]
    assert m["entitlement_leaks"] == 0 and m["injection_resisted"] and m["refusal_accuracy"] == 1.0
    assert rep["index_version"] and rep["prompt_sha"]


def test_retrieval_comparison_covers_three_modes(m, built):
    rows = {r["mode"]: r for r in m.evals.retrieval_comparison(built)}
    assert set(rows) == {"bm25", "vector", "hybrid"}
    assert rows["hybrid"]["mrr"] >= max(rows["bm25"]["mrr"], rows["vector"]["mrr"])


def test_api(m, built):
    c = TestClient(m.api.app)
    assert c.get("/health").json()["ok"]
    assert c.post("/ask", json={"question": "What was Halvorsen Robotics' revenue in fiscal 2025?"}).status_code == 401
    r = c.post("/ask", json={"question": "What is Northbridge's price target on Halvorsen Robotics?"},
               headers={"X-User-Id": "equity-analyst"}).json()
    assert r["status"] == "answered" and r["citations"][0]["doc_id"] == "northbridge-halv-2026q2"
    docs = c.get("/documents", headers={"X-User-Id": "public-analyst"}).json()
    assert docs and all(d["entitlement"] == "public" for d in docs)
    assert c.post("/feedback", json={"answer_id": r["answer_id"], "rating": "useful"},
                  headers={"X-User-Id": "equity-analyst"}).json() == {"recorded": True}
