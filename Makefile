PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: install test lint demo serve clean

install:
	uv venv .venv --python 3.12 || python3 -m venv .venv
	uv pip install --python $(PY) -e ".[dev]" || $(PIP) install -e ".[dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests

demo:
	$(PY) -m crewgit.cli demo

serve:
	$(PY) -m crewgit.cli serve

clean:
	rm -rf .crewgit/runs .crewgit/worktrees .crewgit/board.db crewgit-demo
