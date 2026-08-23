# 189. A projection carries the origin of what it shows, and the named source is one configured source rather than a reader

- Status: Accepted
- Date: 2026-08-24

## Context

`readers/email.py` is on `main` beside `readers/calendar.py`. That single fact
fires a trigger four ratified documents wrote against, and it makes a sentence
this system says to its users stop being sufficient.

### The four projections, read at `HEAD` rather than remembered

`core/types.py` carries four models that put a stored record in front of a user,
and this is the whole of what each of them knows about where its content came
from:

| Projection | Standing | Which source | When it spoke | Warrant from outside |
| --- | --- | --- | --- | --- |
| `BeliefSummary` | `band` | — | — | — |
| `Belief` | `band` | — | — | — |
| `Question` | `band` (the band the proposal *would* enter) | — | — | — |
| `Retirement` | — | — | — | — |

`Retirement` carries `record_id` and `content` and nothing else. `Question`
carries `band`, which under `_project` in `orchestration/questions.py` is
`band_of(record.provenance.source)` of the **proposal**, and says nothing about
each entry in `retires`. `Belief` and `BeliefSummary` carry `band` and drop the
`Attestation` the record holds.

What the store holds is much richer. `Provenance` makes an `Attestation` present
**exactly** when the band is `ATTESTED` (ADR-0092 §1), so every attested record in
the store names its reporting source and the instant that source said the fact was
current. `Provenance.derived_from_external` records, for a derived belief, whether
its warrant traced to recorded external content, and `rests_on_recorded_external_content`
is the function every consumer asks (ADR-0106 §2). None of it survives the
projection.

### The tier that stopped doing another tier's work

ADR-0098 §8 states three tiers and is explicit that they are stated separately
because that is "the honest version": this system can say **"a source you connected
reported it"** today; it cannot yet say **"your calendar"**; and it will never say
**"Bob"**.

The first tier was written against one reader. With one reader, "attested"
identified the source by elimination — a user reading it knew it meant the
calendar, because there was nothing else it could mean. With two, it does not. A
`.ics` file the user probably owns and an inbox the open internet writes into now
render identically on every inspection surface, and those two have materially
different trust properties. ADR-0098 §12 wrote that trigger down and called it
"this ADR's own": the named half "**fires with the second reader**, when 'attested'
stops identifying the source by elimination."

The surfaces say so themselves. `interfaces/cli.py`'s `_why` renders an attested
belief as *"a source you connected reported it — neither your word nor my
inference. I recorded which source, and when it said so, but cannot show them here
…"*, and the browser's `whyHeld` in `interfaces/gateway/assets/app.js` says the same thing in
the same words. Both sentences are true. Both were written as a statement of a
limitation with a tracker attached (**#1276**), and both stop being adequate at the
moment "which source" has more than one answer.

### Two ratified obligations converge on this ADR, and they are not the same one

**ADR-0098 §8's second clause** is the one #1431 raises:

> **Normative.** Naming **which** source is **not discharged**. It binds the ADR
> that next revises the projection carrying a belief to an inspection surface, and
> binds no surface that cannot do it. §12 records it as live.

**ADR-0073 §4's `ATTESTED` gate** is older, stronger, and is not cited by #1431 at
all. §4 rules that for an attested belief "the complete answer names **what
reported it, and when that source said so**", records that "**Neither half is
carried by any field today**", and sets a gate:

> The gate is on leg 6's first `EXTERNAL` producer: carrying **both** the reporting
> source's identity and its report time is a precondition of it shipping, and
> whether that needs `Provenance` to grow fields is a `core` decision for that lane
> — with a producer in hand — not one to guess here.

Half of that gate was met. ADR-0092 §1 grew `Provenance` the `Attestation`, so the
*record* carries both halves. The *surface* carries neither, and ADR-0073 §4 is a
section titled "What the surface must convey per belief". So the gate is met at the
store and unmet at the projection, and it has been unmet since leg 6's producer
shipped.

The two obligations differ in what they demand. §8 asks for **which source**. §4
asks for **which source and when it spoke** — and §4's own floor adds a third
demand this ADR must not lose: a surface "must not offer our own revision time as
the source's", which is exactly what a surface does when it has only `last_updated`
and a user asking "since when?".

**ADR-0107 did not pass this silently, and that is worth stating because it was the
next reviser.** ADR-0107 revised both belief projections on 2026-08-05, before the
email reader landed on 2026-08-12, and its §10 declined this question by name:
"Whether `Provenance` should record which connected source attested a belief, and
whether the belief DTOs should carry it. ADR-0092 §1 answered the first; the second
is ADR-0073 §4's other open gate and is not this field's question." Nothing is owed
against ADR-0107 for that (§11).

### One lossy-projection shape: one instance settled, three live

ADR-0098 §12 calls this "the **third instance of one lossy-projection shape**
rather than three coincidences", and ADR-0106 §12 rules that "a fourth field added
ahead of the lane reconciling those three is the wrong order of work". Read at
`HEAD`, the ledger is:

- **#568** — the elided-citation count. **Settled**, by ADR-0107 §3: both DTOs
  carry `evidence_elided`, as a field, under one name. It is this ADR's precedent
  rather than its subject.
- **#673** — `Retirement` carries no origin at all, so a question renders
  attacker-authorable calendar text under *"Accepting would retire:"* with no
  marker. **Live**, and ADR-0098 §12 records it as firing now rather than on a
  future revision.
- **#1276** — `Belief` and `BeliefSummary` cannot carry the attesting source or
  when it spoke. **Live.**
- **#746** — no structured marker for a warrant resting on recorded external
  content, so a surface "can only pass through a sentence": it cannot style it,
  filter on it, or decline to render the belief as the assistant's own inference.
  **Live.**

ADR-0107's Consequences names the question those three share and asks for it to be
asked once: "the question of how many scalars this surface should carry before it
wants a nested provenance object is worth asking once rather than four times". §3
is that question, answered.

### ADR-0093 §11's trigger has **not** fired, and this ADR decides ahead of it

#1431 reports ADR-0093 §11's registry trigger as fired alongside ADR-0098 §8's. It
is not, and the correction matters because it changes what this ADR is allowed to
claim. §11 reads:

> - **A source registry**, and with it a **configurable display label** (§7) and an
>   instance-distinguishing `reported_by`. §7 revisits at the third source; the
>   label acquires a subject at the second instance of one source type.

Both of §7's own statements of its condition are "a second instance of one source
type" — "Revisit when a second instance of one source type exists and needs
distinguishing", and "leaves the question live at the point where it acquires a
subject: §11's registry deferral, when a second instance of one source type
exists". Two source *types* is not two instances of one type. `calendar_reader_path`
and `email_source_path` are each one path, so `app/composition.py` builds readers
for exactly one configured calendar and one configured mailbox. **Nothing on `main`
has a second instance of anything**, and §11's own differently-worded first phrase —
"§7 revisits at the third source" — is not met either, nor is ADR-0142 §8's reading
of §11, in which "the registry *and* its configurable display label *and* its
instance-distinguishing `reported_by` all fire together" at the third source. The
corpus offers three phrasings of one trigger and **all three are unfired**, which is
what lets this ADR proceed without first having to settle which of them is right
(§8, §12).

So the instance half of this ADR decides a rule before the condition that was to
bring it back. That is a deliberate act with a precedent and a price, and both are
stated at §6 — which is also why §6 rules an identity's *properties* and refuses to
rule its shape.

The **owner ruled this cluster into scope** as one decision (#1501, 2026-08-23),
naming the instance-distinguishing `reported_by` and the display-label rule that
lifts ADR-0097 §9a's gate. This ADR takes that scope and states plainly, where it
applies, that a clause is ruled ahead of its trigger rather than by it.

### What ADR-0097 §9a actually gates, read rather than paraphrased

> **Normative.** The lane that introduces a source registry and an
> instance-distinguishing identity (ADR-0093 §11) owes, as part of that work, the
> rule for what a live grant does when its source's identity or backing location
> changes. **A second instance of one source type may not become grantable before
> that rule exists.** This is a named precondition on that lane, in the form
> ADR-0021 §3 used on the standing-grant ADR.

The gate lifts when **the rule exists** — not when a registry is built. §7 states
that rule. §8 leaves the registry deferred with its own trigger restated.

### An honest statement of what this ADR is not allowed to settle

- **It may not re-decide ADR-0181.** That ADR's boolean deliberately names no
  source, on ADR-0106 §2's no-consumer ground. This ADR is the consumer arriving
  **on the memory side**, and it adds nothing to the egress seam.
- **It may not name the author within a source.** ADR-0098 §8's third clause is
  adopted unchanged; §4 restates the boundary and narrows it nowhere.
- **It may not claim influence.** ADR-0098 §5's marked limit and ADR-0106 §1's
  second clause bind every marker this ADR projects: none of them detects external
  content embedded in text whose recorded origin is not external.
- **It may not reopen ADR-0186 §7 or ADR-0187.** The audit trail's row rendering
  and the band ordering are settled on their own lanes and are cited here as
  precedent and as boundary, never revisited.
- **It may not decide the reader-side adversary model**, which is #641's remaining
  half, or ADR-0093 §4's `sensitivity` revisit. §10 routes both.
- **It may not implement anything.** Every field below is `core/types.py` surface
  and lands as its own contract PR ahead of any consumer (golden rule 5,
  ADR-0015, ADR-0068 §2).

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. The rule, stated once over the class rather than four times over four fields

> **Normative.** A **user-facing projection** — a model in `core/types.py` built
> from a stored record for the purpose of putting that record in front of a user —
> carries, as **structured fields**, the origin of what it shows: the **standing**
> the record is held with, whether its warrant **rests on recorded external
> content**, and, where the record is attested, **what reported it and when that
> source said so**. Prose in an adjacent free-text field does not satisfy this
> clause.

> **Normative.** A projection carries these facts **as the record holds them**. It
> does not compute a rendering, choose a wording, decide what is worth showing, or
> omit a fact because the surface it expects would not display it. What a surface
> renders is §4's and §5's; what a projection carries is this clause's.

> **Normative.** This clause binds the four projections §2 names and every later
> model added for the same purpose. A projection that cannot carry one of these
> facts is "defective in that respect" under ADR-0098 §7's third clause, and the
> debt falls on the ADR that defines or next revises it, exactly as that clause
> already rules.

**The rule is over the class because the corpus has now paid four times for
answering it one field at a time.** ADR-0098 §7 records the pathology in its own
words: rounds 5 through 8 of that lane "each found a different projected field that
cannot carry an origin … and each was answered by narrowing the clause around that
one field. That is whack-a-mole, and the fourth instance is what made the shape
visible." §7's third clause closed the class on the *obligation* side by assigning
the debt. This section closes it on the *discharge* side by saying what discharges
it, so that a fifth projection is answered before it is written.

**"Structured, not prose" is the half ADR-0106 §6 could not supply.** That section
discharged #746's substance through `MemoryDecision.reason`, which is the channel
that exists — a sentence. ADR-0106 §12 names what a sentence cannot do: "a surface
cannot style it, filter on it, or refuse to render it as the assistant's own
inference — it can only pass through a sentence." A field can. That is the whole of
what this ADR adds to ADR-0106 on that axis, and it is why the marker is a field
rather than a better sentence.

### 2. What each of the four projections gains

> **Normative.** `Belief`, `BeliefSummary` and `Question` each gain two fields:
> `attestation: Attestation | None = None` — the record's `Provenance.attestation`
> as stored, projected whole — and
> `rests_on_recorded_external_content: bool = False`.

> **Normative.** `Retirement` gains one field, `warrant: Warrant | None = None`,
> where `Warrant` is the new promoted type §3 defines.

> **Normative.** A producer of a `Retirement` sets `warrant` **exactly when** it
> sets `content`: both are resolved from one `MemoryStore.get`, and `None` on both
> is the case ADR-0045 §6 produces, where the store hides a closed window and the
> retired record no longer resolves. The obligation is on the producer; no
> cross-field validator on `Retirement` asserts it, for the reason §3 gives.

> **Normative.** On `Question`, both fields describe the **proposal** — the record
> that would be written if the question were accepted — on the same reading
> `band` already has there, and describe no entry in `retires`. Each entry in
> `retires` answers for itself through its own `warrant`.

> **Normative.** `rests_on_recorded_external_content` on any projection is the
> value of `core.types.rests_on_recorded_external_content` (ADR-0106 §2) applied to
> the projected record's `Provenance`, computed by the engine at projection time.
> No producer supplies it, no surface recomputes it from `band` and no component
> reads `Provenance.derived_from_external` in its place.

> **Normative.** `attestation` is present exactly when the projected record's band
> is `ATTESTED`, which `Provenance`'s own validator already guarantees upstream. No
> cross-field validator is added to `Belief`, `BeliefSummary` or `Question` to
> assert it, and the absence of that validator is §3's decision rather than an
> omission.

**Projecting the `Attestation` whole, rather than two scalars beside it, is the
cheap answer and also the right one.** ADR-0092 §2 already argued the shape: the
two halves are carried "as **one value object rather than two nullable fields**"
because two independent `| None` fields "admit four states, of which two are
half-answers: a record naming a source but not when it spoke renders 'your calendar
had this as of …' with a blank, and one naming a time but not a source attributes
it to nobody." ADR-0073 §4's gate demands **both halves**; splitting them at the
projection would reintroduce, on the surface's side of the seam, exactly the
half-states ADR-0092 §2 made unconstructable on the record's side.

**It also costs the closed graph nothing.** `Attestation` is already inside
ADR-0085 §5's transitive closure: `TurnResult.memories` is
`tuple[MemoryRecord, ...]`, `MemoryRecord` reaches `Provenance`, and `Provenance`
reaches `Attestation` and `ReportedExtent`. The promoted surface already encodes
every one of these types on the wire. So this is a field addition to three models,
not a new type in the graph — which is the argument that makes §3's one genuinely
new type worth scrutinising rather than waved through.

**`Attestation.extent` rides along and nothing renders it, deliberately.** ADR-0117
§2 made that field optional and meaningful in its absence, and no surface has a
rendering rule for it. Projecting the object whole carries it; §4 does not require
it to be rendered and does not forbid it. Splitting the object to leave `extent`
behind would mint a second, near-identical spelling of `Attestation` — the failure
ADR-0106 §2 names when it insists on a function rather than a convention — to avoid
carrying one bounded optional value.

**`Retirement` is the one that gets an object, because it is the one with nothing.**
Its three facts are resolved together by one `MemoryStore.get` in
`orchestration/questions.py`'s `_retirement`, or not at all. Making them one
optional object rather than three separately-nullable fields is ADR-0092 §2's
argument applied a second time: a `Warrant` that exists is always whole — a band, a
predicate answer and, on the attested band, the source and the instant — so the
half-answer that section made unconstructable on `Provenance` is unconstructable
here too.

**What the nesting does not buy is the tie to `content`, and §2 makes that a
producer obligation rather than a validator on purpose.** A validator asserting
`content is None ⟺ warrant is None` would refuse, at the moment it landed, the
`Retirement(record_id=…, content=held.content)` that `orchestration/questions.py`
constructs today — so the contract PR §9 requires to carry no producer could not
carry it, and a later PR adding it would be a second contract change for an
invariant one producer already guarantees. Adversarial review found the ordering on
round 1 and the finding was correct. ADR-0107 §4 is the precedent for the shape of
the answer — "No cross-field invariant is added, and the absence is the decision" —
and the field therefore lands additively with a `None` default, exactly as
`evidence_elided` did.

### 3. The shape question, asked once: a value object where the standing is absent, fields where it is not

> **Normative.** `core/types.py` gains one promoted type, `Warrant`, a frozen model
> with `extra="forbid"`, carrying `band: BeliefBand`,
> `rests_on_recorded_external_content: bool` and `attestation: Attestation | None`.

> **Normative.** A validator on `Warrant` asserts the whole of what the band
> determines, over all three members and not over `attestation` alone:
> `ATTESTED` requires `attestation` set and `rests_on_recorded_external_content`
> `True`; `ASSERTED` requires `attestation` unset and
> `rests_on_recorded_external_content` `False`; `DERIVED` requires `attestation`
> unset and admits either value of the predicate. Any other combination is
> unconstructable.

> **Normative.** No projection that already carries `band` as a top-level field
> gains a nested object carrying `band` again. A projection carries each fact it
> holds in exactly one place.

**This is ADR-0107's "asked once rather than four times", answered, and the answer
is both.** The generator is a single rule: *carry the standing and the origin of
the warrant; make a half-answer unconstructable where the facts arrive together;
and never spell one fact twice on one model.* Applied to a model that already
carries `band` — `Belief`, `BeliefSummary`, `Question` — it yields two additive
fields, because a nested object would give that model two paths to its band which a
careless construction could make disagree. Applied to a model that carries no
standing at all — `Retirement` — it yields one value object, because there the three
facts genuinely are jointly present or jointly absent.

**A reader will ask why the four are not uniform, and the honest answer is that
they do not start uniform.** Three of them already answer "how is this held?" and
one has never answered it. A uniform addition would either duplicate `band` three
times or leave `Retirement` with three separately-nullable fields and a validator
tying them together. The asymmetry is in the models this ADR inherited, and the
rule that generates the two treatments is one rule.

**The band-keyed validator is admissible precisely because `Warrant` is new, and
ADR-0106 §7 is the case that shows why that matters.** That section refused a
band-keyed validator on `Provenance` because "A validator asserting `ATTESTED ⟹
True` would refuse, on *decode*, every attested record `readers.calendar` has
already written — ADR-0086 §3's 'does it refuse something that already worked',
answered yes." `Warrant` has no stored instances, no encoded history and no existing
construction site, so the same test is answered **no**. That is also why §2 declines
to add the equivalent validator to `Belief`, `BeliefSummary` and `Question`: those
are ratified types with construction sites in the tree and in every fixture that
builds one, and a new validator tying a new field to an existing one would refuse
constructions that work today.

**It reaches all three members because a validator over `attestation` alone leaves
the type able to contradict §2, and an earlier draft did exactly that.** That draft
asserted only `attestation` set iff `ATTESTED`, which admits
`Warrant(band=ASSERTED, rests_on_recorded_external_content=True, attestation=None)`
— a user's own assertion reporting that its warrant rests on recorded external
content, which ADR-0106 §2's predicate makes `False` for that band and ADR-0098 §1
forbids in principle, since "the user's own utterance is not [external], however it
was composed". It admits the inverse on `ATTESTED` too. Architecture review found it
on round 1. The repair is the same move ADR-0106 §2 made when it band-guarded its
own predicate rather than trusting a stray flag: the band is the classifier
(ADR-0072 §4), so the validator asserts everything the band determines and leaves
free only what it genuinely does not — the `DERIVED` case, which is the one the
field exists for.

**`rests_on_recorded_external_content` keeps the function's exact name, and the
length is the point.** ADR-0106 §2 rules that "Every consumer asking 'does this rest
on recorded external content?' calls this function; none reads
`derived_from_external` directly for that question", and gives the reason: the
hand-rolled version "is short enough that every consumer will write it and one of
them will write only the second half." A field named for the predicate, carrying the
predicate's answer, is that rule made structural for every client of the wire — a
client can no longer write the half. A shorter name would invite exactly the
question the long one forecloses: *which* externality is this?

**Why the field is carried at all when `band` already implies it for one band.**
For an `ATTESTED` belief the value is `True` and a client could derive it. For a
`DERIVED` belief it is the one fact nothing else on the projection supplies, and it
is the one #746 exists for. Carrying one field whose value is the whole predicate,
rather than a field carrying only the part the band does not cover, is what stops
each client re-deriving the disjunction — and ADR-0106 §2 is explicit that a client
re-deriving it is how the second half gets dropped.

### 4. The named-source tier: what a surface says, and the two things it still may not

> **Normative.** A surface rendering an **attested** belief, question or retirement
> names the reporting source and states the instant that source said the fact was
> current, from the projected `Attestation`. It renders `reported_at` as the
> **source's** clock and never as this system's, and it does not offer
> `last_updated` in its place (ADR-0073 §4).

> **Normative.** A surface renders the source at **source granularity and no
> finer**. ADR-0098 §8's third clause is adopted unchanged: no surface claims to
> identify the author within a source, and a surface that rendered `reported_by` as
> though it named a person would assert what this system does not hold.

> **Normative.** A surface conveys that a warrant came from outside where the
> projected record's band is `DERIVED` and its externality answer is `True` — read
> from `rests_on_recorded_external_content` beside `band` on a `Belief`,
> `BeliefSummary` or `Question`, and from
> `retirement.warrant.rests_on_recorded_external_content` beside
> `retirement.warrant.band` on a `Retirement`. It does **not** present the record's
> own content as third-party text on that ground: the content is a sentence this
> system's model wrote, and ADR-0098 §1 decides externality by the recorded origin
> of the text.

> **Normative.** ADR-0098 §7's first two clauses are unchanged and are now
> satisfiable where they were not. A surface presents a `Retirement`'s `content` as
> third-party content **exactly when** `retirement.warrant` is present and
> `retirement.warrant.band` is `ATTESTED`.

> **Normative.** Where `retirement.warrant` is present and its band is `ASSERTED` or
> `DERIVED`, the `content` is **not** third-party and no surface presents it as such:
> an asserted retirement is the user's own word (ADR-0038 §1a) and a derived one is
> this system's own sentence. The clause above governs the text; the clause before it
> governs the warrant, and neither answers for the other.

> **Normative.** Where `retirement.warrant` is `None` the retired record no longer
> resolves — `content` is `None` too (§2) — and the surface renders it as *no longer
> held* (ADR-0045 §6) and asserts nothing about its band, its origin or its source.
> It renders no third state as `False` and no absence as a value.

> **Normative.** Nothing this ADR adds is an input to anything the **store or the
> engine** ranks, orders or selects on. `beliefs()` and `list_beliefs` stay
> order-neutral and confidence-neutral over these fields, no retrieval ranks on them,
> a band's precedence is unchanged (ADR-0187 §1, §4), and no confidence is adjusted.

> **Normative.** A **client** may style, filter and order the rows it already holds
> by these fields, which is what carrying them structurally is for (#746). Doing so
> changes what that client shows and never what the store returns, and no client may
> present its own ordering as the assistant's judgement of which belief matters more.

**This is ADR-0098 §8's second tier, reached.** The system can now say "your
calendar" and, with §5's label, "your work calendar". It still may never say "Bob",
and the reason is unchanged and is worth restating because the new capability makes
the error tempting: ADR-0093 §7 forbids deriving a reader's identity from the
source's location or contents, so the organiser of an invite and the sender of a
mail are not on the record and cannot be. ADR-0098 §8 states the cost of pretending
otherwise: "Promising the finer attribution and delivering the coarser one is worse
than promising the coarser one, because a user who reads 'someone sent you' will
read the name they are shown as that someone."

**The warrant clause is where ADR-0098 §7's own round-6 mistake would recur, so it is
written as a prohibition rather than as an invitation.** That lane accepted a finding
requiring an externality marker to propagate into the projection, and architecture
review then found the clause "incoherent, against this ADR's own §1", because "A
derived proposal's content is a sentence *our* model wrote; the attacker's text is
nowhere in it." The marker §2 projects is a fact about the *warrant*, and a surface
that read it as a fact about the *text* would misattribute the assistant's own words.
The clause says which one it is.

**And this document made the same mistake one clause later, which is why the
third-party rule is now conditional on the band.** An earlier draft ruled that a
surface "presents [a `Retirement`'s `content`] as third-party content under §7",
without qualification — so a retirement of the user's own assertion would have been
rendered as somebody else's words, and a retirement of this system's own inference
likewise. ADR-0098 §7's first clause is scoped to "every span **its projection
identifies as external**", and once `warrant` carries the retired record's band the
projection identifies exactly one of the three that way. Architecture review found it
on round 3. It is recorded rather than quietly fixed for the reason ADR-0098 §7
records its own: reaching one layer past what the data supports is a property of
writing about this subject, and a paragraph warning about it in the abstract does not
stop the next paragraph doing it.

**Reading the two facts through `warrant` rather than off the `Retirement` is stated
because an earlier draft did not state it.** `Retirement` carries no `band` and no
`rests_on_recorded_external_content` of its own — §2 puts both inside `warrant` — so a
clause naming them bare was not implementable as written. Adversarial review found it
on round 3, and the access path is now spelled in the clauses themselves.

**Splitting the ranking clause in two is a repair, and the draft it repairs said both
things at once.** That draft ruled flatly that "Nothing this section adds is a
ranking, ordering or filtering input" while the Consequences promised a client could
"style, filter and order" on the new fields — and architecture review found on round 4
that an implementing surface cannot satisfy both. The two halves are genuinely
different questions and the corpus already separates them: ADR-0107 §9 declines
"Making `beliefs()` or `list_beliefs` order or filter on the count" on ADR-0077 §6's
ground that "a number computed at presentation cannot reorder a store it never
touches", which is a rule about the *store*. What a client does with a page it is
holding is the presentation side of the same sentence, and it is the whole point of
#746's complaint that a surface "cannot style it, filter on it, or order by it". So
the store-side prohibition stands unweakened and the client-side permission is stated
rather than left to collide with it.

**What the two live surfaces owe changes, and both currently say they cannot.**
`interfaces/cli.py`'s `_why` and `interfaces/gateway/assets/app.js`'s `whyHeld` each tell the
user the source was recorded and cannot be shown. Under §2 it can be. Rewriting
those two sentences is §9's obligation on the implementing lane, and closing #1276
is what it amounts to.

### 5. The display label renders, and it comes to rest nowhere

> **Normative.** A **display label** is a human-facing name for one configured
> source instance. It is never stored on a memory record, never written to
> `Provenance`, never carried in `export`, and never written to a log. ADR-0093 §7's
> prohibition on a configurable value reaching a record's identity is unchanged and
> is not narrowed by this section.

> **Normative.** A surface renders the display label where one exists for the source
> and falls back to `Attestation.reported_by` where none does. This is ADR-0093 §7's
> own fallback — "a surface with no label falls back to `reported_by`" — adopted
> unchanged.

> **Normative.** Where a label is carried to a client at all, it is carried
> **transiently** and settles nowhere: not on a `Belief`, a `Question`, a
> `Retirement` or a `Warrant`, not in a grant listing, not in `export`. Which
> response carries it, and whether one carries it at all before the registry exists,
> is the surface lane's to decide (§8, §9).

> **Normative.** No label is a source identity, and no component joins on one. Every
> join keyed on a source — ADR-0097 §1's grant key, ADR-0102 §4's admission,
> `Attestation.reported_by` — is keyed on the identity and on nothing else.

**The split between identity and label is the whole of what makes a label safe, and
ADR-0093 §7 already worked out why.** A label is the thing a user writes, and "A
free-text setting is precisely the mechanism by which a user would put their email
address or a path there, and no validator can tell a chosen label from a personal
one." An identity that lands in `Provenance`, in every export and in every log line
therefore cannot be user-authored — which §6 keeps — and a value that *is*
user-authored therefore cannot land in any of those, which this section rules.

**The shape is ADR-0097 §9a's, transplanted, and the transplant is exact.** That
section had the same problem with the configured location: the user needs to see it
to act, and it must not settle. Its answer was to state the obligation "over the
property rather than over an operation", ruling *that* the user sees it and *that*
it comes to rest nowhere while leaving the carrying shape to the surface ADR. The
same division applies here for the same reason, and adopting it rather than
inventing a second one keeps one rule in the corpus for one hazard.

**This ADR does not build the label's configuration, and §8 says why.** What it
rules is that the label is a rendering-time resolution against the identity, never a
value on a record — which is the decision that has to exist *before* anyone
configures one, because it is the decision a configuration mechanism could
irreversibly get wrong.

### 6. The named source is a **configured source**, and its identity is minted, durable and not re-used

> **Normative.** A source identity names **one configured source** — one entry in a
> deployment's configuration for a reader type, with its own backing location — and
> not a reader class, not a backing location, and **not a `Reader` object**. Every
> `Reader` object the composition root builds to serve one configured source carries
> that one identity.

> **Normative.** ADR-0093 §7's two properties are unchanged and bind every identity:
> it is a stable Tier 2 value, and it is **never derived from the source's location
> or contents**. A path, filename, address or account identifier may not be used as
> one, or as any part of one.

> **Normative.** An identity is **assigned once**, when its source is first
> configured, and **never changes** — not across restarts, not when the source's
> backing location is repointed, and not when another source of the same type is
> configured beside it. The **first** source of a reader type a deployment
> configures may hold that type's bare declared name — `"calendar"`, `"email"` —
> and a deployment that has assigned that bare name has spent it.

> **Normative.** Every source of a reader type configured **after** that one carries
> a **discriminator**: a value **minted** by the deployment, drawn uniformly from a
> fixed-width closed alphabet — 128 bits, rendered as 32 lowercase hexadecimal
> characters — carrying no information about the source it names, and refused by
> every admitting seam if it is not of that form.

> **Normative.** No component re-uses an identity. Retiring a configured source does
> not release its identity for a later one, and no deployment re-assigns a bare
> declared name it has spent. **This is a rule about assignment and not a uniqueness
> proof**: a fresh draw equal to a retired identity is not excluded by it, and §12
> defers that residual.

> **Normative.** The seam is `Reader.name` and there is no other. ADR-0097 §1 rules
> that "A grant's subject is a **reader's declared identity** — the value
> `Reader.name` returns, which `SourceReading.source` equals … and which reaches a
> stored belief as `Attestation.reported_by`", and "keys on nothing else". No lane
> may satisfy this section by adding an instance-identity value beside `Reader`.

> **Normative.** **Nothing in this ADR permits a discriminated identity to be
> built.** ADR-0093 §7 rules that a sensor's identity "is **declared by the sensor**
> and is not a configurable value", and a minted discriminator reaching `Reader.name`
> from a deployment's configuration is a change to what §7 decided — a **partial
> supersession** under ADR-0070 §1, not an amendment, because a reader holding §7
> would refuse what this section describes. This ADR does not make it, and no lane
> reads this section as having made it. §12 defers that act with the properties above
> as its specification.

> **Normative.** ADR-0097 §9's canonicality rule is unchanged and reaches a
> discriminated identity exactly as it reaches a bare one: a source whose identity is
> not equal to its own `str.strip()` is not grantable.

**The unit is the configured source and not the reader object, and the tree is why
that distinction had to be found rather than assumed.** `app/composition.py` builds
**three** `CalendarReader` objects for one configured calendar — `facet_reader`,
`ingestion_reader`, `upcoming_reader` — and **two** `EmailReader` objects for one
configured mailbox, deliberately, because ADR-0140 §13 requires each consumer its
own instance and a shared one makes "a running scheduled ingest make the
request-path facet raise `ReaderError` and vanish". `_held_sources` pairs those
copies back into one source each. An identity keyed on the reader *object* would
make one configured calendar three independently grantable sources, which is a
worse answer than the one this ADR set out to improve on.

**Assign-once-and-never-change is what keeps the first source's grant, and an
earlier draft broke exactly that.** That draft made the discriminator a property of
*being one of several* — every source of a type carried one once a second existed —
so configuring a second calendar would have re-identified the first, orphaning the
grant the user had already made over it. Adversarial review found it on round 2 and
the finding was correct. Keying the rule on **when a source was configured** rather
than on **how many now exist** removes the retroactive move entirely: the bare name
belongs to the source that took it, permanently, and a later source of the same type
takes a discriminated one.

**Durability is not decoration, and it is the clause a lane would drop first.** A
re-assigned identity orphans every record whose `Attestation.reported_by` names the
old one and every grant keyed on it — the belief surface would name a source that no
longer exists, and the read gate would find no live grant for a source the user
granted. That is why an identity is assigned at configuration and not per process.

**The fixed form is what closes the hazard ADR-0093 §7 names, and it is why a
discriminator is arguable at all.** §7 chose a declared constant over a setting
because "A free-text setting is precisely the mechanism by which a user would put
their email address or a path there, **and no validator can tell a chosen label from
a personal one**". A validator *can* tell 32 hexadecimal characters from an email
address, so the hazard is closed by the shape of the value rather than by a rule
about what may be typed into it. That is the same *kind* of answer §7 gave — "A
declared constant cannot carry personal data at all, which is a property rather than
a rule" — reached by a different route, because a class constant, being the same for
every object of its class, is the one thing a discriminator cannot be. It is an
argument for what §7 should become, **not** a reading under which §7 already permits
it; the clause above says so, and §12 carries it to the lane that may act on it.

**"Not re-used" rests on the mint's arithmetic, and that is a probabilistic property
rather than a bookkeeping guarantee.** An earlier draft ruled that no composition
root assigns an identity the deployment "has ever held", which needs a durable record
of every retired identity — machinery §8 declines to build — and then called an
accidental collision "unreachable", which a uniform draw does not make it. Both
reviewers found the first on round 1 and both found the second on round 2, and both
were right each time. What is true is narrower: a 128-bit uniform draw collides with a
given retired identity with probability 2⁻¹²⁸, which is the **same assumption the
grant store already rests on, with more margin** — `app/composition.py`'s `_uuid`
mints every `SourceGrant`'s id from `uuid.uuid4()`, 122 random bits, under ADR-0021
§3 and ADR-0102 §5, and a collision *there* would make two grant records one, in an
append-only store whose premise is that its records are not fabricated. This ADR adds
no new assumption and asks for six fewer bits of luck than the store it writes into;
what it declines to do is call the existing assumption a certainty.

**What that leaves, stated rather than papered over.** Two residuals, and neither is
closed by anything above. A *collision* would let a new source inherit a retired
one's grant, at the probability just named. And a deployment that **deliberately**
re-installs a retired identity — pasting the old value into a new source's
configuration — transfers the grant that stood over it, and no rule available here
prevents that. The exposure of the second is bounded exactly as ADR-0097 §9a bounds
its own: "on the deployment this system is built for, the operator and the user are
the same person", so it is that person editing their own configuration file, not a
third party substituting a source beneath them. §12 defers both, with the condition
that makes each matter. **Neither residual is load-bearing for §7's discharge**, and
§7's last clause says why.

**The bare name survives for the source that took it, and that is what makes this
migration free.** Every attested record in every deployment carries
`reported_by="calendar"` or `reported_by="email"`; every grant carries the same
values as `source`. Under the assign-once clause those identities keep naming exactly
the source they have always named, so no record is rewritten, no grant is re-keyed,
and nothing that worked stops working — ADR-0086 §3's admissibility test answered
"no" on both stores. The asymmetry between a bare identity and a discriminated one is
a fact about when each was assigned, and ADR-0184 is the corpus's ruling that a value
recorded before a distinction existed is legible history rather than a defect to
backfill.

**This section is ruled ahead of its trigger, and ADR-0107 is the precedent for
doing so.** ADR-0093 §11's condition has not fired (Context). ADR-0107 decided the
elision's surface before its own trigger fired, under a section titled "Why this is
worth deciding before the trigger fires", on the ground that the moment a decision
becomes necessary is the moment it becomes expensive to get wrong. The case here is
stronger: ADR-0097 §9a makes the absence of a *rule* a gate on a capability, so
leaving it unwritten does not defer a decision, it forbids a feature. What is paid
for deciding early is stated at the last clause but one: this ADR specifies the
identity and does **not** authorise it, because authorising it means partially
superseding ADR-0093 §7 with no second source in hand to check the choice against —
the widening ADR-0073 §4 declined in its own words, "not one to guess here".

### 7. What a live grant does when identity or location changes — ADR-0097 §9a's gate discharged, and the second gate this ADR found

> **Normative.** Repointing a configured source at a different backing location does
> **not** change its identity, and a live grant over that identity **stands**. This
> is ADR-0097 §9a's stated behaviour, ratified here as the rule rather than recorded
> there as an open consequence.

> **Normative.** A grant authorises the configured source its identity names and no
> other. A grant that outlives its source is history and authorises nothing, which is
> ADR-0097 §9's existing ruling that "A grant whose reader later disappears is not a
> defect", unchanged.

> **Normative.** Configuring a second source of a type changes neither the first
> source's identity nor any grant over it. Nothing about a shared reader type is
> inherited, and no grant widens because a second source of that type now exists.

> **Normative.** ADR-0097 §9a's disclosure obligation is unchanged and now binds per
> configured source: the grant surface makes that source's **current configured
> location** available to the user transiently at the moment of granting, and that
> location comes to rest nowhere. No client describes a grant as covering a
> particular file (ADR-0097 §9a).

> **Normative.** ADR-0097 §9a's precondition — "the rule for what a live grant does
> when its source's identity or backing location changes" — is **discharged** by the
> four clauses above, and by them alone. The discharge does not rest on §6's mint, on
> any claim about collisions, or on any machinery: §9a gates a second source's
> grantability on a **rule existing**, and the rule is the text above.

> **Normative.** **Discharging §9a does not make a second source grantable**, and no
> lane may read it as having done so. A second configured source of one reader type
> needs a discriminated identity, §6's last clause but one rules that this ADR does
> not authorise one, and until an ADR partially supersedes ADR-0093 §7 there is no
> second identity for a grant to name. When there is, its grantability is decided by
> ADR-0097 §9 and ADR-0102 §4 exactly as a first source's is, over `Reader.name`.

**Lifting a gate is not the same as building what it gated, and the distinction is
the whole of why this fits in one ADR.** §9a's precondition is written over "the
rule", and a rule is a text. The registry, the label's configuration, and the engine
operations that would let a user *see* two sources are separate work with their own
triggers (§8). What the gate stops is a second source becoming grantable while the
question "whose grant is this now?" has no answer. It has one above.

**Two gates stood in front of a second source, the corpus recorded one of them, and
this ADR found the other.** ADR-0097 §9a's is the recorded one and is discharged
here. ADR-0093 §7's non-configurable-identity clause is the unrecorded one: no ADR
names it as blocking a second source, and it does, because a second source needs an
identity §7's clause forbids assembling. Discharging one gate while another stands is
not a half-measure — it is the accurate state of the corpus, and stating it is worth
more than a discharge that reads as a clearance. §12 carries the second gate with the
specification an ADR closing it would implement.

**The collision and re-installation residuals are deliberately not load-bearing
here.** An earlier draft made this section's second clause depend on §6's mint never
colliding, which both reviewers correctly refused on round 2: a probabilistic property
cannot carry an absolute "and no other". The clause above is now about what a grant
*names*, which is true whatever the mint does, and the residuals live where they
belong — as §6's stated limits and §12's deferrals, bounded by ADR-0097 §9a's own
single-user ground.

**Revocation is untouched and stays prospective.** ADR-0097 §6 rules that revoking
stops the reading and does not unwrite the beliefs. Per-source identities change
nothing about that except that a revocation is now as narrow as the source it names,
which is the improvement rather than a new question.

### 8. What stays deferred: the registry, the label's configuration, and the surface that shows two

> **Normative.** The **source registry** stays deferred, with ADR-0093 §11's trigger
> unchanged and unfired. This ADR rules the properties a source identity must have
> (§6) and the rule a live grant follows (§7); it builds no registry, adds no
> list-valued or mapping-valued source configuration, and no lane may read it as
> having done either — ADR-0142 §8's clause is unchanged and still governs.

> **Normative.** ADR-0102 §10's obligation on the registry lane — a re-derivation of
> `grantable_sources`' worst case over the whole `GrantableSource` graph, in the same
> change — is unchanged and still owed by that lane. This ADR adds nothing to that
> graph and does not discharge it.

> **Normative.** **Where a display label is configured, and by what mechanism**, is
> the registry lane's. §5 rules what a label may never be and where it may never
> settle; a lane that adds one inherits both clauses and adds its own storage
> argument.

> **Normative.** **The client surface for more than one configured source** — how a
> user distinguishes two mailboxes when granting, listing or revoking — is the grant
> surface's (ADR-0102), on ADR-0084 §5's step-1/step-2 split. This ADR adds no
> `AssistantEngine` method and changes no signature.

**The trigger is restated by reference rather than paraphrased, because the corpus
does not agree with itself about what it says.** ADR-0093 §7 states it twice as "a
second instance of one source type"; §11's own first phrase says "§7 revisits at the
third source"; and ADR-0142 §8 reads §11 as one entry in which "the registry *and*
its configurable display label *and* its instance-distinguishing `reported_by` all
fire together" at the third source. Under every one of the three readings the trigger
is **unfired** on this tree — two source types, one configured source each — which is
why this ADR can note the divergence without having to settle it. Settling it is
ADR-0093's own lane's, and §12 records it.

**Naming what is not built is load-bearing here because §6 and §7 read like a
registry if they are skimmed.** They are not one. They are the two texts ADR-0097 §9a
and ADR-0093 §11 each said had to exist before a second source of one type could be
granted, and nothing more — which is precisely the scope that lets this ADR decide
ahead of a trigger without guessing at a shape it has no producer for.

### 9. What the implementing lanes owe

> **Normative.** The contract lane lands §2's and §3's `core/types.py` surface —
> three field pairs, one new `Warrant` type with §3's band validator, and
> `Retirement.warrant` — as its own PR ahead of any consumer, with no producer and
> no surface change in it (golden rule 5, ADR-0015). Every field it adds is
> additive with a default, so that PR leaves every construction site in the tree
> compiling and passing unchanged.

> **Normative.** That lane bumps `PROTOCOL_VERSION`. Every one of these models is
> wire-carried and declares `extra="forbid"`, so a new hub's `Belief` is refused by
> an old client's decoder: ADR-0124 §9's second limb, "a change to a wire-carried
> `core` type that makes a value one peer emits invalid for the other, whether the
> change widens or narrows the type", is engaged in the direction that bites.

> **Normative.** The projection lane populates the new fields at the four sites that
> build them — `belief_from_record` and `belief_summary_from_record` in
> `orchestration/engine.py`, `_project` and `_retirement` in
> `orchestration/questions.py` — reading `rests_on_recorded_external_content`
> (ADR-0106 §2) and never `Provenance.derived_from_external`. It carries §2's
> producer obligation on `Retirement`: `warrant` is set exactly when `content` is.

> **Normative.** The surface lane rewrites the attested explanation on both live
> surfaces — `_why` in `interfaces/cli.py` and `whyHeld` in
> `interfaces/gateway/assets/app.js` — so that each names the source and the report
> instant under §4, and neither continues to state that it cannot show them. It
> renders a retirement under §4's three retirement clauses, taking all three arms —
> attested, asserted-or-derived, and no longer held — at `_render_retirements` in
> `interfaces/cli.py` and `renderRetirements` in
> `interfaces/gateway/assets/app.js`. Its tests assert the rendering, not only that a
> field is present.

> **Normative.** The same lane renders an **attested question** under §4's first
> clause, at `_render_question` in `interfaces/cli.py` and `renderQuestion` in
> `interfaces/gateway/assets/app.js`. §4 binds every surface that renders an attested
> belief, question or retirement, and a question is the projection the first attested
> proposals actually reach; a lane that updated only the belief explanation would
> leave the surface §4 was written for unchanged.

> **Normative.** The surface lane ships, for **each of the six rendering paths the
> two clauses above name** — `_why`, `_render_retirements` and `_render_question` in
> `interfaces/cli.py`, and `whyHeld`, `renderRetirements` and `renderQuestion` in
> `interfaces/gateway/assets/app.js` — a test over an **attested, resolved** subject
> asserting that **both** `reported_by` and `reported_at` reach the rendered output.
> A test asserting only that a field is populated, or only that the source is named,
> does not satisfy it.

> **Normative.** For the **two retirement paths** of those six, the surface lane
> additionally ships a test over an **unresolved** retirement — `warrant` and
> `content` both `None` — asserting that the output renders *no longer held* and
> states no band, no origin and no source.

**The matrix is enumerated rather than counted, because a numeral in it went stale
inside one round.** An earlier draft said "those four rendering paths" when the two
clauses above named four; the round-4 repair added the two question renderers without
moving the numeral, and on round 5 the two lenses read the surviving "four" as two
*different* sets of four — adversarial as belief-plus-question, architecture as
belief-plus-retirement — each correctly reporting that the paths it thought were
excluded could regress with every required test still passing. Both were right about
the gap and neither was right about which paths it covered, which is what a counted
list buys and an enumerated one does not.

**The tombstone arm is a second test rather than a clause of the first, because the
state a single test would have named cannot exist.** An earlier draft asked for "a
test over an attested retirement whose retired record no longer resolves", and §2
makes `warrant` and `content` `None` together for exactly that record — so an
unresolved retirement is in no band, carries
no attestation, and there is no attested tombstone to construct. Adversarial review
found it on round 5. The attribution arm and the tombstone arm are different subjects
and get a test each.

> **Normative.** Every value these fields carry is inserted into a surface's output
> as **data**, neutralised for that target on render (ADR-0042 §4, ADR-0098 §7's
> second clause). A source identity is a value this system declared and a
> `reported_at` is an instant, but a `Retirement.content` is not, and the surface
> that renders the two together neutralises both.

> **Normative.** The **surface** lane, for **each** rendering target that presents a
> retirement, ships a test that builds a question whose `retires` names an attested
> record whose `content` carries that target's own syntax, and asserts that the
> rendered attribution of every span is unchanged by it. This is ADR-0098 §9's marked
> test obligation read one projection over, and a test asserting only that a source
> name appears does not satisfy it.

**The `reported_at` half is the one an implementing lane will drop, because the
source-naming half is the one everybody is talking about.** ADR-0073 §4's gate asks
for both and its floor forbids substituting our clock for the source's — the exact
error the current CLI sentence exists to avoid making. A lane that names the source
and leaves "Last revised" as the only instant has met §8's second clause and breached
§4's gate.

**The rendering-security test sits on the surface lane and not the projection lane,
and an earlier draft had it on the wrong one.** That draft asked the projection lane
to assert "the rendered attribution of every span" — output that lane does not
produce, since the surfaces are still unchanged when it lands, so the test could only
have been made to pass by moving a surface into a lane §9 fences to `orchestration/`.
Adversarial review found it on round 4. It is per rendering target rather than once
because ADR-0042 §4's division is per target — "the engine carries the value verbatim,
the adapter escapes for its target" — so a terminal's syntax and a browser's are two
different tests of one clause.

### 10. What this ADR does not decide

- **The sensitivity tier of a source, and what a crafted entry can do to a parser.**
  #641's remaining three questions — the adversary at the seam, whether ADR-0093 §4's
  "`sensitivity` chosen for what the source holds" survives a public feed, and
  `.ics`/mail parsing hardening — are a sibling decision with #641's own trigger
  ("before a reader is pointed at a co-located fetcher's output"), routed there by
  ADR-0181 §9 and untouched here. Naming a source on a surface is not a statement
  about what that source is allowed to hold.
- **Whether a tainted belief may parameterise an egress or actuation.** ADR-0106
  §12's third bullet, firing with the first actuator, in that lane's ADR.
  ADR-0181's egress-side fact stays a boolean about a call and gains no source name
  from this ADR.
- **Whether an `ATTESTED` or `ASSERTED` belief's line should render a citation count,
  and an elision ceiling with it.** ADR-0107 §10 left it to "the lane holding leg 6's
  first `EXTERNAL` producer". This ADR holds a projection, not a producer, and adds no
  count to either band's line.
- **`Attestation.extent`'s rendering.** Carried by §2, rendered by nothing, and
  ADR-0117's to decide.
- **Retracting an attested belief when its source stops reporting it**, ADR-0093 §11's
  own deferral, which naming the source makes more legible and no more tractable.
- **A per-span externality marker.** ADR-0181 §2's third clause forbids one being
  added on the strength of that section, and nothing here supplies the ground either:
  ADR-0098 §5 establishes the link is unrecoverable once a model's output is recorded
  truthfully.
- **`MemoryStore`, `MemoryWriter`, `Reader` or `AssistantEngine` signatures.** No
  Protocol changes of any kind. §6 names `Reader.name` as the only seam a
  discriminated identity could use (ADR-0097 §1) and then declines to authorise one,
  so nothing in this ADR changes what `Reader.name` returns today, what
  `ReaderContract` requires of it, or what the shared conformance suite (ADR-0095 §3)
  asserts about it. The lane that takes §12's partial supersession decides all three.
- **Whether one configured source may be served by readers declaring different
  identities.** §6 rules the opposite — every reader object serving one configured
  source carries that source's one identity — and rules nothing about how a
  composition root arranges that, which is `app/`'s and is not a contract question.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in this ADR's own text, clause by clause, against
ADR-0070 §1's test: would a reader holding only the earlier ADR be misled? The answer
is that **no earlier ADR's status line changes**. The four places where the opposite
reading is available:

- **ADR-0098 §8's second clause** is **discharged**, not narrowed. It named the ADR
  that would discharge it — "the ADR that next revises the projection carrying a
  belief to an inspection surface" — and this is that ADR. A reader holding ADR-0098
  alone reads a live obligation with a named owner, which is true until this merges
  and is the state that ADR's §12 describes. Discharging an obligation on the terms it
  set is not amending it.
- **ADR-0073 §4's `ATTESTED` gate** is **met**, on the terms it set: both halves, at
  the surface, with a producer in hand. §4's own text anticipated that "whether that
  needs `Provenance` to grow fields is a `core` decision for that lane" — ADR-0092 §1
  took the record half, this ADR takes the projection half, and neither re-decides
  what §4 asks for.
- **ADR-0093 §7 and §11** are **not amended, and §6's last clause is what keeps that
  true.** §7's two surviving properties — a stable Tier 2 value, never derived from
  the source's location or contents — are adopted verbatim (§6), and its label
  fallback is adopted verbatim (§5). §11's registry deferral stands with its trigger
  unfired (§8).

  **The clause a discriminator would engage is §7's "declared by the sensor and is
  not a configurable value", and this ADR stops short of engaging it — after two
  rounds of being pushed from both sides.** Architecture review raised on round 1
  that a composition-root-minted discriminator returned from `Reader.name` would be
  neither a reader-declared constant nor the existing Protocol semantics, so a §11
  claiming ADR-0093 unamended would be false. That draft was answered by deferring
  *which seam* carried the identity — and on round 2 the same lens showed that the
  deferral is not available either, because **ADR-0097 §1 already fixes the seam**:
  "A grant's subject is a **reader's declared identity** — the value `Reader.name`
  returns … A grant keys on nothing else." Both findings were correct, and together
  they close the space: there is one seam, and putting a minted value into it is a
  change to what ADR-0093 §7 decided.

  **So the honest classification is that a discriminated identity is a partial
  supersession of ADR-0093 §7, and this ADR does not make it.** Under ADR-0070 §1's
  test a reader holding §7 would refuse to give a second configured calendar its own
  identity, and after such an ADR they would not — they act differently, so it is a
  supersession and not an amendment, and it is partial, since everything else §7
  decides stands. Making it means editing ADR-0093's Status line, which is a decision
  about another ADR's document taken with **no second source in hand** to check the
  choice against. §6's clause therefore *specifies* the identity and refuses to
  authorise it, and §12 carries the supersession as the one act still owed. A reader
  holding ADR-0093 alone reads that an instance-distinguishing `reported_by` awaits a
  later lane and that a sensor's identity is not configurable; **both stay exactly
  true after this ADR**, which is the whole of what §11's test asks.

  **What §6 does add is the specification a discriminator must meet** — a question §7
  left live by name, "at the point where it acquires a subject" — and writing the
  specification for a deferral that named its own successor is not a change to what
  §7 decided.
- **ADR-0097 §9a's precondition** is **discharged** (§7), in the form it specified —
  "the rule for what a live grant does when its source's identity or backing location
  changes". §9a's other clauses, including the prohibition on describing a grant as
  covering a particular file, are adopted unchanged.

Nothing is owed against **ADR-0107**. It was the next reviser of the belief
projections after ADR-0098 §8's second clause was written, and it declined this
question explicitly in its §10 rather than passing it silently — and it did so before
ADR-0098 §12's own trigger fired, since ADR-0107 is dated 2026-08-05 and
`readers/email.py` landed with ADR-0140 on 2026-08-12. Its §3 stands unamended; this
ADR adds fields beside `evidence_elided` and changes nothing about it.

Nothing is owed against **ADR-0106**. Its §2's closing clause — "The field carries no
`Attestation` and names no source. Which source a derived belief traces to is
ADR-0098 §8's second clause, undischarged there and not discharged here" — stays true
of ADR-0106. §2 of this ADR projects the *predicate's* answer, which is what ADR-0106
§2 built the predicate for, and adds no source name to `Provenance`.

Under ADR-0070 §1 this is a **new decision** on ground four earlier ADRs each declared
to be someone else's, not an amendment to any of them.

### 12. Deferred, by name, each with the condition that fires it

- **The source registry**, with ADR-0102 §10's re-derivation of `grantable_sources`'
  worst case riding on it. ADR-0093 §11's, trigger unchanged and unfired under every
  one of the corpus's three phrasings of it (§8).
- **Which of those three phrasings ADR-0093 §11's trigger actually has.** §7 says "a
  second instance of one source type" twice, §11's own first phrase says "the third
  source", and ADR-0142 §8 reads all three of §11's items as firing together at the
  third source. Nothing turns on it while none of them is met; it is ADR-0093's lane's
  to settle, and it **fires with whichever of the three arrives first**.
- **The partial supersession of ADR-0093 §7's non-configurable-identity clause**,
  without which no second source of one reader type can have an identity and none can
  therefore be granted (§7's last clause). §6 is its specification: the seam is
  `Reader.name` (ADR-0097 §1), the first-configured source keeps the bare declared
  name, every later one carries a 128-bit fixed-form minted discriminator, and
  identities are assigned once and not re-used. It is a **small, fully-specified ADR
  lane** — one clause of one ADR, one Status line — and it **fires with the first
  deployment that wants a second source of one type**, or with whichever of §11's
  three trigger phrasings arrives first.
- **A collision between a minted identity and a retired one**, which would let a new
  source inherit the retired one's grant at probability 2⁻¹²⁸. Closing it needs the
  durable allocation history §8 declines to build; it **fires with the registry**,
  which is the first thing that would hold one anyway.
- **A deliberate re-installation of a retired identity.** §6's mint cannot stop an
  operator pasting an old identity into a new source's configuration. The exposure is
  bounded by ADR-0097 §9a's own ground — the operator and the user are the same
  person — and it **fires with the same condition §9a's does**: when those two roles
  diverge, which is the multi-user case ADR-0097 §12 already defers.
- **Where a display label is configured and which response carries it.** Fires with
  the registry, or with the first lane that gives a user two sources to tell apart.
  §5 binds it in advance on the two points that cannot be got wrong later.
- **The client surface for more than one configured source** — granting, listing and
  revoking across two mailboxes. ADR-0102's, on ADR-0084 §5's split. Fires with the
  first deployment that configures a second one.
- **A citation count, and an elision ceiling, on the `ATTESTED` line.** ADR-0073 §4's
  own `ATTESTED` gate and ADR-0107 §10's; fires with the lane that holds the evidence
  to answer it.
- **`Attestation.extent`'s rendering.** ADR-0117's; fires with the first surface that
  has a use for a reported entry's position in its source's own world.
- **The reader-side adversary model and the source's sensitivity tier.** #641's
  remaining three questions, with that issue's own trigger, routed by ADR-0181 §9.
- **Whether a tainted belief may parameterise an egress.** ADR-0106 §12's; fires with
  the first actuator.

## Consequences

**What becomes easier.** The one screen whose job is "why do you believe that?"
answers it for the attested band for the first time since that band acquired a
producer: a user reading a belief can see *which* connected source reported it and
*when that source said so*, instead of a sentence explaining that the system knows
both and cannot show them. A question that would retire an attacker-authorable
calendar line renders that line as somebody else's words, which is the surface
ADR-0098 §7 exists for and the one it could not reach. A client can style, filter and
order the page it holds on a warrant that came from outside instead of parsing a
sentence for it, while the store it drew that page from stays as order-neutral as it
was (§4). And a
second mailbox stops being an open design question and becomes a specified one: the
grant rule ADR-0097 §9a gated it on exists, and what remains between here and a
second source is one clause of one ADR, named and written out.

**What becomes harder.** Four projections grow, three of them on the largest response
this surface produces. ADR-0085 §8f's arithmetic absorbs it — the listing's bound is
"fifty beliefs' own `content` plus a handful of scalars each", and an `Attestation` is
a handful of scalars, not a new product term — but the handful is now larger and the
belief page's worst case grew again. `PROTOCOL_VERSION` moves, so every hub and every
client upgrade together, which is the cost ADR-0124 §9 makes deliberate rather than
silent. The corpus gains a promoted type, `Warrant`, used by exactly one projection.
And every surface that renders an attested belief now owes two facts where it owed
none, so a surface that renders one of them is newly capable of a specific error —
naming the source while still showing our clock as the source's.

**What is paid for deciding §6 and §7 ahead of their trigger, and what is
deliberately not paid.** No second configured source exists, so nothing checks the
identity against a real one. §6 therefore *specifies* it — Tier 2, assigned once,
fixed-form, minted, not re-used, on `Reader.name` — and stops there, leaving the act
that authorises it to the lane that has a second source in hand. That is the same
division ADR-0097 §9a used when it ruled that a location must be shown and must not
settle while leaving the carrying shape to the surface ADR, and it means a later lane
that finds the specification unsatisfiable supersedes §6 with evidence this ADR could
not have. What is **not** paid is any claim this ADR cannot keep: it builds no
allocation ledger, no registry and no `Reader` contract change, and it does not
pretend a second source is grantable when a clause of ADR-0093 §7 still says it is
not.

**What would trigger revisiting this.** Three things, named so a later lane does not
have to derive them. If a third source type arrives, ADR-0093 §7's own revisit fires
and the registry takes §5's label and §6's discriminator together. If a projection
ever needs to say something about *part* of its content rather than the record as a
whole — a rationale quoting one source among several — §1's rule is stated over the
record and would need a per-span answer, which ADR-0181 §2's third clause and
ADR-0098 §5 currently make unobtainable. And if `Warrant` acquires a second consumer,
the asymmetry §3 rules between it and the three band-carrying projections is worth
re-testing against the models as they then stand rather than as they are here.

## Alternatives considered

**Name the source in prose and add no field.** ADR-0106 §6 already discharges the
substance of #746 through `MemoryDecision.reason`, and the same channel could carry
"your calendar said so on Monday". It is the cheapest option and it fails on
ADR-0106 §12's own account of what a sentence cannot do — style, filter, refuse to
render as the assistant's own inference — and on ADR-0073 §4, which addresses the
surface's fields by name. It also leaves every client parsing English for a fact the
store holds structurally.

**Add the fields one issue at a time.** #673, #1276 and #746 are three issues and
could be three PRs. Refused because ADR-0106 §12 rules it the wrong order of work in
as many words, and because ADR-0098 §7 records what happened the last time this class
was answered one field at a time: four rounds of whack-a-mole and a clause that had to
be rewritten over the class in the end. Three separate lanes would also each have to
answer ADR-0107's scalars-versus-object question independently, and would answer it
three ways.

**Carry `reported_by` alone and leave `reported_at` behind.** It satisfies ADR-0098
§8's second clause exactly, is one field rather than an object, and is what #1431 asks
for. Refused on ADR-0073 §4, whose gate is explicitly **both** halves, and on ADR-0092
§2, whose half-state argument is precisely that a source without its instant renders
"your calendar had this as of …" with a blank.

**One nested provenance object on all four projections.** The tidiest-looking answer
and the one ADR-0107's Consequences invites. Refused in §3: three of the four already
carry `band` at top level, so a nested object carrying `band` would give one model two
paths to one fact, and the two can be made to disagree by a careless projection. A
nested object *without* `band` would leave `Retirement` — the only projection with no
standing at all — needing `band` beside it and back to separately-nullable fields.

**Give `Belief`, `BeliefSummary` and `Question` an `attested ⟹ attestation` validator
too, for symmetry with `Warrant`.** Refused on ADR-0086 §3's admissibility test, which
ADR-0106 §7 applied to the same shape one type over: those three are ratified types
with construction sites in the tree, and a validator tying a new field to an existing
one refuses constructions that work today. `Warrant` is new and refuses nothing.

**Key a grant to the backing location instead of the identity, so that repointing
revokes it.** It removes the hazard §7 rules over, rather than ruling over it.
Refused twice by ADR-0097 §9a and refused again here for the same two reasons: a path
on the record is the Tier 1 leak the identity rule exists to prevent, and a digest of
the path avoids the leak by inventing an instance identity through a field — which is
the question §6 answers openly instead.

**Require a durable allocation ledger — every identity a deployment has ever held,
kept so that none is ever re-issued.** It is what an unqualified "never re-used"
needs, and both reviewers correctly pointed out on rounds 1 and 2 that the draft
obliged one without ruling one and then over-claimed what a mint alone delivers.
Refused rather than adopted: a ledger is durable hub-side state with an owner, a
lifecycle, an export story and a retention rule — the schema decision ADR-0142 §8
says two sources do not buy — while §6's mint reaches the same outcome at 2⁻¹²⁸ with
no store at all, on the assumption the grant store's own ids already rest on. The
residual is stated at §6 and deferred at §12 rather than bought here.

**Put the minted discriminator into `Reader.name` and record the ADR-0093 §7
supersession in this ADR.** The route ADR-0097 §1 leaves as the only one, and the one
the closing lane will take. Refused **for this ADR** on two grounds, and the first is
the substantive one: choosing it means partially superseding a ratified clause with
no second source in hand to check the choice against, which is the widening ADR-0073
§4 declined in its own words — "not one to guess here" — and which ADR-0107 §10
declined again for the same reason one type over. The second is procedural and is
recorded rather than hidden: this lane's fence is this ADR's own file, and a partial
supersession edits ADR-0093's Status line (ADR-0070 §1). Either ground alone would
defer it; §12 specifies it completely enough that the lane taking it writes a Status
line and a short argument rather than a fresh decision.

**Leave §6 and §7 out and ship the projection alone.** Defensible: ADR-0093 §11's
trigger has not fired, and ADR-0045 §1 and ADR-0028 §7 both rule that a field with no
consumer is surface. Refused because §6 and §7 add no field and no surface — they add
two texts — and because the absence of one of those texts is not a deferral but a
**gate**: ADR-0097 §9a forbids a second configured source becoming grantable until
the rule exists. Deferring here would keep a capability locked on the absence of a
paragraph. And the second gate §7 records would have stayed unfound: it took writing
§6's specification to discover that ADR-0093 §7 blocks a second source independently
of §9a, which is a fact worth more to the next lane than the paragraph itself.
