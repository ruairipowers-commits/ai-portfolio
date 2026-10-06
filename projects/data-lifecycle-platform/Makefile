.PHONY: setup all data fetch build graph eval test ui api mcp dagster cost clean
setup:      ## install (editable) with every extra the demo uses
	pip install -e ".[ui,dev,hub,api,mcp,orchestration]"
all:        ## offline end to end: seed → ingest → dbt + tests → SHACL → graph → AI workflows
	dlp all
data: ; python scripts/generate_sample_data.py
fetch:      ## real Hugging Face slices (needs network): replaces the offline fixture
	dlp fetch
build: ; dlp build
graph: ; dlp graph
eval: ; dlp eval
test: ; pytest -q
ui: ; dlp ui
api: ; dlp api
mcp: ; dlp mcp
dagster:    ## Dagster UI over the same assets
	dagster dev -m orchestration.definitions
cost: ; dlp cost-report
clean: ; rm -rf warehouse output data/landing semantic/target semantic/logs
