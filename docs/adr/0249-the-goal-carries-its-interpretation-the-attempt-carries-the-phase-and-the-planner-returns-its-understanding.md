# 249. The goal carries its interpretation, the attempt carries the phase, and the planner receives a brief and returns its understanding

- Status: Proposed
- Date: 2026-09-12
- **Partially supersedes** [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md)
  — **§1's third clause in its second sentence alone: "The goal is minted once per turn from
  the user's unrewritten words and nothing about it changed" is false of a goal that carries
  an interpretation, and false of a turn that associates to a goal an earlier turn opened.
  Nothing else in that ADR.** §1's subject-stability rule — *"The revision carries the **same
  `goal_id`** as the plan it replaces"* — binds **verbatim** and is strengthened: a turn's two
  calls now also receive the same `GoalBrief`. Its reason, *"a second goal would make one turn
  look like two in every store that holds goals"*, binds entire. §1's authored-at-the-seam
  clause, its context-assembled-once clause, its nothing-else-is-re-run clause and its
  capability-re-read clause are relied on unchanged, and §§2–15 are untouched.
- **Partially supersedes** [ADR-0014](0014-planning-model.md)
  — **three scopes, each narrow. §5's `PlanStore` member enumeration and its `save_goal`
  upsert contract**: the roster gains members and `save_goal` becomes the opening write alone,
  because an upsert that replaces a whole goal would defeat the append-only interpretation this
  ADR makes it carry. **§5's `PlanExport` shape**: the document gains `attempts`, and §5's
  closure rule extends to `attempt_id` rather than changing. **§6's `Planner.plan` input roster
  and its `-> ActionPlan` return**, which ADR-0041 and ADR-0211 have already partially
  superseded in the roster alone; the return type moves here for the first time. §5's
  compare-and-swap discipline, its transitions-not-snapshots rule, its local-residency,
  export-completeness and deletion obligations, and §6's parameters-not-fetched argument all
  bind entire and are the grounds this ADR reasons from. **§1 is fulfilled and superseded in
  none** (§14), and §§2, 3, 4 and 7 are untouched.
- **Partially supersedes** [ADR-0244](0244-a-confirm-on-a-search-parks-as-a-durable-question-and-the-answer-runs-that-exact-read-once.md)
  — **§2's field enumeration in the count and in one field's type, layering on ADR-0248's
  record: `ParkedRead.goal` becomes a `GoalBrief`, and the record gains a non-content field
  `goal_id` that settlement does **not** clear. Nothing else in that ADR.** §2's
  three-content-fields clause as ADR-0248 left it — four content fields — binds entire and is
  not widened: `goal_id` is an identifier and joins the facts that survive settlement. §2's
  validator keeps both halves it refuses, §2's never-carries clause, its `parameters` clause
  and its `APPROVED` clause bind entire, §3's indivisibility, its retention rule, its
  one-open-park-per-conversation rule and its `settle` clearing clause bind entire, and
  §§1, 4–23 stand entire.

## Context

### Where this comes from

Issue #2255 is the owner's handoff from the Planning/Execution wiki review: implement an
explicit task lifecycle that separates understanding the request, investigating feasibility,
forming a plan, validating and authorizing it, executing it, and verifying the outcome. The
design survey on that issue (revision 1, three comments) is the direction; the owner ruled on
2026-09-12 that its A0–A10 breakdown is the working delivery cut and that **each ADR still
establishes its own concrete contract**. This is A1.

[ADR-0248](0248-the-users-request-is-its-own-value-on-the-turn-and-the-goal-statement-stops-standing-in-for-it.md)
is A0 and is merged. It made the user's request a value of its own — `TurnResult.utterance` —
so that the goal's statement could stop standing in for it. Its §8 names, by name, what it
left here: *"**What `Goal.statement` means.** It is the user's stripped utterance at this
decision and stays so until A1 changes it"*, and with it the interpretation, the revisions,
`GoalBrief`, `GoalAttempt`, the phase model, the four goal-classified query rows of its §5,
and **ADR-0228 §1's per-turn minting clause** — *"which is **A1's to supersede**"*.

### The gap this closes

[ADR-0014](0014-planning-model.md) §1 has said since the planning model was written that
*"A `Goal` is deliberately **not** the same thing as a user utterance"*, and gave the reason:
*"A request ('book me a flight') is transient; a goal ('relocate to Lisbon in September')
outlives any one conversation and is what makes a plan resumable and a notification
justifiable."* The implementation has never carried anything the distinction could be about.
`LearningLoop._goal_from` mints a `Goal` whose `statement` is the stripped utterance, its six
fields hold no outcome, no constraint, no success criterion and no condition, and nothing in
the system has ever revised one. Three of `GoalStatus`'s four members have never been written:
at `fc575d4d`, `git grep 'GoalStatus\.'` over `src/` returns **zero** hits outside
`core/types.py`.

So the six-phase lifecycle has nowhere to put what it learns. A turn that discovers the user
meant Sunday rather than Saturday has no field to record it in, no way to say which turn
raised it, and no way for a later planner call to see it. That is the gap, and it is a
contract gap rather than a wiring one.

### What this ADR is not allowed to settle

#2255's breakdown assigns association and focus to A2, the bounded investigation loop and the
effort figures to A3, the evidence rules to A4, the plan's step fields to A5, authorization
coverage to A6, driving to A7, retry and reconciliation to A8, cancellation to A9, and
verification to A10. §13 names every one of those deferrals with what fires it. This ADR
decides the values those lanes write into and the seam they write across, and nothing else.

## Decision

### 1. What a `Goal` is: an append-only sequence of interpretation revisions

> **Normative.** A **`Goal`** is the **understood outcome** of a request, together with its
> constraints, its success criteria and its conditions, carried as an **append-only sequence
> of interpretation revisions**. `core/types.py` gains `GoalInterpretation`, `GoalElement` and
> `Ground`; `Goal` gains `conversation_id`, `interpretation`, `interpretation_elided`,
> `version` and `last_engaged_at`; and `Goal.statement` stops being a stored field.

> **Normative.** A `GoalInterpretation` is a frozen model with `extra="forbid"` whose fields
> are exactly: `revision`, an `int` at least 1, one greater than its predecessor's;
> `outcome`, a `NonBlankEncodableText` stating the understood outcome; `constraints`,
> `criteria` and `conditions`, each a possibly-empty `tuple[GoalElement, ...]`;
> `recorded_at`, a `UtcInstant`; and `raised_by`, the `Identifier` of the conversation turn
> whose message caused this revision. It carries no plan, no attempt, no evidence and no
> status.

> **Normative.** A `GoalElement` is a frozen model with `extra="forbid"` whose fields are
> exactly `text` (`NonBlankEncodableText`), `ground` (a `Ground`), `evidence_id`
> (`Identifier | None`) and `span` (`EncodableText | None`). A **model validator** refuses
> every shape but three: `FROM_EVIDENCE` with an `evidence_id` and no `span`; `USER_STATED`
> with a `span` and no `evidence_id`; `INFERRED` with neither. The type is what expresses the
> correspondence rather than a rule to remember, which is the move ADR-0244 §2 makes for
> `ParkedRead`'s content fields.

> **Normative.** `Ground` is a `StrEnum` valued by lower-cased member name and **closed at
> exactly three members**: `USER_STATED`, `FROM_EVIDENCE` and `INFERRED`. The vocabulary is
> added to and never renamed, on `ReadKind`'s own rule (ADR-0226 §4): no later ADR removes a
> member, renames one, gives one a second spelling, or replaces this enum with a
> differently-named one for the same question.

> **Normative.** `Goal.interpretation` is a `tuple[GoalInterpretation, ...]`, **oldest first,
> never empty**, whose last element is the goal's **current** interpretation. No lane edits an
> element in place, reorders the tuple, removes an element other than by §2's elision, or
> writes a `revision` that is not one greater than the element before it.

> **Normative.** `Goal.statement` becomes a **read-only property projecting the current
> interpretation's `outcome`**. It is not a model field: it has no setter, it is not accepted
> in a constructor, **it does not appear in `model_dump()`**, and no lane assigns it. Every
> existing reader of `goal.statement` keeps reading it and receives the current outcome
> statement.

> **Normative.** A serialised `Goal` — in a `PlanExport`, in a `PlanStore`'s own rows —
> therefore carries the **interpretation** and not a second copy of its outcome, and a goal
> **round-trips through construction from its own dump**. A computed field that serialised but
> could not be constructed from would break that round trip under `extra="forbid"`, which is
> why the projection is a property.

> **Normative.** `Goal`'s non-blank refusal moves with the value it guards: it is
> `GoalInterpretation.outcome`'s `NonBlankEncodableText` that refuses a blank objective, and
> `Goal` keeps no validator of its own on `statement`. The refusal `planning/sqlite_store.py`
> argues for is preserved and is taken one type earlier.

**Two authorities that can disagree is the failure this avoids, and it is why `statement` is
computed rather than stored.** A stored `statement` beside a stored interpretation is two
records of one fact, and the ADR-0244 §2 argument applies without change — *"a terminal park
read back with a fabricated `Goal` … would misrepresent a record"* — because a goal read back
with a `statement` that is not its current outcome would misrepresent one in exactly the place
a reader would not look. Computing it is not the read-time inference ADR-0213 forbids: that
clause is about a record's own content being **derived from other content** at read —
*"none derives them from `MemoryBase.content`, from a rendered facet, from a composed reply or
from any other span of content"* — and nothing here derives anything. It reads one stored
field of one stored element by a fixed rule.

> **Normative.** `Goal.conversation_id` is the `Identifier` of the conversation the goal was
> **opened in**. It is provenance and **not a fence**: no clause of this ADR makes a goal
> unreachable from another conversation, and whether and how a goal is resumed from one is
> A2's (§13). ADR-0014 §1's *"a goal … **outlives any one conversation**"* binds entire.

> **Normative.** `Goal.version` is an `int` starting at 0, and it is the **compare-and-swap
> token** every mutation of the goal advances. It is a different value from a
> `GoalInterpretation.revision` and the two are never read for each other: `version` orders
> writes, `revision` names an understanding.

**`version` rather than a second "revision", and the name is load-bearing.** ADR-0014 §5
already fixes this token's name and its argument for `ExecutionState` — *"Optimistic
concurrency turns that into a detectable, retryable failure, and it belongs to the store
because the store is the only place with a total order over writes"* — and reusing the word it
uses is what keeps one reader from taking a stale-write refusal for a stale-understanding one.
The design report calls both values "revision"; that collision is not carried here.

> **Normative.** `Goal.last_engaged_at` is a `UtcInstant` stamped when a turn engages the
> goal. **What engages a goal is A2's** (§13), and no lane in this decision reads
> `last_engaged_at` for any purpose: this ADR lands the field and nothing else.

### 2. The revision history is bounded, the elision is on the record, and no message is lost

> **Normative.** `core/types.py` gains `MAX_GOAL_INTERPRETATIONS`, a **fixed constant valued
> 32**. It is not a `Settings` field, not a constructor knob and not a per-deployment value,
> exactly as `MAX_TOPICS_PER_PROPOSAL` is not (ADR-0213 §4). A goal whose sequence would
> exceed it drops its **oldest** element on the write that would exceed it, and the
> **current** interpretation is never dropped.

> **Normative.** `Goal.interpretation_elided` is an `int` field, `ge=0`, defaulting to 0,
> carrying **the number of interpretation revisions this goal's history has dropped**. It is a
> count and never an identifier, and it never decreases. A write that drops *k* elements
> advances it by *k*.

**Silent truncation is not available, and the reason is ADR-0086 §4's word for word.** That
section refuses it because *"A displaced citation that leaves no trace would make a belief
report a narrower warrant than it has, which is a *false* answer to the one question the
provenance display exists to answer."* A goal reporting three revisions where five happened
answers the question *"when did the system's understanding change, and why"* falsely, which is
the one question the interpretation chain exists to answer. The count is *"a count and never
an id: keeping the ids would defeat the bound, since the ids are the payload"*, and that is
true here for the same reason — the payload is the revision.

**An elided revision loses an interpretation and never a message.** The user's words live in
the episode (`EpisodicMemory.content`), in the archive entry (ADR-0225 §1) and in the index
row, each at its own address, and ADR-0248 made the request a value of its own on the turn
that received it. Dropping the goal's oldest *reading* of a request destroys no record of the
request.

**Why 32 and not a tuned figure.** The bound exists to stop a long-running goal growing a row
without limit, not to express a judgement about how often understanding should change; 32 is
larger than any plausible count of times one objective is re-understood inside one
conversation, and because the elision is disclosed rather than silent, a deployment that hits
it learns that it did. ADR-0086 §1's reasoning for fixing its own bound in `core` rather than
in `Settings` applies unchanged: *"a knob that raises the ceiling is a knob that re-opens it."*

### 3. A goal is opened carrying its first revision, minted by `orchestration` from the request

> **Normative.** A goal is **opened carrying `revision` 1**, minted by `orchestration` from
> the turn's request: its `outcome` is the request as ADR-0248 §1 carries it, stripped once by
> the pass that received it; its `constraints`, `criteria` and `conditions` are empty; its
> `raised_by` is the turn that opened the goal; and its `recorded_at` is that turn's instant.
> No goal is ever constructed with an empty `interpretation`, and no lane opens a goal from
> any other value.

> **Normative.** Revision 1 carries **no `GoalElement`** and therefore proposes no ground.
> A planner's first `understanding` for a goal is recorded as revision 2 or later, never as
> revision 1, and no model output ever authors revision 1.

**This is forced by the order of the turn, and it is the clause the design report does not
have.** The relevance read and the episodic supplement are taken **before** `Planner.plan` is
called — `loop.py` reads `self._retrieve(goal.statement)` and `self._supplement(goal.
statement, …)` above the planner call on both its paths — and the interpretation the planner
proposes is a *result* of that call. So on a goal's first turn there is no interpretation in
existence at the moment the goal's statement is first read. A design in which `statement` is
absent until the planner answers would make `Goal.statement` optional, break the non-blank
refusal `planning/sqlite_store.py` argues for, and leave the two blind reads with no query at
all.

**And it makes this decision's first turn byte-identical to ADR-0248's.** That ADR's §6
asserts *"the request and `Goal.statement` are **byte-equal on every path that carries a
turn**"* and rests it on there being *"**one** normalisation in **one** place"*. On a goal's
first turn that equality survives here unchanged, because revision 1's outcome **is** that one
normalised string. What changes is what happens on the turns after it.

**The goal's first understanding of a request is the request, and that is the honest
starting point rather than a placeholder.** Its ground is `USER_STATED` in substance — the
user said it — and the reason it carries no `GoalElement` is that an element is a *part* of an
understanding (a constraint, a criterion, a condition) and revision 1 has decomposed nothing.
ADR-0014 §1's distinction is not violated by the two values being equal for one turn: after
ADR-0248 the request is its own value on the turn, so the goal no longer **stands in for** it,
which is what §1 was about.

### 4. `GoalStatus` is the goal's overall disposition, and `ACHIEVED` gets no producer here

> **Normative.** `GoalStatus`'s four members are the goal's **overall disposition** — whether
> the objective stands, was reached, was given up, or cannot currently be reached. They are
> **not** the state of any one attempt: an attempt may be blocked while the goal is `ACTIVE`,
> and `BLOCKED` on the goal means *this objective cannot currently be achieved*. The
> vocabulary is unchanged and is not added to here.

> **Normative.** **`GoalStatus.ACHIEVED` gets no producer in this decision.** No clause of
> this ADR, and no lane implementing it, writes `ACHIEVED`, and **producing a reply never by
> itself establishes that a goal was achieved**: completion criteria concern the requested
> outcome, and a composed answer is not a comparison against one. A10 of #2255 — verification
> against the goal's criteria — is `ACHIEVED`'s only producer, and it is named here so that no
> later lane supplies one by inference.

> **Normative.** An attempt reaching a terminal state **does not** move the goal's status.
> `ABANDONED` and `BLOCKED` likewise gain no producer here; which act writes each is A2's and
> A3's respectively (§13).

**This is the owner's second correction of 2026-09-12, and the tree makes it free.** Three of
`GoalStatus`'s four members have never been written by anything in `src/`, so declining to add
a producer changes no behaviour at all — it declines to add one. The alternative the design
report walked (S1 ending with *"goal status `ACHIEVED`"*) asserts that the question was
answered correctly on the strength of an answer having been composed, which is the
circularity the owner's correction names.

**What this costs, stated rather than hidden.** Until A10 lands, a goal that was fully served
stays `ACTIVE` — its attempt ends with an outcome saying what happened, and its disposition
records that nobody established the outcome. That is a legible gap and an honest one; a
status that claimed achievement nothing verified would be neither.

### 5. `GoalAttempt`: what was tried, once, from a user act

> **Normative.** `core/types.py` gains **`GoalAttempt`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `id`; `goal_id`; `opened_at`; `phase`, an
> `AttemptPhase`; `state`, an `AttemptState`; `outcome`, an `AttemptOutcome | None`; `effort`,
> an `AttemptEffort`; `plan_ids`, `execution_ids` and `authorization_ids`, each a possibly-
> empty `tuple[Identifier, ...]`; `ended_at`, a `UtcInstant | None`; and `version`, its own
> compare-and-swap token. **Plans, executions and authorizations are referenced by id and
> never inlined**, which is ADR-0014 §3's own pattern for `approval_ref`.

> **Normative.** `AttemptState` is a `StrEnum` valued by lower-cased member name and **closed
> at exactly seven members**: `RUNNING`, `AWAITING_CLARIFICATION`, `AWAITING_AUTHORIZATION`,
> `BLOCKED`, `EFFECT_UNRESOLVED`, `CANCELLED` and `ENDED`. **`CANCELLED` and `ENDED` are the
> terminal members** and no transition leaves a terminal member. The vocabulary is added to
> and never renamed.

> **Normative.** `AttemptOutcome` is a `StrEnum` valued by lower-cased member name and
> **closed at exactly six members**: `VERIFIED`, `CONDITION_PREVENTED`, `PARTIAL`, `FAILED`,
> `UNCERTAIN` and `ANSWERED`. The vocabulary is added to and never renamed. **Which member a
> given attempt earns is A10's** (§13); this decision fixes the vocabulary, because a field
> typed by an enum nobody has written is not a contract.

> **Normative.** A **model validator** refuses every `GoalAttempt` but two shapes: a terminal
> `state` with both `outcome` and `ended_at` present, and a non-terminal `state` with both
> absent.

> **Normative.** **`ANSWERED` means the attempt produced an answer and nothing was verified.**
> It is not a weaker `VERIFIED` and no lane reads it as one: it asserts that a reply exists,
> that no step failed and that no condition blocked, and it asserts nothing about whether the
> reply is correct.

> **Normative.** **A reopened goal starts a new attempt**, and an attempt is opened only by a
> **user act**. No implementation opens an attempt in order to obtain a fresh allowance, and
> no replan, branch or recovery opens one. **Which user acts open an attempt is A2's and
> A3's** (§13); that they must be user acts is fixed here.

> **Normative.** **`GoalAttempt` carries no interpretation and no element.** The objective and
> its disposition are the goal's; the phase, the progress and the effort are the attempt's. No
> lane puts an outcome statement, a constraint, a success criterion or a condition on an
> attempt, and none reads one off it.

> **Normative.** `AttemptEffort` is a frozen model with `extra="forbid"` carrying at least
> `planner_calls`, an `int` `ge=0`, and `working`, a `timedelta` `ge=0` accumulating the
> attempt's **working** intervals and **excluding every interval spent waiting for the user**.
> Both are monotonically non-decreasing within an attempt: **no replan, branch, recovery or
> phase transition resets either**, and no implementation subtracts from one.

> **Normative.** **A3 fixes the allowances, the reserve and any further member of
> `AttemptEffort`** (§13). This decision fixes the ledger's owner — the attempt — and the two
> counters above, and fixes no figure.

**Waiting is not work, and the ledger separates them because an allowance that counted
wall-clock would exhaust every paused goal by morning.** That is one of the three clocks
#2255's addendum asks be accounted separately: a question's deadline bounds how long a
question stands, the attempt's ledger bounds how much work one attempt may do, and evidence's
instants bound nothing by themselves. This decision lands the second clock's carrier and names
the other two as A2's and A4's.

**"Paused" is a derivation and not a status member.** A goal is paused when its status is
`ACTIVE` and its current attempt's state is `AWAITING_CLARIFICATION`, `AWAITING_AUTHORIZATION`
or `BLOCKED`. It is stated here once so two surfaces cannot render it differently, and it is
not a fifth `GoalStatus` member because a status member would be a second authority that can
disagree with the attempt — the same argument §1 makes for computing `statement`.

### 6. `AttemptPhase`, and the writer clause

> **Normative.** `core/types.py` gains **`AttemptPhase`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly six members, in this order**: `UNDERSTAND`,
> `INVESTIGATE`, `PLAN`, `AUTHORIZE`, `EXECUTE`, `VERIFY`. The vocabulary is added to and
> never renamed.

> **Normative.** Within one attempt, `phase` **advances in that order and never moves
> backwards**. A new attempt opens at `UNDERSTAND`. **Recording an interpretation revision
> does not move the phase**: an understanding revised during investigation advances the
> goal's `version`, which is what §8's stale-target rule keys on, and leaves the attempt where
> it stood.

> **Normative.** **A phase whose work is vacuous is stamped and left in the same instant.**
> No phase mandates a model call, a store read, a park or a user interaction; six phases are
> six responsibilities and six observable transitions, and a turn that answers a plain
> question passes through all six on one planner call.

> **Normative — the writer clause.** **`orchestration` stamps the phase, records the
> interpretation revision and its provenance, and sets `supersedes`. No model output writes
> any of them, no field of any planner envelope carries a phase, and no implementation infers
> a phase at read time.**

> **Normative.** A planner envelope that comes back carrying a phase, or a revision number, or
> a `raised_by`, or a `recorded_at`, has those values **discarded silently** — not an error,
> not a park, not a degradation of the turn. ADR-0228 §5 takes exactly this posture for a
> `supersedes` a planner supplied, and ADR-0226 §3 takes it for a label a model invents.

**The writer clause is ADR-0228 §5's discipline applied to two more fields for its own stated
reason.** That section gives the loop `supersedes` because *"an id a model returned would be an
unprovenanced value in a durable audit record — which is the ground ADR-0226 §9 refused to log
`ActionPlan.id` on, applied here to a field that would then be *written* rather than merely
logged."* A phase and a revision stamp are durable audit values in precisely that sense: they
are the record of *what the system did and when it understood what*, and a model that could
write them could write a history. The interpretation's **content** is the model's judgement and
is bought for exactly that; its **provenance** is not, and §7 is where the line is drawn.

### 7. The `Planner.plan` envelope: a brief in, an understanding out

> **Normative.** `core/protocols.py`'s `Planner.plan` takes a **`GoalBrief` as its first
> positional parameter** in place of `Goal`, gains **one keyword parameter** `utterance`
> (`str`, required) and **one keyword parameter** `evidence` (`Sequence[EvidenceDigest]`,
> defaulting to empty), keeps `context`, `memories`, `capabilities`, `files` and `empty_reads`
> exactly as they stand, and returns a **`PlannerOutput`** in place of an `ActionPlan`. This
> is a **BREAKING** contract change under golden rule 5.

> **Normative.** `utterance` is annotated `str` rather than `NonBlankEncodableText`, because a
> Protocol annotation validates nothing and a second spelling of the refusal would suggest
> otherwise. The blank refusal lives where ADR-0248 §1 put it — on `TurnResult.utterance`, and
> on the pass that strips the text once — and no implementation of this Protocol re-checks it.

> **Normative.** The inputs stay **keyword parameters and are not bundled into a planning-input
> type.** ADR-0211 §2's ruling is applied rather than reopened: *"a frozen `core` model is
> **harder** to extend than a keyword-only parameter list, because every field addition is
> another `core` change with its own ADR, where a fourth keyword is one more line in the same
> block."* `GoalBrief` is not an exception to that ruling — it is not packaging, it is a
> projection bought for the containment §9 argues.

> **Normative.** `core/types.py` gains **`PlannerOutput`**, a frozen model with
> `extra="forbid"` carrying exactly two fields: `plan`, an `ActionPlan`, required; and
> `understanding`, a `ProposedUnderstanding | None`, defaulting to `None`. `None` means **the
> planner proposed no change to the understanding**, and it is the semantically correct answer
> for a planner that knows nothing of this envelope. No implementation reads `None` as an
> error, a degradation, or an instruction to re-plan.

> **Normative.** **`ActionPlan.read_request` does not move.** ADR-0226 §4 places it on the
> plan, and ADR-0226 §8 makes the plan's own field the whole of the trigger's record —
> *"a turn on which `read_request` is not `None` is a turn the trigger fired on, and a turn on
> which it is `None` is a turn it did not"*. Nothing in this decision disturbs either, and
> `PlannerOutput` carries no read request of its own.

> **Normative.** `core/types.py` gains **`ProposedUnderstanding`**, a frozen model with
> `extra="forbid"` carrying exactly: `outcome`, a `NonBlankEncodableText`; `constraints`,
> `criteria` and `conditions`, each a possibly-empty `tuple[ProposedElement, ...]`; and
> `questions`, a possibly-empty `tuple[NonBlankEncodableText, ...]`. It carries **no
> revision number, no `raised_by`, no `recorded_at`, no goal id and no phase** — every one of
> those is `orchestration`'s under §6.

> **Normative.** `core/types.py` gains **`ProposedElement`**, a frozen model with
> `extra="forbid"` carrying exactly `text` (`NonBlankEncodableText`), `ground` (a `Ground`),
> `evidence_label` (`EncodableText | None`) and `span` (`EncodableText | None`). A **model
> validator** refuses every shape but three, mirroring `GoalElement`'s: `FROM_EVIDENCE` with a
> label and no span; `USER_STATED` with a span and no label; `INFERRED` with neither.

> **Normative — ground resolution.** `orchestration` **refuses a ground it cannot resolve**,
> and resolves exactly two kinds and no others. A `FROM_EVIDENCE` element's `evidence_label` is
> resolved **by ADR-0226 §3's labelling scheme, unchanged** — the label of the record at
> 1-based index *n* of the `memories` sequence passed **on that call** — and the stamped
> `GoalElement.evidence_id` is the identifier of the record the loop itself labelled. A
> `USER_STATED` element's `span` is resolved by checking it is a span of the turn's own
> request (`TurnResult.utterance`, ADR-0248 §1); the stamped `GoalElement.span` is that span.

> **Normative.** An element whose ground does not resolve — a label outside the shown set, a
> span that is not a span of this turn's request — is **dropped from the recorded revision**,
> silently and without failing the turn, exactly as ADR-0226 §3 drops a label outside the shown
> set. A `ProposedUnderstanding` **all** of whose elements are dropped still records its
> `outcome`, because the outcome is not grounded per element.

> **Normative.** **No record identifier is rendered to the planner and none is accepted from
> it.** ADR-0228 §8's statement of ADR-0226 §3's namer rule binds this envelope entire: an
> element's ground crosses as a **label**, never as a record identifier, and the loop never
> parses an identifier out of a planner's output. The goal's own id is not a record identifier
> in that rule's sense and is the one value this seam has always carried; §9 states what it is
> doing there and why it is rendered nowhere.

**This is the namer rule reaching the one place the design report left it resting on care.**
The report has the planner propose *"elements each with a proposed ground"* and has
`orchestration` *"refuse a ground it cannot resolve to a record the loop chose"*, which is
right — but it does not say what crosses the seam, and the only value that can cross and still
satisfy ADR-0226 §3 is the label. Resolving through the label buys §3's own property without
adding a mechanism: *"the resolvable set is exactly what the loop chose to render, so the
widest possible abuse of the mechanism is asking for something already on screen."* And the
span check is buildable only because ADR-0248 put the request on the turn: before A0 there was
no value on the turn to check a span against that was not itself the goal.

> **Normative.** **Interpretation is the model's; prerequisites and permissions are code's.**
> A model may interpret meaning, resolve a reference, assess whether a record supports a
> proposition, and **raise** a question. **A model may never clear a permission, a coverage
> test, a prerequisite or a dependency**, and no clause of this decision or of any lane
> implementing it takes one on a model's word.

**#2096 item 8's owner-ruled principle is why the asymmetry runs one way only** — *"A model is
a safe denier and an unsafe allower, because of who rehearses against it: an attacker who
beats a deny-only layer gains a deny."* A model that wrongly raises a question costs a
question; a model that wrongly clears one costs an unauthorised effect. What each side of that
line concretely decides is A6's and A7's, and this decision only fixes that the line exists and
which side interpretation sits on.

### 8. A plan names the interpretation revision it targets, and a stale target is not driven

> **Normative.** `ActionPlan` gains one field, **`targets_revision: int`**, `ge=1`, **required
> with no default**, naming the `GoalInterpretation.revision` the plan was planned against.

> **Normative.** **The loop sets it, and the planner never does.** On every plan a planner
> returns, the loop takes the field for its own: it discards any value the plan came back
> carrying and sets it to the `revision` of the interpretation **whose brief it projected for
> that call** — a value the loop holds on the `Goal` itself, which is why `GoalBrief` need not
> and does not carry it (§9). This is
> ADR-0228 §5's rule for `supersedes` applied unchanged — *"there is never a moment at which a
> component other than the loop holds a plan whose `supersedes` is the planner's"* — and a
> value the planner supplied is discarded **silently**.

> **Normative.** **A plan whose `targets_revision` is not the goal's current revision is not
> driven.** Nothing dispatches a step of it and nothing claims a step of it. What happens
> instead — a replan, a typed refusal, a report to the user — and **the mechanism that enforces
> it at the dispatch boundary are A7's and A9's** (§13); what is fixed here is that the plan
> carries the target, that a stale target is not driven, and that no lane satisfies the rule by
> a read of the goal taken separately from the claim.

> **Normative.** `targets_revision` is **not a second `supersedes`**. A revision within a turn
> (ADR-0228 §1) carries the same `targets_revision` as the plan it replaces where the
> understanding did not change between the two calls, and a greater one where it did. Nothing
> reads one field for the other.

**This is the owner's third correction of 2026-09-12 made mechanical.** The correction reads:
*"When understanding changes during investigation, subsequent planning receives the updated
goal view and identifies the interpretation revision it targets."* The first half is §7's
envelope — the planner's next call receives the brief of the current revision. The second half
needs a field, because otherwise "the plan targets the current understanding" is an assertion
nobody can check after the fact, and a plan formed against Saturday would drive against a goal
that now says Sunday with nothing anywhere recording the mismatch. Putting the field on
`ActionPlan` rather than on the envelope is ADR-0014 §2's own ground: the plan is *"an
auditable record of a decision"*, and *which understanding the decision was taken against* is
part of the decision.

**And it is the loop's for §6's reason and not a new one.** The loop knows which brief it
passed; the planner would be reporting back a number the loop already holds, and a number a
model wrote into a durable audit chain is unprovenanced whatever it says. It is also why
`GoalBrief` carries **no** revision number: the planner has no use for it, so it is not
rendered.

### 9. `GoalBrief`: the planner-facing projection

> **Normative.** `core/types.py` gains **`GoalBrief`**, a frozen model with `extra="forbid"`
> whose fields are exactly: `goal_id`; `outcome`, a `NonBlankEncodableText`; `constraints`,
> `criteria` and `conditions`, each a possibly-empty `tuple[BriefElement, ...]`; `status`, a
> `GoalStatus`; `deadline`, a `UtcInstant | None`; and `open_questions`, a possibly-empty
> `tuple[NonBlankEncodableText, ...]` carrying the **texts** of the goal's open questions.

> **Normative.** `core/types.py` gains **`BriefElement`**, a frozen model with
> `extra="forbid"` carrying exactly `text` (`NonBlankEncodableText`) and `ground` (a `Ground`)
> — the ground **kind** and **nothing else**.

> **Normative.** **A `GoalBrief` carries no ground reference, no record identifier, no
> evidence identifier, no span, no revision number, no attempt, no plan, no effort figure, no
> provenance and no authority.** The containment is a property of the type: an implementation
> that rendered every field of every value it was handed, logged them all, or returned them,
> discloses none of those, because there is none on the value to disclose.

> **Normative.** `GoalBrief` is projected **from the goal's current interpretation alone**.
> No lane projects a brief from an elided revision, from a superseded one, or from a union of
> several.

> **Normative.** `_render_request` **prints no identifier** — not `goal_id`, not an evidence
> id — and prints each element's ground **kind** and never a ground reference.

**ADR-0230 §4 already made this move and stated its reason, and this is that sentence applied
to the goal.** Its clause reads: *"**The capability does not cross the planning seam, and that
is a property of the types rather than a rule a planner is trusted to keep.**"* A `Goal` whose
elements carry `evidence_id` values *is* a value holding record identifiers into `memory`, so
passing the whole goal to `Planner.plan` would leave ADR-0228 §8's namer rule —
*"**no record identifier is rendered to a model and none is accepted from one**"* — resting on
`_render_request` remembering not to print them. `ShownFile` is the precedent and `GoalBrief`
is its shape.

**What `goal_id` is doing on the brief, since the rule above forbids identifiers.** It is not
a record identifier in the namer rule's sense: it names the subject of the call rather than a
record in the labelled supply, it has crossed this seam since ADR-0014 §6 put `Goal` in the
signature, and `ActionPlan.goal_id` — which ADR-0014 §2 requires and ADR-0228 §1 keeps at the
`Planner.plan` seam — is the value `Engine._check_plan_is_for_goal` compares it against. The
containment this section buys is over **ground references**, which are identifiers into
another subsystem's store, and `goal_id` is not one. It is also rendered nowhere, by the clause
above, so no model ever sees it.

> **Normative.** `Engine._check_plan_is_for_goal` compares `plan.goal_id` with the brief's
> `goal_id` — reading `turn.goal.goal_id` where it reads `turn.goal.id` today — and is
> **unchanged in substance**, including the refusal it raises and the message naming both ids.

> **Normative.** The `GoalBrief` of a goal at revision 1 carries its `outcome` and **no
> elements**, and that is a well-formed brief rather than a degraded one. No implementation
> treats an element-free brief as an error, a failure to understand, or a reason to ask a
> question.

**The open questions ride on the brief and not as a second parameter.** The design report's
signature carries both a `questions` keyword and the question texts on the brief, which is one
value with two carriers and a forward dependency on a `GoalQuestion` type A2 mints and the tree
does not yet have (`git grep 'GoalQuestion\|OpenQuestion'` over `src/` and `docs/adr/` returns
nothing at `fc575d4d`). One carrier is kept, it is the brief, and it carries **texts** — which
is all a planner can act on, since a question's identity, its deadline and its settlement are
A2's and none of them is the model's business.

### 10. The evidence digest the planner sees

> **Normative.** `core/types.py` gains **`EvidenceDigest`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `requested`, an `EncodableText | None` stating
> what the ask named; `supported`, an `EncodableText | None` stating what the response
> establishes a proposition about; `read_at`, a `UtcInstant`; `as_of`, a `UtcInstant | None`;
> `verdict`, an `EncodableText` carrying the typed outcome's own value; and `standing`, an
> `EvidenceStanding`.

> **Normative.** `EvidenceStanding` is a `StrEnum` valued by lower-cased member name and
> **closed at exactly three members**: `STANDING`, `INAPPLICABLE` and `SUPERSEDED`. The
> vocabulary is added to and never renamed. **Which rules put a row in `INAPPLICABLE` or
> `SUPERSEDED` are A4's** (§13); that the digest can **say** a row was superseded is fixed
> here, so that refreshed evidence has a way to state that it displaces an older
> disagreement rather than standing beside it forever.

> **Normative.** **An `EvidenceDigest` carries no record identifier**, no evidence row id, no
> memory id, no snippet, no title and no address. ADR-0228 §8's namer rule binds it exactly as
> it binds `GoalBrief`.

> **Normative.** `supported` is **never derived from `requested`**, from the query, or from
> the fact that a read completed, and a digest whose response establishes no applicability
> carries `supported` absent. **An absent `supported` supports nothing.**

> **Normative.** `verdict` carries **the value of a typed outcome** and never a prose summary
> a model wrote about one. **The outcome vocabularies themselves are A4's** (§13).

> **Normative.** `GoalEvidence` — the durable row the digest projects from — and the
> `PlanStore` members that hold it are **A4's to mint** (§13). What this decision fixes is
> that any such row must be able to answer the six members above, and that A4's widening of
> `PlanStore` is a second BREAKING contract change with its own ADR.

**Minting an empty box here would be worse than deferring it.** #2255's A4 decides what
`requested` and `supported` are composed from, how conflicts are adjudicated, what invalidation
marks and what supersession means; a `GoalEvidence` whose fields all said "A4 decides" would be
a type ratified with no content, and the first real consumer would have to reopen it. The
digest is different: it is a member of **this** ADR's envelope, the planner cannot be given
evidence without it, and its six members are exactly what the planner can act on.

**And the supersession member is the owner's first correction of 2026-09-12, kept as room
rather than taken as a rule.** The correction reads: *"Refreshed evidence needs supersession
rules, so retained historical disagreements do not permanently block progress."* A digest that
could only say `STANDING` or `INAPPLICABLE` would force A4 either to widen this type — another
`core` change — or to encode supersession inside `verdict`, where nothing could read it. Three
members cost nothing now and leave A4 free.

### 11. Migration, consumer by consumer

ADR-0248 §5 classified every reader of `goal.statement` and left **six** rows to this decision
— the two relevance reads, the two episodic supplements, `planner._render_request` and
`PlanExport` — and its §11 fires the projection question for `ParkedRead.goal` here as well.
Each is answered below, together with the two consumers §5's table does not cover because they
do not read `statement`: `Planner.plan` and `TurnResult.goal`.

> **Normative.** **`Planner.plan` receives a `GoalBrief`** (§7, §9).

> **Normative.** **`TurnResult.goal` becomes a `GoalBrief`.** `TurnOutcome.turn` is a
> `TurnResult` and `TurnOutcome` is what the promoted wire surface returns, so a widened `Goal`
> would put the interpretation chain and its ground references on the wire; the projection goes
> instead. The request rides beside it on `TurnResult.utterance`, which ADR-0248 §1 already put
> there.

> **Normative.** **The goal record is persisted by the stage that holds it.** `Engine`'s two
> `self._plans.save_goal(turn.goal)` calls are removed rather than re-pointed: a turn that
> carries a projection carries no record to save, and the loop that opened the goal and
> recorded its revision is the stage with the record. Nothing else about when a turn persists
> changes, and ADR-0228 §5's *"a turn that ends before that site persists nothing"* binds
> unchanged for plans.

> **Normative.** **`ParkedRead.goal` becomes a `GoalBrief | None`**, and the record gains
> **`goal_id: Identifier | None`**, which **settlement does not clear**. `goal_id` joins `id`,
> `conversation_id`, `decision_id`, `parked_at`, `expires_at` and `disposition` among the
> facts that survive settlement; `goal` stays a content field and is cleared with the other
> three that ADR-0248 left (`parameters`, `utterance`, `plan`).

> **Normative.** Storing the brief rather than the record **strengthens** ADR-0244 §3's
> retention rule — *"The content lives exactly as long as the question does"* — by holding
> strictly less Tier 1 content for the same duration, and §2's validator is not widened: the
> brief is a content field and a terminal park carries none.

> **Normative.** **`PlanExport` gains `attempts: tuple[GoalAttempt, ...]`** and its
> `schema_version` annotation is edited from `Literal[7]` to `Literal[8]`, exactly as ADR-0226
> §4 edited it rather than defaulting it. ADR-0014 §5's closure rule — *"every
> `goal_id`/`plan_id` referenced by an included record resolves within the same export"* —
> **extends** to `attempt_id`: an export naming an attempt it does not carry does not validate
> as a `PlanExport` at all. It does **not** gain evidence rows, because A4 mints them (§10).

> **Normative.** **The relevance read and the episodic supplement keep querying
> `goal.statement`**, which now means the current interpretation's outcome statement. The four
> call sites ADR-0248 §5 classified as reading *the goal* are not re-pointed, not widened to
> the request, and not given a second query: a turn takes **one** relevance read and **one**
> episodic supplement, and no lane concatenates the outcome statement with the request to make
> a query.

**The four query rows are answered by leaving them where they are, and that is the substantive
answer rather than an evasion.** ADR-0014 §1's own annotation designates the field for this —
`statement: str # canonical text rendering, used for retrieval` — and ADR-0248 §5 argued the
classification out in full: *"A query is not a quotation — nothing renders it to a user,
nothing attributes it to anyone, and no clause of the corpus claims it is the user's own words.
So the conservative reading, and the one the ratified text supports, is that retrieval reads
*the goal*."* ADR-0210 §1's clause — the evaluation is over the supply *"a **relevance read
taken with this turn's own goal statement** returned"* — stays literally true, and a reader
holding only ADR-0210 acts identically, so no record is owed against it (ADR-0082 §1).

**What this does and does not do for #2266, stated plainly.** #2266 records that on the M31
exit-sentence turn — *"find more about that, taking my preferences into account"* — retrieval
ran over a goal statement carrying *"no content word that any personal record is near"*, so the
supply reached the composer without the user's location or preferences. On a turn that
associates to a goal an earlier turn opened, this decision changes what that query **is**: it
becomes the accumulated outcome statement rather than the bare follow-up sentence, so the
exit-sentence turn would retrieve over what the goal is about rather than over four contentless
words. That is a real change in the right direction and it is **not a closure of #2266**. Two
of that issue's three candidate fixes — carrying the previous turn's selected records forward,
and giving the composer's population its own read — touch ADR-0238 §2's closure, which is
ratified and outside this fence; and the first turn of a goal is unchanged by §3, so a first
turn whose request is contentless retrieves exactly as badly as it does today. What reaches a
follow-up turn that the goal's statement still misses is the planner's own `read_request`
(ADR-0226 §4), which is the corpus's existing answer to *"the supply did not carry what I
need"* and whose bound is A3's.

> **Normative.** **`planning.planner._render_request` takes a `GoalBrief` and the turn's
> request.** It renders the outcome statement under the `Goal:` heading it already uses; the
> constraints, the success criteria and the conditions under **headings of their own**, each
> element with its ground **kind**; the status, the deadline and the open questions as it
> renders status and deadline today; and the **request under a heading of its own**, because
> the goal statement no longer carries it. It prints no identifier and no ground reference.

> **Normative.** `_render_request` prints **no goal-level `provenance`**. The field stays on
> `Goal` — ADR-0014 §1 requires it and its reason is unchanged — and it is not projected,
> because every element of the brief carries its own `Ground`, which is strictly more
> informative than one source value for the whole objective.

### 12. `PlanStore` widening, the wire, and the stored shapes

> **Normative.** `PlanStore` gains members and changes one, and this is a **BREAKING**
> contract change under golden rule 5:
>
> - **`save_goal` becomes the opening write alone.** It refuses a goal whose `id` the store
>   already holds, with the same error class an unknown goal already raises. An upsert that
>   replaced a whole goal would defeat §1's append-only interpretation and this section's
>   compare-and-swap in one call.
> - **`record_interpretation(revision: GoalRevision) -> Goal`** — appends one
>   `GoalInterpretation` to the named goal, performs §2's elision, advances `version`, and
>   returns the stored goal. `core/types.py` gains **`GoalRevision`**, a frozen command
>   carrying `goal_id`, the `GoalInterpretation`, and the `expected_version` it was computed
>   against.
> - **`open_attempt(attempt: GoalAttempt) -> str`**, **`get_attempt(attempt_id) ->
>   GoalAttempt | None`** and **`attempts_of(goal_id) -> tuple[GoalAttempt, ...]`** in
>   `opened_at` order.
> - **`commit_attempt(transition: AttemptTransition) -> GoalAttempt`** — the attempt's **only**
>   mutation route. `core/types.py` gains **`AttemptTransition`**, a frozen command carrying
>   `attempt_id`, the `expected_version`, and the fields it sets — `to_phase`, `to_state`,
>   `outcome`, `ended_at` and the effort members it advances, each optional and each leaving
>   its field unchanged where absent.

> **Normative.** **Both new writes are compare-and-swap, on ADR-0014 §5's existing discipline
> and for its existing reason.** `record_interpretation` succeeds only where the stored
> `Goal.version` still equals `expected_version`; `commit_attempt` succeeds only where the
> stored `GoalAttempt.version` still equals it. A stale write raises a `PlanningError` of the
> same class `StaleExecutionError` occupies for executions. **The read, the comparison and the
> write are one indivisible step**, and there is **no separate read on which a decision is
> taken** before either.

> **Normative.** The store accepts **commands, not snapshots**, for `record_interpretation`
> and `commit_attempt` alike. ADR-0014 §5's argument binds unchanged: *"Had the store taken a
> whole `ExecutionState`, any consumer of the Protocol could commit `PENDING → SUCCEEDED`
> directly and the claim that deterministic code owns state transitions (VISION §7) would rest
> on nobody choosing to bypass it."*

> **Normative.** **`delete_goal`'s cascade reaches attempts**, and ADR-0014 §5's rule — *"a
> goal the user deletes must not leave its plan history behind"* — is **extended rather than
> re-promised**. Its live-step refusal is unchanged: it keys on a `RUNNING` step, not on an
> attempt's state, and an attempt in a non-terminal state does not block a deletion.

> **Normative.** **No new Protocol is created**, so no new conformance suite and no new
> canonical fake is owed. The existing `PlanStore` conformance suite, the existing `Planner`
> conformance suite, `InMemoryPlanStore` and the canonical fakes in `ai_assistant.testing` each
> gain the new obligations **in the same change that adds them** (`CONTRIBUTING.md` → "Adding
> a Protocol": *"The triad is what a Protocol *change* is measured against too"*).

> **Normative.** **`PROTOCOL_VERSION` moves by exactly one**, on the single lane of §15 that
> changes the wire-visible surface, and `wire/envelope.py`'s log gains an entry naming this
> ADR and this reason. **`TurnResult.goal`'s change of type is the whole of the ground**:
> `TurnResult` is carried on `TurnOutcome.turn`, `TurnOutcome` is what the promoted surface
> returns, `TurnResult` sets `extra="forbid"` and `wire/codec.py` renders a model by
> `model_dump()`, so a hub emitting a `GoalBrief`-shaped `goal` is invalid for a client
> expecting a `Goal`-shaped one. That is ADR-0124 §9's second limb — *"a change to a
> wire-carried `core` type that makes a value one peer emits invalid for the other"* — and
> ADR-0178 §6 is the precedent for stating the bump in the deciding ADR rather than leaving the
> lane to discover it.

> **Normative.** **`PlanExport.schema_version` is a stored-record version and is not a second
> wire ground.** `PlanExport` crosses no frame: it is the portable document `PlanStore.export`
> returns, reached through that Protocol and emitted by no peer. It moves on ADR-0039 §10's own
> mechanism — *"`StepExecution` is inside the export, so its shape changing is exactly what the
> version exists to announce"* — and `wire/envelope.py`'s log records that separation, as
> ADR-0244 §17's entry already does for the converse case.

> **Normative.** No lane adds a compatibility shim, an optional-member negotiation, a
> per-member capability flag or a lenient decode to let two versions interoperate. ADR-0084
> §3's exact-match handshake is the mechanism and the refusal naming both versions is the
> intended user-visible outcome.

> **Normative.** **The parked-read store's `schema_version` moves by exactly one**, because
> `ParkedRead`'s stored object definition changes again. The upgrade reads no park content and
> rewrites none. **A park written before this decision is not repaired**: no lane back-fills,
> re-derives or re-validates a stored `goal` column, and ADR-0248 §3's transitional fallback is
> untouched.

> **Normative.** **Nothing else under `wire/` changes.** The connect exchange gains no member,
> no existing frame's encoding changes, no `FrameKind` is added, no codec entry is registered,
> and the promoted method set does not move.

> **Normative.** **No new class of content crosses the wire.** `GoalBrief` carries strictly
> less than the `Goal` it replaces on `TurnResult` and `ParkedRead`; ADR-0004 §5's rule that
> *"Tier 0/1 data must never be logged"* binds unchanged and nothing here logs a brief, an
> interpretation or an element.

**The figures, as prose rather than as a mark.** `PROTOCOL_VERSION` reads **36** at
`fc575d4d`, and ADR-0248 §7 schedules **36 → 37** for A0's implementation lane, which is in
flight; the parked-read store's `schema_version` reads **1** and ADR-0248 §7 schedules **1 →
2** on the same lane. A0 lands before A1 by the owner's dispatch, so the expected moves here
are **37 → 38** and **2 → 3**. They are stated as expectations and not as marks because the
obligation is *move by one on the lane that changes the surface*, and an ADR that fixed a
figure a sibling lane has not yet written would be stating a fact about the tree rather than a
decision (`CONTRIBUTING.md` → "No state claims in living documents").

### 13. What this ADR does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them. Each is named so that a reader cannot mistake this ADR's silence for a
> ruling, and each carries the condition that fires it.

- **Association over N candidates, focus, and what moves `last_engaged_at`.** A2. Fired by
  this ADR landing: the field exists and nothing reads it until A2 says what does.
- **Materiality, when a question is asked, and the `GoalQuestion` record and its store.** A2.
  Fired by this ADR landing. `GoalBrief.open_questions` carries texts and nothing else until
  then.
- **Resumption of a goal from another conversation by explicit reference** — an owner ruling
  of 2026-09-12 — and whether automatic cross-conversation association is ever built. A2.
  `Goal.conversation_id` is provenance and leaves room for both (§1).
- **Which user acts open an attempt.** A2 and A3. That an attempt is opened only by a user
  act is fixed in §5; which acts they are is not.
- **The bounded investigation loop, the per-attempt allowance, its reserve, progress and
  stopping, and any further member of `AttemptEffort`.** A3. Fired by this ADR landing.
- **`GoalEvidence`, the `PlanStore` members that hold it, the `requested`/`supported`
  composition, the verdict vocabularies, conflict adjudication, invalidation and the
  supersession rules.** A4. Fired by this ADR landing; §10 fixes what any such row must be
  able to answer.
- **`ActionPlan`'s step fields — `depends_on`, engine-resolved result references, the `when`
  vocabulary and `verifies`.** A5, which also fires ADR-0014 §7's output-references and
  step-dependencies deferrals.
- **Authorization: fixed values, permitted ranges, the basis triple, and coverage from several
  acts.** A6.
- **The plan-driving stage, and the mechanism that enforces §8's stale-target rule at the
  dispatch boundary** — including whether `StepTransition` carries the goal version and the
  attempt id it is claimed under. A7 and A9.
- **Retry, reconciliation, `EFFECT_UNRESOLVED` and modify-before-replace.** A8, which takes
  ADR-0014 §7's idempotency and `INDETERMINATE`-resolution deferral.
- **Verification against the goal's criteria, strength proportional to consequence, which
  `AttemptOutcome` member an attempt earns, and the producer of `GoalStatus.ACHIEVED`.** A10.
  §4 fixes that this ADR supplies none.
- **What else reaches a follow-up turn's supply** — #2266's remaining candidates. Fired by an
  ADR against ADR-0238 §2's closure, which §11 declines to open.
- **Whether ADR-0244 §3's one-open-park-per-conversation rule survives ADR-0247 §5.** Booked
  by the owner on 2026-09-12 as a separate contract review; untouched here.

### 14. Records owed on earlier ADRs, under ADR-0082 §1

**ADR-0228 §1 — partially superseded**, in one sentence, and the header records it. The clause
reads *"The revision carries the **same `goal_id`** as the plan it replaces. The goal is minted
once per turn from the user's unrewritten words and nothing about it changed; a second goal
would make one turn look like two in every store that holds goals."* Its second sentence states
two things that stop being true: a goal is **not** minted per turn once a turn may associate to
a goal an earlier turn opened, and its statement is **not** the user's unrewritten words once
§1 makes it the current outcome. A reader holding only ADR-0228 would mint a goal on every turn
and read the utterance off it, which fails ADR-0070 §1's test on the supersession side. **The
first sentence and the reason are kept verbatim**, because what §1 was actually deciding —
the stability of the subject across a turn's two calls — is unaffected and is strengthened:
both calls now receive the same `GoalBrief` as well as the same `goal_id`.

**ADR-0014 §5 and §6 — partially superseded**, in the scopes the header names. §5's code block
enumerates eleven `PlanStore` members and §6's enumerates `plan`'s three parameters and its
`ActionPlan` return; a reader holding only ADR-0014 would implement eleven members with an
upserting `save_goal`, and a planner returning a bare plan, and would not conform. Both fail
ADR-0070 §1's test. The scope is the enumerations, the `save_goal` contract and the return
type: §5's compare-and-swap discipline, its commands-not-snapshots rule and its data-rights
obligations are **relied on as written and extended**, and §6's parameters-not-fetched argument
is quoted in ADR-0211 §2's own words and applied rather than moved. §5's `PlanExport` block is
in the same scope, for the same reason, in `attempts` alone.

**ADR-0014 §1 — fulfilled, and superseded in none.** Its sentence *"A `Goal` is deliberately
**not** the same thing as a user utterance"* becomes true of the implementation for the first
time; its *"`Goal` is a `core` type rather than a memory kind. A goal is planning input, not a
retrieval record"* is the ground for not making this a `MemoryKind` and binds entire; its
*"outlives any one conversation"* binds entire and is why §1 makes `conversation_id`
provenance rather than a fence. Its code block gains fields, which is the same kind of change
ADR-0226 §4 made to §2's `ActionPlan` block — additively, with no record owed against §2, as
ADR-0014's own header shows — and a reader holding only ADR-0014 §1 builds a conforming `Goal`
and reads a conforming `statement`. Applying ADR-0082 §1's test — *"Would a reader holding only the earlier
ADR now act differently, or read one of its clauses more widely than it now holds?"* — the
answer is no, so no record is owed and none is written.

**ADR-0244 §2 — partially superseded**, layering on ADR-0248's record, in the field count and
in `goal`'s type. A reader holding only ADR-0244 as ADR-0248 left it would refuse an eleventh
field and would expect `goal` to be a `Goal`. The scope is that and nothing else: the
three-content-fields clause as ADR-0248 widened it is **not** widened again, because `goal_id`
is an identifier that settlement keeps.

**ADR-0225 §1, ADR-0210 §1, ADR-0226 §3 and §4, ADR-0230 §4, ADR-0211 §2, ADR-0086 §4,
ADR-0213 §4, ADR-0004 §5 and §6, ADR-0178 §6 and ADR-0248 — relied on unchanged, and the
showings are above.** ADR-0225 §1 is not reached: ADR-0248 already moved the archived user
words to `turn.utterance`, and this decision changes what the *goal* carries, not what the
entry does. ADR-0210 §1's clause stays literally true (§11). ADR-0226 §3's labelling is the
mechanism §7 resolves grounds through, unchanged and unwidened; §4's `read_request` placement
is preserved by §7 in terms. ADR-0230 §4's containment argument is applied to a second seam,
which is a stacked addition and not an amendment. ADR-0211 §2's ruling is obeyed. ADR-0086 §4
and ADR-0213 §4 supply the elision shape and the fixed-constant shape respectively and neither
is widened. ADR-0248 is **fulfilled**: §8's list of what it left to A1 is what §§1–13 above
decide, and every clause of ADR-0248 binds entire.

### 15. The lane cut, and which lane moves the wire

> **Normative.** The implementation lands in **four lanes**, in this order, each a separate PR.
>
> - **L1 — the contract, with a green tree at unchanged behaviour.** `core/types.py` and
>   `core/protocols.py` gain every type and member above; the `PlanStore` conformance suite,
>   the `Planner` conformance suite, `InMemoryPlanStore`, `planning/sqlite_store.py` and the
>   canonical fakes in `ai_assistant.testing` gain the new obligations; and every call site is
>   moved mechanically so the tree type-checks — the loop opens a goal carrying revision 1
>   (§3) and projects a brief, and `planning/planner.py` returns `PlannerOutput(plan=…,
>   understanding=None)`. **No behaviour changes in L1.**
> - **L2 — the `Planner` seam.** `planning/` alone: `_render_request` renders the brief, the
>   request and the evidence digest; the model envelope proposes a `ProposedUnderstanding`.
> - **L3 — the `orchestration` threading.** `orchestration/` alone: recording the revision,
>   resolving grounds, stamping the phase, opening and committing attempts, setting
>   `targets_revision`, and removing `Engine`'s `save_goal` calls.
> - **L4 — the wire-visible consumers.** `TurnResult.goal`, `ParkedRead.goal` and `goal_id`,
>   `PlanExport`, and their stores. **L4 moves `PROTOCOL_VERSION` and the parked-read store's
>   `schema_version`, and it is the only lane that moves either.**

> **Normative.** **L1 is the one sanctioned cross-subsystem lane**, and it is sanctioned by
> ADR-0137 §2, which makes *"the **contract triad together with its primary production
> implementation** … one unit of work — one lane, one PR"* and fixes that *"Primary means the
> consumer whose demands shape the contract, not the one that is cheapest to write"* — here
> the `PlanStore` implementations, which are what the interpretation chain, the elision and the two
> compare-and-swap writes are actually shaped by. **L2, L3 and L4 are each one subsystem**, and
> no other cross-subsystem pairing is authorised by this decision.

**Why L1 cannot be smaller, stated rather than assumed.** A `Planner.plan` signature change is
not confinable to `planning/`: `core/protocols.py` declares it, `planning/planner.py`
implements it, `ai_assistant.testing` fakes it and `orchestration/loop.py` calls it, and a PR
that moved fewer than all four would not type-check under `mypy --strict`. ADR-0137 §2's
argument is exactly the one that applies — the contract *"stays **soft while its hardest
consumer stress-tests it**"* — and the alternative, ratifying the seam and discovering its
shape a lane later, is the failure that section exists to prevent.

**Why the behaviour is held back to L2 and L3 rather than riding L1.** L1 is a large mechanical
diff and a review of it is a review of a translation; L2 and L3 are where the judgements are,
and a reviewer reading them is reading a decision rather than a rename. That is the same
division ADR-0137 §2 draws between the triad and its consumers, applied inside one contract
change.

### 16. The arms this decision owes

> **Normative.** The lanes implementing this decision owe representative-input tests for each
> of the following, and a lane that lands without its arm has not discharged this ADR.

1. **S1, end to end.** *"What is two plus two?"* on a conversation's first turn: a goal opened
   at revision 1 whose outcome is the stripped request; **one** `Planner.plan` call and **one**
   composing call, which is exactly today's cost; six phase stamps; no read request; no
   question; one attempt ending `ENDED`/`ANSWERED`; and the goal's status still **`ACTIVE`**.
2. **S2's understanding half.** *"Actually, make it Sunday"* against a goal whose earlier
   attempt booked a campsite: a **new attempt** on the **same** goal, a new interpretation
   revision whose `raised_by` names this turn and whose changed element grounds `USER_STATED`
   on a span of this turn's request, and every prior revision retained unedited.
3. **The writer clause.** A planner double returning an envelope carrying a phase, a revision
   number, a `raised_by` and a `recorded_at` — every one discarded, the turn not degraded, and
   the stamped values `orchestration`'s.
4. **The namer rule.** A planner double that renders **every field of every value it receives**
   into its prompt produces a prompt in which no goal id, no evidence id and no span reference
   of that turn appears — the structural half asserted over `GoalBrief`'s and
   `EvidenceDigest`'s field sets, the behavioural half over the rendered prompt. This is
   ADR-0230's arm 20 shape applied to this seam.
5. **Ground resolution and its refusals.** A `FROM_EVIDENCE` element whose label is outside the
   shown set, and a `USER_STATED` element whose span is not a span of the turn's request: each
   dropped from the recorded revision, silently, with the revision's `outcome` still recorded
   and the turn unharmed.
6. **The stale-target rule.** A plan whose `targets_revision` is not the goal's current
   revision is not driven; and a plan the loop built carries the `revision` of the
   interpretation whose brief it projected for that call, whatever the planner returned in that
   field.
7. **`ACHIEVED` has no producer.** Over the whole implementation, no assignment of
   `GoalStatus.ACHIEVED` exists anywhere under `src/` — asserted as a test over the shipped
   tree, not as a review convention, so that a later lane cannot supply one without the ADR
   that decides it.
8. **The bootstrap is byte-equal.** On a goal's first turn, revision 1's `outcome`,
   `Goal.statement` and `TurnResult.utterance` are the same string, which keeps ADR-0248 §6's
   assertion true on that path.
9. **The elision is bounded and disclosed.** A goal driven past `MAX_GOAL_INTERPRETATIONS`
   revisions keeps the current one, drops the oldest, and reports the count; the count never
   decreases; and no elision is silent.
10. **Both compare-and-swap writes.** Two `record_interpretation` calls computed against the
    same `expected_version`: one succeeds and one raises, with no interpretation lost and no
    interleaving; the same for two `commit_attempt` calls. Run against **both** conforming
    `PlanStore` implementations through the shared suite.
11. **The export closes.** A `PlanExport` carrying an attempt whose `goal_id` the document does
    not hold does not validate; one whose references all resolve does; `schema_version` reads
    the new value and a document at the previous value does not validate at all.
12. **`delete_goal` reaches attempts**, and an attempt in a non-terminal state does not block a
    deletion that no `RUNNING` step blocks.
13. **An element-free brief is well-formed.** A goal at revision 1 plans without a question
    being raised on the ground that the brief carried no elements.

### 17. This ADR classified under ADR-0070 §1 and ADR-0082 §1

> **Normative.** This is a **substantive contract ADR** under `CONTRIBUTING.md` → "Contract
> ADRs land before their implementation": it changes Protocols and `core` types that cross
> subsystem boundaries. It ships as its own PR, is reviewed by **both** lenses while
> `Proposed`, and is ratified only once that set is green on one tree (ADR-0015 §5, ADR-0165).
> No implementation lands in this PR.

This ADR is marked, so ADR-0089 §3 governs: the block quotes above are the whole of what binds,
and the prose beside them is read to determine what a marked clause means.

## Consequences

**What becomes possible.** A turn can change what the system understands without losing what it
understood before, and can say which turn changed it and on what ground. A plan can be checked
against the understanding it was formed for. An attempt can record how far it got and how much
it spent, separately from whether the objective was reached. And every lane from A2 to A10 has a
value to write into instead of a field to invent, which is the whole reason this ADR is one
lane and not ten.

**What becomes harder.** `Goal` stops being a value a test can build in one line: it needs a
conversation, a turn and at least one interpretation. `Planner.plan`'s signature moves again —
ADR-0211 added `capabilities`, and `core/protocols.py`'s own note records that *"ADR-0230 §3 and
ADR-0240 §7 each add one"* — and every fake, every conformance arm and every benchmark harness
call site moves with it. The four-lane cut means
four reviews and four base moves rather than one, and L1's diff is large even though its
behaviour is unchanged.

**What is deliberately left uncomfortable.** A goal that was fully served stays `ACTIVE` until
A10 lands (§4), and a first turn whose request is contentless retrieves exactly as badly as it
does today (§11). Both are legible gaps with named owners, and both are better than a producer
or a query nobody argued for.

**What would trigger revisiting this.** A2 discovering that association needs something on the
goal that §1 does not carry; A4 discovering that `EvidenceDigest`'s six members cannot project
the row it needs; A3 discovering that `AttemptEffort`'s two counters cannot express its
allowance. Each is an additive `core` change with its own ADR, which is the shape ADR-0211 §2
argues a keyword list and a small projection are chosen for.

## Alternatives considered

**One large `Goal` object holding plans, attempts, executions and evidence inline.** Rejected.
The interpretation is one coherent value read and written together and a brief must be
projectable from it without a second read, which is why it is inline; plans, attempts and
executions are written at different rates by different stages, and inlining them would make
every interpretation write rewrite an execution log. ADR-0014 §3's `approval_ref` pattern —
*"deliberately a foreign key and not a copy of the decision"* — is the precedent for the split.

**Keeping `statement` as a stored field kept in step with the current revision.** Rejected in
§1: two records of one fact, and nothing in the type stops them disagreeing. The projection
costs one thing — a `Goal` can no longer be constructed by setting `statement` alone, and a
serialised goal no longer carries the string under that name — and buys the invariant outright.

**Passing the whole `Goal` to `Planner.plan` and relying on `_render_request` not to print the
ground references.** Rejected in §9 on ADR-0230 §4's stated ground: *"that is a property of the
types rather than a rule a planner is trusted to keep."* It would also make every future field
of `Goal` a namer-rule question re-answered at the render site.

**A planning-input bundle replacing the keyword list.** Rejected in §7 by applying ADR-0211 §2
rather than reopening it: a frozen `core` model is harder to extend than a keyword list, and
this seam is scheduled to be extended again by A3, A4 and A5.

**Letting the planner name the revision its plan targets.** Rejected in §8. The loop already
holds the number on the goal it projected the brief from, so the planner would be reporting a
value the loop has; the brief would have to carry a number the planner has no use for; and a
number a model wrote into a durable audit chain is unprovenanced, which is ADR-0228 §5's ground
for taking `supersedes` off the planner in the first place.

**A ground that crosses the seam as a record identifier rather than a label.** Rejected in §7.
It would breach ADR-0228 §8's namer rule directly, and the label scheme ADR-0226 §3 already
fixes resolves the same intent while keeping §3's own inert failure mode: *"a label the planner
invents is an index, and an index outside the range it was shown resolves to nothing"*.

**A fifth `GoalStatus` member for "paused".** Rejected in §5: a status member would be a second
authority that can disagree with the attempt it is supposed to summarise. The derivation is
stated once in §5 so two surfaces cannot render it differently.

**Giving `GoalStatus.ACHIEVED` a producer here — the composing stage, on a turn that answered.**
Rejected by the owner's correction of 2026-09-12 and argued in §4: producing a reply establishes
nothing about the requested outcome, and a status claiming otherwise would assert a comparison
nothing performed.

**Minting `GoalEvidence` here with A4's fields left open.** Rejected in §10: a type ratified
with no content is a type the first real consumer must reopen. Fixing the **digest** instead
gives the planner what it can act on and gives A4 a stated obligation without a ratified empty
box.

**Querying retrieval with the request, or with the request and the outcome statement
concatenated.** Rejected in §11. The request is already on the turn (ADR-0248 §1) and is
rendered to the planner under its own heading, so nothing is lost by not querying with it;
ADR-0014 §1 designates the statement for retrieval; and a concatenated query is a third value
nobody wrote, embedded as though someone had.

**Landing the whole implementation as one lane.** Rejected in §15. The contract change alone
touches four packages by necessity, and adding the behaviour to it would make one review cover
both a mechanical translation and every judgement this ADR takes.

Refs: ADR-0248, ADR-0228, ADR-0014, #2255, #2266
