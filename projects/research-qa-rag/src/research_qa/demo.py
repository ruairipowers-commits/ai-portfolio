"""Live-demo support: links back to the portfolio, and a private sandbox per visitor.

Run locally, nothing changes: `current()` is None and every path resolves under the project root.

In the hosted demo (Hugging Face Space) the image sets PORTFOLIO_DEMO=1. Each browser session then
gets its own copy of the mutable demo data (`MUTABLE`), made from the pre-built copy in the image,
so one visitor's edits, resets or approvals never change what another visitor sees. Sandboxes idle
for more than DEMO_SESSION_TTL_HOURS are deleted; reloading the page starts a fresh one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from contextvars import ContextVar
from pathlib import Path

PROJECT = "research-qa-rag"
MUTABLE = ("warehouse", "data", "output")   # relative to the project root
LINK_KEYS = ("blog_url", "source_url", "portfolio_url", "demo_url", "console_url")

_workspace: ContextVar[Path | None] = ContextVar(f"{PROJECT}-workspace", default=None)


def enabled() -> bool:
    return os.getenv("PORTFOLIO_DEMO") == "1"


def current() -> Path | None:
    """This session's sandbox, or None when running normally."""
    return _workspace.get()


def _sessions_dir() -> Path:
    return Path(os.getenv("DEMO_SESSIONS_DIR", "/tmp/demo-sessions")) / PROJECT


def _prune(base: Path) -> None:
    ttl = float(os.getenv("DEMO_SESSION_TTL_HOURS", "3")) * 3600
    keep = int(os.getenv("DEMO_MAX_SESSIONS", "40"))
    dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for i, d in enumerate(dirs):
        if i >= keep or time.time() - d.stat().st_mtime > ttl:
            shutil.rmtree(d, ignore_errors=True)


def activate(session_id: str, root: Path) -> Path:
    """Point this script run at the visitor's sandbox, creating it from the baseline on first use."""
    base = _sessions_dir()
    d = base / (re.sub(r"[^A-Za-z0-9-]", "", session_id) or "anon")
    if not (d / ".ready").exists():
        base.mkdir(parents=True, exist_ok=True)
        _prune(base)
        for rel in MUTABLE:
            src = root / rel
            if src.is_dir():
                shutil.copytree(src, d / rel, dirs_exist_ok=True)
            elif src.exists():
                (d / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, d / rel)
        d.mkdir(parents=True, exist_ok=True)
        (d / ".ready").touch()
    os.utime(d)   # last activity, for pruning
    _workspace.set(d)
    return d


def activate_streamlit(root: Path) -> Path | None:
    """Call at the top of the Streamlit script; a no-op unless PORTFOLIO_DEMO=1."""
    if not enabled():
        return None
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    ctx = get_script_run_ctx()
    return activate(ctx.session_id if ctx else "anon", root)


# ---------------------------------------------------------------- links back to the portfolio
def links(root: Path) -> dict[str, str]:
    """Write-up, source and demo URLs: env PORTFOLIO_<KEY> first, then portfolio_links.json
    (written by the portfolio's publish script). Missing ones are simply not shown."""
    file = root / "portfolio_links.json"
    data = json.loads(file.read_text()) if file.exists() else {}
    out = {}
    for k in LINK_KEYS:
        v = os.getenv("PORTFOLIO_" + k.upper()) or data.get(k, "")
        if v and "REPLACE" not in v and "{{" not in v:
            out[k] = v
    return out


def links_markdown(root: Path) -> str:
    l = links(root)
    parts = [f"📝 [Blog post]({l['blog_url']})" if "blog_url" in l else "",
             f"💻 [Source code]({l['source_url']})" if "source_url" in l else "",
             f"🌐 [Portfolio]({l['portfolio_url']})" if "portfolio_url" in l else "",
             f"🛡️ [Governance console]({l['console_url']})" if "console_url" in l else ""]
    return " · ".join(p for p in parts if p)


def sidebar(st, root: Path) -> None:
    """Links back to the write-up and repo, plus what visitors to the hosted demo should know."""
    md = links_markdown(root)
    if md:
        st.sidebar.markdown(f"**About this project**  \n{md}")
    if enabled():
        st.sidebar.info("Public demo: runs the free offline mock model (no API keys). You have your own copy "
                        "of the data — nothing you change affects other visitors. Reloading the page starts fresh.",
                        icon="🧪")
