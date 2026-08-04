# 99. One hub, one principal: a household member is a subject in the owner's model, not an account on the owner's hub

- Status: Proposed
- Date: 2026-08-04
- **Decides a scope and adds no surface.** No Protocol, no type, no field, no
  code. It ratifies the framing every existing decision already leans on — the
  store is **the owner's world model** — and settles the one question that
  framing leaves open in a house with more than one person in it: a second
  person is a **subject** the model holds beliefs *about*, never a second
  **principal** the hub answers *to*.
- **Required review set: adversarial *and* architecture**, even though the PR
  carrying it is prose only and touches neither `core/protocols.py` nor
  `core/types.py`. ADR-0094 took the same set for the same shape of change — a
  scoping and vocabulary ruling that added no surface — and this one bounds
  every `core` decision that comes after it, including the subject axis §5 sends
  to its own ADR. Reviewed while `Proposed` and ratified only after, in a
  separate lane (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"; #633 records why the flip cannot ride in the PR that carries
  it).
- **Amends no earlier ADR and supersedes none**, and §6 applies ADR-0070 §1's
  test and ADR-0082 §1's record rule to the two places where the opposite
  reading is available: ADR-0058's scoping of its own threat model, and
  ADR-0097 §12's deferral of **Who granted**.
- **It ratifies a premise the corpus already leans on, and records that the
  premise is currently filed against an ADR that does not contain it.**
  ADR-0058 scopes a rejection to "ADR-0002's single-user local-first model" and
  ADR-0059 scopes an issue the same way; ADR-0002 as merged decides
  "Local-first by default" and contains the word "user" nowhere. §6 states the
  finding, declines to fix another ADR's text from this lane, and files it.
- **Decided with no producer in hand, deliberately — which is why it decides so
  little.** ADR-0073 §4's "with a producer in hand" discipline is why §5 defers
  the subject axis rather than inventing a field for it. What this ADR does is
  fix the *frame* a later lane designs that field inside, because the frame is
  the thing that gets fixed by default — by drift — if nobody fixes it on
  purpose.

## Context

### Nothing in the corpus models whom a belief is *about*

The bands encode how a belief was **learned**. ADR-0072 partitions one store
into `ASSERTED`, `DERIVED` and `ATTESTED`; `Provenance` answers "why is this
held?"; ADR-0092 §1 hangs an `Attestation` off it to answer "what reported it,
and when that source said so". ADR-0045 §2 puts a `Validity` window on the
envelope to answer "when is this live".

No field answers **about whom**. There is no subject anywhere in `core/types.py`
and none in any Protocol. So every belief the store holds is implicitly about
one person, and which person that is has never been written down.

### That is tolerable only under a framing nobody has ratified

The framing is that the store is **the owner's world model** — an account of
what one person's assistant believes, in which other people appear as content.
Under it, an unqualified belief is about the owner by default, and a belief
about someone else is still the owner's belief about them.

The phrase "world model" appears nowhere in `docs/`, `VISION.md` or `README.md`
as of this ADR's date. The framing is load-bearing and unwritten, which is the
condition this corpus treats as a defect rather than a convenience.

### The channel is already open, and this is not a future problem

`assistant observe` is a shipped CLI command in `interfaces/cli.py`. It needs no
configuration and no grant, it defaults to the most recently active
conversation, and it asks the engine to distil beliefs from that conversation's
turns (ADR-0077). Say "my wife prefers window seats" in a conversation, run
`observe`, and what lands is a belief that is *about* someone else and
structurally indistinguishable from a belief about the owner.

Read-only ingestion widens that channel; it does not open it. The one thing
that would make this an ADR to write later rather than now is if nothing could
yet produce a third-party belief, and something already can.

### Three consequences follow, and only the first is this ADR's

1. **Third-party beliefs already exist as a possibility**, per above. This ADR
   rules the frame they sit in.
2. **Deletion and export by subject are unimplementable.** ADR-0007 §1's surface
   is `delete(record_id)`, `clear()` and `export()` — one record, everything, or
   the whole store. "Forget everything about Marta" has nothing to index on.
   §5 defers this; it needs the axis first.
3. **Supersession has what looks like a cross-subject hole.** ADR-0092 §4 makes
   a user assertion retire an `EXTERNAL` belief. So the owner asserting "Marta
   prefers aisle seats" retires Marta's own attested report that she prefers
   window seats, and the owner's word wins unconditionally. §4 rules that this
   is correct, and that what the case actually exposes is a **rendering**
   obligation rather than a supersession one.

### What the corpus already assumes, and where the assumption is filed

Nothing ratifies single-principal, but a great deal depends on it:

- ADR-0036 §3 records that the permission layer "records that a human answered,
  not which human" (#113) — `resolve` takes a boolean.
- ADR-0097 §1 rules that "the grant is not keyed to a user, and that is a
  property of this system rather than an omission", and §12 defers **Who
  granted** with the firing condition "the first multi-user deployment".
- ADR-0004 reasons about "a single-user local app" when choosing an encryption
  default.
- ADR-0058 rejects an executor-level audit check because "under ADR-0002's
  single-user local-first model there is no second party in the process for the
  gate to defend the user against", and scopes the whole decision that way.

The last of these cites an ADR that does not say it (§6). Taken together the
corpus has been *relying* on single-principal for dozens of decisions while
attributing it to a document that decided persistence, not people. This ADR
supplies the ruling those decisions have been standing on.

### Why now, and why this cheaply

The value of ruling it now is what it forecloses. The default shape a household
drifts toward is Alexa's: accounts on one device, per-account voice profiles,
per-account permissions, a shared store with an access-control dimension. Every
one of those is a change to a ratified invariant — one user model (ADR-0072),
one supersession law (ADR-0038, ADR-0092), one delete and export right
(ADR-0007), one set of grants (ADR-0097). Reaching that shape by drift means
discovering the invariants were broken after something depends on the break.
Ruling it costs a page.

## Decision

### 1. The store is the owner's world model, and the hub has exactly one principal

> **Normative.** A hub has exactly one principal: the owner. The owner is the
> single person whose word is `USER_ASSERTED`, whose delete and export rights
> ADR-0007's surface discharges, and whose grants ADR-0097 records. No decision
> may add a second principal to one hub — a second account, a second asserting
> identity, or a second set of data rights — without superseding this clause.

> **Normative.** Every belief the store holds is a belief *of the owner's
> model*: it records what this assistant holds on the owner's behalf, and never
> purports to record what is true of another person independently of the owner.

The second clause is the framing, stated as an obligation because a reader can
disobey it — by building a store that claims to hold the truth about a
household, arbitrating between its members, or serving one member's query from
another member's beliefs. None of those is this system.

**This is a ratification, not a new constraint.** Every clause above describes
what the tree already does; what changes is that it is now decided rather than
assumed, so a lane that wants otherwise argues a supersession instead of filling
a silence.

**It does not foreclose multi-principal in general.** ADR-0058's revisit
condition — "a multi-principal or multi-tenant deployment where the caller of
the executor is no longer identical to the principal the trail records" — and
ADR-0097 §12's "fires with the first multi-user deployment" both stand exactly
as written. What this ADR rules is that a *household member* is not the route by
which that day arrives (§3). Should it arrive by another route, this clause is
what gets superseded, and that is the intended mechanism.

### 2. Principal and subject are orthogonal axes

This is the clause the rest of this ADR exists to protect.

- **Principal** — whose hub this is; who may assert; whose delete and export
  rights these are; who the grants belong to. **One**, by §1.
- **Subject** — whom a given belief is *about*. **Many**, and unmodeled as of
  this ADR's date.

> **Normative.** §1's ruling is about the principal axis alone. It may never be
> cited to argue that a belief is necessarily about the owner, to refuse a
> subject axis, or to narrow what a later ADR may model about a third party.

**Ruling the principal single is precisely *why* the subject axis is needed.**
The two readings are opposites and the wrong one is the easier one to reach: "we
ruled single-principal, so beliefs are about the owner, so no subject field is
owed." That inference does not hold. If a household member is a subject in the
owner's model rather than an account on the owner's hub, then "about whom"
becomes the **only** axis left that can carry them. Closing the principal axis
loads the subject axis; it does not relieve it.

The corpus already contains the vocabulary for exactly this move. ADR-0092's
`Attestation` exists because folding `EXTERNAL` into another band "hands an
integration the standing reserved for the user's own word" — a distinction of
*source* that survives only because it has a field. A distinction of *subject*
has no field yet, and has the same shape.

### 3. A second household member is a second hub, and hubs meet as peers

> **Normative.** A second person in the household is served by their own hub. No
> decision may serve them by adding an account, a subject-scoped permission
> system, or a second identity to one hub's store.

**The corpus reserved the word for this and named the case.** ADR-0094's
normative reservation holds "peer" for its transport sense "and for a future
hub-to-hub relationship", and its firing condition enumerates the cases: "If
hubs ever talk to each other — federation, **a household running two**, a hub
that backs another up — *those* are peers in the word's ordinary sense". A
two-hub household is already named there as the peer case. This ADR does not
invent the answer; it makes the enumeration binding for the household question
and takes the consequence.

**What that buys.** Every invariant stays intact: one user model, one
supersession law, one delete right, one grant set, per hub. Sharing between two
people stops being an intra-store permission problem — the hardest kind, because
it touches every read path — and becomes an explicit inter-hub decision, made
once, at a boundary that already exists as a concept.

**What it costs, stated plainly.** Two hubs means two installs, two stores, and
no shared view until federation is designed (§5). A household that wants "what
does my partner's calendar say" gets nothing from this decision today. That cost
is accepted: it is the cost of *not yet having built* federation, whereas the
alternative's cost is a broken invariant, which is the kind that compounds.

### 4. Supersession does not move; rendering acquires a floor

> **Normative.** This ADR changes no supersession rule. ADR-0092 §4's widening —
> a user assertion retires an `EXTERNAL` belief — applies to a belief about a
> third party exactly as it applies to one about the owner, and no ADR may cite
> this one for a subject-conditional supersession rule.

The apparent hole dissolves under §1. Asking "whose word wins about Marta —
hers, or the owner's?" presumes the store is adjudicating facts about Marta. It
is not. It models what the owner believes, and on that question the owner's
assertion beating an external report is correct **by construction**: ADR-0038
§1a's "a user's assertion is its own warrant" is a statement about the owner's
authority over the owner's own model, not a claim of authority over Marta.

What survives is real, and it is a disclosure obligation:

> **Normative.** A surface must not present the owner's belief about another
> person as that person's own word, or as a report from them. Where a surface
> distinguishes the bands at all, a belief about a third party carries the same
> band it would carry about the owner, and the band's meaning is unchanged: an
> `ASSERTED` belief about Marta is the *owner's* assertion, never Marta's.

This is ADR-0073 §4's floor extended along one axis and nothing more. §4 already
forbids presenting an attested belief "as the user's word or as our inference".
The failure this adds is the mirror image: presenting the owner's word about
someone else as though that person had said it. Both are the same defect — a
surface lending a belief a warrant it does not have — and this one becomes
reachable the moment third-party beliefs accumulate, which is now.

Note what this clause is **not**: it is not a rendering *format*, not a required
field, and not an obligation to display a subject the store cannot yet name. It
is a floor on what a surface may imply, discharged today by not implying it.

### 5. What this does not decide, each with the condition that fires it

- **The subject axis itself** — whether a belief names its subject, in what
  type, with what identity, and what an absent subject means. It is the next
  ADR, taken **with the producer in hand** per ADR-0073 §4's discipline. Fires
  with the first producer that writes a belief about someone other than the
  owner deliberately, rather than incidentally as `observe` can today. One
  pointer for that lane, and it is a pointer rather than a ruling: ADR-0092 §1
  put `Attestation` on `Provenance` because who-reported-it is a producer-set
  fact "about *trust and source*", while ADR-0045 §2 put `Validity` on the
  envelope as "a lifecycle property of *the record's life in the store*". A
  subject is neither — it is what the belief is *about* — and that argues the
  envelope. **That lane decides it; this one does not.**
- **Subject-scoped delete and export** — ADR-0007's `delete`/`clear`/`export`
  gaining a dimension, so that "forget everything about Marta" and "show me
  everything you hold about Marta" are expressible. **Both, not just delete**:
  ADR-0004 §6's rights are symmetric and an export that cannot be scoped is the
  same gap facing the other way. Fires with the subject axis, which it strictly
  depends on; it cannot be taken first.
- **Person identity, enrolment, and speaker identification** — what names a
  person, how one is enrolled, and how an utterance is attributed to one. The
  voice-spoke leg owns it (#665). This is **distinct from** ADR-0094 §10's
  deferred spoke identity, which is *device* identity: knowing which microphone
  spoke is not knowing who talked into it, and the two must not be conflated by
  a lane that finds one of them already deferred.
- **Bystander consent** — what is owed to a person captured by a spoke who is
  not the owner. Already owed on #441's amendment and the capture lane, where
  ADR-0094 §10 places the trigger ladder and the grant model. Untouched here:
  ruling that a bystander is a subject rather than a principal says nothing
  about what consent they are owed.
- **What federation actually looks like** — the transport, the trust model, what
  crosses between hubs, and who may ask what of whom. §3 rules that a second
  household member is a peer-hub question; it does not design the peer
  relationship. Fires when a second hub exists, which is ADR-0094's own firing
  condition for its reservation, and nothing here authorises one.

### 6. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**It amends nothing and supersedes nothing.** Every clause above is a **stacked
addition** in ADR-0082 §1's sense: it adds obligations that contradict no
sentence an earlier ADR wrote, so the record belongs in this ADR and nowhere
else. The test is applied to the two places where the opposite reading is
available.

**ADR-0058.** Its Consequences say "This decision is scoped to ADR-0002's
single-user local-first model" and name a multi-principal deployment as the
revisit trigger. §1 ratifies the single-principal premise and §3 removes one
route to multi-principal. Does a reader holding only ADR-0058 now act
differently, or read one of its clauses more widely? No. Its rejection of the
executor-level check stands on the same premise it always stood on, now
ratified rather than assumed; its revisit condition is a conditional whose
antecedent this ADR neither satisfies nor deletes (§1). No sentence of ADR-0058
becomes false or over-wide, so no record is owed against it.

**ADR-0097 §12.** Its **Who granted** deferral reads "No user identity exists
(#113, ADR-0036 §3). Fires with the first multi-user deployment, as an optional
field." Unchanged and untouched: this ADR adds no user identity, and §3 rules
only that a household member is not how a second one arrives. The deferral's
firing condition is as live after this ADR as before.

**A finding recorded rather than fixed: the single-user premise is filed against
the wrong ADR.** ADR-0058 attributes a "single-user local-first"
architecture/model/assumption to ADR-0002 in four places, and ADR-0059 quotes
#308 scoping an issue "single-user local-first (ADR-0002)". ADR-0002 as merged
decides language, architecture, model layer, interface, persistence
("Local-first by default") and workflow, and contains the word "user" zero
times; it rules local-first and never rules single-user. This ADR does not
correct those texts — they are ratified, ADR-0070 §1 protects them, the
correction changes no decision either document made, and it is outside this
lane's fence. It is filed as **#685**. What this ADR does is remove the reason
the misfiling mattered: from ratification the premise has a home, and a later
citation should point here.

**Neither VISION.md nor CLAUDE.md is edited by this lane**, and §7 answers what
VISION owes.

### 7. What `VISION.md` owes, answered rather than performed

`VISION.md` describes "a structured, evolving model of the user's" goals,
preferences, routines, relationships and the rest, speaks of "the user"
throughout, and names as a long-term artifact "a portable personal context graph
that represents the user's goals, preferences, projects, relationships,
routines, and history". It says nothing about households, and nothing about a
second person.

**No amendment is owed for §1 or §2.** VISION is already singular-principal in
every sentence that touches the question, and its "relationships" line already
contemplates other people appearing *inside* one person's model — which is what
§1 ratifies. Adding "and there is only one user" would restate what the document
already says throughout.

**An amendment becomes owed with §3's federation, and this ADR names it as owed
then.** "One hub per person, and hubs meet as peers" is a product-shape promise
of the kind VISION makes, and it is not derivable from anything VISION currently
says; a reader could reasonably read the portable-context-graph line as
promising a shared household graph. Fires with the ADR that designs federation
(§5), not with this one — because until then there is no shape to describe, and
a VISION line describing an undesigned relationship is the drift this ADR exists
to prevent.

## Consequences

- **The framing every decision leaned on is now decided.** "The store is the
  owner's world model" is citable, and a lane that wants a shared or arbitrating
  store argues a supersession rather than filling a silence.
- **The Alexa-household shape is foreclosed cheaply**, before anything is built
  that assumes it. Per-account permissions, per-account profiles and a
  subject-scoped ACL layer over the memory store are all now supersessions of
  §1 or §3.
- **The subject axis is loaded, not lifted.** §2 is the bridge, and it is
  deliberately phrased as a prohibition on citing §1 the wrong way, because that
  citation is the specific failure this ADR would otherwise cause. The next ADR
  is expected, and it is expected to add a field this one refuses to guess at.
- **Two of ADR-0007's obligations are now known to be incomplete**, which is
  progress rather than regression: they were incomplete before, and nothing
  could say so. #685's sibling is not filed here — §5's deferral is the record,
  because a subject-scoped delete cannot be specified before the axis exists.
- **Two hubs is the household answer, and it does not work yet.** A household
  wanting a shared view gets a deferral. Anyone who finds that cost
  unacceptable has a concrete thing to argue against — §3 — instead of a silence
  to fill in either direction.
- **This decision should be revisited** if a deployment shape arrives where the
  hub is not one person's — a hosted or family-plan product, or a device that
  ships with the assistant pre-installed for a household. That is a change to
  §1, taken as a supersession, and ADR-0058's threat model moves with it.

## Alternatives considered

- **Accounts on one hub — the Alexa household shape.** Rejected in §3. It
  requires a subject dimension on every read path, an access-control layer over
  the memory store, per-principal supersession, and per-principal data rights;
  each is a change to a ratified invariant, and together they are a different
  product. It is also the shape reached by drift, which is why it is named and
  refused rather than left unmentioned.
- **Decide nothing; wait for the producer.** This is the corpus's default
  discipline (ADR-0073 §4) and it is right about *fields*, which is why §5
  defers the subject axis. It is wrong about *frames*: a frame left undecided
  does not stay open, it gets fixed by whatever the first implementer assumes,
  and the first implementer here is a shipped `observe` command already
  producing third-party beliefs.
- **Rule the frame and the subject field together, in one ADR.** Rejected for
  the reason ADR-0073 §4 gives — no producer is in hand, so the field would be
  guessed at — and because bundling them puts a contract-surface decision behind
  a scoping one and lets a disagreement about the field block the frame.
- **A subject-conditional supersession rule** — an attested belief from a person
  about themselves outranking the owner's assertion about them. Rejected in §4.
  It presumes the store adjudicates facts about third parties, which §1 rules it
  does not, and it would make the supersession law depend on an axis that does
  not exist yet. What the case actually wants is the disclosure floor §4 rules.
- **Say nothing about rendering and defer that too.** Rejected: the floor costs
  nothing to state, is discharged today by surfaces that simply do not imply the
  false thing, and is the one obligation here that becomes *harder* to add later
  — after a surface has shipped implying it.
