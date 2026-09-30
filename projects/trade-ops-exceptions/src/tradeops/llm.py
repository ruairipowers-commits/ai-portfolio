"""Model registry -> LangChain chat models, budgets, fallback; plus the offline scripted mock.

Controls: MODEL-01 aliases, MODEL-05 fallback, SEC-05 approved models only, COST-01/02 budgets.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


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
    approved: bool
    region: str | None = None
    deprecation_date: date | None = None

    def priced(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, tin: int, tout: int) -> float:
        return 0.0 if not self.priced() else (tin * self.input_per_mtok + tout * self.output_per_mtok) / 1e6


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        raw = yaml.safe_load(self.path.read_text())
        self.aliases: dict[str, str] = raw["aliases"]
        self.models = {
            n: ModelSpec(n, m["provider"], str(m["model_id"]), m.get("input_per_mtok"), m.get("output_per_mtok"),
                         bool(m.get("approved")), m.get("region"),
                         date.fromisoformat(str(m["deprecation_date"])) if m.get("deprecation_date") else None)
            for n, m in raw["models"].items()
        }

    def resolve(self, alias: str) -> ModelSpec:
        name = self.aliases.get(alias, alias)
        if name not in self.models:
            raise RegistryError(f"Unknown model or alias '{alias}'")
        spec = self.models[name]
        if not spec.approved:
            raise RegistryError(f"Model '{name}' is not approved for use (SEC-05)")
        return spec

    def set_alias(self, alias: str, model: str) -> None:
        if model not in self.models:
            raise RegistryError(f"Unknown model '{model}'")
        text, n = re.subn(rf"(?m)^(\s+{re.escape(alias)}:\s*)\S+", rf"\g<1>{model}", self.path.read_text())
        if n != 1:
            raise RegistryError(f"Alias '{alias}' not found")
        self.path.write_text(text)


class Budget:
    """Per-exception and per-run spend caps (COST-01)."""

    def __init__(self, per_exception: float, per_run: float, allow_unpriced: bool = False):
        self.per_exception, self.per_run, self.allow_unpriced = per_exception, per_run, allow_unpriced
        self.run_spent = 0.0

    def check(self, spec: ModelSpec, exception_spent: float, est_in: int, max_out: int) -> None:
        if not spec.priced() and not self.allow_unpriced:
            raise BudgetExceeded(f"Model '{spec.name}' has no pricing in models.yaml (COST-01)")
        worst = spec.cost(est_in, max_out)
        if exception_spent + worst > self.per_exception:
            raise BudgetExceeded(f"per-exception budget ${self.per_exception:.2f} would be exceeded")
        if self.run_spent + worst > self.per_run:
            raise BudgetExceeded(f"run budget ${self.per_run:.2f} would be exceeded")


def estimate_tokens(messages: list[BaseMessage]) -> int:
    return sum(len(str(m.content)) + len(json.dumps(getattr(m, "tool_calls", []) or [])) for m in messages) // 4 + 1


def build_chat_model(spec: ModelSpec, max_tokens: int) -> BaseChatModel:
    if spec.provider == "mock":
        return ScriptedInvestigator()
    if spec.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=spec.model_id, max_tokens=max_tokens, temperature=0)
    if spec.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=spec.model_id, max_completion_tokens=max_tokens)
    if spec.provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        return ChatBedrockConverse(model=spec.model_id, region_name=spec.region, max_tokens=max_tokens, temperature=0)
    raise RegistryError(f"Unknown provider {spec.provider}")


# ============================================================ offline scripted investigator
def _next_bday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class ScriptedInvestigator(BaseChatModel):
    """Deterministic stand-in for an LLM. It follows a fixed lookup playbook and simple comparison
    rules, emitting real tool calls so the whole agent loop, MCP server and policy run end to end.
    It deliberately ignores instructions in tool results and knows nothing about policy, so the
    deterministic guardrails are exercised exactly as with a real model. It is NOT a language model."""

    tools: list[str] = []
    PLAYBOOK: tuple[str, ...] = ("get_exception", "get_trade", "get_broker_confirm", "get_allocations",
                                 "get_custodian_record", "get_ssi")

    @property
    def _llm_type(self) -> str:
        return "scripted-investigator"

    def bind_tools(self, tools, **kwargs):
        names = [t.name if hasattr(t, "name") else getattr(t, "__name__", str(t)) for t in tools]
        return self.model_copy(update={"tools": names})

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        ex_id = re.search(r"EX-\d{4}", str(next(m for m in messages if isinstance(m, HumanMessage)).content)).group(0)
        got: dict[str, Any] = {}
        errors: set[str] = set()
        called: list[str] = []
        for m in messages:
            if isinstance(m, ToolMessage):
                called.append(m.name)
                try:
                    data = json.loads(m.content if isinstance(m.content, str) else json.dumps(m.content))
                except ValueError:
                    data = {"error": str(m.content)}
                if isinstance(data, dict) and "error" in data:
                    errors.add(m.name)
                got.setdefault(m.name, data)

        def call(name: str, **args) -> ChatResult:
            msg = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{len(called)}_{name}"}])
            return self._result(msg, messages)

        trade = got.get("get_trade", {})
        for step in self.PLAYBOOK:
            if step in called:
                continue
            if step == "get_exception":
                return call(step, exception_id=ex_id)
            if step == "get_ssi":
                return call(step, counterparty=trade.get("broker", ""))
            return call(step, trade_id=got.get("get_exception", {}).get("trade_id", ""))

        proposal = self._decide(ex_id, got, errors)
        if proposal is None:  # nothing found: keep digging (exercises the step cap)
            cats = ["QUANTITY_MISMATCH", "PRICE_MISMATCH", "SETTLE_DATE_MISMATCH", "SSI_MISMATCH"]
            return call("find_similar_exceptions", category=cats[called.count("find_similar_exceptions") % 4])
        return call("submit_proposal", **proposal)

    def _decide(self, ex_id: str, g: dict, errors: set[str]) -> dict | None:
        t, c, a = g.get("get_trade", {}), g.get("get_broker_confirm", {}), g.get("get_allocations", {})
        cu, s = g.get("get_custodian_record", {}), g.get("get_ssi", {})
        broker = t.get("broker", "")

        def ev(tool, field, value):
            return {"tool": tool, "field": field, "value": value}

        def prop(cat, fix, cause, details, evidence, email=None, conf=0.8):
            return {"exception_id": ex_id, "category": cat, "root_cause": cause, "fix_type": fix,
                    "fix_details": details, "evidence": evidence, "email_draft": email, "confidence": conf}

        def mail(subject, body):
            return {"recipient": broker, "subject": f"{subject} — trade {t.get('trade_id')}", "body": body}

        if "get_custodian_record" in errors:
            dates_differ = c.get("found") and c.get("settle_date") != t.get("settle_date")
            return prop("SETTLE_DATE_MISMATCH" if dates_differ else "UNKNOWN", "ESCALATE",
                        "Custodian record could not be read, so the break cannot be confirmed against the custodian.",
                        "Escalate to ops lead; request a re-send of the custodian record.",
                        [ev("get_trade", "settle_date", t.get("settle_date"))], conf=0.3)
        if not c.get("found"):
            return prop("MISSING_CONFIRM", "CHASE_CONFIRM", f"No confirm received from {broker}.",
                        f"Chase {broker} for confirm/affirmation before cutoff.",
                        [ev("get_broker_confirm", "found", False), ev("get_trade", "broker", broker)],
                        mail("Missing confirm", f"We have not received your confirm for trade {t.get('trade_id')} "
                             f"({t.get('side')} {t.get('quantity')} {t.get('ticker')}). Please send today."))
        if c.get("account_ref") != s.get("account_ref"):
            return prop("SSI_MISMATCH", "REQUEST_BROKER_CORRECTION",
                        "Broker confirm uses settlement instructions that differ from our verified SSI on file.",
                        f"Ask {broker} to settle to SSI on file {s.get('account_ref')}; do not change our SSI.",
                        [ev("get_broker_confirm", "account_ref", c.get("account_ref")),
                         ev("get_ssi", "account_ref", s.get("account_ref"))],
                        mail("SSI correction", f"Please amend settlement instructions to our SSI on file "
                             f"({s.get('account_ref')})."))
        if t.get("quantity") != c.get("quantity"):
            internal = a.get("total_allocated") == c.get("quantity")
            evid = [ev("get_trade", "quantity", t.get("quantity")), ev("get_broker_confirm", "quantity", c.get("quantity")),
                    ev("get_allocations", "total_allocated", a.get("total_allocated"))]
            if internal:
                return prop("QUANTITY_MISMATCH", "AMEND_INTERNAL", "Our booked quantity differs from allocations, confirm and custodian.",
                            f"Amend booked quantity {t.get('quantity')} -> {c.get('quantity')}.", evid)
            return prop("QUANTITY_MISMATCH", "REQUEST_BROKER_CORRECTION", "Broker confirmed a quantity that differs from our booking and allocations.",
                        f"Ask {broker} to correct confirm quantity to {t.get('quantity')}.", evid,
                        mail("Quantity correction", f"Your confirm shows {c.get('quantity')}; our booking and allocations show {t.get('quantity')}. Please correct."))
        if a.get("total_allocated") != t.get("quantity"):
            return prop("ALLOCATION_MISMATCH", "AMEND_INTERNAL", "Sub-account allocations do not sum to the block quantity.",
                        f"Rebalance allocations to total {t.get('quantity')}.",
                        [ev("get_trade", "quantity", t.get("quantity")), ev("get_allocations", "total_allocated", a.get("total_allocated"))])
        if float(t.get("booked_price", 0)) != float(c.get("price", 0)):
            internal = float(t.get("booked_price")) != float(t.get("exec_avg_price"))
            evid = [ev("get_trade", "booked_price", t.get("booked_price")), ev("get_trade", "exec_avg_price", t.get("exec_avg_price")),
                    ev("get_broker_confirm", "price", c.get("price"))]
            if internal:
                return prop("PRICE_MISMATCH", "AMEND_INTERNAL", "Booked price differs from EMS fills; broker price matches fills.",
                            f"Amend booked price {t.get('booked_price')} -> {t.get('exec_avg_price')}.", evid)
            return prop("PRICE_MISMATCH", "REQUEST_BROKER_CORRECTION", "Broker price differs from our fills and booking.",
                        f"Ask {broker} to correct price to {t.get('exec_avg_price')}.", evid,
                        mail("Price correction", f"Your confirm shows {c.get('price')}; average execution price was {t.get('exec_avg_price')}."))
        if t.get("settle_date") != c.get("settle_date"):
            t1 = _next_bday(date.fromisoformat(t["trade_date"])).isoformat()
            evid = [ev("get_trade", "trade_date", t.get("trade_date")), ev("get_trade", "settle_date", t.get("settle_date")),
                    ev("get_broker_confirm", "settle_date", c.get("settle_date"))]
            if t.get("settle_date") != t1:
                return prop("SETTLE_DATE_MISMATCH", "AMEND_INTERNAL", f"Our settle date is not T+1 ({t1}); broker's is.",
                            f"Amend settle date {t.get('settle_date')} -> {t1}.", evid)
            return prop("SETTLE_DATE_MISMATCH", "REQUEST_BROKER_CORRECTION", f"Broker settle date is not T+1 ({t1}).",
                        f"Ask {broker} to correct settle date to {t1}.", evid,
                        mail("Settle date correction", f"Please amend settle date to {t1} (T+1)."))
        return None

    def _result(self, msg: AIMessage, messages: list[BaseMessage]) -> ChatResult:
        tin, tout = estimate_tokens(messages), len(json.dumps(msg.tool_calls)) // 4 + 1
        msg.usage_metadata = {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout}
        return ChatResult(generations=[ChatGeneration(message=msg)])
