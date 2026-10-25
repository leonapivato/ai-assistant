# 350. Every spawn is a scheduled task written into the Task Scheduler, whose sensor starts it when it comes due, and the Task Manager is the one way in from outside

- Status: Proposed
- Date: 2026-10-25
- Scope: how one activation sets up another, to start now, at an instant, on a rule or after other scheduled tasks end; the **Task Scheduler**, the built-in channel every such spawn is written into (§2), the spawn and what a scheduled task holds (§3), the four capabilities planning is offered (§4), when a task falls due and where it may speak (§5), the activation it starts (§6), its sensor (§7), a restart and a miss (§8), finding, changing, cancelling and stopping scheduled work, with its limits (§9), and the **Task Manager**, the one way in from outside (§10). It is Part B (§§6–11) of proposal [#3384](https://github.com/leonapivato/ai-assistant/pull/3384), read at `86152e7a8`, with the B rows of its tables. Reminders are scheduled tasks (§11), and their own rules stay for the reminders decision. Part A, the operations between activations, is a separate decision, and this one stands on ADR-0332 as it is. §14 names what is not decided here.
- Dependency: [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md), [ADR-0295](0295-stopping-an-activation-is-a-command-that-starts-nothing-new-and-cuts-off-nothing-already-sent.md), [ADR-0297](0297-a-stop-is-marked-on-the-activation-and-recorded-where-claims-are-decided.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md) and [ADR-0341](0341-a-pure-read-is-a-call-that-writes-nothing-and-does-not-leave-the-hub-so-looking-something-up-in-the-assistants-own-records-does-not-commit-an-activation.md), as their status lines leave them.
- Authorization: the owner ruled every part in the design walk of 2026-10-21 to 2026-10-24, recorded in proposal #3384's §§6–11. On 2026-10-24 the owner asked "Should we make this an adr and implement it first before moving to modes?", and on the coordinator's recommendation, to convert both parts and implement this one first, said "Yes to the milestone, number it correctly". The dispatcher assigned 0350. Ratifying it is the owner's, after the owner's own review: "just finish adrs A and B. And dont ratify them. Ill review when they are done." (2026-10-25).
- Milestone: [15, Task Scheduler: reminders and work that runs later](https://github.com/leonapivato/ai-assistant/milestone/15); acceptance [#3416](https://github.com/leonapivato/ai-assistant/issues/3416).
- **Changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `PlanStore` gains the scheduled-task members and `PlanExport` the tasks (§12:3). `core/types.py` gains the scheduled task, its occurrence and their enumerations (§12:1), `LabelKind` gains a member (§12:2), and `InputOrigin` gains `assistant` (§12:7). `core`'s register of channel types gains the Task Scheduler (§2:7), and `Settings` gains six fields (§12:5). `AssistantEngine` gains no member (§10:6). `PROTOCOL_VERSION` advances in the lane whose types first cross the wire (§12:6).
- **Partially supersedes**, in the clauses §15's first table names: ADR-0284, ADR-0292, ADR-0303, ADR-0306, ADR-0307, ADR-0323, ADR-0328, ADR-0329 and ADR-0338.

## Context

**The question.** Activations run side by side. How does one start another, now or later,
and how is that work found, changed, cancelled and stopped? The owner's walk answered with
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
- `AssistantEngine.delete_conversation` is the engine's deletion of a conversation.

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
carries no authority, states the one place it may speak or none, and points to the
activation that spawned it and the tasks it waits for. The sensor compares wall-clock
instants, pushes each due task on its own, and after a restart never runs a step again once
it has spawned its next. The Task Manager is the one way in from outside, and planning uses
the same operations.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> reviewed it, ratifies it. An assigned number or a green review alone does not change its
> status.

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

> **Normative.** It holds only **scheduled tasks**, each an activation waiting to be
> started, with its occurrences and their outcomes. Whether an activation is running is never
> written into it: that is the assistant's current state (ADR-0292 §11:7), read live from
> the engine.

> **Normative.** Its kind is declared in code, as the line's is (`orchestration/channel_kinds.py`).
> It declares that its place runs activations side by side and not one at a time (ADR-0332
> §2:3), that it takes no message from a person or from the assistant, that it shows no
> running work, that it expects no reply, and that it pushes and can be pulled (ADR-0292
> §6:5).

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
> - where it may speak (§5:5);
> - what it carries: the creator's instruction, bounded in size;
> - its **parent**, the activation that spawned it;
> - the tasks it waits for, where its when is §5:4's;
> - where it was set: the place of the spawning activation's input;
> - its marks (§3:8);
> - its occurrences, each with its state and outcome (§7:5–§7:6).

> **Normative.** A task's author is the person, established as the spawning activation's
> input's author was, where that input carries the person's authority (ADR-0292 §5:5), and
> the assistant otherwise. Either is written when the task is set (ADR-0292 §5's table).

> **Normative.** A task spawned by an activation that has read outside content (ADR-0306
> §4:5) carries the outside-content mark.

> **Normative.** A scheduled task carries no authority, whoever set it. It informs the
> activation it starts and authorizes nothing, as ADR-0292 §5:6 already rules of a reminder.
> No approval given in the spawning activation carries over (ADR-0321 §4:1).

> **Normative.** Where a task was set is recorded as data. No rule reads it for where the task
> speaks or whom it is for.

So a person's "remind me…" in the hub chat is the person's task, and the assistant's own
follow-up ("I'll check back tomorrow"), and every step a chain spawns, is the assistant's.
Neither can authorize anything when it comes due. An approval is used only by the activation
of the yes that gave it, so a spawned step that needs one asks again.

**What spawning is for.** It is the rarer case. Most activations call tools, speak and end.
A spawn covers continuing work too long for one activation, breaking work into independent
pieces, isolating work in a separate context, reminders and schedules, and the assistant's
own follow-ups: a retry, a check back, a nudge. These vary only in when (§5:1) and where
(§5:5). "Background task" is dropped as a concept: an activation spawning its own next step
covers it.

### 4. The capabilities

> **Normative.** Planning is offered four capabilities, each declared under ADR-0306 §2 with
> the effect *the assistant's own records*, never leaving the hub, and never with an unknown
> outcome:
>
> | Capability | What it does | Safe to repeat | `writes` | Result |
> | --- | --- | --- | --- | --- |
> | spawn | writes a scheduled task: what it carries, when (§5:1), where it may speak or none (§5:5) | No | the person's tier | no outside text |
> | change a scheduled task | moves its next occurrence (§9:4) | No | the person's tier | no outside text |
> | cancel a scheduled task | ends what of it is pending (§9:5) | Yes | the person's tier | no outside text |
> | list scheduled tasks | the list pull (§4:6) | Yes | none | no outside text |
>
> Exact names and arguments are the lane's that builds them (§13), within this table.

> **Normative.** The effect value *the assistant's own records* is read by ADR-0306's and
> ADR-0341's rules alone: for claims, effect records, routing and the pure read. It makes no
> part of the Task Scheduler's content the assistant's memory, and §2:3 stands.

> **Normative.** Acting runs each of the four against the plan store directly, as ADR-0306
> §3:3 runs a call to the assistant's own records: awaited to its end, and never through
> `ToolInvoker`. For spawn, change and cancel, that direct write is the Task Scheduler's
> actuator.

So spawn, change and cancel each write, and so commit their activation (ADR-0332 §3:2,
ADR-0341 §2:1). The list pull writes nothing and does not leave the hub, so it is a pure
read (ADR-0341 §2:1), and planning may look before it acts. A spawn is not safe to repeat,
and neither is a change, since a change on a task that has ended adds an occurrence (§9:4).
So each gets an effect record (ADR-0306 §5:3), and the backstop refuses the same spawn or
the same change twice in one matter unless planning marks it deliberate (ADR-0306 §5:9).

> **Normative.** Change and cancel are offered to an activation whose input carries the
> person's authority. Any other activation's change or cancel naming a task it did not
> spawn is refused as *not done*, with the reason, and writes nothing.

> **Normative.** A spawn is refused as *not done*, with the reason, and writes nothing,
> where its instant is earlier than now, where it waits on a task §5:4 does not allow, where
> it states a place §5:6 does not allow or states neither a place nor none (§5:5), or where
> §9:7 or §9:8 refuses it.

> **Normative.** The **list pull** answers, for the person the asking activation is for: the
> activations running for that person, other than the asker, live from the engine, each
> shown as ADR-0332 §4:1 shows one to understanding and under ADR-0332 §4:2–§4:3's limits;
> that person's pending scheduled tasks; and those of their tasks that ended most recently.
> Each part is bounded by §12:5's listing bound, and each item carries its label (§9:2).

> **Normative.** In the list pull's result, a running activation whose input's origin is
> `outside`, and a task carrying the outside-content mark, are shown with their text
> withheld and their mark shown. That is how the result carries no outside text.

> **Normative.** A spawn's result carries the new task's label and the hub's own rendering of
> when it falls due and where it may speak, written from the stored record.

### 5. When, and where it may speak

> **Normative.** A task's **when** is one of: **now**; **an instant**; **a rule**; or **after
> named tasks end**. A spawn may state an instant as a delay from now, resolved to an
> instant when it is set. A condition ("when I get home") is not a when under this decision.

> **Normative.** An instant is stored in UTC and compared as one. A spawn states it with its
> UTC offset or as a delay. How a local time stated without an offset is read in a person's
> zone is the reminders decision's (§11).

> **Normative.** A **rule** is a description, validated whole by the hub when the task is
> written, from which code alone computes each next occurrence's instant. Its vocabulary, its
> zone semantics, its end and what changing one occurrence means are a later decision's.
> Until that decision lands, no capability offers a rule and no task holds one.

> **Normative.** A task timed **after named tasks** falls due at the instant the last of them
> ends, however each ends (§7:6). It may name only one-off tasks for the same person that
> exist when it is written, and what it waits for never changes.

So no task waits on itself, and no two wait on each other. "Compare these three apartments"
is three tasks spawned now and, in a later round that has their labels, a fourth timed after
all three, which reads their episodes (§6:5).

> **Normative.** **Where it may speak** is exactly one place the creator states, or none.
> There is no default, and planning states one or the other on every spawn.

> **Normative.** Until a decision on which places a creator may name lands, a creator may
> state only: the place its own activation's input came from, where that place takes
> messages; for an activation the Task Scheduler started, the place its own task states; or
> none.

> **Normative.** A task that may speak nowhere may work, write records and spawn, and writes
> no message (§6:7).

> **Normative.** Where a task's place is gone when an occurrence falls due, the task is
> cancelled and nothing is pushed. A conversation is gone once deleted. The line's chat is
> gone once the line is disconnected, or once the settings name another chat.

> **Normative.** Deleting a conversation cancels, in the same engine operation, every
> pending task set to speak there. §5:8 catches any that the deletion missed.

A cancelled task stays in the record as cancelled, and deleting a conversation forgets
nothing (ADR-0292 §3:10).

### 6. The activation a scheduled task starts

> **Normative.** An occurrence falling due is a push on the schedule (ADR-0292 §6:2), and it
> starts one activation, whoever set the task, the assistant included.

> **Normative.** Its input's author is the task's author, stated by the hub from the record
> (ADR-0292 §5:1), and it carries no authority (§3:9). The input holds what the task carries,
> when and where the task was set, the instant the occurrence was due, and whether it is late
> (§8:9) or a second try (§8:6).

> **Normative.** Its origin is `outside` where its task carries the outside-content mark, and
> `assistant` otherwise, a value `InputOrigin` gains (§12:7). Its text is the creator's
> instruction as planning wrote it, never the person's own words, so it never takes `user`
> (ADR-0284 §2:2), whoever set the task.

> **Normative.** The activation is for the person its task is for.

> **Normative.** Its window, which the Task Scheduler's kind declares (ADR-0292 §10:2), holds
> its task's parent's episode and the episode of each task its task waited for. Each is
> shown only where frozen, rendered through the episode window's projection (ADR-0276 §4:6)
> under its disclosure predicate (ADR-0276 §4:9), and linked to the activation it records.

> **Normative.** A task's parent and the tasks it waits for are read only as those finished
> episodes. No running activation's state is read through them, and nothing is pushed back
> along them.

An episode still open is never shown, as no open episode reaches a model (ADR-0286 §6:4),
and planning's episode window skips them today. "Remind me at 8 to call Mom about it"
reaches its activation with its parent's episode, which says what "it" was.

> **Normative.** An activation the Task Scheduler starts writes its messages into the place
> its task states, and into no other. Where its task states none, it writes none, as ADR-0307
> §3:8 keeps the text of an input whose place takes no message. ADR-0306 §4:7, ADR-0307 §3:1,
> §3:7 and §3:8 and ADR-0323 §6:1 read, for that activation, the place its task states in
> place of the place its input came from.

> **Normative.** §6:7 holds until a decision makes speaking a call in every place. Milestone
> 15 is not the milestone that ends ADR-0306's interim on ADR-0292 §7:2: planning still
> chooses no place.

> **Normative.** An activation the Task Scheduler starts is never the running activation of
> the place its task states (ADR-0332 §2:3, ADR-0295 §1:2). That place's admission does not
> wait for it, its current state does not show it, and no "working…" or typing is shown for
> it (ADR-0323 §6:8).

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
> that refuses where the occurrence is no longer pending. Where it is refused, nothing is
> pushed. Between a cancel and a push, whichever lands first in the store wins.

> **Normative.** When the activation ends, its occurrence takes its outcome from how it
> ended: *done* where its episode froze completed; *couldn't finish* where it froze failed;
> *stopped* where a stop ended it (ADR-0295 §3:1); and *interrupted* for every other
> ending but ADR-0286 §7:2's restart close, which §8 settles.

> **Normative.** An occurrence ending wakes the sensor, so a task waiting on it falls due at
> once (§5:4), and a task with a rule has its next occurrence computed.

Whether tasks that fall due together should become one is not this decision's. Under
ADR-0332, as §6 shows, they never join: two unrelated reminders due at 8:00 give two
messages, and so does one set twice by mistake.

### 8. After a restart, and missed tasks

> **Normative.** At start, after ADR-0286 §7:2's close and before it pushes anything, the
> sensor settles each occurrence marked pushed whose activation is not running. §8:2–§8:7
> apply in order, and the first that applies decides.

> **Normative.** Where any scheduled task names that activation as its parent, the occurrence
> ends *interrupted* and is never pushed again, so a chain cannot fork.

> **Normative.** Where that activation's episode froze with any ending but ADR-0286 §7:2's
> restart close, the occurrence takes the outcome §7:6 gives.

> **Normative.** Where its task states a place and a message the activation claimed into
> that place is done (ADR-0306 §5:5), the occurrence ends *done*.

> **Normative.** Where the occurrence was not itself a second try (§8:6), and the activation
> claimed no effect, or only messages each *not done*, the occurrence is pushed again. It is
> pushed at most §12:5's push limit of times in all, and is then ended *interrupted*.

> **Normative.** Where the occurrence was not itself a second try, and the activation claimed
> only messages and any of them has an unknown outcome or none written, the occurrence is
> pushed once more as a **second try**, and the occurrence records that it is one. Its input
> says so, and planning's instruction has its message say that it is sent in case the last
> did not arrive. It is never tried a third time. After the second try's activation ends,
> the occurrence takes §7:6's outcome. Where a restart cuts that activation off too, §8:4
> may still find it *done*, and §8:7 otherwise ends it *interrupted*.

> **Normative.** Otherwise the occurrence ends *interrupted* and is never pushed again.
> ADR-0306 §5:6 and §5:13 hold for every effect it claimed.

> **Normative.** §8:6 replaces ADR-0306 §5:6's *never resolved by guessing* and §5:13's
> *never retried, done another way* for the message of an activation the Task Scheduler
> starts, and for no other effect. No outcome is ever reported as done.

So a step that has spawned its next is never run again. A step that may have spoken is said
at most twice, the second time marked. A step that did nothing runs again. A step that acted
in the world and was cut off is not repeated.

> **Normative.** An occurrence pushed more than §12:5's lateness grace after the instant it
> was due is **late**, and its input says so with that instant. It is said once, however
> late, and no cut-off drops it.

> **Normative.** A task with a rule that missed more than one occurrence pushes only its
> latest missed occurrence, and sets each earlier one *skipped*, so it never bursts.

### 9. Finding, changing, cancelling and stopping scheduled work

> **Normative.** A place-window item written by an activation the Task Scheduler started
> links, beside that activation (ADR-0303 §7:1), to its scheduled task, through the
> occurrence's pushed mark.

> **Normative.** Planning names scheduled tasks by label, under a new kind, `T1`, `T2`…
> (ADR-0307 §5:1). A place-window item that links to a scheduled task is shown with that
> task's label beside its episode label (ADR-0307 §5:6).

> **Normative.** Planning's instruction says three things. A task the place window shows by
> label is changed or cancelled by one call. Any other task is found by the list pull first.
> Where the words could mean more than one task, planning asks which.

"Snooze 10 minutes", right after a reminder, is one call in one round: change `T2`. "Cancel
the bins one" is a pull, then the cancel. A label planning was never shown is refused, with
the reason (ADR-0307 §5:3).

> **Normative.** A change moves a task's next pending occurrence to now or to a new instant.
> On a task whose every occurrence has ended, it adds one pending occurrence at that
> instant. It is refused as *not done*, with the reason, where the task's occurrence is
> pushed and has not ended.

> **Normative.** A cancel ends every pending occurrence of a task as *cancelled*. It stops no
> running activation. Where nothing of the task is pending, it is *not done*, with that
> reason, and writes nothing.

> **Normative.** Whatever stops a chain stops its running step first (ADR-0295) and only then
> cancels the tasks that step spawned. Where a task's push wins against that cancel (§7:5),
> it stops the activation the push named, and treats it in turn as the chain's running step.
> It is done once no activation of the chain is running and none of its tasks is pending.

Once a stop has landed, the store refuses the stopped step's spawn (§3:3), so no new task
appears after it. A task already spawned that the sensor pushes between the stop and the
cancel is the race the rule's second sentence closes: its activation is stopped in turn,
and the walk goes on down the parent pointers. **Pausing** is stopping the running step and
moving its next task's time, two operations and no third.

> **Normative.** A task's **chain length** is one where its parent was not started by the Task
> Scheduler, and one more than the parent's task's otherwise. A spawn whose task's chain
> length would exceed §12:5's chain limit is refused as *not done*, with the reason.

> **Normative.** A spawn, or a change that adds an occurrence (§9:4), that would take the
> person's pending occurrences past §12:5's pending limit is refused as *not done*, with the
> reason, and writes nothing.

> **Normative.** §9:7's and §9:8's checks are made in the plan-store step that writes the
> task or the occurrence (§3:3), so two writes of one round cannot pass them together.

Every activation the Task Scheduler starts also runs under ADR-0194's ceiling on what the
world may cost, its own deadline and its round limit, as every activation does.

### 10. The Task Manager

> **Normative.** The **Task Manager** is the one way in from outside for managing activations
> and scheduled tasks. It is a surface of commands and queries in ADR-0292 §1:3's sense,
> which the assistant does not perceive, and not a spoke on a channel.

> **Normative.** Its queries are what is running, live from the engine; what is scheduled,
> from the Task Scheduler; and what ran lately, the occurrences that ended most recently.
> Its commands are: stop a running activation (ADR-0295); cancel a scheduled task (§9:5);
> and change a scheduled task (§9:4). Adding a task by hand is a later decision's.

> **Normative.** Its stop is the one stop operation `AssistantEngine.stop_activation` runs
> (ADR-0295, ADR-0297). The hub chat's stop control and the line's `/stop` are shortcuts
> that send it for the activation their place shows.

> **Normative.** Inside, the same operations serve. Planning's list pull is its queries, and
> planning's change and cancel are its commands under §4:4's checks, each with one
> implementation.

> **Normative.** A command from outside reaches it only as ADR-0292 §12:5 requires: a
> structured act naming one operation, never words a model interprets.

> **Normative.** This decision adds no operation to the local API. `AssistantEngine` gains no
> member, and the browser's surface (ADR-0177 §1:1) gains none: `stop_activation` is the
> Task Manager's stop there. The decision that opens the Task Manager's view brings its
> queries, cancel and change to the local API, and records that change against ADR-0177
> §1:1 where the browser reaches them.

**Its full view opens later.** For now its operations exist because the shortcuts and the
pull need them. A screen listing what runs, with how long, what is scheduled and what is
done comes with that later decision, and shown to people it would be called **Tasks**.

### 11. Reminders are scheduled tasks

> **Normative.** A decision on reminders builds a reminder as a scheduled task under this
> decision, set by the person, whose when is an instant or a rule. It builds no channel,
> store or sensor of its own for them.

The walk left ADR-0340's rewrite to keep: local times and zones (its §5); recurrence (§9);
the late rule (§8), here §8:9–§8:10; the second try (§7), here §8:6; the read-back when set,
now naming where it will speak; and set, change, cancel and done as plain words ("done",
"snooze", "I already took it"). Its deletion rule is §5:9 here. It drops: the clock as a
channel of its own; a reminder counting as its conversation's own activation (its §3:4),
which §6:9 replaces; the say-only limit (§3:7), since §6:10 applies the ordinary rules; the
special report kind (§10), since a chain's last step says what it found; and grouping at the
sensor (§6:4), since §7:4 groups nothing. Its question 2, whether a reminder set on the hub
chat goes to the line, dissolves: the creator states where a task may speak, and the
read-back says so ("I'll remind you on Telegram at 8").

### 12. The code it binds

> **Normative.** `core/types.py` gains frozen pydantic models for the scheduled task and its
> occurrence, holding §3:6's parts, and closed `StrEnum`s for a task's author (the person or
> the assistant) and an occurrence's state: pending; pushed, naming its activation; done;
> couldn't finish; stopped; interrupted; cancelled; skipped. An occurrence also records how
> many times it has been pushed (§8:5) and whether it is a second try (§8:6). Each
> enumeration is added to and never renamed. Exact names, and how when and the marks are
> represented, are the lane's that builds the triad (§13).

> **Normative.** `LabelKind` gains a member for the scheduled task, with the prefix `T`.

> **Normative.** `PlanStore` gains members to: write a task with the spawn's effect claim and
> §9:7–§9:8's checks in one step (§3:3, §9:9); change one, with §9:8's check in the same
> step (§9:4); cancel one (§9:5); cancel
> every pending task set to speak in a place (§5:9); read tasks by id, by person and state,
> and by parent; read the occurrences due at an instant and the tasks whose waits have all
> ended (§7:3, §5:4); mark an occurrence pushed (§7:5); and write an occurrence's outcome
> (§7:6, §8). `PlanExport` gains the tasks and their occurrences, its `schema_version`
> advances, and `PlanStore.clear` erases them (ADR-0004 §6, ADR-0292 §3:11). Exact signatures
> are the triad's, within this list.

> **Normative.** The plan store is a store under ADR-0326: the lane that changes its schema
> ships the upgrade (ADR-0326 §4:1).

> **Normative.** `Settings` gains six fields, each a default that
> [#2589](https://github.com/leonapivato/ai-assistant/issues/2589) may tune without a
> decision: the sensor's **recheck interval** (thirty seconds); the **lateness grace** (two
> minutes); the **chain limit** (ten); the **pending limit**, per person (fifty); the
> **push limit** (three); and the **listing bound** for the list pull and the Task Manager's
> queries (twenty). Exact names are the triad's.

> **Normative.** `PROTOCOL_VERSION` advances in the lane whose change first puts any type
> this decision adds or changes on the wire (ADR-0124 §9).

> **Normative.** `InputOrigin` gains `assistant` (§6:3), added under ADR-0284 §2:1's closed
> enumeration, and every reader of `origin` (ADR-0284 §2:3) handles it in the lane that adds
> it.

### 13. Delivery

The lanes, each after this decision merges `Accepted`, held by milestone 15:

1. **TS1, the triad with its primary implementation** (ADR-0137 §2:1): §12's types, the
   `LabelKind` and `InputOrigin` members with every reader of `origin`, the register entry
   (§2:7), the six settings, the `PlanStore` members
   and `PlanExport`, the conformance suite, the canonical fake, and the SQLite plan store in
   `planning/` with its upgrade.
2. **TS2, the Task Scheduler in `orchestration/`:** its kind (§2:6), its sensor (§7, §8), the
   four capabilities (§4), the activation it starts (§6), the place-window links and labels
   (§9:1–§9:3), the Task Manager's operations (§10), `delete_conversation`'s cancel (§5:9),
   and the composition wiring in `app/`.

> **Normative.** TS1 may touch `core`, `testing`, `planning` and their tests, permitted
> expressly here as one unit. In `orchestration/` it may only adapt each reader of
> `InputOrigin` to handle `assistant` (§6:11–§6:12, §12:7), and it touches no other package.

> **Normative.** TS1 merges before TS2, and TS2 is briefed only after TS1 has merged
> (ADR-0137 §4:1).

> **Normative.** TS2's tests include: two occurrences due at one instant, which start two
> activations; a cancel and a push racing, where whichever lands first wins; each of
> §8:2–§8:7 at start, a step that spawned its next never pushed again among them; a second
> try cut off by a second restart before it claimed anything, which ends *interrupted*; a
> spawn refused on a stop record, at the chain limit and at the pending limit; a change of
> an ended task refused at the pending limit, and a change and a spawn racing at it; a chain
> stopped while its next task is pushed between the stop and the cancel, whose activation is
> then stopped; and a deleted conversation's pending tasks cancelled.

> **Normative.** TS2 adds synthetic prompt cases (ADR-0337 §3) for at least: a spawn to
> start now; "snooze 10 minutes" right after a task's message; and a cancel whose words
> could mean either of two tasks.

### 14. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Merging inputs that come due together, planning's view of what else is running, and stopping a running activation in words across places | The operations between activations, a separate decision (proposal #3384's Part A) |
| The rule vocabulary (daily, weekdays, weekly), zone semantics, the read-back's wording, and the set, change, cancel and done phrases for reminders | The reminders decision, ADR-0340 rewritten on this one (§11) |
| Which places a creator may name beyond §5:6, and spawning for other people | A later decision, with the household design ([#691](https://github.com/leonapivato/ai-assistant/issues/691)) |
| Speaking as a call in every place, and planning choosing the place (ADR-0292 §7:2) | The decision on calls onto channels |
| Opening the Task Manager's view to people, and adding a task by hand | A later decision (§10:6) |
| Spawns on a condition, and what an event's activation may spawn | Watches ([#2585](https://github.com/leonapivato/ai-assistant/issues/2585)), then a decision of their own |
| How marks travel on every read of a peer's episode, and the audience where a message lands | The outside-content and audience designs ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)) |
| A running step that spawns again after its pending next step was cancelled in words | Stopping in words, with Part A; the Task Manager's stop first (§9:6) |
| The values of §12:5 | #2589 |
| How a claim left with no outcome is recovered for any effect but §8:6's | [#2584](https://github.com/leonapivato/ai-assistant/issues/2584) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 15. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0284 | §2:1, in the addition alone: `InputOrigin` gains `assistant`, the origin of a scheduled task's input that carries no outside-content mark | §6:3, §12:7 |
| ADR-0292 | §5:6, in the addition alone: every scheduled task, whoever set it, informs the activation it starts and authorizes nothing; §6:8, in the addition alone: a scheduled task falling due starts an activation, though the assistant wrote it; §10:1, in the addition alone: the Task Scheduler's window holds its task's parent's and waited-on tasks' frozen episodes; §12:1's *setting a timer*: it is a spawn, written through the Task Scheduler's actuator | §3:9, §6:1, §6:5, §3:1, §4:3 |
| ADR-0303 | §7:1, in the addition alone: an item an activation the Task Scheduler started wrote also links to its scheduled task | §9:1 |
| ADR-0306 | §4:7, for an activation the Task Scheduler starts: its message goes into the place its task states, or nowhere; §5:6's *never resolved by guessing* and §5:13's *never retried, done another way*, for that activation's message alone: one second try | §6:7, §8:6, §8:8 |
| ADR-0307 | §3:1, §3:7 and §3:8, for an activation the Task Scheduler starts: they read the place its task states; §5:1, in the addition alone: the label kind `T`; §5:6, in the addition alone: an item is shown with its scheduled task's label | §6:7, §9:2 |
| ADR-0323 | §6:1's *the chat is the input's place*, for an activation the Task Scheduler starts: the chat is the place its task states, and the writer still refuses any chat but the one the settings name | §6:7 |
| ADR-0328 | §4:2, in the addition alone: no support points at an input whose origin is `assistant`, and the writer refuses one | §6:11 |
| ADR-0329 | §13:6, in the addition alone: an activation the Task Scheduler starts writes its messages into the place its task states, and no other background work messages the user | §6:7 |
| ADR-0338 | §2:2, in the addition alone: an activation the Task Scheduler starts is for the person its task is for | §6:4 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0292 §1:1–§1:3, §2:5–§2:6, §2:10 | Nothing: the Task Scheduler is built in, reached by a sensor and an actuator, and the Task Manager is commands and queries |
| ADR-0292 §3 | Nothing: its clauses bind the Task Scheduler (§2:3); a cancel deletes nothing (§3:8–§3:9) |
| ADR-0292 §6:2, §6:10 | Nothing: an occurrence falling due is a push, and one input starts one activation |
| ADR-0292 §11:7 | Nothing: running work is current state, and a pushed mark records only which activation an occurrence was pushed to (§2:5, §7:5) |
| ADR-0292 §12:2, §12:5–§12:6 | Nothing: a spawn is still an action that planning chooses, authorizing checks, acting runs and the record keeps; a command is a structured act |
| ADR-0293 §6:2, §10:4 | Nothing: a task's activation is not started from the conversation it speaks into, which the chat already permits |
| ADR-0295, ADR-0297 | Nothing: the Task Manager's stop is their stop, and the store refuses a stopped activation's spawn (§3:3) |
| ADR-0306 §2, §3:3, §4:1, §5:3–§5:4, §5:9 | Nothing: the four capabilities declare the five properties, run against the plan store, and are checked, claimed and matched as their declarations say |
| ADR-0306 §4:7's interim on ADR-0292 §7:2 | Nothing for planning: it chooses no place, and milestone 15 does not end the interim (§6:8) |
| ADR-0317 | Nothing: it reaches activations started from a conversation, and a task's activation is not one |
| ADR-0321 §4:1 | Nothing: an approval is used only by its yes's activation (§3:9) |
| ADR-0332 §2:3, §3:3, §4:1, §4:6 | Nothing: the schedule runs side by side, and a task's activation never joins and is never taken over (§6) |
| ADR-0332 §9's background work | Nothing in its words: spawning answers it, with no kind of its own |
| ADR-0341 §2:1 | Nothing: the list pull is a pure read, and spawn, change and cancel are not (§4) |
| ADR-0286 §6:4, §7:2 | Nothing: no open episode is shown (§6:5), and the restart close runs before §8 settles |
| ADR-0083 §7 | Nothing: the scheduler's table is unchanged, and the Task Scheduler's sensor is a loop of its own |
| ADR-0177 §1:1 | Nothing: the browser's surface gains no operation (§10:6) |
| ADR-0194 | Nothing: its ceiling binds every activation the Task Scheduler starts |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0284, ADR-0292, ADR-0303, ADR-0306, ADR-0307, ADR-0323, ADR-0328,
> ADR-0329 and ADR-0338, atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified
> bodies. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**

- "Remind me at 8 to call Mom about it", once the reminders decision lands, is a task that
  speaks here at 8 and reads its parent's episode for what "it" was.
- "Keep looking for apartments this week" is a step that spawns its next for tomorrow, and
  each step spawns the next until done or capped (§9:7).
- "Compare these three apartments" is three checks spawned now and a gather step timed after
  all three end.
- "Stop the apartment search" through the Task Manager stops the running step, then cancels
  the pending one (§9:6).
- Every spawn survives a restart, now and later share one path, new input still reaches the
  controller only through a sensor, and the Task Manager sees everything.

| Situation | What happens |
| --- | --- |
| Two unrelated reminders due at 8:00 | Two activations, two messages (§7:4) |
| A reminder set twice by mistake | Two messages under this decision; merging is a separate decision's (§14) |
| A reminder falls due while you're typing to Telegram | Separate activations, because their authority differs. Both happen (§6) |
| "Snooze 10 minutes" right after a reminder | The window shows which task wrote it: one change (§9:1–§9:4) |
| The hub restarts mid-step | The step is settled from its records, and never run again once it has spawned its next (§8:2) |
| The hub was down at 8 | The reminder is said once, marked late (§8:9) |

**What it costs.**

- **A model call per occurrence,** and per step of a chain. The chain and pending limits
  bound how many, and nothing else bounds model spend.
- **Duplicates are possible.** A message that may not have arrived is said once more,
  marked (§8:6).
- **A missed occurrence is said however late** (§8:9).
- **Words cannot stop a running step yet.** A cancel in words ends only what is pending, and
  a step still running may spawn again. Until Part A lands, the Task Manager's stop, through
  the hub chat's control, the line's `/stop` or the CLI, is the safe order (§9:6).
- **A step that acted in the world and was cut off by a restart is not repeated** (§8:7),
  so the rest of its work waits for the person to ask again.
- **Machinery and records.** A triad on `PlanStore` with an upgrade, a channel type in
  `core`'s register, a label kind, an input origin, a sensor loop, four capabilities, six
  settings, and header records on nine ADRs.

**The cut, for the dispatcher.** §13's two lanes. TS1 is the `PlanStore` triad with its
primary implementation, the SQLite plan store, as one lane under ADR-0137 §2:1. TS2 is every
consumer, in `orchestration/` with the composition wiring, briefed against TS1's merged
contract under ADR-0137 §4:1. The reminders decision's own lanes follow both.

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
  walk: the creator states one, or none.
- **Task Manager operations on the local API now.** Rejected: nothing outside needs them
  before its view opens, and the stop it needs exists (§10:6).
