---
name: dispatch-agents
description: Dispatch scoped work to parallel agents in sibling clones, then verify what comes back and sequence the merges. Use when handing issues to multiple agents, briefing an agent on a lane, checking an agent's reported result, or deciding merge order across in-flight PRs.
---

# dispatch-agents

Runs the loop that begins where `find-parallel-work` stops. That skill
*proposes* lanes; this one dispatches them, checks what returns, and merges in
an order that respects contract-first.

This is a dev-process tool for building `ai-assistant` itself. It covers the
mechanical parts only — the judgement calls are yours, and §4 says why encoding
them is a mistake.

## 1. Preflight

**Inventory the clones.** Agents run one per clone (ADR-0015 §2), never in
linked worktrees, and never in the user's primary clone:

```bash
for d in ~/projects/ai-assistant-*; do
  printf '%s: %s %s\n' "$d" "$(git -C "$d" branch --show-current)" \
    "$(git -C "$d" status --porcelain | wc -l) dirty"
done
```

A clone on a non-`main` branch is occupied. A clone with no `.venv` needs
`just setup` before its agent can run the gate — say so in the brief rather than
letting the agent discover it.

**Assign ADR numbers yourself.** ADR-0015 §5 makes this the dispatcher's job
precisely to remove the race a shared ledger could not arbitrate. Read *both*
sources — merged ADRs and open branches, since a number is claimed the moment a
lane starts, not when it merges:

```bash
git ls-tree origin/main docs/adr/ --name-only | tail -3
git ls-remote --heads origin | awk '{print $2}'   # branch names carry claims
```

Checking only `docs/adr/` on `main` will hand out a number another live lane is
already using.

## 2. Write the brief

An under-specified brief is the single largest source of rework. Each one
carries:

- **The clone path**, and that other clones are off-limits.
- **A scope fence** — the directories this lane may touch, and the ones it may
  not, naming the lane that owns each excluded one. `core/protocols.py` and
  `core/types.py` are the highest-collision surface; at most one lane holds them
  at a time.
- **Corrections to stale issue text.** Issues written before a decision landed
  will instruct against it. Read the issue before dispatching and say plainly
  which parts no longer apply — an agent that follows a stale issue faithfully
  has still done the wrong work.
- **The ADR number, or that none is needed.** Never let an agent pick one.
- **Cross-lane interactions**, in both directions: what this lane will see if
  another merges first, and what it must not assume.
- **The finishing loop**: full gate, `just review-codex`, triage, `just ship`,
  `gh pr ready` — and that the agent owns all of it without asking.
- **Fetch and rebase before gating *and* before reviewing.** A gate against a
  stale tree is not evidence, and Codex reads the working tree for context, so a
  stale branch makes it report other lanes' merged work as regressions.

State the deliverable you want in the report: PR number, what was verified, what
was waived and why, what was filed.

## 3. Verify every report — assume nothing

Agent reports are written from the agent's belief, which can be stale or wrong.
Reported status has been contradicted by CI more than once. Check the thing, not
the claim:

```bash
gh pr checks <n>                        # not the reported gate result
gh pr view <n> --json isDraft,mergeable,mergeStateStatus,reviewDecision
gh pr diff <n> --name-only              # scope claims: did it touch what it said?
```

- **`gh pr checks` over any reported green.** An agent that gated before
  rebasing ran a full suite that was missing the check which would have failed.
- **`mergeStateStatus: BEHIND`** means it was never gated against current
  `main`.
- **Scope claims** ("no `core/` change", "docs untouched") are one command to
  confirm and have been wrong.

**Before merging anything, diff the open PRs against each other.** Two lanes
editing one file is invisible in either PR alone:

```bash
for p in $(gh pr list --state open --json number --jq '.[].number'); do
  gh pr diff "$p" --name-only | sed "s|^|$p |"
done | sort -k2 | uniq -f1 -D
```

## 4. Adjudicate escalations — do not encode the answers

When an agent stops on a conflict between authorities, resolve it from the
texts, not from precedent or from this file. Read the actual lines before
ruling; agents cite these from memory and misquote them.

Authority runs: **ADRs > `CONTRIBUTING.md` > a reviewer's opinion.**
`CONTRIBUTING.md` is itself ratified by ADR-0003, so an ADR outranks it.

Deliberately not encoded here: the rulings themselves. Two waivers that look
alike can resolve opposite ways because the governing authority differs — one
structural finding against `CONTRIBUTING.md` was correctly overruled and the
next correctly upheld. A skill that pre-decided them would be wrong half the
time with full confidence.

## 5. Merge

- **A contract ADR merges before its implementation** (golden rule 5,
  ADR-0015 §5). Where a lane split into an ADR PR and an implementation PR, the
  order is load-bearing — admin bypass makes merging out of order easy.
- **Bypassing review is not the same as bypassing the gate.** Merging past a
  required human review is the operator's call. Merging past `BEHIND` skips
  *evidence*. Update the branch, let CI run, then merge:

  ```bash
  gh pr update-branch <n> --rebase
  gh pr checks <n>            # wait for pass
  gh pr merge <n> --rebase --admin --delete-branch
  ```

- **Rebase-merge only** — the repo forbids squash and merge commits, and
  requires linear history.
- **Renaming a clone breaks its `.venv`** (absolute paths). Rename only between
  agents, then `rm -rf .venv && just setup`. Never rename a clone an agent is
  running in; its working directory vanishes mid-run.

## 6. Watch the cost

Parallelism is capped by clones deliberately (ADR-0015 Consequences): nothing
detects two agents colliding, so lane separation is the dispatcher's job and
does not scale by adding agents.

The dominant cost is agent tokens, not wall time, and the dominant *waste* is
rework from a thin brief. Prefer fewer, larger, well-fenced lanes over many
small ones. A lane that needs three rounds of correction cost more than the two
lanes it displaced.
