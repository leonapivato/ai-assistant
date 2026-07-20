#!/usr/bin/env bash
# Report the local Codex review to the pull request — the merge-readiness step
# (ADR-0015 §1).
#
# Review runs locally now, so the PR record depends on someone pasting it. This
# script is that paste, with the forgettable parts checked rather than trusted:
# it refuses unless a review artifact exists for the *exact* commit the PR head
# points at. The common failure under a paste-it-yourself norm is a review of a
# stale commit — that one is now mechanical.
#
# Deliberately not a pre-push hook: review is a pre-merge step, not a per-push
# one. Gating every push would force a full Codex run per WIP commit, which is
# the fix-per-finding cost pattern ADR-0015 exists to remove.
#
# Usage: scripts/ship.sh
set -euo pipefail

die() {
    echo "ship: $1" >&2
    exit 1
}

command -v gh >/dev/null 2>&1 || die "gh CLI not found on PATH"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "HEAD" ]] && die "detached HEAD — check out the PR branch first"
[[ "$branch" == "main" ]] && die "on main; ship reports a PR branch's review"

# The review covers the committed diff, so uncommitted work is by definition
# unreviewed — shipping here would report a review of something else. Use
# `status --porcelain`, not `diff --quiet`: an untracked file is unreviewed work
# too, and a pair of diff checks silently passes it.
if [[ -n "$(git status --porcelain)" ]]; then
    die "working tree is dirty (tracked or untracked) — commit or stash first"
fi

sha="$(git rev-parse HEAD)"

# The PR must already show this commit, or the review would name a SHA a reader
# cannot find on the PR.
pr_sha="$(gh pr view --json headRefOid --jq .headRefOid 2>/dev/null || true)"
[[ -z "$pr_sha" ]] && die "no PR found for '${branch}' — open one first (gh pr create)"
if [[ "$pr_sha" != "$sha" ]]; then
    die "PR head is ${pr_sha:0:12} but HEAD is ${sha:0:12} — push first"
fi

# Adversarial is the required lens before merge; architecture is additionally
# required for a contract change, and is posted too whenever it was run.
shopt -s nullglob
artifacts=(".review/${sha}-"*.md)
shopt -u nullglob

if [[ ! -f ".review/${sha}-adversarial.md" ]]; then
    stale=""
    if compgen -G ".review/*.md" >/dev/null; then
        stale=" (reviews exist for other commits — they do not cover ${sha:0:12})"
    fi
    die "no adversarial review for ${sha:0:12}${stale}
     run: just review-codex adversarial"
fi

# A change to the shared contract surface needs the architecture lens too
# (CONTRIBUTING, "Contract ADRs land before their implementation"). That was
# documented but unenforced, which is precisely the prose-not-mechanism failure
# ADR-0015 exists to correct — so check it here rather than trusting recall.
base_ref="$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null || true)"
[[ -z "$base_ref" ]] && die "could not resolve the PR's base branch"

# Everything below fetches from `origin`, which is only the PR's base repository
# in a direct-push clone — the model this project uses (ADR-0010, ADR-0015). From
# a fork, `origin` is the fork and origin/<base> is *its* copy of the branch, so
# the range check and the core/ scan would silently validate the wrong diff.
# Refuse rather than build fork support for a workflow nobody here runs: a loud
# stop is recoverable, a quietly-wrong contract check is not.
#
# `isCrossRepository` is a real `gh pr view` field, unlike the `baseRepository`
# this first reached for — which does not exist, so the query failed, the error
# was swallowed, and the check silently never ran. Errors are not suppressed
# here for that reason: a check that cannot run must stop the ship, not wave it
# through.
cross_repo="$(gh pr view --json isCrossRepository --jq .isCrossRepository)" ||
    die "could not determine whether this PR comes from a fork"
if [[ "$cross_repo" == "true" ]]; then
    die "this PR comes from a fork, so origin is not its base repository
     ship assumes origin is the base repo (ADR-0015 clone-per-agent)
     post the review by hand instead"
fi
# Fetch the base so the comparison is against the real merge target, not a
# possibly-stale local ref; FETCH_HEAD is that ref as of this moment.
git fetch --no-tags --quiet origin "$base_ref" ||
    die "could not fetch base '${base_ref}' to check for contract changes"

# Capture the file list before matching, rather than piping git into `grep -q`.
# `grep -q` exits at the first match and closes the pipe; on a diff large enough
# to fill the pipe buffer, git then dies of SIGPIPE and — under `set -o
# pipefail` — the whole pipeline reports failure. The `if` would read that as
# "no core change" and skip the architecture requirement entirely: a fail-open
# on the one check that guards the shared contract surface.
changed_files="$(git diff --name-only "FETCH_HEAD...${sha}")"
if grep -qE '^src/ai_assistant/core/(protocols|types)\.py$' <<<"$changed_files"; then
    if [[ ! -f ".review/${sha}-architecture.md" ]]; then
        die "this change touches core/protocols.py or core/types.py, so it needs
     the architecture lens as well as the adversarial one
     run: just review-codex architecture"
    fi
fi

# Naming the right commit is not enough: a review run against a narrower base
# (`just review-codex adversarial HEAD~1`) covers only part of the PR yet
# produces a correctly-named artifact. Compare the range each review actually
# covered against the PR's own merge base.
expected_base="$(git merge-base FETCH_HEAD "$sha")"
for a in "${artifacts[@]}"; do
    recorded_base="$(sed -n '1s/.*base_sha=\([0-9a-f]*\).*/\1/p' "$a")"
    if [[ "$recorded_base" != "$expected_base" ]]; then
        die "$(basename "$a") reviewed a different range than this PR covers
     (recorded base ${recorded_base:-none}, PR base ${expected_base:0:12})
     re-run the review with its default base: just review-codex <persona>"
    fi

    # Re-check the verdict here, not just when recording. A filename and a
    # base_sha say where an artifact came from, not that it holds a finished
    # review: a file truncated by an interrupt, or edited by hand, keeps valid
    # metadata while losing its body. ship is the last point before this
    # becomes the record, so it verifies rather than trusts.
    a_last="$(grep -v '^[[:space:]]*$' "$a" | tail -n 1 |
        tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    if ! grep -qiE '^verdict:?[[:space:]]*(block|approve with nits|approve)\.?$' <<<"$a_last"; then
        die "$(basename "$a") does not end in a verdict — it is incomplete
     re-run: just review-codex $(basename "$a" .md | sed "s/^${sha}-//")"
    fi
done

num="$(gh pr view --json number --jq .number)"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT

# A hidden marker naming the commit, so a re-run can find the comment it already
# posted. It is the first line of the body precisely so the lookup below can
# match on a first line alone, without pulling whole comment bodies through a
# shell variable.
marker="<!-- ship:${sha} -->"

{
    echo "$marker"
    echo "🔍 **Local Codex review** — commit \`${sha:0:12}\`"
    echo
    for a in "${artifacts[@]}"; do
        persona="$(basename "$a" .md)"
        persona="${persona#"${sha}-"}"
        echo "<details><summary><strong>${persona}</strong></summary>"
        echo
        # Drop the provenance comment; it is metadata for this script, not for
        # a reader of the PR.
        tail -n +2 "$a"
        echo
        echo "</details>"
        echo
    done
} >"$body"

# One comment per commit — the whole report is a single API call, so there is no
# partial-success state to reconcile. (Posting per persona would avoid the shared
# size budget below, but a transient failure on the second call would leave the
# first posted and make re-running `ship` duplicate it.)
#
# GitHub rejects a body over 65536 characters, and nothing here is truncated:
# cutting at a byte boundary drops the tail, which is exactly where the ranked
# findings and the verdict sit. A silently-shortened review posted as a
# successful ship is worse than no comment, so an oversized report fails closed.
max_bytes=60000
if [[ "$(wc -c <"$body")" -gt "$max_bytes" ]]; then
    die "the review report is over ${max_bytes} bytes and cannot be posted intact
     truncating it would risk dropping the findings and the verdict
     post it by hand, or re-run the review to get a shorter one"
fi

# Re-read the PR head immediately before posting. Fetching the base and building
# the body takes seconds, and a push landing in that window would leave a review
# on the PR that reads as current but covers superseded code. This cannot be
# atomic with comment creation — hence the SHA in the comment header as well —
# but it closes the realistic window rather than the theoretical one.
if [[ "$(gh pr view --json headRefOid --jq .headRefOid)" != "$sha" ]]; then
    die "PR head moved while preparing the review — re-run ship"
fi

# Posting is not idempotent on its own: if GitHub creates the comment but the
# response is lost in transit, `gh` exits non-zero having already succeeded, and
# a re-run adds an identical second review. Look for this commit's marker first
# and update in place when it is there, so a re-run converges on one comment
# whether the previous attempt failed before, during, or after the write.
#
# `@tsv` keeps one comment per line — a body's own newlines are escaped — so the
# match happens here rather than in a jq filter, which is also what lets this be
# tested against a fake `gh`. Only the first line is fetched; whole bodies are
# not needed and would be megabytes on a long-running PR.
#
# A failure to read the existing comments stops the ship. Posting anyway would
# give up the very guarantee this lookup exists to provide, and a re-run costs
# nothing now that it converges.
comment_lines="$(gh api --paginate "repos/{owner}/{repo}/issues/${num}/comments" \
    --jq '.[] | [(.id | tostring), (.user.login // ""), (.body | split("\n")[0])] | @tsv')" ||
    die "could not read the PR's existing comments to check for an earlier ship
     re-run once the API is reachable"

# The marker alone does not identify *our* comment — anyone can write the same
# HTML comment, deliberately or by quoting an earlier ship. Patching a comment
# belonging to someone else would destroy their text where permissions allow it
# and fail the ship where they do not, so authorship is part of the match.
me="$(gh api user --jq .login)" ||
    die "could not determine the authenticated GitHub account
     re-run once the API is reachable"

existing_ids=()
while IFS=$'\t' read -r id author first_line; do
    # GitHub returns bodies with CRLF line endings, so the marker would never
    # compare equal without stripping the carriage return.
    if [[ "$author" == "$me" && "${first_line%$'\r'}" == "$marker" ]]; then
        existing_ids+=("$id")
    fi
done <<<"$comment_lines"

# Every match is updated, not just the first. Check-then-create is not atomic —
# GitHub offers no conditional comment creation — so two ships racing on one
# commit can both find nothing and both post. That window is narrow (one clone
# per agent, one PR per branch, ADR-0015) and its outcome is cosmetic. What
# would not be cosmetic is a duplicate that then goes stale: updating only the
# first match would leave the second showing a superseded review forever.
if [[ ${#existing_ids[@]} -gt 0 ]]; then
    echo "ship: updating ${#existing_ids[@]} existing review comment(s) for" \
        "${sha:0:12} on PR #${num}…" >&2
    for id in "${existing_ids[@]}"; do
        gh api --silent --method PATCH \
            "repos/{owner}/{repo}/issues/comments/${id}" -F "body=@${body}"
    done
else
    echo "ship: posting ${#artifacts[@]} review(s) for ${sha:0:12} to PR #${num}…" >&2
    gh pr comment "$num" --body-file "$body"
fi
echo "ship: done. Resolve or file issues for any blocker/major finding before merging." >&2
