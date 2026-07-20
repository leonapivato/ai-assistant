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

diff="$(git diff "${base_sha}...${sha}")"
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

# Round: how many commits on this branch's lineage already carry a review
# artifact, plus this one. HEAD itself is skipped, so re-running a second
# persona on one commit stays the same round rather than inflating the count.
#
# Rewriting history resets this — an amended or squashed commit leaves the
# lineage and takes its artifact's visibility with it. That is issue #97, and it
# is deliberately not solved here: §3 makes those rewrites cheaper, which makes
# the erasure easier to hit, and the fix belongs with the aggregate's storage
# rather than with this arithmetic.
round=1
while read -r commit; do
    [[ -z "$commit" || "$commit" == "$sha" ]] && continue
    if compgen -G "${review_dir}/${commit}-*.md" >/dev/null; then
        round=$((round + 1))
    fi
done < <(git rev-list "${base_sha}..${sha}")

# Sum added+deleted across a --numstat stream. Binary files report `-` in both
# columns; the numeric guard skips them rather than letting awk coerce `-` to 0
# and imply a count it did not measure.
_numstat_lines() {
    awk '{ if ($1 ~ /^[0-9]+$/) a += $1; if ($2 ~ /^[0-9]+$/) d += $2 }
         END { print a + d + 0 }'
}

net_lines="$(git diff --numstat "${base_sha}...${sha}" | _numstat_lines)"
churn_lines="$(git log --numstat --format= "${base_sha}..${sha}" | _numstat_lines)"
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

# Where the change supersedes or amends another document, that document's size
# belongs next to this one's: ADR-0017 superseded one clause of a 175-line ADR
# and peaked at 821 lines, and it was that comparison — one number next to
# another — that made two hours of drift legible. Read off the *added* lines
# only, so an unchanged historical mention does not register.
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
    echo "  round        ${round} — commits on this branch already carrying a review, plus this one"
    echo "  net diff     ${net_lines} lines across ${commits} commit(s)"
    echo "  churn ratio  ${churn_ratio} — ${churn_lines} lines touched ÷ ${net_lines} net"
    if [[ -n "$supersedes_pretty" ]]; then
        echo "  supersedes   ${supersedes_pretty}"
    fi
    echo "  (advisory — nothing here blocks. A high round count or a churn ratio"
    echo "   far above 1 is the signal that the loop is reworking itself.)"
    echo
} >&2

prompt="$(mktemp -t "codex-prompt-${persona}.XXXXXX.md")"
out="$(mktemp -t "codex-review-${persona}.XXXXXX.md")"
# All three temporaries, on every exit path. `$out` holds the full review text
# and `$artifact_tmp` a half-written copy of it, so leaving either behind
# accumulates review content in /tmp and in .review/ — the latter invisible to
# the dirty-tree check, since .review/ is ignored. ${var:+...} expands to
# nothing while artifact_tmp is still unset, which it is for most of this script.
trap 'rm -f "$prompt" "$out" ${artifact_tmp:+"$artifact_tmp"}' EXIT

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
changed_paths="$(git diff --name-only "${base_sha}...${sha}")"
prose_paths="$(grep -E '\.(md|rst)$' <<<"$changed_paths" || true)"
other_paths="$(grep -vE '\.(md|rst)$' <<<"$changed_paths" || true)"

{
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
    if [[ -n "$prose_paths" ]]; then
        echo "**Prose** — documentation read by a human operator, not executed or tested:"
        echo
        # Read line by line rather than word-splitting: a path containing a space
        # would otherwise be listed as two files that do not exist.
        while IFS= read -r p; do printf -- '- `%s`\n' "$p"; done <<<"$prose_paths"
        echo
    fi
    if [[ -n "$other_paths" ]]; then
        echo "**Code, scripts, config, and tests** — machine-consumed, and judged as such:"
        echo
        while IFS= read -r p; do printf -- '- `%s`\n' "$p"; done <<<"$other_paths"
        echo
    fi
    if [[ -n "$prose_paths" ]]; then
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

# Codex sandboxes the shell commands the model runs (file reads, git) with
# bubblewrap. In CI the runner is already an ephemeral, externally-sandboxed
# environment where bwrap cannot set up its network namespace
# ("bwrap: loopback: Failed RTM_NEWADDR"); that failure breaks every file read
# and degrades the review to an apology. There, skip Codex's own sandbox — the
# exact case --dangerously-bypass-approvals-and-sandbox documents. Locally the
# read-only sandbox works and is a real safety layer, so keep it. GITHUB_ACTIONS
# is "true" on the runner — matched exactly, so an inherited GITHUB_ACTIONS=false
# cannot silently disable the local sandbox; CODEX_REVIEW_NO_SANDBOX=1 forces the
# bypass either way. The prompt still instructs a read-only review regardless.
sandbox_args=(-s read-only)
if [[ "${CODEX_REVIEW_NO_SANDBOX:-}" == "1" || "${GITHUB_ACTIONS:-}" == "true" ]]; then
    sandbox_args=(--dangerously-bypass-approvals-and-sandbox)
fi

# Unset by default, so local runs keep using the Codex CLI's own default model.
# CI pins this (CODEX_REVIEW_MODEL in codex-review.yml) so the reviewer model is
# an explicit, deliberate choice there rather than whatever the pinned CLI
# version happens to default to.
model_args=()
if [[ -n "${CODEX_REVIEW_MODEL:-}" ]]; then
    model_args=(-m "$CODEX_REVIEW_MODEL")
fi

echo "Running Codex '${persona}' review of HEAD vs '${base}' (read-only)…" >&2
# -o captures just the final review; progress streams to stderr.
codex exec "${sandbox_args[@]}" "${model_args[@]}" -o "$out" - <"$prompt" >&2

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
last_line="$(grep -v '^[[:space:]]*$' "$out" | tail -n 1 |
    tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
if ! grep -qiE '^verdict:?[[:space:]]*(block|approve with nits|approve)\.?$' <<<"$last_line"; then
    echo "codex output does not end in a verdict; not recording it as a review" >&2
    echo "this is usually a refusal or a timeout rather than a review" >&2
    echo "last line was: ${last_line}" >&2
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
    echo "<!-- persona=${persona} base=${base} base_sha=${base_sha} sha=${sha}" \
        "tree=${tree} round=${round} net_lines=${net_lines} churn_lines=${churn_lines}" \
        "churn_ratio=${churn_ratio} commits=${commits}${supersedes:+ supersedes=${supersedes}} -->"
    cat "$out"
} >"$artifact_tmp"
mv "$artifact_tmp" "$artifact"

echo >&2
echo "===== ${persona} review (HEAD vs ${base}) =====" >&2
echo "(recorded at .review/${sha}-${persona}.md, tree ${tree:0:12}, round ${round})" >&2
cat "$out"
