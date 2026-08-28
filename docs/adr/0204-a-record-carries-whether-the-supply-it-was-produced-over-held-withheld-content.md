# 204. A record carries whether the supply it was produced over held withheld content, and a channel of unbounded audience withholds one that does

- Status: Proposed
- Date: 2026-08-28
- **Partially supersedes:**
  [ADR-0203](0203-on-a-channel-of-unbounded-audience-the-withholding-binds-the-whole-turn.md)
  — §4's second clause, that "No episode is marked, filtered or withheld on the
  ground that a withholding occurred during the turn that produced it". That clause
  is replaced whole: an episode **is** marked on exactly that ground, and a supply
  site for a channel of unbounded audience withholds a marked one. Nothing else of
  §4 moves — its first clause is a statement about ADR-0203's own reach and stays
  true of it, its third clause about the turn's own stages is kept and relied on
  here, its fourth and fifth clauses decline to decide what this ADR decides, and
  its sixth clause is the clause that names what a decision doing so owes and is
  discharged rather than replaced. §§1–3 and §§5–9 of ADR-0203 are untouched, §1's
  subtraction most of all.
- **Partially supersedes:**
  [ADR-0199](0199-the-audience-of-the-output-channel-decides-what-may-be-said-and-a-withheld-class-is-deflected-rather-than-redacted.md)
  — §3's third clause, the placement of speakable classes, **scoped to exactly one
  case**: a record whose provenance records that content §3 withholds from a channel
  of unbounded audience stood in its warrant — by §2's direct route or §5's
  inherited one, which §1 makes exhaustive. Such a record is withheld from that
  channel however §3's third clause would place it.
  Every other record §3 places is placed unchanged, no class is unplaced, no class
  becomes speakable, and §3's first, second and fourth through eighth clauses are
  untouched — the Tier 0 floor, the withheld list, the notification key, the
  admitting-ADR obligation and the audience-alone reading of a placement all bind
  exactly as they did.
- **This is a contract change.** It adds one field to
  `Provenance` in `core/types.py` — `core` surface, so this ADR is its own
  PR, ratified and merged before anything implements against it (golden rule 5,
  ADR-0015 §5), and it owes **both** lenses: adversarial and architecture, on
  ADR-0015 §1 and `CONTRIBUTING.md` → "Stop when the required reviews are green".
  It adds no Protocol and no member to one, no new `core` type, no `Settings`
  field, no member of the promoted engine surface, no wire operation and — §7 —
  no `PROTOCOL_VERSION` bump.
- **Durability clause.** Every quotation below — from an ADR, from
  `core/types.py`, from `orchestration/`, or from an issue — is of its text as it
  stood at this ADR's base, `df06a763`, and not of its text on any later day. Where
  a later ADR changes one of the ADRs cited, this ADR is read against the text
  quoted here and that ADR's own record says what moved. This is ADR-0143's clause,
  taken for its reason.

## Context

### Where this comes from

The milestone-19 QA run (#1691) drove ADR-0199's ruling end to end on a live hub
and filed #1692 — a spoken turn deflecting on beliefs about a third party, whose
captured episode nevertheless named "her birthday, gift preference, and medical
allergies", and which a later spoken turn was then supplied. ADR-0203 closed that
chain by subtracting what ADR-0199 §3 withholds **before the turn plans**, so that
no stage of a spoken turn is handed a withheld record and nothing downstream of a
model can have derived from one.

Two paths survived that decision, and both are open in the corpus at `df06a763`.
Neither is a defect ADR-0203 introduced; each was left open in terms.

- **#1703 — the withholding turn's own question.** On `converse_spoken` the goal
  statement is the owner's utterance carried unrewritten, and `_exchange_of`
  renders it into the captured episode as `The user asked: <utterance>`.
  `ConversationLifecycle._episode` stamps that episode `OBSERVED` with
  `about_person` unset, which §3's third clause places **speakable**, so a later
  spoken turn may retrieve it and read it back. ADR-0203 §4's fifth clause records
  the path "**as open rather than closed**" and forbids its own citation as
  authority that the path is safe.
- **#1708 — a bounded channel's turn, laundering through capture.** ADR-0203 §1's
  last clause is explicit that "an operation whose channel audience is bounded —
  `converse` and `converse_streaming` as they stand — runs over its whole supply
  exactly as before", which is right for that channel's own answer. But that turn's
  plan rationale is a model completion authored **over** the withheld records,
  `Engine._capture` renders it into the episode, and the episode is stamped
  `OBSERVED` with `about_person` unset — speakable. #1708 reproduced the whole of
  that on a live hub at `4bafc026`: a typed `converse` turn whose episode reads
  `The assistant's plan: The memories already contain facts about Alice
  (penicillin allergy, birthday, gift preference)…`, retrieved into three later
  `converse_spoken` turns' `turn.memories`, one of whose planners acted on it.

### The clause that names what this decision owes

ADR-0203 §4's sixth clause is the instruction this ADR follows, quoted whole:

> "Should a later decision put content ADR-0199 §3 withholds in front of any stage
> of a turn on such a channel again, that decision owes the marking this section
> declines: an additive field on `EpisodicMemory` or on `Provenance` recording that
> the record's warrant traces to withheld content, and the rule by which a supply
> site reads it. That is `core` surface and takes its own ratified ADR ahead of any
> lane (golden rule 5, ADR-0015 §5)."

**Its antecedent has not fired, and that is the finding rather than a technicality.**
No later decision put withheld content in front of a spoken turn's stages; ADR-0203
§1 stands untouched and this ADR does not weaken it. What #1708 records is that the
corpus was *already* doing it, one channel over, through `converse` — so the case
the clause anticipated arrived from the direction it was not watching. The clause's
last sentence — "Until such a decision exists, no lane infers a marking" — is
discharged by this ADR existing, which is the sentence working rather than failing.

### Why the decidable form of "warrant traces to withheld content" is a fact about supply

ADR-0203 §4's phrase is "the record's warrant traces to withheld content", and the
tempting reading of it is a fact about the produced text: did this rationale
actually derive from that belief? **That reading is unavailable**, and it is
unavailable for the reason ADR-0199 §2's second clause gives — deciding it means
reading `MemoryBase.content`, a composed span, or asking a model what a passage is
about, which §2 forbids outright as a decision procedure. A rule that tried to
answer it would fail silently on the first rationale that alluded to a belief
without quoting it, which is the failure mode §2 exists to refuse.

The decidable form is one stage upstream: **what was the producing turn supplied,
and what was this record derived from?**
Every record and every facet in a turn's supply carries a recorded origin, so the
question is three field reads per record and an exact type match per facet —
`disclosure._speakable` and `disclosure._is_unplaced_facet` as they already stand,
which is the same discipline ADR-0203 §1 moved one stage earlier for the same
reason. It is a conservative over-approximation of "traces to", deliberately: it
marks a record whose text happens not to have used the withheld material, and it
never fails to mark one whose text did.

**And the over-approximation is what makes one field close both paths.** On a
spoken turn ADR-0203 §1 subtracts the withheld records before any stage sees them,
so nothing derived from them is in the episode — but the fact that *something was
subtracted* is the whole of what #1703 is about, and it is exactly what a supply
predicate records. On a typed turn nothing is subtracted, so the same predicate
records the case #1708 reproduced. One predicate, evaluated in one place, answering
both.

### What is not in dispute, and is used as given

- **ADR-0199 §1's audience test**, including its fourth clause that one session may
  own channels of differing audience.
- **ADR-0199 §2's recorded-origin discipline**, in both directions. This ADR adds a
  fourth recorded field to read and reads no content whatsoever.
- **ADR-0199 §5's first clause** — withheld at supply, never a filter over composed
  prose. This ADR adds a second supply-site test; it moves no ruling to the output.
- **ADR-0200 §3's declaration** that `converse_spoken` is the output channel and
  its audience is unbounded, declared on the operation and computed nowhere.
- **ADR-0203 §1 and §2 whole.** The subtraction on an unbounded channel stays where
  ADR-0203 put it, over the same predicate, with no second retrieval and no
  backfill.
- **ADR-0203 §4's third clause**, that the turn's own goal statement reaches the
  stages of the turn that asked it. Nothing here withholds a question from the turn
  that was asked it; what this ADR decides is what a **later** turn may be supplied.
- **ADR-0074 §3 and §4.** Every turn is captured, capture stamps what it witnessed,
  and nothing here adds a condition under which a turn is not captured.

### An honest statement of what this ADR is not allowed to settle

It decides one `core` field, what sets it, and what a supply site does with it. It
does not revisit ADR-0199 §3's placements for any record that does not carry the
field set, does not decide person identity or household disclosure (#691, ADR-0199
§7), does not decide the audio mechanism, does not decide whether a composed answer
joins the captured episode (#1314, left where ADR-0170 §9 and ADR-0197 §11 left
it), does not record the channel a turn arrived on (ADR-0074 §11, ADR-0200 §8 and
ADR-0200 §11 leave that to milestone 21 and this ADR does not start it), and
authorises nothing about egress, retention or deletion.

## Decision

We will record on every memory record **whether content ADR-0199 §3 withholds from
a channel of unbounded audience stood in that record's warrant** — because the
supply the turn producing it ran over held such content, or because it was derived
from a record whose own stamp is set — and we will withhold a record carrying that
stamp from any supply site for such a channel.

### 1. One additive field on `Provenance`, recording what stood in a record's warrant

> **Normative.** `Provenance` (`core/types.py`) gains exactly one
> field, `supplied_withheld_content`, a `bool` defaulting to `False`. It records
> whether content ADR-0199 §3 withholds from a channel of unbounded audience stood
> anywhere in this record's warrant, by either of exactly two routes: **directly**,
> where the supply the turn that produced it ran over held such content (§2) —
> whether or not a subtraction then kept that content from the stages that produced
> it, and whether or not the produced text drew on it — or **inherited**, where the
> record was derived from another record whose own field is set (§5).

> **Normative.** The field is on `Provenance` and not on
> `EpisodicMemory`. No `core` type other than
> `Provenance` gains a member, and no existing member of any `core` type changes
> its type, its default or its meaning.

> **Normative.** On a record written **after** this field lands, `False` is the
> field's meaning and not merely its default: it states that neither route reached
> that record, which is true of every such record no turn produced and nothing was
> derived from — a user's own assertion, a calendar import, a reader's proposal. §2
> and §5 are the only two grounds on which any producer sets it `True`, and they are
> exhaustive: no implementation invents a third.

> **Normative.** On a record written **before** this field lands, `False` is a
> decode default and not a measurement, because no producer recorded an answer. §6's
> first clause governs it: the guarantee this ADR gives is prospective, and no lane,
> implementation or later ADR cites a pre-field `False` as evidence about the record
> carrying it. No supply site is thereby given a second test — §3's is the whole of
> what a supply site applies, to every record alike, because nothing in the data
> distinguishes the two cases and a rule that pretended otherwise would be inventing
> a distinction it cannot read.

**On `Provenance` because that is the question it answers**, which is
`MemoryBase`'s own placement rule: "a field is placed by which question it answers,
not by who sets it". `Provenance` is "where a memory came from and how much it
should be trusted"; the envelope answers "what is held, about what, and for how
long". What material stood in front of the producer is the first question, not the
second. ADR-0074 §11 offers both routes and names the test — "or `Provenance` can,
where the lane argues the distinction is provenance rather than payload" — and this
is the argument.

**The sibling field settles it.** `Provenance.derived_from_external` already
answers, for a belief this system worked out, "whether the material it was worked
out *from* included recorded external content" (ADR-0106 §2). This field asks the
identical question about a different property of the same material. Putting the two
on different classes would be the corpus disagreeing with itself about where a
fact-about-the-material lives.

**And it has to be on `Provenance` for §5 to be expressible at all.** A belief the
observer later distils from a marked episode must be able to carry the stamp, and
`EpisodicMemory` cannot carry a field for a `SemanticMemory`. A field only episodes
can hold would close #1708 and leave the same laundering one distillation further
along.

**Two states rather than three, and a pre-field record is neither a third state nor
a definitive negative.** §1's fourth and fifth clauses are the pair that keeps those
apart: a post-field `False` is a measurement, a pre-field `False` is a decode
default nobody may reason from, and *neither* gives a supply site a second test to
apply — which is what stops the honest statement of the residue from turning into an
unimplementable rule about data nothing can distinguish.

**And a third state was still considered and rejected.** ADR-0109's
`last_confirmed_at` takes `None` for "the store does not hold this", and the shape
was considered here and rejected: §1's question — did such content stand in this
record's warrant, by either route? — has a true answer for every record ever
written, and for the overwhelming majority, every record no turn produced and
nothing was derived from, that answer is `False`. A `None` meaning "unrecorded" that a supply site had to withhold on would
withhold every belief in the store from the spoken channel until every producer in
the system was taught to write `False`, which is ADR-0199 §3's speakable set
emptied by a type default and milestone 19's exit test failing on the day the field
lands. §6 states the one place where the two-state field is genuinely a residue.

### 2. The stamp is set from the turn's own supply, on every channel, from recorded origin alone

> **Normative.** On every conversational operation, the supply the turn assembled
> and retrieved is evaluated against ADR-0199 §3's withholding **once, between
> retrieval and planning**, and the result of that evaluation is carried to capture.
> What varies by the channel's audience is whether the evaluation's **subtraction**
> is applied to the turn's supply — ADR-0203 §1, unchanged — and never whether the
> evaluation is made.

> **Normative.** The value carried to capture is the **disjunction of two terms
> over the one supply the turn already holds**, and is `True` where either is. The
> first is §2's direct route: that evaluation found at least one record or one
> context facet ADR-0199 §3 withholds from a channel of unbounded audience, in the
> supply **as assembled and retrieved** and before any subtraction. The second is
> §5's inherited route: at least one record in that same supply carries
> `supplied_withheld_content` already. It is `False` only where neither holds.

> **Normative.** The second term is §5's rule applied to the turn, which is a
> producer deriving a record from the records it was supplied, and it is not a
> second evaluation: it is one field read per record over a supply already in hand,
> and it reaches no `ContextProvider`, no `MemoryStore` and no store query. A turn
> that plans over a stamped record captures a stamped episode, on every channel.

> **Normative.** The value is a property of the **turn whose rendering the episode
> carries**, not of the pass that performs the capture. Where a pass captures an
> episode rendered from a turn produced by an earlier pass — the resolution of a
> parked turn, which ADR-0074 §3 captures a second time — the value carried is that
> turn's own evaluation, retained with the parked turn and applied unchanged. No
> implementation re-evaluates, recomputes or defaults it at the second capture.

> **Normative.** A pass that carries no turn carries `False`, and that is true of
> what its episode holds rather than a default it falls back on: a routed pass and a
> resumption recovered from durable state each render an episode from the utterance
> or from the bare fact of the resumption, with no goal statement and no plan
> rationale of any turn in it (`_exchange_of`, `_routed_exchange_of`, ADR-0197 §10).

> **Normative.** Capture writes that value into the captured episode's
> `Provenance.supplied_withheld_content` and stamps every other field exactly as
> ADR-0074 §4 fixes them. No other field of the episode changes, no condition is
> added under which a turn is not captured, and the episode's `content` is exactly
> what ADR-0074 §3 and ADR-0197 §10 make it — unchanged, on every channel.

> **Normative.** The evaluation is ADR-0199 §3's placement applied to ADR-0199 §2's
> recorded origin, unchanged. No class becomes speakable or unspeakable by this
> ADR, no second decision procedure is introduced, and nothing here is decided by
> reading `MemoryBase.content`, a facet's rendered text, a goal statement, a plan, a
> composed reply or any other span of content.

> **Normative.** The evaluation reaches no `ContextProvider` and no `MemoryStore`,
> performs no second context assembly and no second retrieval, and issues no store
> query of any kind. It is a predicate over what the turn already holds, and on an
> operation whose channel audience is bounded it changes nothing the turn is
> supplied.

**One evaluation, two uses, is the whole implementation.**
`orchestration.disclosure.supply_for_unbounded_audience` already returns the
narrowed context, the kept records, and a boolean saying whether anything was held
back. On an unbounded channel every one of the three is used, exactly as ADR-0203
§1 has it. On a bounded channel only the boolean is used and the narrowed supply is
discarded — the turn runs over everything, as ADR-0203 §1's last clause requires,
and the fact is recorded. There is one predicate, in one module, and ADR-0199's
posture stays where ADR-0203 §2's last paragraph put it: "the whole of the posture
lives in one module, which is where a reader will look for it".

**Evaluating on the bounded channel too is what closes #1708, and it costs that
channel nothing.** The typed turn's answer, its plan, its `TurnResult` and its
persisted plan are all untouched (§4). What it gains is a boolean about material it
was already handed, computed from fields it already carries — three field reads per
record for the first term and a fourth for the second, over a supply the turn
already holds in memory.

**And the second term is what stops the bounded channel becoming a laundry.** §3
leaves a stamped record in a bounded turn's supply on purpose, so that turn plans
over it and answers from it — which means its own captured episode is a value
derived from a stamped record. Without the disjunction the direct evaluation reads
that episode as `OBSERVED` with `about_person` unset, ADR-0199 §3 places it
speakable, and one more typed turn is all it takes to strip the stamp off the whole
warrant. The rule is §5's, and a turn is a producer like any other.

**A routed pass carries `False`, and that is true of it rather than convenient.**
ADR-0197's routed operation produces no `TurnResult`, and `_routed_exchange_of`
builds its episode from the utterance and a phrase for the route's outcome with **no
part of the routed account** — "not the listing, not the display subject, not the
scalar argument, and not the candidates" (ADR-0197 §10). There is no supply, so
there is nothing for the predicate to find, and there is no value in the episode for
a stamp to be about.

### 3. A supply site for a channel of unbounded audience withholds a stamped record

> **Normative.** A supply site for a channel whose audience is **unbounded**
> withholds every record whose `Provenance.supplied_withheld_content` is `True`. It
> does so whatever ADR-0199 §3's third clause would otherwise place the record as,
> and the withholding is at supply in ADR-0199 §5's first clause's sense: the record
> reaches no stage of the consuming turn or delivery, and nothing anywhere removes,
> masks, blanks or rewrites part of a composed value to satisfy this ADR.

> **Normative.** This test is stated over a supply site for such a channel and not
> over `converse_spoken`. Any later component that assembles what a channel of
> unbounded audience will be composed from — a further spoken operation, a
> delivery-side supply, an unprompted utterance — applies it, and an ADR admitting
> such a component states that it does rather than settling the question by silence
> (ADR-0199 §3's sixth clause, read for this field).

> **Normative.** A supply site for a channel whose audience is **bounded** applies
> this test to nothing. A stamped record is supplied to a bounded channel's turn
> exactly as it is today, and is rendered on a bounded surface exactly as it is
> today.

> **Normative.** Where this test removes a record, ADR-0203 §2 governs what follows
> unchanged: nothing is refetched, widened, re-run or backfilled to replace it, the
> order of what survives is the order it had, and the fact that a withholding
> occurred reaches the composing stage as ADR-0199 §5's third clause requires.

**This is one more field read at the site that already reads three.**
`disclosure._speakable` reads `about_person`, then `Provenance.source`, then
`Attestation.reported_by`; it gains a fourth read of the same record's provenance
and returns `False` where the stamp is set. No new module, no new seam, and the
decision procedure stays "recorded origin, never the words".

**The deflection is the same deflection.** A turn whose supply this test narrows is
a turn on which a withholding occurred, so ADR-0199 §5's third, fourth and fifth
clauses apply to it verbatim: the composing stage is told **that** something was
withheld and composes an answer stating it, the answer carries no span of and no
value derived from what was withheld, and where nothing speakable remains it says
so and carries nothing else. Nothing about the shape of a deflection moves here.

### 4. A bounded channel's own turn is untouched, and only its capture gains a stamp

> **Normative.** On an operation whose output channel's audience is bounded, the
> supply the turn runs over, the plan it produces, the step that plan drives, the
> `TurnResult` it returns, the reply composed for it and the plan persisted through
> `PlanStore.save_plan` are all exactly what they are today. ADR-0203 §1's last
> clause stands whole, and no implementation narrows a bounded channel's supply on
> the strength of this ADR.

> **Normative.** What changes on such an operation is one field of the record its
> capture writes, and nothing else. No surface renders differently, no existing
> field changes value, and no `TurnOutcome`, `TurnResult` or `SpokenTurn` member
> gains, loses or changes meaning.

**The bounded channel's own answer was never the question.** ADR-0199 §1 fixes the
posture as a function of the channel's audience alone, and a rendered page reaches a
person "only through an act of that person's own". #1708's finding is not that the
typed answer was wrong — it says so in terms, "which is correct for that channel's
own answer" — but that its *capture* becomes an input to a channel whose audience
is not bounded. The retained value is what crosses; the delivered value does not.

**Which is why the plan store and the "What happened" panel are correctly
untouched.** ADR-0203 §4's own prose notes that a mark on the episode "leaves both".
That is an objection to marking as a repair for the *spoken* channel, where ADR-0203
§1's earlier subtraction is the better instrument and is the one it took. It is not
an objection here: on a bounded channel the plan row and the rendered panel are
values delivered to a bounded audience, which ADR-0199 §1 does not restrict, and the
one path by which they reach an unbounded audience is the captured episode this ADR
stamps. #1708's own strings sweep records exactly that shape — `plans.db` carries
the typed turn's plan, and "Every `converse_spoken` turn's plan carries none".

### 5. The stamp never clears, and a record derived from a stamped one carries it

> **Normative.** No fold, merge, reinforcement or consolidation clears
> `supplied_withheld_content` on the record that carries it. Where two records are
> folded, the survivor's value is the **disjunction** of both sides' values, and no
> implementation writes `False` over a `True`.

> **Normative.** A producer that derives a record from other records in this store
> sets `supplied_withheld_content` on what it produces to the disjunction of the
> field over **every record it was supplied**. The disjunction ranges over what the
> producer received and never over the subset it cited, selected, ranked or judged
> relevant — `Provenance.evidence` is not the input set, and no implementation reads
> it as one. A producer whose inputs are not records of this store has nothing to
> inherit and writes `False`.

> **Normative.** A `SUPERSEDE` neither clears nor inherits the field, because it is
> not an operation on the stamped record's value at all. ADR-0040 §5a's
> differential — a `SUPERSEDE` "carries nothing of the target onto the surviving
> record", which ADR-0045 leaves standing unchanged — puts the correction's own
> provenance on the correction, and `supplied_withheld_content` is a member of that
> provenance. So the correction carries the value the clause above computes for the
> **proposal**, over what its own producer was supplied, and nothing of the
> target's.

> **Normative.** The stamped target is not edited by the supersession either. Under
> ADR-0045 §4 and §5a the target is **retained with a closed validity window** and
> the correction is written as a new record at a freshly-minted id, so a stamped
> record that is superseded keeps its own `True` and stays withheld from a channel
> of unbounded audience for as long as it is in the store. Neither ADR-0040 §5a nor
> ADR-0045 §4 is contradicted by any sentence of this ADR.

> **Normative.** Beyond that, no user act, configuration, setting or later lane
> clears the field in place on a record that carries it. A supersession is the only
> route by which a live belief stops carrying a `True`, and it is that route because
> it retires the record rather than editing it.

**This is ADR-0106 §4's ratchet, taken for its reason.** That section rules that
`derived_from_external` never clears and that "a fold's value is the **disjunction**
of both sides, so a tainted belief reinforced by a clean observation stays tainted.
Without that, the laundering the marker exists to stop simply moves one step along —
consolidate tainted material, then reinforce it once from a clean source and watch
the marker clear." Every word of that transfers. `orchestration/consolidation.py`
and the writer already compute exactly this disjunction for the sibling field, so
the mechanism is the one in place rather than a new one. ADR-0106 §4 draws the same
line at supersession — the user's own word is "never obliged to inherit taint from
what it retires" — and the clause above is that line generalised to any proposal,
which is what ADR-0040 §5a's differential already requires of every writer.

**The inheritance clause is what stops the second distillation.** ADR-0074 §4 makes
capture "the first producer into the derived band, arriving before the observer it
exists to feed". Without the clause, an observer distilling a belief from a stamped
episode would produce an unstamped belief that §3's third clause places speakable —
#1708's laundering with one more hop in it. Stating the rule now costs a sentence;
discovering it after the observer lands costs a supersession.

### 6. What this closes, and the residue it does not reach

> **Normative.** No lane, implementation or later ADR cites this ADR as authority
> that a record written before this field existed carries a true value in it. Such a
> record decodes `False` because nothing recorded an answer, and where its producing
> turn's supply in fact held withheld content, that `False` is wrong about it. This
> is a limit on what may be *concluded* from the value and not a second value: §1's
> fifth clause fixes the same thing at the field's own definition, and neither
> clause gives a supply site anything to read beyond §3's test.

> **Normative.** Nothing in this ADR is cited as authority that a question naming a
> third party is safe to repeat on a channel of unbounded audience where the turn
> that asked it was supplied nothing ADR-0199 §3 withholds. That case is not decided
> here, is not decidable from recorded origin, and stays where ADR-0199 §2's second
> clause leaves it.

**#1703 closes on the path it records.** Its subject is "a withholding turn's own
question", and a withholding turn is exactly a turn whose supply held content §3
withholds — so §2 stamps its episode and §3 withholds that episode from a later
unbounded-channel turn. The three remedies #1703 lists are all avoided: ADR-0199
§3's placement is not narrowed for any unstamped episode, so continuity on the
spoken channel survives for every turn on which nothing was withheld; the goal
statement is not omitted from the capture, so an episode's `content` does not become
a function of its turn's channel and the observer's citations read the same text they
read today; and the mark is the third remedy, decided here at the `core` surface
ADR-0203 §4 said it would take.

**#1708 closes at the root.** The typed turn's episode is stamped by §2 and withheld
by §3 from every later unbounded-channel supply, whatever its `content` happens to
say — which is ADR-0199 §5's first clause honoured, "the ruling at supply and never
over composed prose", so the outcome does not depend on what a composition happened
to write.

**The pre-field residue is real, is stated rather than papered over, and has a
ratified remedy.** Episodes already in a running deployment's store were captured
before this field existed and decode `False`, so a supply site will place a
pre-field episode exactly as it places one today. ADR-0203 §8 is right that a
retention horizon "would drain the offending episodes eventually, which is not a
fix". What is available and is a fix is ADR-0074 §8's deletion: unconditional,
conversation-scoped, and already a user-facing act. This ADR invents no migration —
a backfill would have to mark every pre-field episode, which is the whole
conversational history withheld from the spoken channel on the day of the upgrade —
and states instead that the guarantee is prospective, so nobody reads a `False` on
an old record as evidence about it.

**And the question residue is the one ADR-0199 §2 makes undecidable.** A turn that
asks aloud about a person the store holds nothing about is supplied nothing §3
withholds, so its episode is unstamped and a later spoken turn may repeat the
question. Deciding otherwise would mean reading the words for whom they are about,
which §2's second clause forbids in terms. Recording that as a limit is better than
a rule that would fail on the first question phrased without a name in it.

### 7. Scope: one `core` field, and no `PROTOCOL_VERSION` bump

> **Normative.** This ADR adds one field to one `core` type. It adds no Protocol and
> no member to one, no other `core` type and no field on one, no `Settings` field,
> no member of the promoted engine surface, no wire operation, and no tool. The
> `Planner`, `MemoryStore`, `ContextProvider` and `ConversationStore` contracts are
> unchanged in signature and in meaning.

> **Normative.** `PROTOCOL_VERSION` does not move for this change. The field is
> additive with a default on a model that does not forbid extras, so a peer at the
> older version accepts every frame a peer at the newer version may send and reads
> every member it names with the meaning it had; and no method's arguments or
> results change, and no encoding changes (ADR-0124 §9).

> **Normative.** The field is **hub-authoritative**. No client sets it, no component
> reads it off a wire-received record to decide a placement, and the ruling this ADR
> adds is applied in `orchestration`, at supply, inside the turn — ADR-0199 §5's
> first clause and ADR-0200 §2's clause that the gateway performs no part of the
> composition, both unchanged.

> **Normative.** Nothing here authorises egress, relaxes any permission floor, or is
> cited toward a designation, a registration or a destination. ADR-0017 §1 and §3,
> ADR-0021 §5, ADR-0148 §3, ADR-0154 §2 and ADR-0155 §1 and §3 are untouched.

**The version rule is applied rather than asserted past.** ADR-0124 §9's test is
that "`PROTOCOL_VERSION` is bumped by any change after which a frame a conforming
peer at the new version may send would be refused by a conforming peer at the old
version, or would be accepted by it with a different meaning". `Provenance` carries
`model_config = ConfigDict(frozen=True)` and does not set `extra="forbid"`, and the
new member has a default — so neither limb bites. That is what distinguishes this
from ADR-0181 §3's third field on `ConfirmationEgress`, which bumped: that field was
**required with no default** and its model **does** set `extra="forbid"`, so the
change was refused in both directions. Here an older peer decoding a newer hub's
record ignores a member it does not know, and there is no direction in which a
client emits a `Provenance` at all — every `AssistantEngine` method's arguments are
scalars, ids, a `FeedbackEvent` or a `SpokenAudio`, and `wire/surface.METHODS` is
derived from that Protocol.

**And the hub-authoritative clause is why that is safe rather than merely
permitted.** A disclosure marker an old peer silently discards would be a real
hazard if any peer decided a placement from it. None does: the withholding happens
at supply, in the hub, before anything is composed or returned, which is exactly
where ADR-0199 §5 and ADR-0200 §7 put it and where this ADR leaves it.

### 8. The representative-input tests this decision owes

These are what the implementing lane must make a test say, not a suggested file
layout. Each names an input and the outcome it fixes.

1. **A typed turn supplied a withheld record stamps its episode.** A `converse`
   turn over a store holding a belief whose `about_person` is stated: the turn's
   `TurnResult.memories` still carry that belief (§4), and the captured episode's
   `Provenance.supplied_withheld_content` is `True`.
2. **A typed turn supplied nothing withheld does not stamp it.** The same operation
   over a store of the owner's own beliefs: the captured episode's field is `False`.
3. **The typed turn's stamped episode is withheld from a later spoken turn.** With
   the episode of test 1 in the store, a `converse_spoken` turn whose retrieval
   returns it is supplied a `turn.memories` that does not contain it, and the
   composing stage is told a withholding occurred. This is #1708's chain, refused.
4. **A deflecting spoken turn stamps its own episode, and a later spoken turn is not
   supplied it.** A `converse_spoken` turn whose supply held a withheld record
   captures an episode with the field `True`, and a second `converse_spoken` turn
   over the same store is not supplied that episode. This is #1703's path, refused.
5. **A stamped episode still reaches a bounded channel.** The episode of test 1 is
   present in a later `converse` turn's `turn.memories`, unchanged.
6. **Milestone 19's exit test is unaffected.** A `converse_spoken` turn over a store
   of the owner's own `USER_ASSERTED`, `OBSERVED` and `INFERRED` beliefs with
   `about_person` unset, plus a `CalendarFacet`, captures an episode with the field
   `False`, and a second spoken turn is supplied that episode.
7. **The stamp survives a fold as a disjunction and clears on nothing.** Folding a
   stamped record with an unstamped one yields a stamped survivor, in both argument
   orders.
8. **A record constructed without the field decodes `False`.** A `Provenance`
   serialised without the member — the pre-field shape — round-trips to `False`
   rather than failing, which is §1's third clause and §6's first clause pinned
   together.
9. **A parked turn's resolution inherits its stamp, and a later spoken turn is not
   supplied either episode.** A turn supplied a withheld record that parks for
   confirmation, then resumes: both the episode captured at the park and the episode
   captured at the resolution carry `True`, and neither reaches a subsequent
   `converse_spoken` turn's `turn.memories`. The second half is what §2's third
   clause exists for — the resolution's own pass retrieves nothing, and its episode
   nevertheless renders the parking turn's goal and plan.
10. **A resumption recovered from durable state, and a routed pass, carry `False`.**
    A resumption whose parked turn is `None`, and a routed pass, each capture an
    episode whose stamp is `False` — and the same test reads the captured `content`
    to show that neither carries a goal statement or a plan rationale, which is what
    makes the `False` true of it rather than a hole.
11. **A record derived from a stamped one is stamped, and is itself withheld.** A
    producer deriving a belief from a stamped episode produces a record whose
    `supplied_withheld_content` is `True`, and that belief is absent from a later
    `converse_spoken` turn's `turn.memories`. This is §5's second clause pinned end
    to end: without it an implementation passes every test above while the second
    hop launders the value.
12. **The disjunction ranges over what the producer received, not over what it
    cited.** A producer supplied one stamped record and one unstamped one, emitting a
    belief whose `Provenance.evidence` cites **only the unstamped** input: the emitted
    belief carries `True`. This is the test §5's second clause is worth writing down
    for — an implementation that folds the field over `evidence` alone passes test 11
    and fails here, and its output reaches an unbounded channel carrying a warrant the
    producer actually read.
13. **A producer supplied nothing stamped emits `False`.** The same producer over an
    input set none of which carries the field emits a belief carrying `False`, so
    §5's disjunction is pinned in the direction that would otherwise stamp
    everything and empty ADR-0199 §3's speakable set by a different route.
14. **A bounded turn supplied a stamped episode captures a stamped episode.** A
    `converse` turn whose retrieval returns the stamped episode of test 1 — which §3
    leaves in a bounded channel's supply, deliberately — captures an episode whose
    own `supplied_withheld_content` is `True`, and a later `converse_spoken` turn is
    supplied neither. This is §2's second term pinned: the direct evaluation alone
    reads that episode as `OBSERVED` with `about_person` unset, places it speakable
    and yields `False`, so an implementation without the disjunction launders the
    whole warrant through one bounded turn and one extra hop.
15. **A supersession writes an unstamped correction beside a retained stamped
    target.** A stamped record superseded by a proposal whose own producer was
    supplied nothing stamped: the test asserts **two** records at **distinct** ids —
    the target retained with a closed validity window and still carrying `True`, and
    the live correction at a freshly-minted id carrying `False` (ADR-0045 §4, §5a) —
    and the reverse case, an unstamped target superseded by a stamped proposal,
    carrying `False` and `True` respectively. This is ADR-0040 §5a's differential and
    §5's third and fourth clauses pinned together, in both directions, so neither the
    ratchet nor the differential can be implemented at the other's expense.

### 9. What the implementing lane owes

The implementation is one lane, briefed after this ADR merges (ADR-0015 §5, golden
rule 5). It owes:

1. **The field** on `Provenance` in `core/types.py`, documented in place with what
   it records and what it does not, and the canonical fakes and provenance builders
   in `ai_assistant.testing` extended to set it. **No new Protocol is added, so no
   new triad is owed** (`CONTRIBUTING.md` → "Adding a Protocol"); what is owed is
   that the `MemoryStore` conformance suite pins the field's round-trip, so every
   implementation persists and returns it rather than silently dropping it.
2. **The capture-side stamp** in `orchestration`: the evaluation of §2 made once per
   turn between retrieval and planning on every conversational operation, and the
   resulting boolean threaded to `Engine._capture` and through
   `ConversationLifecycle.capture` into `_episode`. **Including the park's second
   capture**: `Engine._capture_resumption` hands `_capture` the parked turn itself,
   so `_exchange_of` renders that turn's goal and plan into a *second* episode, and
   the value has to ride on `_Parked` beside the `TurnResult` it belongs to rather
   than being recomputed from a pass that retrieves nothing.
3. **The supply-side read** in `orchestration/disclosure.py`: one further field read
   in `_speakable`, with the module docstring's account of what it reads extended to
   name it.
4. **The fold's disjunction** and the derivation rule of §5, alongside the sibling
   computation `orchestration/consolidation.py` and the writer already perform for
   `derived_from_external`.
5. **The fifteen tests of §8.**
6. **Closing #1703 and #1708**, which this decision answers and that lane fixes.

> **Normative.** The records this decision owes on ADR-0203 and on ADR-0199 are made
> in **this ADR's own change**, not scheduled into the implementing lane. Each is one
> change making two edits together: the earlier ADR's `Status` line takes the leading
> `Partially superseded by ADR-0204 (<scope>)` form of ADR-0070 §4 and
> `docs/adr/template.md` — accumulating a second pair on ADR-0199's line without
> dropping the first — and an appended dated note records the supersession (ADR-0070
> §1, ADR-0082 §2). The scope names the clause as this ADR's header names it, and
> nothing else of either ADR is touched. Applying one edit without the other is not a
> partial record.

**Both records are made here rather than scheduled**, which is the order ADR-0203
itself took for ADR-0199's record and the order ADR-0202 took for ADR-0004's and
ADR-0174's. ADR-0082 §7 puts the condition at the superseding ADR *existing* rather
than at its being ratified, so both orders are permitted; making them here is
possible because this ADR's change is scoped to both files, which is what ADR-0203
§7 said its own change was not.

### 10. What this ADR does not decide

> **Normative.** Beyond §§1–9 and §11, this ADR decides nothing. It changes no ADR
> other than the two clauses named in its header, adds no `core` name other than the
> one field, and moves no method signature on the promoted surface.

- **ADR-0199 §3's placements, for any record this field does not stamp.** Which
  classes are speakable is untouched in both directions. This ADR adds one further
  reason a record is withheld and unplaces nothing.
- **ADR-0203 §1's subtraction.** It stays exactly where ADR-0203 put it, over the
  same predicate. This ADR does not restore a withheld record to any stage of a turn
  on a channel of unbounded audience, and nothing here is read as licence to.
- **The channel a turn arrived on.** ADR-0074 §11 names that additive route and
  ADR-0200 §8 and §11 leave it to milestone 21. This ADR records a fact about a
  turn's *supply*, which is a different fact, and starts nothing on the channel.
- **A bounded spoken channel.** ADR-0200 §3 rules it a later ADR's, arriving as its
  own declared channel. §3's test above keys on the declaration such an ADR makes,
  with no clause here to amend.
- **Whether the composed answer joins the captured episode** (#1314). ADR-0170 §9
  and ADR-0197 §11 leave it to `track:memory` and this decision leaves it there.
  Where it lands, a stamped episode is withheld whatever its content, so §3's
  property survives it — a consequence to check then, not a permission granted now.
- **Multi-person household disclosure** (#691, ADR-0199 §7), **speaker
  identification, voiceprints and presence** (ADR-0199 §4), and **the surface on
  which a channel's audience is declared** (ADR-0199 §9). Each stands untouched.
- **Retention, deletion and egress.** ADR-0074 §7's episode horizon and §8's
  deletion protocol are untouched; §6 points at §8 as the remedy available for the
  pre-field residue and adds nothing to it.
- **A mechanical check that a wire-carried `core` type's change bumped the
  version.** #891 carries it and ADR-0124 §9 declines to design it; §7 applies the
  rule as a review obligation, which is where that ADR puts it.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0203 §4's second clause — a record is owed, and it is a partial
supersession.** The clause reads: "No episode is marked, filtered or withheld on the
ground that a withholding occurred during the turn that produced it." A reader
holding only ADR-0203 marks no episode and filters none at supply; after this
decision they mark exactly that episode and withhold it. That is a reader acting
**differently**, which is ADR-0070 §1's line, so it is a supersession, and it is
partial in ADR-0070 §3's sense because it names one clause of one section.

It is worth stating what the clause's stated **ground** was, because the ground is
what moved. §4 gives it in the same breath: "With §1 in force the withholding has
put nothing in the episode to mark: every record and every facet the captured
rendering's plan half was derived from was placed as speakable on that channel
before any stage saw it." That premise is true of a turn on a channel of unbounded
audience and false of a turn on a bounded one, which is #1708's finding, and it does
not reach the goal statement at all, which is #1703's. So the clause is replaced
rather than merely narrowed: an episode is now marked on the very ground it named.

**The rest of ADR-0203 §4 is kept, and three clauses of it are load-bearing here.**
Its first clause — "**This ADR** adds no field to `EpisodicMemory`, adds no field to
`Provenance`" — is a statement about ADR-0203's own reach and stays true of it word
for word; a later ADR adding a field does not make it false, and no record is owed
on it. Its third clause, that the turn's own goal statement reaches the stages of
the turn that asked it, is used as given and is untouched. Its sixth clause is the
one this ADR discharges: it names the shape a decision doing this owes, and this
decision has that shape.

**ADR-0203 §4's fourth and fifth clauses — no record is owed, and it is worth
stating.** The fourth declines to decide anything about the goal statement and says
what governs it "exactly as they are today"; the fifth records the residual path "as
open rather than closed", forbids ADR-0203's citation as authority that the path is
safe, and tracks it as #1703. Both are statements about ADR-0203's own scope. A
reader holding only ADR-0203 finds the question open and undecided there, and it is
still open and undecided *there*; what changed is that another ADR now decides it,
which is what §8's second bullet said would happen. Neither sentence becomes false
and neither is read more widely.

**ADR-0203 §1's milestone-19 cost paragraph is falsified and no record is owed,
because it is not a clause.** That prose reads "the conversation's recent turns
reach `memories` as captured episodes, which are `OBSERVED` with `about_person`
unset by construction (ADR-0074 §4), so the subtraction never removes one and
ADR-0074 §5's continuity seam is unaffected". After this decision the subtraction
does remove one — a stamped episode. ADR-0089 §1 rules that "a measurement, an
argument, a worked example, or a classification of the change being made is not"
normative, and §3 that in a marked ADR "unmarked text… never supplies an
obligation"; ADR-0203 is a marked ADR and that paragraph carries no mark. So no
supersession is owed on it. It is named in the dated note this change appends
anyway, because a reader checking ADR-0203's cost claim deserves to be sent here
rather than left with a sentence that has stopped being true.

**ADR-0199 §3's third clause — a record is owed, and it is a partial supersession.**
The clause places as speakable "a belief whose `Provenance.source` is
`USER_ASSERTED`, `OBSERVED` or `INFERRED` and whose `about_person` is not stated"
and two more classes. A captured episode is the first of those by construction
(ADR-0074 §4), so a reader holding only ADR-0199 supplies a stamped episode to a
channel of unbounded audience; after this decision they withhold it. Acting
differently again, so a supersession, and **narrow**: it is scoped to a record
carrying this ADR's field set — by either of §1's two routes, so a belief derived
from a stamped episode is inside the scope as squarely as the episode is — and
every other record §3's third clause places is placed unchanged.

**ADR-0199 §2 — no record is owed, and this is the judgement a reviewer should
check first.** Its first clause enumerates what a class is decided from, and one
might read this ADR as adding a fourth field to that list. It does not: §2's
enumeration is the recorded origin from which **§3's placements** are computed, and
this ADR computes none of §3's placements differently — it adds a separate reason to
withhold, decided from a separate recorded field. §2's second clause, the one that
carries the section's weight, is obeyed exactly: no class here is decided by reading
`MemoryBase.content`, a facet's rendered text, a composed reply or any other span,
and §1's argument above is that the *only* content-free form of ADR-0203 §4's
"warrant traces to" phrase is a predicate over recorded origin. §2's third clause —
content whose origin was not recorded has no class and is withheld — is untouched
and is the shape §6's residue is stated against.

**ADR-0199 §5 — no record is owed.** Its first clause puts the withholding at
supply, which is where §3 above puts this one. Its second clause is the one ADR-0203
partially superseded and this ADR does not touch either half. Its third through
ninth clauses shape the deflection, and every one of them applies unchanged to a
turn narrowed by this ADR, which §3's fourth clause states rather than leaves to be
inferred.

**ADR-0200 §8 — no record is owed, and it is the section a reader will check
second.** Its second clause ends "This ADR adds no field to `EpisodicMemory`, no
field to `Provenance`, and no record of the channel a turn arrived on." Like
ADR-0203 §4's first clause, that is a statement about ADR-0200's own reach: it
remains true that ADR-0200 adds none. It is not a prohibition on a later ADR, and
reading it as one would make ADR-0203 §4's sixth clause — which tells a later
decision to add exactly such a field — incoherent with it. §8's first clause, that
no audio is retained anywhere by any component on this path, is untouched and this
ADR retains nothing. ADR-0200 §11's deferral of **recording the channel on an
episode** is likewise untouched: this field records a fact about a turn's supply and
says nothing about the channel it arrived on, and no lane reads one off the other.

**ADR-0074 — no record is owed.** §3 captures every turn and still does; §4's list
of what capture stamps and what it leaves alone — `importance`, `participants`,
`validity`, `occurred_at`, `content` — is untouched, and "capture judges nothing" is
honoured, because capture is *handed* this boolean by the pipeline exactly as it is
handed `content` rather than computing it. §5's continuity seam is unchanged in
mechanism, and what a stamped episode costs it is stated in Consequences. §11's
bullet is the clause that offers `Provenance` as the additive route "where the lane
argues the distinction is provenance rather than payload", and §1 above is that
argument; using an offer is not amending it. Its closing warning — that a lane "must
not infer the trigger from the band: `OBSERVED` says the assistant witnessed
something" — is obeyed: this ADR reads nothing off the band and records the fact in
a field of its own.

**ADR-0040 §5a and ADR-0045 §4 — no record is owed on either, and §5's third and
fourth clauses are written to make that true rather than to assume it.** §5a's
differential is that a `SUPERSEDE` "carries nothing of the target onto the surviving
record", and ADR-0045's own amendment note records that this half "stands unchanged"
while §5a's id clause was rewritten — the correction is no longer written at the
target's id; the target is "**retained with a closed validity window**" and the
correction is written at "a **freshly-minted id absent from the store**". A ratchet
that made a correction inherit its target's stamp would contradict the differential;
one that edited the target would contradict the retention. This ADR does neither:
`supplied_withheld_content` is a member of the proposal's provenance and travels with
it exactly as `derived_from_external` already does, and a retained target is not
written to at all, so a writer conforming to §5a and to ADR-0045 §4 conforms to §5
with no further rule. §8's test 15 pins both records, both ids and both directions.
ADR-0040's `REINFORCE` half is likewise untouched — §5's first clause states the
disjunction for a fold, which is the evidence-shaped obligation §5a already puts on
that arm and not a new constraint on how content or confidence combine.

**ADR-0106 — no record is owed.** Its subject is `derived_from_external`, and every
clause of it is about that field. This ADR adds a sibling and reuses §4's ratchet
argument by citation; it changes no rule about `derived_from_external`, and no
consumer of that field reads or writes this one.

**ADR-0124 §9 — no record is owed.** §7 above applies its bump rule and comes out at
"no bump", which is the rule working rather than an exception to it, and its review
obligation on any change to `core/types.py` is discharged by this ADR and by the
lens set §7 names.

## Consequences

**#1708's chain is closed at the root and #1703's on the path it records.** A record
in whose warrant such content stood — because its producing turn was supplied it,
or because it was derived from a record that was — does not reach a channel of
unbounded audience, whatever its text says and whichever channel its turn ran on. The
outcome no longer depends on what a model happened to write into a rationale, which
is ADR-0199 §5's first clause finally holding across the whole path rather than on
one channel.

**Continuity on the spoken channel is lost for exactly the turns that were supplied
withheld content.** The owner who asks aloud about their partner, is deflected, and
a day later asks "what have we talked about?" does not get that turn back — and
neither does the owner who asked about their partner on the typed channel. That is
the trade ADR-0199 §7 already took for third-party beliefs, extended by one hop, and
it is bounded to those turns: every turn on which nothing was withheld is supplied
exactly as it is today, so milestone 19's exit test is untouched (§8, test 6).

**A bounded channel pays one boolean per turn.** The disclosure predicate now runs
on every conversational operation rather than on spoken ones alone. It is three
field reads per record and an exact type match per facet over a supply the turn
already holds, with no store call, so the cost is arithmetic; what it buys is that
the fact is recorded at the one moment it is decidable.

**`Provenance` gains a fourth thing a producer can get wrong.** The field is
defaulted, so a producer that forgets it writes `False` and a record is supplied
that should have been withheld — the fail-open direction, and the one this ADR
accepts deliberately in §1's third clause because the alternative empties ADR-0199
§3's speakable set. §5's disjunction and §8's tests are the mitigation — tests 9, 11, 12 and 14
in particular, which pin the two paths on which a value travels without a fresh
evaluation to compute it — and a producer review obligation is the rest of it.

**Deployment is one redeploy of the hub with no version handshake to coordinate**
(§7). Existing stores read back with the field `False`, which is right about every
record except the episodes of turns that were already supplied withheld content —
§6's residue, whose remedy is ADR-0074 §8's conversation deletion.

**What would trigger revisiting this.** A producer that derives a record from
something other than this store's records and cannot answer the inheritance question
of §5; a channel whose audience is bounded arriving on the spoken path (ADR-0200
§11), which would make "unbounded" a per-channel test at more than one site; or
person identity landing (#691), which is the setting in which #1703's remaining
question — a question naming a third party on a turn where nothing was withheld —
stops being undecidable from recorded origin.

## Alternatives considered

**Omit the goal statement, or the plan rationale, from a withholding turn's
capture.** Available inside `orchestration` with no `core` change, and rejected for
the reason ADR-0203 §4 gives and #1703 repeats: it makes an episode's `content`
depend on the channel its turn arrived on, which reaches every consumer of
`content` including the observer's citations, and it produces the silent hole in
the conversation record ADR-0197 §10 warns a lane will leave. It also does not
close #1708, whose episode is captured on a channel where no withholding was
applied at all.

**Narrow ADR-0199 §3's placement so no episode is speakable on an unbounded
channel.** Rejected because it over-withholds catastrophically: the conversation's
recent turns *are* episodes (ADR-0074 §5), so it ends continuity on the spoken
channel for every turn, withheld or not, and milestone 19's exit test asks for an
answer "drawing on accumulated memory".

**Extend ADR-0203 §1's subtraction to the bounded channel — plan a typed turn over
the narrowed supply too.** This would close #1708 with no `core` change at all, and
it is rejected because it answers a disclosure question by degrading an answer whose
audience ADR-0199 §1 places as bounded. The typed answer is ruled correct by ADR-0203
§1's last clause; taking it away would mean the owner can no longer ask about their
partner on any channel, which is the capability ADR-0199 §5's deflection exists to
preserve by naming the screen. It also leaves #1703 entirely, since a spoken turn's
goal statement is not in any supply.

**A three-state field, with `None` meaning "no producer recorded an answer" and a
supply site withholding on it.** This is ADR-0199 §2's third clause and ADR-0109's
`last_confirmed_at` shape, and it is the fail-closed direction, which is why it was
weighed seriously. It is rejected because the absence is not in fact informative
here: the question has a true answer for every record ever written, and for every
record no turn produced that answer is `False`. Withholding on `None` would withhold
every belief in the store from the spoken channel until every producer in the system
wrote an explicit `False` — ADR-0199 §3's speakable set emptied by a type default, on
the day the field lands. §6's first clause is what carries the honest part of the
objection: the pre-field residue is stated, and no reader may treat an old record's
`False` as evidence.

**The field on `EpisodicMemory` rather than on `Provenance`.** ADR-0074 §11 offers
both. Rejected on the placement test `MemoryBase` states — the field answers where a
record came from, not what is held — on the sibling `derived_from_external` already
occupying the analogous slot on `Provenance`, and decisively on §5: a belief distilled
from a stamped episode must be able to carry the stamp, and a field only episodes can
hold would leave the same laundering one distillation further along.

**Mark the record but leave the supply site alone, and filter at the composing
stage or over the composed answer.** Rejected by ADR-0199 §5's first clause and §2's
second: a filter over composed prose is content inspection, it fails silently on the
first sentence it did not anticipate, and "a composed answer with a hole cut in it
is exactly that — an utterance the listener cannot distinguish from a complete one".
