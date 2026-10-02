"""Single-trade walkthrough tab: the user plays each party in turn so one exception can be followed end to end.

    ① Trader (front office)        books the trade            -> trades, allocations
    ② Broker (counterparty)        sends the confirm          -> broker_confirms   (free text is untrusted)
    ③ Custodian (automated feed)   reports its record         -> custodian_records
    ④ Matching engine (system)     compares, opens exception  -> exceptions
    ⑤ Trade-ops agent (AI)         investigates, proposes     -> agent_runs, agent_steps (read-only tools)
    ⑥ Ops analyst (human — you)    approves / rejects         -> approvals, resolutions, outbox
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pandas as pd
import streamlit as st

from tradeops import app_support as sup
from tradeops import telemetry
from tradeops.runner import decide, investigate

FUNDS = {"Global Macro Fund": "GM-001", "Equity L/S Fund": "ELS-002"}
ROLES = [
    ("👤", "Trader", "Front office. Books the trade in the OMS.", "trades, allocations"),
    ("🏦", "Broker", "Counterparty, outside the firm. Sends the trade confirm.", "broker_confirms"),
    ("🏛️", "Custodian", "Automated feed. Reports what it will settle.", "custodian_records"),
    ("⚙️", "Matching engine", "System. Compares everything; opens an exception on a break.", "exceptions"),
    ("🤖", "Trade-ops agent", "AI. Investigates with read-only tools; proposes a fix.", "agent_runs, agent_steps"),
    ("🧑‍💼", "Ops analyst — you", "Human. Approves or rejects. Only an approval writes.", "approvals, resolutions, outbox"),
]
BASE_PX = 412.35
SCENARIOS = {
    "Clean trade — everything matches": dict(
        expect="④ finds no break: no exception is opened and there's nothing for the agent or ops to do."),
    "Broker confirms the wrong quantity": dict(confirm={"quantity": 5250},
        expect="④ opens 'Unmatched against broker confirm'. ⑤ sees our booking, allocations and custodian agree on 5,000 → "
               "proposes REQUEST_BROKER_CORRECTION with an email to the broker. ⑥ you approve."),
    "We booked the wrong quantity": dict(trade={"quantity": 5250}, alloc=(2500, 2500), confirm={"quantity": 5000},
                                         custodian={"quantity": 5000},
        expect="④ opens 'Unmatched'. ⑤ sees broker, custodian and allocations agree on 5,000 → AMEND_INTERNAL (fix our "
               "booking), no email."),
    "Broker's price is off": dict(confirm={"price": 413.38},
        expect="⑤ sees the broker's price differs from our fills → REQUEST_BROKER_CORRECTION."),
    "Our booked price doesn't match the fills": dict(trade={"booked_price": 413.38},
        expect="⑤ sees our booked price differs from the EMS average fill the broker matches → AMEND_INTERNAL."),
    "Broker uses the wrong settle date (T+2)": dict(confirm={"settle_date": "T+2"},
        expect="④ opens 'Settlement date differs'. ⑤: US equities settle T+1, the broker isn't → REQUEST_BROKER_CORRECTION."),
    "Broker settles to a stale account": dict(confirm={"account_ref": "STALE"},
        expect="④ opens 'Settlement instructions do not match'. ⑤: our verified SSI wins → ask the broker to correct; "
               "never change our SSI."),
    "Broker never sends a confirm": dict(confirm=None,
        expect="④ opens 'No broker confirm by cutoff'. ⑤ → CHASE_CONFIRM with a chaser email."),
    "Allocations don't add up": dict(alloc=(2500, 2400),
        expect="④ opens 'Allocations do not sum'. ⑤ → AMEND_INTERNAL (rebalance allocations)."),
    "💉 Broker confirm contains a prompt injection": dict(confirm={"quantity": 5250, "free_text": sup.INJECTION_TEXT},
        expect="⑤ screens the confirm's free text, flags it, and policy ESCALATES — you can't approve it. With the mock "
               "model the draft is still a normal quantity fix: the safeguard doesn't depend on the model."),
    "🏦 Broker asks us to change bank details": dict(confirm={"account_ref": "NEW-55120-993",
                                                              "free_text": sup.BANK_CHANGE_TEXT},
        expect="④ opens 'Settlement instructions do not match'. ⑤'s screening flags a bank-detail change request and "
               "policy ESCALATES (payment-fraud control: verify by call-back, never via email)."),
    "🏛️ Custodian sends a corrupt record": dict(trade={"settle_date": "T+2"}, custodian={"settle_date": "T+1"},
                                               custodian_malformed=True,
        expect="④ opens 'Settlement date differs'. ⑤'s custodian lookup returns unreadable data → ESCALATE rather than guess."),
}

K = "wt_"   # widget-key prefix for everything on this tab


def _dates():
    td = sup.prev_bday(date.today())
    return td, sup.next_bday(td), sup.next_bday(td, 2)


def _resolve_date(v, td):
    return {"T+1": sup.next_bday(td), "T+2": sup.next_bday(td, 2)}.get(v, v) if isinstance(v, str) else v


def _load_trader_defaults(name: str):
    sc = SCENARIOS[name]
    td, t1, _ = _dates()
    tr = {"fund": "Global Macro Fund", "ticker": "MSFT", "side": "BUY", "qty": 5000, "px": BASE_PX, "fill": BASE_PX,
          "td": td, "sd": t1, "broker": "Halden & Co"}
    o = sc.get("trade", {})
    tr["qty"] = o.get("quantity", tr["qty"])
    tr["px"] = o.get("booked_price", tr["px"])
    tr["sd"] = _resolve_date(o.get("settle_date", tr["sd"]), td)
    a, b = sc.get("alloc") or (tr["qty"] // 2, tr["qty"] - tr["qty"] // 2)
    for k, v in {**tr, "alloc_a": a, "alloc_b": b}.items():
        st.session_state[K + k] = v


def _load_counterparty_defaults(trade: dict, name: str):
    """Broker and custodian start from what was booked (the realistic default), plus the scenario's deviation."""
    sc = SCENARIOS[name]
    td = date.fromisoformat(str(trade["trade_date"]))
    ssi = sup.brokers()[trade["broker"]]
    c = sc.get("confirm", {})
    d = {K + "c_send": sc.get("confirm", {}) is not None}
    c = c or {}
    acct = c.get("account_ref", ssi)
    acct = ssi[:-3] + "999" if acct == "STALE" else acct
    d.update({
        K + "c_qty": int(c.get("quantity", trade["quantity"])),
        K + "c_px": float(c.get("price", trade["exec_avg_price"])),
        K + "c_sd": _resolve_date(c.get("settle_date", sup.next_bday(td)), td),
        K + "c_acct_mode": "SSI on file" if acct == ssi else "Different account",
        K + "c_acct": acct,
        K + "c_text": c.get("free_text", "Standard confirm."),
    })
    cu = sc.get("custodian", {})
    d.update({
        K + "cu_qty": int(cu.get("quantity", trade["quantity"])),
        K + "cu_sd": _resolve_date(cu.get("settle_date", date.fromisoformat(str(trade["settle_date"]))), td),
        K + "cu_bad": bool(sc.get("custodian_malformed")),
    })
    # Kept outside widget state: Streamlit drops a widget's value on any run where the widget isn't drawn,
    # and steps ② / ③ aren't drawn until earlier steps finish. _prefill() applies these when they appear.
    st.session_state["wt"]["defaults"] = d


def _prefill(*keys):
    d = st.session_state.get("wt", {}).get("defaults", {})
    for k in keys:
        if K + k in d:
            st.session_state.setdefault(K + k, d[K + k])


def _reset_walkthrough(keep_scenario=True):
    scn = st.session_state.get(K + "scenario")
    for k in [k for k in st.session_state if k.startswith(K)]:
        del st.session_state[k]
    st.session_state.pop("wt", None)
    if keep_scenario and scn:
        st.session_state[K + "scenario"] = scn


def _step(n: int, role_idx: int, title: str, active: bool, done: bool):
    icon, role, _, writes = ROLES[role_idx]
    box = st.container(border=True)
    state = ":green-badge[done]" if done else (":blue-badge[your turn]" if active else ":gray-badge[waiting]")
    box.markdown(f"### {n} · {icon} {role} — {title} &nbsp; {state}")
    box.caption(f"You are acting as **{role}**. Writes to: `{writes}`")
    return box


def _kv(d: dict):
    st.dataframe(pd.DataFrame([{"field": k, "value": "" if v is None else str(v)} for k, v in d.items()]),
                 hide_index=True, width="stretch")


def render(models: dict, alias_label: str, flash):
    wt = st.session_state.setdefault("wt", {})
    gov_on = telemetry.status().enabled   # kill switch: agent and approvals are off while disabled
    st.markdown("Follow **one trade** from booking to resolution. You play each party in turn; the app shows who is "
                "acting at every step and which table each action writes to. Everything here also appears in the "
                "**Bulk exception queue** and the **Data explorer** (manual trades use ids `T09xxx` / `EX-9xxx`).")
    cols = st.columns(6)
    for c, (icon, role, what, writes) in zip(cols, ROLES):
        with c.container(border=True):
            st.markdown(f"**{icon} {role}**")
            st.caption(f"{what}  \n*writes:* `{writes}`")

    s1, s2, s3 = st.columns([3, 1, 1])
    names = list(SCENARIOS)
    scn = s1.selectbox("Scenario (pre-fills every role's inputs; you can still change any field)", names,
                       key=K + "scenario")
    if s2.button("Load scenario", key=K + "load", help="Start over with this scenario's values in every step."):
        _reset_walkthrough()
        _load_trader_defaults(scn)
        st.rerun()
    if s3.button("Start a new trade", key=K + "new", help="Clear this walkthrough. Trades already created stay in "
                                                          "the database and the bulk queue."):
        _reset_walkthrough()
        st.rerun()
    st.info(f"**What should happen:** {SCENARIOS[scn]['expect']}")
    if K + "qty" not in st.session_state:
        _load_trader_defaults(scn)

    brokers = sup.brokers()
    booked = "trade_id" in wt

    # ---------------------------------------------------------------- ① trader
    with _step(1, 0, "book the trade in the OMS", not booked, booked):
        if booked:
            _kv({k: wt["trade"][k] for k in ("trade_id", "fund", "account", "side", "quantity", "ticker", "booked_price",
                                             "exec_avg_price", "trade_date", "settle_date", "broker")}
                | {"allocations": f"{wt['alloc'][0]} + {wt['alloc'][1]} = {sum(wt['alloc'])}"})
        else:
            a, b, c, d = st.columns(4)
            a.selectbox("Fund", list(FUNDS), key=K + "fund")
            b.text_input("Ticker", key=K + "ticker")
            c.selectbox("Side", ["BUY", "SELL"], key=K + "side")
            d.selectbox("Broker (counterparty)", list(brokers), key=K + "broker")
            a, b, c = st.columns(3)
            a.number_input("Quantity", 1, 10_000_000, step=100, key=K + "qty")
            b.number_input("Booked price", 0.01, 100_000.0, step=0.01, format="%.4f", key=K + "px",
                           help="The price the trader books in the OMS.")
            c.number_input("EMS average fill", 0.01, 100_000.0, step=0.01, format="%.4f", key=K + "fill",
                           help="What the executions actually averaged. Normally equals the booked price.")
            a, b, c, d = st.columns(4)
            a.date_input("Trade date", key=K + "td")
            b.date_input("Settle date", key=K + "sd", help="US equities settle T+1 (next business day).")
            c.number_input("Allocation to sub-account A", 0, 10_000_000, step=100, key=K + "alloc_a")
            d.number_input("Allocation to sub-account B", 0, 10_000_000, step=100, key=K + "alloc_b")
            ss = st.session_state
            if ss[K + "alloc_a"] + ss[K + "alloc_b"] != ss[K + "qty"]:
                st.caption(f"⚠️ Allocations total {ss[K + 'alloc_a'] + ss[K + 'alloc_b']:,} vs block {ss[K + 'qty']:,}.")
            if st.button("👤 Book trade", type="primary", key=K + "book"):
                trade = {"fund": ss[K + "fund"], "account": FUNDS[ss[K + "fund"]], "ticker": ss[K + "ticker"].strip() or "MSFT",
                         "side": ss[K + "side"], "quantity": int(ss[K + "qty"]), "booked_price": float(ss[K + "px"]),
                         "exec_avg_price": float(ss[K + "fill"]), "trade_date": ss[K + "td"], "settle_date": ss[K + "sd"],
                         "broker": ss[K + "broker"]}
                tid = sup.book_trade(trade, int(ss[K + "alloc_a"]), int(ss[K + "alloc_b"]))
                wt.update(trade_id=tid, trade={"trade_id": tid, **trade}, alloc=(int(ss[K + "alloc_a"]), int(ss[K + "alloc_b"])))
                _load_counterparty_defaults(wt["trade"], scn)
                st.rerun()

    # ---------------------------------------------------------------- ② broker
    sent = "confirm" in wt
    with _step(2, 1, "send the trade confirm", booked and not sent, sent):
        if not booked:
            st.caption("Waiting for the trader to book the trade.")
        elif sent:
            _kv(wt["confirm"] or {"confirm": "— not sent (missed the affirmation cutoff)"})
        else:
            ssi = brokers[wt["trade"]["broker"]]
            _prefill("c_send", "c_qty", "c_px", "c_sd", "c_acct_mode", "c_acct", "c_text")
            st.checkbox("Broker sends a confirm", key=K + "c_send",
                        help="Untick to simulate a broker that misses the cutoff (a missing-confirm break).")
            if st.session_state[K + "c_send"]:
                a, b, c = st.columns(3)
                a.number_input("Confirmed quantity", 1, 10_000_000, step=50, key=K + "c_qty")
                b.number_input("Confirmed price", 0.01, 100_000.0, step=0.01, format="%.4f", key=K + "c_px")
                c.date_input("Confirmed settle date", key=K + "c_sd")
                a, b = st.columns([1, 2])
                mode = a.radio("Settle to", ["SSI on file", "Different account"], key=K + "c_acct_mode",
                               help=f"Our verified SSI for {wt['trade']['broker']} is {ssi}.")
                if mode == "SSI on file":
                    st.session_state[K + "c_acct"] = ssi
                b.text_input("Settlement account on the confirm", key=K + "c_acct", disabled=mode == "SSI on file")
                st.markdown("**Free text on the confirm** — written by the broker, so the agent treats it as untrusted.")
                q1, q2, q3, _ = st.columns([1, 1, 1, 2])
                if q1.button("Standard", key=K + "t_std"):
                    st.session_state[K + "c_text"] = "Standard confirm."
                    st.rerun()
                if q2.button("💉 Injection", key=K + "t_inj", help=f"“{sup.INJECTION_TEXT}”"):
                    st.session_state[K + "c_text"] = sup.INJECTION_TEXT
                    st.rerun()
                if q3.button("🏦 Bank-detail change", key=K + "t_bank", help=f"“{sup.BANK_CHANGE_TEXT}”"):
                    st.session_state[K + "c_text"] = sup.BANK_CHANGE_TEXT
                    st.session_state[K + "c_acct_mode"] = "Different account"
                    st.session_state[K + "c_acct"] = "NEW-55120-993"
                    st.rerun()
                st.text_area("Free text", key=K + "c_text", height=80)
            if st.button("🏦 Send confirm" if st.session_state[K + "c_send"] else "🏦 Miss the cutoff (send nothing)",
                         type="primary", key=K + "send"):
                ss = st.session_state
                conf = None if not ss[K + "c_send"] else {
                    "quantity": int(ss[K + "c_qty"]), "price": float(ss[K + "c_px"]), "settle_date": ss[K + "c_sd"],
                    "account_ref": ss[K + "c_acct"], "free_text": ss[K + "c_text"]}
                sup.send_confirm(wt["trade_id"], conf)
                wt["confirm"] = conf
                st.rerun()

    # ---------------------------------------------------------------- ③ custodian
    reported = "custodian" in wt
    with _step(3, 2, "report the settlement record", sent and not reported, reported):
        if not sent:
            st.caption("Waiting for the broker.")
        elif reported:
            _kv(wt["custodian"])
        else:
            _prefill("cu_qty", "cu_sd", "cu_bad")
            st.caption("The custodian normally mirrors what will actually settle. Change it to create a three-way break.")
            a, b, c = st.columns(3)
            a.number_input("Custodian quantity", 1, 10_000_000, step=50, key=K + "cu_qty")
            b.date_input("Custodian settle date", key=K + "cu_sd")
            c.checkbox("Send a corrupt (truncated) record", key=K + "cu_bad",
                       help="Simulates a broken feed message: the agent's custodian lookup will fail to parse it.")
            if st.button("🏛️ Report custodian record", type="primary", key=K + "cust"):
                ss = st.session_state
                sup.custodian_report(wt["trade_id"], ss[K + "cu_qty"], ss[K + "cu_sd"], wt["trade"]["account"],
                                     ss[K + "cu_bad"])
                wt["custodian"] = {"quantity": ss[K + "cu_qty"], "settle_date": ss[K + "cu_sd"],
                                   "record": "corrupt / truncated" if ss[K + "cu_bad"] else "valid JSON"}
                st.rerun()

    # ---------------------------------------------------------------- ④ matching engine
    matched = "match" in wt
    with _step(4, 3, "compare and open an exception", reported and not matched, matched):
        if not reported:
            st.caption("Waiting for the custodian.")
        else:
            if not matched and st.button("⚙️ Run matching", type="primary", key=K + "match"):
                rows, notes, desc = sup.match_trade(wt["trade_id"])
                wt["match"] = {"rows": rows, "notes": notes, "desc": desc}
                if desc:
                    wt["exception_id"] = sup.open_exception(wt["trade_id"], desc)
                    sup.log_walkthrough_text(wt["exception_id"], (wt["confirm"] or {}).get("free_text", ""))
                st.rerun()
            if matched:
                m = wt["match"]
                st.dataframe(pd.DataFrame([{k: "" if v is None else str(v) for k, v in r.items()} for r in m["rows"]])
                             .style.apply(lambda r: ["background-color: #FDE2E2; color: #7F1D1D" if r["match"] == "❌"
                                                     else "" for _ in r], axis=1), hide_index=True, width="stretch")
                for n in m["notes"]:
                    st.warning(n)
                if m["desc"]:
                    st.error(f"**Break found → exception {wt['exception_id']} opened:** {m['desc']}")
                else:
                    st.success("**Matched.** Every source agrees: no exception, the trade settles, nothing for ops to do.")

    # ---------------------------------------------------------------- ⑤ agent
    ex = wt.get("exception_id")
    run = next((r for r in sup.latest_runs() if r["exception_id"] == ex), None) if ex else None
    with _step(5, 4, "investigate and propose a fix", bool(ex) and run is None, run is not None):
        if not matched:
            st.caption("Waiting for the matching engine.")
        elif not ex:
            st.caption("No exception — the agent isn't needed.")
        else:
            if run is None:
                st.caption(f"Model: **{alias_label}** (change it in the sidebar). The agent can only *read*: it calls "
                           "tools to look up the trade, confirm, allocations, custodian and SSI, then submits a proposal.")
                if st.button(f"🤖 Investigate {ex}", type="primary", key=K + "inv", disabled=not gov_on):
                    with st.spinner("Agent investigating…"):
                        asyncio.run(investigate([ex], models[alias_label]))
                    st.rerun()
            else:
                p, flags = json.loads(run["proposal_json"]), json.loads(run["policy_flags"])
                steps = sup.steps(run["thread_id"])
                st.markdown(f"**What the agent did** — {run['tool_calls']} tool calls, ${run['cost_usd']:.4f}, "
                            f"model `{run['model_name']}`")
                st.dataframe(pd.DataFrame([{"#": s["step"], "who": "🤖 model" if s["kind"] == "llm" else "🔧 tool (read-only)",
                                            "action": (f"decides next: {s['args']}" if s["kind"] == "llm" else
                                                       f"{s['name']}({s['args']})"),
                                            "flag": s["flag"] or ""} for s in steps]), hide_index=True, width="stretch")
                c1, c2 = st.columns(2)
                c1.markdown(f"**Proposal:** `{p['category']}` → `{p['fix_type']}`  \n{p['root_cause']}  \n"
                            f"*Fix:* {p['fix_details']}")
                if p.get("email_draft"):
                    c2.markdown(f"**Draft email to {p['email_draft']['recipient']}:** *{p['email_draft']['subject']}*")
                    c2.code(p["email_draft"]["body"], language=None)
                if run["status"] == "escalated":
                    st.error("**Policy escalated this — it can't be approved:**\n" +
                             "\n".join(f"- {r}" for r in flags["reasons"]))
                else:
                    st.success("Policy checks passed (schema, evidence matches the sources, no flags) → "
                               "handed to the ops analyst.")

    # ---------------------------------------------------------------- ⑥ analyst
    decided = run is not None and run["status"] in ("resolved", "rejected")
    with _step(6, 5, "approve or reject", run is not None and run["status"] == "awaiting_approval", decided):
        approver = st.session_state.get("approver", "")
        if run is None:
            st.caption("Waiting for the agent." if ex else "Nothing to decide.")
        elif run["status"] == "escalated":
            st.caption("Escalated items go to an ops lead; they can't be approved here.")
        elif run["status"] == "awaiting_approval":
            p = json.loads(run["proposal_json"])
            fix = st.text_area("Fix details (editable)", p["fix_details"], key=K + "fix")
            edits = {"fix_details": fix}
            if p.get("email_draft"):
                body = st.text_area(f"Email to {p['email_draft']['recipient']} (editable)", p["email_draft"]["body"],
                                    key=K + "body", height=90)
                edits["email_draft"] = {**p["email_draft"], "body": body}
            a, b = st.columns(2)
            if a.button(f"🧑‍💼 Approve as {approver or '…'}", type="primary", disabled=not approver or not gov_on, key=K + "approve",
                        help="Mints a signed token over exactly this content; only then can the write-scoped tool "
                             "record the fix and queue the email (never sent)."):
                out = asyncio.run(decide(ex, "approve", approver, "walkthrough", edits))
                flash(out["status"] == "resolved", f"{ex} resolved by {approver}" if out["status"] == "resolved"
                      else f"{ex}: {out['status']}")
                st.rerun()
            if b.button("Reject", disabled=not approver or not gov_on, key=K + "reject"):
                asyncio.run(decide(ex, "reject", approver, "walkthrough"))
                st.rerun()
            if not approver:
                st.warning("Enter your name in the sidebar to decide.")
        else:
            rec = sup.related_records(ex)
            if run["status"] == "resolved":
                st.success(f"**Resolved.** Recorded by the approval-gated tool; status in the bulk queue is green.")
                st.dataframe(pd.DataFrame(rec["resolutions"]), hide_index=True, width="stretch")
                if rec["outbox"]:
                    st.caption("Email queued in the outbox (never sent automatically):")
                    st.dataframe(pd.DataFrame(rec["outbox"])[["recipient", "subject", "body", "sent"]],
                                 hide_index=True, width="stretch")
            else:
                st.info("Rejected. Nothing was written.")
