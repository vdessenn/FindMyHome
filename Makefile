# Single entry point: what you type by hand is what a CI will call one day.
PY_MIN  := 3.11
VERSION  = $(shell uv version --short)

.PHONY: help install lint format typecheck test test-min check coverage build binary image clean cache-clear

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Create/sync the environment from uv.lock
	uv sync

lint:  ## Check style and errors without changing anything
	uv run ruff check .
	uv run ruff format --check .

format:  ## Fix and reformat in place
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## mypy --strict (checks the Site Protocol in particular)
	uv run mypy

test:  ## Tests on the development Python
	uv run pytest

test-min:  ## Tests on the minimum Python declared by requires-python
	UV_PROJECT_ENVIRONMENT=.venv-$(PY_MIN) uv run --python $(PY_MIN) pytest

check: lint typecheck test test-min  ## Everything that must be green before committing

coverage:  ## Coverage report - informative, never blocking
	uv run pytest --cov --cov-report=term-missing

build:  ## Wheel + sdist into dist/
	uv build

binary:  ## Standalone PyInstaller binary (Linux x86_64 on this machine)
	uv run pyinstaller packaging/findmyhome.spec --clean --noconfirm

image:  ## Docker image tagged with the project version
	docker build -t findmyhome:$(VERSION) .

cache-clear:  ## Empty the development HTTP cache (re-downloads next time)
	rm -rf .cache

clean:  ## Remove artefacts and tool caches (keeps the HTTP cache)
	rm -rf dist build .venv-* *.egg-info .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
