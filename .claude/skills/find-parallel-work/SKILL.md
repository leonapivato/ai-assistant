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
3. It maps to an item in roadmap.md's build-sequence checklist or the
   first-vertical artifact table.

For each candidate, check whether it has a `core/protocols.py` entry yet. If
not — true for any subsystem that hasn't landed its first Protocol — flag
this explicitly. That's the one shared surface CONTRIBUTING.md calls out as
highest-collision: two lanes both proposing a `core/` addition the same day
is exactly the scenario "push the contract first, say so in the PR title"
exists to defuse. Don't silently omit this risk from the issue; state it as
an instruction to whoever picks up the lane.

Exclude anything not in the roadmap's *first vertical* seven artifacts even
if the subsystem folder exists and is unclaimed — e.g. `permissions`'
`ActionPolicy` is a real candidate artifact per the roadmap table but is not
part of the first vertical, so don't bundle it into an early batch without
calling that out as second-wave.

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
  - Whether it touches `core/protocols.py`, and the coordination instruction
    if so (claim the ADR number and lane in `WORKING.md` before starting;
    push the contract commit first and flag it in the PR title).
  - A reminder to register the lane in `WORKING.md` on pickup — this skill
    does not do that itself.
- **Out of scope**: name anything that looked tempting but got excluded in
  step 2 and why (already owned, not in the first vertical, etc.) so the
  issue doesn't get re-litigated in comments.

## 4. Confirm before posting

`gh issue create` is the one externally-visible action here — it posts to
shared GitHub state other people see. Print the drafted body and get
explicit confirmation before running it. Never auto-fire this step.
