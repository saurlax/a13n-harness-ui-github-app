.PHONY: sync check test build

sync:
	uv sync --locked

check:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked pyright
	uv run --locked pytest

test:
	uv run --locked pytest

build:
	uv build
