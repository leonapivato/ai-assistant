# 388. Before the stores withhold: a name a write adds must resolve, a story starts in one write, the pin pass is a run, and a work with no facts keeps its activation

- Status: Proposed
- Date: 2026-11-26
- Scope: an amendment to decisions D1 and D2 of milestone 22, "Every record has a home"
  (acceptance [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)). It settles what the build
  lanes found the merged decisions leave unsaid, or say two ways, for a build whose bound stores
  withhold: a name the memory store judges itself (§2), a story a work starts and does not see
  (§3), the observer's pin pass (§4), and a work with no recorded facts (§5). §6 and §7 are held
  (below). §8 records what it amends, §9 what building it needs.
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
  (§2:1 and its table, in the addition alone) and
  [ADR-0289](0289-a-story-store-holds-which-experiences-belong-to-the-same-matter.md) (§3:1, in
  the addition alone), as §8 records.

## Context

The stores are bound, and a work's stages, the observer and the upkeep runs read through sights,
all in the counting mode (ADR-0383 §7:10, §11:1). The last build lane switches them to withhold.
Four places would then do what no clause says, recorded on #3711 with their choices:

1. **A name the store judges itself.** ADR-0383 §4:8 gives a name of a record the writer's sight
   does not see the refusal a name of a record never written gets, and presupposes that one is
   refused. In the memory store only a support's episode is: the writer refuses one it does not
   hold (ADR-0328 §4:7). Every other name, a confirmation's asking activation and `ran_in`, a
   track-record entry's and a label's episode, a lineage outside the batch, an open question's
   parts and an episode's takeover lineage, is judged only where it resolves, and against every
   stored row, bound or not (`MemoryStore.bound`;
   [#3727](https://github.com/leonapivato/ai-assistant/issues/3727)). A withholding store would
   then refuse a withheld name of another home and accept one never written, which tells the two
   apart; judged over held rows alone, it would let a record name a withheld record of another
   home, against ADR-0383 §4:7 and §8:3.
2. **A story a work starts.** `StoryCalls._start` creates the story through the work's bound
   store, then writes its first notes through it. A work whose sight does not see the home it
   writes into, an unidentified sender's (ADR-0383 §4:4 and §6's table), does not hold the story
   it made, since ADR-0383 §7:4's list of its own records is closed. Its notes are refused as a
   write to a story it does not hold (ADR-0383 §7:5), and the call ends unfinished.
3. **The pin pass.** `PinConfirmations` (ADR-0338 §9:6) reads every person's pins and each pin's
   memory, and writes a `pinned` support for each, unbound. It reads for no ended work, so
   ADR-0383 §6:7 gives it no sight, and it is not one of ADR-0384 §2's jobs, so ADR-0383 §6:8
   gives it none.
4. **A work with no recorded facts.** Where `record_started` fails, the work reads by
   `Sight.of_producer(None, ())`, an anyone bound with no activation, because `Sight.of_work`
   takes recorded facts. Nothing is its own, so a withholding store would not give back its own
   episode: the freeze reads a mismatch, the deletion misses, and the episode stays open
   ([#3763](https://github.com/leonapivato/ai-assistant/issues/3763)).

None of the four is reached in the counting build, where a bound store holds every record.

## Decision

We will have a withholding memory store refuse a name a write adds that resolves to no record it
holds, withheld and never written alike; start a story and its first notes in one write; run the
pin pass as an ADR-0384 run; and give a work with no recorded facts a work's sight that keeps its
activation.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules the hub ADR-0383 §1:2 rules, and only the four points above.
> It changes nothing a bound store in the counting mode answers or refuses.

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

The names are those ADR-0383 §4:7 lists as they reach `memory.db`: an evidence pointer's episode
on a support, an operation or an open question, a confirmation's asking activation and
`ran_in`, a track-record entry's and a label's episode, a lineage, and an episode's taker and the
activation a joined input was taken from. A sight sees every record of a home or none, so a name
resolving to a held record is of a home the reader sees, and §8:3 holds.

The production writers that add a name were read against `main` at `47a634704`. The observer
names the leaving episode, which its run holds, and a ticketed confirmation's approval episode,
which it reads first; it does not read the asking activation's episode, which a capture failure,
retention, a sweep or a forget may have deleted. A lineage names memories the writer read
through the same store, or ones in the same batch. A takeover's names are admitted activations,
and only an input whose author is established as a person is shown running work, and only that
person's (ADR-0349 §5:2, §5:5), so taker and taken share whom they are for and each one's sight
holds the other's episode. No production path writes `record_use` or
`write_labels`.

> **Normative.** The observer gives a candidate no confirmation (ADR-0361 §5:10) where the asking
> activation's episode is not held, as it already gives none where the approval's episode is not,
> so §2:1 refuses no memory for it.

The other stores already refuse an unresolved name: the story store a member story it does not
hold (`unknown_story`), and the conversation store a reply target (`no_such_reply`).

### 3. A story a work starts

> **Normative.** Planning's start call (ADR-0300 §10:3) makes the story and its first notes in one
> write, through the work's bound story store, and reads nothing of the story back. A refused note
> refuses the start, and nothing is written.

> **Normative.** ADR-0383 §7:4's list of a work's own records stays closed. A story a work
> starts lands in the home ADR-0383 §4:1 gives it, and a work whose sight does not see that home
> does not see the story afterwards: a later note, link or read naming it answers as for a story
> never written (ADR-0383 §8:2).

A start that sits inside a larger story first reads that story through the bound store, so a work
that does not see its home names none, and the link runs only where the work sees the story it
made. A group's stories are held, and §4:7 makes the new story theirs, so a group needs nothing.
The story-links stage starts a story without reading it back and is unchanged. Making the story
the starting activation's own was set aside: every note another work adds later would reach it.

### 4. The pin pass

> **Normative.** The pass ADR-0338 §9:6 makes at the start of each observer run is an ADR-0384
> run. It is run once for each person domain ADR-0384 §1:3 rules, in this milestone the owner's,
> and reads and writes by `Sight.of_run` for that domain (ADR-0383 §6:8), under ADR-0384 §3 to
> §5 and §7.

> **Normative.** It runs where ADR-0338 §9:6 puts it, in the observer's run before its episodes,
> on no row of its own. The observer holds its stores in the holder that binds the stores for a
> pass, and binds the person-model store, the memory store and the memory writer to the run's
> sight for it, as it binds them to an episode's. It holds no store unbound for the pass.

> **Normative.** The pass is not run for the hub's shared things. A pin is a person's on their
> own profile, and a `pinned` support on a memory of another home names a record of another home
> (ADR-0383 §4:7).

> **Normative.** The pass before a retiring write (ADR-0338 §9:9) is part of the episode's run,
> and reads and writes by that episode's sight, as every read of a producer does (ADR-0383 §7:7).

With one person the run reads every pin the unbound pass reads today. Its write is the one
ADR-0383 §4:5 already gives a run, into the domain it tends.

### 5. A work with no recorded facts

> **Normative.** A work whose facts were not recorded (ADR-0368 §2:4) has a work's sight: an
> anyone bound alone, and its activation. Its episode, its effects and the approval requests it
> asked are its own (ADR-0383 §7:4), and it sees nothing else.

> **Normative.** A work whose facts are recorded later is made its sight again as ADR-0383 §6:6
> rules, the meet of the two, so it never widens.

It is then read by the bounds a producer reading its episode gets (ADR-0383 §6:7), with its own
records held as every work's are, which is what ADR-0387 §6:5 already assumes. Opening no episode
for such a work was set aside: it would lose the one record of a defect. A work with facts and
no activation id is unchanged: with no activation, nothing can be its own.

### 6. A limit a store enforces at a write

Held. Brought to the coordinator before its clause is written.

### 7. The upcoming-event producer's reads and writes

Held. Brought to the coordinator with §6.

### 8. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0383 §4:8, in the addition alone: a
> withholding memory store also refuses a name a write adds that resolves to no record it holds
> (§2:1, §2:2), and ADR-0383 §6:4, in the addition alone: a work whose facts were not recorded
> has a work's sight of an anyone bound and its activation (§5:1). Every other clause stands.

> **Normative.** This decision partially supersedes ADR-0384 §2:1 and its table, in the addition
> alone: the pin pass is a fourth job it covers, run in the observer's run (§4). Every other
> clause stands, the observer's row included.

> **Normative.** This decision partially supersedes ADR-0289 §3:1, in the addition alone:
> `create` also takes the story's first notes, written in its one write (§3:1). Every other
> clause stands.

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0383,
> ADR-0384 and ADR-0289 and in a dated header note on each, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. They take effect on its ratification.

| Clause | How it stands |
| --- | --- |
| ADR-0383 §4:7, §7:2, §7:4, §7:5, §7:11, §8:2, §8:3 | Stand, read through §2 and §3 |
| ADR-0383 §6:7, §6:8, §7:7 | Stand: §4 and §5 apply them |
| ADR-0328 §4:5, §4:7 | Stand: §2:4 narrows when a confirmation is given, which §4:5 bounds from above |
| ADR-0338 §9:6, §9:8, §9:9 | Stand, read through §4 |
| ADR-0300 §10:3; ADR-0387 §6:5 | Stand: §3 and §5 build them under a withholding store |
| [#3727](https://github.com/leonapivato/ai-assistant/issues/3727) | Narrowed: §2:1 refuses its first write through a withholding bound store, so it stays only for an unbound store's writes |

### 9. What building it needs

Lane B11 builds it, with the switch, or a lane cut before it.

- **`core/types.py`:** `Sight.of_work`'s `facts` parameter becomes `WorkFacts | None`; given
  `None` it makes a work's sight of an anyone bound alone and the activation it is given, its
  senders not read (§5:1). A model for a story's first note, carrying what `append_note` takes
  (the text, its author, the activation it was written during and its outside mark).
- **`core/protocols.py`:** `StoryStore.create` gains a keyword-only `notes`, a sequence of that
  model, empty by default, written after the members in the one transaction and each logged as
  `append_note` logs a note (§3:1). `MemoryStore.bound`'s and the write members' docstrings move
  the name judgement off the stored row and state §2:1 to §2:3; each conformance suite gains the
  cases: a withheld name and a never-written one refused alike, an already carried name not
  judged again, and a name held of another home refused as today.
- **`core/errors.py`:** `UnresolvedEvidenceError`'s docstring widens from a support's episode to
  any name §2:1 refuses. No new error.
- **Stores:** the three memory stores and the canonical fake judge an added name over held
  records in the withholding mode; the story stores and their fake take a create's notes.
- **Orchestration:** `StoryCalls._start` makes one create carrying its notes; the observer drops
  a confirmation whose asking episode is not held (§2:4) and runs the pin pass through its holder
  by the run's sight (§4); `ActivationState` makes a work's sight for a work with no facts (§5).
  ADR-0383 §9:1's named test drops the pin pass from its list.
- **Wire and formats:** none. No record gains a field, and no label moves.

## Consequences

- Under a withholding store, no record a reader sees names one it does not, and no refusal tells
  a withheld name from one never written.
- A ticketed memory whose asking work's episode is gone lands without its confirmation.
- An unidentified sender's work starts a story whole and sees nothing of it afterwards.
- The pin pass reads through the filter, and the observer holds no store unbound for it.
- A work with no recorded facts captures, freezes and deletes its own episode as any work does.
- **Revisit** when a second person or a group is admitted.

## Alternatives considered

- **Judge a name only against held records (choice (a) on #3711).** Set aside: a record could
  name a withheld record of another home, against ADR-0383 §4:7 and §8:3.
- **Make the name guard a write's own check (choice (c)).** Set aside: the refusal would then
  tell a withheld record from one never written, against ADR-0383 §4:8.
- **Name the pin pass code's own bookkeeping, unbound.** Set aside: it would leave a reader
  across every home, which ADR-0384 §7:1 rules out for upkeep.
