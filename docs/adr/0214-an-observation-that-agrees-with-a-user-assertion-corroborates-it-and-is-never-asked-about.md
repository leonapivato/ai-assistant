# 214. An observation that agrees with a user assertion corroborates it, and is never asked about

- Status: Accepted
- Date: 2026-08-29
- **Not a contract change under golden rule 5.** No Protocol in
  `core/protocols.py` gains a member or changes a signature, no type or enum
  member is added to `core/types.py`, and no `MemoryDecisionKind`,
  `ConflictRelation` or metric key is added. It is nevertheless a change to a
  ratified `MemoryWriter` **conformance obligation** — ADR-0040 §5b's fold
  refusal, which "*is* the contract" in that ADR's own words — so it ships as
  its own `Proposed` PR and carries **both** review lenses, per
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation". This is
  ADR-0121's header form, taken deliberately: this ADR widens the very clause
  ADR-0121 narrowed, so it owes the same treatment.
- **This ADR amends** [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)
  §2a and §3, [ADR-0040](0040-reinforcement-and-supersession-are-different-rulings.md)
  §5b, [ADR-0045](0045-memory-records-carry-a-validity-window.md) §5 (clause 1)
  and [ADR-0121](0121-an-agreeing-restatement-is-ruled-agreement-not-conflict.md)
  §5. §7 applies ADR-0070 §1's test clause by clause, including the places a
  record looks owed and is not.
- **This ADR partially supersedes**
  [ADR-0159](0159-a-conflict-is-labelled-before-it-is-ruled-on-and-similarity-alone-folds-nothing.md)
  §4 — its **fourth** normative clause, "The `ASK_USER` ruling for a non-asserted
  proposal whose conflict set holds a `USER_ASSERTED` member is unchanged and
  continues to precede this arm", in the scope named in §7 and no wider. §4's
  three ruling arms, its purity conditions, its target classes, its
  reads-no-score clause and its non-empty-set clause are all untouched, as is
  every other section of ADR-0159. The clause fixes a ruling's precedence and
  offers no justification an agreeing observation could escape, so ADR-0070 §1
  makes it a supersession rather than an amendment — §7 argues that line against
  the clauses this ADR does merely amend.
- **Follow-up to** ADR-0121 §11, whose second deferral it discharges, and to
  ADR-0103 §6, whose corroboration rule it applies to a third pairing. Refs
  #869, #862, #863, #1782.
- **Durability clause.** Every quotation below — from an ADR, from `memory/`,
  from `ai_assistant.testing`, or from an issue — is of its text as it stood at
  this ADR's base, `d64065a2`, and not of its text on any later day. Where a
  later ADR changes one of the ADRs cited, this ADR is read against the text
  quoted here and that ADR's own record says what moved. This is ADR-0143's
  clause, taken for its reason.

## Context

### The mirror ADR-0121 named and left open

ADR-0121 closed the case of a **user** restating themselves. Its §11 filed the
mirror in terms, and this ADR is the lane that clause named:

> **A non-asserted proposal that agrees with a user assertion.** An observation
> restating what the user told us still rules `ASK_USER` under rule 5. The
> ordinary fold arm would take the incoming record's source and *demote* the
> assertion to an observation, so fixing it means extending ADR-0103 §6's
> corroboration rule again, on a path ADR-0120 §6 excludes from its measure
> anyway. Out of scope and filed.

The defect is `DefaultMemoryPolicy._rule_on_conflicts`'s rule 5, which is
unconditional over the conflict set:

```python
if not is_asserted and asserted_conflict:
    return MemoryDecision(
        kind=MemoryDecisionKind.ASK_USER,
        reason="conflicts with a user-asserted memory",
    )
```

`asserted_conflict` is `any(c.provenance.source is MemorySource.USER_ASSERTED
for c in conflicts)`, and `conflicts` is
`MemoryIngestor._detect_conflicts`'s output — a same-kind ranked retrieval
filtered at `conflict_threshold`, default `0.75`. That is a **topical
similarity** signal, which ADR-0121 §1 already ruled is neither a contradiction
signal nor an agreement one. An observation whose content is, after ADR-0121
§1's four transformations, byte-for-byte what the user already told us scores at
the top of that ranking. So the system takes a belief it just re-derived from
watching the user, notices it matches what the user said, and asks the user
whether they are contradicting themselves.

ADR-0121 §2's agreement arm cannot reach it. `_rule_on_agreement`'s own `Args`
say so: the `record` is one "whose source the caller has already established is
`USER_ASSERTED`", and `_rule_on_assertion` — the only caller — is reached only
behind `if is_asserted`. The arm is correct and it is on the wrong side of the
branch for this population.

### Why the ordinary fold cannot be the fix

`REINFORCE`'s ordinary arm in `MemoryIngestor._merge` writes the incoming record
at the target's id, taking the incoming record's `source`. Folding an `OBSERVED`
proposal onto a `USER_ASSERTED` target on that arm would move the record out of
the `ASSERTED` band — the harm ADR-0038 §2a names as the second half of its
clause-1 reason, and the half ADR-0121 never had to answer because its incoming
record was itself `USER_ASSERTED`:

> - **any** fold onto a `USER_ASSERTED` target, whatever the proposal's source
>   (§3, §5) — the write replaces what the user told us, and from a
>   non-asserted proposal it also downgrades the record's provenance out of the
>   profile;

So the writer floor refuses it, correctly, and `_agreeing_restatement`'s second
condition says why in as many words: "A non-asserted proposal agreeing with an
assertion is a *different* case, ADR-0121 §11 leaves it ruling `ASK_USER`, and
admitting it here would let `_merge`'s ordinary arm demote the assertion to an
observation."

That sentence is the whole of the problem, and it names its own solution: the
demotion is a property of the *arm*, not of the fold. `_merge` already has an
arm that demotes nothing — the corroboration arm ADR-0103 §6 ruled and ADR-0121
§4 applied a second time. Reaching it is what this ADR decides.

### Why now, and why the cost was invisible

Today the observation stage never runs on the deployed hub on its own: a fact
told in chat becomes a belief only when `assistant observe` is run by hand
(#1695, #1737). So the population this defect lives in is nearly empty and
nothing has surfaced it. Batch #1782 is turning the observer on — an observation
cursor, then observe-on-quiet — and the moment it runs, the commonest
observation there is (the one restating what the owner already said, from the
very conversation in which they said it) becomes a contradiction question in the
deferral queue. That is a user-visible harm arriving on a schedule, and the
decision has to be ratified and implemented before the trigger is armed.

### What has to be decided

Three things, and none follows from the ADRs above.

1. **Where the arm sits and how wide it reaches.** ADR-0159 §4 rewrote the whole
   non-asserted path since ADR-0121 was written — `ACCEPT` is now the default
   and each write is an exception, resting on an affirmative statement about a
   named record. An arm added carelessly here would fire ahead of ADR-0159 §4's
   two exceptions on a population they already rule, and would relitigate a
   decision three months newer than the defect.
2. **Whether the corroboration rule is extended, subsumed, or set beside.**
   ADR-0103 §6 keys its clause on both **bands** and argues for it in terms;
   ADR-0121 §4's second pairing is keyed on **sources** and argues for that in
   terms. A third pairing has to say which, and why the corpus has two answers.
3. **Whether clause 1 gains a third exception.** ADR-0121's Consequences left an
   explicit test for one: "Clause 1 has two exceptions now, and a third would be
   a pattern. […] Both are verified at the writer and both are keyed on facts
   that make clause 1's own justifications inapplicable, which is the test a
   third would have to meet. A clause with a list of exceptions nobody can state
   from memory is the failure mode to watch for."

## Decision

### 1. An agreeing observation is ruled `REINFORCE`, ahead of the prior-assertion deferral

The arm is a sibling of ADR-0121 §2's, on the other side of `is_asserted`, and
it is scoped to exactly the population the prior-assertion deferral owns.

> **Normative.** This section's arm is evaluated **only** where the proposed
> record's `provenance.source` is `OBSERVED` or `INFERRED` **and** at least one
> member of the conflict set has `provenance.source` `USER_ASSERTED`.

> **Normative.** For such a proposal, let the **agreeing set** be the members of
> the conflict set that agree with the proposal under ADR-0121 §1, and the
> **foldable agreeing set** be those members of it whose `provenance.source` is
> `USER_ASSERTED`, `OBSERVED` or `INFERRED`.

> **Normative.** `DefaultMemoryPolicy` rules `REINFORCE`, naming as `target_id`
> the best-ranked member of the foldable agreeing set, exactly when every
> `USER_ASSERTED` member of the conflict set is in the agreeing set. This arm is
> evaluated **before** the prior-assertion deferral.

> **Normative.** Where that condition does not hold, the proposal falls through
> to the prior-assertion deferral exactly as it stands, with no change to it.

> **Normative.** Where the conflict set holds no `USER_ASSERTED` member, this
> arm is not evaluated and no rule of ADR-0159 §4 is reached differently. The one
> clause of ADR-0159 this ADR reaches is §4's **fourth**, which fixes the
> precedence of the very deferral this arm precedes; it is partially superseded
> in this arm's scope (§7) and stands whole outside it.

**The scope clause is what confines this ADR to one clause of ADR-0159**, and it
is worth more than the generality it gives up. §4's fourth normative clause is
reached either way — it is the clause fixing this deferral's precedence, and
placing an arm ahead of the deferral is what this ADR does. What the scope clause
buys is that **nothing else** of ADR-0159 is reached. Stated over every
non-asserted proposal,
this arm would fire ahead of ADR-0159 §4(a) on sets holding no assertion at all
— a population §4 rules today with a purity condition this arm does not carry
("**no** member is labelled `CONTRADICTS`") and a target class this arm does not
use (`_RELATION_TARGETS`, which excludes `USER_ASSERTED`). It would be a partial
supersession of a decision made to fix a measured defect (#1188: the fold
premise false at the ratified threshold, 385 of 765 proposals folded), bought as
a side effect of fixing a different one. Scoping to the deferral's own
population means every rule ADR-0159 wrote still rules exactly what it ruled.

**The target is the best-ranked member of the foldable agreeing set, and which
record that is decides which fold arm runs.** The set is ADR-0159 §4(a)'s target
class plus `USER_ASSERTED`, so two outcomes are reachable and both are intended:

- Where an agreeing `OBSERVED` or `INFERRED` member outranks every agreeing
  assertion, the arm names **that** member and the fold takes `_merge`'s ordinary
  arm. The assertion is left exactly as it was — not refreshed, not touched — and
  the record named is the one ADR-0159 §4(a) would itself have named. That parity
  is worth checking rather than assuming: no reconciler runs on this population
  (ADR-0159 §2 excludes an ingest whose conflict set holds an assertion), so no
  member carries a label, `_effective_relations` computes `RESTATES` from
  `agrees` alone, §4(a) limb (i)'s purity condition is vacuously satisfied, and
  its scan selects the same record. The presence of an agreeing assertion no
  longer changes which record an observation folds onto; it stops the question
  being asked and does nothing else.
- Where the best-ranked agreeing member **is** the assertion, the arm names it
  and §4's corroboration arm runs. This is the member ADR-0159 §4(a) cannot name,
  because a fold onto it was refused until §3 above.

**Rank is the tie-break and not the ruling**, which is ADR-0121 §2's rule and
ADR-0159 §4's ("`conflicts[0]` is never the target by position"): the scan runs
over the members the agreement predicate and the target class already selected,
in the order the set arrived. Whether the arm should instead *prefer* an agreeing
assertion — refreshing the currency of the record that actually stands, rather
than of an observation ranked above it — is a real question, and §9 files it with
#871 rather than deciding it here.

**The one condition is what preserves ADR-0038 §3's asymmetry, and it is not
optional.** ADR-0121 §2's second condition is kept here word for word, and its
work is different and larger. There, without it, a user who said "window seats",
then "aisle seats", then "window seats" again would leave two live contradictory
assertions. Here the fold creates no new record at all (§4), so that failure is
not reachable — and a worse one is. Suppose the store holds two live
contradictory assertions already, reached by a route ADR-0121 §2 does not close:
a confirmed answer under ADR-0078 §5a retiring one of a larger set, or two
assertions each below `conflict_threshold` of the other and each above it of
this observation. An observation agreeing with one of them, folded without the
condition, refreshes **that one's** currency (§4, ADR-0103 §3) and leaves the
other to age. Currency drives what a later read surfaces, so the system would
have quietly adjudicated a contradiction between two things the user said, on
the strength of having watched them. That is ADR-0038 §3's "an inference may
**never** displace an assertion, silently or otherwise" reached by the softest
available route, and the condition is what forbids it.

**What the condition is not stated over.** A *disagreeing* `OBSERVED`,
`INFERRED` or `EXTERNAL` member blocks nothing, exactly as ADR-0121 §2 rules for
its own arm and exactly as ADR-0159 §4 rules for an unlabelled member: such a
member is a similarity hit, not evidence of a contradiction, and letting it
block would downgrade a *certain* agreement to a question on the strength of the
0.75 score this whole line of decisions exists to stop reading.

**Where the condition fails, `ASK_USER` is still right.** The proposal is a
belief we worked out, the set holds an assertion it does not agree with, and we
cannot tell from a similarity score whether the two contradict. Deferring is
ADR-0038 §3's ruling and this ADR does not touch it. What changes is that the
deferral is now reached by a determination rather than by the mere presence of
an assertion in a ranked list.

**The arm reads no score.** The conflict set supplies the candidates; ADR-0121
§1's predicate — `kind` and `content` under NFC, case folding, whitespace
collapse and strip, and nothing else — decides. Reading agreement off the score
inverts on the case that matters, for the reason ADR-0121 §1 gives and this ADR
does not restate: the strings scoring highest against "I prefer window seats"
include "I prefer aisle seats", and folding **that** onto a user assertion is
the one outcome no design here may reach.

### 2. The target source classes, and why `EXTERNAL` is still not one

> **Normative.** `USER_ASSERTED`, `OBSERVED` and `INFERRED` are the target source
> classes §1's arm may name. An `EXTERNAL` target is not, and a conflict-set
> member whose source is `EXTERNAL` is therefore never named by the arm, whether
> or not it agrees with the proposal.

This is ADR-0121 §3's set, unchanged, answering the same question one source
class over: *which target may an agreeing fold land on*. The shipped constant
`_AGREEMENT_FOLDABLE` already holds it, and this ADR adds no fourth allow-list —
ADR-0092 §5's warning is against **one set answering two questions**, and this is
one question asked twice.

**`EXTERNAL` stays out for ADR-0121 §3's reason, which this ADR does not
weaken.** A `REINFORCE` folds at the target's id, an imported record's id is the
integrating system's idempotency key, and the next routine sync overwrites the
fold. Identity of content does nothing to that argument, and an observation's
identity of content does nothing more than a user's did. ADR-0161 §1's clause
(ii) is the one pairing that reaches an `EXTERNAL` target, and it is untouched
here: it requires the *proposal* to be `EXTERNAL` and to carry the same
`provenance.attestation.reported_by`, which no `OBSERVED` or `INFERRED` proposal
does.

**The residue is stated rather than hidden.** An observation agreeing with an
imported record, in a set holding no assertion, is ADR-0159 §4's population and
is unchanged. In a set holding an assertion the observation also agrees with, the
arm folds onto the best-ranked member of the foldable agreeing set — which may be
the assertion or may be a better-ranked agreeing observation (§1) — and the
`EXTERNAL` member is never named either way. That is the same one-target limit
ADR-0121 left, and #871 files it.

### 3. Clause 1's second exception is widened in one condition; there is no third exception

> **Normative.** ADR-0121 §5's exception to `_refuse_unsafe_fold`'s clause 1 is
> widened in exactly one condition: the incoming record's `provenance.source`
> must be `USER_ASSERTED`, `OBSERVED` or `INFERRED`, where ADR-0121 §5 required
> `USER_ASSERTED`. Its other conditions are unchanged — the ruling is
> `REINFORCE`, and the two records **agree** under ADR-0121 §1.

> **Normative.** Clause 1 carries **two** exceptions after this ADR and not
> three: ADR-0078 §5b's covering confirmation, and ADR-0121 §5's agreeing fold
> as widened here. Every other fold onto a `USER_ASSERTED` target is refused
> exactly as before, including every `SUPERSEDE` outside ADR-0078 §5b's
> exception, every `REINFORCE` whose records do not agree, and every fold whose
> incoming record is `EXTERNAL`.

> **Normative.** The widened exception is **verified at the writer, never
> trusted from the ruling**: a conforming writer recomputes ADR-0121 §1's
> predicate and reads the incoming record's `provenance.source` itself, over the
> target it holds and the proposal it was given, and refuses the fold where
> either fails, whatever the ruling says.

**This is a widening rather than a third exception, and the distinction is
substantive.** ADR-0121's Consequences set the test — an exception must be
"keyed on facts that make clause 1's own justifications inapplicable". This
widening is keyed on **the same fact as the exception it widens**: §4 makes the
fold write the target's own bytes back at the target's own id. That fact is a
property of the *fold*, and specifically of the arm the fold takes, not of the
incoming record's source. ADR-0121 §5 required the incoming record to be
`USER_ASSERTED` because that was the only way, at ADR-0121's base, to reach the
corroboration arm; §4 below removes that dependency. So no second key is added,
one condition that was never doing the work is dropped, and clause 1's list of
exceptions is a list of two that a reader can still state from memory.

**Clause 1's two justifications are quoted and neither reaches this fold.**
ADR-0045 §5 states them:

> - *Destructiveness* — "the write replaces what the user told us". The window
>   dissolves this: a window-closing `SUPERSEDE` keeps the target on disk.
> - *Signal strength* — ADR-0038 §5 / §2: the conflict signal is topical
>   similarity (a 0.75 lexical or embedding score), **not** contradiction, and
>   is too weak to authorise retiring a record the user gave us.

§4's fold replaces nothing and retires nothing — it writes the target's own
content, source, confidence, attestation and window back at the target's own id
— and it does not run on the 0.75 score at all: the conflict set supplies a
candidate and ADR-0121 §1's predicate, which reads no score, decides.

**And ADR-0038 §2a's second half, which ADR-0121 never had to answer, is
answered here.** §2a's reason for clause 1 has two clauses and the second is
specific to this ADR's population: "from a non-asserted proposal it also
downgrades the record's provenance out of the profile". §4 keeps the target's
`provenance.source`, so the survivor stays in the `ASSERTED` band and the
profile ADR-0072 §1 defines as that band is unchanged. The reason does not
reach this fold either, and it is the reason that would have.

**It stays record-keyed**, which is the property ADR-0045 §5 was protecting when
it foreclosed a relation-split, and which ADR-0038 §2a's "*every* fold overwrites
the target, so the target is what has to be checked" makes load-bearing. The
predicate reads the target's source, the incoming record's source, and both
records' `kind` and `content`. All are record facts, in hand at the boundary,
and none of them is the relation between the records. The ruling appears in the
exception only to name which fold is permitted, exactly as ADR-0078 §5b's does.

**The reinforce-safe class is untouched.** It stays `{OBSERVED, INFERRED,
USER_ASSERTED}` and it answers clause 2's question — may a `USER_ASSERTED`
proposal fold at *this record's* id — which this ADR does not ask. ADR-0092 §5's
split between it and the retirement class stands, and the conformance case
pinning the `EXTERNAL` `REINFORCE` refusal keeps its job.

### 4. Every `REINFORCE` onto a user assertion corroborates

> **Normative.** A `REINFORCE` whose target's `provenance.source` is
> `USER_ASSERTED` **corroborates**, whatever the incoming record's
> `provenance.source`. The survivor is the stored target with its `content`,
> `provenance.source`, `provenance.confidence`, `attestation`, `validity` and
> `expires_at` unchanged.

> **Normative.** On that fold the survivor takes: the two records' `evidence`
> unioned under ADR-0086 §3's bound with their `evidence_elided` summed; the
> disjunction of their `derived_from_external` (ADR-0106 §4); the disjunction of
> their `supplied_withheld_content` (ADR-0204 §5); the incoming record's
> `last_updated`; and `last_confirmed_at` **composed** from the later of the two
> records' *usable* confirming instants, from whichever is usable where only one
> is, and as unknown only where neither is (ADR-0103 §6, ADR-0109 §5). It takes
> nothing else of the incoming record.

> **Normative.** This clause is keyed on the target's `provenance.source` and is
> **total** over the incoming record's. It is not keyed on the `ASSERTED` band.

> **Normative.** This clause subsumes ADR-0121 §4's second clause, which is the
> case where the incoming record is `USER_ASSERTED` and which it rules
> identically. ADR-0103 §6's clause — a `DERIVED` incoming record onto an
> `ATTESTED` target — sits beside it, unchanged in scope, wording and effect. A
> target is not both `USER_ASSERTED` and in the `ATTESTED` band, so the two
> clauses cannot both reach one fold and no precedence between them is stated.

**The reasoning is ADR-0103 §6's, and it is true of this pairing word for
word.** §6 rules that a derived record folded onto a better-warranted one "takes
nothing of the incoming record but its `evidence` and its effect on currency",
because agreement "is information about whether the belief still holds, not
about how much warrant it has: the observation supplies no warrant the target
did not already have." An observation agreeing with what the user told us is
exactly that sentence. We watched the user and re-derived a belief they had
already given us on their own authority. The observation adds no warrant — the
user's word is already the top of the scale — and it adds two real things: the
episode that showed it, and the fact that the belief was seen to hold again when
that episode happened.

**The instant is the observation's, not the write's**, and that is the product
value this ADR actually delivers. ADR-0103 §6 argues it: "A proposal citing a
January episode can sit in a batch and land in June; a fold that read its own
clock would report a belief confirmed in June on the strength of a January
observation." The composition is `_confirming_instant`'s, unchanged, and the
consequence is that beliefs the user goes on living out age more slowly than
beliefs they merely once stated. That is what ADR-0103 §3 built currency for and
what an automatically-running observer makes reachable for the first time.

**Keyed on the target's source, and total over the incoming record's, because
the mirror of the refusal is the safe shape.** ADR-0038 §2a's general lesson —
"*every* fold overwrites the target, so the target is what has to be checked" —
applies to how a fold folds exactly as it applies to whether it may. Stating
this clause over the target alone makes it a **floor** rather than an
enumeration: if some later ADR admits a fourth incoming source through clause
1's exception, that fold corroborates by default rather than falling to an
ordinary arm nobody weighed for it. A rule that has to be widened in two places
to stay correct is a rule that will one day be widened in one, and the place it
would be forgotten is the arm that overwrites the user's own words.

**Not keyed on the `ASSERTED` band, for ADR-0038 §2a's allow-list reason and for
symmetry with the refusal it mirrors.** §2a's shape argument is that "a
`MemorySource` added later is not silently enrolled in a destructive rule by
omission", and the corpus applies it to every membership question in this
neighbourhood. Clause 1 is itself stated over `USER_ASSERTED` and not over the
band, so a fold rule stated over the band would be *wider than the refusal it
pairs with* — it would prescribe how to fold folds clause 1 does not reach,
which is the failure ADR-0103 §6 named when it chose its own keying: "a clause
prescribing how that fold folds would prescribe a fold that may not happen." The
two clauses are keyed differently and each follows its own words; that asymmetry
is ADR-0103 §6's on the target side and ADR-0121 §4's on the source side, and it
is inherited rather than invented here.

**The subsumption is a simplification of the implementation and of nothing
else.** `_corroborates` today holds two pairings; after this ADR it holds two
again, one of which is wider. It does not become the reinforce-safe class read a
second time — that set answers a different question (§3) and reusing it here
would be the ADR-0092 §5 mistake this ADR has now declined twice.

**What is given up is named.** Where the incoming observation's confidence
happens to be relevant at all, today's `max` is not taken and the assertion's
`1.0` stands — which is trivially right here and worth saying, because on
ADR-0103 §6's pairing the same trade cost something real. Nothing is destroyed:
the observation's episode is retained and cited on the survivor, and it remains
available to propose the derived belief on its own terms if the assertion is
ever retired.

### 5. Where the test runs, what the lock gains, and what stays out

> **Normative.** ADR-0121 §6 binds unchanged: the agreement test is computed by
> `DefaultMemoryPolicy` when it chooses the ruling and independently by
> `MemoryIngestor` when it admits clause 1's exception; the canonical
> `MemoryWriter` fake in `ai_assistant.testing` computes it too; and no
> subsystem outside `memory` performs it.

> **Normative.** The shared `MemoryWriter` conformance suite gains cases for the
> widened permission and for the refusals it leaves standing, and the shared
> `MemoryPolicy` conformance suite is unchanged — §1's arm is
> `DefaultMemoryPolicy`'s ruling and not an obligation on every policy.

> **Normative.** ADR-0159 §2's reconciler invocation condition is untouched. No
> reconciler is invoked, no relation is computed and no model request is made on
> any ingest whose conflict set holds a `USER_ASSERTED` member, which is every
> ingest §1's arm reaches.

> **Normative.** This ADR adds no store read, no model call and no I/O to the
> ingest path, and disturbs no ordering inside `MemoryIngestor`'s lock:
> conflicts are detected, relations are determined where ADR-0159 §2 admits
> them, the policy rules, and `_refuse_unsafe_fold` runs before either fold arm
> is selected — exactly as they run today.

**The lock clause is stated because the obvious generalisation would breach
it.** A reader might reasonably ask why §1's arm does not simply lift ADR-0159
§2's exclusion and let a reconciler label this population, which would catch
paraphrase as well as exact restatement. ADR-0159 §2 refuses it in terms and its
reason is unchanged: a model request there would be spent "*inside the ingest
lock*", and the write path that holds that lock is the one an interactive turn
waits on. The narrow predicate needs neither a provider nor a network, so §1's
arm holds in the deployment ADR-0159 §6 ratifies — none configured at all —
which is the deployment an always-on observer is most likely to be running in.

**A model-judged agreement test would be *less* dangerous on this pairing than
on ADR-0121's, and is still refused.** Because §4 makes the survivor the target,
a false agreement here cannot rewrite a belief; it can only attach a wrong
episode and refresh currency on the strength of it. That is a smaller harm than
ADR-0121 §1 weighed. It is still refused, for two reasons: ADR-0159 §2's cost
argument above, and because admitting a judged test for one pairing of a
predicate ADR-0121 §1 states as **one** predicate would give the policy and the
writer two different answers to the same question — the single failure §1
forbids. Paraphrase is #868's, whole, for both arms at once.

**The duplication into `ai_assistant.testing` is golden rule 1's**, unchanged
from ADR-0121 §6: the canonical fake may not import `memory`, which is why the
predicate and now the arm's permission are stated normatively here rather than
left to one implementation to define.

### 6. What this does to the measures, and the one place issue #869 is wrong

> **Normative.** This ADR adds no metric key, changes no metric key's meaning,
> and requires no emitter to carry a quantity it does not carry today. Every
> definition in ADR-0120 §2, §3, §5 and §6 stands verbatim and is computed over
> the same keys.

What changes is which events occur, which is the point.

- **ADR-0120 §5's correction rate does not move at all.** Its ruling population
  is attributed to a **user** seam, and §3 fixes that set as "`converse`,
  `resume`, `observe`, `learn` and `answer`" — so `observe` is in it. But the
  numerator is `decisions_supersede` alone and the denominator is "the sum of
  the six `decisions_*` metric values". This arm moves rulings from
  `decisions_ask_user` to `decisions_reinforce`, and both are among the six. The
  numerator is untouched and the denominator's sum is unchanged.
- **ADR-0120 §6's repeated-explanation rate does not move either**, and cannot.
  Its population is the **direct** set, which §3 fixes as `learn` and `answer`.
  Both direct seams produce `USER_ASSERTED` proposals, and §1's arm fires only
  on an `OBSERVED` or `INFERRED` one, so the arm is structurally unreachable
  there. The producer ADR-0121 gave that numerator remains its only one.
- **The `observe` reinforcement share moves, and this is the one claim in issue
  #869 that does not hold.** #869 says: "The `observe` seam is excluded from
  ADR-0120 §6's measure by that clause's own ruling, so nothing in the
  instrument moves." The exclusion is real — §6's third clause: "`decisions_reinforce`
  under the `observe` seam is **not** part of this measure, and is not admissible
  as a substitute for it." But §6's *fourth* clause defines a second figure over
  exactly the excluded population — "The **`observe` reinforcement share** over
  `W` is the sum of `decisions_reinforce`, divided by the sum of the six
  `decisions_*` values, over every `MEMORY_WRITE` trace […] attributed to the
  `observe` seam" — and its fifth requires the report to state it, "labelled as
  the observation stage's re-mining overlap". That figure's numerator gains
  every ruling this arm makes, so it rises at this change. Nothing in ADR-0120
  becomes false; #869's inference from the exclusion to "nothing moves" is what
  is wrong, and correcting it changes no decision this ADR makes.
- **The `observe` reinforcement share has a discontinuity at this change**, and
  it is not one ADR-0120 §8 partitions on: §8 partitions a window at a
  `CONFIGURATION` trace whose metric mapping differs from its predecessor's, and
  a policy change emits none. This is ADR-0121 §7's finding reached a second
  time, on a third figure, and no amendment to §8 is proposed for the reason
  ADR-0121 gave: "partitioning on arbitrary code changes is not something the
  trace stream can see, and inventing a marker for it is a bigger decision than
  this one."
- **The deferral queue shrinks and no measure sees it.** ADR-0078's queue stops
  receiving a question per agreeing observation, which is the harm #869 reports
  and the reason to act. No ratified measure counts queued questions, so this is
  a product consequence rather than an instrument one.

### 7. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made here, clause by clause, so a
reviewer can check it against the quoted text and require a record added or
removed by naming the sentence that does or does not become false or over-wide.

**ADR-0038 §3 — amended**, in §1's scope and no wider. §3 ratifies the rule this
ADR narrows, in terms: "This is not new — `DefaultMemoryPolicy` already returns
`ASK_USER` when a non-asserted proposal conflicts with a user-asserted record —
and this ADR ratifies that rule as the counterpart of §1 rather than an
incidental precaution." A reader holding only ADR-0038 defers where §1
reinforces, so under ADR-0070 §1's test the sentence has become over-wide.
**What stands is §3's whole substance.** "The direction is strictly one-way: an
assertion may displace an inference; an inference may **never** displace an
assertion, silently or otherwise" is true word for word of this ADR, and §4 is
what keeps it true: nothing of the assertion is displaced, and §1's one
condition is what stops an observation adjudicating between two assertions by
refreshing one's currency. §3's second consequence — supersede the best-ranked
*supersedable* conflict by a scan rather than taking `conflicts[0]`, because
"taking the first would have let an assertion destroy an assertion by ranking
accident" — is untouched, and §1's arm scans for the same reason.

**ADR-0038 §2a — amended**, a second time and in the same scope. Its first fold
refusal — "**any** fold onto a `USER_ASSERTED` target, whatever the proposal's
source" — was narrowed once by ADR-0121 §5 and is narrowed once more by §3
above. Both halves of §2a's stated reason are quoted in §3 and neither reaches
this fold; the second half is the one specific to a non-asserted proposal, and
§4 is the clause that answers it. **What stands is nearly all of §2a**, exactly
as ADR-0121's own note records: the refusal stays keyed on the records, the
allow-list *shape* is untouched (§3 widens no set to `is not EXTERNAL` and adds
no set), §2a's second refusal onto an `EXTERNAL` target is untouched, and §2a's
"enforced at the ingestor, not only chosen by the policy" is why §3's widened
exception is recomputed at the writer rather than trusted from the ruling.
ADR-0038's `Status` line leads with `Partially superseded by`, so under ADR-0082
§2 the record goes in the appended dated note alone.

**ADR-0040 §5b — amended**, a second time. Its conformance predicate, stated so
it "cannot be paraphrased into something broader":

> A `REINFORCE` or `SUPERSEDE` must raise `MemoryStoreError` and write nothing
> when `target.provenance.source is USER_ASSERTED`, **or** when
> `incoming.provenance.source is USER_ASSERTED` **and**
> `target.provenance.source is EXTERNAL`. Every other pairing is permitted.

The first disjunct's exception widens by one condition, so a suite pinning the
disjunct as ADR-0121 left it would now refuse a fold this ADR permits — the
contract-widening mistake §5b itself names, arriving from the other direction.
The second disjunct is untouched, as is §5b's argument that the refusals are
contract rather than tuning and its reasoning about why a second writer is
exactly the conforming implementation the obligation is for.

**ADR-0045 §5 clause 1 — amended**, a second time, in the scope of §3's widening
and no wider. Clause 1's text is unconditional over rulings and sources, so it
becomes over-wide; its two justifications are quoted in §3 and neither becomes
false, because neither describes the permitted fold. ADR-0045's `Status` line
leads with `Partially superseded by`, so under ADR-0082 §2 the record goes in the
appended dated note alone. Everything else of §5 is in force, including §5b's
`EXTERNAL` narrowing and clause 1 for every other pairing.

**ADR-0121 §5 — amended.** Its normative clause reads that clause 1 "gains one
exception, and one only: a `REINFORCE` whose incoming record's source is
`USER_ASSERTED` and which **agrees** with the target under §1 is permitted. Every
other fold onto a `USER_ASSERTED` target is refused exactly as before, including
every `SUPERSEDE` outside ADR-0078 §5b's confirmation exception and every fold
from a non-asserted proposal." The final clause becomes false. **What stands is
the rest of §5**: the verification-at-the-writer requirement, the record-keyed
property and its ADR-0078 §5b precedent, the reinforce-safe class at `{OBSERVED,
INFERRED, USER_ASSERTED}`, `EXTERNAL`'s exclusion for ADR-0092 §5's reason, and
the retirement class untouched at `{OBSERVED, INFERRED, EXTERNAL}`.

**ADR-0121 §4 — nothing.** Its second clause rules that an agreeing `REINFORCE`
onto a `USER_ASSERTED` target "contributes the incoming record's **evidence and
its confirming instant, and nothing else**". §4 above rules identically for a
wider population, so a reader holding only ADR-0121 acts the same way on every
fold §4 reaches and reads no clause of it more widely. This is ADR-0082 §1's
stacked addition, recorded here and nowhere else — the same judgement ADR-0121
§9 made about ADR-0103 §6, for the same reason.

**ADR-0121 §2 — nothing.** Its arm is stated for a proposal "whose
`provenance.source` is `USER_ASSERTED`", and §1 above is a sibling arm on the
other side of that branch. No condition of §2's changes, its position relative
to the arms it precedes is unchanged, and its third clause — the fall-through —
still describes exactly what happens when its own conditions fail.

**ADR-0121 §11's second bullet — discharged, not amended.** It filed this
question and named the extension this ADR makes. A deferral discharged by the
lane it named is the mechanism working (ADR-0102 §13), and the appended note
records the discharge. Its remaining bullets are untouched: paraphrase (#868)
and the `EXTERNAL` residue (#870) are still open, and §9 below re-files them.

**ADR-0121's Consequences — nothing.** "Clause 1 has two exceptions now, and a
third would be a pattern" is not a normative clause, and this ADR does not make
it false in substance either: §3 widens the second exception rather than adding
a third, and states the test that consequence set and how the widening meets it.

**ADR-0103 §6 — nothing.** §4 above applies §6's rule to a third pairing. §6's
own clause is about a `DERIVED` proposal onto an `ATTESTED` target and is
unchanged in scope, wording and effect; §4's fourth clause states that the two
are disjoint. Nothing §6 says becomes false or over-wide. ADR-0121 §9 recorded
the same about the same clause, and this is the second stacked addition to it.

**ADR-0159 §4's fourth normative clause — partially superseded**, and this is the
section's most load-bearing entry. The clause reads:

> **Normative.** The `ASK_USER` ruling for a non-asserted proposal whose conflict
> set holds a `USER_ASSERTED` member is unchanged and continues to precede this
> arm. Nothing in this ADR reaches it.

A reader holding only ADR-0159 rules `ASK_USER` where §1 above rules `REINFORCE`,
so they act differently, and under ADR-0070 §1 that is a change to what was
decided rather than an amendment. It is **partial** and narrow: the clause stands
whole for every conflict set holding an asserted member that *disagrees* with the
proposal — which is every set §1's one condition fails on — and its second
sentence, "Nothing in this ADR reaches it", stays a true statement about
ADR-0159's own reach.

**Why this clause is superseded where §2a, §3 and the rest above are amended.**
ADR-0082 §1 requires the line to be argued rather than declared, and the test is
ADR-0070 §1's applied to the clause's own text. Every clause this ADR *amends* is
a **refusal or a deferral carrying a stated justification**, and in each case the
justification does not reach the permitted fold — the clause was over-wide
relative to its own reason, and every sentence of that reason survives. This
clause carries no justification at all. Its whole content is that a ruling
**continues to precede** an arm, and §1 places an arm ahead of it; there is
nothing in it for the permitted case to be an exception *to*, so it is replaced
in scope rather than narrowed by exception. That is the reading ADR-0121 §9 gave
ADR-0050 §2, whose rule was likewise "stated unconditionally over the conflict
set and positioned first".

**What stands, and it is the rest of ADR-0159.** §1's scope clause confines this
arm to a population §2 excludes from reconciliation and §4's three ruling arms
never rule on, so §2's invocation condition, §4(a), §4(b) and §4(c), §4's purity
conditions, `_RELATION_TARGETS`, §4's non-empty-set and reads-no-score clauses,
§5's retirement narrowing and §6's degraded-path parity all stand exactly as
written and rule exactly what they ruled. ADR-0159's `Status` line already leads
with `Partially superseded by`, so under ADR-0082 §2 this ADR's pair joins that
line and the record itself goes in the appended dated note. ADR-0161 is likewise
untouched: its clause (ii) requires an `EXTERNAL` proposal, which §1's arm
excludes by its own scope.

**ADR-0092 §5 — nothing.** The reinforce-safe class is not widened (§3) and the
retirement class is not touched. §5's split between them and its warning against
tidying the constants into one stand, and this ADR declines the tidy-up twice —
once for the target class in §2 and once for the fold rule in §4.

**ADR-0050 §2 and ADR-0078 §5b — nothing.** Both are stated over a
`USER_ASSERTED` proposal or a user's confirmation, neither of which §1's arm
touches. ADR-0121 §9's partial supersession of ADR-0050 §2 is unchanged in
scope.

**ADR-0120 — nothing, and this is not an oversight.** Every normative clause of
§2, §3, §5, §6 and §8 stays literally true and computable; the measures are
defined over metric keys and this ADR adds none, removes none and redefines
none. What changes is the frequency of events the keys count, which is the world
moving. A **dated note** is nevertheless appended to ADR-0120, which ADR-0070 §1
permits unconditionally, recording that the `observe` reinforcement share gains
a producer at this change and carries a discontinuity §8 does not partition on —
a future reader of §6 needs that fact and can get it nowhere else. It is a note,
not an ADR-0082 §1 record: no clause of ADR-0120 fails ADR-0070 §1's test.

**ADR-0204 §5 and ADR-0106 §4 — nothing.** Both state their disjunction over the
fold rather than over either side, and §4's second clause takes both on the
widened arm exactly as `_merge` already takes them on the two existing ones. A
rule stated over the fold does not narrow when the fold's population grows.

All of these edits land in **this ADR's PR**, so no `Status` line or note ever
names an ADR that does not exist.

### 8. What the implementing lane owes

The implementing lane is `memory` plus `ai_assistant.testing` plus their tests,
and it is one subsystem's change.

- `memory/policy.py`: §1's arm in `_rule_on_conflicts`, ahead of the
  prior-assertion deferral and behind the confirmation rule, reading
  `_AGREEMENT_FOLDABLE` and `agrees` and nothing else; the class docstring's
  numbered rules renumbered to match, with rule 5's entry rewritten to say what
  now precedes it. No new module-level constant.
- `memory/ingest.py`: `_agreeing_restatement`'s second condition widened from
  `incoming.provenance.source is MemorySource.USER_ASSERTED` to membership of
  `{OBSERVED, INFERRED, USER_ASSERTED}`, and `_corroborates`'s second pairing
  restated as `target.provenance.source is MemorySource.USER_ASSERTED` alone.
  `_merge` itself needs no change: its corroboration arm already writes what §4
  specifies, and the docstring paragraphs naming "ADR-0121 §4's second clause"
  gain this ADR's wider statement.
- `ai_assistant.testing`'s `FakeMemoryWriter` (`testing/writer.py`): the same
  two edits to its own `_agreeing_restatement` and `_corroborates`, duplicated
  rather than imported (golden rule 1), so the fake and `MemoryIngestor` cannot
  answer the conformance suite differently.
- `tests/memory/memory_writer_contract.py`: the widened permission (an
  `OBSERVED` and an `INFERRED` `REINFORCE` agreeing with a `USER_ASSERTED`
  target, each folding and each leaving the survivor's `content`, `source` and
  `confidence` untouched), and — pinned, because they are the cases a later
  tidy-up breaks — the refusals it does not disturb: a non-agreeing non-asserted
  `REINFORCE` onto an assertion, an `EXTERNAL` `REINFORCE` onto an assertion, a
  `SUPERSEDE` onto an assertion outside ADR-0078 §5b, and the standing
  `USER_ASSERTED` → `EXTERNAL` `REINFORCE` refusal.
- `tests/memory/test_policy.py`: the three cases that pin §1 by its shape — an
  agreeing `OBSERVED` proposal whose conflict set holds an agreeing assertion
  rules `REINFORCE` and does not ask; the same proposal where a *second*
  assertion in the set disagrees still rules `ASK_USER`; and an `OBSERVED`
  proposal whose only agreeing member is `EXTERNAL` still rules `ASK_USER` (§2's
  target class). Two more pin the arm's boundaries, and the first is the case an
  implementation is likeliest to get wrong. **The incoming-source boundary**: an
  `EXTERNAL` proposal agreeing exactly with a `USER_ASSERTED` conflict still
  rules `ASK_USER`. The branch this arm is added to is keyed on `not
  is_asserted`, which admits `EXTERNAL`; widening *that* branch instead of naming
  `OBSERVED` and `INFERRED` would rule `REINFORCE` on a fold §3 does not permit,
  and `_refuse_unsafe_fold` would then turn a deferral into a `MemoryStoreError`
  — a failure the writer-side conformance cases cannot catch, because the ruling
  never reaches them from a conforming policy. **The scope boundary**: with no
  asserted member in the set, the ruling is whatever ADR-0159 §4 gives and this
  arm is not consulted. And one more, pinning the **target selection** itself: an
  `OBSERVED` proposal against the ordered conflict set `[OBSERVED, USER_ASSERTED]`
  where both agree must rule `REINFORCE` naming the **`OBSERVED`** member, and the
  same two records in the order `[USER_ASSERTED, OBSERVED]` must name the
  **assertion**. Nothing else in this list distinguishes those two, and they do
  not merely differ in `target_id`: they select different arms of `_merge` (§4),
  so an implementation preferring the assertion by source rather than by rank
  would corroborate where the ordinary arm is owed, and would pass every other
  case here.
- `tests/memory/test_currency_fold.py`, `test_taint_fold.py` and
  `test_withheld_fold.py`: the composed `last_confirmed_at` and the two
  disjunctions exercised on the widened pairing, in the direction that can fail
  — a tainted or stamped **target** reinforced by a clean observation.
- No change to `core/protocols.py`, `core/types.py`, `learning/`,
  `orchestration/` or `interfaces/`, and no change to
  `tests/memory/memory_policy_contract.py`.

### 9. What this ADR does not decide

- **Paraphrase**, for either arm (#868, ADR-0121 §11). §5 argues why the answer
  must be one answer for both and why the ingest lock is the constraint, and
  decides nothing beyond that.
- **The `EXTERNAL` residue** (#870, ADR-0121 §3, §7). §2 keeps `EXTERNAL` out of
  the target class for ADR-0121 §3's reason and adds nothing to the question.
- **Whether a multi-member agreeing set should fold more than once** (#871). §1
  names one target and leaves any second agreeing member live, which is the same
  limit ADR-0121 §2 left and the same duplication residue ADR-0092 §7 names,
  reached here by a third path.
- **Whether §1 should prefer an agreeing assertion over a better-ranked agreeing
  observation.** It does not: the arm takes the best-ranked member of the
  foldable agreeing set, which is ADR-0121 §2's rule and ADR-0159 §4(a)'s. The
  difference is observable and is more than a `target_id` — the two selections
  run different arms of `_merge` (§4), so where an observation is named the
  assertion's currency is not refreshed at all. Preferring the assertion would
  refresh the record that actually stands rather than an observation ranked above
  it, which is arguably better, and it would make rank stop being the tie-break
  both sibling arms use. It is a real question and it is not this ADR's; it is
  filed with #871, whose subject is the same set read the same way.
- **A marker for a policy change in the trace stream** (§6, ADR-0121 §7). Not
  proposed, for the reason ADR-0121 gave.
- **Whether the observation stage should decline to propose a belief it has
  already proposed.** That is the observation cursor's neighbourhood (#1737,
  #785) and a different subsystem's decision. It would reduce this arm's
  population and would not remove it: a cursor stops re-mining the same
  episodes, and this arm fires on a *first* observation of a belief the user
  separately asserted.

## Consequences

- **An observation that restates what the owner told us stops producing a
  question the owner should never have been asked.** This is the product
  consequence and it is the reason to act; batch #1782's observe-on-quiet is
  what makes it urgent rather than latent.
- **A user assertion now gains evidence and currency from being lived out.**
  Before this ADR the only thing that could refresh an assertion's currency was
  the user saying it again (ADR-0121). Now watching them act on it does too,
  which is closer to what ADR-0103 §3 built currency to mean and is reachable
  for the first time from the stage that produces most of the system's beliefs.
- **Clause 1 still has two exceptions, and the second is now stated over three
  incoming sources.** The failure mode ADR-0121 named — "a clause with a list of
  exceptions nobody can state from memory" — is not made worse, and the test it
  set is met in §3. A third exception would still be a pattern.
- **The corroboration rule is now target-keyed on one side and band-keyed on the
  other**, which is a genuine irregularity in `_corroborates` and is argued
  rather than tidied (§4). Anyone tempted to make the two clauses look alike
  should read ADR-0103 §6's paragraph on why its own keying is "deliberate rather
  than economical" and §4's on why this one is not the same question.
- **The `observe` reinforcement share becomes larger and less comparable across
  this change** (§6), and #869's claim that nothing in the instrument moves is
  corrected. Anyone reading a window spanning this change must partition by
  hand, exactly as ADR-0121 §7 requires for the two figures it moved.
- **`ASK_USER` on the observed path is now a determination rather than a
  side effect of a ranked list.** Where it fires, it fires because an assertion
  in the set does not agree — which is a statement about content, not about
  retrieval order. That is a better question to be asked and there will be far
  fewer of them.
- **Revisit when** a model-judged agreement test is on the table (#868), or when
  the `observe` reinforcement share rises far enough that the gap between exact
  restatement and paraphrase becomes the dominant uncertainty in it.

## Alternatives considered

- **Rule `REJECT` for an observation restating a standing assertion.** It writes
  nothing, creates no duplicate, needs no writer-floor change at all, and is by
  some distance the cheapest fix here. Rejected for ADR-0121's reason applied to
  a stronger case: it throws away the one thing the observation supplies
  (currency, ADR-0103 §3), and `REJECT` means the policy declined a proposal for
  want of warrant, so using it for a proposal that is true, already held, and
  freshly evidenced is the mislabelling ADR-0040 §1 forbids. It would also make
  the observer's agreement with the user invisible in the trace stream, where
  §6's `observe` reinforcement share is the only place it can show.
- **Rule `ACCEPT` and let the observation land beside the assertion.** Rejected:
  it is the duplication ADR-0092 §7 names as a residue to shrink, and it puts a
  second record of the same belief at a *lower* band beside the user's own
  words, which is what a later read then has to reconcile.
- **Fold on the ordinary arm and accept the demotion.** Rejected in §3 and by
  ADR-0038 §2a's own words: the survivor would leave the `ASSERTED` band, so a
  belief the user told us would silently become one we merely observed, and the
  next assertion-versus-inference ruling would treat it as an inference. That is
  the harm clause 1 exists to prevent, and it is the reason the corroboration
  arm is the whole of the fix.
- **State §1's arm over every non-asserted proposal, not only those whose
  conflict set holds an assertion.** Rejected in §1: it would fire ahead of
  ADR-0159 §4's two exceptions on a population they rule today, dropping their
  purity conditions and widening their target class as a side effect. Fixing
  #869 does not license relitigating #1188's decision.
- **Extend ADR-0159 §2 so a reconciler labels this population.** Rejected in §5:
  it spends a model request inside the ingest lock on the path an interactive
  turn waits on, and it makes a ruling depend on a provider being reachable in
  exactly the deployment ADR-0159 §6 ratifies without one.
- **Add a fourth allow-list for the incoming sources the corroboration arm
  admits.** Rejected in §4: the arm is stated over the target and is total over
  the incoming side precisely so that no such list exists to fall out of date,
  and the permission that *does* need an allow-list is clause 1's exception,
  which already has one.
