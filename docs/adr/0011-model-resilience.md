# 11. Model resilience: a classified failure surface and a decorator seam

- Status: Proposed
- Date: 2026-07-18

## Context

The `models` layer is the seam that makes the assistant model-agnostic
(ADR-0002), but it is the thinnest subsystem relative to its ambition: one
Protocol method, `ModelProvider.complete`, and one adapter,
`PydanticAIProvider`. Everything [VISION](../../VISION.md) §6 promises — routing on
"capability, speed, cost, privacy, and reliability" — is still unbuilt, and
VISION §7 names **retries** explicitly among the things deterministic services
must own rather than leave to the model.

Two concrete problems block that work:

1. **Failure was a single undifferentiated type.** Every provider exception was
   flattened into one `ModelError`. A rate limit, an expired key, a timeout and
   a refused prompt were indistinguishable, so no caller could decide whether
   retrying was sane. No retry policy can be built on an unclassified failure
   surface.
2. **There was no deadline.** A hung provider blocked its caller indefinitely.
   The `context` subsystem had already established per-source timeouts
   (ADR-0008 §4); `models` — which does far more I/O — had none.

Fixing those forces a prior architectural question, because it is the same
question every remaining `models` capability asks. Routing, fallback, usage and
cost accounting, and instrumentation are all *cross-cutting behaviour around a
completion*. Where does that behaviour live? The available answers are: widen
the `ModelProvider` Protocol; grow `PydanticAIProvider`; or compose. This ADR
picks the third and sets the precedent the later slices follow.

This adds no new `core` type and changes no Protocol — but it establishes a
structural pattern for the subsystem, which is the kind of non-obvious decision
`CLAUDE.md` says to record.

## Decision

We will classify model failures by cause, and add cross-cutting model behaviour
by **wrapping** `ModelProvider` implementations rather than widening the
Protocol or growing the adapter.

### 1. A failure taxonomy carrying an explicit `retryable` flag

`core/errors.py` gains subclasses of `ModelError`:

```python
ModelAuthError            # 401/403        retryable = False
ModelRateLimitError       # 429            retryable = True
ModelTimeoutError         # 408, deadline  retryable = True
ModelUnavailableError     # 5xx, connection failures   retryable = True
ModelContentFilterError   # refused on policy grounds  retryable = False
ModelResponseError        # malformed/unusable reply   retryable = False
```

`retryable` is a `ClassVar[bool]` on the exception rather than a lookup table in
the retry logic, so the knowledge lives with the error and any future consumer
(a circuit breaker, a router choosing a fallback) reads the same answer.

`PydanticAIProvider` maps pydantic-ai's exceptions and HTTP status codes onto
this taxonomy. The mapping is **conservative: an unrecognised failure stays a
bare, non-retryable `ModelError`.** A wrongly-retryable classification makes a
client hammer a provider that can never succeed — strictly worse than not
classifying at all.

This is **additive**: `complete` still raises only `ModelError`, so existing
callers are unaffected and the Protocol is untouched.

### 2. Cross-cutting behaviour composes by wrapping

Because `ModelProvider` is a `Protocol`, a class that implements it *and holds
another one* is substitutable everywhere the contract is expected:

```python
provider = RoutingProvider(RetryingProvider(PydanticAIProvider(model)))
```

Each layer adds one concern and delegates the rest. Consequences we are choosing
deliberately:

- **No Protocol change** for anything expressible as behaviour around a
  completion — retry, timeout, routing, fallback, instrumentation, caching. By
  golden rule 5 a Protocol change is a breaking change; this avoids paying that
  cost repeatedly.
- **The adapter stays a translator.** `PydanticAIProvider`'s job remains
  message-history translation and error mapping. Resilience does not accrete
  into it.
- **Uniform across implementations.** A wrapper works over any `ModelProvider`,
  including test fakes and future non-pydantic-ai adapters, so behaviour need
  not be reimplemented per adapter.
- **Testable in isolation.** Each layer is tested against a fake inner provider
  with no network and no real time.

### 3. The deadline belongs to the wrapper, not the adapter

`RetryingProvider` applies `asyncio.timeout` **per attempt**. Placing it in the
wrapper rather than inside `PydanticAIProvider` follows from §2 — every provider
gets it uniformly — and from a requirement retry imposes: a retry loop must be
able to abandon a hung attempt in order to start the next one, which it cannot
do if the deadline is buried in the callee.

**Outer cancellation is not caught.** `asyncio.timeout` converts only the
`CancelledError` it raised itself, so a caller cancelling the task still sees
`CancelledError` rather than a spurious retry or a timeout.

**Providers must be cancellation-cooperative, and this is a contract
requirement rather than something the wrapper can enforce.** `asyncio` abandons
a call by cancelling it, so a provider that swallows `CancelledError` cannot be
stopped by *any* wrapper — no implementation of `RetryingProvider` could make
the deadline binding against one. Real providers are cooperative (pydantic-ai
sits on httpx/anyio, which are), and the requirement is stated here so it is a
known property rather than an assumption.

Two things the wrapper *does* guarantee even so, both found by adversarial
review:

- A provider that swallows the cancellation and then returns normally does not
  get its late reply handed back as if the deadline had held. Expiry does not
  always surface as an exception — the context manager exits quietly in that
  case — so the deadline is asked directly whether it expired.
- A `TimeoutError` the provider raises *itself* is not reported as our deadline
  expiring. The two are told apart by where they are caught: on expiry the inner
  call sees a `CancelledError`, and the `TimeoutError` appears only at context
  exit, so one caught inside can only have come from the provider.

### 4. Backoff is full jitter

The delay is drawn uniformly from `[0, ceiling)`, where `ceiling` doubles per
attempt up to a cap. Randomising the whole interval — rather than adding jitter
to a fixed delay — stops callers that failed together from retrying in lockstep
and re-overloading a provider that is already degraded.

### 5. Wrapper configuration is a local dataclass, not a `core` type

`RetryPolicy` (timeout, attempts, backoff bounds) is a frozen dataclass in
`models/`, validated at construction. It configures an implementation and never
crosses a subsystem boundary, so per `CONTRIBUTING.md` it does not belong in
`core/types.py`; only data that crosses a seam does. `Settings` mirrors the
knobs, and `RetryPolicy.from_settings` owns the mapping so the knobs have one
interpretation; *constructing* the wrapper belongs to whoever composes the
pipeline, which is `orchestration` and does not exist yet.

Validation explicitly rejects **non-finite** values at both layers. NaN compares
`False` to everything and infinity counts as "positive", so both slip past
ordinary bounds checks and then degrade silently rather than loudly — an
infinite timeout disables the deadline, an infinite cap unbounds backoff. For
the same reason backoff clamps its exponent and saturates by comparing against
the cap through division: computing `base * 2 ** attempt` first can overflow to
infinity, after which capping is meaningless.

### 6. What this pattern cannot absorb

Wrapping only works for behaviour expressible *around* the existing signature.
These remain genuine Protocol changes, each needing its own ADR:

- **Usage and cost accounting** — `complete` returns a bare `Message`, so token
  counts have nowhere to go. Requires changing the return type.
- **Structured output** — typed extraction needs a new, generic method.
- **Tool-calling** — tool exchanges are not representable in `Message` today
  (`Role.TOOL` is rejected), and need a tool-call identity.

### 7. Deferred

- **Classifying transport timeouts precisely.** `httpx` timeouts do not subclass
  builtin `TimeoutError`, but for the supported providers an SDK wraps them into
  `ModelAPIError`, so they already classify as `ModelUnavailableError` —
  retryable, hence correct behaviour with a coarse label. Precise classification
  means importing `httpx` directly; deferred to the streaming slice, where
  pydantic-ai does let bare `httpx` errors escape from chunk reads.
- **Context-length overflow** as its own class: detecting it requires
  provider-specific response-body sniffing, and a misfire is silent.
- **Honouring `Retry-After`** on a 429 in place of computed backoff.
- **Circuit breaking** — a further wrapper, once there is traffic to justify it.

## Consequences

- **Failures become actionable.** Callers can distinguish "try again" from "this
  will never work", which is the precondition for retry, fallback and routing.
- **The remaining `models` roadmap gets cheaper.** Routing, fallback and
  instrumentation land as wrappers with no Protocol change, and can therefore be
  built in parallel with work in other subsystems.
- **Composition order becomes a real decision.** `Routing(Retrying(...))` retries
  within one model; `Retrying(Routing(...))` re-routes on each attempt. These
  differ in cost and latency, and the wiring layer must choose deliberately.
- **Debugging crosses more layers.** A failure may pass through several wrappers;
  each preserves `__cause__` so the chain stays readable, but a stack trace is
  longer than a direct call.
- **The taxonomy is a lasting commitment.** Consumers will branch on these
  classes, so adding one later is easy while changing a `retryable` value is not
  — it silently alters retry behaviour everywhere.
- **A conservative default means some retryable failures are not retried.**
  Anything unrecognised is treated as fatal. This is deliberate, and the cost is
  paid in occasional missed retries rather than in retry storms.
- **Revisit when** a second adapter or the routing slice lands, since either may
  show that some resilience genuinely belongs in the adapter after all.
