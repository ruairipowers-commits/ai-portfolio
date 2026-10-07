"""The offline mock model. Deterministic prose from the facts it is given, no keys, $0.

It is deliberately naive in one way a real model can be: if the mission description contains an instruction to say
something ("say this launch failed"), it says it. The guard downstream must catch that, exactly as it would have to
with a real model.
"""
from __future__ import annotations

import json
import re


def _tag(text: str, tag: str):
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.S)
    return m.group(1) if m else ""


def respond(role: str, user: str) -> dict:
    facts = json.loads(_tag(user, "facts") or "{}")
    if role == "mission":
        return _mission(facts, _tag(user, "description"))
    if role == "digest":
        return _digest(facts)
    if role == "changes":
        return _changes(facts)
    return {"subject": "unknown", "text": "Unknown role.", "citations": []}


def _mission(f: dict, description: str) -> dict:
    L = f.get("launch", {})
    when = L.get("net_date")
    verb = {"success": "launched successfully", "failure": "failed", "partial": "reached a lower orbit than planned",
            "pending": "is scheduled to launch"}.get(L.get("outcome"), "launched")
    parts = [f"{L.get('mission_name') or L.get('name')} {verb} on a {L.get('rocket')} from {L.get('location')} "
             f"on {when}."]
    future = L.get("outcome") == "pending"
    if L.get("mission_type"):
        kind = L["mission_type"].lower()
        art = "an" if kind[:1] in "aeiou" else "a"
        parts.append(f"It is {art} {kind} mission" + (f" to {L['orbit']}." if L.get("orbit") else "."))
    st = f.get("booster")
    if st:
        parts.append(f"Booster {st['serial']} {'will fly for the' if future else 'was on its'} "
                     f"{_ordinal(st['flight_number'])} time" + (" and landed." if st.get("landing_success") else "."))
    if f.get("crew_count"):
        parts.append(f"{f['crew_count']} crew {'will fly' if future else 'flew'}, led by {f.get('commander') or 'the commander'}.")
    if f.get("splashdown"):
        parts.append(f"The capsule returned with a splashdown in the {f['splashdown']}.")
    m = re.search(r"say (?:that )?this launch ([^.]+)\.", description or "", re.I)
    if m:                                    # the careless behaviour the guard has to catch
        parts.append(f"This launch {m.group(1).strip()}.")
    cites = [{"field": "launch.rocket", "value": L.get("rocket")}, {"field": "launch.outcome", "value": L.get("outcome")},
             {"field": "launch.net_date", "value": when}]
    return {"subject": L.get("launch_id", ""), "text": " ".join(parts), "citations": cites}


def _ordinal(n) -> str:
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _digest(f: dict) -> dict:
    t = (f"In the week from {f['week_start']} to {f['week_end']} there {'was' if f['launches'] == 1 else 'were'} {f['launches']} launch{'' if f['launches'] == 1 else 'es'}: "
         f"{f['successes']} succeeded and {f['failures']} did not. ")
    if f.get("crewed"):
        t += f"{f['crewed']} carried crew. "
    if f.get("landings"):
        t += f"Boosters landed {f['landings']} time{'' if f['landings'] == 1 else 's'}. "
    if f.get("top_provider"):
        t += f"The busiest provider was {f['top_provider']} with {f['top_provider_launches']}."
    return {"subject": f"week of {f['week_start']}", "text": t.strip(),
            "citations": [{"field": "launches", "value": f["launches"]}, {"field": "successes", "value": f["successes"]}]}


def _changes(f: dict) -> dict:
    items = f.get("changes", [])
    if not items:
        return {"subject": "changes", "text": "No target times changed since the last refresh.", "citations": []}
    lines = [f"{c['name']} moved from {c['from_date']} to {c['to_date']} ({c['days']} days)." for c in items[:5]]
    return {"subject": "changes", "text": f"{len(items)} launches changed target time. " + " ".join(lines),
            "citations": [{"field": "count", "value": len(items)}]}
