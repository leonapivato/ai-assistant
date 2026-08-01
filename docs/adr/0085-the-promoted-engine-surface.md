# 85. The promoted engine surface: fifteen methods, twenty-three types, one closed graph

- Status: Proposed
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
  at `main` @ `e1e4070`, not derived from the ADRs. Where the corpus and the tree
  disagree, §11 says so and says which one this ADR follows.
- **No implementation lands with it.** No `src/`, no `tests/`. It ratifies what
  `core/protocols.py` and `core/types.py` will contain; the triad — Protocol +
  shared conformance suite + canonical fake in `ai_assistant.testing` — is
  ADR-0084 §5's step 3 and a separate lane, merging before any client (golden
  rule 5, ADR-0015 §5).
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

Enumerated from the tree, the closure is **twenty-three types**, not three.
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

Written as they appear on the Protocol. `Identifier` and `UtcInstant` are
`core/types.py`'s existing annotated aliases (a non-blank `str`, a tz-aware
`datetime`); `DEFAULT_PAGE_SIZE` is §3a below.

```python
class AssistantEngine(Protocol):
    # The two turn calls (ADR-0042 §3)
    async def converse(
        self,
        utterance: str,
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

    # The inspection surface (ADR-0073 §7)
    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[Belief, ...]: ...

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
does not validate anything by itself.** So the contract clause carries it:

> An implementation refuses a blank identifier argument with `ValueError`, before
> any I/O.

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

`Engine.beliefs` does this at `engine.py:1314-1315`, snapshotting both to tuples
before creating the tracked task; a wire client does it by construction, having
serialised the arguments before sending. The clause exists so the conformance
suite can prove it of *both*, rather than it being an accident of how one of them
happens to be written.

**Empty and `None` remain different**, as ADR-0073 §2 already fixed: `None`
selects every band or kind, an empty sequence selects nothing, and the two
filters compose by conjunction.

### 4. The twenty-three promoted types and their normative fields

Every type below moves to `core/types.py` as a frozen pydantic model or a
`StrEnum`, under ADR-0068 §1 — `frozen=True`, `tuple` collections, nested models
frozen (§9 covers the mechanism and what changes with it). Fields are listed in
declaration order; a trailing `= …` is the default.

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

### 5. The complete transitive closure, and the boundary it stops at

This is the enumeration ADR-0084 §4 assigns to this ADR. It is written as a
reachability walk from the fifteen signatures, because that is the only form in
which "complete" is checkable.

**Roots — what the fifteen methods name.** Arguments: `str`, `timedelta`, `bool`,
`int`, `Identifier`, `FeedbackEvent`, `Sequence[BeliefBand]`,
`Sequence[MemoryKind]`, `ContinuationToken`. Returns: `TurnOutcome`,
`LearnOutcome`, `ObservationReport`, `Belief`, `Question`, `AnswerOutcome`,
`ConversationSummary`, `ConversationDigest`, `Confirmation`, `bool`.

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

Belief ┬─ band     → BeliefBand [core]
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

**The twenty-three that promote**, gathered from that walk: `ContinuationToken`,
`Confirmation`, `StepOutcome`, `TurnOutcome`, `LearnDecision`, `QueueOutcome`,
`QueuedQuestion`, `IngestSummary`, `LearnOutcome`, `Evidence`, `Belief`,
`ConversationSummary` (twelve from `engine.py`); `QuestionState`, `Retirement`,
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
not `computed_field`.** **Eleven exist**, and the list is normative — a triad
implementation that carried a subset would leave the CLI reading an attribute
that is not there:

| Model | Properties |
| --- | --- |
| `IngestSummary` | `stored` |
| `LearnOutcome` | `stored` |
| `Evidence` | `lost` |
| `Belief` | `evidence_count`, `lost_evidence`, `unsupported` |
| `ObservedProposal` | `stored`, `evidence_count`, `inspectable` |
| `ObservationReport` | `stored`, `discarded` |

Every one is a pure function of fields the model already carries — verified
individually, and it is what makes the non-serialisation rule below safe rather
than merely tidy.

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
`_converse` has `first.id` where `first = turn.plan.steps[0]` (`engine.py:1981`,
`:1995`), and `_resume` has `parked.step_id` (`engine.py:2068`, `:2075`). There is
no path on which a `StepOutcome` exists and the step it is about does not — a turn
whose plan had no step returns `TurnOutcome(step=None)` and constructs no
`StepOutcome` at all (`engine.py:1974-1980`). So an optional field would be an
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
> serialised **payload** — for a call, the request's argument object as §10
> encodes it; for a return, the result value as §10 encodes it — measured as the
> byte length of that payload's canonical UTF-8 JSON encoding, which is pinned
> below.** Every implementation enforces it, on arguments before dispatch and on
> results before return.

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

**The encoding is pinned, because "JSON mode" names a value shape and not a byte
string.** Two conforming encoders can produce different byte counts for the same
value — one inserting whitespace after `,` and `:`, one escaping non-ASCII as
`\uXXXX` — and a limit whose measurement differs between the two implementations
is not one limit. So:

> **The measurement is taken on the payload's UTF-8 JSON encoding in its
> canonical form: no insignificant whitespace (the `,` and `:` separators carry
> none), and non-ASCII characters emitted as UTF-8 rather than as `\u` escapes.**
> This is the encoding ADR-0084 §3 puts on the wire, and it is what pydantic's
> own `model_dump_json()` produces — so an implementation that measures the bytes
> it is about to send, and an in-process one that calls the same method, agree by
> construction rather than by care.

Pinning it as the *wire's* encoding rather than as a convention of this ADR is
what keeps the two numbers the same: the client is measuring the frame it will
actually write, not a proxy for it.

The measure is a serialisation at all because that is what ADR-0084 §3's length
prefix counts, and a limit measured on anything else — a character count, a
Python object size — would be a number the two implementations compute
differently for the same value. A directory named in a non-ASCII script spends more of the budget
than it looks like it does, and so does an utterance.

**Subtracting the reserve is the other half of the arithmetic.** Set the contract
limit equal to `hub_max_frame_bytes` and a payload at exactly the limit overflows
the frame by the envelope's own bytes. With the subtraction, a payload the
contract admits always fits a frame, and the in-process engine enforces the
identical number by reading the same setting.

**The in-process engine pays a measurement it did not pay before, and the
contract fixes the answer rather than the method.** It has no payload to
serialise for its own sake, so enforcing the bound means encoding one. That cost
is ADR-0084 §4's, not this ADR's — "every implementation enforces it, the
in-process engine included" — but the clause is written so the cost is avoidable
where it cannot bind:

> What the contract fixes is **which payloads are refused**, not how the refusal
> is computed. An implementation may use any cheaper test that refuses exactly
> the same set — for instance skipping the encoding entirely when a conservative
> upper bound proves the payload is inside the limit.

**The in-process engine reads `Settings.hub_max_frame_bytes` directly.** It has no
handshake to be told the value by; the client is told it by the connect reply
(ADR-0084 §3) and enforces the number it was told. Same number, two routes to it.

**An oversized payload raises `OversizedValueError(AssistantError)`, naming the
limit, the measured size, and the largest argument or field contributing to it**
(§9) — which is ADR-0084 §4's "naming the limit and the field that exceeded it"
under a payload-level bound, and is the actionable half: "your request is 17 MiB
against a 16 MiB limit, mostly `utterance`" tells a user what to do, and a bare
total does not. On the client this fires *locally*,
before a byte is sent, which is ADR-0084 §3's stated behaviour for an oversized
argument — "not as a connection that closes mid-request".

#### 8d. `hub_max_frame_bytes` has a floor of 1024 bytes

ADR-0084 §3 requires the setting to be "large enough for the mandatory handshake
and the smallest valid envelope" and says "the exact floor depends on the envelope
schema and is therefore fixed by the surface ADR". With §8a's schema:

> **`hub_max_frame_bytes` is refused at load time below 1024 bytes**, alongside
> its existing `gt=0` and its upper bound at the 4-byte prefix's ceiling.

The connect reply's payload carries a version (an integer), a build identifier, a
readiness flag and the effective frame size — every member fixed-width except the
build identifier, so the floor is only derivable if that one is bounded. It is
not bounded anywhere today, and a floor resting on an unstated bound is not a
proof: a hub emitting a 1000-byte build identifier would accept
`hub_max_frame_bytes=1024` at load and then fail every handshake, which is the
exact failure this floor exists to prevent, produced by the check that was
supposed to prevent it. So the bound is made normative here, which ADR-0084 §3's
assignment of the floor to this ADR necessarily carries with it:

> **The connect reply's build identifier is at most 64 bytes**, and a longer one
> is a protocol violation.

With that, the connect reply's payload is under 200 bytes; with the 512-byte
reserve, 1024 leaves room for the handshake and for a small request besides. A value below the
floor yields a hub that passes every ADR-0083 §3 startup step and then refuses
every client including the CLI — indistinguishable from a hub that is down, which
is ADR-0084's ruling 4 failure produced by a config typo, and load time is where
it should surface.

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

### 9. The declared failures, and the two error types this surface needs

A Protocol whose methods raise unnamed exceptions is not a contract a conformance
suite can hold anyone to, and ADR-0084 §3 requires a wire error to carry "a typed
code and a message". So the failures are declared, and two new types are named —
both of them the *spelling* of a refusal ADR-0084 already ratified, not a new
decision.

**`UnknownContinuationError(PlanningError)`.** ADR-0084 §7 ratified that
presenting a token the server cannot resolve "yields one specific, typed refusal —
an unknown-continuation error — and never a generic failure, and never a denial",
covering both a hub restart and eviction under
`max_outstanding_confirmations`. `Engine._resume` raises a bare `PlanningError`
today (`engine.py:2061`), which is indistinguishable from four other planning
faults. Subclassing `PlanningError` rather than `AssistantError` directly is
deliberate: every existing `Raises: PlanningError` contract on this surface stays
true, and a caller that already handles it keeps working, while a caller that
wants ADR-0084 §7's specific remedy — call `pending_confirmations()` and re-mint —
can now catch the thing that has that remedy.

**`OversizedValueError(AssistantError)`.** §8's typed refusal. It carries the
limit, the payload's measured size, and the name of the largest argument or field
contributing to it, because ADR-0084 §4 requires the limit and the field and
because "too large" without a number is not actionable.

**The per-method declared failures:**

| Method | Declares |
| --- | --- |
| `converse` | `ValueError`, `UnknownConversationError`, `PlanningError`, `ContextError`, `AuditError`, `ToolBindingError`, `OversizedValueError` |
| `resume` | `UnknownContinuationError`, `PermissionDeniedError`, `AuditError`, `ToolBindingError`, `OversizedValueError` |
| `learn` | `MemoryStoreError`, `OversizedValueError` |
| `observe` | `ValueError`, `UnknownConversationError`, `ConversationStoreError`, `MemoryStoreError`, `ModelError`, `OversizedValueError` |
| `beliefs`, `belief` | `MemoryStoreError`, `ValueError`, `OversizedValueError` |
| `forget` | `MemoryStoreError`, `ValueError` |
| `questions`, `interrupted_questions` | `DeferralStoreError`, `MemoryStoreError`, `ValueError`, `OversizedValueError` |
| `answer` | `MemoryStoreError`, `UnresolvedEvidenceError`, `DeferralStoreError`, `ValueError`, `OversizedValueError` |
| `forget_question` | `DeferralStoreError`, `ValueError` |
| `recent_conversations`, `conversation` | `ConversationStoreError`, `ValueError` |
| `forget_conversation` | `ConversationStoreError`, `MemoryStoreError`, `ValueError` |
| `pending_confirmations` | `PlanningError`, `AuditError`, `OversizedValueError` |

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
  named exactly as the Python parameters are, with omitted optional arguments
  omitted rather than sent as `null` — so the receiver applies its own declared
  default (§3a) and the two implementations cannot disagree about what "not
  passed" means. The method name is the envelope's `method` member (§8a), not a
  payload member.
- **Argument scalars** take pydantic's JSON-mode form for their type: `timeout`
  is an ISO-8601 duration string, a `bool` is a JSON boolean, an `Identifier` is a
  string, and `bands`/`kinds` are JSON arrays of their enum values.
- **A result payload** is the promoted model serialised through pydantic's JSON
  mode; `null` where the method returns an optional (`belief`, `conversation`); a
  JSON array where it returns a tuple (`beliefs`, `questions`,
  `interrupted_questions`, `recent_conversations`, `pending_confirmations`); and a
  JSON boolean for the three methods returning `bool` (`forget`,
  `forget_question`, `forget_conversation`, and no other).
- **Every promoted `StrEnum` serialises as its member value**, which is why §4
  keeps the `StrEnum` base: `Disposition.EXECUTED` is `"executed"` on the wire
  today and after the move, so the relocation changes no byte.
- **The byte encoding is §8c's canonical form** — compact separators, non-ASCII
  as UTF-8 rather than `\u` escapes — for every payload on this wire, so the
  bytes a client measures against §8c's limit are the bytes it writes.

### 11. Where the corpus and the tree disagree, and which this ADR follows

Recorded rather than smoothed over, because each was found by reading the code and
a later reader will otherwise find the same discrepancy and wonder which won.

- **"Around nineteen methods" (ADR-0084 §5, and its Consequences).** The surface
  is fifteen after lifecycle is removed. This ADR follows the tree. §5's argument
  does not rest on the figure.
- **"Three of those live in `orchestration`" (ADR-0084 §4).** Twenty-three types
  promote and five of them are unnamed there. This ADR follows the walk; §4
  assigned the complete graph here precisely so that it would.
- **`pending_confirmations() -> list[Confirmation]` (ADR-0052 §2).** Becomes a
  tuple, §3b, under ADR-0052's own delegation of "the exact set" to this ADR.
- **`Engine.observe(conversation_id)` positional.** Becomes keyword-only, §2. No
  ADR fixed it; ADR-0077 §10's `observe` signature is the `Observer` Protocol's,
  a different method.
- **A bare `PlanningError` for an unresolvable token (`engine.py:2061`).** ADR-0084
  §7 requires a distinct typed refusal; §9 names it.

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
- **ADR-0068.** §1's rule is applied to twenty-three new models, which is the rule
  being used rather than changed. §9's frozen-pydantic mechanism is §1's form
  exactly: `frozen=True`, `tuple` collections, nested models frozen.
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
  signatures, twenty-three types with their fields, one closed graph, five
  contract clauses and two error types. ADR-0015 §5's purpose — that no lane
  authors `core` contract surface unreviewed — is discharged by this document
  existing and being reviewed as contract surface.
- **`core/types.py` grows by twenty-three types**, which is the largest single
  addition it has taken. That is the cost ADR-0084 §5 named ("a large Protocol and
  a large conformance suite — considerably more than the triads the corpus has
  written so far"), quantified.
- **Five contract clauses exist that no type expresses**, and the conformance
  suite is the only thing that can hold an implementation to them: the page-size
  default (§3a), pre-`await` materialisation of the filters (§3d), local refusal
  of malformed page arguments and blank identifiers (§3c, §9), the size limit in
  both directions (§8), and the disposition-is-not-the-outcome rule (§7). Each is
  written as a testable sentence for that reason.
- **What becomes harder: every one of these fields now costs an ADR to change.**
  ADR-0084 §4 anticipated it — "changing a field that was free to change in
  `orchestration` now costs an ADR" — and the figure is twenty-three types' worth
  of fields. A subsystem that wants a new field on `TurnOutcome` writes an ADR;
  before this, it edited a dataclass.
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
- **Leave the measurement as "pydantic JSON mode" without pinning the bytes.**
  Rejected in §8c: JSON mode names a value shape, not a byte string, so two
  conforming encoders differing only in whitespace or `\u` escaping would
  disagree about whether the same call is oversized — which is one limit in name
  and two in effect.
- **Derive the `hub_max_frame_bytes` floor without bounding the build
  identifier.** Rejected in §8d: the floor is then a proof resting on an unstated
  premise, and a hub emitting a long build identifier would accept the minimum
  configuration and fail every handshake — the floor's own failure, arriving
  through the floor.
- **Set the contract size limit equal to `hub_max_frame_bytes`.** Rejected in §8c:
  a value at exactly the limit passes the contract and overflows the frame by the
  envelope's bytes, so the in-process engine would accept what the client
  provably cannot send — §4's divergence, from the side nobody was watching. The
  fixed reserve is what relates the two limits.
- **Compute the envelope reserve exactly (109 bytes) rather than fixing it at
  512.** Rejected in §8b: ADR-0084 §3 permits a later version to add envelope
  members, and an exact reserve turns any such addition into a silent overflow at
  the ceiling. The slack costs 402 bytes out of a 16 MiB default.
- **Leave the correlation id unbounded.** Rejected in §8a: without a bound the
  envelope reserve is not a constant, so §8c's arithmetic has nothing to subtract
  and the contract limit cannot be stated at all.
- **Make `StepOutcome.step_id` optional.** Rejected in §7: both construction sites
  hold the id already and a `StepOutcome` cannot exist without a step, so the
  optionality is unproducible and every client would carry a dead `None` branch.
- **Give `Disposition` a `FAILED` member, or duplicate `status`/`failure` onto
  `StepOutcome`.** Both already rejected by ADR-0084 §8 — the first fuses the
  gate's verdict with the invocation's outcome and amends ADR-0037; the second
  creates two sources of truth for a fact `state` already carries correctly. §7
  adds one field instead.
- **Keep `pending_confirmations` returning a `list` to avoid touching ADR-0052's
  printed signature.** Rejected in §3b: it is the only mutable page on a
  fifteen-method surface, and ADR-0052's own note delegates the spelling here.
- **Freeze the thirteen unspecified argument conventions as they are today rather
  than adopting a rule.** Rejected in §2: it preserves one positional optional
  (`observe`) that cannot be joined by a second without ordering ambiguity, and it
  leaves a `core` Protocol with no stated convention for the next method anyone
  adds. The rule costs one call-site edit in a file the client lane is rewriting.
- **Constrain `ObservedProposal.confidence` to `[0, 1)`, matching ADR-0077 §5's
  producer rule.** Rejected in §4: it converts a producer bug into a report that
  cannot be constructed, so the entry a human most needs to see — a proposal
  something got wrong — would take the whole `ObservationReport` down with it.
- **Add a `data_export` method to the Protocol while the surface is being
  pinned.** Rejected in §6c: `Engine` exposes no export today and no CLI command
  reaches `ConversationLifecycle.export`, so adding one would be widening the
  surface under cover of pinning it — and ADR-0084 §5's argument for promoting the
  whole surface is an argument about the surface that *exists*.
