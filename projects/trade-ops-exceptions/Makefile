.PHONY: setup server all queue eval test test-server ui cost clean
setup:        ## Python (editable, with UI + dev extras) and the Node MCP server
	pip install -e ".[ui,dev]" && tradeops build-server
server: ; tradeops build-server
all:          ## synthetic data -> investigate every open exception (mock model, offline)
	tradeops all
queue: ; tradeops queue
eval: ; tradeops eval
test: ; pytest -q
test-server: ; cd mcp-server && npm test
ui: ; tradeops ui
cost: ; tradeops cost-report
clean: ; rm -rf warehouse output data/ground_truth.json mcp-server/dist
