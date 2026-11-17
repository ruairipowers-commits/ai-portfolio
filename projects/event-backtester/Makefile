setup:      ## install (editable; builds the C++ kernel) with UI and dev extras
	pip install -e ".[ui,dev]"
all:        ## end-to-end offline demo
	event-backtester all
data: ; event-backtester data
run: ; event-backtester run
eval: ; event-backtester eval
test: ; pytest -q
ui: ; event-backtester ui
cost: ; event-backtester cost-report
clean: ; rm -rf output data build
