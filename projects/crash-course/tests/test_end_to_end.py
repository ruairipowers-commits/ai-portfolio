"""The offline end-to-end run (`course all`) and the eval gate pass on the mock models."""
from crash_course import evals, simulate


def test_course_all_end_to_end(s):
    out = simulate.run(s, seed=3, learners=8)
    assert out["ok"], out
    assert out["content"]["passing"] == out["content"]["familiar_levels"] >= 38
    assert out["builds"]["published"]
    assert {x["owner"] for x in out["suggestions"]["items"]} == {"approved", "rejected"}
    assert out["revision"]["held_answer_key_edits"] >= 1


def test_eval_gate_passes(s):
    out = evals.run(s)
    assert out["passed"], {k: g for k, g in out["gates"].items() if not g["ok"]}
