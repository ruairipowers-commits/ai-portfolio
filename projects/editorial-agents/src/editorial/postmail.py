"""Each new draft post, emailed to the owner by this service: the whole post, the editor's scorecard, and signed
Approve / Archive links (HITL-02, SEC-01).

The service sends it, not a GitHub workflow, so the link secret never leaves this host: a pull request can't read it.
It finds new posts in the same read-only pass as `github_sync` (public API; the PR's post file is read from
raw.githubusercontent.com at the PR's head commit) and emails each PR once.
"""
from __future__ import annotations

import json
import re
from html import escape as e

from . import links, mailer
from .config import owner_email, public_url, repo, settings
from .store import Store

POST = re.compile(r"^site/[a-z]+/posts/[^/]+\.md$")


def md_to_html(md: str) -> str:
    """Enough Markdown for an email: headings, paragraphs, lists, links, bold, italics, inline code, fences."""
    def inline(t: str) -> str:
        t = e(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)

    out, para, items, fence = [], [], [], None
    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
    for ln in md.splitlines():
        if ln.startswith("```"):
            if fence is None:
                flush()
                fence = []
            else:
                out.append(f"<pre style='background:#f5f5f5;padding:8px;overflow:auto'>{e(chr(10).join(fence))}</pre>")
                fence = None
            continue
        if fence is not None:
            fence.append(ln)
        elif m := re.match(r"^(#{1,4})\s+(.*)", ln):
            flush()
            out.append(f"<h{len(m.group(1)) + 1}>{inline(m.group(2))}</h{len(m.group(1)) + 1}>")
        elif m := re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", ln):
            if para:
                flush()
            items.append(m.group(1))
        elif not ln.strip() or ln.strip().startswith("<!--"):
            flush()
        else:
            if items:
                flush()
            para.append(ln.strip())
    flush()
    return "\n".join(out)


def parse_post(text: str, fallback: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    body = text[m.end():] if m else text
    title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), fallback)
    body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("# ")).strip()
    return {"title": title, "body": body, "words": len(re.findall(r"[A-Za-z0-9']+", body))}


def scorecard(pr_body: str) -> str:
    m = re.search(r"<!-- scorecard -->(.*?)<!-- /scorecard -->", pr_body or "", re.DOTALL)
    return m.group(1).strip() if m else ""


def compose(tid: str, pr: dict, post: dict) -> dict:
    base = public_url()
    acts = {a: f"{base}/act?t={links.sign(tid, a)}" for a in links.POST_ACTIONS}
    labels = {lb.get("name") for lb in pr.get("labels", [])}
    held = "needs-work" in labels
    days = settings()["links"]["post_ttl_days"]
    subject = ("Draft needs work: " if held else "Draft ready: ") + post["title"]
    card = scorecard(pr.get("body", ""))
    how = (f"Approve adds it to the publishing line: one approved post goes live each day, oldest approval first. "
           f"Archive keeps it to publish later: this email's Approve link works for {days} days, and the daily topic "
           f"email lists archived posts too. Each link opens a confirmation page first. Merging the pull request by "
           f"hand still publishes at once.")
    text = (f"{post['title']} ({post['words']} words){' — needs work' if held else ''}\n\n"
            f"Approve: {acts['approve']}\nArchive: {acts['archive']}\nPull request: {pr.get('html_url', '')}\n\n"
            f"{how}\n\n{('Scorecard:' + chr(10) + card + chr(10) + chr(10)) if card else ''}---\n\n{post['body']}\n")
    cell = "padding:3px 8px;border-bottom:1px solid #eee"
    rows = "".join("<tr>" + "".join(f'<td style="{cell}">{e(c.strip())}</td>' for c in ln.strip("|").split("|"))
                   + "</tr>" for ln in card.splitlines() if ln.startswith("|") and not set(ln) <= set("|-: "))
    btn = "display:inline-block;padding:8px 16px;border-radius:4px;text-decoration:none;margin:4px 8px 4px 0;color:#fff"
    buttons = (f'<p><a href="{e(acts["approve"])}" style="{btn};background:#2e7d32">Approve</a>'
               f'<a href="{e(acts["archive"])}" style="{btn};background:#546e7a">Archive</a>'
               f'<a href="{e(pr.get("html_url", ""))}" style="color:#3f51b5;margin-left:4px">Pull request</a></p>')
    html = (f'<div style="max-width:680px;margin:auto;font:15px/1.55 sans-serif;color:#222">'
            f'<h2 style="margin-bottom:2px">{e(post["title"])}</h2>'
            f'<p style="color:#666;margin-top:0">{post["words"]} words'
            f'{" · <b style=color:#c62828>needs work</b>" if held else ""}</p>{buttons}'
            f'<p style="color:#777;font-size:13px">{e(how)}</p>'
            + (f'<table style="border-collapse:collapse;font-size:13px">{rows}</table>' if rows else "")
            + f'<hr style="border:0;border-top:1px solid #ddd;margin:18px 0">{md_to_html(post["body"])}'
            f'<hr style="border:0;border-top:1px solid #ddd;margin:18px 0">{buttons}</div>')
    return {"subject": subject, "text": text, "html": html}


def notify(store: Store, open_prs: dict[str, dict], get) -> list[int]:
    """Email each open draft-post PR once (kv `emailed:<number>`). `open_prs`: topic id → PR. Returns PR numbers sent."""
    sent = []
    for tid, pr in open_prs.items():
        n = pr.get("number")
        if store.get_kv(f"emailed:{n}"):
            continue
        try:
            files = json.loads(get(f"https://api.github.com/repos/{repo()}/pulls/{n}/files",
                                   headers={"Accept": "application/vnd.github+json"}))
            path = next((f["filename"] for f in files if f.get("status") == "added" and POST.match(f["filename"])),
                        None)
            if not path:
                store.set_kv(f"emailed:{n}", {"skipped": "no new post file"})
                continue
            sha = (pr.get("head") or {}).get("sha", "")
            raw = get(f"https://raw.githubusercontent.com/{repo()}/{sha}/{path}")
            mail = compose(tid, pr, parse_post(raw, pr.get("title", path)))
            to = owner_email()
            status = mailer.send(to or ["owner@localhost"], mail["subject"], mail["text"], mail["html"]) \
                if (to or not mailer.configured()) else "not sent: no EDITORIAL_EMAIL"
            store.set_kv(f"emailed:{n}", {"status": status, "sha": sha, "path": path})
            store.run("post_email", status, {"pr": n, "topic": tid})
            sent.append(n)
        except Exception as ex:  # noqa: BLE001 — try again on the next sync
            store.run("post_email", "error", {"pr": n, "error": f"{type(ex).__name__}: {ex}"[:300]})
    return sent
