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
  and `Planner` are untouched (§3, §5, §9). Capture uses `write_atomic` in the
  `INSERT_IF_ABSENT` mode ADR-0046 §2 already ratified, continuation uses `get`
  and `search`, and the conversation's turns reach the model through
  `Planner.plan`'s existing `memories` parameter.
- **Amends and supersedes nothing — because ADR-0075 carries the one supersession
  this decision needs.** Applying ADR-0070 §1's test: no clause of a prior ADR is
  replaced *here*. The contestable case was ADR-0005's proposal → policy write
  path, which capture does not use; §3 sets out why the rule's subject is a belief
  rather than the evidence a belief cites. That argument was adjudicated
  insufficient to avoid a supersession (#442), so **ADR-0075 partially supersedes
  ADR-0005 in exactly that scope and merged first** — this ADR is built on the
  amended rule rather than against the original one. ADR-0005's taxonomy is used as
  written (§3); ADR-0072
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
  park); ADR-0046 §2 (the write modes, and why a minted id is inserted rather than
  upserted), §3 ("absent" is physical presence), §5 (the deferred compare-and-swap,
  #248); ADR-0064 (an ordinal only moves forward, and the store proves it);
  ADR-0066 §1 (what `complete` will accept as a history); ADR-0014 §5 and ADR-0049
  (the precedent that state with its own lifecycle gets its own store); **ADR-0075
  §1 and §2** (the partial supersession of ADR-0005's write path that §3's capture
  rests on, and how narrow it is), ADR-0070 §1 (the test that made it a
  supersession rather than a reinterpretation); #441 (the
  unratified vision direction whose leg-2 constraints §3 carries and §11 files).

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
last turn landed — the latter **unset until a turn actually lands** (§2). It is
not a session, not a process, and not a terminal.

**The id is opaque, random, and device-agnostic.** A UUID4 minted through an
injected factory, exactly as `orchestration/runner.py` and `planning/planner.py`
already mint ids (the determinism rule in `CONTRIBUTING.md`: inject randomness). It encodes nothing — not a device, not a pid, not a tty, not a
path, not a timestamp — for two reasons. Anything encoded in it is a fact a future
spoke would have to be able to forge in order to resume, which is how a local
assumption becomes a migration; and an id that sorts by mint time is an ordering
consumers start relying on before anyone decided it was one (§2's `last_turn_at`
is the ordering key, and it is a field).

**Starting a conversation is an insert, never an overwrite.** `start` writes the
record only if its id names nothing — the same rule and the same reason as §3's
episode insert, and it matters for the same reason: the factory is *injected*, so
a repeating test double, a seeded factory, or a future non-random scheme makes a
collision reachable in a way probability does not answer. On collision `start`
retries with a freshly minted id, and exhausting a small retry budget raises
`ConversationStoreError` (§9) rather than returning a conversation whose id names
someone else's. A `start` that overwrote would destroy a conversation; one that
silently returned the existing record would graft a stranger's turns onto this
client's — the same failure §1 refuses when a *client* names an id, arriving from
the other direction.

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

**Beginning a turn is activity, and it is recorded before the turn's work — in a
field of its own.** A continuation marks the conversation active at the moment it
is resolved, not only when its turn is captured. Two things need that. A turn
against a conversation sitting at its retention horizon would otherwise be racing
the reclaim that drops it (§7) — the user is *using* the conversation, and nothing
in the record would say so until the turn ended. And a turn that never completes
still says the user was here, which is the honest input to "which conversation?"
below.

**`last_active_at` and `last_turn_at` are two different facts and are two
fields.** Activity is "someone was here", set when the conversation is created and
again whenever a turn begins. `last_turn_at` is "a turn was **recorded**" — set by
the append that writes the turn into the index, and unset until one is (§9).

**It is recorded-time, not landed-time, and that is a decision rather than an
approximation.** A turn's existence in this design *is* its index entry: the
episode is its content, and content can be missing from a turn that certainly
happened — deleted by the user (§8), expired (§7), or never written because the
memory store failed (§3). A field meaning "the episode is on disk" would need an
operation to set it after the second write, would be false for exactly the turns
whose content was later removed, and would make the record disagree with the read
rule that already treats an unresolvable turn as a gap (§5). Writing an *attempted
continuation* into it would be the different and worse error — claiming a turn that
was never even recorded — which is what `last_active_at` is for. The distinction is
not cosmetic: `last_turn_at` unset is what tells the empty conversation from the
one whose first turn landed instantly, which §7's reclaim and any future idleness
reading both depend on. The mark is a conversation-store mutation like any other,
so it takes the same per-conversation exclusion as an append, a deletion and a
reclaim (§9).

**The hub can answer "which conversation?", because a stateless client cannot.**
The store offers a bounded read of recent conversations, ordered by **last
activity** descending with the id as tie-break — the shape ADR-0073 §2 argues for
and `AuditTrail.recent` set (ADR-0021 §4), for the same reason: some total order
must be named or two implementations answer the same page differently.

**Last activity is `last_active_at`**, which is set at creation and refreshed by
every turn that begins (above), so the sort key is always present and the order is
total with no fallback rule to get wrong — the alternative, a key defined only for
conversations that have turns, is exactly where two conforming stores answer the
same page differently. `last_turn_at` is *not* the sort key: ordering a listing by
"has a turn landed" would sink a conversation the user opened a minute ago below
one they abandoned last week. Without this
read, "continue yesterday's conversation" would require the *client* to have kept
the id, which is precisely the state VISION §Principle 8 forbids an interface to
own.

**No implicit end, and no explicit close in this ADR.** No idle timeout closes a
conversation. An idleness rule is a presentation judgement — "is this the same
conversation?" — invented ahead of any consumer, and a wrong one is not cleanly
recoverable: it splits, in the record, something the user experienced as one
thread. `last_turn_at` is a field, so any consumer that wants an idleness reading
takes its own without the hub imposing one. An explicit close is **deferred with
its consumer** (§11), and it is additive: a status field on a record that has none
forecloses nothing.

**A conversation ends in exactly two ways, and neither is a judgement about
whether it is "over": the user deletes it (§8), or retention expires it (§7).**
The first is ADR-0004 §6's right. The second is data minimisation reaching the
whole record rather than a lifecycle rule — the same horizon that governs the
turns, applied to what indexes them — and it is worth separating from the first
because they behave differently on the way there:

- **While the record stands, an emptied conversation is still appendable.** Turns
  expire before the record does (§7), so a conversation whose turns are gone can
  still be continued by id; it simply continues with no history, exactly as a
  turn deleted from the middle leaves a gap (§5). Expiring the *content* does not
  retire the *identity*.
- **Once the record itself is reclaimed, its id is unknown**, and a continuation
  naming it is refused as §1 refuses any unknown id — loudly, rather than by
  silently starting a fresh conversation under a new one. That is the one way a
  valid id stops working through the passage of time, and it is stated here rather
  than discovered by a client that held one too long.

### 3. Every turn is an episode: capture writes one `EpisodicMemory` per outcome

**Every turn the engine hands back is durably recorded, and its content is exactly
one `EpisodicMemory` in the one `MemoryStore`** (ADR-0072 §1; the two halves are
separated below, because only the first is atomic with the turn). The turn *is* the
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

**The entailment runs one way: every turn is an episode, and not every episode is
a turn.** This ADR decides what a *conversation* deposits in the store; it does
not define an episode as a thing conversations produce. `EpisodicMemory` is
ADR-0005 §1's general kind — "something that happened" — and a source that is not
a conversation at all deposits one too: a calendar event ingested by leg 6's
sensors, and (per #441, a direction recorded but not ratified) a captured moment
with a timestamp and no dialogue around it.

The shape carries that without a caveat, and it is §9's decision that makes it so:
**conversation membership lives in the conversation index, not as a field on the
record.** An episode belonging to no conversation is therefore the *default* shape
rather than a permitted exception — there is no `conversation_id` to leave unset,
no convention about what an empty one means, and no producer obliged to invent a
conversation to have somewhere to put its episode. A design that had put
membership on the record would have made "episode = turn" true by construction,
which is exactly the retrofit #441 asks leg 2 to avoid.

**The unit is the turn, not the message and not the conversation** — for a
conversational episode, which is the only source that exists to decide for.

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

**The guarantee is exact about which half is durable.** A turn is recorded when its
index entry lands, and its episode is written immediately after (§8's intent log).
The two are separate stores, so a memory-store failure — an embedder fault, a
locked database — leaves a turn recorded with **no** episode: the transcript shows
a gap at that ordinal, the observer has nothing to cite for it, and the failure is
**reported on the outcome** (§9) rather than swallowed. That is the honest form of
"every turn is captured", and it is preferred over the two alternatives. Failing
the turn would throw away an answer the user already has because the record of it
could not be written. Retrying would record the exchange twice (above). A missing
episode is the one outcome that loses nothing but the record, says so, and is
indistinguishable — to every reader — from the turn the user deleted themselves.

**A turn that raises before producing an outcome is not captured**, and the gap is
deliberate. There is no exchange to record: the adapter rendered an error, the
engine produced no result, and what failed is *operational* information — Tier 2,
and the subject of leg 8's `EvaluationTrace`, not of Tier 1 memory (ADR-0004 §1).
Writing an episode whose outcome is an internal fault would put debugging data in
the store the user inspects and the observer mines. Revisit if the observer turns
out to need failed turns; it is additive.

**Capture is deterministic recording, and it does not pass the propose/dispose
gate.** It writes to the store directly rather than through `MemoryWriter.ingest`.
ADR-0005's
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

**The strongest objection to this is that ADR-0005's Consequences say "every write
goes through a reviewable proposal → policy path", and its §3 hands `learning`
"feedback/observations" to turn into proposals.** Read at maximum breadth, capture
is an observation and this ADR is changing that decision rather than working within
it — which under ADR-0070 §1 would need a partial supersession, not a
reinterpretation. Three things answer it, and the third is the one that decides:

- **The rule's subject is a belief, and an episode is not one.** ADR-0072 §3 drew
  the line this ADR relies on, in its own words: "an observation is *evidence for*
  a belief and never the belief itself". What `learning` turns into a proposal is
  the belief it read *off* an observation; the observation is what the belief will
  cite. ADR-0005 §2 says so in the same breath, describing `evidence` as
  "references (e.g. episode ids)" — episodes were already, in ADR-0005's own
  design, the thing pointed *at* by the records that go through the gate.
- **The property the gate protects is untouched.** ADR-0005's stated worry is a
  model writing "arbitrary statements straight into permanent memory" (§Context,
  third problem) and its rule is that "memory is never written directly by the
  model" (§3). Capture asserts nothing about the user, infers nothing, and writes
  no model output as fact: it records that an exchange occurred and what was said
  in it.
- **Routing capture through the gate would destroy data, today, with the shipped
  policy.** This is not a preference. `MemoryIngestor._detect_conflicts` searches
  the store with `kinds=[record.kind]`, so an episode's "conflicts" are *other
  episodes* — and two turns about one subject are exactly what a similarity search
  returns. A `REINFORCE` ruling then merges them into one record at the target's
  id, and a `SUPERSEDE` closes the earlier turn's validity window and retires it.
  Either outcome erases part of a transcript, on machinery built for beliefs that
  contradict each other, applied to facts that cannot. Two things that both
  happened are never in conflict, and a write path whose whole purpose is to
  resolve conflicts is the wrong path for records that never have any.

So this ADR treats ADR-0005 §3 as governing the belief write path, which is what
its own vocabulary and its own conflict machinery are built for.

**That reading was rejected as a reading, and ratified as a decision.** ADR-0070
§1's test asks whether a reader would act differently, and a reader of ADR-0005's
Consequences would have routed an episodic write through the policy path — so the
gap was owed a supersession however good the argument for it was (#442). **ADR-0075
settles it**: it partially supersedes ADR-0005's proposal → policy write path for
the deterministic capture of an episode recording a turn, one producer wide, and it
merged before this ADR. The three arguments above are its Context and §4's evidence
is its §4. What remains here is a description of the path capture takes, resting on
a rule that now says so.

**What bounds capture instead is that it writes one record per outcome, judges
nothing (§4), inserts rather than upserts (above), and retains under a finite
default horizon (§7).** Unmediated is not unbounded.

**A captured episode's id is derived from the turn, not minted.** It is a function
of the conversation's id and the turn's ordinal — the two values the store has
already proved unique (§9's ordinal invariant, §1's insert-if-absent identity) —
so **two captured episodes cannot collide, by construction rather than by
probability**.

**The store allocates the ordinal and derives the id, in the append, and hands
back the turn.** Capture does not compute the id and does not predict the ordinal:
the ordinal is the store's to allocate (§9's invariant), so anything derived from
it is the store's to derive. A caller that guessed the next ordinal in order to
build the id would be re-deriving the invariant outside the seam that owns it, and
two engines guessing at once would build the *same* id for what the store then
makes two distinct turns — the collision the derivation exists to prevent,
reintroduced by the caller. So `ConversationStore.append` does the whole thing in
one operation — allocate, derive, write the intent — and returns the
`ConversationTurn` carrying the id capture must then write. The encoding is
therefore the store's, defined once behind the contract rather than agreed between
callers.

**Uniqueness among turns is not uniqueness in the store, so the encoding is a
reserved namespace.** `MemoryRecord.id` is an unconstrained string and the store
is shared: a sensor (leg 6) or a future capture source (#441) writes episodes of
its own, and nothing structural stops one from choosing a string this scheme would
also produce. So the derived form is **structurally recognisable and reserved to
captured conversation turns — no other producer mints into it**, which is a rule
about the id space rather than a contract change, and it is the kind of rule that
costs nothing while there is one producer and is unenforceable to retrofit once
there are three. Reserving it is also what keeps the *meaning* of a conflict
sharp (below): inside a reserved namespace whose leading component is a UUID4 this
hub minted, a collision is not bad luck, it is a producer breaking the rule or an
invariant already broken. This is what lets §8's intent log work: the index entry names the
episode id before the episode exists, and there is no minting step in between that
could have to be redone. A minted id would need a retry on collision, a retry
would need a *second* id in an index entry already written, and the contract would
owe an operation to re-point or abandon a turn — surface bought entirely to
survive an id scheme that did not have to be random. Nothing about a turn's
identity is a secret the id is protecting: the record is Tier 1 and reachable only
through the store that holds it.

**The write is still an insert, not an upsert.** Capture writes the episode as a
one-element `write_atomic` batch in `INSERT_IF_ABSENT` mode — **not** `add`, which
is a documented upsert keyed on the caller's id and would let a colliding id
silently replace an unrelated record. ADR-0046 §2 ruled this case for this reason
("a minted id that must not clobber an existing record", ADR-0045 §4) and is
explicit that "a batch of one is legal and degenerates to a single atomic write",
so capture needs no contract change to get it.

With a derived id the mode is a **guard rather than a routine path**, and it is
kept for what a conflict would then mean: an id derived from a unique conversation
and a store-proved ordinal collides only if the ordinal invariant has broken, or if
a foreign producer took an id in the reserved namespace (above). Both are faults,
neither is a race, and a retry answers neither. So a `MemoryStoreConflictError`
**fails the capture loudly** — degrading the turn, not the answer (§9) — and
nothing is retried.

**Capture is attempted once per outcome, and it is deliberately not
idempotent-by-replay.** A second attempt would take a second `append`, which
allocates a second ordinal and therefore a second id, so it would record the same
exchange twice rather than converge on one record. Making a replay collapse onto
the first turn would need a durable idempotency key on the capture itself — a
`TurnOutcome` identity that survives a restart, which nothing in the engine has
(a `ContinuationToken` is explicitly process-scoped). That is surface bought for a
retry this ADR does not perform: a failed capture is **reported, not re-attempted**
(§9), because the turn's answer is already delivered and a second write of an
exchange is a worse error than a missing record of one. A future capture that does
want to retry inherits the requirement rather than the freedom — it owes the key
first. That is ADR-0046's own posture where it already uses this
mode: the applier's insert-if-absent failure fails the whole batch, and nothing
retries under a different id. Two things follow: the episode id capture reports is
always the one its turn determines, so §8's compensation can never destroy a
record capture did not write; and "absent" is physical presence (ADR-0046 §3), so
an id colliding with an expired-but-unpurged row is refused rather than
resurrected.

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

**Turns are read through the index and fetched by id**, and an id that does not
resolve is **skipped, not an error** — whether it was deleted, expired, or is an
intent whose episode write never landed (§7, §8). A
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
default. The accepted cost is stated plainly and in two stages: **a conversation
whose turns have passed the horizon continues with no history**, its turns gone
from retrieval and export; and once the record itself is reclaimed, its id stops
resolving (§2).

**A belief may outlive its evidence, and this ADR does not close that.** ADR-0072
§3 already named it — "a retention deadline can end that" — and filed it. Capture
turns it from hypothetical into reachable, so what is added here is the gating, not
the answer: leg 3 may not populate the derived band without deciding what a belief
whose citations have expired renders, which is the same lane ADR-0073 §4 already
gates on. The question is not made easier by having capture guess at it now.

**The conversation record outlives its turns, and is reclaimed on the same
horizon.** A conversation is reclaimable when it has **no live turns *and* its
`last_active_at` is past the horizon** — both conditions, not the first alone.
Eligibility reads *activity*, not `last_turn_at`, so a continuation that is
underway protects the conversation even before its turn lands (§2). The
second is what keeps expiry from becoming the implicit end §2 refuses: with only
the first, a conversation whose single turn expired would be dropped while its
owner still held a working id, and the id would stop resolving as a side effect of
retention on the *content*. With both, a continuation re-activates a conversation
before it can be reclaimed, and a conversation is dropped only when nothing has
happened in it for the whole horizon and nothing of it is left to read.

The horizon is the same one the turns use (no second clock to disagree with the
first), read from the same setting, and the reclaim is the same sweep §8's
tombstone uses.

### 8. Deletion: unconditional, conversation-scoped, and ordered

ADR-0004 §6's right applies unchanged, and ADR-0073 §5's ruling extends to
episodes: **"the store deletes what it is told to delete"** (§5), and no
kind-conditional refusal is added, for the reason §5's rejected alternative gives
about a band-conditional one — "a store that can refuse a data-rights operation is
a store where ADR-0004 §6 is conditional".

**The conversation is a deletion unit, because it is the unit the user thinks
in.** "Forget this conversation" destroys the conversation's episodes and its
index. That spans two stores with no transaction between them, so the protocol is
ratified rather than left to the implementer — and it is ratified as a protocol
rather than as an ordering, because an ordering alone cannot make it hold.

**The index entry is written first, and it names the episode before the episode
exists.** Capture appends the turn and *then* writes the episode (§3). This is an
intent log, and it buys the one property the deletion needs: **no episode can exist for a
conversation without its id having been recorded in that conversation's index
first.** So an enumeration of the index names every episode that conversation will
ever have, including one whose write has not landed yet. The cost is that a crash
between the two writes leaves an index entry with no episode, which §5's read rule
already renders as a gap — the same thing a deleted turn looks like, and a great
deal better than the reverse, which is content no conversation admits to.

**Deletion is a tombstone, then a sweep, and the tombstone is the conversation
record itself.** Deleting conversation C:

1. **stamps C deleted** (a `deleted_at` on the record, §9), which is durable and
   refuses every later append to C;
2. **deletes every episode the index names**, including any whose write is still in
   flight — an id not yet present is a no-op, and the stamp is what stops it
   arriving unnoticed;
3. **drops the index and the record**, once step 2 has nothing left that resolves
   **and a bounded grace period has passed since the stamp** — the two conditions
   together, because "nothing resolves" is also true of an intent whose episode
   write has not landed yet.

A deleted conversation is gone from every read — `recent` never lists a stamped
record, and a continuation naming one is refused exactly as an unknown id is (§1).

**Steps 1–3 normally run to completion in the deleting call, and the tombstone is
what makes a crash survivable rather than final.** If the process dies at any
point, or a racing capture writes its episode after step 2, the stamped record and
its index are still there, still naming every episode id involved. So the
**reclaim** — the same sweep §7 gives the empty-conversation case, run by the
deleting call, at engine start, and later by the hub's scheduler (leg 5) — finishes
it: delete what the index names, then drop the record. It is idempotent, and it can
run any number of times.

**This is why the serialisation obligation sits on the store and not on a
caller.** An `asyncio.Lock` inside one `Engine` would not do it: the engine's own
code already contemplates "another engine over the same durable stores"
(`orchestration/engine.py`), so two engines — in one process or two — hold two
locks and serialise nothing. **`ConversationStore` therefore owes per-conversation
mutual exclusion between an append and a deletion as a contract obligation** (§9),
which every implementation satisfies in its own way: an in-memory store with a
lock, a SQLite-backed one with a transaction, which is also what makes it hold
across processes. Putting the obligation on the seam rather than on the caller is
the same reasoning ADR-0064 uses for the ordinal — an invariant a caller is
*asked* to maintain is an invariant that holds until a second caller exists.

**Compensation stays, as the fast path.** An append refused because the
conversation is stamped obliges capture to delete the episode it just wrote, so
the common case leaves nothing for the sweep to find. It is narrow deliberately: an
append refused for any *other* reason leaves the episode in place, because an
orphan episode is a true record of an exchange and deleting it would destroy data
on a transient store error. And because a captured episode's id is determined by
its own conversation and ordinal (§3), a compensation can never destroy a record
capture did not write.

**Capture verifies after its write, and that — not the clock — is the fence.** An
append that succeeded before the stamp is not evidence that the conversation still
exists when the episode write commits: the two are separate calls on separate
stores, and `write_atomic` awaits an embedder before it reaches its own lock, so
the gap is unbounded in principle. So the compensation rule is stated on both
edges: **capture re-reads the conversation after the episode write, and deletes
the episode it just wrote if that conversation is stamped or gone.** A refused
append (the deletion landed first) and a completed one (the deletion landed
mid-write) then have the same outcome, and neither depends on how long anything
took.

**The grace period widens the sweep's reach; it is not a bound and is not offered
as one.** No elapsed time proves that a suspended write cannot still commit —
`Engine.converse`'s timeout is explicitly "not an overall wall-clock deadline",
only a per-attempt budget (ADR-0029 §4, ADR-0042 §3), so nothing in this system
licenses "long enough". What the grace does is keep the tombstone — and with it
the only record naming a pending intent — alive past the deletion, so a capture
that commits and *then* dies is still swept when the reclaim next runs. The
tombstone's lifetime is a configured `timedelta` (the `confirmation_ttl` shape),
and the reclaim re-runs against it.

**What is left is one window, and it is accepted rather than claimed away.** It is
now the conjunction of two failures rather than a duration: a capture must commit
its episode *and* fail or die before its verification, *and* the tombstone must
already have been reclaimed when it does. Three things are true about it, and all
three are why this ADR accepts it:

- **No protocol over two stores closes it.** Every ordering, tombstone or handshake
  moves the window; only a transaction spanning both stores removes it, and there
  is no seam that spans them. Adding one — or collapsing the conversation index
  into `MemoryStore` to get its transaction — is a change to the memory contract
  made for a failure mode with no reachable instance.
- **The reachable version is already gone.** A capture and a deletion of one
  conversation cannot overlap through anything shipped: one process, one client,
  one command at a time (roadmap stance 3). Where they *can* overlap — two engines
  over shared stores — the append is serialised against the deletion by §9's
  store-level exclusion, and a write that slips past it is caught by the
  verification above. What is left needs the verifying process to die in the
  interval between two of its own calls, on the one conversation being deleted.
- **The residue is visible and destroyable, not invisible.** The episode is a
  record like any other: it appears in `assistant beliefs --kind episodic`, in
  `export`, and `forget` destroys it. What is lost is the automatic sweep, not the
  user's reach.

This is the disposition ADR-0073 §5 already took for its own two-call window —
name it, bound it, say what would close it, and decline to ratify the primitive
that would. **What closes it is named**: a transactional posture across the local
stores, which is leg 5's "stores' concurrent-access posture" hardening tail, due
with the process model that makes two writers real (§11).

**Between the stamp and the reclaim, the tombstone itself is a residue**:
ordinals, timestamps and episode ids — **no content** — surviving a deletion the
user was told succeeded. It is bounded by the grace and by the reclaim running in
the deleting call, at start-up, and later on the hub's schedule. Holding the index
in memory instead would remove it and take the crash-safety with it, which is the
worse trade.

**Deleting one episode is deleting one record**, through the surface leg 1 already
shipped (ADR-0073 §5's show-then-confirm, with its window named and accepted). The
conversation-scoped form obeys the same ceremony: what will be destroyed is shown
before consent is taken, in a form a human can judge — for a conversation, the
count and span rather than every turn.

### 9. The contract surface owed, and why it is a new store

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/types.py`** gains `Conversation` (the identity, `started_at`,
  `last_active_at` — always set, refreshed when a turn begins, and the key every
  listing and the reclaim read — `last_turn_at`, **optional and unset until a turn
  lands**, and `deleted_at`, the tombstone stamp of §8, likewise optional; §2) and
  `ConversationTurn` (the conversation it belongs to, its ordinal, the id of the
  episode that records it, and when it occurred).
  Both frozen pydantic models (ADR-0068), both timezone-aware at every instant
  (ADR-0023, ADR-0030).
- **`core/protocols.py`** gains **one** Protocol, `ConversationStore`, owing:
  start a conversation, inserting only if the minted id is absent and retrying on
  collision (§1); read one by id; append a turn — allocating its ordinal, deriving
  its episode id, and returning the `ConversationTurn` that names both (§3);
  read a conversation's turn tail, bounded and ordered; read recent conversations,
  bounded and ordered by `last_active_at` (§2); mark a conversation active (§2);
  resolve an episode id back to the
  turn that cites it (§10 declines duplicating that relation onto the record, so
  the store owes both directions); stamp a conversation deleted (§8); export; and
  reclaim — the sweep that finishes a stamped deletion and drops a conversation
  that has no live turns *and* has been idle past the horizon (§7, §8).
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

   **What that buys, stated exactly, because the overclaim is tempting:** two
   appends land in one unambiguous order that every reader agrees on, and neither
   can silently take the other's position. It does **not** detect that an appender
   planned against a tail that has since moved — two clients that both read
   through ordinal 7 and then append are serialised as 8 and 9, and the store has
   been told nothing that would let it refuse the second. Detecting *that* needs an
   expected-tail argument on append and a conflict error to go with it, which is
   ADR-0046 §5's deferred compare-and-swap wearing this ADR's hat and is deferred
   with the same consumer (§11). The ordinal is what makes such an argument
   expressible later — there is a value to compare against — which is the sense in
   which this decision does not foreclose it.
2. **Every read is bounded by default and totally ordered** (ADR-0021 §4, ADR-0073
   §2): turns by ordinal ascending, conversations by last activity descending with
   the id as tie-break (§2).
3. **A conversation's mutations are mutually exclusive at the store, all of them**
   (§8): an append, an activity mark (§2), a deletion stamp and a **reclaim** of one
   conversation never interleave. An append to a stamped conversation is refused,
   and a stamped conversation is absent from every read.

   **The reclaim is inside that set, not beside it**, and it re-checks eligibility
   while holding the exclusion — because eligibility is a claim about state that an
   append or an activity mark changes. Deciding "no live turns, idle past the
   horizon" and then dropping the record in a separate step is how a reclaim
   destroys a conversation a user has just come back to. The boundary is therefore
   decided rather than left to whoever wins: an activity mark that lands first
   makes the conversation ineligible and the reclaim skips it; a reclaim that lands
   first drops the record, and the continuation behind it is refused at the *start*
   of its turn (§1) — before any work, before any answer, which is the loud refusal
   §1 already specifies rather than an answer the user loses.

   This is an obligation on the *seam* precisely because a caller-held lock does
   not survive a second caller — the engine's own code already contemplates
   "another engine over the same durable stores".
4. **The standing module clauses bind it** like every other Protocol: input
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
   **a conversation with no turns ordered beside one that has them** (§2 — the case
   a suite built only from conversations that have turns never reaches, and the one
   that catches a store sorting on `last_turn_at`), the bounded defaults, an unknown id refused rather than
   created (§1), an unresolvable episode id skipped rather than raised (§5),
   detachment, and input observation. A suite that only exercises small explicit values will not reach
   the ordinal invariant or the defaults; the argument ADR-0073 §8 makes about
   `offset` and about the default `limit` applies here unchanged.

   **The cross-store protocol is not testable there, and is owed its own tests.**
   A conformance suite exercises one store against one contract; §3's insert, §8's
   ordering, its compensation and its serialisation span two stores and the stage
   between them, so they are the *capture stage's* tests, in `tests/orchestration/`,
   against injected doubles rather than in the shared suite. Every one of the
   following is a case where the guarantee is either kept or silently lost, and
   none of them is reachable from a suite that only writes successfully:

   - **Two appends to one conversation deriving distinct episode ids**, asserted
     on the returned `ConversationTurn`s — the clause that catches an
     implementation deriving the id from anything it does not allocate under the
     same exclusion (§3).
   - **An episode id that is already stored** — capture fails loudly and
     overwrites nothing (§3), including when the occupant is a *foreign* record
     that took a reserved-namespace id, which is the case the reservation rule
     forbids and the guard exists to catch. With a derived id this is a broken invariant rather
     than a routine collision, which is exactly why the test asserts a refusal and
     not a retry. **A colliding conversation id** is the live case on the other
     store and belongs in the conformance suite (§1): a repeating injected factory
     must not overwrite a conversation, must not hand back someone else's, and must
     raise `ConversationStoreError` when the retry budget is exhausted.
   - **An append refused because the conversation is gone** — the compensating
     delete runs, and it deletes the episode capture just wrote and nothing else.
   - **A deletion that lands while the episode write is in flight**, so the append
     succeeded and the conversation is stamped by the time the write commits — the
     post-write verification destroys the episode (§8). This is the case elapsed
     time cannot decide, so a test that only exercises the refused-append edge
     leaves the fence untested.
   - **A compensating delete that itself fails** — the turn still returns its
     answer, and the failure is reported rather than swallowed (§9.6).
   - **An interruption between the two writes**, in each order, asserting the
     residue each case is ratified to leave (§8): an orphan episode after a
     capture, a re-runnable deletion after a deletion.
   - **A reclaim racing a continuation** — a conversation eligible for reclaim
     (no live turns, idle past the horizon) that is continued at the same moment:
     asserting the boundary §9.3 ratifies in both directions, since a reclaim whose
     eligibility is decided outside the exclusion passes a single-threaded test and
     destroys a conversation the user just returned to.
   - **A capture and a deletion of the same conversation issued concurrently** —
     asserting they serialise (§8) rather than interleave. **Through two `Engine`
     instances sharing one pair of stores**, not one: a lock held by a single
     engine passes the one-engine version of this test and fails the topology the
     engine already supports, which is the fault this clause exists to catch. The
     store-level obligation belongs in the conformance suite too, so every
     implementation is held to it rather than only the wiring.
   - **A racing capture that lands its episode after a completed deletion, inside
     the grace** — asserting the reclaim finds and destroys it, because the stamped
     record and its index are still there naming it (§8). **And the same landing
     after the grace**, asserting the accepted residue rather than a guarantee the
     protocol does not provide: the test pins what this ADR decided, so a later
     reader finds the window in the suite rather than rediscovering it. And **a
     reclaim run twice**, to pin idempotence.
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
  relation, on a type that is general to episodes from any source — and the field
  that would have made "episode = turn" true by construction, which #441 asks leg 2
  not to do (§3).
- **Writing the episode with `MemoryStore.add`.** §3. A blind upsert under a
  freshly minted id can replace an unrelated record, and `INSERT_IF_ABSENT` for
  exactly this case is already ratified (ADR-0046 §2).
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
  Not foreclosed, and partly already answered: §9's ordinal is allocated and proved
  by the store, so concurrent appends land in one agreed order rather than an
  ambiguous one, and §8's exclusion between an append and a deletion is a store
  obligation rather than a caller's lock, so it holds for two engines over one pair
  of stores. What is deferred is what needs a *stale* appender to be detectable — an
  expected-tail argument on append, and the policy for refusing one (reject,
  re-order, or branch). That is ADR-0046 §5's deferred compare-and-swap (#248) in
  this ADR's clothes, and it becomes a real question with the second spoke.
- **A transactional posture across the two local stores**, which is what would
  close §8's last window — an episode landing after its conversation's tombstone
  was reclaimed. Deferred to leg 5, whose hardening tail is named as "the stores'
  concurrent-access posture" and whose process model decides what a second writer
  even is. Not foreclosed: §8's protocol is a sequence of ordinary store calls, so
  a transaction spanning them would subsume it rather than replace it.
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
- **Who triggered an episode's retention** — the user asking for a moment to be
  kept, versus the assistant deciding to keep it. #441 records this as a
  distinction a later rung will need, and it is deliberately not designed here:
  there is one producer, it is deterministic, and everything it captures is
  triggered by the user having a conversation, so a field distinguishing the two
  would today hold one constant. Nothing forecloses it — the trigger is a property
  of the *episode*, and `EpisodicMemory` can carry an additive field (or
  `Provenance` can, where the lane argues the distinction is provenance rather than
  payload) without touching this ADR's decisions, because membership is by index
  (§3) and capture stamps no field the trigger would contradict (§4). What that
  lane must not do is infer the trigger from the band: `OBSERVED` says the
  assistant witnessed something, and says nothing about who asked for it to be
  kept.
- **Every sensor-side question #441 raises** — ephemeral buffers, wake phrases,
  transcription, distillation, and the salience classifier. Out of scope by that
  issue's own terms, and untouched here beyond §3's ruling that an episode need not
  belong to a conversation.
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

- **Leg 2's exit test is met by what ships**, with its guarantee stated where it
  holds: a conversation has a durable, device-agnostic identity that any client can
  continue by id, and every turn is durably recorded and leaves an `EpisodicMemory`
  an observer can cite by id — **durable index, best-effort episode** (§3). A
  memory-store failure leaves that turn a gap with nothing to cite, reported on the
  outcome; the exit test is "episodes exist that an observer could cite", not "no
  turn is ever missing one", and no two-store design can promise the stronger form.
  The observer does not exist yet, and the substrate is correct without it — the
  same shape leg 1 landed in (a correct surface over an empty band).
- **The contract owed is one Protocol, two types, and one error class.** No
  existing Protocol changes, which is the smallest surface this leg could have
  needed and is only possible because ADR-0005 already typed episodic memory and
  `Planner.plan` already takes records.
- **The episode stays source-agnostic**, and #441's leg-2 constraint is carried
  rather than declined (§3). It costs nothing here because it is the *absence* of a
  field: an episode belonging to no conversation is the default shape, so the first
  non-conversational producer adds a source, not a migration.
- **Capture is the first producer into the derived band**, arriving ahead of the
  observer. That is stated rather than discovered, and it is why §4 answers
  ADR-0072 §3's two obligations explicitly instead of leaving the next lane to
  infer that a transcript is a belief.
- **The propose/dispose gate keeps its scope, and the exemption is ratified rather
  than assumed.** Capture writing directly was first offered as a *reading* of
  ADR-0005 §3; both Codex personas rejected it and #442 was adjudicated against it,
  so the exemption is now an explicit partial supersession (ADR-0075) that merged
  ahead of this ADR. The gate is unchanged for every other producer — every belief
  write in every band, and leg 3's observer above all — which is what ADR-0075 §2
  pins. The episode-folding evidence that decided it (§3) survives as the reason
  the gate was wrong for this class rather than merely skipped.
- **Two shipped surfaces are deliberately narrowed** (§6) on the day capture lands,
  and the narrowing is invisible today because nothing writes an episode. Had it
  not been decided here, the first capture lane would have changed what every turn
  retrieves and what `assistant beliefs` prints, as a side effect nobody ratified.
- **Selective memory survives contact with a transcript** — because episodes are
  given a shorter life than the beliefs distilled from them, not because capture is
  made stingy. The cost is real and named, in two stages: a conversation whose
  turns have passed the horizon continues with no history, and one that has been
  idle for the whole horizon is reclaimed and its id stops resolving (§2, §7).
- **"Every turn is captured" is a guarantee about the turn, not about its
  content.** The index entry is durable; the episode is written right after and can
  fail, leaving a gap the outcome reports (§3). Stating it that way is what keeps
  the ADR from promising an atomicity two stores cannot give, and it costs nothing
  a reader did not already have to handle — a gap is what a deleted or expired turn
  looks like too.
- **A resumed conversation can show gaps**, from a deleted turn or an expired one
  (§5, §7, §8). That is the deletion right working, and it is the one behaviour
  a "restore my history" instinct would break.
- **Deletion across two stores is a protocol, not an ordering** (§8): an intent
  log, a durable tombstone, a sweep that finishes it, and a store-level exclusion
  between an append and a deletion. That is more than an ordering rule, and the
  reason is that an ordering cannot hold — a crash or a racing capture leaves
  content a completed deletion could no longer find, and a data right that depends
  on a best-effort cleanup completing is not a right. The residue is bounded and
  content-free: ids, ordinals and timestamps, until the sweep runs.
- **One window is accepted rather than closed** (§8), and it is a conjunction of
  failures rather than a duration: a capture commits its episode, dies before the
  verification that would have destroyed it, and the tombstone that would have
  named it has already been reclaimed. No two-store protocol closes that, only a
  transaction spanning both, and the reachable instance is already excluded by the
  store-level serialisation, the post-write verification, and there being one
  client. It is stated, tested as the residue it is, and handed
  to leg 5 with the concurrent-access posture it belongs to — the disposition
  ADR-0073 §5 took for its own window.
- **The obligation landed on the seam rather than on the engine**, which is the
  correction that mattered most in review. A lock inside one `Engine` would have
  looked correct and served nothing: the engine already contemplates another engine
  over the same durable stores, so the guarantee had to be the store's or it was
  nobody's.
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
  Rejected in §3, and it is the alternative with the strongest claim on this
  decision — it is the ratified path, and taking it would need no argument about
  ADR-0005's scope at all. It loses on evidence rather than on principle: the
  shipped ingestor detects conflicts within the proposal's own kind, so episodes
  conflict with episodes, and the fold rulings that follow (`REINFORCE` merges at
  the target's id, `SUPERSEDE` closes the target's window) would silently destroy
  or retire turns that happened. A `REJECT` would discard an interaction the user
  had, and every capture would pay for a similarity search whose answer is
  meaningless. Revisit if a policy is ever written that refuses to fold an
  `EPISODIC` record — which is a decision for the lane that owns the policy, and is
  the constraint §4 already places on it.
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
- **A permanent registry of every conversation id ever issued, so a reclaimed id
  can never be minted again.** Rejected, and the reason is the one this ADR spent
  its deletion protocol on: a durable record of every id the user has *deleted*,
  retained forever, is precisely the residue §8 exists to reclaim. It would buy
  protection against one thing — an id factory that repeats — which is not a
  property of the ratified scheme (UUID4, §1) and is not guarded against anywhere
  else in this system: goal, plan, step, execution and decision ids are all minted
  by the same injected factory with no registry behind any of them. `start`'s
  insert-if-absent (§1) covers the case that matters, a collision with a
  conversation that *exists*; a collision with one that was destroyed at the user's
  request is a broken factory, and the answer to a broken factory is not to keep
  the user's deleted data as an index of what not to reuse.
- **Serialising capture against deletion with a lock inside the `Engine`.**
  Rejected in §8, and it is worth recording because it was this ADR's first
  answer. It reads as sufficient — one process, one loop — and it is not: the
  engine's own recovery path is written for "another engine over the same durable
  stores", so two engines hold two locks and exclude nothing. A guarantee about
  durable state belongs to whatever owns the durable state.
- **An ordering rule alone — episodes first, index second — with a compensating
  delete.** Rejected in §8. It survives a *failed* deletion and not a completed
  one: a capture that writes its episode after the enumeration, and then crashes
  before compensating, leaves content no re-run can find, because the index that
  would have named it is gone. The tombstone exists precisely so that the record
  naming the orphan outlives the deletion.
- **Letting the client mint the conversation id.** Rejected in §1. It makes
  collision the hub's problem to arbitrate and lets a client name an id it was
  never given.
- **Starting a fresh conversation when an unknown id is presented.** Rejected in
  §1. It converts a typo or a stale id into a silently lost continuation, which is
  the failure mode a user cannot diagnose.
