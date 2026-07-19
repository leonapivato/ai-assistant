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
# persona is `architecture` or `adversarial`. Sends the diff to OpenAI.
review-codex persona base="master":
    scripts/codex-review.sh "$1" "${2:-master}"

# Claim an isolated workspace for one branch/PR: always a linked worktree, so
# any number of agents can run in parallel with none sharing a working tree.
# Prints WORKSPACE=<path> — work only there. See CONTRIBUTING "Coordinating
# parallel work". Example: just claim-workspace memory/add-cache
# Omit base for the default (origin/master); give one to stack this branch on
# another, e.g. just claim-workspace models/part-2 models/part-1
# The empty default here is just-level only: when base is genuinely omitted
# the script gets a single argument, not an explicit-but-empty one — an
# explicit "" is invalid (base must not be empty), so this recipe must not
# forward it as if it were real input the caller typed.
claim-workspace branch base="":
    if [ -n "$2" ]; then scripts/claim-workspace.sh "$1" "$2"; else scripts/claim-workspace.sh "$1"; fi

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
    uv run pre-commit install --install-hooks --hook-type commit-msg
    git config commit.template .gitmessage
