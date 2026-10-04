# prodc -- task runner. uv is the only tool needed (the package itself is zero-dep).
# One-time setup after cloning:  make install-hooks
.DEFAULT_GOAL := help
.PHONY: help install-hooks format lint typecheck test check bump docs build

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install-hooks: ## point git at the tracked .githooks/ (pre-commit + pre-push)
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit .githooks/pre-push scripts/bump-version scripts/check-version-bump
	@echo "hooks installed: core.hooksPath -> .githooks"

format: ## auto-format + autofix lint (ruff)
	uv run ruff format src tests examples
	uv run ruff check --fix src tests examples

lint: ## lint (ruff) -- same as CI
	uv run ruff check src tests examples

typecheck: ## type-check (pyright) -- same as CI
	uv run pyright

test: ## run the test suite
	uv run pytest -q

check: lint typecheck test ## the full CI test stage: lint + typecheck + test

bump: ## bump version in pyproject.toml -- TYPE=patch|minor|major (default patch)
	./scripts/bump-version $(or $(TYPE),patch)

docs: ## build docs strictly (as CI / Read the Docs do)
	uv run --extra docs mkdocs build --strict

build: ## build sdist + wheel into dist/
	uv build --out-dir dist
