.PHONY: install fmt lint type test check migrate serve scan baseline doctor

install:
	uv sync

fmt:
	uv run ruff format src tests

lint:
	uv run ruff check src tests --fix

type:
	uv run mypy src

test:
	uv run pytest -q

check:
	uv run ruff format --check src tests
	uv run ruff check src tests
	uv run mypy src
	uv run pytest -q

migrate:
	uv run opportunity-radar db migrate

serve:
	uv run opportunity-radar serve

scan:
	uv run opportunity-radar scan

baseline:
	uv run opportunity-radar baseline

doctor:
	uv run opportunity-radar doctor
