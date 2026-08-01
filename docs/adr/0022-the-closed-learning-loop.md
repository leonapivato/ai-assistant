# 22. The closed learning loop in `orchestration`

- Status: Partially superseded by ADR-0084 (§2's placement of `TurnResult` outside `core/types.py`, and its sole graduation trigger)
- Date: 2026-07-20
- Partially superseded: 2026-07-31 by ADR-0084 — **§2's paragraph on where
  `TurnResult` lives, and on the one condition that would move it, is false;
  nothing this ADR decided about the learning loop changes.**
  [ADR-0084](0084-the-local-api-and-the-cli-as-a-client.md) §5 finds ADR-0042
  §1's revisit trigger fired and promotes the engine façade to a Protocol in
  `core/protocols.py`, which forces its result types into `core/types.py` (golden
  rule 2: a `core` Protocol cannot name an `orchestration` return type). ADR-0042
  §1 is partially superseded there. **This ADR does not cite ADR-0042 — ADR-0042
  §1 cites *it*, by name**, and that is why the clause below was missed three
  times; see the method note at the end.

  **Replaced**, both halves of one paragraph in §2:

  1. "`TurnResult` is a frozen dataclass in `orchestration`, not a pydantic model
     in `core/types.py`". `Engine.converse` and `Engine.resume` return
     `TurnOutcome`, which ADR-0084 §4 names **explicitly** in its promoted set,
     and `TurnOutcome.turn` is `TurnResult | None`
     (`orchestration/engine.py:252`). §4's bound is "the *transitive closure* of
     what the Protocol's methods name, not just the types they return", because "a
     promoted DTO drags every type its fields reach" — the rule that pulls
     `Disposition`, `QuestionState` and `SuccessorLink` along with it. `TurnResult`
     is reached by that same rule, one field in. **The practical consequence,
     which is the whole reason this record exists:** changing a field of
     `TurnResult` was a free `orchestration` edit and is now a `core` contract
     change under golden rule 5, owing an ADR. A reader acting on the superseded
     sentence would ship one without — the process failure ADR-0015 §5 exists to
     prevent.
  2. **The operative one.** "It graduates to `core` the day a subsystem must
     receive one." This is the *sole* trigger, and ADR-0084 §12 has already ruled
     on the identical clause where ADR-0042 §1 restated it — "promotion to `core`
     is reserved for 'the day a subsystem needs to receive one,' which this is
     not" — because §4 promotes for a **transport**, not for a subsystem. That
     ruling lands on this sentence a fortiori: ADR-0042 §1 was quoting ADR-0022
     §2, so the clause superseded there is this one. A reader holding only ADR-0022
     reads its graduation condition more widely than it now holds, which is the
     second limb of ADR-0082 §1's test.

  **Not replaced, and it is nearly everything.** The *reason* half of the
  sentence — "because it crosses no *subsystem* boundary: only `interfaces`,
  which already depends on this package, ever sees one" — stays a true statement
  about where the value travels. What it stops doing is *entailing* the
  conclusion drawn from it, exactly the separation ADR-0077's record makes for
  the same borrowed reasoning. §1's pipeline order, §2's ruling that retrieval is
  not run concurrently with context assembly and why, §3's failure behaviour
  stage by stage, and §§4, 4a and 5 as already amended by ADR-0028 are all
  untouched — ADR-0084 changes nothing about the learning loop. **The exact
  promoted set remains #281's to pin** (ADR-0084 §4 hands it, the field layouts
  and the method signatures to a follow-on contract ADR rather than to an
  implementing lane), so this record states the reach of §4's ratified closure
  rule as the code stands today; it does not pre-empt that ADR's enumeration.

  **Under ADR-0082 §2, the amendment qualifier comes off this line as it takes
  the leading token.** `Accepted, §§4, 4a, 5 amended by ADR-0028` becomes the
  leading-token form ADR-0070 §4 requires for a new partial supersession, and the
  ADR-0028 record stays whole in the `Amended: 2026-07-21 by ADR-0028` note
  directly below, which names §4, §4a and §5 and states each change. Nothing is
  lost by the move; it is ADR-0080 §8's operation as ADR-0082 §2 generalises it,
  and it keeps ADR-0070 §4's extraction invariant true — every `ADR-NNNN` after
  the leading token is a supersession target, so `ADR-0028` could not stay on the
  line.

  **How this clause survived three enumerations, recorded because the method is
  the point.** ADR-0084 §12 corrected a *lexical* search into a semantic one:
  ask, of every ADR that names the superseded one, what it relied on it **for**.
  That is necessary and it is not sufficient. This ADR predates ADR-0042 and
  names it nowhere; the citation runs the other way, ADR-0042 §1 borrowing
  "ADR-0022 §2's reasoning for `TurnResult`" — and ADR-0077 §10 item 7 borrows it
  from ADR-0022 directly. A sweep that walks citations **forward** from the
  superseded ADR cannot reach the ADR a superseded clause was borrowed **from**.
  Whoever next supersedes a premise should walk the citations in both directions
  and search for the premise's own words independently of any ADR number: this
  clause was found by searching for the reasoning ("crosses no … boundary",
  "graduates to `core`"), not by following a reference.
- Amended: 2026-07-21 by ADR-0028 — §4's "MERGE is reported but not applied" is
  withdrawn as a standing limitation. It describes the loop until the
  MemoryWriter triad lands and learn delegates to it; from then a MERGE is
  applied by memory's own fold and reported with the target's record id. §4's
  remaining clauses stand unchanged — ACCEPT, STORE_TEMPORARY, REJECT/ASK_USER,
  "no proposals is a normal outcome", in-order independent application with no
  transaction, the non-atomic search → decide → add across calls (issue #104),
  and last-write-wins on a repeated record id. §4a's conflict-tuning check is
  relocated, not withdrawn: LearningLoop stops taking conflict_limit and
  conflict_threshold, and MemoryIngestor's constructor refuses the same values
  it would have (ADR-0028 §4a). §4a's retrieval_limit check is unaffected. §5's
  injected clock stops stamping expires_at, which the writer's own clock now
  does (ADR-0028 §4b); it still stamps the goal.

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

- **Intent** is the utterance taken *unrewritten* as the goal's statement —
  trimmed of surrounding whitespace, as `Goal`'s own validator would trim it,
  and otherwise untouched. No inference happens: inferring intent needs a model,
  and no contract offers intent extraction. The goal's provenance is
  `USER_ASSERTED` — the user said
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

The same absence makes `search → decide → add` non-atomic *across* calls: two
concurrent `learn`s can both resolve conflicts before either writes, so each
policy rules as though nothing contradicted it and both records land. We do not
serialise on a lock held by the loop. A lock would cover one `LearningLoop`
instance and not two of them, nor a loop sharing a store with `MemoryIngestor` —
an atomicity guarantee that holds only when nothing else writes is worse than a
documented absence, because it reads as protection. The fix belongs to the
contract (issue #104); until then the loop's guarantee is exactly what is
written here.

Ordering also settles collisions: two proposals carrying the same record id
resolve **last-write-wins**, because `MemoryStore.add` is an upsert keyed on id.
The loop does not de-duplicate, because the id is documented as the caller's
idempotency key — a processor re-proposing an id may well mean to supersede its
own earlier proposal, and both outcomes report that id, so the collision is
visible rather than hidden.

### 4a. Tuning is validated at construction

`retrieval_limit`, `conflict_limit` and `conflict_threshold` are checked when the
loop is built, because each bad value *disables a stage while the loop keeps
reporting health*. `retrieval_limit=0` makes `search` return nothing by contract,
so every turn is unpersonalised with `memory_degraded` reading `False` — a
generic answer presented as a healthy personal one, which is precisely what
`memory_degraded` exists to prevent. `conflict_limit=0`, and a `NaN` threshold,
silently hand the policy no conflicts to rule against.

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
