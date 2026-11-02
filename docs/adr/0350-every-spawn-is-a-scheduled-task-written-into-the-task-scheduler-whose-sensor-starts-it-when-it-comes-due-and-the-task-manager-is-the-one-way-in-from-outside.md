# 350. Every spawn is a scheduled task written into the Task Scheduler, whose sensor starts it when it comes due, and the Task Manager is the one way in from outside

- Status: Partially superseded by ADR-0340 (§3:6, §4:1 and §12:1, each in the addition alone: a rule as a when; §11:1, in the addition alone: a rule on any task the person set; §6:2, §4:5 and §5:2, each in the addition alone: a rule's input facts, its refusals, and a local time stated with no offset; §7:5 and §7:7, for a task with a rule: its next occurrence is written when the one before it is first pushed, not when that one ends, and none after its end; §12:3, in the addition alone: the members ADR-0340 §9:3 changes) and ADR-0349 (§4:1's capability set and §10:4, each in the addition alone: planning is also offered the Task Manager's stop) and ADR-0351 (§6:3, in the origins; §6:11, in *an input whose origin is `assistant`*; §6:12, in *by its origin*; §12:7 whole) and ADR-0352 (§9:6 whole; §7:5's refusal below a cascade record; §8:1's lineage check below a stop; §10:2's *with §9:6's cascade*; §9:3, in the addition alone; §12:3's cascade members and records; §13:3's cascade cases) and ADR-0356 (§3:4, in what is offered alone: spawn is offered on every round, and a spawn §3:4 does not admit comes back refused; §6:7's message place label and *as ADR-0307 §3:8 keeps the text*: a message call names where it goes) and ADR-0357 (§9:3's instruction lines, in where they are said alone: the descriptions of `spawn`, `cancel_task` and `list_tasks`) and ADR-0361 (§5:11, §6:7 and §6:8, each in the addition alone: an approval's activation's place list and messages, and a taken input's place) and ADR-0362 (§3:3, §3:4, §3:7 and §4:4, each in the addition alone: a spawn's write may spend a ticket, a ticket's call runs in the work holding its input, and under a ticket the input's authority is read as carried) and ADR-0364 (§5:6's *only places on its own activation's place list*, outside a work that keeps a list; §5:10, whole; §5:11, outside an activation the Task Scheduler started; §5:12; §5:13, in that an `L` label names any connection)
- Date: 2026-10-25
- Scope: how one activation sets up another, to start now, at an instant, on a rule or on a hub event; the **Task Scheduler**, the built-in channel every such spawn is written into (§2), the spawn and what a scheduled task holds (§3), the three capabilities planning is offered (§4), when a task falls due, the places it suggests and the place list planning names them from (§5), the activation it starts (§6), its sensor (§7), a restart and a miss (§8), finding, replacing, cancelling and stopping scheduled work, with its limits (§9), and the **Task Manager**, the one way in from outside (§10). It is Part B (§§6–11) of proposal [#3384](https://github.com/leonapivato/ai-assistant/pull/3384), read at `86152e7a8`, with the B rows of its tables. Reminders are scheduled tasks (§11), and their own rules stay for the reminders decision. Part A, the operations between activations, is a separate decision, and this one stands on ADR-0332 as it is. §14 names what is not decided here.
- Dependency: [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md), [ADR-0295](0295-stopping-an-activation-is-a-command-that-starts-nothing-new-and-cuts-off-nothing-already-sent.md), [ADR-0297](0297-a-stop-is-marked-on-the-activation-and-recorded-where-claims-are-decided.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md) and [ADR-0341](0341-a-pure-read-is-a-call-that-writes-nothing-and-does-not-leave-the-hub-so-looking-something-up-in-the-assistants-own-records-does-not-commit-an-activation.md), as their status lines leave them.
- Authorization: the owner ruled every part in the design walk of 2026-10-21 to 2026-10-24, recorded in proposal #3384's §§6–11. On 2026-10-24 the owner asked "Should we make this an adr and implement it first before moving to modes?", and on the coordinator's recommendation, to convert both parts and implement this one first, said "Yes to the milestone, number it correctly". The dispatcher assigned 0350. The owner reviewed it on 2026-10-25 and directed: "send it to the line for another review, and then If there's nothing from the review that seems like it changed anything serious and doesn't need my review, feel free to ratify it yourself and continue implementing." The coordinator ratifies it after that review, and brings it back to the owner where that review changes something serious.
- Milestone: [15, Task Scheduler: reminders and work that runs later](https://github.com/leonapivato/ai-assistant/milestone/15); acceptance [#3416](https://github.com/leonapivato/ai-assistant/issues/3416).
- **Changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `PlanStore` gains the scheduled-task members and `PlanExport` the tasks (§12:3). `core/types.py` gains the scheduled task, its occurrence and their enumerations (§12:1), `LabelKind` gains two members (§12:2), and `InputOrigin` gains `assistant` (§12:7), and `PlanningRound` gains its message's place (§12:8). `NewMessage` and `ConversationStore` gain the claim an assistant's message was written under (§12:9). `core`'s register of channel types gains the Task Scheduler (§2:7), and `Settings` gains six fields (§12:5). `AssistantEngine` gains no member (§10:6). `PROTOCOL_VERSION` advances in TS1 (§12:6).
- **Partially supersedes**, in the clauses §15's first table names: ADR-0284, ADR-0292, ADR-0293, ADR-0295, ADR-0297, ADR-0303, ADR-0306, ADR-0307, ADR-0323, ADR-0328, ADR-0329 and ADR-0338.
- Partially superseded: 2026-10-25 by ADR-0340 — §3:6, §4:1 and §12:1, each in the addition alone: a scheduled task's when may be a rule, with more than one occurrence over its life, which a spawn states with an optional zone name (ADR-0340 §4, §8:1, §9:1). §11:1, in the addition alone: a rule may be the when of any task whose author is the person, not of a reminder alone, and of no task the assistant set (ADR-0340 §4:1). §6:2, in the addition alone: the input of a task with a rule also states its rule in words and how many occurrences it skipped (ADR-0340 §7:1). §4:5, in the addition alone: a spawn is also refused on ADR-0340 §3:5's and §4's grounds. §5:2, in the addition alone: a spawn may state a local date and time with no offset, read in the zone it names or in the person's zone (ADR-0340 §3:2). §7:5 and §7:7, for a task with a rule: its next occurrence is written in the step that first marks the occurrence before it pushed, not when that one ends, and none is computed after its until or after its pending occurrence ends cancelled (ADR-0340 §4:6–§4:7). §12:3, in the addition alone: the plan store's members ADR-0340 §9:3 changes. Every other clause stands. This replacement takes effect on ratification of ADR-0340. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0349 — §4:1's capability set and §10:4, each in the addition alone: planning is also offered the Task Manager's stop (§10:2), as a stop call of its own, where its activation's input carries the user's authority. It names one activation shown it as running for the same person, is checked by rule as every call is, and runs as the Task Manager's stop with §9:6's cascade and one implementation (ADR-0349 §4:6–§4:12). Every other clause stands. This replacement takes effect on ratification of ADR-0349. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0351 — §6:3, in the origins: a scheduled task's input carries the assistant's statement as its party, and unknown beside it where the task carries the outside-content mark (ADR-0351 §3:6). §6:11, in *an input whose origin is `assistant`*: no support points at a part whose parties include the assistant's statement, a marked task's input included (ADR-0351 §7:3). §6:12, in *by its origin*: a reader attributes an input by its parties, with understanding's relay mark, and one whose parties are the assistant's statement and that is not relayed as written by the assistant (ADR-0351 §5:4, §5:7). §12:7, whole: `InputOrigin` and its `assistant` member retire (ADR-0351 §8:1). Every other clause stands. This replacement takes effect on ratification of ADR-0351. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-26 by ADR-0352 — §9:6, whole: a stop command stops only the activation it names, writes no cascade record and walks nothing, and what the activation set up stays until a cancel or a stop names it (ADR-0352 §2:1–§2:4). §7:5's refusal below a cascade record, whole: the push step refuses only an occurrence no longer pending or a task no longer held (ADR-0352 §2:3). §8:1's *anything below it that is still pending is kept from running by §7:5's lineage check*: what is below a stop is settled and pushed as anything else is (ADR-0352 §2:4). §10:2's *with §9:6's cascade*. §9:3, in the addition alone: planning's instruction also says that a stop or a cancel reaches only what the person's words cover, keeping the rest and asking where it is unclear (ADR-0352 §3:8). §12:3's members that write a cascade record and refuse a push below one, and `PlanExport`'s cascade records, which an upgrade retires after cancelling what they would have refused and writing a stop record for each activation pushed below them (ADR-0352 §2:6, §6:1–§6:4). §13:3's cases of a crash after a cascade record, a stop whose walk cancels a grandchild, a chain stopped while its next task is pushed, and a takeover's stop writing no cascade record. §3:3, the spawn's refusal on the stop record, stands unchanged. Every other clause stands. This replacement takes effect on ratification of ADR-0352. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §3:4, in what is offered alone: spawn is offered on every round, and a spawn from an activation §3:4 does not admit comes back refused, saying why, and runs nothing (ADR-0356 §4:3–§4:5). §6:7's *each of its messages names, by its place label, the one place on the list it goes into* and *as ADR-0307 §3:8 keeps the text*: a round's text is no message, and a message call names where it goes, as the tools decision decides, under the same list and the same check (ADR-0356 §7:3). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0357 — §9:3's *Planning's instruction says four things*, in where they are said alone: the descriptions of `spawn`, `cancel_task` and `list_tasks` say them, each the part about it (ADR-0357 §7:1–§7:3). What they say is unchanged by ADR-0357. Every other clause stands as its other records leave it, §6:7 included. This replacement takes effect on ratification of ADR-0357. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §5:11, in the addition alone: an approval's activation's place list holds the asking work's places, marked suggested, and any activation's list holds the place an input it took by a take came from, where that place takes a message (ADR-0361 §6:7, §7:3). §6:7, in the addition alone: an approval's activation writes messages into places on its list alone, as a task's activation does. §6:8's *planning in every other activation still chooses no place*, in the addition alone: such an activation may also name a taken input's place. Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-11-01 by [ADR-0362](0362-a-ticket-runs-the-person-models-calls-and-the-task-schedulers-and-a-cards-edit-and-a-taps-answer-need-no-claim-of-the-lines.md) — §3:3, in the addition alone: the actuator's write may take an effect record claimed under a ticket, deciding and spending the ticket in the same step, every other check of that step unchanged (ADR-0362 §3:1–§3:2). §3:4, in the addition alone: a ticket's spawn, cancel or list call runs in the work holding the ticket's input, the approval's own activation included (ADR-0362 §3:4). §3:7 and §4:4, in the addition alone: for a call run under a ticket, the spawning activation's input is read as carrying the person's authority, for that call alone, so the task's author is the person and it may replace or cancel any of the person's tasks (ADR-0362 §3:5). Every other clause stands. This replacement takes effect on ratification of ADR-0362. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-11-01 by [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md) — §5:6's *only places on its own activation's place list*, outside a task's work and an approval's, which still suggest only from their lists: a spawn may suggest any connection the work was shown that takes a text message (ADR-0364 §11:3). §5:10, whole: the Connections section replaces the place list, for every work (ADR-0364 §3:1). §5:11, outside an activation the Task Scheduler started: a work may send a text into any connection it was shown that takes one (ADR-0364 §9:3); §6:7's list stands for a task's work (ADR-0364 §9:4). §5:12: each entry says what the system can do with it (ADR-0364 §3:3). §5:13, in that an `L` label names any connection; its refusal of a label not shown stands. Every other clause stands. This replacement takes effect on ratification of ADR-0364. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The question.** Activations run side by side. How does one start another, now or later,
and how is that work found, replaced, cancelled and stopped? The owner's walk answered with
one place every spawn goes through, the Task Scheduler, and one way in from outside, the
Task Manager. The walk's principles, in the owner's words:

- *"Things like the reminder or background task are just normal activations that might have
  spawned from a certain conversation, but they don't live there."*
- *"I like how a spawn is just an actuator action in the place, which gets sensed by the
  sensor and starts an activation, it's its own loop."*
- *"For now, do a simple design that works. Don't worry much about who and what and
  privacy. That stuff will be addressed later."*

**What is already ratified.**

- ADR-0292 §1's lead: "The hub runs things that are not the assistant: the clock, and any
  medium it hosts, such as the conversations." §1:1 reaches the assistant only through
  sensors and actuators on channels, and §1:3 has the user operate on the assistant by
  command or query, which the assistant does not perceive.
- ADR-0292 §5:6: "A reminder the user set informs the activation it starts and authorizes
  nothing". §6:2 counts "a reminder coming due" as a push. §6:8: "The assistant's own
  writing never starts an activation." §11:7 keeps whether an activation is running out of
  the medium. §12:1 lists *setting a timer* among the inside actions that run "directly,
  with no channel and no actuator".
- ADR-0306 §4:7 holds the round's message to "the place the input came from", and ADR-0307
  §3:1, §3:7 and §3:8 and ADR-0323 §6:1 follow it. ADR-0329 §13:6 has no background work
  message the user "until a decision on proactivity says otherwise". ADR-0293 §10:4 already
  permits, on the hub chat, "writing from an activation not started from one".
- ADR-0332 §2:3 lets a kind declare whether its places run one activation at a time. Its
  §3:3 joins only on such a place, and its §4:6 takes over only an activation whose input
  carries the same authority. Its §9 leaves background work to "the timers and proactivity
  milestone".
- ADR-0292 §7:4: "What counts as *sent* is the kind's. For the conversation, a message is
  sent once the medium has recorded it". ADR-0323 §10 gives the line an episode window
  because a bot cannot read its chat's history.
- ADR-0295 makes a stop a command naming one activation, and ADR-0297 decides it in the plan
  store with every claim. ADR-0286 §6:4 keeps an open episode from every model input.
- ADR-0083 §7's scheduler is the hub's housekeeping loop, which accepts that "a missed or
  late tick is never a correctness bug".

**What the tree holds,** on `origin/main` at `82d03b61b`:

- No Task Scheduler, scheduled task or clock channel exists. `core`'s register
  (`_INPUT_ORIGINS` in `core/channel_validation.py`) knows `conversation`,
  `informational_event` and `telegram`, and `_ONE_AT_A_TIME` in
  `orchestration/channel_kinds.py` names `conversation` and `telegram`.
- `PlanStore` holds stop records, activation effects and observations. `PlanExport` crosses
  no wire, as `wire/envelope.py` records at each of its version moves.
- `LabelKind` in `core/types.py` has the prefixes S, E, N, M, R and A (`_LABEL_PREFIXES`).
- `AssistantEngine.stop_activation` stops one activation through the engine's `_stop`. The
  gateway's stop route and the CLI call it, and the line's `/stop` reaches the same `_stop`
  through the engine's `_stop_line`.
- Planning's episode window skips every open episode (`_Request._episodes` in
  `orchestration/planning.py`: `if processing is not None and processing.is_open:
  continue`).
- A message the assistant writes into a conversation (`NewMessage`, through
  `ConversationStore.append_message`) records nothing of the effect record that claimed it,
  so nothing reads a claim's message back from the transcript.

**A draft beside it.** ADR-0340 (#3271, `Proposed`, unmerged) built reminders on a clock
channel of their own, with their record in the plan store. The walk replaced its channel
with the Task Scheduler, and its rewrite follows this decision (§11). Nothing here records
against it.

**Why it needs a decision.** The Task Scheduler is a medium reached through a sensor and an
actuator, which ADR-0292 §12:1 rules out for setting a timer. A task the assistant set
starting an activation is what §6:8 forbids. An activation it starts must speak into a
place its input did not come from, which ADR-0306 §4:7 forbids. Each is a ratified clause,
and changing what it requires is a supersession (ADR-0070). The plan store is a `Protocol`
in `core`.

## Decision

We will make every spawn a call that writes a scheduled task into the Task Scheduler, a
built-in channel whose sensor starts an ordinary activation when the task falls due. A task
carries no authority, suggests zero or more places, and points to the
activation that spawned it and the tasks it waits for. Its activation speaks only into a
place on its place list, where the suggestions are marked. Once nothing about it is left,
the task is removed, and what ran stays in the episodes. The sensor compares wall-clock
instants, pushes each due task on its own, and after a restart never runs a step again once
it has spawned its next. The Task Manager is the one way in from outside, and planning uses
the same operations.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the coordinator
> ratifies it, as the owner directed on 2026-10-25 (the header's authorization). An assigned
> number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is the lanes §13 sets out, each held by milestone 15,
> and no lane is dispatched before this decision merges.

### 2. The Task Scheduler

> **Normative.** The **Task Scheduler** is a built-in channel (ADR-0292 §2:5–§2:6) with
> exactly one place, **the schedule**.

> **Normative.** It is a medium the hub hosts, in ADR-0292 §1's sense: something the hub
> runs that is not the assistant. The assistant reaches it only through its sensor and its
> actuator.

> **Normative.** ADR-0292 §3's clauses on a hosted medium bind it. Its content is held in the
> hub apart from the assistant's memory, recall does not search it, consolidation and the
> observer do not read it, and it is the user's data under ADR-0292 §3:11.

> **Normative.** It is fully private for now. Its kind takes no spoke on any device, no
> device is an end of its place, and a person reaches it only through the Task Manager
> (§10).

> **Normative.** It holds only **scheduled tasks**: each an activation waiting to be
> started, with what settling and stopping it needs, or one whose work has ended but that
> is kept while anything below it is live, until §7:8 removes it. What ran is kept
> in episodes (§7:9), never in it. Whether an activation is running is never written into
> it: that is the assistant's current state (ADR-0292 §11:7), read live from the engine.

> **Normative.** Its kind is declared in code, as the line's is (`orchestration/channel_kinds.py`).
> It declares that its place runs activations side by side and not one at a time (ADR-0332
> §2:3), that it takes no message from a person or from the assistant, that it shows no
> running work, that it expects no reply, that it pushes and can be pulled (ADR-0292
> §6:5), and that its place's window is a task's lineage (§6:5).

> **Normative.** `core`'s register of channel types (`core/channel_validation.py`) gains the
> Task Scheduler, which declares its origin per input (§6:3) and establishes no author as
> the user in its place.

> **Normative.** Wherever the hub names them, in decisions, code, prompts and records, the
> channel is named the **Task Scheduler** in full, its items **scheduled tasks**, and
> Python's own kind an *asyncio task*. "The scheduler" stays the name of ADR-0083 §7's
> housekeeping loop, which this decision leaves unchanged.

The owner chose these names over *the agenda* and *the activation scheduler*. Shown to
people, the Task Manager's view would be called **Tasks** (§10).

### 3. Spawning, and what a scheduled task holds

> **Normative.** A **spawn** is a call to a capability (§4:1): planning calls it,
> authorizing checks it by rule as every call is (ADR-0306 §4:1), and acting writes the
> scheduled task through the Task Scheduler's actuator.

> **Normative.** Every spawn goes through the Task Scheduler, a spawn to start now included.
> No activation starts another by any other path.

> **Normative.** The actuator's write is one plan-store step that writes the task and claims
> the spawn's effect record together (ADR-0306 §5:4). The store refuses it, writing nothing,
> where it holds a stop record for the spawning activation (ADR-0295 §2:2, ADR-0297).

> **Normative.** Spawn is offered only to an activation that is a person's (ADR-0338 §2:2)
> and was started from a conversation, from the line or by the Task Scheduler.

> **Normative.** A scheduled task is for the person the spawning activation is for, and for
> no one else.

> **Normative.** A scheduled task holds:
> - its id;
> - for whom (§3:5);
> - its author (§3:7);
> - when (§5:1);
> - the places its spawner suggests, zero or more (§5:5);
> - what it carries: the creator's instruction, bounded in size;
> - its **parent**, the activation that spawned it;
> - the tasks it waits for, where its when is §5:4's;
> - where it was set: the place of the spawning activation's input;
> - its marks (§3:8);
> - its chain length (§9:7);
> - its occurrences, each with its state and outcome (§7:5–§7:6), until §7:8 removes it.

> **Normative.** A task's author is the person, established as the spawning activation's
> input's author was, where that input carries the person's authority (ADR-0292 §5:5), and
> the assistant otherwise. Either is written when the task is set (ADR-0292 §5's table).

> **Normative.** A task spawned by an activation that has read outside content (ADR-0306
> §4:5) carries the outside-content mark.

> **Normative.** A scheduled task carries no authority, whoever set it. It informs the
> activation it starts and authorizes nothing, as ADR-0292 §5:6 already rules of a reminder.
> No approval given in the spawning activation carries over (ADR-0321 §4:1).

> **Normative.** Where a task was set is data the task carries and its activation's input
> states (§6:2). It puts no place on any place list (§5:11), and no rule reads it for whom
> the task is for.

So a person's "remind me…" in the hub chat is the person's task, and the assistant's own
follow-up ("I'll check back tomorrow"), and every step a chain spawns, is the assistant's.
Neither can authorize anything when it comes due. An approval is used only by the activation
of the yes that gave it, so a spawned step that needs one asks again.

**What spawning is for.** It is the rarer case. Most activations call tools, speak and end.
A spawn covers continuing work too long for one activation, breaking work into independent
pieces, isolating work in a separate context, reminders and schedules, and the assistant's
own follow-ups: a retry, a check back, a nudge. These vary only in when (§5:1) and in the
places they suggest (§5:5). "Background task" is dropped as a concept: an activation spawning its own next step
covers it.

### 4. The capabilities

> **Normative.** Planning is offered three capabilities, each declared under ADR-0306 §2 with
> the effect *the assistant's own records*, never leaving the hub, and never with an unknown
> outcome:
>
> | Capability | What it does | Safe to repeat | `writes` | Result |
> | --- | --- | --- | --- | --- |
> | spawn | writes a scheduled task: what it carries, when (§5:1), the places it suggests by label, zero or more (§5:5), and, where it names one, the task it replaces (§9:4) | No | the person's tier | no outside text |
> | cancel a scheduled task | ends what of it is pending (§9:5) | Yes | the person's tier | no outside text |
> | list scheduled tasks | the list pull (§4:6) | Yes | none | no outside text |
>
> Exact names and arguments are the lane's that builds them (§13), within this table.

> **Normative.** The effect value *the assistant's own records* is read by ADR-0306's and
> ADR-0341's rules alone: for claims, effect records, routing and the pure read. It makes no
> part of the Task Scheduler's content the assistant's memory, and §2:3 stands.

> **Normative.** Acting runs each of the three directly against the plan store, as
> ADR-0306 §3:3 runs a call to the assistant's own records, awaited to its end, and never through
> `ToolInvoker`. For spawn and cancel, that direct write is the Task Scheduler's
> actuator.

So spawn and cancel each write, and so commit their activation (ADR-0332 §3:2,
ADR-0341 §2:1). The list pull writes nothing and does not leave the hub, so it is a pure
read (ADR-0341 §2:1), and planning may look before it acts. A spawn is not safe to repeat, so it
gets an effect record (ADR-0306 §5:3), and the backstop refuses the same spawn twice in one
matter unless planning marks it deliberate (ADR-0306 §5:9). A spawn that replaces a task
is still a spawn, with its effect record and the backstop: there is no change capability,
and "make it 9" is a replace (§9:4).

> **Normative.** Cancel, and a spawn naming a task it replaces, are offered to an activation
> whose input carries the person's authority. Any other activation's cancel, or spawn
> naming a task to replace, that names a task it did not spawn is refused as *not done*,
> with the reason, and writes nothing.

> **Normative.** A spawn is refused as *not done*, with the reason, and writes nothing,
> where its instant is earlier than now, where it waits on a task §5:4 does not allow, where
> it suggests a place §5:6 does not allow or names a label §5:13 refuses, where it names a
> task to replace that §9:4 does not allow, or where §9:7 or §9:8 refuses it.

> **Normative.** The **list pull** answers, for the person the asking activation is for: the
> activations running for that person, other than the asker, live from the engine, each
> shown as ADR-0332 §4:1 shows one to understanding and under ADR-0332 §4:2–§4:3's limits;
> that person's pending scheduled tasks, each with a short description of its parent the
> hub writes from the record, such as "spawned by Tuesday's step" or "spawned by your
> message on Monday", so planning can tell which belong together; and the activations the Task Scheduler started for
> them that ended most recently, read from the episodes of the schedule (§7:9).
> Each part is bounded by §12:5's listing bound, and each item carries its label (§9:2).

> **Normative.** In the list pull's result, a running activation whose input's origin is
> `outside`, and a task carrying the outside-content mark, are shown with their text
> withheld and their mark shown. That is how the result carries no outside text.

> **Normative.** A spawn's result carries the new task's label and the hub's own rendering of
> when it falls due and of the places it suggests, written from the stored record.

### 5. When, and the places it suggests

> **Normative.** A task's **when** is one of: **now**; **an instant**; **a rule**; or **a hub
> event** (§5:4). A spawn may state an instant as a delay from now, resolved to an instant
> when it is set. A condition in the world ("when I get home") is not a when under this
> decision: it waits for watches ([#2585](https://github.com/leonapivato/ai-assistant/issues/2585)).

> **Normative.** An instant is stored in UTC and compared as one. A spawn states it with its
> UTC offset or as a delay. How a local time stated without an offset is read in a person's
> zone is the reminders decision's (§11).

> **Normative.** A **rule** is a description, validated whole by the hub when the task is
> written, from which code alone computes each next occurrence's instant. Its vocabulary, its
> zone semantics, its end and what changing one occurrence means are a later decision's.
> Until that decision lands, no capability offers a rule and no task holds one.

> **Normative.** A **hub event** is one of a closed list of events the hub notices as each
> happens, never by polling, and only a later decision adds to the list. Its one member is
> **named tasks ending**: a task timed on it falls due at the instant the last of the tasks
> it names ends, however each ends (§7:6), and at once where all of them have ended when it
> is written. It may name only one-off tasks for the same person that exist when it is
> written, and what it waits for never changes.

"Your next message" is not a hub event, by the owner's choice. So no task waits on itself,
and no two wait on each other. "Compare these three apartments" is three tasks spawned now
and, in a later round that has their labels, a fourth timed after all three, which reads
their episodes (§6:5). The three stay in the Task Scheduler while the activation that
spawned them runs (§7:8), so that later round can name them however soon they finish.

> **Normative.** A scheduled task carries **zero or more places its spawner suggests**, each
> by its place label (§5:13). No place is suggested by default, except as §5:6 carries a
> step's places forward. A suggestion constrains nothing: where the task's activation may
> speak is its place list (§6:7), on which the suggested places are marked.

> **Normative.** Until a decision on which places a spawner may suggest lands, a spawner may
> suggest only places on its own activation's place list (§5:11). A spawn from an
> activation the Task Scheduler started that states no places carries its own task's
> suggested places forward, since it is the same work continuing, as a replace inherits
> them (§9:4). One that states places suggests those.

> **Normative.** A task's activation whose place list is empty may work, write records and
> spawn, and writes no message (§6:7).

> **Normative.** A place list is built when it is shown, at the activation's start and at
> every planning round. A stored suggestion naming a place that is gone is filtered out of
> the list, and never rewritten. A conversation is gone once deleted. The line's chat is
> gone once the line is disconnected, or once the settings name another chat.

> **Normative.** Nothing is cancelled because a place is gone. Deleting a conversation or
> disconnecting the line cancels no task and rewrites no suggestion, and an occurrence whose
> suggested places are all gone is still pushed. A message naming a place no longer on its
> activation's list is refused, as §6:7 refuses any place off the list.

Some activations need no place and some need several: "remind me here and on Telegram"
suggests two. A suggestion is the spawner's word on where the matter belongs, and the
activation that runs later, which knows more, decides among its place list. A place holds no
activation: it is only where a message may go. In practice the line is the fallback: a
task whose conversation was deleted still speaks on the line where it is connected, and
with no line and no place left it writes nothing (§5:7). The owner chose this: "just not
deleting anything when a conversation is deleted… keep it kind of general". Deleting a
conversation forgets nothing (ADR-0292 §3:10).

> **Normative.** Planning in an activation offered spawn (§3:4) is shown its activation's
> **place list**: places grouped under channel headings. A heading names its channel for
> reading and is never named by a label, and each place under it carries a place label
> (§5:13). A channel appears only where at least one place under it is on the list.

> **Normative.** An activation's place list holds the line's chat, where the line is
> connected, and: for an activation the Task Scheduler started, its task's suggested places,
> marked as suggested; for every other activation, the conversation its input came from, if
> any. Where a task was set puts no place on it (§3:10). For an activation the Task
> Scheduler did not start, the list is what its spawns may name and nothing more: it still
> replies where its input came from (§6:8).

> **Normative.** Each place carries a short description of what it is. What a place
> can do, such as whether it notifies, how it formats and who sees it, is a later decision's
> ([#3250](https://github.com/leonapivato/ai-assistant/issues/3250)).

> **Normative.** Places are named by a planning label of a new kind, `L1`, `L2`… (ADR-0307
> §5:1), and only a place carries one: a channel heading is never named. A spawn naming a
> label that planning was not shown on a place in its place list is refused whole, with the
> reason (ADR-0307 §5:3).

The place list is the naming boundary: what it shows is all a spawn can name. A pull of
the person's other places returns with the decision on speaking as a call in every place.
For an activation the Task Scheduler started, its place list (§6:7) is also the speaking
boundary.
The prefix `L` collides with no label kind planning has (`S`, `E`, `N`, `M`, `R`, `A`, and
§9:2's `T`), with none understanding or the observer adds to those (`H`, `P`, `Q`, `C`), and
with none ADR-0349's draft on #3384 adds: it labels in-progress entries with `R` for
understanding and with episode labels for planning. Preferences about places, such as
"wants reminders on Telegram", reach planning as the person model's style memories do today
(ADR-0338), and this decision adds nothing for them.

### 6. The activation a scheduled task starts

> **Normative.** An occurrence falling due is a push on the schedule (ADR-0292 §6:2), and it
> starts one activation, whoever set the task, the assistant included.

> **Normative.** Its input's author is the task's author, stated by the hub from the record
> (ADR-0292 §5:1), and it carries no authority (§3:9). The input holds what the task carries,
> when and where the task was set, the instant the occurrence was due, whether it is late
> (§8:9) or a second try (§8:6), and the links to the episodes §6:5 names.

> **Normative.** Its origin is `outside` where its task carries the outside-content mark, and
> `assistant` otherwise, a value `InputOrigin` gains (§12:7). Its text is the creator's
> instruction as planning wrote it, never the person's own words, so it never takes `user`
> (ADR-0284 §2:2), whoever set the task.

> **Normative.** The activation is for the person its task is for.

> **Normative.** The schedule's place window, which its kind declares (ADR-0292 §10:2), is
> the lineage of the activation's task, read from the tasks the Task Scheduler keeps (§7:8)
> and shown as steps numbered from the start: a *start* line, giving the activation that
> began the lineage, which is not a task, by its place, its local time and its input in
> brief, with its episode's link; then each ancestor step in order, giving when it ran, in
> local time, its outcome and its instruction in one line; then the current activation,
> marked as current. It is bounded by the chain limit (§9:7). The input links to its task's parent's episode and to the
> episode of each task its task waited for. Each linked episode is shown only where frozen,
> rendered through the episode window's projection (ADR-0276 §4:6) under its disclosure
> predicate (ADR-0276 §4:9), labelled, and linked to the activation it records, as the
> episodes recall finds are shown.

> **Normative.** Those linked episodes are pointers the task carries (§3:6), not anything
> the schedule attests. A task's parent and the tasks it waits for are read only as those
> finished episodes. No running activation's state is read through them, and nothing is
> pushed back along them.

A place window is what the place itself attests. The schedule attests its kept tasks, so
its window is the lineage they record, and the task an activation runs is its input. The
lineage is never longer than the chain limit (§9:7). An episode still open is never linked, as no open episode reaches a model (ADR-0286 §6:4),
and planning's episode window skips them today. "Remind me at 8 to call Mom about it"
reaches its activation with its parent's episode linked from its input, which says what
"it" was.

> **Normative.** An activation the Task Scheduler starts may write messages into any place on
> its **place list** (§5:11), and into none off it. Until the decision on speaking as a call
> in every place widens it, that list holds the line's chat, where the line is connected,
> and each place its task suggests that is not gone, marked as suggested. Where its task was
> set puts no place on it (§3:10). Each of its messages names, by its place label, the one
> place on the list it goes into, and authorizing's message-place check (ADR-0306 §4:1)
> refuses a message that names none or one off the list, a place gone since the list was
> built included (§5:8). With an empty list it writes none,
> as ADR-0307 §3:8 keeps the text of an input whose place takes no message. ADR-0306 §4:7,
> ADR-0307 §3:1 and §3:8 and ADR-0323 §6:1 read, for that activation, the places on its
> place list in place of the place its input came from, and ADR-0307 §3:7's *couldn't
> finish* goes into each suggested place on the list, or nowhere where its task suggests
> none.

> **Normative.** §6:7's list holds until the decision on speaking as a call in every place
> widens it, and the rule that such an activation writes into no place off its list stays.
> Milestone 15 is not the milestone that ends ADR-0306's interim on ADR-0292 §7:2: planning
> in every other activation still chooses no place, and in an activation the Task Scheduler
> starts it chooses only among its place list.

> **Normative.** An activation the Task Scheduler starts is not one any conversation caused.
> A conversation's current state, its "working…", its stop control and its admission cover
> the activations that conversation caused (ADR-0332 §2:3, ADR-0295 §1:2), and so none of
> them includes it, even where it writes into that conversation. The line shows no typing
> for it (ADR-0323 §6:8).

> **Normative.** Beyond §6:7, it is an ordinary activation. It is offered the capabilities
> any activation is offered, and every call it makes is checked by rule as every call is
> (ADR-0306 §4).

So a person typing in a conversation while a reminder speaks there gets an activation of
their own beside it. The two never join and are never taken over. The schedule runs side by
side (§2:6), so ADR-0332 §3:3 joins nothing there. Two of the Task Scheduler's activations
share one place, so neither is shown to the other under ADR-0332 §4:1. A person's
activation and a task's never carry the same authority, so ADR-0332 §4:6 takes over neither.

> **Normative.** No support points at an input whose origin is `assistant`, and the code that
> sets a support's origin and holder (ADR-0328 §4:2, ADR-0345 §2:1) refuses one that does.
> ADR-0328 §4:2's origin table gains no row for it, and a
> support of such an activation points at another part of its episode, such as a round's
> message, which ADR-0328 §4:2 and ADR-0345 §2 already rule.

> **Normative.** Every reader that attributes an input by its origin (ADR-0284 §2:3) attributes
> one whose origin is `assistant` as written by the assistant, never as something the person
> said.

So a reminder's text, or a chain's next step, is never evidence that the person said it
again, nor a holder ADR-0345 §2 has no kind for. What the task rests on is in its parent's
episode, where the observer already read it. An input whose origin is `assistant` is no
outside trigger (ADR-0306 §4:5): only a task carrying the mark is one, through the origin
`outside`.

### 7. The sensor

> **Normative.** The Task Scheduler's sensor is one loop that the engine starts with the hub
> and stops with it, as it does the line's reader. It is not a row of ADR-0083 §7's
> scheduler.

> **Normative.** It sleeps until the earliest instant an occurrence falls due, for no longer
> than §12:5's recheck interval. Every write to a scheduled task wakes it, so a task due now
> is pushed straight away.

> **Normative.** It compares wall-clock instants in UTC, never elapsed sleep. It pushes every
> pending occurrence due at or before now.

> **Normative.** Each due occurrence is pushed as an input of its own and starts its own
> activation. The sensor groups nothing, and occurrences due together start separately.

> **Normative.** Before an occurrence's activation is admitted, the sensor marks it
> **pushed**, naming the id that activation will be admitted under, in one plan-store step
> that refuses where the occurrence is no longer pending. The same step also refuses, and
> ends the occurrence *cancelled*, where an activation in its task's lineage carries a
> cascade record (§9:6): its task's parent, or the parent of any task above it (§6:5).
> Where it is refused, nothing is pushed. Between a cancel and a push, whichever lands first
> in the store wins.

> **Normative.** When the activation ends, its occurrence takes its outcome from how it
> ended: *done* where its episode froze completed; *couldn't finish* where it froze failed;
> *stopped* where a stop ended it (ADR-0295 §3:1); and *interrupted* for every other
> ending but ADR-0286 §7:2's restart close, which §8 settles.

> **Normative.** An occurrence ending wakes the sensor, so a task waiting on it falls due at
> once (§5:4), and a task with a rule has its next occurrence computed.

> **Normative.** A task is kept in the Task Scheduler while anything of it or below it is
> live: while something of it is pending, while one of its pushed occurrences is not settled
> (§7:6, §8), and while a task below it, spawned by one of its occurrences' activations or
> by theirs in turn, is pending, pushed or running. It is also kept while a task the Task
> Scheduler holds waits on it, and while its parent, the activation that spawned it, is
> still running. Once none of these holds, it is removed. Each task records its chain length when it is written (§9:7), so no count needs
> a task that was removed.

> **Normative.** What ran is kept in episodes, never in the Task Scheduler: each occurrence
> that ran is its activation's episode, indexed by the schedule (ADR-0292 §10:5). An
> occurrence that never ran is recorded where it ended. Planning's cancel is on the episode
> of the activation that made the call, and a skipped occurrence is in the input of the late
> occurrence pushed in its place (§8:10). A cancel by a Task Manager command (§10:2) is
> answered to its caller and leaves no other record.

So every ancestor of live work is kept, which the schedule's window shows (§6:5), and
nothing is left for §8 to settle. §9:6's cascade runs down through live work alone, so it
never needs a removed task. A later round of a task's parent can still name it in a task
that waits on it (§5:4), however soon it finished. Removal is the medium's own retention,
which its kind declares (ADR-0292 §3:5), and no act of the assistant's (ADR-0292 §3:9).

Whether tasks that fall due together should become one is not this decision's. Under
ADR-0332, as §6 shows, they never join: two unrelated reminders due at 8:00 give two
messages, and so does one set twice by mistake.

### 8. After a restart, and missed tasks

> **Normative.** At start, after ADR-0286 §7:2's close and before it pushes anything, the
> sensor settles each occurrence marked pushed whose activation is not running. Where the
> store holds a stop record for that activation (ADR-0297), the occurrence ends *stopped*,
> is never pushed again, and nothing else in §8 applies to it. Anything below it that is
> still pending is kept from running by §7:5's lineage check, so a stop cut off by the
> restart leaves nothing below it to start. Otherwise §8:11 confirms that
> activation's messages first, and §8:2–§8:7 then apply in order, the first that applies
> deciding.

> **Normative.** Where that activation's effect records (ADR-0306 §5:3) hold a spawn, the
> occurrence ends *interrupted* and is never pushed again, so a chain cannot fork.

> **Normative.** Where that activation's episode froze with any ending but ADR-0286 §7:2's
> restart close, the occurrence takes the outcome §7:6 gives.

> **Normative.** Where a message the activation claimed into a place on its place list is
> done (ADR-0306 §5:5), the occurrence ends *done*.

> **Normative.** Where the occurrence was not itself a second try (§8:6), and the activation
> claimed no effect, or only messages each *not done*, the occurrence is pushed again. It is
> pushed at most §12:5's push limit of times in all, and is then ended *interrupted*.

> **Normative.** Where the occurrence was not itself a second try, its pushes are still under
> §12:5's push limit, and the activation claimed only messages and any of them has an
> unknown outcome or none written, the occurrence is pushed once more as a **second try**,
> and the occurrence records that it is one. Its input
> says so. Whether and how its message mentions it is the activation's judgment. It is never tried a third time. After the second try's activation ends,
> the occurrence takes §7:6's outcome. Where a restart cuts that activation off too, §8:4
> may still find it *done*, and §8:7 otherwise ends it *interrupted*. Where the
> occurrence's pushes have reached the push limit, this clause does not apply, and §8:7 ends
> it *interrupted* with no further push.

> **Normative.** Otherwise the occurrence ends *interrupted* and is never pushed again.
> ADR-0306 §5:6 and §5:13 hold for every effect it claimed.

> **Normative.** §8:6 replaces ADR-0306 §5:6's *never resolved by guessing* and §5:13's
> *never retried, done another way* for the message of an activation the Task Scheduler
> starts, and for no other effect. §8:11's confirmation is not a guess: it reads the record
> that decides, for that kind, whether a message was sent (ADR-0292 §7:4). No unknown
> outcome is ever reported as done.

A spawn's effect record outlives the task it wrote, so a step whose next step already ran
and was removed is still found. So a step that has spawned its next is never run again.
Where its place can confirm delivery, as the hub chat can, whether a step spoke is read, not
guessed. A step that may have spoken where its place cannot, as on the line, is said at most
twice, the second time with its input saying so. A step that did nothing runs again, up to the push limit. A
step that acted in the world and was cut off is not repeated.

> **Normative.** An occurrence pushed more than §12:5's lateness grace after the instant it
> was due is **late**, and its input says so with that instant. It is pushed once, however
> late, and no cut-off drops it. Whether and how its message mentions the lateness is the
> activation's judgment.

> **Normative.** A task with a rule that missed more than one occurrence pushes only its
> latest missed occurrence, whose input says how many it skipped, and sets each earlier one
> *skipped*, so it never bursts.

**Confirming delivery.**

> **Normative.** For each message the activation claimed whose outcome is unknown or none
> written, the sensor asks the kind of the place it was claimed into whether it can confirm
> delivery. Where the kind can, it confirms from its medium's own record, and the sensor
> writes what it confirms onto the effect record (ADR-0306 §5:5): *done*, with its position,
> where the medium recorded the message, and *not done* where it did not, through §12:3's
> settling member, since `finish_activation_effect` writes an outcome only once (ADR-0306
> §6:4). Where the kind cannot, or the place is gone (§5:8), the record is left as it was.

> **Normative.** Each kind declares whether it can confirm delivery, in
> `orchestration/channel_kinds.py`'s shape, as it declares whether its places run one
> activation at a time. The hub chat's conversations can: the hub hosts each one's
> transcript, a message is sent once that transcript records it (ADR-0292 §7:4), and the
> transcript records with each of the assistant's messages the effect record it was claimed
> under, deleted or not (§12:9). The line cannot: the Bot API gives a bot no way to read its
> chat's history, and the line's place window is built from the hub's own episodes (ADR-0323
> §10). Every other kind declares that it cannot.

So a message the hub chat confirms ends its occurrence *done* under §8:4, with no second
try, and one it confirms absent leaves an ordinary push again under §8:5. Only a message the
place cannot confirm, as on the line, takes §8:6's marked second try.

### 9. Finding, replacing, cancelling and stopping scheduled work

> **Normative.** A place-window item written by an activation the Task Scheduler started
> links, beside that activation (ADR-0303 §7:1), to its scheduled task while the Task
> Scheduler holds it, through the occurrence's pushed mark. Once the task is removed (§7:8),
> the item links to the activation's episode alone.

> **Normative.** Planning names scheduled tasks by label, under a new kind, `T1`, `T2`…
> (ADR-0307 §5:1). A place-window item that links to a scheduled task is shown with that
> task's label beside its episode label (ADR-0307 §5:6).

> **Normative.** Planning's instruction says four things. A task the place window shows by
> label is replaced or cancelled by one call. Any other task is found by the list pull
> first. "Snooze 10 minutes" or "again tomorrow", after a task's message, is a new spawn,
> written from what the place window shows of the episode that wrote the message. Where the
> words could mean more than one task, planning asks which.

"Snooze 10 minutes", right after a reminder, is one spawn in one round, written from the
episode the window shows beside the reminder. "Make it 9", for a reminder not yet said, is a
spawn replacing its `T` label. "Cancel the bins one" is a pull, then the cancel. "Stop the
apartment search" is the pull, whose parent descriptions show which tasks belong together,
then a cancel of each pending one. A running step is stopped by the Task Manager's stop
(§10:2), whose cascade does the rest (§9:6); stopping it in words is Part A's (§14). A
label planning was never shown is refused, with the reason (ADR-0307 §5:3).

> **Normative.** A spawn may name a pending task it **replaces**. In one plan-store step it
> cancels that task's pending occurrences, as §9:5 does, and writes the new task, which
> takes the replaced task's parent and suggested places in place of its own, and so its
> chain length (§9:7). It passes every check a new spawn passes (§4:5, §5:4, §9:7–§9:9),
> with the pending count taken after the cancel, so a task waiting on named tasks is
> replaced only with a valid wait. Its inherited places are not checked again under §5:6,
> and one that is gone is filtered from lists as §5:8 filters it. Where the named task has nothing
> pending, the spawn is refused as *not done*, with the reason, and writes nothing.
> Changing one occurrence of a rule is the reminders decision's.

> **Normative.** A cancel ends every pending occurrence of a task as *cancelled*. It stops no
> running activation. Where nothing of the task is pending, it is *not done*, with that
> reason, and writes nothing.

> **Normative.** A stop command (ADR-0295 §1) naming a running or pushed activation also
> stops what is still live below it. It first writes a **cascade record** naming that
> activation in the plan store, then stops the activation (ADR-0297), so the store refuses
> its spawns (§3:3). It then walks the tasks below it: the tasks that activation spawned,
> and the tasks spawned by those tasks' activations in turn, read from the tasks the Task
> Scheduler keeps (§7:8) whether or not their activations have ended. Along the walk it
> cancels every pending occurrence and stops every activation that is pushed or running
> (§9:10), and acts on nothing that has ended. Where a push wins against a cancel (§7:5),
> the activation it names is stopped in turn. The stop is done once nothing below the
> stopped activation is pending, pushed or running. A takeover's stop (ADR-0295 §5) writes
> no cascade record and walks nothing.

There is no series or chain object: the building blocks are spawns, and a stop cascades
down from live work. The walk does the work at once, and the cascade record makes it hold:
whatever a restart or a failure leaves of the walk, §7:5's push step refuses every pending
occurrence below a cascade record, from a conversation's activation or a scheduled step,
settled or not. A step that has ended is walked through, never stopped: §7:8 keeps
every task with anything live below it, so the walk reaches every live descendant, and it
never needs a task that was removed. A stop naming an ended activation directly still
changes nothing.
A takeover's stop (ADR-0295 §5) is not a stop command and does not cascade. Only an
uncommitted activation is taken over (ADR-0332 §4:6), and a spawn commits its activation
(§4), so a taken-over activation has spawned nothing. A stop naming an
activation that has already ended changes nothing (ADR-0295 §1:6): what it left pending is
ended by a cancel. **Pausing** is replacing the pending next task with one at a later time
(§9:4). A step still running is left to finish or is stopped, and a stop also cancels its
next step, so resuming is then a new spawn.

> **Normative.** A task's **chain length** is one where its parent was not started by the Task
> Scheduler, and one more than the parent's task's otherwise, and it is recorded on the task
> when the task is written. A spawn whose task's chain
> length would exceed §12:5's chain limit is refused as *not done*, with the reason.

> **Normative.** A spawn that would take the person's pending occurrences past §12:5's
> pending limit is refused as *not done*, with the reason, and writes nothing.

> **Normative.** §9:7's and §9:8's checks are made in the plan-store step that writes the
> task (§3:3), so two spawns of one round cannot pass them together.

> **Normative.** A stop naming an activation the Task Scheduler has pushed but not yet
> admitted writes its stop record (ADR-0297) for that pushed id and answers `STOPPED`. The
> sensor's admission refuses an id that carries a stop record, so nothing starts, and the
> occurrence ends *stopped* (§7:6).

Every activation the Task Scheduler starts also runs under ADR-0194's ceiling on what the
world may cost, its own deadline and its round limit, as every activation does.

### 10. The Task Manager

> **Normative.** The **Task Manager** is the one way in from outside for managing activations
> and scheduled tasks. It is a surface of commands and queries in ADR-0292 §1:3's sense,
> which the assistant does not perceive, and not a spoke on a channel.

> **Normative.** Its queries are what is running, live from the engine; what is scheduled,
> from the Task Scheduler; and what ran lately, the activations the Task Scheduler started
> that ended most recently, read from the episodes of the schedule (§7:9).
> Its commands are: stop a running or pushed activation (ADR-0295), with §9:6's cascade;
> cancel a scheduled task (§9:5); and replace a scheduled task (§9:4). Adding a task by
> hand is a later decision's.

> **Normative.** Its stop is the one stop operation `AssistantEngine.stop_activation` runs
> (ADR-0295, ADR-0297). The hub chat's stop control and the line's `/stop` are shortcuts
> that send it for the activation their place shows.

> **Normative.** Inside, the same operations serve. Planning's list pull is its queries, and
> planning's cancel and its spawn that replaces a task are its commands under §4:4's
> checks, each with one implementation.

> **Normative.** A command from outside reaches it only as ADR-0292 §12:5 requires: a
> structured act naming one operation, never words a model interprets.

> **Normative.** This decision adds no operation to the local API. `AssistantEngine` gains no
> member, and the browser's surface (ADR-0177 §1:1) gains none: `stop_activation` is the
> Task Manager's stop there. The decision that opens the Task Manager's view brings its
> queries, cancel and replace to the local API, and records that change against ADR-0177
> §1:1 where the browser reaches them.

**Its full view opens later.** For now its operations exist because the shortcuts and the
pull need them. A screen listing what runs, with how long, what is scheduled and what is
done comes with that later decision, and shown to people it would be called **Tasks**.

### 11. Reminders are scheduled tasks

> **Normative.** A decision on reminders builds a reminder as a scheduled task under this
> decision, set by the person, whose when is an instant or a rule. It builds no channel,
> store or sensor of its own for them.

The walk left ADR-0340's rewrite to keep: local times and zones (its §5); recurrence (§9);
the late rule (§8), here §8:9–§8:10, which the input now states and the activation words as
it judges; the second try (§7), here §8:6, likewise stated in the input with no wording
required; the read-back when set,
now naming the places it will speak in; and set, change, cancel and done as plain words ("done",
"snooze", "I already took it"). Its walk's answer 9, that deleting a conversation cancels the reminders set to speak there,
is reversed: nothing is cancelled when a place is gone (§5:9). It drops: the clock as a
channel of its own; a reminder counting as its conversation's own activation (its §3:4),
which §6:9 replaces; the say-only limit (§3:7), since §6:10 applies the ordinary rules; the
special report kind (§10), since a chain's last step says what it found; and grouping at the
sensor (§6:4), since §7:4 groups nothing. Its question 2, whether a reminder set on the hub
chat goes to the line, dissolves: the spawner suggests the places, the line's chat among
them (§5:6), and the line's chat is on every place list where the line is connected (§5:11, §6:7), and the read-back says so ("I'll remind you on Telegram at
8"). Snoozing is a new spawn (§9:3).

### 12. The code it binds

> **Normative.** `core/types.py` gains frozen pydantic models for the scheduled task and its
> occurrence, holding §3:6's parts, and closed `StrEnum`s for a task's author (the person or
> the assistant) and an occurrence's state: pending; pushed, naming its activation; done;
> couldn't finish; stopped; interrupted; cancelled; skipped. An occurrence also records how
> many times it has been pushed (§8:5) and whether it is a second try (§8:6), and a task its
> chain length (§9:7). Each
> enumeration is added to and never renamed. Exact names, and how when and the marks are
> represented, are the lane's that builds the triad (§13).

> **Normative.** `LabelKind` gains two members: the scheduled task, with the prefix `T`, and
> the place, with the prefix `L`.

> **Normative.** `PlanStore` gains members to: write a task with the spawn's effect claim and
> §9:7–§9:8's checks in one step (§3:3, §9:9), cancelling a task it replaces in that same
> step (§9:4); cancel one (§9:5); read
> tasks by id, by person and state, and by parent, and a task's lineage (§6:5); read
> whether anything below a task is pending, pushed or running (§7:8, §9:6); write a stop
> record for a pushed id not yet admitted (§9:10); write a cascade record (§9:6) and refuse
> a push below one (§7:5); read the occurrences due at an instant
> and the tasks whose waits have all ended (§7:3, §5:4); mark an occurrence pushed (§7:5);
> write an occurrence's outcome (§7:6, §8); settle a message's effect record whose outcome
> is unknown or unwritten from its place's confirmation, once, to done with its position or
> to not done, and refuse every other change to an outcome already written (§8:11); and
> remove a task once §7:8 holds. `PlanExport`
> gains the tasks the store holds, their occurrences and the cascade records, its `schema_version`
> advances, and `PlanStore.clear` erases them (ADR-0004 §6, ADR-0292 §3:11). Exact signatures
> are the triad's, within this list.

> **Normative.** The plan store is a store under ADR-0326: the lane that changes its schema
> ships the upgrade (ADR-0326 §4:1).

> **Normative.** `Settings` gains six fields, each a default that
> [#2589](https://github.com/leonapivato/ai-assistant/issues/2589) may tune without a
> decision: the sensor's **recheck interval** (thirty seconds); the **lateness grace** (two
> minutes); the **chain limit** (ten); the **pending limit**, per person (fifty); the
> **push limit** (three); and the **listing bound** for the list pull and
> the Task Manager's queries (twenty). Exact names are the triad's.

> **Normative.** `PROTOCOL_VERSION` advances in TS1 (§13), in the same change, since
> `PlanningRound`'s place (§12:8) crosses the wire inside `EpisodicMemory.processing_record`
> (ADR-0124 §9). Any other lane whose change alters a wire-carried type advances it again in
> that change.

> **Normative.** `InputOrigin` gains `assistant` (§6:3), added under ADR-0284 §2:1's closed
> enumeration, and every reader of `origin` (ADR-0284 §2:3) handles it in the lane that adds
> it.

> **Normative.** `PlanningRound` gains the place its message goes into, for an activation the
> Task Scheduler starts: the place its place label resolved to (§6:7), and nothing for any
> other activation. Its exact shape is the triad's.

> **Normative.** `NewMessage` gains, for the assistant's messages alone, the id of the effect
> record the message was claimed under (ADR-0306 §5:4), and `ConversationStore.append_message`
> records it with the message. `ConversationStore` gains a read answering, for a
> conversation and such an id, whether the conversation holds the message written under it,
> deleted or not, and at what position. The id is shown on no message a device reads. It is
> carried in the conversations' export with its message (`ConversationExport`, ADR-0004
> §6), whose `schema_version` advances. Exact names are that triad's (§13).

### 13. Delivery

The lanes, each after this decision merges `Accepted`, held by milestone 15:

1. **TS1, the `PlanStore` triad with its primary implementation** (ADR-0137 §2:1):
   §12:1's types, the `LabelKind` and `InputOrigin` members with every reader of `origin`,
   `PlanningRound`'s place (§12:8), the register entry (§2:7), the six settings, the
   `PlanStore` members and `PlanExport`, the conformance suite, the canonical fake, the
   SQLite plan store in `planning/` with its upgrade, and the advance of `PROTOCOL_VERSION`
   (§12:6).
2. **TS1b, the `ConversationStore` triad with its primary implementation** (ADR-0137 §2:1):
   §12:9's `NewMessage` field and `ConversationStore` read, the conformance suite's cases for
   them, the canonical fake, and the SQLite conversation store in `memory/` with its upgrade (ADR-0326
   §4:1).
3. **TS2, the Task Scheduler in `orchestration/`:** its kind (§2:6), its sensor (§7, §8), each
   kind's declaration of whether it can confirm delivery (§8:12), the chat writer's claim id
   (§12:9), the three capabilities (§4), the stop's cascade and the pushed id's stop (§9:6,
   §9:10), the place list (§5:10–§5:13), the activation it
   starts (§6), the place-window links and labels (§9:1–§9:3), the Task Manager's operations
   (§10), and the composition wiring in `app/`.

> **Normative.** TS1 may touch `core`, `testing`, `planning` and their tests, permitted
> expressly here as one unit. In `orchestration/` it may only adapt each reader of
> `InputOrigin` to handle `assistant` (§6:11–§6:12, §12:7). In `wire/` it may only advance
> `PROTOCOL_VERSION` (§12:6), with the wire-surface and type-closure tests that pin it. It
> touches no other package. TS1b may touch `core`, `testing`, `memory` and their tests,
> permitted expressly here as one unit, and no other package.

> **Normative.** TS1 and TS1b merge before TS2, in either order, and TS2 is briefed only after
> both have merged (ADR-0137 §4:1).

> **Normative.** TS2's tests include: two occurrences due at one instant, which start two
> activations; a cancel and a push racing, where whichever lands first wins; each of
> §8:2–§8:7 at start, a step that spawned its next never pushed again among them; a second
> try cut off by a second restart before it claimed anything, which ends *interrupted*;
> three restarts, the first two before anything was claimed and the third after a message
> was claimed into the line's chat with no outcome, which ends *interrupted* with no fourth
> push (§8:5–§8:7); a hub chat message left with no outcome, confirmed recorded, which ends
> its occurrence *done* with no second try, and confirmed absent, which is pushed again
> unmarked (§8:11); a line message left with no outcome, which takes the second try; a
> restart after a step's stop record was written but before its episode froze as stopped,
> which ends the occurrence *stopped* and pushes nothing (§8:1); a crash after a stop
> command's cascade record but before its walk cancels a pending child, for a conversation's
> activation and for a scheduled step whose occurrence has already settled, where the child
> is never pushed and ends *cancelled* (§7:5); a
> spawn refused on a stop record, at the chain limit and at the pending limit; a spawn
> replacing a task with nothing pending refused, and one replacing a task that waits on
> named tasks with an invalid wait refused (§9:4); a task removed once §7:8 holds, and one
> kept while a task below it is pending; a stop of a step whose child ended after spawning
> a grandchild still pending, which cancels the grandchild (§9:6); a stop of a pushed id
> with admission suspended right after the pushed write, which nothing then starts
> (§9:10); a child spawned now
> that ends before a later round of its parent writes the task waiting on it, which that
> task still names (§5:4, §7:8); a restart after a step's next task ran and was removed,
> which still never pushes that step again (§8:2); a
> task suggesting two places, one of them deleted, which still has the other on its list
> (§5:8); a message of a task's activation naming a place off its list, refused (§6:7); a
> spawn naming a channel heading or a label never shown, refused (§5:13); a chain
> stopped while its next task is pushed between the stop and the cancel, whose activation is
> then stopped; a takeover's stop, which writes no cascade record; a conversation deleted
> while a pending task suggests it, which cancels nothing, and whose occurrence then speaks on
> the line, or writes nothing with no line (§5:8–§5:9); and a spawn from a task's activation
> stating no places, which carries its task's suggested places forward (§5:6).

> **Normative.** TS2 adds synthetic prompt cases (ADR-0337 §3) for at least: a spawn to
> start now; "snooze 10 minutes" right after a task's message, which is a new spawn;
> "remind me on Telegram at 8", set on the hub chat, which suggests the line's chat; and a
> cancel whose words could mean either of two tasks; and "make it 9" for a reminder not yet
> said, which is a spawn replacing it.

### 14. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Merging inputs that come due together, planning's view of what else is running, and stopping a running activation in words across places | The operations between activations, a separate decision (proposal #3384's Part A) |
| The rule vocabulary (daily, weekdays, weekly), zone semantics, the read-back's wording, and the set, change, cancel and done phrases for reminders | The reminders decision, ADR-0340 rewritten on this one (§11) |
| Which places a creator may name beyond §5:6, and spawning for other people | A later decision, with the household design ([#691](https://github.com/leonapivato/ai-assistant/issues/691)) |
| Speaking as a call in every place, and planning choosing the place (ADR-0292 §7:2) | The decision on calls onto channels |
| Opening the Task Manager's view to people, and adding a task by hand | A later decision (§10:6) |
| Conditions in the world, and what an event's activation may spawn | Watches ([#2585](https://github.com/leonapivato/ai-assistant/issues/2585)), then a decision of their own |
| Hub events beyond named tasks ending (§5:4) | A later decision |
| What a place can do: whether it notifies, its formatting, who sees it | [#3250](https://github.com/leonapivato/ai-assistant/issues/3250) |
| How marks travel on every read of a peer's episode, and the audience where a message lands | The outside-content and audience designs ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)) |
| A running step that spawns again after its pending next step was cancelled in words | Stopping in words, with Part A; the Task Manager's stop first (§9:6) |
| The values of §12:5 | #2589 |
| How a claim left with no outcome is recovered for any effect but the message of an activation the Task Scheduler starts (§8:6, §8:11) | [#2584](https://github.com/leonapivato/ai-assistant/issues/2584) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 15. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0284 | §2:1, in the addition alone: `InputOrigin` gains `assistant`, the origin of a scheduled task's input that carries no outside-content mark | §6:3, §12:7 |
| ADR-0292 | §5:6, in the addition alone: every scheduled task, whoever set it, informs the activation it starts and authorizes nothing; §6:8, in the addition alone: a scheduled task falling due starts an activation, though the assistant wrote it; §12:1's *setting a timer*: it is a spawn, written through the Task Scheduler's actuator | §3:9, §6:1, §3:1, §4:3 |
| ADR-0293 | §5:2's table, in the addition alone: an assistant's message also records the effect record it was claimed under, kept for confirming delivery after a restart and shown on no device | §8:12, §12:9 |
| ADR-0295 | §1:1, in the addition alone: a stop command naming a running or pushed activation also stops what is still live below it, walking through steps that have ended, and its cascade record keeps anything below it from being pushed later; a takeover's stop (§5:1) does not cascade, since only an uncommitted activation is taken over (ADR-0332 §4:6) and a spawn commits, so it has spawned nothing | §7:5, §9:6 |
| ADR-0297 | §5:5, for an id the Task Scheduler has pushed and not yet admitted: the stop writes its stop record and answers `STOPPED`, and admission refuses that id | §9:10 |
| ADR-0303 | §7:1, in the addition alone: an item an activation the Task Scheduler started wrote also links to its scheduled task, while the Task Scheduler holds it | §9:1 |
| ADR-0306 | §6:4, in the addition alone: a message's record whose outcome is unknown or unwritten is settled once more from its place's confirmation (§8:11, §12:3); §4:7, for an activation the Task Scheduler starts: each message goes into the place on its place list it names, and none goes off the list; §5:6's *never resolved by guessing* and §5:13's *never retried, done another way*, for that activation's message alone: one second try, where its place's kind cannot confirm delivery | §6:7, §8:6, §8:8, §8:11, §12:3 |
| ADR-0307 | §3:1, §3:7 and §3:8, for an activation the Task Scheduler starts: they read the places on its place list, and *couldn't finish* goes into its suggested places on it; §5:1, in the addition alone: the label kinds `T` and `L`; §5:6, in the addition alone: an item is shown with its scheduled task's label; §6:1, in the addition alone: planning in an activation offered spawn is given its place list, places grouped under channel headings, built when shown | §5:10–§5:13, §6:7, §9:2 |
| ADR-0323 | §6:1's *the chat is the input's place*, for an activation the Task Scheduler starts: the chat is a place on its place list wherever the line is connected, and the writer still refuses any chat but the one the settings name | §5:11, §6:7 |
| ADR-0328 | §4:2, in the addition alone: no support points at an input whose origin is `assistant`, and the writer refuses one | §6:11 |
| ADR-0329 | §13:6, in the addition alone: an activation the Task Scheduler starts writes its messages into places on its place list, and no other background work messages the user | §6:7 |
| ADR-0338 | §2:2, in the addition alone: an activation the Task Scheduler starts is for the person its task is for | §6:4 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0292 §1:1–§1:3, §2:5–§2:6, §2:10 | Nothing: the Task Scheduler is built in, reached by a sensor and an actuator, and the Task Manager is commands and queries |
| ADR-0292 §3 | Nothing: its clauses bind the Task Scheduler (§2:3); removal is its kind's retention (§3:5), and the assistant deletes nothing (§3:9) |
| ADR-0292 §10:5 | Nothing: what ran is the episodes indexed by the schedule (§7:9) |
| ADR-0292 §7:4 | Nothing: a kind that can confirm delivery reads what counts as sent for it (§8:11–§8:12) |
| ADR-0323 §10 | Nothing: the line's window is the hub's own episodes, so the line cannot confirm delivery (§8:12) |
| ADR-0124 §9 | Nothing: TS1 advances `PROTOCOL_VERSION` in the change that puts `PlanningRound`'s place on the wire (§12:6) |
| ADR-0292 §6:2, §6:10 | Nothing: an occurrence falling due is a push, and one input starts one activation |
| ADR-0292 §11:7 | Nothing: running work is current state, and a pushed mark records only which activation an occurrence was pushed to (§2:5, §7:5) |
| ADR-0292 §12:2, §12:5–§12:6 | Nothing: a spawn is still an action that planning chooses, authorizing checks, acting runs and the record keeps; a command is a structured act |
| ADR-0293 §6:2, §10:4 | Nothing: a task's activation is not started from the conversation it speaks into, which the chat already permits |
| ADR-0295, ADR-0297 | Nothing beyond the rows above: the Task Manager's stop is their stop, a stop of an ended activation changes nothing (ADR-0295 §1:6), and the store refuses a stopped activation's spawn (§3:3) |
| ADR-0292 §10:1–§10:2 | Nothing: the schedule's window is what its medium holds, the lineage of the kept tasks (§6:5), and the parent's and waited-on tasks' episodes come with the input |
| ADR-0306 §2, §3:3, §4:1, §5:3–§5:4, §5:9 | Nothing: the three capabilities declare the five properties, run against the store each reaches, and are checked, claimed and matched as their declarations say |
| ADR-0306 §4:7's interim on ADR-0292 §7:2 | Nothing for every other activation: planning chooses no place for it, and milestone 15 does not end the interim (§6:8) |
| ADR-0317 | Nothing: it reaches activations started from a conversation, and a task's activation is not one |
| ADR-0321 §4:1 | Nothing: an approval is used only by its yes's activation (§3:9) |
| ADR-0332 §2:3, §3:3, §4:1, §4:6 | Nothing: the schedule runs side by side, and a task's activation never joins and is never taken over (§6) |
| ADR-0332 §9's background work | Nothing in its words: spawning answers it, with no kind of its own |
| ADR-0341 §2:1 | Nothing: the list pull is a pure read, and spawn and cancel are not (§4) |
| ADR-0338 | Nothing beyond §2:2's addition: preferences about places reach planning as style memories, as they do today (§5) |
| ADR-0286 §6:4, §7:2 | Nothing: no open episode is shown (§6:5), and the restart close runs before §8 settles |
| ADR-0083 §7 | Nothing: the scheduler's table is unchanged, and the Task Scheduler's sensor is a loop of its own |
| ADR-0177 §1:1 | Nothing: the browser's surface gains no operation (§10:6) |
| ADR-0194 | Nothing: its ceiling binds every activation the Task Scheduler starts |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0284, ADR-0292, ADR-0293, ADR-0295, ADR-0297, ADR-0303, ADR-0306,
> ADR-0307, ADR-0323, ADR-0328, ADR-0329 and ADR-0338, atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified
> bodies. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**

- "Remind me at 8 to call Mom about it", once the reminders decision lands, is a task that
  speaks here at 8 and reads its parent's episode for what "it" was.
- "Remind me on Telegram at 8", set on the hub chat, suggests the line's chat from the place
  list (§5:6, §5:10).
- "Keep looking for apartments this week" is a step that spawns its next for tomorrow, and
  each step spawns the next until done or capped (§9:7).
- "Compare these three apartments" is three checks spawned now and a gather step timed after
  all three end.
- "Stop the apartment search" through the Task Manager stops the running step, and its
  cascade cancels the pending next step and stops anything below it that is live (§9:6).
  In words, planning cancels the pending steps the list pull shows (§9:3).
- Every spawn survives a restart, now and later share one path, new input still reaches the
  controller only through a sensor, and the Task Manager sees everything.

| Situation | What happens |
| --- | --- |
| Two unrelated reminders due at 8:00 | Two activations, two messages (§7:4) |
| A reminder set twice by mistake | Two messages under this decision; merging is a separate decision's (§14) |
| A reminder falls due while you're typing to Telegram | Separate activations, because their authority differs. Both happen (§6) |
| "Snooze 10 minutes" right after a reminder | A new spawn, written from the episode the window shows beside it: one round (§9:3) |
| "Make it 9", for a reminder not yet said | A spawn replacing it, in one store step (§9:4) |
| The hub restarts mid-step | The step is settled from its records, and never run again once it has spawned its next (§8:2) |
| The hub was down at 8 | The reminder is said once, marked late (§8:9) |

**What it costs.**

- **A model call per occurrence,** and per step of a chain. The chain and pending limits
  bound how many, and nothing else bounds model spend.
- **Duplicates are possible on the line.** After a restart the hub chat reads whether a
  message was recorded (§8:11), so it never hears one twice. The line cannot, so a message
  there that may not have arrived is tried once more, its input saying so (§8:6, §8:12).
- **A missed occurrence is said however late** (§8:9).
- **Words cannot stop a running step yet.** A cancel in words ends only what is pending, and
  a step still running may spawn again. Until Part A lands, the Task Manager's stop, through
  the hub chat's control, the line's `/stop` or the CLI, is the safe order (§9:6).
- **A step that acted in the world and was cut off by a restart is not repeated** (§8:7),
  so the rest of its work waits for the person to ask again.
- **Machinery and records.** A triad on `PlanStore` with an upgrade, a smaller one on
  `ConversationStore` with an upgrade, a channel type in `core`'s register, two label kinds,
  an input origin, a sensor loop, a delivery declaration on each kind, three capabilities,
  six settings, and header records on twelve ADRs.

**The cut, for the dispatcher.** §13's three lanes. TS1 is the `PlanStore` triad with its
primary implementation, the SQLite plan store, and TS1b the `ConversationStore` triad with
the SQLite conversation store, each one lane under ADR-0137 §2:1, independent of each other.
TS2 is every consumer, in `orchestration/` with the composition wiring, briefed against both
merged contracts under ADR-0137 §4:1. The reminders decision's own lanes follow all three.

**An origin to be recast.** `InputOrigin.assistant` (§6:3, §12:7) is written as this
decision needs it. The owner has directed a separate decision that recasts an input's origin
as the set of parties whose words it carries, sharing ADR-0345's holder kinds, with
*outside* following from those parties. `assistant` here is that decision's stand-in for
an input whose parties are {the assistant}, a party of ADR-0345's kind *the assistant's
statement*, and not for the empty set. The empty set is kept for an input that carries no
one's words at all, and `None` means the parties are unknown. Nothing here decides it.

**What would reopen it.**

- Chains that hit the chain or pending limit in ordinary use.
- Second tries that people hear as noise.
- Steps cut off by restarts often enough that §8:7's caution costs real work.
- A medium the assistant needs to write into that is not the Task Scheduler, the chat or the
  line, which would show whether *the assistant's own records* is the right effect value for
  a hosted medium (§4:2).

## Alternatives considered

- **Fork,** a running copy of an activation. Rejected: it doubles the model calls, and the
  copy could act twice.
- **Suspend and resume.** Rejected: it does not survive a restart. Ending and being
  continued by a spawned step does the same job.
- **A spawn "now" that starts the activation directly,** past the Task Scheduler. Rejected:
  it would not survive a restart, would be a second path, would bring new input to the
  controller without a sensor, and the Task Manager would not see it.
- **Grouping due tasks at the sensor,** as ADR-0340's draft did. Rejected: grouping is a
  separate decision's, and the sensor groups nothing (§7:4).
- **"Background task" as a kind of its own.** Rejected: an activation spawning its own next
  step covers it.
- **A lineage rule that pushes findings between related activations.** Rejected: a task's
  parent and the tasks it waits for are reads of finished episodes, not sharing (§6:6).
- **A store of its own behind a new `Protocol`.** A cleaner separation. Rejected because the
  task and the spawn's effect claim, and the stop that refuses it, must be decided in one
  step, which the plan store already holds (ADR-0297, ADR-0306 §5:4).
- **A row of ADR-0083 §7's scheduler.** Rejected: the scheduler accepts lateness and
  starvation, and a late reminder is the defect.
- **A new effect value for a hosted medium.** Rejected for now: every rule ADR-0306 states
  reads the three values, and *the assistant's own records* already routes, claims and
  records a write in the hub as a spawn needs (§4:2). §4:2 keeps the value from making the
  content memory.
- **Running a step again after a restart whatever it did.** Rejected: it would fork a chain
  that had spawned its next step, and repeat a world act whose outcome is unknown, which
  ADR-0306 §5:13 forbids.
- **A default place where a task speaks,** such as the place it was set. Rejected by the
  walk: the spawner names the places, and may name none.
- **Suggested places as the only places a task's activation may speak in.** Rejected in the
  owner's review of 2026-10-25: "I said it can take in a suggest place, I dont think that
  means it should be constrained to that." The place list is the boundary (§6:7).
- **Exactly one place per task, or none.** Rejected in the owner's review of 2026-10-25: it
  thought only of speaking. Some activations need no place and some need several, and
  "remind me on Telegram at 8", set on the hub chat, must work.
- **Naming a channel, such as "the hub chat".** Rejected: a channel with many places names
  no one place, so only a place carries a label (§5:13).
- **Snooze as a change of the task that fired.** Rejected in the owner's review: a fired task
  is removed once settled (§7:8), and a snooze is a new spawn from the episode (§9:3).
- **A change capability.** Rejected in the owner's review of 2026-10-25: a change is a spawn
  that names the task it replaces (§9:4), so it passes every check a spawn does, and a task
  waiting on named tasks cannot be moved past its wait.
- **A series or chain object** that groups a lineage's tasks. Rejected in the owner's review
  of 2026-10-25: "I dont love how a series is becoming some object… keep the building blocks
  as just spawns." A stop cascades down from live work (§9:6), and the list pull's parent
  descriptions show which tasks belong together (§4:6).
- **Cascading a takeover's stop.** Not needed: only an uncommitted activation is taken over
  (ADR-0332 §4:6), and a spawn commits its activation (§4), so a taken-over activation has
  spawned nothing to cascade to.
- **A place pull** listing the person's other conversations. Removed in the owner's review
  of 2026-10-25: it returns with the decision on speaking as a call in every place.
- **Cancelling a task when its places are gone,** as ADR-0340's walk had it for a deleted
  conversation. Rejected in the owner's review of 2026-10-25: "just not deleting anything
  when a conversation is deleted… keep it kind of general". Lists are built when shown, and
  the line is the fallback (§5:8–§5:9).
- **Requiring what a late or second-try message says.** Removed in the owner's review of
  2026-10-25: the input states the facts, and the wording is the activation's (§8:6, §8:9).
- **Keeping fired tasks as their history.** Rejected: the episodes already hold what ran
  (§7:9), and a second history would drift from them.
- **"Your next message" as a hub event.** Rejected by the owner.
- **Task Manager operations on the local API now.** Rejected: nothing outside needs them
  before its view opens, and the stop it needs exists (§10:6).
