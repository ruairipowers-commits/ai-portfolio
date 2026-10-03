.PHONY: install test serve index ask digest
install: ; pip install -e ".[dev]"
test: ; pytest -q
serve: ; siteassist serve                       ## http://localhost:8700 (needs PORTFOLIO_SITE_URL or SITE_INDEX)
index: ; siteassist index
ask: ; siteassist ask "What does the governance console do?"
digest: ; siteassist digest                     ## build yesterday's engagement email without sending
