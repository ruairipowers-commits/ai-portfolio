.PHONY: setup all data ingest eval compare test ui serve cost clean
setup:      ## install (editable) with UI + dev extras
	pip install -e ".[ui,dev]"
all:        ## end-to-end offline demo
	rqa all
data: ; rqa data
ingest: ; rqa ingest
eval: ; rqa eval
compare: ; rqa compare-retrieval
test: ; pytest -q
ui: ; rqa ui
serve: ; rqa serve
cost: ; rqa cost-report
clean: ; rm -rf warehouse output data
