.PHONY: setup ui all data run eval test bench cost rust-test clean
setup:      ## install (editable; builds the Rust engine with maturin) with UI and dev extras
	pip install -e ".[ui,dev]"
all:        ## end-to-end offline demo
	lob-matching-engine all
data: ; lob-matching-engine data
run: ; lob-matching-engine run
eval: ; lob-matching-engine eval
test: ; pytest -q
rust-test: ; cd rust && cargo test --release
bench:      ## native benchmark (no Python in the loop)
	cd rust && cargo run --release --bin lob-bench -- 2_000_000 10_000
ui: ; lob-matching-engine ui
cost: ; lob-matching-engine cost-report
clean: ; rm -rf output data rust/target
