# 1. Record architecture decisions

- Status: Accepted
- Date: 2026-07-16

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
