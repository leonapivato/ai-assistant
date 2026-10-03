# 285. The current observer is retired, and the benchmark harness with it

- Status: Proposed
- Date: 2026-10-03
- Scope: [M36](https://github.com/leonapivato/ai-assistant/milestone/2), reopened 2026-09-30 for [#2613](https://github.com/leonapivato/ai-assistant/issues/2613); the first item of the plan recorded there on 2026-10-03, ahead of step 3a and step 3b, behind their shared cutover.
- Dependency: ADR-0284, implemented at `ee659a12`.
- Authorization: the owner ruled on 2026-10-03 (#2613) that state whose only job is to keep the system working until its replacement arrives is removed when that is cheapest, accepted proposal #2646 the same day ("lgtm, convert it to the ADR") and directed its conversion into this ADR. The dispatcher assigned 0285, the next number on `main`. That authorizes drafting and numbering, not ratification or implementation.
- **Supersedes** [ADR-0212](0212-the-observation-cursor-is-a-per-conversation-watermark-on-the-conversation-index.md) — **whole.** The observation cursor is removed (§4 below). Its earlier partial supersessions by ADR-0218, ADR-0275 and ADR-0283 stay on its status line as history.
- **Supersedes** [ADR-0220](0220-the-watermark-driven-observation-walk-tiles-contiguously-and-forgoes-the-window-overlap.md) — **whole.** The observation walk and the benchmark harness it bound are removed (§1, §8 below).
- **Partially supersedes** [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) — **the observer and its operation.** §1, §2, §3 and §8 entire; and §4, §5, §9, §10 and §11 in every clause whose subject is the observer, its batch, its prompt, its route, its outcome, its trigger or its contract surface. §6, §7, §5's policy rule and writer floor, and §9's items for them stand. The route §3 named passes to consolidation (§5 below).
- **Partially supersedes** [ADR-0083](0083-the-hub-is-a-resident-process.md) — **one scope.** §7's job-table row for observation, whole. Every other row and clause stands.
- **Partially supersedes** [ADR-0085](0085-the-promoted-engine-surface.md) — **one scope.** Every entry for the `observe` method and the two observation types: §3's `observe` signature, §4's Group E (`ObservedProposal`, `ObservationReport`), §5's closure in their branch, §9's `observe` row and §10's `observe` mapping. Every other method, type and clause stands.
- **Partially supersedes** [ADR-0100](0100-a-belief-states-whom-it-is-about-and-the-label-resolves-to-nothing.md) — **one scope.** §5:1–§5:4 entire. §4 and §9 stand for every producer that remains.
- **Partially supersedes** [ADR-0120](0120-a-measure-is-a-rate-over-the-trace-stream-read-offline-while-the-hub-is-stopped.md) — **two scopes.** §3:2's `observe` member of the user set, and its `observe_due` member of the machine set as ADR-0218 added it. §6:3–§6:5 entire. Every other clause stands.
- **Partially supersedes** [ADR-0156](0156-a-distilled-belief-states-its-event-time-in-its-content.md) — **one scope.** §2:1 entire, the observation prompt's rendering of `occurred_at`. Every other clause stands.
- **Partially supersedes** [ADR-0160](0160-the-episodic-bound-meets-the-belief-budget-and-post-hoc-attribution-replaces-the-ablation-arm.md) — **two scopes.** §3:2–§3:7 and §4:1–§4:9 entire: the scored benchmark run and its retraction predicate. §3:1 and every other clause stand.
- **Partially supersedes** [ADR-0162](0162-what-the-user-tells-the-assistant-is-recorded-and-selectivity-moves-to-retrieval-and-forgetting.md) — **five scopes.** §1:1–§1:4, §2:1–§2:4, §4:1–§4:2, §6:1–§6:5 and §7:1–§7:5 entire, and §8:1 as ADR-0221 §4:1 replaced it. §3, §5, §8:2–§8:5 and §9–§13 stand.
- **Partially supersedes** [ADR-0163](0163-an-episode-names-its-principal-participant-and-the-capturing-client-supplies-it.md) — **one scope.** §5:3's observation-prompt member. Its planner and consolidation members, and every other clause, stand.
- **Partially supersedes** [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md) — **one scope.** §1:1's `observe` member. Every other member and clause stands.
- **Partially supersedes** [ADR-0213](0213-a-record-carries-the-topics-it-is-about-proposed-once-at-write-and-never-inferred-at-read.md) — **two scopes.** §5:9 entire, and §6:1's `ModelBackedObserver` member. Consolidation stays the one producer of topics, and every other clause stands.
- **Partially supersedes** [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md) — **three scopes.** §4:2 entire, §5:1–§5:4 entire, and §5:7–§5:8 entire. Every other clause stands.
- **Partially supersedes** [ADR-0218](0218-a-conversation-is-observed-once-it-goes-quiet-and-a-max-age-backstop-bounds-the-wait.md) — **every clause but one.** §8's narrowing of ADR-0111 §4's second normative clause stands, recorded on ADR-0111 and relied on by consolidation's chunked job.
- **Partially supersedes** [ADR-0221](0221-an-episode-carries-the-reply-a-typed-disposition-and-how-the-turn-was-captured.md) — **one scope.** §4:1 entire, the observation prompt's replacement of ADR-0162 §8:1. §4:2 and every other clause stand.
- **Partially supersedes** [ADR-0222](0222-the-stored-reply-is-read-back-in-the-conversation-tail-and-by-the-observer.md) — **the observer door and the harness.** §2:2, §3:1–§3:4, §5:8 and §9:1–§9:5 entire; §4:1's and §5:4's reach to §3; §4:2's third site; §4:3's two observation settings; and §6:1–§6:3's `learning/observer.py` site. The tail door and every other clause stand.
- **Partially supersedes** [ADR-0239](0239-the-observation-pass-labels-the-episodes-it-read-and-a-label-lands-as-a-conditional-write-at-the-episodes-own-id.md) — **the labelling pass.** §1, §2, §3, §5, §8 and §9 entire, and §4:5–§4:7. §4:1–§4:4, §6, §7 and §13 stand for the labels an episode carries.
- **Partially supersedes** [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) — **three scopes.** §6:1's and §6:8's `record_observed` member, §6:6 entire, and §11:1–§11:3 entire. Every other clause stands.
- **Partially supersedes** [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) — **one scope.** The observer's member of §6:2, §8:3 and §8:7. Every other member and clause stands.

## Context

The observation milestone ([Observation across activation episodes](https://github.com/leonapivato/ai-assistant/milestone/3),
blocked, with the design discussion on #2528) will rebuild observation from scratch,
as an observer plus a coordinator, once episodes carry what it needs. It keeps the
observer's job, which is to interpret supplied episodes and propose evidence-backed
beliefs, and gives batching, progress and retries to the new coordinator. Its stated
scope excludes historical backfill, and puts a consolidation redesign out of scope.

The owner ruled on 2026-10-03 that the in-between state does not matter. Anything
whose only job is to keep the system working until its replacement arrives is
removed when that is cheapest, not maintained. Goals, parks and resumes fail that
test for now, because the rebuild of the turn loop will delete them along with what
grows around them (#2613, 2026-10-03). The observer passes it: nothing that will be
rebuilt depends on it, and every change to episodes or memory since ADR-0283 has
paid for it again. Step 2 (ADR-0284 §11's lane 4) rewired its renderer one week
before this decision.

What the code holds, at `ee659a12`:

- **The producer.** `learning/observer.py`'s `ModelBackedObserver`, behind the
  `Observer` Protocol in `core/protocols.py`, with the fake `FakeObserver` in
  `testing/observation.py` and the conformance suite
  `tests/learning/observer_contract.py`. It is the only implementation of
  `ObservationOutcome` and `EpisodeLabelling`.
- **The stage.** `orchestration/observation.py`'s `ObservationStage` selects due
  conversations, batches their episodes, calls the observer, routes the proposals
  through the memory-write policy and labels the episodes it read. The engine wraps
  it as `observe`, on the `AssistantEngine` Protocol and so on the wire, returning
  `ObservationReport` and its `ObservedProposal`s from `core/types.py`, and as
  `observe_due`, returning the stage's `ObservationRunReport`.
- **The schedule.** `service/scheduler.py` arms the `observation` job every
  `observation_interval`, fifteen minutes by default. `service/configuration.py`
  reports four observation figures on the configuration trace.
- **The cursor.** `Conversation.observed_through`, written by
  `ConversationStore.record_observed`, held in the conversation store's
  `observed_through` column and carried in `ConversationExport`.
- **The settings.** `observation_interval`, `observation_quiet_window`,
  `observation_max_unobserved_age`, `observation_batch_size`,
  `observation_max_proposals` and `observer_model`. Settings are read with the
  `ASSISTANT_` prefix and `extra="ignore"`, so a variable that names no field is
  ignored without an error.
- **The route.** Consolidation reads through the observer's provider:
  `app/composition.py` builds one route from `observer_model`, or `default_model`
  where it is unset, that never falls back, and hands it to both stages. No ADR
  rules the sharing; the composition root's comment gives ADR-0077 §3's no-fallback
  rule as its reason.
- **The surfaces.** `assistant observe` in the CLI, `POST /observe` and its button
  in the gateway, and the `observe` and `observe_due` seams in `evaluation/`, with
  the `observe` reinforcement share ADR-0120 §6 reports.
- **The benchmark harness.** `benchmarks/memory/` ingests conversations and distils
  them through `ObservationStage` and `ModelBackedObserver`. Its tests are under
  `tests/benchmarks/`, `tests/planning/test_planner.py` imports its
  `render_context`, and `pyproject.toml` puts `benchmarks` in mypy's files and on
  pytest's path. Ingestion has not run since ADR-0283 retired the turn index
  (#2626), and benchmarking is paused. `BatchCompleter` (ADR-0143) has no other
  consumer.

The corpus rules the observer in two kinds of place. ADR-0077, ADR-0212, ADR-0218,
ADR-0220 and ADR-0239 decide the component, its cursor, its schedule, its walk and
its labelling pass. Some sections of ADR-0077 and ADR-0239 also hold rules every
producer and reader depends on: ADR-0077 §6's tombstones and §7's `Provenance`
validator, its §5 policy rule and writer floor, and ADR-0239's statements of what a
label on an episode means. About twenty later ADRs name the observer inside rules
about something else: as one renderer of the stored reply, one producer of topics or
placements, one reader of every episode, one browser operation, one seam a measure
reads.

## Decision

### 1. The observer is retired

> **Normative.** `ModelBackedObserver`, the `Observer` Protocol, its canonical fake
> and its conformance suite, `ObservationOutcome` and `EpisodeLabelling` are
> removed, and `ObservationStage` with its report types.

> **Normative.** No component of this system proposes a belief from episodes in the
> background until an ADR of the observation milestone (#2528) introduces one. This
> ADR adds no producer in the observer's place.

> **Normative.** No clause this ADR supersedes binds the observer the observation
> milestone builds. That milestone's ADR decides which of them, if any, it adopts.

The removal of `Observer` is a breaking Protocol change, and the removal of the
`observe` method below is a second one.

### 2. The engine surface and the wire

> **Normative.** `AssistantEngine.observe`, `Engine.observe`, `Engine.observe_due`,
> `ObservationReport` and `ObservedProposal` are removed, with the wire client's
> `observe` and the fake engine's.

> **Normative.** Each change that alters a shape crossing the wire advances
> `PROTOCOL_VERSION` in that change.

The method's removal is such a change: `wire.surface.METHODS` is derived from the
`AssistantEngine` Protocol, so a peer at the earlier version may call a method the
hub no longer answers.

### 3. The schedule

> **Normative.** The scheduler arms no observation job.

> **Normative.** `service/configuration.py` reports no observation figure on the
> configuration trace.

A window spanning the change partitions there under ADR-0120 §8, as at any change of
configuration.

### 4. The cursor

> **Normative.** `Conversation.observed_through` and `ConversationStore.record_observed`
> are removed, from the Protocol, its conformance suite, its canonical fake and the
> sqlite store.

> **Normative.** The conversation store's schema creates no `observed_through`
> column, and the migration that adds one to an earlier file is removed.

> **Normative.** Nothing drops the column from a file that already holds it, and no
> store format advances for it.

> **Normative.** `ConversationExport.schema_version` advances by one, because the
> `Conversation` the export carries loses a member (ADR-0014 §5).

The column is dropped rather than left in place. ADR-0247 §5 kept two vestigial
columns so that a file written before its decision and one written after it had one
shape, because dropping a column from SQLite means rebuilding the table that holds
every conversation. That reason does not reach this column. The hub moves to a fresh
data directory at the cutover (ADR-0284 §9:1), so no deployed file written before
this decision is ever opened by a build after it. A development file that still holds
the column opens and works, because nothing selects it.

### 5. The settings, and consolidation's route

> **Normative.** `observation_interval`, `observation_quiet_window`,
> `observation_max_unobserved_age`, `observation_batch_size` and
> `observation_max_proposals` are removed from `Settings`.

> **Normative.** `Settings.observer_model` is renamed `consolidation_model`, with the
> same type, the same default of `None` and no alias for the old name.

> **Normative.** Consolidation reads through one route, built from
> `consolidation_model` where it is set and from `default_model` where it is not, and
> that route never falls back.

The last clause restates for consolidation what ADR-0077 §3 ruled for the observer
and what the composition root already builds. It is now consolidation's route alone,
so it gets consolidation's name.

The environment consequence is stated because it is silent. A hub environment that
still sets `ASSISTANT_OBSERVER_MODEL` starts without an error after the change, and
its consolidation reads through `default_model` instead. The `ASSISTANT_OBSERVATION_*`
variables are ignored the same way, which is harmless. So the cutover's deploy renames
`ASSISTANT_OBSERVER_MODEL` to `ASSISTANT_CONSOLIDATION_MODEL` wherever it is set, and
deletes the rest. No alias is kept, because an alias is exactly the in-between state
the owner's ruling removes, and the cutover is a deploy the operator runs once.

### 6. The surfaces

> **Normative.** The CLI's `observe` command, the gateway's `POST /observe` route and
> its button are removed.

### 7. Evaluation

> **Normative.** `observe` and `observe_due` leave evaluation's seam sets, and the
> `observe` reinforcement share leaves the report.

> **Normative.** A trace a store already holds under the `observe` or `observe_due`
> seam is read as a trace under any seam on no set: it is unclassified, counted as
> such, and enters no measure. No reader special-cases either name.

That is evaluation's existing rule for a seam it does not classify, so an old store
stays readable, and its observation writes appear in the unclassified count, where
an operator can see them, rather than in a population. A trace store written after
the cutover holds no such trace.

### 8. The benchmark harness is deleted

> **Normative.** `benchmarks/` and `tests/benchmarks/` are deleted, with their entries
> in `pyproject.toml` and the tests elsewhere that import the harness.

> **Normative.** `BatchCompleter`, its types, its implementation, its fake and its
> suite are not removed by this ADR. Whether they go is #2647.

The harness cannot be kept compiling without the observer, because it imports the
stage. "Stop maintaining it" therefore has to mean deleting it. Its history keeps it,
and the observation milestone or a resumed benchmark effort can bring back whatever
it needs. Rewiring it to `learn` was considered and rejected: the harness measures
belief distillation, so without the observer it would measure something else, and it
would still need porting (#2626).

### 9. What stays

> **Normative.** Explicit `learn`, consolidation, belief reconciliation, the memory-write
> policy and `MemorySource.OBSERVED` stay as they are.

> **Normative.** `learning/` keeps its import-linter contracts as they stand.

> **Normative.** No producer proposes the topics or the participants of an episode.
> The labels an episode carries are written only by the owner's acts ADR-0213 §9
> rules.

ADR-0239 §4:1–§4:4, §6 and §7 still state what such a label means.

What the user says in conversation is no longer turned into beliefs in the background.
It is still recorded: every episode keeps the user's words, and recall (ADR-0281) finds
them. Once step 3 keeps episodes until they are forgotten, nothing said is lost when
the retention horizon passes. ADR-0162's principle, that what the user tells the
assistant is recorded, holds through the episode. Its intake clauses (§1, §2, §4, §6,
§7) ruled the observer's output and go with it; its retrieval and forgetting clauses
(§5, §9) and its evidence rules for the assistant's half of an exchange (§8:2–§8:5)
stand. The distilled layer of beliefs returns with the observation milestone.

The browser and voice have no way to write a belief, because the gateway has never
offered `learn`. That is accepted as part of the in-between state.

### 10. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on each affected ADR's
> status line and in a dated header note, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

> **Normative.** A clause is replaced here where it obliges or configures something
> this ADR removes, or fixes a set of parties of which the observer, its stage, its
> pass, its prompt, its cursor, its settings, its surfaces or the harness is a member.

ADR-0082 §1's test applied to the rest of the corpus leaves four kinds of clause
unrecorded, and none of them becomes false in a way a reader would act on:

- A prohibition on something removed, which holds of nothing: for example ADR-0162
  §3:1, ADR-0223 §9:1, ADR-0225 §4:2 and §4:5, and ADR-0227 §1:7.
- A work order or test list of a lane that has merged, such as ADR-0156 §7:2,
  ADR-0163 §7, ADR-0275 §14 and ADR-0283 §14.
- A deferral or a statement of what an ADR does not decide, such as ADR-0217 §12 and
  ADR-0239 §13.
- A clause that names the observer only as a precedent, a type reference or one
  illustration of a universal rule. Examples are ADR-0159 §3:4's "the same validated
  spec `observer_model` carries", which now reads `consolidation_model`, ADR-0230
  §10:3 and ADR-0231 §16:3, ADR-0210 §2:3, and ADR-0275 §12:4.

The replacements ADR-0212, ADR-0218, ADR-0220 and ADR-0239 themselves made elsewhere
concerned only what this ADR removes, so they lapse with it and need no new record:
ADR-0212's of ADR-0074 §9 and of ADR-0111 §2 and §7 as they reach the observation
cursor, ADR-0218's of ADR-0077 §8, ADR-0083 §7's row and ADR-0120 §3:2, ADR-0220's of
ADR-0162 §7, and ADR-0239's of ADR-0075 and ADR-0213, which admitted the pass's label
write. The one exception is ADR-0218 §8's narrowing of ADR-0111 §4's second normative
clause, which keeps consolidation admissible as a chunked job and stands.

ADR-0143 is not superseded. No clause of it assumes the harness exists, and §8 forbids
giving the seam to any subsystem, so the deletion leaves it without a consumer and
makes none of its text false (#2647).

The proposal named ADR-0106 §12 as the ruling that made consolidation share the
observer's route, and ADR-0221 §8 as an observer clause. Neither holds on `main`.
ADR-0106 §12 is a list of deferrals and names no route; the sharing is the
composition root's choice, now ruled in §5. The observer clause in ADR-0221 is §4:1,
and §8 is about the record's migration.

| Earlier clause | What changes |
| --- | --- |
| ADR-0077 §1–§3, §8; observer clauses of §4, §5, §9–§11 | The observer and its operation go; its route passes to consolidation. |
| ADR-0083 §7's observation row | No observation job. |
| ADR-0085 §3, §4 Group E, §5, §9, §10 for `observe` | The method and its two types go. |
| ADR-0100 §5:1–§5:4 | No observer to refuse a subject. |
| ADR-0120 §3:2, §6:3–§6:5 | No `observe` or `observe_due` seam; no `observe` share. |
| ADR-0156 §2:1 | No observation prompt. |
| ADR-0160 §3:2–§3:7, §4 | No scored benchmark run. |
| ADR-0162 §1, §2, §4, §6, §7, §8:1 | Intake through the observation stage goes. |
| ADR-0163 §5:3 | Two rendering sites, not three. |
| ADR-0177 §1:1 | The browser does not reach `observe`. |
| ADR-0212 | Superseded whole. |
| ADR-0213 §5:9, §6:1 | Consolidation alone proposes topics. |
| ADR-0217 §4:2, §5:1–§5:4, §5:7–§5:8 | No producer proposes a placement; a correction is not distilled by an observer. |
| ADR-0218, except §8's narrowing of ADR-0111 §4 | No scheduled observation. |
| ADR-0220 | Superseded whole. |
| ADR-0221 §4:1 | No observation prompt. |
| ADR-0222 §2:2, §3, §4:1–§4:3, §5:4, §5:8, §6:1–§6:3, §9 | No observer door, and no harness. |
| ADR-0239 §1–§3, §4:5–§4:7, §5, §8, §9 | No labelling pass. |
| ADR-0283 §6:1, §6:6, §6:8, §11 | No watermark. |
| ADR-0284 §6:2, §8:3, §8:7 | No observer among the readers and renderers. |

### 11. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs:
>
> 1. **`benchmarks`**: delete `benchmarks/` and `tests/benchmarks/`, their
>    `pyproject.toml` entries, and `tests/planning/test_planner.py`'s parity with
>    `render_context` (§8).
> 2. **`interfaces`**: the CLI command, the gateway route and its button (§6).
> 3. **`orchestration` with `app` and `service`**: the stage, `Engine.observe` and
>    `observe_due`, the scheduler job and the configuration figures, the composition
>    wiring, and consolidation's route with the `Settings` field's rename (§3, §5).
>    `AssistantEngine.observe`, `ObservationReport`, `ObservedProposal`, the wire
>    client's method, the fake engine and the `PROTOCOL_VERSION` advance ride the
>    same change, under ADR-0137 §2's contract-plus-primary-implementation widening
>    (§2).
> 4. **`learning`, `core` and `testing`, a triad**: `ModelBackedObserver`, the
>    `Observer` Protocol, its fake and its suite, `ObservationOutcome`,
>    `EpisodeLabelling`, and the five removed `Settings` fields (§1, §5).
> 5. **`memory`, a triad**: `Conversation.observed_through`,
>    `ConversationStore.record_observed`, the column and its migration, the
>    conformance suite, the canonical fake and `ConversationExport`'s version (§4).
> 6. **`evaluation`**: the seams and the share (§7).

> **Normative.** Lanes 1 and 2 land before lane 3, because the harness imports the
> stage and the interfaces call the method lane 3 removes. Lanes 4, 5 and 6 land
> after lane 3 and are independent of each other.

> **Normative.** Lane 3's tests assert, through production composition: the hub's
> scheduler holds no observation job; `AssistantEngine` declares no `observe`;
> consolidation's provider is built from `consolidation_model` where it is set and
> from `default_model` where it is not, and does not fall back; and the configuration
> trace carries no observation figure.

> **Normative.** This decision ships no deploy of its own. It rides the cutover #2613's
> steps 2 and 3 share.

> **Normative.** The M36 addition's exit is ruled by the owner on #2613, with the
> tested revisions and live-hub evidence recorded there. A ratified ADR, merged lanes
> or a passing suite alone does not establish it.

## Consequences

- Every later change to episodes and memory stops paying for a component the
  observation milestone replaces whole. `learning/` shrinks to `learn`, and the
  gate's population is `learn`, consolidation, ingestion and the other producers
  that already write.
- What the user says is kept as episodes and found by recall. A belief is written
  only when someone asks for one explicitly or when consolidation derives one.
  Episodes get no automatic topic or participant labels. The Observe button and the
  `assistant observe` command go.
- Two Protocols change, `Observer` and `AssistantEngine`, and the wire protocol
  advances. `ConversationStore` loses an operation and `ConversationExport` a
  version.
- The operator renames `ASSISTANT_OBSERVER_MODEL` at the cutover, or consolidation
  silently reads through the conversational route.
- There is no benchmark harness. A resumed benchmark effort rebuilds one and decides
  its own measurements, including the episodic bound's (ADR-0160 §3 and §4 no longer
  bind it). #2626 closes with lane 1. `BatchCompleter` waits on #2647.
- `UnresolvedEvidenceError` loses the consumer ADR-0077 §5 named it for. It stays,
  because the writer still raises it.
- What would revisit this: nothing short of the observation milestone, whose ADR
  introduces an observer under rules of its own.

## Alternatives considered

- **Keep the observer running, at the minimum.** That is what step 2 did, when lane 4
  rewired its renderer. Every later change to episodes or memory pays for it again,
  for a component that the milestone replaces whole.
- **Switch it off but keep the code.** Disarm the job and keep everything else. That
  costs almost nothing now, but the code still has to compile and pass its tests
  through every change, which is the cost this decision removes.
- **Keep the benchmark harness, rewired to `learn`.** The harness measures belief
  distillation. Without the observer it would measure something else, and it would
  still need porting (#2626).
- **Keep the `observed_through` column and stop reading it.** That is ADR-0247 §5's
  precedent, and it avoids a table rebuild. There is no file to rebuild: the data
  directory is fresh at the cutover, so a dropped column costs nothing and leaves no
  vestige for the observation milestone to explain.
- **Keep `observe` and `observe_due` classified, so that an old store's measures read
  as before.** That keeps a vocabulary entry for each of two operations that no longer
  exist. Old stores stay readable without it, and the unclassified count shows what
  was set aside.
- **Supersede ADR-0077 and ADR-0239 whole**, as the proposal listed them. Both hold
  rules that outlive the observer: ADR-0077 §6's tombstones, §7's `Provenance`
  validator and §5's policy rule and writer floor govern code every producer passes
  through, and ADR-0239 §4, §6 and §7 say what a label already on an episode means.
  Whole supersession would leave those mechanisms with no ratified authority.
- **Keep an alias for `ASSISTANT_OBSERVER_MODEL`.** It would hide the rename from an
  operator who never reads it, and it is in-between state kept to spare a one-line
  edit at a deploy the operator runs anyway.
