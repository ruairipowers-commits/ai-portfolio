"""Outside-in uptime check of the blog and every live demo (run by .github/workflows/uptime.yml every 30 minutes).

    SITE_URL=… DEMOS_URL=… python3 scripts/uptime.py [--out FILE]   # exit 1 if anything is down
    python3 scripts/uptime.py --email FILE                           # mail FILE to ALERT_EMAIL via SMTP_*

What "up" means: the blog home page answers 200; the demos landing page answers 200; the governance console and
the site assistant answer /api/health with {"ok": true}; each Streamlit app answers /_stcore/health with "ok".
Standard library only (plus PyYAML to read the app list from the specs, like scripts/demos.py).
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-portfolio-uptime/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def checks(site: str, demos: str) -> list[tuple[str, str, callable]]:
    out = [("blog", site.rstrip("/") + "/", lambda c, b: c == 200)]
    if demos:
        from demos import CONSOLE, apps
        d = demos.rstrip("/")
        out.append(("demos home", d + "/", lambda c, b: c == 200))
        for a in apps():
            if a["kind"] == "fastapi":
                out.append((a["slug"], f"{d}/{a['slug']}/api/health",
                            lambda c, b: c == 200 and json.loads(b or "{}").get("ok") is True))
            else:
                out.append((a["slug"], f"{d}/{a['slug']}/_stcore/health", lambda c, b: c == 200 and b.strip() == "ok"))
    return out


def run(site: str, demos: str) -> tuple[bool, str]:
    lines, ok = [], True
    home_down = False
    for name, url, good in checks(site, demos):
        if home_down:                      # the whole machine is unreachable: don't wait on every app
            lines.append(f"SKIP  {name:<22} {'-':<9} {url}")
            continue
        code, body = get(url)
        if not good(code, body):          # one retry: a single slow response isn't an outage
            time.sleep(20)
            code, body = get(url)
        up = good(code, body)
        ok &= up
        home_down = name == "demos home" and not up
        lines.append(f"{'UP  ' if up else 'DOWN'}  {name:<22} {code or 'no answer':<9} {url}"
                     + ("" if up or code else f"  ({body[:120]})"))
    if not demos:
        lines.append("note: DEMOS_URL not set — only the blog was checked")
    head = "Everything is up." if ok else "Something is DOWN. What to try, on the demo machine:\n" \
        "  1. Is it awake and online? (Tailscale / ping)   2. deploy/selfhost/update.sh --status\n" \
        "  3. docker compose -f deploy/selfhost/generated/docker-compose.yml --env-file deploy/selfhost/.env ps\n" \
        "  4. journalctl -u ai-portfolio-demos -n 50      5. sudo systemctl restart docker  (last resort: reboot)"
    return ok, head + "\n\n" + "\n".join(lines)


def email(path: str) -> None:
    to = os.environ.get("ALERT_EMAIL") or os.environ.get("SMTP_FROM") or ""
    msg = EmailMessage()
    msg["Subject"] = "Portfolio uptime: something is down"
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ["SMTP_USER"]
    msg["To"] = to
    msg.set_content(Path(path).read_text() if Path(path).exists() else "The uptime check failed before it could report.")
    port = int(os.environ.get("SMTP_PORT") or 587)
    with (smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, timeout=30) if port == 465
          else smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=30)) as s:
        if port != 465:
            s.starttls(context=ssl.create_default_context())
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def main(argv: list[str]) -> int:
    if "--email" in argv:
        email(argv[argv.index("--email") + 1])
        return 0
    site = os.environ.get("SITE_URL") or ""
    if not site and "/" in os.environ.get("GITHUB_REPOSITORY", ""):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        site = f"https://{owner}.github.io/{repo}"
    ok, report = run(site, os.environ.get("DEMOS_URL", ""))
    print(report)
    if "--out" in argv:
        Path(argv[argv.index("--out") + 1]).write_text(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
