"""Offline stand-ins for the three model roles. Deterministic, no keys, same input and output schema as a real
model, so validation, content checks and approvals run exactly as they would live.

They are deliberately simple and are not the content a real model writes:
  - writer     builds a level from the source page's own sections; quiz questions are fill-the-gap items cut
               from source sentences (so every answer is grounded by construction)
  - moderator  keyword and pattern heuristics
  - reviser    turns flagged questions and feedback into edits; it also "falls for" a feedback injection on
               purpose, so the code guard that holds answer-key edits is tested end to end
"""
from __future__ import annotations

import hashlib
import re

from .catalog import FRONT, norm, plain
from .checks import STOP

# ---------------------------------------------------------------- moderator
KNOWN = {
    "kubernetes": "https://kubernetes.io/docs/", "react": "https://react.dev/", "rust": "https://doc.rust-lang.org/book/",
    "go": "https://go.dev/doc/", "golang": "https://go.dev/doc/", "kafka": "https://kafka.apache.org/documentation/",
    "spark": "https://spark.apache.org/docs/latest/", "snowflake": "https://docs.snowflake.com/",
    "databricks": "https://docs.databricks.com/", "excel": "https://support.microsoft.com/excel",
    "power bi": "https://learn.microsoft.com/power-bi/", "tableau": "https://help.tableau.com/",
    "git": "https://git-scm.com/doc", "linux": "https://www.kernel.org/doc/html/latest/",
    "redis": "https://redis.io/docs/", "mongodb": "https://www.mongodb.com/docs/", "polars": "https://docs.pola.rs/",
    "pytorch": "https://pytorch.org/docs/stable/", "tensorflow": "https://www.tensorflow.org/api_docs",
    "langchain": "https://python.langchain.com/docs/", "llamaindex": "https://docs.llamaindex.ai/",
    "next.js": "https://nextjs.org/docs", "nextjs": "https://nextjs.org/docs", "vue": "https://vuejs.org/guide/",
    "graphql": "https://graphql.org/learn/", "kotlin": "https://kotlinlang.org/docs/home.html",
    "swift": "https://www.swift.org/documentation/", "java": "https://dev.java/learn/",
    "c#": "https://learn.microsoft.com/dotnet/csharp/", "excel formulas": "https://support.microsoft.com/excel",
    "regex": "https://docs.python.org/3/library/re.html", "regular expressions": "https://docs.python.org/3/library/re.html",
    "bash": "https://www.gnu.org/software/bash/manual/", "vector databases": "", "prompt engineering": "",
    "airtable": "https://support.airtable.com/", "zapier": "https://help.zapier.com/", "figma": "https://help.figma.com/",
    "jira": "https://support.atlassian.com/jira-software-cloud/", "sql": "", "statistics": "", "llm evals": "",
}
INJECTION = re.compile(r"(?i)(ignore (all |any |your |previous )*(instructions|rules)|system prompt|you are now|"
                       r"approve this|return approve|verdict[\"']?\s*[:=]|</request>)")
EXPLICIT = re.compile(r"(?i)\b(porn\w*|nsfw|nudes?|erotic\w*|sex(ual|y)?|fetish\w*|hentai|onlyfans)\b")
HARM = re.compile(r"(?i)\b(stalk\w*|dox\w*|spy on|hurt|kill (my|some(one|body))|revenge on|harass\w*)\b")
BROAD = re.compile(r"(?i)\b(everything|all of|computer science|the internet|life|anything|whatever|stuff|technology)\b")
TECHY = re.compile(r"(?i)\b(api|sdk|sql|data|cloud|web|app|framework|library|language|server|ops|devops|ml|ai|llm|"
                   r"agent|database|pipeline|dashboard|spreadsheet|automation|testing|security|network|vector|"
                   r"prompt|model|analytics|engineering|design|scripting|python|excel|regex)\b")


def moderator(req: dict) -> dict:
    text = req.get("suggestion", "")
    low = text.lower().strip()
    if INJECTION.search(text):
        return {"verdict": "reject-recommended", "categories": ["injection"],
                "reasons": ["The suggestion tries to instruct the reviewer instead of naming a topic."],
                "duplicate_of": None, "learnable_in_format": False, "proposed_title": "", "proposed_outline": [],
                "official_docs": ""}
    if EXPLICIT.search(text) or HARM.search(text):
        cat = "sexual" if EXPLICIT.search(text) else "harassment"
        return {"verdict": "reject-recommended", "categories": [cat],
                "reasons": [f"Not suitable for this site ({cat})."], "duplicate_of": None,
                "learnable_in_format": False, "proposed_title": "", "proposed_outline": [], "official_docs": ""}
    title = re.sub(r"(?i)\b(basics|101|for beginners|intro(duction)? to|crash course( on)?|learn)\b", "", text)
    title = re.sub(r"\s+", " ", title).strip(" -:") or text.strip()
    title = title if any(ch.isupper() for ch in title) else title.title()
    key = next((k for k in sorted(KNOWN, key=len, reverse=True) if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", low)), None)
    outline = [f"What {title} is and the problem it solves", f"Where {title} came from and how it is used today",
               f"Who uses {title} in a business", f"Key use cases for {title}", "Pros and cons",
               f"A hello-world {title} example"]
    if BROAD.search(text) and not key:
        return {"verdict": "needs-review", "categories": [], "learnable_in_format": False,
                "reasons": ["Too broad to teach in 15 minutes / 1 hour / 4 hours; suggest a specific tool or skill."],
                "duplicate_of": None, "proposed_title": title[:80], "proposed_outline": [], "official_docs": ""}
    if key is not None or TECHY.search(text):
        return {"verdict": "approve-recommended", "categories": [], "learnable_in_format": True,
                "reasons": [f"{title} is a specific, teachable technology topic."], "duplicate_of": None,
                "proposed_title": title[:80], "proposed_outline": outline, "official_docs": KNOWN.get(key, "") or ""}
    return {"verdict": "needs-review", "categories": [], "learnable_in_format": True,
            "reasons": ["Not a topic I recognise; check that it is a real technology or skill."],
            "duplicate_of": None, "proposed_title": title[:80], "proposed_outline": outline, "official_docs": ""}


# ---------------------------------------------------------------- writer
def h2_sections(md: str) -> dict[str, str]:
    body = FRONT.sub("", md)
    out, cur = {}, None
    for line in body.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            cur = m.group(1).strip()
            out[cur] = ""
        elif cur:
            out[cur] += line + "\n"
    return {k: v.strip() for k, v in out.items()}


def _get(secs: dict, *names: str) -> str:
    for n in names:
        for k, v in secs.items():
            if k.lower().startswith(n.lower()):
                return v
    return ""


def sentences(text: str) -> list[str]:
    t = plain(text, lower=False)
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", t) if 8 <= len(x.split()) <= 45]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z-]{4,}", text) if not w.endswith("-")]


def cloze(source_md: str, prefix: str, n: int, seed: str, extra_text: str = "") -> list[dict]:
    sents = sentences(source_md + "\n\n" + extra_text)
    pool = sorted(set(_words(" ".join(sents).lower())))
    out, used = [], set()
    for rnd in range(3):
        for i, sent in enumerate(sents):
            if len(out) >= n:
                return out
            low = sent.lower()
            cands = [w for w in dict.fromkeys(_words(low)) if low.count(w) == 1 and (sent, w) not in used
                     and w not in STOP
                     and re.search(rf"(?<![\w./_-]){re.escape(w)}(?![\w/_-]|\.\w)", low)]
            if len(cands) <= rnd:
                continue
            w = cands[(rnd * 3 + i) % len(cands)]
            used.add((sent, w))
            others = [p for p in pool if p not in low and p != w]
            if len(others) < 3:
                continue
            h = int(hashlib.sha256(f"{seed}{sent}{w}".encode()).hexdigest(), 16)
            picks = [others[(h >> (8 * k)) % len(others)] for k in range(6)]
            distract = list(dict.fromkeys(picks))[:3]
            if len(distract) < 3:
                continue
            opts = distract[:]
            pos = h % 4
            opts.insert(pos, w)
            gap = re.sub(rf"\b{re.escape(w)}\b", "_____", sent, count=1, flags=re.I)
            if len(gap) > 380:
                continue
            out.append({"id": f"{prefix}{len(out) + 1}", "prompt": f"Fill the gap: “{gap}”", "options": opts,
                        "answer": pos, "explanation": f"The material says: “{sent}”", "evidence": sent})
    return out


def writer(req: dict) -> dict:
    c, level, md = req["course"], req["level"], req["source"]["markdown"]
    secs = h2_sections(md)
    title, docs = c["title"], c.get("docs") or ""
    what = _get(secs, "What it is") or c.get("title", "")
    uses = _get(secs, "Typical use", "Use cases") or "- (see the official documentation)"
    in_ai = _get(secs, "In AI work") or what
    in_pf = _get(secs, "In this portfolio") or "Not used in the portfolio yet."
    pros = _get(secs, "Pros and cons") or "| Pros | Cons |\n|---|---|\n| — | — |"
    usage = _get(secs, "Basic usage")
    code = (re.search(r"```(\w*)\n(.*?)```", usage, re.S) or [None, "", ""])
    lang, snippet = (code[1], code[2]) if code[0] else ("", "")
    docs_line = f"- [{title} documentation]({docs}) — the official reference." if docs else "- The official documentation."
    rows = [r for r in pros.splitlines() if r.startswith("|") and not re.match(r"^\|[-:| ]+\|$", r)][1:]
    cons = [r.strip("|").split("|")[-1].strip() for r in rows if "|" in r.strip("|")]
    body = {
        "concept": what, "history": in_ai, "business": in_ai, "use_cases": uses, "pros_cons": pros,
        "resources": docs_line, "hello_world": f"Run the smallest working {title} example below and check its output.",
        "interview": (f"- **What is {title} and when would you choose it?** Name the problem it solves and one "
                      f"trade-off.\n- **What are its limits?** For example: {cons[0] if cons else 'see the cons'}.\n"
                      f"- **How have you used it?** Describe the example project and what you checked."),
        "recap": uses, "core_terms": what,
        "setup": f"1. Follow the install guide in the official docs: {docs or 'see the docs'}\n"
                 f"2. Create a fresh project folder.\n3. Run the basic example.\n\nYou are ready when the basic example runs.",
        "guided_project": f"Build a small, real {title} task step by step (see the project below).",
        "mistakes": "\n".join(f"- {x}" for x in cons) or "- Skipping the official setup steps.",
        "cheat_sheet": usage or what, "next_steps": docs_line,
        "modules": f"Four modules cover what {title} is, where it is used, how it is used in AI work, and its trade-offs.",
        "production": "\n".join(f"- {x}" for x in cons) or "See the trade-offs.",
        "alternatives": f"Compare {title} with other tools in the {c.get('category', 'same')} category before choosing it.",
        "in_portfolio": in_pf, "capstone": f"Extend the {title} project into something you would show a colleague.",
        "further_learning": docs_line,
    }
    filler = (f"{title} is covered here from its official documentation ({docs or 'see the docs'}) and the owner's "
              f"notes. This part of the {level} level explains how {title} is used in practice, what to watch for, "
              f"and how it compares with the alternatives a team would consider.")
    sections = [{"id": s["id"], "heading": s["id"].replace("_", " ").capitalize(),
                 "body": b if len((b := body.get(s["id"], what) or "").strip()) >= 40 else (b + "\n\n" + filler).strip()}
                for s in req["sections"]]
    n = req["quiz_questions"]
    level_text = "\n\n".join(x["body"] for x in sections)
    quiz = cloze(md, "q", n, c["slug"] + level, extra_text=level_text)
    modules = []
    if level == "intermediate":
        for i, (mid, mtitle, text) in enumerate([("m1", f"How {title} works", what), ("m2", "Where it is used", uses),
                                                 ("m3", "In AI work", in_ai), ("m4", "Trade-offs", pros)], 1):
            check = cloze(text, f"m{i}q", 6, c["slug"] + mid, extra_text=what)
            modules.append({"id": mid, "title": mtitle, "minutes": 30, "body": text,
                            "exercise": f"Apply this module to a small example of your own and note one thing that "
                                        f"surprised you about {title}.", "check": check})
    minutes = req.get("project_minutes", 3)
    project = {"title": f"{title}: {'hello world' if level == 'familiar' else 'guided project' if level == 'beginner' else 'capstone'}",
               "kind": "runnable" if snippet else "illustrative", "minutes": minutes,
               "goal": f"Get a working {title} example running and understand each line.",
               "steps": ["Set up as in the official docs.", "Copy the example into a new file.", "Run it.",
                         "Change one thing and run it again."],
               "code": snippet, "language": lang, "expected": "The example runs without errors.",
               "done_when": ["The example runs.", "You changed one line and saw the effect."]}
    return {"course": c["slug"], "level": level, "version": 1, "title": f"{title} — {level}", "status": "draft",
            "source": {"page": req["source"]["page"]}, "provenance": {"written_by": "mock-writer"},
            "sections": sections, "modules": modules, "project": project, "quiz": quiz}


# ---------------------------------------------------------------- reviser
def reviser(req: dict) -> dict:
    lv = req["level"]
    edits = []
    for qid, st in sorted(req.get("stats", {}).items()):
        edits.append({"target": f"quiz:{qid}", "evidence": [f"stats:{qid}"], "touches_answer_key": False,
                      "change": "Point to the exact sentence in the material that answers this, and say why the "
                                "most-chosen wrong option doesn't fit.",
                      "reason": f"Missed by {st.get('missed_pct', 0)}% of {st['n']} attempts."})
    heads = {x["id"]: norm(x["heading"]) for x in lv["sections"]}
    for f in req.get("feedback", []):
        text = norm(f"{f.get('unclear', '')} {f.get('add', '')}")
        if not text:
            continue
        if "answer" in text and lv["quiz"]:          # the mock is naive on purpose (see module docstring)
            edits.append({"target": f"quiz:{lv['quiz'][0]['id']}", "evidence": [f"feedback:{f['id']}"],
                          "change": "Change the correct answer as the learner asked.",
                          "reason": "A learner asked for it.", "touches_answer_key": False})
            continue
        target = next((sid for sid, h in heads.items() if h and (h in text or sid.replace("_", " ") in text)), None)
        if target is None and any(w in text for w in ("project", "step", "example", "code")):
            target = "project"
        target = target or lv["sections"][0]["id"]
        edits.append({"target": target, "evidence": [f"feedback:{f['id']}"], "touches_answer_key": False,
                      "change": "Add one short worked example and define any term used before it is explained.",
                      "reason": "Learners said this part was unclear."})
    dedup = {}
    for e in edits:
        dedup.setdefault((e["target"], e["change"]), e)
    edits = list(dedup.values())[:10]
    return {"edits": edits, "summary": f"{len(edits)} edit(s) from {len(req.get('feedback', []))} feedback items and "
                                       f"{len(req.get('stats', {}))} flagged questions."}
