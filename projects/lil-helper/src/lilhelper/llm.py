"""Provider-agnostic LLM layer: model registry, budgets, retries, fallback, image input for flyers.

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
    vision: bool = False

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
                vision=bool(m.get("vision", False)),
            )

    def name_of(self, alias: str) -> str:
        return self.aliases.get(alias, alias)

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
    """Deterministic offline stand-in for the three jobs, so the project runs with no keys and CI is free.

    - suggest (ROLE: suggest): returns recipe ideas for the season from a fixed list (mock.suggest) — one of which
      hides an allergen, as real models sometimes do, so the checks have something to catch.
    - flyer (ROLE: flyer): can't see pixels; reads the text a person would read off the flyer (the .txt next to each
      sample image) line by line (mock.flyer). A real vision model reads the image.
    - notes (ROLE: notes): one templated line per meal from the facts it is given (mock.notes).
    """

    def complete(self, spec: ModelSpec, system: str, user: str, max_tokens: int,
                 images: list[bytes] | None = None) -> tuple[str, int, int]:
        from . import mock
        if "ROLE: suggest" in system:
            text = json.dumps(mock.suggest(_tag_json(user, "household")))
        elif "ROLE: flyer" in system:
            text = json.dumps(mock.flyer(_tag_text(user, "flyer_text")))
        elif "ROLE: notes" in system:
            text = json.dumps(mock.notes(_tag_json(user, "plan")))
        else:
            raise RuntimeError("mock provider: unknown role")
        return text, estimate_tokens(system + user) + 800 * len(images or []), estimate_tokens(text)


def _tag_text(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", text, re.S)
    return m.group(1) if m else ""


def _tag_json(text: str, tag: str) -> dict:
    m = re.search(rf"<{tag}>\s*(\{{.*\}})\s*</{tag}>", text, re.S)
    return json.loads(m.group(1)) if m else {}


class OllamaProvider:
    """A local open model through Ollama's chat API (OLLAMA_URL, default http://localhost:11434), JSON mode."""

    def complete(self, spec, system, user, max_tokens, images=None):
        import base64
        import httpx
        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        um = {"role": "user", "content": user}
        if images:
            um["images"] = [base64.b64encode(b).decode() for b in images]
        body = {"model": os.getenv("OLLAMA_MODEL") or spec.model_id, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system}, um],
                "options": {"temperature": 0.2, "num_predict": max_tokens, "num_ctx": 16384}, "think": False}
        r = httpx.post(f"{url}/api/chat", json=body, timeout=httpx.Timeout(600, connect=5))
        if r.status_code == 400 and "think" in body:          # a model without a thinking switch
            body.pop("think")
            r = httpx.post(f"{url}/api/chat", json=body, timeout=httpx.Timeout(600, connect=5))
        r.raise_for_status()
        d = r.json()
        return d["message"]["content"], d.get("prompt_eval_count", 0), d.get("eval_count", 0)


class AnthropicProvider:
    def complete(self, spec, system, user, max_tokens, images=None):
        import base64
        import anthropic  # pip install '.[anthropic]'

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env (SEC-01)
        content = [{"type": "image", "source": {"type": "base64", "media_type": _mime(b),
                                                "data": base64.b64encode(b).decode()}} for b in images or []]
        content.append({"type": "text", "text": user})
        resp = client.messages.create(
            model=spec.model_id, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens


class OpenAIProvider:
    def complete(self, spec, system, user, max_tokens, images=None):
        import base64
        from openai import OpenAI  # pip install '.[openai]'

        client = OpenAI()  # reads OPENAI_API_KEY
        content = [{"type": "image_url", "image_url": {"url": f"data:{_mime(b)};base64,{base64.b64encode(b).decode()}"}}
                   for b in images or []] + [{"type": "text", "text": user}]
        resp = client.chat.completions.create(
            model=spec.model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            response_format={"type": "json_object"},
            max_completion_tokens=max_tokens,
        )
        return resp.choices[0].message.content, resp.usage.prompt_tokens, resp.usage.completion_tokens


class BedrockProvider:
    def complete(self, spec, system, user, max_tokens, images=None):
        import boto3  # pip install '.[aws]'; uses the standard AWS credential chain

        client = boto3.client("bedrock-runtime", region_name=spec.region or os.getenv("AWS_REGION", "us-east-1"))
        content = [{"image": {"format": _mime(b).split("/")[1], "source": {"bytes": b}}} for b in images or []]
        content.append({"text": user})
        resp = client.converse(
            modelId=spec.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
        return text, resp["usage"]["inputTokens"], resp["usage"]["outputTokens"]


def _mime(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


PROVIDERS = {"mock": MockProvider, "ollama": OllamaProvider, "anthropic": AnthropicProvider,
             "openai": OpenAIProvider, "bedrock": BedrockProvider}


class LLMClient:
    def __init__(self, registry: Registry, budget: Budget, retries: int = 2):
        self.registry = registry
        self.budget = budget
        self.retries = retries

    def _call(self, spec: ModelSpec, system: str, user: str, max_tokens: int,
              images: list[bytes] | None = None) -> LLMResult:
        if images and not spec.vision and spec.provider != "mock":
            raise RegistryError(f"Model '{spec.name}' can't read images; point the vision alias at one that can.")
        self.budget.preflight(spec, system + user, max_tokens)
        provider = PROVIDERS[spec.provider]()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                t0 = time.perf_counter()
                text, tin, tout = provider.complete(spec, system, user, max_tokens, images=images)
                cost = spec.cost(tin, tout)
                self.budget.record(cost)
                return LLMResult(text, tin, tout, cost, int((time.perf_counter() - t0) * 1000), spec)
            except BudgetExceeded:
                raise
            except Exception as e:  # provider/network errors
                last = e
                time.sleep(min(2 ** attempt, 8) if spec.provider != "mock" else 0)
        raise RuntimeError(f"{spec.name} failed after {self.retries + 1} attempts: {last}")

    def complete(self, alias: str, system: str, user: str, max_tokens: int, fallback_alias: str | None = None,
                 images: list[bytes] | None = None) -> LLMResult:
        spec = self.registry.resolve(alias)
        try:
            return self._call(spec, system, user, max_tokens, images)
        except (BudgetExceeded, RegistryError):
            raise
        except Exception:
            if not fallback_alias:
                raise
            fb = self.registry.resolve(fallback_alias)
            res = self._call(fb, system, user, max_tokens, images)
            res.used_fallback = True
            return res


def extract_json(text: str) -> dict:
    """The first JSON object in a model's reply (models sometimes wrap it in a code fence or a sentence)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = t.find("{")
        depth = 0
        for i in range(start, len(t)) if start >= 0 else []:
            depth += {"{": 1, "}": -1}.get(t[i], 0)
            if depth == 0:
                return json.loads(t[start:i + 1])
        raise ValueError("no JSON object in the model's reply")
