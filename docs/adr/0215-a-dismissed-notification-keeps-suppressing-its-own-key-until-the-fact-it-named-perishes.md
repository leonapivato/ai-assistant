# 215. A dismissed notification keeps suppressing its own key until the fact it named perishes

- Status: Proposed
- Date: 2026-08-29
- **Partially supersedes:**
  [ADR-0130](0130-a-notification-is-a-proposal-and-only-a-perishable-one-earns-an-interruption.md)
  — the **population §8's duplicate lookup reads**, and the four other clauses
  that name it. §2 below replaces the actionable set with the *suppressing* set;
  §4 replaces the purge guard that stands behind it. Named exactly, the replaced
  text is: §3's atomicity phrase "the same absence of an actionable record for one
  key"; §5's third `DROP` condition "it duplicates an actionable record under §8";
  §7's sentence "§8's duplicate rule reads the same population, so a fact that
  recurs after its notification expired or was dismissed is a new candidate and
  not a duplicate", in its **dismissed** half only; §7's purge clause "A record is
  purgeable only once it is no longer actionable and its retention has elapsed. No
  record is purged while it is still actionable, whatever its retention, so a
  record's key suppresses duplicates for the whole time §8 says it does"; §8's
  clause "A candidate offered by a producer whose key matches an **actionable**
  record (§7) is ruled `DROP` naming the duplicate"; and the two clauses of §9's
  conformance list that pin the two of these a suite can observe. A reader holding
  only ADR-0130 writes a store that re-interrupts on the next tick after a
  delivery, which is acting differently in ADR-0070 §1's sense and puts this on
  the supersession side rather than the amendment side. It is **partial** and
  deliberately narrow: §5's ruling order, §5's reconsideration, §6's three
  standing settings and its interruption budget, §7's cap and its
  retention-from-cessation stamp, and §8's cursorless-producer guarantee are not
  merely kept but are the **ground** of this decision — §5 below says so clause by
  clause.
- **Durability clause.** Every reference below to an ADR is to its text as it
  stood at this ADR's base, `2ba14572`, not to its status on any later day. Where
  a later ADR moves one of the clauses quoted here, this decision is read against
  the text quoted, and the reconciliation is that ADR's to record.

## Context

### One event, three interruptions, and every clause held

Issue #1372 is a composition finding from the milestone-14 phone QA (2026-08-22),
measured on the live hub with the upcoming-event producer of ADR-0132 armed at a
one-minute interval and a fifteen-minute lead, `upcoming_event` at reach
`interrupt`, and **one** planted calendar event.

What the run recorded, from `assistant notifications` and the gateway log: the
occurrence was noticed at 23:00 and delivered to the phone at 23:06:20; noticed
again at 23:06 and delivered at 23:06:22; again at 23:07, delivered at 23:07:22
to two open streams; and again at 23:08, where ADR-0130 §6's default budget of
three interruptions per rolling twenty-four hours was exhausted and the ruling
came back `HOLD`. The ticks between 23:01 and 23:05 produced nothing at all.

**One event, three interruptions, and a budget spent for the day.** Nothing
malfunctioned. Every clause involved did exactly what it says.

### The clauses, and why their composition is the gap

ADR-0130 §8 makes re-noticing the design rather than a defect, and says what
makes it safe:

```text
**Normative.** A candidate offered by a producer whose key matches an
**actionable** record (§7) is ruled `DROP` naming the duplicate. A
reconsideration is not an offer and never matches itself (§5).
```

```text
**Normative.** No producer may require a durable cursor in order to be correct.
A producer that re-notices the same fact on every tick is behaving as designed,
and this section is what makes that safe.
```

ADR-0130 §7 says which population that is:

```text
**Normative.** A record is **actionable** while it is neither dismissed, nor
expired, nor ruled `DROP` by a reconsideration. It is **retained** until
retention removes it.
```

```text
**Normative.** The cap counts **actionable** records and no others, so
dismissing a notification frees capacity at once and an expired one holds none.
§8's duplicate rule reads the same population, so a fact that recurs after its
notification expired or was dismissed is a new candidate and not a duplicate.
```

And ADR-0131 §3b makes a delivery end that population membership:

```text
**Normative.** **Every** way an entry leaves the outbox **dismisses** its
ADR-0130 record, through the dismissal `NotificationStore` carries — an
acknowledgement (§3), an eviction under either bound (§3), a broken lease (§3),
and a withdrawal (§3a), together with any further way a later decision adds.
```

The tree does what those say. `SqliteNotificationOutbox.acknowledge` calls
`_dismiss`, which calls `NotificationStore.dismiss`; `SqliteNotificationStore`
stamps `dismissed_at`, and its duplicate lookup — `_is_duplicate`, whose SQL is
narrowed by the module constant `_UNCEASED`, "dismissed_at IS NULL AND dropped_at
IS NULL" — stops seeing the record at that instant.

**So a notification suppresses its own duplicates for exactly as long as it is
undelivered, and stops the moment it is delivered.** That is the inverse of what
the guarantee is for. The 23:01–23:05 silence is §8 working; the 23:06 repeat is
§8 switched off by the very event that means it succeeded.

### The producer is correct, and this is not its bug to fix

ADR-0132 is the producer in question and needs no change. Its §5 makes the
candidate's expiry the occurrence's start instant, and offers "a candidate on
every run for every occurrence its walk selects" while holding "no durable state
recording which it has offered before". Its §10 forbids one outright:

```text
**Normative.** The producer holds no durable cursor and no durable per-source
state of any kind, and no implementation may introduce one.
```

Every producer in this tree is entitled to that posture, because ADR-0130 §8
promised to absorb the repetition it produces. The promise is what failed, not
the producer relying on it.

### The two jobs a dismissal was doing, and only one of them is about the fact

A dismissal in ADR-0130 is a statement about a **record**: it "ends actionability
and leaves the record readable" (§9), it "frees capacity at once" (§7), and it
takes the record off the list a person reads. ADR-0131 §3b then borrowed it for a
statement about **bytes** — the outbox is done with this entry — because ADR-0130
§9 already provided exactly the operation an undeliverable or delivered
notification wants, and inventing a second one would have reached into another
ADR's ground. That reuse was right and is kept whole here.

What went wrong is that a third thing was tied to the same act. §8's suppression
is a statement about neither the record nor the bytes: it is a statement about
the **fact** — this fact has already been proposed, so proposing it again is a
duplicate. A fact does not stop being the same fact because a record about it was
taken off a list, or because a device confirmed some bytes. The lifetime that
governs suppression is the fact's own, and the corpus already carries it: the
candidate's declared expiry, which ADR-0130 §5 makes the sole route to
`INTERRUPT` precisely because it is the one criterion a producer can be held to.

### What is genuinely open, and what only looks open

Open: which population §8's lookup reads, and what stops retention purging a
record out from under it. Not open, and settled elsewhere: whether the producer
may keep a cursor (ADR-0132 §10, no); whether delivery state may land on the
record (ADR-0130 §2 and the `HeldNotification` docstring, no); whether a spent
budget unit is refunded (ADR-0130 §5, no); and whether the cap counts anything
but actionable records (ADR-0130 §7, no — and §3 below keeps it).

## Decision

### 1. A record suppresses its key while the fact it named is still live

> **Normative.** A `HeldNotification` **speaks for its key** — equivalently, it
> **suppresses** candidates carrying that key; the two phrasings name one thing —
> at an instant when it is actionable at that instant, or when it carries a
> dismissal, carries **no** reconsideration `DROP`, and its candidate declares an
> expiry later than that instant. It speaks at no other instant, and where a
> record carries both stamps the `DROP` decides: such a record speaks for nothing
> after it ceased.

> **Normative.** The horizon is the candidate's **declared expiry** and nothing
> else. No new instant is stored, no duration is configured, and no implementation
> may derive a suppression horizon from a setting, a clock reading taken at the
> dismissal, or any figure not already on the record.

> **Normative.** A candidate that declares **no** expiry yields a record whose
> suppression ends exactly where its actionability ends. No implementation may
> supply a default horizon for it.

**The horizon this adds is not a new one — it is the horizon the record already
had.** An undismissed record whose candidate expires at `E` is actionable until
`E` and suppresses until `E` today. What changes is only that **dismissing no
longer shortens it.** So the reach of suppression in the worst case — a producer
declaring a distant expiry — is exactly what ADR-0130 already admitted, and this
decision adds no case in which a key is suppressed for longer than the producer
itself said the fact would live.

**The predicate is total, and rests on no assumption about which stamps can
coexist.** It reads two stamps and a declared expiry and answers at any instant.
The tree's store does in fact never stamp a dismissal on a record that is not
actionable — `SqliteNotificationStore.dismiss` reports `False` there, because "the
cessation instant a retention horizon is measured from may not be moved by a second
call" — and a reconsideration never reaches a dismissed record,
`HeldNotification.is_due_at` requiring `dismissed_at is None`. But
`HeldNotification`'s coherence validator does **not** forbid the pair: it ties
`dropped_at` to a `DROP` ruling and says nothing about a dismissal beside it. So
the clause states the precedence rather than relying on the pair being
unreachable — the `DROP` wins — and a dismissal stamped at or after an expiry
yields a horizon already past. `HeldNotification.ceased_at` already takes the
earliest of the three cessations, so nothing here needs a fourth stamp.

**A record that ceased by expiry, or by a reconsideration's `DROP`, suppresses
nothing after it ceased**, which follows from the clause rather than adding to it:
neither disjunct holds. For expiry that is the point — the fact perished. For the
`DROP` it is deliberate, and the reason is ADR-0130 §5's own ordering. A `DROP` on
a reconsideration comes from an expiry or from a class lowered to `off` (§5), and
while a class is `off` the reach condition is evaluated **before** the duplicate
condition, so every offer of that key is dropped naming the reach and writes
nothing whether or not the old record suppresses. Suppression there would buy
nothing while the class is off, and would cost the user the case that matters: the
owner turns the class back to `interrupt` inside the candidate's lifetime — a mind
changed faster than the fact perishes — and must be reachable. §6 of ADR-0130
already sweeps held records for that act; this keeps the dropped ones from
outliving it.

**This shape is not new, and the corpus carries it one store over.** ADR-0130 §8
says what it reached for: "This is `MemoryUpdateProposal.proposal_fingerprint`'s
discipline and ADR-0078 §7's dedup-by-question, reached for the same reason and by
the same means." In `DeferredProposal` that discipline is the predicate
`speaks_for_its_key_at`, and a **`REJECTED`** row — a question that is over, whose
actionable life ended — goes on speaking for its key for the whole of its
retention. `DeferredProposal.is_purgeable_at` keeps it alive expressly for that:
"A *terminal* row is retained for one further lifetime because something depends on
it surviving: a `REJECTED` key is read to refuse re-asking, and that is the whole
retention argument." ADR-0130 §8 borrowed the deduplication and left that half
behind, and #1372 is the bill. This decision restores it, with the notification's
own declared horizon in place of the deferral's retention — and the predicate takes
the same name, because it is the same predicate.

### 2. §8's duplicate lookup reads the suppressing population

> **Normative.** A candidate offered by a producer whose key matches a record that
> **suppresses** at the ruling instant (§1) is ruled `DROP` naming the duplicate.
> This replaces ADR-0130 §8's actionable-record test and changes nothing else
> about it: a reconsideration is still not an offer and still never matches
> itself, and a `DROP` still writes no durable record.

> **Normative.** ADR-0130 §5's third `DROP` condition — "it duplicates an
> actionable record under §8" — is read as "it duplicates a suppressing record
> under §8". The ordering of §5's four conditions, the reason each names, and the
> conjunctive `INTERRUPT` clause after them are untouched.

> **Normative.** ADR-0130 §3's atomicity clause binds the suppressing set where it
> named the actionable one: two rulings made concurrently may not both proceed on
> the strength of the same absence of a **suppressing** record for one key. Its
> other two limbs — the last unit of budget and the last free slot under the
> cap — are unchanged and still read the populations they always read.

**At most one record per key suppresses at any instant, and it follows from the
rule rather than being imposed on top of it.** A suppressing record makes every
offer of its key a `DROP`, and a `DROP` writes nothing; so no second record for
that key can be admitted while the first suppresses. That is what keeps the lookup
single-valued and what keeps ADR-0131 §3b's record resolution — which matches an
outbox entry's key to *the* actionable record carrying it — unambiguous, since a
suppressing record that is no longer actionable is not a candidate for that match.

**The expired half of ADR-0130 §7's sentence survives and is not superseded.** "A
fact that recurs after its notification **expired** is a new candidate and not a
duplicate" stays true under §1: an expired record carries no dismissal, so neither
disjunct holds and it suppresses nothing. Only the "or was dismissed" half is
replaced. That asymmetry is the whole decision in one line — expiry is the fact
perishing, and a dismissal is not.

### 3. The cap is untouched: it counts actionable records, and a delivered one holds none

> **Normative.** ADR-0130 §7's cap counts **actionable** records and no others,
> exactly as ratified. A record that suppresses without being actionable holds no
> capacity, and no clause of this ADR may be read as widening the cap's
> population.

**Capacity and suppression are answers to different questions, and #1372 is the
evidence that tying them together is what broke.** The cap bounds *the list a
person reads*: ADR-0130 §7 says so — "Bounding the actionable set is what the cap
is actually for — it is the list a person reads." Suppression bounds *repeat
contact about one fact*. A delivered notification should leave the first and not
the second, and that is precisely the pair this decision separates. So a delivered
record frees its slot at once, as §7 promised, and still holds its key.

**This is also why the store's two reads must stay two reads.** An implementation
that computed one population and used it for both would be re-introducing the
coupling this ADR removes, in the other direction.

### 4. Retention yields again: no record is purged while it still suppresses

> **Normative.** A record is purgeable only once it **no longer suppresses** (§1)
> and its retention has elapsed. This replaces ADR-0130 §7's purge clause, which
> tested actionability, and it is that clause's own stated reason applied to §2's
> population: no record is purged while its key is still doing §8's work.

> **Normative.** The retention duration and the instant it runs from are
> unchanged: it is stamped on the record at admission, never consulted from the
> setting afterwards, and it runs from the instant the record **ceased to be
> actionable**. `None` still means never purged.

**So a dismissed record's purge waits for the later of its two conditions, and
neither boundary direction moves.** `HeldNotification.is_purgeable_at` tests
retention **strictly** — "at the horizon it is still held, and past it it is not,
which is the boundary §9's conformance clause states" — and §1's horizon is
half-open, a record speaking for its key strictly before the declared expiry. This
ADR changes neither; it adds a second condition that must hold as well. So for a
record dismissed at `D` with retention `R` and a candidate expiring at `E`: where
`E` is later than `D + R`, the record is not purgeable before `E` and is purgeable
at it, because it stops speaking there and retention elapsed strictly earlier;
where `E` is not later than `D + R`, the record is purgeable exactly where
ADR-0130 §7 already put it, strictly after `D + R`.

**This is the same correction §7 already made once, applied to the clause that
moved.** ADR-0130 §7 argued: "Measured from admission, a record whose expiry sits
beyond the horizon is purged while it is still actionable — at which point its key
suppresses nothing, a cursorless producer re-notices the same fact, and the same
observation interrupts a second time on a schedule set by the retention figure.
§8's guarantee is stated unconditionally, so retention has to be the clause that
yields." Every word of that argument holds for a *dismissed* record under §2, and
without this clause a deployment with a short retention would reproduce #1372 on a
slower schedule.

**It adds no unbounded case.** The guard's reach is `max(ceased + retention,
expiry)`, and `expiry` is a bound ADR-0130 §7 already granted: the same record
undismissed is unpurgeable until that same instant today, because it is actionable
until then. A record with no expiry is unreached by this clause entirely, by §1's
third clause.

### 5. What is kept whole, and no clause here may be read as reaching it

> **Normative.** ADR-0130 §6's interruption budget is untouched in every part: its
> default of three per rolling twenty-four hours, the rule that a unit is spent
> when an `INTERRUPT` disposition is recorded rather than when contact is
> attempted or succeeds, and ADR-0130 §5's rule that "no spent unit is refunded
> except by an act that says so". No clause of this ADR refunds a unit, and no
> lane may read one as doing so.

> **Normative.** ADR-0130 §5's reconsideration is untouched: a reconsideration is
> not an offer, introduces no second record, never matches itself as a duplicate,
> falls due at a `reconsider_at` that is a floor rather than a deadline, and is
> driven by the job §5 places on the concrete `orchestration` engine. A
> reconsideration runs only on a record that has not been dismissed, so no record
> reached by §1's second disjunct is one a reconsideration can rule.

> **Normative.** ADR-0130 §6's three standing settings, their defaults, and both
> of its re-ruling clauses — the failed-condition-set sweep and the `off` sweep
> over every actionable held record — are untouched.

> **Normative.** ADR-0131 §3b is untouched in every normative part: the live
> handoff stays the primary path and the startup reconciliation stays a **repair**
> and never a trigger; every way an entry leaves the outbox still dismisses its
> record; the dismissal still commits before the removal; and the invariant that
> ordering establishes — an actionable record with no outbox entry means its
> enqueue never committed — still holds, because this ADR changes no record's
> actionability.

> **Normative.** ADR-0130 §2's refusal stands and is widened by nothing here: a
> record carries no delivery state, and no clause of this ADR may be read as
> placing one on the record, on the candidate or on the disposition.

**The last one is load-bearing rather than decorative.** It is what distinguishes
this decision from the alternative it declines: a rule that read "was this
delivered?" would need that fact written down somewhere, and it is exactly the
fact ADR-0078 §8 refused to put on a memory decision and ADR-0130 §2 refused to
put on a candidate. §1's predicate reads the dismissal stamp the record already
carries and the expiry the producer already declared, and asks nothing about
transport.

### 6. What the owner sees

Not normative; this section states the observable behaviour the clauses above
produce, so that a QA run and the implementing lane are testing the same thing.

- **One event, one interruption.** The 23:00 notice interrupts. Every notice from
  23:01 until the occurrence's start instant is dropped as a duplicate, whether or
  not the phone acknowledged the first. The budget spends one unit for the day
  instead of three.
- **A changed event is a new candidate.** ADR-0132 §6 keys on "the producer's
  declared name, the occurrence's rendered sentence and its extent's two
  endpoints", so a meeting moved from 23:15 to 23:45 has a different key, matches
  no suppressing record, and is offered afresh. The owner is told about the move.
- **A dismissal still empties the list and still frees the cap**, at once, exactly
  as before — it simply no longer invites the same fact back on the next tick.
- **After the occurrence starts, the key is free again.** Suppression ends at the
  expiry ADR-0132 §5 sets to the start instant, at which point the producer's own
  lead window no longer selects the occurrence either. The two horizons agree, and
  neither depends on the other.

### 7. The contract surface, and what the implementing lane owes

> **Normative.** `core/types.py`'s `HeldNotification` gains exactly one predicate
> and **no field**:
>
> `def speaks_for_its_key_at(self, moment: datetime) -> bool: ...`
>
> returning whether the record speaks for its key at `moment` in §1's sense. It is
> a pure function of the record — the dismissal stamp, the drop stamp, and the
> candidate's declared expiry — and reads no setting, no clock and no store. The
> name is `DeferredProposal.speaks_for_its_key_at`'s, deliberately: it is the same
> predicate over the other store's records, and two names for it is how the two
> drift.

> **Normative.** The predicate lives on the type and not in a backend, for the
> reason `is_actionable_at` does: two conforming stores must not be able to
> disagree about the instant a key stops speaking.

> **Normative.** No field is added to any wire-carried type, so no value either
> peer emits becomes invalid for the other and `PROTOCOL_VERSION` does not move.
> An implementing lane that finds itself adding a field has left this decision.

> **Normative.** No Protocol gains or loses a member and no signature changes.
> **But the behavioural contract of `NotificationStore` does change** — its
> admission refuses a duplicate over the *speaking* set rather than the actionable
> one, and its purge no longer releases a record that still speaks for its key — so
> this is a breaking contract change, flagged as one under golden rule 5. The
> implementing lane therefore updates `core/protocols.py`'s own statement of those
> two rules in the same change: `NotificationStore`'s class docstring, which states
> the cap-and-duplicate population and the purge guard verbatim from ADR-0130 §7,
> and the members that restate them — `admit`, `purge` and the atomicity paragraph
> §3 puts on the seam. Leaving those standing would put two contradictory
> statements of one contract in the tree, which is the failure the shared
> conformance suite cannot catch.

> **Normative.** The implementing lane changes the duplicate lookup and the purge
> of **every** `NotificationStore` implementation together with the shared
> conformance suite, in one change: the SQLite store, the canonical fake in
> `ai_assistant.testing`, and the suite in `tests/core/`. A lane that moves one
> and not the others has made two conforming stores disagree, which is the failure
> the shared suite exists to prevent.

> **Normative.** The shared conformance suite asserts, on every implementation:
> that a candidate re-offered after its predecessor was **dismissed** is ruled
> `DROP` naming the duplicate while the predecessor's declared expiry is still in
> the future, and writes no record; that **at or after** that expiry the
> predecessor speaks for its key no longer, observed both ways — the *same*
> candidate re-offered there is ruled `DROP` naming the **expiry** and not the
> duplicate, ADR-0130 §5 evaluating expiry first, and a candidate carrying the same
> key with an expiry still in the future is **admitted**; that a candidate whose
> predecessor declared **no** expiry is admitted after a dismissal, exactly as
> before; that a record dropped by a reconsideration speaks for nothing after the
> drop, including one carrying a dismissal stamp beside the drop; that a dismissal
> frees the cap at once even while its key still speaks; and that a dismissed
> record whose candidate's expiry falls **later** than its retention horizon is not
> purged before that expiry and is purged at it, while one whose expiry falls at or
> before that horizon is purged exactly where ADR-0130 §7 already put it.

> **Normative.** Those two of ADR-0130 §9's conformance obligations that state the
> replaced rules are superseded by the clause above and are removed rather than
> left standing beside it: "that a candidate re-offered after its predecessor
> expired or was dismissed is **not** a duplicate", in its *dismissed* half, and
> the purge obligation "that a record dismissed, expired or dropped by a
> reconsideration is purged neither before nor at its retention horizon measured
> from **that** instant but immediately after it", in the case where the record is
> still speaking for its key at that horizon. The boundary that obligation states
> is **not** superseded and is re-asserted above for every record that speaks for
> nothing. Every other obligation in §9's list stands, the `None`-retention case
> included.

> **Normative.** The lane touches `core/types.py`, so it is a contract change: it
> merges alone, it owes the adversarial **and** architecture review set (ADR-0015
> §1), and nothing implements against this ADR until it has merged (golden rule 5,
> ADR-0015 §5).

**The named sites, so the lane does not have to find them.** The duplicate lookup
is `SqliteNotificationStore._is_duplicate`, whose SQL narrows by the module
constant `_UNCEASED` and whose remaining filter is `is_actionable_at`; the
narrowing by dismissal is what has to go, and the record's own predicate is what
replaces it. The purge is `SqliteNotificationStore._purge_sync` by way of the
module helper `_is_purgeable`, which wraps `HeldNotification.is_purgeable_at` and
is where the second condition joins. The canonical fake's counterparts are in
`ai_assistant.testing`'s notification module, and the shared suite is
`tests/core/notification_contract.py`. `SqliteNotificationOutbox` needs no change
at all: every site it reads actionability at still means actionability.

**No new index and no new column.** The lookup already selects by
`candidate_key`; what changes is which of the selected rows count. The rows for
one key are bounded by the same argument ADR-0130 §7 makes for its expired tail.

### 8. Explicitly declined

> **Normative.** No implementation may introduce a delivery state, a delivery
> stamp, or any record of whether contact was attempted or reached a device, in
> order to satisfy §1. §5 keeps ADR-0130 §2's refusal, and a lane that needs such
> a fact has found a decision this ADR did not make.

> **Normative.** No producer is required to hold a cursor, a durable record of
> what it has offered, or any per-source state, by any clause of this ADR.
> ADR-0130 §8's "No producer may require a durable cursor in order to be correct"
> is the guarantee this decision repairs, and ADR-0132 §10's prohibition is
> untouched.

> **Normative.** No configurable suppression window, grace period or cooldown is
> introduced, and no implementation may add one. The horizon is the producer's own
> declared expiry.

**A configurable window is the priority score in another costume.** ADR-0130 §11
refused a numeric urgency because "weighed by the policy, it is a threshold nobody
can calibrate on the first day", and a global "suppress a dismissed key for N
minutes" is exactly that threshold: right for a calendar occurrence and wrong for
whatever ships next, with nothing to calibrate it against. A declared expiry is
falsifiable and per-fact, which is the property ADR-0130 §5 chose expiry for.

### 9. What this ADR does not decide

- **Whether a fact whose entry was evicted or terminally refused should come back
  before its expiry.** ADR-0131 §3b dismisses the record on an eviction, a broken
  lease and a `TOO_LARGE`/`KEY_COLLISION` refusal; under §2 such a record keeps
  suppressing until its expiry, so the fact is not re-offered in that window. That
  is a real cost and Consequences names it. It is not decided here because
  distinguishing "dismissed because the owner was reached" from "dismissed because
  the hub gave up" requires the record to carry *why*, which is delivery state,
  which §5 and §8 refuse. **Revisit when the hub's log — which ADR-0131 §3b
  already requires for a terminal refusal — records such a dismissal of a record
  that was never delivered, and the owner judges that silence worse than the
  second interruption this ADR removes.** The remedy at that point is a cessation
  cause on the record, which is a new contract surface and its own ADR.
- **The churn of a no-expiry candidate on the held list.** §1's third clause
  leaves such a record exactly where ADR-0130 left it: dismissing it lets the next
  tick re-admit it. It cannot produce #1372's failure, because ADR-0130 §5's
  conjunctive clause makes a declared expiry the first condition of `INTERRUPT`,
  so such a candidate can never interrupt at all. **Revisit if a no-expiry
  producer is observed re-admitting a dismissed record onto the held list;** the
  remedy is then a producer-declared horizon on the candidate, not a global figure
  (§8).
- **A producer whose projection churns.** A retitled or moved occurrence yields a
  different key and is a new candidate by construction: ADR-0132 §6 decides the
  projection and records that "keying on both means a retitled or moved entry
  yields a second candidate — a duplicate", citing ADR-0092 §7's "a small edit
  folds; a rewrite duplicates" as #631, "open rather than closed". This ADR bounds
  repeat contact *per key* and makes no claim about a producer that emits a new
  key for an unchanged fact.
- **Whether the notification surface should render a suppressing-but-dismissed
  record differently.** ADR-0130 §7's read surface enumerates retained records and
  is untouched; whether a client shows that a key is still held is a presentation
  question for a later lane.
- **Anything about the delivery seam.** ADR-0131's outbox, its bounds, its leases
  and its reconciliation are read here and changed nowhere.

### 10. What this records against earlier ADRs

- **ADR-0130 — partially superseded**, scoped exactly as the header names, under
  ADR-0070 §1's test and ADR-0070 §3's partial form. A reader holding only
  ADR-0130 would build the store that produced #1372, so its clauses do not merely
  gain a neighbour; they read differently. ADR-0130's `Status` line takes the
  leading `Partially superseded by` token — dropping `Accepted`, per
  `docs/adr/template.md`, "so a prefix match on 'Accepted' cannot misread the
  replaced part as live" — and carries the dated note ADR-0070 §1 requires.
- **That record lands in this same change, which is what ADR-0070 §1 permits and
  what the corpus does.** §1's second permitted header edit is "**recording a
  supersession that has landed** on the Status line (ADR-0001 already requires
  this). This presupposes the superseding ADR *exists*: flipping a live decision to
  `Superseded` with no such ADR is not a status change but an unrecorded decision
  change, and is not permitted." The presupposition is **existence**, and ADR-0215
  exists in the commit that writes the record. It is also the route the corpus took
  most recently: commit `284ae501`, whose subject is "docs(adr): propose ADR-0211,
  the planner is told which capabilities exist", carries ADR-0211 standing
  `Proposed` **and** the `Partially superseded by ADR-0211` records on ADR-0014 and
  ADR-0176 — one commit, one PR, both required lenses. Nothing on `main` ever
  points at a `Proposed` supersession, because `CONTRIBUTING.md` → "Finishing an
  ADR PR" flips this ADR to `Accepted` before the merge and `just ready` refuses
  otherwise (ADR-0165 §5). Deferring the record to a second PR would do the
  opposite: it would put ADR-0130 on `main` reading an unqualified `Accepted` while
  six of its clauses had already been replaced — the inaccuracy §1's *third*
  permitted edit exists to correct, arrived at deliberately.
- **ADR-0131 — nothing owed, and the test is applied rather than assumed.**
  ADR-0082 §1 asks whether a reader holding only ADR-0131 "would now act
  differently, or read one of its clauses more widely than it now holds", and for
  every normative clause of §3b the answer is no: this ADR changes no record's
  actionability, so the reconciliation clause selects the same records, the
  dismiss-before-remove ordering is unchanged, and the invariant it establishes is
  unchanged. What this decision does make stale is one sentence of §3b's
  **unmarked** argument — "If the fact still holds after an eviction, it comes back
  through the *producer* re-noticing it as a new candidate (ADR-0130 §7), which
  faces the cap and the budget afresh" — and under ADR-0089 §3 unmarked text in a
  marked ADR "is read to determine what a marked clause *means*; it never supplies
  an obligation". No clause fails ADR-0082 §1's test, so no record is owed, and
  ADR-0082 §1 is explicit that "a later ADR that calls its change an amendment of
  ADR-N without a clause of ADR-N failing §1's test has mis-declared it". §9 above
  names the consequence that sentence described, which is where a reader coming
  from ADR-0131 will find it.
- **ADR-0132 — nothing owed.** Its §5's re-offer clause and its §10's no-cursor
  clause are the guarantees this decision honours; its §5 argument that "a
  duplicate of an actionable record is dropped and writes nothing, so a re-offer
  is free" stays true of a suppressing record and is now true more often. No
  clause of it becomes false or wider.
- **ADR-0141 — nothing owed.** Its §6 duplicate share is defined over
  `condition_duplicate` on the offer population and is computed identically; only
  the *value* moves, which is what a measure is for. Its §7 condition incidence is
  likewise unchanged in definition. This ADR is a stacked addition to it under
  ADR-0082 §1.
- **ADR-0078, ADR-0093, ADR-0111 — nothing owed and nothing read across.**
  ADR-0078 §8's two refusals are kept by §5; ADR-0093 §5's cursorless posture and
  ADR-0111 §11's finding that no cursor answers a receding window over somebody
  else's data are the premises §2 restores rather than clauses it touches.
- **This ADR's `Status`.** It decides `core/types.py` surface, so the required
  review set is adversarial **and** architecture (ADR-0015 §1, `CONTRIBUTING.md` →
  "Stop when the required reviews are green"), and ADR-0015 §5's
  ratify-after-review sequencing reaches it: it is drafted, reviewed and revised as
  `Proposed`, and its status is flipped only once both required reviews return
  clean on one tree. `CONTRIBUTING.md` → "Finishing an ADR PR" is the sequence, and
  this line records the route rather than re-arguing it. Nothing implements against
  §7 until this has merged.

## Consequences

**Easier.**

- **One event costs one interruption.** The failure #1372 measured is closed by a
  predicate, with no new state, no new setting, no new seam and no protocol bump.
  The budget stops being spent on repetition, which is what makes the default of
  three per day a meaningful figure rather than a countdown.
- **§8's promise becomes true for the case it was written for.** ADR-0130 §8 says
  a producer that re-notices on every tick "is behaving as designed, and this
  section is what makes that safe". After a delivery it was not safe. It is now,
  and every existing cursorless producer inherits the repair without changing.
- **The dismissal recovers a single meaning.** It ends actionability, frees the
  cap, and takes the record off the list — three statements about the record — and
  says nothing about the fact. ADR-0131 §3b can keep using it for a delivered or
  undeliverable entry without that reuse leaking into the policy.
- **Nothing about the delivery seam has to know.** The outbox reads
  actionability at every site it reads anything, and every one of those still
  means what it meant. The repair lands entirely inside ADR-0130's ground.
- **The rule is testable at an instant.** `suppresses_at` is a pure function of
  two stamps and a declared expiry, so the conformance suite can pin the boundary
  the way it already pins `is_actionable_at`'s, and two backends cannot drift.

**Harder.**

- **A notification the hub gave up on stays suppressed until its fact perishes.**
  An entry evicted under a byte bound, or refused as `TOO_LARGE`, dismisses its
  record (ADR-0131 §3b), and that record now blocks its key until the expiry. The
  owner is told nothing about that occurrence, having spent a budget unit on it.
  This errs toward silence, which is the direction ADR-0130 §5 chose deliberately
  — "errs toward silence when delivery is unreliable — which is the direction a
  system with no attention signal should err in" — but it is a real loss, and §9
  states the condition that reopens it.
- **A dismissed record stays in the store longer.** §4's guard holds a record
  through `max(ceased + retention, expiry)` instead of `ceased + retention`. For
  the calendar producer that is minutes; for a producer declaring a distant expiry
  it is that expiry, which the same record already had while undismissed. It is
  bounded storage, not unbounded, and §9's delete surface still reaches it.
- **Two populations now exist where one did, and a reader has to hold both.**
  "Actionable" and "suppressing" differ in exactly one case — a dismissed record
  before its expiry — and every clause that names a population now has to name the
  right one. The clauses above name them exhaustively for that reason, and the
  conformance suite pins the difference rather than leaving it to reading.
- **The duplicate share ADR-0141 §6 measures will move, and the move is the
  point.** An operator comparing windows across this change will see the share
  rise, because rulings that were `INTERRUPT` become `condition_duplicate`. That is
  the measure reporting the repair, not a regression, and it is worth saying once
  in the record so that nobody reads the step as a producer defect.
- **A no-expiry candidate is left exactly where it was.** The decision buys
  nothing for a producer that declines to declare a horizon, and §9 says so
  plainly rather than implying coverage the clauses do not give.

## Alternatives considered

**A `delivered` state distinct from `dismissed`, kept inside §8's population.**
This is #1372's second candidate direction and it was the closest call. It fails
on three counts, in increasing order of weight. It needs a fourth stamp on
`HeldNotification` whose whole content is "contact reached a device" — which is
delivery state on the record, refused by ADR-0130 §2's clause that "no clause of
this ADR may be read as placing one there" and by ADR-0078 §8 before it, so taking
this direction means superseding those refusals rather than composing with them.
It forces a second ruling nobody asked for: does a delivered record hold cap
capacity? Either answer is a change to ADR-0130 §7's cap — the one clause #1372
does not touch. And it repairs the delivered case only: a record the owner
dismisses by hand, or one the outbox evicts, is still re-admitted on the next tick,
so the guarantee stays conditional on which act ended the record. §1's rule needs
no new state, leaves the cap alone, and covers every cessation by dismissal
uniformly.

**The producer's lead window excluding facts it has already delivered.** This is
#1372's third candidate direction, and it is foreclosed twice over. ADR-0130 §8
rules that "No producer may require a durable cursor in order to be correct", and
ADR-0132 §10 rules for this producer specifically that it "holds no durable cursor
and no durable per-source state of any kind, and no implementation may introduce
one". Beyond the prohibition, it is the wrong place: it would repair one producer
and leave the guarantee broken for every other, when the guarantee is §8's and the
defect is in §8's population.

**Suppressing until the record is purged by retention.** Simpler to state — the
key is held for as long as the record exists — and rejected because it puts a
user-visible behaviour on a storage setting. Retention's default of seven days
would suppress a fact for a week after it perished, and `retention = None` would
suppress it forever, which is precisely the "suppressing duplicates forever"
hazard ADR-0130 §6 argues against when it makes the `off` sweep reach a record
held for an absent expiry. The declared expiry is the horizon that means
something.

**Making the dismissal itself refuse to end suppression only when it came from the
outbox.** A narrower repair, and it requires the store's `dismiss` to learn who is
calling it — a caller-identity parameter on a `NotificationStore` operation, so
that a `core` Protocol would encode which subsystem is on the other end. That
inverts golden rule 1's direction and makes ADR-0131's reuse of the dismissal into
a special case in ADR-0130's contract. The predicate approach keeps the seam
caller-blind.

**Doing nothing, and lowering the producer's interval instead.** Raised because it
is the operational reflex and it does not work. A longer interval reduces the
*number* of repeats and cannot remove them; with a lead window of fifteen minutes
and any interval shorter than it, at least one re-notice lands inside the window
by construction, and ADR-0132 §4 requires the lead to exceed the interval for
coverage. The failure is structural, not a tuning error.
