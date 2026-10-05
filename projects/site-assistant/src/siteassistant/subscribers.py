"""Blog subscriptions: double opt-in, one email per new post, one-click unsubscribe (DATA-03).

  subscribe(email, roles) → a pending row and ONE confirmation email. `roles` (from the site's audiences) limits
                       which posts they get; empty means every post. Changeable later from a link in every email. The response never says whether the address was
                       already subscribed (no address enumeration). Unconfirmed rows are deleted after a week.
  confirm(token)     → confirmed. Only confirmed addresses get post emails.
  unsubscribe(token) → the row is deleted, not just flagged. The token is an HMAC of the subscriber id, so the
                       address itself never appears in a link.
  notify(pages)      → called after each hourly index refresh: any post on the live site that hasn't been announced
                       yet is emailed (intro + link) to every confirmed subscriber whose roles match the post's
                       audience (or who chose none), one message each, at most
                       `max_posts_per_run` posts per run. The first run only records what's already published.

Addresses are used for nothing else: never logged, never sent to the governance console (counts only), never shared.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import telemetry

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")



def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _secret() -> bytes:
    s = os.getenv("SUBSCRIBE_SECRET") or os.getenv("ASSISTANT_ADMIN_TOKEN") or os.getenv("GOVERNANCE_ADMIN_TOKEN") or ""
    if not s and os.getenv("PORTFOLIO_DEMO") == "1":
        raise RuntimeError("SUBSCRIBE_SECRET (or ASSISTANT_ADMIN_TOKEN) is required to sign unsubscribe links")
    return (s or "dev-only-not-secret").encode()


def unsubscribe_token(sid: int) -> str:
    return f"{sid}.{hmac.new(_secret(), f'unsub:{sid}'.encode(), hashlib.sha256).hexdigest()[:32]}"


def _sid_from(token: str) -> int | None:
    try:
        sid = int(token.split(".", 1)[0])
    except ValueError:
        return None
    return sid if hmac.compare_digest(unsubscribe_token(sid), token) else None


def public_base() -> str:
    """Where the service is reached from email links."""
    if os.getenv("ASSISTANT_PUBLIC_URL"):
        return os.environ["ASSISTANT_PUBLIC_URL"].rstrip("/")
    demos = os.getenv("PORTFOLIO_DEMOS_URL", "")
    return (demos.rstrip("/") + (os.getenv("ROOT_PATH") or "/site-assistant")) if demos else "http://localhost:8790"


def init(store) -> None:
    """Tables live in store.SCHEMA (created with the store); nothing else to set up."""


def known_roles(store) -> list[str]:
    """The site's audiences, in the site's order (published in assistant/corpus.json); else those used by posts."""
    roles = store.get_kv("audiences", []) or []
    if roles:
        return list(roles)
    seen: dict[str, None] = {}
    for meta in (store.get_kv("pages", {}) or {}).values():
        for a in meta.get("audience") or []:
            seen[a] = None
    return list(seen)


def clean_roles(store, roles) -> list[str]:
    allowed = known_roles(store)
    return [r for r in allowed if r in set(roles or [])]       # only real roles, in the site's order


def subscribe(store, email: str, roles: list[str] | None = None) -> str:
    """Returns 'sent', 'already', 'invalid' — the caller shows the same message for sent and already.
    A confirmed subscriber who signs up again with different roles gets a confirmation to apply them (the roles
    only change once they click it, so nobody can change someone else's choice)."""
    email = (email or "").strip().lower()
    if not EMAIL.match(email):
        return "invalid"
    chosen = json.dumps(clean_roles(store, roles))
    row = store.query("select id, status, roles from subscribers where email = ?", (email,))
    if row and row[0]["status"] == "confirmed" and (row[0]["roles"] or "[]") == chosen:
        return "already"
    token = secrets.token_urlsafe(24)
    h = hashlib.sha256(token.encode()).hexdigest()
    if row and row[0]["status"] == "confirmed":        # keep them subscribed; the new roles wait for the click
        store.set_kv(f"pending_roles:{h}", {"id": row[0]["id"], "roles": json.loads(chosen)})
        store.execute("update subscribers set confirm_hash = ? where id = ?", (h, row[0]["id"]))
    elif row:
        store.execute("update subscribers set confirm_hash = ?, created_at = ?, roles = ? where id = ?",
                      (h, now(), chosen, row[0]["id"]))
    else:
        store.execute("insert into subscribers (email, status, confirm_hash, created_at, roles) "
                      "values (?, 'pending', ?, ?, ?)", (email, h, now(), chosen))
    link = f"{public_base()}/subscribe/confirm?t={token}"
    site = os.getenv("PORTFOLIO_SITE_URL", "").rstrip("/") or "the blog"
    which = json.loads(chosen)
    scope = f" (posts for: {', '.join(which)})" if which else ""
    text = (f"Please confirm you'd like an email when a new post is published on {site}{scope}.\n\nConfirm: {link}\n\n"
            "If you didn't ask for this, ignore this email: nothing more will be sent, and the address is deleted "
            "within a week.\n")
    page = (f"<p>Please confirm you'd like an email when a new post is published on "
            f"<a href='{html.escape(site)}'>{html.escape(site)}</a>{html.escape(scope)}.</p><p><a href='{html.escape(link)}' "
            f"style='display:inline-block;padding:8px 14px;background:#546e7a;color:#fff;border-radius:4px;"
            f"text-decoration:none'>Confirm my subscription</a></p><p style='color:#777;font-size:13px'>If you didn't "
            f"ask for this, ignore this email: nothing more will be sent, and the address is deleted within a week.</p>")
    status = send(email, "Confirm your subscription", text, page)
    telemetry.record("subscribe", items=1, detail={"status": status})
    return "sent"


def confirm(store, token: str) -> list[str] | None:
    """Confirms the address (or a confirmed subscriber's new roles). Returns their roles ([] = every post), or None."""
    h = hashlib.sha256((token or "").encode()).hexdigest()
    row = store.query("select id, status, roles from subscribers where confirm_hash = ?", (h,))
    if not row:
        return None
    r = row[0]
    if r["status"] == "confirmed":
        change = store.get_kv(f"pending_roles:{h}") or {}
        roles = change.get("roles", json.loads(r["roles"] or "[]"))
        store.execute("update subscribers set roles = ?, confirm_hash = null where id = ?", (json.dumps(roles), r["id"]))
        store.execute("delete from kv where key = ?", (f"pending_roles:{h}",))
        return roles
    store.execute("update subscribers set status = 'confirmed', confirmed_at = ?, confirm_hash = null where id = ?",
                  (now(), r["id"]))
    telemetry.record("subscribe_confirm", items=1)
    return json.loads(r["roles"] or "[]")


def roles_for(store, token: str) -> list[str] | None:
    sid = _sid_from(token or "")
    row = store.query("select roles from subscribers where id = ? and status = 'confirmed'", (sid,)) if sid else []
    return json.loads(row[0]["roles"] or "[]") if row else None


def set_roles(store, token: str, roles: list[str]) -> bool:
    if roles_for(store, token) is None:
        return False
    store.execute("update subscribers set roles = ? where id = ?",
                  (json.dumps(clean_roles(store, roles)), _sid_from(token)))
    telemetry.record("subscribe_roles", items=1)
    return True


def wants(sub_roles: str | None, audience: list[str]) -> bool:
    chosen = json.loads(sub_roles or "[]")
    return not chosen or bool(set(chosen) & set(audience or []))


def unsubscribe(store, token: str) -> bool:
    sid = _sid_from(token or "")
    if sid is None:
        return False
    store.execute("delete from subscribers where id = ?", (sid,))
    telemetry.record("unsubscribe", items=1)
    return True


def purge_pending(store, days: int = 7) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    store.execute("delete from subscribers where status = 'pending' and created_at < ?", (cutoff,))


def counts(store) -> dict:
    rows = store.query("select status, count(*) n from subscribers group by status")
    out = {r["status"]: r["n"] for r in rows}
    by_role: dict[str, int] = {}
    for r in store.query("select roles from subscribers where status = 'confirmed'"):
        for role in json.loads(r["roles"] or "[]") or ["Every post"]:
            by_role[role] = by_role.get(role, 0) + 1
    out["by_role"] = by_role                     # counts only: the console never sees an address
    return out


def notify(store, pages: dict, site_url: str, max_posts: int = 2) -> list[str]:
    """Email confirmed subscribers about posts not announced yet. Returns the paths announced this run."""
    if not pages:
        return []
    known = {r["path"] for r in store.query("select path from announced")}
    if not store.get_kv("subscriptions_seeded"):              # first run: don't announce the back catalogue
        for p in pages:
            store.execute("insert or ignore into announced (path, ts) values (?, ?)", (p, now()))
        store.set_kv("subscriptions_seeded", now())
        return []
    new = sorted((p for p in pages if p not in known), key=lambda p: pages[p].get("date", ""), reverse=True)[:max_posts]
    subs = store.query("select id, email, roles from subscribers where status = 'confirmed'")
    for path in new:
        page = pages[path]
        url = f"{site_url.rstrip('/')}/{path}"
        sent = 0
        for s in subs:
            if not wants(s.get("roles"), page.get("audience") or []):
                continue
            tok = unsubscribe_token(s["id"])
            unsub = f"{public_base()}/unsubscribe?t={tok}"
            prefs = f"{public_base()}/subscribe/roles?t={tok}"
            text = (f"{page.get('title', '')}\n\n{page.get('intro', '')}\n\nRead it: {url}\n\n"
                    f"You're getting this because you subscribed to new posts. Choose which roles' posts you get: "
                    f"{prefs}\nUnsubscribe: {unsub}\n")
            body = (f"<div style='max-width:620px;font:15px/1.5 sans-serif'><h2 style='font-weight:600'>"
                    f"{html.escape(page.get('title', ''))}</h2><p>{html.escape(page.get('intro', ''))}</p>"
                    f"<p><a href='{html.escape(url)}' style='display:inline-block;padding:8px 14px;background:#546e7a;"
                    f"color:#fff;border-radius:4px;text-decoration:none'>Read the post</a></p>"
                    f"<p style='color:#777;font-size:12px'>You're getting this because you subscribed to new posts. "
                    f"<a href='{html.escape(prefs)}'>Choose which roles' posts you get</a> · "
                    f"<a href='{html.escape(unsub)}'>Unsubscribe</a> — one click, and your address is deleted.</p></div>")
            if send(s["email"], f"New post: {page.get('title', '')}", text, body, unsubscribe_url=unsub) in ("sent", "written"):
                sent += 1
        store.execute("insert or replace into announced (path, ts, recipients) values (?, ?, ?)", (path, now(), sent))
        telemetry.record("announce", items=sent, detail={"path": path})
    return new


def send(to: str, subject: str, text: str, page: str, unsubscribe_url: str | None = None) -> str:
    """One message to one person (never a shared To/Cc list). Offline: written to warehouse/outbox."""
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "blog@localhost"
    msg["To"], msg["Subject"] = to, subject
    msg["Message-ID"], msg["Date"] = make_msgid(domain="site-assistant"), formatdate()
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    if not all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")):
        from .store import db_path
        from pathlib import Path
        d = Path(db_path()).parent / "outbox"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{len(list(d.glob('*.eml'))) + 1:05d}.eml").write_bytes(bytes(msg))
        return "written"
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                s.send_message(msg)
        return "sent"
    except Exception as e:  # noqa: BLE001 — one bad address must not stop the others
        print(f"subscriber email failed: {type(e).__name__}")
        return "failed"
