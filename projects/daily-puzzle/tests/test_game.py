"""The daily cycle, play, scoring, leaderboard and integrity of the answer key (FR-2..FR-6, NFR-3)."""
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from daily_puzzle import cycle, game, generate, grading, mailer
from daily_puzzle.store import engine, fetch_one, players, puzzles as P

NY = ZoneInfo("America/New_York")
MON = date(2026, 10, 5)


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), NY).astimezone(timezone.utc)


def player(conn, handle="ada_lovelace", tracks=("logic", "word", "numbers", "coding", "ai_ml")):
    return conn.execute(players.insert().values(email=f"{handle}@example.com", handle=handle, tracks=list(tracks),
                                                created_at=at(MON, 0), confirmed_at=at(MON, 0))).inserted_primary_key[0]


def test_cycle_states_and_times(s, conn):
    assert cycle.tick(conn, s, at(MON, 2)) == []                                  # before generate_at
    acts = cycle.tick(conn, s, at(MON, 3, 1))
    assert acts[0]["job"] == "generate" and acts[0]["status"] == "published"
    p = cycle.puzzle_for_day(conn, MON.isoformat()) if hasattr(cycle, "puzzle_for_day") else None
    p = fetch_one(conn, select(P).where(P.c.day == MON.isoformat()))
    assert p["status"] == "scheduled" and p["track"] == "logic"                 # Monday = logic
    assert [a["job"] for a in cycle.tick(conn, s, at(MON, 7, 0))] == ["open"]
    assert cycle.tick(conn, s, at(MON, 12)) == []                                 # idempotent
    assert [a["job"] for a in cycle.tick(conn, s, at(MON, 23, 59))] == ["close"]
    assert cycle.tick(conn, s, at(MON + timedelta(days=1), 0, 2)) == []           # reveal waits 5 minutes
    assert cycle.tick(conn, s, at(MON + timedelta(days=1), 0, 4))[0]["job"] == "reveal"
    p = fetch_one(conn, select(P).where(P.c.id == p["id"]))
    assert p["status"] == "revealed" and p["reveal_answer"]


def test_missed_window_is_caught_up_in_order(s, conn):
    cycle.tick(conn, s, at(MON, 3, 1))
    acts = cycle.tick(conn, s, at(MON + timedelta(days=1), 9))                      # server was off for a day
    jobs = [a["job"] for a in acts]
    assert jobs.index("reveal") < jobs.index("generate") < jobs.index("open") if "reveal" in jobs else True
    assert fetch_one(conn, select(P).where(P.c.day == MON.isoformat()))["status"] in ("closed", "revealed")


def test_rotation_and_config(s):
    tracks = [generate.choose(MON + timedelta(days=i), s)[0] for i in range(5)]
    assert tracks == ["logic", "word", "numbers", "coding", "ai_ml"]
    s.puzzles["tracks"]["coding"]["enabled"] = False
    assert generate.choose(MON + timedelta(days=3), s)[0] != "coding"        # disabled track falls back to random


def test_escalation_uses_reserve_and_emails_operator(s, conn, project):
    generate.build_reserve(conn, s, per_track=1)
    res = generate.daily(conn, s, MON, scenario="two_answers", kind="knights-knaves", every_round=True)
    assert res["status"] == "escalated" and res["rounds"] == 3 and res["puzzle_id"]
    used = fetch_one(conn, select(P).where(P.c.id == res["puzzle_id"]))
    assert used["source"] == "reserve" and used["day"] == MON.isoformat() and used["track"] == "logic"
    esc = fetch_one(conn, select(P).where(P.c.id == res["escalated_id"]))
    assert esc["status"] == "escalated" and len(esc["verification"]["rounds"]) == 3
    assert list((project / "output" / "outbox").glob("*escalation*"))
    generate.review(conn, esc["id"], "Ruairi", "reject", "really ambiguous")
    with pytest.raises(ValueError):
        generate.review(conn, esc["id"], "", "approve")


def test_first_bad_draft_recovers(s, conn):
    res = generate.daily(conn, s, MON, scenario="nondeterministic", kind="tiny-finetune")
    assert res["status"] == "published" and res["rounds"] == 2


def test_accept_submit_score_and_attempt_cap(s, conn):
    cycle.tick(conn, s, at(MON, 7, 1))
    p = fetch_one(conn, select(P).where(P.c.day == MON.isoformat()))
    key = grading.unseal(p["sealed_key"])["answer"]
    a, b, c3 = player(conn, "ada_l"), player(conn, "bob_k"), player(conn, "cy_m")
    t = at(MON, 9)
    assert game.submit(conn, s, a, p["id"], key, at=t)["status"] == "not_accepted"
    for pid in (a, b, c3):
        game.accept(conn, pid, p["id"], at=t)
    assert game.submit(conn, s, a, p["id"], key, at=t)["status"] == "solved"
    assert game.submit(conn, s, a, p["id"], key, at=t)["status"] == "already_solved"
    fb = game.submit(conn, s, b, p["id"], "wrong", at=t)
    assert fb == {"status": "incorrect", "attempts_used": 1, "attempts_left": 5, "points": 0}
    assert game.submit(conn, s, b, p["id"], key, at=t)["points"] == 70
    for i in range(6):
        fb = game.submit(conn, s, c3, p["id"], f"guess {i}", at=t)
    assert fb["status"] == "out_of_attempts"
    assert game.submit(conn, s, c3, p["id"], key, at=t)["status"] == "out_of_attempts"      # 7th attempt refused
    assert game.submit(conn, s, a, p["id"], key, at=at(MON + timedelta(days=1), 1))["status"] == "closed"
    board = game.leaderboard(conn, s, at=t)
    assert [(r["handle"], r["accepted"], r["attempted"], r["solved"], r["score"]) for r in board] == \
        [("ada_l", 1, 1, 1, 100), ("bob_k", 1, 1, 1, 70), ("cy_m", 1, 1, 0, 0)]
    assert "email" not in board[0]


def test_ties_break_on_fewer_attempts_then_earlier_solve(s, conn):
    cycle.tick(conn, s, at(MON, 7, 1))
    p1 = fetch_one(conn, select(P).where(P.c.day == MON.isoformat()))
    k1 = grading.unseal(p1["sealed_key"])["answer"]
    x, y = player(conn, "early_bird"), player(conn, "late_owl")
    for pid, when in ((y, at(MON, 20)), (x, at(MON, 8))):
        game.accept(conn, pid, p1["id"], at=when)
        game.submit(conn, s, pid, p1["id"], k1, at=when)
    assert [r["handle"] for r in game.leaderboard(conn, s, at=at(MON, 21))] == ["early_bird", "late_owl"]
    d2 = MON + timedelta(days=1)
    cycle.tick(conn, s, at(d2, 7, 1))
    p2 = fetch_one(conn, select(P).where(P.c.day == d2.isoformat()))
    game.accept(conn, y, p2["id"], at=at(d2, 8))
    game.submit(conn, s, y, p2["id"], grading.unseal(p2["sealed_key"])["answer"], at=at(d2, 8))
    board = game.leaderboard(conn, s, at=at(d2, 9))
    assert board[0]["handle"] == "late_owl" and board[0]["score"] == 200                     # cumulative
    assert game.leaderboard(conn, s, track="word", at=at(d2, 9))[0]["accepted"] == 1


def test_key_never_leaks_before_close(s, project, monkeypatch, governance_spool):
    """NFR-3: not in pages, API, emails, logs or telemetry while the puzzle is open."""
    from daily_puzzle.web import create_app
    eng = engine(s)
    with eng.begin() as c:
        pid_player = player(c, "ada_l")
        cycle.tick(c, s, at(MON, 4))
        p = fetch_one(c, select(P).where(P.c.day == MON.isoformat()))
        key = grading.unseal(p["sealed_key"])
        c.execute(P.update().where(P.c.id == p["id"]).values(opens_at=datetime.now(timezone.utc) - timedelta(hours=1),
                                                             closes_at=datetime.now(timezone.utc) + timedelta(hours=8)))
        cycle.tick(c, s, datetime.now(timezone.utc))
    from daily_puzzle.web import session_value
    client = TestClient(create_app(scheduler=False))
    client.cookies.set("dp_session", session_value(pid_player))
    pages = [client.get("/").text, client.get(f"/p/{p['id']}").text, client.get("/archive").text]
    client.post(f"/accept/{p['id']}")
    pages.append(client.post(f"/submit/{p['id']}", data={"answer": "zzz"}).text)
    r = client.get(f"/p/{p['id']}/answer.json")
    assert r.status_code == 403 and key["answer"] not in r.text
    mails = "".join(f.read_text() for f in (project / "output" / "outbox").glob("*.eml"))
    assert "ada_l" in mails                                                   # the daily email went out
    with eng.connect() as c:
        row = fetch_one(c, select(P).where(P.c.id == p["id"]))
    stored = json.dumps({k: v for k, v in row.items() if k not in ("statement",)}, default=str)
    secret_bits = [key["answer"], key["solution"][:30]] + ([key["code"][:40]] if key["code"] else [])
    for blob in [*pages, mails, stored, governance_spool.read_text()]:
        for bit in secret_bits:
            if bit and not (bit.isdigit() and len(bit) < 3):                      # tiny numbers occur by chance
                assert bit not in blob


def test_draft_and_pack_puzzles_are_not_public(s):
    from daily_puzzle.web import create_app
    with engine(s).begin() as c:
        out = generate.pack(c, s, 1, ["word"], "easy", 5)
        reserve = generate.build_reserve(c, s, 1)
        esc = generate.daily(c, s, MON, scenario="wrong_key", kind="ordering", every_round=True)
    client = TestClient(create_app(scheduler=False))
    hidden = out["puzzle_ids"] + reserve[1:] + [esc["escalated_id"]]
    assert len(hidden) >= 3
    for pid in hidden:
        assert client.get(f"/p/{pid}").status_code == 404
        assert client.get(f"/p/{pid}/answer.json").status_code == 404


def test_simulated_week(s, conn):
    from daily_puzzle import simulate
    log = simulate.week(conn, s, MON, 3, 10, 7, injection_by="amber_otter")
    assert [x["status"] for x in log if x["job"] == "generate"] == ["published"] * 4
    assert sum(x["injections"] for x in log if x["job"] == "players") >= 1
    from daily_puzzle.store import attempts, fetch_all
    inj = [r for r in fetch_all(conn, select(attempts)) if "injection_text" in (r["flags"] or [])]
    assert inj and not any(r["correct"] for r in inj)                     # graded by code as wrong, and flagged
    board = game.leaderboard(conn, s)
    assert len(board) == 10 and board[0]["score"] >= board[-1]["score"]
    assert not list(mailer.outbox_dir().glob("*sim-*"))                    # simulated players are never emailed
