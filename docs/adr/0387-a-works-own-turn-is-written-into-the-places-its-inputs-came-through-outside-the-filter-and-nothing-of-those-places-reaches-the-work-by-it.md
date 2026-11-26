# 387. A work's own turn is written into the places its inputs came through outside the filter, and nothing of those places reaches the work by it

- Status: Proposed
- Date: 2026-11-26
- Scope: an amendment to decision D1 of milestone 22, "Every record has a home" (acceptance
  [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)). It decides which places are a
  work's own (§2), which writes of its turn go there outside the filter (§3), how a list names
  them (§4), what stays withheld (§5) and the edges (§6), and records what it amends (§7).
- Authorization: the coordinator's proposal under the owner's delegation of ratification. The
  coordinator told the owner the pick on 2026-11-26 and invited an objection; none came. The
  owner's only words here are #3709's record: on 2026-11-26, "Yes, agreed", to the milestone's
  scope. The owner has ruled nothing in this decision. The coordinator assigned 0387 and ratifies
  it once its reviews are green.
- **Contract-surface decision; a decision only.** It changes no Protocol, type or code. It amends
  a contract decision, so it takes the adversarial and the architecture review.
- **Partially supersedes**
  [ADR-0383](0383-each-record-carries-its-home-and-every-read-a-work-a-producer-or-a-run-makes-is-of-a-store-bound-to-one-sight-which-answers-as-though-it-held-only-what-that-sight-sees.md)
  §7:7, §7:9, §8:2 and §9:1, each in the addition alone (§7).

## Context

ADR-0383 has every read a work makes go through a store bound to its sight (ADR-0383 §7:7). A
bound store answers a conversation it does not hold as one never started, for a write too
(ADR-0383 §7:2, §8:2). No class under `orchestration/` may hold the conversation store unbound
except the holders ADR-0383 §9:1 names. An unidentified sender's work is for the owner, its
conversation is the owner's, and its sight sees nothing but its own records (ADR-0383 §6's
table). `ConversationStore.bound` says "how a work's turn reaches its own input's place is not
this store's", and no merged clause says whose it is. Once the stages are handed bound stores that
withhold, the code on `origin/main` at `fd24769ca` would:

1. **lose the answer**: `ChatWriter.send` gets `UnknownConversationError` from `append_message`,
   logs the conversation as gone and returns `None`, so `_ConversationWriter.deliver` in
   `orchestration/phase_path.py` records the message failed;
2. **refuse the turn**: `Engine._begin_conversation_stage` calls `mark_active` through
   `Conversations.begin`, which raises `UnknownConversationError`;
3. **report the capture degraded**: `ActivationWriter._record_turn` gets `None` from
   `record_turn`, so the episode is kept (ADR-0293 §2:7) but never verified (ADR-0283 §7:2);
4. **drop the place from the list**: `PlaceLists._held` gets `None` from `get`. Today only a
   person's work keeps a list (`Engine._scheduling`, ADR-0368 §9:5), and its sight sees the
   owner's domain, so this case does not arise until there is a second person.
   `Engine._shown_connections` already names the origin from the input.

Nothing else in a work's turn names its input's place in a store that carries a home. Three
callers touch that place outside any work's stages, and ADR-0383 §7:8 leaves them unbound. The
chat reader, a sensor, marks messages taken in as the work is admitted, before its stages run
(ADR-0293 §1:2, §6:6 to §6:8). The task sensor confirms a message after a restart
(ADR-0350 §8:11). The engine's start closes an episode left open (ADR-0286 §7:2). The line's intake and outbox carry no home (ADR-0383 §3). The
window and history reads are reads, and are meant to be withheld.

## Decision

We will write a work's own turn into the places its inputs came through as the unbound store
writes it today, name those places from the inputs, and keep every read of them, or of anything in
them, a read of the work's bound store.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules only where a work's own turn is written and how a work's own
> places are named. It changes no read's answer, no record's home, no check, no mark and no place
> a work may send into.

### 2. A work's own places

> **Normative.** A work's own places are the places ADR-0367 §4:7 reads: the place each input it
> holds came through, its trigger's and each joined input's, absorbed or taken, as its inputs
> record them.

> **Normative.** In an approval's work, each place ADR-0382 §2:1 keeps outside the check is also
> one of its own places, read as ADR-0382 §2:2 reads it. Where that place cannot be read,
> ADR-0382 §4:4 keeps none.

> **Normative.** No other place is a work's own: not a task's suggested places (ADR-0382 §4:3),
> and not any other connection the work is shown (ADR-0364 §9:3).

> **Normative.** Code decides whether a place is one of a work's own from the work's inputs, and
> in an approval's work from the asking activation as §2:2 reads it, never from a model's output
> or an input's text.

ADR-0382 keeps an approval's work's message there outside the check "as if that work were the
asking one answering there". The same ground lets the message be written there.

### 3. The writes of a work's own turn

> **Normative.** The engine makes three kinds of write of a work's own turn outside the filter,
> and not through the store bound to the work's sight: it marks the conversation the work's
> trigger came through active as the turn begins (ADR-0074 §2); it writes a message of the work's
> into one of its own places (ADR-0293 §6:10, §6:12); and it records that the work's episode
> landed in the conversation its trigger came through (ADR-0283 §6:2, §7:1).

> **Normative.** No other write is made outside the filter for a work. A message into any place
> that is not one of its own is written through its bound store (ADR-0383 §7:5).

> **Normative.** Each write of §3:1 is made as the unbound store makes it today, with every check
> the store makes of its own: a write repeated under an effect is that message (ADR-0350 §12:9),
> and a conversation absent or stamped deleted refuses the write.

> **Normative.** What such a write gives back reaches the work only as whether it was made. A
> message's position is kept in code's delivery bookkeeping alone, the work's effect record and
> its confirmation (ADR-0350 §12:9, §8:11), and reaches no model and no surface. No field of a
> conversation a write returns reaches a stage, a model or a surface.

A conversation numbers its own messages, so the gap between a work's input and its reply would
count the messages the work does not see. ADR-0369 §10:6 forbids that count, and ADR-0383 §8:5's
store-wide figures do not include a position.

### 4. Naming its own places

> **Normative.** Where a list a work is shown, its place list (ADR-0350 §5:10) or its Connections
> section (ADR-0364 §3:5), names one of its own places, code names it from the input it came
> through, and not from a read of its bound store.

> **Normative.** Whether one of a work's own places still stands, which decides whether it stays
> on a list (ADR-0350 §5:8), is answered outside the filter, as §3's writes are. The work gets
> that answer and nothing more.

> **Normative.** A place on a list that is not one of the work's own, a task's suggested place or
> a recent conversation among them, is read through the bound store (ADR-0383 §7:7).

Whether a place stands tells the work no more than the refusal of its own message there would.

### 5. Nothing of the place reaches the work

> **Normative.** Nothing here gives a work a record, field, count or message of any of its own
> places: its earlier messages, its devices and the conversation's fields reach the work only
> through its bound store (ADR-0383 §7:7, §7:9), a message §3 wrote included.

A message is held by its home alone, since ADR-0383 §7:4 makes no message a work's own. A work
whose sight does not see that home knows what it wrote from its own effect records.

> **Normative.** Each record §3 writes carries the home ADR-0383 §4 gives it today. Marking a
> conversation active and recording a turn change no home (ADR-0383 §4:6).

> **Normative.** The check, the mark, the place list and the place rules each refuse what they
> refuse today (ADR-0367, ADR-0370, ADR-0382). §3 decides only how a write already allowed is made.

These writes are not reads through a bound store, so ADR-0383 §11's count records nothing for them.

### 6. The edges

> **Normative.** A deleted place refuses §3's writes as it does today. Deleted before the turn
> begins, marking it active is refused, and so is the turn. Deleted while the work runs, a
> message is not written and its effect fails as gone, recording the turn writes nothing and the
> episode is kept (ADR-0293 §2:7), and §4:2 answers that the place is gone.

> **Normative.** On the line, the answer leaves through the outbox, and no conversation record is
> marked or recorded: the hub keeps no copy of the chat (ADR-0323 §2:5). The line's intake and
> outbox carry no home, so this decision touches nothing there.

> **Normative.** A work with inputs from several places may write a message into each of them, as
> the place rules allow. Marking active and recording the turn reach only the conversation its
> trigger came through, as today. A trigger that came through no conversation, such as a task's,
> a signal's or an approval's, marks and records nothing.

> **Normative.** An assistant's message carries no `replies_to` today, and this decision gives it
> none. A decision that gives it one rules how the message it names is read.

> **Normative.** A work with no facts (ADR-0368 §2:4; code reads it as for no one) has its own
> places like any other work, and §2 to §5 hold for it alike.

### 7. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0383 §7:7, in the addition alone: whether
> one of a work's own places still stands (§4:2) is not a read of its bound store.

> **Normative.** This decision partially supersedes ADR-0383 §7:9, in the addition alone: each
> place a work's input came through reaches the work with that input, named by it (§4:1), and the
> engine writes the work's turn there outside the filter (§3:1).

> **Normative.** This decision partially supersedes ADR-0383 §8:2, in the addition alone: §3's
> writes and §4:2's answer are also outside it, and give a work what they give today.

> **Normative.** This decision partially supersedes ADR-0383 §9:1, in the addition alone: the
> holders that make §3's writes and answer §4:2 may hold the conversation store unbound. Each
> uses it for those alone and hands it to no stage, and the named test admits them.

ADR-0383 §7:5 stands, since §3's writes are not made through a bound store. ADR-0383 §7:8 stands
too: these holders are not ADR-0383 §7:7's readers, and this is the decision that rules them,
while the chat reader, the task sensor and the closing of open episodes stay as ADR-0383 §7:8
leaves them. ADR-0383 §4, §7:2, §7:4, §7:11, §8:1, §8:5 and §11 stand, read through §3:4 and §5.
No other clause needs a record. §2 reads ADR-0367 §4:7 and ADR-0382 §2 through. §4 reads
ADR-0350 §5:8 and §5:10, ADR-0361 §6:7 and §7:3, and ADR-0364 §3:5 and §9:3 through. §3 makes
the writes of ADR-0074 §2, ADR-0283 §6:2 and §7:1, and ADR-0293 §6:10 and §6:12 as they are made
today.

### 8. What building it needs

> **Normative.** Building this decision changes nothing in `core/protocols.py` or `core/types.py`.

The lane that hands the stages their bound stores builds it, in `orchestration/` and the
composition root. Four things go through the unbound conversation store, and nothing else does:
marking the trigger's conversation active, writing a message into one of a work's own places,
recording the turn, and answering whether one of its own places still stands. The chat writer
uses the bound store for every other place. ADR-0383 §9:1's named test admits exactly those
holders. The lane also ships tests that, under a store that withholds, an unidentified sender's
work begins its turn, writes its answer, has its turn recorded and verified, and still reads none
of its chat's earlier messages.

## Consequences

- A work whose sight does not see the place it was asked in, an unidentified sender's among them,
  answers there and is captured as today, and reads nothing of that place.
- A work whose sight sees its places notices no change.
- The holders that write a work's turn keep the conversation store unbound for those writes alone,
  and the named test lists them.
- **Revisit** when another person's or a group's place exists (milestone 24), or when an
  assistant's message gains a reply.

## Alternatives considered

- **Bound stores hold a work's input conversation as its own (ADR-0383 §7:4).** That would also
  give the work the conversation's fields and devices through every read member, which
  ADR-0383 §6's table withholds.
- **Widen an unidentified sender's sight to its conversation.** That would give the work its
  chat's earlier messages, which #3709's record and ADR-0383 §6 withhold.
- **Write through the bound store and accept the loss.** That would leave the answer unwritten and
  the turn refused for every work whose sight does not see its own place.
