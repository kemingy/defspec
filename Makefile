PY_SOURCE=defspec tests examples docs

sync:
	@uv sync --all-extras --all-groups

lint:
	@uv run -- ruff check ${PY_SOURCE}
	@uv run -- ruff format --check ${PY_SOURCE}
	@uv run -- mypy --non-interactive --install-types defspec tests
	@uv run -- ty check

format:
	@uv run -- ruff check --fix ${PY_SOURCE}
	@uv run -- ruff format ${PY_SOURCE}

clean:
	@-rm -rf dist build */__pycache__ *.egg-info

build:
	@uv build

publish: build
	@uv publish

test:
	@uv run pytest -v tests

doc:
	@cd docs && make html && cd ..
	@uv run -m http.server -d docs/build/html -b 127.0.0.1 8531

.PHONY: lint format clean build publish test
