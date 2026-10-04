"""One-off puzzle packs as two PDFs: questions (no answers) and a separate answer key (FR-7).

Both are rendered from HTML templates with WeasyPrint. The questions PDF is built only from public fields; the
answer key is the one place outside the reveal step that decrypts the sealed key, and only for `pack` puzzles.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from sqlalchemy import select

from . import grading
from .config import PKG, TRACK_LABEL, Settings, data_dir
from .store import fetch_all, now, puzzles as P

md = MarkdownIt("commonmark", {"html": False})          # model-written Markdown, raw HTML disabled
env = Environment(loader=FileSystemLoader(PKG / "templates"), autoescape=select_autoescape(["html"]))
env.filters["md"] = lambda t: md.render(t or "")
env.globals["TRACK_LABEL"] = TRACK_LABEL


def pack_puzzles(conn, pack_id: str) -> list[dict]:
    return fetch_all(conn, select(P).where(P.c.pack_id == pack_id, P.c.status == "pack").order_by(P.c.id))


def render(conn, s: Settings, pack_id: str, which: str) -> bytes:
    """`which` = questions | answers. Returns PDF bytes."""
    from weasyprint import HTML
    rows = pack_puzzles(conn, pack_id)
    if not rows:
        raise LookupError(f"no pack {pack_id}")
    cfg = s.puzzles["packs"]
    keys = {}
    if which == "answers":
        keys = {r["id"]: grading.unseal(r["sealed_key"]) for r in rows}
    html = env.get_template(f"pack_{which}.html").render(
        puzzles=rows, keys=keys, pack_id=pack_id, title=cfg["title"], footer=cfg["footer"],
        made=now().strftime("%d %B %Y"), seed=pack_id.split("-")[0].removeprefix("pk"))
    return HTML(string=html).write_pdf()


def write(conn, s: Settings, pack_id: str, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or data_dir() / "output" / "packs"
    out_dir.mkdir(parents=True, exist_ok=True)
    q, a = out_dir / f"{pack_id}-questions.pdf", out_dir / f"{pack_id}-answers.pdf"
    q.write_bytes(render(conn, s, pack_id, "questions"))
    a.write_bytes(render(conn, s, pack_id, "answers"))
    return q, a


def list_packs(conn) -> list[dict]:
    rows = fetch_all(conn, select(P.c.pack_id, P.c.track, P.c.created_at).where(P.c.status == "pack").order_by(P.c.id))
    packs: dict[str, dict] = {}
    for r in rows:
        p = packs.setdefault(r["pack_id"], {"pack_id": r["pack_id"], "count": 0, "tracks": set(), "created_at": r["created_at"]})
        p["count"] += 1
        p["tracks"].add(r["track"])
    return sorted(packs.values(), key=lambda p: p["created_at"] or datetime.min, reverse=True)
