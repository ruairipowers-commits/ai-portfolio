"""The speaker's word list: presets from config/lexicons/ plus their own words, minus their ignore list.

A custom list is plain text, one entry per line, so anyone can paste one in:

    um
    to be honest | crutch phrase | 2
    so | sentence starter | 1 | opener
    # comments and blank lines are skipped

Fields after the phrase are optional: category, weight, rule (always · opener · closer · context). Everything is
matched literally (SEC-04: a list line is data, never a pattern), case-insensitively, on whole words.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .text import WORD, norm

RULES = ("always", "opener", "closer", "context")
# words that are often normal English; with no rule given they get neighbour rules, then a model if still unclear
CONTEXT_WORDS = {"like", "so", "right", "actually", "well", "just", "you know", "i mean", "kind of", "sort of"}


@dataclass
class Entry:
    text: str
    category: str = "custom"
    weight: float = 1.0
    rule: str = "always"
    source: str = "custom"
    note: str = ""
    example: str = ""

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(norm(w) for w in WORD.findall(self.text))


@dataclass
class Lexicon:
    entries: list[Entry] = field(default_factory=list)
    ignore: set[str] = field(default_factory=set)
    repetition: bool = False
    repetition_allow: set[tuple[str, ...]] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def active(self) -> list[Entry]:
        """Entries to match, longest phrase first so "you know" wins over a lone "you"."""
        seen, out = set(), []
        for e in self.entries:
            key = e.words
            if not key or " ".join(key) in self.ignore or key in seen:
                continue
            seen.add(key)
            out.append(e)
        return sorted(out, key=lambda e: -len(e.words))

    def to_text(self) -> str:
        """Export as a reusable custom list (the format parse_custom reads)."""
        lines = ["# speaking-coach word list — phrase | category | weight | rule"]
        lines += [f"{e.text} | {e.category} | {e.weight:g} | {e.rule}" for e in self.active()]
        if self.ignore:
            lines += ["", "# ignore"] + [f"!{w}" for w in sorted(self.ignore)]
        return "\n".join(lines) + "\n"


def preset_dir(root: Path) -> Path:
    return Path(root) / "config" / "lexicons"


def presets(root: Path) -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text()) for p in sorted(preset_dir(root).glob("*.yaml"))}


def parse_custom(text: str, max_entries: int = 200) -> tuple[list[Entry], set[str], list[str]]:
    """Parse a pasted word list. Lines starting with ! go to the ignore list. Returns entries, ignore, warnings."""
    entries, ignore, warnings = [], set(), []
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            ignore.add(" ".join(norm(w) for w in WORD.findall(line[1:])))
            continue
        parts = [p.strip() for p in line.split("|")]
        phrase = parts[0]
        if not WORD.findall(phrase):
            warnings.append(f"line {n}: no words in '{phrase[:40]}' — skipped")
            continue
        clean = " ".join(WORD.findall(phrase))
        if clean.lower() != " ".join(phrase.lower().split()):
            warnings.append(f"line {n}: '{phrase[:40]}' matched literally as '{clean}' (symbols are ignored)")
        weight = 1.0
        if len(parts) > 2 and parts[2]:
            try:
                weight = max(0.0, min(5.0, float(parts[2])))
            except ValueError:
                warnings.append(f"line {n}: weight '{parts[2]}' is not a number — using 1")
        rule = parts[3].lower() if len(parts) > 3 and parts[3] else ""
        if rule and rule not in RULES:
            warnings.append(f"line {n}: rule '{rule}' unknown (use {', '.join(RULES)}) — using default")
            rule = ""
        low = " ".join(norm(w) for w in WORD.findall(clean))
        rule = rule or ("context" if low in CONTEXT_WORDS else "always")
        entries.append(Entry(clean, parts[1] if len(parts) > 1 and parts[1] else "custom", weight, rule, "custom"))
        if len(entries) >= max_entries:
            warnings.append(f"only the first {max_entries} entries are used")
            break
    return entries, ignore, warnings


COMMON = {"the", "a", "an", "and", "to", "of", "i", "it", "is", "in", "that", "we", "you", "was", "for", "on", "this"}


def build(root: Path, preset_names: list[str], custom_text: str = "", ignore: list[str] | None = None,
          repetition_allow: list[str] | None = None, max_custom: int = 200,
          repetition: bool | None = None) -> Lexicon:
    """repetition: None = on if any chosen preset turns it on; True/False to force."""
    lex = Lexicon(repetition_allow={tuple(norm(w) for w in WORD.findall(p)) for p in (repetition_allow or [])})
    available = presets(root)
    for name in preset_names:
        data = available.get(name)
        if data is None:
            lex.warnings.append(f"preset '{name}' not found")
            continue
        lex.repetition |= bool(data.get("repetition"))
        for e in data.get("entries", []):
            lex.entries.append(Entry(str(e["text"]), e.get("category", name), float(e.get("weight", 1)),
                                     e.get("rule", "always"), name, e.get("note", ""), e.get("example", "")))
    custom, custom_ignore, warnings = parse_custom(custom_text, max_custom)
    # a custom entry replaces a preset entry for the same phrase (the speaker's own weight and rule win)
    keys = {e.words for e in custom}
    lex.entries = custom + [e for e in lex.entries if e.words not in keys]
    lex.warnings += warnings
    lex.warnings += [f"'{e.text}' is a very common word: expect a high rate" for e in custom
                     if " ".join(e.words) in COMMON]
    if repetition is not None:
        lex.repetition = repetition
    lex.ignore = {" ".join(norm(w) for w in WORD.findall(i)) for i in (ignore or [])} | custom_ignore
    return lex
