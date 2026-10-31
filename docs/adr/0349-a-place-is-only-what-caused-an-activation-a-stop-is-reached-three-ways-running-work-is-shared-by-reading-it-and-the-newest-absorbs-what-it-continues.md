# 349. A place is only what caused an activation, a stop is reached three ways, running work is shared by reading it, and the newest absorbs what it continues

- Status: Partially superseded by ADR-0351 (§7:5's third condition, §7:12 and §7:15, each in *origin* alone; §7:7 and §7:21, each in the addition alone: the relay mark; §10:7's *`JoinedInput` keeps its shape*, in the addition alone: `relayed`) and ADR-0352 (§4:7's *with ADR-0350 §9:6's cascade*; §4:6, §4:8, §4:11, §6:1, §6:5 and §7:14, each in the addition alone: a stop call's result lists what is still live, and a round's answer calls run first; §1:5's case of a stop call whose cascade cancels the task) and ADR-0353 (§5:6's list, in the addition alone: when the entry's input arrived; §5:7, in the addition alone: an `R` label may be cited anywhere; §7:3's and §10:1's `continues`, the proposal's field, in its name alone: `meant_for`, and §7:3 in the addition alone: its test; §10:2's *the proposal's labels*: `meant_for`'s, and its *as a grounding defect (ADR-0276 §6)*, in the repair alone: none) and ADR-0356 (§4:6 and §7:26, each in what is offered alone: the stable set is offered on every round, and a call whose condition fails comes back refused) and ADR-0357 (§7:19's instruction line, in where it is said alone: `answer_offer`'s description) and ADR-0360 (§5:2's *understanding alone* and §5:9's *Planning is not shown the section*, for planning's exchange alone: the section in its briefing, and its starts and ends in the news; §5:1, for planning's exchange and in the addition alone: that news shows a started activation's entry and an ended one's short view)
- Date: 2026-10-25
- Scope: the operations between activations that run at the same time. A place is only what caused an activation (§2). The operations are spawn, stop, share and merge (§3). A stop is reached by a command from outside, by a merge, or by planning's call to the Task Manager's stop (§4). Running work is shown to understanding in an in-progress section, and planning pulls it, through ADR-0350's list pull and a look-up of one activation's findings, each reading open episodes through one read function (§5, §6). One matter is one activation: the newest absorbs the older ones its input continues until they act, and after one acts it is offered the newer input, which it takes or declines, the newer waiting on it where it declines (§7). No place waits: every input starts its own activation (§8). This is Part A (§§1–5) of proposal [#3384](https://github.com/leonapivato/ai-assistant/pull/3384) at `86152e7a8`, converted. Its Part B, the Task Scheduler and the Task Manager, is ADR-0350's, and spawning is decided there (§3).
- Dependency: [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0295](0295-stopping-an-activation-is-a-command-that-starts-nothing-new-and-cuts-off-nothing-already-sent.md), [ADR-0297](0297-a-stop-is-marked-on-the-activation-and-recorded-where-claims-are-decided.md), [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0341](0341-a-pure-read-is-a-call-that-writes-nothing-and-does-not-leave-the-hub-so-looking-something-up-in-the-assistants-own-records-does-not-commit-an-activation.md), [ADR-0343](0343-a-join-is-taken-pending-its-readers-marking-and-every-route-by-which-an-activation-leaves-running-settles-it-first.md), [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) and [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), the Task Scheduler and the Task Manager, merged `Accepted` (§1:3), as their status lines leave them.
- Authorization: the owner ruled every part of this decision in the design walk of 2026-10-21 to 2026-10-24, recorded in proposal #3384's Part A, which this converts. On the two ADRs the walk produced, the owner's words, verbatim: "just finish adrs A and B. And dont ratify them. Ill review when they are done." The owner reviewed this draft on 2026-10-25 and directed three changes, verbatim: "drop understandings, cancel, and give planning the task manager stop instead, yes" (§4:6–§4:12); "The outside content mark will be reviewed further. The privacy, audience, and security front." (§11); and, on a section that is often full, "when the assistant gets to be really busy and it's constantly handling tasks at the same time … it might be worth rethinking this" (Consequences). On a further edit, the owner asked: "if in progress action is for awareness only, what does that actually benefit it? Why have that in instead of just giving it a capability to see all in progress episodes?" (§5:2, §5:9), and "If there's constant activations, it can pause it forever though, right?" (§7:12–§7:14); and then: "I think I agree with each of the 349's edits". Ratification is the owner's, after their own review. The dispatcher assigned 0349.
- **Changes `core`, so it is a contract-surface decision. No `Protocol` changes.** `ProposedActivationUnderstanding`'s and `ActivationUnderstanding`'s `continues` becomes a sequence. `ConversationState` names every running activation, not one. `Settings` loses `join_limit` and gains `held_input_limit` and `in_progress_limit` (§9, §10). The offer adds no type: it lives in the engine's working sets, its answer is a call, and `JoinedInput` keeps its shape, its `taken_over_from` also naming the activation that handed an input over (§10:7). Understanding is stored with the episode, and the episode and the conversation's state both cross the wire, so the episode store ships an upgrade and `PROTOCOL_VERSION` advances.
- **Partially supersedes**, in the clauses §12's first table names: ADR-0286, ADR-0292, ADR-0295, ADR-0307, ADR-0315, ADR-0332, ADR-0343 and ADR-0350.
- Partially superseded: 2026-10-25 by ADR-0351 — §7:5's third condition, §7:12 and §7:15, each in *origin* alone: two inputs meet it where both are outside, both the person's own, or both the assistant's, read with understanding's relay mark, and an activation holding several inputs is read over all of them. In §7:12's and §7:15's waits, an input no understanding version has yet covered meets it both as its parties give it and as a relay mark would leave it, outside and carrying no authority; §7:17 reads §7:5's condition so (ADR-0351 §8:5). §7:7 and §7:21, each in the addition alone: an absorption and a take set `relayed` on each `JoinedInput` they append whose input was relayed where it came from, in the same step (ADR-0351 §5:14). §10:7's *`JoinedInput` keeps its shape*, in the addition alone: `JoinedInput` gains `relayed: bool = False` (ADR-0351 §5:14). Every other clause stands. This replacement takes effect on ratification of ADR-0351. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-26 by ADR-0352 — §4:7's *with ADR-0350 §9:6's cascade*: the stop call stops only the activation it names (ADR-0352 §2:1). §4:11, in the addition alone: its result also lists what the stopped activation set up that is still live, each task by its `T` label with its due time and author and each activation running below by its episode label, or says nothing is (ADR-0352 §3:1–§3:6). §4:6, §4:8, §6:1 and §6:5, each in the addition alone: a running activation a stop call's result showed may be named by the stop call and the look-up (ADR-0352 §3:7). §7:14, in the addition alone: once the round may run, its answer calls run first and alone, and where an answer that asked to take did not come to a take, none of the round's other calls that are not pure reads, and not its message, is dispatched (ADR-0352 §4:1–§4:3). §1:5's case of a stop call whose cascade cancels the task: the task stays pending and the result lists it (ADR-0352 §7:4). Every other clause stands. This replacement takes effect on ratification of ADR-0352. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §5:6's list, in the addition alone: each entry also shows when its input arrived (ADR-0353 §2:5). §5:7, in the addition alone: an `R` label may be cited in `cites`, where it resolves to a `running` referent holding the activation's episode id and its input in brief, and in `belongs_to`, where it links to that activation's matter, and only `meant_for` makes the input part of that work (ADR-0353 §10:1–§10:4). §7:3's and §10:1's `continues`, the proposal's field, in its name alone: `meant_for` (§9:2), and §7:3 in the addition alone: an input is meant for work that, carried on without it, would now do the wrong thing or something no longer wanted (§10:5). §10:2's *the proposal's labels*: `meant_for`'s; the recorded `continues` keeps its name and shape (§9:4); and its *as a grounding defect (ADR-0276 §6)*, in the repair alone: a label that resolves to no shown activation is dropped and counted, never a parse failure, with no repair (§9:11). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §4:6 and §7:26, each in what is offered alone: every capability is offered on every round, the stop call and a waiting round's included, and a call whose condition does not hold, such as a stop call without the person's authority or any call on a waiting round but the stop call naming the work waited on and a message call, comes back refused, saying why, and runs nothing (ADR-0356 §4:3–§4:5). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0357 — §7:19's *Planning's instruction says, in one line*, in where it is said alone: `answer_offer`'s description says it (ADR-0357 §7:1–§7:3). What the line says is unchanged by ADR-0357. Every other clause stands as its other records leave it. This replacement takes effect on ratification of ADR-0357. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0360](0360-the-news-also-reports-the-time-other-works-starting-and-ending-and-what-the-person-newly-chose-to-keep-in-mind.md) — §5:2's *understanding alone* and §5:9's *Planning is not shown the section*, for planning's exchange alone: planning is shown the in-progress section in its briefing, as ADR-0356 §3's concurrent stimuli, and each activation that starts or ends after it in a report's news, under §5:2–§5:5's rules and §5:10's limit (ADR-0360 §3). §5:1's *No rule pushes one activation's findings into another's* gains that news as its one exception, for planning's exchange: a started activation's entry and meaning, and an ended one's short view (ADR-0356 §9), under the section's rules and the view's filters (ADR-0360 §3:6). None of the three is replaced for any other stage. Every other clause stands. This replacement takes effect on ratification of ADR-0360. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

In this document a bare section reference, such as §7:5, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0332 §3:2.

**The owner's question, 2026-10-21.** *"What if there was some basic operations that can be
done in parallel activations, such as merging … Or do these operations merge, fork, split,
cover, essentially anything that could happen?"* The walk that followed, from 2026-10-21 to
2026-10-24 on proposal #3384, narrowed that to three operations, spawn, stop and share,
with merge as a share and a stop in one step. Along the way the owner set the principles the
rest follows:

- **Spawned work is ordinary.** *"Things like the reminder or background task are just normal
  activations that might have spawned from a certain conversation, but they don't live
  there."*
- **A place ties an activation to nothing.** It is only what caused the activation. An
  earlier draft gave each activation a home place, for its window, its "working…" and its
  stop. The owner dropped it.
- **The newest decides.** *"The newest activation has the most up-to-date information, and
  therefore it should be the choice of the newest activation."*
- **Do the simple version.** *"For now, do a simple design that works. Don't worry much about
  who and what and privacy. That stuff will be addressed later."*

**What it assumes.** Outside content, disclosure (who may see what) and authority (approvals)
are other designs, and this decision assumes they work. Whatever crosses between activations
carries its author, its authority and its marks. The gaps those designs must close are named
in §11. The owner: *"Just note that the gaps need to be closed."*

**What the code does today, at `77ac3671`,** with ADR-0350's lanes TS1, TS1b and TS2
merged.

- **One activation at a time within a place, with joining** (ADR-0332 §2:3–§2:5, §3). A new
  input on a place joins the activation running there until it commits
  (`Engine._join_running`, `orchestration/joining.py`), pending the reader's marking
  (ADR-0343). Anything else waits.
- **A takeover across places** (ADR-0332 §4). Understanding is shown the same person's
  running activations on their *other* places, under `R` labels, and may name one it
  `continues`. The takeover stage (`Engine._takeover_stage`) stops that one and takes
  its input, where it has not committed.
- **One stop** (ADR-0295, ADR-0297), the Task Manager's (ADR-0350 §10:3). The hub chat's
  stop control reaches `AssistantEngine.stop_activation`, and the line's `/stop` reaches the
  same engine step through its reader (`orchestration/telegram.py`). That step writes the
  cascade record and stops what is live below the activation (ADR-0350 §9:6,
  `TaskManager.cascade` in `orchestration/task_manager.py`). A conversation's current state
  names one running activation (`ConversationState.activation_id`).
- **Planning has the Task Manager's cancel and replace, and no stop** (ADR-0350 §4:1,
  §10:4). Its three calls on the Task Scheduler are spawn, cancel and the list pull
  (`ScheduledTaskCalls`).
- **Planning sees running work only in the list pull.** Its running part
  (`TaskManager.running`) shows each activation running for the person, other than the
  asker, by its input in brief, oldest first, under the listing bound (ADR-0350 §4:6).
  Planning's episode window skips every open episode (`orchestration/planning.py`,
  `_Request._episodes`), and no model reads an open episode (ADR-0286 §6:4).

**What this reverses.** The controller walk's answer 1 on #3257, which ADR-0332 converted,
chose one activation at a time within a place. The owner reverses it here, and with it the
walk's later answer on #3384 that a conversation waits once something running in it has
acted. The owner, 2026-10-25: *"didn't we just separate the activation from the place? feel
like there's a cleaner solution here"*. So no place waits: every message starts its own
activation (§8), and the waiting moves into §7, as a relation between activations that
understanding judges. After the older has acted, the matter goes to it with its consent:
*"the first activation can reply to the second one saying whether it feels comfortable.
Continuing that work, in which case the second activation can end, or it can respond with,
I can't continue this, I've gone too far. It's better if you just do it after I end."*
Those answers are walk records, not ADRs, so they are stated here rather than superseded.

**What ADR-0292 already owes.** ADR-0292 §11:2–§11:3 put understanding in charge of how a new
activation relates to running work, with merging and taking over as one mechanism. ADR-0292
§11:4 says the end state owes, before it runs, "waiting once, before an action, for the
user's inputs not yet understood". Without that wait the newest cannot decide: an older
activation could act on "book Saturday" before the newer "actually Sunday" was understood.
§7:12–§7:14 build it.

## Decision

We will treat a place as only what caused an activation. Activations act on each other by
four operations: spawn, which ADR-0350 decides; stop; share; and merge, which is a share and
a stop in one step. A stop is reached from outside, by a merge, or by planning, which is
given the Task Manager's stop beside its cancel and replace. Every running activation for a
person is shown to understanding, which names what its input continues. Planning is shown no
section: it pulls ADR-0350's list of what is running and looks up a running activation's
findings. Each of these
reads open episodes through one read function. One matter is one activation. Every message
starts its own activation, and no place holds one back. Before the older acts, the newest
absorbs it, and an activation about to act waits for newer input to be understood. After
it acts, the older is offered the new input: it takes it, and the newer ends silent, or it
declines, and the newer does its own work once the older has ended.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner has ratified
> it after their own review. An assigned number or a green review alone does not change its
> status.

> **Normative.** No lane implements this decision before it merges `Accepted`.

> **Normative.** This decision stands on ADR-0350 as merged `Accepted` (#3419), and §1:4's
> steps build on ADR-0350's lanes as they merged: the Task Manager, its stop's cascade and
> planning's calls on the Task Scheduler (#3432).

> **Normative.** The implementation ships as separate pull requests in this order.
>
> 1. **`core`, `wire`, `testing` and `memory`, permitted expressly here as one unit.** §10's
>    types and §9's two new settings; the one read function (§6:7) in
>    `core/episode_encoding.py`; the `PROTOCOL_VERSION` advance with the wire surface and
>    type closure; and the episode store's upgrade under ADR-0326 §4:1–§4:2 for §10:6's
>    change. It also adapts, with no change in behaviour, each place in `orchestration` and
>    `interfaces` that builds or reads `ConversationState` or either understanding type's
>    `continues`: `activation_ids` names the one activation the state names today, and
>    `continues` holds at most the one label or activation it holds today, and is empty
>    where it holds none, a continuation being a non-empty `continues`. `join_limit` stays
>    until step 2.
> 2. **`orchestration`, the activation:** understanding's `continues`; the in-progress
>    section for understanding (§5); the findings look-up and its declaration,
>    and the running part of ADR-0350's list pull (§6); planning's stop call, its
>    declaration and its result (§4:6–§4:12); the takeover stage as §7 restates it; the
>    waits before a takeover and before every act, the commitment step and the re-plan
>    (§7:12–§7:16); the offer, the answer call, the waits on an older activation and the
>    waiting round (§7:17–§7:29); and the removal of joining by code, with `join_limit`
>    (§9:1) and its wiring in `app/`.
> 3. **`orchestration`, the readers:** `ChatReader` and `TelegramReader` shrink to the start
>    wait for every message (§8:1–§8:2), what they hold in it for the first act's wait
>    (§7:12), and the line's `/stop` for every running activation (§4:3). Neither holds a
>    message back for running work.
> 4. **`interfaces`:** the hub chat page's stop control for every activation its
>    conversation's state names (§4:3).
>
> Step 2 depends on step 1, step 3 on step 2, and step 4 on step 1.

> **Normative.** The tests of the step that builds each include these cases:
> - two newer activations name the same older one, with the newer of the two finishing its
>   understanding first and then last: in both orders the older of the two absorbs it
>   first, and the newer follows forward and absorbs that one, where it has not committed;
> - A finishes a look-up and records its findings, B absorbs A, and C absorbs B before B
>   plans: C's planning is shown A's findings, read from A's episode, and B's;
> - an older activation reaches its first act while a newer one for the same person has not
>   recorded its understanding: it waits, the newer absorbs it, and it dispatches nothing;
> - an older activation reaches its first act while the correction is still held in its
>   place's start wait: it waits for the correction's activation, which absorbs it;
> - planning's stop call naming a committed activation that spawned a task still pending:
>   the activation is stopped, the cascade cancels the task, and the result shows the
>   stopped activation's finished work;
> - the same call from an activation whose input does not carry the user's authority, which
>   is refused and stops nothing;
> - a stop call naming a label planning was never shown, and one naming a label shown for
>   no running activation, each refused whole;
> - a stop call naming an activation absorbed since it was shown, which is refused, stops
>   nothing and names its absorber;
> - a stop call whose activation then waits before its first act (§7:12), while a newer
>   input continues it: the newer absorbs it, and nothing is stopped;
> - an activation that failed before its first round and wrote *couldn't finish*: a
>   findings look-up shows that fixed line with its outcome, and nothing else it did;
> - two older activations on different places, neither yet understood, and a newer input
>   continuing one of them: the in-progress entries show each one's input, and only the
>   one named is absorbed;
> - a message on a place where a running activation has acted starts its own activation at
>   once, and one that continues nothing never waits;
> - an offer taken: the offering activation ends writing no message, and the older's reply
>   covers both inputs;
> - an offer declined: the offering activation's waiting round is shown the reason, it waits
>   for the older's end, and then plans from the older's finished work;
> - the older ends without answering an offer, which counts as a decline;
> - a newer input continuing an activation that has acted on another place: no offer is
>   made, and the newer waits on it, or its waiting round stops it;
> - a take refused at `held_input_limit`, which counts as a decline;
> - an offer that follows forward from an absorbed activation to the absorber that has acted;
> - an activation that has acted is about to book, and the person's correction on the same
>   place arrives during its planning: the booking is not dispatched, the offer is answered,
>   and the booking goes out corrected;
> - an input arriving during an act's wait is not waited for;
> - an activation that has acted reaches an act while a newer input on another place runs:
>   it does not wait;
> - re-plans for offers stop once the older's held inputs and the offers made to it that it
>   did not take reach `held_input_limit`, with successive offers arriving while it answers,
>   and with an offer withdrawn and made again by an absorber while its answer is planned;
> - an offer made while the older's round is being planned, before its act's wait begins:
>   the round's acts are held back and planning runs again with the offer shown;
> - a waiting round that writes only its message: the activation does not end, and plans
>   its work once the older has ended;
> - a newer input naming an activation whose input was taken: it follows the hand-over to
>   the activation that took it;
> - an activation with an open offer absorbed by a newer one: the absorber makes the offer
>   again, with every input it holds;
> - an input continuing two activations that have acted: no offer is made, and it waits on
>   both;
> - an absorption refused at `held_input_limit`, at a limit of 1 and at an exhausted one;
> - the read function shows no stage in progress, no dispatched-but-unfinished call, and
>   nothing the activation read from another.

### 2. A place is only what caused an activation

> **Normative.** An activation's place is the place its input came from (ADR-0292 §5:1), and
> it ties the activation to nothing else. No activation has a home place.

> **Normative.** An activation's context is its windows, recall, its stories and the
> in-progress section understanding is shown (§5). Another place's recent messages reach
> it only by a pull of that place (ADR-0292 §6:3), where the place's kind declares one;
> this decision declares none.

> **Normative.** Whether a place shows running work and offers a stop is its kind's
> declaration (§4:13), and not part of the general model.

> **Normative.** Admission and the reply a conversation expects stay the rules of the kind
> of the place that caused the activation. Waiting is no kind's rule: an activation waits
> only on another that its input continues (§7:25, §8:1).

Speaking into a place other than the input's is an act like any other call, and that is
decision C's, its own track (§11). Until it lands, ADR-0306 §4:7 stands: the round's own
message goes only into the place the input came from.

### 3. The operations

| Operation | What it is |
| --- | --- |
| **Spawn** | An activation sets up another, to start now, later or after other tasks end. ADR-0350 decides it. |
| **Stop** | ADR-0295's stop, unchanged: nothing new starts, what is in flight finishes and is recorded, nothing new is written, and nothing is abandoned or undone (§4) |
| **Share** | An activation sees what the others are doing, and can fetch what they found (§5, §6) |
| **Merge** | A share and a stop as one step. Before the older acts, the newest takes in its input and findings, and the older is stopped. After it acts, the older may take the newest's input, offered to it, and the newest is stopped (§7) |

> **Normative.** One activation acts on another only by the four operations the table names.

> **Normative.** Spawning is ADR-0350's, and this decision decides nothing of it.

> **Normative.** Start is not an operation. Every activation begins from an input its place's
> sensor took in and admission admitted, whether a message, an email or a scheduled task
> coming due, and no activation begins another except by spawning.

> **Normative.** Once an activation has committed, nothing is absorbed into it, and only an
> input offered to it and taken joins it (§7:17–§7:24). Anything else that comes after is a
> new activation, which reads the records, and waits on it where it continues it (§7:25).

> **Normative.** For every rule of this decision, an activation has **acted** exactly when
> acting has committed it under ADR-0332 §3:2, a pure read being what ADR-0341 §2:1 defines.
> The committed mark an absorption or a take sets (§7:7, §7:21) is not an act.

That is how a correction after a reply works today, and it stays so. Fork, split, suspend
and "kill" were considered and are not operations (Alternatives).

### 4. Stop

**One operation.**

> **Normative.** Every route in this section stops an activation by ADR-0295's stop, as
> ADR-0297 records it: it names exactly one activation, sets its stop mark and then writes
> its stop record (ADR-0297 §3:3–§3:4), and the stopped activation carries every guarantee
> of ADR-0295 §§2–4.

**From outside.**

> **Normative.** From outside, a stop is the Task Manager's stop command, which ADR-0350
> decides.

> **Normative.** The hub chat's stop control sends a stop for each activation its
> conversation's current state names as running, and the line's `/stop` stops each
> activation started from the line's chat that is running. Each is a shortcut to the one
> stop.

> **Normative.** A conversation's current state names every running activation started
> from it whose id is known (§10:3).

**By a merge.**

> **Normative.** An absorbed activation is stopped as a taken-over one is (§7:7, ADR-0295
> §5:1). That stop stays internal: it is not the Task Manager's stop command, writes no
> cascade record and walks nothing (ADR-0350 §9:6).

An absorbed activation has spawned nothing. Only an uncommitted activation is absorbed
(§7:5), and a spawn commits its activation (ADR-0350 §4), so there is nothing below it to
cascade to.

**By planning.** "Never mind the booking," said on Telegram after the web activation has
booked.

> **Normative.** Planning is offered the Task Manager's stop (ADR-0350 §10:2) as a call
> of its own, the **stop call**, where its activation's input carries the user's authority
> (ADR-0292 §5:5). The call names one running activation by the label planning was shown it
> under as running (§5:7): a running entry's in a list pull this activation made (§6:2), an
> offer's (§7:19) or a wait's (§7:26). Its exact name and arguments are the lane's that
> builds it (§1:4's step 2).

> **Normative.** The stop call is declared as ADR-0350 §4:1 declares the cancel of a
> scheduled task: the assistant's own records, never leaving the hub, an outcome never
> unknown, safe to repeat, the person's tier in `writes`, and a result with no outside
> text. It is checked by rule as every call is (ADR-0306 §4). Acting runs it directly,
> awaited to its end and never through `ToolInvoker`, as the Task Manager's stop with
> ADR-0350 §9:6's cascade, by the one implementation `AssistantEngine.stop_activation` runs
> (ADR-0350 §10:3–§10:4).

> **Normative.** A stop call is refused whole as *not done*, with the reason, and stops
> nothing, where its activation's input does not carry the user's authority; where it names
> a label planning was never shown (ADR-0307 §5:3); and where the label it names was not
> shown for a running activation in a list pull's running part, an offer or a wait.

> **Normative.** Where the activation named was absorbed since it was shown, the call is
> refused as *not done* and stops nothing, and its reason says that it was absorbed, and
> by which activation, under that activation's label. It is not followed forward.

> **Normative.** Where the activation named has otherwise ended or been stopped since it
> was shown, the call stops nothing, and its result says so (ADR-0295 §1:6).

> **Normative.** Where the stop call stopped the activation, or found it ended or stopped
> under §4:10, its result shows that activation's finished work through §6's peer view
> (§6:7–§6:10), so that the round's message can say what had finished.

> **Normative.** A stop call is an act (§3:5). It commits its activation, so §7:12–§7:14's
> wait and commitment step come before it.

The message stays input, and becomes no command (ADR-0292 §12:5–§12:6, ADR-0350 §10:5):
planning chooses the call, authorizing checks it, acting runs it and the record keeps it, as
ADR-0292 §12:2 has every inside action. ADR-0350 §10:4 already has planning use the Task
Manager's cancel and replace, and the stop was the one command missing. A forward, a reminder
or a message whose author is not established carries no user's authority, so it stops
nothing. "Go on" afterwards takes it back, because a stop abandons no goal (ADR-0295 §4:1).
This is the item ADR-0332 §9 left to #2515.

Where the work named has not acted, the newest usually absorbs it instead, since an input
that cancels work continues it (§7:3). The stop call is for work that has acted, and for work
no input of the person's can absorb, such as a step the Task Scheduler started. "Stop the
apartment search" while a step runs is one stop call, and the cascade cancels the step's next
task, so a running step that would spawn again after its next task was cancelled in words is
stopped first (ADR-0350 §14).

**An activation absorbed since it was shown is refused, not followed.** The takeover stage
follows an absorbed activation forward because it runs in code on the newest's own
understanding, oldest first (§7:15). Planning's call was judged on what planning was shown,
and the absorber holds newer input, which may be the user's correction after the words. The
newest decides (§7), so the call is refused, its reason names the absorber, and the next
round can pull the list (§6:2), which shows the absorber with its input. Planning stops it by
its label if the words still mean it.

**Committing the stopping activation.** The stop writes the plan store's stop and cascade
records, so it is not a pure read (ADR-0341 §2:1), and it is not undone. Committed, the
stopping activation can no longer be absorbed, so no newer input takes over a matter after
part of it was cut. Before the call, §7:12's wait gives a newer input the chance to absorb
it: "never mind the booking", then "no, keep it" a second later, and nothing is stopped.
After the call, a newer input that continues the stopping activation is offered to it or
waits on it (§7:17), as after any act.

Within one place, "never mind" after the work has acted continues it, so it is offered to the
older (§7:17), whose planning, taking it, stops doing more and says what had finished. The
stop control stops it at once. Across places no offer is made, and the newer's waiting round
may stop the older with the stop call (§7:26).

**What a place shows.**

> **Normative.** A kind declares whether its places show running work and offer a stop. The
> conversation kind declares "working…" and the stop control (ADR-0293 §8:2, ADR-0295 §1:2);
> the line declares typing (ADR-0323 §6:8) and `/stop` (ADR-0332 §8); the Task Scheduler's
> declaration is ADR-0350's.

> **Normative.** A place shows running work, and offers a stop, only for the activations it
> caused.

So a spawned activation speaking into a conversation was caused by the Task Scheduler, and it
is stopped by words or through the Task Manager. Whether an activation is running is still
never written into the medium (ADR-0292 §11:7).

### 5. Share: understanding's in-progress section

**No supervisor.** An earlier draft had rules that pushed findings between activations: the
same story, the same person, lineage. The walk replaced them with what follows, built mostly
from what exists.

> **Normative.** No rule pushes one activation's findings into another's. Understanding
> learns of other activations only through §5's section, and planning only as §5:9 states.

> **Normative.** Understanding, and understanding alone, is shown, beside its window, an
> **in-progress section**: one entry for each activation running for the same person whose
> stop mark is unset, other than this one, on any place, the activations ADR-0350's Task
> Scheduler started included.

> **Normative.** The same person means that both inputs' authors are established as that
> person (ADR-0332 §4:1). For an activation the Task Scheduler started, its person is the one
> its scheduled task is for, as ADR-0350 records it.

> **Normative.** An activation is entered in the section only where
> `admitted_to_understanding` (in `orchestration/disclosure.py`, ADR-0276 §4) would admit an
> episode of its place to this pass.

> **Normative.** No activation is entered in the section of an input whose author is another
> person or is not established.

> **Normative.** Each entry shows exactly, in version 1:
> - a label;
> - what caused it: its channel and its place;
> - what it took in, in brief, through §6's read function, so that outside input never
>   appears raw;
> - whether it has acted.

> **Normative.** Understanding labels the entries with `R` labels (ADR-0332 §7:3). Planning
> names a running activation by the episode label of its episode (ADR-0307 §5:1), wherever
> it is shown one.

> **Normative.** Understanding is shown the section as it stands when its call is rendered.

> **Normative.** Planning is not shown the section. It learns of running work only through
> ADR-0350's list pull and its running part (§6:2), the findings look-up (§6:1), the offers
> open to it (§7:19), and what an absorption (§7:10), a wait (§7:26–§7:27) or a stop call's
> result (§4:11) shows it.

> **Normative.** The section shows at most `in_progress_limit` entries (§9:3), newest first,
> and says how many more are running.

The section is understanding's because understanding is one model call with no tools: it
can name in `continues` only what it is shown. Planning has calls, so it is given a
capability rather than a list: it pulls what is running when the matter needs it, and looks
up what one found. A section in every round of planning would be awareness only, cost every
round its length, and act on nothing. Running work reaches a planner that needs it as an
offer (§7:19), an absorption (§7:10) or a wait (§7:27), each of which planning acts on.

### 6. Share: the look-up, the list and the one read function

**The look-up and the list.** Planning pulls what is running, and looks up what one has
found.

> **Normative.** Planning may look up the findings of a running activation, by the label it
> was shown it under as running (§5:7): in a list pull's running part, an offer or a wait.
> "What has the flight search found?"

> **Normative.** The list of what is running is ADR-0350's list pull: "what are you doing
> right now?" Its running part lists each activation the section would enter (§5:2–§5:5),
> each as §5:6's entry shows it and under its episode label (§5:7), bounded by ADR-0350's
> listing bound (ADR-0350 §12:5) in place of §5:10's limit.

> **Normative.** What is scheduled and what ran lately reach planning as ADR-0350's list
> pull decides, and this decision adds nothing to them.

> **Normative.** The findings look-up's capability declares its effect as the assistant's own
> records, that it does not leave the hub, a result with no outside text, an outcome that is
> never unknown, that it is safe to repeat, and an empty `writes`, as reading a story does
> (ADR-0306 §3:1). It is a pure read (ADR-0341 §2:1) and commits nothing.

> **Normative.** A findings look-up naming a label that was not shown for a running
> activation in a list pull's running part, an offer or a wait is refused whole, with
> the reason, and runs nothing, as ADR-0307 §5:3 refuses a label never shown.

> **Normative.** Where the named activation has ended since it was shown, the look-up shows
> its finished work and says that it has ended.

**The one read function.**

> **Normative.** One read function renders every model-facing read of an episode: it is
> `project_episode` in `core/episode_encoding.py` (ADR-0284 §8:1), extended with a **peer
> view**. The in-progress entries, the findings look-up, the running part of ADR-0350's list
> pull, an absorbed activation's findings (§7:10), the finished work of one waited on
> (§7:27), the input an offer shows (§7:19) and a stop call's result (§4:11) read the peer
> view (§6:8–§6:10). Recall's rendering keeps its projection, as ADR-0284 §8:1 and
> ADR-0308 §3:1 rule it.

> **Normative.** The peer view is computed from two records alone: the activation's episode
> as stored, open or frozen, and its effect records, which orchestration reads from the
> plan store (`PlanStore.activation_effects`, ADR-0306 §6) and hands to the pure function.
> Of an open episode it shows only what its stages appended when they ended (ADR-0286
> §3:1), and of the effect records only those whose outcome is written: never a stage or
> round in progress, and never a call or message not yet finished.

> **Normative.** Of another activation's work, the peer view shows only that activation's
> own work:
> - what it took in: its input, as `project_episode` renders it with `admit_outside_input`
>   false, cut to its excerpt bound, so that outside input is withheld (ADR-0284 §8:1);
> - what it is doing: its latest understanding's meaning, rendered as provisional
>   (ADR-0276 §4:6), where one is recorded;
> - what it found: its rounds' episode notes (ADR-0307 §4) and its digests' answers with
>   their evidence, each item with its mark (ADR-0308 §5:5);
> - what it did: each of its effect records (ADR-0306 §5:3) whose outcome is done or
>   unknown, each with that outcome: a call shown by its capability; a message by the
>   message of the round the record names; and the *couldn't finish* message, whose record
>   names no round (ADR-0307 §10), as a fixed line saying the activation could not finish.

> **Normative.** The peer view never shows another activation's recall results, story
> links, failed calls, drafts or approvals, nor anything that activation read from another:
> the in-progress section its understanding was shown, its look-ups and list pulls of
> others, and the findings it absorbed, an offer, a wait or a stop call's result showed
> it.

> **Normative.** No call's result is added to an episode for a share. A result that was not
> digested reaches another activation only as the episode notes of the activation that
> called it record it (ADR-0307 §4:2).

> **Normative.** Nothing a share shows authorizes anything. It reaches the reader as
> information carrying no authority, no approval is shown, and an approval is used only by
> its yes's activation (ADR-0321 §4:1).

> **Normative.** Planning is shown every activation a share shows it under that activation's
> episode label (§5:7), and an outside episode (ADR-0303 §3:2) shown so counts in the
> reader's record of what it read, as any episode planning is shown under a label counts for
> ADR-0306 §4:5. So an activation shown another that has read outside content has read
> outside content, and ADR-0306 §4:4's stand-in applies to it.

Because a peer is shown only its own work, nothing echoes back and no reads chain. The
authorizing boundary holds across a share by §6:13, and the episode notes and evidence the
view shows carry their marks as recall shows them. One read function means the gaps §11
still names are closed in one place when they are closed.

### 7. Merge: one matter, one activation

One matter, one activation. Before the older acts, the newest absorbs it. After it acts, the
older is offered the new input, and takes it or declines.

> **Normative.** A merge is a share and a stop in one step: one activation takes in
> another's input and finished findings, and the other is stopped. Before an older
> activation has acted, only a newer one absorbs it (§7:4–§7:11). After it has acted, it
> may take a newer one's input, offered to it (§7:17–§7:24). No activation takes on
> another's input except by absorbing it (§7:5) or taking an offer (§7:21).

> **Normative.** Every input starts its own activation, after its place's start wait
> (ADR-0332 §5), whatever else runs (§8).

> **Normative.** Understanding's reply may name, in `continues`, the shown running
> activations its input continues: whose work it **corrects, completes, cancels or changes**.
> An input that asks for separate work on the same matter continues none.

The newest's understanding sees the older ones in its in-progress section, and, within one
place, their messages in its place window too. "What's the weather there?" while a
hotel search runs is separate work: kept separate, the weather comes back first, each runs on
its own, a failure stays contained, and each reply lands where it was asked.

> **Normative.** The takeover stage, once for each understanding version that names any
> activation in `continues` (§10:8), first waits as §7:15 states. Then, in one step with no
> await between, it follows each activation named forward, while it has been absorbed or
> has had its input taken, to the activation that absorbed it or took its input; absorbs
> those it reached under §7:5–§7:7; and offers its input to, or waits on, those it reached
> under §7:17.

> **Normative.** In that step the stage absorbs each activation it reached from `continues`
> where all of these hold:
> - it started before this one;
> - it is running, it has not committed, and its stop mark is unset;
> - its input's author is this input's author, established in the same way, and its input
>   carries the same authority (ADR-0292 §5:5) and the same origin (ADR-0284 §2:2).

> **Normative.** Where absorbing every activation that qualifies under §7:5 would bring the
> inputs this activation holds above `held_input_limit` (§9:2), the stage absorbs none of
> them and records the decision *not taken*.

> **Normative.** To absorb an activation, the stage, in that one step, sets its stop mark and
> its committed mark, so that it can neither commit nor be absorbed by another; records that
> this activation absorbed it; and appends every input it holds to this activation as a
> `JoinedInput` naming it. It writes the absorbed activation's stop record after the step,
> as a stop does (ADR-0297 §3:4).

> **Normative.** The stage records, for the version, each activation named and what became
> of it (§10:4).

> **Normative.** The understanding version that named an activation in `continues` covers
> every input absorbing it brought, and the meaning an offer carried covers every input a
> take brings the older (§7:21), so `not_understood` (ADR-0332 §3:9) does not answer for
> them.

> **Normative.** Planning of an activation that took in another's input by a merge is
> shown, at every round, the finished findings of each activation it absorbed or whose
> offered input it took, and, in turn, of each activation one of those had absorbed or
> taken. Each is read fresh through §6's read function from that activation's own
> episode, so findings an absorbed activation had taken in reach the reader from their
> source, never through the activation that held them (§6:10).

> **Normative.** A merge does not extend the deadline of the activation that takes in the
> other's input.

A look-up in the hub's own records is not acting, so an older activation may have done real
work before it is absorbed, and the merge keeps it. Work it had started finishes after the
stop and is recorded on its own episode (ADR-0297 §4:9), which is why §7:10 reads it fresh.
Only the newer absorbs the older, so there are no cycles. "Joining" and "takeover" stop being
two mechanisms: within a place and across places, the newest absorbs.

**Every act waits for the newest.** The newest can decide only if the older does not act
first.

> **Normative.** Before acting dispatches any call of a round that is not a pure read, or the
> round's message, the activation waits for each newer input that, once understood, could
> absorb it or offer to it. Before it has committed, that is each activation that started
> after it, is running for the same person, and whose input has this input's author,
> authority and origin, on any place, and each such input that a reader of one of that
> person's places holds in its start wait. After it has committed, that is each such
> activation caused by its own place, and each such input its own place's reader holds. It
> waits until each activation, and each held input's activation once admitted, has ended, or
> has recorded its first understanding version or its omission and, where that version
> names any activation in `continues`, the takeover stage's decision for it; and until each
> held input not taken in is released. What it waits for is what runs, and what is held,
> when the wait begins.

> **Normative.** That wait is bounded by the pass's deadline. Where it reaches the deadline,
> acting dispatches none of the round's calls and not its message, and ends as a stage whose
> deadline expired during it (ADR-0280 §5:1).

> **Normative.** The step after the wait follows it with no await between, and in one step:
> where the activation's stop mark is set, acting dispatches none of the round's calls that
> are not pure reads and not its message; where an offer is open to this activation that
> this round's planning was not shown (§7:19), made before the wait or during it, acting
> dispatches none of them either, and planning runs a round again, shown the offer, which
> counts toward the round limit; and otherwise, where the activation has not committed, it
> marks the activation committed.

This is ADR-0292 §11:4's "waiting once, before an action, for the user's inputs not yet
understood", before every action. A reader holds an input in its start wait for a second or
two, so the wait covers a correction typed just before the act, not only one already
started. Before the activation commits, a newer input on any place could absorb it, so the
wait reaches every place. After it commits, only an offer could reach it, and offers stay
within one place (§7:18), so the wait reaches its own place alone.

**It cannot be paused forever.** Three bounds hold however many activations keep coming.
What an act waits for is fixed when the wait begins, so an input that arrives during the
wait is not waited for. The wait is bounded by the pass's deadline (§7:13). And a re-plan
happens only for an offer, and no offer is made to an activation whose held inputs and the
offers made to it that it did not take reach `held_input_limit` (§7:22). Each re-plan needs
an offer the round was not shown, and each offer counts toward that limit from the moment
it is made, and keeps counting whether it is then declined, withdrawn or made again by an
absorber, so an activation re-plans for offers fewer than `held_input_limit` times. Past
that, newer input waits on it instead (§7:25).

**Takeover decisions are made oldest first.** Two newer activations may continue the same
older one, and the newest may finish its understanding first. Were it to absorb first, the
middle one would follow forward to an activation newer than itself, which it cannot
absorb, and both would go on to act on one matter.

> **Normative.** Before its step (§7:4), the takeover stage waits, once, for each older
> activation running for the same person whose input has this input's author, authority
> and origin, until each has ended, or has recorded its first understanding version or its
> omission and, where that version names any activation in `continues`, the takeover
> stage's decision for it. What it waits for is what runs when the wait begins.

> **Normative.** That wait is bounded by the pass's deadline. Where it reaches the deadline,
> nothing is absorbed or offered, and the stage ends as a stage whose deadline expired
> during it (ADR-0280 §5:1).

So whoever absorbed a named activation is older than the activation following it forward,
and the newest still absorbs last. No two wait for each other. A takeover waits only on
older activations' takeover decisions, which each records in its step, before it plans, so
before its first act. An act waits only on newer ones. A takeover never waits on an act.

**After the older has acted: the offer.** "Only two bedrooms," while the apartment search
has already saved a shortlist. The search cannot be absorbed, because it has acted. Its
planning knows what it has done, so it is asked.

> **Normative.** In the takeover step (§7:4), an activation reached from `continues` that has
> acted (§3:5), started before this one, is running with its stop mark unset, and meets
> §7:5's third condition is **offered** this activation's input, where both were caused by
> the same place: every input this activation holds, with the meaning its understanding
> version recorded. Where they were caused by different places, or where the step reaches
> more than one activation under this clause, no offer is made, and this activation **waits
> on** each (§7:25).

> **Normative.** Until decision C (§11) lets an activation speak into another place, an
> offer is made only within one place, since the older's message goes only into the place
> its own input came from (ADR-0306 §4:7).

> **Normative.** At the start of each of its rounds, the older's planning is shown each
> offer open to it: the offered input, shown as an in-progress entry shows input (§5:6),
> with the meaning the offering activation's understanding recorded, under the offering
> activation's episode label (§5:7). Planning's instruction says, in one line, to take an
> offer unless it has already done something the offered input would change that cannot be
> undone.

> **Normative.** Planning answers an offer by the **answer call**: take it, or decline it
> with a short reason, naming the offer by the offering activation's label. The call is
> declared as the stop call is (§4:7) and checked by rule as every call is (ADR-0306 §4).
> A call naming a label that names no offer open to this activation is refused whole, as
> *not done*, with the reason.

> **Normative.** A take, in one step with no await between, where the offering activation is
> running with its stop mark unset: appends every offered input to the older as a
> `JoinedInput` naming the offering activation; sets the offering activation's stop mark and
> committed mark; and records the hand-over in both activations' takeover decisions. It
> writes the offering activation's stop record after the step, as §7:7 does, and that stop
> is §4:5's: internal, with no cascade. The offering activation ends writing no message
> (ADR-0295 §3:3).

> **Normative.** Where a take would bring the inputs the older holds above
> `held_input_limit`, it is refused and counts as a decline, with that reason. No offer is
> made to an older where the inputs it holds, with one for each offer ever made to it that
> it did not take, open, declined or withdrawn, reach `held_input_limit`: this activation
> waits on it instead (§7:25). Where the offering activation is no longer
> running with its stop mark unset, the offer is withdrawn and the take changes nothing.

> **Normative.** A decline's reason is recorded in the offering activation's takeover
> decision, and shown to its planning (§7:26).

> **Normative.** An offer stays open until the older's planning answers it, or the older
> ends. An older that ends, or is stopped, without answering has declined it. An activation
> that absorbs another takes on, in the same step, what the other had reached under §7:17:
> the other's open offer is withdrawn and made again by the absorber, with every input it
> holds, under §7:17 and §7:22, and the absorber waits on each activation the other waited
> on.

**Waiting on an older activation.** Where the older declines, or no offer could be made,
the newer one does its own work only once the older has ended, and then from what it
finished.

> **Normative.** An activation **waits on** each activation it reached under §7:17 that
> declined its offer or was offered nothing (§7:17, §7:22). It plans its own work only once each
> activation it waits on has ended, stopped included. While its offer is open, its planning
> runs no round.

> **Normative.** Where, once its offer is no longer open, it waits on an activation still
> running, its planning's first round is a **waiting round**, which never ends the
> activation, whatever calls it made. That round is shown each
> activation it waits on, as an in-progress entry shows one (§5:6) and under its episode
> label (§5:7), and the decline's reason, where there was one. It is
> offered only the stop call, naming an activation it waits on (§4:6), and may write the
> round's message. Its next round runs only once each activation it waits on has ended,
> whether or not the waiting round made a call (ADR-0315 §2:1–§2:3).

> **Normative.** Planning of an activation that waited is shown, at every round after the
> wait, the finished work of each activation it waited on, read fresh through §6's peer
> view, as §7:10 shows absorbed findings.

> **Normative.** The time an activation spends in §7:25–§7:26's waits does not count
> against its pass's deadline: its deadline is moved later by the time waited. The waits
> are bounded by
> each older activation's own end, which that activation's own deadline and round limit
> bound.

> **Normative.** An activation whose understanding names no running activation in
> `continues` never waits on one.

The waiting round is where the newer one says, if it should, that it will carry on after
the older: "I'll filter to two bedrooms once the search finishes." Across places it is also
where planning may stop the older and take the matter over, with the stop call (§4:6): the
wait then ends with the stop. A message in the waiting round is an act (§3:5), so §7:12's
wait comes before it.

Only the newer offers or waits, and only on older ones, so no two wait on each other. An
activation offers to at most one: where its input continues two pieces of work that have
acted, a take by one would leave the other going on with no one to wait on it, so it waits on
both. A hand-over is followed forward as an absorption is, so a later input that continues
the handed-over activation reaches the one that took its input. A take
is asked of the activation that has acted, because only its planning knows whether the new
input would undo what it did. The meaning the offering activation recorded serves the older:
both were caused by the same place and read the same place window, so understanding does
not run again for a taken input (§7:9). The older is shown the offer at its next round, so a
take costs no model call of its own. The answer call writes, so it is not a pure read, and
it reaches only an activation that has already acted, so it commits nothing that was not
already committed.

The deadline is moved because the wait is not the waiting activation's own work. Counting it
would end every activation waiting behind long work as *couldn't finish* before it had begun.
The older's own deadline and round limit still bound how long anything waits.

### 8. No place waits

> **Normative.** Every input on every place starts its own activation, after its place's
> start wait (ADR-0332 §5), whatever runs on that place or any other. No kind declares that
> its places run one activation at a time, or that an input waits for running work.

> **Normative.** The start wait (ADR-0332 §5:1, §5:3) runs for every message, whether or
> not something runs on the place.

> **Normative.** A reader marks a message taken in by the activation that admitted it, as at
> admission (ADR-0293 §6:8, ADR-0323 §5:8). Absorbing and taking mark nothing again.

A place holds nothing. A burst of messages is handled by absorption: each message starts its
own activation, and a newer one that continues an older one absorbs it while it has not
acted (§7:5). Input that continues work that has acted is offered to it, or waits on it, and
input that continues nothing never waits (§7:17, §7:29). So spawning is no longer needed to
keep a place free. Spawn (ADR-0350) is for work that runs later, outlasts an activation's
time limit, or splits into parallel parts.

Two activations on one place that are separate work may both act before either ends. A true
race between two acts on one thing is the lock and recheck's (#2586).

**Replies out of order.** With several activations in one conversation, replies arrive in the
order the work finishes. Saying which message a reply answers, by a native reply, a
"replying to…" display or a fixed prefix, is decision C's (§11).

### 9. The numbers

> **Normative.** `Settings` loses `join_limit` (ADR-0332 §6:5).

> **Normative.** `Settings` gains `held_input_limit`, an integer, default **4**, at least 1:
> the most inputs one activation holds, its own with every one it absorbed or took. 1 turns
> absorbing and taking off.

> **Normative.** `Settings` gains `in_progress_limit`, an integer, default **5**, at least 1:
> the most entries understanding's in-progress section shows (§5:10).

> **Normative.** [#2589](https://github.com/leonapivato/ai-assistant/issues/2589) tunes these
> defaults by measurement, without a new decision.

`held_input_limit`'s default is ADR-0332's `join_limit` of 3 with the activation's own input.
ADR-0332 §6's four waits stand as they are. The starting values are guesses, to be measured.

### 10. The code it binds

> **Normative.** `ProposedActivationUnderstanding.continues` becomes
> `tuple[EncodableText, ...] = ()`, each element the `R` label of an in-progress entry
> (ADR-0332 §7:3).

> **Normative.** `ActivationUnderstanding.continues` becomes `tuple[Identifier, ...] = ()`:
> the activations the proposal's labels resolved to, in the proposal's order, each once. A
> label that resolves to no shown activation is dropped as a grounding defect (ADR-0276
> §6), never a parse failure.

> **Normative.** `ConversationState.activation_id` becomes `activation_ids:
> tuple[Identifier, ...] = ()`: every running activation started from the conversation whose
> id is known, and empty unless the state is working.

> **Normative.** The working set's takeover decision, per understanding version (ADR-0332
> §7:6), records each activation named in `continues`, and what became of it: absorbed;
> not taken; offered, and then taken, declined with its reason, or withdrawn; or waited on
> with no offer. A take is recorded in the older's takeover decisions too.

> **Normative.** Each change that alters a shape the wire carries advances
> `PROTOCOL_VERSION` in that change, under ADR-0124 §9:2, with the wire surface and type
> closure, and the memory and engine conformance suites, extended to the shape.

> **Normative.** §10:2's change to the stored understanding is a schema change under
> ADR-0326 §2:3, and ships ADR-0326 §4:1–§4:2's upgrade and its test in the same pull
> request. A stored `continues` naming one activation becomes a one-element sequence, and
> an absent one an empty sequence.

> **Normative.** `JoinedInput` keeps its shape. Each one this decision appends names, in
> `taken_over_from`, the activation it was absorbed from, or the offering activation whose
> input was taken. An offer and its answer are the engine's working state, recorded in the
> takeover decisions (§10:4) and, for the answer, as the older's call; no type in `core`
> is added for them. The answer call is a capability in `orchestration`, and no
> `ControllerStage` or `ControllerRule` member is added: the planning stage holds the
> waits of §7:25–§7:26.

> **Normative.** `ControllerRule.TAKEOVER_UNDECIDED` answers where the latest understanding
> version names any activation in `continues` and there is no takeover decision for that
> version, and makes the takeover stage due, which absorbs (§7).

> **Normative.** `ControllerStage.TAKEOVER` and `ControllerRule.TAKEOVER_UNDECIDED` keep
> their names, and the rule keeps its row (ADR-0332 §4:5).

No `Protocol` changes: `AssistantEngine.stop_activation` is the one stop every route
reaches, planning's stop call included, and no field in `core` carries a stop.

### 11. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| The Task Scheduler, scheduled tasks, spawning, the sensor, and the Task Manager's operations and view | ADR-0350 |
| **Decision C, calls onto channels:** every channel the same shape; speaking as a say-call into any place; *in reply to* and replies out of order; a conversation's expected reply as its kind's requirement; and its supersession of ADR-0170 ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)) | Its own track |
| **Modes:** quick, normal, deliberate, "just blurt" | Its own decision, next on this front |
| **The gap for outside content:** marks travelling on every read of another activation's episode, through the one read function (§6:7), beyond authorizing's count (§6:13): to understanding's in-progress section, and to what a reader's own notes and messages then rest on. §6:13 reaches planning only through what planning pulls, looks up or is offered. And a question for that front: should a running entry planning pulls (§6:2), which carries no outside text (§5:6), mark its reader at all? Under §6:13 as written it does, so one running activation that has read outside content marks every activation whose planning pulls the list while it runs | The outside-content design: the privacy, audience and security front, which reviews the mark further |
| **The gap for privacy:** shares and merges stay within one person (§5:3, §7:5) until the household design | The household design |
| **The gap for forgetting:** every read is fresh each round, so a forget or a deletion is honored (cf. [#3319](https://github.com/leonapivato/ai-assistant/issues/3319)) | The privacy and forgetting design |
| **The gap for the audience:** the audience where a message lands ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)) | The audience design |
| What a place whose activation was absorbed hears about where the matter went | [#2588](https://github.com/leonapivato/ai-assistant/issues/2588) |
| The lock and recheck for two acts on one thing | [#2586](https://github.com/leonapivato/ai-assistant/issues/2586) |
| Batching unrelated messages into one activation, if two messages ever feel chatty | Measurement first |
| The values of §9, and the in-progress section's size | #2589 (§9:4) |
| A pull of another place's recent messages, as a capability (§2:2) | The kind that declares it |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

### 12. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0332 | §2:3–§2:5, whole: every input on every place starts its own activation, and no kind runs one at a time or holds an input back for running work (§8:1); §3:3–§3:8, §3:15 and §3:18, whole: no input joins by code, and before its first act an activation waits once for newer input to be understood (§7:12–§7:14); §3:9, in the addition alone: a version covers the inputs its absorption brought, and a taken input is covered by the meaning its offer carried; §4:1–§4:4, whole: the in-progress section on every place, spawned activations included, and `continues` a sequence, narrowed so that separate work continues none; §4:6, whole: the newest absorbs, following forward, under the held-inputs limit; §4:8, for a named activation that has committed: it is offered this activation's input or waited on, and this activation does not simply go on (§7:17–§7:29); §5:1, §5:3 and §5:5, each in the addition alone, and §5:4, whole: the start wait runs whether or not something runs on the place, and no input joins or waits behind running work; §6:5, whole: `held_input_limit` replaces `join_limit`; §7:3 and §7:4, whole; §7:6, in the takeover decision's content; §8:4, in the addition alone: `/stop` stops every running activation started from the chat | §4:3, §5:2–§5:7, §7:3–§7:7, §7:9, §7:12–§7:29, §8:1–§8:3, §9:1–§9:2, §10:1–§10:4, §10:7–§10:9 |
| ADR-0315 | §2:1–§2:3, each in the addition alone: a waiting round never ends the activation, and the next round after it runs once each activation it waits on has ended; a round whose acts were held back for an offer it was not shown brings another round, whatever it called | §7:14, §7:26 |
| ADR-0343 | §2:1–§4:3, whole: no join is taken by code, so none is pending, and no route waits for one | §7:12–§7:14, §8:3 |
| ADR-0292 | §11:2, as ADR-0332 left it, in two parts: input that adds separate work to running work stops nothing; and after the older has committed, the newer's input is offered to it, and where it takes it the newer is stopped and the older carries on; §11:7, in the addition alone: running work is shown only where the place's kind declares it, and only for the activations it caused | §4:13–§4:14, §7:3, §7:17–§7:24 |
| ADR-0295 | §1:1, §1:4 and §1:5, each in the addition alone: a stop is also reached by planning's stop call, an act it chooses and authorizing checks, where its input carries the user's authority, so words planning reads may lead to a stop, though they stay a message; §1:2, in the addition alone: the conversation's state names every running activation, and its stop control stops each | §4:3–§4:4, §4:6–§4:8, §10:3 |
| ADR-0286 | §6:4, in the addition alone: understanding's in-progress section, the findings look-up, the running part of ADR-0350's list pull, the reads of absorbed work and a stop call's result read another activation's open episode through the one read function | §4:11, §5:6, §6:7–§6:8 |
| ADR-0307 | §6:1, in the addition alone: planning is given, read fresh each round, absorbed findings, the offers open to it and the finished work of what it waited on; §6:6, in the addition alone: planning may look up a running activation's findings | §6:1, §7:10, §7:19, §7:27 |
| ADR-0350 | §4:1's capability set and §10:4, each in the addition alone: planning is also offered the Task Manager's stop, as its stop call, where its activation's input carries the user's authority, naming a running activation it was shown, with §9:6's cascade and one implementation | §4:6–§4:12 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0292 §11:1, §11:5 | Nothing on their lines: ADR-0332 replaced §11:1 within a place and §11:5 whole, and this decision replaces ADR-0332's clauses. Every message on every place now starts its own activation (§8:1), which is §11:1's end state, reached by this decision's clauses |
| ADR-0293 §6:2–§6:3, ADR-0323 §5:5 | Nothing on their lines: ADR-0332 replaced their waiting and taking in with joining and one activation at a time, and this decision replaces ADR-0332's clauses (§8:1) |
| ADR-0292 §11:4 | Nothing: §7:12 builds its wait once before each action, and ADR-0295 §3:3 its stopped activation writing nothing; its lock and recheck stays #2586's, as ADR-0332 §9 left it |
| ADR-0292 §10:4, §12:2, §12:5–§12:6 | Nothing: a running activation on the place is shown to understanding beside the window, in the section, and a message never becomes a command: planning's stop call is an inside action that planning chooses, authorizing checks and acting runs |
| ADR-0292 §11:2's stopping of the older, as ADR-0332 left it | Nothing: the rule acting on understanding's judgment still stops only an older one not yet committed, by absorbing it (§7). Planning's stop call is not that rule but an act, so a committed one it stops leaves ADR-0332's narrowing as it stands |
| ADR-0295 §§2–5, ADR-0297 | Nothing: every route reaches the one stop, and the stop mark is read and set as before. A stop holds no waiting message back (ADR-0295 §3:6), and no place holds one (§8:1) |
| ADR-0306 §4:7, §5:2 | Nothing: the round's message goes only into the input's place until decision C, which is why an offer is made only within one place (§7:18), and everything claimed finishes |
| ADR-0321 §4:1 | Nothing: an approval is used only by its yes's activation, and no share shows one |
| ADR-0341 | Nothing: a pure read is as it defines it, and the findings look-up is one |
| ADR-0350 §4:6, §10:3, §14 | Nothing in their words beyond the row above: its list pull showed a running activation as ADR-0332 §4:1–§4:3 did, which §5:2–§5:6 replace, so its running part shows the in-progress entries (§6:2); its stop shortcuts send the Task Manager's stop for each activation their place shows (§4:3, §4:14); and §14's stopping in words, with the running step that spawns again, is decided here by the stop call (§4:6) |
| ADR-0276 §4, ADR-0286 §6:1 | Nothing: the episode window holds what it held, and no search returns an open episode; the in-progress section is beside the window, not in it |
| ADR-0303 §7 | Nothing: a place-window item links to the activation that took it in, an absorbed one included |
| ADR-0284 §8:1, ADR-0308 §3:1, §5:5 | Nothing: recall's projection stays as they rule it, and the peer view is a second view of the same function, whose evidence carries its marks as recall's does |
| ADR-0303 §3:2, ADR-0306 §4:4–§4:6 | Nothing: an activation a share shows planning is an episode shown under a label, and an outside one counts in the reader's record as any does (§6:13) |
| ADR-0332 §2:1–§2:2, §2:6, §3:1–§3:2, §3:10–§3:14, §3:16–§3:17, §4:7, §5:2, §5:6–§5:11, §6:1–§6:4, §6:6, §7:1–§7:2, §7:5, §7:7–§7:10, the rest of §8 | Nothing in their words: an absorption's and a take's inputs are recorded as `JoinedInput`s naming their activation, an absorbed or handed-over activation is stopped as a taken-over one was, a take extends no deadline (§3:14, §7:11), and the waits and `/stop` stand |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0286, ADR-0292, ADR-0295, ADR-0307, ADR-0315, ADR-0332,
> ADR-0343 and ADR-0350, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> their ratified bodies. The replacements take effect on this ADR's ratification.

## Situations

| Situation | What happens |
| --- | --- |
| Three quick messages in one chat, before any reply | Each starts its own activation, and the newest absorbs the older two: one reply |
| "Actually Sunday," a second after "book Saturday," before it acts | The older waits for the newer's understanding, and the newest absorbs it: Saturday is never booked |
| "Actually Sunday" in the same chat, after it booked Saturday | It is offered to the booking: the booking takes it and changes the booking itself, or declines, and the newer waits for it to end, sees the booking, and changes it |
| "Only two bedrooms" while the apartment search, which has saved a shortlist, runs | Offered to the search, which takes it and filters, and the newer ends silent; or it declines, and the newer says it will filter once the search finishes |
| "Only two bedrooms" on Telegram while the web search, which has acted, runs | No offer across places: the newer waits for the search to end, or its waiting round stops the search and takes the matter over |
| "Actually Sunday" on Telegram, before the web booking acts | The newest absorbs across places: one Sunday booking, and the reply comes on Telegram |
| "Never mind the booking" on Telegram, after the web one acted | Planning stops it through the Task Manager's stop, whose cascade cancels what it spawned, and the reply says what had finished |
| "Never mind the booking," then "no, keep it" a second later | The stop call waits for the newer input to be understood, the newer absorbs the stopping activation, and nothing is stopped |
| "Stop the apartment search" while one of its steps runs | Planning stops the step, and the cascade cancels its next task |
| "Also, what's the weather there?" while a hotel search runs | Separate activations: the weather answers first |
| "My budget's $400 now" while a flight search runs | Before the search acts, the newer absorbs it, on any place. After it acts, within one place the search is offered the change, takes it and adapts; across places the newer waits, and applies it once the search ends |
| "What's the cheapest so far?" from another device | Planning looks up the search's findings and answers |
| "What are you doing right now?" | Planning pulls ADR-0350's list, whose running part shows the in-progress entries |
| Two newer activations name the same older one at once | The first absorbs it; the second follows forward and absorbs the first, if it hasn't acted |

## Consequences

**What becomes possible.**

- A correction a second after a request changes the first answer, on any of the person's
  places, before the first acts.
- "Never mind" on another device stops work that has already acted, and what it spawned,
  through the same stop the Task Manager runs.
- Planning pulls what is running and looks up what one found, when the matter needs it.
- A burst of messages gets one reply, and separate questions get separate ones.
- No place waits: a question while work runs is answered at once, and work that has acted
  is asked whether it takes a correction before anything waits.
- Joining and takeover become one mechanism, and the record names, on each absorbed input,
  where it came from.

**What it costs.**

- Fields in `core/types.py`, a schema change to the episode store with its upgrade, and a
  `PROTOCOL_VERSION` advance.
- A stop in words costs planning a round, and commits its activation, so it can no longer
  be absorbed: a later input that continues it is offered to it or waits on it (§7:17).
- Two settings in place of one.
- Every message pays its own understanding, where joining paid one for a burst past the
  start wait.
- An offer costs the older activation a call in its next round, and a decline leaves the
  newer waiting until the older ends. Its deadline is moved by the wait, so a waiting
  activation can run long after its input arrived.
- Across places, until decision C, work that has acted is never offered a correction: the
  newer waits, or stops it.
- Every act waits for newer input from the same person to be understood, when there is
  any: on any place before the activation commits, and on its own place after. An offer
  arriving in that wait costs a round again.
- Two activations in one conversation that are separate work may both act before either
  ends. Two acts on one thing is #2586's.
- An absorbed activation's messages appear in two episodes, the stopped one and the absorber,
  whose `JoinedInput` names the former.
- Until the gaps of §11 close, a peer's marks reach authorizing (§6:13) but not every reader,
  and shares stay within one person.
- A takeover decision may wait for an older one's understanding, and a call result planning
  did not digest or note reaches no other activation.

**The cut, for the dispatcher.** Four lanes, in §1:4's order, after this decision merges.
ADR-0350 and its lanes TS1, TS1b and TS2 have merged. Step 2 removes ADR-0332's joining by code and ADR-0343's pending join with
it. ADR-0340 (#3271) is rewritten on top of ADR-0350, and is no lane of this decision.

**What would reopen it.**

- **The household design**, for shares and merges across people.
- **The outside-content design**, for marks on peer reads.
- **#2589's measurements**, if a message's own understanding costs too much where nothing
  has acted.
- **A section that is often full.** When the assistant is very busy and constantly handling
  tasks at the same time, the newest `in_progress_limit` entries of understanding's section
  (§5:10) may not be the ones that matter.
  The likely fix is relevance over recency: for example, understanding is shown the
  entries that relate to its input first, by story or by place, before the newest.

## Alternatives considered

- **Fork, a running copy.** Rejected: it doubles the model calls, and the copy could act
  twice. Kept from acting, a copy is just a share.
- **Split into equal parts.** Rejected: a person answers a two-part message once and hands
  off the long part, which is a spawn.
- **Suspend and resume.** Rejected: it doesn't survive a restart. Ending and being continued
  does the same job.
- **"Kill."** Rejected: too abrupt for ADR-0295's graceful stop, and "stop" already names the
  mechanism.
- **A home place**, for each activation's window, "working…" and stop. Rejected: a place is
  only what caused an activation (§2).
- **A supervisor with share rules** (the same story, the same person, lineage). Rejected:
  understanding's section, with planning's look-up and list, does the same job with less, and the
  automatic flow carries no findings.
- **Joining by code, with a separate takeover** (ADR-0332 §3, §4). Rejected: one rule, the
  newest absorbs, covers both.
- **The newest able to push itself into the older.** Before the older acts, rejected: the
  newest absorbs it, and the older's findings move with the merge. After it acts, an offer
  the older may take or decline is the decision, by the owner on 2026-10-25 (§7:17).
- **The older taking every newer input unasked**, after it acts. Rejected: only its
  planning knows whether the input would change something it cannot undo.
- **One activation at a time per conversation** (ADR-0332 §2:3). Rejected: the place holds
  nothing, and the waiting belongs between activations that continue one another (§7).
- **A conversation that waits once something in it has acted.** Rejected by the owner on
  2026-10-25: it tied the activation to its place again, and made a question wait behind
  unrelated work. The offer and the wait on the older (§7:17–§7:29) do the same job for
  input that continues the work, and nothing else waits.
- **No wait before the first act.** Rejected: an older activation could act on a request the
  newer input corrects, before the newer was understood, and the newest would not decide
  (ADR-0292 §11:4).
- **A new planning label kind for running activations.** Rejected: each has an open episode,
  and its episode label holds once it ends.
- **The in-progress section in every round of planning.** Dropped by the owner on
  2026-10-25: it was awareness only, and planning, which has calls, pulls what it needs
  (§5:9). Understanding keeps it, since it is one call with no tools.
- **A relation to the reader on each entry.** Not added: with the section understanding's
  alone, understanding judges the relation itself, in `continues`.
- **Understanding's `cancels`**, a field naming the running work its input asks to stop, on
  which a rule in the takeover stage stopped it. Dropped by the owner on 2026-10-25, in favour
  of planning's stop call (§4:6): planning already had the Task Manager's cancel and
  replace, and the stop was the one command missing (ADR-0350 §10:4). One stop, with its
  cascade, serves every route, and nothing new in `core` carries it.
