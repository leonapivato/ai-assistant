# 74. A conversation is a first-class entity; a turn is an episode

- Status: Proposed
- Date: 2026-07-28
- **This is a contract change.** §9 adds one Protocol — `ConversationStore` — to
  `core/protocols.py`, two types to `core/types.py`, and one error class to
  `core/errors.py`. Golden rule 5 therefore applies: this ADR ships as **its own
  docs-only PR**, is reviewed while still `Proposed` so a finding can still change
  the decision, and is flipped to `Accepted` on merge (`CONTRIBUTING.md`,
  "Contract ADRs land before their implementation"; ADR-0015 §5). **No code
  changes with it.** Because the Protocol is *new*, the implementation lane owes
  the full triad — Protocol, shared conformance suite, canonical fake —
  in one change (`CONTRIBUTING.md`, "Adding a Protocol"), and stage 1 is this ADR
  merging (§9).
- **Changes no existing Protocol.** `MemoryStore`, `MemoryWriter`, `MemoryPolicy`
  and `Planner` are untouched (§3, §5, §9). Capture uses `add`, continuation uses
  `get` and `search`, and the conversation's turns reach the model through
  `Planner.plan`'s existing `memories` parameter.
- **Amends and supersedes nothing.** Applying ADR-0070 §1's test: no clause of a
  prior ADR is replaced. ADR-0005's taxonomy is used as written (§3); ADR-0072
  §3's two obligations on the derived band are read against their own stated scope
  and enforcement point rather than narrowed (§4); ADR-0073's store contract,
  order, and ceremony are untouched, and the one thing this ADR settles about that
  surface — its **default** kind selection — is a question ADR-0073 left unstated
  (§6). No ADR's Status line is edited.
- **Refs:** the roadmap's leg 2 (the mandate: "a conversation becomes a
  first-class, server-side entity — device-agnostic, resumable from any future
  spoke — and every turn is durably recorded as `EpisodicMemory`") and its
  stance 3 (hub and spokes, one spoke for now); VISION §Principle 8 (the resident
  service and the stateless client), §Principle 2 (typed, intentional, selective
  memory), §Principle 7 (deterministic systems own critical state); ADR-0005 §1
  (the four kinds, and `content` as a canonical rendering beside a structured
  payload), §2 (`Provenance`, and `evidence` as "references, e.g. episode ids"),
  §3 (propose/dispose); ADR-0072 §1 (one store), §2 (`band_of` is total), §3 (what
  a derived belief owes, its scope, and its enforcement point), §5 (retrieval is
  band-neutral); ADR-0073 §1 (`None` means every value), §2 (bounded default,
  named total order), §4 (what the belief surface conveys, and its two gates), §5
  (`delete` is unconditional; show-then-confirm), §7 (the façade is shape, not
  spelling); ADR-0007 §1 (the data-rights surface), §2 (retention is enforced at
  read time), §5 (size caps deferred); ADR-0004 §1 (conversation history is Tier
  1), §5 (logging), §6 (data rights), §7 (data minimization — "prefer references
  over copies where practical"); ADR-0042 §1 (the concrete façade), §3 (one call
  in, one result out), §4 (a parked confirmation); ADR-0052 (durable resume of a
  park); ADR-0064 (an ordinal only moves forward, and the store proves it);
  ADR-0066 §1 (what `complete` will accept as a history); ADR-0014 §5 and ADR-0049
  (the precedent that state with its own lifecycle gets its own store).

## Context

Leg 1 gave the user a way to read and kill what the assistant believes (ADR-0072,
ADR-0073). It listed a store of assertions, because the derived band has no
producer: the roadmap's own summary is that "a system that learns only by
dictation is the 'repeatedly explain preferences' failure VISION.md opens by
condemning". Leg 3's observer is what ends that — and it cannot be written,
because there is nothing for it to read.

The dated position, at the time of writing:

**A turn is an event with no record and no name.** `Engine.converse` runs one
turn — goal from the utterance, context, retrieval, plan, one step — and returns a
`TurnOutcome` (`orchestration/engine.py`, `orchestration/loop.py`). Nothing about
that turn is persisted. The next `converse` starts from zero: it has the memory
store, and no idea that a previous exchange happened at all. "Continue yesterday's
conversation" has no referent, and neither has "why do you believe that?" — because
the answer would have to cite an interaction nobody wrote down.

**The vocabulary for the record already exists and is unused.** ADR-0005 §1 named
`EpisodicMemory` — "something that happened", with `occurred_at`, `participants`,
`outcome`, `importance` — and §2 documented `Provenance.evidence` as "references
(e.g. episode ids)". ADR-0072 §3 hardened that reading into a rule: a proposal in
the `DERIVED` band "cites at least one evidence reference", and "an evidence
reference denotes the id of a record in the same store". So the shape of the
substrate is already ratified; what is missing is a producer. No production code
constructs an `EpisodicMemory` today (`testing/learning.py` is the only
constructor in the tree).

**Continuity is a hub property, decided before the hub exists.** VISION §Principle
8 rules that "a conversation begun in one place should be resumable in another,
because the conversation lives in the hub rather than in whatever displayed it",
and that every interface is a **stateless client**. The hub is leg 5; the roadmap
is explicit that legs 1–4 run inside the in-process application and that "slices
landing before the hub exists must not bake in single-shot or single-client
assumptions" (stance 3). A conversation identity minted now, with no hub, is
either device-agnostic by construction or a migration later.

**Four forces make this a decision rather than an implementation detail.**

1. **A new Protocol is a breaking change** (golden rule 5), and this one is the
   first durable state in the system that is neither a belief, a plan, nor an
   audit record. Whether it *is* new surface — as against an extension of
   `MemoryStore` — is the question the next lane would otherwise decide by
   whichever was easier to write (§9).
2. **Capture writes to memory without passing the propose/dispose gate**, which
   is the mechanism ADR-0005 §3 exists to enforce. Whether that is a hole or a
   correct reading of what the gate is *for* has to be argued, not assumed (§3).
3. **Every turn in the store changes what two shipped surfaces show.** Retrieval
   is kind-blind (`loop.py` calls `search(query, limit)` with no `kinds`) and the
   belief listing is kind-blind by default (`interfaces/cli.py`, `beliefs`), so
   the first capture lane silently changes what every turn retrieves and what
   `assistant beliefs` prints — unless this ADR says otherwise (§6).
4. **Verbatim capture of everything is in visible tension with the principle the
   product is built on.** VISION §Principle 2 asks the assistant to "remember
   selectively... and avoid preserving sensitive or incidental details without
   justification", and adds that "observing broadly and retaining broadly are
   different things". An episodic log of every word the user has ever typed is the
   most sensitive data the system holds (roadmap leg 3 says exactly this). A
   decision that does not reconcile the two is a decision that quietly loses to
   whichever principle the implementer read last (§7).

## Decision

### 1. A conversation is a first-class entity, identified by an opaque id the hub mints

A **conversation** is durable, server-side state with an identity of its own: a
`Conversation` record (§9) carrying an opaque id, when it started, and when its
last turn landed. It is not a session, not a process, and not a terminal.

**The id is opaque, random, and device-agnostic.** A UUID4 minted through an
injected factory, exactly as `orchestration/runner.py` and `planning/planner.py`
already mint ids (the determinism rule in `CONTRIBUTING.md`: inject randomness). It encodes nothing — not a device, not a pid, not a tty, not a
path, not a timestamp — for two reasons. Anything encoded in it is a fact a future
spoke would have to be able to forge in order to resume, which is how a local
assumption becomes a migration; and an id that sorts by mint time is an ordering
consumers start relying on before anyone decided it was one (§2's `last_turn_at`
is the ordering key, and it is a field).

**The hub mints; a client presents an id it was given.** A client never invents a
conversation id. If it could, two clients could collide on one, and a client could
name an id that already exists and graft its turns onto a conversation it was
never part of. This is VISION §Principle 7's rule (identity is deterministic
state) applied to the one identity the product has not needed until now.

**An id the store does not know is refused, not silently started.** A continuation
naming an unknown conversation raises rather than opening a fresh one under a new
id: silently starting one turns a typo, a stale copy-paste, or a client bug into
"my conversation vanished", and the user's continuation lands somewhere they
cannot find. The id is untrusted input from an adapter and is validated as such
(`core/types.py` `describe_untrusted` is what renders it back safely).

**The id may be logged; the turn may not.** It carries no user content, so it is a
correlation handle a Tier-2 log may hold — the same argument ADR-0055 makes for a
`ContextSource.name`, on a value that is random rather than declared. What the
user said stays out of logs unconditionally (ADR-0004 §5).

### 2. Lifecycle: one way to start, one way to continue, and no implicit end

**Start.** A turn carrying no conversation id starts one. The engine mints the
identity and records the conversation *before* the turn's work, so the id exists
independently of whether the turn succeeds, and the turn reports the id it ran
under. A turn that fails outright therefore leaves an empty conversation, which is
harmless and reclaimable (§7).

**Continue.** A turn carrying a conversation id appends to that conversation. This
is the whole of resumption: there is no "open", no lease, no attach. A spoke that
holds nothing but the id can continue a conversation begun anywhere, which is what
"device-agnostic, resumable from any future spoke" has to mean when the only spoke
is the CLI on the hub's own machine.

**The hub can answer "which conversation?", because a stateless client cannot.**
The store offers a bounded read of recent conversations, ordered by `last_turn_at`
descending with the id as tie-break — the shape ADR-0073 §2 argues for and
`AuditTrail.recent` set (ADR-0021 §4), for the same reason: some total order must
be named or two implementations answer the same page differently. Without this
read, "continue yesterday's conversation" would require the *client* to have kept
the id, which is precisely the state VISION §Principle 8 forbids an interface to
own.

**No implicit end, and no explicit close in this ADR.** A conversation does not
expire into a terminal state, and no idle timeout closes one. An idleness rule is a
presentation judgement — "is this the same conversation?" — invented ahead of any
consumer, and a wrong one is not cleanly recoverable: it splits, in the record,
something the user experienced as one thread. `last_turn_at` is a field, so any
consumer that wants an idleness reading takes its own without the hub imposing one.
An explicit close is **deferred with its consumer** (§11), and it is additive: a
status field on a record that has none forecloses nothing.

**Deletion is the only terminal state** (§8). That is deliberate: the one way a
conversation ends is the user ending it, which is ADR-0004 §6's right rather than a
lifecycle this system invented.

### 3. A turn is an episode: capture writes one `EpisodicMemory` per outcome

**Every turn the engine hands back is durably recorded as exactly one
`EpisodicMemory` in the one `MemoryStore`** (ADR-0072 §1). The turn *is* the
episode; episodes are not distilled from some other, more primitive turn entity.
Three reasons, in the order they bind:

- **ADR-0072 §3 pins the referent.** "An evidence reference denotes the id of a
  record in the same store." A citable episode that lived in a second store would
  break that clause on the day the observer first cited one — and the observer's
  citations are the entire point of the substrate (roadmap leg 2: "`Provenance.evidence`
  was designed to cite episode ids").
- **Distillation is leg 3's job, and leg 2 must not need it.** If a turn were raw
  material from which episodes are *later* distilled, the distiller would be a
  model-backed producer — which is the observer. Leg 2's exit test ("episodes
  exist that an observer could cite") would then be met by nothing until leg 3
  shipped, and leg 3 would be reading its own output.
- **A second verbatim store duplicates Tier 1 content.** The turn text would exist
  twice, under two retention rules and two deletion surfaces with no transaction
  between them. ADR-0004 §7 asks for the opposite ("prefer references over copies
  where practical"), and here it is practical: the episode already holds the text,
  because ADR-0005 §1 gives every record a `content` "canonical text rendering,
  used for lexical and (later) embedding retrieval".

**The unit is the turn, not the message and not the conversation.**

- *Not the conversation*: an episode that grows with each turn is a mutable
  aggregate, and the shared record graph is frozen (ADR-0068). A citation to "the
  whole conversation" is also not evidence — it is a gesture at everything.
- *Not the message*: `EpisodicMemory` carries an `outcome`, which is a property of
  a completed exchange, and one `occurred_at`, which a pair of messages minutes
  apart does not have. An assistant message on its own is also not "something that
  happened" in any sense an observer can reason over.

**The capture point is where a `TurnOutcome` is produced**, which is both
`Engine.converse` and `Engine.resume` (ADR-0042 §3's "one result out"). So a turn
that parks for confirmation is captured when it parks, and its resumption
(ADR-0052) is captured as its own episode. Two records, both true: the unit is
what the user saw, and a park *is* an answer. The alternative — hold the episode
open until the park resolves — makes the record of an exchange depend on a
confirmation the user may never answer (ADR-0059's lifetime deadline), so an
abandoned park would erase the question the user actually asked.

**A turn that raises before producing an outcome is not captured**, and the gap is
deliberate. There is no exchange to record: the adapter rendered an error, the
engine produced no result, and what failed is *operational* information — Tier 2,
and the subject of leg 8's `EvaluationTrace`, not of Tier 1 memory (ADR-0004 §1).
Writing an episode whose outcome is an internal fault would put debugging data in
the store the user inspects and the observer mines. Revisit if the observer turns
out to need failed turns; it is additive.

**Capture is deterministic recording, and it does not pass the propose/dispose
gate.** It calls `MemoryStore.add` directly, not `MemoryWriter.ingest`. ADR-0005's
worry is stated precisely and is a different worry: "if the **model** can write
arbitrary statements straight into permanent memory, memory becomes an unbounded,
unreviewable side effect" (§Context, third problem), and its rule is that "memory
is never written directly by the model" (§3). Capture writes what was said, by
deterministic code, inferring nothing — which is VISION §Principle 7's own
division. Routing it through the gate would also be incoherent: `MemoryPolicy`
rules `ACCEPT`/`REJECT`/`ASK_USER` (ADR-0005 §3), and there is no sense in which a
policy may reject the fact that an exchange occurred, ask the user whether they
would like their own question remembered, or detect a conflict between two things
that both happened.

**What bounds it instead is that capture writes one record per outcome, judges
nothing (§4), and retains under a finite default horizon (§7).** Unmediated is not
unbounded.

### 4. What capture stamps — and the two obligations on the derived band

`Provenance.source` is `OBSERVED`: the assistant witnessed the exchange. That
places every captured episode in the `DERIVED` band, because `band_of` is total and
maps `OBSERVED` there (ADR-0072 §2). Capture is therefore the **first producer
into the derived band**, arriving before the observer it exists to feed, and
ADR-0072 §3's two obligations have to be answered rather than stepped around.

**The sub-1.0 obligation binds capture.** §3's reason is about standing: "a
producer that can emit 1.0 is claiming the standing that only the user's own word
carries". An episode quotes the user, which is not the same as the user asserting
a fact about themselves, and the belief surface renders confidence (ADR-0073 §4) —
so an episode at 1.0 would read exactly like an assertion. Capture stamps a single
documented constant strictly below 1.0. The *value* is the implementing lane's:
nothing reads it comparatively, because retrieval is confidence-neutral (ADR-0072
§5) and inspection only renders it. What is ratified is that it is a constant and
not a computed score — capture has nothing to compute from.

**The evidence obligation does not bind capture, and this is the load-bearing
half.** §3's rule is that "a **proposal** in the `DERIVED` band cites at least one
evidence reference", and it names its own scope and enforcement point: the
obligations are "scoped to beliefs proposed into the `MemoryStore`", "because they
need an enforcement point and only the memory write path has one: a proposal is
judged by a `MemoryPolicy` before it is stored". Capture is not a proposal and
reaches no policy (§3). Substantively the rule would also invert its own
rationale — it exists because a derived belief with no evidence "cannot answer
'why do you believe that?'", and an episode's answer is that it happened and was
recorded as it happened. An episode is the terminal citation: the thing other
records cite. Requiring it to cite something would demand a regress or a
self-reference.

Two obligations follow from saying that out loud rather than leaving it inferred:

- **The `MemoryPolicy` rule leg 3 owes must exempt episodes.** ADR-0072 §3 assigns
  "writing that rule" to the observer's lane. That rule is now constrained: it
  binds proposals of *beliefs*, and an `EPISODIC` record reaching the gate must not
  be refused for citing nothing. Stating it here is what stops leg 3 from writing a
  band-wide rule that would make its own substrate unwritable if capture were ever
  routed through the writer.
- **ADR-0073 §4's gate stays on leg 3, and capture does not trip it.** That gate is
  that "leg 3's observer may not land a populated `DERIVED` band behind an
  inspection surface that cannot say why" — an obligation about resolving *citations*
  into readable evidence. An episode's warrant is complete with no citation to
  resolve, in the same way ADR-0038 §1a makes an assertion's warrant complete. The
  gate is on the first producer of derived **beliefs**, and it is untouched.

**Capture judges nothing else.** `importance` stays at its default: importance is a
judgement, and salience is leg 7's decision, not a number the recorder invents.
`participants` stays empty: the two parties to a turn are structural rather than
informative, and filling the field with constants would occupy, with noise, the
field an observer means to fill with the people an episode is *about*. `validity`
stays fully open: nothing retires an episode, because supersession is a law about
beliefs that contradict each other (ADR-0045 §4, ADR-0072 §4) and two things that
happened never do. `occurred_at` and `Provenance.last_updated` come from the
injected clock (ADR-0026), and `content` is the canonical rendering of the exchange
— what was asked, and how it turned out.

### 5. Continuity reaches the model through the seam it already has

The conversation's recent turns are handed to the planner as part of `memories`,
the `Sequence[MemoryRecord]` parameter `Planner.plan` already takes. **No Protocol
changes**, and in particular `Planner` does not grow a `history` parameter.

The retrieval stage's output becomes: the conversation's recent episodes, **first**,
followed by the relevance-retrieved beliefs. The parameter is documented "records
retrieved as relevant to the goal, best first", and placing the tail first is
faithful to that reading rather than a strain on it — for a continued conversation
the immediately preceding turns *are* the most relevant records the store holds.
Both halves are already `MemoryRecord`s, and the planner already renders records
into its prompt (`planning/planner.py`), so this is the existing mechanism carrying
one more thing.

**The tail is bounded**, by a configured count of recent turns, for the reason
every read in this system is bounded (ADR-0021 §4, ADR-0073 §2): an unbounded
replay of a months-old conversation is a prompt nobody sized. Which turns fall
inside the bound is a window over the conversation's ordinals, not a relevance
question.

**Turns are read through the index and fetched by id**, and an id that no longer
resolves is **skipped, not an error** (§8's partial states, §7's expiry). A
conversation that lost a turn to a deletion shows a gap; it does not fail to
resume, and it never resurrects the deleted turn.

**A batch read on `MemoryStore` is declined.** Fetching *k* episodes is *k* calls
to `get`. A `get_many` would be a contract change bought for one caller at a scale
where it buys nothing measurable, and the honest place to revisit it is the hub,
where a resume crosses a transport (§11).

**Tool turns are not replayed as messages, and this ADR does not make them
representable.** `ModelProvider.complete`'s contract records that "a tool
exchange is not representable at this seam", that "both implementations reject any
history containing one", and that "nothing here promises tool support"
(`core/protocols.py`, ADR-0066 §1). Continuity delivered as *records* rather than as a `Message` history
sidesteps that entirely — which is a further argument for the seam chosen here,
not a gap in it.

### 6. An episode is substrate, not a belief: what the two reading surfaces do

Capture puts tens of records per day into a store two shipped surfaces read
kind-blind. Neither behaviour is defensible once the store fills, and neither
requires a contract change to fix.

**Retrieval selects the belief kinds.** The turn's relevance retrieval passes a
`kinds` filter excluding `EPISODIC`, so a captured turn does not compete with
beliefs for the retrieval budget. This changes nothing observable today — nothing
writes an `EPISODIC` record in production — and it prevents the alternative, which
is that the first capture lane silently changes what every turn retrieves and
nobody decides whether that was an improvement. Cross-conversation episodic recall
("what did we discuss last Tuesday?") is a real capability and is **deferred with
its ranking question** (§11): mixing raw turns with distilled beliefs in one
relevance cut is the ordering problem leg 7 is for. `MemoryStore.search` itself
stays exactly as ADR-0072 §5 ruled — band-neutral, kind-filtered only by its
caller's argument.

**The belief listing excludes `EPISODIC` by default.** `assistant beliefs` answers
"what do you believe about me", and an episode is not a belief — it is the evidence
a belief is made of. Left kind-blind, the surface leg 1 built to be readable would
print a transcript. `--kind episodic` still lists episodes, and the store contract
is untouched: ADR-0073 §1's "`None` means every value" is a *store* semantic, and
ADR-0073 never pinned the CLI's default (§4 names what a belief conveys; §7 names
the flags). This ADR settles a question that surface did not have to face while the
derived band was empty.

**Nothing here weakens ADR-0073 §5.** An episode is a record with an id, so
`assistant forget <id>` destroys one exactly as it destroys a belief, and §8 adds
the conversation-scoped form.

### 7. Retention: episodes are substrate with their own horizon

**Captured episodes carry a finite `expires_at` by default**, stamped at capture
from the injected clock and a retention window read from `core.config.Settings`
(the `confirmation_ttl: timedelta | None` field is the shape: a duration, with
`None` available to mean "no deadline"). Expiry is enforced at read time and
reclaimed by `purge_expired` (ADR-0007 §2), so the guarantee does not wait on a
scheduler that does not exist yet (leg 5).

This is the reconciliation VISION §Principle 2 demands, and it is a real one:

- **The principle governs the belief layer, and the mechanism it names is the
  gate.** "What the assistant observes is *proposed*; a deterministic policy
  decides what is kept; and what is kept carries its provenance, its confidence,
  and the evidence behind it." That is a rule about *beliefs*, and it presumes
  something observed for the policy to judge. VISION's own next sentence — "observing
  broadly and retaining broadly are different things" — is only satisfiable if the
  observed material exists in some retained form for the gate to read.
- **So the tension is not resolved by capturing less; it is resolved by episodes
  being a different kind of thing with a shorter life.** A belief is retained
  indefinitely, is inspectable, and is corrigible. An episode is retained for a
  bounded window, is not presented as a belief (§6), and is what the belief is
  answerable to. The distillation that carries value past the horizon is leg 3's
  observation and leg 7's consolidation — which is exactly the shape the roadmap's
  accumulation loop already draws.
- **"Without justification" is answered by the horizon, not by an exemption.** A
  turn is preserved because it is unread evidence, and a finite window is what
  makes that claim expire when it stops being true.

**The default is finite, and the user may set it to unbounded.** The choice matters
in one direction more than the other: an unbounded default would ship an
ever-growing Tier-1 log of everything the user has ever typed, with no cap decision
behind it (ADR-0007 §5 deferred size caps), and the roadmap names the episodic
stream the most sensitive data the system holds (leg 3). Keeping forever is a
decision a user can make; it is not one the system should make on their behalf by
default. The accepted cost is stated plainly: **a conversation older than the
horizon cannot be continued in full**, and its turns are gone from retrieval and
export.

**A belief may outlive its evidence, and this ADR does not close that.** ADR-0072
§3 already named it — "a retention deadline can end that" — and filed it. Capture
turns it from hypothetical into reachable, so what is added here is the gating, not
the answer: leg 3 may not populate the derived band without deciding what a belief
whose citations have expired renders, which is the same lane ADR-0073 §4 already
gates on. The question is not made easier by having capture guess at it now.

**The conversation record's retention follows its turns.** A conversation whose
turns have all expired or been deleted holds nothing but a timestamp, and is
reclaimable by the same purge (§9's obligation). No separate deadline is put on the
conversation record, because two clocks over one thing is two clocks to disagree.

### 8. Deletion: unconditional, conversation-scoped, and ordered

ADR-0004 §6's right applies unchanged, and ADR-0073 §5's ruling extends to
episodes: **"the store deletes what it is told to delete"** (§5), and no
kind-conditional refusal is added, for the reason §5's rejected alternative gives
about a band-conditional one — "a store that can refuse a data-rights operation is
a store where ADR-0004 §6 is conditional".

**The conversation is a deletion unit, because it is the unit the user thinks
in.** "Forget this conversation" destroys the conversation's episodes and its
index. It is not atomic — two stores, no cross-store transaction — so the order is
ratified rather than left to the implementer:

- **Episodes first, index second, in both directions.** On capture: write the
  episode, then the turn index. On deletion: delete the episodes, then the index.
- **A partial failure must never leave content the user believes destroyed.**
  Deleting the index first would leave orphan episodes — still retrievable, still
  inspectable — under a conversation the user was told was gone. Deleting the
  episodes first leaves index entries pointing at nothing, which the read skips as
  a gap (§5), so the visible state is *more* deleted than the operation completed,
  never less.
- **The same asymmetry makes the capture order right.** A failure between the two
  writes leaves an episode that no conversation lists: a true record of something
  that happened, retrievable and deletable, merely absent from a transcript. The
  reverse would list a turn whose content never existed.
- **The operation is idempotent**, so re-running it finishes a partial one.

**Deleting one episode is deleting one record**, through the surface leg 1 already
shipped (ADR-0073 §5's show-then-confirm, with its window named and accepted). The
conversation-scoped form obeys the same ceremony: what will be destroyed is shown
before consent is taken, in a form a human can judge — for a conversation, the
count and span rather than every turn.

### 9. The contract surface owed, and why it is a new store

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/types.py`** gains `Conversation` (the identity and its two stamps:
  `started_at`, `last_turn_at`) and `ConversationTurn` (the conversation it belongs
  to, its ordinal, the id of the episode that records it, and when it occurred).
  Both frozen pydantic models (ADR-0068), both timezone-aware at every instant
  (ADR-0023, ADR-0030).
- **`core/protocols.py`** gains **one** Protocol, `ConversationStore`, owing:
  start a conversation; read one by id; append a turn, allocating its ordinal;
  read a conversation's turn tail, bounded and ordered; read recent conversations,
  bounded and ordered by `last_turn_at` (§2); resolve an episode id back to the
  turn that cites it (§10 declines duplicating that relation onto the record, so
  the store owes both directions); delete a conversation; export; and reclaim
  conversations left empty by expiry (§7).
- **`core/errors.py`** gains a `ConversationStoreError` in the `AssistantError`
  hierarchy, because every seam raises from it (`CONTRIBUTING.md`) and no existing
  class fits — a conversation is not memory, planning, context, or audit.

**Signatures are deliberately not written here.** What is ratified is the
obligation set and the semantics above; the exact spelling ships with the triad,
where a real caller can hold it. Three semantics are ratified rather than deferred,
because they are where two implementations silently differ:

1. **The ordinal only moves forward, and the store proves it.** Per conversation,
   ordinals are dense, unique, and monotonic — a store-enforced invariant, not a
   convention a caller keeps, which is ADR-0064's ruling applied to a second log.
   It is what makes a second concurrent appender (§11) a conflict the store can
   detect rather than a silent interleave.
2. **Every read is bounded by default and totally ordered** (ADR-0021 §4, ADR-0073
   §2): turns by ordinal, conversations by `last_turn_at` descending with the id as
   tie-break.
3. **The standing module clauses bind it** like every other Protocol: input
   observation before the first await (ADR-0065), cancellation that does not orphan
   a resource (ADR-0060), and detached snapshots on every read.

**Why a new Protocol rather than an extension of `MemoryStore`.** The rejected
alternative is real: `MemoryStore` already holds the episodes, and a
`conversation_id` field on `EpisodicMemory` plus a conversation-scoped read would
avoid a second seam entirely. It is refused because the two contracts answer
different questions:

- `MemoryStore`'s reads are **belief** reads — relevance ranking, two read-time
  axes, a band vocabulary, live-only enumeration. A conversation is an
  **append-ordered log** with an ordinal invariant and no notion of being
  superseded. Putting one behind the other means every future belief read carries a
  conversation axis it does not want, which is precisely the widening ADR-0073 §1
  and §3 refused for `list_beliefs` (a `sources` filter, an `include_retired`
  flag) — and for the same reason: one flag, two questions.
- **The precedent is that state with its own lifecycle gets its own store.**
  `PlanStore` (ADR-0014 §5, ADR-0049) and `AuditTrail` (ADR-0021) are both Tier 1,
  both local, and both separate — not because a store was cheap, but because their
  invariants are their own. ADR-0072 §1's "one store" argument is about beliefs
  not being split into a profile store and a model store; it is not a rule that all
  durable state is memory. VISION §Principle 8 lists what the hub owns as "memory,
  the user model, conversations, plans, permissions" — four things, named
  separately.
- **The membership relation gets exactly one home.** A `conversation_id` on the
  record *and* an index is two records of one fact, and they drift. The index wins
  because `EpisodicMemory` is general — an episode ingested from a calendar (leg 6)
  has no conversation — and a field that is empty for whole classes of record is a
  field consumers learn to distrust.

**What the implementing lane owes** (stage 2; stage 1 is this ADR merging):

1. The Protocol, the two types, and the error class.
2. **The shared conformance suite**, with a clause per obligation above — the
   ordinal invariant under repeated appends, the two orders including tie-breaks,
   the bounded defaults, an unknown id refused rather than created (§1), an
   unresolvable episode id skipped rather than raised (§5), detachment, and input
   observation. A suite that only exercises small explicit values will not reach
   the ordinal invariant or the defaults; the argument ADR-0073 §8 makes about
   `offset` and about the default `limit` applies here unchanged.
3. **The canonical fake** in `ai_assistant.testing`, plus the concrete
   `Test…Contract` subclass that runs it through the suite — without which the
   triad check fails, naming what is missing (`CONTRIBUTING.md`).
4. **A production implementation**, SQLite-backed beside the existing stores, with
   ADR-0004 §4's file permissions.
5. **The capture stage and the façade** (§3, §5): `Engine.converse`/`Engine.resume`
   take an optional conversation id and report the one they ran under. The façade
   is concrete and not a contract (ADR-0042 §1), so those names are shape, not
   spelling (ADR-0073 §7).
6. **The CLI** (§10): continuation is an option on `ask`, plus a listing of recent
   conversations. Capture failure degrades the turn rather than failing it — the
   answer is still the answer — but it is **reported** on the outcome beside
   `memory_degraded`, because a user whose turns are silently not being recorded
   will not find out until they try to continue.

### 10. Explicitly declined

- **A separate verbatim transcript store, with episodes distilled from it.** §3.
  It duplicates Tier 1 content, splits retention and deletion across two stores
  with no transaction, and makes leg 2 depend on leg 3's distiller to produce
  anything citable.
- **A `conversation_id` field on `EpisodicMemory`.** §9. Two homes for one
  relation, on a type that is general to episodes from any source.
- **A `messages: tuple[Message, ...]` payload on `EpisodicMemory`.** §5. Continuity
  reaches the model as records, so the structured message list has no reader — and
  `Role.TOOL` turns are not representable at the model seam anyway (ADR-0066 §1).
- **A `history` parameter on `Planner.plan`.** §5. A Protocol change bought where
  the existing `memories` parameter already carries what the planner renders.
- **A conversation axis on `MemoryStore.search` or `list_beliefs`.** §9. One flag,
  two questions — the widening ADR-0073 §1 and §3 refused.
- **A batch `get_many` on `MemoryStore`.** §5. Deferred to the hub, where a resume
  crosses a transport.
- **An idle timeout that ends a conversation, or a `title` on the record.** §2. Both
  are judgements with no consumer; a title is model-generated summary, which is
  leg 3's work.
- **A turn count on `Conversation`.** §2. ADR-0073 §7 declined a count for want of
  a consumer, and this one is derivable from the ordinal.
- **Reusing the verb `resume`.** `Engine.resume` and the CLI's `resume` answer a
  *parked confirmation* (ADR-0042 §4, ADR-0052). Continuation is an option on
  `ask`, not a second meaning for a verb that transports consent; overloading it
  would put two unrelated flows behind one word in the surface where the
  distinction matters most.
- **Recording a device, client, or transport on a turn.** §11. It would invent an
  identity scheme the later arc owns.

### 11. What this ADR does not decide

- **Multi-spoke concurrency.** Two clients appending to one conversation at once.
  Not foreclosed: §9's ordinal is allocated and proved by the store, so a second
  appender is a detectable conflict rather than a silent interleave — what is
  deferred is the *policy* (refuse, re-order, or branch), which needs a second
  spoke to be a real question. It is also where ADR-0046 §5's deferred
  compare-and-swap (#248) stops being hypothetical.
- **Push delivery and sync.** Not foreclosed: a client holds nothing but an id it
  was given (§1, §2), so "conversation X has a new turn" is deliverable to it
  without any state migration on either side.
- **Cross-device presence — which device is live in a conversation.** Not
  foreclosed, and deliberately not started: nothing on a turn records where it came
  from, and adding it later is additive. Recording it now would require a device
  identity, whose enrolment and revocation the later arc owns.
- **Network transport and its security posture.** Not foreclosed: capture and
  continuation happen entirely behind the `Engine` façade, so the transport
  boundary is the façade's (leg 5's local-API ADR), and nothing decided here
  crosses a wire or assumes it does not.
- **Cross-conversation episodic recall and its ranking** (§6). Due with leg 7's
  retrieval-under-load work, or earlier if the observer needs it.
- **What a belief whose evidence has expired renders** (§7). ADR-0072 §3's filed
  question, gated on leg 3 like ADR-0073 §4's citation-resolution gate.
- **Whether capture ever passes a policy**, and the `EPISODIC` exemption that rule
  would need (§4). Leg 3 writes the rule; this ADR constrains it.
- **Size and count caps on the episodic stream.** ADR-0007 §5's deferral is
  unchanged: §7 enforces a TTL, and which records to evict under a cap is still its
  own decision.
- **An explicit "close this conversation"** (§2), **an import of an exported
  conversation** (ADR-0007 §5), **streaming a turn** (ADR-0042 §5), and **failed
  turns as records** (§3). Each additive, each waiting for a consumer.

## Consequences

- **Leg 2's exit test is met by what ships**: a conversation has a durable,
  device-agnostic identity that any client can continue by id, and every turn
  leaves an `EpisodicMemory` an observer can cite by id. The observer does not
  exist yet, and the substrate is correct without it — the same shape leg 1 landed
  in (a correct surface over an empty band).
- **The contract owed is one Protocol, two types, and one error class.** No
  existing Protocol changes, which is the smallest surface this leg could have
  needed and is only possible because ADR-0005 already typed episodic memory and
  `Planner.plan` already takes records.
- **Capture is the first producer into the derived band**, arriving ahead of the
  observer. That is stated rather than discovered, and it is why §4 answers
  ADR-0072 §3's two obligations explicitly instead of leaving the next lane to
  infer that a transcript is a belief.
- **The propose/dispose gate keeps its scope.** Capture writing directly is a
  reading of ADR-0005 §3, not an exception to it: the gate governs what the *model*
  proposes about the user, and recording that an exchange happened proposes nothing.
  A later producer that wants to write beliefs still goes through the gate, and
  §4's constraint on leg 3's policy rule keeps the two from colliding.
- **Two shipped surfaces are deliberately narrowed** (§6) on the day capture lands,
  and the narrowing is invisible today because nothing writes an episode. Had it
  not been decided here, the first capture lane would have changed what every turn
  retrieves and what `assistant beliefs` prints, as a side effect nobody ratified.
- **Selective memory survives contact with a transcript** — because episodes are
  given a shorter life than the beliefs distilled from them, not because capture is
  made stingy. The cost is real and named: a conversation older than the retention
  horizon cannot be continued in full.
- **A resumed conversation can show gaps**, from a deleted turn or an expired one
  (§5, §7, §8). That is the deletion right working, and it is the one behaviour
  a "restore my history" instinct would break.
- **Deletion across two stores is ordered rather than atomic** (§8). The residue of
  a partial failure is always *more* deleted than the operation completed, which is
  the only asymmetry a data right can tolerate.
- **The hub inherits a conversation model it does not have to change** (§11): ids
  it minted, clients that hold nothing, an ordinal it can arbitrate on, and no
  transport assumptions.
- **Revisit if** a second spoke makes concurrent appends real; if the observer
  needs failed turns, cross-conversation recall, or a batch episode read; if the
  retention horizon proves to be the wrong default in either direction; or if a
  conversation's turn tail grows large enough that a bounded window over ordinals
  stops being the right way to choose what the model sees.

## Alternatives considered

- **Turns in their own store, verbatim; episodes distilled from them later.**
  Rejected in §3. It breaks ADR-0072 §3's same-store referent for evidence, defers
  leg 2's only deliverable to leg 3's distiller, and stores the user's words twice
  under two retention rules.
- **Everything in `MemoryStore`: a `conversation_id` on `EpisodicMemory` plus a
  conversation-scoped read.** Rejected in §9. It is genuinely the smaller surface,
  and it is what a reviewer should expect this ADR to take. It loses on three
  counts: identity would not exist until a turn was captured (so a client cannot be
  told which conversation it is in until after the answer); ordering would rest on
  a clock rather than on a store-proved ordinal, which is undecidable for two
  concurrent appenders; and a belief contract would grow an axis for a question it
  is not asked, the widening ADR-0073 refused twice.
- **One episode per message, role-tagged.** Rejected in §3. `EpisodicMemory` has one
  `occurred_at` and one `outcome`, both properties of a completed exchange, and half
  an exchange is not "something that happened" an observer can reason over.
- **One episode per conversation, appended to as it grows.** Rejected in §3. It
  requires a mutable record in a frozen graph (ADR-0068), and a citation to a whole
  conversation is not evidence.
- **Capture through `MemoryWriter.ingest`, so every write passes the policy.**
  Rejected in §3. `MemoryPolicy`'s rulings are meaningless applied to a record of
  what happened, conflict detection has nothing to detect, and a `REJECT` would
  silently discard an interaction the user had. The property the gate protects —
  the model not writing about the user unreviewed — is untouched, because capture
  infers nothing.
- **Episodes at confidence 1.0, on the grounds that the exchange certainly
  happened.** Rejected in §4. Confidence is standing, not certainty about the
  recording, and 1.0 is the standing only the user's own word carries (ADR-0072 §3).
  An episode rendered beside an assertion at equal confidence teaches exactly the
  false model ADR-0072 §6 exists to prevent.
- **Unbounded episodic retention by default.** Rejected in §7. It ships an
  ever-growing log of the most sensitive data the system holds, with no cap
  decision behind it (ADR-0007 §5), and makes "avoid preserving without
  justification" (VISION §Principle 2) a setting rather than a default.
- **Cascading the retention deadline: keep an episode alive while a belief cites
  it.** Rejected in §7 by omission, and named here so the silence is not read as an
  oversight. It sounds protective and it inverts the principle: a low-confidence
  inference would pin the raw transcript it was derived from, indefinitely, and the
  more the observer proposed the less anything would ever expire. What a belief
  outliving its evidence should do is ADR-0072 §3's open question, and it is
  answered by the lane with a producer.
- **A conversation that ends after an idle period.** Rejected in §2. It is a
  presentation judgement with no consumer, and getting it wrong splits, in the
  record, what the user experienced as one thread.
- **Letting the client mint the conversation id.** Rejected in §1. It makes
  collision the hub's problem to arbitrate and lets a client name an id it was
  never given.
- **Starting a fresh conversation when an unknown id is presented.** Rejected in
  §1. It converts a typo or a stale id into a silently lost continuation, which is
  the failure mode a user cannot diagnose.
