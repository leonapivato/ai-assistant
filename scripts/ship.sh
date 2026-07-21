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
saw_persona_mismatch=0

# The lenses ship knows about. This is the whole set: `adversarial` is required
# before merge and `architecture` on top of it for a contract change, and an
# artifact naming anything else satisfies neither requirement — so rather than
# posting it under a heading that claims a lens nobody defined, refuse it.
# Adding a third persona means adding it here as well as writing its rubric.
declare -A known_persona=([adversarial]=1 [architecture]=1)

# Read one provenance field. The value is captured up to the next space rather
# than as "however many hex characters happen to follow", because `[0-9a-f]*`
# silently *stops* at the first non-hex byte: `base_sha=<expected>junk` would
# capture exactly the expected hash and compare equal, accepting an artifact
# whose recorded field is not the hash at all. Capturing the whole token means a
# malformed field mismatches and fails closed, which is what the comment below
# promises. The leading space also pins the field name, so `base_sha=` can never
# be read as `sha=` and a future `<x>_tree=` can never be read as `tree=`.
provenance_field() {
    sed -n "s/.*[[:space:]]$1=\([^[:space:]]*\).*/\1/p" <<<"$2"
}

# The closing line every genuine review carries (docs/review/guide.md). Matched
# against the *last non-blank line*, not anywhere in the body: a substring search
# accepts prose that merely mentions the words, e.g. "I cannot provide a verdict
# or APPROVE this change". Markdown emphasis is stripped first, since the
# reviewer writes "**Verdict: X**", "Verdict: X" and "VERDICT: X" interchangeably.
#
# The `Verdict:` label is optional: docs/review/guide.md asks only for "a
# one-line verdict: BLOCK, APPROVE WITH NITS, or APPROVE", so a bare
# `APPROVE WITH NITS` conforms and must not be read as an incomplete artifact
# (issue #120). Kept deliberately identical to the same test in
# codex-review.sh — one records the artifact and the other refuses to post an
# incomplete one, so a review the recorder accepts and the shipper rejects would
# strand a valid review with no way to ship it.
#
# A verdict alone does not count, for the same reason the recorder rejects one:
# the rubric's anti-patterns forbid rubber-stamping, and an artifact whose only
# non-blank body line is the verdict carries no findings and no statement of
# what was checked. Line 1 is the provenance comment and is not body — the same
# line `tail -n +2` strips before posting.
artifact_has_verdict() {
    local last body_lines
    last="$(grep -v '^[[:space:]]*$' "$1" | tail -n 1 |
        tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    grep -qiE '^(verdict:?[[:space:]]*)?(block|approve with nits|approve)\.?$' <<<"$last" ||
        return 1
    body_lines="$(tail -n +2 "$1" | grep -c -v '^[[:space:]]*$' || true)"
    [[ "$body_lines" -ge 2 ]]
}

# --- Disposition snapshots (ADR-0025 §4) -------------------------------------
#
# A persistent review round records a per-finding disposition SNAPSHOT of the
# state it reviewed, named by the full anchor `<loop_id>-<persona>-<tree>.md`.
# ship publishes the snapshot belonging to the terminal artifact's tree so the
# merge reviewer can read the verdict-changing history — which findings were
# retired, and across which rounds — not only the terminal verdict.

# The snapshot for a terminal artifact, selected by the full anchor
# (loop_id, persona, tree). Echoes the path, or nothing when the artifact carries
# no loop_id — a bypass or pre-ADR-0025 artifact, which has no persistent-session
# dispositions to publish. An artifact that DOES carry a loop_id is a persistent
# round and must have its anchored snapshot: a missing one fails closed rather
# than posting the verdict with no disposition evidence (e.g. a snapshot write
# that failed). Fails closed too on ambiguity (more than one loop recorded a
# snapshot for the same content) or a loop mismatch (the snapshot found is not
# the loop the artifact names — a stale snapshot from another path). $1 persona,
# $2 tree, $3 the artifact's recorded loop_id.
disposition_snapshot() {
    local persona="$1" tree="$2" want="$3" f lid
    # No loop_id: not a persistent artifact, so nothing to select. Requiring a
    # non-empty match below is what closes the stale-snapshot case a bypass
    # artifact would otherwise pick up.
    [[ -n "$want" ]] || return 0
    local -a matches=()
    local -A loops=()
    shopt -s nullglob
    for f in .review/dispositions/*-"${persona}-${tree}".md; do
        lid="$(provenance_field loop_id "$(head -n 1 "$f")")"
        [[ -n "$lid" ]] || continue
        loops["$lid"]=1
        [[ "$lid" == "$want" ]] && matches+=("$f")
    done
    shopt -u nullglob
    if [[ ${#loops[@]} -gt 1 ]]; then
        die "ambiguous disposition snapshots for ${persona} tree ${tree:0:12}:
     ${#loops[@]} loops recorded one for the same content, so which belongs beside
     this verdict cannot be determined (ADR-0025 §4). Clear stale
     .review/dispositions/ and re-run the review."
    fi
    if [[ ${#matches[@]} -eq 0 ]]; then
        die "the review artifact for ${persona} tree ${tree:0:12} is a persistent
     round (loop ${want}) but its anchored disposition snapshot is missing —
     refusing to post a verdict with no disposition evidence (ADR-0025 §4).
     Re-run: just review-codex ${persona}"
    fi
    printf '%s\n' "${matches[0]}"
}

# Each finding's header fields as `id<TAB>severity<TAB>status<TAB>first<TAB>last`.
snapshot_finding_lines() {
    sed -n 's/.*<!-- finding id=\([^ ]*\) severity=\([^ ]*\) status=\([^ ]*\) first_round=\([^ ]*\) last_round=\([^ ]*\) -->.*/\1\t\2\t\3\t\4\t\5/p' "$1"
}

# The verbatim text of one finding (between its header and terminator).
snapshot_finding_text() {
    awk -v id="$2" '
        $0 ~ ("<!-- finding id=" id " ") { g = 1; next }
        g && /<!-- \/finding -->/ { g = 0 }
        g { print }
    ' "$1"
}

# Whether a proposal carries a plausible secret (a key Codex may have read from an
# ignored file like .env). Deliberately broad and fail-toward-exclude: a false
# positive costs one finding its published proposal (it takes ordinary review), a
# false negative would publish a secret. $1 the text to scan.
contains_secret() {
    grep -qiE '(-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|gh[posur]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|(api[_-]?key|secret|password|passwd|token|bearer)[[:space:]]*[=:][[:space:]]*[^[:space:]]{6,})' <<<"$1"
}

# Replaces every fenced block (a Codex proposal patch) with a marker, so an
# excluded proposal is dropped rather than truncated or redacted in place. Any
# ``` line toggles the fence, so the block is removed whatever its language label.
strip_proposal_fences() {
    awk '
        /^[[:space:]]*```/ {
            if (infence) { infence = 0 } else { infence = 1; print "> _(Codex proposal excluded — see note)_" }
            next
        }
        !infence { print }
    ' <<<"$1"
}

# Renders a disposition snapshot into a collapsible section, bounded by a
# cumulative published-byte budget so a long loop cannot exceed ship's comment
# limit (ADR-0025 §4). A §3 Codex proposal is the exception: it appears in full,
# unless it cannot be published exactly and safely (too large, or carrying a
# secret), in which case it is excluded — not truncated — and that finding takes
# ordinary review, fail-closed. $1 snapshot path, $2 persona.
render_dispositions() {
    local snap="$1" persona="$2"
    local budget="${CODEX_SHIP_DISPOSITION_BUDGET:-20000}"
    local total used=0 hidden=0
    total="$(grep -c '<!-- finding id=' "$snap" || true)"
    [[ "${total:-0}" -eq 0 ]] && return 0

    echo "<details><summary><strong>${persona} — dispositions (${total} finding(s))</strong></summary>"
    echo
    echo "_Per-finding disposition record from the persistent review session"
    echo "(ADR-0025 §4). A **retired** finding was raised in an earlier round and,"
    echo "after the reviewer's own reassessment, not re-raised — the auditable"
    echo "evidence that a verdict changed._"
    echo
    local id sev status first last text note is_proposal has_fence entry entry_bytes
    while IFS=$'\t' read -r id sev status first last; do
        [[ -n "$id" ]] || continue
        text="$(snapshot_finding_text "$snap" "$id")"
        note=""
        is_proposal=0
        has_fence=0
        grep -qiE '^[[:space:]]*```' <<<"$text" && has_fence=1
        # The secret scan covers the WHOLE finding, not only a labelled proposal
        # fence: a key Codex read from an ignored file could sit in prose or in a
        # `python`/unlabelled fence too. If any is found, the entire finding text
        # is excluded — not redacted in place — so publishing never leaks it, and
        # that finding takes ordinary independent review (ADR-0025 §3, fail-closed).
        if contains_secret "$text"; then
            text="_(finding content excluded — see note)_"
            note="  "$'\n'"> ⚠ **Content excluded** — this finding may carry a secret, so it is not published; it takes ordinary independent review (ADR-0025 §3, fail-closed)."
        elif [[ "$has_fence" -eq 1 && "$(printf '%s' "$text" | wc -c)" -gt "$budget" ]]; then
            text="$(strip_proposal_fences "$text")"
            note="  "$'\n'"> ⚠ **Codex proposal excluded** — too large to publish in full; this finding takes ordinary independent review (ADR-0025 §3, fail-closed)."
        elif [[ "$has_fence" -eq 1 ]]; then
            # A proposal (any fenced block) appears in full, never bounded away.
            is_proposal=1
        fi
        entry="$(printf -- '- **%s** — _%s_ (rounds %s–%s)\n\n%s\n%s\n' \
            "$sev" "$status" "$first" "$last" "$text" "$note")"
        entry_bytes="$(printf '%s' "$entry" | wc -c)"
        if [[ "$is_proposal" -eq 0 && $((used + entry_bytes)) -gt "$budget" ]]; then
            hidden=$((hidden + 1))
            continue
        fi
        printf '%s\n\n' "$entry"
        used=$((used + entry_bytes))
    done < <(snapshot_finding_lines "$snap")
    if [[ "$hidden" -gt 0 ]]; then
        echo "_…${hidden} more finding(s) omitted to stay within the published-size"
        echo "budget; the complete record is in \`.review/dispositions/\` (local)._"
        echo
    fi
    echo "</details>"
    echo
}

declare -A covering_rank=()

shopt -s nullglob
for a in .review/*.md; do
    provenance="$(head -n 1 "$a")"
    recorded_base="$(provenance_field base_sha "$provenance")"
    recorded_tree="$(provenance_field tree "$provenance")"
    recorded_persona="$(provenance_field persona "$provenance")"

    # `<sha>-<persona>.md`; personas carry no dash, so the last field is it.
    name="$(basename "$a" .md)"
    persona="${name##*-}"

    # An artifact predating ADR-0020 records no tree, so its content cannot be
    # verified at all. Fail closed: unverifiable is not the same as matching,
    # and re-running a review costs one round where accepting this costs the
    # guarantee. Same for a hand-edited or truncated provenance line. The
    # persona field has been recorded since the artifact was introduced, so an
    # artifact old enough to lack it lacks the tree too and fails here anyway.
    if [[ -z "$recorded_base" || -z "$recorded_tree" || -z "$recorded_persona" ]]; then
        saw_unreadable=1
        continue
    fi

    # Which lens ran is the one claim ship makes on the artifact's behalf, and
    # until now it read that claim off the *filename* alone — so an architecture
    # artifact renamed to `<sha>-adversarial.md` satisfied the mandatory
    # adversarial requirement without that lens ever having run (issue #99).
    # The field the reviewer recorded is the claim; the filename is a label
    # anyone can retype. Require them to agree, and require the result to be a
    # lens this script actually knows.
    #
    # This does not make the artifact tamper-proof and does not try to be — a
    # forged file can set both. It closes the case where the two disagree, which
    # is the one a rename produces, and it is nearly free because the field was
    # already being recorded.
    if [[ "$recorded_persona" != "$persona" || -z "${known_persona[$persona]:-}" ]]; then
        saw_persona_mismatch=1
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

    # Several commits can legitimately carry a review of this same tree — that is
    # the point of the change — so pick between them deterministically rather
    # than taking whichever the glob yielded first.
    #
    # Completeness outranks being filed under HEAD. Selecting an incomplete
    # artifact while a valid one covers the same tree would refuse the ship on
    # the strength of a file the author has already superseded; the verdict check
    # below is a test of the *review*, not a way to lose one. Among equals,
    # prefer the artifact named for the current commit, so a reader comparing the
    # posted comment against the PR head sees no discrepancy.
    rank=0
    if artifact_has_verdict "$a"; then
        rank=2
    fi
    if [[ "$name" == "${sha}-${persona}" ]]; then
        rank=$((rank + 1))
    fi
    if [[ -z "${covering[$persona]:-}" || "$rank" -gt "${covering_rank[$persona]}" ]]; then
        covering["$persona"]="$a"
        covering_rank["$persona"]="$rank"
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
     a review exists with no recorded persona/base/tree — it predates ADR-0020
     or was edited, so what it covers cannot be verified"
fi
if [[ "$saw_persona_mismatch" == "1" ]]; then
    why="${why}
     a review exists whose recorded persona does not match its filename, or
     names a lens this script does not know — the filename is not evidence that
     a lens ran, so run the review it claims rather than renaming the record"
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
# Enumerating the known personas is exhaustive: the loop above rejects anything
# outside `known_persona`, so nothing else can be in `covering` to be missed.
artifacts=()
for persona in adversarial architecture; do
    [[ -n "${covering[$persona]:-}" ]] && artifacts+=("${covering[$persona]}")
done

# Re-check the verdict here, not just when recording. A base and a tree say what
# an artifact covers, not that it holds a finished review: a file truncated by an
# interrupt, or edited by hand, keeps valid metadata while losing its body. ship
# is the last point before this becomes the record, so it verifies rather than
# trusts.
for a in "${artifacts[@]}"; do
    if ! artifact_has_verdict "$a"; then
        name="$(basename "$a" .md)"
        die "$(basename "$a") does not end in a verdict — it is incomplete
     re-run: just review-codex ${name##*-}"
    fi
done

# Resolve each artifact's disposition snapshot by the full anchor now, before
# building the body, so an ambiguity or a loop mismatch fails the ship closed
# rather than after posting (ADR-0025 §4).
declare -A snapshot=()
for a in "${artifacts[@]}"; do
    prov="$(head -n 1 "$a")"
    a_persona="$(provenance_field persona "$prov")"
    a_tree="$(provenance_field tree "$prov")"
    a_loop="$(provenance_field loop_id "$prov")"
    snap="$(disposition_snapshot "$a_persona" "$a_tree" "$a_loop")"
    [[ -n "$snap" ]] && snapshot["$a_persona"]="$snap"
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
# Both are absent from artifacts recorded before they existed, and `binary_files`
# is absent whenever the diff has no binary path at all — so each is rendered
# only when present, never as a zero or an "exact" the reader has to discount.
agg_bound="$(agg_field churn_bound)"
agg_binary="$(agg_field binary_files)"
# Binary work can be absent from the net diff and still be work the branch did —
# added in one commit, reverted in a later one. Carried separately for that
# reason, so the caveat the author saw is not lost on the way to the PR.
agg_binary_churn="$(agg_field binary_churn)"

{
    echo "$marker"
    echo "$header"
    echo
    # Older artifacts carry no aggregate; omit the line rather than print blanks.
    if [[ -n "$agg_round" ]]; then
        summary="round ${agg_round} · ${agg_net} lines net"
        [[ -n "$agg_commits" ]] && summary="${summary} across ${agg_commits} commit(s)"
        if [[ -n "$agg_binary" ]]; then
            summary="${summary} + ${agg_binary} binary file(s) unmeasured"
        fi
        if [[ -n "$agg_ratio" ]]; then
            # A churn figure computed after a squash, amend or rebase counts only
            # the work still on the branch, so it is a floor rather than a
            # measurement. The merge reviewer has to see that distinction or the
            # number reads as "little rework happened" on precisely the branch
            # that was reworked enough to be worth squashing (issue #97).
            #
            # `n/a` is not a ratio, so it takes neither the `≥` nor the `×` — a
            # diff with no measurable text lines (a binary-only or rename-only
            # state) reports no ratio at all, and `churn ≥n/a×` would be noise
            # in the one line that exists to be read at a glance. The
            # rewritten-history caveat still applies and is stated on its own.
            if [[ "$agg_ratio" == "n/a" ]]; then
                summary="${summary} · churn n/a (${agg_churn} touched)"
                if [[ "$agg_bound" == "lower" ]]; then
                    summary="${summary} · history rewritten, earlier rounds not counted"
                fi
            elif [[ "$agg_bound" == "lower" ]]; then
                summary="${summary} · churn ≥${agg_ratio}× (${agg_churn} touched;"
                summary="${summary} lower bound — history rewritten, earlier rounds not counted)"
            else
                summary="${summary} · churn ${agg_ratio}× (${agg_churn} touched)"
            fi
            if [[ -n "$agg_binary_churn" ]]; then
                summary="${summary} + ${agg_binary_churn} binary change(s) unmeasured"
            fi
        fi
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
        # The verdict-changing evidence: the per-finding dispositions belonging to
        # this terminal artifact's tree (ADR-0025 §4). Rendered into the published
        # comment so it reaches the merge reviewer, not only git-ignored .review/.
        if [[ -n "${snapshot[$persona]:-}" ]]; then
            render_dispositions "${snapshot[$persona]}" "$persona"
        fi
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
#
# The loop is not atomic — GitHub has no multi-comment write — so a failure part
# way through leaves the PR showing this review on one comment and a superseded
# one on another. Two things follow, and they are what issue #76 asked for.
#
# First, a failed PATCH does not abort the rest. Under a bare `set -e` the first
# failure stops the loop, so a transient error on the first of three comments
# leaves the other two stale as well — the script gives up on comments it had
# every chance to fix. Attempting all of them makes the divergence as small as
# the failures actually were.
#
# Second, the exit names which comments were written and which were not, rather
# than surfacing gh's bare error. The state is self-healing — a re-run finds
# every comment for this commit and rewrites all of them — but only if the
# operator can see that a re-run is what is needed, and where to look.
#
# What the message deliberately does *not* say is that a failed comment is
# stale. A non-zero PATCH does not prove the write was not applied: the request
# can succeed and its response be lost, exactly the ambiguity this script
# already documents for comment creation below. Reporting "showing a superseded
# review" would be a claim ship cannot support, and re-reading the comments to
# find out would add a round of API calls to the path where the API is already
# failing. Naming the uncertainty is both honest and sufficient, because the
# recovery for either case is the same re-run.
#
# Retrying in-process was the other option the issue offered and is not taken:
# a retry without backoff buys almost nothing against the failures that actually
# happen (auth, rate limit, network down), and a re-run of ship is already the
# correct and tested recovery.
if [[ ${#existing_ids[@]} -gt 0 ]]; then
    echo "ship: updating ${#existing_ids[@]} existing review comment(s) for" \
        "${sha:0:12} on PR #${num}…" >&2
    updated_ids=()
    failed_ids=()
    for id in "${existing_ids[@]}"; do
        if gh api --silent --method PATCH \
            "repos/{owner}/{repo}/issues/comments/${id}" -F "body=@${body}"; then
            updated_ids+=("$id")
        else
            failed_ids+=("$id")
        fi
    done
    if [[ ${#failed_ids[@]} -gt 0 ]]; then
        # `${arr[*]}` rather than `${arr[@]}`: one space-joined string for the
        # message, and both arrays are known non-empty on the branches that read
        # them, so `set -u` has nothing to trip on.
        updated_desc="none"
        if [[ ${#updated_ids[@]} -gt 0 ]]; then
            updated_desc="${updated_ids[*]}"
        fi
        die "could not update every review comment on PR #${num}
     for commit ${sha:0:12}:
       updated:        comment(s) ${updated_desc}
       write failed:   comment(s) ${failed_ids[*]}
     the failed comment(s) may or may not have been updated — a lost response
     looks the same as a rejected request — so treat the PR as inconsistent
     until a re-run settles it
     nothing is wrong with the review itself; the write failed, not the record
     re-run: just ship — it rewrites every comment it owns for this commit, so
     a re-run converges on one current review"
    fi
else
    echo "ship: posting ${#artifacts[@]} review(s) for ${sha:0:12} to PR #${num}…" >&2
    gh pr comment "$num" --body-file "$body"
fi
echo "ship: done. Resolve or file issues for any blocker/major finding before merging." >&2
