#!/usr/bin/env bash
# Run an adversarial review with Codex — a different model, for a perspective
# independent of the one that wrote the code.
#
# Uses the same rubric as documented in docs/review/, feeding it plus the branch
# diff to `codex exec`, read-only. `codex exec review --base` cannot take custom
# instructions on stdin, so we drive `codex exec` directly with an explicit diff.
#
# NOTE: this sends the diff and repository context to OpenAI. It is a deliberate
# pre-merge step, not something to run on every change.
#
# Usage: scripts/codex-review.sh <architecture|adversarial> [base-ref]
#   base-ref defaults to origin/main when known (else local main); the
#   review covers HEAD's *committed* changes vs base-ref — commit a fix (even
#   a small follow-up you'll squash later) before re-running, or the diff
#   Codex sees will not reflect it.
set -euo pipefail

persona="${1:-}"
base="${2:-}"

if [[ -z "$persona" ]]; then
    echo "usage: scripts/codex-review.sh <architecture|adversarial> [base-ref]" >&2
    exit 2
fi

if [[ -z "$base" ]]; then
    # Prefer origin/main, same as claim-workspace.sh's own base resolution
    # (see its header) — the local `main` branch ref is not kept current by
    # anything in this workflow (worktrees branch from origin/main, never
    # touching local main at all) and can sit stale indefinitely, silently
    # reviewing a different diff than CI's merge-relative one. This script
    # still does no network itself; run `git fetch origin` first for a fresh
    # origin/main, same as before claiming a workspace.
    base=main
    if git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null 2>&1; then
        base=origin/main
    fi
fi

repo_root="$(git rev-parse --show-toplevel)"
rubric="${repo_root}/docs/review/${persona}.md"

if [[ ! -f "$rubric" ]]; then
    echo "unknown persona '${persona}': no ${rubric}" >&2
    exit 2
fi

if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found on PATH; install it to run reviews" >&2
    exit 127
fi

# Codex reads files from the working tree for context, not just the diff we hand
# it. Reviewing with uncommitted changes present therefore reasons about a tree
# that is not the commit the artifact will name — and once those changes are
# stashed, ship.sh still accepts it. Same rule as ship: clean tree or nothing.
#
# `status --porcelain` does not report *ignored* files, and deliberately so.
# Codex can read an ignored file, so in principle one could influence a review
# and then vanish. Closing that would mean refusing to run whenever any ignored
# file exists — which is always: .venv/, .env, and every tool cache are ignored
# by design. There is no reliable way to tell "an ignored fixture that swayed
# the review" from "the virtualenv", so the check would either never pass or
# depend on a hand-maintained exemption list that silently rots. Waived
# deliberately; the tracked+untracked check is what is enforceable here.
if [[ -n "$(git status --porcelain)" ]]; then
    echo "working tree is dirty (tracked or untracked); commit or stash first" >&2
    echo "the review would reason about files that are not in the reviewed commit" >&2
    exit 1
fi

# Resolve HEAD to an immutable SHA *before* diffing, and review that SHA rather
# than the moving ref. A review can run for minutes; if HEAD advances meanwhile,
# re-resolving afterwards would file this diff under a commit Codex never saw,
# and ship.sh would accept it as evidence for that commit. Pinning here means
# the artifact always names exactly the code that was reviewed.
sha="$(git rev-parse HEAD)"

# Pin the *base* for the same reason, and at the same time. `base` is a ref
# ("origin/main"), and a concurrent fetch can move it mid-review: the diff would
# be computed from the old merge base while the recorded one is re-resolved
# afterwards to the new commit — an artifact certifying a range Codex never saw,
# which ship.sh would then accept. Both edges of the reviewed range are immutable
# from here on.
base_sha="$(git merge-base "$base" "$sha")"

# The tree is the anchor ship.sh checks (ADR-0020 §3): it identifies the content
# reviewed, where the SHA identifies only the commit that happened to carry it.
# Pinned here with the other two edges, and for the same reason — everything the
# artifact certifies is resolved before the review starts, never after it.
tree="$(git rev-parse "${sha}^{tree}")"

# The branch is what scopes the round count below to *this* review loop, and it
# is recorded in the artifact for that reason. Unlike the SHA or the base, it
# survives a squash, an amend and a rebase — which is exactly the property the
# count needs (issue #97).
branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
    # Detached: "HEAD" is a placeholder, not an identity, so using it as the
    # scope key would make every detached checkout share one review loop and
    # contaminate the others' counts. Key on the commit instead — each detached
    # review is then its own loop, starting at round 1. Nothing is lost: such a
    # review cannot be shipped at all, since ship refuses a detached HEAD.
    branch="detached-${sha}"
fi

# One limit is left standing, deliberately, and it cuts both ways. The name is
# all that identifies the loop, so reusing a name inherits the old branch's
# rounds and over-counts, while *renaming* a branch mid-loop orphans every
# artifact filed under the old name and resets the count to 1.
#
# The second direction is the worse of the two and is worth stating plainly: this
# number exists to make a runaway loop legible, so under-counting hides the very
# thing it is for, where over-counting only says "look at your loop" too loudly.
# What keeps it acceptable is not the direction but the occasion — an open PR is
# bound to its branch name, so a rename mid-review breaks the PR before it can
# skew the count, and neither case arises from the rewrites this is built to
# survive, since squash, amend and rebase all preserve the name.
#
# Fixing it needs a durable per-loop identifier — a ledger in `.review/`, which
# is state to maintain and to keep consistent across those same rewrites. That
# is a real design with failure modes of its own, and #97 lists it as a candidate
# without mandating it. Not worth building for an advisory number until one of
# these cases is actually observed.

# --- The reviewed range's rendering, and its identity (ADR-0027 §2) ----------
#
# THIS BLOCK IS DUPLICATED VERBATIM IN scripts/ship.sh AND MUST STAY IDENTICAL.
# One script records the identity and the other recomputes it to decide whether a
# review still covers HEAD across a moved base, so a divergence between the two
# spellings would not fail loudly — it would compute two different identities for
# one patch and quietly cost a review round every time. Same reasoning as
# `artifact_has_verdict`, which is duplicated across the pair for the same
# reason.
#
# The diff options are PINNED rather than inherited from the repository or user
# config. Every one of them changes the rendered patch text and therefore the
# identity, so leaving them to config would make the identity a function of when
# and where it was computed rather than of the two commits. `core.quotePath=false`
# is also what the reviewer's own diff uses, so a non-ASCII path reaches it as
# `docs/café.md` rather than `"docs/caf\303\251.md"` — an escaped path is a file
# it cannot find in the tree.
# >>> shared-patch-identity (ADR-0027 §2) — kept byte-identical in both scripts
_diff_opts=(
    -c core.quotePath=false
    -c diff.renames=true
    -c diff.algorithm=myers
    -c diff.context=3
    -c diff.indentHeuristic=true
    -c diff.noprefix=false
    -c diff.mnemonicPrefix=false
)

# Whether the range carries an entry with NEITHER a hunk NOR an `index` line, so
# its contribution to the identity is a function of its PATHS ALONE (ADR-0027 §2).
# That is exactly the set of entries whose pre- and post-image blobs are the same
# object: a 100%-similarity rename or copy, and a mode-only change. git emits
# `similarity index 100% / rename from / rename to` or `old mode / new mode` for
# those and no `index` line at all, so a reviewed rename of `f` to `g`, rebased
# onto a base that changed `f`'s contents, presents a byte-identical identity
# while `g` now holds content no reviewer saw.
#
# Read from `--raw -z` rather than by scanning the rendered patch text: the blob
# pair is the structural fact, where a text scan would have to guess at entry
# boundaries in a format where a pathname may itself contain a newline.
# A LISTING THAT COULD NOT BE READ IS REPORTED AS PATHLESS. The producer's exit
# status has to be captured rather than read through a process substitution,
# which discards it: `git diff` can fail *after* emitting a prefix — an
# unreadable blob in a partial clone, a broken pipe — and a truncated listing
# read as a complete one would say "no pathless entry" about a range it never
# finished describing. So it is written to a file whose write is checked, and any
# failure answers the fail-closed way rather than the convenient way.
_range_has_pathless_entry() {
    local -a rec=()
    local raw
    raw="$(mktemp -t patch-raw.XXXXXX)" || return 0
    if ! git "${_diff_opts[@]}" diff --no-ext-diff --no-textconv --raw --abbrev=40 -z \
        "$1...$2" >"$raw"; then
        rm -f "$raw"
        return 0
    fi
    mapfile -d '' -t rec <"$raw"
    rm -f "$raw"
    local i=0 meta old new status
    while [[ $i -lt ${#rec[@]} ]]; do
        meta="${rec[$i]}"
        # ":<oldmode> <newmode> <oldsha> <newsha> <status>"
        read -r _ _ old new status <<<"${meta#:}"
        case "$status" in
        R* | C*) i=$((i + 3)) ;;
        *) i=$((i + 2)) ;;
        esac
        # A record that runs off the end is a format this cannot parse, so it is
        # reported as pathless: unparsed is not the same as safe.
        if [[ $i -gt ${#rec[@]} || "$old" == "$new" ]]; then
            return 0
        fi
    done
    return 1
}

# The identity of the patch `git diff <$1>...<$2>` renders (ADR-0027 §2). Echoes
# the identity, or NOTHING when the range has no identity that may be trusted.
#
# The mechanism is `git patch-id --verbatim`, and specifically NOT `--stable`.
# Both ignore hunk line numbers — the first property, so a base move elsewhere in
# a touched file merely renumbers the hunk headers and must not invalidate — but
# `--stable` also STRIPS WHITESPACE, which fails the second property outright: a
# base move that re-indents a context line inside a reviewed hunk is semantic in
# Python, and under `--stable` the identity would not move, so a review of
# content that is no longer there would be reused. `--verbatim` calculates the id
# of the input as given and implies `--stable`, so it satisfies both. The two
# spellings differ by one flag and only one of them is safe; ADR-0027 §2 fixes
# the choice here rather than leaving it to the implementation.
#
# Empty output is the fail-closed answer, never a value to compare: an empty
# range, an entry anchored on its paths alone, or a `patch-id` that produced
# nothing all make the moved-base acceptance path UNAVAILABLE rather than
# satisfied. Two such artifacts must never compare equal to each other.
patch_identity() {
    if _range_has_pathless_entry "$1" "$2"; then
        return 0
    fi
    git "${_diff_opts[@]}" diff --no-ext-diff --no-textconv "$1...$2" |
        git patch-id --verbatim | awk 'NR == 1 { print $1 }' || return 0
}
# <<< shared-patch-identity

diff="$(git "${_diff_opts[@]}" diff --no-ext-diff --no-textconv "${base_sha}...${sha}")"
if [[ -z "$diff" ]]; then
    echo "no changes between ${base_sha} and ${sha} to review" >&2
    exit 0
fi

# The identity of the patch this review reads, pinned here with the other three
# edges and for the same reason: everything the artifact certifies is resolved
# before the review starts, never after it. `ship` recomputes it against the
# PR's current merge base, and where the base has MOVED it is what says whether
# the reviewer read this content (ADR-0027 §2). Recorded empty when the range has
# no trustworthy identity, which is what makes the moved-base path unavailable
# rather than accepted.
patch_id="$(patch_identity "$base_sha" "$sha")"

review_dir="${repo_root}/.review"

# --- Aggregate (ADR-0020 §2) -------------------------------------------------
#
# Printed on every run, unasked, and recorded in the provenance line so `just
# ship` carries it to the PR. The failure mode this addresses is illegibility,
# not excess: every round of a runaway loop is locally defensible, and neither
# runaway case in issue #91 terminated on its own — both were stopped from
# outside by someone holding an aggregate view. So this blocks nothing and gates
# nothing. It is a number, deliberately: a round cap would have forbidden the
# round of #90 that found `gh pr merge --match-head-commit`.
#
# Everything below is `git log --numstat` arithmetic — no model, no judgment.

# Round: how many *distinct reviewed states* of this branch already exist, plus
# this one. A round is a review of a content state, so that is what is counted —
# the trees recorded in `.review/`, not the commits those artifacts are filed
# under (issue #97).
#
# Counting lineage commits was the obvious reading of §2, and it does not
# survive the very operations §3 exists to make cheap. A squash, an amend or a
# rebase in place removes the previously reviewed SHAs from `base..HEAD`, so the
# count resets toward 1 — precisely on the branch that has been through enough
# rounds to be worth squashing. The mechanism that encourages the rewrite was
# erasing the aggregate the rewrite is evidence for.
#
# Keying on the recorded tree fixes that for free, because `.review/` is
# git-ignored: rewriting history does not touch the artifacts, and a tree is
# stable across every rewrite that preserves content. The same property makes
# the count behave as before where it was already right — a second persona on
# one commit, or a re-run of one persona, reviews the same tree as HEAD and so
# is excluded rather than inflating the round.
#
# Scoped by *branch name*, which `.review/` records for this purpose. The scope
# key has to identify "this review loop", and the branch is the only thing that
# does: `.review/` is a per-clone directory that accumulates across every branch
# worked in it, so an unscoped count would report a previous PR's rounds as this
# one's. The base commit is not a usable key either — two branches cut from the
# same `origin/main` share it exactly, so scoping on it would let a finished
# branch's rounds leak into a fresh one — while the branch name is stable across
# precisely the rewrites this is trying to survive, rebase onto a moved base
# included.
#
# An artifact written before the field existed is skipped rather than guessed
# at, so the count resets once across that upgrade and is right afterwards.
declare -A reviewed_trees=()
shopt -s nullglob
for artifact_file in "${review_dir}"/*.md; do
    artifact_line="$(head -n 1 "$artifact_file")"
    artifact_branch="$(sed -n 's/.*[[:space:]]branch=\([^[:space:]]*\).*/\1/p' <<<"$artifact_line")"
    artifact_tree="$(sed -n 's/.*[[:space:]]tree=\([^[:space:]]*\).*/\1/p' <<<"$artifact_line")"
    # No recorded tree or branch means the artifact predates this and says
    # nothing usable. HEAD's own tree is this round, not a previous one — which
    # is what keeps a second persona, or a re-run, from inflating the count.
    if [[ -z "$artifact_branch" || -z "$artifact_tree" ]]; then
        continue
    fi
    if [[ "$artifact_branch" != "$branch" || "$artifact_tree" == "$tree" ]]; then
        continue
    fi
    reviewed_trees["$artifact_tree"]=1
done
shopt -u nullglob
round=$((${#reviewed_trees[@]} + 1))

# How many of those earlier reviewed states are still reachable on this branch.
# One that is not means history was rewritten, which is what makes the churn
# figure below a lower bound: the commits carrying that rework are gone from
# `base..HEAD`, so `git log --numstat` cannot see the lines they touched.
declare -A lineage_trees=()
while read -r commit; do
    if [[ -n "$commit" ]]; then
        lineage_trees["$(git rev-parse "${commit}^{tree}")"]=1
    fi
done < <(git rev-list "${base_sha}..${sha}")

orphaned_rounds=0
for reviewed_tree in "${!reviewed_trees[@]}"; do
    if [[ -z "${lineage_trees[$reviewed_tree]:-}" ]]; then
        orphaned_rounds=$((orphaned_rounds + 1))
    fi
done

# Sum added+deleted across a --numstat stream, and count the entries that report
# `-` in both columns. Those are binary: git measures no lines for them at all.
# Skipping them in the sum is right — coercing `-` to 0 would imply a
# measurement that was never taken — but skipping them *silently* is what issue
# #100 is about, since a commit that replaces a binary asset then reports
# `net_lines=0` and `churn_ratio=n/a`, indistinguishable from a rename- or
# mode-only change that really did touch nothing. Counted here so the output can
# say "unmeasured" instead of implying "unchanged".
#
# Emits both numbers on one line so the stream is consumed once.
_numstat() {
    awk '{ if ($1 ~ /^[0-9]+$/) a += $1
           if ($2 ~ /^[0-9]+$/) d += $2
           if ($1 == "-" && $2 == "-") b++ }
         END { print a + d + 0, b + 0 }'
}

read -r net_lines net_binary < <(git diff --numstat "${base_sha}...${sha}" | _numstat)
read -r churn_lines churn_binary < <(
    git log --numstat --format= "${base_sha}..${sha}" | _numstat
)
commits="$(git rev-list --count "${base_sha}..${sha}")"

# Churn ratio: cumulative lines touched across the branch's commits divided by
# net lines in the final diff. Far above 1 means most of the work has been
# rework — the mechanical proxy for "consecutive commits fixing what the
# previous commit introduced". A diff of pure renames or mode changes touches no
# lines, so guard the division rather than reporting a ratio of nothing.
churn_ratio="n/a"
if [[ "$net_lines" -gt 0 ]]; then
    churn_ratio="$(awk -v c="$churn_lines" -v n="$net_lines" 'BEGIN { printf "%.1f", c / n }')"
fi

# Churn is defined over the branch's commits (ADR-0020 §2), and a rewrite takes
# commits away, so after a squash the figure counts only the work done since —
# understating the rework exactly where it matters most. That definition is not
# quietly redefined here: recovering the true figure would mean reconstructing
# work from trees that may already have been garbage-collected, and inventing a
# number is worse than reporting a smaller one honestly.
#
# So the limitation is labelled instead of defeated. Where an earlier reviewed
# state is no longer on the branch, the ratio is marked a lower bound and the
# missing rounds are named, which is what the aggregate is for: the number
# exists to be legible, and a figure silently understating rework on a
# much-reworked branch is the opposite of legible.
churn_bound="exact"
if [[ "$orphaned_rounds" -gt 0 ]]; then
    churn_bound="lower"
fi

# Where the change supersedes or amends another document, that document's size
# belongs next to this one's: ADR-0017 superseded one clause of a 175-line ADR
# and peaked at 821 lines, and it was that comparison — one number next to
# another — that made two hours of drift legible. Read off the *added* lines
# only, so an unchanged historical mention does not register.
#
# Matched case-sensitively, and that is a decision rather than an oversight
# (issue #100). `Supersedes:` and `Amends:` are ADR *fields*, and every
# occurrence in docs/adr/ is capitalised as one. Matching lowercase too would
# pick up ordinary prose — "this amends ADR-0004", "which supersedes ADR-0012" —
# in body text and running commentary, which names a document the change does
# not actually supersede. The field convention is the signal; the word is not.
supersedes=""
supersedes_pretty=""
mapfile -t superseded_refs < <(
    printf '%s\n' "$diff" | grep -E '^\+' | grep -E 'Supersedes|Amends' |
        grep -oE 'ADR-[0-9]{4}' | sort -u
)
if [[ ${#superseded_refs[@]} -gt 0 ]]; then
    for ref in "${superseded_refs[@]}"; do
        for target in "${repo_root}/docs/adr/${ref#ADR-}-"*.md; do
            [[ -f "$target" ]] || continue
            target_lines="$(wc -l <"$target" | tr -d '[:space:]')"
            supersedes="${supersedes:+${supersedes},}${ref}:${target_lines}"
            supersedes_pretty="${supersedes_pretty:+${supersedes_pretty}, }${ref} (${target_lines} lines)"
        done
    done
fi

{
    echo
    echo "===== aggregate (ADR-0020 §2) ====="
    echo "  round        ${round} — distinct reviewed states of this branch, plus this one"
    net_desc="${net_lines} lines across ${commits} commit(s)"
    if [[ "$net_binary" -gt 0 ]]; then
        net_desc="${net_desc}, plus ${net_binary} binary file(s), unmeasured"
    fi
    echo "  net diff     ${net_desc}"
    churn_desc="${churn_ratio} — ${churn_lines} lines touched ÷ ${net_lines} net"
    if [[ "$churn_binary" -gt 0 ]]; then
        churn_desc="${churn_desc}, plus ${churn_binary} binary change(s), unmeasured"
    fi
    echo "  churn ratio  ${churn_desc}"
    if [[ "$churn_bound" == "lower" ]]; then
        echo "               ^ a LOWER BOUND: ${orphaned_rounds} earlier reviewed state(s) are no"
        echo "                 longer on this branch's history (squash, amend or rebase), so the"
        echo "                 rework before that rewrite is not counted. The round count above"
        echo "                 does include them."
    fi
    if [[ -n "$supersedes_pretty" ]]; then
        echo "  supersedes   ${supersedes_pretty}"
    fi
    echo "  (advisory — nothing here blocks. A high round count or a churn ratio"
    echo "   far above 1 is the signal that the loop is reworking itself.)"
    echo
} >&2

prompt="$(mktemp -t "codex-prompt-${persona}.XXXXXX.md")"
out="$(mktemp -t "codex-review-${persona}.XXXXXX.md")"
# The `--json` event stream from a persistent round is captured here to read the
# `thread_id` back; `$inject_tmp` holds re-injected prior dispositions on a
# degraded round. Both are cleaned on every exit path alongside `$out`.
stream="$(mktemp -t "codex-stream-${persona}.XXXXXX.json")"
inject_tmp="$(mktemp -t "codex-inject-${persona}.XXXXXX.md")"
# Every temporary, on every exit path. `$out` holds the full review text and
# `$artifact_tmp` a half-written copy of it, so leaving either behind accumulates
# review content in /tmp and in .review/ — the latter invisible to the dirty-tree
# check, since .review/ is ignored. ${var:+...} expands to nothing while
# artifact_tmp is still unset, which it is for most of this script.
trap 'rm -f "$prompt" "$out" "$stream" "$inject_tmp" ${artifact_tmp:+"$artifact_tmp"}' EXIT

# --- Persistent session identity and read-only proof (ADR-0025 §1) -----------
#
# A review loop keeps ONE Codex conversation, resumed each round via `codex exec
# resume`, so the reviewer carries what it already said and what the author
# already answered (#125's memoryless re-raise is gone at the root). The session,
# its fallback transcript, and the recorded dispositions are bound to a durable
# per-loop identity, not the bare branch name — a reused or renamed branch must
# not inherit another loop's session or findings (#97, now load-bearing).
#
# The identity key is `sha1(branch)-sha1(base_sha)`. It is stable across exactly
# the rewrites the workflow relies on — an amend, a squash, or an in-place rebase
# all keep both the branch name and the base — so those resume the same warm
# session. It CHANGES on the two events that must invalidate a session: a rebase
# onto a moved base (the re-validation ADR-0025 §1 requires — a moved base is a
# different diff, so a fresh key selects a fresh session and the old base's
# session simply lingers unreferenced) and a branch cut from a newer base reusing
# a name (a fresh key, so no stale thread is resumed). The residual — a reused
# name that happens to share a base — is bounded to soft memory carry-over, never
# a wrong ship anchor: the shippable artifact is still tree-anchored (§4), and
# ship matches on `(base, tree)` regardless of which thread produced the verdict.
# The bypass is CI-only and not the persistent path (see the invocation below):
# a cold one-shot that keeps no session and runs no read-only proof, today's
# behaviour preserved. Detected here so no session state is created on that path.
# GITHUB_ACTIONS is matched exactly against "true", so an inherited
# GITHUB_ACTIONS=false cannot enable it; CODEX_REVIEW_NO_SANDBOX=1 forces it.
bypass=0
if [[ "${CODEX_REVIEW_NO_SANDBOX:-}" == "1" || "${GITHUB_ACTIONS:-}" == "true" ]]; then
    bypass=1
fi

codex_home="${CODEX_HOME:-$HOME/.codex}"
session_dir="${review_dir}/session"
disposition_dir="${review_dir}/dispositions"
branch_key="$(printf '%s' "$branch" | sha1sum | awk '{print $1}')"
base_key="$(printf '%s' "$base_sha" | sha1sum | awk '{print $1}')"
loop_key="${branch_key}-${base_key}"
meta_file="${session_dir}/${loop_key}.meta"
thread_file="${session_dir}/${loop_key}.${persona}.thread"
lock_file="${session_dir}/${loop_key}.lock"
# The disposition record is a per-reviewed-state SNAPSHOT (ADR-0025 §4), named by
# the full anchor `<loop_id>-<persona>-<tree>.md`, so `ship` selects the one
# belonging to the terminal artifact's tree and fails closed if two loops claim
# the same (persona, tree). `snapshot_file` and `prior_snapshot` are resolved
# once loop_id is known, below.

# A durable, opaque per-loop id, minted once and recorded in the artifact so the
# ship-time snapshot can be selected by the full anchor (loop, persona, base,
# tree) rather than the tree alone (ADR-0025 §4). Written atomically.
_mint_id() {
    if [[ -r /proc/sys/kernel/random/uuid ]]; then
        cat /proc/sys/kernel/random/uuid
    else
        od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
    fi
}

# --- Serializing the loop's read-modify-write (issue #142) -------------------
#
# Deciding the loop identity is a READ (the meta) then a WRITE (a minted id, a
# thread wipe), and advancing the loop at the end of a round is another. Each
# individual `mv` is atomic, but two concurrent invocations — `adversarial` and
# `architecture` started at once on a fresh loop — could interleave *between*
# read and write: both see no meta, both mint a different loop_id, and a later
# run then pairs one run's loop_id with the other run's thread, mixing
# differently-anchored records into one disposition ledger. So each phase runs
# inside an exclusive lock on `<loop_key>.lock`, making it one read-modify-write.
#
# The lock is held only across the two filesystem phases, NEVER across the Codex
# call itself: a round runs for minutes, and blocking a sibling persona for the
# whole of it would trade a latent race for a guaranteed stall.
#
# `flock` is used rather than a hand-rolled `mkdir`/`O_EXCL` lockfile precisely
# because of the stale-lock failure mode: an flock lives on an open file
# descriptor, so the kernel releases it when the holder exits — cleanly, on a
# crash, or on SIGKILL. A crashed prior round therefore cannot wedge the review
# loop; the worst it leaves behind is an inert zero-byte lock file. A directory
# or PID lockfile would survive its owner and need a stale-timeout heuristic
# that either wedges or breaks mutual exclusion. `-w` bounds the wait anyway, so
# even a live-but-hung holder produces a loud failure instead of a hang.
lock_wait="${CODEX_REVIEW_LOCK_WAIT:-60}"
lock_fd=""
_lock_session() {
    if [[ -n "$lock_fd" || "$serialized" -eq 0 ]]; then
        return 0
    fi
    mkdir -p "$session_dir"
    exec {lock_fd}<>"$lock_file"
    if ! flock -w "$lock_wait" "$lock_fd"; then
        echo "timed out after ${lock_wait}s waiting for the review-loop lock" >&2
        echo "  ${lock_file}" >&2
        echo "another codex-review run is holding it; personas run sequentially in" \
            "one clone (ADR-0015)" >&2
        exit 1
    fi
    return 0
}
_unlock_session() {
    if [[ -z "$lock_fd" ]]; then
        return 0
    fi
    flock -u "$lock_fd"
    exec {lock_fd}>&-
    lock_fd=""
}

# One round per persona per loop AT A TIME, and this one is refused rather than
# queued. Serializing the loop's state is not enough on its own: two rounds of
# the SAME persona write the same artifact path, the same thread file and the
# same snapshot path, so whichever ordering they interleave in, the published
# verdict can end up paired with the other round's dispositions — the terminal
# turn ADR-0025 §4 requires them to belong to. There is nothing to merge and no
# ordering that helps, so the second invocation is refused loudly (the "detect
# and refuse a second concurrent init" half of #142). Held for the whole round,
# Codex call included, and never released explicitly: process exit closes the
# descriptor, so a crashed round leaves nothing to wedge the next one.
#
# The loop lock above is still taken and released around the short state phases,
# so a DIFFERENT persona is only ever blocked for that filesystem work, never for
# the minutes a round spends in Codex.
inflight_fd=""
_claim_persona() {
    if [[ "$serialized" -eq 0 ]]; then
        return 0
    fi
    mkdir -p "$session_dir"
    exec {inflight_fd}<>"${session_dir}/${loop_key}.${persona}.inflight"
    if ! flock -n "$inflight_fd"; then
        echo "another '${persona}' review of this loop is already running in this" >&2
        echo "clone; refusing to start a second one. Two rounds of one persona share" >&2
        echo "an artifact, a thread and a disposition snapshot, so they cannot both" >&2
        echo "be recorded. Run personas one at a time (ADR-0015, issue #142)." >&2
        exit 1
    fi
    return 0
}

# Whether the loop phases can be serialized at all. `flock` is util-linux, so it
# is present wherever `sha1sum` (already required above, for the loop key) is.
# Where it is somehow absent, the loop degrades to the unserialized behaviour it
# had before #142 and says so, rather than refusing to review: the race needs two
# concurrent invocations, which the one-agent-per-clone workflow (ADR-0015) does
# not produce, so bricking the tool would be the worse failure.
serialized=1
if ! command -v flock >/dev/null 2>&1; then
    serialized=0
    if [[ "$bypass" -eq 0 ]]; then
        echo "warning: flock not found; the review loop's init/update cannot be" >&2
        echo "  serialized. Run one codex-review at a time (issue #142)." >&2
    fi
fi

# The loop meta, written atomically. `last_sha` is the ancestry anchor the next
# round continues from, so it is passed explicitly: init publishes the identity
# WITHOUT advancing it, and only a fully recorded round moves it forward.
_write_meta() {
    local last="$1" tmp="${meta_file}.partial.$$"
    printf 'loop_id=%s\nbranch=%s\nbase_sha=%s\nlast_sha=%s\n' \
        "$loop_id" "$branch" "$base_sha" "$last" >"$tmp"
    mv "$tmp" "$meta_file"
}
# No session state on the bypass path — it keeps no thread to resume. loop_id
# stays empty there and is recorded empty, alongside the empty thread_id.
#
# Off the bypass path, decide continuation vs reset. The loop_key
# (sha1(branch)-sha1(base_sha)) is necessary but not sufficient: a branch name
# reused for unrelated work off the *same* base collides on it exactly. So a run
# continues the recorded loop only when the last state that loop reviewed is an
# ancestor of HEAD — i.e. HEAD builds on it. A reused name (its recorded last
# state is unrelated to the new HEAD) fails that test and resets: a fresh loop_id
# and a wipe of any thread and dispositions filed under this key, so no prior
# loop's session, findings, or proposals bleed into this verdict (ADR-0025 §1's
# explicit reset on reuse). An amend, squash, or in-place rebase also fails the
# ancestry test and resets to a fresh cold session — safe, never worse than
# today's cold loop, and such rewrites usually land at the end of a loop rather
# than between the warm rounds this is optimising.
#
# A meta carrying a loop_id but NO last_sha is a loop whose identity has been
# reserved and which has recorded no round yet — an invocation still in flight,
# or one that died before completing a round. That is ADOPTED, not reset: the
# reset exists to detect a branch name reused for unrelated work, and the
# evidence for that is the recorded last state, which such a loop does not have.
# Adopting is what makes two concurrent fresh starts agree on one identity
# (#142); there is also nothing to bleed, since no thread or disposition is
# filed until a round completes. It is not resumed either (the ancestry test
# gates that), so an adopted loop's first recorded round is a cold one.
loop_id=""
recorded_thread=""
if [[ "$bypass" -eq 0 ]]; then
    _claim_persona
    _lock_session
    recorded_last_sha=""
    if [[ -f "$meta_file" ]]; then
        loop_id="$(sed -n 's/^loop_id=//p' "$meta_file")"
        recorded_last_sha="$(sed -n 's/^last_sha=//p' "$meta_file")"
    fi
    if [[ -n "$loop_id" && -n "$recorded_last_sha" ]] &&
        git merge-base --is-ancestor "$recorded_last_sha" "$sha" 2>/dev/null; then
        # Continuing this loop: resume the persona's thread if it has one.
        if [[ -f "$thread_file" ]]; then
            recorded_thread="$(head -n 1 "$thread_file")"
        fi
    elif [[ -n "$loop_id" && -z "$recorded_last_sha" ]]; then
        # Reserved, not yet advanced: adopt the identity as described above.
        :
    else
        # New loop, or a reused/rewritten branch: reset the per-loop identity and
        # clear any session and dispositions filed under it. Threads are keyed by
        # loop_key so are cleared by that; the disposition snapshots are keyed by
        # the OUTGOING loop_id, cleared by it (the new loop_id has none of its own).
        old_loop_id="$loop_id"
        loop_id="$(_mint_id)"
        recorded_last_sha=""
        rm -f "${session_dir}/${loop_key}."*.thread
        [[ -n "$old_loop_id" ]] && rm -f "${disposition_dir}/${old_loop_id}-"*.md
    fi
    # Publish the identity before releasing the lock, so a concurrent invocation
    # reads it instead of minting a rival one. `last_sha` is deliberately carried
    # unchanged (empty on a fresh or reset loop): reserving the identity must not
    # advance the anchor the next round continues from — only a fully recorded
    # round does that, below.
    _write_meta "$recorded_last_sha"
    _unlock_session
fi

# The disposition snapshot for this reviewed state, and the most recent snapshot
# from an earlier round of this same loop+persona. The prior snapshot is what a
# new round both re-injects (mechanism b) and carries forward from (so a finding
# retired in an earlier round stays visible in this state's snapshot). Empty on
# the bypass path (no loop_id, no dispositions).
snapshot_file=""
prior_snapshot=""
if [[ "$bypass" -eq 0 && -n "$loop_id" ]]; then
    snapshot_file="${disposition_dir}/${loop_id}-${persona}-${tree}.md"
    prior_round=-1
    shopt -s nullglob
    for _snap in "${disposition_dir}/${loop_id}-${persona}-"*.md; do
        [[ "$_snap" == "$snapshot_file" ]] && continue
        _r="$(sed -n 's/.* round=\([0-9][0-9]*\).*/\1/p' <(head -n 1 "$_snap"))"
        [[ -n "$_r" ]] || _r=0
        if [[ "$_r" -gt "$prior_round" ]]; then
            prior_round="$_r"
            prior_snapshot="$_snap"
        fi
    done
    shopt -u nullglob
fi

# The effective sandbox for a completed round, read from Codex's own session
# rollout (`$CODEX_HOME/sessions/.../rollout-*-<thread_id>.jsonl`). Every round's
# `turn_context` records the sandbox policy it actually ran under, so read-only is
# *proven from Codex's record*, not assumed from the flags we passed — which is
# what the driver must show, since a resume takes no `-s` and still honours a
# widening `$CODEX_HOME/config.toml`. The newest `turn_context` is this round's.
# Empty output (rollout missing or unparseable) is treated as unproven and fails
# closed by the caller.
_effective_sandbox() {
    local tid="$1" sess
    [[ -n "$tid" ]] || return 0
    sess="$(find "${codex_home}/sessions" -type f -name "*${tid}*.jsonl" 2>/dev/null |
        sort | tail -1)"
    [[ -n "$sess" && -f "$sess" ]] || return 0
    grep -E '"type":[[:space:]]*"turn_context"' "$sess" | tail -1 |
        sed -nE 's/.*"sandbox_policy":[[:space:]]*\{[[:space:]]*"type":[[:space:]]*"([^"]*)".*/\1/p'
}

# --- What the reviewer is reading (ADR-0020 §1) ------------------------------
#
# Adversarial review applies a code rubric, and applied to prose its findings
# about illustrative snippets are noise: a fenced block in an ADR is an example
# for a human operator, and "no error handling" or "untested" is not a defect in
# one. The qualification goes *here*, in the per-run preamble, rather than in a
# rubric or in docs/review/guide.md: those are standing contracts, true of every
# change, and editing one would apply this unconditionally — including to the
# changes where it is false. What this particular diff is, is per-run data.
#
# The classification is by path, and the exemption is stated per *block*, not
# per file. A fenced block can BE the decision — ADR-0016 defines the
# ToolRegistry Protocol in one — and a prose file routinely carries both kinds.
#
# Only `.md` and `.rst` count as prose. `.txt` is deliberately excluded: this
# repository's documentation is Markdown, while a `.txt` is as likely to be
# machine-consumed (a requirements list, a test fixture) as read. The two
# misclassifications are not symmetric — calling prose "code" costs a few noisy
# findings, calling code "prose" hands it an exemption from exactly the scrutiny
# it needs — so the split fails toward strict.
#
# Read NUL-delimited with `core.quotePath=false`, not as newline-separated text.
# Under git's default `quotePath=true` a non-ASCII path is emitted quoted and
# octal-escaped — `docs/café.md` becomes `"docs/caf\303\251.md"` — and the
# trailing quote defeats a `\.(md|rst)$` test, so the file would be classified
# as machine-consumed and silently lose the prose qualification. NUL delimiting
# also handles a path containing a newline, which no line-based read can.
#
# Classification is then a glob rather than a regex, since there is no longer a
# text stream to match against.
mapfile -d '' -t changed_paths < <(
    git "${_diff_opts[@]}" diff --no-ext-diff --no-textconv -z --name-only "${base_sha}...${sha}"
)

# One list item per path. Reading NUL-delimited keeps a path with a newline in
# it whole as one array element, but printing it raw would still put its second
# line into the prompt as *structure* rather than as a filename — one path
# rendering as two list items, neither of which exists. Escaped only when there
# is a control character to escape, so an ordinary path — a non-ASCII one
# included — is shown exactly as it appears on disk.
#
# This is a legibility fix, not a security boundary. The diff itself is handed
# to the reviewer verbatim a few lines below, so anyone who can commit a file
# can already put arbitrary text in front of it; the path is not a privileged
# channel and treating it as one would be theatre.
_render_path() {
    case "$1" in
    *[$'\n\t\r']*) printf -- '- `%s` (control characters escaped)\n' "$(printf '%q' "$1")" ;;
    *) printf -- '- `%s`\n' "$1" ;;
    esac
}

prose_paths=()
other_paths=()
for changed_path in "${changed_paths[@]}"; do
    case "$changed_path" in
    *.md | *.rst) prose_paths+=("$changed_path") ;;
    *) other_paths+=("$changed_path") ;;
    esac
done

# Writes the round's prompt to `$prompt`. With a non-empty, non-blank injection
# file as $1, the recorded prior-round dispositions are prepended (mechanism b,
# ADR-0025 §1) so a cold round that lost the warm session still sees what was
# already raised and answered. Round 1 and every resumed round pass nothing.
_write_prompt() {
{
    if [[ -n "${1:-}" && -s "${1:-}" ]]; then
        cat "$1"
        echo
    fi
    cat "$rubric"
    echo
    echo "## Change under review"
    echo
    echo "Review ONLY the committed diff below (${sha} vs ${base}). You may read full"
    echo "files in the repo for context, but do not modify anything. Output exactly the"
    echo "ranked findings and verdict from docs/review/guide.md."
    echo
    echo "### What these paths are"
    echo
    if [[ ${#prose_paths[@]} -gt 0 ]]; then
        echo "**Prose** — documentation read by a human operator, not executed or tested:"
        echo
        for p in "${prose_paths[@]}"; do _render_path "$p"; done
        echo
    fi
    if [[ ${#other_paths[@]} -gt 0 ]]; then
        echo "**Code, scripts, config, and tests** — machine-consumed, and judged as such:"
        echo
        for p in "${other_paths[@]}"; do _render_path "$p"; done
        echo
    fi
    if [[ ${#prose_paths[@]} -gt 0 ]]; then
        cat <<'PROSE'
In the prose files above, a fenced code block is by default **illustrative**: an
example shown to a human reader, not a program this repository runs, ships, or
tests. Judge such a block on whether it would **mislead the reader who follows
it** — a command that does not work, a wrong path or flag, a claim the
repository contradicts. Do **not** judge it for runtime correctness, error
handling, edge cases, concurrency, or test coverage, and do not ask for tests
on it. Findings of that kind on an illustrative snippet are noise; drop them.

**This exemption does not extend to a normative snippet.** Where a fenced block
*states a contract the repository will implement against* — a Protocol or type
definition, an interface signature, a schema, a required file format or
provenance line, a rule stated as the decision itself — the snippet **is** the
decision, and its internal validity is the subject of the review. Judge it as
strictly as you would the same text in a source file: correctness, internal
consistency, completeness, and whether an implementation could satisfy it.
ADR-0016 defines the `ToolRegistry` Protocol in exactly such a block.

Decide this **per block, not per file**: one document can carry both kinds, and
which one a block is depends on whether something is meant to be built against
it. If a block's status is genuinely ambiguous, review it as normative and say
that you did.
PROSE
        echo
    fi
    echo '```diff'
    printf '%s\n' "$diff"
    echo '```'
} >"$prompt"
}

# Re-injects the most recent prior snapshot into $1 (mechanism b), with a header
# telling the reviewer these are its own prior findings, not to be blindly
# re-raised (a warm re-raise past a seen rejection is a deliberate signal the ADR
# leaves un-suppressed). The snapshot already carries retired findings, so the
# reviewer sees the full disposition history, not just the last round.
_render_dispositions() {
    {
        echo "## Prior findings of THIS review (re-injected — the live session was unavailable)"
        echo
        echo "You have already reviewed earlier states of this same change in this review"
        echo "loop. Below are the findings you raised and their current disposition. Do NOT"
        echo "blindly re-raise a finding marked retired or already answered — engage it or"
        echo "leave it retired. You MAY re-raise a finding you still hold after reading the"
        echo "history; that is a deliberate, informed signal, not noise."
        echo
        cat "$prior_snapshot"
    } >"$1"
}

# A stable, unique id for a finding: its text with markdown and case flattened to
# an alnum key, hashed. Stable across reformatting of the same claim, distinct
# across different claims (ADR-0025 §4's id uniqueness/stability). The leading
# list enumerator (`1.`, `2)`, …) is dropped first, so the same finding keeps its
# id when its rank shifts between rounds. The WHOLE key is hashed — never a
# prefix — so two long findings sharing an opening (a shared reproduction
# preamble, say) do not collide and silently drop one. Reads stdin.
_finding_id() {
    local key
    key="$(tr -d '*#`_>~' | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' ' ' |
        sed 's/^ *//; s/^[0-9][0-9]* //; s/ *$//')"
    printf '%s-%s' "$persona" "$(printf '%s' "$key" | sha1sum | cut -c1-12)"
}

# Writes the per-finding disposition snapshot for this reviewed state (ADR-0025
# §4). This round's findings — parsed from the review body — are recorded status
# `open`; any finding present in the prior snapshot but absent now is carried
# forward status `retired` (Codex's own reassessment: it stopped raising it), so
# the snapshot for the terminal tree is self-contained and `ship` can render the
# verdict-changing history from it alone. Each finding block is delimited so the
# renderer can bound, select, and secret-scan it. Written atomically.
_write_snapshot() {
    [[ -n "$snapshot_file" ]] || return 0
    mkdir -p "$disposition_dir"
    local work
    work="$(mktemp -d -t "codex-snap-${persona}.XXXXXX")"

    # The review body without its trailing verdict line (validated present
    # already), so the verdict is not folded into the last finding block.
    awk 'NF{last=NR} {l[NR]=$0} END{for(i=1;i<=NR;i++) if(i!=last) print l[i]}' \
        "$out" >"${work}/body"
    # Split into finding blocks at each TOP-LEVEL ranked list item ("1.", "2)",
    # …). Markdown treats 0–3 leading spaces as top-level and 4+ as nested, so
    # that is the split rule: a finding's own indented reproduction steps stay
    # part of it, while a top-level list a reviewer happens to indent a couple of
    # spaces still splits. Text before the first item (a preamble) is discarded.
    awk -v dir="$work" '
        /^ {0,3}[0-9]+[.)]/ { n++; f=sprintf("%s/cur-%04d", dir, n) }
        n>0 { print >> f }
    ' "${work}/body"
    # A review the reviewer did not format as a ranked list yields no blocks
    # above. Rather than silently lose it (a lost finding is exactly what §4
    # forbids), record the whole body as one finding.
    if ! compgen -G "${work}/cur-*" >/dev/null; then
        cp "${work}/body" "${work}/cur-0001"
    fi

    local -A cur_text=() cur_sev=()
    local -a cur_order=()
    local bf id sev
    shopt -s nullglob
    for bf in "${work}"/cur-*; do
        id="$(_finding_id <"$bf")"
        [[ -n "${cur_text[$id]:-}" ]] && continue
        # `|| true`: no severity word is not an error, and a failing grep in this
        # bare assignment would trip `set -e` (the pipeline fails under pipefail).
        sev="$(grep -m1 -oiE 'blocker|major|minor' "$bf" | tr '[:upper:]' '[:lower:]' || true)"
        [[ -n "$sev" ]] || sev="unknown"
        cur_order+=("$id")
        cur_sev["$id"]="$sev"
        # Escape the HTML-comment markers so a finding that quotes `<!-- ... -->`
        # (a review OF this very script does) cannot be mistaken for a finding
        # header or terminator and truncate the record. Escaped once, here, so a
        # retired finding carried forward from a prior snapshot is not re-escaped;
        # GitHub renders the entities back to the literal markers.
        cur_text["$id"]="$(_escape_markers <"$bf")"
    done
    shopt -u nullglob

    local snapshot_tmp="${snapshot_file}.partial.$$"
    {
        echo "<!-- snapshot loop_id=${loop_id} persona=${persona} base_sha=${base_sha}" \
            "tree=${tree} sha=${sha} round=${round} verdict=${last_line} -->"
        for id in "${cur_order[@]}"; do
            local first="$round"
            local prior_first
            prior_first="$(_snapshot_field "$prior_snapshot" "$id" first_round)"
            [[ -n "$prior_first" ]] && first="$prior_first"
            _emit_finding "$id" "${cur_sev[$id]}" open "$first" "$round" "${cur_text[$id]}"
        done
        # Findings from the prior snapshot that this round did not raise: retired.
        local pid psev pfirst plast
        while IFS=$'\t' read -r pid psev pfirst plast; do
            [[ -n "$pid" ]] || continue
            [[ -n "${cur_text[$pid]:-}" ]] && continue
            _emit_finding "$pid" "$psev" retired "$pfirst" "$plast" \
                "$(_snapshot_text "$prior_snapshot" "$pid")"
        done < <(_snapshot_ids "$prior_snapshot")
    } >"$snapshot_tmp"
    mv "$snapshot_tmp" "$snapshot_file"
    rm -rf "$work"
}

# Neutralises the HTML-comment framing markers in finding text so payload can
# never be read as structure. GitHub renders the entities back to `<!--`/`-->`.
# Applied once, when a finding is first parsed (not on carry-forward).
_escape_markers() {
    sed 's/<!--/\&lt;!--/g; s/-->/--\&gt;/g'
}

# Emits one finding block: a machine header the renderer parses, then the
# finding text (its markers already escaped at parse time), then a terminator.
_emit_finding() {
    echo "<!-- finding id=${1} severity=${2} status=${3} first_round=${4} last_round=${5} -->"
    printf '%s\n' "$6"
    echo "<!-- /finding -->"
}

# The `id<TAB>severity<TAB>first_round<TAB>last_round` of every finding in a
# snapshot file, one per line. Empty when the file is missing.
_snapshot_ids() {
    [[ -n "$1" && -f "$1" ]] || return 0
    sed -n 's/.*<!-- finding id=\([^ ]*\) severity=\([^ ]*\) status=[^ ]* first_round=\([^ ]*\) last_round=\([^ ]*\) -->.*/\1\t\2\t\3\t\4/p' "$1"
}

# One header field of a specific finding in a snapshot file.
_snapshot_field() {
    [[ -n "$1" && -f "$1" ]] || return 0
    sed -n "s/.*<!-- finding id=${2} .*${3}=\\([^ ]*\\).*/\\1/p" "$1" | head -n 1
}

# The verbatim text of a specific finding in a snapshot file (between its header
# and terminator).
_snapshot_text() {
    [[ -n "$1" && -f "$1" ]] || return 0
    awk -v id="$2" '
        $0 ~ ("<!-- finding id=" id " ") { grab=1; next }
        grab && /<!-- \/finding -->/ { grab=0 }
        grab { print }
    ' "$1"
}

# Unset by default, so local runs keep using the Codex CLI's own default model.
# CI pins this (CODEX_REVIEW_MODEL in codex-review.yml) so the reviewer model is
# an explicit, deliberate choice there rather than whatever the pinned CLI
# version happens to default to.
model_args=()
if [[ -n "${CODEX_REVIEW_MODEL:-}" ]]; then
    model_args=(-m "$CODEX_REVIEW_MODEL")
fi

# On the bypass path (detected above) Codex's own bubblewrap sandbox is skipped:
# in CI the runner is already an ephemeral, externally-sandboxed environment where
# bwrap cannot set up its network namespace ("bwrap: loopback: Failed
# RTM_NEWADDR"), which breaks every file read and degrades the review to an
# apology — the exact case --dangerously-bypass-approvals-and-sandbox documents.
# The review loop is local (ADR-0015 §1), so this bypass does not reach a
# persistent session — a persistent review never widens its sandbox (ADR-0025 §1).
# When it applies, this is a cold one-shot exactly as before: no thread recorded,
# no resume, no read-only proof (the sandbox is deliberately off).

# The injection budget bounds `diff + re-injected dispositions` (ADR-0025 §1's
# graceful-degradation floor): past it, mechanism (b) would not fit, so the round
# drops to a plain cold review of the diff rather than a truncated injection.
inject_budget="${CODEX_REVIEW_INJECT_BUDGET:-500000}"
diff_bytes="$(printf '%s' "$diff" | wc -c)"

# The thread this round actually ran on, recorded afterwards so the next round
# resumes it. Empty on the bypass path (no persistence).
round_thread=""

if [[ "$bypass" -eq 1 ]]; then
    _write_prompt ""
    echo "Running Codex '${persona}' review of HEAD vs '${base}' (CI bypass, cold)…" >&2
    # -o captures just the final review; progress streams to stderr.
    codex exec --dangerously-bypass-approvals-and-sandbox "${model_args[@]}" \
        -o "$out" - <"$prompt" >&2
else
    # Enforced read-only on every round, proven from Codex's own record below.
    # Resume takes no `-s`, and a widening `$CODEX_HOME/config.toml` is honoured
    # over a bare invocation, so read-only is forced with `-c sandbox_mode` — a
    # driver-set `-c` overrides config.toml, on both a fresh start and a resume.
    # `-s read-only` is kept on the fresh start too: it is redundant with the
    # `-c`, but it is the flag the CLI documents for the initial sandbox and it
    # keeps the start invocation self-describing. Neither the sandbox-bypass flag
    # nor any widening `-s`/`-c sandbox_mode` override is ever passed here.
    ro_config=(-c sandbox_mode="read-only")
    used_resume=0

    if [[ -n "$recorded_thread" ]]; then
        _write_prompt ""
        echo "Resuming Codex '${persona}' session ${recorded_thread:0:12} vs '${base}'" \
            "(read-only)…" >&2
        # `--json` puts the event stream (carrying thread.started) on stdout,
        # captured to $stream; Codex's human progress stays on stderr. `-o` still
        # writes just the final review to $out.
        if codex exec resume "$recorded_thread" --json "${ro_config[@]}" \
            "${model_args[@]}" -o "$out" - <"$prompt" >"$stream"; then
            used_resume=1
            round_thread="$recorded_thread"
        else
            # Resume is unavailable — a pruned session, an ephemeral host. Not a
            # failure: fall through to a fresh read-only session with the prior
            # dispositions re-injected (mechanism b), the ADR-0025 §1 fallback.
            echo "resume unavailable; starting a fresh read-only session with prior" \
                "findings re-injected" >&2
        fi
    fi

    if [[ "$used_resume" -eq 0 ]]; then
        # A fresh start: round 1 of this loop, or a degraded resume. Re-inject the
        # recorded dispositions when they exist and `diff + injection` fits the
        # budget; past the budget, drop to a plain cold review of the diff (the
        # floor) rather than truncating — the dispositions stay on record, never
        # silently lost, and a re-raise then costs at most one round.
        inject=""
        if [[ -n "$prior_snapshot" && -s "$prior_snapshot" ]]; then
            _render_dispositions "$inject_tmp"
            inject_bytes="$(wc -c <"$inject_tmp")"
            if [[ $((inject_bytes + diff_bytes)) -le "$inject_budget" ]]; then
                inject="$inject_tmp"
            else
                echo "prior findings + diff (${inject_bytes}+${diff_bytes} bytes) exceed the" \
                    "injection budget (${inject_budget}); dropping to a plain cold review of" \
                    "the diff (the degradation floor). The dispositions remain recorded in" \
                    "${prior_snapshot}." >&2
            fi
        fi
        _write_prompt "$inject"
        echo "Running Codex '${persona}' review of HEAD vs '${base}' (read-only, fresh" \
            "session)…" >&2
        codex exec --json -s read-only "${ro_config[@]}" "${model_args[@]}" \
            -o "$out" - <"$prompt" >"$stream"
        round_thread="$(grep -o '"thread_id":"[^"]*"' "$stream" | head -1 |
            sed 's/.*:"//; s/"$//')"
    fi

    # Read-only proven, not assumed (ADR-0025 §4): read the sandbox Codex actually
    # ran this round under from its session rollout, and fail closed unless it is
    # read-only. Empty means the rollout could not be found or parsed — unproven,
    # which is not the same as read-only, so it fails closed too. This holds even
    # against a widening config.toml, since the `turn_context` records the
    # effective policy after all config layering.
    effective_sandbox="$(_effective_sandbox "$round_thread")"
    if [[ "$effective_sandbox" != "read-only" ]]; then
        echo "refusing to record: could not prove the review ran read-only" >&2
        echo "effective sandbox for thread ${round_thread:-<unknown>} was" \
            "'${effective_sandbox:-unreadable}' (a widening \$CODEX_HOME/config.toml, a" \
            "bypass flag, or a missing session rollout can cause this)" >&2
        exit 1
    fi
fi

# Pinning the diff is not enough on its own: Codex reads files from the working
# tree as it goes, so if the checkout moved *during* the review — another commit,
# a stray edit — it reasoned about a tree that is not the SHA this artifact would
# name. Re-check both, and record nothing if either changed. A missing artifact
# costs a re-run; a false one is evidence for code nobody reviewed.
if [[ "$(git rev-parse HEAD)" != "$sha" || -n "$(git status --porcelain)" ]]; then
    echo "the checkout changed while the review was running; not recording it" >&2
    echo "HEAD was ${sha}, now $(git rev-parse HEAD); re-run on a settled tree" >&2
    exit 1
fi

# An artifact is evidence that a review happened, so an empty one is worse than
# none: ship.sh checks that the file exists, and would post silence as though it
# were a clean review. Codex can exit 0 having written nothing (a dropped
# connection, a refusal); fail loudly instead of recording that.
if [[ ! -s "$out" ]] || ! grep -q '[^[:space:]]' "$out"; then
    echo "codex produced an empty review; not recording an artifact" >&2
    echo "re-run: scripts/codex-review.sh ${persona} ${base}" >&2
    exit 1
fi

# Non-empty is a weak test: a refusal or a timeout message ("I'm unable to
# review this repository") is prose, and would be recorded and posted as though
# it were a review. The rubric requires a closing one-line verdict
# (docs/review/guide.md), so demand exactly that.
#
# Matched against the *last non-blank line*, not anywhere in the body: a
# substring search accepts prose that merely mentions the words, e.g. "I cannot
# provide a verdict or APPROVE this change". Markdown emphasis is stripped
# first, since the reviewer writes "**Verdict: X**", "Verdict: X" and
# "VERDICT: X" interchangeably.
#
# The `Verdict:` label is optional, because the contract this check enforces
# does not require it. docs/review/guide.md asks the reviewer to "end with a
# one-line verdict: BLOCK, APPROVE WITH NITS, or APPROVE", and the preamble
# tells it to output the verdict "from docs/review/guide.md" — so a bare
# `APPROVE WITH NITS` is a conforming review. Demanding the label made this
# check stricter than the rubric it cites and discarded conforming reviews as
# refusals, at the cost of a full run each time (issue #120).
#
# The guard is not weakened by it. What it exists to catch is a refusal or a
# timeout — "I'm unable to review this repository" — and those do not end in a
# line that is exactly a verdict word. Anchoring to the whole line is what does
# the work here; the label never did.
last_line="$(grep -v '^[[:space:]]*$' "$out" | tail -n 1 |
    tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
if ! grep -qiE '^(verdict:?[[:space:]]*)?(block|approve with nits|approve)\.?$' <<<"$last_line"; then
    echo "codex output does not end in a verdict; not recording it as a review" >&2
    echo "this is usually a refusal or a timeout rather than a review" >&2
    echo "last line was: ${last_line}" >&2
    exit 1
fi

# A verdict and nothing else is not a review either. The rubric's own
# anti-patterns say so: "No rubber-stamping. 'Looks good' with no scrutiny is a
# failure. If you genuinely find nothing, say so explicitly and state what you
# checked." So an output whose only non-blank line is the verdict has skipped
# the part that carries the value.
#
# This check is new rather than moved. Dropping the `Verdict:` label above let a
# bare `APPROVE` through, which the label had been excluding by accident — but
# `Verdict: APPROVE` alone always passed, so the hole predates that and merely
# widened. Closed for both forms, since closing it for one would leave the rule
# depending on which spelling the reviewer happened to pick.
body_lines="$(grep -c -v '^[[:space:]]*$' "$out" || true)"
if [[ "$body_lines" -lt 2 ]]; then
    echo "codex returned a verdict with no review body; not recording it" >&2
    echo "the rubric requires ranked findings, or an explicit statement of what" >&2
    echo "was checked when there are none (docs/review/guide.md)" >&2
    exit 1
fi

# Record the review against the content it covers (ADR-0020 §3, superseding
# ADR-0015 §1's commit anchor). `just ship` refuses to report a review whose
# recorded base and tree do not match the PR's current merge base and HEAD tree,
# which turns "did you review the current code?" from a matter of care into a
# check. The artifact is git-ignored: evidence for the local ship step, not
# history.
#
# THE ARTIFACT IS NAMED BY THE ANCHOR IT IS SELECTED BY (ADR-0027 §6). The name
# used to carry the commit, which stopped being what the artifact is selected by
# when ADR-0020 §3 re-anchored acceptance onto content — and issue #149 is what
# that vestige cost: two runs of one SHA against different bases collided on one
# path, so the older-base run finishing last replaced the current-base artifact
# and `ship` rejected a valid review as stale. Carrying every field the
# acceptance rule selects on — the loop identity (ADR-0025 §4), the persona, the
# base and the tree — makes that collision UNCONSTRUCTIBLE rather than unlikely:
# two runs the rule would distinguish can no longer occupy one path. This is the
# same mechanism as the patch identity, not a second one; once selection is by
# content, naming by content is the identity function.
#
# `noloop` stands in for a run with no loop identity — the CI bypass path, which
# keeps no session — so the field is never empty and the segments never collapse.
# The name is an identity and nothing parses it: `ship` reads the persona from
# the recorded provenance field, never off the filename.
mkdir -p "$review_dir"
artifact="${review_dir}/${loop_id:-noloop}-${persona}-${base_sha}-${tree}.md"
# base_sha was pinned before the diff (above), not re-resolved here: ship.sh
# compares it against the PR's real base, so a review run against a narrower or
# since-moved base — which still produces a correctly-named artifact — cannot
# pass as review of the whole PR diff.
#
# Written to a temporary file and renamed into place, never streamed straight
# to the final path: an interrupt partway through the write would otherwise
# leave a truncated artifact carrying a valid name and base_sha, which ship
# would accept as proof of a completed review. `mv` within one directory is
# atomic, so the artifact either exists whole or not at all.
#
# The aggregate (§2) is recorded on the same line so `just ship` can render it
# into the PR comment: the human at merge then sees the same round count and
# churn ratio the author saw, which is the whole point of printing it.
artifact_tmp="${artifact}.partial.$$"
{
    # Both binary counts are recorded, not just the one in the final diff. §2's
    # requirement is that the reviewer at merge holds the aggregate the author
    # held, and the terminal prints both — so persisting only `net_binary` would
    # drop a caveat the author saw. They come apart for real: a binary added in
    # one commit and reverted in a later one is absent from the net diff while
    # still being unmeasured work the branch did.
    #
    # Each is omitted rather than recorded as 0, so ship renders a caveat only
    # where there is one. `${var:+…}` cannot express that: the counts are the
    # string "0" when empty, which is non-empty and would expand.
    binary_field=""
    if [[ "$net_binary" -gt 0 ]]; then
        binary_field="binary_files=${net_binary} "
    fi
    if [[ "$churn_binary" -gt 0 ]]; then
        binary_field="${binary_field}binary_churn=${churn_binary} "
    fi
    # loop_id and thread_id are recorded for ADR-0025 §4's ship-time snapshot
    # selection by the full anchor (loop, persona, base, tree, terminal turn).
    # thread_id is empty on the bypass path, which keeps no session.
    # patch_id is ADR-0027 §2's coverage anchor across a moved base. Recorded
    # even when empty, so `ship` can tell "this artifact predates the field" from
    # "this range had no trustworthy identity" — both make the moved-base path
    # unavailable, and neither may be read as a match.
    echo "<!-- persona=${persona} base=${base} base_sha=${base_sha} sha=${sha}" \
        "branch=${branch} tree=${tree} patch_id=${patch_id} round=${round}" \
        "loop_id=${loop_id} thread_id=${round_thread}" \
        "net_lines=${net_lines} churn_lines=${churn_lines}" \
        "churn_ratio=${churn_ratio} churn_bound=${churn_bound} commits=${commits}" \
        "${binary_field}${supersedes:+supersedes=${supersedes} }-->"
    cat "$out"
} >"$artifact_tmp"
mv "$artifact_tmp" "$artifact"

# Persist the session and dispositions only on the persistent path — the bypass
# path keeps no thread. Written last, after every validation has passed, so a
# rejected round never advances the loop the next round continues: the meta's
# last_sha (the ancestry anchor above) only moves once a round is fully recorded.
#
# The whole advance is one read-modify-write under the loop lock (#142): re-read
# the meta and refuse to record if the identity this round was anchored to is no
# longer the loop's. That happens when another invocation reset the loop while
# this round was in flight — recording anyway would file this round's thread and
# dispositions under a loop_id no later round will look up, silently orphaning
# them. The review itself is already on disk at `$artifact`; only
# the session advance is refused, and re-running the persona records it cleanly.
#
# The identity is necessary but not sufficient: the anchor must also only ever
# move FORWARD. Two concurrent rounds of the same loop can finish out of order —
# one started at B, another at its descendant C — and the later-finishing older
# round would otherwise rewind last_sha to B and replace the persona's thread
# with its own staler session, so the next round resumes the conversation that
# saw less. The settled-tree check above catches the ordinary shape of this (the
# older round's HEAD has moved under it), but it is a check about the *checkout*,
# not about the loop's state, and it passes if the checkout is put back. So the
# loop guards its own anchor too: the advance requires the recorded state to be
# an ancestor of this round's — "this round builds on what the loop recorded".
# Sequentially this always holds: the meta's last_sha is either empty (a fresh,
# reset, or adopted loop) or the state this round continued from.
if [[ "$bypass" -eq 0 ]]; then
    _lock_session
    current_loop_id=""
    current_last_sha=""
    if [[ -f "$meta_file" ]]; then
        current_loop_id="$(sed -n 's/^loop_id=//p' "$meta_file")"
        current_last_sha="$(sed -n 's/^last_sha=//p' "$meta_file")"
    fi
    if [[ "$current_loop_id" != "$loop_id" ]]; then
        _unlock_session
        echo >&2
        echo "another codex-review run reset this review loop while this round was" >&2
        echo "in flight (loop ${loop_id:0:12} was replaced by ${current_loop_id:0:12})." >&2
        echo "Refusing to record this round's session state under a dead identity." >&2
        echo "Run one persona at a time in a clone (ADR-0015), then re-run this one." >&2
        exit 1
    fi
    if [[ -n "$current_last_sha" ]] &&
        ! git merge-base --is-ancestor "$current_last_sha" "$sha" 2>/dev/null; then
        _unlock_session
        echo >&2
        echo "this review loop has already recorded a newer state (${current_last_sha:0:12})" >&2
        echo "than this round's (${sha:0:12}), so this round finished out of order." >&2
        echo "Refusing to rewind the loop's anchor and session to the older state." >&2
        echo "Run one persona at a time in a clone (ADR-0015), then re-run this one." >&2
        exit 1
    fi
    _write_meta "$sha"
    if [[ -n "$round_thread" ]]; then
        thread_tmp="${thread_file}.partial.$$"
        printf '%s\n' "$round_thread" >"$thread_tmp"
        mv "$thread_tmp" "$thread_file"
    fi
    _write_snapshot
    _unlock_session
fi

echo >&2
echo "===== ${persona} review (HEAD vs ${base}) =====" >&2
echo "(recorded at ${artifact#"${repo_root}/"}, tree ${tree:0:12}, round ${round})" >&2
cat "$out"
