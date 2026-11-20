.PHONY: install check lint lint-python lint-docs lint-yaml hooks format

install:
	uv sync

check: lint

lint: lint-python lint-docs lint-yaml

lint-python:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	uv run bandit -c pyproject.toml -r src
	uv run codespell

lint-docs:
	uv run pre-commit run markdownlint-cli2 --all-files
	uv run python tools/check_agent_docs.py --no-coupling

lint-yaml:
	uv run yamllint -c .yamllint.yaml .pre-commit-config.yaml .yamllint.yaml docs/constitution/SOURCE.lock

hooks:
	uv run pre-commit install
	uv run pre-commit run --all-files

format:
	uv run ruff format .
	uv run ruff check --fix .
	uv run pre-commit run markdownlint-cli2 --all-files
