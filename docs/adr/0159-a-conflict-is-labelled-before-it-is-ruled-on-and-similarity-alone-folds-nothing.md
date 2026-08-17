# 159. A conflict is labelled before it is ruled on, and similarity alone folds nothing

- Status: Partially superseded by ADR-0161 (of §4, §4(a) whole — its target class, its target selection and the reach of its `CONTRADICTS` purity condition — and the paragraph excluding `EXTERNAL` from both target classes, each only as it reaches a proposal whose own `provenance.source` is `EXTERNAL`; of §6, the members its degraded floor may name as a target, for every non-asserted proposal)
- Date: 2026-08-16
- **Partially superseded: 2026-08-16 by
  [ADR-0161](0161-an-attested-re-read-restates-its-own-import-and-folds-at-an-id-that-is-ours.md),
  in the scope the `Status` line names — an `EXTERNAL` proposal that **agrees**
  with its own stored `EXTERNAL` predecessor is folded, not accepted beside it.**
  §4's exclusion imports ADR-0121 §3's argument, whose premise is that "an imported
  record's id is the integrating system's idempotency key, and the next routine sync
  overwrites the fold". ADR-0092 §6 forbids that premise for every conforming
  producer — the producer mints an id "opaque to the source", and "minting removes
  the aim" — so on this tree the next sync never computes the target's id and the
  fold is not overwritten. Left standing, §4 defeated ADR-0110 §4's presence rule
  for every attested reader: an unchanged scheduled read proposed at a fresh id,
  ruled `ACCEPT`, and left its own predecessor absent from a reading that reported
  it, so the coverage close retired it. ADR-0161 §1 replaces §4(a) with an
  eligibility clause admitting an `EXTERNAL` target where the proposal is itself
  `EXTERNAL`, the two agree under ADR-0121 §1, and both name the same
  `Attestation.reported_by`. It gives that member precedence over any other eligible
  member, and lifts §4(a)'s `CONTRADICTS` purity condition from it alone — on this
  pairing the block leaves the contradiction as live as the fold does, and
  additionally duplicates a fact and retires a record under a covered reading
  (ADR-0161 §1). Found by this ADR's own implementation lane (PR #1197) and filed as
  #1198.

  **§6 moves in the same scope, and it moves as a supersession rather than an
  amendment.** §6's normative clause is "rules `REINFORCE` onto a member that
  `agrees` under ADR-0121 §1", and it states no target class; read as its own text
  rather than as a pointer to §4(a), it admits an agreeing `EXTERNAL` member that
  §4(a) refuses on the reconciled path, so the degraded path would fold where the
  reconciled one would not — below the floor §6's own heading says it never goes
  below. Two rulings change against §6's text — that one, and an `OBSERVED` or
  `INFERRED` proposal agreeing with an `EXTERNAL` member, which §6's text folds and
  ADR-0161 §1 rules `ACCEPT` (§4(a)'s exclusion holding as ratified, now written
  down where an implementer builds from it) — so the §6 half of the scope is stated
  over every non-asserted proposal, and ADR-0070 §1 makes it a supersession however
  narrow.
  **What §6 decided is untouched:** failure and absence degrade to ADR-0121 §1's
  certain predicate plus `ACCEPT`, as a ratified deployment rather than a fallback,
  and never below it — and an agreeing `OBSERVED` or `INFERRED` member folds in the
  degraded case exactly as it does today. Only the target set moves, by clause (ii)
  and by nothing else. ADR-0161 §4 and §8 carry the reasoning.

  **Nothing else moves.** §4(b) is untouched — `EXTERNAL` names no supersession
  target, its own purity condition binds unchanged, and an `EXTERNAL` member counts
  in both conditions as any other member does — as are §4(c), the `ASK_USER`
  precedence, the non-empty-set `ACCEPT` reason, §1's relations, §2's siting and
  invocation condition, §3's rungs and bounds, §5's retirement exclusion and its
  last clause, §6's degradation ruling, §8's whole contract surface including its
  conformance clause, §9's measures, §10's one-lane ruling, §11's record and §12's
  dispositions. ADR-0161 §8 applies ADR-0082 §1's test clause by clause and states
  why the scope is drawn here; its §7 argues why this is a supersession rather than
  an in-place amendment.

  **Recorded now rather than at ADR-0161's ratification**, per ADR-0082 §7:
  ADR-0070 §1's condition is that the superseding ADR **exists**, and it lands in
  this same change, so the reference resolves.
- **This is a contract change under golden rule 5.** `MemoryPolicy.decide` gains a
  keyword-only parameter and `core/types.py` gains one enum (§8). It also narrows a
  ratified `MemoryWriter` conformance obligation — ADR-0079 §3's full-set retirement
  — so it ships as its own `Proposed` PR and carries **both** review lenses, per
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation".
- **This ADR answers the question**
  [ADR-0040](0040-reinforcement-and-supersession-are-different-rulings.md) §7 filed —
  "**Whether `DefaultMemoryPolicy` rule 5 should supersede** in some cases (§4).
  Filed as an issue on ratification; it is a policy-lane question that this
  vocabulary makes askable" — and is the "different ADR with a different blast
  radius" [ADR-0121](0121-an-agreeing-restatement-is-ruled-agreement-not-conflict.md)
  §1 named when it refused a model-judged test "here, not forever".
- **This ADR amends** ADR-0040 §4 (its description of rule 5's ruling) and
  **partially supersedes** [ADR-0050](0050-resolving-the-full-contradiction-set.md)
  §1 and [ADR-0079](0079-a-correction-resolves-every-conflict-it-is-shown.md) §3, in
  the scope named in §11, which applies ADR-0082 §1's test to each and to every ADR
  a record might look owed on.
- Refs #1188, #1029. Disposes #868, #869, #871, #1169 and #743 in §12, each by name.

## Context

### The pilot measured a rule folding half of everything it saw

The pilot-3 error anatomy (#1029, run `8a8f7a033b3c`, seven LoCoMo conversations)
read the `memory_write` traces across the seven stores: **765 proposals → 380
`ACCEPT`, 385 `REINFORCE`, 0 `REJECT`, 0 `SUPERSEDE`.** Half of every proposal the
observer made was folded into a record that already existed. One belief
("Caroline is transgender; …") absorbed thirteen proposals.

The folds were not restatements. Distinct surviving facts sit at cosine 0.77–0.80
against each other — "Jon lost his job shortly before 21 June 2023 …" against "Jon
took a temporary job around mid-July 2023 …" at 0.77; "Melanie has children whom
she takes to parks" against "Melanie has multiple children, including …" at 0.79.
The conflict probe's threshold is 0.75, so the population it captures is routinely
*different facts about the same person*, and `MemoryIngestor`'s fold keeps one
content. Every such fold destroys a distinct fact, old or new.

The downstream reading is the one that makes this urgent. Accuracy when only a
belief citing the gold turn reached the answering prompt was **36.6%**, against
78–81% when the raw episode did; 37% of gold turns are cited by no belief at all;
and enumerable questions come back truncated — "Which cities has John been to?" →
"Seattle" — which is what a store of folded lists looks like from the outside.
[ADR-0158](0158-an-episode-may-supplement-the-answering-prompt-and-never-shares-the-belief-budget.md)
supplements the prompt with episodes to route *around* this loss; this ADR is
about not causing it.

### The rule, exactly as it stands

`DefaultMemoryPolicy._rule_on_conflicts` in `memory/policy.py`, for a proposal
whose `provenance.source` is not `USER_ASSERTED`:

- if any conflict is `USER_ASSERTED` → `ASK_USER`, "conflicts with a user-asserted
  memory";
- otherwise, if the conflict set is non-empty → `REINFORCE` at `conflicts[0]`,
  "updates an existing memory";
- otherwise, below `min_confidence` → `STORE_TEMPORARY`; else `ACCEPT`.

Two details matter and neither is what a reader assumes. The threshold is
`memory/ingest.py`'s `_DEFAULT_CONFLICT_THRESHOLD = 0.75`, not the policy's — the
policy holds no threshold at all and reads no score. And ADR-0121 §1's agreement
predicate, `memory/_agreement.py`'s `agrees`, is **not consulted on this path**:
`_rule_on_agreement` is reached only from `_rule_on_assertion`, which runs only for
a `USER_ASSERTED` proposal. So on the observed path nothing has ever checked
whether the two records say the same thing. The target is `conflicts[0]` — the
best-ranked record, which is a *similarity* ranking, chosen without reading the
proposal at all.

### The corpus already knew, and said so

This is not a defect nobody noticed. ADR-0040 §4 labelled the ruling and
immediately disowned the label:

> Rule 5 is the uncomfortable one and we are labelling it honestly rather than
> quietly. Those records were paired because they are *topically similar*, which
> ADR-0038 §2 is explicit is not contradiction; calling the ruling `REINFORCE`
> asserts they agree, and sometimes they will not. That mislabelling is not created
> here — `_merge`'s union-and-maximise has been rule 5's behaviour since ADR-0005,
> and this ADR only makes it legible. Whether rule 5 should sometimes supersede is
> a question about `DefaultMemoryPolicy`'s reasoning, decidable in the policy lane
> once the vocabulary exists, and it is filed rather than answered here (§7).

The vocabulary arrived with ADR-0040. The policy lane never came. What #1188
contributes is not the observation but the *rate*: "sometimes they will not" is
half.

### Why nothing in the corpus could fix it, and what was missing

Three ratified sentences fence the ground, and together they leave exactly one
gap.

- **ADR-0038 §2 / ADR-0045 §5: topical similarity is not contradiction.** A 0.75
  score is "too weak to authorise retiring a record", which is why there has never
  been a supersession path for a non-asserted proposal — `_rule_on_assertion` is
  the only caller of the supersession arm, and it runs only for an assertion.
- **ADR-0121 §1: similarity is not agreement either**, and cannot be made into it
  by raising the threshold, because "the two strings that score *highest* against
  'I prefer window seats' include 'I prefer aisle seats'". Its answer was a
  syntactic predicate that is *certain* where it fires and silent everywhere else.
- **ADR-0121 §1 again: the certain predicate is narrow on purpose.** "'The user
  said the same thing in different words' is a real and larger population than
  exact restatement, and only a language model can see it."

So the conflict set arrives at the policy carrying a *score* and nothing else, and
the corpus has ruled that the score authorises neither of the two things the policy
might do with it. The rule folds anyway, because a fold was the only arm available.
What is missing is not a better threshold and not a wider predicate. It is a
**relation**: a statement about how the proposal stands to a *named* record, made
by something entitled to make it, arriving as data the policy can read.

### What ADR-0121 §1 refused, and why this is the ADR it named

> **A model-judged entailment test is refused here, not forever.** … Admitting one
> would put a `ModelProvider` behind `MemoryPolicy.decide` — a new injected
> dependency on the ingest path, a non-deterministic ruling, a network call inside
> a write, and a Protocol change. Each of those is arguable; together they are a
> different ADR with a different blast radius, and the narrow predicate is
> available now and strictly better than nothing.

That refusal is prose, not a marked clause, and it is explicitly a deferral rather
than a prohibition. This ADR is the different ADR. It does not relitigate ADR-0121:
`agrees` is unchanged, its two normative clauses in §1 stay true word for word, and
§6's "no subsystem outside `memory` performs the test" is honoured rather than
routed around. §7 below takes the four grounds one at a time and says which are
incurred, which is not, and what is paid for each.

ADR-0121 §6 also closes the obvious escape, and it is worth quoting because the
shape it refuses is the shape a reader will reach for first:

> **Putting the test in `learning` was considered and is refused.** The direct seams
> could compare a proposal against what they last stored and decline to propose at
> all. That moves a memory rule out of `memory`, gives `observe` and `learn` two
> different answers to the same question, and makes the write path's guarantee
> depend on every caller's diligence — and it would produce no trace at all.

All four reasons survive intact and all four bear on a reconciler. §2 sites it
where they do not bite.

## Decision

### 1. A conflict carries a relation, and the relation is what a fold rests on

> **Normative.** A **conflict relation** is a statement about how a proposed record
> stands to one named record of the conflict set, and is one of exactly three
> values: `RESTATES` — the proposed record says what the named record already says;
> `ADDS` — the proposed record says something the named record does not say and
> does not deny; `CONTRADICTS` — the proposed record and the named record cannot
> both be true of the same subject at the same time.

> **Normative.** A conflict-set member for which no relation was determined is
> **unlabelled**. Unlabelled is not a fourth relation and is never asserted: it
> records that nothing was determined, and every rule below treats it as supplying
> no ground for anything.

> **Normative.** A relation is a property of the two records' `kind` and `content`
> and of nothing else. No relation is derived from a retrieval score, a rank, a
> `Provenance` field, a band, a validity window or an embedding distance. A relation
> derived from any of those is not one, whatever it is called.

The three values are chosen so that the second is the one that carries the pilot's
whole finding. "Jon lost his job shortly before 21 June 2023" and "Jon took a
temporary job around mid-July 2023" score 0.77 and are `ADDS` — two true facts, in
sequence, about one person. The rule that was fired on them was designed for
`RESTATES` and the rule that a reader might reach for next is `CONTRADICTS`, and
both are wrong. Naming `ADDS` explicitly is what lets the policy do the correct
thing with them, which is nothing at all.

**Relations are not `MemoryDecisionKind` and do not become one.** ADR-0040 §1 fixed
that a ruling "names the relation the policy asserts, never the write it causes",
and this vocabulary sits one layer below that: a relation is an *input* to choosing
a ruling, made about a pair of records before any ruling exists. Two proposals with
identical relations may still be ruled differently — by confidence, by the taint
ceiling, by the secret gate — so collapsing the two vocabularies would lose the
distinction between what is true of the records and what we have decided to do.

### 2. The reconciler is `memory`'s, and it runs before the ruling, not inside it

> **Normative.** Conflict relations are determined by a **reconciler**: a component
> of the `memory` subsystem, held by `MemoryIngestor`, invoked after the conflict
> probe has resolved the conflict set and before `MemoryPolicy.decide` is called.
> The relations it returns are passed to `decide` as an argument (§8).

> **Normative.** A reconciler is invoked **exactly when** all three hold: the
> proposed record's `provenance.source` is not `USER_ASSERTED`; no member of the
> conflict set is `USER_ASSERTED`; and the proposal clears the **admissibility
> floor** — it is not `DataTier.SECRET`, it is not a derived belief citing no
> evidence, and its warrant does not rest on unconfirmed recorded external content.
> On every other ingest none is invoked, no relation is computed, no model request
> is made, and `decide` is called with none.

> **Normative.** The floor named above is `_rule_on_admissibility`'s rulings read as
> properties of the proposal alone, and this exclusion **tracks** that floor rather
> than restating it: a ruling later added to the floor excludes its population here
> too, without amending this ADR. It binds `MemoryIngestor` whatever `MemoryPolicy`
> it holds — it is not a prediction about how a policy will rule, and an injected
> policy carrying no such floor does not lift it.

**The admissibility floor is in the invocation condition because the ruling is too
late.** ADR-0078 §5a states that the floor's rulings "precede any conflict
reasoning", and a relation *is* conflict reasoning — it is a statement about the
proposal against a named member of the conflict set. `_rule_on_admissibility` runs
*inside* `decide`, so a reconciler sited before `decide` on §2's other two
conditions alone would run ahead of it. For two of the floor's populations that
costs a model request on a proposal about to be rejected or deferred. For the third
it is not recoverable at all: a `DataTier.SECRET` proposal whose conflict set holds
no assertion would put tier-0 content into a model request before the gate ADR-0004
§3 exists to enforce had run, and the `ASK_USER` that follows recalls nothing. The
exclusion therefore sits where the invocation decision is made, in `MemoryIngestor`,
rather than in a policy that runs after the request has gone. It is stated over the
whole floor and not over the secret rule alone for ADR-0078 §5a's own reason — "a
floor that holds only while a coincidence holds is not a floor".

The invocation condition is normative rather than left to a reconciler's own
economics, because it is a **correctness boundary and not a cost heuristic**. The
two `USER_ASSERTED` populations it excludes are already owned: a `USER_ASSERTED`
proposal is ADR-0121 §2's arm, and a conflict set holding one is the
`ASK_USER` arm §4 leaves untouched. Neither reads a relation, so computing one there
would buy nothing and would spend a model request inside the ingest lock on the two
paths a user waits on — the `learn` and `answer` direct seams, whose proposals are
asserted. What is left to the reconciler's own economics is only whether a request
is worth making about the members the `agrees` rung did not settle (§3), which is
the decision that is unobservable in the ruling.

> **Normative.** No implementation of `MemoryPolicy` consults a `ModelProvider`, a
> `BatchCompleter`, a store, a clock or a network. `decide` returns the same ruling
> for the same `proposal`, the same `conflicts` and the same relations, and every
> input its ruling depends on is an argument or a construction-time property of the
> implementation.

> **Normative.** The **reconciler** is a `memory`-internal seam. No Protocol for it
> is added to `core/protocols.py`; no subsystem outside `memory` holds one,
> constructs one or invokes one; and no component outside `memory` determines a
> relation. `learning`, `orchestration` and `interfaces` propose and consume exactly
> as they do today.

> **Normative.** The **relations** are not internal. They are contract data at the
> existing `MemoryPolicy` seam, so *every* implementation of `MemoryPolicy` receives
> them, wherever it lives, and `MemoryIngestor` passes them to whatever policy it
> was injected with without branching on which one that is.

The two clauses draw one line and it is worth naming, because collapsing them is the
easy mistake: what stays inside `memory` is the machinery that *makes* a relation,
not the value it makes. A `MemoryPolicy` implementation may live anywhere — that is
what the injected seam is for, and ADR-0040 §3 is explicit that "the ingestor takes
rulings from *any* injected `MemoryPolicy`" — so an argument to `decide` reaches
outside `memory` by construction. A boundary that tried to withhold it from a
foreign policy would have to test which implementation it held, which is exactly the
dependency-inversion failure golden rule 1 exists to prevent. What no foreign
component may do is *determine* a relation, and that is what §2's first clause and
§3's rungs bind.

**Nothing in the tree implements `MemoryPolicy` outside `memory` today**, and that
is a fact about the tree rather than a property of the contract: `learning` and
`orchestration` reach the write path through `MemoryWriter`, which "holds its own
`MemoryPolicy` and its own store, and exposes neither".

**Why not inside `decide`.** ADR-0005 §3 is the sentence the whole corpus cites —
"a **deterministic** `MemoryPolicy` decides the outcome" — and it is the property
worth keeping. A policy that awaits a model is not testable by enumeration, not
explainable to the user whose belief it destroyed, and not runnable when no provider
is reachable. `NotificationPolicy`'s ratified contract already states the standard
in these terms and cites this very method as the shape it copies: "The method is
`async` mirroring `MemoryPolicy.decide`, and an implementation that awaits anything
outside its arguments has already broken the clause above" (ADR-0130 §11). This ADR
makes that standard explicit for `MemoryPolicy` rather than weakening it, and buys
the model's judgement without spending it.

**Why not in `learning` or `orchestration`.** ADR-0121 §6's four reasons apply
unchanged and are decisive. A reconciler in `learning` would move a memory rule out
of `memory`; would give the `observe`, `learn` and `answer` seams three different
answers to one question; would make the write path's guarantee depend on every
caller's diligence, which ADR-0038 §2a already ruled is not where a safety property
may live; and would sit on the wrong side of the conflict probe, which runs inside
`MemoryIngestor` and is where the candidates come from. That last one is not a
preference: `learning` has no conflict set to label.

**Why `memory` may hold a `ModelProvider`.** Nothing forbids it. Egress is a rule
about which package opens the socket — ADR-0017 §1 permits it "from `models/` or
from a designated integration seam inside `tools/`", ADR-0154 §2 states in terms
that "no lane cites this ADR toward a change to `models/`", and the import-linter
contract confining network transports names only `ai_assistant.tools.*`. A caller
holding the `ModelProvider` Protocol is not itself an egress boundary; `models/` is.
`memory` importing `core.protocols.ModelProvider` is precisely the sanctioned form,
and `lint-imports` passes it today.

**What ADR-0155 §3 makes of the reconciler's output, and it is not one answer.**
Every relation is covered content: it is the output of an operation supplied the
stored conflict records. But §3's classification is "three-valued at every supply:
covered with a model call on the path, covered with none, or not covered", and a
reconciler produces relations in **two** of those classes, not one.

- A relation the model labelled has a model call on every covered path, so §3's
  *third* clause governs its reaching an egress span.
- A relation the `agrees` rung labelled (§3) has a covered path with **no** model
  call — the rung is a string comparison over stored records and nothing else — so
  §3's *second* clause governs it, which is the absolute prohibition no
  authorisation cures.

Recording the two as one would put a syntactically-derived relation on the softer
branch, and a later relaxation of that branch — which §3's third clause explicitly
reserves to an owner ruling and a commissioned ADR — would then externalise a value
derived from the store by no model at all. That is the direction §3 exists to
forbid, so the distinction is written down here rather than left for the lane that
would get it wrong.

It bears on nothing this ADR does, and the reason is **not** that a relation stays
inside `memory` — §2's second clause hands it to every `MemoryPolicy`
implementation, wherever that lives. The reason is that both clauses are stated over
"a span of an egress call at the designated `tools/` egress seam", and no path this
ADR opens reaches one: the reconciler writes its relations to the ingestor, the
ingestor passes them to `decide`, and a `MemoryPolicy` may consult no network at all
(§2). A relation reaching an egress span would take a component this ADR does not
create, doing something §2 forbids the one recipient it names.

**Why not the bulk seam.** ADR-0143 §8 rules that "no subsystem is given a
`BatchCompleter` by this ADR" and that "a batch runs in the process that submits it
and never in the hub". An ingest-time reconciler runs in the hub. The bulk seam is
not available and is not sought.

### 3. What the reconciler answers, what it may spend, and what it may not do

> **Normative.** A conflict-set member that **agrees** with the proposed record
> under ADR-0121 §1 is labelled `RESTATES`, always, with no model call. That
> predicate is the reconciler's first rung and it is unconditional: a reconciler
> that reaches a different answer on a pair `agrees` admits is not conforming.

> **Normative.** A reconciler consults a model only for members the rung above did
> not label, and only for the **first `reconciler_max_conflicts` members of the
> conflict set in rank order**. `Settings` gains `reconciler_max_conflicts: int`,
> positive, defaulting to **3**. Members beyond that bound are left unlabelled.

> **Normative.** A reconciler installs a model-supplied label only for a member it
> **consulted the model about**. A label the reply carries for any other record —
> including a member of the conflict set that fell beyond the bound, and including
> one the `agrees` rung already labelled — is discarded, and that member stays as
> the two clauses above leave it.

> **Normative.** A reconciler names the route it calls rather than inheriting the
> default. `Settings` gains `reconciler_model`, defaulting to `None`, typed as the
> same validated `provider:model` spec `observer_model` carries (`_ModelSpec | None`
> in `core/config.py`), so a malformed route is refused at construction rather than
> at first use; `None` means the configured default route.

> **Normative.** Where both contents state an event time under ADR-0156 §2 and those
> times differ, the relation is not `CONTRADICTS` unless the two claims are
> incompatible **at one time**. Two true statements about one subject at different
> times are `ADDS`.

> **Normative.** A reconciler makes **at most one model request per ingest**,
> covering every member it consults about, and makes none where the rung above
> labelled every member it would have consulted about.

> **Normative.** A reconciler never raises and never refuses an ingest, save for the
> cancellation the clause below excepts. A model error, a timeout, an unreadable
> reply, an unroutable request or the absence of a reconciler altogether yields
> **unlabelled** for every member it could not label, and the write proceeds on the
> relations it does hold.

> **Normative.** A `CancelledError` **delivered from outside the ingest** is not
> absorbed by the clause above. It is delivered onward out of `MemoryIngestor` under
> ADR-0060 §1's second clause, never converted into an unlabelled member and never
> allowed to stand as a completed write, and the ingest lock is released as it
> unwinds. A deadline `models/` issues against its **own** request is not such a
> cancellation — it is the self-issued kind ADR-0060 §1 distinguishes, and the clause
> above classifies it into unlabelled like any other timeout.

The first clause is the whole architecture of the thing in one sentence:
**ADR-0121 §1's predicate is itself a reconciler answer.** The syntactic test and
the model call are two rungs of one ladder, not two competing designs, and putting
them behind one seam is what makes the model's contribution *additive* — it answers
only where certainty already failed, and it can never overturn a certain answer.
That is also what bounds the spend: a verbatim restatement costs nothing, and the
model is asked only about the residue that a string comparison cannot settle.

**What is left to the reconciler's own economics, once §2 has drawn the boundary.**
`MemoryIngestor` decides *whether a reconciler runs at all*, on §2's normative
condition, because that is a correctness boundary. Inside it the reconciler decides
*whether the request is worth making* — whether the `agrees` rung settled every
member within the bound, whether anything is left to ask about — and that decision
stays there because a mis-scoped one is **unobservable in the ruling**: asking about
a member the policy will not read costs money and changes no outcome, and not asking
where the policy would have read the label degrades to §6's safe default. A
reconciler cannot make a ruling wrong by getting its own economics wrong. That
asymmetry is the whole reason the two halves live in different places.

**The temporal clause is not a nicety, it is the pilot's central case.** The 0.77
pair that opens the Context is exactly two dated facts about one person's
employment, and a reconciler that reads "lost his job" against "took a temporary
job" without their anchors will call it `CONTRADICTS` and retire a true belief —
converting a fold that lost a fact into a supersession that loses a fact, which is
no improvement. ADR-0156 §2 already requires the distilled belief to state the event
time its evidence establishes, in its own `content`, and the observer already does
it. This clause is what makes that anchor load-bearing at the one seam that reads
two beliefs against each other. It also raises the stakes of #1169 (§12).

**Why a bound of three, and why `Settings` rather than a constant.** The conflict
set is already bounded by `conflict_limit` — `memory/ingest.py`'s
`_DEFAULT_CONFLICT_LIMIT` is 100, and a value below 1 is refused — so that ceiling
is nowhere near a cost bound and this one is: three is where the measured
distribution puts the records a proposal could plausibly restate or contradict, and
a fourth is nearly always a topical neighbour. It is a `Settings` field for the
reason `observation_max_proposals` is one (ADR-0077 §2) — it is a knob an operator
tunes against their own corpus, and its right value is an empirical question this
ADR does not pretend to have settled.

**The bound has a response half, and it is the half a test forgets.** Asking about
three members does not stop a reply naming a fourth, and the fourth's id is a *valid*
id — it is in the conflict set — so §8's ignore rule, which is stated over ids absent
from `conflicts`, does not reach it. Installed, a volunteered `CONTRADICTS` on a
member nobody asked about would block a fold §4(a) would otherwise make, which is the
bound failing in the one direction it exists to prevent. The clause is stated over
what the reconciler *consulted about* rather than over what the reply contains,
because that is the fact the reconciler holds and the model cannot influence.

**One request, not one per member, and the reason is not only cost.** A relation is a
statement about a pair, but the *set* is what disambiguates it: shown the three
records together, a labeller can see that two of them are a sequence and the third is
the claim being restated, where the same three judged in isolation invite three
independent guesses. Bundling them is also what makes §6's latency statement a
statement — one request under one deadline, rather than up to
`reconciler_max_conflicts` of them under `model_max_attempts` retries each.

### 4. The non-asserted arm: three outcomes, each with a purity condition

> **Normative.** For a proposal whose `provenance.source` is not `USER_ASSERTED`,
> and whose conflict set holds no `USER_ASSERTED` member, `DefaultMemoryPolicy`
> rules, in this order:
>
> **(a)** `REINFORCE`, naming as `target_id` the best-ranked member labelled
> `RESTATES` whose `provenance.source` is `OBSERVED` or `INFERRED`, exactly when
> such a member exists **and no** member is labelled `CONTRADICTS`;
>
> **(b)** otherwise `SUPERSEDE`, naming as `target_id` the best-ranked member
> labelled `CONTRADICTS` whose `provenance.source` is `OBSERVED` or `INFERRED`,
> exactly when such a member exists **and no** member is labelled `RESTATES`;
>
> **(c)** otherwise the confidence arm exactly as it stands — `STORE_TEMPORARY`
> below `min_confidence`, else `ACCEPT`.

> **Normative.** A conflict set that is non-empty reaches (c) whenever neither
> exception fires. The `ACCEPT` it produces carries a `reason` distinguishing it
> from the empty-set case, so "no conflict" and "conflicts, none restating and none
> contradicting" are legible apart in the trace stream.

> **Normative.** The arm reads relations and the members' `provenance.source`. It
> reads no retrieval score, no rank other than to break a tie among members the
> relations already selected, and no threshold. `conflicts[0]` is never the target
> by position.

> **Normative.** The `ASK_USER` ruling for a non-asserted proposal whose conflict
> set holds a `USER_ASSERTED` member is unchanged and continues to precede this
> arm. Nothing in this ADR reaches it.

**`ACCEPT` is the default and each write is the exception.** That inversion is the
substance of the change. Today a non-empty conflict set is *sufficient* for a fold;
under this arm a fold requires an affirmative, record-specific statement that the
two say the same thing, and a retirement requires an affirmative statement that they
cannot both be true. Everything else lands as its own belief, which destroys nothing
and is what the store is for. The pilot's 385 folds become, on this rule, the small
subset that a reconciler actually calls `RESTATES`.

**The purity conditions are ADR-0121 §2's second condition, read one source class
over.** ADR-0121 refuses to reinforce onto an agreeing record while a *disagreeing*
assertion sits live in the same set, because that leaves two live contradictory
records — "the honesty defect ADR-0050 §2 exists to prevent, reached by a new path".
The same hazard is here in both directions. A set holding both a `RESTATES` and a
`CONTRADICTS` member is a set in which the *stored records disagree with each
other*, and no ruling on this proposal resolves that: reinforcing one leaves the
contradiction live, superseding the other leaves the reinforced record's own
contradiction live. So neither exception fires, the proposal lands beside them, and
nothing is destroyed on the strength of a conflict the proposal did not create. It
is the conservative answer and it is deliberately not `ASK_USER` — an observation is
not something the user should be interrogated about (#869), and the question we
would be asking is about two records neither of which the user just wrote.

**Unlabelled members block nothing, and this is the right sign.** An unlabelled
member could be anything, including a contradiction. Letting it block would mean
one reconciler failure downgrades a *certain* `agrees` restatement to a duplicate,
which is a regression against ADR-0121 for no gain; letting it pass means a
`RESTATES` fold may occur while an unexamined member contradicts, which is strictly
better than today, where every member folds unexamined. The asymmetry is the
destroy-nothing rule applied twice: an unlabelled member neither authorises a write
nor withdraws one that a certain answer authorised.

**`EXTERNAL` is in neither target class, and the reason is ADR-0121 §3's, unchanged.**
A `REINFORCE` folds at the *target's* id, an imported record's id is the
integrating system's idempotency key, and the next routine sync overwrites the fold —
so a fold onto an import is futile whatever the incoming source is. A `SUPERSEDE`
onto an import is worse than futile: the sync restores the record, and a
model-judged contradiction is not a claim an observation is entitled to make against
the system that reported the fact.

**The exclusion is from the target classes and from nothing else.** An `EXTERNAL`
member is never *named* by either exception, and it counts in both purity conditions
exactly as any other member does: an `EXTERNAL` member labelled `CONTRADICTS` blocks
(a), and one labelled `RESTATES` blocks (b). That asymmetry is deliberate and it is
the conservative direction. The reason `EXTERNAL` may not be a target is about what a
*write* at an imported id would do — it is futile, and a supersession is a claim an
observation may not make. It is not a reason to disregard what the reconciler said
about the record. A proposal that contradicts an import is a contested proposal
whoever holds the import, and the ruling for a contested proposal is (c): the belief
lands beside what it contests and nothing is destroyed. ADR-0092 §4's "the user
outranks the calendar" is about a *user assertion* and is untouched — an observation
is not the user.

### 5. What a supersession on a labelled contradiction retires

> **Normative.** A conflict labelled `RESTATES` or `ADDS` is **never retired**, by
> any ruling, at any writer. It is not in the retirement set of a `SUPERSEDE`
> naming another member, and a writer that would retire it refuses the write
> instead.

> **Normative.** ADR-0079 §3's `MemoryWriter` obligation — a `SUPERSEDE` retires
> "the named `target`, plus every other conflict in the set the policy ruled on
> whose source is supersedable" — is narrowed by the clause above and is otherwise
> unchanged. Where the writer holds no relations, the obligation binds exactly as
> ADR-0079 §3 states it.

> **Normative.** The exclusion is enforced at the writer, from the writer's own
> relations, never trusted from the ruling — the boundary that performs the write,
> per ADR-0038 §2a. The canonical `MemoryWriter` fake in `ai_assistant.testing`
> carries the same seam and the same exclusion, duplicated rather than imported
> (golden rule 1), and the shared `MemoryWriter` conformance suite pins both halves:
> the `agrees` half, which every writer can compute with no model, and the `ADDS`
> half, driven by an injected stub reconciler.

> **Normative.** This ADR opens no exception to `_refuse_unsafe_fold`'s clause 1 and
> widens neither the reinforce-safe class nor the retirement class. Every write
> either arm above can ask for is one the writer floor already permits.

**The retirement set is where this rule would have destroyed most.** ADR-0050 §1
defines the set as the named target plus every supersedable conflict, on an explicit
premise: "Every entry in the conflict set the detector surfaced is a same-kind,
at-or-above-threshold contradiction of the proposal; they are all the belief being
corrected, restated." That premise is precisely what #1188 measures and refutes — at
0.75 the set is routinely a mixture of restatements, additions and contradictions.
Left standing, giving the observed path a supersession arm would have turned one
lost fact per fold into up to `conflict_limit` lost facts per correction. The
narrowing is not a refinement of ADR-0050 §1; it is the condition on which the arm
in §4(b) may exist at all.

**The last clause is what distinguishes this ADR from ADR-0121, and it is the
answer to #868's hardest question.** ADR-0121 §5 had to open a hole in
`_refuse_unsafe_fold`'s clause 1, and therefore had to require the exception be
"verified at the writer, never trusted from the ruling" — recomputing §1's predicate
at the boundary. #868 observes, correctly, that "a verified exception whose predicate
is a model call is not verifiable at the boundary in the way ADR-0038 §2a requires".
That objection is fatal to a model predicate that must *unlock* a refusal. It does
not reach this ADR, because nothing here unlocks anything. Both target classes are
`{OBSERVED, INFERRED}`; a `REINFORCE` onto them was already permitted and a
`SUPERSEDE` onto them was already permitted. The reconciler's labels only ever
*narrow* what happens: they withhold a fold the old rule performed, and they
withhold a retirement ADR-0050 §1 permitted. A safety property that can only be
tightened by an untrusted input needs no verification, and that asymmetry is why
this ADR can hold a model call where ADR-0121 could not.

### 6. Failure and absence degrade to ADR-0121's floor, and never below it

> **Normative.** With no reconciler injected, or with one whose every answer fails,
> `DefaultMemoryPolicy`'s non-asserted arm rules `REINFORCE` onto a member that
> `agrees` under ADR-0121 §1 and otherwise falls to the confidence arm. That is the
> ratified behaviour of this ADR in the degraded case, not a fallback outside it.

> **Normative.** No ingest is refused or ruled differently because a reconciler was
> unavailable, other than by the relations it therefore does not hold. An ingest
> whose reconciler makes no request is not delayed by one at all, and an ingest
> whose reconciler makes one is delayed by that request alone, under `models/`'s own
> deadline and retry budget (`model_timeout_seconds`, `model_max_attempts`).

**The request is inside `MemoryIngestor`'s lock, and that is a cost this ADR pays
knowingly rather than a consequence it overlooked.** `MemoryIngestor.ingest`
serialises "the whole sequence … on a lock held by this ingestor", because the
conflict snapshot and the write it feeds are one read-modify-write and an interleaved
pair silently discards a correction. The reconciler reads that snapshot, so it is
inside the lock by construction: moving it outside would reintroduce exactly the
lost-update race the lock closes, on a path where the discarded write may now be a
supersession. So a second ingest arriving during a reconciliation waits for it, and
the delays queue rather than overlap.

Three things bound what that costs, and none of them is a promise that it is free.
The clause above holds the per-ingest addition to **one** request. Most ingests make
none — a proposal with an empty conflict set, one whose set `agrees` settles, and
every `USER_ASSERTED` proposal, which takes the asserted path and never reaches a
reconciler at all. And the population that does make one arrives from the observation
stage, which ADR-0077 §8 already puts on a scheduled job rather than in a turn,
precisely so that a model round trip on this path is not a latency tax on the user.
An interactive `learn` or `answer` write is asserted, so it never
spends a request of its own — but it is **not** immune to the queue, and the
distinction is worth stating rather than glossing. An asserted ingest arriving while
an observed one is mid-request waits on the same lock for as long as that request
takes. What bounds it is a bound on the *other* ingest: one request, under
`model_timeout_seconds` × `model_max_attempts`. No priority or isolation scheme is
ruled here; a lock that let an asserted write overtake a reconciling one would have
to reason about whether the overtaken conflict snapshot is still good, which is the
lost-update question ADR-0038 and issue #248 already own and which this ADR is not
the place to reopen. If a deployment finds the queueing material, the answer
available to it without a new ADR is to run with no reconciler and take §6's floor.

The degraded behaviour is worth stating as a decision rather than leaving to
inference, because it is what makes the reconciler *optional machinery*. A
deployment with no provider reachable — the case ADR-0130 §11 names as "exactly
when a resident process is still noticing" — gets ADR-0121 §1's certain predicate
plus `ACCEPT`. That is strictly better than today's behaviour on the same inputs:
it folds where the two strings are identical and duplicates where they are not,
where today it folds on similarity alone. There is no configuration of this system
in which the rule this ADR replaces is the better one.

### 7. ADR-0121 §1's four grounds, one at a time

ADR-0121 §1 named four costs of admitting a model-judged test. Three are incurred
and one is not, and the corpus is owed the arithmetic rather than the conclusion.

- **"A new injected dependency on the ingest path."** Incurred, and it is
  `MemoryIngestor`'s rather than `MemoryPolicy`'s. What §6 buys is that it is an
  *optional* dependency with a ruled, safe absence, so no deployment is forced to
  acquire it and no test needs a provider to exercise the write path.
- **"A non-deterministic ruling."** **Not incurred.** `decide` remains a total
  function of its arguments (§2), and its conformance suite remains a suite over a
  function. What became model-derived is an *input* — which is the status the
  proposal itself has held since ADR-0005 §3, on the same path, from the same
  provider. Moving one more input into that class is a much smaller change than
  moving the ruling out of it, and it is the entire reason for the placement in §2.
- **"A network call inside a write."** Incurred, and bounded four ways: it fires
  only where `agrees` did not settle the member, only for the non-asserted arm, only
  for at most `reconciler_max_conflicts` members, and never on the answering turn —
  the observation stage is a scheduled job (ADR-0077 §8), and the `learn` and
  `answer` direct seams take the asserted path, which this ADR does not touch. The
  deadline and retry are `models/`'s existing ones (`model_timeout_seconds`,
  `model_max_attempts`), and §3's never-raises clause converts an exhausted one into
  an unlabelled member rather than a failed write.
- **"A Protocol change."** Incurred, and paid in the form ADR-0121 §1 anticipated:
  its own ADR, ratified and merged as its own PR before anything implements against
  it (golden rule 5, ADR-0015 §5). §8 states exactly what it is.

### 8. The contract surface this owes

> **Normative.** `core/types.py` gains one enum, `ConflictRelation`, with exactly
> the three members §1 names — `RESTATES`, `ADDS`, `CONTRADICTS`. No other type,
> field or shape in `core/types.py` changes, and no member is added to
> `MemoryDecisionKind`.

> **Normative.** `MemoryPolicy.decide`'s signature becomes exactly:
>
> `async def decide(self, proposal: MemoryUpdateProposal, *, conflicts: Sequence[MemoryRecord], relations: Mapping[str, ConflictRelation] | None = None) -> MemoryDecision`
>
> — one added keyword-only parameter named `relations`, typed
> `Mapping[str, ConflictRelation] | None`, defaulting to `None`, keyed by
> `MemoryRecord.id`. No other Protocol in `core/protocols.py` gains a member or
> changes a signature, and no other parameter of `decide` changes name, kind,
> annotation or order.

> **Normative.** A policy ignores any entry whose key is not the id of a member of
> `conflicts`, and treats a member absent from the mapping as unlabelled. The
> existing target-coherence obligation is unchanged: a target-carrying ruling still
> names one of the records `decide` was handed (ADR-0040 §5).

> **Normative.** The `MemoryPolicy` conformance suite does not assert which relation
> a policy picks for a given labelling. ADR-0040 §5's rule stands: "a conformance
> suite *is* the contract", and asserting an implementation's ladder would make one
> policy's reasoning the contract.

> **Normative.** `MemoryPolicy.decide`'s docstring states the determinism obligation
> §2 ratifies, in the terms `NotificationPolicy`'s already uses.

> **Normative.** The value passed as `relations` is a **runtime** read-only mapping
> — `types.MappingProxyType` over the caller's mapping, or an equivalent that no
> `isinstance(..., dict)` narrowing turns back into a mutable object. A caller never
> passes the mutable mapping it holds.

> **Normative.** §5's `RESTATES`/`ADDS` exclusion is evaluated against a mapping the
> writer holds and has handed to no policy. A relation the writer reads to determine
> what a `SUPERSEDE` retires is never one a `MemoryPolicy` was given the opportunity
> to change.

**The type is spelled out because a conformance obligation cannot substitute for
it.** `Mapping` rather than `dict`, because the annotation is what makes a mutating
policy a type error rather than a conforming implementation. What the annotation is
**not** is a runtime guarantee: it is erased at run time, `isinstance(relations,
dict)` recovers a mutable object from a parameter typed this way, and a foreign
policy that narrowed and wrote would be changing the very mapping the ingestor
holds. The two clauses above are what actually close that, and they are not
interchangeable. The read-only view is defence in depth — it makes the mutation fail
where it is attempted. The writer's untouched mapping is the guarantee: §5 requires
its exclusion to hold "at the writer, from the writer's own relations, never trusted
from the ruling", which is ADR-0038 §2a's shape, and if the writer's relations and
the policy's were one object that safety property would rest on the untrusted policy
— precisely the failure §5 exists to avoid. Stated this way a mutation of whatever
the policy was handed cannot reach the writer at all, whatever the policy does with
it. `str` keys, because they are `MemoryRecord.id` values and `target_id` is one.
And `| None = None` rather than an empty default for two reasons: a mutable literal
default is not available anyway, and the two states are genuinely different —
`None` says no reconciler ran at all (§2's condition excluded this ingest, or none
is injected), `{}` says one ran and labelled nothing. Both rule identically under
§4, since every member is unlabelled either way, but only one of them is a fact a
`reason` or a later trace can report, and erasing the distinction at the contract
would make it unrecoverable.

**Keying by id, against ADR-0121 §2's instinct, and why it is right here.**
ADR-0121's implementation states set membership "over the records rather than over a
set of ids", because "membership in the agreeing set is a property of what a record
*says*, and collecting ids first would make it a property of a store's identifiers".
That reasoning is about a predicate the policy computes for itself. Here the
determination has already been made, by a component the policy does not hold, about
records it must be able to *name* as `target_id` — and `target_id` is an id. The
mapping records which record the reconciler made its statement about, which is the
one thing a sequence of relations detached from the records could not say.

**The parameter has a default, and the default is what keeps the blast radius
finite.** The compatibility it buys is at the **call signature**: every existing
call site compiles unchanged, and a policy that ignores the parameter is still
conforming. It is emphatically **not** behavioural compatibility for
`DefaultMemoryPolicy`, which rules differently when handed no relations than it does
today — §6 states that degraded behaviour and it is a decision, not a fallback. An
implementer reading this paragraph as licence to keep the blind fold alive on the
no-relations path has read it exactly backwards. The breaking half of the contract
change is structural conformance: an implementation of `MemoryPolicy` must accept
the parameter. That is golden rule 5's breaking change and it is flagged as one; it
is also the whole of the *contract* movement.

### 9. What this does to the measures

> **Normative.** This ADR adds no metric key, removes none, and changes no metric
> key's definition. `decisions_reinforce`, `decisions_accept` and
> `decisions_supersede` count what they have always counted.

> **Normative.** The report labels a window spanning this change as not comparable
> across it, in the terms ADR-0121 §7 already uses for the same reason.

The distribution moves hard and in a direction that will look like a regression to
anyone reading a single number. `decisions_reinforce` falls — on the pilot's
population, from 50% toward the small fraction that is genuine restatement —
`decisions_accept` rises by nearly the whole difference, and `decisions_supersede`
becomes non-zero on the observed path for the first time. None of that is a change
in what the counters mean; it is the counters finally counting a rule that says what
it does. ADR-0120 §5's correction rate becomes *more* faithful and will read higher,
for the same reason ADR-0121 made it read lower: it is now counting corrections
rather than the absence of them.

**ADR-0120 §6's repeated-explanation rate does not move**, because it is summed over
the `learn` and `answer` direct seams and this ADR touches neither. §6's numerator
stays the lower bound ADR-0121 §7 made it, and #868 stays open (§12).

### 10. What the implementing lane owes, and that it is one lane

> **Normative.** The implementation is **one lane**: `core/types.py`,
> `core/protocols.py`, `memory`, `ai_assistant.testing` and their tests, ratified
> and merged behind this ADR.

ADR-0137 §1 asks whether the slice "puts substantial **new machinery** into at most
one subsystem". It does: the reconciler and the policy arms are `memory`'s, and both
sides of the seam this ADR states — the ingestor that computes relations and the
policy that reads them — are in `memory`. The `core` delta is the contract that seam
is written at, and the composition-root wiring and the fake's mirroring are
adaptation, which §1 excludes from the bound ("A lane may carry adaptation across
any number of subsystems"). ADR-0137 §2's contract-seam cut is available if a
reviewer reads it otherwise and reaches the same one-lane answer by that route.

The lane owes:

- `core/types.py` — `ConflictRelation` (§8).
- `core/protocols.py` — `MemoryPolicy.decide`'s parameter and the determinism
  clause in its docstring (§8, §2).
- `memory` — the reconciler behind a `memory`-internal seam, with the `agrees` rung,
  the spend condition, the bound, the route, the temporal clause and the
  never-raises clause and its cancellation exception (§3);
  `DefaultMemoryPolicy`'s non-asserted arm (§4), with the class docstring's numbered
  rules renumbered to match; `MemoryIngestor`'s invocation between the probe and the
  ruling and behind the admissibility floor (§2), sharing `policy.py`'s floor
  predicates rather than restating them — both modules are `memory`'s, so a
  duplicate that could drift is avoidable here and is not to be written; the
  read-only mapping it passes to `decide` and the unhanded mapping it rules the
  retirement set from (§8); and the retirement exclusion (§5).
- `ai_assistant.testing` — the same seam, the same read-only hand-off to `decide`
  and the same exclusion on the canonical `MemoryWriter` fake, which holds its own
  policy and computes its own retirement set and so carries §8's second clause in
  its own right, duplicated rather than imported.
- The shared `MemoryWriter` conformance suite — the `agrees` and `ADDS` halves of
  §5's exclusion, and the standing refusals it does not disturb.
- The `MemoryPolicy` conformance suite — the parameter's presence and the
  target-coherence obligation over it; **not** which relation maps to which ruling.
- `core/config.py` — `reconciler_max_conflicts` and `reconciler_model` (§3).
- `app/composition.py` — the wiring lines.
- Tests pinning the pilot's own shapes by their measured values: the 0.77 pair rules
  `ACCEPT` and retires nothing; a verbatim restatement rules `REINFORCE` with no
  model call; a set holding both a `RESTATES` and a `CONTRADICTS` member rules
  `ACCEPT`; a `SUPERSEDE` on a labelled contradiction leaves an `ADDS` sibling live;
  an unavailable reconciler reproduces §6's floor exactly; and an `EXTERNAL` member
  is named by neither arm while still counting in both purity conditions.
- Tests pinning the two boundaries §2 and §3 draw, **counted against a recording
  double rather than inferred from a ruling**, because every ruling they govern is
  reachable without them and a test that only reads the ruling passes on an
  implementation that violates both:
  - **zero** reconciler invocations and **zero** provider requests for a
    `USER_ASSERTED` proposal, and again for a non-asserted proposal whose conflict
    set holds a `USER_ASSERTED` member (§2's invocation condition);
  - **zero** of each again for a `DataTier.SECRET` proposal, for a derived belief
    citing no evidence, and for an unconfirmed belief whose warrant rests on
    recorded external content — each given a non-asserted conflict set that would
    otherwise have reconciled, so the test fails on an implementation that invokes
    ahead of the floor (§2). The secret case is the one that must assert on the
    **provider**: a ruling-only assertion passes whether or not tier-0 content was
    sent;
  - **exactly one** provider request for a non-asserted proposal whose conflict set
    holds several members the `agrees` rung did not settle, and **zero** for one
    whose members it settled entirely (§3's one-request clause);
  - the request covers no member beyond `reconciler_max_conflicts` in rank order,
    **and** a reply volunteering a label for the beyond-bound member's own valid id
    leaves that member unlabelled — the response half of the same bound, which a
    test reading only the request cannot see;
  - a malformed `reconciler_model` is refused where `Settings` is built, not at the
    first ingest that would have used it.
- A test pinning §8's two mapping clauses, which no test reading only the ruling can
  see: an injected policy that narrows `relations` with `isinstance(..., dict)`,
  relabels an `ADDS` member `CONTRADICTS`, and returns a `SUPERSEDE` naming a
  different member — assert the `ADDS` sibling stays live **and** that the mapping
  the writer rules the retirement set from is unchanged after `decide` returns,
  whether the attempted mutation raised or landed on something the writer does not
  read. The rest of the list exercises no cross-seam mutation.

**This ADR's own ratification.** The required set is adversarial **and**
architecture (ADR-0015 §1, `CONTRIBUTING.md` → "Stop when the required reviews are
green"), because §8 decides a contract surface. ADR-0015 §5's ratify-after-review
sequencing is taken as ADR-0130 §12 and ADR-0136 §7 took it: drafted, reviewed and
revised as `Proposed`, with the status flipped only once both required reviews
returned clean on **one** tree, and both re-run on the flipped tree.
`CONTRIBUTING.md` → "Finishing an ADR PR" holds that sequence and the reason for it,
and is pointed at rather than re-argued here. The PR carries the round record;
nothing implements against §8 until this has merged.

### 11. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test, applied to each: would a reader holding only the earlier ADR now
act differently, or read one of its clauses more widely than it now holds?

**A record is owed on three.**

- **ADR-0040 §4 — amended.** Its description "**rule 5** — a non-asserted proposal
  that conflicts with a non-asserted record, reason 'updates an existing memory' —
  becomes `REINFORCE`" is no longer a complete description of `DefaultMemoryPolicy`,
  and a reader building rule 5 from it would build the rule this ADR replaces. That
  fails the test. It is an **amendment** and not a supersession, because ADR-0040
  decided nothing here: §4's own heading is "migrates with no behavioural change",
  §5 rules that "the suite must not assert which relation a policy picks", and §7
  files "whether rule 5 should supersede" as expressly not decided. Discharging §7's
  deferral is separately a **stacked addition** and owes nothing — a deferral
  answered by the ADR it named leaves the deferring sentence true (ADR-0083 §15).
  ADR-0040's `Status` carries a leading `Partially superseded by` token, so under
  ADR-0082 §2 the record is the appended dated note alone and no qualifier goes on
  the line.
- **ADR-0079 §3 — partially superseded**, in the scope of §5's exclusion. §3
  promoted the full-set retirement to a `MemoryWriter` conformance obligation
  stating the set as "the named `target`, plus every other conflict in the set the
  policy ruled on whose source is supersedable". §5 narrows that set. A reader
  holding only ADR-0079 would build a writer that retires records this ADR forbids
  retiring, which is a change to what was decided and takes a superseding ADR
  (ADR-0070 §1). ADR-0079's `Status` is a plain `Accepted`, so the leading-token
  form and a dated note both land on it (ADR-0070 §4, ADR-0082 §2).

  **This reverses ADR-0050's 2026-08-02 finding about the same section, and the
  reversal is the point.** That note rules that "**ADR-0079 §3 needs no record of
  its own**" because §3 states the obligation *intensionally* — "whose source is
  supersedable" — so ADR-0092's widening of what is supersedable "leaves its
  sentence true verbatim and no reader of it acts differently (ADR-0082 §1)". That
  reasoning is right and is exactly why it does not reach this ADR. §5's exclusion
  is not a change to which *sources* are supersedable: it withholds retirement from
  a conflict whose source **is** supersedable, on a ground §3's sentence has no term
  for. The intensional statement is what saved §3 from ADR-0092 and is what exposes
  it here.
- **ADR-0050 §1 — partially superseded**, in the same scope. §1 is where the set is
  "defined precisely", and it rests the definition on the premise that "every entry
  in the conflict set the detector surfaced is a same-kind, at-or-above-threshold
  contradiction of the proposal". #1188 measures that premise false at the ratified
  threshold. ADR-0050's `Status` already carries the leading token with three pairs;
  a fourth is added and none is dropped (ADR-0070 §4), with the record in the note.

**No record is owed on the rest**, and each is named because a reader may expect
otherwise.

- **ADR-0121 §1.** Its two normative clauses define `agrees` and bound what the
  agreement test may read. Both stay true word for word: `agrees` is unchanged, and
  it still reads no model value — §3 makes it the reconciler's first rung *beside* a
  model call, never a model-informed version of itself. §1's refusal of a
  model-judged test is prose, is stated as "refused here, not forever", and names
  "a different ADR" as its discharge. This is that ADR. Nothing of §1 becomes false
  or reads more widely.
- **ADR-0121 §6.** "No subsystem outside `memory` performs the test" stays true, and
  §2 sites the reconciler so that all four of §6's reasons for refusing `learning`
  are satisfied rather than evaded. §6's sentence that "no Protocol signature, DTO
  or engine method changes" is a statement about *that* ADR's implementation, not a
  prohibition on later ones.
- **ADR-0121 §2, §3, §4, §5.** All four are about a `USER_ASSERTED` proposal.
  This ADR's arm is reachable only when the proposal is not asserted and no member
  is, so the two populations are disjoint. §3's `EXTERNAL` argument is *cited* in
  §4 above and applied to a second population, which is a stacked addition.
- **ADR-0005 §3.** "A deterministic `MemoryPolicy` decides the outcome" stays true,
  and §2 ratifies it explicitly rather than relaxing it.
- **ADR-0038 §2, §2a, §3.** §2's "topical similarity is not contradiction" is
  vindicated: this ADR stops the one rule that treated it as agreement. §2a's "every
  fold overwrites the target, so the target is what has to be checked" is honoured —
  §5 adds an exclusion enforced at the writer and opens no exception. §3 is
  untouched; no observation supersedes an assertion here or anywhere.
- **ADR-0045 §5.** Clause 1 is untouched and gains no exception (§5's last clause).
  Its "topical similarity may not retire a record the user gave us" is unaffected: a
  `USER_ASSERTED` member is never reached by this arm.
- **ADR-0050 §2.** The assertion-versus-assertion deferral is untouched, as is
  ADR-0121 §9's narrowing of it.
- **ADR-0103 §6.** It governs how a `DERIVED`→`ATTESTED` fold folds and "authorises
  none". §4 excludes `EXTERNAL` from both target classes, which shrinks §6's
  population on this path without touching a word of its rule.
- **ADR-0079 §1.** "A correction resolves every conflict it is shown, or it does not
  land" stays true under §5. What §5 changes is the extension of "conflict": a
  member labelled `ADDS` is not a conflict the correction was shown, it is a distinct
  fact similarity surfaced. §1's own honesty claim — "not 'every conflict that
  exists on the topic'" — is the same claim, made more accurately.
- **ADR-0154, ADR-0155, ADR-0017 §1.** §2 records what each makes of a `memory`-held
  `ModelProvider` and of a relation's coverage status. No clause of any of the three
  becomes false, and none is read more widely: ADR-0154 §2 already disclaims reach
  into `models/`, and ADR-0155 §3's prohibitions are stated over the `tools/` egress
  seam.
- **ADR-0156.** §3's temporal clause *reads* an anchor §2 requires and imposes no
  new obligation on any producer. ADR-0156 §1's "no read-time predicate,
  eligibility rule, ordering, retention rule or store filter reads a temporal
  anchor" stays true: a reconciler is none of those, it is a reader weighing
  rendered text, which is exactly what §1's second sentence describes.
- **ADR-0143 §8, ADR-0158 §5.** Each is cited and each is left as it stands.
- **ADR-0077 §2.** The observer's selectivity bar and its `observation_max_proposals`
  bound are untouched. #1188's open question — whether the similarity search should
  still bound something, or whether §2's selectivity is bound enough — is answered
  in this ADR's own terms rather than in ADR-0077's: `conflict_limit` still bounds
  the set, and §3's `reconciler_max_conflicts` bounds the spend. No producer-side
  bound moves.
- **ADR-0078 §5a, and the floor it names — ADR-0004 §3, ADR-0077 §5, ADR-0106 §6.**
  §2's invocation condition puts the reconciler *behind* the admissibility floor and
  moves, widens and narrows none of it. Each of the floor's rulings fires on exactly
  the population it fired on before, and §5a's "precede any conflict reasoning"
  reaches one further component — which is the reading it already had, since a
  relation is a statement about the proposal against a conflict-set member. Nothing
  here makes the floor a reconciler rule: §2's second clause states the exclusion
  over the proposal's own properties, so it holds whatever `MemoryPolicy` is
  injected and does not become a prediction about one.
- **ADR-0060 §1.** §3's cancellation clause adds no obligation of its own. It says
  which of §1's two kinds each arm of the never-raises clause is about — a
  cancellation delivered from outside, which §1 requires be delivered onward, versus
  one `models/` issues against its own deadline, which §1 lets a method classify
  into a return value. §1 binds this path already, through `MemoryWriter`; what §3
  does is stop a marked clause of *this* ADR from reading as a licence §1 does not
  grant.

### 12. What this ADR does not decide

- **#868 — paraphrase on the asserted path. Left open, and narrowed.** ADR-0120 §6's
  repeated-explanation rate is summed over the `learn` and `answer` seams, whose
  proposals are `USER_ASSERTED` and take ADR-0121 §2's arm, which this ADR does not
  reach. Closing it means letting a reconciler label feed that arm, and onto a
  `USER_ASSERTED` target that runs straight into #868's own second bullet: ADR-0121
  §5's exception is *verified at the writer*, and a model predicate is not verifiable
  there. §5's last clause explains why this ADR escapes that objection and why an
  extension to the asserted-onto-asserted pairing would not. The tractable subset —
  a paraphrasing assertion onto an `OBSERVED` or `INFERRED` target, which needs no
  writer-floor exception — is a real follow-up and is left to it. The rate stays a
  lower bound and the report keeps saying so.
- **#869 — an observation agreeing with a user assertion still asks. Left open.**
  §4's last normative clause says in terms that the `ASK_USER` ruling is untouched.
  A reconciler label would make the case *detectable*, which is new, but acting on it
  still requires what #869 names: extending ADR-0103 §6's corroboration arm so a
  lower-warrant proposal folding onto a higher-warrant target contributes evidence
  and currency and nothing else, without demoting the target's `source`. That is a
  fold rule, not a labelling rule, and it belongs with whoever writes it.
- **#871 — a multi-member agreeing set folds onto one target. Left open, and made
  rarer.** §4(a) names one target, exactly as ADR-0121 §2 does, and a second
  `RESTATES` member stays live. This ADR makes that shape *more* common on the
  observed path, because a set that previously all folded now folds once. It remains
  duplication and not loss, and #871's own reading — that consolidation is the right
  home for collapsing near-identical records — is unchanged and is now better
  supported.
- **#1169 — consolidation's prompt strips ADR-0156 anchors. Left open, and its
  priority raised.** §3's temporal clause makes a belief's stated event time
  load-bearing at the reconciler, and a fold that drops the anchor produces exactly
  the input on which the reconciler will call a sequence a contradiction. Fixing the
  consolidator's prompt is `orchestration`'s and is outside this ADR's fence in
  either direction; what this ADR contributes is a second, independent reason to do
  it.
- **#743 — ADR-0092 §6 against ADR-0103 §6 on which attestation a `REINFORCE`
  takes. Left open, and its population shrunk.** §4 excludes `EXTERNAL` from both
  target classes, so `DefaultMemoryPolicy` no longer reaches the `DERIVED`→`ATTESTED`
  fold at all on the observed path. The contradiction is between two ADRs about how
  such a fold folds and survives untouched for any policy that does reach it; whether
  ADR-0092 §6 owes a record under ADR-0082 §1 is the corpus judgement #743 says it is
  not its own to make, and it is not this ADR's either.
- **A prompt for the reconciler.** This ADR rules what a relation *is* (§1) and what
  a reconciler may read and spend (§3). The wording that elicits it is the
  implementing lane's, as ADR-0077 §4 and ADR-0156 §2 leave the observer's to theirs.
- **The right value of `reconciler_max_conflicts`, and of `conflict_threshold`.**
  Three and 0.75 are the ratified starting values. Whether the threshold should move
  once folds stop depending on it is a measurement question the pilot-4 arm can
  answer and this ADR deliberately does not.
- **A relation in the trace stream.** §9 adds no metric key and no trace field.
  Whether the relation distribution is worth emitting is a decision about what the
  stream is for, and naming it properly is its own ruling — the same call ADR-0121
  §7 made about a policy-change marker.
- **Retrieval-triggered distillation**, which ADR-0158 §8 defers and which reaches
  `learning` and `orchestration` together. Adjacent, and not this.

## Consequences

- **A distinct fact stops being destroyed for resembling one.** This is the product
  consequence and the reason to act; the pilot is how we measured it. On its
  population the change is roughly 385 folds becoming a small number of folds and a
  large number of beliefs.
- **The store grows faster.** Half of what was folded now lands. That is the correct
  outcome and it moves cost onto retrieval and onto consolidation — which is where
  ADR-0106 already puts merge-of-near-identical work, and where #871 says it
  belongs. A store that grows because it stopped losing things is not a leak.
- **The observed path gets a supersession for the first time**, so a belief the
  assistant held and later found false can be corrected without the user saying
  anything. `decisions_supersede` leaves zero.
- **The write path acquires a network round trip, inside a lock.** An ingest that
  reconciles is serialised behind one model request, and every concurrent ingest
  queues behind it (§6). Principally that is a throughput cost on batch ingestion,
  which is where the reconciling population lives — but it is **not only** that: an
  interactive `learn` or `answer` write spends no request of its own and can still
  wait out one in flight, so the cost reaches turn latency by way of the queue. That
  is the price of the judgement, it is bounded by one request under `models/`'s
  deadline and retries, and §6 names the only lever a deployment has against it.
- **`memory` acquires a model dependency**, and it is the first. The subsystem that
  has never called a provider now optionally does. §6 is what keeps that from being a
  hard dependency, and the conformance suites are what keep the fake honest about it.
- **`MemoryPolicy.decide` gains a parameter**, so every implementation must accept
  it. That is the breaking change, flagged under golden rule 5, and it is the whole
  of the contract movement.
- **Two figures become non-comparable across this change** (§9), and a third — the
  repeated-explanation rate — deliberately does not move at all.
- **The reconciler is a new place to be wrong**, and the failure it can produce is
  new: a false `CONTRADICTS` retires a true belief where the old rule would merely
  have folded it. §3's temporal clause and §4's purity conditions are the two guards,
  and §5's exclusion bounds the damage to one record rather than the set. This is the
  thing to watch in the pilot-4 arm.
- **Revisit when** the pilot-4 arm reports the relation distribution against measured
  accuracy; when the tractable half of #868 is worth taking; or if a false
  `CONTRADICTS` rate shows up that §3's guards do not explain.

## Alternatives considered

- **Raise the conflict threshold.** Rejected for ADR-0121 §1's reason, unchanged and
  now measured: the score's ordering puts a one-token contradiction at the top, and
  the pilot's own distinct-fact pairs sit at 0.77–0.80, above where a raise would
  have to land to help. No threshold value separates "different fact" from "same
  fact".
- **Never fold a non-asserted proposal — always `ACCEPT`.** The cheapest design here,
  needing no model, no contract change and no ADR of this size. Rejected because it
  throws away the genuine restatements along with the rest, guarantees the duplicate
  accumulation ADR-0092 §7 names as a residue to shrink, and would leave the observed
  path with no correction mechanism at all — turning a rule that loses facts into one
  that keeps every stale belief forever. It is also strictly worse than §6's degraded
  behaviour, which gets the certain folds for free.
- **Put the `ModelProvider` behind `MemoryPolicy.decide`.** The shape ADR-0121 §1
  names and the smallest diff: no new component, no new parameter, no `core/types.py`
  member. Rejected in §2. It costs the determinism ADR-0005 §3 states and ADR-0130
  §11 holds the sibling policy to, makes the `MemoryPolicy` conformance suite a suite
  over a network call, and forces every consumer's test to hold a provider. The
  parameter is the price of keeping the ruling a function.
- **Label in `learning`, before the proposal is made.** Rejected in §2 on ADR-0121
  §6's four grounds, and on a fifth: `learning` has no conflict set. The candidates
  come from a store read inside `MemoryIngestor`, so a labeller sited before the
  writer would have to perform its own retrieval and would reach a different set.
- **A `ConflictReconciler` Protocol in `core/protocols.py`.** Rejected in §2. Both
  sides of the seam are in `memory`, and `core/protocols.py` is for contracts between
  subsystems; adding one here would widen the surface ADR-0027 §3 puts in the review
  floor for no injection anyone needs.
- **A fourth relation for "unknown".** Rejected in §1. Unlabelled is the *absence* of
  a statement, and giving it a name invites a rule to be written over it — at which
  point a reconciler failure starts changing rulings, which is exactly what §6
  forbids.
- **Let an unlabelled member block a fold.** Rejected in §4. It would let one model
  failure downgrade a certain `agrees` restatement into a duplicate, regressing
  against ADR-0121 for no safety gain.
- **`ASK_USER` for a set holding both a `RESTATES` and a `CONTRADICTS` member.**
  Rejected in §4. The contradiction is between two stored records, not with the
  proposal; the user did not write either of them, and #869 already records that
  asking about an observation is a cost the user should not be paying.
- **Batch the reconciler through `BatchCompleter`.** Rejected in §2 on ADR-0143 §8's
  two clauses: no subsystem is given one, and a batch never runs in the hub.
