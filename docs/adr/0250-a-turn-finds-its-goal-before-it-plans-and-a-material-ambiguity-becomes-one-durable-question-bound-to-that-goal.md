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
