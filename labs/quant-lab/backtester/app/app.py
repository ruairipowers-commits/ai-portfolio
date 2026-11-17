"""Event-driven backtester — Streamlit front end.

Run:  streamlit run backtester/app/app.py
"""
import streamlit as st

st.set_page_config(page_title="Event-driven backtester", page_icon="🔁", layout="wide")
pages = [
    st.Page("pages/data.py", title="Market data", icon="📦"),
    st.Page("pages/backtest.py", title="Strategy backtest", icon="🔁", default=True),
    st.Page("pages/costs.py", title="Cost & latency sensitivity", icon="💸"),
    st.Page("pages/optimize.py", title="Sweep & walk-forward", icon="🧭"),
    st.Page("pages/lookahead.py", title="Lookahead-bias lab", icon="🔮"),
]
st.navigation(pages).run()
st.sidebar.caption("Python event engine + C++ kernels · built by Ruairi Powers with Claude")
