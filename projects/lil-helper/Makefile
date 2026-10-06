.PHONY: setup all plan simulate eval test ui serve app clean
setup:      ## install (editable) with UI and dev extras, and the phone app's packages
	pip install -e ".[ui,dev]" && cd app && npm install
plan: ; helper plan
all simulate: ; helper simulate --weeks 4
eval: ; helper eval
test: ; pytest -q && cd app && npx tsc --noEmit
ui: ; helper ui
serve: ; helper serve
app: ; cd app && npx expo start
clean: ; rm -rf output logs warehouse
