"""Email to the owner: SMTP from the environment (the same Resend SMTP values as the rest of the demo host), or,
offline, a file in warehouse/outbox/ so the demo and tests can read what would have been sent."""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import data_dir


def configured() -> bool:
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send(to: list[str], subject: str, text: str, html: str) -> str:
    """Returns 'sent', 'written' (outbox file) or raises."""
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "editorial-agents@localhost"
    msg["To"], msg["Subject"] = ", ".join(to), subject
    msg["Message-ID"], msg["Date"] = make_msgid(domain="editorial-agents"), formatdate()
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if not configured():
        d = data_dir() / "outbox"
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.eml"))) + 1
        (d / f"{n:04d}-{re.sub(r'[^a-z0-9]+', '-', subject.lower())[:50]}.eml").write_bytes(bytes(msg))
        return "written"
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
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
