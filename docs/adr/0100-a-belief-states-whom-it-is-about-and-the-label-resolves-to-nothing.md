# 100. A belief states whom it is about when that is not the owner, and the label resolves to nothing

- Status: Proposed
- Date: 2026-08-04
- **Decides one axis, the two `core` fields that carry it, and the two things
  that must ship with them.** `MemoryBase` gains an optional `about_person`;
  `FeedbackEvent` gains the same field and `assistant learn` gains a route into
  it (§7), so the one producer that already writes third-party beliefs can say
  so; and an observer refuses to propose a stated subject, pinned by the
  `Observer` conformance suite (§5), so the axis ships with the check ADR-0099 §5
  fires it on rather than after it. No band changes and no supersession rule
  changes.
- **Flagged as a breaking change under golden rule 5, and this is why it merges
  first.** The implementing lane touches `core/types.py` — `MemoryBase` and
  `FeedbackEvent` each gain a field — and `core/protocols.py`, where
  `Observer.observe`'s "what may be proposed" names the new field and the shared
  `Observer` conformance suite gains §5's clause. The `Observer` change adds no
  obligation the contract does not already state (§5); it is named here anyway,
  because a lane editing `core/protocols.py` should find the authority in this
  header rather than infer it.
- **Required review set: adversarial *and* architecture.** `ship.sh` gates the
  architecture review on `core/protocols.py` or `core/types.py` changing, and the
  PR carrying this ADR touches neither — it is prose only. The set is taken
  anyway because the *decision* is `core` surface: ADR-0093 through ADR-0099 each
  declared both for that reason, and this one specifies a field on the envelope
  every belief in the system carries. Reviewed while `Proposed` and ratified only
  after, in a separate lane (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"; #633 records why the flip cannot ride in the PR that carries
  it).
- **Discharges the first deferral of ADR-0099 §5**, which reads "The subject axis
  itself — whether a belief names its subject, in what type, with what identity,
  and what an absent subject means. It is the next ADR." ADR-0099 stood
  `Proposed` when this ADR was written, and this ADR is written to be ratified
  beside it; every reference below to ADR-0099 is to its text as merged on
  2026-08-04, not to its status on any later day.
- **Amends no earlier ADR and supersedes none.** §11 applies ADR-0070 §1's test
  and ADR-0082 §1's record rule to the four places where the opposite reading is
  available: ADR-0077 §2, ADR-0009 §1 and §4, ADR-0073 §4's enumeration, and ADR-0099
  §5's own deferral.
- **It corrects one premise it inherits, and the correction is in §8.** The claim
  that every belief written to date is about the owner — so that a backfill is
  correct by construction — is *not* established by the tree. `assistant learn`
  accepts arbitrary third-party content today, so a deployed store may already
  hold beliefs about other people. §3's reading of an unstated subject is
  therefore a **reading**, stated as one, and §8 bounds what it can honestly
  promise for records written before the field existed.

## Context

### The corpus already binds two obligations on an axis no field carries

ADR-0099 §2 names the axis and rules it open: "**Subject** — whom a given belief
is *about*. **Many**, and unmodeled as of this ADR's date", with a marked clause
holding that §1's single-principal ruling "may never be cited to argue that a
belief is necessarily about the owner, to refuse a subject axis, or to narrow
what a later ADR may model about a third party."

What makes the axis owed is not that ADR-0099 named it. It is that **two ratified
rules are already phrased on it, and neither can be checked**:

- **ADR-0077 §2.** "A proposal is warranted only when the belief is **about the
  user** and would change a later answer — a preference, a durable fact about
  them or their world, a workflow they follow." That rule binds a shipped
  producer. `ModelBackedObserver`'s `_SYSTEM_PROMPT` carries it in as many words —
  "Propose a belief only when it is ABOUT THE USER and would change a later
  answer" — and the phrase recurs in the module docstring and in `observe`'s.
  **So the whole of the rule's enforcement is a sentence inside a prompt string.**
  ADR-0077 §2 says as much of itself, calling this "the half of that principle a
  gate cannot enforce".
- **ADR-0098 §4.** Its fourth ceiling turns on the same distinction. The section
  separates "a **faithful transcription** — a reader saying what its source says,
  at a band that already caps its standing" from "a **model-authored
  generalisation about the user** that an attacker's sentence helped produce",
  and rules only the second. Which side a proposal falls on depends on whom it is
  about, and no field records that either.

An obligation carried by a prompt and by no record is the condition this corpus
treats as a defect. It is not that the system lacks an opinion about whom a
belief is about; it has two, both ratified. It has nowhere to put the answer.

### Three producers exist, and each stands in a different relation to the axis

ADR-0073 §4's "with a producer in hand" discipline is what this corpus uses to
refuse a field nobody can fill. Three producers write beliefs today, and the
verified facts about them are not interchangeable:

- **`ModelBackedObserver`** (`learning/observer.py`) is *bound* by ADR-0077 §2 to
  propose only about the user, and nothing enforces it. It is the producer the
  axis exists to make checkable.
- **`RuleBasedFeedbackProcessor`**, behind `assistant learn`, is *unrestrained*.
  It takes a `FeedbackEvent`, mints `Provenance(source=MemorySource.USER_ASSERTED,
  confidence=_FULL_CONFIDENCE, …)`, and builds a `SemanticMemory` or
  `PreferenceMemory` straight from `event.content`. Nothing in the command, the
  type or the processor looks at whom the content is about. `assistant learn
  "Marta prefers window seats"` is an ordinary, supported, fully-warranted
  `USER_ASSERTED` belief about a third party, and under ADR-0099 §1 it is exactly
  right that it is. It is the producer that needs somewhere to *say* so.
- **`CalendarReader`** is neither, and the difference matters to §4. Its
  *content* may name anyone — `_render` builds `Calendar entry "<title>" at
  <place>, <when>` — but the reader has nothing to state a subject *from*.
  `Occurrence` carries `summary`, `location`, `zone_label`, the instants and
  `reported_at`, and no attendee, organiser or identifier is parsed at all; the
  facet's own docstring records the same refusal for "no summary, location,
  description, organiser, attendee or identifier". A reader that has never read
  an `ATTENDEE` line cannot state who an entry is about without inferring it from
  a title, which is a different act entirely (§4).

So the producer half is satisfied, and it is satisfied unevenly: one producer
must be checked, one must be able to speak, one must stay silent.

### The consumer half, honestly

ADR-0099 §5 defers the axis on the **consumer**, not the producer: "Fires with
the first consumer that must distinguish", naming four — subject-scoped delete or
export, a rendering that names a subject, speaker attribution on the voice leg
(#665), "and anything that has to *check* ADR-0077 §2's 'about the user' rule
rather than instruct it".

It is the fourth that has fired, and the honest statement of why is that it is
not a consumer in the ordinary sense. It cannot exist before the field: a check
of "is this about the user" needs somewhere to look. What distinguishes it from a
speculative consumer is that **the obligation it would discharge is already
ratified and already binding on shipped code**. The refusals this corpus makes on
surface-with-no-consumer grounds — ADR-0045 §1, ADR-0028 §7, ADR-0092 §10, and
ADR-0097 §1's own deferred grant subject, which reasons that "adding a subject
field now would be surface with no consumer" — each refused a field whose
*obligation* did not yet exist. Here it does, in two places, and one of them is
enforced today by asking a language model nicely.

**So the check ships with the field rather than after it, and §5 requires it.**
A field whose consumer were optional would leave ADR-0099 §5's condition unfired
while spending the surface, which is the refusal above with an extra step. §5
makes an observer's refusal to state a subject a conformance-pinned obligation
rather than a prompt's request; §7 does the same for the user's route into the
field. Both are preconditions of the field, in ADR-0073
§4's "a precondition of that producer shipping" sense.

The cost of continuing to wait is asymmetric, and it is the argument ADR-0099
made for ruling the frame early, read one level down. Every day the field does
not exist, `assistant learn` may write another belief whose subject is
unrecoverable — not deferred, *lost*, because nothing but the user ever knew it.
§8 is what that costs.

### The word `subject` is taken at least five times over

ADR-0099 §5 flagged one collision. There are more, and a later reader will meet
several of them in one afternoon:

1. **`FeedbackEvent.subject`** — `EncodableText | None`, "Optional scope/context,
   e.g. 'email tone'" (ADR-0009: `subject: str | None = None   # optional
   scope/context, e.g. "email tone"`). `RuleBasedFeedbackProcessor` lands it as
   `PreferenceMemory.context`, per ADR-0009's "`PREFERENCE` target →
   `PreferenceMemory(preference=content, context=subject)`", and the `SEMANTIC`
   branch takes no such field, so an asserted *fact* discards it entirely.
2. **`assistant learn --about`** — the CLI spelling of (1), helped as "Optional
   scope this feedback is about, e.g. 'units'". The most natural flag for the
   person axis is already bound to the scope axis, on the very command that
   writes third-party beliefs.
3. **A grant's subject.** ADR-0097 §1 rules normatively that "A grant's subject
   is a **reader's declared identity**". That is a *third* sense, and it is the
   dangerous one, because it lives in the neighbourhood of identity.
4. **A decision's subject.** ADR-0021 uses "subject" throughout for what a
   permission ruling is about — a tool and its parameters — and records that
   "`PermissionRuling` has no field in which a subject could be named".
5. **A sensitive subject.** ADR-0077 §2 declines "an observer-side taxonomy of
   forbidden subjects" and rejects "a subject filter" — there, `subject` means
   *topic*: health, sexuality, finances.

And in `ai_assistant.testing`, "the subject" is uniformly the object under test.
Five senses, none of them a person, one of them normative, and the two most
natural spellings for the new axis — the field name and the flag — both already
taken by the same competing sense on the same command.

### The near-relative that is not this axis

`EpisodicMemory.participants: tuple[EncodableText, ...]` already exists in
`core/types.py` and has since ADR-0005 §1: free text, person-shaped, resolving to
nothing. It is the closest thing in the tree to what §6 specifies, and it is a
different axis. Participants are who was *present at an event*; a subject is whom
a *belief is about*. It is also inert: ADR-0075 §2 rules that "Capture judges
nothing. No importance, no participants, no evidence", ADR-0074 leaves it empty
for a conversation turn because "the two parties to a turn are structural", and
ADR-0073 §4 excludes it from the band-scoped read as a kind-specific field. So
the corpus already has a free-text person label that no code resolves — evidence
that the shape in §6 is livable, and a name a reader must not conflate with it.

### One hazard that predates this ADR and is worth naming before it is blamed on it

`MemoryIngestor` "detects conflicting existing memories (same kind, highly
similar content)". Kind and content similarity; nothing else. So "Marta prefers
window seats" and an owner preference about seating are already conflictable
today, and a `SUPERSEDE` across that pair already retires the wrong belief. The
axis does not create this. It is the precondition for ever fixing it, and §12
defers the fix rather than smuggling it in.

## Decision

We will add one optional field to the shared memory envelope naming whom a
belief is about, and the same field to the feedback event so the user can state
it. An unstated subject is read as the owner. The value is a label the user or a
source supplied, carried verbatim, resolving to nothing.

### 1. One optional field on the envelope

`core/types.py` gains one field on `MemoryBase`:

```python
about_person: EncodableText | None = Field(
    default=None,
    description=(
        "Whom this belief is about, when that is someone other than the owner "
        "(ADR-0100 §2). None means no subject is stated, which is read as the "
        "owner's. A label as given, resolving to nothing (§6)."
    ),
)
```

> **Normative.** `MemoryBase` carries `about_person`, an optional non-blank
> `EncodableText` defaulting to `None`. A value that is empty or whitespace-only
> is refused at construction; the only two states are "no subject stated" and "a
> stated name".

**Two states, not three**, for ADR-0092 §2's reason. That section chose a value
object over two nullable fields because four states admitted two half-answers,
and "a value object whose fields are both required, held in one optional slot,
makes the half-states **unconstructable** instead of merely discouraged." Here
there is one datum, so a value object would be ceremony rather than structure —
but the same discipline decides the blank: a record stating `""` as its subject
is a producer that meant to speak and said nothing, and it must not be
representable.

> **Normative.** This ADR adds no field to `MemoryUpdateProposal`,
> `Provenance`, `Attestation`, `SourceReading`, `ContextFacet` or any Protocol.

A proposal already carries `proposed: MemoryRecord`, so a policy sees
`about_person` through it with no new surface; that is what makes §5's check
reachable at the gate. And `proposal_fingerprint` projects "the whole record
minus the three fields that are bookkeeping about the record rather than the
belief it states" (`id`, `score`, `provenance.last_updated`), so the subject
enters the fingerprint automatically. That is correct and deliberate: a belief
about Marta and an identically-worded belief about the owner are two different
things to be asked to accept, exactly as ADR-0078 §7 argues of `validity`.

### 2. Placement: the envelope, and the test that decides the next field too

The two placement precedents are cited together as a pair, and they do not
settle this case, because they agree on every case where their two criteria
agree and this is the first case where the criteria come apart.

- **ADR-0045 §2** put `Validity` on `MemoryBase`: the window "is a lifecycle
  property of *the record's life in the store*, set operationally by the
  applier", and "`Provenance` stays about *trust and source*". Its authorship
  argument is stated as an exclusion: "Putting a store-set lifecycle field on
  `Provenance`, whose every other field is set by the *producer* of the belief,
  would mix two authorships."
- **ADR-0092 §1** put `Attestation` on `Provenance`: "Who reported a belief and
  when they said so are producer-set facts about *trust and source* — which is
  what ADR-0045 §2 says `Provenance` stays about."

A subject is **producer-set**, like an attestation, and it is **not about trust
or source**, unlike one. So the two readings point opposite ways, and the ADR
must say which criterion governs.

**Subject-matter governs, and authorship never admitted anything on its own.**
`MemoryBase.content` is producer-set and sits on the envelope. So do
`SemanticMemory.fact`, `PreferenceMemory.preference` and
`ProceduralMemory.situation`. If producer-authorship were sufficient for
`Provenance`, the whole of what a belief *says* would live there. It never has.
ADR-0045 §2's authorship sentence excludes applier-set fields from `Provenance`;
it does not admit every producer-set one, and reading it as though it did is the
error this section exists to foreclose.

**The test, stated so it decides the next field rather than being re-derived.**

> **Normative.** `Provenance` carries what answers *why this should be believed*
> — the warrant, its source, and how far it is trusted. `MemoryBase` carries what
> answers *what is held, about what, and for how long*. A field is placed by
> which question it answers, not by who sets it.

Whom a belief is about is half of the proposition. Two beliefs with identical
warrant differ in subject; two beliefs with an identical subject differ in
warrant. The axis is orthogonal to trust in exactly the way ADR-0099 §2 rules
principal and subject orthogonal, and putting it inside the trust object would
be the same category error one level down.

**A second reason, in ADR-0045 §2's own currency.** It placed `Validity` beside
`expires_at` so that "all read predicates live in one place and the SQLite column
sits next to `expires_at`." The first consumer this axis has (§12: subject-scoped
delete and export) is precisely a read-and-delete predicate. On `Provenance` it
would be the only such predicate reaching through a nested object into a JSON
column; on the envelope it is a column beside the two that already filter reads.

**And a third, negative one.** `Provenance`'s only optional member is
`attestation`, bound by a validator to be "present exactly when the band is
`ATTESTED`". A subject is band-independent — an `ASSERTED`, `DERIVED` or
`ATTESTED` belief may each be about anyone — and a second optional member sitting
beside a band-conditioned one invites a reader to assume it is band-conditioned
too. §9 refuses that validator explicitly, and the placement stops the question
arising.

### 3. What an unstated subject means, and the owner is never named

> **Normative.** `about_person` is stated only when the belief is about a person
> other than the owner. `None` means **no subject is stated**; it is not a claim
> that the belief is about the owner and it is not "unknown".

> **Normative.** A belief with no stated subject is read as the owner's own —
> about the owner or the owner's world, in ADR-0077 §2's sense. No reader,
> surface, store or later ADR may treat `None` as an unknown subject, or exclude
> a `None` record from an answer about the owner on the ground that it says
> nothing.

The distinction between "says nothing" and "says the owner" is what lets §8 be
honest about records that predate the field while keeping every present read
total. A record is never subject-less in *meaning*; it is subject-less in
*statement*, and the reading rule closes the gap.

> **Normative.** The owner is never named in `about_person`. There is no spelling
> of the owner for this field.

This follows from a verified fact rather than a preference: **there is no user
identity anywhere in the tree.** ADR-0036 §3 records that the permission layer
"records that a human answered, not which human"; ADR-0097 §1 rules that "the
grant is not keyed to a user, and that is a property of this system rather than
an omission" and defers **Who granted** to the first multi-user deployment. A
label naming the owner would be a person-identity claim the system cannot check,
and worse, it would create two spellings of one subject — `None` and
`"Leonardo"` — that no code could reconcile and no delete could cover. One
spelling, and it is the absence.

### 4. Who may state a subject, and nobody may infer one

> **Normative.** A producer states a subject only from a statement of subject it
> actually received: an explicit user act, or a structured field of a source that
> names whom an entry is about. No producer may infer a subject from content — not
> by a model, not by a name-matching heuristic, not by parsing a title.

This one clause is what keeps the axis from becoming the thing it must not
become. Inferring "Marta" from `Calendar entry "Coffee with Marta"` is
person-identification from free text: it decides who counts as a person, when two
mentions are one person, and when a name in a sentence is its subject rather than
its scenery. That is the voice-spoke leg's question (#665), and ADR-0094 §10
already warns that it is distinct from *device* identity. A subject axis that
quietly acquired an inference step would have taken it.

Applied to the three producers, and the outcomes are all forced:

- **`assistant learn`** states one when the user does, and §7 gives it the
  carrier. This is the only route by which a non-owner subject enters the store
  under this ADR.
- **`CalendarReader`** states none, because `Occurrence` parses no attendee or
  organiser and the reader may not infer one from `summary`. Its beliefs are read
  as the owner's under §3 — which is *correct*, not a shortfall: "Calendar entry
  'Coffee with Marta', Tuesday 3pm" is a durable fact about the owner's world,
  which is the case ADR-0077 §2's "or their world" already covers.
- **`ModelBackedObserver`** states none, always — §5.

> **Normative.** This ADR authorises no producer to propose a belief it could not
> propose before it. Adding the axis widens no producer's warrant, and no ADR,
> lane or reviewer may cite the field's existence as licence to propose about a
> third party.

The trap this closes is real and easy to spring: a field for third-party subjects
reads like permission to write third-party beliefs. It is not. The permission
already exists for exactly one producer, by ADR-0099's ruling and by shipped
behaviour, and it exists for no other. The field makes an existing permission
legible; it grants none.

### 5. ADR-0077 §2 is untouched, and the obligation it already states becomes checkable

> **Normative.** ADR-0077 §2's warrant rule is unchanged by this ADR: what an
> observer may propose is exactly what it was.

> **Normative.** An observer proposal states no subject. One that would is **not
> proposed**, and is counted in `ObservationOutcome.discarded_unusable`.

> **Normative.** The shared `Observer` conformance suite pins that refusal, so it
> binds every implementation rather than the shipped one.

> **Normative.** No lane may implement the refusal downstream of the producer —
> not by a caller dropping a returned proposal, not by a policy rule keyed on the
> band, and not by a writer substituting a ruling the policy did not make
> (ADR-0081 §3, restated by ADR-0098 §5).

**The check is required, not offered, and that is what makes the deferral's
firing condition honest.** ADR-0099 §5 fires the axis on "anything that has to
*check* ADR-0077 §2's 'about the user' rule rather than instruct it". A field
whose only check were optional would ship the surface and leave the condition
unfired — so the check lands in the same change, and §7's last clause does the
same for the user's route. Neither is a follow-up.

**This adds no obligation to the `Observer` contract; it makes one that is
already there checkable.** `Observer.observe` already carries the bar in as many
words — "A belief is warranted only when it is *about the user* and would change
a later answer … so it is stated as a producer-side obligation" — and already
rules that a proposal failing the producer's own discipline "is **not proposed**,
and is counted in ``discarded_unusable``". A proposal stating a non-owner subject
is a proposal the contract's existing bar already forbids; what changes is that
it can now be *seen*, so the conformance suite can pin what the prose could only
assert. `discarded_unusable`'s own definition already enumerates this shape of
refusal — entries the producer refused "for a reason of its own", including one
"naming a kind an observer may not propose".

**The refusal is the producer's and stays there, which is why the last clause
forbids the two downstream shapes.** Neither was available. `MemoryPolicy.decide`
receives a proposal and conflicting records and no producer identity, so its only
proxy is the band — and §2 holds the axis band-independent, so a rule that no
`DERIVED` proposal may state a subject would bind every future derived producer,
including one that legitimately receives a structured subject, and would widen
`MemoryPolicy`'s behavioural contract for every implementation. Nor may a caller
drop a returned proposal: `Observer`'s contract has the caller put "each returned
proposal through the write path, in order and independently", and an exception to
that clause is a change to the seam rather than a use of it. Both would buy a
producer's discipline by charging someone else's contract.

**Refuse rather than raise**, following ADR-0077's own posture — "A malformed
response degrades; a model failure propagates". One unusable entry is discarded
and counted; failing the whole pass over it would lose the proposals that were
fine.

**It holds today by construction and is written so it survives the next
observer**, which is ADR-0098 §4's form for exactly this shape of clause.
`ModelBackedObserver` builds every record itself from a fixed JSON envelope whose
schema has no subject key, so the shipped observer *cannot* state one however the
model answers. The clause therefore binds nothing today and is fail-closed
against the second `Observer` implementation, which is the one the corpus cannot
inspect.

**What this buys, stated exactly, because overclaiming here would be the worst
outcome available.** The observer's compliance with ADR-0077 §2 becomes
*representable*, and one breach of it is discarded deterministically rather than
merely discouraged in a prompt.

**It does not make ADR-0077 §2 enforceable, and this ADR does not claim it
does.** A model that proposes "Marta prefers window seats" while leaving
`about_person` unset is as undetectable after this ADR as before. The gap is the
one ADR-0077 §2 named of itself and ADR-0098 §5 named of its own fourth ceiling:
a rule about the *meaning* of a sentence cannot be enforced by a check on a
field. What changes is that the honest case is now recordable and the dishonest
case is now *a lie about a field* rather than an unstated assumption — which is
where every other check in this corpus starts.

### 6. Identification: a label, carried verbatim, resolving to nothing

> **Normative.** `about_person` holds a label as the user or the source stated
> it. It is not an identifier, not a key, and not a reference: under this ADR
> nothing resolves it, and no store, producer, surface or lane may treat two
> equal labels as the same person or two unequal labels as different people.

> **Normative.** Whether labels may be compared, matched, aliased or resolved to
> a person — and by what rule — is reserved to a later ADR, which is the only
> thing that may lift the clause above. No lane may reach that answer by
> implementing one.

> **Normative.** A subject label is stored exactly as given and returned exactly
> as given. No component normalises, canonicalises, case-folds, trims beyond §1's
> blank check, aliases or de-duplicates it on the way in or on the way out.

> **Normative.** A belief has at most one subject. A belief about two people is
> two beliefs.

**Why a bare label and not a handle.** The alternative — an opaque id into a
person record — requires deciding what a person record is, when two mentions are
one person, and who may create one. That is a person registry, it is #665's, and
ADR-0094 §10 separates it from device identity precisely so a lane that finds one
of them deferred does not assume the other. A field that resolves to nothing
takes none of those decisions, and the corpus already runs one:
`EpisodicMemory.participants` has been free-text-resolving-to-nothing since
ADR-0005 §1.

**Why matching is not decided here, and why storage still is — and the two
clauses above are the split, not a contradiction.** The first fixes what holds
*while nothing else is ratified*: comparison behaves as though the label resolved
to nothing, which is the fail-safe reading and the only one available before a
matching rule exists. The second says which instrument may change that — a later
ADR, ratified, and never a lane deciding it in code. The third is what makes both
affordable: verbatim storage leaves every matching rule available, since
case-insensitive matching, aliasing or a registry can all be layered over exact
strings, and none of them can be recovered from labels that were silently
normalised on the way in. Storage is settled here **because** matching is not:
the floor is what keeps the later answer open. The corpus has the same instinct about `reported_at`: ADR-0092 §3 refuses
any local substitute for what a source said, because a value that is *nearly*
right is harder to spot than one that is missing. A normalised name is nearly
right.

**A weaker precedent than it looks, named so a reviewer does not have to find
it.** `Attestation.reported_by` is often reached for here — "the connected source
instance", required to be stable across syncs. It is a *closed* set in practice:
ADR-0097 §1 admits a grant's `source` "only when it equals the `name` of a
`Reader` the hub actually holds, which makes the admissible set the set of
declared constants and leaves no free-text route in". A person label has no such
set and never will. `participants` is the honest precedent; `reported_by` is not.

**One subject, not a tuple**, because a tuple is a relationship graph in
disguise: it invites "who else was involved", then "how are they related", and
each of those is a decision this lane does not own. One record, one proposition,
one subject — and the split is free, since two beliefs about two people are two
things the user can correct and delete independently.

> **Normative.** The axis is *whom*, not *what*. A belief about a company, a
> project, a device or a topic states no subject.

The five competing senses of "subject" in the Context are all *what* senses. If
the field admits them it becomes a sixth, and the one guard that reliably keeps it
out is that its name says otherwise (§7) and this clause says otherwise.

### 7. The name is `about_person`, and `FeedbackEvent.subject` keeps its meaning

> **Normative.** The field is named `about_person` on every type that carries it.
> It is not named `subject`, and no lane may rename `FeedbackEvent.subject` on
> this ADR's authority.

> **Normative.** `FeedbackEvent` gains `about_person` with `MemoryBase`'s
> semantics and `None` default, and `RuleBasedFeedbackProcessor` copies it onto
> the record it builds — onto both the `PREFERENCE` and `SEMANTIC` branches.
> `FeedbackEvent.subject` continues to mean an optional preference scope and
> continues to land as `PreferenceMemory.context`.

**Why the axis keeps the word and the field does not.** ADR-0099 §2 fixed
"subject" as the *name of the axis*, and this ADR does not fight ratified
vocabulary: the axis is the subject axis throughout. The *field* cannot be
`subject`, because §7's second clause puts it on `FeedbackEvent` — the one type
where the competing sense already lives, on the one command that already writes
third-party beliefs. `FeedbackEvent.subject` and `FeedbackEvent.about_person`
side by side is the clearest possible statement that they are two axes; two
fields called `subject` on one type is not available, and a field called
`subject` on `MemoryBase` while `FeedbackEvent.subject` means a scope is the
collision ADR-0099 §5 warned the next lane about.

**Why `about_person` and not `about`.** `--about` is the CLI flag for the scope
axis on `assistant learn`. The word alone is spoken for at the surface the user
sees. `_person` also does real work: it names the constraint §6's last clause
imposes, so a writer reaching to store "email tone" in it notices at the
keystroke rather than at review.

> **Normative.** `assistant learn` gains an input route that sets
> `FeedbackEvent.about_person`, in the same change as the field. Its spelling is
> the implementing lane's, constrained only by the fact that `--about` and `-a`
> already carry the scope axis.

**The route is a precondition of the field shipping, in ADR-0073 §4's sense, not
a follow-up.** `assistant learn` is the only route by which a non-owner subject
enters the store (§4), and today the command's only optional input is `--about`,
which populates `FeedbackEvent.subject` and lands as `PreferenceMemory.context`.
Ship the field and the processor copy without a route and every `assistant learn
"Marta prefers window seats"` still constructs `about_person=None` — so §3 reads
it as the owner's, and the field's arrival would make a *false* record of exactly
the case it was added for. The spelling stays the lane's because
`CONTRIBUTING.md` and golden rule 3 keep `interfaces/` thin; the *existence* of
the route cannot be, because §8's honest limit depends on it.

### 8. Migration, and what the backfill can honestly promise

> **Normative.** Records written before this field exists carry no subject. The
> SQLite migration adds a nullable column and backfills it `NULL`; the wire
> encoding gains one optional field, additive under ADR-0008 §1's pattern.

> **Normative.** No lane may infer a subject for an existing record — not from
> its content, not from `participants`, not by asking a model. A pre-existing
> record's subject is unstated and stays unstated until the user says otherwise.

Mechanically this is ADR-0045 §9's migration exactly: an absent column backfilled
to the open/absent value, no behaviour change, no re-derivation.

**What it cannot promise, said plainly.** Under §3 every unstated record is read
as the owner's, and for records written before the field that reading is an
inference, not a fact. `assistant learn` has accepted arbitrary third-party
content since it shipped, so a store may already hold beliefs about other people
that will be read as the owner's forever. The claim "correct by construction"
does not survive contact with that producer, and this ADR declines to make it.

Three things follow, and they are the whole of the position:

1. **The imprecision is bounded to records written before the field**, and it
   does not grow after it: from the moment `assistant learn` can state a subject,
   an unstated one is the user's own silence rather than a missing affordance.
2. **It is correctable only by the user**, which is the same remedy the corpus
   offers for every other wrong belief — ADR-0038 §1a's "a user's assertion is
   its own warrant", and a `USER_ASSERTED` correction retires the old record
   under ADR-0092 §4.
3. **Guessing would be worse than the gap.** A backfill that scanned content for
   names would be person-identification (§4), applied retroactively, at scale,
   with no user in the loop, writing subjects nobody stated.

**This is the answer to "for how long does the backfill stay true".** It was
never exactly true; it stops being *defensible* the day a producer can state a
subject and doesn't, which is the day this field ships.

### 9. No validator ties the subject to a band or a source

> **Normative.** No validator on `MemoryBase` or `Provenance` constrains
> `about_person` by `source`, by band, or by kind. §4's and §5's obligations are
> discharged by producers, and pinned where a producer's discipline already is
> — never by a model validator.

ADR-0092 §1 chose a validator for `attestation` because its rule is an `if and
only if` that is true in both directions and forever: an attestation is meaningful
exactly when the band is `ATTESTED`. This rule is not like that. "The observer
states no subject" is true of *the observer*, not of the `DERIVED` band, and the
observer is not the last derived producer this system will have. A validator
binding the subject to a band would be a constraint on producers that do not
exist yet, written in the ADR with the least evidence about them — which is the
form of over-reach ADR-0077 §2 refused when it declined a sensitive-category enum
"on the strength of one producer's need".

There is a second reason, and it is structural: the rule that would be worth
enforcing is "the observer states no subject", and a `core` validator cannot see
which producer built a record. The check belongs where the producer is known,
which is the gate.

### 10. The subject axis and ADR-0098's origin axis are independent

> **Normative.** Whom a belief is about and where its content came from are two
> axes. Neither implies the other, and no lane may read a stated subject as
> evidence of externality, or an `EXTERNAL` source as evidence of a third-party
> subject.

All four combinations are reachable, and two of them are shipped:

| | subject unstated | subject stated |
|---|---|---|
| **internal content** | the ordinary observed or asserted belief | `assistant learn "Marta prefers window seats"` |
| **external content** | every `CalendarReader` proposal today (§4) | a source that states an attendee — none does yet |

ADR-0098 §4's ceiling — "No record whose content or evidence is external is
written in the `ASSERTED` band" — caps *standing*, on the origin axis. The
subject axis caps nothing; it records aboutness. So a belief about a third party
derived from external content is constrained twice over, by two rules that do not
substitute for each other: it may not reach the asserted band because of where it
came from, and it says whom it is about because a producer stated one.

The interaction worth marking is at ADR-0098 §4's fourth ceiling, whose subject
is "a model-authored generalisation about the user". This ADR makes that phrase's
own subject nameable and does **not** make the ceiling enforceable: ADR-0098 §5
shows the clause has no seam to bite at, because `MemoryPolicy.decide` "holds no
store, so it cannot resolve the ids in `Provenance.evidence`". Nothing here
supplies that seam.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**It amends nothing and supersedes nothing.** Every clause above is a **stacked
addition** in ADR-0082 §1's sense — an obligation that contradicts no sentence an
earlier ADR wrote — so the record belongs in this ADR and nowhere else. ADR-0070
§1's test is applied to the four places where the opposite reading is available.

**ADR-0077 §2, and the `Observer` contract it wrote.** §2 rules the observer's
warrant, in prose, with no field. §5 adds a field the rule can be *stated*
against, and a conformance clause pinning a refusal `Observer.observe`'s own bar
already requires. Does a reader holding only ADR-0077 now act differently, or
read a clause of it more widely? No — and the test is worth walking, because §5
does reach `core/protocols.py`. An observer built to ADR-0077 §2 proposes only
beliefs about the user; such a proposal never states a non-owner subject; so
§5's refusal excludes nothing that reader's observer would ever have produced.
Nor does §5 touch the caller's half of that contract: no returned proposal is
dropped, so "the caller puts each returned proposal through the write path, in
order and independently" holds unqualified. The warrant is word-for-word what it
was; §5's first clause says so; and the enforcement gap ADR-0077 §2 acknowledged
of itself is still open, by §5's own admission. **Addition** — a docstring
sentence and a conformance clause that make an existing obligation checkable, not
a widening of what `Observer` requires.

**ADR-0009 §1 and §4.** §1 defines `FeedbackEvent.subject` as an optional scope and maps
it to `PreferenceMemory.context`. §7 adds a *second, differently named* field
beside it and leaves the first untouched in name, type, meaning and destination.
A reader holding only ADR-0009 builds the same `FeedbackEvent` and the same
`PreferenceMemory`. **Addition.** (Whether the older field would be better named
`scope` is §12's, not this ADR's, and it is filed.)

**ADR-0073 §4's enumeration.** ADR-0073 rules the band-scoped read *is* an
enumeration, and §4 fixes what a surface conveys per belief. Adding a field to
`MemoryBase` does not join that list, and a lane must not assume it does in
either direction.

> **Normative.** This ADR adds nothing to ADR-0073 §4's per-belief enumeration.
> Whether a surface renders a subject is §12's deferred rendering question.

With that clause stated, no sentence of ADR-0073 becomes false or over-wide.
**Addition.**

**ADR-0099 §5's deferral.** Discharging a deferral is not amending the ADR that
made it: the deferral's own text names "the next ADR" as its discharge, and a
condition firing as written is the mechanism working. ADR-0099's sentences all
stay true. **Addition, and no record is owed on ADR-0099's `Status` line.**

**No ADR's decision text, header or `Status` line is edited by this lane**, and
neither `VISION.md` nor `CLAUDE.md` is touched. ADR-0099 §7 already ruled what
VISION owes and when — "An amendment becomes owed with §3's federation" — and
this ADR adds no product-shape promise VISION does not already make: a model of
one person, in which other people appear, is what VISION's "relationships" line
already describes.

### 12. Deferred, by name, each with the condition that fires it

- **Subject-scoped delete and export.** ADR-0007 §1's `delete(record_id)`,
  `clear()` and `export()` gaining a dimension, so "forget everything about
  Marta" and "show me everything you hold about Marta" are expressible — **both,
  not just delete**, since ADR-0004 §6's rights are symmetric and ADR-0099 §5
  sequenced them together. **Its dependency is satisfied by this ADR and it is
  not taken here**, because it changes the `MemoryStore` Protocol, which golden
  rule 5 and ADR-0015 §5 put in its own ratified, separately-merged ADR. It is
  the next one. **It is the ADR §6's second clause reserves the matching rule to**
  — "forget everything about Marta" is unanswerable without deciding whether
  `"marta"` is the same subject — and it inherits §8's honest limit: a
  subject-scoped delete cannot reach a record whose subject was never stated.
- **Whether a stated subject scopes conflict detection.** `MemoryIngestor`
  detects conflicts on "same kind, highly similar content", so a third-party
  belief can already conflict with an owner belief and a `SUPERSEDE` can already
  retire the wrong one. **This ADR changes nothing about that**, deliberately:
  ADR-0099 §4 rules that "no ADR may cite this one for a subject-conditional
  supersession rule", and while scoping *detection* is a different question from
  changing the supersession *law*, it is close enough that it deserves its own
  argument rather than a paragraph here. Fires with the first lane that touches
  conflict detection, or with the first reported false supersession across
  subjects.
- **The disclosure floor extended to the subject axis** — that a surface never
  renders the owner's belief about another person as that person's own word.
  ADR-0099 §4 already rules the floor; what is deferred is *rendering*: whether a
  surface must name the subject, and how. Note what it is not: ADR-0099 §1
  ratifies the store as the owner's world model, under which the owner's
  assertion outranking an external report about a third party is correct by
  construction, so this is a rendering obligation and **not** a new supersession
  law. Fires with the first surface that renders a subject, and it is the lane
  that would extend ADR-0073 §4's enumeration (§11).
- **Person identity, enrolment and speaker identification** — what names a
  person, how one is enrolled, how an utterance is attributed. #665's, and
  ADR-0094 §10 keeps it distinct from *device* identity. §6 is written so that
  none of it is presumed: a label that resolves to nothing survives any answer
  #665 gives, including one that introduces handles later.
- **Bystander consent** — what is owed to a person a spoke captures who is not
  the owner. #441 and the capture lane; ADR-0094 §10 holds the trigger ladder and
  the grant model. Ruling that a bystander is a subject rather than a principal
  says nothing about what consent they are owed, and neither does giving the
  subject a field.
- **Federation and what a peer relationship carries** — ADR-0094's reservation
  and ADR-0099 §3's second hub. Nothing here authorises one, and a subject label
  is deliberately unusable as a cross-hub key: it resolves to nothing on the hub
  that wrote it, so it cannot resolve to anything on another.
- **Whether `FeedbackEvent.subject` should be renamed `scope`.** Not taken here:
  it is a `core/types.py` rename, breaking under golden rule 5, and it changes a
  decision ADR-0009 made, so it needs its own ADR rather than a paragraph in this
  one. Filed. Fires if the two fields are shown to be confused in practice, and
  §7's side-by-side naming is the cheap mitigation until then.

## Consequences

- **Two ratified rules acquire a place to put their answer.** ADR-0077 §2 and
  ADR-0098 §4's fourth ceiling are both phrased on this axis; after this ADR the
  honest case is recordable. Neither becomes *enforceable* (§5), and the ADR says
  so rather than letting a later reader infer otherwise from the field's
  existence.
- **An obligation the `Observer` contract already states becomes testable.**
  "A belief is warranted only when it is *about the user*" has been in that
  contract since ADR-0077 with nothing able to check it; §5 turns one breach of
  it into a refusal the conformance suite pins. The dishonest breach is still
  undetectable; the difference is that it now requires lying about a field.
- **The next belief a user writes about someone else can say so**, because §7
  requires the route in the same change. This is the concrete gain, and it is the
  one that decays with delay: every such belief written before the field is a
  subject nobody but the user can ever recover (§8).
- **`assistant learn` gains an affordance and no new authority.** §4's last
  clause is written as a prohibition on *citing this ADR*, because the citation
  is the specific failure it would otherwise cause.
- **Subject-scoped delete and export become specifiable**, which is a gain and an
  obligation: ADR-0007's surface is now known-incomplete with a dependency
  satisfied, rather than known-incomplete with a dependency missing.
- **The store acquires an axis it cannot resolve**, on purpose. Two records
  saying `"Marta"` and `"marta"` are two subjects to every piece of code in the
  system until a lane rules otherwise (§6). That is the cost of keeping person
  identity out, and it is paid in a place — matching — where it can be paid off
  later without rewriting stored data.
- **One more optional field on the envelope every record carries.** The migration
  is mechanical (§8), the wire change is additive, and `export` carries the field
  with no change because it returns `MemoryRecord`.
- **Revisit if** a person registry arrives from #665, at which point §6's label
  is the thing that must either resolve or stay unresolved beside it; or if a
  producer appears that receives a structured subject from its source, which is
  the first case §4's "structured field" clause was written for and has no
  instance of today.

## Alternatives considered

- **Defer again, until a consumer that is not a check exists.** This is the
  corpus's default discipline (ADR-0073 §4) and ADR-0099 §5 applied it. Rejected
  on the Context's argument: the obligation the axis would serve is already
  ratified and already binding on shipped code, which is what the
  surface-with-no-consumer refusals (ADR-0045 §1, ADR-0028 §7, ADR-0092 §10,
  ADR-0097 §1) never had; and the cost of waiting is not deferral but loss (§8).
- **Put the check at the policy gate** — every `MemoryPolicy` rejects a `DERIVED`
  proposal that states a subject. Rejected in §5. `decide` receives no producer
  identity, so the band is the only proxy it has; a band-scoped refusal
  contradicts §2's band-independent axis, binds every future derived producer
  including one that legitimately receives a structured subject, and widens
  `MemoryPolicy`'s behavioural contract for every implementation — charging one
  Protocol's contract to enforce another producer's discipline.
- **Have the observation stage discard a returned proposal that states a
  subject.** Rejected in §5, and it is worth naming because it looks like the
  obvious home: the stage is the one place that knows the proposal came from an
  observer. It fails on the `Observer` contract's own words — the caller "puts
  each returned proposal through the write path, in order and independently" — so
  a required discard is an *exception* to that clause rather than a use of it,
  and exceptions to a seam's caller obligations are how a seam stops meaning one
  thing. The producer refusing is the same outcome with no exception.
- **Ship the field and leave the check to whoever wants it** — a check anything
  downstream *may* make. Rejected in §5. It is the
  deferral's condition claimed and not met: an implementation could satisfy every
  other clause here, install no check, and arrive at exactly the state ADR-0099
  §5 held the field back from — new envelope surface, nothing distinguishing one
  subject from another. A permission is not a consumer.
- **Ship the field and leave the user's route to a follow-up lane**, on the
  ground that `interfaces/` is thin and a flag is not an ADR's business. Rejected
  in §7. The spelling is indeed not this ADR's; the *existence* of a route is,
  because without one `assistant learn "Marta prefers window seats"` still writes
  `about_person=None` and §3 then reads it as the owner's — the field's first act
  would be to make a false record of the case it was added for.
- **Put it on `Provenance`, beside `Attestation`.** Rejected in §2. It reads
  well on authorship — a subject is producer-set, as an attestation is — and it
  fails on subject-matter, which is the criterion both precedents actually used.
  Following authorship alone would put `content` there too.
- **A `Subject` value object rather than a bare field**, in `Validity`'s and
  `Attestation`'s shape. Rejected in §1: those exist to make half-states
  unconstructable across two required halves, and there is one datum here. A
  one-field wrapper would buy nothing and would look like a place to add a
  handle, which §6 refuses.
- **An opaque handle into a person record.** Rejected in §6: it is a person
  registry, it decides #665's question, and it is unbuildable without deciding
  when two mentions are one person.
- **A tuple of subjects.** Rejected in §6. It is a relationship graph one field
  early, and two beliefs about two people split cleanly and delete independently.
- **Name the field `subject` and accept the collision.** Rejected in §7. It is
  unavailable on `FeedbackEvent`, which is the type §7 must extend, and it would
  put a sixth sense of an already five-way overloaded word on the envelope every
  belief carries.
- **Name it `subject_person`, keeping the ratified axis word in the field.**
  Genuinely close, and rejected on the CLI: the axis word is the one the user
  never sees, while `about` is the word the help text and the flag already use for
  the *other* axis. `about_person` puts the disambiguation where the confusion
  actually happens, and reads as the axis's own definition.
- **`None` means unknown rather than the owner.** Rejected in §3. It converts the
  entire existing store into unknown-subject records, so no read about the owner
  is ever total, and it turns a decidable question into a permanent gap — while
  buying only the honesty that §3's "no subject stated" wording already supplies.
- **Constrain the field by band with a validator**, so a `DERIVED` record cannot
  name a subject. Rejected in §9: it is true of the observer, not of the band, and
  it writes a constraint on producers that do not exist yet.
- **Backfill by scanning existing content for names.** Rejected in §8. It is
  person-identification, retroactive, at scale, with no user in the loop.
- **Rule the axis and subject-scoped delete together.** Rejected in §12: delete
  and export change the `MemoryStore` Protocol, and golden rule 5 puts a Protocol
  change in its own ratified, separately-merged ADR. Bundling would also let a
  disagreement about a method signature block a field the store needs first.
