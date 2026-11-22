PYTHON := .venv/bin/python

.PHONY: setup run check

setup:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m flask --app app run --port 5002

check:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m pytest
	node --test test_dashboard.js
