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

ROOT = Path(__file__).resolve().parents[2]
INJECTION = re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|rules)|system prompt|you are now|"
                       r"disregard (the|your) (rules|instructions)|jailbreak", re.I)


def model_config(alias: str = "chat") -> dict:
    reg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())
    m = dict(reg["models"][reg["aliases"].get(alias, alias)])
    if m["provider"] == "ollama" and os.getenv("OLLAMA_MODEL"):
        m["model"] = os.environ["OLLAMA_MODEL"]
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


def build_messages(question: str, passages: list[dict], history: list[dict]) -> list[dict]:
    system = (ROOT / "prompts" / "answer.md").read_text()
    blocks = []
    for i, p in enumerate(passages, 1):   # excerpts are data: delimited, with their source
        blocks.append(f"<excerpt n=\"{i}\" page=\"{p['page_title']}\" section=\"{p.get('section') or ''}\">\n"
                      f"{p['text']}\n</excerpt>")
    msgs = [{"role": "system", "content": system}]
    for h in history:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:1500]})
    msgs.append({"role": "user", "content": "Excerpts from the blog:\n\n" + "\n\n".join(blocks) +
                 f"\n\nQuestion: {question}"})
    return msgs


def extractive(question: str, passages: list[dict]) -> Iterator[str | dict]:
    """No model: quote the two best passages, with their citations."""
    if not passages:
        yield "The blog doesn't cover that — try different words, or browse the Technologies and Blog pages."
        yield {"model": "extractive-v1", "input_tokens": 0, "output_tokens": 0, "status": "refused"}
        return
    yield "The local model isn't available right now, so here are the most relevant passages:\n\n"
    for i, p in enumerate(passages[:2], 1):
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
            "options": {"temperature": settings["chat"]["temperature"],
                        "num_predict": settings["chat"]["max_answer_tokens"]}}
    tin = tout = 0
    try:
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
        yield {"model": m["model"], "input_tokens": tin, "output_tokens": tout, "status": "ok"}
    except Exception as e:  # noqa: BLE001 — a model failure degrades to quotes, never to an error page
        yield f"\n\n(The model stopped: {type(e).__name__}. Showing passages instead.)\n\n"
        yield from extractive(question, passages)


def time_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
