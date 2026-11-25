PYTHON := .venv/bin/python

.PHONY: setup run check bench seed studio eval

setup:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m flask --app app run --port 5002

check:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m pytest
	node --test test_dashboard.js test_assistant_page.js

bench:
	$(PYTHON) -m scripts.bench

seed:
	$(PYTHON) -m assistant.seed

studio:
	.venv/bin/langgraph dev

eval:
	$(PYTHON) -m scripts.eval_assistant
