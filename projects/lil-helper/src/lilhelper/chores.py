"""Who does what: cook, dishes, set the table, kid assistant, feed the dog — a fair rotation (OR-Tools CP-SAT).

Rules: only people at home that night; cooks must be able to cook; age minimums; dishes isn't the cook; a kid
assistant helps the cook (optional job). Fairness: minimize the busiest person's load counted over the last
`window_weeks` (so last week's heavy load is balanced this week), then spread each job across people.
"""
from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from .config import DAYS, Household, Person

WEIGHT = {"cook": 3, "dishes": 2, "set_table": 1, "kid_assistant": 1, "feed_dog": 1}


@dataclass
class Assignment:
    day: str
    job: str
    person: str
    name: str


def capacity(p: Person) -> int:
    return 1 if p.is_kid else 2


def eligible(p: Person, job: str, spec: dict, day: str) -> bool:
    if day not in p.home:
        return False
    if spec.get("who") == "can_cook" and not p.can_cook:
        return False
    if spec.get("kids_only") and not p.is_kid:
        return False
    if p.is_kid and p.years < int(spec.get("min_age", 0)):
        return False
    return True


def rota(h: Household, cooked_nights: list[str], past_load: dict[str, int] | None = None,
         locks: dict[tuple[str, str], str] | None = None) -> tuple[list[Assignment], dict[str, int], list[str]]:
    jobs = (h.raw.get("chores") or {}).get("jobs", {})
    past_load = past_load or {}
    locks = locks or {}
    people = list(h.people.values())
    m = cp_model.CpModel()
    a: dict[tuple[str, str, str], cp_model.IntVar] = {}
    gaps = []
    for job, spec in jobs.items():
        if job == "feed_dog" and not h.pets:
            continue
        days = DAYS if spec.get("per") == "day" else cooked_nights
        for d in days:
            ok = [p for p in people if eligible(p, job, spec, d)]
            if not ok:
                if not spec.get("optional"):
                    gaps.append(f"nobody can do {job} on {d}")
                continue
            vs = []
            for p in ok:
                v = m.NewBoolVar(f"{job}_{d}_{p.id}")
                a[(job, d, p.id)] = v
                vs.append(v)
            if (job, d) in locks and locks[(job, d)] in [p.id for p in ok]:
                m.Add(a[(job, d, locks[(job, d)])] == 1)
            m.AddExactlyOne(vs) if not spec.get("optional") else m.Add(sum(vs) <= 1)
            if spec.get("optional"):
                m.Add(sum(vs) == 1) if len(ok) >= 1 else None
    # dishes isn't the cook
    for job, spec in jobs.items():
        other = spec.get("not_same_as")
        if other:
            for (j, d, pid), v in a.items():
                if j == job and (other, d, pid) in a:
                    m.Add(v + a[(other, d, pid)] <= 1)
    # kids carry a lighter share: load is divided by capacity (adults 2, kids 1) before it's compared
    for job, spec in jobs.items():
        cap = spec.get("kid_max_per_week")
        if cap is not None:
            for p in people:
                if p.is_kid:
                    m.Add(sum(v for (j, d, pid), v in a.items() if j == job and pid == p.id) <= int(cap))
    load = {}
    for p in people:
        load[p.id] = sum(WEIGHT.get(j, 1) * v for (j, d, pid), v in a.items() if pid == p.id) + past_load.get(p.id, 0)
    mx = m.NewIntVar(0, 4000, "max_load")
    for p in people:
        m.Add(load[p.id] * (2 // capacity(p)) <= mx)
    # spread each job: the most nights any one person has a given job
    spread = []
    for job in jobs:
        top = m.NewIntVar(0, 7, f"top_{job}")
        for p in people:
            m.Add(sum(v for (j, d, pid), v in a.items() if j == job and pid == p.id) <= top)
        spread.append(top)
    m.Minimize(100 * mx + sum(spread))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3.0
    solver.parameters.random_seed = 1
    solver.parameters.num_workers = 1                # one worker: the same plan every run (reproducible)
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], {}, gaps + ["no rota fits the rules"]
    out = [Assignment(d, j, pid, h.people[pid].name) for (j, d, pid), v in a.items() if solver.Value(v)]
    out.sort(key=lambda x: (DAYS.index(x.day), list(jobs).index(x.job)))
    week_load = {p.id: sum(WEIGHT.get(x.job, 1) for x in out if x.person == p.id) for p in people}
    return out, week_load, gaps
