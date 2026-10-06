"""Provider-agnostic LLM layer: model registry, budgets, retries, fallback.

Controls: MODEL-01 (aliases), MODEL-05 (fallback), COST-01/02 (budgets, attribution),
SEC-05 (approved providers only), SEC-01 (keys only from the environment).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


class BudgetExceeded(RuntimeError):
    pass


class RegistryError(RuntimeError):
    pass


@dataclass
class ModelSpec:
    name: str
    provider: str
    model_id: str
    input_per_mtok: float | None
    output_per_mtok: float | None
    approved: bool = False
    region: str | None = None
    deprecation_date: date | None = None

    def priced(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, in_tok: int, out_tok: int) -> float:
        if not self.priced():
            return 0.0
        return (in_tok * self.input_per_mtok + out_tok * self.output_per_mtok) / 1_000_000


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    model: ModelSpec
    used_fallback: bool = False


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        raw = yaml.safe_load(self.path.read_text())
        self.aliases: dict[str, str] = raw["aliases"]
        self.models: dict[str, ModelSpec] = {}
        for name, m in raw["models"].items():
            dep = m.get("deprecation_date")
            self.models[name] = ModelSpec(
                name=name,
                provider=m["provider"],
                model_id=str(m["model_id"]),
                input_per_mtok=m.get("input_per_mtok"),
                output_per_mtok=m.get("output_per_mtok"),
                approved=bool(m.get("approved", False)),
                region=m.get("region"),
                deprecation_date=date.fromisoformat(str(dep)) if dep else None,
            )

    def resolve(self, alias_or_name: str) -> ModelSpec:
        name = self.aliases.get(alias_or_name, alias_or_name)
        if name not in self.models:
            raise RegistryError(f"Unknown model or alias '{alias_or_name}'")
        spec = self.models[name]
        if not spec.approved:
            raise RegistryError(f"Model '{name}' is not approved for use (SEC-05). Set approved: true after review.")
        return spec

    def set_alias(self, alias: str, model_name: str) -> None:
        """Rewrite one alias line in place so comments in models.yaml survive."""
        if model_name not in self.models:
            raise RegistryError(f"Unknown model '{model_name}'")
        text = self.path.read_text()
        new, n = re.subn(rf"(?m)^(\s+{re.escape(alias)}:\s*)\S+", rf"\g<1>{model_name}", text)
        if n != 1:
            raise RegistryError(f"Alias '{alias}' not found in {self.path}")
        self.path.write_text(new)
        self.aliases[alias] = model_name


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


class Budget:
    def __init__(self, max_usd_per_run: float, max_input_tokens_per_call: int, allow_unpriced: bool = False):
        self.max_usd = max_usd_per_run
        self.max_in = max_input_tokens_per_call
        self.allow_unpriced = allow_unpriced
        self.spent = 0.0

    def preflight(self, spec: ModelSpec, prompt: str, max_out: int) -> None:
        est_in = estimate_tokens(prompt)
        if est_in > self.max_in:
            raise BudgetExceeded(f"Prompt ~{est_in} tokens exceeds per-call cap {self.max_in}")
        if not spec.priced() and not self.allow_unpriced:
            raise BudgetExceeded(
                f"Model '{spec.name}' has no pricing in models.yaml; refusing to run (COST-01)."
            )
        worst = spec.cost(est_in, max_out)
        if self.spent + worst > self.max_usd:
            raise BudgetExceeded(
                f"Run budget ${self.max_usd:.2f} would be exceeded "
                f"(spent ${self.spent:.4f} + worst case ${worst:.4f})"
            )

    def record(self, cost: float) -> None:
        self.spent += cost


# ---------------------------------------------------------------- providers
class MockProvider:
    """Deterministic heuristic 'model' so the project runs offline and CI is free.

    It reads the facts block and applies simple rules; it deliberately does NOT
    know about injection or policy, so the deterministic guardrails downstream
    are exercised exactly as they would be with a real model.
    """

    def complete(self, spec: ModelSpec, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        m = re.search(r"<vendor_facts>\s*(\{.*?\})\s*</vendor_facts>", user, re.S)
        f = json.loads(m.group(1)) if m else {}
        score = f.get("rule_score", 0)
        if f.get("pii_present") and not f.get("license_derived_use"):
            rec, conf = "REJECT", 0.85
        elif not f.get("point_in_time", True):
            rec, conf = "PARK", 0.7
        elif score >= 70 and f.get("days_stale", 99) <= 14:
            rec, conf = "PURSUE", 0.8
        elif score >= 40:
            rec, conf = "PARK", 0.6
        else:
            rec, conf = "REJECT", 0.7
        cite = ["rule_score", "history_years", "pct_tickers_mapped", "null_rate", "days_stale"]
        memo = {
            "vendor_id": f.get("vendor_id", "unknown"),
            "recommendation": rec,
            "confidence": conf,
            "summary": f"{f.get('vendor_name')} ({f.get('category')}): rule score {score}, "
                       f"{f.get('history_years')}y history, {f.get('pct_tickers_mapped')} of tickers mapped.",
            "strengths": [s for s, ok in [
                ("Long history", f.get("history_years", 0) >= 5),
                ("High ticker mapping", f.get("pct_tickers_mapped", 0) >= 0.85),
                ("Fresh delivery", f.get("days_stale", 99) <= 14)] if ok],
            "risks": [s for s, bad in [
                ("PII present without derived-use license", f.get("pii_present") and not f.get("license_derived_use")),
                ("History is not point-in-time (look-ahead risk)", not f.get("point_in_time", True)),
                ("Weak ticker mapping", f.get("pct_tickers_mapped", 1) < 0.7),
                ("Stale delivery", f.get("days_stale", 0) > 14)] if bad],
            "evidence": [{"metric": k, "value": f[k]} for k in cite if k in f],
            "next_steps": ["Human reviewer to confirm recommendation"],
        }
        text = json.dumps(memo)
        return text, estimate_tokens(system + user), estimate_tokens(text)


class AnthropicProvider:
    def complete(self, spec, system, user, max_tokens):
        import anthropic  # pip install '.[anthropic]'

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env (SEC-01)
        resp = client.messages.create(
            model=spec.model_id, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens


class OpenAIProvider:
    def complete(self, spec, system, user, max_tokens):
        from openai import OpenAI  # pip install '.[openai]'

        client = OpenAI()  # reads OPENAI_API_KEY
        resp = client.chat.completions.create(
            model=spec.model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            max_completion_tokens=max_tokens,
        )
        return resp.choices[0].message.content, resp.usage.prompt_tokens, resp.usage.completion_tokens


class BedrockProvider:
    def complete(self, spec, system, user, max_tokens):
        import boto3  # pip install '.[aws]'; uses the standard AWS credential chain

        client = boto3.client("bedrock-runtime", region_name=spec.region or os.getenv("AWS_REGION", "us-east-1"))
        resp = client.converse(
            modelId=spec.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
        return text, resp["usage"]["inputTokens"], resp["usage"]["outputTokens"]


PROVIDERS = {"mock": MockProvider, "anthropic": AnthropicProvider, "openai": OpenAIProvider, "bedrock": BedrockProvider}


class LLMClient:
    def __init__(self, registry: Registry, budget: Budget, retries: int = 2):
        self.registry = registry
        self.budget = budget
        self.retries = retries

    def _call(self, spec: ModelSpec, system: str, user: str, max_tokens: int) -> LLMResult:
        self.budget.preflight(spec, system + user, max_tokens)
        provider = PROVIDERS[spec.provider]()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                t0 = time.perf_counter()
                text, tin, tout = provider.complete(spec, system, user, max_tokens)
                cost = spec.cost(tin, tout)
                self.budget.record(cost)
                return LLMResult(text, tin, tout, cost, int((time.perf_counter() - t0) * 1000), spec)
            except BudgetExceeded:
                raise
            except Exception as e:  # provider/network errors
                last = e
                time.sleep(min(2 ** attempt, 8) if spec.provider != "mock" else 0)
        raise RuntimeError(f"{spec.name} failed after {self.retries + 1} attempts: {last}")

    def complete(self, alias: str, system: str, user: str, max_tokens: int, fallback_alias: str | None = None) -> LLMResult:
        spec = self.registry.resolve(alias)
        try:
            return self._call(spec, system, user, max_tokens)
        except BudgetExceeded:
            raise
        except Exception:
            if not fallback_alias:
                raise
            fb = self.registry.resolve(fallback_alias)
            res = self._call(fb, system, user, max_tokens)
            res.used_fallback = True
            return res
