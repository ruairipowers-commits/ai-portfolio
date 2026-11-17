#!/usr/bin/env bash
# Build all three native engines and run the test suites.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Python dependencies"
python3 -m pip install -r requirements.txt

echo "==> 1/3 Rust order book (maturin)"
( cd lob_engine && cargo test --release -q && maturin build --release -q \
  && python3 -m pip install --force-reinstall --no-deps target/wheels/lob_engine-*.whl )

echo "==> 2/3 Backtester (pybind11 kernel, editable install)"
python3 -m pip install -e backtester

echo "==> 3/3 Options engine (pybind11)"
python3 -m pip install ./options_engine

echo "==> Tests"
python3 -m pytest -q lob_engine/tests backtester/tests options_engine/tests

cat <<'EOF'

Done. Launch any app:
  streamlit run lob_engine/app/app.py
  streamlit run backtester/app/app.py
  streamlit run options_engine/app/app.py
EOF
