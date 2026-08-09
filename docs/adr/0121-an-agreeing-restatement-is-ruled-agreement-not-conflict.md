# 121. An agreeing restatement is ruled agreement, not conflict

- Status: Proposed
- Date: 2026-08-09
- **Not a contract change under golden rule 5.** No Protocol in
  `core/protocols.py` gains a member or changes a signature, no type or enum
  member is added to `core/types.py`, and in particular **no
  `MemoryDecisionKind` member is added** (§8). It is nevertheless a change to a
  ratified `MemoryWriter` **conformance obligation** — ADR-0040 §5b's fold
  refusal, which "*is* the contract" in that ADR's own words — so it ships as
  its own `Proposed` PR and carries **both** review lenses, per
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation".
- **This ADR amends** [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)
  §2a, [ADR-0040](0040-reinforcement-and-supersession-are-different-rulings.md)
  §5b, [ADR-0045](0045-memory-records-carry-a-validity-window.md) §5 (clause 1)
  and [ADR-0092](0092-an-attested-belief-names-its-source-and-a-user-assertion-retires-it.md)
  §5, and **partially supersedes**
  [ADR-0050](0050-resolving-the-full-contradiction-set.md) §2 in the scope named
  in §9. §9 applies ADR-0070 §1's test to each, including the places a record
  looks owed and is not.
- **Follow-up to** [ADR-0120](0120-a-measure-is-a-rate-over-the-trace-stream-read-offline-while-the-hub-is-stopped.md)
  §6, whose numerator this ADR gives a producer, and to ADR-0040 §7, which filed
  the mirror of this question and left it to the policy lane. Refs #862, #863,
  #865.

## Context

### Leg 8's instrument found a population that cannot occur

ADR-0120 §6 ratified the **repeated-explanation rate**: the sum of
`decisions_reinforce` over the direct seams `learn` and `answer`, divided by the
sum of the six `decisions_*` values over the same population. Leg 8's QA run
(#862) drove a live hub through four deliberate restatements and the numerator
fired zero times, while the `observe` seam reinforced freely (share 0.60–0.78).

Issue #863 records that as an undercount. It is stronger than an undercount, and
the correction matters because it changes what has to be decided.
`DefaultMemoryPolicy._rule_on_conflicts` routes every user-asserted proposal to
`_rule_on_assertion` before it reaches the reinforce site, and
`_rule_on_assertion` has exactly three arms — `ASK_USER`, `SUPERSEDE`, `ACCEPT`.
The policy's rule 9 reinforce sits behind `not is_asserted`. Both direct seams
produce `USER_ASSERTED` proposals. So `decisions_reinforce` at a direct seam is
**structurally unreachable**, at any input, for any conflict set: the measure is
not noisy or small, it is defined over an empty event class.

ADR-0120 §6 did not know this. Its own prose reads as though the class were
inhabited —

> **What a `REINFORCE` means is fixed by the enum and it is the right event.**
> `MemoryDecisionKind`'s docstring: "`REINFORCE` — the incoming record agrees with
> the target and strengthens it." A direct user act that produces a reinforcement
> is the user supplying a belief the system already held […]

— and it priced the cost as volume rather than reachability: "The cost is a small
population, and it is accepted rather than hidden." That sentence was not true of
the tree when it was written. Nothing ADR-0120 *decided* is wrong; it defined a
rate over a key, and the rate is computed correctly. What was missing is a
producer, and producing one is a policy decision, which is what this ADR is.

### What the policy does with a restatement today, in both directions

The two live failure modes share one cause and are worth stating separately,
because they land in different measures.

**A verbatim restatement of the user's own assertion becomes a contradiction
question.** `_rule_on_assertion` arm 1 fires when *any* member of the conflict
set is `USER_ASSERTED`, and the conflict set is
`MemoryIngestor._detect_conflicts`'s output: a same-kind ranked retrieval
filtered at `conflict_threshold`, default `0.75`. That is a **topical
similarity** signal, which the arm's own docstring concedes in terms — "topical
similarity is not a contradiction signal (ADR-0045 §5)". A user restating their
own standing preference word for word scores at the top of that ranking, so the
arm fires and the system asks the user whether they are contradicting
themselves. #862 observed this three times out of three.

That is precisely the interaction ADR-0038 §5 predicted when it rejected
`ASK_USER` for this case: "`ASK_USER` would interrogate the user about a
'conflict' that is most often a restatement." ADR-0050 §2 overrode §5 for good
reasons — issue #245's honesty gap is real, and ADR-0045's window made a
confirmation's outcome non-destructive — but it defended the interrogation cost
on a premise the run falsifies:

> The prompt is also **targeted** — it fires only when an incoming assertion
> topically conflicts with an *existing assertion*, not with an inference and
> not with an external record — so it is rare and high-value, not the blanket
> interrogation §5 feared.

It is targeted on *topical conflict*, and topical conflict is exactly what a
restatement is. The targeting selects the benign case as reliably as the harmful
one. ADR-0050 §2's ruling is right about contradictions and over-wide about
agreement, and it has never had a discriminator with which to tell them apart.

**A restatement that agrees with a belief we merely observed either retires it or
duplicates it, and never reinforces it.** Which of the two happens turns on the
conflict threshold, and both were seen:

- Above threshold, arm 2 fires. It names the best-ranked conflict whose source is
  in the retirement class and rules `SUPERSEDE` — closing the window on the very
  record the user just confirmed, and counting in ADR-0120 §5's correction rate
  as a belief the user overturned. An agreement inflating the correction rate is a
  measure-fidelity defect that #863 does not name and that §5's own justification
  forbids: "One ruling kind means 'what was held is now wrong', and it is the one
  counted."
- Below threshold the conflict set is empty, arm 3 rules `ACCEPT`, and a second
  near-identical record lands beside the first. #862's scratch store ended the run
  holding three near-identical window-seat records while the observation job
  reinforced one of them twice from the same conversation.

### The corpus has been circling this for four ADRs

This is not a new observation, and almost every piece of the argument is already
ratified somewhere.

ADR-0040 §4 labelled the mirror case honestly and filed the question:

> Whether rule 5 should sometimes supersede is a question about
> `DefaultMemoryPolicy`'s reasoning, decidable in the policy lane once the
> vocabulary exists, and it is filed rather than answered here (§7).

ADR-0040's Context named this exact quadrant as the live residue — "an asserted
restatement of something we had inferred" — read by the applier as supersession.
ADR-0045 §7 left #245 as "a decidable policy-lane question", noting that the
narrowing it would need is "gated on a real contradiction signal (or explicit
user confirmation)". ADR-0092 §6 already relies on identity of content routing a
restatement to a fold, on the non-asserted path:

> an unchanged re-sync proposes the same content, `_detect_conflicts` scores an
> identical live record at the top of its ranking (lexical overlap under the
> in-memory store, embedding similarity under SQLite — identical text is the one
> case neither can miss), and `DefaultMemoryPolicy` rules `REINFORCE`, which
> folds at the **target's** id. One record, updated in place, no duplicate […]

An `EXTERNAL` producer restating itself folds. A user restating themselves gets a
question, a duplicate, or a retirement. That asymmetry is the whole defect, and
closing it is a policy-lane decision the vocabulary has been waiting on since
ADR-0040 §1 named `REINFORCE` for the relation rather than the mechanism.

### What makes this a decision rather than a patch

Three things have to be *decided*, and none of them follows from the ADRs above.

1. **What upgrades a conflict-set member from "similar" to "agreeing."** The
   conflict set is a similarity signal, and ADR-0045 §5's surviving justification
   is that similarity is too weak to authorise a destructive fold. A ruling that
   read agreement off the same signal would inherit the same weakness pointing
   the other way — and would be worse, because the failure mode of a false
   *agreement* is folding a contradiction into the record it contradicts.
2. **What the ruling is per target source class**, given that a `USER_ASSERTED`
   target is currently forbidden to fold at all (ADR-0045 §5 clause 1) and an
   `EXTERNAL` target is forbidden to be reinforced for a reason (ADR-0092 §5)
   that identity of content does nothing to dissolve.
3. **Where the test runs**, given ADR-0038 §2a's standing rule that a safety
   property "may not rest on the ruling it is protecting against."

## Decision

### 1. Agreement is a decidable property of two records, never an inference

Two records **agree** when a reader can see that they say the same thing without
any judgement being exercised. This ADR fixes that as a syntactic predicate over
the records themselves, so that the policy that chooses a ruling and the writer
that verifies it compute the same answer from the same inputs, with no store
read, no model call, and no scoring.

> **Normative.** Two `MemoryRecord`s **agree** exactly when their `kind` values
> are equal and their `content` strings are equal after applying, in order:
> Unicode NFC normalisation, Unicode case folding, replacement of every maximal
> run of Unicode whitespace by a single space, and removal of leading and
> trailing whitespace. No other transformation participates in the test.

> **Normative.** The agreement test reads `kind` and `content` and **nothing
> else**. It never reads a retrieval score, a `Provenance` field, a validity
> window, a band, an embedding, or any value obtained from a `ModelProvider`.

The four transformations are chosen to be exactly the ones that change no word.
They admit "I prefer window seats" against "I prefer  Window Seats." and admit
nothing else. Stemming, synonym expansion, stop-word removal and any embedding
comparison are excluded, and their exclusion is the point rather than a
simplification: each of them decides that two *different* strings mean the same
thing, which is a judgement, and a judgement is what this predicate must not
contain if it is to license the fold §5 permits.

**A raised similarity threshold is refused, and the reason is that it inverts on
the case that matters.** The obvious cheaper design is to keep reading the
conflict set's scores and call anything above some higher band (0.95, say)
agreement. It fails in the one direction no design here may fail. Retrieval
scores measure surface proximity, so the two strings that score *highest* against
"I prefer window seats" include "I prefer aisle seats" — a one-token edit, and
under `ASSISTANT_EMBEDDER=hashing`, which is what #862 ran and what a
low-resource deployment runs, a near-maximal score. A false agreement folds a
correction into the belief it corrects, at that belief's id, taking the maximum
confidence — silently converting the user's correction into a reinforcement of
what they were correcting. That is a strictly worse failure than either failure
mode this ADR is fixing, and no threshold value avoids it, because the ordering
that produces it is the ordering the score is computed from.

**A model-judged entailment test is refused here, not forever.** "The user said
the same thing in different words" is a real and larger population than exact
restatement, and only a language model can see it. Admitting one would put a
`ModelProvider` behind `MemoryPolicy.decide` — a new injected dependency on the
ingest path, a non-deterministic ruling, a network call inside a write, and a
Protocol change. Each of those is arguable; together they are a different ADR
with a different blast radius, and the narrow predicate is available now and
strictly better than nothing. §7 states the measurement consequence: the
resulting rate is a **lower bound**, and it says so in the report's own terms.

### 2. An agreeing restatement is ruled `REINFORCE`, ahead of both conflict arms

> **Normative.** For a proposal whose `provenance.source` is `USER_ASSERTED`, let
> the **agreeing set** be the members of the conflict set that agree with the
> proposal under §1, and the **foldable agreeing set** be those members of it
> whose `provenance.source` is `USER_ASSERTED`, `OBSERVED` or `INFERRED`.

> **Normative.** `DefaultMemoryPolicy` rules `REINFORCE`, naming as `target_id`
> the best-ranked member of the foldable agreeing set, exactly when **both** hold:
> the foldable agreeing set is non-empty, and every `USER_ASSERTED` member of the
> conflict set is in the agreeing set. This arm is evaluated **before** the
> prior-assertion deferral and before the supersession arm.

> **Normative.** Where those conditions do not all hold, the proposal falls
> through to the prior-assertion deferral, the supersession arm and the
> acceptance arm exactly as they stand, with no change to any of them.

**The second condition is what keeps issue #245 closed, and it is not optional.**
Without it, a user who said "window seats", then "aisle seats", then "window
seats" again would reinforce the first record and leave the second live — two
live contradictory assertions, which is the honesty defect ADR-0050 §2 exists to
prevent, reached by a new path. The condition is stated over the *asserted*
members only because they are the ones ADR-0050 §2 protects: a disagreeing
`OBSERVED` or `INFERRED` member in the set is not evidence of a contradiction
(it is a similarity hit) and is dealt with by the next clause.

**An agreement retires nothing, and this is a deliberate narrowing of what a
restatement is worth.** `REINFORCE` has no retirement set (ADR-0045 §4; ADR-0050
§1's widening is a `SUPERSEDE` mechanism), so members of the conflict set outside
the agreeing set are left live. That is the honest outcome: the proposal added no
information, so it warrants no retirement, and retiring a record on the strength
of a *restatement* would be retiring it on similarity alone — the thing ADR-0045
§5 refuses. The first time the user asserted this belief, the ordinary
supersession arm ran and retired what it was warranted to retire; a second
telling does not buy a second retirement.

**The arm's position is what makes it a decision rather than a tie-break.** It
must precede the prior-assertion deferral, because that arm is unconditional over
asserted conflicts and would otherwise consume every self-restatement; and it
must precede the supersession arm, because that arm would otherwise retire an
agreeing `OBSERVED` belief. Placed anywhere else it is unreachable, in exactly
the way `decisions_reinforce` is unreachable today.

### 3. The ruling per target source class, and why `EXTERNAL` is not in it

> **Normative.** `USER_ASSERTED`, `OBSERVED` and `INFERRED` are the target source
> classes an agreeing restatement may fold onto. An `EXTERNAL` target is not, and
> a conflict-set member whose source is `EXTERNAL` is therefore never named by
> the arm in §2, whether or not it agrees with the proposal.

`OBSERVED` and `INFERRED` need no new permission at the writer floor: ADR-0038
§2a's reinforce-safe class already admits them, and ADR-0040's implementation
obligations already pin the case — "a policy returning `REINFORCE` for a
`USER_ASSERTED` proposal onto an `INFERRED` target keeps that target's evidence."
The applier has been able to perform this fold since ADR-0040; only the policy
has never asked for it.

`USER_ASSERTED` needs a narrow, verified exception at the writer floor, which §5
grants and argues.

**`EXTERNAL` is excluded, and the exclusion is not an oversight to tidy up
later.** ADR-0092 §5's reason for keeping `EXTERNAL` out of the reinforce-safe
class is that a `REINFORCE` folds at the *target's* id, an imported record's id
is the integrating system's idempotency key, and the next routine sync overwrites
the fold. Identity of content does nothing to that argument — the next sync
overwrites the record whether or not the user's words matched the import's. So
the refusal stands exactly as ADR-0092 §5 wrote it, and the reinforce-safe class
does not gain a third derived member here.

**The residue is stated rather than hidden.** A user asserting what an imported
record already says therefore still falls through to the supersession arm and
still counts in ADR-0120 §5's correction rate as a correction that did not
happen. The store outcome is defensible — a `SUPERSEDE` mints a fresh id
(ADR-0045 §4), so the user's own words land off the foreign key and the import is
retired, which is what ADR-0092 §4 decided a user assertion does to an import —
and only the measure's label is wrong. §7 files it; it is not fixable without
either widening the reinforce-safe class against ADR-0092 §5's live reason or
distinguishing the case in the trace, which §8 declines.

### 4. A fold takes from a restatement what the restatement actually adds

`REINFORCE`'s ordinary fold arm writes the incoming record at the target's id,
taking the incoming record's `source`, content and attestation and the maximum of
the two confidences. That is right where new warrant genuinely arrives and wrong
where none does, and an agreeing restatement is both cases depending on the
target.

> **Normative.** An agreeing `REINFORCE` onto an `OBSERVED` or `INFERRED` target
> folds on the ordinary arm, unchanged. The survivor is the assertion at the
> target's id: `source` becomes `USER_ASSERTED`, confidence is the maximum,
> evidence is unioned and currency is composed as ADR-0109 §5 rules.

> **Normative.** An agreeing `REINFORCE` onto a `USER_ASSERTED` target
> contributes the incoming record's **evidence and its confirming instant, and
> nothing else**. The survivor is the stored target with its `content`,
> `provenance.source`, `provenance.confidence`, `attestation`, `validity` and
> `expires_at` unchanged; the evidence union, `derived_from_external` disjunction,
> `last_updated` and the composed `last_confirmed_at` move exactly as they do on
> the ordinary arm.

The two clauses are one rule read against two targets. When the user confirms a
belief we had merely observed, real warrant arrives: the belief is now something
they told us, and promoting the survivor's source is not a side effect of the
fold but the substance of it — the record moves into the class rule 5 protects
from silent override, which is precisely the standing a user assertion is
entitled to. When the user confirms a belief they had already asserted, no
warrant arrives that the record did not already have. The same authority is
saying the same thing again, so the only new facts are that the belief still
holds (currency) and what episode showed it (evidence).

**The second clause is the shape ADR-0103 §6 already ruled, applied to a second
pairing, and it is a stacked addition rather than an amendment.** ADR-0103 §6
rules that a derived record folded onto an attested one "contributes its evidence
and nothing else", on the reasoning that agreement "is information about whether
the belief still holds, not about how much warrant it has: the observation
supplies no warrant the target did not already have." That sentence is true, word
for word, of a restatement onto an assertion. ADR-0103 §6's own clause is about a
`DERIVED` proposal onto an `ATTESTED` target and stays exactly as it is; this ADR
adds a second pairing to which the same rule applies, and contradicts no sentence
ADR-0103 wrote (§9).

**Nothing in `core` constrains which content wins, so no contract moves here.**
ADR-0040 §5a states in terms that beyond evidence retention, "which content wins,
how confidence combines, `last_updated` — is unasserted". The fold rule is
`memory`'s, exactly where ADR-0028 §8 left it.

**And it is what makes §5's exception provable rather than argued.** Under this
clause an agreeing fold onto a user assertion writes the target's own bytes back
at the target's own id. Not similar bytes, not normalised bytes: the same ones.

### 5. Clause 1 gains a verified exception and stays record-keyed

ADR-0045 §5 clause 1 refuses **any** fold onto a `USER_ASSERTED` target, for both
rulings, and states two justifications for the refusal:

> - *Destructiveness* — "the write replaces what the user told us". The window
>   dissolves this: a window-closing `SUPERSEDE` keeps the target on disk.
> - *Signal strength* — ADR-0038 §5 / §2: the conflict signal is topical
>   similarity (a 0.75 lexical or embedding score), **not** contradiction, and is
>   too weak to authorise retiring a record the user gave us.

Both justifications are about a fold that **replaces or retires** what the user
told us. §4's fold does neither: it writes the target's own content back, keeps
its source, confidence, window and attestation, retires nothing, and closes no
window. And the signal it runs on is not the 0.75 score at all — the conflict set
supplies a *candidate*, and §1's predicate, which reads no score, decides. Clause
1's reasons do not reach this fold, and this ADR carves out exactly the case in
which they do not.

> **Normative.** `_refuse_unsafe_fold`'s clause 1 — no fold of any kind onto a
> `USER_ASSERTED` target — gains one exception, and one only: a `REINFORCE`
> whose incoming record's source is `USER_ASSERTED` and which **agrees** with the
> target under §1 is permitted. Every other fold onto a `USER_ASSERTED` target is
> refused exactly as before, including every `SUPERSEDE` outside ADR-0078 §5b's
> confirmation exception and every fold from a non-asserted proposal.

> **Normative.** The exception is **verified at the writer, never trusted from
> the ruling**: a conforming writer recomputes §1's predicate over the target it
> holds and the proposal it was given, and refuses the fold when the predicate
> does not hold, whatever the ruling says.

> **Normative.** A conforming writer performing the permitted fold writes it as
> §4's second clause specifies. A writer that would fold otherwise refuses
> instead.

> **Normative.** The **reinforce-safe class** becomes `{OBSERVED, INFERRED,
> USER_ASSERTED}`. `EXTERNAL` remains excluded, for ADR-0092 §5's reason
> unchanged. The **retirement class** is untouched at `{OBSERVED, INFERRED,
> EXTERNAL}`, and the two sets stay separately named.

**Clause 1 stays keyed on the records, which is the property ADR-0045 §5 was
protecting when it foreclosed a relation-split.** ADR-0045 §5 says "Clause 1
(below) stays record-keyed", having just split §5b's `EXTERNAL` clause *by
relation* because `SUPERSEDE` and `REINFORCE` had stopped doing the same thing to
the id. This ADR does not split clause 1 by relation: the exception's predicate
reads the target's source, the incoming record's source, and both records' `kind`
and `content` — all record facts, all in hand at the boundary, none of them the
relation between the records. The ruling appears in the exception only to name
which fold is permitted, exactly as ADR-0078 §5b's confirmation exception names
`SUPERSEDE`. ADR-0038 §2a's "*every* fold overwrites the target, so the target is
what has to be checked" survives intact, because the exception's whole content is
a proof that this fold does not overwrite the target.

**ADR-0078 §5b is the precedent for the mechanism and answers the one objection
to it.** That ADR narrowed this same clause by a verified exception, and drew the
line at `SUPERSEDE` on the ground that "a `REINFORCE` onto an assertion would
rewrite the user's own words at the target's id, which no answer authorises."
That sentence is exactly right and is exactly what §4's second clause makes
false of this fold: the user's words are not rewritten, because the target's
content is what is written. The exception is keyed on the very fact that
disarms §5b's reason for excluding it, and on nothing else.

**The reinforce-safe class is widened to match its ratified meaning, not past
it.** ADR-0092 §5 defines membership as "does not carry a foreign idempotency
key". A `USER_ASSERTED` record carries none; it was outside the set only because
clause 1 already refused every fold onto it, so the question never arose. Leaving
it out would refuse the permitted fold twice, once for a reason that is false of
it — which is the drift ADR-0092 §5 warns about from the other direction, a set
whose membership stops matching the question it answers. `EXTERNAL` stays out
because its exclusion *is* the meaning, and this ADR neither widens the
retirement class nor merges the two sets. ADR-0092 §5's split remains the
standing rule and the conformance case pinning the `EXTERNAL` `REINFORCE`
refusal keeps its job.

### 6. The test runs in the policy and again at the writer, and nowhere else

> **Normative.** The agreement test is computed by `DefaultMemoryPolicy` when it
> chooses the ruling, and independently by `MemoryIngestor` when it admits §5's
> exception. The canonical `MemoryWriter` fake in `ai_assistant.testing` computes
> it too, and the shared `MemoryWriter` conformance suite gains cases for the
> permitted fold and for the refusals it does not disturb.

> **Normative.** No subsystem outside `memory` performs the test. `learning`,
> `orchestration` and `interfaces` propose and consume exactly as they do today,
> and no Protocol signature, DTO or engine method changes.

The duplication between the policy and the writer is required rather than
tolerated, and it is the same duplication ADR-0038 §2a already imposed: "a policy
reaches `MemoryIngestor` through an injected seam", so a safety property must
hold at the boundary that performs the write, not at the one that recommends it.
The duplication into `ai_assistant.testing` is golden rule 1's — the fake may not
import `memory` — and is why the predicate is stated normatively here rather than
left to one implementation to define.

**Putting the test in `learning` was considered and is refused.** The direct
seams could compare a proposal against what they last stored and decline to
propose at all. That moves a memory rule out of `memory`, gives `observe` and
`learn` two different answers to the same question, and makes the write path's
guarantee depend on every caller's diligence — and it would produce no trace at
all, so ADR-0120 §6's numerator would stay empty by a different route.

### 7. What this does to the three measures, and what it does not

> **Normative.** This ADR adds no metric key, changes no metric key's meaning,
> and requires no emitter to carry a quantity it does not carry today. Every
> definition in ADR-0120 §2, §5 and §6 stands verbatim and is computed over the
> same keys.

What changes is which events occur, which is the point.

- **ADR-0120 §6's numerator gains a producer.** A direct restatement now rules
  `REINFORCE` and is counted, so the repeated-explanation rate measures a
  population that can be non-empty.
- **ADR-0120 §5's correction rate stops counting agreement as correction**, for
  `OBSERVED` and `INFERRED` targets. The beliefs-per-correction diagnostic moves
  with it and in the same direction.
- **The rate is a lower bound and the report says so.** §1's predicate sees exact
  restatement and not paraphrase, so a user who repeats themselves in different
  words is not counted. This is a stated limit of the instrument, in ADR-0120
  §11's sense, and it is a **floor**: the true rate is at least the reported one.

> **Normative.** The report labels the repeated-explanation rate as a lower
> bound, naming that agreement is judged by exact restatement and that a
> paraphrase is not counted.

- **`EXTERNAL` agreement still counts as a correction** (§3), and is filed.
- **The series has a discontinuity at this change**, and it is not one ADR-0120
  §8 partitions on: §8 partitions a window at a `CONFIGURATION` trace diff, and a
  policy change emits none. Correction rates and repeated-explanation rates
  computed across a window spanning this change are not comparable with each
  other. #829's baseline window has not opened, and #865 already sequences it
  after this ADR's implementation lands, so on the intended timeline no ratified
  baseline spans the change. No amendment to §8 is proposed: partitioning on
  arbitrary code changes is not something the trace stream can see, and inventing
  a marker for it is a bigger decision than this one (§11).

### 8. No `MemoryDecisionKind` member, and no new metric key

> **Normative.** This ADR adds no member to `MemoryDecisionKind`, no member to
> `TraceKind`, `TraceOutcome`, `TraceRef` or `TraceRecordSet`, and no metric key.
> ADR-0119 §13e's gate is not reached and ADR-0120 §2's all-six eligibility rule
> is untouched.

A seventh ruling kind — "agrees, adds nothing" — is the design this ADR most
obviously might have taken, and it is refused on three grounds, in increasing
order of weight.

`MemoryDecisionKind.REINFORCE` **already means this**. Its ratified definition is
"the incoming record agrees with the target and strengthens it" (ADR-0040 §1),
and ADR-0040 §1's naming rule is that "the member names the relation, not the
mechanism". An agreeing restatement is that relation. A new member would name the
same relation twice and would be the mislabelling ADR-0040 §1 exists to prevent.

A member is a `core/types.py` change under golden rule 5, needing its own
ratified ADR merged ahead of any implementation — and it would arrive with a
seventh `decisions_*` key, which would make every trace from the new emitter a
**strict, non-empty subset of the six** and therefore *malformed* under ADR-0120
§2's eligibility rule, entering no population at all. Every measure ADR-0120
ratified would silently read zero against the new emitter until §2 and ADR-0119's
per-kind key roster were amended together. That is a large, coupled change bought
for a distinction the existing vocabulary already draws.

And the distinction it would buy is not one the measures need. ADR-0120 §5 and §6
divide the six counts between "overturned" and "agreed"; agreement is one bucket
in both.

### 9. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made here, clause by clause, so a
reviewer can check it against the quoted text and require a record added or
removed by naming the sentence that does or does not become false or over-wide.

**ADR-0050 §2 — partially superseded.** Its rule is "if a user-asserted proposal
conflicts with any existing `USER_ASSERTED` record, rule `ASK_USER`", stated
unconditionally over the conflict set and positioned first. A reader holding only
ADR-0050 defers where this ADR reinforces, so they act differently: this changes
what was decided, and ADR-0070 §1 makes that a supersession rather than an
amendment. It is **partial** and narrow — §2's rule stands whole for every
conflict set holding an asserted member that *disagrees* with the proposal, which
is the #245 case §2 was written for, and every word of §1 and of §2's
recency-precedence and `ASK_USER`-writes-nothing clauses is untouched. What is
replaced is §2's scope over conflict sets whose asserted members all agree.
§2's sentence that "both live" is "a correctness defect, not a benign restatement
to be tolerated" stays true and is not the sentence being narrowed: it is about
two *contradictory* assertions both standing live, which the second condition of
§2 above still prevents.

**ADR-0045 §5 clause 1 — amended**, in the scope of §5's exception and no wider.
Clause 1's text is unconditional over rulings, so it becomes over-wide; its two
stated justifications are both about a fold that replaces or retires the user's
record and neither becomes false, because neither describes the permitted fold.
This is the shape ADR-0078 §5b's confirmation exception took against the same
clause, recorded there as an amendment naming its exact scope, and this ADR
follows that precedent deliberately rather than by default. ADR-0045's `Status`
line leads with `Partially superseded by`, so under ADR-0082 §2 the record goes
in the appended dated note alone.

**ADR-0038 §2a — amended**, in the same scope. §2a's first fold refusal — "**any**
fold onto a `USER_ASSERTED` target, whatever the proposal's source" — becomes
over-wide by the same exception. §2a's second refusal, its allow-list *shape*,
its keyed-on-the-records argument and its enforced-at-the-ingestor rule all stand;
§5's exception is verified at the ingestor precisely because §2a requires it.

**ADR-0040 §5b — amended.** Its conformance predicate is stated in terms so it
"cannot be paraphrased into something broader" — "must raise `MemoryStoreError`
and write nothing when `target.provenance.source is USER_ASSERTED`, **or** when
`incoming.provenance.source is USER_ASSERTED` **and**
`target.provenance.source is EXTERNAL`". The first disjunct becomes over-wide,
and a suite pinning it as written would now refuse a fold this ADR permits — the
contract-widening mistake §5b itself names. The second disjunct is untouched, as
is §5b's argument that the refusals are contract rather than tuning.

**ADR-0092 §5 — amended.** §5 names the reinforce-safe class as "`{OBSERVED,
INFERRED}`, unchanged", and that sentence stops being true of the tree. Its
*reason* is what this ADR keeps: the class still means "does not carry a foreign
idempotency key", `EXTERNAL` still fails that test and stays out, and the two
sets stay two. §4's "the `EXTERNAL` `REINFORCE` refusal stands" is untouched, and
so is §5's warning against tidying the constants back into one.

**ADR-0120 — nothing, and this is not an oversight.** Every normative clause of
§2, §5 and §6 stays literally true and computable; the measures are defined over
metric keys and this ADR adds none, removes none and redefines none. What changes
is the *frequency* of events the keys count, which is the world moving, not the
ADR becoming wrong — and §6's own reasoning, "`REINFORCE` agrees" and "A direct
user act that produces a reinforcement is the user supplying a belief the system
already held", becomes true of the tree where it was previously vacuous. That is
the opposite of the direction ADR-0082 §1's test names, so no `Status` qualifier
is owed. A **dated note** is nevertheless appended to ADR-0120, which ADR-0070 §1
permits unconditionally, recording that §6's "the cost is a small population" was
not true of the tree when written and that §7 above states the series
discontinuity — a future reader of §6 needs both facts and can get them nowhere
else.

**ADR-0103 §6 — nothing.** §4's second clause applies §6's rule to a second
pairing. §6's own clause is about a `DERIVED` proposal onto an `ATTESTED` target
and is unchanged in scope, wording and effect; nothing it says becomes false or
over-wide. This is ADR-0082 §1's stacked addition, recorded here and nowhere
else.

**ADR-0119 — nothing.** §8's per-kind key obligation and §13e's vocabulary gate
are both untouched (§8 above).

**ADR-0040 §7 and ADR-0045 §7 — discharged, not amended.** Each filed the
question this ADR answers and named the policy lane as where it would be
answered. A deferral discharged by the lane it named is the mechanism working
(ADR-0102 §13), and the appended notes record the discharge.

All of these edits land in **this ADR's PR**, so no `Status` line or note ever
names an ADR that does not exist.

### 10. What the implementing lane owes

The implementing lane is `memory` plus `ai_assistant.testing` plus their tests,
and it is one subsystem's change.

- `DefaultMemoryPolicy`: the agreement arm of §2, ahead of the two conflict arms,
  with the class docstring's numbered rules renumbered to match.
- `MemoryIngestor`: §5's verified exception in `_refuse_unsafe_fold`, the
  reinforce-safe class widened per §5, and §4's second clause in the fold — which
  is the corroboration-shaped arm, selected by the pairing rather than by the
  ruling's word.
- `ai_assistant.testing`'s canonical `MemoryWriter` fake: the same exception and
  the same fold, duplicated rather than imported (golden rule 1).
- The shared `MemoryWriter` conformance suite: the permitted fold, the refusal of
  a fold whose predicate does not hold, and — pinned, because it is the case a
  later tidy-up breaks — the standing refusal of a `USER_ASSERTED` `REINFORCE`
  onto an `EXTERNAL` target.
- Tests that pin the three live cases from #862 by their observed shapes: verbatim
  self-restatement rules `REINFORCE` and does not ask; a restatement agreeing with
  an `OBSERVED` conflict rules `REINFORCE` and does not retire it; and a
  restatement whose conflict set holds a *disagreeing* prior assertion still rules
  `ASK_USER`.
- No change to `core/protocols.py`, `core/types.py`, `learning/`, `orchestration/`
  or `interfaces/`.

### 11. What this ADR does not decide

- **Paraphrase.** Whether a model-judged agreement test belongs on the ingest
  path, and what it would cost (§1). Filed.
- **A non-asserted proposal that agrees with a user assertion.** An observation
  restating what the user told us still rules `ASK_USER` under rule 5. The
  ordinary fold arm would take the incoming record's source and *demote* the
  assertion to an observation, so fixing it means extending ADR-0103 §6's
  corroboration rule again, on a path ADR-0120 §6 excludes from its measure
  anyway. Out of scope and filed.
- **The `EXTERNAL` agreement residue** (§3, §7). Filed.
- **A marker for a policy change in the trace stream** (§7). Not proposed; naming
  it properly is a decision about what the stream is for.
- **Whether a multi-member agreeing set should fold more than once.** The arm
  names one target and leaves any second agreeing member live — the duplication
  residue ADR-0092 §7 already names, reached here by a rarer path. Filed.
- **The cross-kind reach of a correction (#864).** A separate lane, with its own
  ADR in flight in the same batch (#865). This ADR neither depends on it nor
  constrains it: the agreement test reads `kind` and requires equality, and the
  conflict probe that supplies the candidates is kind-scoped either way.

## Consequences

- **A user who repeats themselves is no longer interrogated about it**, and no
  longer accumulates duplicates for it. This is the product consequence and it is
  the reason to act; the measure is how we noticed.
- **ADR-0120 §6's rate becomes an instrument.** It was a well-defined rate over an
  empty numerator; it is now a floor on a real quantity. The report has to say
  "floor", which is a permanent honesty cost of §1's narrow predicate.
- **ADR-0120 §5's correction rate gets more faithful and will read lower**, and
  the two figures are not comparable across this change (§7). Anyone reading a
  window spanning it must partition by hand.
- **Clause 1 has two exceptions now, and a third would be a pattern.** ADR-0078
  §5b's and this one. Both are verified at the writer and both are keyed on facts
  that make clause 1's own justifications inapplicable, which is the test a third
  would have to meet. A clause with a list of exceptions nobody can state from
  memory is the failure mode to watch for.
- **The reinforce-safe class now has three members and one exclusion**, and the
  exclusion carries the whole of ADR-0092 §5's argument. The tidy-up hazard
  ADR-0092 §5 named gets slightly worse, and the conformance case it named is what
  continues to stop it.
- **A restatement now refreshes currency** (ADR-0103 §3, ADR-0109 §5), where
  before it produced a question, a duplicate or a retirement. Beliefs the user
  repeats will age more slowly than beliefs they do not, which is the behaviour
  ADR-0103 intended and has not until now been reachable from a direct seam.
- **Revisit when** a model-judged agreement test is on the table (§1), or when the
  reported repeated-explanation rate is high enough that the gap between exact
  restatement and paraphrase becomes the dominant uncertainty in it.

## Alternatives considered

- **Raise the conflict threshold and read agreement off the score.** Rejected in
  §1: the score's own ordering puts a one-token contradiction at the top, so a
  false agreement folds a correction into what it corrects. No threshold value
  fixes it.
- **Add a seventh `MemoryDecisionKind`.** Rejected in §8: `REINFORCE` already
  names this relation, and the addition would make every trace from the new
  emitter malformed under ADR-0120 §2 until that clause and ADR-0119's key roster
  were amended with it.
- **Rule `REJECT` for a restatement of a standing assertion.** It writes nothing,
  creates no duplicate and needs no writer-floor change — the cheapest design
  here. Rejected because it throws away the one thing a restatement actually
  supplies (currency, ADR-0103 §3), and because `REJECT` means the policy declined
  a proposal for want of warrant, so using it for a proposal that is true and
  already held is the mislabelling ADR-0040 §1 forbids. It would also leave
  ADR-0120 §6's numerator empty, by a third route.
- **Rule `ACCEPT` and let the duplicate stand**, i.e. ADR-0038 §5's "accept
  beside" for the agreeing case. Rejected: it is the behaviour #862 observed
  producing three near-identical records in one run, and ADR-0092 §7 already names
  duplication as a residue to shrink rather than a resting place.
- **Perform the test in `learning` and decline to propose.** Rejected in §6: it
  moves a memory rule out of `memory`, splits the answer across callers, and
  produces no trace.
- **Leave clause 1 alone and fix only the `OBSERVED`/`INFERRED` case.** This is
  the fix #863's closing sentence proposes, and it is a real subset — it needs no
  writer-floor change at all. Rejected because the `USER_ASSERTED` target is the
  *common* case of a user repeating themselves and is the one #862 observed three
  times out of three, and because leaving it would keep the false contradiction
  question, which is the harm the user actually feels.
