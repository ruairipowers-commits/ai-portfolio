"""One way to call a model: versioned prompt, delimited request, budget, fallback, schema validation, run log.

SEC-02: untrusted text goes inside <request>…</request> as JSON with '<' and '>' escaped, so it can't close the
delimiter or open a new one. SEC-04: the reply must parse into the Pydantic schema or the call counts as failed.
MODEL-04: the prompt file's hash is logged on every call. OBS-01 / COST-02: one `runs` row per call.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from . import telemetry
from .config import Settings, root
from .llm import Budget, LLMClient, Registry, extract_json
from .store import log_run


@dataclass
class Call:
    value: BaseModel | None
    error: str
    cost_usd: float
    tokens: int
    model: str
    prompt_hash: str


def prompt(name: str) -> tuple[str, str]:
    text = (root() / "prompts" / f"{name}.v1.md").read_text()
    return text, hashlib.sha256(text.encode()).hexdigest()[:12]


def request_block(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    return "<request>\n" + raw.replace("<", "\\u003c").replace(">", "\\u003e") + "\n</request>"


def registry() -> Registry:
    return Registry(root() / "config" / "models.yaml")


def alias_for(role_alias: str) -> str:
    """Env override per role, e.g. COURSE_WRITER_MODEL=local-qwen (a model name or alias)."""
    env = {"course-writer": "COURSE_WRITER_MODEL", "course-moderator": "COURSE_MODERATOR_MODEL",
           "course-reviser": "COURSE_REVISER_MODEL"}.get(role_alias)
    return os.getenv(env) if env and os.getenv(env) else role_alias


def call(conn, s: Settings, action: str, prompt_name: str, alias: str, payload: dict, schema: type[BaseModel],
         budget_usd: float, max_tokens: int, fallback: str | None = None) -> Call:
    system, phash = prompt(prompt_name)
    user = request_block(payload)
    reg = registry()
    budget = Budget(budget_usd, s["cost"]["max_input_tokens_per_call"], s["cost"]["allow_unpriced_models"])
    client = LLMClient(reg, budget)
    telemetry.require_enabled(action)
    alias = alias_for(alias)
    ihash = hashlib.sha256(user.encode()).hexdigest()[:16]
    try:
        res = client.complete(alias, system, user, max_tokens, fallback_alias=fallback)
    except Exception as e:  # budget, provider outage after retries and fallback
        telemetry.record(action, status="failed", flags=["model_error"], detail={"error": type(e).__name__})
        return Call(None, f"{type(e).__name__}: {e}", 0.0, 0, reg.name_of(alias), phash)
    try:
        value = schema.model_validate(extract_json(res.text))
        outcome, err = "ok", ""
    except (ValidationError, ValueError) as e:
        value, outcome, err = None, "invalid", f"reply failed schema validation: {str(e)[:300]}"
    log_run(conn, action, res, alias, phash, ihash, outcome)
    telemetry.record(action, model=res.model.name, input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                     cost_usd=res.cost_usd, latency_ms=res.latency_ms, status="ok" if value else "failed",
                     flags=(["invalid_output"] if not value else []) + (["fallback"] if res.used_fallback else []))
    return Call(value, err, res.cost_usd, res.input_tokens + res.output_tokens, res.model.name, phash)
