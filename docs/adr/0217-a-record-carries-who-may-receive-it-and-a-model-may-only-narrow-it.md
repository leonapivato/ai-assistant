# 217. A record carries who may receive it, the owner's act is final over a model's, and a model may only narrow

- Status: Proposed
- Date: 2026-08-29
- **Partially supersedes:**
  [ADR-0204](0204-a-record-carries-whether-the-supply-it-was-produced-over-held-withheld-content.md)
  — **the instrument, not the rule.** §1's first, second, third and fourth clauses,
  §3's first and third clauses and §5's first and second clauses are replaced as to
  *which field carries the answer and what values it takes*: `Provenance.supplied_withheld_content`
  becomes `MemoryBase.placement`, a `Placement` whose `OWNER` reach is that field's
  `True` and whose `ANYONE` reach is its `False`. Every record ADR-0204 caused to be
  withheld is withheld after this ADR, on the same evidence, at the same site, by the
  same producer; what changes is that two further setters may write the same slot and
  that the slot is no longer a boolean. §2's evaluation, §3's second and fourth
  clauses, §4's bounded-channel rule, §5's third, fourth and fifth clauses — the
  `SUPERSEDE` differential, the retained target, and the closing prohibition that no
  user act clears in place what the derivation set — §6's residue and §8's tests all
  bind unchanged, over the new field's `OWNER` reach in place of the old field's
  `True`. §7's version footing is replaced: §9 below rules that `PROTOCOL_VERSION`
  **does** move, because this change removes a member from a wire-carried `core` type
  rather than changing a value a hub computes.
- **Partially supersedes:**
  [ADR-0199](0199-the-audience-of-the-output-channel-decides-what-may-be-said-and-a-withheld-class-is-deflected-rather-than-redacted.md)
  — §3's third clause, the placement of speakable classes, **scoped to one further
  case beyond the one ADR-0204 already carved**: a record whose own `placement` does
  not admit the channel's audience is withheld from that channel however §3's third
  clause would place it, whether that placement was set by the owner's act, by a
  model's proposal, or by ADR-0204's derivation. Every other record §3 places is
  placed unchanged, no class is unplaced, no class becomes speakable, and §3's first,
  second and fourth through eighth clauses are untouched — the Tier 0 floor, the
  withheld list, the notification key, the admitting-ADR obligation and the
  audience-alone reading of a placement all bind exactly as they did. §6's owner-side
  class control is **not** superseded: §7 below states the ADR-0082 §1 test that finds
  the per-record act a stacked addition to it rather than an amendment of it.
- **Amends:**
  [ADR-0210](0210-the-withholding-fires-on-what-the-turn-was-retrieved-for-and-the-conversations-own-turns-fire-nothing.md)
  — §1's third clause and §8's third clause, each only as it names
  `Provenance.supplied_withheld_content` by field. ADR-0210's decision is untouched:
  the set the evaluation ranges over on a channel of unbounded audience is exactly the
  set §1 named, and this ADR neither widens nor narrows it. What moves is the name of
  the recorded value the second term of that evaluation reads.
- **This is a contract change, and a Protocol change.** It adds two members to the
  `AssistantEngine` **Protocol** in `core/protocols.py` (§7) — which golden rule 5
  makes a **breaking change**, flagged here in terms — adds one field to `MemoryBase`
  in `core/types.py`, removes one from `Provenance` in the same file, adds three
  `core` types (`Placement`, `PlacementReach`, `PlacementSetter`) and two members to
  `RoutableOperation`, adds one member to `FeedbackEvent`, and **changes the
  behavioural contract of the `FeedbackProcessor` Protocol** without moving its
  signature (§7) — which golden rule 5 reaches, because a Protocol change is a change
  to what an implementation must do and not only to how it is called. So this ADR is
  its own PR, ratified and merged before anything implements against it (golden rule 5,
  ADR-0015 §5), and it owes **both** lenses:
  adversarial and architecture, on ADR-0015 §1 and `CONTRIBUTING.md` → "Stop when the
  required reviews are green". It adds **no new** Protocol and no member to any
  Protocol other than `AssistantEngine`, and no `Settings` field. It adds two wire
  operations and — §9 — it **does** move `PROTOCOL_VERSION`.
- **Durability clause.** Every quotation below — from an ADR, from `core/types.py`,
  from `orchestration/`, or from an issue — is of its text as it stood at this ADR's
  base, `a35ad5e5`, and not of its text on any later day. Where a later ADR changes
  one of the ADRs cited, this ADR is read against the text quoted here and that ADR's
  own record says what moved. This is ADR-0143's clause, taken for its reason.

## Context

### Where this comes from

The owner's design note **#1719**, filed 2026-08-28 out of the guarded-class
discussion in the milestone-20 batch #1709, is the primary source and its six
numbered points are the shape of this decision. Its opening states the gap:

> Disclosure today has one axis — the channel's audience (ADR-0199 §1) — and one
> owner-side control that is ruled but unbuilt (ADR-0199 §6). There is no way for the
> owner to say *this particular fact is sensitive*: `DataTier.SECRET` is credentials
> in the keyring and never a belief; `about_person` is the record's subject, not the
> owner's wish. ADR-0204 has just put the field this needs on `Provenance` for a
> different setter.

That last sentence is the whole of why this is a widening rather than an addition,
and #1719's first point says so in terms: the two shipped values are `{owner}`
("guarded") and `anyone`, **"as a widening of ADR-0204's mark, not a second field"**.

### What the corpus already has, read against the tree

Three things are already built and this ADR moves none of them.

**ADR-0199 §3 decides a *class* from recorded origin.** `orchestration/disclosure.py`
holds the one site, and `_speakable` is three field reads and, since ADR-0204 §3, a
fourth:

```python
    if record.about_person is not None:
        return False
    provenance = record.provenance
    if provenance.supplied_withheld_content:
        return False
    if provenance.source in _PLACED_SOURCES:
        return True
```

**ADR-0204 §3's read is already not a class decision, and the tree says so.**
`_speakable`'s own docstring records the distinction this ADR builds on:

> **And a fourth read, before any placement is reached** (ADR-0204 §3): a record whose
> `supplied_withheld_content` is set is withheld from this channel however §3's third
> clause would place it. It is read first among the provenance fields because it is
> not a placement at all — §3 places the record exactly as it always did, and this is
> a separate reason the record does not reach the channel, over a separate recorded
> field.

**ADR-0210 §1 narrowed which records may set the *boolean*, and nothing else.** Its
fourth clause is explicit that the subtraction did not move with it: "A record
ADR-0199 §3 or ADR-0204 §3 withholds does not reach any stage of the turn wherever it
stood, and this ADR gives no stage a record it did not have before. What a member of
the first group loses is only the power to set a boolean."

So the mechanism this decision needs exists, at one site, reading recorded fields. What
does not exist is a way for the **owner** to write into it about one record.

### The two things "placement" can mean, and why both words stay

ADR-0199 §3 already uses *placement* for a mapping from a **class** to *speakable on a
channel of this audience* — "These classes are placed as **speakable**", "A candidate
matching a placement in `producer` and `notification_class`". #1719 and #1718 use
*placement* for the set of **people** who may receive a record. The two are different
relations and the collision is real.

Renaming either was considered and rejected. ADR-0199's word is ratified in eight
clauses and in the tree's own prose; #1719's and #1718's word is the owner's, is the
one track:identity is being planned in, and is the word the read rule is naturally
stated in. So both stay and the ADR disambiguates in terms rather than by fiat: §2
states the rule with each occurrence qualified, and §1's last clause fixes the
vocabulary for every later reader.

### What is not in dispute, and is used as given

- ADR-0199 §1's audience test, §2's recorded-origin discipline, §3's Tier 0 floor and
  its `about_person` limb, §4's tighten-never-widen rule, and §5's deflection.
- ADR-0203 §1's subtraction before the turn plans, and §2's "one assembly, one
  retrieval, one filter".
- ADR-0204 §2's evaluation and §5's ratchet, as generalised by §3 below.
- ADR-0210 §1's narrowed evaluation set.
- ADR-0100 §2's placement rule for a field on a memory record, quoted in the tree as
  "a field is placed by which question it answers, not by who sets it".
- ADR-0045 §2's argument about two authorships, quoted in `Provenance`'s own docstring.

### An honest statement of what this ADR is not allowed to settle

It cannot name a person, because there is no person identity in this system (#691,
ADR-0199 §7). It therefore cannot express a placement of *some* people, only the two
sets #1719 ships. It cannot decide the household question ADR-0199 §7 deferred and
#1718 holds. It cannot decide a **class-level** act — "guard everything about my
health" — because no record carries a topic; that axis is ADR-0213's (#1791, ratified
on its branch and not merged at this ADR's base), and this ADR cites it by number and
subject and depends on no sentence of its text. And it cannot decide the surface
ADR-0199 §6 deferred for the owner's **class** postures; §7 below builds a per-record
act and states the test that keeps them apart.

## Decision

We will put **who may receive it** on every record in the store, as ADR-0204's mark
widened rather than as a second field; state the read rule in the general form and show
it reduces today to exactly ADR-0199 §3 and §5; admit three setters with a stated
precedence, of which a model's is the weakest and may only narrow; leave the default
where ADR-0199 §3 put it; and change nothing about Tier 0, `about_person`, or the
mechanics of withholding at supply.

### 1. One placement on every record in the store, on `MemoryBase`, widening ADR-0204's mark

> **Normative.** `MemoryBase` (`core/types.py`) gains exactly one field, `placement`,
> of a new frozen `core` type `Placement`, defaulting to `Placement()`. It records
> **who may receive this record**. It is on `MemoryBase`, so every record kind carries
> it — `EpisodicMemory`, `SemanticMemory`, `PreferenceMemory` and `ProceduralMemory`.

> **Normative.** `Placement` carries a **reach**, a `PlacementReach` defaulting to
> `ANYONE`, and the stamp of who set it: a `PlacementSetter | None` defaulting to
> `None`, and a `UtcInstant | None` defaulting to `None`. `PlacementReach`'s members as
> this ADR ships it are two — `ANYONE`, denoting every person, and `OWNER`, denoting the
> set whose one member is the owner — and this enumeration is **the vocabulary as it
> stands, not a cardinality this ADR fixes**. `PlacementSetter` has exactly three
> members, `OWNER_ACT`, `DERIVED` and `PROPOSED`, and *that* enumeration **is**
> exhaustive: they are §3's three setters and no implementation or later ADR adds a
> fourth without superseding §3's first clause.

> **Normative.** `Provenance.supplied_withheld_content` is **removed**, and the
> question it answered is answered by this field: a record ADR-0204 §2 or §5 would have
> stamped `True` is written with reach `OWNER` and setter `DERIVED`, and a record it
> would have stamped `False` is written with the default. No other member of any `core`
> type changes its type, its default or its meaning.

> **Normative.** A `Placement` whose setter is `None` states that **nothing has
> narrowed this record**, and on a record written after this field lands that is a
> measurement and not merely a default, exactly as ADR-0204 §1's third clause says of
> its `False`. On a record written **before** this field lands it is a decode default
> and not a measurement; §9's decode rule is what keeps that case from silently
> widening a record ADR-0204 had already narrowed.

> **Normative.** The reach is a **denotation of a set of people**, and the two members
> above are the two sets this system can denote today. A later ADR that gives it
> further denotations — named people, circles (#1718) — **adds** them, and does so as a
> stacked addition under ADR-0082 §1: it changes no sentence of this ADR, because every
> clause here is written over *a* reach rather than over the pair, `ANYONE` and `OWNER`
> keep the denotations §1 gives them, and §2's rule is stated over sets so that it does
> not move when a third arrives. What such an ADR may **not** do is redefine either
> shipped denotation or restate §2's rule; either of those is a supersession and is
> recorded as one.

> **Normative.** **Vocabulary.** ADR-0199 §3 *places a class* as speakable **on a
> channel**; this ADR *places a record* **for a set of people**. Neither renames the
> other, neither is read as the other, and §2's read rule is a conjunction of the two.
> No implementation, lane or later ADR collapses them.

**On `MemoryBase` rather than on `Provenance`, by `MemoryBase`'s own placement rule.**
ADR-0100 §2 fixes the test and the tree states it: `Provenance` answers *why this
should be believed* and the envelope answers *what is held, about what, and for how
long* — "a field is placed by which question it answers, not by who sets it". ADR-0204
§1 applied that test to its own field and got `Provenance`, correctly: "What material
stood in front of the producer is the first question, not the second." This field asks
a different question. *Who may receive this record* is not a fact about the material
the producer saw; it is a fact about the record's disposition, and it belongs to the
family the envelope already holds — **about whom** (`about_person`), **for how long**
(`expires_at`, `validity`), and now **to whom**. It also lands beside the axis
`_speakable` already reads from the envelope first.

**And ADR-0045 §2's argument, which `Provenance`'s docstring quotes against itself,
comes out the same way.** That section put `validity` on the envelope because the
window is "a lifecycle property of the record's life *in the store*, set operationally
by the applier", and putting it on `Provenance` — "whose every other field is set by
the *producer* of the belief" — "would mix two authorships". A placement the owner
revises after the fact, on a record already in the store, is that shape exactly. It is
the second, corroborating argument and not the first, because ADR-0100 §2 says
authorship is not the test; but where the question test and the authorship test agree,
the placement is not close.

**ADR-0204's field was right where it was, and moving it is not a correction of it.**
The two questions are genuinely different, and ADR-0204's answer to its own one was
sound. What changed is that a *second* and *third* setter now write the same slot, and
the slot's question is then no longer "what stood in front of the producer" but "who
may receive this" — of which the derivation's answer is one input. Recording that the
question moved, and moving the field with it, is better than leaving a field in a class
whose docstring stops describing it. §9 states the prose edit that owes.

**One field rather than two, which is #1719's first point and is also the safer
shape.** Two fields — a boolean warrant fact and a placement beside it — would put two
recorded values in front of one read, and the read would have to combine them. Every
such pair invites the failure where one is written and the other is not: a supply site
that consults the placement and not the mark would speak a record ADR-0204 withholds,
and the mistake is silent. One slot, three setters, one read.

### 2. The read rule, in its general form, and what it reduces to today

> **Normative.** A record is emitted on an output channel only if **every person who
> can perceive that channel's emission is a member of the record's placement**. This is
> stated over sets and is the whole of what this ADR adds to the read.

> **Normative.** It is a **conjunct beside ADR-0199 §3, never a replacement for it**. A
> record reaches a channel only where §3 places its class as speakable on that channel
> **and** this rule admits it. Nothing here places a class, unplaces one, or makes
> speakable anything §3 withholds.

> **Normative.** Today it reduces exactly to ADR-0199 §1's two audiences and nothing
> else. On a channel whose audience is **unbounded**, what it emits "reaches whoever is
> within range of the device with no act of theirs" (ADR-0199 §1), so the people who
> can perceive it are not bounded by any set this system holds: only reach `ANYONE`
> admits them, and a record whose reach is `OWNER` is withheld. On a channel whose
> audience is **bounded**, ADR-0199 §1 makes the perceiver the owner alone, so both
> reaches admit and **nothing is withheld on this ADR's account** — no park, no tap, no
> marker on a screen only the owner sees.

> **Normative.** The withholding is at supply in ADR-0199 §5's first clause's sense,
> and everything that clause and ADR-0203 §2 say of a withheld record is true of one
> withheld here: it reaches no stage of the consuming turn, nothing is refetched,
> widened, re-run or backfilled to replace it, the order of what survives is the order
> it had, and no implementation composes a value and then removes, masks, blanks or
> rewrites part of it to satisfy this ADR.

> **Normative.** The rule is applied **at the sites the channel's audience is read
> today, and at no new site**. It is one further field read in the predicate ADR-0199
> §3 and ADR-0204 §3 are already applied by, and it creates no stage, no seam, no store
> call and no second pass.

> **Normative.** **Composition with ADR-0210 §1 is by that ADR's own words and adds no
> rule.** On a channel of unbounded audience the **subtraction** removes an
> `OWNER`-placed record wherever in the turn's supply it stood, the first group
> included; the **evaluation** whose result stamps the captured episode and tells the
> composing stage that a withholding occurred ranges over exactly the set ADR-0210 §1
> named. So an `OWNER`-placed record a relevance read returned for this turn is
> withheld **and** fires the deflection; one the supply holds only because it stands in
> the conversation's own recent turns is withheld and fires nothing. This is ADR-0210
> §1's fourth clause applied unchanged, and no clause of this ADR narrows or widens the
> set it named.

**Stating the general form now, when only two sets are denotable, is the point of
stating it at all.** #1719's second point asks for it and gives the reason: the rule
that survives track:identity is the one written over sets, and the reduction above is a
*consequence* of today's two audiences rather than a special case bolted on. #1718 says
the same from the other side — the rule "subsumes ADR-0199's rule exactly (unbounded =
anyone can perceive → only anyone-placed records; bounded-to-owner → everything)". When
a named person becomes denotable, this sentence does not move; what moves is how many
sets there are to be a member of.

**"Bounded flows freely" is a decision and not an omission.** The tempting alternative
is to render a guarded record differently on the owner's own screen — a marker, a
collapsed row, a second confirmation. #1719 refuses it in terms, and ADR-0199 §1 is why:
the posture "is a function of the audience of the channel it is bound for, and of
nothing else". A screen only the owner can see has one perceiver, that perceiver is the
owner, and the owner is in every placement this ADR can express. A marker there would be
a posture keyed on something other than the audience.

**The conjunction is what makes §6's default true.** If this rule *replaced* ADR-0199
§3's placements, then a record whose placement is `ANYONE` would be speakable on an
unbounded channel whatever its class — a message reader's proposal, an unplaced facet,
an attested record from a source no ADR named — and the fail-closed property §3's
fourth clause exists for would be gone on the day this landed. As a conjunct it can
only subtract.

### 3. Three setters, and the precedence between them

> **Normative.** Exactly three setters write `placement`, and they are exhaustive. No
> implementation invents a fourth.
>
> - **The owner's explicit act** (`OWNER_ACT`) — at write, or after the fact on a
>   record already in the store. §7 states the acts.
> - **The derivation** (`DERIVED`) — ADR-0204 §2's evaluation and §5's inheritance,
>   unchanged in every respect except what they write into.
> - **A model's proposal** (`PROPOSED`) — §4.

> **Normative.** **The derivation.** A record whose production ADR-0204 §2's
> disjunction is `True` of, and a record ADR-0204 §5's inheritance reaches, is written
> with reach `OWNER` and setter `DERIVED`. ADR-0204 §2's evaluation is unchanged: the
> same one supply, the same two terms, the same site between retrieval and planning,
> the same narrowing on one channel under ADR-0210 §1. Its second term reads this
> field's reach in place of the removed boolean and is otherwise the same term.

> **Normative.** **ADR-0204 §5's ratchet binds over this field, generalised from a
> disjunction to a meet.** Where two records are folded the survivor's reach is the
> **narrower** of the two sides'; a producer deriving a record from records of this
> store writes the **narrowest** reach over every record it was supplied, never over
> the subset it cited, selected, ranked or judged relevant; and no implementation
> writes a wider reach over a narrower one on any of those paths. On the two-member
> reach of §1 the meet **is** ADR-0204 §5's disjunction, member for member, so no
> producer's arithmetic changes.

> **Normative.** **ADR-0204 §5's closing prohibition binds unchanged, and it is the
> limit of the owner's act.** No user act, configuration, setting or later lane widens
> in place a placement whose setter is `DERIVED`. A supersession is the only route by
> which a live record stops carrying one, on ADR-0204 §5's third, fourth and fifth
> clauses, which are untouched.

> **Normative.** **The owner's explicit act is final over a model's proposal, in both
> directions.** An act may narrow a placement whose setter is `None` or `PROPOSED` to
> reach `OWNER`, and may widen one whose setter is `PROPOSED` or `OWNER_ACT` to reach
> `ANYONE`. Either writes setter `OWNER_ACT` and the instant of the act. An act on a
> placement whose setter is `DERIVED` **narrows only**: a widening act on such a record
> is refused, and the refusal names the two routes that remain — a supersession, or a
> class ruling under ADR-0199 §6.

> **Normative.** **A model's proposal is the weakest and may only narrow.** It writes
> reach `OWNER` and setter `PROPOSED`, and **only** where the record's placement is
> reach `ANYONE` with setter `None`. It never widens a reach, never overwrites a
> setter of `OWNER_ACT` or `DERIVED`, and never runs on a record already in the store.

> **Normative.** Where more than one setter would write in one act, the **narrower
> reach stands**. Where two would write the same reach, the recorded setter is decided
> by one total order, strongest first: **`DERIVED`, then `OWNER_ACT`, then
> `PROPOSED`**. So a record a guarded write and a proposal both place `OWNER` records
> `OWNER_ACT`, which is what makes the owner's act final over a model's in the
> same-reach case as well as the differing-reach one; and a record the derivation and
> an owner's act both place `OWNER` records `DERIVED`, because that narrowing is the one
> §3's closing clause forbids lifting. No implementation records a setter weaker in this
> order than the strongest that in fact wrote the reach the record carries.

> **Normative.** **Neither an act nor a proposal reaches a floor.** No placement, by
> any setter, admits a Tier 0 value to any output channel (ADR-0199 §3's first clause),
> and no placement makes speakable on a channel of unbounded audience a record whose
> `about_person` is stated (ADR-0199 §3's second clause and §6's fourth clause). Both
> stay withheld under every act the owner makes and no surface offers either as
> something the owner may admit. A widening act on such a record is accepted and
> changes nothing about what that channel carries.

**The precedence is a lattice and a ratchet, which is why it can be stated without
arithmetic.** ADR-0021 §5 fixed the shape of a function it could not fix the threshold
of — "Raising `risk_level`, raising `reversibility`, or widening `discloses` — with
everything else held equal — must never produce a *less* restrictive outcome" — and
called that "checkable on any implementation without knowing its rules". The same move
is available here: the reaches are ordered by narrowness, every automatic setter moves
down the order and never up, and the only setter that may move up is a recorded human
act on one record. A reviewer can check that property without knowing what any model
proposed.

**The owner's act is final over a model, and not over the derivation, and the asymmetry
is ADR-0204's rather than this ADR's.** ADR-0204 §5's last clause is unambiguous: "no
user act, configuration, setting or later lane clears the field in place on a record
that carries it. A supersession is the only route by which a live belief stops carrying
a `True`". That clause exists because the derivation's narrowing is not a judgement
about *this* record's sensitivity — it is a fact that content the owner may not admit
stood in this record's warrant, and #1708's laundering is what happens when it clears.
The owner overriding it per record would be the owner admitting, one derivative at a
time, exactly what ADR-0199 §6's fourth clause says no owner act may admit. So the
clause is kept whole.

**What that costs is real and is named rather than papered over.** A store accumulates
`DERIVED` narrowings the owner cannot lift, and #1775 measured how fast that can happen
before ADR-0210 bounded it. Two routes remain open and both are ratified: a supersession
retires the record (ADR-0045 §4, ADR-0040 §5a), and a class ruling under ADR-0199 §6
changes the posture of the class rather than the record. #1719 names the second as the
intended escape — "A class that never converges is the signal for a deterministic class
ruling under ADR-0199 §6 — the escape hatch, not the default" — and §12 records the
residue with the condition that fires it.

### 4. The model's proposal rides a pass a producer already makes, and never runs at read

> **Normative.** A model's proposal is made **at write, by a producer that is already
> consulting a `ModelProvider` on that pass**, over the record it is about to write. No
> writer gains a provider call it did not have, no new model seam is created, and no
> producer that makes no model pass makes a proposal.

> **Normative.** **The producer that makes one today is `Observer`, and it is named
> rather than left to the eligibility test.** An observer proposes a record from
> material it was handed and its proposal is the first placement that record could
> carry. `orchestration/consolidation.py` is also model-backed — it is constructed with
> a `ModelProvider` — and it does **not** propose: what it produces is *derived from
> records of this store*, so ADR-0204 §5's inheritance, generalised by §3, already
> gives it the narrowest reach over everything it consolidated, and a second narrowing
> keyed on the consolidated text would be a model re-judging material another model has
> already judged. Widening the set of producers that propose is a later decision and
> §12 records it.

> **Normative.** It **never runs at read**. No supply site, no composing stage, no
> delivery path and no rendering consults a model, or any classifier, to decide a
> placement. The read is a field read, and ADR-0199 §2's decision procedure is
> untouched.

> **Normative.** A record written by a producer that makes no proposal carries the
> default, and that is not a degraded state: it is §6's default, which is ADR-0199 §3's
> placement. Where the provider is unreachable, the pass that would have carried the
> proposal has already failed or degraded on its own terms, and no separate failure
> mode is created here.

> **Normative.** The proposal is bounded by the pass it rides. No implementation adds a
> retry, a second pass, a batch job or a scheduled sweep whose purpose is to propose
> placements, and no proposal is made over records already in the store.

**#1719's lean was "every belief write, budgeted; episodes inherit", and this is that
lean given a mechanism.** "Every belief write" is unreachable as stated: a calendar
import, a `MemoryStore.add` from a reader and a fold in `memory/ingest.py` are all
belief writes with no model in front of them. Riding the pass a producer already makes
lands on the writes that actually matter — `learning/observer.py` proposes
beliefs from episodes with a provider in hand, and that is where a belief the owner
never explicitly typed comes from — and it makes "budgeted" exact rather than
aspirational: the budget is the pass's, and the count of provider calls is unchanged.
"Episodes inherit" is then true by §3's derivation and needs no separate rule: an
episode is captured from a turn and takes the narrowest reach over that turn's supply.

**ADR-0130 §11's three grounds are answered, and they are answered because the model is
at the write and not at the read.** That section forbids a model ruling on a
notification because "An interruption a model chose cannot be explained to the user who
received it, cannot be tested deterministically, and cannot run when no provider is
reachable — which is exactly when a resident process is still noticing."

- **Explainable.** The stamp records that this record's narrowing is `PROPOSED` and
  when, so the surface can say *the model kept this to you* and the owner can lift it
  in one act (§7). ADR-0130's case has nothing to point at; this one has a field.
- **Deterministic.** Every read of a placement is a read of a recorded value. Two reads
  of the same record give the same answer forever, and a test pins a placement by
  constructing it.
- **Provider-down.** The proposal is not made, the record keeps §6's default, and the
  system behaves exactly as it does today. ADR-0130's failure mode is a policy that
  cannot rule; this one has a ruling for every record without asking anybody.

**And it is the shape ADR-0213 takes for topics, deliberately.** #1719 states the
parallel: "topics are proposed by a model when a record is written and recorded on it,
deterministic thereafter, so ADR-0199 §2 holds (a read keys on a recorded stamp, never
on the words)". ADR-0213 (#1791) is ratified on its branch and not merged at this ADR's
base, so it is cited here **by number and subject only**; no clause below depends on a
sentence of its text.

**The objection worth stating is that a model now reads content to decide something
about disclosure, and ADR-0199 §2's answer is narrower than it first looks.** §2's
second clause reads: "No implementation, lane or later ADR may decide **a class** by
reading `MemoryBase.content`, a facet's rendered text, a composed reply, or any other
span of the content itself — not by keyword, not by pattern, not by a classifier, and
not by asking a model what a passage is about." Two things keep this proposal outside
it. It decides no class: §2's classes are unmoved and §3's placements of them are
computed exactly as they were. And it is not a *decision procedure at the supply site*
— it is a producer recording a value, once, which every later read consults as a field.
§2's own reasoning is about the failure of a filter that runs on every read and "fails
on the first sentence that phrases a diagnosis in ordinary language, and its failure is
silent"; a proposal that can only narrow fails, when it fails, by guarding something
that did not need guarding, which the owner can see and lift.

### 5. Where a proposal narrows what the owner's own act produced, the turn says so

> **Normative.** Where a model's proposal narrows a record produced by an act the owner
> took in that turn, the reply for that turn **states that it did** and names the act
> that lifts it. The statement carries no span of any withheld content and no value
> derived from one; the content it is about is the owner's own utterance.

> **Normative.** This is a statement about the write and is not a deflection. ADR-0199
> §5's clauses govern a withholding at supply and are neither invoked nor changed by
> it, and no turn is parked, no confirmation is owed, and nothing is refused.

> **Normative.** The owner's correction is the explicit widening act of §7 on that
> record — deterministic, and final over the proposal by §3. It is not a re-run of the
> proposal, a re-prompt, or a model re-judging its own stamp.

> **Normative.** The correction is **also** learned. The turn performing a widening act
> is captured as an episode by ADR-0074 §3 like any other, and `learning/`'s observer
> distils a `PreferenceMemory` from it on its ordinary pass, by exactly the machinery
> that distils every other preference — no new event kind, no new recogniser, no
> utterance pattern, and no second store.

> **Normative.** A proposal under §4 is supplied the live `PreferenceMemory` records
> **only where the producer's own ratified seam already admits such an input**, and
> today none does. `Observer.observe` takes a `Sequence[EpisodicMemory]` and its
> Protocol makes the absence a scope limit rather than an omission — "It holds no store
> handle … an implementation cannot fetch more, cannot widen its own batch, cannot read
> a belief" — so an observer's proposal is made over the episodes it was handed and
> nothing else. Giving that producer a second input is a change to a Protocol other
> than `AssistantEngine`, which §9 forbids this ADR and its implementation, and which
> golden rule 5 puts behind an ADR of its own. §12 records the deferral with the
> condition that fires it.

> **Normative.** Until that ADR exists, a proposal is made without a preference in
> front of it and the preference reaches the owner rather than the model: the record it
> is distilled from is a belief the owner can read, and the per-record act of §7 is
> what actually changes an outcome. No lane cites this ADR as authority for a producer
> reading preferences it was not handed, and no implementation gives one a store handle
> to get them.

> **Normative.** No preference so learned is itself a setter. It is evidence a proposal
> may weigh where a ratified seam supplies it, and never a rule any read applies; it
> narrows and widens nothing on its own; and no implementation reads one at a supply
> site.

**#1719's fourth point is honoured on the reading the vocabulary actually supports.**
That point asks what happens when "Owner's placement vs the model's narrowing at the
moment of write" disagree, and rules that "the narrower stands (fail-closed) and the
reply says so". In the shipped vocabulary an explicit act at write is a *narrowing*
(`--guarded`, "keep it to me"), which the proposal can never contradict because it is
already the narrowest; there is no explicit widening act at write, because on a record
no proposal has yet narrowed it would be a no-op. So the reachable disagreement is
exactly the one above: the owner said "remember this", meant nothing about disclosure,
and the model guarded it. The narrower stands, the reply says so, and the correction is
one act. Recording that the disagreement moved is better than legislating a case the
acts cannot produce.

**Learning it through the ordinary observer, rather than through a recogniser for
"correction" utterances, is the choice #1719 left open and it is the cheaper of the
two.** The alternative — an ADR-0176-style feedback event, or a `learn` shape the CLI
recognises as a disclosure preference — needs a new event kind, a new capture path, and
a rule for what a client must say to trigger it, and it puts a second producer of
disclosure-bearing records in the system. The act is already deterministic and already
captured; the generalisation from *this record* to *this kind of thing* is precisely
what an observer does, and it arrives with the same confirmation machinery, the same
provenance and the same supersession behaviour as every other belief it proposes.

**And the preference is deliberately not a setter.** A learned sentence like *"my coffee
habits may be said aloud"* has no decidable extension over records — matching it to a
record would be content inspection at the read, which ADR-0199 §2 forbids in terms. The
only place it could ever act is in front of the *proposer*, which is a model at write,
where its whole effect would be that the model stops proposing a narrowing the owner
keeps lifting.

**#1719's "The model is trained by the owner, not switched off" is therefore delivered
in part, and the missing part is named rather than implied.** The correction is
deterministic and final (§3), and it is captured and distilled like any other belief, so
the owner's ruling is durable and legible. What this ADR cannot deliver is the last hop
— that ruling reaching the model on the *next* record — because the only producer with a
model in front of it is `Observer`, whose Protocol makes "episodes in, proposals out" a
scope limit rather than a signature detail, and widening it is a Protocol change §9
forbids this ADR. Reporting the gap is better than writing a clause no implementation
could satisfy without breaking a seam this ADR says it does not touch: the deferral is
§12's, with the condition that fires it. Until then the corrective loop closes through
the owner and the per-record act, and the read is exactly as deterministic as it was.

### 6. The default is ADR-0199 §3's placement, and this ADR adds narrowing only

> **Normative.** A record carrying the default placement is placed exactly as ADR-0199
> §3 places its class, on every channel, and this ADR subtracts nothing from it. No
> record becomes less speakable on the day this field lands than it was the day before,
> except a record ADR-0204 had already narrowed, which is narrowed by the same rule
> under a new name.

> **Normative.** This ADR flips no floor, raises no default and admits nothing. Every
> clause above can only remove a record from a channel; none adds one.

**#1719's sixth point rules this and gives the ground, and it is the owner's own
judgement rather than a derivation from the corpus.** "An ADR that read 'placement on
every record' as owner-only by default would silence the assistant on day one (owner,
2026-08-28: the initial state is a solid balance, not a conservative one)." ADR-0199 §3
already chose a named speakable set precisely so that milestone 19's exit test — the
owner asking aloud about their own life and hearing an answer drawn from accumulated
memory — is answerable, and its own text says "A rule that passed the safety test and
failed the exit test would be a rule nobody could ship." A guarded-by-default placement
would fail that test on the first turn.

### 7. The acts: one flag at write, two operations after the fact

> **Normative.** The owner's explicit act at **write** is one additive member on
> `FeedbackEvent` (`core/types.py`), `guarded: bool` defaulting to `False`, carried
> unchanged through `AssistantEngine.learn` — whose signature does not move — and
> honoured by the `FeedbackProcessor` that builds the record: where it is `True` every
> record that event produces is written with reach `OWNER` and setter `OWNER_ACT`.
> It is a narrowing only, and `False` is not an act of any kind.

> **Normative.** It **ships with its route**, `assistant learn --guarded`, on
> `about_person`'s own precedent in the same class: ADR-0100 §4's member ships with
> `assistant learn --about-person` because "a field with no route would leave every
> third-party belief constructing `about_person=None`". A `guarded` nobody can set is
> the same defect.

> **Normative.** The member is on `FeedbackEvent` and **not** encoded by an adapter,
> because deciding a record's placement is not adapter work: golden rule 3 keeps
> business logic out of `interfaces/`, and an adapter that translated a flag into a
> placement would be deciding disclosure in the thinnest layer in the system. The
> adapter sets a field; `learning/` reads it.

> **Normative.** Honouring `guarded` is a change to the **`FeedbackProcessor`
> Protocol's behavioural contract**, and it is stated as one rather than left to read
> as a change in one implementation. Implementations of that Protocol are
> interchangeable behind `core/protocols.py`, so one that built its normal proposal and
> ignored the member would be structurally conformant and would silently discard an
> explicit owner act. Golden rule 5 reaches a change to what an implementation must do
> and not only to how it is called, which is why this ADR decides it.

> **Normative.** It therefore carries that Protocol's own obligations, in the **same
> change** as the member: `FeedbackProcessorContract` gains a guarded-event arm,
> every implementation bound to that suite is made to pass it, and the canonical fake
> in `ai_assistant.testing` honours the member. A fake that ignores it would put a
> default placement on records in every orchestration and world test that uses one,
> which is the silent loss this clause exists to prevent.

> **Normative.** The member and its honouring land **atomically**, and no tree ever
> accepts `guarded=True` without acting on it. A `core` member a client may set and a
> hub may ignore is a fail-open window on the promoted surface — a caller's explicit
> guard accepted, recorded nowhere, and the record speakable — and the version bump
> that admits such a caller is what makes it reachable rather than theoretical. §11
> puts the member, the processor, the suite arm and the fake in one change for this
> reason and no other.

> **Normative.** The owner's explicit act **after the fact** is two members added to
> the `AssistantEngine` Protocol (`core/protocols.py`), whose signatures are exactly:
>
> ```python
> async def guard(self, record_id: Identifier) -> Placement | None: ...
> async def unguard(self, record_id: Identifier) -> Placement | None: ...
> ```
>
> **Normative.** An act writes **only where §3's precedence lets it win, and only
> where what it would write differs from what the record carries**. `guard` writes
> reach `OWNER` with setter `OWNER_ACT` and the instant of the act; `unguard` writes
> reach `ANYONE` with setter `OWNER_ACT` and the instant of the act. Where the
> placement's setter is `DERIVED`, `unguard` writes **nothing** — §3's closing clause
> is not lifted by an act — and neither does an act whose whole effect would be to
> rewrite a placement it does not change in reach or in setter. Nothing else writes an
> `OWNER_ACT` stamp.

> **Normative.** The two consequences of that clause are stated so no implementation
> has to derive them. A `guard` on a record whose placement is reach `OWNER` with
> setter `PROPOSED` or `None` **does** write, because it changes the setter from one
> the owner may lift to one this ADR calls final, which is a difference §3 acts on.
> A second `guard` on the result writes nothing, so the instant does not move and the
> returned value is identical — which is what makes both operations idempotent, and it
> is idempotent in the strict sense that the second call returns exactly what the first
> returned.

> **Normative.** Each **returns the record's placement as it stands after the act**,
> and `None` where `record_id` named nothing live — which is not an error, on
> `AssistantEngine.forget`'s own reading of the same case ("the user's intent … is
> already satisfied"). Each raises `ValueError` where `record_id` is blank and
> `MemoryStoreError` where reading or writing memory failed, and declares no other
> error in its own `Raises` block. `OversizedValueError` is **inherited, not
> exempted**: `AssistantEngine`'s own clause declares it of "**every** method below …
> and is not repeated in each one's `Raises` block", on the ground that
> ":data:`Identifier` carries no maximum length, so even ``forget`` can be handed an
> oversized argument", and these two are no different. Nothing here reads the
> exhaustive list above as an exemption from ADR-0085 §8's bound. In particular a **refusal raises nothing**: `unguard` on a placement whose
> setter is `DERIVED` returns that placement unchanged — reach `OWNER`, setter
> `DERIVED` — and a surface reads the returned reach and setter to say why nothing
> moved. A raise was rejected because it
> would make an act the system declines on ratified grounds indistinguishable, on
> ADR-0197's routed path, from an operation that failed (`RouteOutcome.FAILED`), and
> because it would make an idempotent act — `guard` on an already-guarded record — a
> failure too. Both operations are idempotent, and calling either twice returns the
> same value.

> **Normative.** The two members are **`AssistantEngine`'s and no other Protocol's**.
> No `MemoryStore`, `MemoryWriter`, `ContextProvider`, `Planner`, `NotificationPolicy`
> or any other Protocol in `core/protocols.py` gains a member, changes a signature or
> changes a return type. Whether `MemoryStore` needs an operation to perform the write
> is an implementation question inside `memory/` that this ADR does not settle and that
> no lane settles by adding a Protocol member without its own ADR (golden rule 5).

> **Normative.** The added members carry the obligations any member of a Protocol
> carries: the shared `AssistantEngine` conformance suite gains an arm for each clause
> of §3 and §10 that binds an implementation, and the canonical fake in
> `ai_assistant.testing` implements both. §11 states which change carries them.

> **Normative.** `RoutableOperation` gains exactly two members, `GUARD` and `UNGUARD`,
> named for the operation each routes to, in ADR-0197 §3's own naming rule.

> **Normative.** Both are **confirm-owed**, so a routed one is rendered and confirmed
> before it is performed (ADR-0197 §7). ADR-0197 §3's widening rule is satisfied and each condition is stated
> here rather than cited: (i) both are members of the promoted surface; (ii) neither
> reaches any egress boundary — no `ToolRegistry`, no `ToolInvoker`, no
> `EgressDestination`, no credential; (iii) each takes exactly one argument, resolved
> by ADR-0197 §5's deterministic lookup from a router-named query, over the same
> candidate set a routed `forget` enumerates — live beliefs of every `MemoryKind`
> except `EPISODIC` (ADR-0201 §1) — with the per-operation mapping being
> `MemoryBase.id`; (iv) each writes durably and is therefore confirm-owed by ADR-0197
> §3's own test; (v) condition (v) does not apply, both being confirm-owed rather than
> read-only.

> **Normative.** They are **two operations and not one with a mode**, because ADR-0197
> §3's second clause puts an operation taking "a second varying argument — a scope, a
> mode, an accept/reject decision, a preferences object" outside the vocabulary. Two
> single-argument members satisfy the clause as written; no lane collapses them into
> one taking a placement.

> **Normative.** This ADR decides these two members and the flag, and **no client
> rendering**. Where a surface lists beliefs it may offer the act, and how it renders a
> record's placement is the implementing lane's within ADR-0199 §5's bounds; nothing
> here obliges a surface to render one.

**This is a per-record act and it is a stacked addition to ADR-0199 §6, not an amendment
of it — the ADR-0082 §1 test, applied.** §6's third clause is "The owner may record that
**a class** §3 placed as speakable is withheld, and that **a class** §3 withheld under
its second or third limb is speakable"; its last clause defers "The surface carrying
these records — its Protocol, its types, its operations and its client rendering". Both
are about a class posture held in a store of its own. Would a reader holding only
ADR-0199 now act differently, or read one of its clauses more widely than it now holds?
No: every sentence of §6 stays true of the class control it is about, none of them
becomes over-wide, and this ADR builds no class control and no store for one. So the
obligation is recorded here and nowhere else, which is ADR-0082 §1's own disposition for
a stacked addition. §6's *fourth* clause — the Tier 0 and `about_person` floors — is
adopted verbatim for the per-record act by §3's last clause, which is an obligation this
ADR takes on rather than a change to §6.

**The append-only record of an act is the audit trail, and no new store is minted.**
#1719 asks for "append-only record, ADR-0199 §6's form". A confirm-owed routed operation
already records a decision row (ADR-0197 §9), and the promoted operations are performed
under the same trail every other write is. The record's field carries the *effective*
placement and its stamp; the trail carries the history. Building a second append-only
store for two operations would be the surface ADR-0199 §6's last clause deferred, built
for a purpose that clause is not about.

**`EPISODIC` is outside the routed lookup for ADR-0201 §1's reason, unchanged.** An
episode is never a candidate of a routed lookup, never its display subject and never the
identity a façade call is made with. Episodes still carry placements — they are where the
derivation writes most often — and the typed door still names any record by id. What is
outside the vocabulary is *resolving an episode from a sentence*, which is the loop
ADR-0201 closed.

### 8. What is untouched

> **Normative.** **Tier 0.** ADR-0199 §3's first clause is a floor and stays one. No
> reply and no delivery on a channel of any audience carries a Tier 0 value or any span
> of one, and no placement, act, proposal or derivation reaches it.

> **Normative.** **`about_person`.** ADR-0100's subject axis is a second axis and both
> stay. A record whose `about_person` is stated is withheld from a channel of unbounded
> audience under ADR-0199 §3's second clause whatever its placement, and this ADR
> neither narrows nor widens that clause. The subject of a record is a natural member
> of its placement when identity exists, and that is #1718's to decide, not this ADR's.

> **Normative.** **The mechanics of withholding at supply.** ADR-0199 §5 and ADR-0203
> §1 and §2 are untouched: the subtraction is a filter over what the turn already
> assembled and retrieved, applied between retrieval and planning, adding nothing and
> refetching nothing, and the deflection keeps its shape and its prohibitions whole.

> **Normative.** **Retrieval.** ADR-0203 §2's third clause binds unchanged: retrieval
> stays channel-blind and placement-blind. No store gains a placement parameter, no
> query filters on one, and no ranking reads one. ADR-0187 §4's floor is untouched.

> **Normative.** **Notifications.** No `NotificationCandidate` gains a placement and no
> notification is placed by this ADR. ADR-0199 §3's fourth and fifth clauses and
> ADR-0206 govern the delivery path exactly as they do, and a candidate "references and
> does not contain" the records it names, so placing a record does not reach through to
> a candidate naming it.

> **Normative.** **Grants.** ADR-0199 §6's first clause binds: no `SourceGrant`
> authorises speech, no `GrantScope` member expresses a placement, and no lane reads a
> standing grant as permission to put anything on an output channel.

> **Normative.** **Egress.** Nothing here authorises egress, relaxes any permission
> floor, widens any grant, or is cited toward a designation, a registration or a
> destination. ADR-0017 §1 and §3, ADR-0154 §2 and ADR-0155 §1 and §3 are untouched.

### 9. Scope: the `core` surface, the version, and the decode of a record written before this

> **Normative.** The `core` change is exactly: `MemoryBase` gains `placement`;
> `Provenance` loses `supplied_withheld_content`; `Placement`, `PlacementReach` and
> `PlacementSetter` are added; `FeedbackEvent` gains `guarded: bool = False`;
> `RoutableOperation` gains `GUARD` and `UNGUARD`; and the `AssistantEngine`
> **Protocol** gains `guard` and `unguard` with §7's signatures. `FeedbackProcessor`'s
> **signature** does not move — the member rides the event it already takes — but its
> **behavioural contract** does, per §7. No other Protocol changes in either sense, and
> there is no `Settings` field, no `ContextFacet` and no `NotificationCandidate`
> member.

> **Normative.** The Protocol change is the reason this ADR is ratified and merged
> before anything implements against it, and it is stated rather than left to be
> inferred from "the promoted surface": `AssistantEngine` is a `Protocol` in
> `core/protocols.py` — "the assistant's whole request surface, as a client sees it"
> (ADR-0085 §1), provided by `orchestration` and consumed by `interfaces` — so adding
> to it is golden rule 5's breaking change and carries golden rule 5's obligations.

> **Normative.** **`PROTOCOL_VERSION` moves for this decision**, on **two independent
> grounds**, and ADR-0124 §9's test is applied rather than asserted past. It moves
> **once per change that changes a frame**: §11's first change moves it on the two
> grounds below, and §11's second moves it again for `FeedbackEvent.guarded`, a member
> a client sets. Two entries in `wire/envelope.py`'s log, each naming its own reason,
> is what that file's own practice requires; collapsing them into one bump would leave
> a released version whose log entry does not describe it.

> **Normative.** The **first ground is the promoted surface's method set.** §7 adds
> `guard` and `unguard` to `AssistantEngine`, and ADR-0210 §8 names that limb of
> ADR-0124 §9's reach in terms — "§9's reach is the frame — its encoding, the validity
> of a wire-carried `core` type, and **the promoted surface's method set**". A frame a
> peer at the new version may send names an operation a peer at the old version does not
> serve. This ground stands on its own and is sufficient.

> **Normative.** The **second ground is the wire-carried `core` type**, and it is
> stated because it is the one with a disclosure consequence. `MemoryBase` and
> `Provenance` *are* wire-carried: `TurnResult.memories` is `tuple[MemoryRecord, ...]`,
> and ADR-0210 §8 reasons from exactly that — "`TurnResult.memories` — wire-carried
> inside `TurnOutcome.turn`" and "every `Provenance` a hub at the new version emits is
> valid for a peer at the old one". A member is **removed** from `Provenance` and a
> member carrying the same answer added to `MemoryBase`. Neither type sets
> `extra="forbid"`, so no decode *fails* in either direction — and that is precisely
> the hazard: a peer at the older version decoding a record from a hub at the newer one
> reads `supplied_withheld_content` as its `False` default on a record whose placement
> is `OWNER`, and a peer at the newer version decoding an older hub's record reads the
> default placement on a record that hub had stamped. Both are ADR-0124 §9's second
> limb — "accepted by it with a different meaning" — on a disclosure-bearing value, and
> the meaning that is lost is the restrictive one.

> **Normative.** This is a different case from the one ADR-0204 §7 and ADR-0210 §8
> settled, and neither is cited as having answered it. Both ruled on a value the hub
> **computes** for a field whose shape is unmoved; ADR-0210 §8's own words are "No
> frame changes shape or encoding, no member is added or removed". Here a member is
> added and a member is removed. The nearer precedent is ADR-0187 §5's account of
> ADR-0181 §3, where *adding* a member to a wire-carried type bumped the version.

> **Normative.** ADR-0204 §7's hub-authoritative clause is **kept as a live
> condition**, and generalised: the placement is set in the hub, no client sets it, and
> no component reads it off a wire-received record to decide anything. A later decision
> that gives any client, spoke or gateway a rule keyed on a placement **as received
> over the wire** owes ADR-0124 §9's test afresh in its own text and may not cite this
> section as having answered it.

> **Normative.** **A record already in a store is decoded, never defaulted.** The
> implementing lane maps a `provenance.supplied_withheld_content` of `true` to a
> placement of reach `OWNER` and setter `DERIVED` at **decode**, and `false` or absent
> to the default. The mapping is total, one-directional and applied wherever a record
> carrying the legacy member is decoded, and no lane relies on a separate migration pass
> or on a store being rewritten before it is read. **The load-bearing site is the
> persistent store**, which holds records written under ADR-0204 and is read on the
> first turn after the upgrade; the wire is covered by the same mapping and by the
> version bump above, which is what keeps a peer at the old version from being handed
> one of these records at all. Without it every record ADR-0204 narrowed would decode
> as unnarrowed on the day this landed, which is ADR-0204 §1's fourth clause hazard —
> a decode default read as a measurement — with a disclosure consequence.

> **Normative.** Two **prose edits inside `core/types.py`** are owed rather than merely
> permitted, on ADR-0210 §8's second clause's own reasoning: `Provenance`'s class
> docstring carries five paragraphs describing `supplied_withheld_content` and its
> ADR-0210 exception, and `_speakable`'s docstring in `orchestration/disclosure.py`
> says the fourth read "is not a placement at all". Both describe a field that will not
> exist and a vocabulary this ADR fixes. The lane states the rule where the field now
> lives and cites this ADR beside ADR-0204 §1 and ADR-0210 §1.

### 10. The representative-input tests this decision owes

> **Normative.** The implementing lane pins **the reduction**: a record with reach
> `OWNER` is absent from the supply of a turn on a channel of unbounded audience and
> present, unchanged and unmarked, in the supply of the same turn on a channel of
> bounded audience.

> **Normative.** The lane pins **the conjunction**: a record with the default placement
> whose class ADR-0199 §3 does not place speakable is still withheld from an unbounded
> channel, so that no placement is ever read as making something speakable.

> **Normative.** The lane pins **the ADR-0204 equivalence, arm for arm**: every arm of
> ADR-0204 §8's tests, restated over reach `OWNER` in place of `True`, comes out as it
> did — including §5's fold, the derivation's narrowest-over-every-record-supplied
> rule, and the `SUPERSEDE` differential.

> **Normative.** The lane pins **ADR-0210 §1's composition**: an `OWNER`-placed record
> a relevance read returned is withheld and fires the deflection; an `OWNER`-placed
> record the supply holds only in ADR-0074 §5's first group is withheld and fires
> nothing, and the captured episode of that turn carries the default placement.

> **Normative.** The lane pins **each precedence arm**: a proposal on a record whose
> setter is `OWNER_ACT` writes nothing; a proposal on a record whose setter is
> `DERIVED` writes nothing; a widening act on a `PROPOSED` record succeeds; a widening
> act on a `DERIVED` record is refused; a narrowing act on a `DERIVED` record changes
> nothing and is not an error.

> **Normative.** The lane pins **the floors**: a widening act on a record whose
> `about_person` is stated leaves it withheld from an unbounded channel, and no
> placement admits a Tier 0 value anywhere.

> **Normative.** The lane pins **the decode**: a stored record carrying
> `supplied_withheld_content: true` and no placement decodes to reach `OWNER`, setter
> `DERIVED`, and is withheld from an unbounded channel on the first read after the
> upgrade.

> **Normative.** The lane pins **the two operations, through the shared
> `AssistantEngine` conformance suite**: each returns the record's placement after the
> act; each returns `None` for an id naming nothing live; each raises `ValueError` on a
> blank id; and `unguard` on a `DERIVED` placement returns it unchanged — reach `OWNER`,
> setter `DERIVED` — rather than raising.

> **Normative.** The lane pins **the stamping cases of §7 one by one**, because they
> are where an implementation can satisfy the prose and break §3. A `guard` on a
> placement whose setter is `PROPOSED` or `None` writes setter `OWNER_ACT`; a second
> `guard` on the result returns a value **identical to the first's**, the instant
> included, because nothing was written; an `unguard` on a `DERIVED` placement leaves
> the setter `DERIVED`, so a later `guard` and `unguard` pair cannot launder it to
> `OWNER_ACT` and then to `ANYONE`; and a `guard` on a `DERIVED` placement changes
> nothing and is not an error.

> **Normative.** The lane pins **§4's boundary with a deterministic fake provider**,
> which the precedence arms above cannot reach. Three arms: a proposal on a record whose
> placement is the default *succeeds* and writes reach `OWNER` with setter `PROPOSED`,
> so the mechanism is shown to work at all; the producer's provider-call **count** over
> a pass is what it is without this decision, so no call is added; and on every read
> path — supply, composition, delivery and any rendering — the provider-call count is
> likewise **unchanged from what it is without this decision**, so a turn whose reply
> ADR-0170's composing stage produces still makes that stage's own call and no other.
> The arm is *no additional call*, and it is not *no call*: composition is
> model-backed by construction, and an arm demanding zero calls there would be a test
> no conforming implementation could pass. What it catches is the breach §4's second
> clause exists for — a classification call added at a read — which every other arm
> here would let through.

> **Normative.** The lane pins **the write-time act on the shared
> `FeedbackProcessorContract`**, so that every implementation and the canonical fake
> are bound by it and not one of them: a `FeedbackEvent` carrying `guarded=True`
> produces records placed reach `OWNER` with setter `OWNER_ACT`, and one carrying the
> default produces records placed by §6's default. The arm is taken at that seam and
> not through the CLI, because the flag reaches the processor unread by any adapter.

> **Normative.** The lane pins **the inherited bound**: `guard` and `unguard` raise
> `OversizedValueError` for an oversized `record_id`, in the `AssistantEngine`
> conformance suite beside the other members that carry it.

> **Normative.** The lane pins **the same-reach tie**: a record a guarded write and a
> proposal both place `OWNER` records setter `OWNER_ACT`; a record the derivation and an
> owner's act both place `OWNER` records setter `DERIVED`.

> **Normative.** The lane pins **the negative arm**, without which the rest can pass
> vacuously: a store of records all carrying the default placement answers a spoken
> turn exactly as it does today, with nothing withheld and no deflection composed.

### 11. What the implementing lane owes

> **Normative.** **The `core` field move is not separable from its readers, and the
> lane does not attempt it.** `Provenance.supplied_withheld_content` is read or written
> today at exactly these sites, and the inventory is stated in full rather than left to
> be rediscovered: `core/types.py`, `memory/ingest.py` (the fold's disjunction on both
> arms), `orchestration/consolidation.py` (the stamp assigned over the records
> consolidated), `orchestration/disclosure.py`, `orchestration/observation.py`,
> `orchestration/conversations.py`, `orchestration/engine.py` and
> `ai_assistant/testing/writer.py`. A change removing the field without every one of
> them leaves a tree that does not type-check and, were it deployed, a spoken turn that
> raises on the first record it places, or a fold that silently drops ADR-0204 §5's
> ratchet. So the removal, the addition on `MemoryBase`, the three new types, the decode
> mapping of §9 and **every site above** land in **one change**.

> **Normative.** That change therefore spans `core`, `memory`, `orchestration`, `wire`
> and `testing`, and its width is a property of a `core` field removal rather than a
> lane's choice: **no** split of it compiles. The lane states that in its PR
> description, names this clause, and widens the change no further — a site not in the
> inventory above and not required by §9 is outside it.

> **Normative.** That same change carries §7's `AssistantEngine` members, their
> conformance-suite arms, the canonical fake in `ai_assistant.testing`, the
> `RoutableOperation` members and the routing that resolves and dispatches them
> (`orchestration/routing.py`), the two prose edits of §9, and the
> `PROTOCOL_VERSION` bump with its `wire/envelope.py` log entry. It is one unit of work
> on `CLAUDE.md`'s contract-seam exception — a contract and the primary implementation
> whose demands shape it, together (ADR-0137 §2) — and the lane states that exception
> when it opens, because a change spanning `core`, `orchestration`, `wire` and
> `testing` is otherwise more than one change.

> **Normative.** The **second change** is §7's write-time act, entire and atomic:
> `FeedbackEvent.guarded` in `core/types.py`, the `FeedbackProcessor` implementations
> in `learning/` that honour it, the guarded-event arm on `FeedbackProcessorContract`,
> `FakeFeedbackProcessor` in `ai_assistant.testing`, and its own `PROTOCOL_VERSION`
> bump with its `wire/envelope.py` entry. It spans `core`, `learning` and `testing` on
> `CLAUDE.md`'s contract-seam exception (ADR-0137 §2) — a contract member, the
> conformance suite that binds it, the canonical fake and the primary implementation
> are one unit of work — and §7's last clause is why no split of it is admissible.

> **Normative.** §4's model proposal is a **third change**, in `learning/observer.py`
> and its tests alone. It lands after the first, is independent of the second, and
> changes no `core` definition and no Protocol.

> **Normative.** `assistant learn --guarded` and any rendering of a placement are a
> **fourth change**, in `interfaces/` and its tests alone (`CLAUDE.md`, "Interface
> adapters are thin"): the adapter sets `FeedbackEvent.guarded` and decides nothing.
> It lands after the second, because a flag reaching a processor that ignored it would
> be a control silently doing nothing.

> **Normative.** No lane reads the ordering above as licence to widen any of the three.
> Anything not named in one of them is a change of its own.

> **Normative.** The records this decision owes on ADR-0204, ADR-0199 and ADR-0210 are
> made in **this ADR's own PR** (ADR-0082 §1, ADR-0070 §1), and are header-only.

### 12. Deferred, by name, each with the condition that fires it

> **Normative.** **Named people and circles as denotable reaches** — #1718, item 4.
> Fires when person identity exists (#691). Additive by §1's fifth clause: it adds
> denotations and supersedes no clause here.

> **Normative.** **Class-level acts** — "guard everything about my health". Fires when
> a record carries a topic (ADR-0213, #1791) and a class posture has a surface
> (ADR-0199 §6's last clause). This ADR decides per-record acts only.

> **Normative.** **The household question** — ADR-0199 §7, unchanged and not narrowed.

> **Normative.** **A `DERIVED` narrowing the owner cannot lift** (§3). Tracked as its
> own question and fired by a store on which the accumulation is measured, as #1775
> measured ADR-0204's before ADR-0210 bounded it. Until then the two ratified routes —
> a supersession, and a class ruling under ADR-0199 §6 — are the answer.

> **Normative.** **Widening the set of producers that propose a placement** (§4).
> Fires when a model-backed producer other than `Observer` writes a record that is not
> derived from records of this store, or when a measurement shows the observer's
> proposals leave a class of record unreached. Until then `Observer` is the only
> proposer and §3's inheritance places everything else.

> **Normative.** **Supplying a learned preference to the proposer** (§5). Fires with an
> ADR that gives a model-backed producer an input beside the episodes it is handed —
> `Observer.observe`'s signature is the seam, and widening it is a Protocol change
> golden rule 5 puts behind its own ADR. Until then a proposal is made without one, and
> the corrective loop closes through the owner's per-record act.

> **Normative.** **Rendering a placement on a bounded surface.** §2 rules that nothing
> is withheld there and §7 rules that nothing is obliged to render one. Whether a
> beliefs list *shows* a placement is a surface decision no clause here settles.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**Against ADR-0204 this is a partial supersession, on §1's second limb.** A reader
holding only ADR-0204 would write a `bool` on `Provenance` and would read it at a supply
site; after this ADR they would write a `Placement` on `MemoryBase`. That is acting
differently, so the record is owed and the instrument is supersession rather than
amendment. What is *not* superseded is the decision ADR-0204 took: the same records are
narrowed, on the same evidence, by the same producer, at the same site, and §5's ratchet
and its closing prohibition bind whole. The header names the clauses.

**Against ADR-0199 this is a partial supersession of §3's third clause and of nothing
else**, on the same footing ADR-0204's own record took: a reader holding only ADR-0199
would place a record its §3 places speakable, and after this ADR a record whose
placement does not admit the channel is withheld however §3 would place it. §6 is a
stacked addition and §7 above states that test in full.

**Against ADR-0210 this is an amendment.** ADR-0210's decision — which members of the
supply the evaluation ranges over — is unchanged in every particular, and §2's last
clause above applies it verbatim. What fails ADR-0082 §1's test is narrower: §1's third
clause and §8's third clause name `Provenance.supplied_withheld_content` by field, and a
reader holding only ADR-0210 would look for a field that no longer exists. Under
ADR-0070 §1 that reconciles the ADR with a fact that postdates it while leaving a reader
acting identically once they hold both, which is an amendment; under ADR-0082 §2 the
record goes on the `Status` line — ADR-0210's carries no leading token — and in the dated
note.

**Against ADR-0085 no record is owed, and the addition is stated rather than assumed.**
ADR-0085 §1 makes `AssistantEngine` "the assistant's whole request surface, as a client
sees it"; §7 adds two members to it. Would a reader holding only ADR-0085 now act
differently, or read one of its clauses more widely than it now holds? No — a surface
described as *whole* is not a surface described as *closed*, and the corpus has added to
it before on exactly this footing: `standing_grants` is a member ADR-0139 §2 added, and
ADR-0197 §3's widening rule presupposes that the promoted surface grows. This is a
stacked addition under ADR-0082 §1, recorded in this ADR and nowhere else. What it is
*not* is a change anyone may make without an ADR: golden rule 5 binds, which is why the
header flags the Protocol break and why this ADR is merged before its implementation.

**Against ADR-0203, ADR-0100, ADR-0197, ADR-0201, ADR-0130 and ADR-0021 no record is
owed.** ADR-0203 §1's subtraction and §2's bounds are used as given and every sentence of
them stays true. ADR-0100's axis is untouched and §8 says so. ADR-0197 §3's widening rule
is *satisfied* by §7, which is what that rule is for, and ADR-0201 §1's lookup is used
unchanged. ADR-0130 §11 forbids a model ruling on a **notification candidate** and this
ADR adds no such ruling; §4 answers its three grounds because they are the right grounds,
not because §11 reaches this case. ADR-0021 §5's monotonicity is cited as a precedent for
the shape of §3's precedence and is not touched.

## Consequences

**The owner can guard one fact, which they could not do before, and it costs one act.**
That is #1719's gap closed on its own terms: not a tier, not a subject, not a grant —
the owner's wish about this record.

**The spoken channel gets quieter in exactly one direction and never louder.** Every
clause can only subtract, so the worst outcome of a wrong proposal is a deflection where
an answer would have done, and the owner can see why (the stamp) and lift it (one act).
The worst outcome of a *missing* proposal is today's behaviour.

**A model now sits in front of a disclosure-bearing field, and that is a real change of
posture.** It is bounded three ways — it may only narrow, it runs only at write, and it
runs only where a provider was already being consulted — and the read stays a field read.
But the corpus has not had a model write into a disclosure decision before, and a reader
should see that stated rather than discovered.

**`PROTOCOL_VERSION` moves twice, so every spoke redeploys twice.** That is the cost of
moving a member of a wire-carried `core` type and of adding the promoted surface's two
operations, and then of a second member a client sets. §9 takes it deliberately in
preference to a silent disagreement between a hub and a spoke about a disclosure-bearing
field, and §11's ordering means neither redeployment is on a tree that accepts an
instruction it does not act on.

**A store carries `DERIVED` narrowings the owner cannot lift.** §12 names it as a residue
with two ratified escapes. It is the price of keeping ADR-0204 §5's closing prohibition,
and #1708 is why that price is worth paying.

**Four changes follow, not one**, and §11 orders them and bounds each. The first is
large and cannot be made smaller: the field move, its decode mapping and every
production reader of the removed field are one commit, because any split of them is a
tree that does not type-check or a deployment that widens every narrowed record. It
takes `CLAUDE.md`'s contract-seam exception and says so.

## Alternatives considered

**A second field beside ADR-0204's mark.** A `placement` on `MemoryBase` with
`supplied_withheld_content` kept on `Provenance` as the measured warrant fact. It has one
real merit: the two questions genuinely are different, and keeping both records both
answers. Rejected because #1719's first point rules against it and because the safety
argument agrees with the owner — two recorded values in front of one read is a standing
invitation for a supply site to consult one of them, and the failure is silent. The
warrant fact is not lost: a placement whose setter is `DERIVED` *is* the record that the
derivation fired.

**Retyping the field in place on `Provenance`.** The smallest possible diff, and the most
literal reading of "a widening of ADR-0204's mark". Rejected on ADR-0100 §2's placement
rule: the question the widened field answers is "who may receive this", which is the
envelope's question and not `Provenance`'s, and ADR-0045 §2's refusal to mix producer-set
and applier-set fields on that class points the same way. Keeping it on `Provenance`
would also have cost the same `PROTOCOL_VERSION` bump, since a retype moves the member's
wire shape, so the smaller diff buys nothing on the version question.

**A guarded-by-default placement.** Rejected by #1719's sixth point and by ADR-0199 §3's
own exit-test argument. It is the shape a safety-first reading of the corpus would
produce and it would make the assistant useless out loud on day one.

**Letting the owner widen a `DERIVED` narrowing.** Attractive because the residue in §12
is real. Rejected because ADR-0204 §5's closing prohibition is not about this record's
sensitivity but about content the owner may not admit having stood in its warrant, and
ADR-0199 §6's fourth clause is the ratified statement that the owner may not admit it.
The escape hatches are a supersession and a class ruling, both of which act on something
other than the derivative.

**A model proposal on every belief write.** #1719's stated lean. Rejected as unreachable
rather than as wrong: a fold, a calendar import and a reader's proposal are belief writes
with no model in front of them, so "every write" would mean minting a provider call at
seams that have none — and the model-backed seam that is *not* the observer,
`orchestration/consolidation.py`, produces records derived from records of this store,
which §3's inheritance already places — a new model seam in `memory/`, which golden rule 4 and ADR-0015 §5
would each want an ADR for. Riding the pass a producer already makes covers the writes
that carry a model's judgement and makes "budgeted" exact.

**A recogniser in `learning/` for correction utterances.** Rejected in §5: a new event
kind and a new capture path, to reach a generalisation the observer already makes from an
episode the act already produces.

**One `place(record_id, placement)` operation instead of two.** Rejected by ADR-0197 §3's
second clause, which puts an operation taking "a second varying argument — a scope, a
mode" outside the routable vocabulary until a decision says how that argument is chosen,
rendered and confirmed. Two single-argument members need no such decision.
