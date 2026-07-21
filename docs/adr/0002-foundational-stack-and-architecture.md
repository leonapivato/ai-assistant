# 2. Foundational stack and architecture

- Status: Accepted, partially superseded by ADR-0024 (build-backend clause)
- Date: 2026-07-16
- Note (2026-07-21): **The build-backend clause is superseded by ADR-0024.**
  That clause is the "(+ `uv_build` backend)" parenthetical in *Language &
  tooling* below; ADR-0024 §4 replaces `uv_build` with `hatchling`, whose build
  hook fetches and verifies the vendored embedding artifact. This is a note,
  not a status — the `Status` line above carries the status change ADR-0001
  requires. Everything else here stands: the rest of *Language & tooling*, and
  the architecture, model layer, interface, and persistence decisions, plus the
  ADR-0010 supersession already recorded inline under *Workflow / CI*.

## Context

Starting a new, model-agnostic AI-assistant project intended to be built mostly
by AI agents. We needed to fix the runtime stack, the module architecture, and
the development workflow before feature work begins.

## Decision

**Language & tooling.** Python 3.14 (pinned via `.python-version`), managed with
`uv` (+ `uv_build` backend). Quality gates: `ruff` (lint + format), `mypy`
(strict), `pytest` (+ `pytest-asyncio`, `pytest-cov`).

**Architecture.** A `core` package holds the contracts — `typing.Protocol`
interfaces plus shared pydantic types, config, and errors. Every other subsystem
(`models`, `memory`, `context`, `planning`, `tools`, `permissions`, `learning`)
implements or consumes those contracts and never imports another subsystem's
concrete code. `orchestration` wires implementations together via dependency
injection. `interfaces` holds thin adapters. This inversion is what lets agents
build/replace one subsystem in isolation with reviewable diffs.

**Model layer.** We own the high-level orchestration; the LLM + tool-calling
plumbing uses **pydantic-ai** (`pydantic-ai-slim` with per-provider extras),
wrapped behind our own `ModelProvider` Protocol so no provider SDK leaks outside
`models/`.

**Interface.** CLI-first (`typer` + `rich`), registered as the `assistant`
console script. The core stays interface-agnostic; API/UI adapters come later.

**Persistence.** Local-first by default: SQLite with `sqlite-vec` for embedding
search (dependencies added when `memory/` is implemented).

**Workflow / CI.** Local-only for now: `pre-commit` runs format + lint +
type-check. Remote CI (e.g. GitHub Actions) is deferred; revisit in a future ADR
when hosting is chosen. *(Superseded by ADR-0010: hosting is now GitHub and the
gate runs in CI on protected pull requests.)*

## Consequences

- New model providers are a change confined to `models/`.
- Swapping SQLite for a networked DB (e.g. Postgres/pgvector) is confined to
  `memory/` because callers depend on the `MemoryStore` Protocol.
- Deferring remote CI means the `pre-commit` gate is the only automated check
  until a hosting decision is made; contributors must run it.
- Choosing pydantic-ai is reversible: it lives behind `ModelProvider`, so a
  future move to hand-rolled provider clients touches only `models/`.
