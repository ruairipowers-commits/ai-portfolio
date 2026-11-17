import pandas as pd
import streamlit as st

from lob_matching_engine import _engine as L
from lob_matching_engine.lab.common import ladder, tname

st.title("🧪 Matching rules, step by step")
st.caption("Each scenario runs on a fresh book through the real engine. Step through it, read the engine's events, "
           "and see the automatic check confirm the rule.")


def S(side, ot, price=0, qty=1, trader=1, trigger=None):
    return ("submit", side, ot, price, qty, trader, trigger)


SCENARIOS = {
    "Price-time priority": dict(
        intro="Better price always trades first; at the same price, earlier orders trade first (FIFO).",
        steps=[("Alice offers 5 @ 100.02", S("sell", "limit", 10002, 5, 2)),
               ("Bob offers 5 @ 100.01", S("sell", "limit", 10001, 5, 3)),
               ("Carol offers 5 @ 100.01 (after Bob)", S("sell", "limit", 10001, 5, 4)),
               ("You buy 12 with a limit at 100.02", S("buy", "limit", 10002, 12, 1))],
        check=lambda ev: [(e["maker_trader"], e["price"], e["qty"]) for e in ev[-1] if e["event"] == "trade"] == [(3, 10001, 5), (4, 10001, 5), (2, 10002, 2)],
        expect="Fills: Bob 5 @ 100.01 → Carol 5 @ 100.01 → Alice 2 @ 100.02."),
    "IOC vs FOK": dict(
        intro="Both refuse to rest. IOC takes what it can; FOK is all-or-nothing.",
        steps=[("Alice offers 5 @ 100.00", S("sell", "limit", 10000, 5, 2)),
               ("FOK buy 8 @ 100.00: only 5 available", S("buy", "fok", 10000, 8, 1)),
               ("IOC buy 8 @ 100.00", S("buy", "ioc", 10000, 8, 1))],
        check=lambda ev: not any(e["event"] == "trade" for e in ev[1]) and sum(e["qty"] for e in ev[2] if e["event"] == "trade") == 5,
        expect="FOK is killed with zero fills; IOC fills 5 and cancels 3."),
    "Post-only protection": dict(
        intro="Post-only (maker-only) orders are rejected if they would take liquidity.",
        steps=[("Alice offers 10 @ 100.05", S("sell", "limit", 10005, 10, 2)),
               ("Post-only buy @ 100.05 would cross", S("buy", "post_only", 10005, 10, 1)),
               ("Post-only buy @ 100.04 joins the bid", S("buy", "post_only", 10004, 10, 1))],
        check=lambda ev: ev[1][-1]["event"] == "rejected" and ev[2][-1]["event"] == "rested",
        expect="First is rejected, second rests at 100.04."),
    "Modify: keep vs lose priority": dict(
        intro="Reducing size at the same price keeps your place in the queue. Increasing size or changing price is cancel/replace.",
        steps=[("You bid 10 @ 99.90", S("buy", "limit", 9990, 10, 1)),
               ("Bob bids 10 @ 99.90", S("buy", "limit", 9990, 10, 3)),
               ("You size down to 6 (order #1)", ("modify", 1, 9990, 6)),
               ("You size up to 20 (order #1)", ("modify", 1, 9990, 20)),
               ("Alice sells 10 at market", S("sell", "market", 0, 10, 2))],
        check=lambda ev: ev[2][0]["kept_priority"] and not ev[3][0]["kept_priority"] and [e["maker_trader"] for e in ev[4] if e["event"] == "trade"] == [3],
        expect="After the size-up Bob is ahead of you, so Alice's sell fills Bob's 10."),
    "Stop cascade": dict(
        intro="Stops sit outside the book until the last trade touches the trigger. One stop's fills can trigger the next.",
        steps=[("Ask ladder: 5 @ each of 100.00–100.05", ("ladder", "sell", 10000, 6, 5, 2)),
               ("Bob: buy stop 5 @ trigger 100.01", S("buy", "stop_market", 0, 5, 3, 10001)),
               ("Carol: buy stop 5 @ trigger 100.02", S("buy", "stop_market", 0, 5, 4, 10002)),
               ("You lift 10 at market", S("buy", "market", 0, 10, 1))],
        check=lambda ev: sum(e["event"] == "triggered" for e in ev[3]) == 2,
        expect="Your buy prints 100.01 → Bob's stop fires and prints 100.02 → Carol's stop fires and prints 100.03."),
    "Self-trade prevention": dict(
        intro="With STP on, an order never trades against the same trader. The resting order is cancelled instead.",
        steps=[("You offer 5 @ 100.00", S("sell", "limit", 10000, 5, 1)),
               ("Alice offers 5 @ 100.00", S("sell", "limit", 10000, 5, 2)),
               ("You buy 5 @ 100.00", S("buy", "limit", 10000, 5, 1))],
        check=lambda ev: any(e.get("reason") == "self-trade prevention" for e in ev[2])
        and [e["maker_trader"] for e in ev[2] if e["event"] == "trade"] == [2],
        expect="Your resting offer is cancelled and you trade with Alice."),
    "Market order with thin book": dict(
        intro="Market orders walk the book until filled or liquidity runs out; the rest is cancelled, never rested.",
        steps=[("Alice offers 3 @ 100.00 and 3 @ 100.10", ("ladder", "sell", 10000, 2, 3, 2, 10)),
               ("You buy 10 at market", S("buy", "market", 0, 10, 1))],
        check=lambda ev: sum(e["qty"] for e in ev[1] if e["event"] == "trade") == 6 and ev[1][-1]["event"] == "cancelled",
        expect="6 shares fill across two levels, 4 are cancelled for insufficient liquidity."),
}


def run(book, cmd):
    if cmd[0] == "submit":
        _, side, ot, p, q, t, trig = cmd
        return book.submit(side, ot, p, q, t, trig)[1]
    if cmd[0] == "modify":
        return book.modify(cmd[1], cmd[2], cmd[3])[1]
    if cmd[0] == "ladder":
        _, side, start, n, q, t, *step = cmd
        step = step[0] if step else 1
        out = []
        for i in range(n):
            out += book.submit(side, "limit", start + i * step, q, t)[1]
        return out


name = st.selectbox("Scenario", list(SCENARIOS))
sc = SCENARIOS[name]
st.info(sc["intro"])
key = f"sc_{name}"
k = st.session_state.get(key, 0)
c1, c2, c3 = st.columns([1, 1, 4])
if c1.button("Next step ▶", disabled=k >= len(sc["steps"]), type="primary"):
    k += 1
if c2.button("Restart"):
    k = 0
st.session_state[key] = k

book = L.OrderBook(9_000, 11_000, stp=True)
all_ev = [run(book, cmd) for _, cmd in sc["steps"][:k]]
for i, (desc, _) in enumerate(sc["steps"]):
    done = i < k
    with st.container(border=True):
        st.markdown(f"{'✅' if done else '⬜'} **Step {i + 1}.** {desc}")
        if done and i == k - 1:
            ev = pd.DataFrame(all_ev[i])
            for col in ("taker_trader", "maker_trader"):
                if col in ev:
                    ev[col] = ev[col].map(lambda x: tname(int(x)) if pd.notna(x) else "")
            a, b = st.columns([3, 2])
            a.dataframe(ev, hide_index=True, width="stretch")
            b.dataframe(ladder(book, 8), hide_index=True, width="stretch")

if k == len(sc["steps"]):
    ok = sc["check"](all_ev)
    (st.success if ok else st.error)(f"{'Rule verified' if ok else 'Unexpected result'}: {sc['expect']}")
else:
    st.caption(f"Expected outcome: {sc['expect']}")
