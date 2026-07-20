# 22. The closed learning loop in `orchestration`

- Status: Accepted
- Date: 2026-07-20

## Context

`orchestration` was a docstring. Every contract the first vertical needs has
landed — `ContextProvider` (ADR-0008), `MemoryStore`/`MemoryPolicy` (ADR-0005 to
ADR-0007), `Planner` (ADR-0014), `FeedbackProcessor` (ADR-0009) — and
[`docs/roadmap.md`](../roadmap.md) §"The first vertical" asks for one loop that
exercises them together:

```text
conversation
  → retrieve relevant user context
  → generate a response or plan
  → observe the user's correction
  → propose a preference update (policy accepts it)
  → use that preference successfully next time
```

Three forces shape how it is built.

1. **`orchestration` may import no concrete subsystem** (golden rule 1). It
   receives implementations by injection and sees them only through `core`
   Protocols. That is not a style preference here: it is the property being
   tested, since a loop that reaches for `memory.MemoryIngestor` would prove the
   contracts *insufficient* rather than prove the pipeline works.
2. **Nothing is invocable.** ADR-0016 §7 deferred `Tool.invoke`, and no `Tool`
   Protocol exists. Tool selection, permission checking and execution — the
   middle of `CLAUDE.md`'s pipeline — therefore have no honest implementation
   available, whatever the eventual shape.
3. **Every stage can fail, and they do not all mean the same thing.** A missing
   memory and a missing context are both "a stage yielded nothing", and treating
   them alike would either abort turns that were answerable or answer turns that
   were not.

## Decision

We will add `LearningLoop` to `ai_assistant.orchestration`, wiring the five
contracts above into two entry points.

### 1. Two calls, not one

`respond(utterance) -> TurnResult` answers; `learn(event) -> tuple[MemoryIngestResult, ...]`
observes. Separate calls, because a correction arrives whenever the user gets
round to it — usually not within the turn it corrects. A single method taking
optional feedback would force the caller to model a conversation as a sequence
of paired turns, which it is not.

Tool selection, permissions and execution are **out of scope for this loop** and
join the pipeline when the subsystems can invoke something. This is a scope
decision, not a claim that the pipeline is complete.

### 2. Stage order, and what each stage may use

`respond` runs: **intent → context → memory retrieval → planning**, the order
`CLAUDE.md` states. Each stage may use only what the ones before it produced.

- **Intent** is the utterance taken *verbatim* as the goal's statement. No
  inference happens: inferring intent needs a model, and no contract offers
  intent extraction. The goal's provenance is `USER_ASSERTED` — the user said
  it — which is exactly the distinction `Goal` (ADR-0014 §1) exists to preserve.
- **Retrieval** is scoped by the goal statement, so it depends on intent.
- **Planning** is handed the context and the memories rather than fetching them,
  because a planner that fetched them would import two subsystems it has no
  business importing (`Planner`, ADR-0014 §6). Retrieved memory is what makes a
  plan personal rather than generic.

Retrieval is *not* run concurrently with context assembly. The saving is one
round trip; the cost would be that a later retrieval which reads the context —
time of day, attention, urgency — becomes a re-plumbing rather than a change of
argument.

`TurnResult` is a frozen dataclass in `orchestration`, not a pydantic model in
`core/types.py`, because it crosses no *subsystem* boundary: only `interfaces`,
which already depends on this package, ever sees one. It graduates to `core` the
day a subsystem must receive one.

### 3. Failure behaviour, stage by stage

The rule is: **a stage aborts the turn when continuing would require inventing
something; otherwise it degrades and says so.**

| Stage | On failure | Why |
| --- | --- | --- |
| Intent | `PlanningError` | A blank utterance is a request that cannot become a plan. Raised as an `AssistantError` rather than letting `Goal`'s validator surface a `ValidationError`. |
| Context | propagate `ContextError` | Assembly already degrades a failing optional source internally (ADR-0008), so a raised error is a wiring fault. The alternative — fabricating a situation the planner then treats as fact — is worse than stopping. |
| Retrieval | degrade to no memories, `memory_degraded=True` | Losing memory costs the answer its personalisation, not its usefulness. |
| Planning | propagate `PlanningError` | There is no turn without a plan. |
| Learning | propagate | See §4. |

`memory_degraded` is on `TurnResult` rather than only in a log line because an
unpersonalised answer is the one degradation a user of *this* system most
deserves to be told about: the accumulated user model is the product, so
silently answering generically is the failure that looks most like success.

### 4. The write path, and what "nothing was written" means

`learn` runs each proposal through the same three steps `MemoryIngestor` does —
resolve conflicts from the store, ask the policy, apply the ruling — because
the model never writes memory directly (VISION §7).

- **`ACCEPT`** writes the record. **`STORE_TEMPORARY`** writes it with
  `expires_at` stamped from the injected clock.
- **`REJECT` and `ASK_USER`** write nothing, and are reported with a `None`
  record id.
- **`MERGE` is reported but not applied.** Folding two records into one is
  `memory`'s own semantics; it lives in `MemoryIngestor`, which golden rule 1
  forbids this package from importing, and re-deriving the fold here would fork
  it. The decision and a `None` record id are returned, so a caller sees exactly
  what was ruled and that nothing was stored. This is a known gap, not a
  silently dropped update — see Consequences.
- **No proposals** is a normal outcome, not an error: ADR-0009 defers episodic
  and procedural targets, so a processor legitimately proposes nothing.

Proposals are applied in order and independently. There is no transaction,
because `MemoryStore` offers none; a store failure therefore propagates with
earlier proposals already applied. Reporting success for a partially applied set
would be a claim about memory integrity this loop cannot make.

### 5. Determinism

The clock and the goal-id factory are injected (`CONTRIBUTING.md` →
"Determinism"), so a turn is reproducible and the tests assert exact ids and
timestamps rather than shapes.

## Consequences

**Easier.** The first vertical closes: a test learns a preference from a
correction and demonstrates the planner is handed it on the next turn — the
roadmap's acceptance criterion, as an assertion rather than a claim. Every
collaborator being a Protocol means the same engine runs against the canonical
fakes and against the real subsystems, and swapping a `Planner` or a
`MemoryStore` is a constructor argument.

**Harder — and this is the finding.** Building the loop against the existing
contracts worked, but it surfaced three gaps, each filed rather than fixed here:

1. **The memory write path has no `core` Protocol.** ADR-0009 §Context already
   named this ("`MemoryIngestor` is concrete in `memory/`, not a `core`
   contract… the pipeline wires them to the ingestor") and left it for the
   pipeline. The pipeline now exists and cannot wire to the ingestor: it must
   re-derive conflict detection and lose `MERGE` entirely. A `MemoryWriter`
   Protocol — one `ingest(proposal) -> MemoryIngestResult` method, satisfied by
   `MemoryIngestor` — would let `orchestration` reuse the real write path and
   would delete this loop's duplication and its `MERGE` gap together. That is a
   `core` change and belongs in its own ADR and PR (golden rule 5). Issue #103.
2. **`MemoryStore` offers no batch or transaction**, so multi-proposal learning
   cannot be atomic (§4). Issue #104.
3. **`FakeMemoryStore` has no configured failure mode**, unlike
   `FakeContextProvider`'s `failure=`, so a consumer testing its degradation
   path must subclass the canonical fake. Issue #105.

**Revisit this ADR** when (1) lands — `learn` then delegates instead of
re-deriving — or when tool invocation exists, at which point selection,
permission checking and execution join `respond` between planning and learning.
