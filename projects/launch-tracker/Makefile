.PHONY: setup all data build fetch eval test ui flows cost clean
setup:      ## install (editable) with the app and dev extras
	pip install -e ".[ui,dev]"
all:        ## offline end to end on the fictional sample: load → headline → summaries → digest → what changed
	launches all
data: ; launches data
build: ; launches build
fetch:      ## real data (needs network): Launch Library 2 within 15 requests/hour, GCAT and SATCAT daily
	LAUNCHES_MODE=live launches fetch
eval: ; launches eval
test: ; pytest -q
ui: ; launches ui
flows:      ## scheduled refreshes with Prefect (pip install -e ".[flows]")
	launches flows
cost: ; launches cost-report
clean: ; rm -rf warehouse output logs data/fixture
