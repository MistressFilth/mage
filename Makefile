.DEFAULT_GOAL := help

.PHONY: help init sync unit-test features-test test clean lint typecheck format check release

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

init: ## Set up the environment from scratch
	uv sync --all-extras

sync: ## Update an existing environment to match pyproject.toml
	uv sync --all-extras

unit-test: ## Run unit tests only
	uv run pytest tests/unit

features-test: ## Run behavior/feature tests only
	uv run pytest tests/features

test: unit-test features-test ## Run all tests

clean: ## Delete caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .coverage dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +

lint: ## Run linters
	uv run ruff check src tests scripts

typecheck: ## Run typecheckers
	uv run ty check src tests scripts

format: ## Run formatters (may auto-edit)
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

check: lint typecheck format ## Run lint, typecheck, and format together

release: ## Build, tag, and release a new version
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=X.Y.Z"; exit 2; }
	$(MAKE) check
	$(MAKE) test
	uv version $(VERSION)
	git add pyproject.toml uv.lock CHANGELOG.md
	git commit -m "chore(release): v$(VERSION)"
	git tag -a "v$(VERSION)" -m "v$(VERSION)"
	uv build
	git push --follow-tags
