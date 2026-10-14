.PHONY: install test all serve ui eval check sources
install: ; pip install -e ".[dev]"
test: ; pytest -q
all: ; course all                     ## offline end-to-end: checks, a simulated learner, a suggestion, a build, a revision, eval gate
serve: ; course serve                 ## learner site on http://localhost:8810
ui: ; course ui                       ## operator app (Streamlit): approvals, builds, feedback
eval: ; course eval
check: ; course check                 ## content checks on every course file
sources: ; course sources             ## refresh sources/tech from the site's tech pages
