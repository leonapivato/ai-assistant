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
  ADR-0249 §12's record.** The roster gains eight members — `engage_goal`,
  `set_goal_status`, `candidates_for`, `record_question`, `get_question`, `open_question`,
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
- **Partially supersedes** [ADR-0170](0170-a-reply-is-not-a-tool-the-turn-composes-its-answer-and-the-outcome-carries-it.md)
  — **§4's `turn`-`None` enumeration, in its count alone.** The turn whose association came
  back `UNDECIDED` (§3) engaged no goal, took no relevance read, no episodic supplement and
  no `Planner.plan` call, so it has **no `TurnResult`** — a second shape beyond the
  recovered park on which `turn` is `None`, and a reader holding only §4 would refuse it.
  **This is ADR-0197 §8's move exactly**, that decision having admitted the first such shape:
  *"a `None` `turn` beside a non-`None` `routed` may carry a `reply`"*. **§4's `reply`
  enumeration does not move at all**: the undecided turn carries a reply, composed by
  `orchestration` from the typed value. §4's both-directions rule binds entire and the new
  shape is stated in both, `reply_degraded` stays `True` on the composition-failure shape
  **and on no other** and is never `True` where `turn` is `None`, §4's park clause, its
  recovered-park clause and its composition-failure clause are untouched, and §§1-3 and
  §§5-9 stand entire.
- **Partially supersedes** [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md)
  — **§1's thirty-operation enumeration alone, which gains `goals`,
  `withdraw_clarification` and `abandon_goal`.** This is ADR-0200's precedent exactly: that
  decision recorded against the same clause when it added `converse_spoken`. Nothing else in
  that ADR moves — §1's every-argument-the-browser-owns clause, its caller-owned-deadline
  class (which gains **no** member, because none of the three takes a turn budget), its
  `learn`-is-unreached clause and its single-principal clause bind entire, and §§2-13 are
  untouched.

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
>    the question (§11), whatever the question's disposition.
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

> **Normative.** **Neither engagement field reaches any model-facing projection.**
> `GoalBrief`'s fields are ADR-0249 §9's and gain nothing here; `GoalCandidacy` carries no
> instant and no conversation (§4); and no prompt this decision builds renders either value.
> They are read by the candidate-set query, by the focus derivation and by `GoalSummary`
> (§15), and by nothing else.

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

> **Normative.** **The elision is disclosed and never silent, and the disclosure is keyed
> on what the turn actually did.** `elided` is rendered to the associator on the candidacy
> (§4), and where it is non-zero the reply discloses it on every turn that **opened a goal**
> — whether from a `FRESH` verdict or from a `CONTINUES` that found no focused goal to
> continue (§3) — and on every turn that **asked** (`UNDECIDED`). **No lane keys the
> disclosure on the verdict**, because a `CONTINUES` over a capped set that displaced the
> conversation's only open goal opens a goal while reporting that one was found. **No lane
> raises the cap to avoid disclosing an elision**, and none renders the dropped goals.

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
>   opens no goal, records no revision, engages nothing (§1), takes **no relevance read, no
>   episodic supplement and no `Planner.plan` call**, drives no plan and produces no effect.
>   Its outcome shape is §5's, which is the one shape this decision adds beside ADR-0170
>   §4's.

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
> one member and no more**: `associate`, an `async` method taking one **positional-only**
> parameter, a `GoalCandidacy`, and returning a `GoalAssociation`. There is **no second
> member**, **no keyword parameter** and **no second positional**, and an implementation
> holds a `ModelProvider` and **nothing else that reads** — not a `MemoryStore`, not a
> `PlanStore`, not a `ConversationStore`, not a `ContextProvider` and not any other. It
> lives in `ai_assistant.planning` and is reached by `orchestration` **through this Protocol
> and by no other route**. This is a **BREAKING** contract change under golden rule 5.

The signature, shown rather than marked (ADR-0089 §2), is:

```python
class GoalAssociator(Protocol):
    async def associate(self, candidacy: GoalCandidacy, /) -> GoalAssociation: ...
```

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

> **Normative.** `TurnOutcome` gains **four** `None`-defaulting members, one per fact, on
> ADR-0244 §9's own rule: **`goal_engagement: GoalEngagement | None`** (§5),
> **`clarification: Clarification | None`** (§10), **`reference: ReferenceOutcome | None`**
> (§11) and **`disambiguation: GoalDisambiguation | None`** (below). No member is derived
> from another and a client renders each on its own.

> **Normative.** **`goal_engagement`** carries what this turn did with a goal. It is `None`
> on an outcome that engaged none — a routed operation (ADR-0197 §7), a restated settled
> binding (ADR-0198 §1), and the `UNDECIDED` turn of §3, which engaged nothing by §1.

> **Normative.** `core/types.py` gains **`GoalDisambiguation`**, a frozen model with
> `extra="forbid"` carrying exactly `candidates`, a **non-empty**
> `tuple[NonBlankEncodableText, ...]` holding the **outcome statements** of the goals the
> turn is asking about, and `elided`, an `int` `ge=0` (§2). **It carries no identifier, no
> label, no status and no instant**: a label is meaningless outside the call that rendered
> it (§3), and the user answers in words on the next turn or by a reference (§11).

> **Normative — which goals `candidates` holds, in both of `UNDECIDED`'s shapes.** Where the
> associator named **two or more** labels that resolve, `candidates` holds exactly those
> goals' outcome statements, in candidacy order. Where it named **fewer than two that
> resolve** — a decline, an unparseable answer, or a single label outside the candidacy's
> range (§4, §3) — the system has no subset to ask about, so `candidates` holds **every**
> candidate of the candidacy, in candidacy order. The tuple is therefore non-empty on every
> `UNDECIDED` turn, because §3 makes no `associate` call over an empty candidate set, and it
> may hold exactly **one**, which is a well-formed question — *is this about that, or is it
> something new?* — and not a degraded one.

> **Normative — the one outcome shape this decision adds, and ADR-0170 §4 is superseded in
> one count.** An `UNDECIDED` turn returns `turn` `None`, a **non-`None` `reply`**,
> `reply_degraded` `False` and `disambiguation` set. **`turn` is `None` on a second shape**;
> `reply`'s three-shape enumeration is **untouched**, because this turn carries one. The
> validator ADR-0170 §4 obliges is stated over both directions as it already is, and **no
> other outcome carries a `disambiguation` at all**.

> **Normative.** **The reply is composed by `orchestration` from the typed value, and no
> model writes it.** The turn made no model call it could compose from — it took no
> relevance read, no episodic supplement and no `Planner.plan` call, because association
> precedes all three — so the sentence is deterministic, is built from `candidates` and
> `elided`, and **cannot disagree with the member beside it**. That is the distinction
> ADR-0170 §4's own argument turns on: what it refuses beside structured data is *"a second,
> **model-written** account of the same pending action"*, and a value rendered from the
> structure is not a second account of it.

**Carrying a reply rather than leaving it absent is what keeps every channel working, and
the spoken one is why.** ADR-0200 §4 rules that *"`spoken` is the rendering of
`outcome.reply` and of nothing else"* and that *"`spoken` is `None` wherever `outcome.reply`
is `None`"*. An undecided turn with no reply would therefore answer a spoken request with
**silence** while waiting for an answer it never asked for out loud — and fixing that at the
speech seam would mean a second spoken-composition rule beside ADR-0207's, for a question
`orchestration` can simply put in the one place every surface already reads. It also makes
this decision's supersession narrower: `reply`'s enumeration does not move at all, and only
ADR-0197 §8's `turn`-`None` count does, which is the precedent for adding exactly this kind
of shape.

> **Normative.** `core/types.py` gains **`GoalEngagement`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `disposition`, an `EngagementDisposition`;
> `outcome`, a `NonBlankEncodableText` carrying the engaged goal's **current outcome
> statement**; `revised`, a `bool`; `outcome_changed`, a `bool`; `added`, a possibly-empty
> `tuple[NonBlankEncodableText, ...]`; and `removed`, a possibly-empty
> `tuple[NonBlankEncodableText, ...]`. It carries **no goal id, no attempt id, no revision
> number, no label, no ground and no instant.**

> **Normative.** **`revised` says a revision was recorded, and nothing more.** It is `True`
> exactly where this turn recorded a `GoalInterpretation` through
> `PlanStore.record_interpretation`, and it is **not** a claim that any text moved.
> `outcome_changed` is `True` exactly where the recorded revision's `outcome` differs from
> the previous revision's, byte for byte.

> **Normative.** **`added` and `removed` are computed by comparing the two revisions and
> never by a model.** `added` carries the `text` of every element of the **new** revision
> that the previous revision did not carry in the **same** tuple, byte for byte; `removed`
> carries the `text` of every element the **previous** revision carried that the new one does
> not, on the same comparison. Both are in the tuple order `constraints`, `criteria`,
> `conditions`, and an element retained by label (ADR-0249 §7) appears in neither.

> **Normative — the invariant, stated over every revision ADR-0249 §7 permits.** Where
> `revised` is `False`, `outcome_changed` is `False` and `added` and `removed` are both
> empty. Where `revised` is `True`, **every combination is admitted**, all three empty
> included: that shape is a revision that changed no words at all, and it is **reachable and
> legitimate** — a planner that restates the same constraint text with a `USER_STATED` ground
> where the previous revision held an `INFERRED` one has changed the interpretation's
> **grounding** and nothing a reader would read. ADR-0249 §7 permits that revision in terms,
> and no clause here declares it invalid.

> **Normative.** **Removal is disclosed and never inferred from silence.** ADR-0249 §7 makes
> omission the whole of the removal mechanism — *"An element of the current interpretation
> that the `ProposedUnderstanding` neither retains nor replaces is **not** in the new
> revision"* — so a revision whose only effect is to drop the user's stated budget is a
> revision whose only trace is an absence. `removed` is that trace, and a turn that dropped an
> element and said nothing would be the silent rewrite §3 and §5 exist to forbid.

> **Normative.** **`EngagementDisposition`** is a `StrEnum` valued by lower-cased member
> name and **closed at exactly four members**: `OPENED` — a goal this turn opened;
> `CONTINUED` — the focused goal; `RESUMED` — an open goal that was **not** the focused
> goal; and `REOPENED` — a closed goal, whose status this turn moved to `ACTIVE` (§12).
> The vocabulary is added to and never renamed.

> **Normative — decision 6, as a rule rather than a judgement.** **A reply carries one
> sentence naming the goal it is about where, and only where, the `disposition` is
> `RESUMED` or `REOPENED`, or `revised` is `True` **and** at least one of `outcome_changed`,
> `added` and `removed` says something moved.** A turn whose disposition is `OPENED` or
> `CONTINUED` and which moved no word says nothing about goals at all: an ordinary topic
> change and an ordinary continuation each need neither an announcement nor a confirmation.

> **Normative.** **A grounding-only revision is recorded and not announced.** Where
> `revised` is `True` and `outcome_changed`, `added` and `removed` are all empty, the
> understanding a reader would read is unchanged — what moved is the record of **who said
> it**, which the goal's own interpretation chain carries and which no reply states. A
> sentence there would announce a change the user cannot see, on a turn where nothing they
> told the assistant was re-read.

> **Normative.** **A revision that moved a word is never silent, and the sentence states
> what actually moved.** Where the sentence is owed on the revision limb it states the goal's
> `outcome` as this turn recorded it, **every text in `added`**, and **every text in
> `removed`** as something no longer held — never merely that something changed, and never the outcome alone where
> either tuple is non-empty. That is the real safeguard against a wrong association: the user
> sees what the assistant now thinks they asked for, on the turn it changed.

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

**Four members, because they are four facts and no turn holds all of them, which is
ADR-0244 §9's rule rather than a preference.** That section put each fact on *"one
`None`-defaulting member per fact"* and refused to collapse two because that would make
*"one field a `Confirmation` on one path and an enum on another, which is a union a client
must discriminate before it can render either"*. The four come apart in the cases that
actually occur: a turn raises a **clarification** on a goal it also engaged and revised; a
turn whose **reference** named nothing still associates by §3, and may then come back
`UNDECIDED`, where there is **no** engagement to hang the reference on; and a
**disambiguation** exists only on a turn that engaged nothing at all. A reference member
nested inside `GoalEngagement` would therefore be unreportable in exactly the case a user
most needs told — the handle they were given resolved to nothing — or would force an
engagement value asserting a goal was engaged when none was.

**What stays inside `GoalEngagement` is one fact with four facets.** The disposition, the
outcome statement, whether a revision happened and what changed are all *what this turn did
with the goal it engaged*; a client renders them together or not at all, and each is
meaningless without the others.

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

> **Normative — the label is resolved against the proposal and the text is taken from the
> recorded revision.** `orchestration` resolves `about` to the **position** it names in the
> `ProposedUnderstanding`'s own tuple, and then records the `text` of the **`GoalElement`
> that position produced in the revision this turn recorded** — which is the newly grounded
> element where the proposal stated one, and the element **retention copied forward** where
> the proposal carried a `retains` and nothing else (ADR-0249 §7). Where `about` is `None`
> it records the recorded revision's **outcome**. So `GoalQuestion.about` is a statement in
> words in every case, is never absent on an `OPEN` question, and **is never the proposed
> element's own `text`** — a retaining `ProposedElement` has none, by ADR-0249 §7's
> *"a **retaining** element carries `retains` **and nothing else**"*.

> **Normative.** **The label does not survive the call and no label is persisted as a
> reference**, which is ADR-0226 §3's cost clause binding here as it binds everywhere else.
> What is stored is the subject's text, which is stable under every later revision.

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
state, and ADR-0014 §5 charters `PlanStore` for exactly that — *"Durable planning state
belongs to `planning`, not to the wiring layer"*, over values that are *"all personal data,
so this state is squarely within ADR-0004's scope"*.

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

### 9. `PlanStore` gains eight members, and this is a BREAKING contract change

> **Normative.** `PlanStore` gains the following **eight** members, and this is a
> **BREAKING** contract change under golden rule 5, layering on ADR-0249 §12's widening of
> the same Protocol:
>
> - `async def engage_goal(self, goal_id: str, /, *, at: UtcInstant, conversation_id: str,
>   expected_version: int) -> Goal` — stamps `last_engaged_at` and `last_engaged_in`,
>   advances `version`, and returns the goal as written. It refuses on a stale
>   `expected_version` with ADR-0014 §5's stale-write error class, and it writes **nothing
>   else**: not the status, not the interpretation, not the attempt.
> - `async def set_goal_status(self, goal_id: str, /, *, status: GoalStatus, at: UtcInstant,
>   expected_version: int) -> Goal` — the goal's **only** status-mutation route. It advances
>   `version`, refuses on a stale `expected_version`, and writes **nothing else**: not the
>   engagement stamp, not the interpretation, not the attempt.
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

> **Normative.** **This decision writes exactly two `GoalStatus` values through
> `set_goal_status`**: `ACTIVE`, on a reopen (§13), and `ABANDONED`, on `abandon_goal` (§12).
> **The member refuses neither `ACHIEVED` nor `BLOCKED`**, because A10 and A3 write them
> through this same route and a store that refused a member would be a second place the
> vocabulary is decided.

> **Normative.** **All eight are commands and none is a snapshot.** Each names the change it
> makes and returns the stored record; none takes a whole `Goal` or a whole `GoalQuestion`
> back in order to write it. ADR-0014 §5's argument binds unchanged and no fifth frozen
> command type is minted for it — a keyword list that names one change is a command in that
> section's sense, which is the shape ADR-0244 §3's `settle` already uses.

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

> **Normative.** `TurnOutcome`'s **`clarification: Clarification | None`** (§5) carries the
> question **this turn raised**, so that the question appears in the exchange that raised it.
> It is `None` on every turn that raised none, and a turn carries at most one.

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
> It is resolved by `orchestration` against records this system holds, and **no prompt this
> decision builds prints it or the goal id it resolves to**; no `GoalCandidacy` carries
> either (§4). ADR-0228 §8's namer rule binds it entire.

> **Normative.** **`GoalBrief.goal_id` is untouched and is still carried.** ADR-0249 §9 puts
> it there, requires `Engine._check_plan_is_for_goal` to compare `plan.goal_id` against it,
> and rules that *"`_render_request` **prints no identifier**"* — so the brief of a
> referenced turn carries exactly the id the reference resolved to, and the containment is
> the renderer's, not the type's. **No clause of this decision removes an identifier from
> `GoalBrief`, adds one to it, or narrows what §9 says it carries.**

> **Normative.** **The handle is the question's own durable `id` and needs no re-minting.**
> `GoalQuestion` is a row of a durable store, so a restart changes nothing about it:
> ADR-0052 §1's enumerate-and-re-mint path is **not** extended here, no handle table holds
> a question, and `pending_confirmations` gains nothing. That path exists because a parked
> step lives in a process-scoped table (ADR-0042 §4); a question does not.

> **Normative — what a `question_id` reference does, and it does it whatever the
> disposition.** `goal_id` survives settlement (§8), so the reference resolves to a goal in
> every case, and the turn **engages that goal** (§1). Then:
>
> - **`OPEN` and unexpired, on an attempt in a non-terminal `AttemptState`** →
>   `settle_question` takes it `ANSWERED`; that attempt **resumes at the phase it stood** and
>   its state moves to `RUNNING`. **No new attempt is opened** (§12).
> - **`OPEN` and unexpired, on an attempt already in a terminal `AttemptState`** —
>   `CANCELLED` or `ENDED` — → `settle_question` takes it `ANSWERED` and the turn **opens a
>   new attempt** by §12's third act, at `UNDERSTAND`, on the same goal. **No transition out
>   of a terminal state is attempted**, which ADR-0249 §5 forbids in terms: *"no transition
>   leaves a terminal member"*. The answer is not lost — it revises the goal's
>   **interpretation**, which is the goal's and not the attempt's (ADR-0249 §5) — and the new
>   attempt plans against the revised understanding.
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

> **Normative.** `TurnOutcome` carries **`reference: ReferenceOutcome | None`** — a member
> **of its own** (§5), never nested in `GoalEngagement` — saying what became of the turn's
> reference. **`ReferenceOutcome`** is a `StrEnum` valued by lower-cased member name and
> **closed at exactly four members**: **`UNKNOWN`** — the reference named no question and no
> goal this store holds; **`ANSWERED`** — this turn settled the question it named;
> **`EXPIRED`** — the question's `disposition` is `GoalQuestionDisposition.EXPIRED`, whether
> this turn settled it or an earlier read did; **`ALREADY_SETTLED`** — its `disposition` is
> `ANSWERED`, `WITHDRAWN` or `SUPERSEDED` and this turn did not settle it. The vocabulary is
> added to and never renamed.

> **Normative — the four are mutually exclusive by construction, and that is why no
> precedence is stated.** `UNKNOWN` is the case where no record was found at all; the other
> three are read **off the question's own `disposition`** and no question carries two.
> **`EXPIRED` is stated over the disposition and never over a clock comparison**, which is
> ADR-0244 §9's own rule — *"`EXPIRED` is stated over the **disposition** rather than over
> which call discovered it"* — and the deadline is compared **only** where the question is
> still `OPEN` (§12). A question answered an hour after it was asked and referenced a week
> later is `ALREADY_SETTLED`, not `EXPIRED`: it was answered, and a reply saying otherwise
> would tell the user their answer never arrived.

> **Normative.** **`reference` is `None` on a turn that carried none, and on a `goal_id`
> reference that resolved.** A resolved goal reference has nothing to report beyond the
> engagement itself, which `disposition` already carries as `RESUMED` or `REOPENED` (§5);
> a `goal_id` naming no goal this store holds is `UNKNOWN`.

> **Normative.** **An `UNKNOWN` reference is reported whatever the association then does.**
> The turn falls through to §3 and is associated like any other, so it may come back
> `UNDECIDED` — an outcome carrying **no** `goal_engagement` (§5) — and `reference` is a
> member of its own precisely so that the user is still told the handle they gave resolved
> to nothing. **No implementation constructs a `GoalEngagement` in order to carry a
> reference outcome**, because that value asserts a goal was engaged.

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

> **Normative — the answer's writes happen in this order, and the order is the decision.**
> `settle_question` first, then `record_interpretation` for the revision the answer
> produced, then `commit_attempt` for the attempt's state. **`settle_question` is taken
> before anything else is written**, which is ADR-0244 §6's own reason: settling first has no
> window in which a second party sees an answered question beside an open one and has to
> guess whether the first answerer is still running.

> **Normative — what the order costs, stated rather than hidden.** A process that dies
> between the writes leaves a question `ANSWERED` whose content is cleared, an attempt still
> `AWAITING_CLARIFICATION`, and a goal whose interpretation the answer did not reach. **That
> state is read for exactly what it is**: the question was taken and the answer did not
> land. **Nothing repairs it, nothing re-opens the question, and no lane adds a
> reconciliation walk, a tombstone or a second lifecycle.** The goal is still open, still a
> candidate and still engageable; the next turn that associates to it resumes the attempt
> (§11), and the user's recourse for the lost answer is to say it again. That is a bounded
> loss of one answer and it is preferred to the alternative, which is a question re-offered
> after an answer whose revision may or may not have been recorded.

> **Normative.** **Raising a question carries the same order and the same reading.**
> `record_question` is written before `commit_attempt` moves the attempt to
> `AWAITING_CLARIFICATION`, so a crash between them leaves an `OPEN` question on an attempt
> still `RUNNING`. It is answerable, its `goal_id` still reaches the goal, its deadline still
> frees it, and the turn that answers it moves the attempt by §11's ordinary path. **Nothing
> repairs that state either**, and no implementation refuses a question whose attempt is not
> `AWAITING_CLARIFICATION`.

> **Normative.** **What a restart does not have to resolve.** The question is durable, the
> attempt's state is durable, the goal and its interpretation chain are durable, and the
> reference is a record id rather than a process-scoped handle — so **no handle table is
> rebuilt, no continuation is re-minted and no enumeration runs at start**. The two windows
> above are the whole of what a crash can leave behind, each is legible from the rows
> themselves, and neither is a state a recovery protocol resolves.

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

### 12. Expiry, withdrawal, supersession, abandonment, and which user acts open an attempt

> **Normative.** **An expiry is settled and is never inferred.** A question whose
> `expires_at` is at or before the clock's reading is settled `EXPIRED` by the **first
> operation that reads it** — a `record_question` on the same goal, an `open_question`
> read, an `outstanding_questions` enumeration, or a turn whose reference names it. The
> settlement clears the content (§8) and moves **nothing else**: not the goal's status, not
> the attempt's state, not `last_engaged_at`.

> **Normative.** **A goal whose question expired is still paused and still resumable.** Its
> attempt stays `AWAITING_CLARIFICATION`, it stays in the candidate set, it stays engageable
> by an ordinary turn, and **no lane reads an expiry as a refusal, an abandonment, a denial
> or a decision of any kind.** Decision 2 binds here in terms: *"Silence is neither refusal
> nor abandonment."*

> **Normative.** `AssistantEngine` gains **`async def withdraw_clarification(self,
> question_id: Identifier, /) -> ClarificationWithdrawal`**. It settles an `OPEN` question
> `WITHDRAWN`, clearing its content in the same step and freeing the goal's one question
> slot. **It takes no reason, no free text and no deadline.**

> **Normative.** `core/types.py` gains **`ClarificationWithdrawal`**, a `StrEnum` valued by
> lower-cased member name and **closed at exactly two members**: `WITHDRAWN` and
> `NOTHING_TO_WITHDRAW` — the question is already terminal, or no such question exists. An
> unknown id is `NOTHING_TO_WITHDRAW` and **never a raise**, which is
> `AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception` binding at this
> seam.

> **Normative.** **Withdrawing removes the question and not the pause.** The attempt stays
> `AWAITING_CLARIFICATION` and the goal stays open; what the act buys is the freedom to ask
> again, which is exactly what the one-open rule's genuine constraint (§8) is about. A
> withdrawal **records no answer**, revises no interpretation and engages no goal — the
> difference from an answer, on ADR-0244 §11's own distinction between a denial and a
> cancellation: *"a denial is the user answering *no* and is a ruling; a cancellation is the
> user withdrawing the question and is not one."*

> **Normative.** **`SUPERSEDED` has exactly one producer: opening a new attempt on a goal
> whose earlier attempt's question is still `OPEN`.** That act settles the question
> `SUPERSEDED` in the same sequence that opens the attempt. **Nothing else writes it** — not
> a revision, not an expiry, not a second question, not a withdrawal.

> **Normative.** **No terminal disposition is inferred from silence.** A question is `OPEN`
> until something settles it; `OPEN` is never read as answered, as declined, or as
> permission to act; and there is no timeout, retry, sweep or reclaim that revises an
> understanding the user did not answer for.

> **Normative — which user acts open an attempt**, settling the half ADR-0249 §13 leaves to
> A2. Exactly three, and **no non-user act opens one**:
>
> 1. A turn that **opens a goal** opens that goal's first attempt.
> 2. A turn that **reopens a closed goal** opens a new attempt, which is ADR-0249 §5's *"A
>    reopened goal starts a new attempt"* binding entire.
> 3. A turn that **associates to an open goal that has no runnable attempt** — its current
>    attempt is in a terminal `AttemptState` (`CANCELLED` or `ENDED`), **or it has no attempt
>    at all** — opens a new attempt. The second limb is not hypothetical: ADR-0249 §12
>    migrates every pre-decision goal with an empty attempts table, so an `ACTIVE` migrated
>    goal the user references would otherwise have no route to a first attempt and nothing to
>    resume, to pause or to hang a clarification on.
>
> **An answer to a clarification opens none** (§11), a resumed park opens none, a resumed
> step opens none, and a turn that associates to a goal whose attempt is non-terminal opens
> none. **A3 may name further acts for the investigation loop and may name none that is not
> a user act**, which is ADR-0249 §5's clause and is not reopened here.

> **Normative.** **A new attempt opens at `UNDERSTAND`** (ADR-0249 §6) and carries **no
> reference of the attempt it follows**: `plan_ids`, `execution_ids` and
> `authorization_ids` each start empty. What ties the two together is the **goal**, which
> is what ADR-0249 §5 means by *"Plans, executions and authorizations are referenced by id
> and never inlined"* — the goal's record is the join and an attempt-to-attempt pointer
> would be a second one.

> **Normative — `GoalStatus.ABANDONED` and its one producer.** `AssistantEngine` gains
> **`async def abandon_goal(self, goal_id: Identifier, /) -> GoalAbandonment`**, and **it is
> the only thing in this system that writes `ABANDONED`.** No expiry, no silence, no
> timeout, no sweep, no reclaim, no model output and no inference writes it.
> `core/types.py` gains **`GoalAbandonment`**, a `StrEnum` valued by lower-cased member name
> and **closed at exactly three members**: `ABANDONED`, `ALREADY_CLOSED` and `NO_SUCH_GOAL`.

> **Normative.** **Abandoning writes the goal's status through `PlanStore.set_goal_status`
> (§9) and settles its open question `WITHDRAWN`, and does nothing else.** It does **not** move the attempt's state, does not
> write an `AttemptOutcome`, does not end an execution and does not cancel anything in
> flight: **what becomes of an attempt on an abandoned goal is A9's** (§17), and ADR-0249
> §4's rule that *"An attempt reaching a terminal state **does not** move the goal's
> status"* is obeyed in the direction it is stated and not inverted here. An abandoned goal
> leaves the open set (§1), so nothing associates to it and nothing plans for it.

> **Normative.** **`GoalStatus.BLOCKED` gains no producer here.** ADR-0249 §4 reads
> *"`ABANDONED` and `BLOCKED` likewise gain no producer here; which act writes each is A2's
> and A3's **respectively**"* — so `BLOCKED` is **A3's**, and no clause of this decision, and
> no lane implementing it, writes it. **`GoalStatus.ACHIEVED` likewise gains none**, which
> is A10's and the owner's correction 2.

**Expiry settled by the next reader rather than by a sweep, on ADR-0244 §10's own reason.**
That decision settles an expired park *"at the first operation that reads it"* and states why
it is safe: there is no live answerer for the settlement to race, because the answer path
refuses an expired row before it acts. The same holds here — a reference naming an expired
question is `EXPIRED` and never `ANSWERED` — so no scheduler, no job and no background pass is
added, and ADR-0083 §7's *"no job gets new store surface"* is not reached.

**Why `SUPERSEDED` exists and has exactly that producer.** Without it, a user who reopens a
completed goal while an old attempt's question is still open would have a question bound to an
attempt that is over: answering it would resume an attempt the new one replaced, and not
answering it would block the new attempt from asking anything. Settling it in the same
sequence that opens the attempt closes both, and naming a single producer is what stops a
later lane inventing a second one — a supersession written on every revision would settle
exactly the questions whose answer is the revision the user is about to give.

**And the abandonment is a user act because ADR-0249 §4 defines the member as a decision
nobody but the user can take.** `ABANDONED` means *"was given up"*, and a system that writes
it from an expiry writes that the user gave up because they did not reply within a window —
which is decision 2's prohibition stated as an implementation. One explicit act, one
disposition, and the alternative refused by name.

### 13. Reopening, and resumption from another conversation by explicit reference

> **Normative.** **A closed goal is reopened by a turn that associates to it**, by any path
> of §3: a `TurnReference` naming it, or an `ASSOCIATES` verdict whose label resolves to it.
> Reopening writes `GoalStatus.ACTIVE` through `PlanStore.set_goal_status` (§9), opens a new
> attempt (§12) and engages the goal (§1),
> and the outcome's `EngagementDisposition` is `REOPENED`, which §5 makes an announced case.

> **Normative.** **Reopening preserves everything the goal holds.** Its interpretation chain
> is appended to and never reset, its `interpretation_elided` count is not touched, its
> `conversation_id` is not rewritten, its earlier attempts stay exactly as they stand with
> their outcomes and their references, and **no effect any earlier attempt produced is
> replayed, undone or re-attempted.** ADR-0249 §1's append-only rule binds entire.

> **Normative — decision 5.** **A goal is resumed from another conversation by explicit
> reference and by that alone.** The reference is a `TurnReference` carrying a `goal_id`
> (§11), performed from a surface listing the user was shown (§15). **There is no automatic
> cross-conversation association**: no candidate set of any conversation is widened to
> another's goals, no search, ranking or match runs across conversations, and no model is
> ever shown a goal of a conversation other than the one the turn is running in.

> **Normative.** **The reference quotes no internal identifier to any model.** The `goal_id`
> is resolved by `orchestration` before any call is made; the candidacy carries no
> identifier at all (§4); and on the turn a reference fires, **no `associate` call is made**
> (§3 step 1). A goal id therefore reaches a model on no path of this decision.

> **Normative.** **`Goal.conversation_id` keeps its provenance meaning while a second
> conversation engages the goal.** It is written once, at the opening, and is **never
> rewritten**; what the second conversation moves is `last_engaged_in` (§1), which is a
> separate field with a separate meaning. So the record still answers *"where did this
> objective come from"* truthfully after any number of cross-conversation resumptions, which
> is the question ADR-0249 §1 put the field there to answer.

> **Normative.** **A goal engaged from a second conversation becomes a candidate there and
> stays one until a third engages it** (§2), and becoming a candidate is not an association:
> every later turn of that conversation still resolves its goal by §3 over the whole set.

> **Normative.** **A reference resolves against the `PlanStore` and against nothing else.**
> A goal whose row `PlanStore.delete_goal` removed resolves to nothing and the reference is
> `UNKNOWN`; a goal whose **conversation** was deleted keeps its row and **stays
> referenceable**, because ADR-0074 §8's deletion reaches episodes, the index and the
> conversation record, and **this decision adds no cross-store deletion of its own** (§17).
> Such a goal is a candidate in no conversation but the one that next engages it, which is
> the honest state and not one to repair.

**This is the owner overruling the design report, and the mechanism is the cheap middle option
that report named.** Its recommendation was *"no, in this design"*, with the gap named:
*"yes-by-association would need a cross-thread candidate set nothing in the corpus has;
yes-by-explicit-reference is the cheap middle option if the owner wants it, and is additive
later."* The owner wanted it, and it is additive exactly as described: the reference path (§3
step 1) already exists for the question handle, so cross-conversation resumption is that path
given a second shape rather than a second mechanism.

**Why `last_engaged_in` rather than requiring the reference every turn.** The alternative —
candidacy strictly by `conversation_id` — would make a resumed goal invisible to the very next
turn, so *"actually, make it Sunday"* the turn after a resumption would find nothing and open
a duplicate goal. That is not "explicit reference is supported"; it is "one turn may borrow a
goal". One field, one writer, and the property decision 5 actually asks for: **the user points
once and the work is here.** What is still not built is any way for the system to find a goal
in another conversation on its own, which is the half the owner deferred.

**What this costs, stated rather than hidden.** A goal's candidate membership is now a
two-field test rather than a one-field one, and a goal that has moved between conversations is
a candidate in **two** of them — the one that opened it and the one that last engaged it. That
is the honest reading of what happened to it, and the cap (§2) bounds what either set costs.
A goal that has moved through five conversations is a candidate in two, not five, because
`last_engaged_in` holds one value; the other three reach it by reference, which is the same
route they used the first time.

### 14. Pauses as the user experiences them, and the elision the reply discloses

> **Normative — decision 1, as a rule and not a judgement.** **A paused goal is mentioned in
> exactly two places and in no other:**
>
> 1. the reply of the turn that **associated to it** — which is §5's announcement, owed
>    because the disposition is `RESUMED` or `REOPENED`; and
> 2. the reply of a turn whose association came back **`UNDECIDED`** with that goal among
>    the labels the model named — the ask (§3) names the goals it is asking between.
>
> **No turn mentions a paused goal it neither associated to nor asked about**, and in
> particular **no turn mentions one merely because it is a candidate.** A user who asks an
> unrelated question is answered, and their reply says nothing about the campsite.

> **Normative.** **No notification, no interruption and no proactive contact** is produced
> for a paused goal, an outstanding question, an expiring question or an expired one (§10).

> **Normative — decision 2's telling.** **An expiry is explained on the turn it becomes
> relevant and on no other.** Where a turn's reference names a question this decision
> settled `EXPIRED`, or names one already `EXPIRED`, `goal_engagement.reference` carries
> `EXPIRED` and the reply says that the question expired and that the goal is still being
> worked on. **No turn announces an expiry it did not encounter**, and no sweep announces
> one at all.

> **Normative.** **Where the candidate set was capped, the reply says so on the turns where
> it could have mattered, and the test is the turn's `EngagementDisposition` rather than the
> verdict.** Where `elided` is non-zero the reply states that older goals were not considered
> and that one may be named directly, on every turn whose disposition is **`OPENED`** and on
> every turn that returned a **`disambiguation`** (§5). **On a `CONTINUED`, a `RESUMED` or a
> `REOPENED` the elision is not mentioned**: a goal was found, and reciting what was not
> looked at would be noise on the turns the mechanism worked.

**"Relevant or useful" made checkable, which is what the owner's ruling needs to be
implementable.** The ruling reads *"A paused goal is mentioned once when relevant or useful,
not automatically on the next unrelated turn."* Relevance is not a judgement any two
implementations would make alike, so it is read as the two places where the association
machinery has **already established** relevance: the turn that went to the goal, and the turn
that could not tell whether it should. The "once" then falls out of the structure rather than
needing a marker on the record — a resumption is a resumption exactly once, because the next
turn on that goal is a `CONTINUED`, and an ask is settled by the answer.

**And the prohibited case is prohibited explicitly, because it is the tempting one.** A
system that knows a goal is paused wants to say so, and the next unrelated turn is where it
would. The owner ruled against it; the clause above is that ruling written as a place the
sentence may not appear, which is how a reviewer can check it.

**Why the disclosure is keyed on what the turn did and not on what the model said.**
ADR-0086 §4 refuses a silent elision because *"A displaced citation that leaves no trace would
make a belief report a narrower warrant than it has, which is a *false* answer to the one
question the provenance display exists to answer."* The question the candidate set exists to
answer is *which of your goals is this about*, and the only answers a cap can falsify are the
ones that say **none of them**: a goal opened may duplicate an elided one, and a question
asked may be asked between a set missing the right answer. A goal **found** is a goal found,
and an elision cannot have made that false.

**Keying it on the verdict would miss one case, and the case is reachable.** A `CONTINUES`
over a conversation whose cap is filled by recently engaged **closed** goals has no focused
goal to continue, so §3 opens one — a goal opened on a verdict that says a goal was found,
and exactly the answer the elision may have falsified. Reading the **disposition** instead
catches it, because what the turn did was `OPENED` whatever the model called it.

### 15. What the surfaces owe, what a channel of unbounded audience may be told, and the names they do not take

> **Normative.** `AssistantEngine` gains **`async def goals(self, *, limit: int =
> DEFAULT_PAGE_SIZE, offset: int = 0) -> tuple[GoalSummary, ...]`**, the listing from which
> a user learns what is outstanding and obtains the references §11 and §13 take. It is
> paged on ADR-0085 §3's own convention and answers no total count, on ADR-0074 §2's
> ground.

> **Normative.** `core/types.py` gains **`GoalSummary`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `id`, an `Identifier`; `outcome`, a
> `NonBlankEncodableText`; `status`, a `GoalStatus`; `paused`, a `bool`;
> `last_engaged_at`, a `UtcInstant | None`; and `clarification`, a `Clarification | None`
> carrying the goal's open question where one stands. **It carries no attempt id, no
> revision number, no element, no ground, no evidence reference and no plan.**

> **Normative.** **`paused` is computed and never stored**, by ADR-0249 §5's own
> definition: the goal's status is `ACTIVE` and its current attempt's state is
> `AWAITING_CLARIFICATION`, `AWAITING_AUTHORIZATION` or `BLOCKED`. **The engine computes
> it**, so that two surfaces cannot render it differently — which is why ADR-0249 §5 states
> the derivation once — and **no adapter derives it**.

> **Normative.** **The command line and the browser both implement this decision.** Each
> renders a raised clarification in the exchange that raised it, lists outstanding goals and
> their questions, carries an answer with its reference, and offers the withdrawal and the
> abandonment acts. A **spoken** channel renders none of the acts and its reply is the whole
> of what the user is told, which is ADR-0244 §13's placement posture unchanged;
> `SpokenTurn` gains nothing.

> **Normative.** **A spoken turn is answered on every path of this decision, including the
> undecided one.** Its clarification and its disambiguation each reach the user through
> `outcome.reply`, which ADR-0200 §4 synthesises — *"`spoken` is the rendering of
> `outcome.reply` and of nothing else"* — so **no clause of this decision leaves a spoken
> request silent**, no second spoken-composition rule is added beside ADR-0207's, and no
> clause of ADR-0200 or ADR-0207 is amended.

> **Normative.** **A surface that renders no statement for a `ReferenceOutcome`, an
> `EngagementDisposition` or a `ClarificationWithdrawal` member it was given has not
> implemented this section** — it is not permissibly degraded, which is ADR-0242 §9's last
> clause read here.

> **Normative.** **No adapter reads a store, joins a row, computes a member or composes a
> reply.** Rendering a fixed statement per enum member is presentation (ADR-0242 §9), and
> golden rule 3 binds: `interfaces/` gains no read of a `Goal`, a `GoalAttempt`, a
> `GoalQuestion`, a `GoalCandidates` or a `PlanStore`, and ADR-0042 §6's prohibition stands
> word for word.

> **Normative — a turn on a channel of unbounded audience does not associate to a stored
> goal.** On such an operation (`converse_spoken`, as ADR-0200 §3 declares it) **no
> `GoalCandidacy` is built and no `GoalAssociator.associate` call is made**: §3's second step
> governs and the turn **opens a goal of its own**, carrying revision 1 minted from this
> turn's request (ADR-0249 §3). **No stored goal, no stored interpretation element, no
> stored outcome statement and no stored question text reaches any stage of such a turn.**

> **Normative.** **So no `GoalDisambiguation` and no `RESUMED`, `REOPENED` or `CONTINUED`
> disposition is reachable on such an operation**, and the brief its planner receives is a
> revision-1 brief carrying this turn's own request, **no elements** and **no
> `open_questions`** (ADR-0249 §9). A clarification that turn's planner raises is composed on
> that turn over that supply and is spoken in the ordinary way (§10, §11).

> **Normative.** **This decision places no class as speakable and reads no ground for a
> disclosure purpose.** `GoalInterpretation.outcome_ground` is not a disclosure marker, is not
> read as one, and no lane admits stored goal content to an unbounded channel on the strength
> of it. ADR-0199 §3's enumeration is untouched, its Tier 0 floor binds entire, and
> ADR-0199 §2's *"No implementation, lane or later ADR may decide a class by reading …
> a composed reply, or any other span of the content itself"* is obeyed by deciding nothing.

> **Normative.** **`converse` and `converse_streaming` are bounded and associate over the
> whole candidate set**, which is ADR-0203 §1's last clause unchanged — *"An operation whose
> channel audience is bounded … runs over its whole supply exactly as before"*. **No caller
> puts an operation on either side of that line** (ADR-0200 §3), and this decision moves no
> operation across it.

> **Normative.** **`converse_spoken` gains no parameter and `SpokenTurn` gains nothing.**
> A goal opened on a spoken turn is an ordinary goal: it is a candidate for the bounded
> operations of its conversation, it is listed by `goals`, and it is engageable from any
> bounded surface. **What is not available is continuing one *by voice*, and that is a
> stated cost rather than a gap** (§17).

> **Normative.** **The names are new and overload none.** `AssistantEngine.questions`,
> `AssistantEngine.answer`, `AssistantEngine.forget_question`, the CLI's `assistant
> questions`, `assistant answer` and `assistant forget-question`, and the type `Question`
> with its `QuestionState` are **ADR-0078 §8's deferred memory questions** and are untouched
> by this decision: it adds no member to them, changes no argument of them, and renames
> nothing. **No surface of this decision presents a goal clarification in the same list, the
> same command or the same vocabulary as a memory question.**

> **Normative.** **No statement rendered for any member of this decision's vocabularies
> carries** a record identifier other than the question id the answer act requires, a
> destination, an account identity, a provider name, a query or any fragment of one, a
> monetary figure, a budget, a threshold or a `Settings` field name. That is ADR-0242 §9's
> bar binding on these vocabularies as it binds on that one, and for the same reason.

**Why nothing stored is admitted rather than some of it, and what was tried first.** The
narrower rule is tempting: admit a candidate whose outcome the **owner stated**, withhold the
rest, and a spoken turn keeps most of its reach. It is unsound, and the reason is worth
stating because it is not obvious. ADR-0249 §7 resolves a `USER_STATED` ground by checking
that the **span** is a span of the turn's request — it does not check that the `outcome`
*equals* that span. A planner may therefore return an outcome carrying anything at all
beside a valid one-word span and have it recorded `USER_STATED`, so the ground is a **model's
attribution** and not a recorded origin. Admitting content on it would make the model the
disclosure authority, which is exactly what ADR-0199 §2 forbids: *"The **class** of a piece
of content is decided from what the system recorded about where the content came from, and
never by inspecting the content for what it appears to be about."* A tighter test —
`outcome` byte-equal to its span — would be sound for the outcome and would still say
nothing about the goal's **elements** or its **open question**, each of which the brief
carries and each of which an earlier bounded turn may have composed over content this channel
withholds.

**So the line is drawn where it is decidable: nothing stored crosses.** A spoken turn runs
over its own request, which is what ADR-0203 §1 already says such a turn's goal is — *"its
`goal` is the owner's utterance as ADR-0074 §3 carries it"* — and ADR-0203 §4's exemption of
*"the turn's own goal statement"* is left meaning exactly what it meant before this decision,
because on such a turn the goal **is** that utterance. No class is placed, no ground is read
for a disclosure purpose, and the rule is checkable by looking at which operation is running
rather than at any content at all.

**And it is stored content rather than this turn's completion, which is why the line falls
there.** ADR-0203's whole construction is to subtract **before** the turn plans, so that
whatever a model then writes is composed over material already placed — which is why a
clarification question *this* turn's planner raised is speakable, and why a goal outcome or
constraint *an earlier* turn's planner wrote is not. The two look alike on the page and are
on opposite sides of the line.

**The question id is rendered because the act takes it, and that is the tree's own
pattern rather than an exception carved here.** ADR-0078 §8's `Question.id` is documented as
*"The question's id, which `answer` and `forget_question` take"*, and the CLI has printed it
since. A surface that showed a question but no way to name it would have put a question the
user cannot answer, and the alternative — a re-minted opaque handle — is ADR-0052 §1's
machinery bought for a record that is already durable (§11). What the bar above forbids is
everything else.

**Two goal-shaped things with the same English word is the confusion this section is written
to prevent.** A deferred memory question asks *may I believe this about you*, is answered
yes-or-no, and its answer writes a belief. A goal clarification asks *which of two things did
you mean*, is answered in words, and its answer revises an interpretation. Sharing a command
would make the binary answer reachable for a question that has no binary answer, and would
make `assistant questions` a list of two kinds nobody asked to see together.

### 16. The writer clauses

> **Normative.** **`orchestration` writes every value this decision adds, and no model
> writes any of them.** Focus (§1), the association outcome (§3), the goal a turn is
> associated to, the question's id, its `asked_at`, its `expires_at`, its `attempt_id` and
> every disposition it ever carries (§§8–12), the attempt-opening act (§12), the goal's
> status through `set_goal_status` (§§9, 12, 13) and the engagement announcement (§5) are each stamped by the loop from the
> injected clock, the injected id factory and typed outcomes.

> **Normative.** **What a model supplies is exactly three things**, and each is a judgement
> about meaning: an `AssociationVerdict` with its labels (§4), a `ProposedQuestion`'s `text`
> and `about` (§7), and — through ADR-0249 §7, unchanged — a `ProposedUnderstanding`. **No
> model supplies an identifier, an instant, a disposition, a status, a phase, a state, a
> deadline or a count**, and a value coming back carrying one has it **discarded silently**,
> which is ADR-0249 §6's posture and ADR-0228 §5's before it.

> **Normative.** **No model output clears anything.** ADR-0249 §7's asymmetry binds this
> decision entire: *"A model may never clear a permission, a coverage test, a prerequisite
> or a dependency."* An association is not an authorization, a `FRESH` verdict is not a
> finding that no goal applies to anything, and the absence of a `ProposedQuestion` is not a
> finding that nothing is ambiguous — it is the absence of a report.

> **Normative.** **No interface adapter authors any of them either.** Golden rule 3 and
> ADR-0042 §6 bind: an adapter relays a reference the user gave it and renders what the
> outcome carries, and derives, defaults, composes and synthesises nothing — which is
> ADR-0177 §1's *"the gateway derives none of them, defaults none of them, composes no
> operation out of two, and synthesises no result from a call it did not make"*.

### 17. What this ADR does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them.

- **`GoalStatus.BLOCKED`'s producer, the bounded investigation loop, the per-attempt
  allowance and its reserve, progress and stopping, and any further member of
  `AttemptEffort`.** A3, by ADR-0249 §4 and §13. Fired by this ADR landing.
- **Whether the association call is counted against, or changes, any per-turn model-call
  budget.** ADR-0228 §3's figure is a bound on `Planner.plan` and is untouched (§4);
  whether a turn's **total** model calls acquire a bound of their own is A3's, which owns
  the effort ledger. Fired by an ADR against ADR-0228 §3's own reservation of that figure.
- **`GoalStatus.ACHIEVED`, verification against the goal's criteria, and which
  `AttemptOutcome` member an attempt earns.** A10, by ADR-0249 §4. This decision supplies
  none, which is the owner's correction 2.
- **What becomes of an attempt on an abandoned goal, and cancellation generally.** A9.
  §12 writes the goal's status and nothing on the attempt.
- **`GoalEvidence`, evidence standing, and what "recheck evidence" compares.** A4. §11
  states what "recheck" means until A4 lands and names A4 as what extends it.
- **Authorization coverage, and what "recheck authorization" compares beyond the gates
  that already run at dispatch.** A6. §11 likewise.
- **Whether a `GoalQuestion` ever earns a notification.** Deferred by name. Fired by an
  ADR that mints a `NotificationCandidate` producer with its class, its reach level and its
  budget under ADR-0130 §§5–7. §10 makes the absence of a producer this decision's ruling
  and not an oversight.
- **Automatic cross-conversation association.** Deferred by the owner's decision 5, and
  §13 forecloses nothing: a candidate set that spanned conversations, and whatever would
  bound it, is what such a decision would have to supply.
- **Whether a question may be asked outside a planner's return** — by the composing stage,
  by a driver, by a verification. Fired by A5, A7 or A10 needing one. §6's three
  conditions are stated over a `ProposedQuestion`, and a second raiser would need its own
  subject and its own materiality test.
- **Whether ADR-0244 §3's one-open-park-per-conversation rule survives ADR-0247 §5.**
  Booked by the owner on 2026-09-12 (decision 9) as a separate contract review, and
  **untouched here**. §8's one-open rule is **per goal** and is a different rule about a
  different record with a different constraint; nothing in this decision reads, relies on or
  disturbs that clause.
- **Whether a channel of unbounded audience may ever be told about a stored goal, and by
  what route a spoken turn continues one.** §15 withholds every stored goal value from such a
  turn and states the cost; `converse_spoken` gains no parameter here. Fired by a decision
  that **places** goal content as speakable under ADR-0199 §3 on a recorded origin this
  system actually holds — which `GoalInterpretation.outcome_ground` is not, because ADR-0249
  §7 resolves it against a span rather than against the outcome — or that gives a spoken turn
  a content-free way to name a goal.
- **A retention horizon for a goal row.** §2 mints none, on decision 4. Fired by a lane
  that needs one, which would owe its own export, deletion and disclosure obligations.
- **Any cross-store deletion beyond `delete_goal`'s cascade.** §9's cascade is internal to
  one store; ADR-0074 §8's conversation deletion is untouched and reaches no goal.

### 18. Records owed on earlier ADRs, under ADR-0082 §1

**ADR-0249 §7 — partially superseded**, in `ProposedUnderstanding.questions`'s element type
alone, and §7 above states the showing. A reader holding only ADR-0249 builds a
`ProposedUnderstanding` whose `questions` are bare strings, which after this decision does not
construct — ADR-0070 §1's test on the supersession side. **Everything else about that field is
fulfilled rather than moved**: it is still carried, still the planner's, still read by no lane
of ADR-0249, and §7's own sentence — *"**what a raised question becomes is A2's**"* — is what
this decision does. §7's `Planner.plan` roster, its `PlannerOutput` enumeration, its
retained-or-restated validator, its retention clauses, its `ProposedElement` shapes, its
ground resolution and its refusals, its minted-record clause and its
interpretation-is-the-model's asymmetry all bind entire and are the grounds §§6–7 reason from.

**ADR-0249 §1 — partially superseded**, in the `Goal` model declaration's field count alone.
`Goal` gains `last_engaged_in`, so a reader holding only §1 authors a goal that never carries
one and does not conform. The scope is the declaration: §1's `conversation_id`-is-provenance
clause is **relied on as the ground for the new field**, §1's four-absences clause is
**extended and not weakened** — the fifth absence has the same one route and the same
no-lane-writes-`None` rule — and §1's `statement` projection, its append-only rule, its
`version` clause and its elision reference are untouched. **§1's clause that *"no lane in this
decision reads `last_engaged_at` for any purpose"* is fulfilled**, not superseded: it is a
statement about ADR-0249's lanes and it stays true of them.

**ADR-0014 §5 — partially superseded**, in the `PlanStore` member enumeration and the
`PlanExport` shape, layering on ADR-0249 §12's record. §9 states the showing. §5's
compare-and-swap discipline, its transitions-not-snapshots rule, its local-residency,
export-completeness and deletion obligations bind entire and are what §9 reasons from; §5's
charter sentence — *"Durable planning state belongs to `planning`, not to the wiring
layer"* — is the ground §8 argues the store choice on.

**ADR-0085 §3 — partially superseded**, in `converse`'s parameter list and in the roster's
count. A reader holding only §3 writes a `converse` with no `reference` parameter, so a client
answering a clarification has nowhere to name it — ADR-0070 §1's test on the supersession
side. §3's spelled-out-annotation rule, its docstring obligations and §5's closed-graph
obligation bind entire and are obeyed: `TurnReference`, `GoalSummary`, `Clarification`,
`GoalEngagement`, `ClarificationWithdrawal`, `GoalAbandonment`, `EngagementDisposition` and
`ReferenceOutcome` are `core` types reachable from the surface. **`converse_streaming` needs
no record**: ADR-0173 defines it as taking exactly `converse`'s arguments in exactly its
order, so it inherits the keyword by that clause.

**ADR-0170 §4 — partially superseded**, in its `turn`-`None` enumeration's count alone, and
§5 states the showing. A reader holding only §4 refuses an outcome whose `turn` is `None`
beside a `GoalDisambiguation`, which is the only shape an `UNDECIDED` turn can return: it
engaged no goal, so there is no `TurnResult` to build. **ADR-0197 §8 is the precedent and is
untouched** — it admitted the first such shape for a routed pass and this admits the second
for an undecided association. **§4's `reply` enumeration is not reached**: the undecided turn
carries a reply, so the three shapes on which `reply` is `None` are exactly the three §4
names. §4's requirement that the invariants be stated *"in **both** directions"* as a
`model_validator(mode="after")` binds entire and reaches the new shape; `reply_degraded`
stays `True` on the composition-failure shape and on no other, and never `True` where `turn`
is `None`; and §4's park, recovered-park and composition-failure clauses are untouched. Its
refusal of *"a second, model-written account"* beside structured data is the ground §5 gives
for composing the disambiguation's reply **deterministically from the typed value** rather
than from a model, and ADR-0200 §4's *"`spoken` is `None` wherever `outcome.reply` is
`None`"* is why it is carried in `reply` at all.

**ADR-0177 §1 — partially superseded**, in its thirty-operation enumeration alone, which gains
`goals`, `withdraw_clarification` and `abandon_goal`. This is ADR-0200's precedent exactly —
that decision recorded against the same clause when it added `converse_spoken` — and the scope
is the enumeration and nothing else: §1's arguments-the-browser-owns clause, its
caller-owned-deadline class (which gains no member, because none of the three takes a turn
budget), its `learn`-is-unreached clause and its single-principal clause all bind entire.

**One record that is *not* this decision's, and it is filed rather than folded in.** ADR-0244
§11 added `cancel_read` to the promoted surface and §13 admitted the browser for it, and the
gateway routes it — `("POST", "/confirmation/cancel-read"): "cancel_read"` in
`interfaces/gateway/server.py` — but ADR-0244 recorded nothing against ADR-0177 §1's closed
enumeration, and its own §21 does not list that ADR among the four it records against or the
three it cites without one. That is ADR-0244's record to make, so it is **#2274** and not a
clause of this document.

**ADR-0203, ADR-0199 and ADR-0200 — relied on unchanged, and nothing is placed, widened or
amended.** ADR-0203 §1's subtraction is stated over *"the turn's supply"* and over every
*"stage of that turn"*, and §15 satisfies it by admitting **no** stored goal value to such a
turn at all; ADR-0203 §1's *"its `goal` is the owner's utterance as ADR-0074 §3 carries it"*
stays literally true of a spoken turn, and §4's exemption of *"the turn's own goal statement"*
is left meaning what it meant before this decision. **ADR-0199 gains nothing**: §3's
enumeration of what is withheld is untouched, **no class is placed as speakable**, §2's
decide-from-recorded-origin rule is obeyed by deciding nothing from content, and §3's Tier 0
floor binds entire. **ADR-0200 is untouched**: §4's *"`spoken` is the rendering of
`outcome.reply` and of nothing else"* is what §5 satisfies by carrying a reply,
`converse_spoken` gains no parameter, `SpokenTurn` gains no member, and ADR-0207's
live-confirmation sentence gains no sibling.

**ADR-0244, ADR-0226, ADR-0228, ADR-0074, ADR-0086, ADR-0130, ADR-0052, ADR-0176, ADR-0211,
ADR-0213, ADR-0042, ADR-0078 and ADR-0247 — relied on unchanged, and the showings are above.**
**ADR-0244** is reused and not amended: §1's the-turn-does-not-park shape, §3's store
properties, §9's one-member-per-fact widening of `TurnOutcome` and its own two members' mutual
exclusion, §10's expiry-as-settlement and no-disposition-from-silence rules, §11's
withdrawal-is-not-an-answer distinction and §13's surface posture are each read and applied;
**its §3 one-open-park-per-conversation clause is untouched** and is the owner's separate
review (§17). **ADR-0226 §3** is the labelling mechanism §3 and §7 resolve through, unchanged
and unwidened. **ADR-0228 §3's bound is not reached** (§4), §5's persistence-site prohibition
is obeyed, and §8's namer rule binds this decision's two seams. **ADR-0074 §2** supplies §1's
timestamp argument and its tie-break, and §7 and §8 supply §2's retention reading; no clause of
either moves. **ADR-0086 §4** supplies the disclosed-elision shape and its count-versus-flag
test, and is not widened. **ADR-0130 §5** is cited to say that this decision reaches its
chassis on no path. **ADR-0052 §1 is deliberately not extended** (§11), and a reader holding it
does nothing wrong — a question is not a parked step. **ADR-0176 §1** supplies §4's asserted
decline. **ADR-0211 §2's ruling is obeyed**: the associator's one value is a projection bought
for containment and not packaging, exactly as ADR-0249 §7 says of `GoalBrief`. **ADR-0213 §4**
supplies the fixed-constant shape for §2's cap. **ADR-0042 §6** and golden rule 3 are what §15
binds the adapters under. **ADR-0078 §8's surface is untouched** (§15), so a reader holding it
is not wrong about anything. **ADR-0247** is not reached at all: this decision touches no
search, no provider, no draw and no admission.

### 19. The lane cut, and the one lane that moves the wire

> **Normative.** **Every lane of this decision lands after ADR-0249's L1, L2 and L3**, in
> that order and without exception. M1 supersedes a type L1 lands and M3 threads code L3
> writes, so a lane of this decision that landed first would either break the tree or
> re-land ADR-0249's own diff.

> **Normative.** The implementation lands in **four lanes**, in this order, each a separate
> PR.
>
> - **M1 — the contract, the wire and the stored shapes, at unchanged behaviour.**
>   `core/types.py` and `core/protocols.py` gain every type and member above — the
>   `GoalAssociator` Protocol, `GoalCandidacy`, `CandidateGoal`, `GoalAssociation`,
>   `AssociationVerdict`, `MAX_ASSOCIATION_CANDIDATES`, `GoalCandidates`,
>   `ProposedQuestion`, `GoalQuestion`, `GoalQuestionDisposition`, `TurnReference`,
>   `Clarification`, `GoalEngagement`, `EngagementDisposition`, `ReferenceOutcome`,
>   `GoalDisambiguation`, `GoalSummary`, `ClarificationWithdrawal`, `GoalAbandonment`,
>   `Goal.last_engaged_in`, `ProposedUnderstanding.questions`'s element type, `PlanStore`'s
>   eight members, `PlanExport.questions`, `TurnOutcome`'s four members and its widened
>   `reply`/`turn` validator (§5), `converse`'s keyword and `AssistantEngine`'s three
>   operations. Both conforming `PlanStore` implementations, the
>   `PlanStore` and `Planner` conformance suites and the canonical fakes in
>   `ai_assistant.testing` gain the new obligations; the **`GoalAssociator` triad** —
>   Protocol, shared conformance suite and canonical fake — lands whole; the plan store's
>   migration lands; `Settings.goal_question_ttl` lands; and every call site is moved
>   mechanically so the tree type-checks. **M1 moves `PROTOCOL_VERSION`, the plan store's
>   `schema_version` and `PlanExport.schema_version`, and it is the only lane that moves any
>   of them.** **No behaviour changes in M1**: no association is run, no focus is stamped,
>   no question is raised and no reference is resolved.
> - **M2 — the `planning` seam.** `planning/` alone: `planning/associator.py` implements
>   `GoalAssociator` over a `ModelProvider` and nothing else that reads; `_render_request`
>   renders the brief's `open_questions` and the envelope proposes `ProposedQuestion`
>   values with their `about` labels.
> - **M3 — the `orchestration` threading.** `orchestration/` alone: the candidate read and
>   the association in `Engine`, the four engagement acts, the materiality test over the
>   registry, raising and settling a question, opening attempts, `abandon_goal`, and the
>   engagement and clarification members on the outcome.
> - **M4 — the surfaces.** `interfaces/` alone: the CLI's and the browser's listing, answer,
>   withdraw and abandon acts, and a rendered statement for every member of every vocabulary
>   this decision adds.

> **Normative.** **M1 is the one sanctioned cross-subsystem lane**, and it is sanctioned by
> ADR-0137 §2, which makes *"the **contract triad together with its primary production
> implementation** … one unit of work — one lane, one PR"* and fixes that *"Primary means
> the consumer whose demands shape the contract, not the one that is cheapest to write"* —
> here the `PlanStore` implementations, which the question record, its one-open gate, its
> settlement, its cascade, its export and its migration are actually shaped by. **M2, M3 and
> M4 are each one subsystem**, and no other cross-subsystem pairing is authorised.

> **Normative.** **Every wire-visible change rides M1.** `TurnOutcome`'s four members,
> `converse`'s keyword, the three promoted operations and `Goal.last_engaged_in` each make a
> hub's turn or a client's call undecodable by a peer at the previous version, so splitting
> them across lanes would leave two peers passing the exact-match handshake and then failing
> to decode a turn — the failure ADR-0124 §9 exists to prevent. **The operator restarts
> once.**

> **Normative.** **The `GoalAssociator` triad is not deferred.** `CONTRIBUTING.md` →
> "Adding a Protocol" binds: the Protocol, the shared conformance suite and the canonical
> fake in `ai_assistant.testing` are one unit of work and land together, with the production
> implementation following in M2 as the seam's second consumer.

### 20. The arms this decision owes

> **Normative.** The lanes implementing this decision owe representative-input tests for
> each of the following, and a lane that lands without its arm has not discharged this ADR.

1. **A first turn costs nothing new.** *"What is two plus two?"* on a conversation's first
   turn: the candidate set is empty, **no `associate` call is made**, a goal is opened at
   revision 1, and the turn's model calls are exactly today's — which keeps ADR-0249 §16 arm
   1 true unchanged.
2. **One candidate still costs a call.** The same request on a conversation holding one open
   campsite goal: **an `associate` call is made**, a `FRESH` verdict opens a second goal,
   the campsite goal's `last_engaged_at` is **unmoved**, and its interpretation chain gains
   no revision. The arm fails if the answer is composed against the campsite goal or if its
   revision count moves.
3. **Two plausible campsites remain.** A goal whose brief carries two equally plausible
   readings of *"our usual campsite"* and a plan proposing a side-effecting booking step:
   the planner's `ProposedQuestion` is taken, a `GoalQuestion` is written, the attempt's
   state is `AWAITING_CLARIFICATION`, its **phase does not move**, **no step is driven**,
   and the outcome carries the clarification. The same turn with the registry declaring the
   step **not** side-effecting and the subject a `constraints` element asks **nothing**.
4. **The usual campsite resolves.** A planner that returns no `ProposedQuestion` on a
   side-effecting plan: no question is written, the attempt is not paused, and the turn
   proceeds — asserted so that the second materiality limb cannot become "ask whenever
   acting".
5. **Materiality by kind, over both tuples and the outcome.** A `ProposedQuestion` whose
   `about` names a `criteria` element, one naming a `conditions` element, and one that is
   `None`: each material on a turn proposing **no** side-effecting step. One naming a
   `constraints` element on the same turn: **dropped**. And three that resolve to nothing —
   a label outside the proposal's tuples, a label of a different tuple, and a label naming an
   element ADR-0249 §7's ground resolution dropped — each **dropped** with the turn otherwise
   unharmed. Where several come back, the **first** whose subject resolves and is material is
   the one taken and every other is dropped.
6. **A question about a retained element constructs.** A `ProposedUnderstanding` whose
   `criteria` carries a **retaining** `ProposedElement` (`retains="S1"` and nothing else,
   ADR-0249 §7) and a `ProposedQuestion` whose `about` is `S1`: the subject resolves, the
   question is material, and `GoalQuestion.about` carries the **text of the `GoalElement`
   retention copied forward**, non-blank, so the record constructs. The arm fails if the
   implementation reads the proposed element's own `text`, which a retaining element does
   not have.

7. **The answer reaches the right goal across an unrelated turn and a restart (Q6).** A
   paused campsite goal; an unrelated question answered normally with focus moving to the
   new goal and the campsite goal's question still `OPEN`; the process restarted; then a
   turn carrying the question's reference — which associates to the campsite goal with
   **no** `associate` call, settles the question `ANSWERED`, resumes the **same** attempt at
   the phase it stood, and records a revision.
8. **Decision 3's late answer.** The same answer arriving after the attempt has been paused
   for hours: the reply restates the revised understanding, a **fresh** `Planner.plan` call
   is made over the new brief, nothing from the paused turn's supply or plan is reused, and
   no second question is raised where the answer resolved the ambiguity.
9. **An answer after expiry reopens rather than vanishes (decision 2).** The question is
   settled `EXPIRED` and its content cleared; a turn carrying its reference still engages
   the goal, `goal_engagement.reference` reads `EXPIRED`, the reply says the question
   expired and the work continues, and **nothing reads the expiry as a refusal or an
   abandonment.** The goal's status is still `ACTIVE`. And `Settings.goal_question_ttl` is
   **refused at load** where it is zero or negative, and admits no disable spelling.
10. **Decision 5: an explicit-reference resume from another conversation.** A goal opened in
    conversation A and referenced by `goal_id` from conversation B: the turn associates to it
    with no `associate` call, `conversation_id` still reads **A**, `last_engaged_in` reads
    **B**, the goal is a candidate in **both**, and the **next** turn of B associates to it by
    the ordinary rule. The arm fails if `conversation_id` moved or if the goal appears in a
    third conversation's candidate set.
11. **Never a silent rewrite, and the undecided outcome is well formed in both its
    shapes.** Two open goals; an `associate` returning two labels: the turn asks, opens no
    goal, records no revision, **engages neither goal**, drives nothing, and takes **no**
    relevance read, episodic supplement or `Planner.plan` call. Its outcome carries `turn`
    `None`, a non-`None` `reply` composed by `orchestration` from the typed value,
    `reply_degraded` `False`, `goal_engagement` `None`, and a `GoalDisambiguation` whose
    `candidates` are the two goals' outcome statements — **and the widened `TurnOutcome`
    validator accepts it**. Then the **fewer-than-two** shape, three ways over a conversation
    holding exactly **one** candidate: an unparseable model answer, an explicit decline with
    no labels, and a single label outside the candidacy's range. Each returns `UNDECIDED`,
    each constructs a `GoalDisambiguation` whose `candidates` hold that one goal's outcome
    statement, and none fails the turn, invents a candidate or picks the one it has.
12. **The announcement rule, over all four dispositions, and what it states.** `RESUMED`
    and `REOPENED` each produce the sentence; `CONTINUED` with `revised` `False` produces
    none; `OPENED` with `revised` `False` produces none; and **any** disposition with
    `revised` `True` produces one stating the revised outcome, every text in `added` and
    every text in `removed`. Three load-bearing cases, each over a **retained** outcome:
    an element **replaced** (the date becomes Monday) puts the new text in `added` and the
    old in `removed`; an element **added** (a new budget) puts it in `added` with `removed`
    empty; and an element **removed by omission** (ADR-0249 §7) puts it in `removed` with
    `added` empty — and the sentence states the removal. The arm fails if any of the three
    produces a sentence naming only the unchanged outcome, and the removal case fails if
    `revised` reads `False` or both tuples come back empty.

13. **A spoken turn is never left silent.** An undecided association driven through
    `converse_spoken`: `outcome.reply` is non-`None`, `spoken` renders it, `spoken_degraded`
    is `False`, and the user hears the question. The same over a turn that raised a
    clarification. The arm fails if either path yields `spoken` `None`.

14. **A spoken turn is told nothing a stored goal holds.** A conversation holding two
    candidates — one carrying an `INFERRED` outcome, one carrying a `USER_STATED` outcome, a
    stored `FROM_EVIDENCE` constraint and an open question — driven through
    `converse_spoken`: **no `associate` call is made**, no `GoalCandidacy` is constructed,
    the turn opens a goal of its own, and the prompt its planner receives contains **no byte**
    of either candidate's outcome text, of the stored constraint's text, or of the open
    question's text. Its brief carries this turn's request, no elements and no
    `open_questions`. The arm is asserted over the **production** renderer and over the
    absence of the call, not over a filter. The **same** conversation driven through
    `converse` makes the call over **both** candidates, which is ADR-0203 §1's
    bounded-operation clause.

15. **No disposition of a stored goal is reachable by voice, and the cost is the one
    stated.** Over `converse_spoken`, no outcome carries a `GoalDisambiguation`, and no
    `GoalEngagement` carries `RESUMED`, `REOPENED` or `CONTINUED`. The goal such a turn opens
    **is** an ordinary goal: the next `converse` turn of that conversation has it in its
    candidate set, `goals` lists it, and it is engageable from a bounded surface.

16. **The revision invariant holds over every revision ADR-0249 §7 permits, the
    grounding-only one included.** `revised` `False` with `outcome_changed` `False` and both
    tuples empty constructs; `revised` `True` with all three empty **also** constructs, and
    is driven from a real planner return — a constraint restated with the **same text** and a
    `USER_STATED` ground where the previous revision held `INFERRED`. That turn records the
    revision, and **announces nothing**. The arm fails if the revision is refused, if
    `revised` is reported `False`, or if a sentence is composed for it.

17. **A settled question is not reported expired.** A question settled `ANSWERED` an hour
    after it was asked and referenced again after its original deadline has passed reads
    `ALREADY_SETTLED`; one settled `WITHDRAWN` and one settled `SUPERSEDED` read the same;
    and only a question whose `disposition` is `EXPIRED` reads `EXPIRED`. The arm fails if
    any of the three is reported expired on a clock comparison.
18. **Focus, and the four acts that move it.** Each of §1's four acts advances
    `last_engaged_at` and `last_engaged_in`; and a candidate-set read, an export, a
    retrieval, an expiry, a withdrawal, an attempt transition and an `UNDECIDED` turn each
    leave both untouched. Run against **both** conforming `PlanStore` implementations
    through the shared suite.
19. **The one-open-question gate, and both compare-and-swap writes.** Two
    `record_question` calls on one goal: one succeeds and one answers `False`, with no
    second row. Two `settle_question` calls on one question: one answers `True` and one
    `False`, with the content cleared exactly once. Two `engage_goal` calls computed against
    the same `expected_version`: one succeeds and one raises. All on **both**
    implementations through the shared suite.
20. **A refused question is not reported.** `record_question` answering `False`: the
    outcome's `clarification` is `None`, the attempt's state is **not** moved, and the turn
    still drives no side-effecting step.
21. **The cap is bounded and disclosed, and the disclosure is keyed on the disposition.** A
    conversation with more than `MAX_ASSOCIATION_CANDIDATES` goals: the candidacy carries
    exactly the cap in §1's order, `elided` carries the true remainder, and no dropped goal
    is rendered. The disclosure appears on an `OPENED` turn and on a turn carrying a
    `disambiguation`, and **not** on a `CONTINUED`, a `RESUMED` or a `REOPENED`. **The
    cap-boundary case is its own arm**: a conversation whose cap is filled by recently
    engaged **closed** goals and whose only open goal was elided, on a `CONTINUES` verdict —
    the turn opens a goal, its disposition is `OPENED`, and the elision **is** disclosed.
    The arm fails if the disclosure is keyed on the verdict.
22. **The namer rule, in two arms that assert only what is true.** **(a) Structural**:
    `GoalCandidacy` and `CandidateGoal` carry **no field in which an identifier could
    sit**, asserted over the two types' declared field sets. **(b) Behavioural**: given a
    candidacy built from goals with distinctive ids and a turn carrying a `TurnReference`
    with a distinctive `goal_id`, the prompt the production associator builds contains
    neither string.
23. **`set_goal_status` is the one status route, `ABANDONED` has exactly one caller of it,
    and two statuses have none.** Over the
    shipped tree, the only assignment of `GoalStatus.ABANDONED` under `src/` is
    `abandon_goal`'s, the only `ACTIVE` one is the reopen path's, both go through
    `set_goal_status`, and **no** assignment of `GoalStatus.ACHIEVED` or
    `GoalStatus.BLOCKED` exists anywhere — asserted as a test over the tree, not as a review
    convention, so that a later lane cannot supply one without the ADR that decides it. And
    `set_goal_status` refuses a stale `expected_version` on **both** conforming
    implementations through the shared suite.
24. **`SUPERSEDED` has exactly one producer.** Reopening a closed goal whose earlier
    attempt's question is still `OPEN` settles it `SUPERSEDED` and clears its content in the
    same sequence that opens the new attempt; a revision, an expiry, a withdrawal and a
    second question each settle nothing `SUPERSEDED`.
25. **Which acts open an attempt, including the migrated goal.** Opening a goal, reopening
    one, associating to a goal whose current attempt is `ENDED`, and associating to an
    `ACTIVE` goal that has **no attempt at all** each open one at `UNDERSTAND` with empty id
    tuples; answering a clarification, resuming a park, resuming a step and associating to a
    goal with a live attempt each open **none**. The no-attempt case is driven **through the
    migration**: a plan store at ADR-0249 §12's version holding an `ACTIVE` goal and an empty
    attempts table is upgraded, that goal is referenced by `goal_id`, and the turn opens its
    first attempt, pauses it on a clarification and answers it — end to end, from a **stored**
    row.
26. **A migrated goal reads back and is a candidate.** A plan store at ADR-0249 §12's
    version holding goals is opened and upgraded: each goal reads back with
    `last_engaged_in` **absent** and no questions; a conversation's candidate set orders
    such a goal **after** every goal carrying an engagement instant; and the goal is still
    associable, still reopenable and still referenceable.
27. **The export closes, and a settled question exports empty.** A `PlanExport` naming a
    question whose `goal_id` the document does not hold does not validate; one whose
    references all resolve does; a settled question exports with its content absent;
    `schema_version` reads the new value and a document at the previous value does not
    validate at all.
28. **`delete_goal` reaches questions**, open and terminal alike, and an open question does
    not block a deletion.
29. **No notification is minted, on any path.** Raising a question, a question expiring, a
    question superseded and a goal paused each produce **no** `NotificationCandidate`, no
    `NotificationPolicy` call and no `NotificationStore` row — asserted over the shipped
    tree, so that the absence of a producer is a fact rather than a reading of this
    document.
30. **The surfaces are separate.** `assistant questions` and `assistant answer` list and
    answer **memory** questions only, and neither lists nor accepts a `GoalQuestion`; the
    clarification acts neither list nor accept an ADR-0078 `Question`.
31. **Both crash windows leave a legible state and nothing repairs it.** With failure
    injected between `settle_question` and `record_interpretation`, the restarted system
    reads a question `ANSWERED` with its content cleared, an attempt still
    `AWAITING_CLARIFICATION` and an unchanged interpretation; the goal is still open, still a
    candidate, and the next turn associating to it resumes the attempt. With failure injected
    between `record_question` and `commit_attempt`, the restarted system reads an `OPEN`
    question on a `RUNNING` attempt, and that question is **answerable**. **No start-up pass,
    sweep, reconciliation or repair runs in either case**, and no implementation refuses a
    question whose attempt is not `AWAITING_CLARIFICATION`.

32. **An `UNKNOWN` reference is reported even where nothing was engaged.** A turn carrying a
    `TurnReference` naming no question and no goal, whose association then comes back
    `UNDECIDED`: `reference` reads `UNKNOWN`, `goal_engagement` is `None`, and a
    `disambiguation` is carried. The arm fails if a `GoalEngagement` is constructed to hold
    the reference outcome, or if the `UNKNOWN` is dropped.

33. **`GoalBrief.goal_id` still crosses the seam on a referenced turn.** A turn whose
    `TurnReference` resolves: the brief handed to `Planner.plan` carries that goal's
    `goal_id`, `Engine._check_plan_is_for_goal` compares the plan's against it, and the
    prompt `_render_request` builds contains neither string — ADR-0249 §9 asserted unchanged
    across this decision.

34. **A turn that ends early persists nothing new.** A turn whose planner raises, one
    rejected for capacity and one that fails before the planner is reached each leave **no
    question row** and no engagement stamp — ADR-0228 §5's clause asserted over this
    decision's record kinds as well.

### 21. This ADR classified under ADR-0070 §1 and ADR-0082 §1

> **Normative.** This is a **substantive contract ADR** under `CONTRIBUTING.md` → "Contract
> ADRs land before their implementation": it changes Protocols and `core` types that cross
> subsystem boundaries. It ships as its own PR, is reviewed by **both** lenses while
> `Proposed`, and is ratified only once that set is green on one tree (ADR-0015 §5,
> ADR-0165). No implementation lands in this PR.

**ADR-0070 §1's test is whether a reader holding only the earlier ADR would do the wrong
thing, and it comes out on the supersession side six times.** A lane holding only ADR-0249 §7
builds a `ProposedUnderstanding` that does not construct; one holding only ADR-0249 §1 authors
a `Goal` missing a field `orchestration` must set; one holding only ADR-0014 §5 implements a
store with no clarification and no engagement stamp; one holding only ADR-0085 §3 writes a
`converse` a client cannot pass a reference to; one holding only ADR-0177 §1 refuses three
operations the browser now reaches; and one holding only ADR-0170 §4 refuses the only
outcome an undecided association can return. Each is named in the header with its scope and each has a
dated note in the superseded document's own header, which is ADR-0082 §1's form.

This ADR is marked, so ADR-0089 §3 governs: the block quotes above are the whole of what
binds, and the prose beside them is read to determine what a marked clause means.

## Consequences

**What becomes possible.** A conversation can hold more than one objective and a turn can say
which one it is about, which is the whole of what #2255's Q5 asked. A request the assistant
did not understand can be put back to the user as a durable question bound to the objective it
is about, answered a day later from any surface and across a restart, and resumed into the
same attempt at the phase it stood. A finished objective can be picked up again without
losing its interpretation history, and a goal can be carried into a second conversation by
pointing at it once. `Goal.last_engaged_at`, `Goal.conversation_id` and
`ProposedUnderstanding.questions` — three values ADR-0249 landed with nothing reading them —
acquire their readers.

**What becomes harder, and what it costs.** Every turn of a conversation that has ever opened
a goal now makes one model call it did not make before, bounded by an eight-candidate prompt,
and §3 argues why the cheaper heuristic is not available. `PlanStore` grows eight members, a
second migration and a wider export, and both conforming implementations and the shared suite
carry all of it. The promoted surface grows three operations and one keyword and `TurnOutcome` grows four
members, so the wire moves and the operator restarts once. `TurnOutcome`'s validator admits
one more shape, which every client that discriminates on `turn` and `reply` must learn. And a user can now be asked a question, which is a cost
paid on every turn the model reports an ambiguity about a material subject — §6's three
conditions exist to keep that cost proportional, and arm 4 is what stops the second
materiality limb from becoming "ask whenever acting".

**What is deliberately still missing.** A goal row has no retention horizon and nothing
reclaims one; "recheck evidence and authorization" means replanning and the existing gates
until A4 and A6 land; a paused goal earns no notification and no proactive contact; and
nothing finds a goal in another conversation without the user pointing at it. Each is named in
§17 with the condition that fires it.

**What would trigger revisiting this.** A deployment that hits
`MAX_ASSOCIATION_CANDIDATES` routinely would mean one conversation genuinely carries more live
objectives than the cap admits, which is a signal about the product rather than a figure to
raise. An association whose model call proves unreliable in the `UNDECIDED` direction — asking
often where a person would not — would fire a decision about what else the candidacy should
carry, which is the one value this decision deliberately kept at two fields. And A3's effort
ledger reaching a per-turn model-call bound would be the lane that decides whether the
`associate` call is counted.

## Alternatives considered

**Focus as a pointer on the conversation record.** Rejected on ADR-0074 §2's own reasoning: a
mutable "the focused one" is a second authority two concurrent turns can race, and the loser's
write leaves the conversation pointing at a goal neither turn engaged. A per-goal timestamp
each turn writes on its own row cannot disagree with itself, and the derivation every reader
computes is the same one.

**One non-terminal goal per conversation, with a paused goal blocking a new one.** Rejected
under the owner's standing rule and Q6. Its only ground was that association over one
candidate is easier to get right than association over N, which is convenience, and the
user-facing cost is that a paused campsite request would prevent answering an unrelated
question or force a new conversation.

**A recency tie-break instead of the ask.** Rejected: two labels come back exactly when the
user is switching between two live things, so the tie-break revises the goal they were not
talking about, and the wrongness is invisible until a later turn plans against it. Asking
costs one sentence.

**Association inside the planner's envelope.** Rejected as structurally circular:
`Planner.plan` takes a `GoalBrief` projected from *the* goal's current interpretation
(ADR-0249 §7, §9), so calling it requires already knowing which goal. Handing it every
candidate's brief would give back the containment ADR-0230 §4 and ADR-0249 §9 bought, and
would count against ADR-0228 §3's bound, which is A3's figure and not this decision's.

**A second member on `ProposedUnderstanding` carrying question subjects.** Rejected as one
value with two carriers: the texts and the subjects would be two tuples that can disagree in
length and in order, which is the shape ADR-0249 §9 already refused when it declined the
design report's separate `questions` keyword beside the brief's own field.

**Keeping `questions` as bare texts and testing materiality over the text.** Rejected because
the test would be a substring match between two free-text strings — material because a word
recurred, not material because a synonym did — which is not a code test in the sense #2255's
addendum demands, and which would make condition 2 a reviewer's judgement wearing a type's
clothes.

**A `GoalQuestions` Protocol and store of its own, mirroring `ParkedReads`.** Rejected on
ADR-0244 §3's own argument read the other way: a park belongs in `permissions/` because it is
*"the unanswered half of a recorded permission question"*, and a clarification is joined to no
decision and gates no access. The deciding cost is deletion — a question's life is its goal's,
and a second store would put it behind a second cascade with no transaction between the two,
which is exactly the cross-store protocol ADR-0074 §8 had to ratify and which `PlanStore`
makes unnecessary.

**A dedicated `answer_clarification` operation.** Rejected: decision 3 requires the answer to
restate, recheck and **proceed**, which is a planner call, a supply, a composition and a
reply — everything `converse` already is. A second turn path is a path every later decision
would have to be stated over twice.

**A re-minted `ContinuationToken` for the question, on ADR-0052 §1's path.** Rejected as
machinery bought for a record that is already durable. That path exists because a parked step
lives in a process-scoped table (ADR-0042 §4); a `GoalQuestion` is a row, so the handle is its
id and a restart changes nothing.

**Writing `ABANDONED` on expiry, or on a long silence.** Rejected in terms by decision 2 —
*"Silence is neither refusal nor abandonment"* — and by what the member means: a system that
writes "the user gave up" because nobody replied within a window has recorded a decision
nobody took.

**A notification for an outstanding or expiring question.** Rejected here rather than ruled
impossible. A `GoalQuestion` carries a required deadline and would satisfy ADR-0130 §5's
perishability condition, so the reason none is minted is that a producer is a decision with
its own class, reach level and budget, and this decision takes none — which is ADR-0244 §10's
posture and the owner's decision 1.
