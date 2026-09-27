# 280. An activation controller runs the stages by rules and records every choice with the episode

- Status: Accepted
- Date: 2026-09-27
- Scope: [M38](https://github.com/leonapivato/ai-assistant/milestone/5), [#2576](https://github.com/leonapivato/ai-assistant/issues/2576).
- Dependency: ADR-0275, ADR-0276 and their milestones M36 and M37.
- Authorization: the owner accepted the proposal on #2577 on 2026-09-27, after ruling its scope on #2576 the same day, and directed its conversion into this ADR. The dispatcher assigned the next available number, 0280. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **two scopes.** **§1's exclusion list, in one item**: *"phase/tool history"* is no longer excluded for the record of stages §6 below defines; a tool history, a live activation log and §1's other exclusions stand entire. **§4's `EpisodeProcessingRecord` field set, in the additions alone**: the record gains §7 below's two members; every existing field, value and validator stands.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **one scope.** §7's first clause, *"`EpisodeProcessingRecord.schema_version` becomes `Literal[2]`"*, in the literal alone: it becomes `Literal[3]` under §7 below. The three understanding fields, the exactly-one validator and every other clause of ADR-0276 stand entire.

## Context

An activation's processing is a fixed sequence written into one engine
method. `Engine._run_turn` routes the utterance, reads the conversation's
history, runs the understanding stage, associates a goal, reconciles a
continuing goal, calls `LearningLoop.respond`, drives the first step,
composes and captures, and every decision about whether one of those runs is
a branch in that method or inside a stage. An informational event takes a
second fixed sequence in `Engine._dispatch_channel`. Nothing records which of
those steps ran or why.

The owner's direction on the wiki's
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller)
page (revision `f18ccf6`, direction and not ratified) replaces the fixed
sequence with a controller that runs whatever is due by rules, never calls a
model, records every choice, and lets later work add a phase, rerun one or go
back. This decision builds that controller's skeleton and none of the new
phases the page describes: recall, digesting, closing and the recall hook are
later milestones' work.

The inventory recorded on #2576 at `8265b204` sorted every branch on the
activation paths into three kinds: whether a stage runs, which is a
controller rule; what a stage is given, which is context assembly; and how a
stage works, which stays in the stage. It found few branches of the first
kind, and it found that only channel input and `AssistantEngine.resume` are
activations — `answer`, `withdraw_clarification`, `abandon_goal` and
`cancel_read` admit no activation and capture no episode.

The owner ruled the milestone's scope on #2576 on 2026-09-27: the controller
covers channel activations and `resume` keeps its legacy path; ADR-0249 §6's
`AttemptPhase` stays inside the stages and separate from the controller's
record; and existing behaviour may break temporarily where preserving it
would bend the design, provided each break is listed.

Two parts of today's pipeline are expected to be replaced: intent routing
(ADR-0197), which is to return as tool calls planning plans and acting runs,
and the spoken turn (ADR-0200), which is to return through channel work
(#2578) in which a channel becomes a sensor for input and an actuator for
output. The owner's aim is that **the new design is not shaped by what will
be removed**. This decision therefore keeps both working and quarantines
them: routing is one legacy stage with one rule, and voice stays at the
channel's edge, outside the controller, so that deleting either later removes
its wrapper and changes no rule, no record field and no stage interface.

## Decision

### 1. Status, scope and terminology

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one
> tree and the owner's authorization to ratify stands; an assigned number or a
> green review alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this
> decision until this numbered ADR has merged `Accepted` under ADR-0015 §5.

> **Normative.** A **stage** is a unit of processing the controller runs,
> named in §4's `ControllerStage`. A **phase** is a job in the wiki's target
> design (recall, understanding, planning, authorizing, acting, digesting,
> closing). The two do not map one to one, no stage is named after a phase it
> only partly performs, and nothing in this decision's record is a phase.

> **Normative.** The **activation controller** runs every channel activation
> admitted through `Engine._receive` or `Engine._streamed`: typed and spoken
> conversation turns and informational events. `AssistantEngine.resume` keeps
> its existing path, and an episode with a `RecordedResumeTrigger` carries no
> stage record.

**Why stage and not phase.** One stage, understanding, does one phase's job.
The turn loop plans and services reads; driving a step authorizes and acts;
beginning the conversation, associating a goal and reconciling are no phase
at all; composing is part of what planning or closing will do. Naming the
record after phases would claim a mapping that the later milestones have not
built yet.

### 2. What will be replaced is quarantined

> **Normative.** Intent routing runs as one stage, `routing`, which wraps
> `RoutingStage` and the routed pass together: it either declines, recording
> the decision `declined`, or takes the route and performs, composes and prepares capture for
> the routed pass exactly as ADR-0197 and its amenders decide. The controller
> knows only which of the two happened. No other rule, stage or record field
> refers to routing.

> **Normative.** The spoken turn stays at the channel's edge, outside the
> controller. `Engine._converse_spoken` records a delivery report, transcribes
> the recording and checks for words before the controller runs, and
> synthesizes after it returns, as it does today (ADR-0200 §4, ADR-0205 §1);
> the controller is handed the transcript as the turn's text and never sees
> audio, a delivery report or a synthesized rendering.

> **Normative.** The audience rules ADR-0200 §3 declares for the spoken
> operation stay inside the stages and context assembly that apply them today:
> the unbounded-audience supply (ADR-0203 §1), association returning no goal
> on the unbounded operation (ADR-0250 §15), and the understanding stage's
> episode window withheld there (ADR-0276 §4). No rule of §4 reads the
> audience, the payload modality, the conversational operation or the reply
> capability.

> **Normative.** A pass whose input yielded no text — speech with no words, or
> speech whose transcription failed — does not run the controller's rules, and
> records the single end entry `ControllerRule.no_text_input` under §5. The rule is
> named for the input, not for speech, so a later sensor that yields no text
> ends the same way.

**The test for the quarantine.** Deleting routing later deletes the `routing`
stage and its two rules. Moving voice to a sensor and an actuator later
replaces the edge in `Engine._converse_spoken`. Neither touches another rule,
the record's shape or the stage interface.

### 3. The controller

> **Normative.** `ActivationController` is an orchestration-local class in
> `orchestration/controller.py`, constructed with its stages and its rules.
> It is not a Protocol, and `core/protocols.py` gains no member for it or for
> the stage interface.

> **Normative.** A stage, as the controller runs it, has a `ControllerStage`
> name and one method, `async run(state) -> StageResult`. `StageResult` is
> orchestration-local and carries a `StageOutcome` (§5) and, for `failed` or
> `timed_out`, the error. A stage adds its results to the pass's state and
> never chooses what runs next.

> **Normative.** The controller repeats one step until the pass ends: evaluate
> §4's rules in their fixed order against the pass's state and the last
> outcome; take the first rule that answers; if it names a stage, run that
> stage and append its entry (§6); if it ends the pass, append the end entry
> and stop.

> **Normative.** The controller calls no model and makes no store read or
> write of its own. Everything it decides on is on `ActivationState`, and no
> text produced inside the activation is read by a rule.

> **Normative.** `ActivationState` carries the pass's **working set**: the
> decisions the stages have made on the pass, which the rules read — the
> resolved conversation, the routing decision (`declined` or `taken`), the
> understanding outcome (a recorded version or an omission), the association,
> the disambiguation question asked, the reconciliation result, the turn
> `LearningLoop.respond` returned, the drive's disposition and the composed
> reply. The working set is never persisted.

> **Normative.** A decision is present in the working set once a stage has made
> it, **including a decision that nothing came of**: a declined route, an
> association that found no goal, a composed reply that is degraded. An absent
> value means only that the decision has not been made, and a stage that
> produces nothing records that as its decision rather than leaving it
> absent.

> **Normative.** Beginning the conversation, understanding, the event summary,
> association, reconciliation, the turn loop, driving and composing each run as
> the existing stage or engine method they wrap, with the same inputs and
> effects. `LearningLoop.respond` runs as one stage.

**Why readiness rules and not a transition table.** A transition table is
simpler for one fixed order. Every later rule the wiki names reads what the
episode gained — a new understanding version, read results, effects, a
contest from the recall hook — so the table would carry the whole state in
its edges. A rule reads the state directly, and adding one is adding one row.

**Why no Protocol.** No other subsystem implements or calls a stage, and the
interface is expected to change in each of the next milestones as the turn
loop and the drive split. A Protocol would add a ratified contract, a
conformance suite and a canonical fake for an interface nothing outside
orchestration sees.

### 4. The rules

> **Normative.** `ControllerStage` is a closed `StrEnum`, **added to and never
> renamed**, with exactly these members: `begin_conversation`, `routing`,
> `understanding`, `event_summary`, `associate_goal`, `ask_disambiguation`,
> `reconcile`, `turn_loop`, `drive`, `compose` and `end`.

> **Normative.** `ControllerRule` is a closed `StrEnum`, **added to and never
> renamed**, with exactly the members the table below, the loop guard, §2 and §5
> name.

> **Normative.** The rules are evaluated in the order of this table, and the
> first that answers decides:

| # | Rule | Answers when | Makes due |
| --- | --- | --- | --- |
| 1 | `conversation_unresolved` | A conversation turn with no resolved conversation | `begin_conversation` |
| 2 | `route_unchecked` | A conversation turn, routing is wired, and there is no routing decision | `routing` |
| 3 | `route_taken` | The routing decision is `taken` | the end of the pass |
| 4 | `not_understood` | The understanding stage is wired and there is no understanding outcome for the input | `understanding` |
| 5 | `event_unsummarized` | An informational event with no event summary, and either an understanding outcome or the understanding stage unwired | `event_summary` |
| 6 | `association_due` | A conversation turn with no association | `associate_goal` |
| 7 | `disambiguation_raised` | The association asks which goal is meant, and no disambiguation question has been asked | `ask_disambiguation` |
| 8 | `continuing_unreconciled` | The association continues a goal, reconciliation is wired, and there is no reconciliation result | `reconcile` |
| 9 | `unplanned` | A conversation turn whose association asks nothing, and no turn | `turn_loop` |
| 10 | `plan_has_steps` | A turn that raised no question, whose plan has steps, and no drive disposition | `drive` |
| 11 | `reply_owed` | A turn whose step did not park for confirmation, and no composed reply | `compose` |
| 12 | `nothing_due` | Always | the end of the pass |

> **Normative.** `nothing_due` is last and always answers, so every pass the
> controller runs ends by a rule.

> **Normative.** Every rule reads decisions in the working set and never
> whether a stage has run. A composition that returns a degraded reply
> without raising (ADR-0170 §8) is a composed reply, so it answers
> `reply_owed`: the composer is called exactly once and the pass reaches
> `nothing_due`.

> **Normative — the M38 loop guard.** The controller runs a stage at most once
> per pass. When the first rule that answers names a stage already run on the
> pass, the controller does not run it: it ends the pass with the end entry
> `ControllerRule.stage_repeated`. No path of this decision reaches the guard,
> and a test asserts that none does. The guard is separate from the rules:
> the decision that lets a stage run again — planning after a new
> understanding version, understanding after a contest from the recall hook —
> replaces the guard with the no-progress limit the wiki's Controller page
> names, and changes no rule.

> **Normative.** The attempt's bookkeeping stays inside the stages that do it
> today: persistence order, the reservation, the `ruled` callback,
> `_compared`, the attempt's end gate and every `AttemptPhase` stamp
> (ADR-0249 §6). No rule reads or writes an `AttemptPhase`.

> **Normative.** A later decision adds a stage or a rule by adding members to
> these enums and a row to this table; it does not reorder the rows it does
> not change without saying so. A decision that retires routing removes the
> `routing` stage and rules 2 and 3 from the table; their enum members remain,
> unused, under the never-renamed rule.

The order reproduces ADR-0276 §5's placement — the conversation resolved,
routing declined, understanding before association — and ADR-0074 §2's
conversation resolved before the turn's work, so neither is amended.

**The turn loop's future cut points.** `LearningLoop.respond` is one stage
here. Its planner calls, its read-servicing loop and its investigation stop
rule are where the planning-and-acting milestone will cut it into stages the
controller runs and records. The record's shape does not change when it does;
it gains entries.

### 5. Outcomes and fixed defaults

> **Normative.** `StageOutcome` is a closed, serializable classification in
> `core/types.py`: `done`, `failed` or `timed_out`. A stage that raises yields a
> `StageResult` of `failed` carrying the error; a stage whose deadline expired
> before or during it yields `timed_out` carrying the error; a stage whose
> deadline had already passed when it was due is not run and yields
> `timed_out` carrying the deadline error. Only the `StageOutcome` enters a
> `StageEntry`; the error never does.

> **Normative.** The controller's fixed default for `failed` is to end the
> pass with `ControllerRule.stage_failed`, and for `timed_out` to end it with
> `ControllerRule.stage_timed_out`; in each case it appends the end entry and
> then re-raises the carried error, so `terminal_status` (ADR-0275 §5,
> ADR-0276 §6) classifies the pass as it does today.

> **Normative.** A pass cancelled or interrupted while the controller runs
> ends with the end entry `ControllerRule.interrupted`, appended in the
> controller's `finally` before the cancellation propagates and before
> finalization reads the state.

> **Normative.** A channel activation that ends before the controller is
> entered — cancelled at the admission barrier, or ended at the speech edge
> of §2 — receives its end entry from `ActivationState` at finalization,
> which appends it exactly when the state holds no end entry: `interrupted`
> for a cancellation; `no_text_input` for speech with no words or whose
> transcription failed; `ended_before_controller` for any other failure ahead
> of the controller, such as a delivery report that could not be applied.
> Appending it changes no exception, status or reason the pass already
> carries.

A later decision can give a stage a different default — planning without an
understanding, for example — by changing one rule, not by catching errors in
the engine.

### 6. The stage record

> **Normative.** Add to `core/types.py` the frozen, `extra="forbid"` model
> `StageEntry` with exactly these fields: `stage: ControllerStage`;
> `due: ControllerRule`; `started_at: UtcInstant`; `ended_at: UtcInstant`;
> `outcome: StageOutcome`. `ControllerStage`, `ControllerRule` and
> `StageOutcome` are added to `core/types.py` beside it.

> **Normative.** Every channel activation records one entry per stage run and
> **exactly one end entry**, last — appended by the controller when it ends the
> pass, and otherwise by `ActivationState` at finalization under §5 — whose `stage` is `end`, whose `due` is the
> rule that ended the pass, and whose `outcome` is `done`. No meaning is
> carried by the absence of an entry.

> **Normative.** An entry carries no stage result. The results stay where the
> episode already keeps them — the understanding versions and their omission,
> the links, the response, the status and the reason — and the record names
> which stage ran, why it was due and how it ended.

> **Normative.** `started_at` and `ended_at` are readings of the injected
> clock, as ADR-0275 §4 takes the record's own; an end entry's two readings
> are equal.

> **Normative.** Entries accumulate on `ActivationState` as each stage ends
> and are readable there while the pass runs. They are written **once**, at
> capture, into the processing record with the rest of it; ADR-0275 §8's
> capture-once rule stands, and nothing is written durably before
> finalization.

> **Normative.** The record is bounded at `STAGE_RECORD_LIMIT` entries, a
> composition-root constant with initial value **64**. Where more were
> recorded, the tuple keeps the first `STAGE_RECORD_LIMIT // 2` entries and
> the last `STAGE_RECORD_LIMIT - STAGE_RECORD_LIMIT // 2`, in order, and
> `stages_elided` counts the entries dropped. The end entry is never elided.

`understanding_omitted` (ADR-0276 §7) overlaps the record: each of its values
can be read from the entries of a controller-run pass. It stays, because it is
also the only statement of why a resume episode carries no understanding
(`no_input`), and resume carries no stage record.

### 7. Retention, inspection and the wire

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes
> `Literal[3]`, and the record gains `stages: tuple[StageEntry, ...] = ()` and
> `stages_elided: int = 0` in `[0, 2**31)`. A record whose trigger is a
> `RecordedChannelTrigger` carries a non-empty `stages` whose last entry, and
> only that entry, has `stage` `end`; a record whose trigger is a
> `RecordedResumeTrigger` carries an empty `stages` and `stages_elided=0`;
> both enforced by validator. No reader for a version-2 record exists.

> **Normative — fresh state, on ADR-0275 §12's own mechanism.** Advance the
> episode-record format marker (`EPISODE_RECORD_FORMAT`), so that a store
> written before this decision is refused before mutation with
> `IncompatibleStateError` exactly as ADR-0275 §12 refuses an older store, and
> its files are neither erased nor upgraded. No migration, backfill or
> version-2 read path is a deliverable.

> **Normative.** The episode's canonical detail (ADR-0275 §10) carries the
> record as it carries every other field. The human rendering of
> `assistant episode` shows each entry's stage, rule, outcome and duration in
> order, and the elided count where the record carries one. Inspection invokes
> no model (ADR-0275 §11).

> **Normative.** `EpisodicMemory.processing_record` crosses the wire, so each
> change that alters its shape advances `PROTOCOL_VERSION` in that change, on
> ADR-0124 §9's rule, with the wire surface/type closure and the memory and
> engine conformance suites extended with the shape. No compatibility shim or
> lenient decode is added.

> **Normative.** Retention, deletion, export, placement and disclosure are
> ADR-0275 §9's, unchanged. A stage record grants no authority and is read by
> no model this decision wires.

### 8. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then
> the implementation ships as separate PRs in this order:
>
> 1. **`core` with `wire` — additive only.** §6's types and §7's two record
>    fields with their defaults, `schema_version` still `Literal[2]` and **no**
>    validator of §7, with the `PROTOCOL_VERSION` advance and the wire
>    surface/type closure.
> 2. **`orchestration`** — the controller, its stages, its rules, its fixed
>    defaults, the edge's `no_text_input` entry and the record on
>    `ActivationState`, written at capture into the fields of step 1.
> 3. **The cutover — `core`, `memory` and `wire`, permitted expressly here as
>    one mechanical unit:** `schema_version` becomes `Literal[3]` with §7's
>    validators, a second `PROTOCOL_VERSION` advance, and the format marker's
>    advance with its startup check and fresh-store initializer.
> 4. **`interfaces`** — the rendering of §7.
>
> Step 2 depends on step 1; steps 3 and 4 on step 2.

> **Normative.** Step 2's tests assert, for each activation kind, the exact
> entries its record carries, end entry included: a typed turn that drives a
> step; a typed turn that raises a question; an informational event with the
> understanding stage unwired, which still records `event_summary`; a turn that ends in a
> disambiguation; a turn whose step parks for confirmation; a routed turn; a
> spoken turn; a spoken turn with no words; a spoken turn whose
> transcription fails; an informational event; a pass whose understanding
> fails; a pass whose understanding times out; a composition that returns a
> degraded reply without raising, which records one `compose` entry and then
> `nothing_due`; a pass cancelled while the controller runs; a pass cancelled
> at the admission barrier before the controller is entered; and a pass
> cancelled during the speech edge's delivery-report or transcription work.
> A test over fake stages drives a rule that names an already-run stage and
> asserts the `stage_repeated` end entry, and each activation-kind test
> asserts that no entry is `stage_repeated`. The rules and the controller are tested over constructed
> states and fake stages, including elision that keeps the end entry.

> **Normative.** Each implementation PR lists every existing behaviour it
> changes, each with its reason, and the gate passes on every PR. Existing
> tests that assert an outcome keep passing; a test that asserts only the
> internal call order of `Engine._run_turn` may be rewritten against the
> rules.

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each
> affected ADR's status line and in a dated header note, atomically with this
> file, under ADR-0070 §4 and ADR-0082 §1. Preserve earlier supersessions and
> every ratified body. The replacements take effect on ratification.

| Decision | Replaced scope and what remains |
| --- | --- |
| ADR-0275 §1 | "Phase/tool history" leaves the exclusion list for §6's record of stages alone. A tool history, a live activation log and every other exclusion stand. |
| ADR-0275 §4 | The record gains `stages` and `stages_elided`. Every existing field, value and validator stands. |
| ADR-0276 §7 | The first clause's `schema_version` literal becomes `3`. The understanding fields, the exactly-one validator and every other clause stand. |

> **Normative.** ADR-0074 §2, ADR-0197 and its amenders, ADR-0200, ADR-0203,
> ADR-0205, ADR-0249 §6, ADR-0250 §3 and §15, and ADR-0276 §5 remain binding as
> this decision reads them, and nothing above is a replacement of any of them.

> **Normative.** This decision does not provide the per-phase processing
> history ADR-0249 §13 defers or the prerequisite the observation milestone
> names on #2528. The turn loop is one stage, so its planning rounds, reads
> and investigation are not in the record; that history arrives when a later
> decision splits the turn loop into stages the controller runs.

## Consequences

**What becomes possible.** Every channel activation's episode says which
stages ran, why each was due and why the pass ended, and the same record is
readable while the pass runs. A later milestone adds recall as a stage and a
rule, lets a new understanding version make planning due again, or gives a
failed stage a different default, each without restructuring the engine. When
the turn loop splits, its rounds become entries in the same record.

**What it costs.** One more `core` type family and a record field on the wire.
The hub's data directory starts fresh at the cutover, as it did for M36 and
M37. Engine tests that asserted the internal order of `Engine._run_turn` are
rewritten against the rules.

**What it deliberately leaves.** No new phase is built. `resume` keeps its path
and records no stages. Routing and voice keep working, quarantined, until
their replacements supersede ADR-0197 and ADR-0200. `understanding_omitted`
stays until resume goes through the controller. Nothing is written durably
mid-pass; that belongs to the milestone that makes effects durable.

**What would reopen this decision.** The planning-and-acting split, which adds
stages and rules. Routing returning as tool calls, which retires the `routing`
stage. The channel work returning voice as a sensor and an actuator, which
replaces the edge. A need to see an activation's progress across a hub
restart, which moves the record to a durable write-ahead store.

## Alternatives considered

- **A transition table** instead of readiness rules. Rejected in §3.
- **Rules keyed on whether a stage has run.** Simpler to state for one pass
  that never reruns, but it is a transition table spelled as flags: every later
  rerun would have to rewrite each rule. Rejected for rules over decisions and
  one separate loop guard (§4).
- **Naming the stages after the wiki's phases.** Rejected in §1: the mapping
  does not exist yet.
- **Folding the record into `AttemptPhase`.** Ruled out by the owner.
  Attempts belong to goals, and a later milestone replaces that structure.
- **The record in its own store, written as each stage ends.** It gives crash
  visibility now, but contradicts ADR-0275 §1's exclusion of a live activation
  log, and it arrives better with the durable-effects milestone, which needs a
  write-ahead record anyway.
- **A stage interface in `core/protocols.py`.** Rejected in §3.
- **Wrapping `resume`.** Its admission happens partway through the runner,
  under the recovery lock, and a later milestone replaces parks. Ruled out; the
  gap is that resume episodes record no stages meanwhile.
- **Removing routing and refusing spoken input now.** It would keep the
  controller free of both, but the ratified clauses that require them reach
  some fifteen ADRs — ADR-0197 and ADR-0201 whole, ADR-0205 and ADR-0207
  whole, ADR-0274 §4's dispatch table, most of ADR-0200, the routing-trail
  Protocols of ADR-0279 §2, and required tests across ADR-0198, 0203, 0204,
  0207, 0221, 0223, 0226, 0230, 0240, 0248, 0250, 0264 and 0276. Each removal
  belongs in the decision that brings its replacement. Rejected for the
  quarantine of §2.
- **Rules that read the spoken operation's audience.** The audience is already
  declared by ADR-0200 §3 and applied inside the stages; lifting it into the
  rules would shape the controller around a path that is to be replaced.
  Rejected; it stays inside the stages.
