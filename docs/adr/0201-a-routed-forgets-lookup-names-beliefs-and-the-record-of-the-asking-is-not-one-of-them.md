# 201. A routed forget's lookup names beliefs, and the record of the asking is not one of them

- Status: Accepted
- Date: 2026-08-27
- **Partially supersedes:**
  [ADR-0197](0197-an-ask-reaches-the-hubs-own-operations-through-a-routing-stage-and-a-routed-operation-is-never-re-read.md)
  — §5's first clause, that a routed operation's argument "is resolved from that
  query by deterministic local code reading the store the operation itself
  reads", **scoped to exactly one case**: the kinds a routed `forget`'s lookup
  enumerates. There the lookup reads the store `forget` reads with `EPISODIC`
  excluded rather than reading it whole. Everything else §5 decided — that the
  resolution is a lookup and never a generation, that every candidate is a record
  that exists, the display-subject/scalar-argument split, the three arms
  (`NOT_FOUND`, `AMBIGUOUS`, `AMBIGUOUS_TRUNCATED`), the refusal to choose among
  candidates by rank, recency, score, best match or a second model call, the
  bound and its disclosure — is untouched and binds this lookup exactly as it
  bound the last one. §9 below classifies this and the four ADRs against which no
  record is owed.
- **This is not a contract change.** It adds no `core` name, moves no method
  signature and moves no promoted method's contract. What moves is one argument
  of one private read inside `ai_assistant.orchestration`, and one sentence of an
  ADR. It is still decided in its own PR and ratified before anything implements
  against it, because that is the sequence an ADR takes (ADR-0015 §5); it owes
  the adversarial lens alone, on `CONTRIBUTING.md` → "Stop when the required
  reviews are green".

## Context

### Where this comes from

Issue #1637 was opened by the lane that built ADR-0197's routing stage (PR
#1634), as a thing that decision left open rather than a defect in the build. It
has since collected three records, and each one made it larger:

1. **The opening record.** A routed `forget` resolves its argument over
   `MemoryStore.list_beliefs` unfiltered by kind, and ADR-0074 §3 captures every
   exchange as an `EpisodicMemory` whose `content` quotes the user's own
   utterance. So the record of *asking* to forget something matches the query
   that asked for it, and a second ask reaches `RouteOutcome.AMBIGUOUS` over the
   belief and the episode of the first ask.
2. **Adversarial review round 7 on PR #1634**, a `major` on the same behaviour,
   adding that the suite does not exercise it: `tests/orchestration/
   test_engine_routing.py` routes on the query `jazz` while its utterance is
   `please forget that preference`, so no test in the repository drives the shape
   a user actually types. The verdict was `APPROVE WITH NITS`, so the loop closed
   with this outstanding rather than blocked on it.
3. **The milestone-26 QA run (#1646)**, which reproduced it three times — twice
   on a scratch hub through the CLI, once on the deployed hub through the browser
   — and then **re-verified it at `226c3f0b`, after PR #1652**. That is the record
   that changes the decision, and it is set out below.

### What the tree does today, read rather than assumed

`Engine._routed_beliefs` is the read behind the lookup. It is not the promoted
`AssistantEngine.beliefs`, which answers `BeliefSummary` rows; it is a private
member reached through the `RoutedOperations` adapter object, answering the
`Belief` records ADR-0197 §8 gives the `forget` arm. Its body is one call:

```python
records = await self._memory.list_beliefs(bands=None, kinds=None, limit=limit, offset=offset)
return tuple([await self._project(record) for record in records])
```

`kinds=None` is ADR-0073 §1's "every value", so every captured turn in the store
is a candidate, and `orchestration.routing._paged` walks that listing page by page
until it has one more than `DEFAULT_PAGE_SIZE` matches or the store runs out.

### The loop, and why rephrasing does not exit it

PR #1652 replaced whole-query substring containment with a term-wise match, to fix
#1647 — a routed `forget` reaching `NOT_FOUND` on a belief that plainly existed,
because the router copies the sentence's connective out with the user's words and
`that I drive a green estate car` was never a contiguous substring of `I drive a
green estate car`. That fix is correct and this decision does not disturb it. It
also widened what the episode of the ask matches, because **the episode's content
is the user's own sentence**: every word a user can use to name the belief is a
word the episode already carries.

The re-verification at `226c3f0b`, over one planted belief `I drive a green estate
car`, is the whole argument in six lines:

```text
> forget that I drive a green estate car
   -> AMBIGUOUS over 2:  the belief, and conv:8d842f58-…:1 "The user asked: forget that I drive a green estate car"
> forget my green estate car          # the rephrase the AMBIGUOUS rendering invites
   -> AMBIGUOUS over 3:  the belief, conv:8d842f58-…:1, and conv:91ed04dc-…:3
```

Three things follow, and the third is the one that decides this ADR.

- **The user's escape is the thing that closes it.** ADR-0197 §5 ends the route on
  ambiguity and the rendering invites the user to say which one they meant; saying
  it again captures another episode, so the candidate set grows by one on every
  attempt. Asking again is precisely what the user is told to do.
- **It compounds with #1647's class.** A phrasing whose query misses the real
  belief still captures an episode containing that query, so the *next* attempt
  with the same phrasing reaches `AMBIGUOUS` rather than `NOT_FOUND`, over a
  listing in which the only thing matching the user's words is the record of them
  having said them.
- **The two candidates in the second pass sit in two different conversations.**
  `conv:8d842f58-…` and `conv:91ed04dc-…` are distinct ids. Any wording that names
  the belief is a subset of the sentence *every* earlier ask quoted, so this is
  structural rather than incidental: the loop is not confined to the conversation
  the ask is part of.

Nothing is destroyed on any of these passes — `AMBIGUOUS` performs nothing,
confirms nothing and writes no row (ADR-0197 §5, §9) — so the failure is a closed
door rather than a lost record. What it costs is the routed door for that subject,
permanently, while the typed door goes on working: the asymmetry milestone 26
existed to close.

### What the corpus already decides, read as evidence

Three things are already ratified, and together they leave this decision much
smaller than it first looks.

**An episode is not a belief, and the surface answering "what do you believe about
me" already says so.** ADR-0074 §6: "**The belief listing excludes `EPISODIC` by
default.** `assistant beliefs` answers 'what do you believe about me', and an
episode is not a belief — it is the evidence a belief is made of. Left kind-blind,
the surface leg 1 built to be readable would print a transcript." The tree carries
that as `interfaces.cli._DEFAULT_BELIEF_KINDS`, derived from `MemoryKind` rather
than spelled out "so a fifth `MemoryKind` is listed by default rather than
silently omitted by a list nobody updated". A routed `forget`'s query is the user
naming a belief in their own words; the enumeration behind the question that
phrase belongs to already excludes episodes.

**The lookup was never "everything `forget` can destroy", and nobody has called
that a divergence.** `Engine.forget` relays `MemoryStore.delete` "and nothing
more", and `delete` removes a record by id whatever it is. `list_beliefs` reads
strictly less: live beliefs only, because "a retired record is not a belief the
assistant holds but a record of one it used to" (ADR-0073 §3, and `list_beliefs`'
own contract), and never an expired record or one not live at now (ADR-0007,
ADR-0045 §6). So the typed door already destroys records the routed lookup can
never name, on two axes, by ratified decision. The question this ADR settles is
not whether the lookup may read less than `forget` destroys — it always has — but
where that line falls.

**The kind axis is the store contract's own filter.** `list_beliefs` takes
`kinds`, applies it *before* the page cut (ADR-0073 §2: "every predicate this read
applies belongs before the cut"), and ADR-0073 §1's "`None` means every value" is
a statement about what the *store* does with an absent argument, not an obligation
on a caller to omit it. Excluding a kind here needs no contract change, no new
axis and no new method.

### What #1637 opened with, and why it no longer holds

The issue's own question was narrower: whether the lookup should exclude "the
conversation record the ask is *part of*", which "removes the surprise without
making the two doors differ about what exists". At the time that was the right
shape to propose. The re-verification refutes it — the second pass matched an
episode from an earlier conversation as well as one from the current one — and the
refutation is structural, not a matter of degree: a user who asks about the same
subject next week is asking in words the episodes of every previous week already
quote. A same-conversation exclusion would make the first repeat work and leave
every subsequent one broken, which is the worse of the two failures because it
looks fixed.

## Decision

### 1. A routed `forget`'s lookup enumerates the belief kinds, and `EPISODIC` is not one of them

> **Normative.** A routed `forget`'s lookup (ADR-0197 §5) enumerates live beliefs
> of every `MemoryKind` **except** `EPISODIC`. An episodic record is never a
> candidate of that lookup, never its display subject, never the record whose
> identity becomes the façade call's argument, and never an entry in an
> `AMBIGUOUS` or `AMBIGUOUS_TRUNCATED` listing.

> **Normative.** The selected set is **derived from `MemoryKind`** — every member
> that is not `EPISODIC` — and never written out as a list of the kinds that exist
> today. A `MemoryKind` added later is therefore a candidate by default rather
> than silently omitted by a list nobody updated. This is
> `interfaces.cli._DEFAULT_BELIEF_KINDS`' own rule and its own reason (ADR-0074
> §6), applied one seam over.

The exclusion is by **kind**, not by conversation, not by provenance band and not
by "the episode this ask produced". Kind is the axis the store already filters on,
the axis ADR-0074 §6 already ruled on for the surface answering the same question
in words, and the only one of the three that closes the loop the re-verification
found rather than closing its first turn.

### 2. This is a rule of query resolution, and it changes nothing about what `forget` destroys

> **Normative.** Nothing in §1 changes what `AssistantEngine.forget` destroys.
> `forget` still relays `MemoryStore.delete` and destroys any record its
> `record_id` names, an episodic record included; no store gains a
> kind-conditional refusal; ADR-0074 §8's rule that "the store deletes what it is
> told to delete" and ADR-0004 §6's unconditional deletion right are untouched;
> and the routed and typed doors go on agreeing, record for record, about what
> `forget <id>` does.

> **Normative.** ADR-0197 §2's third clause is satisfied unchanged. The exclusion
> sits **upstream of the façade call**, in the resolution step the typed door does
> not have because it is handed an id. The stage still performs the operation by
> calling the engine's own implementation, there is still exactly one
> `MemoryStore.delete` call site, and it still stands behind one set of
> preconditions.

This is the clause the decision turns on, so it is worth stating why the objection
it answers does not survive. §2's third clause exists so that "two doors to one
operation" do not "stop behaving the same way", and its worked case is a stage
that *reimplements* an operation rather than calling it. A routed lookup that
names fewer records is not a second implementation of `forget`; it is a different
way of **saying which record**, and the typed door has no counterpart to it at
all. The two doors already differ in exactly this way and have since ADR-0073 §3:
a retired record is unreachable by phrase and destroyable by id. What §2 forbids
is the two doors disagreeing about what happens once the record is named, and after
this decision they do not.

### 3. Where the exclusion is applied

> **Normative.** The exclusion is expressed as the `kinds` argument of the
> `MemoryStore.list_beliefs` read behind the lookup, so it is applied by the store
> before the page cut (ADR-0073 §2). An excluded record is not read into
> `orchestration`, is not projected into a `Belief`, and is not discarded after a
> page has come back.

Two reasons, and the second is the operational one.

- **Projection is not free.** `Engine._routed_beliefs` projects every record on
  every page through `Engine._project`, which resolves that record's citations
  through one `MemoryStore.get_many` (ADR-0086 §6). Filtering after the read would
  pay that read for every captured turn in the store and then throw the result
  away.
- **The walk's cost should be the belief count, not the transcript count.**
  `routing._paged` pages until it has one more than `DEFAULT_PAGE_SIZE` matches or
  a short page ends it, so a routed `forget` that resolves to one candidate walks
  the *whole* filtered listing. Episodes are the bulk of a used store — ADR-0074
  §6's own framing is "tens of records per day" — so an unfiltered walk makes the
  cost of every routed `forget` a function of how long the user has been talking
  to the assistant. With the filter it is a function of how much the assistant
  believes.

### 4. The scope: `forget`'s lookup, and nothing else

> **Normative.** This decision reaches the lookup for `forget` and nothing else.
> `revoke` and `forget_question` resolve over `standing_grants` and `questions`,
> neither of which holds a memory record, and neither is changed. No read-only
> operation of ADR-0197 §3 is touched. §4's envelope, §6's two composing inputs,
> §7's confirmation card and token, §9's trail row, and §10's rendering,
> composition, failure and capture clauses are all unchanged, and so are the
> `AMBIGUOUS`/`AMBIGUOUS_TRUNCATED` split, its `DEFAULT_PAGE_SIZE` bound and its
> never-truncated-silently rule.

> **Normative.** The capture of a routed pass is unchanged. ADR-0074 §3 still
> writes one episode per routed exchange and ADR-0197 §10 still requires the
> user's utterance to reach it and still forbids any part of the routed account
> from joining it. This decision changes what the *next* lookup reads, never what
> capture writes.

### 5. A query naming only episodes reaches `NOT_FOUND`, and nothing new is invented for it

> **Normative.** A routed `forget` whose query names only episodic records
> resolves to **no** candidate, and the route ends in `RouteOutcome.NOT_FOUND` —
> ADR-0197 §5's existing arm, applied to a lookup that now finds nothing. No
> member is added to `RouteOutcome` and the composing stage's two inputs
> (ADR-0197 §6) gain nothing.

> **Normative.** No surface distinguishes "your words matched nothing" from "your
> words matched only the record of you saying them". Neither the routed account an
> adapter renders (ADR-0197 §10) nor the composed reply carries a signal that the
> excluded kind was reached, and no later ADR adds one without deciding ADR-0197
> §6's second clause afresh.

The last clause is a refusal, and it is deliberate. Telling the user which of the
two happened would take either a third value on the outcome enum or a count of
their own records reaching a prompt, and ADR-0197 §6's second clause is exactly
what forbids the second. It would also be telling them about a record the routed
door has just decided not to offer them, which is a strange thing to volunteer.

**What a user who genuinely means an episode does instead** is unchanged and is
two typed doors, neither of which this decision touches: `assistant
forget-conversation <id>` destroys a conversation's episodes and its index
(ADR-0074 §8), and `assistant beliefs --kind episodic` lists episodes with the ids
`assistant forget <id>` takes. Neither is a capability routing had and lost:
`forget_conversation` is not in ADR-0197 §3's vocabulary, and a routed `forget`
naming one specific captured turn out of a transcript by phrase is not a thing a
user was doing.

### 6. The representative-input test this decision owes

> **Normative.** The implementing lane pins the representative input, and a suite
> that does not carry it does not exercise this decision. Two routed `forget` asks
> whose **utterance contains the query**, with the first ask's exchange captured
> before the second is routed, over a store holding one matching belief. The
> second ask resolves to that one belief and reaches the confirmation, not
> `RouteOutcome.AMBIGUOUS`.

> **Normative.** The same shape is pinned a second time with the two asks in
> **different conversations**, the earlier conversation's episode still in the
> store. This is the arm the narrower alternative would have left open, and it is
> the arm the milestone-26 re-verification actually observed, so it is pinned
> separately rather than assumed to follow.

> **Normative.** A third case pins §2 against the change: an episodic record whose
> id is passed to the typed `forget` is still destroyed. §1 must not be
> implementable by a store-side or façade-side refusal, and this is what makes
> that mechanical rather than argued.

The existing `_UTTERANCE` / `_QUERY` pair in `tests/orchestration/
test_engine_routing.py` is the shape that hides this: the utterance `please forget
that preference` deliberately shares no word with the query `jazz`, which is
sensible for the tests it was written for — they are asserting that no part of the
routed account reaches a prompt — and is precisely why the interaction has been
described in prose for three records and pinned nowhere. New constants, not a
change to those: the existing pair is load-bearing for what it was written for.

### 7. What this ADR does not decide

> **Normative.** Beyond §§1–6 and §9, this ADR decides nothing. It adds no `core`
> name, no Protocol member, no `RouteOutcome` member and no `Settings` field; it
> moves no method signature and no promoted method's contract; and it changes no
> ADR other than the one clause of ADR-0197 §5 named in the header.

- **Whether the routed operation joins the captured episode** (#1314), which
  ADR-0197 §11 files to `track:memory` and which this decision leaves exactly
  where it found it. It is the other direction of this seam — the routed account
  feeding the capture, rather than the capture feeding the next lookup — and §1
  above is deliberately silent on it. Closing this one does not close that one,
  and a later decision there does not reopen this.
- **Whether a `forget` through the typed door is recorded** (ADR-0197 §11).
  Untouched, and on the same `track:memory` ground.
- **Whether `forget_conversation` becomes routable.** ADR-0197 §3's widening rule
  and its five conditions are how it would arrive, and nothing here starts that.
- **Whether retrieval, `beliefs`, `search`, `export` or any other reading surface
  changes.** None of them does. ADR-0074 §6 already settled retrieval and the
  belief listing, and this decision is the third application of its reasoning
  rather than a revision of it.
- **Whether an episode should be capturable in a form the next lookup cannot
  match** — a capture that stored the utterance somewhere other than `content`, or
  a store-side "not retrievable by phrase" flag. That is a change to ADR-0074 §3's
  shape, it would reach every consumer of `content` including the observer's
  citations, and it is not needed: the loop closes at the reading end.
- **Episode retention.** ADR-0074 §7's horizon is untouched, and this decision
  does not lean on it. A finite horizon would eventually drain the candidate set
  by itself, which is not a fix — the loop is at its worst in the minutes after
  the first ask.

### 8. What the implementing lane owes

The implementation is one lane in `orchestration`, briefed after this ADR merges
(ADR-0015 §5, golden rule 5). It owes:

1. **The change itself**: the `kinds` argument of `Engine._routed_beliefs`' read,
   derived from `MemoryKind` per §1, with the derivation sited where a reader of
   the routing stage will find it.
2. **The docstrings that now read more widely than they hold.**
   `Engine._routed_beliefs` says it "reads the store `forget` itself reads
   (ADR-0197 §5)"; `orchestration.routing.RoutedOperations` says §5's lookup "has
   to read the store that operation reads"; `routing.resolve` says its candidates
   are "read from the store the operation itself reads". Each is re-pointed at
   this ADR, not deleted — the sentence is still true of the store, and what
   changes is the kinds.
3. **The three tests of §6.**
4. **This ADR's ADR-0082 §1 record on ADR-0197**, which is the item below.
5. **Closing #1637**, whose three records are what this decision answers.

**The record on ADR-0197 is a specified operation, not an append, and it is
specified here so the lane applying it cannot get it wrong.** ADR-0197's `Status`
reads `Accepted, §7 amended by ADR-0198` — a plain `Accepted` line carrying an
amendment qualifier and no leading token. Recording this partial supersession
makes it a **leading-token** line, and ADR-0082 §2's fourth paragraph then governs
what happens to the qualifier already on it.

> **Normative.** The record owed on ADR-0197 is one change making three edits
> together: the `Status` line takes the leading `Partially superseded by ADR-0201
> (<scope>)` form (ADR-0070 §4, `docs/adr/template.md`), the existing `§7 amended
> by ADR-0198` qualifier **moves off that line into the dated note** (ADR-0082
> §2), and an appended dated note records this supersession (ADR-0070 §1). The
> scope parenthesis names §5's first clause as the header of this ADR names it.
> Applying any one of the three without the others is not a partial record: it
> either leaves ADR-0070 §4's extraction invariant reading `ADR-0198` as a
> supersession target, or drops a ratified record off the corpus.

> **Normative.** That change is owed by the **first** change after this one to
> touch ADR-0197, and the implementing lane of §§1–6 is that change unless a
> nearer one arrives. It is not conditional on the implementation landing: it
> records a decision, and the decision is ratified when this ADR merges.

**Why it is not made in this ADR's own PR, stated rather than assumed.** ADR-0082
§1 decides **whether** a record is owed and §2 decides **where on the earlier ADR
it goes**; neither decides which *change* carries it, and §1 says in terms that
what the later ADR owes in its own text is naming the clause and applying the
test — "the judgement is made in the later ADR's text, which is where it is
reviewed". This ADR does that, in its header and in §9. The corpus's two most
recent worked cases both put the application in the implementation lane rather
than the ADR lane: ADR-0197's own four records on three ADRs (`91fd1dae`, in PR
#1634) and ADR-0198's three records on ADR-0042, ADR-0052 and ADR-0197
(`46ac2680`, in PR #1643, "apply ADR-0198's ADR-0082 §1 records to 0042, 0052 and
0197"). Nothing forbids the other order — ADR-0082 §7 is explicit that §1's
condition is that the superseding ADR **exists**, not that it is ratified, so the
record may be written beside a `Proposed` one — and a lane whose fence admits both
files may make it atomically. What is **not** permitted is the record never being
made, which is what the clause above closes.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0197 §5 — a record is owed, and it is a partial supersession.** Its first
clause rules that the argument "is resolved from that query by deterministic local
code reading the store the operation itself reads". A reader holding only ADR-0197
implements `forget`'s lookup over an unfiltered `list_beliefs` and gets the loop
above; after this decision they implement it over a kind-filtered one. That is a
reader acting **differently**, not a clause read too widely, which is ADR-0070
§1's line between an amendment and a supersession — so it is a supersession, and
partial supersession is the sanctioned form for replacing part of an earlier ADR
(ADR-0070 §3). It is **narrow**: the clause fails only for `forget`, and only on
the kind axis. Its "lookup, not a generation" half is not merely preserved but
strengthened — the candidates are a strict subset of the records that already
existed — and `revoke` and `forget_question` resolve exactly as §5 ruled.

**ADR-0197 §2 — no record is owed, and it is worth stating rather than omitting.**
Its third clause is where a reader will look for a record, because it is the clause
#1637 and PR #1634's reviewer both reasoned from. It rules that the stage "performs
the routed operation by calling the engine's own implementation", "does not reach
into a store the engine holds to perform an operation itself", and "composes no
operation out of two". Every sentence stays true word for word: the stage still
calls `AssistantEngine.forget`, there is still one `MemoryStore.delete` call site,
and nothing is composed. §2's clause governs **performing**; §1 above governs
**naming**, which is a different step and one §5 owns. Recorded here because a
reader checking §5's record will look for a companion on §2, and because ADR-0082
§1 forbids a record demanded on book-keeping grounds alone.

**ADR-0074 §6 — no record is owed.** Its two rulings are that retrieval passes a
`kinds` filter excluding `EPISODIC` and that the belief listing excludes it by
default. Both stay exactly as ruled; §1 above adds a third reader on the same axis
for the same reason, which is a stacked addition. Its closing sentence — "an
episode is a record with an id, so `assistant forget <id>` destroys one exactly as
it destroys a belief" — is one §2 above restates and obeys rather than narrows.

**ADR-0073 §1, §2 and §3 — no record is owed.** §1's `kinds` axis is used as
declared and "`None` means every value" describes what the store does with an
absent argument, not what a caller must pass. §2's before-the-cut rule is cited
and relied on by §3 above. §3's live-only rule is unchanged, and is quoted above as
the precedent that the lookup already reads less than `forget` destroys.

**ADR-0007 §1 and ADR-0004 §6 — no record is owed.** The `delete` contract and the
unconditional deletion right behind it are
untouched: no record becomes undeletable, no store gains a refusal, and the only
thing that changes is which records a *phrase* can name.

**Everything else is a stacked addition and no record is owed.** ADR-0197 §§1, 3,
4, 6, 7, 8, 9, 10 and 11 (§4 above asserts that none of them moves, which is a
claim about this decision's reach and not about them; §11's two `track:memory`
deferrals are named and left where they were). ADR-0086 §6 (its batch read is
cited as a cost, not changed). ADR-0045 §6 (quoted as existing read-time
behaviour). ADR-0015 §5 and ADR-0070 §§1, 3 and 4 (followed, in the forms they
prescribe).

**This ADR's own ratification.** Drafted, reviewed and revised as `Proposed`; the
status flipped only once the required review — adversarial, this deciding no
contract surface — returned clean on one tree, with `just adr-ratify` making the
flip and `CONTRIBUTING.md` → "Finishing an ADR PR" the sequence followed. Nothing
implements against §§1–6 until this has merged.

## Consequences

**The routed door stops closing behind the user.** A repeat ask about the same
subject reaches the same candidate it reached the first time, and the rendering's
own invitation — "say which one" — stops being the thing that makes the next
attempt worse. This is the asymmetry milestone 26 existed to close, and it is the
last observed instance of it.

**The routed lookup's cost stops tracking how much the user has talked.** §3 makes
the walk proportional to the belief count rather than to the transcript, and
removes one `get_many` per captured turn from a routed `forget` that resolves to
one candidate. Nothing measured this before the store filled; it would have been
measured eventually.

**One capability is withdrawn, and it is one nobody had usefully.** A routed
`forget` naming a single captured turn by phrase no longer resolves. In practice
it never did — the ask that named the episode captured another episode matching the
same phrase, so the second candidate arrived with the query — and both typed doors
for an episode are unchanged.

**A future `MemoryKind` is a candidate without anyone remembering to add it**, and
that is §1's derivation earning its keep. The failure it forecloses is the quiet
one: a fifth kind that a routed `forget` silently cannot name, discovered by a user
rather than by the gate.

**The two doors are now visibly asymmetric in a way that is written down.** They
were already asymmetric on two axes (retired, expired) and nothing said so in one
place. §2 says it, and a future decision that wants to close the gap — a routed
door onto history, say — has a clause to argue against rather than an absence.

**What would trigger revisiting this.** A routable operation whose lookup wants
episodes on purpose — cross-conversation episodic recall is a real capability
ADR-0074 §11 defers with its ranking question, and a routed door onto it would
need its own read rather than this one. Or a capture shape in which the utterance
is not the episode's `content`, which would remove the mechanism this decision
works around; §7 declines to require one, and does not forbid one arriving for its
own reasons.

## Alternatives considered

**Leave it, and let the user disambiguate.** ADR-0197 §5's own position, and
defensible when written: the failure is honest, performs nothing and shows the
candidates. The re-verification is what refutes it — the disambiguating sentence
is itself captured, and every wording that names the belief is a subset of the
sentence the episodes quote, so the set the user is choosing from grows with each
attempt. A failure mode the documented remedy makes worse is not one to leave.

**Exclude only the conversation the ask is part of.** #1637's opening proposal,
and the narrowest thing that removes the surprise. Refuted by observation rather
than by argument: the milestone-26 re-verification's second pass matched an
episode from an earlier conversation as well as one from the current one, and that
is structural — next week's ask is worded in words last week's episodes already
quote. This would make the first repeat work and leave the rest broken, which
reads as fixed and is not.

**Exclude only the episode this very ask produced.** Narrower still, and it fails
on the first pass in the QA record: the reproduction that started #1637 was a
*second* ask after the first card was abandoned, where the offending candidate is
the previous ask's episode and not this one's.

**Rank, and prefer the non-episodic candidate.** Directly forbidden by ADR-0197
§5 — "no clause of this ADR permits choosing among candidates by rank, recency,
score, best match, or a second model call" — and rightly: it turns a lookup into a
judgement about which of the user's records they meant, immediately before
destroying one. Excluding a kind before the lookup is not a rank; it decides what
the question ranges over, in the open, once.

**Make the router's query narrower**, so the copied connective does not reach the
match. This is #1647's territory and PR #1652 already ruled the other way, for the
right reason: the router is asked for the user's own words, and a stage that
trimmed them would be a second guesser sitting where §4 put a closed envelope. It
also would not help — `my green estate car` is as much a subset of the episode as
of the belief.

**Stop capturing routed passes**, or capture them without the utterance. Forbidden
by ADR-0197 §10, which requires the utterance to reach the capture point and names
the silent hole a lane that skipped it would leave: "a captured exchange with the
user's own sentence missing from it … visible only to the next person to resume
that conversation". The conversation record is not the thing to damage to fix a
lookup.

**Refuse an episodic id at the `forget` seam**, so the two doors agree by making
*both* of them decline. This is the one alternative that is not merely worse but
forbidden: ADR-0074 §8 rules that "the store deletes what it is told to delete" and
adds no kind-conditional refusal, in its own words "for the reason §5's rejected
alternative gives about a band-conditional one — 'a store that can refuse a
data-rights operation is a store where ADR-0004 §6 is conditional'" — the §5 there
being ADR-0073's. §6's third test exists so nobody implements §1 this way by
accident.
