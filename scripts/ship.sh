#!/usr/bin/env bash
# Report the local Codex review to the pull request — the merge-readiness step
# (ADR-0015 §1).
#
# Review runs locally now, so the PR record depends on someone pasting it. This
# script is that paste, with the forgettable parts checked rather than trusted:
# it refuses unless a review artifact exists whose recorded *base* and *tree*
# both match the PR's current merge base and HEAD's tree (ADR-0020 §3). The
# common failure under a paste-it-yourself norm is a review of stale content —
# that one is mechanical.
#
# The anchor used to be the exact commit SHA (ADR-0015 §1). Content is the
# stricter thing to check and the cheaper one to satisfy: a review taken against
# different content, or a different base, still fails exactly as before, while a
# commit that changes no reviewed byte — an amended message, a squash, an
# in-place rebase, a revert back to a reviewed tree — no longer forces a fresh
# round. What is *not* relaxed: an adversarial record is still required, and the
# architecture lens is still required for a change touching the contract surface.
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
core_change=0
if grep -qE '^src/ai_assistant/core/(protocols|types)\.py$' <<<"$changed_files"; then
    core_change=1
fi

# --- Which reviews cover this PR (ADR-0020 §3) -------------------------------
#
# An artifact is accepted when its recorded *base* and its recorded *tree* both
# match this PR's current merge base and HEAD's tree — whatever commit it is
# filed under. Two independent conditions, and both are load-bearing:
#
#   tree: the content reviewed. A scope cut, a fixup, any real edit changes it,
#         so a review of different content is refused exactly as before. This is
#         what makes the commit SHA safe to stop matching on: an amended message,
#         a squash, an in-place rebase, or a revert back to a reviewed tree
#         changes the commit but not one reviewed byte.
#   base: the left edge of the range. A review run against a narrower base
#         (`just review-codex adversarial HEAD~1`) covers only part of the PR,
#         and a rebase onto moved origin/main genuinely changes the diff. Both
#         still force a fresh review.
#
# Dropping either check would be a real loss of the guarantee, not a
# simplification: the tree alone would accept a review of the same content
# against a different base, and the base alone would accept a review of code
# that has since changed.
expected_base="$(git merge-base FETCH_HEAD "$sha")"
head_tree="$(git rev-parse "${sha}^{tree}")"

declare -A covering=()
# Why an artifact was rejected, so the failure message can distinguish "content
# moved" from "base moved". The ADR flags this explicitly: a single generic
# error would be misread as the old stale-commit one.
saw_tree_mismatch=0
saw_base_mismatch=0
saw_unreadable=0

shopt -s nullglob
for a in .review/*.md; do
    provenance="$(head -n 1 "$a")"
    recorded_base="$(sed -n 's/.*base_sha=\([0-9a-f]*\).*/\1/p' <<<"$provenance")"
    # The leading space matters: it pins the field name to `tree=` and stops a
    # future `<something>_tree=` field from being read as this one.
    recorded_tree="$(sed -n 's/.* tree=\([0-9a-f]*\).*/\1/p' <<<"$provenance")"

    # An artifact predating ADR-0020 records no tree, so its content cannot be
    # verified at all. Fail closed: unverifiable is not the same as matching,
    # and re-running a review costs one round where accepting this costs the
    # guarantee. Same for a hand-edited or truncated provenance line.
    if [[ -z "$recorded_base" || -z "$recorded_tree" ]]; then
        saw_unreadable=1
        continue
    fi
    if [[ "$recorded_tree" != "$head_tree" ]]; then
        saw_tree_mismatch=1
        continue
    fi
    if [[ "$recorded_base" != "$expected_base" ]]; then
        saw_base_mismatch=1
        continue
    fi

    # `<sha>-<persona>.md`; personas carry no dash, so the last field is it.
    name="$(basename "$a" .md)"
    persona="${name##*-}"
    # Several commits can legitimately carry a review of this same tree — that
    # is the point of the change. Prefer the one filed under the current HEAD
    # when it exists, so the common case posts the artifact whose filename
    # matches the PR head and a reader sees no discrepancy.
    if [[ -z "${covering[$persona]:-}" || "$name" == "${sha}-${persona}" ]]; then
        covering["$persona"]="$a"
    fi
done
shopt -u nullglob

# The reason each refusal names, appended to whichever requirement fails below.
why=""
if [[ "$saw_tree_mismatch" == "1" ]]; then
    why="${why}
     a review exists for *different content* — the change moved since it was
     reviewed, so it needs a fresh one (this is not the old stale-commit error:
     amending or squashing without editing content no longer costs a round)"
fi
if [[ "$saw_base_mismatch" == "1" ]]; then
    why="${why}
     a review exists against a *different base* — the branch was rebased onto a
     moved '${base_ref}', or the review was run with a narrower base, so it does
     not cover this PR's full diff"
fi
if [[ "$saw_unreadable" == "1" ]]; then
    why="${why}
     a review exists with no recorded base/tree — it predates ADR-0020 or was
     edited, so its content cannot be verified"
fi

# Adversarial is the required lens before merge. ADR-0020 relaxes neither this
# nor the architecture requirement below; it changes only what counts as a
# review of *this* content.
if [[ -z "${covering[adversarial]:-}" ]]; then
    die "no adversarial review covering this PR's content
     (HEAD tree ${head_tree:0:12}, base ${expected_base:0:12})${why}
     run: just review-codex adversarial"
fi

# A change to the shared contract surface needs the architecture lens too
# (CONTRIBUTING, "Contract ADRs land before their implementation").
if [[ "$core_change" == "1" && -z "${covering[architecture]:-}" ]]; then
    die "this change touches core/protocols.py or core/types.py, so it needs
     the architecture lens as well as the adversarial one${why}
     run: just review-codex architecture"
fi

# Posting order is fixed rather than glob order, so the comment reads the same
# way every time regardless of which commits the artifacts happen to be under.
artifacts=()
for persona in adversarial architecture; do
    [[ -n "${covering[$persona]:-}" ]] && artifacts+=("${covering[$persona]}")
done
for persona in "${!covering[@]}"; do
    case "$persona" in
    adversarial | architecture) ;;
    *) artifacts+=("${covering[$persona]}") ;;
    esac
done

# Re-check the verdict here, not just when recording. A base and a tree say what
# an artifact covers, not that it holds a finished review: a file truncated by an
# interrupt, or edited by hand, keeps valid metadata while losing its body. ship
# is the last point before this becomes the record, so it verifies rather than
# trusts.
for a in "${artifacts[@]}"; do
    a_last="$(grep -v '^[[:space:]]*$' "$a" | tail -n 1 |
        tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    if ! grep -qiE '^verdict:?[[:space:]]*(block|approve with nits|approve)\.?$' <<<"$a_last"; then
        name="$(basename "$a" .md)"
        die "$(basename "$a") does not end in a verdict — it is incomplete
     re-run: just review-codex ${name##*-}"
    fi
done

num="$(gh pr view --json number --jq .number)"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT

# The two lines that identify a ship comment: a hidden marker naming the commit,
# then the visible header. They lead the body precisely so the lookup below can
# recognise a comment from its opening lines alone, without pulling whole comment
# bodies through a shell variable.
marker="<!-- ship:${sha} -->"
header="🔍 **Local Codex review** — commit \`${sha:0:12}\`"

# The aggregate the author saw when the review ran (ADR-0020 §2), rendered into
# the comment rather than left in the provenance line — `tail -n +2` below strips
# that line, so without this the merge reviewer would never see the numbers. The
# whole point is that the human at merge holds the same aggregate view the author
# had; in both runaway cases in issue #91 it was an outside observer holding
# exactly this that ended the loop.
adversarial_provenance="$(head -n 1 "${covering[adversarial]}")"
agg_field() { sed -n "s/.* $1=\([^ ]*\).*/\1/p" <<<"$adversarial_provenance"; }
agg_round="$(agg_field round)"
agg_net="$(agg_field net_lines)"
agg_churn="$(agg_field churn_lines)"
agg_ratio="$(agg_field churn_ratio)"
agg_commits="$(agg_field commits)"
agg_supersedes="$(agg_field supersedes)"

{
    echo "$marker"
    echo "$header"
    echo
    # Older artifacts carry no aggregate; omit the line rather than print blanks.
    if [[ -n "$agg_round" ]]; then
        summary="round ${agg_round} · ${agg_net} lines net"
        [[ -n "$agg_commits" ]] && summary="${summary} across ${agg_commits} commit(s)"
        [[ -n "$agg_ratio" ]] && summary="${summary} · churn ${agg_ratio}× (${agg_churn} touched)"
        if [[ -n "$agg_supersedes" ]]; then
            # `ADR-0004:175,ADR-0012:98` → `ADR-0004 (175 lines), ADR-0012 (98 lines)`
            pretty="$(sed 's/:\([0-9]*\)/ (\1 lines)/g; s/,/, /g' <<<"$agg_supersedes")"
            summary="${summary} · supersedes ${pretty}"
        fi
        echo "_${summary}_"
        echo
    fi
    for a in "${artifacts[@]}"; do
        name="$(basename "$a" .md)"
        persona="${name##*-}"
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

# Posting is not idempotent on its own: if GitHub creates the comment but the
# response is lost in transit, `gh` exits non-zero having already succeeded, and
# a re-run adds an identical second review. Look for this commit's comment first
# and update in place when it is there, so a re-run converges on one comment
# whether the previous attempt failed before, during, or after the write.
#
# `@tsv` keeps one comment per line — a body's own newlines are escaped — so the
# match happens here rather than in a jq filter, which is also what lets this be
# tested against a fake `gh`. Only the opening two lines are fetched; whole
# bodies are not needed and would be megabytes on a long-running PR.
#
# A failure to read the existing comments stops the ship. Posting anyway would
# give up the very guarantee this lookup exists to provide, and a re-run costs
# nothing now that it converges.
comment_lines="$(gh api --paginate "repos/{owner}/{repo}/issues/${num}/comments" \
    --jq '.[] | [(.id | tostring), (.user.login // ""),
        (.body | split("\n")[0]), (.body | split("\n")[1] // "")] | @tsv')" ||
    die "could not read the PR's existing comments to check for an earlier ship
     re-run once the API is reachable"

# The marker alone does not identify *our* comment — it is public text anyone can
# write or quote. Patching on it alone would destroy someone else's comment where
# permissions allow it and fail the ship where they do not. Two further
# conditions narrow the match: the comment must be authored by this account, and
# it must carry ship's own header on the line after the marker.
#
# A byte-identical forgery still matches, and nothing short of server-side state
# this script deliberately does not keep would catch that. What is closed is the
# case that actually happens — a comment quoting or mentioning a ship marker.
me="$(gh api user --jq .login)" ||
    die "could not determine the authenticated GitHub account
     re-run once the API is reachable"

existing_ids=()
while IFS=$'\t' read -r id author line1 line2; do
    # GitHub returns comment bodies with CRLF line endings, so every line
    # arrives with a trailing carriage return and would never compare equal.
    # `@tsv` encodes that CR as the two characters `\` and `r` — it cannot emit
    # a raw one without breaking the one-record-per-line format — so what is
    # stripped here is the escape, not a control byte.
    if [[ "$author" == "$me" && "${line1%'\r'}" == "$marker" &&
        "${line2%'\r'}" == "$header" ]]; then
        existing_ids+=("$id")
    fi
done <<<"$comment_lines"

# Re-read the PR head immediately before writing. Fetching the base, building the
# body, and reading the PR's comments all take seconds, and a push landing in
# that window would leave a review on the PR that reads as current but covers
# superseded code. This check sits after the lookup for that reason: everything
# between it and the write must be the write itself. It cannot be atomic with
# comment creation — hence the SHA in the comment header as well — but it closes
# the realistic window rather than the theoretical one.
if [[ "$(gh pr view --json headRefOid --jq .headRefOid)" != "$sha" ]]; then
    die "PR head moved while preparing the review — re-run ship"
fi

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
