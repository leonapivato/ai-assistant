# 13. Model routing and fallback: a second axis on the failure taxonomy

- Status: Proposed
- Date: 2026-07-19

## Context

ADR-0011 established that cross-cutting model behaviour composes by *wrapping* a
`ModelProvider` rather than widening the Protocol, and shipped the first wrapper
(`RetryingProvider`). It listed routing and fallback as the next capability the
seam was meant to carry, and predicted that composition order would become a real
decision. This ADR builds that capability and settles the order.

[VISION](../../VISION.md) §6 asks for routing on "capability, speed, cost, privacy,
and reliability". Only the last of those is reachable today: the assistant has no
cost model, no latency history, and no capability metadata per model. So this
slice deliberately implements **reliability routing only** — an ordered
preference list with fallback — and leaves ranking to a later slice that has the
state to rank with.

The blocking problem is narrower than "pick the best model". It is that
`RetryingProvider` can only ever hand a failure back to the caller. If the
configured provider is down, throttled, or refusing our credentials, every
request fails, no matter how many other providers are configured. Retry makes a
single provider more reliable; nothing yet makes the *system* more reliable than
its most fragile provider.

Attempting to route surfaced a modelling gap. ADR-0011's `retryable` flag answers
"would this same call, to this same provider, succeed if repeated?". Fallback
asks a different question — "would a *different* provider succeed?" — and the two
answers are not the same. Reusing `retryable` to drive fallback would be wrong in
both directions: it would refuse to fall back on an expired API key (not
retryable, but the clearest case for trying another provider) and it would
happily re-send a content-policy refusal to every provider in the list.

## Decision

We will add fallback as a second wrapper on the ADR-0011 seam, driven by a new,
independent flag on the failure taxonomy.

### 1. `routable` as a second axis, orthogonal to `retryable`

`ModelError` gains `routable: ClassVar[bool]` alongside `retryable`. The full
matrix:

| Error                     | `retryable` | `routable` | Why they differ                            |
| ------------------------- | ----------- | ---------- | ------------------------------------------ |
| `ModelError` (bare)       | ✗           | ✗          | Unrecognised — conservative on both axes    |
| `ModelAuthError`          | ✗           | **✓**      | Same key always refused; another provider has its own |
| `ModelRateLimitError`     | ✓           | ✓          | Quota is per provider                       |
| `ModelTimeoutError`       | ✓           | ✓          | A provider too slow to meet the deadline    |
| `ModelUnavailableError`   | ✓           | ✓          | The canonical fallback case                 |
| `ModelContentFilterError` | ✗           | **✗**      | Travels with the request, not the provider  |
| `ModelResponseError`      | ✗           | **✓**      | Often a limit of *this model*, not the ask  |

The three bold rows are the justification for a second flag rather than a reused
one. If the axes always agreed, `retryable` would have sufficed.

**`ModelContentFilterError` is deliberately not routable.** Re-sending a refused
prompt to provider after provider until one accepts is not resilience; it is
shopping for the most permissive filter. It would also widen the set of providers
that see a prompt already flagged as sensitive, which ADR-0004 asks us not to do
silently.

The conservative default is unchanged and now applies to both axes: an
unrecognised failure is neither retryable nor routable. On the routing axis the
cost of that default is a missed fallback; the cost of the opposite default would
be silently transmitting user data to additional providers on any failure we do
not understand — an ADR-0004 concern, not merely a spend concern.

This is additive: no Protocol changes, no existing flag changes value, and code
that only knows about `retryable` keeps working.

### 2. `RoutingProvider` — static preference order

`RoutingProvider` holds an ordered list of `Route`s (a provider, an optional
per-route `"provider:model"` override, and a diagnostic label) and tries them in
order. A routable failure advances to the next candidate; a non-routable one
propagates immediately.

Preference order is **static**: the first healthy route always wins. There is no
health tracking, so a persistently dead primary is re-tried on every request.
That is a real cost, accepted deliberately — the alternative (circuit breaking)
needs state, a decay policy, and a story for what happens across process
restarts. ADR-0011 already deferred circuit breaking to "once there is traffic to
justify it", and that is still true.

A per-route model override lets one underlying provider appear as several routes
— a cheap model first, a stronger one behind it — without a second adapter
instance.

### 3. Retry goes *inside* routing

Both orders type-check, and the wrapper composes either way:

```python
RoutingProvider([Route(RetryingProvider(a)), Route(RetryingProvider(b))])  # chosen
RetryingProvider(RoutingProvider([Route(a), Route(b)]))                    # not
```

We recommend retry-inside-routing. Retrying within a provider is the cheap
correction — a transient blip resolves without ever touching a second provider,
so no extra prompt is transmitted and no second vendor is billed. Routing is the
expensive correction and should only be reached once a provider has genuinely
failed to deliver.

The outer form re-routes on every attempt, which spreads a single logical request
across providers on the first blip. It also interacts badly with §1: a
non-routable failure aborts the router, so the outer retry loop would re-enter a
router that is going to refuse again.

Nothing enforces the order — enforcing it would mean a wrapper knowing what wraps
it, which is exactly the coupling ADR-0011 avoided. It is a wiring decision, and
`orchestration` owns it.

### 4. An explicit `model=` override disables routing

`ModelProvider.complete` already accepts a per-call override. When a caller
supplies one, `RoutingProvider` sends the call to the first route's provider with
that model and **does not fall back**.

Routing is the policy for choosing a model when the caller has *not* expressed a
preference. A caller who names a model has already chosen, usually for a reason
the router cannot see (a capability, a data-residency constraint, a
reproducibility requirement). Silently answering from a different model would be
a worse failure than an honest error, and would be undetectable downstream.

### 5. Exhaustion preserves classification

When every route fails, the *last* failure is re-raised **as-is**, annotated with
a PEP 678 note naming each candidate and why it failed.

Preserving the type — rather than flattening to a generic `ModelError` — means a
caller that backs off on `ModelRateLimitError` still sees one after routing.
Flattening would destroy exactly the classification ADR-0011 built.

The obvious way to do that is to rebuild the error as `type(last)(summary)`. We
tried it, and it is wrong: it assumes every `ModelError` subclass takes exactly
one message argument. Ours do, but a route may be *any* `ModelProvider`, and one
raising a richer subclass — `ProviderQuotaError(limit, message)` — turns the
reconstruction into a `TypeError`. That is not a degraded message but a different
exception type, which the caller's `except ModelError` does not catch, with the
provider's real failure destroyed. An adversarial review caught this; a
regression test now pins it.

Re-raising the original object and attaching a note makes no constructor
assumption at all and additionally preserves the message, traceback, and
`__cause__`. The cost is that the summary is a note rather than part of `str(exc)`
— it renders in tracebacks and in anything using `traceback.format_exception`,
but a log line that formats only `str(exc)` will not show it. Accepted:
correctness of the propagated type outranks convenience of one logging shape.

### 6. Every route must be a provider the user configured

ADR-0004 §2 permits off-device user data only from the `models/` layer, and only
to "the model provider the user has configured" — **singular**. Routing makes
that plural, so it must be squared explicitly rather than by implication.

The rule: a route list may contain **only providers the user has explicitly
configured**, on the same footing as the primary. Falling back is not permission
to reach a provider the user never chose. Concretely:

- `RoutingProvider` never acquires a provider. It receives fully-constructed
  `ModelProvider`s by injection and cannot widen the set of endpoints reachable;
  it can only re-send to one already wired in. Whoever composes the pipeline —
  `orchestration` — is therefore the component that owes this obligation.
- When route configuration lands in `Settings`, a configured route must require
  its own credential, so a provider the user has not set up cannot become a
  silent fallback.
- A fallback is user-visible in principle: which provider answered is not
  currently reported, and should be once there is an interface to report it.
  Recorded as a gap, not a solved problem.

**This amends ADR-0004 §2** from one configured provider to a configured *set*.
The privacy property that ADR intends is unchanged — user data reaches only
providers the user chose — but the wording assumed a single one, and ADR-0013
cannot be ratified without that amendment being accepted too.

Found by the Codex architecture reviewer, which raised it as a blocker on the
grounds that "calling the route list a privacy surface does not establish
consent". That is correct: §1's note that a route list *is* an ADR-0004 surface
described the risk without constraining anything.

### 7. Deferred

- **Ranking by cost, latency, or capability** — the rest of VISION §6. Needs
  usage and cost data that `complete` cannot return today; ADR-0011 §6 already
  names that a genuine Protocol change.
- **Health tracking and circuit breaking** (§2) — a further wrapper.
- **Parallel racing** (hedged requests) — send to two providers, take the first
  reply. Cheaper in latency, more expensive in spend and in how many providers
  see the prompt; a privacy decision as much as a performance one.
- **Per-route budgets or quotas.**

## Consequences

- **The system is now more reliable than its most fragile provider**, which was
  not previously true at any retry count.
- **The taxonomy has two axes, and every future subclass must consider both.**
  This is the main ongoing cost of the decision. A new error type that sets
  neither flag gets the safe default, so the failure mode is a missed fallback
  rather than a wrong one — but the matrix in §1 is now a thing to keep honest,
  and a test pins it so a change to it has to be deliberate and visible.
- **Routing spends money in more places.** A fallback re-sends the prompt to a
  second vendor. The conservative `routable` default keeps this to failures we
  actually recognise.
- **More providers may see a given prompt**, and **this ADR cannot be ratified
  alone.** §6 constrains routes to providers the user configured, but that
  restates ADR-0004 §2 in the plural, so accepting ADR-0013 means accepting an
  amendment to an already-Accepted ADR. Configuring a route list is a privacy
  decision, not only an availability one.
- **Nothing is wired yet.** No component constructs a `RoutingProvider` and
  `Settings` has no route configuration, so this slice changes no egress in
  practice. The obligations in §6 fall due when `orchestration` wires the
  pipeline — which is the moment to re-read them, not merge time.
- **A dead primary is re-tried on every request** (§2) — bounded by that route's
  own deadline, but a real per-request latency cost until circuit breaking lands.
- **Failures are noisier to read.** An exhausted-routes error carries every
  candidate's failure. Deliberate: the alternative is knowing only that "the
  model failed" while three different causes hide behind it.
- **Revisit when** cost/latency data exists (turning static order into real
  ranking), or when a deployment runs enough traffic that re-probing a dead
  primary on every request becomes the dominant cost.
