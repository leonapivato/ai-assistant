---
name: find-parallel-work
description: Survey the roadmap, WORKING.md, and core/protocols.py to find independent subsystem slices ready for parallel agents, then draft a GitHub tracking issue for them. Use when asked to find, plan, or scope parallel work for multiple agents, or to open an issue coordinating that work.
---

# find-parallel-work

Produces one GitHub tracking issue that lays out a batch of independent,
non-colliding work slices — sized so each one maps to a single
`just claim-workspace <area>/<slug>` and a single agent. This is a
dev-process tool for building `ai-assistant` itself, not a feature of the
product. It **proposes** a batch; it never claims workspaces, edits
`WORKING.md`, or spawns agents itself — a human reviews the issue and decides
what to hand out.

## 1. Gather ground truth — don't hand-roll it

Read these, in this order, and trust them over any stale assumption:

- `just status` — the derived picture: module counts per package, the current
  `core/protocols.py` Protocol inventory, and ADR states. This is the
  canonical source for "what's actually built" — never guess it.
- `WORKING.md` — the *human-declared* picture: lane ownership and ADR numbers
  currently in flight. Any subsystem with a named owner, or any ADR number
  claimed against it that isn't yet `Accepted`, is off the table for this
  batch.
- `docs/roadmap.md` — the "first vertical" seven-artifact table and the build
  sequence checklist. A candidate lane must map to an unchecked item there;
  don't propose work the roadmap hasn't sequenced yet.
- `VISION.md` — pull the specific principle/section that justifies each lane,
  so the issue reads as "why this, now" rather than a bare task list.

## 2. Compute candidates

A subsystem is a valid candidate for this batch only if **all** of:

1. It's `_unclaimed_` in `WORKING.md` (no owner, no in-flight ADR against it).
2. `just status` shows it as not-yet-built (module count is "contract only"
   or clearly behind the others).
3. It maps to one of the roadmap's **first-vertical seven artifacts**
   (`UserProfile`, `Memory`, `CurrentContext`, `Goal`, `ToolDefinition`,
   `ActionPlan`, `FeedbackEvent`) — not merely to *any* unchecked
   build-sequence item, and not to the wider per-subsystem candidate-artifact
   table. The build-sequence checklist tells you which of the seven are
   still unbuilt; an unchecked item that isn't one of the seven (e.g.
   `permissions`' `ActionPolicy`) fails this rule and belongs in "Out of
   scope" as second-wave, not in the batch.

For each candidate, check whether it has entries in **both**
`core/protocols.py` and `core/types.py` yet. A subsystem can be missing
either independently — a new Protocol method can take/return a pydantic
model that doesn't exist yet, and CLAUDE.md requires any public data crossing
a subsystem boundary to live in `core/types.py`, not just the Protocol
signature. If either is missing, flag it explicitly: that's the shared
surface CONTRIBUTING.md calls out as highest-collision — two lanes both
proposing a `core/` addition the same day is exactly the scenario "push the
contract first, say so in the PR title" exists to defuse. Don't silently
omit this risk from the issue; state it as an instruction to whoever picks up
the lane, and name which of the two files (or both) is involved.

**Cross-check the batch, not just each lane in isolation.** If two or more
selected candidates would each need to touch `core/protocols.py` or
`core/types.py`, they are not actually independent — "push the contract
first" only defuses the collision for one of them; the second is now building
against a contract file that's about to change out from under it. Don't
present both as start-now-in-parallel. Either drop the batch to one `core/`
touching lane plus everything that's a pure leaf (no `core/` change needed),
or explicitly sequence the second to stack on the first (`just
claim-workspace <area>/<slug> <first-lane-branch>`) once the first's contract
commit is pushed — state which of the two this batch is doing, don't leave it
implicit.

## 3. Draft the issue

One issue, not one per lane — matches `WORKING.md`'s own lightweight-ledger
style. Structure:

- **Title**: short, names the batch (e.g. "Parallel work: planning + tools
  contracts").
- **Why**: 2-3 sentences linking the specific `VISION.md` principle and
  `docs/roadmap.md` line this batch advances.
- **One checklist section per lane**, each with:
  - Subsystem name and the roadmap artifact(s) it delivers.
  - Proposed `area/slug` for `just claim-workspace`.
  - Whether it touches `core/protocols.py`, `core/types.py`, or both, and the
    coordination instruction if so (claim the ADR number and lane in
    `WORKING.md` before starting; push the contract commit first and flag it
    in the PR title).
  - A reminder to register the lane in `WORKING.md` on pickup — this skill
    does not do that itself.
- **Out of scope**: name anything that looked tempting but got excluded in
  step 2 and why (already owned, not in the first vertical, etc.) so the
  issue doesn't get re-litigated in comments.

## 4. Confirm before posting

`gh issue create` is the one externally-visible action here — it posts to
shared GitHub state other people see. Print the drafted body and get
explicit confirmation before running it. Never auto-fire this step.

State can go stale between step 1 and this one — someone else can claim a
lane in `WORKING.md` while the draft sits waiting for confirmation.
Immediately before creating the issue, reread `WORKING.md` (cheap — it's one
file) and drop or re-flag any lane that gained an owner since step 1 rather
than posting a batch that includes work someone already picked up.
