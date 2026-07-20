# Task runner for common workflows. Install `just`: https://github.com/casey/just
# Run `just` with no arguments to list recipes.

# Expose recipe arguments as "$1", "$2", ... so recipes reference them
# shell-quoted instead of interpolating {{...}} as bare text (which would let a
# crafted argument run commands). Every recipe that forwards an argument to a
# command below uses the quoted positional form.
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
    uv run pytest "$@"

# Advisory dependency vulnerability audit
audit:
    uv run pip-audit

# Derived project status — packages, Protocols, ADRs + gaps (generated, never hand-edited)
status:
    uv run python scripts/project_status.py

# Adversarial review by Codex (a different model) vs a base branch; read-only.
# persona is `architecture` or `adversarial`. Sends the diff to OpenAI. Omit
# base-ref to let codex-review.sh pick origin/main when known (else local
# main) — an empty default here, not a hardcoded "main", so that
# resolution actually runs instead of being short-circuited by this recipe.
review-codex persona base="":
    scripts/codex-review.sh "$1" "$2"

# Report the local Codex review to the PR — the merge-readiness step (ADR-0015).
# Refuses unless a review artifact covers the content the PR head carries: its
# recorded base and tree must both match the PR's merge base and HEAD's tree
# (ADR-0020 §3), whatever commit the artifact is filed under.
ship:
    scripts/ship.sh

# First-time developer setup
setup:
    uv sync
    uv run pre-commit install --install-hooks
    git config commit.template .gitmessage
