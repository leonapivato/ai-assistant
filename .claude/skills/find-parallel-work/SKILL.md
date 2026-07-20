---
name: find-parallel-work
description: Survey the roadmap and core/protocols.py to find independent subsystem slices ready to hand to agents, then draft a GitHub tracking issue for them. Use when asked to find, plan, or scope parallel work for multiple agents, or to open an issue coordinating that work.
---

# find-parallel-work

Produces one GitHub tracking issue laying out a batch of independent,
non-colliding work slices, each sized for a single agent in a single clone.
This is a dev-process tool for building `ai-assistant` itself, not a product
feature. It **proposes**; the operator decides what actually gets dispatched.

## 1. Survey a current `origin/main`

State on disk can be stale, and a lane list computed from a stale tree proposes
work that is already done. Read the ref, not the checkout:

```bash
git fetch origin
git show origin/main:docs/roadmap.md
git show origin/main:src/ai_assistant/core/protocols.py
git show origin/main:src/ai_assistant/core/types.py
```

For the derived picture — module counts per package, Protocol inventory, ADR
states — `project_status.py` reads a *checkout*, not a ref, so point it at a
disposable one rather than at wherever you happen to be standing (you are
normally on a feature branch, which has neither `origin/main`'s content nor a
fast-forward path to it):

```bash
tmp="$(mktemp -d)"
git worktree add --detach --quiet "$tmp/survey" origin/main
python3 scripts/project_status.py --root "$tmp/survey"   # stdlib-only, runnable bare
git worktree remove "$tmp/survey" && rm -rf "$tmp"
```

`--root` exists for exactly this. Remove the worktree even if a step in between
fails, so a partial survey does not stay registered.

Also check what is already claimed by open work:

```bash
gh pr list --state open --json number,title,headRefName
gh issue list --state open --limit 100 --json number,title,body
```

Open PRs and issues are where work-in-flight lives (ADR-0015). There is no
ledger file; do not look for one.

## 2. Compute candidates

A subsystem is a valid candidate only if **all** of:

1. No open PR or issue already covers it.
2. It maps to one of the roadmap's **first-vertical seven artifacts**
   (`UserProfile`, `Memory`, `CurrentContext`, `Goal`, `ToolDefinition`,
   `ActionPlan`, `FeedbackEvent`). An unchecked build-sequence item that isn't
   one of the seven belongs in "Out of scope" as second-wave.
3. `project_status.py`'s module count is consistent with rule 2. That count is
   "a rough progress proxy," not a completion test — a subsystem can be built
   with few dense modules. If the count and the roadmap checklist **disagree**,
   drop the lane and name the discrepancy rather than guessing which is right.

For each candidate, note whether it needs an entry in `core/protocols.py`,
`core/types.py`, or both — a Protocol method can take or return a type that
does not exist yet, and public data crossing a subsystem boundary must live in
`core/types.py`.

**Cross-check the batch as a whole.** Two lanes that both touch `core/` are not
independent: the second would build against a contract about to change. Either
keep one `core/`-touching lane plus pure leaves, or explicitly sequence the
second to start after the first's contract PR merges. State which; don't leave
it implicit.

## 3. Draft the issue

One issue for the batch, not one per lane.

- **Title**: names the batch (e.g. "Parallel work: planning + tools contracts").
- **Why**: 2–3 sentences tying the batch to a specific `VISION.md` principle and
  `docs/roadmap.md` line.
- **One checklist section per lane**, each with: the subsystem and roadmap
  artifact(s) it delivers, a proposed `<area>/<slug>` branch name, and whether
  it touches `core/protocols.py`, `core/types.py`, or both.

For a `core/`-touching lane, the checklist item says the contract ADR ships as
its own PR and merges before the implementation (ADR-0015 §5). **Do not assign
ADR numbers here** — the operator assigns them at dispatch. Proposing a number
in an issue that sits open for a week just recreates the stale-ledger problem.

- **Out of scope**: anything excluded in step 2 and why, so it isn't
  re-litigated in comments.

## 4. Confirm before posting

`gh issue create` posts to shared state. Print the drafted body and get explicit
confirmation first — never auto-fire it.

If the confirmation takes a while, re-run the `gh issue list` scan from step 1
immediately before creating, in case someone opened an overlapping issue in the
meantime. That is a courtesy check, not a reservation; merged and posted state
is authoritative, nothing before it.
