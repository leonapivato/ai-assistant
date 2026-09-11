# 246. Reach does not bind at all on a search bound to a destination the user chose, and the supply's type refuses no placement

- Status: Proposed
- Date: 2026-09-11
- **Partially supersedes** [ADR-0245](0245-reach-is-audience-control-so-a-derived-owner-reach-record-composes-a-search-bound-to-a-destination-the-user-chose.md)
  — **§1's third clause in the two-facts rule it states; §2's third, fourth and fifth
  clauses; §3's first clause and its second clause in the limb that presupposes a
  validator; §7's second clause in the sentence naming what `withheld` counts on a
  `USER_CHOSEN` destination; §8's first and second clauses; §9's first clause in its
  differing-outcome limb; §11 Arm B in its exclusion limb, Arm D entire and Arm F in its
  premise; and §12's second deferral, which is discharged rather than superseded, and its
  fourth deferral in its exclusion half.** Those scopes, and nothing else in that ADR:
  §1's other five clauses, §2's first, second and sixth clauses, §3's third and fourth
  clauses, §4, §5, §6, §7's first and third clauses, §8's third clause, §9's second and
  third clauses, §10 (discharged by the lane that has landed), §11 Arms A, C and E, §12's
  first and third deferrals, §13, §14 and §15 bind as written.
- **Partially supersedes** [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md)
  — **§2's validator clause in the limb ADR-0245 §3 restated verbatim; §3's first clause
  in the limbs ADR-0245 left standing; and §12's second clause in the remainder ADR-0245
  §8 restated.** Those three scopes, and nothing else in that ADR beyond what ADR-0241,
  ADR-0242 and ADR-0245 already recorded there.

## Context

### Where this comes from

ADR-0245 §1 settled the axis. `Placement.reach` is audience control — ADR-0217 §1's
"**denotation of a set of people**" — and a search provider the owner named in a
recorded act is not a person this assistant talks to, so the reach axis does not decide
whether a record may be composed over for that provider. On that ground ADR-0245 §1
admits a record placed reach `OWNER` setter `DERIVED` to a `SearchSupply` built for a
destination whose recorded trust is `DestinationTrust.USER_CHOSEN`.

ADR-0245 §2 then kept two setters out. A narrowing the owner made by their own act
(`PlacementSetter.OWNER_ACT`) and a narrowing a model proposed (`PROPOSED`) stay
"**excluded from every `SearchSupply`**, on a destination of any recorded trust". §2 said
in terms why it stopped there:

> **This is the narrow reading, taken deliberately.** The ruling's *logic* — a provider is
> not a person the assistant talks to — reaches `OWNER_ACT` and `PROPOSED` as readily as
> it reaches `DERIVED`. This ADR supersedes only as far as the ruling **speaks**, because
> the instrument for widening it is one sentence of this section and an owner who was
> asked, and the instrument for narrowing it again after a disclosure is nothing at all.

ADR-0245 §12's second deferral names the trigger exactly: "**Admitting an `OWNER_ACT` or
`PROPOSED` narrowing** (§2). Fired by an owner ruling that addresses the explicit act,
which the 2026-09-11 ruling did not."

That trigger has fired. The owner was asked and has ruled, on the same day and on the
same issue thread, that the logic does reach both setters. This ADR is the one sentence
§2 reserved, and it records the ruling rather than deriving it.

### The owner's ruling of 2026-09-11, which this ADR records

The ruling is that on a `WEB_SEARCH` request bound to a destination of recorded trust
`USER_CHOSEN` under a recipient grant, **`Placement.reach` does not bind at all** — no
record is withheld from the `SearchSupply` on reach or on setter, whatever the setter.
Three grounds were given, and each is stated here because each answers a different half
of ADR-0245 §2's reasoning.

**1. A model's proposed narrowing answers a question about people.** ADR-0217 §4's
proposal is a model judging whether the owner would want a belief repeated where others
hear; that answer says nothing about a provider. And beliefs are exactly what the
milestone's own sentence — "find more about that, **taking my preferences into
account**" — draws on. The observation pass is where the stamp is made: at
`origin/main` `35a39aa6`, `learning/observer.py`'s `_placement` writes "reach ``OWNER``
with setter ``PROPOSED`` and the instant of the pass" from one optional `guarded` key in
the envelope the model already fills in. Under ADR-0245 §2 a preference the observation
pass had flagged would silently drop out of a follow-up query, and nothing in the turn
would say so.

**2. The owner's explicit guard is defined by ADR-0217 §3 as setting reach and nothing
else.** ADR-0217 §3 gives the act one effect on one axis — "An act may narrow a placement
whose setter is `None` or `PROPOSED` to reach `OWNER`, and may widen one whose setter is
`PROPOSED` or `OWNER_ACT` to reach `ANYONE`" — and §7 states the surfaces that make it.
A guarded record has never meant "local only"; it has meant "not for other people". The
owner's own test for the difference: they would type the same thing into a search engine
at a provider they chose.

**3. "Never leaves the machine" is an egress question and would be a tier, not a
reach.** The tier axis is ADR-0004 §1's — Tier 0 secrets, Tier 1 personal data, Tier 2
operational — and its rules are about channels and logs, not about who may hear a
sentence: Tier 0 never reaches an output channel (ADR-0199 §3's first clause) and Tier
0/1 never reach a log (ADR-0004 §2, §5). **No member of that axis is something a user
puts on a memory record.** Overloading `Placement.reach` with "never leaves the machine"
would be the same category error ADR-0238 §3 made when it answered a provider-disclosure
question with an audience axis. If such a class is ever wanted it is a **new tier with
its own act**, and §12 defers it by name with what fires it.

### What the ruling does not reach, and what this ADR therefore does not touch

Reach keeps its full force on every channel a person can perceive. ADR-0217 §2's
placement of a record for a set of people, ADR-0199 §3's classes, ADR-0203 §1's
subtraction and `orchestration/disclosure.py`'s four reads are untouched: at
`origin/main` `35a39aa6` `_speakable` still refuses a record whose `placement.reach is
not PlacementReach.ANYONE` on a channel whose audience is wider, and **this ADR changes
no word of any of those**. A guarded record stays unspeakable to a roommate, a house
cleaner or another user of the hub exactly as it is today; what changes is one supply
built for a party that is not a person.

Tier 0's floor stays, and it never enters a record in the first place. On an `UNCHOSEN`
destination nothing loosens: ADR-0238 §2's clause that a non-empty `records` is built
only for a `USER_CHOSEN` destination binds entire, so the supply carries the utterance
and an empty `records`. The lineage floor (ADR-0181 §5) and the closed-loop condition
(ADR-0238 §5) are untouched — they answer **injection**, which is a different question
from audience and is not the one this ADR moves.

### The tree, read rather than assumed, at `origin/main` `35a39aa6`

ADR-0245's implementing lane has landed, so what this ADR changes exists and was read
rather than imagined.

- `core/types.py` carries `_admitted_to_a_supply(placement)` — ADR-0245 §2's admitted set
  stated positively — and `_placed_for_a_search_supply`, the `AfterValidator` on
  `SearchSupply.records` that refuses any member outside it. Its message reads "a search
  supply carries only records placed for ANYONE, or narrowed to OWNER by a DERIVED
  narrowing".
- `orchestration/reads.py` carries a **second copy** of the same predicate, deliberately
  and with its reason in the docstring: "the rule is asked twice: by the validator, which
  refuses, and here, where ADR-0238 §11's counts are taken over the population the
  builder holds."
- `_search_supply` returns three values — the supply, the withheld count
  (`len(admissible) - len(supplied)`) and the supplied-narrowed count (`sum(1 for record
  in supplied if record.placement.reach is not PlacementReach.ANYONE)`) — and returns
  `SearchSupply(utterance=utterance), 0, 0` on an `UNCHOSEN` destination.
- `PROTOCOL_VERSION` is **34** in `wire/envelope.py`. `SearchSupply` is named in
  `core/types.py`, `core/protocols.py`, `orchestration/reads.py`, `planning/composer.py`,
  `permissions/policy.py` and `testing/queries.py`, and in **no** module of `wire/` and
  **no** module of `interfaces/`.
- `learning/observer.py`'s `_placement` is the `PROPOSED` producer ground 1 names, and
  `orchestration/disclosure.py`'s `_speakable` is the reach subtraction this ADR leaves
  alone.
- One docstring is **already false** at this commit and was left behind by ADR-0245's
  lane: `planning/composer.py`'s module docstring reads "Every member is placed for
  :attr:`~ai_assistant.core.types.PlacementReach.ANYONE` — ``SearchSupply`` refuses any
  other reach at construction", which ADR-0245 §2 falsified. It is recorded as an issue
  and §10 folds its correction into the implementing lane rather than leaving a module
  describing a check the tree does not have.

### What this ADR is not allowed to settle

It does not re-read ADR-0217, ADR-0199, ADR-0204 or ADR-0004. It narrows no clause of any
of them, adds no axis, tier, tag or band, and supersedes nothing in them — the new tier
ground 3 names is deferred, not created. It decides nothing about an `UNCHOSEN`
destination, which ADR-0238 §16 reserves to milestone 32's ADR. It does not resolve
ADR-0217 §3's two readings, which #2227 records and which §9 below finds moot on this
path and live on its own. It touches no word of ADR-0238 §5's closed-loop condition,
§8's budget or §1's trust fact, and it re-establishes nothing ADR-0231 §12 gave up.

## Decision

### 1. On a destination the user chose, `Placement.reach` does not bind at all

> **Normative.** **On a `WEB_SEARCH` request bound to a destination whose recorded trust
> is `DestinationTrust.USER_CHOSEN` (ADR-0238 §1), `Placement.reach` does not bind at
> all.** No record is withheld from the `SearchSupply` on its reach, on its setter, or on
> any combination of the two, **whatever the setter** — `PlacementSetter.DERIVED`,
> `PlacementSetter.OWNER_ACT`, `PlacementSetter.PROPOSED` and the absent setter alike.
> The population a supply may carry is decided by ADR-0238 §2's three populations and by
> §2's trust read, and by nothing about the records' placements.

> **Normative.** **This supersedes ADR-0245 §2's third, fourth and fifth clauses.** A
> record whose `placement.set_by` is `OWNER_ACT` and whose reach is not `ANYONE` is
> **admitted**; a record whose `placement.set_by` is `PROPOSED` is **admitted**; and §2's
> positively-stated admitted set of "exactly one class … two combinations" ceases to
> describe what a supply admits, there being no combination it refuses. ADR-0245 §12's
> second deferral is **discharged** by the ruling §"the owner's ruling" records, which is
> the instrument ADR-0245 §2's closing paragraph reserved.

> **Normative.** **It also supersedes ADR-0245 §1's third clause in the rule it states**
> — "the record-level facts that keep information out of a query are `Placement.reach`
> **and** `Placement.set_by`" — which ceases to be true on this path: **no record-level
> fact keeps information out of a query bound to a chosen destination.** ADR-0245 §1's
> honouring limb is restated rather than replaced: no field, member, axis, tier, tag or
> band is added by this ADR either, and what it does is subtract a filter rather than
> read a new fact.

> **Normative.** **Reach keeps its full force everywhere this system speaks to a
> person.** ADR-0217 §1's denotation and §2's placement, ADR-0199 §3's classes, ADR-0203
> §1's subtraction and ADR-0204 §2's derivation are untouched by every clause of this ADR,
> which supersedes no word of any of them. A record narrowed to the owner — by an act, a
> derivation or a proposal — stays withheld from every reply and every delivery whose
> audience is wider, exactly as it is today.

> **Normative.** **The condition is ADR-0238 §2's trust read and nothing more, and the
> grant still decides whether anything leaves.** That read is taken before the supply is
> built and "decides only *what may be composed over*". The recipient grant (ADR-0193),
> the lineage floor (ADR-0181 §5) and ADR-0238 §5's four closed-loop conditions are
> **untouched** and continue to decide, at the ruling point and at the moment the request
> is built, whether any byte reaches the destination. ADR-0245 §1's fifth and sixth
> clauses bind entire and are relied on as written, including their bound on the party
> set: ADR-0013 §6's "only providers the user has explicitly configured", and "Falling
> back is not permission to reach a provider the user never chose". **No clause of this
> ADR adds a party to that set.**

**Why this is one sentence rather than a posture change.** ADR-0245 §1 had already ruled
that the axis is wrong for this question. What §2 kept was not a second axis but a
*hesitation*: three setters write one field, the ruling's words named the derivation, and
the lane could not tell whether the owner's act was inside the ruling or outside it. The
owner has now said it is inside. Nothing about who receives what moves; what moves is the
last remnant of ADR-0238 §3's borrowed axis.

**The composition reaches no party the turn's own model calls are not already admitted to
reach.** ADR-0245 §1's sixth clause states this over the admitted *set* rather than over
one endpoint, and it is unchanged by widening what a supply carries: the turn's planner is
supplied the same records over the same seam, and `orchestration/disclosure.py`'s
subtraction is applied at the *reply*, not at the plan. A guarded record already reaches a
`ModelProvider` the owner configured, every turn it is retrieved. What this decision adds
is that a second call of the same turn, to the same configured set, may be composed over
it too.

**And the channel question is closed mechanically before this ADR runs.** ADR-0226 §5
rules that "**A read request is not serviced on an operation whose output channel's
audience is unbounded**", and a `WEB_SEARCH` is a read request (ADR-0231 §9). So every
supply this ADR widens belongs to an operation whose channel audience is bounded. That is
ADR-0245 §1's paragraph, read exactly as it stands, with no obligation added to ADR-0226
§5 and no exception stated to it.

**The honest accounting, in ADR-0238 §4's own discipline.** What widens is the population
a query may be composed over: from records placed for every person, plus records the
derivation narrowed, to **every record the three populations contain**. What it buys is
that a preference the observation pass flagged, and a note the owner guarded, resolve
"taking my preferences into account" instead of silently dropping out. **What it costs is
that the owner has no per-record instrument left for keeping a record out of a search
query.** `guard` is not that instrument and, on ADR-0217 §3's own definition, never was.
The instrument that would be one is a new tier, and §12 defers it rather than inventing
it here.

### 2. What still binds, by name

> **Normative.** **Tier 0, everywhere.** ADR-0199 §3's first clause is a floor and this
> ADR supersedes no word of it: no supply, query, request or delivery carries a Tier 0
> value or any span of one, on a destination of any trust. ADR-0238 §12's credential
> clause binds entire, and ADR-0231 §12's credential residue is unchanged. This costs the
> decision nothing at the supply, because a Tier 0 value does not enter a `MemoryRecord`
> in the first place.

> **Normative.** **Everything ADR-0238 §3 excludes today, on an `UNCHOSEN` destination.**
> Nothing loosens there. ADR-0238 §2's clause that "A supply carrying a non-empty
> `records` is constructed only for a destination whose recorded trust is `USER_CHOSEN`"
> binds entire, so on such a destination the supply carries the utterance and an empty
> `records` and ADR-0231 §3's utterance-only property holds for it exactly as ratified.

> **Normative.** **ADR-0238 §2's three populations bind entire and are the bound that
> remains.** What may enter `records` is closed to episodes of this conversation that
> `orchestration` selected into the turn's supply, the `MemoryRecord` values the turn's
> retrieval and episodic supplement selected, and records **this turn's own** `WEB_SEARCH`
> servicings minted at a destination of recorded trust `USER_CHOSEN`. Membership is a set
> the loop records from the supply it assembled, never a judgement about a record and
> never a reading of its content, and no clause of this ADR widens it.

> **Normative.** **No `about_person` filter is added at the supply**, and ADR-0245 §2's
> sixth clause binds entire. ADR-0217 §1's vocabulary clause — "ADR-0199 §3 *places a
> class* as speakable **on a channel**; this ADR *places a record* **for a set of people**
> … No implementation, lane or later ADR collapses them" — binds here, and a record whose
> `about_person` is stated is admitted or refused by the same rules as any other record,
> which after §1 means it is not refused at all on a chosen destination.

> **Normative.** **No component decides exclusion by inspecting content.** ADR-0238 §3's
> second clause binds verbatim and this ADR restates it into no weaker form: no lane reads
> any section here as licence to filter, gate, redact, score or classify a record, a span,
> a query or a supply by resemblance, keyword, classifier, detector or any reading of
> text. ADR-0098 §5's unrecoverability, ADR-0098 §6's refusal of a detector as a gate and
> ADR-0146 §2's recorded-never-inferred rule bind entire. **A decision that removes a
> recorded-fact filter is not an invitation to add a content one.**

### 3. The type refuses no placement, and the validator is deleted

> **Normative.** **`SearchSupply` refuses no `records` member on its placement**, and
> `core/types.py`'s `AfterValidator` on `SearchSupply.records` —
> `_placed_for_a_search_supply` — and the predicate it calls, `_admitted_to_a_supply`, are
> **deleted**. `records` becomes a plain `tuple[MemoryRecord, ...]` with default `()`.
> **This supersedes ADR-0245 §3's first clause**, and ADR-0238 §2's validator clause in
> the limb ADR-0245 §3 restated verbatim: "The refusal is on the type, so no producer,
> decode, test double or later lane can construct a supply carrying an excluded record"
> ceases to be a rule this corpus holds, there being no excluded record.

> **Normative.** **The deletion hands nothing back to the caller, and that is the test it
> had to meet.** ADR-0238 §2 relocated ADR-0093 §10's bound — "a caller able to widen the
> read is a caller able to defeat the bound" — "from the absence of a parameter to the
> validator on the value", and ADR-0245 §3 kept it there for that reason. What the
> validator ever enforced was the **placement** predicate and nothing else; §1 leaves no
> placement predicate to enforce. The two bounds that remain — ADR-0238 §2's trust clause
> and its three populations — were **never** properties of the type: ADR-0245 §3's third
> clause fixes the trust condition at the one construction site and says in terms that it
> "is not a property this type can hold". So no bound moves from the type to the caller;
> one bound ceases to exist and the other two stay exactly where ADR-0238 §2 put them.

> **Normative.** **The trust condition stays at the builder, unmoved, and `core` stays
> blind to trust.** ADR-0245 §3's third clause binds entire: `_search_supply` in
> `orchestration/reads.py` keeps the branch returning an empty `records` for an `UNCHOSEN`
> destination. No destination, `DestinationTrust`, `DestinationTrustRecord`,
> `RecipientGrant`, `EgressBinding` or conversation record is read by `core` or passed to
> it, and `SearchSupply` gains no field by which it could be. **No lane reads this section
> as licence to pass trust into `core` in order to give the type something to refuse**:
> ADR-0245's alternatives section rejected exactly that, and this ADR rejects it again on
> the same ground.

> **Normative.** **The second copy of the predicate goes with it.**
> `orchestration/reads.py`'s own `_admitted_to_a_supply` exists only to take the counts
> over the population the builder holds, and with §1's rule the count it computed is
> structurally zero. It is deleted, and §7 states what the audit records instead.

> **Normative.** **`SearchSupply` keeps everything else ADR-0238 §2 gave it.** Exactly
> two fields and a lane adds no third; `records` stays an immutable `tuple` defaulting to
> the empty one, on ADR-0231 §3's ground that a caller supplying nothing composes exactly
> as this corpus composed before ADR-0238; the type is still not the unforgeable
> composed-query value ADR-0231 §19 defers; and ADR-0238 §3's fourth clause, on the
> `__dict__` bypass and the absent detachment obligation, binds entire and has one fewer
> check to bypass.

**Why a validator that cannot fail is worse than none.** A check whose predicate is
vacuously true enforces nothing and *states* something — and what
`_placed_for_a_search_supply` would state, kept as a no-op, is the rule the owner has just
ruled against. A later reader would take the presence of an `AfterValidator` on this field
as evidence that some population is refused, and would be wrong. ADR-0089 §1's discipline
for prose applies to code here for the same reason: a mark that binds nothing should not
look like one.

### 4. The `core` surface and the version

> **Normative.** This decision adds **no** member to any `core` type, **no** member to any
> Protocol in `core/protocols.py`, **no** error to `core/errors.py` and **no** field to
> `core.config.Settings`. What changes in `core` is that `SearchSupply.records` loses its
> validator and its two module-level helper functions, and that the field's description
> loses the sentences naming the admitted placements. ADR-0238 §13's enumerated surface
> stands, and every other member of every `core` type keeps its type, its default and its
> meaning.

> **Normative.** **`SearchSupply.records`'s docstring moves**, and what it must still say
> is ADR-0238 §2's: which three populations may enter, that a non-empty `records` is built
> only for a destination whose recorded trust is `USER_CHOSEN`, and why the default is the
> empty tuple. What it must **not** say is that any placement is refused. The same
> correction is owed wherever a docstring cites the deleted validator — at
> `origin/main` `35a39aa6` that is `core/protocols.py`'s `QueryComposer.compose` and
> `planning/composer.py`'s module docstring — and §10 scopes it.

> **Normative.** **`PROTOCOL_VERSION` does not move**, on ADR-0124 §9's rule, and the
> finding is re-checked at this ADR's tree rather than inherited: at `origin/main`
> `35a39aa6` it is **34**, and `SearchSupply` is named in no module of `wire/` and no
> module of `interfaces/`. It is `QueryComposer.compose`'s in-process argument and crosses
> no frame. This decision adds no member to the connect exchange, changes no frame's
> encoding and changes no promoted method's arguments or results.
> `ConversationExport.schema_version` stays at **2** and no stored record's decode
> changes. **A lane that finds either statement false moves the corresponding version in
> the same change** rather than reading this clause as permission not to.

> **Normative.** **No stored record is re-read, back-filled or reinterpreted.** A
> `Placement` already in a store decodes exactly as it does today, keeps its reach, its
> setter and its instant, and is read by every other consumer of the field exactly as it
> is read today. What changes is that one consumer — the supply — stops reading it.

### 5. This decision rests on ADR-0238 §1, and rests on it harder

> **Normative.** **The whole of this decision rests on ADR-0238 §1's clause that a
> destination's trust is set only by a recorded act of the user**, and ADR-0245 §5 binds
> entire, quoted rather than restated:
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

> **Normative.** **Any later loosening of that clause reopens this decision**, on
> ADR-0245 §5's terms and with more at stake than when it wrote them. An ADR that lets a
> configuration, a connected account, an operator setting, a tool declaration, a grant, a
> default or a model output set, raise or contribute to a destination's trust removes the
> ground on which §1 admits **every** record of the three populations to a supply. Such an
> ADR states in its own text what becomes of this decision, and no lane reads either
> clause as surviving the change that made `USER_CHOSEN` reachable without a user.

**The one caveat that is not about degree, restated because its weight has grown.** After
ADR-0245 a deployment whose trust fact could be reached without a user act would have
disclosed records the *derivation* narrowed. After this ADR it would disclose records the
**owner** narrowed by their own act. The single recorded act of the user is now the whole
of what stands between a guarded note and a query, which is precisely why §5 is restated
and not merely cited.

### 6. The composer is unchanged

> **Normative.** **No filter, rule or test of content is added at the composer, and
> ADR-0245 §6 binds entire.** `planning/composer.py`'s `_SYSTEM_PROMPT` carries the
> guidance ADR-0245 §6 quotes — "Use them only for that. Do not search for a note, do not
> repeat one back, and do not carry a detail from one into the query unless the request is
> asking about it" — and the implementing lane **leaves it untouched**. Changing it is
> deferred by name in §12, because the guidance is what the owner's decision rests on and
> a lane rewording it under review pressure would be changing the decision. ADR-0231 §11's
> clause that the only value `WebSearcher.request` is passed is the composer's own `query`,
> byte for byte, binds entire, and **no arm of §11 asserts over the prompt's words or over
> a query's content.**

**The caveat is the same one and it has grown, and the answer is still deliberate.** The
composer may carry a specific the search did not need, and after this ADR that specific
may come from a guarded note. The alternatives are unchanged and are still refused: a
content filter, which ADR-0238 §3's second clause forbids and ADR-0098 §6 refuses as a
gate, or a second model pass judging the first's output, which buys a judgement nobody can
check and costs a call. What changed is not the answer but the honesty owed about it, and
§1's accounting and §9 are where that is written down.

### 7. The audit

> **Normative.** ADR-0238 §11's first clause binds entire: **no second audit, no second
> event key and no new emission point**. One `INFO`-level structured log event per turn,
> under the one fixed key, carrying the ambient correlation identifier and no other
> identifier. Its **counts only** rule binds entire — no record id, no conversation id, no
> destination, no query text, no fragment or length of one, no title, no snippet and no
> provider message — as does its clause that the destination's recorded trust is not
> written to this event.

> **Normative.** **The record keeps exactly four counts and this ADR adds none and
> removes none.** ADR-0238 §11's enumeration as ADR-0245 §7 left it — supplied, withheld,
> this turn's `calls`, and the supplied-narrowed count — is what the event carries. **No
> lane deletes the `withheld` field** because §1 makes it constant, and **no lane adds a
> fifth count or a per-setter breakdown** of the supplied-narrowed one; either would be a
> change to ADR-0238 §11's enumeration, which this ADR does not take. §12 defers the
> breakdown by name.

> **Normative.** **`withheld` keeps ADR-0238 §11's definition and is zero on every
> path.** The definition — "the count of records withheld from the supply by §3's filter"
> — stays true of the filter as §1 now leaves it: on a `USER_CHOSEN` destination the
> filter withholds nothing, and on an `UNCHOSEN` one the whole population is withheld by
> §2's **trust clause** and not by the filter, which is the zero the tree already writes.
> **This supersedes ADR-0245 §7's second clause in the sentence naming what the count
> measures on a chosen destination** — "it counts the records refused for carrying an
> `OWNER_ACT` or `PROPOSED` narrowing" — which ceases to be true. That sentence's
> companion, that the number **falls** the day a decision lands, holds again and for the
> last time: it falls to zero.

> **Normative.** **The supplied-narrowed count keeps its definition and widens what it
> measures**, and ADR-0245 §7's third clause binds entire. It is "the number of records
> supplied to the composer whose `placement.reach` is not `PlacementReach.ANYONE`" —
> **now over every setter**, an `OWNER_ACT` and a `PROPOSED` narrowing included. It is the
> one number that measures the class this decision lets through, it rises on the same
> deployment the day this lands, and **no lane reads that rise as a defect.**

**The instrument is owed for the reason ADR-0238 §11 gave and ADR-0245 §7 repeated.** "A
deployment that has given up a structural property owes itself a number." This decision
gives up the last record-level exclusion, and the number that moves is the one ADR-0245
added: `withheld` goes to zero and stays there, so a deployment that watched only it would
see the system withholding nothing and conclude nothing was flowing. The supplied-narrowed
count is where the truth is, and that is why §7 forbids its deletion in the same breath as
it forbids a fifth.

### 8. The negative arm, restated over what it protects

> **Normative.** **An injected result cannot raise the budget and cannot change the
> destination.** That is milestone 31's negative arm as the owner amended it on #1908 on
> 2026-09-11, and it is what this ADR asserts over: ADR-0238 §8's per-conversation call
> budget is spent by `admit_search` before a supply exists and no result, model output or
> provider message raises it; and ADR-0238 §1's trust fact is set by a recorded act of the
> user and by nothing else, so no result makes a destination trusted or moves a request to
> a destination the user did not choose.

> **Normative.** **This supersedes ADR-0245 §8's first and second clauses**, and ADR-0238
> §12's second clause in the remainder ADR-0245 §8 restated. "An injected result cannot
> carry an **excluded** record into a query" and "an injected result cannot **widen the
> admitted set**" both cease to describe a property this corpus holds on a chosen
> destination: **there is no excluded record and no admitted set to widen.** The arms are
> not weakened into a softer form — they are replaced by the two above, which are the ones
> the owner's exit sentence now states and which rest on recorded facts rather than on a
> filter.

> **Normative.** **What still bounds what an injected result can reach is membership, not
> placement.** ADR-0238 §2's three populations are recorded by the loop from the supply it
> assembled, so a result's content cannot add a record to them; and the lineage floor
> (ADR-0181 §5) and ADR-0238 §5's four closed-loop conditions decide, at the moment the
> request is built, whether the turn may send at all. **A result that steers *which* of
> the turn's own records the composer emphasises is not bounded by this corpus and is not
> claimed to be** — that is ADR-0098 §5's corridor, and §9 states it rather than closing
> it.

> **Normative.** ADR-0245 §8's third clause binds entire, so ADR-0238 §12's other four
> clauses bind entire and this ADR restates none of them into a weaker form: an injected
> result cannot raise the budget, cannot make a destination trusted, cannot widen the
> closed-loop population, and cannot make a binding claim a closed loop; and credentials
> stay out structurally with ADR-0231 §12's one residue unchanged.

### 9. What ADR-0245 §9 stated as a residue is now a decided admission

> **Normative.** **ADR-0217 §3's two readings no longer differ in outcome on this
> path**, and **this supersedes ADR-0245 §9's first clause in the limb that states their
> differing outcomes** — "where the second governs, the derived record is excluded by §2,
> and where the first governs, a sentence descending from a guarded record may reach a
> supply and a query". Under §1 a record derived over a supply that held a guarded record
> reaches a supply whether its setter is recorded `OWNER_ACT` or `DERIVED`, and so does
> the guarded record itself. **This ADR resolves neither reading and narrows neither**; it
> records that the supply no longer distinguishes them.

> **Normative.** **#2227 is moot on this path and live on its own**, and this ADR closes
> nothing about it. The setter still decides the owner's recourse under ADR-0217 §3's
> closing clause — "An act on a placement whose setter is `DERIVED` **narrows only**: a
> widening act on such a record is refused" — so which reading governs still decides
> whether the owner can ever `unguard` a record derived from a guarded one. That question
> belongs to the ADR that owns ADR-0217's reading and **no lane resolves it from this
> document**; the issue stays open against that owner and is not closed by this ADR.

> **Normative.** **What ADR-0245 §9 disclaimed as undetected is now stated as decided,
> and that is a widening of the disclosure and not of the corridor.** A sentence
> descending from a guarded record, and the guarded record itself, may be composed over
> for a chosen destination. It is not detected, is not subtracted, and no detector closes
> it (ADR-0098 §5, §6). **No lane states, implies or relies on this decision detecting
> anything about what a record descends from**, and ADR-0245 §9's second and third clauses
> bind entire — including that what would close the corridor is a recorded per-record
> provenance fact, which §12 keeps deferred.

**The residue's shape has changed and shrunk in one respect.** ADR-0245 §9's worry was
that an owner's guard could be laundered through a derivation and reach a query without
anyone deciding it should. After this ADR nothing is laundered, because nothing is hidden:
a guarded record reaches a chosen destination's query **by a ruling**, openly, counted by
§7's supplied-narrowed number. What remains genuinely open is ADR-0098 §5's corridor
itself — that the model's wording is not bounded by any recorded fact — and that is
untouched, unnarrowed and unclosed by every clause here.

### 10. What the implementing lane owes

> **Normative.** **One PR, in `core/` and `orchestration/`.** The change is the deletion
> of `_placed_for_a_search_supply` and `_admitted_to_a_supply` from `core/types.py` and of
> the `AfterValidator` annotation on `SearchSupply.records`; the field's description; the
> deletion of `orchestration/reads.py`'s copy of the predicate and the withheld-count
> arithmetic that used it; and the arms of §11. **No Protocol changes**, so this is not a
> triad and adds no conformance suite; `testing/queries.py`'s canonical composer fake is
> changed only if an arm below needs it.

> **Normative.** **The lane corrects, in the same change, every docstring that cites the
> deleted validator**, including `core/protocols.py`'s `QueryComposer.compose` and
> `planning/composer.py`'s module docstring, whose "``SearchSupply`` refuses any other
> reach at construction" is already false at `origin/main` `35a39aa6`. **That correction
> is docstring text only** — no behaviour, no test, no rule — and it rides here rather
> than becoming a second change because a module describing a check the tree does not have
> is a false statement this decision creates.

> **Normative.** **No re-drive is owed.** The mechanism was driven under ADR-0245 §10 on
> a scratch hub over `tests/tools/answering_origin_harness.py`, and what this decision
> changes is *which records are admitted* rather than how a supply reaches a composer, a
> ruling or a provider. That is asserted by §11's arms over the production type, the
> production builder and the production servicing path. A lane that nevertheless finds the
> composer declining on an admitted record reports it rather than adjusting an arm.

> **Normative.** **The lane changes no word of ADR-0217, ADR-0199, ADR-0204, ADR-0004,
> ADR-0098 or ADR-0231**, and no clause of ADR-0238 or ADR-0245 outside the scopes this
> ADR's header names. It leaves `planning/composer.py`'s `_SYSTEM_PROMPT` untouched (§6).
> It moves `PROTOCOL_VERSION` only if it finds §4's finding false, in which case it moves
> it in the same change and says so.

> **Normative.** **The lane files nothing and defers nothing this ADR has not named.**
> Findings outside this change are issues under `CONTRIBUTING.md`'s triage rule, not
> growth of the PR.

### 11. The representative-input tests this decision owes

> **Normative.** Each arm below is a test the implementing lane owes, over the production
> type, the production builder and the production servicing path, and not over a double
> standing in for one of them. **ADR-0245 §11 Arms A, C and E bind entire and are
> unchanged**, and ADR-0238 §15's other arms bind entire.

> **Normative.** **Arm D — the owner's act reaches a supply by every route, and this
> replaces ADR-0245 §11 Arm D entire.** On a `USER_CHOSEN` destination, a record placed
> reach `OWNER` setter `OWNER_ACT` is **admitted** when the turn's retrieval selected it,
> when the episodic supplement selected it, and when it arrived as this turn's own minted
> `WEB_SEARCH` record; the supply's `records` contains it in each case, the composer is
> handed it, and **the supply is constructed rather than refused** — asserted on the type
> directly, by constructing a `SearchSupply` carrying such a record, so that a lane which
> left the validator in place fails the arm loudly.

> **Normative.** **Arm D′ — a model's proposal reaches a supply on the same terms.** A
> record placed reach `OWNER` setter `PROPOSED` — the placement `learning/observer.py`'s
> observation pass writes — is admitted on a `USER_CHOSEN` destination by the same three
> routes, is carried in `records`, and reaches §7's supplied-narrowed count. The arm
> exists because ground 1 of the ruling is about a *preference* dropping out of a
> follow-up query, and this is the placement such a preference carries.

> **Normative.** **Arm B′ — ADR-0245 §11 Arm B in its narrowed form, and this replaces
> its exclusion limb.** Arm B's `DERIVED` limb stands: a record placed reach `OWNER`
> setter `DERIVED`, in a selection a search result influenced and in one it did not, is
> admitted and reaches the supplied-narrowed count. Its `OWNER_ACT` and `PROPOSED` limb is
> **inverted**: neither is refused by `SearchSupply` at construction, in either selection,
> and neither reaches the withheld count.

> **Normative.** **Arm F′ — the audit's four counts, and this replaces ADR-0245 §11 Arm F
> in its premise.** Arm F is written over a turn "carrying an admitted `DERIVED` narrowing
> and a **refused** `OWNER_ACT` one", which §1 makes unreachable — so the arm is restated
> over a turn carrying an admitted `DERIVED` narrowing **and** an admitted `OWNER_ACT` one:
> the event records the supplied count, the withheld count at **zero**, this turn's `calls`
> and the supplied-narrowed count at **two**, each at its true value, and carries **the
> ambient correlation identifier and no other identifier** — ADR-0238 §11's own rule,
> restated here so the arm cannot be satisfied by dropping a field §7 keeps.

> **Normative.** **Arm G — the `UNCHOSEN` destination is unmoved.** With every other fact
> identical to Arm D's and the destination's trust record absent, the supply carries the
> utterance and an empty `records`, its withheld count is zero, and the guarded record is
> not composed over. The arm asserts that the emptiness is ADR-0238 §2's **trust clause**
> and not a placement filter, so a lane that deleted the trust branch along with the
> validator fails it.

> **Normative.** **Arm H — reach still binds where a person listens.** With the same
> guarded record in view, the turn's **reply** on a channel whose audience is wider than
> the owner does not carry it, exactly as it does not today. The arm exists because §1's
> subtraction is the one thing a reader of this ADR might believe it removed, and it is
> asserted over `orchestration/disclosure.py`'s production path rather than over a
> restatement of it.

### 12. Deferred, by name, each with what fires it

- **A tier for a record that never leaves the machine** (ground 3, §1). Not a reach, not
  a setter and not a band on `Placement`: a **new tier with its own act**, its own
  surface and its own ADR, in ADR-0004 §1's axis rather than ADR-0217 §1's. Fired by an
  owner asking for a record that never leaves the machine — the request ADR-0217 §7's
  `guard` does not serve and, on ADR-0217 §3's definition, never did. **Not fired** by a
  lane reading a guard as one, and **not** discharged by any clause of this ADR.
- **Changing the composer's guidance line** (§6). `planning/composer.py`'s
  `_SYSTEM_PROMPT` stands as ADR-0245 §6 left it. Fired by evidence that the guidance is
  not doing its work — a driven turn whose query carries a specific the request did not
  ask about — and by nothing else; **not fired** by a review finding that the line could
  be worded better, and never by a content filter, which §2 forbids.
- **A per-setter breakdown of the supplied-narrowed count** (§7). Fired by an owner or
  operator asking to see how often a record narrowed by their own act composes a query.
  **Not fired** by a lane finding the number interesting: it is a fifth figure in
  ADR-0238 §11's enumeration and takes the ADR that adds it.
- **A recorded fact distinguishing a computed narrowing from one descending from an
  owner's act** (§9, ADR-0245 §12's first deferral, which binds entire). Fired by the ADR
  that decides ADR-0098 §5's deferred provenance surface, or by an ADR resolving ADR-0217
  §3's two readings — which #2227 records and which §9 finds live on ADR-0217's own
  ground. **Not fired** by a lane wanting to infer the distinction from content.
- **Anything about an `UNCHOSEN` destination.** ADR-0238 §16's deferral stands untouched
  and ADR-0245 §12's third deferral binds entire; this ADR adds nothing to either.
- **A reach denotation beyond `ANYONE` and `OWNER`** (ADR-0217 §1). **This supersedes
  ADR-0245 §12's fourth deferral in its exclusion half** — "§2's admitted set names two
  combinations and no more, so a third denotation is excluded until then" — which §1
  makes false: a later denotation binds no more at a supply than `OWNER` does, because
  reach does not bind there at all. The deferral itself stands, with its answer stated:
  the ADR that adds a denotation says what a supply does with it **if it wants something
  other than §1's rule**, and a lane adds none in the meantime.

### 13. Scope, and what this records against earlier ADRs

**Superseded on ADR-0245, and nothing else.** §1's third clause in the two-facts rule it
states (§1); §2's third, fourth and fifth clauses (§1); §3's first clause and its second
clause in the limb presupposing a validator (§3); §7's second clause in the sentence
naming what `withheld` counts on a chosen destination (§7); §8's first and second clauses
(§8); §9's first clause in its differing-outcome limb (§9); §11 Arm B's exclusion limb,
Arm D entire and Arm F's premise (§11); and §12's fourth deferral in its exclusion half
(§12). **Discharged rather than superseded:** §12's second deferral, by the ruling it
named as its trigger (§1); and §10, whose obligations fell on the lane that has landed.

**Superseded on ADR-0238, and nothing else beyond what ADR-0241, ADR-0242 and ADR-0245
already recorded there.** §2's validator clause in the limb ADR-0245 §3 restated verbatim
(§3); §3's first clause in the limbs ADR-0245 left standing — that the record-level fact
keeping information out of a query is `Placement.reach`, and that "§2's validator is where
that is enforced" (§1, §3); and §12's second clause in the remainder ADR-0245 §8 restated
(§8). **No further record is owed on ADR-0238 §11**: its enumeration keeps the four counts
ADR-0245 left it, and its definition of `withheld` is a reference to §3's filter rather
than a restatement of §3's predicate, so it stays true of the filter as §1 leaves it.
**None on §15 Arm 4**, which ADR-0245 §11 Arm B already replaced.

**Relied on as written, by name.** ADR-0238 §1 entire (§5 quotes it); §2's remaining
clauses — the three populations, the single construction site, the trust clause and the
cross-turn promise; §3's second, third and fourth clauses; §4's accounting; §5's four
closed-loop conditions and its window; §6's reach; §8's budget; §11's one-event, one-key
and counts-only rules; §12's other four clauses; §13's `core` surface; §15's other arms;
§16's deferrals. ADR-0245 §1's first, second, fourth, fifth and sixth clauses; §2's first,
second and sixth clauses; §3's third and fourth clauses; §4; §5; §6; §7's first and third
clauses; §8's third clause; §9's second and third clauses; §11 Arms A, C and E; §12's
first and third deferrals; §13, §14 and §15.

**No record is owed on ADR-0217, ADR-0199, ADR-0204, ADR-0004, ADR-0098, ADR-0193,
ADR-0181, ADR-0231, ADR-0226, ADR-0013 or ADR-0124**, on ADR-0082 §1's test: every
sentence each of them wrote stays true and none is read more widely. ADR-0217 §1's reach
keeps its denotation and its vocabulary clause, and §3's setters, precedence and closing
clause are read exactly as written — §9 declines their one ambiguity rather than resolving
it, and §1 stops a *consumer* reading the field rather than changing what the field means.
ADR-0199 §3's floor and classes are untouched. ADR-0204 §2's evaluation and §5's ratchet
are inputs and are not moved. ADR-0004 §1's tiers are read as the axis a local-only class
would belong to and nothing is added to them. ADR-0098 §5's corridor is quoted and
unnarrowed and §6's refusal of a detector is restated in §2. ADR-0193's grant and
ADR-0181 §5's floor stand at the ruling point. ADR-0231 §3's composer signature and §11's
byte-for-byte clause are untouched. ADR-0226 §5 is read and a consequence drawn from it,
with no obligation added. ADR-0013 §2's per-request fallback and §6's configured-set bound
are relied on through ADR-0245 §1's sixth clause, unchanged. ADR-0124 §9's rule is applied
and reaches its "no bump" answer, and a rule applied is not a rule amended.

**Where the records go.** ADR-0245's `Status` line reads `Accepted`, so it takes the
leading `Partially superseded by ADR-0246 (<scope>)` token and `Accepted` is dropped, as
`docs/adr/template.md` requires, with the whole record in an appended dated note (ADR-0070
§1). ADR-0238's `Status` line already leads with `Partially superseded by`, so under
ADR-0082 §2 no amendment qualifier is written on it, this ADR's three scopes are added to
it as one further `ADR-0246 (<scope>)` pair, and the record lives in a second appended
dated note. **No ratified text of either ADR is rewritten.**

### 14. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Each edit, with §1's test applied: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

- **ADR-0245 §2's third, fourth and fifth clauses** — **yes**, and this is the decision.
  A reader holding only §2 refuses an `OWNER_ACT` or `PROPOSED` narrowing at construction
  and builds a type admitting exactly two combinations. **Supersession.** §2's first,
  second and sixth clauses — the Tier 0 floor, the `UNCHOSEN` case and the absent
  `about_person` filter — are restated in §2 above and lose nothing.
- **ADR-0245 §1's third clause** — **yes**. It names `Placement.reach` **and**
  `Placement.set_by` as the record-level facts that keep information out of a query; after
  §1 neither does, on a chosen destination. **Supersession**, in that rule alone. §1's
  other clauses stay true: the axis is still audience control, the `DERIVED` record is
  still admitted, the trust read is still the condition, and the party set is still
  ADR-0013 §6's.
- **ADR-0245 §3's first clause, and §3's second in one limb** — **yes**. A reader holding
  only §3 keeps an `AfterValidator` refusing a population, and §3's second clause says
  what that validator reads. **Supersession** of the first and of the second's
  presupposition; the second's surviving half — `core` stays blind to trust and gains no
  member — is restated in §3 and §4 and is honoured rather than replaced. §3's third
  clause (the trust condition stays at the builder) and fourth (ADR-0238 §3's second,
  third and fourth clauses bind verbatim) are untouched and restated.
- **ADR-0245 §7's second clause** — **yes**, in one sentence. A reader holding only §7
  expects `withheld` to count refused `OWNER_ACT` and `PROPOSED` records on a chosen
  destination and would write a test asserting it non-zero. **Supersession**, in that
  sentence alone; the clause's definition-by-reference to §3's filter and its
  `UNCHOSEN`-is-zero limb stay true.
- **ADR-0245 §7's first and third clauses** — **no**. The one-event rule is untouched, and
  the supplied-narrowed count's sentence — "records supplied to the composer whose
  `placement.reach` is not `PlacementReach.ANYONE`" — stays true word for word while the
  population it counts widens. A reader holding only §7 emits the same field with the same
  meaning. §7 above states what it now measures, which is disclosure and not an amendment.
- **ADR-0245 §8's first and second clauses** — **yes**. Both are stated over an excluded
  record and an admitted set, and after §1 neither exists on a chosen destination; a reader
  holding only §8 would write an arm asserting a refusal that cannot happen.
  **Supersession**, replaced by §8's two arms over the budget and the destination. §8's
  third clause is untouched.
- **ADR-0245 §9's first clause** — **yes**, in its differing-outcome limb. It says the two
  readings of ADR-0217 §3 differ in whether the derived record reaches a supply; after §1
  they do not. **Supersession** in that limb; its "resolves neither reading and narrows
  neither" limb is restated and honoured. §9's second and third clauses — the corridor and
  what would close it — are untouched.
- **ADR-0245 §11 Arms B, D and F** — **yes**, in the scopes named. Arm D asserts a refusal
  on three routes and is **replaced entire** by §11 Arm D's inverse; Arm B's exclusion limb
  asserts two refusals and is inverted by Arm B′ while its `DERIVED` limb stands; Arm F's
  premise names "a refused `OWNER_ACT` one", a turn §1 makes unconstructible, so the arm as
  written asserts nothing and Arm F′ restates it. **Supersession** in each case. **Arms A,
  C and E** — **no**: Arm A's non-empty supply, non-declining composer, `ALLOW` on route
  (b) and zero withheld count all still hold; Arm C's admitted `about_person` record and
  empty second supply still hold; Arm E's revocation still flips the supply to
  utterance-only.
- **ADR-0245 §12's second deferral** — **discharged, not superseded.** It names the trigger
  — an owner ruling addressing the explicit act — and that ruling has happened. A reader
  holding only §12 is not misled about a rule; they are holding a deferral whose condition
  has since been met, which is a fact that postdates it (ADR-0070 §1). The record is the
  dated note, and the precedent is ADR-0242's own record on ADR-0238 — "§14's surface
  assignment is **discharged rather than superseded**" — carried on that ADR's `Status`
  line.
- **ADR-0245 §12's fourth deferral** — **yes**, in its exclusion half. "A third denotation
  is excluded until then" becomes false, a supply refusing nothing on reach. **Supersession**
  in that half; the deferral stands and §12 restates what the adding ADR owes.
- **ADR-0245 §10** — **no**. It binds the lane implementing *that* ADR, which has landed;
  §10 above binds a different lane and takes nothing from it. ADR-0245 §14 classified
  ADR-0238 §14 the same way, for the same reason.
- **ADR-0245 §4, §5, §6, §13, §14, §15** — **no**. §4's `core`-surface and version findings
  are re-applied at this tree and reach the same answers; §5 is restated with its weight
  named; §6 is relied on entire and §6 above adds a deferral rather than a change; §13 and
  §14 classify ADR-0245's own edits and are unmarked (ADR-0089 §3), so they impose nothing
  to supersede; §15's marking, both-lens and ratification rules are followed by this ADR
  too.
- **ADR-0238 §2's validator clause** — **yes**, in the limb ADR-0245 §3 restated verbatim.
  "The refusal is on the type, so no producer, decode, test double or later lane can
  construct a supply carrying an excluded record" ceases to be a property of this corpus.
  **Supersession** in that limb; §2's trust clause, its three populations, its single
  construction site and its cross-turn promise are untouched.
- **ADR-0238 §3's first clause** — **yes**, further. ADR-0245 made its sentence
  non-exclusive; this ADR makes both halves false on a chosen destination — no
  record-level fact keeps information out of such a query, and "§2's validator is where
  that is enforced" names a validator that no longer exists. **Supersession** in those
  limbs. Its "with no field, member, axis, tag or band added" limb is restated and honoured
  a second time.
- **ADR-0238 §3's second, third and fourth clauses** — **no**. Nothing here inspects
  content, the one-bit residue is extended in *shape* and closed in no part (§9), and the
  `__dict__` bypass and absent detachment obligation are untouched — the bypass simply has
  one fewer check to bypass, which changes no sentence §3 wrote.
- **ADR-0238 §12's second clause** — **yes**, in the remainder ADR-0245 §8 restated. Its
  property is stated over an excluded record and has no subject on a chosen destination.
  **Supersession**; §8 above states what the arm protects instead, over the budget and the
  destination, which is the form the owner's own exit sentence now takes.
- **ADR-0238 §11's enumeration and its `withheld` definition** — **no**, on both. The
  enumeration keeps four counts and this ADR adds and removes none; the definition is a
  reference to §3's filter, and §3's filter moving does not move the sentence.
- **ADR-0238 §13, §14, §15's other arms, §16** — **no**. §13's enumeration is of the
  surface *that* decision added and §4 changes no member's type, default or meaning; §14
  binds a lane that has landed; §15's other arms are untouched, Arm 1b keeping the producer
  ADR-0245 gave it; §16's deferrals are untouched.
- **ADR-0217 §1, §2, §3, §4, §7** — **no**, on all five. The reach keeps its denotation,
  the vocabulary clause is quoted and honoured, the three setters and their precedence are
  read as written, §4's proposal is read as the judgement about people that it is, and §7's
  acts keep every effect ADR-0217 gives them. What §1 above changes is which *consumers*
  read the field, not what the field records or what any act writes into it.
- **ADR-0199 §3, ADR-0203 §1, ADR-0204 §2 and §5** — **no**. The floor, the classes and
  the subtraction at the reply are untouched and §1's fourth clause says so in terms; the
  derivation and the ratchet are inputs and are not moved.
- **ADR-0004 §1, §2, §5** — **no**. The tiers are read as the axis on which a local-only
  class would sit, and nothing is added to, removed from or reinterpreted in them; §12
  defers the class rather than creating it.
- **ADR-0098 §5 and §6, ADR-0146 §2** — **no**. §9 quotes the corridor, widens its
  disclosure and disclaims every assurance about it; §2 restates §6's refusal of a detector
  and ADR-0146 §2's recorded-never-inferred rule rather than qualifying either.
- **ADR-0193, ADR-0181 §5, ADR-0231 §3, §11, §12, §19, ADR-0226 §5, ADR-0013 §2 and §6,
  ADR-0124 §9, ADR-0089** — **no**, on all. Each is left standing at the point it already
  governs; ADR-0231 §19's deferred unforgeable value is untouched, and ADR-0089's marking
  rules are followed rather than changed.

### 15. Marking, review and ratification

This ADR is **marked** under ADR-0089: every obligation it imposes is a
`> **Normative.**` block quote, and unmarked text beside a mark is read to determine what
the mark means and supplies no obligation of its own. The fenced block in §5 is a
**quotation** of ADR-0238 §1 and makes no mark (ADR-0089 §2).

It is a **contract-surface** decision — it changes what `core/types.py`'s `SearchSupply`
admits, and removes a validator from it — so it owes both the adversarial and the
architecture lens (ADR-0015 §1), is reviewed while `Proposed`, and is ratified by
`just adr-ratify` in the one-line flip ADR-0165 exempts. Under golden rule 5 it merges as
its own PR before the implementing lane §10 describes is briefed, and that lane's
authority is the merged text.

## Consequences

**What becomes easier.** The milestone's own sentence works: "find more about that,
**taking my preferences into account**" resolves over the preferences the observation pass
flagged and the notes the owner guarded, instead of composing over whatever survived a
filter the owner did not intend to apply here. The corpus loses a rule rather than gaining
one — one validator, one predicate, one copy of that predicate and one class of refusal
disappear — and `Placement` goes back to meaning exactly what ADR-0217 §1 said it means,
with no consumer reading it for a question it was not written to answer.

**What becomes harder.** There is now **no per-record instrument** by which a user keeps
something out of a search query bound to a chosen destination. A query may carry wording
shaped by a note the owner guarded by their own act, and nothing detects that, subtracts
it or counts it beyond §7's one number. `withheld` becomes a permanently zero field that a
reader must not mistake for evidence of withholding. And the weight ADR-0245 put on
ADR-0238 §1's single recorded user act is now the whole of what stands between a guarded
record and a provider — a dependency §5 restates for exactly that reason.

**What would trigger revisiting this.** Any loosening of ADR-0238 §1's
set-by-a-user-act clause (§5, which reopens this decision outright). An owner asking for a
record that never leaves the machine (§12's first deferral, which is the instrument this
decision's cost calls for). Evidence that the composer's guidance line is not doing its
work (§12). A resolution of ADR-0217 §3's two readings, which changes the owner's recourse
even though it no longer changes what a supply admits (§9, #2227). And an arm of §11
coming back the other way — a supply still refusing a guarded record, or a reply now
carrying one — either of which would mean the change was implemented wrongly rather than
decided wrongly.

## Alternatives considered

**Keep the validator with a predicate that admits everything.** Rejected in §3. A check
that cannot fail enforces nothing and asserts something: a later reader takes an
`AfterValidator` on `records` as evidence that some population is refused. If the rule is
gone the check goes with it.

**Keep excluding `OWNER_ACT` and admit only `PROPOSED`.** Rejected. It would split the
owner's ruling in half on the reasoning ADR-0245 §2 gave for excluding both, which the
owner has now addressed directly on ground 2 — the guard sets reach and nothing else. It
would also leave the milestone's exit sentence resting on a distinction the owner does not
draw.

**Pass the destination's trust into `SearchSupply` so the type still has something to
refuse.** Rejected, as ADR-0245 rejected it: it would put a destination fact in `core`'s
validator for a question ADR-0238 §2 already answers at the one construction site, and
would give `core` a reason to know about trust for no gain. After §1 it would also be a
validator with nothing to do even with the fact in hand.

**Read "guarded" as "local only" and keep such records out.** Rejected on ground 3. That
is an egress class, not an audience one; `Placement` has no member for it and ADR-0004
§1's tier axis has no member a user puts on a record. Reading one axis as the other is the
category error ADR-0238 §3 made, and repeating it would cost the same repair a second
time. The class is deferred with its own act and its own ADR (§12).

**Add a per-setter breakdown to the audit so a deployment can see guarded records
composing.** Rejected here and deferred in §12. It is a fifth figure in ADR-0238 §11's
enumeration, and the number this decision owes itself — the supplied-narrowed count — is
already in the event and already rises. An owner who wants the breakdown fires the
deferral.

**Leave ADR-0245 §2 standing and let the implementing lane read the ruling into it.**
Rejected outright. ADR-0245 §2's closing paragraph names the instrument for widening the
reading — "one sentence of this section and an owner who was asked" — and a lane is not
that instrument. This document is.
