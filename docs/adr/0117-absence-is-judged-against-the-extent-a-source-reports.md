# 117. Absence is judged against the extent a source reports, not against the window the store keeps

- Status: Accepted
- Date: 2026-08-08
- **Decides `core` surface and implements none of it.** One **optional field** on
  `Attestation` in `core/types.py`, the small frozen value object it takes, and
  the operand of `ReadCoverage`'s containment predicate (§2, §9). **No new Protocol
  and no new member**: `Reader` is untouched, `MemoryStore` is untouched, and
  ADR-0115 §1's `ingest_reading` already carries the whole reading. What does move
  is that member's **obligation** — what a covered reading demotes — which is the
  semantics-only kind of contract change ADR-0116's header names, and which lands
  in both `MemoryWriter` implementations and the conformance suites together (§3,
  §9). Golden rule 5 and ADR-0015 §5 put a contract ADR in
  its own PR, merged and ratified before anything implements against it; the
  implementation is a separate later lane. **Its required review set is therefore
  adversarial *and* architecture**, even though the PR carrying it is prose only —
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface "when it is the ADR deciding that surface", and `scripts/ship.sh`
  fires its own architecture requirement on a diff touching `core/protocols.py` or
  `core/types.py`, which this diff does not. Both lenses are therefore run
  deliberately, as ADR-0110's own header records for the same reason.
- **Partially supersedes [ADR-0110](0110-a-covered-readings-absence-closes-a-window-and-a-clock-never-does.md)
  §3 and §10**, in the scope §3 and §9 below name and in no other: §3's condition 3
  changes its **carrier** — from the record's envelope validity window to the
  extent its attestation reports — and §10's buildability ruling acquires one
  further optional `core/types.py` field beyond the one it names. §3's other three
  conditions, its containment *rule*, its `ASSERTED`-unreachability argument and
  its ADR-0092 §4 error calculus all stand unchanged; §10's `core/protocols.py`
  clause stands unchanged. This is §10's own last sentence firing rather than being
  overridden — it routes a lane that concludes it needs more surface to "its own
  ratified ADR for it under golden rule 5", exactly as ADR-0115 §8 recorded for the
  writer member. The record is on that ADR's `Status` line and in its appended
  dated note, both landing in this change, which is the atomic pair ADR-0082 §7
  requires.
- **Appends a dated correction to ADR-0110 §4's converse-hazard argument, and
  supersedes nothing there** (§10). §4's two normative clauses — presence is the
  ingest's own answer, and one stored-nothing proposal suspends absence — are
  untouched and are relied on here. What is corrected is the unmarked sentence
  arguing that a spurious close is bounded because "identical text is the one case
  neither can miss", which is true of a **live** record and of no other, because
  `MemoryIngestor._detect_conflicts` reaches the store through `MemoryStore.search`
  and every `search` applies `Validity.live_at`.
- **Discharges ADR-0110 §9's fourth deferral for the calendar** — "Which sources
  should declare coverage, and what a bounded window means for each … is that
  reader's lane's, with the source in hand" — and fires that ADR's own **"Revisit
  if"**: "a reader is found whose entries have a position in the source's world
  that the envelope window cannot state (§3's condition 3 would then need a
  different carrier)". §5 and §6 answer the deferral; §2 and §3 supply the carrier.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-08**, not
  to its status on any later day. Where an ADR this decision composes with stands
  or stood `Proposed` on `main`, its ratification flip is its own lane's;
  `CONTRIBUTING.md` → "Trivial ADR edits" and ADR-0070 §1 both class that flip as
  recording a ratification rather than deciding one, so no clause cited here moves
  with it. Where a later ADR *changes* one of them, that change owes its own record
  and this ADR is owed a matching one.
- Refs #828, #827, #804, #639, #729.

## Context

ADR-0110 ratified a second closer beside `SUPERSEDE`: a reading that declares the
coverage it exhausted may retire a belief the reading omits, under four conditions
(§3). ADR-0115 gave the writer the seam that makes the reconciliation serialisable,
and the machinery landed. Nothing has ever used it.

**#827 is the finding, and it was made against a live hub rather than reasoned
about.** With the calendar source granted and ingesting on a 20-second interval,
an event removed from the `.ics` keeps its `ATTESTED` belief live indefinitely
across many successful reduced-calendar cycles. Two of §3's four conditions are
structurally unsatisfiable: `CalendarReader` declares no coverage, so
`MemoryWriter.ingest_reading` takes ADR-0115 §4's ruled no-coverage path; and
`CalendarReader`'s proposals set no envelope validity window, so every one of them
defaults to fully open — a window ADR-0110 §3's own containment rule says no
bounded coverage contains. Both halves behaved exactly as their ADRs say. The
composition is a mechanism with **zero reachable producers**.

ADR-0110 §9 anticipated a reader lane closing that gap and deferred the choice to
it, "with the source in hand". This is that lane, and the source in hand does not
fit.

**The calendar is a forward-looking source, and that turns out to be the whole
problem.** Most of what a calendar reports has not happened yet: `CalendarReader`
resolves a window of `[read_at - calendar_window_past, read_at +
calendar_window_future)`, whose defaults are one day back and **seven days
forward** (ADR-0093 §7a). The beliefs it proposes are the retrieval route for
calendar content by ADR-0096 §5's explicit design — the facet carries three scalars
and deliberately no entry text, on the ground that "the same read's proposals
already carry the occurrences into memory as `ATTESTED` beliefs". So "what is on my
calendar on Thursday" is answered from beliefs about entries that lie in the future.

**The envelope validity window is already spoken for.** ADR-0045 §6 makes it a
read-time filter: a record is returned by `get` and `search` only where
`Validity.live_at(now)` holds at both ends. ADR-0110 §3 then asks a producer to
bound that same window so it "states a position in the source's world". For a
source whose entries lie ahead of the read, those two jobs give the field opposite
instructions, and the collision is not a matter of degree — §1 below shows it
disables the mechanism outright and takes the fold down with it.

**One force against the answer, named early.** ADR-0045 §2 placed the window on the
envelope rather than on `Provenance` and gave a reason that reads directly on this
decision; ADR-0046 §5 records that ADR-0045 "weighed and *avoided* the blast radius
of adding envelope fields"; and ADR-0045 §10 already files one unreconciled
overlap between two temporal notions on a record. A decision that adds a further
producer-set interval to `core` is spending against all three, and §9 prices it.

## Decision

### 1. The envelope window cannot carry a forward-looking source's position, and the reason is mechanical

This section states no obligation. It is the finding the rest of the ADR is built
on, and it is written out because every alternative in §Alternatives fails at one
of these three points and would otherwise look reasonable.

`Validity.live_at` gates **three** things, not one, and the third is the one
ADR-0110 §3 did not price:

1. **Retrieval.** `MemoryStore.get` and `MemoryStore.search` return only live
   records (ADR-0045 §6).
2. **The absence enumeration.** ADR-0110 §6 routes the reconciliation through
   `MemoryStore.list_beliefs`, which applies the same predicate.
   `MemoryIngestor._absence_candidates` says so in as many words — "a closed or
   **not-yet-open** window and an expired record are gone before this sees them" —
   and ADR-0110 §3's own first clause is written over "a **live** record".
3. **Conflict detection.** `MemoryIngestor._detect_conflicts` finds the records a
   proposal might fold onto by calling `MemoryStore.search`, so a record that is
   not live is not a conflict candidate.

Give a calendar proposal the envelope window ADR-0110 §3 asks for — the
occurrence's own span, which is the only entry-anchored interval the source offers
— and all three fire at once for every entry that has not started yet:

- **The record is not retrievable**, which removes the capability ADR-0096 §5 built
  the proposals to serve. A meeting three days out cannot be searched for until it
  begins.
- **The record is never an absence candidate**, because `list_beliefs` skips it. So
  a **cancelled future meeting — #639's motivating case — is never demoted**, and
  the mechanism this ADR exists to reach is delivered dead.
- **The record is invisible to conflict detection**, so the next read's identical
  proposal finds no conflict, `DefaultMemoryPolicy` returns `ACCEPT` ("sufficient
  confidence and no conflict"), and `MemoryIngestor._apply` installs it at a
  **freshly minted** id. At the cadence #827 observed that is thousands of duplicate
  beliefs per future entry per day, none of which is ever retrievable and none of
  which is ever demotable.

The third is the one that matters most, because it falsifies ADR-0110 §4's own
safety argument rather than merely inconveniencing a lane. §4 bounds the converse
hazard — a present, unchanged entry spuriously closed — by observing that an
unchanged re-report always folds: "identical text is the one case neither can
miss." That is a statement about **retrieval**, and retrieval cannot see a record
whose window has not opened. §10 records the correction where a later lane will
find it.

**The corpus already knew a future-dated producer window was hazardous**, in the
one place it could not be avoided: `_supersede` overrides whatever `validity` a
proposal carries, on the stated ground that "a proposal with a producer-set closed
or future-dated window must not leave the store with the target retired and the
correction already hidden or **not yet live** — which would be no live belief at
all." That is this ADR's finding, met once at a different seam and repaired there
by discarding the producer's window.

**And the clock-anchored repair is unsound, not merely inelegant.** The obvious
escape is to anchor the window to the read instead of to the entry —
`[read_at, read_at + calendar_window_future)`, refreshed by each fold. It restores
liveness, it survives the sliding coverage, and it demotes a removed entry
correctly. It also destroys condition 3. A record whose window says "from when we
read to our horizon" is contained in the *next* read's coverage no matter where its
entry actually lies, so containment stops discriminating — and an entry that merely
scrolls out of the **past** edge of the window, still present in the `.ics`, is
absent from the next reading, contained by it, and **retired as though deleted**.
That is precisely the outcome ADR-0110 §2 built coverage to prevent: "an entry
absent from a reading either was deleted from the source or was never inside the
slice the reader looked at." Condition 3 is the clause that separates them, and a
read-anchored window makes it a tautology. §Alternatives records the rest of its
costs.

### 2. What a source reports about where an entry lies is producer testimony, and it sits beside the attestation

> **Normative.** A producer may state, for a belief it reports, the **extent** of
> that belief's subject in the reporting source's own world: a half-open
> `[from, until)` pair of **`UtcInstant | None`**, `None` at either end meaning
> unbounded, and both-set implying `until > from`. It is carried as an **optional**
> field on `Attestation` in `core/types.py`, and its absence means the producer
> states no extent.

> **Normative.** An extent states **where the reported entry lies**, and a producer
> may declare it only where that is true of the entry it is reporting. It is never
> trimmed to fit a coverage, never widened past what the source says, and never
> derived from the read's own bound or from the reader's configuration.

> **Normative.** Declaring **no** extent is always available and is always safe: a
> producer that cannot express an entry's extent declares none. No producer
> constructs a degenerate or inverted extent, and no source shape may make stating
> an extent raise.

**Why beside the attestation and not on the envelope.** ADR-0045 §2 drew this exact
line when it placed the validity window, and it decides this one the other way. The
window "is a lifecycle property of *the record's life in the store*, set
operationally by the applier"; putting it on `Provenance`, "whose every other field
is set by the *producer* of the belief, would mix two authorships." An extent is the
pure case of the other kind — the reporting source's own statement about the thing
it reported, of the same class as `reported_by` and `reported_at` beside it — so it
belongs where the producer-set facts are, and asking the operational axis to carry
it is the authorship mixing §2 refused, arriving from the other direction.

**`Attestation` rather than `Provenance`, because that is where the only consumer
can reach it.** ADR-0110 §3's condition 1 already keys on
`Provenance.attestation.reported_by`, and an attestation is present exactly when the
band is `ATTESTED` (ADR-0092 §1). Placing the extent inside the same value object
puts conditions 1 and 3 on one object and makes §3 **structurally unreachable**
outside the attested band rather than excluded by a rule — the stronger form §3
itself prefers, citing ADR-0080 §2 for the same preference. It is also the
conservative placement under ADR-0046 §5's discipline: no non-attested producer has
a consumer for an extent, and widening later is additive.

**Optional does not reopen ADR-0092 §2's half-state argument.** That section made
`reported_by` and `reported_at` both required inside one optional slot because they
are two halves of one answer, and either alone renders a half-answer to the user.
An extent is not a half of that answer; it is a separable third fact whose absence
is meaningful and legible — "this source states no position for this entry" — and
which nothing renders. Making it required would break every existing construction
site and every stored record to avoid a `None`, the trade ADR-0093 §3 refused for
the facet half, ADR-0109 §2 refused for `last_confirmed_at`, and ADR-0110 §2 refused
for coverage itself.

**Mirrored, not reused, and for ADR-0110 §2's own reason.** The shape is
`Validity`'s and the shape is deliberately all it borrows. §2 declined to name
coverage with `Validity` because "the two say different things about different
subjects", and an extent is a third subject again: a `Validity` is our window on a
belief we hold, a `ReadCoverage` is a claim about the read we performed, and an
extent is the source's claim about where the reported entry lies. Naming two of
them with one type would put a record's operational window and its source's
testimony in one annotation, on one record, one field apart.

**The domain and the invariant are pinned here and the spelling is not**, which is
ADR-0110 §2's disposition of the same question and ADR-0103 §9's test applied: two
lanes reading an extent as instants and as dates or source cursors give different
answers to §3's containment question while each claiming compliance, so the domain
is decided; a second implementation choosing another field name has renamed
something rather than decided something.

### 3. ADR-0110 §3's containment is evaluated against the extent

> **Normative.** ADR-0110 §3's condition 3 is read as: **the record's attestation
> declares an extent `E`, and `E` lies wholly within the reading's coverage `C`.**
> A record whose attestation declares no extent satisfies condition 3 for no
> reading and is never absence-demotable. Conditions 1, 2 and 4 are unchanged, and
> a close still requires all four.

> **Normative.** The containment rule itself is unchanged in content and is
> restated here only with its operand corrected: `E = [ef, eu)` lies wholly within
> `C = [cf, cu)` iff **`cf` is `None` or (`ef` is not `None` and `ef >= cf`)** and
> **`cu` is `None` or (`eu` is not `None` and `eu <= cu`)**. An unbounded extent end
> is contained only by an unbounded coverage end on the same side.

Everything ADR-0110 §3 argued for condition 3 survives the change of carrier, and
that is the test of it. "A record whose window is fully open states no position in
the source's world" becomes a record whose attestation declares no extent, and it is
still never absence-demotable. "A record whose producer bounded its window states
where in the source's world it lives, and a reading that exhausted that region and
did not find it has observed something" is now stated by the field whose only job is
to say so. What has gone is a coincidence — that the interval saying *where the
entry is* was also the interval deciding *whether the record is readable* — and with
it every consequence §1 traced.

**Nothing else about the close moves.** ADR-0110 §5's retirement obligations, its
single close instant and its atomicity over the write set; §5a's serialisation
prerequisite, which ADR-0115 satisfied; §6's per-record justification and its
`list_beliefs` enumeration; §4's presence definition and its stored-nothing
suspension — all are used exactly as ruled, and this ADR adds nothing to them and
subtracts nothing from them.

**The consumers that change are both writers, and they change together.**
`ReadCoverage`'s containment predicate is stated over the extent rather than over a
`Validity`. Two implementations call it, because ADR-0115 §1 made the reconciliation
a `MemoryWriter` obligation rather than one class's habit:
`MemoryIngestor._absence_candidates` and the canonical `FakeMemoryWriter` in
`ai_assistant.testing`, which implements `ingest_reading` and runs its own §3
selection — duplicated rather than imported, as golden rule 1 requires of a fake in a
different subsystem. Changing one and not the other is not a partial implementation
but a divergence: the fake would keep demoting on the envelope window while the real
writer demoted on the extent, and the shared suite would be driving two different
rules while reporting one.

> **Normative.** The change of operand lands in **both** `MemoryWriter`
> implementations and in the shared `MemoryWriter` conformance suite as one unit of
> work, never in one of them alone — the triad discipline `CONTRIBUTING.md` →
> "Adding a Protocol" states for a contract, applied to a contract obligation that
> already has two implementations.

Whether `core` expresses the predicate as a changed parameter type or as a second
predicate beside the existing one is spelling and is the implementing lane's, subject
to there being exactly **one** containment rule in exactly one place — the "one rule,
one place" discipline `Validity.live_at` and `ReadCoverage.contains` already keep.

### 4. The envelope validity window stays operational, and a producer never sets one to obtain a demotion

> **Normative.** A producer does not bound a record's envelope validity window in
> order to make the record absence-demotable, and no reader is required to set one.
> The window remains what ADR-0045 §2 made it — the record's operational life in
> the store — and ADR-0080 §5's ruling that a producer-set `valid_from` "stays
> settable" is untouched and neither widened nor relied on here.

> **Normative.** No implementation of this decision may make a belief's presence on
> the read path depend on when it was last read. A belief leaves the read path on a
> warranting event and on nothing else (ADR-0110 §1).

The second clause is a guard rail rather than a new rule: it restates ADR-0110 §1's
spine at the one seam where a repair that violates it is attractive and would look
like producer testimony. A window whose end is a horizon measured from the read is a
belief that disappears because time passed and no one looked, which is the mechanism
§1 legislates against wearing the costume of the mechanism §1 permits. This ADR does
not amend §1, does not narrow it, and does not seek an exception to it; it removes
the pressure that was pushing against it. §Alternatives records what taking that
route would have cost.

**What this buys, stated plainly, because it is the user-visible half.** Under this
ruling a lapse in reading does nothing at all. If the hub does not read the calendar
for a week, no belief is retired, no belief is hidden, and the assistant answers
from what it holds — stale where the source has moved on, and corrected by the next
reading that arrives, because ADR-0092 §4 makes an attested belief re-reportable.
That is the correct failure direction: a wrongly retained belief is repaired by a
later read, and a wrongly retired one under a clock-driven rule would not be.
Demotability also stops depending on how often the scheduler runs, which a
read-anchored window would have made it depend on silently.

### 5. The calendar's coverage is the interval it resolved, and an unaccounted read declares none

> **Normative.** `CalendarReader` declares a coverage of `[read_at -
> calendar_window_past, read_at + calendar_window_future)`, using the same saturated
> edges the read's own window was computed with, so both ends are always
> representable instants.

> **Normative.** A reader declares a coverage only where the read **accounted for**
> every entry the source held inside it. An entry the source held there which the
> read could not interpret — skipped rather than resolved — leaves the read
> unaccounted over that interval, and such a reading declares **no coverage**.
> Declining to emit an occurrence the source itself says does not occur is not a
> skip.

The first clause is the interval `occurrences_in_window` is asked to resolve, and it
is honest for the reasons ADR-0110 §2 established rather than any this reader
supplies: ADR-0093 §5 enforces a bound "by **refusing**, never by truncating" and §8
makes a read that cannot complete raise, so a `SourceReading` that exists is a read
that reached its whole window; and `occurrences_in_window` applies the entry cap
**before** the skip rule, which the module records as load-bearing precisely so that
"a source that busts its cap cannot be turned into a successful 'your calendar is
clear'". It is not widened: it is what the read exhausted, never what the reader was
configured to cover, which is ADR-0110 §2's never-widened discipline.

**The second clause is the one this lane owes, and it is grounded rather than
cautious.** ADR-0093 §7b skips an entry a parseable source contains but this reader
cannot interpret — a component with no usable `DTSTART`, an `RRULE` that will not
parse, a series whose extent cannot be established because two masters share a
`UID` or an override's form is opaque — and `CalendarReader` skips an occurrence
whose `DTSTAMP` is absent, because ADR-0092 §3 permits no substitute for a report
time the source did not make. Each of those is an entry the source **does** hold
inside the read's interval and the reading does not account for. Letting such a
reading warrant an absence would close windows on a false warrant: §3's warrant is
that the source was read to exhaustion over the region and did not report the entry,
and here the source did report it.

**The decisive half is that the close would not be recoverable.** ADR-0110 §3's
entire error calculus is ADR-0092 §4's — the attested band is on the recoverable
side because a wrongly closed window "is re-proposed by the next scheduled read". An
entry the reader cannot interpret is **not** re-proposed by the next read, or the
one after; it stays uninterpretable until the source is repaired. So a close on that
absence sits outside the calculus §3 rests on, and refusing it is applying §3's own
ground rather than adding caution to it.

**It is deliberately coarse, and it is coarse in the same shape §4 already chose.**
One skipped entry withholds coverage for the whole reading, exactly as one
stored-nothing proposal suspends absence for the whole reading under ADR-0110 §4.
The alternative is a coverage that is a *set* of intervals with the uninterpretable
entries punched out, and ADR-0110 §2 pinned coverage to a single half-open pair; a
set-valued coverage is a different decision, made by a different ADR, for a
mechanism that has yet to run once. §11 files the cost and names its revisit
condition.

### 6. The calendar's extent is the occurrence's own span

> **Normative.** For each occurrence it proposes, `CalendarReader` declares an
> extent of `[occurrence.start, occurrence.end)` — the occurrence's own resolved
> span, in UTC, exactly as the window decision was made on it.

> **Normative.** Where that span is not expressible as an extent — an occurrence
> whose `start` and `end` coincide — the proposal declares **no** extent. It is
> proposed as it is today and is simply never absence-demotable; nothing about the
> shape raises, and nothing about it is skipped.

The span is entry-anchored, stable across reads, and states exactly what §3 wants
stated: where in the calendar's world this entry lies. Two shapes need saying out
loud, because both are reachable from a conforming `.ics` and both are places a
later lane could invent a repair that breaks something.

**The zero-duration entry declines the extent, and must never raise.** ADR-0093 §7b
gives a date-time `DTSTART` with no end an instantaneous occurrence, and
`_occurrences` carries a separate membership arm for it because "a half-open
interval of zero width contains nothing". An extent with `until == from` is refused
by §2's invariant — for `Validity`'s reason, that an interval which admits no
instant would be contained by every coverage and would make such a record demotable
by any reading at all, which is the unsound direction. So the honest value is none,
and §2's third clause is what makes that safe: an instantaneous reminder is
proposed, retrievable and folded exactly as it is today, and only its
absence-demotability is withheld. A reader that instead widened the span by an
invented epsilon to make it representable would be stating an extent the source did
not give, which §2 forbids.

**The occurrence that straddles a window edge needs no rule, and must not be
given one.** `_occurrences` admits an occurrence that **overlaps** the window
rather than one that starts inside it, and ADR-0093 §7b decided that deliberately —
membership on the start instant alone "would make an event that began before the
window and is still running permanently unreachable by every future run". Such an
occurrence's extent is not contained in the coverage, so it is proposed, retrievable
and folded, and it is not absence-demotable. That is the correct answer arriving
from §3's containment rule with nothing added: the reading did not exhaust the
region that entry occupies, so its absence from a later reading would prove nothing.
A reader that trimmed the extent to the window to obtain containment would be
manufacturing a warrant, which is why §2's second clause names trimming beside
widening.

**The report time is untouched.** `Occurrence.reported_at` remains the entry's
`DTSTAMP` and remains what `Attestation.reported_at` carries; the extent is a
different fact about a different thing, and neither is derived from the other. An
entry reported on Monday about a meeting on Thursday has both, and they disagree by
design.

### 7. The fold, the facet and the read path are untouched

Beyond §3's change of operand in the two writers, no change to the fold is required,
and the reason is worth recording because a reader of this ADR will reasonably ask
whether the extent survives one.

**It does, on both arms, with no change to `_merge`.** On the ordinary `REINFORCE`
arm the survivor is the incoming record wearing the target's id, and its
`Provenance` is rebuilt with `attestation=incoming.provenance.attestation` — so the
incoming reading's extent replaces the stored one, which is right: the newest report
is the one that says where the entry now lies, and a rescheduled entry's extent
moves with it. On ADR-0103 §6's corroboration arm — a `DERIVED` record folded onto an
attested one — the survivor keeps the **target's** attestation, and therefore the
target's extent, which is equally right: a derived record carries no attestation, has
no extent to contribute, and ADR-0103 §6 withholds the incoming record's belief
properties from the survivor anyway.

**Retrieval is unchanged in every respect.** Nothing here filters, ranks, weights or
orders anything: the extent reaches no read path, is read by exactly one consumer,
and is compared against exactly one value. ADR-0112's ruling that currency never
ranks is untouched, and ADR-0072 §5 acquires no exception.

**The facet is unchanged**, and the asymmetry ADR-0096 §5 protects is preserved. The
facet still counts occurrences the proposals skip; §5's withheld-coverage clause acts
on the **reading's coverage** and never on the facet, so a reading whose coverage is
withheld still contributes its situational half exactly as before. Nobody should
"fix" that by making the facet skip the same entries, and nothing here asks them to.

**`SourceReading.coverage` is unchanged.** ADR-0110 §2's field, its optionality and
its meaning stand as ratified; ADR-0115 §4's no-coverage path — "where
`reading.coverage` is `None` nothing is reconciled" — is what §5's second clause
deliberately routes an unaccounted read into, so that clause needs no new mechanism
at all.

### 8. What generalises, and what is left to the next source

> **Normative.** The rule this ADR states is general: **where a source's entries
> have a position in that source's world, that position is producer testimony and is
> carried by the extent (§2); it is never carried by the record's envelope validity
> window.** It binds every producer that opts into ADR-0110 §3, not only the
> calendar.

What is **not** general, and is not decided here, is whether any particular second
source has entries with a position worth stating, or what its coverage is. ADR-0110
§9's deferral is discharged for the calendar and stands unchanged for everything
else: that judgement belongs to the lane that holds the source, which is the lane
that can say whether "absent" means anything for it at all. A source whose entries
have no position — a settings export, a contact list — declares no extent, is never
absence-demotable, and is not thereby deficient.

The property that made the calendar the hard case is that it is **forward-looking**:
its entries lie ahead of the read, so a position-stating envelope window would not
yet be open. A backward-looking source would have hit the same collision from the
other side — a position-stating window already closed, hence equally invisible — so
the finding is not about the future in particular but about the envelope window
having a second job. §2's placement removes it for both.

### 9. The contract surface owed

**New surface in `core` — a breaking change (golden rule 5), implemented by a later
lane:**

- **`core/types.py`** gains **one optional field** on `Attestation` carrying §2's
  extent, and the small frozen value object it takes: a half-open interval of
  `UtcInstant | None` with `None` meaning unbounded and a both-set ⇒ end-after-start
  invariant, mirroring `Validity`'s shape and *not* reusing its name. Optional with a
  `None` default, so every existing construction site, every stored record and every
  fixture stays valid — ADR-0093 §3's additive pattern, and ADR-0109 §2's test for a
  `core` validator ("does it refuse something that already worked") comes out the
  same way. Records already in a store decode with no extent and are therefore never
  absence-demotable, which is the safe default and needs no migration.
- **`ReadCoverage`'s containment predicate** takes the extent as its operand (§3).
  Its rule is unchanged; whether the change is a parameter type or a second
  predicate is spelling, subject to one rule in one place.
- **`core/protocols.py`** gains **no Protocol and no member**. `Reader` is untouched —
  the extent rides on the proposals it already returns. `MemoryWriter` gains nothing:
  ADR-0115 §1's `ingest_reading` already carries the whole reading, which is the seam
  ADR-0110 §5a required. `MemoryStore` is untouched: §5's closes go through
  `write_atomic` and §6's enumeration through `list_beliefs`. **`ingest_reading`'s
  signature does not move and its obligation does**, which is the semantics-only shape
  of a contract change ADR-0116's header names: what a covered reading demotes is part
  of that member's contract, so the docstring stating ADR-0110 §3's conditions is
  corrected, both implementations move, and the conformance clause below binds them.
- **`MemoryDecisionKind`, `MemoryDecision` and `MemoryPolicy` are untouched**, per
  ADR-0110 §5: an absence-close carries no proposal and reaches no policy.

> **Normative.** The mechanism this ADR decides is buildable on the `core` surface
> that exists, plus ADR-0110 §10's optional field on `SourceReading` and this
> section's optional field on `Attestation` with its value object, and it authorises
> no other `core` change. A lane that concludes it needs a Protocol member, a second
> temporal axis on `MemoryBase`, or a change to any read path owes its own ratified
> ADR for it under golden rule 5, and may not read this one as pre-authorising it.

**What is genuinely the implementing lane's**: the spelling of the field and its
value object; `CalendarReader`'s construction of both values; the `FakeReader`
coverage knob and the extent it needs alongside it (#804); and what the shared
`Reader` conformance suite pins. **What is not the lane's**, because two lanes could
there make incompatible choices and both claim compliance (ADR-0103 §9's test), is:
§2's domain, invariant and placement; §3's operand and containment rule; §4's two
clauses; §5's coverage interval and its accounted-for condition; and §6's span and
its declines-rather-than-raises rule.

**The conformance question is answered rather than deferred**, because unlike
ADR-0110 §10 this ADR has both a producer and a driven suite in hand, and because the
suite fails **silently** if it is left alone. ADR-0115 §7 allocates the work already:
the shared `MemoryWriterContract` pins §4's no-coverage arm, ADR-0110 §4's suspension
clause and §6's mid-call observation, while "each of ADR-0110 §3's other conditions
independently prevents a close" is pinned by each implementation's own tests. That
allocation is untouched. What moves is the fixture underneath it.

**Every one of the shared suite's covered cases asserts a negative** — that nothing
closed — and each is meaningful only because its stored record is *otherwise*
demotable. Today that record earns its demotability from a bounded envelope validity
window. Under §3 it earns nothing: it would declare no extent, be demotable by no
reading at all, and every one of those assertions would keep passing while proving
nothing. A suite that goes green for the wrong reason is worse than one that fails,
which is why this is ruled here rather than left to the lane to notice.

> **Normative.** The shared `MemoryWriter` conformance suite's demotable fixture
> earns its demotability from a declared **extent** contained in the reading's
> coverage, not from a bounded envelope validity window. A suite in which the
> negative cases would still pass with the fixture's extent removed does not satisfy
> this clause.

> **Normative.** Each `MemoryWriter` implementation's own tests state §3's condition 3
> over the extent — ADR-0115 §7's existing allocation, with the carrier corrected —
> and include the case that a record whose attestation declares **no** extent is
> demoted by no reading, whatever its envelope validity window.

> **Normative.** The shared `Reader` conformance suite states that a reading's
> declared coverage and a proposal's declared extent are both statements about the
> read that was performed. A fake that synthesises either from its own configuration
> models exactly what §2 and ADR-0110 §2 forbid, so both are scripted by the test
> author, as #804 already asks for coverage.

`MemoryStore` acquires no obligation: it stores and returns a record whose attestation
carries one more optional field, and no read path consults it.

### 10. What this records against earlier ADRs

The judgement ADR-0082 §1 requires, clause by clause, by applying ADR-0070 §1's test
to each earlier ADR's text: would a reader holding only that ADR now act differently,
or read one of its clauses more widely than it now holds?

**ADR-0110 §3 — a record is owed, and it is a partial supersession.** Condition 3
names the carrier in terms — "the record's own envelope validity window lies wholly
within `C`" — and §3's second normative block states the containment rule over "the
record's window `[vf, vu)`". A reader holding only ADR-0110 builds a reader that
bounds envelope windows, and after this ADR that reader is wrong: it would produce
the three failures §1 traces. That is ADR-0070 §1's test met, and its answer is
supersession, scoped to the carrier. The **rule** is untouched, conditions 1, 2 and 4
are untouched, the `ASSERTED`-unreachability argument is reproduced rather than
relaxed (§2 strengthens it, since the extent lives inside the attestation), and the
ADR-0092 §4 recoverability calculus is not merely kept but used as this ADR's own
ground in §5. §3's Consequences sentence — that a reader lane "owes two things — a
coverage declaration and bounded envelope windows on the records it proposes" — falls
under the same scope and is superseded with it.

The alternative reading was taken to review before being set aside: that §3's clause
is satisfied by *any* bounded window and this ADR merely picks one, so nothing is
narrowed. It does not survive the text. §3 names the envelope window, ADR-0110's
Consequences name it again, and §4 below asks producers **not** to bound it — a
reader holding both would be told opposite things by two ratified documents, which is
the state a supersession exists to prevent.

**ADR-0110 §10 — a record is owed, in one clause and no more.** Its normative clause
states the mechanism is buildable "on the `core` surface that exists plus §10's one
optional field, and it authorises no other Protocol change". This ADR adds a second
optional `core/types.py` field, so the buildability sentence stops being true as
written. Its `core/protocols.py` clause, its `MemoryDecisionKind` clause and its
routing sentence all stand — and the routing sentence is what this ADR is: a lane
that concluded it needed more surface brought its own ratified ADR, which is §10's
own prescription firing rather than being overridden, precisely as ADR-0115 §8
recorded when the same sentence fired for `MemoryWriter`. ADR-0110's `Status` line
accumulates this pair beside ADR-0115's in the form ADR-0070 §4 and
`docs/adr/template.md` require.

**ADR-0110 §4 — a dated note is owed, and not a supersession.** §4's two normative
clauses are untouched and are used here as ruled. What this ADR corrects is the
unmarked sentence in the surrounding argument — that a spurious close is bounded
because an unchanged re-report always folds, "identical text is the one case neither
can miss". Under ADR-0089 §3 unmarked text in a marked ADR "is read to determine what
a marked clause *means* and never supplies an obligation", so no obligation moves and
a reader holding §4 still builds the same thing. What that reader would carry away is
a false reassurance about a design this ADR forbids, so the correction is recorded
where it will be found: the fold's premise is that the target is **live**, because
`MemoryIngestor._detect_conflicts` reaches the store through `MemoryStore.search`.
An appended dated note is the corpus's shape for exactly this — recording against an
argument without touching a decision.

**ADR-0110 §1, §2, §5, §5a, §6, §7, §8, §9, §11, §12 — nothing owed.** §1 is held
rather than amended, and §4 above adds a guard rail restating it. §2's coverage, its
endpoint type, its invariant and its never-widened discipline are relied on
unchanged and extended by analogy to the extent, which is using a rule as specified.
§5's retirement obligations and §5a's prerequisite are untouched. §6's per-record
justification is what makes §5's coarse withholding harmless — a reading that
declares no coverage closes fewer windows and never a different one. §7's ADR-0093
§4 preservation is untouched: nothing here lets a reader propose an absence, and an
extent is a statement about an entry the reader **did** report. §8's lapse rule is
untouched and §4 above is its restatement at a new seam. §9's deferral is discharged
for one source, which is what a deferral is for. §11 and §12 are unaffected.
**Stacked additions and one discharge; no record owed.**

**ADR-0045 §2, §6 and §10 — nothing owed.** §2's placement argument is not
contradicted but applied: it is the ground for putting the extent with the
producer-set fields rather than on the envelope, and this ADR adds no envelope field,
so ADR-0046 §5's note that ADR-0045 "weighed and *avoided* the blast radius of adding
envelope fields" is respected rather than spent. §6's read semantics are relied on
unchanged and are the whole of §1's finding. §10's three deferrals — as-of retrieval,
the full transaction-time axis, and **reconciling `SemanticMemory.valid_until` with
the envelope window** — are carried forward untouched; §11 states expressly that the
third is not decided here, and the extent is not an answer to it. **Stacked addition;
no record owed.**

**ADR-0080 §2 and §5 — nothing owed.** §5's ruling that envelope `valid_from` "stays
settable" is neither relied on nor withdrawn: §4 above says producers need not set
one for this purpose, which leaves the permission exactly where §5 put it. §2's
"producer testimony" characterisation of a bounded window is untouched for the
producers that do set one. **No record owed.**

**ADR-0092 §1, §2, §3, §4 and §6 — nothing owed.** §1's iff is what makes §2's
placement structurally band-scoped. §2's half-state argument is answered in §2 above
rather than narrowed. §3's report-time rule is untouched and is the reason §5's
withholding clause exists. §4's recoverability is cited as the ground for §5 and read
no more widely than it holds. §6's minting rule is untouched. **No record owed.**

**ADR-0093 §4, §5, §7a, §7b, §8 and §10 — nothing owed.** §4's first sentence stands:
a reader still proposes no absence, and §5 above makes a reader *withhold* a warrant
rather than assert one. §5's refuse-don't-truncate and §8's raise-don't-return are
what make §5's first clause honest. §7a's figures and §7b's semantics — the overlap
membership, the zero-duration arm, the skip rule, the cap ordering — are used exactly
as ruled and §6 above is written to avoid repairing any of them. §10's `as_of`
protection is untouched; an extent is a statement about the reported entry, not a
reading-wide claim. **Stacked additions; no record owed.**

**ADR-0096 §5 and §6 — nothing owed.** The facet is untouched and §7 above states so,
including that a withheld coverage does not withhold a facet. **No record owed.**

**ADR-0115 §1, §4 and §7 — nothing owed.** §1's member carries the reading whole and
is exactly the seam this decision needs; its signature does not move, and what its
contract *means* moves only because ADR-0110 §3, which it references by number, has
been superseded there rather than here. §4's no-coverage path is what §5's second
clause routes into. §7 allocates the conformance work between the shared suite and
each implementation's own tests, and §9 above keeps that allocation exactly as ruled
while correcting the carrier the fixtures underneath it rely on — its clause "each of
ADR-0110 §3's other conditions independently prevents a close" cites those conditions
by number and stays true as written. Using a mechanism as specified is not amending
it. **No record owed.**

**ADR-0103 §6 and §9, ADR-0109 §5, ADR-0112 — nothing owed.** §6's corroboration arm
is relied on unchanged in §7 and gains no exception. §9's test is applied twice, in §2
and §9. ADR-0109 §5's selection is untouched. ADR-0112's ruling that currency never
ranks is untouched; nothing here reaches retrieval. **No record owed.**

### 11. What this ADR does not decide

- **Any second source's coverage or extent.** §8 states what generalises and stops
  there; ADR-0110 §9's deferral stands for every source but the calendar.
- **Whether a coverage may be a set of intervals.** §5's withholding clause is coarse
  because ADR-0110 §2 pinned coverage to one half-open pair. A per-entry coverage is a
  different decision with a different blast radius, and it has no consumer until this
  mechanism has run in production at all.
- **Reconciling `SemanticMemory.valid_until` with the envelope window.** ADR-0045
  §10's deferral is carried forward exactly as written. The extent is not that
  reconciliation and must not be read as taking a position on it: `valid_until` is a
  per-kind, content-declared world-expiry set by the belief's author, and an extent is
  a per-attestation statement by a reporting source about where a reported entry lies.
- **Retention, eviction and store size.** A record whose entry has passed stays live
  and stays retrievable exactly as it does today; nothing here expires anything.
  ADR-0007 §5's deferral and ADR-0103 §1's framing both stand, and a closed window is
  still not a deletion.
- **As-of retrieval and the second temporal axis.** ADR-0045 §1 and §10 deferred both
  for want of a consumer and this ADR creates none.
- **A threat model for a producer that lies about its extent.** ADR-0095 §6 files the
  seam's threat model as its own parked question, and ADR-0110 §9 declined to open it
  for coverage. The honest bound is the same one and is now stated twice: an extent is
  a producer's assertion about what it reported, and §3's other three conditions are
  what stop a wrong one from reaching anything but that producer's own records.
- **Whether the scheduler should surface a withheld coverage.** §5's second clause is
  silent to a user by construction. Whether an operator-facing surface reports "this
  source's calendar has an entry we cannot read, so absence is suspended" is the
  scheduler and inspection lanes', and #828's batch does not open it.

## Consequences

- **The absence close acquires its first reachable producer**, and the path #827
  found unreachable becomes exercisable end to end: a granted calendar source
  ingests, an event removed from the `.ics` is retired by the next covered reading,
  and the raising-read and no-coverage arms keep behaving as ADR-0110 §3 and
  ADR-0115 §4 rule.
- **`core` grows one optional field on `Attestation` and no Protocol member**, which
  is the cheapest shape this decision was available in once §1's finding is accepted.
  The alternative that costs less surface costs correctness instead, and is priced
  below.
- **Every calendar belief stays retrievable exactly as it is today.** The change is
  additive at the producer and invisible at every read path, which is the property
  that makes it safe to land under a mechanism that has never run.
- **ADR-0110 §1 is held rather than spent.** No belief leaves the read path because
  time passed; demotability does not depend on the scheduler's cadence; and a hub
  that has not read for a week retires nothing.
- **A calendar the reader cannot fully interpret loses absence-demotion silently**,
  for as long as the unreadable entry is inside the window. That is the deliberate
  cost of §5's second clause and it is the safe direction, but it is silent, and the
  revisit condition is named below.
- **An instantaneous entry and an entry straddling the window edge are never
  absence-demotable.** Both are proposed, retrievable and folded as they are today;
  only the demotion is withheld, in each case because the reading did not observe
  what a close would have to rest on.
- **The implementing lane owes**: the field and its value object with the additive
  migration story; `CalendarReader`'s coverage and extent; the `FakeReader` knobs
  (#804) and what the shared `Reader` conformance suite pins; the change of operand in
  **both** `MemoryWriter` implementations — `MemoryIngestor` and the canonical
  `FakeMemoryWriter` — together with the `MemoryWriterContract` fixture §9 rules on
  and each implementation's own condition-3 tests; and the end-to-end regression #827
  asks for. It is one lane, after this ADR merges and is ratified, and it is larger
  than the one this ADR's own lane was first briefed as.
- **#827, #804 and #639 close with that lane**, not with this one: this ADR decides,
  and closing an issue on a decision that has not been built is the bookkeeping
  ADR-0110 §11 avoided for the same pair.
- **Revisit if** a source is found whose entries have a position that a single
  half-open interval cannot state (a recurring entry's whole series, say, rather than
  one occurrence — the extent would then need a different shape, not a different
  home); if real calendars are observed to carry uninterpretable entries routinely
  enough that §5's withholding suppresses demotion in practice rather than
  exceptionally (a set-valued coverage, deferred in §11, is that lane's decision); or
  if a producer outside the attested band is ever found to need an extent, which
  would move the field from `Attestation` to `Provenance` or to the envelope and owes
  its own ADR under §9's clause.

## Alternatives considered

- **Give the calendar's proposals the occurrence span as their *envelope* validity
  window**, which is what ADR-0110 §3 asks for on its face and what #827 offered as
  the natural candidate. Rejected in §1, on three findings verified against the tree
  rather than reasoned about: a future entry's record is not retrievable, which
  removes the capability ADR-0096 §5 built the proposals to serve; it is not
  enumerated by `list_beliefs`, so a cancelled future meeting — #639's own case — is
  never demoted and the mechanism ships dead; and it is invisible to
  `MemoryIngestor._detect_conflicts`, so every read installs a duplicate at a fresh
  minted id and ADR-0110 §4's converse-hazard argument fails with it.
- **Anchor the window to the read: `[read_at, read_at + calendar_window_future)`,
  refreshed by each fold.** Rejected in §1 and §4. It restores liveness and it does
  demote a removed entry, which is what makes it dangerous rather than obviously
  wrong. But it makes containment a tautology — a record whose window is "from our
  read to our horizon" is contained by the next reading's coverage wherever its entry
  actually lies — so ADR-0110 §3's condition 3 stops discriminating, and an entry that
  merely scrolls out of the **past** edge of the window is retired as though deleted.
  It also makes every belief vanish from the read path `calendar_window_future` after
  the last successful read, which is ADR-0110 §1's forbidden mechanism arriving as
  producer testimony; and an outage longer than that horizon permanently duplicates
  the whole calendar, because the un-live originals are invisible to conflict
  detection and un-demotable forever after. Ruling this in would have required
  amending §1's scope explicitly, and §1 is right.
- **Put the extent on `MemoryBase`, beside `validity` and `expires_at`.** Rejected in
  §2. It is the placement with the widest blast radius — ADR-0045 weighed and avoided
  exactly that, and ADR-0046 §5 records it — and it buys nothing: ADR-0110 §3's
  condition 1 confines the mechanism to the attested band, so an extent outside an
  attestation has no consumer, which is ADR-0046 §5's own ground for deferring
  surface. Putting it inside `Attestation` also makes §3 structurally unreachable for
  other bands rather than excluded by a rule, which §3 itself prefers.
- **Put it on `Provenance` beside `last_updated` rather than inside `Attestation`.**
  Rejected in §2 on the weaker of the two grounds — it would be present on records
  that can never use it and would separate condition 1's field from condition 3's —
  but recorded because it is the closest call in this ADR, and because widening from
  `Attestation` to `Provenance` later is additive if a non-attested consumer appears.
- **Reuse `Validity` as the extent's type rather than mirroring it.** Rejected in §2.
  It costs no new class and it would let `ReadCoverage`'s predicate stand unchanged,
  which is genuinely tempting. It also puts a record's operational window and its
  source's testimony in the same annotation one field apart, which is the confusion
  ADR-0110 §2 spent a paragraph avoiding when it declined to name coverage with
  `Validity` — "the two say different things about different subjects" — and the
  third subject is no closer to the first than the second was.
- **Reuse `SemanticMemory.valid_until` as the extent's end.** Rejected in §11. It is
  one end rather than two, it exists on one kind rather than on every record a reader
  may propose, and using it would decide ADR-0045 §10's parked reconciliation between
  that field and the envelope window as a side effect of a reader lane — the shape
  golden rule 5 exists to stop.
- **Make the extent required on `Attestation`.** Rejected in §2: it breaks every
  existing construction site and every stored record to avoid a `None`, the trade
  ADR-0093 §3 refused for the facet half, ADR-0109 §2 refused for `last_confirmed_at`
  and ADR-0110 §2 refused for coverage. It would also force every attested producer to
  answer a question most of them have no answer to.
- **Let a reading with skipped entries declare coverage anyway, and accept the
  occasional wrong close.** Rejected in §5, and not on caution: ADR-0110 §3's whole
  error calculus is that a wrongly closed attested window "is re-proposed by the next
  scheduled read", and an entry this reader cannot interpret is not re-proposed by any
  read. The close would be effectively permanent, which puts it outside the calculus
  §3 rests on.
- **Punch the uninterpretable entries out of the coverage** — a set-valued coverage —
  so one bad `VEVENT` costs one entry's demotability rather than the reading's.
  Rejected in §5 and filed in §11: ADR-0110 §2 pinned coverage to a single half-open
  pair, so this is a change to that ADR's surface bought for a mechanism that has not
  yet run once.
- **Widen a zero-duration occurrence's extent by an epsilon** so it is representable.
  Rejected in §6: it states an extent the source did not give, which §2's second clause
  forbids, and it would be indistinguishable at the seam from the widening ADR-0110 §2
  exists to prevent. Declining the extent costs that entry nothing but its
  demotability.
- **Trim an edge-straddling occurrence's extent to the window** so it is contained.
  Rejected in §6, and it is the mirror image of widening a coverage: it manufactures
  containment by shrinking the testimony instead of stretching the claim, and it would
  close windows on entries the reading provably did not exhaust the region of.
- **Have the reader stop proposing occurrences that have already ended**, so that a
  span-based envelope window would never be stale. Rejected as scope and as harm: it
  changes what the reader believes rather than how absence is judged, it makes "what
  was on my calendar this morning" unanswerable, and it exists only to rescue an
  envelope carrier this ADR rejects for independent reasons.
- **Defer the whole question back to ADR-0110's authors as a revisit**, rather than
  deciding it here. Rejected because ADR-0110's "Revisit if" names this case and hands
  it forward rather than reserving it, and because the deferral has a cost that is now
  measured: leg 7's demotion path has no reachable producer at all until a reader lane
  opts in, and #827 is that fact.
