# WORKING.md — who owns what, right now

A lightweight coordination ledger for parallel work. The architecture keeps
subsystems isolated behind `core` Protocols, so two people can build different
subsystems at once with little overlap — *provided they do not both wander into
the same one*. This file records the current lanes so they don't.

**Update this when you pick up or hand off a subsystem.** It is intentionally
short-lived state, not history; git remembers the past. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) → "Coordinating parallel work" for the
shared-surface rules (ADR numbers and `core/` changes) this file supports.

This file holds only the *human-declared* bits (lane owners, ADR numbers in
flight). For the *derived* picture — which packages are built vs stubs, the
Protocol inventory, ADR statuses and numbering gaps — run `just status`; it is
generated from the repo and never hand-edited.

_Last updated: 2026-07-19._

## Lanes

| Subsystem        | Owner        | Status            | Branch / ADR                        |
| ---------------- | ------------ | ----------------- | ----------------------------------- |
| `models` (resilience) | mattewolf    | in progress (WIP) | `models/error-taxonomy`, ADR-0011 (Proposed) |
| `models` (routing)    | mattewolf    | in progress (WIP) | `models/routing` (stacked on `models/error-taxonomy`), ADR-0013 (Proposed) |
| `orchestration`  | _unclaimed_  | not started       | —                                   |
| `planning`       | _unclaimed_  | not started       | —                                   |
| `tools`          | _unclaimed_  | not started       | —                                   |
| `permissions`    | _unclaimed_  | not started       | —                                   |

## ADR numbers in flight

Claim a number here *before* drafting, so two branches don't grab the same one.
Highest merged ADR is **0012**; drop your row when the ADR merges.

| ADR  | Title                | Owner  | Branch                 |
| ---- | -------------------- | ------ | ---------------------- |
| 0011 | Model resilience     | mattewolf | `models/error-taxonomy` |
| 0013 | Model routing and fallback | mattewolf | `models/routing` |

## Shared surface

`core/` (`protocols.py`, `types.py`, `errors.py`) belongs to no single lane —
every subsystem's contract passes through it. Before editing it, follow the
`core/`-change heads-up rule in `CONTRIBUTING.md`. A change here is the one edit
most likely to conflict.

## Already built (no active owner)

`core` (contracts), `models` (base adapter), `memory`, `context`, `learning`.
Touch these through their Protocols; if you need to *change* one's contract,
that is a `core/` change — coordinate it.
