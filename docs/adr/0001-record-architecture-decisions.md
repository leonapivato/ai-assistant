# 1. Record architecture decisions

- Status: Partially superseded by ADR-0070 (the change-a-decision mechanism)
- Date: 2026-07-16
- Partially superseded: 2026-07-26 by ADR-0070 — the change-a-decision clause
  below ("to change a past decision, write a new ADR that supersedes the old one
  and update the old one's status") is replaced by ADR-0070's amend-vs-supersede
  test, which adds in-place amendment (for a change that alters no decision) and
  partial supersession. Append-only, sequential numbering, one file per decision,
  and the Context/Decision/Consequences structure all stand; the amendment
  mechanism is append-only in form (an appended dated note, no rewrite of
  ratified text). This line is an appended note; the `Status` field above is this
  ADR's only status. See ADR-0070.

## Context

This project is built largely by AI agents working in parallel. For that to stay
organized and reviewable, decisions must be written down where both humans and
agents can find them, so they are not silently relitigated in each change.

## Decision

We keep Architecture Decision Records (ADRs) in `docs/adr/`, one Markdown file
per decision, numbered sequentially (`NNNN-title.md`). Each ADR states Context,
Decision, and Consequences. ADRs are append-only: to change a past decision,
write a new ADR that supersedes the old one and update the old one's status.

## Consequences

- Agents (see `CLAUDE.md`) must consult existing ADRs before changing an
  established decision and must add an ADR for any non-obvious new one.
- The decision history is reviewable in-repo, no external tracker required.
