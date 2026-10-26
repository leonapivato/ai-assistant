# 340. A reminder is a scheduled task the person sets, on an instant or a rule read in their zone, said back from the hub's record, and falling back to its own words

- Status: Proposed
- Date: 2026-10-25
- Scope: the reminder layer on the Task Scheduler. It covers what makes a scheduled task a reminder (§2), one-off times and local times (§3), the rule and its vocabulary (§4), skipping, changing and the plain words (§5), the read-back and the renderings (§6), a reminder coming due and its fixed line (§7), the capability surface and planning's instruction (§8), the code it binds (§9) and its delivery (§10). It is the reminders decision that [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md) §5:2, §5:3, §9:4 and §11:1 name. It rewrites the draft of 2026-10-21, which built reminders on a clock channel of their own, keeping what ADR-0350 §11 lists. §11 names what is not decided here.
- Dependency: [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md), [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), [ADR-0317](0317-an-activation-that-chose-to-say-nothing-has-finished.md) and [ADR-0337](0337-a-prompt-change-is-judged-on-a-regression-suite-with-repeated-samples-each-recorded-call-is-asked-what-it-had-to-guess-and-a-candidate-is-promoted-after-three-clean-days.md), as their status lines leave them.
- Authorization: the coordinator walked proposal [#3271](https://github.com/leonapivato/ai-assistant/pull/3271) on 2026-10-21, and the owner's walk of ADR-0350 from 2026-10-21 to 2026-10-25 replaced its channel with the Task Scheduler and listed what this rewrite keeps and drops (ADR-0350 §11). The owner ruled on 2026-10-25 that nothing is cancelled when a place is gone. The dispatcher assigned 0340. Ratification is the owner's, after their review.
- Milestone: [15, Task Scheduler: reminders and work that runs later](https://github.com/leonapivato/ai-assistant/milestone/15).
- **Changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `core/types.py`'s scheduled task gains its reminder mark and a rule as a when, and holds more than one occurrence where it has a rule (§9:1). `TaskRefusal` gains this decision's refusals (§9:2). `PlanStore`'s members that settle, push and cancel an occurrence take a rule's next occurrence, its skipped ones and its end (§9:3). No capability is added (§8:1), and `Settings` gains no field.
- **Partially supersedes**, in the clauses §12's first table names: ADR-0307, ADR-0317, ADR-0338 and ADR-0350.

## Context

**The question.** A person asks "remind me at 8 to call Mom", "every weekday at 7, the
bins", "in 20 minutes, check the oven". How does Aether set that, say it back, say it at
that time, and take "done", "snooze 10 minutes" and "skip tomorrow's" in its stride?

**What is already ratified.**

- ADR-0350 §11:1: "A decision on reminders builds a reminder as a scheduled task under this
  decision, set by the person, whose when is an instant or a rule. It builds no channel,
  store or sensor of its own for them."
- ADR-0350 left four things to this decision. §5:2: "How a local time stated without an
  offset is read in a person's zone is the reminders decision's." §5:3: a rule's
  "vocabulary, its zone semantics, its end and what changing one occurrence means are a
  later decision's. Until that decision lands, no capability offers a rule and no task holds
  one." §9:4: "Changing one occurrence of a rule is the reminders decision's." Its §14 adds
  "the read-back's wording, and the set, change, cancel and done phrases for reminders".
- ADR-0350 already rules what a reminder needs most of. A task informs and authorizes
  nothing (§3:9, ADR-0292 §5:6). A missed occurrence is pushed once, marked late (§8:9), a
  rule that missed several pushes only its latest (§8:10), and a message whose delivery is
  unknown gets one second try (§8:6), each stated in the input with no wording required.
  Snoozing is a new spawn (§9:3), "make it 9" a replace (§9:4), and there is no change
  capability. Nothing is cancelled when a place is gone (§5:9). Where its activation cannot
  finish, the fixed *couldn't finish* goes into each suggested place on its place list
  (§6:7).
- ADR-0338 §3:6: "Where a person's zone is set, it is the zone of every time code reads for
  that person: planning's current time (ADR-0307 §6:1) and the quiet windows (ADR-0130
  §6:4). Where it is empty, or the activation is no person's, those reads use
  `Settings.timezone`."

**What the tree holds,** on `origin/main` at `77ac36716`, after ADR-0350's lanes TS1
([#3428](https://github.com/leonapivato/ai-assistant/pull/3428)), TS1b
([#3431](https://github.com/leonapivato/ai-assistant/pull/3431)) and TS2
([#3432](https://github.com/leonapivato/ai-assistant/pull/3432)):

- `TaskWhen` in `core/types.py` is `DueNow | DueAt | DueAfterTasks`, with no rule, and
  `ScheduledTask.occurrences` holds exactly one occurrence (`max_length=1`).
- `SPAWN` in `orchestration/task_scheduler.py` takes `instruction`, `at` ("an ISO 8601
  instant with its UTC offset"), `delay_minutes`, `after`, `places` and `replaces`.
- The Task Scheduler's renderings (`when_text`, `task_input`, `lineage_steps`) take one zone,
  which the composition root wires as `settings.timezone` (`TaskSchedulerSeams(zone=...)` in
  `app/composition.py`), not the person's profile zone that `person_zone` in
  `orchestration/person_block.py` reads.
- `PhasePath._couldnt_finish` in `orchestration/phase_path.py` writes `COULDNT_FINISH`, with
  the listing of effects, into each suggested place of a task's activation.

**Why it needs a decision.** The four points ADR-0350 left open are decisions. The owner's
ruling that a reminder's fallback is its own words changes ADR-0350 §6:7's *couldn't
finish* line for reminders, and the rule changes `core`.

## Decision

We will make a reminder a scheduled task the person set, marked as a reminder, whose
instruction is what they are to be reminded of. Its when is a fixed instant, or a daily,
weekday or weekly rule at a local time that follows the person's current zone. The spawn's
result says it back from the stored record, in the person's zone, with the places it will
speak in. "Done", "snooze" and "skip tomorrow's" are ADR-0350's cancel and spawn. Where its
activation cannot finish, its suggested places get the reminder's own words as a fixed line.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner ratifies it
> after their review. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is the lanes §10 sets out, each held by milestone 15,
> and no lane is dispatched before this decision merges.

### 2. A reminder is a scheduled task

> **Normative.** A **reminder** is a scheduled task under ADR-0350 that carries the
> **reminder mark**, written when it is set and never changed. This decision builds no
> channel, store, sensor or capability of its own for reminders.

> **Normative.** A spawn is a reminder only where the spawning activation's input carries the
> person's authority (ADR-0292 §5:5), so its author is the person (ADR-0350 §3:7). A spawn
> marked as a reminder from any other activation is refused as *not done*, with the reason,
> and writes nothing.

> **Normative.** A reminder's instruction is what the person is to be reminded of, worded
> for them, with every referent resolved ("call Mom about the passport"), and not an
> instruction to the assistant ("remind the user to…").

> **Normative.** A reminder suggests at least one place (ADR-0350 §5:5). A spawn marked as a
> reminder that suggests none is refused as *not done*, with the reason, and writes nothing,
> unless it replaces a reminder, whose places it takes (ADR-0350 §9:4).

> **Normative.** A spawn that names a reminder it replaces is a reminder, and a reminder
> replaces only a reminder. A spawn breaking either is refused as *not done*, with the
> reason, and writes nothing.

So a reminder is the person's, informs the activation it starts and authorizes nothing
(ADR-0350 §3:9). The assistant's own follow-up ("I'll check back tomorrow") is a scheduled
task without the mark, as ADR-0350 has it. A reminder must suggest a place because its
read-back says where it will speak (§6), and no place is suggested by default (ADR-0350
§5:5). Its activation still chooses among its whole place list (ADR-0350 §6:7), the line's
chat included where the line is connected.

### 3. One-off times, and local times

> **Normative.** A one-off reminder's when is an instant (ADR-0350 §5:2), fixed when it is
> set. No change of the person's zone moves it.

> **Normative.** A spawn may state an instant as a local date and time with no UTC offset.
> The hub reads it in the zone the spawn names, an IANA zone name, and in the person's zone
> where it names none, and resolves it to an instant when the task is written. This holds for
> every spawn, a reminder or not.

> **Normative.** The **person's zone** is the zone ADR-0338 §3:6 reads for the person the
> task is for: their profile zone where it is set, and `Settings.timezone` otherwise, read
> through `person_zone`, the one function that reads it.

> **Normative.** A local time that a daylight-saving change skips resolves to the first
> instant after the gap. A local time it repeats resolves to the earlier of the two
> (`fold=0`).

> **Normative.** A spawn stating both a UTC offset and a zone name is refused as *not done*,
> with the reason, and writes nothing. A zone name that `zoneinfo` does not resolve is
> refused the same way.

A one-off is predictable: "remind me at 8 tonight" is 8 tonight where the person asked it,
and the read-back (§6) catches a wrong zone. "At 8 Lisbon time" names its zone. Whether "at
8", said at 9 in the morning, means 8 tonight is planning's reading of the words; the hub
refuses an instant earlier than now (ADR-0350 §4:5).

### 4. The rule

> **Normative.** A reminder's when may be a **rule**, and only a reminder's may (ADR-0350
> §5:3). A spawn stating a rule that is not marked as a reminder is refused as *not done*,
> with the reason, and writes nothing.

> **Normative.** A rule is, in version 1, one of: **daily**; **weekdays**, Monday to Friday;
> or **weekly**, on a set of one or more days of the week. Each holds a local time of day,
> to the minute. The set is closed, added to and never renamed.

> **Normative.** A rule may name an IANA zone. A rule naming one has every occurrence
> computed in it. A rule naming none follows the person's current zone: each occurrence's
> instant is computed in the person's zone as it stands when that occurrence is computed.

> **Normative.** A rule may hold a **from**, a local date before which no occurrence falls,
> and an **until**, the last local date on which one may fall. A from that has passed
> constrains nothing, so a replace may keep it. The hub refuses as *not done*, with the
> reason, a rule whose until is earlier than its from, or that yields no occurrence later
> than now.

> **Normative.** A rule's first occurrence is the first instant its rule yields that is later
> than now and on or after its from, computed when the task is written.

> **Normative.** When a pushed occurrence of a rule takes its outcome (ADR-0350 §7:6,
> §8:1–§8:7), its next occurrence is the first instant the rule yields that is later than
> the instant the ended one was due, computed then, even where that instant has passed. The
> plan store writes the ended one's outcome and the next pending occurrence in one step, so a
> rule is never without a pending occurrence until it ends. A next occurrence that has passed
> is a missed one, which §4:8 pushes.

> **Normative.** A rule **ends** when the next instant it would yield falls after its until,
> or when its pending occurrence ends *cancelled*, by a cancel (ADR-0350 §9:5) or by a
> cascade (§7:5). No next occurrence is computed after either, and ADR-0350 §7:8 then
> removes the task once nothing of it is live.

> **Normative.** Where a rule's pending occurrence is due, the sensor takes its stored
> instant unchanged, and computes from the rule each instant the rule yields after it, up to
> now. Where that finds any, the occurrence missed more than one (ADR-0350 §8:10): in the step
> that marks the latest pushed (ADR-0350 §7:5), the plan store records the pending one and
> each other earlier one *skipped*, each with the instant it was due, as the sensor gave
> them. Where it finds none, the pending occurrence itself is pushed.

> **Normative.** A daylight-saving change reaches a rule's occurrences as §3:4 rules for a
> local time.

> **Normative.** A task with a rule keeps every occurrence while the Task Scheduler holds the
> task, so each message one of them wrote still links to its task (ADR-0350 §9:1–§9:2), and
> never reuses an occurrence's number. What ran stays in the episodes (ADR-0350 §7:9).

"Every day at 8" means 8 wherever the person is: a rule follows their zone from the
occurrence after the zone changes. The occurrence already pending was computed in the old
zone and keeps its instant, so after a move one occurrence may come at the old zone's 8.
"Every weekday at 9:30, New York time" names its zone and stays in it. A rule holds one
pending occurrence at a time, so it counts one toward the pending limit (ADR-0350 §9:8), and
it stays in the Task Scheduler until it ends.

### 5. Skipping, changing, and the plain words

> **Normative.** **Skipping** a rule's next occurrence, "skip tomorrow's", is a spawn
> replacing the reminder (ADR-0350 §9:4) with the same rule, whose from is the local date
> after the skipped occurrence's. Where the rule yields nothing after the skipped one before
> its until, skipping it is a cancel (ADR-0350 §9:5).

> **Normative.** Only a rule's next occurrence can be skipped. Changing one occurrence of a
> rule, "tomorrow at 9 instead", is skipping it and a one-off reminder for the new time,
> two spawns in one round.

> **Normative.** Changing a reminder, "make it 9", is a spawn replacing it (ADR-0350 §9:4):
> for a one-off, at the new instant; for a rule, the same rule at the new time of day.

> **Normative.** **Snoozing**, "snooze 10 minutes" right after a reminder's message, is a new
> reminder (ADR-0350 §9:3), one-off, with the same instruction, suggesting the place the
> person said it in.

> **Normative.** "Done", or "I already took it", for an occurrence not yet said, is a cancel
> (ADR-0350 §9:5) of a one-off reminder, and a skip (§5:1) of a rule's. For an occurrence
> already said, it is no call: that occurrence has ended.

> **Normative.** "Cancel the bins one" is a cancel (ADR-0350 §9:5), which for a rule ends it
> (§4:7).

Skipping is a replace, not a cancel of one occurrence alone, for three reasons. A cancel then
keeps one meaning, the whole reminder, and ADR-0350 §9:5 and the cancel's arguments are
untouched. The replace's result is a read-back of the whole new schedule ("every day at 8:00
PM, from Thursday 23 October"), so the person hears what is now set. And a rule holds one
pending occurrence, so there is no later occurrence a cancel could name. A replace takes the
replaced reminder's suggested places (ADR-0350 §9:4), so "make it 9 on Telegram" is a cancel
and a new reminder.

### 6. The read-back, and the renderings

> **Normative.** Every rendering of a reminder's times, in a spawn's result (ADR-0350 §4:8),
> the list pull (§4:6), its activation's input (§6:2) and the schedule's window (§6:5), is in
> the person's zone, or, for a rule naming a zone, in that zone, which the rendering then
> names.

> **Normative.** The **read-back** is the hub's rendering in a spawn's result of a reminder
> it wrote, from the stored record. It gives the next occurrence's weekday, date and local
> time, with a relative word where it falls today or tomorrow; for a rule, the rule in words
> with its from and until; and each place it suggests, by its description, with the place
> the reminder was set in as *here* ("Tonight, Tuesday 21 October, at 8:00 PM, on
> Telegram"). Its exact words are the lane's (§10).

> **Normative.** Planning's instruction says that a reminder is said back from the read-back,
> and never from planning's own reckoning of the time.

### 7. A reminder coming due

> **Normative.** A reminder's occurrence starts an ordinary activation under ADR-0350 §6.
> Its input states, beside what ADR-0350 §6:2 lists, that it is a reminder the person asked
> for, its rule in words where it has one, and how many occurrences it skipped where §4:8
> skipped any.

> **Normative.** A late reminder is ADR-0350 §8:9's, and a second try §8:6's. The input
> states each fact, and nothing in this decision requires how the message words either.

> **Normative.** A reminder comes due at the instant its when gives. No rule of this decision
> holds, delays or drops it for the hour it falls at.

> **Normative.** Where a reminder's activation does not finish, in the cases ADR-0317 §3:2–
> §3:4 name, its **fixed line** is written in place of *couldn't finish*: `Reminder:` and the
> reminder's instruction ("Reminder: call Mom"), followed by the listing of effects ADR-0317
> §3:1 gives where there is any. It goes into each suggested place on its place list, and
> nowhere where none is left (ADR-0350 §6:7).

> **Normative.** The fixed line is claimed and written as *couldn't finish* is, and the
> episode freezes as ADR-0317 §3:5 classifies an activation that did not finish.

A model writes the reminder in words that fit (ADR-0350 §6:10), and the facts it rests on,
late or a second try, are the hub's. Where no model can, because the model is down or the
round limit ended it, the person still gets what they asked to be reminded of rather than "I
couldn't finish this." A stop and a restart write nothing (ADR-0317 §3:6), and a restart is
settled by ADR-0350 §8. Quiet hours are not decided here (§11): the asked time wins.

### 8. The capability surface

> **Normative.** Reminders use ADR-0350 §4:1's three capabilities, spawn, cancel a scheduled
> task and list scheduled tasks, and no other. Spawn gains three arguments: the reminder
> mark; a rule (§4:2–§4:4); and a zone name (§3:2, §4:3). Its instant argument also takes a
> local date and time with no offset (§3:2). Exact names are the lane's (§10), within this
> clause.

> **Normative.** The list pull shows each scheduled task's reminder mark, and for a rule its
> rendering in words and its next occurrence (§6:1).

> **Normative.** Planning's instruction adds to ADR-0350 §9:3's four things, and to nothing
> else: a reminder is marked as one and its instruction is what to remind of (§2:3); a local
> time is stated with no offset unless the person named one, and a zone only where the
> person named one; the read-back is said back (§6:3); and skip, done and snooze are §5's
> calls.

> **Normative.** Planning in a reminder's activation is given no instruction of this
> decision's beyond ADR-0350's for an activation the Task Scheduler started. Its input says
> it is a reminder (§7:1).

### 9. The code it binds

> **Normative.** `core/types.py`'s scheduled task (`ScheduledTask`, and `TaskSpawn` for a
> spawn) gains the reminder mark (§2:1). `TaskWhen` gains a rule, a frozen pydantic model
> holding its kind as a closed `StrEnum`, its days for a weekly rule, its local time, and
> optionally its zone, its from and its until. A task with a rule holds more than one
> occurrence over its life, numbered from one. Validators refuse a rule on a task without
> the mark (§4:1), a reminder whose author is not the person (§2:2), a reminder suggesting no
> place (§2:4), a weekly rule with no day, and an until earlier than a from (§4:4). Exact
> names are the triad's.

> **Normative.** `TaskRefusal` gains a member for each refusal of §2:2, §2:4, §2:5 and §4:1
> that the plan store makes, added and never renamed. The other refusals of §3:5 and §4:4
> are the spawn's, made before the store is reached, each *not done* with its reason.

> **Normative.** `PlanStore` changes as follows. `PlanStore.settle_occurrence`, for a task
> with a rule, takes the next occurrence's instant, or none where the rule has ended, and
> writes it with the outcome in one step (§4:6). `PlanStore.mark_occurrence_pushed` takes,
> for a missed occurrence of a rule, the instants of the occurrences it records skipped and
> of the one it pushes, written in that one step (§4:8). `PlanStore.cancel_scheduled_task`
> ends a rule (§4:7). Occurrences are kept as §4:10 rules. `PlanStore.write_scheduled_task`
> makes §2:5's check in its step, against the task it replaces. `PlanExport` carries the new
> fields and its `schema_version` advances. Exact signatures are the triad's.

> **Normative.** The plan store is a store under ADR-0326: the lane that changes its schema
> ships the upgrade (ADR-0326 §4:1).

> **Normative.** The rule's arithmetic, a rule's first, next and latest missed instant in a
> zone, is one function, which every caller uses. The plan store does not compute an
> instant: it writes what the caller computed in the person's zone.

> **Normative.** `PROTOCOL_VERSION` advances only in a lane whose change alters a type the
> wire carries (ADR-0350 §12:6).

### 10. Delivery

The lanes, each after this decision merges `Accepted`, held by milestone 15:

1. **R1, the `PlanStore` change with its primary implementation** (ADR-0137 §2:1): §9:1's
   types, §9:2's refusals, §9:3's members and `PlanExport`, the conformance suite's cases, the
   canonical fake and the SQLite plan store in `planning/` with its upgrade.
2. **R2, reminders in `orchestration/`:** spawn's arguments (§8:1) and their refusals (§3:5,
   §4:4), local times (§3), the rule's arithmetic (§9:5) and the sensor's use of it (§4:5–§4:8),
   the renderings in the person's zone (§6), the reminder's input (§7:1), the fixed line
   (§7:4–§7:5), the list pull's fields (§8:2), planning's instruction (§8:3) and the
   composition wiring in `app/`.

> **Normative.** R1 may touch `core`, `testing`, `planning` and their tests, permitted
> expressly here as one unit, and no other package. R2 may touch `orchestration`, `app`,
> `prompt_cases/` and their tests, and `scripts/prompt_replay.py` with its tests where a case
> needs it, and nothing else.

> **Normative.** R1 merges before R2, and R2 is briefed only after R1 has merged (ADR-0137
> §4:1).

> **Normative.** R1's and R2's tests together include: a weekdays rule across a weekend; a
> weekly rule on two days; an until on which the last occurrence falls, after which the task
> is removed; a local time in a daylight-saving gap and one in a repeat, for a one-off and for
> a rule; the person's zone changed while a rule's occurrence is pending, which keeps that
> instant and computes the next in the new zone; a rule naming a zone, which a change of the
> person's zone does not move; a profile zone that differs from `Settings.timezone`, which a
> local time, a rule and every rendering follow; a cancel of a rule, after which no
> occurrence is computed; a skip, whose replace's from is the day after; an occurrence's
> outcome and the next occurrence written in one step, with no instant at which the task has
> nothing pending; a rule missed for three days, which pushes one late occurrence stating
> that it skipped two; a pending occurrence due under the old zone, found after the person's
> zone changed, which is still pushed; a restart days after a rule's pushed occurrence whose message is
> confirmed done, which settles it and then pushes the latest missed one late; a skip of a
> bounded rule's last occurrence, which is a cancel; "make it 9" on a rule whose from has
> passed, which replaces it; the fixed line on the round limit, written into each suggested place
> on the list with the effects listed, and written nowhere where every suggested place is
> gone; a stop and a restart, which write no fixed line; and each refusal of §2:2, §2:4,
> §2:5, §3:5, §4:1 and §4:4.

> **Normative.** R2 adds synthetic prompt cases (ADR-0337 §3) for at least: "remind me at 8 to
> call Mom", said at 9 in the morning, which is a reminder at 20:00 local with no offset;
> the same said at 7 in the morning, at 08:00; "every weekday at 7, the bins", which is a
> weekdays rule; "I already took it" before a one-off reminder shown by its label falls
> due, which is its cancel; "skip tomorrow's" for a daily reminder, which is a replace from
> the day after tomorrow; "snooze 10 minutes" right after a reminder's message, which is a
> one-off reminder ten minutes from now with the same instruction; "done" right after a
> reminder's message, which is no call; "make it 9" for a daily reminder not yet said, which
> replaces it with the same rule at the new time; and a reminder's activation, which writes
> one message into its suggested place.

### 11. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Monthly rules, "the first Monday", and times relative to an event | Each a later decision, added to §4:2's set |
| "Keep reminding me until I say done" | After the pilot, starting with medicine |
| Quiet hours, as a person-model preference the activation judges delivery by; retiring ADR-0130's quiet windows; a "silent" option for a message | The decision on speaking as a call in every place |
| Skipping an occurrence other than a rule's next | A later decision, if the pilot asks for it |
| Changing a reminder's places by a replace | ADR-0350 §9:4 keeps them; a later decision on which places a spawner may suggest |
| Reminders for another member of a household | The members design ([#691](https://github.com/leonapivato/ai-assistant/issues/691)) |
| Conditions in the world ("when I get home") | Watches ([#2585](https://github.com/leonapivato/ai-assistant/issues/2585)) |
| Merging reminders that fall due together | The operations between activations (ADR-0350 §14) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 12. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0307 | §3:7's fixed *couldn't finish* message, for a reminder's activation: its fixed line in place of it | §7:4–§7:5 |
| ADR-0317 | §3:1's fixed *couldn't finish* message, for a reminder's activation: its fixed line in place of it, followed by the same listing of effects, into its suggested places on its list | §7:4–§7:5 |
| ADR-0338 | §3:6, in the addition alone: a reminder's local times, its rule's occurrences and the renderings of its times are read in the person's zone | §3:2–§3:3, §4:3, §6:1 |
| ADR-0350 | §3:6, §4:1 and §12:1, in the addition alone: a task's reminder mark, which a spawn states, and a rule as a when with more than one occurrence; §6:2, in the addition alone: a reminder's input also states that it is one and its rule; §4:5, in the addition alone: a spawn is also refused on §2's, §3:5's and §4's grounds; §5:2, in the addition alone: a spawn may state a local date and time with no offset, read in a named zone or the person's; §6:7's *couldn't finish*, for a reminder's activation: its fixed line; §7:7, for a task with a rule: its next occurrence is written with the ended one's outcome in one step, and none after its until or a cancel; §12:3, in the addition alone: the members §9:3 changes | §2, §3:2, §3:5, §4, §7:1, §7:4, §8:1, §9:1–§9:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0350 §5:3, §9:4's last sentence, §11:1 and §14's reminders row | Nothing: this is the decision they name, and it builds no channel, store or sensor of its own |
| ADR-0350 §3:9, ADR-0292 §5:5–§5:6 | Nothing: a reminder is set only from input carrying the person's authority, and informs and authorizes nothing |
| ADR-0350 §5:5–§5:6, §5:8–§5:9, §6:7 | Nothing beyond §2:4's one place: no place is suggested by default, a reminder speaks only on its place list, and nothing is cancelled when a place is gone |
| ADR-0350 §6:3 | Nothing: a reminder's instruction is the creator's instruction as planning wrote it |
| ADR-0350 §8:6, §8:9–§8:10 | Nothing: a reminder's second try and lateness are those clauses, and §4:8 finds the latest missed occurrence for §8:10 |
| ADR-0350 §9:3–§9:5, §4:4 | Nothing: snooze is a new spawn, a change and a skip are replaces, a cancel ends what is pending, each under §4:4's authority |
| ADR-0350 §9:8 | Nothing: a rule holds one pending occurrence, which counts once |
| ADR-0306 §5:9 | Nothing: the backstop refuses the same reminder twice in one matter unless planning marks it deliberate |
| ADR-0317 §3:5–§3:6 | Nothing: an activation that writes the fixed line did not finish, and a stop or a restart writes nothing |
| ADR-0130 | Nothing: a reminder is no notification candidate, and its quiet windows reach none |
| ADR-0337 §3 | Nothing: R2's cases are synthetic cases under it |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0307, ADR-0317, ADR-0338 and ADR-0350, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**

| Situation | What happens |
| --- | --- |
| "Remind me at 8 to call Mom", on the hub chat | A reminder for 8 tonight, said back as "Tonight, Tuesday 21 October, at 8:00 PM, here" (§6:2) |
| "Remind me on Telegram at 8", on the hub chat | It suggests the line's chat, and the read-back says "on Telegram" |
| "Every weekday at 7, the bins" | A weekdays rule at 07:00 in the person's zone (§4) |
| The person flies to Lisbon | A one-off keeps its instant; a rule follows from its next occurrence (§3:1, §4:3) |
| "Skip tomorrow's" | A replace from the day after, said back whole (§5:1) |
| "I already took it", before 8 | A cancel of the one-off, or a skip of the rule's (§5:5) |
| "Snooze 10 minutes", after it is said | A new one-off reminder (§5:4) |
| The model is down at 8 | "Reminder: call Mom" in its suggested places (§7:4) |
| The hub was down at 8 | Said once, the input stating it is late (ADR-0350 §8:9) |
| The conversation it was set in is deleted | Nothing is cancelled; it speaks on the line where the line is connected, or writes nothing (ADR-0350 §5:9) |

**What it costs.**

- **A model call per occurrence**, as every task's (ADR-0350's Consequences). The fixed line
  costs none.
- **One occurrence after a move may come at the old zone's time** (§4:3).
- **A rule's record grows by one occurrence each time it falls due** while it is held
  (§4:10). Pruning old ones would cut their messages' links to the task, which ADR-0350
  §9:1 keeps, so it waits for a decision that supersedes that clause, if the size ever
  matters.
- **Only a rule's next occurrence can be skipped**, and "tomorrow at 9 instead" is two
  spawns (§5:2).
- **A reminder must name a place**, so a reminder set where none can be suggested is
  refused (§2:4).
- **Machinery and records.** A change to the `PlanStore` triad with an upgrade, a rule type,
  three spawn arguments, the rule's arithmetic in one function, the fixed line, and header
  records on four ADRs. TS2's renderings move from `Settings.timezone` to the person's zone
  for reminders (§6:1).

**The cut, for the dispatcher.** §10's two lanes: R1 is the contract change with the SQLite
plan store, under ADR-0137 §2:1, and R2 every consumer, briefed against the merged
contract.

**What would reopen it.**

- People asking for monthly rules, or for skipping a later occurrence, in the pilot.
- A move whose one stale occurrence people notice.
- Read-backs that people correct often, which would show planning misreading local times.
- Fixed lines that fire often, which would show reminders' activations failing.

## Alternatives considered

- **A clock channel of its own,** as the draft of 2026-10-21 had it. Dropped by the owner's
  walk: a reminder is a scheduled task (ADR-0350 §11:1).
- **A reminder as its conversation's own activation,** with the say-only limit, the report
  kind and grouping at the sensor, all from the old draft. Dropped: ADR-0350 §6:9, §6:10 and
  §7:4 replace each, and a chain's last step says what it found.
- **Deleting a conversation cancelling its reminders,** the old walk's answer 9. Reversed by
  the owner on 2026-10-25: nothing is cancelled when a place is gone (ADR-0350 §5:9).
- **"Skip tomorrow's" as a cancel of the next occurrence alone.** Rejected: it gives cancel
  two meanings, changes ADR-0350 §9:5's cancel and its arguments, and says back nothing of
  what is left set (§5).
- **A capability of its own for reminders,** a `remind` beside spawn. Rejected: it would
  duplicate spawn's checks, effect record and backstop, and the owner's walk made reminders
  scheduled tasks.
- **A second text beside the instruction,** a short line for the fixed fallback. Rejected:
  two texts drift. The reminder's instruction is written to be said, so it is the fixed
  line's text (§2:3).
- **Re-resolving a pending occurrence when the person's zone changes.** Rejected for now: it
  would need every profile write to reach the plan store, for one occurrence's difference.
- **Storing a rule's occurrences as instants up front.** Rejected: "every weekday at 7"
  would not follow the person's zone or a daylight-saving change.
- **An iCalendar `RRULE` string as the rule.** Rejected for now, as the old draft did: a
  closed rule is one the hub validates whole and says back exactly, and it maps onto a
  subset of `RRULE` if the calendar needs one.
- **A rule on any scheduled task.** Rejected: ADR-0350 §11:1 gives the rule to reminders,
  the person's ask, and recurring work the person did not ask for is proactivity's.
- **A default place,** such as where it was set, or the line automatically. Rejected: the
  spawner suggests places and the read-back says where, so the old draft's question 2
  dissolves.
- **The generic *couldn't finish* for a reminder.** Replaced by the owner's ruling: the
  person still gets what they asked to be reminded of (§7:4).
- **A late or second-try wording in the fixed line or the message.** Rejected: the input
  states the facts, and nothing requires how a message says them (ADR-0350 §8:6, §8:9).
- **A quiet-hours rule here.** Not taken: quiet hours become a person-model preference that
  the activation judges delivery by, with the speaking decision (§11).
