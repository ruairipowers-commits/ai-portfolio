.PHONY: setup all data eval test ui cost clean
setup:      ## install (editable) with UI and dev extras
	pip install -e ".[ui,dev]"
all:        ## offline demo: every sample transcript → output/*.report.{md,html}
	coach all
data: ; python scripts/generate_sample_data.py
eval: ; coach eval
test: ; pytest -q
ui: ; coach ui
cost: ; coach cost-report
clean: ; rm -rf output logs warehouse
