# 340. A task the person sets may come due at a local time or on a rule in their zone, and is said back from the hub's record

- Status: Accepted
- Date: 2026-10-25
- Scope: reminders, and the other tasks a person sets, on the Task Scheduler. It covers a task the person set (§2), one-off times and local times (§3), the rule and its vocabulary (§4), skipping, changing and the plain words (§5), the read-back and the renderings (§6), a task coming due (§7), the capability surface and planning's instruction (§8), the code it binds (§9) and its delivery (§10). It is the reminders decision that [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md) §5:2, §5:3, §9:4 and §11:1 name. It rewrites the draft of 2026-10-21, which built reminders on a clock channel of their own, keeping what ADR-0350 §11 lists. §11 names what is not decided here.
- Dependency: [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md), [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0317](0317-an-activation-that-chose-to-say-nothing-has-finished.md) and [ADR-0337](0337-a-prompt-change-is-judged-on-a-regression-suite-with-repeated-samples-each-recorded-call-is-asked-what-it-had-to-guess-and-a-candidate-is-promoted-after-three-clean-days.md), as their status lines leave them.
- Authorization: the coordinator walked proposal [#3271](https://github.com/leonapivato/ai-assistant/pull/3271) on 2026-10-21, and the owner's walk of ADR-0350 from 2026-10-21 to 2026-10-25 replaced its channel with the Task Scheduler and listed what this rewrite keeps and drops (ADR-0350 §11). The owner ruled on 2026-10-25 that nothing is cancelled when a place is gone. The owner reviewed this rewrite on 2026-10-25 and ruled: there is no reminder mark, and a rule goes to any task the person set (§2, §4:1); there is no fixed fallback line, and a task that cannot finish is [#3435](https://github.com/leonapivato/ai-assistant/issues/3435)'s (§11); a task need not suggest a place (§6:2); every scheduled task's times render in the person's zone (§6:1); skipping a one-off is a cancel (§5:1), "usually it's just replacing it the next day unless it's already scheduled for the next day, which is just a cancel"; and quiet hours are no rule here, "nothing mechanical… it's something in the person model" (§7:3). The dispatcher assigned 0340. Ratification is the owner's, after their review.
- Milestone: [15, Task Scheduler: reminders and work that runs later](https://github.com/leonapivato/ai-assistant/milestone/15).
- **Changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `core/types.py`'s `TaskWhen` gains a rule, a scheduled task holds more than one occurrence where it has one, and a spawn carries a rule's first occurrence (§9:1). `TaskRefusal` gains this decision's refusal (§9:2). `PlanStore`'s member that writes a task writes a rule's first occurrence, its member that pushes an occurrence takes a rule's next occurrence and its skipped ones, and its cancel ends a rule (§9:3). No capability is added (§8:1), and `Settings` gains no field.
- **Partially supersedes**, in the clauses §12's first table names: ADR-0338 and ADR-0350.

## Context

**The question.** A person asks "remind me at 8 to call Mom", "every weekday at 7, the
bins", "in 20 minutes, check the oven", "every morning at 7, check the weather and tell me".
How does Aether set that, say it back, start it at that time, and take "done", "snooze 10
minutes" and "skip tomorrow's" in its stride?

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
- ADR-0350 already rules what a reminder needs most of. A task's author is the person where
  the spawning input carries their authority, and the assistant otherwise (§3:7). A task
  informs and authorizes nothing (§3:9, ADR-0292 §5:6). A missed occurrence is pushed once,
  marked late (§8:9), a rule that missed several pushes only its latest (§8:10), and a
  message whose delivery is unknown gets one second try (§8:6), each stated in the input
  with no wording required. Snoozing is a new spawn (§9:3), "make it 9" a replace (§9:4),
  and there is no change capability. No place is suggested by default (§5:5), and nothing is
  cancelled when a place is gone (§5:9). Where its activation cannot finish, the fixed
  *couldn't finish* goes into each suggested place on its place list (§6:7).
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
- The Task Scheduler's renderings (`when_text`, `task_input`, `lineage_steps`) and the Task
  Manager's local times take one zone, which the composition root wires as
  `settings.timezone` (`TaskSchedulerSeams(zone=...)` in `app/composition.py`), not the
  person's profile zone that `person_zone` in `orchestration/person_block.py` reads. That
  falls short of ADR-0338 §3:6 for every scheduled task
  ([#3434](https://github.com/leonapivato/ai-assistant/issues/3434)).

**Why it needs a decision.** The four points ADR-0350 left open are decisions, and the rule
changes `core`.

## Decision

We will treat a reminder as what it is in the store: a scheduled task the person set, with
no mark of its own. Any task the person set may come due at a fixed instant, or on a daily,
weekday or weekly rule at a local time that follows the person's current zone; no task the
assistant set holds a rule. Every scheduled task's times are read and rendered in the
person's zone. The spawn's result says the task back from the stored record, with the places
it suggests or that it suggests none. "Done", "snooze" and "skip tomorrow's" are ADR-0350's
cancel and spawn.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner ratifies it
> after their review. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is the lanes §10 sets out, each held by milestone 15,
> and no lane is dispatched before this decision merges.

### 2. A task the person set

> **Normative.** There is one kind of scheduled task (ADR-0350). A **task the person set**
> is one whose author is the person (ADR-0350 §3:7), which the plan store records when the
> task is written. This decision adds no mark and stores no other distinction. In its prose,
> a **reminder** is the everyday word for a task the person set whose job is to tell them
> something.

> **Normative.** What this decision gives only a task the person set, a rule (§4:1) and
> §5's plain words, it gives by that author. Its local times (§3), renderings and read-back
> (§6) and what it says of a task coming due (§7) hold for every scheduled task.

> **Normative.** This decision builds no channel, store, sensor or capability of its own
> (ADR-0350 §11:1).

So "remind me at 8 to call Mom" and "every morning at 7, check the weather and tell me" are
the same kind of thing: tasks the person set, whose instructions differ. A task's
instruction is planning's instruction to the activation it starts, as ADR-0350 §6:3 has it.
A task may suggest no place: "at 5, add milk to my shopping list" works with none suggested,
and its read-back says so (§6:2). Its activation still chooses among its whole place list
(ADR-0350 §6:7), the line's chat included where the line is connected, so the read-back
says that too. The assistant's own follow-up ("I'll check back tomorrow") and every step a
chain spawns are tasks the assistant set, as ADR-0350 has them.

### 3. One-off times, and local times

> **Normative.** A one-off task's when is an instant (ADR-0350 §5:2), fixed when it is set.
> No change of the person's zone moves it.

> **Normative.** A spawn may state an instant as a local date and time with no UTC offset.
> The hub reads it in the zone the spawn names, an IANA zone name, and in the person's zone
> where it names none, and resolves it to an instant when the task is written. This holds for
> every spawn, whoever its author.

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

> **Normative.** A task's when may be a **rule** only where its author is the person
> (ADR-0350 §3:7). A spawn stating a rule for a task whose author is not the person is
> refused as *not done*, with the reason, and writes nothing.

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

> **Normative.** When an occurrence of a rule is first marked pushed (ADR-0350 §7:5), its
> next occurrence is the **successor** of the instant it was due: the first instant the rule
> yields on a local date later than that instant's own, both read in the zone the rule is
> computed in then. The plan store writes the mark and the next pending occurrence in that
> one step, so a rule holds a pending occurrence until it ends, and a cancel, a replace or a
> skip (§5) reaches it while the occurrence before it still runs. Where the successor would
> fall after the rule's until, none is written. A push again after a restart (ADR-0350
> §8:5–§8:6) writes none, and nor does an occurrence's outcome (ADR-0350 §7:6–§7:7). A
> pending occurrence whose instant passes unpushed, as while the hub is down, is a missed
> one, which §4:8 pushes.

> **Normative.** A rule **ends** when the next instant it would yield falls after its until,
> or when its pending occurrence ends *cancelled*, by a cancel (ADR-0350 §9:5) or by a
> cascade (ADR-0350 §9:6). No next occurrence is computed after either, and ADR-0350 §7:8 then
> removes the task once nothing of it is live.

> **Normative.** Where a rule's pending occurrence that was never pushed is due, the sensor
> takes its stored instant unchanged and computes its successors in turn (§4:6), up to
> now. Where it finds none, the pending occurrence is pushed. Where it finds
> any, the rule missed more than one occurrence (ADR-0350 §8:10): in the step that marks the
> latest pushed (ADR-0350 §7:5), the plan store records the pending one and each other
> earlier one *skipped*, each with the instant it was due, as the sensor gave them. Either
> way, that step writes the pushed one's successor (§4:6), which the sensor gives too. An
> occurrence pushed again after a restart (ADR-0350 §8:5–§8:6) is pushed itself, its second
> try and its pushes kept. The successor its first push wrote stays pending, and this clause
> pushes it, or the latest missed one, once it is due, beside the one pushed again.

So no zone change gives one local day two occurrences: after a move west,
Monday's 8:00 in New York is followed by Tuesday's 8:00 in Los Angeles.

> **Normative.** A daylight-saving change reaches a rule's occurrences as §3:4 rules for a
> local time.

> **Normative.** A task with a rule keeps every occurrence while the Task Scheduler holds the
> task, so each message one of them wrote still links to its task (ADR-0350 §9:1–§9:2), and
> never reuses an occurrence's number. What ran stays in the episodes (ADR-0350 §7:9).

A rule goes to any task the person set, not to reminders alone, so "every morning at 7,
check the weather and tell me" is a daily rule on a work task. That is safe for three
reasons: a scheduled task carries no authority (ADR-0350 §3:9); every call its activation
makes is still checked by rule (ADR-0350 §6:10); and version 1's rules fall due at most once
a day. A task the assistant set holds no rule, because recurring work the person did not ask
for is proactivity's.

"Every day at 8" means 8 wherever the person is: a rule follows their zone from the
occurrence after the zone changes. The occurrence already pending was computed in the old
zone and keeps its instant, so after a move one occurrence may come at the old zone's 8.
"Every weekday at 9:30, New York time" names its zone and stays in it. A rule holds its
next occurrence pending, even while the one before it runs, so it counts one toward the
pending limit (ADR-0350 §9:8), or two while an occurrence of it waits to be pushed again
after a restart. It stays in the Task Scheduler until it ends.

### 5. Skipping, changing, and the plain words

> **Normative.** **Skipping** a rule's next occurrence, "skip tomorrow's", is a spawn
> replacing the task (ADR-0350 §9:4) with the same rule, whose from is the local date after
> the skipped occurrence's. Where the rule yields nothing after the skipped one before its
> until, skipping it is a cancel (ADR-0350 §9:5). Skipping a one-off task is a cancel
> (ADR-0350 §9:5).

> **Normative.** Of a rule, only its next occurrence can be skipped. Changing one occurrence
> of a rule, "tomorrow at 9 instead", is skipping it (§5:1) and a one-off task for the new
> time, in one round: two spawns, or, where the skip is a cancel because the skipped
> occurrence is the rule's last, a cancel and a spawn.

> **Normative.** Changing a task, "make it 9", is a spawn replacing it (ADR-0350 §9:4): for
> a one-off, at the new instant; for a rule, the same rule at the new time of day.

> **Normative.** **Snoozing**, "snooze 10 minutes" right after a task's message, is a new
> task (ADR-0350 §9:3), one-off, with the same instruction, suggesting the place the person
> said it in.

> **Normative.** "Done", or "I already took it", for an occurrence not yet said, is a cancel
> (ADR-0350 §9:5) of a one-off task, and a skip (§5:1) of a rule's. For an occurrence
> already said, it is no call: that occurrence has ended.

> **Normative.** "Cancel the bins one" is a cancel (ADR-0350 §9:5), which for a rule ends it
> (§4:7).

> **Normative.** §5:1–§5:6 are planning's calls for any task the person set, whatever its
> instruction asks.

A one-off has one occurrence, so skipping it leaves nothing set, and that is a cancel.
Skipping a rule's occurrence is a replace, not a cancel of one occurrence alone, for three
reasons. A cancel then keeps one meaning, the whole task, and ADR-0350 §9:5 and the
cancel's arguments are untouched. The replace's result is a read-back of the whole new
schedule ("every day at 8:00 PM, from Thursday 23 October"), so the person hears what is now
set. And a rule holds only its next occurrence pending, so there is no later occurrence a
cancel could name. A replace takes the replaced task's suggested places (ADR-0350 §9:4), so
"make it 9 on Telegram" is a cancel and a new task.

### 6. The read-back, and the renderings

> **Normative.** Every rendering of a scheduled task's times, whoever set it, is in the
> person's zone (§3:3): in a spawn's result, the list pull, its activation's input, the
> schedule's window and the Task Manager's queries (ADR-0350 §4:8, §4:6, §6:2, §6:5,
> §10:2). A rule naming a zone is rendered in that zone, and the rendering names it.

> **Normative.** The **read-back** is the hub's rendering in a spawn's result of the task it
> wrote, from the stored record. It gives the next occurrence's weekday, date and local
> time, with a relative word where it falls today or tomorrow, or, for a task waiting on
> named tasks (ADR-0350 §5:4), that it falls due when they end, and no time; for a rule, the
> rule in words with its from and until; and each place it suggests, by its description,
> with the place the task was set in as *here* ("Tonight, Tuesday 21 October, at 8:00 PM, on
> Telegram"), or, where it suggests none, that it suggests no place, adding, where the line
> is connected, that it may still message the person on the line (ADR-0350 §5:11, §6:7).
> Its exact words are the lane's (§10).

> **Normative.** Planning's instruction says that a task the person set is said back from
> the read-back, and never from planning's own reckoning of the time.

### 7. A task coming due

> **Normative.** A task's occurrence starts an ordinary activation under ADR-0350 §6. For a
> task with a rule, its input states, beside what ADR-0350 §6:2 lists, its rule in words,
> and how many occurrences it skipped where §4:8 skipped any.

> **Normative.** A late occurrence is ADR-0350 §8:9's, and a second try §8:6's. The input
> states each fact, and nothing in this decision requires how the message words either.

> **Normative.** A task comes due at the instant its when gives. No rule of this decision
> holds, delays or drops it for the hour it falls at.

A model writes the message in words that fit (ADR-0350 §6:10), and the facts it rests on,
late or a second try, are the hub's. Where its activation does not finish, ADR-0350 §6:7's
*couldn't finish* stands for every task. Saying what the task was, and falling back to the
line, is [#3435](https://github.com/leonapivato/ai-assistant/issues/3435)'s (§11). Quiet
hours are not decided here (§11): the asked time wins.

### 8. The capability surface

> **Normative.** Tasks the person sets use ADR-0350 §4:1's three capabilities, spawn, cancel
> a scheduled task and list scheduled tasks, and no other. Spawn gains two arguments: a rule
> (§4:2–§4:4) and a zone name (§3:2, §4:3). Its instant argument also takes a local date and
> time with no offset (§3:2). Exact names are the lane's (§10), within this clause.

> **Normative.** The list pull shows, for a task with a rule, its rule in words and its next
> occurrence (§6:1).

> **Normative.** Planning's instruction adds three things to ADR-0350 §9:3's four, and
> nothing else: a local time is stated with no offset unless the person named one, and a
> zone only where the person named one; the read-back is said back (§6:3); and skip, done
> and snooze are §5's calls.

> **Normative.** Planning in an activation a task's occurrence starts is given no
> instruction of this decision's beyond ADR-0350's for an activation the Task Scheduler
> started. Its input states its rule where it has one (§7:1).

### 9. The code it binds

> **Normative.** `core/types.py`'s `TaskWhen` gains a rule, a frozen pydantic model holding
> its kind as a closed `StrEnum`, its days for a weekly rule, its local time, and optionally
> its zone, its from and its until. A task with a rule holds more than one occurrence over
> its life, numbered from one. Validators refuse a rule on a task whose author is not the
> person (§4:1), a weekly rule with no day, and an until earlier than a from (§4:4).
> `TaskSpawn` carries, for a rule, the instant of its first occurrence (§4:5), as the caller
> computed it (§9:5), and none for any other when. `ScheduledTask` and `TaskSpawn` gain no
> other field. Exact names are the triad's.

> **Normative.** `TaskRefusal` gains a member for §4:1's refusal where the plan store makes
> it, added and never renamed. The refusals of §3:5 and §4:4 are the spawn's, made before
> the store is reached, each *not done* with its reason.

> **Normative.** `PlanStore` changes as follows. `PlanStore.write_scheduled_task`, for a
> rule, writes the first occurrence at the instant its spawn carries, in its one step with
> the task and its effect claim (ADR-0350 §3:3). It refuses, writing nothing, a rule spawn
> carrying no first instant and a spawn of any other when carrying one: each is the
> caller's error, raised as a `PlanningError`, and no `TaskRefusal`.
> `PlanStore.mark_occurrence_pushed`, for an occurrence of a rule first pushed, takes the
> next occurrence's instant, or none where the rule has ended (§4:7), and writes it pending
> in the step that marks the occurrence pushed (§4:6); for a missed occurrence of a rule, it
> also takes the instants of the occurrences it records skipped and of the one it pushes,
> written in that one step (§4:8). A push again after a restart takes and writes no next
> occurrence. `PlanStore.settle_occurrence` writes no next occurrence.
> `PlanStore.cancel_scheduled_task` ends a rule (§4:7). Occurrences are kept as §4:10 rules. `PlanExport` carries the new
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
   types, §9:2's refusal, §9:3's members and `PlanExport`, the conformance suite's cases, the
   canonical fake and the SQLite plan store in `planning/` with its upgrade.
2. **R2, the consumers in `orchestration/`:** spawn's arguments (§8:1) and their refusals
   (§3:5, §4:4), local times (§3), the rule's arithmetic (§9:5) and the sensor's use of it
   (§4:5–§4:8), every scheduled task's renderings in the person's zone, the Task Manager's
   included, which closes [#3434](https://github.com/leonapivato/ai-assistant/issues/3434)
   (§6:1), the read-back (§6:2), the input's rule and skipped count (§7:1), the list pull's
   fields (§8:2), planning's instruction (§8:3) and the composition wiring in `app/`.

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
> local time, a rule and every rendering follow; a task the assistant set, rendered in a
> profile zone that differs from `Settings.timezone`, in its spawn's result, the list pull,
> its activation's input, the schedule's window and the Task Manager's queries; a task
> suggesting no place, whose read-back says it suggests none, with the line connected and
> without it, adding only with it that the task may still message the person on the line;
> a task waiting on named tasks, whose read-back says it falls due when they end and gives
> no time; a rule's first occurrence, written at the instant its spawn carries with the
> task and its effect claim in one step; a rule spawn carrying no first instant, and a
> spawn of another when carrying one, each refused with nothing written; a cancel of a
> rule, after which no occurrence is computed; a skip, whose replace's from is the day after;
> an occurrence's first push and the next occurrence written in one step, with no instant
> before the rule ends at which it has nothing pending; a cancel while a rule's occurrence
> runs, which cancels the next and ends the rule; a skip while it runs, which replaces it; a rule missed for three days, which pushes one late
> occurrence stating that it skipped two; a pending occurrence due under the old zone, found
> after the person's zone changed, which is still pushed; a rule's occurrence pushed again
> after a restart days later, once with no effect claimed and once as a second try, each
> pushed itself with no next occurrence written, beside the latest missed one; a restart days after a rule's pushed
> occurrence whose message is confirmed done, which settles it and then pushes the latest
> missed one late; a skip of a bounded rule's last occurrence, which is a cancel; "make it 9"
> on a rule whose from has passed, which replaces it; a rule spawned from an activation whose
> input does not carry the person's authority, which is refused (§4:1); and each refusal of
> §3:5 and §4:4.

> **Normative.** R2 adds synthetic prompt cases (ADR-0337 §3) for at least: "remind me at 8 to
> call Mom", said at 9 in the morning, which is a task at 20:00 local with no offset;
> the same said at 7 in the morning, at 08:00; "every weekday at 7, the bins", which is a
> weekdays rule; "every morning at 7, check the weather and tell me", which is a daily rule
> on a task the person set; "I already took it" before a one-off task shown by its label
> falls due, which is its cancel; "skip tomorrow's" for a daily task, which is a replace from
> the day after tomorrow; "skip it" for a one-off task shown by its label, which is its
> cancel; "snooze 10 minutes" right after a task's message, which is a one-off task ten
> minutes from now with the same instruction; "done" right after a task's message, which is
> no call; "make it 9" for a daily task not yet said, which replaces it with the same rule at
> the new time; "tomorrow at 9 instead" for a daily task, which is a replace from the day
> after tomorrow and a one-off task at 09:00 tomorrow; the same for a daily task whose until
> is tomorrow, which is its cancel and that one-off task; and a reminder's activation, which
> writes one message into its suggested place.

### 11. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Monthly rules, "the first Monday", and times relative to an event | Each a later decision, added to §4:2's set |
| "Keep reminding me until I say done" | After the pilot, starting with medicine |
| Quiet hours, as a person-model preference the activation judges delivery by; retiring ADR-0130's quiet windows; a "silent" option for a message | The decision on speaking as a call in every place |
| A task whose activation cannot finish: saying what it was, and falling back to the line where no suggested place is left | [#3435](https://github.com/leonapivato/ai-assistant/issues/3435); until then ADR-0350 §6:7's *couldn't finish* |
| Skipping an occurrence other than a rule's next | A later decision, if the pilot asks for it |
| Changing a task's places by a replace | ADR-0350 §9:4 keeps them; a later decision on which places a spawner may suggest |
| Tasks for another member of a household | The members design ([#691](https://github.com/leonapivato/ai-assistant/issues/691)) |
| Conditions in the world ("when I get home") | Watches ([#2585](https://github.com/leonapivato/ai-assistant/issues/2585)) |
| Merging tasks that fall due together | The operations between activations (ADR-0350 §14) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 12. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0338 | §3:6, for a zone a spawn names: a local time the spawn states is read in that zone, and a rule naming a zone is computed and rendered in it, not in the person's zone | §3:2, §4:3, §6:1 |
| ADR-0350 | §3:6, §4:1 and §12:1, in the addition alone: a rule as a when, with more than one occurrence, which a spawn states with a zone name; §11:1, in the addition alone: a rule may be the when of any task the person set, not of a reminder alone, and of none the assistant set; §6:2, in the addition alone: a task with a rule has its input state its rule and its skipped count; §4:5, in the addition alone: a spawn is also refused on §3:5's and §4's grounds; §5:2, in the addition alone: a spawn may state a local date and time with no offset, read in a named zone or the person's; §7:5 and §7:7, for a task with a rule: its next occurrence is written in the step that first marks the one before it pushed, not when that one ends, and none after its until or a cancel; §12:3, in the addition alone: the members §9:3 changes | §3:2, §3:5, §4, §7:1, §8:1, §9:1–§9:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0350 §5:3, §9:4's last sentence and §14's reminders row | Nothing: this is the decision they name, and it builds no channel, store or sensor of its own |
| ADR-0350 §3:7, §3:9, ADR-0292 §5:5–§5:6 | Nothing: a task the person set is one whose author is the person, recorded as §3:7 rules, and it informs and authorizes nothing |
| ADR-0350 §5:5–§5:6, §5:8–§5:9, §6:7 | Nothing: no place is suggested by default, a task may suggest none, it speaks only on its place list, nothing is cancelled when a place is gone, and *couldn't finish* is §6:7's for every task |
| ADR-0338 §3:6, beyond a zone a spawn names | Nothing: a local time stated with no zone, a rule's occurrences and every rendering of a scheduled task's times are times code reads for the person the task is for, so they are in that person's zone (§3:3, §6:1); TS2's renderings in `Settings.timezone` fall short of it ([#3434](https://github.com/leonapivato/ai-assistant/issues/3434)), and R2 brings them to it |
| ADR-0350 §6:3 | Nothing: a task's instruction is planning's instruction to the activation it starts |
| ADR-0350 §8:6, §8:9–§8:10 | Nothing: a task's second try and lateness are those clauses, and §4:8 finds the latest missed occurrence for §8:10 |
| ADR-0350 §9:3–§9:5, §4:4 | Nothing: snooze is a new spawn, a change and a rule's skip are replaces, a one-off's skip is a cancel, a cancel ends what is pending, each under §4:4's authority |
| ADR-0350 §9:8 | Nothing: a rule holds its next occurrence pending, which counts once, and twice only while an occurrence is pushed again after a restart |
| ADR-0306 §5:9 | Nothing: the backstop refuses the same task twice in one matter unless planning marks it deliberate |
| ADR-0317 §3 | Nothing: a task's activation that does not finish writes *couldn't finish* as it rules |
| ADR-0130 | Nothing: a scheduled task is no notification candidate, and its quiet windows reach none |
| ADR-0337 §3 | Nothing: R2's cases are synthetic cases under it |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0338 and ADR-0350, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

**What becomes possible.**

| Situation | What happens |
| --- | --- |
| "Remind me at 8 to call Mom", on the hub chat | A task for 8 tonight, said back as "Tonight, Tuesday 21 October, at 8:00 PM, here" (§6:2) |
| "Remind me on Telegram at 8", on the hub chat | It suggests the line's chat, and the read-back says "on Telegram" |
| "Every weekday at 7, the bins" | A weekdays rule at 07:00 in the person's zone (§4) |
| "Every morning at 7, check the weather and tell me" | A daily rule on a task the person set, whose activation looks the weather up and says it (§4:1) |
| "At 5, add milk to my shopping list" | A task suggesting no place, said back as suggesting none, and, where the line is connected, as one that may still message the person there (§6:2) |
| The person flies to Lisbon | A one-off keeps its instant; a rule follows from its next occurrence (§3:1, §4:3); every task's times read in the new zone (§6:1) |
| "Skip tomorrow's" | For a rule, a replace from the day after, said back whole; for a one-off, a cancel (§5:1) |
| "I already took it", before 8 | A cancel of the one-off, or a skip of the rule's (§5:5) |
| "Snooze 10 minutes", after it is said | A new one-off task (§5:4) |
| The hub was down at 8 | Said once, the input stating it is late (ADR-0350 §8:9) |
| The conversation it was set in is deleted | Nothing is cancelled; it speaks on the line where the line is connected, or writes nothing (ADR-0350 §5:9) |

**What it costs.**

- **A model call per occurrence**, as every task's (ADR-0350's Consequences), and a rule on a
  work task makes that call every time it falls due.
- **One occurrence after a move may come at the old zone's time** (§4:3).
- **A rule's record grows by one occurrence each time it falls due** while it is held
  (§4:10). Pruning old ones would cut their messages' links to the task, which ADR-0350
  §9:1 keeps, so it waits for a decision that supersedes that clause, if the size ever
  matters.
- **Of a rule, only the next occurrence can be skipped**, and "tomorrow at 9 instead" is two
  calls (§5:2).
- **A task that cannot finish says only *couldn't finish***, as every task's activation does
  (ADR-0350 §6:7), until #3435.
- **Machinery and records.** A change to the `PlanStore` triad with an upgrade, a rule type,
  two spawn arguments, the rule's arithmetic in one function, and header records on two
  ADRs. TS2's renderings move from `Settings.timezone` to the person's zone for every
  scheduled task (§6:1), which closes #3434.

**The cut, for the dispatcher.** §10's two lanes: R1 is the contract change with the SQLite
plan store, under ADR-0137 §2:1, and R2 every consumer, briefed against the merged
contract.

**What would reopen it.**

- People asking for monthly rules, or for skipping a later occurrence, in the pilot.
- A move whose one stale occurrence people notice.
- Read-backs that people correct often, which would show planning misreading local times.
- Rules on work tasks whose cost the person did not expect.

## Alternatives considered

- **A clock channel of its own,** as the draft of 2026-10-21 had it. Dropped by the owner's
  walk: a reminder is a scheduled task (ADR-0350 §11:1).
- **A reminder as its conversation's own activation,** with the say-only limit, the report
  kind and grouping at the sensor, all from the old draft. Dropped: ADR-0350 §6:9, §6:10 and
  §7:4 replace each, and a chain's last step says what it found.
- **A reminder mark** on the scheduled task, written when it is set, with rules for marked
  tasks alone. Dropped by the owner on 2026-10-25, for three reasons. The task's author
  already records who set it (ADR-0350 §3:7). The mark gated rules too narrowly, so "every
  morning at 7, check the weather and tell me" had no rule. And its only real job was the
  fixed fallback line, which is now parked as #3435.
- **A fixed fallback line for a reminder,** `Reminder:` and its instruction in place of
  *couldn't finish*. Dropped with the mark by the owner on 2026-10-25: without a mark there
  is no reminder to give it to. Saying what a task was when it cannot finish is #3435's, for
  every task.
- **A reminder that must suggest a place.** Dropped by the owner on 2026-10-25: some tasks
  the person sets need no place ("at 5, add milk to my shopping list"), and the read-back
  says it suggests none (§6:2).
- **Deleting a conversation cancelling its reminders,** the old walk's answer 9. Reversed by
  the owner on 2026-10-25: nothing is cancelled when a place is gone (ADR-0350 §5:9).
- **"Skip tomorrow's" as a cancel of the next occurrence alone.** Rejected: it gives cancel
  two meanings, changes ADR-0350 §9:5's cancel and its arguments, and says back nothing of
  what is left set (§5).
- **A capability of its own for reminders,** a `remind` beside spawn. Rejected: it would
  duplicate spawn's checks, effect record and backstop, and the owner's walk made reminders
  scheduled tasks.
- **Re-resolving a pending occurrence when the person's zone changes.** Rejected for now: it
  would need every profile write to reach the plan store, for one occurrence's difference.
- **Storing a rule's occurrences as instants up front.** Rejected: "every weekday at 7"
  would not follow the person's zone or a daylight-saving change.
- **An iCalendar `RRULE` string as the rule.** Rejected for now, as the old draft did: a
  closed rule is one the hub validates whole and says back exactly, and it maps onto a
  subset of `RRULE` if the calendar needs one.
- **A rule on a task the assistant set.** Rejected: recurring work the person did not ask
  for is proactivity's.
- **A default place,** such as where it was set, or the line automatically. Rejected: the
  spawner suggests places and the read-back says where, so the old draft's question 2
  dissolves.
- **A late or second-try wording in the message.** Rejected: the input states the facts, and
  nothing requires how a message says them (ADR-0350 §8:6, §8:9).
- **A quiet-hours rule here.** Not taken, by the owner's ruling: quiet hours become a
  person-model preference that the activation judges delivery by, with the speaking
  decision (§11).
