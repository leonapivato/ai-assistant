# 141. A notification measure counts rulings, and the ruling seam emits the trace it is counted from

- Status: Proposed
- Date: 2026-08-12
- **This decision adds contract surface, and it is one member.** `TraceKind`
  gains `NOTIFICATION` (§2). That is a `core/types.py` change, so golden rule 5
  and ADR-0015 §5 bind: this ADR is merged, ratified, before anything implements
  against it, and the required review set is adversarial **and** architecture.
  ADR-0119 §13e is the clause that puts the price here — "A member added to
  `TraceKind`, `TraceOutcome`, `TraceRef` or `TraceRecordSet` takes its own
  ratified ADR, merged before anything implements against it" — and §10 records
  that the member is the whole of the addition: no Protocol changes, no
  `Settings` field appears, no `AssistantEngine` method, wire operation or CLI
  command is created, and no other enumeration gains a member.
- **This ADR's ratification.** It decides a contract surface, so the required set
  is adversarial **and** architecture, and it is ratified only on a tree where
  both are green — `CONTRIBUTING.md` → "Finishing an ADR PR: `Proposed` through
  the reviews, `Accepted` on the way out". A blocker on the first flipped tree
  returned it to `Proposed` under that section's recovery clause, so it takes the
  route that clause describes and is ratified on its **second** flip. This PR's
  round record carries every round and both lenses' outcomes; the `Status` line
  above states where the sequence has reached. Nothing implements against §10
  until this has merged.
- **It answers #980 by ruling the measure's definition, and it does not close
  it.** #980 asks for an instrument in the tree. This ADR supplies what an
  instrument needs before it can be written — what is counted, out of what, and
  from where — and the harness itself is the follow-on lane, in the shape
  ADR-0120 §9 already fixed. #980 stays open as that lane's issue.
- **The premise #980 reasons from does not hold, and §Context shows it against
  the merged tree.** #980 proposes a measure "over figures the store already
  holds", concluding that "every input is already durable in `notifications.db`
  and `outbox.db`; none of it needs new recording". Three merged facts refuse
  that: a reconsideration **overwrites** the ruling it replaces, the budget
  ledger **deletes** its own history on every read, and a device's
  acknowledgement is recorded as a **dismissal**. What the stores hold is the
  present state of a set of records; what a measure of proactivity needs is a
  record of the rulings that produced it, and the two differ by exactly the
  events the question is about.
- **This ADR amends nothing and supersedes nothing.** §11 applies ADR-0082 §1's
  test at each place a record looks owed — ADR-0119 §3 most closely — and records
  why none is.
- **It discharges no deferral of ADR-0130 and reverses none.** ADR-0130 §2's
  refusal to carry delivery state stands untouched, and §9 below states what that
  costs this instrument rather than routing around it.

## Context

### Leg 10 left a half of its exit test that nobody can read

`docs/roadmap.md`'s leg 10 exits when "the assistant tells the user something
they did not ask for and were glad to be told, and the user can tune what reaches
them". The second half is mechanical and leg 10 shipped it. The first half is
experiential, and the ruling on #879 defers it: the owner is away, so there is no
daily use for a notification to land in, and no judgement to make about whether
landing was welcome.

That deferral is fine. What is not fine is that when the owner returns and usage
resumes, **there will be nothing to compare against.** #980 is the record of it,
found by leg 10's QA pass (#978) against the pattern
`.claude/skills/qa-leg/SKILL.md` §2 states: "Where a leg ships no instrument, say
so in the run's record — each leg should leave one behind, and its absence is
what makes the next leg's QA expensive." Leg 8 left three measures and a console
script (ADR-0120). Leg 10 left neither, and #978 records the concrete price: every
figure in that run was obtained by writing throwaway drivers and reading timings
out of the hub's structured log by hand, so nothing in the tree reproduces any of
them.

**The arc gate is why this is worth a decision rather than a script.**
`docs/roadmap.md` → "The gate between leg 10 and leg 11" makes leg 8's measures
able to overrule a plan — "if memory precision is flat, or the correction rate is
not falling, through legs 9 and 10, then legs 11 and 12 pause". A notification
figure read off an ad-hoc query has no standing in a conversation like that. A
figure two implementations would compute identically, over a population defined
in a ratified text, does.

### What the chassis actually records, as merged

The definitions below are only as good as their agreement with what is on
`origin/main`, and #980's suggested shape does not survive the check. This is the
inventory each clause was written against.

**The trace stream carries four kinds and four emitters, and no notification
module is among them.** `TraceKind` has `OPERATION`, `RETRIEVAL`, `MEMORY_WRITE`
and `CONFIGURATION` (ADR-0119 §3). The emitting sites are
`orchestration/traces.py` (from `Engine._tracked`), `memory/sqlite_store.py`,
`memory/ingest.py` and `service/configuration.py`. **No notification module holds
a `TraceSink` at all** — not `memory/notification_store.py`, not
`memory/notification_policy.py`, not `memory/notification_outbox.py`, not
`orchestration/notifications.py`, not `orchestration/upcoming.py`.

**What notification work does produce is `OPERATION` traces, one per engine call,
and two of them carry a count.** `Engine._tracked` wraps every public method, so
eight notification-shaped seams appear in the stream today —
`notice_upcoming_events`, `notifications`, `next_notification`,
`dismiss_notification`, `forget_notification`, `notification_preferences`,
`set_notification_preferences` and `reconsider_notifications`. Two carry a metric:
`notice_upcoming_events` carries `noticed`, how many candidates a producer run
offered, and `reconsider_notifications` carries `reconsidered`, how many held
records one sweep re-ruled. Both are literals written in `orchestration/engine.py`
and both are aggregates over a run. **None of the eight is on either seam
allowlist** in `evaluation/_vocabulary.py`, so none contributes to any measure
ADR-0120 defines; they reach the per-seam latency summary and the stream-health
counts and nothing else.

**`notifications.db` holds one row per admitted record**, with columns `id`,
`candidate_key`, `candidate`, `kind`, `reason`, `failed`, `ruled_at`,
`reconsider_at`, `admitted_at`, `retention`, `dismissed_at` and `dropped_at`; a
one-row preferences table; and `notification_interruptions(spent_at)`, the budget
ledger. `outbox.db` holds `outbox(candidate_key, candidate, record_id, sequence,
delivery_id, leased_at, departing, cost)` and a counters row.

Four properties of that inventory decide this ADR, and each is a place #980's
shape would have produced a wrong number that looked right.

**A reconsideration overwrites the ruling it replaces.** ADR-0130 §5 rules that a
reconsidered record "is updated in place with the new disposition", and
`SqliteNotificationStore._write` implements it as one `INSERT OR REPLACE INTO
notifications` on the record's own `id`. So `kind`, `reason`, `failed` and
`ruled_at` describe the **latest** ruling and no other. A candidate held behind a
quiet window, held again behind an exhausted budget, and finally interrupted is
one row reading `interrupt`, with one `ruled_at`. Counting dispositions out of
that table counts *records in their final state* and calls it "what the policy
decided", which is a different quantity that happens to have the same units. It
also undercounts spent budget: ADR-0130 §5 spends a unit at every `INTERRUPT`
including a reconsideration's, and a record can only carry one.

**The budget ledger deletes its own history.** `SqliteNotificationStore._budget`
runs `DELETE FROM notification_interruptions WHERE spent_at <= ?` at the window
floor on **every** read, and says why in its own comment: it "keeps the ledger
bounded by the window rather than by uptime". That table is a rate limiter's
working state, not a record. Any figure about the budget over a past window is
unavailable from it.

**A device's acknowledgement is written as a dismissal.**
`SqliteNotificationOutbox.acknowledge` marks the entry departing, calls
`self._dismiss(entry.record_id)` — which stamps `dismissed_at` on the
`notifications` row — and then deletes the outbox row. So after a delivery
completes, the outbox retains nothing, and the durable record is
indistinguishable from one the owner dismissed by hand. ADR-0131 §3b adds a third
producer of the same stamp: a `TOO_LARGE` or `KEY_COLLISION` refusal "dismisses
the record". `HeldNotification.dismissed_at`'s own description says "When the user
dismissed it", which on two of those three paths it does not mean. #980's "what
was dismissed vs read" is therefore not a distinction the store can draw, and the
half of it that would matter most is worse than unavailable — it is available and
wrong.

**"Seen" is not absent by oversight; it is refused.** ADR-0130 §2: "A candidate
carries no delivery state. Whether contact was attempted, reached a device, or
was seen is not a field of the candidate and not a field of its disposition, and
no clause of this ADR may be read as placing one there." `core/types.py` restates
it over the whole type block. So no instrument built on this chassis can report
whether the user welcomed anything, and §8 says so as a limit rather than
implying otherwise by silence.

### Three constraints this ADR did not choose

**ADR-0119 §5's denominator rule.** "Every measure must be a rate whose
denominator is drawn from the same stream — never from an external count of
turns, rows or runs", because the stream is lossy in principle and "a ratio of
two quantities that lost rows at the same rate survives the loss". ADR-0120 §5's
commentary sharpens it: the two parts must be observed by *one act*, so they are
lost by one act. §5 below draws its numerator and denominator from three keys one
statement writes together, for exactly that reason.

**ADR-0119 §2's content rule.** A trace carries numbers, booleans, enum members,
literals its emitting module wrote, and opaque ids. Nothing else. This is what
forecloses the per-class decomposition #980 asks for, and §8 states it as a limit
rather than reaching for an amendment.

**ADR-0120 §10's one-store rule.** "The reporting tool opens no store but the
trace store, and never resolves a record id against another one", because
"reading only the trace store is what keeps a measure a statement about events" —
a store read is "a measure of the present rather than a record of an event". That
clause was argued about `memory.db`, and the notification store turns out to be
the better example of it: `memory.db` at least keeps a superseded belief's window,
while a reconsidered notification's previous ruling is simply gone.

### What makes this a decision rather than a query somebody writes

Four things, each with a reasonable-looking wrong answer, and the second is the
one that would have cost the most.

1. **The obvious source is the notification store, and it answers a different
   question.** #980 proposes it in as many words. It is the natural instinct —
   the data is right there, no emitter is needed, and the query is short. What
   comes back is a census of records in their final state, over a population the
   retention purge is actively removing (ADR-0130 §7), with the budget's history
   deleted and a dismissal that means three things. §1 refuses it and §Context is
   the showing.
2. **The obvious carrier is `TraceKind.OPERATION`, and using it silently breaks
   ADR-0120 §3.** A notification ruling is an event at a seam, `OPERATION` is the
   kind for events at seams, and nothing in ADR-0119 obviously forbids a second
   one inside a call. But ADR-0120 §3 attributes a memory write by finding "the
   **unique** `OPERATION` trace in the retained stream carrying the same
   `TraceRef.CORRELATION` value", and `evaluation/_stream.py` implements that by
   dropping a correlation it meets twice. One reconsideration sweep rules many
   records under one correlation; one producer run offers many candidates under
   one. Emitting `OPERATION` for each would put several under one correlation, so
   the index entry would be dropped — and every `MEMORY_WRITE` sharing that
   correlation would become **unattributed** and leave ADR-0120's §4, §5 and §6
   populations entirely. A new measure would have quietly degraded three ratified
   ones, and the symptom would have been a rising `unattributed` count in a
   stream-health block nobody reads until something else is wrong. §2 is that
   hazard closed by construction.
3. **The obvious denominator is a count of candidates, and it is not in the same
   stream.** "Interruptions per candidate produced" is the phrasing a person
   reaches for. `noticed` is right there on the producer's `OPERATION` trace. But
   an offer ruled `DROP` writes no durable record (ADR-0130 §8), a producer
   without an outbox hands off nothing, and the producer's count and the store's
   rulings are observed by two acts that can lose rows independently — which is
   precisely the shape ADR-0119 §5's rule forbids. §5's denominator is the ruling
   population itself.
4. **The obvious decomposition is per notification class, and the trace may not
   carry one.** #980 asks for "tellings per class per window" and it is the figure
   an operator would most want, because a rate pooled across classes moves when a
   producer is added. A class is a producer-declared name (ADR-0130 §6), so it is
   a literal in the *producer's* module and not in the module that would emit —
   which is not one of ADR-0119 §2's four permitted string origins as read from
   the emitting seam. §8 states the limit and files the question rather than
   widening a tier rule to buy a breakdown.

## Decision

### 1. A notification measure is a rate over ruling events in the trace stream, and no notification store is opened

> **Normative.** Every measure and every diagnostic this ADR defines is computed
> from `EvaluationTrace` records alone, over an explicit half-open window of
> `occurred_at`, by the reporting tool ADR-0120 §9 places in
> `ai_assistant/evaluation/` and reaches through the console script in
> `ai_assistant/service/`.

> **Normative.** No figure defined here is derived from `notifications.db`, from
> `outbox.db`, or from any store but the trace store. ADR-0120 §10's first clause
> is obeyed rather than excepted, and this ADR opens no seventh door.

> **Normative.** The unit of population is a **ruling**, never a record. The same
> notification ruled three times contributes three events, and a record that was
> never ruled contributes none.

**The store holds the present; the question is about events, and the gap between
them is not small here.** ADR-0120 §10 states the general form — a store read is
"a measure of the present rather than a record of an event" — and §Context shows
the notification store is the sharpest instance of it in this tree. A
reconsideration is an `INSERT OR REPLACE` on the record's own id, so the ruling
it replaces is gone: not superseded, not marked, gone. A measure that reads
`kind` counts the last thing that happened to each surviving record, which is a
perfectly well-defined quantity and is not what "how often does this system
decide to interrupt?" means.

**Counting rulings rather than records is also what removes a trailing-edge bias
that the record shape would have had.** ADR-0120 §8 had to make settling a
parameter of memory precision because a surfacing near the window's end has had
less opportunity to be overturned. A record-shaped notification measure inherits
exactly that problem — a `HOLD` written on the window's last day may become an
`INTERRUPT` the day after, and the window would understate interruption in
proportion to how recently it ended. A ruling has no such future: it was made,
it is complete, and nothing later revises it. §8 is what that buys, and it is a
consequence of the unit rather than a separate fix.

**And it is the only shape that survives the retention purge.** ADR-0130 §7 has a
retention horizon of seven days from the instant a record ceased to be
actionable, and a purge job already runs it. So a window older than the horizon
has no records left to count, while ADR-0119 §10's trace horizon is explicitly
"longer than any measurement window". Reading the store would have produced a
measure that silently reported on whatever had not been swept yet.

### 2. `TraceKind` gains one member, and this ADR is ADR-0119 §13e's ratified addition

> **Normative.** `TraceKind` gains a fifth member, `NOTIFICATION`, whose value is
> `"notification"`. This ADR is the "later ADR" ADR-0119 §3 permits and the
> "own ratified ADR" §13e requires; nothing implements against it until this has
> merged.

> **Normative.** No member is added to `TraceOutcome`, `TraceRef` or
> `TraceRecordSet`, and no other type or constant is added to `core/types.py`.

**A ruling is not an `AssistantEngine` operation, and pretending otherwise breaks
a ratified measure rather than merely reading oddly.** ADR-0119 §8 fixes
`OPERATION` as "one `OPERATION` trace per call" at the engine boundary, and
ADR-0120 §3 builds on that exact cardinality: a write is attributed by finding
"the **unique** `OPERATION` trace in the retained stream carrying the same
`TraceRef.CORRELATION` value". `evaluation/_stream.py` implements the uniqueness
by discarding any correlation it meets twice. One reconsideration sweep rules
many records inside one engine call and one producer run offers many candidates
inside another, so an `OPERATION` trace per ruling would put several under one
correlation and delete that correlation from the index — taking with it the
attribution of any `MEMORY_WRITE` in the same operation, which then enters
none of ADR-0120's §4, §5 or §6 populations. The damage would be to three
existing measures, silent, and visible only as a rising `unattributed` count.

**It also stops an existing diagnostic from meaning two things.** ADR-0120 §7's
latency summary is the distribution of `elapsed` per seam over `OPERATION`
traces, and it answers "is the hub fast" about engine calls. Folding a store's
per-ruling crossing into that population mixes two units in one figure. A
distinct kind keeps `by_kind` in the stream-health counts honest for the same
reason.

**Why this is worth a member rather than avoidable.** ADR-0119 §3 collapsed the
dispatch's five seams into four kinds and gave the test: three of the five "are
the same event seen from different callers", because ADR-0083 §8 makes every
scheduler job a public `Engine` call. A notification ruling fails that test in
the one way that matters — it happens *many times within* one such call, not once
per call — which is the same reason `RETRIEVAL` and `MEMORY_WRITE` are their own
kinds. §13e's price is one ADR, and this is it.

### 3. One ruling is one trace, emitted by the store that made it, after the act commits

> **Normative.** The two seams that emit are `NotificationStore.admit` and
> `NotificationStore.reconsider` — ADR-0130 §3's atomic act, in both the shapes
> it takes. Their seam labels are `notification_admit` and
> `notification_reconsider`, literal constants in the emitting module.

> **Normative.** One crossing of either seam produces **at most one** trace, on
> ADR-0119 §5's one-crossing rule. A `reconsider` call that found nothing to rule
> emits none: no ruling was made.

> **Normative.** The emission is **outside** ADR-0130 §3's atomic act and is
> subordinate to it under ADR-0119 §5. No ruling fails, retries, is rolled back
> or changes its disposition because a trace could not be written, and no trace
> is written inside the ruling transaction.

> **Normative.** A crossing that raised an `Exception` before ruling still emits
> its trace, carrying its outcome and its fault class and **none** of the metric
> keys §4 defines. Under ADR-0119 §3's observation rule their absence says the
> ruling was not reached.

> **Normative.** A **cancellation is never classified and emits nothing.** An
> externally delivered `CancelledError` is re-raised before any outcome or fault
> class is decided, and no trace records it — ADR-0119 §3's clause, on ADR-0060
> §1, applied here rather than excepted.

**The cancellation carve-out is stated rather than inherited, because this seam
is the one most likely to meet one.** ADR-0119 §3 makes it general —
"A cancellation is never classified… so no trace records one" — and
`fault_class_of` takes an `Exception` rather than a `BaseException` precisely so
a `CancelledError` cannot reach a `fault_class` at all. The clause above would
otherwise read as an unconditional obligation over *every* raise, which is how a
lane ends up emitting a `FAULT` trace for a shutdown and putting a spurious
incomplete ruling in a window. `SqliteNotificationStore` already absorbs
cancellation at a physical boundary for the ruling transaction's sake, so the
crossing this ADR traces is exactly a place the two rules meet. Architecture
review found the contradiction on the fifth round.

> **Normative.** The trace carries `refs[TraceRef.CORRELATION]` on ADR-0119 §4's
> clause, read from the ambient value as every other emitter reads it. No measure
> defined here joins on it.

> **Normative.** This ADR is the fifth seam ADR-0119 §8's closing paragraph
> permits — "Nothing here forbids a fifth seam… What it may not do is add a
> `TraceKind`" — and §2 above is the ADR that clause requires for the part the
> permission withholds.

**The store emits rather than the writer stage, and that placement is forced
twice over.** ADR-0130 §3 requires the duplicate lookup, the cap check, the
budget read, the ruling and the write to be "one atomic act in the store", and
`orchestration/notifications.py` says in its own docstring that its job "is to
hold the policy and hand it to the store — never to sequence those steps
itself". So the facts §4 records — which conditions held — exist only inside that
transaction. A trace emitted one layer up would satisfy the letter of "we have
notification telemetry" and be blind to the reason, which is the same argument
ADR-0119 §8 made when it put `RETRIEVAL` inside `MemoryStore.search` rather than
above it. And the reconsideration path does not pass through the writer stage at
all — the engine's maintenance operation drives `NotificationStore.reconsider`
directly — so a writer-sited emitter would miss every ruling that is not a first
offer, which is most of the interesting ones.

**Subordination is stated as its own clause because the ruling is transactional
and the retrieval path is not.** ADR-0119 §5's rule is general, but the specific
failure it prevents here is concrete: a sink call inside `_ruling_transaction`
would let a trace-store fault roll back a committed disposition, spending nothing
and telling nobody, which is the exact inversion of "the instrument is
subordinate to the work it observes".

### 4. What a notification trace carries: three disposition counts, up to eight condition counts, and one duration

> **Normative.** Every metric key below is a literal constant written in the
> emitting module. Every value this ADR reads as a **count** — the three
> disposition keys and the eight condition keys — is a non-negative integer that
> is not a `bool`, on ADR-0120 §2's count rule, so one predicate serves both
> ADRs.

> **Normative.** A completed ruling carries **all three** disposition keys —
> `ruled_interrupt`, `ruled_hold`, `ruled_drop` — each `0` or `1`, written by one
> statement so they are observed and lost together.

> **Normative.** A completed ruling carries **all four** drop-condition keys,
> always: `condition_expired`, `condition_reach_off`, `condition_duplicate` and
> `condition_at_cap`.

> **Normative.** A completed ruling carries the four interrupt-condition keys —
> `condition_perishable`, `condition_reach_interrupt`, `condition_quiet_window`
> and `condition_budget` — exactly when the ruling was **not** `DROP`, and
> carries none of them when it was.

> **Normative.** Each condition key carries `1` when the proposition its
> `NotificationCondition` member names held at the ruling instant, and `0` when
> it did not. The propositions are the enumeration's own, not their negations.

> **Normative.** A trace at `notification_reconsider` whose ruling was
> `INTERRUPT` carries `held_seconds`: the ruling instant less the record's
> `admitted_at`, in seconds. No other trace carries it.

> **Normative.** `held_seconds` is **not** a count and the clause above does not
> reach it. It is a finite, non-negative `int` or `float` that is not a `bool`;
> ADR-0119 §3 already refuses `NaN` and the infinities at construction. A trace
> carrying anything else under this key is excluded from §7's latency
> distribution and from no other population, and the report counts it.

> **Normative.** No notification trace carries a `records` entry, a notification
> id, a candidate key, a producer name, a notification class, a summary, a
> detail, a confidence or an expiry instant. A trace of a ruling carries what was
> decided and on what conditions, and nothing about what the notification said.

**The key roster is the merged policy's own observation set rather than a wish
list.** `DefaultNotificationPolicy.rule` computes all four drop conditions into
one mapping before it tests them in order, so all four are genuinely observed on
every ruling that reaches the policy — including one dropped by the first. It
reaches the interrupt conditions only when no drop condition fired, and then
evaluates all four, because ADR-0130 §5 requires a `HOLD` to carry "the **whole
set** of conditions that failed at its ruling, not the first alone". The clauses
above are that behaviour written down, which is what makes "does it carry the
key" the same question as "was the quantity observed" (ADR-0119 §3).

**The propositions are taken as the enumeration states them, and two of them are
not opposites.** `NotificationCondition.EXPIRED` is "declares an expiry not later
than the ruling instant" and `PERISHABLE` is "declares an expiry later than the
ruling instant" — and a candidate declaring **no** expiry at all makes both false,
which is exactly why ADR-0130 §5 holds it rather than dropping it. A
well-formedness rule reading them as negations would classify every non-expiring
candidate as inconsistent, which is the normal case. §5 states the rule that is
actually true of them: they are never both `1`.

**`held_seconds` is what a join would otherwise have cost, and it costs
nothing.** #980 asks for "the distribution of held-to-delivered latency". The
delivered half is unavailable (§9), and the held half would otherwise need a
`TraceRef` member so a hold could be found from its later interrupt — a second
`core/types.py` addition at §13e's full price, plus an id in the stream that
ADR-0120 §10 then forbids the report to print. The store already holds
`admitted_at` on the record it is re-ruling, so the duration is in hand at the
ruling instant and travels as a number. A subtraction beats a join.

**Nothing about the candidate travels, and the last clause is written as a
prohibition rather than left to the type.** ADR-0119 §2 already forbids the free
text, and a summary is literally what the user would be shown — leg 10's
producers draw it from the owner's calendar. What §2 does *not* forbid on its own
is the class or the producer name, both of which look like enum-shaped labels
from a distance; §9 records why they may not travel and files the question.

### 5. Every trace is in exactly one of four states, tested in order

> **Normative.** Every `NOTIFICATION` trace is in exactly one of four states —
> **incomplete**, **malformed**, **counter-inconsistent** or **well-formed** —
> decided by the four tests below applied **in this order**, the first that
> applies deciding it. The states are disjoint and exhaustive by construction, so
> no trace is counted under two of them and none is left unclassified by any
> implementation.

> **Normative.** A trace is **incomplete** when it carries **none of the metric
> keys §4 defines** — none of the three disposition keys, none of the eight
> condition keys and no `held_seconds`. It records a crossing that raised before
> ruling (§3), it enters no population, and the report counts it apart from the
> two faults below because it is not one.

> **Normative.** A trace is **malformed** when any of the following holds: it
> does not carry all three disposition keys; a key §4 reads as a count carries a
> value that is not a non-negative integer, or is a `bool`; the three disposition
> values do not sum to exactly `1`; a condition key carries a value other than
> `0` or `1`; a drop-condition key is absent; the ruling is not `DROP` and an
> interrupt-condition key is absent; or the ruling is `DROP` and an
> interrupt-condition key is present. A malformed trace enters no population.

> **Normative.** A trace is **counter-inconsistent** when its keys are all present
> with admissible values and disagree with one another: `condition_expired` and
> `condition_perishable` are both `1`; or `ruled_interrupt` is `1` while any
> interrupt-condition key is `0`; or `ruled_drop` is `1` while every
> drop-condition key is `0`; or `ruled_hold` is `1` while every
> interrupt-condition key is `1`; or the ruling is **not** `DROP` while any
> drop-condition key is `1`.

> **Normative.** A trace in none of those three states is **well-formed**.

> **Normative.** Over a window `W`, the **ruling population** is every
> **well-formed or counter-inconsistent** trace whose `occurred_at` lies in `W`.
> Membership is decided by which keys a trace carries and never by its
> `TraceOutcome`, on ADR-0120 §2's rule. Its **offer** and **reconsideration**
> sub-populations are those of its members whose seam is `notification_admit` and
> `notification_reconsider` respectively.

> **Normative.** A trace whose seam is neither of those two is **unclassified**:
> it stays in the ruling population, enters neither sub-population, and the
> report names each unclassified seam it met.

> **Normative.** §6's duplicate share and §7's condition incidence are computed
> over the **well-formed** members of their populations alone. Every other figure
> §6 and §7 define reads the ruling population whole.

> **Normative.** The report states, separately from one another, how many
> `NOTIFICATION` traces it met as incomplete, as malformed, as
> counter-inconsistent and as unclassified.

**The last counter-inconsistency clause is ADR-0130 §5's ordering read as an
invariant, and it is the one a reader is most likely to leave out.** That section
evaluates the four drop conditions **first**, "each yielding `DROP` naming
itself", so a satisfied drop condition and a ruling of `INTERRUPT` cannot both
have happened — a duplicate that interrupted is not a policy this tree can run.
Without the clause such a trace passes every other test, enters the ruling
population as well-formed, and counts a refusal as an interruption, moving the
one measure §6 exists for. Adversarial review found it on the second round.

**Ordered and disjoint, because two overlapping predicates are two
implementations that disagree.** A trace carrying `ruled_interrupt = 2` satisfies
"carries all three disposition keys" and also fails the sum rule; a condition key
of `-1` is both a bad count and a bad condition value. Stated as independent
predicates, each such trace is admissible under one clause and excluded under
another, and the report's own exclusion counts double. This is the property §1 of
ADR-0120 calls the whole point of the clauses being fussy — "two implementations
must produce the same number" — and an order is the cheapest thing that supplies
it. Adversarial review found both overlaps on the first round.

**Malformed and counter-inconsistent divide by how far the damage reaches, which
is ADR-0120 §7's line and is drawn here for its reason.** A disposition set that
does not sum to one cannot say what was ruled, and a missing condition key means
a population's denominator would silently shrink — neither trace can be trusted
for anything, so both leave every population. Conditions that are all present and
admissible but disagree with the disposition are a localised fault: they are
written by a different statement from the disposition keys, so the trace can
still say truthfully that an interruption happened while being untrustworthy
about why. Excluding it from the interruption share as well would discard a real
ruling for a reason the share does not depend on.

**A missing key is malformed rather than merely uncounted, and that is the
second overlap closed.** §4 requires all four drop-condition keys on every
completed ruling and all four interrupt-condition keys on every non-`DROP` one.
A `HOLD` arriving without `condition_budget` breaches that, and under a rule that
only checked consistency *where the keys were present* it would have entered the
condition incidence, shrinking that one condition's denominator while appearing
in no exclusion count at all — the invisible failure ADR-0120 §2 names when it
says a measure that "silently divided by a partial sum would be wrong in a way
nobody could see". No emitter in this tree can produce one; counting it is cheap
and makes the assumption checkable.

**Incomplete is named rather than folded into malformed, because it is the
ordinary fault path.** ADR-0119 §8 requires a crossing that raised before ruling
to emit its trace anyway, and §3 above requires it to carry none of §4's keys. So
a trace carrying none of them is the design working, not a defect, and counting
it beside two genuine faults would make an outage look like an emitter bug.

**Incomplete is defined over §4's whole key set, and malformed's first disjunct
widened to catch what that released.** Defined over the disposition keys alone,
the state matched more than the path it names: a trace carrying
`condition_budget = 2` and no disposition would satisfy the first test, be
decided there, and never reach the checks that would have called it malformed —
so emitter corruption would be reported as an ordinary pre-ruling fault and
stream health could not tell an outage from a defect. Narrowing it to §3's own
words — **none** of the keys §4 defines — makes the two sections one predicate:
a trace bearing any of those keys reached the ruling, so it is a fault of the
emitter and belongs to the tests below. That narrowing alone would have left a
hole, because a trace carrying valid drop conditions and no disposition at all
passed every remaining test and entered the ruling population as well-formed;
so the first malformed disjunct now reads "does not carry all three disposition
keys" rather than "a strict, non-empty subset". Incomplete is tested first and
requires an empty key set, so the widened disjunct reaches exactly the traces
incomplete released and the four states stay disjoint and exhaustive. No measure
defined here moves under either edit — both states leave every population — and
what is bought is the legibility of the exclusion counts, which is what this
section's clauses exist for. Adversarial review found it on the seventh round.

**Two seam labels rather than a denylist, on ADR-0120 §3's discipline.** A later
lane may add a third ruling seam, and defaulting an unrecognised one into the
offer or the reconsideration population would silently absorb it into a
diagnostic. The count that rises is the prompt to classify it. It stays in the
ruling population because the disposition keys mean what they say whatever seam
wrote them, which is the difference between this and ADR-0120 §3's unattributed
writes.

### 6. Two measures: the interruption share and the duplicate share

> **Normative.** Each measure below is a ratio of two counts drawn from the same
> traces, over an explicit half-open window `W = [a, b)` of `occurred_at`.

> **Normative.** Every ratio this ADR defines, measure or diagnostic alike, is
> **undefined** when its denominator is zero, and the report states that it is
> undefined rather than stating a figure or a zero. This is ADR-0120 §1's rule
> restated for these rates, not extended to ADR-0120's.

> **Normative.** No measure or diagnostic defined here carries a threshold, a
> target, a pass/fail verdict or a trend claim.

> **Normative.** The **interruption share** over `W` is the sum of
> `ruled_interrupt`, divided by the sum of `ruled_interrupt`, `ruled_hold` and
> `ruled_drop`, over §5's ruling population.

> **Normative.** The **duplicate share** over `W` is computed over the
> **well-formed** members of §5's offer population: the count of them carrying
> `condition_duplicate` as `1`, divided by the count of them. Every well-formed
> trace carries the key by §5's malformed rule, so the numerator and the
> denominator are observed by one statement and lost by one.

> **Normative.** The report states each measure's denominator beside it.

**The interruption share is the figure "proactivity must earn its place" turns
into.** ADR-0130's whole ruling is that only a perishable candidate escalates and
everything else is held, and the share is what that policy did in practice over a
window. Read across two windows it answers the question #980 exists for: after
the owner tunes a class up, or a producer is added, or a default moves, did the
system start interrupting more or less, and by how much. It is deliberately not
"how many interruptions" — a count moves with how many candidates were produced,
which is a fact about producers, and ADR-0119 §5's rule forbids the external
denominator that would fix it.

**Its denominator is the three keys and not a candidate count.** `noticed` on the
producer's `OPERATION` trace is the tempting alternative and it is observed by a
different act at a different seam, so the two lose rows independently — the shape
ADR-0119 §5 refuses. The three disposition keys are written by one statement, so
they are lost by one statement, and their sum is the population every ruling
belongs to exactly once.

**The duplicate share measures the thing leg 10 deliberately made safe and never
sized.** ADR-0130 §8 rules that "a producer that re-notices the same fact on every
tick is behaving as designed", and #978 watched that happen — 25 ticks at 15
seconds with the held count constant at 1. So the raw proposal volume is not a
count of things noticed; it is a count of noticings, and the share of them that
were duplicates is what tells an operator which. It is a measure rather than a
diagnostic because it is a rate an operator can rule on: a share that climbs
toward 1 as the corpus grows is a producer whose window is re-reading more than
it discovers.

**It is defined over offers only, and the reason is in ADR-0130 §5.** "A
reconsideration is not a new offer… and §8's duplicate rule does not read the
record being reconsidered as a duplicate of itself", so `condition_duplicate` is
structurally `0` on every reconsideration and pooling the two would divide a real
numerator by an inflated denominator. Counter-inconsistent traces leave this
population because the share reads a condition key, which is exactly what a
counter-inconsistent trace is untrustworthy about.

### 7. Five diagnostics travel with the measures and none of them is one

> **Normative.** No diagnostic below is a measure of this ADR, none carries a
> threshold verdict, and none may be substituted for a measure.

> **Normative.** The **disposition mix** over `W` is the three sums §6's
> denominator is made of, stated as counts.

> **Normative.** The **condition incidence** over `W` is, for each of the eight
> condition keys, the count of **well-formed** traces in the ruling population
> carrying it, the count carrying it as `1`, and their ratio.

> **Normative.** The report states each condition's own carrying count beside its
> ratio, and never divides one condition's numerator by another's population. The
> four interrupt-condition keys are absent from every `DROP`, so their
> denominators are the non-`DROP` rulings and not the ruling population.

> **Normative.** The **held-to-interruption latency** over `W` is the
> distribution of `held_seconds` over the members of §5's **reconsideration**
> sub-population whose `ruled_interrupt` is `1` and which carry `held_seconds` as
> a value §4 admits — the placement §4 requires, and no other. It is a
> distribution and not a ratio, so the undefined rule does not reach it; over an
> empty sample the report says the sample is empty.

> **Normative.** A trace carrying `held_seconds` where §4 forbids it, or carrying
> an inadmissible value or none where §4 requires it, is **misplaced** for this
> diagnostic. A misplaced value is never read as a latency, its trace stays in
> every other population, and the report counts it.

> **Normative.** The **held-first share** over `W` is the sum of
> `ruled_interrupt` over the reconsideration population, divided by the sum of
> `ruled_interrupt` over the ruling population.

> **Normative.** The **notification stream-health counts** over `W` are the
> `NOTIFICATION` traces walked, §5's four state counts, the count met as
> unclassified with each such seam named, the count of misplaced `held_seconds`,
> and the count carrying an outcome other than `OK`.

**The condition incidence is what makes a share of zero readable, and without it
the measure is a trap.** ADR-0130 §6 ships every class at reach `hold`, so a hub
nobody has tuned interrupts nothing and the interruption share is exactly `0`
forever. That is not "proactivity is not earning its place"; it is "nobody has
granted it a place", and the two demand opposite responses. The incidence
separates them in one line: `condition_reach_interrupt` at `0` on every ruling
says the reach level is the binding constraint, `condition_budget` at `0` says the
budget is, and `condition_quiet_window` at `0` says the timing is.

**The held-first share is the cheapest reading of whether holding is working.**
ADR-0130 §5's design is that a held candidate whose blocking condition later
clears is reconsidered and may then interrupt. Whether that path ever fires is a
yes/no an operator cannot get from the interruption share, and it costs no key —
the seam label already separates the two populations.

**The latency distribution is a diagnostic for ADR-0120 §7's reason.** It answers
"how long does the chassis sit on something before it lets it through" rather
than any question about whether proactivity is earning its place, and it is not a
rate, so ADR-0119 §5's denominator rule has nothing to bind.

### 8. The window is ADR-0120's, and no settling period applies to any figure here

> **Normative.** ADR-0120 §8's window rules govern this report unchanged: the
> partition at every `CONFIGURATION` trace whose metric mapping differs from its
> predecessor's, the refusal of a window starting before the oldest retained
> trace, and the empty-stream statement that precedes every other clause.

> **Normative.** No measure or diagnostic defined here takes a settling period,
> and no figure defined here is withheld — for want of one, or because the
> retained stream does not extend past the window's end. The window is the one
> the operator asked for, whatever its end, and ADR-0120 §8's clause withholding
> a memory-precision figure reaches no figure of this ADR.

> **Normative.** Every figure defined here is stated for each part of a
> partitioned window as well as for the window entire, on ADR-0120 §8's clause.

**No settling, because nothing here looks forward from its event.** ADR-0120 §8
makes settling a parameter of memory precision because a surfacing's numerator
lies in its future and a window's trailing edge has had less of one. A ruling's
numerator is the ruling itself: the disposition keys are written by the same act
the trace records, so a ruling made one second before the window closed
contributes exactly what a ruling made on the first day does. Bolting a settling
period on anyway would withhold figures for no reason and would suggest a bias
that is not there.

**The partition still matters, and more here than for the memory measures.**
`service/configuration.py`'s allowlist is what ADR-0120 §8 partitions on, and the
notification chassis's `Settings` figures — the store's cap, its retention and the
reconsideration interval (ADR-0130 §9) — change what these rates mean when they
move. The standing settings of ADR-0130 §6 are **not** in `Settings` and emit no
`CONFIGURATION` trace, so a reach level raised or a budget widened does not
partition a window. That is a real discontinuity in the series and §9 states it
as a limit rather than proposing a marker for it, on ADR-0121 §7's precedent:
"partitioning on arbitrary code changes is not something the trace stream can
see, and inventing a marker for it is a bigger decision than this one".

### 9. What this instrument cannot see, stated as limits

> **Normative.** Nothing in this ADR is to be read as a measure of whether the
> user welcomed being told anything. Each figure is a rate over rulings the
> system made, and is bounded by what a ruling can distinguish.

> **Normative.** The report states, beside the measures, that no figure it
> carries is evidence about whether contact was welcome.

Each limit below is a real question a reader of the numbers will ask, and each is
named rather than approximated.

- **Whether anything was welcome.** ADR-0130 §2 refuses delivery state on a
  candidate or a disposition — "whether contact was attempted, reached a device,
  or **was seen**" — and this ADR keeps that refusal rather than reversing it.
  So the experiential half of leg 10's exit is not what this instrument reports.
  What it supplies is the other side of that conversation: what the system
  proposed, what it let through, and what stopped the rest.
- **Whether a notification was delivered, or read.** Nothing records either.
  `outbox.db` retains nothing after an acknowledgement, and there is no
  `delivered_at` or `read_at` anywhere in the tree.
- **Whether a dismissal was the owner's.** `dismissed_at` has three producers —
  the owner's act, a device's acknowledgement, and ADR-0131 §3b's terminal
  refusal — so no dismissal rate is offered here at all. Filed rather than
  approximated.
- **Any decomposition by notification class or by producer.** Both are
  producer-declared names (ADR-0130 §6, ADR-0093 §7), so from the emitting seam
  neither is one of ADR-0119 §2's four permitted string origins, and a metric key
  named after one would be a key derived from data. So every figure here is
  pooled across classes, and a rate that moves when a producer is added has moved
  for that reason. Filed.
- **A standing-setting change inside a window.** §8's partition sees
  `CONFIGURATION` traces, and ADR-0130 §6 keeps the reach levels, quiet windows
  and budget out of `Settings` deliberately. A window spanning a tuning act is
  not internally comparable, and the report cannot say so.
- **The budget's occupancy over a past window.** The ledger deletes its own
  history (§Context). `ruled_interrupt` is a faithful count of units spent,
  because ADR-0130 §5 spends one exactly when an `INTERRUPT` is recorded — but
  how close the budget came to exhausting at any past instant is not recoverable,
  and `condition_budget` reports only whether it was exhausted at each ruling.
- **Coverage.** ADR-0130's Consequences already say it: "nothing here makes
  noticing complete", and a fact a producer's window never covers is never
  proposed. Every figure here is conditioned on a candidate having been produced.
- **The stream's own completeness.** A trace lost to an emission failure is
  logged and not counted (ADR-0119 §5). ADR-0119 §5's denominator rule is what
  keeps these rates usable despite it, and is why no figure here is an absolute.

### 10. The contract surface, and what the implementing lane owes

> **Normative.** The implementing lane adds to `core/types.py` exactly one thing:
> `TraceKind.NOTIFICATION`. It corrects that enumeration's docstring, which says
> "Exactly four members", in the same change.

> **Normative.** No Protocol in `core/protocols.py` gains a member or changes a
> signature. `NotificationStore`, `NotificationPolicy`, `NotificationWriter`,
> `NotificationOutbox`, `TraceSink` and `TraceStore` are untouched.

> **Normative.** The concrete `SqliteNotificationStore` takes a **`TraceSink` as
> a required keyword constructor argument with no default**, in the shape
> `SqliteMemoryStore` already takes `traces_sink`, on ADR-0119 §7's clause that
> "a composition that omits it does not type-check". `app/composition.py` wires
> it.

> **Normative.** Emission is **not** an obligation of the `NotificationStore`
> contract. ADR-0130 §9's shared conformance suite gains no case, and no
> canonical fake is required to emit — the same arrangement `MemoryStore` and
> `SqliteMemoryStore` already have for `RETRIEVAL`. The SQLite store's own tests
> pin the emission, its key roster and its subordination.

> **Normative.** The measure definitions, the diagnostics and the restated metric
> literals live in `ai_assistant/evaluation/`, and the report reaches an operator
> through the existing `ai-assistant-measures` console script. ADR-0120 §9's
> placement, its instance-lock discipline and its refusal of an `AssistantEngine`
> method, a wire operation and an `assistant` subcommand are reused whole and
> none is narrowed.

> **Normative.** No `Settings` field is added. The report takes no new argument:
> the window it already takes is this report's window, and §8 rules that the
> settling argument bounds ADR-0120 §4 alone.

> **Normative.** The lane's restated literals are pinned against the emitter's
> own constants, in the shape `tests/evaluation/test_measures_vocabulary.py`
> already takes — `evaluation` may import only `core`, so the emitter's keys are
> duplicated by construction and the test is what keeps the two copies honest.

**The lane is one subsystem plus its tests, twice, and that is admissible rather
than a widening.** The emitter is `memory`, the reader is `evaluation`, and
`CLAUDE.md`'s one-subsystem rule bites. ADR-0119's own emitter lanes are the
precedent: a trace's producer and its consumer are two changes, and a measure
whose emitter does not exist yet is a measure over nothing. The honest sequencing
is the emitter first — it is inert until something walks the stream — and the
measure second, and nothing here requires them to be one change.

### 11. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1 puts the judgement in this ADR's text, and the test is ADR-0070 §1's:
*would a reader holding only the earlier ADR now act differently, or read one of
its clauses more widely than it now holds?* Applied at each place a record looks
owed. **None is owed.**

**ADR-0119 §3's four-member clause — not owed, and this is the closest of the
set.** Its words are: "`TraceKind` has exactly four members **at this decision**:
`OPERATION`, `RETRIEVAL`, `MEMORY_WRITE` and `CONFIGURATION`. **A later ADR may
add one**; nothing else may". The clause is self-dating and self-permitting: it
states a fact about its own moment and names the instrument by which the fact
changes. A reader holding only ADR-0119 already expects a fifth member to arrive
by a ratified ADR, and after this one they still do. Discharging a permission by
the route the permission itself named is "the mechanism working" (ADR-0102 §13,
quoting ADR-0100 §11), which is the same disposition ADR-0120 §13 took for
ADR-0119 §15's deferrals. What §13e prices is the *ADR*, and it is paid here; it
does not additionally demand a `Status` edit, and nothing in ADR-0082 §1 makes an
anticipated addition an amendment.

**ADR-0119 §8 — not owed.** Its closing paragraph grants the fifth seam in as
many words and withholds exactly one thing: "What it may not do is add a
`TraceKind`". §2 above is the ADR that supplies the withheld half, and §3 obeys
the three conditions the grant attaches — §2's tier clauses, §5's subordination
and one-crossing clauses, and §4's correlation clause. A reader holding only
ADR-0119 permits a fifth seam under those conditions, before and after.

**ADR-0119 §2, §5 and §7 — not owed.** §2's content rule is obeyed and §9 states
what obeying it costs. §5's denominator rule is obeyed and §6 shows where it
bites. §7's third clause names eight pipeline packages and forbids them the walk;
this ADR adds an *emitter* to `memory`, which §7's second clause already requires
of every emitting site, and puts the walk nowhere new — the reader stays in
`evaluation`, which is not among the eight and which `pyproject.toml`'s import
contract forbids all eight from importing.

**ADR-0120 §9 and §10 — not owed, and §10 gets stronger rather than wider.** §9's
placement is reused unchanged; §10's "opens no store but the trace store" is the
clause §1 above enforces against #980's proposal, and §10's "no record id" is what
§4's last clause implements. Neither sentence becomes wider; one of them acquires
a second case it already covered.

**ADR-0120 §1 and §7 — not owed.** §1's clauses bind "every measure defined by
**this ADR**", and §6 above restates them for its own measures rather than
extending §1's scope. §7's first clause says the report carries three diagnostics
beside ADR-0120's measures, which is a statement of what that report owes and not
a ceiling on what a later ratified measure may add beside its own; §7's second
clause — no diagnostic is a measure, none carries a threshold verdict — is
restated in §7 above rather than narrowed. A reader holding only ADR-0120 still
requires those three and still refuses to substitute one for a measure.

**ADR-0120 §3 — not owed.** Its attribution is a rule about `MEMORY_WRITE` traces
and their `OPERATION` traces. No measure here is attributed, and §2's whole
argument is for *preserving* §3's uniqueness premise rather than relying on it.

**ADR-0121 §7 and §8 — not owed.** Nothing here touches the three measures, their
metric keys, or the populations they are computed over.

**ADR-0130 §2 — not owed, and its refusal is the reason §9 exists.** No trace
here carries delivery state, and §9 states the cost of that rather than routing
around it. ADR-0130 §3's atomicity is unchanged and §3 above sits outside it.
ADR-0130 §5's, §6's, §7's and §8's rulings are read as facts about what happens,
never modified: §4's key roster is the policy's own observation set and §6's
duplicate share exists because §8 made re-noticing safe.

**ADR-0131 §3b — not owed.** Its dismissal-on-terminal-refusal clause is quoted
in §Context and §9 as a fact that limits this instrument. Nothing here changes
what a refusal does, and no figure defined here reads `dismissed_at` at all.

**ADR-0083 ruling 4 and §10 — not owed**, on ADR-0119 §14's and ADR-0120 §13's
application of ADR-0102 §13. The report is the offline tool ADR-0083 §10 names,
taking the instance lock ADR-0120 §9 already requires, opening one store fewer
than an alternative would have.

**ADR-0004 §2's telemetry clause — not owed.** The report is a local rendering of
local Tier 2 data and transmits nothing; ADR-0120 §10's ruling covers it and this
ADR adds no egress seam and no opt-in.

**Addition, in ADR-0102 §13's form.** A reviewer who reads any of these the other
way is invited to name the sentence of the earlier ADR that becomes false or
over-wide, which is the showing ADR-0082 §1 requires of a demand for a record.

### 12. What this ADR does not decide

- **The numbers.** No target, no threshold and no expected value is set for any
  figure here. Whether an interruption share is good is the operator's ruling.
- **Whether these figures join the arc-3 gate.** `docs/roadmap.md`'s gate between
  legs 10 and 11 is stated over leg 8's measures, and #881 holds its unruled
  undefined arm. Nothing here adds a figure to that gate or answers #881; §6's
  undefined rule is ADR-0120 §1's, applied to new rates.
- **The experiential half of leg 10's exit**, which stays where #879 put it: the
  owner's judgement once daily use resumes. §9 is explicit that this instrument
  does not supply it.
- **Feedback-based adaptation of the tuning surface**, which ADR-0130 §10 already
  declines and whose precondition is that same daily use. A measure is not a
  feedback loop, and ADR-0119 §7's rule that nothing the system does is
  conditioned on a trace forecloses making one out of these figures.
- **A per-class or per-producer breakdown**, and how a producer-declared label
  could ever reach a trace under ADR-0119 §2. §9 files it.
- **A delivery-side or read-side signal**, which would reopen ADR-0130 §2 and is
  a decision of its own.
- **A latency diagnostic over the ruling seams' `elapsed`.** The field is carried
  because ADR-0119 §3 carries it on every trace; no figure here reads it, and
  extending ADR-0120 §7's per-seam summary across kinds is not proposed.
- **The report's output format** beyond §6's and §9's content rules, on ADR-0120
  §14's disposition: nothing depends on it.
- **When the measurement window opens.** #879's return and #829's window are the
  operator's; this ADR supplies the definitions a window is read with.

## Consequences

**Leg 11's QA run has something to compare against, and leg 10's does not.** That
asymmetry is the honest statement of what this buys. The instrument records
rulings from the moment its emitter ships, so the baseline starts then — not
retroactively, because the events it counts were never written down. Every ruling
made before that lane merges is unrecoverable, which is the concrete price of
leg 10 having shipped no instrument and the reason #980 was worth filing rather
than noticing later.

**A notification measure is cheap to add now and was expensive to add correctly.**
The four properties §Context establishes each took a read of the merged tree, and
three of them contradict the shape #980 proposed in good faith. That is ADR-0120's
own stated friction — "a fifth measure gets the same treatment, and the odds are
good that it too finds a field that is not emitted" — arriving exactly as
predicted, one leg later.

**The trace stream gains a fifth kind, and every consumer that switches on the
enumeration acquires a case.** ADR-0119 §13e priced this and named the cost:
"every consumer switching on the vocabulary silently acquires an unhandled case".
In this tree the consumers are `evaluation`'s walk and its stream-health counts,
both of which the implementing lane touches anyway. The cost lands on a later
lane that adds a sixth kind and finds the same argument waiting.

**The chassis's stores stay unreadable from outside the hub, and that was not
free.** Reading `notifications.db` offline would have needed no emitter, no enum
member and no ADR, and it would have produced numbers within a week. What it
would not have produced is numbers that mean what their names say. Paying an
emitter and a contract member to keep ADR-0120 §10 intact is the same trade
ADR-0120 §9 made when it paid a hub restart to keep a read path closed.

**An untuned hub now reads as untuned rather than as unproactive.** §7's
condition incidence is what makes the shipped defaults legible: with every class
at `hold`, the interruption share is zero and `condition_reach_interrupt` is zero
on every ruling, and the two together say "nobody granted it a place" rather than
"it did not earn one". Without the diagnostic the measure alone would have
supported the wrong reading for as long as the defaults stood.

**What becomes harder: adding a producer without moving the numbers.** Every rate
here is pooled across notification classes (§9), so a new producer changes the
denominator of both measures and the incidence of every condition. A window
spanning a producer's arrival is not internally comparable, and unlike a
`Settings` change it does not partition. Whoever adds the second producer inherits
that, and the honest remedy is the per-class decomposition §9 files rather than a
rule nobody can enforce.

## Alternatives considered

**A measure over `notifications.db` and `outbox.db`, as #980 proposes.** Refused;
§1 and §Context. It is the cheapest option by a wide margin and it answers a
different question: a census of surviving records in their final state, with the
budget's history deleted, a dismissal that means three things, and a retention
purge quietly bounding the population. It also breaches ADR-0120 §10's one-store
rule, which would have had to be superseded rather than obeyed.

**`TraceKind.OPERATION` as the carrier for a ruling trace.** Refused; §2. It
avoids the contract member entirely and it breaks ADR-0120 §3's uniqueness
premise, taking the attribution of every co-correlated `MEMORY_WRITE` with it —
damage to three ratified measures, visible only as a rising `unattributed` count.

**A `TraceRef` member so a hold could be joined to its later interrupt.**
Refused; §4. It buys the held-to-interruption latency at the price of a second
`core/types.py` member under §13e and an id in the stream that ADR-0120 §10 then
forbids the report to print. `held_seconds` is the same figure computed by
subtraction at the one moment both instants are in hand.

**A `TraceRecordSet` member carrying the notification's id.** Refused for the
same reason and one more: no measure defined here needs identity across traces,
and ADR-0119 §3's cap and truncation machinery would be carried for a set that is
always of size one.

**Carrying the notification class as the seam label.** Refused; §9. A class is a
literal in its *producer's* module, not in the module that emits, so admitting it
would widen ADR-0119 §2's third string category for every emitter in the tree in
order to buy one breakdown. The narrower question — how a producer-declared label
could reach a trace at all — is filed as its own decision.

**A per-class metric key, one per class met.** Refused. The key would be derived
from data, which ADR-0119 §2's second clause forbids outright, and §3's lowercase
key pattern would accept most class names, so the breach would be silent.

**Emitting from `orchestration/notifications.py` rather than from the store.**
Refused; §3. The failed-condition set, the budget read and the duplicate lookup
exist only inside ADR-0130 §3's atomic act, so a trace one layer up would be
blind to every reason; and the reconsideration path never passes through that
stage at all, so it would miss most rulings.

**Emitting inside the ruling transaction, so a trace and a ruling commit
together.** Refused; §3. It is the shape that makes the record and the trace
provably agree, and it inverts ADR-0119 §5: a trace-store fault would roll back a
committed disposition. The instrument is subordinate to the work, and a stream
that is occasionally incomplete is the accepted cost ADR-0119 §5 already priced.

**A dismissal rate, or a "read" rate.** Refused; §9. `dismissed_at` has three
producers and "seen" is refused by ADR-0130 §2. Reporting either would put a
figure in front of an operator whose name promises a user's judgement and whose
value is mostly a client's acknowledgement.

**One measure instead of two.** Considered and refused. The interruption share
alone cannot distinguish a producer that discovered one fact from one that
re-noticed the same fact two hundred times, and #978 shows that difference is the
normal case rather than an edge one.

**A settling period, for symmetry with ADR-0120 §4.** Refused; §8. Nothing here
looks forward from its event, so a settling period would withhold figures for no
reason and imply a bias that does not exist.

**Deferring the whole decision until daily use resumes.** Refused. An instrument
has to exist before the window it measures; a baseline started after it is needed
is not a baseline, and #980 exists because leg 10 discovered exactly that.
