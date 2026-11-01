# 328. A memory is a statement resting on supports: its standing is computed from them, and every change to it is an operation citing one

- Status: Partially superseded by ADR-0329 (§4:2's origin table and §4:12, in the additions alone; §11:3 and §11:4, in the additions alone; §15:5, in the addition alone) and ADR-0338 (§4:1's points-at field, §4:2's origin table, §4:11 and §4:12, in the additions alone, and §4:7 for that part alone: a pin as a part, and the origin `pinned`) and ADR-0345 (§3:1's field table, in the additions of labels and marks and the removal of `topics`; §3:6, as to `about_person`'s producer and `topics`; §4:1's support fields, in the addition of the holder; §5:10, for a create; §6:5, §11:5, §11:6 and §11:7, for a placed proposal; §11:9, as to the union of topics; §15:1, §15:2 and §15:5, in the additions alone; §15:4 and §15:5, for a memory marked `assistant_statement`; §5:9, in the addition of the writer `owner`, for label writes; §4:6, in the addition alone: a confirmation support is also added as `against` where a dispute is recorded) and ADR-0350 (§4:2, in the addition alone: no support points at an input whose origin is `assistant`) and ADR-0351 (§4:2's origin table, its first two rows; §4:4's pasted text, for an input marked relayed) and ADR-0356 (§4:1's points-at field and §4:2's origin table, in the additions alone: a message call) and ADR-0361 (§4:5 and §4:6, each in the addition alone: a confirmation support may name a request approved on a card)
- Date: 2026-10-18
- Scope: what the memory store holds beside episodes. The memory record, its supports, its operations, its track record and its open questions; the values computed from it; how today's writers write it until the observer's decision is built; and the mechanical upgrade of every record stored before it. Batch [#3148](https://github.com/leonapivato/ai-assistant/issues/3148), lane L-α, for milestone #3 ([#2528](https://github.com/leonapivato/ai-assistant/issues/2528)).
- Dependency: ADR-0045, ADR-0217, ADR-0219, ADR-0286, ADR-0306, ADR-0308, ADR-0321 and ADR-0326, as their status lines leave them.
- Authorization: the owner ruled this design in the learning walk of 2026-10-17 and 2026-10-18 and approved it on 2026-10-18. This decision writes those rulings down and settles only what they leave open, each such point named where it is settled. The dispatcher assigned 0328. The owner reads it before it is ratified (§1:1).
- **Contract-surface decision.** It changes `core/types.py` (a memory kind and the types it carries, `MemoryKind`, `RecalledItem`'s admissible kinds, and the inspection projections) and `core/protocols.py` (`MemoryStore`'s reads, `MemoryWriter`, `MemoryPolicy`'s reading of a proposal, and the removal of `FeedbackProcessor`). It is a breaking change under golden rule 5. The episode record gains no field (§2).
- **Supersedes**, each in what remains in force (§18): ADR-0009 and ADR-0122.
- **Partially supersedes**, in the clauses §18's second table names: ADR-0005, ADR-0072, ADR-0073, ADR-0077, ADR-0086, ADR-0092, ADR-0103, ADR-0106, ADR-0107, ADR-0109, ADR-0159, ADR-0189, ADR-0217 and ADR-0321.
- **Leaves to the observer's decision**, the second ADR of batch #3148 (§17): who writes memories once the observer exists and when, candidates, the evidence bar, how open questions are raised and reach planning, who records the track record, and the supersessions of ADR-0306 §3:2, ADR-0309 §6:5, ADR-0285 §1:2, ADR-0319 §5 and ADR-0321 §5's yes path.
- Partially superseded: 2026-10-18 by ADR-0329 — §4:2's origin table and §4:12, in the additions alone: a support may be an observer's inference, addressed by the episode whose processing drew it, with the origin `observer_inference`, ranking at inference and not outside, its `when` that episode's `occurred_at` (ADR-0329 §9:7). §11:3, in the addition alone: `MemoryWriter` also gains a member that records one track-record entry (ADR-0329 §14:4). §11:4, in the addition alone: a proposal may carry one retiring operation on a stored memory (ADR-0329 §12:4). §15:5, in the addition alone: planning's label also carries each unresolved open question (ADR-0329 §6:6). Every other clause stands. This replacement takes effect on ratification of ADR-0329. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0338 — §4:1's points-at field and §4:2's origin table, in the additions alone: a support may point at a pin, addressed by the pin's id, with the origin `pinned`, ranking at "you confirmed this wording" and not outside (ADR-0338 §4:4). §4:7, for that part alone: the pin is checked as held by the person-model store, by the observer's code before the write (ADR-0338 §4:5). §4:11 and §4:12, in the additions alone: code sets `sure` on a `pinned` support, and its `when` is the instant the pin was made (ADR-0338 §4:4). Every other clause stands. This replacement takes effect on ratification of ADR-0338. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0345 — §3:1's field table, in the additions alone: a memory also carries situation labels and marks (ADR-0345 §7, §8), and in the removal of `topics` (ADR-0345 §10). §3:6, as to `about_person`, which is replaced by `subjects` and `involved`, set by the observer (ADR-0345 §9), and as to `topics`, which leaves the memory. §4:1's support fields, in the addition alone: every support records its holder, set by code (ADR-0345 §2). §5:10, for a create alone: a create may set a validity end after its instant (ADR-0345 §6:1). §6:5, §11:5, §11:6 and §11:7, for a placed proposal alone: its write follows its placement and the holder rule (ADR-0345 §3–§5). §11:9, as to the union of topics on a fold. §15:1, §15:2 and §15:5, in the additions alone: projections and planning's label also carry holders, labels, marks and a future validity end (ADR-0345 §12). §15:4 and §15:5, for a memory marked `assistant_statement` alone: it is conveyed as what the assistant said, citing that message, never as from an outside source or as what its holder said (ADR-0345 §12:4). §5:9, in the addition alone: the closed set of writers gains `owner`, for label writes by the owner's own act (ADR-0345 §7:8). §4:6, in the addition alone: a confirmation support is also added, as `against` and backing nothing, where a placed proposal's write records a dispute (ADR-0345 §3:8). Every other clause stands. This replacement takes effect on ratification of ADR-0345. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0350 — §4:2, in the addition alone: no support points at an input whose `InputOrigin` is `assistant`, the origin table gains no row for one, and the code that sets a support's origin and holder refuses one that does (ADR-0350 §6:11). Every other clause stands. This replacement takes effect on ratification of ADR-0350. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0351 — §4:2's origin table, its first two rows: a support pointing at the input or one of its messages takes `user_message` where that part's parties are a person's own and `outside_input` where they are outside, and none points at a part whose parties are empty or include the assistant's statement; a support pointing at an input understanding marks relayed, or a message of it, takes `outside_input` (ADR-0351 §7:2, §7:3, §7:6). The other rows stand. §4:4's *text the user pasted into a message of their own takes `user_message`*, for an input understanding marks as carrying words its sender did not write themselves: it takes `outside_input`, held by unknown, and an unmarked paste keeps `user_message` (ADR-0351 §7:6). Every other clause stands. This replacement takes effect on ratification of ADR-0351. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §4:1's points-at field and §4:2's origin table, in the additions alone: a support may point at the message one message call sent, as `MessageCallPart`, which takes the origin a round's message takes, by the same fact; `RoundMessagePart` stays for rounds recorded before ADR-0356 (ADR-0356 §13:2). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §4:5 and §4:6, each in the addition alone: a confirmation support may name a request instead of a question part, added only where the request was approved and its ticket run in that episode, and the statement it compares is the one the request's recorded call holds (ADR-0361 §5:10). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### What the owner ruled

The learning walk of 2026-10-17 and 2026-10-18 settled what a memory is before settling
who writes one. Three of its principles bind everything below:

```text
A19  The episode is the record. A memory is derived from it and rebuildable, and
     extracts only what is needed without the episode.
A20  A memory is a dated claim in its context. It is never stale in storage; it is
     judged at use. A re-check adds a dated support. A change is not a correction.
A21  Memories may be wrong. Every memory is auditable (what it says, its standing,
     its dates, its supports and the episodes they point at) and fixable (a
     correction sticks).
```

On the record itself the owner ruled: two kinds, the episode and the memory; a memory
stores its wording, its supports, an operations log, a track record, its validity, a
status, its placement and its revision; a support points at a part of an episode and never
copies it; every change is an operation that cites the support that caused it; standing is
the highest origin among the supports that back the claim as worded, worked out by code;
the stored confidence number goes (the owner's pick O4: reading certainty on supports,
evidence strength computed); a track record counts only reliance that shaped something the
user acted on; open questions live on the memory; and every record already stored is
carried over mechanically, nothing silently deleted. On sequencing the owner ruled that
planning's side ships together with the observer, and that `remember` keeps its
user-visible behaviour until then.

### What a memory record is today

Surveyed at `d4cbff1e`. A memory is one of three kinds beside the episode —
`SemanticMemory`, `PreferenceMemory`, `ProceduralMemory` — on `MemoryBase`'s envelope
(`id`, `content`, `provenance`, `score`, `expires_at`, `validity`, `about_person`,
`topics`, `revision`, `placement`). `Provenance` carries `source` (four `MemorySource`
values, which `band_of` maps onto three `BeliefBand`s), `confidence` (a float that
`_user_asserted_is_certain` forces to 1.0 for `USER_ASSERTED`), a flat `evidence` tuple of
ids with `evidence_elided`, `last_updated`, `attestation`, `derived_from_external` and
`last_confirmed_at`. `SemanticMemory` carries a `valid_until` of its own beside `validity`.

What writes it in production is narrow:

- **`remember`** (`orchestration/remembering.py`) writes one `SemanticMemory`, `INFERRED`
  at `REMEMBERED_CONFIDENCE` (0.8), citing the activation's episode, carrying
  `derived_from_external` where the activation had read outside content. A yes to its
  question confirms it, and the confirmed memory keeps that provenance unchanged
  (ADR-0321 §5:3), so nothing on the record says the user confirmed it.
- **`ConsolidationStage`** (`orchestration/consolidation.py`) is off by default
  (`consolidation_interval` is `None`) and writes the old shape: a confidence ladder,
  `OBSERVED` or `INFERRED`.
- **`RuleBasedFeedbackProcessor`** (`learning/processor.py`), the only producer of
  `USER_ASSERTED` outside `testing/`, is constructed nowhere in production since `learn`
  retired (ADR-0293 §11:5).
- **Readers** no longer ingest (ADR-0294). A reader's `SourceReading.proposals` reach the
  notification path, never the memory store.

So the memories a live store holds were written by `remember`, `INFERRED`. Two further
kinds of value borrow the memory types without being stored memories. The records a search,
a forecast, a fetch or a reader mints as one activation's supply are `SemanticMemory` values
with `EXTERNAL` provenance and an `Attestation` (`SearchOutcome.records`,
`ForecastOutcome.records`, `FetchOutcome.record`, `SourceReading.proposals`); none of them
reaches the store. And each frozen episode keeps recall's items (`RecalledItem`), each
naming a recalled record's `kind` and band.

### What does not fit

- `source` mixes who said it (`USER_ASSERTED`, `EXTERNAL`) with how it was reached
  (`OBSERVED`, `INFERRED`). There is no "you confirmed this wording", and "you said it" is
  forced to 1.0 even where the reading of what you said is unsure.
- `confidence` has no single meaning: the policy's 0.3 floor reads it as a probability,
  consolidation's ladder as an amount of evidence, the 1.0 of an assertion as the authority
  of your word, and `remember`'s 0.8 is a constant. Nothing calibrates it.
- `evidence` is a flat list of ids. It cannot say for or against, which part of an episode,
  when, or whose words, which A20's appended supports, the observer's evidence bar and A21's
  audit all need.
- Nothing records that a memory ended (it was true, no longer) as distinct from being wrong
  (it was never true), or links a retired memory to the one that replaced it
  ([#1839](https://github.com/leonapivato/ai-assistant/issues/1839)).
- Policy rule 13 stores a low-confidence proposal for seven days and lets it expire, a
  hidden forgetting path A20 does not allow.

### Prior art: ADR-0103

ADR-0103 found that one float was being asked to hold two facts and split it into
**evidence-strength** and **currency**, both on `Provenance`. This decision keeps that split
and takes both off a stored number. Evidence-strength becomes the evidence summary, computed
from the supports (§7). Currency becomes age, computed from the latest support and judged by
whoever uses the memory (A20); no decay function is ever applied to a memory (A8 defers
fading). What ADR-0103 got right carries over and is kept: evidence is never unseen, since no
support is ever removed (§4); an unknown instant is neither fresh nor stale (ADR-0103 §9:5);
transaction time never stands in for a confirming instant (§9:2); an instant in the reader's
future is not usable (§9:3). What goes is the number itself, ADR-0103 §4:1's reservation of
1.0 with it.

### Words

In this decision **standing** is one of the four values of §6, and a **band** is a group of
standings. ADR-0189 §1:1 and `RecalledItem.standing` use "standing" for what this decision
calls the band, and keep that meaning. Older decisions say **belief** for what this decision
calls a **memory**; §12 reads them so.

## Decision

We will keep two kinds of record. An episode stays exactly as it is. A memory is one
statement in fixed wording that rests on supports pointing at parts of episodes; every change
to it is an operation citing the support that caused it; its standing and every other value
about it are computed by code from those supports; and every memory stored before this
decision is carried into the new shape on open, mechanically. Until the observer is built,
`remember` and its yes path write this record with no change the user sees beyond what a
confirmation now means.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> read it, has authorized its ratification. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137:
> the contract triad with its primary production implementation (`SqliteMemoryStore`,
> `MemoryIngestor` and `DefaultMemoryPolicy`, with §16's upgrade) is one unit of work,
> and each lane keeps the gate green.

> **Normative.** §14's removals may each land in a lane of their own ahead of the type
> change.

> **Normative.** The observer's decision builds on this record and changes it only by
> superseding the clause it changes.

### 2. Two kinds of record

> **Normative.** The memory store holds two kinds of record: the **episode**, which records
> one activation, and the **memory**, which states one thing.

> **Normative.** The episode is unchanged. `EpisodicMemory`, its envelope and its processing
> record keep every field and every meaning they have, and nothing in this decision writes
> to a stored episode.

> **Normative.** The semantic, preference and procedural kinds retire from the store. What
> `PreferenceMemory.strength` and `context` and `ProceduralMemory.steps` carried is said in
> the wording of a memory written from now on; §16 says what the upgrade does with them.

> **Normative.** A record minted as one activation's supply — `SearchOutcome.records`,
> `ForecastOutcome.records`, `FetchOutcome.record`, the records `SourceReading.proposals`
> carry — is not a memory and is never stored. Each keeps exactly the fields it carries
> today, its `EXTERNAL` `Provenance` and `Attestation` included. Where a type is shared
> between those records and the stored memory (`MemoryRecord`, `MemoryUpdateProposal`), the
> implementation separates the two without changing what a minted record carries.

> **Normative.** A recall item (`RecalledItem`) that recalls a memory names the memory kind.
> An item stored naming `semantic` stays as stored and keeps meaning a record recalled
> before this decision. `RecalledItem` gains no field.

> **Normative.** For a recalled memory, `RecalledItem.standing` carries the memory's band
> (§6), `rests_on_recorded_external_content` the value §7 computes, and `attestation` the
> source details of the memory's latest counted source support that backs it as worded
> where its standing is from a source, and `None` otherwise.

### 3. What a memory stores

| Field | What it is |
| --- | --- |
| id | The memory's id |
| wording | The statement, in the field the store embeds and searches (today `MemoryBase.content`) |
| supports | §4, at least one |
| operations | The log of §5, starting with one create |
| track record | §8 |
| open questions | §9 |
| status | current, ended or wrong |
| validity | ADR-0045's window, set by operations |
| placement | ADR-0217's, unchanged |
| revision | ADR-0219's, unchanged |
| expires_at, about_person, topics, score | Kept, as §3:5 and §3:6 say |

> **Normative.** A memory stores the fields the table above names, and carries no
> `Provenance`.

> **Normative.** No operation changes a memory's wording. A different wording is a
> different memory, created by a create or a replace (§5). A wording the user confirmed is
> therefore never reworded, and a merge adds supports, never text.

> **Normative.** A memory carries at least one support, and its operations log begins with
> exactly one create, which cites a `for` support that backs the memory as worded.

> **Normative.** A memory's status is `current`, `ended` or `wrong`, and it changes only by
> an operation (§5). A memory whose status is not `current` has a set validity end.

> **Normative.** `expires_at` keeps its meaning (ADR-0004, ADR-0045 §6). Forgetting is
> parked, and nothing in this decision sets one.

> **Normative.** `about_person` and `topics` stay on the memory with their ratified meanings
> (ADR-0100, ADR-0213) and with no producer. Their only producers retire (§14), and no lane
> adds one until a decision names it: the design of other people for `about_person`, and
> the forgetting design or store maintenance for `topics`.

### 4. A support

A support is one piece of evidence about the memory, kept on the memory.

| Field | What it holds |
| --- | --- |
| points at | One part of one episode, or a legacy record (the part table below) |
| origin | Set by code from what it points at (the origin table below), and stored |
| direction | `for` or `against` |
| note | In words, how the part relates to the claim. No relation categories |
| backs as worded | Whether the part backs the claim as the wording states it |
| how sure | `sure`, `likely` or `unsure` about the reading of the part, or not judged |
| when | When the part happened, on this system's clock, from the episode's record |
| about when | Optionally, the time the part refers to |
| source details | For a source, which source and when it said so: an `Attestation` |
| added at, added by | When this support was added, and by which writer (§5:9) |

The parts a support may point at:

| Part | Addressed by |
| --- | --- |
| The input | The episode, and optionally the position of one of its trigger's recorded messages |
| A round's message | The episode and the planning round that wrote the message |
| An evidence item | The episode, the digest's position and the item's position in it |
| A confirmation | The episode of the yes, and the question part it approved (the asking activation, its round, the part) |
| A remember call | The episode and the id of the effect record the call is claimed under (ADR-0306 §5:3); only the remember capability points here (§13) |
| A legacy record | The id of a record stored before this decision (§16) |

The origin each part takes, the standing it ranks at, and whether it is outside content:

| What the support points at | Origin | Ranks at | Outside |
| --- | --- | --- | --- |
| The input or one of its messages, where the input's `InputOrigin` is `USER` and the message carries no `forwarded_from` | `user_message` | you said it | no |
| The input where its `InputOrigin` is `OUTSIDE`, or a message carrying `forwarded_from` | `outside_input` | from a source | yes |
| A confirmation | `confirmation` | you confirmed this wording | no |
| An evidence item | `evidence` | from a source | yes |
| A round's message, the activation not having read outside content | `assistant_message` | from a source | no |
| A round's message, the activation having read outside content | `assistant_message_over_outside` | from a source | yes |
| A remember call, its activation not having read outside content | `remembered` | inference | no |
| A remember call, its activation having read outside content | `remembered_over_outside` | inference | yes |
| A legacy record that did not rest on recorded external content | `legacy` | inference | no |
| A legacy record that did | `legacy_outside` | inference | yes |

> **Normative.** A support records the fields the first table names. Nothing on a support
> copies the text of the part it points at.

> **Normative.** A support's origin is set by code from the part it points at and the
> episode's record, as the origin table rules, and is stored on the support. No model's
> output sets or changes an origin.

> **Normative.** A part planning wrote takes its outside origin where the activation's
> record, as it stands when the support is added, says the activation had read outside
> content: the fact ADR-0306 §4:5 defines and `remember`'s `rests_on_outside_content`
> carries.

> **Normative.** A recorded message carrying `forwarded_from` takes `outside_input`. Text the
> user pasted into a message of their own takes `user_message`, as ADR-0098 §1 has it, until
> the outside-content redesign ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590))
> decides otherwise.

> **Normative.** A confirmation support is added only where the records show the user's yes
> approved the question part it names: an approval covering that part, given in that
> episode (ADR-0321 §4:6).

> **Normative.** A confirmation support is `for` a memory whose wording agrees, under
> ADR-0121 §1's predicate, with the statement the approved part showed, and only there does
> it back the memory as worded. It is `against` a memory that the ingest adding it retires
> (§11:7), and which memories that ingest may retire stays the write path's law: an
> assertion only where the question showed it replaced (ADR-0078 §5, ADR-0321 §5:5), and
> the rest as ADR-0079 §3 and ADR-0171 §2 decide. It is added to no other memory.

> **Normative.** A support other than a legacy one points at an episode the store holds when
> the support is added. A support that does not is refused, and nothing is written.

> **Normative.** A support is unique by its memory and the part it points at. Adding a
> support whose part the memory already carries changes nothing and is not an error, and
> the support already there keeps its fields.

> **Normative.** Every support is kept. Nothing removes a support from a memory, and no
> bound limits how many a memory carries; a bound takes its own decision.

> **Normative.** An `against` support never backs the claim as worded.

> **Normative.** How sure is set by whoever read the part. Code sets `sure` on a
> confirmation support, and leaves a `remembered`, `remembered_over_outside`, `legacy` or
> `legacy_outside` support not judged.

> **Normative.** A support's `when` is read from the episode's record: a recorded message's
> `sent_at` where the support names one, and the episode's `occurred_at` otherwise for the
> input and for a remember call; the round's `recorded_at`; the digest's `recorded_at`; and the
> approval's `given.at` for a confirmation. §16 sets a legacy support's.

> **Normative.** Source details are carried only by an `outside_input`, `evidence` or
> `legacy_outside` support, only where the records it points at state them, and as an
> `Attestation`. ADR-0092 §3 governs their `reported_at`.

### 5. Operations

| Operation | Cites | What it does |
| --- | --- | --- |
| create | The memory's first support | Starts the memory, `current`. May name the memories it replaces |
| add support | The support added | Adds one support |
| end | The support showing it no longer holds | Closes validity (§5:10) and sets `ended`: it was true, and is no longer. May name a successor |
| mark wrong | The support showing it was never true | Closes validity at the operation's instant and sets `wrong`, kept for audit. May name a successor |
| replace | The support showing the claim was too broad | Names the narrower memory that replaces it, closes validity at the operation's instant and sets `ended` |
| stop counting | The support that explains another away | Names that other support, which stays on the memory and stops counting |
| raise question | A support the question rests on | Adds an open question (§9) |
| resolve question | The support that resolved it | Records the resolution of a named open question |

> **Normative.** A memory's supports, status, validity and open questions change only by the
> operations the table names, and its wording by none (§3:2). Each operation is recorded in
> the memory's log with its kind, the support that caused it, a note in words, the instant
> it was written and the writer that wrote it.

> **Normative.** A memory's placement changes by ADR-0217's routes, its topics by
> ADR-0213's, and its track record by §8, as they stand. None of those writes is an
> operation, and none changes its wording, supports, status, validity or open questions.

> **Normative.** The support an operation cites is one the memory carries once the
> operation is applied. An operation may add the support it cites in the same write.

> **Normative.** An operation is applied as one atomic write: the record it yields replaces
> the stored memory only where the stored revision is the one its writer read (ADR-0219
> §2), and otherwise nothing changes.

> **Normative.** No operation removes a support, a logged operation, a track-record entry or
> an open question, resolved ones included.

> **Normative.** An end, a mark wrong or a replace that names a successor is written in one
> atomic write with the successor's create, which names the retired memory among those it
> replaces. Each of the two memories names the other's id.

> **Normative.** A create makes a memory `current`; an end or a replace makes it `ended`; a
> mark wrong makes a `current` or an `ended` memory `wrong`. Nothing makes a memory
> `current` again: something true again is a new memory.

> **Normative.** A support stopped from counting stays on the memory and is never stopped
> twice, and stopping is not undone. It is excluded from the standing (§6), the evidence
> summary, as of, reading certainty and whether the memory is unbacked; it is included in
> learned, rests on outside content and whether the memory is legacy (§7).

> **Normative.** A writer is named from a closed set, added to and never renamed:
> `remember` (§13) and `migration` (§16). The observer's decision adds its own.

> **Normative.** An end closes validity at the about-when of the support it cites where that
> support carries one, and at the operation's instant otherwise. An end whose about-when
> lies after the operation's instant is refused: a claim that holds until a later time is
> worded so.

> **Normative.** Every close of a validity window this section makes clamps and never
> resurrects (ADR-0080 §1), and one with no representable close is refused with nothing
> written (ADR-0080 §3).

### 6. Standing

| Standing | In plain words | Band |
| --- | --- | --- |
| confirmed | you confirmed this wording | `ASSERTED` (yours) |
| said | you said it | `ASSERTED` (yours) |
| source | from a source | `ATTESTED` |
| inference | inference | `DERIVED` |

> **Normative.** A memory's standing is one of four values, highest first: you confirmed
> this wording, you said it, from a source, inference.

> **Normative.** A memory's standing is the highest at which the origin table ranks the
> origin of any counted support that is `for` the memory and backs it as worded. Where no
> such support exists, its standing is inference.

> **Normative.** Standing is computed by code from the stored supports, a lookup and a
> maximum, and is never set. It is never derived from how sure, from a count, from a
> model's number or from any other value, and it changes exactly when the memory's supports
> or their counting change (the principle of ADR-0072 §4, kept).

> **Normative.** `BeliefBand` keeps its three members, each now a group of standings:
> `ASSERTED` is confirmed and said, `ATTESTED` is source, and `DERIVED` is inference. A
> memory's band is its standing's group.

> **Normative.** A lower standing never silently overrides a higher one. A writer refuses an
> end, a mark wrong or a replace whose cited support's origin ranks below the memory's
> standing, and a stop counting whose cited support's origin ranks below the origin of the
> support it stops, and writes nothing. Where such a change is wanted, the open question it
> needs is raised on the memory (§9).

### 7. Values computed from a memory

> **Normative.** The values this section names are computed from the stored record and are
> never stored as judgments: the evidence summary, as of, learned, reading certainty, rests
> on outside content, transaction time, legacy and unbacked.

> **Normative.** The **evidence summary** is the number of counted `for` supports, the number
> of counted `against` supports, the number of distinct episodes they point at, and the
> latest `when` among them.

> **Normative.** **As of** is the latest usable confirming instant among the counted `for`
> supports. A support's confirming instant is its source details' `reported_at` where it
> carries source details, and its `when` otherwise. An instant is usable where it is set and
> not in the reader's future (ADR-0103 §6). Where none is usable, as of is unknown, and
> unknown is neither fresh nor stale (ADR-0103 §9:5).

> **Normative.** **Learned** is the earliest `when` among all the memory's supports, and
> unknown where none carries one.

> **Normative.** **Reading certainty** is the best how sure among the counted `for` supports
> that back the memory as worded, and not judged where none of them carries one.

> **Normative.** **Rests on outside content** holds exactly where the memory's band is not
> `ASSERTED` and at least one of its supports, counted or not, has an outside origin. A
> support stopped from counting still counts here: a warrant once received is never
> unreceived.

> **Normative.** Rests on outside content says what was recorded and never that a memory
> was uninfluenced by outside content, as ADR-0106 §1:2 rules for the predicate it
> replaces.

> **Normative.** A memory's **transaction time** (ADR-0045 §3) is the latest instant among
> the operations in its log.

> **Normative.** A memory is **legacy** exactly where every one of its supports has the
> origin `legacy` or `legacy_outside`.

> **Normative.** A memory is **unbacked** exactly where no counted `for` support backs it
> as worded.

> **Normative.** A store may persist a value this section computes for its own reads, only
> as a derivation it rewrites on every write of the row, and no persisted value is read to
> compute another.

> **Normative.** No value this section computes ranks a search. `MemoryStore.search` ranks by
> relevance alone (ADR-0072 §5, ADR-0103 §8:1).

### 8. The track record

> **Normative.** A memory keeps a track record: dated use entries, each naming the episode of
> the activation that relied on the memory, when it relied on it, whether the reliance held
> up or let the user down, a note in words, and when and by which writer the entry was
> recorded.

> **Normative.** An entry is recorded only for a use that shaped something the user acted
> on — a suggestion the user accepted, an action that ran, an answer the user used — and
> never for a passing mention.

> **Normative.** A track-record entry is unique by its memory and its episode. Recording it
> again changes nothing.

> **Normative.** The track record never changes a memory's standing, supports, status or
> validity, is not a support, and ranks nothing.

> **Normative.** Who records an entry, when, and how held up or let down is decided are the
> observer's decision's. Nothing records an entry before it.

### 9. Open questions

> **Normative.** An open question lives on the memory it is about, with an id, its kind
> (`conflict`, `policy_ask` or `recheck`, a closed set added to and never renamed), what it
> asks in words, the memory's supports it rests on (at least one), when it was raised and
> by which writer, and, once resolved, when, the support that resolved it, and a note.

> **Normative.** An open question is raised and resolved only by an operation (§5), and a
> resolved question stays on the memory.

> **Normative.** No background work sends an open question to the user as a message. A
> question is asked only where the user is present, until a decision on proactivity says
> otherwise.

> **Normative.** Who raises an open question, when, and how it reaches planning and is
> answered are the observer's decision's. The interim raises none (§13).

### 10. What retires from the record

| Retires from a memory | Replaced by |
| --- | --- |
| `Provenance.confidence` | Reading certainty on supports, and the evidence summary (§7) |
| `Provenance.source` as the stored standing | Origins on supports, and the computed standing (§6) |
| `Provenance.evidence` and `evidence_elided` | Supports, every one kept (§4) |
| `Provenance.attestation` | A source support's source details (§4) |
| `Provenance.derived_from_external` | Outside origins on supports, and rests on outside content (§7) |
| `Provenance.last_confirmed_at` | As of (§7) |
| `Provenance.last_updated` | Transaction time (§7) |
| `SemanticMemory.valid_until` | Nothing: validity is the one window (ADR-0045 §2) |
| The semantic, preference and procedural kinds | One memory kind (§2) |

> **Normative.** A memory carries none of the fields the table's first column names, and
> each is replaced as its second column says.

> **Normative.** No memory carries a confidence number, stored or presented.

> **Normative.** No `MemoryPolicy` stores a proposal tentatively. `DefaultMemoryPolicy` rules
> `STORE_TEMPORARY` on nothing, and its `min_confidence` and `temporary_ttl` retire with
> their seven-day default. A proposal that does not meet an evidence bar is not committed;
> the bar is the observer's decision's.

> **Normative.** `MAX_EVIDENCE_CITATIONS` and `evidence_elided` bound nothing on a memory.

> **Normative.** A member of a closed enumeration that no record any store holds after
> §16's upgrade names, and that no minted record carries, leaves `core` with this
> decision's implementation, subject to ADR-0326 §2:3 where a stored value names it.

### 11. The write path and the store

> **Normative.** `MemoryStore` stays mechanical. It stores and returns memories whole, its
> reads compute nothing beyond §7's permitted derivations, and `write_atomic`'s modes are
> unchanged.

> **Normative.** A memory is live exactly where its validity is live at the reader's instant
> (ADR-0045 §6). `list_beliefs` filters on the band §6 computes, and the belief listing
> excludes episodes by default (ADR-0074 §6).

> **Normative.** `MemoryWriter` gains one member that applies one operation (§5) to one
> stored memory, computing the record it yields and writing it conditionally on the
> revision read, and refusing, with nothing written, every write §4, §5 or §6:5 refuses.

> **Normative.** `MemoryWriter.ingest` stays the path that creates a memory under
> `MemoryPolicy`. Its proposal carries a memory whose supports and create its producer
> built.

> **Normative.** On an `ACCEPT`, `ingest` installs the proposed memory.

> **Normative.** On a `REINFORCE`, `ingest` adds the proposal's supports to the target, one
> add support each, and leaves the target's wording as it is. A support the target already
> carries changes nothing.

> **Normative.** On a `SUPERSEDE`, `ingest` installs the proposed memory at a fresh id as it
> does today, and ends each memory the ruling retires with an end citing the new memory's
> first support, added to the retired memory as an `against` support. Each retired memory
> names the new one as its successor, and the new one names them as the memories it
> replaces. An end that §6:5 refuses, or a retired memory that already carries the part
> that support points at, refuses the whole ingest, with nothing written.

> **Normative.** On a `REJECT` or an `ASK_USER`, `ingest` writes nothing.

> **Normative.** Every rule of the ratified write path over a field this decision keeps
> stays as it stands: placement's ratchet (ADR-0217), the union of topics on a fold
> (ADR-0213 §8), and expiry.

> **Normative.** `MemoryPolicy` reads a memory through §12, and its ruling stays a total
> function of its arguments (ADR-0159 §2).

> **Normative.** A proposal's fingerprint keeps ADR-0078 §7's criterion over the memory: the
> id, the revision, the score, the topics, and every support's added at and operation's
> instant are bookkeeping and excluded; everything else is in, and the supports are taken
> as a set keyed by the part each points at.

> **Normative.** `MemoryStore.walk_records` and `advance_walk` stay, with no caller until
> store maintenance (§14).

### 12. Reading earlier clauses through the new record

| An earlier clause's term, said of a memory | Reads as |
| --- | --- |
| `MemorySource.USER_ASSERTED`, band `ASSERTED`, an assertion, the user's word | Band `ASSERTED`: standing confirmed or said |
| `OBSERVED`, `INFERRED`, band `DERIVED`, an inference, derived | Band `DERIVED` |
| `EXTERNAL`, band `ATTESTED`, attested | Band `ATTESTED` |
| `band_of(provenance.source)` | The memory's band (§6) |
| `rests_on_recorded_external_content`, `derived_from_external` | Rests on outside content (§7) |
| A record that carries no provenance (ADR-0306 §5:16) | Never a memory: its supports are its provenance |
| `Provenance.evidence`, the evidence it cites | The episodes its supports point at |
| `Provenance.attestation`, `reported_by`, `reported_at` | Its source supports' source details |
| `Provenance.last_updated` | Transaction time (§7) |
| `Provenance.last_confirmed_at`, the confirming instant | As of (§7) |
| `Provenance.confidence` | Nothing |
| `SemanticMemory`, `PreferenceMemory`, `ProceduralMemory`, a belief's kind | The memory kind |
| A belief | A memory |

> **Normative.** A ratified clause still in force that says one of the table's terms of a
> memory reads it as the table says where that reading leaves what the clause decided
> unchanged, and is not superseded by that reading. Where it does not, the clause is
> superseded and §18 names it.

> **Normative.** Where such a clause names a retired field, member or producer (§10, §14) as
> one of several things it governs, that limb binds nothing and the rest binds as written.

> **Normative.** A clause this decision does not name stands as written. A lane that finds a
> clause which, read through the table, requires what §§2–11 forbid files an issue, and a
> later decision records it; meanwhile this decision governs in that respect.

### 13. The interim, until the observer is built

> **Normative.** Until the observer's decision is implemented, `remember` keeps every
> behaviour the user sees under ADR-0306 and ADR-0321 — its declaration, its question, its
> replies, its *needs you* — and writes the memory record as this section says.

> **Normative.** A remember call proposes one memory: its wording is the statement, its one
> support points at the remember call with the origin `remembered`, or
> `remembered_over_outside` where `rests_on_outside_content` is true, `for`, backing it as
> worded, not judged, its `when` the episode's `occurred_at`, added by `remember`; and its
> create cites that support, by `remember`. Its placement is set by rule as today
> (ADR-0217 §3:12).

> **Normative.** A remember that runs under a yes (ADR-0321 §5:2) proposes instead one
> support with the origin `confirmation`, pointing at the yes's episode and the approved
> question part, `sure`, its `when` the approval's `given.at`. The proposal still carries
> the `UserConfirmation` built as today, and the memory stands at "you confirmed this
> wording".

> **Normative.** `DefaultMemoryPolicy` keeps its rules read through §12, rule 13 excepted
> (§10): its asserted arms key on band `ASSERTED`, its taint floor (ADR-0106 §6) on a
> proposal in band `DERIVED` that rests on outside content and carries no confirmation, and
> its target classes on bands.

> **Normative.** An `ASK_USER` on the write stage stays governed by ADR-0319 §5 until the
> observer's decision. The interim raises no open question and records no track-record
> entry.

> **Normative.** The reply's wording, planning's instructions and `remember`'s declaration do
> not change under this decision.

### 14. Old producers

> **Normative.** `RuleBasedFeedbackProcessor` retires, with the `FeedbackProcessor` Protocol,
> its canonical fake, its conformance suite, `FeedbackEvent` and `FeedbackKind`. Feedback is
> interpreted by models and never mechanically (the owner's A3), and how it reaches memory
> is the observer's decision's.

> **Normative.** The consolidation stage retires: `ConsolidationStage` with its report types,
> its scheduler row, and the engine's `consolidate`. Store maintenance, its successor, is a
> later milestone's and its own decision's, and [#829](https://github.com/leonapivato/ai-assistant/issues/829)
> re-decides its default then.

> **Normative.** The matters pass keeps its schedule. `consolidation_interval` stays, and the
> scheduler's `matters_pass` row runs at it, armed and disabled as it is now: ADR-0300 §9:3's
> "the schedule of the background memory work".

> **Normative.** `consolidation_model` and the route it builds stay, serving the work that
> rides them: the story tidy-up, the matters pass and the reconciler. ADR-0285 §5:3 stands.

### 15. What a reading surface shows

> **Normative.** A projection of a memory — `Belief`, `BeliefSummary` and every later model
> for that purpose (ADR-0189 §1:3) — carries, as structured fields and as the record holds
> them: the id, the wording, the standing, the band, the status, the validity end, as of,
> learned, the evidence summary, reading certainty, the track record's counts (relied on,
> held up, let down) and last use, whether it is legacy, whether it is unbacked, and rests
> on outside content.

> **Normative.** The single-memory projection also carries each support: its origin,
> direction, note, how sure, `when`, about when, source details, whether it counts, and the
> part it points at resolved to readable content or shown as gone.

> **Normative.** No projection of a memory carries a confidence, a presented confidence or
> an elision count.

> **Normative.** A surface showing a memory to the owner (the CLI, the gateway's panel) shows
> at least its standing in plain words, its age, its evidence summary where its standing is
> inference, its reading certainty where that is not `sure`, every let-down, and the legacy
> mark. The wording is the surface's.

> **Normative.** Planning's label for a memory conveys its standing in plain words, its age,
> its evidence summary where its standing is inference, its reading certainty where that is
> not `sure`, and its track record where it has one. The text is planning's.

> **Normative.** A memory planning would be shown that rests on outside content reaches it
> only through a digest (ADR-0308 §3:3, read through §12).

> **Normative.** A support whose episode no longer resolves still counts, and is shown as
> gone and never as evidence. A memory none of whose supports' episodes resolves is held,
> marked and answerable, and nothing retires it for that (ADR-0077 §6's tombstone and its
> held state, kept).

> **Normative.** A change to a shape the wire carries advances `PROTOCOL_VERSION` in that
> change.

### 16. The upgrade of what is already stored

| Stored before this decision | Becomes |
| --- | --- |
| An episode | Unchanged |
| A semantic, preference or procedural record | A memory at the same id |
| Its `content`, with a preference's `context` and a procedural record's steps | The wording (§16:3) |
| Its `validity`, `placement`, `expires_at`, `about_person`, `topics` | The same values |
| The whole record, as stored | One legacy support, carrying it |
| Its `last_updated` | The create's instant |
| A validity end at or before the upgrade's instant | An end dated at that validity end, and `ended` |

> **Normative.** On open, the memory store upgrades every record written before this
> decision in place, by the table above, with no model and nothing dropped (ADR-0326 §4:1,
> §4:3, §4:4).

> **Normative.** Each semantic, preference or procedural record becomes a memory at the same
> id, carrying its `validity`, `placement`, `expires_at`, `about_person` and `topics`
> unchanged.

> **Normative.** The memory's wording is the record's `content`, followed, for a preference
> record carrying a `context`, by ` (context: ` + its context + `)`, and, for a procedural
> record carrying steps, by ` Steps: ` + its steps in order, each preceded by its number,
> a full stop and a space, joined by `; `. A preference's `strength` is a number, which no
> memory's wording carries (§10), and is kept on the legacy support alone.

> **Normative.** The memory carries one legacy support pointing at the record's own id,
> carrying the record whole as it was stored. Its origin is `legacy_outside` where
> `rests_on_recorded_external_content` held for the record's `Provenance`, and `legacy`
> otherwise; it is `for`, backs the memory as worded, is not judged, and is added by
> `migration`.

> **Normative.** The legacy support's `when` is the latest `occurred_at` among the episodes
> the store holds that the record's `evidence` names, the record's `last_confirmed_at` where
> it names none the store holds, and unknown where neither is set. Its source details are
> the record's `attestation`, where it carried one.

> **Normative.** The memory's create cites the legacy support, by `migration`, at the
> record's `last_updated`. Where the record's validity end is at or before the instant of
> the upgrade, an end follows, citing the same support at that end, and the memory is
> `ended`.

> **Normative.** No stored episode is rewritten, a recall item naming `semantic` included.

> **Normative.** The memory store's label advances, and a file at the previous label is
> upgraded rather than refused. Refusing it would be a fresh data directory, which takes
> the owner's ruling (ADR-0326 §4:7), and none is made here.

> **Normative.** The upgrading lane ships ADR-0326 §4:2's test over a file the previous
> release wrote holding each memory kind that release could store, and raises the memory
> store's `Store.shape` in `scripts/upgrade_stores.py` with a carry from the shape it
> replaces (ADR-0326 §7).

> **Normative.** A legacy memory stands at inference, marked legacy, until a later write
> adds supports to it. Nothing deletes a legacy memory or its legacy support for being
> legacy.

### 17. What the observer's decision decides

> **Normative.** This decision does not decide who writes memories once the observer exists
> or when, the candidate the observer reads and the part and origins a support pointing at
> one takes (ranking at inference), the evidence bar, how a support's reading fields are
> judged, the placement of what the observer writes, or how a memory from a source is
> worded so that it states what its source said. The observer's decision decides each, and
> no lane builds one under this decision.

> **Normative.** This decision supersedes none of ADR-0306 §3:2, ADR-0309 §6:5, ADR-0285
> §1:2, ADR-0319 §5 or ADR-0321 §5's yes path. Each stays in force until the observer's
> decision supersedes it.

### 18. Relationship to earlier decisions

Superseded, each in what remains in force, because §14 retires what they govern:

| Earlier decision | What it governed |
| --- | --- |
| ADR-0009 | `FeedbackEvent`, `FeedbackProcessor` and the first deterministic processor, in what ADR-0122 left |
| ADR-0122 | Resolving a `FeedbackEvent`'s `memory_kind` from what a correction touches, in what ADR-0319 left |

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What retires | Why |
| --- | --- | --- |
| ADR-0005 | §1's union of four kinds, as to the semantic, preference and procedural kinds; §2's `Provenance` on every record and its profile and model as a query over `source` and `confidence`, as they apply to a memory; §3's store-temporarily outcome | Two kinds, a memory carrying supports instead of `Provenance`, and nothing stored tentatively (§2, §3, §10). The episode keeps its envelope, and §3's propose/dispose path stands |
| ADR-0072 | §1's definition of the profile and the inferred model by `MemorySource` and confidence; §2's ruling that the three bands partition `MemorySource`, as it applies to a memory; §3 whole; §6's rule that a belief is rendered carrying its confidence | Bands are groups of standings (§6), and a memory carries no confidence (§10). §4's keyed-on-the-record rule, §5's relevance-only retrieval, §7 and §9 stand |
| ADR-0073 | §4's per-belief list — its band, its confidence, its kind among four and its band-dependent answer to why it is held — except that list's floor that a citation is never rendered as evidence it cannot show; and §7's `Belief` carrying exactly §4's fields | §15 states what a projection carries. The floor stands, as §15:7 keeps it |
| ADR-0077 | §6's presented confidence: the number falling with lost support, every surface stating the adjusted one, and a belief held at its effective floor | No confidence (§10). §6's lazy resolution, tombstone and held state stand (§15:7) |
| ADR-0086 | §1–§4, as they apply to a memory | Every support is kept (§4) |
| ADR-0092 | §1, as it applies to a memory | The attestation is a source support's details (§4). §3 governs those details |
| ADR-0103 | §2:1, §3:1, §3:2, §4:1, §6:1, §6:2, §9:1 and §9:4, each as it applies to a memory | Evidence strength and currency are computed (§7) |
| ADR-0106 | §1:1, §2:1, §2:2, §3:1, §4:1, §4:2 and §7:1, each as it applies to a memory; §5:1, §6:8, §9:1, §9:2 and §10:5–§10:8 whole; §10:1 and §10:4 as they apply to a memory | Outside origins replace the marker (§4, §7); consolidation retires (§14). §1:2 and §6:1–§6:7 stand, read through §12 |
| ADR-0107 | §2–§7, as they apply to a memory's projection | No elision on a memory (§10, §15) |
| ADR-0109 | §1:1, §2:1, §4:1–§4:4, §5:1–§5:3, §6:1–§6:3, §8:1–§8:3, §9:1, §9:2 and §10:1–§10:4, each as it applies to a memory | As of is computed from supports (§7). §1:2, §2:2, §3:1, §3:2 and §7:1 stand, read on as of |
| ADR-0159 | §4:1's arm (c), in its `STORE_TEMPORARY` below `min_confidence` | Nothing is stored tentatively (§10); arm (c) is `ACCEPT` |
| ADR-0189 | §2:1, §2:5 and §2:6, as they reach the projection of a memory | §15 states what the projection carries. §1 stands: a projection carries the band it calls the standing, and §6's standing beside it (§15) |
| ADR-0217 | §7:1–§7:8: the owner's write-time `guarded` flag on `FeedbackEvent`, its route and its honouring by the `FeedbackProcessor` | Both retire (§14). §7:9–§7:18's `guard` and `unguard` after the fact stand, outside §5's operations (§5:2) |
| ADR-0321 | §5:3 | A confirmed memory carries a confirmation support and stands at "you confirmed this wording" (§13). §5:3's "how much weight a confirmed memory carries is the learning milestone's" is this decision |

Read through §12 and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0038, ADR-0045 §5, ADR-0050, ADR-0078, ADR-0079, ADR-0080, ADR-0081, ADR-0121, ADR-0159 (but §4:1(c)), ADR-0161, ADR-0171, ADR-0214 | Nothing: the write path's law reads its source and band terms through §12. ADR-0038 §3's one-way rule is §6:5's case of an inference against an assertion |
| ADR-0092 §3, ADR-0117 | Nothing: they govern an `Attestation`, which a source support carries |
| ADR-0306 §5:16, ADR-0308 §3:3 | Nothing: a memory's source is outside where it rests on outside content |
| ADR-0100, ADR-0213 | Nothing: `about_person` and `topics` stay, with no producer (§3:6); their producer limbs bind nothing (§12:2) |
| ADR-0300 §9:3, ADR-0285 §5:3 | Nothing: the schedule and the route stay (§14) |
| ADR-0045, ADR-0074 §6, ADR-0217 (but §7:1–§7:8), ADR-0219, ADR-0072 §5 | Nothing: validity, the listing's default, placement, the revision and relevance-only search are kept as they stand |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of each ADR this section's first two tables name, atomically with this
> ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- Every memory answers A21's audit from its own record: what it says, its standing, when it
  was learned and as of when, and every support pointing at the part of the episode it rests
  on, with every change explained by an operation.
- A confirmation means something on the record: a memory the user confirmed stands at the
  top and is never reworded or silently overridden.
- A change and a correction are told apart, history is kept, and a retired memory names its
  successor, which discharges #1839.
- The observer's decision has a record to write: supports to add, operations to apply, the
  standing order enforced at the writer, and open questions and a track record to fill.

**What it costs.**
- The type change reaches every reader of a memory's provenance in `orchestration`
  (planning's labels, recall, disclosure, `remember`), `interfaces` (the CLI and the panel)
  and the wire. The dispatcher cuts those lanes (§1:3).
- Supports are unbounded per memory. A memory restated often grows; a bound is its own
  decision if it causes trouble (§4).
- In the interim, a remember that contradicts a memory the user confirmed is asked about as
  "replacing …" (ADR-0321 §5:5) instead of being written, because the policy now sees an
  assertion where it saw none.
- Legacy memories show as legacy, at inference, until the observer re-processes their
  episodes.

**What stays open.**
- Everything §17 names, for the observer's decision.
- Store maintenance and #829's default.
- Forgetting, a bound on supports, credibility per source, and the design of other people.

## Alternatives considered

- **Keep `Provenance` on the memory and add supports beside it.** Rejected: two warrants on
  one record can disagree, and `source` and `confidence` are the fields whose meanings do
  not hold.
- **Fixed relation categories on a support** (narrows, ends, wrong, discounts). Rejected by
  the owner: real evidence is mixed, and fixed categories are too hard to codify. A note in
  words carries the relation, and the discrete part lives in the operations.
- **Keep a confidence, calibrated or coarse** (the walk's O1, O2, O7). Rejected for O4:
  reading certainty where a reading was made, evidence computed, nothing a model can dial up.
- **Copy the user's words onto the support.** Rejected: point at the episode, which keeps
  one copy and leaves forgetting to decide what a deleted episode leaves behind.
- **Retire `topics` and `about_person` now.** Not chosen: nothing writes either, the designs
  that would use them are parked, and keeping an unwritten field costs nothing where retiring
  it now and restoring it later costs two upgrades.
- **Leave the old kinds and adapt the policy only.** Rejected: the walk found the gaps in the
  record itself, and the observer needs a record that can say what it is going to write.
- **A fresh data directory instead of the upgrade.** Not available: it takes the owner's
  ruling (ADR-0326 §3:4), and the owner asked for nothing to be silently deleted.
- **One ADR with the observer.** Not chosen: two keep each reviewable, and the record merges
  first so the observer is designed against it.
