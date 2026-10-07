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

PROJECT = "launch-tracker"
MUTABLE = ("warehouse", "output", "logs")   # relative to the project root
LINK_KEYS = ("blog_url", "source_url", "portfolio_url", "demo_url", "console_url",
             "site_title", "standard_url", "blog_index_url", "about_url", "demos_home_url")

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


# ---------------------------------------------------------------- the banner shared with the blog
BAR_TOP, BAR_TABS = 48, 40          # px: the blog's (MkDocs Material) header row and tabs row
BAR_COLOR = "#546e7a"               # Material "blue grey", the blog's primary colour (mkdocs.yml)
_LOGO = ("M12 8a3 3 0 0 0 3-3 3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0 3 3m0 3.54C9.64 9.35 6.5 8 3 8v11c3.5 0 "
         "6.64 1.35 9 3.54 2.36-2.19 5.5-3.54 9-3.54V8c-3.5 0-6.64 1.35-9 3.54Z")


def banner_html(root: Path, title: str) -> str:
    """The blog's header (site name + Home · Governance · Blog · About tabs) as a fixed bar, plus a Live demos tab
    (active) and this project's write-up and source. Empty when the portfolio links aren't known (e.g. a plain local
    checkout), so a local run looks exactly as before."""
    from html import escape
    l = links(root)
    if "portfolio_url" not in l:
        return ""
    a = lambda href, text, cls="": f'<a class="{cls}" href="{escape(href)}" target="_top">{escape(text)}</a>'
    tabs = [("portfolio_url", "Home"), ("standard_url", "Governance"), ("blog_index_url", "Blog"),
            ("about_url", "About")]
    nav = "".join(a(l[k], t) for k, t in tabs if k in l)
    nav += a(l.get("demos_home_url") or l.get("demo_url", "#"), "Live demos", "on")
    side = "".join(a(l[k], t, "pill") for k, t in (("blog_url", "Write-up"), ("source_url", "Source code"),
                                                 ("console_url", "Governance console")) if k in l)
    h = BAR_TOP + BAR_TABS
    css = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap');
.pf-bar{{position:fixed;top:0;left:0;right:0;z-index:1000001;background:{BAR_COLOR};color:#fff;
 font-family:Roboto,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
 box-shadow:0 0 .2rem rgba(0,0,0,.1),0 .2rem .4rem rgba(0,0,0,.2)}}
.pf-bar a{{color:inherit;text-decoration:none}}
.pf-row{{display:flex;align-items:center;gap:.9rem;height:{BAR_TOP}px;padding:0 1.2rem}}
.pf-row svg{{width:24px;height:24px;fill:currentColor;flex:none}}
.pf-site{{font-weight:700;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pf-app{{font-size:16px;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pf-side{{margin-left:auto;display:flex;gap:.5rem;flex:none}}
.pf-bar a.pill{{font-size:13px;padding:.2rem .65rem;border:1px solid rgba(255,255,255,.45);border-radius:2rem}}
.pf-bar a.pill:hover{{background:rgba(255,255,255,.12)}}
.pf-tabs{{display:flex;gap:1.6rem;height:{BAR_TABS}px;align-items:center;padding:0 1.2rem 0 calc(1.2rem + 24px + .9rem);
 overflow-x:auto;scrollbar-width:none}}
.pf-tabs a{{font-size:14px;opacity:.7;white-space:nowrap}}
.pf-tabs a:hover,.pf-tabs a.on{{opacity:1}}
.pf-tabs a.on{{font-weight:700}}
/* make room for the bar: Streamlit's own toolbar, the sidebar and the page all start below it */
header[data-testid="stHeader"]{{top:{h}px}}
section[data-testid="stSidebar"]{{top:{h}px;height:calc(100vh - {h}px) !important}}
[data-testid="stMainBlockContainer"],.block-container{{padding-top:calc({h}px + 3rem) !important}}
@media (max-width:720px){{.pf-app,.pf-bar a.pill:not(:first-child){{display:none}} .pf-tabs{{padding-left:1.2rem;gap:1.1rem}}}}
</style>"""
    return (css + f'<div class="pf-bar"><div class="pf-row">'
            f'<a href="{escape(l["portfolio_url"])}" target="_top" aria-label="Home">'
            f'<svg viewBox="0 0 24 24"><path d="{_LOGO}"/></svg></a>'
            f'{a(l["portfolio_url"], l.get("site_title", "AI Workflow Portfolio"), "pf-site")}'
            f'<span class="pf-app">{escape(title)}</span><span class="pf-side">{side}</span></div>'
            f'<nav class="pf-tabs">{nav}</nav></div>')


def banner(st, root: Path, title: str) -> None:
    """Show the shared banner at the top of a Streamlit app (call right after st.set_page_config)."""
    html = banner_html(root, title)
    if html:
        st.markdown(html, unsafe_allow_html=True)
