# 218. A conversation is observed once it goes quiet, a max-age backstop bounds the wait, and the job ships armed

- Status: Proposed
- Date: 2026-08-29
- **Partially supersedes**
  [ADR-0083](0083-the-hub-is-a-resident-process.md) — §7's job-table row for
  observation, in its **Default** and **Calls** cells and in nothing else of §7.
  §7's fourth bullet is **not** superseded: its sentence is conditional on the
  cursor's absence and stays true as written. Named in §11(a).
- **Partially supersedes**
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) — §8's **third**
  reason, and nothing else of §8 or of ADR-0077. Reasons 1, 2 and 4 stand whole,
  and the no-per-turn-trigger sentence is kept rather than narrowed. Named in
  §11(b).
- **Partially supersedes**
  [ADR-0120](0120-a-measure-is-a-rate-over-the-trace-stream-read-offline-while-the-hub-is-stopped.md)
  — §3's second normative clause, in the single scope of the **machine** seam
  set's membership, which gains one member. The user set, the direct set, the
  unclassified rule and every measure below are untouched. Named in §11(c).
- **This ADR uses ADR-0212 and does not amend it.** Every pass this decision
  schedules is ADR-0212's pass, performed against a conversation the run
  **names** — which is §3's own optional-id branch — so §3's "given none" default,
  §4's tail start, §5's advance and §8's three operations all bind unchanged.
  §11(d) applies ADR-0082 §1's test to each and records nothing.
- **Contract surface, without a Protocol.** This ADR adds two `Settings` fields
  and changes the default of a third (§7). It touches no Protocol in
  `core/protocols.py`, no type or member in `core/types.py`, no member of the
  promoted engine surface and no wire operation, so golden rule 5's "Protocol
  change" is not triggered and no triad is owed; `PROTOCOL_VERSION` does not move
  (§6). It is contract surface all the same, on ADR-0083's own header precedent —
  "the corpus's own line is the triple ADR-0054's header draws, 'no Protocol in
  `core/protocols.py`, no `core` type, and **no `Settings` field**'" — so it is
  `Proposed`, alone in its PR, carries **both** review lenses (ADR-0015 §1), and
  merges ahead of anything implementing against it (ADR-0015 §5).
- **No implementation lands with it.** No `src/`, no `tests/`. §10 states what the
  implementing lane owes.

## Context

### Where this comes from

The owner's direction of 2026-08-28, recorded as **#1737**, is *cursor first, then
observe-on-quiet*: two ADRs in that order. **ADR-0212 is the first and is
ratified** — a per-conversation watermark on the conversation index, a candidate
order, a per-pass bound, and three new `ConversationStore` operations. This is the
second, and ADR-0212 §9 names it by the same words the issue does:

> **The trigger, and the cadence.** #1737's ADR B — observe-on-quiet with the
> interval as a backstop — and it is the next lane, not this one. This ADR flips no
> default: `observation_interval` stays `None` and ADR-0083 §7's table still ships
> the job disabled. […] the condition that fires it is the trigger ADR ratifying.

The gap #1737 opens with is a fact about the deployed hub rather than a
hypothetical: `ASSISTANT_OBSERVATION_INTERVAL` is unset, so a fact the user tells
the assistant in chat is captured as an episode (ADR-0074 §3) and becomes a belief
only when `assistant observe` is run **by hand**. The issue's title states the
outcome it wants — "chat facts become beliefs without a hand-run `observe`" — and
that outcome is not reached by the cursor alone. The cursor made an armed timer
*safe*; nothing has yet made one *armed*.

### What ADR-0212 bought, and what it deliberately left

ADR-0212 answers "what has already been looked at". Three of its clauses are what
this decision is built on, and each is quoted where it is used below: candidacy and
the candidate order (§3), the per-pass bound and the one-conversation-per-pass rule
(§3), and the advance (§5). Two of its statements are the reason a trigger is now
decidable at all:

- **A tick with nothing unobserved costs no model call.** §3: "Given none and no
  candidate, the pass reads no turns, calls no model, and reports nothing
  observed." That removes the whole of `core/config.py`'s stated reason for the
  disabled default — "Enabling it on a timer before the cursor exists (ADR-0083
  §13) buys repeated cost and no new coverage."
- **A pass strictly advances.** §5: "**the watermark never stands still across a
  pass over a non-empty page**, and a conversation with turns above its watermark
  cannot be re-read indefinitely." That is what makes a *run* — more than one pass
  — terminate, which is what §3 leaves to this ADR: "How many passes one scheduled
  run performs is not decided here — ADR-0111 §4's run clause governs it and the
  trigger ADR arms it (§9)."

What ADR-0212 does **not** answer is when to look. Its selection rule is total: it
orders every candidate and takes the first. Run on a timer with no further
condition, that reads a conversation the user is in the middle of, one page at a
time, on whatever tick happens to fall between two turns — which is the thing
#1737's item 1 is written to avoid ("a fact and its correction two turns later
arrive together").

### The condition ADR-0214 was, and why it matters here

Until 2026-08-29 an observation that agreed with something the user had asserted
was ruled `ASK_USER` — the system parking a question back at the user about a fact
the user had already told it. **ADR-0214** rules that population `REINFORCE`
instead: "An observation that agrees with a user assertion corroborates it, and is
never asked about." Under a hand-run observer that was a cost the user paid at a
moment they chose. Under an armed one it would be an unattended job manufacturing
user-facing questions on a timer, which is the shape nobody would arm twice.
ADR-0214 is therefore a **precondition of this decision**, discharged before it
rather than by it, and it is cited here as such and not re-decided.

### What ADR-0083 and ADR-0111 already decide, and is not re-decided here

**ADR-0083 §7** owns the loop: one table of jobs, "each with a name, an interval
and a next-due instant", run "**one at a time**", with "A job's next run […]
scheduled from its *completion*, not from its start." It already carries the
observation row, shipped disabled, and it already states the duration discipline
every interval follows — "a `timedelta` refused at load time unless it is finite
and strictly positive", with "**'Disabled' is `None`, never `0`**". **ADR-0083 §8**
owns where a job lives: "Every scheduler job is a public `Engine` call", the
scheduler "holds an `Engine` and nothing else", and "The `Engine` therefore grows a
maintenance surface […] That is new *concrete* surface on a class in
`orchestration`, not `core` contract surface".

**ADR-0111** owns what one run may spend. §4: "A chunked job's single run commits
chunks until either its work is exhausted or its run budget is spent, then
returns. The budget is checked only at a chunk boundary, so no chunk is abandoned
part-way and a run may overrun its budget by at most the duration of one chunk."
§5: "When a chunk cannot be recorded as done, the run stops immediately, leaves the
cursor at the last chunk that was recorded, and returns without processing any
later chunk." §6: "A run that halts or raises is retried at its next due instant
under ADR-0083 §7's fixed delay after completion. No job varies its interval in
response to failure, and no failure count is durable." All three bind this job and
none is re-decided; §3 and §9 below say how each reaches it.

### The two instants the index carries, and why the difference decides §1

`Conversation` carries both, and its docstring separates them:

> **`last_active_at` and `last_turn_at` are two different facts** (§2). Activity is
> "someone was here": set at creation and refreshed whenever a turn *begins*, so it
> is always present and is the key every listing and the retention reclaim read.
> `last_turn_at` is "a turn was **recorded**", set by the append that writes a turn
> into the index and unset until one lands.

`ConversationStore.mark_active` "Sets `last_active_at` from the store's clock",
where `ConversationTurn.occurred_at` is the caller's — "When the exchange this turn
records happened". And ADR-0212 §3 ordered its candidates on the first of the two,
ascending. Which instant "quiet" is measured on is therefore not a detail: it
decides whether the quiet candidates are a prefix of the order the corpus already
ratified, or an arbitrary subset of it. §1 takes that up.

### Today's job row, in the code

`service/scheduler.py`'s `jobs_for` builds the table ADR-0083 §7 names, and the
observation row is `("observation", settings.observation_interval, engine.observe)`
— dropped from the table entirely while the interval is `None`, since `jobs_for`
filters on exactly that. `core/config.py`'s `observation_interval` defaults to
`None` and describes itself as running "the most recently active conversation",
which ADR-0212 §3 has already replaced. Nothing else in the tree is waiting on this
decision: the three store operations ADR-0212 §8 names are the implementing lane's
to add, and the trigger is what tells that lane what to call them for.

## Decision

### 1. Quiet is measured on `last_active_at`, and the quiet candidates are a prefix of ADR-0212 §3's order

> **Normative.** A candidate conversation, in ADR-0212 §3's sense, is **quiet**
> when the run's clock instant minus that conversation's `last_active_at` is at
> least `observation_quiet_window` (§7). Quietness is a property of the
> conversation and is measured on `last_active_at` alone — not on `last_turn_at`,
> not on `started_at`, and not on any turn's `occurred_at`.

**Why the activity instant and not the last recorded turn.** `last_active_at` is
"refreshed whenever a turn *begins*"; `last_turn_at` is set "by the append that
writes a turn into the index". Between those two moments the user is mid-exchange
— the model is answering, or a step is parked — and that is precisely the state a
quiet window exists to stay out of. Measuring on `last_turn_at` would call a
conversation quiet while its next turn is in flight, and the pass would then read a
page ending one turn short of the exchange it belongs to, which is #1737 item 1's
own failure ("Reads the whole exchange at once rather than a fragment
mid-conversation") reached through the field that looks like it means the same
thing. `last_active_at` is also always present, while `last_turn_at` is "unset
until one lands", so the rule needs no reading for an absent value.

**And the decisive property is structural: quiet candidates are a prefix.**
ADR-0212 §3 orders candidates by "`last_active_at` **ascending**, ties broken by
`id` ascending", and quietness as defined above is *monotone decreasing* in that
key: if a candidate is quiet, every candidate before it in the order is quiet too.
So **the head of the listing is quiet exactly when any candidate is quiet**, and
the quiet arm of §2's due test needs no scan at all — it reads one row. That is
what keeps this trigger from re-ordering, re-sorting or re-paging a listing ADR-0212
§3 states "no consumer re-sorts". A quiet test on `last_turn_at` would have no such
relation to the order, and every quiet arm would then be a scan whose cost grew
with the listing.

**A non-monotonic clock costs the prefix property and nothing else.**
`Conversation` records that "`started_at`, `last_active_at` and `last_turn_at` all
come from an injected clock, which this project never promises is monotonic". Under
a stepped clock the listing may be ordered on values that do not reflect real
activity order, so the prefix property degrades to "the head is *usually* quiet
first". The due test itself does not degrade: it is evaluated per candidate against
that candidate's own instant, so a mis-ordered listing costs at most a scan past a
non-quiet head, which §2's rule already performs. This is the same limit ADR-0212
§3 named for its own order ("The bound is a property of the clock, and this ADR does
not promise more than the clock gives it") and it is inherited rather than
re-argued.

### 2. The backstop is the age of the material, and due is quiet **or** backstopped

> **Normative.** A candidate's **unobserved span** begins at the `occurred_at` of
> the single turn returned by `ConversationStore.turns_after` for that
> conversation with `after_ordinal` set to its `observed_through` and `limit` 1 —
> the lowest turn above its watermark, or its first turn where no watermark is
> recorded.

> **Normative.** A candidate is **backstopped** when the run's clock instant minus
> the start of its unobserved span is at least `observation_max_unobserved_age`
> (§7).

> **Normative.** A candidate is **due** when it is quiet **or** backstopped. A
> scheduled pass is performed only against a due candidate, and a run that finds
> no due candidate reads no turns, calls no model and writes nothing.

> **Normative.** The backstop is evaluated by walking the candidate listing in
> ADR-0212 §3's order and taking the **first** candidate that is due. The listing
> is not re-sorted, and a run never selects a later due candidate over an earlier
> one on the ground that its span is older.

**The interval cannot play this role, and that is the substantive answer to
#1737's item 2.** The issue leaves open whether "the existing interval setting can
play this role, or a second duration". It cannot, and the reason is that the two
figures bound different things. `observation_interval` is ADR-0083 §7's fixed delay
after completion — *how often the question is asked*. A backstop is a bound on *how
old unobserved material may get* — a property of the material, not of the loop.
A conversation in continuous use answers "not quiet" at every tick however
frequent, so no value of the interval reaches it; shortening the interval only asks
the same question more often and gets the same answer. Two figures, two fields.

**What the backstop actually closes.** ADR-0077 §8 names two accepted gaps, of
which the first is "a conversation the user never observes". ADR-0212 §3 closed that
one for the *idle* case by making every candidate reachable in the order. The quiet
trigger reopens a narrower version of it — a conversation that never goes quiet is
never due — and the backstop is what closes that. Without it, a single long working
session accumulates unobserved turns until it ends, and its earliest turns can reach
`episode_retention`'s horizon (30 days by default) and expire undistilled while the
conversation is still live. The backstop bounds that wait at one figure an operator
can read.

**Why the span's start and not the conversation's last activity.** The question the
backstop asks is "has material been waiting too long", and the material is the turns
above the watermark. Measuring on `last_active_at` would make an actively-used
conversation permanently *not* backstopped, which is the case the backstop exists
for. Measuring on the *newest* unobserved turn would do the same thing one turn
later. The oldest is the only one of the three that ages.

**One divergence between the due test and the pass is deliberate, and it is named
rather than left to be found.** For a conversation with **no** watermark the clause
above reads its *first* turn, while ADR-0212 §4 rules that the pass which follows
reads "that conversation's most recent `observation_batch_size` turns" and "does not
read forward from the conversation's first turn". Those are answers to two different
questions — how long has unobserved material been waiting, and where does a first
pass begin — and §4 has already priced the prefix its answer passes over ("A tail
start passes over **every** turn below the window it reads"). Making the due test
read the tail window instead would cost a `observation_batch_size`-wide read per
probed candidate to reach a figure that changes no pass's behaviour. It is not
bought.

**`occurred_at` is the caller's instant, and using it here is not ADR-0111 §2's
excluded shape.** §2 excludes a wall-clock instant as a **cursor** — "a row written
with an earlier instant after the cursor passed […] sits permanently behind the
position and is never reached". Nothing here is a position: the walk's position is
ADR-0212's ordinal watermark and this instant decides only *whether to walk now*. A
skewed `occurred_at` therefore costs timing and never coverage — too old fires the
backstop early, which merely observes sooner; too new delays it, and the quiet arm
still reaches the conversation the moment it stops receiving turns. This is
ADR-0093 §5's posture, where a read is bounded "by the clock, its configuration and
the source's own content", applied to a trigger rather than to a read.

**What a run pays for the scan, stated as a bound.** Testing quietness costs
nothing beyond the listing, which one call already returns. Testing the backstop
costs one `turns_after` call with `limit` 1 per candidate examined, and a pass
examines at most one listing — `conversations_with_unobserved_turns` "bounded by
default at **50**" (ADR-0212 §8). So a pass performs at most 50 single-row index
reads before it selects, no model call among them, and in the ordinary case it
performs **zero**: §1's prefix property makes a quiet head the common answer, and a
quiet head is due without any probe. The probes are paid only on a tick where
nothing is quiet, which is exactly the state the backstop exists to resolve.

**A deployment may set the backstop below the quiet window, and that is coherent
rather than refused.** The two fields are independent durations and no cross-field
validation is added: with a max age at or below the quiet window every candidate is
backstopped before it is quiet, and the job degrades to a pure age trigger that
reads mid-conversation pages. That is a policy an operator can state and this ADR
does not need to forbid; refusing it at load would refuse a well-defined
configuration to protect a default nobody is obliged to keep. What is *not*
coherent is a backstop above `episode_retention`, since the material can then
expire before the backstop fires — named in the Consequences, not refused, because
`episode_retention` is nullable ("keep forever") and a cross-field rule over a
nullable horizon has a branch that means nothing.

### 3. The run: one new `Engine` operation, passes over conversations it names, bounded by the run budget

> **Normative.** The scheduled trigger is a **new operation on `Engine`**,
> `observe_due`, taking no argument. It is concrete surface on a class in
> `orchestration` in ADR-0083 §8's sense — "The `Engine` therefore grows a
> maintenance surface" — and it is **not** added to the `AssistantEngine` Protocol
> in `core/protocols.py`, **not** exposed as a wire operation, and **not** a
> reason to move `PROTOCOL_VERSION`. `Engine.consolidate` is the precedent in each
> of those respects.

> **Normative.** One run performs zero or more **passes**. Before each pass it
> reads the candidate listing afresh, applies §2's due test in ADR-0212 §3's
> order, and — where a due candidate exists — performs exactly one ADR-0212 pass
> **naming that conversation's id**. It returns when no candidate is due or when
> `scheduler_run_budget` is spent.

> **Normative.** The run budget is checked **only at a pass boundary**, so a run
> overruns it by at most one pass. That is ADR-0111 §4's clause applied with the
> pass as the chunk, which is what ADR-0212 §3 already calls it.

> **Normative.** The listing one pass considers is a single call to
> `ConversationStore.conversations_with_unobserved_turns` at the bound ADR-0212 §8
> gives it. A run performs no offset, no continuation and no widened listing, and
> a candidate beyond that bound is reached on a later pass or a later run and
> never by paging.

> **Normative.** Every pass a run performs happens inside the **run's own**
> `Engine._tracked` scope. A pass is never a nested call to `Engine.observe`, so
> every trace a run emits carries the run's correlation and attributes to the
> run's seam (§6).

> **Normative.** `scheduler_chunk_size` does not reach this job. ADR-0212 §3 rules
> that already — "an implementation that hands it to `turns_after` or to
> `conversations_with_unobserved_turns` is not implementing this ADR" — and this
> ADR adds the run without adding a second reader of that count: the page is
> bounded by `observation_batch_size`, the run by `scheduler_run_budget`, and
> nothing by the chunk size.

**Why a new operation rather than an argument on `observe`, and the reason is not
taste.** `observe` is a **wire** operation: `wire/client.py` calls it by name with
`conversation_id`, and `AssistantEngine` in `core/protocols.py` declares it. Adding
an argument to it would add an argument to the promoted engine surface, which is
ADR-0124 §9's own trigger for moving `PROTOCOL_VERSION` — a protocol bump bought to
express a cadence. A second reason is stronger still and is §6's: the two callers
write for different *causes*, and ADR-0120 §3 attributes a write by the seam of the
operation that caused it, so one seam serving both would make an armed job's writes
indistinguishable from a user's deliberate ones. A third is the return shape:
`ObservationReport` is "What one observation pass did", carrying one
`conversation_id` and one `route`, and a run performs many passes. `observe_due`
returns the passes it performed, in order; `ObservationReport` gains nothing, which
is what ADR-0212 §9 left standing.

**Why the run *names* the conversation, and what that buys.** ADR-0212 §3's third
clause reads "One pass observes **one** conversation: the conversation named by the
operation's optional id, or — given none — the first candidate in that order." A
scheduled pass takes the first branch: the run does the selecting and hands the pass
an id. So §3 binds this job **unchanged** — no clause of it is narrowed, and its
"given none" default stays exactly what a hand-run `assistant observe` gets. The
alternative — letting the pass select — would have required §3's default to mean one
thing for the CLI and another for the scheduler, which is an amendment bought for
nothing.

**Why more than one pass per run.** ADR-0111 §4's clause is that a chunked run
"commits chunks until either its work is exhausted or its run budget is spent", and
a pass is a chunk. Running exactly one pass per tick would make the drain rate a
function of the interval alone: at ADR-0212 §4's tail start, every conversation that
already exists costs exactly one pass to catch up, so the first armed hub would take
one conversation per tick to reach a steady state it could otherwise reach in a
run or two. Bounding the run by time instead is what ADR-0111 §4 exists for, and it
is the bound an operator can already read off the configuration.

**The run terminates, and the argument is ADR-0212 §5's.** Each pass over a
non-empty page names a position "strictly above the watermark that pass read", and
"the watermark never stands still across a pass over a non-empty page". So each pass
strictly shrinks the unobserved span of the conversation it served, every candidate
holds finitely many turns, and a conversation leaves the candidate set once its
watermark reaches its highest turn. New turns arriving during a run make their
conversation *not quiet*, which removes it from the due set rather than extending
the run. The run budget bounds it in every case, including the pathological one
where turns arrive faster than passes complete.

**One conversation may take the whole run, and that is the ordering working.** A
candidate with many pages of unobserved turns stays at the head of the ascending
order — no new turns, so no new activity instant — and is served pass after pass
until it is exhausted or the budget is spent. ADR-0212 §3 chose that order because
"It serves the material nearest its expiry first", and a run that abandoned a
half-drained conversation to spread its budget would be serving the material
*furthest* from expiry with the same number of model calls. What the next run does
is resume, which is what the watermark is for.

### 4. Where it runs, and the three triggers that stay forbidden

> **Normative.** ADR-0083 §7's observation row calls `observe_due` and is armed by
> `observation_interval`. It is a job on that table like any other: serial, re-armed
> at completion plus its interval, logged with its class on failure, and never able
> to take the process down.

> **Normative.** Nothing else triggers observation. There is **no per-turn
> trigger**, no request-time path that performs a pass, arms a run or advances a
> watermark, and nothing a turn waits on. ADR-0077 §8's sentence is kept whole:
> "It is **not** wired into the turn", and its first reason with it — "**Nothing is
> waiting on it, and a turn is.**"

**The job body stays what ADR-0083 §8 requires.** It is "a public `Engine` call"
holding "an `Engine` and nothing else": the due test, the listing and the passes are
all behind the façade, in `orchestration`, where the stage already holds both
stores. The scheduler learns nothing about watermarks, quiet windows or spans — it
holds a name, an interval and a bound method, which is what `service/scheduler.py`'s
`JobBody` says it holds. ADR-0083 §7's "**No job gets new store surface**" is also
kept: the three operations a run calls are ADR-0212 §8's, ratified before this
decision and not widened by it.

**"No polling" is already spent, and by ADR-0083 rather than by this ADR.** §8's
opening sentence continues "and there is no polling, no background task and no
ambient machinery", which described the state of the system when ADR-0077 was
written and which ADR-0083 §7 changed by putting the job on the table. ADR-0083 §15
classifies that act itself: "Each defers a job *to* this scheduler; this ADR is what
they deferred to. A deferral discharged by the ADR it named is a stacked addition,
not an amendment — the deferring sentence stays true and now has an answer." This
ADR arms the job ADR-0083 added; it does not add a second one, and §11(b) records
what it does and does not change about §8.

### 5. The job ships armed, and "configuration is not consent" is answered rather than inherited

> **Normative.** `observation_interval` ships with a **finite positive default**
> (§7), so a hub that configures nothing observes on a cadence. `None` remains the
> spelling of "off" and remains available to any deployment that wants it, under
> ADR-0083 §7's convention unchanged.

**ADR-0093 §6 forbids inheriting either posture, which is why this section argues
it.** That clause — "A sensor's job may ship enabled once §9's gate is discharged.
The reason observation ships disabled is specific to observation and does not
transfer" — was written so "the next lane reads 'the observation job ships disabled'
as the house posture for scheduled ingestion and ships a switch nobody can safely
flip". The same discipline applied in the other direction forbids reading ADR-0093
§7's "Every sensor ships **disabled by default**" as a house posture for this job.
Four grounds decide it, in the order they bind.

**1. The stated reason for the disabled default is spent, by the decision that was
named to spend it.** ADR-0083 §7's bullet reads: "Enabling it on a timer before the
cursor exists buys repeated cost and no new coverage. The interval exists so that
enabling it is configuration; the default is off until the cursor lands (§13)." The
cursor has landed. `core/config.py` states the same conditional at the field itself.
Both sentences stay literally true — they are about the state *before* the cursor —
and both stop reaching the default the moment ADR-0212 is ratified, which is why §11(a)
records the table cell and not the bullet. ADR-0212 §9 names this ADR's ratification
as "the condition that fires it".

**2. The sequencing gate ADR-0077 §8 set is discharged, and it is checkable.** Its
second reason is a condition, not a preference: "**The roadmap sequences leg 4
against volume** — the `ASK_USER` gap (#423), the contradiction surplus (#313/#314)
and bounded-window retirement (#306) 'land before the observer runs at volume'." All
four issues are closed — #423 on 2026-07-30, #313 on 2026-07-29, #314 on 2026-08-10,
#306 on 2026-07-29. **ADR-0214** then removes the residue those closures did not
reach, by ruling that an observation agreeing with a user assertion corroborates
rather than asking. So the volume this default admits arrives at a gate that has
been discharged rather than at one still standing, and reason 2 needs no record: a
reader holding only ADR-0077 checks the four issues and reaches the same answer.

**3. No new recipient sees anything, and that is ADR-0004 §2's property rather than
a reassurance.** ADR-0077 §3 makes the observer's route default to the
conversational one — "Unset — the default — means the observer reads through the
route the operator has *already* configured for conversation" — and argues the
default on exactly this ground: "ADR-0004 §2's property, as amended, is that user
data reaches only providers the user explicitly configured, and a default that names
no new provider cannot breach it." Arming the job names no provider either. The
material is the user's own turns with this assistant, captured by ADR-0074 §3 into
this deployment's own store, and already sent to that same configured route on the
turn that produced them. This is the whole distance between this job and ADR-0093
§7's calendar, where the default would decide a **grant** over a file the assistant
does not own — "a fresh install that read a calendar unasked would be making the
grant decision by omission, which is the one way it must not be made". There is no
grant here to make by omission.

**4. What the explicit trigger protected is disclosure, and disclosure survives.**
ADR-0077 §8's third reason is the one this ADR replaces, and it is worth quoting
whole because the replacement is narrow: "**The first version of a producer that
sends accumulated history to a model should not run without the user knowing.** The
user chooses when the transcript is read, and the outcome tells them which route
read it (§3). That is a stronger form of consent than a setting, and it costs
nothing while the product has one user and one spoke." Three of that sentence's own
qualifiers have turned. It is no longer the *first version* — ADR-0121, ADR-0159,
ADR-0162, ADR-0212 and ADR-0214 have all landed on this producer since. It no longer
*costs nothing*: #1737 is the record of what it costs, which is that the deployed
hub's user model does not accumulate at all unless somebody remembers to run a
command. And "the user knowing" is not what the explicit trigger was the only source
of: the armed job is stated in the hub's configuration record at every start —
`service/configuration.py` carries `observation_interval_armed` and
`observation_interval_seconds` on its allowlist — it appears in `hub_ready`'s job
list, and every run still reports the route that read the episodes, which is the
half of reason 3 that was doing the work. What is genuinely given up is the *per-run*
choice, and that is stated as given up rather than argued away.

**What the deployed hub sets: nothing.** After this decision and its
implementation, a hub needs no `ASSISTANT_OBSERVATION_INTERVAL` to observe, and the
deployment that #1737 was written about stops depending on an environment variable
being remembered. An operator who wants the job off sets the variable to the disable
sentinel, and an operator who wants a different cadence sets a duration; both are
ADR-0083 §7's existing convention and neither is new surface.

**The one thing an armed default must not do is move a measure silently, and it does
not.** `service/configuration.py` records at the observation entry that this is "the
job that *grows* the user model, and it ships disabled — so the moment it is armed is
an intervention no measure of accuracy may straddle unknowingly". The moment stays
observable: arming changes the `CONFIGURATION` trace the hub emits at startup, and
ADR-0120 §8 "partitions at a `CONFIGURATION` trace diff", so a window spanning the
upgrade that flips this default is partitioned by the mechanism that already exists
for an operator flipping it by hand. §6 is what keeps the *populations* apart once it
is armed.

### 6. A scheduled run writes on its own initiative, and the seam says so

> **Normative.** `observe_due` is a distinct operation seam. It joins ADR-0120 §3's
> **machine** set. It does **not** join the user set or the direct set, and
> `observe` stays in the user set exactly where §3 put it.

**ADR-0120 §3 obliges this lane to classify rather than leaving it.** Its prose:
"Defaulting an unrecognised seam into either list would silently absorb a new writer
into a measure […] An unclassified count that rises is a visible prompt to classify
the new seam." A seam on neither list "is dropped from every measure into
`unclassified`, which fails safe and fails silently", so a lane that adds a writing
seam and says nothing has hidden its own writes from every measure.

**The machine set, and the tie-break is §3's own stated purpose.** Two of §3's
grounds point in different directions for a scheduled observation, and it is worth
saying so plainly rather than picking one quietly. `observe` is in the user set
because "the content originates with the user even though the proposal is the
model's" — and that stays true of a scheduled run. The machine set is "the
operations that write on their own initiative" — and that is what a scheduled run
is. What decides between them is the purpose §3 states for having the split at all:

> Arming consolidation adds a job that supersedes and retires records on its own
> initiative. A correction rate that counted those would rise on the day of the
> arming, and the rise would be a fact about the scheduler rather than about the
> user model. Splitting the population by the *cause* of the write is the only way
> the before/after reads as what #829 says it is.

This ADR arms a job. If its writes carried the `observe` seam, every measure over
the user set would step at the moment of arming, and the step would be a fact about
this decision rather than about the user model — the precise confound §3 exists to
prevent, produced by the precise act it was written about. So the cause governs, and
the cause is the schedule.

**What that costs, stated rather than buried.** §3 put `observe` in the user set on
the ground that "A supersession reached that way is the user correcting the system
through the only route the system offers", and once the job is armed most
observation is scheduled — so §5's correction rate loses that population and is
computed over `converse`, `resume`, `learn`, `answer` and hand-run `observe` alone.
That is a narrower measure, and it is the honest one: a supersession the scheduler
reached at 03:00 is not a user correcting anything at 03:00. Whether the measurement
lane wants a fourth set — writes whose *content* is the user's but whose *cause* is
not — is a measurement decision this ADR does not take, and it is filed rather than
pre-empted.

**ADR-0120 §6's `observe` reinforcement share is left where two other decisions put
it.** Its exclusion rests on "Successive observation batches overlap by design, so
their reinforcements are dominated by the *stage re-reading the same episodes*" — a
premise ADR-0212's cursor already falsified, before this ADR, since successive passes
now share no turn. Arming the job then moves the share's *population* as well, since
scheduled reinforcements carry the new seam. Neither consequence is this ADR's to
decide: the first is the cursor's and the second is a question about what §6 should
measure. Both are filed together, and §10 names the issue.

### 7. Three `Settings` figures, two of them new, all under ADR-0083 §7's duration discipline

> **Normative.** `Settings` gains `observation_quiet_window`, a `timedelta`
> defaulting to **10 minutes**, refused at load unless it is exactly a `timedelta`
> that is finite and strictly positive, in the `gt=timedelta(0)` form ADR-0083 §7
> requires of every duration on this loop. It is **not** nullable.

> **Normative.** `Settings` gains `observation_max_unobserved_age`, a `timedelta`
> defaulting to **6 hours**, under the same refusal and likewise **not** nullable.

> **Normative.** `observation_interval`'s default becomes **15 minutes**. Its type,
> its `gt=timedelta(0)` refusal and its `None`-means-disabled spelling are
> unchanged.

> **Normative.** No cross-field validation is added between these three, or between
> any of them and `episode_retention`. Each is refused on its own range and on
> nothing else.

**Named figures rather than "bounded", for ADR-0074 §9.3's reason.** ADR-0093 §5
restates it for exactly this kind of field — "its figures are `Settings` fields with
named defaults, and a figure outside its range is refused at load rather than at the
first run" — and ADR-0083 §7 named every interval it added on the same ground. A
figure left to the implementation is two conforming hubs behaving differently while
each believes it conforms.

**Ten minutes for the quiet window.** It is #1737's own example and it is the right
order of magnitude for what it decides: long enough that a pause to read, to think or
to fetch a coffee does not end the exchange, short enough that a conversation
finished before lunch is a belief by lunch. It is the figure most likely to be tuned
by a deployment, which is why it is a field.

**Six hours for the backstop.** It is chosen against the two figures it sits
between, not in isolation. It must be comfortably above the quiet window, so that a
conversation with any ordinary pause is served by the quiet arm and the backstop
stays the exception it is meant to be — thirty-six times above, at the defaults. And
it must be far below `episode_retention`'s 30 days, so that a continuously-active
conversation's oldest unobserved turns are distilled two orders of magnitude before
they can expire. Six hours is also about the length of the longest working session a
single user plausibly holds in one conversation, which makes the backstop's ordinary
firing rate roughly "once per long day of continuous use" rather than "several times
an hour".

**Fifteen minutes for the interval, and the figure is bought against the loop rather
than against cost.** The tick decides latency, not spend: with the cursor, a tick
with no due candidate performs one bounded listing read and returns, so asking more
often costs almost nothing. What it does cost is the serial loop — ADR-0111 §4's
arithmetic is "at most one budget plus one chunk per interval", and against
`scheduler_run_budget`'s five-minute default a fifteen-minute interval holds this
job's worst-case share of the loop to about a third of its own period, leaving the
hourly purge and sweep the rest. The user-visible figure it buys is the sum of the
quiet window and one interval: at the defaults, a conversation that ends is a belief
within twenty-five minutes.

**Neither new field is nullable, and ADR-0084 §3's departure is the precedent.**
There, four figures were made non-nullable because "a scheduler job that never runs
is a coherent deployment" while a hub with no frame cap is not. The same test
separates these fields from the interval beside them. `observation_interval` is
nullable because "the job is off" is a deployment; a quiet window of `None` would
have to mean "observe mid-conversation", which is a *policy* this ADR ruled against
in §1 and not a way of turning anything off, and a max age of `None` would mean "no
backstop", reinstating the gap §2 exists to close. Off is spelled once, on the
interval, which is also what keeps ADR-0083 §7's "'Disabled' is `None`, never `0`"
readable: one field means off, and a reader does not have to work out which of three
nulls disabled the job.

**No cross-field refusal, and the reason is that both orderings are meaningful.**
§2 already names what a backstop below the quiet window does — it makes the job a
pure age trigger — and a load-time refusal would reject a configuration that
behaves exactly as its author asked. A refusal against `episode_retention` is worse:
that field is nullable and `None` means keep forever, so the comparison has a branch
with no meaning, and the setting it would police is the *user's* deliberate choice
(`core/config.py`: "``None`` here means 'keep forever', it is the user's deliberate
choice"). The interaction is stated in the Consequences instead, which is where a
figure an operator should think about belongs when refusing it would be wrong.

### 8. ADR-0111 §4's admissibility condition, checked rather than assumed

> **Normative.** Every operation inside one pass is bounded by a deadline, and the
> deadlines are the two the corpus already supplies: the pass's single model call
> by `model_timeout_seconds`, and every write that reaches an embedder by
> `embedding_timeout_seconds` (ADR-0118). This ADR supplies no new deadline and
> introduces no operation that lacks one.

**§4 states this as a condition on being chunked at all**, and ADR-0212 §3 assigned
the check to this lane by name: "Discharging it is the trigger lane's, not this
one's […] what that lane will be checking is named here so it is not rediscovered".
§4's words are "a job whose chunk reaches an operation with no deadline is not a job
that may be chunked under this ADR, and its lane owes that operation a deadline
before it may be scheduled". Checked, in the order a pass performs them:

- **The listing and the probes** — `conversations_with_unobserved_turns`, and one
  `turns_after` with `limit` 1 per candidate examined — are bounded local index
  reads of the same class every other job on the loop already performs, and each is
  bounded in *size* by ADR-0212 §8's own limits.
- **The page** — `turns_after` at `observation_batch_size`, then one `MemoryStore.get`
  per turn — is the read ADR-0077 §1 sized deliberately, "a handful of exchanges, not
  a month of transcript".
- **The model call** — at most one per pass (ADR-0212 §3) — is bounded by
  `model_timeout_seconds`, "the 'Deadline for a single model attempt, in seconds'"
  ADR-0111 §4 itself names, and it does not fall back (ADR-0077 §3), so the true
  bound is one attempt's product rather than a chain of providers'.
- **The write path** — the gate, the memory store and the deferral queue — reaches
  the embedder through `MemoryStore.write_atomic`, which carries
  `embedding_timeout_seconds` since ADR-0118, "applied by the composition root at the
  single wiring point every consumer goes through".
- **The advance** — one `record_observed` — is a local index write with two
  conditions read inside the per-conversation exclusion (ADR-0212 §8).

That is the same discharge `core/config.py` records for the consolidation interval,
resting on the same two figures and inventing nothing: "A chunk's model call is
bounded by `model_timeout_seconds`; its writes reach the `Embedder` through
`MemoryStore.write_atomic`, and that seam carries `embedding_timeout_seconds` since
ADR-0118".

**Two chunked jobs may be armed at once, and the arithmetic adds.** With
`consolidation_interval` also set, the loop's worst case is two run budgets plus two
chunks per the shorter interval. Both budgets are the same field, both intervals are
readable off the configuration, and ADR-0083 §7's tolerance is unchanged: "a missed
or late tick is never a correctness bug". A deployment that finds the purge running
late has two figures to raise and it can see both.

### 9. Failure, and the two races a run meets

> **Normative.** A pass that raises leaves ADR-0212 §6 to say what happens to the
> watermark, and halts the run: no later pass is performed, the run returns, and
> ADR-0111 §6 retries it at its next due instant with no backoff and no durable
> failure count.

> **Normative.** An `UnknownConversationError` raised for the conversation a pass
> selected is **not** a failure of that pass. It means the conversation was stamped
> deleted between the listing and the read, the run drops that candidate, and the
> run continues. It is never treated as a fault to log as one, and it never halts
> the run.

> **Normative.** A run whose passes all complete but which observed nothing —
> because no candidate was due, or because every due candidate's page resolved to
> no episode — is a **successful** run. It is not logged as a failure and does not
> change the job's next due instant.

**Halting on a raise is ADR-0111 §5 applied, not a stricter rule.** §5's disposition
is "either the chunk was recorded or it was not", and a pass that raises before its
advance attempt is a chunk that was not recorded — ADR-0212 §6 keeps the watermark
where it was, so the same page is re-read on the next run and nothing is lost. §5's
own carve-out is also kept: "A per-item ruling that is a *normal outcome* of
processing — a proposal the gate rejects, a turn ADR-0074 §5 says is 'skipped, not an
error' — is not a chunk that failed to be recorded, and does not halt anything." A
page with an unresolved turn, a producer that proposes nothing, a proposal the gate
refuses: none of those stops a run.

**The deletion race is the one place this ADR reads a raise as a normal outcome, and
the reason is that the listing already excludes the state.**
`conversations_with_unobserved_turns` returns "every conversation that is **not**
stamped deleted"; `turns_after` and `record_observed` raise
`UnknownConversationError` "for an id that names nothing or names a conversation
stamped deleted". So the error is reachable from exactly one thing — a deletion
landing between the two calls — and ADR-0074 §8's tombstone makes that an ordinary
act the user performs, not a fault. Halting a whole run because the user deleted a
conversation while it ran would let one ordinary act stop a tick, and it would look
like a store fault in the log. Dropping the candidate cannot loop: the next pass
re-reads the listing, from which the deleted conversation is already absent.

**The overlap race needs nothing from this ADR.** A hand-run `assistant observe` may
run while a scheduled run is in flight, and ADR-0212 §5 already rules that case
whole: "Overlap safety rests on `record_observed`'s monotonicity (§8) and on nothing
else […] whichever order the calls arrive in, the **higher** of the two positions
stands and the lower performs nothing." The scheduler cannot overlap *itself* — a job
"structurally unable to overlap itself", ADR-0083 §7 — so the only overlap available
is with the operator, and the store settles it.

### 10. What the implementing lane owes, what is filed, and what this ADR does not decide

**It lands after ADR-0212's implementation, and cannot land before.** Every clause
above calls one of the three operations ADR-0212 §8 adds to `ConversationStore` and
reads the member it adds to `Conversation`. A trigger lane merged ahead of them
would have nothing to call.

**The surface it lands, by file:**

- **`core/config.py`** — `observation_quiet_window` and
  `observation_max_unobserved_age` as §7 specifies, and `observation_interval`'s
  default moved from `None` to fifteen minutes. That field's description still reads
  "How often the hub distils beliefs from the most recently active conversation.
  Disabled by default until the observation cursor lands", both halves of which
  ADR-0212 and this ADR have made false; it is replaced, not patched.
- **`orchestration`** — `Engine.observe_due`, and the stage's due selection behind
  it. `Engine.observe` is untouched: same signature, same seam, same behaviour, and
  ADR-0212 §3's "given none" default still selects the first candidate without a due
  test, because an operator who typed the command has already decided it is time.
- **`service/scheduler.py`** — the observation row's body becomes
  `engine.observe_due`. Its name, its interval field and its position in §7's fixed
  order are unchanged, and its docstring's observation paragraph is rewritten
  against §5 above rather than left stating a disabled default.
- **`service/configuration.py`** — the two observation keys stay exactly as they
  are; the comment beside them ("it ships disabled — so the moment it is armed is an
  intervention no measure of accuracy may straddle unknowingly") is rewritten to say
  what §5 says instead, which is that the moment is the upgrade and ADR-0120 §8
  partitions on it.
- **`evaluation/_vocabulary.py`** — `MACHINE_SEAMS` gains `observe_due` (§6). A lane
  that lands the operation and not this member has hidden every scheduled write from
  every measure, silently, which is the failure that file's own comment names.
- **No `core/protocols.py`, no `core/types.py`, no `PROTOCOL_VERSION` bump**, and no
  member on `ObservationReport`.

**What the tests owe, beyond the ordinary:** that the quiet arm is decided on
`last_active_at` and the backstop on the span's start; that a run selects the first
**due** candidate and not merely the first candidate; that the budget is checked at a
pass boundary and not inside one; that a deleted conversation drops rather than
halting; that a run's writes carry the run's seam and not `observe`'s; and that the
shipped default arms the job, pinned as a value rather than asserted in prose.

**Filed rather than absorbed: #1815.** ADR-0120 §6's exclusion of the `observe`
reinforcement share rests on an overlap ADR-0212 removed, and §6's population and
§5's move again once this job is armed and carries its own seam. Both are
measurement questions for a measurement lane, and §6 above says why neither is taken
here.

**What this ADR does not decide:**

- **The cursor.** ADR-0212's, ratified, and used throughout without amendment
  (§11(d)).
- **Anything about the observer's proposals.** ADR-0077's — what may be proposed,
  the utility bar, the prompt, the payload, the route, the confidence function and
  the proposal bound. This ADR changes *when* episodes reach the producer and
  nothing about what it does with them.
- **Consolidation's cadence.** ADR-0111 §4's and `consolidation_interval`'s, which
  stay disabled by default for the reasons `core/config.py` records at that field —
  reasons this ADR does not extend to observation and §5 says why.
- **A selector for episodes belonging to no conversation.** ADR-0212 §9 leaves it,
  ADR-0077 §8 forecasts it, and a trigger over a population that does not exist yet
  would be a rule nobody could test. The condition that fires it is the same one
  ADR-0212 names: the first producer of episodes that no `ConversationTurn` names.
- **A trigger for anything else on the loop.** No other job's default moves and no
  other job gains a due test.
- **What a run tells a user about its progress.** `ObservationReport` gains nothing;
  ADR-0111 §11's "**Progress reporting to a user.** What a run *tells* somebody is
  the report surface #494 and #659 hold open" is where that stays.
- **Whether an armed observer should be paced by cost rather than by time.** A
  spend-based bound — passes per day, calls per hour — is a different instrument
  from an interval and would need a durable counter, which is durable state under
  ADR-0083 §6's discipline bought against a cost nobody has measured on this job
  yet. The condition that fires it is a deployment reporting the spend as the thing
  it wants to bound.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is applied below to a **named clause** of each earlier ADR, in
that section's own currency: "Would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?"

> **Normative.** **(a) This ADR partially supersedes ADR-0083**, in ADR-0070 §3's
> sense, in exactly one scope: **§7's job-table row for observation**, in its
> **Default** cell — "**disabled**" — and its **Calls** cell — "the `Engine`
> observation operation". The default becomes a finite duration (§5, §7) and the
> call becomes `observe_due` (§3). Nothing else of §7, and nothing else of ADR-0083,
> is replaced.

The test comes out yes on both cells. A reader holding only ADR-0083 would build a
hub whose observation job is absent from the table unless configured, and would have
it call the same façade operation the CLI calls — and after this ADR both are wrong
in a way that changes what they build.

**§7's fourth bullet is *not* superseded, and the distinction is the bullet's own
conditional.** It reads: "Enabling it on a timer before the cursor exists buys
repeated cost and no new coverage. The interval exists so that enabling it is
configuration; the default is off until the cursor lands (§13)." Every sentence
stays true as written: the first is about the state *before* the cursor, and the
second states the condition under which the default holds. ADR-0212 satisfied that
condition. A reader holding only ADR-0083 therefore reads the bullet correctly both
before and after this ADR — they simply need to know whether the cursor has landed,
which the bullet itself tells them to ask. This is the same shape ADR-0083 §15 used
on its own deferrals — "the deferring sentence stays true and now has an answer" —
and recording a supersession against a conditional that fired would misdescribe what
happened.

**§7's other clauses bind this job and are relied on rather than narrowed**: the
fixed delay after completion, the serial loop and its accepted starvation, "a missed
or late tick is never a correctness bug", "A failing job never takes the process
down", "**No job gets new store surface**", the `gt=timedelta(0)` duration discipline
and "**'Disabled' is `None`, never `0`**". §8 likewise: this ADR's new operation is
the maintenance surface §8 provides for, and the job body is still "a public `Engine`
call". §13's deferral of the cursor was discharged by ADR-0212, not by this ADR, and
nothing here reaches it.

**The `Status` line's form changes, and that is ADR-0082 §2 rather than a loss.**
ADR-0083's line reads "Accepted, §7 amended by ADR-0111"; adding a leading
`Partially superseded by` token drops `Accepted` (ADR-0070 §4) and, under ADR-0082
§2, "no amendment qualifier is written on that line". The ADR-0111 qualifier is
therefore removed from the line and **not** removed from the record: ADR-0083's
2026-08-06 note carries that amendment in full, and its 2026-08-06 follow-up records
its ratification. Leaving the qualifier in place beside a leading token would also
break ADR-0070 §4's one authoring constraint — "a scope names a clause, not another
ADR […] every `ADR-NNNN` after the leading `Partially superseded by` is a target" —
by declaring ADR-0111 a partial superseder of ADR-0083, which it is not.

> **Normative.** **(b) This ADR partially supersedes ADR-0077**, in exactly one
> scope: **§8's third reason**, beginning "**The first version of a producer that
> sends accumulated history to a model should not run without the user knowing**"
> and ending "it costs nothing while the product has one user and one spoke". §5
> replaces it. Nothing else of §8 and nothing else of ADR-0077 is replaced.

The test comes out yes: a reader holding only ADR-0077 would conclude that an
observer must not run except when the user asks it to, and after this ADR one runs
on a cadence nobody set. §5 states the four grounds and states plainly what is given
up, which is the per-run choice.

**Three clauses of §8 that look reachable, and are not.**

- **Reason 1** — "**Nothing is waiting on it, and a turn is.**" — is kept whole and
  §4 restates it as a normative clause of this ADR. Nothing here runs inside
  `converse`, and no turn waits on a pass.
- **Reason 2** — the volume gate naming #423, #313, #314 and #306 — is **discharged,
  not superseded**. Its four conditions are closed issues, so a reader holding only
  ADR-0077 checks them and reaches this ADR's answer unaided. ADR-0083 §15's rule
  applies: a condition that has been met is not a sentence that has become false.
- **Reason 4** — "**Leg 5's scheduler owns cadence, and inherits this operation
  unchanged.** […] Cadence then becomes configuration rather than a contract change"
  — is what this ADR *uses*. The one place it is stretched is worth naming: the
  scheduler now calls a **second** operation rather than "the same façade
  operation". That is a widening of the mechanism reason 4 names and not a
  contradiction of what it decided, which was that cadence is configuration; §3
  gives the three grounds, of which the protocol bump is the one a reader of
  ADR-0077 could not have anticipated. §8's own "no polling, no background task"
  sentence was already spent by ADR-0083 §7 and is not reached again here (§4).

> **Normative.** **(c) This ADR partially supersedes ADR-0120**, in exactly one
> scope: **§3's second normative clause**, in the membership of the **machine** seam
> set alone, which gains `observe_due`. The user set, the direct set, the
> unclassified rule, §3's other clauses and every measure §4, §5, §6, §7 and §8
> define are untouched.

The test comes out yes on that clause and only there: a reader holding only
ADR-0120 would compute the machine set as four members and drop every scheduled
observation write into `unclassified`, which §3 designs to fail safe *and silently*
— so the reader would act differently and would not be told. §3's prose already
provides for the act ("An unclassified count that rises is a visible prompt to
classify the new seam"); what it does not do is name the member, and naming it is
what a lane adding a writing seam owes.

**No record is owed on ADR-0120 §5 or §6, and #1815 is why rather than an
exception.** §5's correction rate and §6's share are both defined over seam sets
*by reference*, so both stay literally computable after (c) and neither definition
changes. What changes is the population each one ranges over, which is the thing
those definitions are for. The questions that raises — whether §6's exclusion still
earns its place, whether the share should span both seams, whether §3 wants a fourth
set — are decisions about what should be measured, not clauses this ADR made false,
and #1815 holds them.

> **Normative.** **(d) This ADR records nothing against ADR-0212, ADR-0111,
> ADR-0093, ADR-0214 or ADR-0074**, and each is used as written.

- **ADR-0212.** Every clause it states about a pass binds this job unchanged, and §3
  above is written to keep it that way: a scheduled pass takes §3's *named-id*
  branch, so §3's "given none" default is not narrowed; §4's tail start is not
  reached by §2's due test, which asks a different question and says so; §5's advance
  and its overlap rule are relied on for the run's termination and for the
  hand-run race; §8's three operations are called at the bounds it gave them. §9
  named this lane as the one that would arm the job, which is a deferral discharged
  and therefore a stacked addition under ADR-0083 §15's rule.
- **ADR-0111.** §4's run clause, §5's halt and §6's no-backoff retry are applied in
  §3, §8 and §9 exactly as written; §2's wall-clock exclusion is *not* reached,
  because the instant in §2 above decides a trigger and not a position, which that
  clause is stated over. §11's own deferral of "Enabling any job the scheduler ships
  disabled" is discharged by this ADR for one job, which is again a stacked addition.
- **ADR-0093.** §6's clause is used in the direction it was written — it forbids
  transferring observation's disabled default to a sensor — and §5 above declines to
  transfer a sensor's disabled default back. Neither §6 nor §7 states a rule about
  observation's own default, so neither becomes false. §5's clock-bounded read is
  cited as a posture, not amended.
- **ADR-0214.** Cited as the precondition it was. Nothing about its arm, its scope
  or its target class is touched.
- **ADR-0074.** §3's capture, §5's skip rule, §7's horizon and §8's tombstone are all
  read as they stand; §9's ordering rule was already replaced for this listing by
  ADR-0212 §10(b) and is not reached again.

## Consequences

**A fact told in chat becomes a belief without anybody running a command**, which is
#1737's title and the point of the pair. At the shipped figures the wait is bounded
by the quiet window plus one interval — twenty-five minutes from the end of a
conversation — and by six hours for one that never ends.

**The first tick after an upgrade does real work, and it is bounded work.** ADR-0212
§4 starts every pre-existing conversation at its tail, so each costs exactly one pass
to reach a watermark at its highest turn and then leaves the candidate set. A hub
with *n* conversations therefore pays about *n* model calls once, spread over as many
runs as `scheduler_run_budget` needs, and then settles to a rate set by how much the
user actually says. That is a visible cost on the day of the upgrade, and it is the
cost of the coverage ADR-0077 §8's first gap named.

**The hourly jobs run later than they used to.** ADR-0111 §4's arithmetic now applies
to a job that is armed by default: the loop's worst case gains one run budget plus
one pass per observation interval. ADR-0083 §7's tolerance covers it — "a missed or
late tick is never a correctness bug" — and a deployment that wants the purge
punctual raises `observation_interval` or lowers `scheduler_run_budget`, both
readable off the configuration.

**Two measures change population on the day this lands**, and neither changes
silently: §6 puts scheduled writes on their own seam, ADR-0120 §8 partitions the
window at the configuration diff, and #1815 holds the question of what the measures
should do about it.

**A deployment can still mis-set the pair.** A backstop above `episode_retention`
lets a continuously-active conversation's oldest unobserved turns expire before the
backstop fires; a backstop at or below the quiet window makes the quiet arm inert and
the job an age trigger. Both are coherent configurations, neither is refused at load
(§7), and both are named here so that an operator meeting one recognises it.

**What would trigger revisiting this decision.** A conversation that stays a
candidate across many runs without its watermark moving — which §3's termination
argument says cannot happen and which would mean ADR-0212 §5's invariant is not
holding in practice. A run that regularly spends its whole budget on one
conversation, which would mean the per-pass bound is too small for the volume rather
than that the order is wrong. A deployment reporting the *spend* rather than the
latency as the thing it needs to bound, which is §10's last deferral. Or a second
principal (`track:identity`), where "quiet" stops being a property of one user's
attention and the window has to be argued again.

## Alternatives considered

**The existing interval as the backstop, which #1737 leaves open.** Rejected in §2:
the interval says how often the question is asked and a backstop says how old the
material may get, and a conversation in continuous use answers "not quiet" at every
tick however frequent. The variant where the run falls back to "serve the first
candidate anyway when nothing is quiet" was considered and is worse than a second
field rather than cheaper: it reads a mid-conversation page on *every* tick where the
user is talking, which is exactly the fragment the quiet window exists to avoid, and
it makes the quiet window a preference rather than a rule.

**Quiet measured on `last_turn_at`.** Rejected in §1. It calls a conversation quiet
while its next turn is in flight, and — decisively — it has no relation to the order
ADR-0212 §3 ratified, so every quiet test becomes a scan where the chosen field makes
it a single row.

**An argument on `Engine.observe` instead of a new operation.** Rejected in §3 on
three grounds, of which two are mechanical: `observe` is a wire operation declared on
`AssistantEngine`, so an argument moves `PROTOCOL_VERSION` under ADR-0124 §9; and one
seam serving both callers makes an armed job's writes indistinguishable from a user's
under ADR-0120 §3. The third is that `ObservationReport` describes one pass and a run
performs many.

**One pass per scheduled run.** Rejected in §3. It is simpler and it makes the drain
rate a function of the interval alone, which turns the first armed tick's backlog
into a queue drained one conversation per interval. ADR-0111 §4 already supplies the
right bound for a job that spends a model call per unit of work, and it is a bound an
operator can read.

**Shipping disabled and letting the deployment arm it.** This is the status quo and
it is what #1737 exists to change; §5 argues it against the four grounds rather than
asserting the flip. The honest cost of rejecting it is stated there: the per-run
consent ADR-0077 §8's third reason describes is given up, and disclosure rather than
choice is what remains.

**A per-turn or end-of-turn trigger.** Refused outright by §4, and it is ADR-0077
§8's reason 1 rather than a preference: a turn would wait on a model round trip for
work nobody is waiting for. "After the answer is sent" is the same thing with a
longer name — the process is resident, so the work still lands inside the turn's
operation, and the quiet window is the honest way to say "when the exchange is over".

**A durable "last observed at" instant on the conversation index.** It would make the
backstop a single field comparison with no probe read at all. Rejected because it is
a second store-written member on a `core` type — golden rule 5 surface — bought to
save at most fifty single-row index reads on the minority of ticks where nothing is
quiet, and because ADR-0212 deliberately added exactly one member and argued the
bound. The condition that would buy it is a deployment where the probe reads are
measurably the cost, which they are not at a bounded listing of fifty.
