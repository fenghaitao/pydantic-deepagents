.DEFAULT_GOAL := all

.PHONY: .uv
.uv: ## Check that uv is installed
	@uv --version || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

.PHONY: .pre-commit
.pre-commit: ## Check that pre-commit is installed
	@pre-commit -V || echo 'Please install pre-commit: https://pre-commit.com/'

.PHONY: install
install: .uv .pre-commit ## Install the package, dependencies, and pre-commit for local development
	uv sync --frozen --all-extras --group dev --group lint --group docs
	uv run pre-commit install --install-hooks

.PHONY: install-all-python
install-all-python: ## Install and synchronize an interpreter for Python 3.13
	UV_PROJECT_ENVIRONMENT=.venv313 uv sync --python 3.13 --frozen --all-extras --group dev --group lint --group docs

.PHONY: sync
sync: .uv ## Update local packages and uv.lock
	uv sync --all-extras --group dev --group lint --group docs

# ── Deterministic dependency management ────────────────────────────────────────
# Why this matters:
#   uv resolves and records environment markers (os, arch, Python version) in
#   uv.lock.  Running `uv lock` on macOS or Windows inserts platform-specific
#   markers that differ from the Linux x86_64 CI environment, causing spurious
#   diff churn and potential runtime errors in CI.
#
#   pyproject.toml already constrains resolution via [tool.uv].required-environments
#   to "linux x86_64", but the lock file still encodes the *generating* platform
#   unless it is produced on that same platform.
#
#   Rules of thumb:
#     • Day-to-day:          make uv-sync        (never modify uv.lock)
#     • Adding a dependency: make uv-lock-update  (Linux x86_64 only, or via Docker)
#     • CI:                  uv sync --locked     (validate lock, abort on drift)
# ───────────────────────────────────────────────────────────────────────────────

.PHONY: uv-sync
uv-sync: .uv ## Install deps from the frozen lock file — never modifies uv.lock
	uv sync --locked --all-groups

.PHONY: uv-lock-update
uv-lock-update: .uv ## Regenerate uv.lock (Linux x86_64 + Python 3.13) and sync to it; use this when adding/upgrading dependencies, never for day-to-day syncing
	@# Guard: lock must be generated on Linux x86_64 to avoid platform marker drift.
	@if [ "$$(uname -s)" != "Linux" ] || [ "$$(uname -m)" != "x86_64" ]; then \
		echo ""; \
		echo "ERROR: uv-lock-update must run on Linux x86_64 (current: $$(uname -s)/$$(uname -m))."; \
		echo ""; \
		exit 1; \
	fi
	uv lock --python 3.13
	uv sync --locked --all-groups

.PHONY: uv-lock-check
uv-lock-check: .uv ## Verify uv.lock is up-to-date and consistent (used in CI)
	uv lock --check

.PHONY: format
format: ## Format the code
	uv run ruff format
	uv run ruff check --fix --fix-only

.PHONY: lint
lint: ## Lint the code
	uv run ruff format --check
	uv run ruff check

.PHONY: typecheck-pyright
typecheck-pyright:
	@# To typecheck for a specific version of python, run 'make install-all-python' then set environment variable PYRIGHT_PYTHON=3.10 or similar
	PYRIGHT_PYTHON_IGNORE_WARNINGS=1 uv run pyright $(if $(PYRIGHT_PYTHON),--pythonversion $(PYRIGHT_PYTHON))

.PHONY: typecheck-mypy
typecheck-mypy:
	uv run mypy pydantic_deep tests

.PHONY: typecheck
typecheck: typecheck-pyright ## Run static type checking

.PHONY: typecheck-both
typecheck-both: typecheck-pyright typecheck-mypy ## Run static type checking with both Pyright and Mypy

.PHONY: security
security: ## Run Bandit security scanner on production code
	uv run bandit -r pydantic_deep -x tests -ll

.PHONY: test
test: ## Run tests and collect coverage data
	@# To test using a specific version of python, run 'make install-all-python' then set environment variable PYTEST_PYTHON=3.10 or similar
	COLUMNS=150 $(if $(PYTEST_PYTHON),UV_PROJECT_ENVIRONMENT=.venv$(subst .,,$(PYTEST_PYTHON))) uv run $(if $(PYTEST_PYTHON),--python $(PYTEST_PYTHON)) coverage run -m pytest --durations=20
	@uv run coverage report

.PHONY: test-all-python
test-all-python: ## Run tests on Python 3.10 to 3.13
	COLUMNS=150 UV_PROJECT_ENVIRONMENT=.venv310 uv run --python 3.10 coverage run -p -m pytest
	COLUMNS=150 UV_PROJECT_ENVIRONMENT=.venv311 uv run --python 3.11 coverage run -p -m pytest
	COLUMNS=150 UV_PROJECT_ENVIRONMENT=.venv312 uv run --python 3.12 coverage run -p -m pytest
	COLUMNS=150 UV_PROJECT_ENVIRONMENT=.venv313 uv run --python 3.13 coverage run -p -m pytest
	@uv run coverage combine
	@uv run coverage report

.PHONY: testcov
testcov: test ## Run tests and generate an HTML coverage report
	@echo "building coverage html"
	@uv run coverage html

.PHONY: docs
docs: ## Build the documentation
	uv run mkdocs build

.PHONY: docs-serve
docs-serve: ## Build and serve the documentation
	uv run mkdocs serve

.PHONY: backend-start
backend-start: potpie-start ## Start potpie backend + observability stack (Vector/VictoriaMetrics/VictoriaLogs/Tempo/Grafana)
	bash scripts/vector/observability.sh start

.PHONY: backend-stop
backend-stop: ## Stop observability stack and force-stop potpie backend (clears stale locks)
	-bash scripts/vector/observability.sh stop 2>/dev/null || true
	$(MAKE) potpie-stop-force
	@# Remove stale NFS flock files left by VictoriaMetrics/VictoriaLogs after unclean shutdown.
	@-find scripts/vector/data -name "flock.lock" -delete 2>/dev/null || true

.PHONY: potpie-start
potpie-start: ## Start the potpie backend
	$(MAKE) -C code-graph-providers/potpie start

.PHONY: potpie-stop
potpie-stop: ## Stop the potpie backend
	$(MAKE) -C code-graph-providers/potpie stop

.PHONY: potpie-stop-force
potpie-stop-force: ## Force-stop the potpie backend
	$(MAKE) -C code-graph-providers/potpie stop-force

.PHONY: potpie-mcp-start
potpie-mcp-start: ## Start the potpie MCP server (SSE) on a dynamically allocated port
	$(eval POTPIE_MCP_PORT := $(shell uv run python -c "from ports_allocator import PortManager; print(PortManager().allocate('potpie.mcp'))"))
	@echo "Starting potpie-mcp on port $(POTPIE_MCP_PORT)..."
	uv run potpie-mcp start -b -t sse -p $(POTPIE_MCP_PORT)

.PHONY: potpie-mcp-stop
potpie-mcp-stop: ## Stop the potpie MCP server and release the allocated port
	uv run potpie-mcp stop
	@uv run python -c "from ports_allocator import PortManager; PortManager().release('potpie.mcp')" 2>/dev/null || true

.PHONY: potpie-ci-ensure-backend
potpie-ci-ensure-backend: ## CI: verify all potpie backend services healthy; start if not
	$(MAKE) -C code-graph-providers/potpie ensure-healthy HEALTH_FLAGS="--phoenix"

.PHONY: potpie-ci-backup-logfire
potpie-ci-backup-logfire: ## CI: back up potpie logfire session traces
	$(MAKE) -C code-graph-providers/potpie backup-logfire

# ── scip-clang ────────────────────────────────────────────────────────────────

.PHONY: setup-scip-clang
setup-scip-clang: ## Download pre-built scip-clang binary (default, v0.3.3)
	bash code-graph-providers/scip-languages/setup-scip-clang.sh

.PHONY: setup-scip-clang-build
setup-scip-clang-build: ## Build scip-clang from source (requires Bazel/npm)
	bash code-graph-providers/scip-languages/setup-scip-clang.sh --build

.PHONY: all
all: typecheck security testcov ## Run code static type checks, security scan, and tests with coverage report generation

.PHONY: help
help: ## Show this help (usage: make help)
	@echo "Usage: make [recipe]"
	@echo "Recipes:"
	@awk '/^[a-zA-Z0-9_-]+:.*?##/ { \
		helpMessage = match($$0, /## (.*)/); \
		if (helpMessage) { \
			recipe = $$1; \
			sub(/:/, "", recipe); \
			printf "  \033[36m%-20s\033[0m %s\n", recipe, substr($$0, RSTART + 3, RLENGTH); \
		} \
	}' $(MAKEFILE_LIST)
