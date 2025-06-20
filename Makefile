PY_SOURCE=defspec tests examples

sync:
	@uv sync --all-extras --all-groups

lint:
	@uv run ruff check ${PY_SOURCE}
	@uv run mypy --non-interactive --install-types defspec tests

format:
	@uv run ruff check --fix ${PY_SOURCE}
	@uv run ruff format ${PY_SOURCE}

clean:
	@-rm -rf dist build */__pycache__ *.egg-info

build:
	@uv build

publish: build
	@uv publish

test:
	@uv run pytest -v tests

.PHONY: lint format clean build publish test
