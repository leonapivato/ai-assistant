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
# base-ref to let codex-review.sh pick origin/master when known (else local
# master) — an empty default here, not a hardcoded "master", so that
# resolution actually runs instead of being short-circuited by this recipe.
review-codex persona base="":
    scripts/codex-review.sh "$1" "$2"

# Claim an isolated workspace for one branch/PR: always a linked worktree, so
# any number of agents can run in parallel with none sharing a working tree.
# Prints WORKSPACE=<path> — work only there. See CONTRIBUTING "Coordinating
# parallel work". Example: just claim-workspace memory/add-cache
# Omit base for the default (origin/master); give one to stack this branch on
# another, e.g. just claim-workspace models/part-2 models/part-1
# `*base` (variadic), not `base=""` (a defaulted single param): a defaulted
# param always has *some* value once just resolves it, so the recipe body can
# never tell "caller wrote an explicit empty string" apart from "caller wrote
# nothing at all" — both arrive as base="". Variadic captures exactly what
# was actually typed, zero or more items, so "$@" forwards the real argument
# count through to the script's own base_given/empty-base checks unchanged
# (verified directly: `just claim-workspace area/b ""` reaches the script as
# two arguments, the second genuinely empty, not collapsed to one).
claim-workspace branch *base:
    scripts/claim-workspace.sh "$@"

# Claim several workspaces at once, concurrently (one worktree per branch).
# Example: just claim-workspaces memory/add-cache tools/registry planning/goal
claim-workspaces *branches:
    scripts/claim-workspaces.sh "$@"

# Release a claimed workspace once its PR merges (FORCE=1 to discard changes).
release-workspace branch:
    scripts/release-workspace.sh "$1"

# List active workspaces: branch, clean/dirty, last commit, path.
workspaces:
    scripts/list-workspaces.sh

# Report worktrees whose PR has merged or closed (dry-run; FORCE=1 to remove).
prune-workspaces:
    scripts/prune-workspaces.sh

# First-time developer setup
setup:
    uv sync
    uv tool install pre-commit
    pre-commit install --install-hooks
    git config commit.template .gitmessage
