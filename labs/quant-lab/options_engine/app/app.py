"""Options pricing & Greeks engine — Streamlit front end.

Run:  streamlit run options_engine/app/app.py
"""
import streamlit as st

st.set_page_config(page_title="Options pricing & Greeks", page_icon="🧮", layout="wide")
pages = [
    st.Page("pages/pricer.py", title="Pricer & Greeks", icon="🧮", default=True),
    st.Page("pages/surfaces.py", title="Greeks explorer", icon="🗻"),
    st.Page("pages/convergence.py", title="Convergence & speed lab", icon="📉"),
    st.Page("pages/exotics.py", title="Exotics & American", icon="🧩"),
    st.Page("pages/strategies.py", title="Strategy builder & risk", icon="🛠️"),
]
st.navigation(pages).run()
st.sidebar.caption("C++ engine (pybind11, std::thread) · built by Ruairi Powers with Claude")
