# 85. The promoted engine surface: fifteen methods, twenty-four types, one closed graph

- Status: Accepted
- Date: 2026-07-31
- **This is ADR-0084 §5's step 2, and it exists so that no lane authors `core`
  contract surface unreviewed.** ADR-0084 decided *that* the façade is promoted
  to a Protocol, *what class* of thing promotes with it, and the boundary rules
  the surface must satisfy. This decides *what the surface is*: the method
  signatures, the promoted type set and their normative fields, the complete
  transitive type graph those fields reach, ADR-0084 §8's step-identity field,
  and the size limit as a contract clause.
- **Written with implementation contact, as ADR-0084 §4 requires.** Every
  signature, field and type below was read off `orchestration/engine.py`,
  `runner.py`, `questions.py`, `loop.py`, `observation.py` and `conversations.py`
  at `main` @ `0abdb3f`, not derived from the ADRs. **Every line citation below is
  grounded at that commit** and was re-checked against it symbol by symbol. Where the corpus and the tree
  disagree, §11b says so and says which one this ADR follows.
- **No implementation lands with it.** No `src/`, no `tests/`. It ratifies what
  `core/protocols.py` and `core/types.py` will contain; the triad — Protocol +
  shared conformance suite + canonical fake in `ai_assistant.testing` — is
  ADR-0084 §5's step 3 and a separate lane, merging before any client (golden
  rule 5, ADR-0015 §5).
- **The belief *listing* and the single-belief view return different types, and
  that is this ADR's one substantive departure from the tree.** ADR-0077 §6
  splits the two surfaces — the listing "resolves *existence* and renders the
  count, the lost count, and the adjusted confidence", the single-belief view
  "renders the surviving citations as readable evidence". `Engine._project`
  serves both and resolves content for both, which is **#552**. §4a decides the
  shape that makes the ratified split expressible, and §8f shows what it does to
  the frame arithmetic.
- **The byte-level wire encoding is ratified by ADR-0087, not here.** §8c fixes
  the size limit and that it is measured on one canonical encoding; **ADR-0087**
  fixes that encoding, with normative test vectors (§11a). Writing the grammar
  here was attempted and withdrawn; so was leaving it to an implementing lane,
  which the triad's canonical fake refutes (§8c).
- **This ADR amends nothing.** §12 applies ADR-0082 §1's test to every earlier
  ADR whose text this one touches and finds no record owed — each of the clauses
  examined is a deferral whose deferring sentence stays true and now has an
  answer (ADR-0083 §15's carve-out), or a conditional whose consequent this ADR
  is. Ratifying a `Proposed` ADR is not itself an amendment event (ADR-0082 §1).

## Context

### What ADR-0084 handed over, and what it deliberately did not answer

ADR-0084 §5 concluded that ADR-0042 §1's own revisit trigger has fired: a client
satisfying the façade's surface over a transport *is* the second engine
implementation ADR-0042 named, so the façade is promoted to a Protocol in
`core/protocols.py` and its result types to `core/types.py` (§4). It then split
the work in two, and the split is the reason this ADR exists:

> Pinning a nineteen-method surface and ten DTOs' fields *here*, in an ADR about
> a transport, would be the unspiked seam #281 and `CONTRIBUTING.md`'s
> spike-first guidance both warn against; but leaving them to a lane would make
> that lane the unreviewed author of `core` contract surface, which golden rule 5
> and ADR-0015 §5 exist to prevent.

So ADR-0084 §11 defers "the field layout of the promoted DTOs and the exact
method set of the Protocol" to this ADR by name, and #281 — filed out of
ADR-0042's own architecture review, for want of implementation contact — is its
brief.

### The transitive closure is the load-bearing half, and it is much larger than three types

ADR-0084 §4 is explicit that the promoted set is bounded by "the *transitive
closure* of what the Protocol's methods name, not just the types they return",
and names three members that live in `orchestration` today: `Disposition`
(`runner.py:203`), `QuestionState` (`questions.py:92`) and `SuccessorLink`
(`questions.py:171`). It says the surface ADR "owns the complete graph
explicitly rather than discovering it mid-implementation", and the reason is
mechanical: promote a type to `core` while something its fields reach stays in
`orchestration`, and `core` imports `orchestration`, which golden rule 2 forbids
and `lint-imports` fails.

Enumerated from the tree, the closure is **twenty-four types**, not three.
Naming the three ADR-0084 could see from where it stood would have left twenty
for the triad lane to find one `lint-imports` failure at a time. §5 below is that
enumeration, and §6 is the boundary: what the closure reaches and stops at.

### The engine's surface is fifteen methods, not nineteen

ADR-0084 §5 estimates "around nineteen methods" and its Consequences repeat the
figure. The tree has **seventeen** public methods on `Engine`, of which `start()`
and `aclose()` are ruled off the Protocol by §5 itself — they are the hub's
lifecycle, and a client that could call `aclose()` could shut down the hub from a
spoke. The promoted surface is therefore **fifteen** methods.

That is a count, not a decision, and correcting it costs nothing: §5's argument —
that a spoke needs the whole surface, so a Protocol trimmed to today's caller
would be re-widened by the first adapter that reads beliefs — is unaffected by
whether the whole surface is fifteen or nineteen. The figure is stated here so
the conformance suite has a number to be complete against.

### What is genuinely unsettled, and what this ADR must not re-open

Three questions ADR-0084 left open are settled here because a Protocol cannot be
written without them: what a promoted model's fields *are*, what a method's
declared failures are, and what "the size limit is part of the contract" means as
a number two implementations can both compute.

### The listing and the single-belief view are two surfaces, and the tree has one type

ADR-0077 §6 divides the inspection surface in as many words:

> The listing resolves *existence* and renders the count, the lost count, and the
> adjusted confidence; the single-belief view renders the surviving citations as
> readable evidence and the lost ones as tombstones.

`Engine._project` (`engine.py:2254`) serves both — `_beliefs` calls it per record
and `_belief` calls it once — and it resolves each citation's *content* for both,
so every belief on a fifty-row page carries the full text of every episode behind
it. Two ratified ADRs ask the listing for a count; the code delivers the corpus.
That is **#552**, filed out of ADR-0086's lane and handed here because the second
half of it is a DTO shape.

**The tree's own adapter already honours the split**, which is the implementation
contact that decides §4a. `_render_belief(belief, *, evidence=False)`
(`cli.py:1987`) documents the two views and prints citations only when `evidence`
is true; the listing path and its `_why` line (`cli.py:1936-1950`) read `band`,
`kind`, `confidence`, `content`, `last_updated`, `valid_until`, `id`,
`evidence_count`, `lost_evidence` and `unsupported` — and never `evidence`. The
only consumer that exists already wants the smaller shape.

**This matters now rather than later** because a promoted `Belief` that carries
resolved content on the listing path makes the over-delivery contract surface,
where withdrawing it is a Protocol change instead of an edit — and because §8's
frame arithmetic has a multiplicative term it cannot bound while the listing
carries contents.

Three are closed and stay closed: a smaller Protocol covering just what the CLI
uses (rejected, §5); a separate wire schema mapped to and from the façade types
(rejected, §4); and `core/protocols.py` as the placement (§5 answered ADR-0042's
objection to that file). None is relitigated below.

## Decision

### 1. The Protocol is `AssistantEngine` in `core/protocols.py`, and it carries fifteen methods

**We will add one Protocol, `AssistantEngine`, to `core/protocols.py`**, carrying
the fifteen request methods below and nothing else. It is named for the
capability rather than for the class that first satisfies it, as every other
Protocol in that file is, and it does not collide with the concrete
`orchestration.engine.Engine` that implements it.

**It is the first *provided* contract in a file of consumed ones**, and that
asymmetry is real. ADR-0084 §5 already ruled on it — the asymmetry "is an
observation about the file's current contents, not a rule anyone ratified", and
`core/protocols.py` is the floor path the review process already treats as
contract surface. This ADR adds one obligation the observation earns: the
Protocol's own docstring states that it is provided by `orchestration` and
consumed by `interfaces`, so a reader of the file is not left to infer the
direction from the method names.

**Lifecycle is off the surface.** `start()` and `aclose()` stay on the concrete
class the composition root builds (ADR-0084 §5). Two consequences follow and are
stated because they are easy to miss:

- **`RuntimeError` on a shutting-down engine is not a declared failure of any
  Protocol method.** `Engine._reject_if_closing` raises it today, and it is a
  property of *that* object's lifecycle, not of the contract. A client never
  observes it: ADR-0083 §4's phase A stops the listener and unlinks the socket
  before draining, so a spoke arriving during shutdown reads a closed door, which
  ADR-0084 §1 rules is the correct answer. The conformance suite therefore does
  not require it, and an implementation without a lifecycle does not have to
  invent one to conform.
- **The concrete `Engine` keeps both methods and stays substitutable**, because a
  Protocol constrains what an implementation must have, not what it may not.

### 2. One argument convention, stated once and applied to all fifteen

ADR-0042 §3–§4 fixed keyword-only for `converse` and `resume`. The other thirteen
methods have no ratified convention, and thirteen ad-hoc choices in a `core`
Protocol is thirteen things a later widening can get inconsistently. So:

> **The subject of a call — the one thing it acts on — is positional. Every
> other argument is keyword-only.**

The subject is what the method's name is about: the utterance `converse` runs,
the token `resume` answers, the event `learn` folds, the record `belief` reads
and `forget` destroys, the question `answer` and `forget_question` name, the
conversation `conversation` and `forget_conversation` name. Modifiers —
`timeout`, `approved`, `accept`, `conversation_id`, `bands`, `kinds`, `limit`,
`offset` — are keyword-only.

**Why the rule, rather than freezing what is there.** A keyword-only modifier can
be joined by another without changing any call site, and an optional *positional*
cannot be joined by a second optional without a caller having to know their
order. On the wire this is invisible — ADR-0084 §3 makes a request payload "a
JSON object whose members are the call's arguments", so every argument is named
there regardless — which is precisely why the Python surface should agree with
it: two surfaces that disagree about which arguments are ordered is one more
thing for a spoke to get wrong for no benefit.

**The one call this changes is `observe`.** It reads
`observe(conversation_id: str | None = None)` today, positionally, and becomes
`observe(*, conversation_id: str | None = None)`. Its argument is an optional
*selector* — "this conversation, or the most recently active" — which is exactly
what `converse`'s `conversation_id` is, and that one is already keyword-only. The
cost is a one-word edit at `cli.py:1153`, which the client lane (ADR-0084 §5's
step 4) is rewriting anyway.

### 3. The fifteen signatures

Written as they appear on the Protocol, **verbatim rather than abbreviated** —
this block is what an implementation is generated from, so unlike §4's tables it
spells every annotation out. `Identifier` and `UtcInstant` are `core/types.py`'s
existing annotated aliases (a non-blank `str`, a tz-aware `datetime`);
`EncodableText` is `core/types.py:343`'s alias for a `str` with a UTF-8
encoding (§4c), and `utterance` is the only bare-text argument on the surface; `DEFAULT_PAGE_SIZE` is §3a below.

```python
class AssistantEngine(Protocol):
    # The two turn calls (ADR-0042 §3)
    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome: ...

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,
    ) -> TurnOutcome: ...

    # The two accumulation legs
    async def learn(self, event: FeedbackEvent) -> LearnOutcome: ...

    async def observe(
        self, *, conversation_id: Identifier | None = None
    ) -> ObservationReport: ...

    # The inspection surface (ADR-0073 §7, ADR-0077 §6 — two surfaces, two types)
    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]: ...

    async def belief(self, record_id: Identifier) -> Belief | None: ...

    async def forget(self, record_id: Identifier) -> bool: ...

    # The deferred-question surface (ADR-0078 §8)
    async def questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]: ...

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]: ...

    async def answer(
        self, question_id: Identifier, *, accept: bool
    ) -> AnswerOutcome: ...

    async def forget_question(self, question_id: Identifier) -> bool: ...

    # The conversation surface (ADR-0074 §2, §8)
    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]: ...

    async def conversation(
        self, conversation_id: Identifier
    ) -> ConversationDigest | None: ...

    async def forget_conversation(self, conversation_id: Identifier) -> bool: ...

    # Durable recovery (ADR-0052 §1)
    async def pending_confirmations(self) -> tuple[Confirmation, ...]: ...
```

Four things in that block are decisions rather than transcription, and each is
argued below: the page-size default (§3a), the `tuple` return on
`pending_confirmations` (§3b), `Identifier` on every id argument (§3c), and
`Sequence` on the two filters together with the observation clause that makes it
safe (§3d).

#### 3a. One page-size constant, `DEFAULT_PAGE_SIZE = 50`, in `core/types.py`

Three constants carry the figure 50 today — `_DEFAULT_BELIEF_PAGE`
(`engine.py:124`), `_DEFAULT_CONVERSATION_PAGE` (`:131`) and
`DEFAULT_QUESTION_PAGE` (`questions.py:81`) — and all three cite the same
authority: ADR-0073 §2's bounded default, itself matching `AuditTrail.recent`.
Moving the surface to `core` while leaving three private module constants behind
in two `orchestration` modules would leave the Protocol's stated defaults with no
public name to refer to.

**So one public constant, `DEFAULT_PAGE_SIZE: Final[int] = 50`, lives in
`core/types.py`**, and all four paging signatures default to it —
`beliefs`, `questions`, `interrupted_questions` and `recent_conversations`.

**And the default is normative, not decorative.** A default written in a
`Protocol` method signature binds nobody: each implementation writes its own, and
a client that defaulted to 100 while the engine defaulted to 50 would return a
different page for the same call — the divergence ADR-0084 §4 moved the size
limit into the contract to prevent, arriving one field over. So the contract
clause is:

> An implementation that is called without `limit` behaves as though
> `DEFAULT_PAGE_SIZE` had been passed.

The conformance suite asserts it on all four.

#### 3b. `pending_confirmations` returns a tuple

It returns `list[Confirmation]` today, and ADR-0052 §2 prints that signature. It
becomes `tuple[Confirmation, ...]`, for three reasons in the order they bind:

- **Every other enumeration on this surface already returns a tuple**, and a
  fifteen-method Protocol with one method returning a mutable page is a wart a
  spoke author has to remember.
- **ADR-0068 §1's house form is the immutable collection.** The rule is written
  about model *fields*, so it does not reach a return type on its own; but the
  reason behind it does — a caller that mutates a returned page has changed
  nothing about the engine's state and may believe otherwise.
- **A wire client materialises a fresh sequence per call regardless**, so the
  mutable spelling buys no implementation freedom on the side that would need it.

**ADR-0052 is not amended by this**, and §12 shows the work: its own appended
note already routes the spelling here, recording that `pending_confirmations`
joining the contract surface "is a **live obligation** on the surface ADR (#281),
which ADR-0084 §4 makes the owner of the exact set."

#### 3c. Every id argument is `Identifier`, and that is a real strengthening

`Identifier` is `Annotated[str, AfterValidator(_non_blank)]`. The engine takes
bare `str` today and treats each id as opaque, which is right — but "opaque" and
"may be empty" are different claims, and only the first is intended. A blank
`record_id` reaching `MemoryStore.get` returns `None` and renders as "no such
belief", which is a true sentence about a call the caller never meant to make.

**Because these are Protocol arguments rather than model fields, the annotation
does not validate anything by itself** — and `Identifier` does more than validate.
Its `AfterValidator` is `_non_blank`, which **returns the value stripped**
(`core/types.py`): it is a normaliser as well as a check. Left to the annotation,
a wire client that deserialises its arguments through `Identifier` would turn
`" rec-1 "` into `"rec-1"` and find the record, while an in-process engine handed
the raw `str` would look up `" rec-1 "` and answer `None`. Two implementations,
one call, opposite answers — §4's divergence arriving through a validator nobody
thought of as behaviour.

So the contract clause carries the whole of `Identifier`, not half of it:

> **Every identifier argument undergoes `Identifier` validation before any I/O**
> — which both **rejects** a blank value with `ValueError` and **strips**
> surrounding whitespace from the value the implementation then uses.

Stating the normalisation rather than only the refusal is the load-bearing half.
A rule that said "reject blank" would leave stripping optional, and optional
normalisation on an *identity* argument is worse than none: it makes the answer to
`belief(" rec-1 ")` a property of which implementation you are holding.

This is the same shape as §3d's materialisation clause and §8's page-range
clause: an annotation states the intent and a contract clause makes it
enforceable, so the conformance suite can hold both implementations to the same
answer instead of one refusing and the other returning `None`.

`ContinuationToken.handle` is likewise `Identifier` on the model (§4), which is
where a `frozen` pydantic model *does* validate.

#### 3d. The two filters stay `Sequence`, and the observation clause comes with them

`beliefs` takes `bands: Sequence[BeliefBand] | None` and `kinds: Sequence[MemoryKind] | None`.
Keeping `Sequence` rather than narrowing to `tuple` keeps a caller from having to
convert a list it already holds, and the wire client serialises to a JSON array
either way.

What makes that safe is a clause the engine already satisfies and the Protocol
must state, because ADR-0065's input-observation rule binds stores and not this
surface:

> **Both filters are materialised before the implementation's first `await`.** A
> caller that mutates the sequence it passed cannot change which page it gets.

`Engine.beliefs` does this at `engine.py:1329-1330`, snapshotting both to tuples
before creating the tracked task; a wire client does it by construction, having
serialised the arguments before sending. The clause exists so the conformance
suite can prove it of *both*, rather than it being an accident of how one of them
happens to be written.

**Empty and `None` remain different**, as ADR-0073 §2 already fixed: `None`
selects every band or kind, an empty sequence selects nothing, and the two
filters compose by conjunction.

### 4. The twenty-four promoted types and their normative fields

Every type below moves to `core/types.py` as a frozen pydantic model or a
`StrEnum`, under ADR-0068 §1 — `frozen=True`, `tuple` collections, nested models
frozen (§9 covers the mechanism and what changes with it). Fields are listed in
declaration order; a trailing `= …` is the default.

**`str` in these tables means `EncodableText`** (§4c) — every string this
surface carries must have a UTF-8 encoding. It is written `str` below for readability and
stated once here rather than repeated thirty times, which is the same choice §4c
makes for the same reason. **The abbreviation is confined to these tables**: §3's
Protocol block spells `EncodableText` out, because that block is what an implementation
is generated from and a reader of it may never reach this line.

**Group A — the turn surface (from `orchestration/engine.py`)**

| Type | Fields |
| --- | --- |
| `ContinuationToken` | `handle: Identifier` |
| `Confirmation` | `tool_id: Identifier`, `tool_description: str`, `parameters: FrozenJsonMapping`, `reason: str`, `token: ContinuationToken` |
| `StepOutcome` | `disposition: Disposition`, `state: ExecutionState`, `step_id: Identifier`, `tool_id: Identifier \| None = None`, `confirmation: Confirmation \| None = None` |
| `TurnOutcome` | `turn: TurnResult \| None`, `step: StepOutcome \| None = None`, `conversation_id: Identifier \| None = None`, `capture_degraded: bool = False` |

`StepOutcome.step_id` is new; §7 is its own section because ADR-0084 §8 ratified
the field and left its spelling and type here.

**Group B — the learn surface (from `orchestration/engine.py`)**

| Type | Fields |
| --- | --- |
| `LearnDecision` (`StrEnum`) | `STORED`, `REJECTED`, `REINFORCED`, `SUPERSEDED`, `DEFERRED`, `STORED_TEMPORARILY` |
| `QueueOutcome` (`StrEnum`) | `QUEUED`, `ALREADY_ASKED`, `QUEUE_FULL`, `NOT_QUEUABLE` |
| `QueuedQuestion` | `outcome: QueueOutcome`, `question_id: Identifier \| None = None`, `question_state: QuestionState \| None = None` |
| `IngestSummary` | `decision: LearnDecision`, `record_id: Identifier \| None`, `reason: str`, `queued: QueuedQuestion \| None = None` |
| `LearnOutcome` | `results: tuple[IngestSummary, ...]` |

**Group C — the inspection surface (from `orchestration/engine.py`)**

| Type | Fields |
| --- | --- |
| `Evidence` | `content: str \| None = None` |
| `BeliefSummary` | `id: Identifier`, `band: BeliefBand`, `kind: MemoryKind`, `content: str`, `confidence: float` (`ge=0.0, le=1.0`), `last_updated: UtcInstant`, `evidence_count: int = 0` (`ge=0`), `lost_evidence: int = 0` (`ge=0`), `valid_until: UtcInstant \| None = None` |
| `Belief` | `id: Identifier`, `band: BeliefBand`, `kind: MemoryKind`, `content: str`, `confidence: float` (`ge=0.0, le=1.0`), `last_updated: UtcInstant`, `evidence: tuple[Evidence, ...] = ()`, `valid_until: UtcInstant \| None = None` |
| `ConversationSummary` | `id: Identifier`, `started_at: UtcInstant`, `last_active_at: UtcInstant`, `last_turn_at: UtcInstant \| None = None` |

**Group D — the deferred-question surface (from `orchestration/questions.py`)**

| Type | Fields |
| --- | --- |
| `QuestionState` (`StrEnum`) | `OPEN`, `INTERRUPTED`, `DECLINED`, `APPLIED`, `STALE`, `REDEFERRED` |
| `Retirement` | `record_id: Identifier`, `content: str \| None` |
| `SuccessorLink` | `id: Identifier`, `state: QuestionState` |
| `Question` | `id: Identifier`, `state: QuestionState`, `content: str`, `kind: MemoryKind`, `band: BeliefBand`, `rationale: str`, `reason: str`, `retires: tuple[Retirement, ...]`, `asked_at: UtcInstant`, `expires_at: UtcInstant \| None`, `successor: SuccessorLink \| None = None` |
| `AnswerKind` (`StrEnum`) | `APPLIED`, `REJECTED`, `STALE`, `REDEFERRED`, `NOT_OPEN` |
| `AnswerOutcome` | `kind: AnswerKind`, `question_id: Identifier`, `record_id: Identifier \| None = None`, `successor: SuccessorLink \| None = None`, `successor_refused: bool = False`, `disposed: bool = False` |

**Group E — the observation surface (from `orchestration/observation.py`)**

| Type | Fields |
| --- | --- |
| `ObservedProposal` | `content: str`, `kind: MemoryKind`, `step: MemorySource`, `confidence: float` (`ge=0.0, le=1.0`), `rationale: str`, `decision: LearnDecision \| None`, `record_id: Identifier \| None`, `reason: str`, `evidence: tuple[Evidence, ...] = ()` |
| `ObservationReport` | `proposals: tuple[ObservedProposal, ...] = ()`, `discarded_unusable: int = 0` (`ge=0`), `discarded_over_limit: int = 0` (`ge=0`), `dropped_unsupported: int = 0` (`ge=0`), `route: str \| None = None`, `conversation_id: Identifier \| None = None`, `episodes_read: int = 0` (`ge=0`) |

**Group F — the remaining reached types**

| Type | Home today | Fields |
| --- | --- | --- |
| `Disposition` (`StrEnum`) | `runner.py:203` | `EXECUTED`, `DENIED`, `AWAITING_CONFIRMATION`, `NO_CAPABLE_TOOL`, `AMBIGUOUS_CAPABILITY` |
| `TurnResult` | `loop.py:118` | `goal: Goal`, `context: CurrentContext`, `memories: tuple[MemoryRecord, ...]`, `plan: ActionPlan`, `memory_degraded: bool = False` |
| `ConversationDigest` | `conversations.py:140` | `id: Identifier`, `started_at: UtcInstant`, `last_turn_at: UtcInstant \| None`, `recorded_turns: int` (`ge=0`) |

#### 4a. `beliefs()` returns `BeliefSummary`, and the split is enforced by the type

**The question ADR-0084 left unasked**, and which #552 makes unavoidable before
`Belief` becomes contract surface: must the promoted surface be able to
distinguish *"this citation exists and resolves, but its text is not delivered
here"* from *"this citation no longer resolves"*?

**On the tree's shape it cannot.** `Evidence` carries `content: str | None` and
`lost` is `content is None` (`engine.py:602`, `:605-607`); `Belief.evidence_count`
is `len(self.evidence)` and `lost_evidence` counts the `None`s (`:683-690`). So a
listing that renders a count must populate `evidence`, and an entry with no
content is *indistinguishable from a tombstone*. Exactly two behaviours are
available: ship every episode's full text on every page, or misreport every
citation as lost. The tree does the first.

> **We will give the two surfaces two types.** `beliefs()` returns
> `tuple[BeliefSummary, ...]`; `belief()` returns `Belief | None`.
> `BeliefSummary` carries `evidence_count` and `lost_evidence` as **fields** and
> has **no `evidence` field at all**. `Belief` is unchanged: it carries the
> resolved `evidence` tuple, and its counts stay derived from it.

**The deciding reason is that this is the only shape where the wrong behaviour is
unrepresentable rather than merely detectable.** Every alternative leaves a
`beliefs()` implementation *able* to ship citation contents, so the ratified split
survives only as a clause a conformance suite has to police. Here the return type
has nowhere to put a content, so a conforming listing cannot over-deliver — and my
five prose contract clauses (§3a, §3c/§9, §3d, §7, §8) do not become six. A
contract that makes a rule structural has spent the same words to better effect.

**The second reason is implementation contact, which is what ADR-0084 §4 asked
this ADR to be written with.** The shipped listing renderer reads exactly
`BeliefSummary`'s nine fields and never `evidence` (`cli.py:1936-1950`, `:1987`).
The only adapter that exists already treats these as two shapes; this makes the
contract agree with it rather than with `_project`.

**The third is that it bounds the frame by construction**, which §8f works
through: with no per-citation field on the listing type, the page × citations ×
content term does not exist, and what is left is the single-belief view's
citations — the term #473 was always about.

**The same three names read identically on both types**, which is what keeps a
renderer from needing two code paths — but only **two** of them change category,
and being precise about which is load-bearing:

| Name | On `BeliefSummary` | On `Belief` |
| --- | --- | --- |
| `evidence_count` | **field** — nothing to derive it from | property over `evidence` |
| `lost_evidence` | **field** — same reason | property over `evidence` |
| `unsupported` | **property**, over the two counts | property over `evidence` |

`unsupported` stays derived on **both**, because on `BeliefSummary` the two count
fields already determine it. Making it a field there would be the second source of
truth §6b rejects, and it would put a value on the wire that a client can compute
exactly — so one implementation could send `unsupported: true` while another
omitted it, and the same call would measure two different sizes against §8c. §4's
field table and §6b's property table are the normative pair; this row exists so
they are read together.

`unsupported` has one definition everywhere — `evidence_count > 0 and
lost_evidence == evidence_count` — so a belief citing nothing is not
"unsupported", it is supported by the user's own word (ADR-0038 §1a).

**ADR-0073 §4's floor gets a static guarantee rather than a convention.** Its rule
is that "a citation the surface cannot render as evidence is never rendered *as*
evidence — not as a reassuring id, not silently dropped". A client holding a
`BeliefSummary` cannot render a citation as evidence, because it holds no
citations; it holds how many there are and how many are gone, which is what
ADR-0073 §4 asked the listing to convey.

**This does not change what the listing computes, only what it ships.** The
adjusted confidence is a function of how many citations resolved
(`presented_confidence`, ADR-0077 §6), so the listing still resolves *existence*
per citation. That is #552's item 1 and it belongs to the lane that edits
`_project`; a batch read is what makes it cheap, which is ADR-0086 §6's
`get_many` — named as context, not as a dependency of this ADR.

#### 4b. The cross-field invariants promote with the fields

**A field list is not the whole of a DTO's contract, and dropping an invariant
while promoting one is the quiet way to lose it.** Five of these types carry a
cross-field rule — four state one in the text they carry today, and `BeliefSummary`
acquires one with its counts (§4a); those rules are ratified content,
not commentary, and they become **model validators** on the promoted models —
which is precisely the "what it adds is validation" ADR-0084 §4 names as the
reason for moving to pydantic in the first place.

| Model | Invariant |
| --- | --- |
| `StepOutcome` | `confirmation` is present **iff** `disposition` is `AWAITING_CONFIRMATION` |
| `IngestSummary` | `queued` is present **iff** `decision` is `DEFERRED` |
| `QueuedQuestion` | `question_id` and `question_state` are both `None` when `outcome` is `QUEUE_FULL` or `NOT_QUEUABLE` |
| `AnswerOutcome` | `record_id` is present **iff** `kind` is `APPLIED`; `successor` and `successor_refused` are set only when `kind` is `REDEFERRED` |
| `BeliefSummary` | `lost_evidence <= evidence_count` |

**`StepOutcome`'s is the one a wire client cannot work around**, which is why it
is listed first. ADR-0042 §4 obliges a parked step's result to carry the
confirmation content and the opaque token the adapter renders and relays; a
nullable field with no invariant permits an `AWAITING_CONFIRMATION` outcome
carrying neither, and a client handed one has nothing to resume with and no
contract violation to point at. The invariant is what makes "park, render,
relay" a sequence a spoke can rely on rather than one that happens to work
in-process.

**The three others are the same shape**: each is an existing ratified rule
(ADR-0078 §10 item 9 for `IngestSummary.queued`, ADR-0078 §7 for
`QueuedQuestion`, ADR-0078 §8 for `AnswerOutcome`) that a bare field list would
silently drop. **`BeliefSummary`'s is the price of counts-as-fields**: on `Belief`
the counts cannot disagree with the evidence because they are computed from it,
and moving them to fields buys the listing its shape at the cost of one
constraint the model must now assert for itself.

**`QueuedQuestion`'s is stated in one direction only, deliberately.** The
converse — that a `QUEUED` or `ALREADY_ASKED` outcome always names a question —
is *nearly* true and is not asserted, because `from_admission` keeps a defensive
branch for an admission whose deferral is absent (`engine.py:377-378`), which
`DeferralAdmission`'s own validator is supposed to make unreachable. Asserting an
invariant that a defensive branch can violate would turn a store-conformance
fault into an unconstructable DTO, which is §4's `confidence` reasoning applied
to a different field.

**Every other "``None`` when…" in these docstrings stays prose**, because it
describes *when* a value is absent rather than constraining which combinations
exist — `TurnOutcome.turn` is `None` on a recovered resume, `Evidence.content` is
`None` for a tombstone — and a validator cannot check a fact about how the value
was produced. The conformance suite is where those are exercised.

**Relocating an enum is not redefining it** (ADR-0084 §4). `Disposition` keeps its
five members and everything ADR-0037 ratified about them, including §8's refusal
of a `FAILED` member; `QuestionState`, `AnswerKind`, `LearnDecision` and
`QueueOutcome` keep theirs. What changes is which module declares them, and the
`StrEnum` base is unchanged so every existing value string is byte-identical on
the wire.

**Two constraints are deliberately *not* tightened**, and saying so is the point:

- **`confidence` is bounded `[0, 1]`, not `[0, 1)`.** `ObservedProposal`'s
  docstring states that a producer's confidence is "always strictly below 1.0 —
  the standing only the user's own word carries", and that is true and is
  ADR-0077 §5's rule *about the producer*. Encoding it as a validation constraint
  would convert a producer bug into an unreadable report: the entry that most
  needs to reach a human — a proposal something got wrong — would fail to
  construct, and the whole `ObservationReport` with it. The bound the *model*
  states is the bound the value is meaningful within; the strict one stays where
  it is enforced.
- **`route` stays `str | None`**, not `Identifier | None`. It is a model route
  label whose shape belongs to `models/`, and a `core` model is not the place to
  start constraining it.

#### 4c. Every string this surface carries is encodable, and that is a type

**ADR-0087 §9 hands this here by name**, and it is the one hole a ratified
encoding leaves in a surface that predates it: "§2 gives two values no encoding —
a lone surrogate `str` (§2b) and a non-finite `float` (§2c) — and §7 fixes that
the type is where each must be refused, before measurement… **the refusal belongs
on the type, and the promoted types are the surface ADR's.**"

**The float half is already closed, and checking rather than assuming is the
point.** Every `float` on this surface is a confidence — `Belief.confidence`,
`BeliefSummary.confidence`, `ObservedProposal.confidence` — and §4 gives all three
`ge=0.0, le=1.0`. NaN fails both comparisons and the infinities fail one, so the
bounds already refuse exactly the values ADR-0087 §2c has no form for. Nothing is
added here for floats; it is recorded so a reader does not go looking for it.

**The string half was open, and left open it is a divergence — in two
directions, not one.** A Python `str` may hold a lone surrogate, and such a
string has no UTF-8 encoding. Over the wire that is immediate: the in-process
engine has no reason to encode it and a client must, so one implementation
accepts the call and the other raises at the socket. **And the store refuses it
too** — the five databases are SQLite, whose driver encodes text as UTF-8 and
raises `UnicodeEncodeError` at the `INSERT` (verified against the tree). So the
constraint is not the wire's; it is a property of text that can be written down
at all, and the wire and the store are two places that need it.

**That is why the type is named for the property rather than for the
transport.** Naming it after the frame would name it for one of the two things it
protects — and the store half is the fact §4c leans on below to argue that
closing this was a fix rather than a decision.

> **Every string the promoted surface can carry is `EncodableText`** — the
> `core` alias at `core/types.py:343`, a `str` that refuses a value with no UTF-8
> encoding. That is every `str` and `str | None` field of a promoted type, every
> `str` argument (`utterance`), the `message` and any string inside `details` of
> an error payload (§10a), and every `Identifier`, which layers on it.

**This ADR adopts an existing `core` alias rather than inventing one**, which is
a stronger position than the one it drafted from. `EncodableText` is in the tree,
`Identifier`, `VisibleIdentifier` and `Sha256Hex` are layered on it, and
`tests/core/test_text_encodability_coverage.py` **fails the gate on a bare `str`
field anywhere in `core/types.py`**. So the promoted types inherit a mechanical
guard: the property §4c states is enforced by a test rather than by a reviewer
noticing, from the moment the triad puts these models in that file.

**This is emphatically not a size rule, and putting it in §8 would have hidden
it.** A payload can be far inside §8c's limit and still have no canonical
encoding at all — a lone surrogate is one character. So no size test, however
carefully written, would catch it, and an implementation is free to measure
however it likes precisely because validity is settled before measurement begins.
That is why ADR-0087 §7 puts the refusal on the type and why this section sits in
§4 rather than §8.

**It validates by running the encoder, not by enumerating what can fail**, which
is `FrozenJson`'s method and the reason ADR-0087 §9 points at it: the surrogate
and big-integer cases are exactly the ones an enumeration missed (#121, #127). A
rule stated over "every string" rather than over a list of fields is the same
discipline one level up — §8d declines to bound the handshake member by member and
§10a declines to name each error's `details` — and a field list here would rot the
first time a promoted type gains a `str`.

**The refusal is `ValueError`, at construction or before any I/O**, so it needs no
new error type and no new declaration: `UnicodeEncodeError` **is** a `ValueError`,
and §3c and §9 already declare `ValueError` on every method that takes text. What
§4c adds is that both implementations raise it for the same inputs at the same
point, rather than one of them discovering it at the socket.

**What this covers, and the gap it used to leave.** `EncodableText` reaches the
**promoted types' own fields** and the surface's **direct arguments**. When this
section was drafted it did **not** reach the strings inside the pre-existing
`core` types §5's walk terminates at, so `learn(FeedbackEvent(content="\ud800"))`
constructed. That was **#565**, and **#566 closed it**: `EncodableText` is now
applied across `core/types.py` — `FeedbackEvent.content`, `.subject` and
`.evidence`, `Goal.statement`, `MemoryBase.id`, `Provenance.evidence` and the
rest — with a coverage test that fails the gate on any bare `str` field in that
module. The gap this section named is closed in the tree, not merely tracked.

**The scope was stated as a rule and not a list, and that is why it closed
cleanly:**

> **Every string-bearing field reachable from the `core` types §5's walk
> terminates at** — at any depth, through nested models and through collections
> of them. Not a named set of fields.

**A field table was written here and is deliberately gone**, because it was
falsified in a single review round. It named `FeedbackEvent`, `Goal`,
`ActionPlan`, `MemoryRecord` and `ExecutionState`, and missed **`MemoryBase.id`**
— a plain `str`, not an `Identifier` — and **`Provenance.evidence`**, both
reachable through `MemoryRecord` and both able to carry a surrogate into a
`TurnResult` a canonical fake returns. That is §4c's own argument landing on
§4c: a rule over "every string" survives, and a list of fields rots. **The
failure is left on the record rather than quietly replaced**, because the next
reader's instinct is to write the list again — and because #566 closed the gap by
covering the module mechanically rather than by working down a list, which is the
same lesson at implementation scale.

**Two observations do survive as *evidence*, not as scope.** `CurrentContext`
carries no string at all — only `now`, `time_of_day` and two booleans — so a
reader assuming every leaf needs work is wrong. And the JSON-shaped fields need
none for a better reason than absence: `PlanStep.parameters`,
`StepExecution.output` and `Confirmation.parameters` are
`FrozenJsonMapping`/`FrozenJsonValue`, and `FrozenJson` **already** catches a
surrogate by running the real encoder at validation — the precedent ADR-0087 §9
points at and the method §4c adopts. The gap is in fields left as bare `str`, not
in ones that were given a validator.

**The boundary is where it is for a reason, not for want of noticing.** ADR-0087
§9 scoped its handover in as many words — "the refusal belongs on the type, and
**the promoted types** are the surface ADR's" — and the leaves are not promoted.
They predate this ADR and are consumed by `memory`, `planning`, `tools` and
`permissions`, none of which is on a wire; re-annotating them changes the shared
record graph ADR-0068 froze, with a blast radius outside any contract ADR's fence.
Absorbing that here is the mistake ADR-0087 exists as evidence against — a
representation concern reviewed by people reading for method shape.

**And #565 was a *fix*, not a decision this ADR was ducking** — which is what
made leaving it to its own change cost the corpus nothing, and is borne out by
#566 having simply made it:

- **No ADR ever ratified that those fields accept unencodable text.** There is no
  clause to supersede and no reader acting on one; the plain `str` is an absence,
  not a decision.
- **ADR-0087 §9 is a deferring clause acquiring an answer**, which is ADR-0083
  §15's stacked-addition carve-out on its own stated test: its sentence stays true
  and now has an answer. So #565 owed no supersession either, and #566 wrote
  none.
- **Nothing durable can already hold such a value, and that is the load-bearing
  reason rather than a reassurance.** The five stores are SQLite, whose driver
  encodes text as UTF-8, so inserting a lone surrogate raises
  `UnicodeEncodeError` at the `INSERT` — checked against the tree, not assumed,
  because the whole claim turns on it — and it is also why the alias is named
  `EncodableText` rather than for the wire (§4c). It follows that #565 could
  invalidate no stored record and needed no migration: the gap was reachable only
  **in memory**, between constructing a value and a socket that does not exist
  yet. A fix with no durable footprint is one a later change can simply make,
  which is exactly what #566 did.

### 5. The complete transitive closure, and the boundary it stops at

This is the enumeration ADR-0084 §4 assigns to this ADR. It is written as a
reachability walk from the fifteen signatures, because that is the only form in
which "complete" is checkable.

**Roots — what the fifteen methods name.** Arguments: `str`, `timedelta`, `bool`,
`int`, `Identifier`, `FeedbackEvent`, `Sequence[BeliefBand]`,
`Sequence[MemoryKind]`, `ContinuationToken`. Returns: `TurnOutcome`,
`LearnOutcome`, `ObservationReport`, `BeliefSummary`, `Belief`, `Question`,
`AnswerOutcome`, `ConversationSummary`, `ConversationDigest`, `Confirmation`,
`bool`.

**The walk**, with each edge being a field:

```text
TurnOutcome
├── turn        → TurnResult ─┬─ goal      → Goal            [core]
│                            ├─ context   → CurrentContext  [core]
│                            ├─ memories  → MemoryRecord    [core]
│                            └─ plan      → ActionPlan      [core]
└── step        → StepOutcome ┬─ disposition  → Disposition        (runner.py)
                              ├─ state        → ExecutionState     [core]
                              └─ confirmation → Confirmation ─── token → ContinuationToken
                                                └─ parameters → FrozenJsonMapping [core]

LearnOutcome → IngestSummary ┬─ decision → LearnDecision
                             └─ queued   → QueuedQuestion ┬─ outcome        → QueueOutcome
                                                          └─ question_state → QuestionState (questions.py)

ObservationReport → ObservedProposal ┬─ kind      → MemoryKind    [core]
                                     ├─ step      → MemorySource  [core]
                                     ├─ decision  → LearnDecision
                                     └─ evidence  → Evidence

BeliefSummary ┬─ band → BeliefBand [core]      (the `beliefs()` page — §4a)
              └─ kind → MemoryKind [core]      (no citation field: the walk ends)

Belief ┬─ band     → BeliefBand [core]         (the `belief()` view — §4a)
       ├─ kind     → MemoryKind [core]
       └─ evidence → Evidence

Question ┬─ state     → QuestionState  (questions.py)
         ├─ kind      → MemoryKind     [core]
         ├─ band      → BeliefBand     [core]
         ├─ retires   → Retirement     (questions.py)
         └─ successor → SuccessorLink ── state → QuestionState (questions.py)

AnswerOutcome ┬─ kind      → AnswerKind    (questions.py)
              └─ successor → SuccessorLink (questions.py)

ConversationSummary  → (scalars only)
ConversationDigest   → (scalars only)
```

**The twenty-four that promote**, gathered from that walk: `ContinuationToken`,
`Confirmation`, `StepOutcome`, `TurnOutcome`, `LearnDecision`, `QueueOutcome`,
`QueuedQuestion`, `IngestSummary`, `LearnOutcome`, `Evidence`, `BeliefSummary`,
`Belief`, `ConversationSummary` (thirteen from `engine.py`, of which
`BeliefSummary` is new — §4a); `QuestionState`, `Retirement`,
`SuccessorLink`, `Question`, `AnswerKind`, `AnswerOutcome` (six from
`questions.py`); `Disposition` (from `runner.py`); `TurnResult` (from `loop.py`);
`ObservedProposal`, `ObservationReport` (from `observation.py`);
`ConversationDigest` (from `conversations.py`).

**Where the walk stops, and why that is a closed boundary and not a hopeful
one.** Every leaf above marked `[core]` already lives in `core/types.py` and is
already a frozen pydantic model or `StrEnum` under ADR-0068 §1: `Goal`,
`CurrentContext`, `ActionPlan`, `MemoryRecord` (and the four record types its
discriminated union names), `ExecutionState` (and `StepExecution`, `StepStatus`,
`StepFailure`, `ToolFailureKind`, `SkipReason` beneath it), `FrozenJsonMapping`,
`FrozenJsonValue`, `BeliefBand`, `MemoryKind`, `MemorySource`, `Identifier`,
`UtcInstant`, and — as an argument — `FeedbackEvent`. The walk terminates because
`core` is already closed under its own field graph, which is exactly what
ADR-0068 established.

**Five types ADR-0084 §4 did not name are in this closure**, and each was found
by walking rather than by reading the ADR: `Retirement` (via `Question.retires`),
`AnswerKind` (via `AnswerOutcome.kind`), `TurnResult` (via `TurnOutcome.turn`),
`ObservedProposal` (via `ObservationReport.proposals`) and `ConversationDigest`
(the `conversation` return). ADR-0084 §4 was explicit that it was naming
examples — "three of those live in `orchestration` today" — and equally explicit
that the complete graph is this ADR's, so this is the deferral being discharged
rather than a correction.

**And the walk is over *declared field types*, not over runtime values.** That
distinction is what makes it terminate: `MemoryRecord` is a four-arm discriminated
union, and enumerating its arms would grow the table without changing the answer,
because all four are already `core` models frozen by ADR-0068 §1. The rule the
triad lane should apply when it re-derives this is: follow a field's annotation to
its declared type, stop at anything already in `core`, and never follow a method.

### 6. What does not promote, and the rule that keeps `core` clean

Three categories stay in `orchestration`, and the first is the one that would
have broken the build.

**(a) Projection helpers stay behind, because one of them names a type the
closure does not reach.** All seven classmethods and two module functions that
construct these DTOs today, private ones included, enumerated so the triad lane
does not have to find them:

| Helper | Today | Names |
| --- | --- | --- |
| `LearnOutcome.from_results` | `engine.py:446` | `orchestration.writes.WriteOutcome` |
| `QueuedQuestion.from_admission` | `engine.py:354` | `core.types.DeferralAdmission` |
| `Belief.from_record` | `engine.py:707` | `core.types.MemoryRecord` |
| `ConversationSummary.from_record` | `engine.py:768` | `core.types.Conversation` |
| `ObservedProposal.ruled` | `observation.py:231` | `core.types.MemoryUpdateProposal`, `core.types.MemoryIngestResult` |
| `ObservedProposal.unsupported` | `observation.py:247` | `core.types.MemoryUpdateProposal` |
| `ObservedProposal._project` | `observation.py:266` | `core.types.MemoryUpdateProposal` |
| `learn_decision` | `engine.py:487` | `core.types.MemoryDecisionKind` |
| `question_state` | `questions.py:126` | `core.types.DeferralState` |

`LearnOutcome.from_results` takes `WriteOutcome`, which lives in
`orchestration/writes.py`. Carried onto the promoted model it would put
`core → orchestration` in the import graph — the precise `lint-imports` failure
ADR-0084 §4 promotes the closure to avoid, reintroduced by a classmethod nobody
counted as a field.

> **The promoted models carry their fields, not their constructors.** Every
> projection helper becomes a module-level function in the `orchestration` module
> that owns the projection, and none of them is part of the Protocol.

`_project` is private and is `ruled`'s and `unsupported`'s shared implementation;
it moves with them, so the two keep an implementation rather than losing one. It
is listed because a rule stated over "every projection helper" is only checkable
against a complete inventory, and a private member is exactly the kind that gets
left behind.

The other eight would have been safe to carry — `MemoryUpdateProposal`,
`MemoryIngestResult`, `MemoryRecord`, `Conversation`, `DeferralAdmission`,
`MemoryDecisionKind` and `DeferralState` are all `core.types` — and they move
anyway, for two reasons: a rule with exceptions is a rule the triad lane has to re-derive, and a
projection from a `core` record into a `core` DTO belongs to the layer that
*decides* the projection. `Belief.from_record` is where `band_of` is applied
(ADR-0073 §7); putting that in `core/types.py` would make `core` the home of a
policy decision the engine owns.

**The closure walk does not reach them**, which is what makes this consistent
rather than convenient: the walk follows declared field types and never follows a
method (§5).

**(b) Derived predicates stay as plain properties on the promoted models, and are
not `computed_field`.** **Twelve exist**, and the list is normative — a triad
implementation that carried a subset would leave the CLI reading an attribute
that is not there:

| Model | Properties |
| --- | --- |
| `IngestSummary` | `stored` |
| `LearnOutcome` | `stored` |
| `Evidence` | `lost` |
| `Belief` | `evidence_count`, `lost_evidence`, `unsupported` |
| `BeliefSummary` | `unsupported` |
| `ObservedProposal` | `stored`, `evidence_count`, `inspectable` |
| `ObservationReport` | `stored`, `discarded` |

Every one is a pure function of fields the model already carries — verified
individually, and it is what makes the non-serialisation rule below safe rather
than merely tidy.

**`BeliefSummary` is where the field/property line is drawn deliberately rather
than by habit** (§4a). `evidence_count` and `lost_evidence` are *fields* there
because the type carries no evidence to derive them from, and `unsupported` stays
a property because it is a pure function of those two. On `Belief` all three stay
properties. The rule is the same one in both places — derive what the fields
already determine, and store only what nothing else can produce.

> They stay as `@property`, so they are **not serialised**. A client
> reconstructing a promoted model from JSON recomputes them from the same fields
> the engine did, and gets the same answer by construction.

`computed_field` would put them on the wire, which is two sources of truth for a
fact the fields already carry, and a client that trusted the transmitted copy
over its own recomputation would be trusting a value nothing validates. This is
ADR-0084 §4's "a value worth returning is worth returning as itself", applied to
a value that is worth *not* returning.

**(c) Stage and private types stay where they are.** `StepDisposition`
(`runner.py:233`), `_Parked` (`engine.py:828`), `CaptureReport` and
`AssembledHistory` (`conversations.py`), `DataExport` (`conversations.py:170`)
and every stage class are outside the closure: no public method returns one and
no promoted field reaches one. `DataExport` is worth naming explicitly because it
looks like a surface type and is not — `ConversationLifecycle.export` exists,
`Engine` exposes no `export`, and no CLI command reaches it. Putting a data-export
method on the Protocol would be adding surface rather than pinning it, and
ADR-0007 §3's export therefore stays exactly where it is until something needs it
through the door.

### 7. `StepOutcome.step_id`, and the disposition rule ADR-0084 §8 ratified

ADR-0084 §8 ratified that the field exists and what the rule is, and left "its
spelling and type" here.

> **`StepOutcome` gains `step_id: Identifier`, required and never `None`.** It
> names the plan step this pass drove, and it is the key that addresses
> `state.steps`, whose elements are `StepExecution` with `step_id: Identifier`
> (`core/types.py:2250`).

**It is required, and that is checkable rather than aspirational.** A
`StepOutcome` is constructed at exactly two sites, and both hold the id already:
`_converse` has `first.id` where `first = turn.plan.steps[0]` (`engine.py:2066`,
`:2080`), and `_resume` has `parked.step_id` (`engine.py:2153`, `:2160`). There is
no path on which a `StepOutcome` exists and the step it is about does not — a turn
whose plan had no step returns `TurnOutcome(step=None)` and constructs no
`StepOutcome` at all (`engine.py:2059-2065`). So an optional field would be an
optionality nothing in the tree can produce, and every client would carry a `None`
branch it can never reach.

**`Identifier` rather than a bare `str`** because it is the same key
`StepExecution.step_id` is, and a client that looks it up must be comparing values
of the same type. This is the field that makes ADR-0084 §8's rule operable:

> **The disposition is the gate's verdict; the named step's `status` and
> `failure` are the outcome.** A client that renders success from the disposition
> alone is wrong.

That rule is a **contract clause on the Protocol**, stated in
`AssistantEngine.converse`'s and `resume`'s docstrings and in `StepOutcome`'s, not
merely prose in this ADR — because #531's defect was an adapter reading
`disposition` and discarding `state` (`cli.py:1289`), and every future spoke will
have the same two fields in front of it. Naming the step is what turns "read
`state` too" from advice into an addressable operation:
`next(s for s in outcome.state.steps if s.step_id == outcome.step_id)`.

**`tool_id` is not an alternative and stays what it is.** ADR-0084 §8 already ruled
that two steps may bind the same tool, so `tool_id` cannot identify a step; it
stays `Identifier | None`, meaning "the tool selected, or none was".

**The adapter half stays #531's**, unchanged: rendering a failed step as a failure
and setting a non-zero exit code is the client lane's, under ADR-0042 §6.

### 8. The size limit is a contract clause, and here is the number both sides compute

ADR-0084 §4 ruled that the limit "is part of the promoted Protocol's declared
contract, not a property of the transport, and *every* implementation enforces
it", so that a client is never silently less capable than the engine it stands in
for — in either direction, an oversized `Belief.evidence` coming back or an
oversized utterance going in. It left the number to this ADR, and §3 of that ADR
separately assigns "the envelope's member names" and `hub_max_frame_bytes`'s lower
bound here too. The three are one problem: a limit on a *value* and a limit on a
*frame* that are not related by a stated constant are two limits, and the whole
point of §4 was to have one.

#### 8a. The envelope, so the reserve can be computed

The envelope is a JSON object (ADR-0084 §3) with these members, and no others:

| Member | On | Value |
| --- | --- | --- |
| `kind` | every frame | one of `connect`, `connect_ack`, `request`, `result`, `error` |
| `id` | every frame | the correlation id |
| `method` | `request` only | the `AssistantEngine` method name |
| `payload` | every frame | the request arguments, the result value, the handshake body, or the error body |

**The correlation id is a UUID string and is at most 36 bytes.** Bounding it is
what makes the reserve below a constant rather than an aspiration; a frame whose
`id` is longer is a protocol violation and takes ADR-0084 §3's undecodable-frame
close, because the length is part of what makes the frame decodable within
budget.

#### 8b. The envelope reserve is 512 bytes

Worst case, encoded: `{"kind":"","id":"","method":"","payload":}` is 42 bytes of
punctuation and member names; the longest `kind` is `connect_ack` at 11; the
correlation id is at most 36; the longest method name is `interrupted_questions`
at 21, tied with `pending_confirmations`. That is **110 bytes**, exclusive of the
payload value itself, which is what the limit in §8c is measured on.

> **The envelope reserve is fixed at 512 bytes.**

The slack is deliberate and is the reason a computed figure is not used: a later
protocol version may add a member to the envelope (ADR-0084 §3 permits it), and a
reserve derived from today's exact worst case would silently become wrong the day
it does, converting a schema addition into an off-by-a-few-bytes frame overflow at
the ceiling. 512 leaves 402 bytes of headroom for such additions, which is
several of them, without anyone having to notice.

#### 8c. The declared limit is on the whole payload, not on one value

> **The contract limit is `hub_max_frame_bytes - 512`, applied to the whole
> serialised **payload**, measured as the byte length of that payload's canonical
> UTF-8 JSON encoding** — the codec ADR-0084 §3 already fixes. There are **three**
> payload classes and the limit covers all of them: for a call, the request's
> argument object as §10 encodes it; for a return, the result value as §10 encodes
> it; and for a failure, the error payload as §10a encodes it. Every
> implementation enforces it, on arguments before dispatch, on results before
> return, and on errors before they are sent.

**The error payload is the third class and it is the one with no room to fail**,
which is why §10a gives it a reduction rule of its own rather than the refusal the
other two get. An oversized argument or result raises `OversizedValueError` — but
an oversized *error* has nowhere to raise to, because the thing that would carry
the refusal is the frame that does not fit. §10a closes that.

**Bounding the payload rather than each value is the correction that makes the
arithmetic true, and it is worth stating why the per-value form fails.** A
request payload is a JSON object carrying *every* argument: bound `utterance`
alone at `hub_max_frame_bytes - 512` and a `converse` call at exactly that bound
still adds `{"utterance":…,"timeout":"PT30S"}`'s member names, punctuation and the
timeout itself — so a payload every one of whose arguments the contract admits
overflows the frame anyway. The client would then have to refuse an input the
contract admitted, or send a frame the server refuses on its prefix: precisely
the divergence ADR-0084 §4 moved the limit into the contract to prevent, one
level up from where it was being watched. A whole-payload bound has no such gap,
because what it measures is the thing the length prefix counts.

**The *encoding* those bytes are counted in is ratified by ADR-0087, not by this
ADR and not by an implementing lane.** A limit is only one limit if both
implementations measure the same byte string, so something must fix the encoding
exactly — `/` versus `\/`, `0.1` versus `1e-1`, `"…12:00:00Z"` versus
`"…12:00:00+00:00"` and `"PT0.5S"` versus `"PT0.500000S"` are all real
disagreements at the boundary. What this ADR fixes is the **limit**; what
ADR-0087 fixes is the **encoding** the limit is measured on.

> **The measurement is taken on the payload's canonical wire encoding, which
> ADR-0087 ratifies with normative test vectors.** §11a says what it settles.

ADR-0087 §6 states the same sentence from its own side — "the one thing the
surface ADR needs from this one is that the limit it declares is measured on the
canonical encoding ratified here" — and rules that saying it "decides nothing
about sequence, so stating it costs that ADR no amendment record". §12 relies on
that reading rather than on mine.

**The duration form moves bytes, and every figure in §8 was re-checked against
it.** ADR-0087 §2e refuses ISO-8601's nominal `Y` and writes whole days instead,
so a canonical duration is **up to three bytes wider** than the library's form —
proved there, attained at `timedelta(days=1095)` (`"P3Y"` → `"P1095D"`), and
taken here as given. Checked against each figure this section derives, and
**none moves**:

| Figure | Carries a duration? | Effect |
| --- | --- | --- |
| §8b's 110-byte envelope worst case | no — `kind`, `id`, `method`, punctuation | none |
| §8d's connect payloads and the 1024 floor | no — a version, a build identifier, a flag, a frame size | none |
| §8f's belief-page worst case | no — `BeliefSummary` and `Belief` carry instants, not durations | none |

**The one duration on this surface is `timeout`**, a request argument on
`converse` and `resume` (§3). That is checkable rather than asserted: `core` has
four `timedelta` fields — `MemoryDecision.ttl`, `DeferredProposal.retention`, and
`ToolDefinition`'s `idempotency_window` and `latency` — and §5's walk reaches
none of them, because the promoted DTOs flatten what they project from rather
than carrying it. No **result** payload can hold a duration at all. And no figure
here is derived from an estimated request width — requests are bounded by §8c's
limit itself. So the +3 is
invisible to §8's arithmetic. It is recorded because ADR-0087 §2e says a reserve
or floor derived from a worst-case payload width "must be derived from §2's
forms", and the honest way to discharge that is to show the check rather than to
assert the conclusion.

**Why it is a separate ADR rather than a section here**, in the order the reasons
bind:

- **The bytes must be ratified, and an earlier draft of this section was wrong
  that they need not be.** That draft argued the conformance suite could test the
  limit's *behaviour* and leave its boundary open until the transport landed. The
  argument does not survive the triad's own **canonical fake**
  (`CONTRIBUTING.md` → "Adding a Protocol"): change 3 ships a second
  implementation and a shared suite both it and `Engine` must pass, so two
  implementations can disagree about which calls are refused before the wire
  package exists at all. Refusal is contract-visible, and a suite can only test
  what is specified. **Recording the retraction rather than the conclusion alone
  is deliberate** — the same mistake is available to anyone who reads §8d's and
  §10a's preference for structure over enumeration and over-applies it.
- **But they must not be ratified *here*.** Pinning a byte grammar in a
  nineteen-clause contract ADR is the unspiked seam #281 and `CONTRIBUTING.md`'s
  spike-first guidance warn about, and it was attempted: four review rounds each
  found one more corner it had not covered, with a fifth (`"P2DT3S"` versus
  `"PT172803S"`) still open when it was withdrawn. An enumeration of a space
  nobody can prove they have covered is a list of the cases someone thought of.
  ADR-0087 carries **normative test vectors**, which is the form that makes an
  encoding checkable rather than argued.
- **The two obligations are different in kind, and separating them is what lets
  each be reviewed as itself.** This ADR is a *surface* contract — signatures,
  types, failures. ADR-0087 is a *representation* contract. Merging them would put
  a byte grammar in front of reviewers reading for method shape, which is how the
  corners went unnoticed for four rounds.

**Where ADR-0087 sits in the work is ADR-0087's to state, not this ADR's**, and
the restraint is deliberate rather than coy. A position in a sequence is a fact
about the ADR that occupies it; asserting it here would be this document deciding
something about another one, and ADR-0084 §5's own enumeration is what it would
be deciding against. §12 records why that leaves no amendment owed here.

**Citing another ADR for a decision it owns is ordinary, and the precedent is
this ADR itself.** ADR-0084 §5 named "the surface ADR (#281's scope)" before that
ADR existed, and §4 and §11 both defer to it by name. ADR-0087 is `Accepted` and
in the corpus, so the reference here resolves to ratified text rather than to an
expectation.

**A `core`-owned codec is the obvious alternative and ADR-0084 §6 forecloses it.**
That ADR places "the envelope, the framing, the codec, the error mapping, and the
client" in the `wire` package, and golden rule 2 keeps `core` free of them. So the
canonical encoding cannot be ratified here as a `core` API without contradicting a
ratified placement; what this ADR can do — and does — is fix that there is exactly
one, that both measurement and transmission use it, and that the limit is measured
on it.

**What ADR-0087 can do that this ADR cannot: test it.** A byte encoding is
exactly the kind of thing a round-trip vector pins in a line — encode, measure,
compare — where a prose grammar is checked only by whoever reads it next. That is
the whole reason the material moved rather than being cut.

#### 8d. `hub_max_frame_bytes` has a floor of 1024 bytes

ADR-0084 §3 requires the setting to be "large enough for the mandatory handshake
and the smallest valid envelope" and says "the exact floor depends on the envelope
schema and is therefore fixed by the surface ADR". With §8a's schema:

> **`hub_max_frame_bytes` is refused at load time below 1024 bytes**, alongside
> its existing `gt=0` and its upper bound at the 4-byte prefix's ceiling.

**A floor is a proof, and it needs the handshake to be bounded in *both*
directions — as a whole, not member by member.** The mandatory handshake is two
frames, not one (ADR-0084 §2): the client's connect request carries a protocol
version, a free-form client identifier and a credential member; the server's
reply carries a version, a build identifier, a readiness flag and the effective
frame size. Nothing bounds the encoded width of any of them — an identifier is a
free-form string, and a "single integer" version has no stated range, so its
decimal form is as wide as the value.

**The request half matters more than it looks, because it is sent blind.** The
client has not yet been told the hub's `hub_max_frame_bytes` — that is what the
reply carries — so a client cannot enforce the server's limit on the one frame
it sends before learning it. A floor that fits only the reply therefore yields a
hub that accepts `hub_max_frame_bytes` at its minimum, passes every ADR-0083 §3
startup step, and then refuses the connect frame of every client, including the
CLI: the exact failure this floor exists to prevent, produced by the check meant
to prevent it.

**Bounding the members one at a time is the tempting fix and it is the one that
keeps failing.** Two separate members turned out to be unbounded on inspection,
which is evidence that inspection is not a reliable way to enumerate them — and a
later protocol version may add a fifth (ADR-0084 §3 permits it) that no sentence
here would reach. So the bound is stated over the payload, where it closes:

> **Each connect-exchange payload — the request and the reply alike — is at most
> 256 bytes encoded.** A frame that would exceed it is a configuration fault on
> the side that would send it rather than a frame to send. The build identifier
> and the client identifier are each at most 64 bytes; every other member's
> encoded width is bounded by the payload bound, whatever members a later
> protocol version adds.

That is fail-closed in the direction that matters: a member nobody thought about
cannot silently widen either handshake frame past the floor, because the
aggregate is what is checked, on both sides. Today's reply — a version, a 64-byte
build identifier, a boolean and a frame size that the 4-byte prefix caps at ten
digits — encodes to roughly 135 bytes, and the request is smaller; 256 is
generous rather than tight for either.

With that, 512 (the envelope reserve) plus 256 (either connect payload) is 768,
and **1024** leaves room for both handshake frames and for a small request
besides. A value
below the floor yields a hub that passes every ADR-0083 §3 startup step and then
refuses every client including the CLI — indistinguishable from a hub that is
down, which is ADR-0084's ruling 4 failure produced by a config typo, and load
time is where it should surface.

#### 8e. #473 is not designed around

`Belief.evidence` is an unbounded tuple that grows monotonically under
`REINFORCE` (#473), and this ADR does not pretend otherwise: `evidence` carries no
`max_length`, and the contract limit above is the only thing standing between a
grown tuple and an unsendable result. ADR-0084 §11 makes #473 a prerequisite of
the *client* lane and not of this one, and §4 records honestly that until its
bound lands the bad state is unreachable rather than provably unreachable. The
same holds here. What this ADR adds is that the failure, when it comes, is
`OversizedValueError` naming `Belief.evidence` — a sentence a user can read and
act on — rather than a frame that will not send.

#### 8f. The worst case is the belief page, and §4a is what bounds it

**A limit is only useful if someone has asked which payload is largest, and §8
did not until #552 raised it.** The answer is not a turn or an observation — it is
`beliefs()`, because it is the one response whose size is a *product* of three
factors rather than a sum.

`Evidence.content` is a cited episode's own text and no contract bounds an
episode's content. So the evidence payload is `beliefs × citations × content`, and
against §3's 16 MiB default the three shapes differ by two orders of magnitude:

| Response | Citation contents in one frame | Budget per citation before refusal |
| --- | --- | --- |
| `belief()` — one belief | at most its own citation count | wide |
| `beliefs()` **as the tree writes it** — 50 beliefs, each fully resolved | 50 × the per-belief count | narrow, and it *shrinks as the page fills* |
| `beliefs()` **under §4a** — `BeliefSummary` | **zero** | not applicable |

**§4a removes the product, not the number.** The contract limit is unchanged —
`hub_max_frame_bytes - 512`, §8c — and no figure in §8 moves. What changes is that
the listing's evidence payload is not merely small but **structurally absent**: a
`BeliefSummary` has no field a citation's content could occupy, so the page-size
factor disappears from the arithmetic rather than being argued down. A fifty-row
page is bounded by fifty beliefs' own `content` plus a handful of scalars each.

**What is left is exactly the term #473 is about**, and this ADR does not close it
and does not pretend to. `belief()` returns one `Belief` whose `evidence` tuple is
unbounded in the tree, so the single-belief view's payload is bounded only once a
citation *count* bound exists. ADR-0084 §11 already names #473 a prerequisite of
the **client** lane rather than of this one, and that stays exactly true: §4a
narrows the residual from a page-multiplied product to one belief's citations, and
closing it is #473's.

**This ADR does not lean on ADR-0086.** That ADR is `Proposed` on another lane and
proposes the citation bound; a contract ADR that derived its own soundness from an
unratified one would be asserting a guarantee the corpus does not yet hold. The
relationship is the other direction and is worth stating plainly: ADR-0086 §7
works the same arithmetic, finds the listing's product is "not provably safe" for
any bound *it* could pick because the unbounded factor is not one it owns, and
hands the shape here. §4a is that shape. Neither ADR depends on the other; each
removes one factor of the same product.

### 9. The declared failures, and the two error types this surface needs

A Protocol whose methods raise unnamed exceptions is not a contract a conformance
suite can hold anyone to, and ADR-0084 §3 requires a wire error to carry "a typed
code and a message". So the failures are declared, and two new types are named —
both of them the *spelling* of a refusal ADR-0084 already ratified, not a new
decision.

**`AssistantError` gains one field, `details_elided: bool = False`** (§10a) —
the only change this ADR makes to an *existing* error type. It exists so a client
whose reconstruction lost an exception's structured state can say so, instead of
presenting an empty list as an empty answer. It is `False` everywhere else.

**Both new types live in `core/errors.py`**, beside the hierarchy they extend —
the same file every other `AssistantError` subtype is declared in, and the one a
Protocol in `core/protocols.py` can name without reaching outside `core`.

**`UnknownContinuationError(PlanningError)`.** ADR-0084 §7 ratified that
presenting a token the server cannot resolve "yields one specific, typed refusal —
an unknown-continuation error — and never a generic failure, and never a denial",
covering both a hub restart and eviction under
`max_outstanding_confirmations`. `Engine._resume` raises a bare `PlanningError`
today (`engine.py:2146`), which is indistinguishable from four other planning
faults. Subclassing `PlanningError` rather than `AssistantError` directly is
deliberate: every existing `Raises: PlanningError` contract on this surface stays
true, and a caller that already handles it keeps working, while a caller that
wants ADR-0084 §7's specific remedy — call `pending_confirmations()` and re-mint —
can now catch the thing that has that remedy.

**`OversizedValueError(AssistantError)`.** §8's typed refusal. It carries the
limit, the payload's measured size, and the name of the largest contributing
member — because ADR-0084 §4 requires the limit and the field, and because "too
large" without a number is not actionable.

**"Largest" has to be a rule, not a judgement, and this is the one place §10a's
round-trip makes that bite.** `details` is reconstructed on the far side and must
match, so two implementations that named different members for the same payload
would break the reconstruction contract this section just established. Left as
prose, "largest contributing field" does not determine an answer: it says nothing
about nesting, and nothing about ties. So:

> **`field` is `str | None`. It names the top-level member of the payload whose
> own canonical encoding (ADR-0087 §2) is longest, ties broken by the member
> name's bytes in ascending order, and is `None` where the payload has no named
> members** — a `beliefs` result is a bare array, a `forget` result a bare
> `true`. The optional type is not defensive: the `None` case is reachable, since
> an oversized `beliefs` page is exactly a bare array with no member to name.

**Top-level only, and no path syntax**, which is the restraint that keeps this
from becoming a second specification. A path language would need its own grammar,
its own escaping for member names containing separators, and its own review — for
a value whose whole job is to make an error message actionable. Naming
`utterance` or `evidence` is what a caller needs to act; naming
`proposals[3].evidence[7].content` is not enough better to be worth a grammar.

**ADR-0084 §4's "the field that exceeded it" is honoured rather than reinterpreted
loosely.** Under §8c's payload-level bound no single field *exceeds* the limit —
the payload does — so the faithful reading is the field that contributed most to
exceeding it, which is what this rule names. Where the payload is a bare value
there is no field to name and `null` says so, rather than inventing one.

**`OversizedValueError` is declared by *every* method, and is therefore stated
once here rather than repeated in fifteen rows.** §8c's bound applies to every
request payload and every result payload, and no method on this surface is
provably inside it: `Identifier` carries no maximum length, so even
`forget(record_id=…)` can be handed an oversized argument, and every enumerating
method's result grows with `limit`. A table that listed it per method would
invite exactly the omission that a universal rule cannot have — and the rule is
what the conformance suite tests anyway.

**The per-method declared failures**, `OversizedValueError` assumed throughout:

| Method | Declares |
| --- | --- |
| `converse` | `ValueError`, `UnknownConversationError`, `PlanningError`, `ContextError`, `AuditError`, `ToolBindingError` |
| `resume` | `UnknownContinuationError`, `PermissionDeniedError`, `AuditError`, `ToolBindingError` |
| `learn` | `MemoryStoreError` |
| `observe` | `ValueError`, `UnknownConversationError`, `ConversationStoreError`, `MemoryStoreError`, `ModelError` |
| `beliefs`, `belief` | `ValueError`, `MemoryStoreError` |
| `forget` | `ValueError`, `MemoryStoreError` |
| `questions`, `interrupted_questions` | `ValueError`, `DeferralStoreError`, `MemoryStoreError` |
| `answer` | `ValueError`, `MemoryStoreError`, `UnresolvedEvidenceError`, `DeferralStoreError` |
| `forget_question` | `ValueError`, `DeferralStoreError` |
| `recent_conversations`, `conversation` | `ValueError`, `ConversationStoreError` |
| `forget_conversation` | `ValueError`, `ConversationStoreError`, `MemoryStoreError` |
| `pending_confirmations` | `PlanningError`, `AuditError` |

**`ValueError` is *not* universal, and the three exceptions are the check on that
table.** `resume`, `learn` and `pending_confirmations` take no bare identifier
and no page argument — `ContinuationToken` and `FeedbackEvent` are pydantic
models whose own validation fires at construction, before the call — so there is
nothing for them to refuse locally.

**`ValueError` is declared and is deliberately not an `AssistantError`.** It
covers a malformed page argument (`limit` or `offset` outside `[0, 2**63)`) and a
blank `Identifier` (§3c). ADR-0073 §2 already fixed that treatment — the store
"refuses rather than clamps" — and `Engine.beliefs`' docstring already tells an
adapter that lets a user supply either to refuse an out-of-range value "at its own
parse boundary rather than at this one". It stays a caller programming error
rather than a condition of the system.

What the promotion adds is a clause, for the same reason §3d and §8 need one:

> **An implementation refuses a malformed page argument or a blank identifier
> locally, before any I/O**, so both implementations refuse the same values
> without a round trip and neither is silently more permissive.

**Argument-encoding failures on the wire are not new contract surface.** ADR-0084
§3's undecodable-frame close, version mismatch, credential refusal and
second-concurrent-request close are all transport conditions, reported by the
client as a transport failure. They are not `AssistantEngine` failures and no
Protocol method declares them.

### 10. The per-method wire mapping

ADR-0084 §3 assigns "the per-method mapping of arguments and results onto these
forms" here. It follows mechanically from §3's own rules once the signatures are
fixed, so it is stated compactly rather than method by method:

- **A request payload** is a JSON object whose members are the call's arguments,
  named exactly as the Python parameters are. **An argument the caller did not
  pass is absent, not `null`** — so the receiver applies its own declared default
  (§3a) and the two implementations cannot disagree about what "not passed"
  means. That distinction is semantic and is fixed here; the bytes that express it
  are §8c's deferral. The method name is the envelope's `method` member (§8a), not
  a payload member.
- **Argument scalars** take **ADR-0087 §2's** form for their type — not the
  library's, which ADR-0087 partially supersedes ADR-0084 §3 on: `timeout` is an
  ISO-8601 duration under §2e (whole days, never a nominal `Y`), a `bool` is a
  JSON boolean, an `Identifier` is a string, and `bands`/`kinds` are JSON arrays
  of their enum values.
- **A result payload** takes the shape of the method's own declared return
  annotation, so it follows the signature rather than a second declaration:
  `null` where the method returns an optional (`belief`, `conversation`); a JSON
  array where it returns a tuple (`beliefs` — of `BeliefSummary`, §4a —
  `questions`, `interrupted_questions`, `recent_conversations`,
  `pending_confirmations`); and a JSON boolean for the three methods returning
  `bool` (`forget`, `forget_question`, `forget_conversation`, and no other).
  **A result carries every field of its type** — there is no "not passed" on a
  return, and a value's bytes must not depend on how the object was built.
- **Every promoted `StrEnum` serialises as its member value**, which is why §4
  keeps the `StrEnum` base: `Disposition.EXECUTED` is `"executed"` on the wire
  today and after the move, so the relocation changes no byte.
- **One canonical encoding serves both jobs.** The bytes a client measures
  against §8c's limit are exactly the bytes it writes, so measurement and
  transmission can never disagree. **Which bytes those are is ratified by
  ADR-0087** (§11a).

#### 10a. The error frame, so a declared failure survives the wire

**A typed failure that cannot be reconstructed on the far side is not a contract,
and §9 declares one that §10 above had no room for.** ADR-0084 §3 fixes that
errors are "a distinct message kind, carrying a typed code and a message, never a
result payload", and leaves the member names here. §9 then obliges
`OversizedValueError` to carry the limit, the measured size and the largest
contributing field — three values a client reconstructing from a code and a
message alone cannot repopulate. It would raise the right *type* with empty
fields, which is the in-process engine and the client disagreeing about a
contract-declared exception: §4's divergence, one layer over from where §8 closed
it.

**The error payload** is a JSON object with these members:

| Member | Presence | Value |
| --- | --- | --- |
| `code` | always | the exception type's own class name |
| `message` | always | the exception's human-readable message |
| `details` | always | an object whose members are the exception's public attributes **other than `details_elided`**, or `null` where the type carries none |
| `reduced` | always | `true` where the payload was reduced to fit (below), otherwise `false` |

**Every member is always present**, deliberately: a conditional member would be a
second thing two implementations could do differently, and `"details":null` costs
fifteen bytes to remove the question. A client reads `details` as null-or-object and `reduced` as a
plain boolean, with no absence to interpret.

**The code is the class name, which makes the mapping total by construction
rather than by a registry someone maintains.** A hand-kept table of tokens is a
second vocabulary to drift against the first — the objection §4 raises to mapping
`Disposition` to a bare string, and it applies with more force to a mapping used
only on failure paths, which are the least exercised. Class names are already
contract surface: renaming one in `core/errors.py` is already a change that costs
an ADR, so the wire inherits that stability for free.

**`details` is the exception's own public attributes, which makes its schema
mechanical for the same reason the code is the class name.** Naming members
per-error in this ADR would be a table to keep in step with `core/errors.py` by
hand, and it would go stale the first time a structured error is added. So:

> An `AssistantError` subtype that carries structured state declares it as
> **public attributes whose names match its constructor's keyword parameters**,
> and `details` is exactly those attributes serialised under ADR-0087 §2. A
> client reconstructs by calling the named type with the message positionally and
> the `details` members as keyword arguments.
>
> **`details_elided` is excluded from `details`, because it is transport metadata
> rather than exception state.** It says something about *this delivery*, not
> about the failure; it is carried by the frame's own `reduced` member and set on
> the reconstructed exception by the client. Without the exclusion every
> exception would carry structured state, `details: null` could never be sent,
> and no subtype's constructor would accept the member back.

That is a **contract clause on the error types**, testable by the conformance
suite: an attribute the constructor will not accept back under the same name
breaks reconstruction, and nothing else would catch it.

**Exactly two declared failures carry structured state today**, and both are
named because the general rule is only checkable against a known set:

| Type | `details` members |
| --- | --- |
| `OversizedValueError` | `limit: int`, `size: int`, `field: str \| None` |
| `UnresolvedEvidenceError` | `unresolved_ids: tuple[str, ...]` |

Both counts are of *structured state*, and `details_elided` is not that (above),
so adding it to the base class leaves this list at two.
`UnresolvedEvidenceError` is the one this ADR did not invent — it already carries
`unresolved_ids` (`core/errors.py:232-242`), it is declared by `answer` (§9), and
its ids are the whole content of the refusal. Every other type in §9's vocabulary
defines no `__init__` and therefore carries a message and nothing else, so it
sends no `details` at all. `OversizedValueError`'s three attributes are fixed here
because this ADR is what creates the type (§9).

**One code per *concrete* type, never flattened to a declared base.** §9's table
names base classes — `ModelError`, `MemoryStoreError`, `PlanningError` — and each
has subtypes an implementation may actually raise. Encoding a
`ModelRateLimitError` as `"ModelError"` would destroy exactly what ADR-0077 §3
requires to survive: it obliges a failed observing call to surface "unwrapped and
with its classification intact", and a client that received the base class has
been handed a classification the server did not make. So the code names what was
raised.

**An unknown code is a protocol violation, not a widening.** A client meeting a
code it does not know reports a transport-level protocol failure naming the code;
it does **not** fall back to the nearest ancestor it recognises. Falling back
would manufacture a typed refusal the server never sent, and ADR-0084 §3's exact
version match means the two halves ship together, so an unknown code is a bug
rather than a version skew to tolerate. A `details` object with a member the named
type does not accept, or missing one its constructor requires, fails the same way
— closed, rather than raising a half-populated exception whose empty field a
caller would read as "no ids were unresolved".

**An error payload is bounded like every other, and its overflow has a fixed
reduction rather than a refusal.** §8c's limit covers the error payload, and
`UnresolvedEvidenceError.unresolved_ids` is an unbounded tuple — so a refusal
citing enough unresolved records is a *typed error that cannot be sent*. Answering
that with `OversizedValueError` is not available and the reason is worth stating:
the response to a failed error delivery would itself be an error frame, so the
rule would recurse, and it would mislabel — the value the caller sent was not
oversized, the diagnosis of it was. So:

> **If an error payload exceeds the limit, `details` is set to `null` and
> `message` is truncated so the payload fits, and `reduced` becomes `true`.** This is always satisfiable: §8d's floor
> leaves room for a code, the member names and a non-empty message at the
> smallest legal `hub_max_frame_bytes`.

**A client that receives `reduced: true` raises the declared exception, with its
structured state absent and *marked* absent.** This is the substitutability
requirement biting, and an earlier draft got it wrong in an instructive way: it
had the client raise a *transport-level* failure instead, which meant one
`answer()` call raised `UnresolvedEvidenceError` in-process and something
undeclared over the wire. Two observable failure contracts for one call is
precisely what ADR-0084 §4–§5 promote this surface to prevent.

So the marker lives on the exception, not only on the frame:

> **`AssistantError` carries `details_elided: bool = False`.** It is `True` only
> on an exception a client reconstructed from a reduced payload. The client
> raises the **declared type**, with the message it was given, no structured
> state, and `details_elided` set.

**One optional attribute on the base class is what makes this honest rather than
inverted.** `unresolved_ids` defaults to `()`, so a reconstructed
`UnresolvedEvidenceError` without the flag would tell a caller that **nothing**
was unresolved at the exact moment that too much was. With it, a caller that
branches on the ids checks `details_elided` first and learns the list is
*missing* rather than empty.

**Some difference is physically forced here, and the contract's job is to make it
declared rather than silent.** A client cannot deliver a list through a pipe
narrower than the list, and no wording changes that. What the contract fixes is
that both implementations raise the same *type* with the same meaning, and that
the shortfall is machine-detectable. `details_elided` is `False` on every
in-process raise, because nothing elides there.

**Truncating the message is acceptable where truncating a payload is not**, and
the distinction is ADR-0073 §4's. Its no-silent-truncation rule protects a
*citation rendered as evidence* — a warrant a user is judging. An error message is
a diagnostic string, it is not evidence for anything, and `reduced: true` makes
the shortening explicit rather than silent. Nothing about the user's data is
dropped: the ids that would have travelled in `details` are still in the hub's
own state and its logs.

**`ValueError` is deliberately absent from this vocabulary**, and its absence is a
property of §9 rather than an omission here. Every `ValueError` the surface
declares — a malformed page argument, a blank identifier — is refused **locally,
before any I/O** (§3c, §9), so it never crosses a frame. The wire's error
vocabulary is therefore exactly the `AssistantError` subtree, which is also what
makes "the code is the class name" safe: `ValueError` is not ours to name.

### 11. Deferred by name, and where the corpus and the tree disagree

#### 11a. What is settled elsewhere: ADR-0087's encoding, and #565's discharged prerequisite

Named so the reference in §8c resolves to a decision rather than to a silence.

> **The canonical wire encoding — the exact byte string a payload serialises to —
> is ADR-0087's**, ratified with normative test vectors. This ADR fixes the limit
> (`hub_max_frame_bytes - 512`, §8c), that it covers all three payload classes,
> and that it is measured on that encoding.

**What ADR-0087 settles**, listed because each is a place two encoders can differ
at the boundary and each was found by review *here* rather than by inspection —
so the list is the evidence this ADR contributed, and every entry is now answered
in ratified text:

- insignificant whitespace, and the `,` / `:` separators;
- string escaping — `/` versus `\/`, the two-character control forms versus
  `\u00XX`, and non-ASCII as UTF-8 versus `\u`;
- number form — the shortest round-tripping decimal, and whether an exponent is
  ever emitted (`Belief.confidence` is the field this bites);
- instants — the UTC designator (`Z` versus `+00:00`) and fractional-second
  digits;
- durations — fractional seconds, trailing zeros, and whether a day component is
  used (`"P2DT3S"` versus `"PT172803S"`);
- the entry point for payloads that are **not** models — a request's argument
  object, and the bare `true` a `forget` returns;
- whether a value's bytes may depend on how the object was *constructed* rather
  than on what it is. **They may not**, and this one is a constraint rather than a
  question: two equal values must encode identically, or the same page lands on
  opposite sides of the limit depending on which implementation built it.

**This ADR pre-judged none of them**, and the list above is the problem statement
ADR-0087 inherited rather than a set of answers it was expected to reach — which
is why two of its rulings went the other way from the draft this ADR once
carried. Its §2e refuses the nominal `Y` outright, where the withdrawn draft here
would have taken whatever the library emitted; and its §2e range constraints
close a single-valuedness gap that draft never noticed. **Where this ADR and
ADR-0087 could be read as disagreeing, ADR-0087 governs the encoding and this ADR
governs the limit.**

**This ADR says nothing about where ADR-0087 sits in the work, and the omission
is the decision.** A position in a sequence is a fact about the ADR that occupies
it, so **ADR-0087 states its own** — its §6 places itself at ADR-0084 §5's step
**2b**, before the triad, on the ground that the triad ships the canonical fake
and so is where a second implementation is first held to §4's limit. The
ADR-0082 §1 record goes with it: ADR-0084's `Status` line now names both §5's
enumeration and §3's payload-encoding rule. Placing it from here would have made
§5's enumeration false *in this document* and made this the amending change
(§12).

**ADR-0087 §6 also declines to order itself against this ADR**, and that is worth
recording because it is the reason neither document has to mention the other's
position: "the relative order of this ADR and the surface ADR is deliberately not
fixed… neither is a prerequisite of the other". Both are contract changes before
the triad. This ADR is ADR-0084 §5's step 2 whatever else lands.

**#565's fix was named here as a prerequisite of the client lane, and it has
landed.** While the pre-existing `core` leaves still held bare `str`, this
contract declared request and result values ADR-0087 §2b gives no wire form, so
a client built first would have been one whose encoder raises on inputs this
Protocol admits — ADR-0084 §4's substitutability failure arriving through the
leaves. **#566 closed it** (§4c), so the condition is discharged rather than
outstanding, and the client lane inherits no debt from this clause.

**It is recorded rather than deleted**, because the reasoning is what a later
reader needs: a contract that admits a value no implementation can encode is not
made safe by the fact that nobody has built the second implementation yet, and
naming that as a readiness condition is what stopped it being discovered at the
socket.

**This is ADR-0084 §11's own form, deliberately** — that ADR attaches exactly
this kind of condition to #473 twice, at `0084:839` ("**So #473 is a prerequisite
of the client lane, not merely context for it**") and again in its §11. It is
named as that form so a reader probing it lands on the precedent rather than on
the shape this ADR avoids elsewhere: **a prerequisite is a fact about the client
lane's readiness, not a claim about when a change merges.** It orders no ADRs
against each other and enumerates nothing, so it leaves ADR-0084 §5's enumeration
of *changes* untouched and owes no record — the same reason ADR-0084 §11 owed
none for #473. **Nothing here said when #565's fix would merge**, only that the
client lane was not ready before it did — and #566 has since landed it, so the
condition is discharged rather than pending.

#### 11b. Where the corpus and the tree disagree, and which this ADR follows

Recorded rather than smoothed over, because each was found by reading the code and
a later reader will otherwise find the same discrepancy and wonder which won.

- **"Around nineteen methods" (ADR-0084 §5, and its Consequences).** The surface
  is fifteen after lifecycle is removed. This ADR follows the tree. §5's argument
  does not rest on the figure.
- **"Three of those live in `orchestration`" (ADR-0084 §4).** **Twenty-three
  existing `orchestration` types relocate**, five of them unnamed there, and
  `BeliefSummary` is **new** (§4a) — twenty-four promoted types in total. The two
  numbers count different things and both appear in this ADR, so they are
  distinguished here rather than left to collide: §4's tables and §5's walk are
  over the twenty-four, and the triad implements that set. This ADR follows the
  walk; §4 assigned the complete graph here precisely so that it would.
- **`pending_confirmations() -> list[Confirmation]` (ADR-0052 §2).** Becomes a
  tuple, §3b, under ADR-0052's own delegation of "the exact set" to this ADR.
- **`Engine.observe(conversation_id)` positional.** Becomes keyword-only, §2. No
  ADR fixed it; ADR-0077 §10's `observe` signature is the `Observer` Protocol's,
  a different method.
- **A bare `PlanningError` for an unresolvable token (`engine.py:2146`).** ADR-0084
  §7 requires a distinct typed refusal; §9 names it.
- **`Engine._project` resolves citation *content* on the listing path
  (`engine.py:2254`).** ADR-0077 §6 gives the listing existence and counts and
  gives content to the single-belief view alone. **Here this ADR follows the
  ADRs and not the tree** (§4a), and the reversal of direction is the point of
  listing it separately.

  Every other entry above is a place the *corpus* has gone stale about code that
  is correct, so the tree wins. This one is the opposite: the code diverges from
  two ratified ADRs, which is **#552**, and a contract ADR ratifies the decision
  rather than the defect. Promoting `Belief` as the tree projects it would make
  the divergence contract surface and turn its withdrawal into a Protocol change
  — which is precisely the cost ADR-0084 §4 says the promotion imposes, spent on
  preserving a bug.

### 12. Amendment records under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in the later ADR's text, naming the
clause and applying ADR-0070 §1's test: would a reader holding only the earlier
ADR now act differently, or read one of its clauses more widely than it now holds?
It also fixes the order — classify, then record — and its own note is explicit
that ratifying a `Proposed` ADR is not an amendment event, so this ADR's eventual
move to `Accepted` triggers nothing.

**No record is owed on any ADR. Applying the test to each candidate:**

- **ADR-0084.** This ADR is what its §5 step 2 and §11 deferred to *by name*. A
  deferral discharged by the change the deferring ADR named is a stacked addition
  on ADR-0083 §15's own stated test — the deferring sentence stays true and now
  has an answer. §11's two count corrections do not reach the test either: "around
  nineteen" and "three of those" are approximations inside sentences whose
  operative content is that the surface is promoted whole and that the closure is
  this ADR's to enumerate. A reader holding only ADR-0084 would not act
  differently; they would come here for the number, which is what §4 tells them to
  do.
- **ADR-0052.** Its appended note already rules that its Revisit clause "stays
  true and is now discharged" and that `pending_confirmations` joining the
  contract surface "is a **live obligation** on the surface ADR (#281), which
  ADR-0084 §4 makes the owner of the exact set." The `list` in §2's code block is
  inside the obligation it delegates, so changing it is this ADR exercising a
  delegation rather than contradicting a decision. Nothing ADR-0052 *decided* — a
  method that reconstructs answerable confirmations from durable state, an opaque
  token, enumerate-and-re-mint — moves.
- **ADR-0042.** Already partially superseded by ADR-0084 §12 on exactly the
  clauses this ADR acts under. §3's `converse(utterance, *, timeout)` and §4's
  opaque-token rule are kept verbatim; §2's argument convention *extends* them to
  thirteen methods ADR-0042 never spoke about, which is an addition and not a
  reading of §3 more widely than it holds.
- **ADR-0037.** `Disposition` keeps its five members and its module changes.
  ADR-0084 §12 reached the same conclusion for the same reason; relocating an enum
  is not redefining it (ADR-0084 §4).
- **ADR-0068.** §1's rule is applied to twenty-four new models, which is the rule
  being used rather than changed. §9's frozen-pydantic mechanism is §1's form
  exactly: `frozen=True`, `tuple` collections, nested models frozen.
- **ADR-0073 §4 and ADR-0077 §6, specifically.** §4a is worth its own entry
  because it changes a *shape*, and a shape change is the kind of thing that
  usually owes a record. It does not, on ADR-0070 §1's test in either limb. A
  reader holding only ADR-0077 §6 would act **exactly** as §4a requires — they
  would give the listing counts and the single view citations, which is what §6
  says in as many words; and no clause is read more widely than it holds, because
  §6's sentence is being applied at its stated scope rather than extended. What
  §4a changes is the *tree*, not either ADR: it makes a type that can express §6's
  split, where the tree has one that cannot. An ADR whose text you have to
  contradict to implement is amended; one whose text you have to be *able* to
  implement is served.
- **ADR-0084 §5's sequence, and §3's payload-encoding rule — no record owed here,
  and both are already recorded elsewhere.** Stated rather than left silent,
  because the silence is what invites the question. This ADR *cites* ADR-0087 for
  the encoding (§8c) and says nothing about where it lands (§11a); citing an ADR
  is not sequencing one. ADR-0070 §1 puts a record where the falsifying decision
  is, and both falsifying decisions are ADR-0087's — its §6 inserts the step, its
  §2 replaces the encoding rule — so **ADR-0084's `Status` line already carries
  the partial-supersession record naming both clauses**, written by ADR-0087's own
  change. ADR-0087 §6 reaches the same conclusion from its side about the one
  sentence this ADR does state: the limit being measured on the encoding ratified
  there "decides nothing about sequence, so stating it costs that ADR no amendment
  record."
- **ADR-0087.** No record owed in either direction. This ADR cites it and depends
  on it for the encoding; it depends on this one for nothing (its §6), and neither
  fixes the other's position.
- **ADR-0086.** No record, and no dependency in either direction. Its §7 hands
  the DTO shape here explicitly and takes no position on it; §8f states the
  relationship and declines to lean on an unratified ADR.
- **ADR-0073, ADR-0074, ADR-0077, ADR-0078.** Each supplies the semantic content
  of a promoted DTO — what `Belief` carries, what a `ConversationSummary` sorts
  by, what an `ObservationReport` counts, what a `Question` shows — and this ADR
  moves those fields without changing one of them. The records those ADRs owe for
  becoming contract surface are ADR-0084 §12's, already written for ADR-0073 and
  ADR-0078 §8 and deferred to **#536** for ADR-0077 §10 item 7. Nothing here adds
  to that set.
- **ADR-0083.** Untouched. §14's boundary holds in both directions and this ADR
  adds no setting, no lifecycle step and no startup condition beyond the floor §8d
  states, which ADR-0084 §3 asked for by name.

## Consequences

- **The triad lane has a specification rather than a design task.** Fifteen
  signatures, twenty-four types with their fields, one closed graph, five
  contract clauses and two error types. ADR-0015 §5's purpose — that no lane
  authors `core` contract surface unreviewed — is discharged by this document
  existing and being reviewed as contract surface.
- **`core/types.py` grows by twenty-four types**, which is the largest single
  addition it has taken. That is the cost ADR-0084 §5 named ("a large Protocol and
  a large conformance suite — considerably more than the triads the corpus has
  written so far"), quantified.
- **Six contract clauses exist that no type expresses**, and the conformance
  suite is the only thing that can hold an implementation to them: the page-size
  default (§3a), pre-`await` materialisation of the filters (§3d), local refusal
  of malformed page arguments and blank identifiers (§3c, §9), the size limit in
  both directions and across all three payload classes with the error payload's
  reduction (§8, §10a), the disposition-is-not-the-outcome rule (§7), and an
  error type's structured state round-tripping through its own constructor, with
  `details_elided` set where it could not (§10a). Each is
  written as a testable sentence for that reason. **Six more are expressed by the
  types themselves** — §4b's five cross-field validators and §4c's encodable-text
  refinement — and one more by a return type alone (§4a), which is the cheapest of
  the lot: it needs no clause and no test, because the wrong response cannot be
  constructed.
- **What becomes harder: every one of these fields now costs an ADR to change.**
  ADR-0084 §4 anticipated it — "changing a field that was free to change in
  `orchestration` now costs an ADR" — and the figure is twenty-four types' worth
  of fields. A subsystem that wants a new field on `TurnOutcome` writes an ADR;
  before this, it edited a dataclass.
- **The belief listing stops carrying the corpus** (§4a). `beliefs()` returns
  `BeliefSummary`, so ADR-0077 §6's split is a type signature rather than a
  convention, and the frame arithmetic's page-multiplied term disappears (§8f).
  **The listing still resolves existence** — the adjusted confidence needs it —
  so the lane that edits `_project` owes #552's item 1, and a batch read is what
  makes it cheap.
- **Two adapter consequences fall to the client lane**, not one: `observe`'s
  selector becomes keyword-only (§2), and the listing renderer takes
  `BeliefSummary`. The second is nearly free — `_render_belief(evidence=False)`
  and `_why` already read only the summary's fields (`cli.py:1936-1950`,
  `:1987`), so the change is the annotation and the `evidence=` parameter going
  away on that path.
- **What becomes easier: a spoke is writable.** A client author has the whole
  surface, the whole type graph, the wire form of every argument and result, and
  the failures each method declares, without reading `orchestration`.
- **#281 is discharged** — the normative outcome DTO, the opaque-token DTO and its
  lifetime, and the exact keyword-only `converse`/`resume` signatures it asked for
  are §4, §4 and §3. #531's contract half is discharged by §7; its adapter half
  stays open for the client lane.
- **The relocation changes no wire byte and no enum value.** Every promoted
  `StrEnum` keeps its base and its member values, so the move is invisible to
  anything serialising them.
- **Revisit when** the plan-driving stage (#242) lands, since a turn driving more
  than one step makes `StepOutcome`'s singular `step_id` the wrong shape and
  ADR-0052's Revisit clause anticipates the same for recovery; when #473 bounds
  `Belief.evidence`, which turns §8e's "unreachable in practice" into "provably
  unreachable"; when a stage emits progress, which is ADR-0042 §5's streaming
  extension and would add a method or a shape here; and when the two halves can
  version independently, which is when ADR-0084 §4's rejected separate wire schema
  becomes the right answer and this Protocol stops being the wire's schema too.

## Alternatives considered

- **Carry the projection classmethods onto the promoted models.** Rejected in §6:
  `LearnOutcome.from_results` names `orchestration.writes.WriteOutcome`, so
  carrying it puts `core → orchestration` in the import graph and fails
  `lint-imports`. Carrying only the four that are safe was the near miss — it
  would work today — and is rejected because it leaves the triad lane a rule with
  an exception to re-derive, and because `Belief.from_record` applies `band_of`,
  which is ADR-0072 §1's projection and not `core`'s to own.
- **Expose the derived predicates as `computed_field`s so they cross the wire.**
  Rejected in §6b: they are pure functions of fields already sent, so
  transmitting them creates a second source of truth for a fact the client can
  recompute exactly, and a client trusting the transmitted copy would be trusting
  a value nothing validates.
- **Bound each argument and result *value* independently, rather than the
  payload.** Rejected in §8c: a request payload carries every argument plus its
  member names, so a `converse` call whose `utterance` sits exactly at the bound
  overflows the frame on `timeout` alone — leaving the client to refuse an input
  the contract admitted, or to send a frame the server refuses on its prefix.
  Bounding the payload measures the thing the length prefix counts.
- **Leave the canonical byte encoding to the implementing lane, with the
  conformance suite testing only the limit's behaviour.** *Held for two rounds and
  rejected in §8c.* The triad's canonical fake is a second implementation and it
  arrives in change 3, so two implementations can disagree about which calls are
  refused before the wire package exists at all; refusal is contract-visible, and
  a suite can only test what is specified. ADR-0087 ratifies the bytes instead.
- **Pin the canonical byte encoding in this ADR** — first as a grammar of rules an
  encoder must satisfy, then as a named pydantic entry point. *Attempted, and
  withdrawn.* The grammar form took four review rounds, each finding one more
  corner (`/` versus `\/`, `0.1` versus `1e-1`, `Z` versus `+00:00`, `"PT0.5S"`
  versus `"PT0.500000S"`) with a fifth still open; the entry-point form then had to
  answer which adapter, which flags, and what `T` is per payload class, and one of
  those answers made a result's bytes depend on how the object was *constructed*
  rather than on its value. Both are the unspiked seam #281 warns about, and both
  are the enumeration §8d and §10a decline elsewhere. The encoding is a
  *representation* contract, where a round-trip vector pins it in a line — so it is
  **ADR-0087's** (§11a). **What is kept here is the
  limit and that it is measured on one canonical encoding** — the part ADR-0084 §4
  makes contract.
- **Answer an oversized error payload with `OversizedValueError`, as an oversized
  argument or result is answered.** Rejected in §10a: the response to a failed
  error delivery is itself an error frame, so the rule recurses, and it mislabels
  — what was too large was the diagnosis, not the value the caller sent.
- **Have the client raise a transport-level failure when an error payload was
  reduced, rather than the declared exception.** *Held briefly, and rejected in
  §10a*: it gave one `answer()` call two observable failure contracts —
  `UnresolvedEvidenceError` in-process, something undeclared over the wire — which
  is the substitutability ADR-0084 §5 promotes this surface to provide. Raising
  the declared type with `details_elided` keeps one contract.
- **Reconstruct the declared exception from a reduced payload with no marker.**
  Rejected in §10a for the opposite reason: `unresolved_ids` defaults to `()`, so
  a caller branching on it is told nothing was unresolved at the moment too much
  was. Losing structured state costs information; inverting it misleads.
- **Bound `UnresolvedEvidenceError.unresolved_ids` in this ADR so the error
  always fits.** Rejected: bounding an unbounded citation sequence is #473's
  question and another lane's, and taking it here to solve a transport problem
  would decide a memory-contract matter as a side effect. The reduction rule
  needs no bound and holds whatever that lane decides.
- **Let a client widen an unrecognised error code to the nearest ancestor it
  knows.** Rejected in §10a: it manufactures a typed refusal the server never
  sent, and ADR-0084 §3's exact version match means an unknown code is a bug
  rather than skew to absorb.
- **Add a `data_export` method to the Protocol while the surface is being
  pinned.** Rejected in §6c: `Engine` exposes no export today and no CLI command
  reaches `ConversationLifecycle.export`, so adding one would be widening the
  surface under cover of pinning it — and ADR-0084 §5's argument for promoting the
  whole surface is an argument about the surface that *exists*.
