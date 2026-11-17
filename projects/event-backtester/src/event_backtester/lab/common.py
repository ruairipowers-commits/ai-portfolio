from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from event_backtester import ExecConfig, synthetic_ticks

GREEN, RED, BLUE, GREY = "#1a9850", "#d73027", "#4575b4", "#8c8c8c"


@st.cache_data(show_spinner="Generating ticks…", max_entries=8)
def make_ticks(**kw) -> pd.DataFrame:
    return synthetic_ticks(**kw)


def get_ticks() -> pd.DataFrame:
    """The dataset shared with the Research workflow page (data/ticks/default.parquet), else a fresh synthetic one."""
    if "ticks" not in st.session_state:
        from event_backtester.store import Settings, workspace
        s = Settings.load()
        p = workspace() / s["dataset_path"]
        if p.exists():
            st.session_state.ticks = pd.read_parquet(p)
            d = s["dataset"]
            st.session_state.ticks_label = f"Default dataset · {d['days']} days · trend {d['trend_strength']} · seed {d['seed']}"
        else:
            st.session_state.ticks = make_ticks()
            st.session_state.ticks_label = "Synthetic · 60 days · default settings"
    return st.session_state.ticks


def data_badge():
    t = get_ticks()
    st.caption(f"📦 Data: **{st.session_state.get('ticks_label', 'custom')}** · {len(t):,} ticks · "
               f"{t.ts.dt.date.nunique()} days · {t.ts.iloc[0]:%Y-%m-%d} → {t.ts.iloc[-1]:%Y-%m-%d}. Change it on *Market data*.")


def exec_controls(prefix: str = "", show_mode: bool = True) -> ExecConfig:
    """Sidebar execution/cost model controls."""
    with st.sidebar.expander("Execution & costs", expanded=True):
        bar = st.selectbox("Bar size", ["1min", "5min", "15min", "30min", "1h"], index=1, key=prefix + "bar")
        size = st.number_input("Shares per unit of signal", 1, 1_000_000, 500, step=100, key=prefix + "size")
        cash = st.number_input("Starting equity ($)", 1_000, 100_000_000, 100_000, step=10_000, key=prefix + "cash")
        lat = st.select_slider("Decision → order latency", [0, 1, 10, 50, 100, 250, 1000, 5000, 30000], value=50,
                               format_func=lambda x: f"{x} ms", key=prefix + "lat")
        otype = "market"
        timeout = 1
        if show_mode:
            otype = st.radio("Order type", ["market", "limit"], horizontal=True, key=prefix + "otype",
                             help="Limit = join the near touch passively; converts to market after the timeout.")
            if otype == "limit":
                timeout = st.slider("Limit timeout (bars)", 1, 10, 1, key=prefix + "to")
        c1, c2 = st.columns(2)
        cps = c1.number_input("¢ per share", 0.0, 5.0, 0.35, step=0.05, key=prefix + "cps") / 100
        minc = c2.number_input("Min ticket $", 0.0, 20.0, 0.35, step=0.05, key=prefix + "minc")
        cbps = c1.number_input("Commission bps", 0.0, 50.0, 0.0, step=0.5, key=prefix + "cbps")
        slip = c2.number_input("Slippage bps", 0.0, 50.0, 0.0, step=0.5, key=prefix + "slip")
        imp = c1.number_input("Impact bps @1% ADV", 0.0, 200.0, 10.0, step=1.0, key=prefix + "imp",
                              help="Square-root law: impact = this × √(order / 1% of ADV)")
        adv = c2.number_input("ADV (shares)", 10_000, 500_000_000, 2_000_000, step=100_000, key=prefix + "adv")
    return ExecConfig(bar=bar, size=float(size), latency_ms=float(lat), order_type=otype, limit_timeout_bars=timeout,
                      comm_per_share=cps, comm_bps=cbps, min_comm=minc, slip_bps=slip, impact_bps_at_1pct=imp,
                      adv=float(adv), init_cash=float(cash))


def fmt_metrics(d: dict) -> pd.DataFrame:
    pct = {"Total return", "Annualised return", "Annualised vol", "Max drawdown", "Time in market"}
    rows = []
    for k, v in d.items():
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            s = "—"
        elif k in pct:
            s = f"{v:.2%}"
        elif isinstance(v, (int, np.integer)) or (isinstance(v, float) and float(v).is_integer() and abs(v) > 100):
            s = f"{v:,.0f}"
        else:
            s = f"{v:,.2f}"
        rows.append((k, s))
    return pd.DataFrame(rows, columns=["metric", "value"])


def heatmap(z, x, y, title, xlab, ylab, fmt=".2f", colorscale="RdYlGn", zmid=0, mark=None):
    fig = go.Figure(go.Heatmap(z=z, x=x, y=y, colorscale=colorscale, zmid=zmid, texttemplate="%{z:" + fmt + "}",
                               textfont=dict(size=9), hovertemplate=f"{xlab} %{{x}}<br>{ylab} %{{y}}<br>%{{z:{fmt}}}<extra></extra>"))
    if mark is not None:
        fig.add_trace(go.Scatter(x=[mark[0]], y=[mark[1]], mode="markers", marker=dict(symbol="star", size=16, color="black"),
                                 name="best", showlegend=False))
    fig.update_layout(title=title, xaxis_title=xlab, yaxis_title=ylab, height=480, margin=dict(l=10, r=10, t=40, b=10))
    return fig
