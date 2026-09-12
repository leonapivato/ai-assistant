# 250. A turn finds its goal before it plans, focus is the most recently engaged goal, and a material ambiguity the planner reported becomes one durable question bound to that goal

- Status: Proposed
- Date: 2026-09-12
- **Partially supersedes** [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — **two scopes, each narrow. §7's `ProposedUnderstanding` field enumeration, in one
  member's element type alone**: `questions` becomes a
  `tuple[ProposedQuestion, ...]`, so that a raised question names **what it is about** and
  §6's materiality test has a subject to run over. Nothing else about that field moves —
  it is still carried on the envelope, still the planner's to fill, still read by no lane
  of ADR-0249, and §7's statement that *"**what a raised question becomes is A2's**"* is
  what this decision is doing rather than something it contradicts. §7's every other
  clause binds entire: its `Planner.plan` roster, its `PlannerOutput` two-field
  enumeration, its retained-or-restated validator, its retention-copies-forward clause,
  its `ProposedElement` shapes, its ground-resolution rules and their refusals, its
  minted-record clause and its interpretation-is-the-model's asymmetry. **And §1's `Goal`
  model declaration, in the field count alone**: `Goal` gains `last_engaged_in`, an
  `Identifier | None` naming the conversation of the goal's most recent engagement, so a
  reader holding only ADR-0249 §1 builds a `Goal` that never carries one and does not
  conform. §1's `conversation_id`-is-provenance-and-not-a-fence clause binds **entire and
  is the ground this field is added on**; §1's four-absences clause is **extended and not
  weakened**, `last_engaged_in`'s `None` being reachable by the same one route as
  `last_engaged_at`'s; §1's `statement`-as-projection rule, its append-only
  interpretation rule, its `version` clause and its *"no lane in this decision reads
  `last_engaged_at` for any purpose"* clause are untouched, the last being **fulfilled**
  by §1 below. §§2-6 and §§8-17 of ADR-0249 stand entire.
- **Partially supersedes** [ADR-0014](0014-planning-model.md)
  — **§5's `PlanStore` member enumeration and its `PlanExport` shape, layering on
  ADR-0249 §12's record.** The roster gains seven members — `engage_goal`,
  `candidates_for`, `record_question`, `get_question`, `open_question`,
  `outstanding_questions` and `settle_question` — `delete_goal`'s cascade reaches a goal's
  questions, and `PlanExport` gains `questions` with §5's closure rule extending to
  `question_id` rather than changing. A reader holding only ADR-0014, or only ADR-0249's
  widening of it, implements a store with no durable clarification and no engagement
  stamp, which is ADR-0070 §1's test coming out on the supersession side. §5's
  compare-and-swap discipline, its transitions-not-snapshots rule, its local-residency,
  its export-completeness and deletion obligations bind entire and are the grounds this
  decision reasons from; §§1-4, §6 and §7 are untouched by this decision.
- **Partially supersedes** [ADR-0085](0085-the-promoted-engine-surface.md)
  — **§3's signature block, in `converse`'s parameter list and in the roster's count
  alone.** `converse` gains one keyword parameter, `reference` (`TurnReference | None`,
  defaulting to `None`), and the surface gains `goals`, `withdraw_clarification` and
  `abandon_goal`. A reader holding only §3 writes a `converse` that cannot be given a
  reply reference, so a client naming the question it is answering has no parameter to
  name it in — ADR-0070 §1's test on the supersession side. §3's every-annotation-is-
  spelled-out rule, its docstring obligations, its `DEFAULT_PAGE_SIZE` convention and §5's
  closed-graph obligation bind entire and are obeyed: every type this decision adds to the
  surface is reachable from it and is `core`'s. **`converse_streaming` needs no record of
  its own**: ADR-0173 defines it as *"taking exactly `converse`'s arguments in exactly its"*
  order, so it takes the new keyword by that clause rather than by an amendment to it.

## Context

### Where this comes from

Issue #2255 is the owner's handoff from the Planning/Execution wiki review, and its A0–A10
breakdown is the ruled delivery cut. A0 is [ADR-0248](0248-the-users-request-is-its-own-value-on-the-turn-and-the-goal-statement-stops-standing-in-for-it.md),
merged and implemented: the user's request became a value of its own on the turn. A1 is
[ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md),
ratified at `db915e62`: the goal became an append-only sequence of grounded interpretation
revisions, the attempt became the carrier of the phase, and `Planner.plan` became a brief in
and an understanding out. **This is A2.**

ADR-0249 §13 names what it left here, by name: *"Association over N candidates, focus, and
what moves `last_engaged_at`"*; *"Materiality, when a question is asked, the `GoalQuestion`
record and its store, and what becomes of a `ProposedUnderstanding`'s `questions`"*;
*"Resumption of a goal from another conversation by explicit reference … and whether
automatic cross-conversation association is ever built"*; *"Which user acts open an
attempt"* (shared with A3); and, at §4, which act writes `GoalStatus.ABANDONED`.

The owner's rulings of 2026-09-12 on #2255 bind this decision directly. Decisions 1–6 and
the answer to Q6 are each implemented below by a clause that names them, and **correction 2**
— *"Producing a reply never by itself establishes that the goal was achieved"* — is obeyed by
this decision writing no `GoalStatus.ACHIEVED` anywhere, exactly as ADR-0249 §4 requires. The
**standing rule** — *convenience alone is insufficient justification for a user-facing
restriction* — is applied throughout, and the one restriction this decision keeps names the
genuine constraint behind it (§8).

### The gap this closes

ADR-0249 landed `Goal.last_engaged_at` and said of it, in terms: *"**What engages a goal is
A2's** (§13), and no lane in this decision reads `last_engaged_at` for any purpose: this ADR
lands the field and nothing else."* It landed `ProposedUnderstanding.questions` and said
*"**A `ProposedUnderstanding`'s `questions` are carried and no lane of this decision reads
them.** Nothing here asks a question, stores one, or projects one onto a brief."* And it made
`Goal.conversation_id` *"provenance and **not a fence**"* while ruling that whether a goal is
reached from a second conversation *"is A2's"*.

So after A1 the system can hold several goals and revise any of them, and has no rule for
deciding **which one a turn is about**. Its planner can report that it did not understand,
and there is nowhere for that report to go. Its goals carry an engagement instant nothing
writes and nothing reads. Every one of those is a contract gap rather than a wiring one, and
each is a value ADR-0249 deliberately landed empty for this decision to fill.

### What this decision reads, and what it had to read from a document rather than from the tree

Every clause below was checked against `origin/main` at **`db915e62`**. **ADR-0249's types
are not in the tree**: at that commit `git grep` over `src/` returns **zero** hits for
`GoalInterpretation`, `GoalElement`, `Ground`, `GoalAttempt`, `AttemptState`,
`AttemptPhase`, `AttemptOutcome`, `AttemptEffort`, `GoalBrief`, `BriefElement`,
`ProposedUnderstanding`, `ProposedElement`, `PlannerOutput`, `EvidenceDigest` and
`MAX_GOAL_INTERPRETATIONS`, because ADR-0249's §15 L1 lane is in flight. **Their shapes are
therefore read from ADR-0249's own normative text and not from a definition**, and this
decision is written against the contract that ADR is, which is what a contract ADR landing
before its implementation means (`CONTRIBUTING.md` → "Contract ADRs land before their
implementation"). What **was** read in the tree, and is relied on as read: `Goal`,
`GoalStatus`, `ContinuationToken`, `Question`, `QuestionState` and `ToolDefinition` in
`core/types.py`; `Planner`, `PlanStore`, `QueryComposer`, `ParkedReads`, `ToolRegistry` and
`AssistantEngine` in `core/protocols.py`; `permissions/parked_reads.py`;
`orchestration/loop.py`'s constructor and `orchestration/engine.py`'s `save_goal` sites; and
`interfaces/cli.py`'s `resume`, `cancel-read`, `questions`, `answer` and `forget-question`
commands.

**Three tree facts shape this decision and are stated here because a reader would otherwise
assume their opposite.**

**`ToolDefinition.side_effecting` exists.** It is declared `side_effecting: bool` with the
description *"Whether invoking it changes anything outside itself."* §6's materiality test is
therefore a test over a declared fact and not over a judgement, which is what #2255's addendum
demands: *"Giving a model's judgment a typed label does not make it mechanically proven — say
what code checks and what it takes on the model's word."*

**`LearningLoop` holds no `PlanStore`, and this decision does not give it one.** ADR-0228 §5
forbids it — *"no lane adds a second persistence site, gives `LearningLoop` a `PlanStore`, or
carries a plan out of a failing turn in order to write it"* — and ADR-0249 §11 restates it
verbatim. Every store read and every store write this decision adds is therefore `Engine`'s,
and the values travel to and from the loop **inside `ai_assistant.orchestration` as data**,
which is ADR-0249 §11's own carrier shape.

**`questions` and `answer` are taken.** `AssistantEngine.questions`, `AssistantEngine.answer`
and the CLI's `assistant questions` / `assistant answer` are ADR-0078 §8's **deferred memory
questions** — a contradiction about a belief, answered `--accept`/`--reject`. A goal's
clarification is a different thing about a different subject with a different vocabulary, and
§15 gives it names of its own rather than overloading those.

### What this ADR is not allowed to settle

#2255's breakdown assigns the bounded investigation loop and the effort figures to A3, the
evidence rules to A4, the plan's step fields to A5, authorization coverage to A6, driving to
A7, retry and reconciliation to A8, cancellation to A9, and verification to A10. §17 names
every deferral with the condition that fires it. In particular this decision writes no
`GoalStatus.ACHIEVED` (A10's, ADR-0249 §4), no `GoalStatus.BLOCKED` (**A3's**, by ADR-0249
§4's own words), no `AttemptOutcome` member (A10's), no `AttemptEffort` figure (A3's), and no
`AttemptState.CANCELLED` (A9's).

## Decision

### 1. Focus is a timestamp, it has one writer, and exactly four acts move it

> **Normative.** A goal is **open** where its `GoalStatus` is `ACTIVE` or `BLOCKED`, and
> **closed** where it is `ACHIEVED` or `ABANDONED`. No lane reads a third state off the
> status, and **`BLOCKED` is open** because ADR-0249 §4 defines it as *"this objective
> cannot **currently** be achieved"* — a goal nobody has given up on and the kind a user
> most often comes back to.

> **Normative.** The **focused goal of a conversation** is the open goal of that
> conversation's candidate set (§2) with the **greatest `last_engaged_at`**, with the
> **`goal_id` ascending as the tie-break**, and a goal whose `last_engaged_at` is absent
> sorts **after** every goal carrying one and is never the focused goal while another
> candidate is open. A conversation whose candidate set holds no open goal **has no
> focused goal**, and no lane substitutes a closed one.

> **Normative.** **Focus is derived on every read and is stored nowhere.** No field, no
> row, no column and no in-process value names "the focused goal"; no act sets focus
> directly; and no surface, adapter or model may assert one this rule does not produce.

> **Normative.** **`Goal.last_engaged_at` and `Goal.last_engaged_in` have exactly one
> writer, `PlanStore.engage_goal` (§9), called by `orchestration` from the injected clock
> and the turn's conversation.** No other store member writes either — `save_goal`,
> `record_interpretation`, `open_attempt` and `commit_attempt` each leave both exactly as
> they found them — and no model output, no planner envelope and no interface adapter
> reaches them.

> **Normative.** **Exactly four acts engage a goal, and nothing else does.**
>
> 1. A **turn that associates to it** under §3, including the turn that opens it.
> 2. A **turn answering that goal's `GoalQuestion`** — a turn whose `TurnReference` names
>    the question (§10), whatever the question's disposition.
> 3. A **resumed park of that goal**: `AssistantEngine.resume` answering a `ParkedRead`
>    whose `goal_id` names it (ADR-0249 §11), on the path that dispatches.
> 4. A **resumed step of that goal**: `AssistantEngine.resume` answering a parked
>    confirmation whose execution's plan carries that `goal_id`.

> **Normative.** **Nothing else moves either field.** Not a listing, not an export, not a
> retrieval, not a candidate-set read, not a question expiring, not a question being
> withdrawn, not an attempt ending, not a reconsideration, not a migration, and not a turn
> whose association came back `UNDECIDED` (§3) — a turn that asked **which** goal has
> engaged none of them, and stamping the candidates would reorder the very set the next
> turn's question is asked over.

> **Normative.** `Goal.last_engaged_in` is an `Identifier | None` naming the conversation
> of the goal's **most recent** engagement. **`Goal.conversation_id` is never rewritten**:
> it stays the conversation the goal was opened in, which is ADR-0249 §1's provenance
> clause binding entire. `None` is reachable by exactly one route — a row written before
> this decision — and **no lane writes `None` into it**, which is ADR-0249 §1's
> four-absences posture extended to a fifth field for its own stated reason.

**A timestamp rather than a pointer, in ADR-0074 §2's own words for the same question.**
That section chose a per-record activity instant over a key defined only for some records
because *"the sort key is always present and the order is total with no fallback rule to get
wrong — the alternative, a key defined only for conversations that have turns, is exactly
where two conforming stores answer the same page differently."* A mutable "the focused one"
field is worse than that alternative: it is a second authority two concurrent turns can race,
and a race it loses leaves a conversation pointing at a goal neither turn engaged. A
timestamp each turn writes on **its own** row cannot disagree with itself, and the derivation
is the same one every reader computes.

**And the tie-break is named for ADR-0074 §2's stated reason, not for tidiness.** Its listing
is ordered *"by **last activity** descending with the id as tie-break"* because *"some total
order must be named or two implementations answer the same page differently"*. Two goals
engaged in the same instant is reachable — a clock with millisecond resolution and a turn
that engages two goals is not, but a migrated pair carrying no instant at all is — so the
order is stated rather than left to a store's row order.

**The absent instant sorts last rather than first, and that is the conservative direction.**
A migrated goal carries no `last_engaged_at` (ADR-0249 §1), and sorting it first would make
the oldest, least-touched objective in the store the focused goal of every conversation that
holds one. Sorting it last makes it exactly what it is: reachable, still a candidate,
and not what this conversation was most recently about.

**Why an `UNDECIDED` association engages nothing, stated because the opposite is tempting.**
A turn that asks *"which of these did you mean?"* has not decided, and stamping the
candidates it asked about would move them all to the head of the order — so the answer turn's
candidate set would be ordered by the asking rather than by the user's own history, and a
capped set (§2) could evict a goal the user is about to name. The question is asked over the
order that existed when the ambiguity arose, and stays asked over it.

### 2. The candidate set: what is in it, how it is ordered, and the cap it discloses

> **Normative.** The **candidate set of a conversation `C`** is every goal whose
> `conversation_id` is `C` **or** whose `last_engaged_in` is `C`, open or closed alike,
> ordered by §1's key, truncated to `MAX_ASSOCIATION_CANDIDATES`, and carrying the count
> of goals the truncation dropped. It is read through
> `PlanStore.candidates_for` (§9) and assembled by no other route.

> **Normative.** `core/types.py` gains **`MAX_ASSOCIATION_CANDIDATES`, a fixed constant
> valued 8**. It is not a `Settings` field, not a constructor knob and not a
> per-deployment value, exactly as `MAX_GOAL_INTERPRETATIONS` (ADR-0249 §2) and
> `MAX_TOPICS_PER_PROPOSAL` (ADR-0213 §4) are not.

> **Normative.** `core/types.py` gains **`GoalCandidates`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `goals`, a `tuple[Goal, ...]` of at most
> `MAX_ASSOCIATION_CANDIDATES` elements in §1's order; and `elided`, an `int` `ge=0`
> carrying **how many goals of the set the cap dropped**. It is a count and never an
> identifier, and a store that cannot count them does not answer `0`.

> **Normative.** **The elision is disclosed and never silent.** `elided` is rendered to
> the associator on the candidacy (§4), and where it is non-zero and the association came
> back `UNDECIDED` or `FRESH`, the reply says that older goals were not considered and
> that one can be named directly (§14). **No lane raises the cap to avoid disclosing an
> elision**, and none renders the dropped goals.

> **Normative.** **A closed goal is a candidate while the conversation that reaches it is
> retained, and this decision mints no timer of its own.** A goal is absent from the set
> of a conversation that is stamped deleted or has been reclaimed (ADR-0074 §8), because
> no turn runs in such a conversation at all. **No `Settings` field, no window and no
> deadline bounds how long a goal is reopenable**, and `PlanStore.delete_goal` is the one
> act that removes a goal.

**This is decision 4 implemented, and what it costs is stated rather than hidden.** The
owner ruled *"Reopening is allowed while the goal and its applicable history remain retained;
no separate timer."* The goal row and its whole interpretation chain live in the `PlanStore`
and are reclaimed by nothing; the **history** — the episodes of the turns that built it —
lives in the memory store under ADR-0074 §7's finite `episode_retention`, and the
conversation record under §7's horizon. So the three retentions are genuinely different
horizons, and the honest statement is the one above: **the goal outlives its episodes**, a
goal reopened after its conversation's episodes expired is reopened with its understanding
intact and its transcript gone, and a goal whose conversation was deleted is unreachable
because the conversation is. ADR-0014 §1's *"a goal … **outlives any one conversation**"* is
satisfied by exactly that asymmetry, and a second timer over the goal row would be the
figure decision 4 refuses.

**Why the cap is 8 and why it is in `core`.** The set is rendered to a model as a labelled
list (§4), so it is bounded by what a person can be plausibly juggling in one conversation
rather than by what a prompt can hold; 8 is larger than any plausible count of live
objectives in one thread, and because the elision is disclosed rather than silent a
deployment that hits it learns that it did. ADR-0086 §1's reason for fixing its own bound in
`core` rather than in `Settings` applies unchanged: *"a knob that raises the ceiling is a
knob that re-opens it."*

**A count and not a flag, and ADR-0086 states the test that decides which.** That ADR carries
both markers and distinguishes them: *"`details_elided` marks a loss whose size the *client*
cannot know, so a boolean is all that is honest there; this field marks a capacity decision
the *writer* made and can count."* The writer here is the store answering
`candidates_for`, which holds the whole set and can count what it did not return, so a flag
*"would discard a magnitude the writer holds"*.

**`last_engaged_in` is what makes decision 5 a resumption rather than a single borrowed
turn.** Without it a goal referenced from a second conversation would be associated to on
exactly the turn that named it and be invisible on the next, so *"make it Sunday"* the turn
after would find nothing. With it the goal is a candidate in the conversation that is now
working on it, and **nothing has been built that finds a goal in another conversation without
the user pointing at it once** — which is the boundary decision 5 draws (§13).

### 3. The association rule: a reply reference first, then one call, four dispositions

> **Normative.** **Every turn resolves its goal before it plans**, in this order, and the
> first step that answers is the answer.
>
> 1. **A `TurnReference` wins outright and costs no model call.** Where the turn carries
>    one (§10), it names a goal by a record **this system holds** — a `GoalQuestion`'s
>    `goal_id` or a `Goal`'s own id — and the turn associates to that goal.
> 2. **An empty candidate set opens a new goal, and costs no model call.** A conversation
>    whose candidate set is empty has nothing to associate to, and the turn opens a goal
>    carrying revision 1 by ADR-0249 §3.
> 3. **Otherwise exactly one `GoalAssociator.associate` call** is made over the labelled
>    candidate set (§4), and its verdict is dispositive in three ways and ambiguous in
>    one.

> **Normative.** **The label of the candidate at 1-based index *n* of the candidacy is the
> ASCII string `G` followed by *n* in decimal with no padding.** That is the whole of the
> scheme, it is the same on both sides of the seam, both sides derive it from the value
> they hold and neither consults the other, and **no label survives the call that rendered
> it and none is persisted as a reference.** It is ADR-0226 §3's scheme applied to a
> fourth sequence, and `G` collides with none of `M` (ADR-0226 §3) or `C`/`S`/`D`
> (ADR-0249 §9).

> **Normative.** **The four dispositions.** `orchestration` resolves the verdict and the
> labels it came back with, and takes exactly one of these:
>
> - **`ASSOCIATES` whose one label resolves** → the turn associates to that goal.
> - **`FRESH`** → the turn opens a new goal (ADR-0249 §3).
> - **`CONTINUES`** → the turn associates to the **focused** goal (§1). Where the
>   conversation has no focused goal the turn opens a new goal instead.
> - **`UNDECIDED`** → the turn **asks which goal it is about** and associates to none. It
>   opens no goal, records no revision, engages nothing (§1), drives no plan and produces
>   no effect.

> **Normative.** **A label that resolves to nothing is `UNDECIDED` and never a pick.** A
> string that does not match the form, an *n* below 1 or beyond the candidacy's length, and
> an `ASSOCIATES` carrying other than exactly one label are each treated as `UNDECIDED` and
> the turn asks. **No implementation falls back to the focused goal, to the first
> candidate, to the most recent one, or to any tie-break at all**, because every one of
> those picks a goal the model did not name.

> **Normative.** **The turn never picks between two goals and never rewrites one
> silently.** Where two or more goals are named, the answer is the ask. This is #2255's
> own prohibition read at this seam, and §5 is the second half of it.

**Why the ask rather than a tie-break, in the case the tie-break would get wrong.** Two
labels come back exactly when the user has two live things one sentence could belong to,
which is when they are most likely to be switching between them. A recency tie-break would
then revise the goal they were **not** talking about, and the first they would learn of it is
a later turn planning against an objective that acquired a constraint from another one. The
cost of asking is one sentence; the cost of picking is a goal whose interpretation chain now
contains a revision nobody made.

**Why one candidate still costs a call, stated because the cheap path is tempting and
wrong.** It is tempting to rule that a conversation holding exactly one candidate associates
to it without asking anything. It would be wrong: *"What is two plus two?"* asked in a
conversation whose one live goal is a campsite booking would then be recorded as a revision
of that booking's understanding, which is precisely the silent rewrite the clause above
forbids. Distinguishing a fresh request from a continuation is a judgement about meaning, and
ADR-0249 §7 puts judgements about meaning on the model's side of the line — *"A model may
interpret meaning, resolve a reference … **A model may never clear a permission, a coverage
test, a prerequisite or a dependency**"*. Associating is interpretation, so it is bought.

**So the cost is one model call per turn on a conversation that holds a candidate, and it is
stated rather than buried.** A conversation's **first** turn costs nothing new — its
candidate set is empty, which is ADR-0249 §16 arm 1's own case, so *"What is two plus two?"*
on a fresh conversation is still one `Planner.plan` call and one composing call. A turn
carrying a reply reference costs nothing new. Every other turn of a conversation that has
ever opened a goal pays one additional call, over a prompt bounded by the cap: at most eight
outcome statements, eight statuses and the request. That is the price of the property the
whole section exists for, and the alternative priced against it — a heuristic — buys a
cheaper turn by making a wrong association undetectable.

**What the `UNDECIDED` turn is, precisely.** It is an ordinary turn whose reply is a
question about **which objective**, not a `GoalQuestion`: nothing durable is written, no
attempt moves, no goal is engaged, and the user's next turn is associated by this same rule
over the same set. A `GoalQuestion` (§8) is bound to a goal, and a turn that could not find a
goal has none to bind one to. The two are different questions and this decision keeps them
apart.

### 4. `GoalAssociator`: one seam, one member, one value, and it is not a `Planner.plan` call

> **Normative.** `core/protocols.py` gains **`GoalAssociator`**, a Protocol with **exactly
> one member and no more**:
>
> ```python
> class GoalAssociator(Protocol):
>     async def associate(self, candidacy: GoalCandidacy, /) -> GoalAssociation: ...
> ```
>
> The parameter is **positional-only and is the only one**, there is **no second member**,
> and an implementation holds a `ModelProvider` and **nothing else that reads** — not a
> `MemoryStore`, not a `PlanStore`, not a `ConversationStore`, not a `ContextProvider` and
> not any other. It lives in `ai_assistant.planning` and is reached by `orchestration`
> **through this Protocol and by no other route**. This is a **BREAKING** contract change
> under golden rule 5.

> **Normative.** `core/types.py` gains **`GoalCandidacy`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `request`, an `EncodableText` carrying the
> turn's own request as ADR-0248 §1 carries it; `candidates`, a **non-empty**
> `tuple[CandidateGoal, ...]` of at most `MAX_ASSOCIATION_CANDIDATES` elements in §1's
> order; `elided`, an `int` `ge=0`; and `focused`, an `EncodableText | None` carrying the
> **label** of the focused candidate, absent where the conversation has no focused goal.

> **Normative.** `core/types.py` gains **`CandidateGoal`**, a frozen model with
> `extra="forbid"` carrying exactly `outcome` (a `NonBlankEncodableText`) and `status` (a
> `GoalStatus`).

> **Normative.** **A `GoalCandidacy` carries no identifier of any kind** — no `goal_id`, no
> `conversation_id`, no attempt id, no evidence id, no record id — and no instant, no
> revision number, no element, no ground, no plan, no effort figure and no authority. The
> containment is a property of the type: an implementation that rendered every field of
> every value it was handed, logged them all, or returned them, discloses none of those,
> because there is none on the value to disclose.

> **Normative.** `core/types.py` gains **`GoalAssociation`**, a frozen model with
> `extra="forbid"` carrying exactly `verdict` (an `AssociationVerdict`) and `labels` (a
> possibly-empty `tuple[EncodableText, ...]`). A **model validator** refuses every shape
> but four: `ASSOCIATES` with **exactly one** label; `FRESH` with none; `CONTINUES` with
> none; and `UNDECIDED` with any number, including none.

> **Normative.** **`AssociationVerdict`** is a `StrEnum` valued by lower-cased member name
> and **closed at exactly four members**: `ASSOCIATES`, `FRESH`, `CONTINUES` and
> `UNDECIDED`. The vocabulary is added to and never renamed, on `ReadKind`'s own rule
> (ADR-0226 §4).

> **Normative.** **`UNDECIDED` is the decline, and it is asserted rather than empty.** A
> model that will not choose says so by returning it; **an implementation that cannot parse
> its model's answer returns `UNDECIDED` and never a guess**, and no implementation reads
> an unparseable answer as `FRESH`, as `CONTINUES`, or as an error that fails the turn.

> **Normative.** **`orchestration` resolves every label and the implementation resolves
> none.** The associator renders each candidate's label from the tuple it was given; the
> loop resolves a label by parsing *n* and indexing **the very tuple it passed on this
> call**. No mapping, table or identifier crosses between `planning` and `orchestration`,
> and neither package imports a name from the other to agree on one.

> **Normative.** **This is not a `Planner.plan` call, and ADR-0228 §3's bound is
> untouched.** That section rules that *"A turn makes **at most two** calls to
> `Planner.plan`"*; an `associate` call is a call to a different Protocol with a different
> value and a different answer, so the figure two is neither read, raised nor made
> configurable here. **A turn makes at most one `associate` call**, and no lane of this
> decision makes a second, retries one, or re-asks on a different prompt.

**A single-member Protocol holding a `ModelProvider` is not a new mechanism; it is
`QueryComposer`'s, applied to a second judgement.** That Protocol's own docstring states the
shape this section copies: *"The parameter stays positional-only and stays the only one, this
stays a single-member Protocol … no keyword, no second member, and no constructor dependency
on a store seam … A composer holds a `ModelProvider` and nothing else that reads, lives in
`ai_assistant.planning`, and is reached by `orchestration` through this Protocol and by no
other route."* Every reason it gives holds here word for word, and the one that decides the
shape is ADR-0238 §2's: *"Three parameters would put the bound back in the caller's hands one
member at a time — a supply site that passed the right records would be conforming and one
that passed the wrong ones would be a defect nobody could see from the signature. One value
names the whole of what a composition may draw on in a place a reviewer reads once."*

**And the association cannot ride the planner's envelope, which is the argument against the
cheaper-looking design.** `Planner.plan` takes a `GoalBrief` as its first positional parameter
(ADR-0249 §7), and a brief is *"projected from the goal's current interpretation alone"*
(§9) — so calling the planner requires already knowing **which** goal. A design that asked the
planner to associate would have to hand it every candidate's brief, which is the containment
ADR-0230 §4 and ADR-0249 §9 bought being given back, and would then have to decide what
`ActionPlan.goal_id` meant on the way in. The circularity is structural, not incidental: the
association is what makes the brief, so it precedes the call that consumes one.

**Why the label discipline and not a goal id.** ADR-0228 §8 binds every call of every turn:
*"**no record identifier is rendered to a model and none is accepted from one**, no label
survives the call that rendered it, and no label is persisted as a reference."* ADR-0226 §3's
reason for the scheme is exactly the property wanted here — *"the resolvable set is exactly
what the loop chose to render, so the widest possible abuse of the mechanism is asking for
something already on screen"* — and the worst a label a model invents can do is name a
candidate index that is not there, which §3 turns into an ask.

**`goal_id` is absent from the candidacy where it is present on the brief, and the difference
is real.** ADR-0249 §9 keeps `goal_id` on `GoalBrief` because *"it names the subject of the
call rather than a record in the labelled supply"* and because `Engine._check_plan_is_for_goal`
compares the plan's id against it. A candidacy has no subject yet — deciding the subject is
the call — and nothing downstream compares anything against a candidacy, so the field would be
a record identifier with no work to do.

**`UNDECIDED` as an asserted decline is ADR-0176 §1's shape.** That decision refused to let an
empty answer stand for a decline, making the decline *"a second legal envelope shape"* carried
by an explicit marker, because an empty result and a refusal to choose are different facts and
an implementation that conflated them would drive on the wrong one. The same is true here with
the same consequence: a parse failure read as `FRESH` would open a duplicate goal on every
turn a model's answer was malformed, and a parse failure read as `CONTINUES` would revise the
focused goal on the strength of nothing at all.

### 5. What the reply says: an announcement for a resumption or a revision, and silence otherwise

> **Normative.** `TurnOutcome` gains **`goal_engagement: GoalEngagement | None`**,
> defaulting to `None`, carrying what this turn did with a goal. It is `None` on an outcome
> that engaged none — a routed operation (ADR-0197 §7), a restated settled binding
> (ADR-0198 §1), and the `UNDECIDED` turn of §3, which engaged nothing by §1.

> **Normative.** `core/types.py` gains **`GoalEngagement`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `disposition`, an `EngagementDisposition`;
> `outcome`, a `NonBlankEncodableText` carrying the engaged goal's **current outcome
> statement**; `revised`, a `bool`; and `reference`, a `ReferenceOutcome | None` (§10).
> It carries **no goal id, no attempt id, no revision number, no element, no ground and no
> instant.**

> **Normative.** **`EngagementDisposition`** is a `StrEnum` valued by lower-cased member
> name and **closed at exactly four members**: `OPENED` — a goal this turn opened;
> `CONTINUED` — the focused goal; `RESUMED` — an open goal that was **not** the focused
> goal; and `REOPENED` — a closed goal, whose status this turn moved to `ACTIVE` (§12).
> The vocabulary is added to and never renamed.

> **Normative — decision 6, as a rule rather than a judgement.** **A reply carries one
> sentence naming the goal it is about where, and only where, the `disposition` is
> `RESUMED` or `REOPENED`, or `revised` is `True`.** A turn whose disposition is `OPENED`
> or `CONTINUED` with `revised` `False` says nothing about goals at all: an ordinary topic
> change and an ordinary continuation each need neither an announcement nor a
> confirmation.

> **Normative.** **A revision is never silent.** Where `revised` is `True` the sentence
> states the **revised understanding** — the goal's `outcome` as this turn recorded it —
> and not merely that something changed. That is the real safeguard against a wrong
> association: the user sees what the assistant now thinks they asked for, on the turn it
> changed.

> **Normative.** **Nothing is confirmed and nothing is asked.** The sentence is a
> statement in a reply the turn was composing anyway. No lane turns it into a confirmation,
> a park, a question, a second turn or an interruption, and **a turn is never held waiting
> for the user to acknowledge it.**

> **Normative.** **The sentence is composed by `orchestration` from the typed value and by
> no model's decision.** No model is asked whether to announce, no envelope carries an
> announcement flag, and no interface adapter computes one: a surface renders what
> `goal_engagement` says, on ADR-0242 §9's rendering-is-presentation ground.

**This is decision 6 turned into two conditions a reviewer can check.** The owner ruled
*"Meaningful resumptions or revisions of ongoing work are briefly announced. Ordinary topic
changes need neither announcement nor confirmation."* "Meaningful" is not a judgement any
implementation could apply consistently, so it is read as the two facts that make a turn
meaningful in the sense the rule is about: the turn moved to a goal the conversation was not
on, or the turn changed what the system understands. Both are typed facts the loop already
holds at composition time, neither is a model's opinion, and the second is the one a silent
failure would hide.

**`CONTINUED` is silent because announcing it would be noise on every turn.** A user
adding a constraint to the thing they have been discussing for six turns does not need to be
told which goal it is; told every time, the sentence stops being read, which is the failure
that makes the `RESUMED` case worth announcing.

**One member and not three, on ADR-0244 §9's own reasoning.** That section put two facts on
`TurnOutcome` as *"one `None`-defaulting member per fact"* and refused to collapse them
because they would have made *"one field a `Confirmation` on one path and an enum on another,
which is a union a client must discriminate before it can render either"*. Here the
disposition, the outcome statement, whether a revision happened and what became of a reference
are four facets of **one** fact — what this turn did with a goal — and a client renders them
together or not at all, so they are one model with four fields rather than four optional
members a client must correlate. The clarification (§9) is a **second** fact, on a separate
member, because a turn can raise one without engaging a goal it also revised.

**ADR-0244 §9's own two members and their validator are untouched.** `read_confirmation` and
`read_answer` keep their names, their types, their defaults, their mutual exclusion and their
precedence; `goal_engagement` is outside that validator and enters no clause of it, so a
reader holding only ADR-0244 §9 implements exactly what it says and is not wrong about
anything (§18).

### 6. Materiality is code's, and a question is asked under three conditions and no fewer

> **Normative.** **A question is put to the user only where all three of the following
> hold**, and no implementation asks on fewer, on a setting, on a deployment flag, on a
> confidence figure, or on a model saying it would like to ask.
>
> 1. **The planner reported the interpretation ambiguous** — it returned a
>    `ProposedQuestion` (§7) on this call.
> 2. **The subject that question names is material**, by the test below, which is code's
>    and is never taken on the model's word.
> 3. **No evidence or established preference resolved it** — the planner raised the
>    question having been given this turn's supply, so a question it still raises is one
>    the supply did not resolve for it.

> **Normative — the materiality test, and it is the whole of it.** A question's subject is
> **material** where either limb holds:
>
> - **By kind.** The subject is the interpretation's **outcome**, or an element of its
>   `criteria` or its `conditions`. A success criterion is what decides whether the goal
>   was met and a condition is what decides whether to act at all, so an ambiguity in
>   either changes the answer to a question the system will have to answer.
> - **By consequence.** The `ActionPlan` the **same** `PlannerOutput` carries proposes at
>   least one step whose capability the `ToolRegistry` declares
>   `ToolDefinition.side_effecting`. A turn about to change something outside itself is a
>   turn whose every understood element is material.
>
> A subject that is an element of `constraints` on a turn proposing no side-effecting step
> is **not** material, and the question is dropped: a constraint bounds an action, and with
> no action proposed there is nothing this turn for it to bound.

> **Normative.** **The registry read is the loop's, over the plan's own declared
> capabilities**, through the `ToolRegistry` `LearningLoop` already holds, and it is a read
> of a **declaration** — not of a risk level, not of a reversibility, not of a tier reach
> and not of a policy ruling. **No permission is consulted, cleared or implied by this
> test**, which is ADR-0249 §7's asymmetry binding: *"A model may never clear a permission,
> a coverage test, a prerequisite or a dependency."*

> **Normative.** **What is taken on the model's word is named.** Conditions 1 and 3 are the
> planner's report and this decision takes them as such: a model that wrongly reports an
> ambiguity costs one question, and a model that wrongly reports none costs an answer over
> a reading the user can correct on the next turn. **Neither condition can clear anything**
> — a model that reports no ambiguity does not thereby authorise an act, satisfy a
> prerequisite or establish coverage, and no lane reads the absence of a `ProposedQuestion`
> as any of the three.

> **Normative.** **A model never opens a question and never settles one.** It **raises**;
> the loop decides whether a raised question becomes a `GoalQuestion` (§9), and the loop
> alone settles one (§§10–11). No planner envelope carries a question id, a deadline, a
> disposition or a settlement, and any such value that comes back is **discarded
> silently** — not an error, not a park, not a degradation of the turn — which is ADR-0249
> §6's posture applied to this decision's fields for its own stated reason.

**Revision 0's rule is withdrawn and this is what replaces it, on #2255's addendum.** The
design report's earlier rule — that an `INFERRED` ground on a material element is itself
unresolved — is refuted by the addendum's own counterexample: *"your report treats every
material inferred element as unresolved; that causes unnecessary questions ('next weekend'
would ask every time)"*. "Next weekend" is an inference about a material element on every
turn that contains it, and asking about it every time is the interruption the acceptance table
counts against. So an inference is not by itself a question; **an ambiguity the model reported
about a material subject is.**

**Where this test departs from the design report, and why.** The report's condition 1 reads
*"the element is material by C.1's code test"*, and C.1's test is *"whether an element is
referenced by a success criterion, a constraint, or the parameters of a step whose capability
the registry declares side-effecting"*. Its middle limb is not buildable as code: "referenced
by" between two free-text strings is a substring match, which would call an element material
because a word recurred and not material because a synonym did — a test whose answers a
reviewer could not predict is not a code test, which is exactly what the addendum warns
against. So the limb that survives is the one that reads a **declaration** —
`side_effecting`, which the tree carries — and beside it the limb that reads **tuple
membership**, which needs no matching at all. Both are decidable by inspection of values the
loop already holds, which is what makes condition 2 code's.

**And the constraint case is the one this narrowing gives up, stated plainly.** A goal
carrying an ambiguous constraint on a turn that proposes no side-effecting step does not ask.
The cost is one answer composed under the wider of two readings of a bound that bounds
nothing this turn; the moment such a goal proposes an act, the second limb fires and the
question is asked before anything happens. That is the direction #2255 asks for in terms —
*"the assistant does not push through into a consequential action"* — and the opposite
direction would ask about a budget on a turn that only explained something.

**Condition 3 is the model's and is written down as the model's.** Before A4 there is no
evidence store to compare against and no typed standing for a preference, so nothing in the
system can mechanically establish that the supply failed to resolve an ambiguity. What is
true is narrower and is what the clause claims: the planner was handed this turn's memories
and its request, and it raised the question anyway. #2096 item 8's owner-ruled principle is
why relying on it is safe in this direction only — *"A model is a safe denier and an unsafe
allower, because of who rehearses against it: an attacker who beats a deny-only layer gains a
deny."*

### 7. `ProposedQuestion`: a raised question names what it is about

> **Normative.** `core/types.py` gains **`ProposedQuestion`**, a frozen model with
> `extra="forbid"` carrying exactly `text` (a `NonBlankEncodableText`, the question as the
> user would read it) and `about` (an `EncodableText | None`). It carries **no id, no
> deadline, no disposition, no goal id, no attempt id and no instant** — every one of those
> is `orchestration`'s (§6).

> **Normative.** **`ProposedUnderstanding.questions` becomes a
> `tuple[ProposedQuestion, ...]`**, possibly empty, and everything else ADR-0249 §7 says
> about the field is unchanged: it is carried on the envelope, it is the planner's to fill,
> and it is `orchestration`'s to read.

> **Normative — what `about` names.** `about` is a **label of the same
> `ProposedUnderstanding`'s own tuples**, spelled by ADR-0249 §9's scheme read over the
> proposal rather than over the brief: `C` followed by *n* for the element at 1-based index
> *n* of `constraints`, `S` followed by *n* for `criteria`, `D` followed by *n* for
> `conditions`. **`None` means the question is about the outcome**, which every
> understanding has.

> **Normative.** **A label outside the proposal's own tuples resolves to nothing and the
> question is dropped** — silently, without failing the turn, exactly as ADR-0249 §7 drops
> an element whose ground does not resolve. A label of a tuple other than the one it
> spells likewise resolves to nothing: the label space is per tuple.

> **Normative.** **`orchestration` resolves `about` to the proposed element it names and
> records that element's `text`**, not its label, on the `GoalQuestion` (§8). The label
> does not survive the call, and **no label is persisted as a reference**, which is
> ADR-0226 §3's cost clause binding here as it binds everywhere else.

> **Normative.** **Resolution happens over the proposal as it was received, before any
> element is dropped by ADR-0249 §7's ground resolution.** A question about an element
> whose ground did not resolve is itself **dropped**, because the element it is about is
> not in the recorded revision and a question about nothing is not a question.

> **Normative.** **At most one question is taken from a call.** Where several come back,
> the loop takes the **first in tuple order** whose `about` resolves and whose subject is
> material (§6), and drops every other, silently. The order is the tuple's and there is no
> ranking, no scoring and no second call to choose between them.

**This is the one place ADR-0249 is reopened, and the showing is why it had to be.** That
decision made `questions` a `tuple[NonBlankEncodableText, ...]` and said so for a stated
reason: the field *"rides the envelope … so that A2 need not reopen a `core` type to carry a
value the planner can already produce"*. The reason is sound and the field is kept; what a
bare text cannot do is answer **what the question is about**, and §6's materiality test is a
test over a subject. With no subject, condition 2 could only be a review convention — a
reviewer reading the question text and forming a view — which is exactly the shape #2255's
addendum rules out. So the element type gains one optional field and nothing else moves:
`questions` is still carried, still the planner's, still unread by any ADR-0249 lane, and
still projected onto no brief by that decision.

**It is additive at the seam and it is not additive at the type, which is why it is recorded
as a supersession.** A planner that returned bare strings would fail to construct a
`ProposedUnderstanding` after this decision, so ADR-0070 §1's test comes out on the
supersession side and §18 records it. The alternative considered and rejected was a **second**
member on `ProposedUnderstanding` carrying subjects parallel to the texts, which is one value
with two carriers and two ways to disagree — the shape ADR-0249 §9 already refused when it
declined the design report's separate `questions` keyword beside the brief's own field.

**Why the label space is the proposal's and not the brief's.** A question is raised **about
the understanding the planner is proposing**, which is frequently about an element that is not
in the brief at all — the campsite element the model just added, the reading of "dry" it is
proposing. Labelling against the brief would leave exactly those unnameable, and labelling
against both would give one spelling two meanings on one call. The proposal's own tuples are
the set the model is looking at when it raises the question, which is ADR-0226 §3's rule
applied honestly: *"the resolvable set is exactly what the loop chose to render"* becomes, at
this one seam, exactly what the model chose to propose — and the loop still resolves, still
drops what does not resolve, and still persists no label.

### 8. `GoalQuestion`: the record, and the one open question per goal

> **Normative.** `core/types.py` gains **`GoalQuestion`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `id`, an `Identifier`; `goal_id`, an
> `Identifier`; `attempt_id`, an `Identifier`; `text`, a `NonBlankEncodableText | None`;
> `about`, a `NonBlankEncodableText | None`; `asked_at`, a `UtcInstant`; `expires_at`, a
> `UtcInstant`; `disposition`, a `GoalQuestionDisposition`; and `settled_at`, a
> `UtcInstant | None`.

> **Normative.** **`text` and `about` are the two content fields**; `id`, `goal_id`,
> `attempt_id`, `asked_at`, `expires_at`, `disposition` and `settled_at` are facts. A
> **model validator** refuses every shape but two: an `OPEN` question carrying both content
> fields and no `settled_at`, and a terminal question carrying neither content field and a
> `settled_at`.

> **Normative.** **A settled question keeps its facts and loses its content.** `settle_question`
> clears `text` and `about` **in the same step that moves the disposition**, and no
> implementation retains a copy, a digest, a snapshot or an archive of either. **The
> content lives exactly as long as the question does**, which is ADR-0244 §3's retention
> rule applied here for its own reason, and `goal_id` **survives settlement** so that a
> late answer still reaches the goal (§11).

> **Normative.** **`GoalQuestionDisposition`** is a `StrEnum` valued by lower-cased member
> name and **closed at exactly five members**: `OPEN`, `ANSWERED`, `WITHDRAWN`, `EXPIRED`
> and `SUPERSEDED`. The four terminal members are distinct acts with distinct meanings and
> **no implementation treats any as a weaker form of another**. The vocabulary is added to
> and never renamed.

> **Normative.** **A goal holds at most one `OPEN` question.** `PlanStore.record_question`
> enforces it, the read of the existing question and the write are **one indivisible
> step**, and the enforcement is the store's rather than a caller's — two turns of one
> conversation, two conversations engaging one goal, and two engines over one data
> directory can none of them open a second question on the same goal.

> **Normative — the genuine constraint, named as the standing rule requires.** The
> restriction is kept because **two outstanding questions about one objective have no order
> and answering either changes what the other means**: a user asked which campsite and
> which weekend, answering the second, has answered a question whose first reading the
> first answer would have changed. That is a correctness constraint about a shared subject,
> not a storage convenience, and it is the same reason ADR-0244 §3 gives `settle` its
> resolve-once gate. **It is per goal and never per conversation**: a conversation may hold
> any number of paused goals, each with its own question.

> **Normative.** **Every question carries a deadline and there is no spelling for one
> without.** `core.config.Settings` gains exactly one field, **`goal_question_ttl:
> timedelta`**, required, defaulting to **PT72H**, refused at load where it is zero or
> negative, admitting **no disable sentinel**. `expires_at` is computed from it **once**, at
> the instant the question is written, and is never extended, refreshed or recomputed.

> **Normative.** **`GoalBrief.open_questions` carries at most one text** — the goal's open
> question's `text` where one stands, and nothing where none does. It carries no id, no
> subject, no deadline and no disposition, which is ADR-0249 §9's *"it carries **texts**"*
> clause binding entire. The planner is not asked to answer it and no implementation reads
> its presence as an instruction to answer, to re-raise, or to plan differently; it is
> there so that a planner does not raise a question the system is already asking.

**The store is `PlanStore`'s and not a store of its own, and ADR-0244's own argument is why
the two cases come apart.** That decision gave a parked read a store in `permissions/` because
*"a park is the unanswered half of a recorded permission question, joined to the trail by
`decision_id`"*, and ADR-0004 §7 charters that subsystem for gating access to Tier 0/1 data
*and recording it*. A `GoalQuestion` is joined to no decision, gates no access and records no
permission: it is an unanswered question about **what the user wants**, which is planning
state, and ADR-0014 §5 charters `PlanStore` for exactly that — *"Durable planning state:
goals, plans, and execution"*.

**And the deletion argument decides it even if the charter did not.** A question's life is its
goal's, and `PlanStore.delete_goal` is the one act that removes a goal, with ADR-0014 §5's
cascade and data-rights obligations already stated over it. A second store would put a goal's
questions behind a second deletion with no transaction between the two — which is precisely
the protocol ADR-0074 §8 had to **ratify** rather than leave to an implementer, and it
ratified it only because episodes and the conversation index genuinely live in two stores.
Here they need not, so a second store would buy a second cross-store deletion protocol and
nothing else. ADR-0238 §8's counter-argument does not reach either way: a question, like a
park, *"has all four"* of a terminal event, a deadline, an enumeration and a key, so it is
rediscoverable wherever it lives — which means the choice is decided by the charter and the
cascade rather than by recoverability.

**PT72H rather than PT24H, and the two reasons are different from ADR-0244's.** A park's
24-hour deadline bounds a durable row holding the **exact query** that would leave the device,
which is the most sensitive content in that decision; a question holds the system's statement
of an objective the goal already carries, so the deadline is not protecting content the goal
does not also hold. What it **is** doing is bounding how long one goal's single question slot
stays occupied, and three days is the interval over which *"I will get back to it"* is the
normal case rather than an abandonment — it spans a weekend, which is the shape of the
worked example this whole batch is written around. The no-disable rule is kept for both of
ADR-0244 §3's reasons and one of this decision's own: *"a park nothing can free is a durable
row holding Tier 1 content that no act, no enumeration and no reclaim would ever reach"*, and
here a question nothing can free would block that goal's next question **forever**, which is
the one-open rule turning from a correctness constraint into a trap.

### 9. `PlanStore` gains seven members, and this is a BREAKING contract change

> **Normative.** `PlanStore` gains the following members, and this is a **BREAKING**
> contract change under golden rule 5, layering on ADR-0249 §12's widening of the same
> Protocol:
>
> - `async def engage_goal(self, goal_id: str, /, *, at: UtcInstant, conversation_id: str,
>   expected_version: int) -> Goal` — stamps `last_engaged_at` and `last_engaged_in`,
>   advances `version`, and returns the goal as written. It refuses on a stale
>   `expected_version` with ADR-0014 §5's stale-write error class, and it writes **nothing
>   else**: not the status, not the interpretation, not the attempt.
> - `async def candidates_for(self, conversation_id: str, /, *, limit: int) -> GoalCandidates`
>   — §2's set for that conversation, in §1's order, truncated to `limit`, with `elided`
>   counting what the truncation dropped.
> - `async def record_question(self, question: GoalQuestion, /) -> bool` — writes an `OPEN`
>   question, or answers `False` where that **goal** already holds one. The read of the
>   existing question and the write are **one indivisible step**.
> - `async def get_question(self, question_id: str, /) -> GoalQuestion | None`.
> - `async def open_question(self, goal_id: str, /) -> GoalQuestion | None` — that goal's
>   open question, or `None`.
> - `async def outstanding_questions(self) -> tuple[GoalQuestion, ...]` — every `OPEN`
>   question, in `asked_at` order.
> - `async def settle_question(self, question_id: str, /, *, disposition:
>   GoalQuestionDisposition, at: UtcInstant) -> bool` — moves an `OPEN` question to a
>   terminal member and **clears `text` and `about` in the same step**, answering `True` to
>   the caller that moved it and `False` to every other. The read, the comparison and the
>   write are one indivisible step, and `settle_question` on an already-terminal question
>   answers `False` and changes nothing.

> **Normative.** **`settle_question` is the resolve-once gate.** No lane reads a question,
> decides, and writes back; no lane acts on an answer before `settle_question` has answered
> `True` for it; and a caller that lost the compare-and-swap records nothing, revises
> nothing and reports the settled state. That is ADR-0244 §3's gate at the seam a goal has
> instead of a decision.

> **Normative.** **`delete_goal` removes that goal's questions, open and terminal alike**,
> and `GoalDeletion` reports them exactly as ADR-0249 §12 has it report attempts. An open
> question does not block a deletion, on ADR-0073 §5's ruling that *"the store deletes what
> it is told to delete"*.

> **Normative.** **`PlanExport` gains `questions: tuple[GoalQuestion, ...]`** and its
> `schema_version` annotation is edited to the next literal, exactly as ADR-0249 §11 edited
> it rather than defaulting it. ADR-0014 §5's closure rule extends to `question_id`: an
> export naming a question it does not carry, or carrying a question whose `goal_id` or
> `attempt_id` it does not carry, does not validate as a `PlanExport` at all. **A settled
> question exports with its content already absent**, which is the retention rule (§8) and
> not an omission from the export.

> **Normative.** **The store migration is the plan store's second**, from the version
> ADR-0249 §12 lands to the next, and it is table creation for the questions plus the two
> new `Goal` columns. ADR-0049 §1's `meta("schema_version")` marker is what it reads, and
> its loud refusal of a database *"whose `schema_version` is **newer** than the code
> understands"* binds entire. **A goal row written before this decision migrates with
> `last_engaged_in` absent** and no question rows, which is ADR-0249 §1's absence posture
> and the one route to a `None`.

> **Normative.** **Every one of the seven lands on both conforming implementations and in
> the shared `PlanStore` conformance suite, and the canonical fake in
> `ai_assistant.testing` gains them all.** A conformance suite that exercised one
> implementation would be a suite that lets the other disagree, which is what the shared
> suite exists to prevent.

**Why `engage_goal` is a member rather than a stamp folded into the writes that already
exist.** A turn that associates to a goal and records **no** revision — a continuation that
adds nothing to the understanding — still engaged it, and there is no other write on that
path to carry the stamp. Folding it into `record_interpretation` would leave focus unmoved on
exactly the turns a user would be most surprised to find it unmoved on, and folding it into
`commit_attempt` would make an attempt transition a focus event, which §1 says it is not. One
member with one writer is also what makes §1's *"exactly one writer"* clause checkable rather
than a convention spread over four call sites.

**And it takes `expected_version` because everything on a goal does.** ADR-0249 §1 makes
`version` *"the **compare-and-swap** token every mutation of the goal advances"*, and a stamp
that skipped it would be the one mutation two concurrent turns could interleave — which is
ADR-0014 §5's own argument for the token: *"Optimistic concurrency turns that into a
detectable, retryable failure, and it belongs to the store because the store is the only place
with a total order over writes."*

### 10. Raising a question: what the turn returns, what it does not do, and a refused write

> **Normative.** `TurnOutcome` gains **`clarification: Clarification | None`**, defaulting
> to `None`, carrying the question **this turn raised**, so that the question appears in the
> exchange that raised it. It is `None` on every turn that raised none.

> **Normative.** `core/types.py` gains **`Clarification`**, a frozen model with
> `extra="forbid"` carrying exactly `question_id` (an `Identifier`), `text` (a
> `NonBlankEncodableText`) and `expires_at` (a `UtcInstant`). It carries **no goal id, no
> attempt id, no subject and no disposition**: the subject is what the question text is
> about and the user reads it there, and the goal is what `goal_engagement` names.

> **Normative.** **The turn that raises a question does not park.** It composes, its
> answer *is* the question, and it returns. ADR-0226 §5 binds entire — no implementation
> *"raises out of the turn, parks **it**, or puts a question to the user on account of a
> read that did not land"* — and this decision obeys it rather than moving it, because
> **what pauses is the goal's attempt**, not the turn.

> **Normative.** **A turn that raised a question drives no step of its plan and produces no
> effect.** The plan is persisted exactly as ADR-0228 §5 and ADR-0249 §11 already have it
> persisted; it is not driven, no execution is started, and no `ToolCall` is constructed.

> **Normative.** **The attempt's state becomes `AWAITING_CLARIFICATION` and its phase does
> not move.** ADR-0249 §6's rule that a phase *"advances in that order and never moves
> backwards"* is obeyed by leaving the phase exactly where the turn left it: a question is
> a pause, not a retreat, and the attempt resumes at the phase it stood (§11).

> **Normative.** **A question exists only where the store accepted it.** Where
> `record_question` answered `False` — that goal already holds an open question — or raised,
> **no question exists**: `clarification` is `None`, the attempt's state is **not** moved,
> and nothing durable is outstanding. **A lane that reported a question it did not write
> would tell the user to answer a question nothing holds**, which is ADR-0244 §1's clause
> read at this seam.

> **Normative.** **The turn still declines to act in that case.** The decision not to drive
> a side-effecting step was taken on the ambiguity and not on the write, so a turn whose
> question the store refused drives no step either. Its reply still states the ambiguity;
> what is missing is a durable question to answer, and the user's next turn is associated by
> §3 like any other.

> **Normative.** **No notification is minted, on any path of this decision.** No lane
> produces a `NotificationCandidate`, calls `NotificationPolicy`, writes a
> `NotificationStore` row, or reaches ADR-0130's chassis at all — not when a question is
> raised, not when one expires, not when one is superseded, and not when a goal is paused.

**Why the outcome member rather than a sentence woven into the composed reply.** The reply is
composed by the loop and the question is written by `Engine` at the one persistence site
(ADR-0228 §5, ADR-0249 §11), so a reply that named a question id would be asserting a record
the write had not yet made. Putting the question on `TurnOutcome` is ADR-0244 §9's own
shape — *"`read_confirmation`… the confirmation for a read **this turn parked**, so the
question appears in the exchange that raised it"* — and it makes the failure mode honest: the
member is set by the site that knows the write succeeded, and a refused write produces an
outcome that says no question stands, rather than a reply that says one does.

**And this is the reason no notification is minted, which is not the reason the design report
gave.** The report grounded decision 1's *"no notification by default"* on an unanswered
question not being perishable. That is **false** of this record: §8 gives every question a
required `expires_at`, so it would satisfy ADR-0130 §5's *"it declares an expiry later than
the ruling instant"* — the very condition that section makes the whole of the escalation test.
The honest ground is the one above: **this decision builds no producer at all**, which is
ADR-0244 §10's posture in terms — *"no notification is minted for any of the three"*, resting
on ADR-0235 §8's *"a notification is a decision about interrupting the user and this ADR takes
none"*. A producer is a decision with its own ADR, its own class, its own reach level and its
own budget, and it is not made by inference from a deadline this decision added for a
different reason.

### 11. Answering: the reference, the settlement, and decision 3's rule for a late answer

> **Normative.** `AssistantEngine.converse` gains **one keyword parameter, `reference:
> TurnReference | None`, defaulting to `None`**, and `converse_streaming` gains it by
> ADR-0173's *"taking exactly `converse`'s arguments in exactly its"* order. No other
> operation gains it.

> **Normative.** `core/types.py` gains **`TurnReference`**, a frozen model with
> `extra="forbid"` carrying exactly `question_id` (an `Identifier | None`) and `goal_id`
> (an `Identifier | None`). A **model validator** admits exactly two shapes: a
> `question_id` and no `goal_id`, or a `goal_id` and no `question_id`. A shape a caller
> cannot reach is better refused by the type than documented, which is ADR-0244 §9's own
> reason for refusing its two members together.

> **Normative.** **A reference is never rendered to a model and never accepted from one.**
> It is resolved by `orchestration` against records this system holds; no candidacy, no
> brief and no prompt carries it or the goal id it resolves to. ADR-0228 §8's namer rule
> binds it entire.

> **Normative.** **The handle is the question's own durable `id` and needs no re-minting.**
> `GoalQuestion` is a row of a durable store, so a restart changes nothing about it:
> ADR-0052 §1's enumerate-and-re-mint path is **not** extended here, no handle table holds
> a question, and `pending_confirmations` gains nothing. That path exists because a parked
> step lives in a process-scoped table (ADR-0042 §4); a question does not.

> **Normative — what a `question_id` reference does, and it does it whatever the
> disposition.** `goal_id` survives settlement (§8), so the reference resolves to a goal in
> every case, and the turn **engages that goal** (§1). Then:
>
> - **`OPEN` and unexpired** → `settle_question` takes it `ANSWERED`; the attempt the
>   question names **resumes at the phase it stood** and its state moves from
>   `AWAITING_CLARIFICATION` to `RUNNING`. **No new attempt is opened** (§12).
> - **`OPEN` and past `expires_at`** → it is settled `EXPIRED` and **not** `ANSWERED`, by
>   the clause below; the turn proceeds as an ordinary engagement of the goal.
> - **terminal already** → nothing is settled and the turn proceeds as an ordinary
>   engagement of the goal.
> - **naming no question this store holds** → nothing is settled, nothing is engaged, and
>   the turn is associated by §3 like any other.

> **Normative.** **An answer that arrives after expiry reopens the work rather than
> vanishing**, and that is the whole of the mechanism: the question is gone, the **goal** is
> not, and a reference the user was given still names it. Where the goal's current attempt
> is terminal the turn opens a new one (§12); where it is not, the turn resumes it.

> **Normative.** `TurnOutcome.goal_engagement` carries **`reference: ReferenceOutcome |
> None`** saying which of the four happened. **`ReferenceOutcome`** is a `StrEnum` valued
> by lower-cased member name and **closed at exactly four members**, decided in this order,
> so that the answer is deterministic across implementations: **`UNKNOWN`** (no such
> question), **`EXPIRED`** (its deadline had passed, whether this turn settled it or an
> earlier read did), **`ALREADY_SETTLED`** (answered, withdrawn or superseded before this
> turn arrived), **`ANSWERED`** (this turn took it). The vocabulary is added to and never
> renamed.

> **Normative — decision 3, as the rule for a late answer.** After an answer the turn
> **briefly restates the understanding** — which is §5's revision sentence, owed here
> because an answer that changes nothing about the understanding is not an answer —
> **rechecks evidence and authorization, then proceeds**, and **asks only about remaining
> ambiguity or uncovered consequences**, which is §6's three conditions evaluated afresh on
> this turn and on nothing carried over.

> **Normative — what "recheck" means today, stated rather than promised.** Before A4 and A6
> land it has exactly two subjects, and both already exist: **(a)** the answering turn makes
> its **own** `Planner.plan` call over the brief of the revised interpretation, so no plan,
> no read, no supply and no judgement is carried over from the paused turn; and **(b)**
> every permission is taken at the instant of the act by the gates that already do so — a
> `CONFIRM` is put again, `EgressBinder.rebind` derives the binding afresh, and ADR-0231
> §6's pre-execution checks run at dispatch. **Nothing is carried forward from the paused
> turn and no lane treats the age of the pause as authority for anything.** A4 gives
> "recheck" an evidence standing to read and A6 gives it an authorization coverage to
> compare; until then this clause is the whole of it.

> **Normative.** **A restart changes nothing about an answer.** The question is durable, the
> attempt's `AWAITING_CLARIFICATION` is durable, the goal and its interpretation chain are
> durable, and the reference is a record id rather than a process-scoped handle. **There is
> no intermediate state a restart has to resolve** and no recovery protocol is added.

> **Normative — Q6.** **An unrelated request during a clarification is answered normally.**
> The paused goal keeps its open question and its `AWAITING_CLARIFICATION` attempt; the new
> turn opens or resumes another goal by §3; focus moves to the one the new turn engaged
> (§1). **No lane refuses a turn, opens a new conversation, blocks a new goal or defers a
> request on account of an outstanding clarification.** When the answer eventually arrives
> it reaches the right goal by the question's own `goal_id`, across intervening turns and
> across a restart.

**Answering is a turn and not an operation of its own, and that is the whole reason
`converse` gains a keyword rather than the surface gaining a fifth verb.** Decision 3 requires
the answer to restate the understanding, recheck and **proceed** — which is a planner call, a
supply, a composition and a reply, i.e. everything `converse` already is. A dedicated
`answer_clarification` would either duplicate that or call it, and the duplicate would be the
second turn path every later decision would then have to be stated over twice. The keyword
also makes the reference exactly what it is: a fact about **this** turn, beside its request,
which is where ADR-0248 §1 already put the request.

**Why a settled question still resolves to its goal.** ADR-0244 §10's argument for keeping a
settled park's facts applies here word for word: *"A row that vanished would make a duplicate
answer indistinguishable from a mistyped token"*, and ADR-0198's whole reason for restating a
settled binding is that *"the engine states what was decided rather than refusing to say"*.
Here it buys something further — the user who answers a day late is not told their answer was
too late and discarded; they are told the question expired and the work carries on, which is
decision 2 in terms: *"the goal stays resumable. Silence is neither refusal nor abandonment."*

**Why the answer resumes the attempt rather than opening one.** ADR-0249 §5 rules that *"an
attempt is opened only by a **user act**"* and leaves which acts to this decision. An answer
**is** a user act, so the rule permits either reading, and the deciding argument is what an
attempt is for: it is *"what was tried, once"*, carrying the phase, the effort ledger and the
ids of the plans, executions and authorizations of one try. A clarification does not end a
try; it interrupts one, and the work before the question — the reads taken, the plans made,
the authorizations obtained — is work of the **same** attempt. Opening a new one would reset
the phase to `UNDERSTAND`, orphan those references, and start a second effort ledger for one
continuous piece of work, which is exactly what ADR-0249 §5's *"no replan, branch or recovery
opens one"* is guarding.

**And the phase does not move backwards, which is what makes the pause expressible at all.**
ADR-0249 §6 forbids a backwards phase, and #2255 wants understanding to reopen. The two are
reconciled by the `state`: the attempt stands where it stood and stops being runnable, and the
answer's revision *"does not move the phase"* by §6's own clause — *"an understanding revised
during investigation advances the goal's `version`, which is what §8's stale-target rule keys
on, and leaves the attempt where it stood."* So the plan the paused turn made is stale by
construction the moment the answer is recorded, and §8's stale-target refusal is what stops it
being driven. **Nothing new enforces that**; the rule ADR-0249 already landed does.
