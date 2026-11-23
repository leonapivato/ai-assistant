# 372. A place has a start level that what is said there carries, and a work re-runs once without what is narrower than its story

- Status: Proposed
- Date: 2026-11-22
- Scope: an amending decision on
  [ADR-0370](0370-every-work-carries-a-mark-of-who-may-see-all-it-has-seen-which-starts-at-its-places-audience-and-only-shrinks-and-a-send-reaching-anyone-outside-it-needs-a-yes.md)
  (the audience mark), on the audience side alone, recording two things the owner ruled on
  2026-11-22 in the methods walk with the coordinator: a start level per place, and the re-run by
  story. It decides a place's start level (§2); the audience label every block carries (§3); who
  may see what was said, which answers
  [#3636](https://github.com/leonapivato/ai-assistant/issues/3636) (§4); what a work's floor, what
  is put in front of it and its mark become (§5); the re-run (§6) and what the controller needs for
  it (§7). §8 works the cases, §9 records what it does to earlier decisions, §10 names the contract
  changes it would need, §11 what it leaves to others, and §12 what it settled where the rulings
  left a point open.
- Authorization: the owner's rulings of 2026-11-22, given in the methods walk with the coordinator.
  There is no proposal file. Their words, verbatim, all of 2026-11-22. The two scores: "use the 2
  score from here on" (the words of this decision). The start level, first raised: "the starting
  point doesnt have to be at the threshold, it could start at everyone too, but this is a setting
  for a specific place. right?" (§2:1). Why: "A card on every utward send from a private chat isnt
  what I want and I think the 1.1 thing we dismissed might fix it, what do you think." And: "If in
  my private chat, I dont have some long standing rule where everything I say is private, then what
  we talk about can be starting at a wider level, and it may be able to do this without a card,
  depending on the context in the chat before it." (§2, §5:1). In between: "yeah and it can be
  inbetween private and anyone too." (§2:1). The fetch: "depends on the setting, I think thats fine
  tho, it can be 1 general fetch that gathers what would have been in front." (§5:3). A model
  narrows: "But yes the model can narrow it, but never widen it, based on its discretion." (§3:6,
  §3:8). One label, through memory: "I think they should, like the episodic memory, that goes into
  short-term memory, that goes into other activations too. But it should be filtered by the
  audience." (§3, §4:2). The instruction: "it looks like the instruction should also count, but the
  instruction should only be able to narrow, widening should be with a card for now" (§3:1, §3:8).
  Confirming the rule: "overall looks good, but 8 is an interesting case.", to "Do these outcomes
  match what you want, so that I can record the start-level rule as ruled?" (§2, §3, §5). Said in a
  place: "I dont think this means that it necesarily widens a blocks label if its said in a place,
  but that exact block in that place has that places audiences score." (§3:1, §3:2, §3:5).
  Scenario 8, when open: "But it could also narrow the episode, and not narrow the actually message
  that goes into the family chat, so this way people dont see the memory, but the message goes
  without hte card, what do you think." Settled: "Yes, move on", to "Settle scenario 8 as your
  second version and move to the authority score?" (§3:7, §8). What the re-run is for: "something
  in this chat history or some other context is causing it to be more narrow, and that context has
  nothing to do with the current work, maybe there could be a way of removing that and continuing
  with the wider audience." Stories: "Understanding connects to a story right. So if it connects to
  a story that has a wider audience, maybe it tries to recall itself, but without the stuff
  narrowing it down. Then continues from there, what do you think?" The re-run itself: "I was
  thinking that it literally re-runs understanding, but removes all context that has a narrower
  audience and continues as normal, which do you think is better". Ruled: "Yes, ruled", to "Record
  the re-run mechanism as ruled?" (§6). Both scores: "if i can it should, right, why not.", to "Do
  you agree that one re-run should cover both scores?" (§6:11). Lost context: "But what if by doing
  that it loses context it needs. I guess it can fetch for it" (§6:6, §6:10). The dispatch: "Yes,
  mark it done and dispatch ADR-0372". The coordinator assigned 0372 and ratifies it, under the
  owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides what every block carries, who may see it and what a work is shown, which
  bounds the `core` types the build makes, so it takes the adversarial and the architecture review.
  Building it is a breaking change under golden rule 5, through the `core` changes §10 names, none
  of which is made here. It dispatches no implementation (§1:2).
- **Partially supersedes**
  [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md)
  (§3:3's admitted differences and §3:8's *no field is added for a stage's result*, each in the
  addition alone: the re-run's recall),
  [ADR-0308](0308-recall-runs-again-on-what-understanding-found-and-outside-content-reaches-planning-only-as-a-digests-evidence.md)
  (§2:8 and §2:10, each in the addition alone),
  [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md)
  (§3:9, in the addition alone),
  [ADR-0369](0369-a-record-lands-in-the-domain-of-whom-its-work-is-for-sharing-rules-open-a-domain-and-default-to-private-every-read-is-filtered-to-who-may-see-and-each-person-sees-deletes-and-exports-their-own.md)
  (§3:4, §6:1 and §6:3, each in the addition alone) and
  [ADR-0370](0370-every-work-carries-a-mark-of-who-may-see-all-it-has-seen-which-starts-at-its-places-audience-and-only-shrinks-and-a-send-reaching-anyone-outside-it-needs-a-yes.md)
  (§3:1, in a message's and a
  signal's floor; §3:2 and §3:4, for the first pass and in reading the cut; §4:1, §4:2 and §4:5,
  each in the addition alone; §4:3, in who may see a message), as §9 records.

## Context

ADR-0370 gave every work a mark, "the set of people who may see everything its models have been
shown so far" (ADR-0370 §4:1), which starts at the work's floor, "for a message, the audience of
the place it came from" (§3:1, §4:2), and checks every send against it (§5:1). It counted the
instruction (§4:1), and it counted a message, and a message shown from a place's window, as seen by
"the audience of the place it was said in or arrived in" (§4:3). In a private chat the floor is the
person alone, so every send from it to anyone else needs a card (ADR-0370 §9's rent case), unless
a standing approval covers that place (§6). In a shared place, anything narrower than the place is
kept from being put in front of the work and reaches it only by a fetch (§3:2), the chat's own
earlier private turns included.

ADR-0369 lands every record in the domain of whom its work is for (ADR-0369 §2:1), keeps a domain
private by default (§3:4), and lets a person see another domain's record only as §6:1 lists. #3636,
filed while ADR-0370 was written, found that the record of an exchange in a shared place lands in
one member's domain, so other members' works may not read it, though every member saw it happen.
The owner ruled #3636 on 2026-11-22: what is said in a place, by a person or by a work, can be seen
by whoever was in that place's audience when it was said, and someone who joins later gets only
what came after. Its amending decision on ADR-0369 §6:1 was owed.

**What the owner decided.** In the methods walk of 2026-11-22 the owner found ADR-0370's result in
a private chat was not what they want ("A card on every utward send from a private chat isnt what
I want"), and ruled, as read back to them and confirmed, a start level per place: a set of people
from the place's own audience up to anyone, set by the person whose place it is; what is said there
carries that level as its one audience label, both for what the person's works may send with no
card and for who may see it through memory, other people's works included; the instruction counts
at that level and can only narrow; a model may narrow a block and never widen one; widening is a
person's act; and what is narrower than the level is fetched when needed, possibly by one general
fetch. Beside it they settled that text said in a place is a block of its own carrying what that
place gave it when it was said; the walk's scenario 8, a private detail typed beside an instruction
to send in a place whose level is wider; and that a reviewed story summary is not a way to lift a
story's level. They then ruled the re-run by story, in six points, to take unrelated narrow context
out of a work rather than let it narrow the work, and agreed that one re-run covers both scores.

**Words.** A **work**, a **place**, a place's **audience**, a work's **floor**, **mark** and
**ceiling**, **put in front of**, **fetch**, **send**, **card** and **yes** are ADR-0370's, and a
bare **mark** is ADR-0370 §4:1's. The owner calls the mark a work's **audience score**, low meaning
narrow and high wide ("use the 2 score from here on"); this decision keeps "the mark". A **domain**,
**may see**, a **line**, a **sharing rule**, a **reach** and a **meet** are ADR-0369's. A
**story** and its **members** are ADR-0289's: a member is an activation or a story (ADR-0289
§2:2). A **block** is the owner's word for one thing a model of a work is shown, each item ADR-0370
§4:1 lists. A block's **audience label** is §3's. A place's **start level** is §2:1's; it is not a
level in ADR-0368's sense, which is how sure the hub is. Something is **said in a place** when a
person sends it from that place or a work sends it into it. The **first pass**, the **cut**, a
story's **audience** and **below the cut** are §6's. In this document a bare section reference,
such as §6:4, is to this decision's own clauses.

## Decision

We will give every place a start level, from its audience up to anyone, which what is said there
carries as its audience label; let a person see what was said where they were inside its label or
in the place's audience when it was said; start each work at that level; and, where what a work's
first pass of understanding was shown holds anything narrower than the story it links the input
to, re-run the work once from recall without it, counting only the second pass toward its mark.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and when, is
> the owner's planning call, made after it merges.

> **Normative.** Until a place's start level (§2), the audience labels (§3) and the re-run (§6) are
> built, every read, every send and every phase runs as it does today, and nothing in this decision
> changes what the running hub reads, shows, sends or asks.

> **Normative.** This decision admits no one, and nothing of it is among what ADR-0365 §1:3's
> provision for admitting another person needs built.

A place nobody sets has its audience as its start level (§2:2), so a work there starts where
ADR-0370 starts it. #3636 asked for its answer before any place two admitted people can both write
into is built; §4:1 is that answer, and its build is the owner's planning call like the rest.

### 2. A place's start level

The owner: "the starting point doesnt have to be at the threshold, it could start at everyone too,
but this is a setting for a specific place. right?", and "yeah and it can be inbetween private and
anyone too."

> **Normative.** Every place has a **start level**: a set of people, stated as a place's audience
> is (ADR-0370 §2:1), that takes in the place's audience and may be any wider set, up to anyone.

> **Normative.** A place's start level is its audience until it is set otherwise. Where the place's
> audience is not inside the level set, as where its declaration lapses (ADR-0370 §2:4), the level
> is read as the people of both.

> **Normative.** A place's start level is set by whoever may declare its audience under ADR-0370
> §2:2, by their own act. A call that widens it is checked as ADR-0369 §5:3 checks a widening, its
> default grant covering those people alone at a bar of normal; one that only narrows it is free,
> as ADR-0369 §5:2 has it.

> **Normative.** A change to a place's start level acts on what is said there from then on, and
> changes the audience label of nothing already said.

The start level is the place's own setting, kept with its audience on the place's record (ADR-0292
§9:5). It is not a sharing rule: a sharing rule names a kind of a domain, not a place (ADR-0369
§3:1, §3:2); it is read as it stands at each read (ADR-0369 §6:3, §8:1), where what a place gives a
block is fixed when the block is said; and it opens nothing past a record's reach (ADR-0369 §5:4).
Its default is the place's audience, as least privilege has it (ADR-0365 §3:1): a person who sets
nothing keeps ADR-0370's private chat. A person who wants their own chat to start at the family
sets it there, and what they then say in it is the family's to see. Who sets it is who says who
perceives the place, and widening it is held to the bar ADR-0369 gives any widening because it
widens who may see what is said. The act is named here; a surface for it is the build's.

### 3. Blocks and the audience label they carry

> **Normative.** A message a person says in a place, and an input no person sent that arrives in
> one, is a block of its own and carries as its **audience label** the place's start level when it
> was said or arrived.

> **Normative.** A message a work sends into a place carries as its audience label the people of
> the work's mark when it sent it together with the people of that place's audience then.

> **Normative.** Every other record a work writes, its episode included, carries as its audience
> label the work's mark when the record is written: for its episode, the mark when the episode is
> frozen (ADR-0286 §4:1), and while it is open, the mark as it stands.

> **Normative.** A record a producer writes after a work has ended (ADR-0369 §2:2) carries as its
> audience label the meet of the people who may see each record it was written from, for the mark
> (ADR-0370 §4:3, as §5:2 reads it), taken when it is written.

> **Normative.** An audience label is set when its block is said or written, each group it names
> denoting its members then. After that it only narrows (§3:6), and nothing widens it.

> **Normative.** A model of a work may narrow the audience label of a block of the domain its
> work's records land in, or of a record its work writes, at its own discretion or on a person's
> word, to any set inside that label. A person narrows the label of a block of their own domain as
> they narrow any record of it (ADR-0369 §5:2).

> **Normative.** Narrowing a block's audience label changes the mark of no work already shown the
> block, whose mark took the label when it was shown (ADR-0370 §4:2); it acts on every later
> reading.

> **Normative.** No instruction, message or model widens an audience label or a mark. A person
> lets more people learn what a work has seen only by a yes on a card for one send (ADR-0370 §5:3,
> §5:5), and lets more people see what is said, or a record, only by a standing change: the place's
> start level (§2:3), a sharing rule or a line on a record (ADR-0369 §3, §5).

"I dont think this means that it necesarily widens a blocks label if its said in a place, but that
exact block in that place has that places audiences score." §3:1 is that rule for what a person
says, and the instruction is such a block: it counts at the place's level, and the person can
narrow it by saying so, never widen it ("widening should be with a card for now"). §3:2 is the
same rule for what a work says, with one guard. Since a work's mark can be narrower than the
place's level, as when it has fetched a private calendar and replies in the private chat, a reply
cannot take the level, or a later reader would learn the calendar through it; it takes the mark it
had, which is everything its writer may pass on unasked, together with the people who heard it
said, as #3636 has it. A reply sent beyond the mark on a yes is so heard by the place's whole
audience, so "that exact block in that place" carries that place's audience, while the record it
came from, and the running work's mark, are not widened (ADR-0370 §5:5). §3:3 is the audience
counterpart of what ADR-0371 §5:1 has a work's writing carry on the authority side, which it
leaves as it is.

§3:6 rests on ADR-0217's rule that "a model may only narrow" (ADR-0217 §3:15) and on ADR-0369 §5:2,
narrowing being always free; "But yes the model can narrow it, but never widen it, based on its
discretion." §3:7 is scenario 8, as the owner settled it: in a private chat whose level is the
family, the person types a private detail beside "tell the family I'll miss dinner"; the model
narrows the record of the exchange, so later readers do not see the detail; the running work keeps
the mark it took when the text was shown, and the message goes with no card. A model unsure of the
text may still ask for a yes on its own, as ADR-0361 §2:3 lets planning narrow what runs freely.

### 4. Who may see what was said

> **Normative.** What is said in a place, by a person or by a work, may be seen by whoever was in
> that place's audience when it was said. Someone who joins later gets only what came after.

> **Normative.** A person may also see a record of another domain where they are inside the
> audience label it carries (§3) as it stands, a group it names counting only those who were its
> members when the record was said or written and still are.

> **Normative.** §4:1 and §4:2 are cases of ADR-0369 §6:1, beside its others. Each holds only
> where the person is in the record's reach and no limit covering them bears on the record, as
> ADR-0369 §6:1 reads a limit. Neither opens a record of a group's domain to someone who has left
> that group (ADR-0369 §9:3), and ADR-0369 §3:4's default is private save as they provide.

> **Normative.** A record that carries no audience label, such as one a connection brought in or
> one written before labels could be recorded, opens to no one through §4:2.

> **Normative.** An audience or an audience label naming anyone opens a record under §4:1 and §4:2
> to each person the hub admits. What a work with an unidentified sender reads stays ADR-0369
> §10:2's and §10:4's.

> **Normative.** Code decides §4:1 from the place's audience as it was when the thing was said, and
> §4:2 from the record's audience label as it stands and each named group's members as §4:2 counts
> them, as ADR-0369 §6:3 has it decide the rest, and no model decides it or takes part.

§4:1 is the owner's ruling on #3636, carried whole, and §4:2 is what the start level's one label
needs of it: "like the episodic memory, that goes into short-term memory, that goes into other
activations too. But it should be filtered by the audience." Neither can be stated inside ADR-0369
§6:1 as it stands, whose cases are exactly a person's own domain, a group's domain, a line and a
manager's power: a person's private chat set to the family lands in their domain (ADR-0369 §2:1),
and no line opens it. So this decision answers #3636 by adding both as cases of ADR-0369 §6:1, in
the addition alone. Each keeps §6:1's reach and its limits, so a record's reach still caps it
(ADR-0369 §5:4), and a person's limit still takes away (ADR-0365 §3:2). A later joiner gets what
came after because a label's groups and a place's audience are read as they were when the thing was
said (§3:5), as ADR-0369 §9 has a member see a group's records from when they joined; and a
label's narrowing acts on every later read (§3:7), so a model's narrowing in scenario 8 keeps the
detail from other people's works. What a work
is shown of it stays bounded by ADR-0369 §10, and then by the work's cut (§6:5). Whether a read
through §4 is entered in a person's access log is left (§11); ADR-0369 §13:1 is unchanged.

### 5. The floor, what is put in front, and the mark

> **Normative.** A work's floor (ADR-0370 §3:1), for a message or an input no person sent, is the
> audience label it carries (§3:1). For a task's occurrence and an approval's outcome it stays as
> ADR-0370 §3:1 has it, and a work holding several inputs has as its floor the meet of theirs.

> **Normative.** For the mark (ADR-0370 §4:3), the people who may see a message, an input no person
> sent or a message shown from a place's window are those inside the audience label it carries
> (§3:1, §3:2) as it stands when it is shown. Everything else ADR-0370 §4:3 names is read as written,
> with §4 among ADR-0369 §6:1's cases.

> **Normative.** A fetch of what is below a work's cut (§6:4) may be one general call that gathers
> what would have been put in front of the work at a narrower cut, within ADR-0369 §10. It is a
> fetch, and what it returns meets the mark when it is shown.

ADR-0370's line becomes:

```text
the sender  ⊆  the mark  ⊆  the start level of the place the stimulus arrived in
```

The mark starts at the floor (ADR-0370 §4:2), now the start level, and shrinks as it did. The
senders stay in it, since a place's start level takes in its audience (§2:1) and a work fetches no
more than its senders may see (ADR-0369 §10:2). ADR-0370 §5:7 stands: a work can answer its own
sender in the place the request arrived while its mark takes in that place's audience, which a
start level never narrows. ADR-0370 §6's standing approvals stand: a start level stops the card on
every outward send from a place, by starting what is said there wider, and a standing approval
still lets one person's works send into one named place beyond their mark. Whether a model is
shown its place's start level, and when it makes the general fetch, are the next prompt review's
("depends on the setting, I think thats fine tho, it can be 1 general fetch that gathers what would
have been in front").

### 6. The re-run by story

The owner: "I was thinking that it literally re-runs understanding, but removes all context that
has a narrower audience and continues as normal".

> **Normative.** A work's **first pass** is recall's first run and understanding's first run
> (ADR-0309 §3). What is put in front of them is what the stages put in front of a work, within
> what ADR-0369 §10 lets it read and, for a work with no sender, ADR-0370 §3:3, whatever its floor.

> **Normative.** After the first pass, code takes the work's **cut**: the meet of its floor and,
> for each member the first pass's `story_links` names (ADR-0300 §6:7), that story's audience
> (§6:3), or that activation's audience label (§3:3). With no link, the cut is the floor.

> **Normative.** A story's **audience** is the meet of the audience labels of its activation
> members' episodes and the audiences of its story members, each as it stands. A story with no
> members narrows nothing, nor does an activation member whose episode is gone (ADR-0289 §4:7), and
> an episode written before its label could be recorded is read as carrying whom its work was for.

> **Normative.** A block is **below the cut** where the people who may see it for the mark (§5:2)
> do not take in everyone in the cut. Where the first pass was shown any block below the cut, the
> work re-runs: recall's first run and understanding run again, shown only what is not below the
> cut, and the work goes on from that second pass as it would have from the first. Where it was
> shown none, nothing re-runs and the first pass is the pass that counts.

> **Normative.** After the first pass, what is put in front of a work, on its second pass and on
> any later round, is only what is not below its cut; anything below it reaches the work only by a
> fetch.

> **Normative.** A work re-runs at most once, and its second pass is the pass that counts. Where it
> cannot resolve something, it fetches or asks. An input that joins the work later meets its cut
> with that input's floor and makes nothing re-run.

> **Normative.** Nothing crosses from a first pass that was re-run to the second but the cut, which
> code takes from the first pass's links. No model of the work is shown anything that first pass
> found or wrote, and every later stage reads the second pass's understanding, the story-links
> decision included.

> **Normative.** Where a work re-ran, nothing its first pass was shown counts toward its mark: the
> mark starts at its floor and meets what the second pass and every later stage are shown, and code
> keeps it from what the work's episode records those passes were shown.

> **Normative.** A work's episode records a first pass that was re-run, its recall's finds and its
> understanding as a version of its own (ADR-0276 §7:3), beside the second pass's and marked as
> replaced by the re-run. Each part the first pass produced is placed for the people who may see
> every block that pass was shown (ADR-0369 §7:2), so ADR-0358 §10:5 leaves it out for anyone
> else. Another work shown it, by a look-up (ADR-0358 §10:3) or by a peer view while the re-run is
> pending (ADR-0349 §6:7), counts it toward its mark at that placement (ADR-0370 §4:3), and after
> its own first pass is not shown it in front where it is below its cut (§6:5).

> **Normative.** A fetch after the re-run is a fetch: what it returns meets the mark when it is
> shown, and nothing re-runs. A story's audience falls through it only by what the work then writes
> (§3:3, §6:3).

> **Normative.** This decision gives the re-run one ground for leaving a block out: that it is below
> the cut. A later decision may add grounds; a block any ground applies to makes the work re-run as
> a block below the cut does and is left out of the second pass, and the work still re-runs at most
> once (§6:6).

The point of the re-run is the owner's: "something in this chat history or some other context is
causing it to be more narrow, and that context has nothing to do with the current work, maybe there
could be a way of removing that and continuing with the wider audience." The first pass sees
everything the work may read, so a reference such as "this" or "him" can be resolved and the input
linked to its story (§6:1). The story stays whole (§6:3): its members are never below the cut, so a
work continuing a private story keeps it, and its mark is as narrow as the story's. What the second
pass loses it fetches or asks for (§6:6): "But what if by doing that it loses context it needs. I
guess it can fetch for it". A new matter, linked to nothing, re-runs at its floor, the start level
(§6:2).

A first pass's sight could only bend which story it links. The second pass is shown nothing below
the cut, and the cut is never wider than the floor, so a wrong link costs a fetch or a card, never
a send of what was left out. The episode keeps the first pass for the record, as ADR-0286 §3:1 has
every stage's result kept, but placed so that only those who could see all it saw are shown it
(§6:9). The short view shows the latest understanding (ADR-0356 §9:1), and a peer view shows the
latest recorded meaning (ADR-0349 §6:7), which is the first pass's until the second pass records
its own; whichever another work is shown, it counts at its placement, and a look-up that shows the
first pass narrows that work's mark as any fetch does. A story
member whose episode was forgotten narrows nothing, since nothing of it can be shown. The cost is one more run of recall and of understanding when the re-run
fires. A work with no sender never re-runs: it is shown nothing narrower than its floor (ADR-0370
§3:3), so nothing it holds can be below a cut no wider than that floor.

**The authority side is recorded here and not decided.** The owner ruled that the same mechanism
works for the authority score, the level of a work's context (ADR-0371 §6:1), and agreed that one
re-run covers both scores: "if i can it should, right, why not." What one re-run leaves out for
that level, and every other change on the authority side, is a later amending decision's (§11).
§6:11 is written so that it adds a ground to this one re-run rather than a second re-run. ADR-0371
is not amended here.

### 7. The re-run in the controller

> **Normative.** Code decides the re-run, after understanding's first run and before the
> story-links decision (ADR-0300 §6:10), by a rule of the controller (ADR-0280 §3); no model decides
> it.

> **Normative.** On a work that re-runs, recall's first run and understanding each run once more:
> ADR-0308 §2:10's limit on recall's runs and ADR-0332 §3:9's on understanding's each admit that
> one further run, and ADR-0308 §2:8 does not keep a block below the cut, recall's find or not, from
> making understanding run that once.

> **Normative.** The story-links decision, recall's second run and its digest each run once, after
> the pass that counts, as ADR-0332 §3:11 has them.

The controller has no such rule today, and three clauses stop a second pass: ADR-0308 §2:10
("ADR-0280 §4:6's guard ends a pass that would run it a third time"), ADR-0332 §3:9 ("understanding
runs at most once for each" input), and ADR-0308 §2:8 ("nothing recall finds makes understanding run
again"). §7:2 supersedes each in the addition alone, for that one further run. The understanding the
second pass records is a new version (ADR-0276 §7:3), and planning starts from it (ADR-0332 §3:12).
ADR-0217 §2:4 and §2:5 are not reached: they bar a second pass made to apply a record's placement or
to replace a withheld record, and the re-run does neither.

### 8. Worked cases

ADR-0370 §9's cases stand where no start level is set and no re-run fires. These are the cases a
start level or the re-run changes, with the clause that settles each.

| What happens | The mark | Outcome |
| --- | --- | --- |
| You say privately "tell the flat I'll be late with rent", your private chat left at its audience | You alone | A card with the text, as ADR-0370 §9 has it |
| The same, with your private chat's start level set to the flat | The flat (§5:1) | Sent with no card |
| A weekly rota task set from that chat, posting in the flat's chat | The flat: the task records the mark (ADR-0370 §4:6) | No card on its first run |
| Earlier in that chat you talked of a diagnosis, and the model narrowed it to you (§3:6); now "tell the flat the bins are out" | First pass: everything. The bins are a new matter: cut the flat; the diagnosis is below it | Re-runs without it (§6:4); the flat; sent with no card |
| Same chat: "tell the flat I can't come, because of what we talked about" | The story is the diagnosis: cut you alone (§6:2) | Kept whole; a card for the flat (ADR-0370 §5:3) |
| Same chat, scenario 8: "tell the flat I'll miss dinner, I'm at the doctor" | The flat, taken when shown | The model narrows the record for later readers (§3:6, §3:7); sent with no card |
| Sam, later, in his own private chat, asks what you said about the bins | His work's: the label is the flat, Sam inside | His work may be shown it (§4:2) |
| A courier's work at the door, after you set a chat to anyone | Anyone | Not shown it: an unidentified sender reads what a line opens (§4:5) |
| Ana joins the flat's chat next week | The flat, from then | She sees what is said there after she joined (§4:1) |
| You ask in the flat's chat when your dentist is; recall surfaces a private memory | First pass: everything; cut the flat | Re-runs without it; the calendar is fetched, the mark falls to you, answered privately (§6:10) |

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0286,
> ADR-0308, ADR-0332, ADR-0369 and ADR-0370 and in a dated header note on each, atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0370 §3:1, a message's floor the audience of its place, and an input no person sent the audience of its place | In those two items: the audience label it carries, its place's start level when said (§5:1). The task's, the approval's and the meet stand |
| ADR-0370 §3:2, what is put in front bounded by the floor | For the first pass, not bounded by it (§6:1); after it, bounded by the cut (§6:5). "Anything narrower reaches it only by a fetch" stands |
| ADR-0370 §3:4, the pass's audience read as the floor for what is put in front | In reading the cut where it reads the floor, after the first pass (§6:5). The ceiling for a fetch stands |
| ADR-0370 §4:1, §4:2 and §4:5, everything a model was shown counts, kept from the episode | In the addition alone: a first pass that was re-run counts toward no mark (§6:8) |
| ADR-0370 §4:3, a message counted as seen by its place's audience | In who may see a message, a signal and a window's message: those inside its audience label (§5:2). The rest stands |
| ADR-0369 §6:1, exactly where a person may see a record | In the addition alone: what was said, to its place's audience then (§4:1), and a record, to those inside its label (§4:2) |
| ADR-0369 §3:4, private where no line opens a record | In the addition alone: save as §4:1 and §4:2 provide (§4:3) |
| ADR-0369 §6:3, code decides from the domain, the reach and the lines | In the addition alone: and from the label and the audience when said (§4:6) |
| ADR-0308 §2:10, recall at most twice; ADR-0308 §2:8, nothing recall finds re-runs understanding | In the addition alone: the re-run's one further run (§7:2) |
| ADR-0332 §3:9, understanding at most once for each input | In the addition alone: the re-run's one further run (§7:2) |
| ADR-0286 §3:3's admitted differences and §3:8, no field for a stage's result | In the addition alone: the record keeps the re-run's recall beside the first pass's (§6:9) |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0370 §2 | A place's audience is still who perceives it; the start level takes it in (§2:1) and lapses with it (§2:2) |
| ADR-0370 §3:3, §4:4, §4:6, §4:7 and §5 | A work with no sender, shipped text, what a task and a request record, and every send's check, unchanged; §5:7's reply where the request arrived goes while the mark takes in the place's audience |
| ADR-0370 §6 | Standing approvals still stand in for a yes beyond the mark |
| ADR-0369 §2, §5, §7:5, §8 to §10 and §13 | Records land where they did; a person narrows freely and widens at normal; a record written from what a work read takes the meet; taking a rule back acts forward; a member sees from joining; §10 is the most a work reads; the access log is unchanged (§11) |
| ADR-0217 §2:4, §2:5 and §3:15 | The re-run applies no placement and replaces no withheld record; a model only narrows |
| ADR-0289, ADR-0300 §6:7 and §6:12, ADR-0303 §7:1 | Stories, links and the window's links are read as they are; a story's audience is computed from its members (§6:3), and no story carries one |
| ADR-0276 §7:3 and ADR-0332 §3:10 to §3:12 | The second pass records a new understanding version; joins and planning follow it |
| ADR-0286 §3:1 and ADR-0358 §10:3 to §10:5 | Every stage's result is kept, the first pass's included; a look-up shows every version and leaves out a part placed for someone else (§6:9) |
| ADR-0289 §4:5 and §4:7 | A member whose episode is gone stays a member and narrows nothing (§6:3) |
| ADR-0349 §6:7 to §6:10 | A peer view shows the latest recorded meaning, the first pass's while a re-run is pending, and whoever is shown it counts it at its placement (§6:9) |
| ADR-0280 §4:6, as ADR-0308 and ADR-0332 scope it | The guard stands, with the one further run §7:2 admits |
| ADR-0361 §2:3 | A work may ask for a yes on a send that needs none |
| ADR-0371 | The authority side, ADR-0371 §6 included, is not amended (§6) |

### 10. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made by the
lane the owner's planning dispatches, under this decision once merged.

- **A place's start level:** a value on each place's record, beside its audience (ADR-0370 §12),
  with the act that sets it (§2:3).
- **Audience labels:** a value on each message a place's window holds and on every record a work or
  a producer writes, set by code when it is said or written (§3), with each group's members then
  (§3:5), and a model's narrowing of one (§3:6).
- **The filter:** §4's two cases in ADR-0369 §10's filter, reading the place's audience as it was
  when a thing was said (§4:1), which needs who was in a place's audience over time.
- **The cut and the passes:** the cut on the activation's state; on the episode, a field for the
  re-run's recall beside the first pass's, the first pass's parts marked as replaced and each
  placed for the people who may see all that pass was shown (§6:9), which needs a placement on an
  understanding version and on a recall's record; a member of
  `ControllerRule` for the re-run (§7:1); and the counts of ADR-0308 §2:10 and ADR-0332 §3:9 admitting
  its run (§7:2).
- **A story's audience:** computed at read from its members' episodes (§6:3), from the mark
  ADR-0370 §12 already puts on the frozen episode. `StoryStore` gains nothing.

### 11. What this decision leaves to others

- **A later amending decision on the authority side:** what one re-run leaves out for the level of
  a work's context (ADR-0371 §6:1), as a ground under §6:11; ADR-0371's levels and how sure the hub
  is; what a block's authority is; that only a person changes what a block counts at; vouching; a
  person's review; whether a checked write-up counts as weak; and a guard on acts that move money.
  The owner parked or has not finished each.
- **The owner:** whether the assistant answers every message in a group chat.
- **The next prompt review:** how a model is told its mark, its cut or a place's start level; when
  it makes the general fetch (§5:3); how it explains answering in a private place, or offers to open
  a calendar; when it narrows a label (§3:6).
- **A further decision:** whether a read through §4 is entered in a person's access log (ADR-0369
  §13), and whether ADR-0369 §1:5 gates §4 on that log.
- **The build:** a surface for setting a start level (§2:3).

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 12. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3 and §1:4**: nothing changes until built; nothing of it is needed to admit a second person.
- **§2**: a start level stated as an audience is; that it is the place's audience by default
  (§2:2), and read with the audience where the audience reaches beyond it; that whoever declares the
  audience sets it, widening at ADR-0369 §5:3's bar and narrowing free (§2:3); that a change acts
  forward (§2:4); and that it is a setting of the place, not a sharing rule.
- **§3:2**: a work's message carries its mark with the audience it was said to, not the place's
  level; **§3:3 and §3:4**, the label of every other record a work or a producer writes; **§3:5**,
  that a label is fixed when said, its groups read then; **§3:6**, that a model narrows only a block
  of the domain its work writes into, to any set inside the label; **§3:8**, which acts widen.
- **§4:2 to §4:6**: the label read as it stands, its groups counting those who were members then
  and still are; that neither case reopens a group's domain to someone who left it; the label as a
  case of ADR-0369 §6:1 under its reach and its limits; that a
  record with no label opens to no one through it; that anyone means each person the hub admits, and
  an unidentified sender reads as ADR-0369 §10 has it; and that code decides it. **§4:1** is the
  owner's ruling on #3636; that it is a case of §6:1 beside the others, under its reach and limits,
  is this decision's.
- **§5:1 and §5:2**: the floor and §4:3's people for a message, read from its label; **§5:3**, that
  the general fetch is a fetch within ADR-0369 §10.
- **§6**: that the first pass is recall's and understanding's first runs and is bounded by ADR-0369
  §10 (§6:1); the cut as the meet of the floor and the linked stories and activations, a story's
  audience as the meet of its members' labels, a story with no members narrowing nothing, several
  links met, and an old episode read as its work's person (§6:2, §6:3); that the later rounds are
  bounded by the cut (§6:5); that a join re-runs nothing (§6:6); that only the cut crosses, and
  the mark counts from the second pass (§6:7, §6:8); that the episode keeps the first pass placed
  for those who could see all it saw, with room for the re-run's recall (§6:9); that a forgotten
  member narrows nothing (§6:3); a fetch after the re-run (§6:10); and the grounds (§6:11).
- **§7**: where the re-run sits among the phases, and the further runs it needs.

## Consequences

- A person who sets their private chat to start at the family no longer gets a card for every send
  to the family from it; what they say there is the family's to see, through memory as well, unless
  they or the model narrow it.
- Unrelated private context in a chat's history or in recall no longer narrows a work: the first
  pass finds the story, and the work goes on without what is narrower than it.
- Other members' works can read what was said in a shared place, as of who was there, which closes
  #3636.
- A private detail typed into a chat whose level is wider is caught by a model's narrowing for
  later readers, not by a card on the send that carries it; a model may still ask.
- A work that re-runs spends one more run of recall and of understanding, and the episode keeps the
  first pass for the record.
- The open episode's reach stays `OWNER` with `DERIVED` until it freezes (ADR-0286 §1:3), so another
  person's work reads a running work's record through §4 only once it has frozen.
- Nothing changes in the running hub until the owner's planning dispatches the build (§1:3).
- **Revisit** if a model's narrowing is too rarely used for private details typed into a wide chat,
  or if the re-run fires on most works.

## Alternatives considered

- **Leave every work's floor at its place's audience**, as ADR-0370 has it, with standing approvals
  for the sends a person makes often. Set aside by the owner: "A card on every utward send from a
  private chat isnt what I want".
- **The start level as a sharing rule on the place's conversation.** Not taken: a sharing rule
  names a kind of a domain and is read as it stands, where what a place gives a block is fixed when
  it is said (§2). Taken: a setting of the place, at a sharing rule's bars.
- **Two labels**, one deciding what the person's works may pass on and one deciding who may read
  through memory. Not taken: the owner accepted one label, filtered by audience.
- **Scenario 8 by narrowing the running work**, so the send asks for a card. Not taken: the owner
  settled on narrowing the record for later readers and sending with no card (§3:7).
- **Keep narrow history out of a work and leave a marker to fetch it.** Set aside by the owner:
  a private conversation would be fetched each turn, and references in it would not resolve.
- **Understanding passes on only its links, in a fixed shape, to the later phases.** Replaced by the
  owner's own version: the work re-runs from recall without what is narrower, and continues as
  normal (§6).
- **A person's review of a story's summary as the way a story gets its level back.** Not adopted:
  "No I think this is fine, right?", to the coordinator's question whether a person's review of a
  story's summary should be that way. A story that needs a narrow block keeps its level, and a send
  beyond it takes a card.
