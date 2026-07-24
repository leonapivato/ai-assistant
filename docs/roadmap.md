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
points). It is implemented today in the memory write path (`MemoryUpdateProposal`
→ `MemoryPolicy`) and in the execution path (`ActionPlan` → `ActionPolicy`, whose
`CONFIRM` parks the step for the user). It never got the single ratifying ADR
this line once anticipated; the principle is instead carried by ADR-0005,
ADR-0021 and ADR-0037 severally. `NotificationCandidate` is the one proposal
artifact still unbuilt.

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

1. `UserProfile` — **not built.** The only one of the seven with no type in
   `core/types.py` and no line in the build sequence below, so nothing has been
   flagging its absence. `core/types.py` distinguishes the profile from the
   inferred user model in prose, and VISION §"Persistent User Model" makes it
   central, but there is no artifact. See "What is still missing" below.
2. `Memory` (typed) — `EpisodicMemory`/`SemanticMemory`/`PreferenceMemory`/
   `ProceduralMemory` over a shared `MemoryBase`.
3. `CurrentContext`
4. `Goal`
5. `ToolDefinition`
6. `ActionPlan`
7. `FeedbackEvent`

Six of the seven exist. The closed loop below is proven end to end by an
integration test, and runs in the application for a turn the user drives —
except that the correction step has no route in through the CLI (see the
`interfaces`/`app` entry in the build sequence).

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
- [x] **`models` — `Embedder`.** On-device `FastEmbedEmbedder` plus a
      deterministic `HashingEmbedder` for tests (ADR-0006). **The application
      does not use it:** `app/composition.py` builds the store with
      `HashingEmbedder`, and `Settings` has no embedder knob, so semantic recall
      in the running system is not semantic. ADR-0006's "on-device default" is a
      decision the composition root has never honoured.
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
- [x] **`context` — `CurrentContext` assembly.** Temporal `CurrentContext` +
      `ContextProvider`, assembled from an internal `ContextSource` seam
      (`ClockContextSource`), with graceful degradation (ADR-0008). Facets
      (calendar, tasks, ...) added as optional fields when their sources land.
- [x] **`planning` — `Goal`/`ActionPlan`/`ExecutionState`.** Capability-level
      `ActionPlan` (frozen) separated from durable `ExecutionState`, written only
      through compare-and-swap `StepTransition`s that a deterministic
      `PlanExecution` validates; `InMemoryPlanStore` carries the ADR-0004 data
      rights (ADR-0014). Since landed: a model-backed planner (`ModelBackedPlanner`,
      ADR-0047) and a durable SQLite `PlanStore` (ADR-0049), so a parked step
      survives a restart. Still deferred: step dependencies (`PlanStep` has no
      `depends_on`; a plan is an ordered list), and exactly-once execution —
      discharged by ADR-0029 as far as it honestly can be, and irreducible for an
      `Idempotency.NONE` side-effecting tool, where a crash mid-effect still
      yields an `INDETERMINATE` step for explicit resolution.
- [x] **`tools` — `ToolDefinition` registry** with risk/reversibility metadata.
      A frozen `ToolDefinition` where no safety field has a default, carrying
      severity-ordered `RiskLevel`/`Reversibility`, ADR-0004 tier reach
      (`reads`/`writes`/`discloses`, a ceiling rather than a per-call measure),
      structured `ToolCost`, and an `Idempotency` guarantee; queried through a
      query-only `ToolRegistry` that returns candidates without ranking them
      (ADR-0016). Settles ADR-0014's capability vocabulary as an open,
      registry-authoritative set. Since landed: invocation — the `ToolInvoker`
      seam with parameter-schema enforcement and ADR-0004 §2's egress rule
      (ADR-0029) — and the first local tools behind a default-registry factory
      (ADR-0048). Still deferred: **ranking** — the registry returns capable
      candidates unordered and there is no rule for choosing among several
      (#241); ADR-0053's selection-time alias layer resolves a *synonym* onto an
      advertised capability, which is not ranking. Also deferred: registry
      persistence (only `InMemoryToolRegistry` exists) and per-call data reach.
- [x] **`permissions` — `ActionPolicy` + audit trail** (ADR-0004). A monotone
      rule table (`ThresholdActionPolicy`) whose user thresholds cannot configure
      it below the contract's floors, and a durable `SqliteAuditTrail` recording
      every decision (ADR-0021, ADR-0036). A `CONFIRM` binds durably to its
      execution and is recoverable after a restart (ADR-0044), under a lifetime
      deadline with resolution recovery (ADR-0059). Deferred from ADR-0004's
      catalogue: spend limits, approved recipients, and time windows — the policy
      rules today on risk and reversibility only.
- [x] **`learning` — `FeedbackEvent` capture.** `FeedbackEvent` +
      `FeedbackProcessor`; a deterministic processor turns explicit
      correction/preference feedback into `USER_ASSERTED` memory proposals
      (ADR-0009). The first closed loop (feedback → proposal → ingest → retrieve)
      is proven by an integration test, and `LearningLoop.learn` automates the
      wiring — though nothing calls it outside tests (see the façade entry).
      Deferred: `RATING`/implicit signals, a model-backed processor.
- [x] **`orchestration` — the closed learning loop.** `LearningLoop` wires
      `ContextProvider`, `MemoryStore`, `MemoryPolicy`, `Planner` and
      `FeedbackProcessor` by injection, seen only through their Protocols:
      `respond()` runs intent → context → retrieval → planning, `learn()` runs
      feedback → proposal → policy → memory, and a test proves a preference
      learned from a correction is reused on the next turn (ADR-0022). Since
      landed: the memory write path as a contract (`MemoryWriter`, ADR-0028), so
      a ruling is applied behind that seam — with reinforcement and supersession
      separated (ADR-0040) over the full contradiction set (ADR-0050).
- [x] **`orchestration` — selection, permission and execution.** The stage that
      ADR-0016 §7 said could not be written honestly until `Tool.invoke` existed:
      capability → candidate tools → `ActionPolicy` ruling → invocation, joined
      in one contract (ADR-0037), with the result the seam returns revalidated
      before it is trusted (ADR-0051).
- [x] **`orchestration`/`interfaces` — the façade and a runnable application.**
      An `Engine` façade over the pipeline with opaque continuation tokens
      (ADR-0042), which parks a `CONFIRM` and resumes it durably across a restart
      (ADR-0052); a composition root in `app/` wiring the SQLite memory, plan and
      audit stores; and a thin Typer CLI (`ask`, `resume`). **Not yet reachable
      from any interface: `learn()`.** The façade exposes no way to submit a
      `FeedbackEvent`, and the CLI has no feedback command, so the correction leg
      of the first vertical's closed loop runs only in tests.
- [ ] Later: `NotificationCandidate`/proactivity + interruption policy,
      `EvaluationTrace`/eval harness, `Commitment` ledger, a derived user-model
      projection ADR. None of these has a type in `core/types.py`; each still
      needs decomposing into ADR-backed slices before it is dispatchable.
      `DecisionRecord` is **delivered under another name** — `PermissionDecision`
      plus the `AuditTrail` contract (ADR-0021) is the artifact this line meant.

## What is still missing

The build sequence above tracks what each *slice* deferred. This section tracks
what the **product** lacks, which is a different list — every item here is
machinery that exists but that a real user cannot reach, or an artifact the
first vertical named and never got. Keep it honest: an entry leaves this list
when a user can exercise it, not when a test can.

- **`UserProfile` does not exist.** Artifact #1 of the seven. Needs an ADR
  deciding what the profile is (asserted, user-owned) versus what the inferred
  user model is (derived from memory, revisable), and which one the retrieval
  path reads. Plausibly subsumes the "derived user-model projection ADR" above.
- **The correction leg of the loop has no interface.** `LearningLoop.learn`
  works; `Engine` does not expose it and the CLI cannot reach it. The product's
  central claim — it learns from your corrections — is currently test-only.
- **Production memory retrieval is not semantic.** The composition root wires
  the deterministic test embedder (see the `Embedder` entry).
- **No tool exercises the permission path in practice.** Both local tools
  (`report_current_time`, `recall_memory`) are read-only and low-risk, so
  `ThresholdActionPolicy` never returns `CONFIRM` in real use and the durable
  park/resume machinery (ADR-0044/0052/0059) runs only under test.
- **No ranking among capable tools** (#241), so a second tool advertising a
  capability makes selection arbitrary rather than reasoned.
- **Context has one facet.** `ClockContextSource` only — no calendar, tasks,
  location, device, or attention source, so "whether to act at all" is decided
  on time of day alone.

## Deliberately deferred

- **All 15 artifacts at once.** Start with the seven and one loop.
- **A single mega-commit to `core/types.py`.** Each cross-boundary type is a
  Protocol-adjacent decision and lands as its own ADR-backed slice.
- **Proactivity, evaluation harness, commitment ledger.** Valuable, but they
  follow the first working loop rather than precede it. (Decision records are no
  longer on this list — they landed as `PermissionDecision`/`AuditTrail`.)
