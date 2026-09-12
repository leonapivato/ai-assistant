# 249. The goal carries its interpretation, the attempt carries the phase, and the planner receives a brief and returns its understanding

- Status: Proposed
- Date: 2026-09-12
- **Partially supersedes** [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md)
  — **§1's third clause in its second sentence alone: "The goal is minted once per turn from
  the user's unrewritten words and nothing about it changed" is false of a goal that carries
  an interpretation, and false of a turn that associates to a goal an earlier turn opened.
  Nothing else in that ADR.** §1's subject-stability rule — *"The revision carries the **same
  `goal_id`** as the plan it replaces"* — binds **verbatim**, and its reason, *"a second goal
  would make one turn look like two in every store that holds goals"*, binds entire. The two
  calls of a turn plan for the same **goal**; where the first call revised the understanding
  they receive briefs of different revisions, and §1 neither said nor needed otherwise. §1's authored-at-the-seam
  clause, its context-assembled-once clause, its nothing-else-is-re-run clause and its
  capability-re-read clause are relied on unchanged, and §§2–15 are untouched **but for the
  second scope below**.

  **And §1's one-field clause together with §5's every-other-field clause, in the count
  alone**: *"The **one** field any other component ever sets is `supersedes`"* and *"Every
  other field is **exactly as the planner returned it**"* become two fields, `supersedes` and
  `targets_revision`, both under §5's identical discipline — taken by the loop, taken once,
  immediately on return, discarding whatever the plan came back carrying. Every remaining field
  of every plan is still exactly as the planner returned it, §5's discard-silently clause, its
  no-plan-identifier clause, its `save_plan` refusal, its export-closure clause and its
  persistence clauses bind entire, and §1's authored-at-the-seam enumeration is untouched
  because `targets_revision` is not among the five fields it names.
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
  bind entire and are the grounds this ADR reasons from. **And §1's `Goal` model declaration**:
  `statement` ceases to be a constructor field and becomes a read-only projection absent from
  the dump, and `conversation_id`, `interpretation`, `interpretation_elided`, `version` and
  `last_engaged_at` join the declaration, so a reader holding only §1 writes
  `Goal(statement=…)` and does not build a conforming `Goal`. **§1's prose is fulfilled and
  superseded in none** — its not-an-utterance rule, its `core`-type-not-memory-kind rule, its
  used-for-retrieval annotation, its outlives-any-one-conversation clause and its `Provenance`
  sentence each bind entire (§14) — and §§2, 3, 4 and 7 are untouched.
- **Partially supersedes** [ADR-0248](0248-the-users-request-is-its-own-value-on-the-turn-and-the-goal-statement-stops-standing-in-for-it.md)
  — **§3's fallback clause in its accessor alone: where a park carries no `utterance`,
  `Engine._resume_read` takes `park.goal.outcome` rather than the parked `Goal.statement`,
  because §12 converts a pre-decision park's `goal` column to a `GoalBrief`. Nothing else in
  that ADR.** The bytes are identical — the conversion sets `outcome` from the stored
  `statement` — so §3's *"That reading is exact for the whole life of the fallback"* binds
  entire and stays true; the fallback is still the only site that may take it, is still not
  widened to a park carrying an `utterance`, to a blank one, to any other reader of §5's table
  or to any other site, and is still not removed. §§1, 2, 4-13 stand entire, and §8's list of
  what it left to A1 is what this ADR decides.
- **Partially supersedes** [ADR-0049](0049-a-durable-plan-store.md)
  — **§1's migration clause alone: "The migration is table creation only. There is no prior
  persistent `PlanStore` and therefore no on-disk schema to evolve" stops being true, and §12
  lands that store's first migration, 1 → 2. Nothing else in that ADR.** §1's durable
  `meta("schema_version")` marker is relied on as the thing it was written for — *"so a
  **future** schema change has the version marker"* — its loud refusal of a database *"whose
  `schema_version` is **newer** than the code understands"* binds entire, and §1's schema, its
  foreign keys, its live-execution ordering and §§2–5 are untouched.
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
> are exactly: `revision`, an `int` at least 1, minted one greater than the revision it follows
> in the goal's **history** — which after §2's elision need not be the element before it in the
> tuple;
> `outcome`, a `NonBlankEncodableText` stating the understood outcome; `constraints`,
> `criteria` and `conditions`, each a possibly-empty `tuple[GoalElement, ...]`;
> `recorded_at`, a `UtcInstant`; and `raised_by`, an `Identifier | None` naming the
> conversation turn whose message caused this revision. It carries no plan, no attempt, no
> evidence and no status.

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

> **Normative.** `Goal.conversation_id` is an `Identifier | None` naming the conversation the
> goal was **opened in**. It is provenance and **not a fence**: no clause of this ADR makes a
> goal unreachable from another conversation, and whether and how a goal is resumed from one is
> A2's (§13). ADR-0014 §1's *"a goal … **outlives any one conversation**"* binds entire.

> **Normative — the three fields that admit absence, and the one route that produces it.**
> `Goal.conversation_id`, `Goal.last_engaged_at` and `GoalInterpretation.raised_by` are each
> typed `| None`, and **`None` is reachable by exactly one route: a row written before this
> decision** (§12). **No lane writes `None` into any of them.** `orchestration` supplies all
> three on every goal it opens and every revision it records, and an implementation that leaves
> one absent on a value it authored does not conform. This is ADR-0248 §3's move applied to
> three more fields for its own reason: requiring them would make every stored goal fail to
> decode, and a goal that cannot be read is worse than one whose provenance says, truthfully,
> that this system did not record it.

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

> **Normative.** `Goal.last_engaged_at` is a `UtcInstant | None` stamped when a turn engages
> the goal. **What engages a goal is A2's** (§13), and no lane in this decision reads
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
called: in `LearningLoop.respond` and again in `LearningLoop.resumed_read`, `_retrieve` and
`_supplement` are both given the goal's statement above the planner call, and the
interpretation the planner proposes is a *result* of that call. So on a goal's first turn there is no interpretation in
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

> **Normative.** **A label naming a record that resolves in no store does not resolve here
> either.** A search-minted record stands in the supply and carries a valid label, and ADR-0231
> §16 rules that it *"is not a citation target and not a durable reference … its `id` is minted
> for one turn … and resolves in no store"*. So a `FROM_EVIDENCE` element whose label names one
> is **dropped**, exactly as an out-of-range label is: an interpretation is a durable audit
> record, and a durable record grounded on an identifier nothing can retrieve states a warrant
> it cannot show. **How a search finding grounds an element is A4's** (§13) — through an
> evidence row keyed on the goal, not through an id into `memory`.

> **Normative.** An element whose ground does not resolve — a label outside the shown set, a
> label naming a minted record, a span that is not a span of this turn's request — is **dropped
> from the recorded revision**, silently and without failing the turn, exactly as ADR-0226 §3
> drops a label outside the shown set. A `ProposedUnderstanding` **all** of whose elements are
> dropped still records its `outcome`, because the outcome is not grounded per element.

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

> **Normative.** `ActionPlan` gains one field, **`targets_revision: int | None`**, `ge=1` where
> present and **defaulting to `None`**, naming the `GoalInterpretation.revision` the plan was
> planned against. `None` means **not yet stamped**, and it is the only value a planner can
> return, because `GoalBrief` carries no revision for a planner to copy.

> **Normative.** **The unstamped state exists only between the planner's return and the loop's
> stamp, and `PlanStore.save_plan` refuses a plan that still carries it** — with the same error
> class ADR-0228 §5 gives an unresolvable `supersedes`, and for the same reason: the window is
> closed at the store rather than trusted to close itself. A plan **already on disk** carrying
> `None` — the one route being a row written before this decision (§12) — decodes, and §8's
> not-driven rule below reads it as targeting no revision, so it is **not driven**.

> **Normative.** **The loop sets it, and the planner never does.** On every plan a planner
> returns, the loop takes the field for its own: it discards any value the plan came back
> carrying and sets it to **the goal's current `revision` at the moment it takes the plan —
> after this same call's `understanding`, if any, has been recorded**. It does this **once** per
> plan, immediately on return and before any other component observes it, and a value the
> planner supplied is discarded **silently**. The value is one the loop holds on the `Goal`
> itself, which is why `GoalBrief` need not and does not carry it (§9).

> **Normative — a plan is never stale against the understanding it was returned with.** A
> `Planner.plan` call decides the understanding and the plan **in one pass**, so the plan
> embodies the understanding rather than predating it, and the revision it targets is the one
> that call produced. Ordering the stamp after the recording step is the whole of what makes
> that true: stamping the *input* revision would leave every turn on which the planner revised
> its understanding holding a plan §8 forbids driving, with no serviced read to license a second
> call (ADR-0228 §2) — a conforming path through the most ordinary response there is.

> **Normative — ADR-0228's one-field clause becomes a two-field clause, and nothing else about
> it moves.** §1's *"The **one** field any other component ever sets is `supersedes`"* and §5's
> *"Every other field is **exactly as the planner returned it**"* are **partially superseded in
> that count alone**: the fields any other component sets are `supersedes` and
> `targets_revision`, both under §5's identical discipline — taken by the loop, taken once, at
> the same moment, discarding whatever came back — and every remaining field of every plan is
> still exactly as the planner returned it. §1's authored-at-the-seam clause binds entire and is
> untouched: `targets_revision` is not among the fields it enumerates (`id`, `goal_id`, `steps`,
> `rationale`, `read_request`), and no implementation authors or edits any of those anywhere but
> at the `Planner.plan` seam.

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

> **Normative.** **The loop builds the goal record and its revisions; `Engine` persists them**,
> at the one site that persists a plan today. `Engine`'s `self._plans.save_goal(turn.goal)`
> calls stop reading the turn — a turn carrying a projection carries no record to save — and
> read the carrier instead: the record travels **inside `ai_assistant.orchestration` as data**,
> adding no member to any Protocol and riding on no wire-carried type. That is the carrier
> shape ADR-0242 §7 already uses, and it is what keeps ADR-0228 §5's prohibition intact —
> *"no lane adds a second persistence site, gives `LearningLoop` a `PlanStore`, or carries a
> plan out of a failing turn in order to write it."* **No lane gives `LearningLoop` a
> `PlanStore`.**

> **Normative.** ADR-0228 §5's rule that *"A turn that ends before that site persists nothing,
> exactly as it does today"* binds for the goal and the attempt exactly as it binds for the
> plan: a turn that ends early leaves no goal row, no attempt row and no plan row, and no lane
> adds a second site to write one sooner.

> **Normative.** **`ParkedRead.goal_id` is an identifier and not a resolution guarantee.** A
> park whose goal the store does not hold — the one route being a turn that parked and then
> ended before its persistence site — is answerable exactly as ADR-0248 §3's `utterance`-less
> park is: the association finds nothing and the resumption proceeds on what the park itself
> carries. No lane repairs, back-fills or refuses such a park, and no lane reorders persistence
> to prevent it.

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

> **Normative.** **The relevance read and the episodic supplement keep querying the goal's
> current outcome statement.** In `LearningLoop.respond` they read it as `goal.statement`,
> unchanged at the call site; in `LearningLoop.resumed_read` the value comes off the park, which
> now carries a `GoalBrief`, so those two read **`brief.outcome`** — the same value under the
> name the projection gives it (§9), and on a converted park the same bytes the stored
> `statement` held (§12). None of the four is widened to the request or given a second query: a
> turn takes **one** relevance read and **one** episodic supplement, and no lane concatenates
> the outcome statement with the request to make a query.

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
>   `outcome`, `ended_at`, the effort members it advances, and **`add_plan_id`,
>   `add_execution_id` and `add_authorization_id`**, each an `Identifier | None`. Every member
>   is optional and every absent member leaves its field unchanged.

> **Normative.** **The three reference tuples grow by append and never by replacement.** An
> `add_*` member appends its identifier to the corresponding tuple; an identifier the tuple
> already holds is ignored rather than duplicated or refused; and no member of
> `AttemptTransition` removes, reorders or replaces an identifier.

> **Normative — opening an attempt and persisting one are two acts, and only the second is
> bound by §11.** An attempt is **opened in memory** when the user act that opens it occurs,
> which is before the turn's first planner call; it is **first written** at the one site §11
> names, together with the goal, its revisions and the turn's plans, carrying every phase stamp,
> state move and reference the turn had produced **by that moment**. A turn that ends before
> that site writes no attempt row, exactly as it writes no goal row and no plan row.

> **Normative — after the first write, every change goes through `commit_attempt`, in this turn
> as in any later one.** The site §11 names precedes `start_execution` and precedes composition,
> so an execution id, an authorization id, the phase reaching `VERIFY`, the terminal `state` and
> the `outcome` a turn earns are all facts that do not exist yet when the row is first written.
> Each reaches the store through a `commit_attempt` under §12's compare-and-swap, at the moment
> the fact becomes true. **Nothing buffers a transition, nothing replays one, and no lane writes
> an attempt that claims a result before it happened** — an attempt whose `outcome` is
> `ANSWERED` is written after the answer exists, which is the whole of what `ANSWERED` asserts
> (§5).

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

> **Normative.** **`PROTOCOL_VERSION` moves by exactly one, in the same change that makes a
> wire-carried value one peer emits invalid for the other**, and `wire/envelope.py`'s log gains
> an entry naming this ADR and the reason. That is ADR-0124 §9's second limb quoted rather than
> restated — *"a change to a wire-carried `core` type that makes a value one peer emits invalid
> for the other, whether the change widens or narrows the type"* — and §15 cuts the lanes so
> that **exactly one** lane satisfies it, which is what makes the bump singular rather than a
> property of the cut.

> **Normative.** **Three changes of this decision are each independently that ground, and the
> lane carrying any of them carries the bump.** `Goal` gains required fields and loses
> `statement` from its dump; `ActionPlan` gains `targets_revision`; and `TurnResult.goal`
> changes type. `TurnResult` is carried on `TurnOutcome.turn`, `TurnOutcome` is what the
> promoted surface returns, `TurnResult`, `Goal` and `ActionPlan` all set `extra="forbid"`, and
> `wire/codec.py` renders a model by `model_dump()` — so each of the three, on its own, makes a
> hub's turn undecodable by a client at the previous version. **No lane lands one of them
> without the bump**, and ADR-0178 §6 is the precedent for stating that in the deciding ADR
> rather than leaving a lane to discover it.

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

> **Normative.** **Every stored row this decision reshapes stays readable, and this decision
> lands the migrations that make that true.** `ParkedRead` and `Goal` both change shape on
> disk, and both stores hold rows written before it. A refusal to open, a silent failure to
> decode, and a row read back with a fabricated value are each ruled out: ADR-0244 §15 —
> *"**A park survives a restart and is offered again**"* — is the obligation for one store, and
> ADR-0004 §6's export and deletion rights are the obligation for the other.

> **Normative.** **The parked-read store's `schema_version` moves by exactly one, and its
> upgrade converts the `goal` column.** A stored `goal` object of the pre-decision shape is
> read and rewritten as a `GoalBrief`: `goal_id` and the record's new `goal_id` column both
> from its `id`; `outcome` from its `statement`; `status` and `deadline` carried across;
> `constraints`, `criteria`, `conditions` and `open_questions` empty. **The conversion is
> lossless and not a fabrication**: by §3 a goal opened before this decision has exactly one
> interpretation, whose outcome is its statement, so the brief states what the record already
> said and invents nothing. This upgrade **does** read park content, unlike ADR-0248 §7's,
> because its alternative is a park that cannot be decoded at all; it writes no new content, and
> ADR-0004 §5's rule that *"Tier 0/1 data must never be logged"* binds it unchanged.

> **Normative.** **A pre-decision park's stored `plan` is left byte for byte as it is**, decodes
> with `targets_revision` `None`, and its resumption is unaffected: ADR-0244 §8 composes a
> resumed turn from the park and drives no step, so a plan that §8 refuses to drive costs such a
> park nothing.

> **Normative — ADR-0248 §3's fallback moves one accessor and nothing else.** §3 rules that
> where a park carries no `utterance`, `Engine._resume_read` *"takes the parked `Goal.statement`
> instead, and it is the only place in the system that may"*. A converted park carries a
> `GoalBrief`, which has no `statement`, so **the fallback reads `park.goal.outcome`**. The
> value is the **same bytes**: §12's conversion sets `outcome` from the stored `statement`, and
> §3's own clause that *"That reading is exact for the whole life of the fallback, and A1 does
> not change that"* stays true — this decision changes the field's name at that site and not
> what it holds. §3's every other clause binds entire: the fallback is still **not widened** to
> a park that carries an `utterance`, to a blank one, to any other reader of ADR-0248 §5's table
> or to any other site; it is still **not removed**, and no lane removes it while a park lacking
> an `utterance` can be answered.

> **Normative.** **The plan store's on-disk `schema_version` moves 1 → 2, and this decision
> lands that store's first migration.** ADR-0049 §1 wrote the marker for exactly this — *"A
> durable `meta("schema_version")` row is written at creation so a **future** schema change has
> the version marker"* — and its loud refusal is stated of a database *"whose `schema_version`
> is **newer** than the code understands"*, which a version 1 store is not. A version 1 store is
> upgraded in place rather than refused: each `goals` row
> gains an `interpretation` of exactly one revision, whose `outcome` is the row's stored
> `statement`, whose `recorded_at` is its `created_at`, and whose `raised_by` is **absent**;
> `conversation_id` and `last_engaged_at` are **absent**; `version` and `interpretation_elided`
> are 0; and each `plans` row's `targets_revision` is **absent**.

> **Normative.** **The migration writes no value this system did not record, and the absences
> are the whole of how it says so.** It does not invent a turn id for `raised_by`, a
> conversation for `conversation_id`, an instant for `last_engaged_at` or a revision for
> `targets_revision`; §1's three-fields clause and §8's unstamped clause admit exactly these
> rows and no others. A synthesised `raised_by` would attribute an understanding to a turn that
> never raised it, which is the falsehood §2 refuses silent truncation on the same ground.

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
- **How a search finding grounds an interpretation element.** A4. §7 drops a `FROM_EVIDENCE`
  ground naming a search-minted record, because ADR-0231 §16 makes such a record *"not a
  durable reference"* whose id *"resolves in no store"*, and a durable interpretation grounded
  on one would state a warrant it cannot show. The route A4 has is an evidence row keyed on the
  goal; nothing here forecloses it, and nothing here opens ADR-0231 §16.
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
the stability of the *subject* across a turn's two calls — is unaffected: both calls plan for
one goal under one `goal_id`. What is **not** claimed is that both calls see the same
`GoalBrief`. Where the first call revised the understanding, §8 records that revision and the
second call receives the brief of the new one — which is the owner's third correction working
rather than a breach of §1. §1 fixed the subject, not the view of it, and a second call planning
against an understanding the first call superseded is exactly what correction 3 forbids.

**ADR-0014 §5 and §6 — partially superseded**, in the scopes the header names. §5's code block
enumerates eleven `PlanStore` members and §6's enumerates `plan`'s three parameters and its
`ActionPlan` return; a reader holding only ADR-0014 would implement eleven members with an
upserting `save_goal`, and a planner returning a bare plan, and would not conform. Both fail
ADR-0070 §1's test. The scope is the enumerations, the `save_goal` contract and the return
type: §5's compare-and-swap discipline, its commands-not-snapshots rule and its data-rights
obligations are **relied on as written and extended**, and §6's parameters-not-fetched argument
is quoted in ADR-0211 §2's own words and applied rather than moved. §5's `PlanExport` block is
in the same scope, for the same reason, in `attempts` alone.

**ADR-0014 §1 — partially superseded in its `Goal` model declaration, and fulfilled in its
prose.** The two halves come apart, and the showing is why.

Its **model declaration** is superseded. §1 declares `statement: str` as a constructor field of
`Goal` and enumerates six fields. After §1 of this decision `statement` is not a field at all —
it is not accepted in a constructor and does not appear in a dump — and `conversation_id`,
`interpretation`, `interpretation_elided`, `version` and `last_engaged_at` join the declaration.
A reader holding only ADR-0014 §1 writes `Goal(statement=…)` and does **not** build a conforming
`Goal`, which is ADR-0070 §1's test coming out on the supersession side. This is **not** the
additive case ADR-0226 §4 made against §2's `ActionPlan` block, where every earlier constructor
call still worked: a field that stops being constructible is a different kind of change, and it
is recorded as one.

Its **prose binds entire and is fulfilled**. *"A `Goal` is deliberately **not** the same thing as
a user utterance"* becomes true of the implementation for the first time; *"`Goal` is a `core`
type rather than a memory kind. A goal is planning input, not a retrieval record"* is the ground
for not making this a `MemoryKind`; *"canonical text rendering, used for retrieval"* is the
ground §11 reads the query off; and *"a goal … **outlives any one conversation**"* is why §1
makes `conversation_id` provenance rather than a fence. §1's `Provenance` sentence is untouched
and the field stays on `Goal`.

**ADR-0248 §3 — partially superseded**, in its fallback clause's accessor alone, and the header
records it. §3 rules that where a park carries no `utterance`, `Engine._resume_read` *"takes the
parked `Goal.statement` instead, and it is the only place in the system that may"*. §12 converts
a pre-decision park's `goal` column to a `GoalBrief`, which has no `statement`, so a reader
holding only ADR-0248 would read a field that is not there — ADR-0070 §1's test coming out on
the supersession side. The scope is the accessor: the fallback reads `park.goal.outcome`, over
**the same bytes**, so §3's *"That reading is exact for the whole life of the fallback, and A1
does not change that"* binds entire and is vindicated rather than weakened. §3's no-widening
clause, its only-place clause, its no-removal clause and its permission for a later change to
delete it all bind entire.

**ADR-0049 §1 — partially superseded**, in its migration clause alone, and the header records
it. §1 reads *"**The migration is table creation only.** There is no prior persistent
`PlanStore` and therefore no on-disk schema to evolve: a fresh database is the only starting
state this store has ever had."* After this decision there is a prior on-disk schema to evolve
and §12 evolves it, so a reader holding only ADR-0049 would implement table creation and refuse
a version 1 database — ADR-0070 §1's test coming out on the supersession side. The scope is that
clause: §1's `meta("schema_version")` marker is **relied on as the thing it was written for**
and is quoted in §12 as such; §1's loud refusal of a database *"whose `schema_version` is newer
than the code understands"* binds entire; and §1's schema, its foreign keys, its live-execution
ordering and §§2–5 are untouched.

**ADR-0228 §1's one-field clause and §5's every-other-field clause — partially superseded**, in
the count alone, and §8 states the showing. A reader holding only ADR-0228 would refuse to let
any component set a second field of a plan; after this decision two are loop-owned, under §5's
identical discipline — taken by the loop, taken once, discarding whatever came back. Nothing
else about either clause moves, and §1's authored-at-the-seam enumeration is untouched because
`targets_revision` is not among the fields it names.

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
is widened. **ADR-0248 is fulfilled** — §8's list of what it left to A1 is what §§1–13 above
decide — and is partially superseded in its §3 accessor alone, recorded above; every other
clause of ADR-0248 binds entire, its §1 request value being what makes §7's span check
buildable at all.

### 15. The lane cut, and the one lane that moves the wire

> **Normative.** The implementation lands in **three lanes**, in this order, each a separate PR.
>
> - **L1 — the contract, the wire and the stored shapes, at unchanged behaviour.**
>   `core/types.py` and `core/protocols.py` gain every type and member above, **including**
>   `TurnResult.goal`'s change of type, `ParkedRead.goal` and `goal_id`, and `PlanExport`. Both
>   conforming `PlanStore` implementations, the `PlanStore` and `Planner` conformance suites and
>   the canonical fakes in `ai_assistant.testing` gain the new obligations; §12's two store
>   migrations land; and every call site is moved mechanically so the tree type-checks — the
>   loop opens a goal carrying revision 1 (§3), projects a brief, stamps `targets_revision`
>   (always 1 in this lane), and hands the record to `Engine` on §11's carrier, while
>   `planning/planner.py` returns `PlannerOutput(plan=…, understanding=None)`. **L1 moves
>   `PROTOCOL_VERSION`, the plan store's `schema_version`, the parked-read store's
>   `schema_version` and `PlanExport.schema_version`, and it is the only lane that moves any of
>   them.** No behaviour changes in L1: no attempt is opened, no phase is stamped, no
>   understanding is proposed and no ground is resolved.
> - **L2 — the `Planner` seam.** `planning/` alone: `_render_request` renders the brief, the
>   request and the evidence digest; the model envelope proposes a `ProposedUnderstanding`.
> - **L3 — the `orchestration` threading.** `orchestration/` alone: recording the revision,
>   resolving grounds, stamping the phase, and opening and committing attempts.

> **Normative.** **Every wire-visible change of this decision rides L1, and that is the whole
> reason the cut has three lanes rather than four.** §12 requires the bump in the same change
> that makes a peer's value invalid, and `Goal`'s new fields, `ActionPlan.targets_revision` and
> `TurnResult.goal`'s type each do that on their own. A cut that landed any of them ahead of the
> bump would leave two peers passing the exact-match handshake and then failing to decode a
> turn — the failure ADR-0124 §9 exists to prevent — so **no lane of this decision lands a
> `core` type change that reaches `TurnOutcome` except L1**.

> **Normative.** **L1 is the one sanctioned cross-subsystem lane**, and it is sanctioned by
> ADR-0137 §2, which makes *"the **contract triad together with its primary production
> implementation** … one unit of work — one lane, one PR"* and fixes that *"Primary means the
> consumer whose demands shape the contract, not the one that is cheapest to write"* — here the
> `PlanStore` implementations, which are what the interpretation chain, the elision, the two
> compare-and-swap writes and both migrations are actually shaped by. **L2 and L3 are each one
> subsystem**, and no other cross-subsystem pairing is authorised by this decision.

**Why L1 cannot be smaller, stated rather than assumed, and it is two reasons and not one.**
First, a `Planner.plan` signature change is not confinable to `planning/`: `core/protocols.py`
declares it, `planning/planner.py` implements it, `ai_assistant.testing` fakes it and
`orchestration/loop.py` calls it, and a PR that moved fewer than all four would not type-check
under `mypy --strict`. Second, the wire: three independent changes of this decision make a hub's
turn undecodable by an older client, and splitting them across lanes would mean two bumps, two
incompatible releases and an interval in which a lane had landed one of them without one.
ADR-0137 §2's argument covers the first — the contract *"stays **soft while its hardest consumer
stress-tests it**"* — and ADR-0124 §9 covers the second.

**Why the behaviour is held back to L2 and L3 rather than riding L1.** L1 is a large mechanical
diff and a review of it is a review of a translation; L2 and L3 are where the judgements are,
and a reviewer reading them is reading a decision rather than a rename. That is the same
division ADR-0137 §2 draws between the triad and its consumers, applied inside one contract
change. It also means the **operator restarts once**: L1 is the only release of this decision
that a hub and its clients must upgrade together.

### 16. The arms this decision owes

> **Normative.** The lanes implementing this decision owe representative-input tests for each
> of the following, and a lane that lands without its arm has not discharged this ADR.

1. **S1, end to end.** *"What is two plus two?"* on a conversation's first turn: a goal opened
   at revision 1 whose outcome is the stripped request; **one** `Planner.plan` call and **one**
   composing call, which is exactly today's cost; six phase stamps; no read request; no
   question; one attempt whose **stored** row ends `ENDED`/`ANSWERED`, written first at §11's
   site and moved there by a same-turn `commit_attempt` once the answer exists; and the goal's
   status still **`ACTIVE`**.
2. **S2's understanding half.** *"Actually, make it Sunday"* against a goal whose earlier
   attempt booked a campsite: a **new attempt** on the **same** goal, a new interpretation
   revision whose `raised_by` names this turn and whose changed element grounds `USER_STATED`
   on a span of this turn's request, and every prior revision retained unedited.
3. **The writer clause.** A planner double returning an envelope carrying a phase, a revision
   number, a `raised_by` and a `recorded_at` — every one discarded, the turn not degraded, and
   the stamped values `orchestration`'s.
4. **The namer rule, in two arms that assert only what is true.**
   **(a) Structural, and over the projections alone.** `GoalBrief` and `EvidenceDigest` carry
   **no field in which a ground reference could sit** — no `evidence_id`, no record id, no
   evidence row id, no span — asserted over the two types' declared field sets. That is the
   whole of the structural claim, and it is deliberately not a claim about a prompt: the
   `utterance` and the `memories` are *also* inputs to this seam, a `USER_STATED` ground's span
   is by construction a span of the `utterance`, and a record's id is a field of a
   `MemoryRecord` — so a double that rendered every input would print both, and would be
   rendering values ADR-0226 §3 already governs rather than anything this decision adds.
   **(b) Behavioural, and over the production renderer.** Given a brief whose `goal_id` is a
   distinctive string and a digest built from a record with a distinctive id, the prompt
   `_render_request` builds contains neither string. §9's distinction between what a type
   *contains* and what the renderer *prints* is exactly what these two arms separate.
5. **Ground resolution and its refusals.** A `FROM_EVIDENCE` element whose label is outside the
   shown set, and a `USER_STATED` element whose span is not a span of the turn's request: each
   dropped from the recorded revision, silently, with the revision's `outcome` still recorded
   and the turn unharmed.
6. **The stale-target rule, and what the stamp actually is.** A plan whose `targets_revision`
   is not the goal's current revision is not driven. And the stamp is **the goal's revision
   after this call's understanding was recorded**, whatever the planner returned in that field,
   in both cases: a call that received revision 1 and returned no understanding yields a plan
   targeting 1, and one that received revision 1 and returned an understanding recorded as
   revision 2 yields a plan targeting **2** (arm 20). A stale target is therefore produced by a
   *later* revision and never by the call that made the plan.
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
14. **A turn that ends early persists nothing, and a turn that gets past the site records the
    rest.** A turn whose planner raises, one rejected for capacity and one that fails before the
    planner is reached each leave **no goal row, no attempt row and no plan row** — ADR-0228 §5's
    clause asserted over the two new record kinds as well as over the plan, and asserted on a
    `LearningLoop` that still holds no `PlanStore`. And a turn that reaches the site and then
    composes leaves a stored attempt whose phase, state and outcome are the ones it actually
    finished on, moved there by same-turn `commit_attempt` calls rather than claimed in advance.
15. **A park outlives a goal the store never got.** A park written on a turn that then ended
    early is still answerable, its resumption composes from what the park itself carries, and
    nothing repairs or refuses it (§11).
16. **A pre-decision park upgrades and is answered.** A parked-read database carrying the
    store's **pre-decision** table, its indexes, its settlement trigger and its
    `schema_version` marker, holding an unexpired `OPEN` park whose `goal` column is a
    pre-decision `Goal` and whose `plan` carries no `targets_revision`, is opened, upgraded,
    read back with a `GoalBrief` whose `outcome` is the stored `statement` and whose `goal_id`
    matches the record's new column, **answered**, and then settled — with a park written after
    the upgrade settled in the same run. A fresh database seeded with converted JSON cannot
    stand in for it, on ADR-0248 §10's own ground: it is the **stored** definition and not the
    row that the object check refuses. The same arm composes with an absent `utterance`.
17. **A pre-decision plan store upgrades and stays exportable.** A plan store at
    `schema_version` 1 holding goals and plans is opened and upgraded; each goal reads back with
    exactly one interpretation whose `outcome` is its stored `statement` and whose `raised_by`,
    `conversation_id` and `last_engaged_at` are **absent**; each plan reads back with
    `targets_revision` absent and is **not driven**; `export` produces a `PlanExport` at the new
    `schema_version` that validates and closes; and `delete_goal` still cascades.
18. **The absences have exactly one producer.** No path through `orchestration` writes `None`
    into `Goal.conversation_id`, `Goal.last_engaged_at`, `GoalInterpretation.raised_by` or
    `ActionPlan.targets_revision`, and `PlanStore.save_plan` refuses a plan whose
    `targets_revision` is still absent (§8, §12).
19. **The attempt's references grow, within a turn and across turns alike.** An attempt the
    store already holds takes a plan id, then an execution id, then an authorization id through
    `commit_attempt` — the first two inside the turn that opened it — each appended in order;
    a repeated identifier is ignored rather than duplicated; and no member of `AttemptTransition`
    removes or reorders one.
20. **An ordinary revising turn drives.** A planner call that receives revision 1 and returns
    **both** a `ProposedUnderstanding` and an actionable plan yields a plan whose
    `targets_revision` is the revision that call produced, not the one it received — so the plan
    is driveable, no second planner call is needed, and ADR-0228 §2's entry conditions are not
    reached. The arm fails if the stamp is taken before the recording step.
21. **A minted record is not a ground.** A second planner call whose supply carries a
    search-minted record returns a `FROM_EVIDENCE` element naming that record's **valid** label:
    the element is dropped, the revision's `outcome` is still recorded, the turn is not
    degraded, and no durable interpretation anywhere carries that record's id.
22. **The fallback still reads the request.** A converted pre-decision park carrying no
    `utterance` resumes with `asked` equal to the bytes its stored `Goal.statement` held, read
    off `park.goal.outcome` — ADR-0248 §3's exactness asserted across the conversion rather than
    assumed.

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
call site moves with it. The three-lane cut means three reviews and three base moves rather
than one, and L1's diff is large even though its behaviour is unchanged — it carries the
contract, both store migrations and every wire-visible change at once, because §15 shows it
cannot be split without landing an incompatible value ahead of the version that announces it.

**And the deployment is a coordinated upgrade, once.** L1 is a release a hub and its clients
install together; L2 and L3 are ordinary releases behind it. That is the cost of ADR-0084 §3's
exact-match handshake applied to a change this wide, and it is paid once rather than twice
because §15 refuses to spread the wire surface across lanes.

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
