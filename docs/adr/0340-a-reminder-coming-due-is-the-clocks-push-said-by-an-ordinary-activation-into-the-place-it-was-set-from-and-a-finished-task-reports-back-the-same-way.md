# 340. A reminder coming due is the clock's push, said by an ordinary activation into the place it was set from, and a finished task reports back the same way

- Status: Proposed
- Date: 2026-10-21
- Scope: the first slice of proactivity, in which nothing is unasked. It covers reminders the person asks for ("remind me at 8 to take my medicine", "every weekday at 7, the bins", "in 20 minutes, check the oven") and the seam by which a finished background task reports back once. It decides the clock channel and its input (§2), where a reminder is said and what its activation may do (§3), the reminder record and the calls that set and change it (§4), its times (§5), the clock sensor (§6), when a reminder counts as said, its fixed line and its one more try (§7), late reminders (§8), recurrence (§9), a task's report (§10), the code it binds (§11) and its delivery (§12). These are picks 1 to 6 of proposal [#3271](https://github.com/leonapivato/ai-assistant/pull/3271), with the walk's answers 1 to 10. §13 names what is not decided here, the owner's open question on delivery to the line among it.
- Dependency: [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), [ADR-0317](0317-an-activation-that-chose-to-say-nothing-has-finished.md), [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md), [ADR-0329](0329-the-observer-is-memorys-one-writer-it-commits-what-an-episode-leaving-the-window-shows-and-planning-records-candidates-for-it.md), [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md) and [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md), as their status lines leave them. A task's report has its first producer in the background-work decision, which no decision has yet made (§10:7).
- Authorization: the coordinator walked proposal #3271 on 2026-10-21 under the owner's standing delegation, and the walk record on #3271 holds the ten answers this decision converts. The owner's words on that delegation, verbatim (2026-10-21): "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you." The walk marks question 2's automatic delivery to the line as the owner's, and §13 leaves it open. The dispatcher assigned 0340, and ratifies it under that delegation.
- **Changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `PlanStore` gains the reminder members (§11:2), and `core/types.py` gains the reminder record, its occurrence, its rule and their enumerations (§11:1). `ActivationEffect` gains whether any part of a message was written, and `PlanStore.finish_activation_effect` takes it (§11:3). `core`'s register of channel types gains the clock (§2:2). Five capability declarations are added (§4:6), and `Settings` gains five fields (§11:5). `PROTOCOL_VERSION` advances in the lane whose types first cross the wire (§11:6).
- **Partially supersedes**, in the clauses §14's first table names: ADR-0292, ADR-0306, ADR-0307, ADR-0317, ADR-0323, ADR-0329, ADR-0332 and ADR-0338.

## Context

**The question.** How does Aether say something at a time the person asked for? A reminder
is the delayed reply to the person's own request, so it is the first slice of proactivity
in which nothing is unasked. Speaking first, unasked, stays out: how much the assistant does
unasked and when it speaks first are boundaries set per person (`VISION.md` Principle 5),
which is authority's territory and the owner's.

**The test.** `VISION.md` Principle 3 makes what a trusted human assistant would do the test
for how Aether behaves. Asked to remind you of something, such an assistant says back what
they understood ("8 tonight, your medicine"), says it at that time in a word that fits the
moment, owns up once if they missed it, takes "done", "give me ten minutes" and "forget the
bins one" in their stride, offers to help rather than acting on the reminder alone, and,
sent on an errand, comes back once when it is done. Where the analogy breaks, this decision
does something else:

| A person… | This decision, where it cannot do the same |
| --- | --- |
| keeps an eye on the clock | A model never decides that it is time: a deterministic clock reads the record (`VISION.md` Principle 7; §6) |
| says it in words that fit | Planning words it, seeing the conversation it joins, and a fixed line goes out where no model can (§7) |
| confirms what they heard | The confirmation repeats the hub's rendering of the time, not the model's (§4:9) |
| owns up to a miss | The hub knows how late it is and says the time it was due; several misses are one message (§8) |
| never knows whether a word got through | A message whose outcome is unknown is tried once more, marked as such, and never again (§7:5) |
| can't be told by a stranger to remind you | Only input carrying the person's authority sets a reminder, and a reminder coming due authorizes nothing (§4:4, ADR-0292 §5:6) |
| reaches you wherever you are | The hub chat page shows no system notification (ADR-0175 §9:3); the confirmation says where it will arrive, and the person may name the line (§3:1, §4:9) |
| knows not to interrupt your meeting | Nothing senses attention today. The asked time wins (§3:9) |
| comes back from an errand once | A finished task reports once, in the place that started it; progress waits to be asked about (§10) |

**What was already ratified.**

- ADR-0292 §6:2 counts "a reminder coming due" as a push, and §5:6 rules that "a reminder
  the user set informs the activation it starts and authorizes nothing". Its §5 table gives
  "a reminder's author is whoever set it, at the time they set it". §7 says "proactivity
  needs nothing of its own": a timer's push starts an activation, which writes into a place.
  §7:3 builds no separate notification route, and §2:5 names the clock among the built-in
  channels.
- ADR-0292 §13 retires the notification route (`next_notification`, ADR-0131) into writing
  into a place, when that replacement is built (§13:1). This decision is the first such
  replacement, and retires nothing: the upcoming-event producer keeps the route until the
  calendar's push is built (ADR-0324 §4:3).
- Until "the timers and proactivity milestone", a round's message goes only into the place
  the input came from (ADR-0306 §4:7, ADR-0307 §3:1), an activation whose place takes no
  message writes none (ADR-0307 §3:8), the line writes only to the input's place (ADR-0323
  §6:1), and no background work messages the user (ADR-0329 §13:6). This decision lifts each
  of these for exactly the activations the clock starts.
- ADR-0332 §2:3 runs one activation at a time on a conversation and on the line. ADR-0338
  §3:6 makes the person's profile zone the zone of what code reads for them, and its §2:2
  already makes an activation whose input is "a reminder or timer the user set" the owner's.

**What the code does, at `origin/main` `eb5e79c0`.** No reminder, timer or clock channel
exists: admission knows `conversation`, `telegram` and `informational_event`
(`_INPUT_ORIGINS` in `core/channel_validation.py`). The hub's scheduler
(`service/scheduler.py`) runs maintenance jobs on one serial loop, accepting that "a missed
or late tick is never a correctness bug" (ADR-0083 §7). The notification chassis
(`memory/notification_store.py`, `notification_outbox.py`, `notification_policy.py`) is
wired, with the upcoming-event stage as its one producer, and delivers through the gateway's
long poll to the hub chat page's notifications panel alone. `ChatWriter.send` writes nothing
into a conversation that is gone. `TelegramWriter` splits a long message into parts, and
where a later part fails it records the message *not done* with the delivered part in
`written` (`_cut_short`, pinned by `test_a_message_cut_short_between_parts_is_never_done`).

**Why not a notification.** Shown on ADR-0130's chassis, a reminder would be a candidate of
class `reminder`, held by the shipped defaults (reach `hold`, three interruptions a day,
quiet windows; ADR-0130 §6:2) until the person raised the class, and delivered, if at all,
to the page's panel (ADR-0131 §1:2, ADR-0175 §9:3), never to the line or the conversation
it was asked in. A candidate is "something they did not ask for" (ADR-0130 §1:1), so every
lever the chassis has bounds the unasked, and each one applied to an asked reminder is a
broken promise. The route is also the one ADR-0292 §13 retires.

## Decision

We will make a reminder coming due a push on the built-in clock channel, starting an
ordinary activation that says it, in its own words, into the place the reminder was set
from or the line the person named. The reminder will be a record in the plan store, set and
changed only by own-records calls from input carrying the person's authority. A
deterministic clock will push it on time, say it late where it was missed, and try once
more where a message may not have arrived. A finished background task will report back once
through the same record.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher as §12 sets out, and
> no lane is dispatched before a milestone holds the work (`CLAUDE.md` → "Delivery
> planning").

### 2. The clock channel and its input

> **Normative.** The clock is a built-in channel (ADR-0292 §2:5). Its kind only pushes,
> takes no message, holds no medium, and is declared in code as the line's kind is
> (`orchestration/channel_kinds.py`).

> **Normative.** `core`'s register of channel types (`core/channel_validation.py`) gains
> the clock, which declares its origin per input (ADR-0284 §2:2) and establishes no author
> as the user in any place of its own.

> **Normative.** Each reminder is a place on the clock, so a reminder's episodes are indexed
> by the clock and that reminder (ADR-0292 §10:5).

> **Normative.** A reminder coming due is one input. It holds the reminder's text, when and
> in which place it was set, each occurrence it says with the instant that occurrence was
> due, whether it is late (§8) or a second try (§7:5), and the reminder's rule.

> **Normative.** Its author is the person who set the reminder, written when they set it
> (ADR-0292 §5's table), and it carries no authority (ADR-0292 §5:6).

> **Normative.** Its origin is `user`, except for a reminder set in an activation that had
> read outside content (ADR-0306 §4:5), whose input's origin is `outside`, and a report
> (§10), whose origin is §10:4's.

> **Normative.** An activation the clock starts joins, by rule, the stories of the
> activation that set the reminder, as they stand when it is admitted.

### 3. Where it is said, and what its activation may do

> **Normative.** A reminder's **place** is the place it speaks into, fixed when it is set:
> the place of the input that set it, or, where that input named the line and a line is
> connected, the line's chat. No other place may be named, and planning chooses none.

> **Normative.** An activation the clock starts writes its messages into its reminder's
> place, and into no other. That place takes the role ADR-0306 §4:7, ADR-0307 §3:1 and
> ADR-0323 §6:1 give the input's place, and the assistant starts no conversation for it.

> **Normative.** Its window is its reminder's place's window, read as that place's kind
> reads it.

> **Normative.** For ADR-0332 §2:3, an activation the clock starts counts as started from
> its reminder's place. It is admitted only where no activation is running there, and while
> it runs, the place admits no other.

> **Normative.** Before it admits an activation for a reminder whose place was busy, the
> clock reads the reminder again, and pushes nothing for an occurrence that has since been
> cancelled, marked done or snoozed.

> **Normative.** An activation the clock starts is its reminder's place's running
> activation for that place's current state and for a stop (ADR-0295, ADR-0332 §8). A stop
> ends the occurrence it was saying as *stopped*, and the clock never pushes it again.

> **Normative.** Planning in an activation the clock starts is offered no capability whose
> effect is the world or that leaves the hub, and none of the reminder calls (§4:6). Its
> message is its only act outside the hub's own records, and it may offer help as a
> question ("It's Friday: you wanted to book the campsite. Shall I look?").

> **Normative.** Planning's instruction for an activation the clock starts says that it is
> saying a reminder the person asked for, says whether the reminder is late or a second
> try, and asks it to say the reminder in one message.

> **Normative.** A reminder is said at the time it is due, whatever later boundaries on
> speaking first say, unless a decision on those boundaries says otherwise.

**Why.** Speaking where it was asked is what a person expects of an asked reminder, and
where to speak unasked is proactivity's question. Counting the clock's activation as the
place's own keeps one voice at a time in a conversation, and the re-read honours a "cancel
the medicine reminder" being handled at 8. An activation that only says the reminder cannot
surprise the person at 3 a.m., and its offer becomes the person's yes in a new activation
that carries their authority.

### 4. The reminder record, and the calls that set and change it

> **Normative.** A reminder is a record in the plan store (`PlanStore`). It holds its id,
> its kind (`asked` or `report`), its text, its place, the person it is for, when it is due
> (an instant, or a rule under §9), the activation and the episode that set it, whether that
> activation had read outside content, its state, and each occurrence with its own state.

> **Normative.** An occurrence's state is one of: pending; pushed, naming the activation;
> said; uncertain (§7:4); stopped; snoozed to an instant; done; skipped; cancelled; or
> undelivered (§7:7). The set is closed, added to and never renamed.

> **Normative.** A reminder is set, changed, cancelled and marked done only through the
> plan store's members (§11:2), each one atomic step, and the call that sets a reminder
> writes the reminder and claims its effect record in that one step.

> **Normative.** Only an activation whose input carries the person's authority (ADR-0292
> §5:5) is offered the calls that set, change, cancel or mark done a reminder. An activation
> the clock starts, and a background task's slice, sets none.

> **Normative.** A reminder is for the person the setting activation is for (ADR-0338
> §2:2), and an activation that is no person's sets none.

> **Normative.** Planning is offered five capabilities, each declared with the effect *the
> assistant's own records*, never leaving the hub, never with an unknown outcome, and with
> a result carrying no outside text (ADR-0306 §2, §3):
>
> | Capability | What it does | Safe to repeat |
> | --- | --- | --- |
> | set a reminder | its text; when, as an instant, a local date and time, a delay or a rule; and optionally the line as its place | No |
> | change a reminder | snooze one occurrence to a new time, or move the reminder | Yes |
> | cancel a reminder | one occurrence, or the reminder | Yes |
> | mark a reminder done | the current or next occurrence, said or not | Yes |
> | list reminders | the person's pending reminders | Yes |
>
> Exact names and arguments are the triad lane's, within this table.

> **Normative.** A set whose time resolves to an instant not later than now is refused as
> *not done*, with the reason (ADR-0306 §5:1), and writes nothing.

> **Normative.** Planning is shown the person's pending reminders under a label kind of
> their own, `T1`, `T2`…, bounded by a `Settings` count (§11:5), and the change, cancel and
> done calls name a reminder by that label (ADR-0307 §5:2–§5:3).

> **Normative.** The set call's result carries the hub's own rendering of the reminder's
> time, recurrence and place, written from the stored record in the person's zone ("Tonight,
> Tuesday 21 October, at 8:00 PM, here"), and planning's instruction is to say it back.

> **Normative.** Deleting a conversation cancels every reminder whose place it is, in the
> same act, and the hub chat page's deletion prompt says how many reminders that cancels.
> Disconnecting the line cancels every reminder whose place is the line's chat.

> **Normative.** The plan store's export carries every reminder and its occurrences, and
> its clear erases them (ADR-0004 §6).

"Done", "snooze 10 minutes" and "cancel the bins reminder" are ordinary messages:
understanding reads them in context and planning calls the capability for the reminder it
means, asking where the words could mean two. "I already took it", before 8, is a *done*
for that occurrence, so it is not said.

### 5. Times are the person's local times

> **Normative.** A reminder's times are read in the zone of the person it is for, under
> ADR-0338 §3:6: their profile zone where it is set, and `Settings.timezone` otherwise.
> Reminder code reads that zone through one function.

> **Normative.** A one-shot reminder is stored as a UTC instant, resolved when it is set,
> and no zone change moves it.

> **Normative.** A recurring reminder is stored as a local time of day and a rule, with no
> instant. Each next occurrence is computed in the person's zone as it stands when that
> occurrence is computed.

> **Normative.** A local time that a daylight-saving change skips falls due at the first
> instant after the gap, and a local time it repeats falls due once, resolved at `fold=0`.

### 6. The clock sensor

> **Normative.** The clock's sensor is one loop that the engine starts with the hub and
> stops with it, as it does the line's reader. It is not a row of the scheduler's table
> (ADR-0083 §7).

> **Normative.** It sleeps until the earliest instant an occurrence falls due, for no longer
> than a `Settings` recheck interval (§11:5), and setting, changing or cancelling a reminder
> wakes it.

> **Normative.** It compares wall-clock instants in UTC, never elapsed sleep. Every
> occurrence due at or before now whose state is pending, snoozed and due, or uncertain and
> due for its second try (§7:5), is pushed.

> **Normative.** Occurrences due for one place when the clock looks are pushed together, as
> one input and one activation.

> **Normative.** An occurrence is marked *pushed*, naming its activation, when that
> activation is admitted.

> **Normative.** At start, before it pushes anything, the clock reads each pushed
> occurrence whose activation is no longer running, and sets its state by §7's rule from
> that activation's effect records.

### 7. Said, the fixed line, and one more try

> **Normative.** Whether an occurrence was said is read from the effect records of the
> messages its activations claimed into its reminder's place (ADR-0306 §5:3), and from
> nothing else, by one rule:
>
> - **said**, where any message is done, or any part of one was written, whatever its
>   outcome;
> - **uncertain**, where none is said and any message's outcome is unknown, or any message
>   was claimed and given no outcome;
> - **not said**, where no message was claimed, or every message claimed is *not done* with
>   no part written.

> **Normative.** Where an activation the clock starts ends with an occurrence it was saying
> *not said*, by any ending but a stop or a restart, the fixed line is written into the
> reminder's place: `Reminder:` and the reminder's text, with the instant it was due where
> it is late, and with *in case my last message didn't reach you* on a second try. This
> replaces *couldn't finish* (ADR-0307 §3:7, ADR-0317 §3:1) for those activations, and
> where the activation's own message said every occurrence, nothing further is written.

> **Normative.** Where the fixed line is written, the episode freezes as ADR-0317 §3:5
> classifies an activation that did not finish.

> **Normative.** An occurrence that the rule reads *uncertain* at the end of its
> activation, or at start (§6:6), is set *uncertain*, and no fixed line follows in that
> activation.

> **Normative.** An occurrence set *uncertain* for the first time is pushed once more, a
> `Settings` wait (§11:5) after it was set so, as a second try, and its message says that it
> is sent in case the last one did not reach the person. An occurrence is tried a second
> time once at most: after its second try it is *said*, whatever its messages' outcomes.

> **Normative.** §7:5 replaces ADR-0306 §5:6's *never resolved by guessing* and §5:13's
> *never retried, done another way* for the message of an activation the clock starts
> alone. Every other effect keeps both clauses, and no outcome is ever reported as done.

> **Normative.** An occurrence *not said* at the end of its activation is pushed again after
> the same wait, and pushed at most a `Settings` number of times in all (§11:5). One still
> *not said* after the last is set *undelivered* and shown so in the person's list.

**Why.** A split Telegram message whose first part arrived reached the person, so it is
said. For a reminder, a duplicate costs far less than a miss, so a message that may not
have arrived is tried once more and marked, and never a third time. Nothing reached the
person where every message is *not done* with nothing written, so trying again repeats
nothing they saw.

### 8. Late reminders

> **Normative.** An occurrence pushed more than a `Settings` grace (§11:5) after the
> instant it was due is late, and its input says so with that instant.

> **Normative.** A missed occurrence is said once, however late, marked late, with the time
> it was due. No cut-off drops one.

> **Normative.** A recurring reminder that missed more than one occurrence pushes its latest
> missed occurrence alone, and sets each earlier one *skipped*, so it is said once and not
> once per occurrence.

> **Normative.** Several reminders missed for one place are said in one activation and one
> message (§6:4).

### 9. Recurrence

> **Normative.** A reminder's rule is one of a closed set: once; daily, at a local time;
> weekdays, at a local time; or weekly, on a chosen set of days, at a local time. Each
> recurring rule may carry an end date. The set is added to and never renamed.

> **Normative.** The hub validates a rule on the set call, refuses one that is not in the
> set as *not done* with the reason, and renders every rule back in words for the
> confirmation (§4:9).

> **Normative.** Cancelling one occurrence of a recurring reminder ("skip tomorrow") sets
> that occurrence *cancelled* and leaves the rule.

> **Normative.** A reminder repeated until the person says done waits for a decision of its
> own.

### 10. A finished task's report

> **Normative.** When a background task ends, by being done, by stopping because its next
> step needs the person's yes, by giving up, or by running out of its budget, its last slice
> sets one reminder of kind `report`, due at once, whose place is the place of the input
> that started the task, and whose stories are the task's.

> **Normative.** A task sets one report, however it ends. Nothing else a task does writes
> into a person's place, and its progress and any mid-task question stay on its story for
> the person to ask about.

> **Normative.** A report's input author is the assistant (ADR-0292 §5's table), and the
> activation it starts is for the person whose input started the task.

> **Normative.** A report's input origin is `outside` where the task read outside content,
> and `user` otherwise.

> **Normative.** A report is pushed and said by §§6–8 as any reminder is.

> **Normative.** A slice of a task never writes into a person's place itself.

> **Normative.** No report is set before the background-work decision builds tasks, and
> that decision uses this section for a task's report back.

### 11. The code it binds

> **Normative.** `core/types.py` gains frozen pydantic models for the reminder, its
> occurrence and its rule, and closed `StrEnum`s for the reminder's kind, the occurrence's
> state (§4:2) and the rule (§9:1), each added to and never renamed. Exact names are the
> triad lane's.

> **Normative.** `PlanStore` gains members to set a reminder with its effect claim in one
> step, change one, cancel one or one occurrence, mark one done, list a person's pending
> reminders, read the occurrences due at an instant, mark an occurrence pushed, and set an
> occurrence's state. `PlanExport` gains the reminders, and its `schema_version` advances.
> Exact signatures are the triad lane's, within this list.

> **Normative.** `ActivationEffect` gains whether any part of a message was written, and
> `PlanStore.finish_activation_effect` takes it with a message's outcome. The writers set
> it: the line from the parts it delivered, and the hub chat, which records a message whole
> or not at all, never.

> **Normative.** The plan store is a store under ADR-0326: the lane that changes its schema
> ships the upgrade (ADR-0326 §4:1).

> **Normative.** `Settings` gains five fields, each a default #2589 may tune without a
> decision: the lateness grace (two minutes), the sensor's recheck interval (thirty seconds),
> the number of pending reminders planning is shown (ten), the wait before a push again
> (one minute), and the most pushes of one occurrence (three).

> **Normative.** `PROTOCOL_VERSION` advances in the lane whose change first puts any type
> §11 adds or changes on the wire.

### 12. Delivery

The lanes, each after this decision merges `Accepted` and a milestone holds them:

1. **R1, the triad:** §11:1–§11:4's types, `PlanStore` members, the effect's written part,
   the conformance suite and the canonical fake, and the SQLite store with its upgrade,
   including the rule arithmetic of §5 and §9.
2. **R2, one-shot reminders end to end:** the capabilities, offering the rule *once* alone;
   the clock kind and its register entry; the clock sensor; an activation the clock starts,
   speaking into a conversation or the line; §7 and §8; the writers' written part; the
   composition wiring; and §11:5's settings.
3. **R3, recurrence offered:** daily, weekdays and weekly in the set call and in planning's
   instruction.
4. **R4, the page:** a reminders list with cancel, behind an `AssistantEngine` read, and the
   deletion prompt of §4:10.
5. **R5, the report:** in the background-work decision's lanes.

> **Normative.** R1 merges before R2, and R2 before R3 and R4. Each lane that consumes the
> triad is briefed after R1 has merged (ADR-0137 §4:1).

> **Normative.** R2 adds synthetic prompt cases (ADR-0337 §3) for at least these: "at 8" set
> before and after 8 a.m., a "done" said before the reminder is due, a cancel naming one of
> two reminders, and a late reminder said as late.

> **Normative.** R2's tests include a split message whose first part was delivered and whose
> second failed, which is *said* and not pushed again, and a message whose outcome is
> unknown, which is tried a second time once and never a third.

### 13. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| **[owner]** Whether a reminder set on the hub chat goes to the line automatically, where one is connected, because the page shows no system notification (the walk's question 2) | The owner, before this decision is ratified |
| Speaking first, unasked, and the per-person boundaries on it, quiet hours among them | Authority, which the owner designs |
| Planning choosing the place, and a place kept for the assistant's notices (ADR-0292 §7:2–§7:3) | Proactivity proper |
| Retiring the notification route, and the calendar's push in place of the upcoming-event producer (ADR-0292 §13, ADR-0324 §4:3) | Each its own decision |
| A reminder repeated until the person says done (walk answer 6) | After the pilot, starting with medicine |
| What an activation the clock starts may do beyond saying the reminder, such as a search (walk answer 5) | A later decision |
| Monthly and other rules; times relative to an event; places; conditions | Each its own decision; a condition is a watch ([#2585](https://github.com/leonapivato/ai-assistant/issues/2585)), and acting on one is [#2583](https://github.com/leonapivato/ai-assistant/issues/2583)'s |
| Reminders for another member of a household | The members design ([#691](https://github.com/leonapivato/ai-assistant/issues/691)) |
| Background tasks themselves | The background-work decision (ADR-0332 §9) |
| How a claim left with no outcome is recovered for any effect but a reminder's message | [#2584](https://github.com/leonapivato/ai-assistant/issues/2584) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 14. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0292 | §10:1, in the addition alone: an activation the clock starts reads its reminder's place's window | §3:3 |
| ADR-0306 | §4:7, for an activation the clock starts: its message goes into its reminder's place; §5:6's *never resolved by guessing* and §5:13's *never retried, done another way*, for the message of an activation the clock starts alone: one more try; §6:1's `ActivationEffect` row and §6:4's `finish_activation_effect`, in the additions alone: whether any part of a message was written | §3:2, §7:5–§7:6, §11:3 |
| ADR-0307 | §3:1 and §3:8, for an activation the clock starts: its round's text is written into its reminder's place; §3:7, for an activation the clock starts: the fixed line in place of *couldn't finish*; §5:1, in the addition alone: the label kind `T`; §6:1, in the addition alone: the person's pending reminders | §3:2, §4:8, §7:2 |
| ADR-0317 | §3:1–§3:4, for an activation the clock starts: §7:2's fixed line in their place | §7:2 |
| ADR-0323 | §6:1's *the chat is the input's place*, for an activation the clock starts: the chat is its reminder's place, and the writer still refuses any chat but the one the settings name | §3:2 |
| ADR-0329 | §13:6, in the addition alone: an activation the clock starts writes its messages, for a reminder or a report, and no other background work messages the user | §3:2, §10 |
| ADR-0332 | §2:3, in the addition alone: an activation the clock starts counts as started from its reminder's place | §3:4 |
| ADR-0338 | §2:2, in the addition alone: a report's activation is the person's whose input started the task; §3:6, in the addition alone: a reminder's times are read in the person's zone | §5:1, §10:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0292 §5:5–§5:6, §6:2 | Nothing: a reminder coming due is a push that informs and authorizes nothing |
| ADR-0292 §7:2–§7:3, §13 | Nothing: planning still chooses no place, no notification route is built, and nothing retires |
| ADR-0284 §2:2 | Nothing: the clock declares its origin per input, as the line does (ADR-0323 §4:11) |
| ADR-0293 §2:3, §6:11 | Nothing: deleting a conversation forgets nothing, a cancelled reminder stays in the record, and the assistant starts no conversation |
| ADR-0306 §2, §3, §4:1 | Nothing: the five capabilities declare the five properties, run against their store, and are checked by rule |
| ADR-0321 §4:1, §4:4, ADR-0323 §4:8 | Nothing: an offer in a reminder's message is a message, the person's yes is a new input, and *shown to you* reads the reminder's place, which establishes the user |
| ADR-0328 §9:3, ADR-0329 §13:4 | Nothing: a reminder is no open question, and the observer's questions stay unsent |
| ADR-0332 §3:3 | Nothing: a person's message carries authority and a reminder's input does not, so a message never joins an activation the clock starts |
| ADR-0083 §7 | Nothing: the scheduler's table is unchanged, and the clock is a loop of its own |
| ADR-0130, ADR-0131, ADR-0132 | Nothing: the chassis and its producer keep working as they decide |
| ADR-0004 §6, ADR-0326 | Nothing: the plan store's export, clear and upgrades cover reminders |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0292, ADR-0306, ADR-0307, ADR-0317, ADR-0323, ADR-0329, ADR-0332
> and ADR-0338, atomically with this ADR under ADR-0070 and ADR-0082, preserving their
> ratified bodies. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**

- "Remind me at 8 to take my medicine" works on the hub chat and on the line, is confirmed
  back in the hub's own words, and arrives at 8 in the place it was asked, worded for the
  conversation it joins.
- A reminder survives a restart, an outage of the model and a lost send: it is said late
  and marked, said by a fixed line, or tried once more and marked.
- "Done", "snooze" and "cancel" just work, and every change goes through a call the record
  shows.
- A background task, once built, has one ready way to come back once.
- The notification route has its first replacement in writing into a place.

**What it costs.**

- **A model call per reminder.** Each occurrence runs an activation; the fixed line costs
  none.
- **A busy conversation delays a reminder** until its running activation ends, bounded by
  that activation's own deadline.
- **A reminder on the hub chat is seen only while a device has the page open**, until the
  owner rules §13's first row.
- **A rare duplicate.** A message that may not have arrived is said once more, so a person
  may hear it twice, marked as a second try.
- **A missed reminder is said however late**, so "sorry, I missed the oven at 6:20" may
  come the next morning.
- **Machinery and records.** A triad on `PlanStore` with an upgrade, a field on the effect
  record, a clock loop, five capabilities, five settings, and header records on eight
  ADRs.

**The proposal's questions, as the walk answered them.**

| # | Question | Here |
| --- | --- | --- |
| 1 | The carrier | The clock's push and an ordinary activation, with the fixed line (§2, §3, §7:2) |
| 2 | Where it is said | The place it was set from, or the line where the person names it (§3:1); automatic delivery to the line is the owner's (§13) |
| 3 | Too late to bother | Always said once, marked late, misses grouped (§8) |
| 4 | An unknown outcome | One more try, marked, never more than once (§7:4–§7:6) |
| 5 | What its activation may do | Only say it, and offer as a question (§3:7) |
| 6 | Repeat until done | Waits (§9:4, §13) |
| 7 | Zones | Recurring follows the person's zone; one-shot is an instant (§5) |
| 8 | Quiet hours | The asked time wins (§3:9) |
| 9 | A deleted conversation | Cancels its reminders, and the prompt says so (§4:10) |
| 10 | The report | One report however the task ends (§10:1–§10:2) |

**What would reopen it.**

- Second tries that people hear as noise, because unknown outcomes turn out common.
- Reminders on the hub chat that people miss because the page was closed.
- A model that words a reminder so loosely that the person misses what it was.
- A busy place that holds reminders late often enough to matter.

## Alternatives considered

- **A notification on ADR-0130's chassis.** Rejected: its levers bound the unasked, its
  defaults hold an asked reminder, it reaches neither the line nor the conversation, and
  ADR-0292 §13 retires its route (Context).
- **Amending the chassis** with a `reminder` class that interrupts by default, exempt from
  the budget, with a delivery to the line. Rejected: it rebuilds beside the phases the
  separate route ADR-0292 §7:3 rules out, to be redone when the route retires.
- **A fixed line with no activation.** Cheapest and fully deterministic, and kept as the
  fallback. Rejected as the carrier: a second message path outside the phases, with no
  episode and no effect record, that cannot read the matter or say it like a person.
- **Planning choosing the place.** Rejected for now: where to speak unasked is proactivity's
  question.
- **A store of its own behind a `ReminderStore` Protocol.** A cleaner separation, rejected
  because the reminder and its effect claim must be written in one step.
- **A scheduler row.** Rejected: the scheduler accepts lateness and starvation (ADR-0083
  §7), and a late reminder is the defect.
- **Going anyway after a bounded wait for a busy place** (the proposal's first draft).
  Rejected: it overlaps the place's running activation against ADR-0332 §2:3, and can say
  a reminder while its cancellation is being handled.
- **Never trying an unknown outcome again** (the proposal's pick). Changed by the walk: for
  a reminder a duplicate costs much less than a miss.
- **Counting a *not done* message as nothing reached the person.** Rejected: the line
  records a split message *not done* after delivering its first part.
- **Dropping a missed reminder past a cut-off**, fixed or set per reminder. Rejected by the
  walk: the person relied on it.
- **Storing every reminder as an instant.** Rejected: it moves "every weekday at 7" by an
  hour at each daylight-saving change.
- **An iCalendar `RRULE` string as the rule.** Rejected for now: a model writing RRULE text
  is easy to get subtly wrong, and a closed rule is one the hub can validate whole and say
  back exactly. The closed rule maps onto a subset of it if the calendar needs one.
- **A confirmation question before setting.** Rejected: setting is reversible and stays in
  the hub, and the read-back catches a wrong time.
- **The last slice of a task writing its report.** Rejected: a slice never writes into a
  person's place.
- **A task waiting silently until asked.** Rejected by the walk: handing off an errand means
  not having to ask.
