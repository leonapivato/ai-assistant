# Roadmap — orchestration artifacts and build sequence

**Status: working guidance, not a ratified decision.** This document sketches
*where we are going* and *in what order*, so individual slices connect to a
shared picture. Nothing here is binding. Every artifact that crosses a subsystem
boundary (a new `core` type or a Protocol change) is ratified in its own ADR
**before** it is implemented — see `docs/adr/` and the rules in `CLAUDE.md`. If
this roadmap and an ADR disagree, the ADR wins.

## North star

The defining artifact of the product is a **portable personal context graph**: a
user-controlled, model-agnostic representation of a person's goals, preferences,
relationships, projects, routines, and history — usable with any underlying
model. Every subsystem below exists to build, protect, or exploit that graph.
Portability and user control of this graph are already commitments in
[ADR-0004](adr/0004-privacy-and-data-handling.md) (export/delete/data rights).

## Product thesis and priorities

The defensible value is an **accumulated, dynamic user model plus continuous
learning** — personal understanding that compounds over time and cannot be
copied. It is **not** model quality. We do not try to out-answer
GPT/Claude/Gemini on general intelligence; we aim for *"any model might answer a
random question better, but my assistant understands **me** better."* Success
feels like "it knows me," not "it remembers my name."

Two consequences that shape everything below:

- **Model-agnosticism is the strategy, not a preference.** Because the value
  lives in the user model *around* the interchangeable model, the `models/` seam
  ([ADR-0002](adr/0002-foundational-stack-and-architecture.md)) is load-bearing.
- **Trust is upstream of personalization, not polish.** No trust → no access to
  email/calendar/accounts → no behavioural data → no user model. The
  propose/dispose write path, permissions, and transparency are prerequisites
  for the data that personalization needs.

Rough priority ordering (user's ranking): personalization, trust, and continuous
learning (long-term) are the top tier; then memory and context awareness; then
initiative, integrations, and reasoning/planning; then speed and personality.
This is why the sequence favours **one closed learning loop over breadth of
integrations**.

Note on layering: the "user model" the product promises (communication style,
decision patterns, motivations, evolving interests) is largely a **derived view
over** the memory substrate, not individual records. [ADR-0005](adr/0005-memory-model.md)
defines that record substrate; a later ADR will define the derived
user-model projection built on top of it.

## Guiding principle (candidate ADR)

> **The LLM proposes; deterministic services dispose.**

The model is used for what it is good at — extracting intent, drafting plans,
interpreting tool output, generating language, and *proposing* memories. Risky,
stateful, or irreversible concerns are owned by deterministic code:

| The model may propose | Deterministic services own |
| --- | --- |
| intent & risk classification | permissions & confirmation |
| candidate plans | scheduling & state transitions |
| tool-output interpretation | identity & transaction/spend limits |
| language & style | retries & idempotency |
| memory updates | audit history & data deletion |

Mechanically, this shows up as **proposal artifacts** that a policy then accepts,
rejects, merges, defers, or escalates: `MemoryUpdateProposal`,
`NotificationCandidate`, and an `ActionPlan` with explicit approval points. This
is the seam that keeps an AI-built system reviewable — the consequential
decisions are never the model's to make alone. It reinforces the `models/`
boundary from [ADR-0002](adr/0002-foundational-stack-and-architecture.md) and the
permission/audit layer from ADR-0004, and is a strong candidate for its own ADR
before the `orchestration` engine is wired.

## Domain artifacts by subsystem

The catalogue below maps candidate artifacts onto the existing architecture. It
is a menu, not a commitment — each lands as a small slice behind an ADR when we
build it.

| Subsystem | Candidate artifacts | Key ideas to preserve |
| --- | --- | --- |
| `memory` | `UserProfile` (asserted facts) vs. `UserModel` beliefs; typed memory — `EpisodicMemory`, `SemanticMemory`, `PreferenceMemory`, `ProceduralMemory`; `MemoryUpdateProposal` | Typed memory, **not** one vector blob. Every inference carries `confidence`, `evidence`, `source`, `last_updated`. The model never writes permanent memory directly — it proposes. |
| `context` | `CurrentContext` (time, location, device, activity, calendar state, attention, urgency) | Context governs response length, notification timing, tool selection, and **whether to act at all**. |
| `planning` | `Goal`, `Project`, `ActionPlan`, `ExecutionState`, `Commitment` ledger | Separate the static plan from durable, resumable execution state. Promises/obligations are first-class rows, not recovered by fuzzy search. |
| `tools` | `ToolDefinition` with `risk_level`, `reversibility`, `cost`, `latency` | Rich metadata lets the planner and permission layer *reason* about tools instead of hard-coding integrations. |
| `permissions` | `ActionPolicy` (confirmation, spend limits, approved recipients, time windows, reversibility requirement); `DecisionRecord` | Trust is an explicit artifact, not vague instructions. Record *why* consequential actions were taken, for explanation and debugging. |
| `learning` | `FeedbackEvent` (explicit vs. implicit), preference updates | Every correction/behaviour becomes a structured learning signal that feeds `MemoryUpdateProposal`s. |
| `orchestration` | `NotificationCandidate` + interruption policy; `EvaluationTrace` | Proactivity is *scored* before it interrupts: `value = usefulness × urgency × confidence − interruption_cost`. Trace runs end-to-end (Tier-2 operational data, no egress per ADR-0004) to evaluate the whole system, not just answer quality. |

## The first vertical

Do **not** materialise all of the above before anything runs. The first goal is a
minimal but *complete* set of artifacts plus one closed loop:

Seven artifacts to start with:

1. `UserProfile`
2. `Memory` (typed)
3. `CurrentContext`
4. `Goal`
5. `ToolDefinition`
6. `ActionPlan`
7. `FeedbackEvent`

One closed learning loop that exercises `context` + `memory` + `learning` +
`orchestration` together:

```text
conversation
  → retrieve relevant user context
  → generate a response or plan
  → observe the user's correction
  → propose a preference update (policy accepts it)
  → use that preference successfully next time
```

Getting this one loop working end to end is worth more than wiring twenty
services that never close a feedback loop.

## Build sequence and status

Contracts-first, one subsystem per slice (per `CLAUDE.md`). Rough order:

- [x] **`models` — `ModelProvider`.** `PydanticAIProvider` over pydantic-ai.
- [x] **`memory` — `MemoryStore` (in-memory).** Dependency-free lexical store, a
      real contract for downstream slices to build against.
- [ ] **Memory model ADR + persistent store.** Typed memory, profile-vs-model,
      confidence/evidence provenance, `MemoryUpdateProposal`; then SQLite +
      vector backend (needs an embedding seam) honouring ADR-0004 (0600 perms,
      export/delete/retention).
- [ ] **`context` — `CurrentContext` assembly.**
- [ ] **`planning` — `Goal`/`ActionPlan`/`ExecutionState`.**
- [ ] **`tools` — `ToolDefinition` registry** with risk/reversibility metadata.
- [ ] **`permissions` — `ActionPolicy` + audit trail** (ADR-0004).
- [ ] **`learning` — `FeedbackEvent` capture.**
- [ ] **`orchestration` — the pipeline** wiring the above via injected contracts,
      then the first closed loop above.
- [ ] Later: `NotificationCandidate`/proactivity, `EvaluationTrace`/eval harness,
      `DecisionRecord`, `Commitment` ledger.

## Deliberately deferred

- **All 15 artifacts at once.** Start with the seven and one loop.
- **A single mega-commit to `core/types.py`.** Each cross-boundary type is a
  Protocol-adjacent decision and lands as its own ADR-backed slice.
- **Proactivity, evaluation harness, decision records, commitment ledger.**
  Valuable, but they follow the first working loop rather than precede it.
