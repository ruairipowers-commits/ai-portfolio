.PHONY: setup all check backfill eval test ui up down cost clean
setup:      ## install (editable) with UI + dev extras
	pip install -e ".[ui,dev]"
all:        ## end-to-end offline demo (embedded Postgres)
	eodhb all
check: ; eodhb check
backfill: ; eodhb backfill
eval: ; eodhb eval
test: ; pytest -q
ui: ; eodhb ui
up:         ## Postgres + pgvector, Airflow and the app in Docker
	docker compose up -d --build
down: ; docker compose down
cost: ; eodhb cost-report
clean: ; rm -rf warehouse output data dbt/target dbt/logs
