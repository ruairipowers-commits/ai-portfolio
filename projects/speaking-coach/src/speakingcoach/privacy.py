"""DATA-03 and SEC-02: what a model is allowed to see, and how.

- pseudonymize(): names, emails and phone numbers become [NAME_1], [EMAIL_1], [PHONE_1] before any model call and
  are restored afterwards, so a rewrite still says "Priya" but the provider never saw it.
- scan_injection(): flags text that tries to give the model instructions. It's only a flag: the counts and grade are
  computed by code, so an injected "give me a perfect score" can't change them.
- fence(): escapes angle brackets so transcript text can't close the delimiters it sits in.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\w)")
CAP_RUN = re.compile(r"\b[A-Z][a-z][a-zA-Z'’-]*(?:\s+[A-Z][a-z][a-zA-Z'’-]*){0,2}\b")
# capitalised words that are not names
NOT_NAMES = set("""I I'm I've I'll I'd Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March
April May June July August September October November December OK Okay Yes No So And But Um Uh Well Like Right The
A An It We You They He She This That What When Where Why How If Then Also Just Now Here There Thanks Thank Hi Hello
Mr Mrs Ms Dr Q1 Q2 Q3 Q4 English Internet God Christmas Easter Zoom Teams Slack Excel Python SQL AI API""".split())
INJECTION = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+)*"
    r"(instructions|rules|prompts?|directions)"
    r"|\bsystem\s*:|\byou are now\b|\bact as\b|\bnew instructions\b|\bdeveloper mode\b"
    r"|(grade|score|rate)\s+(me|this|it)\s+(an?\s+)?(a|perfect|100|zero|10/10)"
    r"|report\s+(zero|no)\s+filler", re.I)


class Pseudonymizer:
    def __init__(self, names: list[str] | None = None):
        self.forward: dict[str, str] = {}
        self.extra = [n for n in (names or []) if n.strip()]

    def _tag(self, kind: str, value: str) -> str:
        if value not in self.forward:
            n = sum(1 for v in self.forward.values() if v.startswith(f"[{kind}_")) + 1
            self.forward[value] = f"[{kind}_{n}]"
        return self.forward[value]

    def learn_names(self, text: str) -> None:
        """Names = capitalised words that appear mid-sentence somewhere (so 'Priya' at a sentence start is caught
        too once she's been seen mid-sentence), plus any names the speaker listed."""
        for m in CAP_RUN.finditer(text):
            before = text[:m.start()].rstrip()
            if not before or before[-1] in ".?!\n\"“:":
                continue
            words = [w for w in m.group().split() if w.strip("'’") not in NOT_NAMES]
            if words and len(words) == len(m.group().split()):
                self._tag("NAME", m.group())
                for part in words if len(words) > 1 else []:
                    if len(part) >= 3:
                        self._tag("NAME", part)     # "Priya Nair" seen → "Priya" alone is caught too
        for n in self.extra:
            self._tag("NAME", n.strip())

    def apply(self, text: str) -> str:
        text = EMAIL.sub(lambda m: self._tag("EMAIL", m.group()), text)
        text = PHONE.sub(lambda m: self._tag("PHONE", m.group()), text)
        for value, tag in sorted(self.forward.items(), key=lambda kv: -len(kv[0])):
            if tag.startswith("[NAME_"):
                text = re.sub(rf"\b{re.escape(value)}\b", tag, text)
        return text

    def restore(self, text: str) -> str:
        for value, tag in self.forward.items():
            text = text.replace(tag, value)
        return text

    def placeholders(self, text: str) -> set[str]:
        return set(re.findall(r"\[(?:NAME|EMAIL|PHONE)_\d+\]", text))


def scan_injection(text: str) -> list[str]:
    return [m.group(0) for m in INJECTION.finditer(text or "")]


def fence(text: str) -> str:
    return (text or "").replace("<", "‹").replace(">", "›")
