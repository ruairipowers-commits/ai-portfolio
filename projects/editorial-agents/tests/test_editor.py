from editorial import evals, review
from editorial.config import ROOT

D = ROOT / "evals" / "drafts"


def test_longest_shared_run_finds_copied_text():
    src = review.words("the quick brown fox jumps over the lazy dog near the quiet river bank today")
    post = review.words("as noted the quick brown fox jumps over the lazy dog near the quiet river, said nobody")
    n, txt = review.longest_shared_run(post, src, 8)
    assert n == 13 and txt.startswith("the quick brown fox")
    assert review.longest_shared_run(review.words("nothing in common here at all ok"), src, 8)[0] == 0


def test_scorecard_markdown_includes_judged_rows():
    r = review.review(D / "clean.md", D / "sources" / "fraud")
    md = review.scorecard_md(r, [{"criterion": "Accuracy", "score": 4, "note": "fine"}])
    assert "| Accuracy (editor) | 4/5 | fine |" in md and "✅" in md


def test_eval_gate_passes():
    r = evals.run()
    assert r["passed"], [x for x in r["results"] if not x["passed"]]
    assert len(r["results"]) == 9
