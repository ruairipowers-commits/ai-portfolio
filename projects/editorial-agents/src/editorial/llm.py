"""The scout's classifier, behind a model registry (MODEL-01), with schema validation (SEC-04), a fallback
(MODEL-05) and a per-run call budget (COST-01).

The model only describes and tags. It never ranks: rank comes from code (signals, novelty, breadth). Its output is
validated against a schema; anything invalid falls back to the deterministic mock, and the topic is flagged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

import yaml

from .config import ROOT, settings

KINDS = ("research", "tool", "practice", "news")
_KIND_BY_SOURCE = {"arxiv": "research", "huggingface_papers": "research", "huggingface_trending": "tool",
                   "hacker_news": "practice", "reddit": "practice", "rss": "news"}


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Result:
    data: dict
    model: str
    latency_ms: int
    fallback: bool = False
    prompt_hash: str = ""


def registry() -> dict:
    return yaml.safe_load((ROOT / "config" / "models.yaml").read_text())


def resolve(alias: str) -> tuple[str, dict]:
    reg = registry()
    name = (os.getenv("EDITORIAL_CLASSIFIER_MODEL") if alias == "classifier" else None) or reg["aliases"][alias]
    spec = reg["models"][name]
    if not spec.get("approved"):
        raise RuntimeError(f"model {name} is not approved in config/models.yaml (SEC-05)")
    return name, spec


def prompt_template() -> str:
    return (ROOT / settings()["classify"]["prompt"]).read_text()


class Classifier:
    def __init__(self, alias: str | None = None, max_calls: int | None = None):
        self.alias = alias or settings()["classify"]["model_alias"]
        self.name, self.spec = resolve(self.alias)
        self.max_calls = max_calls or settings()["cost"]["max_model_calls_per_run"]
        self.calls = 0
        self.sectors = list(settings()["sectors"])

    def classify(self, c: dict) -> Result:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"classifier call budget of {self.max_calls} reached this run")
        self.calls += 1
        tpl = prompt_template()
        prompt = tpl.format(sectors=", ".join(self.sectors), title=c["title"], summary=c.get("summary", "")[:1200],
                            source=c["source"])
        ph = hashlib.sha256(tpl.encode()).hexdigest()[:12]
        t0 = time.time()
        if self.spec["provider"] == "mock":
            return Result(mock_classify(c, self.sectors), self.name, int((time.time() - t0) * 1000), prompt_hash=ph)
        try:
            raw = _ollama(self.spec, prompt)
            data = validate(raw, self.sectors)
            return Result(data, self.name, int((time.time() - t0) * 1000), prompt_hash=ph)
        except Exception:  # noqa: BLE001 — invalid output or model down: deterministic fallback, flagged
            fb_name, _ = resolve("classifier-fallback")
            return Result(mock_classify(c, self.sectors), fb_name, int((time.time() - t0) * 1000), True, ph)


def _ollama(spec: dict, prompt: str) -> str:
    import httpx
    url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    body = {"model": os.getenv("OLLAMA_MODEL") or spec["model_id"], "stream": False, "format": "json",
            "think": False, "options": {"temperature": 0.2, "num_ctx": 4096},
            "messages": [{"role": "user", "content": prompt}]}
    r = httpx.post(f"{url}/api/chat", json=body, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"]


def validate(raw: str, sectors: list[str]) -> dict:
    """SEC-04: the model's JSON is data to check, not to trust."""
    d = json.loads(raw)
    out = {"summary": " ".join(str(d.get("summary", "")).split()[:40]),
           "sectors": [s for s in d.get("sectors", []) if s in sectors][:4],
           "angle": " ".join(str(d.get("angle", "")).split()[:40]),
           "interest": int(d.get("interest", 0)), "kind": d.get("kind")}
    if not out["summary"] or not out["sectors"] or not 1 <= out["interest"] <= 5 or out["kind"] not in KINDS:
        raise ValueError("classifier output failed the schema")
    return out


def mock_classify(c: dict, sectors: list[str]) -> dict:
    """Deterministic stand-in: sectors by keyword, interest by source signals, summary = the source's first sentence."""
    text = f"{c['title']} {c.get('summary', '')}".lower()
    kw = settings()["sectors"]
    hits = sorted(((sum(text.count(k) for k in kw[s]), s) for s in sectors), reverse=True)
    tagged = [s for n, s in hits if n > 0][:4] or ["Information Technology"]
    sig = c.get("signals", {})
    pop = max(float(sig.get("upvotes", 0) or 0), float(sig.get("points", 0) or 0) / 3, float(sig.get("likes", 0) or 0) / 5)
    interest = 2 + (pop >= 20) + (pop >= 100) + any(w in text for w in ("agent", "evaluation", "benchmark", "open-source",
                                                                      "open source", "governance", "fine-tun"))
    first = re.split(r"(?<=[.!?])\s", c.get("summary") or c["title"])[0]
    return {"summary": " ".join(first.split()[:30]), "sectors": tagged,
            "angle": f"Could apply in {', '.join(tagged[:2])}.", "interest": min(5, interest),
            "kind": _KIND_BY_SOURCE.get(c["source"], "news")}
