# 133. A producer's read is a third use of a source, and the user grants it separately

- Status: Proposed
- Date: 2026-08-11
- **Note (2026-08-11, UTC): ratified.** `Proposed` → `Accepted` on the content this
  ADR merges with, after both required reviews returned green: adversarial
  **APPROVE with no findings**, and architecture **APPROVE with nits** whose single
  `minor` — a Consequences bullet that compared a two-member scope to a three-member
  one and read as though all three had once been required — is corrected in the same
  commit as this flip. Both lenses are re-run on this ratified tree and `just ship`
  posts their terminal figures to PR #956; the round numbers and churn ratio are
  taken from that comment rather than restated here, so this note cannot disagree
  with it. This edit takes `CONTRIBUTING.md` → "Trivial ADR edits"' exemption for
  the ratification flip and ADR-0015 §5's trivial-ADR exemption; **the correction
  riding with it is made in place rather than appended because this ADR still stood
  `Proposed` when it was written** (ADR-0070 §1 scopes its no-rewrite rule to
  ratified decision text, and ADR-0095 §7 states that adjudication in full). **No
  decision changes**, and no normative clause acquires, loses or alters an
  obligation — ADR-0070 §1's own test applied to the ratifying edit first. From
  here, any further correction is an appended dated note.
- **Partially supersedes: ADR-0097 — §2's enumeration of the uses a grant may
  name.** `GrantScope` has three members, not two. Everything else of §2 stands
  and is what this decision is built on: "A use a grant does not name is not
  authorised by it", the non-empty-scope refusal, the whole-revocation rule, and
  the axis §2 took from ADR-0093 §3. §8 applies ADR-0070 §1's test clause by
  clause and states exactly what is replaced and what survives.
- **Decides `core/types.py` surface and implements none of it.** It adds **one
  member** to an existing `StrEnum` — no Protocol changes, no new type, no
  signature change on `SourceGrants` or `SourceGrantStore` — and it moves
  `PROTOCOL_VERSION` (§6). Golden rule 5 and ADR-0015 §5 put the decision in its
  own PR ahead of the change that implements it, so **no `src/` and no `tests/`
  land with it**.
- **Required review set: adversarial *and* architecture**, even though the PR
  carrying it is prose only. `CONTRIBUTING.md` → "Stop when the required reviews
  are green" states the test — a change is contract-surface "when it is the ADR
  deciding that surface" — and this is the ADR deciding a `core/types.py` member
  that crosses the wire. That is ADR-0097's own reading of its own PR, and
  ADR-0127 is the other side of the same line: it took adversarial alone on the
  stated ground that "**No `core` surface is decided** — no Protocol in
  `core/protocols.py`, no type or member in `core/types.py`, `PROTOCOL_VERSION`
  untouched". All three of those are false here. `scripts/ship.sh` fires its
  architecture requirement on a `core/` **path** in the diff and so will not
  demand it for this PR; the requirement is `CONTRIBUTING.md`'s, and the script's
  own comment says why the two are not the same thing — the check exists because
  the rule "was documented but unenforced".
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `2e2c838f`, not to its status on any later day.
  ADR-0130 and ADR-0131 both read `Accepted` there; ADR-0097, ADR-0093, ADR-0102,
  ADR-0124 and ADR-0089 read `Accepted` there, and ADR-0070 is partially
  superseded by ADR-0127 in a scope this decision does not touch (a `Proposed` ADR
  that is withdrawn). Where a later ADR *changes* one of them, this ADR is read
  against the text quoted here and that ADR's own record says what moved. The
  `Date` line is this ADR's authoring date in this clone's `-0400` frame, the
  convention ADR-0112, ADR-0113, ADR-0129 and ADR-0131 state for their own; the
  base named here is the anchor that does not move under either frame.
- **This decision exists because a lane hit the fork, not because it was
  theorised.** PR #953 was dispatched to decide the first notification producer
  (ADR-0132) and stopped on one question: under ADR-0097 §2's own axis that
  producer's read is a *third* use of the calendar, and both ways of authorising
  it change ratified ground that lane's fence did not reach. The adjudication on
  that PR ruled option A — a third member — and assigned this ADR. ADR-0132 is
  sequenced behind it.
- Refs: #629 (the grant model, leg 11's, which this does not pre-empt), #943 (the
  batch), #891 (the mechanical wire-compatibility check that does not exist).

## Context

### ADR-0130 created a consumer nothing authorises

ADR-0130 §1 mints the proposal artifact for proactive contact:

> **Normative.** A `NotificationCandidate` is the proposal artifact for proactive
> contact: a producer's assertion that the user may be worth telling something
> they did not ask for.

and rules that **any component may produce one**. §7 and §9 make what a producer
concludes durable *when it is kept*: a held record is "retained until retention
removes it", stays enumerable after it expires, and reaches `NotificationStore`'s
export, which ADR-0130 §9 puts there to carry the user's export right. Not every
candidate is kept — §8 rules that "A `DROP` writes no durable record. `HOLD` and
`INTERRUPT` do" — and the exposure is the **possibility**, which is what a consent
question is always about: a producer that reads a source may put a durable,
exportable record into the store, in free text it wrote to be shown to a person,
about whatever it read, and neither it nor the user can know in advance which
candidates will be dropped.

The first such producer reads the user's calendar (ADR-0132). Nothing in the
corpus authorises that read.

### The two members, and the axis they sit on

ADR-0097 §2 is the clause:

> **Normative.** A grant names one or more **uses** from `GrantScope`, whose
> members are `FACET` — reading the source to contribute a `ContextFacet` at
> assembly time — and `INGEST` — reading the source to propose beliefs into
> memory. A use a grant does not name is not authorised by it.

Its supporting text fixes where the axis came from and what a member has to be:

> **The axis is not invented; it is ADR-0093 §3's, promoted to something the user
> can answer.** … "You may look at my calendar to answer what I am asking now, but
> do not remember it" is a coherent sentence, it is one a person actually means,
> and it is the only scope distinction the ratified surfaces can honour today.

Two tests, then. A member must sit on ADR-0093 §3's axis — *one scope per consumer
of a reading* — and it must be a sentence a person actually means. §2 adds a third:

> **Both members have a live consumer**, which is what keeps this from being
> surface with no consumer (ADR-0045 §1, ADR-0028 §7).

A producer's read passes all three. It is a third consumer, distinct from both:
it contributes no `ContextFacet` — ADR-0096 §6 gives the calendar facet three
scalars and it carries no entry text at all — and it proposes no belief, because
`NotificationCandidate` is not a memory record and never enters the memory store.
The sentence is "read my calendar and remember it, but do not raise it with me
unprompted", which is not merely coherent but is the tuning leg 10's exit test
promises: *"the user can tune what reaches them"*. And its consumer is decided,
not imagined: ADR-0130 §10 reserves each producer to its own lane, and ADR-0132
is that lane.

### Why this is not a wider reading of `INGEST`

The available alternative is to rule the producer's read an `INGEST` read: no
`core` change, no re-grant, and ADR-0130 §6's per-class reach already gives the
user a finer control. It is rejected, and the reason is not tidiness.

`INGEST` authorises "reading the source to propose beliefs into memory". Reading
it to conclude something the assistant will say to the user unprompted is not
that, and stretching it there widens a ratified **consent** clause to cover a use
it does not name — ADR-0070 §1's second limb, on the one subject this corpus is
least willing to be approximate about. The concrete cost is a sentence: a user who
grants `INGEST` and refuses proactive contact has no way to say so, because both
uses would be spelled by one word. Under the wider reading the sentence is not
merely unhonoured, it is **unsayable**.

There is a second cost, and it is the one that survives every appeal to the reach
setting. Reach operates *after* the read and *after* the durable record is
written; a class at `hold` — ADR-0130 §6's default for every class — still means
the source was read and a record about it now sits in the notification store,
enumerable and exportable. So a user who used the reach setting to say "do not
raise my calendar with me" would have accepted exactly the reading and exactly the
durable write they were trying to refuse. §4 below states that as a decision
rather than leaving it as an argument.

### The corpus already anticipated a third member, in three places

This is not a decision the tree resists. It was designed for.

- **The enum's own docstring** justifies "exactly two" as "the only scope
  distinction the ratified surfaces can honour **today**". A notification surface
  exists now, so the rationale's own condition has fired.
- **`interfaces/cli.py::_scope_phrase`** renders a scope in words and is total over
  the enum through `assert_never`, with the reason written down: "so a third member
  surfaces at type-check time rather than as a missing phrase". The type checker
  is already holding the place.
- **ADR-0102 §5's revocation sweep** queries `SourceGrants.live` for every member
  of `GrantScope` and says in its own supporting text that it "stays total as the
  enum grows because it is written over the enum rather than over its members".

Three places where a later hand would otherwise have had to guess, all of them
already answered. What is *not* answered anywhere is the consent question, which
is this ADR's.

### An honest statement of what this ADR is not allowed to settle

**The grant-management surface is leg 11's, not this decision's.** #629 records the
gap — "a sensor may be enabled with no grant" — and the roadmap files sensor
breadth and the grant model together in leg 11. This ADR adds a **member to a
vocabulary**; it decides no grant model, no source registry, no content-level
scope, and no client flow.

**Which producers exist is ADR-0132's.** ADR-0130 §10 reserves it, and nothing
below names a producer, a class, a cadence or a lead window.

**Nothing here reaches delivery.** ADR-0130 §1 rules that producing a candidate
reaches nobody and ADR-0131 owns the seam. A grant governs a *read*; it has never
governed an act, and ADR-0097 §7 forbids it being read as one.

## Decision

### 1. `NOTIFY` is the third use, and it authorises exactly one thing

> **Normative.** `GrantScope` gains a third member, `NOTIFY`: **reading the source
> so that a producer may conclude a `NotificationCandidate` about what it read.**
> ADR-0097 §2's remaining clauses are unchanged and govern it — a use a grant does
> not name is not authorised by it, a grant's scope is non-empty, and a revocation
> revokes a grant whole.

> **Normative.** `NOTIFY` authorises a **read**. It authorises no contact, no
> disposition, no delivery and no channel, and no implementation may consult it
> for any of those. A candidate concluded under a live `NOTIFY` grant is ruled by
> ADR-0130 §5 exactly as any other candidate is.

**The name is chosen for the user's vocabulary, because that is what a
`GrantScope` member is.** ADR-0097 §10 fixes the enum as "a stable, serialisable,
**user-facing** vocabulary", and the sentence the member has to make sayable is
"do not raise it with me unprompted". The word a person already owns for that is
*notify* — it is the word on every device they have used — and the member should
be spelled in the user's language rather than in the chassis's. `NOTICE` was the
close alternative and is weighed in Alternatives considered.

**The second clause is what keeps the name from overclaiming**, and it is a real
hazard rather than a hypothetical one. A member named `NOTIFY` reads as though
granting it decides that the user will be notified, and it does not: ADR-0130 §1
rules that producing a candidate reaches nobody, and §6 defaults every class to
`hold`. `NOTIFY` sits where `FACET` and `INGEST` sit — it names **the use a
reading is put to**, not the outcome that follows. `INGEST` is the precedent
already in the tree: it authorises *proposing* beliefs, and `MemoryPolicy` may
still reject every one of them. So the discipline is the corpus's, applied to a
third member: the scope gates the read at the read, and ADR-0097 §7's rule that "a
source grant is not an action authorisation" is neither relaxed nor extended.

### 2. Refusing it forecloses unprompted contact from that source, and granting it implies neither other use

> **Normative.** Where no live grant names `NOTIFY` for a source, that source is
> **not read** to conclude a notification candidate. Nothing is opened, on
> ADR-0097 §5's rule for the other two uses: the source is not resolved, not
> opened and not parsed.

> **Normative.** The guarantee is over the **read**, and it is not a guarantee
> that nothing the user is ever told can be traced back to that source. A record
> some other use lawfully wrote — a belief an `INGEST` read proposed — is a record
> in memory, and a producer that reads memory reads memory. The absence of a
> `NOTIFY` grant is not a filter over records already stored, and no
> implementation may read it as one; a producer over such records is bounded by
> its own decision and by ADR-0130 §5, not by this member.

> **Normative.** `NOTIFY` implies neither `FACET` nor `INGEST`, and neither of
> them implies `NOTIFY`. A grant's scope may name any non-empty subset of the
> three, and it authorises exactly the uses it names. No implementation may infer
> one member from another, **rank** them, or treat any of them as a superset of
> another. The declaration-order normalisation `SourceGrant.scope` carries (§6) is
> a serialisation convention and is not a rank: it decides how two implementations
> write one grant down, and nothing may read a precedence, a severity or an
> authority relation off it.

**Refusal is the property this member exists for, so it is stated first.** A user
who declines `NOTIFY` on their calendar has bought a guarantee with a shape: the
assistant will not read that calendar in order to raise something with them, so no
durable record about it can be written, held, or later delivered *from that
reading*. Under a widened `INGEST` that guarantee has no expression at all; under
this member it is the ordinary meaning of ADR-0097 §2's surviving sentence.

**The second clause bounds that guarantee where the corpus has already bounded
it, rather than promising more than a grant has ever bought.** ADR-0097 §6 is the
settled precedent and it is emphatic: "Revoking a grant retires no belief, closes
no validity window, deletes no record and alters no stored record. Its whole
effect is that §5's check stops passing." A grant's reach ends at the read, in
both directions — a revocation does not unwrite what an authorised read produced,
and a refusal does not reach back over it either. Promising otherwise here would
require what ADR-0097 §12 has twice deferred: per-belief grant attribution, which
"needs a pointer field on `Attestation`", and "revoke and forget everything this
source told me", which needs an enumeration of beliefs by `reported_by` that
ADR-0092 §10 declined to add. Neither surface exists, so a guarantee resting on
them would be a sentence with no mechanism — and would be the first place in this
corpus where a grant reached past the read.

**The residual is therefore named rather than papered over.** A producer reading
memory can conclude a candidate about something the user's calendar said, on the
strength of a belief an `INGEST` grant authorised, with no `NOTIFY` grant
anywhere. That is a real gap in the sentence "do not raise my calendar with me",
and it is the same gap ADR-0097 §6 already accepted when it ruled revocation
prospective. What closes it is provenance the corpus has deferred with its firing
condition attached, not a clause here; §7 records it as undecided, and until then
ADR-0130 §6's reach level is the control that reaches such a producer, which is
one more reason §4 keeps both.

**Independence is ADR-0093 §3's axis held rather than restated.** That section
rules that a reading's consumers read "at their own cadence" and that "neither may
derive its answer from the other's reading". One scope per consumer is what makes
that legible to a user, and an implication between members would collapse two
consumers into one grant — which is precisely the collapse §2 refused when it
declined to make `INGEST` cover the facet. There is nothing to rank here either:
ADR-0097 §10 refuses an order over the members because "two uses of a source are
not comparable and an order would invite a `max()` that means nothing", and a
third use is not more comparable than the second was.

### 3. Adding the member authorises nothing that was granted before it

> **Normative.** No existing grant is migrated, back-filled, re-interpreted or
> widened by the arrival of this member. A grant recorded before `NOTIFY` existed
> names the uses it names, so it does not authorise `NOTIFY`, and no lane may
> write a record on the user's behalf to change that. Authorising the third use is
> a user act in ADR-0097 §1's sense, taken through ADR-0102's grant operation, and
> ADR-0097 §2's two-act form — revoke, then grant — is how a live grant acquires
> it.

**This is the clause that makes the change inert until the user acts, and it
follows from the sentence §2 keeps rather than from anything new.** "A use a grant
does not name is not authorised by it" already decides it; it is marked here
because the opposite reading is available and cheap. A lane holding a store full
of `(FACET, INGEST)` grants and a new member could reasonably think it was being
helpful by treating an existing `INGEST` as covering the new use — which is
exactly option B, re-entering through the implementation door after being refused
at the decision door.

**The cost is named rather than hidden: every user with a live grant must grant
again to get proactive contact from that source.** On a single-user local machine
that is one act. It is also the correct act, because the new use is one the user
has never been asked about, and ADR-0097 §4's append-only store is what makes the
two records — the revocation and the wider grant — legible afterwards as a thing
the user decided on a day.

### 4. The grant and the reach level are two acts on two axes, and neither subsumes the other

> **Normative.** The `NOTIFY` grant and ADR-0130 §6's per-class reach level are
> independent controls and neither is a substitute for the other. The grant is
> **per source**, is a recorded user act on an append-only store, and gates the
> **read**. The reach level is **per notification class**, is durable user state
> in the notification store, and gates **how loudly a disposed candidate arrives**.
> No implementation may derive one from the other, default one from the other, or
> treat a reach of `off` as a revocation.

**Reach cannot do the grant's work, for two reasons and the second is decisive.**
It is keyed on the wrong thing: ADR-0130 §6 rules a class "declared by its
producer", "not a configurable value" and "not a closed enumeration", and nothing
binds a class to a source — one producer may read one source and declare one
class, but a class is not a source's name and a user setting it has not said
anything about a source. And it operates too late: reach is read when a candidate
is *disposed*, which is after the source was opened, after it was parsed, and (at
`hold`, the shipped default for every class) after a durable, exportable record
about it was written. ADR-0130 §6's `off` sweep drops *held records*; it stops no
read. A control that can only mute what has already been read is not a control
over reading, and reading is what a grant is about — ADR-0097 §5 says so in as
many words: "a design that reads the file and then declines to propose from it has
already done the thing it was not permitted to do, and it does it on the
schedule."

**The grant cannot do reach's work either, which is why this is a composition and
not a replacement.** It is binary and per source, so it cannot express "tell me
about starts but hold the rest" — that is a class distinction and reach owns it.
It does not reach a producer that reads no granted source at all: ADR-0130 §11
names the deferral queue as an ordinary producer lane, and such a producer reads
the system's own store, so no grant governs it and reach is its only control. And
it is the wrong instrument for a preference: revoking a grant to quieten a
notification would destroy the authorisation to read, which ADR-0097 §6 makes
prospective and whole and which the user would then have to rebuild.

> **Normative.** A producer that reads no granted source needs no grant under this
> decision, and this decision authorises no read that ADR-0097 §5 does not already
> gate. `NOTIFY` governs a read of a source in ADR-0097 §1's sense — a `Reader`'s
> declared identity — and nothing else.

**Read together, the two controls answer two different questions and a user can
tell which is which.** *May this source feed me things I did not ask for at all?*
is the grant, and refusing it is a statement about the user's data. *How loudly
does this kind of thing arrive?* is the reach level, and setting it is a statement
about the user's attention. Leg 10's exit test asks for the second; leg 6's
`VISION.md` promise — "granted, scoped, and revocable" — asks for the first. A
system with only one of them can answer only one of those questions.

### 5. The check is the producer's driver's, held by construction

> **Normative.** The check for `NOTIFY` is the **caller's**, in ADR-0097 §5's
> sense: the site that drives the reader on the producer's behalf. A `Reader`
> neither holds a grant seam nor learns of one, and `Reader`'s surface is
> unchanged (ADR-0093 §1, §10). That site takes a **`SourceGrants`** — the query
> seam, never `SourceGrantStore` — as a required constructor argument with no
> default, exactly as ADR-0097 §5's third clause already requires of every site
> that drives a reader.

> **Normative.** ADR-0097 §5a's three driver rules apply to a `NOTIFY` read
> unchanged and without exception: no `await` between the `live()` answer and the
> call to `Reader.read()`; a re-check when `read()` returns, with the reading
> **discarded** if the grant has gone — nothing concluded from it, no candidate
> produced from it; and fail-closed on an unanswerable check.

**Nothing here is new machinery, and that is the point.** ADR-0097 §5's first and
third clauses are written over "a reader" and "every site that drives a reader",
not over the two uses that existed when they were written, so the third use lands
inside them. What §5 did not say is who checks a use that did not exist, and §8
classifies that as a stacked addition rather than an amendment: no sentence of §5
becomes false, and one it never wrote is supplied here.

**The discard limb is the one worth marking rather than assuming.** For `INGEST`
the reading is discarded by proposing nothing, and for `FACET` by contributing
nothing; the producer's equivalent is concluding nothing — and because ADR-0130 §3
makes producing and persisting one call, a producer that concluded first and
checked afterwards would already have written the durable record. So the re-check
lands before the conclusion, in the same place the other two drivers put it.

### 6. The contract surface this decides, and what the implementing lane owes

Names below are ratified as **shape, not spelling**, in ADR-0073 §7's form. The
claims about the tree are stated as of this ADR's base, `2e2c838f`.

> **Normative.** `core/types.py`'s `GrantScope` gains one member, `NOTIFY`,
> **appended after `INGEST`**. Declaration order is what `_grant_scope` normalises
> a scope to and what `_SCOPE_ORDER` is read off, so a member is added at the end
> and never inserted: the order stays a record of when each use was decided.
> Nothing else about the enum changes — it stays a plain unordered `StrEnum`
> (ADR-0097 §10), the empty and duplicate refusals are untouched, and
> `SourceGrant` gains no field.

> **Normative.** The same change bumps `PROTOCOL_VERSION`, under ADR-0124 §9's
> second limb: "a change to a wire-carried `core` type that makes a value one peer
> emits invalid for the other, whether the change widens or narrows the type". It
> bites in both directions — a new client's `grant` argument carrying `"notify"`
> is refused by an old hub, and an old client decoding a `SourceGrant` result whose
> scope names `"notify"` is refused at the client, which `wire/codec.py`'s
> `grant_scope` names in its own docstring ("A wire client decoding an unknown
> string for a scope member meets the same value"). ADR-0124 §9 makes compliance a
> **review obligation** on the change and decides no mechanical check; #891 carries
> the check that does not exist.

> **Normative.** `SourceGrants` and `SourceGrantStore` are **unchanged**. `live`
> already takes a `use` and needs no signature change, `record`/`recent`/`export`/
> `clear` are untouched, and no Protocol in `core/protocols.py` is edited. This
> decision adds no Protocol and no triad.

> **Normative.** The implementing lane also owes, in the same change: the
> `GrantScope` docstring's "exactly two members" rationale rewritten to three and
> citing this ADR; a phrase for the new member in `interfaces/cli.py`'s scope
> rendering, which `assert_never` already fails the type check without; a case in
> the shared source-grant conformance suite asserting that a grant naming `NOTIFY`
> does not answer `live` for `FACET` or `INGEST`, nor either of them for `NOTIFY`
> — §2's independence, held on every implementation; and a test that a
> **`NOTIFY`-only live grant is revoked** by the grant operation, so ADR-0102 §5's
> sweep is held total over the member that was added rather than over the two that
> were there when it was written.

**The revocation test is asked for by name because the wrong implementation passes
every test that exists**, which is ADR-0102 §5's own stated reason for marking the
sweep at all. The concrete regression is small and silent: a `_live` helper written
over `(FACET, INGEST)` instead of over `GrantScope` finds no `NOTIFY`-only grant,
so `revoke` returns `None`, the caller is told there was nothing to withdraw, and
the grant stays live. The independence case above would not catch it — it calls
`live` directly — and the existing revocation coverage exercises `INGEST`. The
tree's current `_live` is already written over the enum and says so in its own
docstring; what is missing is the test that keeps it that way.

> **Normative.** No enforcement site lands with the member. The gate of §5 lands
> with the producer that needs it (ADR-0132), and until then no lane may read a
> granted source to conclude a notification candidate — with or without a
> `NOTIFY` grant, and whatever an existing `FACET` or `INGEST` grant says.

**Where the member lands is sequenced, not free.** ADR-0102 §5's revocation sweep
is written over the enum and stays total as it grows, so nothing about revocation
changes; but `core/types.py` has one holder at a time in this project's working
model, so this member is a small lane behind the in-flight `core` work rather than
a change slipped in beside it.

**A member with no code consumer for one lane's duration is the sequencing rule's
cost, and it is worth naming because ADR-0097 §2 refused speculative surface.**
The refusal there was of a member with no consumer *decided* — a scope enumerating
entry kinds that "would be a schema with no reader on either side of it". This is
the opposite case: the consumer is decided (ADR-0130's producer class), its first
instance is ADR-0132's and is sequenced behind this one, and golden rule 5 is
what puts the vocabulary ahead of it. The window is also benign in both
directions: while no producer exists, a granted `NOTIFY` authorises a read
nobody performs, and a refused one forecloses a read nobody was going to
perform. The last clause above
is what keeps it benign — the hazard is not the idle member, it is a producer
landing that reads without the gate.

> **Normative.** The member is **offered from the moment it exists**, and the
> client's existing grant surface carries it with no gate. Its `--scope` option is
> typed over `GrantScope`, so it accepts the new value by construction; the option's
> help text, which today enumerates the two uses in words, names all three; and the
> confirmation the user is shown before the grant is recorded renders it through
> the scope phrasing above. No lane may suppress the member from that surface while
> it is in the enum: an option that silently refuses a member of its own type, or
> a help string enumerating two of three uses, is a surface disagreeing with the
> vocabulary — which is the failure ADR-0097 §8 names when it forbids anything
> deciding what the user permitted on their behalf.

**This is decided here rather than deferred, because the tree leaves no third
option.** An earlier draft left the offer to `interfaces/` shaping; that was wrong
on the facts. `assistant grant --scope` is annotated `list[GrantScope]`, so the
member is accepted the instant it is declared, and the only way *not* to offer it
would be to add a refusal that does not exist today. Deferring the question would
therefore have deferred nothing and left a help string quietly incomplete instead.
What stays leg 11's is the grant-management **surface** — how sources are
presented, how a grant is amended, what a user is shown about their standing
grants — which #629 holds and which this member joins rather than reshapes.

### 7. What this ADR does not decide

- **The grant-management surface.** #629 and leg 11 hold it. This adds a member to
  a vocabulary; it decides no grant model, no source registry, and nothing about
  how sources are presented, how a grant is amended, or what a user is shown about
  the grants they hold. §6 decides only that the existing client surface carries
  the new member rather than hiding it — which the option's own type already
  settles — and nothing beyond that.
- **Content-level scope.** ADR-0097 §12's first deferral is unchanged and
  unnarrowed: which entries, which fields, which calendar is still deferred with
  the condition that fires it, and a third *use* is not a step toward a sub-source
  selector.
- **Which producers exist, and what any of them notices.** ADR-0130 §10 reserves
  it and ADR-0132 takes the first one. No class, cadence, lead window or expiry is
  decided here.
- **Whether a spoke reporting across the process boundary needs a grant.**
  ADR-0097 §12 defers "a grant for something that is not a `Reader`" and this
  decision does not fire it: §4's last clause keys `NOTIFY` on a reader's declared
  identity exactly as §1 of ADR-0097 keys a grant.
- **Anything about delivery.** ADR-0131 owns the seam; §1 above forbids reading
  the scope for any part of it.
- **Whether a refused `NOTIFY` reaches records another use lawfully wrote.** §2's
  second clause rules that it does not, and names why: the surfaces that would
  carry provenance are ADR-0097 §12's two deferrals, each with its firing
  condition already attached. Widening the guarantee is that lane's, and it would
  reach every grant rather than this member.
- **A fourth member.** The axis admits one scope per consumer of a reading, so a
  fourth arrives with a fourth consumer and with its own decision — not by
  analogy with this one.

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text, where it is reviewed, and
fixes the test: *would a reader holding only the earlier ADR now act differently,
or read one of its clauses more widely than it now holds?* Applied clause by
clause, to the five places the opposite answer is available.

**ADR-0097 §2 — partially superseded, and this is the whole of what is replaced.**
Replaced: the enumeration inside §2's first marked clause — "whose members are
`FACET` … and `INGEST`". A reader acting on that sentence builds a two-member
enum, refuses `"notify"` at its boundary, and concludes that a producer's read is
authorised by one of the two or by nothing. All three are now wrong, and that is
the exhaustive extent of the change. **Not replaced — which is nearly all of §2,
and this decision depends on every part of it.** "A use a grant does not name is
not authorised by it" is what §3 above rests on. The non-empty-scope refusal
stands and now has three members to draw from. The whole-revocation clause stands
and is what §3's two-act form uses. And §2's *axis* is not replaced but extended
along its own line — one scope per consumer, a third consumer, a third scope.
§2's supporting text is unmarked, so under ADR-0089 §3 it obligates nothing and is
read to determine what the marked clause means; its "exactly two of them" and its
"the only scope distinction the ratified surfaces can honour today" move with the
clause they explain rather than being separately superseded. The same is true of
§10's restatement of the enum as having "exactly two members": it is an unmarked
bullet in the section listing what the triad lane owed, that lane has landed, and
it reads as evidence of §2's meaning rather than as an obligation of its own.

**ADR-0097 §5 and §5a — a stacked addition, no record owed.** §5's first clause is
written over "a reader … for a use" and its third over "every site that drives a
reader"; both reach the third use without a word changing. What §5 does not do is
name the caller for a use that did not exist, and §5 above supplies one. ADR-0082
§1: "Adding an obligation that contradicts no sentence the earlier ADR wrote is a
stacked addition: it is recorded in the ADR that makes it, and nowhere else." No
sentence of §5 or §5a becomes false or over-wide, so no record is written on
ADR-0097's status line for them — the line records §2's supersession alone.

**ADR-0093 §3 — nothing owed, and the reason is the mark.** Its heading and its
prose say "two consumers", but its marked clause rules something narrower: "A
sensor's two consumers read at their own cadence: the context facet reads at
assembly time, and ingestion reads on its schedule. Neither may derive its answer
from the other's reading". That is a cadence-and-non-derivation rule over the two
consumers it names, not a census of how many a reading may have. Both sentences
stay true after this decision — the facet still reads at assembly, ingestion still
on its schedule, and a producer deriving its answer from either would be
prohibited by the same principle rather than permitted by its silence. ADR-0093 is
a marked ADR (it carries normative clauses and postdates ADR-0089), so under
ADR-0089 §3 its unmarked "two legitimate consumers" supplies no obligation to
contradict. No status edit and no note.

**ADR-0102 §5 — nothing owed, and its own text says so.** Its revocation sweep
queries `live` "for **every** member of `GrantScope`", and its supporting text
already scopes itself against exactly this change: the sweep "stays total as the
enum grows because it is written over the enum rather than over its members". A
reader acts identically before and after. Likewise ADR-0102's four engine
operations: `grant` takes a `Sequence[GrantScope]` and needs no change to carry a
third member.

**ADR-0130 and ADR-0131 — nothing owed and nothing read across.** ADR-0130 is
applied rather than narrowed: §1's producer posture, §5's ruling path, §6's reach
levels and §7's durability are used exactly as ratified, and §4 above composes
with §6 without replacing a word of it. ADR-0130 makes no claim about grants at
all — the word does not appear in it in this sense — which is the gap this ADR
fills rather than a clause it moves. ADR-0131 governs delivery, which §1 above
puts out of reach of the scope.

**ADR-0124 §9 — applied, not amended.** §6 above discharges its review obligation
by naming the bump in the change that causes it, which is the compliance §9 asks
for. Its declining to decide a mechanical check is untouched and #891 still
carries one.

**This ADR's own `Status`.** It decides `core/types.py` surface, so its required
set is adversarial *and* architecture (header), and ADR-0015 §5's
ratify-after-review sequencing reaches it: it was drafted and reviewed as
`Proposed`, and its status flipped only once both required reviews had returned
green. The record of that flip is the dated note in the header, per ADR-0070 §1.
Nothing implements against §6 until this has merged.

**ADR-0097's record lands in this change rather than at this ADR's ratification,
and the corpus has adjudicated that question twice already.** The reading that a
`Proposed` ADR may not carry a supersession record cites ADR-0070 §1's "a
supersession that has landed", and ADR-0082 §7 names it by number: "**#458 — the
recurring misreading of ADR-0070 §1's 'a supersession that has landed' clause.**
Not a governance gap but a reviewer failure mode … §1's condition is that the
superseding ADR **exists**, not that it is ratified — the hazard §1 names is a
`Status` line pointing at nothing, and an atomic pair makes that unreachable."
`CONTRIBUTING.md` carries the same sentence — "Recording a supersession likewise
presupposes the superseding ADR exists" — and ADR-0131 records the argument
deadlocking PR #478 and recurring on PR #945, where the two lenses took opposite
positions in consecutive rounds. The pair here is atomic: ADR-0097's `Status` and
this file land in one merge, so at no instant does that line point at nothing. The
citation is repeated here because ADR-0131 asked that a further recurrence "cost
the next author a citation rather than a round"; it cost this one a round, which
is why **#957** files the rubric fix.

## Alternatives considered

- **Rule the producer's read an `INGEST` read** (option B on PR #953). Rejected in
  Context and in §4: it widens a ratified consent clause to cover a use it does not
  name, and it makes "read my calendar and remember it, but do not raise it with me
  unprompted" unsayable — the sentence ADR-0097 §2's own test asks for. Its real
  attraction, that ADR-0130 §6's reach already gives finer control, is answered by
  §4: reach is read after the read and after the durable write, so it cannot carry
  a refusal of reading.
- **Name the member `NOTICE`.** It fits ADR-0130's internal vocabulary well — that
  ADR speaks of the noticer, of noticing and of re-noticing — and it does not
  overclaim delivery, since noticing is exactly what the producer does. Rejected
  on the ground ADR-0097 §10 states for the enum: it is a **user-facing**
  vocabulary, and "notice" is ambiguous in ordinary English between the verb and a
  posted notice, while "notify" is unambiguous and is the word the user has already
  met on every device they own. The overclaim `NOTICE` avoids is closed instead by
  §1's second marked clause, which is a better place for it — the guarantee lives
  in a sentence a reader can quote rather than in the connotation of a token.
- **Name it `PROACTIVE`, `ALERT` or `INTERRUPT`.** `INTERRUPT` is taken: it is a
  reach level in ADR-0130 §6 and a disposition kind in §5, and reusing it across
  two axes is exactly the confusion §4 exists to prevent. `ALERT` implies urgency,
  which ADR-0130 §11 explicitly declines to let anything self-declare.
  `PROACTIVE` describes the system's posture rather than the use a reading is put
  to, which is what the other two members name.
- **Add an optional `SourceGrant` field instead of an enum member** — a boolean or
  a sub-scope saying "may feed notifications". Rejected: it would put two
  vocabularies for one axis in one record, and ADR-0097 §2 already fixes the axis
  as membership of `GrantScope`. It would also make the third use invisible to
  ADR-0102 §5's sweep and to `_scope_phrase`'s exhaustive rendering, both of which
  are total over the enum and neither of which would learn about a new field.
- **Defer the member until the first producer needs it, and land both together.**
  Rejected by golden rule 5 and ADR-0015 §5: a `core/types.py` change ships as its
  own ratified decision ahead of what implements against it. The window this opens
  is named and bounded in §6.
- **Rule the producer's read a *fourth* thing — an unauthorised read that the
  policy alone bounds.** Rejected because it is option B without the honesty: it
  reads the user's source under no named authority at all, and `VISION.md`'s
  "granted, scoped, and revocable" is a property of the read, not of what is done
  afterwards.

## Consequences

**Easier.**

- **A sentence a person means becomes sayable.** "Read my calendar and remember
  it, but do not raise it with me unprompted" is a grant naming `INGEST` and
  withholding `NOTIFY`, written in the vocabulary the user already grants in.
  Before this decision its second half had no expression at all — there was no
  member to withhold.
- **Leg 10's exit test gets its tuning axis without borrowing another one.** The
  user tunes *what reaches them* with reach levels and *what may feed them* with
  the grant, and the two answers cannot be confused for each other.
- **The producer lane unblocks with its authority named.** ADR-0132 resumes
  against a member that exists rather than against a fork, and its §2 can require
  the scope by name.
- **The change is inert until the user acts.** §3 means no existing grant silently
  acquires a use nobody was asked about — the property that makes an append-only
  consent store worth having.
- **Three places in the tree that were written for this stop being conditional.**
  The enum docstring's "today", the CLI's `assert_never`, and ADR-0102 §5's sweep
  were each written against a third member arriving; one of them is now exercised
  rather than merely anticipated.

**Harder.**

- **Every user with a live grant must grant again to get proactive contact from
  that source.** §3 makes that deliberate and ADR-0097 §2's two-act form makes it
  two records rather than one; on a single-user local machine it is one act, and
  it is the act the user has never been asked to perform.
- **The protocol version moves for one enum member.** ADR-0124 §9's rule is
  directional and this is squarely inside it, so client and hub must be upgraded
  together — which after the hop means two machines. The alternative is a silent
  decode failure inside a `grant` call, which is the outcome ADR-0084 §3's
  handshake exists to replace.
- **A member exists before its consumer does.** §6 bounds the window and names the
  hazard it does not tolerate, but for one lane's duration the grant surface can
  offer a use nothing performs. That is golden rule 5's cost, paid here in the
  cheapest place it can be paid.
- **A refusal is a refusal of the read, and a user may reasonably hear more in
  it.** §2's second clause is honest about the gap — a producer over memory can
  conclude about what an `INGEST` read put there — and that gap is ADR-0097 §6's,
  inherited rather than created. It is the strongest argument for the provenance
  ADR-0097 §12 defers, and it should be cited when that deferral's condition next
  looks like firing.
- **`GrantScope` is now a vocabulary that will keep growing.** Each new consumer
  class of a reading is a new member and a new user question, and the enum's
  friendliness degrades with its length. §7 declines a fourth member by analogy for
  that reason: the next one arrives with its own consumer and its own argument, or
  not at all.
