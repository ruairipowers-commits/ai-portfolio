"""The three model jobs, each wrapped in code checks. A model's output is data: schema-validated, mapped onto the
catalog, run through the safety rules, and (for specials) confirmed by a person before it counts (SEC-04)."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from . import safety, store
from .catalog import Catalog, Recipe
from .config import ROOT, Household, Settings
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError, extract_json


# ---------------------------------------------------------------- schemas
class SuggestedRecipe(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    meal: str
    active: int = Field(ge=1, le=240)
    total: int = Field(ge=1, le=600)
    veg: float = Field(ge=0, le=6)
    protein: int = Field(ge=0, le=120)
    tags: list[str] = []
    ing: dict[str, float]
    why: str = Field(default="", max_length=200)


class Suggestions(BaseModel):
    recipes: list[SuggestedRecipe]


class FlyerItem(BaseModel):
    text: str = Field(max_length=160)
    price: str = Field(max_length=40)


class FlyerRead(BaseModel):
    store: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    items: list[FlyerItem] = []
    other: list[str] = []


class Note(BaseModel):
    day: str
    meal: str
    note: str = Field(max_length=140)


class Notes(BaseModel):
    notes: list[Note]


@dataclass
class Call:
    job: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    prompt_sha: str
    ok: bool
    fallback: bool = False
    error: str = ""


@dataclass
class AIContext:
    s: Settings
    client: LLMClient
    calls: list[Call] = field(default_factory=list)

    @classmethod
    def make(cls, s: Settings, alias_overrides: dict[str, str] | None = None) -> "AIContext":
        reg = Registry(ROOT / "config" / "models.yaml")
        for k, v in (alias_overrides or {}).items():
            reg.aliases[k] = v
        if s["privacy"].get("local_only"):
            for a, name in reg.aliases.items():
                if reg.models[name].provider not in ("mock", "ollama"):
                    raise RegistryError(f"local_only is on: alias {a} points at {name} ({reg.models[name].provider})")
        b = Budget(s["cost"]["max_usd_per_run"], s["cost"]["max_input_tokens_per_call"],
                   s["cost"].get("allow_unpriced_models", False))
        return cls(s, LLMClient(reg, b, s["llm"]["retries"]))

    def prompt(self, job: str) -> str:
        return (ROOT / self.s["llm"]["prompts"][job]).read_text()

    def ask(self, job: str, alias_key: str, user: str, images: list[bytes] | None = None) -> dict | None:
        system = self.prompt(job)
        alias = self.s["llm"][alias_key]
        try:
            res = self.client.complete(alias, system, user, self.s["llm"]["max_output_tokens"],
                                       fallback_alias=self.s["llm"]["fallback_alias"], images=images)
        except (BudgetExceeded, RegistryError) as e:
            self.calls.append(Call(job, alias, 0, 0, 0.0, 0, store.sha(system), False, error=str(e)[:200]))
            return None
        except Exception as e:
            self.calls.append(Call(job, alias, 0, 0, 0.0, 0, store.sha(system), False, error=type(e).__name__))
            return None
        self.calls.append(Call(job, res.model.name, res.input_tokens, res.output_tokens, res.cost_usd, res.latency_ms,
                               store.sha(system), True, res.used_fallback))
        try:
            return extract_json(res.text)
        except Exception:
            self.calls[-1].ok = False
            self.calls[-1].error = "not_json"
            return None

    @property
    def cost(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)


# ---------------------------------------------------------------- 1. recipe ideas
@dataclass
class IdeaResult:
    accepted: list[Recipe]
    rejected: list[dict]
    flags: list[str]


def suggest_recipes(ctx: AIContext, h: Household, c: Catalog, month: int, specials: list[str]) -> IdeaResult:
    share = ctx.s["privacy"]["share_names_with_model"]
    eaters = h.eaters("dinner")
    household = {"month": month, "region": h.info.get("region"), "count": h.raw.get("suggestions", {}).get("per_week", 2),
                 "eaters": [{"who": p.label(share), "allergies": p.allergies, "diet": p.diet} for p in eaters],
                 "weeknight_prep_minutes": min(h.prep_limit(d) for d in ("mon", "tue", "wed", "thu")),
                 "on_special": specials[:20], "already_have": sorted(r.name for r in c.recipes.values())[:60]}
    cat = {iid: ing.unit for iid, ing in c.ingredients.items() if ing.cat != "pet"}
    user = (f"<household>\n{json.dumps(household)}\n</household>\n<catalog>\n{json.dumps(cat)}\n</catalog>")
    raw = ctx.ask("suggest", "suggest_alias", user)
    if raw is None:
        return IdeaResult([], [], ["model_error"])
    try:
        sugg = Suggestions.model_validate(raw)
    except ValidationError:
        return IdeaResult([], [], ["schema_invalid"])
    acc, rej, flags = [], [], []
    limit = max(h.prep_limit(d) for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
    want = int(household["count"])
    for sr in sugg.recipes:
        reasons = []
        text = " ".join([sr.name, sr.why] + list(sr.ing))
        if safety.looks_like_instruction(text):
            reasons.append("contains instructions")
            flags.append("instruction_in_output")
        unknown = [i for i in sr.ing if i not in c.ingredients]
        if unknown:
            reasons.append(f"ingredients not in the catalog: {', '.join(unknown)}")
        if sr.meal not in ("breakfast", "lunch", "dinner"):
            reasons.append("unknown meal")
        if sr.active > limit:
            reasons.append(f"{sr.active} min hands-on is longer than any day allows")
        if any(r.name.lower() == sr.name.lower() for r in c.recipes.values()):
            reasons.append("already in the recipe book")
        rid = "sugg_" + re.sub(r"[^a-z0-9]+", "_", sr.name.lower()).strip("_")[:40]
        r = Recipe(rid, sr.name, sr.meal, sr.active, sr.total, {k: v for k, v in sr.ing.items() if k in c.ingredients},
                   sr.veg, sr.protein, [t for t in sr.tags if t in KNOWN_TAGS], [], "suggested")
        if not unknown:
            v = safety.recipe_for(c, r, eaters)
            if not v.ok:
                reasons += v.reasons
        if reasons:
            rej.append({"name": sr.name, "why": sorted(set(reasons))})
        elif len(acc) < want:
            acc.append(r)
    return IdeaResult(acc, rej, sorted(set(flags)))


KNOWN_TAGS = {"vegetarian", "kid_friendly", "batch", "leftovers", "fried", "processed", "sheet_pan", "one_pot",
              "slow_cooker"}


# ---------------------------------------------------------------- 2. flyers → specials
NUM = re.compile(r"(\d+(?:\.\d+)?)")


@dataclass
class FlyerResult:
    store: str
    items: list[dict]
    flags: list[str]
    other: list[str]


def _price(p: str) -> float | None:
    m = re.search(r"(\d+)\s*for\s*\$\s?(\d+(?:\.\d{1,2})?)", p, re.I)
    if m:
        return round(float(m.group(2)) / int(m.group(1)), 2)
    m = re.search(r"\$\s?(\d+(?:\.\d{1,2})?)", p)
    return float(m.group(1)) if m else None


def read_flyer(ctx: AIContext, h: Household, c: Catalog, pb, store_id: str, *, image: bytes | None = None,
               text: str | None = None) -> FlyerResult:
    """A photo or PDF page (vision model), or text a person typed/pasted. Every item comes back unconfirmed."""
    user = f"Store: {pb.store_cfg.get(store_id, {}).get('name', store_id)}\n"
    if text is not None:
        user += f"<flyer_text>\n{text}\n</flyer_text>"
    raw = ctx.ask("flyer", "vision_alias", user, images=[image] if image else None)
    if raw is None:
        return FlyerResult(store_id, [], ["model_error"], [])
    try:
        fr = FlyerRead.model_validate(raw)
    except ValidationError:
        return FlyerResult(store_id, [], ["schema_invalid"], [])
    flags = []
    other = [o for o in fr.other]
    if any(safety.looks_like_instruction(o) for o in other + [i.text for i in fr.items]):
        flags.append("instruction_on_flyer")
    ratio = float(ctx.s["shopping"]["typo_special_ratio"])
    allergic = {a for p in h.people.values() for a in p.allergies}
    out = []
    for it in fr.items:
        row = {"text": it.text, "price_text": it.price, "store": store_id, "ingredient": None, "price": _price(it.price),
               "regular": None, "status": "needs_confirm", "why": []}
        if safety.looks_like_instruction(it.text):
            row["status"], row["why"] = "ignored", ["looks like an instruction, not a product"]
            out.append(row)
            continue
        iid = c.match(it.text)
        if not iid:
            row["status"], row["why"] = "unmatched", ["not an ingredient Lil'Helper plans with"]
            out.append(row)
            continue
        row["ingredient"] = iid
        extra = re.sub(re.escape(c.ingredients[iid].name), "", it.text, flags=re.I)
        if re.search(r"\b(cookies?|bars?|chips|cereal|candy|cake|crackers)\b", extra, re.I):
            row["why"].append(f"may not be plain {c.ingredients[iid].name} — check before confirming")
        hit = set(c.allergens_of(Recipe("x", it.text, "dinner", 0, 0, {iid: 1})).keys()) & allergic
        if hit:
            row["why"].append(f"contains {', '.join(sorted(hit))} — someone in the house is allergic")
            row["status"] = "not_for_us"
        regs = [o for o in pb.shelf.get(store_id, {}).get(iid, [])]
        if regs and row["price"] is not None:
            reg = regs[0]
            unit_txt = c.ingredients[iid].unit
            per_unit = bool(re.search(rf"\b(per|/)\s*{unit_txt}\b|\beach\b", it.text, re.I))
            n = NUM.search(re.sub(r"\$\s?\d+(?:\.\d+)?", "", it.text))
            qty = float(n.group(1)) if (n and not per_unit and re.search(rf"\d\s*{unit_txt}", it.text, re.I)) else None
            unit_price = row["price"] if per_unit else (row["price"] / qty if qty else row["price"] / float(reg["pack"]))
            reg_unit = float(reg["price"]) / float(reg["pack"])
            row["regular"] = round(reg_unit * float(reg["pack"]), 2)
            row["pack"] = float(reg["pack"])
            row["unit_price"] = round(unit_price, 3)
            row["sale_pack_price"] = round(unit_price * float(reg["pack"]), 2)
            if unit_price < ratio * reg_unit:
                row["status"] = "flagged"
                row["why"].append(f"${unit_price:.2f}/{unit_txt} is under {int(ratio * 100)}% of the usual "
                                  f"${reg_unit:.2f} — likely a misprint; check before it counts")
            elif unit_price >= reg_unit:
                row["why"].append("not cheaper than the usual price")
                row["status"] = "no_saving"
        elif not regs:
            row["why"].append(f"{pb.store_cfg.get(store_id, {}).get('name', store_id)} isn't on file as selling this")
        out.append(row)
    return FlyerResult(store_id, out, flags, other)


def confirmed_specials(items: list[dict], person: str) -> list[dict]:
    """Specials a person confirmed, in the PriceBook's format. Flagged/ignored/not-for-us rows never count."""
    return [{"store": r["store"], "ingredient": r["ingredient"], "price": r["sale_pack_price"],
             "regular": r["regular"], "source": "flyer", "confirmed_by": person}
            for r in items if r.get("status") == "needs_confirm" and r.get("ingredient") and r.get("sale_pack_price")]


# ---------------------------------------------------------------- 3. why-notes
def write_notes(ctx: AIContext, h: Household, plan) -> dict[tuple[str, str], str]:
    share = ctx.s["privacy"]["share_names_with_model"]
    facts = {"entries": [{"day": e.day, "meal": e.meal, "recipe": e.name, "why": e.why, "active": e.active,
                          "eaters": [h.people[p].label(share) for p in e.eaters]} for e in plan.entries]}
    raw = ctx.ask("notes", "notes_alias", f"<plan>\n{json.dumps(facts)}\n</plan>")
    fallback = {(e.day, e.meal): "; ".join(e.why) or "keeps the week varied" for e in plan.entries}
    if raw is None:
        return fallback
    try:
        notes = Notes.model_validate(raw)
    except ValidationError:
        return fallback
    out = dict(fallback)
    for n in notes.notes:
        if (n.day, n.meal) in out and not safety.looks_like_instruction(n.note):
            out[(n.day, n.meal)] = n.note
    return out
