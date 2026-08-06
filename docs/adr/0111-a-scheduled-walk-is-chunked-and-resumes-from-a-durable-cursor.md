# 111. A scheduled walk is chunked, and resumes from a durable cursor that never leads its effects

- Status: Proposed
- Date: 2026-08-06
- **Durability clause.** Every reference below to ADR-NNNN is to its text as
  merged on 2026-08-06, not to its status on any later day. Where a later ADR
  changes one of them, this ADR is read against the text quoted here and the
  later ADR's own record says what moved.
- **This is leg 7's fork 6** (#729): it decides how a scheduled job *walks and
  resumes*, and nothing about what a job may conclude. It discharges the durable
  cursor #632 tracks, answers the three questions ADR-0106 defers to this lane by
  name — cursor placement, backoff, and whether a run halts on the first refusal
  — and rules on the refusal-versus-fault legibility #710 reports.
- **Surface.** This ADR adds two `Settings` fields (§4). It touches **no**
  Protocol in `core/protocols.py` and **no** type in `core/types.py`, so golden
  rule 5 is not triggered and no triad is owed; §9's discriminator would at most
  add an `AssistantError` subclass, which ADR-0083 §6 already classified — "a new
  `AssistantError` subclass is neither a Protocol nor a `core/types.py` model, so
  golden rule 5 is not triggered". The mechanics it decides live in `service/`
  and, for the cursor, below each subsystem's own façade.
- **No implementation lands with it.** No `src/`, no `tests/`. Enabling any job
  the scheduler ships disabled is an implementation lane's act against this text
  once ratified, never this ADR's (§11).
- **Records owed under ADR-0082 §1, and this change writes both.** ADR-0083 §7
  and ADR-0077 §8 each carry a sentence a reader would now read more widely than
  it holds. §10 names them, applies the test clause by clause, and states what is
  *not* owed and why. **Nothing here supersedes anything**, wholly or in part.

## Context

### The cursor is deferred by decision in three ratified places, and tracked by one issue

**ADR-0083 §13** defers it by name and gives the reason the deferral is not
laziness:

> **The observation cursor.** ADR-0077 §8 files it as leg 5's — "a cursor is
> durable per-user state whose natural owner is the resident process". It is not
> taken here, for a reason worth stating: it is **new durable state**, so it is
> itself subject to §6's upgrade-with-state discipline and needs its own decision
> about what an older or newer build does with a cursor it does not understand.
> Deciding that inside a lifecycle ADR would bury it.

**ADR-0077 §8** carries the same deferral from the observer's side — "There is no
durable cursor, and re-observation is safe by construction" — and **§11** files
"the durable cursor that stops it re-reading what it has seen (§8)" with leg 5.
Leg 5 arrived and re-deferred it. **#632** is the tracking entry, opened because
the only way to find the deferral was to read the three ADRs.

The consequence is stated plainly in `docs/roadmap.md`'s leg 3: the scheduler
ships the observation job disabled "because a timer without a cursor re-reads one
window and reaches nothing new". ADR-0083 §7 says the same thing as a decision —
"Enabling it on a timer before the cursor exists buys repeated cost and no new
coverage."

So the cursor is the thing standing between the scheduler and the first job it
was built to run. That is why it is decided here rather than inside the lane that
enables a job: a lane that needs the cursor to ship would be deciding new durable
state under schedule pressure, which is exactly what ADR-0083 §13 declined to do.

### ADR-0106 defers three questions to this lane, by name

ADR-0106 §6 rules that a consolidation whose question the deferral queue refuses
"has not been disposed of", that "its material is retained and re-proposed on a
later run", and that "the consolidator does not record that chunk as done". It
then names what it is not deciding:

> **How** it retains and retries — cursor placement, backoff, whether a run stops
> on the first refusal — is fork 6's scheduler-chunking lane and is not decided
> here; **that** it must is decided here, because the containment of §6 fails
> without it.

Its §12 repeats the assignment — "cursor placement, backoff, and whether a run
halts on the first refusal are fork 6's scheduler-chunking lane. **Fires with
that lane**" — and its ratification note records the deferral as unfired because
this lane was unopened. The consolidation implementation lane is blocked on these
three answers, and on nothing else this ADR holds.

### A weeks-resident process restarts, and that is the whole argument for chunking

ADR-0083 §1 makes the hub a resident process; §4 gives it a two-phase shutdown;
§5 maps its exits into "come back" and "stay down", which presupposes a
supervisor that restarts it. A process designed to be restarted by a supervisor,
upgraded in place, and stopped by an operator is one whose longest-running job
will be interrupted partway through, repeatedly, over the months leg 7's exit
test measures.

A walk with no durable position loses everything it has done when that happens.
Worse, it loses it *silently* and identically every time: a job whose typical run
exceeds its mean time between restarts never finishes at all, and its logs say
only that it started. Resumability is therefore not a recovery path bolted onto a
bulk job — it is the property that makes a bulk job possible on this process
model, which is the same conclusion ADR-0104 §2 reached for the re-embedding
migration and titled "Resumability is a property of the design, not a recovery
path".

Fork 6's premise follows from that rather than from a preference: **because
chunk-and-resume is required anyway, concurrency buys only failure modes.** A
concurrent scheduler would buy throughput the chunking already bounds, at the
cost of two jobs contending on one store's connection — which ADR-0083 §7 named
as one of the things serialising removes.

### ADR-0083 §7 accepted starvation and named the revisit condition

§7's ruling is explicit and so is its limit:

> **Jobs run serially, and starvation is accepted rather than engineered away.** A
> long job delays its siblings. […] Revisit when a job's typical runtime approaches
> its interval, which is what consolidation (leg 7) is likely to do first.

Consolidation is leg 7 and it is the job §7 predicted. The revisit condition has
fired. What §7 did not have — and what a bulk job over an accumulating store
makes necessary — is any *bound* on how long the long job delays its siblings.

### #710: a raising job produces two records, and the second one lies about severity

**#710** reports that every scheduler job that raises emits both the structured
record `Scheduler._log_failure` writes at warning and, additionally, an asyncio
**ERROR** with a full traceback from asyncio's own default exception handler. The
second record originates in `Engine._tracked`, which runs the underlying work as a
shielded task (ADR-0042 §2, ADR-0054): the awaiter retrieves the exception, the
inner shielded future's result is not retrieved, and asyncio reports it as
unhandled.

That matters here because of what ADR-0097 §5 ratified: an armed calendar job over
an ungranted source "logs a refusal every interval, and that is the correct
behaviour rather than a defect to design around". So a deployment behaving exactly
as ratified emits an ERROR-level traceback every interval. The issue records that
no Tier 1 content leaks — the refusal messages are payload-free — so this is a
severity and legibility problem, not a data-residency one. It rides with this ADR
because "what a scheduled run says when it does not finish its work" is a
run-semantics question, and every clause below produces outcomes that are neither
success nor fault.

### What makes this a decision rather than an implementation detail

Three things, each of which has a wrong answer that looks reasonable:

1. **A cursor is new durable state**, and ADR-0083 §13 already ruled that it owes
   a decision about what a build does with a cursor it does not understand. §6's
   state-fault rule is sitting right there and refusing to start is the *wrong*
   answer for this class of state; that has to be said, because nothing stops a
   lane from reaching for the nearest ratified precedent.
2. **A cursor that leads its effects loses work permanently and silently**, which
   is the exact failure the cursor exists to prevent, reintroduced by an ordering
   choice. The safe direction has to be stated as an obligation, not left to be
   got right per job.
3. **Chunking without a bound on the run is not chunking**, it is the same walk
   with more commits. The bound is what converts an unbounded walk into a
   duty cycle a serial loop can carry, and it is what answers §7's revisit.

## Decision

### 1. The scheduler holds no cursor; a cursor lives in the store whose progress it records

> **Normative.** The scheduler holds no durable state of its own. A scheduled
> job's resumption position is durable state of the subsystem whose store the job
> walks, reached only through the same public `Engine` operation the scheduler
> already calls, and the scheduler neither reads it, writes it, nor passes it.

ADR-0083 §8 rules that "every scheduler job is a public `Engine` call" and that
the scheduler "lives in a new top-level `ai_assistant/service/`". §7 adds "No job
gets new store surface. Every one of them calls an operation that already
exists." A cursor held by `ai_assistant.service.scheduler.Scheduler` would breach
both in one move: it would make `service/` a persistence layer, and it would put
the position on the *outside* of the façade where it can be handed to a job that
disagrees with it.

The decisive argument is not tidiness, it is atomicity. ADR-0104 §2 ruled that a
migration's chunk rows and "the cursor naming the last source `rowid` copied are
written in one transaction on the work store, so the recorded cursor can never
claim progress the work store does not hold." Only the component holding the
store's connection can do that. The scheduler holds a façade, so a
scheduler-owned cursor could only ever be written *after* the operation returned
— which is a second, weaker guarantee bought by moving the state further from the
data it describes.

**The operation therefore takes no cursor argument and needs no new façade
parameter.** `engine.observe` is called by `ai_assistant.service.scheduler.jobs_for`
today with no arguments, and the CLI calls the same operation; both resume from
the same durable position, which is the property ADR-0077 §8 asked for when it
said the scheduler "becomes a second caller of the same façade operation" and
"Cadence then becomes configuration rather than a contract change."

> **Normative.** A cursor is per walked order and per job. Two jobs walking the
> same store do not share a position, and one job walking two orders holds one
> position in each.

This is the placement half of ADR-0106's first deferred question, answered: **the
cursor is placed inside the store the job walks, under the subsystem that owns
it.** `src/ai_assistant/memory/sqlite_store.py` already carries the shape — a
`meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` table beside a `records` table
whose primary key is an explicit `rowid INTEGER PRIMARY KEY` — so the mechanism
exists and this clause chooses it rather than inventing one.

### 2. A cursor is a position in a total insertion order, and nothing else

> **Normative.** A cursor names a position in an order the walked store already
> maintains, which must be total over the walked rows and must not reorder rows
> under later writes. It is not a set of processed identifiers, not a wall-clock
> instant, not an offset into a paged read, and not a fraction of the work.

Each excluded shape has a specific failure. **A set of identifiers** is unbounded
durable state that grows with the store, so the mechanism that exists to make a
walk affordable becomes the largest thing in the database. **A wall-clock
instant** is not a total order over writes and does not have to be monotone with
them: a row written with an earlier instant after the cursor passed — a backfill,
a clock correction, an instant supplied by a caller rather than by the store —
sits permanently behind the position and is never reached, which is the coverage
failure the cursor exists to fix arriving through the cursor itself. **A fraction**
is not a position at all; it cannot survive the store changing size.

**The offset exclusion is the one a reader is most likely to reach for**, because
the read surfaces these jobs already use are paged. `MemoryStore.list_beliefs`
enumerates live beliefs a page at a time, and ADR-0110 §6 records the property
that makes an offset unusable as a resumption position: its offset paging "may
skip or repeat a record" over a mutating store. An offset is a count into a
result set, so a row inserted or deleted below it moves every later row's number
— which is the "must not reorder" half of the clause failing on the most ordinary
write the store takes. The order underneath the page is fine to walk; the *page
number* is not the position. ADR-0110 §6 files improving that paging with this
lane, and this clause is the answer: it is not improved, it is not used.

> **Normative.** A cursor absent from the store means the walk has not started
> and the job begins at the first row of its order. A cursor is never initialised
> to a sentinel value.

ADR-0104 §2 ruled the same thing for the migration and stated the reason, which
transfers unchanged: "There is no integer to use as one. `rowid` is an explicit
`INTEGER PRIMARY KEY` here, so it starts at `-2**63` and SQLite has nothing below
that to compare against — which makes the obvious sentinel, `0`, silently skip
every row at or below it." The failure mode is the worst kind available to a
cursor: a silent skip that reports success.

**A high-water mark answers "what is new", not "what has changed", and that limit
is named rather than hidden.** A row updated in place below the cursor keeps its
position and is not revisited — the same property ADR-0104 §2 flagged when it
wrote that "a record updated or deleted below the cursor is not revisited by a
resumed scan". For a one-shot migration that is fatal and §2 spends a fingerprint
on it; for a *recurring* job it is usually correct, because the work is the new
material. A job whose correctness requires reconsidering changed rows cannot
express its selection as a high-water mark alone, and this ADR gives it no other
mechanism: what such a job selects is its own ADR's question, not this one's
(§11).

### 3. A cursor may lag its effects and may never lead them

> **Normative.** A chunk's effects and the cursor recording that chunk are
> committed in one transaction where they live in one store. Where the effects
> land in a different store from the cursor, the effects are made durable first
> and the cursor is advanced afterwards, never the reverse.

> **Normative.** A scheduled walk is at-least-once. A crash, a shutdown, or a
> failure between a chunk's effects and its cursor advance re-processes that
> chunk on the next run, and no clause of this ADR may be implemented in a way
> that turns that repetition into a skip.

This is the whole safety argument, and it is an asymmetry rather than a
preference. A cursor that lags its effects costs repeated work; a cursor that
leads them costs coverage, permanently and silently, because nothing downstream
knows the rows existed. The costs are not comparable, so the ordering is not a
judgement call per job.

**Repetition is already ruled safe where these jobs write.** ADR-0077 §8 states it
for observation — "re-observation is safe by construction… the gate folds each
into a `REINFORCE` on the existing record rather than writing a duplicate" and
"§5's confidence function **closes the repetition route to inflation**: the same
belief on the same support scores the same however many times it is derived". The
cost it names is "a model call and a moved `provenance.last_updated`", accepted
there and accepted here. Any job that cannot tolerate a repeated chunk is a job
that cannot be scheduled under this ADR, and its lane must say so rather than
invert the ordering.

**Two stores is the ordinary case, not the exotic one.** An observation walk reads
the conversation index and writes to the memory store; a consolidation walk reads
and writes memory but may also enqueue into the deferral queue. SQLite gives no
transaction across those files, so the second clause is what covers the case the
first cannot, and it covers it in the safe direction by construction.

### 4. A run is bounded by a deadline; a chunk is bounded by a count; both are configuration

> **Normative.** A chunked job's single run commits chunks until either its work
> is exhausted or its run budget is spent, then returns. The budget is checked
> only at a chunk boundary, so no chunk is abandoned part-way and a run may
> overrun its budget by at most the duration of one chunk.

> **Normative.** A job may be chunked only if every operation it performs inside
> one chunk is itself bounded by a deadline. A run's overrun past its budget is
> bounded by one chunk's duration, and that bound is worth exactly as much as
> those deadlines are.

> **Normative.** `Settings` gains `scheduler_run_budget`, a `timedelta` defaulting
> to five minutes, and `scheduler_chunk_size`, an integer defaulting to 50. The
> duration is refused at load unless it is finite and strictly positive, in the
> `gt=timedelta(0)` form ADR-0083 §7 requires of every duration it adds; the count
> is refused at load unless it is exactly an `int` in `[1, 2**63)`.

**The two bounds do different jobs and neither substitutes for the other.** The
*chunk count* bounds what a crash discards and what a run may overrun by; the
*run budget* bounds how long a chunked job delays its siblings on a serial loop.
Bounding only by count leaves the run's duration a function of per-record cost —
a model call for consolidation, an embedding for a re-derivation — which is
unknowable at configuration time. Bounding only by time leaves the transaction
size unbounded, so a slow run's interruption discards more work the slower the
machine is.

**Re-arming is ADR-0083 §7's, untouched.** A run that returns with work remaining
is re-armed at completion plus its interval exactly like one that finishes,
because the scheduler is not told which happened and does not need to be. That is
deliberate: it keeps §7's "A job's next run is scheduled from its *completion*,
not from its start" and its consequence — a job "structurally unable to overlap
itself" — literally intact, and it keeps the whole of chunking below the façade
where §1 put the cursor. It also forecloses the hot loop that an immediate re-arm
invites, in which a run that can make no progress becomes due the instant it
returns.

**What this buys is a duty cycle, and the starvation bound is its arithmetic.** A
chunked job occupies the loop for at most one budget plus one chunk per interval,
so a sibling due while it runs waits at most that long, and a backlog drains at
roughly `budget / interval` of the machine's throughput. Five minutes against the
one-hour default of `retention_purge_interval` and `conversation_sweep_interval`
is a delay a purge can absorb: ADR-0083 §7 records that "a missed or late tick is
never a correctness bug", because ADR-0007 §2 enforces retention at read time so
"the privacy guarantee does not depend on a background job".

**That arithmetic is only as good as the chunk's own deadlines, which is why the
second clause is a clause and not a remark.** A budget checked at a chunk boundary
bounds nothing if the boundary can fail to arrive: a provider call that never
returns holds the serial loop for as long as it hangs, and no figure in
`Settings` would say so. The corpus already supplies the deadline for the cost
that dominates these jobs — `model_timeout_seconds` is the "Deadline for a single
model attempt, in seconds", defaulting to 60, carrying `gt=0` and
`allow_inf_nan=False` precisely because infinity "would silently disable the
deadline". So a chunk's true bound is the product `core/config.py` already names,
"``max_attempts * timeout + total backoff``", multiplied by the chunk's records
— not one timeout, and worth computing before setting a chunk size. **What the
clause adds is that this must be checked rather than assumed**: a job whose chunk
reaches an operation with no deadline is not a job that may be chunked under this
ADR, and its lane owes that operation a deadline before it may be scheduled.
**This ADR adds no cancellation mechanism** and does not reach inside a chunk;
declaring the admissibility condition is the part that is run mechanics, and
supplying a missing deadline belongs to whichever seam lacks it.

**Fifty is chosen small on purpose.** The chunk is both the unit of loss and the
unit of overrun, and the jobs this ADR is written for spend a model call or an
embedding per record; a deployment whose per-record cost is high wants it lower,
which is precisely why it is a field rather than a constant. Naming a figure
rather than saying "bounded" follows ADR-0074 §9.3's rule that "a 'bounded
default' with no figure is two conforming stores handing the same continuation
different history", and the neighbouring precedent is `observation_batch_size`,
whose default of 20 is deliberately small for the same reason: "this batch is both
a prompt and an egress."

**`[1, 2**63)` is not decoration, and `observation_batch_size` is the precedent
for both ends.** A chunk size is what a walking job hands a paged read as its
limit, and `MemoryStore.list_beliefs` raises `ValueError` "If `limit` or `offset`
falls outside `0 <= value < 2**63`" — a bound its own docstring explains is
refused rather than clamped because "Python's `int` is unbounded and SQLite's
parameter binding is not, so an over-wide value raises `OverflowError` out of the
driver while an in-memory store answers with an empty page". A setting that loads
happily and then fails on the job's first scheduled run — hours after the
misconfiguration, in a background task — is the failure `core/config.py` already
refuses for exactly this shape: `observation_batch_size` carries `ge=1` and
`lt=2**63` on the stated ground that "A setting the store would refuse must fail
at load, not at the first observation." **"Exactly an `int`" is the other half**,
and it is the corpus's own words: `bool` is an `int` subclass, so `True` would
otherwise load as a chunk size of one, which is why these fields are
`_IntegerSetting` rather than bare `int`. Both bounds are read off the
neighbouring field rather than invented here.

**The bounds are the scheduler's mechanics, not a job's quality parameters.**
ADR-0106 §12 files "the deferral queue's cap value for a scheduled producer" with
the consolidation lane's own measurement, and ADR-0103 §5 divides semantics from
parameters. That division is respected: these two figures bound a *run*, not what
a run may conclude, and the quality parameters stay where those ADRs put them.

### 5. A run halts at the first chunk it cannot record as done

> **Normative.** When a chunk cannot be recorded as done, the run stops
> immediately, leaves the cursor at the last chunk that was recorded, and returns
> without processing any later chunk.

**This is forced by §2's contiguity, not chosen.** A cursor is one position in one
order. If a run skipped an unrecordable chunk and went on to the next, either the
cursor advances past the skipped chunk — losing it permanently, which §3 forbids —
or the cursor stays put while later chunks are processed, which makes the whole
range between the cursor and the run's end ambiguous: on resume it is
re-processed, so the later chunks' effects happen twice while the skipped one is
retried, and the position no longer means what §2 says it means. Halting is the
only disposition under which the cursor keeps its meaning.

**This answers ADR-0106's third deferred question and satisfies its §6.** ADR-0106
§6 requires that a refused consolidation's "material is retained and re-proposed
on a later run" and that "the consolidator does not record that chunk as done".
Halting delivers exactly that, and it delivers something §6 could not oblige on
its own: it stops the run from spending model calls producing further questions
for a queue that has already answered `DeferralAdmissionOutcome.REFUSED` because
it is at its cap — a condition that will not change part-way through a run, since
nothing but a user answering a question clears it.

**The rule is stated over the *disposition*, not over the *reason*.** A capacity
refusal, a store error, a shutdown, and a spent budget all reach it identically:
either the chunk was recorded or it was not. A per-item ruling that is a *normal
outcome* of processing — a proposal the gate rejects, a turn ADR-0074 §5 says is
"skipped, not an error" — is not a chunk that failed to be recorded, and does not
halt anything.

### 6. There is no backoff; a failed or refused run is retried at its next due instant

> **Normative.** A run that halts or raises is retried at its next due instant
> under ADR-0083 §7's fixed delay after completion. No job varies its interval in
> response to failure, and no failure count is durable.

**This answers ADR-0106's second deferred question, and the answer is "none".**
That is a decision rather than an omission, and it rests on three things:

- **The interval is already the backoff.** A fixed delay after completion bounds
  retry cost by construction, and the cost of a halted run is small: §5 stops it
  at the first unrecordable chunk, so a run against a full queue does one chunk's
  work and returns.
- **A backoff curve is durable state about failure**, which lands it back under
  ADR-0083 §6's upgrade-with-state discipline for no coverage gain, and makes a
  job's cadence a function of history that an operator cannot read off the
  configuration.
- **The corpus already ratified retry-at-interval for the case that would most
  tempt a backoff.** ADR-0097 §5 rules that an armed job over an ungranted source
  "logs a refusal every interval, and that is the correct behaviour rather than a
  defect to design around". Backing that off would make the refusal quieter over
  time — the opposite of what an operator needs from a state only they can clear.

**A run that makes no progress is not distinguished from one that does**, because
under §4 it cannot spin: the next attempt is one full interval away either way.

### 7. A cursor this build cannot read is discarded and the walk restarts; it is never a state fault

> **Normative.** A cursor that is absent, unreadable, malformed, or written in a
> form this build does not understand is discarded, and the walk restarts from the
> beginning of its order. It is never advanced past a position that could not be
> read, and it never refuses the hub's start.

> **Normative.** A store whose recorded cursor and recorded progress disagree is
> treated as damaged in the same way: the cursor is discarded and the walk
> restarts. Nothing may resume from a position the store's contents do not
> support.

**This is the decision ADR-0083 §13 demanded and it comes out the opposite way
from §6, for §6's own stated reason.** §6's rule is that "The hub refuses to start
when the state it would serve **cannot be served correctly by this build**", and
its test "is whether serving would be **silently wrong** — answers a client cannot
tell from correct ones. It is not 'is this state unfamiliar'." Applied to a
cursor: a cursor holds no evidence and answers no query. Discarding one costs a
repeated walk — the cost §3 already accepted and ADR-0077 §8 already named — and
returns nothing wrong to any client. So an unreadable cursor is not a state fault,
`IncompatibleStateError` is not its class, and a build that refused to start over
one would take a resident process down over scaffolding. §6's own contrast with
ADR-0064 §3 is the same reasoning applied twice: rules that look opposed come out
differently because the facts differ, and "'Must not refuse' is not a general
preference for starting; it is the correct answer for the class of fault ADR-0064
§3 is about."

**Discard-and-restart is also the only disposition consistent with §3.** The
alternative — keeping an unreadable cursor and refusing to walk — converts a
transient, recoverable state into a job that is permanently and quietly stopped,
which is the failure #738 describes in its own domain: a store that "sticks
instead of being discarded", where "the operator gets a permanent, opaque failure
instead of a slow success".

**On #738 specifically, and what this ADR does and does not cover.** #738's shape
— rows present, cursor absent, read as "resumable from the beginning" and
therefore permanently stuck — is covered *as a shape* by the second clause above,
which is why that clause is stated over the disagreement rather than over any
particular store's schema. Its *instance* is not this ADR's and is not amended by
it: `Reembedder._resumable` in `src/ai_assistant/memory/reembed.py` belongs to the
re-embedding migration, ADR-0104 §6 rules that "No part of the system runs this
migration on its own", and a job nothing schedules is not a scheduled job. **#738
stays open under ADR-0104 §2 and is fixed there.** This ADR neither amends
ADR-0104 nor pre-empts that fix; what it does is make the same disposition
obligatory for everything the scheduler *does* walk, so the next occurrence of the
shape is not decided case by case.

### 8. The loop stays serial: §7's revisit fires, and the answer is a bounded run

> **Normative.** The scheduler runs one job at a time. A long-running job is made
> tolerable by bounding its run (§4), never by running jobs concurrently.

ADR-0083 §7's revisit condition — "when a job's typical runtime approaches its
interval, which is what consolidation (leg 7) is likely to do first" — has fired,
and this is the answer to it. Serialising is kept, with its stated benefits
unchanged: "a scheduler that is one thing to reason about, one thing to cancel and
one thing to drain", and no "question of two jobs contending on one store's
connection."

**Concurrency would buy throughput this ADR bounds on purpose and would cost the
properties the rest of it depends on.** Two jobs walking one store contend on one
connection; two cursors advancing under one another make §3's ordering guarantee a
per-pair argument instead of a rule; and ADR-0083 §8's shutdown ordering — "Service
shutdown stops and joins the scheduler *before* calling `Engine.aclose()`" — stops
being one join. Against that, the thing throughput would buy is a backlog draining
faster, which §4 already makes a configured duty cycle an operator can raise.

**This is fork 6's premise stated as a ruling**, and it is the one place this ADR
constrains a later lane's design rather than its mechanics: a lane that wants
parallelism inside a job's own chunk — several records embedded at once, say —
is not touched by this clause, which is about the scheduler's loop.

### 9. A refusal and a fault are different records, and an expected refusal is exactly one record

> **Normative.** A scheduled run that ends in a refusal the corpus rules correct
> for the deployment's configuration is recorded distinguishably from a run that
> ends in an unexpected fault, and the distinction is drawn from the exception's
> class, never from its message text.

> **Normative.** An expected refusal produces exactly one operational record per
> run. No component may emit a second record for the same refusal at a severity an
> operator's monitoring treats as a fault.

**The problem is that a correct deployment currently looks like a failing one.**
#710 records both records verbatim: `Scheduler._log_failure` writes
`hub_scheduler_job_failed` at warning "with `job`, `error_class`, `cause`,
`elapsed_seconds` and a `detail` saying the job is retried", and asyncio's default
handler additionally writes an ERROR with a full traceback. ADR-0097 §5 rules the
refusal itself correct behaviour, so on a resident hub the correct state emits an
ERROR-level traceback every interval. That runs against ADR-0083 §6's legibility
posture, where the structured record "is the one designed to be read".

**Class, not message, because the corpus has already paid for the alternative.**
ADR-0083 §6 records exactly this defect in `_verify_or_init_meta`'s refusal: it
"is a `MemoryStoreError` — a subsystem error from below the disk line — so the
entry point cannot tell 'this deployment cannot serve this store' from 'this disk
is broken' without matching on a message string", and the remedy was a class. The
scheduler already carries the one string match the corpus permits, and its own
docstring says why it is bounded: `ENGINE_SHUTTING_DOWN` is "the engine's own
message constant, so the two sides cannot drift; treating *every* `RuntimeError`
as a shutdown would turn a real bug into a silent clean exit." A second string
match, over messages no constant pins, is not that.

**Which classes are refusals is the implementing lane's list, and it is short
today**: `SourceNotGrantedError` is the one ADR-0097 §5 names, and a queue-at-cap
disposition under ADR-0106 §6 is the next. Whether the discriminator is a marker
base class or an explicit tuple is a code decision this ADR does not take; what it
takes is that a discriminator must exist and must not be a message.

**The mechanism that removes the second record is not this ADR's.** It lives in
`Engine._tracked`'s shielded task — engine-lifecycle ground under ADR-0042 §2 and
ADR-0054, where #710 says "the cancellation/drain semantics are load-bearing, so it
wants its own look rather than a reflex `add_done_callback`". Nothing here
authorises a change there; the second clause above states the requirement that
lane must satisfy, so it is no longer a noise complaint with no ruling behind it.
**#710 stays open and is closed by that lane.**

> **Normative.** A run that halts under §5 without processing its remaining work
> is recorded as a completed run that did not exhaust its work, not as a failure.

A halt is neither of the two things §7 of ADR-0083 knows about. Recording it as a
failure would make a queue at its cap indistinguishable from a broken store;
recording it as an ordinary completion would make a job that has stopped making
progress invisible. The record must say which, because under §6 the only thing an
operator can act on is the underlying condition.

**Tier 1 stays out of all of it.** ADR-0004 §5's rule that "Logs are Tier 2 only"
is untouched, and ADR-0083 §7's job record already excludes results because "an
`ObservationReport` names beliefs, which is Tier 1 content". A cursor position is
a row position, not content, and a chunk count is a number; both are Tier 2 and
may be logged.

### 10. Amendment records under ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text — "A later ADR's change is
recorded on the earlier ADR exactly when the later ADR amends a named clause of
that earlier ADR", the test being whether "a reader holding only the earlier ADR
[would] now act differently, or read one of its clauses more widely than it now
holds". Applied here, clause by clause.

**Two records are owed, and this change writes both.**

**ADR-0083 §7.** Its sentence — "**Jobs run serially, and starvation is accepted
rather than engineered away.** A long job delays its siblings" — is preceded by
the reasoning that "a tick is a walk to exhaustion whose duration is a function of
the backlog, not of the interval". A reader holding only ADR-0083 would build
consolidation as a walk to exhaustion and would read §7's acceptance of starvation
as unbounded. §4 makes a chunked job's run bounded and §8 makes that the answer to
§7's own revisit condition. That is reading a clause more widely than it now
holds, so the test is met. **What is *not* changed is important and is stated so
the record is not read too widely in the other direction**: the fixed delay after
completion, the serial loop, the job table, the disabled default for observation,
the `gt=timedelta(0)` discipline, and the "no job gets new store surface"
constraint are all untouched and this ADR depends on each of them. ADR-0083's
`Status` is plain `Accepted`, with no leading token, so under ADR-0082 §2 the
qualifier belongs on it and the dated note goes below.

**ADR-0077 §8.** Its sentence "a cursor is durable per-user state whose natural
owner is the resident process" is a filing note explaining why the cursor went to
leg 5, but it reads as a placement claim, and ADR-0083 §13 quotes it as one. A
reader holding only ADR-0077 would build the cursor in the resident process. §1
rules that it lives in the store the job walks, below the façade, and that the
resident process holds none of it. The test is met on the second limb, and the
record is owed. **This is an amendment and not a supersession** under ADR-0070
§1: what ADR-0077 §8 *decided* — that observation is an explicit operation, its
selection rule, its skip rule, and that there is no durable cursor today — is
untouched, and "re-observation is safe by construction" is not merely preserved
but relied on by §3. ADR-0077's `Status` carries the leading `Partially superseded
by` token, so under ADR-0082 §2 **no qualifier is written on that line** and the
appended dated note is the whole record.

**No record is owed on:**

- **ADR-0083 §13.** It defers the cursor to a decision of its own. This ADR is
  that decision. ADR-0083 §15 rules the classification for exactly this shape: "A
  deferral discharged by the ADR it named is a stacked addition, not an amendment
  — the deferring sentence stays true and now has an answer." The two halves of
  this ADR are therefore classified differently on purpose: discharging §13 is a
  stacked addition, and bounding §7's run is not.
- **ADR-0077 §11.** Same rule: it files the cursor with a later leg and this ADR
  supplies the answer. Its sentence stays true.
- **ADR-0106 §6 and §12.** §12 names this lane and these three questions
  explicitly and says the deferral "**Fires with that lane**". Answering a
  question an ADR deferred to you by name is the discharge ADR-0083 §15
  describes. §5's halt is what §6's "does not record that chunk as done" already
  required; no sentence of ADR-0106 becomes false or over-wide.
- **ADR-0110 §6 and §9.** They decline the enumeration's mechanics to this lane
  by name — "it is the scheduler chunking-and-cursor lane's (#632, #710)" — and
  §9 records that the reference is by issue only "because a citation to a number
  no ref carries is a Tier 1 defect under ADR-0088 §6 as ADR-0090 §1 narrows it".
  Supplying the mechanics a clause deferred to you is the discharge ADR-0083 §15
  describes, so no record is owed and none is written. §2's offset exclusion is
  the one place this ADR answers something §6 files with this lane, and it
  answers it by declining the shape rather than by changing anything §6 decided:
  `MemoryStore.list_beliefs`' paging is untouched and its known behaviour over a
  mutating store stays exactly what §6 says it is.
- **ADR-0104.** §2's rules are quoted here as the model and are restated at a
  different seam, not changed; §6 keeps the migration outside the scheduler
  entirely, which is why §7 leaves #738 to ADR-0104's ground. Every sentence of
  ADR-0104 stays true and this ADR obligates nothing of the migration.
- **ADR-0076 §2.** Its requirement that a sweep "drain to an empty batch" binds
  the conversation sweep, which holds no cursor and is not a chunked job. Nothing
  above reaches it, and §4's bound is scoped to chunked jobs precisely so it
  cannot.
- **ADR-0097 §5.** Its ruling that a refusal every interval is correct behaviour
  is kept by §6 and relied on by §9. §9 adds an obligation about how that refusal
  is *recorded*; §5 said nothing about severity or record count, so it is not read
  more widely.
- **ADR-0042 §2 and ADR-0054.** §9 states a requirement and explicitly declines
  to decide where the shielded future's exception is retrieved. Neither ADR's
  clauses are touched.
- **ADR-0007 §2.** §4's budget is quoted against it and it comes out unchanged: a
  late purge is not a correctness bug because retention is enforced at read time.
  Nothing here relies on the purge being timely.
- **ADR-0083 §6.** §7 above distinguishes a cursor from the state §6 governs by
  applying §6's own test and finding it unmet. ADR-0083 §15 already settled that
  classification for a sibling case: "Examining a revisit condition and finding it
  unmet changes nothing." §6's rule is neither narrowed nor widened — a foreign
  embedding space still refuses to start.

**Both records are well-formed from the moment they are written**, on ADR-0083
§15's own ground: "The existence condition is that the naming ADR ships in the
same change, not that it has ratified." Both notes name ADR-0111 and ship in this
change; if this ADR does not land, neither does either note.

**The records are append-only and deliberately narrow.** ADR-0070 §1 permits the
`Status` header edit and the appended dated note and nothing else, so no sentence
of ADR-0083 or ADR-0077 is rewritten. ADR-0083 §7's "walk to exhaustion" reasoning
and ADR-0077 §8's "natural owner is the resident process" are **left standing as
written**, and each note records what has become narrower and why.

### 11. What this ADR does not decide

- **What a scheduled job may conclude.** This ADR decides how a job walks and
  resumes; the semantics of what it writes are its own ADR's. **Consolidation's
  taint, band and refusal rulings are ADR-0106's** and are untouched.
- **What closes a validity window, and what demotion means.** **ADR-0110** decides
  it, and the seam between the two ADRs is stated on both sides. A reconciliation
  sweep is a scheduled walking job and inherits every clause above; what it may
  conclude about a record is ADR-0110's and not this ADR's. Read the seam this
  way: **§§1–8 bind the walk, ADR-0110 binds the verdict.** ADR-0110 §6 states
  the property that makes the split safe from its side — each close "is justified
  by one record and one reading and by nothing else", so a reconciliation
  examining only part of the live set "closes **fewer** windows and never a
  different one" — and its §9 files cursor placement, chunking, backoff,
  halt-on-refusal and resumption here by issue rather than by number, because
  this ADR's number was unissued when it was written. That composition is checked
  and not merely asserted: §3's at-least-once ordering can only repeat a close's
  input, which §6's first clause makes harmless, and §5's halt can only leave
  windows unexamined, which §6 rules closes fewer and never different. Its status
  on any later day is its own lane's; this ADR reads it as merged on 2026-08-06,
  per the durability clause above.
- **The observation job's selector.** ADR-0077 §8 ratifies a *window* — "that
  conversation's most recent `observation_batch_size` turns", or the same window
  over the most recently active conversation — and calls it "today's only
  selector". A cursor-driven walk is a second selector, and choosing its order and
  its unit is ADR-0077's ground, not this ADR's. What binds that choice is §2:
  whatever order it walks must be total and must not reorder under later writes.
  **Filed as its own issue.**
- **Enabling any job the scheduler ships disabled.** ADR-0083 §7's table ships
  observation disabled "until the cursor lands (§13)". This ADR decides the
  cursor; it does not land it and does not flip a default. That is an
  implementation lane's act against this text once ratified.
- **Coverage over an external source.** §2 presumes an order the *store*
  maintains. A reader over a source this system does not own has no such order —
  ADR-0093 §7b pins overlap, occurrence-counting and the timezone source for the
  calendar reader against exactly that gap — and nothing above supplies one. A
  cursor is not the remedy for a receding window over somebody else's data.
- **#738's fix.** §7 covers the *shape*; the instance is ADR-0104's ground and
  stays with its issue.
- **Where `Engine._tracked`'s shielded exception is retrieved.** #710's mechanism,
  ADR-0042 §2 and ADR-0054's ground (§9).
- **The deferral queue's cap value for a scheduled producer**, which ADR-0106 §12
  files with the consolidation lane's measurement, and any parameter beyond the
  two figures §4 names, which ADR-0103 §5's division puts with leg 8.
- **Progress reporting to a user.** What a run *tells* somebody is the report
  surface #494 and #659 hold open; §9 decides only what is written to the
  operational log.

## Consequences

**The scheduler's first job becomes enablable.** ADR-0083 §7 ships observation
disabled and §13 says why; both halves of that reason — a cursor as new durable
state, and what a build does with one it cannot read — now have an answer, so
enabling the job becomes a lane with a ratified text to build against rather than
a lane that must decide durable state on the way past.

**The consolidation lane is unblocked on exactly the three things it was blocked
on.** Cursor placement is §1, backoff is §6, and halting on the first refusal is
§5 — and §5 turns out to be forced by §2's contiguity rather than chosen, which
means ADR-0106 §6's retention obligation and this ADR's mechanics cannot come
apart later.

**A long job's cost becomes a configured duty cycle rather than an unknown.** An
operator reading `scheduler_run_budget` against a job's interval can state the
worst delay a sibling job suffers **and the deadlines of the operations inside
one chunk** — §4's second clause makes the second half a precondition of being
chunked at all, so the figure is computable rather than nominal. That is the
bound ADR-0083 §7 accepted the absence of, and it is what makes the serial loop
keep its advantages at leg 7's volume instead of becoming the thing that forces
concurrency.

**What gets harder: every chunked job now owes an order, and a deadline on
everything inside its chunk.** §2 refuses instants, offsets and identifier sets,
so a subsystem that wants a scheduled walk must have — or add — a total,
non-reordering key over the rows it walks; §4's second clause adds that an
operation with no deadline disqualifies the job until it has one, which is a real
constraint on any future chunked job reaching a seam the corpus has not yet
bounded. `src/ai_assistant/memory/sqlite_store.py`
has one; a store that does not will discover it here rather than after the job
ships.

**Repeated work is now a designed cost rather than an accident.** §3's
at-least-once direction and §7's discard-and-restart both spend work to protect
coverage. On the observation path that cost is a model call, which ADR-0077 §8
already priced and accepted; on a future path where a repeated chunk is expensive
or externally visible, this ADR's clauses are the constraint that lane must argue
against, and it should expect to lose to §3.

**A refusal stops looking like an outage.** §9 makes "the deployment is configured
this way" and "something is broken" two different records, which is what makes
ADR-0097 §5's ratified every-interval refusal survivable in a monitored
deployment.

**What would trigger revisiting this.** A job whose correctness requires
revisiting rows updated below its cursor (§2 names the limit and gives no
mechanism); a store that cannot supply a total non-reordering order; a deployment
where one budget for all chunked jobs is demonstrably wrong because two chunked
jobs have very different costs; or measurement showing the duty cycle cannot keep
up with accumulation, which is leg 8's data and would reopen §8 rather than §4.

## Alternatives considered

**A cursor held by the scheduler, in `service/`.** Rejected on ADR-0083 §7 and §8
— it makes `service/` a persistence layer and gives every job new store surface —
and, decisively, on atomicity: only the holder of the store's connection can write
the cursor in the chunk's own transaction, which is the guarantee ADR-0104 §2 was
willing to restructure a migration around. A scheduler-held cursor could only ever
be written after the operation returned.

**A single scheduler state store shared by every job.** The same objection plus a
new one: it is a second database in `data_dir` under ADR-0083 §6's upgrade
discipline, holding nothing but positions into other databases, and every one of
its writes is a cross-store ordering problem §3 would then have to govern
everywhere instead of at the exceptions.

**A wall-clock cursor — "observed everything before instant T".** Rejected in §2.
It is the most natural shape and the most dangerous: the orders these jobs walk
are not guaranteed monotone in any instant a caller or a clock supplies, so a row
that lands behind the mark is skipped forever, silently. The failure is
indistinguishable from working correctly.

**Re-arming an unexhausted job immediately instead of after its interval.** It
drains a backlog faster, and it was seriously considered. Rejected because it
changes ADR-0083 §7's re-arm rule — costing a partial supersession for throughput
§4 already exposes as a setting — and because it needs a guard against a run that
returns unexhausted having made no progress, which would otherwise spin the loop.
Keeping the interval keeps chunking entirely below the façade and leaves the
scheduler unchanged, which is why no supersession appears anywhere in §10.

**Exponential backoff on a failing job.** Rejected in §6. It is durable state
about failure, it makes cadence unreadable from configuration, and it makes the
one refusal the corpus explicitly ratified as correct behaviour quieter over time.

**Refusing to start on an unreadable cursor, by analogy with ADR-0083 §6.** The
nearest ratified precedent and the wrong one. §6's test is whether serving would
be silently wrong; a cursor answers no query, so discarding it returns nothing
wrong to anybody, and refusing would take a resident process down over
scaffolding.

**Skipping an unrecordable chunk and continuing the run.** Rejected in §5 because
it is unrepresentable: one position in one order cannot express "everything up to
here except that". Either the skipped chunk is lost or the position stops meaning
what §2 says.

**Deciding the observation job's cursor-driven selector here.** Tempting, because
it would close #632 end to end, and ADR-0077 §8's own phrase "today's only
selector" invites a second one. Declined because choosing what the observer reads
is ADR-0077's ground and this lane's fence is run mechanics; §2's constraints bind
whatever that lane picks, which is the part this ADR is entitled to decide.

**Concurrency instead of chunking.** Rejected in §8, and rejected as fork 6's
premise: resumable chunks are required by the restart model regardless, so
concurrency adds contention, a harder drain, and pairwise cursor-ordering
arguments in exchange for throughput §4 already exposes as a setting.
