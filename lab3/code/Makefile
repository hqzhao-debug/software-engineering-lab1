PYTHON ?= python3

.PHONY: build test lint format demo metrics check

build:
	$(PYTHON) tools/build.py

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m ruff check campus_market tests tools
	$(PYTHON) -m ruff format --check campus_market tests tools

format:
	$(PYTHON) -m ruff check --fix campus_market tests tools
	$(PYTHON) -m ruff format campus_market tests tools

demo:
	$(PYTHON) -m campus_market.demo

metrics:
	$(PYTHON) tools/metrics.py

check: lint test build
