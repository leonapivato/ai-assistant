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

# `core.quotePath=false` here too, so a non-ASCII path reaches the reviewer as
# `docs/café.md` rather than `"docs/caf\303\251.md"`. Same reason as the path
# classification below: the reviewer reads this diff, and an escaped path is a
# file it cannot find in the tree.
diff="$(git -c core.quotePath=false diff "${base_sha}...${sha}")"
if [[ -z "$diff" ]]; then
    echo "no changes between ${base_sha} and ${sha} to review" >&2
    exit 0
fi

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
disposition_file="${disposition_dir}/${loop_key}.${persona}.md"

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
# No session state on the bypass path — it keeps no thread to resume. loop_id
# stays empty there and is recorded empty, alongside the empty thread_id.
loop_id=""
recorded_thread=""
if [[ "$bypass" -eq 0 ]]; then
    if [[ -f "$meta_file" ]]; then
        loop_id="$(sed -n 's/^loop_id=//p' "$meta_file")"
    fi
    if [[ -z "$loop_id" ]]; then
        loop_id="$(_mint_id)"
        mkdir -p "$session_dir"
        meta_tmp="${meta_file}.partial.$$"
        printf 'loop_id=%s\nbranch=%s\nbase_sha=%s\n' \
            "$loop_id" "$branch" "$base_sha" >"$meta_tmp"
        mv "$meta_tmp" "$meta_file"
    fi
fi

# The thread this persona's session is resumed on, if the loop already has one.
if [[ "$bypass" -eq 0 && -f "$thread_file" ]]; then
    recorded_thread="$(head -n 1 "$thread_file")"
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
    git -c core.quotePath=false diff -z --name-only "${base_sha}...${sha}"
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

# Renders the recorded per-round dispositions for this loop+persona into $1, with
# a header telling the reviewer these are its own prior findings, not to be
# blindly re-raised (a warm re-raise past a seen rejection is a deliberate signal
# the ADR leaves un-suppressed).
_render_dispositions() {
    {
        echo "## Prior rounds of THIS review (re-injected — the live session was unavailable)"
        echo
        echo "You have already reviewed earlier states of this same change in this review"
        echo "loop. Below are the findings you raised and the verdicts you reached, per"
        echo "round. Do NOT blindly re-raise a finding you already made that was answered —"
        echo "engage the answer or withdraw it. You MAY re-raise a finding you still hold"
        echo "after reading the response; that is a deliberate, informed signal, not noise."
        echo
        cat "$disposition_file"
    } >"$1"
}

# Appends this round's review to the disposition ledger (ADR-0025 §1, §4): the
# durable backstop mechanism (b) re-injects when the warm session is gone, and
# the record §4 requires reach the merge reviewer. Keyed on the reviewed tree, so
# re-running one commit does not duplicate an entry, and a stable per-state id is
# recorded. The ledger is git-ignored (under .review/), like the artifacts.
_append_disposition() {
    local id
    id="$(printf '%s' "$tree" | sha1sum | awk '{print $1}')"
    mkdir -p "$disposition_dir"
    if grep -q "id=${id} " "$disposition_file" 2>/dev/null; then
        return 0
    fi
    {
        echo "<!-- disposition loop_id=${loop_id} persona=${persona} round=${round}" \
            "base_sha=${base_sha} tree=${tree} sha=${sha} id=${id} verdict=${last_line} -->"
        echo "### Round ${round} — tree ${tree:0:12} — verdict: ${last_line}"
        echo
        cat "$out"
        echo
    } >>"$disposition_file"
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
        if [[ -s "$disposition_file" ]]; then
            _render_dispositions "$inject_tmp"
            inject_bytes="$(wc -c <"$inject_tmp")"
            if [[ $((inject_bytes + diff_bytes)) -le "$inject_budget" ]]; then
                inject="$inject_tmp"
            else
                echo "prior findings + diff (${inject_bytes}+${diff_bytes} bytes) exceed the" \
                    "injection budget (${inject_budget}); dropping to a plain cold review of" \
                    "the diff (the degradation floor). The dispositions remain recorded in" \
                    "${disposition_file}." >&2
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
# check. The filename still carries the SHA — it keeps artifacts from colliding
# and says which commit the run happened on — but it is no longer what ship
# matches on, so a commit that changes no reviewed byte no longer costs a round.
# The artifact is git-ignored: evidence for the local ship step, not history.
mkdir -p "$review_dir"
artifact="${review_dir}/${sha}-${persona}.md"
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
    echo "<!-- persona=${persona} base=${base} base_sha=${base_sha} sha=${sha}" \
        "branch=${branch} tree=${tree} round=${round}" \
        "loop_id=${loop_id} thread_id=${round_thread}" \
        "net_lines=${net_lines} churn_lines=${churn_lines}" \
        "churn_ratio=${churn_ratio} churn_bound=${churn_bound} commits=${commits}" \
        "${binary_field}${supersedes:+supersedes=${supersedes} }-->"
    cat "$out"
} >"$artifact_tmp"
mv "$artifact_tmp" "$artifact"

# Persist the session and dispositions only on the persistent path — the bypass
# path keeps no thread. The thread is written last, after every validation has
# passed, so a rejected round never advances the session the next round resumes.
if [[ "$bypass" -eq 0 ]]; then
    if [[ -n "$round_thread" ]]; then
        mkdir -p "$session_dir"
        thread_tmp="${thread_file}.partial.$$"
        printf '%s\n' "$round_thread" >"$thread_tmp"
        mv "$thread_tmp" "$thread_file"
    fi
    _append_disposition
fi

echo >&2
echo "===== ${persona} review (HEAD vs ${base}) =====" >&2
echo "(recorded at .review/${sha}-${persona}.md, tree ${tree:0:12}, round ${round})" >&2
cat "$out"
