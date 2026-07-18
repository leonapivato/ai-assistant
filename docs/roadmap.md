# Roadmap — orchestration artifacts and build sequence

**Status: working guidance, not a ratified decision.** This document is the
tactical companion to [`VISION.md`](../VISION.md): the *why* and *what* live
there; this covers *how* and *in what order*. Nothing here is binding. Every
artifact that crosses a subsystem boundary (a new `core` type or a Protocol
change) is ratified in its own ADR **before** it is implemented — see
`docs/adr/` and the rules in `CLAUDE.md`. If this roadmap and an ADR disagree,
the ADR wins.

The guiding architectural principle — *the LLM proposes; deterministic services
dispose* (VISION §7) — is realized as **proposal artifacts** a policy rules on
(`MemoryUpdateProposal`, `NotificationCandidate`, `ActionPlan` with approval
points). It is implemented today in the memory write path and remains a strong
candidate for its own ADR before the `orchestration` engine is wired.

## Domain artifacts by subsystem

The catalogue below maps candidate artifacts onto the architecture. It is a
menu, not a commitment — each lands as a small slice behind an ADR when we build
it.

| Subsystem | Candidate artifacts | Key ideas to preserve |
| --- | --- | --- |
| `memory` | typed memory — `EpisodicMemory`, `SemanticMemory`, `PreferenceMemory`, `ProceduralMemory`; profile-vs-model by provenance; `MemoryUpdateProposal` | Typed memory, **not** one vector blob. Every inference carries `confidence`, `evidence`, `source`, `last_updated`. The model never writes permanent memory directly — it proposes. |
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

- [x] **`models` — `ModelProvider`.** `PydanticAIProvider` over pydantic-ai
      (ADR-0002).
- [x] **`models` — `Embedder`.** On-device `FastEmbedEmbedder` default plus a
      deterministic `HashingEmbedder` for tests (ADR-0006).
- [x] **`memory` — typed records + provenance** (ADR-0005 slice 1).
- [x] **`memory` — propose/dispose policy** (`MemoryUpdateProposal`,
      `MemoryPolicy`, `DefaultMemoryPolicy`; ADR-0005 slice 2).
- [x] **`memory` — persistent store + write loop.** SQLite + `sqlite-vec`
      semantic store (0600 perms, model/dim tagging) and a `MemoryIngestor`
      closing conflict-detect → policy → persist (ADR-0006 slices 2–3).
- [x] **`memory` — retention & data rights.** `expires_at` enforced at read time
      (`get`/`search` hide expired) plus `purge_expired`; `delete`/`clear`/
      `export` added to the `MemoryStore` contract (ADR-0007, satisfying ADR-0004
      §6). Deferred: size caps, import, cross-tier keyring purge.
- [ ] **`context` — `CurrentContext` assembly.**
- [ ] **`planning` — `Goal`/`ActionPlan`/`ExecutionState`.**
- [ ] **`tools` — `ToolDefinition` registry** with risk/reversibility metadata.
- [ ] **`permissions` — `ActionPolicy` + audit trail** (ADR-0004).
- [ ] **`learning` — `FeedbackEvent` capture.**
- [ ] **`orchestration` — the pipeline** wiring the above via injected contracts,
      then the first closed loop above.
- [ ] Later: `NotificationCandidate`/proactivity, `EvaluationTrace`/eval harness,
      `DecisionRecord`, `Commitment` ledger, a derived user-model projection ADR.

## Deliberately deferred

- **All 15 artifacts at once.** Start with the seven and one loop.
- **A single mega-commit to `core/types.py`.** Each cross-boundary type is a
  Protocol-adjacent decision and lands as its own ADR-backed slice.
- **Proactivity, evaluation harness, decision records, commitment ledger.**
  Valuable, but they follow the first working loop rather than precede it.
