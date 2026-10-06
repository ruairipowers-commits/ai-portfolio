"""After a meal, one tap: how much was eaten (all / some left / lots left) and a 1–5 rating. Portions learn from
it, the pantry knows what's left over, and the savings report gets its satisfaction number (FR-6, HITL-03)."""
from __future__ import annotations

from .config import Settings

EATEN = {"all": 1.0, "some_left": 0.8, "lots_left": 0.55}


def record(con, week_of: str, day: str, meal: str, recipe: str, eaten: str, rating: int | None, by: str) -> None:
    from .store import now
    if eaten not in EATEN:
        raise ValueError(f"eaten must be one of {sorted(EATEN)}")
    if rating is not None and not 1 <= int(rating) <= 5:
        raise ValueError("rating is 1–5")
    con.execute("INSERT OR REPLACE INTO feedback VALUES (?,?,?,?,?,?,?,?)",
                (week_of, day, meal, recipe, eaten, rating, by, now()))
    con.commit()


def learn(con, s: Settings, week_of: str) -> dict[str, float]:
    """Update each recipe's portion factor from this week's answers (EWMA), and shrink one that has had lots left
    `leftover_weeks_to_shrink` times running. Returns the changed factors."""
    from .store import now
    f = s["feedback"]
    lr, lo, hi = float(f["portion_learning_rate"]), float(f["min_portion"]), float(f["max_portion"])
    shrink_after = int(f["leftover_weeks_to_shrink"])
    changed = {}
    for r in con.execute("SELECT recipe, eaten FROM feedback WHERE week_of=?", (week_of,)).fetchall():
        cur = con.execute("SELECT factor, leftover_streak FROM portions WHERE recipe=?", (r["recipe"],)).fetchone()
        factor, streak = (cur["factor"], cur["leftover_streak"]) if cur else (1.0, 0)
        streak = streak + 1 if r["eaten"] == "lots_left" else 0
        target = factor * EATEN[r["eaten"]] if r["eaten"] != "all" else min(hi, factor * 1.05)
        new = factor + lr * (target - factor)
        if streak >= shrink_after:
            new = min(new, factor * 0.9)
        new = round(min(hi, max(lo, new)), 3)
        con.execute("INSERT OR REPLACE INTO portions VALUES (?,?,?,?)", (r["recipe"], new, streak, now()))
        if abs(new - factor) > 1e-6:
            changed[r["recipe"]] = new
    con.commit()
    return changed


def ratings(con, week_of: str) -> list[float]:
    return [float(r["rating"]) for r in con.execute("SELECT rating FROM feedback WHERE week_of=? AND rating IS NOT NULL",
                                                    (week_of,))]


def ratings_before(con, week_of: str, weeks: int = 4) -> list[float]:
    import datetime as dt
    start = (dt.date.fromisoformat(week_of) - dt.timedelta(weeks=weeks)).isoformat()
    return [float(r["rating"]) for r in con.execute(
        "SELECT rating FROM feedback WHERE week_of<? AND week_of>=? AND rating IS NOT NULL", (week_of, start))]
