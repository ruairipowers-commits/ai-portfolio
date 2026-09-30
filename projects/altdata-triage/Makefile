.PHONY: setup all data ingest transform triage eval test cost clean
setup:      ## install (editable) with dev extras
	pip install -e ".[dev]"
all:        ## end-to-end offline demo
	altdata-triage all
data: ; altdata-triage data
ingest: ; altdata-triage ingest
transform: ; altdata-triage transform
triage: ; altdata-triage triage
eval: ; altdata-triage eval --alias triage-primary
test: ; pytest -q
cost: ; altdata-triage cost-report
docs:       ## dbt lineage docs (DATA-01)
	DUCKDB_PATH=warehouse/altdata.duckdb dbt docs generate --project-dir dbt --profiles-dir dbt && echo "open dbt/target/index.html"
clean: ; rm -rf warehouse output data/incoming dbt/target dbt/seeds/security_master.csv
