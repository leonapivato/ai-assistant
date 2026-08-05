# 103. Confidence is two quantities — the evidence for a belief, and whether it still holds

- Status: Proposed
- Date: 2026-08-05

## Context

Leg 7 of `docs/roadmap.md` — "Memory at volume" — has been carried since ADR-0072
as a single filed deferral, restated verbatim by two later ADRs. ADR-0072 §10
files **"Consolidation, decay, and salience — what happens to a derived belief
that is never reinforced and never corrected. Leg 7."** ADR-0073 and ADR-0077 §11
each carry it forward unchanged, naming this leg as its owner. This ADR answers
the *decay* half of that deferral, and nothing else in it.

### One float is being asked to hold two facts

`Provenance.confidence` has one ratified meaning, and it is a meaning about
**evidence**. ADR-0072 §3: "Confidence is the producer's belief strength. It is
not a relevance score, not a quality score, and not a priority." ADR-0077 §5
makes it a deterministic function of the epistemic step and the number of
distinct supporting episodes, with four ratified properties, of which one is
"non-decreasing in the number of supporting episodes, under a ceiling", and
another is "no clock, no randomness, no model-supplied number". Two `core`
validators pin its endpoints against the band: `Provenance._user_asserted_is_certain`
and `Provenance._derived_is_never_certain` (ADR-0077 §7).

The deferral this ADR answers asks for something that number cannot supply. The
roadmap's own phrasing is "confidence decay and salience so unreinforced beliefs
age instead of accumulating" — a *clock* on a quantity ADR-0077 §5 ratified as
having none, and an erosion of a quantity ADR-0072 §3 defined as the warrant a
producer has. Decaying `confidence` does not make a belief age. It makes the
system misreport how much evidence it has, and the misreport is permanent: the
episodes are still there, the fold that produced the number is still
deterministic, and the number no longer matches either. The one question the
whole provenance apparatus exists to answer — "why do you believe that?" — is
answered by the evidence, and a decayed strength answers it wrongly.

Yet the thing the deferral is *reaching for* is real. A belief the assistant
worked out eighteen months ago from three conversations has exactly as much
evidence today as it had then, and is much less likely to still be true. Both
sentences are true at once, which is the tell that there are two quantities and
one field.

### What is open, and what is not

**The fold's confidence rule is open.** ADR-0040 §1 defines `REINFORCE` and then
says: "How content and confidence combine is the applier's, not this ruling's
(§5a)", and that `MemoryIngestor` "implements them today with `_merge` (newest
content wins, evidence unioned, confidence maximised) … but *that* fold rule is
`memory`'s choice, as ADR-0028 §8 already holds, and this ADR does not promote it
to contract." §5a states the conformance obligation and its limit — "**`REINFORCE`
retains both records' `evidence`.** Everything else about the fold — which content
wins, how confidence combines, `last_updated` — is unasserted" — and then, in a
sentence ADR-0086's partial supersession does not reach, "Everything else ADR-0028
§8 excluded stays excluded: content precedence, confidence maximisation,
`last_updated`, the conflict threshold and limit, and the tuning check remain
`memory`'s own and unasserted."

So max-merge was never ratified, and this ADR supersedes nothing to rule on it.
Issue #646 states the opposite — it attributes both "newer content wins" and
`max` to ADR-0040 §5a as ratified rules — and that attribution is wrong on the
text. The defect #646 reports is real and reproduces; only its account of what
ratified the behaviour does not hold.

**Retrieval-side ranking is not open, and this ADR does not open it.** ADR-0072
§5 rules `MemoryStore.search` "band-neutral and confidence-neutral", on three
stated reasons, and puts precedence in the consumer, by band. Its consequences
name the price of changing that: "A future proposal to weight retrieval by
confidence has to supersede §5 rather than arrive as a tuning change." Splitting
the quantity does not buy an exemption from a rule about the store's ranking, and
this ADR claims none (§8).

### The defect that forces the fold question now

Issue #646: a `REINFORCE` whose target is an `EXTERNAL` record at confidence 1.0
— legitimate under ADR-0038 §2a — and whose incoming record is `OBSERVED` or
`INFERRED` produces `source=OBSERVED, confidence=1.0`, because `_merge` in
`memory/ingest.py` takes `source` from the incoming record and `confidence` as
the maximum — the fold `MemoryIngestor` routes a `REINFORCE` to. That
`Provenance` is refused by `Provenance._derived_is_never_certain`, the fold raises
a `ValidationError` out of `core`, and nothing is written. `_refuse_unsafe_fold`
does not catch it: its second clause fires only when the *incoming* record is
`USER_ASSERTED`. `DefaultMemoryPolicy` needs no unusual configuration to reach
it.

The two rules that collide are individually sensible, and the collision is where
the two quantities are visible. "Take the maximum" is right about *evidence* and
wrong about *what a derived source can warrant*. That is the whole of the bug.

### The framing question under everything in this leg

Every other fork in leg 7 — consolidation, eviction, ranking, the scheduler —
resolves differently depending on whether the leg is about **size** or about
**quality**. It is worth settling once, because the size reading is the one that
destroys evidence, and evidence is what this system's thesis is built on.

The arithmetic does not support a size reading. A stored belief is text plus one
vector; the vector's width is the embedder's (`Embedder.dimensions`, ADR-0006
§1), and at a common 768 float32 dimensions that is about 3 KB. A store holding a
million beliefs and episodes is therefore a few gigabytes of vectors and text of
the same order — on a data directory ADR-0083 §3 already requires to be local
storage. Years of ordinary use do not approach a pressure that would justify
deleting the record of why the assistant believes anything.

## Decision

### 1. Leg 7 is about quality, not size

> **Normative.** No decision in leg 7 may delete, expire, elide or weaken a
> belief, or the evidence behind a belief, in order to reclaim storage. A leg 7
> decision that removes or narrows anything states a warrant other than store
> size. This clause does not disturb ADR-0086 §1's citation bound, whose stated
> motivation is unbounded growth of one record's citation list under repeated
> folds rather than store size; ADR-0007 §2's retention deadlines; or the user's
> own `delete` and `clear`, which ADR-0007 §1 defines.

> **Normative.** Consolidation does not authorise deleting or expiring the
> episodes its output cites or derives from. A consolidated belief is an addition
> to the store's account of itself, never a replacement for the record it was
> derived from.

VISION §Principle 1 requires every inference to have evidence, confidence, scope
and a way to be corrected, and ADR-0072 §1 makes a derived belief re-derivable
"**while the observations behind it are still retained**" — a condition it calls
out as "not decorative", because a belief whose cited episodes are gone "is
neither re-derivable nor explicable". Reclaiming space by dropping episodes
converts a correctable model into an uncorrectable one, and does it silently.

**ADR-0007 §5's size-caps deferral is untouched and unrevoked.** It defers "which
records to evict when a cap is hit" to its own slice, and its "Revisit if" clause
stands as written. This ADR does not decide that slice; it removes one *reason*
from it, for the span of this leg. If measurement ever produces real size
pressure, ADR-0007 §5's own revisit clause is what reopens it, and this section is
revisited with it.

### 2. Confidence is two quantities

> **Normative.** A belief's provenance carries two distinct, separately readable
> quantities. **Evidence-strength** is how much warrant the evidence gives the
> belief — the quantity `Provenance.confidence` already carries under ADR-0072
> §3, unchanged in meaning. **Currency** is how far the belief should be trusted
> to still hold *now*. Neither substitutes for the other, and no surface renders
> one as the other.

The split is not a division of an existing number into halves. It is the
recognition that `confidence` has always been evidence-strength — ADR-0072 §3 and
ADR-0077 §5 both define it that way — and that the second quantity has never
existed. So nothing about `Provenance.confidence`'s meaning changes, no stored
record is reinterpreted, and both `core` validators keep binding exactly what
they bind today.

**The two quantities have different clocks and different causes**, which is why
one field cannot carry both. Evidence-strength changes when the *evidence*
changes, is deterministic on it (ADR-0077 §5), and is band-constrained. Currency
changes when *time* passes, is not a statement about evidence at all, and is
band-constrained in a different way — a `DERIVED` belief observed this morning is
perfectly current and still below 1.0 in strength, and an `ASSERTED` belief from
two years ago is at full strength and may be badly stale.

### 3. Evidence-strength ratchets; currency declines

> **Normative.** Evidence-strength does not decline with the passage of time, and
> no `REINFORCE` lowers it. It rises as agreeing evidence accumulates, under
> ADR-0077 §5's ceiling, and it otherwise moves only through a `SUPERSEDE` or a
> correction — which retire a belief and write another (ADR-0072 §4), rather than
> ageing the one that stands.

> **Normative.** Currency may decline with elapsed time since the belief was last
> confirmed. A decline in currency is never a decline in evidence-strength, and it
> does not reclassify a belief's band: band standing stays keyed on
> `Provenance.source` and never on either quantity (ADR-0072 §4). Whether lapsed
> currency may close a validity window is not decided here (§8).

The ratchet is the half that protects the thesis. An accumulated user model is
worth having only if the account of *how* it accumulated survives; a strength
that erodes on a clock is a system quietly forgetting its own reasoning while
keeping the conclusion. The decline is the half that makes the model honest about
time, and it is a new quantity precisely so that it can decline without taking
anything with it.

### 4. A lapsed `ASSERTED` belief is re-confirmed, never eroded

> **Normative.** An `ASSERTED`-band belief's evidence-strength never decays;
> ADR-0072 §3's reservation of 1.0 for the user's own word is unconditional in
> time. Where such a belief's currency has lapsed, the system's response is to
> **re-confirm it with the user**. Lapsed currency alone does not lower an
> `ASSERTED` belief's evidence-strength, does not retire it, and does not
> authorise acting on it as though it were fresh.

A user said it, and time does not unsay it. What time does is make it *possibly
out of date*, and the honest response to "possibly out of date" is a question, not
a quiet downgrade of the user's own word. ADR-0038 §3's one-way law and
`_refuse_unsafe_fold`'s first clause already refuse letting a derived signal
retire an assertion; letting a clock do it would reach the same outcome through a
mechanism with no signal at all, which is worse, because nothing observed
anything.

This clause rules the *response*, not its trigger or its plumbing: what counts as
lapsed is §5's deferred parameter, and how a re-confirmation is asked is ADR-0078's
durable-question machinery, which already exists and is not re-decided here.

### 5. The semantics are ratified now; the parameters are leg 8's

> **Normative.** This ADR ratifies the two quantities' semantics and no numbers.
> The decay function, its rate, and the staleness threshold at which lapsed
> currency triggers §4's re-confirmation are deferred to leg 8's measurement. A
> lane that must ship a schedule before that measurement exists names it
> provisional in its own ADR, and it is revisited when leg 8's data lands.

Splitting the two is what makes this ADR safe to ratify with no data. The
semantics are decidable from the corpus — ADR-0072 §3 already says what
`confidence` means, and it is not "how fresh". A half-life is not decidable from
the corpus, and a number invented here would arrive with the authority of a
ratified decision and the evidence of a guess. Leg 8's exit test is "'is the user
model getting more accurate?' is answered by data, not opinion", and a decay rate
is exactly that kind of question.

### 6. #646: a cross-band `REINFORCE` corroborates rather than accumulates

> **Normative.** A record's evidence-strength is admissible in the band its own
> `source` places it in. No fold installs a record whose evidence-strength its
> surviving band does not admit, and therefore no fold constructs a `Provenance`
> that `core` refuses.

> **Normative.** Where a `REINFORCE`'s target is in the `ATTESTED` band and its
> incoming record is in the `DERIVED` band, the fold takes nothing of the incoming
> record but its `evidence` and its effect on currency: the surviving record keeps
> the target's `source`, `attestation`, content and evidence-strength, its
> evidence is unioned under ADR-0086 §3's bound, and its currency is refreshed.
> The clause governs how such a fold folds and authorises none: a fold the writer
> boundary refuses stays refused (ADR-0045 §5). Every other pairing is left as it
> stands.

This is the ruling #646 asks for, and the split is what supplies it. Agreement
between a derived observation and a better-warranted record is genuine
information, and it is information about **currency**: the belief was seen to hold
again just now. It is not information about warrant, because the observation
supplies no warrant the target did not already have. Recording it as strength is
what produced the `ValidationError`; recording it as currency is what it actually
means.

**The clause is keyed on both bands, and that is deliberate rather than
economical.** The pairings are enumerable, and stating the rule as "a `DERIVED`
incoming record onto any other target" would have swept in the one pairing the
corpus refuses outright: nothing of any source folds onto an `ASSERTED` target
under either ruling (`_refuse_unsafe_fold` clause 1, ADR-0045 §5), so a clause
prescribing how that fold folds would prescribe a fold that may not happen. Naming
`ATTESTED` on the target side keeps the rule inside the reachable set. Of the
rest: a `USER_ASSERTED` incoming record is not in the `DERIVED` band, so the
existing fold stands and the assertion wins at 1.0, which is right; a `DERIVED`
target reinforced by an `EXTERNAL` record folds to `EXTERNAL` at up to 1.0, which
ADR-0038 §2a permits and the first clause admits; and same-band folds are
untouched. The one remaining pairing is #646's, and it is the one this clause
rules.

**The reverse pairing carries a milder version of the same question, and it is
not ruled here.** A `DERIVED` target at a strength above an `EXTERNAL` incoming
record's folds, today, to an `EXTERNAL` survivor carrying the higher number — a
strength the surviving source's own record did not supply. That is admissible
under the first clause, because the `ATTESTED` band admits it and `core` refuses
nothing; it produces no defect, no refusal and no lost attestation, and the
general question of what a source-changing fold may carry is wider than the
decision this ADR is. It is filed rather than absorbed (#733), which is what
`CLAUDE.md`'s triage rule asks of a finding outside the change.

**Keeping the target's content, and not only its strength, is deliberate.**
`Provenance.attestation` is present exactly when the band is `ATTESTED`
(ADR-0092 §1), so a fold that dropped the target's band would drop the record of
*who reported the belief and when* — which ADR-0073 §4 makes a disclosure
obligation, not a nicety. And a surviving record that kept the target's
attestation while carrying the incoming record's text would attribute to an
external system words it never reported. Neither half is available, so the
incoming record contributes evidence and currency, and nothing else.

**What is given up is named.** Where the derived incoming record's strength
happens to exceed the attested target's, today's `max` would raise the survivor's
number and this clause does not. That is the intended trade: the survivor is the
attested record, and a derived observation's strength is not a warrant that record
acquired by being agreed with. Nothing is destroyed — the observation's episode is
retained, cited, and available to propose the derived belief on its own terms.

### 7. This is `memory`'s semantics; the contract is not touched here

> **Normative.** §6 rules `memory`'s fold semantics and does not promote them to
> the `MemoryWriter` conformance suite. ADR-0028 §8's exclusion of the fold's own
> rule, and ADR-0040 §5a's statement that how confidence combines is unasserted,
> both stand. Whether any clause of this ADR becomes a conformance obligation is
> decided by the lane that implements it, in an ADR that names those clauses and
> applies ADR-0070 §1's test to them.

ADR-0040 §5a is explicit about why this line matters: "a writer that combines
confidence differently conforms, and must, or ADR-0028 §8's exclusion is void."
Promoting §6 to the suite would make that sentence false, which is an amendment
of two ratified ADRs and belongs to the change that makes it — with the record
ADR-0082 §1 requires, on those ADRs, in that lane. Ruling `memory`'s own
semantics needs none of that, because it is the thing ADR-0028 §8 and ADR-0040
§5a both say is `memory`'s to rule.

### 8. Currency has no retrieval-side role, here or by implication

> **Normative.** This ADR grants neither quantity any retrieval-side role.
> Whether and how currency reaches retrieval — through fork 4's validity
> machinery, through composition above the store seam, or through ranking inside
> `MemoryStore.search` — is the retrieval-ranking lane's decision, and that lane's
> ADR states which shape it takes and what ADR-0072 §5 costs under it. Nothing in
> this ADR is permission to weight `MemoryStore.search` by either quantity.

The tempting claim — that splitting the quantity lets currency feed ranking
without touching ADR-0072 §5 — is false, and stating it here would ratify a false
reading of a live decision. §5 is a rule about **what the store's ranking may
mix**, not about which field's name is on the multiplicand: it refuses the
product on the grounds that "relevance and belief strength are different axes"
and that "multiplying them yields a number that is neither", and both grounds
read on currency exactly as they read on strength. §5's second reason — that a
store which quietly down-ranks derived beliefs starves the loop those beliefs
improve through — reads on currency with more force, not less.

The clause is neutral in the other direction too, deliberately. ADR-0072's
philosophy is that standing is resolved on the write path and retrieval reads a
clean live set, and a maintenance path that acts on lapsed currency — closing a
validity window, or asking §4's question — delivers the same quality outcome with
§5 untouched. That is a genuinely open shape, and so is composition above the
seam, and so is in-store ranking at §5's stated price. Choosing among them needs
the measurement and the consumer that lane will hold. This ADR neither claims
currency ranks nor claims it never will.

### 9. What the implementing lane decides

> **Normative.** How the two quantities are represented on `Provenance` — field
> names, types, and whether currency is stored or computed — is the implementing
> lane's, subject to three constraints: both quantities are separately readable by
> a consumer; `Provenance.confidence`'s ratified meaning (ADR-0072 §3) is not
> silently reinterpreted; and no migration of an existing record fabricates a
> currency decline that was never measured.

> **Normative.** Where currency is computed rather than stored, it is computed
> from the instant the belief was last **confirmed**. `Provenance.last_updated` is
> not that instant and may not stand in for it: it is transaction time, the clock
> of the system revising its own belief (ADR-0045 §3). The implementing lane names
> the confirmation instant it reads for each band, and stores one where the record
> carries none.

> **Normative.** Currency's domain carries an explicit **unknown**, distinct from
> every value it can take. A belief whose confirmation instant the store does not
> hold — which is every record written before this decision — reads as unknown,
> and never as current. Unknown is not freshness: no surface or consumer renders
> or treats an unknown currency as a confirmed one. Whether an unknown currency
> triggers §4's re-confirmation, and on what schedule, is a parameter question and
> is deferred with the rest of them (§5).

Deferring surface until a consumer exists is this repository's standing
discipline — ADR-0072 §7 deferred a read's signature on exactly that ground, and
ADR-0028 §7 declined batch ingestion on it. What is *not* deferred is the
semantics, because that is what the implementing lane would otherwise have to
invent, and what golden rule 5 requires to be ratified ahead of it: this is a
`core` type that crosses subsystem boundaries, so the decision lands as its own
PR before anything implements against it (ADR-0015 §5).

**The line between what is ruled and what is deferred is "could two lanes make
incompatible choices and both claim compliance?"** A field name cannot fail that
test — a second implementation choosing a different one is a rename, and the
conformance question is whether the quantity is readable at all, which the first
clause pins. The *domain* can fail it, and does: a lane that reads a migrated
record as fully current and a lane that reads it as unknown have made different
decisions about what the system claims to know, and both would have satisfied this
section as it stood before the third clause was added. So the domain is ruled here
and the representation is not, and the third clause exists because that is
precisely where the deferral was too wide.

**Unknown is a distinct state because an unmeasured currency and a fresh one are
different facts.** This is ADR-0086 §4's distinction one quantity over: an elision
"is not a tombstone, and the two are different facts", because a surface that
renders them alike "tells the user their data was lost when it was not". Reading
a legacy record as current tells the user the assistant confirmed something it
never confirmed — the same error, in the direction that flatters the system. And
the alternative failure is real too, which is why the third constraint on the
first clause stays: reading it as *stale* would fabricate a decline nobody
measured. Neither invention is available, so the honest value is neither, and a
domain with only numbers in it has nowhere to put that.

The third constraint is the one worth stating out loud. A store migrated forward
holds records whose currency was never observed; deriving a decline for them from
a rate nobody has measured (§5) would manufacture staleness the system never saw,
and §4 would then start asking the user to re-confirm things on the strength of an
invented number.

**The confirmation clock is a separate clause because the obvious field is the
wrong one.** `Provenance.last_updated` is the instant a currency computation would
reach for, and it is transaction time — "the clock of the store changing its mind,
not the clock of when the belief holds". The `ATTESTED` band makes the gap
concrete rather than theoretical: ADR-0092 §3 rules that `Attestation.reported_at`
is the source's own clock, that it is "never reconciled with ours", and that
"`reported_at` earlier than `last_updated` is the normal case, not an anomaly". A
calendar's months-old report imported this morning has a `last_updated` of this
morning, so a currency read off transaction time would call it perfectly fresh —
which is not a rounding error but the exact inversion of what §3 defines currency
to measure. Where a band's confirmation instant is not on the record at all, the
lane stores one rather than substituting the nearest field that is.

> **Normative.** Where a belief's currency has lapsed, a surface that renders the
> belief conveys that alongside its evidence-strength. The wording is the
> prompt-assembly lane's, as ADR-0072 §6 already rules.

ADR-0072 §6 requires provenance to survive the last hop into the prompt, because
"provenance has to survive the last hop into the prompt, or the correction loop
has no trigger". A lapsed belief rendered with its strength alone states a warrant
the system no longer stands behind at face value, which is the same laundering §6
exists to stop, one quantity over.

### 10. What this ADR records against earlier ADRs: nothing

The judgement ADR-0082 §1 requires is made here, clause by clause, by applying
ADR-0070 §1's test to each earlier ADR's text: would a reader holding only that
ADR now act differently, or read one of its clauses more widely than it now holds?

- **ADR-0040 §1, §5a and ADR-0028 §8.** Both leave the fold's confidence rule to
  `memory` and say so in terms. §7 declines to promote §6 to the suite precisely
  so that neither sentence becomes false. A reader holding only ADR-0040 still
  builds a conforming writer. **Stacked addition; no record owed.**
- **ADR-0072 §3, §4, §5, §6.** §3's definition of `confidence` is adopted
  unchanged, not narrowed. §4's rule that standing is keyed on `source` is
  restated and relied on. §5 acquires no exception and is granted none (§8). §6
  gains a further thing to convey and loses nothing it required. **Stacked
  additions; no record owed.**
- **ADR-0077 §5, §7.** The ratchet is §5's "non-decreasing … under a ceiling"
  property applied over time rather than over support, and §7's validator is
  relied on rather than relaxed — §6 exists to stop the fold reaching it.
  **No record owed.**
- **ADR-0007 §5 and ADR-0086 §1.** §1 above names both as untouched, and its own
  clause carries the exemption rather than leaving it to prose. **No record
  owed.**

Under ADR-0082 §1 a record is owed "exactly when the later ADR amends a named
clause of that earlier ADR", and "absent a clause that fails §1's test, there is
nothing to record". No clause of any ADR above fails it.

## Consequences

- **#646 has a ruling and a lane.** The implementing lane applies §6 in `_merge`
  (`memory/ingest.py`), and owes the regression test #646 records as missing on
  both trees. Whether `FakeMemoryWriter` follows it, and whether the conformance
  suite grows a cross-band case, is that lane's under §7 — and if it rules yes, it
  owes the ADR-0082 §1 records §7 declines to make here.
- **`Provenance` grows surface in the implementing lane**, which is why this is a
  contract-surface decision reviewed under both the adversarial and the
  architecture lens even though the diff is prose (`CONTRIBUTING.md` → "Stop when
  the required reviews are green").
- **The decay half of ADR-0072 §10's deferral closes; salience and consolidation
  stay open.** ADR-0073 and ADR-0077 §11 carry the same deferral and are
  correspondingly narrowed. Nothing here decides what a *salient* belief is.
- **The retrieval-ranking lane inherits a genuinely open question**, not a
  settled shape (§8), and the validity/demotion lane inherits a second reason to
  exist: it is the mechanism under which currency acts without §5 moving at all.
- **Two quantities cost more everywhere they are read.** Every producer, every
  renderer and every export gains a second number to carry and a second way to be
  wrong about it. That is the price of the ratchet, and it is paid deliberately:
  one number that means two things is cheaper to write and impossible to answer
  "why do you believe that?" from.
- **Revisit if** leg 8's measurement shows re-confirmation is too noisy to run at
  any threshold (§4's response, not its parameters, would then be back open), if
  currency proves to need storing rather than computing (§9), or if real size
  pressure ever materialises, which reopens §1 through ADR-0007 §5's own revisit
  clause.

## Alternatives considered

- **Decay `confidence` in place**, as the roadmap's wording suggested. Rejected:
  it contradicts ADR-0077 §5's "no clock" property, erodes the ratified meaning
  ADR-0072 §3 gives the field, and makes the system misreport its own evidence
  permanently. It also cannot be undone by re-observation without inflating the
  number, which ADR-0077 §5 was built to prevent.
- **Rule the decay parameters here too.** Rejected under §5: a rate invented
  without measurement would carry ratified authority on guessed evidence, and leg
  8 exists to supply exactly that data.
- **Fix #646 by clamping the folded strength just below 1.0** when the surviving
  band is `DERIVED`. Rejected: the `DERIVED` ceiling is an open bound with no
  greatest admissible value, so the clamp needs an invented epsilon — a decay
  parameter by another name — and it still leaves a derived record claiming a
  warrant its source never supplied.
- **Fix #646 by refusing the fold with a named `MemoryStoreError`**, #646's third
  option. Rejected: it is legible, but it discards real information. The derived
  observation genuinely agreed with the target, and under the split there is a
  correct place to put that agreement. A refusal would be the right answer only if
  there were nothing true to record.
- **Fix #646 by taking the incoming record's strength rather than the maximum**,
  #646's second option. Rejected: it lands the survivor in the lower band with the
  weaker warrant, so an external system's certain report is demoted to a guess
  because a guess agreed with it, and the attestation is lost with the band.
- **Split the quantity and let currency feed ranking**, as issue #729's body
  proposed. Rejected under §8: ADR-0072 §5 governs what the store's ranking may
  mix, not which field feeds it, and its own consequences name supersession as the
  price. Ratifying the dividend here would have ratified a false reading of a live
  decision.
- **Rule "no eviction, demotion instead" here**, since §1's framing implies it.
  Declined as scope: the demotion mechanism is bi-temporal validity, which is its
  own lane with its own `core` surface. §1 rules out the *reason* for eviction and
  leaves the mechanism to the lane that builds it.
