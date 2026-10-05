"""Email Ruairi a draft post that's waiting for review (run by .github/workflows/draft-post.yml).

    PR_NUMBER=… PR_URL=… PR_BODY=… PR_HEAD=… REPO=owner/name python3 scripts/draft_email.py POST.md [--dry-run]

The email has the title, the intro, the editor's scorecard from the PR body, and three links:
  Review & approve  → the pull request (Merge publishes it)
  Read the draft    → the file on its branch
  Improve with Claude → a claude.ai link with a prompt to revise this PR
Withholding needs no link: the PR stays open as a draft. Closing it drops the topic.
Standard library only. SMTP settings come from the repository secrets (SMTP_*, ALERT_EMAIL).
"""
from __future__ import annotations

import html
import os
import re
import smtplib
import ssl
import sys
import urllib.parse
from email.message import EmailMessage
from pathlib import Path


def parse_post(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    body = text[m.end():] if m else text
    title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), path.stem)
    intro = body.split("<!-- more -->")[0]
    intro = " ".join(ln for ln in intro.splitlines() if not ln.startswith("# ")).strip()
    words = len(re.findall(r"[A-Za-z0-9']+", body))
    return {"title": title, "intro": " ".join(intro.split()), "words": words}


def scorecard(body: str) -> str:
    m = re.search(r"<!-- scorecard -->(.*?)<!-- /scorecard -->", body or "", re.S)
    return m.group(1).strip() if m else "(no scorecard in the pull request)"


def compose(post: dict, pr: dict) -> tuple[str, str, str]:
    needs_work = "needs-work" in pr.get("labels", "")
    subject = ("Draft needs work: " if needs_work else "Draft ready for review: ") + post["title"]
    prompt = (f"In my ai-portfolio repo, pull request #{pr['number']} is a draft blog post ({pr['url']}). Review it "
              "against factory/style-guide.md and the editor rubric in projects/editorial-agents/prompts/editor.v1.md, "
              "then propose specific improvements and push them to the PR branch. Don't merge.")
    claude = "https://claude.ai/new?q=" + urllib.parse.quote(prompt)
    read = f"https://github.com/{pr['repo']}/blob/{pr['head']}/{pr['path']}"
    card = scorecard(pr.get("body", ""))
    text = (f"{post['title']} ({post['words']} words)\n\n{post['intro']}\n\nEditor's scorecard:\n{card}\n\n"
            f"Review & approve (merge to publish): {pr['url']}\nRead the draft: {read}\n"
            f"Improve with Claude: {claude}\n\nTo withhold: do nothing — it stays a draft. To drop it, close the PR.\n")
    cell = "padding:3px 8px;border-bottom:1px solid #eee"
    rows = "".join("<tr>" + "".join(f'<td style="{cell}">{html.escape(c.strip())}</td>' for c in ln.strip("|").split("|"))
                   + "</tr>" for ln in card.splitlines() if ln.startswith("|") and not set(ln) <= set("|-: "))
    btn = "display:inline-block;padding:8px 14px;border-radius:4px;text-decoration:none;margin:4px 6px 4px 0"
    page = (f'<div style="max-width:680px;margin:auto;font:15px/1.5 sans-serif"><h2>{html.escape(post["title"])}</h2>'
            f'<p style="color:#555">{post["words"]} words{" · <b style=color:#c62828>needs work</b>" if needs_work else ""}</p>'
            f'<p>{html.escape(post["intro"])}</p><h3 style="font-size:15px">Editor\'s scorecard</h3>'
            f'<table style="border-collapse:collapse;font-size:13px">{rows}</table><p>'
            f'<a href="{html.escape(pr["url"])}" style="{btn};background:#2e7d32;color:#fff">Review &amp; approve</a>'
            f'<a href="{html.escape(read)}" style="{btn};background:#eceff1;color:#263238">Read the draft</a>'
            f'<a href="{html.escape(claude)}" style="{btn};background:#eceff1;color:#263238">Improve with Claude</a></p>'
            f'<p style="color:#777;font-size:13px">To withhold: do nothing — it stays a draft. To drop the topic, close '
            f'the pull request. Merging publishes it and emails subscribers.</p></div>')
    return subject, text, page


def send(subject: str, text: str, page: str) -> None:
    to = os.environ.get("ALERT_EMAIL") or os.environ.get("SMTP_FROM") or ""
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, to
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ["SMTP_USER"]
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    port = int(os.environ.get("SMTP_PORT") or 587)
    ctx = ssl.create_default_context()
    with (smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, context=ctx, timeout=30) if port == 465
          else smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=30)) as s:
        if port != 465:
            s.starttls(context=ctx)
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def main(argv: list[str]) -> int:
    path = Path(argv[0])
    pr = {"number": os.environ.get("PR_NUMBER", "?"), "url": os.environ.get("PR_URL", ""),
          "body": os.environ.get("PR_BODY", ""), "head": os.environ.get("PR_HEAD", "main"),
          "repo": os.environ.get("REPO", ""), "labels": os.environ.get("PR_LABELS", ""), "path": str(path)}
    subject, text, page = compose(parse_post(path), pr)
    if "--dry-run" in argv or not os.environ.get("SMTP_HOST"):
        print(subject + "\n\n" + text)
        return 0
    send(subject, text, page)
    print("sent:", subject)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
