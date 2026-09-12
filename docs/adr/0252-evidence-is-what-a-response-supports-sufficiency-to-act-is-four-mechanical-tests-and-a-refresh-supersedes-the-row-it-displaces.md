# 252. Evidence is what a response supports, sufficiency to act is four mechanical tests, and a refresh supersedes the row it displaces

- Status: Proposed
- **Partially supersedes [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md),
  in two narrowly stated scopes**, and §16 shows the working for both.
  **§1's `GoalElement` field enumeration and its three-shape validator** — *"A `GoalElement`
  is a frozen model with `extra="forbid"` whose fields are exactly `text`
  (`NonBlankEncodableText`), `ground` (a `Ground`), `evidence_id` (`Identifier | None`) and
  `span` (`EncodableText | None`). A **model validator** refuses every shape but three"* — gains
  one field and one shape: a `FROM_EVIDENCE` element may name an evidence row of this goal
  through `evidence_row_id` instead of a record of the labelled supply through `evidence_id`,
  and carries **exactly one** of the two. The same widening reaches `GoalInterpretation`'s
  outcome arguments, which §1 validates *"as a `GoalElement`'s are"*. §1's every other clause
  binds **verbatim**: the append-only sequence, `Ground`'s closure at three members, the
  four-absences clause, and `GoalElement`'s rule that the type expresses the correspondence
  rather than a rule to remember.
  **§7's `FROM_EVIDENCE` resolution clause** — *"A `FROM_EVIDENCE` element's `evidence_label`
  is resolved **by ADR-0226 §3's labelling scheme, unchanged** — the label of the record at
  1-based index *n* of the `memories` sequence passed **on that call**"* — gains a second label
  space over the `evidence` sequence §7 itself put on the seam, in the shape §9 already used for
  `constraints`, `criteria` and `conditions`. §7's every other clause binds **verbatim**,
  including its refusal of a label naming a search-minted record, its silent drop of a label
  that resolves to nothing, its rule that an element whose ground does not resolve is dropped
  rather than failing the turn, its no-identifier-crosses-the-seam clause, and its
  interpretation-is-the-model's asymmetry.
- **No other ADR is superseded in whole or in part**, and §16 shows the working for each one a
  reader would expect to be — ADR-0096, ADR-0226, ADR-0228, ADR-0237, ADR-0240, ADR-0250 and
  ADR-0251 among them. **ADR-0096 is relied on and not superseded**, which is the one a reader
  should check first: its two instants and its never-a-gate rule are what make sufficiency a
  separate question rather than a freshness verdict on the evidence.
- Date: 2026-09-12

## Context

### Where this comes from

ADR-0249 §13 defers to this decision by name, fired by that ADR landing:

> **`GoalEvidence`, the `PlanStore` members that hold it, the `requested`/`supported`
> composition, the verdict vocabularies, conflict adjudication, invalidation and the
> supersession rules.** A4. Fired by this ADR landing; §10 fixes what any such row must be
> able to answer.

and, in the same list:

> **How a search finding grounds an interpretation element.** A4. §7 drops a `FROM_EVIDENCE`
> ground naming a search-minted record, because ADR-0231 §16 makes such a record *"not a
> durable reference"* whose id *"resolves in no store"*, and a durable interpretation grounded
> on one would state a warrant it cannot show. The route A4 has is an evidence row keyed on the
> goal.

ADR-0249 §10 fixed the projection and left the record: an `EvidenceDigest` carrying
`requested`, `supported`, `read_at`, `as_of`, `verdict` and `standing`, an `EvidenceStanding`
closed at `STANDING`, `INAPPLICABLE` and `SUPERSEDED`, and the sentence that **which rules put
a row in the last two is A4's**. It also fixed three prohibitions this decision is written
under and does not relitigate: a digest carries no identifier of any kind, `supported` is
*"never derived from `requested`, from the query, or from the fact that a read completed"*, and
`verdict` carries *"the value of a typed outcome"* and never a prose summary a model wrote
about one.

The design direction is revision 1 of the report on #2255, part 2 §E whole. The owner's
rulings of 2026-09-12 on that issue bind this decision directly. **Correction 1** —
*"Refreshed evidence needs supersession rules, so retained historical disagreements do not
permanently block progress"* — is the clause the report's §E.4 does not satisfy, and §8 below is
this decision's answer to it. **Decision 8** — *"A useful real-information reader lands
alongside M32"* — is obeyed by §15 saying what an evidence row needs from a reader's typed
outcome and designing no reader. The **standing rule** — *convenience alone is insufficient
justification for a user-facing restriction* — is applied throughout, and the one restriction
this decision adds to a user's reach is the bound of §13, whose genuine constraint is named
there.

### What the tree holds today, read rather than assumed, at `origin/main` `54c6b72e`

ADR-0249's L1 has landed, so `core/types.py` holds `EvidenceStanding` and `EvidenceDigest` as
§10 specifies them, `Goal` carries its interpretation chain, `GoalElement` carries
`evidence_id`, `Ground` is closed at three members, `GoalAttempt` and `AttemptTransition` exist,
`GoalBrief` is the planner's first parameter, `PlanExport.schema_version` reads `Literal[8]`,
and `planning/sqlite_store.py`'s `_SCHEMA_VERSION` reads `2` with an `attempts` table beside
the three ADR-0049 §1 created.

**Three ratified shapes this decision cites are not in the tree, and every citation of them
says so.** ADR-0250's implementation has not landed, so `PlanStore.set_goal_status` and its
seven siblings are absent; ADR-0251's has not landed, so `ReadOutcomeKind`, that decision's
`ReadOutcome` model and `AttemptKind` are absent. They are cited as ratified contracts, which
is what they are — this decision is written against the corpus and the tree together, and where
they disagree the disagreement is stated rather than papered over.

**One collision is observed rather than decided here.** `core/types.py` already defines
`ReadOutcome` as a `StrEnum` (ADR-0185 §1, *"How one attempt to read a source ended"*), and
ADR-0251 §3 mints a frozen model of the same name for a different question. That is ADR-0251's
implementing lane's to resolve and is filed as an issue; nothing in this decision depends on
which way it goes, because every clause below cites `ReadOutcomeKind`, which collides with
nothing.

### The gap this closes, stated as the failure the corpus has today

#2255's addendum states it in one sentence: *"A query asking for Sunday's forecast does not
establish that its result describes Sunday. Distinguish what was **requested** from what the
response **supports** … Retaining an old forecast does not mean it remains sufficient to permit
booking."*

Nothing in the corpus records either half. A servicing's typed outcome is computed, acted on
within the turn and discarded — ADR-0251 §3 says so of its own carrier in terms: *"The carrier
does not span the attempt, and it mints nothing durable … it is an in-process argument built
from the turn's own servicings and discarded with the turn."* So an attempt that read a
forecast on turn 1 holds, on turn 4, no record that it did, no record of what the response
covered, and no way to distinguish *we asked about Sunday* from *the answer describes Sunday*.
The consequence is the one the addendum names: the only available substitute for evidence is a
model sentence about what was read, which is a model completion with no recorded origin that
ADR-0228 §11 rules *"no lane … treats as evidence of anything."*

### What this ADR is not allowed to settle

#2255's breakdown gives the step's own fields to A5, verification to A10, authorization to A6
and the plan-driving stage to A7. This decision therefore fixes **what a row is, what it
supports, and when it satisfies** — and fixes neither the step that declares a condition, nor
the stage that dispatches one, nor the act that verifies an outcome. §15 names each with what
fires it.

## Decision

### 1. `GoalEvidence`: the durable row, and the two bases a row may have

> **Normative.** `core/types.py` gains **`GoalEvidence`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `id`, an `Identifier`; `goal_id`, an
> `Identifier`; `attempt_id`, an `Identifier` naming the attempt that recorded it; `basis`, an
> `EvidenceBasis`; `read_kind`, a `ReadKind | None`; `source`, an `EncodableText | None`;
> `requested`, an `EvidenceApplicability | None`; `supported`, an `EvidenceApplicability |
> None`; `read_at`, a `UtcInstant`; `as_of`, a `UtcInstant | None`; `records`, a possibly-empty
> `tuple[Identifier, ...]`; `minted`, an `int` `ge=0`; `verdict`, an `EncodableText`;
> `standing`, an `EvidenceStanding`; `inapplicable_at_revision`, an `int | None` `ge=1`; and
> `superseded_by`, an `Identifier | None`.

> **Normative.** `core/types.py` gains **`EvidenceBasis`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly two members**: `READ_OUTCOME` and `INTERPRETATION`. The
> vocabulary is added to and never renamed, on `Ground`'s own rule (ADR-0249 §1, itself
> ADR-0226 §4's). It names **which of §3's two admitted sources** the row's `supported` was
> composed from, and therefore **which closed vocabulary `verdict` is a value of** (§5).

> **Normative — a model validator refuses every shape but the ones below, and there are
> three axes to it.**
>
> - **By basis.** A `READ_OUTCOME` row carries a `read_kind`. An `INTERPRETATION` row carries
>   **no** `read_kind`, **exactly one** member of `records`, and `minted` `0` — the
>   interpretation call's whole input is one recorded record, and a verdict over two records is
>   not one this decision admits.
> - **By kind.** `minted` is `0` on every `READ_OUTCOME` row whose `read_kind` is not
>   `WEB_SEARCH` (§3), and `records` is empty on a `WEB_SEARCH` row.
> - **By standing.** `STANDING` carries neither `inapplicable_at_revision` nor `superseded_by`;
>   `INAPPLICABLE` carries `inapplicable_at_revision` and no `superseded_by`; `SUPERSEDED`
>   carries `superseded_by` and no `inapplicable_at_revision`. Every other combination is
>   refused, so a row that says it was displaced without saying by what is **not
>   constructible**.

**The mark and its argument travel together or the value does not construct, which is
ADR-0249 §1's own move one type over.** That section gives its reason in terms — *"The type is
what expresses the correspondence rather than a rule to remember, which is the move ADR-0244 §2
makes for `ParkedRead`'s content fields"* — and a row marked `SUPERSEDED` whose `superseded_by`
was left absent is exactly the half-state that rule exists to make unreachable. It is also what
makes correction 1 auditable: *"retained historical disagreements do not permanently block
progress"* is only checkable if every retirement names what did it.

> **Normative.** **`records` holds identifiers that resolve in the owner's `MemoryStore`, and
> holds nothing else.** A record ADR-0231 §1's search minted is **never** named there: ADR-0231
> §16 rules that such a record *"is not a citation target and not a durable reference … its `id`
> is minted for one turn … and resolves in no store"*, and a durable row naming one would state
> a warrant it cannot show — which is the refusal ADR-0249 §7 already takes against the same id
> and ADR-0249 §12's migration takes against a `FROM_EVIDENCE` ground it cannot substantiate.

> **Normative.** **What a `WEB_SEARCH` row carries instead is `minted`, a count and never an
> id.** It is how many records that servicing minted for this ask, and it is ADR-0086 §4's
> shape applied for ADR-0086 §4's reason: *"It is a count and never an id: keeping the ids would
> defeat the bound, since the ids are the payload."* Here the ids would not defeat a bound —
> they would defeat resolvability — but the honest record is the same one, a number that says a
> response was read and a silence where a reference cannot go.

> **Normative.** **`source` is the reading's own declared identity where the servicing has
> one, and is absent on every row this decision's producers write.** No producer of this
> decision fills it: the five `ReadKind` members each name their own source (§8), and the one
> shape that would carry a finer identity is a `Reader`'s `SourceReading.source`, whose producer
> is decision 8's reader and is not built here. **No lane fills it with a provider name, a host,
> an address, a path, a `Settings` field name or a credential identity** — ADR-0231 §13's bar,
> which ADR-0242 §9 states of `SearchNotServiced` and ADR-0226 §9 states of the audit, binds
> this field for the same reason: a durable row is a worse place for one of those than a log is.

> **Normative.** **A `GoalEvidence` carries no content.** It carries no record text, no snippet,
> no title, no excerpt, no query, no label, no rendered result and no prose of any kind. What it
> carries of the world is exactly the two applicabilities of §2, whose values are instants and
> the label vocabularies ADR-0237 and ADR-0213 already fix, and the two instants of §4.
> ADR-0226 §1's record-not-payload rule is the ground — *"What a serviced request returns into
> the supply is `MemoryRecord`s carrying their own `Provenance`, and never a payload, a
> rendering, a summary or free text of any kind"* — read one level down, at the durable record
> **about** a servicing rather than at the servicing's yield.

**A row is provenance and never a second copy of what was read.** ADR-0052 §3 makes each turn's
supply ephemeral; a row that carried the records' text would be a durable copy of Tier 1
content, written at a second site, retained on a second rule and exported by a second document —
every one of which is a thing the corpus decides elsewhere and none of which this decision is
entitled to re-decide. The records are named by id where they are durable, counted where they
are not, and read back through the store that holds them.

### 2. `EvidenceApplicability`: one shape for both applicabilities, so the coverage test is an inclusion

> **Normative.** `core/types.py` gains **`EvidenceApplicability`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `window`, a `TimeWindow | None`; `participants`, a
> `tuple[NonBlankEncodableText, ...] | None`; `topics`, a `tuple[TopicLabel, ...] | None`;
> `about_person`, a `tuple[NonBlankEncodableText, ...] | None`; and `elided`, an `int` `ge=0`
> defaulting to `0`.

> **Normative.** A **model validator** refuses an applicability applying **no** axis and one
> whose present sequence axis is **empty**. `None` is the one spelling of *not applied*, exactly
> as it is on `StructuredAsk` (ADR-0240 §2), and a value applying nothing is expressed by the
> field holding it being **absent** rather than by an empty applicability.

> **Normative.** `TimeWindow` is used exactly as ADR-0237 §2 defines it and is not
> re-expressed: the half-open `[start, end)` reading, the unset ends, the refusal of a window
> with both ends unset and the refusal of one whose `end` is not strictly after its `start` are
> that ADR's and are inherited whole. No second window type is minted, no applicability carries
> two windows, and none carries a sequence of them.

> **Normative.** **`requested` and `supported` are the same type, and the coverage test of §6
> is an inclusion of one in the other, stated once.** An applicability `A` **covers** an
> applicability `B` when, **for every axis**: `A`'s window contains `B`'s by ADR-0117 §3's
> containment predicate, read over the applicabilities' windows rather than over a
> `ReportedExtent` and a `ReadCoverage`; and for each label axis, `A`'s values are a superset of
> `B`'s. **An axis `A` does not apply covers no applied axis of `B`**, and an axis `B` does not
> apply is covered by anything.

**The containment predicate is ADR-0117 §3's, reused rather than restated, and the reuse is the
point.** That section states it as *"`E = [ef, eu)` lies wholly within `C = [cf, cu)` iff **`cf`
is `None` or (`ef` is not `None` and `ef >= cf`)** and **`cu` is `None` or (`eu` is not `None`
and `eu <= cu`)**"*, together with the sentence that decides the hard case: *"An unbounded
extent end is contained only by an unbounded coverage end on the same side."* That is the same
question this decision asks — *does what the source covered contain what we need?* — and a
second statement of it is a second place for the unbounded case to be got wrong.

> **Normative.** **An axis `A` does not apply covers no applied axis of `B`, and the direction
> is not negotiable.** An unapplied axis means *this applicability says nothing about that
> axis*, and a value that says nothing about the people a step names has not established
> anything about them. Reading an absent axis as *everything* would be the same substitution
> ADR-0240 §2 refuses at the ask — *"no value of any axis means 'everything'"* — arriving at the
> response instead.

> **Normative — the axes take the types of the fields they copy, and tighten only in ways that
> reject.** `participants` and `about_person` are `NonBlankEncodableText`, which is
> `StructuredAsk`'s own annotation for the first (ADR-0240 §2) and is a tightening of
> `EpisodicMemory.participants`' `EncodableText`; `topics` is `TopicLabel`, which both the ask
> and `MemoryRecord.topics` already carry. **A blank value on a returned record contributes
> nothing to `supported` and advances `elided`** — it is dropped, never stripped, never
> case-folded and never repaired. ADR-0096 §2's rule is the ground and its words are the reason:
> *"a faithful copy takes the type of the field it copies, and may tighten only in ways that
> reject … Tightening by *normalising* is how two spellings of one value drift."* A value naming
> nobody legibly is a value an applicability is narrower without, which is the safe direction
> (below).

> **Normative.** **Each label axis of an applicability holds at most
> `MAX_APPLICABILITY_VALUES` values, a fixed `core` constant valued 32**, not a `Settings`
> field, not a constructor knob and not a per-deployment value, on ADR-0213 §4's and ADR-0086
> §1's own rule — *"a knob that raises the ceiling is a knob that re-opens it."* A composition
> that would exceed it keeps the first 32 values in the order the source produced them and
> advances `elided` by the number dropped.

> **Normative.** **The truncation can never widen a warrant, and the direction is why it is
> admissible at all.** A narrower `supported` covers **less** and therefore satisfies **fewer**
> conditions (§6), so a truncated `supported` fails closed; a truncated `requested` establishes
> nothing either way, because `requested` establishes nothing at all (§3). ADR-0086 §4's refusal
> of silent truncation binds entire and `elided` is what discharges it — *"A displaced citation
> that leaves no trace would make a belief report a narrower warrant than it has"* — and the
> count is on the value rather than beside it so that no consumer can hold one without the
> other.

### 3. `requested` and `supported`: what each is composed from, and the prohibition list

> **Normative.** **`requested` is composed by `orchestration` from the *typed* part of the ask
> and from nothing else, and is absent where the ask has no typed part.** Per `ReadKind`, at the
> vocabulary ADR-0226 §2, ADR-0230 §1, ADR-0231 §1 and ADR-0240 §1 leave closed:
>
> - **`STRUCTURED_READ`** — present, composed from the `StructuredAsk`'s four axes, each carried
>   across **byte for byte** into the corresponding axis of the applicability. An ask carrying a
>   `query` beside its structure contributes the structure alone.
> - **`SIGHTED_QUERY`** — **absent**. The ask's only argument is a composed query.
> - **`CITATION_HOP`** and **`LOCAL_FILE`** — **absent**. Each ask's only argument is a label,
>   which is an ordinal into a sequence that does not survive the call.
> - **`WEB_SEARCH`** — **absent**, necessarily. ADR-0231 §1 gives the ask *"no field"*.

**One kind of five produces a `requested`, and that is the rule working rather than a gap.**
`requested` exists to record *what we went looking for* in a form a later turn can compare
against *what came back*, and a form that can be compared is a typed one. The four absences each
have a clause of the corpus behind them and none is an omission to repair later:

- **A composed query is a model completion.** ADR-0228 §11 rules it *"a model completion with no
  recorded origin, of the same class as `ActionPlan.rationale`"* and that *"no lane … treats it
  as evidence of anything."* Copying one into a durable row and rendering it back to the planner
  in a digest is exactly treating it as evidence of what was asked — and it is the shape #2255's
  *"a model merely repeating an old fact is not a refresh"* warns against, one level down.
- **A label does not survive its call.** ADR-0226 §3 fixes that *"A record's label is its
  position in the sequence the loop handed the planner"*, and ADR-0249 §9 states the consequence
  in terms: *"A label is meaningful only within the call that rendered it: **no label survives
  that call, and none is persisted as a reference.**"* A `requested` composed of `M2` would be a
  persisted label, which that sentence forbids by name.
- **A `LOCAL_FILE` entry resolves to a path**, and a path is an address of the owner's
  filesystem. ADR-0226 §9's counts-and-kinds rule keeps one out of the audit; a durable row is a
  worse place for one.
- **A `WEB_SEARCH` ask has nothing to compose from**, and that is ADR-0231 §1's *"whole safety
  mechanism and a property of the type rather than a rule an implementation is trusted to
  keep"*.

> **Normative.** **`supported` is composed from exactly two sources and from nothing else.**
>
> 1. **A typed read outcome that carries the applicability structurally** — read off the records
>    the ask **returned**, never off the ask. Per the fields ADR-0237 filters on and ADR-0240 §2
>    names: the **window** from each returned record's own interval — an `EpisodicMemory`'s
>    `occurred_at` as the degenerate interval at that instant, and a record's
>    `Validity.valid_from`/`valid_until` where it carries one — taken as the smallest
>    `TimeWindow` containing all of them; `participants` from each returned
>    `EpisodicMemory.participants`; `topics` from each returned `MemoryRecord.topics`; and
>    `about_person` from each returned `MemoryRecord.about_person`, which is one value per record
>    and reaches the axis as the set of the distinct values the returned records carry. Where a
>    returned record carries an `Attestation.extent` (ADR-0117 §2), **that extent is that
>    record's interval** and the record's own instants are not substituted for it, because
>    ADR-0117 §2 makes the extent *"the reporting source's own statement about the thing it
>    reported"* and this decision has no better authority for what a source covered.
> 2. **An interpretation verdict over exactly one recorded record** — the applicability the
>    interpretation step declared, over the one record its whole input was.
>
> **A row whose response establishes no applicability carries `supported` absent**, and
> ADR-0249 §10's sentence binds entire: **an absent `supported` supports nothing.**

> **Normative — the prohibition list, and each entry is a route this decision closes.**
> `supported` is **never** derived from `requested`; **never** from the ask, the query, the
> labels or the entry; **never** from the fact that a read completed, was serviced, was
> admitted, or reached its source; **never** from a `ReadOutcomeKind` member on its own;
> **never** from a model's sentence about what a response covered; and **never** from a
> detector, a classifier or any inspection of a record's text. The last is ADR-0098 §6 —
> *"No detector of injected instructions is a gate"* and *"No ADR, lane, or surface may state a
> bound it obtains from such a detector"* — and ADR-0146 §2's *"Discloser provenance is decided
> by **recorded origin**, never by inspecting a span"*, read on this axis: an applicability
> recovered by reading what a record says is an applicability whoever wrote that record chose.

**The asymmetry between the two fields is the whole of the addendum's point, and it is
structural rather than a rule to remember.** `requested` comes from the **ask**, which the loop
composed from a planner's output; `supported` comes from the **records**, which a store or a
source produced. They are therefore written from two different objects at two different moments,
and no implementation can fill the second from the first by accident — it would have to reach
for a value it is not holding. A single `applicability` field would have made the confusion a
one-line mistake, which is revision 0 of the report's shape and is what the addendum corrects.

> **Normative.** **A `WEB_SEARCH` row's `supported` is absent unless a minted record declares an
> extent**, and no lane infers one from the query, from the response's ordering, from a result's
> title or from the provider's identity. ADR-0231 §1 puts the namer with the user and leaves the
> response carrying no structural axis at all; what such a response does carry is its declared
> instant, which is `as_of` (§4) and not an applicability.

> **Normative.** **No `ContextFacet` produces an evidence row.** A facet is not a servicing, has
> no `ReadKind` and no typed outcome of an ask; and ADR-0096 §3 rules that *"A facet is built
> from a reading taken during the assembly that returns it. No facet is served from a cached,
> carried-over or previously assembled reading."* A durable row composed from one would be
> exactly the carried-over reading that clause forbids, held at a second address and read back
> on a later turn as though it were current. Revision 1 of the report's §E.1 names
> `ContextFacet.as_of` among `supported`'s sources; **that is corrected here rather than
> implemented**, and what a facet gives a turn it gives by being reassembled.

### 4. The two instants, reused as written

> **Normative.** `read_at` is the instant **this system** performed the read the row was
> composed from, taken from the injected clock, and is always present. `as_of` is the instant
> **the source itself declares** for that reading, and is absent where it declares none. Both are
> ADR-0096 §2's fields with ADR-0096 §2's meanings, and that section's prohibition binds
> **verbatim**: *"A facet's `as_of` carries only an instant the source itself declares. It may
> never be filled from the filesystem, from the clock, from `read_at`, or from one entry's stamp
> applied to the rest."*

> **Normative.** Per basis and per kind, `as_of` is taken from: a **`WEB_SEARCH`** row, the
> response's declared instant, which ADR-0231 §16 already names — *"mints records whose
> `reported_at` is that response's declared instant"*; a row over records carrying an
> `Attestation`, that attestation's `reported_at` (ADR-0092 §3), taken as the **earliest** where
> the row's records carry several; and **absent everywhere else**, including on every row whose
> records are the owner's own store-written beliefs and episodes, which declare no reading-level
> instant.

**The earliest and not the latest, because the row states one instant for a set.** A row
composed from three records the source reported at three moments speaks for the picture as of
the oldest of them; taking the newest would let one fresh record make two stale ones look
current, which is ADR-0096 §2's *"a true statement about us and a false one about the source"*
arriving through an aggregation instead of through a substitution.

> **Normative.** **No row carries a staleness verdict**, and ADR-0096 §3 binds this decision
> entire: no boolean, no freshness class, no expiry, no `Settings` figure defining when a row
> becomes stale, and no producer, store or surface withholds, drops or downgrades a row because
> it judges it old. **Age is computed by a consumer from the instants the row carries**, and the
> one consumer this decision gives it is §6's fourth test, which reads a figure the **plan**
> declared and never one the evidence carries.

**This is why ADR-0096 can be relied on rather than superseded, and it is the load-bearing move
of the whole decision.** The addendum's *"Retaining an old forecast does not mean it remains
sufficient to permit booking"* reads, on first hearing, as a demand for staleness — and
staleness is exactly what ADR-0096 §3 refuses to put in `core`, for a reason that has not
weakened: *"nothing has measured how old a calendar reading may be before a plan built on it is
wrong, and inventing a number to have one"* would be an unargued figure. The resolution is that
the question was never about the evidence. A forecast does not become insufficient; a **booking
step** declares what it needs, and the step's own prerequisite fails. §6 puts the figure where
the decision is, and ADR-0096 §3 keeps every clause it had.

### 5. The verdict vocabularies, and which member of each is affirmative

> **Normative.** **`verdict` carries the value of a typed outcome and never a prose summary**,
> which is ADR-0249 §10's clause binding on the row exactly as it binds on the digest. Which
> vocabulary the value is drawn from is decided by `basis` and by nothing else (§1), so a reader
> holding a row never has to guess what `"empty"` is a member of.

> **Normative — the `READ_OUTCOME` vocabulary is ADR-0251 §2's `ReadOutcomeKind`, adopted
> whole and not re-minted.** A `READ_OUTCOME` row's `verdict` is the value of the
> `ReadOutcomeKind` member ADR-0251 §2's classifier assigned to that ask —
> `RETURNED_RECORDS`, `EMPTY`, `DUPLICATE`, `TRUNCATED`, `REFUSED`, `FAILED` or `EXPIRED`. That
> vocabulary is ratified and is **not in the tree at `54c6b72e`**, because ADR-0251's
> implementation has not landed; this decision's implementing lane therefore depends on it and
> §17 cuts the lanes so that it lands first.

**Every incomplete, empty, refused, failed and expired result stays distinct and none of them
satisfies anything, and the vocabulary is reused rather than added to.** ADR-0251 §2 already
separated the seven for the reasons this decision would have to restate — *"`REFUSED` and
`FAILED` are separated because they license different next moves"*, *"`EXPIRED` is its own member
and is not folded into `FAILED`"*, and `DUPLICATE` kept apart from `EMPTY` because *"the store
returned records, and a planner told otherwise would broaden away from records already in front
of it"*. A second vocabulary for the same question would be the *"two carriers for one fact"*
defect ADR-0251 §3 names, with the first implementation to disagree with itself being right in
one of them. **No member is added here**, because none is missing: the seven are stated to be
*"disjoint and exhaustive over the asks a servicing reached"*.

> **Normative — the `INTERPRETATION` vocabulary is the one the interpretation step declares,
> and this decision fixes its shape and not its members.** An `INTERPRETATION` row's `verdict` is
> the value of a member of a **closed** enumeration the plan's interpretation step declared,
> whose members that step's own decision fixes, and which **always** carries a member meaning
> *the record does not settle it*. **A row whose verdict is that member satisfies nothing** (§6).
> Which enumeration it is, and what its affirmative member is called, is A5's and A7's (§15).

> **Normative — the two vocabularies are disjoint in their values, so a `verdict` identifies
> itself.** No member of the interpretation enumeration takes a value equal to any of
> `ReadOutcomeKind`'s seven. The digest carries `verdict` and **not** `basis` (ADR-0249 §10 fixes
> its six members and this decision adds none), so a value that could belong to either vocabulary
> would be a value a reader of the digest cannot interpret — and a planner told `"empty"` without
> being told of what would be told nothing. The constraint is on the **later** vocabulary, which
> is the one not yet minted.

> **Normative — the affirmative test, which is §6's second, stated here once per basis.**
>
> - A **`READ_OUTCOME`** row's verdict is **affirmative** where the ask **admitted at least one
>   record the supply did not already hold**, counted after ADR-0226 §7's deduplication — so
>   `RETURNED_RECORDS` always, and `TRUNCATED` where it admitted a record. **`EMPTY`,
>   `DUPLICATE`, `REFUSED`, `FAILED`, `EXPIRED` and a `TRUNCATED` that admitted none are each
>   non-affirmative and each satisfy nothing.**
> - An **`INTERPRETATION`** row's verdict is **affirmative** where it is the member the
>   interpretation step declared as settling the proposition, and non-affirmative for every other
>   member of that enumeration.

**The affirmative test is ADR-0251 §7's productivity fold, reused rather than re-derived.** That
section states it as *"a round is productive where *any* ask of it admitted at least one record
the supply did not already hold, counted after ADR-0226 §7's deduplication"*, and adds the
property that makes it usable here: *"The fold is over records admitted and never over the
member, which is what keeps it total and free of the contradiction a member-based test carries
… The test is a count and never a judgement about relevance, quality or usefulness."* Read per
ask rather than per round, that is exactly the question *did this response put anything new in
front of us*, and reusing it means the loop's progress test and this decision's sufficiency test
cannot come to disagree about one servicing.

**`DUPLICATE` is the case that separates §6's first two tests, and it is why they are two.** A
duplicated-out ask **returned** records, so §3 composes a `supported` from them and the coverage
test passes; what it did not do is put anything in front of the planner it did not already have,
which ADR-0251 §7 counts as unproductive. Without the second test such a row would satisfy a
condition on the strength of a read that told the turn nothing — and the earlier row those
records already justified is still standing and still says so, so nothing is lost by refusing it.

> **Normative.** **`EMPTY` is the member that most invites a false reading, and it establishes
> nothing about the world.** ADR-0237 §7 binds this decision entire and its clause is quoted
> rather than paraphrased: *"No consumer composes an assertion of absence from an empty or short
> structured result — not to the owner, not into a record, and not into a plan."* **An evidence
> row is a record in that clause's sense.** So an `EMPTY` row records that an ask was made and
> came back with nothing; it carries `supported` absent (there are no records to compose one
> from), it satisfies no condition, and **no lane reads it as evidence that the thing it asked
> about did not happen, does not exist, or is not so.**

### 6. Sufficiency to act: four mechanical tests, evaluated at dispatch

> **Normative.** A condition of a goal is **satisfied for the purpose of dispatching a step**
> only where a `GoalEvidence` row of that goal exists for which **all four** of the following
> hold. Each is a comparison of values or of members of a closed vocabulary; **none is a
> judgement, and no model output settles any of them.**
>
> 1. **Coverage.** The row's `supported` **covers** the applicability the step's condition
>    declares, by §2's inclusion. An **absent `supported` covers nothing**, so a row with none
>    fails here first.
> 2. **Affirmative verdict.** The row's `verdict` is affirmative in §5's sense.
> 3. **Standing.** The row's `standing` is **`STANDING`**. An `INAPPLICABLE` row and a
>    `SUPERSEDED` row each satisfy nothing.
> 4. **Recency.** The row satisfies the **step's declared recency requirement**, evaluated at
>    **the moment of dispatch** against `as_of` where the source declared one and against
>    `read_at` otherwise.

> **Normative — where coverage is unproven it is exact, and it refuses.** No lane folds,
> widens, clamps, rounds, extends or normalises an applicability in order to make a coverage test
> pass — not a window to a day boundary, not a label to a case-folded form, not an unapplied axis
> to *everything*. ADR-0148 §2's default is the rule and its words are the reason: *"Where the
> protocol does not establish that two distinct supplied forms denote the same recipient, the
> canonical form is the supplied form unchanged and comparison against it is byte-exact. No
> canonicaliser folds case, strips, reorders or rewrites a form on any ground weaker than the
> protocol saying those two forms are one recipient."* Label comparison is
> ADR-0101 §2's canonical caseless fold where the axis's own type already fixes one — which
> `TopicLabel` does (ADR-0213 §3, *"refused rather than normalised"*) and `participants` does
> (ADR-0237 §2) — and is byte-exact everywhere else.

> **Normative — recency is the plan's declaration and never the evidence's property.** The
> figure lives on the step, A5 lands the field, and **a step that declares no recency
> requirement imposes none**: its condition is satisfied by a row that passes the first three
> tests however old it is. **Evidence never expires by itself**, no sweep marks a row for age, and
> no `Settings` figure, deployment flag or per-request parameter supplies a default.

**The two absent declarations point in opposite directions, and that is deliberate rather than
an inconsistency.** Test 2 has a closed vocabulary whose affirmative member §5 fixes, so a
condition that named no member would be a **missing** declaration and fails closed on ADR-0228
§2(a)'s rule — *"no implementation reads an absent declaration as a default, as
unknown-and-therefore-permitted, or as a case to decide at run time from anything other than a
declaration."* Test 4 has **no figure anywhere in this system** to be missing: ADR-0096 §3
refuses to put one in `core` and explains why — *"nothing has measured how old a calendar
reading may be before a plan built on it is wrong, and inventing a number to have one would be
the padded-list failure"* — so a default here would not be a fail-closed reading of a
declaration, it would be a number nobody decided, gating a user's act. The owner's standing rule
settles the direction: *convenience alone is insufficient justification for a user-facing
restriction*, and a fabricated expiry is a restriction bought for nothing at all.

**Retention is not sufficiency, and the two are kept apart because #2255 asks for both.** A row
that fails test 4 is **retained**, stays visible in the history, stays in the digest the planner
sees, and stays available for composing an answer that says what was known and when. What it
does not do is satisfy a condition whose recency requirement it no longer meets. Nothing is
dropped, nothing is hidden and nothing is downgraded — which is ADR-0096 §3's *"A facet's age
never gates its presence"* holding, with the gate moved onto the act rather than onto the
record.

> **Normative.** **This decision dispatches nothing, and the tests above have no caller in it.**
> The step that declares a condition is A5's, the stage that dispatches one is A7's, and the
> authorization coverage a dispatch also needs is A6's. What is fixed here is the predicate and
> its operands; **no lane reads this section as authority for dispatching a step, for refusing
> one, or for writing any `GoalStatus`.**

> **Normative.** **A model never clears one of these tests.** ADR-0249 §7's asymmetry binds
> entire: *"A model may never clear a permission, a coverage test, a prerequisite or a
> dependency, and no clause of this decision or of any lane implementing it takes one on a
> model's word."* An `INTERPRETATION` row is not an exception and is the case that most looks
> like one: what the model supplied is a member of a closed enumeration over one recorded record,
> and **which effect follows is the plan's declared branch** — the model can produce one of *n*
> values and cannot produce the dispatch.

### 7. Conflict and incompleteness: what can disagree, what cannot, and what an obstacle is

> **Normative — two rows conflict where all of the following hold**: both are `STANDING`; both
> have `basis` `INTERPRETATION`; their `supported` applicabilities **overlap**, meaning some
> applicability is covered by both; they were drawn from the **same** declared enumeration; and
> their `verdict`s are **different members** of it.

> **Normative.** **Where a condition is covered by two conflicting rows it is not satisfied, and
> the disagreement is reported.** No rule picks a winner: **not recency, not source, not
> confidence, not a count of rows on each side, and not a preference between kinds.** The
> condition fails test 2 of §6 because no single row settles it, and the obstacle is what the
> turn reports rather than a constraint quietly relaxed.

**No tie-break, and each of the tempting ones is refused by a clause already ratified.** A
recency rule would let a later, weaker read overturn an earlier, stronger one — and §8's
supersession is the *narrow* case in which recency does decide, bought by requiring that the
later row be a refresh of the same ground from the same source rather than merely newer. A
source-preference rule is source reputation, which ADR-0098 §6's second clause forbids anyone
from buying a bound with: *"No ADR, lane, or surface may state a bound it obtains from such a
detector."* A confidence score is a model's judgement about its own judgement, which ADR-0249
§7's asymmetry keeps out of a clearing decision. What is left is the honest outcome #2255 names:
an obstacle reported.

> **Normative — a `READ_OUTCOME` row never conflicts with anything, and this is a correction of
> the design direction rather than an omission.** A `ReadOutcomeKind` member *"states what became
> of the ask and never why a source ruled the way it did"* (ADR-0251 §2), so two read rows over
> overlapping applicabilities state two facts about two asks and disagree about nothing. **No
> lane manufactures a disagreement between them** — not by comparing the records they name, not
> by comparing their texts, not by counting them, and not by any inspection of what a record
> says.

**Revision 1 of the report's §E.4 is written as though any two standing rows could disagree, and
they cannot.** Its shape is right and its operand is wrong: *"Where two rows' `supported`
applicabilities overlap and their verdicts disagree"* is a real test, but for a read row the
verdict is about the **ask** and not about the world, so the disagreement it describes is
unreachable on that basis. Manufacturing one would mean reading the records — which is content
inspection, which ADR-0098 §5 and §6 and ADR-0146 §2 rule out on this path, and which would put
the adjudication in exactly the place #1844's steered-loop note warns about. So the section is
narrowed to the basis that **can** disagree, which is the one whose verdict is a judgement about
a proposition: the interpretation verdict. That is also where #2255's *"conflicting evidence"*
scenario actually lives — two readings of a source, not two readings of a store.

> **Normative.** **An incomplete, empty, refused, failed or expired outcome satisfies nothing
> and is not an obstacle either.** Each is recorded as its own row with its own verdict; each
> fails §6's second test; and none of them is read as establishing that the thing asked about is
> absent, unreachable or impossible. ADR-0251 §9's clause is what keeps that from escalating:
> *"a `WEB_SEARCH` answering `SearchDisposition.NOT_CONFIGURED` on a turn whose reads admitted
> nothing … passes limbs 1 and 2 and **fails limb 3**"*, because *"One unavailable source
> establishes that one route is shut, not that it was the only one."*

> **Normative.** **A servicing that did not complete produces no row at all.** ADR-0251 §2's
> classifier case 1 is the rule — *"the ask was not made, the budget did not reach it, or the
> servicing's stage did not run to its end"* produces no outcome entry — and a row composed where
> there is no entry would be a record of an ask nobody put. ADR-0228 §2(d)'s posture is the
> reason: a servicing that failed or was partial *"leaves the supply as planning saw it"*, so
> there is nothing to compose a `supported` from and nothing that happened to record.

### 8. Supersession: what refreshes the same, what never supersedes, and the mark that never un-marks

This section is the owner's **correction 1** implemented: *"Refreshed evidence needs supersession
rules, so retained historical disagreements do not permanently block progress."*

> **Normative — the refresh test, and all five limbs must hold.** A row `L` **refreshes** an
> earlier row `E` of the same goal where:
>
> 1. `E.standing` is `STANDING`;
> 2. `L.basis` **equals** `E.basis`;
> 3. `L.read_kind` **equals** `E.read_kind` and `L.source` **equals** `E.source`, absent
>    counting as equal to absent and never to a present value;
> 4. both `supported` applicabilities are **present** and they **overlap** in §7's sense; and
> 5. `L`'s verdict is **affirmative** in §5's sense.
>
> **A row that refreshes an earlier row supersedes it**: the earlier row's `standing` becomes
> `SUPERSEDED` and its `superseded_by` names `L`, in the same indivisible write that records `L`
> (§12).

> **Normative — what never supersedes, each stated so a later lane cannot read it back in.** A
> row of a **different basis**; a row of a **different `read_kind`** or a **different `source`**;
> a row whose `supported` is **absent**, and a row whose earlier candidate's `supported` is
> absent; a row whose verdict is **not affirmative**; a **model sentence**, which is never a row
> at all (§14); and a row of a **different goal**, which the store refuses outright (§12).

**Limb 5 is the one that protects the user, and without it a transport failure retires a good
forecast.** A refresh that came back `FAILED`, `REFUSED`, `EXPIRED` or `EMPTY` establishes
nothing and carries no `supported` to overlap with; permitting it to supersede would mean that
*asking again and getting nothing* silently retired the answer we had, and the next dispatch
would fail a condition that was satisfied a moment earlier for no reason anyone recorded. The
asymmetry is #2096 item 8's, one level down: **a later read may confirm and displace, and may
never retire by failing.**

**Limbs 2 and 3 are what "the same source" means in this system, and the honest answer is
narrower than it looks.** Every kind names its own source — a `SIGHTED_QUERY`, a
`STRUCTURED_READ` and a `CITATION_HOP` read the owner's own `MemoryStore`, a `LOCAL_FILE` reads
the owner's filesystem through the `Fetcher` seam, and a `WEB_SEARCH` reads the configured
provider — so within this decision's producers `read_kind` **is** the source identity, and
`source` is absent on every row they write (§1). A finer identity is not withheld out of caution:
the only one available for a `WEB_SEARCH` is the provider's name, which ADR-0231 §13's bar and
ADR-0242 §9's keep out of a record that states what became of an ask. **The `source` field is the
carrier for the identity a `Reader` will have and nothing else**, which is ADR-0249 §10's own
posture toward `EvidenceStanding.SUPERSEDED` — the decision lands the carrier so that the lane
that needs it does not have to reopen a `core` type — and §15 names what fires it.

**Limb 4 is why a refresh of one thing does not retire another.** *Overlap* and not *equality*:
a row supporting the coming week and a row supporting Saturday alone overlap, so a fresh read of
the week displaces the Saturday row it subsumes. Two rows about different weekends do not
overlap and neither touches the other. Requiring equality would make a refresh almost never
fire — the applicabilities a store returns are composed from whatever records came back and are
rarely byte-identical twice — and correction 1 would be satisfied in form and not in fact.

> **Normative.** **Supersession never un-marks, exactly as invalidation does not (§9).** A row
> that is `SUPERSEDED` is never returned to `STANDING`, by a later revision, by a later refresh,
> by the deletion of the row that displaced it, or by any other route. The mark is terminal and
> the row is kept.

> **Normative.** **A `SUPERSEDED` row blocks nothing**, which is ADR-0251 §9's clause taking
> effect: *"Where evidence rows disagree and one carries `EvidenceStanding.SUPERSEDED`
> (ADR-0249 §10), **the superseded row blocks nothing**: it is not counted toward any progress
> test of §7, it does not satisfy either limb above, and no attempt stops on it. **Which rows are
> superseded is A4's** (ADR-0249 §13)."* This section is the answer that sentence names, and
> §6's third test is where it bites: a superseded row satisfies nothing, and §7's conflict test
> reaches only `STANDING` rows, so a disagreement one side of which has been refreshed **stops
> being a disagreement** and the goal proceeds.

**Two standing rows that disagree still disagree, and correction 1 does not ask otherwise.** The
correction's subject is *retained historical* disagreements — a reading from three days ago that
nothing has revisited — and the mechanism it asks for is a way for new work to displace old
work. What it does not ask for is that a live disagreement be resolved by fiat, and §7's refusal
to pick a winner is untouched: the route out of a standing conflict is to **read again**, which
supersedes the side that was refreshed and leaves the other standing to be refreshed in its turn.

### 9. Invalidation: keyed on `supported`, a marking with its revision, never a deletion

> **Normative.** When `orchestration` records a new interpretation revision on a goal, every
> `STANDING` row of that goal whose **`supported`** applicability **names a value the revision
> changed** is marked `INAPPLICABLE`, with `inapplicable_at_revision` carrying the `revision`
> that did it. **Naming** is mechanical: the changed value falls inside `supported`'s window, or
> is a member of one of its label axes under §6's comparison. Every other row is untouched.

> **Normative.** **The marking keys on `supported` and never on `requested`.** A row whose ask
> named Saturday but whose response supports the coming week **survives** a move to Sunday,
> because what it establishes still covers the new date; a row whose response supports Saturday
> alone does not. Keying on `requested` would discard the first, which is a row the system paid
> for and still holds the warrant of.

> **Normative.** **Invalidation is a marking and never a deletion.** The row is kept with its
> applicabilities, its instants, its verdict and its references intact; it is still exported
> (§13), still reachable through `get_evidence` and `evidence_of`, and still in the digest the
> planner sees (§11). What changes is exactly one field.

> **Normative.** **Invalidation never un-marks.** A later revision that restores the old value
> does **not** return the row to `STANDING`: it is read again or it is not used. Un-marking would
> make a goal's evidence state depend on the **order** of its revisions rather than on what is
> known, so two goals that reached the same understanding by different routes would hold
> different evidence — which is the *"second authority that can disagree"* ADR-0249 §5 refuses
> for a status member, arriving at a mark instead.

> **Normative — what is deferred is the derivation of the changed set, and not the predicate.**
> **Which values a revision changed** is computed from the step-level declared keys A5 lands
> (§15); no type in the tree at `54c6b72e` carries a typed applicability on a `GoalInterpretation`
> or on a `GoalElement`, and this decision mints none there. Until A5 lands, **the changed set is
> empty and no row is invalidated**, which is stated here rather than left to inference.

**That interval is safe rather than merely admitted, and the reason is that nothing can act on
evidence yet.** §6's tests have no caller in this decision, the stage that dispatches a step is
A7's, and the step that declares a condition is A5's — the same lane that lands the declared
keys. So there is no tree on which a row could be stale, unmarked, and permitting an act: the
first lane that can dispatch against evidence is the lane that can also invalidate it. This is
ADR-0249 §4's posture stated for a predicate rather than for a status — *"`ACHIEVED` gets no
producer here"* — and declining to invent a derivation from values that do not exist is the
honest outcome rather than a gap left open.

### 10. Grounding an interpretation element on an evidence row

> **Normative.** **`core/types.py`'s `GoalElement` gains `evidence_row_id`, an `Identifier |
> None`, and its validator admits a fourth shape**: a `FROM_EVIDENCE` element carries **exactly
> one** of `evidence_id` — the record of the labelled supply ADR-0249 §7 stamps — and
> `evidence_row_id` — a `GoalEvidence` row **of the same goal**. `USER_STATED` and `INFERRED`
> carry neither, exactly as before. **`GoalInterpretation` gains `outcome_evidence_row_id` on the
> same rule**, because ADR-0249 §1 validates the outcome's arguments *"as a `GoalElement`'s are"*.

> **Normative.** **The planner names an evidence row by label, never by identifier**, and the
> scheme is ADR-0226 §3's applied to a fourth sequence in the shape ADR-0249 §9 applied it to
> three. The label of the digest at 1-based index *n* of `Planner.plan`'s **`evidence`** sequence
> is the ASCII string **`E` followed by *n*** in decimal with no padding. That is the whole of
> the scheme, it is the same on both sides of the seam, both sides derive it from the sequence
> they hold and neither consults the other, and **no label survives the call that rendered it**.

> **Normative.** A `ProposedElement`'s **`evidence_label` carries either an `M` label or an `E`
> label**, and the prefix is the whole of what decides which sequence `orchestration` resolves it
> against: `M` against the `memories` passed on that call, `E` against the `evidence` passed on
> that call. **`ProposedElement` gains no field.** A label of neither form, an *n* below 1 or
> beyond the sequence's length, and an `E` label naming a row the store no longer holds each
> **resolve to nothing**, and the element is **dropped silently** — not an error, not a park, not
> a degradation of the turn — which is ADR-0249 §7's disposal binding unchanged over one more
> way to fail to resolve.

**The prefix rather than a second field, because the label space is already per sequence and the
planner already knows which one it read.** ADR-0249 §9 fixed `C`, `S` and `D` for the brief's
three tuples and stated the property this reuses — *"the label space is per tuple"*, so a label
naming an element of another tuple *"resolves to nothing"*. A second field would let a planner
emit both and the loop choose, which is the *"two carriers for one fact"* defect; the prefix
makes the two spaces mutually exclusive at the value. And ADR-0226 §3's clause that no lane
*"substitutes another spelling, adds a prefix per group, or makes it configurable"* is scoped to
the `memories` sequence it governs: ADR-0249 §9 added three prefixes for three other sequences
without disturbing it, and this is the fourth.

> **Normative.** **A row id is stamped by `orchestration` and never parsed out of model output**,
> which is ADR-0226 §3's namer rule and ADR-0228 §8's statement of it binding on one more
> identifier: *"no record identifier is rendered to a model and none is accepted from one."* The
> digest carries no row id (ADR-0249 §10), the label is an ordinal, and the loop stamps the id of
> the row **it itself labelled**.

> **Normative — what happens to an element when its row is marked: nothing.** A `GoalElement`
> grounded on a row that is later marked `INAPPLICABLE` or `SUPERSEDED` is **not rewritten, not
> dropped, not re-grounded and not removed from the revision it sits in**, and no lane records a
> revision on account of a mark. ADR-0249 §1's sequence is append-only and a revision is a
> statement of what was understood **when it was recorded**; editing one to reflect a later mark
> would destroy exactly the audit the chain exists to be. What the mark changes is **sufficiency**
> (§6), which is evaluated at dispatch against the row and never against the element.

> **Normative — a `FROM_EVIDENCE` element whose `evidence_row_id` resolves in no row is
> answerable and is never repaired.** The one route to it is §13's elision. Such an element is
> answered exactly as ADR-0249 §11 answers a park whose goal the store does not hold — *"an
> identifier and not a resolution guarantee"* — the element still states what it says, the
> missing warrant is disclosed by `EvidenceHistory.elided`, and **no lane repairs, back-fills or
> refuses it, and none reorders retention to prevent it.**

**That is not the search-minted case wearing a different hat, and the difference is
disclosure.** ADR-0249 §7 refuses a ground naming a minted record because its id *"resolves in no
store"* from the instant it is written and nothing anywhere records that it once did. An elided
evidence row **was** durable, **was** resolvable, and its loss is carried as a count on the very
value a reader consults. A warrant that says *this rested on a row the history has since dropped,
and here is how many it has dropped* is a true statement; a warrant that says *this rested on an
id* when no id ever resolved is not.

### 11. The digest the planner sees, and what reads a row's standing

> **Normative.** The `evidence` the loop passes to `Planner.plan` is **one `EvidenceDigest` per
> row of that goal's history the store holds**, in `read_at` order oldest first, projected by
> `orchestration` alone. Its six members are ADR-0249 §10's and this decision adds none:
> `requested` and `supported` are the rendering below of the row's applicabilities; `read_at`,
> `as_of` and `standing` are the row's own; and `verdict` is the row's `verdict`.

> **Normative — the rendering, which is deterministic and is `orchestration`'s.** An
> `EvidenceApplicability` renders to an `EncodableText` as its **applied** axes in the model's own
> field order — window, participants, topics, about_person — each named by its field name;
> unapplied axes are omitted; a window's ends render as ISO-8601 UTC instants and an unset end as
> the absence of that end; label values render **byte for byte** in the order the applicability
> holds them; and a non-zero `elided` renders as a count. An **absent** applicability renders as
> an absent digest member, which is what makes ADR-0249 §10's *"an absent `supported` supports
> nothing"* legible on the seam. **No model writes the rendering, no lane substitutes a prose
> summary for it, and no lane makes it configurable.**

> **Normative.** **Every row is projected, `INAPPLICABLE` and `SUPERSEDED` ones included**, and
> the digest's `standing` is what says which. ADR-0249 §10 put the member there for exactly this
> — *"so that refreshed evidence has a way to state that it displaces an older disagreement
> rather than standing beside it forever"* — and a digest sequence filtered to `STANDING` would
> make the member constant and the sentence false.

> **Normative.** **The digest carries no identifier of any kind**, which is ADR-0249 §10's
> clause binding on this projection: no evidence row id, no memory id, no snippet, no title and
> no address. Nor does it carry `basis`, `read_kind`, `source`, `records`, `minted`,
> `inapplicable_at_revision`, `superseded_by`, or the row's goal or attempt. **Those are the
> row's and the loop's**, and the containment is a property of the type exactly as ADR-0249 §9
> argues for `GoalBrief`: *"an implementation that rendered every field of every value it was
> handed, logged them all, or returned them, discloses none of those, because there is none on
> the value to disclose."*

> **Normative.** **The planner is not told which rows satisfy anything.** No member of the
> digest says *sufficient*, *usable*, *fresh*, *covering* or *satisfied*; §6's four tests are
> evaluated by code at dispatch and their result crosses no seam. ADR-0249 §7's asymmetry is the
> ground, and ADR-0251 §3's clause is the precedent one level over: *"the planner is still not
> told which round it is on."*

> **Normative.** **No new class of content crosses the seam.** A rendered applicability carries
> instants and the label vocabularies the planner itself composes asks from and already sees on
> the records in `memories`; ADR-0004 §5's rule that *"Tier 0/1 data must never be logged"* binds
> unchanged and **nothing here logs a row, an applicability or a digest**. `_render_request`
> prints no identifier, which is ADR-0249 §9's clause extended by nothing.

> **Normative — the digest sequence is bounded by construction and needs no second bound.** At
> most `MAX_GOAL_EVIDENCE` rows exist per goal (§13), so at most that many digests are rendered,
> and the elision that keeps it so is disclosed on `EvidenceHistory` rather than being silent.
> ADR-0086's obligation is discharged at the store rather than at the seam, so no lane truncates
> the sequence at the seam and none reports a second count there.

> **Normative — what ADR-0251 §9 reads from a row is `standing` and nothing else.** That
> section's rule — that a superseded row *"is not counted toward any progress test of §7, it does
> not satisfy either limb above, and no attempt stops on it"* — is evaluated from
> `EvidenceStanding` alone. **No lane gives the loop's progress test, its unproductive-run test,
> its stop reasons or its `BLOCKED` predicate any other field of a row**, and this decision adds
> no producer of `GoalStatus.BLOCKED`, `ACHIEVED` or `ABANDONED`.

### 12. `PlanStore` gains four members, and this is a BREAKING contract change

> **Normative.** `PlanStore` gains the following **four** members, and this is a **BREAKING**
> contract change under golden rule 5, layering on ADR-0249 §12's widening of the same Protocol
> and on ADR-0250 §9's:
>
> - **`record_evidence(evidence: GoalEvidence, /, *, supersedes: Sequence[Identifier] = ()) ->
>   str`** — persists a **new** row and returns its id. It **refuses** a row whose `id` the store
>   already holds, and a row whose `goal_id` the store does not hold, each with the error class
>   an unknown goal already raises. In the **same indivisible step** it marks each row named by
>   `supersedes` `SUPERSEDED` with `superseded_by` set to the new row's id, refusing the whole
>   call where any named row is not this goal's, is not `STANDING`, or is the row being written.
>   It performs §13's elision.
> - **`invalidate_evidence(invalidation: EvidenceInvalidation, /) -> int`** — marks each named
>   row `INAPPLICABLE` with `inapplicable_at_revision` set to the command's `revision`, and
>   returns **how many rows this call moved from `STANDING`**. A row already marked is left
>   exactly as it stands and is not counted. The read, the comparison and the write are one
>   indivisible step.
> - **`get_evidence(evidence_id: str, /) -> GoalEvidence | None`** — the row, or `None`.
> - **`evidence_of(goal_id: str, /) -> EvidenceHistory`** — that goal's rows in `read_at` order
>   oldest first, with `elided` counting what §13's bound has dropped.

> **Normative.** `core/types.py` gains **`EvidenceInvalidation`**, a frozen command with
> `extra="forbid"` carrying exactly `goal_id` (an `Identifier`), `revision` (an `int` `ge=1`) and
> `evidence_ids` (a **non-empty** `tuple[Identifier, ...]`); and **`EvidenceHistory`**, a frozen
> model with `extra="forbid"` carrying exactly `rows` (a possibly-empty `tuple[GoalEvidence,
> ...]`) and `elided` (an `int` `ge=0`).

> **Normative.** **The store accepts commands, not snapshots.** Neither mutation takes a whole
> `GoalEvidence` back in order to write it, and no member replaces a stored row. ADR-0014 §5's
> argument binds unchanged and is ADR-0249 §12's reason for the same shape: *"Had the store taken
> a whole `ExecutionState`, any consumer of the Protocol could commit `PENDING → SUCCEEDED`
> directly and the claim that deterministic code owns state transitions (VISION §7) would rest on
> nobody choosing to bypass it."*

> **Normative — the standing member is the compare-and-swap token, and `GoalEvidence` carries no
> `version`.** A row moves **once**, from `STANDING` to a terminal member, and never again (§8,
> §9), so the comparison a write needs is *is this row still `STANDING`* and a monotonic counter
> beside it would be a second spelling of the same fact. **Every write compares and swaps on that
> member with the read in the same indivisible step**, and a caller that lost the race changes
> nothing, records nothing and reads the settled state back. That is ADR-0250 §9's
> `settle_question` shape — *"answering `True` to the caller that moved it and `False` to every
> other"* — applied to a mark instead of a disposition, and it is why `invalidate_evidence`
> returns a count rather than a row.

> **Normative — the predicate is `orchestration`'s and the atomicity is the store's, and the
> split is deliberate.** The loop computes **which** rows a new row refreshes (§8) and **which** a
> revision invalidates (§9); the store applies the marks it is given **atomically with the write
> that occasions them** and evaluates neither predicate. A store that evaluated the refresh test
> would be a second place the rule lives, and the first conforming implementation to read it
> differently would be right in one of them. A loop that applied the marks in a **second** write
> would leave a window in which a refreshed row and its refresher both stand — which for
> correction 1 is the exact failure being fixed, so the window is closed by construction.

> **Normative.** **`delete_goal`'s cascade reaches evidence**, and `GoalDeletion` gains
> **`evidence_removed`, an `int` `ge=0`**, reported exactly as ADR-0249 §12 has it report
> attempts and ADR-0250 §9 has it report questions. ADR-0014 §5's rule — *"a goal the user
> deletes must not leave its plan history behind"* — is **extended rather than re-promised**, and
> its live-step refusal is unchanged: it keys on a `RUNNING` step, and no row of any standing
> blocks a deletion. **No member deletes one row**, so the only route out of the store for a row
> is its goal's deletion, `clear`, or §13's elision.

> **Normative.** **No new Protocol is created**, so no new conformance suite and no new canonical
> fake is owed. The existing `PlanStore` conformance suite, `InMemoryPlanStore`,
> `SqlitePlanStore` and the canonical fake in `ai_assistant.testing` each gain all four members
> **in the same change that adds them** (`CONTRIBUTING.md` → "Adding a Protocol": *"The triad is
> what a Protocol *change* is measured against too"*). A conformance suite exercising one
> implementation would be a suite that lets the other disagree.

> **Normative — `PROTOCOL_VERSION` does not move, and that is stated rather than left to
> inference.** Nothing this decision adds is carried on a wire-borne type. `GoalEvidence` reaches
> no frame: `TurnResult.goal` is a `GoalBrief` (ADR-0249 §11), `EvidenceDigest` crosses the
> in-process `Planner.plan` seam and already exists at the tree's current version, and
> `PlanExport` *"crosses no frame: it is the portable document `PlanStore.export` returns,
> reached through that Protocol and emitted by no peer"* (ADR-0249 §12). **`GoalElement`'s new
> field is the one to check**, because `GoalElement` is reachable from `Goal`, which
> `PlanExport` carries — and `PlanExport` is not a wire ground, while `Goal` itself no longer
> rides on `TurnResult`. **A lane that finds a wire-carried route to any value this decision adds
> moves the constant by one and records the reason in `wire/envelope.py`'s log**, on ADR-0124
> §9's second limb; this decision asserts there is none at `54c6b72e` and states the test rather
> than the conclusion alone.

### 13. The bound, the elision, retention, deletion and export

> **Normative.** `core/types.py` gains **`MAX_GOAL_EVIDENCE`, a fixed constant valued 64**. It
> is not a `Settings` field, not a constructor knob and not a per-deployment value, on ADR-0213
> §4's and ADR-0086 §1's own rule: *"a knob that raises the ceiling is a knob that re-opens it."*
> A goal whose history would exceed it drops its **oldest** row on the write that would exceed it.

> **Normative.** **`EvidenceHistory.elided` carries how many rows this goal's history has
> dropped.** It is a count and never an identifier, it **never decreases**, and a write that
> drops *k* rows advances it by *k*. Silent truncation is not available, and ADR-0086 §4's reason
> is the reason here: *"A displaced citation that leaves no trace would make a belief report a
> narrower warrant than it has, which is a *false* answer to the one question the provenance
> display exists to answer."*

> **Normative.** **The elision drops by age and by nothing else** — not by standing, not by
> verdict, not by whether a row is referenced by an interpretation element, and not by any
> judgement of usefulness. A rule that kept `STANDING` rows preferentially would make the history
> a curated selection rather than a record, and the one thing an audit trail must not be is
> edited toward the answer.

**Why 64 and not a tuned figure, and it is a first declaration labelled as one.** ADR-0251 §5
declares a planner-call allowance of four per attempt, and ADR-0226 §2 admits at most one ask of
each kind per request, so an attempt reading as hard as the corpus permits records on the order
of twenty rows; 64 admits roughly three such attempts on one goal before anything is dropped, and
the drop is disclosed rather than silent, so a deployment that hits it **learns that it did**.
ADR-0249 §2's reasoning for its own 32 applies unchanged — the bound exists to stop a
long-running goal growing a row without limit, not to express a judgement about how much
evidence a goal should have. Nothing in this repository measures how many reads a real
investigation takes; §18's arms and the audit ADR-0251 §7 extends are what would turn the figure
into a measurement.

> **Normative.** **`PlanExport` gains `evidence: tuple[GoalEvidence, ...]`**, and its
> `schema_version` annotation is **edited** to the next literal rather than defaulted, exactly as
> ADR-0249 §11 edited it and ADR-0250 §9 books the same edit. ADR-0004 §6's export right is what
> obliges it: a goal's evidence is the user's data and an export that omitted it would be an
> incomplete one.

> **Normative — ADR-0014 §5's reference-closure rule is *not* extended to `evidence_row_id`,
> and this is a decision rather than an omission.** The closure — *"every `goal_id`/`plan_id`
> referenced by an included record resolves within the same export"* — holds for references that
> are guaranteed resolvable, which `attempt_id` (ADR-0249 §11) and `question_id` (ADR-0250 §9)
> are because neither attempts nor questions are elided. **Evidence rows are elided**, so
> extending the closure would make a long-running goal's export fail to validate for a reason the
> elision already discloses. `evidence_row_id` therefore joins `GoalElement.evidence_id`, which
> names a record of another store and has never been in the closure. **An export still carries
> every row the store holds for every goal it carries**, and `evidence`'s own `goal_id`s resolve
> within it on the existing rule.

> **Normative — the figures live in the tree and this decision names none of them as a rule.**
> **The plan store's `_SCHEMA_VERSION` moves by exactly one**, in the change that lands the
> evidence table, and **`PlanExport.schema_version`'s annotation moves by exactly one** in the
> change that adds `evidence`. ADR-0049 §1's durable `meta("schema_version")` marker is what the
> migration reads and its loud refusal of a database *"whose `schema_version` is **newer** than
> the code understands"* binds entire. Fixing an integer here would assert a fact about a tree
> that keeps moving, which is what `CONTRIBUTING.md` → "No state claims in living documents"
> refuses, and ADR-0249 §12 already took this posture in terms: *"the number is the tree's and
> not this decision's."*

**As a dated observation rather than a rule**: at `54c6b72e`, `_SCHEMA_VERSION` reads **2** and
`PlanExport.schema_version` reads **`Literal[8]`**, and **ADR-0250's implementation has not
landed**, so its questions migration and its own `PlanExport` edit are still ahead of this one.
Whether this lane's implementation makes 2 → 3 and 8 → 9 or 3 → 4 and 9 → 10 is therefore decided
by merge order and not by this document. That sentence is an observation of one commit, carries
its sha, and binds nothing.

> **Normative — the migration adds a table and converts nothing.** The upgrade is **table
> creation alone**, with the foreign key onto `goals` that ADR-0049 §1's schema discipline
> requires, created **empty** because no earlier store holds a row. **The migration writes no
> value this system did not record** — it invents no row, no instant, no applicability and no
> verdict — which is ADR-0249 §12's own clause for its own migration, and here it is satisfied
> trivially because there is nothing to convert.

> **Normative — what the table must decide, and what it must not.** Exactly three of the row's
> values are **columns** rather than blob members, because three contracted behaviours key on
> them: `goal_id`, which `evidence_of` and `delete_goal`'s cascade select on and which carries
> the foreign key; `read_at`, which decides `evidence_of`'s contractual order and §13's elision;
> and `standing`, which is §12's compare-and-swap token. The row itself is the blob, exactly as it
> is for `goals`, `plans`, `executions` and ADR-0249 §12's `attempts`. **No other value is
> promoted to a column**, and in particular no applicability axis is: a schema that indexed the
> label axes would be a second retrieval surface over the owner's records, which ADR-0208 §1 and
> ADR-0226 §13 govern and this decision does not open.

> **Normative — the elision count is durable and its storage is the implementing lane's.**
> `EvidenceHistory.elided` is a value the store holds per goal and returns; **it is not recomputed
> at read time, not derived from a row count, and not reset by a deletion of any row**. What shape
> the store keeps it in is not contracted — the contract is the value, its monotonicity and the
> fact that it advances in the **same indivisible step** as the write that drops the rows, so a
> reader can never see a shortened history without the count that explains it.

> **Normative.** **A row is first written at the one site ADR-0249 §11 names**, together with
> the goal, its revisions, the attempt and the turn's plans. ADR-0228 §5's prohibition binds
> entire — *"no lane adds a second persistence site, gives `LearningLoop` a `PlanStore`, or
> carries a plan out of a failing turn in order to write it"* — and ADR-0249 §11's consequence
> binds with it: **a turn that ends before that site writes no evidence row**, exactly as it
> writes no goal row, no attempt row and no plan row, and **no lane reorders persistence to write
> one sooner**.

### 14. The writer clauses

> **Normative.** **`orchestration` writes every value this decision adds, and no model writes
> any of them.** The row's `id`, `goal_id`, `attempt_id`, `basis`, `read_kind`, `source`,
> `requested`, `supported`, `read_at`, `as_of`, `records`, `minted`, `verdict`, `standing`,
> `inapplicable_at_revision` and `superseded_by`; the refresh set a `record_evidence` carries;
> the changed set an `invalidate_evidence` carries; and the `E`-label resolution and the
> `evidence_row_id` it stamps — each is written by the loop from the **injected clock**, the
> **injected id factory**, the **typed outcomes of a servicing** and the **values a store
> returned**. This is ADR-0249 §6's writer clause and ADR-0250 §16's applied to one more record.

> **Normative.** **What a model supplies toward evidence is exactly one thing**: on an
> `INTERPRETATION` row, one member of the closed enumeration its interpretation step declared,
> over one recorded record. **No model supplies an identifier, an instant, an applicability, a
> standing, a basis, a read kind, a source, a count or a verdict of a read**, and a planner
> envelope coming back carrying one has it **discarded silently** — not an error, not a park, not
> a degradation of the turn — which is ADR-0249 §6's posture and ADR-0228 §5's before it.

> **Normative.** **A model sentence is never evidence and never becomes a row.** No text a model
> wrote — a rationale, a summary, a restatement of what a read returned, a claim that something
> was checked — is composed into `requested`, into `supported`, into `verdict` or into any field
> of a row, and **no row is recorded on account of one**. ADR-0226 §1's record-not-payload rule
> is the ground, and ADR-0228 §11 is the sentence: a model completion *"with no recorded origin
> … is not of a better class than one composed over a narrower one, and no lane infers a
> placement for it, renders it to a channel a rationale is inadmissible to, or **treats it as
> evidence of anything**."*

**#2255's *"a model merely repeating an old fact is not a refresh"* is this clause and §8's limb
5 together.** A model that restates on turn 4 what a read established on turn 1 changes no row,
mints no row, and moves no `read_at`; the only thing that supersedes a row is another row, and
the only thing that makes a row is a servicing's typed outcome or an interpretation call's typed
verdict. That the restatement is *"of the same class as `ActionPlan.rationale`"* is the whole of
why it cannot do the work.

> **Normative.** **No interface adapter authors any of them either.** Golden rule 3 and ADR-0042
> §6 bind: an adapter renders what an outcome carries and derives, defaults, composes and
> synthesises nothing, which is ADR-0177 §1's *"the gateway derives none of them, defaults none
> of them, composes no operation out of two, and synthesises no result from a call it did not
> make"*.

> **Normative.** **No `Settings` field, deployment flag, environment value or per-request
> parameter is added by this decision**, and none of its figures, predicates or vocabularies is
> made configurable. ADR-0228 §3's non-configurability argument binds one level over, and the two
> fixed constants are fixed for ADR-0086 §1's stated reason.

### 15. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **The step's declared condition, its declared applicability, its declared recency requirement
  and its declared affirmative member.** **A5**, which ADR-0249 §13 already gives *"`ActionPlan`'s
  step fields — `depends_on`, engine-resolved result references, the `when` vocabulary and
  `verifies`"*. §6's four tests are stated over those declarations and this decision lands none of
  them. Fired by A5.
- **The derivation of §9's changed set from an interpretation revision.** **A5**, in the same
  lane and for the same reason: no type carries a typed applicability on a `GoalInterpretation` or
  a `GoalElement`, and until one does the changed set is empty (§9).
- **The interpretation step: its enumeration's members, its declared output schema, the call that
  produces a verdict, and which record is its whole input.** **A5** and **A7**. This decision
  fixes that an `INTERPRETATION` row exists, that its verdict is a member of a closed enumeration
  that always carries a does-not-settle member, and that such a row is over exactly one recorded
  record. Fired by the lane that adds an interpretation step.
- **The stage that dispatches a step, and what a failed sufficiency test then causes** — a
  replan, a typed refusal, a report, a step left `PENDING`. **A7** and **A9**.
- **Authorization coverage.** **A6**. A dispatch needs both, they are two tests, and nothing in
  this decision clears an authorization or is cleared by one.
- **Verification against the goal's criteria, and the producer of `GoalStatus.ACHIEVED`.**
  **A10**. ADR-0249 §4 fixes that this ADR supplies none, and §11 above adds that no field of a
  row reaches any status predicate.
- **A reader's evidence row.** Decision 8 of 2026-09-12 lands *"a useful real-information
  reader … alongside M32"*, and this decision designs no reader. **What an evidence row needs from
  a reader's typed outcome is named here and nothing more**: a `SourceReading.source` for §1's
  `source` field — the reader's declared identity, which ADR-0093 §10 already puts on every
  reading, and which is what makes §8's limb 3 finer than `read_kind`; an
  `Attestation.reported_at` for `as_of` where the source declares one; and, for `supported`, a
  `ReportedExtent` (ADR-0117 §2), which is *"the reporting source's own statement about the thing
  it reported"* and is the only authority this decision will accept for what a reader covered.
  **How a reader's read is asked for, serviced, budgeted or audited is that lane's**, and whether
  it is a `ReadKind` member at all is ADR-0226 §1's question and not this one.
- **A cross-turn carrier for `ReadOutcome`.** **ADR-0251 §14's deferral, untouched.** That
  section declines a durable home for a turn's typed outcomes and names this decision's rows as
  the reason to be careful — *"two widenings of one store inside one milestone, for two
  overlapping records of what a read returned, is the collision that decision warns about"*. **A
  `GoalEvidence` row is not that carrier and no lane reads it as one**: it records what a response
  **supported**, is written only where there is something to support, and is not one entry per ask
  the servicing reached.
- **A per-row retention rule of its own.** A row lives as long as its goal does (§13), and
  whether a goal's evidence should outlive or predecease the goal is a retention question ADR-0004
  §6 owns. Fired by a decision that gives goals a retention horizon.
- **A blocker vocabulary, and any producer of `GoalStatus.BLOCKED`.** ADR-0251 §9's, untouched:
  this decision supplies the sufficiency half of its limb 3 and no reason that passes all three.
- **Whether `ReadOutcome`'s name collision is resolved by renaming ADR-0185's enum or
  ADR-0251's model.** ADR-0251's implementing lane. Filed as an issue; nothing here depends on it.

### 16. Records owed on earlier ADRs, under ADR-0082 §1

**ADR-0249 §1 — partially superseded**, in the `GoalElement` clause alone, and the header records
it. The clause reads *"A `GoalElement` is a frozen model with `extra="forbid"` whose fields are
exactly `text` (`NonBlankEncodableText`), `ground` (a `Ground`), `evidence_id` (`Identifier |
None`) and `span` (`EncodableText | None`). A **model validator** refuses every shape but
three"*. Both halves stop being true: the field list gains `evidence_row_id`, and the validator
admits a fourth shape. A reader holding only ADR-0249 would conclude that a `FROM_EVIDENCE`
element can only name a record of the labelled supply — which is precisely the conclusion §13 of
that ADR defers here, and which §7 of it says in terms is not the route: *"The route A4 has is an
evidence row keyed on the goal; nothing here forecloses it."* **Everything else in §1 binds
entire**, and two clauses are worth naming because a reader might expect them to have moved and
they have not: `Ground` stays **closed at exactly three members** — this decision adds no fourth
and gives no member a second spelling — and `GoalInterpretation`'s field enumeration changes only
in the respect §1 itself makes derivative, by validating the outcome's arguments *"as a
`GoalElement`'s are"*.

**ADR-0249 §7 — partially superseded**, in the `FROM_EVIDENCE` resolution clause alone. The
clause reads *"A `FROM_EVIDENCE` element's `evidence_label` is resolved **by ADR-0226 §3's
labelling scheme, unchanged** — the label of the record at 1-based index *n* of the `memories`
sequence passed **on that call** — and the stamped `GoalElement.evidence_id` is the identifier of
the record the loop itself labelled."* It stops being the whole of the resolution once §10 above
adds the `E` space. **Everything else in §7 binds entire**, including the clauses this decision
depends on: that a label naming a search-minted record is dropped, that an element whose ground
does not resolve is dropped silently without failing the turn, that no record identifier is
rendered to the planner or accepted from it, the retention-by-label mechanism, the
outcome-retention clause, and the interpretation-is-the-model's-and-prerequisites-are-code's
asymmetry.

**ADR-0096 — relied on and not superseded, and this is the record that says so.** §2's two
instants are reused with their meanings and their prohibition (§4); §3's no-threshold,
no-flag, never-a-gate rules bind this decision entire. A reader might expect §3 to have moved,
because §6's fourth test does compare an instant against a figure — it has not: the figure is the
**step's**, evaluated at dispatch, and no row carries a verdict about its own age, no `Settings`
value defines one, and no row is withheld, dropped or downgraded for being old.

**ADR-0226 §3 — not superseded**, and the working: its clause that no lane *"substitutes another
spelling, adds a prefix per group, or makes it configurable"* is stated of **`memories`**' label
scheme, which is untouched — `M` followed by *n*, resolved against the sequence passed on that
call. ADR-0249 §9 added `C`, `S` and `D` for three other sequences and recorded no supersession;
§10 above adds `E` for a fourth on the same reading.

**ADR-0237 §7 — not superseded and is strengthened by being cited.** Its clause that *"No
consumer composes an assertion of absence from an empty or short structured result — not to the
owner, not into a record, and not into a plan"* reaches a new kind of record here and §5 states
that it does.

**ADR-0251 §9 — not superseded; its deferral is answered.** That section rules that a superseded
row blocks nothing and says *"Which rows are superseded is A4's"*; §8 above is that answer, and
nothing in this decision touches §9's three limbs, its writer, its write path or its refusal to
name a reason.

**ADR-0250 §9 and ADR-0249 §12 — not superseded; both are layered on.** Each widens `PlanStore`
and each states the next migration; this decision adds four members and one migration beside
them, changes no member either added, and takes ADR-0250 §9's `settle_question` shape as the
precedent for its own compare-and-swap (§12).

**ADR-0249 §11 — not superseded**, and the sentence a reader will check is *"It does **not** gain
evidence rows, because A4 mints them (§10)."* That is a statement about **that decision's**
change to `PlanExport`, with A4 named in the same breath as the minter; §13 above is the minting
it anticipates, not a contradiction of it.

### 17. The lane cut

> **Normative.** This ADR is ratified and merged as its own PR before anything implements
> against it (ADR-0015, golden rule 5), and its implementation is cut into **two** lanes.

- **I1 — the contract, the store and the migration.** `EvidenceBasis`,
  `EvidenceApplicability`, `GoalEvidence`, `EvidenceInvalidation`, `EvidenceHistory`,
  `MAX_GOAL_EVIDENCE`, `MAX_APPLICABILITY_VALUES`; `GoalElement.evidence_row_id` and
  `GoalInterpretation.outcome_evidence_row_id` with their validators; `GoalDeletion` and
  `PlanExport`; the four `PlanStore` members on both conforming implementations, in the shared
  conformance suite and on the canonical fake; and the plan store's migration.
- **I2 — the loop.** Composing `requested` and `supported` from a servicing's typed outcome,
  stamping the row at ADR-0249 §11's site, computing the refresh set and the changed set,
  projecting the digest, and resolving the `E` label space.

> **Normative — I1 depends on ADR-0251's L1.** §5 adopts `ReadOutcomeKind`, which that
> implementation lands, so I1 follows it rather than racing it. **No lane of this decision mints
> a second read-outcome vocabulary to avoid the dependency.**

> **Normative.** **Neither lane moves `PROTOCOL_VERSION`** (§12), and neither adds a `Settings`
> field, a deployment flag or a configurable figure (§14).

### 18. The arms this decision owes

> **Normative.** The implementing lanes pin at least the following, each stated as the behaviour
> and not as a spelling:

1. **Clarification changes the campsite but not the dates.** A row whose `supported` covers the
   coming week **survives** a revision that changes only the campsite; a row whose `supported`
   covers Saturday alone and a revision that moves the date to Sunday marks that row
   `INAPPLICABLE` with `inapplicable_at_revision` carrying that revision (§9).
2. **A row keyed on `requested` would have been discarded and is not.** A row whose `requested`
   names Saturday and whose `supported` covers the coming week survives a move to Sunday — the arm
   that separates the two applicabilities.
3. **Dates change and the evidence is rechecked before acting.** A step whose declared recency
   requirement the row no longer meets does not have its condition satisfied, while the row stays
   retained, exported and in the digest (§6).
4. **A forecast read that fails or is inconclusive satisfies nothing.** Each of `EMPTY`,
   `DUPLICATE`, `REFUSED`, `FAILED`, `EXPIRED` and a `TRUNCATED` admitting no record fails §6's
   second test, and an `INTERPRETATION` row carrying the does-not-settle member fails it too.
5. **An `EMPTY` read asserts no absence.** A row whose verdict is `EMPTY` carries `supported`
   absent and satisfies nothing, and nothing composes an assertion that the thing did not happen
   (ADR-0237 §7, §5 above).
6. **Conflicting evidence reports an obstacle.** Two `STANDING` `INTERPRETATION` rows over the
   same enumeration with overlapping `supported` and different verdicts leave the condition
   unsatisfied; two `READ_OUTCOME` rows over overlapping applicabilities **never** conflict (§7).
7. **A refresh supersedes and progress resumes.** A later affirmative row of the same basis,
   kind and source whose `supported` overlaps marks the earlier `SUPERSEDED` with
   `superseded_by` set, in one indivisible write; the remaining row stands alone and the condition
   is satisfied again (§8, §12).
8. **A failed refresh retires nothing.** A later row of the same basis, kind and source whose
   verdict is `FAILED`, `REFUSED`, `EXPIRED` or `EMPTY` supersedes no row, and the earlier row is
   still `STANDING` (§8 limb 5).
9. **A query naming Sunday whose response supports no period.** The row carries `requested` where
   the ask was a `STRUCTURED_READ` and `supported` **absent**, and satisfies nothing (§3).
10. **A model sentence never becomes a row.** A planner output restating what an earlier read
    established mints no row, moves no `read_at` and supersedes nothing (§14).
11. **A marking never un-marks.** A revision restoring an earlier value leaves an `INAPPLICABLE`
    row marked; deleting the row that superseded another does not return it to `STANDING` (§8, §9).
12. **An element grounded on a row survives the row's marking.** The revision is not rewritten,
    not re-grounded and not removed, and no revision is recorded on account of a mark (§10).
13. **An `E` label resolves against `evidence` and an `M` label against `memories`**; a label of
    neither form, an out-of-range ordinal, and an `E` label naming a row the store does not hold
    are each dropped silently (§10).
14. **The bound elides and discloses.** A goal whose history exceeds `MAX_GOAL_EVIDENCE` drops
    its oldest rows and `EvidenceHistory.elided` carries how many, never decreasing; an
    applicability exceeding `MAX_APPLICABILITY_VALUES` on an axis keeps the first 32 and advances
    its own `elided`.
15. **The migration runs on a database of the previous version**, creates the table empty,
    converts nothing, and refuses a database whose `schema_version` is newer (ADR-0049 §1).
16. **Export closure.** An export carries every row of every goal it carries, every row's
    `goal_id` resolves within it, and an element whose `evidence_row_id` names an elided row does
    **not** make the document invalid (§13).
17. **`delete_goal` cascades**, `GoalDeletion.evidence_removed` counts the rows, and a row of any
    standing blocks no deletion.
18. **The digest discloses no identifier**, carries every row including marked ones, and says
    nothing about sufficiency (§11).
19. **A `WEB_SEARCH` row names no record and counts them instead.** `records` is empty, `minted`
    carries how many the servicing minted, and no minted id reaches the row (§1, ADR-0231 §16).
    An `INTERPRETATION` row carries exactly one member of `records`, `minted` `0` and no
    `read_kind`; a row of any other `READ_OUTCOME` kind carries `minted` `0`.
20. **The row names the attempt that recorded it** on `attempt_id`, and is read back by
    `get_evidence` by `id` and in `evidence_of`'s `read_at` order (§1, §12).
21. **`as_of` is the source's instant or nothing.** A row over records carrying attestations
    takes the **earliest** `reported_at`; a row over the owner's own store-written records carries
    `as_of` absent; and no producer fills it from the clock, from `read_at` or from a filesystem
    stamp (§4, ADR-0096 §2).
22. **The outcome grounds on a row too.** A `GoalInterpretation` whose outcome is `FROM_EVIDENCE`
    carries exactly one of `outcome_evidence_id` and `outcome_evidence_row_id`, on the same
    validator shape as an element's (§10).
23. **The rendering is deterministic and prose-free.** One applicability renders to the same text
    twice, an unapplied axis is absent from it, an absent applicability renders as an absent digest
    member, and no model output reaches it (§11).

### 19. This ADR classified under ADR-0070 §1 and ADR-0082 §1

This is a **new decision with two narrow partial supersessions**, both of ADR-0249 and both
recorded on that ADR's header by this change. It supersedes nothing else in whole or in part;
§16 shows the working for every ADR a reader would expect to be. It is a **BREAKING** contract
change under golden rule 5 — `PlanStore` gains four members, `GoalElement` and
`GoalInterpretation` each gain a field and a validator shape, `GoalDeletion` gains a field, and
`PlanExport` gains a member and moves its version — and ADR-0249 §10 booked it as one in advance:
*"A4's widening of `PlanStore` is a second BREAKING contract change with its own ADR."*

## Consequences

**What becomes possible.** A goal holds a durable, typed record of what its investigation
established — separately from what it asked — so a later turn can tell *we asked about Sunday*
from *the answer describes Sunday*, and a step can be gated on the second. Refreshed evidence
displaces the evidence it refreshes, so a disagreement from three days ago stops blocking a goal
the moment somebody reads again. A search finding can ground an interpretation element for the
first time, through a row that resolves rather than through an id that never did.

**What becomes harder, and deliberately.** Nothing satisfies a condition by having completed: a
read that ran, returned, and was recorded still satisfies nothing unless its **response** covers
what the step needs. Four kinds of ask produce no `requested` at all, so the record of *what we
looked for* is thinner than an implementer's instinct would make it — which is the price of
keeping a model's composed query and a per-call label out of a durable row. And two of the most
natural adjudications are unavailable: no rule picks a winner between two standing readings, and
no read outcome is ever read as evidence of absence.

**What this costs the corpus.** A third widening of `PlanStore` inside one milestone, after
ADR-0249 §12's and ADR-0250 §9's, and a third migration of the same store — each conforming
implementation, the shared conformance suite and the canonical fake take all three. The store is
becoming large, which is a consequence worth watching rather than a defect this decision can fix:
the alternative was a second store for evidence, rejected below.

**What would trigger revisiting this.** A measurement that `MAX_GOAL_EVIDENCE` elides on real
goals, which the disclosed count makes visible. A reader whose typed outcome cannot fill
`source`, `as_of` or `supported` as §15 specifies. A verdict vocabulary that genuinely has no
affirmative member. And a conflict between two `READ_OUTCOME` rows that a lane can show is real
without inspecting a record's text — which §7 argues is unreachable, and which if reached would
reopen it.

## Alternatives considered

**One `applicability` field instead of two.** This is revision 0 of the report's shape and it is
what the owner's addendum corrects. With one field, the value would be filled from whichever of
the ask or the response was to hand, and the first implementation to fill it from the ask would
be indistinguishable from one that filled it from the response. Two fields written from two
objects at two moments make the confusion unreachable rather than forbidden.

**A staleness field, a freshness class, or an expiry on the row.** Refused by ADR-0096 §3 and by
the absence of any figure to put in one. It would also put the decision in the wrong place: the
question is never *is this forecast stale* but *does this booking step accept evidence read this
long ago*, and only the step knows.

**A recency tie-break for conflicting evidence.** Rejected because it would let a later, weaker
reading overturn an earlier, stronger one on no ground but its timestamp. §8's supersession is
the narrow case where recency does decide, and it is bought by five limbs — same basis, same
kind, same source, overlapping support, affirmative verdict — every one of which the bare
tie-break would skip.

**A confidence or source-preference ranking.** Rejected on ADR-0098 §6, which forbids stating a
bound obtained from a detector, and on ADR-0146 §2's recorded-never-inferred rule. A ranking is a
judgement about content, made by the class of system an adversary is already steering.

**A fourth `Ground` member for an evidence row.** Rejected. `Ground` is *"closed at exactly three
members"* (ADR-0249 §1) and a fourth would change every exhaustive match over it, oblige the
planner to choose an id space it cannot know, and disclose the id space on the brief's
`BriefElement.ground` for no consumer's benefit. The label prefix puts the choice where the
knowledge is — the planner knows which sequence it read the label off — and leaves the
enumeration closed.

**A second store for evidence, or a `MemoryStore` write.** Rejected twice over. Evidence is
planning state keyed on a goal, and ADR-0014 §5's store is where planning state keyed on a goal
lives; a second store would need its own migration, export, deletion cascade and conformance
suite for one record type. Writing rows to `MemoryStore` is refused by ADR-0231 §16 for a search
(*"No minted record is ingested, proposed, folded, superseded or written to the `MemoryStore`"*)
and by ADR-0093 §1 for everything else — a row is not a belief and proposing one would put an
unattested claim into the user's memory.

**Letting the store evaluate the refresh predicate.** Rejected: it would be a second place the
rule lives, and two conforming implementations could disagree about which rows a write displaced
with no test in either package catching it. The loop computes the set; the store applies it
atomically.

**Applying the marks in a second write after recording the row.** Rejected: it leaves a window in
which a row and its refresher both stand, which for correction 1 is the exact failure being
fixed.

**Keeping `STANDING` rows preferentially when the bound elides.** Rejected: it would make the
history a curated selection rather than a record. Age is the only criterion a bound may use
without editing the audit toward the answer.
