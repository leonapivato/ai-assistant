# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `learning` + `core`: feedback capture that closes the first learning loop
  (ADR-0009). Adds `FeedbackEvent`/`FeedbackKind` and a `FeedbackProcessor`
  Protocol; `RuleBasedFeedbackProcessor` maps explicit correction/preference
  feedback to a `USER_ASSERTED` memory proposal of the event's target
  `memory_kind` (a fact → `SemanticMemory`, a preference → `PreferenceMemory`),
  which the existing policy accepts. Learning *proposes* only — the pipeline
  wires proposals to the ingestor — so no subsystem writes memory directly. An
  integration test proves the vertical end to end (feedback → proposal → ingest
  → retrieve). `RATING`/implicit signals are deferred to a follow-up ADR.
- `models`/`core`: per-attempt timeouts and retry for model calls.
  `RetryingProvider` *wraps* any `ModelProvider` (it implements the same
  Protocol and delegates), so resilience composes with any implementation
  without either side knowing about the other — and needs no Protocol change.
  It is the first consumer of the `retryable` flag: a transient failure is
  retried with full-jitter exponential backoff, while one that would fail
  identically every time is re-raised immediately instead of burning quota.
  The deadline is per attempt, so a hung call can be abandoned and retried;
  outer cancellation still propagates rather than being mistaken for a timeout.
  Tunables live in a `RetryPolicy` dataclass, mirrored by validated
  `model_timeout_seconds`/`model_max_attempts`/`model_backoff_*` `Settings`.
- `models`/`core`: a model-failure taxonomy. `ModelError` gains specific
  subclasses — `ModelAuthError`, `ModelRateLimitError`, `ModelTimeoutError`,
  `ModelUnavailableError`, `ModelContentFilterError`, `ModelResponseError` —
  each carrying a `retryable` class attribute, so a caller can distinguish a
  transient fault from one that would fail identically on every attempt.
  `PydanticAIProvider` now maps pydantic-ai's exceptions (and HTTP status
  codes) onto that taxonomy. Purely additive: `complete` still raises only
  `ModelError`, so existing callers are unaffected and no Protocol changed.
  Unrecognised failures stay a bare, non-retryable `ModelError` — a wrong
  "retryable" is worse than none. Deferred: distinguishing context-length
  overflow, which needs provider-specific response-body sniffing.
- `context` + `core`: the situational-context step of the pipeline (ADR-0008).
  Adds a temporal `CurrentContext` (`now`, `time_of_day`, `is_weekend`,
  `within_working_hours`) and a `ContextProvider` Protocol.
  `AssemblingContextProvider` composes internal `ContextSource`s
  (`ClockContextSource` today) — merging them concurrently, degrading gracefully
  when a source faults, hangs (a per-source timeout), or returns a faulting
  mapping (an optional facet just goes absent), and raising
  the new `ContextError` only on a wiring bug (a field collision or a missing
  required facet). Adds `timezone`/working-hours `Settings`, validated at load
  (an unknown timezone or empty window is a `ConfigurationError`). The
  `ContextSource` seam is internal to `context/`, so only the typed
  `CurrentContext` crosses a subsystem boundary.
- `memory`/`core`: user data rights and retention (ADR-0007, closing the
  ADR-0004 §6 obligation). `MemoryStore` gains `delete`, `clear`, `export`
  (portable live snapshot), and `purge_expired`; both `InMemoryMemoryStore` and
  `SqliteMemoryStore` implement them. Retention is now enforced: a record past
  its `expires_at` is treated as forgotten — `get`/`search` never return it,
  independent of whether `purge_expired` has reclaimed it — with an injectable
  clock for deterministic expiry. `clear` scopes to this store's Tier-1 rows;
  the cross-tier keyring purge remains a higher-layer concern. Opening a
  pre-ADR-0007 database backfills the new `expires_at` column from each record's
  JSON, so already-expired legacy memories stay forgotten; a naive `expires_at`
  is normalised to UTC so both stores agree; and `export` surfaces read/decode
  failures as `MemoryStoreError` like the other operations. (Additive
  `MemoryStore` Protocol change; backfill, tz-normalisation, and export error
  wrapping found by the Codex adversarial reviewer.)

### Fixed

- `memory`/`core`/`models`: adversarial-review hardening of the store's error
  boundary. `SqliteMemoryStore` now translates any failed open (missing parent
  directory, extension load, schema, embedder mismatch) to `MemoryStoreError`
  and closes a half-open connection rather than leaking it; wraps embedder
  faults, wrong-sized/mis-counted vectors, and malformed results as
  `MemoryStoreError` in both `add` and `search` (previously raw exceptions
  escaped the store boundary), validating the query vector, not just the record
  vector. `MemoryIngestor` now raises instead of silently storing a proposal as
  new when a `MERGE` names an absent target, and reports an overflowing
  temporary-store ttl as `MemoryStoreError` rather than a raw `OverflowError`.
  `MemoryDecision` rejects a non-positive `STORE_TEMPORARY` ttl and outcome
  fields foreign to its kind. `HashingEmbedder` rejects non-positive dimensions.
  Found across two Codex adversarial passes.
- `docs`: ADR-0006 now reflects the as-built `Embedder` contract — the ratified
  §1 signature still showed a per-call `model` parameter the implementation had
  dropped; recorded as an amendment (golden rule 5). Found by the Codex
  architecture reviewer.
- `memory`: `SqliteMemoryStore.add` is now transactional — a failed multi-table
  write rolls back and raises `MemoryStoreError` instead of leaving a partial
  record/vector pair a later write could commit; a wrong-sized embedder vector
  is rejected up front. `search` with a non-positive `limit` returns `[]` instead
  of erroring or mis-slicing (also fixed in `InMemoryMemoryStore`). Found by the
  Codex adversarial reviewer.

### Changed

- `memory`: `SqliteMemoryStore` now ranks with cosine distance, so `search`
  scores are cosine similarity in `[0, 1]` — better separated and directly
  usable as a similarity threshold.
- `core`: `MemoryRecord` is now a typed discriminated union (episodic, semantic,
  preference, procedural) with per-record `Provenance` (source, confidence,
  evidence), replacing the flat content blob. `MemoryStore` gains `get()` and a
  `kinds` filter on `search()`. (ADR-0005; breaking Protocol/`core` change.)

### Added

- `memory`: `MemoryIngestor`, closing the propose/dispose/persist loop —
  detects conflicting memories (same kind, high similarity), runs the
  `MemoryPolicy`, and applies the ruling to the store (accept, merge, store
  temporarily with an expiry, or defer). Adds `MemoryIngestResult` and an
  `expires_at` retention field on memory records (ADR-0005/0004).
- `memory`: `SqliteMemoryStore`, the persistent local-first `MemoryStore` over
  SQLite + `sqlite-vec` (ADR-0002/0006) — embeds records on write, ranks by
  vector similarity on `search`, tags vectors with the embedding model/dimension
  (rejecting a mismatched embedder), and creates the database file owner-only
  (ADR-0004). Adds an `Embedder.model_id` for that tagging.
- `core` + `models`: an `Embedder` seam for semantic retrieval (ADR-0006) — an
  `Embedder` Protocol and `Embedding` type, an on-device default
  `FastEmbedEmbedder` (local, lazy-loaded), and a deterministic dependency-free
  `HashingEmbedder` for offline tests. `fastembed` is confined to `models/` by
  the import-linter contract.
- `core` + `memory`: the propose/dispose memory write path (ADR-0005) —
  `MemoryUpdateProposal`, `MemoryDecision`, and a `MemoryPolicy` Protocol, with a
  deterministic `DefaultMemoryPolicy` that accepts, rejects, merges, defers, or
  temporarily stores proposed memories. Adds a `DataTier` sensitivity type.
- Project skeleton: Python 3.14 + uv, `src/` layout, package `ai_assistant`.
- Tooling: ruff (lint + format), mypy (strict), pytest, pre-commit, import-linter.
- Architecture scaffold: `core` contracts (Protocols, types, config, errors) and
  subsystem packages (`models`, `memory`, `context`, `planning`, `tools`,
  `permissions`, `learning`, `orchestration`, `interfaces`).
- CLI adapter with an `assistant` console script.
- `models`: `PydanticAIProvider`, the first `ModelProvider` implementation,
  wrapping pydantic-ai behind the contract and confining provider SDKs to this
  layer.
- `memory`: `InMemoryMemoryStore`, a dependency-free, non-persistent
  `MemoryStore` with lexical retrieval, for developing and testing downstream
  subsystems against a real contract.
- Development standards: `CONTRIBUTING.md`, ADR process, and ratified policies
  (ADR-0002, ADR-0003, ADR-0004 privacy & data handling).
- `LICENSE` (MIT), `justfile` task runner, and `.editorconfig`.
