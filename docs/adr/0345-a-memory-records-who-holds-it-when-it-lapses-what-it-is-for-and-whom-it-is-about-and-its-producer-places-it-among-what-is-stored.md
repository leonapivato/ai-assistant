# 345. A memory records who holds it, when it lapses, what it is for and whom it is about, and its producer places it among what is stored

- Status: Partially superseded by ADR-0348 (§3, in the addition alone; §5's `recheck` row and §5:9; §8:1, in "kept or took on"; §15:2's worked example, in step 3's holders, and its case of an answer that adds no support) and ADR-0351 (§2's table, its first and fourth rows and its limit on an `outside_input` support's holder; §2:2, in the addition alone; §2:1 and §2:8, in the addition alone: the relay mark) and ADR-0356 (§8:3's and §12:4's *a round's message*, in the addition alone: a message call's message)
- Date: 2026-10-21
- Scope: the memory record and the write path a placed proposal takes. Who holds each support, the assistant's messages as statements it made and never as its beliefs, backing only a record of what it said, and the rule that a memory is changed only in its own holder's beliefs; a proposal that names how it stands to each stored memory its producer retrieved, and the write that follows from it; a validity end set at creation; situation labels; marks; a producer for `about_person` and a search filter on it; the retirement of `topics` from the memory; and the upgrade. The observer's use of all of it, what it reads, its steps and its calls, is the second decision of this walk.
- Dependency: ADR-0328, ADR-0329, ADR-0336, ADR-0217, ADR-0219, ADR-0045, ADR-0100, ADR-0213, ADR-0326 and ADR-0338, as their status lines leave them.
- Authorization: the owner ruled this design in the observer walk of 2026-10-21, in the observer-and-learning fork, and directed it be written ("I think we get started"). This decision writes those rulings down and settles only what they leave open, each such point named where it is settled. The number is provisional until the owner assigns it (`CONTRIBUTING.md` → "ADR numbers are assigned at dispatch"). The owner reads it before it is ratified (§1:1).
- **Contract-surface decision.** It changes `core/types.py` (`MemorySupport` gains its holder; the memory gains labels, marks, `subjects` and `involved`, and loses `topics` and `about_person`; `MemoryUpdateProposal` gains a placement; the projections gain holders, labels, marks, the people a memory is about and a future validity end) and `core/protocols.py` (`MemoryStore.search` gains a person filter; `MemoryWriter.ingest` writes a placed proposal by §5; `MemoryWriter` gains a label write). It is a breaking change under golden rule 5.
- **Partially supersedes**, in the clauses §16's table names: ADR-0100, ADR-0213, ADR-0328, ADR-0329, ADR-0336 and ADR-0338.
- Partially superseded: 2026-10-25 by ADR-0348 — §3, in the addition alone: where a placed write installs a memory, a counted `against` support on it whose holder backs it, from a part earlier in the record's order, stops counting (ADR-0348 §3). §5's `recheck` row and §5:9: a `recheck` raises no question on a memory that already holds an open one, and a named answer resolves its question citing a backing support the memory carries once the write is applied (ADR-0348 §4). §8:1, in "kept or took on": a person takes a statement on by agreeing with or confirming it, and a request to keep alone keeps a record of the saying (ADR-0348 §2). §15:2's worked example, in step 3's holders: M5 is held by the page alone, with the owner's request cited (ADR-0348 §2). §15:2's case "an answer whose relation adds no support leaves the question open": the question stays open only where the memory carries no backing support of the answer (ADR-0348 §4). Every other clause stands. This replacement takes effect on ratification of ADR-0348. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-25 by ADR-0351 — §2's table, its first and fourth rows: a support pointing at a recorded message is held by that message's party, and one pointing at the input as a whole by its one party where it has exactly one, and by unknown otherwise (ADR-0351 §7:1); and its limit on an `outside_input` support's holder: it may be an outside source marked established (ADR-0351 §7:4). §2:2, in the addition alone: `StatementPart` gains a member for the instruction a scheduled task carries (ADR-0351 §3:7). §2:1 and §2:8, in the addition alone: a support pointing at an input understanding marks as carrying words its sender did not write themselves, or a message of it, is held by unknown, and that relay mark, which code reads from the episode, makes a holder unknown and nothing else (ADR-0351 §7:5, §7:6). Every other clause stands. This replacement takes effect on ratification of ADR-0351. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §8:3's and §12:4's *a round's message*, in the addition alone: a support pointing at the message one message call sent, as `MessageCallPart`, counts for §8:3's check and is cited under §12:4 with its call, as `StatementCitation.call_id`, so two messages of one round are cited apart (ADR-0356 §13:3). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### What the owner ruled

The walk started from the observer and reached the record it writes. These rulings
shape the record.

- **Capture is not usage.** On a home device that knows who is talking, the owner
  says Sam can't be trusted with something and Sam says Sam can: "both statements
  should be into the system with the provenance … there's a difference between
  capture and usage. And so now we have to just make sure the capture is right."
  Which statement governs is usage's question, by topic and by who is asking. The
  record's job is to hold enough that usage can decide.
- **A memory is a belief someone holds.** "If I say the wall is red and Sam says the
  wall is blue, is that really contradictory? No, because it's saying I believe the
  wall is red, Sam believes the wall is blue. Both are true." A contradiction exists
  only inside one holder's beliefs over time. The owner agreed that a holder retires
  only their own backing, and asked to keep the existing ranking as usage's default:
  recall that prefers what the owner said ("maybe a recall does a filtering for
  statements made by the owner first").
- **A holder is a connection, and never a claim.** "It's not the identification that
  matters here, it's the connection": two parts under one stable identifier are one
  holder, and the person behind it can be linked later. A forwarded "message from the
  user", a screenshot, or Sam saying "the user agrees with me" stays Sam's: only an
  identity the channel establishes holds a person's belief.
- **A contradiction is kept beside, as evidence against.** Nobody's word removes another
  holder's belief by rule. A claim against a memory from someone who does not hold it is
  installed beside it and recorded on it as evidence against.
- **No beliefs of the assistant's own, for now.** After the owner's worry that an
  advertisement could convince the assistant and, through it, the user, long-term memory
  holds only what people and sources believe. The assistant's message is a statement it
  made, "the source of I stated this at this time in this chat, not that I believe this",
  and never a
  belief it holds. Where a person keeps something the assistant said with nothing behind
  it, the memory cites what it can, the assistant's message: "make it not that there's no
  source. Instead, it should cite what it can." With the assistant holding nothing, there
  is nothing to convince it of; convincing waits for a decision on its standards of
  belief.
- **The assistant's word is a source; its weight is usage's.** The danger is a loop: "it
  might say something like the best car is x, and then if I ask why it thinks that, it
  might say because I said it in this chat." The owner put the answer in usage, not
  capture: "the assistants words can still be a source, its just one with low credit in
  many cases. As other sources can be too." What the assistant said may be kept as a record
  of the saying, true as worded and backing nothing beyond it.
- **A person is a kind of source.** "Person is a type of source, no?" One holder, of
  several kinds, under one set of capture rules.
- **The commit step frames, then places.** The new memory's wording and metadata come
  from what it rests on alone, without the stored memories: "I don't see why
  information about what's already in the store should affect how it frames the
  memory". Then "code mechanically retrieves similar memories. It doesn't have to be
  capped at 5", and "for each one, the model can decide … some sort of enum on its
  relationship". The owner agreed the closed set §4 adopts, with "weakens" and
  "recheck" kept apart.
- **No kinds; labels and marks instead.** A kind field was rejected: "there's so many
  memories that linger between two or three kinds", and "for plan, isn't that
  time-bounded stuff covered by the validity window". In its place, free-text labels
  "attached to the memory … for a separate kind of recall that is a semantic search
  over labels instead of the content", with "some minimum semantic search distance"
  against near-duplicates at write, and a writer free to "reorganize the labels".
  Machine-filterable values such as a one-time occasion are a separate closed field
  (agreed as "D22 confirmed").
- **Writes stay safe without new machinery.** "We have to make sure it's also async
  safe", then "unless I'm wrong, it doesn't need to write at the same time safely":
  the observer is the one writer and runs one run at a time, so the existing guards
  are the whole answer (§11).

Two more rulings set what the record carries: the scout extracts whom a memory is
about from the episode, and a memory's sensitivity is a placement the scout proposes
(the observer's decision, §9 here only names the producer).

### What is there today

Surveyed at `15e62f08`.

- **A support carries an origin but no holder** (ADR-0328 §4). The origin table says
  how the part reached the assistant: the user's message, a confirmation, a source's
  evidence, the assistant's words, an inference. Who held the belief is implicit: the
  user's message is the owner's, since the owner is the only person whose input any
  channel admits (`orchestration/telegram.py` takes input only from the configured
  account; the hub chat and the web door admit only the owner's devices and sign-in).
- **Retirement follows a ranking across origins.** ADR-0328 §6:5 refuses a retiring
  operation whose cited support ranks below the memory's standing.
  `DefaultMemoryPolicy` (`memory/policy.py`) rules over the reconciler's relations by
  band: an asserted proposal supersedes a derived or attested member it contradicts
  (its rule 9, ADR-0336 §3(b)).
- **The relation is judged inside the write path.** `MemoryIngestor` invokes a
  reconciler model on every admissible unconfirmed ingest (ADR-0336 §2:1), labelling
  each member of a similarity-cut conflict set `RESTATES`, `ADDS` or `CONTRADICTS`
  (`ConflictRelation`). The observer's commit step has already chosen an action over
  up to five similar memories it was shown (ADR-0329 §9:3), so the same question is
  answered twice.
- **A validity end cannot lie in the future.** ADR-0328 §5:10 refuses an end whose
  about-when lies after the operation's instant: "a claim that holds until a later
  time is worded so". Nothing then knows the claim has lapsed.
- **`about_person` and `topics` have no producer** (ADR-0328 §3:6). `topics` is
  ADR-0213's canonical exact-match tag list.
- **`MemoryStore.search` ranks by relevance alone** over the content, filtered by
  kind and band.
- **Style marks and pin suggestions** live in the person-model store (ADR-0338 §9:4,
  §9:5).
- **A digest records no source identity.** No part the observer reads carries an
  `Attestation`, so evidence from a search or a page names no source (the observer sets
  none, `orchestration/observer/commit.py`).

### Words

A **holder** is the party whose belief a support records (§2). A **placement** is a
producer's statement of how a proposed memory stands to each stored memory it
retrieved (§4); a proposal carrying one is **placed**. A **situation label** is a
free-text descriptor of when or for what a memory matters (§7). A **mark** is a member
of a closed set describing the memory itself (§8). A memory's **holders** are the
holders of its counted `for` supports that back it as worded (§2:10). **Standing**,
**support**, **origin**,
**operation** and **counted** are ADR-0328's.

## Decision

We will record, on every support, who holds the belief it records, and change a memory
only in its own holder's beliefs. A producer that has retrieved the stored memories
similar to its proposal names how the proposal stands to each, from a closed set, and
the writer derives the write from those relations by rule, with no reconciler and no
ranking across holders. A memory may carry a validity end in the future, situation
labels, marks and whom it is about, and stops carrying `topics`.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> read it, has authorized its ratification. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137, as
> §15 sets out, and each lane keeps the gate green.

### 2. Who holds a support

| What the support points at | Its holder |
| --- | --- |
| The input or one of its messages, where the input's `InputOrigin` is `USER` and the message carries no `forwarded_from` | The person who sent it: the owner, today |
| A confirmation | The person who gave the yes: the owner, today |
| A pin (ADR-0338 §4:4) | The person who made the pin |
| A message carrying `forwarded_from`, or an input whose `InputOrigin` is `OUTSIDE` | A claimed source: the forward's claimed original sender where the trigger records one (`ClaimedAuthor`), held as claimed, and otherwise unknown |
| An evidence item | The source the record names: its digest's `Attestation.reported_by` where the record states one, and otherwise unknown |
| A round's message, a remember call, or an observer's inference | The assistant's statement: what it said or inferred, where and when |
| A legacy record | Unknown |

> **Normative.** Every support records its holder, set by code from the part it points at
> and the episode's record, as the table rules. No model's output sets or changes a
> holder.

> **Normative.** A holder is the source of the claim a support records, and is one of four
> kinds, a closed set added to and never renamed: a person, named by an identifier; an
> outside source, named by an identifier and marked established or claimed; the
> assistant's statement, naming the part it made, a round's message, a remember call or an
> observer's inference; and unknown. Every kind is held
> under the same capture rules.

> **Normative.** A holder of the kind the assistant's statement records that the assistant
> said something, where and when, and never that it believes it. The assistant holds no
> belief, and nothing in this decision changes, retires or keeps a memory on the ground
> that the assistant believes anything.

> **Normative.** Until a decision on the assistant's standards of belief decides otherwise,
> a support whose holder is the assistant's statement backs one memory alone as worded: a
> record of the saying, which states what the assistant said, where and when, and is
> marked `assistant_statement` and `occasion` (§8). While ADR-0329 §9:7 stands for the
> observer's own writes, the inference it has the observer create, backed as worded by an
> `observer_inference` support, is the one other. On any other memory it is cited, as `for`
> or `against`, never backs it, and never makes the assistant a holder of what it said.

> **Normative.** Until a decision on identified people adds others, the one person a
> holder names is the owner, and the identifier that names the owner is a
> composition-root constant.

> **Normative.** A holder is named by the stable identifier the record carries for whoever
> said or reported the part, whether or not that identifier resolves to a known person:
> `Attestation.reported_by` for an evidence item, and the claimed sender's identifier for
> a forward. Two holders are the same holder exactly where they name the same identifier,
> and connecting two parts to one identifier is enough, with no identity behind it. A
> part whose record carries no identifier has an unknown holder, which is never the same
> holder as any other.

> **Normative.** A person holder is named only by an identity the channel itself establishes
> for whoever sent the part (ADR-0323 §4:2). An author the part only claims, in a forward,
> a quotation or a report, names a claimed source holder, which is never the same holder
> as an established one, whatever identifier either carries, and becomes the same only by
> the owner's act linking the two.

> **Normative.** A holder is set from who sent or reported a part, never from what the
> part says. A part claiming what another person believes is held by whoever sent it.

> **Normative.** A support keeps the identifier its holder was recorded under, and no write
> rewrites it. Which person an identifier belongs to is a link held outside the support,
> by a later decision on identified people. Once such a link exists, every support
> carrying that identifier is attributed to that person without being rewritten, and two
> holders whose identifiers link to the same person are the same holder in every write
> made after the link.

> **Normative.** A memory's holders are the holders of its counted `for` supports that back
> it as worded, and its partial supporters are the holders of its other counted `for`
> supports. Both are values ADR-0328 §7 computes from the stored record, never stored as a
> judgment, and a partial supporter is never shown as holding the memory.

> **Normative.** A memory's standing stays as ADR-0328 §6 computes it. It says how the
> memory's backing reached the assistant, and in a placed proposal's write (§5) it ranks
> no holder above another.

**Why only an established identity holds.** Sam forwarding a text "from the user", or
showing a screenshot of one, or saying "the user agrees with me", must never make a belief
the user's. Each is held by Sam, with the claimed author recorded as a claimed source. What
the user believes comes only from the user's own words on a channel that establishes them.

**Why a holder beside the origin.** The origin says how a part reached the assistant;
the holder says whose belief it is. Today they coincide, because only the owner speaks,
and the table maps every origin to one holder. They part once a device knows who is
talking: Sam's message to a home speaker is a person's direct word, with an origin like
the owner's and a different holder. Recording the holder now, while it is always
derivable, costs one field and spares an upgrade that would have to guess.

**Why the assistant's word backs only a record of the saying.** The assistant's message is
a source like any other, and how much it counts for is usage's. What sets it apart is that
the assistant is the one source that reads memory. Kept as its claim, "X is the best car"
would be recalled, said again and kept again, until the answer to "why?" is "because I
said so". Kept as a record of the saying, "On Oct 20 the assistant said X is the best car
for the user's commute", it is true as worded and says nothing of whether X is right;
saying it again makes a second record, never more weight. No other holder's word ends
it, since it stays true that it was said (§3).

### 3. A memory changes only in its holder's beliefs

> **Normative.** In the write a placed proposal yields (§5), a retiring relation adds the
> proposal's backing supports to the stored memory it names as `against`.

> **Normative.** The proposal's backing supports, in the clause above and throughout §5,
> are its counted `for` supports that back it as worded, and its first backing support is
> the first of them.

> **Normative.** A retiring relation changes the stored memory only through the counted
> supports on it whose holder is a holder of one of the proposal's backing supports: each
> such support stops counting, by one stop counting each, citing that holder's backing
> support. No other holder's support on it changes.

> **Normative.** The stored memory is retired in the same atomic write, by the operation the
> relation names (§5), exactly where no counted `for` support backing it as worded remains
> on it. The operation cites the proposal's backing support that the last stop cites, or,
> where the write stops none because nothing backed the memory already, the proposal's
> first backing support. A memory some other holder still holds stays current.

> **Normative.** A stored memory a retiring relation leaves current has its remaining
> counted backing supports added as `against` in the same write to the proposed memory
> where it is installed, and otherwise to each memory it is folded into (§5:3), so the
> dispute is recorded on both memories.

> **Normative.** ADR-0328 §6:5's refusal by standing does not bind the write a placed
> proposal yields. The clauses above are its guard.

> **Normative.** Where a `restates` folds a proposal into a stored memory (§5:3), each
> counted `against` support on that memory whose holder is a holder of one of the
> proposal's backing supports stops counting, citing that holder's backing support: a
> holder's new word on the whole claim ends their own dispute with it. A `contained` fold
> stops nothing, since its proposal states only part of the claim.

> **Normative.** A confirmation support, a `pinned` support and an `observer_inference`
> support are also added where §3:1 or §3:5 records a dispute, as `against` and backing
> nothing, besides where ADR-0328 §4:6, ADR-0338 §4:5 and ADR-0329 §9:7 allow them.

**Why per holder.** A stored "the wall is red" held by the owner and a new "the wall is
blue" held by Sam are both true as beliefs. Retiring either would destroy a fact about
what someone believes, on a ranking that usage, not capture, should apply. Inside one
holder's beliefs a change is real: the owner's "I eat meat again" ends the owner's
"vegetarian", and a page that updates ends what that page said.

A memory held by several people, Sam's and Tom's "blue", outlives one of them changing
their mind: Sam's support stops counting, Tom's keeps it current.

**Saying something, and what the assistant said.** Nobody's word removes another holder's
belief by rule: saying something records the speaker's belief, and adds it to what it
contradicts as evidence against, so the dispute is visible from either memory. The
assistant's messages are statements it made, not beliefs it holds, so there is nothing of
the assistant's to convince or overrule. Whether the assistant should ever hold beliefs,
and by what standard it would be convinced of one, is a later decision's. No belief, of
anyone's, is authority to act.

### 4. A placed proposal

> **Normative.** `MemoryUpdateProposal` gains an optional placement: for each stored memory
> its producer retrieved, the memory's id, the revision the producer read it at, one
> relation, and, for every relation but `independent`, a note in words on how the two
> relate; and, optionally, one open question on one of those memories that the proposal
> answers.

| Relation | The proposed memory, against the stored one |
| --- | --- |
| `restates` | Makes the same claim, whatever the wording |
| `contained` | States part of what the stored one states, and nothing it does not |
| `supports` | Makes a different claim that is evidence for the stored one |
| `weakens` | Makes a different claim that is evidence against the stored one, settling nothing |
| `recheck` | Bears on the stored one without being for or against it, and makes it worth checking |
| `no_longer_true` | Shows the stored one held and has stopped holding |
| `never_true` | Shows the stored one was never true |
| `claimed_too_much` | Is the narrower truth of a stored one that claimed more than holds |
| `independent` | Neither restates, supports, weakens nor changes it |
| `unclear` | No other relation fits, or the producer cannot tell how the two relate |

> **Normative.** The relation is one of the table's ten values, a closed set added to and
> never renamed. It is not `ConflictRelation`, and neither is read as the other.

> **Normative.** A producer that cannot place a pair says `unclear` rather than choosing
> another value, and its note says why.

> **Normative.** A placed proposal may name only memories its producer read, each at the
> revision it read. How the producer retrieves them is its own decision's.

> **Normative.** For a placed proposal, `MemoryIngestor` invokes no reconciler, and
> `MemoryPolicy` is consulted only for its admissibility floor and its rule on a
> confirmed proposal. On `DefaultMemoryPolicy` those are its rules 1 to 4; its rules 5 to
> 12 read no placed proposal.

> **Normative.** Where the policy's floor or its confirmation rule rules on a placed
> proposal, that ruling is final and the placement is not applied. Otherwise the writer
> applies the placement by §5.

> **Normative.** The writer reads every memory a placement names. Where any named memory's
> stored revision differs from the revision the placement records, or a named memory is no
> longer held, the writer refuses the whole proposal with nothing written, and its result
> says so.

> **Normative.** The writer computes every holder and standing it rules on from the stored
> records and the proposal's supports, and reads none from the placement.

A proposal with no placement is ruled as today, through the reconciler and every rule of
the policy. The observer's decision makes the observer's proposals placed; no other
producer writes a memory today.

### 5. The write a placement yields

| Relation to a stored memory | What the writer does to that memory |
| --- | --- |
| `restates` | Adds the proposal's supports to it, where §5:2 and §5:3 allow; otherwise nothing |
| `contained` | Where §5:3 allows, adds to it, none backing it as worded, the proposal's supports, each in its own direction, where every holder of its backing supports already holds it, and its backing supports, as `for`, otherwise |
| `supports` | Adds the proposal's backing supports to it as `for`, none backing it as worded |
| `weakens` | Adds the proposal's backing supports to it as `against` |
| `recheck` | Raises a `recheck` question on it, resting on its own backing supports and adding none (§5:9) |
| `no_longer_true` | §3; where it retires, an end citing the support §3:4 names, closed at that support's about-when where it carries one, and at the write's instant otherwise (ADR-0328 §5:10) |
| `never_true` | §3; where it retires, a mark wrong |
| `claimed_too_much` | §3; where it retires, a replace naming the proposed memory |
| `independent` | Nothing |
| `unclear` | Nothing |

> **Normative.** The writer applies, to each memory a placement names, what the table's
> row for its relation says.

> **Normative.** A `restates` adds the proposal's supports to the stored memory only where
> adding them would not raise the stored memory's standing and the proposal carries no
> confirmation support. Otherwise the stored memory is left as it is.

> **Normative.** A placement has one disposition, for the whole proposal. Where it names
> `claimed_too_much`, the proposed memory is installed, and no `restates` or `contained` in
> it adds supports. Otherwise, where a `restates` adds its supports to a stored memory under
> §5:2, or a `contained` names a stored memory every holder of the proposal's backing
> supports already holds and the proposal carries no confirmation support, the proposal is
> folded into each such memory and not installed.
> Otherwise the proposed memory is installed.

> **Normative.** Where the proposed memory is installed, each memory a retiring relation
> retired names it as successor, and it names each as a memory it replaces (ADR-0328
> §5:6). Where the proposal is folded, a memory a retiring relation ends or marks wrong
> names no successor: ADR-0328 §5:6 names one only at its create, and the memory folded
> into already states what holds instead.

> **Normative.** An answered question named by the placement is resolved as §5:9 says,
> whether or not the proposed memory is installed.

> **Normative.** Everything one placed proposal yields is written in one atomic write,
> conditional on the revision of every memory it changes (ADR-0219 §2).

> **Normative.** Every support a relation adds, and every operation it causes, carries that
> relation's note as its note.

> **Normative.** Every write the table names is an operation ADR-0328 §5 already defines,
> and every rule of ADR-0328 §4 binds the supports it adds: a support whose part the
> memory already carries changes nothing, and a confirmation support is added to no
> memory but the one it backs, one its own ingest retires (ADR-0328 §4:6), or, as
> `against`, one a dispute names (§3:8).

> **Normative.** A `recheck` question rests on the stored memory's own counted supports
> that back it as worded, or, where none does, on every support it carries, changing none
> of them; it asks in the words of the relation's note and adds no support, so a memory
> worth checking is not shown as disputed. A question the placement names
> as answered is resolved citing a backing support of the proposal that the placement's
> relation to that memory adds there, and stays open where that relation adds none.

> **Normative.** A placed proposal carries no `observer_inference` support and no `pinned`
> support, and the writer refuses one that does: an inference is ADR-0329's observer's
> alone (§2:4), and a `pinned` support is added only by ADR-0338 §9:6's pass.

**Why a fixed set, a note and `unclear`.** The relation holds only the distinctions that
change what is written: fold or beside, evidence for or against, a question, an end, a
mark wrong, a replace, or nothing. What a reader needs beyond that, "implies Lisbon
through the Tagus", "says she moved last month", is the note, kept on what the relation
wrote. `unclear` is the way out for a pair the set does not fit: a forced choice is where
a wrong fold or a wrong end comes from, so a doubt writes nothing to the stored memory and
loses nothing, the new memory standing beside it. Where `unclear` recurs in one shape, the
set gains a value.

**Why `restates` can install beside.** A restatement judged by a model and folded onto a
stored wording would add the new support as backing that wording, and the stored
memory's standing would rise to the new support's on the model's judgement that two
wordings say the same thing. That is the laundering ADR-0336 §3:3 refused. Where the
standing would not rise, as when the owner says again in other words what the owner
already said, the fold only dates the memory again, and a repeat makes no duplicate.
Where it would, the new memory stands at its own standing beside the old one, and store
maintenance may merge them later.

**Why `contained` writes no new memory for the same holder, and one for another.** Where
the owner says again part of what the owner said, the stored memory already states it,
and the new supports count as evidence for it without backing its whole wording, so its
standing does not move (ADR-0328 §6:2). Where Sam says "Ana lives in Lisbon" against the
owner's "Ana lives in Lisbon and teaches piano", Sam's belief is his own memory: folded
in, it would end with the owner's if the owner corrected the piano half, and Sam would
never have held the rest. Sam's support still counts as evidence for the owner's memory,
as a partial supporter, never as its holder. A `claimed_too_much` in the same placement
always installs the proposal, since a replace names the narrower memory it creates.

A compound memory is where `contained` is weakest: one held only inside "lives in Lisbon
and teaches piano" ends with it when half of it is corrected
([#3259](https://github.com/leonapivato/ai-assistant/issues/3259)). The observer's
decision frames one claim per memory, so the store holds few compounds. Splitting the
ones it holds is store maintenance's.

**A worked example.** Five holders: the owner; Sam and Tom, speaking to a home device that
knows who is talking; a hospital staff page the assistant read; and the assistant's
statements, which are cited and never back a memory. Each step is placed against what
the earlier steps stored.

1. The owner: "My sister Ana moved to Lisbon last year and works as a nurse." Framed as
   three memories, each backed by the owner: M1 "Ana is the user's sister", M2 "Ana lives
   in Lisbon", M3 "Ana works as a nurse".
2. Sam: "Ana's flat overlooks the Tagus." M4, held by Sam. Against M2 it `supports`, so
   Sam's support joins M2 as `for`, not backing it: Sam is M2's partial supporter.
3. The assistant reads the staff page ("Ana K., nurse, Santa Maria Hospital"), says so,
   and the owner says "remember that". M5 "Ana works at Santa Maria Hospital" rests on the
   page's evidence item, not the assistant's sentence, and on the owner's request: held by
   the page and the owner. Against M3 and M2 it `supports`.
4. Tom: "Ana's in Porto now, she moved last month." M6 "Ana lives in Porto", held by Tom.
   Against M2 it is `no_longer_true`, but Tom holds nothing on M2: his backing joins M2 as
   `against`, nothing stops, M2 stays the owner's, and the owner's backing joins M6 as
   `against`. Against M4 it `weakens`; against M5 it is `recheck`.
5. Sam: "Oh right, she moved to Porto, and her flat isn't by the Tagus any more." Two
   claims. "Ana lives in Porto" `restates` M6 at equal standing, so it folds: M6 is held by
   Tom and Sam. Against M2 it is `no_longer_true`: Sam's partial support on M2 stops, the
   owner's backing keeps M2 current, and the dispute is recorded both ways (§3:5). "Ana's
   flat no longer overlooks the Tagus" is `no_longer_true` against Sam's own M4: his
   backing stops, nothing backs M4, and it ends.
6. The owner: "Yeah, Ana moved to Porto last month." It folds into M6, now held by Tom, Sam
   and the owner, and the owner's Lisbon support that step 4 added to M6 as `against` stops
   counting (§3:7). Against M2, the owner's own, it is `no_longer_true`: the owner's supports
   stop, nothing backs M2, and it ends, closed at last month. It names no successor, since
   the proposal folded into M6, which already says where Ana lives (§5:4).
7. The assistant: "So she's probably not at Santa Maria any more." Nobody keeps it, and a
   passing guess is not worth a record of the saying, so nothing is written. The owner: "Right, she's at São João now." M7 "Ana works at São João
   Hospital", held by the owner. Against M5 it is `no_longer_true`: the owner's supports on
   M5 stop, the page's backing keeps M5 current as what the page says, the dispute is
   recorded both ways, and the owner's answer resolves M5's open question. When the page
   updates, the same source withdraws its own backing, and M5 ends. That last step needs the
   digest to record the page's identity, which it does not yet (see Consequences).

| Memory | Held by | Status at the end |
| --- | --- | --- |
| M1 Ana is the user's sister | the owner | current |
| M2 Ana lives in Lisbon | nobody | ended at last month |
| M3 Ana works as a nurse | the owner (the page in part) | current |
| M4 Ana's flat overlooks the Tagus | nobody | ended |
| M5 Ana works at Santa Maria Hospital | the page | current; the owner against |
| M6 Ana lives in Porto | Tom, Sam, the owner | current |
| M7 Ana works at São João Hospital | the owner | current; the page against |

Usage that prefers the owner, and a person on themselves, answers "Porto, São João",
and still knows the page is out of date and that Lisbon held until last month.

### 6. A memory that lapses

> **Normative.** A create may set the memory's validity end after the create's instant,
> where the support it cites carries an about-when naming that end.

> **Normative.** A memory past its validity end keeps its status and is not live (ADR-0328
> §11:2, ADR-0045 §6): reads that return live memories do not return it, and a projection
> of it shows the end.

> **Normative.** An end, a mark wrong or a replace whose about-when lies after its instant
> stays refused (ADR-0328 §5:10). Only a create sets a future end.

"Flying to Lisbon on the 5th" is created with its validity ending on the 6th, and drops
out of what planning is shown once that passes, with nothing written. A memory that is
true from now on carries no end.

### 7. Situation labels

> **Normative.** A memory carries situation labels: a tuple of entries, each a free-text
> label, the instant it was added, the writer that added it, and the episode that suggested
> it where one did.

> **Normative.** A label says when or for what the memory matters, or what kind of
> statement the memory is. Its wording is its producer's.

> **Normative.** A memory carries at most a composition-root number of labels, and a label
> is at most a composition-root number of characters.

> **Normative.** The store embeds each label as it embeds a memory's wording.

> **Normative.** A label whose embedding lies within a composition-root distance of a label
> the memory already carries is not added, and its write says so.

> **Normative.** `MemoryWriter` gains a member that replaces a memory's labels whole,
> conditionally on the revision read, recording each new label's instant and writer. A
> label write is not an operation and changes nothing but the labels.

> **Normative.** A create may carry labels, written with it under §7:3 and §7:5.

> **Normative.** The owner may add or remove a memory's labels by an act of their own,
> through the member §7:6 names, and such a label names the writer `owner`. ADR-0328 §5:9's
> closed set of writers gains `owner`, for label writes alone. The surface that makes the
> act is a later interfaces decision's.

> **Normative.** Labels change no standing, status, validity, support or operation, and
> nothing this decision adds ranks a search by them. A search over labels is a later
> decision's.

**Why a field of their own, not `topics`.** `topics` is ADR-0213's: canonical labels
compared exactly, strictly ordered, unioned on a fold. A situation label is matched by
meaning, carries who added it and when, and is reorganised by its writer, which none of
those rules fits. `topics` has no producer (ADR-0328 §3:6), so it retires (§10) rather
than serving two purposes.

### 8. Marks

> **Normative.** A memory carries marks: a set of members of one closed enumeration, added
> to and never renamed. This decision adds two members. `occasion`: the memory states
> something that happened at a time, such as a choice made on a date; it says nothing about
> whether it happened once or often. `assistant_statement`: what the
> memory states traces to the assistant's own words in a round's message, either as a
> record of the saying (§2:4) or as what a person kept or took on from them with nothing
> recorded behind them.

> **Normative.** A mark is set by the memory's producer at its create, and changes later
> only by a decision that names how.

> **Normative.** The writer refuses a memory a write creates that is marked
> `assistant_statement` and carries no support pointing at a round's message, and one that
> a support held by the assistant's statement backs as worded unless it is marked both
> `assistant_statement` and `occasion` or is the inference §2:4 excepts.

> **Normative.** A memory marked `occasion` carries no validity end set at its create.

> **Normative.** Marks about how a person wants to be treated stay in the person-model
> store: ADR-0338's style marks and pin suggestions are unchanged, and this field holds
> marks about the memory itself.

An occasion memory is an ordinary memory: its wording dates it, and it stays true that it
happened. A second time is a second occasion memory, independent of the first, and the
two together are what store maintenance draws a pattern from. The mark lets recall and
store maintenance find occasions by an exact filter, where a label matched by meaning
could miss one.

**Why `assistant_statement` is a mark and not computed.** A memory a person keeps from
what the assistant said is the person's: their "remember that" takes on the words shown,
so it backs the memory as worded and makes them its holder; the assistant's message is
cited and never backs it (§2:4), so when the person later withdraws, nothing backs the
memory and it ends by §3:4. Code
then cannot tell from the supports alone that the assistant's words were all that stood
behind it, because the person's support looks like any statement of theirs. The producer,
which saw the parts, says so; code checks that the assistant's message is among the
supports. The memory still cites what it can: the message, where and when the assistant
said it. Every claim has a source, and here the source is that statement. One mark covers
the record of the saying too, so one filter finds everything that came from the
assistant's words, and the holder tells which it is: the assistant's statement for a
record, the person for what they kept.

### 9. Whom a memory is about

> **Normative.** A memory's `about_person` is replaced by two fields: `subjects`, the people
> the claim is a fact about, and `involved`, the people it concerns without being about
> them. Each is `None`, never determined, or a set of names, which may be empty, meaning
> determined to be none.

> **Normative.** A person appears in at most one of the two fields of a memory, and in
> `subjects` where both would fit.

> **Normative.** A name is carried exactly as a part the memory rests on gives it, and
> resolves to no identity. Which names are one person is a link held outside the memory by
> a later decision on identified people, as §2:9 has it for holders, and no model decides
> it.

> **Normative.** Where a memory is about the owner, `subjects` names the owner by the
> identifier §2:5 names. An empty `subjects` means the memory is about no person, and
> neither field's `None` is read as meaning the owner or anyone else.

> **Normative.** The observer sets both fields on every memory it writes, as its decision
> says. A memory no producer set them on carries `None` in each.

> **Normative.** `MemoryStore.search` gains an optional person filter that returns only
> memories naming a given name in `subjects` or `involved`, or in `subjects` alone where the
> caller asks, bound before the ranking cut as every eligibility predicate is (ADR-0128 §1).

> **Normative.** A memory's placement may be narrowed by its producer's proposal at its
> create (ADR-0217 §4), and the observer's decision names the observer as such a
> producer. Nothing here widens what a proposal may do.

**What the fields are for, and what they are not.** They find and weigh: placement
retrieves every memory sharing a person with the new one; usage prefers a person's own
word on facts they are the subject of; recall answers "what do I know about Ana?";
forgetting, later, finds "everything about Ana". They are not privacy: who may hear a
memory is its placement. The roles matter because they read differently: in "Ana is
pregnant" Ana is a subject, and her own word on it counts most; in "I'm planning a
surprise party for Ana" she is involved, the plan is the owner's, and she is exactly who
must not hear it, which placement decides. The lists are a model's judgement and may be
incomplete, so retrieval and forgetting also search by content, and nothing treats a
missing name as proof that a memory is not about someone.

**Why ADR-0100's rules give way here, and what of them stays.** ADR-0100 named no subject
for the owner, because no user identity existed, and barred any model from inferring a
subject from content, so that a model would not decide who counts as a person or when two
mentions are one. The owner now has an identifier (§2:5), and the owner ruled that the
observer, which knows the person, extracts whom a memory is about. What ADR-0100 guarded
against stays guarded: a name is carried as a part gives it, and no model decides that two
names are one person (§9:3).

### 10. `topics` retires from the memory

> **Normative.** The memory carries no `topics`. ADR-0213 no longer governs a memory, and
> its rules for an episode stand as ADR-0239 and ADR-0285 leave them.

> **Normative.** A memory stored with topics carries each as a situation label after the
> upgrade (§13), added by `migration`.

### 11. Concurrent writes

> **Normative.** This decision adds no lock, queue or second writer. A placed proposal is
> made safe by the guards already in force: one observer run at a time (ADR-0329 §16:6),
> the conditional write (ADR-0219 §2), the refusal of a stale placement (§4:7), one atomic
> write per proposal (§5:6), and a support keyed by its part so a retry adds nothing
> twice (ADR-0328 §4:8).

Between the producer's retrieval and the write the producer may make a model call, so a
placement can go stale. The writer refuses it whole and the producer places again. Two
producers creating the same claim at once could leave a near-duplicate; none runs today,
and store maintenance would merge one.

### 12. What a reading surface shows

> **Normative.** Every projection of a memory ADR-0328 §15:1 names also carries its
> holders and partial supporters, its `subjects` and `involved`, its labels, its marks, and
> its validity end where it lies
> in the future.

> **Normative.** The single-memory projection ADR-0328 §15:2 names also carries each
> support's holder.

> **Normative.** Planning's label for a memory conveys its holders wherever they are not the
> owner alone, the holders of its counted `against` supports where it has any, so a
> disputed memory reads as disputed, and its validity end where it lies in the future. The
> text is planning's.

> **Normative.** Every projection and planning's label convey a memory marked
> `assistant_statement` as what the assistant said, citing that message, where and when it
> was said, and the person who kept it where one did, and never as from an outside source
> or as what the person said, whatever standing ADR-0328 §6 computes for it.

How much such a memory counts for is planning's to weigh, as for any source, and the label
gives it what it needs. Planning's instruction, whose wording is the prompts', treats the
assistant's own past words as never a reason in themselves: "why X?" is answered "I
suggested it on the 20th, but nothing else backs it", not with the suggestion as proof.

> **Normative.** A change to a shape the wire carries advances `PROTOCOL_VERSION` in that
> change (ADR-0124 §9).

### 13. The upgrade

> **Normative.** On open, the memory store upgrades every memory in place, with no model and
> nothing dropped (ADR-0326 §4:1): each support gains its holder by §2's table, from the
> record it points at as the store holds it, with a legacy support's holder unknown; each
> memory gains no labels but those §10:2 carries over, and no marks; and a memory's
> `about_person` becomes `subjects` holding that one name, or `subjects` `None` where it
> named none, with `involved` `None` either way.

> **Normative.** A support whose episode no longer resolves gains the holder its origin
> alone determines where the table maps that origin to one holder, and unknown otherwise.

> **Normative.** The memory store's label advances, a file at the previous label is
> upgraded rather than refused, and the upgrading lane ships ADR-0326 §4:2's test over a
> file the previous release wrote and raises the memory store's `Store.shape` in
> `scripts/upgrade_stores.py` with a carry from the shape it replaces (ADR-0326 §7).

> **Normative.** The upgrade keeps each support's direction and whether it backs the claim
> as worded, so a support it gives the assistant's statement as its holder keeps backing
> what it backed, and the memory it is on keeps its wording and gains no mark. §2:4's limit
> and §8:3's refusal bind what a write adds after the upgrade, never what the upgrade
> carries, and such a memory is shown with the assistant's statement among its holders
> (§12:3).

### 14. What the observer's decision decides

> **Normative.** This decision does not decide what the observer reads, how it retrieves
> the memories it places against, which model calls it makes, how it words a memory or
> its labels, how it decides a relation, or how it proposes whom a memory is about or its
> placement. The observer's decision decides each, and no lane builds one under this
> decision alone.

### 15. Delivery

> **Normative.** The implementation is one contract-surface lane under ADR-0137 §2: the
> types and protocols, `memory` (the writer's placed path, the label write, the search
> filter, the holder computation and the upgrade), the canonical `MemoryWriter` and
> `MemoryStore` fakes in `ai_assistant.testing`, the shared conformance suites, the
> projections and the wire, and their tests.

> **Normative.** That lane's tests include, each failing on a writer that implements only
> the others: Sam's `no_longer_true` against the owner's memory installs beside, stops
> nothing and adds an `against` support; the owner's against the owner's memory retires
> it; one of two holders withdrawing leaves the memory current; two holders backing one
> proposal each withdraw their own supports, and the memory both held is retired; a
> contradiction from another holder records `against` supports on both memories; a claimed
> author is never
> the same holder as an established one with the same identifier; a part saying what
> another person believes is held by its sender; two parts under one identifier are one
> holder; a partial supporter is not a holder; a `contained` from another holder installs
> beside; a support held by the assistant's statement backs only a record of the saying,
> or the inference §2:4 excepts, so a kept statement ends when the person who kept it
> withdraws, and a memory it backs without both marks is refused; a record of the saying
> stays current under another holder's contradiction; an `assistant_statement` memory
> without the assistant's message is refused, and one with it is shown citing that message;
> a `restates` that would raise standing installs beside; a `restates` at equal standing
> folds with no new memory; an `unclear` writes nothing to the stored memory and installs
> the proposal where nothing folds it; a `restates` that folds beside an `unclear` installs
> nothing; a fold beside a `no_longer_true` ends the retired memory naming no successor; a
> `claimed_too_much` installs the proposal beside a `restates` that would fold; a holder's
> fold stops their own `against` support on that memory; a confirmation support on a
> memory a retiring relation leaves current is added to the proposal as `against`; a
> backdated correction closes the end at its own about-when; an `observer_inference`
> support on a memory a retiring relation leaves current is added to the proposal as
> `against`; a `contained` fold keeps an `against` support's direction; a `contained`
> fold stops none of the holder's `against` supports; a `recheck` adds no support and
> leaves its memory undisputed, and on a memory with no counted backing rests on the
> supports it carries; a retiring relation against a memory with no counted backing
> retires it citing the proposal's first backing support; an answer whose relation adds no support leaves the
> question open; a placed proposal carrying an `observer_inference` or `pinned` support is
> refused; an upgraded memory that an
> `observer_inference` support backs as worded keeps that backing, over a file the previous
> release wrote; a relation's note is on what it wrote; a `contained` adds supports without
> raising standing; a stale
> revision refuses the whole proposal; a create with a future validity end drops out of
> live reads after it; a near-duplicate label is refused; a person is in one of `subjects`
> and `involved` at most, a name not given by a part is refused, and an unset field stays
> `None`; the person filter binds
> before the cut; a label records the episode that suggested it, and the owner's label
> write names the writer `owner`; the upgrade assigns holders by §2's table; and each step of §5's worked
> example, from the same placements, ends in that example's table.

### 16. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0100 | §1, §3 and §4:1, as they apply to a memory: its one `about_person`, the unstated subject read as the owner's, the owner never named, and no model inferring a subject | §9 |
| ADR-0213 | Every clause, as it applies to a memory | §7, §10 |
| ADR-0328 | §3:1's field table, in the additions of labels and marks and the removal of `topics`; §3:6, as to `about_person`'s producer and `topics`; §4:1's support fields, in the addition of the holder; §5:10, for a create; §6:5, §11:5, §11:6 and §11:7, for a placed proposal; §11:9, as to the union of topics; §15:1, §15:2 and §15:5, in the additions alone; §15:4 and §15:5, for a memory marked `assistant_statement`; §5:9, in the addition of the writer `owner`, for label writes; §4:6, in the addition alone: a confirmation support is also added as `against` where a dispute is recorded | §2–§10, §12 |
| ADR-0329 | §9:7, in the addition alone: an `observer_inference` support is also added as `against` where a dispute is recorded; §13:2, for a `recheck` a placed write raises: it rests on the memory's own backing supports and adds none | §3:8, §5:9 |
| ADR-0338 | §4:5, in the addition alone: a `pinned` support is also added as `against` where a dispute is recorded | §3:8 |
| ADR-0336 | §2:1, §3:1–§3:3, §4:1, §5:1 and §7:1, for a placed proposal | §4, §5 |

## Consequences

**What gets easier.**
- A false claim from someone else can add only a belief they hold. It can never end,
  mark wrong or outrank what the owner said, because a holder changes only their own
  beliefs (§3).
- A forged forward, a screenshot or "the user agrees with me" never becomes the user's
  belief, because only an identity the channel establishes holds a person's belief (§2).
- The relation is judged once, by the producer that framed the memory, and the writer
  derives the write by rule. The reconciler's second model call goes for placed
  proposals.
- Plans lapse on their own (§6), and occasions can be found exactly (§8).
- Recall can prefer a holder by an exact filter, once usage asks for it, because holders
  are structured.

**What gets harder, and what this leaves.**
- **Usage now carries the ranking.** Planning sees beliefs from several holders and needs
  rules for choosing among them: by topic, role, recency and credibility. On a one-person
  hub nothing changes, because the owner is the only person holder and the existing
  ranking is usage's default. Recall should bring competing beliefs together, and every
  surface shows holders. These need design with the household.
- **More memories stand side by side.** A restatement that would raise standing, a claim
  from another holder, and a near-duplicate from a racing create all install beside.
  Store maintenance, a later decision, merges them.
- **Two write paths.** A proposal with no placement keeps the reconciler and every policy
  rule. No producer makes one once the observer's decision is built. A later decision may
  retire that path.
- **Labels are written before they are searched.** A label search is a later decision, of
  the store's search contract and recall.
- **Forgetting loses `topics`.** ADR-0213 came from the owner's direction that "the topic
  thing needs to exist for forgetting anyway". Forgetting stays undesigned and deferred,
  to be approached with care. It will likely draw on situation labels and the exact
  person filter in place of exact topic tags, and this decision rules nothing about
  it.
- **Outside sources depend on the digest recording who said it.** An outside source is
  named by the identifier its digest records (§2:6), and no digest records one today, so
  until the digest stage does (ADR-0308, the planning side), every source's evidence has an
  unknown holder: a page that updates cannot withdraw its own claim, and credibility per
  source has nothing to attach to. That change is the digest's own decision, expected soon,
  and nothing here needs to change when it lands.
- **Person holders other than the owner** wait on a decision on identified people.
  Until then the person column of §2 names the owner alone.
- **The assistant keeps no belief of its own**, only records of what it said, until a
  decision on its standards of belief: independence, interest (a source never vouches for itself), directness, track
  record, proportion, recency, coherence, the person first on themselves, and humility.
  That decision, with store maintenance, is where earned opinions and credibility per
  source begin.

## Alternatives considered

- **A kind field** (state, event, plan, instruction). Rejected by the owner: memories
  straddle kinds, the validity window already bounds time, and marks and labels cover the
  rest without forcing one category.
- **One mixed label list**, structured and free entries together. Not chosen: an exact
  filter and a match by meaning are used differently and follow different rules, so a
  mixed list would need a kind tag per entry and is two fields in one.
- **Keeping the reconciler as a second judge.** Not chosen: it answers the question the
  producer already answered, with a narrower view, and the two can disagree. The safety
  it was kept for, a write never ending a fact on resemblance alone, is §3 and §5's.
- **A person's word withdrawing the assistant's belief by rule**, by anyone or by the
  subject and the owner alone. Withdrawn: an inference is a belief like any other, so it
  would change only by its holder's own judgement, and an `against` support keeps the
  dispute visible either way.
- **The assistant as a holder of beliefs, convinced by judgement.** Adopted during the walk
  and then withdrawn: once the assistant holds no beliefs, its messages are statements it
  made, and there is nothing of its own to convince. It returns, if ever, with the
  decision on the assistant's standards of belief.
- **The assistant's claim kept as worded, held by its statement and weighed low.** Not
  chosen: "X is the best car", held by the assistant's message, reads as a fact wherever
  its label is lost, and a later message saying otherwise would end it as though the
  assistant had changed its mind, a belief under another name. A record of the saying
  carries its source in its wording and is true as it stands.
- **No memory of what the assistant said, left to episode search.** Proposed in the walk
  and withdrawn: the owner put the limit in usage, not capture. How much of it the
  producer keeps is its prompt's, and episode search holds the rest once it is built
  (ADR-0287).
- **A person as a kind apart from a source.** Not chosen: "Person is a type of source,
  no?" Every holder is the source of a claim; the kinds matter to usage, not to capture's
  rules.
- **A ranking across holders for retirement**, the owner above sources above inference.
  Withdrawn: that is usage's choice, and capture that applies it destroys a belief usage
  might need.
- **Wording another holder's claim as theirs**, "Sam says …". Not chosen: the holder on
  the support carries it, agreement across holders then reinforces one memory, and one
  holder changing their mind withdraws only their own backing. A source's report keeps
  ADR-0329 §9:8's wording until the outside-content rework.
- **The model as the holder of an untraced statement.** Withdrawn: a model's output
  depends on its whole context, the system prompt, the person's message and whatever it
  read, mixed with what it already knew, so no claim can be pinned on the model alone. The
  statement is the assistant's, and what was in its context stays one pointer away, in the
  episode its support points at.
- **Saying "no source".** Withdrawn by the owner: "make it not that there's no source.
  Instead, it should cite what it can." A kept statement of the assistant's cites the
  assistant's message.
- **Computing that a memory rests on the assistant's statement alone, from the supports.**
  Not chosen: a person's "remember that" backs the memory as worded, so the supports cannot
  show that nothing else stood behind it. The producer marks it (§8).
- **A set with no way out**, the producer always choosing one of nine. Not chosen: a
  forced choice is where a wrong fold or end comes from. `unclear` writes nothing.
- **Escalating an `unclear` pair to a stronger model.** Not now: the record shows how often
  it happens, and store maintenance, with a wider view, is the next level.
- **Links between related memories**, from the reconciler's `ADDS`. Withdrawn: stripped
  down it says "similar and not in conflict", which the search recomputes from
  embeddings with no model call.
