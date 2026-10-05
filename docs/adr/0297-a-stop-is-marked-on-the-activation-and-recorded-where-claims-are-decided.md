# 297. A stop is marked on the activation and recorded where claims are decided

- Status: Proposed
- Date: 2026-10-05
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: how a stop bites, which ships with the conversation channel (ADR-0293 §11:8, ADR-0295 §6).
- Dependency: ADR-0295, ratified.
- Authorization: the dispatcher, under the owner's ruling of 2026-10-04 that how each phase honours a stop is the phases' design (ADR-0295 §2) and the owner's standing direction that mechanism design is the lanes'. The dispatcher assigned 0297. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0255](0255-the-driver-walks-a-plan-in-dependency-order-claims-each-step-under-its-attempt-and-stops-rather-than-acting-under-an-unfinished-one.md) — **one scope.** **§11:1's *"Nothing else"* closure over `StepTransition`, in the addition alone**: `StepTransition` gains `activation_id` (§2 below). Every other clause stands, §3's conjuncts, validator, threading and refusal classes included.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **two scopes, each for a pass whose stop has been taken in.** **§3:3's step**: the controller reads the stop before it evaluates the rules and once a stage's result is in hand, and leaves the loop on it (§4 below). **§5:2's fixed default**: a stage that failed or timed out after the stop was taken in ends the pass with the stop's end entry, and its error is not re-raised (§4 below). Every other clause stands, and both clauses stand entire for every pass no stop reaches.
- **Partially supersedes** [ADR-0170](0170-a-reply-is-not-a-tool-the-turn-composes-its-answer-and-the-outcome-carries-it.md) — **one scope.** **§4:1's shapes on which `reply` is `None`, in the addition alone**: a fourth, the outcome of a resume a stop ended, marked by `TurnOutcome.stopped` and never `reply_degraded`, stated in both directions by §4:3's validator (§4 below). §4:2's flag rule stands entire: `reply_degraded` is not set on the new shape. Every other clause stands.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **three scopes.** **§4:1's `ProcessingReason` values, in the addition alone**: `stopped`. **§5:3's table, in the addition alone**: a first row, *a stop ended the pass*, classified `interrupted / stopped`. **§5:6's *"original outward exception … remain[s] intact"*, for a stopped pass alone**: a turn call awaiting it raises `ActivationStoppedError`, and a stopped resume returns its outcome with no reply (§4 below). Every other clause stands.

## Context

**The question.** ADR-0295 decided what a stop guarantees: nothing new starts in a stopped
activation once the stop has landed; an effect's claim made after the stop is refused by
the store, the store deciding which of the two landed first; an effect already sent is not
cut off and its outcome is recorded; nothing acquired is orphaned; the episode ends with a
stop's own end entry; nothing new is written into the conversation; and the conversation's
current state carries the running activation's id and shows *stopped*. By the owner's
ruling of 2026-10-04 it left **how** each phase honours those guarantees to the phases'
design. This ADR is that design, for every phase at once, and it decides only the
mechanism: nothing here re-decides a guarantee of ADR-0295.

**The gap ADR-0295 leaves for a mechanism.** A cancellation bites at the claim because it
ends the attempt, and ADR-0255 §3's attempt conjunct refuses a claim under an attempt that
is terminal or paused (ADR-0261 §4:1). A stop cannot take that route. ADR-0261 §1:4 rules
that there is *"no act that ends an attempt while leaving its goal open"*, and a stop must
leave the goal standing (ADR-0295 §4:1); pausing the attempt instead would borrow a state
whose meaning is *waiting on the user's answer*, which a stop is not. And an attempt
outlives an activation — a step parked in one activation is resumed in another — so a
fence on the attempt would bind work the stop does not name. **The claim needs a value of
its own to be refused on, keyed to the activation the stop names.**

**What exists**, as dated observations at `9589e3b2`:

- **One claim site.** The only construction of a `→ RUNNING` `StepTransition` in the tree
  is `StepExecutor`'s claim in `orchestration/executor.py`; `StepRunner.run` and
  `StepRunner.resume` reach it, each threading `attempt_id` as ADR-0255 §3:14 rules.
  `StepTransition` carries `attempt_id` and **no** activation.
- **The activation's id.** `ActivationState.activation_id` is minted at admission, a
  canonical UUID4 (ADR-0275 §6:1), for a channel activation (`admit_channel`) and for the
  control activation that resolves a park (`admit_resume`); it is `None` only where the
  injected id factory failed, which degrades capture and does not stop the turn.
- **The controller's loop.** `ActivationController.run` evaluates the rules, runs the stage
  the first answering rule names, and in its `finally` appends `ControllerRule.INTERRUPTED`
  where no end entry was appended (ADR-0280 §3:3, §5:3). It reads nothing but the pass's
  state (§3:4). A resume is not run by the controller and records its own entries
  (ADR-0284 §5:5).
- **Where claims are decided.** Every claim is decided inside `PlanStore.commit_transition`,
  in one indivisible step, on ADR-0014 §5's ground: *"it belongs to the store because the
  store is the only place with a total order over writes."* No other store holds a claim.
- **No stop.** Nothing records a stop, nothing in `ControllerRule` or `ProcessingReason`
  names one, and `AssistantEngine` has no member for one.

**The ADRs this touches**, as they stand on `main`:

| ADR | What it decides today | How this decision relates |
| --- | --- | --- |
| ADR-0295 §§1–5 | What a stop guarantees, and that how each phase honours it is the phases' design. | Implemented: this is that design. Nothing re-decided. |
| ADR-0261 §1:4, §4, §7 | A cancellation ends the goal, not an attempt; it bites through ratified conjuncts and adds none; `ClaimRefused` is raised by exactly two liveness conjuncts. | Applied and unchanged: a stop ends no attempt (§2), §4:1's *"adds no claim condition"* is that decision's own statement and stays true of it, and the stop's refusal is a class of its own (§2), so §7:3's *"exactly two"* stands. |
| ADR-0255 §3, §11:1 | The claim names its attempt; three claim conditions; `StepTransition` gains nothing else. | §3 applied one conjunct over; §11:1's closure partially superseded, in the addition alone (§2). |
| ADR-0014 §5 | The store's total order decides between writes. | Applied: it decides between a stop and a claim (§1, §2). |
| ADR-0280 §3:3, §5:2, §5:3 | The controller's step; a failed stage ends the pass and re-raises; a cancelled pass ends `interrupted` in the `finally`. | §3:3 and §5:2 partially superseded for a stopped pass; §5:3's point is where the stop's end entry is appended, as ADR-0295 §3:2 rules (§4). |
| ADR-0275 §4:1, §5:3, §5:6 | `ProcessingReason`'s values; the ordered terminal table; outward exceptions intact. | Partially superseded: `stopped`, a first row, and the outward exception of a stopped pass (§4). |
| ADR-0170 §4, ADR-0235 §6:10 | `reply` is `None` on exactly three shapes; `resume` returns wherever an answer was recorded. | ADR-0170 §4:1 partially superseded, in the addition: a stopped resume returns, with no reply and `stopped` set (§4). |
| ADR-0060 | Cancellation must not orphan a resource a seam acquired. | Kept by construction: a stop cancels no task (§4). |
| ADR-0293 §8, §10 | The current state; the adapter writes the reply or *couldn't finish*. | Applied as ADR-0295 amended it (§4, §5). |
| ADR-0004 §6 | The user can view, export and delete their data. | Kept: the stop record is exported and cleared with the store (§1). |

## Decision

We will make a stop two writes in a fixed order: a **mark** on the running activation's
in-process state, which the controller and a resume read and which ends the pass before
its next stage, and then a **stop record** in the plan store, against which the
store refuses every later claim made under that activation. No task is cancelled, so an
effect already sent finishes and records its own outcome.

> **Normative.** §§1–6 govern how a stop is recorded, how it bites at a claim, how a pass
> it reaches ends, and the engine surface that gives it.

### 1. The stop record

> **Normative.** `PlanStore` gains one member, `record_stop(activation_id: str, /) -> None`,
> which writes a stop record naming that activation, and nothing else, in one indivisible
> step.

> **Normative.** `record_stop` is idempotent: recording a stop for an activation the store
> already holds one for writes nothing and raises nothing, and it refuses no activation
> id, since the store knows nothing of which activations ran.

> **Normative.** The stop record lives in the plan store and in no other store, because
> the claim it must refuse is decided there and only the store that decides a claim holds
> a total order over it (ADR-0014 §5).

> **Normative.** A stop record carries the activation id alone: no instant, no reason,
> no conversation and no content.

When the user stopped is already recorded where the user reads it, as the episode's end
entry (§4).

> **Normative.** `PlanExport` gains `stopped_activations`, the tuple of activation ids
> the store holds a stop record for, and its `schema_version` advances by one; `clear`
> erases every stop record with the store's other rows; `delete_goal` reaches none,
> since a stop record names no goal.

That keeps ADR-0004 §6's view, export and deletion limbs over the one datum this decision
adds rather than taking a scope on them, as ADR-0268 had to for a record no export carried.

> **Normative.** No stop record is removed while the store holds its rows, and no lane
> adds an expiry, a sweep or a release member for one.

A stop record matters only while its activation can claim, and activation ids never
recur (ADR-0275 §6:1), so a record that outlives its activation fences nothing; one row
per stop the user gives is the whole of its growth.

### 2. The claim names its activation, and a stopped one is refused

> **Normative.** `StepTransition` gains `activation_id`, an `Identifier | None` defaulting
> to `None`, naming the activation a `→ RUNNING` claim is made under; its model validator
> forbids it on every other `to_status`.

> **Normative.** Every claim made under an activation that has an id names that id: a
> turn's drive, and a resume's claim, which names the control activation that resolves
> the park.

> **Normative.** A claim names no activation only where the activation it is made under
> has no id, and no lane omits the id on any other ground.

An activation with no id can be named by no stop, so no stop record can exist for a claim
of it to be refused on: the conjunct below is vacuous there because the stop is
unreachable, not because the claim escapes it. That is why the field is not required on
`→ RUNNING` as `attempt_id` is (ADR-0255 §3:2): requiring it would make the one activation
a failed id factory leaves unable to act at all, which ADR-0275 §6:1's degradation does
not do today.

> **Normative.** `PlanStore.commit_transition` refuses a `→ RUNNING` transition that names
> an activation the store holds a stop record for, decided in the same indivisible step
> as the write, with no separate read on which the decision is taken (ADR-0255 §3:16's
> rule, one conjunct over).

> **Normative.** That refusal raises `ClaimStopped`, a new `PlanningError` subclass in
> `core/errors.py` that is not a `StaleExecutionError` and not a `ClaimRefused`, raised
> by this conjunct and by nothing else.

It is not stale, because no re-read makes the claim land: a stop is never withdrawn. It is
not `ClaimRefused`, because ADR-0261 §7:3 has that class raised by exactly two liveness
conjuncts and makes catching it mean that the goal's state can be read and reported; a
stop changes no goal state, so the read would establish nothing, and the class stays
exactly as ADR-0261 scoped it.

> **Normative.** `ClaimStopped` carries a message and no structured state, and it
> propagates out of the walk as ADR-0261 §7:2 has every exception but `ClaimRefused`
> propagate; no lane composes a reply about it.

What the pass then does is §4's: the controller ends a channel activation as stopped
whatever the stage that met the refusal did, and a resume ends as stopped and returns the
outcome §4 gives it.

> **Normative.** The ordering between a stop and a claim is the store's: where the stop
> record lands first, the claim is refused, nothing is invoked, and the step stays at its
> entry status and stored version (ADR-0255 §3:22); where the claim lands first, it
> stands, the effect proceeds, and the step's own disposal records its outcome as done,
> not done or unknown (ADR-0295 §2:3).

There is no third case, the store's total order admitting no instant between the two
writes — ADR-0261 §4:2's reasoning, applied to a different pair of writes.

> **Normative.** Where a stop record and another claim condition would both refuse one
> claim, which class the store raises is not fixed, and no caller depends on it.

The pass ends as stopped either way (§4), and a conformance test asserts each refusal on
its own.

> **Normative.** The activation id is compared and not stored: `StepExecution` gains no
> field for it, and the step's committed row is unchanged.

> **Normative.** `StepRunner.run`, `StepRunner.resume` and `StepExecutor.execute` each
> gain one keyword parameter, `activation_id`, which each passes through to the claim
> and reads for nothing else; no stage fetches it.

That is ADR-0255 §3:14's threading, one value over, and like `attempt_id` it is a name the
store checks rather than a subject the gate rules on (ADR-0255 §3:15).

> **Normative.** The stop bites at the step claim and at no other write: `claim_effect`,
> the permission ruling and a park are not refused on a stop record.

The step claim is the boundary every transmission is made under (ADR-0148 §9, ADR-0255
§4:1). An effect row `claim_effect` wrote immediately before a claim the stop then refused
stands as it stands after any refused claim, and ADR-0259 §2's rules decide a later claim of
that intended action. A park is governed by the walk's own reading of the mark (§4), not by
the store.

### 3. The mark, and the order of a stop's two writes

> **Normative.** The engine holds, in process, the `ActivationState` of every activation
> it has admitted and not yet finalized, by activation id, and a stop reaches an
> activation only through it.

That is ADR-0255 §4:4's in-process scope, which ADR-0083's one resident process per data
directory makes sufficient: there is no cross-process signal, no queue and no lease.

> **Normative.** An activation has ended, for a stop, once its end entry is appended,
> whether by the controller or at finalization (ADR-0280 §6:2).

> **Normative.** A stop takes the activation's state, tests whether its end entry is
> appended, and sets the activation's stop mark, in one synchronous step with no await
> between them.

The controller's end entry is appended in a synchronous step of its own (§4), and both run
on the one event loop, so the two are totally ordered: either the mark is set first and the
pass's end entry will be the stop's, or the end entry was appended first and the stop finds
the activation ended. Nothing else decides which.

> **Normative.** A stop sets the mark before it writes the stop record, and only after
> the mark is set does it call `record_stop`.

The order is what makes the record and the end entry agree. A claim refused on the record
is a claim of an activation already marked, so the pass it belongs to ends as stopped (§4);
the reverse order would let a claim be refused by a stop whose pass then ended on a rule as
though nothing had stopped it, and wrote *couldn't finish* about the refusal.

> **Normative.** The mark is never cleared.

> **Normative.** A stop has landed, for ADR-0295 §2's race, when its stop record is
> written; from the mark onwards the activation starts nothing new in process (§4), so
> nothing new starts once the stop has landed.

> **Normative.** Where `record_stop` raises, the stop raises that error, and the mark
> stays set: the activation still ends as stopped and starts nothing new, and a claim of
> a step it entered before the mark is decided by the store as though no stop had been
> made.

A repeated stop of an activation still running writes the record again, idempotently,
which is the retry for that failure.

### 4. How a stopped pass ends

> **Normative.** The controller reads the activation's stop mark before each evaluation of
> the rules and again once each stage's result is in hand, before it applies ADR-0280
> §5:2's fixed default.

> **Normative.** Where the mark is set, the controller leaves its loop without evaluating
> the rules, running a stage, or appending an end entry itself.

> **Normative.** The controller's `finally`, finding no end entry, appends
> `ControllerRule.STOPPED` where the mark is set and `ControllerRule.INTERRUPTED` where it
> is not.

That is the point ADR-0280 §5:3 names, which is where ADR-0295 §3:2 rules a stop's end
entry is appended. **`ControllerRule.STOPPED`, valued `"stopped"`, is the member ADR-0295
§3:1 added and left unnamed**; it ends a pass, so it is one of the rules that do. A
cancellation that reaches a marked pass still propagates (ADR-0060), and the end entry is
still the stop's.

> **Normative.** A stage that fails or times out after the mark is set ends the pass with
> the stop's end entry, and the error it carries is not re-raised.

The stop was taken in first, so it is what ended the pass; re-raising would classify a
stopped pass as failed and have the adapter write *couldn't finish*, which ADR-0295 §3:3
forbids.

> **Normative.** A pass that ends before the controller is entered appends the stop's end
> entry at finalization where the mark is set, at the point ADR-0280 §5:4 appends
> `interrupted`.

> **Normative.** A resume, which the controller does not run (ADR-0284 §5:5), reads the
> mark before it begins `compose` and nowhere else, composes nothing once it is set, and
> ends with the stop's end entry.

The resume therefore records the user's answer whenever the stop lands, and its claim is
the store's to decide (§2).

> **Normative.** The unit at which nothing new starts is the stage, and the claim: once
> the mark is set no stage begins, and once the stop record is written no claim lands; a
> stage already running when the mark is set is work already started, and the rounds,
> rulings and steps inside it are that stage running to its end.

That is this ADR's reading of ADR-0295 §2:1 under the owner's ruling that *"which work is
interrupted at once, and how each phase stops, is the phases' design"*. A further round of
the turn loop after the mark still services the reads it asks for, within the turn's
planning budget and allowances (ADR-0251 §4), and a walk's next step still meets its
ruling — and is refused at its claim. So no effect starts after the stop has landed,
which ADR-0295 §2:2 makes the store's, and no stage starts after the mark. The one residual
is a step whose ruling is `CONFIRM` and whose park commits after the mark: its confirmation
stands as any pending confirmation stands, answerable where pending confirmations are
listed, and the question it asks is an ended activation's open question (ADR-0295 §1:7).

> **Normative.** A stop cancels no task and adds no deadline: a stage running when the
> mark is set runs to its own end under exactly the deadlines and timeout enforcement it
> runs under today, and a stop neither shortens nor lengthens any of them.

A stage whose budget is enforced by cancelling its own call — recall's (ADR-0281 §5), the
understanding stage's — still ends `timed_out` at that budget; work whose deadline only
gates starting and never cancels what is running (ADR-0255 §9) still runs to its own
completion, and may outlast the pass's budget as ADR-0228 §4 already allows.

> **Normative.** Work already entered when the mark is set writes everything it owes as
> it would had no stop been given — an effect's own disposal and its completion record,
> an effort charge, an attempt's `EFFECT_UNRESOLVED` — before its stage returns.

So ADR-0295 §2:3's *"not cut off"* holds because nothing is cut off, and ADR-0060 holds
because nothing a seam acquired is abandoned mid-call. The cost is that a stop waits for
the stage in flight, for as long as that stage's own contracts let it run, which ADR-0295
already records ("a stop is not instant").

> **Normative.** The stop itself writes nothing to the goal or the attempt: no goal or
> attempt is ended, paused, stamped or charged because a stop was given, and the stages
> the stop keeps from starting write nothing they would have written.

ADR-0295 §4:1's *"the goal … stands as it was"* is then true of the attempt beneath it,
and what the user does next decides both.

> **Normative.** `ProcessingReason` gains `stopped`, and a pass whose end entry is
> `ControllerRule.STOPPED` is classified `interrupted / stopped` ahead of every other row
> of ADR-0275 §5:3's table, the cancellation row included.

> **Normative.** The adapter of ADR-0293 §10 writes nothing for a pass whose end entry is
> `ControllerRule.STOPPED` — no reply, even one already composed, and no *couldn't finish*.

> **Normative.** A turn call awaiting a stopped pass raises `ActivationStoppedError`, a
> new `AssistantError` subclass in `core/errors.py` carrying a message and no structured
> state, in place of what the pass would otherwise return or raise; a cancellation of the
> caller's own task still propagates as itself.

A turn's outcome is assembled by the composing stage the stop keeps from running, and a
turn call already returns no outcome where a stage's failure ends it (ADR-0275 §5:3's
failure rows); what the stopped activation finished, the user reads in the current state
(ADR-0295 §3:5). Under ADR-0293 §11:2 a conversation's text input no longer arrives on a
turn call, so this reaches the turn calls that remain — a spoken turn's, an informational
event's — and any caller still on a legacy route.

> **Normative.** `TurnOutcome` gains `stopped`, a `bool` defaulting to `False`, which is
> `True` exactly on the outcome of a resume whose control activation was stopped.

> **Normative.** A `resume` whose control activation is stopped returns its `TurnOutcome`
> with `stopped` `True`, `reply` `None` and `reply_degraded` `False`, and every other
> field as the resume established it — the step's outcome and the recipient-grant outcome
> among them — whether or not a reply had been composed when the mark was set; a
> cancellation of the caller's own task still propagates as itself.

A resume records the user's answer before it acts (ADR-0255 §3:23), and ADR-0235 §6:10
rules that `resume` *"raises only where no answer was recorded, and returns wherever one
was"*, so a stopped resume returns, and what the answer established reaches the caller who
gave it. That is a fourth shape on which `reply` is `None`, beside ADR-0170 §4:1's three,
and `stopped` is what lets a client tell it from the other three from the value alone, as
§4:2 requires of `reply_degraded`.

> **Normative.** `TurnOutcome`'s model validator states the fourth shape in both
> directions (ADR-0170 §4:3): `stopped` `True` requires `reply` `None` and
> `reply_degraded` `False`, and a `reply` of `None` with `reply_degraded` `False` on a
> pass that has a `turn` and did not park requires `stopped` `True`.

### 5. The engine surface

> **Normative.** `AssistantEngine` gains `stop_activation(activation_id: Identifier, /) ->
> ActivationStop`, the stop command of ADR-0295 §1, naming exactly one activation.

> **Normative.** `ActivationStop` is a closed `StrEnum` in `core/types.py`, valued by
> lower-cased member name and added to and never renamed, with exactly three members:
> `STOPPED`, `ALREADY_ENDED` and `NO_SUCH_ACTIVATION`.

> **Normative.** `stop_activation` answers `STOPPED` where it set the mark, or found it
> already set, on an activation whose end entry was not yet appended, and its stop record
> was written.

> **Normative.** It answers `ALREADY_ENDED`, writing nothing, where the activation's end
> entry was already appended, or where the engine holds no running activation by that id
> but an episode stands at its address, `activation:<activation_id>` (ADR-0283 §2).

That is ADR-0295 §1:6's answer, and it covers an activation a restart closed (ADR-0286
§7), which holds no state in the new process and left an episode.

> **Normative.** It answers `NO_SUCH_ACTIVATION`, writing nothing, where the engine holds
> no running activation by that id and no episode stands at its address.

An activation whose episode was forgotten, or never captured, is answered the same way:
the hub then holds nothing that says it ran, and the answer claims no more than that.

> **Normative.** A device learns the id to name from the conversation's current state,
> which carries the `activation_id` of the activation started from that conversation for
> exactly as long as the current state shows "working…" (ADR-0293 §8:2, ADR-0295 §1:2).

An activation whose id the factory failed to mint shows "working…" with no id and cannot
be stopped; that is the residual of §2's no-id case, stated rather than hidden.

> **Normative.** `stop_activation` checks no device role itself: it is reached only as a
> command (ADR-0292 §12:5), and which devices may send one is decided where every
> command's sender is checked, against the roles the user assigned (ADR-0292 §4:1,
> ADR-0295 §1:4).

> **Normative.** The command line gives a stop as `assistant stop <activation-id>`, and
> prints the answer's meaning.

### 6. The contract, and how it lands

> **Normative.** This is a breaking contract change under golden rule 5: `StepTransition`
> gains a field, `PlanStore` a member and a refusal on `commit_transition`, `PlanExport` a
> field, `AssistantEngine` a member, `TurnOutcome` a field and a fourth reply-less shape,
> `core/types.py` `ActivationStop`, `ControllerRule.STOPPED` and
> `ProcessingReason.STOPPED`, and `core/errors.py` `ClaimStopped` and
> `ActivationStoppedError`.

> **Normative.** Each Protocol change lands with its conformance coverage and its
> canonical fake in the same change, with its primary implementation (ADR-0137 §2): the
> plan store's record, conjunct and export with `planning/`, and the engine member with
> `orchestration/`.

> **Normative.** Each change that alters what crosses the wire — the engine member,
> `ActivationStop`, `ActivationStoppedError`, `TurnOutcome.stopped`, and the new values of
> `ControllerRule` and `ProcessingReason` on the episode record — advances
> `PROTOCOL_VERSION` in that change,
> on ADR-0124 §9's rule.

> **Normative.** The plan store's change lands before any orchestration change that
> relies on its refusal, and the command line and the gateway's stop control land last.

> **Normative.** The plan store's conformance suite asserts: a claim naming a stopped
> activation is refused with `ClaimStopped`, nothing committed; a claim committed before
> the stop record stands; `record_stop` is idempotent; a claim naming no activation, or
> another activation, is unaffected; `activation_id` is unconstructible on any
> `to_status` but `RUNNING`; and the export and `clear` carry and erase the record.

> **Normative.** The engine's tests assert, over a seeded fake: a stop during the drive
> refuses the next claim and the pass ends `stopped`; an effect claimed before the stop
> completes, records its outcome and the bookkeeping it owes, even where that outlasts the
> pass's budget; a stop before the controller is entered, and one during a stage that
> then fails, each end `stopped`; a stopped pass writes nothing into its conversation and
> its waiting messages are then taken in (ADR-0295 §3:6); a resume stopped after its
> answer was recorded returns `stopped`, with no reply and its recipient-grant outcome;
> and each of `ALREADY_ENDED` and `NO_SUCH_ACTIVATION` writes nothing.

### 7. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0255, ADR-0280, ADR-0170 and ADR-0275 in the
> scopes its header names, and no clause of any other ADR.

> **Normative.** This numbered draft records its replacements on the status line and in
> a dated header note of ADR-0255, ADR-0280, ADR-0170 and ADR-0275, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect
> on this ADR's ratification.

| Earlier decision | Where it goes |
| --- | --- |
| ADR-0255 §11:1's closure over `StepTransition`, in the addition | §2 (`activation_id`) |
| ADR-0280 §3:3's step, for a stopped pass | §4 (the mark read before the rules and after a stage) |
| ADR-0280 §5:2's fixed default, for a stopped pass | §4 (the stop's end entry, no re-raise) |
| ADR-0170 §4:1's reply-less shapes, in the addition | §4 (a stopped resume, `TurnOutcome.stopped`) |
| ADR-0275 §4:1's `ProcessingReason` values, in the addition | §4 (`stopped`) |
| ADR-0275 §5:3's table, in the addition | §4 (`interrupted / stopped`, first) |
| ADR-0275 §5:6's outward exception, for a stopped pass | §4 (`ActivationStoppedError`; a stopped resume's reply-less outcome) |

Not superseded, each read and found to stand: ADR-0261 §4:1's *"This decision adds no
claim condition"* and §1:1's *"no new `AssistantEngine` member"* are stated over that
decision and over a cancellation, which a stop is not (ADR-0295 §4); ADR-0261 §7:3's
*"exactly two"* raisers of `ClaimRefused` stands, the stop raising a class of its own;
ADR-0255 §3's conjuncts, its count of what that decision added, and §4:3's *"nothing
else"* are each stated over that decision; and ADR-0280 §4:2's member set took
`ControllerRule.STOPPED` already, by ADR-0295, which this ADR names and does not widen.

## Consequences

**What becomes clear.** A stop is two writes in one order, and each guarantee of ADR-0295
has one place that keeps it: the store keeps *no effect after the stop*, the mark keeps
*nothing new starts* and the stop's end entry, and the absence of any cancellation keeps
*not cut off* and *nothing orphaned*. The stop itself touches neither the goal nor the
attempt, so a stop followed by "go on" or "make it Sunday" finds them as the work already
under way left them. The answer to a stop
says which of three things was true.

**What it costs.** A stop waits for the stage in flight, a model call included, before the
pass ends, for as long as that stage's own contracts let it run, a stop adding no
deadline of its own. The plan store gains a member, a conjunct and an export field, and
the engine a member, a vocabulary, an error and a `TurnOutcome` field that cross the
wire. The plan store holds
one row per stop the user ever gave, until it is cleared.

**What follows from it.**

1. **The plan store's lane**: `record_stop`, the conjunct, `ClaimStopped`, the export field,
   with the `PlanStore` conformance suite and canonical fake.
2. **The orchestration lane**: the in-process holding of running activations, the mark,
   the threaded `activation_id`, the controller's and the resume's reading of the mark,
   the classification, the adapter's silence, `stop_activation` and
   its wire route, with the engine conformance suite and canonical fake.
3. **The interfaces lane**: `assistant stop`, and the gateway's stop control beside
   "working…", built on the current state's id.

**What stays open.**

- **Interrupting a model call in flight on a stop**, which would make a stop faster at the
  cost of deciding, per stage, what a cancelled call leaves; nothing here forbids a later
  decision taking it.
- **How long to wait for an effect already sent** that has no deadline of its own, which
  ADR-0295 left open and this ADR does not decide: a stop adds no bound, and the
  effect's own deadlines govern.

**Out of scope.** Takeover and stopping by words are the concurrency milestone's (ADR-0295
§5); how a device finds an activation not started from a conversation is the device
session's (ADR-0295, out of scope).

## Alternatives considered

- **Read the mark inside the turn loop and the walk**, before each round and each step.
  Declined: the loop's further round is admitted *"if and only if **all**"* of ADR-0251
  §4:1's conditions hold and its stop vocabulary is closed (ADR-0228 §9, as ADR-0251 left
  it), so the check would reopen both for a gain bounded by the turn's planning budget, and
  a walk's next step is already refused at its claim.
- **Fence the attempt instead of the activation**, by a new `AttemptState` or by pausing
  it. Declined: ending an attempt while its goal stays open is the act ADR-0261 §1:4
  forbids, pausing borrows a state that means *waiting on the user's answer*, and an
  attempt spans activations, so the fence would bind a later "go on" the stop never named.
- **Fence the execution.** Declined for the same last reason: an execution parked in one
  activation is resumed in another, and a stop names one activation.
- **Keep the stop in process only**, the walk checking the mark before each claim.
  Declined: that is a read-then-claim, and a claim already past its check when the stop
  arrives would land after the stop, which ADR-0295 §2:2 forbids by placing the decision
  in the store.
- **Raise `ClaimRefused` for a stopped claim.** Declined: ADR-0261 §7:3 fixes that class to
  two raisers and makes catching it mean the goal's state can be read and reported, and a
  stop moves no goal state; it would take a supersession of §7 to say less.
- **Write the record before the mark.** Declined: a claim could then be refused by a stop
  whose pass ended on a rule, writing *couldn't finish* about a refusal the user caused
  (§3).
- **Cancel the pass's task, as `interrupted` does.** Declined: a cancellation reaching a
  call in flight yields `INDETERMINATE` (ADR-0029 §4), which is the cut-off ADR-0295 §2:3
  forbids, and every stage would have to be shown to release what it holds (ADR-0060).
- **Require `activation_id` on every claim**, as `attempt_id` is required. Declined: the
  one activation that has no id cannot be stopped, so requiring it buys no refusal and
  costs that activation every action it would take.
- **Leave the stop record out of the export.** Declined: it would take a scope on ADR-0004
  §6's view and export limbs, as ADR-0268's closure record did, for a datum that costs one
  field to carry.
