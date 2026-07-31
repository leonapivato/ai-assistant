# 77. The observer proposes beliefs from episodes, through the gate, on a named route

- Status: Partially superseded by ADR-0084 (§10 item 7's placement of the façade's observation result outside contract surface, and the header's restatement of that premise)
- Date: 2026-07-28
- Partially superseded: 2026-07-31 by ADR-0084 — **§10 item 7's claim that the
  façade's observation result is an `orchestration` type and not contract surface
  is false; everything this ADR decided about *what* that result conveys stands.**
  [ADR-0084](0084-the-local-api-and-the-cli-as-a-client.md) §5 finds ADR-0042 §1's
  revisit trigger fired and promotes the engine façade to a Protocol in
  `core/protocols.py`, which forces its result types into `core/types.py` (golden
  rule 2: a `core` Protocol cannot name an `orchestration` return type). ADR-0042
  §1 is partially superseded there, and the clauses below rest on it by citation.
  ADR-0084 §12 rules this record owed and defers it to its own lane (#536).

  **Replaced**, both clauses in §10 item 7:

  1. "The façade is concrete and not a contract (ADR-0042 §1), so those names are
     shape, not spelling (ADR-0073 §7)." The premise is false after ADR-0084 §5.
     **The conclusion outlives its premise, for a different reason**: ADR-0084 §4
     hands the exact set, the field layouts and the method signatures to a
     follow-on contract ADR (#281) rather than to an implementing lane, so these
     names are still shape and the spelling is still a later ADR's — ADR-0073 §7's
     form, reached now because the surface is ratified elsewhere rather than
     because it is not a contract at all.
  2. **The operative one.** "**Its result is an `orchestration` type beside
     `LearnOutcome`**, not a `core` one". `Engine.observe` returns
     `ObservationReport` (`orchestration/observation.py:305`, returned at
     `engine.py:1201`), which is inside the set ADR-0084 §4 promotes — the result
     types the promoted surface returns, and the transitive closure of what they
     name. It is therefore a `core` pydantic model frozen under ADR-0068 §1, not a
     frozen `orchestration` dataclass. **The practical consequence, which is the
     whole reason this record exists:** changing a field of that report was an
     `orchestration` edit and is now a `core` contract change under golden rule 5,
     owing an ADR. A reader acting on the superseded sentence would ship one
     without — the process failure ADR-0015 §5 exists to prevent — and this is not
     hypothetical: **#494 proposes adding a field to exactly this type**, to carry
     the `DeferralAdmission` the stage currently drops.

  **One clause of item 7 stays literally true and stops being sufficient**, which
  is worth separating out rather than sweeping into the quotations above. "It
  crosses no subsystem boundary, only `interfaces` (ADR-0022 §2's reasoning for
  `TurnResult`)" is still a true statement about where the value travels; what it
  no longer does is *entail* the conclusion drawn from it. ADR-0084 §4 promotes for
  a different reason — golden rule 2, forced by §5's Protocol — and ADR-0042 §1's
  "promotion to `core` is reserved for 'the day a subsystem needs to receive one'"
  is itself superseded there, the transport being what needs to receive one. The
  "beside `LearnOutcome`" adjacency survives the move as well: `LearnOutcome` is
  promoted by the same clause, so the two types still sit together, at a new
  address.

  **Also replaced, and it is not in §10.** The `Refs` list's gloss "ADR-0042 §1
  (the façade is concrete, not a contract)" restates the same premise and fails
  for the same reason. It is recorded because a reader who never reaches §10 meets
  it in the header, and because it is precisely the *paraphrase* the first
  enumeration passed over (ADR-0084 §12). The gloss beside it — ADR-0042 "§3 (one
  call in, one result out)" — is untouched: ADR-0084 §12 supersedes §1, §2 and §7
  of ADR-0042, and not §3.

  **Not replaced, and it is nearly all of this ADR.** The rest of §10 item 7
  stands: the stage selecting **at most** `observation_batch_size` episodes, so
  the producer's refusal (§1) guards a contract rather than a routine path; the
  four things the result carries and why they are kept apart — each proposal
  paired with the ruling it received rather than rendered from the ruling alone,
  the producer's two counts relayed unchanged, the separate count of proposals
  dropped at the write for unresolved evidence, and the route that is **absent
  when none read**; and the closing reason for the separation, that
  `ObservationOutcome`'s invariant is over the entries the model emitted. **What
  the result conveys is exactly as ratified; only its home and the cost of
  changing it move.**

  Nothing else in this ADR rests on the superseded premise, and each was checked
  by asking what it relied on ADR-0042 §1 *for*:

  - **§9's contract surface is untouched.** `Observer`, `ObservationOutcome`, the
    `Provenance` validator, `UnresolvedEvidenceError` and `MemoryWriter.ingest`'s
    refusal clause are a producer seam on the write path, not the façade.
    `ObservationOutcome` was already a `core` type and stays one — ADR-0084
    promotes nothing about it, and it is a different type from the façade's report,
    deliberately named apart. The header's "**This is a contract change** … one
    Protocol, one type, one validator, one error class" and the Consequences'
    "adds the least contract surface of the four" are true claims about *this
    ADR's own change* and stay true; ADR-0084 adding `core` types later does not
    make them retroactively false.
  - **§5's `DefaultMemoryPolicy` sentence stays true.** "The rule §5 puts on the
    *shipped* `DefaultMemoryPolicy` is a rule in a concrete policy, not contract
    surface" is about the policy, not the façade, and ADR-0084 promotes no policy.
    This is the sentence a lexical search for the phrase matched, and it is not
    the one that failed (ADR-0084 §12).
  - **§6's placement of citation resolution stays true, and is strengthened.**
    "The `orchestration` façade, on the belief views it already assembles — not in
    `interfaces/`" says where the work happens; an adapter that reaches the engine
    over a transport makes the case for keeping a live-at-now computation out of
    `interfaces` stronger, not weaker.
  - **§8's cadence conclusion stays true.** "Leg 5's scheduler … becomes a second
    caller of the same façade operation. Cadence then becomes configuration rather
    than a contract change" survives, because a second caller of an unchanged
    operation is not a change to it — the ruling ADR-0084 §12 makes for ADR-0078
    §8's "the hub adds push without touching this contract". §10's deferral of
    cadence to leg 5, "the façade operation is what the scheduler calls,
    unchanged", is intact for the same reason.

  **This note claims no closure beyond this file.** ADR-0084 §12 records that the
  first enumeration of ADR-0042 §1's fan-out was lexical and missed this ADR, and
  that a fan-out has to be found by asking what each citing ADR relied on the
  superseded one for; a record declaring itself exhaustive would repeat the error
  it exists to correct.

  ADR-0084 is `Accepted` and merged, so the `Status` line above names an ADR that
  exists and is ratified, and ADR-0070 §1's hazard — a line pointing at nothing —
  does not arise. Appended note per ADR-0070 §1: no text below it is rewritten,
  and the superseded sentences are left standing exactly as written.
- Note (2026-07-31): **The ADR-0081 amendment qualifier moves off the `Status`
  line into the note below; nothing about the amendment changes.** The line read
  `Accepted, §5's check-not-a-guarantee clause amended by ADR-0081`. Taking the
  leading `Partially superseded by` token above,
  [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §2
  applies: on a line led by that token no amendment qualifier is written, and
  "when a line takes the leading token, any qualifier already on it moves to the
  dated note in the same change". Left in place, `ADR-0081` would sit after the
  leading token and ADR-0070 §4's extraction invariant — "every `ADR-NNNN` after
  the leading `Partially superseded by` is a target" — would read ADR-0081 as a
  partial-supersession target of this ADR, which it is not; ADR-0081 §5 says so
  itself. This is a re-rendering, not a deletion: **the amendment stands in full
  in the 2026-07-29 note directly below**, which is untouched, and §5's third
  clause is bounded exactly as that note records. ADR-0082 §3's "ADR-0077's
  qualifier is correct as it stands and is not touched" was a statement about a
  plain `Accepted` line and is not contradicted — §2 is what governs the line this
  change writes. Refs #536, #477.
- Note (2026-07-29): **§5's third clause is bounded, not lifted.** Its statement —
  *"It is a check, not a guarantee. An episode deleted between the check and the
  write leaves a citation that no longer resolves, and no seam closes that"* —
  stands **verbatim for the case it names and argues**: a destruction by an actor
  *other than the ingest*, in the window between the check and the write, whose
  residue is a citation that **no longer resolves**. That is "the same two-store
  race ADR-0074 §8 accepted and bounded" its own justification names, and §6's
  handling of it — lazy resolution, a deleted-evidence tombstone, a lowered
  presented confidence, no rewrite — is **entirely unchanged**.
  [ADR-0081](0081-no-write-consumes-the-evidence-its-own-proposal-cites.md) §1
  refuses a different case the sentence read in isolation would sweep in: a write
  **the ingest itself performs**, landing at an id its own proposal cites, whose
  residue is a citation that **still resolves** — to the record that replaced its
  referent — and which §6 therefore cannot detect or render. ADR-0081 §5 applies
  ADR-0070 §1's test and records why that is an amendment noted here rather than a
  supersession: nothing §5 decided is replaced, and no reader acting on the clause
  or on §6 acts differently. §5's other clauses, §6 in whole, and every other
  section stand untouched.
- **This is a contract change.** §9 adds **one** Protocol — `Observer` — to
  `core/protocols.py`; **one** type — `ObservationOutcome` — and **one**
  source-conditional validator on `Provenance`, both in `core/types.py` (§7); and
  **one** error class, `UnresolvedEvidenceError(MemoryStoreError)`, to
  `core/errors.py` (§5) — the distinguishable subclass ADR-0079 §4 left open.
  Golden rule 5 therefore applies: this ADR ships as
  **its own docs-only PR**, is reviewed while still `Proposed` so a finding can
  still change the decision, and is flipped to `Accepted` on merge
  (`CONTRIBUTING.md`, "Contract ADRs land before their implementation";
  ADR-0015 §5). **No code changes with it.** Because the Protocol is *new*, the
  implementing lane owes the full triad — Protocol, shared conformance suite,
  canonical fake — in one change (`CONTRIBUTING.md`, "Adding a Protocol"), and
  stage 1 is this ADR merging.
- **Changes no existing Protocol's *shape*, and widens one's documented
  semantics.** `MemoryWriter.ingest` gains one refusal clause (§5): a `DERIVED`
  proposal whose evidence names no record the store holds is refused rather than
  written. No signature changes; the docstring and the conformance suite do,
  which is the review concern `CONTRIBUTING.md` names when a Protocol's meaning
  changes without its shape. `MemoryStore`, `MemoryPolicy`, `FeedbackProcessor`
  and `ConversationStore` are untouched — the rule §5 puts on the *shipped*
  `DefaultMemoryPolicy` is a rule in a concrete policy, not contract surface.
- **Amends and supersedes nothing.** Applying ADR-0070 §1's test to each ADR this
  decision touches:
  - **ADR-0072 §3** declined a `Provenance` validator explicitly and **filed the
    question for this lane** ("Whether `Provenance` grows a
    `DERIVED`-implies-sub-1.0 validator is filed (§10) for the observer's lane,
    which will be the first code that could breach it"). §7 answers a filed
    question; a reader of ADR-0072 was told the question was open and whose it
    was, and acts identically before and after.
  - **ADR-0072 §10** files "what happens to a derived belief whose evidence is
    later deleted or expires", and §3 names the three candidates — "retire it,
    keep it with its explanation degraded, or cascade the delete". §6 chooses the
    middle one. Choosing among options a prior ADR listed as open is not a change
    to what it decided.
  - **ADR-0072 §6** ("a derived belief that reaches a prompt is rendered as a
    belief, carrying its band and its confidence") is **discharged, not
    weakened**: §6 below decides *which* number that is once support has been
    destroyed — a case ADR-0072 could not reach, because it predates any producer
    of derived beliefs and any evidence that could be deleted. Nothing licenses
    omitting the confidence, and ADR-0072 §5's confidence-neutral `search` is
    untouched: the adjustment is presentational and never reorders retrieval.
  - **ADR-0073 §4** put a **gate** on this lane — "resolving citations into
    readable evidence is due with the first producer of derived beliefs, as a
    precondition of that producer shipping". §6 discharges it and answers "the
    open half of #431" that §4 handed here.
  - **ADR-0074 §4** constrained the `MemoryPolicy` rule this lane owes ("an
    `EPISODIC` record reaching the gate must not be refused for citing nothing").
    §5 writes the rule inside that constraint.
  - **ADR-0075 §2** names leg 3's observer as **not** covered by the capture
    exemption. §4 keeps it inside the gate, which is what that clause requires.
  No ADR's Status line is edited.
- **Refs:** the roadmap's leg 3 (the mandate: "a model-backed producer that reads
  episodes and proposes `OBSERVED`/`INFERRED` memories through the existing
  `MemoryPolicy` gate", and the two decisions it demands — "the scope of
  observation and what justifies retention" and "**which model reads the raw
  episodes**"), its leg 4 ("These land before the observer runs at volume"), its
  leg 5 (the hub's internal scheduler) and its stance 1 (propose/dispose is the
  existing chassis, given its most important producer); VISION §Principle 1
  ("every inference should have evidence, confidence, scope, and a way to be
  corrected"; "built chiefly by **observation**, not by interrogation"),
  §Principle 2 (selective memory; "observing broadly and retaining broadly are
  different things"; "watching is trustworthy only on those terms"); ADR-0004 §1
  (conversation history is Tier 1), §2 as amended (user data may be sent only to
  model providers the user has explicitly configured), §5 (logs are Tier 2), §6
  (data rights), §7 (data minimisation — "send the minimum necessary context to
  the model provider"); ADR-0005 §1 (the four kinds; `content` as the canonical
  rendering), §2 (`Provenance`; `evidence` as "references (e.g. episode ids)"),
  §3 (propose/dispose and the policy outcomes); ADR-0006 §2 (on-device embedding
  is the default, "so that memory content never leaves the device just to be
  indexed"; cloud is opt-in), §3 (embedders live in `models/`); ADR-0024 §1 (no
  runtime code fetches a model artifact), §6 (one vendored model, no
  arbitrary-model path); ADR-0061 §1 (the two vendor extras the installed
  artifact ships); ADR-0013 §4 (an explicit `model=` override disables routing),
  §6 (every route must be a provider the user configured, and the composition
  root owes it); ADR-0062 §4 (a per-route model override is deliberately not
  configurable); ADR-0007 §2 (retention enforced at read time); ADR-0009 §3
  (learning produces proposals; the pipeline closes the loop); ADR-0022 §3 (abort
  versus degrade, and why `memory_degraded` is on the outcome), §4 as amended by
  ADR-0028 §4 ("no proposals is a normal outcome"); ADR-0028 §1 (the writer's one
  method), §4 (`orchestration` injects and delegates; the same-store
  composition-root obligation), §5 (`MemoryStoreError` crosses the seam), §7
  (batch and transaction deferred, #104); ADR-0038 §1a (an assertion is its own
  warrant), §2 (the error asymmetry and re-derivability), §3 (derived never
  retires asserted); ADR-0040 §1 (`REINFORCE`/`SUPERSEDE` name the *relation*);
  ADR-0045 §4 (supersession closes a window), §5 (no fold onto a `USER_ASSERTED`
  target), §6 (read-time liveness); ADR-0047 §1 (injected seams), §2 (the ids are
  the planner's, never the model's), §6 (malformed output); ADR-0071 (the
  `raw_decode` extraction that replaced the brace slice, #293); ADR-0026 (the
  injected clock); ADR-0042 §1 (the façade is concrete, not a contract), §3 (one
  call in, one result out); ADR-0068 (the frozen record graph); ADR-0072 §1–§7
  and §10; ADR-0073 §1 (`None` means every value), §2 (bounded default, named
  order, out-of-range is a `ValueError`), §4 (the floor and the gate), §5
  (`delete` is unconditional), §7 (the façade is shape, not spelling); ADR-0074
  §3 (capture), §4 (what capture stamps and the two derived-band obligations), §5
  (why `get_many` was declined), §6 (episodes are excluded from retrieval and
  from the default listing), §7 (the episode horizon), §9 (the stores and the
  coordinator), §11 (its deferrals); ADR-0075 §1 (the scope replaced), §2 (the
  exemption is one producer wide and **does not reach the observer**), §5 (the
  sensitivity question handed here); #431 (the owner direction §6 ratifies), #432
  (§7 half-closes), #441 (the constraints §1 and §3 carry), #423 (ADR-0078, in
  flight); **ADR-0079** §3 and §4 (merged Accepted — the two obligations §5's
  third clause stacks on, its `MemoryStoreError` convention at this seam, and the
  distinguishable subclass it left open), #306, #104, #248, #425.

## Context

Legs 1 and 2 built the two halves this leg joins. ADR-0072 and ADR-0073 gave the
user a way to read and kill what the assistant believes, over a store whose
`DERIVED` band has never held a record. ADR-0074 and ADR-0075 gave that band its
substrate: every turn is durably recorded as an `EpisodicMemory`, written
directly, retained under a finite horizon, deletable by conversation. Both
surfaces are correct and one of them is empty. The roadmap's premise is that
closing that gap is worth more than any breadth it defers, because "a system that
learns only by dictation is the 'repeatedly explain preferences' failure
VISION.md opens by condemning".

The dated position, at the time of writing:

**Everything the producer needs exists except the producer.** `MemoryPolicy` and
`MemoryWriter` are shipped and wired; `Engine.learn` already runs proposals
through the writer; `list_beliefs` enumerates a band; `assistant beliefs` and
`assistant forget` render and destroy; episodes are captured on every turn and
excluded from retrieval and from the default listing (ADR-0074 §6). No code in
the tree constructs a proposal whose source is `OBSERVED` or `INFERRED`.

**Four forces make this a decision rather than an implementation detail.**

1. **The episodic stream is the most sensitive data the system holds**, and a
   model has to read it. The roadmap says so and demands the choice be explicit:
   "the on-device embedder (ADR-0006/0024) is the precedent, and the router seam
   (ADR-0013) makes a local/small-model route a named option rather than an
   accident of configuration". Left to the implementer, the observer would simply
   reach for the same `default_model` the planner uses, and the most consequential
   egress decision in the product would be made by whichever provider happened to
   be configured (§3).
2. **The gate is the mechanism that makes watching trustworthy, and it is not
   optional here.** VISION §Principle 2 is explicit that "a system that observes
   with no gate in front of memory and no inspection surface behind it is
   surveillance, not personalization", and ADR-0075 §2 names the observer as the
   paradigm case the gate exists for — "a model's inference about a person, which
   must be rejectable". What each of the six rulings *means* for a producer that
   emits many proposals per batch has never been worked through (§4).
3. **A derived belief outlives its evidence, by design.** Episodes carry a finite
   horizon (ADR-0074 §7) and the user may destroy a conversation at any time
   (ADR-0074 §8), while the belief distilled from it is retained indefinitely.
   ADR-0072 §3 named this and filed it; ADR-0073 §4 gated this lane on it. The
   owner ruled the direction on #431 (2026-07-28): **deleting a conversation does
   not delete the beliefs derived from it**, a destroyed citation becomes an
   explicit tombstone, and lost support may lower the belief's confidence. The
   mechanics are unratified (§6).
4. **Volume is the risk, and the roadmap sequences leg 4 against it.** Leg 4 says
   the epistemic-soundness fixes — `ASK_USER` with no resolution path (#423), the
   contradiction surplus (#313/#314), bounded-window retirement (#306) — "land
   before the observer runs at volume". So this ADR has to decide a trigger that
   *cannot* produce volume yet, without inventing machinery leg 5 will own (§8).

## Decision

### 1. The observer reads episodes it is handed, and can read nothing else

The observer is a **model-backed producer in `learning`** that takes a bounded
batch of `EpisodicMemory` records and returns `MemoryUpdateProposal`s — with the
two discard counts §4 requires, as one `ObservationOutcome` (§9). That is the
whole of its input.

**It holds no store handle, and that is the scope limit rather than a rule about
it.** `Observer.observe` receives the episodes; it cannot fetch more, cannot
widen its own batch, cannot read a belief, a plan, an audit record or a
permission decision, and cannot reach `MemoryStore` at all. The alternative — a
producer holding a store and choosing what to read — would make "the scope of
observation" a property of the producer's code rather than of a ratified seam,
and every later reviewer would have to re-derive it by reading an implementation.
Here it is a type: episodes in, proposals out.

**Selection therefore belongs to `orchestration`**, the one place that
legitimately holds both stores by injection (ADR-0074 §9, the same ruling that
put the two-store sweeps there). It selects the batch; the producer judges it.

**The store's read-time axes do the filtering for free.** The stage can only
select episodes the store still returns, and `get`/`search`/`list_beliefs` never
return an expired or non-live record (ADR-0007 §2, ADR-0045 §6). A deleted
conversation's episodes are destroyed (ADR-0074 §8). So an episode the user has
put beyond reach is beyond the observer's reach too, with no separate filter to
keep in step — which is the failure a second filter would eventually have.

**A batch is a set of episodes, not a conversation.** Nothing in the Protocol,
the producer, or the prompt requires the batch's members to share a conversation,
and the producer never asks which conversation an episode came from. This is
#441's leg-2 constraint carried forward at no cost: ADR-0074 §3 made an episode
belonging to no conversation the *default* shape, and a producer that keyed on
conversation membership would have re-imposed "episode = turn" one layer up,
where leg 6's ingested sources and #441's captured moments would have to be
retrofitted around it.

**The batch is bounded, and the bound is named here rather than left to the
lane.** `Settings` gains `observation_batch_size: int`, **defaulting to 20 episodes and
bounded to `[1, 2**63)` at load** — positive because a zero batch observes
nothing while reporting health, and bounded above because the batch is read
through `ConversationStore.turns`, whose `limit` "outside `[0, 2**63)`" is a
`ValueError` by its own contract (§8). A setting the store read would refuse must
fail at load, not at the first observation: that is what `load_settings` promises
for every other value there. Every read in
this system is bounded (ADR-0021 §4, ADR-0073 §2) and this one is also a *prompt*
and an *egress*: an unbounded batch is a prompt nobody sized and a payload nobody
measured. The default is deliberately small — a handful of exchanges, not a
month of transcript — because §3 sends this batch to a model and §8 keeps the
producer's output proportional until leg 4 lands. Naming the figure follows
ADR-0074 §9.3's ruling that "the defaults are named, not left to the
implementation": two conforming stages picking 20 and 2,000 would send
categorically different amounts of Tier 1 data while each believed it conformed.

**A batch is a set: an episode appears in it at most once.** A batch carrying the
same episode id twice is refused with a `ValueError`, for the reason the floor in
§5 exists: two prompt entries for one episode, cited by the model under two
labels, would let a single observation supply the two *distinct* supports an
`INFERRED` belief owes, and would raise the confidence §5 computes from that
count. Support is therefore counted over **distinct episode ids** — belt and
braces, because the count is the thing the floor and the confidence both rest on
— and a caller handing the producer the same episode twice has a bug in its
selection, which a silent de-duplication would hide rather than fix.

**An oversized batch is refused, never truncated.** The producer is constructed
with its maximum and raises `ValueError` on a batch larger than it — the posture
ADR-0073 §2 set for an out-of-range read argument ("out of range is a
`ValueError`, not a clamp"), and ADR-0022 §4a's reason for validating tuning at
construction: a silent truncation disables half the work while the caller keeps
reporting health, and the episodes the caller believed were observed were never
read. The obligation is on the seam because the Protocol is a cross-subsystem
contract: a stage that bounds its own selection is not evidence that the *next*
caller will.

### 2. What it may propose: three kinds, two epistemic steps, and a utility bar

**Kinds.** The observer proposes `SemanticMemory`, `PreferenceMemory` and
`ProceduralMemory` — never `EpisodicMemory`. An episode is a record that
something happened, and the only thing entitled to write one is the deterministic
capture path that was present when it happened (ADR-0074 §3, ADR-0075 §2). A
model-authored episode would be a fabricated event wearing the type reserved for
witnessed ones, and it would be *cited* by later beliefs as though it were
evidence. The observer distils evidence; it does not manufacture it.

**Epistemic step.** Every proposal is `OBSERVED` or `INFERRED`, and the producer
chooses between them on ADR-0072 §3's test — whether the cited evidence *entails*
the belief or merely *supports* it. Both land in the `DERIVED` band (ADR-0072
§2), so nothing about the supersession law depends on the choice; what depends on
it is the confidence the producer assigns (§5) and the floor on how much evidence
a proposal needs (§5). ADR-0072 §3's own reason is why the distinction is worth
carrying: "a wrong `OBSERVED` record is a recording bug… a wrong `INFERRED`
record is a reasoning error over evidence that is itself correct", and a producer
that cannot tell them apart "is not entitled to either label".

**The bar for proposing at all is durable usefulness, not interestingness.** A
proposal is warranted only when the belief is **about the user** and would change
a later answer — a preference, a durable fact about them or their world, a
workflow they follow. Summarising the exchange is the failure mode: it turns the
belief store into a second transcript, at indefinite retention, behind the
surface that answers "what do you believe about me". This is VISION §Principle
2's "remember selectively… avoid preserving sensitive or incidental details
without justification" stated as a producer-side rule, and it is the half of that
principle a gate cannot enforce, because a policy judging one proposal at a time
cannot see that all twenty of them are a retelling.

**Output is bounded per batch, and the bound is named**: `Settings` gains
`observation_max_proposals: int`, **positive, defaulting to 5**, and excess is
**discarded rather than queued**. A model asked to observe will happily emit
twenty beliefs about one conversation; nothing downstream would reject them
individually, and leg 4's soundness work has not landed (§8). Five is the
selectivity bar above, in numbers: a batch that genuinely yields more durable
beliefs than that is a batch worth observing twice. Discarding rather than
queueing keeps the bound honest — a queue is durable state this ADR does not
ratify, and the episodes remain in the store, so a later run over the same batch
can propose what this one dropped. The bound is on the **producer's return
value**, so it holds whatever the model emits and whatever the stage does next.

**Sensitivity: the tiering question ADR-0075 §5 handed here is answered by
declining a category filter.** Every belief the observer proposes is Tier 1
personal data, so `MemoryUpdateProposal.sensitivity` is `PERSONAL` on every
proposal, and there is deliberately no observer-side taxonomy of forbidden
subjects. Two reasons, and the second is the one that decides:

- **The vocabulary does not exist.** ADR-0004 §1's three tiers are the whole of
  it, and "health", "sexuality", "finances" are not tiers. Inventing a
  sensitive-category enum here would ratify a taxonomy on the strength of one
  producer's need, in the ADR that has the least evidence about how it would be
  used.
- **A subject filter would be the wrong instrument even if it existed.** An
  assistant that refuses to model the user in the areas they talk about most is
  not more trustworthy; it is less useful and equally observant. The mechanism
  VISION §Principle 2 actually names is the one this ADR uses: propose, dispose,
  render with provenance, delete on demand. `sensitivity` stays on the proposal
  because a *deployment* may give its policy a stricter rule (the shipped policy
  already defers every `SECRET`-tier proposal to the user), and that is where a
  bar belongs — at the gate, deterministic and reviewable, not inside the model
  that is doing the observing.

### 3. Which model reads the episodes: a named route, no fallback, minimal payload

This is the decision the roadmap demands be explicit, and it has four parts.

**The observer's model route is its own named configuration.** `Settings` gains
`observer_model: _ModelSpec | None`, beside `default_model` and
`fallback_models`. Unset — the default — means the observer reads through the
route the operator has *already* configured for conversation. Set, it names the
route that reads episodes, and the composition root builds it like any other.

Unset-means-the-conversational-route is chosen over off-by-default and over a
distinct required value for one reason: **it widens nothing.** ADR-0004 §2's
property, as amended, is that user data reaches only providers the user
explicitly configured, and a default that names no new provider cannot breach it.
An off-by-default observer would make leg 3's exit test unreachable without
configuration, and a *required* second spec would make the commonest correct
setup — one provider, used for everything — an error.

What the setting buys is that **the choice is nameable, visible and separable**.
An operator who wants the episodic stream read by a smaller, cheaper or
locally-hosted model changes one setting and does not touch the route their
answers come from. Without it, the two are the same decision by accident of
configuration, which is precisely the accident the roadmap asks this ADR to
prevent.

**The observer's call never falls back.** Whatever route it names, a failure is
not re-sent to a second provider. ADR-0013 §4 already rules the mechanism — "a
caller who names a model has already chosen" — and here the reasons are its own
Consequences read against this payload:

- **Fallback's cost is that "more providers may see a given prompt"** (ADR-0013
  §Consequences). For a turn that buys an answer the user is waiting for. For an
  observation it buys nothing, because **observation is deferrable**: the
  episodes are durable, nothing is waiting, and the free remedy is to run again.
- **It is the one payload where the trade inverts.** A turn's prompt is one
  utterance; an observation's prompt is accumulated history. Widening the set of
  recipients for reliability is exactly what ADR-0004 §7's minimisation rule
  argues against when the reliability buys nothing.

So a routable failure that would advance a turn to the next candidate simply ends
the observation, and the failure is reported (§4).

**The payload is the batch and nothing else.** The prompt carries the episodes'
canonical `content` (ADR-0005 §1) and what the model needs to cite them (§5). It
does **not** carry the user's existing beliefs, the profile, the context facet,
or a plan. Sending beliefs would be the obvious way to stop the observer
re-proposing what is already known — and it is refused, because de-duplication is
the gate's job and the gate is deterministic and local: a repeat is folded into a
`REINFORCE` (§4). Paying for that with a second class of Tier 1 data in the
prompt would be minimisation (ADR-0004 §7) traded away for something already
solved. Nothing about an episode or a proposal reaches a log (ADR-0004 §5).

**On-device is the direction, and it is stated as such rather than pretended.**
ADR-0006 §2 made on-device embedding the default "so that memory content never
leaves the device just to be indexed", and ADR-0024 turned that model into a
build input. The same argument applies with more force here — reading the
transcript is a stronger act than indexing it — and it **cannot be honoured
today**: ADR-0024 §6 vendors exactly one model and it is an embedder, ADR-0061 §1
ships two vendor extras and both are hosted, and `Settings` has no endpoint
configuration with which to name a locally-hosted OpenAI-compatible route. So
this ADR ratifies the shape rather than a claim: the route is a first-class
named setting, so the day a local generative route is realizable it becomes a
configuration change and this decision's default is revisited (§11,
Consequences). #441's leg-3 constraint is carried here: the same setting is
where local transcription and distillation would point, which is another reason
it is a route rather than a boolean.

**The observe outcome names the route that read the episodes.** ADR-0013 §6
records as an open gap that "which provider answered is not currently reported,
and should be once there is an interface to report it". This operation is that
interface for the one call where it matters most, and the report is to the user
on the result — never to a log, which ADR-0013 §2 keeps free of model ids.

### 4. The write path: proposals through the ratified gate, ruling by ruling

**The observer writes nothing.** It returns proposals; the `orchestration` stage
ingests each through `MemoryWriter.ingest`, in order and independently, exactly
as `learn` already does (ADR-0009 §3, ADR-0028 §4). The producer holds no writer
and no policy, so it cannot rule on its own output — which is the entire content
of "the model proposes; a deterministic policy disposes" for the producer the
principle was written for (ADR-0005 §3, ADR-0075 §2).

There is no transaction, and this ADR adds none: ADR-0028 §7 deferred batch and
transaction (#104), and a partially applied batch of independent beliefs is not
the failure a transaction exists to prevent. The producer leaves
`MemoryUpdateProposal.conflicts` empty: conflicts are resolved by the writer, in
the same call that rules on them, and are "not supplied by the caller" (ADR-0028
§3). A producer that filled them would be re-deriving `memory`'s conflict
semantics — the duplication ADR-0028 exists to remove.

What each ruling means for this producer:

| Ruling | What happens | Why it is right here |
| --- | --- | --- |
| `ACCEPT` | The belief is stored, citing its episodes. | The intended path. |
| `REINFORCE` | Folded into the conflicting record at the target's id. | **This is how accumulation works**, not a duplicate-write bug: observing the same thing again strengthens the belief instead of creating a second one (ADR-0040 §1). |
| `SUPERSEDE` | The conflicting *derived* record is retired, window closed. | A later observation may overturn an earlier inference. It can never reach an assertion: no fold lands on a `USER_ASSERTED` target (ADR-0045 §5), and derived never retires asserted (ADR-0038 §3). |
| `STORE_TEMPORARY` | Stored with the policy's TTL. | A thin belief gets a window instead of permanence. Intended, and now reachable: the producer's confidence ladder (§5) can fall below the policy's `min_confidence`. |
| `REJECT` | Nothing is stored, and nothing is retried. | The gate refusing a proposal is the gate working. Re-proposing it would be arguing with a deterministic policy. |
| `ASK_USER` | Nothing is stored; the proposal is **reported**, not dropped. | Below. |

**Two of those six are unreachable for this producer under the shipped policy,
and that is stated rather than left for an implementer to notice.**
`DefaultMemoryPolicy` rules `SUPERSEDE` only for a *user-asserted* proposal; a
non-asserted proposal with conflicts rules `REINFORCE`, and one whose conflicts
include an assertion rules `ASK_USER`. `REJECT` likewise has no rule that reaches
it there. The table is the contract's vocabulary, not a prediction of what today's
policy emits: the stage handles all six because the policy is injected and a
deployment may run a stricter one, and because ADR-0079 has already changed what
a conflict-heavy ruling does — a correction now resolves every conflict it is
shown or refuses to land. What the observer must never do is
depend on a ruling being unreachable.

**`ASK_USER` is the observer's most likely deferral, and its resolution is
ADR-0078's problem.** The shipped `DefaultMemoryPolicy` defers whenever a
non-asserted proposal conflicts with a user-asserted record — "an inference never
silently overrides a user-asserted memory". That is ADR-0038's asymmetry working
exactly as designed, and it is the case the observer will hit most, because the
beliefs it forms are about the same topics the user has corrected. Today that
ruling has no resolution path and the conflict is silently dropped (#423).

This ADR **names the dependency and does not design the mechanism**. ADR-0078 is
in flight for #423 and owns what a pending memory decision is, how it is
surfaced, and how a resolution flows back through the writer. What the observer
owes it is one property, stated so ADR-0078 can rely on it:

**A deferred proposal is self-contained, so that a durable pending state can hold
it without the producer changing.** Everything needed to re-adjudicate it later
travels in the `MemoryUpdateProposal` itself — the candidate record, its cited
episode ids, its rationale — rather than in producer-side context that only
existed during the call. The producer therefore neither retries a deferral, nor
escalates it, nor rewrites the proposal to avoid it, nor holds it to re-submit.

**It is not durable today, and this ADR does not claim otherwise.** No component
persists a deferred proposal: the ruling is reported on the observe outcome and
the process then exits, so that particular deferral is gone. That is #423's gap,
and closing it — deciding what a pending memory decision *is*, where it lives,
and how a resolution flows back through the writer — is exactly ADR-0078's
decision, which is why this ADR neither invents a store for it nor pretends the
property exists. What this ADR does is make the deferral **visible** in the
interim, where today it is invisible: the observe outcome carries, per deferred
proposal, the candidate's content, its citations and the policy's stated reason —
not merely a count and a `None` record id. That is enough for a user to act on it
in the same session with the surfaces leg 1 already shipped (assert it themselves,
or forget the belief it conflicts with), and it is deliberately not a queue.

**Failure behaviour follows ADR-0022 §3's rule**, applied to an operation the
user asked for:

- **A model failure propagates** — `ModelError`, unwrapped, its classification
  intact (ADR-0013 §5). The user asked for observation and it did not happen;
  returning "no beliefs" would be indistinguishable from "nothing to learn",
  which is the failure `memory_degraded` exists to prevent (ADR-0022 §3).
- **A malformed response degrades**: entries the producer can use are proposed,
  entries it cannot are discarded and **counted**. Nothing is invented to fill a
  gap. The extraction contract is ADR-0071's `raw_decode` scan, never ADR-0047 §4
  step 1's superseded brace slice — a second producer re-deriving that mechanism
  would reintroduce #293.

  **The response is one envelope carrying a list of entries** (ADR-0047 §4's
  shape), and **an envelope that does not decode at all counts as exactly one
  entry, and that entry is `discarded_unusable`** — a synthetic unit, so the
  invariant below has a denominator here too. Without it, `I cannot help` yields
  zero proposals and zero discards, which is indistinguishable from a model that
  looked at the batch and honestly proposed nothing — the one confusion this
  counting exists to remove. **The producer does not re-prompt.** ADR-0047 §6
  repairs because a turn has no answer without a plan; an observation has nothing
  waiting on it, so the cheap remedy is a later run rather than a second call
  inside this one.

  **Counting is why the producer returns a value rather than a sequence.** A bare
  `Sequence[MemoryUpdateProposal]` cannot say whether five proposals are five
  good entries, ten of which five were unusable, or ten of which five exceeded
  §2's bound: the three are indistinguishable at the seam, and only the producer
  can tell them apart. Silence would then read as success — the failure ADR-0022
  §3 put `memory_degraded` on the outcome to prevent. So `observe` returns an
  `ObservationOutcome`: the proposals, plus two discard counts (§9).

  **The two counts are exhaustive and disjoint, which takes an order.** The
  producer **validates every entry first, and applies §2's bound only to the
  entries that survived**. So `discarded_unusable` counts **every** entry the
  producer refused for any reason of its own — unparseable, failing validation,
  citing a label that is not in the batch, below §5's evidence floor, or naming a
  kind §2 forbids — and `discarded_over_limit` counts only usable proposals
  dropped to meet the bound. **The proposals returned plus the two counts equal
  the number of entries the model emitted** — an undecodable envelope counting as
  the one synthetic entry above — and no entry lands in both.

  The order is ratified rather than left to the implementer because both halves
  of it are observable. Capping first would put an unusable entry into
  `discarded_over_limit` when it happened to sit past the cut and into
  `discarded_unusable` when it did not, so two conforming producers would report
  different outcomes for one response — and, worse, it would let a malformed
  entry occupy a slot a good one could have filled, so a model that emitted six
  entries of which one was junk would yield four proposals instead of five. Without that invariant a drop can fall between the two
  buckets: an entry citing an unknown label parses cleanly and is inside the
  bound, so it would be discarded silently and the outcome would be
  indistinguishable from a model that proposed nothing — which is the same
  silence this bullet exists to remove, one level down. A finer taxonomy of
  reasons is deliberately not carried: the user's question is "did anything get
  thrown away", and a reason enum would be surface with no consumer.
- **A writer failure propagates** as `MemoryStoreError` (ADR-0028 §5) and
  **nothing is reported**, which is ADR-0022 §4's ruling applied unchanged:
  proposals are applied in order and independently, there is no transaction, and
  "reporting success for a partially applied set would be a claim about memory
  integrity this loop cannot make". So the honest statement of the guarantee is
  the uncomfortable one: **the operation raises, an unknown prefix of its
  proposals is already stored, and the result is indeterminate from the
  exception**. This ADR adds no partial-result error type to soften it — that
  would be a new failure transport built for one caller, where the recovery path
  already exists and is the one leg 1 shipped: `assistant beliefs` shows exactly
  what landed, and `forget` removes any of it. #104 is what closes it properly,
  and it is a memory-contract decision rather than an observer one.
- **No proposals is a normal outcome**, not an error (ADR-0022 §4).

### 5. Evidence discipline: what a proposal cites, and what is refused for citing badly

**Every proposal cites at least one episode id, and the ids are the producer's,
never the model's.** ADR-0072 §3 rules that "a proposal in the `DERIVED` band
cites at least one evidence reference" and that "an evidence reference denotes
the id of a record in the same store". The model does not supply store ids: it
references episodes by a label the prompt assigned to the batch, and the producer
maps each label back to the id of the episode it actually read. This is ADR-0047
§2's rule — "the step ids and the plan id are the planner's, never the model's" —
applied to citations, and it is load-bearing rather than stylistic: a model that
can write an id can write one for an episode it never saw, and the provenance
display would then confidently cite a record that has nothing to do with the
belief.

**A label that does not map is dropped, and a proposal left citing nothing is
discarded.** It is never repaired by attaching the batch wholesale: evidence
attached to satisfy a rule is not evidence, and it would make the "why do you
believe that?" answer a list of everything the observer happened to be reading.

**`INFERRED` needs more than one episode; `OBSERVED` may rest on one.** ADR-0005
§Context names the failure this floor exists for — "a single unusual interaction
can harden into a permanent, wrong 'preference'" — and ADR-0072 §3 supplies the
line: an `OBSERVED` belief restates what its evidence directly shows, so one
episode entails it; an `INFERRED` belief generalises beyond the evidence, and a
generalisation from one instance is the exact shape of that failure. The count is
over **distinct episode ids**, never over citations: two labels resolving to one
episode are one support, which is the same rule §1's duplicate-batch refusal
enforces from the input side. Below the floor the producer proposes nothing, and
the entry it dropped is counted (§4).

**The floor is the producer's, not the gate's**, and this ADR says which is
which, because two rules that look alike would otherwise drift:

- **The policy rule** — **emptiness**. `DefaultMemoryPolicy` gains a rule: a
  proposal in the `DERIVED` band citing **no** evidence rules `REJECT`. This is
  the rule ADR-0072 §3 assigned to this lane, at the enforcement point it named
  ("the enforcement point is the `MemoryPolicy` gate, not the type… a policy can
  state the rule for the band it is judging without constraining `EXTERNAL` or
  `USER_ASSERTED` records that legitimately cite nothing"). It is band-wide and
  minimal, because the gate serves every producer and cannot know which epistemic
  step a record took. **It exempts `EPISODIC` records**, as ADR-0074 §4 binds it
  to — an episode's warrant is that it happened, and requiring it to cite
  something would demand a regress. That exemption guards a path nothing takes
  today (capture does not reach the gate, ADR-0075 §1; and §2 above forbids the
  observer to propose an episode), and it is written anyway so the rule is not one
  refactor away from making its own substrate unwritable. It is listed among what
  the implementing lane owes, with its tests (§9) — a rule this ADR ratifies and
  nobody is obliged to build is not a rule.
- **The writer floor** — **resolvability**, below. The two do not overlap: an
  empty tuple names no record that fails to resolve, so it passes the writer and
  is caught by the policy; a populated tuple naming a record the store does not
  hold passes any policy and is caught by the writer.
- **The producer floor** (`INFERRED` ≥ 2): the observer's own discipline, stated
  here so a second observer inherits it rather than reinventing a weaker one.

**Why emptiness is not *also* a writer floor**, though the writer is the seam
every producer crosses and a deployment injecting its own `MemoryPolicy` could
therefore store an unsupported derived belief. That limit is accepted, named, and
inherited rather than introduced: ADR-0072 §3 chose the policy seam deliberately,
and the shape of a writer floor in this system is ADR-0045 §5 clause 1 — a
refusal to *apply* a ruling the policy already made ("no fold of any kind onto a
`USER_ASSERTED` target… remains an obligation on every writer"). A floor that
pre-empted the ruling instead would make the policy's `REJECT` unreachable for
the case, turning a reportable decision the user can read into an exception, and
would put one rule in two places to drift. What a deployment's own policy permits
is that deployment's floor to set; what it cannot escape is the resolvability
check, because that one cannot live at the policy at all.

**Confidence is computed by the producer, and never taken from the model.** It is
a deterministic, pure function of the epistemic step and the number of distinct
supporting episodes, with these ratified properties:

- strictly below 1.0 always — 1.0 is the standing only the user's own word
  carries (ADR-0072 §3), and §7 makes that mechanical;
- an `OBSERVED` belief on the same support outranks an `INFERRED` one, since the
  latter took a step the evidence does not entail;
- non-decreasing in the number of supporting episodes, under a ceiling;
- no clock, no randomness, no model-supplied number.

The exact values are the implementing lane's, exactly as ADR-0074 §4 ratified
"a documented constant strictly below 1.0" and left the constant to the lane.
Two things this buys, and both matter more than calibration: a model-supplied
confidence is the model's mood rather than a comparable quantity, so nothing
downstream could read two proposals' numbers against each other; and because the
function is deterministic on its inputs, **re-observing the same episodes cannot
inflate a belief** — the same evidence yields the same number, and a `REINFORCE`
that takes the maximum finds nothing higher (§8).

**Write-time resolvability is the writer's obligation.** `MemoryWriter.ingest`
refuses a proposal in the `DERIVED` band whose evidence names a record the store
does not hold. This closes the first half of #431 in the lane ADR-0072 §3 named
("a `MemoryWriter` obligation and a conformance clause, which belongs to the lane
that has a producer capable of breaching it"), and it is what makes §6's
tombstone unambiguous: **every citation resolved once**, so a citation that stops
resolving is *loss*, never a producer bug. Two clauses fix its shape:

- **It refuses rather than rules, and it raises what every other
  writer-boundary refusal raises.** The writer does not return a fabricated
  `REJECT`: a decision is the policy's to make (ADR-0005 §3), and a writer
  inventing one would put a ruling nobody made into the ingest result. The
  refusal is a **`MemoryStoreError`** — the class `MemoryWriter.ingest` already
  documents and the one ADR-0079 §4 chose, days ago, for the other refusal at
  this seam, on the ground that it "is what every other writer-boundary refusal
  raises (`_refuse_unsafe_fold`, `_close_window`, `_checked_id`)". A `ValueError`
  was the wrong instrument for a second reason: `AssistantError` is the CLI's
  runtime failure boundary, and an error that escapes it surfaces to the user as
  a crash rather than as a rendered failure.
- **It is a *named* refusal, because the stage cannot otherwise tell a race from
  a bug.** An episode is selected while live (§1) and the model call suspends for
  a round trip, so a citation can expire under ADR-0074 §7's horizon — or be
  deleted with its conversation — between selection and the write. That is an
  ordinary outcome of a finite retention horizon, not a producer fault, and an
  undifferentiated refusal forces the stage to choose between aborting a batch
  that is working and swallowing real faults to avoid it. So `core/errors.py`
  gains **`UnresolvedEvidenceError(MemoryStoreError)`**, **carrying the
  unresolved ids**. This is precisely the subclass ADR-0079 §4 named and left
  open — "a distinguishable subclass… is **not** decided here; adding one later
  is additive under `except MemoryStoreError` and needs no decision reversed" —
  taken by the lane that has the consumer, in the shape ADR-0076 §2 gave
  `UnknownConversationError` for the identical dilemma.

  **The stage drops that proposal, counts it, and carries on with the rest —
  but only for ids it selected.** The writer sees "this id does not resolve" and
  cannot tell an expiry from a producer typo, so the discrimination belongs to
  the one component that knows: the stage compares the unresolved ids against the
  batch it selected. **Every unresolved id in the batch** — the evidence went
  away under it, which is the race — the proposal is dropped and counted, and the
  remaining proposals are still ingested. **Any unresolved id outside it** — the
  producer cited something it was never handed, which is the fault §5's mapping
  rule exists to prevent — the error propagates. The quantifier is "every",
  deliberately: a proposal citing a selected episode that expired *and* a foreign
  id would otherwise be droppable, and dropping it would bury the producer bug
  under the race that happened to accompany it. A fault plus an expiry is still a
  fault. The dropped proposal is worthless anyway: a belief whose only
  support no longer resolves cannot answer "why do you believe that?", and
  storing it would manufacture at birth the all-tombstoned state §6 handles for
  beliefs that earned their evidence first. This is what keeps §5's guarantee —
  **nothing unsupported is ever stored** — from turning an expiry into a failed
  operation.

  **The count is the stage's, not the producer's** (§9). `ObservationOutcome`'s
  two counts are exhaustive over the entries the *model* emitted (§4) and must
  stay that way; a proposal the producer legitimately made and the writer then
  refused is a different fact, and folding it into either count would misreport
  the model's output.
- **It is a check, not a guarantee.** An episode deleted between the check and
  the write leaves a citation that no longer resolves, and no seam closes that:
  it is the same two-store race ADR-0074 §8 accepted and bounded, arriving from
  the other side. §6 is what makes the residue honest rather than a dangling id.

### 6. When the evidence is destroyed: a tombstone, a lowered presentation, no rewrite

This section ratifies the owner's #431 direction (2026-07-28) as mechanics.
**Deleting a conversation does not delete the beliefs derived from it.** The
alternative — cascading the delete — is refused for the reason the direction
gives it: a user deleting a conversation asked for the conversation to be gone,
not for the assistant to unlearn what it worked out. Retiring the belief instead
is the same act with a softer name.

**Citations are resolved lazily, at the surface that presents the belief, and no
stored record is ever rewritten.** The evidence tuple keeps the ids as written;
a presenting read resolves each through `MemoryStore.get` and renders what it
finds. Eager rewriting at destroy time is refused, and the argument is decisive
rather than economic:

- **It would cover the rare case and miss the common one.** Most evidence loss is
  **expiry**, not deletion: episodes carry a finite default horizon (ADR-0074 §7)
  and retention is enforced at *read time* (ADR-0007 §2), so there is no
  per-episode event at which an eager rewrite could fire. An eager mechanism
  would handle the conversation deletion and silently leave every expired
  citation dangling — the worst of both, since the surface would then have to
  handle the lazy case anyway.
- **It would need a reverse index and a write fan-out.** "Which beliefs cite id
  X" is a read no store offers; deleting a long conversation would then rewrite
  an unbounded set of beliefs inside the deletion protocol ADR-0074 §8 already
  spent a section making crash-safe.
- **It would edit a belief because of something that happened to another
  record.** The record graph is frozen (ADR-0068), and ADR-0072 §4's shape — a
  correction retires and rewrites rather than editing — is the posture this
  system takes when a belief must change. Nothing about losing evidence is the
  producer changing its mind.

**A citation that does not resolve renders as an explicit deleted-evidence
tombstone.** Not a bare id, not a silent gap — ADR-0073 §4's floor already
forbids both ("a citation the surface cannot render as evidence is never rendered
*as* evidence — not as a reassuring id, not silently dropped"). The tombstone
says an evidence item stood here and is gone, and **it deliberately does not say
what it was**. That residue is ratified rather than tolerated: it is the price of
an honest provenance display, and it is the same shape ADR-0074 §9 already
accepted internally for a turn row that outlives its episode. The rendering also
does not distinguish *deleted* from *expired*, because the read cannot tell them
apart and because the user's question — "is there still something behind this?" —
is answered by absence either way.

**Presented confidence falls with lost support; stored confidence does not
move.** The number a surface shows is a pure function — no clock — of the stored
confidence and how many of the belief's citations still resolve, **bounded above
by the stored confidence and below by `min(stored confidence, floor)`**, where
the floor is a documented positive constant. Inside those bounds it equals the
stored value when every citation resolves, and each further citation lost lowers
it **strictly while it is above the effective floor** and leaves it unchanged
once it has reached it — which, where the stored value was already at or below
the floor, is from the first loss onward. The
exact function is the implementing lane's.

**The lower bound is `min(stored, floor)` rather than the floor itself, and the
difference is the whole of the edge case.** `Provenance.confidence` permits
`0.0`, and §5 binds only *this* producer to a positive ladder, so a belief can be
stored at or beneath the floor — where an absolute floor and "never above stored"
have no value between them at all. Capping the floor by the stored value keeps
both bounds satisfiable everywhere: above the floor, degradation runs and stops
there; at or below it, the two bounds coincide, the adjustment is a no-op, and
the loss is carried by the tombstones beside the number. That is the honest
signal anyway — a value that has run out of room to fall says nothing about how
much support went away, which is what the tombstones are for.

Three consequences of that split are decided here rather than left to be
discovered:

- **It is presentation, never ranking.** `MemoryStore.search` stays
  confidence-neutral (ADR-0072 §5) and nothing about retrieval order changes.
  This is the owner's constraint and it is also what makes lazy resolution
  coherent: a number computed at presentation cannot reorder a store it never
  touches.
- **Every surface that states a confidence states the adjusted one.** The
  inspection surface today; the prompt assembler when that lane lands, which
  ADR-0072 §6 already obliges to convey a belief's confidence. Two surfaces
  quoting different numbers for one belief would make the disclosure rule
  meaningless.
- **`export` carries the record as stored** — the ids as written and the stored
  confidence — because an export is the user's data as held, not a rendering of
  it (ADR-0007 §3). An exported id that no longer resolves is the same
  that-not-what residue as the tombstone, in the artifact where the user can see
  everything else too.

**Where the resolution happens.** The `orchestration` façade, on the belief
views it already assembles — not in `interfaces/`, which golden rule 3 keeps thin
and which ADR-0072 §7 already refused to give a live-at-now computation. The
listing resolves *existence* and renders the count, the lost count, and the
adjusted confidence; the single-belief view renders the surviving citations as
readable evidence and the lost ones as tombstones. **That discharges ADR-0073
§4's gate**, which made resolving citations into readable evidence a precondition
of this producer shipping.

The cost is a `get` per citation per presented belief, bounded by the page
(ADR-0073 §2's default of 50) and by evidence tuples that are small by
construction (§5's floor is a minimum, not a target). It is accepted for now and
it gives ADR-0074 §5's declined `get_many` its second consumer — revisited with
the hub, where a resume already crosses a transport (§11).

**A belief whose citations are *all* tombstoned is held, marked, and answerable —
not silently kept and not auto-destroyed.** It stays live at its **effective
floor — `min(stored confidence, floor)`, the lower bound above** — which is the
floor itself for every belief stored above it and the stored value for one that
was never above it. The surface says in as many words that nothing supports it
any more; the number is what has room to say, and the tombstones say the rest. The three candidates were weighed on merits:

- **Auto-retire** is refused: it is the cascade under another name, it destroys a
  belief that may be perfectly true, and it makes the user's deletion of an old
  conversation silently undo an accumulation they never asked to lose.
- **Held at the effective floor, and nothing else**, is refused as the *whole*
  answer: an
  unsupported belief that keeps reaching prompts with no way for the user to be
  asked about it is the "wrong record laundered into a fact" ADR-0072 §6 exists
  to prevent, one step removed.
- **Surfaced for confirm-or-forget** is right, and most of it already ships. The
  affordances exist: `assistant forget` destroys it unconditionally (ADR-0073
  §5), and the user asserting the belief themselves supersedes it into the
  asserted band (ADR-0038 §1, ADR-0072 §4) — confirm and forget, both reachable
  today, over a state the surface now names. What does **not** exist is
  *proactively asking*, which is a pending-question surface: ADR-0078's for a
  memory decision, and the interruption policy's in the later arc. This ADR
  ratifies the state and the rendering, and defers the asking to those lanes
  rather than inventing a third queue (§11).

### 7. `Provenance` grows the validator ADR-0072 §3 filed for this lane

`Provenance` gains a source-conditional validator: **a source whose band is
`DERIVED` may not carry confidence 1.0.** `USER_ASSERTED` keeps its existing
implies-1.0 validator; `EXTERNAL` is untouched, because ADR-0038 §2a says it may
legitimately carry 1.0.

ADR-0072 §3 declined this and said exactly when to revisit — "there is no
producer yet that could violate the rule", and "ratifying an enforcement
mechanism ahead of the code it constrains is how a seam that does not survive
first use gets blessed". This lane is that producer, so the condition it named
is met.

It is worth having as a type rule rather than a policy rule because the policy is
not the only path a `Provenance` takes. Which is what settles **#432**, in two
halves, deliberately:

- **The confidence obligation is closed everywhere `Provenance` goes**, including
  `Goal`, which "carries `Provenance` and reaches no propose/dispose gate". A
  validator on the value needs no gate. Nothing breaks today: `orchestration`
  stamps every goal `USER_ASSERTED`/1.0, and the only records in the derived band
  are captured episodes, which already carry a documented sub-1.0 constant
  (ADR-0074 §4).
- **The evidence obligation is explicitly re-deferred**, with its owner named:
  the lane that adds the first producer of *inferred goals*. It cannot be a
  validator — an assertion legitimately cites nothing (ADR-0038 §1a) and
  `EXTERNAL` may too — so it needs the enforcement seam #432 describes, and no
  such producer exists. #432 stays open, narrowed to that half.

### 8. Trigger and cadence: an explicit operation, which the scheduler later calls

**Observation is an explicit operation on the `Engine` façade** — select a
bounded batch of episodes, observe it, ingest what comes back, return what
happened. The CLI is its first caller. It is **not** wired into the turn, and
there is no polling, no background task and no ambient machinery.

**The selection rule is named, because "a bounded batch" alone starves.** The
operation takes an optional conversation id: it observes **that conversation's
most recent `observation_batch_size` turns**, or, given none, the same window
over the **most recently active** conversation — the order ADR-0074 §2 already
made total for `recent`, over the tail read ADR-0074 §9 already made bounded.
Left unstated, an implementation selecting "the newest N episodes in the store"
would re-read the same N on every run, and the N+1th could never be requested at
all: it would expire unobserved with no way for the user to reach it. With a
conversation as the unit, everything is reachable — `assistant conversations`
lists them and the user can name any one — and the selection is deterministic
enough to test.

**A turn in the window whose episode does not resolve is skipped, and the batch
is not backfilled.** ADR-0074 §3 makes the index entry durable and the episode
best-effort, so a turn can sit in the log with no episode — from a capture
failure, an expiry, or a `forget` — and ADR-0074 §5 already rules what a reader
does with one: "an id that does not resolve is **skipped, not an error**". The
stage applies that rule unchanged, and stops there. Backfilling to fill the batch
would make the window's *span* depend on how many gaps it contains, so two runs
over one conversation would read different stretches of it and the bound would
stop meaning a fixed number of recent turns. A short batch is the honest
consequence of a gap, and §1's bound is a maximum rather than a quota.

**This does not make the producer conversation-shaped.** The Protocol still takes
episodes and the producer still never asks where they came from (§1). What is
conversation-scoped is *today's only selector*, in the stage that holds both
stores, which is exactly where #441's constraint leaves that choice: a sensor's
episodes belong to no conversation, and reaching them needs a second selection
rule in the stage, not a different `Observer`.

**Two gaps in coverage are accepted and named**: a conversation the user never
observes, and — in a conversation longer than the window — turns older than the
tail. Both expire unobserved under ADR-0074 §7's horizon. Closing them means
knowing what has already been observed, which is the cursor below, which is leg
5's.

Four reasons, in the order they bind:

1. **Nothing is waiting on it, and a turn is.** Running the observer inside
   `converse` would add a full model round trip to the latency of every turn for
   work the user is not waiting for. A one-shot CLI process has no "after the
   answer" to hide it in either: the process lives for the turn, so the cost lands
   on the user's wait however it is scheduled.
2. **The roadmap sequences leg 4 against volume** — the `ASK_USER` gap (#423),
   the contradiction surplus (#313/#314) and bounded-window retirement (#306)
   "land before the observer runs at volume". A per-turn trigger *is* volume, on
   the day it merges. An explicit one keeps the producer's output proportional to
   the user's deliberate invocations until those land.
3. **The first version of a producer that sends accumulated history to a model
   should not run without the user knowing.** The user chooses when the
   transcript is read, and the outcome tells them which route read it (§3). That
   is a stronger form of consent than a setting, and it costs nothing while the
   product has one user and one spoke (roadmap stance 3).
4. **Leg 5's scheduler owns cadence, and inherits this operation unchanged.** The
   hub's internal scheduler — already the named home for `purge_expired` and
   confirmation deadlines — becomes a second caller of the same façade operation.
   Cadence then becomes configuration rather than a contract change, which is
   what the mandate asks for.

**There is no durable cursor, and re-observation is safe by construction.** No
state records which episodes have been observed. A second run over the same
episodes re-proposes much the same beliefs, and the gate folds each into a
`REINFORCE` on the existing record rather than writing a duplicate (§4) — while
§5's confidence function **closes the repetition route to inflation**: the same
belief on the same support scores the same however many times it is derived, so a
fold that takes the maximum finds nothing higher. It does not make the model
deterministic, and it is not meant to: a second run that reads more support out of
the same episodes legitimately scores higher, which is reinforcement working
rather than a number drifting upward for being asked twice. What a re-run does cost
is a model call and a moved `provenance.last_updated`, which reorders the
inspection listing (ADR-0073 §2's sort key). That is accepted and named: it is
a true statement — the assistant did re-derive the belief today — and a cursor
is durable per-user state whose natural owner is the resident process, filed with
leg 5 (§11).

**An episode may expire unobserved**, under ADR-0074 §7's finite horizon, and
this ADR does not stretch the horizon to prevent it. The remedy is leg 5's
schedule; the setting is the user's; and a belief is not owed every episode that
ever existed.

### 9. The contract surface owed, and what the implementing lane owes

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/protocols.py`** gains **one** Protocol, `Observer`, owing: turn a
  bounded batch of `EpisodicMemory` records into an `ObservationOutcome`. It is
  named for its product role, as every Protocol here is (`Planner`,
  `MemoryPolicy`, `FeedbackProcessor`); nothing in this codebase uses the
  subscription pattern the word otherwise names.
- **`core/types.py`** gains **one** type and one validator (§7).
  `ObservationOutcome` is a frozen pydantic model (ADR-0068) carrying the
  proposals and the two discard counts §4 requires — `discarded_unusable` and
  `discarded_over_limit`, each a non-negative integer, together exhaustive over
  every entry the model emitted (§4). It is a `core` type
  because it crosses a subsystem boundary (`CLAUDE.md`), following
  `MemoryIngestResult`'s precedent that a seam returning more than one fact
  returns a named value rather than a tuple. The proposal, the episode and the
  record kinds already exist, which is why the cost is one type rather than a
  family.
- **`MemoryWriter.ingest`'s documented semantics** gain §5's refusal clause —
  a **third** obligation on that method, stacked on the two ADR-0079 §4 landed
  days ago (the full-set `SUPERSEDE`, and the over-ceiling refusal) and
  conflicting with neither: both of those are about the *conflict* set, this one
  about the *evidence* set. No signature change.
- **`core/errors.py`** gains **one** class,
  `UnresolvedEvidenceError(MemoryStoreError)`, carrying the unresolved ids so an
  evidence race is separable from a producer bug (§5). It is additive under
  `except MemoryStoreError`, so ADR-0079 §4's raise clause and every existing
  handler are untouched. Nothing else: a model failure is a `ModelError`, a store
  failure the base `MemoryStoreError` (ADR-0028 §5), and a malformed model
  response is a degradation rather than an exception (§4).

An illustrative signature, in ADR-0073 §1's form — the semantics above are the
contract, the spelling is the lane's:

```python
@runtime_checkable
class Observer(Protocol):
    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome: ...
```

**What the implementing lane owes** (stage 2; stage 1 is this ADR merging):

1. The Protocol, `ObservationOutcome`, `UnresolvedEvidenceError`, and the
   `Provenance` validator, plus the `MemoryWriter.ingest` docstring restated as
   §5 rules it, **and its conformance clause**: a `DERIVED` proposal citing a
   record the store does not hold is refused with an `UnresolvedEvidenceError`
   naming that id, nothing is written, and an `ASSERTED` or `EXTERNAL` proposal
   citing nothing is unaffected. It joins the clauses ADR-0079 §3 promoted, and
   `FakeMemoryWriter` matches it for that ADR's reason: a fake that stores what
   production refuses lets a consumer's test pass on state the real writer would
   never produce.
2. **The `DefaultMemoryPolicy` rule** (§5): a `DERIVED` proposal citing no
   evidence rules `REJECT`, an `EPISODIC` record is **not** refused for citing
   nothing, and `ASSERTED`/`EXTERNAL` proposals are untouched. Three tests, one
   per clause. Without this the ADR's "every proposal cites" holds only for the
   producer that happens to obey it.
3. **The shared conformance suite** — the clauses that bind **every** `Observer`,
   which are the ones expressible without a model: every returned proposal is in
   the `DERIVED` band; every proposal cites at least one id drawn from the batch
   it was given and none from outside it; an `INFERRED` proposal cites at least
   two **distinct** episode ids; no proposal is `EPISODIC`; confidence is
   strictly below 1.0, and two proposals **in one outcome** sharing an epistemic
   step and a distinct-support count carry the same confidence; **the returned proposal
   count never exceeds the configured maximum**; **a batch larger than that
   maximum is refused with a `ValueError` rather than truncated** (§1 — the case
   an implementation that silently slices passes every other clause on this
   list); **a batch carrying one episode id twice is refused** (§1); both discard
   counts are non-negative; an empty batch yields no proposals and zero discards;
   input observation (ADR-0065) and cancellation (ADR-0060). The canonical fake
   must be scriptable to report non-zero discards of both kinds, or no consumer
   can test its own degradation path — the gap ADR-0022 §Consequences filed
   against `FakeMemoryStore` as #105, not repeated here.

   **The counting rules of §4 are *not* suite clauses, and putting them there
   would be the error.** "Proposals plus both counts equal the entries the model
   emitted", the validate-then-cap order, an out-of-batch citation label, and an
   undecodable envelope are all statements about a *model response*, which a
   conforming `Observer` need not have — the canonical fake has none. They are
   the model-backed implementation's tests, in `tests/learning/`, against a
   `FakeModelProvider` scripted per case: a valid envelope, one with an entry
   citing an unknown label, one entry below the evidence floor, an entry of a
   forbidden kind, more usable entries than the bound, an unusable entry sitting
   past the bound (asserting it counts once and the bound still fills from behind
   it), and a response that does not decode at all (asserting exactly one
   unusable discard, and no second call to the model). **The whole confidence
   contract belongs here too**, because §5's properties are statements about the
   function and only a scripted response holds its inputs still: four responses
   — `OBSERVED` on one and on two supports, `INFERRED` on two and on three —
   assert that confidence is non-decreasing in distinct support and that
   `OBSERVED` outranks `INFERRED` at equal support; the same response twice
   yields byte-identical confidences; and **the same response under a clock moved
   between calls yields the same confidences**, which is the only way "no clock"
   is observable at all. It cannot be a suite clause phrased as "the same batch twice",
   because a conforming model-backed observer may legitimately return a different
   belief on a second call — an `OBSERVED` proposal citing one episode, then an
   `INFERRED` one citing two — and a suite asserting equal confidence across two
   calls would fail it for doing nothing wrong. What §5 fixes is the *function*,
   not the model.
4. **The canonical fake** in `ai_assistant.testing`, plus the concrete
   `Test…Contract` subclass that runs it through the suite — without which the
   triad check fails, naming what is missing (`CONTRIBUTING.md`).
5. **The model-backed implementation** in `learning/`, with ADR-0047 §1's
   injected seams (`ModelProvider`, a guarded `Clock` per ADR-0026 §7, an
   `id_factory`), the prompt of §3, the label→id mapping of §5, and ADR-0071's
   extraction. **It owes the envelope schema — the list key, an entry's fields,
   and how a citation label is spelled — and this ADR deliberately does not
   ratify one.** The envelope is internal to one implementation and is not on the
   `Observer` seam: a second observer would legitimately prompt differently, as a
   second `Planner` would, so pinning a schema here would constrain nothing a
   conforming implementation must satisfy while ratifying prompt spelling before
   anyone has run it against a real model (`CONTRIBUTING.md`, "Spike first if you
   need to"). ADR-0047 §4 is the precedent for *where* it belongs rather than an
   argument for putting it here: that ADR is an implementation ADR — "it
   implements the *existing* `Planner` Protocol… no `core/protocols.py` or
   `core/types.py` change" — and it fixed its own producer's envelope in the lane
   that built it. This one owes the same, and its tests above are what hold it. The extraction helper stays in the producing subsystem: two
   implementations of one scan is cheaper than promoting a non-contract helper
   into `core` on speculation, and the third model-backed producer is the trigger
   to promote it — the discipline ADR-0028 §7 and ADR-0045 §1 each applied.
6. **Three `Settings` fields.** `observer_model`, defaulting to unset with §3's
   meaning, validated at load like every other spec, and the composition-root
   wiring that builds its route **without fallback** and requires its own
   credential (ADR-0013 §6); `observation_batch_size` (positive, default 20, §1)
   and `observation_max_proposals` (positive, default 5, §2), each refused at
   load when non-positive, as every other bound there is.
7. **The `orchestration` stage and the façade operation** (§8), plus the
   citation-resolving belief views (§6). The façade is concrete and not a
   contract (ADR-0042 §1), so those names are shape, not spelling (ADR-0073 §7).
   The stage selects **at most** `observation_batch_size` episodes, so the
   producer's refusal (§1) guards a contract rather than a routine path.

   **Its result is an `orchestration` type beside `LearnOutcome`**, not a `core`
   one — it crosses no subsystem boundary, only `interfaces` (ADR-0022 §2's
   reasoning for `TurnResult`) — and it carries four things, deliberately kept
   apart. First, one entry per proposal, **each pairing the
   `MemoryUpdateProposal` the observer made with the `MemoryIngestResult` it
   received** — or with the unresolved-evidence drop that replaced it (§5). The
   pairing is the decision, not a convenience: `MemoryIngestResult` carries a
   ruling and a record id and nothing else, and for an `ASK_USER` that id is
   `None`, so an entry built from the result alone would render a deferral as a
   bare ruling with nothing to show — which is precisely the visibility §4
   promises while ADR-0078 is unbuilt. Then: the producer's two counts **relayed
   unchanged**; a
   **separate count of proposals dropped at the write for unresolved evidence**
   (§5); and the model route that read the episodes (§3), **which is absent when
   none did**. A window whose turns have all lost their episodes selects an empty
   batch, and the stage then **does not call the observer at all**: there is
   nothing to observe, no provider is reached, and naming a route would claim a
   read that never happened — the one thing §3's reporting exists to make
   truthful. The separation is the
   decision: `ObservationOutcome`'s invariant is over the entries the model
   emitted, so a post-observation drop has to be counted somewhere else or that
   invariant becomes a lie.
8. **The CLI**: the observe command, and the belief surfaces rendering
   tombstones, the adjusted confidence, and the all-unsupported state.

**Tests the conformance suite cannot reach**, and which are therefore the stage's
and the surface's, in `tests/orchestration/` and `tests/interfaces/`:

- **A belief whose cited episode is then deleted** — the listing shows the lost
  count and a lowered confidence, the detail view shows a tombstone, the stored
  record is **byte-identical to before** (the assertion that catches an
  implementation that "fixed" the record instead of the rendering), and `export`
  still carries the original id.
- **A belief whose cited episode has *expired*** rather than being deleted —
  same rendering, which is what stops an implementation from hooking deletion
  only and passing every deletion test (§6's decisive argument, pinned).
- **A belief whose citations are all gone** — its **effective floor**, the
  unsupported state named, still live, still deletable, and **not** retired.
  **Two stored values, either side of the floor**: one above it lands on the
  floor, one at or below it is unchanged, both bounds having collapsed onto the
  stored value. The pair is what pins `min(stored, floor)` rather than either
  half of it (§6).
- **A proposal citing an id the store does not hold** — refused by the writer,
  nothing stored (§5).
- **An episode that expires between selection and the write, in a batch of
  three** — the proposal citing it is dropped and counted, **the other two are
  still ingested**, and the operation does not fail (§5). The negative assertion
  matters as much: an implementation treating the refusal as a fault aborts a
  batch that was working, on nothing worse than a retention horizon doing its
  job.
- **A model response citing a label outside the batch** — the citation is
  dropped, and a proposal left with none is discarded rather than repaired (§5).
- **A batch observed twice, through an observer scripted to return the same
  proposal both times** — the second run reinforces rather than duplicating, and
  the belief's confidence does not rise (§8). Scripted, because the property
  under test is the *fold*, not the model: an observer free to answer differently
  would make the assertion about the provider.
- **An observer citing an id that was never in its batch** — the writer's
  refusal **propagates**; it is not swallowed as a race (§5). **And the mixed
  case**: one unresolved id from the batch and one from nowhere, asserting it
  propagates too, since a fault accompanied by an expiry is still a fault. The pair with the
  expiry case above is the whole of the discrimination, and an implementation
  that catches `UnresolvedEvidenceError` without checking the batch passes the
  expiry test and hides a producer bug forever.
- **A proposal that conflicts with a user assertion** — `ASK_USER`, nothing
  stored, and the deferral **reported** on the outcome (§4) **carrying the
  candidate's content, its citations and the policy's reason**, not merely a
  count. The assertion worth making is that it is not silently dropped, which is
  #423's whole complaint, and that what is reported is enough to act on.
- **A batch larger than the configured maximum** — refused, with nothing
  observed and no model call made (§1), and **an oversized *return* from the
  model** — truncated to the configured maximum with the discard counted (§2).
  The pair is what stops an implementation applying one bound and inheriting the
  other by accident.
- **Invalid limits** — a non-positive `observation_batch_size` or
  `observation_max_proposals` fails at load as a `ConfigurationError` (§1, §2),
  **and so does an `observation_batch_size` of `2**63`**, which would otherwise
  load cleanly and make every observation raise from the store read it is
  translated into. The posture is the one every other tuning value in `Settings`
  already takes.
- **A model failure and a malformed response**, asserting the two different
  behaviours §4 ratifies: propagate, versus degrade-and-count — the second
  asserting the counts reach the *user-facing* outcome, not merely the
  `ObservationOutcome`, since a stage that drops them re-creates the silence §4
  refuses.
- **A writer failure on the second of three proposals** — the operation raises,
  the first proposal is **still stored**, and nothing reports success (§4). The
  assertion pins the indeterminate partial write as ratified behaviour, so a
  later reader finds it in the suite instead of mistaking it for a bug, and a
  later implementer does not invent the partial-result transport this ADR
  declines.
- **A window containing a turn whose episode never landed** — the batch is the
  episodes that resolved, one short, and the observation runs normally (§8).
  **And a window where none resolved** — no provider is called, no proposals, no
  discards, and the outcome names **no** route (§9). An
  implementation that raised, or that reached further back to fill the batch,
  would change which transcript reaches the model between two runs over one
  conversation.
- **Two conversations in the store, observed in two runs** — the unscoped run
  selects the **most recently active** one, and a second run **naming the other**
  observes that one's episodes (§8). The pair pins the selector in both
  directions and, more to the point, pins that an episode outside the first batch
  is *reachable* — which an implementation re-reading the newest N of the store
  forever would fail. Unscoped twice selects the same conversation twice, by
  design: there is no cursor and no rotation, and a test asserting otherwise
  would be demanding the state §8 declines.
- **An observation run with `observer_model` unset and set** — the same route as
  conversation in the first case, the named one in the second, **and no fallback
  in either**, asserted by making the primary fail and checking that no second
  provider was called. An implementation that reused the router wholesale would
  pass every other test on this list.

### 10. Explicitly declined

- **An observer that holds a `MemoryStore`.** §1. It would make the scope of
  observation a property of an implementation rather than of a seam, and it would
  let a producer read the beliefs it is supposed to be proposing.
- **Passing existing beliefs into the observation prompt** to suppress repeats.
  §3. De-duplication is the gate's, deterministically and locally; paying for it
  with a second class of Tier 1 data in the prompt trades minimisation for
  something already solved.
- **Letting the model supply confidence, or evidence ids.** §5. The first makes
  two proposals' numbers incomparable and lets re-observation inflate a belief;
  the second lets a model cite an episode it never read.
- **Extending `FeedbackProcessor` to carry observation.** Its input is a
  `FeedbackEvent` — explicit, user-stated feedback with a `FeedbackKind` of
  `CORRECTION` or `PREFERENCE` (ADR-0009 §1). Episodes are neither, and
  synthesising a `FeedbackEvent` per episode would put "the user said this"
  wrapping around something the user did not say.
- **Eager rewriting of citations at deletion time.** §6. It misses expiry
  entirely, needs a reverse index and an unbounded write fan-out inside a
  deletion protocol, and edits a frozen belief because another record went away.
- **Cascading a delete from an episode to the beliefs citing it.** §6, and the
  owner's #431 direction rules it out directly.
- **Retiring a belief whose evidence is all gone.** §6. It is the cascade with a
  softer name.
- **Lowering the *stored* confidence when support is lost.** §6. It is a write
  fan-out on a delete, it edits a record no producer revised, and the adjustment
  is wanted only where a number is shown.
- **A per-turn or background-task trigger.** §8. A latency tax on every turn for
  work nothing waits on, and volume before leg 4.
- **A durable "already observed" cursor.** §8. Per-user durable state whose owner
  is the resident process; re-observation is safe without it.
- **A pending-proposal queue for `ASK_USER`.** §4. That is ADR-0078's decision,
  and a second queue invented here would be the thing it has to supersede.
- **A writer floor duplicating the policy's cites-something rule.** §5. It would
  make the policy's `REJECT` unreachable for the case, turning a decision the
  user can read into an exception, and would put one rule in two places to
  drift — where ADR-0045 §5 clause 1's floor refuses to *apply* a ruling rather
  than pre-empting one.
- **Truncating an oversized batch, or silently de-duplicating one.** §1. Both
  hide a caller's selection bug instead of surfacing it, and the second is the
  route by which one episode becomes two supports for an `INFERRED` belief.
- **A reason enum on a discarded entry.** §4. Two exhaustive counts answer "was
  anything thrown away"; a taxonomy of reasons is surface with no consumer.
- **A partial-result error or outcome for a batch whose ingest fails part-way.**
  §4. It is a new failure transport built for one caller, over a gap ADR-0022 §4
  already ruled on and #104 already owns; the recovery path is the inspection
  surface leg 1 shipped.
- **A sensitive-subject filter inside the observer.** §2.
- **A `get_many` on `MemoryStore`.** §6. ADR-0074 §5 declined it; this ADR gives
  it a second consumer and leaves the decision where the hub will hold it.

### 11. What this ADR does not decide

- **How an `ASK_USER` ruling is resolved.** ADR-0078 (#423), in flight. This ADR
  states only what a deferred proposal owes it (§4).
- **What happens to the conflicts beyond `conflict_limit`** when a correction
  contradicts more inferences than the cap. Already decided: ADR-0079 (#313/#314)
  is merged and Accepted — a correction resolves every conflict it is shown or
  refuses to land — which is the ruling this producer makes reachable in
  practice, and §5's third clause on `MemoryWriter.ingest` is stacked on its two
  without touching either.
- **Retiring a producer-set bounded validity window** (#306). Leg 4. The observer
  sets no bounded window today, and it is deliberately not the lane that decides
  what retiring one means.
- **The observer's prompt and its output envelope schema** (§9). The
  implementing lane's, with a real model in hand, as ADR-0047 §4 was the
  planner's. What *is* decided here is what may be in the payload (§3), what the
  producer may take from the response (§5), and how what it refuses is counted
  (§4) — the parts a reader downstream depends on.
- **Cadence and aggregate volume.** Leg 5: how often observation runs, the
  durable cursor that stops it re-reading what it has seen (§8), and the process
  that runs it without being asked. **The per-call bounds are *not* deferred** —
  §1 and §2 name them and their defaults, because a bound left to leg 5 is a
  bound this producer ships without. What leg 5 decides is how many such calls
  happen and when. Not foreclosed: the façade operation is what the scheduler
  calls, unchanged.
- **An on-device generative route** (§3). It needs a local runtime, a
  provisioning decision of the shape ADR-0024 made for the embedder, and endpoint
  configuration `Settings` does not have. Filed; the named setting is what makes
  it a configuration change when it arrives.
- **Who triggered an episode's retention** — #441's user-versus-assistant
  distinction, deferred by ADR-0074 §11 and still deferred: the observer does not
  trigger episode retention, and the field would hold one constant until a
  non-conversational capture source exists. Its owner is that lane (leg 6's
  sensors, or #441's buffered capture). What leg 3 *does* take from #441 is the
  source-agnostic batch (§1) and the weight of local distillation on the route
  decision (§3).
- **Multi-source episodes** — an episode ingested from a sensor rather than a
  conversation. Leg 6. §1's batch is already source-agnostic, so this is an
  additional producer of input, not a change here.
- **Consolidation, decay and salience** — what happens to a derived belief that
  is never reinforced and never corrected. Leg 7 (ADR-0072 §10, unchanged).
- **Cross-conversation episodic recall and its ranking** (ADR-0074 §6, §11).
  Untouched: the observer reads the batch it is handed rather than searching.
- **The evidence obligation on `Goal`** (§7, #432), and any enforcement seam on
  the goal write path. The lane that adds an inferred-goal producer.
- **Whether the shipped policy should refuse to fold an `EPISODIC` record**
  anyway (ADR-0075 §5). Still the policy owner's; §5's rule constrains what leg 3
  writes, not what that lane may add.
- **Prompt-assembly's band precedence and phrasing** (ADR-0072 §5, §6). This ADR
  adds one obligation to that lane — a stated confidence is the adjusted one (§6)
  — and decides nothing else about it.

## Consequences

- **The accumulation loop closes end to end.** A belief the user never dictated
  is formed from observation, disposed by the ratified gate, rendered with its
  band, its confidence and its evidence, and correctable by the user — which is
  the roadmap's exit test for leg 3 and the first time VISION §Principle 1's
  "built chiefly by observation" is true of anything in the tree.
- **The contract cost is one Protocol, one type, one validator and one error
  class** — everything
  else the lane owes is a rule inside a concrete component, a `Settings` field or
  a test — because ADR-0005 typed the proposal, ADR-0028 contracted the write path,
  ADR-0072 fixed what a derived belief means, ADR-0073 built the surface and
  ADR-0074 built the substrate. The heaviest design ADR of the arc adds the least
  contract surface of the four, which is what contract-first was for.
- **The gate holds where it matters most.** ADR-0075 exempted capture and named
  the observer as the paradigm case the gate exists for; this ADR keeps it
  inside, and the producer holds neither writer nor policy, so it cannot rule on
  its own output even by mistake.
- **Which model reads the transcript is now a named, separable setting** rather
  than an accident of `default_model`, and observation never widens the set of
  providers that see user data — by default it names none, and it never falls
  back. The honest cost: the default route is a hosted provider, because no
  on-device generative route is realizable in the installed artifact, and this ADR
  says so rather than implying a local default it cannot ship.
- **`ASK_USER` becomes visible before it becomes resolvable.** Until ADR-0078
  lands, a deferral is reported — with the candidate, its citations and the
  policy's reason — instead of vanishing. That is a smaller thing than resolving
  it, and the ADR says so plainly: nothing persists the deferral, so it does not
  survive the process, and #423 stays open until ADR-0078 closes it.
- **A belief now outlives its evidence honestly.** The tombstone reveals *that*
  an evidence item existed and was destroyed, never what it was; the presented
  confidence falls; the stored record is untouched; retrieval is unmoved. The
  accepted residue is that a deleted episode leaves a visible trace in the
  provenance of a belief the user kept — the price of a provenance display that
  does not lie, ratified rather than discovered.
- **Every presented belief costs a read per citation** (§6), bounded by the page.
  It is the first real cost of ADR-0074 §5's declined batch read, and it is where
  that decision gets revisited.
- **A failed ingest leaves an indeterminate partial write**, and this ADR
  states it rather than papering over it (§4). It is ADR-0022 §4's ruling
  inherited unchanged, it costs the operation a clean result on the one path
  where memory integrity cannot be claimed, and #104 — a batch or transaction on
  `MemoryStore` — is what closes it.
- **Observation is deliberately slower than it could be.** An explicit trigger
  means episodes can expire unobserved and the user must ask for accumulation
  they were promised passively. That is the price of not shipping volume ahead of
  leg 4 and not shipping ambient machinery ahead of leg 5, and it is paid back by
  the scheduler calling the same operation.
- **The derived band stops being hypothetical for every lane downstream.**
  Prompt assembly, consolidation and the contradiction work now have records to
  reason about — and the two gates ADR-0073 §4 set on this producer are
  discharged rather than inherited.
- **Revisit if** a local generative route becomes realizable (§3's default moves
  on-device); if leg 4 lands and the trigger should become the scheduler's (§8);
  if the presented-versus-stored confidence split confuses users more than it
  informs them; if the `INFERRED` floor of two episodes proves too strict for
  beliefs a single rich exchange plainly supports; or if re-observation without a
  cursor costs more in model calls than a cursor would cost in state.

## Alternatives considered

- **The observer holds a `MemoryStore` and selects its own episodes.** Rejected
  in §1. It is the smaller wiring — one collaborator instead of a stage — and it
  makes the scope of observation unreviewable, because "what does it read" then
  has no answer short of reading the implementation. It would also let the
  producer read the beliefs it proposes against, which is the input §3 declines
  for minimisation reasons and §4 declines for de-duplication reasons.
- **Observation on every turn, inside `converse`.** Rejected in §8. It is what
  "passive accumulation" sounds like it should mean, and it taxes every turn with
  a model round trip nothing waits on, produces volume on the day it merges, and
  has nowhere to hide the latency in a one-shot process.
- **A background task per turn, drained at engine close.** Rejected in §8. It
  moves the latency after the printed answer without removing it, and it is
  in-flight state the resident process is supposed to own (leg 5).
- **Off by default, with a required `observer_model`.** Rejected in §3. It makes
  the commonest correct setup — one configured provider used for everything — an
  error, and it buys nothing over the explicit trigger, which already means no
  episode is read without the user asking.
- **Routing the observer over `fallback_models` like any other call.** Rejected
  in §3. Fallback buys reliability by widening the set of providers that see a
  prompt; for a deferrable job over accumulated history the reliability is worth
  nothing and the widening is the one cost that matters.
- **Cascading a delete: destroying beliefs whose evidence the user destroyed.**
  Rejected in §6, and by the owner's direction on #431. It reads as respectful and
  is not: it lets deleting an old conversation silently unlearn a belief the user
  never asked to lose, and it is indistinguishable — from the user's side — from
  the assistant forgetting things at random.
- **Retiring an unsupported belief instead of holding it at its effective
  floor.**
  Rejected in §6. Retirement is non-destructive (ADR-0045 §4) and would still
  remove the belief from every live read, which is the cascade's effect through
  a different door.
- **Eager citation rewriting at deletion time.** Rejected in §6. It is the option
  that "keeps the store honest at rest", and it misses expiry — the dominant case
  — entirely, because retention is enforced at read time with no per-record
  event to hook.
- **Rendering a lost citation as its bare id, or omitting it.** Rejected by
  ADR-0073 §4's floor before this ADR reaches it, and worth naming: an id is a
  warrant the surface cannot show, and an omission makes a belief look
  better-supported than it is.
- **A model-supplied confidence, clamped below 1.0.** Rejected in §5. It is the
  cheapest implementation and it makes every downstream comparison meaningless,
  and — because it varies run to run — it lets repeated observation inflate a
  belief through `REINFORCE`'s maximum.
- **Enforcing the sub-1.0 derived rule at the policy instead of on
  `Provenance`.** Rejected in §7: the policy is not the only path a `Provenance`
  takes, and the `Goal` gap (#432) is precisely the path that has no policy.
- **Deferring the whole #431 question again, to the lane that first sees a
  dangling citation.** Rejected: this *is* that lane. ADR-0073 §4 made resolving
  citations a precondition of this producer shipping, and a producer that
  populates the derived band while the surface cannot say why is exactly what
  that gate forbids.
