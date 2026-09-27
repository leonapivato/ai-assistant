# 280. An activation controller runs the stages by rules and records every choice with the episode

- Status: Proposed
- Date: 2026-09-27
- Scope: [M38](https://github.com/leonapivato/ai-assistant/milestone/5), [#2576](https://github.com/leonapivato/ai-assistant/issues/2576).
- Dependency: ADR-0275, ADR-0276 and their milestones M36 and M37.
- Authorization: the owner accepted the proposal on #2577 on 2026-09-27, after ruling its scope on #2576 the same day, and directed its conversion into this ADR. The dispatcher assigned the next available number, 0280. That authorizes drafting and numbering, not ratification or implementation.
<!-- SUPERSESSION HEADER LINES -->

## Context

An activation's processing is a fixed sequence written into one engine
method. `Engine._run_turn` routes the utterance, reads the conversation's
history, runs the understanding stage, associates a goal, reconciles a
continuing goal, calls `LearningLoop.respond`, drives the first step,
composes and captures, and every decision about whether one of those runs is
a branch somewhere in that method or inside a stage. An informational event
takes a second fixed sequence in `Engine._dispatch_channel`. Nothing records
which of those steps ran or why.

The owner's direction on the wiki's
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller)
page (revision `f18ccf6`, direction and not ratified) replaces the fixed
sequence with a controller that runs whatever is due by rules, never calls a
model, records every choice, and lets later work add a phase, rerun one or go
back. This decision builds that controller's skeleton and nothing of the new
phases the page describes: recall, digesting, closing and the recall hook are
later milestones' work.

The inventory recorded on #2576 at `8265b204` sorted every branch on the
activation paths into three kinds: whether a stage runs, which is a
controller rule; what a stage is given, which is context assembly; and how a
stage works, which stays in the stage. It found few branches of the first
kind, and it found that only channel input and `AssistantEngine.resume` are
activations — `answer`, `withdraw_clarification`, `abandon_goal` and
`cancel_read` admit no activation and capture no episode.

The owner ruled the milestone's scope on #2576 on 2026-09-27:

- the controller is built to the target shape, and **existing behaviour may
  break temporarily** until the later phases land, provided each break is
  listed;
- it covers channel activations only, and `resume` keeps its legacy path;
- ADR-0249 §6's `AttemptPhase` stays untouched inside the stages and separate
  from the controller's record;
- channels are text only for now and spoken input is refused, pending
  separate channel work (#2578) in which a channel becomes a sensor for input
  and an actuator for output;
- intent routing is removed for now, to return as tool calls planning plans
  and acting runs.

The last two are scoping, not design. They are recorded in §2 because the
code change they need contradicts ratified clauses, which only a newer ADR
may replace.

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
> admitted through `Engine._receive` or `Engine._streamed`: text conversation
> turns and informational events. `AssistantEngine.resume` keeps its existing
> path, and an episode with a `RecordedResumeTrigger` carries no stage record.

**Why stage and not phase.** One stage, understanding, does one phase's job.
The turn loop plans and services reads; driving a step authorizes and acts;
beginning the conversation, associating a goal and reconciling are no phase
at all; composing is part of what planning or closing will do. Naming the
record after phases would claim a mapping that the later milestones have not
built yet.

### 2. Scope for now: text only, and no routing

> **Normative.** Channels are text only. A speech payload is refused at
> admission, before any activation state exists, with a `ValueError` naming
> spoken input as unsupported, on every entry point that accepts one:
> `AssistantEngine.converse_spoken` and `AssistantEngine.receive`. No model,
> store, transcription or reply-delivery side effect precedes the refusal.

> **Normative.** The spoken turn path — transcription, synthesis, playback
> delivery reports, `_SpokenCapture` and the choice of
> `UnboundedAudienceSupply` on a conversational pass — is removed from the
> turn path and is not carried by the controller.

> **Normative.** Intent routing is removed from the turn path: no pass
> consults `RoutingStage`, no pass performs a routed operation, and no routed
> park is created. `AssistantEngine.resume` on a handle that names no live
> park restates or refuses under its existing rules.

<!-- SUPERSESSION SCOPE TABLE -->

The controller relies on these assumptions and on nothing else about
channels: every activation it runs is text; a reply, where one is owed, is
text on the originating request; an informational event owes none; and every
reply's audience is the owner. No rule of §4 reads the payload modality, the
conversational operation or the reply capability.

### 3. The controller

> **Normative.** `ActivationController` is an orchestration-local class in
> `orchestration/controller.py`, constructed with its stages and its rules.
> It is not a Protocol, and `core/protocols.py` gains no member for it or for
> the stage interface.

> **Normative.** A stage, as the controller runs it, has a `ControllerStage`
> name and one method, `async run(state) -> StageOutcome`. A stage adds its
> results to the pass's state and never chooses what runs next.

> **Normative.** The controller repeats one step until the pass ends: evaluate
> §4's rules in their fixed order against the pass's state and the last
> outcome; take the first rule that answers; if it names a stage, run that
> stage and append its entry (§6); if it ends the pass, append the end entry
> and stop.

> **Normative.** The controller calls no model and makes no store read or
> write of its own. Everything it decides on is on `ActivationState`, and no
> text produced inside the activation is read by a rule.

> **Normative.** `ActivationState` carries the pass's **working set**: the
> in-flight results the rules read — whether the conversation is resolved,
> whether understanding was entered, the association, whether reconciliation
> ran, the turn `LearningLoop.respond` returned, the drive's disposition and
> whether a reply was composed. The working set is never persisted.

> **Normative.** Understanding, association, reconciliation, the turn loop,
> driving and composing each run as the existing stage or engine method they
> wrap, with the same inputs and effects, except where §2 removes an input.
> `LearningLoop.respond` runs as one stage.

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
> renamed**, with exactly these members: `begin_conversation`,
> `understanding`, `event_summary`, `associate_goal`, `ask_disambiguation`,
> `reconcile`, `turn_loop`, `drive`, `compose` and `end`.

> **Normative.** `ControllerRule` is a closed `StrEnum`, **added to and never
> renamed**, with exactly the members the table below and §5 name.

> **Normative.** The rules are evaluated in the order of this table, and the
> first that answers decides:

| # | Rule | Answers when | Makes due |
| --- | --- | --- | --- |
| 1 | `conversation_unresolved` | A conversation turn whose conversation is not yet resolved | `begin_conversation` |
| 2 | `not_understood` | The understanding stage is wired and was not yet entered | `understanding` |
| 3 | `event_understood` | An informational event whose summary has not run | `event_summary` |
| 4 | `association_due` | A conversation turn not yet associated | `associate_goal` |
| 5 | `disambiguation_raised` | The association asks which goal is meant, and the question was not yet asked | `ask_disambiguation` |
| 6 | `continuing_unreconciled` | The association continues a goal, reconciliation is wired and has not run | `reconcile` |
| 7 | `unplanned` | A conversation turn associated without a disambiguation, whose turn loop has not run | `turn_loop` |
| 8 | `plan_has_steps` | The turn raised no question, its plan has steps, and no step was driven | `drive` |
| 9 | `reply_owed` | The turn loop ran, no step parked for confirmation, and nothing was composed | `compose` |
| 10 | `nothing_due` | Always | the end of the pass |

> **Normative.** `nothing_due` is last and always answers, so every pass the
> controller runs ends by a rule.

> **Normative.** The check that skips composing for a step parked for
> confirmation is rule 9's, and the composer no longer makes it.

> **Normative.** Association runs on every conversation turn. The checks
> `operation is not ConversationalOperation.CONVERSE_SPOKEN` that skip
> association and the understanding stage's episode window are removed with
> the spoken path (§2), and no audience condition replaces them.

> **Normative.** The attempt's bookkeeping stays inside the stages that do it
> today: persistence order, the reservation, the `ruled` callback,
> `_compared`, the attempt's end gate and every `AttemptPhase` stamp
> (ADR-0249 §6). No rule reads or writes an `AttemptPhase`.

> **Normative.** A later decision adds a stage or a rule by adding members to
> these enums and a row to this table; it does not reorder the rows it does
> not change without saying so.

**The turn loop's future cut points.** `LearningLoop.respond` is one stage
here. Its planner calls, its read-servicing loop and its investigation stop
rule are where the planning-and-acting milestone will cut it into stages the
controller runs and records. The record's shape does not change when it does;
it gains entries.

### 5. Outcomes and fixed defaults

> **Normative.** `StageOutcome` is `done`, `failed` or `timed_out`. A stage
> that raises returns `failed` carrying the error; a stage whose deadline
> expired before or during it returns `timed_out` carrying the error; a stage
> whose deadline had already passed when it was due is not run and returns
> `timed_out`.

> **Normative.** The controller's fixed default for `failed` is to end the
> pass with `ControllerRule.stage_failed`, and for `timed_out` to end it with
> `ControllerRule.stage_timed_out`; in each case it appends the end entry and
> then re-raises the carried error, so `terminal_status` (ADR-0275 §5,
> ADR-0276 §6) classifies the pass as it does today.

> **Normative.** A pass cancelled or interrupted while the controller runs
> ends with the end entry `ControllerRule.interrupted`, appended in the
> controller's `finally` before the cancellation propagates and before
> finalization reads the state.

A later decision can give a stage a different default — planning without an
understanding, for example — by changing one rule, not by catching errors in
the engine.

### 6. The stage record

> **Normative.** Add to `core/types.py` the frozen, `extra="forbid"` model
> `StageEntry` with exactly these fields: `stage: ControllerStage`;
> `due: ControllerRule`; `started_at: UtcInstant`; `ended_at: UtcInstant`;
> `outcome: StageOutcome`. `ControllerStage`, `ControllerRule` and
> `StageOutcome` are added to `core/types.py` beside it.

> **Normative.** Every pass the controller runs records one entry per stage
> run and **exactly one end entry**, last, whose `stage` is `end`, whose `due`
> is the rule that ended the pass, and whose `outcome` is `done`. No meaning is
> carried by the absence of an entry.

> **Normative.** An entry carries no stage result. The results stay where the
> episode already keeps them — the understanding versions, the links, the
> response, the status and the reason — and the record names which stage ran,
> why it was due and how it ended.

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

### 7. Retention, inspection and the wire

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes
> `Literal[3]`, and the record gains `stages: tuple[StageEntry, ...] = ()` and
> `stages_elided: int = 0` in `[0, 2**31)`. A record whose trigger is a
> `RecordedChannelTrigger` carries a non-empty `stages` whose last entry is an
> end entry and whose other entries are not; a record whose trigger is a
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

`understanding_omitted` (ADR-0276 §7) overlaps the record for the activations
the controller runs: `failed` and `not_reached` can be read from the entries,
and `routed` and `no_text` no longer occur. It stays, because it is the only
statement of why a resume episode carries no understanding (`no_input`), and
resume carries no stage record.

### 8. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then
> the implementation ships as separate PRs in this order:
>
> 1. **`core`** — `validate_combination` refuses the speech combination (§2).
> 2. **`orchestration`** — the spoken turn path and routing leave the turn
>    path (§2), with every engine test that exercised them rewritten or
>    removed, each named in the PR with its reason.
> 3. **`core` with `wire` — additive only.** §6's types and §7's two record
>    fields with their defaults, `schema_version` still `Literal[2]` and **no**
>    validator of §7, with the `PROTOCOL_VERSION` advance and the wire
>    surface/type closure.
> 4. **`orchestration`** — the controller, its stages, its rules, its fixed
>    defaults and the record on `ActivationState`, written at capture into the
>    fields of step 3.
> 5. **The cutover — `core`, `memory` and `wire`, permitted expressly here as
>    one mechanical unit:** `schema_version` becomes `Literal[3]` with §7's
>    validators, a second `PROTOCOL_VERSION` advance, and the format marker's
>    advance with its startup check and fresh-store initializer.
> 6. **`interfaces`** — the rendering of §7.
>
> Step 2 depends on step 1; step 4 on steps 2 and 3; steps 5 and 6 on step 4.

> **Normative.** Step 4's tests assert, for each activation kind, the exact
> entries its record carries, end entry included: a typed turn that drives a
> step; a typed turn that raises a question; a turn that ends in a
> disambiguation; a turn whose step parks for confirmation; an informational
> event; a pass whose understanding fails; a pass whose understanding times
> out; and a cancelled pass. The rules and the controller are tested over
> constructed states and fake stages, including elision that keeps the end
> entry.

> **Normative.** Each implementation PR lists every behaviour it breaks
> deliberately, each with its reason, and the gate passes on every PR.

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each
> affected ADR's status line and in a dated header note, atomically with this
> file, under ADR-0070 §4 and ADR-0082 §1. Preserve earlier supersessions and
> every ratified body. The replacements take effect on ratification.

<!-- SUPERSESSION RELATIONSHIP TABLE -->

> **Normative.** This decision does not provide the per-phase processing
> history ADR-0249 §13 defers or the prerequisite the observation milestone
> names on #2528. The turn loop is one stage, so its planning rounds, reads
> and investigation are not in the record; that history arrives when a later
> decision splits the turn loop into stages the controller runs.

## Consequences

**What becomes possible.** Every text activation's episode says which stages
ran, why each was due and why the pass ended, and the same record is readable
while the pass runs. A later milestone adds recall as a stage and a rule, lets
a new understanding version make planning due again, or gives a failed stage a
different default, each without restructuring the engine. When the turn loop
splits, its rounds become entries in the same record.

**What it costs.** Voice stops: the phone and the gateway's voice page are
refused until the channel work (#2578) brings voice back as a sensor and an
actuator. The routed operations stop until they return as planned tool calls.
The hub's data directory starts fresh at the cutover, as it did for M36 and
M37. Engine tests that asserted the internal order of `_run_turn` are
rewritten against the rules.

**What it deliberately leaves.** No new phase is built. `resume` keeps its
path and records no stages. Channel audience, what a channel owes and its
limits are the channel work's. `understanding_omitted` stays until resume goes
through the controller. Nothing is written durably mid-pass; that belongs to
the milestone that makes effects durable.

**What would reopen this decision.** The channel work returning voice, which
supersedes §2's refusal and adds whatever rules an audience needs. Routing
returning as tool calls. The planning-and-acting split, which adds stages and
rules. A need to see an activation's progress across a hub restart, which
moves the record to a durable write-ahead store.

## Alternatives considered

- **A transition table** instead of readiness rules. Rejected in §3.
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
- **Keeping voice on a legacy copy of the turn path.** Two turn pipelines side
  by side through several milestones is the tangle the controller exists to
  remove. Ruled out; spoken input is refused.
- **A declared audience per channel.** An earlier draft had each channel
  declare its audience. The code showed the audience rests on choices the
  spoke makes, which is channel work; moved to #2578.
