.PHONY: setup all data request price eval test ui cost clean
setup:      ## install (editable; builds the C++ kernel) with UI and dev extras
	pip install -e ".[ui,dev]"
all:        ## end-to-end offline demo: sample requests → tickets
	options-greeks-engine all
data: ; options-greeks-engine data
request: ; options-greeks-engine request "Buy 2 ACME 105 calls expiring December" --account DR-02
price: ; options-greeks-engine price
eval: ; options-greeks-engine eval
test: ; pytest -q
ui: ; options-greeks-engine ui
cost: ; options-greeks-engine cost-report
clean: ; rm -rf output data build
