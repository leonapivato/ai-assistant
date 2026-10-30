# 352. A stop stops only the activation it names, an offer's answer settles before the round acts, and a hand-over never shows as a stop

- Status: Partially superseded by ADR-0357 (§3:8's instruction line, in where it is said alone: the descriptions of `stop_activation` and `cancel_task`)
- Date: 2026-10-26
- Scope: three gaps between ratified clauses that milestone 16's acceptance found ([#3459](https://github.com/leonapivato/ai-assistant/issues/3459), evidence on [#3442](https://github.com/leonapivato/ai-assistant/issues/3442)), as the owner ruled them on 2026-10-26. Every stop stops exactly the one activation it names, and ADR-0350 §9:6's cascade is removed (§2). A stop call's result lists what the stopped activation set up that is still live, and planning stops or cancels what the person's words cover (§3; [#3460](https://github.com/leonapivato/ai-assistant/issues/3460)). An offer's answer settles before the rest of its round is dispatched (§4; [#3463](https://github.com/leonapivato/ai-assistant/issues/3463)). A conversation's current state never shows the ending of an activation that was absorbed or whose input was taken, and, within one place, shows instead how the activation that took the matter ended (§5; [#3464](https://github.com/leonapivato/ai-assistant/issues/3464)). §8 names what is not decided here.
- Dependency: [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), [ADR-0349](0349-a-place-is-only-what-caused-an-activation-a-stop-is-reached-three-ways-running-work-is-shared-by-reading-it-and-the-newest-absorbs-what-it-continues.md), [ADR-0340](0340-a-task-the-person-sets-may-come-due-at-a-local-time-or-on-a-rule-in-their-zone-and-is-said-back-from-the-hubs-record.md), [ADR-0295](0295-stopping-an-activation-is-a-command-that-starts-nothing-new-and-cuts-off-nothing-already-sent.md), [ADR-0297](0297-a-stop-is-marked-on-the-activation-and-recorded-where-claims-are-decided.md), [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md), [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md) and [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), as their status lines leave them.
- Authorization: the owner walked the three findings with the coordinator on 2026-10-26. On the cascade, verbatim: "Remind me in 40 minutes to check the project notes, meanwhile research blenders. Then I want to cancel the blenders research. Why should that cancel the reminder, they are clearly different"; then "what if we just removed cascading? made all cancels deliberate?"; and then "yes, remove the cascade and write ADR-0352". In the same walk the owner accepted, in the coordinator's analysis, that a chain no longer stops just because a step's activation is stopped (Consequences), that an offer's answer settles before the round acts (§4), and that a hand-over or an absorption is never the ending a conversation shows (§5). On where an activation started from one place is absorbed by one started from another, the owner ruled, verbatim, "go with a": the absorbed activation's conversation stops showing "working…" for it and keeps the ending it showed before, the outcome appears where the person asked, and telling the first place where the matter went stays #2588's (§5:3). On ratification, the owner, verbatim: "conditional go on 352": where the reviews come back clean with nothing serious changed beyond the owner's rulings, the coordinator ratifies it (§1:1). Understanding's misplaced `R` label (#3461) went to the owner's prompts front and is not in this decision. The dispatcher assigned 0352.
- **Changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `PlanStore` loses `record_cascade`, and `mark_occurrence_pushed` loses its refusal below a cascade record and with it the answer `OccurrencePush.CASCADE_CANCELLED` (§6:1–§6:2). `PlanExport` loses `cascades`, and its `schema_version` advances (§6:3). `EpisodeProcessingRecord` gains `taken_over_by`, which `episode_extends` admits in the revision that freezes a record (§6:5–§6:6), and `PROTOCOL_VERSION` advances (§6:7). No `Protocol` gains a member, and `AssistantEngine`, `ConversationState` and `Settings` keep their shapes (§6:8).
- **Partially supersedes**, in the clauses §9's first table names: ADR-0286, ADR-0293, ADR-0295, ADR-0340, ADR-0349 and ADR-0350.
- Partially superseded: 2026-10-30 by ADR-0357 — §3:8's *Planning's instruction says, in one line*, in where it is said alone: the descriptions of `stop_activation` and `cancel_task` say it (ADR-0357 §7:1–§7:3). What the line says is unchanged by ADR-0357. Every other clause stands, §3:10 included. This replacement takes effect on ratification of ADR-0357. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

In this document a bare section reference, such as §4:2, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0350 §9:6.

**What the acceptance found.** Milestone 16's acceptance drove ADR-0349's behaviours through
a scratch hub and the owner's hub on build `22fa9959d`. Every driven arm behaved as ruled,
and three findings were gaps between ratified clauses rather than code that departs from
them:

- **#3460 (major).** "Never mind that blender request," said in a second conversation after
  the blender work had set a reminder and started searching. Planning's stop call stopped
  the work, and ADR-0350 §9:6's cascade cancelled the reminder, as ruled. The stop call's
  result, which ADR-0349 §4:11 makes the stopped activation's peer view, said nothing of
  the cancellation, so both of the stopping activation's messages told the person the
  reminder was still in place.
- **#3463 (major).** An older activation answered an offer with a take and, in the same
  round, acted on the offered input. Every call of a round is dispatched together, so the
  acts ran whatever the take came to. The take was refused at `held_input_limit`, and the
  newer, now waiting on the older, did the same work again: three writes to one reminder,
  and a message telling the person they had not asked for what they had asked for. With an
  act that cannot be undone, the same sequence acts twice in the world.
- **#3464 (minor, needing a ruling).** After a take, a conversation's state read "stopped":
  the offering activation, handed over silently, is newer than the one that took its input
  and ends first, and the state reads the newest ended episode. The same holds across
  places for an absorbed activation's own conversation. Nobody stopped anything.

**The owner's ruling on the cascade.** The owner's example is the whole argument: a
reminder set in one breath with a piece of research is a different matter from the
research, and stopping the research should not cancel it. ADR-0350 §9:6 cancels everything
below a stopped activation, so the reminder goes. The owner's answer was to remove the
cascade and make every cancel deliberate.

**What the tree holds,** on `origin/main` at `a72ceaaf2`:

- `Engine._stop` sets the stop mark, then, where the Task Manager is wired, writes
  `PlanStore.record_cascade` before `record_stop`, and then runs `Engine._cascade`, which is
  `TaskManager.cascade`: the walk that cancels every pending occurrence below and stops every
  pushed or running activation below through `Engine._stop_one`.
  `Engine._stop_pushed(activation_id, cascade=True)` writes the cascade record for an id the
  Task Scheduler pushed and has not admitted.
- `PlanStore.mark_occurrence_pushed` ends an occurrence cancelled and answers
  `OccurrencePush.CASCADE_CANCELLED` where an activation in its task's lineage carries a
  cascade record (`decide_push` in `planning/scheduled_tasks.py`, and its twin in
  `testing/_scheduled_tasks.py`). `PlanExport.cascades` carries the records, and the SQLite
  store keeps them in `cascade_records`.
- **The spawn's refusal is already keyed on the stop record, not the cascade record.**
  ADR-0350 §3:3 has the store refuse a spawn "where it holds a stop record for the spawning
  activation", and `SqlitePlanStore.write_scheduled_task` decides the claim inside its
  transaction, raising `ClaimStopped` on the stop record (ADR-0297 §2:5). The cascade record
  guards only the push step below a stopped activation.
- `MatterCalls._stop` in `orchestration/matter_calls.py` holds the peer view, and whether
  the call stopped the activation and whether it had ended (`PeerShown`). Nothing of the
  cascade reaches it. The stop call's declaration, `STOP_ACTIVATION`, says "Stop running work
  you were shown as running, and what it set up to run later."
- Acting runs a round in `orchestration/phase_path.py`: after ADR-0349 §7:12's wait,
  `_commitment` holds back the whole round where an offer is open that the round was not
  shown, and otherwise the round's calls and its message are dispatched together under one
  `asyncio.gather`. An answer call, `answer_offer`, is run by `MatterCalls._answer` through
  `Matters.answer`, whose `TakeAnswer` is taken, declined, withdrawn or no offer.
- `conversation_state` in `orchestration/conversations.py` reads the conversation's newest
  ended episode (`MemoryStore.channel_episodes(channel, limit=1)`, in number order, so the
  newest started). An absorbed or handed-over activation's episode freezes with
  `ProcessingReason.STOPPED`, as one a person stopped does, and nothing on it names the
  activation that took its matter: `JoinedInput.taken_over_from`, on the taker's episode, is
  the only durable record of the hand-over.

**Why it needs a decision.** ADR-0350 §9:6 rules the cascade, §7:5 the push step's refusal
below it, §8:1 what a restart leaves below a stop, and §10:2 the Task Manager's stop "with
§9:6's cascade"; ADR-0349 §4:7 runs planning's stop call with it; ADR-0340 §4:7 has a rule
end by it. ADR-0349 §4:11 rules what the stop call's result shows. ADR-0349 §7:14 rules
when a round is held back, and nothing rules the order of a round's calls. ADR-0293 §8:3
and ADR-0295 §3:4 rule what the state shows. Changing what each requires is a
supersession (ADR-0070), and the plan store and the episode record are contracts in `core`.

## Decision

We will make every stop stop exactly the one activation it names. Nothing walks below a
stop and no cascade record is written; a stopped activation still writes no new task,
because the store refuses its spawns on its stop record. What it set up stays until it is
cancelled or stopped deliberately, so a stop call's result lists what the stopped
activation set up that is still live, and planning stops or cancels what the person's words
cover, keeps the rest, and asks where it is unclear. Acting runs a round's answer calls
first and alone, and where a take did not happen, it dispatches none of the round's acts and
planning runs again. And an activation that ended because its matter was taken over is
never the one whose ending its conversation shows: its episode names the activation that
took the matter, and where that one is the conversation's own, the conversation shows how it
ended; otherwise the conversation keeps the ending it showed before.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the coordinator
> ratifies it, as the owner directed on 2026-10-26 (the header's authorization): where the
> reviews leave nothing serious changed beyond the owner's rulings. An assigned number or a
> green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

### 2. A stop stops only the activation it names

> **Normative.** Every stop stops exactly the one activation it names, by ADR-0295's stop as
> ADR-0297 records it, and nothing below it: it cancels no scheduled task and stops no other
> activation. This holds for the Task Manager's stop command, whether it is sent by the hub
> chat's stop control, the line's `/stop` or the command line, and for planning's stop call.

> **Normative.** No stop writes a cascade record, and no part of the hub reads one, except
> the plan store's upgrade under §2:6.

> **Normative.** The push step (ADR-0350 §7:5) refuses an occurrence only where it is no
> longer pending, or its task is no longer held. Nothing in a task's lineage refuses it.

> **Normative.** What a stopped activation set up stays as it was: each pending occurrence of
> a task below it falls due as its when gives, and each activation running or pushed from a
> task below it runs on, until a cancel (ADR-0350 §9:5) or a stop names it. This holds after
> a restart: where ADR-0350 §8:1 settles a stopped activation's occurrence *stopped*, what is
> below it is settled and pushed as anything else is.

ADR-0350 §3:3 stands unchanged and is now the whole of what a stop does to the Task
Scheduler's writes: the store refuses a stopped activation's spawn on its stop record, and
whichever of the stop record and the spawn's claim lands first in the store wins (ADR-0295
§2:2). So a step stopped while it writes its next one writes nothing once its stop has
landed. A next step whose write landed first stays, as any task below a stop does, and
§3:1 lists it. ADR-0350 §9:10 stands too: a stop naming an id the Task Scheduler has pushed
and not yet admitted writes its stop record for that id, and nothing starts.

> **Normative.** A rule (ADR-0340 §4:7) ends only when the next instant it would yield falls
> after its until, or when its pending occurrence ends *cancelled* by a cancel, a replace's
> included (ADR-0350 §9:4–§9:5). No stop ends a rule.

> **Normative.** The plan store's upgrade that retires the cascade record (§6:4), in one
> step, first ends *cancelled* every occurrence still pending whose task's lineage carries a
> cascade record, as ADR-0350 §7:5 refused it before this decision; writes a stop record
> (ADR-0297) for the activation of every occurrence marked pushed whose task's lineage
> carries one and whose outcome is not written; and then removes every cascade record. So a
> stop made before this decision keeps the reach it had when it was made.

A pushed occurrence is not left to the push step: at start ADR-0350 §8:1 settles it, and
§8:5 or §8:6 would push it again, where the push step's lineage check used to cancel it.
With its activation's stop record written, §8:1 ends it *stopped* and never pushes it again,
as the old walk's stop of that activation would have.

The takeover's stop and a merge's stop (ADR-0295 §5:1, ADR-0349 §4:5) never cascaded, so
nothing changes for them.

### 3. What a stop call shows, and what planning stops or cancels

**What the stopped activation set up.** A stop no longer reaches what its activation set
up, so the planner that made it is told what is left, and the person can be told.

> **Normative.** Where a stop call stopped the activation it named, or found it ended or
> stopped (ADR-0349 §4:10), its result shows, beside that activation's finished work
> (ADR-0349 §4:11), what that activation set up that is still live: each scheduled task
> below it that has an occurrence pending, and each activation running or pushed from a
> task below it. Where there is none, the result says that nothing it set up is still live.

> **Normative.** *Below* is ADR-0350 §9:6's walk, made as a read: the tasks the activation
> spawned, and the tasks spawned by those tasks' activations in turn, read from the tasks the
> Task Scheduler keeps (ADR-0350 §7:8) whether or not their activations have ended. The walk
> reads only, and is made once the stop's record is written, or once the activation was found
> ended or stopped.

> **Normative.** Each task the result shows carries its `T` label (ADR-0350 §9:2), its
> instruction in brief, when it next falls due as the hub renders it (ADR-0340 §6:1), its
> author, the person or the assistant (ADR-0350 §3:7), and the description of its parent the
> list pull writes (ADR-0350 §4:6).

> **Normative.** Each activation the result shows is shown as the list pull's running part
> shows one (ADR-0349 §6:2), under its episode label, and one pushed and not yet admitted is
> shown under its task's `T` label as starting.

> **Normative.** A task carrying the outside-content mark, and an activation whose input is
> outside, are shown with their text withheld and their mark shown, as the list pull shows
> them (ADR-0350 §4:7), so the result carries no outside text.

> **Normative.** Each of the result's two parts shows at most ADR-0350 §12:5's listing bound
> of items, tasks in the order they were written and activations oldest first, and says how
> many more there are.

> **Normative.** An activation the result shows as running counts as shown running for the
> stop call and the findings look-up (ADR-0349 §4:6, §4:8, §6:1, §6:5), as one a list pull's
> running part showed does. A task it shows counts as shown for a cancel and for a spawn that
> replaces it, under ADR-0350 §4:4's checks.

So the round after a stop call can say what is still set, and can cancel or stop what the
person's words also covered, by the labels the result gave. A running activation below can
be stopped there by the stop call, whose own result then lists what that one set up.

**What planning stops or cancels.**

> **Normative.** Planning's instruction says, in one line, that a stop or a cancel reaches
> only what the person's words cover: planning stops or cancels each running activation and
> each scheduled task the words cover, keeps the rest, and asks which where it is unclear.

> **Normative.** The stop call's declaration (ADR-0349 §4:7) says that it stops that work
> alone, and that its result lists what that work set up that is still live. It no longer
> says that it stops what the work set up to run later.

> **Normative.** The exact words of §3:8's line and of §3:9's declaration are not decided
> here. The lane that builds them ships the words the coordinator routes from the owner's
> prompts front, and changes no other instruction line for this decision.

"Cancel the blenders research" stops the research and keeps the reminder. "Never mind all
the blender stuff" stops the research and, by the labels its result gives, cancels the
blender tasks it set up and stops those of them that run, and keeps a reminder about the
project notes. "Never mind that blender request," where the request also set a reminder to
check the blender notes, stops the research and asks whether the reminder goes too.

### 4. An offer's answer settles before the round acts

> **Normative.** Where a round's allowed calls include an answer call (ADR-0349 §7:20),
> acting, once ADR-0349 §7:14's step lets the round run, dispatches the round's answer calls
> first and alone, and awaits each to its end, before it dispatches any other call of the
> round that is not a pure read, or the round's message.

> **Normative.** Where an answer call of the round asked to take an offer and did not come to
> a take, acting dispatches none of the round's other calls that are not pure reads, and not
> its message, and records each such call *not done*, with a reason saying that the offer was
> not taken. This holds whether the take was refused at `held_input_limit` (ADR-0349 §7:22),
> the offer was withdrawn (ADR-0349 §7:22, §7:24), the call was refused whole (ADR-0349
> §7:20), or authorizing did not allow it.

> **Normative.** Where every answer call of the round came to a take, or to the decline it
> asked for, acting dispatches the rest of the round as it dispatches any round.

A round held back under §4:2 made a call, so planning runs a round again (ADR-0315 §2:1),
shown each answer's result and each held-back call as not done, and that round counts
toward the round limit as every round does. A take that succeeds lets the rest run, so
"actually Sunday" taken by the booking changes the booking in the round that took it. A
decline planning chose lets its own work run, since a decline means the offered input is
not this work's.

**Why it cannot loop.** A round is held back under §4:2 only after an answer that settled
something or was refused. An answer that settled an offer, taken, declined at the limit or
withdrawn, leaves that offer no longer open, and an offer once closed never opens again
(ADR-0349 §7:24). Each offer ever made to an activation counts toward `held_input_limit`
from the moment it is made, whatever becomes of it (ADR-0349 §7:22), so an activation is
held back for a settled answer fewer than `held_input_limit` times. An answer refused whole,
naming no offer open, settles nothing; a planner that kept making one would be held back
every round, and the round limit ends that loop as it ends every loop of refused calls
(ADR-0307 §8:4, ADR-0315 §2:4).

### 5. What a conversation shows after a hand-over

> **Normative.** An activation that ended because it was absorbed (ADR-0349 §7:7), or because
> its input was taken (ADR-0349 §7:21), is never the activation whose ending a conversation's
> current state shows (ADR-0293 §8:3, ADR-0295 §3:4).

> **Normative.** Such an activation's episode records, in the revision that freezes it, the
> activation that took its matter: the one that absorbed it, or the one that took its input,
> as the engine's takeover decisions hold it (ADR-0349 §10:4). Where a restart's close
> freezes it (ADR-0286 §7:2), nothing records it, and the episode reads as the restart left
> it.

> **Normative.** Where the newest ended episode of an activation started from the
> conversation records the activation that took its matter, the state follows it forward,
> through each episode that records one in turn, to the activation that took the matter
> last. Where that activation was started from the same conversation and its episode is
> frozen, the state shows how it ended. Otherwise, while it runs, where it was started from
> another place, or where its episode is not found, the state passes over the taken-over
> episode and reads the next newest ended episode of the conversation in the same way, so it
> shows the ending it showed before the hand-over.

Whether a conversation shows "working…" and a stop control is unchanged: only for the
activations it caused (ADR-0349 §4:14). So the cases come to this:

| Case | What the conversation shows |
| --- | --- |
| A take within one place | "Working…" while the older that took the input runs, beside the ending it showed before; then how the older ended. Never "stopped" |
| An absorption within one place | "Working…" while the absorber runs, beside the ending it showed before; then how the absorber ended. The absorbed one is never shown |
| An absorption across places, on the absorbed activation's conversation | "Working…" stops for the absorbed one, and the ending stays what it was before the absorption, while the absorber runs and after it ends |
| The same, on the absorber's conversation | "Working…" while it runs, and then how it ended, as for any activation it caused |

**Why, within one place.** The activation that absorbed the input or took it is that
place's own, so the conversation shows how it ends, as it does for any activation it
caused. "Stopped" is false: nobody stopped anything.

**Why not, across places.** The owner ruled it on 2026-10-26 ("go with a"). The outcome
appears where the person asked, on the absorber's place. On the absorbed activation's
conversation:

- nothing of that conversation's own finishes, so its ending does not move;
- following the absorber would show an outcome with no reply in that conversation, since the
  reply went to the absorber's place;
- telling that conversation where the matter went is a message into another place, which is
  the speaking decision's, with #2588 (ADR-0349 §11).

A taken-over activation has always been stopped by the step that recorded its taker, and
the taker was running then, so a chain of hand-overs only ever moves on to an activation
that was running when it took the matter, and it ends.

### 6. The code it binds

> **Normative.** `PlanStore.record_cascade` is removed, and no member takes its place.

> **Normative.** `PlanStore.mark_occurrence_pushed` loses its refusal below a cascade record
> (§2:3), and `OccurrencePush` loses `CASCADE_CANCELLED`, a recorded exception to *added to
> and never renamed*: a push's answer is held by no stored record and crosses no wire.

> **Normative.** `PlanExport` loses `cascades`, its `schema_version` advances, and
> `PlanStore.clear` counts no cascade record.

> **Normative.** The SQLite plan store ships ADR-0326 §4:1–§4:2's upgrade and its test in
> the change that removes the cascade record. The upgrade makes §2:6's cancels and stop records
> and drops `cascade_records` in one transaction.

> **Normative.** `EpisodeProcessingRecord` gains `taken_over_by: Identifier | None = None`,
> §5:2's record, defaulted so that a record written before it validates unchanged and its
> `schema_version` does not move, as `joined` was added. Only a frozen record whose reason
> is `stopped` carries one, and it never names the record's own activation.

> **Normative.** `episode_extends` admits `taken_over_by` taking a value only in the
> revision that freezes the record (ADR-0286 §3:3).

> **Normative.** `PROTOCOL_VERSION` advances in the change that adds `taken_over_by`, with
> the wire surface and type closure, since the processing record crosses the wire inside
> episodes (ADR-0124 §9:2). Any other change that alters a shape the wire carries advances
> it again in that change.

> **Normative.** No `Protocol` gains a member for this decision, and `AssistantEngine`,
> `ConversationState` and `Settings` keep their shapes.

### 7. Delivery

> **Normative.** The implementation ships as separate pull requests:
>
> 1. **`core`, `wire`, `testing` and `memory`, permitted expressly here as one unit:**
>    `EpisodeProcessingRecord.taken_over_by` and `episode_extends` (§6:5–§6:6), the
>    `PROTOCOL_VERSION` advance with the wire surface and type closure (§6:7), and the
>    memory conformance suite's case for a frozen record that carries it.
> 2. **`orchestration`, the answer first:** §4 in acting.
> 3. **`orchestration`, the deliberate stop:** the cascade's removal from `Engine._stop`,
>    `Engine._stop_pushed` and `TaskManager` (§2:1–§2:2); the stop call's result (§3:1–§3:7);
>    its declaration and planning's instruction line (§3:8–§3:10); and §5's record at freeze,
>    and the state's reading, with the composition wiring in `app/` they need.
> 4. **`core`, `testing` and `planning`, the `PlanStore` triad with its primary
>    implementation (ADR-0137 §2:1):** §6:1–§6:4, the conformance suite, the canonical fake,
>    `InMemoryPlanStore`, and the SQLite plan store with its upgrade.

> **Normative.** Step 3 is briefed after step 1 has merged, and step 4 after step 3 has
> merged, since no caller of `record_cascade` may remain when it is removed (ADR-0137 §4:1).
> Step 2 depends on neither and may merge in any order with them.

> **Normative.** Step 2's tests include: a round that takes an offer and spawns, where the
> take is refused at `held_input_limit`, which dispatches no spawn and no message, and whose
> next round is shown the decline; the same with the offer withdrawn, the offering
> activation stopped between the offer and its answer; a take that succeeds, after which the
> spawn is dispatched; a decline planning chose, beside a spawn, which dispatches the spawn;
> two answer calls in one round, one taken and one refused, which dispatches nothing else;
> and an answer naming no open offer beside a spawn, which dispatches no spawn.

> **Normative.** Step 3's tests include: a stop by the Task Manager's command of an
> activation that spawned a reminder still pending, after which the reminder still falls
> due; a stop call naming a committed activation that spawned a task still pending, which is
> stopped while the task stays pending and is listed in the result with its `T` label, its
> due time and its author; a stop call naming an activation whose child step ended after
> spawning a grandchild still pending, which lists the grandchild; a stop call whose result
> lists an activation running from a task below it, which the next round's stop call names
> and stops; a stop call naming an activation that set up nothing, whose result says that
> nothing is still live; a stop of a step racing the write of its next step, in both orders,
> where the next step is refused once the stop record has landed and stays otherwise; no
> cascade record written by any stop; a take within one conversation, whose state never reads
> *stopped* and then reads the taker's ending; an absorption across places, whose absorbed
> conversation stops showing "working…" for the absorbed activation and keeps the ending it
> showed before, while the absorber runs and after it ends; and a burst absorbed in one conversation, whose state never reads *stopped*.

> **Normative.** Step 3 adds synthetic prompt cases (ADR-0337 §3) for at least: the owner's
> case, a reminder and research set in one message and then "cancel the blenders research"
> from another conversation, which stops the research, keeps the reminder and says that it is
> still set; "never mind all the blender stuff", which stops the research and cancels or
> stops what its result lists of the blender work; and words that could mean either the
> research alone or the research and its reminder, which asks.

> **Normative.** Step 4's tests include: the upgrade over a store holding a cascade record
> with a pending occurrence below it, which ends that occurrence *cancelled* and leaves no
> cascade record; the same store with an occurrence below it marked pushed and its outcome
> unwritten, as a crash before the walk stopped it leaves one, whose activation the upgrade
> gives a stop record, so that ADR-0350 §8:1 at start ends it *stopped* and never pushes it
> again; and a push of an occurrence whose task's parent carries a stop record,
> which is pushed.

### 8. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Whether understanding's misplaced `R` label, one outside `continues`, is dropped as a grounding defect rather than refused ([#3461](https://github.com/leonapivato/ai-assistant/issues/3461)) | The owner's ruling on where it belongs |
| Which ending a conversation shows when several of its activations that are separate work end in a different order from the one they started in | A decision of its own |
| What a stop sent from outside, by the stop control, `/stop` or the command line, tells the person of what the stopped activation set up | The decision that opens the Task Manager's view (ADR-0350 §10:6) |
| What the place of an activation absorbed across places hears about where the matter went | [#2588](https://github.com/leonapivato/ai-assistant/issues/2588) (ADR-0349 §11) |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

### 9. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0350 | §9:6, whole: a stop command stops only the activation it names, writes no cascade record and walks nothing; §7:5's refusal below a cascade record, whole: the push step refuses only an occurrence no longer pending or a task no longer held; §8:1's *anything below it that is still pending is kept from running by §7:5's lineage check*: what is below a stop is settled and pushed as anything else is; §10:2's *with §9:6's cascade*; §9:3, in the addition alone: planning's instruction also says that a stop or a cancel reaches only what the person's words cover; §12:3's members that write a cascade record and refuse a push below one, and `PlanExport`'s cascade records; §13:3's cases of a crash after a cascade record, a stop whose walk cancels a grandchild, a chain stopped while its next task is pushed, and a takeover's stop writing no cascade record | §2:1–§2:4, §2:6, §3:8, §6:1–§6:4 |
| ADR-0349 | §4:7's *with ADR-0350 §9:6's cascade*; §4:11, in the addition alone: the result also shows what the stopped activation set up that is still live; §4:6, §4:8, §6:1 and §6:5, each in the addition alone: a running activation a stop call's result showed may be named; §7:14, in the addition alone: once the round may run, its answer calls run first and alone, and a take that did not happen holds back the rest; §1:5's case of a stop call whose cascade cancels the task: the task stays pending and the result lists it | §2:1, §3:1–§3:7, §3:9, §4:1–§4:3 |
| ADR-0340 | §4:7's *or by a cascade (ADR-0350 §9:6)*: a rule ends by its until or by a cancel, a replace's included, and no stop ends one | §2:5 |
| ADR-0293 | §8:3, for an activation that ended because it was absorbed or its input was taken: its ending is never shown. Where the activation that took the matter, followed forward, was started from the same conversation, the state shows how it ended once it has ended; otherwise the state reads on to the next newest ended episode, so it keeps the ending it showed before | §5:1–§5:3 |
| ADR-0295 | §3:4, for the same activation: the merge's internal stop is never shown as *stopped* | §5:1 |
| ADR-0286 | §3:3, in the addition alone: the revision that freezes a record may also set `taken_over_by`; §3:8, in the addition alone: `taken_over_by` is a field of the record, not a stage's result | §5:2, §6:5–§6:6 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0295 §1:1 | Nothing in its words: a stop names exactly one activation, and the addition ADR-0350 made to it is the clause §2:1 replaces |
| ADR-0295 §2:2, ADR-0297, ADR-0306 §5:4 | Nothing: a claim after a stop's record is refused, a spawn's among them (ADR-0350 §3:3), whichever lands first deciding |
| ADR-0295 §5:1, ADR-0349 §4:5 | Nothing: a takeover's and a merge's stop never cascaded |
| ADR-0350 §3:3, §7:8, §9:10 | Nothing: the store refuses a stopped activation's spawn on its stop record; tasks are kept while anything below them is live, which §3:2's walk reads; a pushed id's stop writes its stop record and nothing starts |
| ADR-0350 §4:6, §4:7, §12:5 | Nothing: the list pull's parent descriptions, its withholding and its listing bound serve the stop call's result as written (§3:3, §3:5, §3:6) |
| ADR-0349 §4:9, §4:10, §4:12, §7:20–§7:24 | Nothing: an absorbed one is refused and named, an ended one stops nothing, a stop call is an act, and the answer call, the take and its limit stand |
| ADR-0349 §4:14, ADR-0350 §6:9 | Nothing: a conversation shows running work and a stop only for the activations it caused, and an activation the Task Scheduler started is not one |
| ADR-0315 §2:1, §2:4 | Nothing: a round held back under §4:2 made a call, so another round runs, and the round limit ends every loop of rounds |
| ADR-0307 §5:3 | Nothing: a label a stop call's result showed was shown |
| ADR-0124 §9:2 | Nothing: step 1 advances `PROTOCOL_VERSION` in the change that alters the wire's shape (§6:7) |
| ADR-0326 §4:1–§4:2 | Nothing: the plan store's change ships its upgrade and its test (§6:4) |
| ADR-0337 §3 | Nothing: step 3's prompt cases are synthetic cases under it (§7:5) |
| ADR-0137 §2:1, §4:1 | Nothing: step 4 is a triad with its primary implementation, briefed once nothing calls the member it removes |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0286, ADR-0293, ADR-0295, ADR-0340, ADR-0349 and ADR-0350,
> atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

## Situations

| Situation | What happens |
| --- | --- |
| "Remind me in 40 minutes to check the project notes, meanwhile research blenders," then "cancel the blenders research" on Telegram | No offer across places: the newer waits on the research, and its waiting round stops it with the stop call. The reminder stays. The result lists it, by its `T` label, set by the person and due in forty minutes, and the round after the wait says that it is still set |
| The same "cancel the blenders research" in the same chat, after the research has acted | It is offered to the research, which takes it, stops searching and says what it found. Its reminder stays, since the words do not cover it |
| "Never mind all the blender stuff," where the research split itself into steps spawned to start now and a gather step timed after them, and also set the project-notes reminder | Planning stops the research. Its result lists the gather step and the steps still pending, by `T` label, and the steps running, by episode label. Planning cancels and stops the blender ones, and keeps the reminder |
| "Never mind that blender request," where the request was a reminder to check the blender notes and the research | Planning stops the research, and asks whether the blender-notes reminder goes too |
| Apartment checks every hour, a chain whose each step spawns the next an hour on, and "stop the apartment checks" | Planning pulls the list, stops the running step with the stop call and cancels the pending next step, in one round. Where the running step had spawned another before its stop landed, the stop's result lists it, and the next round cancels it |
| A step stopped while it writes its next one | Whichever of the stop record and the spawn's claim lands first in the store wins. Landed after the stop, the spawn is refused and nothing is written. Landed before, the next step stays pending, and a stop call's result lists it |
| A daily rule's occurrence, "every morning at 7, check the weather", stopped while it runs | The hub chat's stop control does not show for it, since the Task Scheduler started it; the command line's stop or a stop call stops that run, and its occurrence ends *stopped*. The rule's next occurrence, written when this one was pushed, stays pending, as it did under the cascade, which never walked to the task that started the run. A cancel ends the rule |
| "Every weekday at 7, the bins, and look up my street's collection days," stopped by the control while it looks | The look-up stops. The rule stays, where the cascade cancelled it. A cancel ends it |
| A refused take: the older, holding the most input it may, answers "make it 9pm instead" with a take and a spawn in one round | The take is refused at `held_input_limit`. The spawn is not dispatched and the round writes no message. The next round sees the decline and carries on with its own work. The newer waits on it and makes the change once it ends: one write |
| A withdrawn take: the offering activation is stopped by the stop control between the offer and its answer | The offer is withdrawn, and the older's acts on it are not dispatched. The next round sees the withdrawal, and the stopped input's work is not done, as its stop asked |
| "Actually Sunday," taken by the booking that has acted | The answer runs first, the take succeeds, and the changed booking is dispatched in the same round |
| Three quick messages in one chat, absorbed by the newest | The page shows "working…" while the newest runs, and then how it ended. It never shows "stopped" |
| "Only two bedrooms," taken by the apartment search in the same chat | The page shows "working…" for the search, and then how the search ended. It never shows "stopped" |
| "Actually Sunday" on Telegram, absorbing the web booking before it acts | The web conversation stops showing "working…" for the booking, and keeps the ending it showed before. Telegram has the reply, and the outcome shows there |

## Consequences

**What becomes easier.**

- A stop does what it names. A reminder, a schedule or anything else set in the same breath
  as stopped work stays, and nothing the person wanted is cancelled silently.
- The reply after a stop rests on a record of what is still set, so it says what is still
  set, as ADR-0349 §4:11 meant for what had finished.
- No act runs on an offered input the older did not take, so a refused or withdrawn take can
  no longer act twice in the world.
- A conversation's state never says "stopped" where nobody stopped anything. Within one
  place it says how the activation that took the matter ended.
- The plan store loses a record kind, a member and a refusal, and the engine its walk.

**What it costs.**

- **A chain no longer stops just because a step's activation is stopped.** Its next step
  stays until it is cancelled deliberately. The owner accepted this: a wrong cascade cancels
  something the person wanted, silently, while a missed cancel is visible, since the step
  speaks or the list shows it, and is capped by the chain limit (ADR-0350 §9:7).
- **A stop sent from outside tells the person nothing of what is left.** The stop control,
  `/stop` and the command line answer the stop alone. Until the Task Manager's view opens
  (§8), the person asks "what's scheduled?" to see it.
- **"Stop" in words may cost planning a round or two:** one to stop, and one to cancel what
  the stop's result lists that the words also covered.
- **An offer's answer delays the rest of its round** by the time the answer takes, a write
  in the hub, and a take that does not happen costs a round.
- **A field on the episode record**, with a `PROTOCOL_VERSION` advance, and an upgrade of the
  plan store.

**What would reopen it.**

- Chains left running after their steps were stopped often enough to cost the person real
  work, which would argue for a stop that offers to cancel what is below it.
- Rounds held back for failed takes often enough to matter, which would argue for telling
  planning to carry a taken input out only from the round after its take.

## Alternatives considered

- **Keep the cascade and report it.** The cascade's result would name what it cancelled,
  which fixes #3460's message. Rejected by the owner: the cancellation itself was wrong, and
  reporting it does not bring the reminder back. "Why should that cancel the reminder, they
  are clearly different."
- **Cascade only through the assistant's own tasks,** sparing what the person set. Rejected:
  a step the assistant set may still be what the person wanted, and the line between the two
  is one planning can judge from the words, and code cannot.
- **Keep the push step's refusal below a cascade record** for records already written.
  Rejected: it would keep a record kind, a member and a refusal for a handful of rows. The
  upgrade applies the old refusal once, stops what was pushed below them, and retires the records (§2:6), so no stop made before
  this decision changes its reach.
- **List only the tasks the stopped activation spawned itself.** Rejected: a step that ended
  after spawning its own next one leaves that one live below the stopped activation, and a
  list that missed it would say nothing is left where something is, which is #3460 again.
- **Tell planning to carry a taken input out only from the next round,** with a prompt case
  to pin it. Rejected as the fix: it rests on a model following a line, and a model that did
  not would act twice. It stays open as wording, beside §4's code (Consequences).
- **Hold the rest of the round back on a decline planning chose, too.** Rejected: a decline
  means the offered input is not this work's, so the round's own work is safe to run, and
  holding it would cost a round for every decline.
- **Across places, show the absorber's ending on the absorbed activation's conversation**,
  once the absorber ends, and no ending while it runs. Rejected by the owner on 2026-10-26
  ("go with a"): nothing of that conversation's own finishes, the outcome would show where no
  reply came, and saying where the matter went is a message into another place, the
  speaking decision's (§5).
- **Within one place, only skip a taken-over activation,** without following it forward.
  Rejected: a take's taker is older than the activation it took from, so separate work that
  started between them and ended would be shown in place of the taker's ending.
- **Find the taker from `JoinedInput.taken_over_from`** on the taker's episode, with no new
  field. Rejected: the taker's episode is open while it runs, and no read finds an open
  episode, so the conversation would read "stopped" until the taker ended, and across places
  the taker's episode lies on another place, which no read of this one reaches.
- **A new `ProcessingReason` for a hand-over.** Rejected: an absorbed or handed-over
  activation is stopped by ADR-0295's stop (ADR-0349 §4:5, §7:21), so its reason is a stop's,
  and the state needs the taker's id, which a reason cannot carry.
