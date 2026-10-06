"""The one door every model call goes through.

Order, every time: kill switch (governance console) → versioned prompt (MODEL-04) → per-action and per-run budget
(COST-01) → registry alias with fallback (MODEL-01/05) → strict schema parse (SEC-04) → run log row (OBS-01) and
one telemetry event (counts, hashes and flags only — never the text).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from . import store, telemetry
from .config import ROOT, Settings, sha
from .guardrails import parse
from .llm import Budget, BudgetExceeded, LLMClient, Registry

M = TypeVar("M", bound=BaseModel)
SYSTEM = ("You are a careful assistant inside a governed data platform. Follow the task instructions exactly and "
          "return only the JSON requested.")


@dataclass
class CallResult:
    output: BaseModel | None
    ok: bool
    model_name: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    used_fallback: bool = False
    prompt_sha: str = ""
    error: str = ""
    flags: list[str] = field(default_factory=list)
    run_id: str = ""


class Runner:
    """Holds one run's budget so several actions in a run share the cap."""

    def __init__(self, settings: Settings, alias: str | None = None, run_id: str | None = None):
        self.settings = settings
        self.registry = Registry(ROOT / "config" / "models.yaml")
        c = settings["cost"]
        self.budget = Budget(c["max_usd_per_run"], c["max_input_tokens_per_call"], c["allow_unpriced_models"])
        self.client = LLMClient(self.registry, self.budget, settings["llm"]["retries"])
        self.alias = alias or settings["llm"]["primary_alias"]
        self.run_id = run_id or "run-" + uuid.uuid4().hex[:10]

    def prompt(self, key: str, **subs) -> tuple[str, str, str]:
        path = ROOT / self.settings["llm"]["prompts"][key]
        text = path.read_text()
        for k, v in subs.items():
            text = text.replace("{{" + k + "}}", v)
        return text, path.stem, sha(path.read_text())

    def call(self, purpose: str, prompt_key: str, blocks: dict[str, str], schema: type[M], *, actor: str = "",
             customer_id: str | None = None, subject: str = "", flags: list[str] | None = None,
             metric_queries: list[str] | None = None, prompt_subs: dict | None = None) -> CallResult:
        flags = list(flags or [])
        telemetry.require_enabled(purpose, actor=actor)            # raises WorkflowDisabled; nothing runs
        instructions, version, psha = self.prompt(prompt_key, **(prompt_subs or {}))
        user = instructions + "\n\n" + f"<task>\n{prompt_key}\n</task>\n" + "\n".join(
            f"<{k}>\n{v}\n</{k}>" for k, v in blocks.items())
        spec = self.registry.resolve(self.alias)
        cap = self.settings["cost"]["max_usd_per_action"]
        res = CallResult(None, False, spec.name, prompt_sha=psha, run_id=self.run_id, flags=flags)
        status = "ok"
        try:
            spent_before = self.budget.spent
            worst = spec.cost(len(user) // 4 + 1, self.settings["llm"]["max_output_tokens"])
            if worst > cap:
                raise BudgetExceeded(f"Worst-case cost ${worst:.4f} exceeds the per-action cap ${cap:.2f}")
            r = self.client.complete(self.alias, SYSTEM, user, self.settings["llm"]["max_output_tokens"],
                                     fallback_alias=self.settings["llm"]["fallback_alias"])
            res.model_name, res.cost_usd = r.model.name, r.cost_usd
            res.input_tokens, res.output_tokens, res.latency_ms, res.used_fallback = (
                r.input_tokens, r.output_tokens, r.latency_ms, r.used_fallback)
            if r.used_fallback:
                res.flags.append("fallback")
            try:
                res.output, res.ok = parse(schema, r.text), True
            except Exception as e:                                  # SEC-04: off-contract output is rejected
                status, res.error = "schema_invalid", f"{type(e).__name__}: {str(e)[:200]}"
                res.flags.append("schema_invalid")
            assert self.budget.spent - spent_before <= cap + 1e-9
        except BudgetExceeded as e:
            status, res.error = "budget_exceeded", str(e)
            res.flags.append("budget_exceeded")
        except Exception as e:
            status, res.error = "error", f"{type(e).__name__}: {str(e)[:200]}"
        with store.session(self.settings) as s:
            s.add(store.AICall(run_id=self.run_id, purpose=purpose, subject=subject, customer_id=customer_id,
                               actor=actor, alias=self.alias, model_name=res.model_name, provider=spec.provider,
                               model_id=spec.model_id, prompt_version=version, prompt_sha=psha,
                               input_sha=sha(user), context_sha=sha(blocks.get("packet", "") or blocks.get("facts", "")),
                               input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=res.cost_usd,
                               latency_ms=res.latency_ms, used_fallback=res.used_fallback, status=status,
                               flags=sorted(set(res.flags)), metric_queries=metric_queries or [], error=res.error or None))
            s.commit()
        telemetry.emit(purpose, status="ok" if status == "ok" else ("blocked" if status == "budget_exceeded" else "error"),
                       actor=actor or None, model=res.model_name, input_tokens=res.input_tokens,
                       output_tokens=res.output_tokens, cost_usd=res.cost_usd, latency_ms=res.latency_ms,
                       records_in=1, records_out=int(res.ok), flags=res.flags, run_id=self.run_id,
                       detail={"prompt_sha": psha, "subject_sha": sha(subject) if subject else ""})
        return res
