"""Getting a governance issue in front of a person: email now; PagerDuty / ServiceNow tickets as a documented design.

Every notification is written to the console's outbox (the `notifications` table, Settings → Outbox) first, then
delivered. So the console always shows exactly what was sent, to whom, and whether delivery worked — and with no
SMTP configured it still works end to end, just without leaving the machine.

Email settings (environment only — never config files):
  SMTP_HOST       e.g. smtp.gmail.com            SMTP_PORT  587 (STARTTLS) or 465 (TLS)
  SMTP_USER       the account                     SMTP_PASSWORD  for Gmail, an app password (not the account password)
  SMTP_FROM       defaults to SMTP_USER           GOVERNANCE_ALERT_EMAIL  default recipient(s), comma-separated

Tickets (not implemented — `ticket_payload()` builds what would be sent so the mapping is reviewable and tested):
  PagerDuty Events API v2   POST https://events.pagerduty.com/v2/enqueue      routing key in PAGERDUTY_ROUTING_KEY
  ServiceNow Table API      POST https://<instance>.service-now.com/api/now/table/incident   basic auth or OAuth
"""
from __future__ import annotations

import os
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

SEVERITY_COLOR = {"low": "#607d8b", "medium": "#b26a00", "high": "#c62828", "critical": "#7b1fa2"}


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def smtp_summary() -> str:
    if not smtp_configured():
        return "not configured — emails are kept in the outbox only"
    return f"{os.getenv('SMTP_USER')} via {os.getenv('SMTP_HOST')}:{os.getenv('SMTP_PORT', '587')}"


def default_recipients() -> list[str]:
    return [a.strip() for a in os.getenv("GOVERNANCE_ALERT_EMAIL", "").split(",") if a.strip()]


# ---------------------------------------------------------------- the email itself
def incident_email(inc: dict, rule: dict, wf_name: str, owner: str, url: str, shutdown: str, app_url: str = "") -> dict:
    """Subject, plain text and HTML for one incident. `url` is the incident's page in the console."""
    ev = (inc.get("evidence") or [{}])[-1]
    facts = [("Workflow", wf_name), ("Severity", inc["severity"].upper()), ("Control", inc.get("control_id") or "—"),
             ("Detected", inc["opened_at"].replace("T", " ")[:19] + " UTC"), ("Owner", owner),
             ("Triggered by", f"{ev.get('actor') or 'unknown'} · {ev.get('event_type', '')} · run {ev.get('run_id') or '—'}"),
             ("Signals", ", ".join(ev.get("flags") or []) or "—"),
             ("Workflow state", shutdown)]
    subject = f"[{inc['severity'].upper()}] {inc['incident_id']} {wf_name}: {inc['title']}"
    text = "\n".join([
        f"Governance issue {inc['incident_id']} — {inc['title']}", "",
        *(f"{k}: {v}" for k, v in facts), "",
        "What happened:", inc.get("summary") or "", "",
        "What to do:", rule.get("guidance", ""), "",
        f"Open the incident: {url}",
        *([f"Open the workflow: {app_url}"] if app_url else []), "",
        "You're receiving this because you're on the escalation list for this workflow in the AI governance console.",
    ])
    color = SEVERITY_COLOR.get(inc["severity"], "#546e7a")
    rows = "".join(f'<tr><td style="padding:4px 12px 4px 0;color:#5f6b76;white-space:nowrap;vertical-align:top">{escape(k)}</td>'
                   f'<td style="padding:4px 0">{escape(str(v))}</td></tr>' for k, v in facts)
    html = f"""<!doctype html><html><body style="margin:0;background:#f3f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2933">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #dde3e8">
<tr><td style="background:#546e7a;color:#fff;padding:14px 20px;font-size:14px;font-weight:600">◆ AI Governance Console</td></tr>
<tr><td style="padding:20px 20px 4px">
  <span style="display:inline-block;background:{color};color:#fff;font-size:12px;font-weight:700;padding:3px 8px;border-radius:4px">{escape(inc['severity'].upper())}</span>
  <span style="font-size:13px;color:#5f6b76;margin-left:6px">{escape(inc['incident_id'])} · {escape(inc.get('control_id') or '')}</span>
  <h1 style="font-size:20px;line-height:1.3;margin:10px 0 6px">{escape(inc['title'])}</h1>
  <p style="margin:0 0 12px;font-size:15px">{escape(wf_name)}</p>
  {f'<p style="margin:0 0 14px;padding:10px 12px;background:#fdecea;border-left:4px solid #c62828;font-size:14px"><b>Workflow switched off automatically.</b> The app refuses new runs until someone reviews this incident and switches it back on.</p>' if inc.get('auto_shutdown') else ''}
  <p style="font-size:14px;line-height:1.5;margin:0 0 14px">{escape(inc.get('summary') or '')}</p>
  <table role="presentation" style="font-size:14px;margin:0 0 16px">{rows}</table>
  <p style="font-size:14px;line-height:1.5;margin:0 0 18px"><b>What to do.</b> {escape(rule.get('guidance', ''))}</p>
  <p style="margin:0 0 22px"><a href="{escape(url)}" style="background:#546e7a;color:#fff;text-decoration:none;padding:10px 16px;border-radius:6px;font-weight:600;font-size:14px;display:inline-block">Review incident {escape(inc['incident_id'])}</a>
  {f'&nbsp; <a href="{escape(app_url)}" style="color:#37474f;font-size:14px">Open the workflow</a>' if app_url else ''}</p>
</td></tr>
<tr><td style="padding:12px 20px;background:#f7f9fa;color:#7b8794;font-size:12px">You're on the escalation list for this workflow in the AI governance console. Change who gets these on its Settings page.</td></tr>
</table></td></tr></table></body></html>"""
    return {"subject": subject, "text": text, "html": html}


def send_email(recipients: list[str], subject: str, text: str, html: str) -> None:
    """Send through SMTP (STARTTLS on 587, implicit TLS on 465). Raises on failure."""
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"]
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.getenv("SMTP_FROM") or user, ", ".join(recipients), subject
    msg["Message-ID"] = make_msgid(domain="governance-console")
    msg["Date"] = formatdate(localtime=False)
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
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)


def deliver(store, nid: str, recipients: list[str], mail: dict, background: bool = True) -> None:
    """Send an outbox entry and record the result on it. In the background by default: never slows ingest."""
    def run():
        try:
            send_email(recipients, mail["subject"], mail["text"], mail["html"])
            store.set_notification_status(nid, "sent")
        except Exception as e:  # noqa: BLE001 — any delivery failure is recorded, never raised into the app
            store.set_notification_status(nid, "failed", f"{type(e).__name__}: {str(e)[:200]}")
    threading.Thread(target=run, daemon=True).start() if background else run()


# ---------------------------------------------------------------- tickets (design only)
PD_SEVERITY = {"low": "info", "medium": "warning", "high": "error", "critical": "critical"}
SN_IMPACT = {"low": "3", "medium": "2", "high": "1", "critical": "1"}


def ticket_payload(channel: str, inc: dict, wf_name: str, url: str) -> dict:
    """What the console would POST for a ticket. Not sent anywhere: the channels are a documented integration
    option (docs/integrations.md). Deduplicated per incident, so repeats update one ticket instead of opening more."""
    if channel == "pagerduty":
        return {"routing_key": "$PAGERDUTY_ROUTING_KEY", "event_action": "trigger", "dedup_key": inc["incident_id"],
                "payload": {"summary": f"{wf_name}: {inc['title']}"[:1024], "source": inc["workflow"],
                            "severity": PD_SEVERITY[inc["severity"]], "component": inc["workflow"],
                            "group": inc.get("control_id") or "", "class": inc["rule_id"],
                            "custom_details": {"incident": inc["incident_id"], "summary": inc.get("summary"),
                                               "auto_shutdown": bool(inc.get("auto_shutdown"))}},
                "links": [{"href": url, "text": f"Governance console {inc['incident_id']}"}]}
    if channel == "servicenow":
        return {"short_description": f"[{inc['incident_id']}] {wf_name}: {inc['title']}"[:160],
                "description": f"{inc.get('summary') or ''}\n\nControl: {inc.get('control_id')}\nConsole: {url}",
                "impact": SN_IMPACT[inc["severity"]], "urgency": SN_IMPACT[inc["severity"]],
                "category": "AI governance", "cmdb_ci": inc["workflow"], "correlation_id": inc["incident_id"],
                "assignment_group": "$SERVICENOW_ASSIGNMENT_GROUP"}
    raise ValueError(f"unknown ticket channel {channel}")
