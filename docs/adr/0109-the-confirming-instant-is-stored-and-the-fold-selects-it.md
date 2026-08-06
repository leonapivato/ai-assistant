# 109. Currency's confirming instant is stored on `Provenance`, and the fold selects it at fold time

- Status: Proposed
- Date: 2026-08-06
- **This is a contract change.** §2 adds one optional field to `Provenance` in
  `core/types.py` — a type every subsystem that proposes, stores, folds or
  renders a belief holds, and which `Goal` carries too (ADR-0068 §2).
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation" puts "a
  Protocol **or a `core` type that crosses subsystem boundaries**" in its own PR,
  ratified before the implementation PR that depends on it (golden rule 5,
  ADR-0015 §5), and states the limit outright: "what must not happen is the
  implementation landing *with* the ADR that justifies it". So **no code changes
  with it** — the field, the fold, the four producers, the canonical fakes and
  their tests are a later lane (§10). This is the shape ADR-0092 took for one
  field on this same type, ADR-0086 for `evidence_elided`, ADR-0106 §2 for the
  taint marker, and ADR-0107 for the two inspection DTOs.
- **Required review set: adversarial *and* architecture**, though the PR carrying
  it is prose only. It decides `core/types.py` surface, which is what
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes
  contract-surface: a change is contract-surface "when it is the ADR deciding
  that surface". Worth stating because it is not mechanical here —
  `scripts/ship.sh` fires its architecture requirement on a diff touching
  `src/ai_assistant/core/protocols.py` or `src/ai_assistant/core/types.py`, and a
  docs-only PR deciding those files trips neither. The requirement is
  `CONTRIBUTING.md`'s, not the script's.
- **`Proposed` here, and the flip is a separate PR.** ADR-0015 §5 has a contract
  ADR reviewed while it is still `Proposed`, so a finding can still change the
  decision; #633 records why the ratifying edit cannot ride in this PR — flipping
  the `Status` line after the reviews are recorded changes the content the head
  carries, which is precisely what `just ship`'s anchor refuses (ADR-0027 §2).
  So the `Proposed` → `Accepted` edit is its own trivial PR (`CONTRIBUTING.md` →
  "Trivial ADR edits"), in ADR-0104's, ADR-0107's and ADR-0108's shape.
  **Ratification is not this lane's.**
- **This ADR takes ADR-0103 §9's representation deferral and answers ADR-0103
  §7's conformance question.** It supersedes no clause of any ADR. One record is
  owed — a dated note on ADR-0103 — and §13 applies ADR-0070 §1's test to a
  further eleven ADRs, in nine entries, and finds none owed. **The note lands in
  this same change**, so no reader ever holds an ADR-0103 whose deferral is discharged somewhere it cannot
  see (ADR-0082 §7; the shape ADR-0107 §11 argued and the deferred shape its own
  round-1 `blocker` refused).
- **Closes #741.** Its seam — that ADR-0103 §9 says "the most recent confirming
  instant" where §6 says "usable" — is settled by §7 below and recorded in the
  same dated note.
- **Reference convention.** A bare `§N` in this document is **this** document's
  section N. Every reference to another ADR's section carries that ADR's number,
  and a self-reference sharing a paragraph with a foreign one is written
  `§N above`. The one exception is §13, whose entries each open by naming the ADR
  they are about, after which a bare `§N` is that ADR's — the form ADR-0107 §11
  uses. This ADR's sections and ADR-0103's overlap almost entirely in number, so
  the convention is stated rather than left to context.
- **Refs:** ADR-0103 §6/§7/§9 (the decision this implements the representation
  of), ADR-0086 §3/§4/§5 (the citation bound, the elision precedent and the
  fingerprint question), ADR-0081 §1 (the writer's store-free predicate),
  ADR-0007 §2 (read-time retention), ADR-0092 §1/§3 (the attestation and its
  clock), ADR-0078 §7 (the fingerprint projection), ADR-0106 §2/§3 (the other
  field this type is owed, and who computes a producer's field), ADR-0040 §5a and
  ADR-0028 §8 (the fold is `memory`'s), ADR-0045 §3 (transaction time),
  ADR-0089 (marking), ADR-0070 and ADR-0082 (amendment and where a record goes);
  #744, #741, #742, #646, #729.

## Context

### What ADR-0103 ratified, and the one thing it left open

ADR-0103 §2 splits `Provenance.confidence` into two quantities:
**evidence-strength**, which `confidence` already carried, and **currency**,
"how far the belief should be trusted to still hold *now*", which has never
existed. §9 then rules currency's domain and its confirming events in detail,
and its first normative clause leaves exactly one thing to the implementing lane
— quoted here without its mark, which belongs to ADR-0103 and not to this
document:

> How the two quantities are represented on `Provenance` — field names, types,
> and whether currency is stored or computed — is the implementing lane's, subject
> to three constraints: both quantities are separately readable by a consumer;
> `Provenance.confidence`'s ratified meaning (ADR-0072 §3) is not silently
> reinterpreted; and no migration of an existing record fabricates a currency
> decline that was never measured.

§9 is explicit about where it drew that line: "**The line between what is ruled
and what is deferred is 'could two lanes make incompatible choices and both
claim compliance?'**" A field name cannot fail that test — "a second
implementation choosing a different one is a rename". The *domain* can, and §9
rules it: unknown is a distinct state, every pre-decision record reads as
unknown, and no surface renders unknown as confirmed.

Issue #744 is the boundary written down. Its central finding is that the
deferred question is **not** a rename after all, because "whether currency is
stored or computed" is one of the three things §9 handed over, and the two
answers diverge observably. That is this ADR.

### The fork, and the finding that decides it

For two of the three bands the confirming instant is already on the record. §9:

> A belief is confirmed by the event that establishes it in its band — for
> `ASSERTED`, the user stating it, or answering §4's re-confirmation; for
> `ATTESTED`, the reporting source's report, whose instant is
> `Attestation.reported_at` (ADR-0092 §3) and never our ingestion of it; for
> `DERIVED`, the most recent observation supporting it, the latest `occurred_at`
> among the episodes `Provenance.evidence` cites, and never the moment of
> derivation.

The `DERIVED` arm is the one that forks. Those `occurred_at` values live on the
**episodes**, not on the `Provenance` in hand, so a lane either **stores** the
instant on the record when the belief is proposed, or **resolves** it later by
reading the cited episodes out of the store.

PR #742's adversarial review found the case where the two answers differ, and it
is recorded on #744 as this lane's sharpest constraint. `_merge` unions both
records' `evidence` and applies ADR-0086 §3's bound, keeping the **last**
`MAX_EVIDENCE_CITATIONS` entries of an accumulation-ordered tuple. `Provenance`
carries no `max_length` — deliberately, because a validator "runs on
*deserialisation* as well as on construction" and would fail a read on a record
a running deployment already holds (ADR-0086 §2) — so an incoming proposal may
legitimately arrive with more citations than the bound. When it does, some of
its own citations are displaced, and **accumulation order is not `occurred_at`
order**, so the displaced one can be the episode carrying the latest instant.
`evidence_elided` retains a count and never an id (ADR-0086 §4), so after the
fold that instant is not recoverable from the survivor.

A resolver therefore reads "latest `occurred_at` among the *retained*
citations", which is §9's definition applied to the tuple the record actually
carries and is conformant on its face. ADR-0103 §6 says something else about the
same survivor:

> its currency is measured from the later of the two records' **usable**
> confirming instants, an instant being usable when the store holds it and it is
> not in our future (§9) — from whichever one is usable where only one is, and as
> **unknown** only where neither is. It is never measured from the moment of the
> fold.

"The two records'" instants are the instants **as they stood at fold time**,
before the bound displaced anything. In the at-capacity, out-of-order case a
resolver and a stored field return different instants and each can claim
compliance — which is §9's own stated test for what must be ruled rather than
left open, arriving inside the deferral §9 left.

### Two more grounds, and one that had to be restated against the tree

**A resolver couples currency to evidence retention.** Episodes expire, and
ADR-0007 §2 enforces that at *read* time: "a record whose `expires_at` is in the
past is treated as **already forgotten** — `get` returns `None` for it; `search`
never includes it", regardless of whether `purge_expired` has run. Citations are
bounded besides (ADR-0086 §3). So under a resolver a belief's currency silently
declines as its evidence ages out or is displaced — a decline nobody measured,
from a rate ADR-0103 §5 has deferred to leg 8. That is the manufactured
staleness ADR-0103 §9's third constraint refuses on the migration path and
ADR-0103 §6's unknown-does-not-spread paragraph refuses at the fold, reached by
a third route. A stored instant is a measurement made once, at the confirming
event, and retention cannot unmake it.

**The writer cannot do the resolver's job at the point ADR-0103 §6 needs it
done, and the precise reason is worth stating rather than paraphrasing.**
`_merge` is a module-level function over two records — it holds no store.
`MemoryIngestor` *does* hold one, so the resolver is not literally unreachable;
what it costs is what ADR-0081 §1 declined to spend, in that clause's own words
about its self-citation predicate: it "costs no `get`, adds no I/O to a section
that holds the ingestor's lock, introduces no new read-modify-write window, and
— unlike its own §5's resolvability check — cannot itself be raced, because
every input is already fixed and private to the call". A fold that resolved
episode instants would take all four costs back, and the race it would take back
is the one that matters here: it would be racing episode expiry, which is ground
two above with a lock around it. The stored field keeps ADR-0103 §6's selection
inside the property ADR-0081 §1 built.

### Read against the tree, because five of the claims are about code

Every claim below was re-read at this ADR's base rather than carried from #744's
text, and two of them come back smaller than the issue priced them.

- **`_merge` in `memory/ingest.py` composes `Provenance` field by field** on both
  arms — the ADR-0103 §6 corroboration arm and the ordinary one — and its
  docstring already records the gap: "**Currency is not written here, because
  nothing represents it yet.** … this function has no store to read them from."
  So the fold is one construction site, not a scatter.
- **`FakeMemoryWriter` in `ai_assistant.testing` carries its own copy of the
  fold**, with the same two arms. Whatever the fold does, it is implemented twice.
- **Four production sites construct a `Provenance` for a record or a goal**:
  `readers/calendar.py` (`EXTERNAL`, holding the occurrence's `DTSTAMP` as
  `reported_at`), `learning/observer.py` (`OBSERVED`/`INFERRED`, holding the batch
  of `EpisodicMemory` it cited), `learning/processor.py` (`USER_ASSERTED`, holding
  the feedback event's `created_at`), and `orchestration/conversations.py`
  (`OBSERVED`, capturing an episode). A fifth, `orchestration/loop.py`, builds a
  `Goal`'s provenance. Every one of them holds its confirming instant already, or
  holds nothing that could be one — which is what makes §4 below cheap.
- **The SQLite store needs no migration and no column.** `SqliteMemoryStore`
  persists each record as `record.model_dump_json()` in a `data` column and
  decodes it back through pydantic; the only columns derived out of the blob are
  `expires_at`, `valid_until` and `about_person`, each because something filters
  on it. An additive field with a `None` default therefore decodes on every stored
  record as `None`, and `_migrate_records` gains nothing to do. This is exactly
  ADR-0086 §4's "**It is additive with a default**, so a stored record written
  before this ADR deserialises with `evidence_elided=0` and nothing migrates",
  one field over — and it means ADR-0103 §9's fourth clause ("every record written
  before
  this decision reads as unknown") is satisfied *structurally*, by the default,
  rather than by a migration anyone has to write correctly.
- **`Provenance` never crosses `wire/`.** No module under `wire/` names
  `Provenance`, `MemoryRecord` or `Goal`; the local API projects the engine's
  DTOs, and `MemoryStore.export` — which does return records whole (ADR-0007 §3)
  — is not on the promoted engine surface. So there is no codec change and no
  frame-size question (ADR-0084 §3).

Issue #744's "corpus-wide change" paragraph priced "the SQLite codec, its
migration, and the conformance suites that would pin whichever half becomes
contract". The codec and the migration come off that list on the evidence above;
the producers, the fakes and the tests stay on it. The cost is real and is
accepted either way — it is simply smaller than the issue that filed it could
see.

### The seam #741 records, and why a stored instant is the thing that closes it

#741 reports that ADR-0103 §9's second and third clauses say "the most recent
confirming instant" without ADR-0103 §6's qualifier, and gives the case: an
`ATTESTED` target whose `reported_at` is future-dated, and a `DERIVED` incoming
record whose latest supporting `occurred_at` is in January. **ADR-0103 §6 says
January.** A reader applying ADR-0103 §9's clauses to the *set* of confirming
instants, taking "most recent" at face value, picks the future one and reaches
unknown. #741 is careful that this is not an inconsistency — ADR-0103 §6 is the
more specific rule and names the case in the paragraph below the clause — and
asks only whether a one-word appended note would make ADR-0103 §9
self-contained.

Under a stored instant the seam does not need to be read carefully; it stops
existing. A record carries **one** instant, so "most recent" has nothing to
select over at read time. The only place two candidates are ever compared is the
fold, where ADR-0103 §6 governs and ADR-0103 §6 is qualified. §7 below records
that and the note is written anyway, because a reader who never reaches this ADR
still reads ADR-0103 §9 alone.

### Why this is worth deciding before there is a consumer

Nothing reads currency today: ADR-0103 §8 grants it no retrieval-side role,
ADR-0103 §5 defers the decay function and the staleness threshold to leg 8's
measurement, and ADR-0103 §4's re-confirmation trigger is deferred with them.
#744 names that as a reason the lane could wait. It is a reason the *rendering*
can wait, and §12 below lets it. It is not a reason the representation can, for
one reason that gets more expensive every week: **the instant can only be
captured while the confirming event is in hand.** A record written today with no
confirming instant reads as unknown forever (ADR-0103 §9's fourth clause is
explicit that no migration may invent one), so every day the decision waits is
another day of beliefs that can never answer "when was this last confirmed?" —
and unknown is the one value ADR-0103 §9 forbids anyone from improving after the
fact.

## Decision

### 1. The confirming instant is stored on the record, never resolved from the store

> **Normative.** A belief's confirming instant is data the record carries. A
> consumer or a writer that needs it reads that field, and never reconstructs it —
> not from the episodes the record cites, not from any other record, and not from
> another field of the same `Provenance`.

> **Normative.** Currency itself — the elapsed interval — is never stored. It is
> computed at read, against the reading component's clock, from the stored
> instant.

The fork §Context poses resolves to the first horn, on the three grounds argued
there: the displacement case makes a resolver and a stored field disagree
exactly where ADR-0103 §6 rules; a resolver couples currency to evidence
retention and so manufactures a decline nobody measured; and ADR-0103 §6's
fold-time selection is only implementable without a store read if the instant is
on the record.

**The two halves of the clause pair are not in tension, and the split is where
ADR-0103's own reasoning puts it.** The instant is a *measurement*, made once,
when something confirmed the belief; the elapsed interval is a *derivation* from
that measurement and a clock, and it is different every time it is asked for.
Storing the derivation would be storing a number that is stale before it is
committed — which is the shape ADR-0077 §6 refused for presented confidence ("a
number computed at presentation cannot reorder a store it never touches"), and
the reason nothing here reaches ADR-0072 §5's ranking rule at all (ADR-0103 §8).

**What "separately readable" means under this representation**, since it is the
first of ADR-0103 §9's three constraints. Evidence-strength is read from
`Provenance.confidence`; currency is read from the stored instant plus a clock.
Neither is derived from the other, neither has to be disentangled from the
other, and `confidence`'s ratified meaning (ADR-0072 §3) is untouched — which is
ADR-0103 §9's second constraint, satisfied by adding a field rather than
reinterpreting one.

### 2. The field: `last_confirmed_at`, optional, and `None` is the unknown

> **Normative.** `Provenance` carries `last_confirmed_at: UtcInstant | None`,
> defaulting to `None`: the instant of the most recent event that confirmed this
> belief, on the clock of whatever confirmed it.

> **Normative.** `None` is ADR-0103 §9's **unknown** — the state of a record whose
> confirming instant the store does not hold. No surface, consumer or writer
> renders, treats or ranks an unknown as a confirmed one, and none reads it as
> stale either.

**The name is the rename-class half of ADR-0103 §9's deferral, and it is chosen
against two neighbours rather than for its ring.** ADR-0103 §9 spends a
paragraph refusing `Provenance.last_updated` as the clock — "it is transaction
time, the clock of the system revising its own belief" — and the field that must
not be confused with it is the field that should sit beside it and read as its
opposite number: `last_updated` is when *we* last changed our mind,
`last_confirmed_at` is when the *world* last confirmed the belief. The bare
`confirmed_at` was rejected because `UserConfirmation.confirmed_at` already
exists in `core/types.py` meaning "when the user's answer was given" — a single
event, not a running maximum — and two fields with one name and different
arities is the kind of near-collision a reader resolves wrongly once and then
trusts. `last_` also carries ADR-0103 §9's "most recent", which §5 and §6 below
are the rules that maintain.

**`| None` rather than a required field, and the alternative is not available.**
ADR-0086 §3 states the test for a `core` validator — "not 'is it a validator on
a `core` type' but 'does it refuse something that already worked'" — and a
required instant refuses *every record ever stored*, on the read path, at
deserialisation. That is the failure ADR-0086 §2 declined a `max_length` to
avoid, at its widest possible scope. The optional field with a `None` default is
the only shape that admits the corpus as it stands, and ADR-0103 §9's fourth
clause independently demands the same outcome: every pre-decision record reads
as unknown.

**`UtcInstant`, because the corpus has one instant type and this is an
instant.** `Provenance.last_updated`, `Attestation.reported_at` and
`EpisodicMemory.occurred_at` are all `UtcInstant`, and its `AfterValidator`
enforces tz-awareness. The values this field takes come from exactly those three
fields (§4), so a different annotation would be a conversion for nothing.

**It carries no meaning on a `Goal`, and that breadth is accepted rather than
fixed.** Every `Goal` carries a `Provenance` (ADR-0068 §2) and reaches no
propose/dispose gate, so a goal's `last_confirmed_at` is `None` unless some
future producer sets one. That is the same harmless breadth ADR-0086 §4 accepted
for `evidence_elided` and ADR-0077 §7's validator accepted before it: a goal is
not a belief whose currency lapses, and a type-level exclusion would cost a
validator that refuses something rather than a field that says nothing.

### 3. Currency is computed at read, and this ADR adds no surface for computing it

> **Normative.** A component computing a belief's currency reads
> `last_confirmed_at` and its own clock, and yields ADR-0103 §9's unknown — never
> a number and never a default — where the field is `None` or where the instant is
> in that component's future.

> **Normative.** This ADR adds no property, helper or type expressing the elapsed
> interval, and no consumer is obliged to compute one. The shape a computed
> currency takes is the first consumer's, decided with the parameters ADR-0103 §5
> defers to leg 8.

**Deferring the computed shape is not the same as deferring the domain**, and
ADR-0103 §9's own line between them is what separates these two clauses. The
domain fails ADR-0103 §9's "could two lanes make incompatible choices and both
claim compliance?" test — one lane reading a `None` as fresh and another as
unknown ship different claims about what the system knows — so the first clause
rules it here. The *shape* of the interval passes that test the way a field name
does: a `timedelta`, a bucketed enum and a boolean past a threshold are renames
of each other until ADR-0103 §5's threshold exists, and inventing one now would
be a decay parameter smuggled in as a type.

**The future-instant arm is ADR-0103 §9's, restated at the read rather than
re-decided.** ADR-0103 §9 rules that a confirming instant in our future makes
the elapsed interval unmeasurable and the currency unknown, that the instant is
"neither refused nor rewritten (ADR-0092 §3)", and that no freshness is
projected through it. Under a stored field that ruling has exactly one place to
act — the read — and the first clause puts it there. §5 is the only other place
a future instant is examined, and it examines it to *choose between two*, never
to rewrite one.

### 4. What a producer supplies, and who computes it

> **Normative.** A producer proposing a belief sets `last_confirmed_at` to the
> instant of the event that confirms it in its band, as ADR-0103 §9 rules that
> event: for `ASSERTED`, the instant the user stated it or answered ADR-0103 §4's
> re-confirmation; for `ATTESTED`, the `Attestation.reported_at` it carries; for
> `DERIVED`, the latest `occurred_at` among the episodes it cites.

> **Normative.** A producer that holds no confirming event for the record it
> proposes writes `None`, and that record reads as unknown. It never substitutes
> its own clock, `Provenance.last_updated`, or any other instant that is in reach.

> **Normative.** `last_confirmed_at` is computed by the component that selected the
> confirming event, from data that component holds, and is never taken from a
> model's output. A value a model-backed producer emitted for it is discarded
> rather than merged (ADR-0106 §3).

> **Normative.** A producer writes its band's instant as it stands and applies no
> usability test to it: an instant in our future is stored unchanged (ADR-0092 §3)
> and reads as unknown (§3). The usability test belongs to the fold alone (§5),
> where there are two candidates to choose between.

**Each band's event is ADR-0103 §9's, and this clause adds nothing to it** — it
says only where the value comes from and who computes it. The reason is the one
ADR-0103 §9 gives for ruling the events at all: two lanes reading "last
confirmed" differently "would ship different answers to 'does the assistant
still believe this?' while both satisfying a clause that named neither."

**The third clause is ADR-0106 §3 one field over, and it is load-bearing here
for the same reason.** ADR-0106 §3 has `derived_from_external` computed by "the
component that **selected the input set**", discarding any value the producer
emitted, on ADR-0098 §4's ground that a rule is "fail-closed against a producer
that forgets, because the producer never had the choice", and on ADR-0094 §5's
that "a claim carried in a submission is not evidence of the standing it
claims". A model asked to emit a timestamp is a producer declaring its own
currency, and the failure that matters is not over-claiming but omitting. The
tree already works this way for the neighbouring field: `LearningObserver` maps
the model's citation labels back onto the ids of the episodes it selected and
computes `confidence` deterministically from the step and the citation count, so
"the citations are ours, never the model's". The latest `occurred_at` over that
same selected set is ours by the same construction — the observer is handed
`Sequence[EpisodicMemory]` and holds every `occurred_at` in the batch.

**The fourth clause is what keeps the producer and the fold from disagreeing
about a future instant.** A producer that dropped a future-dated `reported_at`
to `None` would destroy the very thing §5 needs to compare, and would do it by
the route ADR-0092 §3 closes: "a `reported_at` in our future is not refused",
because source clocks skew and refusing one invents a read-path failure. So the
record keeps what the source said, the read reports unknown, and the fold — the
only place a choice exists — makes it.

**The `ASSERTED` instant is the utterance's, not the write's**, which follows
ADR-0103 §9's "the user stating it" and matters for the same reason its other
two arms name their events: `learning/processor.py` builds its provenance from a
`FeedbackEvent` and already has `event.created_at` in hand, and using the ingest
clock instead would make a re-processed feedback event look freshly confirmed.
The same discipline that keeps `ATTESTED` off our ingestion clock and `DERIVED`
off the moment of derivation keeps `ASSERTED` off the moment of the write.

**An episode is not a belief that lapses, and it takes `None`.** The capture
path in `orchestration/conversations.py` writes an `OBSERVED` `EpisodicMemory`,
which is in the `DERIVED` band and cites nothing — deliberately, because "an
episode is the terminal citation — the thing other records cite — so requiring
it to cite something would demand a regress". ADR-0103 §9's derived rule ranges
over the episodes a record cites, and over the empty set it yields nothing, so
the second clause applies and the record reads as unknown. That is the honest
answer rather than a gap: an episode records that something happened, nothing
retires it, and "is this still true?" is not a question about it. Writing its
own `occurred_at` into the field would make an episode claim a currency it has
no use for and would put a value in the field for every episode in the store,
where ADR-0103 §9's unknown is exactly right.

### 5. The fold selects at fold time, from the two records and its own clock

> **Normative.** Where a `REINFORCE` folds, the survivor's `last_confirmed_at` is
> the later of the target's and the incoming record's **usable** values; the usable
> one where only one is usable; and `None` where neither is. An instant is usable
> when it is not `None` and not in the writer's future at the moment of the fold.

> **Normative.** The fold computes that selection from the two records in hand and
> the writer's own injected clock, and from nothing else. It performs no store
> read, and it never writes the moment of the fold as the survivor's
> `last_confirmed_at`.

This is ADR-0103 §6's third contribution, made implementable. That section
already ruled the composition — "the later of the two records' **usable**
confirming instants … from whichever one is usable where only one is, and as
**unknown** only where neither is … never measured from the moment of the fold"
— and the first clause restates it over the stored field rather than re-deciding
it. What is new is the second clause, and it is what makes the first one true of
the code: the selection reads two values the fold already holds.

**This is where the displacement finding is dissolved rather than mitigated.**
The fold's inputs are the two `last_confirmed_at` values, which were computed by
their producers when the confirming events were in hand — that is, **before**
ADR-0086 §3's bound ever applied. So the union may displace the very citation
whose `occurred_at` supplied the incoming record's instant, and the survivor
still carries that instant, because the instant stopped depending on the
citation list at the moment the proposal was authored. ADR-0086 §3's bound is
untouched, ADR-0103 §1's promise not to disturb it holds, and the interaction
#744 records simply has nowhere left to act. The alternative — computing before
the bound but *inside* the fold — is not available: the fold would need the
episodes, which is the store read §Context rules out.

**The clock is load-bearing, and #741's own worked example is the proof.** Take
#741's pair: an `ATTESTED` target whose future-dated `reported_at` §4 stored
unchanged, and a `DERIVED` incoming record whose instant is January. A fold that
selected "the later present value" would take the future one, and §3's read
would then report unknown for a belief with a perfectly good January
confirmation on the other side — "the same manufactured staleness ADR-0103 §9's
third constraint refuses on the migration path", reached at the fold, which is
exactly the spreading ADR-0103 §6's unknown-does-not-spread paragraph refuses.
Selecting over *usable* values takes January. So the fold needs to know what
"our future" means, which is a clock; and `MemoryIngestor` already holds one,
injected and guarded (`core.clock`), so this costs a parameter and no new
dependency.

> **Normative.** The fold's usability test reads the ingestor's injected clock,
> never a module-level wall clock, so the selection is deterministic under test.

**A future instant that later becomes past is not promoted retroactively, and
nothing is lost by that.** The selection is made once, at the fold; a survivor
that took January keeps January even after the source's future date has passed.
That is the right outcome under ADR-0103 §9's reading of `reported_at` — "a
source's timestamp records when that source asserts the fact *was* current,
never a claim that it stays current until then" — and in any case nothing is
destroyed: the target's `attestation` survives the fold under ADR-0103 §6, so
the record still says what the source reported and when it claimed to be
reporting it. A later lane that wants a different rule has the data it needs on
the record.

**Where the ordinary arm's survivor is the incoming record, the field is still
composed rather than inherited.** `_merge`'s non-corroboration arm returns
`incoming.model_copy(update={"id": target.id, "provenance": provenance})`, so
the survivor is the incoming record wearing the target's id — and taking the
incoming record's instant alone would move a belief's currency **backwards**
whenever the target held the later confirmation, which is reachable with no
producer doing anything unusual (a proposal citing a December episode
reinforcing a belief confirmed in January). "A confirmation we *do* hold is not
unmade" is ADR-0103 §6's own sentence about the unknown case, and it reads
identically about the merely-older one.

### 6. Every `REINFORCE` composes; ADR-0103 §9's fourth clause is read generally

> **Normative.** §5 governs **every** `REINFORCE`, in every band pairing — not
> only the `ATTESTED`-target × `DERIVED`-incoming pairing ADR-0103 §6 rules.

> **Normative.** ADR-0103 §6's other rulings — what the survivor takes of
> `source`, `attestation`, content and evidence-strength — keep their pairing
> scope exactly as written, and nothing here widens them.

**The general reading is the only one that gives ADR-0103 §9's fourth clause
content.** It says a belief "is also confirmed by an agreeing record folded onto
it under §6, **whatever band that record came from**, at *that record's* own
confirming instant and never at the moment of the fold." Under ADR-0103 §6's
clause the incoming record is always in the `DERIVED` band, so "whatever band
that record came from" would be vacuous — a qualifier ruling on a set with one
member. Read as what it says, the clause is about folds generally and cites
ADR-0103 §6 as the section that rules how the composition works.

**The merits point the same way, which is why this is a reading and not a
carve-out.** A `REINFORCE` is by definition an agreeing record (ADR-0040 §3: "a
contradiction is a `SUPERSEDE`"), and ADR-0103 §6's argument for why agreement
is information about currency — "the belief was seen to hold again *when that
observation happened*" — says nothing about bands. A same-band rule that
withheld currency would leave a belief that is re-observed every week ageing
exactly as fast as one nobody has seen since, which inverts the quantity
ADR-0103 §3 introduced.

**And the alternative fails ADR-0103 §9's own test for what must be ruled.**
Left unstated, one lane advances currency on every fold and another only on
ADR-0103 §6's pairing; both cite ADR-0103, and they ship different answers to
"when was this last confirmed?" for the same history of writes. That is the
"could two lanes make incompatible choices and both claim compliance?"
condition, so it is ruled here rather than left to the implementation.

> **Normative.** Only a `REINFORCE` composes `last_confirmed_at`. An `ACCEPT` and
> a `STORE_TEMPORARY` install the proposal's own value; a `SUPERSEDE` installs the
> proposal's own value at a fresh id and inherits nothing of the target
> (ADR-0040 §5a); and a retirement write preserves the stored value with the rest
> of the record (ADR-0080 §1).

**The write path is enumerated rather than left to the reader**, in the shape
ADR-0086 §4 used for `evidence_elided`'s recurrence, and for its reason: stating
the rule over every install is what stops the non-fold cases quietly inventing
or dropping a value. The asymmetry with `evidence_elided` is real and follows
from what each field is. An elision count is a fact about a record's *history*,
so it sums over every source an install draws from; a confirming instant is a
fact about the *world*, so it is selected rather than accumulated, and a
`SUPERSEDE` — which "carries nothing of the target onto the surviving record" —
carries no instant either. A superseding proposal states a different belief; the
retired record's confirmation is not evidence about it.

### 7. ADR-0103 §9 reads "the most recent **usable** confirming instant" (#741)

> **Normative.** Where ADR-0103 §9's second and third clauses say "the most recent
> confirming instant", they are read as the most recent **usable** one, on
> ADR-0103 §6's definition of usable. ADR-0103 §6 controls where the two could be
> read apart.

This is #741's requested clarification, taken. #741 is careful about what it is
reporting: "**Not a defect in the decision**", a "readability seam between two
clauses that agree on the outcome", where ADR-0103 §6 "is the more specific rule
and says so on its face". The outcome was already settled — the architecture
lens raised it as a `major` in round 9 of PR #732 and retired it in round 10 —
and this clause changes none of it. It states the reading so that a lane holding
ADR-0103 §9 alone reaches ADR-0103 §6's answer without having to find it first,
which is the whole of what #741 asks for.

**Under this ADR's representation the seam narrows to almost nothing, and the
clause is still worth writing.** A record carries one instant, so at read there
is no set to take a "most recent" over: §3 above rules that it is *this* instant
or unknown. The only place two candidates are ever compared is the fold §5
rules, which is qualified. So a lane implementing this ADR cannot reach the
divergence #741 describes. A reader of ADR-0103 who never reaches this ADR still
can, which is why the clause exists and why the dated note §13 writes on
ADR-0103 carries it too.

**The record is a dated note, not an edit.** ADR-0070 §1 permits an in-place
amendment "only when the amendment changes no decision", always as an appended
dated note, and #741 says the same in its own words — "ADR-0103 is `Accepted` as
of
#739, so any clarification is now an appended dated note under ADR-0070 §1,
never an in-place rewrite". ADR-0103 §9's ratified sentences are left standing
exactly as written.

### 8. Three things that do not change: the fingerprint, the migration, the validator

> **Normative.** `last_confirmed_at` joins `MemoryUpdateProposal`'s fingerprint
> projection like any other `provenance` field. It is **not** added to the
> excluded set, and ADR-0078 §7's projection is not narrowed.

ADR-0078 §7 defines the projection by "a criterion and an exclusion list rather
than by an inventory of what counts" — "the whole record minus the fields that
are *bookkeeping about the record rather than the belief it states*" — and
`core/types.py` records that the criterion "decides the next one rather than an
inventory having to be extended by whoever adds it". So this is the criterion
applied, not ADR-0078 §7 amended, and the answer is *in*.

**Applying it band by band is what makes the answer safe rather than merely
arguable.** ADR-0078 §7's excluded instant is `provenance.last_updated`, and the
reason is named: "two identical observations produced a minute apart carry
different stamps, so every one of them is a new question and the user is nagged
by the mechanism whose job is to stop that". The operative property is
**stability across re-proposals of one thing** — the same property ADR-0078 §7
relies on when it keeps `confidence` in, deferring to ADR-0077's obligation to
stabilise it. Against that:

- **`DERIVED`.** The instant is the latest `occurred_at` among the cited episodes,
  so re-observing the same batch yields the same value. That is ADR-0077 §5's
  "**re-observing the same episodes cannot inflate a belief**" holding for the
  second quantity, and it is why ADR-0103 §9 chose the observation's instant over
  the moment of derivation. Stable.
- **`ATTESTED`.** The instant is `Attestation.reported_at`, which is already in the
  projection and is the source's own clock, "never reconciled with ours"
  (ADR-0092 §3). A re-import of the same report carries the same value. Stable,
  and redundant with a field already digested.
- **`ASSERTED`.** The instant is the utterance's, so re-processing one feedback
  event yields one value. Two *distinct* utterances a minute apart yield two, and
  that is a second confirming act rather than a second look at one — ADR-0078
  §7's own
  treatment of `confidence` makes exactly this call ("a producer that jitters …
  across re-observations of one thing is emitting genuinely different proposals").

So the nag ADR-0078 §7 excluded `last_updated` to prevent is unreachable through
this field in any band. The residual — a user asserting the same belief twice
against the same conflict set, minting two `question_key`s where today there is
one — is named here rather than discovered later, and it is accepted: the second
assertion is a real event, ADR-0050 §2's contradictory-prior-assertion path is
the only route by which it becomes a question at all, and excluding the field to
suppress it would be "a change to ADR-0078 §7's projection bought for no
observable difference" in the other three cases, which is ADR-0086 §5's stated
reason for declining the same edit.

> **Normative.** No migration writes a `last_confirmed_at` for a record stored
> before this decision. Such a record decodes at the field's `None` default and
> reads as unknown.

This is ADR-0103 §9's fourth clause and its third constraint, satisfied by
construction rather than by a migration written correctly. `SqliteMemoryStore`
stores each record as a JSON blob and decodes it through pydantic, so an
additive field with a default needs no schema work at all (§Context) — the same
property ADR-0086 §4 relied on for `evidence_elided`, and ADR-0045 §9's shape
for a column that is a derived index rather than the truth. **Nothing fabricates
a decline** because nothing fabricates a value: unknown is what the store
actually knows about a record written before anything measured this.

> **Normative.** No validator on `Provenance` constrains `last_confirmed_at` — not
> against `last_updated`, not against `attestation.reported_at`, not by band, and
> not by requiring it. The absence is the decision.

**The three candidate invariants each refuse something legitimate**, which is
ADR-0086 §3's test ("does it refuse something that already worked") and ADR-0107
§4's precedent for stating an absence as a ruling rather than an omission.

- **Required, or required in some band.** Refuses every stored record on the read
  path, at deserialisation (§2), and contradicts ADR-0103 §9's fourth clause.
- **`last_confirmed_at <= last_updated`.** Refuses the ordinary case rather than a
  pathological one: `reported_at` in our future "is not refused" (ADR-0092 §3),
  and §4 stores it, so an attested record legitimately carries an instant later
  than the write that stored it.
- **`last_confirmed_at == attestation.reported_at` for the `ATTESTED` band.**
  Refuses precisely the survivor ADR-0103 §6 mandates: after a corroborating fold
  the record keeps the *target's* attestation while §5 may have advanced the
  instant to the derived record's. The two fields are not redundant, and §11
  records why the derivation that would have made them so is unavailable.

### 9. Not promoted to the `MemoryWriter` conformance suite (ADR-0103 §7's question)

> **Normative.** §§5–6 rule `memory`'s fold semantics and are not promoted to the
> `MemoryWriter` conformance suite. ADR-0028 §8's exclusion of the fold's own rule
> and ADR-0040 §5a's statement that how a fold composes is unasserted both stand,
> and a writer that composes currency differently conforms.

> **Normative.** The canonical `FakeMemoryWriter` in `ai_assistant.testing`
> implements §§5–6 identically to `MemoryIngestor`, so a lane testing against the
> fake observes the ingestor's behaviour. This is a property of the canonical fake,
> not an obligation on every implementation of the Protocol.

ADR-0103 §7 left this open by name — "Whether any clause of this ADR becomes a
conformance obligation is decided by the lane that implements it, in an ADR that
names those clauses and applies ADR-0070 §1's test to them" — and this is that
ADR, naming ADR-0103 §6 and ADR-0103 §9 and answering: no.

**The price of the other answer is what decides it, and ADR-0103 §7 already
stated that price.** ADR-0040 §5a is explicit that "a writer that combines
confidence differently conforms, and must, or ADR-0028 §8's exclusion is void."
Promoting §5 would make that sentence false, which is an amendment of two
ratified ADRs and belongs to the change that makes it. Nothing here needs it:
the field is `core` surface, so what a `Provenance` *means* is contract already,
and what a particular writer does when folding two of them is the thing ADR-0028
§8 and ADR-0040 §5a both say is `memory`'s to rule.

**The fake is held to the ingestor's behaviour anyway, and the two statements do
not conflict.** ADR-0107 §8 required the same of `testing/engine.py` — "so the
canonical fake and the real projection agree" — for the reason that a fake which
diverges silently makes every test written against it a test of nothing. That is
an obligation on *our* fake, discharged by the implementing lane, and it grants
no obligation to a third-party writer.

**Revisit if** a second `MemoryWriter` implementation ever exists and two lanes'
beliefs disagree about currency across the same history of writes. That is the
condition under which ADR-0028 §8's exclusion starts costing something, and the
change that reopens it owes the ADR-0082 §1 records ADR-0103 §7 and this section
both decline to make.

### 10. What the implementing lane owes

> **Normative.** The implementing lane discharges every item this section
> enumerates, in its own PR after this ADR is ratified (golden rule 5, ADR-0015
> §5). Its fence is `core/types.py`, `memory/ingest.py`, the four production
> producers, the canonical fakes in `ai_assistant.testing`, and their tests: it
> changes no file under `core/protocols.py`, because no signature moves, and none
> under `docs/adr/`, because the one record §13 owes lands with this ADR.

> **Normative.** Every test whose expected outcome is a concrete instant
> constructs a `last_confirmed_at` that is not `None` and is distinct from every
> other instant in the case — the injected clock's reading, `last_updated`,
> `attestation.reported_at`, and the other record's instant — and asserts the exact
> instant it expects.

> **Normative.** Every test whose expected outcome is **unknown** asserts
> `last_confirmed_at is None` exactly — never merely falsy, and never by omitting
> the assertion. Where the code path under test can also produce a concrete
> instant, that unknown case is accompanied by a sibling case over the same path
> which does.

The items below are what those three clauses obligate; ADR-0089 §3 has the mark
supply the obligation and this text say what it means. The two test clauses are
stated here rather than beside the test list because a mark indented into a list
item is not a mark (ADR-0089 §2).

**The two test clauses divide the cases and neither covers both**, which is
deliberate: some of the outcomes below *are* `None`, and a rule demanding a
non-`None` value everywhere would be unsatisfiable for exactly those. Each guards
a different vacuity. A concrete-instant case left at the field's default passes
whether the value is carried or silently dropped, so the first clause forbids the
default and forbids reusing an instant already in the fixture. An unknown case is
the mirror: on a path that can produce either outcome, `is None` alone passes
against an implementation that never writes the field, so the second clause pairs
it with a sibling that would fail under that implementation. Two of the three
unknown outcomes below are on such paths and get their siblings from the same
list — the fold where neither input is usable sits beside the selection cases,
and the legacy blob with no key sits beside the round-trip. The third, the
capture path, can only ever produce unknown, so the sibling clause does not
reach it; its assertion still earns its place, because it fails the moment a
producer writes the episode's own `occurred_at` into the field, which is exactly
what §4 above decided against.

1. **`core/types.py`** — `last_confirmed_at: UtcInstant | None = Field(default=None,
   description=…)` on `Provenance`, appended after `attestation`. **No validator**
   (§8). The class docstring gains the contrast §2 turns on: `last_updated` is
   when we last revised the belief, `last_confirmed_at` is when the world last
   confirmed it, and `None` is ADR-0103 §9's unknown rather than a stale or a
   fresh reading. Declaration order is not load-bearing — `_canonical_json` orders
   keys (ADR-0021 §1), so nothing digested depends on where the field sits — which
   is also why this lane and ADR-0106 §2's `derived_from_external` lane can append
   to this type in either order without either blocking the other.
2. **`memory/ingest.py`** — `_merge` composes the field on **both** arms per §5,
   and takes the ingestor's clock to do it. The corroboration arm and the ordinary
   arm select identically; what differs between them is what else the survivor
   takes, which ADR-0103 §6 already rules and this lane does not touch. The
   docstring paragraph that currently reads "**Currency is not written here,
   because nothing represents it yet**" is replaced by what §5 rules, including
   why the bound can no longer displace the instant.
3. **The four producers, each supplying its band's event (§4)** — and in each case
   the instant is one the module already holds, so none of them grows an
   argument:
   - `readers/calendar.py` — the occurrence's `reported_at`, the same value it
     already puts in the `Attestation`, and never `read_at`;
   - `learning/observer.py` — the **latest** `occurred_at` among the episodes the
     citations resolved to, taken from the batch the module selected and never
     from the model's reply (§4, ADR-0106 §3);
   - `learning/processor.py` — the feedback event's `created_at`;
   - `orchestration/conversations.py` — `None`, per §4's episode paragraph, which
     is what the field's default already gives it; the site is listed so the lane
     records the decision rather than reaching it by omission.
   `orchestration/loop.py` builds a `Goal`'s provenance and is **unchanged**: a
   goal is not a belief whose currency lapses (§2).
4. **`ai_assistant.testing`** — `testing/writer.py`'s fold copy implements §5 and
   §6 identically to `MemoryIngestor` (§9); `testing/readers.py`,
   `testing/observation.py` and `testing/learning.py` follow §4 for the bands they
   produce, the fake observer taking the latest `occurred_at` over the same
   `window` of episodes it already slices to build its citations.
   `testing/engine.py`'s canned `Goal` is unchanged, for item 3's reason.
5. **Tests, governed by the two anti-vacuity clauses above.** A fixture left at
   the default passes whether the field is carried or silently dropped, and one
   that reuses the case's clock passes whether the code selected the instant or
   read the clock. Both are tests that cannot fail, which is why those clauses are
   stated once for every case here rather than repeated per item:

   - **The at-capacity regression, which is the case this whole decision turns
     on** (#744, PR #742's finding 2). A deterministic fold whose incoming record
     carries more than `MAX_EVIDENCE_CITATIONS` citations in an accumulation order
     that is **not** `occurred_at` order, such that the bound displaces the
     citation whose episode carries the latest instant. Assert the survivor's
     `last_confirmed_at` is that pre-bound instant, and assert `evidence_elided`
     records the displacement — the two together are what prove the instant
     stopped depending on the retained tuple. It could not be written before this
     ADR, because there was no represented instant to assert on.
   - **Selection, over both arms.** The later of two usable instants wins; the
     **target's** wins where it is the later one (the backwards-move guard §5
     names); the usable one wins where the other is `None`; the survivor is `None`
     where both are.
   - **The future-dated case, which is #741's example with teeth.** An `ATTESTED`
     target whose instant is in the injected clock's future, folded with a
     `DERIVED` record whose instant is in its past: the survivor takes the past
     one. A test that omits this passes under a "later present value" rule, which
     is the rule §5 exists to refuse.
   - **The fold reads the injected clock and never the fold moment.** Freeze the
     clock, and assert the survivor's instant is neither the clock's reading nor
     `last_updated`.
   - **The other three write modes (§6).** An `ACCEPT` and a `STORE_TEMPORARY`
     install the proposal's value; a `SUPERSEDE` at a fresh id carries the
     proposal's and **not** the target's; a retirement write leaves the stored
     value untouched.
   - **The canonical fake agrees with the ingestor**, parameterised over the same
     selection cases, so the two fold implementations cannot drift (§9).
   - **The producers, per band**, asserting the event's instant and not the
     producer's clock: the reader's `reported_at` where `read_at` is deliberately
     different, the observer's **latest** cited `occurred_at` where the batch is
     deliberately out of order, the processor's `event.created_at`, and the
     capture path's `None`.
   - **The store round-trip, both directions.** An exact non-`None` instant
     survives `SqliteMemoryStore` write-then-read; and a stored blob whose JSON
     carries no `last_confirmed_at` key decodes as `None`. The second is what makes
     §8's no-migration claim a checked one rather than a stated one.
   - **The fingerprint.** Two proposals differing only in `last_confirmed_at`
     produce different `proposal_fingerprint`s, which is the checkable form of
     §8's first clause: it proves the field joined the projection rather than the
     exclusion list.
   - **The absent validator.** A `Provenance` whose `last_confirmed_at` is later
     than its `last_updated` constructs, and an `ATTESTED` one whose instant
     differs from its `attestation.reported_at` constructs. Both are states §5 and
     ADR-0092 §3 make reachable, and a later lane adding a validator would break
     these rather than discover the problem in a store.
6. **Nothing renders it.** ADR-0103 §9's rendering obligation reads "**Where** a
   belief's currency has lapsed", and what "lapsed" means is ADR-0103 §5's
   deferred threshold. There is no consumer, so this lane adds none (§12), and the
   CLI's `_why` is untouched.

### 11. Explicitly declined

- **A stored currency — an elapsed interval, a bucket or a staleness flag on the
  record.** It would be wrong the moment after it was written, it would need a
  writer to keep it right, and the writer that could is the one ADR-0103 §8 gives
  no retrieval-side role. The measurement is the instant; the interval is a
  derivation from it and a clock (§1).
- **Resolving the `DERIVED` instant from the cited episodes at read.** The whole
  fork, resolved in §1 on the three grounds §Context argues: the displacement case,
  the coupling to evidence retention, and ADR-0081 §1's store-free write path.
- **Deriving the `ATTESTED` instant from `attestation.reported_at` instead of
  storing it.** Tempting, because that band's instant is already on the record and
  a derived read would keep the two from ever disagreeing. It is unavailable, and
  the reason is ADR-0103 §6: the corroborated survivor **keeps the target's
  attestation** while its currency may be the incoming derived record's, later
  instant. Under a derived read that instant would have nowhere to live and the
  fold ADR-0103 §6 rules would be unimplementable — so the band's instant must be
  stored
  and independently writable, and the two fields' disagreement after a fold is
  meaningful rather than drift.
- **A cross-field validator pinning `last_confirmed_at` to
  `attestation.reported_at`, or ordering it against `last_updated`.** §8 states
  what each would refuse. ADR-0107 §4's precedent applies: the absence is the
  decision, recorded, rather than an omission for a later lane to repair.
- **Reusing `Provenance.last_updated`.** ADR-0103 §9 forbids it in terms — "it is
  transaction time, the clock of the system revising its own belief" — and gives
  the worked case: "a calendar's months-old report imported this morning has a
  `last_updated` of this morning, so a currency read off transaction time would
  call it perfectly fresh".
- **Adding the field to the fingerprint's excluded set.** §8 applies ADR-0078 §7's
  criterion and gets *in*; excluding it would be a change to a ratified projection
  bought for no observable difference in three bands out of three, which is
  ADR-0086 §5's stated reason for declining the same edit for `evidence_elided`.
- **Putting a currency on `Belief` or `BeliefSummary`.** ADR-0107 §10 left that
  question live and named it #744's, and it stays live: there is no consumer, no
  threshold and no rendering, so a field there would be surface invented ahead of
  the lane that will hold the evidence (§12).
- **Making currency an input to `MemoryStore.search`, `list_beliefs` or any
  ordering.** ADR-0103 §8 grants no retrieval-side role "here or by implication",
  and ADR-0072 §5's rule is about what the store's ranking may mix rather than
  which field's name is on the multiplicand.
- **A `Provenance` property or a `core` helper computing the elapsed interval.**
  §3 declines it: the shape is the first consumer's, and inventing one now would
  fix a decay parameter's granularity before leg 8 measures anything.
- **Promoting §5 to the `MemoryWriter` conformance suite.** §9, on ADR-0103 §7's
  own statement of the price.

### 12. What this ADR does not decide

- **The decay function, its rate, and the staleness threshold.** ADR-0103 §5
  defers all three to leg 8's measurement, and nothing here shortens that: this
  ADR represents the instant currency is measured *from* and says nothing about
  what any elapsed interval means.
- **Whether an unknown currency triggers ADR-0103 §4's re-confirmation, and on
  what schedule.** ADR-0103 §9 defers it with the parameters, and this ADR makes
  unknown reachable on far more records than the migration path alone — every record
  written before ratification, plus every episode and every goal — which is a
  reason for that lane to have the count in front of it, not a reason to decide it
  here.
- **Whether and how currency reaches retrieval.** ADR-0103 §8's question, and the
  retrieval-ranking lane's ADR states which shape it takes and what ADR-0072 §5
  costs under it.
- **The shape of a computed currency**, and whether any component gets a helper
  for it (§3). The first consumer decides, with ADR-0103 §5's parameters in hand.
- **Whether the inspection DTOs carry a currency, and how a surface renders one.**
  ADR-0107 §10 left the first live; ADR-0103 §9's last clause puts the wording with
  the prompt-assembly lane under ADR-0072 §6. Both wait on a consumer.
- **The reverse pairing (#733)** — what a source-changing fold may carry when a
  `DERIVED` target at a higher strength is reinforced by an `EXTERNAL` record.
  ADR-0103 §6 filed it rather than absorbing it, and §5 above rules only the
  instant, identically on both arms.
- **Anything about consolidation.** ADR-0106 §5 lands consolidation output in the
  `DERIVED` band, so §4 above already tells a consolidation producer which
  instant to supply — but nothing here bounds, schedules or shapes that lane, and
  its own ADR owns whether a consolidated belief's confirming instant is anything
  other than what §4 above says.
- **ADR-0106 §2's `derived_from_external`.** A different field on the same type
  for a different question. Neither lane blocks the other (§10 item 1).

### 13. Records owed on earlier ADRs, under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this ADR's text, clause by
clause, against ADR-0070 §1's test: *would a reader holding only the earlier ADR
now act differently, or read one of its clauses more widely than it now holds?*

**Owed — ADR-0103, as a dated note and not a supersession.** Three of its
sentences are collected rather than contradicted, and a reader holding only
ADR-0103 would still believe all three open:

- **§9's first clause** leaves representation — "field names, types, and whether
  currency is stored or computed" — to the implementing lane. This ADR is that
  lane and takes it, so the deferral is discharged.
- **§7's last sentence** leaves "whether any clause of this ADR becomes a
  conformance obligation" to "the lane that implements it, in an ADR that names
  those clauses and applies ADR-0070 §1's test to them". §9 above is that ADR,
  naming §6 and §9 of ADR-0103 and answering *no*.
- **§9's second and third clauses** say "the most recent confirming instant" where
  §6 says "usable". §7 above states the reading, which is #741's requested
  clarification and changes no outcome — #741 itself records that "§6 controls"
  and that the two clauses "agree on the outcome".

**Collecting a deferral an earlier ADR filed is a stacked addition, not a
supersession** — ADR-0107 §11's treatment of ADR-0086 §10, on ADR-0086 §11's own
treatment of ADR-0077 §6. Nothing ADR-0103 **decided** changes: §2's split, §3's
ratchet, §4's re-confirmation response, §5's deferred parameters, §6's fold
ruling, §8's retrieval neutrality and §9's domain, confirming events and unknown
are all relied on here exactly as written, and §5's clause about a lane that
must ship a schedule before leg 8 is untouched because this ADR ships no
schedule. ADR-0103's `Status` is a plain `Accepted` and takes **no** token,
because no clause of it is superseded (ADR-0070 §4, ADR-0082 §2); the record is
the dated note ADR-0082 §1 requires, appended, with no ratified sentence
rewritten.

**Not owed — ADR-0086 §2, §3, §4 and §5.** §3's bound and its accumulation order
are applied exactly as ratified and bite identically before and after; §5 above
performs the bound's displacement and merely stops it costing an instant, which
is a fact about what *depends* on §3 rather than a change to §3. §4's
elision-is-not-a-tombstone rule and its recurrence are untouched, and §6 above
follows §4's discipline of enumerating every install rather than inheriting one.
§2's refusal of a `max_length` is relied on in §2 above as the test a required
field fails. §5's fingerprint reasoning is applied rather than narrowed (§8
above), and its conclusion for `evidence_elided` is unchanged. A reader holding
only ADR-0086 builds the same bound, records the same count and digests the same
projection.

**Not owed — ADR-0081 §1.** Its store-free, cannot-be-raced property is a
*reason* in §Context and a constraint §5 above respects; nothing about the
self-citation predicate, its placement, its error class or its `SUPERSEDE`
exemption moves. §1a's rule that the predicate is quantified over the proposal's
evidence rather than the merged tuple is likewise untouched — §5 above adds no
store read to the section ADR-0081 §1 keeps free of them.

**Not owed — ADR-0007 §2 and §5.** §2's read-time retention is cited as the
mechanism a resolver would have coupled currency to, and it keeps working
exactly as written; §5's size-caps deferral is not reached. ADR-0103 §1's leg-7
clause already names both as untouched, and this ADR removes nothing and expires
nothing.

**Not owed — ADR-0092 §1 and §3.** §1's `attestation`-iff-`ATTESTED` invariant
is relied on in §11 above's argument and is neither widened nor weakened. §3's
three rulings — `reported_at` is the source's clock, `reported_at` earlier than
`last_updated` is the normal case, and a future `reported_at` is not refused —
are all *used*: §4 above stores the instant as it stands on the strength of the
third, and §8 above refuses an ordering validator on the strength of the second.
A reader holding only ADR-0092 acts identically. That `last_confirmed_at` may
differ from `reported_at` after a fold adds a fact about a *second* field and
takes nothing from the first.

**Not owed — ADR-0078 §7.** §8 above applies its criterion and its exclusion
list as written, and adds nothing to either. `core/types.py` states that the
criterion "decides the next one rather than an inventory having to be extended
by whoever adds it", so a field joining the projection is §7 operating, not §7
amended. §7's canonicalisation of collections is not reached: this field is a
scalar.

**Not owed — ADR-0040 §5a and ADR-0028 §8.** §9 above declines to promote for
exactly the reason ADR-0103 §7 gave, so ADR-0040 §5a's "a writer that combines
confidence differently conforms, and must" stays true, and ADR-0028 §8's
exclusion stays whole. §6 above's enumeration of the write modes *quotes*
ADR-0040 §5a's `SUPERSEDE` asymmetry rather than extending it: "carries nothing
of the target onto the surviving record" is what makes the instant not
inherited.

**Not owed — ADR-0107 §10.** Its first entry says where ADR-0103's currency
lives on the inspection DTOs "is #744's … deliberately not pre-empted". This ADR
is
#744's ADR lane and declines the DTO question (§11 and §12 above), leaving it
exactly where ADR-0107 §10 put it — with the lane that will hold a consumer. A reader holding
only ADR-0107 still declines to pre-empt it, which is what §10 asked of them.

**Not owed — ADR-0106 §2, §3 and §5.** §2's `derived_from_external` is a
different field and is neither reordered nor reinterpreted; §3's rule about who
computes a producer's field is *applied* in §4 above's third clause and quoted
as the governing precedent rather than extended; §5's placement of consolidation
output in the `DERIVED` band is relied on in §12 above to say a consolidation
producer already knows which instant §4 above asks it for.

**Not owed — ADR-0045 §3 and ADR-0072 §3, §5.** ADR-0045 §3's transaction-time
definition of `last_updated` is the whole reason §2 above names its field the
way it does, and nothing about it moves. ADR-0072 §3's meaning of `confidence`
is untouched, which is ADR-0103 §9's second constraint discharged by addition
rather than reinterpretation; ADR-0072 §5's band-neutral, confidence-neutral
`search` acquires no exception and is granted none (§11 above).

**The record lands in this change, and the deferred shape is refused.** ADR-0082
§7 states ADR-0082 §1's condition outright — "§1's condition is that the
superseding ADR **exists**, not that it is ratified — the hazard §1 names is a
`Status` line pointing at nothing, and an atomic pair makes that unreachable" —
and this record does not even reach that question, since it touches no `Status`
line. Writing it in a following change would leave a `main` on which ADR-0103 §9
says the representation is open beside an ADR-0109 that closes it, with no
pointer in either direction: two live documents stating one thing at two widths,
which is
#477's failure and the one ADR-0089 §5 exists to stop. **What ADR-0082 §1 puts in
this text is the judgement**, argued above where review reaches it; the note
transcribes it, in the same change.

## Consequences

**Easier.** The question "when was this last confirmed?" becomes answerable for
the first time, from the record alone, with no store read and no episode
resolution — and it stays answerable after a fold, after the citation bound
bites, and after the cited episodes expire under ADR-0007 §2. ADR-0103 §6's
third contribution, which `_merge` today records as unimplementable in its own
docstring, becomes one line of selection over two values the fold already holds.

**Easier.** #744's displacement finding stops being a constraint to design
around and becomes a case with no route to fire: the instant is captured before
ADR-0086 §3's bound can reach it, so the bound displaces citations and nothing
else. The regression test the finding asks for finally has something to assert
on (§10).

**Harder.** Every producer of a belief gains an instant to supply and a way to
be wrong about it — the second time this decision has made that trade, after
ADR-0103's own "two quantities cost more everywhere they are read". The failure
mode is quiet, which is why §10's anti-vacuity rule is stated as a requirement
on every test rather than left to care: a producer that omits the instant writes
`None`, and `None` reads as unknown rather than as an error.

**Harder, and named.** A record can now carry two instants that disagree —
`attestation.reported_at` and `last_confirmed_at` — and the disagreement is
legitimate after a fold (§11). Anyone reading the type has to know which
question each answers, which is what §10 item 1 puts in the class docstring and
what §2's naming argument is for.

**Smaller than it looked.** No SQLite migration, no schema column, no wire codec
change, and no `core/protocols.py` change: the store persists whole-record JSON
and the field is additive with a default, so ADR-0103 §9's fourth clause is
satisfied by the default rather than by a migration (§8). What remains is the
producers, the two fold implementations, the fakes and the tests.

**The unknown population is large at first and shrinks by itself.** Every record
written before the implementation lands reads as unknown, and so does every
episode and every goal thereafter. That is the honest state — ADR-0103 §9's
third constraint forbids inventing anything else — and it is the number the lane
deciding ADR-0103 §4's trigger will need in front of it (§12).

**Revisit if** a second `MemoryWriter` implementation makes ADR-0028 §8's
exclusion cost something (§9); if leg 8's measurement shows the stored instant
is the wrong granularity for the decay function it lands on; if a consumer needs
an elapsed interval in more than one place, which is when §3's declined helper
earns its keep; or if a producer ever legitimately holds two confirming events
for one proposal, which is the one shape a single scalar cannot represent and
which no band's ADR-0103 §9 rule produces today.

## Alternatives considered

- **Resolve the instant from the cited episodes on demand.** The other horn of
  #744's fork, rejected on three grounds in §Context and §1: it disagrees with a
  stored field in exactly the case ADR-0103 §6 rules, it couples currency to
  evidence retention so a belief goes stale because its episodes expired, and it
  puts a store read inside the ingest section ADR-0081 §1 keeps free of them. It
  is cheaper on producers and it is wrong.
- **Store the instant, but compute it inside the fold from the episodes.** Keeps
  the field and still needs the store read, so it takes the worst half of each
  option: the corpus-wide producer cost *and* the raced read.
- **Store an elapsed interval or a staleness bucket instead of an instant.**
  Rejected under §1 and §11: it is stale the moment it is written, it needs a
  maintenance writer nothing has authorised, and its granularity is a decay
  parameter ADR-0103 §5 defers to leg 8's measurement.
- **Make the field required, with `None` unrepresentable.** Rejected in §2: it
  refuses every record already in a store, on the read path, at deserialisation —
  ADR-0086 §3's test at its widest possible scope — and it contradicts ADR-0103
  §9's fourth clause, which requires every pre-decision record to read as unknown.
- **Give the `ATTESTED` band no field and read `attestation.reported_at`.**
  Rejected in §11 on ADR-0103 §6: the corroborated survivor keeps the target's
  attestation, so a later derived instant would have nowhere to live and
  ADR-0103 §6's fold would be unimplementable. The saving was one field on one
  band and the cost was the ruling this ADR exists to make implementable.
- **Rule §5 only for ADR-0103 §6's pairing, and leave other folds alone.**
  Rejected in §6: it makes ADR-0103 §9's "whatever band that record came from"
  vacuous, it
  ages a weekly-re-observed belief exactly as fast as an unobserved one, and it
  leaves two lanes able to make incompatible choices while both citing ADR-0103 —
  that ADR's own §9 test for what must be ruled.
- **Select over the later *present* instant and let the read resolve a future one
  to unknown.** Simpler, and it loses #741's case: a future-dated `reported_at`
  would win the selection and make a survivor unknown with a perfectly good
  January observation on the other side, which is the manufactured staleness
  ADR-0103 §6 and §9 both refuse. It is why §5's fold takes a clock.
- **Defer the whole question until a consumer exists**, which is the deferral
  #744 records as available. Rejected in §Context: the confirming instant can only
  be captured while the event is in hand, and ADR-0103 §9's fourth clause makes
  every record written without one permanently unknown. Deferring the *rendering*
  costs nothing and §12 does exactly that; deferring the representation spends
  something that cannot be bought back.
