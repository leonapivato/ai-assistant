# 110. What closes a validity window without the user: a covered reading's absence, and never a clock

- Status: Proposed
- Date: 2026-08-06
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-06, not
  to its status on any later day.** Several of the ADRs this decision composes
  with stand `Proposed` on `main` and their ratification flips are their own
  lanes'; `CONTRIBUTING.md` → "Trivial ADR edits" and ADR-0070 §1 both class that
  flip as recording a ratification rather than deciding one, so no clause cited
  here moves with it. Where a later ADR *changes* one of them, that change owes
  its own record and this ADR is owed a matching one.
- **Decides `core` surface and implements none of it.** One optional field on
  `SourceReading` in `core/types.py` (§2) and a set of obligations on the writer
  boundary (§5). Golden rule 5 and ADR-0015 §5 put a contract ADR in its own PR,
  merged and ratified before anything implements against it; the implementation
  is a separate later lane. **Its required review set is therefore adversarial
  *and* architecture**, even though the PR carrying it is prose only — the reading
  ADR-0093's header records for the same reason, and ADR-0090 §5 and ADR-0091's
  header record in the opposite direction for ADRs that decided no surface.
- **Discharges [ADR-0093](0093-a-sensor-reads-a-source-and-proposes-what-it-read.md)
  §11's fourth deferral** — "Retracting an attested belief when its source stops
  reporting it", whose stated firing condition is "Fires with ADR-0092's override
  mechanism, whose id discipline it shares". ADR-0092 has merged, so the condition
  is met. [ADR-0095](0095-the-read-only-seam-is-a-reader-and-its-weight-stays-in-core.md)
  §6 names this decision as owed and files it as an issue; that issue is #639.
- **Discharges [ADR-0103](0103-confidence-is-two-quantities-evidence-and-currency.md)
  §3's deferred question** — "Whether lapsed currency may close a validity window
  is not decided here" — with the answer **no** (§8). §13 applies ADR-0070 §1's
  test to ADR-0103 §8's routing clause and finds it unmet.
- **Records a dated note on ADR-0093** and nothing else on any earlier ADR. §13
  makes the judgement clause by clause under ADR-0070 §1 and ADR-0082 §1,
  including for the two readings where the opposite answer is available:
  ADR-0093 §4's second sentence and ADR-0103 §8.
- Refs #112, #639, #729 (leg 7 fork 4), #631, #632.

## Context

[ADR-0045](0045-memory-records-carry-a-validity-window.md) gave the store a
non-destructive way to stop believing something: a record's validity window is
closed and the record retained, off `get`/`search` and present in `export`. Every
window that has ever closed since has been closed by one act — a `SUPERSEDE`,
which [ADR-0092](0092-an-attested-belief-names-its-source-and-a-user-assertion-retires-it.md)
§4 widened to reach the `ATTESTED` band and
[ADR-0079](0079-a-correction-resolves-every-conflict-it-is-shown.md) §1 made
total over the conflicts retrieval surfaced. Behind every one of them is a user
assertion or a producer's proposal: something arrived, and the system ruled on it.

Leg 7's fork 4 asks what may close a window when nothing arrived (#729). Two
cases are live and one issue's residue has to be adjudicated against the record.

**A cancelled meeting should stop being believed (#639).** ADR-0093 §4 forbids a
reader proposing an absence, and the refusal is correct: "a bounded read, a
truncated file, a permission error and a genuinely deleted entry are
**indistinguishable from the reading**", so a producer allowed to propose absence
"would retract the user's beliefs on the strength of a failed read, and the
failure would look exactly like success." ADR-0093 §11 deferred the underlying
need by name rather than dismissing it, and its firing condition has fired.

**Currency may lapse, and nothing says what a lapse does to standing.** ADR-0103
§2 split confidence into evidence-strength and currency; §3 ruled that currency
may decline and left "whether lapsed currency may close a validity window" open;
§4 ruled that a lapsed `ASSERTED` belief is re-confirmed with the user, never
eroded and never retired.
[ADR-0109](0109-the-confirming-instant-is-stored-and-the-fold-selects-it.md) §2
stored the confirming instant on `Provenance.last_confirmed_at` and §5 ruled how
a fold selects it, so a lapse is now a thing the system can compute rather than a
thing it can only describe.

**#112 is the issue this whole axis came from**, and its body predates
ADR-0045, ADR-0080, ADR-0092 and ADR-0103. It cites a `TODO.md` that no longer
exists (ADR-0015 removed the file) and proposes a design ADR-0045 largely took
and partly rejected. It has to be read as history and adjudicated against the
record rather than implemented.

**What makes these one decision rather than three.** The absence case and the
currency case are the same question asked from two directions — *what warrants
taking a live belief off the read path when no one asserted anything* — and they
have opposite answers for one reason, which is the finding this ADR turns on: one
of them is an observation and the other is arithmetic. A reading is an event. An
elapsed interval is not. Ruling them separately would have produced two ADRs
neither of which could state the principle that decides both, and #112's residue
is exactly the list of things that principle leaves open.

**One force against, named early.** ADR-0093 §4's refusal is the safety rule "the
whole seam turns on", and any decision that lets an absence close a window is
spending that safety. What makes it affordable is not confidence in readers; it
is that ADR-0093's *own* §5 and §8 already removed three of the four
indistinguishable cases from the seam, leaving exactly one for this ADR to
separate — and that separation costs a field, not a judgement call (§2).

## Decision

### 1. A window closes on a warranting event, and elapsed time is not one

> **Normative.** A validity window closes only on a **warranting event** — an act
> or an observation the system can name and date. The passage of time is not a
> warranting event: no lapse of currency, at any threshold, and no unknown
> currency, closes a validity window.

This is the spine, and everything below is either an application of it or a
boundary around it. It is not a new posture; it is the posture the corpus already
has, stated once so that a later lane cannot reach the other one by increments.
Every closer that exists names an event: ADR-0045 §4's `SUPERSEDE` names the
proposal that overturned the target, ADR-0080 §1's clamp names the producer's own
declared end, ADR-0092 §4 names the user's assertion. None of them is a schedule.

**The reason is the one ADR-0103 §4 gave for the band where it is sharpest, and
it generalises.** §4 refuses letting a clock retire an assertion because doing so
"would reach the same outcome through a mechanism with no signal at all, which is
worse, because nothing observed anything." The clause is about `ASSERTED`, and its
*reason* is not: a clock is no more of a signal about a calendar entry than about
a preference. What differs across bands is not whether time is evidence — it never
is — but what the system should do instead, which is §8.

**And a decay rate does not exist to trigger on.** ADR-0103 §5 defers "the
staleness threshold at which lapsed currency triggers §4's re-confirmation" to
leg 8's measurement, and §9 rules that every record written before ADR-0109 reads
as **unknown** currency and "never as current" — while equally refusing to read it
as stale, because that "would manufacture a decline from a rate nobody has
measured". A rule that closed windows on lapse would therefore have no number to
fire on and a store full of records it must not fire on, and the first
implementation to invent either would be inventing a decision. This is a reason
the ruling is *safe* to make now; §1's ground is that time is not evidence, and it
does not expire when leg 8 lands a number.

### 2. A returned reading is already complete; what it does not carry is its coverage

#639 offers, "as a starting point rather than a conclusion", that a *complete*
read — "one that succeeded, and whose bound was not reached, so nothing was
refused under ADR-0093 §5" — carries information a partial one does not. Read
against ADR-0093, the framing is right about which property matters and wrong
about which half is missing, and the correction is what makes this decision small.

**Completeness is not a condition an absence rule has to add, because ADR-0093
already guarantees it of every reading that exists.** Its §5 rules that "a bound
is enforced by **refusing**, never by truncating", and its §8 that a read "either
completes within its bound and returns a `SourceReading`, or **raises**", and that
"a read that cannot complete may not return what it managed to gather." So a
truncated file and a permission error do not produce a reading at all, and a bound
that was reached produces a `ReaderError` rather than a shorter reading. Of the
four cases §4 called indistinguishable — a bounded read, a truncated file, a
permission error, a genuine deletion — ADR-0093 itself removed the middle two from
the seam, and it did so in the same Decision that stated the problem.

What is left is exactly the pair §4's argument is really about: **a bounded read
and a genuine deletion.** An entry absent from a reading either was deleted from
the source or was never inside the slice the reader looked at. Nothing on
`SourceReading` says which, because nothing on it says what the slice was: it
carries `source`, `read_at`, `as_of` and `proposals`, and ADR-0093 §5 makes the
bound "a function of the clock, its configuration and the source's own content"
held entirely on the reader, where "a caller able to widen the read is a caller
able to defeat the bound".

> **Normative.** A reading warrants no absence unless it **declares its
> coverage**: the interval of the source's world the read exhausted, half-open,
> with `None` at either end meaning unbounded — the shape `Validity` already uses.
> It is carried on `SourceReading` as an **optional** field, and its absence means
> the reading declares no coverage and warrants no absence.

> **Normative.** A coverage declaration states what the read **exhausted**, and a
> reader may declare it only where that is true of the read it performed. It is
> never widened to what the reader was configured to cover, to what the source is
> presumed to hold, or to the reader's whole bound where the read stopped short of
> it — a read that stopped short raises under ADR-0093 §8 and declares nothing.

The field is optional for ADR-0093 §3's own reason, stated there for the deferred
facet half and applying unchanged here: `SourceReading` is built so that "a
reading that predates that field stays valid", and the alternative — a required
field — makes every existing reader's construction site a breaking change bought
to avoid a `None`. It is also the property that keeps this decision from being a
behaviour change on `main`: **no reader in the tree declares coverage, so no
window closes under §3 until a reader lane opts in.** ADR-0093 §4's refusal
remains the operative behaviour of every reader that exists, which is what ADR-0095
§6 predicted when it said that refusal "is the safe default and stays in force
until an ADR replaces it".

**Coverage is a fact about the read, not a claim about the source.** It is the
same class of fact as `read_at` — our own account of what we did — and it is
deliberately not the class ADR-0093 §10 protects `as_of` from becoming, which is a
claim only the source may make. A reader knows what it exhausted because it chose
the bound; it does not know, and may not assert, what the source contains.

### 3. When an absence closes a window

> **Normative.** A live record's validity window may be closed on its absence from
> a reading `R` **only where every one of these holds**, and it is closed on no
> other absence:
>
> 1. the record's `Provenance.attestation.reported_by` is `R.source` — the record
>    is one this source reported;
> 2. `R` declares a coverage `C` (§2);
> 3. the record's own envelope validity window lies **wholly within** `C` — the
>    record states a position in the source's world, and `C` exhausted it;
> 4. the record is **absent from** `R` in §4's sense.

**Condition 3 is what separates the bounded read from the deletion**, and it is
the whole content of the decision. A record whose window is fully open states no
position in the source's world; it cannot be inside any bounded coverage, so it is
never absence-demotable, and that is right rather than a gap — an unbounded
attested belief absent from a forward-looking read tells you nothing, because it
never claimed to be in the slice. A record whose producer bounded its window
states where in the source's world it lives, and a reading that exhausted that
region and did not find it has observed something.

The envelope window is the right carrier and no new field is owed for it. ADR-0045
§6 rules that a producer-set `valid_from` is "enforced, not assumed away … a
producer *may* [set it], and the store must honour the contract regardless";
ADR-0080 §5 answers #306's question — "whether envelope `valid_from` should ever be
producer-settable at all" — **"yes, it stays settable"**; and ADR-0080 §2 calls a
bounded window "producer testimony", building its whole clamp rule around
retiring one. A producer-set bounded window is a ratified thing this system
already knows how to retire, and asking a reader to set one for an entry that has
a shape is asking it to use a facility built for it.

**The consequence for a reader lane is stated rather than left to be discovered:
a reader that wants absence-demotion owes both halves** — a coverage declaration
on the reading, and a bounded envelope window on the records whose absence should
count. Neither alone does anything. This is a deliberate cost: it makes opting in
an explicit act by the lane that holds the source, which is the lane that can say
whether "absent" means anything for that source at all.

**Condition 1 is why no assertion is reachable.** `Provenance.attestation` is
present exactly when the band is `ATTESTED` (ADR-0092 §1), so a record with an
attestation naming `R.source` is an attested record by construction, and §3 can
close nothing in the `ASSERTED` or `DERIVED` bands. #729's fork 4 requires that
"ASSERTED is never auto-demotable"; here it is unreachable rather than excluded,
which is the stronger form and the one ADR-0080 §2 preferred for the same band.

**The band this reaches is the band ADR-0092 §4 already ruled recoverable**, and
that ruling is the error calculus this section inherits rather than re-derives.
ADR-0038 §2's asymmetry permits retiring what can come back and refuses retiring
what cannot; ADR-0092 §4 places the attested band on the recoverable side
explicitly, because an attested belief "is **re-reportable by its source**, on a
schedule, which is a recovery path at least as reliable as re-observation." A
wrongly closed attested window is re-proposed by the next scheduled read. That is
the property that makes an absence rule affordable at all, and it is stated in the
corpus rather than assumed here.

### 4. Absence is the ingest's own answer, not a second matcher

> **Normative.** A record is **present in** `R` exactly when `R`'s ingest left it
> live at its own id: the record's id is among the `MemoryIngestResult.record_id`
> values that ingesting `R`'s proposals returned. A record satisfying §3's first
> three conditions and not present in `R` is **absent from** `R`. No second notion
> of identity is introduced, and no matcher of its own is run.

> **Normative.** Where any proposal of `R` did not resolve to a live record —
> deferred as a durable question (ADR-0078), rejected, or stored temporarily — `R`
> warrants **no** absence at all and closes no window.

**This settles #631's interaction, and it settles it by refusing to have a second
opinion about identity.** ADR-0092 §7 files the residual that identity is
re-established by similarity, so "a small edit folds; a rewrite duplicates", which
means "absent from the later read" and "present but rewritten" can look alike. A
rule that ran its own matcher would have two answers to that question in one
system, and the failure would be silent. Reading presence off the ingest's outcome
gives it exactly one: whatever `_detect_conflicts` and the policy decided is what
absence means.

**Under that definition #631's residual narrows rather than widens for a covered
record, which is worth stating because the opposite is the intuitive fear.** Take
the rewrite ADR-0092 §7 describes: "standup 9am" becomes "sprint planning,
Thursday, room 4", scores below `conflict_threshold` against its predecessor, and
lands as a second live record. Today that is two live attested beliefs about one
entry. Under §3 the predecessor is in coverage, no proposal resolved to it, so its
window closes — and one live record remains, carrying the current text. The
predecessor did stop being true, and the store now says so. The duplication #631
records is not made worse by absence-demotion; for records inside a declared
coverage it is resolved by it.

**The converse hazard is bounded by the same mechanism.** A spurious close would
need a present, unchanged entry to fail to fold onto its own record — and ADR-0092
§6 rules that case out from the other side: an unchanged re-sync "proposes
identical content, `_detect_conflicts` scores an identical live record at the top
of its ranking (lexical overlap under the in-memory store, embedding similarity
under SQLite — **identical text is the one case neither can miss**), and
`DefaultMemoryPolicy` rules `REINFORCE`". So the miss is the rewrite, where the
close is correct, and not the repeat, where it would not be.

**The second clause fails closed, and the case it is built for is real.** A
proposal that conflicts with a `USER_ASSERTED` record is ruled `ASK_USER` and
nothing is written (ADR-0092 §7 traces exactly this path). The entry *is* in the
source; the ingest simply did not resolve it to a record. Counting that as an
absence would close the window of the attested record the user is being asked
about, on the strength of the question. So one unresolved proposal suspends
absence for the whole reading, which is the refuse-rather-than-guess posture
ADR-0093 §5 takes for a bound and ADR-0080 §3 takes for an unrepresentable close.
It is deliberately coarse: the alternative is a per-proposal correspondence rule,
which is a second matcher wearing a different hat.

### 5. The close is a retirement, and it carries a retirement's obligations

> **Normative.** A close under §3 is a **retirement** and carries every obligation
> ADR-0080 already places on one. Its end is `min(now, valid_until)` where the
> record's `valid_until` is set and `now` where it is not; every other field of the
> record is preserved, `valid_from` included; and where that end is at or before a
> set `valid_from`, the close **refuses** under ADR-0080 §3 rather than writing an
> unrepresentable window.

> **Normative.** `now` is **one** instant for a reconciliation, determined before
> any write and shared by every close it performs, exactly as ADR-0080 §1 fixes it
> for one ingest.

> **Normative.** The closes a reconciliation performs land **atomically** as one
> write set through `MemoryStore.write_atomic` (ADR-0046), never through
> `MemoryStore.add`. A partially applied reconciliation is refused for ADR-0045
> §8's reason, one act over: a set of retirements that half-lands is a set of
> beliefs retired for a reading that was never fully accounted for.

> **Normative.** A reader never performs a close. ADR-0093 §1 gives a reader no
> store, no writer and no policy, and this ADR gives it none; the reconciliation is
> performed by a consumer that already holds the store.

**Reusing ADR-0080's rule rather than restating it is the point.** The two shapes
#306 named — a window that already ended, and one that has not opened — do not stop
being shapes because the closer changed, and inventing a second retirement rule
for a second closer is how a store ends up with two answers to "what does retiring
mean". ADR-0080 §2 states one rule "over every record a supersession can reach";
this ADR adds a reacher and takes the rule as it stands.

**A close under §3 reaches no `MemoryPolicy` and needs none.** There is no
proposal to rule on — nothing arrived — so there is nothing for a policy to decide
and no `MemoryDecision` to carry. That is why §3's conditions are enumerated and
conservative: the warrant is the reading's coverage, and it has to be sufficient on
its own, because no policy is standing behind it. #112's sketch asked whether
`MemoryDecisionKind` should grow an invalidation ruling; ADR-0045 declined it there
("`SUPERSEDE` names the relation") and this ADR declines it here for the
independent reason that an absence-close has no proposal to attach a ruling to.

### 6. Each close is justified alone, so the walk belongs to another ADR

> **Normative.** Each close under §3 is justified by one record and one reading
> and by nothing else. A reconciliation that examines only part of the live set
> therefore closes **fewer** windows and never a different one.

That property is what lets this ADR stop where it does. How the live set is
enumerated — the page size, the chunking, a durable cursor, resumption after a
restart, what happens when a chunk raises — is scheduler mechanics, and it is
ADR-0111's lane (#632, #710). Nothing in it can make a close under §3 wrong; the
worst an interrupted walk produces is a belief that stays live one cycle longer,
which the next reading closes.

**The enumeration itself needs no new read surface.** `MemoryStore.list_beliefs`
already enumerates live beliefs filtered by band, in a specified total order, a
page at a time, honouring both read-time axes before the cut. A reconciliation
reads `bands=[ATTESTED]` and filters on `reported_by` in the consumer. That its
offset paging "may skip or repeat a record" over a mutating store is precisely
what §6's first clause makes harmless here, and precisely the property ADR-0111
owns improving.

### 7. ADR-0093 §4 stands, and what it stands over

> **Normative.** ADR-0093 §4's first sentence stands verbatim and this ADR
> narrows it in no respect: a reader never proposes the absence, cancellation or
> retraction of anything, and nothing a reader puts in `SourceReading.proposals`
> may express one.

The reconciliation this ADR permits is not a reader proposing an absence, and the
distinction is structural rather than verbal. The reader states what it read and
what it exhausted, both facts about itself. The inference from *coverage plus
proposals* to *this stored belief is gone* requires the store, which ADR-0093 §1
puts out of a reader's reach in as many words — "It reads its own source and
returns a reading. It may not write to any store, may not read a belief" — and it
is made by the consumer that holds one. A reader that had performed this inference
would be doing what §4 forbids; a reader that declares its coverage has done what
§5 already required it to know.

**§4's second sentence is read with §11, as it was written to be.** That sentence
— "An entry missing from a later reading is not evidence that the entry was
withdrawn" — is stated without qualification, and read alone it says that no
absence is ever evidence. It was not written alone: §11 defers "Retracting an
attested belief when its source stops reporting it" by name, with a firing
condition, in the same Decision. A reader holding ADR-0093 entire was told that a
later ADR would rule this and what would unblock it. §13 applies ADR-0070 §1's
test to the pair and records what is owed.

### 8. A lapse seeks a confirming event; it never retires

> **Normative.** Where a belief's currency has lapsed, the system's response is to
> **seek a confirming event**, never to retire the belief. A lapse closes no
> window, lowers no evidence-strength (ADR-0103 §3), and changes no band
> (ADR-0072 §4).

> **Normative.** What is sought is band-specific and follows from what each band
> can be confirmed by (ADR-0103 §9). For `ASSERTED`, it is ADR-0103 §4's
> re-confirmation with the user, unchanged and not re-decided here. For
> `ATTESTED`, it is a re-read of the reporting source; the reading's outcome — a
> fold that confirms the belief, or §3's absence — is what may then act, and the
> lapse itself never does. For `DERIVED`, it is neither: nothing is asked and
> nothing is closed.

**The `ATTESTED` arm is where the two halves of this ADR meet, and it is the
reason they are one decision.** A lapse is not evidence, but it is a good reason to
go and get some, and for an attested belief there is somewhere to go: the source
re-reports on a schedule (ADR-0092 §4). So the honest machinery is a lapse that
prompts a read and a read that closes a window — the clock triggers the *question*
and the observation supplies the *answer*, which is exactly the shape ADR-0103 §4
already ratified for the band where the question is asked of a person.

**The `DERIVED` arm is the one that looks like an omission and is not.** A derived
belief lapses because no recent observation supports it, and there is nobody to
ask: ADR-0103 §9 rules its confirming instant is "the latest `occurred_at` among
the episodes `Provenance.evidence` cites", so re-deriving from the same episodes
confirms nothing — the exact inflation ADR-0077 §5 was built to prevent, reached
through currency instead of strength. Closing it instead would be worse on two
ratified counts: ADR-0072 §1 makes a derived belief re-derivable "while the
observations behind it are still retained", and ADR-0103 §1 forbids a leg 7
decision that weakens a belief without "a warrant other than store size". Elapsed
time is not that warrant, per §1. What a lapsed derived belief gets is what
ADR-0103 §9's last clause already gives it: a surface that renders it conveys the
lapse alongside its evidence-strength.

**This ADR's warrant under ADR-0103 §1, stated as that clause requires.** §3
removes beliefs from the read path, so it "states a warrant other than store
size": the warrant is that the source the belief is attested to was read to
exhaustion over the region the belief occupies and did not report it. Nothing is
deleted, nothing is expired, no evidence is elided, and every closed record stays
in `export` (ADR-0045 §6).

### 9. What this ADR does not decide

- **Whether currency reaches retrieval, and how.** ADR-0103 §8 routes that to the
  retrieval-ranking lane, which "states which shape it takes and what ADR-0072 §5
  costs under it". This ADR takes none of the three shapes and prices none of
  them. What it supplies is the content of one of the things that lane may choose
  *among* — what acting through the validity machinery consists of — and the
  answer is §8's: it acts by seeking a confirming event. Whether currency
  additionally composes above the store seam or ranks inside `MemoryStore.search`
  is untouched, and nothing here is permission to weight `MemoryStore.search` by
  anything.
- **Scheduler mechanics.** Cursor placement, chunking, backoff, halt-on-refusal
  and resumption are ADR-0111's (#632, #710). §6 states the property that keeps
  the seam clean and declines the rest.
- **Eviction, size caps, and any retention consequence.** ADR-0103 §1's framing
  rules them out for this leg and ADR-0007 §5's deferral stands. A closed window
  is not a deletion and creates no reclamation.
- **As-of retrieval and the second temporal axis.** ADR-0045 §1 and §10 deferred
  both for want of a consumer, and this ADR creates none: a reconciliation reads
  live records and writes closes, and asks nothing about what was believed on an
  earlier day. §12 carries the deferral forward.
- **#631's source-key field and its index.** ADR-0092 §10 declined them and §4
  above deliberately does not require them: absence is read off the gate's own
  outcome precisely so that this decision does not depend on a facility the corpus
  has declined twice. #631's trigger — the first observed duplicate — is unchanged.
- **Which sources should declare coverage, and what a bounded window means for
  each.** §3 states what a reader owes to opt in; whether a given source's entries
  have a position worth stating is that reader's lane's, with the source in hand —
  the discipline ADR-0073 §4 applied to the attestation vehicle and ADR-0093 §10
  to `as_of`.
- **A threat model for a reader that lies about its coverage.** ADR-0095 §6 files
  the seam's threat model as its own parked question and this ADR does not open
  it. What is stated here is the honest bound: coverage is a reader's assertion
  about itself, and §3's other three conditions are what stop a wrong one from
  reaching anything but that reader's own records.

### 10. The contract surface owed

**New surface in `core` — a breaking change (golden rule 5), implemented by a
later lane:**

- **`core/types.py`** gains **one optional field** on `SourceReading` carrying
  §2's coverage, and the small frozen value object it takes: a half-open interval
  with `None` at either end meaning unbounded, mirroring `Validity`'s shape and
  its "both set ⇒ end after start" invariant. Optional with a `None` default, so
  every existing construction site and every stored reading stays valid — ADR-0093
  §3's own additive pattern, and ADR-0109 §2's test for a `core` validator ("does
  it refuse something that already worked") comes out the same way. The spelling
  is the implementing lane's; what is contract is that the reading carries the
  interval it exhausted and that its absence means no coverage was declared.
- **`core/protocols.py`** gains **no new Protocol and no new method**. `Reader` is
  untouched — coverage rides on the reading it already returns. `MemoryStore` is
  untouched: §5's closes go through `write_atomic`, which ADR-0046 landed, and §6's
  enumeration through `list_beliefs`, which ADR-0073 §1 landed.
- **`MemoryDecisionKind`, `MemoryDecision` and `MemoryPolicy` are untouched**, per
  §5: an absence-close carries no proposal and reaches no policy.

**What the implementing lane decides, and the constraint on it.** Whether the
writer boundary exposes §5's close as a new `MemoryWriter` member or as a widening
of an existing one is the implementing lane's — a shape question a second lane
could answer differently without either being non-conforming. What is *not* the
lane's, because two lanes could there make incompatible choices and both claim
compliance (ADR-0103 §9's test), is: the close obeys ADR-0080 §1's clamp and §3's
refusal; it is atomic over the set (§5); it never runs through `MemoryStore.add`;
and it never reaches a record outside §3's four conditions.

**The conformance question is deferred to that lane, in ADR-0103 §7's form.**
Whether any clause here becomes a `MemoryWriter` or `MemoryStore` conformance
obligation is decided by the lane that implements it, in an ADR that names those
clauses and applies ADR-0070 §1's test to them. Ruling it here would promote a
rule with no implementation to a suite that drives two writers.

### 11. #639 answered, clause by clause

#639 asks three things and this ADR answers all three.

- **"Whether that is enough to close a validity window"** — a complete read is
  not, on its own. §2 shows completeness is already guaranteed of every reading and
  is therefore not the discriminating property; §3's coverage is.
- **"Whether closing a window is the right instrument at all"** — yes, and it is
  the only one available: ADR-0045 §4's window close is what "invalidate, don't
  delete" means in this store, ADR-0080 §4 rejected the never-lived alternative,
  and deletion is refused by ADR-0007 §1 and ADR-0103 §1 alike.
- **"The interaction with ADR-0092 §7's residual (#631)"** — §4. Absence is the
  ingest's own answer, so the two mechanisms cannot disagree about identity, and
  for a covered record the rewrite case resolves instead of duplicating.

**#639 closes when this ADR is ratified.** Its ADR-0093 §4 reconciliation is §7,
its firing condition is recorded in this ADR's header, and nothing it asks is left
open. The reader-side opt-in §3 requires is not #639's residue but this decision's
consequence, and it belongs to whichever reader lane wants it.

### 12. #112 adjudicated: it closes, and three deferrals carry forward

#112 asked for bi-temporal validity — "invalidate, don't delete" — and ADR-0045
delivered it. Its open questions are all disposed of on the record: OQ2
(invalidation ruling vs `MERGE`) was ADR-0040's and it declined a new kind; OQ3
(export) is ADR-0045 §6; OQ4 (migration) is ADR-0045 §9; OQ5 (placement on the
envelope, not `Provenance`) is ADR-0045 §2. Its stated defect — a `USER_ASSERTED`
proposal `ACCEPT`ed beside the stale record it contradicts — is resolved by
ADR-0038 §2a, ADR-0045 §4 and ADR-0079 §1's total retirement. Its `TODO.md`
reference is stale: ADR-0015 removed that file and replaced it with GitHub issues.

What #112 never got an answer to is the question this ADR is: it framed
invalidation entirely as a response to *contradiction*, and said nothing about a
belief nobody contradicted. §1, §3 and §8 answer it.

> **Normative.** #112 closes with this decision. Three deferrals it raised outlive
> it, are ADR-0045 §10's rather than this ADR's, and carry forward on their own
> issue rather than on a closed one: **as-of retrieval** (OQ1), **the full
> transaction-time axis**, and **reconciling `SemanticMemory.valid_until` with the
> envelope window**. None has a consumer, and this decision creates none (§9).

Closing it is the honest bookkeeping rather than a courtesy: an issue whose body
cites a deleted file, proposes a design two ADRs took differently, and names open
questions four ADRs have since answered is a source of rework for whoever reads it
next, and the corpus is where its answers now live.

### 13. What this records against earlier ADRs

The judgement ADR-0082 §1 requires is made here, clause by clause, by applying
ADR-0070 §1's test to each earlier ADR's text: would a reader holding only that
ADR now act differently, or read one of its clauses more widely than it now holds?

**ADR-0093 §4 and §11 — a record is owed, and it is a dated note.** §11 defers
"Retracting an attested belief when its source stops reporting it" with the
firing condition "Fires with ADR-0092's override mechanism"; this ADR is that
decision and the condition has fired, so §11's entry stops describing an open
deferral. §4's first sentence is untouched (§7). §4's second sentence — "An entry
missing from a later reading is not evidence that the entry was withdrawn" — is
where the two available readings diverge, and both are stated because the choice
is the reviewable part:

- Read **alone**, it is an unqualified rule that this ADR narrows by exception, and
  a narrowing of a normative clause is a change to what was decided, which ADR-0070
  §1 sends to partial supersession.
- Read **with §11**, which is in the same Decision and defers this exact retraction
  by name with a firing condition, it was never unqualified: a reader holding
  ADR-0093 was told that a later ADR would rule it and what would unblock it, so
  that reader does not now act differently — they act on the ADR §11 pointed them
  to. That is a **discharged deferral**, which the corpus treats as an appended
  dated note rather than a supersession: ADR-0045's 2026-08-02 note is exactly this
  shape, recording ADR-0092's discharge of §5/§7/§10's policy choice with the words
  "**The deferral is discharged, not overturned.**"

**This ADR takes the second reading**, on the ground that §11's entry names this
decision, this ADR, and this firing condition, and that treating a deferral the
earlier ADR itself scheduled as a supersession of the clause it was deferred
against would make every discharge in the corpus a supersession. The record is
therefore an **appended dated note on ADR-0093**, landing in this same change.
Under ADR-0082 §2 no `Status` qualifier is written, because that line is led by
`Partially superseded by ADR-0095`; the note is the whole record. If a reviewer
holds the first reading, what changes is one `Status` line and not one clause
below it, and this section is where that argument belongs.

**ADR-0103 §3 and §8 — nothing owed.** §3's sentence "Whether lapsed currency may
close a validity window is not decided here (§8)" is a deferral, discharged here
with the answer no (§8 above); it asserts nothing that becomes false. §8's clause
is the one where the opposite reading is available and it does not survive
inspection. Its three obligations are that ADR-0103 grants no retrieval-side role,
that the retrieval-ranking lane's ADR states its shape and its ADR-0072 §5 price,
and that nothing there permits weighting `search`. This ADR disturbs none of them:
it takes no shape, states no price, and permits no weighting. What §8 routes to
that lane is *whether and how currency reaches retrieval* — including whether it
does so "through fork 4's validity machinery"; what it does not route is *what
fork 4's machinery is*, which is this lane's and which ADR-0103 §3 expressly left
open. A reader holding only ADR-0103 still builds the same thing and still owes
the same ADR. **Stacked addition; no record owed.**

**ADR-0045 §4, §6, §8 and §10 — nothing owed.** §4's `SUPERSEDE` mechanism is
untouched; this ADR adds a second closer beside it and changes nothing about the
first. §6's read semantics are relied on unchanged, including that a closed record
stays in `export`. §8's atomicity requirement is extended to a new write set by
§5, which is that requirement applied rather than narrowed. §10's deferrals are
carried forward verbatim by §12. **Stacked additions; no record owed.**

**ADR-0080 §1, §2, §3 — nothing owed.** §5 adopts the clamp, the single close
instant and the refusal exactly as ruled, for a new closer. §2's "one rule, stated
once, applies to every record a supersession can reach" gains a reacher and loses
nothing; its `ASSERTED` unreachability argument is reproduced rather than relaxed
(§3). Using a mechanism as specified is not amending it — the ADR-0083 §15 pattern
ADR-0093 §12 applied to three clauses at once. **No record owed.**

**ADR-0092 §4, §6, §7 — nothing owed.** §4's recoverability argument is cited as
the ground for §3 and read no more widely than it holds. §6's minting rule is
untouched and §4 above depends on it. §7's residual is not closed by this ADR
(#631 stays open on its own trigger); §4 above narrows the *set of records for
which it bites* without touching the residual's statement or its filing.
**No record owed.**

**ADR-0072 §1, §4, §5 — nothing owed.** §1's re-derivability condition is cited as
a reason not to close a derived belief. §4's band rule is relied on. §5 acquires no
exception and is granted none: nothing here ranks, weights or composes anything at
retrieval. **No record owed.**

**ADR-0007 §1 and §5 — nothing owed.** No record is deleted and no cap is
implied; §9 says so and ADR-0103 §1 already carried the exemption. **No record
owed.**

## Consequences

- **The last open question about what may take a belief off the read path has an
  answer, and it is a narrow one.** Two closers exist where there was one, and the
  second is bounded by four conditions that no reader on `main` currently
  satisfies — so this ADR ratifies a mechanism and changes no behaviour until a
  reader lane opts in, which is the ordering golden rule 5 asks for anyway.
- **Leg 7's exit test gets its delivery mechanism for the "not noisier" half
  without touching retrieval.** A cancelled meeting stops being retrieved because
  it stops being live, not because it ranks lower, so ADR-0072 §5 stays exactly
  where it is and the retrieval-ranking lane inherits a smaller question rather
  than a pre-empted one.
- **A reader lane that wants absence-demotion owes two things** — a coverage
  declaration and bounded envelope windows on the records it proposes — and this
  is a real cost paid deliberately, so that opting in is an act by the lane holding
  the source rather than a default the seam grants.
- **`core` grows one optional field and no Protocol member**, which is the
  cheapest shape this decision was available in; the alternatives that would have
  cost more are in §Alternatives.
- **The implementing lane owes**: the `SourceReading` field and its value object
  with the additive migration story ADR-0093 §3's pattern implies; the writer
  boundary's close under §5's four constraints; the reconciliation itself,
  sequenced with ADR-0111's scheduler work; and the conformance judgement §10
  defers to it.
- **#639 and #112 close on ratification** (§11, §12), and ADR-0045 §10's three
  surviving deferrals move to their own issue.
- **Revisit if** a reader is found whose entries have a position in the source's
  world that the envelope window cannot state (§3's condition 3 would then need a
  different carrier), if leg 8's measurement shows that seeking a confirming event
  on lapse is too noisy to run at any threshold (§8's response, not its parameters,
  would then be back open — the revisit ADR-0103 §4 already carries, one band
  wider), or if a reader is ever observed declaring a coverage it did not exhaust,
  which is the threat-model question ADR-0095 §6 parked.

## Alternatives considered

- **Close a window on a currency lapse, at a threshold.** Rejected in §1 and §8.
  It has no number to fire on — ADR-0103 §5 defers the threshold to leg 8 — and a
  store in which every pre-ADR-0109 record reads as unknown currency (ADR-0103 §9)
  that it must not fire on. But the ground is not the missing number: elapsed time
  is not an observation, and ADR-0103 §4 already refused this mechanism for the one
  band where it stated its reason, which reads on the others unchanged.
- **Take #639's "complete read" framing as the condition.** Rejected in §2, on the
  finding that ADR-0093 §5 and §8 already guarantee completeness of every reading
  that exists, so the condition would admit every reading and separate nothing. The
  framing was offered as a starting point and this is what checking it against the
  record produced.
- **Have the reader propose a retraction, amending ADR-0093 §4's first sentence.**
  Rejected in §7. §4's argument survives its own ADR's §5 and §8 in exactly one
  respect — a bounded read still looks like a deletion *to the reader* — and the
  reader is the one component that cannot tell the difference, because ADR-0093 §1
  denies it the store. Moving the inference to the consumer keeps §4 whole and puts
  the judgement where the information is.
- **Give the reconciliation its own matcher over the reading's entries.** Rejected
  in §4: it introduces a second notion of identity beside the gate's, which is how
  a system acquires two answers to #631's question, and the second one would be
  invisible at the seam. Reading presence off `MemoryIngestResult` costs nothing
  and cannot disagree.
- **Close on absence regardless of the record's window, scoping only by
  `reported_by` and coverage.** Rejected in §3: an unbounded attested belief has no
  position in the source's world, so no bounded reading can have exhausted the
  region it occupies, and closing it would be doing exactly what ADR-0093 §4's
  indistinguishability argument forbids — retracting on the strength of having
  looked somewhere else.
- **Carry the source's own key on the record and resolve identity by it (#631's
  fix), then define absence by key.** Rejected in §9: ADR-0092 §10 declined the
  field and its index deliberately, twice-stated, and building this decision on it
  would make an unblocked deferral into a blocked one. §4's definition needs
  nothing #631 defers.
- **A new `MemoryDecisionKind` for invalidation**, as #112's sketch proposed.
  Rejected in §5 and §10: ADR-0045 already declined it on the ground that
  `SUPERSEDE` names the relation, and an absence-close has no proposal to attach a
  ruling to, so a member would name a decision no policy ever makes.
- **Require coverage on `SourceReading` rather than making it optional.** Rejected
  in §2 and §10: it breaks every existing construction site and every stored
  reading to avoid a `None`, which is the trade ADR-0093 §3 already refused for the
  facet half and ADR-0109 §2 refused for `last_confirmed_at`.
- **Rule the enumeration's mechanics here too**, since §6 depends on one existing.
  Rejected as scope: they are ADR-0111's (#632, #710), and §6's monotonicity is
  precisely what makes deciding them separately safe.
