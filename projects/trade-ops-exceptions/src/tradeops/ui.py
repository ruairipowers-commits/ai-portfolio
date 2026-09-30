"""Streamlit approval queue (HITL-02). Run: `tradeops ui`.

Analysts see the agent's evidence, can edit the fix and the email draft, and approve or reject.
Approval resumes the paused LangGraph thread; only then is the write-scoped MCP server started.
"""
import asyncio
import json

import streamlit as st

from tradeops import db
from tradeops.runner import db_url, decide, load_settings

st.set_page_config(page_title="Trade-ops exception queue", layout="wide")
s = load_settings()
con = db.connect(db_url(s))

st.title("Settlement exception queue")
st.caption("AI-investigated. Nothing is recorded or sent until you approve. Emails go to an outbox; they are never sent automatically.")

approver = st.sidebar.text_input("Your name (recorded on approval)", value="")
show = st.sidebar.radio("Show", ["awaiting_approval", "escalated", "resolved", "rejected"])
rows = con.query("""select * from agent_runs where run_id not like 'eval-%' and status = ?
                    order by exception_id""", (show,))
st.sidebar.metric("Items", len(rows))
if not rows:
    st.info("Nothing here. Run `tradeops investigate` to populate the queue.")
    st.stop()

ex = st.selectbox("Exception", [r["exception_id"] for r in rows],
                  format_func=lambda e: f"{e} — {next(r for r in rows if r['exception_id'] == e)['category']}")
run = next(r for r in rows if r["exception_id"] == ex)
p, flags = json.loads(run["proposal_json"]), json.loads(run["policy_flags"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Category", p["category"])
c2.metric("Proposed fix", p["fix_type"])
c3.metric("Tool calls", run["tool_calls"])
c4.metric("Cost", f"${run['cost_usd']:.4f}")
if flags["reasons"]:
    st.error("Escalated: " + "; ".join(flags["reasons"]))

st.subheader("Root cause")
st.write(p["root_cause"])
st.subheader("Evidence (checked against source systems)")
st.table([{"tool": e["tool"], "field": e["field"], "value": str(e["value"])} for e in p["evidence"]])

with st.expander("Agent trajectory"):
    st.table(con.query("select step, kind, name, args_json, flag from agent_steps where thread_id = ? order by step",
                       (run["thread_id"],)))

if show == "awaiting_approval":
    st.subheader("Decision")
    fix_details = st.text_area("Fix details", p["fix_details"])
    email = p.get("email_draft")
    if email:
        subj = st.text_input("Email subject", email["subject"])
        body = st.text_area("Email body", email["body"], height=140)
    note = st.text_input("Note")
    a, r = st.columns(2)
    edits = {"fix_details": fix_details}
    if email:
        edits["email_draft"] = {**email, "subject": subj, "body": body}
    if a.button("Approve", type="primary", disabled=not approver):
        st.write(asyncio.run(decide(ex, "approve", approver, note, edits)))
    if r.button("Reject", disabled=not approver):
        st.write(asyncio.run(decide(ex, "reject", approver, note)))
    if not approver:
        st.warning("Enter your name in the sidebar to approve or reject.")
