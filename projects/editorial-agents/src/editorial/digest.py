"""The owner's topic email: the queue in the order the daily writer will take it (picks, then readers' votes, then
rank), each with why it's interesting, its sectors, its votes (total and since the last email), its source link and
one-click Pick / Dismiss links (signed, expiring, single-use; each opens a confirmation page).

Above the topics, the publishing line: approved posts (one goes live each day, oldest approval first), posts waiting
for the owner's decision, and archived posts, each with fresh Approve / Archive links. It warns when nothing is
approved, because then nothing publishes tomorrow."""
from __future__ import annotations

from html import escape as e

from . import links, mailer, telemetry
from .config import owner_email, public_url, settings
from .store import Store


def posts_section(store: Store, base: str) -> tuple[str, str, str]:
    """(subject prefix, html, text) for the publishing line."""
    p = store.posts()
    a, w, ar = p["approved"], p["drafted"], p["archived"]
    btn = "display:inline-block;margin:4px 6px 0 0;padding:3px 9px;border-radius:4px;text-decoration:none;font-size:13px"

    def item(t: dict, actions: tuple[str, ...]) -> tuple[str, str]:
        pr = t.get("pr") or {}
        title, url = pr.get("title") or t["title"], pr.get("url") or t["url"]
        acts = [(x, f"{base}/act?t={links.sign(t['id'], x)}") for x in actions]
        h = (f'<li style="margin:4px 0"><a href="{e(url)}">{e(title)}</a>'
             + "".join(f' <a href="{e(u)}" style="{btn};background:{"#2e7d32" if x == "approve" else "#eceff1"};'
                       f'color:{"#fff" if x == "approve" else "#263238"}">{x.title()}</a>' for x, u in acts) + "</li>")
        tx = f"  - {title} ({url})" + "".join(f"\n      {x.title()}: {u}" for x, u in acts)
        return h, tx

    groups = [("Approved, in publishing order", a, ("archive",)), ("Waiting for your decision", w, ("approve", "archive")),
              ("Archived", ar, ("approve",))]
    html_parts, text_parts = [], []
    if not a:
        warn = ("Nothing is approved, so nothing publishes tomorrow. Approve one of the posts below."
                if w or ar else "Nothing is approved and no drafts are waiting; the next daily run writes more.")
        html_parts.append(f'<p style="font:600 14px sans-serif;color:#c62828">{e(warn)}</p>')
        text_parts.append("!! " + warn)
    for name, rows, acts in groups:
        if not rows:
            continue
        items = [item(t, acts) for t in rows]
        html_parts.append(f'<p style="font:600 14px sans-serif;margin:10px 0 2px">{e(name)} ({len(rows)})</p>'
                          f'<ul style="font:14px/1.45 sans-serif;margin:0;padding-left:18px">'
                          f'{"".join(h for h, _ in items)}</ul>')
        text_parts.append(f"{name} ({len(rows)}):\n" + "\n".join(tx for _, tx in items))
    prefix = f"{len(a)} approved, {len(w)} waiting · "
    return prefix, "".join(html_parts) + '<hr style="border:0;border-top:1px solid #ddd">', "\n\n".join(text_parts)


def render(store: Store) -> dict:
    q = store.queue()
    base = public_url()
    last = (store.last_run("digest") or {}).get("ts", "")
    fresh = store.vote_counts(since=last) if last else store.vote_counts()
    total_new = sum(fresh.get(t["id"], 0) for t in q)
    health = (store.last_run("scout") or {}).get("detail", {}).get("sources", {})
    dead = [k for k, v in health.items() if not str(v).startswith("ok")]
    subject = (f"Blog topics: {len(q)} ranked ideas" + (f" ({sum(t['status'] == 'picked' for t in q)} picked)" if q else "")
               + (f" · {total_new} new reader vote{'s' if total_new != 1 else ''}" if total_new else ""))
    p_subj, p_html, p_text = posts_section(store, base)
    subject = p_subj + subject
    rows_h, rows_t = [], []
    for i, t in enumerate(q, 1):
        a, sc = t.get("analysis") or {}, t.get("scores") or {}
        pick = f"{base}/act?t={links.sign(t['id'], 'unpick' if t['status'] == 'picked' else 'pick')}"
        dismiss = f"{base}/act?t={links.sign(t['id'], 'dismiss')}"
        picked = t["status"] == "picked"
        label = "Unpick" if picked else "Pick for a post"
        nv, new_v = t.get("votes", 0), fresh.get(t["id"], 0)
        vote_h = (f'<b style="color:#3f51b5">{nv} vote{"s" if nv != 1 else ""}'
                  f'{f" (+{new_v} new)" if new_v else ""}</b> · ' if nv else "")
        nxt = "<b style=color:#c62828>Next to write</b> · " if i == 1 else ""
        rows_h.append(
            f'<tr><td style="padding:10px 8px;vertical-align:top;font:700 18px sans-serif;color:#546e7a">{i}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #eee;font:14px/1.45 sans-serif">'
            f'{nxt}{"<b style=color:#2e7d32>✓ Picked</b> · " if picked else ""}{vote_h}'
            f'<a href="{e(t["url"])}" style="font-weight:700">'
            f'{e(t["title"])}</a><br>{e(a.get("summary", ""))}<br><i>{e(a.get("angle", ""))}</i><br>'
            f'<span style="color:#777;font-size:12px">{e(", ".join(a.get("sectors", [])))} · {e(t["source"])} · '
            f'engagement {sc.get("engagement", 0):.2f} · novelty {sc.get("novelty", 0):.2f}</span><br>'
            f'<a href="{e(pick)}" style="display:inline-block;margin-top:6px;padding:4px 10px;background:#546e7a;'
            f'color:#fff;border-radius:4px;text-decoration:none">{label}</a> '
            f'<a href="{e(dismiss)}" style="margin-left:8px;color:#999">Dismiss</a></td></tr>')
        rows_t.append(f"{i}. {'[NEXT] ' if i == 1 else ''}{'[PICKED] ' if picked else ''}{t['title']}"
                      f"{f' — {nv} votes (+{new_v} new)' if nv else ''}\n   {a.get('summary', '')}\n   "
                      f"{', '.join(a.get('sectors', []))} · {t['url']}\n   {label}: {pick}\n   Dismiss: {dismiss}\n")
    foot = (f"The daily writer takes topics from the top (your picks first, then readers' votes, then rank) until "
            f"{settings()['posts']['buffer']} posts are approved or waiting for you. Each post arrives in its own email with Approve and Archive links; "
            f"one approved post goes live each day. Dismiss a topic to skip it. "
            f"Full queue: {base}/" + (f" · Sources not read this run: {', '.join(dead)}" if dead else ""))
    html = (f'<div style="max-width:680px;margin:auto"><h2 style="font:600 20px sans-serif">{e(subject)}</h2>'
            f'{p_html}<table style="border-collapse:collapse;width:100%">{"".join(rows_h)}</table>'
            f'<p style="font:12px sans-serif;color:#777">{e(foot)}</p></div>')
    text = (p_text + "\n\n" if p_text else "") + "\n".join(rows_t) + "\n" + foot
    return {"subject": subject, "html": html, "text": text, "count": len(q)}


def send(store: Store) -> str:
    telemetry.require_enabled("digest", actor="service:digest")
    mail = render(store)
    to = owner_email()
    if not to and mailer.configured():
        status = "not sent: no EDITORIAL_EMAIL / DIGEST_EMAIL"
    else:
        status = mailer.send(to or ["owner@localhost"], mail["subject"], mail["text"], mail["html"])
    store.run("digest", status, {"topics": mail["count"]})
    telemetry.record("digest", actor="service:digest", items=mail["count"], detail={"status": status})
    return status
