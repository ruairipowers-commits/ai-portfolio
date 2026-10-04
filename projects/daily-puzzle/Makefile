.PHONY: install test all serve ui eval pack fixtures
install: ; pip install -e ".[dev]"
test: ; pytest -q
all: ; puzzle all                                   ## offline end-to-end: reserve, a simulated week, a pack, eval gate
serve: ; puzzle serve                               ## player site + scheduler on http://localhost:8800
ui: ; puzzle ui                                     ## operator app (Streamlit)
eval: ; puzzle eval
pack: ; puzzle pack --count 5 --seed 2026           ## questions PDF + answer-key PDF in output/packs/
fixtures: ; python scripts/generate_fixtures.py     ## regenerate the bundled stand-ins for Hugging Face files
