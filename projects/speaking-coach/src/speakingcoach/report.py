"""The report a speaker keeps: Markdown (to paste anywhere) and a self-contained HTML page with every hit
highlighted in place. Everything is escaped; the transcript is never treated as markup."""
from __future__ import annotations

from html import escape

from .workflow import Result

COLORS = {"filler sound": "#f6c177", "filler word": "#eb9fb0", "sentence starter": "#9ccfd8",
          "hedging phrase": "#c4a7e7", "closing crutch": "#a3be8c", "repetition": "#f28b82",
          "crutch phrase": "#ffd479", "intensifier": "#b5d6ff", "jargon": "#d4c5a9"}
FALLBACK = "#e0c3fc"


def color(category: str) -> str:
    return COLORS.get(category, FALLBACK)


def highlighted_html(res: Result) -> str:
    """The transcript with counted hits highlighted, disputed ones outlined, and normal uses left plain."""
    out, pos = [], 0
    for h in sorted(res.hits, key=lambda h: h.start):
        if h.start < pos or h.verdict == "not_filler":
            continue
        out.append(escape(res.text[pos:h.start]))
        tip = escape(f"{h.category} · {h.reason} ({h.source})")
        if h.verdict == "filler":
            out.append(f'<mark style="background:{color(h.category)};color:#111;border-radius:3px;padding:0 2px" '
                       f'title="{tip}">{escape(res.text[h.start:h.end])}</mark>')
        else:
            out.append(f'<span style="outline:1.5px dashed #888;border-radius:3px;padding:0 2px" '
                       f'title="disputed — your call: {tip}">{escape(res.text[h.start:h.end])}</span>')
        pos = h.end
    out.append(escape(res.text[pos:]))
    return "".join(out).replace("\n", "<br>")


def legend_html(res: Result) -> str:
    cats = sorted({h.category for h in res.hits if h.verdict == "filler"})
    chips = [f'<span style="background:{color(c)};color:#111;border-radius:3px;padding:1px 6px;margin-right:6px">'
             f'{escape(c)}</span>' for c in cats]
    chips.append('<span style="outline:1.5px dashed #888;border-radius:3px;padding:1px 6px">disputed</span>')
    return " ".join(chips)


def markdown(res: Result) -> str:
    s = res.score
    lines = [f"# Speaking report{' — ' + res.speaker if res.speaker else ''}", "",
             f"**Grade {s.grade}** · {s.fillers} fillers in {s.words} words · **{s.rate_per_100} per 100 words** "
             f"(target {s.target_per_100:g})", ""]
    if s.timing:
        lines += [f"Pace: {s.timing.words_per_minute:g} words a minute · {s.timing.pauses} pauses of a second or more", ""]
    if s.top:
        lines += ["## Your top crutches", "", "| Word | Times |", "|---|---|"]
        lines += [f"| {'repeated words' if w == 'repetition' else w} | {n} |" for w, n in s.top] + [""]
    if s.by_position and any(s.by_position.values()):
        lines += ["Where: " + " · ".join(f"{k} {v}" for k, v in s.by_position.items()), ""]
    if s.clusters:
        lines += ["## Filler streaks", ""]
        lines += [f"- {c.hits} fillers in one stretch near the {c.position}"
                  + (f" ({int(c.at_seconds // 60)}:{int(c.at_seconds % 60):02d})" if c.at_seconds is not None else "")
                  + f": “{c.excerpt}”" for c in s.clusters] + [""]
    if res.patterns:
        lines += ["## Patterns and what to try", ""]
        lines += [f"- **{p['title']}** — {p['where']}. {p['tip']}" for p in res.patterns] + [""]
    ok = [r for r in res.rewrites if r["status"] == "ok"]
    if ok:
        lines += ["## Said more cleanly", ""]
        for r in ok:
            lines += [f"> {r['original']}", "", f"{r['rewrite']}", ""]
    if s.disputed:
        lines += [f"_{s.disputed} occurrence(s) were unclear and are not counted until you decide._", ""]
    if res.warnings:
        lines += ["## Notes", ""] + [f"- {w}" for w in res.warnings] + [""]
    return "\n".join(lines)


def html(res: Result) -> str:
    """Self-contained HTML report (no external assets)."""
    s = res.score
    e = escape
    parts = [f"<h1>Speaking report{' — ' + e(res.speaker) if res.speaker else ''}</h1>",
             f"<p><b>Grade {s.grade}</b> · {s.fillers} fillers in {s.words} words · <b>{s.rate_per_100} per 100 words</b>"
             f" (target {s.target_per_100:g})</p>"]
    if s.timing:
        parts.append(f"<p>Pace: {s.timing.words_per_minute:g} words a minute · {s.timing.pauses} pauses of a second "
                     f"or more</p>")
    if s.top:
        rows = "".join(f"<tr><td>{e('repeated words' if w == 'repetition' else w)}</td><td>{n}</td></tr>" for w, n in s.top)
        parts.append(f"<h2>Your top crutches</h2><table><tr><th>Word</th><th>Times</th></tr>{rows}</table>")
    if res.patterns:
        parts.append("<h2>Patterns and what to try</h2><ul>" + "".join(
            f"<li><b>{e(p['title'])}</b> — {e(p['where'])}. {e(p['tip'])}</li>" for p in res.patterns) + "</ul>")
    ok = [r for r in res.rewrites if r["status"] == "ok"]
    if ok:
        parts.append("<h2>Said more cleanly</h2>" + "".join(
            f"<blockquote>{e(r['original'])}</blockquote><p>{e(r['rewrite'])}</p>" for r in ok))
    if res.warnings:
        parts.append("<h2>Notes</h2><ul>" + "".join(f"<li>{e(w)}</li>" for w in res.warnings) + "</ul>")
    return _page(res, "".join(parts))


def _page(res: Result, body: str) -> str:
    return (f"<!doctype html><meta charset='utf-8'><title>Speaking report</title>"
            f"<style>body{{font:16px/1.55 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}}"
            f"table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:2px 8px}}"
            f"blockquote{{color:#555;border-left:3px solid #ccc;margin:0;padding-left:1rem}}</style>"
            f"{body}<h2>Transcript</h2><p>{legend_html(res)}</p><p>{highlighted_html(res)}</p>")
