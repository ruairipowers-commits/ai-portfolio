"""Daily engagement: collect yesterday's numbers from every source, store them, email a summary.

Sources (each optional — a missing token is reported in the email, never an error):
  blog       page views, unique visitors, top pages and referrers   this service's /api/track log
  searches   site searches, assistant searches and questions         this service's log (text as typed)
  demos      runs, visitors, tokens and spend in the live demos      governance console /api/summary (live only)
  cloudflare requests, page views, unique visitors for the zone      CF_API_TOKEN (Analytics: Read) + CF_ZONE_ID
  github     repo views, clones (≈ downloads), stars, forks           GITHUB_TRAFFIC_TOKEN (Administration: read)

Email: the same SMTP_* settings as the governance console; to DIGEST_EMAIL (else GOVERNANCE_ALERT_EMAIL).
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import statistics
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape
from zoneinfo import ZoneInfo

import httpx

from .store import Store, now_iso


def yesterday(tz: str) -> str:
    return (datetime.now(ZoneInfo(tz)).date() - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- collectors
def collect_site(store: Store, day: str, top_n: int) -> None:
    rows = store.query("select kind, visitor, page, query, results, status, referrer from activity where day = ?", (day,))
    pv = [r for r in rows if r["kind"] == "pageview"]
    store.put_metric(day, "blog", "page_views", len(pv))
    store.put_metric(day, "blog", "visitors", len({r["visitor"] for r in pv}))
    store.put_metric(day, "blog", "top_pages", None, Counter(r["page"] for r in pv).most_common(top_n))
    store.put_metric(day, "blog", "referrers", None,
                     Counter(r["referrer"] for r in pv if r["referrer"]).most_common(top_n))
    srch = [r for r in rows if r["kind"] in ("search", "site-search")]
    asks = [r for r in rows if r["kind"] == "ask"]
    store.put_metric(day, "searches", "searches", len(srch))
    store.put_metric(day, "searches", "questions", len(asks))
    store.put_metric(day, "searches", "top_queries", None,
                     Counter(r["query"].strip().lower() for r in srch if r["query"].strip()).most_common(top_n))
    store.put_metric(day, "searches", "no_results", None,
                     sorted({r["query"] for r in srch if r["status"] == "no_results"})[:top_n])
    store.put_metric(day, "searches", "questions_asked", None, [r["query"] for r in asks][:top_n])


def collect_demos(store: Store, day: str) -> None:
    url = os.getenv("GOVERNANCE_URL", "").rstrip("/")
    if not url:
        store.put_metric(day, "demos", "status", None, "not configured (GOVERNANCE_URL)")
        return
    try:
        r = httpx.get(f"{url}/api/summary", params={"days": 1, "sim": 0, "end": day}, timeout=15)
        r.raise_for_status()
        s = r.json()
        k = s["kpi"]
        for m in ("visits", "runs", "users", "tokens", "cost", "decisions", "blocked", "escalated"):
            store.put_metric(day, "demos", m, k.get(m, 0))
        store.put_metric(day, "demos", "runs_by_workflow", None,
                         sorted(((wf, int(sum(v))) for wf, v in s["series"].get("runs", {}).items() if sum(v)),
                                key=lambda x: -x[1]))
        store.put_metric(day, "demos", "status", None, "ok")
    except Exception as e:  # noqa: BLE001
        store.put_metric(day, "demos", "status", None, f"error: {type(e).__name__}: {str(e)[:120]}")


CF_QUERY = """query Daily($zone: string, $from: Date, $to: Date) {
  viewer { zones(filter: {zoneTag: $zone}) {
    httpRequests1dGroups(limit: 2, filter: {date_geq: $from, date_leq: $to}) {
      dimensions { date }
      sum { requests pageViews bytes threats }
      uniq { uniques }
    } } } }"""


def collect_cloudflare(store: Store, day: str) -> None:
    tok, zone = os.getenv("CF_API_TOKEN"), os.getenv("CF_ZONE_ID")
    if not (tok and zone):
        store.put_metric(day, "cloudflare", "status", None, "not configured (CF_API_TOKEN, CF_ZONE_ID)")
        return
    try:
        r = httpx.post("https://api.cloudflare.com/client/v4/graphql", timeout=20,
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"query": CF_QUERY, "variables": {"zone": zone, "from": day, "to": day}})
        r.raise_for_status()
        d = r.json()
        if d.get("errors"):
            raise RuntimeError(d["errors"][0].get("message", "GraphQL error"))
        groups = d["data"]["viewer"]["zones"][0]["httpRequests1dGroups"]
        g = next((x for x in groups if x["dimensions"]["date"] == day), None)
        if g:
            store.put_metric(day, "cloudflare", "requests", g["sum"]["requests"])
            store.put_metric(day, "cloudflare", "page_views", g["sum"]["pageViews"])
            store.put_metric(day, "cloudflare", "visitors", g["uniq"]["uniques"])
            store.put_metric(day, "cloudflare", "threats", g["sum"].get("threats", 0))
        store.put_metric(day, "cloudflare", "status", None, "ok" if g else "no data for the day yet")
    except Exception as e:  # noqa: BLE001
        store.put_metric(day, "cloudflare", "status", None, f"error: {type(e).__name__}: {str(e)[:120]}")


def github_repos() -> list[str]:
    repos = [r.strip() for r in os.getenv("GITHUB_REPOS", "").split(",") if r.strip()]
    owner = os.getenv("PORTFOLIO_GITHUB_OWNER") or os.getenv("GITHUB_OWNER")
    return repos or ([f"{owner}/ai-portfolio"] if owner else [])


def collect_github(store: Store, day: str) -> None:
    tok, repos = os.getenv("GITHUB_TRAFFIC_TOKEN"), github_repos()
    if not (tok and repos):
        store.put_metric(day, "github", "status", None, "not configured (GITHUB_TRAFFIC_TOKEN, GITHUB_REPOS)")
        return
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tot = Counter()
    per_repo, errors = [], []
    for repo in repos:
        try:
            info = httpx.get(f"https://api.github.com/repos/{repo}", headers=h, timeout=15).json()
            views = httpx.get(f"https://api.github.com/repos/{repo}/traffic/views", headers=h, timeout=15)
            clones = httpx.get(f"https://api.github.com/repos/{repo}/traffic/clones", headers=h, timeout=15)
            views.raise_for_status(), clones.raise_for_status()
            v = next((x for x in views.json().get("views", []) if x["timestamp"][:10] == day), {})
            c = next((x for x in clones.json().get("clones", []) if x["timestamp"][:10] == day), {})
            row = {"repo": repo, "views": v.get("count", 0), "visitors": v.get("uniques", 0),
                   "clones": c.get("count", 0), "cloners": c.get("uniques", 0),
                   "stars": info.get("stargazers_count", 0), "forks": info.get("forks_count", 0)}
            per_repo.append(row)
            tot.update({k: row[k] for k in ("views", "visitors", "clones", "cloners", "stars", "forks")})
        except Exception as e:  # noqa: BLE001
            errors.append(f"{repo}: {type(e).__name__}: {str(e)[:80]}")
    for k in ("views", "visitors", "clones", "cloners", "stars", "forks"):
        store.put_metric(day, "github", k, tot[k])
    store.put_metric(day, "github", "repos", None, per_repo)
    store.put_metric(day, "github", "status", None, "ok" if not errors else "; ".join(errors))


def collect(store: Store, settings: dict, day: str) -> None:
    collect_site(store, day, settings["digest"]["top_n"])
    collect_demos(store, day)
    collect_cloudflare(store, day)
    collect_github(store, day)


# ---------------------------------------------------------------- the email
HEADLINES = [("blog", "page_views", "Blog page views"), ("blog", "visitors", "Blog visitors"),
             ("searches", "searches", "Searches"), ("searches", "questions", "Questions to the assistant"),
             ("demos", "visits", "Demo visits"), ("demos", "runs", "Demo runs"),
             ("cloudflare", "page_views", "Cloudflare page views"), ("cloudflare", "visitors", "Cloudflare visitors"),
             ("github", "views", "GitHub repo views"), ("github", "clones", "Repo clones (downloads)"),
             ("github", "stars", "GitHub stars (total)")]


def render(store: Store, day: str, settings: dict) -> dict:
    m = store.metrics(day)
    val = lambda s, k: (m.get((s, k)) or {}).get("value")          # noqa: E731
    det = lambda s, k: (m.get((s, k)) or {}).get("detail")         # noqa: E731
    rows_html, rows_text = [], []
    for s, k, label in HEADLINES:
        v = val(s, k)
        if v is None:
            continue
        hist = store.metric_history(s, k, 7, day)
        avg = statistics.mean(hist) if hist else None
        trend = "" if avg is None else (f"{'▲' if v > avg else '▼' if v < avg else '='} vs 7-day avg {avg:,.1f}")
        rows_html.append(f"<tr><td style='padding:5px 14px 5px 0'>{escape(label)}</td>"
                         f"<td style='padding:5px 14px 5px 0;text-align:right;font-weight:600'>{v:,.0f}</td>"
                         f"<td style='padding:5px 0;color:#5f6b76;font-size:13px'>{escape(trend)}</td></tr>")
        rows_text.append(f"{label}: {v:,.0f} {trend}")

    def lst(title, items, fmt=lambda x: escape(str(x))):
        if not items:
            return "", ""
        h = f"<h3 style='font-size:15px;margin:18px 0 6px'>{escape(title)}</h3><ul style='margin:0;padding-left:18px'>" + \
            "".join(f"<li style='margin:2px 0'>{fmt(i)}</li>" for i in items) + "</ul>"
        t = f"\n{title}:\n" + "\n".join(f"  - {i if not isinstance(i, (list, tuple)) else f'{i[0]} ({i[1]})'}"
                                         for i in items)
        return h, t

    pair = lambda i: f"{escape(str(i[0]) or '/')} <span style='color:#5f6b76'>({i[1]})</span>"   # noqa: E731
    sections = [lst("Top pages", det("blog", "top_pages"), pair), lst("Where readers came from", det("blog", "referrers"), pair),
                lst("Top searches", det("searches", "top_queries"), pair),
                lst("Searches with no results (content gaps)", det("searches", "no_results")),
                lst("Questions asked", det("searches", "questions_asked")),
                lst("Demo runs by app", det("demos", "runs_by_workflow"), pair),
                lst("GitHub by repo", [f"{r['repo']}: {r['views']} views, {r['clones']} clones, {r['stars']} stars"
                                       for r in det("github", "repos") or []])]
    notes = [f"{s}: {det(s, 'status')}" for s in ("demos", "cloudflare", "github") if det(s, "status") not in (None, "ok")]
    sec_html = "".join(h for h, _ in sections)
    sec_text = "".join(t for _, t in sections)
    note_html = ("<p style='color:#7b8794;font-size:12px;margin-top:18px'>Not included: " +
                 escape("; ".join(notes)) + "</p>") if notes else ""
    subject = f"Portfolio engagement for {datetime.fromisoformat(day):%a %d %b}: " + \
        f"{val('blog', 'page_views') or 0:,.0f} blog views · {val('demos', 'runs') or 0:,.0f} demo runs · " + \
        f"{(val('searches', 'searches') or 0) + (val('searches', 'questions') or 0):,.0f} searches & questions"
    html = f"""<!doctype html><html><body style="margin:0;background:#f3f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2933">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px"><tr><td align="center">
<table role="presentation" width="620" cellpadding="0" cellspacing="0" style="max-width:620px;background:#fff;border-radius:8px;border:1px solid #dde3e8">
<tr><td style="background:#546e7a;color:#fff;padding:14px 20px;font-size:14px;font-weight:600">AI workflow portfolio · daily engagement</td></tr>
<tr><td style="padding:18px 20px">
<h1 style="font-size:19px;margin:0 0 12px">{escape(datetime.fromisoformat(day).strftime('%A %d %B %Y'))}</h1>
<table role="presentation" style="font-size:14px">{''.join(rows_html)}</table>
{sec_html}{note_html}
</td></tr></table></td></tr></table></body></html>"""
    text = f"Portfolio engagement for {day}\n\n" + "\n".join(rows_text) + "\n" + sec_text + \
        ("\n\nNot included: " + "; ".join(notes) if notes else "")
    return {"subject": subject, "html": html, "text": text}


def recipients() -> list[str]:
    raw = os.getenv("DIGEST_EMAIL") or os.getenv("GOVERNANCE_ALERT_EMAIL") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def send(to: list[str], subject: str, text: str, html: str) -> None:
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"]
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.getenv("SMTP_FROM") or user, ", ".join(to), subject
    msg["Message-ID"], msg["Date"] = make_msgid(domain="site-assistant"), formatdate()
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            s.login(user, pw), s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            if os.getenv("SMTP_STARTTLS", "1") != "0":
                s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)


def run(store: Store, settings: dict, day: str | None = None, send_email: bool = True, **kw) -> dict:
    """Collect, store and (optionally) email one day's engagement. Default: yesterday in the digest timezone."""
    send_email = kw.get("send", send_email)
    day = day or yesterday(settings["digest"]["timezone"])
    collect(store, settings, day)
    mail = render(store, day, settings)
    to = recipients()
    status, error = "rendered", ""
    if send_email:
        if not to:
            status, error = "not sent", "no recipient (DIGEST_EMAIL or GOVERNANCE_ALERT_EMAIL)"
        elif not (os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD")):
            status, error = "not sent", "SMTP not configured"
        else:
            try:
                send(to, mail["subject"], mail["text"], mail["html"])
                status = "sent"
            except Exception as e:  # noqa: BLE001
                status, error = "failed", f"{type(e).__name__}: {str(e)[:200]}"
    store.add_digest(day, to, mail["subject"], status, error, mail["html"])
    return {"day": day, "status": status, "error": error, "subject": mail["subject"], "html": mail["html"]}


def start_scheduler(get_store, settings: dict) -> threading.Thread:
    """Once a day at digest.hour (local time in digest.timezone): yesterday's numbers, emailed once."""
    def loop():
        while True:
            try:
                tz = ZoneInfo(settings["digest"]["timezone"])
                now = datetime.now(tz)
                day = yesterday(settings["digest"]["timezone"])
                if now.hour >= settings["digest"]["hour"] and not get_store().digest_sent(day):
                    attempts = get_store().query("select count(*) n from digests where day = ?", (day,))[0]["n"]
                    if attempts < 3:
                        run(get_store(), settings, day, send_email=True)
            except Exception as e:  # noqa: BLE001
                print(f"digest failed: {e}")
            time.sleep(600)
    t = threading.Thread(target=loop, daemon=True, name="digest")
    t.start()
    return t


# ---------------------------------------------------------------- owner's page
def stats_page(store: Store, settings: dict, base: str, token: str) -> str:
    days = [r["day"] for r in store.query("select distinct day from activity order by day desc limit 14")]
    rows = []
    for d in days:
        c = Counter(r["kind"] for r in store.query("select kind from activity where day = ?", (d,)))
        v = store.query("select count(distinct visitor) n from activity where day = ? and kind = 'pageview'", (d,))[0]["n"]
        rows.append(f"<tr><td>{d}</td><td>{c['pageview']}</td><td>{v}</td><td>{c['site-search'] + c['search']}</td>"
                    f"<td>{c['ask']}</td></tr>")
    recent = store.query("select ts, kind, query, results, status, page from activity where kind in "
                         "('search', 'site-search', 'ask') order by ts desc limit 60")
    digests = store.query("select ts, day, recipients, subject, status, error from digests order by ts desc limit 14")
    tq = escape(token)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Site assistant · activity</title><style>body{{font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:20px 16px;color:#1f2933}}
table{{border-collapse:collapse;width:100%;margin:8px 0 22px}}td,th{{border-bottom:1px solid #e3e7eb;padding:5px 8px;text-align:left;vertical-align:top}}
th{{color:#5f6b76;font-weight:600}}h1{{font-size:21px}}h2{{font-size:16px;margin-top:22px}}button{{font:inherit;padding:6px 12px}}</style></head><body>
<h1>Site assistant · activity</h1>
<p>Index: {store.passage_count()} passages from the blog · last refresh {escape(str((store.last_index() or {}).get('ts', '—')))}</p>
<form method="post" action="{base}/digest/send?token={tq}"><button>Send yesterday's engagement email now</button></form>
<h2>Last 14 days</h2><table><tr><th>Day (UTC)</th><th>Page views</th><th>Visitors</th><th>Searches</th><th>Questions</th></tr>{''.join(rows)}</table>
<h2>Recent searches and questions</h2><table><tr><th>Time (UTC)</th><th>Kind</th><th>Query</th><th>Results</th><th>Status</th><th>Page</th></tr>
{''.join(f"<tr><td>{r['ts'][5:16].replace('T', ' ')}</td><td>{r['kind']}</td><td>{escape(r['query'] or '')}</td><td>{r['results']}</td><td>{escape(r['status'] or '')}</td><td>{escape(r['page'] or '')}</td></tr>" for r in recent)}</table>
<h2>Engagement emails</h2><table><tr><th>Sent (UTC)</th><th>For</th><th>To</th><th>Subject</th><th>Status</th></tr>
{''.join(f"<tr><td>{r['ts'][5:16].replace('T', ' ')}</td><td>{r['day']}</td><td>{escape(r['recipients'] or '')}</td><td>{escape(r['subject'] or '')}</td><td>{escape(r['status'])} {escape(r['error'] or '')}</td></tr>" for r in digests)}</table>
</body></html>"""
