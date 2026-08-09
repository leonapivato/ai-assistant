# 122. A correction's record type is resolved from its target, not declared by its caller

- Status: Accepted
- Date: 2026-08-09
- **Decides `core` surface and implements none of it.** One field on
  `FeedbackEvent` in `core/types.py` becomes **optional** — `memory_kind` gains
  `None` and a default (§1). **No new Protocol and no new member**:
  `FeedbackProcessor` is untouched, `MemoryStore` is untouched, `MemoryWriter` is
  untouched, and no `MemoryKind` member is added. Golden rule 5 and ADR-0015 §5
  put a contract ADR in its own PR, ratified before anything implements against
  it; the implementation is a separate later lane (§10). **Its required review set
  is therefore adversarial *and* architecture**, even though the PR carrying it is
  prose only — `CONTRIBUTING.md` → "Stop when the required reviews are green"
  makes a change contract-surface "when it is the ADR deciding that surface", and
  `scripts/ship.sh` fires its own architecture requirement on a diff touching
  `core/protocols.py` or `core/types.py`, which this diff does not. Both lenses are
  therefore run deliberately, as ADR-0117's own header records for the same reason.
  **Both ran against this decision while it was `Proposed`** — adversarial through
  the rounds that produced §3's intent gate, its `kinds` scoping and its fixed
  resolution set, and architecture through the round that reclassified the ADR-0009
  record as a partial supersession, each returning to APPROVE on the proposed text.
  This `Accepted` line is the ratifying edit ADR-0070 §1 permits — the one that
  "finalises the current decision rather than changing a past one" — and it records
  that outcome rather than pre-empting it. Every merged ADR in this corpus carries
  it, and the branch history carries the `Proposed` rounds it stands on.
- **Partially supersedes [ADR-0009](0009-learning-model.md) §1**, in the scope §1
  and §3 below name and in no other: §1's first bullet requires the *caller* to
  carry the target kind, and that requirement is replaced — `memory_kind` becomes
  optional, and an absent value is resolved by `orchestration` before the
  processor is called. A reader holding only ADR-0009 would act differently, which
  is ADR-0070 §1's test and is what makes this a supersession rather than an
  amendment however small the edit (§9). The bullet's *reason* — "a correction is
  not always a preference… carrying the target kind lets the processor build the
  correct record type" — is not replaced; it is the ground the replacement stands
  on, and is honoured here for the first time. §1's second bullet and §§2–6 stand
  unchanged, including §4's mapping, §3's "learning never imports `memory`", and
  §6's `PROCEDURAL`/`EPISODIC` deferral, which §3 below binds itself to. The record
  is on ADR-0009's `Status` line in ADR-0070 §4's leading-token, **one-physical-
  line** form and in an appended dated note, plus an inline note at §1, all landing
  in this change — the atomic pair ADR-0082 §7 names, whose condition is that the
  superseding ADR *exists* and not that it is ratified (§9).
- **Refuses to widen `memory`'s conflict probe** (§8), and corrects one reason
  that has been offered for that refusal: the shipped ingest lock does **not**
  depend on conflict detection staying kind-scoped. The dependency belongs to the
  per-kind lock that `MemoryIngestor.__init__` weighs and *rejects*. The reasons
  the widening is refused are the four others §8 gives.
- Closes the decision half of issue #864. Refs #862, #865.

## Context

Leg 8's QA run (#862) drove the correction path against a live hub and it did not
compose. With the espresso preference in the store, `assistant learn --kind
correction "Actually I prefer cappuccino in the morning, not espresso — I was
wrong before"` **stored a brand-new `semantic` record and left the contradicted
preference standing**, reporting "Learned. Stored a new memory". The retrieval
trace of the correction's own conflict probe (ADR-0119 §8's `RETRIEVAL` emitter,
which sits inside the store) shows the mechanism exactly: candidates were fetched
and *all* of them were excluded on the `kind` predicate, so the probe returned
nothing and the policy had nothing to rule against.

Two individually defensible decisions meet there and do not compose.

**The caller declares the record type.** `FeedbackEvent.memory_kind` is required,
so something must fill it before the event exists. The only thing upstream is the
CLI, which fills it from a fixed table — `_DEFAULT_MEMORY_KIND` in
`interfaces/cli.py` maps `FeedbackKind.CORRECTION` to `MemoryKind.SEMANTIC` and
`FeedbackKind.PREFERENCE` to `MemoryKind.PREFERENCE` — under a comment citing
`FeedbackEvent`'s own guidance, "a fact becomes a `SemanticMemory`, not a
preference".

**The conflict probe searches within one kind.** `MemoryIngestor._detect_conflicts`
calls `search` with `kinds=[MemoryKind(record.kind)]`, and everything downstream
is built on that scoping: `_apply` refuses a fold target that is not among the
conflicts, and `_fold` records that a `REINFORCE` "cannot reach" ADR-0108 §4's
cross-kind refusal "because its target came from a kind-filtered search".

So a correction arrives already typed by a table that cannot know what it is
correcting, and then looks for its target only in the drawer that table named.
The one command named for corrections is the one path that cannot correct across
kinds.

**The guidance the table cites does not say what the table does.** ADR-0009 §1's
sentence is an *illustration* that a correction's record type varies with what it
corrects — "A correction is not always a preference — 'my office is in Boston, not
New York' is a `SemanticMemory` correction" — offered as the reason the field
exists. The table reads it as a rule that a correction is *always* semantic. That
over-reading is where the defect is: it converts "the type depends on the target"
into a constant, at the one layer that has no access to the target.

**The machinery downstream of the kind is sound.** The same content re-taught as
`--kind preference` found the target immediately, deferred under ADR-0050 §2 — the
arm ADR-0121 has since narrowed, and which still governs here because espresso and
cappuccino *disagree* — and
superseded on `assistant answer --accept`. Nothing in the policy, the fold, the
deferral queue or the writer needs to change. What is missing is a step that names
the drawer before the record is minted.

**The damage is not only that the correction misses.** The record that lands is
*mistyped*, and two things follow that outlive the missed supersession. The
correction's own utterance — "Actually I prefer cappuccino…" — is stored as a
standing semantic fact and kept surfacing in later reads (#864). And
`RuleBasedFeedbackProcessor._to_record`'s `SEMANTIC` branch has nowhere to put
`event.subject`, so it discards it: a correction given with `--about` silently
loses its scope, which the `PREFERENCE` branch would have carried to
`PreferenceMemory.context`. A fix that made the correction *reach* its target
without fixing its *type* would leave both of these in place.

**Which side moves is not obvious, and #864 left it open** ("the fix lane's
call"). It is a decision, not an implementation detail: one side is a public
`core` type and an adapter's default, the other is the safety boundary that
`memory`'s writer, ADR-0050's retirement set and ADR-0108 §4's backstop are all
stated over. This ADR takes it, and issue #864's implementation half waits on it.

## Decision

We will stop asking the caller to name the drawer a correction belongs in, and
resolve it from the belief the correction touches — in `orchestration`, before the
proposal is minted, leaving `memory`'s kind-scoped probe exactly as it is.

### 1. `memory_kind` becomes optional, and absent means "resolve it"

> **Normative.** `FeedbackEvent.memory_kind` is `MemoryKind | None`, defaulting to
> `None`. `None` means the feedback does not name a record type and one is to be
> resolved by §3 — from the belief the feedback touches where the intent leaves
> that open, and from the intent itself where it does not. It never means a record
> type is unknowable, and it is never stored. A value present is the caller's **pin** and
> is honoured unchanged (§6).

The field was required, so every producer had to answer a question some producers
cannot answer. That is the whole defect: the CLI does not know, cannot know, and
was made to answer anyway — and the answer it invented was indistinguishable, at
every layer downstream, from one a user had chosen deliberately.

This is the shape this corpus already takes for a quantity a producer may not
hold. `Attestation`'s coverage is optional because "require it rather than making
it optional… breaks every existing construction site" (ADR-0110, rejected
alternative); `last_confirmed_at` is optional for the same reason (ADR-0109 §2);
`Evidence.content` carries `None` as a tombstone rather than a plausible string;
`_confirming_instant` returns currency as unknown where neither side has a usable
instant rather than substituting the moment of the fold. Representing the unknown
is the standing answer here, and a default that manufactures a value is the
standing mistake.

**It is `None` and not a `MemoryKind` member.** A sentinel member — `UNRESOLVED`,
or similar — would enter every exhaustive `match` over `MemoryKind` in the tree,
including `_to_record`'s and every kind filter on `search` and `list_beliefs`, to
express a state that is never stored on a record. `MemoryKind` is the record's
*type*; a request that has not yet chosen one is not a type.

**The wire needs no accommodation, and "absent" is spelled `null` on it.** The
codec's `project` renders a model through `model_dump()`, which emits every field
including a defaulted one, and it gives `None` a form of its own — so an unpinned
correction crosses the wire as `"memory_kind": null` rather than as a missing
member, and no projection change is owed. "Absent" throughout this ADR means the
field holds `None`, whatever layer is looking at it; there is no second, weaker
sense in which a producer omits it. ADR-0084 §3's connect handshake is an
exact-match version check, so a hub and a client never differ in what
`FeedbackEvent` may carry, and a field that gains a default is source-compatible
with every existing construction site in the tree.

### 2. The adapter stops inventing one

> **Normative.** `interfaces/cli.py` supplies `memory_kind` only where the value
> follows from what the user said: from `--memory-kind` when it is given, and from
> `--kind preference` when it is not. For `--kind correction` with no
> `--memory-kind`, it leaves the field `None`. `_DEFAULT_MEMORY_KIND`'s
> `CORRECTION` entry is removed; no adapter substitutes a record type for a
> correction.

The two intents are not symmetric, and the asymmetry is the reason this is stated
as a rule rather than left to taste.

A **stated preference** establishes a `PreferenceMemory` by its own intent. The
user is not pointing at a stored belief; they are stating one, and its record type
follows from the statement. No lookup is available and none is needed, so the
default stays and is not a guess.

A **correction** points at a belief that already exists. Its record type is a
property of *that* belief, so naming it without looking is not a default, it is a
prediction — and ADR-0009 §1's own sentence says the prediction has no fixed
answer. Leaving the field `None` is the adapter reporting what it knows, which is
what keeps golden rule 3 intact: the resolution is business logic, and this rules
that no part of it happens in `interfaces/`.

**This clause binds the adapter and settles nothing for any other producer.**
`FeedbackEvent` is a `core` type, so a programmatic caller — a future interface, a
test, a later processor's own re-proposal — can construct one with an absent
`memory_kind` and any `kind`, and it is not reached by a rule stated over
`interfaces/cli.py`. §3's first clause therefore states the same asymmetry at the
pipeline, where every producer's event passes, and this section is what that
clause's `PREFERENCE` arm exists to keep consistent with.

### 3. The resolution is `orchestration`'s, and it names a drawer, never a conflict

> **Normative.** `orchestration`'s learning loop resolves an absent `memory_kind`
> before it calls the `FeedbackProcessor`, and the intent decides how. On
> `FeedbackKind.PREFERENCE` the resolution is `MemoryKind.PREFERENCE` and **no
> store read is issued**. On `FeedbackKind.CORRECTION` it is **one** ranked
> `MemoryStore.search` over the feedback's own `content`, **scoped to the
> resolution set — `{MemoryKind.PREFERENCE, MemoryKind.SEMANTIC}`, fixed by this
> clause** — and unscoped by band: the resolved kind is the best-ranked
> returned record's, and where the search returns nothing, §5 governs. Its `limit`
> is the loop's own checked tuning knob, distinct from the turn's
> `retrieval_limit`. The search resolution applies **no similarity threshold and
> makes no ruling**: it selects a kind and nothing else, and whether a
> contradiction exists remains `MemoryIngestor`'s and the `MemoryPolicy`'s question
> alone.

**The `PREFERENCE` arm is not a shortcut, and omitting it would be a defect.** §2
gives the reason a stated preference needs no lookup — its record type follows
from the intent, not from what the store happens to hold — but §2 binds one
adapter, and this clause is where every producer's event actually arrives. Without
the arm, a programmatic `FeedbackEvent(kind=PREFERENCE, content="I prefer tea")`
with no `memory_kind` would be resolved by search: a best-ranked semantic
neighbour would file the user's stated preference as a fact, and on an empty store
§5's fallback would do the same. That is the wrong-drawer defect this ADR exists
to end, reproduced on the arm it was never about. The arm also keeps the two
statements from drifting: §2 is now a consequence of this clause as it applies to
the CLI, rather than a second, independent rule.

**Why `orchestration` and not `learning`.** ADR-0009 §3 is explicit that `learning`
produces proposals and the pipeline closes the loop — "`learning` never imports
`memory`'s concrete ingestor… keeping `learning` dependent only on `core`". A
processor that resolved its own target would need a store seam injected into every
implementation of `FeedbackProcessor`, including the model-backed one §6 of that
ADR defers, to answer a question that is the same for all of them. `LearningLoop`
already holds `memory: MemoryStore` and already reads it as a pipeline stage — the
map in `CLAUDE.md` names memory retrieval as `orchestration`'s step — so the
resolution costs no new seam, no new Protocol, no injection change and no
composition-root obligation.

**Why it names a drawer and not a conflict.** This is the clause that keeps the
step from becoming a second conflict detector. `MemoryIngestor` owns
`conflict_threshold`, the over-ceiling refusal (ADR-0079 §1), the retirement set
(ADR-0050 §1) and the unsafe-fold refusals; a threshold in `orchestration` would
duplicate the first of those in a subsystem that may not import the constant
holding it, and would drift from it silently. So the resolution reads only which
drawer the best-ranked neighbour lives in, and hands the proposal to the ordinary
path. If that neighbour turns out to score below the ingestor's threshold, the
ingest finds no conflict and stores the proposal as new — which is exactly today's
outcome for that case, in the drawer the belief lives in rather than a different
one.

**The one case where this can be worse than today, stated rather than claimed
away.** An earlier draft asserted the resolution could never make an outcome
worse. That is false, and the counter-example is not exotic: a correction of a
semantic belief whose true target ranks *below* an unrelated preference resolves
to `PREFERENCE`, and the semantic target — which today's fixed `SEMANTIC` default
would have probed and superseded — is never looked at. Ranking is relevance, and
relevance is not aboutness; the corpus says so itself when ADR-0045 §5 rules
topical similarity too weak a signal to retire a record. Three things bound it and
none of them dissolves it. It requires a cross-kind neighbour that outranks the
true target, where today's failure requires only that the target not be semantic —
so the exposure is much smaller than the defect being removed, though it is not
zero. The misresolution is *discoverable* — by belief inspection, where today's
mis-filing is not discoverable at all (§4) — and §6's pin is the direct remedy,
which is part of why §6 keeps it authoritative rather than folding it into the
resolution.
This residue is the price of choosing the drawer by the only signal available, and
it is filed with the others in §11 rather than hidden behind a claim of strict
improvement.

**A resolution that cannot be performed propagates, and never degrades into a
drawer.**

> **Normative.** Where §3's search raises, the error propagates from
> `learn` unchanged. The resolution has no degraded mode: a failed lookup never
> falls through to §5, never falls back to the pin's absent value, and nothing is
> proposed, processed or written on the strength of it.

This is the one place where `learn` must not copy `respond`. A turn whose
retrieval fails is answered with fewer memories and says so through
`memory_degraded`, because an answer with less context is still an answer. A
correction whose *type* could not be resolved is not a correction with less
context — it is a correction about to be filed in a drawer chosen by the failure
rather than by the belief, which is precisely the silent mis-filing this ADR
exists to end. §5's fallback answers "the store looked and holds nothing", a fact;
it may not be made to answer "the store could not look", which is not one.

**What propagation costs, and it is not nothing.** For a *persistent* failure it
costs nothing that was going to succeed — the ingest's own conflict probe reads
the same store through the same seam moments later, so a store that cannot answer
the resolution was not going to complete the write either. A **transient** failure
is different, and an earlier draft's blanket claim overlooked it: a read that
times out and would have succeeded on the retry now aborts a `learn` whose single
pre-existing read might have gone through. That is a real availability cost of
adding a read, accepted here rather than argued away, because the alternative is
not "the correction lands" but "the correction lands somewhere the failure chose",
and because a failed `learn` is a legible fault the user retries while a
mis-drawered belief is a silent one they do not know to. Retry policy is the
store seam's question and no part of this decision.

Propagation is also the discipline `LearningLoop.learn` already documents for this
path — "a store failure propagates with the earlier proposals **already
applied**", where "[r]eporting success for a partially applied set would be a
claim about memory integrity this loop cannot make".

**A stale resolution is benign, and is not raced against.** The resolution read
happens outside `MemoryIngestor`'s lock, so a record can retire between the
resolution and the probe. The consequence is that the correction lands in a drawer
whose target has just gone, finds no conflict, and is stored as new — again the
pre-existing outcome, in a better drawer. Nothing is written on the basis of the
resolution, so there is nothing for a race to corrupt.

**Why the set is bounded at all.** ADR-0009 §6 defers `PROCEDURAL` and `EPISODIC`
correction targets, and `_to_record` returns no proposal for them. A resolution
free to select `EPISODIC` — the store is full of episodes, and an episode
recording the user ordering espresso is a plausible best match for a correction
about espresso — would produce an event the processor answers with an empty
sequence, and the user's correction would vanish *entirely*, which is strictly
worse than the defect this ADR fixes.

**Why the set is a literal here and not a question asked of the processor.** The
tempting phrasing is "the kinds the processor can mint", and it is not
implementable: `FeedbackProcessor` exposes `process(event)` and nothing else, so
`orchestration` has no way to ask, and inventing one would be a Protocol change
under golden rule 5 — a capability declaration with one implementation and one
caller, ratified to spare an ADR from naming two enum members. So the set is
named here, matching what ADR-0009 §4 fixes `RuleBasedFeedbackProcessor` to mint,
and **it widens by a ratified decision rather than by inference**: when ADR-0009
§6's deferral is taken up, the lane taking it partially supersedes this clause in
the scope of the set — a change to what was decided, on ADR-0070 §1's test — in
the same change that makes the kinds mintable.

> **Normative.** The `FeedbackProcessor` wired behind the loop mints every kind in
> §3's resolution set. This is a composition-root obligation, in ADR-0028 §4's
> sense — nothing in the type system can state it — and a root that wires a
> processor minting fewer has mis-wired the loop.

That obligation is the honest form of the constraint, and it has precedent
directly beside it: `LearningLoop`'s own constructor already carries "**The writer
behind ``writes`` must persist to ``memory``.** Nothing in the type system can say
so — a ``MemoryWriter`` exposes no store, deliberately — so it is a
composition-root obligation". §7's second clause is what stops a violation of it
from being silent.

**Passing the restriction to `search` rather than applying it afterwards is
load-bearing**, and the reason is where the predicate binds. ADR-0113 §2 binds the
*band* before the ranking cut and is explicit that `kind` keeps "the post-cut
placement ADR-0045 §6 and ADR-0007 ratified for them" — so a page fetched unscoped
is a page of whatever ranked highest, and a store holding many topically similar
episodes returns them and nothing mintable, whereupon §5 files a correction whose
target was sitting just below the cut. Passing `kinds` does not move the predicate
before the cut, but it puts the resolution on exactly the footing
`MemoryIngestor._detect_conflicts` already stands on: the store's own over-fetch
pads for the post-cut kind filter, which is how the conflict probe finds its target
today.

**What that leaves open is retrieval's known non-exhaustiveness, and this ADR does
not claim to close it.** `_detect_conflicts` states the same limit for the same
reason — it "makes no claim that retrieval is exhaustive", and "what it never
surfaced is invisible here", a `MemoryStore` obligation filed as issue #457. A
correction whose target ranks below the resolution's reach resolves by §5 and lands
as it does today, so the residue is bounded by the behaviour this ADR replaces
rather than added to it — but it is a residue, not a guarantee, and a §10 test
pins it as one. Closing it means closing #457, for the conflict probe and this read
together; a second retrieval operation invented here would be a `MemoryStore`
contract decision taken inside a lane that is not deciding `MemoryStore`.

**The read is traced for free and discloses nothing.** ADR-0119 §8's `RETRIEVAL`
emitter is inside the store, so the resolution's search appears in the trace stream
exactly as the conflict probe did — which is how #864 was diagnosed at all, and it
means a misresolution is diagnosable by the same method. And the step reads one
`MemoryKind` off each candidate and no content, inside the hub, so it moves nothing
across a boundary and creates no disclosure obligation under ADR-0073 §4.

### 4. Two drawers match: the best-ranked one wins, and no second proposal is minted

> **Normative.** Where the resolution's candidates span more than one mintable
> kind, the best-ranked candidate's kind is the resolution. No tiebreak beyond
> `search`'s own order is defined, and the feedback yields **one** proposal: a
> single correction is never minted into two kinds.

Three reasons, and each rules out a different tempting alternative.

**Relevance is the only ordering this corpus admits.** ADR-0113 §4 makes the band
an eligibility axis and "never an ordering one", and ADR-0112 §1 affirms that
neither currency nor evidence strength is a term in any ordering. Inventing a
kind-preference rank here — semantic before preference, or the reverse — would be
exactly the kind of second ordering term those decisions refuse, on a signal
weaker than the one they were refusing.

**One utterance is one belief.** The user made a single correction. `search`
returning neighbours in two drawers is a fact about the store's contents, not
evidence that the user holds two wrong beliefs; treating it as the latter reads a
similarity signal as an intent signal, which is the error ADR-0045 §5 named when it
ruled topical similarity too weak to retire a user's record.

**Minting into both would assert what the user did not say, and double the
pollution #864 reports.** `FeedbackProcessor.process` returns a `Sequence`, so two
proposals are expressible, and `LearningLoop.learn` would apply them independently.
But a correction stated as a preference would then also be written as a standing
semantic fact, and the store would hold two records of one utterance — one of them
in a drawer the user never referred to. #864's second complaint is precisely a
stray record polluting retrieval; a design that guarantees one is not a fix.

**A wrong resolution is discoverable and recoverable**, which is what makes
best-ranked acceptable rather than merely convenient. Discoverable is the accurate
word and "visible in the outcome" is not: `IngestSummary` carries a decision and a
record id and no `MemoryKind`, so a correct resolution and a wrong one can both
report "Replaced a prior memory" — against different records. What separates them
is `assistant beliefs`, the belief-inspection surface (ADR-0073 §7), which shows
each record and its kind; the outcome narrows the question rather than answering
it. Recovery is then §6's pin on a re-teach, which is the same recovery the QA run
found by hand. That inspection is a step the user must take is the honest cost of
not adding the resolved kind to the outcome, and the Alternatives record why that
`core` field is filed rather than taken here.

### 5. An unresolvable correction is a free-standing assertion, and lands as `SEMANTIC`

> **Normative.** Where §3's correction arm searches and its read returns nothing,
> the resolved kind is `MemoryKind.SEMANTIC`. This governs that arm
> alone and is never reached from §3's `PREFERENCE` arm, which issues no search.
> The feedback is never dropped,
> never refused, and never held for a question on this ground.

A correction with no live target is not a correction; it is an assertion the user
happened to phrase as one. Something must still be stored, because the alternative
is discarding what the user said, and losing a user's words is the failure this ADR
exists to end — not a fallback it may take.

`SEMANTIC` is the right free-standing drawer, and choosing it **applies ADR-0009
§1's own illustration where that illustration in fact holds**: with nothing to
correct, "a fact becomes a `SemanticMemory`, not a preference" reads on a statement
standing alone. Nothing of §1 beyond the clause §9 names is disturbed by this arm. This is also the only branch on which the old table's answer was
ever right, so the fallback keeps the pre-existing behaviour for exactly the case
that behaviour fitted.

**The obvious alternative is refused: do not read the wording.** Deriving the
drawer from the content — "I prefer…" implying a preference — is natural-language
interpretation, which ADR-0009 §4 keeps out of the deterministic processor by name
("No natural-language interpretation happens here") and §6 defers to a model-backed
processor. A keyword heuristic would be a new inference signal introduced without
an ADR to warrant it, in the layer least able to justify it, and it would fire on
the words of a correction whose target the store has already told us does not
exist.

### 6. `--memory-kind` keeps its role, and acquires a sharper one

> **Normative.** A `memory_kind` present on a `FeedbackEvent` is authoritative: the
> resolution of §3 does not run, no resolution read is issued, and no later stage
> may override it. This holds for both `FeedbackKind` members.

The flag is documented today as "``--memory-kind`` defaults from ``--kind`` and can
be overridden", and it stays exactly that. What changes is what it overrides: it
was a way to pre-empt a fixed table, and it becomes the way to say "I know which
drawer, do not look". That is a stronger guarantee than it had — it now suppresses
a store read as well as a default — and it is the escape hatch §4's best-ranked
rule leaves the user, which is why the pin must survive §1's change rather than
being folded into the resolution.

Ruling this as authoritative also settles a hazard that would otherwise sit in the
implementation: a resolution that ran *and then* deferred to the pin would perform
a search whose result it discards, and a resolution that ran and *overrode* the pin
would silently discard a choice the user stated. Neither is available.

### 7. The processor is handed a resolved event, and says so if it is not

> **Normative.** A `FeedbackEvent` reaching a `FeedbackProcessor` carries a
> resolved `memory_kind`; establishing that is the calling stage's obligation.
> `RuleBasedFeedbackProcessor` **raises** on an unresolved event rather than
> returning an empty sequence. The `FeedbackProcessor` Protocol is unchanged.

`_to_record`'s final arm returns `None` for `PROCEDURAL` and `EPISODIC`, and
`process` turns that into no proposal — the correct answer for a target ADR-0009 §6
defers. An unresolved event is a different thing: it is a producer that skipped a
pipeline stage, and answering it with the deferred-kind arm's silence would report
"nothing to propose" for feedback that had everything to propose. That is the
silent drop this ADR exists to remove, reintroduced one layer down.

Failing loudly is the discipline the neighbouring write path already takes for the
same shape — `_apply` raises rather than storing a proposal as new when a fold
names an absent target, "fail-closed rather than silently downgrading", because "a
write that loses data while reporting success is worse than one that stops".

**And an empty answer to a *resolved* event is a mis-wiring, not a deferral.**

> **Normative.** Where §3 resolved the kind, a `FeedbackProcessor` returning no
> proposal is §3's composition-root obligation broken, and `learn` surfaces it
> rather than returning an empty `LearnOutcome`. Where the caller **pinned** the
> kind (§6), an empty sequence keeps exactly the meaning ADR-0009 §4 and §6 give
> it — a target this processor defers — and nothing here disturbs it.

The two cases look identical at the seam and mean opposite things. A pinned
`PROCEDURAL` is a user asking for something the deterministic processor does not
yet build, and reporting that nothing was proposed is the honest answer §6
ratified. A resolved kind, by contrast, was chosen from §3's set *because* the
processor mints it; an empty sequence there says the root wired a processor that
does not, and reporting it as "no update proposed" would drop a correction on the
strength of a wiring mistake — the same silent loss one layer down, again.

This is what makes §3's obligation enforceable in the only way an untypeable
obligation can be: it is not checked at wiring time, it is *not survivable* at use
time.

The Protocol is untouched because nothing about it changes: `process` takes a
`FeedbackEvent` and returns proposals, exactly as ADR-0009 §2 states. What changed
is one field's domain on the type it takes.

### 8. The alternative refused: widening `memory`'s conflict probe

The other side could move instead: `_detect_conflicts` could search across kinds
for a correction, and the proposal could keep the kind the caller gave it. It is
refused, and the reasons are recorded here because the refusal is the load-bearing
half of this decision.

**(a) It fixes the reach and not the type, so half of #864 survives it.** The
correction would find the espresso preference and retire it — and would then be
installed as a `SemanticMemory`, because `_apply_supersede` writes the *proposal*
as the new record. The user's corrected belief would live in a drawer their
preferences are not read from; `assistant beliefs --kind preference` would show the
preference gone and its replacement nowhere; and the stray semantic record holding
a correction utterance — the pollution #864 reports as its second harm — would be
written by the fix itself. The `--about` scope would still be discarded by
`_to_record`'s `SEMANTIC` branch (Context, above). Reach is not the whole defect.

**(b) It makes ADR-0108 §4's refusal reachable, converting a working ingest into a
store error.** `_merge` returns "the incoming record wearing the target's id" on
its ordinary arm, so a cross-kind `REINFORCE` would upsert a `SemanticMemory` at a
`PreferenceMemory`'s id — which ADR-0108 §4 refuses with `MemoryStoreError`, and
`_fold` says so in as many words, naming the kind-filtered search as the reason a
`REINFORCE` cannot reach it. The widening would make a reinforcement that succeeds
today fail at the store. Amending §4 to permit the write is strictly worse: it
exists so that a caller "cannot vaporise a belief with an episode", and a cross-kind
upsert at a belief's id is that act.

**(c) It widens ADR-0050 §1's retirement set across every kind.** A `SUPERSEDE`
retires "every other detected conflict whose `provenance.source` is in `{OBSERVED,
INFERRED}`". With a cross-kind probe, one correction could retire topically similar
observed episodes and procedures alongside the belief it meant to correct — on
topical similarity, which ADR-0045 §5 already rules too weak a signal for
retirement. The blast radius grows without a new signal to justify it.

**(d) It spends ADR-0079 §1's ceiling across four kinds instead of one.**
`conflict_limit` is "a ceiling, not a truncation budget": above it the ingest
refuses, "writing nothing, closing no window and asking for no ruling". A probe
that returns every kind's neighbours reaches that ceiling on topics where one
kind's neighbours never would, so corrections that land today would begin refusing
outright. A safety knob whose trip point depends on how many *unrelated* drawers
mention the topic is not measuring what it was set for.

**(e) The ingest lock is not a reason, and the record should say so.** It has been
offered as one — that the single-lock correctness argument depends on conflict
detection staying kind-scoped. It does not. `MemoryIngestor.__init__` weighs the
per-kind lock as the finest key that "would still be *correct*", precisely because
`_detect_conflicts` searches within one kind, and **rejects** it: it "pays by making
the safety property depend on conflict detection staying kind-scoped — a coupling a
later cross-kind conflict rule would break silently, which is the failure mode this
change exists to remove". The shipped lock is one lock over all proposals and is
immune to the widening by construction. What a cross-kind probe would foreclose is
the per-kind refinement, which was already rejected on cost. Stating this plainly is
the point of (e): a later reader who resurrects the lock as the reason will find the
four real reasons weaker than they are, and may conclude the refusal was
over-determined by a claim that does not hold.

**What the refusal costs, stated honestly.** A correction still cannot retire a
belief in a drawer *other* than the one it resolves into. Where a user holds both a
wrong preference and a wrong semantic fact on one topic, one correction fixes one of
them and the other must be corrected on its own. That residue is real, it is
narrower than the defect being fixed, and it is left open rather than closed by a
cross-kind probe, for (a)–(d).

### 9. What ratification supersedes, and under which rule

**This is a partial supersession, not an amendment, and the test is not close.**
ADR-0070 §1 permits an in-place amendment "only when the amendment changes no
decision" — where "a reader acting on the ADR would act **identically** before and
after" — and rules that "[a]ny change to what was decided requires a new ADR that
supersedes the old one — wholly, or partially (§3)". ADR-0009 §1's first bullet
decided that the *caller* carries the target kind; a reader holding it builds a
`FeedbackEvent` with a `memory_kind` they chose, and after this ADR they may build
one without. That is acting differently, so §1 is partially superseded, whatever
the edit's size — §1 is explicit that "[t]he line is the **decision**, not the size
of the edit".

That ADR-0009 §1's *reason* survives is not a counter-argument, and treating it as
one was this ADR's own first error. §1's test is about what a reader would do, not
about whether the later ADR agrees with the earlier one's motivation. Partial
supersession is "a first-class form, not a discouraged one" (ADR-0070 §3), and it
is the sanctioned tool exactly here: one clause is replaced, the remainder stays
accepted and legible.

- **ADR-0009's `Status` line takes ADR-0070 §4's leading-token form** —
  `Partially superseded by ADR-0122 (<scope>)`, with `Accepted` dropped so a prefix
  match cannot read the replaced clause as live, on **one physical line**, which §4
  makes "a going-forward requirement" so the value is read whole rather than
  reconstructed from wrapped continuations — and a dated bullet is appended to its
  header after `Date`. Per ADR-0082 §2 the leading token carries no amendment
  qualifier beside it; the record's substance is in the note. The scope names a
  clause and carries no `ADR-NNNN` token, which is §4's one authoring constraint.
- **The record lands here, while this ADR is still `Proposed`, and that is the
  rule rather than an exception to it.** ADR-0070 §1's condition on a status edit
  is that the superseding ADR **exists**, not that it is ratified, and ADR-0082 §7
  states this in terms — naming the contrary reading as "#458 — the recurring
  misreading of ADR-0070 §1's 'a supersession that has landed' clause", "not a
  governance gap but a reviewer failure mode", because "the hazard §1 names is a
  `Status` line pointing at nothing, and an atomic pair makes that unreachable".
  Deferring the edit to a later change is the failure ADR-0082 exists to close
  (#477): `main` would carry ADR-0009 §1 live beside a merged ADR-0122 replacing
  it, which is two ratified ADRs giving opposite instructions about one field.
  ADR-0117 and ADR-0115 both edited ADR-0110's `Status` in their opening commits,
  while `Proposed`.
- **An inline note is appended at ADR-0009 §1**, after its two scoping bullets, in
  the block-quote form ADR-0014 and ADR-0038 use, so a reader arriving at the
  bullet sees the supersession beside it. ADR-0009's Context, Decision and
  Consequences are not rewritten: the replaced clause stays readable as history
  beside the pointer to this ADR, which is the property ADR-0070 §2 keeps.
- **Nothing else in ADR-0009 is touched.** §2's Protocol, §3's placement rule, §4's
  mapping and provenance, §5's recorded policy interaction and §6's deferrals all
  stand. §5 is worth naming because it recorded this defect's same-kind ancestor —
  "an explicit correction that conflicts with an existing **inferred** memory is
  stored as a *new* record rather than superseding the stale one" — which ADR-0038
  and ADR-0050 closed. This ADR closes the cross-kind residue of the same shape.
- **ADR-0050, ADR-0079, ADR-0092 and ADR-0108 are untouched**, which is the
  intended property of §8's refusal: every clause those ADRs state over a
  kind-scoped probe continues to hold, neither amended nor superseded, because the
  probe does not move.
- **ADR-0121 is untouched and does not touch this**, though the two land together
  and both come out of #862. It rules *how a conflict set is judged* once one has
  been detected — an agreeing restatement reinforces rather than deferring — and
  this ADR decides *which drawer is probed for one at all*. The two compose without
  interacting: §3's resolution "names a drawer, never a conflict", so it reaches no
  question ADR-0121 answers, and ADR-0121's predicate reads a conflict set this ADR
  neither widens nor narrows. Where ADR-0121 narrowed ADR-0050 §2, this ADR's one
  citation of that arm is to a *disagreeing* case, which the arm still governs.
- **This ADR is ratified after its required reviews, not before.** It is a
  substantive contract ADR, so it is reviewed while `Proposed` and the `Status`
  flip to `Accepted` is the ratifying edit that records the outcome — ADR-0070 §1's
  permitted in-place header edit, and the sequence ADR-0015 §5 and `CONTRIBUTING.md`
  → "Contract ADRs land before their implementation" require.

### 10. What the implementing lane owes

The implementation is a separate lane, briefed after this ADR merges (golden rule
5, ADR-0015 §5). It touches `core/types.py`, `interfaces/cli.py`,
`orchestration`, `learning/processor.py` and their tests, and it owes:

> **Normative.** The lane lands §1's field change, §2's adapter change, §3's
> resolution stage and §7's refusal **together**, in one change.

Landing the field alone is worse than landing nothing. `_to_record` matches on
`event.memory_kind` and its final arm returns `None` for anything it does not
recognise, so an unresolved `None` falls through it, `process` returns an empty
sequence, and `learn` writes nothing and reports nothing wrong — the correction is
**silently dropped**, where today it is at least stored in the wrong drawer. §7's
refusal is what converts that drop into a fault, which is why it is not separable
from the field.

- **A test at the seam this ADR is about**, not only at the units: a correction
  whose only neighbour is a `PreferenceMemory` supersedes it, driven through the
  loop with a real processor and a real ingestor, since the defect was invisible
  to every test that stopped at one subsystem's boundary.
- **A test on the read's *shape*, not only on what it produced** (§3). Every other
  test here is an outcome test, and §3's clause is not observable from an outcome:
  an implementation that issues two searches, passes `bands`, omits the `kinds`
  argument, or reuses the turn's `retrieval_limit` still resolves a lone preference
  neighbour correctly and passes all of them — while carrying an extra failure
  point, the crowding §3 scopes `kinds` to avoid, and a knob that moves when
  retrieval's is tuned. A recording store therefore asserts, for one unpinned
  correction: **exactly one** `search` call, its query the event's `content`, its
  `kinds` the fixed resolution set, its `bands` unset, and its `limit` the
  resolution's own.
- **A test that the pin suppresses the read** (§6) — an injected store that fails
  the assertion if `search` is called at all is the shape that pins this, because
  a resolution that ran and then deferred to the pin passes an outcome-only test.
- **The same shape for §3's `PREFERENCE` arm**: an unpinned `PREFERENCE` event
  against a store holding a better-ranked semantic neighbour must resolve to
  `PREFERENCE` and issue no search. An outcome-only test passes here by accident
  whenever the store happens to hold nothing.
- **A test for §3's mintable-kind restriction** where the best-ranked candidate
  overall is an `EpisodicMemory`: the correction must resolve to the best-ranked
  *mintable* drawer, and must not vanish.
- **A test pinning the residue, not hiding it** (§3): a store crowded with
  higher-ranked non-mintable records beyond the resolution's reach resolves by §5
  and lands as `SEMANTIC`. It is asserted as the *known* outcome, cited to #457,
  so a later reader finds the boundary recorded rather than discovering it in
  another QA run.
- **A test for §5's fallback** on an empty store, and **for §4** where candidates
  span both mintable kinds.
- **A test that a failing resolution read propagates** (§3): a store whose
  `search` raises `MemoryStoreError` must surface it from `learn` with nothing
  proposed and nothing written — asserted on both halves, since a fallback to §5
  passes any test that only checks the call raised nothing.
- **A test that §7 raises** rather than returning an empty sequence, and a second
  for its other clause: a stub processor returning `()` for a **resolved** event
  surfaces, while the same `()` for a **pinned** `PROCEDURAL` still returns an
  empty `LearnOutcome`. Both, or the two cases have been collapsed.
- **No change to `memory/`.** If the lane concludes it needs one, that is §8 being
  reopened, and it stops and brings back an ADR rather than widening the probe.

### 11. What this ADR does not decide

- **Whether the outcome should name the resolved drawer.** Considered and filed
  (Alternatives); it is `core/types.py` surface for an observability improvement,
  and this ADR keeps its `core` surface to the one field the decision cannot be
  implemented without.
- **The observed path.** `learning/observer.py` mints its own proposals from
  episodes under ADR-0077 and names its own kinds; it has no `FeedbackEvent` and
  no adapter default, so nothing here applies to it. Whether an *observed*
  correction should reach across kinds is a different question with different
  costs, and it is untouched.
- **The cross-drawer residue** §8 records: one correction still resolves to one
  drawer. Reopening it means reopening §8's refusal, with the four costs it
  states.
- **The cross-kind misresolution** §3 records: a semantic target outranked by an
  unrelated preference resolves to the wrong drawer, where today's fixed default
  would have reached it. Bounded, visible, and answered by §6's pin — but real, and
  the reason §4's best-ranked rule keeps an escape hatch rather than standing alone.
- **Retrieval's reach.** A target ranked below what one read surfaces is not found
  here any more than it is found by the conflict probe; that is issue #457's, it
  is stated in §3 rather than papered over, and it is neither closed nor widened.
- **ADR-0009 §6's deferrals.** `PROCEDURAL` and `EPISODIC` correction targets stay
  deferred, and §3's candidate set is written to widen with them rather than to
  outlive them.
- **Anything about the conflict threshold, the ceiling, the retirement set or the
  fold refusals.** They stay `memory`'s, unamended, which is the point of §3's
  "names a drawer, never a conflict".

## Consequences

- **The command named for corrections can correct.** A correction reaches a target
  in whatever drawer the belief lives in, **where §3's bounded read surfaces it**,
  and the existing supersede path — which the QA run proved sound — runs unchanged
  from there. What the read never surfaced is still not reached (§3, issue #457);
  what changes is that the drawer is no longer excluded by construction.
- **The correction lands in the right drawer, not merely near it.** The corrected
  belief is readable from kind-scoped surfaces, and a correction given with
  `--about` keeps its scope on the preference branch instead of losing it to
  `_to_record`'s semantic arm.
- **One extra store read per unpinned correction**, and with it one extra place a
  correction can fail. A ranked `search` on a path a user invokes by hand, on the
  same store the ingest is about to read anyway; it is traced by ADR-0119 §8's
  emitter, so it is visible in the measure stream rather than hidden. A transient
  failure there now fails the `learn` that might otherwise have completed (§3) —
  the accepted cost of refusing to let a failure choose the drawer.
- **`orchestration` grows one pipeline stage**, and `learning` and `memory` grow
  nothing. `learning` stays `core`-only (ADR-0009 §3), `interfaces` stays thin
  (golden rule 3), and `memory`'s writer keeps every safety property it states.
- **A `core` type's field becomes optional**, so every producer of `FeedbackEvent`
  gains a state it must not skip past — which §7 makes loud rather than silent.
- **The cross-drawer residue stays**: one correction fixes one belief, and a user
  holding wrong beliefs in two kinds on one topic corrects each. §8 records why
  closing it with a cross-kind probe would cost more than it buys.
- **Revisit when** ADR-0009 §6's `PROCEDURAL`/`EPISODIC` targets are taken up (§3's
  candidate set widens with them), when a model-backed `FeedbackProcessor` lands
  (§5's fallback is the first thing a reading of the wording would replace, and
  §3's placement is what lets it be replaced in one stage), or if the cross-drawer
  residue proves common enough in use to reopen §8.

## Alternatives considered

- **Widen `memory`'s conflict probe for corrections.** Rejected in §8, on four
  grounds — it leaves the record mistyped, it makes ADR-0108 §4's refusal reachable
  on a `REINFORCE`, it widens ADR-0050 §1's retirement set across kinds, and it
  spends ADR-0079 §1's ceiling across kinds — and *not* on the ingest-lock ground
  that has been offered for it, which §8(e) shows does not hold.
- **Keep `memory_kind` required and let the pipeline override it for a
  correction.** Rejected in §1 and §6: the pin and the adapter's invented default
  are indistinguishable once the field is filled, so an override rule either
  discards a user's explicit `--memory-kind` or reproduces the defect whenever a
  candidate exists in the defaulted drawer. The information has to survive to the
  resolver, and the only place it survives is the field's own domain.
- **Refuse `--memory-kind` together with `--kind correction`,** making the intent
  alone decide and needing no `core` change. Rejected in §6: it buys the saving by
  deleting a documented capability and leaves §4's best-ranked rule with no escape
  hatch, and it puts a semantic rule about record types in an adapter that golden
  rule 3 keeps thin.
- **Resolve inside `learning`, in the processor.** Rejected in §3: ADR-0009 §3
  keeps `learning` dependent only on `core` and gives the pipeline the job of
  closing the loop; injecting a store seam into every `FeedbackProcessor` pays a
  per-implementation cost for a question that is the same for all of them, and
  `LearningLoop` already holds the store.
- **Resolve inside the CLI, before the event is built.** Rejected in §2: the
  adapter is thin by golden rule 3, and it is on the far side of the wire from the
  store in any case (ADR-0083) — it has nothing to read.
- **Give `FeedbackProcessor` a mintable-kinds declaration**, so §3's set could be
  asked for rather than named. Rejected in §3: it is a Protocol change under golden
  rule 5, with its own triad, to spare this ADR from writing two enum members and a
  clause saying who amends them. The composition-root obligation states the same
  constraint at the same strength, and §7's second clause makes breaking it loud.
- **Add a resolution seam as a new Protocol**, so the step is injectable. Rejected
  as surface with one implementation and one caller: `MemoryStore.search` already
  expresses the read, golden rule 5 would put the Protocol's triad ahead of a step
  that is four lines of pipeline, and ADR-0015 §5's cost is not worth a seam nobody
  has asked to substitute.
- **Mint one proposal per matching kind,** using `process`'s `Sequence` return.
  Rejected in §4: it asserts as a standing fact what the user may have stated as a
  preference, and it guarantees the duplicate record #864 reports as its second
  harm.
- **Derive the drawer from the correction's wording.** Rejected in §5: it is the
  natural-language interpretation ADR-0009 §4 excludes from the deterministic
  processor by name and §6 defers to a model-backed one, introduced without an ADR
  to warrant the signal.
- **Report the resolved kind on `LearnOutcome` or `IngestSummary`,** so a user sees
  which drawer was chosen. Not taken here: it is a second `core/types.py` field for
  a fact the existing outcome and `assistant beliefs` already make observable (§4),
  and this ADR keeps its `core` surface to the one field that the decision cannot be
  implemented without. Filed as a follow-up rather than ratified in passing.
