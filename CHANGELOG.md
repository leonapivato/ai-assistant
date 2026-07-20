# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `orchestration`: `LearningLoop`, the first working slice of the request
  pipeline and the roadmap's first closed vertical (ADR-0022). `respond()` runs
  intent → context assembly → memory retrieval → planning; `learn()` turns a
  `FeedbackEvent` into memory-update proposals, has the policy rule on each, and
  writes what it accepts. The two are separate calls because a correction
  arrives whenever the user gets round to it, usually not within the turn it
  corrects. Every collaborator is injected and seen only through its `core`
  Protocol — the engine imports no subsystem — so the same loop runs against the
  canonical fakes and the real subsystems. Failure behaviour follows one rule: a
  stage aborts the turn when continuing would require inventing something,
  and otherwise degrades and says so. A failed context assembly therefore
  propagates (fabricating a situation the planner would treat as fact is worse
  than stopping), while a failed retrieval yields no memories and reports
  `TurnResult.memory_degraded` — an unpersonalised answer is the degradation a
  user of this system most deserves to be told about, since silently answering
  generically is the failure that looks most like success. Deliberately not
  included: tool selection, permission checking, and execution, none of which
  can be written honestly while `Tool.invoke` remains deferred (ADR-0016 §7). A
  `MERGE` ruling is reported but not applied, because folding two records is
  `memory`'s own semantics and golden rule 1 forbids importing `MemoryIngestor`;
  ADR-0022's Consequences records that gap and the `MemoryWriter` Protocol that
  would close it.

- **BREAKING** `tools`/`core`: a new `ToolRegistry` Protocol and the `core`
  types it exchanges (`ToolDefinition`, `RiskLevel`, `Reversibility`,
  `ToolCost`, `CostBasis`, `Idempotency`, `VisibleIdentifier`) plus a
  `ToolRegistrationError`. A
  Protocol change is a breaking change (CLAUDE.md golden rule 5); pre-1.0 this
  needs no deprecation cycle, but anything structurally typed against
  `core.protocols` should be rechecked. It is additive — no existing Protocol or
  type changes — so nothing implemented against the previous contracts breaks.
  A `ToolDefinition` registry carrying the risk metadata the
  permission layer and tool selection need in order to *reason* about tools
  rather than hard-code integrations (ADR-0016, corrected in five clauses by
  ADR-0018). A tool is a **declaration**:
  frozen, and with no default on any field a permission decision depends on —
  the natural-looking default for the data-reach tuples, empty, is the claim
  "this tool touches no data", which is exactly the false statement a forgetful
  integration author would ship, so an under-declared tool does not load.
  `RiskLevel` and `Reversibility` are ordered by severity rather than by string
  value, which is not a convenience but the removal of a live trap: `StrEnum`
  members *are* strings, so `RiskLevel.CRITICAL < RiskLevel.LOW` would be `True`
  and a threshold policy written the obvious way would invert on the most
  dangerous value. All four comparison operators are overridden (`str` supplies
  every one, so deriving three would leave them lexicographic) and they raise
  against a non-member rather than returning `NotImplemented`, which would fall
  through to the reflected `str` comparison and answer anyway. Data reach reuses
  ADR-0004's `DataTier` — `reads`, `writes`, and `discloses` for what leaves the
  device — as a *ceiling* on what a tool may touch, not a measurement of a given
  call, so policy over-prompts rather than under-classifies. `ToolCost` is
  structured (`FREE`/`PER_CALL`/`UNKNOWN`) because the distinction a spend
  policy needs is free versus unknown, not present versus absent, and its amount
  is a finite `Decimal` — `Infinity` and `NaN` both satisfy a non-negative bound,
  `NaN` by making every comparison false. `Idempotency` declares a retry
  *guarantee* with a scope and a strictly positive window, not the presence of a
  parameter a tool may accept and ignore. Nothing on the type decides whether
  the permission gate is consulted: every invocation is gated, the definition
  states facts, and `permissions` draws conclusions. The `ToolRegistry` contract
  is query-only — it returns every candidate for a capability, ordered by id,
  and ranks nothing, since ranking needs policy and context a registry does not
  have — while registration stays inside `tools`, so binding a callable at
  registration when invocation lands is not a breaking contract change. A tool
  id is spent on first use and `deregister` does not free it, because a
  rebindable id could be substituted between a permission decision and the step
  that executes it. Settles ADR-0014's capability vocabulary as an open,
  registry-authoritative set rather than a `core` enum, which would make every
  new integration a breaking change. Deferred: invocation itself, and with it
  exactly-once execution, parameter-schema enforcement, and reconciling
  ADR-0004 §2's egress rule with a subsystem whose job is external calls.

  ADR-0018 corrected five clauses of ADR-0016, all found by writing this
  implementation against it. `description`, `id` and `capability` must contain a
  character that actually *renders*: `strip()` removes whitespace, but a
  zero-width space, a byte-order mark and a variation selector are format and
  combining-mark characters that survive it, and a handful more — the Braille
  blank and the Hangul fillers — sit inside the visible-category whitelist while
  displaying as nothing, so they are refused by name. Every registry query
  returns a snapshot detached recursively, because `ToolDefinition` holds a
  nested `ToolCost` and a shallow copy would let `result.cost.__dict__` rewrite
  registry state through something nominally detached. What a registry stores
  must be valid and detached, so a definition tampered past `frozen=True` into a
  contradictory state cannot be registered — though validation answers only
  "could this have been constructed?", never "is this what the author
  declared?", so a *validly* tampered definition under a fresh id is still
  accepted and nothing detects it (tracked as #54). And registering anything
  under a deregistered id is now refused, reversing ADR-0016's rule that an
  identical re-registration is idempotent: otherwise revocation would hold only
  until a composition root re-ran and replayed the original registration.

  The registration rules bind `tools` alone. `ToolRegistry` stays query-only, so
  `FakeToolRegistry` — importable by every subsystem — is held to the four query
  methods and nothing more, leaving `tools` free to change how it registers
  without breaking a shared fake.

- `models`/`core`: routing and fallback across several providers.
  `RoutingProvider` holds an ordered list of `Route`s and tries them until one
  succeeds, so the system is no longer only as reliable as its most fragile
  provider. Fallback is driven by a new `routable` flag on `ModelError`, added
  alongside `retryable` because the two answer different questions: `retryable`
  asks whether the *same* provider could succeed on a second try, `routable`
  whether a *different* one could succeed at all. The cases where they disagree
  are the point — an expired key is not retryable but is routable (credentials
  are per provider), while a content-policy refusal is neither, since shopping a
  refused prompt around until one provider accepts is not resilience and would
  widen who sees a prompt already flagged sensitive (ADR-0004). An explicit
  per-call `model=` override disables routing rather than silently answering
  from a different model, and exhausting every route re-raises the last failure
  untouched — so its identity, type and message survive routing — while every
  every *routable* candidate failure is logged by class — including one a later
  route papers over, which is the case that would otherwise be invisible, since
  the call goes on to succeed. A non-routable failure is not logged: it is
  raised to the caller, so it is not invisible to begin with. Diagnostics name a route by *position* (`route[1]`) and a failure
  by the nearest class in this project's own taxonomy, so neither a caller's
  string nor a provider's class name reaches a Tier 2 log; and they are emitted
  best-effort, because a broken log sink was able to abort the fallback
  entirely. Messages are deliberately kept
  out of the log: provider errors routinely quote the offending request, which
  would put Tier 1 data in a Tier 2 log (ADR-0004 §5). The key-based redaction
  net cannot catch that anyway — an `error` key looks innocuous — so the call
  site has to. (Three earlier
  attempts were wrong: rebuilding the error as `type(exc)(msg)` assumed a
  one-argument constructor an arbitrary `ModelProvider`'s errors need not have;
  attaching a PEP 678 note mutated an object the router does not own, growing
  without bound when a provider raises a cached instance; and logging
  `str(exc)` leaked the message. All found by the Codex adversarial reviewer.) Preference order is static; health
  tracking, circuit breaking, and cost/latency ranking are deferred. Retry
  belongs inside routing — the cheap correction first — which composes on the
  ADR-0011 seam with no Protocol change. Recorded in ADR-0013.
- `core`: the ADR-0004 §5 log redaction safety net, which the ADR has described
  as configured since it was ratified but which did not exist — there was no
  `structlog.configure` call anywhere in the tree. `core/logging.py` adds
  `configure_logging` (idempotent, called by the CLI before any subcommand, so
  the net is installed process-wide rather than depending on which module logs
  first) and a `redact_sensitive` processor masking values under known-sensitive
  keys. Matching is case-insensitive and substring-based, so `ANTHROPIC_API_KEY`
  and `chat_messages` are caught without enumerating every compound, and it
  recurses through the `Mapping`/`Sequence`/`Set` protocols rather than the
  concrete `dict`/`list` types — a `UserDict` or `MappingProxyType` is an
  ordinary thing to log and sailed straight through an earlier `dict`-only
  check with its secrets intact (found by the Codex adversarial reviewer).
  Loggers are deliberately not cached, so a module-level
  `structlog.get_logger(__name__)` bound at import time still picks up the
  redaction processor once the CLI configures it; caching left such a logger
  emitting through an unredacted chain forever (same reviewer). Mapping *keys*
  are masked too when they look like data rather than field names, dataclasses
  and pydantic models are unwrapped and scrubbed rather than reaching the
  renderer as a leaky repr, and any object the net cannot look inside is masked
  outright — "unknown" means "hidden", not "assumed harmless". Mapping keys are
  judged by *shape*: a field name is an identifier, so anything else is treated
  as data and masked, which catches an SSN or a person's name used as a key.
  Safe types are matched by exact type rather than `isinstance`, since a
  subclass can override `__repr__` to render anything, and an `Enum` renders by
  member name because its *value* can be a secret. Importing the package
  **composes with** an existing structlog configuration rather than replacing
  it, so an embedding application keeps its own (possibly stricter) processors
  and gains ours. It fails
  closed in the only sense a deny-list can: an event that *cannot* be scrubbed is
  dropped rather than emitted unscrubbed. There is deliberately **no
  allow-list**: an exemption is a permanent hole justified by an assumption
  about the value, and the assumption is what fails — `content_type` looks
  inert until a MIME string carries a `name=` parameter. Over-matching is fixed
  locally by renaming the key.

### Fixed

- `core`: `ASSISTANT_LOG_LEVEL` is now validated. An unrecognised level (a typo
  like `EROR`) silently fell back to INFO, so an operator who set `DEBUG` to
  diagnose something got neither the level they asked for nor any indication
  why. It is now rejected at load as a `ConfigurationError`, like every other
  malformed setting, and normalised to upper case.
- `context`: a real Tier 1 leak on the degradation path — a failing context
  source logged `error=str(exc)`, and a source wrapping calendars, tasks or email
  can quote the very personal data it was fetching. Now logs the exception's
  *class*. Key-based redaction cannot catch this (an `error` key looks
  innocuous), which is the point: the net is a safety net, and the primary
  defence remains logging identifiers, classes and counts rather than content.

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
  `model_timeout_seconds`/`model_max_attempts`/`model_backoff_*` `Settings`,
  with `RetryPolicy.from_settings` owning the mapping. Both layers reject
  non-finite values — NaN and infinity slip past ordinary bounds checks and then
  degrade silently — and backoff clamps its exponent and saturates through
  division, so an extreme attempt count or base cannot overflow to infinity and
  defeat the cap. (Non-finite config, the overflow, and the unmapped settings
  were found by the Codex adversarial reviewer.) Recorded in ADR-0011.
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
