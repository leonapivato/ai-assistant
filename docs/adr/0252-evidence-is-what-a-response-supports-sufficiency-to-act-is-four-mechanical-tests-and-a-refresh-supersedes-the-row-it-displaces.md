# 252. Evidence is what a response supports, sufficiency to act is four mechanical tests, and a refresh supersedes the row it displaces

- Status: Partially superseded by ADR-0253 (§14's writer clause, in **one term on one basis**: its enumeration of what *"no model supplies"* stops being true of **`applicability`** on the **`INTERPRETATION`** basis, because §3's second source composes such a row's `supported` from *"the one region the interpretation step **declared**"* and only a plan can declare one — a tension between two clauses of this decision, which ADR-0253 §7 resolves in favour of the specific rule. Every other term of §14 binds entire on both bases — no model supplies an identifier, an instant, a standing, a basis, a read kind, a source, a declaration, a count or a verdict of a read — and §14's *"exactly one thing"* is still the whole of what a model supplies at the interpretation call itself. Nothing else in this ADR: §1's row shape and its four-axis validator, §2's applicability algebra and its three relations, §3's two composition sources and its prohibition list, §4's two instants, §5's verdict vocabularies and the affirmative partition, §6's four mechanical tests, §7's conflict rules, §8's six refresh limbs, §9's invalidation predicate, §§10-13 and §§15-19 all stand entire)
- **Partially supersedes [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md),
  in three narrowly stated scopes**, and §16 shows the working for all three.
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
  **§12's `GoalRevision` clause** — *"`core/types.py` gains **`GoalRevision`**, a frozen command
  carrying `goal_id`, the `GoalInterpretation`, and the `expected_version` it was computed
  against"*, together with `record_interpretation`'s stated effect — gains `invalidates`, a
  possibly-empty `tuple[Identifier, ...]` the member applies in the same indivisible step as the
  append, because §9 below requires an invalidation to be atomic with the revision that occasions
  it and a second store call cannot be. §12's every other clause binds **verbatim**, including
  `save_goal` as the opening write alone, the attempt members, the compare-and-swap discipline
  and its error class, the commands-not-snapshots rule, the `delete_goal` cascade, the
  no-new-Protocol rule and the rule that `PlanExport` is not a second wire ground.
- **No other ADR is superseded in whole or in part**, and §16 shows the working for each one a
  reader would expect to be — ADR-0045, ADR-0096, ADR-0213, ADR-0226, ADR-0228, ADR-0230,
  ADR-0237, ADR-0240, ADR-0250 and ADR-0251 among them. **ADR-0096 is relied on and not superseded**, which is the one a reader
  should check first: its two instants and its never-a-gate rule are what make sufficiency a
  separate question rather than a freshness verdict on the evidence.
- Date: 2026-09-12
- **Note (2026-09-12): every clause this decision pushed onto A5 is discharged by
  [ADR-0253](0253-the-plan-declares-what-a-step-waits-on-what-fills-its-arguments-and-what-must-be-evidenced-before-it-is-dispatched.md),
  and nothing of this ADR is superseded.** §6's push — *"A step's condition declares a required
  `basis`, and on the `INTERPRETATION` basis a `declaration` and the member of its enumeration the
  condition requires"* — is `StepCondition` (ADR-0253 §5), whose `basis` is **required by the
  type** so a condition declaring none is not constructible rather than read as a default, and
  whose `about` names a condition element of the goal's interpretation. §6's open question is
  answered: a condition **may** require a `read_kind` and **may not** require a `source`, because
  §1 rules `source` *"absent on every row this decision's producers write"* and a requirement no
  row could meet is a step that can never dispatch. §6's recency clause — *"The figure lives on
  the step, A5 lands the field"* — is `PlanStep.evidence_recency`, a `timedelta | None`, and a
  step declaring none imposes none. §9's operand — *"What a revision **requires**, and therefore
  §9's two operands"* — is `GoalElement.applicability`, so this ADR's *"until A5 lands,
  `GoalRevision.invalidates` is empty on every revision"* ends; ADR-0253 §7 carries §9's own
  safety obligation forward in terms, that no lane lands the plan-driving stage on a tree where
  that tuple is still empty by construction. §1's *"What form the identifier takes is A5's"* is
  answered with the **`GoalElement.id`**, which is durable, resolves through the plan store,
  survives every revision that retains the element, and gives one plan's two interpretations two
  declarations — where a step id would satisfy §1's parenthetical and fail §8 limb 3, since a
  re-plan mints new ids. §5's *"Which enumeration it is, what its members are called"* is
  `InterpretationVerdict`, closed at `QUALIFIES`, `DOES_NOT_QUALIFY` and `INCONCLUSIVE`, with the
  third as the does-not-settle member and all three disjoint from `ReadOutcomeKind`'s seven; there
  is **one** enumeration over many propositions, which is §7's own reading. §15's interpretation
  entry is discharged: the call's whole input is one recorded record and one element's text, its
  declared output schema is one member and nothing else, and it is **not** a `PlanStep` —
  ADR-0226 §4's reasoning applied, so nothing about it reaches `ExecutionState` or the permission
  gate. **§14's writer clause is partially superseded in one term and on one basis**, which the
  `Status` line above records: a `StepCondition`'s declarations are never copied into a row at all,
  but an element's `applicability` **is** the region §3's second source requires an
  `INTERPRETATION` row to carry, so §14's `applicability` term cannot bind on that basis. Every
  other term of §14, and everything else of this ADR, binds entire. Refs #2255, ADR-0253 §7,
  ADR-0253 §13.

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
> `declaration`, an `Identifier | None`; `requested`, an `EvidenceApplicability | None`;
> `supported`, a possibly-empty `tuple[EvidenceApplicability, ...]`; `supported_elided`, an
> `int` `ge=0`; `read_at`, a `UtcInstant`; `as_of`, a `UtcInstant | None`; `records`, a
> possibly-empty `tuple[Identifier, ...]`; `returned`, an `int` `ge=0`; `admitted`, an `int`
> `ge=0`; `verdict`, an `EncodableText`; `standing`, an `EvidenceStanding`;
> `inapplicable_at_revision`, an `int | None` `ge=1`; and `superseded_by`, an
> `Identifier | None`.

> **Normative.** `core/types.py` gains **`EvidenceBasis`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly two members**: `READ_OUTCOME` and `INTERPRETATION`. The
> vocabulary is added to and never renamed, on `Ground`'s own rule (ADR-0249 §1, itself
> ADR-0226 §4's). It names **which of §3's two admitted sources** the row's `supported` was
> composed from, and therefore **which closed vocabulary `verdict` is a value of** (§5).

> **Normative — a model validator refuses every shape but the ones below, and there are four
> axes to it.**
>
> - **By basis.** A `READ_OUTCOME` row carries a `read_kind` and no `declaration`. An
>   `INTERPRETATION` row carries **no** `read_kind`, a **required** `declaration`, **exactly
>   one** member of `records`, and `returned` and `admitted` both `0` — the interpretation
>   call's whole input is one recorded record, it reads no source and admits nothing, and a
>   verdict over two records is not one this decision admits.
> - **By kind — durable kinds name, ephemeral kinds count.** On a `READ_OUTCOME` row whose
>   `read_kind` is `SIGHTED_QUERY`, `STRUCTURED_READ` or `CITATION_HOP`, `len(records)`
>   **equals** `returned`, or equals `MAX_EVIDENCE_RECORDS` where `returned` exceeds it. On one
>   whose `read_kind` is `WEB_SEARCH` or `LOCAL_FILE`, `records` is **empty** and the count
>   stands alone.
> - **By count.** `admitted <= returned` on every row. **No inequality is stated over
>   `len(records)`**, because the two clauses above already fix it exactly: an inequality read
>   over *every* row would demand `1 <= 0` of an `INTERPRETATION` row, whose basis rule gives it
>   one member of `records` beside `returned == 0`, and would make that basis unconstructible.
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

> **Normative — `returned` and `admitted` are ADR-0226 §9's own counts made durable, and
> *no test of this decision reads either*.** `returned` is how many records the ask handed
> back **before** ADR-0226 §7's deduplication; `admitted` is how many of those the supply did
> **not** already hold, which is that section's `new`. **Both are persisted rather than
> recomputed**, because the supply they were counted over is ephemeral — ADR-0052 §3's
> *"context and retrieved memories are ephemeral and were never persisted"* — so a consumer on a
> later turn cannot reconstruct either, and a row that carried neither would be a record of a
> servicing that could not say how much came back or how much of it was new.

> **Normative — sufficiency never reads a count, and this is stated as a prohibition so a
> later lane cannot read one back in.** §6's four tests read the row's `supported`, its
> `basis`, its `declaration`, its `verdict`, its `standing` and its two instants, and **read
> neither `returned` nor `admitted`**; §8's refresh limbs read neither; §9's invalidation
> predicate reads neither. **Whether a source answered in a way that supports a proposition is
> not whether a turn learned something new.** The second question is ADR-0251 §7's progress
> fold — *"a round is productive where *any* ask of it admitted at least one record the supply
> did not already hold, counted after ADR-0226 §7's deduplication"* — which is that decision's,
> is evaluated over the turn's own servicings, and stays there. The counts are on the row so
> that the fold's inputs survive the turn for an audit and an export; **which consumer reads
> them across turns is not settled here** (§15).

**Round 2 found the collapse and the separation is the correction.** An earlier draft keyed
the affirmative test on `admitted >= 1`, which made a read whose every record deduplicated out
satisfy nothing — and a new goal whose one relevant record initial retrieval had already put in
the supply could then never obtain sufficient evidence at all, because every servicing returning
it is `DUPLICATE` with `admitted == 0` and retrieval mints no row to have been duplicated
against. Keying on `returned >= 1` instead would have moved the same defect rather than removed
it: a count of records is a fact about the **supply** and sufficiency is a question about the
**response**. §5 therefore states the affirmative test over the closed vocabulary alone.

> **Normative.** **`records` holds identifiers that resolve in the owner's `MemoryStore`, and
> holds nothing else.** A record ADR-0231 §1's search minted is **never** named there: ADR-0231
> §16 rules that such a record *"is not a citation target and not a durable reference … its `id`
> is minted for one turn … and resolves in no store"*. **A record ADR-0230 §5's fetch minted is
> never named there either**, on that decision's own sentence about it: §10 rules that a fetched
> record *"is not a citation target and not a durable reference. Its `id` is minted for one turn,
> is rendered to no model, is accepted from none and resolves in no store"*. A durable row naming
> either would state a warrant it cannot show — which is the refusal ADR-0249 §7 already takes
> against the first and ADR-0249 §12's migration takes against a `FROM_EVIDENCE` ground it cannot
> substantiate.

> **Normative — so the two ephemeral kinds count and the three durable kinds name, and the
> split is by where the record lives and not by which ADR minted it.** `WEB_SEARCH` and
> `LOCAL_FILE` each mint a record for one turn that resolves in no store, so their rows carry
> `records` **empty** and `returned` alone. `SIGHTED_QUERY`, `CITATION_HOP` and `STRUCTURED_READ`
> each read the owner's own `MemoryStore` — the first as a relevance selection, the second as
> ADR-0208 §1's *"records the turn already names, fetched by identifier"*, the third through
> ADR-0240 §1's structured filter — so every record they return is store-resident and is named.
> **Where the count stands, it stands as ADR-0086 §4's shape for its own reason** — *"It is a
> count and never an id"* — reached here because the ids would not resolve rather than because
> they are the payload.

**Round 2 found this by the arithmetic and the correction is the kind rule rather than the
contract.** A successful `LOCAL_FILE` fetch returns one record, so a rule demanding
`len(records) == returned` on *"every other `READ_OUTCOME` row"* demanded one identifier that
ADR-0230 §10 says resolves nowhere, while the same section's resolvability rule forbade carrying
it — a shape no implementation could construct either way. Bending the resolvability rule was
available and is refused: **where a read kind cannot satisfy the reference contract, the kind is
excluded from it by a stated rule**, which leaves the contract saying exactly what it said and
puts the exception where a reader will find it.

> **Normative — `records` is bounded, and the disclosure is already on the row.**
> `core/types.py` gains **`MAX_EVIDENCE_RECORDS`, a fixed constant valued 32**, on the same
> footing as §2's two: not a `Settings` field, not a constructor knob and not a per-deployment
> value. A row whose ask returned more keeps the **first 32** identifiers in the order the
> servicing produced them, and **`returned` continues to carry the true count** — so the
> truncation needs no second counter, because the figure that discloses it is the field beside
> it. ADR-0226 §6's budget of ten is counted **after** ADR-0226 §7's deduplication, so it bounds
> `admitted` and not `returned`, and a durable sequence in `core` left to be bounded by a
> producer's arithmetic is exactly what ADR-0086 §1 refuses.

> **Normative.** **`source` is the reading's own declared identity where the servicing has
> one, and is absent on every row this decision's producers write.** No producer of this
> decision fills it: the five `ReadKind` members each name their own source (§8), and the one
> shape that would carry a finer identity is a `Reader`'s `SourceReading.source`, whose producer
> is decision 8's reader and is not built here. **No lane fills it with a provider name, a host,
> an address, a path, a `Settings` field name or a credential identity** — ADR-0231 §13's bar,
> which ADR-0242 §9 states of `SearchNotServiced` and ADR-0226 §9 states of the audit, binds
> this field for the same reason: a durable row is a worse place for one of those than a log is.

> **Normative — `declaration` names the interpretation step's declaration and resolves within
> the plan store.** It is **required on an `INTERPRETATION` row and absent on every other**, it
> is durable, it is stable across turns, and it is what §7 and §8 compare so that two
> interpretation steps examining the same record about **different propositions** are never
> mistaken for one another. **It is never a `MemoryStore` identifier and never a minted one.**
> **What form the identifier takes is A5's** (§15) — a plan id alone does not suffice, because
> one plan may declare two interpretation steps — and no lane of this decision produces a row of
> this basis (§14).

> **Normative.** **A `GoalEvidence` carries no content.** It carries no record text, no snippet,
> no title, no excerpt, no query, no label, no rendered result and no prose of any kind. What it
> carries of the world is exactly the applicabilities of §2, whose values are instants and the
> label vocabularies ADR-0237 and ADR-0213 already fix, and the two instants of §4. ADR-0226
> §1's record-not-payload rule is the ground — *"What a serviced request returns into the supply
> is `MemoryRecord`s carrying their own `Provenance`, and never a payload, a rendering, a
> summary or free text of any kind"* — read one level down, at the durable record **about** a
> servicing rather than at the servicing's yield.

**A row is provenance and never a second copy of what was read.** ADR-0052 §3 makes each turn's
supply ephemeral; a row that carried the records' text would be a durable copy of Tier 1
content, written at a second site, retained on a second rule and exported by a second document —
every one of which is a thing the corpus decides elsewhere and none of which this decision is
entitled to re-decide. The records are named by id where they are durable, counted where they
are not, and read back through the store that holds them.

### 2. `EvidenceApplicability`, and the three relations stated over it

> **Normative.** `core/types.py` gains **`EvidenceApplicability`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `window`, a `TimeWindow | None`; `participants`, a
> `tuple[NonBlankEncodableText, ...] | None`; `topics`, a `tuple[TopicLabel, ...] | None`;
> `about_person`, a `tuple[NonBlankEncodableText, ...] | None`; and `elided`, an `int` `ge=0`
> defaulting to `0`.

> **Normative.** A **model validator** refuses an applicability applying **no** axis and one
> whose present sequence axis is **empty**. `None` is the one spelling of *not applied*, exactly
> as it is on `StructuredAsk` (ADR-0240 §2), and a value applying nothing is expressed by the
> field holding it being **absent** — or, for `supported`, by the tuple being **empty**.

> **Normative.** `TimeWindow` is used exactly as ADR-0237 §2 defines it and is not
> re-expressed: the half-open `[start, end)` reading, the unset ends, **the refusal of a window
> with both ends unset** and the refusal of one whose `end` is not strictly after its `start` are
> that ADR's and are inherited whole. No second window type is minted, no applicability carries
> two windows, and none carries a sequence of them.

> **Normative — one applicability is one *region*, and a `supported` is a tuple of them.** Each
> region is composed from **exactly one** returned record (§3), so a region's axes are values
> that record carried **together**. **No lane merges two regions**, unions their label axes,
> spans their windows, or replaces a tuple by its enclosing interval.

**Regions rather than one aggregate, and the two failures an aggregate has are both
manufactured coverage.** Two records declaring `[09:00, 10:00)` and `[15:00, 16:00)` have an
enclosing window of `[09:00, 16:00)`, and a condition about noon would then pass a coverage test
neither record supports — a gap invented by the representation. And unioning the label axes
across records loses which participant was in which interval, so a row composed from *Alice on
Saturday* and *Bob on Sunday* would cover a condition naming *Alice on Sunday*. Both are the
same defect: an aggregate asserts the **conjunction** of what several records said, where the
records only ever said their own parts. A region per record asserts exactly what one record
carried.

> **Normative — coverage, stated once and used by §6, §8 and §9.** An applicability `A`
> **covers** an applicability `B` when, **for every axis of `B` that `B` applies**, `A` applies
> that axis and `A`'s value contains `B`'s: for `window`, by ADR-0117 §3's containment predicate
> with **`B`'s window as that predicate's contained extent `E` and `A`'s as its containing
> coverage `C`**; for each label axis, `A`'s values are a superset of `B`'s under §6's
> **per-axis** comparison. **An axis `A` does not apply covers no applied axis of `B`**, and an
> axis `B` does not apply is covered by anything. The direction is stated rather than left to a
> reader, because the predicate is not symmetric and the two readings differ on every unbounded
> end.
>
> A **tuple** `S` covers an applicability `B` when **some region of `S` covers `B`**. A tuple
> `S` covers a tuple `T` when **every region of `T` is covered by some region of `S`**, and an
> **empty** `T` is covered by nothing — an empty `supported` supports nothing (§3).

**The containment predicate is ADR-0117 §3's, reused rather than restated, and the reuse is the
point.** That section states it as *"`E = [ef, eu)` lies wholly within `C = [cf, cu)` iff **`cf`
is `None` or (`ef` is not `None` and `ef >= cf`)** and **`cu` is `None` or (`eu` is not `None`
and `eu <= cu`)**"*, together with the sentence that decides the hard case: *"An unbounded
extent end is contained only by an unbounded coverage end on the same side."* That is the same
question this decision asks — *does what the source covered contain what we need?* — and a
second statement of it is a second place for the unbounded case to be got wrong.

> **Normative — an axis `A` does not apply covers no applied axis of `B`, and the direction is
> not negotiable.** An unapplied axis means *this applicability says nothing about that axis*,
> and a value that says nothing about the people a step names has not established anything about
> them. Reading an absent axis as *everything* would be the same substitution ADR-0240 §2
> refuses at the ask — *"no value of any axis means 'everything'"* — arriving at the response
> instead.

> **Normative — overlap, stated once and used by §7 alone.** Two applicabilities **overlap**
> when they apply **at least one axis in common** and, **for every axis both apply**, their
> values intersect: windows that share at least one instant, and label sets with at least one
> member in common under §6's **per-axis** comparison. An axis only one of them applies is
> ignored. Two tuples overlap when **some region of one overlaps some region of the other**.

**Overlap requires agreement on every shared axis, and that is what keeps a shared label from
bypassing a disjoint period.** A row about *Saturday, weather* and a row about *Sunday, weather*
share the `topics` axis and both apply `window`; their windows are disjoint, so they do not
overlap and neither is about the other's ground. Defining overlap as *there exists something
both cover* would make them overlap through a topics-only value that omits the window, which is
the reading §6's own *an unapplied axis of `B` is covered by anything* invites and which this
clause closes. **Overlap is used for conflict and never for supersession** — §8 requires the
stronger relation for the stronger act.

> **Normative.** **The axes take the types of the fields they copy, and tighten only in ways
> that reject.** `participants` and `about_person` are `NonBlankEncodableText`, which is
> `StructuredAsk`'s own annotation for the first (ADR-0240 §2) and is a tightening of
> `EpisodicMemory.participants`' `EncodableText`; `topics` is `TopicLabel`, which both the ask
> and `MemoryRecord.topics` already carry. **A blank value on a returned record contributes
> nothing to its region and advances that region's `elided`** — it is dropped, never stripped,
> never case-folded and never repaired. ADR-0096 §2's rule is the ground and its words are the
> reason: *"a faithful copy takes the type of the field it copies, and may tighten only in ways
> that reject … Tightening by *normalising* is how two spellings of one value drift."*

> **Normative — two bounds, both fixed `core` constants and neither a `Settings` field.**
> **`MAX_APPLICABILITY_VALUES`, valued 32**, bounds each label axis of one region: a composition
> that would exceed it keeps the first 32 values in the order the source produced them and
> advances that region's `elided`. **`MAX_SUPPORTED_REGIONS`, valued 32**, bounds a row's
> `supported`: a composition that would exceed it keeps the first 32 regions in the order the
> servicing produced them and advances the row's `supported_elided`. Neither is a constructor
> knob or a per-deployment value, on ADR-0213 §4's and ADR-0086 §1's rule — *"a knob that raises
> the ceiling is a knob that re-opens it."*

> **Normative — every truncation narrows and none widens, and the direction is why they are
> admissible at all.** A dropped value and a dropped region each make `supported` cover
> **less** and therefore satisfy **fewer** conditions (§6) and supersede **fewer** rows (§8), so
> every truncation fails closed. ADR-0086 §4's refusal of silent truncation binds entire and the
> two counts are what discharge it — *"A displaced citation that leaves no trace would make a
> belief report a narrower warrant than it has"* — and each count sits on the value it describes
> so that no consumer can hold one without the other.

### 3. `requested` and `supported`: what each is composed from, and the prohibition list

> **Normative.** **`requested` is composed by `orchestration` from the *typed* part of the ask
> and from nothing else, and is absent where the ask has no typed part.** Per `ReadKind`, at the
> vocabulary ADR-0226 §2, ADR-0230 §1, ADR-0231 §1 and ADR-0240 §1 leave closed:
>
> - **`STRUCTURED_READ`** — present, composed from the `StructuredAsk`'s four axes, each carried
>   across **byte for byte** into the corresponding axis of one region. An ask carrying a `query`
>   beside its structure contributes the structure alone.
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

> **Normative.** **`supported` is composed from exactly two sources and from nothing else, one
> region per record and never one region per ask.**
>
> 1. **A typed read outcome that carries the applicability structurally** — one region per
>    record the ask **returned**, composed from that record's own values and never from the ask.
>    Per record: `participants` from an `EpisodicMemory`'s `participants`; `topics` from
>    `MemoryRecord.topics`; `about_person` from `MemoryRecord.about_person`, which is one value
>    and reaches the axis as a one-member tuple; and `window` by the rule below. A record
>    carrying **no** applied axis contributes **no region**.
> 2. **An interpretation verdict over exactly one recorded record** — the one region the
>    interpretation step declared, over the one record its whole input was.
>
> **A row whose response establishes no applicability carries `supported` empty**, and ADR-0249
> §10's sentence binds entire: **an absent `supported` supports nothing.**

> **Normative — the window axis is applied where the record's `Provenance.attestation`
> carries a **`ReportedExtent`** (ADR-0117 §2), and **nowhere else**.** That extent is the
> declared interval, because ADR-0117 §2 makes it *"the reporting source's own statement about
> the thing it reported"* and this decision has no better authority for what a source covered.
> Where the record carries no attestation, or an attestation whose `extent` is `None`, the axis
> is **not applied**.
>
> Where the declared interval **cannot be expressed as a `TimeWindow`** — both ends unset, or
> ends that are not strictly ordered — the axis is **not applied** and the region's `elided`
> advances by one. **No lane substitutes a bound the source did not state**, invents an end,
> clamps one to a retention horizon, or widens a window to make one constructible.

> **Normative — a record's `Validity` is never read as a declared interval, and this is stated
> as a prohibition because it is the substitution a reader most wants to make.** Neither
> `valid_from` nor `valid_until` contributes to any region's `window`, on any kind, under any
> fallback, and **no lane reinstates one**.

**A `Validity` is our window on a belief we hold; a `ReportedExtent` is the source's claim about
what it reported. Reading the first as the second is the whole of the error.** ADR-0045 §2 puts
the window on the envelope for exactly that reason and says so in terms: it *"is a lifecycle
property of *the record's life in the store*, set operationally by the applier"*, sitting beside
`expires_at` because both are *"read-time lifecycle filters the store enforces"*, and
*"`Provenance` stays about *trust and source*"*. ADR-0117 §2 then refuses to name coverage with
it for the same reason — *"the two say different things about different subjects"* — and spells
out the three subjects that must not be conflated: *"a `Validity` is our window on a belief we
hold, a `ReadCoverage` is a claim about the read we performed, and an extent is the source's
claim about where the reported entry lies."*

**What the fallback would have done is the failure stated concretely.** A weather record written
on Saturday with `valid_from` set to that instant and no `ReportedExtent` declares an interval
running from Saturday with no end — an operational statement that the belief is live until
something retires it. Read as coverage, it would have supported **every later date**, Sunday
included, off a persistence timestamp no source ever said anything with; an affirmative read
would then have passed Sunday's coverage test on the strength of when we happened to store the
record. That is the manufactured coverage §2's regions argument refuses, arriving through a field
instead of through an aggregate.

**And the honest consequence is stated rather than softened: almost no row this decision's
producers write applies a window at all.** As a dated observation at `origin/main` `54c6b72e`,
`readers/calendar.py` is the only site in the tree that constructs a `ReportedExtent`; every
other producer passes `extent=None`, and both minting producers of §1's ephemeral kinds pass it
explicitly. So the window axis is applied on rows over store-resident records that came from a
calendar reading, and on nothing else until decision 8's reader lands (§15). A window nobody can
apply is a narrower system than an implementer expects and is the true one: the alternative was a
window everybody can apply, meaning nothing.

**A record's `occurred_at` is not a declaration of coverage, and this is the clause a reader
will most want the reason for.** An episode's `occurred_at` is an **instant**, `TimeWindow` is
an interval that *"states at least one end"* and refuses one whose `end` is not strictly after
its `start`, and this corpus has no point type to widen it to. Manufacturing `[t, t + ε)` would
invent a bound, and treating `t` as covering a period would be exactly the assertion ADR-0237 §7
forbids: an episodic read certifies about *"records carrying the values the call named"* and
*"is never a statement about what did or did not happen"* in a period. So an episodic read
supports what its episodes were **about** and **whom** they involved, and supports no period at
all — which is narrower than an implementer's instinct and is what the response actually
established.

**And an unbounded extent is declined rather than carried, which is the fail-closed direction.**
A `ReportedExtent` with both ends unset is the most permissive claim a source can make, and an
applicability has no spelling for it — `TimeWindow` refuses both-ends-unset by construction
(ADR-0237 §2). Declining the axis makes the region cover **no** applied window, where carrying
it as unbounded would make it cover **every** one. ADR-0117 §3's own sentence points the same
way: *"An unbounded extent end is contained only by an unbounded coverage end on the same
side"*, and there is no such coverage here to be the contained side of.

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

> **Normative.** **A `WEB_SEARCH` row's and a `LOCAL_FILE` row's `supported` is composed from
> the minted records' own values by the same rule as every other row's, and from nothing else** —
> and no lane infers an axis from the query, from the response's ordering, from a result's title,
> from a file's name or path, from its mtime, or from the provider's identity. ADR-0231 §1 puts
> the namer with the user and leaves the response carrying no structural axis at all; what such a
> response does carry is its declared instant, which is `as_of` (§4) and not an applicability.

**As a dated observation at `54c6b72e`, that composition is empty on both kinds, and saying so
is more useful than a hedge.** ADR-0231 §16's minted search record carries *"`topics` is empty,
`about_person` is `None`"* and *"`extent` is `None`"*; ADR-0230 §5's minted fetch record carries
the same three, word for word, and a `validity` that is *"fully open"* and which §3 above reads
as nothing. A record carrying no applied axis contributes **no region**, so today **every
`WEB_SEARCH` and every `LOCAL_FILE` row carries `supported` empty**, fails §6's first test, and
satisfies no condition. Such a row is not useless: it records durably that the source was asked
and what became of the ask, which is what §7's incompleteness clause and #2255's audit question
need. What it is not is evidence that anything is so — and an earlier draft's *"unless a minted
record declares an extent"* named a route neither minting clause can reach, which reads as a
capability the corpus does not have. What would change it is decision 8's reader (§15).

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

> **Normative.** Per kind, `as_of` is taken from: a **`WEB_SEARCH`** row, the response's
> declared instant, which ADR-0231 §16 already names — *"mints records whose `reported_at` is
> that response's declared instant"*; a row over records carrying an `Attestation`, that
> attestation's `reported_at` (ADR-0092 §3), taken as the **earliest** where the row's records
> carry several; and **absent everywhere else**, including on every row whose records are the
> owner's own store-written beliefs and episodes, which declare no reading-level instant.

> **Normative — a `LOCAL_FILE` row carries `as_of` absent, and that is an exception stated
> rather than an oversight.** ADR-0230 §5 sets a fetched record's `Attestation.reported_at` to
> *"the **instant the file was read**"*, so the generic rule above would fill `as_of` with the
> value `read_at` already carries. The two are the same event on that producer's own argument —
> *"a source this system interrogates **directly**, whose answer is produced at the instant of
> the read rather than replayed"*, so *"'when the source said so' and 'when we read it' are one
> event rather than two facts of which one stands in for the other"* — and a row carrying it
> twice would be indistinguishable, on inspection, from one that filled `as_of` **from**
> `read_at`, which ADR-0096 §2 forbids by name everywhere else. §6's fourth test reads `as_of`
> where present and `read_at` otherwise, so nothing is lost by the absence: the instant the test
> evaluates is the same instant either way.

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
> the value of a member of a **closed** enumeration the row's `declaration` names, whose members
> that step's own decision fixes, and which **always** carries a member meaning *the record does
> not settle it*. **A row whose verdict is that member satisfies nothing** (§6). Which
> enumeration it is, what its members are called, and which of them a given condition requires
> are each A5's and A7's (§15); what this decision fixes is that the enumeration is closed, that
> it always carries a does-not-settle member, and that §6 test 2 reads the member the
> **condition** declared rather than one this decision names.

> **Normative — the two vocabularies are disjoint in their values, so a `verdict` identifies
> itself.** No member of an interpretation enumeration takes a value equal to any of
> `ReadOutcomeKind`'s seven. The digest carries `verdict` and **not** `basis` (ADR-0249 §10 fixes
> its six members and this decision adds none), so a value that could belong to either vocabulary
> would be a value a reader of the digest cannot interpret — and a planner told `"empty"` without
> being told of what would be told nothing. The constraint is on the **later** vocabulary, which
> is the one not yet minted.

> **Normative — the affirmative test, which §6's second builds on and §8's fifth limb uses,
> stated here once per basis and over the closed vocabulary alone.**
>
> - A **`READ_OUTCOME`** row's verdict is **answering** where it is one of `RETURNED_RECORDS`,
>   `DUPLICATE` and `TRUNCATED` — the three members that state the source **answered with
>   records** — and is **non-answering** where it is `EMPTY`, `REFUSED`, `FAILED` or `EXPIRED`,
>   each of which states that no record came back at all. **A non-answering row satisfies
>   nothing.**
> - An **`INTERPRETATION`** row's verdict is **settling** where it is any member of its
>   `declaration`'s enumeration **other than** the does-not-settle member that enumeration
>   always carries, and **non-settling** where it is that member. **A non-settling row satisfies
>   nothing and refreshes nothing.**
> - **Affirmative** means answering on the first basis and settling on the second, and is the
>   word §8 limb 5 uses for the two together.

> **Normative — the test is a partition of a closed vocabulary and reads no count.** It does
> not read `returned`, does not read `admitted`, and is not a judgement about relevance, quality
> or usefulness. **No lane restates it as a count, adds a count to it, or makes a member's
> classification depend on one.**

**A `TRUNCATED` that returned nothing is kept out by the *first* test and needs no count to do
it.** ADR-0251 §2's precedence is explicit that the member *"displaces 5, 6 and 7 — and only
those — where completeness was not certified"*, so a `TRUNCATED` may sit over an empty answer, a
fully-deduplicated one or a productive one. Such a row has no record to compose a region from,
carries `supported` empty, and fails §6's coverage test before its verdict is ever consulted. The
partition therefore stays a statement about the **vocabulary**, and the arithmetic that used to
be needed to make it safe is done by the test that was already there.

**`DUPLICATE` is answering, and that is the correction round 2 forced.** A duplicated-out ask
returned records; §3 composes regions from them; those regions support exactly what those records
said. Whether the supply already held them is a fact about *this turn's supply* and not about the
response, and an earlier draft that read it as non-affirmative left a new goal unable ever to
obtain sufficient evidence: where initial retrieval has already put the one relevant record in
front of the planner, every servicing returning it is `DUPLICATE`, and retrieval mints no
evidence row, so there is no standing row those records were supposed to have already justified.
**Sufficiency to act and investigation productivity are two questions**, and this decision answers
only the first; ADR-0251 §7's fold answers the second, over the turn's own servicings, and is
untouched here. `DUPLICATE` stays **unproductive for that fold** and **answering for this test**,
which is the whole of the separation.

> **Normative.** **`EMPTY` is the member that most invites a false reading, and it establishes
> nothing about the world.** ADR-0237 §7 binds this decision entire and its clause is quoted
> rather than paraphrased: *"No consumer composes an assertion of absence from an empty or short
> structured result — not to the owner, not into a record, and not into a plan."* **An evidence
> row is a record in that clause's sense.** So an `EMPTY` row records that an ask was made and
> came back with nothing; it carries `supported` empty (there are no records to compose regions
> from), it satisfies no condition, and **no lane reads it as evidence that the thing it asked
> about did not happen, does not exist, or is not so.**

### 6. Sufficiency to act: four mechanical tests, evaluated at dispatch

> **Normative.** A condition of a goal is **satisfied for the purpose of dispatching a step**
> only where a `GoalEvidence` row of that goal exists for which **all four** of the following
> hold. Each is a comparison of values or of members of a closed vocabulary; **none is a
> judgement, and no model output settles any of them.**
>
> 1. **Coverage.** The row's `supported` **covers** the applicability the step's condition
>    declares, by §2's tuple-covers-applicability relation. An **empty `supported` covers
>    nothing**, so a row with none fails here first. **A condition that declares no
>    applicability imposes no coverage requirement**, and this test is then satisfied by any row
>    whose `supported` is **non-empty** — a condition about no axis this decision can compare is
>    not thereby a condition any row satisfies for free.
> 2. **The evidence the condition declared.** The condition declares the **`basis`** it
>    requires, and the row's `basis` equals it. Where that basis is `INTERPRETATION`, the
>    condition also declares the **`declaration`** whose proposition it is about and the
>    **member** of that declaration's enumeration it requires: the row's `declaration` equals
>    the declared one and its `verdict` **is** the declared member. Where that basis is
>    `READ_OUTCOME`, the row's `verdict` is **answering** in §5's sense. **A condition may never
>    declare the does-not-settle member as the member it requires**, and one that does is
>    refused rather than satisfied.
> 3. **Standing.** The row's `standing` is **`STANDING`**. An `INAPPLICABLE` row and a
>    `SUPERSEDED` row each satisfy nothing.
> 4. **Recency.** The row satisfies the **step's declared recency requirement**, evaluated at
>    **the moment of dispatch** against `as_of` where the source declared one and against
>    `read_at` otherwise.

**Test 2 asks whether this is the evidence the condition wanted, and an earlier draft asked
only whether some verdict was affirmative.** The two come apart in both directions and round 2
found both. A condition requiring an interpretation that Sunday's forecast permits an activity
shared its applicability with a plain successful read of Sunday's forecast, and that
`READ_OUTCOME` row passed coverage, affirmativeness, standing and recency without any
interpretation having happened — the step would have dispatched on *a record came back* where it
had asked for *and it says the trip is safe*. And an affirmative interpretation of a **different**
proposition passed the same four tests whenever its applicability matched, because `declaration`
was compared for conflict (§7) and for refresh (§8) and nowhere for satisfaction. Matching the
row to the declaration closes both.

> **Normative — what this pushes onto A5, stated so that lane inherits it rather than
> discovers it.** A step's condition declares **a required `basis`**, and on the `INTERPRETATION`
> basis **a `declaration`** and **the member of its enumeration the condition requires** — three
> declarations this decision does not land, on the lane ADR-0249 §13 gives the step's fields
> (§15). A condition declaring **no** basis is a **missing declaration** and fails closed on
> ADR-0228 §2(a)'s rule: *"no implementation reads an absent declaration as a default, as
> unknown-and-therefore-permitted, or as a case to decide at run time from anything other than a
> declaration."* **Whether a condition may further require a particular `read_kind` or `source`
> is A5's and is neither required nor forbidden here**; what is fixed is that a row of the wrong
> basis, the wrong proposition or the wrong member satisfies nothing.

> **Normative — one row and never several.** The four tests are evaluated **over a single
> row**, and **no lane satisfies a condition by combining two**. A condition covered by neither
> of two rows alone is not satisfied by their union, because the union asserts a conjunction
> neither response made — which is §2's regions argument stated one level up, and is what stops
> *Alice on Saturday* and *Bob on Sunday* from satisfying *Alice and Bob on Sunday*.

> **Normative — where coverage is unproven it is exact, and it refuses.** No lane folds,
> widens, clamps, rounds, extends or normalises an applicability in order to make a coverage test
> pass — not a window to a day boundary, not a label to a case-folded form, not an unapplied axis
> to *everything*. ADR-0148 §2's default is the rule and its words are the reason: *"Where the
> protocol does not establish that two distinct supplied forms denote the same recipient, the
> canonical form is the supplied form unchanged and comparison against it is byte-exact. No
> canonicaliser folds case, strips, reorders or rewrites a form on any ground weaker than the
> protocol saying those two forms are one recipient."*

> **Normative — label comparison is stated per axis, because the corpus already states it per
> axis and the three axes do not agree.** ADR-0237 §3 — *"Matching: three rules, every one of
> them borrowed"* — is the clause, adopted whole and not re-derived:
>
> - **`about_person`** — *"matches by ADR-0101 §2's rule, unchanged and unextended: a value `q`
>   matches a record `r` exactly when `r` states a subject and `NFD(toCasefold(NFD(q)))` equals
>   `NFD(toCasefold(NFD(r.about_person)))`"*, and nothing else is compared.
> - **`participants`** — *"matches by the **same** rule"*, applied across the tuple.
> - **`topics`** — *"matches by **equality of the stored characters** and by nothing else, which
>   is the only relation `TopicLabel` has (ADR-0213 §3). No fold is applied and none is needed:
>   the type is already canonical."*
>
> **No lane applies one rule to all three**, and no lane applies a rule wider than the one its
> axis names.

**Folding a topic would be a wider matching rule, which ADR-0213 reserves to an ADR that is not
this one.** That section gives a `TopicLabel` exactly one relation — *"equality of the stored
characters"* — and closes the door in terms: *"Any wider matching rule — case-insensitivity
beyond the canonical form, prefixes, hierarchy, synonymy, or a similarity measure — is reserved
to a later ADR, which is the only instrument that may lift the clause above. No lane reaches that
answer by implementing one."* ADR-0101 §2's fold is NFD-based, and precomposed `café` and
decomposed `cafe\u0301` are both admissible `TopicLabel`s that the fold equates and the type does
not — so applying it here would let evidence filed under one topic cover a condition naming the
other, which is a matching rule this decision would have made by accident. An earlier draft said
the fold applied *"where the axis's own type already fixes one — which `TopicLabel` does"*; the
type fixes a **canonical form**, which is not a matching rule, and ADR-0237 §3 had already
separated the two.

> **Normative — recency is the plan's declaration and never the evidence's property.** The
> figure lives on the step, A5 lands the field, and **a step that declares no recency
> requirement imposes none**: its condition is satisfied by a row that passes the first three
> tests however old it is. **Evidence never expires by itself**, no sweep marks a row for age, and
> no `Settings` figure, deployment flag or per-request parameter supplies a default.

**The absent declarations point in opposite directions, and that is deliberate rather than an
inconsistency.** Test 2's operands are members of closed vocabularies, so a condition that named
none of them would be a **missing** declaration and fails closed, on the clause quoted above.
Test 1's operand is an applicability, and a condition may legitimately be about no axis this
decision compares — *the trip is bookable*, with the period and the people on the step's other
fields — so an absent one imposes no coverage requirement rather than failing closed; what it may
never do is let an **empty** `supported` through, and it does not. Test 4 has **no figure
anywhere in this system** to be missing: ADR-0096 §3
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
> have `basis` `INTERPRETATION`; their **`declaration`s are equal**, so both verdicts are members
> of one enumeration about one proposition; their `supported` tuples **overlap** in §2's sense;
> **both verdicts are `settling`** in §5's sense; and their `verdict`s are **different members**.

> **Normative — a does-not-settle row conflicts with nothing, and that is stated because the
> member is a different member.** A row carrying the member meaning *the record does not settle
> it* established no answer, so it is not one side of a disagreement: it neither satisfies (§6),
> nor refreshes (§8 limb 5), nor blocks. **It is retained, exported and rendered in the digest**
> like every other row — what it does not do is veto a reading that did settle the proposition
> merely by carrying a different member of the same enumeration.

> **Normative.** **Where a condition is blocked by two conflicting rows it is not satisfied, and
> the disagreement is reported. Only a conflict between rows that could have satisfied *that
> condition* blocks it** — both of the conflicting rows carry the `basis` the condition declares
> and, on the `INTERPRETATION` basis, the `declaration` it declares (§6 test 2). A disagreement
> about **another** proposition, however its applicability overlaps, blocks nothing and is
> reported as what it is. No rule picks a winner among the rows that do block: **not recency, not
> source, not confidence, not a count of rows on each side, and not a preference between kinds.**
> The condition is unsatisfied because no single row the condition asked for settles it, and the
> obstacle is what the turn reports rather than a constraint quietly relaxed.

**The veto is scoped for the reason §6's second test is scoped, and an earlier draft scoped only
one of them.** A condition requiring declaration A's verdict for Sunday was blocked by two rows
disagreeing about declaration B over the same Sunday, because the veto read *covered by two
conflicting rows* and coverage is a statement about applicability alone. The row that answers the
condition is unaffected by an argument about a different question, and letting one stop a dispatch
would be the *"second authority that can disagree"* ADR-0249 §5 refuses — arriving through an
unrelated proposition.

**No tie-break, and each of the tempting ones is refused by a clause already ratified.** A
recency rule would let a later, weaker read overturn an earlier, stronger one — and §8's
supersession is the *narrow* case in which recency does decide, bought by requiring that the
later row **cover** what it retires, from the same source, about the same proposition. A
source-preference rule is source reputation, which ADR-0098 §6's second clause forbids anyone
from buying a bound with: *"No ADR, lane, or surface may state a bound it obtains from such a
detector."* A confidence score is a model's judgement about its own judgement, which ADR-0249
§7's asymmetry keeps out of a clearing decision. What is left is the honest outcome #2255 names:
an obstacle reported.

> **Normative — equal `declaration`s and not merely equal enumerations.** Two interpretation
> steps of one attempt may examine the same record, under the same enumeration, about two
> different propositions; their verdicts are then two answers to two questions and are **not** a
> disagreement. Comparing the declaration and not the vocabulary is what keeps them apart, and is
> the same reason §8's refresh test compares it too.

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

> **Normative.** **An empty, refused, failed or expired outcome satisfies nothing and is not an
> obstacle either.** Each is recorded as its own row with its own verdict; each is
> **non-answering** and fails §6's second test; and none of them is read as establishing that the
> thing asked about is absent, unreachable or impossible. **A `TRUNCATED` outcome is not in that
> list and is not an obstacle either**: where it returned records it is answering and its regions
> support what those records said, and where it returned none it carries `supported` empty and
> fails §6's **first** test — in neither case does *completeness was not certified* become a
> statement about the world. ADR-0251 §2's own sentence is the reason: the member *"says that
> completeness was not certified and never that more records exist."* ADR-0251 §9's clause is
> what keeps that from escalating:
> *"a `WEB_SEARCH` answering `SearchDisposition.NOT_CONFIGURED` on a turn whose reads admitted
> nothing … passes limbs 1 and 2 and **fails limb 3**"*, because *"One unavailable source
> establishes that one route is shut, not that it was the only one."*

> **Normative.** **A servicing that did not complete produces no row at all.** ADR-0251 §2's
> classifier case 1 is the rule — *"the ask was not made, the budget did not reach it, or the
> servicing's stage did not run to its end"* produces no outcome entry — and a row composed where
> there is no entry would be a record of an ask nobody put. ADR-0228 §2(d)'s posture is the
> reason: a servicing that failed or was partial *"leaves the supply as planning saw it"*, so
> there is nothing to compose a region from and nothing that happened to record.

### 8. Supersession: what refreshes the same, what never supersedes, and the mark that never un-marks

This section is the owner's **correction 1** implemented: *"Refreshed evidence needs supersession
rules, so retained historical disagreements do not permanently block progress."*

> **Normative — the refresh test, and all six limbs must hold.** A row `L` **refreshes** an
> earlier row `E` of the same goal where:
>
> 1. `E.standing` is `STANDING`;
> 2. `L.basis` **equals** `E.basis`;
> 3. `L.read_kind` **equals** `E.read_kind`, `L.source` **equals** `E.source`, and
>    `L.declaration` **equals** `E.declaration` — absent counting as equal to absent and never to
>    a present value;
> 4. both `supported` tuples are **non-empty** and **`L.supported` covers `E.supported`** in
>    §2's tuple-covers-tuple sense;
> 5. `L`'s verdict is **affirmative** in §5's sense — **answering** on the `READ_OUTCOME`
>    basis, **settling** on the `INTERPRETATION` basis;
> 6. `L`'s **effective instant** is **strictly later than** `E`'s, where a row's **effective
>    instant** is its `as_of` where the source declared one and its `read_at` otherwise.
>
> **A row that refreshes an earlier row supersedes it**: the earlier row's `standing` becomes
> `SUPERSEDED` and its `superseded_by` names `L`, in the same indivisible write that records `L`
> (§12).

> **Normative — what never supersedes, each stated so a later lane cannot read it back in.** A
> row of a **different basis**; a row of a **different `read_kind`**, **`source`** or
> **`declaration`**; a row whose `supported` is **empty**, and a row whose earlier candidate's
> `supported` is empty; a row whose `supported` **merely overlaps** the earlier row's without
> covering it; a row whose verdict is **non-answering** or **non-settling**; a row whose
> **effective instant is not strictly later** than the earlier row's, **equal instants
> included**; a **model sentence**, which is never a row at all (§14); and a row of a
> **different goal**, which the store refuses outright (§12).

**Limb 4 is coverage and not overlap, and the difference is a user's evidence quietly
disappearing.** A fresh read of **Saturday** overlaps a standing row supporting **the whole
week**, and letting it supersede would retire the week row and take its Sunday support with it —
evidence the system holds, paid for, and has not contradicted. Coverage runs the other way and
only the other way: a fresh read of the **week** covers a Saturday row and displaces it, because
everything the older row established the newer one establishes too. **A refresh may only retire
what it can itself account for**, which is also why §2 defines coverage over the tuple rather
than over an aggregate: a later row with two regions retires an earlier row only where each of
its regions is covered by one of them.

**Limb 5 is the one that protects the user, and without it a transport failure retires a good
forecast.** A refresh that came back `FAILED`, `REFUSED`, `EXPIRED` or `EMPTY` establishes
nothing and carries no region to cover with; permitting it to supersede would mean that *asking
again and getting nothing* silently retired the answer we had, and the next dispatch would fail a
condition that was satisfied a moment earlier for no reason anyone recorded. The asymmetry is
#2096 item 8's, one level down: **a later read may confirm and displace, and may never retire by
failing.**

**Limb 5 is stated per basis, and reading it as *the one affirmative member* would have made a
stale row immortal.** On the `INTERPRETATION` basis §5 fixes exactly one non-settling member —
the one meaning *the record does not settle it* — and every other member, however it answers, is
a reading that **settled** the proposition. Had the limb demanded the member §6 test 2 calls
affirmative, a fresh reading saying *no* could never retire a stale reading saying *yes*: the
negative row would stand beside the affirmative one forever, §7 would report the disagreement
forever, and correction 1 — *"retained historical disagreements do not permanently block
progress"* — would hold only in the direction the system happened to prefer. What limb 5 refuses
is a row that **established nothing**, on either basis, and a settling negative established
something.

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
that needs it does not have to reopen a `core` type — and §15 names what fires it. **On the
`INTERPRETATION` basis the identity is `declaration`**, without which one proposition's
affirmative verdict would retire another proposition's row and §7's disagreement would vanish
into a coincidence of enumerations.

**Limb 6 is the clause that keeps the mark meaning what it says, and it is stated over the
instant §6 actually evaluates.** *Superseded* asserts that something later displaced this; a row
written from a reading taken **earlier** cannot be that, whatever order the loop happened to
record them in. Keying it on `read_at` alone was wrong in a way round 2 made concrete: `E` read
at 10:00 declaring `as_of` 09:59, `L` read at 10:05 declaring `as_of` 08:00, otherwise matching
and covering. On `read_at` alone `L` supersedes `E`, and a step requiring evidence read within
fifteen minutes — which §6 test 4 evaluates against `as_of` where the source declares one — loses
the row that satisfied it and is left with one that does not. **A supersession may never regress
the effective recency instant**, so the limb is stated over that instant, and where one row
declares an `as_of` and the other does not the comparison is still between the two effective
instants, because that is the pair §6 test 4 compares a figure against.

**Strictly later and not merely *not earlier*, because equal instants made the relation
symmetric.** Two rows sharing an effective instant each satisfied *not earlier than* the other,
so either could supersede either and which one did depended on the order a conforming
implementation happened to evaluate them in. Strictness makes the relation a strict partial order
and the outcome determinate; it costs only the case of two readings the clock cannot tell apart,
where leaving both standing is the honest record.

**On the `INTERPRETATION` basis, limb 6 is what separates a refresh from a second opinion, and
two other candidates were tried and rejected.** An interpretation row's effective instant is its
`as_of` where the record it interpreted carries an attestation — which is that **source's own
report instant** (§4) — and its `read_at` otherwise. So *strictly later* on that basis means the
later row rests on a source statement the source made **later**, about the same `declaration`,
covering everything the earlier row supported. That is a relationship between the two readings and
not an artefact of the order the loop wrote them in, and it is what limbs 2 and 3 cannot supply
on a basis where no source identity exists.

**Round 2 asked for the same record and round 3 asked for a different attempt, and each defeats
the other.** Requiring `L` and `E` to interpret the **same** member of `records` would mean that
reading again never retires anything, because a re-reading necessarily interprets a **new**
record — and a three-day-old disagreement would block the goal forever, which is exactly what
correction 1 forbids. Requiring a **different `attempt_id`** would mean that an attempt which
pauses and resumes cannot refresh its own evidence, and ADR-0250 §12 is explicit that ordinary
resumption keeps the attempt — *"the attempt stays `AWAITING_CLARIFICATION`, it stays in the
candidate set, it stays engageable"* — so the retained historical disagreement correction 1
names is precisely the one that proxy would leave standing. Both proxies fail on the same
question, and the answer the row can actually carry is **when the source spoke**.

**What this accepts, stated plainly.** Two readings of two sources about one proposition, whose
sources reported at two different instants, are ordered by those instants: the later-reported one
refreshes the earlier-reported one where it covers it. A live disagreement survives where the two
sources reported at the **same** instant, and where neither reading covers the other — and every
disagreement survives until something covering and later arrives, which is the route out §8 exists
to be. This is the narrow case in which recency decides, and it is bought by the other five limbs
rather than asserted; §7's refusal to pick a winner among rows that are **not** so related is
untouched.

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

### 9. Invalidation: a marking against the revised requirement, never a deletion, never un-marked

> **Normative — the predicate is stated over the requirement and never over a changed value.**
> When `orchestration` records an interpretation revision that changes what a goal requires, a
> `STANDING` row of that goal is marked `INAPPLICABLE` if and only if **its `supported` covered
> the requirement the revision supersedes and does not cover the requirement the revision
> states**, by §2's tuple-covers-applicability relation. `inapplicable_at_revision` carries the
> `revision` that did it. **Every other row is untouched** — including a row that covered
> neither requirement, which the change did not concern.

**Stating it over the two requirements rather than over a changed value is what makes the case
#2255 names come out right, and a membership test cannot.** The scenario is *the dates move from
Saturday to Sunday*: a row supporting **Saturday alone** must be marked and a row supporting
**the whole week** must survive. A predicate reading *the row's support contains a value that
changed* marks both, because every instant of Saturday is also an instant of the week — and
choosing the **new** value instead marks neither, because Sunday is in the week and in neither
Saturday row. There is no changed value that separates a set from its superset. **What separates
them is the requirement**: the week row covers Sunday and goes on satisfying the step, the
Saturday row does not and stops.

> **Normative.** **The predicate keys on `supported` and never on `requested`.** A row whose ask
> named Saturday but whose response supports the coming week **survives** a move to Sunday,
> because what it establishes still covers the new requirement; a row whose response supports
> Saturday alone does not. Keying on `requested` would discard the first, which is a row the
> system paid for and still holds the warrant of.

> **Normative.** **Invalidation is a marking and never a deletion.** The row is kept with its
> applicabilities, its instants, its verdict and its references intact; it is still exported
> (§13), still reachable through `get_evidence` and `evidence_of`, and still in the digest the
> planner sees (§11). What changes is exactly one field.

> **Normative.** **Invalidation never un-marks.** A later revision that restores the old
> requirement does **not** return the row to `STANDING`: it is read again or it is not used.
> Un-marking would make a goal's evidence state depend on the **order** of its revisions rather
> than on what is known, so two goals that reached the same understanding by different routes
> would hold different evidence — which is the *"second authority that can disagree"* ADR-0249 §5
> refuses for a status member, arriving at a mark instead.

> **Normative — the marks are applied in the same indivisible write as the revision that
> occasions them.** `GoalRevision` carries the set, `record_interpretation` applies it, and there
> is **no second call and no window** in which a recorded revision stands beside evidence its own
> change invalidated (§12). A crash between two calls would leave exactly that state, and it is
> the state correction 1's whole purpose is to make unreachable.

> **Normative — what is deferred is the requirement, and not the predicate.** **What a revision
> requires**, and therefore what the predicate's two operands are, is the declared applicability
> A5 lands on the step (§15); no type in the tree at `54c6b72e` carries one on a
> `GoalInterpretation` or a `GoalElement`, and this decision mints none there. Until A5 lands,
> **`GoalRevision.invalidates` is empty on every revision and no row is invalidated**, which is
> stated here rather than left to inference.

**That interval is safe rather than merely admitted, and the reason is that nothing can act on
evidence yet.** §6's tests have no caller in this decision, the stage that dispatches a step is
A7's, and the step that declares a condition is A5's — the same lane that lands the declared
applicability. So there is no tree on which a row could be stale, unmarked, and permitting an
act: the first lane that can dispatch against evidence is the lane that can also invalidate it.
This is ADR-0249 §4's posture stated for a predicate rather than for a status — *"`ACHIEVED` gets
no producer here"* — and declining to invent a derivation from values that do not exist is the
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
value a reader consults, in the store and in the export alike (§13). A warrant that says *this
rested on a row the history has since dropped, and here is how many it has dropped* is a true
statement; a warrant that says *this rested on an id* when no id ever resolved is not.

### 11. The digest the planner sees, and what reads a row's standing

> **Normative.** The `evidence` the loop passes to `Planner.plan` is **one `EvidenceDigest` per
> row of that goal's history the store holds**, in §12's **total order** — `read_at` oldest
> first, ties broken by `id` ascending — projected by `orchestration` alone. Its six members are
> ADR-0249 §10's and this decision adds none:
> `requested` and `supported` are the rendering below; `read_at`, `as_of` and `standing` are the
> row's own; and `verdict` is the row's `verdict`.

> **Normative — the rendering, which is deterministic and is `orchestration`'s.** An
> `EvidenceApplicability` renders as its **applied** axes in the model's own field order —
> window, participants, topics, about_person — each named by its field name; unapplied axes are
> omitted; a window's ends render as ISO-8601 UTC instants and an unset end as the absence of
> that end; label values render **byte for byte** in the order the region holds them; and a
> non-zero `elided` renders as a count. A **`supported` tuple** renders as its regions **in
> order, each delimited from the next**, so that a reader can tell two regions from one — and a
> non-zero `supported_elided` renders as a count beside them. An **absent `requested`** and an
> **empty `supported`** each render as an absent digest member, which is what makes ADR-0249
> §10's *"an absent `supported` supports nothing"* legible on the seam. **No model writes the
> rendering, no lane substitutes a prose summary for it, and no lane makes it configurable.**

**The regions must stay distinguishable on the seam or the projection re-introduces the defect
the type removed.** A rendering that concatenated two regions' axes would show the planner one
applicability spanning both, which is the manufactured conjunction §2 exists to prevent —
arriving at the model instead of at the coverage test, where it would be *worse*, because a model
is exactly the reader that will reason from it.

> **Normative.** **Every row is projected, `INAPPLICABLE` and `SUPERSEDED` ones included**, and
> the digest's `standing` is what says which. ADR-0249 §10 put the member there for exactly this
> — *"so that refreshed evidence has a way to state that it displaces an older disagreement
> rather than standing beside it forever"* — and a digest sequence filtered to `STANDING` would
> make the member constant and the sentence false.

> **Normative.** **The digest carries no identifier of any kind**, which is ADR-0249 §10's
> clause binding on this projection: no evidence row id, no memory id, no snippet, no title and
> no address. Nor does it carry `basis`, `read_kind`, `source`, `declaration`, `records`,
> `returned`, `admitted`, `inapplicable_at_revision`, `superseded_by`, or the row's goal or
> attempt. **Those are the row's and the loop's**, and the containment is a property of the type
> exactly as ADR-0249 §9 argues for `GoalBrief`: *"an implementation that rendered every field of
> every value it was handed, logged them all, or returned them, discloses none of those, because
> there is none on the value to disclose."*

> **Normative.** **The planner is not told which rows satisfy anything.** No member of the
> digest says *sufficient*, *usable*, *fresh*, *covering* or *satisfied*; §6's four tests are
> evaluated by code at dispatch and their result crosses no seam. ADR-0249 §7's asymmetry is the
> ground, and ADR-0251 §3's clause is the precedent one level over: *"the planner is still not
> told which round it is on."*

> **Normative.** **No new class of content crosses the seam.** A rendered region carries
> instants and the label vocabularies the planner itself composes asks from and already sees on
> the records in `memories`; ADR-0004 §5's rule that *"Tier 0/1 data must never be logged"* binds
> unchanged and **nothing here logs a row, a region or a digest**. `_render_request` prints no
> identifier, which is ADR-0249 §9's clause extended by nothing.

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

### 12. `PlanStore` gains three members and changes one, and this is a BREAKING contract change

> **Normative.** `PlanStore` gains three members and changes one, and this is a **BREAKING**
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
> - **`get_evidence(evidence_id: str, /) -> GoalEvidence | None`** — the row, or `None`.
> - **`evidence_of(goal_id: str, /) -> EvidenceHistory`** — that goal's history: its rows in a
>   **total order** — `read_at` oldest first, **ties broken by `id` ascending** — and `elided`
>   counting what §13's bound has dropped.
> - **`record_interpretation` gains its invalidation set**, which is a strengthening of an
>   existing member rather than a new one: `core/types.py`'s **`GoalRevision` gains
>   `invalidates`, a possibly-empty `tuple[Identifier, ...]`**, and the member marks each named
>   row `INAPPLICABLE` with `inapplicable_at_revision` set to the revision it is appending, **in
>   the same indivisible step** as the append, the elision and the version advance. It refuses the
>   whole call where any named row is not this goal's or is not `STANDING`, and it is otherwise
>   ADR-0249 §12's member unchanged, including its compare-and-swap on `expected_version`.

**The order is total rather than merely by instant, because a label is an ordinal into it.**
§10's `E` label is *the row at 1-based index n of the `evidence` sequence*, and §13's elision
drops the **oldest** row; both read the order this member returns. Two rows written from one
servicing can share a `read_at` to the microsecond, so an order stated on that field alone leaves
two conforming stores free to return them either way round — which makes the label space differ
between implementations and makes the elision drop different rows. Breaking the tie on `id`
costs nothing and makes both testable in the shared conformance suite.

> **Normative.** `core/types.py` gains **`EvidenceHistory`**, a frozen model with
> `extra="forbid"` carrying exactly `goal_id` (an `Identifier`), `rows` (a possibly-empty
> `tuple[GoalEvidence, ...]`) and `elided` (an `int` `ge=0`). Every row of `rows` carries that
> `goal_id`, and a model validator refuses a history whose rows do not.

> **Normative.** **The store accepts commands, not snapshots.** Neither mutation takes a whole
> `GoalEvidence` back in order to write it, and no member replaces a stored row. ADR-0014 §5's
> argument binds unchanged and is ADR-0249 §12's reason for the same shape: *"Had the store taken
> a whole `ExecutionState`, any consumer of the Protocol could commit `PENDING → SUCCEEDED`
> directly and the claim that deterministic code owns state transitions (VISION §7) would rest on
> nobody choosing to bypass it."*

> **Normative — every mark rides on the write that occasions it, and there is no third
> member.** A supersession rides on `record_evidence`, an invalidation rides on
> `record_interpretation`, and **no member of `PlanStore` marks a row on its own**. Each mark is
> therefore atomic with the fact that caused it, so there is no window in which a recorded
> revision stands beside evidence it invalidated, and none in which a refreshing row stands beside
> the row it refreshed. A standalone marking member would reopen both windows for no caller's
> benefit: nothing in this system marks a row for a reason that is not one of those two writes.

> **Normative — the standing member is the compare-and-swap token, and `GoalEvidence` carries no
> `version`.** A row moves **once**, from `STANDING` to a terminal member, and never again (§8,
> §9), so the comparison a write needs is *is this row still `STANDING`* and a monotonic counter
> beside it would be a second spelling of the same fact. **The read, the comparison and the write
> are one indivisible step**, which is ADR-0250 §9's `settle_question` shape — *"The read of the
> existing question and the write are **one indivisible step**"* — applied to a mark instead of a
> disposition. A call naming a row another writer has already marked **refuses whole** rather than
> partially applying, so a caller never has to ask which of its marks landed.

> **Normative — within `record_evidence`'s one indivisible step the order is fixed: the
> refusals, then the append, then the marks, then §13's elision.** A row named by `supersedes`
> is **validated** against the history **as it stood before the call** — is it this goal's, is it
> `STANDING`, is it the row being written — so a call is never refused because its own write
> displaced its own operand.
>
> **The elision then runs over the marked history by age alone, and a row this call has just
> marked is an ordinary candidate for it.** The protection is the validation and nothing more:
> a row that was `STANDING` when the call began and `SUPERSEDED` when the marks landed is, at the
> moment the bound is applied, simply one of the goal's rows. **The one row the elision never
> drops is the row being written**, whatever place §12's order gives it, because a store that
> discarded the row it had just been told to persist would return an id from `record_evidence`
> that resolves in nothing.

**The two guarantees had to be separated because together they were unsatisfiable, and the case
is reachable.** A goal may hold `MAX_GOAL_EVIDENCE` standing rows with identical support and one
shared effective instant — limb 6's strictness is exactly what lets them accumulate without
retiring each other — and one later answering row covering that support refreshes **all** of
them. A rule protecting every row the call marks would then leave the write with no eligible
candidate: retaining all of them breaks the bound, dropping any of them breaks the protection, and
refusing the write breaks `record_evidence`'s own contract, which refuses only for the three
reasons §12 lists. Scoping the protection to the appended row leaves exactly one rule the bound
can always satisfy, and it is the rule with a caller's guarantee behind it.

> **Normative — a `superseded_by` may name a row the bound has dropped, and that is admitted
> and disclosed rather than denied.** §12's order is `(read_at, id)` and §8 limb 6 orders by the
> **effective instant**, which is `as_of` where a source declares one; the two orders are not the
> same, so a row that superseded another can sort **before** it and be elided first. Such a
> `superseded_by` is answered exactly as §10 answers a `GoalElement.evidence_row_id` naming an
> elided row — *"an identifier and not a resolution guarantee"* — the mark still states what it
> states, the loss is carried on `EvidenceHistory.elided`, and **no lane repairs it, back-fills
> it, un-marks the row, reorders retention to prevent it, or keeps a row alive because something
> names it.**

**Reconciling the two orders was the alternative and it is refused in both directions.** Ordering
retention by the effective instant would make the elision depend on a value a *source* supplies,
so a source declaring an old `as_of` could decide which of the owner's rows the bound drops —
which is the same authority §3's prohibition list keeps out of `supported`. Keeping a row alive
because another names it would make the history *"a curated selection rather than a record"*,
which §13 refuses in terms, and would let a chain of marks defeat the bound entirely. What is
left is the honest one: the bound drops by age, and every reference it can break is disclosed by
a count beside the value a reader consults. The `superseded_by` case now joins the
`evidence_row_id` case rather than claiming an exemption from it — an earlier draft asserted the
exemption and it was not true.

> **Normative — the predicate is `orchestration`'s and the atomicity is the store's, and the
> split is deliberate.** The loop computes **which** rows a new row refreshes (§8) and **which** a
> revision invalidates (§9); the store applies the marks it is given and evaluates neither
> predicate. A store that evaluated the refresh test would be a second place the rule lives, and
> the first conforming implementation to read it differently would be right in one of them.

> **Normative.** **`delete_goal`'s cascade reaches evidence**, and `GoalDeletion` gains
> **`evidence_removed`, an `int` `ge=0`**, reported exactly as ADR-0249 §12 has it report
> attempts and ADR-0250 §9 has it report questions. ADR-0014 §5's rule — *"a goal the user
> deletes must not leave its plan history behind"* — is **extended rather than re-promised**, and
> its live-step refusal is unchanged: it keys on a `RUNNING` step, and no row of any standing
> blocks a deletion. **No member deletes one row**, so the only route out of the store for a row
> is its goal's deletion, `clear`, or §13's elision.

> **Normative.** **No new Protocol is created**, so no new conformance suite and no new canonical
> fake is owed. The existing `PlanStore` conformance suite, `InMemoryPlanStore`,
> `SqlitePlanStore` and the canonical fake in `ai_assistant.testing` each gain all four
> obligations **in the same change that adds them** (`CONTRIBUTING.md` → "Adding a Protocol":
> *"The triad is what a Protocol *change* is measured against too"*). A conformance suite
> exercising one implementation would be a suite that lets the other disagree.

> **Normative — `PROTOCOL_VERSION` does not move, and that is stated rather than left to
> inference.** Nothing this decision adds is carried on a wire-borne type. `GoalEvidence` reaches
> no frame: `TurnResult.goal` is a `GoalBrief` (ADR-0249 §11), `EvidenceDigest` crosses the
> in-process `Planner.plan` seam and already exists at the tree's current version, and
> `PlanExport` *"crosses no frame: it is the portable document `PlanStore.export` returns,
> reached through that Protocol and emitted by no peer"* (ADR-0249 §12). **`GoalElement`'s and
> `GoalRevision`'s new fields are the two to check**, because `GoalElement` is reachable from
> `Goal`, which `PlanExport` carries, and `GoalRevision` is a store command that crosses no seam
> — and `Goal` itself no longer rides on `TurnResult`. **A lane that finds a wire-carried route to
> any value this decision adds moves the constant by one and records the reason in
> `wire/envelope.py`'s log**, on ADR-0124 §9's second limb; this decision asserts there is none at
> `54c6b72e` and states the test rather than the conclusion alone.

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

> **Normative.** **`PlanExport` gains `evidence: tuple[EvidenceHistory, ...]`, exactly one entry
> per goal the export carries**, and its `schema_version` annotation is **edited** to the next
> literal rather than defaulted, exactly as ADR-0249 §11 edited it and ADR-0250 §9 books the same
> edit. ADR-0014 §5's closure rule reaches it as it reaches every other member: **a history whose
> `goal_id` the export does not carry does not validate as a `PlanExport` at all**, and no goal
> the export carries is without one. ADR-0004 §6's export right is what obliges the member: a
> goal's evidence is the user's data and an export that omitted it would be an incomplete one.

> **Normative — the export carries the elision count, and not only the surviving rows.** A
> document holding 64 rows and no count would say *this is the evidence*, where the truth is
> *this is the evidence that was kept*; and an exported interpretation may ground an element on a
> row the history has since dropped, whose missing warrant is answerable only because the count
> is beside it (§10). Carrying `EvidenceHistory` rather than a bare tuple of rows is what gives
> the count a carrier, and it is the **one** nesting this document takes: ADR-0014 §5's
> *"Flat, not nested: relationships travel as the ids already on the records"* still holds
> entire, because the history carries its `goal_id` and every row carries its own, so a history
> whose goal was deleted stays representable exactly as a plan does.

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

> **Normative — the migration adds a table, a per-goal counter and converts nothing.** The
> upgrade creates the evidence table with the foreign key onto `goals` that ADR-0049 §1's schema
> discipline requires, **empty**, because no earlier store holds a row; and it provides for the
> per-goal elision count, at **zero** for every existing goal, which is true of a store that has
> never dropped a row. **The migration writes no value this system did not record** — it invents
> no row, no instant, no region and no verdict — which is ADR-0249 §12's own clause for its own
> migration, and here it is satisfied trivially because there is nothing to convert.

> **Normative — the stored `goals` blobs are not rewritten either, and that is a property of
> how §10 widens rather than a step the migration skips.** `GoalElement.evidence_row_id`,
> `GoalInterpretation.outcome_evidence_row_id` and `GoalRevision.invalidates` are each **optional
> with an absent or empty default**, and §10's validator **adds** a fourth shape while leaving the
> three ADR-0249 §1 admits untouched — so every goal blob an earlier version wrote decodes
> unchanged, as the `FROM_EVIDENCE` element it was, under the widened model. **No lane back-fills
> `evidence_row_id` from `evidence_id`**, which would assert a row that never existed.

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
> `EvidenceHistory.elided` is a value the store holds per goal and returns; **it is not
> recomputed at read time, not derived from a row count, and not reset by a deletion of any row**.
> What shape the store keeps it in is not contracted — the contract is the value, its
> monotonicity and the fact that it advances in the **same indivisible step** as the write that
> drops the rows, so a reader can never see a shortened history without the count that explains
> it. **`delete_goal` removes the count with the goal**, exactly as it removes the rows.

> **Normative.** **A row is first written at the one site ADR-0249 §11 names**, together with
> the goal, its revisions, the attempt and the turn's plans. ADR-0228 §5's prohibition binds
> entire — *"no lane adds a second persistence site, gives `LearningLoop` a `PlanStore`, or
> carries a plan out of a failing turn in order to write it"* — and ADR-0249 §11's consequence
> binds with it: **a turn that ends before that site writes no evidence row**, exactly as it
> writes no goal row, no attempt row and no plan row, and **no lane reorders persistence to write
> one sooner**.

### 14. The writer clauses

> **Normative — the production rule, stated once here and cited everywhere else.** On a turn
> working on a goal, a **completed** servicing produces **exactly one `READ_OUTCOME` row per ask
> it reached that produced an outcome entry** — ADR-0251 §2's entries, whose clause binds
> verbatim: *"Exactly one entry per ask the servicing reached, and every ask the servicing
> reached has one."* **The member the entry carries decides the row's `verdict` and decides
> nothing about whether the row is written**: `EMPTY`, `DUPLICATE`, `TRUNCATED`, `REFUSED`,
> `FAILED` and `EXPIRED` are each recorded, with `supported` empty where no record came back.
> **An ask in ADR-0251 §2's classifier case 1 produces no entry and therefore no row**, and a
> servicing that did not complete produces none (§7). **A turn that is not working on a goal
> produces no row at all**, because a row carries a `goal_id` and an `attempt_id` and there is
> nothing to fill them from. **No lane writes a second row for one entry, suppresses a row for an
> entry it judges uninteresting, or writes one from anything but an entry.**

**The rule is stated once because an earlier draft paraphrased it twice and the two paraphrases
disagreed.** §15's deferral bullet said a row *"is written only where there is something to
support"*, which suppresses exactly the `EMPTY` row §§5 and 7 require to exist and which arm 5
pins. Two implementers reading the two sentences would build two different durable histories for
the same completed empty read, with no test in either package catching the difference. A
production rule belongs in one place, and the place is the section that says who writes.

> **Normative.** **`orchestration` writes every value this decision adds, and no model writes
> any of them.** The row's `id`, `goal_id`, `attempt_id`, `basis`, `read_kind`, `source`,
> `declaration`, `requested`, `supported`, `supported_elided`, `read_at`, `as_of`, `records`,
> `returned`, `admitted`, `verdict`, `standing`, `inapplicable_at_revision` and `superseded_by`;
> each region's `window`, `participants`, `topics`, `about_person` and `elided`; the refresh set a
> `record_evidence` carries; the invalidation set a `GoalRevision` carries; and the `E`-label
> resolution and the `evidence_row_id` or `outcome_evidence_row_id` it stamps — each is written by
> the loop from
> the **injected clock**, the **injected id factory**, the **typed outcomes of a servicing** and
> the **values a store returned**. This is ADR-0249 §6's writer clause and ADR-0250 §16's applied
> to one more record.

> **Normative.** **What a model supplies toward evidence is exactly one thing**: on an
> `INTERPRETATION` row, one member of the closed enumeration its declaration names, over one
> recorded record. **No model supplies an identifier, an instant, an applicability, a standing, a
> basis, a read kind, a source, a declaration, a count or a verdict of a read**, and a planner
> envelope coming back carrying one has it **discarded silently** — not an error, not a park, not
> a degradation of the turn — which is ADR-0249 §6's posture and ADR-0228 §5's before it.

> **Normative.** **No lane of this decision produces an `INTERPRETATION` row.** The
> interpretation step that would is A5's and A7's (§15), and a row of that basis is not
> constructible without the `declaration` that lane fixes the form of. What is landed here is the
> basis, the row's shape, and the rules §§5–8 state over it — ADR-0249 §10's own posture for
> `EvidenceStanding.SUPERSEDED`, so that the lane which needs them does not reopen a `core` type.

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
> made configurable. ADR-0228 §3's non-configurability argument binds one level over, and the
> four fixed constants — `MAX_GOAL_EVIDENCE`, `MAX_APPLICABILITY_VALUES`,
> `MAX_SUPPORTED_REGIONS` and `MAX_EVIDENCE_RECORDS` — are fixed for ADR-0086 §1's stated
> reason.

### 15. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **The step's declared condition, its declared applicability, its declared recency
  requirement, its declared `basis`, and — on the `INTERPRETATION` basis — its declared
  `declaration` and the member of that enumeration it requires.** **A5**, which ADR-0249 §13
  already gives *"`ActionPlan`'s
  step fields — `depends_on`, engine-resolved result references, the `when` vocabulary and
  `verifies`"*. §6's four tests are stated over those declarations and this decision lands none of
  them. Fired by A5.
- **What a revision *requires*, and therefore §9's two operands.** **A5**, in the same lane and
  for the same reason: no type carries a declared applicability on a `GoalInterpretation` or a
  `GoalElement`, and until one does `GoalRevision.invalidates` is empty (§9).
- **The interpretation step: the form of `declaration`, its enumeration's members, its declared
  output schema, the call that produces a verdict, and which record is its whole input.** **A5**
  and **A7**. This decision fixes that an `INTERPRETATION` row carries a durable `declaration`
  resolving within the plan store, that a plan id alone does not suffice because one plan may
  declare two such steps, that its verdict is a member of a closed enumeration always carrying a
  does-not-settle member whose values are disjoint from `ReadOutcomeKind`'s (§5), and that such a
  row is over exactly one recorded record. Fired by the lane that adds an interpretation step.
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
  it reported"* and is the only authority this decision will accept for what a reader covered —
  with §3's rule binding on it unchanged, so an extent that is not a constructible `TimeWindow`
  applies no window. **How a reader's read is asked for, serviced, budgeted or audited is that
  lane's**, and whether it is a `ReadKind` member at all is ADR-0226 §1's question and not this
  one.
- **A cross-turn carrier for `ReadOutcome`.** **ADR-0251 §14's deferral, untouched.** That
  section declines a durable home for a turn's typed outcomes and names this decision's rows as
  the reason to be careful — *"two widenings of one store inside one milestone, for two
  overlapping records of what a read returned, is the collision that decision warns about"*. **A
  `GoalEvidence` row is not that carrier and no lane reads it as one**, and the three differences
  are stated rather than paraphrased. It exists **only where a goal does**: §14's production rule
  writes rows on a turn working on a goal and on no other, so the turns ADR-0251 §14 is about are
  exactly the turns that produce none. It carries **what the response supported** and the
  entry's member, and **not the typed outcome**: no `Servicing`, no `SearchDisposition`,
  `SearchRefusal`, `FetchRefusal` or `StructuredOutcome` member, no per-ask audit field, and
  nothing a later turn could re-derive the outcome object from. And it is **keyed on the goal and
  read back per goal**, never per turn. **A lane that wants the turn's outcomes across turns still
  owes the decision ADR-0251 §14 defers**, and reconstructing them out of these rows is the route
  that clause forbids.
- **A per-row retention rule of its own.** A row lives as long as its goal does (§13), and
  whether a goal's evidence should outlive or predecease the goal is a retention question ADR-0004
  §6 owns. Fired by a decision that gives goals a retention horizon.
- **A blocker vocabulary, and any producer of `GoalStatus.BLOCKED`.** ADR-0251 §9's, untouched:
  this decision supplies the sufficiency half of its limb 3 and no reason that passes all three.
- **A point-event applicability.** §3 declines the window axis for a record declaring only an
  instant, because `TimeWindow` refuses a degenerate interval and this corpus has no point type.
  Fired by a decision that mints one, which would be ADR-0237 §2's to widen and not this
  decision's.
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

**ADR-0249 §12 — partially superseded**, in the `GoalRevision` clause alone. The clause reads
*"`core/types.py` gains **`GoalRevision`**, a frozen command carrying `goal_id`, the
`GoalInterpretation`, and the `expected_version` it was computed against"*, and
`record_interpretation` is described as one that *"appends one `GoalInterpretation` to the named
goal, performs §2's elision, advances `version`, and returns the stored goal."* The command gains
`invalidates` and the member applies it, because §9 above requires an invalidation to be atomic
with the revision that occasions it and a second call cannot be. **Everything else in §12 binds
entire**: `save_goal` as the opening write alone, the attempt members and `commit_attempt` as the
attempt's only mutation route, `commit_transition`'s claim condition, the append-only reference
tuples, the compare-and-swap discipline and its error class, the commands-not-snapshots rule, the
`delete_goal` cascade, the no-new-Protocol rule, the `PROTOCOL_VERSION` rule and the
`PlanExport`-is-not-a-wire-ground rule — the last of which this decision relies on (§12).

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

**ADR-0045 §2 — not superseded, and this is the record a reader of §3 will look for.** Its
`Validity` keeps every word of its meaning: the envelope window is *"a lifecycle property of *the
record's life in the store*, set operationally by the applier"*, and §3 above reads it as
**nothing** rather than reading it as something narrower. Declining to derive coverage from it is
that section's own posture — ADR-0117 §2 records that §2 *"declined to name coverage with
`Validity`"* because *"the two say different things about different subjects"* — so this decision
inherits the distinction rather than moving it. Nothing here touches `live_at`, the read-time
predicate, the open default, or `SemanticMemory.valid_until`.

**ADR-0230 §5 and §10 — not superseded**, and two clauses of them are relied on. §10's ruling
that a fetched record *"is not a citation target and not a durable reference"* whose id *"resolves
in no store"* is why §1 gives `LOCAL_FILE` the count-only treatment rather than widening the
reference contract; §5's scoped supersession of ADR-0092 §3 — that a locally interrogated root's
report instant and the read instant *"are one event rather than two facts of which one stands in
for the other"* — is why §4 leaves `as_of` absent on such a row rather than duplicating `read_at`
into it. **Neither clause is narrowed**: the fetched record still reaches the supply, still
carries its attestation, and is still never written to any store.

**ADR-0213 §3 — not superseded, and §6 stopped trying to.** Its clause that the only relation two
`TopicLabel`s have is *"equality of the stored characters"*, and its reservation of any wider rule
to *"a later ADR, which is the only instrument that may lift the clause above"*, bind entire. An
earlier draft of §6 applied ADR-0101 §2's caseless fold to the topics axis, which would have been
that wider rule arrived at by implementation; §6 now states each axis's comparison at ADR-0237
§3, which is where the corpus already states all three.

**ADR-0101 §2 — not superseded.** Its D145 fold is used exactly where ADR-0237 §3 already applies
it — `about_person` and `participants` — and nowhere else.

**ADR-0237 §2, §3 and §7 — not superseded.** §3's three borrowed matching rules are adopted
axis by axis in §6 and none is widened. §2's `TimeWindow` is inherited whole and its two
refusals are honoured rather than worked around: §3 above declines the window axis wherever a
source's declared interval is not a constructible window, which is the conservative direction and
adds no second window type. §7's clause that *"No consumer composes an assertion of absence from
an empty or short structured result — not to the owner, not into a record, and not into a plan"*
reaches a new kind of record here and §5 states that it does.

**ADR-0251 §9 — not superseded; its deferral is answered.** That section rules that a superseded
row blocks nothing and says *"Which rows are superseded is A4's"*; §8 above is that answer, and
nothing in this decision touches §9's three limbs, its writer, its write path or its refusal to
name a reason. **ADR-0251 §2's vocabulary is adopted and not re-minted** (§5). **§7's
productivity fold is
*not* reused**, and the change from an earlier draft is recorded here rather than left to a
reader: §5's affirmative test is a partition of ADR-0251 §2's closed vocabulary and reads no
count, so the fold stays where that decision put it, over the turn's own servicings, answering the
question *did this round add anything*. Nothing in §7 moves; what moves is this decision's refusal
to borrow it for a different question.

**ADR-0250 §9 — not superseded; it is layered on.** It widens `PlanStore` and books the store's
second migration; this decision adds three members and one migration beside it, changes no member
it added, and takes its `settle_question` shape as the precedent for its own compare-and-swap
(§12).

**ADR-0249 §11 — not superseded**, and the sentence a reader will check is *"It does **not** gain
evidence rows, because A4 mints them (§10)."* That is a statement about **that decision's**
change to `PlanExport`, with A4 named in the same breath as the minter; §13 above is the minting
it anticipates, not a contradiction of it.

### 17. The lane cut

> **Normative.** This ADR is ratified and merged as its own PR before anything implements
> against it (ADR-0015, golden rule 5), and its implementation is cut into **two** lanes.

- **I1 — the contract, the store and the migration.** `EvidenceBasis`,
  `EvidenceApplicability`, `GoalEvidence`, `EvidenceHistory`, `MAX_GOAL_EVIDENCE`,
  `MAX_APPLICABILITY_VALUES`, `MAX_SUPPORTED_REGIONS`, `MAX_EVIDENCE_RECORDS`; §2's coverage and
  overlap relations, as
  functions of the types that carry them; `GoalElement.evidence_row_id`,
  `GoalInterpretation.outcome_evidence_row_id` and `GoalRevision.invalidates` with their
  validators; `GoalDeletion` and `PlanExport`; the three new `PlanStore` members and
  `record_interpretation`'s strengthening, on both conforming implementations, in the shared
  conformance suite and on the canonical fake; and the plan store's migration.
- **I2 — the loop.** Composing `requested` and the `supported` regions from a servicing's typed
  outcome, stamping the row at ADR-0249 §11's site, computing the refresh set, projecting the
  digest, and resolving the `E` label space.

> **Normative — I1 depends on ADR-0251's L1.** §5 adopts `ReadOutcomeKind`, which that
> implementation lands, so I1 follows it rather than racing it. **No lane of this decision mints
> a second read-outcome vocabulary to avoid the dependency.**

> **Normative.** **Neither lane moves `PROTOCOL_VERSION`** (§12), neither adds a `Settings`
> field, a deployment flag or a configurable figure (§14), and **neither produces an
> `INTERPRETATION` row** (§14).

### 18. The arms this decision owes

> **Normative.** The implementing lanes pin at least the following, each stated as the behaviour
> and not as a spelling:

1. **Clarification changes the campsite but not the dates.** A row whose `supported` covers the
   coming week **survives** a revision that moves the requirement from Saturday to Sunday, because
   it covers the new requirement; a row covering Saturday alone is marked `INAPPLICABLE` with
   `inapplicable_at_revision` carrying that revision; and a row covering neither requirement is
   untouched (§9).
2. **A row keyed on `requested` would have been discarded and is not.** A row whose `requested`
   names Saturday and whose `supported` covers the coming week survives a move to Sunday — the arm
   that separates the two applicabilities.
3. **Dates change and the evidence is rechecked before acting.** A step whose declared recency
   requirement the row no longer meets does not have its condition satisfied, while the row stays
   retained, exported and in the digest (§6).
4. **A forecast read that fails or is inconclusive satisfies nothing, and each fails at the
   test that actually catches it.** `EMPTY`, `REFUSED`, `FAILED` and `EXPIRED` are
   **non-answering** and fail §6's second test; a `TRUNCATED` over an answer that returned no
   record carries `supported` empty and fails the **first**; and an `INTERPRETATION` row carrying
   the does-not-settle member is **non-settling** and fails the second. **A `DUPLICATE` row is
   answering and fails neither on its verdict** — the arm asserts that too, so the separation
   cannot regress.
5. **An `EMPTY` read asserts no absence.** A row whose verdict is `EMPTY` carries `supported`
   empty and satisfies nothing, and nothing composes an assertion that the thing did not happen
   (ADR-0237 §7, §5 above).
6. **Conflicting evidence reports an obstacle.** Two `STANDING` `INTERPRETATION` rows with equal
   `declaration`s, overlapping `supported` and different verdicts leave the condition unsatisfied;
   two such rows with **different** `declaration`s do not conflict; and two `READ_OUTCOME` rows
   over overlapping applicabilities **never** conflict (§7).
7. **A refresh supersedes and progress resumes.** A later affirmative row of the same basis,
   kind, source and declaration whose `supported` **covers** the earlier row's and whose
   **effective instant** is strictly later marks it `SUPERSEDED` with `superseded_by` set, in one
   indivisible write; the remaining row stands alone and the condition is satisfied again. **The
   arm runs within one attempt as well as across two**, because ordinary resumption keeps the
   attempt (ADR-0250 §12) and a refresh may not depend on the attempt boundary (§8, §12).
8. **A narrower refresh retires nothing.** A later affirmative row covering **Saturday** does
   **not** supersede a standing row covering **the whole week**, and the week row keeps its Sunday
   support; a later row covering the **week** does supersede a Saturday row (§8 limb 4).
9. **A shared label does not bridge disjoint periods.** Rows covering *Saturday, weather* and
   *Sunday, weather* neither overlap nor cover one another, so neither conflicts with nor
   supersedes the other (§2, §7, §8).
10. **A failed refresh retires nothing, and neither does one that does not move the clock.** A
    later row of the same basis, kind, source and declaration whose verdict is `FAILED`,
    `REFUSED`, `EXPIRED` or `EMPTY` supersedes no row, and the earlier row is still `STANDING`
    (§8 limb 5); an `INTERPRETATION` row carrying the does-not-settle member supersedes nothing
    either, while one carrying a **settling** member that disagrees with the earlier row **does**.
    A row whose **effective instant** is earlier than or **equal to** the earlier row's supersedes
    nothing (limb 6), including the round-2 case: `E` read at 10:00 with `as_of` 09:59 is not
    superseded by `L` read at 10:05 with `as_of` 08:00, and the step's fifteen-minute recency
    requirement is still satisfied by `E` at 10:06.
11. **A query naming Sunday whose response supports no period.** A `STRUCTURED_READ` whose
    returned episodes declare no interval carries `requested` with its window and `supported`
    whose regions apply **no** window, and satisfies no condition that declares one (§3).
12. **Regions are not merged.** A row composed from a record covering `[09:00, 10:00)` and a
    record covering `[15:00, 16:00)` satisfies no condition declaring noon; a row composed from
    *Alice on Saturday* and *Bob on Sunday* satisfies no condition naming Alice on Sunday; and no
    condition is satisfied by two rows together (§2, §6).
13. **An unrepresentable interval applies no window, and neither does a `Validity`.** A record
    whose `ReportedExtent` has both ends unset, and a record declaring only an `occurred_at`, each
    contribute a region with no window, and the region's `elided` advances where an extent **was**
    declared and declined. **A record carrying a `Validity` with `valid_from` set, `valid_until`
    set, or both, and no `ReportedExtent`, contributes a region applying no window** and satisfies
    no condition declaring one — the arm that pins the fallback out (§3).
14. **A model sentence never becomes a row.** A planner output restating what an earlier read
    established mints no row, moves no `read_at` and supersedes nothing (§14).
15. **A marking never un-marks.** A revision restoring an earlier requirement leaves an
    `INAPPLICABLE` row marked; deleting the row that superseded another does not return it to
    `STANDING` (§8, §9).
16. **Marks are atomic with their write.** `record_interpretation` applies its `invalidates` in
    the same step as the append and the version advance, and refuses whole where a named row is
    not that goal's or is not `STANDING`; `record_evidence` does the same for `supersedes`; and
    **no store member marks a row on its own** (§12).
17. **An element grounded on a row survives the row's marking.** The revision is not rewritten,
    not re-grounded and not removed, and no revision is recorded on account of a mark (§10).
18. **An `E` label resolves against `evidence` and an `M` label against `memories`**; a label of
    neither form, an out-of-range ordinal, and an `E` label naming a row the store does not hold
    are each dropped silently (§10).
19. **The outcome grounds on a row too.** A `GoalInterpretation` whose outcome is `FROM_EVIDENCE`
    carries exactly one of `outcome_evidence_id` and `outcome_evidence_row_id`, on the same
    validator shape as an element's (§10).
20. **The bound elides and discloses.** A goal whose history exceeds `MAX_GOAL_EVIDENCE` drops
    its oldest rows and `EvidenceHistory.elided` carries how many, never decreasing and not
    recomputed from the row count; a region exceeding `MAX_APPLICABILITY_VALUES` on an axis keeps
    the first 32 and advances its own `elided`; a `supported` exceeding `MAX_SUPPORTED_REGIONS`
    keeps the first 32 regions and advances the row's `supported_elided`.
21. **The migration runs on a database of the previous version**, creates the table empty, sets
    every goal's elision count to zero, converts nothing, and refuses a database whose
    `schema_version` is newer (ADR-0049 §1).
22. **Export closure and disclosure.** An export carries exactly one `EvidenceHistory` per goal,
    each with its rows and its elision count; a history whose `goal_id` the export does not carry
    does not validate; and an element whose `evidence_row_id` names an elided row does **not**
    make the document invalid (§13).
23. **`delete_goal` cascades**, `GoalDeletion.evidence_removed` counts the rows, the elision
    count goes with the goal, and a row of any standing blocks no deletion.
24. **The two ephemeral kinds count and the three durable kinds name.** A `WEB_SEARCH` row and
    a **successful single-file `LOCAL_FILE`** row each carry `records` **empty** with `returned`
    saying how many came back and `admitted` how many were new, and **no minted or fetched id
    reaches either row** (§1, ADR-0231 §16, ADR-0230 §10). A `SIGHTED_QUERY`, `CITATION_HOP` or
    `STRUCTURED_READ` row has `len(records)` equal to `returned`, or equal to
    `MAX_EVIDENCE_RECORDS` where `returned` exceeds it, with `returned` still carrying the true
    count. **An `INTERPRETATION` row constructs**: exactly one member of `records`, `returned` and
    `admitted` both 0, no `read_kind`, a required `declaration` — and no count invariant refuses
    it.
25. **The counts survive the turn and no test reads them.** A row read back on a later turn
    carries the `returned` and `admitted` it was written with, reconstructed from no supply (§1);
    and §6's four tests, §8's six limbs and §9's predicate each reach the same verdict on two
    rows differing **only** in those two fields — the arm that pins sufficiency out of
    productivity (§1, §5).
26. **The row names the attempt that recorded it** on `attempt_id`, and is read back by
    `get_evidence` by `id` and in `evidence_of`'s `read_at` order (§1, §12).
27. **`as_of` is the source's instant or nothing.** A row over records carrying attestations
    takes the **earliest** `reported_at`; a row over the owner's own store-written records carries
    `as_of` absent; a **`LOCAL_FILE`** row carries `as_of` absent although its record's
    attestation states an instant, because that instant is `read_at` (§4, ADR-0230 §5); and no
    producer fills it from the clock, from `read_at` or from a filesystem stamp (§4,
    ADR-0096 §2).
28. **The digest discloses no identifier**, carries every row including marked ones, renders two
    regions distinguishably, renders an absent `requested` and an empty `supported` as absent
    members, and says nothing about sufficiency (§11).
29. **Sufficiency matches the evidence the condition declared.** A condition declaring the
    `INTERPRETATION` basis is **not** satisfied by a `READ_OUTCOME` row covering the same axes,
    however recent and however affirmative; a condition declaring one `declaration` is not
    satisfied by an affirmative row of **another** `declaration` with matching applicability; and
    a condition declaring one member of an enumeration is not satisfied by a row carrying a
    **different** settling member of it. A condition declaring **no** basis is refused rather than
    satisfied (§6 test 2).
30. **A condition declaring no applicability is still refused by an empty `supported`.** Such a
    condition is satisfied by a standing, answering, recent row whose `supported` is non-empty,
    and by no row whose `supported` is empty (§6 test 1).
31. **A new goal whose only relevant record is already in its initial supply can proceed.** The
    servicing that returns it classifies `DUPLICATE` with `admitted == 0`; the row's `supported`
    is composed from the returned record; and the condition is **satisfied**. The same turn's
    ADR-0251 §7 progress fold counts the round **unproductive** — the two answers are asserted
    together, on one turn (§5, §6).
32. **A shared source label does not fold a topic.** Two `TopicLabel`s that differ only by
    Unicode normalisation — `caf` + U+00E9 and `caf` + `e` + U+0301 — are **two**
    topics: a row supporting one satisfies no condition naming the other, and the two neither
    overlap nor cover. Two `participants` values differing only by case **are** one participant,
    and so are two `about_person` values (§6, ADR-0237 §3).
33. **Two readings whose sources reported at one instant disagree; a later-reported one
    refreshes.** Two `INTERPRETATION` rows with equal `declaration`s, overlapping `supported`,
    different **settling** verdicts and the **same effective instant** supersede one another in
    neither direction and leave the condition unsatisfied, whether or not they share an
    `attempt_id`; a settling row whose effective instant is strictly later and whose support
    covers one of them supersedes it, and the goal proceeds (§7, §8 limb 6).
34. **A does-not-settle reading vetoes nothing.** Two `INTERPRETATION` rows with equal
    `declaration`s and identical `supported`, one carrying the does-not-settle member and one
    carrying the member the condition requires, **do not conflict**; the condition is
    **satisfied** by the second, and the first stays `STANDING`, exported and in the digest (§5,
    §7).
35. **A disagreement about another proposition blocks nothing.** A condition requiring
    declaration A's member is satisfied by its matching row while two standing rows disagree about
    declaration **B** over the same applicability; the same two rows do block a condition
    requiring declaration B (§6 test 2, §7).
36. **A `superseded_by` may name an elided row, and the count says so.** Where §12's
    `(read_at, id)` order elides the superseding row before the row it superseded, the surviving
    row stays `SUPERSEDED`, its `superseded_by` resolves in nothing, `EvidenceHistory.elided`
    carries the loss, and no lane repairs or un-marks it. **A write never elides the row it is
    writing**, whatever place the order gives it: the oldest other row is dropped instead
    (§12, §13).
37. **Every entry gets a row and nothing else does.** A completed servicing on a goal turn writes
    exactly one row per outcome entry — the `EMPTY`, `REFUSED`, `FAILED` and `EXPIRED` entries
    included, each persisted with `supported` empty and read back on a later turn. An ask in
    ADR-0251 §2's classifier case 1, a servicing that did not complete, and a turn working on no
    goal each write **none** (§14).
38. **A `WEB_SEARCH` row and a `LOCAL_FILE` row satisfy nothing today.** Composed from the
    records ADR-0231 §16 and ADR-0230 §5 mint — `topics` empty, `about_person` absent, `extent`
    `None`, `validity` open — each carries `supported` empty and fails §6's first test, while
    still being written, exported and rendered in the digest (§3, §14).
39. **The history's order is total and the bound reads it.** Two rows sharing a `read_at` to the
    microsecond are returned by `evidence_of` in `id` order by both conforming implementations, the
    `E` labels follow that order, and the elision drops the first of them (§12, §13).
40. **A full history refreshed whole still writes, still marks and still elides.** A goal holding
    `MAX_GOAL_EVIDENCE` standing rows with identical support and one shared effective instant,
    written to with a later answering row covering that support and naming all of them in
    `supersedes`, **succeeds**: every named row is marked `SUPERSEDED` with `superseded_by` set,
    the new row is kept, the oldest row of the marked history is elided, `EvidenceHistory.elided`
    advances by one, and the call is refused for none of §12's three reasons (§12, §13).

### 19. This ADR classified under ADR-0070 §1 and ADR-0082 §1

This is a **new decision with three narrow partial supersessions**, all of ADR-0249 and all
recorded on that ADR's header by this change. It supersedes nothing else in whole or in part;
§16 shows the working for every ADR a reader would expect to be. It is a **BREAKING** contract
change under golden rule 5 — `PlanStore` gains three members and strengthens one, `GoalElement`,
`GoalInterpretation` and `GoalRevision` each gain a field, `GoalDeletion` gains a field, and
`PlanExport` gains a member and moves its version — and ADR-0249 §10 booked it as one in advance:
*"A4's widening of `PlanStore` is a second BREAKING contract change with its own ADR."*

## Consequences

**What becomes possible.** A goal holds a durable, typed record of what its investigation
established — separately from what it asked — so a later turn can tell *we asked about Sunday*
from *the answer describes Sunday*, and a step can be gated on the second. Refreshed evidence
displaces the evidence it covers, so a disagreement from three days ago stops blocking a goal the
moment somebody reads again. A search finding can ground an interpretation element for the first
time, through a row that resolves rather than through an id that never did.

**What becomes harder, and deliberately.** Nothing satisfies a condition by having completed: a
read that ran, returned, and was recorded still satisfies nothing unless its **response** covers
what the step needs, and no two rows are ever combined to cover it between them. An episodic read
supports no **period** at all, because an instant is not an interval and this corpus has no point
type — which is narrower than an implementer's instinct and is what the response actually
established. Four kinds of ask produce no `requested`, so the record of *what we looked for* is
thinner than instinct would make it, which is the price of keeping a model's composed query and a
per-call label out of a durable row. And two of the most natural adjudications are unavailable:
no rule picks a winner between two standing readings, and no read outcome is ever read as
evidence of absence.

**What this costs the corpus.** A third widening of `PlanStore` inside one milestone, after
ADR-0249 §12's and ADR-0250 §9's, and a third migration of the same store — each conforming
implementation, the shared conformance suite and the canonical fake take all three. The store is
becoming large, which is a consequence worth watching rather than a defect this decision can fix:
the alternative was a second store for evidence, rejected below. `GoalEvidence` is also a
nineteen-field record, which is more than any other `core` model carries; every field answers a
question a reviewer asked of an earlier draft, and §18's arms are what keep them honest.

**What would trigger revisiting this.** A measurement that `MAX_GOAL_EVIDENCE` elides on real
goals, which the disclosed count makes visible. A reader whose typed outcome cannot fill
`source`, `as_of` or `supported` as §15 specifies. A point-event type that would let an episodic
read support a period. An interpretation enumeration that genuinely has no member but the
does-not-settle one. And a
conflict between two `READ_OUTCOME` rows that a lane can show is real without inspecting a
record's text — which §7 argues is unreachable, and which if reached would reopen it.

## Alternatives considered

**One `applicability` field instead of two.** This is revision 0 of the report's shape and it is
what the owner's addendum corrects. With one field, the value would be filled from whichever of
the ask or the response was to hand, and the first implementation to fill it from the ask would
be indistinguishable from one that filled it from the response. Two fields written from two
objects at two moments make the confusion unreachable rather than forbidden.

**One aggregate applicability for `supported`, instead of a region per record.** Rejected: it
manufactures coverage twice over. The enclosing window of `[09:00, 10:00)` and `[15:00, 16:00)`
covers noon, which neither response supports; and the union of the label axes across records
asserts that one record carried values that two carried separately. Both are the same defect —
an aggregate states the conjunction of what several records said — and neither is visible in the
happy case, which is what makes the representation rather than a rule the right place to fix it.

**Overlap rather than coverage as the supersession test.** Rejected: a fresh read of Saturday
overlaps a standing row supporting the whole week, and retiring the week row would silently
discard its Sunday support. A refresh may only retire what it can itself account for.

**A staleness field, a freshness class, or an expiry on the row.** Refused by ADR-0096 §3 and by
the absence of any figure to put in one. It would also put the decision in the wrong place: the
question is never *is this forecast stale* but *does this booking step accept evidence read this
long ago*, and only the step knows.

**A recency tie-break for conflicting evidence.** Rejected because it would let a later, weaker
reading overturn an earlier, stronger one on no ground but its timestamp. §8's supersession is
the narrow case where recency does decide, and it is bought by six limbs — same basis, same kind,
same source, same declaration, covering support, an affirmative verdict and a strictly later
**effective** instant, which on the interpretation basis is the instant the **source** reported
— every one of which the bare tie-break would skip.

**A confidence or source-preference ranking.** Rejected on ADR-0098 §6, which forbids stating a
bound obtained from a detector, and on ADR-0146 §2's recorded-never-inferred rule. A ranking is a
judgement about content, made by the class of system an adversary is already steering.

**A fourth `Ground` member for an evidence row.** Rejected. `Ground` is *"closed at exactly three
members"* (ADR-0249 §1) and a fourth would change every exhaustive match over it, oblige the
planner to choose an id space it cannot know, and disclose the id space on the brief's
`BriefElement.ground` for no consumer's benefit. The label prefix puts the choice where the
knowledge is — the planner knows which sequence it read the label off — and leaves the
enumeration closed.

**A standalone `invalidate_evidence` member on `PlanStore`.** Rejected once §9's atomicity
requirement was stated honestly: a revision and its invalidations committed by two calls leave a
recoverable-looking intermediate state in which a new understanding stands beside evidence it
already invalidated, and nothing else in the system marks a row for a reason that is not one of
the two writes that now carry the marks.

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

**A flat `tuple[GoalEvidence, ...]` on `PlanExport`, with the elision count left in the store.**
Rejected: the exported document would then say *this is the evidence* where the truth is *this is
what was kept*, and an exported interpretation grounded on an elided row would carry a missing
warrant with nothing beside it to explain the gap — which is the silent truncation ADR-0086 §4
refuses, arriving in the one artifact the user takes elsewhere.

**Keeping `STANDING` rows preferentially when the bound elides.** Rejected: it would make the
history a curated selection rather than a record. Age is the only criterion a bound may use
without editing the audit toward the answer.

**Recomputing `admitted` at read time instead of persisting it.** Rejected: it cannot be done.
The supply a deduplication was counted over is ephemeral (ADR-0052 §3), so there is nothing on a
later turn to recount against, and a row that dropped the figure would be a durable record of a
servicing unable to say how much of what came back was new. **Sufficiency does not depend on it**
(§1, §5) — that is exactly the separation this decision makes — which is why the field is
justified by what it *records* rather than by what it gates.

**Keying the affirmative test on `returned >= 1` instead of on the vocabulary.** The smaller fix
available when round 2 found the `DUPLICATE` trap, and rejected: it keeps sufficiency reading a
count of records, which is a fact about the ask and about the turn's supply, where the question is
what the **response** supports. It also leaves the same defect one step away — a kind whose count
is composed differently, or a later member returning records the classifier counts another way,
would reopen it. A partition of a closed vocabulary has no such edge, and it needs no arithmetic
at all, because §6's first test already refuses a row with nothing to support.
