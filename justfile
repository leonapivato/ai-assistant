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

# The test leg of ADR-0136 §2's fast gate — the whole suite, distributed, for the
# rounds *between* §1's two anchors. It is neither anchor: §1 requires the suite
# and not a command name, and both anchors run `just check`, as CI does.
#
# Two flags here are load-bearing rather than tuning, so neither should be
# dropped without reading what it buys.
#
# `--basetemp` is about socket paths, not about tidiness. xdist inserts a
# `popen-gwN/` component under the temp root, which took the hub's AF_UNIX paths
# to 112 bytes against this platform's 108-byte `sun_path` budget — nine failures
# that say nothing whatever about the code. A short root buys the margin back.
# pytest *empties* whatever it is given, so this points at a per-clone scratch
# path under /tmp and deliberately not at $TMPDIR, which is the one place a
# reader may have made long on purpose.
#
# `--deselect tests/core/test_protocol_triad.py` is structural. That check reads
# the run record `tests/conftest.py` accumulates across the session; under xdist
# each worker accumulates only its own, so the check runs on one worker, sees
# none of the contract subclasses that passed on the others, and reports every
# Protocol as missing its triad. It is incompatible with a distributed run, not
# flaky in one. Deselecting costs no enforcement: `just check`, both ADR-0136
# anchors and CI all run it serially, so a real triad gap still cannot merge.
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# The suite in parallel — ADR-0136 §2's fast gate, and never one of its anchors
test-fast *args:
    uv run pytest -n auto \
        --basetemp="/tmp/pt-$(basename "$(pwd)")" \
        --deselect tests/core/test_protocol_triad.py \
        "$@"

# Tier 1 — an ADR file or an issue number that does not exist — exits non-zero;
# Tier 2 — unresolved code citations and liveness disagreements — is reported and
# never fails, and a non-empty Tier 2 list is expected (ADR-0088 §3). Tier 1 also
# runs inside `just test`, so this recipe is the *report*, not the gate. Extra
# args pass through, e.g. `just citations --no-tracker`.
#
# Last line, because `just --list` shows only that one: what this recipe reports.
# What the ADRs cite, checked against the repository (ADR-0088 §6)
citations *args:
    uv run python scripts/check_citations.py "$@"

# Advisory dependency vulnerability audit
audit:
    uv run pip-audit

# Derived project status — packages, Protocols, ADRs + gaps (generated, never hand-edited)
status:
    uv run python scripts/project_status.py

# The cross-change view ADR-0020 §2 and ADR-0025 §3 both phrase their revisit
# condition in terms of. Reads the ship comments already on GitHub; adds no
# instrumentation and gates nothing. Extra args passed through, e.g.
# `just review-history --limit 40`.
#
# Last line, because `just --list` shows only that one: what this recipe reports.
# Review aggregate across recently merged PRs — read-only, and gates nothing
review-history *args:
    uv run python scripts/review_history.py "$@"

# persona is `architecture` or `adversarial`. Sends the diff to OpenAI. Omit
# base-ref to let codex-review.sh pick origin/main when known (else local
# main) — an empty default here, not a hardcoded "main", so that
# resolution actually runs instead of being short-circuited by this recipe.
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# Review by Codex (a different model) vs a base branch; read-only
review-codex persona base="":
    scripts/codex-review.sh "$1" "$2"

# Refuses unless a review artifact covers the content the PR head carries,
# whatever commit the artifact is filed under. Two paths are accepted
# (ADR-0027 §2). Base unmoved: the recorded base and tree must both match the
# PR's merge base and HEAD's tree (ADR-0020 §3). Base moved: the recorded base
# must be a proper ancestor of the merge base, the reviewed patch identity
# unchanged, and the move must clear ADR-0027 §3's floor — necessary but not
# sufficient — with the drift published per §4. CONTRIBUTING.md ("Report the
# review, then mark it ready") carries the full conditions.
#
# Last line, because `just --list` shows only that one: what this recipe posts.
# Report the local Codex review to the PR — the merge-readiness step (ADR-0015)
ship:
    scripts/ship.sh

# Ask that same acceptance rule what it would decide, BEFORE pushing a rebase —
# `ship`'s own code, nothing written to GitHub, and a PR head that still lags
# HEAD is fine because this is meant to run before the push. Prints the inputs it
# judged: the base move's file set with ADR-0027 §3 floor paths marked, and where
# it made no floor claim, which of the three reasons applies. Rebase FIRST — onto
# the PR's own base branch, which is not always main — because on a HEAD that
# does not contain the fetched tip it refuses rather than reporting a floor
# tested over the range to the OLD merge base: an earlier base move rather than
# the prospective one, and where nothing else moved, an empty range (issue #751).
#
# Last line, because `just --list` shows only that one: what a base move costs.
# Would this base move cost a review round? Rebase first, then ask (ADR-0027 §2)
drill:
    scripts/ship.sh --drill

# First-time developer setup
setup:
    uv sync
    uv run pre-commit install --install-hooks
    git config commit.template .gitmessage
