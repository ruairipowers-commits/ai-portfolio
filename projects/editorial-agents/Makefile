.PHONY: install test all serve eval scout
install: ; pip install -e ".[dev]"
test: ; pytest -q
all: ; editorial all                   ## offline: scout on fixtures, topic email to warehouse/outbox, eval gate
serve: ; editorial serve               ## queue page + pick/dismiss + scheduler on http://localhost:8810
eval: ; editorial eval
scout: ; editorial scout               ## live sources
