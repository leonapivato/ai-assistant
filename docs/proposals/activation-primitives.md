# Operations between activations, and the Task Scheduler

**The question.** Activations run side by side. How does one start another, now or later?
How is one stopped? How do two that run at the same time learn from each other, and when
do they become one? This proposal answers with three operations (spawn, stop and share),
merge built from two of them, and one place, the **Task Scheduler**, that every spawn goes
through. A view over it, the **Task Manager**, is the one way in from outside.

This is a proposal for the owner's design walk. It records the walk of 2026-10-21 to
2026-10-24, in which the owner ruled each part. It would convert into two ADRs:

- **A**, the operations between activations (§§1–5);
- **B**, the Task Scheduler and the Task Manager (§§6–11).

ADR-0340 (reminders, #3271) would then be rewritten on top of B (§11).

## Where it came from

The owner, 2026-10-21: *"What if there was some basic operations that can be done in
parallel activations, such as merging … Or do these operations merge, fork, split, cover,
essentially anything that could happen?"*

The walk narrowed that to three operations, plus merge as a share and a stop. Along the
way the owner set the principles the rest follows:

- **Spawned work is ordinary.** *"Things like the reminder or background task are just
  normal activations that might have spawned from a certain conversation, but they don't
  live there."*
- **A place ties an activation to nothing.** It is only what caused the activation.
- **The machinery is uniform.** *"I like how a spawn is just an actuator action in the
  place, which gets sensed by the sensor and starts an activation, it's its own loop."*
- **Do the simple version.** *"For now, do a simple design that works. Don't worry much
  about who and what and privacy. That stuff will be addressed later."*

**What it assumes.** Outside content, disclosure (who may see what) and authority
(approvals) are other designs, and this proposal assumes they work. Whatever crosses
between activations carries its author, its authority and its marks. The gaps those
designs must close are listed under *What it leaves open*. The owner: *"Just note that the
gaps need to be closed."*

## Baseline

**Wiki, read at revision `84f20c8`:**
[Concurrent activations](https://github.com/leonapivato/ai-assistant/wiki/Concurrent-activations),
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller),
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Sensors](https://github.com/leonapivato/ai-assistant/wiki/Sensors),
[Internal sensors](https://github.com/leonapivato/ai-assistant/wiki/Internal-sensors),
[Place window](https://github.com/leonapivato/ai-assistant/wiki/Place-window),
[Episode window](https://github.com/leonapivato/ai-assistant/wiki/Episode-window).

**ADRs it reads:**

- **ADR-0292,** the channel model:
  - §1, the edge: sensors and actuators on channels, direct reads of the hub's own
    records, commands and queries;
  - §2, spokes, channels and places;
  - §5, an input's author and authority;
  - §6, push and pull;
  - §7, output, and *"proactivity needs nothing of its own"*;
  - §10, windows;
  - §11, the end state: every message its own activation, understanding judging the
    relation, merging and taking over as one mechanism.
- **ADR-0295 and ADR-0297,** the stop.
- **ADR-0286,** an episode open while its activation runs.
- **ADR-0276 §4,** the episode window.
- **ADR-0306 and ADR-0321 §4,** acting and approvals.
- **ADR-0332:**
  - one activation at a time within a place;
  - joining by code;
  - the takeover;
  - `/stop`;
  - the numbers.
- **ADR-0341,** a pure read does not commit.
- **ADR-0083 §7,** the hub's housekeeping scheduler, which this leaves alone.

**And one draft:** ADR-0340, reminders, which §11 rewrites.

---

# A. Operations between activations

## 1. A place is what caused an activation, and nothing more

An activation's **place** is where its input came from. It ties the activation to nothing
else:

- **Context** comes from the windows, recall and stories. Where an activation needs another
  place's recent messages, it pulls them, a pull ADR-0292 §6 already lists (*"earlier
  messages in a conversation"*).
- **Speaking** is an act like any other call (decision C, *Depends on*), so an activation
  may speak into any place it is allowed to.
- **"Working…" and a stop control** are features a kind may declare for its places, not
  part of the general model (§3).
- **Admission, waiting and the reply a conversation expects** stay the rules of the
  causing place's kind (§5).

An earlier draft gave each activation a **home place** for its window, its "working…" and
its stop. The owner dropped it: a place is only what causes the activation.

## 2. The operations

| Operation | What it is |
| --- | --- |
| **Spawn** | An activation sets up another, to start now, later or after other tasks end, as a write into the Task Scheduler (§7) |
| **Stop** | ADR-0295's stop, unchanged: nothing new starts, what is in flight finishes and is recorded, nothing new is written, and nothing is abandoned or undone |
| **Share** | An activation sees what others are doing, and can fetch what they found (§4) |
| **Merge** | A share and a stop as one step: the newest activation takes in an older one's input and findings, and the older is stopped (§5) |

**Start is not an operation.** An input arriving begins an activation the same way every
time, whether it is a message, an email or a scheduled task coming due.

**After an activation has acted, nothing merges into it.** What comes next is a new
activation that reads the records. That is how a correction after a reply works today, and
it stays so.

**The first act is the line** for every rule here. It is ADR-0332 §3's *committed*: acting
has committed to a call that is not a pure read, or to a message.

## 3. Stop

**One operation, with ADR-0295's guarantees.** It names exactly one activation. There are
three ways to reach it:

1. **A command from outside,** through the Task Manager (§10). The hub chat's stop control
   and the line's `/stop` are shortcuts that send it for the activation their place shows.
   Both already call one engine operation, `AssistantEngine.stop_activation`.
2. **A merge.** The older activation is stopped (§5, ADR-0295 §5).
3. **Words, across places.** "Never mind the booking," said on Telegram after the web
   activation has acted:
   - understanding names the running activation the input **cancels**, a closed field
     beside `continues`;
   - a rule stops it;
   - the reply says what had finished.

   "Go on" afterwards takes it back, because a stop abandons no goal (ADR-0295 §4:1). This
   is the item ADR-0332 §9 left to #2515.

**Whether a place shows running work and offers a stop is its kind's declaration:**
- the hub chat: "working…" and the stop button;
- the line: typing and `/stop`;
- the Task Scheduler: nothing, until the Task Manager's view opens.

A conversation shows and stops the activations it caused. A spawned activation speaking
into that conversation was caused by the Task Scheduler, so it is stopped in words or
through the Task Manager.

## 4. Share

**No supervisor.** An earlier draft had rules that pushed findings between activations
(same story, same person, lineage). The walk replaced them with something simpler, built
mostly from what exists:

**1. The in-progress section of the episode window, refreshed every round.**
- **What it holds:** beside the episode window, a short entry for every activation now
  running. The wiki's Episode window page already directs this (owner, 2026-10-05), and
  ADR-0332 §4 builds it for the person's other places.
- **Who sees it:** understanding, as now, and **planning, read fresh at every round.** Today
  planning's episode window skips open episodes (`planning.py`, `_Request._episodes`).
- **What each entry shows, in version 1:**
  - a label (`P1`);
  - what caused it: the hub chat, Telegram or the Task Scheduler;
  - what it took in, in brief, through the episode window's projection, so outside input
    never appears raw;
  - whether it has acted.
- **What this solves:** a running activation learns of a newer one at its next round. "My
  budget's $400 now," said on Telegram, reaches the running flight search before its next
  round, and the search adapts. Every activation sees the others, so it works in both
  directions.
- **Where it sits in planning's document:** after the parts cached across rounds (#3084),
  so a section that changes every round doesn't break the cache.

**2. Pull tools, for anything more.** Planning calls:
- **the findings of one running activation:** "what has the flight search found?";
- **the list of what is running and scheduled:** "what are you doing right now?"

Both are pure reads of the hub's own records (ADR-0341). Both read activations' **open
episodes** (ADR-0286), which are written as each stage ends. One read function serves the
summary, the pulls and recall's rendering of episodes:

- **Only finished work is visible:** a round in progress or a draft never is.
- **A peer is shown only its own work,** never what it read from others, so nothing echoes
  back and no reads chain.
- **By kind of entry,** a pull shows:
  - what the activation is doing;
  - the call outcomes that carried information, with their digests;
  - the acts it has done.

  It never shows recall results, links, failed calls, drafts or approvals.

**What sharing never does:** authorize. A shared item carries no authority, approvals are
never shown, and an approval is used only by its yes's activation (ADR-0321 §4:1).

## 5. Merge

**The newest decides, and the newest absorbs.** The owner: *"the newest activation has the
most up-to-date information, and therefore it should be the choice of the newest
activation."*

1. **Every input starts its own activation,** after the place's short wait (ADR-0332 §5).
2. **The newest's understanding sees the older ones** in the in-progress section, and,
   within one conversation, the earlier messages in its place window.
3. **It may name the older activations its input continues.** The meaning is narrowed from
   ADR-0332 §4:4's *"completes, corrects or adds to"* to **"corrects, completes, cancels or
   changes the same work."**
4. **A rule absorbs them, in one step with no await between.** Each named activation must
   be:
   - older;
   - not yet acted;
   - not stopped;
   - of the same author, authority and origin.

   Each is stopped, and **its input and its finished findings** move to the newest. A
   lookup in the hub's own records is not acting, so an older activation may have done real
   work, and a merge keeps it.
5. **A named activation already absorbed by another is followed forward** to whoever
   absorbed it.
6. **One activation holds at most a limited number of inputs,** in place of ADR-0332 §6's
   `join_limit`.

**One direction, so no cycles.** Only the newer absorbs the older. "Joining" and
"takeover" stop being two mechanisms. Within a conversation, the earlier messages are in
the newest's place window in full, so its first reading already covers them.

**When merging is wrong.** A separate task on the same matter stays separate, for example
"what's the weather there?" while a hotel search runs. Kept separate:
- the weather comes back first;
- each runs in its own mode;
- a failure stays contained;
- each reply lands where it was asked.

The two can still see each other in the in-progress section.

**Replies out of order.** Replies arrive in the order the work finishes. A say-call takes an
optional *in reply to* a place-window label. Each kind's actuator delivers it:
- the line: a native reply;
- the hub chat: a "replying to…" display;
- a kind without replies: a fixed prefix written by code.

It is attached by rule whenever the message answered is no longer the latest in its
conversation. That is decision C's.

**The conversation kind's rule** replaces ADR-0332 §2:3–§2:4's one activation at a time:
- **While nothing running in the conversation has acted,** every message starts its own
  activation, and the newest decides.
- **Once something running in it has acted,** new messages wait. They are never refused,
  keep their authority (ADR-0292 §5:7), and are taken in when it ends, so the next one sees
  the finished result in the records. Running beside work that has acted would mean acting
  on a half-finished picture, such as rebooking while the first booking is still in flight.

Across places there is no wait. A newer related activation sees "has acted," and can stop
the older or follow after it. A true race between two acts on one thing is the lock and
recheck's (#2586).

---

# B. The Task Scheduler and the Task Manager

## 6. The Task Scheduler

The **Task Scheduler** is a built-in channel with one place, the schedule. It is a hosted
medium in ADR-0292 §1's sense: something the hub runs that is not the assistant. The
assistant reaches it only through its sensor and its actuator, and it is fully private for
now: no person's device attaches to it.

| Part | What it does |
| --- | --- |
| **Its contents** | Only **scheduled tasks**: activations waiting to be started, each with its outcome once it has run. What is running now is live state, never stored there (ADR-0292 §11:7). |
| **Its actuator** | Writes a scheduled task: the spawn. It also changes and cancels them. |
| **Its sensor** | **Pushes** a task that comes due, which starts an activation. **Answers pulls** about what is scheduled. |
| **Its kind's declarations** | Its activations run **side by side**. It takes no message from people, shows no running work, and expects no reply. |

**Names.** The owner chose Task Scheduler and Task Manager over the agenda and the
activation scheduler. Two conventions keep them clear:
- an item is a **scheduled task**, meaning a scheduled activation, and Python's kind is
  always an *asyncio task*;
- the name is always **Task Scheduler** in full, because "the scheduler" stays the hub's
  housekeeping loop (ADR-0083 §7), which is unchanged.

## 7. Spawning

**A spawn is a call:** planning calls it, authorizing checks it, and acting writes the task
through the Task Scheduler's actuator. **Every spawn goes through the Task Scheduler,
"now" included.** A task due at once wakes the sensor straight away. Going through it
means:
- a spawn survives a restart;
- there is one path for now and later;
- new input still reaches the controller only through a sensor;
- the Task Manager sees everything.

**What a scheduled task holds:**

| Part | What it is |
| --- | --- |
| **For whom** | The person of the activation that spawned it (ADR-0338 §2:2) |
| **Author** | Whoever set it: the person ("remind me…") or the assistant (its own follow-ups and next steps), written when it was set |
| **Authority** | None. It informs and authorizes nothing, as ADR-0292 §5:6 already says of reminders, here widened to every scheduled task. No approval carries over (ADR-0321 §4:1). |
| **When** | Now; an instant; a rule ("every weekday at 8"); or **after these tasks end**. A condition ("when I get home") waits for watches (#2585). |
| **Where it may speak** | One place stated by the creator, or none. There is no default. With none, it may work, write records and spawn, but never speak. If the place is gone when the task comes due, the task is cancelled. |
| **What it carries** | The creator's instruction, kept short: the reminder's text, or the step to do |
| **Its pointers** | Its **parent**, the activation that spawned it, whose episode it may read. A gather step also points to **the tasks it waits for**. These replace "lineage" as a sharing rule: they are reads of finished episodes, not sharing. |
| **Where it was set** | The place the spawning activation came from, as data |
| **Its marks** | Its setter's outside-content mark (ADR-0340 §2:6) |
| **Its state and outcome** | Pending, pushed (naming its activation), and then how it ended |

**What spawning is for.** It is the rarer case. Most activations just work: they call
tools, speak wherever they need to and end. A spawn covers:
- **continuing** work too long for one activation;
- **breaking down** work into independent pieces;
- **isolating** work in a separate context;
- **reminders and schedules;**
- **the assistant's own follow-ups:** a retry, a check back, a nudge.

These vary on two axes only: **when** (now, later, after other tasks, or on a condition)
and **where** (the place it may speak in, or none). "Background task" is dropped as a
concept, because an activation spawning its own next step covers it.

## 8. How a scheduled task starts, and restarts

**The sensor:**
- sleeps until the earliest task is due;
- wakes early whenever a task is written;
- never sleeps longer than a set recheck interval;
- compares wall-clock instants, not elapsed sleep;
- pushes everything due at or before now;
- marks each task *pushed*, naming the activation it started.

All of this is ADR-0340 §6, carried over.

**Due together, started separately.** Two tasks due at 8:00 start two activations. Whether
they become one is merge's job (§5): two unrelated reminders give two messages, and a
reminder set twice by mistake merges.

**After a restart,** each pushed task is settled from its activation's records, as ADR-0340
§6–§7 does:
- its main act finished: done;
- its outcome is unknown: tried once more, marked "in case my last message didn't reach
  you";
- nothing happened: run again;
- **it had already spawned its next step: never run again,** so a chain cannot fork.

**Missed while the hub was down:** each is said once, marked late. A recurring task never
bursts its missed occurrences (ADR-0340 §8).

## 9. Changing, cancelling and stopping scheduled work

**Finding the task.** A message a scheduled task's activation wrote is labelled in the
conversation's place window with the task that caused it ("from scheduled task `T2`").
- **"Snooze 10 minutes,"** right after a reminder, is one call in one round: change `T2`.
- **Anything else,** such as "cancel the bins one" or "stop the apartment search," is a pull
  on the Task Scheduler, then the change.
- **Where the words could mean two tasks,** it asks.

**Stopping a chain:** stop the running step first, then cancel what it spawned. Once a
stop lands, the stopped activation can't write anything new, so nothing slips through.

**Pausing** is stopping the running step and moving its next task's time.

**Limits:**
- a cap on a chain's length, counted through the parent pointers;
- a cap on pending tasks;
- the spend ceiling, as always.

## 10. The Task Manager

The **Task Manager** is the one way in from outside for managing activations. In ADR-0292
§1's terms it is a surface of **commands and queries**, which the assistant does not
perceive, not a spoke on a channel:

- **Queries:**
  - what is running, live from the controller;
  - what is scheduled, from the Task Scheduler;
  - what ran lately.
- **Commands:**
  - stop a running activation;
  - cancel or change a scheduled task;
  - later, add one by hand.

**Conversations offer shortcuts into it.** The stop button and `/stop` send its stop.

**Inside, the same operations.** A merge's stop, "never mind" across places and planning's
pull tools all use these same operations.

**Its full view opens later.** For now its operations exist, because the shortcuts and the
pull tools need them. A screen listing everything (running, with how long; scheduled;
done) comes later. Shown to people, it would be called **Tasks**.

## 11. Reminders are scheduled tasks

A reminder is a scheduled task whose "when" is a time. **ADR-0340 keeps:**
- local times and zones (§5): recurring tasks follow the current zone, and a one-off is a
  fixed instant read back when set;
- recurrence (§9);
- the late rule (§8);
- the second try (§7);
- the read-back when set, now naming where it will speak;
- set, change, cancel and done as plain words ("done", "snooze", "I already took it");
- deleting a conversation cancels the tasks set to speak there.

**ADR-0340 drops:**
- the clock as a channel of its own, replaced by the Task Scheduler;
- a reminder counting as its conversation's own activation and waiting for it (§3:4);
- the say-only limit (§3:7): the ordinary authority rules apply;
- the special report kind (§10): a chain's last step says what it found;
- grouping at the sensor (§6:4): merge decides.

ADR-0340's **question 2 dissolves.** It asked whether a reminder set in the hub chat should
go to Telegram automatically. Now the creator states where a scheduled task may speak, and
the read-back says so: "I'll remind you on Telegram at 8."

---

## Situations

| Situation | What happens |
| --- | --- |
| Three quick messages in one chat, before any reply | The newest absorbs the older two: one reply |
| "Actually Sunday," a second after "book Saturday," before it acts | The newest absorbs: Saturday is never booked |
| "Actually Sunday" after it booked Saturday | It waits for that activation to end, sees the booking, and changes it as a new request |
| "Actually Sunday" on Telegram, before the web booking acts | Takeover across places: one Sunday booking, and the reply comes on Telegram |
| "Never mind the booking" on Telegram, after the web one acted | Understanding names what it cancels; a rule stops it; the reply says what finished |
| "Also, what's the weather there?" while a hotel search runs | Separate activations: the weather answers first, replying to its own message |
| "My budget's $400 now" while a flight search runs | The search sees it in the in-progress section at its next round and adapts |
| "What's the cheapest so far?" from another device | Planning pulls the search's findings and answers |
| "What are you doing right now?" | Planning pulls the list of what is running and scheduled |
| "Remind me at 8 to call Mom about it" | A scheduled task speaking here at 8. Its activation reads its parent's episode for what "it" was. |
| Two unrelated reminders due at 8:00 | Two activations, two messages |
| A reminder set twice by mistake | They merge: one message |
| A reminder fires while you're typing to Telegram | Separate, because their authority differs. Both happen. |
| "Snooze 10 minutes" right after a reminder | The window shows which task wrote it: one change |
| "Keep looking for apartments this week" | The activation spawns its next step for tomorrow, and each step spawns the next until done or capped |
| "Compare these three apartments" | Three checks spawned now, plus a gather step timed after all three end |
| "Stop the apartment search" | Stop the running step, then cancel the pending one |
| The hub restarts mid-step | The step is settled from its records, and never re-run once it has spawned its next |
| The hub was down at 8 | The reminder is said once, marked late |
| Two newer activations name the same older one at once | The first absorbs it; the second follows forward and absorbs the first, if it hasn't acted |

## Considered and not adopted

| Idea | Why not |
| --- | --- |
| **Fork,** a running copy | It doubles the model calls, and the copy could act twice. Kept from acting, a copy is just a share. |
| **Split** into equal parts | A person answers a two-part message once and hands off the long part, which is a spawn |
| **Suspend and resume** | It doesn't survive a restart. Ending and being continued does the same job. |
| **"Kill"** | Too abrupt for ADR-0295's graceful stop, and "stop" already names the mechanism |
| **A home place** | A place is only what caused an activation (§1) |
| **A supervisor with share rules** (same story, same person, lineage) | The in-progress section refreshed every round, plus pulls, does the same job with less, and the automatic flow carries no findings |
| **Joining by code, plus a separate takeover** | One rule, the newest absorbs, covers both |
| **The newest able to push itself into the older** | It gains nothing, and the older's findings move with a merge anyway |
| **Grouping due tasks at the sensor** | Merge decides, so there's no special rule |
| **"Background task"** | Spawning one's own next step covers it |
| **One activation at a time per conversation** | It's needed only after something has acted (§5) |

## What it would change

| Part | Amends |
| --- | --- |
| **A place ties nothing; speaking anywhere** | ADR-0306's limit of messages to the input's place. This belongs to decision C, with B's narrow interim below. |
| **Stop by words across places** | ADR-0332 §4:8, where nothing is stopped once the older has committed; ADR-0295 §1:1, §1:4 and §1:5, for this route alone |
| **Running work shown where the kind declares** | ADR-0292 §11:7 |
| **The in-progress section for planning, every round** | Planning's document (ADR-0307); ADR-0332 §4:1–§4:3, which drops "other places" and adds spawned activations |
| **The newest absorbs** | ADR-0332 §3, joining by code, which is replaced; §4:4, where `continues` is narrowed and gains `cancels`; §4:6, where the merge carries findings; §6:5, where the join limit becomes a held-inputs limit |
| **The conversation waits only after acting** | ADR-0332 §2:3–§2:4; ADR-0292 §11:5; and the controller walk's answer 1 on #3257, which chose one activation at a time within a place and is reversed by the owner here |
| **The Task Scheduler** | ADR-0340's clock channel and its records, which it replaces |
| **No authority on any scheduled task** | ADR-0292 §5:6, widened from reminders to every scheduled task |

**B's interim, before decision C lands.** An activation the Task Scheduler starts speaks
only into the place its task states. That narrow widening of ADR-0306 lets B ship before
speaking becomes a say-call everywhere.

## Depends on, and beside

- **Decision C, calls onto channels** (its own track). It covers:
  - every channel the same shape, with at least one place;
  - a call is a pull, an act, or a direct read or write of the hub's own records;
  - **speaking as a say-call** with *in reply to*;
  - a conversation's expected reply as its kind's declared requirement;
  - planning says what, and each kind's actuator decides how.

  It supersedes ADR-0170's "a reply is not a tool" (#2593).
- **Modes** (quick, normal, deliberate, "just blurt"), next on this front. A pending
  "answer the next one quickly" is likely an entry the next activation reads at admission.

## What it leaves open

- **The gaps for the outside-content, privacy and audience work.** These are noted, not
  closed:
  - marks must travel on every read of a peer's episode, through the one read function;
  - shares and merges stay within one person until the household design;
  - every read is fresh each round, so a forget or deletion is honored (cf. #3319);
  - the audience where a message lands (#2590).
- **Which places a creator may name for a scheduled task,** and spawning for other people.
- **Opening the Task Manager's view to people,** and adding tasks by hand.
- **Spawns on a condition** (#2585), and what an event's activation may spawn.
- **What a taken-over place hears** about where the matter went (#2588).
- **The lock and recheck** for two acts on one thing (#2586).
- **Batching** unrelated messages into one, if two messages ever feel chatty.
- **The numbers** (#2589):
  - the held-inputs limit;
  - the chain and pending caps;
  - the in-progress section's size;
  - the sensor's recheck interval.

## How it converts

Two ADRs: **A** (§§1–5) and **B** (§§6–11). B depends on A's merge rule for tasks that come
due together. ADR-0340 is then rewritten on top of B. The numbers come from the
coordinator at conversion.
