# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **`models` + packaging: the on-device embedding model is now a build input,
  not a runtime download (ADR-0024).** `fastembed` used to fetch its 64 MiB ONNX
  model from `huggingface.co` on first `embed`, with no revision pin and no
  integrity pin, into the system temp directory — so it recurred whenever `/tmp`
  was cleared, and whatever served the artifact got to choose what the embedder
  computed (issue #89). The artifact is now pinned to an immutable commit,
  verified file-by-file against a recorded SHA-256 manifest **at build time**,
  and shipped inside the wheel *and* the sdist, so no PyPI install path fetches
  anything and first run works offline. The artifact is never committed to git;
  a build from a git checkout is the only build that fetches.
  - **The build backend changes from `uv_build` to `hatchling`**, which
    ADR-0024 §4 records as superseding ADR-0002's build-backend clause:
    `uv_build` supports no build hooks, and `hatch_build.py` is the hook that
    acquires and verifies. Acquisition stays owned by `models/`; only its
    trigger moved, and the import-linter contract now forbids `huggingface_hub`
    (and `onnxruntime`, `tokenizers`) outside that layer.
  - **`FastEmbedEmbedder.model_id` is no longer the bare model name.** It now
    composes the name, a digest over the *shipped bytes*, and a digest over the
    audited behaviour-affecting versions, so ADR-0006 §4's "the model changed,
    re-embed" can actually fire: re-pinned weights or a bumped `fastembed` /
    `tokenizers` / `onnxruntime` / `numpy` move it, where before both left it
    identical and the store silently ranked old vectors against new queries.
    An implementation change within the existing `Embedder` contract, not a
    Protocol change (ADR-0024 §2). A dev store will report that re-embedding is
    required, which is the existing signal, not a new one.
  - **Those four packages are exact-pinned in the published metadata**
    (ADR-0024 §3), and the ONNX execution provider is pinned to CPU rather than
    `Device.AUTO`, so a machine gaining a GPU cannot move an existing store's
    embedding space.
  - **`FastEmbedEmbedder` serves only the vendored model** (ADR-0024 §6). Any
    other name is refused before a backend is consulted or a socket opened;
    there is no arbitrary-model path, because an arbitrary fastembed model has
    no pinnable identity. A missing artifact raises `ModelError` naming the
    cause instead of downloading, while `embed([])` still returns `[]` offline.

### Added

- Acceptance tests that build a real wheel, a real sdist, and a wheel *from that
  sdist*, all with the network denied, and check that each carries the artifact
  at the packaged path with every file's SHA-256 matching the manifest — the
  gap ADR-0024 §5 named, where "a hook that verifies the wrong bytes, requests
  the wrong revision, packages the wrong path, or configures only the wheel
  ships green".
- A test asserting the `genai-prices` snapshot in use reports
  `from_auto_update=False` (issue #132), so an upstream change to that default
  fails the gate rather than silently enabling a fetch of
  `raw.githubusercontent.com`.
- `core`: `ToolDefinition.interrupted_outcome`, a read-only property giving
  ADR-0029 §4's interrupted-call rule one home (ADR-0031 §1). The rule — `FAILED`
  when the tool is not `side_effecting` **or** its `idempotency` is `NATURAL`,
  `INDETERMINATE` otherwise — lived in two places: the seam's
  `tools.invocation.interrupted_outcome` and the canonical fake's private copy,
  which exists because the fake must not import the subsystem it stands in for.
  `orchestration` cannot import `tools/` either, so the executor would have made
  a third copy of a safety-critical classification — "two copies of a
  safety-critical ordering, free to disagree, with nothing that fails when they
  do" (ADR-0016 §2). It is a **plain `property`, deliberately not a
  `computed_field`**: a computed field enters `model_dump()`, and ADR-0018 §4's
  registration rebuild is `model_validate(tool.model_dump())` against
  `extra="forbid"`, so every registration would fail. Both existing copies are
  deleted rather than aliased. Not a Protocol change and no behaviour moves; the
  exhaustive table moves to `tests/core/`, beside the type.

- `orchestration`: `StepExecutor`, the pipeline's `execute` stage (ADR-0029 §8).
  It claims a plan step, runs one authorised `ToolCall` through an injected
  `ToolInvoker`, and commits what came back — the half the `LearningLoop` has
  been missing, and the first code to reach ADR-0014 §4's `INDETERMINATE` from a
  live executor rather than from a restart scan. Everything it knows about tools
  arrives through `ToolRegistry` and `ToolInvoker`, so it imports no subsystem.
  **The claim precedes the call**, carrying `bound_tool = call.request.tool.id`
  and `approval_ref = call.decision.id`, which is what makes the durable record
  a description of the call that actually ran. Because the claim lands first,
  every later exit commits something: a `ToolBindingError` is committed
  `RUNNING → FAILED` rather than left to strand, since recovery would otherwise
  record `INDETERMINATE` — "we cannot tell whether it acted" — about a call that
  provably never reached the callable. It is **not re-driven**, and the
  mechanism is that **retry is scheduled only from a `ToolResult`, never from an
  exception**: ADR-0029 §5's conjuncts read `result.failure.kind`, and an
  exception produces no result to read.
  **The result mapping is total** over `ToolOutcome`, and `RUNNING →
  INDETERMINATE` is now reachable from a live deadline expiry as well as from
  recovery — a widening of *when* that transition fires, not of the graph.
  **A cancellation is committed on both branches and then re-raised**, by
  `ToolDefinition.interrupted_outcome` read from the *registry's* declaration
  captured before the call, never from `call.request.tool`, which a `__dict__`
  write can flip to read-only mid-flight. The commit uses the whole shield
  idiom rather than a bare `await asyncio.shield(...)` — shield protects the
  inner task, not the `await` of it, so a repeat cancellation is absorbed until
  the write has landed. **The whole write path is cancellation-aware, not just
  the handler's**: once the tool has been reached the outcome is known, so a
  cancellation landing on the ordinary terminal commit lands the write too,
  rather than abandoning it for recovery to report ignorance over. Committing is
  not swallowing in either case: the cancellation still propagates, which is what
  keeps shutdown working.
  **The idempotency window is fail-closed** (ADR-0029 §5): the executor stops
  retrying once it has elapsed, and any reading that is not a positive elapsed
  duration — a step backwards, a jump past the window, a reading the clock guard
  refuses — is treated as *lapsed*. Declining to retry costs a recoverable error
  surfaced to the user; retrying outside a lapsed window costs a duplicated side
  effect. It is measured from the first *attempt*, not from before the claim, so
  a slow `commit_transition` cannot consume a window before the tool was
  reached. A monotonic clock seam is the proper fix and is deferred (#171).
  **`timeout` is checked before the claim**, not left to the seam: `invoke`
  refuses a non-positive or non-`timedelta` deadline before the callable is
  created, and letting that `ValueError` surface from inside would leave the
  step durably `RUNNING` for a call whose coroutine that same guard guarantees
  never existed.

- **BREAKING** `core`/`tools`/`testing`: the `ToolInvoker` Protocol and the
  types it exchanges — `ToolCall`, `ToolResult`, `ToolOutcome`, `ToolFailure`,
  `ToolFailureKind` — plus `ToolBindingError` (ADR-0029). A Protocol change is a
  breaking change (CLAUDE.md golden rule 5); it is additive at the `core`
  surface, but `tools/`'s registration shape does change: `register` and the
  `InMemoryToolRegistry` constructor now take a **callable alongside each
  declaration**, which ADR-0016 §5 predicted and ADR-0029 §1 requires. This is
  the seam the pipeline's right half was blocked on: the `LearningLoop` omitted
  tool selection, permission checking and execution because `Tool.invoke` did
  not exist, and now it does.
  **An unauthorised call is unconstructable.** `ToolCall` runs ADR-0021 §1's
  `authorises` in a model validator, so a `DENY`, an unanswered `CONFIRM`,
  altered parameters, a substituted definition or a different step cannot
  produce a value at all — the one call ADR-0021 said "belongs to the invocation
  contract", placed where an executor cannot forget it. `invoke` then re-runs
  the same check, in a fixed order: **revalidate and detach, compare the
  definition against the registry's own original, then re-evaluate
  `authorises`** — because `frozen=True` does not survive a `__dict__` write,
  and because a payload mutated into a state `FrozenJson` would refuse must come
  back as a `ToolBindingError` rather than as a raw serialisation error from the
  digest. The registry comparison is what closes ADR-0018 §4's
  tampered-but-still-valid definition, at execution, exactly where ADR-0021 §1
  predicted it would become detectable.
  **Failure crosses the seam as data; only seam faults are raised.** Three
  outcomes map one-to-one onto the three `StepStatus` members a finished
  invocation can produce, so an executor's mapping needs no default branch, and
  `INDETERMINATE` — "we do not know whether the effect happened" — can be
  reported at all, which an exception could not do. `retryable` is declared once
  per failure kind and answers *could this succeed*, never *may I repeat it*;
  ADR-0029 §5's conjunction with `ToolDefinition.idempotency` is what an
  executor must satisfy, and an `Idempotency.NONE` side-effecting tool is never
  auto-retried whatever the kind.
  **The seam owns the deadline, and the guarantee is stated weakly on purpose.**
  `timeout` is required and keyword-only — there is no spelling for "forever" —
  and is checked rather than trusted, since `asyncio.timeout(None)` is no
  deadline at all. On expiry a call that may have acted becomes `INDETERMINATE`
  and one that cannot have becomes `FAILED`, classified from the *registry's*
  declaration rather than the caller's, which a `__dict__` write could have
  flipped mid-flight. Both `TIMED_OUT` and cancellation are established rather
  than inferred from an exception type: an upstream SDK's own `TimeoutError`
  inside our budget is `INTERNAL`, and a `CancelledError` a tool invents with
  nothing cancelled is `INTERNAL` too. What the deadline buys is that the seam
  stops waiting, not that the tool stops working — a tool that suppresses its
  own cancellation outlives it, and the conformance suite pins that limit
  deterministically rather than letting a reader assume a hard bound.
  **The idempotency key is derived, not minted**: `decision.id` for a `KEYED`
  tool and `None` otherwise, which makes it stable across retries, distinct for
  a distinct intent, and reproducible after a restart from `approval_ref` alone.
  **No credential crosses this seam in either direction**, which is stronger
  than ADR-0017 §3 asks and is what makes `SecretStore`'s deferral safe rather
  than ambiguous. Implementing this **authorises no egress**: ADR-0017 §3's
  conditions are inherited whole and none is discharged, so `tools/` still
  transmits nothing.

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
