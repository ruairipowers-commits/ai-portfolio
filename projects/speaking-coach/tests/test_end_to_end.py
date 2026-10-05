"""Offline end to end: every sample through the CLI, then the eval gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def coach(*args, cwd: Path):
    return subprocess.run([sys.executable, "-m", "speakingcoach", *args], cwd=cwd, capture_output=True, text=True,
                          env={**__import__("os").environ, "SPEAKINGCOACH_ROOT": str(cwd)}, timeout=300)


def _copy(tmp_path: Path) -> Path:
    import shutil
    for d in ("config", "prompts", "evals", "samples", "scripts"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def test_all_samples_and_eval_gate(tmp_path):
    root = _copy(tmp_path)
    r = coach("all", cwd=root)
    assert r.returncode == 0, r.stderr
    assert "interview-answer: grade F" in r.stdout and "clean-control: grade A" in r.stdout
    assert (root / "output" / "interview-answer.report.html").exists()
    md = (root / "output" / "interview-answer.report.md").read_text()
    assert "Said more cleanly" in md
    e = coach("eval", cwd=root)
    assert e.returncode == 0, e.stdout + e.stderr
    assert "EVAL GATE: PASS" in e.stdout


def test_word_list_only_preview(tmp_path):
    root = _copy(tmp_path)
    r = coach("analyze", "--words", "samples/word-lists/my-meeting-habits.txt", "--presets", "", cwd=root)
    assert r.returncode == 0, r.stderr
    assert "opener: counted only when it starts a sentence" in r.stdout
    assert (root / "output" / "word-list.txt").exists()


def test_promote_refuses_without_eval(tmp_path):
    root = _copy(tmp_path)
    r = coach("promote", "coach-disambiguator", "local-qwen", cwd=root)
    assert r.returncode != 0 and "no passing eval" in (r.stderr + r.stdout)
