# 132. The upcoming-event producer notices a start instant and concludes nothing about it

- Status: Proposed
- Date: 2026-08-11
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `9714787c`, not to its status on any later day. Every
  ADR this decision composes with reads `Accepted` there, ADR-0133 among them —
  that commit is its ratification, on its second flip. Where a later ADR
  *changes* one of them, this ADR is read against the text quoted here and that
  ADR's own record says what moved. The `Date` line is this ADR's authoring date
  in this clone's frame, the convention ADR-0112, ADR-0113, ADR-0129 and ADR-0131
  state for their own; the base named here is the anchor that does not move under
  either frame.

## Context

### ADR-0130 reserved exactly this decision, and named nobody to make it

ADR-0130 decides the chassis and closes with a list of what it does not decide.
The fourth item is this ADR's whole subject:

> **Which producers exist, and what any of them notices.** Each producer is its
> own lane and its own scheduler job under ADR-0083 §7, and what a producer may
> conclude is its own decision's, on ADR-0111 §11's split between binding the
> walk and binding the verdict.

So the chassis is complete and empty. `NotificationCandidate`, the policy, the
three standing settings, the cap, the retention and the reconsideration job are
all ratified; nothing offers a candidate. This ADR decides the first producer,
and one producer only.

### Why a calendar event, and not something cheaper

ADR-0130 §5 makes perishability the entire escalation test — "something that
keeps is not an interruption, it is a message" — and it ruled that way because
expiry is the one criterion of VISION §5's six that is falsifiable. A producer
whose candidates declare no expiry can never be ruled `INTERRUPT` at all: §5's
conjunctive clause names the expiry condition first, and a candidate declaring
none is held naming exactly that.

The calendar is the only source in the tree whose records carry a natural expiry.
It is also the only *live* one: leg 9's verification lane (#886) put a real
`vdirsyncer` behind leg 6's `Reader`, and leg 9's QA (#918, #919) established
that driving a surface through a stand-in is a reach gap rather than evidence.
Leg 10's exit test — the assistant tells the user something they did not ask for
— is not met by a producer that notices a fixture.

### What the tree actually offers a producer over the calendar

Three surfaces exist and only one of them can carry a candidate. This was checked
against the code rather than assumed, because the obvious answer is wrong.

**The facet cannot.** `CalendarFacet` carries three scalars and no entry text at
all — `entries_in_progress`, `next_starts_at`, `covers_until` — and its own
docstring records that this is a decision twice over: the beliefs already carry
the occurrences, and "a calendar's titles and locations are the most disclosing
thing it holds". It carries no identifier and no summary, and `next_starts_at` is
one instant rather than a set. A candidate built from it could say only "something
starts at 14:05", about nothing, keyed on nothing.

**Memory cannot be selected.** The same read's proposals land as `ATTESTED`
beliefs whose `Attestation.extent` is the occurrence's own span
(`ReportedExtent`), which is exactly the structured start instant a producer
wants. But no ratified read reaches them by it. `MemoryStore.list_beliefs` filters
on band and kind and orders by `provenance.last_updated` descending; `search` is a
relevance read that needs a query and an `Embedder`; `walk_records` is ADR-0111's
cursor walk over a total order. Selecting "occurrences starting in the next half
hour" from any of them is either a new `MemoryStore` read surface — a
`core/protocols.py` change owing its own ADR under golden rule 5 — or a
client-side filter over a page whose order is only incidentally the one that
would make it work.

**The reading can.** `SourceReading.proposals` is per-occurrence and structured:
each `MemoryUpdateProposal` carries the occurrence's rendered one-line text as the
belief's content and its span as `Attestation.extent`. That is a start instant, an
end instant and a sentence a person can read, per entry, from one bounded read.

### Which *use* of the source this is was settled by ADR-0133, ahead of this ADR

ADR-0097 §2 fixed `GrantScope` at two members and ruled that "a use a grant does
not name is not authorised by it". Under that section's own axis — "The axis is
not invented; it is ADR-0093 §3's", one scope per consumer of a reading — a
producer reading the calendar to notice something worth telling the user is a
**third** consumer. It contributes no `ContextFacet` at assembly time and proposes
no belief into memory; it concludes a candidate which, ruled `HOLD` or
`INTERRUPT`, becomes a durable record ADR-0130 §7 makes enumerable and §9 makes
exportable — about something the user did not ask for.

Both ways of authorising that would have changed ratified ground, so this ADR did
not settle it and **ADR-0133 does**: `GrantScope` gains `NOTIFY`, "reading the
source so that a producer may conclude a `NotificationCandidate` about what it
read", with the partial-supersession record against ADR-0097 §2 carried there.
Three of its rulings shape this ADR rather than merely permitting it — §1's limit
of the member to the *read*, §2's independence of the three members, and §6's
clause placing the enforcement site with the producer that needs it, which is this
one.

**So the authority is settled elsewhere and this ADR decides what is done with
it**: what the producer walks, on what schedule, within what window, and what it
may and may not conclude.

## Decision

### 1. One job, one bounded read, one candidate per upcoming occurrence

> **Normative.** The upcoming-event producer is a stage in `orchestration` driven
> by a public operation on the concrete engine, which is in turn driven by a job
> on ADR-0083 §7's scheduler whose body is that bound method and which holds no
> store, no reader and no subsystem import.

This is `Engine.ingest`'s shape reused rather than a new one: ADR-0083 §8 puts a
maintenance surface "on a class in `orchestration`, not `core` contract surface",
ADR-0093 §6 already added one row to §7's table on that shape, and ADR-0130 §5
added a second for reconsideration. This is a third row and adds no mechanism.

> **Normative.** The producer's operation takes no argument. The reader is given
> its own source and its own bound, so the producer cannot widen the read, and the
> operation is a legal job body.

`Engine.ingest`'s reason, unchanged: "a caller able to widen the read is a caller
able to defeat the bound."

> **Normative.** The producer holds a `Reader`, a `SourceGrants`, a clock and the
> `NotificationWriter` seam of ADR-0130 §3. It holds no `MemoryStore`, no
> `MemoryWriter` and no `MemoryPolicy`, and it proposes no belief.

It is not a second ingestion path. Whether a calendar entry becomes a belief is
ADR-0093's decision and the ingestion job's; whether it becomes a candidate is
this one's, and the two are independent both ways — a deployment may run either,
both or neither.

> **Normative.** The producer offers each candidate through ADR-0130 §3's single
> seam and takes no other action. It selects no disposition, delivers nothing,
> ranks nothing, and offers every occurrence its walk selects rather than a chosen
> subset of them.

The last clause is worth stating because the temptation is real: a producer
holding five upcoming events and a budget of three will want to pick. Picking is
the numeric priority ADR-0130 §11 declined — "Weighed by a producer, a score is
self-granted authority" — and the aggregate is already bounded twice, by §6's
budget and §7's cap, in a place the user can tune and the producer cannot.

### 2. The authorising grant is `NOTIFY`, and this producer carries its gate

> **Normative.** The producer reads the calendar only where a live grant naming
> `GrantScope.NOTIFY` covers that reader's identity at the instant the read
> starts. Where none does, nothing is opened: the source is not resolved, not
> opened and not parsed.

ADR-0133 §1 mints the member and §2 rules the refusal, in ADR-0097 §5's own terms.
No other member substitutes: ADR-0133 §2 rules the three independent, so a live
`INGEST` grant on this calendar authorises this read no more than a `FACET` one
does, and ADR-0133 §3 rules that no grant recorded before the member existed
acquires it.

> **Normative.** This producer's driver is the enforcement site ADR-0133 §6
> assigns, and ADR-0133 §5 binds it whole: it takes a `SourceGrants` as a required
> constructor argument with no default, it places no `await` between the `live()`
> answer and `Reader.read()`, it re-checks on return and discards the reading
> entire where the grant has gone, and it fails closed on an unanswerable check.

**Pointed at rather than restated, because a restatement is a place to diverge.**
ADR-0133 §5's clauses already bind every driver of a `NOTIFY` read; writing them
out again here would create a second text that can drift from the first under a
later edit, and ADR-0133 §6's marked clause — "No enforcement site lands with the
member. The gate of §5 lands with the producer that needs it" — is what makes this
ADR the site rather than a second author of the rule.

**The discard limb is the one this producer has to place carefully.** ADR-0133 §5
records why: ADR-0130 §3 makes offering and persisting one call, so a producer
that concluded first and re-checked afterwards would already have written the
durable record. The re-check therefore lands between the read returning and the
first offer, and a reading whose grant has gone yields no candidate at all rather
than candidates that are then withdrawn.

> **Normative.** The `NOTIFY` grant and the reach level of ADR-0130 §6 are
> separate acts and this producer derives neither from the other. It reads no
> reach level, and a class whose reach is `off` is not a reason to skip a read.

ADR-0133 §4 rules the two independent and says why in both directions: reach is
keyed on a class rather than a source and is read only once a candidate is
disposed — after the file was opened and parsed — so it can mute what was read
and can never stop a read. Configuration, consent and reach are therefore three
separate acts on this producer, and §4 below keeps the third of them out of the
first.

### 3. The walk: the reading's proposals, at the producer's own cadence

> **Normative.** The producer performs its own `Reader.read()` on its own
> schedule, and derives nothing from the facet path's reading or from the
> ingestion job's.

ADR-0093 §3's rule applied rather than stretched: "Neither may derive its answer
from the other's reading, and neither may present a reading's content without the
instants that reading carries." A producer reading a snapshot ingestion left
behind would be reading durable cross-subsystem state §5 of that ADR forbids, and
would inherit a cadence chosen for a different job.

> **Normative.** The producer's subject is the reading's per-occurrence
> proposals. For each, the occurrence's span is the `extent` its `Attestation`
> carries and the sentence the user would be told is the belief's own rendered
> content; the producer computes neither, and derives nothing from the facet.

The reading is the only per-occurrence structured surface (Context), and taking
the rendered text as written rather than re-rendering it is what keeps the
notification and the belief from disagreeing about the same entry — and keeps
`DESCRIPTION` out of a durable, exportable record, which `_render` already refuses
for a belief and which a notification does not get a weaker rule about.

> **Normative.** An occurrence whose proposal declares no extent, or whose extent
> declares no start, is not noticed. The producer never substitutes an instant the
> source did not give.

`ReportedExtent` rules that "Declaring none is always available and always safe",
and ADR-0092 §3 permits no substitute for a report time the source did not make.
An occurrence with no `DTSTAMP` is already skipped from the proposals by the
reader; this clause covers the rest of the shapes that reach the same place.

> **Normative.** The producer runs on ADR-0083 §7's serial loop, so its read never
> runs concurrently with the ingestion job's. Its cost is duty cycle, not
> contention, and a `Reader`'s single-outstanding-worker reservation is unchanged.

### 4. The lead window, and the two figures

> **Normative.** The producer notices an occurrence whose start lies in the
> half-open interval from the read instant, exclusive, to the read instant plus
> the lead window, exclusive.

The lower edge is exclusive because ADR-0130 §2 refuses at validation a candidate
whose expiry is not later than the instant it was noticed — "a candidate that has
already perished is not a proposal, it is a defect" — and §5 below makes the
expiry the start. An occurrence starting exactly at the read instant would
therefore be a defect rather than a proposal, so it is not noticed. The upper edge
is exclusive on ADR-0093 §7b's half-open convention, and the reader's own window
is `[window_start, window_end)` for the same reason. The predicate at the lower
edge is the one `CalendarReader._facet` already applies for `next_starts_at`.

> **Normative.** The lead window and the job's interval are `Settings` fields on
> ADR-0083 §7's convention: a `timedelta`, finite and strictly positive, refused
> at load otherwise, with "disabled" spelled `None` on the interval and never `0`.

> **Normative.** The interval defaults to `None`. The producer does not run until
> an operator sets it.

ADR-0093 §7's rule for the same source, unchanged: "nothing may read a user's
personal files because a default said so", which is why
`calendar_reader_interval` is `None` until someone sets it. This producer reads
the same file and gets the same default. Configuration, consent and reach are then
three separate acts and none stands in for another — the operator arms the job,
the user grants `NOTIFY` (ADR-0133 §3, which back-fills nothing), and the user
raises the class's reach from `hold`. ADR-0133 §4 rules the last two independent;
this clause keeps the first independent of both, on ADR-0097 §8's rule that
nothing mints a grant from what is already configured.

> **Normative.** The lead window defaults to **thirty minutes**.

Named here rather than left to the lane, on ADR-0093 §5's rule that a figure
invoked here cannot be satisfied elsewhere and ADR-0074 §9.3's reason: two
conforming implementations with different figures notice different things while
each believes it conforms.

> **Normative.** A lead window not strictly greater than the job's interval is
> refused at load, in the cross-field shape `calendar_reader_interval` and
> `calendar_reader_path` already take. A lead window exceeding
> `calendar_window_future` is refused at load on the same mechanism.

**Both refusals exist because the misconfiguration is silent, and silence here is
indistinguishable from working.** With ticks at `t`, `t+I`, … and a lead `L`, an
occurrence is noticed only if some tick sees it inside `(tick, tick+L)`. Where
`L < I` the intervals leave holes: an occurrence starting in `(t+L, t+I]` is too
far away at the first tick and already past at the second, so it is never noticed
at all. Where `L` exceeds the reader's forward window the read never returns the
occurrence in the first place. Either way the job runs, logs nothing and reports
health.

**What the refusal does not buy is a guarantee, and the difference is named
rather than smoothed over.** ADR-0083 §7 schedules a job from its *completion*, so
the real gap between ticks is the interval plus the run, and a late tick is
explicitly "never a correctness bug". `L > I` is therefore necessary and not
sufficient: an occurrence can still fall in the hole a late tick opens, and it is
then never noticed. That is this producer's coverage argument and it is a bounded
one — the remedy available to a deployment is a lead comfortably larger than its
interval, which is the same remedy ADR-0083 §7 offers everywhere else.

### 5. What it concludes: one candidate, expiring when the event starts

> **Normative.** A noticed occurrence yields one `NotificationCandidate` whose
> expiry is the occurrence's start instant, as the source reported it and as the
> extent carries it.

**This is the clause the whole producer exists for.** ADR-0130 §5 makes an expiry
the sole route to `INTERRUPT` and requires it to be falsifiable; a calendar
entry's start is falsifiable by the clock, by the user, and by the source. It is
also the instant at which telling the user stops being worth an interruption: at
14:01 the meeting at 14:00 is not news.

**The end instant was considered and is wrong.** An expiry at the occurrence's end
would keep a candidate actionable through a meeting the user is already sitting
in, and would make a day-long entry interruptible for a day. The value of "this is
about to happen" perishes at the start, and ADR-0130 §7's reading of expiry —
"Expiry ends a record's interruptibility and its actionability" — is exactly the
behaviour wanted.

> **Normative.** The producer offers a candidate on every run for every occurrence
> its walk selects, and holds no durable state recording which it has offered
> before.

> **Normative.** The producer's runs are independent. A run that fails partway
> leaves what it offered offered, claims nothing about what it did not, and is not
> retried other than by the next tick.

Both are ADR-0130 §8's guarantee spent rather than duplicated: a duplicate of an
actionable record is dropped and writes nothing, so a re-offer is free and a
partial pass is not a state to repair. §8 says so in terms — "A producer that
re-notices the same fact on every tick is behaving as designed."

### 6. The candidate key: the producer's name, the sentence and the span

> **Normative.** The `candidate_key` is a digest over the producer's declared
> name, the occurrence's rendered sentence and its extent's two endpoints, and
> over nothing else. It reads no clock, no minted identifier and nothing derived
> from the run.

ADR-0130 §8's requirement applied to this producer's projection. The reader's own
record id is deliberately excluded: ADR-0092 §6 rules that an import "proposes
each record at an id it mints, opaque to the source", so it is fresh on every read
and a key holding one would fold nothing.

**The sentence is in the projection and that is a decision, not padding.**
Keying on the span alone would fold two different meetings at the same hour into
one candidate, so the second is never offered and never told — a loss. Keying on
both means a retitled or moved entry yields a second candidate — a duplicate. The
corpus has ruled this direction already for the same source: ADR-0093 §5 accepts
that "the failure is duplication, not loss", and ADR-0092 §7's "a small edit
folds; a rewrite duplicates" is #631 and is open rather than closed. Duplication
is bounded by §7's cap and §6's budget; loss is bounded by nothing and is invisible.

### 7. The class, the sensitivity and the confidence

> **Normative.** The producer declares **one** notification class for every
> candidate it offers. The class is a constant, is never derived from an entry's
> title, location, duration or any other content of the source, and is distinct
> from the reader's own declared identity.

ADR-0130 §6 keys class naming to ADR-0093 §7's rule for a reader's identity — "a
stable Tier 2 name, never derived from the source's location or contents" — and a
class derived from an event would put Tier 1 content into a value the user tunes
and a surface renders. One class is also what makes the tuning surface usable: the
user's act is "never interrupt me about upcoming events", and a class per event
kind would ask them to make that decision repeatedly.

> **Normative.** The candidate's sensitivity is `DataTier.PERSONAL`, stated by
> the producer and never defaulted.

ADR-0130 §2 requires the choice and forbids the default; ADR-0093 §4 makes the
same requirement of the reader and gives the reason — `PERSONAL` "is correct for a
calendar and must not be assumed correct for the next source". The reader's
proposals over the identical content state the same tier, and a notification
carrying a weaker one would be the same content classified two ways.

> **Normative.** The producer declares a single constant confidence on every
> candidate, and derives it from no property of the occurrence.

A confidence that varied would be the producer grading the events it read, which
is the derived judgement §8 below forbids and the score ADR-0130 §11 declined. The
constant states the only thing the producer actually knows: the source said this.

### 8. What it may not conclude

> **Normative.** The producer performs no model call. It holds no `ModelProvider`
> and no `Embedder`, and no implementation may add one.

ADR-0130 §4's determinism binds `NotificationPolicy` and not a producer — §4's
second clause is explicit that a producer's confidence, summary and class are
"**evidence on the proposal**" — so the chassis would permit a model to decide
what is worth proposing. **This producer declines that permission for itself**, and
the reason is the one ADR-0130 §11 gives for the policy: it runs on every tick of
a resident process, with no provider necessarily reachable, over a source that is
a file. There is nothing here for a model to decide that the source has not
already said.

> **Normative.** The producer forms no judgement about an occurrence's importance,
> urgency, priority or interest, and no candidate it offers varies by one.

> **Normative.** The producer never notices an absence. A cancellation, a deletion
> or an entry that has stopped appearing is not a thing it proposes, and no
> implementation may add a candidate about one.

ADR-0093 §4's safety rule, which this producer inherits for the reason that
section gives rather than by analogy: "a bounded read, a truncated file, a
permission error and a genuinely deleted entry are **indistinguishable from the
reading**". A producer allowed to say "your meeting was cancelled" would say it on
the strength of a failed read, and the failure would look exactly like success.

> **Normative.** The producer does not set, propose or influence a disposition, a
> `reconsider_at`, a reach level, a quiet window or the budget. It offers, and
> ADR-0130 §5 and §6 decide.

### 9. Failure posture: silence for one tick, legible in the log

> **Normative.** A read that fails for its source raises out of the operation, is
> logged with its class and is retried at the job's next due instant. Nothing is
> offered from a failed read, and the process is never taken down.

ADR-0083 §7 and ADR-0093 §6 unchanged, and stronger here than where they were
written: the source is a file the system does not own, so unreadability is an
ordinary state of the world. A read that exceeds any of the reader's bounds is one
of these — the bound is enforced by refusing and never by truncating (ADR-0093
§5), and a producer offering candidates from the part that fitted would be
noticing a subset of the day while reporting a full pass.

> **Normative.** A pass with no live `NOTIFY` grant is never reported as a
> successful pass and never as a source failure. It is logged with its own class
> and retried at the next due instant.

ADR-0097 §5's reasoning taken rather than its clause, which is written about an
ingestion pass: "An ungranted pass reported as zero proposals is
indistinguishable from 'the source had nothing to say within the bound'". A
deployment leaving the interval set after a revocation therefore logs a refusal
every interval, which is configuration and consent disagreeing out loud rather
than a defect to design around. Two facts stay distinguishable in the log, on
ADR-0097 §5a's last clause: an unanswerable grant store propagates as itself and
is never reported as a user who has not said yes.

> **Normative.** A revocation reaches the producer's next read and no record it
> has already offered. A candidate already ruled stands, and the user's remedy is
> the dismissal and the per-record delete ADR-0130 §9 places on the store.

ADR-0097 §6 is that revoking "stops the reading and does not unwrite the beliefs",
and ADR-0133 §2 restates the boundary for this member from the other side: a
grant's reach ends at the read, so a refusal does not reach back over records an
authorised read already produced. A notification record is the same kind of thing
on the same reasoning, and ADR-0130 §6 already rules that no setting change
reaches a record ruled `INTERRUPT`.

> **Normative.** A stale source is not a failure and is not detectable. The
> producer reports what the file says, computes no staleness verdict, and never
> reads a filesystem timestamp as the source's own instant.

ADR-0096's rule for a facet, which applies with more force here: `as_of` is
`None` on a local `.ics` because "the format's report times are per-`VEVENT`, and
the file's mtime is a fact about our filesystem rather than a claim the source
made". A mirror that stopped syncing yields fewer candidates, and that is
indistinguishable from a quiet week. ADR-0130's Consequences already names this
class of cost — "silence is now ambiguous" — and this producer does not escape it.

### 10. No cursor, and ADR-0111 §11 is why

> **Normative.** The producer holds no durable cursor and no durable per-source
> state of any kind, and no implementation may introduce one.

ADR-0111 §11 rules it directly, and the clause was checked against this walk
rather than assumed to cover it:

> **Coverage over an external source.** §2 presumes an order the *store*
> maintains. A reader over a source this system does not own has no such order …
> A cursor is not the remedy for a receding window over somebody else's data.

This walk is exactly that: a lead window recomputed from the clock on every run,
over a file the system does not own. ADR-0093 §5's second half supplies the
positive argument — "The window *moves with the clock*, so every run's window is
recomputed from scratch … There is no accumulating backlog for a cursor to
track" — and ADR-0130 §8 absorbs the repetition that buys. #632 is untouched: this
ADR neither needs the scheduler's durable cursor nor closes its deferral.

### 11. What this deliberately does not open

- **A producer framework.** This is one producer's decision. It ratifies no base
  class, no registry, no producer Protocol and no shared configuration shape.
  ADR-0130 §1 is explicit that "what makes proactive contact safe is that
  producing is not delivering, not that some list of producers was blessed", and a
  framework minted from a sample of one would be a shape argued from no cases.
- **A second producer over the calendar.** Nothing here reserves the source; a
  later producer over the same file is a later lane with its own key namespace,
  its own class and its own figures, and §6's key holds the producer's name for
  exactly that reason.
- **Content-level grant scope.** Which entries, which calendars — ADR-0097 §12
  defers it with the condition that fires it, ADR-0133 §7 leaves it unnarrowed,
  and this producer does not fire it. A `NOTIFY` grant on this calendar is
  all-or-nothing, and the per-class reach level is where a user expresses less
  than all.
- **The residual ADR-0133 §2 names.** That clause bounds the member's guarantee at
  the read, so a producer over *memory* could conclude about calendar content with
  no `NOTIFY` grant anywhere. This producer is not in that residual and does not
  narrow it: §3 reads the source, so refusing `NOTIFY` forecloses it completely.
  Closing the residual needs the provenance surfaces ADR-0097 §12 defers, and
  those are not this lane's.
- **Retracting a candidate whose occurrence moved or vanished.** §8 forbids
  noticing an absence, so a candidate about an entry the user has since deleted
  expires at the start instant it was offered with. Making that better needs a
  retraction path the chassis does not have and a way to tell deletion from a
  failed read that ADR-0093 §4 says does not exist.
- **Anything about delivery.** ADR-0131 decides how a disposed notification
  travels; this ADR states no property of any channel and reads across to none.

### 12. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in this ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

- **ADR-0130 — nothing owed.** §10 reserved this decision to a producer's own
  lane and this is that lane. Every clause above is a producer obeying §1, §2, §5,
  §6 and §8 as ratified; none narrows or widens one.
- **ADR-0093 — nothing owed, and the clause that looks strained is met.** §3's
  normative rule is about how consumers *behave* — their own cadence, no deriving
  from another's reading, no presenting content without its instants — and §3
  above satisfies all three. The sentence naming "two legitimate consumers" is the
  count that existed when it was written and is not an obligation a third breaks;
  this is the ADR-0083 §15 pattern of examining a clause and finding it met, which
  ADR-0093 §3 itself used against ADR-0008 §2. §1's rule that a reader holds no
  store, writer, policy or engine is untouched: `Reader`'s surface gains nothing.
- **ADR-0083 — nothing owed.** §5's job is a new row on §7's table, the addition
  ADR-0093 §6 and ADR-0130 §5 already made twice; the body is a bound public
  engine method holding no store (§7, §8), the operation sits on the concrete
  `orchestration` engine, and §7's tolerance of a late tick is applied in §4
  rather than excepted.
- **ADR-0111 — nothing owed.** §10 relies on §11 as ratified and asks nothing of
  it.
- **ADR-0097 — nothing owed *by this ADR*, and the reason is a sequencing fact
  rather than a reading.** This producer's read is a third use of a source under
  §2's consumer axis, and that is exactly what ADR-0133 decided; the
  partial-supersession record against ADR-0097 §2's two-member enumeration is
  **ADR-0133's and landed with it**. This ADR cites the member as ratified, adds
  no use, widens no clause, and edits no word of ADR-0097. §5 and §5a are applied
  through ADR-0133 §5 rather than reached across to, which is why §2 above points
  at them instead of restating them.
- **ADR-0133 — nothing owed, and one of its clauses is discharged.** §6's marked
  clause places the enforcement site "with the producer that needs it
  (ADR-0132)", and §2 above is that site; discharging a deferral by the ADR it
  names is a stacked addition rather than an amendment (ADR-0083 §15). §1's limit
  of the member to the read, §2's independence of the three members, §3's
  no-migration rule and §4's two-axes ruling are each applied above as ratified
  and none is narrowed. Its §7 reserves "which producers exist, and what any of
  them notices" to this ADR, so nothing here trespasses on it either.

## Consequences

**Easier.**

- **The chassis gets a producer that can actually reach `INTERRUPT`.** A calendar
  start is an expiry, and an expiry is the only route through ADR-0130 §5's
  conjunctive clause. Leg 10's exit test becomes a thing to observe rather than a
  thing to simulate.
- **Nothing new is invented to build it.** A row on ADR-0083 §7's table, an
  operation in the shape `Engine.ingest` already takes, a bounded read the reader
  already performs, ADR-0130's seam and ADR-0133's member. The implementing lane
  adds two `Settings` fields and no contract surface of its own.
- **The producer is bounded three ways before it ever runs.** The interval is
  `None` until an operator sets it, the read needs a live `NOTIFY` grant that
  ADR-0133 §3 back-fills onto nobody, and every class defaults to `hold`. Each is
  a separate act and none implies another.
- **"Do not raise my calendar with me unprompted" becomes sayable, and this
  producer is what it bites on.** ADR-0133 §2 records that the member's guarantee
  ends at the read and that a producer over stored records escapes it; this one
  reads the source, so refusing the grant forecloses it entirely rather than
  partly. That is the strongest form of the sentence available in the corpus
  today.

**Harder.**

- **The implementation is sequenced behind a `core` lane it does not own.**
  `GrantScope.NOTIFY` is ADR-0133 §6's implementing lane, and ADR-0133 §6 forbids
  any lane reading a granted source to conclude a candidate until the gate lands
  with this producer. So the producer cannot be built first, and building it is
  two lanes in order rather than one.
- **Coverage is a bounded argument rather than a guarantee.** §4's load-time
  refusals close the configuration hole; a late tick can still open one, and a
  missed occurrence is silent. **Revisit if the scheduler ever gains a
  catch-up mechanism**, which would close it exactly and which ADR-0083 §7's
  fixed-delay design currently declines.
- **A rewritten entry notifies twice.** §6 keys on the sentence, so moving a
  meeting yields a second candidate about the same meeting. That is #631's shape
  reaching a second surface, and it is the direction chosen deliberately over
  losing an event.
- **Two reads of one file where there was one.** The producer's read is
  independent of ingestion's, so a deployment running both parses the calendar on
  two schedules. The serial loop keeps them from contending; what it costs is duty
  cycle, and ADR-0083 §7's revisit trigger — a job whose runtime approaches its
  interval — now has a second candidate.
