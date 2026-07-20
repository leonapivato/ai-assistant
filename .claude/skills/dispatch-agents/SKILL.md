---
name: dispatch-agents
description: Dispatch scoped work to parallel agents in sibling clones, then verify what comes back and sequence the merges. Use when handing issues to multiple agents, briefing an agent on a lane, checking an agent's reported result, or deciding merge order across in-flight PRs.
---

# dispatch-agents

Runs the loop that begins where `find-parallel-work` stops. That skill
*proposes* lanes; this one dispatches them, checks what returns, and merges in
an order that respects contract-first.

The commands here are illustrations for an operator, not an implementation —
see §6. The judgement calls are yours, and §4 says why encoding them is a
mistake.

## 1. Preflight

**Inventory the clones.** One agent per clone (ADR-0015 §2), never a linked
worktree, never the user's primary clone — the `-*` glob excludes it:

```bash
for d in ~/projects/ai-assistant-*; do
  printf '%s: %s %s dirty\n' "$d" "$(git -C "$d" branch --show-current)" \
    "$(git -C "$d" status --porcelain | wc -l)"
done
```

A clone is free only if it is on `main` **and** clean. Uncommitted work in a
clone sitting on `main` is someone's in-progress change; dispatching there
sweeps it into the agent's branch or loses it. A clone with no `.venv` needs
`just setup` first — say so in the brief rather than letting the agent find out.

**Assign ADR numbers yourself.** ADR-0015 §5 makes this the dispatcher's job, to
remove the race a shared ledger could not arbitrate. A number is claimed when a
lane starts, not when it merges, so `main` alone is never enough:

```bash
git fetch origin --prune
git ls-tree origin/main docs/adr/ --name-only                    # merged
for r in $(git for-each-ref --format='%(refname)' refs/remotes/origin); do
  git ls-tree "$r" docs/adr/ --name-only                         # unmerged
done | sort -u
```

Assign **one above the highest number any source mentions**, and never fill a
gap — an absent number below the maximum is a live claim whose file is not
written yet. Branch names need not contain the number
(`tools/tooldefinition-registry` carried ADR-0016), so your own record of what
you handed out is the primary source; the scan only catches what predates you.

## 2. Write the brief

An under-specified brief is the largest source of rework. Each one carries:

- **The clone path**, and that other clones are off-limits.
- **A scope fence** — which directories this lane may touch and which it may
  not, naming the lane that owns each excluded one. `core/protocols.py` and
  `core/types.py` are the highest-collision surface; one lane holds them at a
  time.
- **Corrections to stale issue text.** An issue written before a decision landed
  will instruct against it. Read it before dispatching and say which parts no
  longer apply — an agent that follows a stale issue faithfully has still done
  the wrong work.
- **The ADR number, or that none is needed.** Never let an agent pick one.
- **Cross-lane interactions** in both directions: what this lane will see if
  another merges first, and what it must not assume.
- **The finishing loop** — full gate, `just review-codex`, triage, `just ship`,
  `gh pr ready` — and that the agent owns all of it without asking.
- **Fetch and rebase before gating *and* before reviewing.** A gate against a
  stale tree is not evidence, and Codex reads the working tree for context, so a
  stale branch makes it report other lanes' merged work as regressions.

Say what the report must contain: PR number, what was verified and at which
commit, what was waived and why, what was filed.

## 3. Verify every report — assume nothing

Reports are written from the agent's belief, which can be stale or wrong.
Reported status has been contradicted by CI. Check the thing, not the claim:

```bash
sha=$(gh pr view <n> --json headRefOid --jq .headRefOid)
gh pr checks <n>                      # not the reported gate result
gh pr view <n> --json isDraft,mergeable,mergeStateStatus,reviewDecision
gh pr diff <n> --name-only            # scope claims: did it touch what it said?
gh pr view <n> --json comments --jq '.comments[].body' | grep -c "ship:$sha"
```

`mergeStateStatus: BEHIND` means it was never gated against current `main`.
Scope claims ("no `core/` change") are one command to confirm and have been
wrong. The last line is the one nothing else covers: green CI and a clean diff
say nothing about whether `just review-codex` and `just ship` ever ran, and a
report claiming both is not evidence that either did. `ship.sh` tags its comment
with the SHA it reviewed, so no tag for the current head means no review of the
current head.

**Before merging, diff the open PRs against each other** — two lanes editing one
file is invisible in either PR alone:

```bash
for p in $(gh pr list --state open --json number --jq '.[].number'); do
  gh pr diff "$p" --name-only | sed "s|^|$p |"
done | sort -k2 | uniq -f1 -D
```

## 4. Adjudicate escalations — do not encode the answers

When an agent stops on a conflict between authorities, resolve it from the
texts. Read the actual lines before ruling; agents cite these from memory and
misquote them.

Authority runs: **ADRs and `CLAUDE.md`'s golden rules > `CONTRIBUTING.md` > a
reviewer's opinion.** `CONTRIBUTING.md` is ratified by ADR-0003, so an ADR
outranks it. A brief outranks neither — if yours conflicts with one, that is
your error to fix, not the agent's to follow.

Deliberately not encoded: the rulings themselves. Two waivers that look alike
resolve opposite ways when the governing authority differs — one structural
finding against `CONTRIBUTING.md` was correctly overruled and the next correctly
upheld. A skill that pre-decided them would be wrong half the time with full
confidence.

## 5. Merge

**A contract ADR merges before its implementation** (golden rule 5, ADR-0015 §5).
Where a lane split into an ADR PR and an implementation PR, the order is
load-bearing, and admin bypass makes merging out of order easy.

**Bypassing review is not bypassing the gate.** Merging past a required human
review is the operator's call; merging past `BEHIND` skips *evidence*.

```bash
sha=$(gh pr view <n> --json headRefOid --jq .headRefOid)
gh pr checks <n> --watch --fail-fast || exit 1
[ "$(gh pr view <n> --json mergeStateStatus --jq .mergeStateStatus)" = BEHIND ] && exit 1
gh pr merge <n> --rebase --admin --delete-branch --match-head-commit "$sha"
```

Each line guards a different hole. `--watch`: bare `gh pr checks` exits
immediately while checks are *pending*, reporting "no checks reported yet" so
the merge proceeds anyway. The `BEHIND` recheck: `main` can land another PR
while yours is being checked, and `--admin` will merge the now-stale branch.
`--match-head-commit`: an agent pushing in the same window gets its commit
admin-merged unreviewed.

**A rebase invalidates the review record.** `just ship` anchors a review to a
commit (ADR-0015 §1), so `gh pr update-branch --rebase` produces a head nothing
has reviewed, and `--admin` merges it regardless. Branch protection is `strict`,
so a stale branch must be updated before it can merge — the two rules pull
against each other, and the resolution is ordering. Merge while the branch is
current. Where an update is unavoidable, the new SHA needs its own gate, review
and ship.

Rebase-merge only; the repo forbids squash and merge commits.

**Renaming a clone breaks its `.venv`** (absolute paths): `rm -rf .venv && just
setup` after. Never rename a clone an agent is running in.

## 6. Watch the cost

Parallelism is capped by clones deliberately (ADR-0015 Consequences): nothing
detects two agents colliding, so lane separation is the dispatcher's job and
does not scale by adding agents. The dominant cost is agent tokens and the
dominant waste is rework from a thin brief — prefer fewer, larger, well-fenced
lanes.

**These commands are illustrations, not an implementation.** Extracting them
into tested scripts has been proposed and is declined: that is the
`claim-workspace.sh` shape ADR-0015 deleted — ~856 lines of shell plus ~1,770
of shell tests — whose `fix(dev)` commits dominated the history. Adversarial
review will keep proposing hardening for conditions this repo does not have
(hundreds of open PRs, hostile concurrent pushes); harden the two or three
paths that have actually failed and leave the rest as prose. If this file needs
its own test suite, it has become the thing ADR-0015 removed.
