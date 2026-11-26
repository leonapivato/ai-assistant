# 388. Before the stores withhold: a name a write adds must resolve, a limit counts what the store holds, and a story's start, the pin pass, the upcoming-event producer and a work with no facts each read by a sight

- Status: Proposed
- Date: 2026-11-26
- Scope: an amendment to decisions D1 and D2 of milestone 22, "Every record has a home"
  (acceptance [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)). It settles six places where
  the merged decisions, read as written, do not say what a build whose bound stores withhold does:
  a name the memory store judges itself (§2), a story a work starts (§3), the observer's pin pass
  (§4), a work with no recorded facts (§5), a limit a store checks at a write (§6), and the
  upcoming-event producer (§7). §8 records what it amends, §9 what building it needs.
- Authorization: the coordinator's proposal under the owner's delegation of ratification, and
  not an owner ruling. The owner's only words here are #3709's record: on 2026-11-26, "Yes,
  agreed", to the milestone's scope. The owner has ruled nothing in this decision. The
  coordinator assigned 0388, shows the owner the draft, and ratifies it once its reviews are
  green.
- **Contract-surface decision; a decision only.** It changes no Protocol, type or code. It
  names changes to `MemoryStore`, `StoryStore` and `Sight` (§9), so it takes the adversarial and
  the architecture review. Building it is a breaking change under golden rule 5.
- **Partially supersedes**
  [ADR-0383](0383-each-record-carries-its-home-and-every-read-a-work-a-producer-or-a-run-makes-is-of-a-store-bound-to-one-sight-which-answers-as-though-it-held-only-what-that-sight-sees.md)
  (§4:8 and §6:4, each in the addition alone),
  [ADR-0384](0384-upkeep-of-a-persons-records-runs-for-that-person-a-run-tends-one-domain-reads-what-its-person-may-see-through-the-filter-and-writes-only-there.md)
  (§2:1 and its table's upcoming-event producer row, each in the addition alone) and
  [ADR-0289](0289-a-story-store-holds-which-experiences-belong-to-the-same-matter.md) (§3:1, in
  the addition alone), as §8 records.

## Context

The stores are bound, and a work's stages, the observer and the upkeep runs read through sights,
all in the counting mode (ADR-0383 §7:10, §11:1). The last build lane switches them to withhold.
The build lanes found six places that switch would leave undecided, each recorded on #3711:

1. **A name the store judges itself.** ADR-0383 §4:8 gives a name of a record the writer's sight
   does not see the refusal a name never written gets, and presupposes that one is refused. In
   the memory store only a support's episode is, by the writer (ADR-0328 §4:7). Every other name
   is judged only where it resolves, and against every stored row, bound or not
   ([#3727](https://github.com/leonapivato/ai-assistant/issues/3727)). Withholding, the store
   would then tell a withheld name of another home from one never written; judged over held rows
   alone, it would let a record name a withheld record of another home (ADR-0383 §4:7, §8:3).
2. **A story a work starts.** `StoryCalls._start` creates the story through the work's bound
   store, then writes its first notes through it. A work whose sight does not see the home it
   writes into, an unidentified sender's (ADR-0383 §4:4 and §6's table), does not hold the story
   it made (ADR-0383 §7:4), so its notes are refused (ADR-0383 §7:5) and the call ends unfinished.
3. **The pin pass.** `PinConfirmations` (ADR-0338 §9:6) reads every person's pins and memories
   and writes a `pinned` support for each, unbound: no clause gives it a sight.
4. **A work with no recorded facts** reads by `Sight.of_producer(None, ())`, since `Sight.of_work`
   takes recorded facts. Nothing is its own, so a withholding store would not give back its own
   episode, and its capture would end degraded
   ([#3763](https://github.com/leonapivato/ai-assistant/issues/3763)).
5. **A limit a store checks at a write** reads only what the bound store holds, so through a
   sight that does not see the home written into, it counts nothing and does not hold.
6. **The upcoming-event producer** reads the person-model store for a zone and writes through
   the notification store, unbound: ADR-0384 §2 says it "reads a source, not a store".

None is reached in the counting build, where a bound store holds every record.

## Decision

We will have a withholding memory store refuse a name a write adds that resolves to no record it
holds; count a write's limits over what the bound store holds and make such a write only where
the writer sees its home; start a story and its notes in one write; and give the pin pass, the
upcoming-event producer and a work with no recorded facts a sight.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules the hub ADR-0383 §1:2 rules, and only the six points above.
> It changes nothing a bound store in the counting mode answers.

### 2. A name the memory store judges itself

> **Normative.** A memory store bound to a sight, in the withholding mode, refuses a write that
> adds to a record a name that does not resolve to a record the store holds once the write is
> made: a record of the same write, or one the bound store gives back. A name withheld from its
> sight and a name never written get the one refusal, `UnresolvedEvidenceError` naming the id,
> with nothing written.

> **Normative.** A name a write adds is one the written record carries and the record stored
> under its id did not. A name the stored record already carried is not judged again, so a write
> to a memory whose support's episode has since been deleted is not refused for it.

> **Normative.** A name that resolves to a record the store holds of another home is refused
> with ADR-0383 §4:7's error, as today. Neither judgement is one of a write's own checks: ADR-0383
> §7:11's list is closed, and both are made over the records the bound store holds (ADR-0383 §7:2).

> **Normative.** The observer gives a candidate no confirmation (ADR-0361 §5:10) where the asking
> activation's episode is not held, as it already gives none where the approval's episode is not,
> so §2:1 refuses no memory for it.

> **Normative.** §2:1 does not judge the takeover lineage a work's capture writes on its own
> episode: the activation that took it over and the activation each joined input was taken from
> (ADR-0349 §7:7, §7:21; ADR-0352 §5:2). Code records them from admitted activations, never from a
> model's output or an input's text, and both sides of a takeover are works for one person
> (ADR-0349 §5:2, §7:5), so of one home. A capture is not lost because the other side's episode
> was deleted after the takeover. §2:3 still refuses one that resolves to a held record of another
> home.

The names are those ADR-0383 §4:7 lists as they reach `memory.db`: an evidence pointer's episode
on a support, an operation or an open question, a confirmation's asking activation and
`ran_in`, a track-record entry's and a label's episode, a lineage, and an episode's taker and the
activation a joined input was taken from. A sight sees every record of a home or none, so a name
resolving to a held record is of a home the reader sees.

The writers that add a name, read on `main` at `47a634704`: the observer names the leaving
episode, which its run holds, and a ticketed confirmation's approval episode, which it reads
first, but not the asking activation's, which a capture failure, retention, a sweep or a forget
may have deleted (hence §2:4). A lineage names memories read through the same store, or in the
same batch. A takeover's names are admitted activations whose episodes may since have been
deleted, hence §2:5; only an input whose author is established as a person is shown running work,
and only that person's (ADR-0349 §5:2, §5:5). No production path calls `record_use` or
`write_labels`. The story store already refuses an unresolved member story (`unknown_story`), and
the conversation store an unresolved reply target (`no_such_reply`).

### 3. A story a work starts

> **Normative.** Planning's start call (ADR-0300 §10:3) makes the story and its first notes in one
> write, through the work's bound story store, and reads nothing of the story back. A refused note
> refuses the start, and nothing is written.

> **Normative.** ADR-0383 §7:4's list of a work's own records stays closed. A story a work
> starts lands in the home ADR-0383 §4:1 gives it, and a work whose sight does not see that home
> does not see the story afterwards: a later note, link or read naming it answers as for a story
> never written (ADR-0383 §8:2).

> **Normative.** `StoryStore.create` takes the story's first notes as a keyword-only argument,
> empty by default, each a value of one `core/types.py` model carrying what `append_note` takes:
> the note's text, its author, the activation it was written during and its outside mark. The
> store writes them after the members, in the same transaction, logs each as `append_note` logs a
> note, and where any is refused refuses the whole create, writing nothing.

A start inside a larger story reads that story first, so a work that does not see its home names
none. A group's stories are held, and ADR-0383 §4:7 makes the new story theirs. The story-links
stage reads nothing back and is unchanged. Making the story the starting activation's own was set
aside: every note another work adds to it later would reach that work.

### 4. The pin pass

> **Normative.** The pass ADR-0338 §9:6 makes at the start of each observer run is an ADR-0384
> run. It is run once for each person domain ADR-0384 §1:3 rules, and reads and writes by
> `Sight.of_run` for that domain (ADR-0383 §6:8), under ADR-0384 §3 to §5 and §7.

> **Normative.** It runs where ADR-0338 §9:6 puts it, in the observer's run before its episodes,
> on no row of its own. The observer binds the person-model store, the memory store and the memory
> writer to the run's sight through the holder it binds them to an episode's sight with, and
> holds no store unbound for the pass.

> **Normative.** The pass is not run for the hub's shared things. A pin is a person's on their
> own profile, and a `pinned` support on a memory of another home names a record of another home
> (ADR-0383 §4:7).

> **Normative.** The pass before a retiring write (ADR-0338 §9:9) is part of the episode's run,
> and reads and writes by that episode's sight, as every read of a producer does (ADR-0383 §7:7).

### 5. A work with no recorded facts

> **Normative.** A work whose facts were not recorded (ADR-0368 §2:4) has a work's sight: an
> anyone bound alone, and its activation. Its episode, its effects and the approval requests it
> asked are its own (ADR-0383 §7:4), and it sees nothing else.

> **Normative.** A work whose facts are recorded later is made its sight again as ADR-0383 §6:6
> rules, the meet of the two, so it never widens.

> **Normative.** `Sight.of_work` takes its facts as `WorkFacts | None`. Given none, it makes a
> work's sight of an anyone bound alone and the activation it is given, and reads no sender.

ADR-0387 §6:5 already assumes such a work has its own records. Opening no episode for it was set
aside: that would lose the one record of a defect. A work with facts and no activation id is
unchanged: with no activation, nothing can be its own.

### 6. A limit a store checks at a write

> **Normative.** A check a store makes at a write over records other than the one written, a cap,
> a count, a chain or pending limit, or whether an equal record is already waiting or already
> done, is a figure of the records the bound store holds (ADR-0383 §7:2, §8:1), and is not one of
> ADR-0383 §7:11's checks.

> **Normative.** A write a store checks against a cap, a count, a chain or pending limit, or
> whether an equal record is already waiting, is made only where the writer's sight, as it stands
> at the write (ADR-0383 §6:6), sees the home the record lands in. Where it does not, code does
> not make the write, and the call answers as the same call answers today where it is not offered
> to that work.

> **Normative.** For a work whose sight does not see its own home, the effect claim's backstop
> (ADR-0306 §5:9, §5:11) is judged against the effects it holds: its own activation's (ADR-0383
> §7:4).

The limits, and the writers that reach them, on `main` at `5e2e824bd`:

| Limit | Store member | Writer | Its sight at the write |
| --- | --- | --- | --- |
| The cap; the duplicate lookup | `NotificationStore.admit` | The upcoming-event producer | §7's, which sees the home it writes into |
| The chain and pending limits; the replace and wait | `PlanStore.write_scheduled_task` | A person's work's spawn | A person bound for the owner, which sees the owner's domain |
| An equal request already waiting | `PlanStore.write_approval_request` | A person's work's request | The same |

Two cases were checked against the code. An owner's work cannot take in an unidentified sender's
input: a join is made only between inputs of one identified author (ADR-0349 §7:5,
`InputStanding.meets`), so its sight at the write is the one it planned with. An owner's work
lowered to weak keeps a person bound for the owner, since no level enters a sight (ADR-0383 §6:9).
So §6:2 refuses no write code makes today, and keeps the limits whole should a sight narrow
between the offer and the write. The backstop's narrowing is bounded: what such a work may do at
all is decided call by call by the check (ADR-0367 §4:1), and no refusal tells it of an effect it
does not hold. The other checks a write makes read every record, as built: an identifier, a
revision and a stop (ADR-0383 §7:11), and the keys code mints for one use, a spent part, a
ticket's key and a message's effect key (ADR-0350 §12:9), each that record's identity under
ADR-0383 §7:11's second item.

### 7. The upcoming-event producer

> **Normative.** The upcoming-event producer's reads and writes are an ADR-0384 run's, by
> `Sight.of_run` for the domain its source's home is in (ADR-0383 §4:3), made by code once for
> each pass in one place. It reads the person-model store and writes through the notification
> store, each bound to that sight, under ADR-0384 §3:3, §4, §5 and §7. Nothing else of ADR-0384
> §2's row changes: it is no upkeep job, and what it reads to find what is coming is its source.

> **Normative.** Its cap and its duplicate lookup are then figures of every notification of the
> home it writes into, and hold whole under §6.

The producer reads two stores to write a record, the zone through `RulingPolicy.pick` and the
cap and duplicates through `NotificationStore.admit`, so ADR-0384 §2's "reads a source, not a
store" does not hold of the code. Naming it with ADR-0383 §7:8's unbound callers would keep a
reader that counts across homes. In this milestone the domain is the owner's.

### 8. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0383 §4:8, in the addition alone: a
> withholding memory store also refuses a name a write adds that resolves to no record it holds,
> save a work's own takeover lineage (§2:1, §2:2, §2:5), and ADR-0383 §6:4, in the addition
> alone: a work whose facts were not recorded has a work's sight of an anyone bound and its
> activation (§5:1, §5:3). Every other clause stands.

> **Normative.** This decision partially supersedes ADR-0384 §2:1 and its table, in the addition
> alone: the pin pass is a fourth job it covers, run in the observer's run (§4); and the table's
> upcoming-event producer row, in the addition alone: its reads and writes are a run's, by the
> sight of its source's home's domain (§7). Every other clause stands, the observer's row included.

> **Normative.** This decision partially supersedes ADR-0289 §3:1, in the addition alone:
> `create` also takes the story's first notes, written in its one write (§3:1, §3:3). Every other
> clause stands.

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0383,
> ADR-0384 and ADR-0289 and in a dated header note on each, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. They take effect on its ratification.

| Clause | How it stands |
| --- | --- |
| ADR-0383 §4:7, §7:2, §7:4, §7:5, §7:11, §8:1, §8:2, §8:3 | Stand, read through §2, §3 and §6 |
| ADR-0383 §6:6, §6:7, §6:8, §7:7, §9:2 | Stand: §4 to §7 apply them |
| ADR-0328 §4:5, §4:7 | Stand: §2:4 narrows when a confirmation is given, which §4:5 bounds from above |
| ADR-0338 §9:6, §9:8, §9:9 | Stand, read through §4 |
| ADR-0306 §5:9, §5:11 | Stand, read over held records (§6:3) |
| ADR-0300 §10:3; ADR-0387 §6:5 | Stand: §3 and §5 build them under a withholding store |
| [#3727](https://github.com/leonapivato/ai-assistant/issues/3727) | Narrowed: §2:1 refuses its first write through a withholding bound store, so it stays only for an unbound store's writes |

### 9. What building it needs

Lane B11 builds it, with the switch, or a lane cut before it.

- **`core/types.py`:** `Sight.of_work` as §5:3 states, and the first note's model §3:3 names.
- **`core/protocols.py`:** `StoryStore.create`'s notes, as §3:3 states. `MemoryStore.bound`'s and the write members' docstrings move
  the name judgement off the stored row and state §2:1 to §2:3 and §2:5; each conformance suite
  gains the cases: a withheld name and a never-written one refused alike, an already carried name
  not judged again, a name held of another home refused as today, and a takeover lineage naming a
  deleted episode written, the capture kept. `PlanStore.bound`'s and
  `NotificationStore.bound`'s docstrings state §6:1.
- **`core/errors.py`:** `UnresolvedEvidenceError`'s docstring widens from a support's episode to
  any name §2:1 refuses. No new error.
- **Stores:** the three memory stores and the canonical fake judge an added name over held
  records in the withholding mode; the story stores and their fake take a create's notes.
- **Orchestration:** `StoryCalls._start` makes one create carrying its notes; the observer drops
  a confirmation whose asking episode is not held (§2:4) and runs the pin pass through its holder
  by the run's sight (§4); `ActivationState` makes a work's sight for a work with no facts (§5);
  the spawn and the approval request check the writer's sight against the record's home before
  they write (§6:2); the upcoming-event producer makes its run's sight once for each pass and
  reads and writes through stores bound to it (§7); the pin pass's sight and the producer's are
  made where every run's is, `upkeep.py:upkeep_run`. `PinConfirmations`, `NotificationWriteStage`
  and `RulingPolicy.pick` leave ADR-0383 §9:1's named test's list, and §9:2's admits the place
  that makes the producer's sight.
- **Tests, one for each limit:** the notification cap, the notification duplicate lookup, the
  chain limit, the pending limit and the already-waiting request each count every record of a
  home its writer's sight sees, and a writer whose sight does not see the home is not made the
  write and gets the not-offered answer.
- **Wire and formats:** none. No record gains a field, and no label moves.

## Consequences

- Under a withholding store, no record a reader sees names one it does not, and no refusal tells
  a withheld name from one never written.
- A ticketed memory whose asking work's episode is gone lands without its confirmation.
- An unidentified sender's work starts a story whole and sees nothing of it afterwards.
- No limit counts a record its writer does not see, and none is reached by a writer that does
  not see the home it writes into. A work that does not see its own home has its repeats caught
  among its own effects alone.
- The pin pass and the upcoming-event producer read through the filter, and neither holds a
  store unbound.
- A work with no recorded facts captures, freezes and deletes its own episode as any work does.
- **Revisit** when a second person or a group is admitted.

## Alternatives considered

- **Judge a name only against held records (choice (a) on #3711).** Set aside: a record could
  name a withheld record of another home, against ADR-0383 §4:7 and §8:3.
- **Make the name guard a write's own check (choice (c)).** Set aside: the refusal would then
  tell a withheld record from one never written, against ADR-0383 §4:8.
- **Count withheld records toward a limit, as a write's own check.** Set aside: a refusal over
  the limit would tell the writer how much it cannot see (ADR-0383 §8:1).
- **Name the pin pass or the upcoming-event producer with the unbound callers.** Set aside: each
  would keep a reader across every home, which ADR-0384 §7:1 rules out for upkeep.
