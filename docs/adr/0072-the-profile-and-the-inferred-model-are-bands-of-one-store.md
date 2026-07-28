# 72. The profile and the inferred user model are bands of one store

- Status: Proposed
- Date: 2026-07-27
- **This is a contract change.** §2 adds a `BeliefBand` enum and a total
  `band_of(MemorySource) -> BeliefBand` mapping to `core/types.py` — a `core`
  addition that every subsystem reading a belief will classify against. Golden
  rule 5 therefore applies: this ADR ships as **its own docs-only PR**, is
  reviewed while still `Proposed` so a finding can still change the decision, and
  is flipped to `Accepted` on merge (`CONTRIBUTING.md`, "Contract ADRs land before
  their implementation"; ADR-0015 §5). **No code changes with it.** The type, the
  band-scoped read (§7), and every consumer are later lanes.
- **Directs** `VISION.md` — §9 below states the amendment, which lands in this
  same PR. `VISION.md` is a living document ratified by nothing; ADR-0019 governs
  what it may contain, and §9 argues the amendment against that rule.
- **Amends and supersedes nothing.** Applying ADR-0070 §1's test to each ADR this
  decision touches: ADR-0005 §2 defined two sets by explicit source membership and
  assigned `EXTERNAL` to neither, so §2 below classifies a source ADR-0005 left
  open rather than reclassifying one it placed — a reader of ADR-0005 acts
  identically before and after. ADR-0038 §§1/2/3, ADR-0040, ADR-0045 §§4/5 and
  ADR-0050 are restated here in band vocabulary and changed in no particular;
  §4 states that explicitly, clause by clause. No ADR's Status line is edited.
- **Refs:** ADR-0005 (typed memory, provenance, propose/dispose — the frame this
  ADR completes), ADR-0007 (the data-rights surface the inspection lane consumes),
  ADR-0009 (the first and so far only belief producer), ADR-0019 (what a living
  document may assert — governs §9), ADR-0038 / ADR-0040 / ADR-0045 / ADR-0050
  (the supersession law §4 restates), ADR-0004 (the tiering and retention rules
  observation runs inside), ADR-0068 (the freeze §2's additions must respect).

## Context

The roadmap was reoriented on 2026-07-24 around **accumulation**: the premise
that the decisions worth making next are the ones that put accumulated beliefs
behind the vocabulary ADR-0005 built, without the user having to dictate them.
This ADR is the first slice of that arc's first leg, and its Context is where
that reorientation is dated — `docs/roadmap.md` deliberately carries only
pointers, because a living document may not carry a narrative that reads as
currently-true forever (ADR-0019 §1).

The dated position, at the time of writing:

**The vocabulary exists and one half of it is empty.** ADR-0005 §2 ruled that the
User Profile versus User Model distinction is expressed *through* provenance
rather than through separate stores: the profile is the `USER_ASSERTED` records,
the user model the `OBSERVED`/`INFERRED` ones, and there is one `MemoryStore`
seam with the split as a query concern. `core/types.py` carries that faithfully —
`MemorySource`, `Provenance` with its `USER_ASSERTED`-implies-1.0 validator,
`evidence`, and, since ADR-0045, a validity window. What the repository does not
have is anything that ever writes `OBSERVED` or `INFERRED`. The only belief
producer is ADR-0009's `RuleBasedFeedbackProcessor`, which stamps
`USER_ASSERTED`/1.0 by construction. So the *inferred* half of the split has
never held a record, the split has never been exercised by a reader, and the
"query concern" ADR-0005 named has no query.

**The supersession law is complete and is written for a producer that does not
exist.** ADR-0038 ruled that a user assertion supersedes a conflicting inference
and never the reverse; ADR-0040 split the ruling into `REINFORCE` and
`SUPERSEDE`; ADR-0045 made supersession non-destructive by closing a validity
window; ADR-0050 extended resolution to the full conflict set. Every one of those
decisions is about what happens when a derived belief meets a user's correction —
and today no derived belief is ever created, so the law governs an empty band.

**The previous roadmap revision expected a `UserProfile` artifact.** The arc it
tracked listed one among its core artifacts, and the current revision's leg 1
still names "the `UserProfile` ADR". That expectation predates ADR-0005's
provenance ruling being lived with, and it is the first thing this ADR has to
settle: whether the profile is a *thing the system holds* or a *way of reading
what it already holds*.

**A retrieval path exists and is band-blind.** `orchestration` retrieves by
calling `MemoryStore.search(query, limit=...)` and passes the records on. Nothing
filters by source, nothing reads `confidence`, and nothing distinguishes a fact
the user stated from a belief the assistant guessed. That is harmless while every
record is `USER_ASSERTED`. It stops being harmless on the first day the derived
band is non-empty, which is the day leg 3's observer lands — so the reading rule
has to be decided before the producer, not after it.

**Four forces make this a decision rather than an implementation detail.**

1. **VISION §2 forbids the obvious shortcut.** "Stable profile information is not
   a separate store but a matter of provenance." A second store of user facts is
   ruled out by the vision, and ADR-0005 §2 gave the argument: two storage
   Protocols would duplicate the contract for a difference that is really about
   provenance. Anything this ADR ratifies has to live inside one store.
2. **The split has to be *readable*, not merely representable.** VISION §Principle
   1 asks that every inference have "evidence, confidence, scope, and a way to be
   corrected", and leg 1's exit test is that the user can read the assistant's
   beliefs, see why each is held, and kill any of them. A distinction that only
   exists as an argument to a filter nobody can express is not readable.
3. **`EXTERNAL` is unclassified.** ADR-0005 §2's partition names four sources and
   places two of them. ADR-0038 §2a already had to reason about `EXTERNAL`
   separately — "neither derived by us nor given by the user, and which may carry
   confidence 1.0" — and excluded it from the supersedable set for a mechanical
   reason. Leg 6's sensors are the first thing that will produce `EXTERNAL`
   records at volume, and every consumer will otherwise pick its own answer.
4. **The observer needs the semantics fixed before it is designed.** Leg 3's
   observer is a model-backed producer of `OBSERVED`/`INFERRED` proposals. Its ADR
   has to decide scope, retention justification, and which model reads the
   episodes. It should not also have to decide what an observed belief *means* —
   what confidence expresses, what evidence it owes, how it loses to a correction
   — because those are properties of the model, not of the producer, and a second
   producer would inherit them.

## Decision

### 1. The profile is a band of one store, not an artifact

We will keep exactly one store of beliefs and treat the profile/model split as a
**standing** each record carries via its provenance — read at query time, never
materialised as a second collection.

- **The user profile** is the set of beliefs the user asserted: `USER_ASSERTED`
  provenance, confidence 1.0 by the validator that already exists, the user's own
  word. It is not re-derivable, and losing one is unrecoverable (ADR-0038 §2).
- **The inferred user model** is the set of beliefs the assistant derived:
  `OBSERVED` or `INFERRED` provenance, sub-1.0 confidence, each citing the
  evidence that produced it. It is provisional by construction and re-derivable:
  if a derived belief is wrongly retired, the observations that produced it will
  propose it again.

There is **no `UserProfile` type, no `UserProfileStore` Protocol, and no second
collection of user facts.** The roadmap's expectation of a `UserProfile` artifact
is declined, and the reason is not economy — it is that the artifact would be a
lie about where the truth lives. A materialised profile is a cache of a query
over the store, and a cache with no invalidation contract drifts from its source
the first time a correction lands. ADR-0005 §2 reached the same conclusion from
the storage side; this ADR reaches it from the reading side and closes the
question rather than leaving it to be re-asked per slice.

What is genuinely missing is not a store but a **vocabulary and a read**: a name
for each standing that every consumer classifies against (§2), and a way to ask
the store for one standing at a time (§7). Those are the projection. The
projection is an *operation over the one store*, not a struct that holds a copy of
it — which is also why this ADR ratifies no container type (§8).

### 2. Three bands, not two — and the classification is a total function

`core/types.py` gains, beside `MemorySource`:

```python
from typing import assert_never  # added to core/types.py's existing typing import


class BeliefBand(StrEnum):
    """The standing a belief is held with — how far it is from the user's word."""

    ASSERTED = "asserted"   # the user told us; their own word, confidence 1.0
    DERIVED = "derived"     # we worked it out; provisional and re-derivable
    ATTESTED = "attested"   # a source the user connected reported it


def band_of(source: MemorySource) -> BeliefBand:
    """The band a provenance source places a belief in (ADR-0072 §2)."""
    match source:
        case MemorySource.USER_ASSERTED:
            return BeliefBand.ASSERTED
        case MemorySource.OBSERVED | MemorySource.INFERRED:
            return BeliefBand.DERIVED
        case MemorySource.EXTERNAL:
            return BeliefBand.ATTESTED
        case _:  # pragma: no cover - exhaustive
            assert_never(source)
```

Three properties are load-bearing.

**`EXTERNAL` gets its own band.** It is not the user's word — the user connected a
calendar; they did not state that a meeting exists — and it is not our inference
either. Folding it into `ASSERTED` would let an integration's record inherit the
standing reserved for what the user personally told us, which is the standing the
whole supersession law protects. Folding it into `DERIVED` would call a third
party's record our guess, and would wrongly imply it is re-derivable by us
(ADR-0038 §2's asymmetry turns on exactly that property; a stale calendar is not
re-derivable by observing harder). ADR-0005 §2 assigned it to neither set, which
was correct and incomplete; this ADR completes it without changing what ADR-0005
placed.

**The mapping is total and its totality is mechanically enforced.** Every arm
names a member and the wildcard does nothing but `assert_never`, so under `mypy
--strict` an unhandled `MemorySource` narrows to a non-`Never` type there and
fails the gate: adding a member without choosing its band cannot merge.
`assert_never` is not currently imported by `core/types.py` (which imports
`Annotated`, `Any`, and `Literal` from `typing`), so the implementing lane adds it
— stated because a snippet that omits it fails the type gate on an undefined name
and would degrade the runtime arm to a `NameError`. This is deliberately the same shape as
ADR-0038 §2a's allow-list argument — "a `MemorySource` added later is not silently
enrolled in a destructive rule by omission" — applied to classification instead of
to supersession, and it is a fact a check owns (ADR-0019 §2) rather than a prose
convention that decays.

**The names avoid the word "model".** This codebase uses "model" for the language
model throughout — `ModelProvider`, `models/`, `ModelRouter`. `UserModelBand` or a
`MODEL` member would read as the LLM's band to every subsequent reader. The
product words *profile* and *user model* stay in prose, where the context
disambiguates them; the code says `ASSERTED` and `DERIVED`.

The function classifies a `MemorySource`, so it applies wherever `Provenance`
does — including `Goal`, whose docstring already makes the same distinction ("a
goal the system *inferred* must never be indistinguishable from one the user
*stated*"). The *profile* and the *inferred user model* specifically name the band
partition of the `MemoryStore`'s records; the bands themselves are general.
**Classification generalising does not carry §3's obligations with it** — those are
scoped to memory proposals for want of an enforcement point elsewhere, which §3
states and §10 files.

Nothing here disturbs ADR-0068: `BeliefBand` is a `StrEnum` and `band_of` is a
pure function of an immutable value.

### 3. What a derived belief means — for a memory proposal

These are properties of the model, fixed here so leg 3's observer ADR inherits
them rather than deciding them.

**They are scoped to beliefs proposed into the `MemoryStore`, deliberately.** §2's
classification applies wherever `Provenance` does, but the two obligations below
do not follow it there, because they need an enforcement point and only the memory
write path has one: a proposal is judged by a `MemoryPolicy` before it is stored
(ADR-0005 §3). `Goal` also carries `Provenance` and reaches no such gate — it is
constructed and handed to `PlanStore` directly — so a future producer of *inferred*
goals could write one at confidence 1.0 with no evidence and breach both rules
unenforced. No such producer exists (`orchestration` stamps every goal
`USER_ASSERTED`/1.0 from the user's own utterance), so this is a gap that opens
with the first inferred-goal producer, not one that is open now. Extending these
obligations to goals needs an enforcement seam on the goal write path — a
validator, or a policy gate of its own — which is a decision for the lane that
proposes inferred goals, filed in §10. Stating the scope now is what stops that
lane from reading these clauses as already binding and already enforced.

**Confidence is the producer's belief strength, and 1.0 is reserved.** It is not a
relevance score, not a quality score, and not a priority. A derived belief carries
`confidence` strictly below 1.0, because an observation is *evidence for* a belief
and never the belief itself — a producer that can emit 1.0 is claiming the standing
that only the user's own word carries. ADR-0005 §2 already described the derived
set as "confidence < 1.0"; this ADR makes that an obligation on producers rather
than a description of the records that happened to exist. It is deliberately **not**
enforced by a `Provenance` validator here: `EXTERNAL` may legitimately carry 1.0
(ADR-0038 §2a), so the validator would have to be source-conditional, and no
producer yet exists to violate it. Whether `Provenance` grows a
`DERIVED`-implies-sub-1.0 validator is filed (§10) for the observer's lane, which
will be the first code that could breach it.

**A derived belief owes evidence; an assertion does not.** `Provenance.evidence`
defaults to empty, which is right for an assertion — ADR-0038 §1a settled that "a
user's assertion is its own warrant". A derived belief with no evidence is the
opposite case: it cannot answer "why do you believe that?", so it fails VISION
§Principle 1 and it fails leg 1's exit test, which is that the user can see why
each belief is held. So **a proposal in the `DERIVED` band cites at least one
evidence reference.** The enforcement point is the `MemoryPolicy` gate, not the
type: propose/dispose is already where a proposal is judged against something
other than its own shape (ADR-0005 §3), and a policy can state the rule for the
band it is judging without constraining `EXTERNAL` or `USER_ASSERTED` records that
legitimately cite nothing. Writing that rule belongs to the observer's lane, with
its producer in hand.

**`OBSERVED` and `INFERRED` are distinguished by whether the evidence entails the
belief.** ADR-0005 named both and never separated them, and every subsequent ADR
has treated them as one set. They are one *band* — §4 keeps them
indistinguishable to the supersession law — but they are not one epistemic act:

- **`OBSERVED`** — the belief restates what the evidence directly shows. "The user
  declined the 07:00 slot on four occasions" is entailed by the four episodes it
  cites; the step from evidence to belief is recording and aggregation.
- **`INFERRED`** — the belief goes beyond what the evidence shows. "The user
  prefers not to meet before 09:00" is *supported* by those same four episodes and
  entailed by none of them; the step is a generalisation, a motive, or a
  preference read off behaviour.

The distinction is worth keeping because the two fail differently. A wrong
`OBSERVED` record is a recording bug — the evidence does not say what we wrote. A
wrong `INFERRED` record is a reasoning error over evidence that is itself correct,
and it is the failure VISION §Major-Risks calls "incorrect personalization". They
warrant different confidence ceilings and different correction affordances, and a
producer that cannot tell them apart is not entitled to either label.

### 4. How a correction moves a topic between bands — restating, changing nothing

A user's correction moves a topic out of the derived band and into the asserted
one. Mechanically this is entirely existing law, restated here in band vocabulary
so the observer's ADR has one place to read it, and **changed in no particular**:

- The correction is proposed as `USER_ASSERTED`, and the policy rules `SUPERSEDE`
  over the conflicting derived record(s) (ADR-0038 §1, ADR-0040).
- The applier closes the superseded record's validity window and writes the
  correction at a fresh id; the retired record stays on disk and stays in `export`
  (ADR-0045 §4, §6).
- Resolution reaches the whole conflicting set, not only the best-ranked member
  (ADR-0050).
- The direction is strictly one-way: `ASSERTED` may retire `DERIVED`; `DERIVED`
  may **never** retire `ASSERTED`, silently or otherwise (ADR-0038 §3), and no
  fold of any kind lands on a `USER_ASSERTED` target (ADR-0045 §5, clause 1).
- `ATTESTED` sits outside that law in both directions today: the writer floor
  permits an `EXTERNAL` `SUPERSEDE` since ADR-0045 §5, and `DefaultMemoryPolicy`
  does not take it (ADR-0045 §7). This ADR does not change that either. Naming
  `ATTESTED` as its own band is what makes the open question *visible* — "may a
  correction retire a calendar's record of the world, and for how long?" — not
  what answers it.

Two consequences of the band framing are worth stating because they are what the
observer ADR will build on. First, the standing is keyed on `source`, never on
`confidence`, so no producer can promote a belief into the profile by claiming
certainty — the confidence rule in §3 is about honest presentation, and the band
boundary does not depend on it holding. Second, a correction does not *edit* a
derived belief; it retires one and writes another, so the derived band is a record
of what the assistant worked out and the asserted band is a record of what the
user said, and neither is ever rewritten to look like the other.

### 5. Retrieval reads the whole store; band precedence is applied above it

`MemoryStore.search` stays **band-neutral and confidence-neutral**: it ranks by
relevance and returns whatever is live, whatever its standing. Three reasons:

- Relevance and belief strength are different axes. Multiplying them yields a
  number that is neither, and no consumer can recover either from the product.
- A store that quietly down-ranks derived beliefs starves the loop that is the
  only way they ever improve. The user cannot correct what they never see, and the
  derived band's whole correction affordance runs through being shown.
- The weighting would be invisible at the seam where it matters and untestable
  from outside it.

**Precedence is applied by the consumer assembling context, and it is by band, not
by detected contradiction.** The assembler fills its budget `ASSERTED` first, then
`ATTESTED`, then `DERIVED`. At equal relevance an assertion outranks an inference,
which is the retrieval-side counterpart of ADR-0038 §3's write-side rule.

The `ATTESTED`-above-`DERIVED` half of that ordering is the least-evidenced part of
this decision, and is stated so a consumer does not invent its own: a connected
source's record of the world is generally a better warrant than our generalisation
over behaviour, but it can be stale in ways we cannot detect. It is ruled now
because leg 6's sensors will otherwise force each consumer to guess, and it is
revisited when the first real sensor exists (§10).

**This is only enforceable if the bands can be read separately** — which is what
makes §7's obligation load-bearing rather than decorative. A band-neutral top-k
followed by a post-hoc partition does not implement precedence: a flood of
low-confidence inferences can displace an assertion *below the cut*, where no
amount of downstream ordering recovers it. The consumer therefore reads per band
and composes, rather than reading once and sorting.

**Contradiction resolution stays on the write path.** The conflict signal in this
system is topical similarity, not contradiction (ADR-0038 §2), and this ADR does
not introduce a runtime contradiction detector at assembly. So the honest
statement of the rule is that precedence is by band, and that a stale derived
belief the write path never resolved can still reach the prompt beside the
assertion that should have retired it. The mitigations are §6's presentation and
the user's correction, not a retrieval-time filter that would be guessing.

### 6. Confidence is presentation, not ranking

A derived belief that reaches a prompt is rendered **as a belief**, carrying its
band and its confidence — "the assistant has observed that…", "the assistant
believes, with low confidence, that…" — never as a bare fact indistinguishable
from what the user stated.

This is the decision that keeps the whole split from being cosmetic. The failure
mode of an inferred user model is not a wrong record in a database; it is a wrong
record laundered into a fact by flat prose, restated back to the user with the
assistant's authority, and never questioned because it did not arrive looking
questionable. VISION §Principle 1's "every inference should have evidence,
confidence, scope, and a way to be corrected" is not satisfied by a field the user
never sees. Provenance has to survive the last hop into the prompt, or the
correction loop has no trigger.

The rule constrains *what the assembler must convey*, not the wording it uses; the
prompt-assembly lane owns the phrasing.

### 7. A band-scoped read is owed; its signature is deferred to the lane with the consumer

§1's projection and §5's precedence both require that a caller can ask the store
for one band at a time. Today no read expresses it: `search` filters by `kinds`
and takes a query, `get` takes an id, and `export` returns every retained record
including window-closed ones and cannot filter at all.

We rule the **obligation** and defer the **signature**:

- The band-scoped read is a **store-level** operation. Fetching `export()` and
  re-filtering in an adapter is refused: it would put a live-at-now computation and
  a clock into `interfaces/`, which golden rule 3 keeps thin, and it would duplicate
  the read predicate ADR-0045 §6 deliberately centralised in the store.
- It honours both read-time axes exactly as `get`/`search` do — expired records
  excluded, non-live records excluded (ADR-0007 §2, ADR-0045 §6) — so "what do you
  believe about me" and "what do you retrieve" cannot disagree.
- Whether it is a new `MemoryStore` method (an enumerating `list_beliefs(*, bands,
  kinds, limit, offset)`) or a `sources`/`bands` filter added to `search` is left
  to the slice that holds the consumer, because the two differ in exactly the way a
  consumer settles: enumeration wants an offset and a stable order and no query,
  while a filter wants relevance. Both shapes satisfy the obligation above.

Deferring surface until a consumer exists is this repository's standing
discipline — ADR-0028 §7 declined batch ingestion on that ground, ADR-0045 §1
declined as-of retrieval on it — and leg 1's inspection surface is the lane that
will hold the consumer. What this ADR forecloses is only the wrong answer: that
the band split can be read by filtering an export.

### 8. Explicitly declined

- **A `UserProfile` type or artifact.** §1. It would be a cache of a query with no
  invalidation contract, and it contradicts VISION §2 and ADR-0005 §2.
- **A second store or a second store Protocol.** ADR-0005 §2's argument stands
  unchanged: two Protocols for a difference that is about provenance.
- **A container projection type** — a `UserModelView` holding the three
  partitioned tuples. It carries no decision that `BeliefBand` does not already
  carry, and a struct that only groups is surface without a consumer. The
  projection this ADR ratifies is the *operation* (§2's classification plus §7's
  read), not a struct that holds a copy of the store's contents. If a later lane
  finds three consumers all assembling the same triple, the type is cheap to add
  then, against evidence.
- **Confidence-weighted retrieval ranking.** §5.
- **Any change to the supersession law.** §4.

### 9. The `VISION.md` amendment

`VISION.md` is the canonical statement of *why* and *what*, aspirational and
rarely changed. The roadmap's design stances currently anticipate three things it
does not own. This ADR directs the amendment, landing in this PR:

1. **Core Principle 1 gains passive observation as the primary mechanism.** VISION
   today names only interaction-implicit signals ("ignored suggestions, repeated
   choices") inside a learning-loop capability. The principle becomes explicit
   that the model is built chiefly by *observing* — interactions first, ingested
   read-only sources where the user grants them — with explicit correction as the
   steering wheel rather than the engine, and that this matters most at cold start,
   when nothing has been asserted.
2. **Core Principle 2 gains the reconciliation.** The selective-memory clause and
   the Non-Goal on unlimited inference are not in tension with observation, but the
   document has to say why: what is observed is *proposed*, a deterministic policy
   disposes, and what is kept carries provenance the user can read, correct, and
   delete. Observation without a gate in front of memory and an inspection surface
   behind it is surveillance; with them it is personalization. The Non-Goals section
   gains the same reconciliation from its side.
3. **Core Principle 3 gains the sensor/actuator split.** A read-only source the
   user connected is granted, scoped, and revocable but changes nothing outside the
   assistant; a tool that acts carries consequences that may be irreversible and
   answers to the approval, limit, and audit machinery. The Tool and Integration
   Layer capability gains the pointer.
4. **A new Core Principle 8 states the hub-and-spokes shape.** One resident service
   owns the state and the intelligence; every interface is a stateless client;
   context and identity belong to the service, not the device. It is written as a
   target, and it names why several existing promises depend on it.

**Every addition is a rule or a target, never a snapshot (ADR-0019 §1).** Nothing
added says what exists, what is deployed, how many spokes there are, or what has
landed — in particular the roadmap's "the only spoke for the time being is the
CLI" is a sequencing fact and stays in the roadmap, where a dated tracker owns it.
The amendment adds no count, no timing, and no completion claim. Principle 8 is a
premise the document *sets* about the shape being built, which ADR-0019 §3
distinguishes from a measurement someone took.

### 10. What this ADR does not decide

- **The observer** — its scope, what justifies retaining an observation, and which
  model reads the raw episodes. Leg 3's ADR. This ADR fixes what its output
  *means*, not what it does.
- **A `Provenance` validator forbidding confidence 1.0 in the `DERIVED` band**
  (§3). Filed for the observer's lane, which is the first code that could breach
  the rule; it would be source-conditional, since `EXTERNAL` may carry 1.0.
- **The `MemoryPolicy` rule enforcing derived-beliefs-cite-evidence** (§3). Same
  lane, same reason.
- **Whether §3's obligations extend to `Goal`, and what would enforce them there**
  (§3). `Goal` carries `Provenance` and reaches no propose/dispose gate, so a
  producer of inferred goals would need an enforcement seam of its own. No such
  producer exists; the decision belongs to the lane that adds one.
- **The band-scoped read's signature** (§7), and whether the inspection surface
  reads live-only or live-plus-retired.
- **Whether a correction may retire an `ATTESTED` record in the shipped policy**
  (§4). ADR-0045 §7 made it safe and left adoption to the policy lane; that is
  unchanged.
- **Consolidation, decay, and salience** — what happens to a derived belief that is
  never reinforced and never corrected. Leg 7.
- **How `EpisodicMemory` records are produced**, which the derived band's evidence
  will cite. Leg 2.

## Consequences

- **The keystone question is closed, and closed as "no new artifact".** Every later
  slice in this arc — the inspection surface, the observer, prompt assembly — now
  reads the same definition of what the profile is, and none of them has to decide
  whether to materialise one.
- **`EXTERNAL` has a home.** The three-band partition is total, and the totality is
  enforced by the gate rather than by prose, so leg 6's sensors arrive into a
  classified world.
- **The contract owed is small and precise:** `BeliefBand` and `band_of` in
  `core/types.py`, and nothing else. No Protocol changes with this ADR; §7's read is
  a later lane's ADR because it is a later lane's consumer.
- **`MemoryStore.search`'s contract is unchanged and now explicitly band-neutral.**
  A future proposal to weight retrieval by confidence has to supersede §5 rather
  than arrive as a tuning change.
- **A stale derived belief can still reach a prompt beside the assertion that
  should have retired it** (§5). This is an accepted, named limitation of resolving
  contradiction only on the write path over a topical-similarity signal; §6's
  presentation rule and the user's correction are the mitigations. It gets better
  when conflict detection becomes contradiction detection, not before.
- **Prompt assembly acquires an obligation** (§6): provenance must survive into the
  prompt. That constrains a lane that has not been written yet, which is the point —
  it is far cheaper to state now than to retrofit onto a prompt template that reads
  well without it.
- **`VISION.md` now owns three stances the roadmap could only anticipate**, so the
  roadmap's design stances become pointers to ratified vision rather than premises
  the roadmap set for itself.
- **The observer's ADR gets smaller.** Confidence semantics, evidence expectations,
  the `OBSERVED`/`INFERRED` distinction, and the correction path are settled here,
  so that ADR can spend itself on the two genuinely hard questions it owns: what
  justifies retention, and which model reads the episodes.
- **Revisit if** a real sensor shows `ATTESTED`-above-`DERIVED` to be the wrong
  default (§5), if three consumers independently assemble the same band triple and
  the container type §8 declines starts paying for itself, if a producer needs a
  band the four `MemorySource` members cannot express, or if the one-store ruling
  ever has to yield to differing encryption or retention policy per band — the
  condition ADR-0005 §Consequences already named as what would force separate
  stores.

## Alternatives considered

- **A materialised `UserProfile` type, assembled from the store.** Rejected in §1.
  It is a cache of a query, and its invalidation contract would have to name every
  write path that can change a `USER_ASSERTED` record — a list that grows with
  every producer. The roadmap expected it; the expectation predates living with
  ADR-0005's ruling.
- **A second store for asserted facts.** Rejected by VISION §2 and ADR-0005 §2
  before this ADR reaches it. Worth naming anyway because it is the shape a reader
  reaches for when told the two halves behave differently: they do, on the read
  and the write *rules*, and not on where the bytes live.
- **Two bands, with `EXTERNAL` folded into `ASSERTED`.** Rejected in §2: it hands an
  integration the standing reserved for the user's own word, and the supersession
  law's entire asymmetry rests on that standing being scarce.
- **Two bands, with `EXTERNAL` folded into `DERIVED`.** Rejected in §2: it calls a
  third party's record our inference and implies it is re-derivable by us, which
  ADR-0038 §2's recoverability argument depends on and which a stale calendar
  falsifies.
- **A `UserModelView` container type holding the partitioned tuples.** Rejected in
  §8: a struct that only groups carries no decision the band vocabulary does not,
  and it would be surface with no consumer — the discipline ADR-0028 §7 and
  ADR-0045 §1 each applied in their own lane.
- **Weighting retrieval by confidence in the store.** Rejected in §5. It conflates
  two axes into a number that recovers neither, and it makes derived beliefs
  systematically less visible exactly where visibility is the only correction
  mechanism they have.
- **Band-neutral top-k, partitioned by the consumer afterwards.** Rejected in §5.
  It reads as equivalent to per-band reads and is not: the truncation happens before
  the partition, so an assertion can be displaced below the cut by inferences it
  outranks.
- **Enforcing sub-1.0 derived confidence with a `Provenance` validator now.**
  Rejected in §3 and filed in §10. The validator has to be source-conditional
  because `EXTERNAL` may carry 1.0 (ADR-0038 §2a), and there is no producer yet that
  could violate the rule — ratifying an enforcement mechanism ahead of the code it
  constrains is how a seam that does not survive first use gets blessed
  (`CONTRIBUTING.md`, "Spike first if you need to").
- **Deciding the band-scoped read's signature here.** Rejected in §7. Naming a
  method without its consumer picks between enumeration and filtering on
  speculation; naming the obligation forecloses the wrong answer (adapter-side
  filtering of `export`) without guessing the right one.
- **Deferring the whole decision until the observer is designed.** Rejected: the
  retrieval path is band-blind today and harmless only because the derived band is
  empty. The reading rule has to be ratified before the first producer lands, or it
  is written under pressure from whatever the observer happens to emit.
