# Task runner for common workflows. Install `just`: https://github.com/casey/just
# Run `just` with no arguments to list recipes.

# Pass recipe arguments as "$1", "$2", ... so they are shell-quoted rather than
# interpolated as bare text (which would let a crafted argument run commands).
set positional-arguments

# Show available recipes
default:
    @just --list

# Full local gate (Definition of Done): format check, lint, types, imports, tests
check: fmt-check lint types imports test

# Auto-fix formatting and lint issues
fix:
    uv run ruff format .
    uv run ruff check --fix .

# Verify formatting without modifying files
fmt-check:
    uv run ruff format --check .

# Lint with ruff
lint:
    uv run ruff check .

# Strict static type check
types:
    uv run mypy

# Enforce architecture dependency boundaries
imports:
    uv run lint-imports

# Run the test suite (extra args passed through, e.g. `just test -k version`)
test *args:
    uv run pytest {{args}}

# Advisory dependency vulnerability audit
audit:
    uv run pip-audit

# Derived project status — packages, Protocols, ADRs + gaps (generated, never hand-edited)
status:
    uv run python scripts/project_status.py

# Adversarial review by Codex (a different model) vs a base branch; read-only.
# persona is `architecture` or `adversarial`. Sends the diff to OpenAI.
review-codex persona base="master":
    scripts/codex-review.sh {{persona}} {{base}}

# Claim an isolated workspace for one branch/PR: the main checkout if free, else
# a linked worktree. Prints WORKSPACE=<path> — work only there. See CONTRIBUTING
# "Coordinating parallel work". Example: just claim-workspace memory/add-cache
claim-workspace branch:
    scripts/claim-workspace.sh "$1"

# Release a claimed workspace once its PR merges (FORCE=1 to discard changes).
release-workspace branch:
    scripts/release-workspace.sh "$1"

# First-time developer setup
setup:
    uv sync
    uv run pre-commit install --install-hooks --hook-type commit-msg
    git config commit.template .gitmessage
