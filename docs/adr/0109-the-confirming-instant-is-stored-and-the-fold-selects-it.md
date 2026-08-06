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
  owed — a dated note on ADR-0103 — and §13 applies ADR-0070 §1's test to eight
  further ADRs and finds none owed. **The note lands in this same change**, so no
  reader ever holds an ADR-0103 whose deferral is discharged somewhere it cannot
  see (ADR-0082 §7; the shape ADR-0107 §11 argued and the deferred shape its own
  round-1 `blocker` refused).
- **Closes #741.** Its seam — that ADR-0103 §9 says "the most recent confirming
  instant" where §6 says "usable" — is settled by §7 below and recorded in the
  same dated note.
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
**evidence-strength**, which `confidence` already carried, and **currency**, "how
far the belief should be trusted to still hold *now*", which has never existed.
§9 then rules currency's domain and its confirming events in detail and leaves
exactly one thing to the implementing lane:

> **Normative.** How the two quantities are represented on `Provenance` — field
> names, types, and whether currency is stored or computed — is the implementing
> lane's, subject to three constraints: both quantities are separately readable by
> a consumer; `Provenance.confidence`'s ratified meaning (ADR-0072 §3) is not
> silently reinterpreted; and no migration of an existing record fabricates a
> currency decline that was never measured.

§9 is explicit about where it drew that line: "**The line between what is ruled
and what is deferred is 'could two lanes make incompatible choices and both claim
compliance?'**" A field name cannot fail that test — "a second implementation
choosing a different one is a rename". The *domain* can, and §9 rules it: unknown
is a distinct state, every pre-decision record reads as unknown, and no surface
renders unknown as confirmed.

Issue #744 is the boundary written down. Its central finding is that the deferred
question is **not** a rename after all, because "whether currency is stored or
computed" is one of the three things §9 handed over, and the two answers diverge
observably. That is this ADR.

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
*deserialisation* as well as on construction" and would fail a read on a record a
running deployment already holds (ADR-0086 §2) — so an incoming proposal may
legitimately arrive with more citations than the bound. When it does, some of its
own citations are displaced, and **accumulation order is not `occurred_at`
order**, so the displaced one can be the episode carrying the latest instant.
`evidence_elided` retains a count and never an id (ADR-0086 §4), so after the fold
that instant is not recoverable from the survivor.

A resolver therefore reads "latest `occurred_at` among the *retained* citations",
which is §9's definition applied to the tuple the record actually carries and is
conformant on its face. ADR-0103 §6 says something else about the same survivor:

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
from a rate ADR-0103 §5 has deferred to leg 8. That is the manufactured staleness
§9's third constraint refuses on the migration path and §6's
unknown-does-not-spread paragraph refuses at the fold, reached by a third route. A
stored instant is a measurement made once, at the confirming event, and retention
cannot unmake it.

**The writer cannot do the resolver's job at the point §6 needs it done, and the
precise reason is worth stating rather than paraphrasing.** `_merge` is a
module-level function over two records — it holds no store. `MemoryIngestor`
*does* hold one, so the resolver is not literally unreachable; what it costs is
what ADR-0081 §1 declined to spend, in that clause's own words about its
self-citation predicate: it "costs no `get`, adds no I/O to a section that holds
the ingestor's lock, introduces no new read-modify-write window, and — unlike §5's
resolvability check — cannot itself be raced, because every input is already fixed
and private to the call". A fold that resolved episode instants would take all
four costs back, and the race it would take back is the one that matters here: it
would be racing episode expiry, which is ground two above with a lock around it.
The stored field keeps §6's selection inside the property ADR-0081 §1 built.

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
  one field over — and it means §9's fourth clause ("every record written before
  this decision reads as unknown") is satisfied *structurally*, by the default,
  rather than by a migration anyone has to write correctly.
- **`Provenance` never crosses `wire/`.** No module under `wire/` names
  `Provenance`, `MemoryRecord` or `Goal`; the local API projects the engine's
  DTOs, and `MemoryStore.export` — which does return records whole (ADR-0007 §3)
  — is not on the promoted engine surface. So there is no codec change and no
  frame-size question (ADR-0084 §3).

Issue #744's "corpus-wide change" paragraph priced "the SQLite codec, its migration, and
the conformance suites that would pin whichever half becomes contract". The
codec and the migration come off that list on the evidence above; the producers,
the fakes and the tests stay on it. The cost is real and is accepted either way —
it is simply smaller than the issue that filed it could see.

### The seam #741 records, and why a stored instant is the thing that closes it

#741 reports that §9's second and third clauses say "the most recent confirming
instant" without §6's qualifier, and gives the case: an `ATTESTED` target whose
`reported_at` is future-dated, and a `DERIVED` incoming record whose latest
supporting `occurred_at` is in January. **§6 says January.** A reader applying §9's
clauses to the *set* of confirming instants, taking "most recent" at face value,
picks the future one and reaches unknown. #741 is careful that this is not an
inconsistency — §6 is the more specific rule and names the case in the paragraph
below the clause — and asks only whether a one-word appended note would make §9
self-contained.

Under a stored instant the seam does not need to be read carefully; it stops
existing. A record carries **one** instant, so "most recent" has nothing to select
over at read time. The only place two candidates are ever compared is the fold,
where §6 governs and §6 is qualified. §7 below records that and the note is
written anyway, because a reader who never reaches this ADR still reads §9 alone.

### Why this is worth deciding before there is a consumer

Nothing reads currency today: ADR-0103 §8 grants it no retrieval-side role, §5
defers the decay function and the staleness threshold to leg 8's measurement, and
§4's re-confirmation trigger is deferred with them. #744 names that as a reason
the lane could wait. It is a reason the *rendering* can wait, and §12 below lets
it. It is not a reason the representation can, for one reason that gets more
expensive every week: **the instant can only be captured while the confirming
event is in hand.** A record written today with no confirming instant reads as
unknown forever (§9's fourth clause is explicit that no migration may invent one),
so every day the decision waits is another day of beliefs that can never answer
"when was this last confirmed?" — and unknown is the one value ADR-0103 §9 forbids
anyone from improving after the fact.

## Decision

### 1. The confirming instant is stored on the record, never resolved from the store

> **Normative.** A belief's confirming instant is data the record carries. A
> consumer or a writer that needs it reads it from `Provenance` and never
> recomputes it by reading the episodes the record cites, or any other record.

> **Normative.** Currency itself — the elapsed interval — is never stored. It is
> computed at read, against the reading component's clock, from the stored
> instant.

The fork §Context poses resolves to the first horn, on the three grounds argued
there: the displacement case makes a resolver and a stored field disagree exactly
where ADR-0103 §6 rules; a resolver couples currency to evidence retention and so
manufactures a decline nobody measured; and §6's fold-time selection is only
implementable without a store read if the instant is on the record.

**The two halves of the clause pair are not in tension, and the split is where
ADR-0103's own reasoning puts it.** The instant is a *measurement*, made once,
when something confirmed the belief; the elapsed interval is a *derivation* from
that measurement and a clock, and it is different every time it is asked for.
Storing the derivation would be storing a number that is stale before it is
committed — which is the shape ADR-0077 §6 refused for presented confidence ("a
number computed at presentation cannot reorder a store it never touches"), and
the reason nothing here reaches ADR-0072 §5's ranking rule at all (ADR-0103 §8).

**What "separately readable" means under this representation**, since it is the
first of §9's three constraints. Evidence-strength is read from
`Provenance.confidence`; currency is read from the stored instant plus a clock.
Neither is derived from the other, neither has to be disentangled from the other,
and `confidence`'s ratified meaning (ADR-0072 §3) is untouched — which is §9's
second constraint, satisfied by adding a field rather than reinterpreting one.

### 2. The field: `last_confirmed_at`, optional, and `None` is §9's unknown

> **Normative.** `Provenance` carries `last_confirmed_at: UtcInstant | None`,
> defaulting to `None`: the instant of the most recent event that confirmed this
> belief, on the clock of whatever confirmed it.

> **Normative.** `None` is ADR-0103 §9's **unknown** — the state of a record whose
> confirming instant the store does not hold. No surface, consumer or writer
> renders, treats or ranks an unknown as a confirmed one, and none reads it as
> stale either.

**The name is the rename-class half of §9's deferral, and it is chosen against
two neighbours rather than for its ring.** ADR-0103 §9 spends a paragraph refusing
`Provenance.last_updated` as the clock — "it is transaction time, the clock of the
system revising its own belief" — and the field that must not be confused with it
is the field that should sit beside it and read as its opposite number:
`last_updated` is when *we* last changed our mind, `last_confirmed_at` is when the
*world* last confirmed the belief. The bare `confirmed_at` was rejected because
`UserConfirmation.confirmed_at` already exists in `core/types.py` meaning "when
the user's answer was given" — a single event, not a running maximum — and two
fields with one name and different arities is the kind of near-collision a reader
resolves wrongly once and then trusts. `last_` also carries §9's "most recent",
which §5 and §6 below are the rules that maintain.

**`| None` rather than a required field, and the alternative is not available.**
ADR-0086 §3 states the test for a `core` validator — "not 'is it a validator on a
`core` type' but 'does it refuse something that already worked'" — and a required
instant refuses *every record ever stored*, on the read path, at deserialisation.
That is the failure ADR-0086 §2 declined a `max_length` to avoid, at its widest
possible scope. The optional field with a `None` default is the only shape that
admits the corpus as it stands, and ADR-0103 §9's fourth clause independently
demands the same outcome: every pre-decision record reads as unknown.

**`UtcInstant`, because the corpus has one instant type and this is an instant.**
`Provenance.last_updated`, `Attestation.reported_at` and
`EpisodicMemory.occurred_at` are all `UtcInstant`, and its `AfterValidator`
enforces tz-awareness. The values this field takes come from exactly those three
fields (§4), so a different annotation would be a conversion for nothing.

**It carries no meaning on a `Goal`, and that breadth is accepted rather than
fixed.** Every `Goal` carries a `Provenance` (ADR-0068 §2) and reaches no
propose/dispose gate, so a goal's `last_confirmed_at` is `None` unless some future
producer sets one. That is the same harmless breadth ADR-0086 §4 accepted for
`evidence_elided` and ADR-0077 §7's validator accepted before it: a goal is not a
belief whose currency lapses, and a type-level exclusion would cost a validator
that refuses something rather than a field that says nothing.

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
§9's own line between them is what separates these two clauses. The domain fails
§9's "could two lanes make incompatible choices and both claim compliance?" test —
one lane reading a `None` as fresh and another as unknown ship different claims
about what the system knows — so the first clause rules it here. The *shape* of
the interval passes that test the way a field name does: a `timedelta`, a bucketed
enum and a boolean past a threshold are renames of each other until §5's threshold
exists, and inventing one now would be a decay parameter smuggled in as a type.

**The future-instant arm is §9's, restated at the read rather than re-decided.**
ADR-0103 §9 rules that a confirming instant in our future makes the elapsed
interval unmeasurable and the currency unknown, that the instant is "neither
refused nor rewritten (ADR-0092 §3)", and that no freshness is projected through
it. Under a stored field that ruling has exactly one place to act — the read — and
the first clause puts it there. §5 is the only other place a future instant is
examined, and it examines it to *choose between two*, never to rewrite one.

### 4. What a producer supplies, and who computes it

> **Normative.** A producer proposing a belief sets `last_confirmed_at` to the
> instant of the event that confirms it in its band, as ADR-0103 §9 rules that
> event: for `ASSERTED`, the instant the user stated it or answered §4's
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
§9 gives for ruling the events at all: two lanes reading "last confirmed"
differently "would ship different answers to 'does the assistant still believe
this?' while both satisfying a clause that named neither."

**The third clause is ADR-0106 §3 one field over, and it is load-bearing here for
the same reason.** §3 has `derived_from_external` computed by "the component that
**selected the input set**", discarding any value the producer emitted, on
ADR-0098 §4's ground that a rule is "fail-closed against a producer that forgets,
because the producer never had the choice", and on ADR-0094 §5's that "a claim
carried in a submission is not evidence of the standing it claims". A model asked
to emit a timestamp is a producer declaring its own currency, and the failure that
matters is not over-claiming but omitting. The tree already works this way for the
neighbouring field: `LearningObserver` maps the model's citation labels back onto
the ids of the episodes it selected and computes `confidence` deterministically
from the step and the citation count, so "the citations are ours, never the
model's". The latest `occurred_at` over that same selected set is ours by the same
construction — the observer is handed `Sequence[EpisodicMemory]` and holds every
`occurred_at` in the batch.

**The fourth clause is what keeps the producer and the fold from disagreeing about
a future instant.** A producer that dropped a future-dated `reported_at` to `None`
would destroy the very thing §5 needs to compare, and would do it by the route
ADR-0092 §3 closes: "a `reported_at` in our future is not refused", because source
clocks skew and refusing one invents a read-path failure. So the record keeps what
the source said, the read reports unknown, and the fold — the only place a choice
exists — makes it.

**The `ASSERTED` instant is the utterance's, not the write's**, which follows §9's
"the user stating it" and matters for the same reason §9's other two arms name
their events: `learning/processor.py` builds its provenance from a `FeedbackEvent`
and already has `event.created_at` in hand, and using the ingest clock instead
would make a re-processed feedback event look freshly confirmed. The same
discipline that keeps `ATTESTED` off our ingestion clock and `DERIVED` off the
moment of derivation keeps `ASSERTED` off the moment of the write.

**An episode is not a belief that lapses, and it takes `None`.** The capture path
in `orchestration/conversations.py` writes an `OBSERVED` `EpisodicMemory`, which is
in the `DERIVED` band and cites nothing — deliberately, because "an episode is the
terminal citation — the thing other records cite — so requiring it to cite
something would demand a regress". §9's derived rule ranges over the episodes a
record cites, and over the empty set it yields nothing, so the second clause
applies and the record reads as unknown. That is the honest answer rather than a
gap: an episode records that something happened, nothing retires it, and "is this
still true?" is not a question about it. Writing its own `occurred_at` into the
field would make an episode claim a currency it has no use for and would put a
value in the field for every episode in the store, where §9's unknown is exactly
right.
