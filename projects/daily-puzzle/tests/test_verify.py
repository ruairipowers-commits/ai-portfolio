"""The verifier: every kind can publish; every known-bad draft is rejected; the sandbox holds (FR-2, NFR-2, NFR-5)."""
import json

import pytest

from daily_puzzle import llm, puzzles, sandbox, verify
from daily_puzzle.puzzles import KINDS


@pytest.fixture()
def ctx(s):
    return verify.Ctx(s, verify.make_client(s, max_usd=5), None, purpose="test")


@pytest.mark.parametrize("kind", list(KINDS))
@pytest.mark.parametrize("difficulty", ["easy", "hard"])
def test_every_kind_publishes(ctx, kind, difficulty):
    d = puzzles.make(kind, 21, difficulty)
    out, rep = verify.verify(d, ctx)
    assert rep.decision == "PUBLISH", rep.reasons
    assert [x["step"] for x in rep.steps][-1] == "solver"


@pytest.mark.parametrize("kind,scenario,flag", [
    ("knights-knaves", "two_answers", "ambiguous"), ("ordering", "two_answers", "ambiguous"),
    ("sequence", "two_answers", "ambiguous"), ("cipher", "wrong_key", "wrong_key"),
    ("python-output", "wrong_key", "wrong_key"), ("tiny-finetune", "nondeterministic", "nondeterministic"),
    ("weights-inspection", "bad_license", "data_rights"), ("weights-inspection", "pickle", "data_rights"),
    ("embeddings", "sandbox_escape", "sandbox_violation"), ("anagram", "offensive", "content_policy"),
    ("combinatorics", "copyrighted", "content_policy")])
def test_bad_drafts_are_rejected(ctx, kind, scenario, flag):
    _, rep = verify.verify(puzzles.make(kind, 4, "easy", scenario), ctx)
    assert rep.decision == "REJECT" and flag in rep.flags, (rep.reasons, rep.flags)


def test_report_never_contains_the_answer(ctx):
    d = puzzles.make("cipher", 9, "medium", "wrong_key")
    _, rep = verify.verify(d, ctx)
    assert d["answer"] not in json.dumps(rep.as_dict())


def test_repeat_is_rejected(ctx):
    d = puzzles.make("anagram", 2, "medium")
    ctx.history = [puzzles.make("anagram", 2, "medium")]
    assert verify.verify(d, ctx)[1].reasons == ["repeat: repeat of an earlier puzzle"]


def test_schema_invalid_model_output(ctx):
    _, rep = verify.verify("Sure! Here is a fun puzzle: what is 2+2?", ctx)
    assert rep.decision == "REJECT" and "schema_invalid" in rep.flags


def test_learning_fields_required_for_coding(ctx):
    d = puzzles.make("data-wrangling", 3, "easy")
    d["learning_objective"], d["skill_tags"] = "", []
    _, rep = verify.verify(d, ctx)
    assert any("learning objective" in r for r in rep.reasons)


def test_solver_disagreement_rejects(ctx, monkeypatch):
    """A different answer from the blind solver blocks publication (the case formal checks can't see)."""
    monkeypatch.setattr(puzzles, "mock_solve", lambda pub: {"answer": "nobody", "code": None, "other_valid_answers": [],
                                                            "confidence": 0.9, "reasoning": "x"})
    _, rep = verify.verify(puzzles.make("ordering", 3, "easy"), ctx)
    assert rep.decision == "REJECT" and "solver_disagrees" in rep.flags


def test_solver_finding_another_answer_rejects(ctx, monkeypatch):
    real = puzzles.mock_solve
    monkeypatch.setattr(puzzles, "mock_solve", lambda pub: {**real(pub), "other_valid_answers": ["Zed"]})
    _, rep = verify.verify(puzzles.make("knights-knaves", 3, "easy"), ctx)
    assert rep.decision == "REJECT" and "ambiguous" in rep.flags


def test_solver_never_sees_key_or_reference(ctx, monkeypatch):
    seen = {}
    real = llm.MockProvider.complete

    def spy(self, spec, system, user, max_tokens):
        if "ROLE: solver" in system:
            seen["user"] = user
        return real(self, spec, system, user, max_tokens)
    monkeypatch.setattr(llm.MockProvider, "complete", spy)
    d = puzzles.make("tiny-finetune", 3, "easy")
    verify.verify(d, ctx)
    assert d["answer"] not in seen["user"] and d["reference_code"][:60] not in seen["user"]
    assert d["solution"][:40] not in seen["user"]


def test_budget_stops_the_run(s):
    ctx = verify.Ctx(s, verify.make_client(s, max_usd=0.000001), None)
    _, rep = verify.verify(puzzles.make("ordering", 3, "easy"), ctx)
    assert "budget" in rep.flags


# ---------------------------------------------------------------- sandbox
def test_sandbox_has_no_secrets_and_no_network(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_secret")
    r = sandbox.run("import os\nprint(os.environ.get('RESEND_API_KEY', 'none'))")
    assert r.ok and r.answer == "none"
    r = sandbox.run("import urllib.request\ntry:\n    urllib.request.urlopen('http://example.com', timeout=2)\nexcept Exception as e:\n    print('caught')\n")
    assert not r.ok and r.violations


@pytest.mark.parametrize("code,why", [
    ("open('/etc/passwd').read()", "read outside"), ("open('../escape.txt','w').write('x')", "write outside"),
    ("import subprocess; subprocess.run(['ls'])", "subprocess"), ("import pickle; pickle.loads(pickle.dumps(object()))", "pickle"),
    ("import os; os.system('ls')", "os.system")])
def test_sandbox_refusals(code, why):
    r = sandbox.run(code)
    assert not r.ok and any(why in v for v in r.violations), r.violations


def test_sandbox_timeout():
    r = sandbox.run("while True: pass", timeout_s=2)
    assert r.timed_out and not r.ok


def test_sandbox_can_use_allowed_assets():
    r = sandbox.run("from safetensors.numpy import load_file\nprint(len(load_file('data/tiny-mlp/model.safetensors')))",
                    [{"id": "fixture/tiny-mlp", "files": ["model.safetensors"]}])
    assert r.ok and r.answer == "4"
    with pytest.raises(PermissionError):
        sandbox.run("print(1)", [{"id": "someone/else", "files": ["x.csv"]}])
