"""The editor's checklist, the half that code can check (EVAL-02). The editor agent adds the judged half (accuracy
against the sources, clarity, usefulness) from prompts/editor.v1.md; both halves go in the pull request.

    editorial review site/blog/posts/<slug>.md --sources drafts/<slug>/sources [--json]

Checks: front matter and structure, length, enough cited sources, no long runs copied from any source, limited
quotation, no banned marketing phrases, no client framing (a standing rule for this site), not too similar to a
published post, and the AI-drafting disclosure.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import settings
from .textsim import Space, cosine


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (yaml.safe_load(m.group(1)) or {}, text[m.end():]) if m else ({}, text)


def _prose(body: str) -> str:
    body = re.sub(r"```.*?```", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    return re.sub(r"\]\([^)]*\)", "]", body)                 # keep link text, drop URLs


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def longest_shared_run(post_words: list[str], source_words: list[str], floor: int) -> tuple[int, str]:
    """Length of the longest word run (≥ floor) the post shares with one source, and the run itself."""
    if len(source_words) < floor or len(post_words) < floor:
        return 0, ""
    grams = {tuple(source_words[i:i + floor]) for i in range(len(source_words) - floor + 1)}
    src = " ".join(source_words)
    best, best_txt = 0, ""
    i = 0
    while i <= len(post_words) - floor:
        if tuple(post_words[i:i + floor]) in grams:
            j = i + floor
            while j < len(post_words) and " ".join(post_words[i:j + 1]) in src:
                j += 1
            if j - i > best:
                best, best_txt = j - i, " ".join(post_words[i:j])
            i = j
        else:
            i += 1
    return best, best_txt


def review(post: str | Path, sources_dir: str | Path | None = None, published: list[str] | None = None) -> dict:
    cfg = settings()["review"]
    text = Path(post).read_text()
    meta, body = _split(text)
    prose = _prose(body)
    pw = words(prose)
    checks = []

    def check(name: str, ok: bool, detail: str):
        checks.append({"criterion": name, "passed": bool(ok), "detail": detail})

    missing = [k for k in cfg["required_front_matter"] if not meta.get(k)]
    check("Front matter", not missing, "complete" if not missing else f"missing: {', '.join(missing)}")
    has_h1 = bool(re.search(r"(?m)^# \S", body))
    check("Structure", has_h1 and "<!-- more -->" in body,
          "title and excerpt marker present" if has_h1 and "<!-- more -->" in body else "needs a '# Title' and '<!-- more -->'")
    n = len(pw)
    check("Length", cfg["min_words"] <= n <= cfg["max_words"], f"{n} words (target {cfg['min_words']}–{cfg['max_words']})")
    urls = sorted(set(re.findall(r"\]\((https?://[^)\s]+)\)", body)))
    check("Cited sources", len(urls) >= cfg["min_sources"], f"{len(urls)} external links (need ≥ {cfg['min_sources']})")

    limit = cfg["max_verbatim_run_words"]
    worst, worst_txt, worst_src = 0, "", ""
    for f in sorted(Path(sources_dir).glob("*.txt")) if sources_dir and Path(sources_dir).exists() else []:
        run, txt = longest_shared_run(pw, words(f.read_text(errors="replace")), 8)
        if run > worst:
            worst, worst_txt, worst_src = run, txt, f.name
    check("Originality", worst <= limit, f"longest run copied from a source: {worst} words"
          + (f" ({worst_src}: “{' '.join(worst_txt.split()[:12])}…”)" if worst > limit else "")
          + ("" if sources_dir else " — no source texts given, so not checked"))
    quoted = sum(len(words(q)) for q in re.findall(r"[“\"]([^”\"]{3,})[”\"]", prose))
    check("Quotation", quoted <= cfg["max_quoted_words"], f"{quoted} words in quotation marks (max {cfg['max_quoted_words']})")
    low = prose.lower()
    banned = [p for p in cfg["banned_phrases"] if p.lower() in low]
    check("Style guide", not banned, "no banned phrases" if not banned else f"remove: {', '.join(banned)}")
    client = [p for p in cfg["client_framing"] if p.lower() in low]
    check("No client framing", not client, "none" if not client else f"remove: {', '.join(client)}")
    if published:
        title = next((ln[2:] for ln in body.splitlines() if ln.startswith("# ")), "")
        intro = body.split("<!-- more -->")[0]
        sp = Space(published + [f"{title} {intro}"])
        v = sp.vec(f"{title} {meta.get('short', '')} {meta.get('categories', '')} {intro}")
        sims = [cosine(v, sp.vec(p)) for p in published]
        top = max(sims, default=0.0)
        check("Novelty", top <= cfg["max_similarity_to_published"],
              f"closest published post similarity {top:.2f} (max {cfg['max_similarity_to_published']})")
    check("AI disclosure", cfg["disclosure"].lower() in low, f"says “{cfg['disclosure']}…”"
          if cfg["disclosure"].lower() in low else f"add a line saying it was “{cfg['disclosure']}”")
    return {"post": str(post), "passed": all(c["passed"] for c in checks), "checks": checks, "words": n,
            "sources": urls}


def scorecard_md(result: dict, judged: list[dict] | None = None) -> str:
    rows = ["| Check | Result | Detail |", "|---|---|---|"]
    rows += [f"| {c['criterion']} | {'✅' if c['passed'] else '❌'} | {c['detail']} |" for c in result["checks"]]
    for j in judged or []:
        rows.append(f"| {j['criterion']} (editor) | {j['score']}/5 | {j.get('note', '')} |")
    return "\n".join(rows)
