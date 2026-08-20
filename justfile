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
# that say nothing whatever about the code. A short root buys the margin back:
# the worst path in the suite runs 66 bytes below its root, so `/tmp/pt-XXXXXX`
# leaves ~26 to spare where the default root left none. It is under /tmp and
# deliberately not under $TMPDIR, which is the one place a reader may have made
# long on purpose.
#
# It is a **fresh** root per invocation because pytest *empties* whatever it is
# given. Anything derived from the clone — its name, its path — is shared by two
# runs of this recipe in one clone, and by two clones that differ only in their
# parent, and either pair would delete a live worker's tree out from under it.
# `mktemp -d` cannot collide. The cost is that pytest's own retention of the last
# few runs is gone, so a failing run keeps its tree and says where, and a passing
# one is removed.
#
# `--deselect tests/core/test_protocol_triad.py` is structural. That check reads
# the run record `tests/conftest.py` accumulates across the session; under xdist
# each worker accumulates only its own, so the check runs on one worker, sees
# none of the contract subclasses that passed on the others, and reports every
# Protocol as missing its triad. It is incompatible with a distributed run, not
# flaky in one. Since ADR-0166 this recipe may also discharge an ADR-0136 anchor,
# so the deselection is no longer covered by a serial local run: CI's full serial
# gate on every push to an open PR is what still catches a real triad gap, and
# ADR-0166 §2 says to pick `just check` when the diff touches a Protocol or a
# canonical fake. And only a run that COLLECTED THE WHOLE SUITE AND EXECUTED IT
# discharges an anchor: the `*args` below reach pytest, as does a `PYTEST_ADDOPTS`
# in the environment (issue #1243), and anything through either that narrows,
# stops early or only collects makes this a scoped selection under ADR-0136 §2
# however the recipe is spelled (ADR-0166 §1).
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# The suite in parallel — ADR-0136 §2's fast gate, and, unnarrowed, an anchor
test-fast *args:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d /tmp/pt-XXXXXX)"
    # `--basetemp` goes *after* "$@" so a forwarded one cannot displace it: pytest
    # takes the last occurrence, and a run that emptied some other directory while
    # the cleanup below removed this one would be the hazard this recipe exists to
    # avoid, silently. `-n auto` leads instead, so `just test-fast -n 4` still works.
    if uv run pytest -n auto --deselect tests/core/test_protocol_triad.py \
            "$@" --basetemp="$tmp"; then
        rm -rf "$tmp"
    else
        status=$?
        echo "just test-fast: temp tree kept for inspection at $tmp" >&2
        exit "$status"
    fi

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

# The one mechanical commit that ends an ADR lane (ADR-0165 §2). Once the
# required review set is green on one tree, this flips the header's single
# `- Status: Proposed` line to `- Status: Accepted` in one ADR file and changes
# nothing else — not the `- Date:` line, not a ratification note, not a second
# ADR. That one-line shape is the entire reason `just ship` then accepts the head
# without a fresh round (ADR-0165 §3): `scripts/ship.sh` recognises it by
# rebuilding the file from its parent's with this same transform, so a flip
# carrying one further byte simply is not recognised and costs its round, exactly
# as today. Write the note or restamp the date in the flip commit if you want
# them — you are choosing to pay the round, which is a correct outcome.
#
# It refuses on a dirty tree, on `main`, on a detached HEAD, and on a `Status`
# line that is not exactly `- Status: Proposed` — a caveat on that line is the
# text most likely to say "not yet", so it is never rewritten silently.
# `--dry-run` prints the plan and changes nothing; `--adr <path>` names the ADR
# when the branch carries more than one standing `Proposed`.
#
# Last line, because `just --list` shows only that one: what this recipe writes.
# Ratify this branch's ADR — the one-line Proposed → Accepted flip (ADR-0165)
adr-ratify *args:
    uv run python scripts/adr_ratify.py ratify "$@"

# The documented way out of draft, and the only one that carries ADR-0165 §5's
# guard: it refuses while any ADR this PR adds or modifies still reads
# `- Status: Proposed`, naming the file. Issue #1044 is two lanes in two days
# that shipped ready with the flip never made, caught both times by a human
# afterwards. The refusal sits HERE and nowhere else — an ADR is `Proposed` for
# its whole reviewed life, so `just ship` still posts an intermediate round on a
# genuinely `Proposed` ADR and refuses nothing on that ground.
#
# It reads the LOCAL tree, so it first refuses unless the PR's head is local
# HEAD — otherwise a flip committed but not pushed would certify a file only this
# clone holds while GitHub still shows the ADR standing `Proposed`, which is the
# same failure with one more step. `ship` carries that precondition already, and
# in the documented order it has run by now anyway.
#
# Typing `gh pr ready` directly is not stopped by this: that command is GitHub's,
# not this repository's. ADR-0165 §5 accepts that limit rather than engineering
# around it, and names a required CI check as its Revisit condition.
#
# Last line, because `just --list` shows only that one: what this recipe does.
# Flip the PR out of draft — refuses on an unratified ADR (ADR-0165 §5)
ready:
    uv run python scripts/adr_ratify.py check-ready
    gh pr ready

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
