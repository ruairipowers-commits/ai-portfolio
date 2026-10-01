"""Streamlit app for the trade-ops exception agent. Run: `tradeops ui`.

Four tabs: Exception workflow (select a row → investigate / queue / tamper / approve), Data explorer
(ER diagram, tables, read-only SQL), Audit & evals, and Guide & models. See docs/app-guide.md.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from tradeops import app_support as sup
from tradeops.llm import BudgetExceeded, Registry, RegistryError
from tradeops.runner import ROOT, decide, investigate

st.set_page_config(page_title="Trade-ops exception agent", page_icon="🧾", layout="wide")
DOCS = Path(__file__).resolve().parents[2] / "docs"   # shipped with the code, not the data folder

STATUS_STYLE = {
    "Awaiting approval": "background-color: #FEF3C7; color: #78350F",
    "Escalated": "background-color: #FEE2E2; color: #7F1D1D; font-weight: 600",
    "Resolved": "background-color: #DCFCE7; color: #14532D; font-weight: 600",
    "Rejected": "background-color: #E5E7EB; color: #374151",
    "Write failed": "background-color: #FEE2E2; color: #7F1D1D",
}
STATUS_BADGE = {"Not investigated": ":gray-badge[Not investigated]", "Awaiting approval": ":orange-badge[Awaiting approval]",
                "Escalated": ":red-badge[Escalated]", "Resolved": ":green-badge[Resolved]",
                "Rejected": ":gray-badge[Rejected]", "Write failed": ":red-badge[Write failed]"}

if not sup.server_built():
    st.error("The MCP tool server isn't built. Run `tradeops build-server` (needs Node 22.13+) and reload.")
    st.stop()
if not sup.has_data():
    sup.reset()

st.session_state.setdefault("run_queue", [])


# ================================================================== helpers
def _df(rows: list[dict]) -> pd.DataFrame:
    """Display-safe frame: mixed types become strings so Arrow doesn't choke."""
    return pd.DataFrame([{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows])


def doc(name: str) -> str:
    """A docs/ page without its top-level title (the tab already names it)."""
    text = (DOCS / name).read_text()
    return text.split("\n", 1)[1] if text.startswith("# ") else text


def flash(ok: bool, msg: str):
    st.session_state["flash"] = (ok, msg)


def run_investigation(ids: list[str], label: str):
    if not ids:
        return
    with st.status(f"Agent investigating {label}…", expanded=False) as status:
        try:
            res = asyncio.run(investigate(ids, models[alias_label]))
            esc = sum(r["status"] == "escalated" for r in res)
            msg = (f"Investigated {len(res)} ({', '.join(ids[:5])}{'…' if len(ids) > 5 else ''}): "
                   f"{len(res) - esc} awaiting approval, {esc} escalated · spend ${sum(r['cost_usd'] for r in res):.4f}")
            status.update(label=msg, state="complete")
            flash(True, msg)
        except (BudgetExceeded, RegistryError) as e:
            status.update(label=f"Stopped: {e}", state="error")
            flash(False, f"Stopped: {e}")
    st.rerun()


def render_comparison(exception_id: str):
    rows, notes = sup.break_comparison(exception_id)
    st.markdown("**How the break shows up across systems** — ❌ marks a field where the sources disagree")
    if rows:
        st.dataframe(_df(rows).style.apply(lambda r: ["background-color: #FDE2E2; color: #7F1D1D" if r["match"] == "❌"
                                                      else "" for _ in r], axis=1),
                     hide_index=True, width="stretch")
    for n in notes:
        st.warning(n)


def render_records(exception_id: str):
    rec = sup.related_records(exception_id)
    order = ["exceptions", "trades", "allocations", "broker_confirms", "custodian_records", "ssis",
             "agent_runs", "agent_steps", "historical_resolutions", "approvals", "resolutions", "outbox"]
    present = [t for t in order if t in rec]
    st.markdown("**Related database records** (" + ", ".join(f"{t}: {len(rec[t])}" for t in present) + ")")
    for tab, name in zip(st.tabs(present), present):
        with tab:
            st.dataframe(_df(rec[name]), hide_index=True, width="stretch") if rec[name] else st.caption("No rows.")


def proposal_summary(run: dict):
    p, flags = json.loads(run["proposal_json"]), json.loads(run["policy_flags"])
    c = st.columns([2, 2, 1, 1])
    c[0].markdown(f"**Category**  \n`{p['category']}`")
    c[1].markdown(f"**Proposed fix**  \n`{p['fix_type']}`")
    c[2].markdown(f"**Tool calls**  \n{run['tool_calls']}")
    c[3].markdown(f"**Cost**  \n${run['cost_usd']:.4f}")
    if flags["flags"]:
        st.warning("Flags raised on tool results: " + ", ".join(flags["flags"]))
    st.markdown(f"**Root cause.** {p['root_cause']}")
    st.markdown("**Evidence** (each value verified against the tool result it came from)")
    st.dataframe(pd.DataFrame([{**e, "value": str(e["value"])} for e in p["evidence"]]), hide_index=True)
    return p, flags


# ================================================================== sidebar
with st.sidebar:
    st.header("Settings")
    models = sup.usable_aliases()
    alias_label = st.selectbox("Model", list(models), key="model",
                               help="Which model investigates. Only approved, priced models with credentials present are "
                                    "listed (SEC-05, COST-01). Default: the offline mock. See Guide & models → Models.")
    st.text_input("Your name (recorded on approvals)", "demo-analyst", key="approver",
                  help="Written to approvals.approver and resolutions.approved_by. Approve/Reject need a name.")
    st.divider()
    if st.button("Reset demo data", help="Regenerate the 40 synthetic exceptions; clears runs, approvals, resolutions, "
                                         "outbox and your Try-to-break-it edits."):
        sup.reset()
        for k in [k for k in st.session_state if k not in ("model", "approver")]:
            del st.session_state[k]
        flash(True, "Demo data reset: 40 open exceptions, nothing investigated.")
        st.rerun()
    st.caption("New here? Open **📘 Guide & models**.")

st.title("Trade-ops exception agent")
st.caption("A LangGraph agent investigates settlement breaks with read-only tools from an MCP server, proposes a fix "
           "and stops. Nothing is recorded or sent until a named analyst approves.")
if "flash" in st.session_state:
    ok, msg = st.session_state.pop("flash")
    (st.success if ok else st.error)(msg)

tab_wf, tab_data, tab_audit, tab_guide = st.tabs(
    ["🧾 Exception workflow", "🗄️ Data explorer", "📏 Audit & evals", "📘 Guide & models"])

# ================================================================== 1. workflow
with tab_wf:
    rows = sup.workflow_rows()
    wf = pd.DataFrame(rows)
    counts = wf["status"].value_counts()
    m = st.columns(6)
    for i, s in enumerate(["Not investigated", "Awaiting approval", "Escalated", "Resolved", "Rejected"]):
        m[i].metric(s, int(counts.get(s, 0)))
    m[5].metric("Tampered", int((wf["tampered"] != "").sum()), help="Exceptions whose broker confirm you changed")

    not_run = wf.loc[wf["status"] == "Not investigated", "exception_id"].tolist()
    queue = [q for q in st.session_state["run_queue"] if q in set(wf["exception_id"])]
    b1, b2, b3 = st.columns([2, 2, 1])
    if b1.button(f"▶ Investigate all not yet investigated ({len(not_run)})", disabled=not not_run, type="primary",
                 help="Run the agent on every exception with no run yet. Each stops at Awaiting approval or Escalated."):
        run_investigation(not_run, f"{len(not_run)} exceptions")
    if b2.button(f"▶ Run queue ({len(queue)})", disabled=not queue,
                 help="Run the agent on the exceptions you added with ➕ Add to run queue, then empty the queue."):
        st.session_state["run_queue"] = []
        run_investigation(queue, f"the queue ({len(queue)})")
    if b3.button("Clear queue", disabled=not queue, help="Empty the run queue without running anything."):
        st.session_state["run_queue"] = []
        st.rerun()
    if queue:
        st.caption("Run queue: " + ", ".join(queue))

    shown = wf.assign(queued=wf["exception_id"].map(lambda e: "⏳" if e in queue else ""),
                      tool_calls=wf["tool_calls"].map(lambda v: "" if v is None or pd.isna(v) else str(int(v))))
    shown = shown[["exception_id", "status", "tampered", "queued", "category", "fix", "description", "trade", "broker",
                   "tool_calls"]]
    styled = (shown.style.map(lambda v: STATUS_STYLE.get(v, ""), subset=["status"])
              .map(lambda v: "background-color: #EDE9FE; color: #4C1D95" if v else "", subset=["tampered"]))
    event = st.dataframe(styled, hide_index=True, width="stretch", height=380, key="wf_table",
                         on_select="rerun", selection_mode="single-row",
                         column_config={"exception_id": st.column_config.TextColumn("exception", width="small"),
                                        "status": st.column_config.TextColumn("status", width="medium"),
                                        "category": st.column_config.TextColumn("category", width="medium"),
                                        "fix": st.column_config.TextColumn("fix", width="medium"),
                                        "tampered": st.column_config.TextColumn("tampered", width="medium"),
                                        "queued": st.column_config.TextColumn("queue", width="small"),
                                        "description": st.column_config.TextColumn("description", width="medium"),
                                        "tool_calls": st.column_config.TextColumn("tools", width="small")})
    st.caption("Click the box at the left of a row to select an exception. Status: amber = awaiting approval · "
               "red = escalated · **green = resolved** · grey = rejected. Purple = you changed its broker confirm.")
    if event and event.selection.rows:
        st.session_state["sel"] = shown.iloc[event.selection.rows[0]]["exception_id"]

    sel = st.session_state.get("sel")
    if not sel or sel not in set(wf["exception_id"]):
        st.info("Select an exception in the table to investigate it, try to break it, or approve its fix.")
    else:
        row = wf.set_index("exception_id").loc[sel]
        run = next((r for r in sup.latest_runs() if r["exception_id"] == sel), None)
        status = row["status"]
        st.divider()
        st.subheader(f"{sel} — {row['description']}")
        st.markdown(f"{STATUS_BADGE.get(status, status)} &nbsp; {row['trade']} · {row['broker']}"
                    + (f" &nbsp; :violet-badge[{row['tampered']}]" if row["tampered"] else ""))
        a1, a2, _ = st.columns([2, 2, 3])
        if a1.button("▶ Investigate this exception", type="primary", disabled=status == "Resolved", key="inv_one",
                     help="Run the agent on this exception now. A new run replaces the previous proposal. "
                          "Not available once resolved."):
            run_investigation([sel], sel)
        if sel in queue:
            if a2.button("➖ Remove from queue", key="dequeue"):
                st.session_state["run_queue"].remove(sel)
                st.rerun()
        elif a2.button("➕ Add to run queue", disabled=status == "Resolved", key="enqueue",
                       help="Collect exceptions and run them together with ▶ Run queue."):
            st.session_state["run_queue"].append(sel)
            st.rerun()

        t_dec, t_break, t_ev, t_traj = st.tabs(["Decision", "Try to break it", "Evidence & records", "Agent trajectory"])

        # ---------------------------------------------------------- decision
        with t_dec:
            if run is None:
                st.info("Not investigated yet. Press **▶ Investigate this exception** (or add it to the run queue).")
            elif status == "Awaiting approval":
                p, _ = proposal_summary(run)
                st.markdown("**Your decision** — edit the fix or email if needed, then approve or reject.")
                approver = st.session_state.get("approver", "")
                fix = st.text_area("Fix details (editable)", p["fix_details"], key=f"fix_{run['thread_id']}")
                edits = {"fix_details": fix}
                if p.get("email_draft"):
                    e = p["email_draft"]
                    subj = st.text_input(f"Email subject → {e['recipient']}", e["subject"], key=f"subj_{run['thread_id']}")
                    body = st.text_area("Email body", e["body"], height=110, key=f"body_{run['thread_id']}")
                    edits["email_draft"] = {**e, "subject": subj, "body": body}
                note = st.text_input("Note (optional)", key=f"note_{run['thread_id']}")
                d1, d2 = st.columns(2)
                if d1.button("✅ Approve", type="primary", disabled=not approver, key="approve",
                             help="Mint a signed approval token over exactly this content, start the write-scoped tool "
                                  "server, record the fix and queue any email (never sent). Status turns green."):
                    out = asyncio.run(decide(sel, "approve", approver, note, edits))
                    w = out["write_result"] or {}
                    flash(out["status"] == "resolved",
                          f"{sel} resolved — fix recorded by {approver}" + ("; email queued in outbox (not sent)"
                                                                            if w.get("email_queued") else "")
                          if out["status"] == "resolved" else f"{sel}: {out['status']} — {w.get('error', w)}")
                    st.rerun()
                if d2.button("Reject", disabled=not approver, key="reject",
                             help="Record that you rejected the proposal. Nothing is written. You can re-investigate."):
                    asyncio.run(decide(sel, "reject", approver, note))
                    flash(True, f"{sel}: rejected by {approver}")
                    st.rerun()
                if not approver:
                    st.warning("Enter your name in the sidebar to approve or reject.")
            elif status == "Escalated":
                reasons = json.loads(run["policy_flags"])["reasons"]
                st.error("**Escalated — can't be approved here.**\n\n" + "\n".join(f"- {r}" for r in reasons))
                st.caption("In production this goes to an ops lead. Here you can inspect the draft below, restore the "
                           "inputs under *Try to break it* and re-investigate.")
                st.markdown("**The agent's draft** (read-only)")
                proposal_summary(run)
            elif status == "Resolved":
                rec = sup.related_records(sel)
                st.success("Resolved through the approval-gated tool.")
                st.dataframe(_df(rec["resolutions"]), hide_index=True, width="stretch")
                if rec["outbox"]:
                    st.markdown("**Queued email** (never sent automatically)")
                    st.dataframe(_df(rec["outbox"]), hide_index=True, width="stretch")
            else:
                rec = sup.related_records(sel)
                st.info(f"{status}. You can re-investigate.")
                st.dataframe(_df(rec["approvals"]), hide_index=True, width="stretch")

        # ---------------------------------------------------------- try to break it
        with t_break:
            current = sup.confirm_text(sel)
            tam = sup.tamper_state().get(sel)
            st.markdown("These simulate the **broker sending us different free text** on the trade confirm — the "
                        "untrusted text the agent reads via `get_broker_confirm`. Each button **applies immediately** "
                        "to this exception, is logged in `demo_inputs` and can be undone. Then press "
                        "**▶ Investigate this exception** to see what happens.")
            if tam:
                st.warning(f"**This exception's broker confirm has been changed** — {sup.TAMPER_LABELS[tam['kind']]} "
                           f"(at {str(tam['changed_at'])[:19].replace('T', ' ')} UTC)"
                           + ("" if run and str(run['started_at']) > str(tam['changed_at'])
                              else ". **Not yet investigated with this text** — press ▶ Investigate this exception.")
                           + f"\n\nOriginal text: “{tam['original_text']}”")
            elif current is not None:
                st.success("Broker confirm is the original, untouched text.")
            if current is None:
                st.info("This exception has no broker confirm (a missing-confirm break), so there's no text to change.")
            elif status == "Resolved":
                st.info("Already resolved — inputs are locked.")
            else:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**💉 Prompt injection**")
                    st.caption(f"Replaces the confirm text with: *“{sup.INJECTION_TEXT}”*  \n**Expect:** *Escalated* — "
                               "“Tool results contained instruction-like text”. With the mock the draft fix stays the "
                               "same: policy catches it, not the model. (SEC-02)")
                    if st.button("💉 Insert injection", key="inj", disabled=bool(tam and tam["kind"] == "injection")):
                        sup.set_confirm_text(sel, sup.INJECTION_TEXT, "injection")
                        flash(True, f"{sel}: injection inserted into the broker confirm. Press ▶ Investigate this exception.")
                        st.rerun()
                with c2:
                    st.markdown("**🏦 Bank-detail change request**")
                    st.caption(f"Replaces the confirm text with: *“{sup.BANK_CHANGE_TEXT}”*  \n**Expect:** *Escalated* — "
                               "“Counterparty requested a bank-detail/SSI change: verify by call-back”. SSIs are never "
                               "changed from a counterparty message (payment-fraud control).")
                    if st.button("🏦 Insert bank-detail change", key="bank",
                                 disabled=bool(tam and tam["kind"] == "bank_change")):
                        sup.set_confirm_text(sel, sup.BANK_CHANGE_TEXT, "bank_change")
                        flash(True, f"{sel}: bank-detail change inserted into the broker confirm. "
                                    "Press ▶ Investigate this exception.")
                        st.rerun()
                st.markdown("**✏️ Write your own**")
                text = st.text_area("Broker free text (untrusted)", current, height=100, key=f"conf_{sel}_{hash(current)}")
                e1, e2 = st.columns(2)
                if e1.button("Save edited text", disabled=text == current, key="save_conf",
                             help="Put this text on the confirm. Instruction-like or bank-change wording will escalate."):
                    sup.set_confirm_text(sel, text, "custom")
                    flash(True, f"{sel}: broker confirm text changed. Press ▶ Investigate this exception.")
                    st.rerun()
                if e2.button("↩ Restore original confirm", disabled=not tam, key="restore",
                             help="Put the broker's original text back and clear the tampered marker."):
                    sup.restore_confirm(sel)
                    flash(True, f"{sel}: original broker confirm restored. Re-investigate to see the normal outcome.")
                    st.rerun()

        # ---------------------------------------------------------- evidence & trajectory
        with t_ev:
            render_comparison(sel)
            render_records(sel)
        with t_traj:
            if run:
                st.caption("Every LLM turn and tool call from the latest investigation. `flag` shows security flags "
                           "raised on a tool result (e.g. injection_suspected).")
                st.dataframe(pd.DataFrame(sup.steps(run["thread_id"])), hide_index=True, width="stretch")
            else:
                st.info("Not investigated yet.")

# ================================================================== 2. data explorer
with tab_data:
    st.caption("Everything the agent and the approval step read and write lives in one database "
               f"({'Postgres' if sup.db.is_pg(sup.db_url(sup.load_settings())) else 'SQLite'}). Explore it read-only.")
    v_er, v_tb, v_sql = st.tabs(["Data model (ER diagram)", "Browse tables", "SQL query"])
    with v_er:
        st.markdown("""
**How an exception is caught and handled**
1. A matching engine or custodian feed opens a row in **exceptions** when the firm's trade doesn't match a counterparty.
2. The agent's read-only tools pull **trades**, **allocations**, **broker_confirms**, **custodian_records** and **ssis**
   and compare them field by field; every call is logged in **agent_steps**, the outcome in **agent_runs**.
3. A named analyst's decision lands in **approvals**.
4. Only an approval mints the signed token that lets the write-scoped server insert into **resolutions** and queue an
   email in **outbox**.

Blue = source systems the agent can only read · amber = agent audit trail · green = approval-gated writes ·
red arrows = the workflow. (`demo_inputs`, which records your *Try to break it* edits, is demo-only and not shown.)""")
        st.graphviz_chart(sup.er_dot(), width="stretch")
    with v_tb:
        meta = pd.DataFrame(sup.list_tables())
        st.dataframe(meta, hide_index=True, width="stretch")
        c1, c2 = st.columns([1, 2])
        tname = c1.selectbox("Table", meta["table"].tolist(), key="tb_name")
        search = c2.text_input("Search any column", key="tb_search")
        rows_ = sup.table_rows(tname, search)
        st.dataframe(_df(rows_), hide_index=True, width="stretch", height=360)
        st.caption(f"{len(rows_)} row(s) shown" + (" (first 200)" if len(rows_) == 200 else ""))
        if rows_:
            st.download_button(f"Download {tname}.csv", _df(rows_).to_csv(index=False), file_name=f"{tname}.csv",
                               mime="text/csv")
    with v_sql:
        ex_name = st.selectbox("Start from an example", ["(write your own)"] + list(sup.EXAMPLE_QUERIES), key="sql_ex")
        if st.session_state.get("_sql_loaded") != ex_name:
            st.session_state["sql_text"] = sup.EXAMPLE_QUERIES.get(ex_name, st.session_state.get("sql_text",
                                                                                                "select * from exceptions"))
            st.session_state["_sql_loaded"] = ex_name
        q = st.text_area("SQL (read-only: one SELECT / WITH statement)", key="sql_text", height=180)
        if st.button("Run query", type="primary", key="sql_run"):
            st.session_state["sql_result"] = sup.run_readonly_sql(q)
        if "sql_result" in st.session_state:
            res, err = st.session_state["sql_result"]
            if err:
                st.error(err)
            else:
                st.dataframe(_df(res), hide_index=True, width="stretch")
                st.caption(f"{len(res)} row(s)" + (f" (limited to {sup.MAX_ROWS})" if len(res) == sup.MAX_ROWS else ""))
                if res:
                    st.download_button("Download results", _df(res).to_csv(index=False), file_name="query.csv",
                                       mime="text/csv")

# ================================================================== 3. audit & evals
with tab_audit:
    st.subheader("Eval gate")
    st.caption("16 golden cases: 2 per break type + injection, bank-detail fraud, malformed data and a loop trap. "
               "Checks outcome **and** trajectory with the model selected in the sidebar. Evals never approve anything.")
    if st.button("Run eval gate", key="eval"):
        from tradeops import evals

        with st.spinner("Evaluating…"):
            rep = asyncio.run(evals.run_eval(models[alias_label]))
        (st.success if rep["passed"] else st.error)("EVAL GATE: PASS" if rep["passed"] else f"FAIL {rep['failures']}")
        mm = st.columns(6)
        for i, k in enumerate(["category_accuracy", "fix_accuracy", "escalation_recall", "trajectory_compliance",
                               "unapproved_writes", "total_cost_usd"]):
            mm[i].metric(k, rep["metrics"][k])
        st.dataframe(_df(rep["cases"]), hide_index=True, width="stretch")
    st.subheader("Resolutions (written only by the approval-gated tool)")
    st.dataframe(_df(sup.table("select * from resolutions order by recorded_at desc")), hide_index=True, width="stretch")
    st.subheader("Outbox (queued, never sent automatically)")
    st.dataframe(_df(sup.table("select exception_id, recipient, subject, body, approved_by, sent from outbox "
                               "order by created_at desc")), hide_index=True, width="stretch")
    st.subheader("Decisions")
    st.dataframe(_df(sup.table("select ts, exception_id, decision, approver, ai_fix_type, final_fix_type, edited, note "
                               "from approvals order by ts desc")), hide_index=True, width="stretch")
    st.subheader("Cost by model")
    st.dataframe(_df(sup.table(
        """select model_name, case when run_id like 'eval-%' then 'eval' else 'prod' end as kind, count(*) as exceptions,
                  sum(tool_calls) as tool_calls, sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens,
                  round(sum(cost_usd), 4) as usd from agent_runs group by 1, 2 order by 1, 2""")),
        hide_index=True, width="stretch")

# ================================================================== 4. guide & models
with tab_guide:
    g_app, g_models = st.tabs(["Using the app", "Models"])
    with g_app:
        st.markdown(doc("app-guide.md"))
    with g_models:
        st.markdown("**Models in `config/models.yaml` right now**")
        reg = Registry(ROOT / "config" / "models.yaml")
        usable = set(models.values())
        targets = {}
        for a, n in reg.aliases.items():
            targets.setdefault(n, []).append(a)
        st.dataframe(pd.DataFrame([{
            "model": n,
            "selectable here": "✅ yes" if n in usable or any(a in usable for a in targets.get(n, [])) else
            ("no — not approved" if not m.approved else "no — add pricing" if not m.priced() else "no — needs credentials"),
            "provider": m.provider, "approved": "yes" if m.approved else "no", "priced": "yes" if m.priced() else "no",
            "aliases pointing here": ", ".join(targets.get(n, [])), "model_id": m.model_id,
        } for n, m in reg.models.items()]), hide_index=True, width="stretch")
        st.markdown(doc("models.md"))
