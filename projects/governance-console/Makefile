.PHONY: setup serve seed import test catalog clean
setup:      ## install (editable) with dev extras
	pip install -e ".[dev]"
serve: ; govconsole serve            ## http://localhost:8600
seed: ; govconsole seed              ## regenerate the labelled simulated history
import: ; govconsole import-spool    ## load events local workflow runs wrote to the spool file
catalog: ; govconsole catalog
test: ; pytest -q
clean: ; rm -rf warehouse
