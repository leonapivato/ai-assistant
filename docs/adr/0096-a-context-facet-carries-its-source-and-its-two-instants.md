# 96. A context facet carries its source and its two instants; staleness is legible, and an absent facet says nothing more

- Status: Proposed
- Date: 2026-08-03
- **Decides `core` surface and implements none of it.** It adds a base model and
  one facet type to `core/types.py`, one optional field to `CurrentContext`, and one
  optional field to `SourceReading` with a model validator on it. **No `Settings`
  figure is owed**, which is a
  consequence of §6's payload rather than an omission. Golden rule 5 and ADR-0015
  §5 put a contract ADR in its own PR, merged before anything implements against
  it, so **no code changes with it** — the types, the `context/` adapter and the
  composition wiring are later lanes (§8).
- **Required review set: adversarial *and* architecture**, even though the PR
  carrying it is prose only. It decides `core/types.py` surface, which is the
  ground ADR-0093, ADR-0094 and ADR-0095 each took the same set for, and which
  `CONTRIBUTING.md` → "Stop when the required reviews are green" states directly:
  a change is contract-surface "when it is the ADR deciding that surface". It is
  **reviewed while `Proposed` and ratified only after**, in a separate lane
  (`CONTRIBUTING.md` → "Contract ADRs land before their implementation"; #633
  records why the flip cannot ride in this PR).
- **Discharges ADR-0093 §11's context-facet deferral and meets ADR-0093 §7a's
  stated condition**, which lifts the reserved facet-only enablement state by
  satisfying it rather than by editing it. It **amends no earlier ADR and
  supersedes none**; §9 applies ADR-0070 §1's test clause by clause, including to
  the four places where the opposite reading is available.
- **Decided with a producer in hand, which is not what the sequencing assumed.**
  ADR-0092's `Attestation`, ADR-0093's `Reader`/`SourceReading`/`ReaderError`, the
  `readers/` package with a working `CalendarReader`, `orchestration`'s ingestion
  stage and all nine of ADR-0093 §7a's `Settings` figures are on `main`. The two
  unbuilt pieces are exactly the two this ADR is about: the `context/` adapter and
  the field it would contribute to. So the discipline ADR-0073 §4 named — decide
  this "with a producer in hand", "not one to guess here" — is satisfiable now and
  is what §6 leans on.

## Context

### The one part of leg 6 that is still a hole

ADR-0093 split a reader's output between two consumers — memory, and the
situational context — and shipped only the memory half. Everything on that half is
built — the Protocol, the reading type, the `readers/` package, a working
`CalendarReader`, the ingestion stage and ADR-0093 §7a's nine `Settings` figures.
The context half is not, and it is blocked on one thing: `CurrentContext` has no
field for a reader to contribute to. `readers/__init__.py` says so from the other
side, listing "the ``context/`` facet" first among the lanes still owed.

That blockage is deliberate and is stated as a rule rather than an omission.
ADR-0093 §7a rules the facet-only enablement state "**reserved, not enabled**",
because "an adapter shipped today could only read the user's calendar and
contribute an empty mapping — I/O on personal data in exchange for nothing". Its
condition for lifting is precise: "Until an ADR adds the calendar facet as an
optional `CurrentContext` field". This is that ADR.

### Three forces, and they do not point the same way

**ADR-0008 built `CurrentContext` for exactly this and said what shape it takes.**
§1 rules that future facets "are added in follow-on ADRs as **optional** fields
(e.g. `calendar: CalendarContext | None = None`), so a producer that predates a
facet stays valid: an absent facet is `None`". `extra="forbid"` is on the model so
that an internal source contributing an unknown field "fails loudly rather than
silently dropping data". Nothing here is being invented; what is being decided is
what goes *inside* such a field.

**The temporal core is not a template for a facet, and treating it as one is the
failure mode.** `now`, `time_of_day`, `is_weekend` and `within_working_hours` come
from a clock: always present, never someone else's word, and incapable of being
stale. A calendar facet is a third party's report, read at an instant, from a file
the hub does not own. Rendered beside `is_weekend` as a bare value it is precisely
what ADR-0072 §6 refuses — "a wrong record laundered into a fact by flat prose,
restated back to the user with the assistant's authority, and never questioned
because it did not arrive looking questionable". The temporal core is bare values
because a clock reading has no provenance to lose. A facet does.

**The owner's ruling settles the shape of the answer.** Recorded on #625 against
#545's prerequisite 2: **a stale facet is present-but-stale, understood from its
source.** It is shown with its staleness legible — not hidden, and not silently
refreshed. #545 states the cost that makes it urgent rather than tidy: "Cheap now;
expensive across ten future facets." VISION §4 lists ten, and nine are unbuilt, so
whatever this ADR decides is paid once or nine times.

### What this ADR is not allowed to settle

Named here so their absence reads as a boundary. §10 states each with the
condition that fires it.

- **The grant surface.** ADR-0093 §7 rules that configuration is not consent, and
  #629 records that `VISION.md`'s "granted, scoped, and revocable" is unmet by
  construction. Adding a facet field grants nothing and changes nothing about
  that; it is its own ADR and its own lane.
- **What a surface *says*.** ADR-0072 §6's own limit applies — a rule of this kind
  "constrains *what the assembler must convey*, not the wording it uses". §7 rules
  a floor and leaves the prose to the lane that writes it.
- **Retrieval and band precedence.** ADR-0072 §5 ranks `ASSERTED` above `ATTESTED`
  above `DERIVED` when a consumer assembles context from the *store*. A facet is
  not a stored belief, is not in a band, and is not retrieved; nothing here touches
  that ordering or its ADR-0072 §10 revisit trigger.
- **Everything ADR-0093 §11 defers other than the facet entry**, which this ADR
  neither discharges nor narrows.

## Decision

We will make a context facet a typed model that carries its own source and the two
instants that say when it was true, add the first such field to `CurrentContext`,
and rule that an absent facet says nothing beyond its absence.

### 1. `CurrentContext` grows one optional field per facet, and every facet is a `ContextFacet`

> **Normative.** A non-temporal facet reaches `CurrentContext` as an **optional
> field defaulting to `None`**, one field per facet, typed as a concrete subclass
> of a new `core/types.py` base model `ContextFacet`. A facet may not be carried in
> a mapping, a sequence, or any container keyed at run time.

> **Normative.** A `ContextFacet` subclass may not redefine `source`, `read_at` or
> `as_of`. Those three names are the base's and are reserved on every facet.

> **Normative.** `ContextFacet` is a base for shared fields and for generic
> consumption, and is **never itself a field annotation**. Every field that carries
> a facet — on `CurrentContext`, on `SourceReading`, or anywhere else in
> `core/types.py` — is annotated with concrete facet types.

**The third clause exists because pydantic serialises by the declared annotation
and says nothing when that loses data.** A field annotated with the base and
holding a subclass round-trips as the base: the subclass's own fields are dropped
on `model_dump` and are simply gone on the way back in. Measured on this
repository's pydantic before the clause was written, a base-annotated field holding
a two-field subclass dumped `{'facet': {'source': 'calendar'}}` and revalidated to
the base class — **with no warning emitted at all.** That is the shape of defect
this corpus keeps ruling against: it produces a wrong answer while every check
passes. Adversarial review raised it against an earlier draft of §5, which
annotated `SourceReading.facet` with the base for the tidiness of never widening a
union; the tidiness was not worth a silent data loss, and the clause is stated on
the base rather than on that one field so the next facet-bearing type does not
rediscover it.

The per-field half is ADR-0008 §1 obeyed rather than restated, and it is worth
saying why the obvious generalisation is refused. A `facets: Mapping[str, Facet]`
container looks like it saves nine future edits and instead moves three properties
out of the type system: `extra="forbid"` stops catching an internal source that
contributes an unknown facet, because every key is admissible; the assembler's
collision check — which today is `CurrentContext.model_validate` plus one explicit
guard in `AssemblingContextProvider.assemble` — becomes hand-written key
arithmetic; and every consumer receives an object whose type says nothing about
what it holds. That last one is the decisive one: a run-time-keyed container of
facets **is** the `Mapping[str, object]` that ADR-0008 §2 deliberately confines to
`context/`, promoted into `core` under a different name. The whole property §2
bought — "the only data that crosses a subsystem boundary is the typed
`CurrentContext`" — is spent to save typing nine field names.

**The base class is the mechanism, and it is chosen over a convention because a
convention here fails silently.** A rule that says "every facet carries its source
and its instants", enforced by review, is held exactly until the tenth facet author
does not read this ADR — and the failure is a facet rendered as a bare value, which
is the one outcome §7's floor exists to prevent. A base class makes it structural,
and it makes it *checkable*: §8 puts on the implementing lane a test asserting that
every optional field of `CurrentContext` is annotated with a `ContextFacet`
subclass. That is the same move `tests/core/test_instant_coverage.py` and
`tests/core/test_text_encodability_coverage.py` already make for `UtcInstant` and
`EncodableText` — a property held over the whole file rather than over the fields
someone remembered.

**Not a generic `Facet[T]` envelope.** Pydantic supports it, and it would put the
stamp beside an arbitrary payload. It buys nothing a base class does not: the
payload type still has to be named per facet, every consumer gains a `.value`
indirection, and `@runtime_checkable` narrowing over a parameterised model is
worse than over a plain subclass. The corpus's own shape for "shared envelope
fields plus kind-specific ones" is a base class with typed subclasses —
`MemoryBase` and its four kinds — and this is that shape one subsystem over.

**The reserved names are the base class's one real hazard, closed by the second
clause.** Flat fields on a base share one namespace with the payload, so a future
facet whose own vocabulary includes "source" would shadow the stamp. Reserving the
three names costs a sentence; nesting them under a `stamp:` sub-object to keep the
namespaces apart would cost every consumer a second indirection to solve a problem
one clause solves. The nesting argument that carried ADR-0092 §2 — a value object
so half-states are unconstructable — does not transfer, and it is worth saying
why rather than borrowing the conclusion: there the *whole* attestation was
optional, so two loose fields admitted two half-answers. Here the optionality is
one level up, on the facet field itself, and a `ContextFacet` that exists carries
all three by construction.

### 2. A facet carries its source and two instants, and the second one is optional for a reason

> **Normative.** `ContextFacet` carries exactly three fields: `source`, an
> `EncodableText` equal to the producing reading's `source`; `read_at`, a `UtcInstant`,
> always present, being the instant **this system** performed the read the facet
> was built from; and `as_of`, a `UtcInstant | None`, being the instant **the
> source itself declares** for that reading, and `None` where it declares none.

> **Normative.** A facet's `as_of` carries only an instant the source itself
> declares. It may never be filled from the filesystem, from the clock, from
> `read_at`, or from one entry's stamp applied to the rest.

**These are ADR-0092 §10's "as-of timestamp and provenance", counted honestly.**
That sequencing note names two things and the right number is three, because
"provenance" for a facet is one field — who reported it — while "as-of" is two
clocks that ADR-0073 §4 exists to keep apart. Collapsing them is the defect §4
states in as many words: "a record synced on Tuesday from a calendar that said so
on Monday renders 'Tuesday', which is a true statement about us and a false one
about the source."

**`read_at` is always present because it is always knowable.** ADR-0093 §10's
argument for the same field on `SourceReading` transfers without modification — it
is our own clock, so there is no source that can fail to supply it and no
substitute anyone would be tempted to reach for.

**`as_of` is optional, and the `None` is the load-bearing part.** The producer in
hand demonstrates it: `CalendarReader._read_source` sets `as_of=None` and says why
— a local `.ics` declares no reading-level as-of, its report times are per-`VEVENT`
(`DTSTAMP`, `LAST-MODIFIED`), and the file's mtime is a fact about our filesystem
rather than a claim the source made. A required field would therefore have exactly
two fillable values for the first facet, and ADR-0092 §3 and ADR-0093 §10 each
forbid one of them by name.

**And the mtime is the specific temptation this clause is written against.** The
two deployment patterns ADR-0095 names are a synced vault and a co-located
fetcher's output, so a reader is usually looking at a *mirror*, and the question
"when did the mirror last sync" has an answer sitting right there in `st_mtime`. It
is not the answer: it is the last local write, and a copy, a restore, an `rsync`
preserving times, or a `touch` each move it independently of anything the source
said. ADR-0092 §3 already refuses it for `reported_at` and gives the reason — a
substitute is "precisely ADR-0073 §4's 'a true statement about us and a false one
about the source' — reintroduced under a different field name, and harder to spot
because it is *nearly* right". A facet is a **weaker** record than a belief, not a
stronger one, so it does not get a licence a belief is denied.

**`Attestation` is borrowed in shape and deliberately not reused as a type.** The
kinship is real — `Attestation` is the corpus's existing answer to "who said so,
and when" — and reuse fails on both its fields. `reported_at` is required and
ADR-0092 §3 defines it as the source's own clock with no substitute permitted, so
an `Attestation` on a calendar facet is unconstructable for the one producer that
exists. And `Attestation` carries no our-clock field at all, because on a stored
belief that role is `Provenance.last_updated`; a facet has no `Provenance`, no
store and no transaction time, so it needs `read_at` of its own. What is reused is
the *argument*, which is ADR-0092 §1's: a band whose whole standing is that someone
else said it is the last thing that should be able to say nothing about whose.

**`EncodableText`, matching the field it copies — and an earlier draft said
`Identifier`, which architecture review showed breaks §5's equality validator.**
`Identifier` is the tighter type and the tempting one: the value is rendered to a
user under §7's floor, where a blank source renders "your … said", which is the
half-answer ADR-0092 §2 makes unconstructable on the belief side. But `Identifier`
carries `_non_blank`, which **strips**, and `SourceReading.source` is
`EncodableText`, which does not. A conforming reader named `"  calendar  "` — the
suite requires `name` stable and non-empty, not trimmed — would then produce a
reading whose `source` keeps the spaces and a facet whose `source` loses them, and
§5's validator would refuse a reading that every other rule permits.

**The rule this settles is more general than the bug: a faithful copy takes the
type of the field it copies.** Tightening only the copy is how two spellings of one
value drift, and the drift is silent until something compares them — which is
exactly what §5's validator does, which is why it surfaced here and not later.

**The same mismatch is already on `main`, one field over, and this ADR declines to
add a third instance.** `Attestation.reported_by` is `Identifier` and is set from
the reader's `name` (`CalendarReader._proposal`), while `SourceReading.source` is
`EncodableText` and is set from the same `name`; constructing both from
`"  calendar  "` yields `'calendar'` and `'  calendar  '`, which do not compare
equal. That is pre-existing, is not this ADR's to change — the type of a field
ADR-0093 §10 specified is that ADR's decision, and changing it here would be a
partial supersession bought for a whitespace case — and is filed as **#662**, which
proposes one identifier contract across `Reader.name`, `SourceReading.source` and
`Attestation.reported_by` at once. When it lands, this field follows the field it
copies, with no edit here.

### 3. Staleness is legible and is never a gate: no threshold, no flag, no cache

> **Normative.** No facet carries a staleness verdict — no boolean, no freshness
> class, no expiry — and no `Settings` figure defines when a facet becomes stale.
> Age is computed by a consumer from the instants the facet carries.

> **Normative.** A facet's age never gates its presence. No producer, adapter or
> assembler may withhold, drop or downgrade a facet because it judges it old.

> **Normative.** A facet is built from a reading taken during the assembly that
> returns it. No facet is served from a cached, carried-over or previously
> assembled reading, and a failed read yields an absent facet rather than the
> previous value.

**This is the owner's ruling given effect three ways, and the third is the one that
does the work.** "Present-but-stale, understood from its source" forbids two
outcomes: hiding a facet for being old, and refreshing it in a way that hides that
it was old. The first clause removes the *vocabulary* for hiding — a `stale: bool`
is not a description, it is a switch, and the first consumer to find it will use it
to drop the facet. The second removes the *permission*. The third removes the
*state* in which the question could arise at all.

**A threshold cannot be decided in `core` anyway, and pretending otherwise is the
divergence ADR-0074 §9.3 names.** "Ten minutes is stale" is a claim about one
source and one use, and a bounded default with no argued figure is "two conforming
stores handing the same continuation different history" — the rule ADR-0093 §5
invokes and ADR-0093 §7a discharges by naming nine figures with their reasons.
There is no reason available here: nothing has measured how old a calendar reading
may be before a plan built on it is wrong, and inventing a number to have one would
be the padded-list failure ADR-0095 corrects in its own Context.

**What a consumer computes instead is two figures, and they are different
questions.** `CurrentContext.now` minus `read_at` is *how long ago we looked* —
always available, always true about us. `now` minus `as_of`, where the source
declares one, is *how old the source says its picture is* — available only when the
source speaks, and the only one of the two that is a statement about the world.
They must not be merged, and where `as_of` is `None` the honest answer to the second
question is that the source does not say, which is what a surface reports under §7.

**Under ADR-0008 §5 the first figure is small, and that is not a reason to drop
it.** `assemble()` "computes fresh each call", and ADR-0093 §3 rules that "the
context facet reads at assembly time", so `read_at` sits close to `now` on every
request and the arithmetic looks like it yields nothing. Two things make the field
load-bearing anyway. It is what the third clause is *checkable against* — a facet
whose `read_at` is materially older than `now` is a cache someone introduced, and
without the field nothing could tell. And it is the anchor for the facet's own
claim: the facet does not assert what is true now, it asserts what the source said
at `read_at`, which is the difference between a reading and a prophecy.

**So the source's staleness is exactly what the source does not tell us, and this
ADR does not paper over that.** For the producer in hand `as_of` is `None`, so the
honest rendering of a calendar facet names the source, says when we read it, and
says nothing at all about when the calendar itself was last current. That is
uncomfortable and it is correct: the alternative on the table was the mtime, and §2
refuses it.

### 4. Absence is one state, and it carries no further meaning

> **Normative.** A facet field is present when a reading for it was produced during
> this assembly, and `None` otherwise. `None` is the single absence: it does not
> distinguish unconfigured, disabled, never-read, failed or empty, and no consumer
> may infer which it was.

> **Normative.** No facet, and no field of `CurrentContext`, reports a source's
> configuration or enablement state.

**The first clause is ADR-0008 §1 applied rather than extended.** That section
already fixed what an absent facet means — "an absent facet is `None`, which also
matches 'context is advisory and need not be complete'" — so a discriminated
absence would be a change to a ratified decision, not an addition to it.

**The assembler could not honour a richer absence even if one were ruled**, which
is the practical half. An unconfigured source is not registered, so it contributes
nothing; a source that fails is skipped by
`AssemblingContextProvider._safe_contribute`, which logs the failure by class and
returns an empty mapping; a source that succeeds with nothing to say contributes a
facet. The first two are indistinguishable at the merge by construction, and making
them distinguishable would require the adapter to be registered-but-silent and to
contribute a marker — which is `context/` reporting *its own wiring* into `core`.

**The second clause is the one that matters and it is not merely tidiness.**
`CurrentContext` reaches a prompt: `_render_request` in `planning/planner.py`
renders it into the user turn. A field saying "the calendar is disabled" is an
operator fact wearing situational clothes, and a model that sees it will do the
obvious thing — ask the user to enable it. That is a grant conversation conducted
by a field nobody designed, in the exact place ADR-0093 §7 rules that
"configuration is not a grant, and no surface may present it as one", and while
#629 records that the grant surface does not exist. Whoever *does* need to
distinguish the states is an operator, and they are already served: the assembler
logs a skipped source by name and class, and the four configuration states are
enumerated in ADR-0093 §7a with one of them refused at load.

**ADR-0093 §7a's reserved state lifts by having its condition met.** With
`CurrentContext.calendar` decided (§6), a source path with no interval is the
facet-only deployment §7a described and reserved: the adapter may be registered,
the file is opened at assembly time, and no ingestion job is armed. Nothing in §7a
is edited or narrowed — its clause names the event that ends the reservation, and
this ADR is that event. §9 applies ADR-0070 §1's test to it.

### 5. `SourceReading` gains the optional facet field, and the two halves may legitimately disagree

> **Normative.** `SourceReading` gains one optional field, `facet`, annotated with
> the concrete facet types a reader may produce — `CalendarFacet | None = None`
> today — and widened by each later ADR that adds a facet. A reading that carries
> no facet is valid, and a reader whose source has no situational reading returns
> `None` in it.

> **Normative.** When a second concrete type joins that annotation, the union is
> made explicitly **discriminated**, each member carrying its own literal tag, so
> that no payload's facet type is decided by inference.

> **Normative.** A facet's `source`, `read_at` and `as_of` are the values of the
> `SourceReading` that carried it, unchanged. An adapter may not construct a facet
> from a different reading, edit its instants, or synthesise one.

> **Normative.** `SourceReading` carries a model validator: where `facet` is set,
> its `source`, `read_at` and `as_of` each equal the reading's own, and a reading
> that violates it is refused at construction.

> **Normative.** The `context/` adapter contributes the facet from the reading it
> took, under the `CurrentContext` field it was wired for. A facet whose type does
> not match that field is a wiring bug and raises `ContextError`.

This is ADR-0093 §3's deferred half discharged in the place §3 put it: "Its
**facet half is deferred** and lands as an **optional** field when the
context-facet decision is made; a reading that predates that field stays valid."

**The annotation is concrete because the base one loses the payload silently**
(§1), and the cost is honest: each later facet-bearing reader widens this union.
That is not a new obligation — every facet already owes an ADR under ADR-0008 §1,
and widening the union is one more line in the change that ADR authorises. The
discriminator clause is the same defect class one step out: pydantic's smart union
picks a member by fit, so two facets that differ only in a scalar could parse as
each other, quietly, exactly as the base annotation dropped a field quietly.

**The validator is what makes the stamp-equality clause true rather than
remembered, and it is admissible on the corpus's own test.** ADR-0086 §3 states
it — "The test is not 'is it a validator on a `core` type' but 'does it refuse
something that already worked'" — and `facet` is a field that does not exist yet,
so no persisted or in-flight reading can fail it and it is vacuous when `facet` is
`None`. That is the ground ADR-0092 §2 stood its own band-keyed validator on, one
type over, and the reasoning is ADR-0092 §1's: "a precondition that a producer can
satisfy by remembering is one it can fail by forgetting, and the failure is
silent". A facet stamped with a different source than the reading that carried it
attributes content and freshness to the wrong system — the precise thing §7's
floor exists to prevent, arriving through the producer instead of the surface.

**The validator is on the type and deliberately *not* a clause added to ADR-0093
§10's `Reader` conformance suite**, and the choice is made on two grounds rather
than for convenience. It is **stronger**: the suite binds implementations of
`Reader`, while a validator reaches every construction path, including a fixture,
a fake and a library consumer — the same reason ADR-0092 §2 put its rule on
`Provenance` rather than at the `MemoryPolicy` gate, since "the gate is not the
only path a `Provenance` takes". And it keeps this ADR **additive on a type it
already touches** instead of adding an item to another ADR's enumerated suite,
which is the operation ADR-0082 §1 treats as changing what that section *said*.

**The duplication inside `SourceReading` is intentional, which the validator can
make look accidental.** If the facet's stamp must always equal the reading's, it
looks redundant on the reading — and it is, for as long as the two travel
together. They do not: the adapter lifts the facet out and puts it in
`CurrentContext`, where the reading is gone and the stamp is the only thing left
saying who produced the value and when. The validator's job is to keep the copy
faithful, not to argue it away.

**The narrowing at the adapter is honest rather than a hole.** A `ContextSource`
holding a `Reader` is constructed for a specific field — this one contributes
`calendar` — so it knows the type it expects, and a mismatch is a deployment wired
wrongly, not data to reconcile. `ContextError` is exactly where ADR-0008 §4 puts
that: "reserved for programmer/wiring bugs the assembler should not paper over".
It is the same posture as §3's source-key collision, one field over.

**The two consumers hold two reader instances, and this is decided here because
leaving it silent means the composition lane picks by accident.**

> **Normative.** The `context/` adapter and the ingestion stage are injected with
> **separate** `Reader` instances for one source. Neither shares the other's
> reader.

ADR-0093 §7 bounds a reader at **one outstanding worker** — "While it is held, a
new `read()` raises `ReaderError` immediately and starts nothing" — and that
reservation is per instance. Share one instance and a scheduled ingestion read
suppresses the request-path facet for as long as it runs, which couples the two
cadences §3 exists to keep independent, in the direction that makes an advisory
facet wait on a periodic job. Two instances cost two workers at most, which is
still bounded, and each consumer then owns its own failure.

**A slow source degrades the facet rather than the request, and it degrades it for
more than one request.** The assembler's own `source_timeout` defaults to 5 s while
`calendar_read_timeout` is 10 s, so a slow calendar is skipped by
`AssemblingContextProvider._safe_contribute` before the reader's own deadline
fires — and the reader's worker is still outstanding, so the *next* assembly's
`read()` raises `ReaderError` immediately and its facet is absent too, until the
worker returns. Two concurrent assemblies produce the same outcome for the second
one. **All of that is the ratified design working**, not a defect: the adapter
carries no `required` marker, so every one of those paths ends at an absent facet,
which §4 rules says nothing beyond its absence. It is stated because a consumer
watching a facet blink in and out will be tempted to read something into the
pattern, and §4's clause forbids exactly that.

**Both halves are computed on every read, and they may contain different things.**
This is worth stating because it looks like a defect and is not. `CalendarReader`
skips an occurrence whose `DTSTAMP` is absent — it must, since ADR-0092 §3 permits
no substitute for a report time the source did not make and ADR-0092 §1's validator
then refuses the record — but the *facet* has no attestation to construct, so that
occurrence is counted in the facet and missing from the proposals. The two halves
of one reading therefore describe overlapping-but-unequal sets, and ADR-0093 §3
already rules that this is the design rather than an error: "the facet states the
source's 'right now' and the belief states what the source said when we last
asked… What matters is not that they agree but that neither is mistaken for the
other." Nobody should "fix" it by making the facet skip the same entries; the facet
is not making an attestation and owes no report time.

### 6. The calendar facet says what is happening and what is next, and deliberately not what it is

> **Normative.** `CurrentContext` gains `calendar: CalendarFacet | None = None`.
> `CalendarFacet` extends `ContextFacet` with three fields: `entries_in_progress`,
> a non-negative `int` counting the occurrences in progress at `read_at` by the
> clause below; `next_starts_at`, a `UtcInstant | None` being the earliest
> in-window occurrence starting strictly after `read_at`, and `None` where the
> window holds none; and `covers_until`, a `UtcInstant` being the exclusive upper
> edge of the window the reading covered.

> **Normative.** An occurrence with a non-zero duration is in progress when
> `start <= read_at < end`; a zero-duration occurrence is in progress when
> `start == read_at`. This is ADR-0093 §7b's half-open membership evaluated at an
> instant rather than over a window, and the two arms exist for §7b's reason.

> **Normative.** `next_starts_at` being `None` states that the reading found no
> later occurrence **within its window**, and never that none exists. No consumer
> may read it as an absence, and no surface may present it as one.

> **Normative.** The calendar facet carries no entry text. It carries no summary,
> location, description, organiser, attendee or identifier, and no per-entry report
> time.

**The facet is the situational view; the entries are already beliefs, and
duplicating them is the mistake here.** The obvious payload is the in-window
occurrences, and it is wrong for a reason ADR-0093 §3 supplies. The same read's
proposals put those occurrences into memory as `ATTESTED` beliefs, retrieval
surfaces them, and ADR-0072 §5 ranks them when a consumer fills its budget. Putting
them in the facet as well ships the same content into the same prompt by two routes
carrying two different stamps — which is precisely the "neither is mistaken for the
other" hazard §3 names, manufactured by us rather than found. The facet's job is
the one thing the beliefs cannot answer at request time without a scan: *is
something happening right now, and when is the next thing*.

**ADR-0093 §7b says this in its own words while arguing something else.** Defending
overlap membership over start-instant membership, it names the cost of the wrong
choice as falling "hardest on the entry the facet most wants: the meeting happening
now". That is the facet's subject, identified by the ADR that deferred it.

**A count rather than a boolean, and the difference is a ruling this reader may not
make.** `busy: bool` has to decide what counts as busy, and the first case breaks
it: an all-day "Holiday" covers the instant and is not a meeting. Choosing is a
judgement about the user's day, and ADR-0093 §2 rules that "A reader infers nothing:
it reads a file and reports what the file says", which is the same ground on which
it refused to file readers in `learning/`. A count is a fact about the parsed
occurrences and needs no such choice. A consumer that must distinguish an all-day
entry from a meeting needs the entries, and §10 defers that with its trigger rather
than half-answering it here.

**`covers_until` is what makes `None` interpretable, and it is one field rather than
two.** `next_starts_at` being `None` means nothing to a consumer who does not know
how far ahead we looked — and a consumer of `CurrentContext` does not read
`Settings`, so the horizon has to travel with the value or not exist. The backward
edge is not carried because nothing a consumer reads is bounded by it:
`entries_in_progress` is anchored at `read_at`, and §7b's overlap membership already
guarantees that an occurrence which began before the window and is still running is
in the reading. Both edges saturate under §7b, so `covers_until` is always a
representable instant.

**No entry text is a Tier-1 decision as much as a design one.** `CurrentContext` is
rendered into every prompt, and a calendar's titles and locations are the most
disclosing thing it holds — `CalendarReader._render` already refuses `DESCRIPTION`
on that ground for a belief, which is a *durable* record, and the advisory path does
not get a weaker rule. Three scalars and an instant carry no free text at all, which
means the facet needs no content budget, no truncation rule, and no argument about
whose timezone renders an all-day entry's date. That is not a coincidence: it is
what choosing the smallest honest payload buys, in ADR-0008 §1's own words —
"Only fields a real source can populate today are modelled."

**And the choice is additive, which is why it is safe to make it small.** A later
ADR may add `entries` to `CalendarFacet` as an optional field the day a consumer
needs them, and every producer and fixture that predates it stays valid — ADR-0008
§1's pattern applied to a facet's own payload. Shipping the entries now and removing
them later would be a breaking change. The asymmetry decides it.

### 7. ADR-0073 §4's floor does not reach a facet; this is the floor that does

ADR-0073 §4's floor is stated over the **band-scoped inspection surface**, per
stored belief: "the surface conveys the band and must not present an attested
belief as the user's word or as our inference… and it must not offer our own
revision time as the source's." Read as written, it does not bind a facet, and the
reason is not a technicality: a facet has no band, is not a belief, is not stored,
and is not enumerated by `list_beliefs`. Stretching §4 to cover it would be reading
a ratified clause past its subject to get a result this ADR can simply decide.

The *reason* for the floor does reach, and it arrives through ADR-0072 §6 rather
than through §4. §6 governs what reaches a prompt, and a facet reaches the prompt.
So the floor is restated here in the facet's own terms, with the same three
prohibitions:

> **Normative.** A surface that presents a facet's content names the facet's
> `source`, and may not present that content as the user's own statement, as this
> system's inference, or as a reading of our own clock.

> **Normative.** A surface may not present `read_at` as the source's own instant.
> Where `as_of` is `None`, a surface says nothing about when the source's picture
> was current rather than substituting `read_at` for it.

> **Normative.** This floor constrains what a surface conveys, not the words it
> uses. It binds any surface that presents a facet's content, and it does not bind
> a surface that presents no facet.

**The gate is on the first lane that renders a facet, not open-ended.** ADR-0073 §4
paired its floor with a gate — resolving citations is "due with the first producer
of derived beliefs, as a precondition of that producer shipping" — and the same
pairing applies: no lane may land a rendering of a facet's content that does not
name its source. Until such a lane exists the floor binds nothing, because
presenting nothing presents no falsehood. That is stated so the adapter lane is not
blocked on a prompt change it does not owe: shipping the field and the adapter with
`_render_request` untouched breaches nothing.

**`core` gains no renderer and this ADR does not ask for one.** The floor is an
obligation on surfaces, and `CurrentContext` is a value. A `describe()` on the facet
would be `core` deciding wording, which ADR-0072 §6 explicitly leaves to "the
prompt-assembly lane".

### 8. What the implementing lanes owe

**The `core` lane, as one change:**

1. `ContextFacet` in `core/types.py` — frozen (ADR-0068), with `source`, `read_at`
   and `as_of` documented as §2 rules them, including the never-from-the-filesystem
   prohibition in the form `SourceReading.as_of`'s docstring already uses.
2. `CalendarFacet` and `CurrentContext.calendar`, per §6.
3. `SourceReading.facet` with its concrete annotation and its stamp-equality
   validator, per §5 — with a **round-trip test** pinning that a `SourceReading`
   carrying a `CalendarFacet` survives `model_dump` and `model_validate` with its
   payload intact, which is the property §1's third clause exists to hold and the
   one the base annotation lost without complaint.
4. A coverage test, which §1's clauses are held by rather than described in:

> **Normative.** The `core` lane ships a test, in the shape
> `tests/core/test_instant_coverage.py` uses, asserting that every optional field
> of `CurrentContext` is annotated with a `ContextFacet` subclass and that no
> `ContextFacet` subclass redefines `source`, `read_at` or `as_of`.

The temporal core needs no exemption from that test: `now`, `time_of_day`,
`is_weekend` and `within_working_hours` are all required fields with no default,
so "every optional field" already selects exactly the facets.

That test is what makes §1 a property of the file rather than of the fields
someone remembered, and it is marked because §1's clauses are otherwise held by
review alone — "the same class of gap ADR-0015 names — an invariant held by prose
rather than mechanism", in `tests/core/test_protocol_triad.py`'s own words.

**The reader lane:** `CalendarReader` populates `SourceReading.facet` with a
`CalendarFacet` built from the same occurrences and the same `read_at`, computing
`entries_in_progress` and `next_starts_at` under §6's membership rules and
`covers_until` from the saturated window edge it already computes. No new
`Settings` figure is owed — §6's payload carries no free text, which is what
`calendar_max_content_bytes` exists to bound on the other half.

**The `context/` lane:** a `ContextSource` in `context/sources.py` holding a
`Reader`, contributing `{"calendar": reading.facet}` when the reading carries one
and `{}` when it does not, carrying **no** `required` marker so a reader fault
degrades the facet and leaves the rest of the context assembled (ADR-0093 §3,
ADR-0026 §4, ADR-0008 §4). It is registered only when `calendar_reader_path` is
set. Its `name` is Tier 2 under `ContextSource.name`'s existing obligation.

**The composition lane:** the adapter is constructed with its **own**
`CalendarReader`, not the one the ingestion stage holds (§5), and is added to the
provider's source list when the path is configured.

**No lane owes a prompt change**, per §7.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text. It is made here, and
the answer is that **no earlier ADR's status line changes**. Four places where the
opposite reading is available:

- **ADR-0008 §1** anticipates exactly this addition and specifies its shape —
  optional field, `None` when absent, added by a follow-on ADR. §1 above uses that
  mechanism as specified and adds a base class *beside* it, constraining what the
  field's type may be rather than changing what the field is. A reader holding only
  ADR-0008 would add an optional facet field before this ADR and after it, which is
  ADR-0070 §1's test, unmet. Using a mechanism as specified is not amending it —
  the ADR-0083 §15 pattern ADR-0093 §12 applied to this same section.
- **ADR-0008 §1's `extra="forbid"`, §4's degradation and §5's fresh-per-call
  assembly** are relied on unchanged. §4's rule that a failing optional source is
  skipped and leaves its facet `None` is what §4 above cites as already deciding the
  absence question, and §3's no-cache clause is §5's "computes fresh each call —
  context is a point-in-time snapshot, not cached state" stated over the facet the
  snapshot now contains. Agreeing with a ratified clause is not amending it.
- **ADR-0093 §7a's reserved facet-only state.** Its clause is conditional on its
  face — "**Until** an ADR adds the calendar facet as an optional `CurrentContext`
  field" — so meeting the condition is the clause operating, not the clause being
  narrowed. A reader holding ADR-0093 alone is told to wait for a field; after this
  ADR the field exists and they stop waiting, which is what the clause instructs in
  both states. Nothing in §7a's text is edited, its nine figures are untouched, and
  its four-state table is unchanged: the second row moves from reserved to live
  because its stated precondition is satisfied. Not an amendment.
- **ADR-0093 §3's deferred facet half, and §10's four-field surface.** §3 rules
  that the facet half "lands as an **optional** field when the context-facet
  decision is made" and §10 lists "the **facet field, absent for now**" as the
  deferred fifth. §5 above is that landing, and its concrete annotation and
  stamp-equality validator are properties of a field neither section specified —
  new text about the fifth field, not changed text about the four. Nothing on
  `source`, `read_at`, `as_of` or `proposals` moves. A deferral discharged on its
  own terms is not a decision changed, which is the treatment ADR-0092's header
  applied when it discharged ADR-0073 §4 and ADR-0045 §5/§7/§10.
- **ADR-0093 §10's `Reader` conformance suite is not added to**, deliberately and
  for the reason §5 gives. Had §5 put the stamp-equality rule there instead, this
  section would owe the record ADR-0082 §1 requires when a later ADR "changed what
  §8 *said*" for ADR-0028's list. It does not, so nothing is owed.

**ADR-0073 §4 — examined and found not to reach**, which §7 argues rather than
asserts, and which is why no floor of §4's is narrowed here. §7 states a *new*
floor over a different subject and leaves §4's own words governing the surface §4
is about.

**ADR-0092 — nothing owed in either direction.** Its §10 sequences this decision
("Context facets carrying an as-of timestamp and provenance. Next wave,
`core/types.py`, sequenced behind the sensor seam") and this ADR occupies that slot.
`Attestation` is cited as it stands, examined in §2, and deliberately not reused; a
reader holding ADR-0092 would act no differently after reading this one.

**ADR-0072 §5 and §6.** §5's band precedence is not touched (§Context). §6 is
applied, not narrowed: §7's floor is §6's rule carried onto a value that is not a
belief, which §6 does not govern and does not forbid.

**ADR-0015 §5's two-stage sequence is obeyed**: this ADR merges before any lane
implements against it, and it changes no code.

### 10. Deferred, by name, each with the condition that fires it

- **The calendar facet's entries.** §6 carries three scalars. Fires with the first
  consumer that must distinguish one occurrence from another — an all-day entry
  from a meeting, or a title in a prompt — which is the first lane to render the
  facet. It lands as an optional field on `CalendarFacet` under ADR-0008 §1's
  pattern, and it owes what §6 avoided: a content budget in ADR-0093 §7a's form,
  and a ruling on whose timezone names an all-day entry's date.
- **The cost of computing both halves on every read.** ADR-0093 §3 has the facet
  read at assembly time and `Reader.read` returns one reading, so a request-time
  read also builds the proposals it discards, and a scheduled read also builds the
  facet it discards. It is bounded by ADR-0093 §7a's figures and runs off the loop
  under §7, so it is a cost rather than a hazard, and nothing has measured it.
  Fires when it is measured to matter, or when a second facet-bearing reader
  exists. The two candidate resolutions are an argument to `Reader.read` selecting a
  half — which ADR-0093 §10 argued against for the bound, and which would owe its
  own Protocol ADR — and leaving it alone.
- **A staleness threshold, and any policy built on one.** §3 refuses to invent a
  figure. Fires when something measures how old a reading may be before a decision
  built on it is wrong; the figure then belongs to the consumer that measured it,
  not to `core`.
- **What a surface says about a facet.** §7 rules a floor and ADR-0072 §6 reserves
  the wording. Fires with the prompt-assembly lane.
- **The remaining nine of VISION §4's facets.** Each owes its own ADR under
  ADR-0008 §1, and each inherits §1's base and §2's three fields rather than
  re-deciding them. That is the whole of what this ADR front-loads.
- **The grant surface**, unchanged and not narrowed (#629).
- **Everything ADR-0093 §11 defers other than the facet entry**, unchanged and not
  re-listed.

## Consequences

- **Leg 6's context half is unblocked**, and the adapter ADR-0093 §7a forbade is
  now the next lane's ordinary work rather than a rule it must wait out.
- **The staleness question is answered by making it computable rather than by
  answering it.** A consumer gets two instants and the source's name; nothing in
  `core` decides what "too old" means, and nothing can hide a facet for being old.
  The owner's ruling is honoured by construction, because age never gates presence.
- **The ninth facet is cheap and the first one paid for it.** A base class and three
  fields are decided once; each later facet decides its payload and inherits its
  stamp. That is #545's prerequisite 2 discharged in the direction it named.
- **What gets harder:** a facet that wants to say something the base does not carry
  needs an ADR, and the calendar facet cannot answer "what is the meeting" until
  §10's first deferral fires. Both are deliberate — the second in particular buys a
  prompt payload that is bounded by construction rather than by a figure.
- **A visible asymmetry is created and named:** the facet and the proposals from one
  reading can describe different entry sets (§5), which will look like a bug to
  whoever finds it first. §5 states it so it is not "fixed".
- **Revisit when** a source arrives that declares a reading-level `as_of` — which
  makes §3's second figure real for the first time and is the first honest test of
  the two-clock split on this path — or when a consumer needs the entries §6
  withholds.

## Alternatives considered

- **A `facets: Mapping[str, Facet]` container on `CurrentContext`.** Rejected in
  §1: it re-creates inside `core` the untyped mapping ADR-0008 §2 confines to
  `context/`, and spends `extra="forbid"` and the collision check to save nine field
  names.
- **Reuse `Attestation` as the facet's stamp.** Rejected in §2: `reported_at` is
  required and admits no substitute, so it is unconstructable for the one producer
  that exists, and `Attestation` carries no our-clock field because a belief's is
  `Provenance.last_updated`.
- **Carry the file's mtime as a third instant, honestly labelled.** Rejected in §2.
  It is a filesystem fact rather than a source claim, it moves under a copy, a
  restore or a `touch`, it is meaningless for a maildir or a feed, and it is
  ADR-0092 §3's named refusal reached by renaming the field.
- **A `stale: bool`, or a `max_age` in `Settings`.** Rejected in §3: the boolean is a
  switch a consumer will use to hide the facet, which is the outcome the owner's
  ruling forbids; the figure has no argued value and ADR-0074 §9.3 rules that an
  unargued bound is two implementations diverging.
- **Distinguish "disabled" from "never read" from "failed" in the absent facet.**
  Rejected in §4: ADR-0008 §1 already fixed `None` as the single absence, the
  assembler cannot tell the first two apart by construction, and a "disabled" marker
  puts configuration into a prompt at the moment ADR-0093 §7 rules configuration is
  not a grant.
- **Put the in-window entries in the calendar facet.** Rejected in §6: the same
  read's proposals already carry them into memory, so the facet would ship the same
  content into the same prompt by a second route with a different stamp, and it
  would need a content budget, a truncation rule and a timezone ruling to do it.
- **Type `ContextFacet.source` as `Identifier`.** The draft this ADR was reviewed
  in, and rejected in §2: `Identifier` strips and `EncodableText` does not, so a
  conforming reader with a padded `name` would produce a facet whose source no
  longer equals the reading's and a validator that refuses it. Architecture review
  found it; the probe confirmed the same mismatch already exists between
  `Attestation.reported_by` and `SourceReading.source` on `main`. #662 is where all
  three get one contract.
- **Annotate `SourceReading.facet` with the base `ContextFacet`.** The draft this
  ADR was reviewed in, and rejected in §1 on measured evidence: pydantic serialises
  by the declared annotation, so a base-annotated field holding a `CalendarFacet`
  dumps the three stamp fields and drops the payload — silently, with no warning.
  Adversarial review raised it; the probe confirmed it; the concrete annotation
  removes it at the root and costs one widened union per future facet.
- **Enforce §5's stamp equality by a clause in ADR-0093 §10's `Reader` conformance
  suite** rather than by a validator on `SourceReading`. Rejected in §5: the suite
  binds `Reader` implementations while a validator binds every construction path,
  and adding an item to another ADR's enumerated suite is the operation ADR-0082 §1
  treats as changing what that section said.
- **Nest the three stamp fields under a `stamp:` sub-object.** Rejected in §1: the
  half-state argument that carried ADR-0092 §2 does not transfer, because the
  optionality here is on the facet field rather than on the stamp, and one clause
  reserving three names closes the only hazard flatness creates.
- **Decide the envelope here and leave the calendar facet to its own ADR.** The
  tidier split, and rejected because it leaves ADR-0093 §7a's reservation standing:
  §7a lifts on a *calendar* field existing, so an envelope-only ADR would unblock
  nothing and buy a second ADR to decide a payload this one can decide with the
  producer already on `main`.
