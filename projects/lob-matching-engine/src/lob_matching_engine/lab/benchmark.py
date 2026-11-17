import os
import platform
import time

import numpy as np
import pandas as pd
import plotly.express as px_
import plotly.graph_objects as go
import streamlit as st

from lob_matching_engine import _engine as L
from lob_matching_engine import demo

CAP = 1_000_000 if demo.enabled() else 5_000_000   # hosted demo: keep runs short on a shared machine

st.title("⏱️ Benchmark lab")
st.caption("Throughput and tail latency of the native engine. Commands are pre-generated, so RNG cost isn't timed. "
           "Each run replays the same stream twice on fresh books: once untimed (throughput) and once with a "
           "timer around every call (latency distribution).")

if "bench_runs" not in st.session_state:
    st.session_state.bench_runs = []

PRESETS = {
    "Realistic venue (default)": dict(limit=0.45, market=0.05, ioc=0.05, fok=0.02, post_only=0.05, stop=0.01, cancel=0.32, modify=0.05),
    "Passive / quote stuffing": dict(limit=0.55, market=0.01, ioc=0.0, fok=0.0, post_only=0.04, stop=0.0, cancel=0.40, modify=0.0),
    "Aggressive / taker heavy": dict(limit=0.40, market=0.25, ioc=0.15, fok=0.05, post_only=0.0, stop=0.05, cancel=0.10, modify=0.0),
    "Cancel/replace storm": dict(limit=0.35, market=0.02, ioc=0.0, fok=0.0, post_only=0.0, stop=0.0, cancel=0.33, modify=0.30),
}

with st.sidebar:
    st.subheader("Workload")
    preset = st.selectbox("Flow preset", list(PRESETS))
    n = st.select_slider("Commands", [x for x in [100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000] if x <= CAP], value=500_000)
    prefill = st.select_slider("Pre-filled resting orders", [0, 1_000, 10_000, 50_000, 100_000, 250_000], value=10_000)
    depth_ticks = st.slider("Passive placement (mean ticks from mid)", 1.0, 100.0, 8.0,
                            help="Wider placement = more populated price levels = longer best-price rescans.")
    mean_qty = st.slider("Mean order size", 1, 200, 20)
    stp = st.toggle("Self-trade prevention on", value=False)
    label = st.text_input("Run label", value=preset.split(" (")[0])

tab_run, tab_sweep, tab_method = st.tabs(["Single run", "Parameter sweep", "Methodology"])


def bench(n, prefill, mix, depth_ticks, mean_qty, stp):
    return L.benchmark(n_orders=n, prefill=prefill, stp=stp,
                       params=dict(mix=mix, depth_ticks=depth_ticks, mean_qty=float(mean_qty), seed=42))


with tab_run:
    if st.button("Run benchmark", type="primary"):
        with st.spinner(f"Replaying {n:,} commands twice…"):
            r = bench(n, prefill, PRESETS[preset], depth_ticks, mean_qty, stp)
        r["label"] = f"{len(st.session_state.bench_runs) + 1}. {label} · {n / 1e6:g}M · prefill {prefill:,}"
        st.session_state.bench_runs.append(r)

    runs = st.session_state.bench_runs
    if not runs:
        st.info("Pick a workload in the sidebar and run a benchmark.")
    else:
        r = runs[-1]
        p = dict(r["percentiles"])
        c = st.columns(7)
        c[0].metric("Throughput", f"{r['throughput_ops'] / 1e6:.2f} M/s")
        c[1].metric("Mean", f"{r['mean_ns']:.0f} ns")
        c[2].metric("p50", f"{p[0.5]:,} ns")
        c[3].metric("p99", f"{p[0.99]:,} ns")
        c[4].metric("p99.9", f"{p[0.999]:,} ns")
        c[5].metric("p99.99", f"{p[0.9999]:,} ns")
        c[6].metric("Max", f"{p[1.0] / 1e3:,.1f} µs")
        st.caption(f"{r['trades']:,} trades · {r['volume']:,} shares · {r['events']:,} engine events · "
                   f"{r['resting_orders']:,} resting at end over {r['levels_bid']}/{r['levels_ask']} bid/ask levels · "
                   f"timer overhead ≈ {r['timer_overhead_ns']:.0f} ns (included in latencies)")

        e, cnt = np.array(r["hist_edges"]), np.array(r["hist_counts"])
        centers = np.sqrt(e[:-1] * e[1:])
        c1, c2 = st.columns(2)
        fh = go.Figure(go.Bar(x=centers, y=cnt, width=np.diff(e), marker_color="#4575b4"))
        for q, col in ((0.5, "#1a9850"), (0.99, "#fdae61"), (0.999, "#d73027")):
            fh.add_vline(x=p[q], line_dash="dash", line_color=col, annotation_text=f"p{q * 100:g}")
        fh.update_layout(title="Latency histogram (log-x)", xaxis_type="log", xaxis_title="ns per command",
                         height=380, margin=dict(l=10, r=10, t=40, b=10))
        c1.plotly_chart(fh, width="stretch")

        fc = go.Figure()
        for rr in runs[-6:]:
            ee, cc = np.array(rr["hist_edges"]), np.array(rr["hist_counts"])
            ccdf = 1 - np.cumsum(cc) / cc.sum()
            fc.add_trace(go.Scatter(x=ee[1:], y=np.clip(ccdf, 1e-7, 1), mode="lines", line_shape="hv", name=rr["label"]))
        for lvl in (1e-2, 1e-3, 1e-4):
            fc.add_hline(y=lvl, line_dash="dot", line_color="#bbb")
        fc.update_layout(title="Tail plot: P(latency > x), last 6 runs", xaxis_type="log", yaxis_type="log",
                         xaxis_title="ns", height=380, margin=dict(l=10, r=10, t=40, b=10), legend=dict(font_size=10))
        c2.plotly_chart(fc, width="stretch")

        pk = pd.DataFrame(r["per_kind"])
        c1, c2 = st.columns([1.2, 1])
        c1.markdown("**Latency by command type**")
        c1.dataframe(pk, hide_index=True, width="stretch",
                     column_config={"mean_ns": st.column_config.NumberColumn(format="%.0f")})
        m = pk.melt(id_vars="kind", value_vars=["p50_ns", "p99_ns", "p999_ns"], var_name="pct", value_name="ns")
        fk = px_.bar(m, x="kind", y="ns", color="pct", barmode="group", log_y=True)
        fk.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        c2.plotly_chart(fk, width="stretch")

        st.markdown("**Run history**")
        hist = pd.DataFrame([{"run": x["label"], "M ops/s": x["throughput_ops"] / 1e6, "mean ns": x["mean_ns"],
                              **{f"p{q * 100:g}": v for q, v in x["percentiles"]}, "trades": x["trades"]} for x in runs])
        st.dataframe(hist, hide_index=True, width="stretch",
                     column_config={"M ops/s": st.column_config.NumberColumn(format="%.2f"),
                                    "mean ns": st.column_config.NumberColumn(format="%.0f")})
        if st.button("Clear history"):
            st.session_state.bench_runs = []
            st.rerun()

with tab_sweep:
    st.markdown("Vary one workload dimension and see how throughput and the tail respond.")
    dim = st.selectbox("Sweep", ["Pre-filled book size", "Passive placement width", "Cancel share", "Market-order share"])
    sweep_n = st.select_slider("Commands per point", [100_000, 250_000, 500_000], value=250_000)
    grids = {"Pre-filled book size": [0, 1_000, 10_000, 50_000, 150_000, 300_000],
             "Passive placement width": [2, 5, 10, 25, 50, 100],
             "Cancel share": [0.05, 0.15, 0.3, 0.45, 0.6],
             "Market-order share": [0.0, 0.05, 0.15, 0.3, 0.45]}
    if st.button("Run sweep", type="primary"):
        rows, bar = [], st.progress(0.0)
        for i, v in enumerate(grids[dim]):
            mix = dict(PRESETS[preset])
            pf, dt = prefill, depth_ticks
            if dim == "Pre-filled book size":
                pf = v
            elif dim == "Passive placement width":
                dt = float(v)
            elif dim == "Cancel share":
                mix["cancel"] = v
            else:
                mix["market"] = v
            t0 = time.perf_counter()
            r = bench(sweep_n, pf, mix, dt, mean_qty, stp)
            p = dict(r["percentiles"])
            rows.append({dim: v, "M ops/s": r["throughput_ops"] / 1e6, "p50": p[0.5], "p99": p[0.99], "p99.9": p[0.999],
                         "levels": r["levels_bid"] + r["levels_ask"], "resting": r["resting_orders"]})
            bar.progress((i + 1) / len(grids[dim]))
        st.session_state.sweep = (dim, pd.DataFrame(rows))
    if "sweep" in st.session_state:
        d, df = st.session_state.sweep
        c1, c2 = st.columns(2)
        c1.plotly_chart(px_.line(df, x=d, y="M ops/s", markers=True, title="Throughput"), width="stretch")
        c2.plotly_chart(px_.line(df, x=d, y=["p50", "p99", "p99.9"], markers=True, log_y=True, title="Latency percentiles (ns)"),
                        width="stretch")
        st.dataframe(df, hide_index=True, width="stretch")

with tab_method:
    st.markdown(f"""
**Engine design** (see `src/book.rs`)
- Dense price ladder: one level per tick inside a fixed band, so locating a level is an array index.
- Each level is an intrusive doubly-linked FIFO stored in a slab with a free list, so add, cancel and fill are
  O(1) and allocation-free in steady state. Price-time priority comes straight from the FIFO.
- `id → slot` map with a multiplicative hasher; cached best bid/ask rescanned only when the best level empties.
- Stops live in ordered maps keyed by (trigger, arrival) and are released after each print, so cascades work.

**Measurement**
- Single thread, release build with fat LTO. Python only calls in and out; the GIL is released during the run.
- *Throughput* comes from a separate untimed loop over the same command stream, so timer overhead doesn't
  deflate it.
- *Latency* wraps each command in `Instant::now()`; the measured timer overhead is shown and included.
- Tails (p99.9+ and max) are dominated by page faults when the slab grows, hash-map resizes and OS
  scheduling. For production numbers, pin the core (`taskset -c 3`), disable turbo/C-states, pre-size the
  slab and run the native CLI:

```bash
cd rust && cargo run --release --bin lob-bench -- 5_000_000 50_000
```

**This machine:** {platform.processor() or platform.machine()} · {os.cpu_count()} logical CPUs · Python {platform.python_version()}
""")
