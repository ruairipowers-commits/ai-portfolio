"""Answering: a local model through Ollama, or an extractive fallback when no model is reachable.

Both stream: `answer()` yields text pieces and finally a dict with model, token counts and status. The fallback
never generates text — it quotes the best-matching passages — so the service (and CI) works with no model at all.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Iterator

import httpx
import yaml

from .index import is_about_person

ROOT = Path(__file__).resolve().parents[2]
INJECTION = re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|rules)|system prompt|you are now|"
                       r"disregard (the|your) (rules|instructions)|jailbreak", re.I)


def model_config(alias: str = "chat") -> dict:
    reg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())
    m = dict(reg["models"][reg["aliases"].get(alias, alias)])
    if m["provider"] == "ollama" and os.getenv("OLLAMA_MODEL"):
        m["model"] = os.environ["OLLAMA_MODEL"]
        m.pop("think", None)                     # a different model: its thinking setting comes from OLLAMA_THINK
    if m["provider"] == "ollama" and os.getenv("OLLAMA_THINK", "").lower() in ("true", "false"):
        m["think"] = os.environ["OLLAMA_THINK"].lower() == "true"
    return m


def ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "").rstrip("/")


def ollama_ready(model: str) -> bool:
    if not ollama_url():
        return False
    try:
        tags = httpx.get(f"{ollama_url()}/api/tags", timeout=3).json().get("models", [])
        return any(t.get("name") == model or t.get("model") == model for t in tags)
    except Exception:  # noqa: BLE001
        return False


def pull_in_background(model: str) -> threading.Thread | None:
    """First start on a new machine: fetch the model (several GB) without blocking the service."""
    if not ollama_url() or ollama_ready(model):
        return None

    def run():
        try:
            httpx.post(f"{ollama_url()}/api/pull", json={"model": model, "stream": False}, timeout=None)
        except Exception as e:  # noqa: BLE001
            print(f"ollama pull {model} failed: {e}")
    t = threading.Thread(target=run, daemon=True, name="ollama-pull")
    t.start()
    return t


def _excerpt(n: int, p: dict) -> str:
    attrs = f'n="{n}" page="{p["page_title"]}" section="{p.get("section") or ""}"'
    if p.get("date"):
        attrs += f' date="{p["date"]}" type="{p.get("kind", "")}"'
    return f"<excerpt {attrs}>\n{p['text']}\n</excerpt>"


def system_prompt(passages: list[dict]) -> str:
    """The rules, then the profile card as excerpt [1]. Both are identical on every request until the site changes,
    so Ollama reuses the cached prefix and only has to read the question and the search results."""
    system = (ROOT / "prompts" / "answer.md").read_text()
    card = next((p for p in passages if p.get("profile")), None)
    return system + ("\n\nProfile card (excerpt [1]):\n" + _excerpt(1, card) if card else "")


def build_messages(question: str, passages: list[dict], history: list[dict], today: str | None = None) -> list[dict]:
    import datetime as dt
    msgs = [{"role": "system", "content": system_prompt(passages)}]
    for h in history:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:1500]})
    blocks = [_excerpt(i, p) for i, p in enumerate(passages, 1) if not p.get("profile")]  # excerpts are data
    today = today or dt.date.today().isoformat()
    tail = PERSON_CHECKLIST if is_about_person(question) else ""
    msgs.append({"role": "user", "content": f"Today is {today}. Excerpts from the site:\n\n" + "\n\n".join(blocks) +
                 f"\n\nQuestion: {question}" + tail})
    return msgs


# Small local models follow the last instructions they read best, so questions about Ruairi end with a short
# checklist (the system prompt stays identical for every question, which keeps its cached prefix valid).
PERSON_CHECKLIST = """

Before you answer this question about Ruairi, check:
- Spell his name exactly "Ruairi".
- Every claim has a citation. Name the specific roles, MIT courses and projects (with dates) that show it.
- Only something the excerpts state counts as evidence. A related fact (a library written in another language,
  a cloud service described as an optional path) is not experience. Say what is built versus documented as an option.
- For each thing asked about that the excerpts don't show, write exactly this, filling in the topic:
  "Thank you for asking about <topic>! The site doesn't show <topic> yet. Ruairi is excited to hear more about
  what he may not know and sees it as a chance to grow, so it's now on Ruairi's plate to review — he's encouraged
  to learn new things."
- End by pointing to the About page and his resume."""


def warm_up(settings: dict, passages: list[dict]) -> None:
    """Load the model and pre-read the system prompt (rules + profile card) so the first visitor doesn't wait for it.
    Called at start-up and whenever the profile card changes."""
    m = model_config(settings["chat"]["model_alias"])
    if m["provider"] != "ollama" or not ollama_ready(m["model"]):
        return
    body = {"model": m["model"], "stream": False, "keep_alive": settings["chat"].get("keep_alive", "24h"),
            "messages": [{"role": "system", "content": system_prompt(passages)},
                         {"role": "user", "content": "Reply with OK."}],
            "options": {**_options(settings, m), "num_predict": 1}}
    if "think" in m:
        body["think"] = m["think"]
    try:
        httpx.post(f"{ollama_url()}/api/chat", json=body, timeout=httpx.Timeout(600, connect=5))
    except Exception as e:  # noqa: BLE001
        print(f"warm-up failed: {e}")


def _options(settings: dict, m: dict) -> dict:
    c = settings["chat"]
    opts = {"temperature": m.get("temperature", c["temperature"]), "num_predict": c["max_answer_tokens"],
            "num_ctx": c.get("num_ctx", 8192)}
    if os.getenv("OLLAMA_NUM_THREAD"):
        opts["num_thread"] = int(os.environ["OLLAMA_NUM_THREAD"])
    return opts


def extractive(question: str, passages: list[dict]) -> Iterator[str | dict]:
    """No model: quote the two best passages, with their citations (the profile card only if nothing else matched)."""
    numbered = list(enumerate(passages, 1))
    best = [(i, p) for i, p in numbered if not p.get("profile")] or numbered
    if not passages:
        yield "The blog doesn't cover that — try different words, or browse the Technologies and Blog pages."
        yield {"model": "extractive-v1", "input_tokens": 0, "output_tokens": 0, "status": "refused"}
        return
    yield "The local model isn't available right now, so here are the most relevant passages:\n\n"
    for i, p in best[:2]:
        sent = " ".join(p["text"].split()[:60])
        yield f"> {sent}… [{i}]\n\n"
    yield {"model": "extractive-v1", "input_tokens": 0, "output_tokens": 0, "status": "fallback"}


def answer(question: str, passages: list[dict], history: list[dict], settings: dict) -> Iterator[str | dict]:
    m = model_config(settings["chat"]["model_alias"])
    if m["provider"] != "ollama" or not ollama_ready(m["model"]):
        yield from extractive(question, passages)
        return
    if not passages:
        yield "The blog doesn't cover that — try different words, or browse the Technologies and Blog pages."
        yield {"model": m["model"], "input_tokens": 0, "output_tokens": 0, "status": "refused"}
        return
    body = {"model": m["model"], "messages": build_messages(question, passages, history), "stream": True,
            "keep_alive": settings["chat"].get("keep_alive", "24h"), "options": _options(settings, m)}
    if "think" in m:            # reasoning models: answer directly (much faster); set per model in models.yaml
        body["think"] = m["think"]
    tin = tout = 0
    timing: dict = {}
    try:
        with httpx.stream("POST", f"{ollama_url()}/api/chat", json=body, timeout=httpx.Timeout(120, connect=5)) as r:
            if r.status_code == 400 and "think" in body:     # a model without a thinking switch: ask again without it
                r.read()
                body.pop("think")
                yield from _stream_again(body, m)
                return
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                piece = (d.get("message") or {}).get("content", "")
                if piece:
                    yield piece
                if d.get("done"):
                    tin, tout = d.get("prompt_eval_count", 0), d.get("eval_count", 0)
                    timing = _timing(d)
        yield {"model": m["model"], "input_tokens": tin, "output_tokens": tout, "status": "ok", **timing}
    except Exception as e:  # noqa: BLE001 — a model failure degrades to quotes, never to an error page
        yield f"\n\n(The model stopped: {type(e).__name__}. Showing passages instead.)\n\n"
        yield from extractive(question, passages)


def _timing(d: dict) -> dict:
    """Ollama's own timings (nanoseconds) → seconds: model load, reading the prompt, writing the answer."""
    return {k: round(d.get(f"{k}_duration", 0) / 1e9, 3) for k in ("load", "prompt_eval", "eval")}


def _stream_again(body: dict, m: dict) -> Iterator[str | dict]:
    tin = tout = 0
    timing: dict = {}
    with httpx.stream("POST", f"{ollama_url()}/api/chat", json=body, timeout=httpx.Timeout(120, connect=5)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            piece = (d.get("message") or {}).get("content", "")
            if piece:
                yield piece
            if d.get("done"):
                tin, tout = d.get("prompt_eval_count", 0), d.get("eval_count", 0)
                timing = _timing(d)
    yield {"model": m["model"], "input_tokens": tin, "output_tokens": tout, "status": "ok", **timing}


def time_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
