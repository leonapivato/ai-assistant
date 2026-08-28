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

# The whole suite, distributed: ADR-0136 §2's fast gate for the rounds *between*
# §1's two anchors, and — since ADR-0166 §1, where nothing narrowed what it
# collected — the `pytest` step at either anchor as well. What discharges an
# anchor is the run and not the command name, so read the summary line.
#
# It runs the whole suite. It used to deselect
# `tests/core/test_protocol_triad.py`, because that check reads the run record
# `tests/conftest.py` accumulates and under xdist each worker accumulates only
# its own — so the check saw none of the contract subclasses that passed on the
# other workers and reported every Protocol as missing its triad. ADR-0179
# aggregates the workers' records on the controller instead, so the deselection
# is gone and this recipe collects and executes every test the tree declares.
#
# `--basetemp` is load-bearing rather than tuning, so it should not be dropped
# without reading what it buys.
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
# Keeping a failed run's tree is deliberate — it is what makes a failure
# inspectable — but the trees are ~1.3G each, they are shared across every clone
# on this machine, and /tmp is a tmpfs. Six of them fill it, and what that looks
# like from inside a clone is not "no space" but ~1700 failures in
# `tests/memory/test_sqlite_*`, every one of which passes in isolation (issue
# #1419). So the recipe reaps on entry, and it reaps only what it can show is
# its own and finished: a tree named the way `mktemp -d /tmp/pt-XXXXXX` names
# one, holding xdist's `popen-gw*` directories, carrying a LEASE FILE this recipe
# wrote, whose lock nobody holds, and older than the window below.
#
# The lease is what carries both halves of that. It is the only evidence of
# ownership available — the temp root has to stay six characters for the
# `sun_path` budget the next paragraph explains, so the name cannot be made
# repository-specific, and shape alone (a `pt-` name, `popen-gw*` children) is
# something any process on this machine could produce. And it is the only thing
# that can say a live run is live, since a run wedged in one test writes nothing
# below its own tree and would look idle from outside however long it stood.
#
# So each run holds an exclusive `flock` on its lease for its whole life and the
# reaper skips any tree whose lock it cannot take. The kernel drops the lock when
# the holder dies, so a killed run leaves a reapable tree rather than an immortal
# one — which a marker file would not, and #1419 is a bug about trees that never
# go away.
#
# It also reports when /tmp is low, so the 1700-failure run is diagnosed before it
# happens rather than after.
#
# Only a run that COLLECTED THE WHOLE SUITE AND EXECUTED IT discharges an anchor:
# the `*args` below reach pytest, as does a `PYTEST_ADDOPTS` in the environment
# (issue #1243), and anything through either that narrows, stops early or only
# collects makes this a scoped selection under ADR-0136 §2 however the recipe is
# spelled (ADR-0166 §1).
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# The suite in parallel — ADR-0136 §2's fast gate, and, unnarrowed, an anchor
test-fast *args:
    #!/usr/bin/env bash
    set -euo pipefail
    # Four hours: two orders of magnitude longer than a run of this suite, and
    # short enough that a day of failures across five clones cannot accumulate.
    stale_after=240
    # Written into every lease this recipe takes, and required of every lease it
    # reaps: it is what tells our tree from one that merely shares the shape.
    # Defined once, so the writer and the reader below cannot drift apart.
    lease_token='just test-fast lease (ai-assistant, issue #1419)'
    stale=""
    # `pt-??????` is exactly and only what the `mktemp` below produces, so a
    # directory that merely begins `pt-` is not a candidate however old it is.
    while IFS= read -r candidate; do
        # It must hold xdist's per-worker directories, which nothing but a run of
        # this recipe puts there. A tree from `just test-fast -n 0` has none and
        # is therefore never reaped -- a leak rather than a wrong deletion, which
        # is the direction to fail in.
        [ -n "$(find "$candidate" -maxdepth 1 -name 'popen-gw*' -print -quit)" ] || continue
        # It must carry THIS RECIPE's lease, and that lease must be free. The
        # lease is what makes the tree ours rather than merely tree-shaped: a
        # six-character `pt-` name and `popen-gw*` children describe a shape, and
        # any process on this machine could produce one -- so the lease is READ,
        # not merely counted, and one that does not name this recipe is somebody
        # else's and is left alone. The lease is also the only thing that can say
        # a live run is live -- a run wedged in one test writes nothing below its
        # own tree and looks idle from outside however long it stands, so no mtime
        # answers this.
        #
        # A tree with no lease of ours beside it is therefore never reaped,
        # whoever made it. That leaks the trees left by runs from before this
        # recipe leased them, and any left by another tool that happens to share
        # the shape; the low-space report below names those, to be removed by hand
        # once. Leaking is the direction to fail in.
        grep -q "^${lease_token}$" "$candidate.lease" 2>/dev/null || continue
        flock -n "$candidate.lease" true 2>/dev/null || continue
        stale="${stale}${candidate}"$'\n'
    done < <(find /tmp -maxdepth 1 -type d -name 'pt-??????' -user "$(id -un)" \
        -mmin +"$stale_after" 2>/dev/null || true)
    if [ -n "$stale" ]; then
        echo "just test-fast: reaping kept temp trees older than ${stale_after}m (#1419):" >&2
        printf '%s' "$stale" | sed 's/^/  /' >&2
        printf '%s' "$stale" | while IFS= read -r old; do rm -rf "$old" "$old.lease"; done
    fi
    free_kb="$(df -Pk /tmp | awk 'NR == 2 { print $4 }')"
    if [ "${free_kb:-0}" -lt 3145728 ]; then
        echo "just test-fast: /tmp has $((free_kb / 1024))M free and one run wants" \
             "~1.3G — these kept trees are why, and none of them was reapable" \
             "(too new, still leased, or carrying no lease of ours). If" \
             "you know one is dead, remove it by hand:" >&2
        ls -ldrt /tmp/pt-* >&2 2>/dev/null || true
    fi
    # At most TEST_FAST_SLOTS runs of this recipe per machine at once (default 3).
    # The suite is `-n auto`, one worker per core, and a run holds 3-5G; on a WSL
    # VM with 16G and a RAM-backed `/tmp`, four clones gating at once (the ordinary
    # shape of a dispatched wave) did not so much slow each other down as take the
    # VM down (2026-08-28, twice). One run alone keeps only ~4 of 8 cores busy, so
    # a few overlap usefully; beyond that they only contend. Three fits a 24G VM
    # (`.wslconfig`) -- on the 16G default, `TEST_FAST_SLOTS=2`. Taken BEFORE the
    # temp tree, so a run that is only waiting holds nothing in `/tmp`; released by
    # the kernel when this shell exits, killed or not. The names are not `pt-*`,
    # so the reaper above never sees them.
    slots="${TEST_FAST_SLOTS:-3}"
    # 1..64: a positive integer bounded well inside what shell arithmetic holds,
    # so no value that passes here can wrap negative and empty the loop below.
    case "$slots" in
        ''|*[!0-9]*|0*) echo "just test-fast: TEST_FAST_SLOTS must be a positive integer, got '$slots'" >&2; exit 2 ;;
    esac
    if [ "${#slots}" -gt 2 ] || [ "$slots" -gt 64 ]; then
        echo "just test-fast: TEST_FAST_SLOTS must be at most 64, got '$slots'" >&2; exit 2
    fi
    # The slots live in a directory only this user can write: the runtime
    # directory where there is one, else `/tmp/ai-assistant-<uid>` -- one fixed
    # name per user, so no environment variable can give two clones two
    # directories and two quotas -- which this recipe makes 0700 and checks is a
    # real directory it owns with that mode, so a planted one is refused, not used.
    # Per user, not per machine, which is what a wave of clones is (ADR-0099 §1).
    if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
        slot_dir="$XDG_RUNTIME_DIR"
    else
        slot_dir="/tmp/ai-assistant-$(id -u)"
        mkdir -p -m 0700 "$slot_dir"
    fi
    if [ -L "$slot_dir" ] || [ ! -d "$slot_dir" ] || [ ! -O "$slot_dir" ] || \
       [ "$(stat -c %a "$slot_dir")" != 700 ]; then
        echo "just test-fast: $slot_dir is not a private directory of ours; refusing to lock there" >&2; exit 2
    fi
    gate=""
    while :; do
        for ((i = 0; i < slots; i++)); do
            slot="$slot_dir/ai-assistant-test-fast.slot$i"
            # A regular file or nothing: not a symlink (dangling included -- `-L`
            # is asked first, since `-e` is false for one), not a FIFO that would
            # block the open, not anything else that could be waiting at that name.
            if [ -L "$slot" ] || { [ -e "$slot" ] && [ ! -f "$slot" ]; }; then
                echo "just test-fast: $slot is not a regular file; refusing to use it as a lock" >&2; exit 2
            fi
            exec {fd}>>"$slot"
            if flock -n "$fd"; then gate="$fd"; break; fi
            exec {fd}>&-
        done
        [ -n "$gate" ] && break
        [ -n "${waited:-}" ] || echo "just test-fast: all $slots slots on this machine are taken by other runs; waiting for one..." >&2
        waited=1
        sleep 2
    done
    tmp="$(mktemp -d /tmp/pt-XXXXXX)"
    # Take this tree's lease and hold it on an open descriptor for the rest of the
    # recipe, so another clone's reaper cannot take this run's tree out from under
    # it however long a test blocks. It is released by the kernel when this shell
    # exits, killed or not.
    #
    # BESIDE the tree, never inside it: pytest deletes and recreates a `--basetemp`
    # it is given, so a lease file in there would be unlinked on the way in. The
    # lock would survive on the descriptor and the reaper would then find a fresh
    # file at that path and take it, which is the whole failure this prevents.
    exec {lease}>"$tmp.lease"
    flock -n "$lease"
    # Say whose lease this is, now that it is held -- and after the `exec`, which
    # truncates. The reaper above reads this line and reaps nothing without it, so
    # a tree of this shape made by anything else survives; without the line, that
    # check would have only presence to go on, which any file answers.
    printf '%s\n' "$lease_token" >&"$lease"
    # `--basetemp` goes *after* "$@" so a forwarded one cannot displace it: pytest
    # takes the last occurrence, and a run that emptied some other directory while
    # the cleanup below removed this one would be the hazard this recipe exists to
    # avoid, silently. `-n auto` leads instead, so `just test-fast -n 4` still works.
    if uv run pytest -n auto "$@" --basetemp="$tmp"; then
        rm -rf "$tmp" "$tmp.lease"
    else
        status=$?
        # The lease file stays with the tree it describes, so that the reaper can
        # find it later and take both. It is unlocked the moment this shell exits.
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

# For a lane that owes BOTH lenses — a contract-surface change, or the ADR
# deciding that surface (`CONTRIBUTING.md` → "Stop when the required reviews are
# green" owns which set a change requires). One round is both lenses on one
# committed tree, so a finding one lens raises and the other would reject is
# visible before anyone edits for it; running adversarial to terminal and
# architecture only at the end is what bought and refunded three rounds on
# PR #1377 (issue #1387).
#
# Composes the driver twice rather than teaching it a third persona name:
# `scripts/codex-review.sh` is an ADR-0027 §3 floor path, so editing it re-opens
# every review on every branch, and it needs to know nothing about this.
#
# Sequential in one command, which is what puts both artifacts on one `tree=`:
# the round figure counts distinct reviewed *trees*, not runs, so a second
# persona on one tree does not advance it (ADR-0138 §2) and the pair is one
# round. Adversarial first because it is the lens `ship` requires
# unconditionally — if the second run dies on quota or a Codex error, the
# required artifact already exists and the round is not lost.
#
# "One tree" is CHECKED here, not assumed. Each driver invocation resolves HEAD
# for itself (`codex-review.sh:78`) and refuses if HEAD moves *during* its own
# run (`:1182`), so the only unguarded window is the seam between the two — and
# a pair split across it would record two trees while claiming one round. This
# extends the driver's own settled-tree check across that seam, and refuses
# before the second lens is spent rather than leaving `ship` to reject a stale
# adversarial artifact after both runs have paid quota.
#
# Triage the two verdicts as one queue, before editing. `docs/review/guide.md`
# → "When a change owes both lenses" carries what to do when they contradict.
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# Both Codex lenses, one round on one tree — for a lane that owes both
review-codex-both base="":
    #!/usr/bin/env bash
    set -euo pipefail
    pinned="$(git rev-parse HEAD)"
    scripts/codex-review.sh adversarial "$1"
    moved="$(git rev-parse HEAD)"
    if [ "$moved" != "$pinned" ]; then
        echo "just review-codex-both: HEAD was ${pinned}, now ${moved} — it moved" \
             "between the two lenses, so the pair would record two trees and would" \
             "not be one round. Architecture NOT run; re-run on a settled tree." >&2
        exit 1
    fi
    scripts/codex-review.sh architecture "$1"

# --- The same round, started and then polled (issue #1594) -------------------
#
# For a caller that cannot hold one process open for the minutes a round takes.
# A dispatched agent's foreground tool call is capped well below a round, and for
# a subagent *ending the turn is ending the agent* — so a backgrounded round
# finishes with nobody left to wake, the artifact lands on disk, and the lane sits
# believing it is waiting for a notification that can never arrive. Twice
# observed; the procedural fix ("run it in the foreground, poll `.review/` by
# tree if you are cut off") is what failed both times.
#
# `-start` returns once the round has claimed its loop and published the tree it
# pinned. `-wait` blocks up to `timeout` seconds and then reports, with three
# exit statuses of which exactly ONE means "ask again":
#
#   0  the artifact is recorded — its path and verdict are on stdout
#   3  `still running` — call `-wait` again; nothing is wrong and nothing is lost
#   4  no round is in flight for HEAD's tree — start one, or read why it stopped
#
# Never relaunch on a 3: the round is alive, and a second one is refused anyway.
# Never poll a 4: nothing is coming.
#
# The driver does the work in both, so `just review-codex` is untouched and
# nothing here can drift from what a round actually is: `-start` re-executes the
# driver's own foreground form, detached.
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# Launch a Codex review round detached; returns at once (poll it with -wait)
review-codex-start persona base="":
    scripts/codex-review.sh --start "$1" "$2"

# `timeout` before `base` because the timeout is the argument anyone passes: the
# base is resolved by the driver, and is only ever spelled out here to match a
# `-start` that spelled it out.
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# Block up to `timeout`s on the round for HEAD's tree, then report it (3=running)
review-codex-wait persona timeout="540" base="":
    scripts/codex-review.sh --wait "$1" "$3" --timeout "$2"

# The start/wait form of `review-codex-both`, for a both-lens lane that has to
# poll. The two lenses run as two detached rounds, which is a shape the driver is
# built for rather than one this recipe invents: its own `#142` block names
# "`adversarial` and `architecture` started at once on a fresh loop" as the case
# the loop lock exists for, that lock is released across the Codex call itself,
# the in-flight locks are per-persona, and the artifact, the thread and the
# disposition snapshot are per-persona paths.
#
# #1425's one-tree guard is not weakened, it is CHECKED LATER AND HARDER. There,
# HEAD is pinned across the seam between two sequential runs. Here, `-wait`
# returns an artifact only when its recorded `tree=` is HEAD's tree — so
# `-both-wait` exiting 0 for both personas *is* the proof that both artifacts
# carry one tree, established before the author triages rather than at a seam.
# Each driver invocation still refuses to record if HEAD moves during it, and
# HEAD is pinned across the seam between the two starts here as well.
#
# Adversarial is started first for the reason `review-codex-both` runs it first:
# it is the lens `ship` requires unconditionally, so if the second start fails
# the required round is already running rather than not yet begun.
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# Launch both Codex lenses detached, one round on one tree (poll with -both-wait)
review-codex-both-start base="":
    #!/usr/bin/env bash
    set -euo pipefail
    pinned="$(git rev-parse HEAD)"
    scripts/codex-review.sh --start adversarial "$1"
    moved="$(git rev-parse HEAD)"
    if [ "$moved" != "$pinned" ]; then
        echo "just review-codex-both-start: HEAD was ${pinned}, now ${moved} — it" \
             "moved between the two starts, so the pair would review two trees and" \
             "would not be one round. Architecture NOT started; the adversarial" \
             "round is already running on ${pinned}." >&2
        exit 1
    fi
    scripts/codex-review.sh --start architecture "$1"

# One deadline across both waits, not one each, so `timeout` means what it says.
# Both are attempted whatever the first returns: a lane told only "adversarial is
# still running" learns nothing about the lens it is also owed, and the second
# wait costs nothing once the shared deadline has passed.
#
# The status reported is the one that DEMANDS THE MOST, ranked by what the caller
# must do about it and not by the numeric order or by arrival — "the last non-zero
# wins" would report a 3 for a pair whose adversarial lens exited 4, telling a
# lane to keep polling a lens that is not running. The ranking is:
#
#   0  both recorded, nothing to do
#   3  neither has failed, one is not finished — ask again
#   4  one has no round in flight — start it, or read why it stopped
#   *  the call itself was wrong (usage, or a malformed poll interval)
#
# Last line, because `just --list` shows only that one: what this recipe runs.
# Block up to `timeout`s on BOTH lenses' rounds for HEAD's tree, then report them
review-codex-both-wait timeout="540" base="":
    #!/usr/bin/env bash
    set -euo pipefail
    rank() {
        case "$1" in
        0) echo 0 ;;
        3) echo 1 ;;
        4) echo 2 ;;
        *) echo 3 ;;
        esac
    }
    deadline=$(( $(date +%s) + $1 ))
    status=0
    for persona in adversarial architecture; do
        remaining=$(( deadline - $(date +%s) ))
        [ "$remaining" -lt 0 ] && remaining=0
        this=0
        scripts/codex-review.sh --wait "$persona" "$2" --timeout "$remaining" ||
            this=$?
        if [ "$(rank "$this")" -gt "$(rank "$status")" ]; then
            status="$this"
        fi
    done
    exit "$status"

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

# `.review/` accumulates for the life of a clone, and two mechanisms read it by
# glob: `ship` selects the artifact covering the PR head's content, and
# `codex-review` derives ADR-0138's round number and churn ratio from the
# distinct reviewed trees recorded **for this branch name**. Branch slugs repeat
# across batches, so a merged lane's leftovers inflate the next lane's round
# count — which is the reason this sweeps by refs rather than by age, and the
# reason it never touches an artifact a live branch could still use.
#
# Merged or orphaned artifacts move to `.review/archive/` by default; `--delete`
# removes them. Neither contradicts an ADR: ADR-0015 §1, ADR-0020 §3 and
# ADR-0027 §2 all treat an artifact as evidence for the local `ship` step, and the
# durable record of a review is the comment `ship` posts to the PR. Archive is
# still the default, because a local move is recoverable and a misclassification
# then costs nothing. `.review/*.md` is not recursive, so an archived artifact is
# as invisible to both mechanisms as a deleted one.
#
# Run it after releasing a clone (the dispatch skill's §5 deletes the merged
# branch), not before: while the branch still exists its artifacts are correctly
# read as live and nothing is swept. `--dry-run` prints the classification and
# changes nothing.
#
# Last line, because `just --list` shows only that one: what this recipe retires.
# Retire the .review/ artifacts no live branch can still use (issue #1391)
review-sweep *args:
    uv run python scripts/review_sweep.py "$@"


# The hub redeploy, with the two details that cost two failed attempts on
# 2026-08-22 encoded rather than remembered (issue #1389): the service venv is
# uv-managed and has no `pip`, and `sudo -u` leaks root's HOME so uv reads
# /root/uv.toml — hence `su - <user> -c` and a login shell throughout.
#
# It refuses a `--no-deps` install when `uv.lock` moved since the commit the box
# records in its marker file, because that is the install this recipe otherwise
# does and it would leave the venv on the old dependency set. An absent marker is
# UNKNOWN rather than clean: it warns and proceeds, since refusing would make the
# first deploy to a fresh box impossible.
#
# Nothing is hard-coded to one box — host, service user, unit, venv, uv path,
# wheel name and marker are all arguments, and the defaults describe the box that
# exists rather than a requirement. `--dry-run` prints every command and contacts
# nothing; the remote half is exercised by hand, so that rendering is what the
# tests cover.
#
# Last line, because `just --list` shows only that one: what this recipe does.
# Build, install, restart and verify the hub on a box (issue #1389)
deploy-hub host *args:
    uv run python scripts/deploy_hub.py "$@"

# One agent per clone (ADR-0015 §2), and each clone carries untracked local state
# no merge ever moves between them. This mirrors the documented list —
# `scripts/clone_sync_files.txt`, which is data and carries its own note that
# nothing in it is committed — from the clone it runs in into the siblings.
# Run it in the primary clone as part of dispatch preflight (issue #1390).
#
# It applies the dispatch skill's freshness test: a clone not on `main` and clean
# is skipped, with the synced files themselves excluded from the cleanliness
# check since they are exactly what is expected to differ. A clone named
# explicitly fails the run when it is not free; one merely found by the default
# scan is reported and skipped, because a busy clone is the ordinary state of a
# batch. A path git *tracks* in the target is never overwritten — that is an
# error, not a skip.
#
# Last line, because `just --list` shows only that one: what this recipe copies.
# Mirror the documented untracked per-clone files into siblings (issue #1390)
clone-sync *args:
    uv run python scripts/clone_sync.py "$@"

# First-time developer setup
setup:
    uv sync
    uv run pre-commit install --install-hooks
    git config commit.template .gitmessage
