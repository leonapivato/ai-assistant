# 248. The user's request is its own value on the turn, and the goal statement stops standing in for it

- Status: Proposed
- Date: 2026-09-12
- **Partially supersedes** [ADR-0225](0225-a-transcript-archive-keeps-the-exchange-as-text-and-nothing-but-the-user-reads-it.md)
  — **§1's fourth clause in its first limb alone: where the pass carried a turn, "what the
  user said" is identified as that turn's own `utterance` rather than its goal statement.
  Nothing else in that ADR.** §1's rule — that the value is the user's own words,
  unrewritten and unrendered — binds entire and is the reason for the change; its routed
  limb, its absent limb, its parked-resolution clause, its three-capture-case partition,
  its assistant-half clause, its no-part-of-`content` clause and its handed-to-capture
  clause all bind verbatim, and §§2–16 are untouched.
- **Partially supersedes** [ADR-0244](0244-a-confirm-on-a-search-parks-as-a-durable-question-and-the-answer-runs-that-exact-read-once.md)
  — **§2's field enumeration and its three-content-fields clause, and §3's `settle`
  clearing clause, each in the count alone: `ParkedRead` gains a fourth content field,
  `utterance`, and settlement clears four fields rather than three. Nothing else in that
  ADR.** The fields already enumerated keep their names, types, meanings and defaults;
  §2's validator keeps both halves it already refuses; §2's never-carries clause,
  its `parameters` clause and its `APPROVED` clause bind entire; §3's indivisibility,
  its one-open-park-per-conversation rule, its one-park-per-decision rule and its other
  six members are untouched; and §§1, 4–23 stand entire.

## Context

### Where this comes from

The owner ruled on 2026-09-12, on #2255's rulings comment, that `Goal` gets its intended
meaning — the understood outcome, its constraints and its success criteria, with
revisions and provenance — instead of the latest utterance it holds today. That is the
next decision in the A-series (A1), and the owner's dispatch line puts this one ahead of
it: *"A0 starts now and lands before A1."*

This ADR is A0. It decides one thing and deliberately no more: **the user's own words
become a value of their own on the turn**, so that every reader that wants *the user's
words* stops reading them off `Goal.statement`. It changes no behaviour, because at this
decision the two are byte-equal.

### What the tree actually does today, verified at `70029ab5`

`git grep -n "goal\.statement\|goal_statement" src/` returns twelve hits, and only some
of them are about the user. The three that matter most:

- `_exchange_of`, in `orchestration/engine.py`, appends
  `f"The user asked: {turn.goal.statement}"`. That string becomes
  `EpisodicMemory.content` — ADR-0005 §1's *"canonical text rendering of the record"* and
  ADR-0074 §4's *"canonical rendering of the exchange — what was asked, and how it turned
  out"*.
- `Engine._run_turn` passes `asked=turn.goal.statement` on both its branches, and
  `Engine._resume_read` passes `asked=goal.statement` off the parked turn's persisted
  goal. `asked` is the transcript archive's user half.
- `composing`'s user prompt opens `"The user said, in their own words:"` and then renders
  `f"  {_quoted_span(turn.goal.statement)}"`.

And `orchestration/loop.py`'s `_goal_from` mints the goal with one line —
`statement = utterance.strip()` — which is the whole reason those three readings are
correct today.

### Why this lands before the goal's meaning changes

ADR-0225 §1 is normative and is explicit about the source:

> **What the user said** is the user's own words on the pass that produced the turn,
> unrewritten and unrendered: the turn's goal statement where the pass carried a turn, the
> utterance where a routed pass threads one (ADR-0197 §10), and **absent** where the pass
> received no user words at all.

Once `Goal.statement` becomes the assistant's interpretation, that clause files an
interpretation under *"the user's own words, unrewritten and unrendered"*, and the episode
says *"The user asked: <what we decided they meant>"*. The composing prompt is worse
still: it would put the assistant's own paraphrase in quotation marks under a heading that
says the words are the user's, and hand that to the model as ground truth.

That is not a plumbing problem — it is the record stating a falsehood. Landing this
decision **while the two values are still equal** means the change is a behavioural no-op
and there is never an interval in which the record is wrong. Landing it afterwards would
mean an interval in which it is.

### The mechanism is the one ADR-0225 §1 already prescribes

§1's closing clause names it:

> The value each of these fields carries is **handed to capture, not computed there**,
> threaded per call site exactly as `modality`, `supplied_withheld` and
> `derived_from_external` already are. Capture judges nothing (ADR-0074 §4) and derives no
> part of an entry from the rendering it is given.

So nothing here invents a mechanism. The three named fields are already threaded per call
site; what this decision does is give the fourth one a value of its own to be threaded
*from*, instead of a value it borrows from the goal.

### What this ADR is not allowed to settle

The goal's meaning, its interpretation chain, its revisions, its provenance, `GoalBrief`,
the attempt, the planner envelope, the dissolution of `Task`, and whether a goal spans
conversations — every one of those is A1's or later, and §8 names them. ADR-0228 §1's
per-turn minting clause is **A1's to supersede**, not this ADR's; it is relied on here
exactly as it stands.

## Decision

### 1. The user's request is a value of its own, carried on the turn

> **Normative.** The **request** — the user's own words on the pass, as the pass received
> them, unrewritten, unrendered and uninterpreted — is a value of its own. It is carried on
> the turn as `TurnResult.utterance`, is set by the component that received it, and is
> **computed, derived, reconstructed or defaulted nowhere else**: no lane parses it out of a
> rendering, reads it off a goal, infers it from a plan, or falls back to any other value
> when it is asked for it. §3's one fallback — for a park older than the field — is the
> single exception, and it reads a value this decision proves is the request (§3).

> **Normative.** `TurnResult.utterance` is typed `NonBlankEncodableText` and is **required
> with no default**. The field **normalises nothing**: the pass strips the text it received
> **once**, and hands that one string both to the goal it mints and to the turn it builds.
> The byte-equality §6 asserts is therefore a property of there being **one** normalisation
> in **one** place, not of two that happen to agree. The general rule ADR-0096 §2 draws —
> *"a faithful copy takes the type of the field it copies, and may tighten only in ways that
> reject"* — is honoured: `NonBlankEncodableText` is `EncodableText` tightened by a rejection alone, and
> its refusal of a blank is the refusal `_goal_from` already raises on the same input.

> **Normative.** The value belongs to **the pass**. A turn assembled from durable state
> carries the request the pass that produced it received (§3), never one a later pass
> supplies; and no lane writes a request onto a turn that did not receive one.

**Why the request is a value rather than a rendering of the goal.** ADR-0014 §1 has said
since the planning model was written that *"A `Goal` is deliberately **not** the same thing
as a user utterance"*, and gave the reason: *"A request ('book me a flight') is transient;
a goal ('relocate to Lisbon in September') outlives any one conversation"*. The
implementation has never honoured it — `_goal_from` makes the goal the utterance — and
every reader that wanted the utterance has quietly taken the goal instead. That is a debt
with one payment date: the day the goal starts meaning what ADR-0014 §1 said it meant. This
ADR pays it on the last day it can be paid for free.

### 2. Where it lives: a field on the turn, and why a threaded argument beside the turn is wrong

> **Normative.** The request lives as a **field on `TurnResult`** and not as an argument
> threaded beside a turn. Every consumer that is handed a `TurnResult` and wants the user's
> words reads them off that turn; no lane adds a parameter carrying the user's words to a
> function that already takes the turn those words belong to.

> **Normative.** The request is **not** a field on `Goal`, is not persisted in the
> `PlanStore`, and is not written into any goal record. `Goal` gains nothing, loses nothing
> and changes nothing in this decision.

**A second parameter beside the turn is a second authority for one fact.** Three
production consumers take a `TurnResult` and render the user's half from it:
`_exchange_of`, which builds `EpisodicMemory.content`; `composing`'s user prompt; and
`Engine._capture`'s `asked`. Giving each a parameter beside the turn admits a pairing that
can **disagree** — a request rendered against a turn it did not come from — with nothing in
the type system and nothing in the gate able to detect it. The turn is the value that says
"this pass produced a turn"; ADR-0225 §1's first case is keyed on exactly that condition,
and the value that condition selects belongs on the object the condition is about.

The routed limb is the contrast that proves the rule rather than an exception to it.
ADR-0197 §10 is explicit: *"A routed pass produces no `TurnResult`, so the implementing
lane threads the utterance to the capture point rather than reading it off a turn that is
not there."* Where there is no turn, a threaded argument is the only carrier available and
is correct; where there is a turn, it is a duplicate.

**And it is not a field on `Goal`, for ADR-0014 §1's own reason.** Under A1 a goal carries
an interpretation that revisions can advance across many turns; one request per goal would
be false the moment a second turn revised it. Putting it there would also copy Tier 1
content into the `PlanStore`, which has no reason to hold it — ADR-0004 §7's minimisation
rule failing in a store whose charter is *"request → executable plan, progress tracking"*.
The pass's words belong to the pass.

### 3. The parked read carries its own request, and the one fallback for a park older than the field

> **Normative.** `ParkedRead` gains a **fourth content field**, `utterance`, typed
> `NonBlankEncodableText | None` and defaulting to `None`, carrying the parked turn's
> request. It is **content** in ADR-0244
> §3's sense: `settle` clears it in the same indivisible step it clears `parameters`, `goal`
> and `plan`, and `drop_for_conversation` removes it with the row. It joins no other
> clause — it is not a fact that survives settlement, and ADR-0244 §3's retention rule that
> *"The content lives exactly as long as the question does"* now reaches one field further.

> **Normative.** ADR-0244 §2's model validator is **not** extended to require `utterance`
> on an `OPEN` park. Both halves it already refuses are unchanged — an `OPEN` park missing
> any of `parameters`, `goal` or `plan`, and a terminal park carrying any of them — and a
> terminal park carries no `utterance` either. An `OPEN` park with `utterance` `None` is
> reachable by exactly one route and no other: a park **written before this decision
> landed**, which is still answerable and must stay so.

> **Normative.** `Engine._resume_read` takes the user's words from the park's own
> `utterance`. **Where the park carries none**, it takes the parked `Goal.statement`
> instead, and it is the only place in the system that may. **No lane widens it**: not to a
> park that carries an `utterance`, not to a blank one, not to any other reader of §5's
> table, and not to any other site.

> **Normative.** **That reading is exact for the whole life of the fallback, and A1 does
> not change that.** A park carries no `utterance` only where it was written before this
> decision's field existed, and every such park's `Goal.statement` was minted by
> `_goal_from` from the user's own stripped words. A park written after this decision
> always carries its `utterance`, so the fallback can never reach a `Goal.statement` minted
> under any other meaning — A1's included. The fallback therefore needs **no** removal to
> stay correct, and **no lane is obliged to remove it**; A1 inherits nothing here.

> **Normative.** A later change **may** delete it, once ADR-0244 §3's `expires_at` has
> retired every park that predates this decision's deployment. Deleting it then makes such
> a park's resolution carry **no** user words rather than the wrong ones. Until such a
> change it stands, and no lane may delete it while a park lacking an `utterance` can still
> be answered: `TurnResult.utterance` is required (§1), so removing the fallback without
> first deciding what a resumed read composes when the pass has no request would leave that
> path with no valid turn to build.

**Why the park needs the field at all.** `Engine._resume_read` builds a real
`TurnResult` — ADR-0244 §8 has it *"captured as a turn's exchange is captured"*, over a
supply of its own — from `park.goal` and `park.plan`, because `settle` cleared them from
the row in the step that closed the question. So the request reaches that pass only if the
park retained it, exactly as the goal and the plan do, and for the same reason ADR-0244 §2
gives for retaining those: *"because §8 composes over them and would otherwise fabricate
them"*.

**Why the fallback rather than a migration.** The alternative shapes are each worse. Making
`utterance` required on an `OPEN` park would make every park written before the field
existed fail to decode, so `get`, `open_park` and `outstanding` would raise on it and a
question the user was asked would become unanswerable, against ADR-0244 §15's normative
*"**A park survives a restart and is offered again**"*.

**Back-filling the column is the real alternative, and the tradeoff is a write against a
branch.** It would work, and it needs no rendering parsed: §3's own argument establishes
that a legacy park's `Goal.statement` **is** the user's words, so the upgrade could copy
that value across and every park would then carry an `utterance`. It is rejected on what it
costs rather than on whether it could be done. A back-fill **rewrites stored Tier 1 content
in rows the user is still being asked about**, which turns §9's upgrade from one that
*"touches definitions and a marker, and no content"* into one that edits the record of what
the user was asked — and the store's guarantee that a park's content is byte for byte what
was recorded when the question was asked would then rest on upgrade code being correct and
uninterrupted, rather than on nothing having written to the row at all. And it buys nothing
a reader can see: the fallback reads the identical bytes, out of the identical row, with no
write at all. What it costs instead is one compatibility branch, which §3 makes permanently
exact rather than merely temporarily correct, which fires only on rows a bounded
`expires_at` retires, which is stated in one place, and which hands A1 no obligation.

### 4. Capture, the archive and the exchange rendering take the user's words from the request

> **Normative.** ADR-0225 §1's fourth clause is superseded **in its first limb alone**.
> "What the user said", where the pass carried a turn, is **that turn's `utterance`** and
> no longer its goal statement. Every other limb of that clause and every other clause of
> §1 binds verbatim: the words are still the user's own, unrewritten and unrendered; a
> routed pass still threads its utterance (ADR-0197 §10); a pass that received no user words
> still carries **absent**; the resolution of a parked step still carries **no** user words;
> the three cases are still ADR-0221 §5's three capture cases and no fourth partition is
> introduced; and the value is still handed to capture and computed nowhere in it.

> **Normative.** `_exchange_of` renders the turn's `utterance` in place of its goal
> statement, so `EpisodicMemory.content` quotes the user rather than the assistant's reading
> of the user. ADR-0005 §1's `content` and ADR-0074 §4's *"what was asked, and how it turned
> out"* are **fulfilled** by this rather than changed: neither ADR's text ever identified
> the goal statement as the source, and §13 records that no amendment is owed against
> either.

> **Normative.** `composing`'s user prompt renders the turn's `utterance` under its
> existing heading. The heading — *"The user said, in their own words:"* — is a claim about
> the text beneath it, and after A1 only the request can make that claim true. No lane
> renders a goal statement under it and no lane changes the heading to accommodate one.

> **Normative.** Nothing in this decision changes what an archive entry carries, what the
> archive is keyed by, when the write happens, or what capture judges. `archive/` gains no
> field, loses none, and needs no change: `asked` is already a parameter of the capture
> call, and what moves is only the expression that supplies it.

### 5. Every reader of `goal.statement`, classified

> **Normative.** Every site below reads `goal.statement` at `70029ab5`, and each is
> classified as reading **the user's words** or **the goal**. A site classified as reading
> the user's words takes the request in this decision. A site classified as reading the goal
> is **untouched here**, and what it receives once the goal's meaning changes is A1's to
> decide. No lane reclassifies a row of this table without the ADR that does it.

| Reader (symbol) | The line, or what it is | Classification | Disposition |
| --- | --- | --- | --- |
| `orchestration.engine._exchange_of` | `f"The user asked: {turn.goal.statement}"` | **user's words** | takes `turn.utterance` (§4) |
| `Engine._run_turn`, no-step branch | `asked=turn.goal.statement` | **user's words** | takes `turn.utterance` (§4) |
| `Engine._run_turn`, step branch | `asked=turn.goal.statement` | **user's words** | takes `turn.utterance` (§4) |
| `Engine._resume_read` | `asked=goal.statement`, off the parked turn | **user's words** | takes `park.utterance`, with §3's fallback for a park older than the field |
| `orchestration.composing`, the user prompt | `"The user said, in their own words:"` then `f"  {_quoted_span(turn.goal.statement)}"` | **user's words** | takes `turn.utterance` (§4) |
| `LearningLoop.respond` → `self._retrieve(goal.statement)` | the relevance query | **the goal** | untouched; A1 |
| `LearningLoop.respond` → `self._supplement(goal.statement, …)` | the episodic supplement's query | **the goal** | untouched; A1 |
| `LearningLoop.resumed_read` → `self._retrieve(goal.statement)` | the relevance query on a resumed read | **the goal** | untouched; A1 |
| `LearningLoop.resumed_read` → `self._supplement(goal.statement, …)` | the supplement's query on a resumed read | **the goal** | untouched; A1 |
| `planning.planner._render_request` | `"Goal:"` then `f"  statement: {goal.statement}"` | **the goal** | untouched; A1 |
| `ParkedRead.goal` (`core/types.py`) | the persisted `Goal` the parked turn was planned against | **carrier of both** | keeps `goal`; gains `utterance` beside it (§3) |
| `PlanExport` | exports goal records whole (ADR-0004 §6, ADR-0014 §5) | **the goal** | untouched; A1 |

Two entries the naive grep returns are **not readers** and are recorded so that a later
sweep does not treat them as ones:

- `planning/sqlite_store.py` mentions `goal.statement = "   "` inside a docstring arguing
  why a blank statement is refused. It reads nothing.
- `orchestration/disclosure.py` carries four prose mentions of *"the turn's own goal
  statement"* and **reads it nowhere**. Three describe ADR-0210 §1's narrowed set; the
  fourth states, in terms, that the module *"is not given the turn's goal"*. Nothing in
  that module changes here, and the prose stays accurate because ADR-0210 §1's clause is
  about the **query** a relevance read was taken with, which this decision does not move.

**The four query rows are the classification most worth arguing, and the argument is
ADR-0210 §1's.** That clause is normative and is stated in the goal's own terms: the
evaluation is taken over the supply that *"a **relevance read taken with this turn's own
goal statement** returned"*. A query is not a quotation — nothing renders it to a user,
nothing attributes it to anyone, and no clause of the corpus claims it is the user's own
words. So the conservative reading, and the one the ratified text supports, is that
retrieval reads *the goal*. Whether an interpretation is a better retrieval query than a
raw utterance is a real question with evidence behind it on both sides, and it is A1's:
this decision leaves those four call sites byte-for-byte where they are, which is what
keeps §6's assertion true of the retrieved supply as well as of the record.

### 6. This is a behavioural no-op, and here is the assertion

> **Normative.** At this decision the request and `Goal.statement` are **byte-equal on
> every path that carries a turn**. `_goal_from` mints the statement as
> `utterance.strip()`, `TurnResult.utterance` carries the same string under the same type
> and the same validator (§1), and no other producer of either exists. Every rendering this
> decision moves therefore produces the identical bytes before and after it.

> **Normative.** The implementing lane owes one arm per capture path asserting that the
> archived user words **and** the episode's `content` are unchanged across the change:
> (a) a turn that drove no step; (b) a turn that drove one; (c) a routed pass, whose
> utterance was already threaded and stays so; and (d) the resolution of a parked read.
> It owes one further arm asserting that where a pass received **no** user words — the
> resolution of a parked step, the resolution of a routed park, and a resumption recovered
> from durable state — the entry still carries none.

> **Normative.** It owes one arm on the composing stage asserting that the assembled user
> prompt is byte-identical before and after, which is the reader §5 moves that the archive
> arms do not cover.

> **Normative.** No arm may establish the no-op by constructing a turn whose `utterance`
> the test itself sets to the goal statement. The arms drive the production path from an
> utterance, which is the only construction under which the equality is the system's claim
> rather than the test's.

### 7. The `core` surface, the wire, and what a record written before this decodes to

> **Normative.** **The `core` surface this decision changes is exactly this and no more.**
> In `core/types.py`: `TurnResult` gains `utterance: NonBlankEncodableText`, required with
> no default; `ParkedRead` gains `utterance: NonBlankEncodableText | None`, defaulting to
> `None`. **No
> other type gains, loses or changes a field, a default or a member** — `Goal`,
> `GoalStatus`, `ActionPlan`, `PlanStep`, `TurnOutcome`, `EpisodicMemory`, `Capture`,
> `Modality`, `PlanExport`, `ParkedReadDisposition`, `Conversation` and `ConversationTurn`
> are untouched. In `core/protocols.py`: **nothing** — no Protocol gains, loses or changes a
> member, an argument or a return, `ParkedReads` and `PlanStore` included. In
> `core/config.py` and `core/errors.py`: nothing.

> **Normative.** **No Protocol changes, so this is not a BREAKING contract change under
> golden rule 5 and no triad is owed.** No Protocol is created, so no conformance suite and
> no canonical fake is added; the existing `ParkedReads` conformance suite and its canonical
> fake in `ai_assistant.testing` gain the new field's assertions in the same change that
> adds it, and `ai_assistant.testing`'s `TurnResult` builder sets the new field there.

> **Normative.** **`PROTOCOL_VERSION` moves 36 → 37**, and `wire/envelope.py`'s log gains an
> entry naming this ADR and this reason. `TurnResult` is carried on `TurnOutcome.turn` and
> `TurnOutcome` is what the promoted surface returns; `TurnResult` sets `extra="forbid"`,
> and `wire/codec.py` renders a model by `model_dump()`, so a hub at 37 emits an
> `"utterance"` member on **every** turn and a client at 36 fails it with
> `extra_forbidden`. That is ADR-0124 §9's second limb — *"a change to a wire-carried `core`
> type that makes a value one peer emits invalid for the other, whether the change widens or
> narrows the type"* — and ADR-0178 §6 is the precedent for stating the bump in the deciding
> ADR rather than leaving the lane to discover it.

> **Normative.** **Nothing else under `wire/` changes.** The connect exchange gains no
> member, no existing frame's encoding changes, no `FrameKind` is added, no codec entry is
> registered, and the promoted method set does not move. `ParkedRead` is **not** a second
> ground: it is an in-process store record reached through the `ParkedReads` Protocol, no
> peer emits it, and adding a field to it emits nothing.

> **Normative.** **A park written before this decision decodes, stays answerable, and is
> not repaired.** It decodes with `utterance` `None`, which §3's validator clause admits;
> no lane back-fills, re-derives, reconstructs or re-validates the column on any stored row;
> and §3's fallback is what its resolution archives, exactly. **The parked-read store's own
> `schema_version` does move, 1 → 2**, because §9's trigger change alters a stored object
> definition; the upgrade reads no park content and rewrites none.
> No other stored record is affected: `ConversationExport.schema_version` stays at **2**,
> ADR-0212 §8 and ADR-0014 §5 are untouched, and no row is minted in ADR-0087 §2c's scalar
> table.

> **Normative.** **No new class of content crosses the wire.** The request is Tier 1
> content, and `TurnOutcome.turn.goal.statement` already carries the identical bytes to the
> identical peers; what moves is which field holds them. ADR-0004 §5's rule that *"Tier 0/1
> data must never be logged"* binds unchanged and nothing here logs the new field. ADR-0200
> §8 is untouched: the request is text, and no audio is retained by anything in this
> decision.

### 8. What this ADR does not decide, by name

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them. Each is A1's or later, and each is named so that a reader cannot
> mistake this ADR's silence for a ruling.

- **What `Goal.statement` means.** It is the user's stripped utterance at this decision and
  stays so until A1 changes it. This ADR neither ratifies that meaning nor changes it.
- **The goal's interpretation, its revisions, its provenance per element, its conditions,
  its success criteria, `revision`, `conversation_id` and `last_engaged_at`.**
- **`GoalBrief`**, and what `Planner.plan`, `TurnResult` and `ParkedRead` carry of a goal
  once a projection exists. `TurnResult.goal` stays a whole `Goal` here; `ParkedRead.goal`
  stays a whole `Goal` here.
- **`GoalAttempt`, `GoalEvidence`, `Authorization`, `AttemptState`, `AttemptOutcome`,** the
  dissolution of `Task`, and the phase model.
- **ADR-0228 §1's per-turn minting clause** — *"The goal is minted once per turn from the
  user's unrewritten words and nothing about it changed"* — which is **A1's to supersede**.
  It is relied on here exactly as it stands, and is what makes §6's byte-equality true.
- **What the relevance read and the episodic supplement are queried with**, and what
  `planner._render_request` renders — §5's four goal-classified rows.
- **Whether a goal spans conversations**, and whether `GoalStatus`'s three unwritten
  members gain producers.
- **Whether the resolution of a parked read should archive the parked question a second
  time at all.** ADR-0225 §1's first case covers it as written, and this decision preserves
  exactly what the tree does; §11 files the question as #2265 rather than answering it.

### 9. What the implementing lane owes, and why it is one lane

> **Normative.** This decision is implemented by **one lane**, whose diff is the two
> `core/types.py` fields, the `PROTOCOL_VERSION` move and its log entry in
> `wire/envelope.py`, the two `TurnResult` construction sites and the `ParkedRead`
> construction site in `orchestration/`, the five readers §5 moves, the fourth cleared
> field in `permissions`' parked-read store and its settlement trigger, and the canonical
> fakes and conformance assertions §7 names.

> **Normative.** **The settlement trigger is extended, and that is a stored-schema change
> rather than an edit to a string.** `SqliteParkedReads` holds every object it defines to
> its own definition: `CREATE TRIGGER IF NOT EXISTS` is a no-op against a trigger already
> in the file, and the object check then compares the **stored** SQL against the module's
> and refuses the database. So a trigger that names a fourth cleared field would make every
> existing parked-read database fail to open, not merely the parks inside it. The lane owes
> a **real upgrade**, in the same setup transaction the object check runs in: where the
> stored trigger is the definition this store shipped before this decision, it is dropped
> and recreated; where it is anything else the existing refusal stands, word for word and
> for its own reason. The store's `schema_version` moves **1 → 2** and a database labelled
> **1 is upgraded rather than refused**, which is the one shape its version check does not
> admit today.

> **Normative.** **The upgrade touches definitions and a marker, and no content.** It reads
> no park's `data`, rewrites no row, back-fills no column, re-validates no stored model and
> settles nothing. A park that was `OPEN` before it is `OPEN` after, with the same
> `expires_at` and the same answer available (§3). The upgrade and the object check remain
> one transaction, so a failure leaves the file exactly as it arrived — unupgraded,
> unlabelled at the new version, and refusing to open rather than half-migrated.

> **Normative.** **The archive side needs no second lane.** `archive/` changes not at all,
> and `Engine._capture` changes not at all: `asked` is already a threaded parameter and
> already carries ADR-0225 §1's three cases. What moves is the expression at four call
> sites that supplies it.

**Why one lane and not three.** `TurnResult.utterance` is required with no default, so
every construction site must set it in the change that adds it; a defaulted field instead
would be exactly the *"second authority"* ADR-0225 §1's handed-to-capture clause exists to
prevent, standing for however many merges the split took. And `ParkedRead.utterance` is
Tier 1 content, so the field and the clause that clears it at settlement must land
together or ADR-0244 §3's retention rule is breached for a window. This is the seam
ADR-0137 §2 widens the one-subsystem rule for — a contract change that cannot be separated
from the consumer whose demands shape it — applied to a `core/types.py` change rather than
a Protocol. The diff is small — two fields, one constant, one tuple, one SQL predicate and
five expressions — with the store upgrade above the one part of it that is not.

### 10. The representative-input tests this decision owes

> **Normative.** Beyond §6's six arms, the lane owes: an arm that a `TurnResult` cannot be
> constructed without an `utterance`; an arm that a blank or whitespace-only utterance is
> refused on the production path at the same point and with the same error it is refused at
> today, and an arm that the field itself refuses a blank; an arm that
> settling a park clears `utterance` alongside `parameters`, `goal` and `plan`, and that
> `get` reads it back as `None`; an arm that an `OPEN` park **round-trips** its
> `utterance` through the store; an arm that opens a database carrying the store's
> **pre-decision** table, indexes, settlement trigger and `schema_version` marker, upgrades
> it, reads its legacy `OPEN` park back with `utterance` `None`, answers it, and then
> settles a park written after the upgrade — a fresh database seeded with legacy JSON
> cannot stand in for it, because it is the **stored trigger definition** and not the row
> that the object check refuses; an arm that a database whose settlement trigger is
> **neither** definition is still refused, with the message it is refused with today; and an
> arm that a peer at the previous protocol version and a peer at 37 refuse each other,
> naming both versions.

### 11. Deferred, by name, each with what fires it

> **Normative.** Each deferral below is deferred **with its firing condition**, and none is
> a decision this ADR declines to take for want of an opinion.

- **Deleting §3's fallback in `Engine._resume_read`.** Not owed to anyone and not A1's:
  §3 makes the fallback permanently exact. Fired, if ever, by a lane that first establishes
  that no park lacking an `utterance` can still be answered, and that decides what a resumed
  read composes and archives when the pass has no request.
- **What the relevance query, the episodic supplement's query and
  `planner._render_request` receive.** Fired by A1.
- **Whether `ParkedRead` keeps a whole `Goal`.** Fired by A1's projection decision.
- **Whether the resolution of a parked read archives the parked question a second time.**
  Filed as #2265 against ADR-0225 §1 and ADR-0244 §8, and fired by the contract review
  the owner booked on 2026-09-12 for ADR-0244 §3's conversation-wide park restriction.
  This decision changes neither the behaviour nor the reasoning; it preserves both.
- **A modality, a source or a derivation on the request.** Fired by nothing here; ADR-0221
  §5's closing clause already owns which further facts land on `Capture`, and this ADR adds
  none of them.

### 12. Scope, and what this records against earlier ADRs

**ADR-0225 §1 — partially superseded**, in the fourth clause's first limb alone, and the
header records it. A reader holding only ADR-0225 would implement `asked` from
`turn.goal.statement`; after this decision that is wrong, which is ADR-0070 §1's test coming
out on the supersession side. The scope is that one limb: §1's rule is the **reason** for
the change and binds entire.

**ADR-0244 §2 and §3 — partially superseded**, in the field count alone, and the header
records it. §2 enumerates `ParkedRead`'s fields as *"exactly"* a list of nine and calls
`parameters`, `goal` and `plan` *"the three content fields"*; §3's `settle` *"clears
`parameters`, `goal` and `plan` in the same step"*. A reader holding only ADR-0244 would
refuse a tenth field and would clear three, so both sentences fail ADR-0070 §1's test. The
scope is the count and nothing else.

**ADR-0005 §1 and ADR-0074 §4 — no record owed, and the showing is here.** The brief for
this lane asked for a record *where their text identifies the goal statement*. Neither text
does: `git grep -c "goal statement\|goal\.statement" docs/adr/0005-*.md docs/adr/0074-*.md`
returns zero for both. ADR-0005 §1 defines `content` as *"a canonical text rendering of the
record"*; ADR-0074 §4 closes *"`content` is the canonical rendering of the exchange — what
was asked, and how it turned out."* Both stay true word for word after this decision, and
are better satisfied by it. Applying ADR-0082 §1's test — *"Would a reader holding only the
earlier ADR now act differently, or read one of its clauses more widely than it now
holds?"* — the answer is no, so no record is owed and none is written.

**ADR-0221 §5 — no record owed, and the showing is here.** Its second capture case says the
resolution of a parked step is an episode *"whose `content` renders that turn's goal
statement and plan rationale"*. That phrase identifies **which episode** the clause is
about; the obligation it imposes is about the **modality value** that episode carries, and
that value is unchanged. A reader holding only ADR-0221 §5 implements `modality` and would
act identically. The phrase's accuracy about `content` survives this ADR because §6 asserts
the bytes are the same, and becomes A1's to re-examine when they stop being — named in §8
rather than recorded here.

**ADR-0228 §1, ADR-0197 §10, ADR-0014 §1, ADR-0200 §8, ADR-0004 §5 and ADR-0210 §1 —
relied on unchanged.** ADR-0228 §1's minting clause is what makes §6 true and is A1's
to supersede. ADR-0197 §10's routed threading is the shape this decision copies and is
untouched. ADR-0014 §1 is **fulfilled in part and superseded in none** — its distinction
becomes true of the implementation for the first time, and its field list does not move
here. ADR-0200 §8 and ADR-0004 §5 stand whole and nothing here is cited toward either.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

> **Normative.** This is a **substantive contract ADR** under `CONTRIBUTING.md` → "Contract
> ADRs land before their implementation": it changes `core` types that cross subsystem
> boundaries. It ships as its own PR, is reviewed by **both** lenses while `Proposed`, and
> is ratified only once that set is green on one tree (ADR-0015 §5, ADR-0165). No
> implementation lands in this PR.

This ADR is marked, so ADR-0089 §3 governs: the block quotes above are the whole of what
binds, and the prose beside them is read to determine what a marked clause means.

## Consequences

**What becomes easier.** A1 becomes a change to one concept instead of a change to one
concept plus a rescue of every record that quoted it. The archive, the episode and the
composing prompt each say what they claim to say, and they keep saying it whatever the goal
comes to mean. The four query call sites become a real question — *should retrieval run on
the user's words or on the understood objective?* — instead of a question nobody can ask
because there is only one string.

**What becomes harder.** `TurnResult` carries one more field, and the wire moves with it:
every client is replaced in lockstep on the redeployment, for a field no client yet reads.
A park in flight across that deployment carries no request, and its resolution leans on
§3's fallback, which is one branch that reads the right value for every row it can ever see
but is a branch all the same, and that no later lane may delete without first answering what
a resumed read with no request composes (§11). And the two byte-equal
values coexist for one ADR's worth of time, which is a state a reader could mistake for
redundancy; §1 and §6 exist so that the equality is stated as a **transitional fact with an
end date** rather than discovered and tidied away.

**What would trigger revisiting this.** A
decision to make the archive's user half something other than the pass's own words. Or
evidence that retrieval on the interpretation beats retrieval on the utterance, which would
move four rows of §5's table and is A1's to weigh.

## Alternatives considered

**Leave the readers on `Goal.statement` and fix them inside A1.** Rejected on the owner's
sequencing and on its own merits. A1 is already a large decision; folding five readers, a
wire bump and a park field into it makes the diff that changes the goal's meaning also the
diff that rescues the record, and a reviewer cannot check either half against the other.
The rescue is only free while the two values are equal, and inside A1 they are not.

**Thread the request beside the turn everywhere, adding no field.** Rejected in §2: it
admits a request paired with a turn it did not come from, at three consumers, with nothing
able to detect it. It is worth saying what it does *not* cost, so the argument is not read
as stronger than it is: threading would genuinely avoid §7's `PROTOCOL_VERSION` move, since
`ParkedRead` is in-process and its own field emits nothing to a peer. The bump is a real
price this decision pays, and it is paid for the correctness §2 argues rather than because
no alternative could avoid it.

**Put the request on `Goal` as a second field.** Rejected in §2: it is false under A1's
revision model, and it copies Tier 1 content into a store with no reason to hold it.

**Give the parked read nothing and let its resolution archive no user words.** Rejected: it
is a behaviour change at exactly the site this decision promises not to change, and it
would make A0 observable in the record — which is the one property the sequencing buys.

**Require `utterance` on an `OPEN` park and migrate the rows.** Rejected in §3: a park
written before the field existed would fail to decode, so a question the user was asked
would become unanswerable, and the only available back-fill is parsing a rendering, which
ADR-0225 §1 refuses in terms.

**Leave the settlement trigger alone and let `settle`'s own code clear the fourth field.**
Rejected. It would avoid §9's store upgrade entirely, and that is its whole appeal. But the
trigger exists so that ADR-0244 §3's clearing is *"the database keeps rather than [a claim]
this module remembers"*, and a fourth content field checked by the module and by nothing
else is a silent asymmetry the next reader has to be told about. The retention guarantee is
the one this store deliberately pushed below the application, and Tier 1 content is the
wrong place to start making exceptions to it.

**Name the field `request` rather than `utterance`.** Rejected on the corpus's own
vocabulary. `utterance` is what every site that already threads this value calls it —
`LearningLoop.respond`, `_goal_from`, the routed capture path, ADR-0197 §10 and ADR-0225 §1
itself — and ADR-0014 §1 draws its distinction in that exact word. `request` is already
spoken for by `ActionPlan.read_request`, `ActionRequest` and `planner._render_request`. The
*distinction* is the request, as the owner's vocabulary has it; the *field that carries it
on a turn* is the utterance, which is the report's own spelling.
