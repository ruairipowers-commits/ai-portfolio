"""One-off packs: two PDFs, answers only in the key, never daily, reproducible from the seed (FR-7, NFR-7)."""
import io
import time

from pypdf import PdfReader
from sqlalchemy import select

from daily_puzzle import generate, grading, packs
from daily_puzzle.store import fetch_all, puzzles as P


def text(pdf: bytes) -> str:
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def test_pack_pdfs_separate_questions_and_answers(s, conn, project):
    t0 = time.perf_counter()
    out = generate.pack(conn, s, 5, ["word", "coding", "ai_ml"], "medium", seed=31)
    q, a = packs.write(conn, s, out["pack_id"])
    assert time.perf_counter() - t0 < 60                                      # NFR-7
    assert len(out["puzzle_ids"]) == 5 and not out["dropped"]
    qt, at = text(q.read_bytes()), text(a.read_bytes())
    rows = fetch_all(conn, select(P).where(P.c.pack_id == out["pack_id"]))
    for r in rows:
        k = grading.unseal(r["sealed_key"])
        assert r["title"] in qt and r["title"] in at
        sol = " ".join(k["solution"].split())[:45]                     # worked solutions state the answer
        assert sol and sol not in " ".join(qt.split()) and sol in " ".join(at.split())
        if k["code"]:                                                   # the line that prints the answer
            last = [l.strip() for l in k["code"].splitlines() if l.strip()][-1]
            assert last[:30] not in " ".join(qt.split())
    assert "answer key" not in qt.lower() or "separate answer key" in qt.lower()
    assert {r["status"] for r in rows} == {"pack"} and all(r["day"] is None for r in rows)


def test_pack_is_reproducible_from_seed_and_capped(s, conn):
    a = generate.pack(conn, s, 3, "random", "easy", seed=99)
    b = generate.pack(conn, s, 3, "random", "easy", seed=99)
    ta = [r["title"] + r["statement"] for r in fetch_all(conn, select(P).where(P.c.pack_id == a["pack_id"]).order_by(P.c.id))]
    tb = [r["title"] + r["statement"] for r in fetch_all(conn, select(P).where(P.c.pack_id == b["pack_id"]).order_by(P.c.id))]
    assert ta == tb
    assert len(generate.pack(conn, s, 999, ["logic"], "easy", seed=1)["puzzle_ids"]) <= s.puzzles["packs"]["max_puzzles"]


def test_daily_puzzles_avoid_pack_puzzles(s, conn):
    """A pack owner would already know the answer, so a daily puzzle may not repeat one."""
    from daily_puzzle import puzzles, verify
    out = generate.pack(conn, s, 1, ["logic"], "easy", seed=5)
    row = fetch_all(conn, select(P).where(P.c.id == out["puzzle_ids"][0]))[0]
    ctx = verify.Ctx(s, verify.make_client(s), conn, purpose="daily")
    clone = {"track": row["track"], "kind": row["kind"], "statement": row["statement"], "spec": {}, "reference_code": ""}
    assert verify.duplicate_problems(clone, ctx)
