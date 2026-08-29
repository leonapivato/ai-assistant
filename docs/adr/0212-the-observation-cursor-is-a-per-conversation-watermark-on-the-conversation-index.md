# 212. The observation cursor is a per-conversation watermark on the conversation index, and a pass advances it once

- Status: Proposed
- Date: 2026-08-29
- **Partially supersedes:**
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) — §8's selection
  sentence and its "there is no durable cursor" sentence, and nothing else of §8 or of
  ADR-0077. The scopes are named clause by clause in §10(a), where §8's remaining
  no-cursor sentence is recorded as narrowed rather than replaced.
- **Partially supersedes:**
  [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md) —
  §9's enumeration of what `Conversation` carries and what `ConversationStore`
  owes, in exactly the way ADR-0205 §10 already moved that enumeration for
  `ConversationTurn`; and §9's rule that every conversation read is ordered by last
  activity descending, replaced for the one new listing operation and for no other.
  Named in §10(b).
- **Partially supersedes:**
  [ADR-0111](0111-a-scheduled-walk-is-chunked-and-resumes-from-a-durable-cursor.md)
  — §2's absent-cursor clause and §7's restart position, **only as they reach the
  observation cursor this ADR decides**. §7's discard-rather-than-fault rule, and every
  other clause of ADR-0111, bind this walk unchanged and are relied on throughout.
  Named in §10(c).
- **This is a contract change.** It adds one member to `Conversation` in
  `core/types.py` and three operations to `ConversationStore` in
  `core/protocols.py` — `core` surface, so this ADR is its own PR, ratified and
  merged before anything implements against it (golden rule 5, ADR-0015 §5), and
  it owes **both** lenses: adversarial and architecture, on ADR-0015 §1 and
  `CONTRIBUTING.md` → "Stop when the required reviews are green". It adds no
  Protocol, no new `core` type, no `Settings` field, no member of the promoted
  engine surface and no wire operation. It moves
  `ConversationExport.schema_version` to `Literal[2]` and — §8 — does **not** move
  `PROTOCOL_VERSION`, because no frame carries that document.
- **The reciprocal `Status` records this decision owes on ADR-0077, ADR-0074 and
  ADR-0111 are made in this change**, atomically with the decision that owes them
  (ADR-0070 §1, ADR-0082 §7, and ADR-0205 §10's "**Both records are made in this
  change**"). Each is header-only — one pair accumulated on the `Status` line under
  ADR-0070 §4, and one appended dated note — and no ratified text of any of the three
  is rewritten. §10 states each pair verbatim and closes **#1788**.
- **Durability clause.** Every quotation below — from an ADR, from
  `core/protocols.py`, from `core/types.py`, from `core/config.py`, from
  `orchestration/observation.py`, or from an issue — is of its text as it stood at
  this ADR's base, `457caad4`, and not of its text on any later day.

## Context

### Where this comes from

On the deployed hub `ASSISTANT_OBSERVATION_INTERVAL` is unset, so the observer
never runs on its own: a fact the user tells the assistant in chat is captured as
an episode (ADR-0074 §3) and becomes a belief only when `assistant observe` is run
by hand (#1695 part 2). The setting is unset for a stated reason, written at the
field itself in `core/config.py`:

> Ships **disabled**, and §7 argues the default rather than assuming it: ADR-0077
> §8 leaves observation with no durable cursor, so a periodic run re-reads the same
> recent window and spends a model call each time while never reaching the turns the
> window has already passed. Enabling it on a timer before the cursor exists
> (ADR-0083 §13) buys repeated cost and no new coverage. The field exists so that
> enabling it is configuration.

The owner's direction of 2026-08-28, recorded as **#1737**, is *cursor first, then
observe-on-quiet*: two ADRs in that order. This is the first of them. The trigger
is the second and is not decided here (§9).

Two tracker entries record the gap this closes, and both are closed by this
decision rather than by an implementation. **#785** — "The observation job's
cursor-driven selector is not chosen, and ADR-0077 §8's window is not it" — asks
three questions and this ADR answers all three: what the cursor is a position in
(§2), how conversations are traversed (§3), and whether `observation_batch_size`
bounds the window or the chunk (§3). **#632** — "The scheduler's durable cursor is
deferred by three ADRs and tracked by no issue" — records the deferral itself.

### The deferrals, in the words that made them

**ADR-0077 §8** ratifies today's selector and files the cursor:

> **There is no durable cursor, and re-observation is safe by construction.** No
> state records which episodes have been observed. […] a cursor is durable per-user
> state whose natural owner is the resident process, filed with leg 5 (§11).

Its §11 files it by name: "the durable cursor that stops it re-reading what it has
seen (§8)". It also names the coverage it forgoes, and names it as reachable:

> **Two gaps in coverage are accepted and named**: a conversation the user never
> observes, and — in a conversation longer than the window — turns older than the
> tail. Both expire unobserved under ADR-0074 §7's horizon. Closing them means
> knowing what has already been observed, which is the cursor below, which is leg
> 5's.

**ADR-0083 §13** declines to take it inside a lifecycle ADR, and says exactly what
a taking ADR owes:

> **The observation cursor.** ADR-0077 §8 files it as leg 5's — "a cursor is
> durable per-user state whose natural owner is the resident process". It is not
> taken here, for a reason worth stating: it is **new durable state**, so it is
> itself subject to §6's upgrade-with-state discipline and needs its own decision
> about what an older or newer build does with a cursor it does not understand.

That is §7 of this ADR's whole subject.

**ADR-0111 §11** declines the selector and says who owns it:

> **The observation job's selector.** ADR-0077 §8 ratifies a *window* — "that
> conversation's most recent `observation_batch_size` turns", or the same window
> over the most recently active conversation — and calls it "today's only selector".
> A cursor-driven walk is a second selector, and choosing its order and its unit is
> ADR-0077's ground, not this ADR's. What binds that choice is §2: whatever order it
> walks must be total and must not reorder under later writes. **Filed as its own
> issue.**

### What ADR-0111 already decides, and is not re-decided here

ADR-0111 is the cursor ADR. This decision **inherits** it rather than minting a
second cursor theory, and the places it departs are §4 and nowhere else. What is
inherited, by clause:

- **§1** — a cursor lives in the store whose progress it records, reached only
  through the same public `Engine` operation the scheduler already calls; "a
  cursor is per walked order and per job. Two jobs walking the same store do not
  share a position, and **one job walking two orders holds one position in each**."
- **§2** — a cursor "names a position in an order the walked store already
  maintains, which must be total over the walked rows and must not reorder rows
  under later writes", and is "not a set of processed identifiers, not a wall-clock
  instant, not an offset into a paged read, and not a fraction of the work".
- **§3** — "A scheduled walk is at-least-once", the effects are made durable before
  the cursor advances where they live in different stores, and "no clause of this
  ADR may be implemented in a way that turns that repetition into a skip".
- **§4** — a run is bounded by a deadline and a chunk by a count, both
  configuration.
- **§5** — "When a chunk cannot be recorded as done, the run stops immediately,
  leaves the cursor at the last chunk that was recorded, and returns without
  processing any later chunk."
- **§6** — no backoff; a failed or refused run is retried at its next due instant.
- **§7** — "A cursor that is absent, unreadable, malformed, or written in a form
  this build does not understand is discarded, and the walk restarts from the
  beginning of its order. It is never advanced past a position that could not be
  read, and it never refuses the hub's start."

### Today's selector, in the code

`ObservationStage.observe` in `orchestration/observation.py` does what ADR-0077 §8
ratifies and nothing more. `ObservationStage._target` reads
`ConversationStore.recent` with `limit=1` when no id is given; `_select` then calls
`ConversationStore.turns(conversation_id, limit=self._batch_size)` — the *tail*
read — and resolves each turn's episode through `MemoryStore.get`, skipping what
does not resolve. The module docstring states the consequence: "There is no durable
cursor either".

`ConversationStore` already holds everything a per-conversation watermark needs. It
"**allocates** each turn's ordinal"; ordinals are "dense from `FIRST_TURN_ORDINAL`,
unique, and monotonic" per conversation; `ConversationStore.turns` returns a page
"ordinal ascending"; and `ConversationTurn` "just gained a store-written field"
under ADR-0205 §3 — `delivery`, "the one operation this contract has that writes a
fact arriving **after** the turn it is about was recorded". A watermark is that same
shape one level up: a fact about a conversation, written after the turns it is
about.

## Decision

### 1. The cursor is a per-conversation watermark on the conversation index

> **Normative.** The observation cursor is a **per-conversation watermark over turn
> ordinals**, held on the conversation index as durable state of the
> `ConversationStore`. It is not held by the scheduler, not held in the
> `MemoryStore`, not held in a store of its own, and not passed as an argument to
> any `Engine` operation.

> **Normative.** The watermark's meaning is exactly this and nothing wider: **the
> observation walk over that conversation has advanced past that ordinal, and no
> later pass selects a turn at or below it.** It is a **position in the walk, not a
> certificate of coverage**: it does not record that every turn below it was read, that
> a belief was proposed, that a proposal was ruled, that an episode resolved, or that a
> model was called.

> **Normative.** Two named cases leave turns below a watermark that no pass read, and
> they are stated here rather than left to be discovered. A conversation whose **first**
> pass begins at its tail window (§4) leaves every turn below that window beneath the
> first watermark recorded; and a turn whose episode did not resolve is passed over
> (§5). Neither is a defect of the watermark, because the watermark asserts nothing
> about them. What a reader may conclude from a watermark of *n* is that the turns
> above *n* are the walk's remaining work — and nothing whatever about the turns
> below it.

**The placement is ADR-0111 §1's, applied.** Its first clause puts a job's
resumption position in "the subsystem whose store the job walks", and its decisive
argument is atomicity: "Only the component holding the store's connection can do
that. The scheduler holds a façade, so a scheduler-owned cursor could only ever be
written *after* the operation returned". The conversation index is the store whose
progress an observation pass records — it is the store that allocated the ordinal
the watermark names — so it is the store that can write the position under the same
per-conversation exclusion its other mutations run under (§8).

**Not the `MemoryStore`, and ADR-0078 §1's argument is the one that decides it.**
That section rejects hosting a non-belief in the memory store because "it would
make the store's records a mix of beliefs and non-beliefs, which is the exact
distinction ADR-0072/ADR-0073 spent two ADRs making legible". A watermark is
bookkeeping about how far the walk has got; it is not a belief of any band,
contributes no confidence and no evidence, and must not be reachable by `MemoryStore.search`,
`MemoryStore.export` or `assistant beliefs`. Holding it as a memory record would
put it in all three.

**Not a store of its own.** ADR-0078 §1 argues a new store as "the heaviest option
available" and earns it because "the thing it persists […] genuinely exists nowhere
today". That is not true here: the ordinal a watermark names is already the
conversation index's, and a second store would need the index to answer its own
precondition — the shape ADR-0074 §9 already ruled on, that "a `ConversationStore`
asked to reclaim would have to reach into memory to answer its own precondition".

**Per conversation, not per turn.** ADR-0205 §3's precedent is a field on
`ConversationTurn` because the fact it records is about one turn. This fact is
about a conversation, and one integer answers it for a log of any length. A
per-turn "observed" stamp would be ADR-0111 §2's excluded shape in a different
spelling — "**A set of identifiers** is unbounded durable state that grows with the
store, so the mechanism that exists to make a walk affordable becomes the largest
thing in the database" — and it would cost a write per turn where this costs one
per pass.

### 2. What the cursor is a position in, and what it is not

> **Normative.** The order the cursor names a position in is **turn ordinal
> ascending, within one conversation**. The position is a turn ordinal and nothing
> else: not an episode id, not an instant, not a page number, not a count of
> episodes read, and not a position in any order spanning more than one
> conversation.

> **Normative.** The observation selector holds **one position per conversation**,
> and the positions of two conversations are independent. A conversation's position
> is meaningful only against its own ordinals.

**The order satisfies ADR-0111 §2 as written, and it is the only order in this
contract that does.** §2 requires an order "the walked store already maintains,
which must be total over the walked rows and must not reorder rows under later
writes". Per conversation, ordinals are "dense from
:data:`~ai_assistant.core.types.FIRST_TURN_ORDINAL`, unique, and monotonic"
(`ConversationStore`), allocated by the store inside the same indivisible step that
writes the row (`ConversationStore.append`), and `FIRST_TURN_ORDINAL` is public
"because every `ConversationStore` implementation and its conformance suite need
the same starting point". An append adds a row above every existing one and moves
none of them, so the "must not reorder" half holds on the most ordinary write the
store takes.

**A single order across conversations was considered and is not available.** There
is no such total order in this contract. `ConversationTurn.occurred_at` is
"**When the exchange this turn records happened**", supplied by the *caller's*
injected clock — `ConversationStore.append` takes it as an argument, "Passed rather
than read here so the turn and the episode recording it carry one instant" — which
is exactly ADR-0111 §2's excluded shape: "**A wall-clock instant** is not a total
order over writes and does not have to be monotone with them: a row written with an
earlier instant after the cursor passed — a backfill, a clock correction, an instant
supplied by a caller rather than by the store — sits permanently behind the position
and is never reached". A backend's `rowid` would be one implementation's private
order rather than one the *contract* maintains, so two conforming stores could
disagree about the same page. And ADR-0111 §1's second clause already licenses the
per-conversation family: "one job walking two orders holds one position in each".

**The watermark is a high-water mark, and ADR-0111 §2 names that limit rather than
hiding it.** "A row updated in place below the cursor keeps its position and is not
revisited […] For a one-shot migration that is fatal and §2 spends a fingerprint on
it; for a *recurring* job it is usually correct, because the work is the new
material." The one shape of "updated below the cursor" this walk can meet is a turn
whose episode had not landed when a pass read its row, and §5 closes the only case
of that which is reachable.

### 3. The selection rule: candidates, their order, and the per-pass bound

> **Normative.** A conversation is a **candidate** for observation when it is not
> stamped deleted and it holds at least one turn whose ordinal is strictly above its
> watermark — every turn, where no watermark is recorded. Candidacy is not restricted
> to the most recently active conversation.

> **Normative.** Candidates are ordered by `last_active_at` **ascending**, ties
> broken by `id` ascending. That order is total, and no consumer re-sorts it.

> **Normative.** One pass observes **one** conversation: the conversation named by
> the operation's optional id, or — given none — the first candidate in that order.
> Given none and no candidate, the pass reads no turns, calls no model, and reports
> nothing observed.

> **Normative.** The pass reads that conversation's **turns above its watermark,
> ordinal ascending, at most `observation_batch_size` of them** — the lowest such
> page, not the tail. The bound is unchanged in value and unchanged in kind: it
> remains a maximum and not a quota, so a page containing a turn whose episode does
> not resolve yields a shorter batch rather than reaching further forward.

> **Normative.** One pass makes at most one `Observer.observe` call, and a pass
> whose page resolves to no episode makes none. A run that wants more than one
> conversation performs more than one pass; no pass mixes two conversations' turns
> into one batch.

**What changes from ADR-0077 §8, precisely.** Its sentence — "The operation takes an
optional conversation id: it observes **that conversation's most recent
`observation_batch_size` turns**, or, given none, the same window over the **most
recently active** conversation" — becomes: the id names the conversation, no id
selects the first candidate, and in both cases the page read is the *lowest*
`observation_batch_size` turns above the watermark rather than the most recent ones.
The bound, its `Settings` field and its maximum-not-quota reading are untouched, as
is the skip rule: "**A turn in the window whose episode does not resolve is skipped,
and the batch is not backfilled.**"

**Why ascending activity, and not the `recent` order.** `ConversationStore.recent`
orders "by `last_active_at` descending, ties broken by `id` ascending", and taking
its head is what the stage does today. ADR-0074 §9 states that order as a rule over
*every* conversation read — "conversations by last activity descending with the id as
tie-break" — so this ADR replaces that rule for this one operation, and §10(b) records
it rather than reading the rule down. Descending cannot be the candidate order: a
conversation that keeps receiving turns would be selected on every pass and a
conversation the user has stopped using would never be reached — which is ADR-0077
§8's first named gap ("a conversation the user never observes") reintroduced through
the cursor, and #1737's item 3 directs it closed. Ascending has three properties
worth stating together:

- **It excludes no candidate, and under a monotonic clock it starves none.** A
  conversation leaves the candidate set once its watermark reaches its highest turn
  — which takes as many passes as it has pages of unobserved turns, not one — and one
  that keeps receiving turns keeps having its key moved to the *back* of the order.
  Where the clock advances monotonically, every candidate is therefore reached in a
  bounded number of passes.

  **The bound is a property of the clock, and this ADR does not promise more than the
  clock gives it.** `Conversation` states that "`started_at`, `last_active_at` and
  `last_turn_at` all come from an injected clock, which this project never promises is
  monotonic (`core/clock.py`)". A clock that is stopped or stepped back can therefore
  leave a busy conversation's `last_active_at` at or below an idle one's, and where
  the tie is broken by an `id` that also sorts first, the busy conversation can be
  served ahead of the idle one indefinitely. That is **accepted and named**, not
  closed: closing it would take a durable service-order position, which is a second
  cursor with its own upgrade discipline and its own `core` surface, bought against a
  clock adjustment rather than against anything the walk does. What this order
  guarantees unconditionally is the property the descending order lacks — that a
  conversation is a candidate on its own terms and is never excluded because a
  different conversation is more active.
- **It serves the material nearest its expiry first**, which is the ordering that
  maximises coverage under a finite horizon. ADR-0074 §7 reclaims a conversation on
  `last_active_at` — "Eligibility reads *activity*, not `last_turn_at`" — so the
  first candidate in this order is the one nearest reclaim.
- **The key is the store's own.** `ConversationStore.mark_active` "Sets
  `last_active_at` from the store's clock", where `occurred_at` is the caller's.
  Ordering a *listing* by an instant is not ordering a *cursor* by one, so ADR-0111
  §2's wall-clock exclusion does not reach it; a listing whose key moves is one row
  in a different place on a later page, which is what every bounded listing in this
  store already accepts (`ConversationStore.recent`: "Offset paging over a mutating
  store may skip or repeat a row; that is accepted rather than closed").

**Why one conversation per pass.** ADR-0077 §1's batch is source-agnostic — "The
Protocol still takes episodes and the producer still never asks where they came
from" — so mixing two conversations into one `Observer.observe` call would not breach
the contract. It is refused anyway: the batch is a prompt, and two interleaved
transcripts in one prompt is a different thing to observe, which ADR-0077 §8's own
ground for choosing the conversation as the unit rules out ("the selection is
deterministic enough to test"). Bounding the *pass* at one conversation also keeps
`observation_batch_size` meaning one thing rather than two, which is #785's third
question — "**Whether `observation_batch_size` bounds the window or the chunk** once
the selection is a walk rather than a tail read". It bounds the page a pass reads,
and a pass is a chunk in ADR-0111 §4's sense: "A chunked job's single run commits
chunks until either its work is exhausted or its run budget is spent". How many
chunks one scheduled run performs is ADR-0111 §4's and the trigger's (§9), not this
section's.

**A hand-run `observe` reads the same watermark.** There is one selector, so the CLI
and the scheduler cannot disagree about what has already been looked at — which is
ADR-0111 §1's point that "both resume from the same durable position". The named
consequence: `assistant observe <id>` run twice in succession does something the
first time and nothing the second, reporting a pass that read no episodes. That is
the honest answer to "what has already been looked at", and re-deriving a belief is
not what re-observation is for. An operation that deliberately ignores the watermark
is not decided here (§9).

### 4. A conversation with no watermark starts at its tail, not at its first turn

> **Normative.** Where a conversation has no recorded watermark, the pass reads
> **ADR-0077 §8's window unchanged** — that conversation's most recent
> `observation_batch_size` turns — and records the watermark §5 names from it. It
> does not read forward from the conversation's first turn.

> **Normative.** The absence of a watermark is read, never written: no pass, store
> or migration initialises a watermark to a sentinel, to zero, or to
> `FIRST_TURN_ORDINAL`. `None` is the only spelling of "no pass has recorded one".

**This is the one place this decision departs from ADR-0111, and the departure is
declared rather than argued around.** §2's clause reads "A cursor absent from the
store means the walk has not started and the job begins at the first row of its
order. A cursor is never initialised to a sentinel value." The second sentence binds
here unchanged and is restated above. The first would have the first pass over an
existing conversation begin at ordinal `FIRST_TURN_ORDINAL`, and it is replaced for
this cursor only (§10(c)).

Three reasons, in the order they bind:

1. **It re-pays for turns already observed by hand.** Until this ADR lands, the only
   observation that happens is `assistant observe`, and it reads the tail. Walking a
   pre-existing conversation from its first turn spends a model call on material a
   hand-run pass may already have distilled — the exact cost `core/config.py` names
   at the interval field ("buys repeated cost and no new coverage"), arriving through
   the mechanism that exists to remove it. #1737's item 2 is explicit that "the
   pre-cursor episodes ADR-0074 §7 will expire are not re-paid".
2. **It reaches nothing the corpus has not already written off.** Turns older than
   the tail in a pre-existing conversation are ADR-0077 §8's *second* named gap, and
   §8 already rules that they "expire unobserved under ADR-0074 §7's horizon".
   Starting at the tail keeps that accepted gap exactly as wide as it is today, for
   the conversations that existed before the cursor did, and closes it for every
   turn recorded afterwards. Starting at ordinal 1 would *widen* coverage
   retroactively, which is a different decision from the one #1737 asks for and one
   nobody has costed.
3. **It makes the first enabled tick's behaviour a function of ancient history.** A
   conversation with a long expired prefix yields page after page of turns whose
   episodes do not resolve. Each such page costs an index read and up to
   `observation_batch_size` `MemoryStore.get` calls and produces no belief, and
   live material sits behind it for as many passes as the prefix is long.

**What this rule costs, stated at its true size.** A tail start passes over **every
turn below the window it reads**, and that prefix is as long as the conversation is:
1,000 turns at a bound of 20 loses 980, not 20. The three reasons above are why that
loss is accepted for a conversation that existed before the cursor — those turns were
already written off by ADR-0077 §8's second gap and ADR-0074 §7's horizon — but the
rule does not know which conversations those are, and its cost is not bounded by the
window.

**It reads the same for a conversation created after the cursor lands, and that is the
limit of a watermark carrying no epoch.** Nothing on the index records when the cursor
arrived, so an absent watermark cannot distinguish a conversation older than this
decision from one that gathered turns faster than the job reached it. A conversation
that accumulates a long history before its first pass loses all of it below the tail,
permanently, exactly as a pre-existing one does. What is true — and is the whole of the
comfort available — is that **this** loss is per *first* pass and not per pass: the
prefix at risk is only what accumulates before the first pass reaches that
conversation, and no later pass re-opens it. That is a statement about the tail start
alone and about nothing else. §5's residual is a separate later-pass skip, much
narrower and differently caused — a turn whose episode did not resolve while a later
turn's did — and §1's second clause names both rather than either. On the deployment this ADR is written for that is the whole backlog,
because `observation_interval` is unset and nothing runs the job; it shrinks toward
zero once observation runs on a cadence, which is #1737's second ADR (§9) and the
reason this one lands first.

**And it recurs on a discard.** §7 treats an unreadable or unsupported watermark as
absent, so the next pass over that conversation is a first pass again and skips
everything below its tail — including turns the discarded value had already been
advanced past. ADR-0111 §7 prices a discard as "a repeated walk"; under §4 it is a
skipped prefix instead, which is a strictly worse price and is named here rather than
left in the gap between two sections. It is accepted because the alternative is the one
ADR-0111 §7 forbids outright — a bookkeeping column refusing the hub's start — and
because the discard is reachable only from a corrupt or unsupported value and never
from ordinary operation.

**None of this is a claim the row makes.** §1's second clause is worded so the
watermark never asserts those turns were read, and the Consequences state the gap this
leaves beside the one it closes. Buying the prefix back takes either a durable epoch on
the index — a second store-written fact, which §5's closing paragraph prices and §9
defers — or a deliberate re-observation that ignores the watermark, which is **#1789**.
Neither is bought here.

**Nothing is skipped in ADR-0111 §3's sense.** Its at-least-once clause forbids an
implementation that "turns that repetition into a skip" — it governs a chunk whose
effects happened and whose cursor did not advance. This clause is about where a walk
*begins*, and beginning at the tail loses no chunk any run performed.

### 5. The advance: one attempt per pass, to the highest turn it handed over

> **Normative.** A pass that read a **non-empty** page makes **exactly one** attempt to
> advance the watermark, after every proposal it produced has been ruled by the write
> path — one `record_observed` call and no other write to the watermark. It makes that
> attempt even where the page resolved to no episode, even where the observer was not
> called, and even where nothing was proposed.

> **Normative.** A pass that read **no turns** makes **no** attempt and writes nothing.
> That is every pass with no target — §3's "given none and no candidate" — and every
> pass over a conversation holding no turn above its watermark, including one the
> operator named explicitly. There is no ordinal for such a pass to name, `None` is not
> one, and `record_observed` refuses anything below `FIRST_TURN_ORDINAL` before any I/O
> (§8). Such a pass calls no model, writes nothing anywhere, and reports nothing
> observed.

> **Normative.** The position it names is **the highest ordinal in the page whose
> episode resolved** — the highest turn the pass actually handed to the observer. Where
> **no** turn in the page resolved, it names the page's highest ordinal instead.

> **Normative.** The watermark never moves backwards. A recorded value is never
> lowered, and a request to record a value at or below the recorded one performs
> nothing.

> **Normative.** A pass that read a non-empty page therefore always names a position
> **strictly above the watermark that pass read** — both branches name an ordinal from
> the page, and every ordinal in the page is above that watermark. Its attempt either
> advances the watermark, or performs nothing because an overlapping pass has already
> advanced it to at or above the same position. So **the watermark never stands still
> across a pass over a non-empty page**, and a conversation with turns above its
> watermark cannot be re-read indefinitely.

> **Normative.** Two passes over one conversation may overlap, and neither the store
> nor this decision serialises them. Each pass computes its position from **its own**
> page and its own resolution of that page's episodes, and the two may legitimately
> differ — an episode can land, expire or be forgotten between the two reads, and the
> index and the memory store share no transaction and no snapshot. Overlap safety
> rests on `record_observed`'s monotonicity (§8) and on nothing else: each call stamps
> if and only if its ordinal is strictly above the recorded one, so whichever order the
> calls arrive in, the **higher** of the two positions stands and the lower performs
> nothing. Where the two name the same position that is the same rule and not an
> exception to it: an attempt that loses is an attempt whose position already stands.

> **Normative.** No pass names a position above what that pass itself read. The
> invariant above is therefore a property of the **watermark under any interleaving**,
> and never a promise that each individual pass is the one that moved it or that two
> passes agree about where to move it.

**Advancing once, at the end, is ADR-0111 §3's ordering and not a choice per pass.**
Its clause: "Where the effects land in a different store from the cursor, the
effects are made durable first and the cursor is advanced afterwards, never the
reverse." An observation pass reads the conversation index and the memory store and
writes to the memory store and the deferral queue; the watermark is on the index. So
the advance attempt is the last act of the pass, and ADR-0111 §3's asymmetry is the
reason: "A cursor that lags its effects costs repeated work; a cursor that leads them
costs coverage, permanently and silently".

**This is #1737's rule with exactly one fallback added, and the fallback is what stops
a stall.** Item 3 words it as "the cursor advances to the last turn *handed over*, not
the last turn that produced a proposal, and advances even when the observer proposes
nothing". The second and third halves are ratified above word for word, and the first
is the first branch above. What the note does not consider is a page that hands nothing
over: the watermark would not move, the next pass would read the same page, and it
would not move again. A conversation whose unobserved turns have all expired — the
ordinary state of one the job reaches after a long idle period — would be a permanent
candidate re-reading one dead page for as long as it lives, which is ADR-0111 §7's own
diagnosis of the shape it forbids ("permanently and quietly stopped", where "the
operator gets a permanent, opaque failure instead of a slow success"). The second
branch closes that in one pass, and it costs nothing: a page that resolved to no
episode reached no observer at all (§3), so passing over it passes over nothing that
was ever readable.

**A trailing gap is therefore given another reading, and an interior one is not.**
That asymmetry is deliberate and it is bought where it pays. A turn whose episode does
not resolve is ordinarily a settled gap — a capture failure, an expiry, or a `forget` —
which ADR-0074 §5 rules is "skipped, not an error". But it can also be a turn whose
episode is still **in flight**: the index is an intent log, and
`ConversationLifecycle.capture` records "the index entry first, then its episode", with
"The cost is that a crash between the two writes leaves an index entry with no episode,
which every reader already renders as a gap." That window is not instantaneous — the
same docstring notes that "``write_atomic`` awaits an embedder before it reaches its
own lock" — so a pass can read a row whose episode lands a moment later. **Where
captures of one conversation are sequential, an in-flight turn is always the newest
turn**, because a later append happens after the earlier capture returned; and the
newest turn is exactly what the first branch stops below. So the common case is
covered by the rule itself rather than by a special case for it.

**Worked, because the arithmetic is the decision.** Watermark 100, bound 20:

- Page 101–120, all resolved → the highest resolved is 120 → advance to **120**.
- Page 101–120, 120 unresolved → the highest resolved is 119 → advance to **119**. The
  next page begins at 120: if its episode has landed in the meantime it resolves and
  is observed; if it has not, that page resolves nothing and the second branch advances
  past it.
- Page 101–120, 105 unresolved → the highest resolved is 120 → advance to **120**. Turn
  105 is passed over. Nothing is re-read and no model call is repeated.
- Page 101–120, none resolved → no observer is called, and the second branch advances
  to **120** in one pass rather than one turn at a time.

**The residual, stated so nobody discovers it as a defect.** A turn is missed when its
episode is in flight while a *later* turn of the same conversation has already
committed one — which takes two captures of one conversation overlapping, since
sequential captures leave the in-flight turn newest — or when it is in flight across
two consecutive readings at the tail. Both are narrow, and the loss is one turn's
*distillation*: the episode itself is unaffected, stays readable by retrieval, and
expires on its own horizon. This is the limit ADR-0111 §2 already names and accepts for
a recurring job — "A row updated in place below the cursor keeps its position and is
not revisited […] for a *recurring* job it is usually correct, because the work is the
new material" — and it is what ADR-0077 §8's skip rule already does today, made
permanent by the cursor rather than introduced by it. Closing it entirely would take a
durable per-turn "the episode landed" fact, which is a second store-written member on
`ConversationTurn` and a second write on every capture. That is not bought here, and §9
names the conditions that would buy it.

**What is deliberately *not* bought is a rule that gives every gap a second reading.**
Such a rule has to stop the watermark below the lowest unresolved turn, which re-reads
that page's resolved turns above the gap on every following pass until the gap clears,
and needs a further fallback for a page whose lowest turn is the gap — and a further
one again for a page carrying two. Each fallback is another place for the rule to
disagree with itself, and the coverage it buys is the interior in-flight turn alone.
The simpler rule pays for that one turn instead.

### 6. Failure: a pass that raises before its attempt leaves the watermark alone

> **Normative.** A pass that raises **before** its advance attempt — reading the
> index, resolving an episode, calling the observer, or ingesting a proposal — moves
> the watermark by nothing. There is no partial advance within a pass, and no pass
> writes the watermark more than once (§5).

> **Normative.** A pass that raises **at** its attempt leaves the watermark in one of
> two states, and the ADR does not pretend otherwise: the stamp may have committed
> before the failure reached the caller, or it may not. Cancellation is the case that
> makes this unavoidable rather than sloppy — `ConversationStore` is governed by "this
> module's cancellation clause (ADR-0060)", and a store whose write runs in a worker
> thread can commit and then have the awaiting task cancelled before the call returns.
> **Both outcomes are safe and neither is a defect**: if the stamp landed, every
> proposal of that pass had already been ruled (§5), so the position records work that
> was done; if it did not, the page is re-read and folds to `REINFORCE` (below). No
> implementation may add a compensating write, a re-read of the watermark to "confirm"
> it, or a retry of the attempt inside the same pass — each of those is a second write
> to the watermark, which §5 forbids, and none of them can distinguish the two states
> anyway.

> **Normative.** Where a failed pass's advance attempt did **not** commit — every
> failure before the attempt, and the half of the ambiguous case above in which the
> stamp did not land — the whole page that pass read is re-read by the next pass, and
> the repetition is safe rather than merely tolerated. Where the stamp **did** commit,
> the whole page is not re-read and does not need to be: the next pass resumes above
> the recorded position under §3's ordinary candidacy rule, and §5 lets a pass name
> that position only after every proposal it produced has been ruled, so the position
> records work that was done. In neither case may an implementation narrow a re-read to
> "the turns whose proposals were not ruled".

**This is ADR-0111 §5, inherited whole.** "When a chunk cannot be recorded as done,
the run stops immediately, leaves the cursor at the last chunk that was recorded,
and returns without processing any later chunk." A pass is the chunk (§3), and §5's
own argument for halting is §2's contiguity: a cursor is one position in one order,
so a partially-advanced position "no longer means what §2 says it means".

**Why a proposal-by-proposal advance is not available, even though #1737 item 4
proposes one.** That item says "a run that ingests some proposals and then fails
advances only through the turns whose proposals were ruled". Proposals are not a
partition of the page: `ObservationStage._check_citations` enforces only that every
citation is "drawn from the batch", so one proposal may cite several turns, one turn
may be cited by several proposals, and a turn may be cited by none. "The turns whose
proposals were ruled" therefore does not name a *position* in the ordinal order, and
a watermark that is not a position is ADR-0111 §2's first excluded shape. The whole
of what item 4's first half asks for is delivered by the clause above: a run that
raises before ingest leaves the watermark, and so does one that raises after a
partial ingest.

**The repetition is already ruled safe, by the section this ADR supersedes in
part.** ADR-0077 §8: "A second run over the same episodes re-proposes much the same
beliefs, and the gate folds each into a `REINFORCE` on the existing record rather
than writing a duplicate (§4) — while §5's confidence function **closes the
repetition route to inflation**: the same belief on the same support scores the same
however many times it is derived, so a fold that takes the maximum finds nothing
higher." ADR-0111 §3 relies on exactly that quotation for exactly this purpose, and
names the price: "a model call and a moved `provenance.last_updated`", accepted
there and accepted here. Nothing in this ADR weakens the fold, and an implementation
may not rely on the watermark to make re-observation safe — the fold is what does
that, and the watermark only makes it rare.

**No backoff.** ADR-0111 §6 binds unchanged: "A run that halts or raises is retried
at its next due instant under ADR-0083 §7's fixed delay after completion. No job
varies its interval in response to failure, and no failure count is durable." This
ADR adds no failure count and no per-conversation retry state.

### 7. Upgrade discipline: ignored by an older build, discarded when unreadable

> **Normative.** The watermark is **additive and acted on by one consumer only** —
> the observation selector. `Conversation` carries the member, so every read that
> returns a `Conversation` — `get`, `recent`, `turns`' conversation, `export` — carries
> it too, and the export's version moves for exactly that reason (§8). What no other
> read changes is its **behaviour**: because a watermark is present, absent, high or
> low, no read selects a different set of rows, orders them differently, refuses where
> it would have answered, or returns a different value in any other member. No consumer
> but the observation selector may branch on it.

> **Normative.** A build that does not read the watermark **ignores it and must not
> refuse to start over it.** A watermark is not state ADR-0083 §6 makes a state
> fault: it holds no evidence, answers no query, and a build that ignores it serves
> every operation exactly as that build served it before.

> **Normative.** A build that reads it and finds none applies §4 — the tail window —
> and not ordinal `FIRST_TURN_ORDINAL`.

> **Normative.** A watermark that is **unreadable, malformed, or not supported by
> the conversation's own turns** — not an integer, below `FIRST_TURN_ORDINAL`, or
> above the highest ordinal the conversation holds — is **discarded**, and the
> conversation is treated as one with no watermark. It is never levelled, never
> advanced past a value that could not be read, and never a state fault:
> `IncompatibleStateError` is not its class, no read raises for it, and it never
> refuses the hub's start.

> **Normative.** That discard is the store's, made where the record is built. A
> `ConversationStore` implementation reading such a value yields a record whose
> watermark is absent, and does **not** raise the `ConversationStoreError` it raises
> for a corrupt row.

**This is ADR-0111 §7's disposition, and §7's argument transfers word for word.** "a
cursor holds no evidence and answers no query. Discarding one costs a repeated walk —
the cost §3 already accepted and ADR-0077 §8 already named — and returns nothing
wrong to any client. So an unreadable cursor is not a state fault,
`IncompatibleStateError` is not its class, and a build that refused to start over one
would take a resident process down over scaffolding."

**Where the restart lands is the second clause of ADR-0111 this ADR replaces, and it
is declared rather than described as a difference.** §7's own words are "the walk
restarts **from the beginning of its order**", in both its clauses — the unreadable
cursor and the cursor that disagrees with the store's contents. This ADR restarts at
the tail instead, because a discarded watermark is read as absent and §4 governs an
absent one. **That changes the price of a discard**: ADR-0111 §7 prices it as "a
repeated walk", and here it is a skipped prefix — including turns the discarded value
had already been advanced past — which §4 states at its true size. It is accepted for
§4's three reasons and because the alternative is the fault §7 forbids outright; and
because it is a change a reader of ADR-0111 would act on, §10(c) records it as a
partial supersession rather than leaving it in the gap between two sections. **What
is not replaced is §7's disposition itself**: discard rather than fault, never
`IncompatibleStateError`, never a refusal to start, never advanced past a value that
could not be read. Those bind here word for word, and are the whole of the clauses
above.

**The store-side clause is not a detail.** `ConversationStore` promises to raise
`ConversationStoreError` "If the store cannot be read, **or a stored row is
corrupt**", and `Conversation` is a frozen pydantic model with `extra="forbid"`. An
implementation that let a bad watermark reach the model's own validation would turn
one unreadable integer into a `ConversationStoreError` on `get`, `recent`, `turns`
and `export` for that conversation — a conversation the user can no longer read
because a bookkeeping column is wrong, which is precisely the outcome ADR-0111 §7
forbids, arriving through a different door. So the coercion is stated as an
obligation of the store rather than left to an implementation's taste.

**The disagreement case is reachable and is the same disposition.** ADR-0111 §7's
second clause — "A store whose recorded cursor and recorded progress disagree is
treated as damaged in the same way" — is met concretely here by
`ConversationExport`: the export carries `conversations` and `turns` side by side,
and the user-facing export "drops those turns" whose episodes no longer resolve
(`ConversationExport`), which is one way a watermark and the turns beside it come
apart on paper. **The reachable case is a store state, not a restore**, and the
distinction matters because `ConversationStore` offers `export` and no import (§8), so
nothing here reads such a document back. What the clause above governs is a *store*
whose watermark names an ordinal its own turns do not reach — from an operator's hand
edit, a partial recovery, a `forget` that took a turn row, a migration, or a downgrade
that dropped rows. That is discarded, and the conversation re-enters at its tail. Any
future import path inherits the same clause and needs no new rule; deciding whether
one should exist is not this ADR's (§9).

**An older build's passes do not write it, and that is safe.** A downgrade followed
by an upgrade leaves the watermark lower than what was actually observed in between,
so the newer build re-reads turns the older build read. That costs the model call
ADR-0077 §8 already prices and produces a `REINFORCE`; it cannot lose coverage,
which is the direction ADR-0111 §3 requires.

### 8. The contract surface owed, and what the implementing lane owes

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/types.py`** gains **exactly one member on one existing type**.
  `Conversation` gains `observed_through: int | None`, defaulting to `None`, bounded
  `ge=FIRST_TURN_ORDINAL`, described as the highest turn ordinal an observation pass
  has recorded for this conversation and unset until one has. No new type, no member
  on `ConversationTurn`, no member on `ConversationSummary`, no member on
  `ConversationDigest`, and no member on `ObservationReport`.

> **Normative.** `ConversationExport.schema_version` becomes **exactly 2** —
> `Literal[2]`, refusing every other value — because `ConversationExport` carries
> `tuple[Conversation, ...]` and this member changes the shape of the portable
> document. ADR-0014 §5 states why the field exists — "an export outlives the code
> that wrote it … a reader must be able to tell which shape it is holding" — and
> ADR-0039 §10 applied it to the sibling export in this exact shape: "`StepExecution`
> is inside the export, so its shape changing is exactly what the version exists to
> announce", pinned rather than defaulted so that "the advertised version is a fact
> about the document rather than an unchecked producer's claim". **No migration is
> owed**, and for ADR-0039 §10's reason rather than because no v1 document exists:
> `ConversationStore` offers `export` and no import, restore or load, so nothing in
> this system ever validates a `ConversationExport` it did not just construct.

**One thing this bump does not do, and it is worth naming rather than leaving to be
found.** ADR-0205 §3 added `ConversationTurn.delivery` — also inside this export —
without moving the version, so the shape that ships today is a v2-shaped document
labelled v1 by ADR-0039 §10's reasoning. This ADR does not relabel it: ADR-0001's
append-only rule is not the obstacle (a label is not decision text) but there is no
read path to relabel *for*, and rewriting the meaning of a version nobody can read
buys nothing. Moving to 2 here announces the shape that ships next. The gap is
recorded as **#1793** rather than absorbed, and it is not this ADR's to decide beyond
saying so.
- **`core/protocols.py`** gains **exactly three operations on `ConversationStore`**,
  and no new Protocol. **All three are `async def`**, as every method of that Protocol
  already is: each reaches the store, and `CLAUDE.md` makes I/O-bound methods `async`.
  The signatures below are written in that form rather than leaving it to be inferred:

  1. `async def turns_after(conversation_id, *, after_ordinal: int | None = None,
     limit: int | None = None) -> list[ConversationTurn]` — the **forward** page: the *lowest*
     `limit` turns whose ordinal is **strictly above** `after_ordinal`, ordinal
     ascending. `after_ordinal` `None` reads from the conversation's first turn;
     `limit` `None` asks for the store's configured replay window, exactly as
     `ConversationStore.turns` does. It refuses `after_ordinal` outside
     `[FIRST_TURN_ORDINAL, 2**63)` and `limit` outside `[0, 2**63)` with
     `ValueError` — ADR-0073 §2's posture, the same refusals `turns` carries for
     `before_ordinal` and `limit`, refused rather than clamped. It is a presenting
     read, so it raises `UnknownConversationError` for an id that names nothing or
     names a conversation stamped deleted, and `ConversationStoreError` for a store
     fault. A short page means there is nothing above it — which is a fact about the
     read and not a discriminator any advance rule may use (§5).
  2. `async def conversations_with_unobserved_turns(*, limit: int = 50) ->
     list[Conversation]` — every conversation that is not stamped deleted and holds
     at least one turn whose ordinal is strictly above its `observed_through`, or
     any turn at all where that is `None`; ordered `last_active_at` ascending with
     `id` ascending as the tie-break; bounded by default at **50**, the figure
     `ConversationStore.recent` already sets and ADR-0073 §2 already argues, with
     `0` returning an empty page and a `ValueError` outside `[0, 2**63)`. It takes
     **no cursor and no offset**, and the reason is that no consumer pages it: the
     stage takes the head of a freshly-read listing on each pass and never asks for a
     second page, because a pass serves one conversation (§3). Offering an offset
     would offer a position over a set whose membership and whose ordering key both
     move between passes — a row leaves once its watermark reaches its highest turn,
     and `last_active_at` moves under every turn — which is the hazard
     `ConversationStore.recent` already names for offset paging ("may skip or repeat
     a row") and `ConversationStore.stamped_conversation_ids` already refuses for a
     walk whose rows leave under it.
  3. `async def record_observed(conversation_id, *, through_ordinal: int) ->
     Conversation | None` — stamps the watermark and returns the conversation as stamped, or
     `None` where it stamped nothing. It stamps if and only if `through_ordinal` is
     **strictly above** the recorded watermark **and at or below** the highest
     ordinal the conversation holds; where either fails it performs nothing,
     returns `None`, and raises nothing — `record_delivery`'s shape and its reason,
     "no row is written, and no error is raised". It refuses `through_ordinal`
     outside `[FIRST_TURN_ORDINAL, 2**63)` locally with `ValueError`, before any
     I/O, on ADR-0085 §3's convention. It raises `UnknownConversationError` for an
     absent or stamped conversation and `ConversationStoreError` for a write fault
     — the same two refusals `append` and `record_delivery` carry.

> **Normative.** `record_observed` joins the per-conversation mutation exclusion
> `ConversationStore` states for `append`, `mark_active`, `record_delivery`,
> `stamp_deleted` and `drop_if_eligible`: per conversation those mutations "never
> interleave; each observes the conversation, decides, and writes as one indivisible
> step". Reading the two conditions above and writing the row is one such step, so
> two concurrent advances leave the higher value recorded and neither leaves the walk
> positioned above what one of the two passes actually read.

> **Normative.** The **second** condition on `record_observed` — at or below the
> conversation's highest ordinal — is the store holding ADR-0111 §3's "never lead"
> direction rather than trusting a caller's discipline. It is unreachable through
> the stage this ADR describes, which only ever names an ordinal it read from this
> store, and it is a property of the seam because `ConversationStore` is a
> cross-subsystem contract and a consumer that is not the engine may hold it.

> **Normative.** `record_observed` **bounds** the position and does not **certify**
> it. The store takes the caller's ordinal, refuses one that would lead the
> conversation's own turns and one that would lower the recorded value, and asserts
> nothing about what the caller read to compute it. A caller that stamps an ordinal it
> never read has mis-positioned the walk, which is a defect in that caller, not a false
> statement by the row — §1's second clause is worded so that the row makes no claim
> that could be false.

**Why the store issues no evidence of the page it served, and could not.** A rule
requiring `record_observed` to accept only a position the store itself vouched for
would have the store hold per-reader state about which page each caller had been
handed — durable if it is to survive a restart, and growing with readers and pages.
That is ADR-0111 §2's first excluded shape in a different spelling ("**A set of
identifiers** is unbounded durable state that grows with the store, so the mechanism
that exists to make a walk affordable becomes the largest thing in the database").
The alternative — folding selection, observation and advance into one store operation
— would put the model call inside `ConversationStore`, which golden rule 1 forbids and
which §5 separately rules out, since holding the per-conversation exclusion across a
pass would hold it across a model call. ADR-0111 §1 already settles the division this
leaves: the walking job computes the position and the store makes it durable. No cursor
in this corpus is certified by its store, and this one is not the first.

> **Normative.** `PROTOCOL_VERSION` does not move for this decision, and the
> implementing lane does not bump it. ADR-0124 §9's rule is that it "is bumped by
> any change after which a frame a conforming peer at the new version may send would
> be refused by a conforming peer at the old version, or would be accepted by it with
> a different meaning". This adds no operation to the promoted engine surface, no
> argument to one, and no member to any wire-carried `core` type: the conversation
> listing crosses the wire as `ConversationSummary`, which gains nothing, and
> `Conversation` itself is not a wire-carried type. `ObservationReport` is unchanged,
> so the observation call's result is byte-identical in shape. **The export version
> move above does not reach the wire either**: no operation on the promoted engine
> surface returns a `ConversationExport` — `ConversationStore.export` is the only
> declaration of it in `core/protocols.py` — and `wire/surface.py` derives its method
> set from that promoted surface, so no frame carries the document whose label
> moves.

> **Normative.** No `Settings` field is added, and no default changes. In
> particular `observation_interval` keeps its `None` default: ADR-0083 §7's job
> table still ships the observation job disabled, and flipping it is the trigger
> ADR's act and not this one's (§9).

**What the implementing lane owes**, stated so it is written rather than assumed:

> **Normative.** The contract half lands as **one change**: the member on
> `Conversation`; the three operations on `ConversationStore`; and — because
> `ConversationStore` gains members — that Protocol's shared conformance suite and
> its canonical fake in `ai_assistant.testing` extended in the same change, which is
> `CONTRIBUTING.md` → "Adding a Protocol" applied to a widened one. **This is a
> breaking Protocol change and the lane flags it** (golden rule 5).

> **Normative.** The `orchestration` half owes the selector of §3 in
> `ObservationStage`, §4's uncursored start, §5's single advance **attempt** — one
> `record_observed` call per pass that read a non-empty page, at the highest ordinal in
> the page whose episode resolved, or at the page's highest where none did, and
> **never** computed from the page's length — **no** call at all on a pass that read no
> turns, and §6's failure disposition including its commit-ambiguous case. It
> owes the
> module docstring of `orchestration/observation.py` corrected, which today states
> "There is no durable cursor either".

> **Normative.** The `memory` half owes the column, the defensive read of §7, and
> the advance under the store's existing per-conversation exclusion. No file under
> `wire/` changes, and no file under `interfaces/` changes.

Tests the lane owes, named so they are written rather than assumed: a pass over a
conversation with no watermark reads its tail and records the tail's highest ordinal,
and the turns below that window stay below the watermark and are never selected again;
the next pass over the same conversation with no new turns reads no turns, calls no
model and records nothing; **a pass with no candidate at all, and a pass over an
explicitly named conversation with nothing above its watermark, each make no
`record_observed` call whatever** — asserted on the store, not only on the reported
result; a pass over a conversation whose page is entirely
unresolvable calls no observer and still advances to that page's highest ordinal **in
one pass**, not one turn at a time; a page whose *last* turn is unresolvable advances
to the highest ordinal below it, and the next pass over that turn alone advances past
it; **an episode that lands between those two passes is observed on the second**; a
page with an unresolvable turn in the **middle** advances to the page's highest
resolved ordinal and passes that turn over, pinned as §5's accepted residual rather
than as a defect, so a later lane changing it has to change this test deliberately; a
page of exactly `observation_batch_size` rows behaves the same as a shorter one, so no
rule depends on the page's length; **two overlapping passes that resolve the page
differently leave the higher position standing whichever order their stamps arrive
in**, written as an end-to-end test over two interleaved passes rather than as two
store calls in a row, with the duplicate proposals folding to `REINFORCE` and no
duplicate record; **a pass cancelled after its `record_observed` commits but before the
await returns leaves the stamped watermark and adds no compensating write**, injected
deterministically, **and the next pass over that conversation resumes above the
stamped position rather than re-reading the page**; a pass that raises inside the write
path after one proposal was ruled advances nothing and the next pass re-reads the whole
page; a second pass over the same page produces `REINFORCE` and no duplicate record,
pinned end to end and not only at the gate; `record_observed` never lowers a
watermark and returns `None` when asked to; `record_observed` refuses an ordinal
above the conversation's highest and stamps nothing; two concurrent `record_observed`
calls leave exactly one recorded value and it is the higher, pinned in the
`ConversationStore` conformance suite beside the store's other concurrent-mutation
rows; `record_observed` on a stamped conversation raises `UnknownConversationError`;
`turns_after` returns the lowest page rather than the tail, is ordinal ascending,
returns a short page at the end of a conversation, and refuses both out-of-range
arguments; `conversations_with_unobserved_turns` excludes a conversation whose every
turn is at or below its watermark, excludes a stamped conversation, includes one with
no watermark and at least one turn, excludes one with no turns at all, and returns
its rows `last_active_at` ascending with `id` ascending as the tie-break; a
conversation with more unobserved turns than one page **stays** in that set after a
pass and leaves it only once its watermark reaches its highest turn; **under a stopped
clock a candidate that keeps receiving turns stays first and an idle candidate is not
reached** — pinned as §3's accepted behaviour rather than as a defect, so that a later
lane changing the order has to change this test deliberately; a watermark that
is not an integer,
below `FIRST_TURN_ORDINAL`, or above the conversation's highest ordinal is read as
absent and no read of that conversation raises; **a conversation carrying such a
watermark is then recovered end to end** — it appears in
`conversations_with_unobserved_turns`, its next pass reads its tail and stamps a fresh
watermark — so that an implementation coercing the value on one read and filtering it
wrongly on another cannot leave the conversation permanently unreachable; a store whose watermark column is
missing entirely opens, serves and starts; `export` carries a stamped conversation's
watermark in the document it produces; and — since there is no import path — a **store**
whose watermark names an ordinal its own turns do not reach reads as unstamped and is
re-observed at its tail, exercised by writing the row rather than by restoring a
document.

### 9. What this ADR does not decide

- **The trigger, and the cadence.** #1737's ADR B — observe-on-quiet with the
  interval as a backstop — and it is the next lane, not this one. This ADR flips no
  default: `observation_interval` stays `None` and ADR-0083 §7's table still ships
  the job disabled. ADR-0111 §11 declined the same thing for the same reason
  ("Enabling any job the scheduler ships disabled […] This ADR decides the cursor;
  it does not land it and does not flip a default"), and the condition that fires it
  is the trigger ADR ratifying.
- **Anything about the observer's proposals.** What may be proposed, the utility
  bar, the prompt, the payload, the confidence function and the proposal bound are
  ADR-0077's, untouched. This ADR changes *which* episodes reach the producer and
  nothing about what it does with them.
- **The consolidation job's cadence and chunking.** ADR-0111 §4's, unchanged; that
  job's cursor is its own and this one is not shared with it, which ADR-0111 §1's
  "per walked order and per job" already requires.
- **A selector for episodes belonging to no conversation.** ADR-0077 §8 forecasts it
  — "a sensor's episodes belong to no conversation, and reaching them needs a second
  selection rule in the stage, not a different `Observer`" — and this ADR decides the
  conversation-scoped selector only. The condition that fires it is the first
  producer of episodes that no `ConversationTurn` names.
- **A re-observation that deliberately ignores the watermark.** §3 makes a repeat
  pass a no-op, and that is the intended behaviour. If a user-facing need for
  "observe this conversation again from scratch" appears, it is a new operation or a
  new argument with its own decision about what it costs — never a change to what
  the watermark means, and never a caller resetting one. Tracked as **#1789** rather
  than pre-empted here; the condition that fires it is such a need being reported.
- **A durable record that a turn's episode landed.** §5's residual exists because the
  index is an intent log and an unresolved turn is indistinguishable from an in-flight
  one. A member on `ConversationTurn` stamped after `write_atomic` commits would close
  it outright, in exactly `ConversationTurn.delivery`'s shape (ADR-0205 §3). It is not
  bought here: it is a second store-written member and a second write on the capture
  path — which is the latency a turn *is* waiting on — for a residual §5 bounds to a
  page boundary and a conversation's opening pass. The condition that fires it is
  evidence from a deployment that turns are being missed, or a second reader of the
  index needing the same fact for its own reason.
- **What a run tells a user about its progress.** `ObservationReport` gains nothing
  here, and ADR-0111 §11 leaves the same question where it was: "**Progress
  reporting to a user.** What a run *tells* somebody is the report surface #494 and
  #659 hold open".
- **Whether the retention horizon should stretch so that fewer episodes expire
  unobserved.** ADR-0074 §7 declines it — "this ADR does not stretch the horizon to
  prevent it. The remedy is leg 5's schedule; the setting is the user's" — and this
  ADR is that schedule's precondition, not a change to the horizon.
- **What a belief whose citations have expired renders.** ADR-0074 §7 gates that on
  its own lane and this ADR does not reach it.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is applied below to a **named clause** of each earlier ADR, in
that section's own currency: "Would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?"

> **Normative.** **(a) This ADR partially supersedes ADR-0077**, in ADR-0070 §3's
> sense, in exactly two scopes and no others.
>
> **§8's selection sentence.** "The operation takes an optional conversation id: it
> observes **that conversation's most recent `observation_batch_size` turns**, or,
> given none, the same window over the **most recently active** conversation" is
> replaced by §3 and §4 of this ADR. A reader implementing that sentence today
> reads the tail of the most recently active conversation; after this ADR they read
> the lowest page above the watermark of the first candidate by activity ascending.
> Everything else in §8 binds unchanged and is relied on here: the bound's value and
> its maximum-not-quota reading, the skip-without-backfill rule, "This does not make
> the producer conversation-shaped", the four reasons the trigger is explicit, and
> the fold that makes repetition safe.
>
> **§8's "there is no durable cursor" sentence.** "**There is no durable cursor, and
> re-observation is safe by construction.**" — the first half is replaced: a durable
> per-conversation position now exists. "re-observation is safe by construction" is
> **kept and relied on**, and §6 of this ADR quotes the argument behind it rather than
> weakening it. §8's forecast that closing its two named gaps "means knowing what
> has already been observed, which is the cursor below, which is leg 5's" is
> discharged rather than replaced, and so is §11's deferral of "the durable cursor
> that stops it re-reading what it has seen (§8)".
>
> **§8's next sentence is narrowed, not replaced, and §1 is the reason.** "No state
> records which episodes have been observed" stays **true as written**: §1 rules the
> watermark a position in the walk and not a certificate of coverage, nothing this ADR
> adds is per-episode or per-turn, and §1 names the two cases in which a turn below a
> watermark was never read. What becomes over-wide is the further reading that nothing
> durable records observation *progress* — the reading a selector that re-reads the
> tail is built from, and the one §3 replaces. So the sentence is kept with that
> reading narrowed, the `Status` pair's scope names the cursor sentence rather than
> both, and the note on ADR-0077 records the narrowing beside the replacement.

> **Normative.** **(b) This ADR partially supersedes ADR-0074**, in the same sense,
> in exactly two scopes.
>
> **§9's enumeration of what `Conversation` carries and what `ConversationStore`
> owes.** The conversation gains `observed_through` and the store gains
> `turns_after`, `conversations_with_unobserved_turns` and `record_observed`.
> This is the same move ADR-0205 §10 made on the same enumeration for
> `ConversationTurn.delivery` and `record_delivery`, and §9's illustrative signature
> is illustrative by its own words.
>
> **§9's rule that every conversation read is ordered by last activity descending.**
> Its item 3 reads "**Every read** is bounded by default and totally ordered […]
> conversations by last activity **descending** with the id as tie-break", and §3 of
> this ADR orders `conversations_with_unobserved_turns` **ascending**. A conforming
> store cannot satisfy both, so the rule is replaced **for that one operation** and
> for no other: `recent` keeps its descending order and its reason, the bounded-default
> half of item 3 binds unchanged and is honoured (a default of 50, refusals rather than
> clamping), and the totality half binds unchanged — the new order is total, with `id`
> ascending as the tie-break, for exactly the reason item 3 gives. §3 of this ADR
> argues why the direction inverts: descending would re-select the busiest conversation
> on every pass and never reach an idle one, which is ADR-0077 §8's first named gap
> arriving through the cursor.
>
> Nothing else in §9 or in ADR-0074 changes — §7's
> horizon, §8's deletion protocol and its tombstone, §9's two sweeps and its
> exclusion set, and §10's refusal to duplicate the membership relation onto the
> record all bind exactly as they did.

> **Normative.** **(c) This ADR partially supersedes ADR-0111**, in the same sense,
> in exactly two scopes, both of them one rule seen twice: **where a walk begins when
> it has no usable position**, and only as that reaches the observation cursor this ADR
> decides.
>
> **§2's absent-cursor clause.** "A cursor absent from the store means the walk has not
> started and the job begins at the first row of its order" is replaced for this cursor
> by §4: an absent watermark begins at the tail window. §2's second sentence ("A cursor
> is never initialised to a sentinel value") is kept and restated in §4.
>
> **§7's restart position.** "the walk restarts **from the beginning of its order**",
> in both of §7's clauses — the unreadable or unsupported cursor, and the cursor that
> disagrees with the store's contents — is replaced for this cursor by §7 of this ADR
> read with §4: a discarded watermark is treated as absent, so the restart lands at the
> tail. The consequence is stated rather than implied: ADR-0111 §7 prices a discard as
> "a repeated walk" and here it is a skipped prefix, which §4 states at its true size.
> **§7's disposition is kept whole** — discard rather than fault, never
> `IncompatibleStateError`, never a refusal to start, never advanced past a value that
> could not be read — and §7 of this ADR applies it word for word.
>
> Every other clause of ADR-0111 binds this cursor unchanged — §1's placement
> and per-order-per-job rule, §2's totality and its excluded shapes, §3's ordering and
> at-least-once guarantee, §4's run and chunk bounds, §5's halt, §6's absence of
> backoff, and §8's serial loop — and §11's deferral
> of the observation selector is discharged rather than replaced. This record is made
> under the fail-closed reading: on the narrower reading of §11, which names totality
> as what binds this choice, §2's absent-cursor clause never reached this cursor and
> no record would be owed. Declaring it is the direction that cannot leave a reader
> of ADR-0111 acting on a clause this ADR contradicts.

> **Normative.** Everything else about this ADR is a **stacked addition** under
> ADR-0082 §1: one member on one `core` type, three operations on one non-promoted
> Protocol, and no other ratified clause read differently after it. In particular
> ADR-0083 §6, ADR-0083 §7 and ADR-0083 §13 are untouched — §6's test is applied in
> §7 and comes out as ADR-0111 §7 already ruled it does for a cursor, §7's table and
> its disabled default are unchanged, and §13's deferral is discharged, which is
> what a deferral is for.

**The three reciprocal records are made in this change, and this is where they are
stated.** ADR-0070 §1 lists "recording a supersession that has landed" among the
permitted in-place header edits and notes that "ADR-0001 already requires this";
ADR-0082 §7 settles that "§1's condition is that the superseding ADR **exists**, not
that it is ratified"; and the corpus practice is to make both records in one change
(ADR-0205 §10: "**Both records are made in this change**"). So the record is owed on
the day this ADR exists, and an earlier draft of this ADR that deferred all three to
issue **#1788** was wrong on the ADRs — architecture review said so in seven
consecutive rounds, and #1788 is closed by this change rather than outliving it.
ADR-0136 §7 is the precedent for the placement and is on point: "a merged ADR-0136
sitting beside an unrecorded ADR-0015 is the window ADR-0082 exists to close."

Each record is a `Status`-line pair **accumulated** under ADR-0070 §4 without dropping
the pairs already on the line — "it does **not** drop the first: replacing the whole
value would lose the earlier dead scope" — plus the appended dated note ADR-0070 §1
requires in every case. Under ADR-0082 §2 no amendment qualifier goes on a
leading-token line, and all three lines carry the leading `Partially superseded by`
token, so on ADR-0074, ADR-0077 and ADR-0111 alike the note is the whole of the record
beyond the pair. **No ratified text of any of the three is rewritten**: the edit is the
one `Status` line and one appended note in the header block, which is the whole of what
ADR-0070 §1 permits in place. **A concurrent lane accumulating its own pair on one of
these lines resolves the collision by keeping both pairs**, which is what ADR-0070 §4
already directs and is a rebase conflict rather than a decision. The pairs are:

- on ADR-0074: `and ADR-0212 (§9's enumeration of what Conversation carries and what
  ConversationStore owes, and its rule that every conversation read is ordered by last
  activity descending)`;
- on ADR-0077: `and ADR-0212 (§8's selection sentence and its durable-cursor
  sentence)`;
- on ADR-0111: `and ADR-0212 (§2's absent-cursor clause and §7's restart position,
  only as they reach the observation cursor)`.

No scope parenthesis carries an `ADR-NNNN` token, which is ADR-0070 §4's authoring
constraint, and each pair as landed reads exactly as it is stated above.

## Consequences

**Easier.**

- **The timer becomes safe to set, which is the whole point of landing this first.**
  Once this ADR is implemented, a tick with nothing above any watermark reads a
  bounded listing, calls no model and writes nothing, so the cost of enabling
  `observation_interval` becomes proportional to new material rather than to the
  tick rate. The interval is still `None` by default and flipping it is the trigger
  ADR's act (§9), but the reason `core/config.py` gives for holding it off — "buys
  repeated cost and no new coverage" — stops being true.
- **Both of ADR-0077 §8's named coverage gaps close for everything recorded above a
  conversation's first watermark, under the fairness §3 states and no more widely.** A conversation
  the user never names becomes reachable, because candidacy is not restricted to the
  most recently active one; and turns older than the tail become reachable, because
  the walk moves forward instead of re-reading the tail. Two qualifications are part
  of the claim rather than footnotes to it: the second gap closes for every turn
  recorded **above a conversation's first watermark**, and not for the turns below it
  — §4 starts an absent watermark at the tail, so every turn below that first window is
  passed over permanently, however long the prefix is, for a conversation that existed
  before the cursor and equally for one that accumulated a backlog before its first
  pass reached it, and a §7 discard makes a conversation a first-pass one again (§4
  states the cost at its true size and names what would buy it back); and "reachable"
  becomes "reached in a bounded number of passes" only where the clock advances
  monotonically, since §3 accepts that a stopped or stepped-back clock can leave one
  candidate served ahead of another indefinitely. Under that clock a conversation can
  still expire unobserved — the coverage this closes is real but conditional, and the
  condition is named where the order is chosen rather than assumed away here.
- **#785 and #632 are answered rather than restated.** #785's three questions have
  the answers in §2 and §3; #632's deferral has an ADR.
- **The selector becomes testable at the seam.** Candidacy, the candidate order and
  the forward page are three store operations with stated total orders and stated
  refusals, so the conformance suite can pin them for every implementation rather
  than each consumer asserting on a private mock.

**Harder, and named.**

- **The conversation index gains a column and the Protocol gains three members.**
  That is the cost of a cursor being durable state, and ADR-0083 §13 predicted it
  ("it is **new durable state**"). The upgrade discipline is §7 and it is the cheap
  direction: an ignored watermark costs the coverage the system has today, and a
  discarded one costs a tail read.
- **A repeat `assistant observe` on one conversation now does nothing**, where today
  it re-derives. That is the intended meaning of "what has already been looked at",
  and §9 names what a deliberate re-observation would take.
- **No page is ever read twice for a gap, and the price of that is one turn.** §5
  advances to the highest turn the pass handed over, so a settled gap costs nothing and
  repeats nothing; what it costs instead is the in-flight turn that sits *below* a
  turn whose episode has already committed, which takes two overlapping captures of one
  conversation. §5 states that residual and the tail case beside it rather than leaving
  either to be discovered. The loss is a distillation, not an episode: the turn's
  content stays readable by retrieval until its own horizon. Closing it entirely would
  take a durable "the episode landed" fact on the turn — a second store-written member
  and a second write on every capture — which §9 names rather than buys.
- **A pass cancelled at its advance attempt leaves an ambiguous watermark**, and §6
  rules both outcomes safe rather than adding machinery that cannot tell them apart.
  Either the position records work that was done, or the page is re-read and folds.

**What would trigger revisiting this.**

- **A producer of episodes that no `ConversationTurn` names.** The per-conversation
  watermark has nothing to be a position in for such an episode, and ADR-0077 §8
  already says reaching them "needs a second selection rule in the stage".
- **A candidate order that starves in practice.** §3's ascending order starves
  nothing under a monotonic clock and names the case a non-monotonic one admits. Two
  things would make it worth revisiting: a deployment whose clock adjustments are
  frequent enough that the named case is observed, or a pass rate so far below the
  rate at which conversations become candidates that the *newest* material waits
  longest. Either is an argument about the order, and the watermark is unaffected by
  both.
- **A second job walking the same index.** ADR-0111 §1's "per walked order and per
  job" would then require a second position, and `observed_through` is named for its
  one consumer rather than as a general "progress" field.

## Alternatives considered

**A `meta` row per conversation in the memory store, keyed by conversation id.**
ADR-0111 §1 notes that `memory/sqlite_store.py` "already carries the shape — a
`meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` table". Rejected: it puts the
position in a store that did not allocate the ordinal, so the write cannot be
atomic with anything the position describes, and ADR-0078 §1's argument against
mixing bookkeeping into the belief store applies to a `meta` row as much as to a
record. It would also give one job two positions in two stores for one walk.

**A cursor over a single insertion order spanning all conversations.** Rejected in
§2: the contract maintains no such total order, `occurred_at` is a caller-supplied
instant that ADR-0111 §2 excludes by name, and a backend's `rowid` is one
implementation's order rather than the contract's.

**A set of observed episode ids.** ADR-0111 §2's first excluded shape, quoted in §1.

**An `observed_at` stamp on `ConversationTurn`, following ADR-0205 §3's precedent
exactly.** Rejected in §1: the fact is about a conversation, not a turn; it would
grow with the log for a question one integer answers; and it would cost a write per
turn rather than one per pass. What ADR-0205 §3 supplies is the precedent that the
index may carry a fact written after the row it is about — which this decision uses
one level up.

**Walking an uncursored conversation from `FIRST_TURN_ORDINAL`, honouring ADR-0111
§2 with no supersession.** Rejected in §4 on three grounds, of which the first is
#1737's own: it re-pays model calls for turns a hand-run `observe` already read,
reaches only material ADR-0077 §8 has already written off, and makes the first
enabled tick's cost a function of expired history. The cheaper honouring — declaring
the departure — is what §10(c) does.

**Advancing the watermark to the last turn *handed over*, as #1737 item 3 words it.**
Rejected in §5: a page that resolves to nothing hands nothing over, so a conversation
whose unobserved turns have all expired would re-read one dead page forever — ADR-0111
§7's "permanently and quietly stopped". What item 3 is actually protecting against —
advancing on the strength of a proposal — is ratified in §5's first clause, which
advances even when nothing was proposed.

**Advancing through the turns whose proposals were ruled, as #1737 item 4 words it.**
Rejected in §6: a proposal may cite several turns and a turn may be cited by none, so
that set does not name a position in the ordinal order, and ADR-0111 §2 requires a
cursor to be a position. ADR-0111 §5's halt gives the same safety with a position that
keeps its meaning.

**One pass covering several conversations, or one observer batch mixing them.**
Rejected in §3: permitted by ADR-0077 §1's source-agnostic batch, but it makes one
prompt two transcripts and makes `observation_batch_size` mean two things. A run that
wants several conversations performs several passes, which is ADR-0111 §4's chunk
model unchanged.

**Keeping "the most recently active conversation" as the target and only walking it
forward.** This would need no candidate read and no new listing, and would leave
ADR-0077 §8's selection sentence half-standing. Rejected: it leaves §8's *first*
named gap open — "a conversation the user never observes" — which #1737's item 3
directs closed, and it makes coverage a function of which conversation the user
happens to be using.

**Surfacing the watermark to the user, on `ConversationSummary` or in
`ObservationReport`.** Rejected in §8: it is bookkeeping, a listing that showed it
would invite it being read as a belief-layer fact, and it would move
`PROTOCOL_VERSION` for a field nobody has asked for. What a run tells a user is
#494's and #659's open ground (ADR-0111 §11).
