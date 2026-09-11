# 245. Reach is audience control, so a derived owner-reach record composes a search bound to a destination the user chose

- Status: Partially superseded by ADR-0246 (§1's third clause in the two-facts rule it states — no record-level fact keeps information out of a query bound to a destination of recorded trust `USER_CHOSEN`; §2's third, fourth and fifth clauses, so an `OWNER_ACT` and a `PROPOSED` narrowing are admitted and the positively-stated admitted set of two combinations ceases to describe what a supply admits; §3's first clause and its second clause in the limb presupposing a validator, `SearchSupply`'s `AfterValidator` and its predicate being deleted and the type refusing no placement; §7's second clause in the sentence naming what `withheld` counts on a chosen destination, that count now being zero on every path; §8's first and second clauses, replaced by arms over the budget and the destination; §9's first clause in its differing-outcome limb, the two readings it leaves unresolved no longer differing in what a supply admits; §11 Arm B in its exclusion limb, Arm D entire and Arm F in its premise; and §12's fourth deferral in its exclusion half. Those scopes, and nothing else in this ADR — §12's second deferral is **discharged** by the ruling it named as its trigger and §10 by the lane that has landed; §1's other five clauses, §2's first, second and sixth clauses, §3's third and fourth clauses, §4, §5, §6, §7's first and third clauses, §8's third clause, §9's second and third clauses, §11 Arms A, C and E, §12's first and third deferrals, §13, §14 and §15 bind as written)
- Date: 2026-09-11
- **Partially supersedes** [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md)
  — **§2's validator clause in the rule it states, §3's first clause, §11's
  enumeration of what the record gains in that enumeration alone, §12's second
  clause in the rule it restates, and §15 Arm 4.** Those five scopes, and nothing
  else in that ADR: §1, §4, §5, §6, §7, §8, §9, §10, §13, §14, §16, §17 and §18 bind
  entire, §2's remaining clauses bind entire and §2's cross-turn promise is relied on
  as written and made reachable, §3's second and third clauses bind **verbatim**, and
  §11's one-event/one-key/counts-only rules and §12's other five arms bind entire.

- **Partially superseded: 2026-09-11 by [ADR-0246](0246-reach-does-not-bind-at-all-on-a-search-bound-to-a-destination-the-user-chose-and-the-supply-type-refuses-no-placement.md)
  — the scopes named on the `Status` line above, and nothing else.** §12's second deferral
  is **discharged** rather than superseded, and §10's obligations fell on the lane that has
  landed.

  **The instrument this ADR reserved is the one that was used.** §2's closing paragraph
  ruled that "The ruling's *logic* — a provider is not a person the assistant talks to —
  reaches `OWNER_ACT` and `PROPOSED` as readily as it reaches `DERIVED`", and that the
  instrument for widening it is "one sentence of this section and an owner who was asked".
  §12 named the trigger: "Fired by an owner ruling that addresses the explicit act, which
  the 2026-09-11 ruling did not." The owner was asked and ruled the same day, on #2224's
  successor thread, that the logic does reach both setters. ADR-0246 is that one sentence.

  **The ruling, on three grounds.** A model's proposed narrowing answers a question about
  *people* — ADR-0217 §4's judgement about whether the owner would want a belief repeated
  where others hear — and says nothing about a provider; and beliefs are what "taking my
  preferences into account" draws on, `learning/observer.py` stamping one reach `OWNER`
  setter `PROPOSED` when the observation pass flags it, so under §2 a preference could
  silently drop out of a follow-up query. The owner's explicit guard is defined by ADR-0217
  §3 as setting reach and nothing else, and a guarded record has never meant "local only".
  And "never leaves the machine" is an egress question that would be a **tier** with its own
  act (ADR-0004 §1), not a reach — overloading `Placement.reach` with it would be the
  category error ADR-0238 §3 made; ADR-0246 §12 defers that class by name.

  **So on a `WEB_SEARCH` request bound to a destination of recorded trust `USER_CHOSEN`
  under a recipient grant, `Placement.reach` does not bind at all**: no record is withheld
  from the `SearchSupply` on reach or on setter, whatever the setter. The validator goes
  with the rule — `core/types.py`'s `_placed_for_a_search_supply` and
  `_admitted_to_a_supply` are deleted and `SearchSupply.records` becomes a plain
  `tuple[MemoryRecord, ...]` — because what the validator ever enforced was the placement
  predicate, §3's third clause already fixes the trust condition at the one construction
  site, and a check that cannot fail asserts a rule the corpus no longer holds.

  **What ADR-0246 does not loosen, and what it costs.** Reach keeps its full force on every
  channel a person can perceive: ADR-0217 §1 and §2, ADR-0199 §3, ADR-0203 §1 and
  `orchestration/disclosure.py` are untouched, and a guarded record stays unspeakable to a
  roommate or another user of the hub exactly as today. ADR-0199 §3's Tier 0 floor is
  untouched. On an `UNCHOSEN` destination nothing loosens — §2's second clause binds entire.
  ADR-0238 §2's three populations, ADR-0193's grant, ADR-0181 §5's lineage floor and
  ADR-0238 §5's closed-loop conditions are untouched and are what remains. The cost is
  stated rather than hedged: **there is no per-record instrument left by which a user keeps
  something out of a search query bound to a chosen destination**, and §5's dependency on
  ADR-0238 §1's single recorded user act now carries the whole weight.

  **The audit keeps four counts.** `withheld` keeps ADR-0238 §11's definition and is zero on
  every path; the supplied-narrowed count §7 added keeps its definition and now counts every
  setter, rising the day ADR-0246's lane lands. No fifth count and no per-setter breakdown,
  which ADR-0246 §12 defers.

  **What is relied upon as written.** §1's first, second, fourth, fifth and sixth clauses,
  including ADR-0013 §6's configured-set bound and the statement about the admitted *set*
  rather than one endpoint; §2's Tier 0 floor, its `UNCHOSEN` clause and its absent
  `about_person` filter; §3's trust-stays-at-the-builder clause and its restatement of
  ADR-0238 §3's second, third and fourth clauses; §4's `core`-surface and `PROTOCOL_VERSION`
  findings, re-applied at ADR-0246's tree to the same answers; §5 entire, restated with its
  weight named; §6's composer guidance, which ADR-0246 §10 leaves untouched and §12 defers
  changing; §7's one-event rule and its supplied-narrowed count; §8's third clause; §9's
  corridor and what would close it; §11 Arms A, C and E; §12's first and third deferrals;
  and §15's marking, both-lens and ratification rules, which ADR-0246 follows too.

  This ADR's `Status` line read `Accepted`, so it takes the leading `Partially superseded by`
  token and `Accepted` is dropped, as `docs/adr/template.md` requires. Appended note per
  ADR-0070 §1; no text below is rewritten. Refs #2227, #2224, #2178, #2168, #1908.

## Context

### Where this comes from

ADR-0238 §2 promises that a later turn of a conversation resolves *find more about
that* over the conversation's own captured episode:

> **What a later turn has instead is the captured episode**, stamped and retrieved
> exactly as ADR-0221, ADR-0223 and retrieval already deliver it, plus whatever
> `MemoryRecord`s the turn selected. That is what resolves "find more about **that**"
> across turns, and it is the first two populations doing the work rather than the
> third.

ADR-0238 §3's first clause withholds exactly that record:

> A record whose reach is `PlacementReach.OWNER` is not supplied to a `QueryComposer`
> on any conforming path, and §2's validator is where that is enforced.

A stamped episode of a conversation that read a search result carries reach `OWNER`
with setter `DERIVED`, because ADR-0204 §2's disjunction is true of the turn that
produced it and ADR-0217 §3 writes that narrowing into `Placement`. So §3's filter
removes the very record §2 names, the composer is handed the utterance and nothing
else, and it declines. #2224 drove this live on a scratch hub at `8f40cf09` and read
the placements out of the store:

```text
23:52:50  planner_calls=2  returned=1 disposition=None      supplied=0 withheld=0 calls=1
                           returned=0 disposition=deadline_expired supplied=1 withheld=0 calls=2
23:53:14  planner_calls=1  returned=0 disposition=composer_declined supplied=0 withheld=1 calls=3
23:53:46  planner_calls=1  returned=0 disposition=composer_declined supplied=0 withheld=2 calls=4
```

`withheld` climbs by one per turn while `supplied` stays zero. ADR-0238 §15 Arm 1b —
milestone 31's own cross-turn exit arm — therefore has no reachable producer. Both
halves are normative, both are implemented correctly, and #2224 states the choice
precisely: either §3's filter admits the conversation's own stamped episodes, "or §2's
sentence about what a later turn has is wrong and the ADR should say what actually
crosses."

### The owner's ruling of 2026-09-11, which this ADR records

The question was routed to the security pass beside #2212 and then re-routed out of it
by the owner, on #2224:

> Reach and the withheld classes are audience control: they protect the owner from
> people the assistant talks to (a roommate, a house cleaner, another user), not from
> a search provider the owner chose and granted, which is "mostly anonymous and won't
> affect my life". ADR-0238 §3 borrowed that axis to answer a provider-disclosure
> question already answered by the grant + trust (and injection by the lineage floor /
> closed loop). So this is an amendment honouring §2's promise, not a posture change.

The ruling is the owner's and this ADR records it rather than deriving it. What this
document owes is the statement of it that a lane can act on, the classes it does not
reach, and an honest account of what is given up.

### Three questions, three layers, and the one the reach axis answers

The corpus already separates three questions, and reading them apart is what makes the
ruling legible rather than a relaxation.

- **Secrets.** ADR-0199 §3's first clause: "No reply and no delivery, on a channel of
  any audience, carries a Tier 0 value or any span of one (ADR-0004 §1). This is a
  floor rather than a posture: no user act, no configuration, no grant and no later ADR
  short of one superseding this clause admits one to an output channel." This ADR
  touches no word of it and supersedes no clause of ADR-0199.
- **Audience.** `Placement.reach` is, in ADR-0217 §1's own words, "a **denotation of a
  set of people**", and its two shipped members denote every person and the owner
  alone. ADR-0217 §1's vocabulary clause keeps that distinct from the class rule:
  "ADR-0199 §3 *places a class* as speakable **on a channel**; this ADR *places a
  record* **for a set of people**." Both protect the owner from people the assistant
  talks to.
- **Provider.** Whether this system may disclose to a party at all is a recipient
  grant (ADR-0193); whether that party is one the user picked by name is destination
  trust (ADR-0238 §1); and whether an attacker's bytes can steer what is disclosed is
  the lineage floor (ADR-0181 §5) and the closed-loop condition (ADR-0238 §5).

ADR-0238 §3 answered the third question with the second question's axis. Its own
reasoning says so plainly — "`Placement` records *who may receive this record*; a
search provider is not the owner" — and that step is the one the owner has now ruled
against: a search provider is not a *person* the assistant talks to, so the set-of-people
denotation does not decide whether a record may be composed over for it.

### The tree, read rather than assumed, at `origin/main` `8f40cf09`

- `SearchSupply` is live in `core/types.py`, with `records` annotated
  `AfterValidator(_reachable_by_anyone)`; that function refuses any member whose
  `placement.reach` is not `PlacementReach.ANYONE` and its message cites ADR-0238 §2,
  §3 on ADR-0217 §1's reach.
- `_search_supply` in `orchestration/reads.py` returns `SearchSupply(utterance=...)`
  with a withheld count of **zero** on an `UNCHOSEN` destination, and otherwise filters
  the admissible population on `record.placement.reach is PlacementReach.ANYONE`,
  counting the remainder as withheld.
- `SearchSupply` is named in `core/types.py`, `core/protocols.py`,
  `orchestration/reads.py`, `planning/composer.py`, `permissions/policy.py` (in a
  docstring) and `testing/queries.py`. It is named in **no** module of `wire/` and in
  **no** module of `interfaces/`.
- `planning/composer.py`'s `_SYSTEM_PROMPT` already carries the guidance the caveat
  below is about: "The request may be followed by notes this assistant already holds.
  They are there to resolve what the request refers to … Use them only for that. Do not
  search for a note, do not repeat one back, and do not carry a detail from one into
  the query unless the request is asking about it."

So the enforcement question §5 of the brief poses is about moving a rule that is
already implemented at a site that already exists, not about designing one.

### What this ADR is not allowed to settle

It does not re-read ADR-0217, ADR-0199 or ADR-0204. It narrows no clause of any of
them, adds no axis, tag or band, and supersedes nothing in them. Where ADR-0217 §3
carries two readings (§9 below), it names the ambiguity and leaves it to the ADR that
owns it. It does not touch ADR-0238 §5's closed-loop condition, §6's reach, §8's
budget or §1's trust fact. It decides nothing about an `UNCHOSEN` destination, which
ADR-0238 §16 reserves to milestone 32's ADR.

## Decision

### 1. Reach is audience control, and a `DERIVED` narrowing does not withhold a record from a supply built for a destination the user chose

> **Normative.** `Placement.reach` records **who may receive a record**, in ADR-0217
> §1's sense of a denotation of a set of **people**, and a withholding taken on that
> axis is audience control. It binds wherever this system speaks to a person, entire
> and unchanged, and this ADR subtracts nothing from any clause of ADR-0217, ADR-0199
> or ADR-0204.

> **Normative.** **It does not withhold a record from a `SearchSupply` built for a
> destination whose recorded trust is `DestinationTrust.USER_CHOSEN`** (ADR-0238 §1).
> On such a supply a `MemoryRecord` whose `placement.reach` is `PlacementReach.OWNER`
> and whose `placement.set_by` is `PlacementSetter.DERIVED` is **admitted**, whichever
> of ADR-0238 §2's three populations selected it — the conversation's own stamped
> episodes, the records the turn's retrieval and episodic supplement selected, and this
> turn's own minted `WEB_SEARCH` records alike.

> **Normative.** **This supersedes ADR-0238 §3's first clause**, whose sentence "A
> record whose reach is `PlacementReach.OWNER` is not supplied to a `QueryComposer` on
> any conforming path" ceases to be true of a `DERIVED` narrowing on a `USER_CHOSEN`
> destination, and whose first sentence ceases to be exclusive: the record-level facts
> that keep information out of a query are `Placement.reach` **and**
> `Placement.set_by`, both read exactly as ADR-0217 §1 defines them. **The limb this
> ADR restates rather than supersedes is the one it honours**: no field, member, axis,
> tag or band is added by this ADR either, and `Placement.set_by` is a field ADR-0217
> §1 already ships and §3 already gives its meaning.

> **Normative.** **ADR-0238 §2's cross-turn promise is honoured rather than replaced.**
> Its sentence — "What a later turn has instead is the captured episode … That is what
> resolves *find more about that* across turns" — is relied on as written and becomes
> **reachable**: the stamped episode a later turn retrieves carries reach `OWNER` with
> setter `DERIVED`, and is admitted by the clause above. No clause of §2 is superseded
> except its validator clause (§3 below), and ADR-0238 §15 Arm 1b acquires the producer
> #2224 found it had none of.

> **Normative.** **The condition is §2's trust read and nothing more, and the grant
> still decides whether anything leaves.** ADR-0238 §2 already obliges a `trust_of`
> read before the supply is built and rules that its answer "decides only *what may be
> composed over*"; that is the read this section's admission runs under. The recipient
> grant (ADR-0193), the lineage floor (ADR-0181 §5) and ADR-0238 §5's four closed-loop
> conditions are **untouched** and continue to decide, at the ruling point and at the
> moment the request is built, whether any byte reaches the destination. A supply
> composed over and then not sent is the shape this corpus already has — composition is
> a `ModelProvider` call inside `planning` and "the transport is not entered until
> after the ruling" (ADR-0238 §15 Arm 5d) — and nothing here moves the boundary.

> **Normative.** **The composition reaches no party the turn's own model calls are not
> already admitted to reach.** A `QueryComposer` holds a `ModelProvider` and nothing
> else that reads (ADR-0231 §3, ADR-0238 §2), and on the only operations where a supply
> exists at all (§2 below) the turn's planner is supplied the same records over the same
> seam. **That is a statement about the admitted *set* and not about one endpoint**:
> `RoutingProvider` tries its routes in order on each request and "A routable failure
> advances to the next candidate" (ADR-0013 §2), so a composition may answer from a
> route the same turn's planning did not reach. What bounds the set is ADR-0013 §6 — a
> route list may contain "**only providers the user has explicitly configured**", and
> "Falling back is not permission to reach a provider the user never chose" — which is
> the bound the turn's planning already runs under, unchanged. **No clause of this ADR
> adds a party to that set**, and none is read as promising per-call recipient
> continuity across two model calls of one turn.

**Why the channel question is already closed, mechanically, before this ADR runs.**
ADR-0226 §5 rules that "**A read request is not serviced on an operation whose output
channel's audience is unbounded**". A `WEB_SEARCH` is a read request (ADR-0231 §9), so
on an operation whose channel audience is unbounded **no `SearchSupply` is constructed
at all** — the servicer does nothing. Every supply this ADR widens therefore belongs to
an operation whose channel audience is bounded, which is the operation on which
ADR-0203 §1's subtraction is not applied because there is no wider audience to withhold
from. The owner's ground — "not leaking info to people using the assistant themselves"
— is not a promise this ADR makes; it is a property the corpus already enforces one
stage earlier, and this ADR neither adds to it nor leans on it for anything else.

**The honest accounting, in ADR-0238 §4's own discipline.** What widens is the
population a query may be composed over: from records placed for every person to those
records plus records the *derivation* narrowed to the owner. What that buys is
milestone 31's cross-turn subject. What it costs is that a query bound to the provider
may now carry wording shaped by a record ADR-0204 narrowed, and §9 below states the
residue rather than claiming it is closed. No clause of this ADR is read as re-establishing
ADR-0231 §12's structural property, which ADR-0238 §4 already took away.

### 2. What stays excluded, by name

> **Normative.** **Tier 0, everywhere.** ADR-0199 §3's first clause is a floor and this
> ADR supersedes no word of it: no supply, query, request or delivery carries a Tier 0
> value or any span of one, on a destination of any trust. ADR-0238 §12's credential
> clause binds entire.

> **Normative.** **Everything ADR-0238 §3 excludes today, on an `UNCHOSEN`
> destination.** Nothing loosens there. ADR-0238 §2's clause that "A supply carrying a
> non-empty `records` is constructed only for a destination whose recorded trust is
> `USER_CHOSEN`" binds entire, so on such a destination the supply carries the
> utterance and an empty `records` and ADR-0231 §3's utterance-only property holds for
> it exactly as ratified.

> **Normative.** **A narrowing the owner made by their own act.** A record whose
> `placement.set_by` is `PlacementSetter.OWNER_ACT` and whose `placement.reach` is not
> `PlacementReach.ANYONE` is **excluded from every `SearchSupply`**, on a destination of
> any recorded trust, and is refused at construction exactly as ADR-0238 §3's first
> clause refused an `OWNER` reach before this ADR.

> **Normative.** **A narrowing a model proposed.** A record whose `placement.set_by` is
> `PlacementSetter.PROPOSED` is excluded on the same terms, its reach being `OWNER` by
> ADR-0217 §1's table in every legal state.

> **Normative.** **The admitted set is therefore exactly one class and is stated
> positively**: a `SearchSupply` admits a record whose `placement.reach` is
> `PlacementReach.ANYONE`, and a record whose `placement.reach` is `PlacementReach.OWNER`
> **and** whose `placement.set_by` is `PlacementSetter.DERIVED`. It admits no other
> combination, and a later reach denotation ADR-0217 §1 permits is admitted by no clause
> here until the ADR that adds it says so.

> **Normative.** **No `about_person` filter is added at the supply.** ADR-0199 §3's
> withheld classes are placements *of a class on a channel* and this ADR does not
> convert one into a supply rule: ADR-0217 §1's vocabulary clause — "ADR-0199 §3
> *places a class* as speakable **on a channel**; this ADR *places a record* **for a
> set of people** … No implementation, lane or later ADR collapses them" — binds here,
> and §1's channel-scoping paragraph is why the class rule has already had its effect
> before a supply exists. A record whose `about_person` is stated is admitted or refused
> by its `Placement` alone, exactly as it is today.

**The ground for excluding the owner's own act, which is the one point the ruling left
open.** Four reasons, and the first is the operative one.

- **The ruling's subject is the derivation.** The owner's words are about "these
  withholdings" — ADR-0199 §3's classes and ADR-0204's stamp — and every one of those
  is a narrowing *this system computes*. `OWNER_ACT` is the one setter the system does
  not compute: it is a per-record instruction a person gave, by
  `assistant learn --guarded` or by `guard` after the fact (ADR-0217 §7), and **the
  system records the act and not its reason**. Admitting it would be deciding what the
  owner meant by it. That is inference about an owner act, and it is the move ADR-0238
  §1 refuses on the neighbouring axis in terms — the fact is "set by a recorded act of
  the user and by nothing else" — and that ADR-0217 §3's precedence refuses on this
  one, where the owner's act is final and the other two setters may only narrow.
- **The exit arm would otherwise have no subject.** Milestone 31's negative arm on
  #1908 is written over an "*excluded*" record, and ADR-0217 §7's guard is the only
  surface by which a user makes a record excluded by an act of their own. A reading
  that admits it leaves the arm asserting nothing a user can reach.
- **The asymmetry of recourse.** A record wrongly withheld costs a search the user can
  re-ask, and the owner lifts the withholding in one recorded act (`unguard`). A record
  wrongly composed into a query cannot be un-sent. Where the texts leave a class
  undecided, the direction with a one-act recourse is the one to take.
- **It costs the ruling nothing.** #2224's driven defect is the conversation's own
  stamped episodes, read out of the scratch store as `{"reach": "owner", "set_by":
  "derived"}`. Arm 1b becomes reachable on `DERIVED` alone, so excluding `OWNER_ACT`
  withholds nothing the ruling asked for.

**And the same ground decides `PROPOSED`, which neither the ruling nor the brief
named.** A `PROPOSED` narrowing is a model's judgement about audience (ADR-0217 §4),
not the derivation ADR-0204 §2 performs over a supply. The ruling is about the
derivation; a setter it did not name is not admitted by it. Excluding it also keeps
ADR-0238 §12's third arm — "An injected result cannot make a destination trusted" —
neighboured by the symmetric property that no model-written placement decides what
enters a supply either.

**This is the narrow reading, taken deliberately.** The ruling's *logic* — a provider is
not a person the assistant talks to — reaches `OWNER_ACT` and `PROPOSED` as readily as
it reaches `DERIVED`. This ADR supersedes only as far as the ruling **speaks**, because
the instrument for widening it is one sentence of this section and an owner who was
asked, and the instrument for narrowing it again after a disclosure is nothing at all.

### 3. The enforcement stays on the type, and the type stays blind to trust

> **Normative.** **`SearchSupply` refuses at construction** any `records` member whose
> `placement` is not one of §2's two admitted combinations. **This supersedes ADR-0238
> §2's validator clause in the rule it states** — "any `records` member whose
> `placement.reach` is not `PlacementReach.ANYONE`" — and **restates the rest of that
> clause verbatim**: "The refusal is on the type, so no producer, decode, test double or
> later lane can construct a supply carrying an excluded record."

> **Normative.** **The validator reads `Placement` and nothing else.** It reads no
> destination, no `DestinationTrust`, no `DestinationTrustRecord`, no `RecipientGrant`,
> no `EgressBinding` and no conversation record, and it is passed none. `core` stays
> blind to trust, and `core/protocols.py` gains no member and `core/types.py` no field
> from this decision.

> **Normative.** **The trust condition stays at the builder, unmoved.** `_search_supply`
> in `orchestration/reads.py` keeps the branch that returns an empty `records` for an
> `UNCHOSEN` destination, which is ADR-0238 §2's clause that "which one applies is
> decided by a recorded fact and never by a judgement" and which that ADR already fixes
> as a property of the one construction site rather than of the type. The division of
> labour between the site and the type does not move; only the type's rule does.

> **Normative.** ADR-0238 §3's second and third clauses bind **verbatim** and this ADR
> restates neither into a weaker form: no component decides exclusion by inspecting
> content, no lane reads any section here as licence to filter by resemblance, keyword,
> classifier or detector, and the one-bit residue §3's third clause states is
> unchanged and unnarrowed (§9 widens its *shape* and closes nothing). ADR-0238 §3's
> fourth clause, on the `__dict__` bypass and the absent detachment obligation, binds
> entire.

**Why the check stays on the type rather than moving to the builder.** ADR-0238 §2's
whole argument for relocating ADR-0093 §10's bound is that "a caller able to widen the
read is a caller able to defeat the bound", so "what is genuinely given up is narrower
than the shape of the change suggests": the property moved "from the absence of a
parameter to the validator on the value". A version of this decision that deleted the
validator and left the builder to filter would hand that bound back to the caller — "a
supply site that passed the right records would be conforming and one that passed the
wrong ones would be a defect nobody could see from the signature" — which is the shape
§2 refuses in terms. So the validator stays, and what changes is one predicate inside
it.

**And the predicate can be written without trust because §2 already decided the
`UNCHOSEN` case at the site.** A supply for an `UNCHOSEN` destination carries an empty
`records`, so a non-empty `records` implies the chosen path without the type having to
know it. The type never needs the fact, which is what keeps golden rule 2 and this
decision's `core` surface at nothing.

### 4. The `core` surface and the version

> **Normative.** This decision adds **no** member to any `core` type, **no** member to
> any Protocol in `core/protocols.py`, **no** error to `core/errors.py` and **no**
> field to `core.config.Settings`. What changes in `core` is one validator's predicate
> on `SearchSupply.records` — the population the existing field admits — and nothing
> else. ADR-0238 §13's enumerated surface stands, and every other member of every
> `core` type keeps its type, its default and its meaning.

> **Normative.** **`PROTOCOL_VERSION` does not move**, on ADR-0124 §9's rule. Read at
> `origin/main` `8f40cf09`, `SearchSupply` is named in no module of `wire/` and in no
> module of `interfaces/`: it is `QueryComposer.compose`'s in-process argument and
> crosses no frame. This decision adds no member to the connect exchange, changes no
> frame's encoding and changes no promoted method's arguments or results.
> `ConversationExport.schema_version` stays at **2** and no stored record's decode
> changes. **A lane that finds either statement false moves the corresponding version
> in the same change** rather than reading this clause as permission not to — ADR-0238
> §13's own instruction, restated because it applies to this lane too.

> **Normative.** **No stored record is re-read, back-filled or reinterpreted.** A
> `Placement` already in a store decodes exactly as it does today; what changes is which
> of them a supply admits, decided fresh at each construction from the value the record
> carries.

### 5. This decision rests on ADR-0238 §1, and says so

> **Normative.** **The whole of this decision rests on ADR-0238 §1's clause that a
> destination's trust is set only by a recorded act of the user.** This ADR quotes it,
> changes no word of it, and relies on it entire:
>
> ```text
> The fact is **set by a recorded act of the user and by nothing else**.
> No configuration sets it, no connected account sets it, no operator setting
> sets it, no tool declaration sets it, no `RecipientGrant` sets it, and **no
> model output ever sets it, raises it, or is consulted about it**. A model may
> not propose a destination's trust, may not be shown a destination in order to
> judge it, and no component infers the fact by inspecting a destination, a
> host, a response, or any content whatever.
> ```

> **Normative.** **Any later loosening of that clause reopens this decision.** An ADR
> that lets a configuration, a connected account, an operator setting, a tool
> declaration, a grant, a default or a model output set, raise or contribute to a
> destination's trust does not merely widen ADR-0238 §1; it removes the ground on which
> §1 above admits a narrowed record to a supply at all. Such an ADR states in its own
> text what becomes of this decision, and no lane reads the clause above as surviving
> the change that made `USER_CHOSEN` reachable without a user.

**This is the one caveat that is not about degree.** Every other bound here — the
budget, the audit, the closed-loop condition, the lineage floor — bounds a channel that
exists. This one is the reason the channel is acceptable at all: the party on the far
end is a party the owner named in a recorded act. A `USER_CHOSEN` a deployment could
reach by configuring an account would make that sentence false while leaving every
clause of this ADR literally satisfied, which is exactly the failure worth naming in
advance.

### 6. The composer is not the user, and the answer is guidance already in the prompt

> **Normative.** **No filter, rule or test of content is added at the composer.**
> ADR-0238 §3's second clause binds: no component decides exclusion by inspecting
> content, and no lane reads this section as licence to gate, redact, score or
> classify a query, a supply or a record by any reading of text. ADR-0231 §11's clause
> that the only value `WebSearcher.request` is passed is the composer's own `query`,
> byte for byte, binds entire.

> **Normative.** **What the composer carries into a query is left to the model, and
> `planning/composer.py`'s `_SYSTEM_PROMPT` already carries the guidance.** At
> `origin/main` `8f40cf09` it reads: "The request may be followed by notes this
> assistant already holds. They are there to resolve what the request refers to … Use
> them only for that. Do not search for a note, do not repeat one back, and do not
> carry a detail from one into the query unless the request is asking about it." The
> implementing lane **may leave that prompt untouched**, and if it changes anything it
> adds at most one short clause of the same kind. It is guidance and not a rule, no
> bound in this corpus is bought from it, and **no arm of §11 asserts over the prompt's
> words or over a query's content**.

**The caveat is real and the answer is deliberate.** The composer may carry more
specifics than the search needs — a name, an identifier, a detail the request did not
ask about — and nothing here stops it. The alternatives are a content filter, which
ADR-0238 §3's second clause forbids and ADR-0098 §6 refuses as a gate, or a second
model pass judging the first's output, which buys a judgement nobody can check and
costs a call. The owner's decision is the model's judgement under one line of guidance,
and the line was already written.

### 7. The audit

> **Normative.** ADR-0238 §11's first clause binds entire: **no second audit, no second
> event key and no new emission point**. One `INFO`-level structured log event per turn,
> under the one fixed key, carrying the ambient correlation identifier and no other
> identifier. Its **counts only** rule binds entire — no record id, no conversation id,
> no destination, no query text, no fragment or length of one, no title, no snippet and
> no provider message — as does its clause that the destination's recorded trust is not
> written to this event.

> **Normative.** **The `withheld` count keeps its definition and changes what it
> measures.** It is, as ADR-0238 §11 states it, "the count of records withheld from the
> supply by §3's filter" — now §3's filter as §2 and §3 above narrow it. On an
> `UNCHOSEN` destination it stays **zero**, because the whole population is withheld by
> §2's trust clause and not by the filter, which is the value the tree already writes.
> On a `USER_CHOSEN` destination it counts the records refused for carrying an
> `OWNER_ACT` or `PROPOSED` narrowing, and on the same deployment it therefore **falls**
> the day this lands. No lane, surface or measurement reads that fall as fewer
> withholdings.

> **Normative.** **The record gains one further count: the number of records supplied
> to the composer whose `placement.reach` is not `PlacementReach.ANYONE`.** **This
> supersedes ADR-0238 §11's enumeration of what the record gains, in that enumeration
> alone** — a reader holding only §11 would build a three-count record and believe it
> complete. Every other clause of §11 binds unchanged: it is a count, it goes in the
> same event under the same key at the same emission point, and it carries no
> identifier.

**The instrument is owed for the same reason §11 owed the first three.** ADR-0238 §11
argues that "A deployment that has given up a structural property owes itself a number
for how often the loop actually re-searched and how much of the supply it was given."
This decision gives up a second one, and without the count above the only number that
moved is `withheld` — which *falls*, so a deployment reading the event would see less
withholding and nothing at all about the class that now flows. One count restores the
symmetry, and it is a per-population figure rather than a per-turn one (ADR-0226 §8).

### 8. The negative arm, restated over the narrowed set

> **Normative.** **An injected result cannot carry an excluded record into a query.**
> §3's validator refuses a `placement` outside §2's two admitted combinations at
> construction, evaluated per record and **regardless of why that record was
> selected**, so no selection a result influences can place an `OWNER_ACT` or
> `PROPOSED` narrowing in a supply. **This supersedes ADR-0238 §12's second clause in
> the rule it restates** — "§2's validator refuses a non-`ANYONE` reach at
> construction" — and keeps its property, its per-record evaluation and its
> regardless-of-selection limb entire over the narrowed excluded set.

> **Normative.** **An injected result cannot widen the admitted set.** The admitted
> combinations are stated over recorded fields of `Placement`, which ADR-0217 §3 lets
> three setters write and a model reach only as `PROPOSED` — which §2 excludes. No
> search result, model output, request content or provider message writes, raises or is
> consulted about a record's placement on any path this ADR opens.

> **Normative.** ADR-0238 §12's other four clauses bind entire and this ADR restates
> none of them into a weaker form: an injected result cannot raise the budget, cannot
> make a destination trusted, cannot widen the closed-loop population, and cannot make
> a binding claim a closed loop; and credentials stay out structurally with ADR-0231
> §12's one residue unchanged.

### 9. The residue, stated rather than closed

> **Normative.** **A record derived over a supply that held a guarded record may carry
> a `DERIVED` narrowing and be admitted here.** ADR-0217 §3 rules that "Where ADR-0204
> §2's own evaluation is `True` of **this** record's production, the record is reach
> `OWNER` setter `DERIVED` on that ground alone, whatever its inputs carried", and it
> also rules that a derived record's setter "follows this section's order over the
> supplied placements that carry the surviving reach", under which an `OWNER_ACT` input
> supplies the strongest setter. **This ADR resolves neither reading and narrows
> neither**; where the second governs, the derived record is excluded by §2, and where
> the first governs, a sentence descending from a guarded record may reach a supply and
> a query.

> **Normative.** **That is ADR-0098 §5's corridor in one further shape, and no clause
> here is an assurance about it.** ADR-0238 §3's third clause states the residue for a
> paraphrase "carrying no `OWNER` reach"; this decision extends the same residue to a
> paraphrase carrying `OWNER` reach with a `DERIVED` setter. It is not detected, is not
> subtracted, and no detector closes it (ADR-0098 §5, §6). **No lane states, implies or
> relies on this decision detecting what descends from a guarded record.**

> **Normative.** **What would close it is named and is not taken here**: a recorded,
> per-record fact distinguishing a narrowing the system computed from one that descends
> from an owner's act — which is the shape of the provenance field ADR-0098 §5 and §12
> already defer, on the ground that it is `core` surface owed its own ADR and that
> ADR-0073 §4 wants it decided "with a producer in hand". §12 below defers it with what
> fires it.

### 10. What the implementing lane owes

> **Normative.** **One PR, in `orchestration/` and `core/` only.** The change is
> `_reachable_by_anyone`'s predicate in `core/types.py` (and its name, its docstring
> and its refusal message, which cite the superseded rule), the docstring of
> `SearchSupply.records`, the withheld-count arithmetic and the new supplied-narrowed
> count in `orchestration/reads.py`, and the audit event's fields at ADR-0238 §11's one
> emission point. **No Protocol changes**, so this is not a triad and adds no
> conformance suite; `testing/queries.py`'s canonical composer fake is extended only if
> an arm below needs it.

> **Normative.** **The lane changes no word of ADR-0217, ADR-0199, ADR-0204, ADR-0098
> or ADR-0231**, and no clause of ADR-0238 outside the five scopes this ADR's header
> names. It moves `PROTOCOL_VERSION` only if it finds §4's finding false, in which case
> it moves it in the same change and says so.

> **Normative.** **The lane re-drives #2224's scenario on a scratch hub** — the
> cross-turn arm of ADR-0238 §15 Arm 1b, over the fixture
> `tests/tools/answering_origin_harness.py`, with the runbook corrections #2225 records
> — and puts what it saw in its PR description: `supplied` non-zero on a later turn, the
> composer not declining, and the turn's query resolving the reference the utterance
> alone does not.

> **Normative.** **The lane files nothing and defers nothing this ADR has not named.**
> Findings outside this change are issues under `CONTRIBUTING.md`'s triage rule, not
> growth of the PR.

### 11. The representative-input tests this decision owes

> **Normative.** Each arm below is a test the implementing lane owes, over the
> production type, the production builder and the production servicing path, and not
> over a double standing in for one of them. ADR-0238 §15's other arms bind entire and
> are unchanged.

> **Normative.** **Arm A — ADR-0238 §15 Arm 1b, now with a producer.** A later turn of
> a conversation whose destination reads `USER_CHOSEN`, whose supply carries the
> conversation's stamped episode placed reach `OWNER` setter `DERIVED` and no minted
> record of any earlier turn, composes a query resolving a reference the utterance alone
> cannot; the supply's `records` is non-empty, the composer does not decline, the ruling
> is `ALLOW` on route (b) with the binding carrying both `planned_with_external_content`
> and `closed_loop` true, and the user is asked nothing. **The arm asserts the supplied
> count is non-zero and the withheld count is zero**, which is the pair #2224 read the
> other way round.

> **Normative.** **Arm B — ADR-0238 §15 Arm 4, in its narrowed form, and this replaces
> it.** A record placed reach `OWNER` setter `OWNER_ACT`, and one placed reach `OWNER`
> setter `PROPOSED`, are each refused by `SearchSupply` at construction — in a selection
> a search result influenced and in one it did not — and each reaches the audit's
> withheld count; a record placed reach `OWNER` setter `DERIVED` in the same two
> selections is **admitted** and reaches the new supplied-narrowed count. The refusal is
> asserted on the type directly, so that a builder that filtered correctly could not
> make the arm pass.

> **Normative.** **Arm C — the about-person record, both paths.** A `MemoryRecord`
> whose `about_person` is stated and whose placement is reach `OWNER` setter `DERIVED`
> is admitted to the supply on a `USER_CHOSEN` destination and composed over; with every
> other fact identical and the trust record absent, the supply carries the utterance and
> an empty `records`. The arm asserts that **no `about_person` filter runs at the supply
> in either case** — the second supply is empty because §2's trust clause emptied it,
> not because the subject axis was read.

> **Normative.** **Arm D — the owner's act survives every route into a supply.** On a
> `USER_CHOSEN` destination, a guarded record is refused when the turn's retrieval
> selected it, when the episodic supplement selected it, and when it arrived as this
> turn's own minted `WEB_SEARCH` record; and a supply built from a population containing
> one is **refused entirely rather than silently pruned by the type**, so a builder that
> forgot to filter fails loudly at the one construction site.

> **Normative.** **Arm E — a revocation between turns flips the supply back to
> utterance-only.** A conversation searches on turn one with a non-empty supply; the
> destination's trust record is revoked; turn two's supply carries the utterance and an
> empty `records`, its withheld count is zero, and its request is not closed-loop. The
> arm exists because §1's admission is stated over a *read* and ADR-0238 §1's
> prospectivity is what makes the next read answer `UNCHOSEN`.

> **Normative.** **Arm F — the audit's two counts move in opposite directions and both
> are asserted.** Over one turn carrying an admitted `DERIVED` narrowing and a refused
> `OWNER_ACT` one, the event records the supplied count, the withheld count, this turn's
> `calls` **and** the supplied-narrowed count §7 adds, each at its true value, and the
> event carries **the ambient correlation identifier and no other identifier** — which
> is ADR-0238 §11's own rule, restated here so that the arm cannot be satisfied by
> dropping the field §7 keeps.

### 12. Deferred, by name, each with what fires it

- **A recorded fact distinguishing a computed narrowing from one descending from an
  owner's act** (§9). Fired by the ADR that decides ADR-0098 §5's deferred provenance
  surface, or by an ADR that resolves ADR-0217 §3's two readings and finds the residue
  reachable in practice. **Not fired** by a lane wanting to infer the distinction from
  content, which ADR-0098 §6 forbids.
- **Admitting an `OWNER_ACT` or `PROPOSED` narrowing** (§2). Fired by an owner ruling
  that addresses the explicit act, which the 2026-09-11 ruling did not. Not fired by a
  lane finding the logic symmetric — §2's closing paragraph says why symmetry is not
  the instrument.
- **Anything about an `UNCHOSEN` destination.** ADR-0238 §16's deferral stands
  untouched and this ADR adds nothing to it.
- **A reach denotation beyond `ANYONE` and `OWNER`** (ADR-0217 §1). Fired by the ADR
  that adds one, which states what a supply does with it; §2's admitted set names two
  combinations and no more, so a third denotation is excluded until then.

### 13. Scope, and what this records against earlier ADRs

**Superseded, and nothing else.** Five scopes of ADR-0238, each named in this
document's header and each stated in the section that takes it: §2's validator clause
in the rule it states (§3); §3's first clause (§1); §11's enumeration of what the record
gains, in that enumeration alone (§7); §12's second clause in the rule it restates (§8);
and §15 Arm 4 (§11 Arm B).

**Relied on as written, by name.** ADR-0238 §1 entire (§5 quotes it); §2's remaining
clauses, including the two-population rule, the single construction site, the
three-population closure and the cross-turn promise §1 makes reachable; §3's second,
third and fourth clauses; §4's accounting; §5's four closed-loop conditions and its
window; §6's reach; §8's budget; §11's one-event, one-key and counts-only rules; §12's
other five clauses; §13's `core` surface; §15's other arms; §16's deferrals.

**No record is owed on ADR-0217, ADR-0199, ADR-0204, ADR-0098, ADR-0193, ADR-0181 or
ADR-0231**, on ADR-0082 §1's test: every sentence each of them wrote stays true and
none is read more widely. ADR-0217 §1's reach keeps its denotation and its vocabulary
clause; ADR-0217 §3's setters and precedence are read as written and §9 declines to
resolve the one ambiguity rather than narrowing it; ADR-0199 §3's floor and classes are
untouched and §2 restates the floor rather than qualifying it; ADR-0204 §2's evaluation
and §5's ratchet are inputs to this decision and are not moved; ADR-0098 §5's corridor
is quoted and unnarrowed; ADR-0193's grant and ADR-0181 §5's floor are left standing at
the ruling point, which §1's fifth clause states in terms; ADR-0231 §3's composer
signature and §11's byte-for-byte query clause are untouched.

**ADR-0226 §5 and ADR-0013 §2 and §6 are relied on and not amended.** §1's
channel-scoping paragraph reads ADR-0226 §5 exactly as it stands and adds no obligation
to it; §1's sixth clause takes its bound from ADR-0013 §6's configured-set rule and
reads ADR-0013 §2's per-request fallback as written rather than claiming continuity
across it.

### 14. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Each edit, with §1's test applied: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

- **ADR-0238 §2's validator clause** — **yes**. A reader holding only §2 builds a type
  refusing every non-`ANYONE` reach, which would refuse the stamped episode §1 above
  admits. **Supersession** in the rule that clause states; its "refusal is on the type"
  limb is restated verbatim in §3 and loses nothing.
- **ADR-0238 §3's first clause** — **yes**, and this is the decision. Its sentence "A
  record whose reach is `PlacementReach.OWNER` is not supplied to a `QueryComposer` on
  any conforming path" becomes false of one combination, and its first sentence's
  exclusivity — that the record-level fact is `Placement.reach` — becomes over-wide once
  `set_by` decides too. **Supersession.** Its "no field, member, axis, tag or band
  added" limb is restated and honoured rather than replaced.
- **ADR-0238 §3's second, third and fourth clauses** — **no**. Nothing here inspects
  content, the one-bit residue is unchanged and unnarrowed (§9 extends its *shape*, and
  says so, without claiming any assurance §3's third clause disclaims), and the
  `__dict__` bypass and the absent detachment obligation are untouched.
- **ADR-0238 §2's cross-turn promise** — **no**. It stays true word for word and becomes
  reachable. A promise honoured is not a promise amended, and a reader holding only §2
  acts identically.
- **ADR-0238 §11's enumeration** — **yes**. A reader holding only §11 builds a
  three-count record and believes it complete; §7 requires a fourth. **Supersession**,
  in that enumeration alone. §11's one-event, one-key, counts-only, no-identifier and
  no-trust-written clauses are untouched, and its `SearchDisposition` clause — already
  partially superseded by ADR-0241 — is not approached.
- **ADR-0238 §11's definition of `withheld`** — **no**. The clause says "withheld from
  the supply by §3's filter", which is a reference to §3 and not a restatement of §3's
  predicate. §3 moves; the sentence stays true of the filter as it now stands. §7 states
  what the number measures so that a reader is not left to work it out, which is
  disclosure and not an amendment.
- **ADR-0238 §12's second clause** — **yes**. It restates the validator's rule as "a
  non-`ANYONE` reach", which becomes false. **Supersession**, in that restatement alone;
  the arm's property, its per-record evaluation and its regardless-of-selection limb are
  restated entire in §8 over the narrowed set.
- **ADR-0238 §12's other five clauses** — **no**. Budget, trust, closed-loop population,
  the binding's `closed_loop` and the credential floor are each untouched, and §8's
  third clause says so.
- **ADR-0238 §15 Arm 4** — **yes**. It is stated over `OWNER` in terms and would fail
  against the type §3 describes. **Supersession**; §11 Arm B replaces it and asserts
  more than it did.
- **ADR-0238 §15's other arms** — **no**. Arm 1b gains a producer without its text
  moving; Arm 2, Arm 5's family, Arm 6's family, Arms 7–9 are untouched. Arm 1a is
  untouched: a minted record of this turn carries whatever placement it carries and
  §2's admitted set decides it, exactly as before for an `ANYONE` one.
- **ADR-0238 §13** — **no**. Its enumeration is of the surface *that decision* added;
  §4 above adds nothing to it and changes no member's type, default or meaning. Its
  "a lane that finds either statement false moves the corresponding version" instruction
  is restated in §4 as applying to this lane, which adds no obligation to §13.
- **ADR-0238 §14** — **no**. It binds the lane implementing *that* ADR, which has
  landed; §10 binds a different lane and takes nothing from it.
- **ADR-0217 §1, §3, §6, §7** — **no**, on all four. The reach keeps its denotation,
  the vocabulary clause is quoted and honoured, the three setters and their precedence
  are read as written, §6's "this ADR adds narrowing only" is untouched because nothing
  here writes a placement at all, and §7's acts are relied on as the surface that makes
  §2's `OWNER_ACT` class reachable. §9 explicitly declines to resolve §3's two readings,
  which is the opposite of reading one more widely.
- **ADR-0199 §3** — **no**. Its floor is restated as a floor, its withheld classes stay
  channel placements, and §2's `about_person` clause keeps ADR-0217 §1's vocabulary
  separation rather than collapsing it.
- **ADR-0204 §2 and §5** — **no**. The derivation and the ratchet are inputs this
  decision reads and neither is moved; nothing here changes what is stamped, when, or
  over what supply.
- **ADR-0098 §5 and §6** — **no**. §9 quotes the corridor, extends the residue's shape
  and disclaims any assurance about it, which is what §5 requires of anyone who touches
  it; §6's refusal of a detector as a gate is restated in §3 and §6.
- **ADR-0226 §5** — **no**. §1 reads its clause and draws a consequence from it; it adds
  no obligation and states no exception.
- **ADR-0193, ADR-0181 §5, ADR-0231 §3 and §11** — **no**. §1's fifth clause leaves each
  standing at the point it already governs, and §6 restates ADR-0231 §11's
  byte-for-byte clause rather than qualifying it.
- **ADR-0013 §2 and §6** — **no**. §1's sixth clause reads §2's *"A routable failure
  advances to the next candidate"* as written — which is why it is stated over the
  admitted set rather than over one endpoint — and takes §6's *"only providers the user
  has explicitly configured"* as its bound. It adds no obligation to either, states no
  exception, and asks for no change to the routing contract.
- **ADR-0124 §9** — **no**. §4 applies its rule and reaches its "no bump" answer; a rule
  applied is not a rule amended.

**Where the records go.** ADR-0238's `Status` line already leads with `Partially
superseded by`, so under ADR-0082 §2 no amendment qualifier is written on it and the
five scopes are added to that line as one further `ADR-0245 (<scope>)` pair, with the
whole record — supersessions and the §11 enumeration alike — in the appended dated note
ADR-0070 §1 requires. No ratified text of ADR-0238 is rewritten.

### 15. Marking, review and ratification

This ADR is **marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
block quote, and unmarked text beside a mark is read to determine what the mark means
and supplies no obligation of its own. The fenced block in §5 is a **quotation** of
ADR-0238 §1 and makes no mark (ADR-0089 §2).

It is a **contract-surface** decision — it changes what `core/types.py`'s `SearchSupply`
admits — so it owes both the adversarial and the architecture lens (ADR-0015 §1), is
reviewed while `Proposed`, and is ratified by `just adr-ratify` in the one-line flip
ADR-0165 exempts. Under golden rule 5 it merges as its own PR before the implementing
lane §10 describes is briefed, and that lane's authority is the merged text.

## Consequences

**What becomes easier.** Milestone 31's cross-turn subject becomes reachable: a later
turn of a conversation resolves "find more about that" over the episode ADR-0238 §2
already promised would carry it, and ADR-0238 §15 Arm 1b acquires a producer. #2224's
contradiction closes on the side the owner ruled for, and it closes by *honouring* §2
rather than by deleting its sentence. The corpus keeps one axis for audience and gains
no second one.

**What becomes harder.** A query bound to the search provider may now carry wording
shaped by a record ADR-0204 narrowed, and a deployment reading the audit sees its
`withheld` number fall. The distinction between "narrowed because the system computed
it" and "narrowed because the owner said so" becomes load-bearing where it was not
before, which puts weight on `Placement.set_by` that no earlier decision put there — and
§9's residue is where that weight is not yet carried. A reader of ADR-0238 §3 must now
read this ADR to know what the filter does.

**What would trigger revisiting this.** Any loosening of ADR-0238 §1's set-by-a-user-act
clause (§5, which reopens this decision outright). An owner ruling on the explicit act
(§2, §12). A resolution of ADR-0217 §3's two readings that makes §9's residue reachable
in practice. A third reach denotation (§12). And the re-drive §10 obliges coming back
with the composer still declining, which would mean the diagnosis in #2224 was
incomplete rather than this decision wrong.

## Alternatives considered

**Delete the validator and filter at the builder.** Rejected on ADR-0238 §2's own
ground: "a caller able to widen the read is a caller able to defeat the bound", and a
supply site that passed the wrong records "would be a defect nobody could see from the
signature". The type keeps the bound; only its predicate moves.

**Pass the destination's trust into `SearchSupply` and let the type decide.** Rejected.
It would put a destination fact in `core`'s validator for a question §2 already answers
at the one construction site — a non-empty `records` implies the chosen path — and it
would give `core` a reason to know about trust for no gain.

**Admit every `OWNER` reach regardless of setter.** Rejected in §2, on four grounds, the
operative one being that the owner's ruling is about withholdings this system derives
and the explicit act is the one it does not. The narrow reading is reversible by one
sentence and an owner who was asked; the wide one is not reversible at all.

**Add a new axis — a "searchable" flag, band or tag on the record.** Rejected. It is the
second axis ADR-0238 §3 refused to invent, for the reason that section gives, and the
information it would carry is already carried by two fields ADR-0217 §1 ships.

**Rewrite ADR-0238 §2's cross-turn promise instead, and say what actually crosses.**
This is #2224's other branch. Rejected because the owner ruled the axis rather than the
sentence: §2's promise is the milestone's subject, and a decision that kept §3 and
deleted §2's sentence would have closed the contradiction by giving up what milestone 31
is for.

**Add a content-level guard at the composer.** Rejected on ADR-0238 §3's second clause
and ADR-0098 §6 — no bound in this corpus is bought from a filter — and because the
guidance the caveat asks for is already in `_SYSTEM_PROMPT` (§6).
