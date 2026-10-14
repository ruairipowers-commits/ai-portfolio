"""The comparison log: what each arm made Claude write is computed by code from the files, and the table pairs topics."""
import json

import pytest

from editorial import routing
from editorial.cli import main


def _files(tmp_path, **texts):
    out = {}
    for k, v in texts.items():
        (tmp_path / f"{k}.md").write_text(v)
        out[k] = tmp_path / f"{k}.md"
    return out


def test_changed_chars_counts_only_new_text():
    assert routing.changed_chars("the cat sat on the mat", "the cat sat on the mat") == 0
    assert routing.changed_chars("the cat sat", "the dog sat") == len("dog") + 1
    assert routing.changed_chars("a b", "a b c d") == len("c") + 1 + len("d") + 1


def test_arms_measure_what_claude_wrote(tmp_path):
    body = "word " * 400
    f = _files(tmp_path, final=body + "fixed ending.", local=body + "bad ending.", notes="Fix the ending.",
               src="source text " * 100)
    log = tmp_path / "runs.jsonl"
    c = routing.record("claude-only", "t1", "s", f["final"], review_notes=f["notes"], read=[f["src"]], log=log)
    lr = routing.record("local-review", "t1", "s", f["final"], local_draft=f["local"], review_notes=f["notes"],
                        read=[f["src"], f["local"]], local_model="gpt-oss:20b", local_seconds=81.24, log=log)
    assert c["claude_written_chars"] == len(body + "fixed ending.") + len("Fix the ending.")
    assert lr["claude_written_chars"] == len("Fix the ending.") + len("fixed") + 1
    assert lr["claude_written_tokens_est"] == round(lr["claude_written_chars"] / 4)
    assert lr["local_seconds"] == 81.2 and c["local_model"] == "" and c["local_seconds"] == 0.0
    s = routing.summary(routing.load(log))
    assert s["paired"]["topics"] == 1 and s["paired"]["median_cut"] > 0.9
    md = routing.table_md(routing.load(log))
    assert "Local model drafts, Claude reviews" in md and "characters ÷ 4" in md and "median" in md


def test_local_review_requires_the_local_draft(tmp_path):
    f = _files(tmp_path, final="x")
    with pytest.raises(ValueError):
        routing.record("local-review", "t", "s", f["final"], log=tmp_path / "r.jsonl")
    with pytest.raises(ValueError):
        routing.record("someone-else", "t", "s", f["final"], log=tmp_path / "r.jsonl")


def test_empty_log_says_so(tmp_path):
    assert "No routed runs" in routing.table_md([])


def test_cli_log_and_table(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(routing, "LOG", tmp_path / "runs.jsonl")
    f = _files(tmp_path, final="final text here", local="local text here")
    assert main(["routing", "log", "--arm", "local-review", "--topic", "t9", "--slug", "x", "--final", str(f["final"]),
                 "--local-draft", str(f["local"]), "--local-model", "gpt-oss:20b", "--local-seconds", "12",
                 "--checks-first-pass", "--defects", "2", "--editor-min", "4", "--published"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["defects"] == 2 and row["published"] and row["checks_first_pass"]
    assert main(["routing", "table"]) == 0
    assert "Local model drafts" in capsys.readouterr().out


def test_sent_prompt_and_exact_local_metrics(tmp_path):
    f = _files(tmp_path, final="the final post text", local="the local post text", prompt="P" * 400,
               metrics=json.dumps({"status": "done", "metrics": {"prompt_tokens": 900, "output_tokens": 2100,
                                                                  "total_seconds": 88.0}}))
    row = routing.record("local-review", "t", "s", f["final"], local_draft=f["local"], sent=[f["prompt"]],
                         local_metrics=f["metrics"], local_seconds=999, log=tmp_path / "r.jsonl")
    assert row["claude_sent_chars"] == 400 and row["claude_written_chars"] == 400 + len("final") + 1
    assert (row["local_prompt_tokens"], row["local_output_tokens"], row["local_seconds"]) == (900, 2100, 88.0)
