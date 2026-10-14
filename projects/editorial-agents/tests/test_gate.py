"""The ready-to-publish gate: code decides, from the code checks and the editor's scores; any doubt holds the post."""
import json

from editorial import review
from editorial.cli import main

BODY = ("---\ndate: 2026-10-15\nslug: x\nshort: X\ncategories: [Agents]\ntags: [{tags}]\naudience: [Hiring managers]\n"
        "section: AI insight\n---\n\n# A title\n\nIntro.\n\n<!-- more -->\n\n{words}\n\n"
        "[one](https://a.example/1) and [two](https://b.example/2).\n\n*{disc}*\n")
GOOD = {"criteria": [{"criterion": c, "score": 4, "note": "ok"} for c in
                     ("Accuracy", "Originality", "Usefulness", "Clarity and voice", "Site rules")], "publishable": True}
DISC = "Drafted with AI agents: Claude reviewed and edited it, it passed every automated check, and I approved it."


def _post(tmp_path, tags="Agents, AutoPublished", disc=DISC, n=1000):
    p = tmp_path / "x.md"
    p.write_text(BODY.format(tags=tags, words=" ".join(f"w{i}" for i in range(n)), disc=disc))
    return p


def test_publishes_only_when_everything_passes(tmp_path):
    g = review.gate(_post(tmp_path), GOOD, published=[])
    assert g["publish"] and g["editor_min"] == 4 and not g["reasons"]


def test_holds_on_any_doubt(tmp_path):
    low = json.loads(json.dumps(GOOD))
    low["criteria"][0]["score"] = 3
    assert not review.gate(_post(tmp_path), low, published=[])["publish"]
    assert not review.gate(_post(tmp_path), {**GOOD, "publishable": False}, published=[])["publish"]
    assert not review.gate(_post(tmp_path), {"criteria": GOOD["criteria"][:3], "publishable": True}, published=[])["publish"]
    assert not review.gate(_post(tmp_path, tags="Agents"), GOOD, published=[])["publish"]          # no AutoPublished tag
    assert not review.gate(_post(tmp_path, disc="Drafted with AI agents."), GOOD, published=[])["publish"]
    held = review.gate(_post(tmp_path, n=200), GOOD, published=[])                                 # too short
    assert not held["publish"] and any("Length" in r for r in held["reasons"])


def test_cli_exit_code(tmp_path, capsys):
    ed = tmp_path / "editor.json"
    ed.write_text(json.dumps(GOOD))
    assert main(["gate", str(_post(tmp_path)), "--editor", str(ed), "--corpus", "fixtures/corpus.json"]) == 0
    assert "DECISION: PUBLISH" in capsys.readouterr().out
    ed.write_text(json.dumps({**GOOD, "publishable": False}))
    assert main(["gate", str(_post(tmp_path)), "--editor", str(ed), "--corpus", "fixtures/corpus.json"]) == 1
