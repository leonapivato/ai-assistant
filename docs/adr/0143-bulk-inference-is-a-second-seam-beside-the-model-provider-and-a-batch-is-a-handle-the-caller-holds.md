# 143. Bulk inference is a second seam beside the model provider, and a batch is a handle the caller holds

- Status: Proposed
- Date: 2026-08-13
- **Durability clause.** Every quotation below — from an ADR, from
  `core/protocols.py`, from `core/errors.py`, from `pyproject.toml`, or from an
  issue — is of its text as it stood at this ADR's base, `6eb04080`, not of its
  text on any later day. Every ADR this decision composes with reads `Accepted`
  there. Where a later ADR changes one of the ADRs cited, this ADR is read
  against the text quoted here and that ADR's own record says what moved. The
  `Date` line is this ADR's authoring date in this clone's frame, the convention
  ADR-0137 follows and names; the base named here is the anchor that does not
  move under either frame.

## Context

### The question, and what it is worth

Issue #1034 records that the benchmark track's cost estimates assumed a ~50%
bulk-inference discount that the tree cannot reach: `ModelProvider` is
per-request only, and golden rule 4 forbids the benchmark harness calling a
provider SDK directly. #1034 enumerates three options and the owner has ruled
**option 1** — extend the model-layer contract with a batch surface. This ADR
decides that surface's shape. It decides no implementation; the triad and its
primary implementation are a separate lane, briefed after this merges (§9).

The money at stake is #1029's full LongMemEval-S run — the pilot itself runs
sequentially at standard pricing and does **not** wait on this decision, which
is why this ADR can be argued on its merits rather than against a clock.

### The state on `main`, read rather than remembered

Each of these was read at this ADR's base, `6eb04080`, not recalled:

- **`ModelProvider` has exactly one member**, `complete`, and it is
  `@runtime_checkable`. Its docstring fixes a well-formedness precondition on
  `messages` (non-empty, not ending on a `Role.ASSISTANT` turn), states that
  the precondition is "a **necessary condition, not a sufficient one**", and
  says in as many words that "nothing here promises tool support".
- **`Embedder` is already a sibling rather than a widening**, and its docstring
  gives the reason: it is "separate from :class:`ModelProvider` because
  embedding is a distinct capability a provider may not offer".
- **`core/protocols.py`'s module docstring carries an authoring guideline** that
  bears directly on this decision: "Prefer adding a new Protocol over widening
  an existing one." Two module-wide clauses — cancellation (ADR-0060) and input
  observation (ADR-0065) — are stated as "binding on **every** Protocol below".
- **`core/errors.py` fixes a two-flag disposition vocabulary for model
  failures**: `ModelError` plus six subclasses, each declaring `retryable`
  ("would *this same call, to this same provider* plausibly succeed if
  repeated?") and `routable` ("would *a different provider* plausibly
  succeed?").
- **`core/types.py` already has the pattern for a failure returned as a value**:
  `ToolFailureKind` is a `StrEnum` with an exhaustive `_RETRYABLE_BY_KIND`
  mapping, and `ToolFailure` carries it. `ToolBindingError`'s docstring states
  the reason that pattern exists — "an exception has no
  ``failure.kind.retryable`` to read, so there is nothing for a retry decision
  to be made from (ADR-0029 §8)".
- **`tests/core/test_protocol_triad.py` enforces the triad mechanically**: it
  enumerates the Protocols in `core/protocols.py` and fails the gate for any one
  missing its `<Protocol>Contract` suite, its `Fake<Protocol>` in
  `ai_assistant.testing`, or the `Test…Contract` subclass binding the two.
- **`models/` reaches vendors only through pydantic-ai today.** Every SDK import
  under `src/ai_assistant/models/` is `pydantic_ai`; no module there imports
  `anthropic` or `openai` directly.

### Three of #1034's premises checked, and one correction

#1034 is a hypothesis set, not a finding set. Two of its premises hold and one
needs correcting:

- **"`models/` exposes no batch route" — holds.** There is no batch surface in
  `core/protocols.py` or in `src/ai_assistant/models/`.
- **"golden rule 4 forbids the harness calling a provider SDK directly" —
  holds in substance, but not by the mechanism a reader would assume.**
  `[tool.importlinter] root_package = "ai_assistant"` builds the graph from that
  package alone, so a harness living outside `src/ai_assistant/` is **not in
  `lint-imports`' graph at all** and no import contract constrains it. Option 2's
  parenthetical — "tolerable only if the harness itself lives outside the
  subsystem-boundary rules — it does not today" — is therefore the wrong way
  round about the mechanism: mechanically the harness *is* outside those rules;
  what is missing is not a prohibition but an enforcement of the rule that does
  apply. §8 decides what does bind it.
- **"embeddings are not part of this question" — holds.** The production
  embedder is on-device FastEmbed over a vendored model (ADR-0024), so
  embedding the corpora is a $0 line either way and `Embedder` is untouched here.

### What the vendor surface actually offers, and what it does not

Read rather than assumed, because the shape of the contract turns on it:

- **pydantic-ai exposes no message-batch surface.** The installed
  `pydantic-ai-slim` 2.11.0 has no batch submission API; its only "batch"
  references are unrelated (tool batching, embedding batches). So the
  implementing lane cannot reach a batch through the library `models/` already
  wraps.
- **Both vendor SDKs do**, and both are already installed by the two extras
  ADR-0061 §1 ships: `anthropic/resources/messages/batches.py` and
  `openai/resources/batches.py`.
- **Anthropic's Message Batches API is submit-then-poll by construction**: a
  batch is created, its `processing_status` is polled until `ended`, and results
  are then streamed. Requests are **non-streaming by construction**, results
  arrive in **any order** and must be keyed by the caller's `custom_id`, each
  result is one of *succeeded / errored / canceled / expired*, batches complete
  within a bounded processing window, results are readable only for a bounded
  retention period after creation, and a batch is size-bounded in both request
  count and bytes.
- **Batch is a capability a platform may not offer.** The Message Batches
  endpoint is a first-party Claude API surface and is not available on every
  platform a `default_model` string could name.

That last point is the same sentence `Embedder`'s docstring already uses about
embedding, and it is the hinge of §1.

### What already binds, and is not relitigated here

- **Golden rule 4** — provider SDKs live only in `models/`. The `provider SDKs
  are confined to the models layer` contract lists every package *except*
  `ai_assistant.models` as a source, so a direct vendor import inside `models/`
  is already permitted and needs no contract edit.
- **Golden rule 5 and ADR-0015 §5** — a Protocol change is a breaking change,
  its ADR is ratified and merged as its own PR before anything implements
  against it. This document is that PR.
- **ADR-0137 §2** — where a slice's cut falls at a contract seam, "the contract
  triad together with its **primary production implementation** is one unit of
  work — one lane, one PR", and primary means "the consumer whose demands shape
  the contract".
- **ADR-0060 and ADR-0065** — stated in `core/protocols.py` as binding on every
  Protocol in the file. A new Protocol inherits both without restating them.
- **ADR-0066 §3** — a malformed argument at the model seam is "neither
  ``retryable`` nor ``routable``, because a malformed argument reproduces
  identically on every attempt from every route".
- **Inference runs in worker processes, never the hub** (#1029). Nothing here
  puts a batch in the hub, and §8 keeps it that way structurally.

### The ADR-0042 §1 objection, answered before it is raised

ADR-0042 §1 declined a Protocol and gave a test this decision must survive: "A
new Protocol is not a free annotation: it obliges a shared conformance suite and
a canonical fake … That machinery earns its cost when many implementations must
be held to one contract."

By a headcount of implementations, a batch seam looks like the case §1 refused —
one real implementation plus its fake. Two things separate them, and both are
checkable rather than rhetorical.

First, **§1's own reasoning turns on an import that is already allowed**: "the
adapter → engine edge is not that shape … `lint-imports` already permits the
import. A Protocol between them would model a substitutability that does not
exist." Here the equivalent import is the one golden rule 4 exists to forbid.
The Protocol is not modelling substitutability between providers; it is the
mechanism by which a consumer depends on the *capability* without depending on
`models/`'s concrete or on a vendor SDK. Remove the Protocol and there is no
legal edge left.

Second, **`Embedder` is the ratified precedent with the same headcount** — two
shipped implementations, one of them (`HashingEmbedder`) explicitly a
deterministic stand-in — and it was made a sibling Protocol for precisely the
reason that applies here.

## Decision

### 1. Bulk inference is a new sibling Protocol; `ModelProvider` is not widened

> **Normative.** Bulk inference is introduced as a **new Protocol** in
> `core/protocols.py`, named `BatchCompleter`. No member is added to
> `ModelProvider`, no existing member of `ModelProvider` changes signature or
> clause, and `BatchCompleter` does not inherit from `ModelProvider`. An object
> may implement both; nothing requires that it does.

Three grounds, in the order a reviewer should check them.

**The authoring guideline in the file says so.** `core/protocols.py`'s module
docstring: "Prefer adding a new Protocol over widening an existing one." A
preference is rebuttable, and the two grounds below are why it is not rebutted
here.

**ADR-0021 §3 already ruled on this exact fork.** Deciding how to extend
`ActionPolicy` for a second request shape, it wrote: "**widening `decide`'s
parameter is breaking; adding a second Protocol beside `ActionPolicy` is
additive.** … A separate Protocol takes nothing away from anyone and is
therefore the presumptive shape, and it is named as such rather than left to be
discovered." The same asymmetry holds one step stronger here, because `Protocol`
is structural: a new *member* on `ModelProvider` silently unsatisfies every
existing structural implementation at once — `PydanticAIProvider`,
`RetryingProvider`, `RoutingProvider`, the canonical `FakeModelProvider`, and
every test double — and, since `ModelProvider` is `@runtime_checkable`, changes
what `isinstance` answers about all of them.

**A batch is a capability a provider may not offer, which is `Embedder`'s exact
ground.** pydantic-ai — the library the seam is built on — exposes no batch
surface at all, and the vendor endpoint that does is not available on every
platform a `default_model` string may name. A member on `ModelProvider` would
assert of *every* route a capability most routes cannot honour, and would oblige
`RetryingProvider` and `RoutingProvider` to forward an operation neither one's
policy fits: retrying a job measured in hours is not what `RetryingProvider`
means, and routing a batch to a fallback provider is incoherent because a handle
issued by one provider is meaningless to another (§2).

### 2. The seam is submit / poll / fetch, and the handle is the caller's

> **Normative.** `BatchCompleter` declares exactly three `async` members:
> `submit`, which takes the batch's items and an optional `"provider:model"`
> override and returns a `BatchHandle`; `poll`, which takes a `BatchHandle` and
> returns a `BatchStatus`; and `fetch`, which takes a `BatchHandle` and returns
> the batch's `BatchItemOutcome`s. No fourth member is declared.

> **Normative.** None of the three members waits for the batch to finish. Each
> returns after one round trip to the provider, and no implementation may
> satisfy `poll` or `fetch` by sleeping until the batch settles. Waiting is the
> caller's loop, over `poll`.

> **Normative.** A `BatchHandle` is valid only against the `BatchCompleter`
> instance that issued it. Presenting a handle to any other instance is a caller
> error, and an implementation that detects it raises `ModelError` with the
> disposition ADR-0066 §3 fixes for a malformed argument — neither `retryable`
> nor `routable` — rather than returning an outcome.

**This is the clause that was genuinely open, and cancellation decides it.**
The alternative — one awaitable that hides the polling, `await
complete_all(items)` — is more pleasant to call and is the shape "I/O-bound
methods are `async`" might seem to suggest. It fails on the clause immediately
above it in the same file. ADR-0060 binds every Protocol here: "**A method that
acquires a resource must not orphan it under cancellation** … at the moment
``CancelledError`` leaves that method, every such resource is either released,
or still held exclusively by work the method started and can observe finishing",
and "**A cancelled call's effect is indeterminate to the caller.**"

A submitted batch is exactly such a resource: it is remote, it outlives the
coroutine, it is being billed, and it cannot be released by returning. A single
awaitable that is cancelled — by a deadline, a `KeyboardInterrupt`, or a worker
process dying — orphans a paid job whose only identifier existed inside the
frame that just unwound. There is no shape of a bare awaitable that hands the
identifier back on the cancellation path. Three members put the handle in the
caller's hands **before any waiting begins**, so the worst a cancellation costs
is the wait.

The one-event-loop rule cuts the same way rather than the other. A suspended
coroutine is cheap, so hiding a multi-hour wait would not by itself stall the
loop — but it would make the wait un-restartable across a process boundary,
and #1029's consumer is a long-running harness that will be interrupted and
resumed. A handle that survives in a file is what makes the resumption possible,
and the provider's own bounded results retention is what makes a later `fetch`
meaningful.

### 3. An item is well-formed on `complete`'s terms, and identified by the caller

> **Normative.** Each item's messages satisfy the same precondition
> `ModelProvider.complete` states on its `messages` argument, read as that
> docstring states it — a necessary condition, not a sufficient one, admitting
> nothing by omission. `submit` validates every item before contacting any
> provider and refuses the **whole batch** if any item fails, raising
> `ModelError` with ADR-0066 §3's disposition. It never submits the well-formed
> subset.

> **Normative.** Every item carries a caller-minted `item_id`, unique within its
> batch. `submit` refuses a batch containing a duplicate `item_id`, on the same
> terms and with the same disposition as the clause above. An implementation
> never mints, rewrites or normalises an `item_id`.

Refusing whole rather than partially is the choice that costs something and is
taken deliberately: a partially-submitted batch is a paid job the caller did not
ask for and cannot describe, and the caller's own record of what it submitted
would be wrong. Validating before contact is what makes the refusal free.

### 4. Every item ends in exactly one of four outcomes, matched by id

> **Normative.** For a batch whose `poll` has reported the terminal state,
> `fetch` returns exactly one `BatchItemOutcome` per submitted item — no more,
> no fewer, and none for an `item_id` that was not submitted.

> **Normative.** An outcome's kind is exactly one of four: `SUCCEEDED`, which
> carries the assistant's reply as a `Message`; `FAILED`, which carries a
> `BatchItemFailure` and no message; `EXPIRED`, which carries neither and means
> the provider's processing window of §6 closed before the item ran; and
> `CANCELLED`, which carries neither and means the batch stopped by an act
> outside this seam.

> **Normative.** The order in which `fetch` returns outcomes is unspecified and
> an implementation is not required to make it stable. A caller matches an
> outcome to its request by `item_id` and never by position.

The taxonomy is the seam's own and is justified by what a caller must *do*
differently with each: read a result, decide on a disposition, resubmit the item
in a new batch, or stop. That it agrees with what both vendor SDKs report is
convergence on the same four underlying facts about a unit of work, not a vendor
shape crossing the seam — nothing in `BatchItemOutcome` carries a vendor status
string, error code, or response envelope.

`CANCELLED` exists although §10 gives the seam no cancel. A batch can be stopped
out of band — an operator in a vendor console, an account action — and an
outcome vocabulary with nowhere to put that fact would force an implementation
to report it as `FAILED` or `EXPIRED`, both of which are false and one of which
carries a disposition that would be acted on.

### 5. A failed item is a value, and its disposition is `ModelError`'s

> **Normative.** A single item's failure is **returned** as a `FAILED`
> `BatchItemOutcome`, never raised. `fetch` raises only for a fault of the fetch
> itself — the handle, the transport, the retention window of §6 — and never
> because some items failed.

> **Normative.** `BatchItemFailure` carries a `BatchFailureKind`, an enum of
> exactly seven members, each declaring the `retryable` and `routable` flags
> `core/errors.py` declares for the model-error class it corresponds to:
> `AUTHENTICATION` (routable only, as `ModelAuthError`), `RATE_LIMITED` (both,
> as `ModelRateLimitError`), `UNAVAILABLE` (both, as `ModelUnavailableError`),
> `CONTENT_FILTER` (neither, as `ModelContentFilterError`), `UNUSABLE_RESPONSE`
> (routable only, as `ModelResponseError`), `UNKNOWN` (neither, as a bare
> `ModelError`), and `INVALID_REQUEST` (neither, which corresponds to no class
> but takes ADR-0066 §3's disposition for a malformed request). The
> dispositions are read from an exhaustive mapping over the enum, in the shape
> `core/types.py` already uses for `ToolFailureKind`, so that adding a member
> without a disposition fails rather than defaults.

Returning rather than raising is forced by the same reasoning ADR-0029 §8 gives
and `ToolBindingError`'s docstring quotes: "an exception has no
``failure.kind.retryable`` to read, so there is nothing for a retry decision to
be made from". A batch's whole point is that one item's refusal must not
destroy the other 1,985 results, and an exception is not a container that can
hold 1,986 answers.

Mirroring `ModelError`'s vocabulary rather than minting a fresh one is what
keeps a caller's retry logic the same whether an answer came through `complete`
or through a batch. The correspondence is deliberately not a bijection, and both
gaps are decisions. There is **no** counterpart to `ModelTimeoutError`: a batch
item has no per-request deadline of its own, and the only clock over it is the
processing window of §6, whose exhaustion is the `EXPIRED` outcome of §4 rather
than a failure. An `EXPIRED` item is resubmitted in a new batch; that is a
caller's action on a new batch, not a retry of this one. And `INVALID_REQUEST`
corresponds to no error class because at the `complete` seam a malformed request
is *raised* under ADR-0066 §3 and never returned — here §3's whole-batch refusal
covers the malformed items `submit` can see, and `INVALID_REQUEST` is what
remains for an item a provider rejects for a reason `submit` could not check.

### 6. There are two expiries, they are different, and neither is silent

> **Normative.** The **processing window** — the provider's bound on how long it
> will attempt an item — is reported per item, as §4's `EXPIRED` outcome, and
> nowhere else. The seam fixes no duration for it.

> **Normative.** The **results retention** — the provider's bound on how long a
> settled batch's outcomes remain fetchable — is reported per batch, as
> `BatchStatus.results_expire_at`, which is `None` when the implementation
> cannot state one. `fetch` called against a batch whose retention has lapsed
> raises `ModelError`; it never returns an empty or short set of outcomes, and
> it never reports a lapsed item as `EXPIRED`.

Conflating these two is the failure this section exists to prevent, and the
dangerous half is the second: a `fetch` that quietly returns 900 outcomes for a
1,986-item batch would be read as 1,086 expired items, and the benchmark built
on it would report a score for a run that never happened. Raising is the only
answer that cannot be silently mis-scored, and it is the direction the
cancellation clause's "the caller may assume neither" already points.

### 7. The seam fixes no size bound, and says so

> **Normative.** `BatchCompleter` fixes no maximum item count and no maximum
> byte size for a batch. `submit` **may** refuse an over-large batch, and when
> it does it raises `ModelError` with ADR-0066 §3's disposition and states the
> bound it applied. A caller is obliged to be prepared to split.

A number here would be one vendor's limit written into a model-agnostic
contract, and it would be wrong for the next implementation on the day it
landed. Naming the refusal without naming the number is what makes the caller's
obligation real without making the contract false.

### 8. Who may call it, and how a consumer outside `ai_assistant` reaches it

> **Normative.** A consumer depends on `BatchCompleter` — the `core` Protocol —
> and on the `core` types of §9, and never on a concrete class in `models/` for
> its *types*. It obtains an instance by construction in a composition root it
> owns: `ai_assistant.app` for an in-package consumer, and its own root for a
> consumer outside `ai_assistant`. No subsystem is given a `BatchCompleter` by
> this ADR.

> **Normative.** Neither this ADR nor its implementing lane edits any
> `[tool.importlinter]` contract. `ai_assistant.models` is already absent from
> the `provider SDKs are confined to the models layer` contract's
> `source_modules`, so a direct vendor-SDK import inside `models/` needs no
> exemption, and no other package acquires one.

> **Normative.** A batch runs in the process that submits it and never in the
> hub. No `BatchCompleter` is wired into `ai_assistant.service`, and no
> scheduler job polls one.

The mechanism that holds golden rule 4 over a consumer living outside
`src/ai_assistant/` is **not** `lint-imports`, and a lane must not assume
otherwise: `root_package = "ai_assistant"` means such a tree is not in the graph
at all. Holding the rule there is that tree's own lane's obligation — the
benchmark harness lane of #1029 carries an AST-parsing check for exactly this —
and this ADR neither creates nor amends it, which is why §11 files it as a
condition rather than a deliverable.

The last clause is #1029's "all inference in worker processes, never the hub"
made structural rather than remembered. It is also why §2's handle shape is not
merely tidy: a hub-resident poll loop is precisely the thing this forbids, and a
seam whose only shape was a hidden multi-hour await would have made the
forbidden thing the easy one.

### 9. The public types this decides, and where they land

> **Normative.** The implementing lane adds exactly **eight** public names to
> `core/types.py`, as pydantic models or `StrEnum`s per `CLAUDE.md`'s
> convention, spelled to the conventions already in that file: `BatchRequest`
> (`item_id`, `messages`); `BatchHandle` (`batch_id`, `submitted_at`,
> `item_count`); `BatchState` (`PENDING`, `COMPLETE`); `BatchStatus` (`handle`,
> `state`, `settled`, `results_expire_at`); `BatchOutcomeKind` (§4's four
> members); `BatchItemOutcome` (`item_id`, `kind`, `message`, `failure`);
> `BatchFailureKind` (§5's seven members); and `BatchItemFailure` (`kind`,
> `detail`). No other public name is added to `core/types.py` by that lane.

> **Normative.** `BatchItemOutcome` binds its optional fields to its kind: a
> `message` is present if and only if the kind is `SUCCEEDED`, and a `failure`
> is present if and only if the kind is `FAILED`. The binding is validated by
> the type, not left to the caller.

> **Normative.** Under ADR-0137 §2 the `BatchCompleter` triad — the Protocol,
> the shared `BatchCompleterContract` conformance suite, and the canonical
> `FakeBatchCompleter` in `ai_assistant.testing` with its `Test…Contract`
> subclass — rides in **one lane and one PR together with its primary
> production implementation**, which is the Anthropic-backed `BatchCompleter`
> in `models/`. The primary *consumer* whose demands shape the contract is the
> memory-benchmark harness of #1029/#1034, and it is a **follow-on consumer
> group** under ADR-0137 §4, briefed only after the paired lane merges.

The naming is not free choice: `tests/core/test_protocol_triad.py` derives the
suite and fake names from the Protocol's, so `BatchCompleter` fixes
`BatchCompleterContract` and `FakeBatchCompleter` mechanically. The suite's
location follows the sibling seams' — `tests/models/model_provider_contract.py`
and `tests/models/embedder_contract.py` — and §13's table is where that lane's
obligations are enumerated.

Naming the primary implementation rather than the primary consumer as the
paired half is a deliberate reading of ADR-0137 §2, and it is the reading the
tree forces. §2 pairs the triad with "the consumer whose demands shape the
contract"; here that consumer lives outside `ai_assistant` entirely, so pairing
it into the triad's lane would put the contract, the vendor implementation and a
new harness subsystem in one review — the compounding ADR-0137 §1 exists to
stop. The vendor-backed implementation in `models/` is the first real caller of
every clause above and is what stress-tests the contract while it is still soft;
the harness follows under §4.

### 10. What this seam does not promise

> **Normative.** `BatchCompleter` makes no promise about, and no implementation
> may be relied on for: streaming (a batch is non-streaming by construction, and
> partial results before the terminal state are not offered); tool use (each
> item inherits `ModelProvider.complete`'s position that nothing at the model
> seam promises tool support, and a `Role.TOOL` turn is not representable in an
> item); prompt-cache behaviour across items or across batches; cancelling a
> submitted batch; a per-item model override; ordering (§4); a size bound (§7);
> or a handle's meaning to any provider other than its issuer (§2).

Cancellation is the one worth its own sentence, because §4 keeps a `CANCELLED`
outcome and a reader will ask why the seam does not offer the verb. A cancel at
this seam could promise only that we asked: work already in flight is billed,
the vendor's own cancel is a best-effort transition rather than a stop, and the
caller's real remedy — stop polling and let the window close — costs nothing and
is already available. A contract member whose only honest guarantee is "the
request was sent" is weaker than no member, because it reads as a stop.

### 11. Deferred, by name, each with the condition that fires it

Each of these is out of scope here and is a decision, not an oversight. None is
normative; each names what would fire it.

- **A `cancel` member (§10).** Fires if a consumer is found that must stop a
  batch it can still be billed for and cannot wait out the window — that is, if
  batch sizes grow enough that a wrong submission is worth money to abort.
- **A per-item model override (§10).** Fires with the first ablation that needs
  two models compared inside one batch. Until then the per-batch override of §2
  matches #1029's fixed-model configuration, and keeps one handle to one route.
- **A second vendor implementation.** Fires when a deployment's `default_model`
  names a vendor whose batch endpoint we intend to use. §12 records why
  ADR-0061 §3's two-vendor obligation does not reach this seam today.
- **Wiring a `BatchCompleter` into `ai_assistant.app` or any subsystem.** Fires
  when a subsystem — not a harness — needs bulk inference. Nothing in the
  product asks for one today, and §8's third clause is what keeps a speculative
  wiring from arriving in the hub.
- **Enforcing golden rule 4 over `benchmarks/` (§8).** Not deferred by this ADR
  at all: it is the #1029 harness lane's obligation, recorded here so a later
  reader does not look for it in this seam's lane.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is applied to each ADR this decision touches: would a reader
holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

- **ADR-0021 — nothing owed.** §3's sentence is *applied*, not narrowed: it says
  "adding a second Protocol beside `ActionPolicy` is additive", and §1 above
  follows that presumption for a different Protocol. No clause of ADR-0021
  becomes false.
- **ADR-0042 — nothing owed.** §1's refusal is explicitly of "an **engine-facing**
  Protocol", argued from the adapter→engine edge already being a permitted
  import. `BatchCompleter` is a subsystem contract of the shape golden rule 1
  exists for, across an edge golden rule 4 forbids. §1's sentence stays true of
  everything it was stated about.
- **ADR-0061 — nothing owed, and its §3 is not widened.** §3 is stated about one
  suite by name: "The `ModelProviderContract` suite now runs three bindings".
  A new sibling Protocol with a one-vendor binding does not make that sentence
  false, and this ADR does not read §3 as an obligation on every future
  model-layer Protocol. §11 records the condition that would fire a second
  vendor binding here.
- **ADR-0060 and ADR-0065 — nothing owed, and both are inherited.** Both are
  stated in `core/protocols.py` as binding on "**every** Protocol below", so a
  new Protocol is covered on the day it lands and neither clause needs
  amending. ADR-0060 is the clause §2 is decided *by*; ADR-0065 is largely
  vacuous here, since every argument at this seam is an immutable pydantic model.
- **ADR-0066 — nothing owed.** Its §3 disposition is *cited* for §3, §6 and §7's
  refusals rather than altered; its clauses remain stated about `complete`.
- **ADR-0137 — nothing owed, and §2 and §4 are applied.** §9 uses §2's pairing
  and §4's consumer-group sequencing exactly as written.
- **This is a stacked addition** in ADR-0082 §1's sense — "Adding an obligation
  that contradicts no sentence the earlier ADR wrote … is recorded in the ADR
  that makes it, and nowhere else" — so **no `Status` line of any earlier ADR is
  edited by this PR**, and this ADR's own diff is one new file.
- **This ADR's `Status`.** It decides `core` Protocol surface and `core/types.py`
  values, so the required review set is adversarial **and** architecture
  (ADR-0015 §1). The ratification sequence is `CONTRIBUTING.md` → "Finishing an
  ADR PR": drafted, reviewed and revised as `Proposed`, both lenses returning
  clean on one tree, the status flipped to `Accepted` on one physical line, and
  both lenses re-run on the flipped tree. Nothing implements against this ADR
  until it has merged.

### 13. The work order: what the implementing lane owes

The table below is the audit. Every normative clause of §1–§10 appears in it
exactly once, and every row names something a reviewer can run. The count is
21 rows against the 23 marked clauses in this ADR; the remaining two sit below
the table, are obligations *about* the table and the suite that satisfies it,
and so have no rows of their own.

| Clause | Deliverable | Test item |
|---|---|---|
| §1 | `BatchCompleter` in `core/protocols.py`; `ModelProvider` byte-unchanged | `test_protocol_triad.py` passes for the new Protocol; a test asserts `ModelProvider`'s member set is unchanged |
| §2 (members) | `submit`/`poll`/`fetch`, all `async`, and no fourth member | Contract case: the Protocol's member set is exactly those three |
| §2 (no waiting) | Each member returns after one round trip | Contract case: `poll` against a still-pending batch returns `PENDING` promptly rather than blocking |
| §2 (handle ownership) | Foreign-handle detection in the implementation | Contract case: a handle from a second instance raises, neither `retryable` nor `routable` |
| §3 (well-formedness) | Pre-contact validation of every item | Contract cases: an empty history, a history ending on `Role.ASSISTANT`, and a history containing a `Role.TOOL` turn each refuse the whole batch with nothing submitted |
| §3 (unique ids) | Duplicate-`item_id` refusal | Contract case: a duplicate refuses; a test asserts `item_id`s round-trip unrewritten |
| §4 (one per item) | Outcome assembly keyed by `item_id` | Contract case: a mixed batch returns exactly one outcome per item and none extra |
| §4 (four kinds) | `BatchOutcomeKind` and its payload rules | Contract cases: one case per kind, asserting the carried payload |
| §4 (order) | — | Contract case: the fake returns outcomes in a shuffled order and the suite still passes, proving no positional assumption |
| §5 (returned not raised) | `FAILED` outcomes in the returned set | Contract case: a batch with a failing item still returns the other items' results and raises nothing |
| §5 (seven kinds) | `BatchFailureKind` + exhaustive disposition mapping | A test asserts the mapping is exhaustive over the enum and matches `core/errors.py`'s flags class by class |
| §6 (window) | `EXPIRED` mapping from the vendor's expired result | Contract case: an expired item is `EXPIRED`, never `FAILED` |
| §6 (retention) | `results_expire_at` + lapsed-fetch refusal | Contract cases: `results_expire_at` is surfaced; a lapsed `fetch` raises and never short-returns |
| §7 (size) | Over-large refusal naming its bound | Contract case: an implementation-declared over-large batch refuses with the right disposition |
| §8 (dependency direction) | Vendor SDK imported only under `models/` | `uv run lint-imports` passes unchanged; a test asserts the new `core` module imports no vendor package |
| §8 (no contract edit) | `pyproject.toml`'s `[tool.importlinter]` untouched | The lane's diff contains no `pyproject.toml` importlinter hunk |
| §8 (not the hub) | No `service`/`app` wiring | A test asserts `ai_assistant.service` holds no `BatchCompleter` |
| §9 (eight types) | The eight names in `core/types.py` | A test asserts exactly those eight names are added and each is exported as the file's conventions require |
| §9 (kind/payload binding) | `BatchItemOutcome` validator | A test asserts each of the four kinds rejects the wrong payload combination |
| §9 (triad + primary) | `BatchCompleterContract`, `FakeBatchCompleter`, `Test…Contract`, and the `models/` implementation, in one PR | `test_protocol_triad.py` is the mechanical check; the suite runs against both the fake and the real implementation |
| §10 (no promises) | Docstring clauses stating each exclusion | A test asserts a `Role.TOOL` turn in an item is refused, matching `complete`'s position |

> **Normative.** The paired lane of §9 satisfies every row of the table above,
> and adds no row to it: a deliverable the table does not name is out of that
> lane and is filed as an issue.

> **Normative.** The vendor binding of the `BatchCompleterContract` suite runs
> offline against the real vendor SDK with only the transport replaced, inside
> `network_denied()` and with a literal dummy credential — the technique
> ADR-0061 §3 established and `tests/models/network_guard.py` and
> `tests/models/test_provider_vendors.py` already carry. No row of the table is
> satisfied by a test that reads a real credential or opens a socket.

## Consequences

**Easier.**

- **The full LongMemEval-S run becomes affordable at the ruled discount** without
  a single vendor import escaping `models/`. That was #1034's whole question and
  §1 and §8 together answer it.
- **A consumer outside `ai_assistant` has a legal edge to the capability.** Before
  this, the harness had a choice between a golden-rule-4 violation and paying 2×;
  §8 gives it a third option that is checkable rather than trusted.
- **A cancelled or crashed wait costs the wait, not the batch.** §2's handle is
  what makes a long benchmark run resumable, and it is the difference between
  losing an hour and losing the money.
- **Retry logic is the same on both seams.** §5's one-to-one mapping onto
  `ModelError` means a caller that already reasons about `retryable`/`routable`
  needs no second vocabulary.

**Harder, and accepted.**

- **The caller writes the poll loop.** §2 hands the caller a loop it did not have
  to write against a `complete`-shaped seam, including choosing a poll interval.
  Accepted: the loop is a dozen lines, and the alternative orphans paid work
  under cancellation.
- **A triad for one real implementation.** §1 buys `Embedder`'s shape and pays
  `Embedder`'s cost — a conformance suite and a canonical fake for a Protocol
  with one production implementation. Accepted on the ADR-0042 §1 analysis in
  Context: the Protocol is the mechanism golden rule 4 leaves, not a bet on
  future substitutability.
- **`models/` acquires a direct vendor-SDK import for the first time.** Every
  module there reaches vendors through pydantic-ai today, and the batch endpoint
  has no pydantic-ai route. This is permitted by construction — the contract's
  `source_modules` already exclude `models/` — but it is a real widening of what
  that package touches, and it means a vendor-SDK upgrade can now break a second
  surface.
- **Eight new public types in `core/types.py`** on a file that is already large.
  Accepted because every one of them crosses a subsystem boundary and
  `CLAUDE.md`'s convention leaves no other home; §9 caps the count so the lane
  cannot quietly grow it.

**Revisit when.** Two conditions, and the second is the one to watch. If a
second vendor's batch endpoint is wired and the contract needs bending to fit
it, §1's "capability a provider may not offer" framing was right but the
member shapes in §2 were drawn too close to one vendor — reopen §2, not §1. And
if a *subsystem* rather than a harness turns out to need bulk inference, §8's
third clause is the one to re-argue first, because a batch in the hub is a
different decision from a batch in a worker and this ADR only decided the
second.

## Alternatives considered

**Widen `ModelProvider` with the three members.** Rejected under §1. It is the
reading of #1034's option 1 that its wording most invites — "extend the
`ModelProvider` contract" — and it is the one the corpus already ruled against
in ADR-0021 §3 and the one `core/protocols.py`'s own guideline discourages. The
decisive detail is structural typing: a new member unsatisfies every existing
implementation and every test double simultaneously, and obliges two decorators
to forward an operation neither one's policy fits.

**One awaitable that hides the polling.** Rejected under §2, on ADR-0060 rather
than on taste. It is genuinely the nicer call site, and if batches were seconds
long it would be the right answer.

**#1034's option 2 — a benchmark-only batch runner inside `models/`, no
Protocol.** Not this ADR's to choose (the owner ruled option 1), but worth
recording why the ruling holds up: the harness would depend on a concrete class
in `models/`, which is the dependency golden rule 1 exists to prevent, and the
`lint-imports` finding above means nothing would have caught it. It also puts
the benchmark's fixture code inside the shipped wheel.

**#1034's option 3 — eat the 2×.** Defensible while the full run is a one-time
event, and it is what the #1029 pilot does. It stops being defensible the moment
a second scored run is wanted, and the benchmark list in #1029's decision rule
has more than one entry.

**Fix a size bound in the contract (§7).** Rejected: a number here is one
vendor's limit written into a model-agnostic contract, wrong for the next
implementation on the day it lands.

**Return outcomes in submission order.** Rejected under §4. It would be a
convenience the seam cannot honestly provide — the vendor's results arrive
unordered, so an implementation would have to buffer the whole batch to sort it,
and the caller must key by `item_id` regardless because §4 admits kinds that
carry no message. A promise that forces a buffer and changes no caller's code is
a cost with no purchase.
