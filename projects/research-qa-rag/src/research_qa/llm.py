"""Provider-agnostic model layer: registry (answer + embedding models), budgets, retries, fallback.

Controls: MODEL-01 (aliases), MODEL-05 (fallback), COST-01/02 (budgets, attribution),
SEC-05 (approved providers only), SEC-01 (keys only from the environment).
"""
from __future__ import annotations

import hashlib
import json
import math
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
    kind: str = "chat"              # chat | embedding
    dimensions: int | None = None   # embeddings only

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
                kind=m.get("kind", "chat"),
                dimensions=m.get("dimensions"),
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
STOP = set("""a an the of in on at to for from by with and or is are was were be been do does did what which who whom
how much many when where why whose this that these those it its as their there than about into over under per vs
say says said report reported reports give gave given company companies tell me please current latest""".split())


def tokens(text: str) -> list[str]:
    """Lower-cased content words with light stemming (shared by the mock answerer and the support check)."""
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9&-]*|\d[\d,.]*", text.replace("’", "'")):
        w = w.lower().rstrip(".,").removesuffix("'s").removesuffix("'")
        w = w.replace(",", "")
        if w in STOP or len(w) < 2 and not w.isdigit():
            continue
        if not w[0].isdigit():
            if w.endswith("ies") and len(w) > 4:
                w = w[:-3] + "y"
            elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
                w = w[:-1]
            elif w.endswith("ed") and len(w) > 5:
                w = w[:-2]
        out.append(w)
    return out


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z$\d])", re.sub(r"\s+", " ", text).strip())
    return [p for p in parts if len(p.split()) >= 4]


class MockProvider:
    """Deterministic *extractive* stand-in for an LLM, so the project runs offline and CI is free.

    It reads the question and the excerpts from the prompt, picks the single sentence that covers the most
    question terms (the excerpt's company and source count as context), and refuses when nothing covers
    enough of the question or a named entity in the question appears in no excerpt. It never writes text of
    its own, and it ignores any instructions in the excerpts — so injection defences are exercised by the
    deterministic screens, not by this model.
    """

    MIN_COVERAGE = 0.6

    def complete(self, spec: ModelSpec, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        q = re.search(r"<question>(.*?)</question>", user, re.S)
        question = q.group(1).strip() if q else ""
        excerpts = re.findall(r'<excerpt id="([^"]+)" meta="([^"]*)">(.*?)</excerpt>', user, re.S)
        q_terms = set(tokens(question))
        names = {w.lower().removesuffix("'s") for w in re.findall(r"(?<!^)\b[A-Z][A-Za-z0-9&-]+", question)}
        best, best_key = None, (0.0, 0, 0)
        for rank, (cid, meta, text) in enumerate(excerpts):
            context = set(tokens(meta)) | set(tokens(text))
            if any(n.lower() not in " ".join(context) for n in {t for n in names for t in tokens(n)}):
                continue   # a company / broker named in the question isn't in this excerpt
            for s in sentences(text):
                in_sentence = q_terms & set(tokens(s))
                covered = in_sentence | (q_terms & set(tokens(meta)))
                coverage = len(covered) / max(len(q_terms), 1)
                non_name = in_sentence - {t for n in names for t in tokens(n)}
                key = (round(coverage, 3), len(in_sentence), -rank)
                if coverage >= self.MIN_COVERAGE and non_name and key > best_key:
                    best, best_key = (cid, s), key
        if best:
            out = {"answer": best[1], "citations": [{"chunk_id": best[0], "quote": best[1]}],
                   "refused": False, "refusal_reason": ""}
        else:
            out = {"answer": "", "citations": [], "refused": True,
                   "refusal_reason": "The documents available to you do not answer this question."}
        text = json.dumps(out)
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


# ---------------------------------------------------------------- embeddings
class MockEmbedder:
    """Offline embedding: signed feature hashing of words and character 4-grams, L2-normalised.

    Lexical rather than semantic — it catches word-form variants that BM25's tokenizer misses, but not synonyms.
    Swap in a real model by pointing `embed-primary` at it (requires a full re-index)."""

    def embed(self, spec: ModelSpec, texts: list[str]) -> tuple[list[list[float]], int]:
        dim = spec.dimensions or 384
        out = []
        for t in texts:
            v = [0.0] * dim
            words = tokens(t)
            feats = words + [w[i:i + 4] for w in words if len(w) > 4 for i in range(len(w) - 3)]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                v[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out, sum(estimate_tokens(t) for t in texts)


class OpenAIEmbedder:
    def embed(self, spec, texts):
        from openai import OpenAI  # pip install '.[openai]'

        resp = OpenAI().embeddings.create(model=spec.model_id, input=texts, dimensions=spec.dimensions)
        return [d.embedding for d in resp.data], resp.usage.prompt_tokens


class BedrockEmbedder:
    def embed(self, spec, texts):
        import boto3  # pip install '.[aws]'

        client = boto3.client("bedrock-runtime", region_name=spec.region or os.getenv("AWS_REGION", "us-east-1"))
        vecs, tok = [], 0
        for t in texts:
            body = json.dumps({"inputText": t, "dimensions": spec.dimensions, "normalize": True})
            r = json.loads(client.invoke_model(modelId=spec.model_id, body=body)["body"].read())
            vecs.append(r["embedding"])
            tok += r.get("inputTextTokenCount", 0)
        return vecs, tok


EMBEDDERS = {"mock": MockEmbedder, "openai": OpenAIEmbedder, "bedrock": BedrockEmbedder}


def embed(registry: "Registry", alias: str, texts: list[str]) -> tuple[list[list[float]], int, ModelSpec]:
    spec = registry.resolve(alias)
    if spec.kind != "embedding":
        raise RegistryError(f"'{alias}' resolves to {spec.name}, which is not an embedding model")
    vecs, tok = EMBEDDERS[spec.provider]().embed(spec, texts)
    return vecs, tok, spec
