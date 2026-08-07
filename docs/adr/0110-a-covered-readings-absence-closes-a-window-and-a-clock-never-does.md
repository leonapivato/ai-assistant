# 110. What closes a validity window without the user: a covered reading's absence, and never a clock

- Status: Partially superseded by ADR-0115 (§10's ruling that the mechanism is buildable on the `core` surface that exists, and its clause that `MemoryWriter` is untouched and no new member is authorised)
- Date: 2026-08-06
- **Partially superseded: 2026-08-07 by
  [ADR-0115](0115-the-writer-contract-carries-the-reading.md), in the scope the
  `Status` line names — the reconciliation §5a requires cannot be reached through a
  per-proposal seam, so `MemoryWriter` gains one member and golden rule 5 is
  triggered for the lane that builds it.** §10 rules that the mechanism "is
  buildable on the `core` surface that exists plus §10's one optional field, and it
  authorises no other Protocol change", and that "**`MemoryWriter` is untouched, and
  no new member is authorised here.**" The implementation lane found otherwise, in
  three review rounds recorded on #803: §5a's prerequisite requires the ingest, the
  selection and the closes to be one serialised sequence rather than three
  separately serialised steps, which requires the whole reading to reach the writer
  as one call, and no existing member carries one — while reaching the concrete
  writer around the contract is what golden rule 1 forbids. **This is §10's own
  prescription firing rather than being overridden**: its last sentence routes a
  lane that "concludes it needs a new `MemoryWriter` or `MemoryStore` member" to
  "its own ratified ADR for it under golden rule 5", and ADR-0115 is that ADR.

  **Nothing else moves, and §5a moves least of all.** Every other ruling here stays
  accepted and ADR-0115 is built on them — §1's spine, §2's coverage and its
  invariant, §3's four conditions and containment rule, §4's presence and
  suspension, §5's retirement obligations, §5a's serialisation prerequisite (which
  ADR-0115 does not relax by one word, but rather supplies the seam that makes it
  satisfiable), §5b's withholding of the compare-and-swap and its token, §§6-9, and
  §12's adjudication of #112. **§10's `core/types.py` half also stays accepted**:
  the one optional field on `SourceReading` is ratified, landed as #803, and is the
  value ADR-0115 §1's member carries. What is replaced is the buildability ruling
  and the no-new-member clause, and nothing besides. ADR-0115 §8 applies ADR-0082
  §1's and ADR-0070 §1's tests separately and states why the scope is drawn here.

  **Recorded now rather than at ADR-0115's ratification**, per ADR-0082 §7: ADR-0070
  §1's condition is "that the superseding ADR **exists**, not that it is ratified —
  the hazard §1 names is a `Status` line pointing at nothing, and an atomic pair
  makes that unreachable". ADR-0115 lands in this same change, so the pair is
  atomic and the reference resolves.
- **Note (2026-08-06): ratified.** `Proposed` → `Accepted`, in the separate lane
  #633 requires, after **both** required reviews came back green on the content
  this ADR merged with: adversarial **APPROVE with no findings** and architecture
  **APPROVE with no findings**, both at round 4, 951 lines net across 5 commits,
  churn reported as a lower bound of `≥1.1×` (1075 touched; history was rewritten,
  so earlier rounds are not counted), each posted to PR #783 by `just ship`. That
  is the outcome ADR-0070 §1 requires the ratifying edit to record — "the
  ratifying edit records that review's outcome, it does not replace it" — and it
  is taken from that comment rather than from a report.

  **Two lenses, and that is what this ADR's own header bullet below declared it
  owed.** It decides `core` surface without touching it — §2's and §10's one
  optional field on `SourceReading` — so it is contract-surface under
  `CONTRIBUTING.md` → "Stop when the required reviews are green", which makes a
  change contract-surface "when it is the ADR deciding that surface". The
  requirement was `CONTRIBUTING.md`'s and not `scripts/ship.sh`'s: the script
  fires its architecture requirement on a diff touching `core/protocols.py` or
  `core/types.py`, and a prose-only PR deciding those files trips neither, so both
  lenses were run deliberately. **This ratifying edit takes the adversarial lens
  alone**, which is the same clause read one step on: `CONTRIBUTING.md` →
  "Trivial ADR edits" exempts "the `Proposed` → `Accepted` ratification flip" from
  a separate review *of the edit itself*, "not licence to rewrite a ratified
  decision in place", and ADR-0015 §5 exempts trivial ADRs by name.

  **The anchor is not the merged head, and the identity is established through
  the tree rather than assumed**: the comment's
  `<!-- ship:a77711e852c67d63a9bebdccd140741c5b39b6be -->` anchor is the pre-merge
  branch head, which is *not* an ancestor of `main` because #783 was
  rebase-merged. Both were resolved with `git rev-parse` rather than trusted:
  `a77711e852c6^{tree}` and `9b16e56^{tree}` — the commit the PR merged as — are
  the same tree, `7a9b09acfec2`. The content the two reviews read is therefore the
  content that landed, notwithstanding the rewritten hash.

  **No `blocker` or `major` finding was waived.** The architecture lens carried one
  `major` through round 3 — that §4's suspension clause put `STORE_TEMPORARY` on
  the stored-nothing side, which ADR-0108 §1 makes false — and it was fixed in the
  text rather than argued away: §4 is keyed on `MemoryIngestResult.record_id` being
  `None` rather than on an enumeration of rulings, and the paragraph beginning "The
  clause is keyed on `record_id` being `None`" records the defect at the site it
  repaired. Round 4 re-ran both lenses over the repaired text and neither raised
  anything.

  **One sentence was corrected and it is the only edit besides the `Status` line.**
  The durability bullet below asserted that "Several of the ADRs this decision
  composes with stand `Proposed` on `main`". That was checked against the tree
  rather than taken, and it was false — at this PR's branch point the only ADRs
  standing `Proposed` on `main` were ADR-0043 and ADR-0089, and this ADR cites
  neither; ADR-0109, the last neighbour it composes with that had stood `Proposed`,
  was ratified eight hours before this ADR's first commit. The sentence is
  therefore made conditional rather than factual, which is what the rest of the
  bullet always relied on: the operative content is that a ratification flip moves
  no clause cited here, and that content is untouched. **Nothing else below is
  edited** — not a clause, not a tense — which is ADR-0070 §1's own test applied
  to the ratifying edit first: no decision text is touched and no normative clause
  acquires, loses or alters an obligation.

  **The scheduler lane's ADR has since been issued, and §6's and §9's issue-only
  reference is left standing rather than renumbered.** That lane's ADR is
  [ADR-0111](0111-a-scheduled-walk-is-chunked-and-resumes-from-a-durable-cursor.md),
  which merged as #784 and is ratified in this same change. §9's ground for naming
  the seam by issue — "a citation to a number no ref carries is a Tier 1 defect
  under ADR-0088 §6 as ADR-0090 §1 narrows it" — was correct at the moment it was
  written and is a dated record of it; rewriting it now would falsify ADR-0111 §10,
  which quotes that sentence and describes this ADR's reference as by-issue-only,
  in the document being ratified beside this one. The seam is navigable without the
  edit: ADR-0111 §11 states it from both sides and cites this ADR by number, and
  §§1–8 there bind the walk while this ADR binds the verdict.

  **The rest of the sweep is empty, and the sites are named so the claim can be
  checked rather than trusted.** Every use of "ratified" below was read: §3's "a
  ratified thing this system already knows how to retire" is ADR-0080 §5's ruling,
  §8's "already ratified for the band" is ADR-0103 §4's, §8's "worse on two
  ratified counts" is ADR-0072 §1's and ADR-0103 §1's, and §10's and the
  Alternatives' "owes its own ratified ADR" and "an ADR ratifies before
  implementation" are golden rule 5's rule rather than any document's standing.
  Not one turns on where an ADR stands. The clauses whose truth *depends* on this
  ratification were written forward and this edit is the event that makes them
  true: §11's "#639 closes when this ADR is ratified", §12's "#112 closes with this
  decision", and the Consequences' "#639 and #112 close on ratification". No tree
  claim has gone stale: nothing outside `docs/adr/` has changed on `main` since
  this PR's branch point, so §2's `SourceReading` fields, §4's
  `MemoryIngestResult.record_id` docstring, §5's `write_atomic` and §6's
  `list_beliefs` all read exactly as the reviews read them. Refs #112, #639, #729,
  #631, #632, #633.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-06, not
  to its status on any later day.** Where an ADR this decision composes with
  stands or stood `Proposed` on `main`, its ratification flip is its own lane's;
  `CONTRIBUTING.md` → "Trivial ADR edits" and ADR-0070 §1 both class that
  flip as recording a ratification rather than deciding one, so no clause cited
  here moves with it. Where a later ADR *changes* one of them, that change owes
  its own record and this ADR is owed a matching one.
- **Decides `core` surface and implements none of it.** Exactly one optional field
  on `SourceReading` in `core/types.py`, with its endpoint type and invariant
  pinned (§2, §10). **No `core/protocols.py` change**: §5's closes ride
  `MemoryStore.write_atomic` and §6's enumeration `MemoryStore.list_beliefs`, both
  of which exist, and §10 rules that a lane concluding it needs a new Protocol
  member owes its own ADR. Golden rule 5 and ADR-0015 §5 put a contract ADR in its own PR,
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
- **Partially supersedes ADR-0093 §4's second sentence** — "An entry missing from
  a later reading is not evidence that the entry was withdrawn" — narrowing it by
  exception to a reading that declares the coverage it exhausted (§3). §4's first
  sentence and every other ADR-0093 ruling stand; the record is on that ADR's
  `Status` line and in its appended dated note, both landing in this change.
  **Nothing else on any earlier ADR.** §13 makes the judgement clause by clause
  under ADR-0070 §1 and ADR-0082 §1, including for ADR-0103 §8, where the opposite
  answer is available and does not survive inspection.
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
> coverage**: the interval of the source's world the read exhausted, expressed as
> a half-open `[covers_from, covers_until)` pair of **`UtcInstant | None`**, where
> `None` at either end means unbounded and both-set implies `covers_until >
> covers_from` — `Validity`'s shape, its endpoint type, and its invariant. It is
> carried on `SourceReading` as an **optional** field, and its absence means the
> reading declares no coverage and warrants no absence.

**The endpoint type and the invariant are ruled here rather than left to the
lane, because they fail ADR-0103 §9's test and a name does not.** That section
draws the line at "could two lanes make incompatible choices and both claim
compliance?" — and a lane reading coverage as instants and a lane reading it as
dates, indices or an opaque source cursor give **different answers to §3's
containment question** while each satisfying a clause that named neither. So the
domain is pinned. What is left to the lane is the field's and the value object's
*spelling*, which is rename-class: a second implementation choosing another name
has renamed something, not decided something.

**`UtcInstant` because the corpus has one instant type and this is an interval of
instants.** `Validity.valid_from`/`valid_until`, `Attestation.reported_at` and
`SourceReading.read_at` are all `UtcInstant`, and §3 compares coverage directly
against `Validity`'s two ends — a comparison across two different annotations
would be a conversion for nothing, and a conversion is where a timezone is lost.

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

> **Normative.** "Wholly within" is containment of one half-open interval in
> another with unbounded ends, stated so no lane has to derive it: the record's
> window `[vf, vu)` lies wholly within `C = [cf, cu)` iff **`cf` is `None` or
> (`vf` is not `None` and `vf >= cf`)** and **`cu` is `None` or (`vu` is not
> `None` and `vu <= cu`)**. An unbounded record end is contained only by an
> unbounded coverage end on the same side — so a record with a fully open window
> is contained only by a fully unbounded coverage, and a bounded reading contains
> none.

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

> **Normative.** Where any proposal of `R` **stored nothing** — its
> `MemoryIngestResult.record_id` is `None`, which is what a `REJECT` and an
> `ASK_USER` deferral (ADR-0078) leave behind — `R` warrants **no** absence at all
> and closes no window.

**The clause is keyed on `record_id` being `None` rather than on an enumeration of
rulings, and the difference is not cosmetic.** `MemoryIngestResult.record_id` is
documented as "Id of the record left live by the write, or None if nothing was
stored", so the field already draws exactly the line this clause needs, and a
ruling added later lands on the correct side of it without amending this ADR. An
earlier draft enumerated instead, and put `STORE_TEMPORARY` on the stored-nothing
side, which is false: ADR-0108 §1 rules that "`ACCEPT` and `STORE_TEMPORARY` write
the proposal as a *new* record", so a temporary store resolves to a live id like
any other install. Keying on the field rather than on a remembered list is what
stops that class of error.

**`ACCEPT` and `STORE_TEMPORARY` therefore need no exception, and it is worth
saying why they do not.** Both install at the *proposal's* id, so neither can ever
mark a §3 candidate present — a candidate is a record the store already held, and
ADR-0108 §2 refuses an install onto a stored id outright. So an entry that
re-appeared and did **not** fold leaves its predecessor absent and closes it. That
is not a gap: it is the rewrite path this section already traces, where the
predecessor genuinely stopped being true and the install carries the current text.
The unchanged entry, which must not take that path, does not — ADR-0092 §6 puts it
on `REINFORCE`, which folds at the target's id and marks it present.

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
source; the ingest simply stored nothing for it. Counting that as an
absence would close the window of the attested record the user is being asked
about, on the strength of the question. So one stored-nothing proposal suspends
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

### 5a. Ruling: this reconciliation is #248's trigger, and it is a hard prerequisite

A reconciliation is a **read-modify-write across three steps** — select the live
in-coverage records (§6), ingest `R`'s proposals (§4), write the closes (§5) —
and `write_atomic` does not make that sequence isolated. ADR-0046 §5 rules this
in terms, and rules it about exactly this shape: "It makes a **write-set**
atomic. The conflict `search` that produced the records happened *before* the
batch is assembled and is not inside it, so a concurrent writer that changed `T`
between the read and the `write_atomic` is still lost. Atomic-write-set is
orthogonal to read-modify-write isolation." So a `REINFORCE` landing on a
selected record between the selection and the batch is overwritten by the close's
`UPSERT`, and the evidence that `REINFORCE` unioned is gone — ADR-0086's citation
list destroyed by a retirement, which is the one outcome ADR-0045 exists to make
impossible.

**ADR-0046 §5 also names what would make this urgent, and this decision is it.**
Its ground for leaving #248 open is that "#248 has no in-scope consumer to
justify that surface" — "nothing runs two writers on one store" — and it states
its own trigger: "If a composition ever does run two writers on one store,
closing #248 is that lane's trigger." The residual it scopes is "**any two
writers not sharing that lock**, in-process or cross-", because #262's lock is
held by one `MemoryIngestor` instance. A reconciliation writing closes is a
writer that does not hold it.

> **Normative.** The reconciliation §3 authorises may not be implemented until
> its selection, its ingest and its closes are **serialised against every other
> writer on the same store** — either because the composition runs one writer and
> the reconciliation shares its serialisation, or because the compare-and-swap
> ADR-0046 §5 scopes to its own lane exists and the closes are conditional on the
> selected records being unchanged. An implementation over an unserialised
> read-modify-write is refused.

> **Normative.** This ADR does **not** design that primitive and adds no
> concurrency token to `MemoryRecord`. A `MemoryWriteMode.IF_UNCHANGED` and its
> token are ADR-0046 §5's own lane's, and #248's, exactly as scoped there.

This is ADR-0045 §8's move, one act over. That section ruled "rather than assume"
that "the window-closing `SUPERSEDE` applier requires #104 first", splitting the
dependency by what actually needs it and stating the consumer requirements
without designing the primitive, so that "a later lane cannot silently implement
the applier over a non-atomic pair of blind upserts." The same sentence is owed
here about a non-isolated one, and for the same reason: the failure is silent,
it destroys evidence, and it would ship under the cover of a feature.

**The cheaper half of the disjunct is the one this expects to be taken.** The
reconciliation runs on the hub's scheduler (ADR-0083 §7), where the ingest path
it consumes already runs; a single writer serialised as #262 serialises one today
satisfies the clause with no new `core` surface at all. The compare-and-swap is
named as the alternative so the clause states a condition rather than a
particular wiring — the discipline ADR-0080 §1 applied when it fixed that there
is *one* close instant without requiring a clock.

### 6. Each close is justified alone, so the walk belongs to another ADR

> **Normative.** Each close under §3 is justified by one record and one reading
> and by nothing else. A reconciliation that examines only part of the live set
> therefore closes **fewer** windows and never a different one.

That property is what lets this ADR stop where it does. How the live set is
enumerated — the page size, the chunking, a durable cursor, resumption after a
restart, what happens when a chunk raises — is scheduler mechanics, and it is
the scheduler chunking-and-cursor lane's (#632, #710), whose ADR is in flight
and is deliberately not cited by number here (below). Nothing in it can make a
close under §3 wrong; the
worst an interrupted walk produces is a belief that stays live one cycle longer,
which the next reading closes.

**The enumeration itself needs no new read surface.** `MemoryStore.list_beliefs`
already enumerates live beliefs filtered by band, in a specified total order, a
page at a time, honouring both read-time axes before the cut. A reconciliation
reads `bands=[ATTESTED]` and filters on `reported_by` in the consumer. That its
offset paging "may skip or repeat a record" over a mutating store is precisely
what §6's first clause makes harmless here, and precisely the property that lane
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
  and resumption belong to the scheduler chunking-and-cursor lane (#632, #710).
  §6 states the property that keeps the seam clean and declines the rest. **That
  lane's ADR is in flight and is not cited by number**, because a citation to a
  number no ref carries is a Tier 1 defect under ADR-0088 §6 as ADR-0090 §1
  narrows it — an unissued number is not a forward reference, it is a citation to
  nothing. The seam is named by its issues instead, which are stable.
- **Eviction, size caps, and any retention consequence.** ADR-0103 §1's framing
  rules them out for this leg and ADR-0007 §5's deferral stands. A closed window
  is not a deletion and creates no reclamation.
- **As-of retrieval and the second temporal axis.** ADR-0045 §1 and §10 deferred
  both for want of a consumer, and this ADR creates none: a reconciliation reads
  live records and writes closes, and asks nothing about what was believed on an
  earlier day. §12 carries the deferral forward.
- **The compare-and-swap #248 needs, and its concurrency token.** §5a rules that
  this reconciliation is the consumer ADR-0046 §5 named as #248's trigger and
  makes serialisation a hard prerequisite; it does not design the primitive, add a
  version field to `MemoryRecord`, or rule on `MemoryWriteMode`. That stays where
  ADR-0046 §5 scoped it.
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

- **`MemoryWriter` is untouched, and no new member is authorised here.**

> **Normative.** The mechanism this ADR decides is buildable on the `core`
> surface that exists plus §10's one optional field, and it authorises no other
> Protocol change. A close is a `MemoryWrite` in `MemoryWriteMode.UPSERT` inside a
> `write_atomic` batch — the mode `MemoryWriteMode` documents a window-close as,
> and same-kind by construction, so ADR-0108 §4's cross-kind refusal is not
> engaged. A lane that concludes it needs a new `MemoryWriter` or `MemoryStore`
> member owes its own ratified ADR for it under golden rule 5, and may not read
> this one as pre-authorising it.

An earlier draft of this section left "a new `MemoryWriter` member or a widening
of an existing one" to the lane as a shape question. That was wrong on this
repository's own terms: those are two different Protocol surfaces, golden rule 5
makes either a decision an ADR has to ratify before it is implemented, and
handing that choice to an implementation lane is the thing the rule exists to
stop. It is also unnecessary — `write_atomic` and `list_beliefs` already carry the
whole mechanism — so the deferral was buying nothing and spending a rule.

**What is genuinely the implementing lane's** is the spelling of §2's field and
value object, and the wiring of the reconciliation into a scheduler job. What is
*not* the lane's, because two lanes could there make incompatible choices and both
claim compliance (ADR-0103 §9's test), is: §2's endpoint type and invariant; §3's
containment rule and its four conditions; §4's definition of presence and its
suspension clause; ADR-0080 §1's clamp and §3's refusal; atomicity over the set
(§5); and §5a's serialisation prerequisite.

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

**ADR-0093 §4 and §11 — a record is owed, and it is a partial supersession.** §11 defers
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

**This ADR takes the first reading — a partial supersession — after taking the
second one to review and having it answered on the text.** The draft argued that
§11's entry names this decision, this ADR and this firing condition, so a reader
holding ADR-0093 entire was told a later ADR would rule it and does not now act
differently; and that treating a deferral the earlier ADR itself scheduled as a
supersession would make every discharge in the corpus one. The architecture lens
answered it by naming what §11 does and does not do, which is the answer:
**§11 defers the *work* and nowhere qualifies or suspends §4's rule.** Its entry
restates the prohibition — "§4 forbids proposing absence, which makes this real
work rather than a special case" — rather than marking §4 provisional, so §4's
sentence is unqualified as it stands and a reader acting on it acts differently
after §3. That is ADR-0070 §1's test met, and its answer is supersession.

The two are genuinely different shapes and the distinction survives: ADR-0092
discharged ADR-0045 §5/§7/§10 without narrowing any sentence of ADR-0045 —
those sections *left a choice to a later lane*, and a lane taking it makes none
of their sentences false. §4 leaves no choice; it states a rule. A discharge that
also narrows a standing clause is both, and it is the narrowing that decides the
record.

**The record is therefore ADR-0093's `Status` line and its appended dated note,
both landing in this same change.** ADR-0110's pair is appended beside ADR-0095's
in the accumulating form ADR-0070 §4 and `docs/adr/template.md` require, and its
scope names exactly the sentence and exactly §3's case. ADR-0082 §2's rule that a
leading-token line carries no qualifier governs *amendments*; a partial
supersession is one of ADR-0070 §4's canonical status tokens and belongs on the
line, which is why an earlier draft's appeal to §2 here was misplaced. This
paragraph is left standing rather than rewritten so the argument that was made
and the answer it got are both legible — the practice ADR-0045's 2026-07-30 note
follows for its own overtaken paragraph.

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

**ADR-0046 §5 — nothing owed.** §5 rules that `write_atomic` does not close
#248's lost update, scopes the residual to "any two writers not sharing that
lock", and states its own firing condition — "If a composition ever does run two
writers on one store, closing #248 is that lane's trigger." §5a above reports
that the trigger has fired and makes the closure a prerequisite. Every sentence
of §5 stays true, including its ground for deferring: the surface is still
unbuilt, and this ADR still declines to design it. Firing a condition an earlier
ADR stated is using it as specified, not amending it. **Stacked addition; no
record owed.**

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
- **#248 acquires the consumer ADR-0046 §5 said would fire its trigger**, and §5a
  makes closing it — by a single serialised writer, or by that section's
  compare-and-swap — a hard prerequisite of the implementation rather than a
  follow-up. This is the one place this decision makes something *harder*, and it
  is a prerequisite for ADR-0045 §8's reason: a silent lost update that destroys a
  citation list under the cover of a retirement is worse than a lane that waits.
- **The implementing lane owes**: the `SourceReading` field and its value object
  with the additive migration story ADR-0093 §3's pattern implies; the
  reconciliation under §5's obligations and §5a's prerequisite, sequenced with the
  scheduler chunking work (#632, #710); and the conformance judgement §10 defers
  to it.
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
- **Design the compare-and-swap here**, so the reconciliation could ship without
  waiting. Rejected in §5a and §9: it needs a concurrency token on `MemoryRecord`,
  which is `core/types.py` surface ADR-0046 §5 scoped to its own lane and ADR-0045
  weighed and avoided for its blast radius, and it would be a second lane's
  contract decided inside this one. Naming the prerequisite costs a sentence and
  leaves the decision where it belongs; the disjunct's cheaper half — one
  serialised writer — needs no new surface at all.
- **Leave the writer surface open, as "a new `MemoryWriter` member or a widening
  of an existing one".** Rejected in §10, after an earlier draft did exactly this.
  Those are two Protocol surfaces, golden rule 5 makes either one a decision an
  ADR ratifies before implementation, and handing the choice to an implementation
  lane is what that rule exists to stop. `write_atomic` and `list_beliefs` carry
  the whole mechanism, so the deferral bought nothing.
- **Leave coverage's endpoint type to the implementing lane**, as ADR-0103 §9 left
  currency's representation. Rejected in §2: §9's own test is whether two lanes
  could make incompatible choices and both claim compliance, and instants versus
  dates versus source cursors give different answers to §3's containment question.
  The *name* passes that test and is left to the lane; the domain does not and is
  not.
- **Rule the enumeration's mechanics here too**, since §6 depends on one existing.
  Rejected as scope: they are the scheduler chunking-and-cursor lane's (#632,
  #710), and §6's monotonicity is
  precisely what makes deciding them separately safe.
