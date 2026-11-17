"""Limit Order Book & Matching Engine — Streamlit front end.

Run:  streamlit run lob_engine/app/app.py
"""
import streamlit as st

st.set_page_config(page_title="LOB & Matching Engine", page_icon="📈", layout="wide")

pages = [
    st.Page("pages/desk.py", title="Trading desk", icon="🧾", default=True),
    st.Page("pages/simulator.py", title="Market simulator", icon="🌊"),
    st.Page("pages/benchmark.py", title="Benchmark lab", icon="⏱️"),
    st.Page("pages/scenarios.py", title="Matching rules, step by step", icon="🧪"),
]
st.navigation(pages).run()
st.sidebar.caption("Rust engine · price-time priority · built by Ruairi Powers with Claude")
