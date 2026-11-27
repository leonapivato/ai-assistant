# 391. Every text carries the say it was written under, a work may do and read only what everyone whose say it holds may, a signal is anyone's, and a reply is a send like any other

- Status: Accepted
- Date: 2026-11-27
- Scope: the amending decision on the authority side of ADR-0365 to ADR-0372, from the walk of
  2026-11-22 and 2026-11-23 and the review of 2026-11-26: the say a text carries (§2), a work's say
  (§3), signals and messages (§4), pasted and forwarded text (§5), a reply (§6), a task's fetch (§7),
  machinery and the re-run (§8), two credits (§9), the two parked points (§10), earlier decisions,
  the build and what is left (§11 to §14), and whose each point is (§15).
- Authorization: the owner's rulings of 2026-11-22 and 2026-11-23 in the methods walk and of
  2026-11-26 in the review, quoted verbatim in §15 with where each is recorded. The rest is the
  coordinator's proposal, ratified by the coordinator under the owner's delegation once its reviews
  are green. §10's picks are not ruled.
- **Contract-surface decision; a decision only.** It changes no Protocol, type, field or code, and
  bounds the `core` types the build makes, so it takes the adversarial and the architecture review.
  Building it is a breaking change under golden rule 5, through the changes §13 names.
- **Partially supersedes** ADR-0306 (§4:7), ADR-0351 (§4:2, §6:2), ADR-0356 (§7:7), ADR-0367
  (§4:2, §4:7), ADR-0368 (§3:2, §3:5, §7:1, §7:5), ADR-0369 (§10:2, §10:3), ADR-0370 (§3:3, §3:4, §5:7,
  §5:8), ADR-0371 (§2:1, §2:4 to §2:6, §5:1, §5:4, §8:2) and ADR-0383 (§6:4 to §6:6), each in the
  scope §11 gives.

## Context

ADR-0371 carries what reading another's text does to a work by levels alone (§2:3): a source
"holds no grant and has no say" (§2:1), another person's writing is a source (§2:4), and what a
work writes carries its context's level (§5:1). ADR-0368 §3:5 gives an input no person sent "no
authority, at none", built in milestone 20; ADR-0367 §4:7 keeps a message into a place a work's own
input came from outside the check, built in milestone 21.

Levels alone miss whose say steers a work. The owner's case: "if Sams message starts an activation
under his authority, but its in the group chat, it gets place context with lower authority". The
coordinator's: the assistant's reply written for one person is read by another's work at its
written level, as if clean. "How sure" is parked, so this decision states authority in people, as
the owner asked, beside ADR-0366 §5's levels, which stay as merged.

**Words.** A **say** is §2:1's and §3:1's; a **stranger** is a member of anyone alone (ADR-0368
§7:2). The level, a source, separate work, findings and the context are ADR-0371's; a line, a grant,
a bar, the check and a card ADR-0367's; the mark, a send and a place ADR-0370's; a block, a story, a
cut and the re-run ADR-0372's. A bare section reference, such as §3:1, is to this decision.

## Decision

We will record whose say every text was written under, and check every call and bound every read
by everyone whose say a work holds.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and when, is
> the owner's planning call.

> **Normative.** Until §2's say, §3's bound and §6's reply line are built, every call and read runs
> as it does today, ADR-0367 §4:7 and ADR-0368 §3:5 included, and nothing in this decision changes
> what the running hub reads, shows, allows or asks.

> **Normative.** This decision admits no one. Before a person other than the owner is admitted,
> §2 and §3 are built, and until they are, ADR-0371 §2:4 and §2:5 hold as written.

### 2. The say a text carries

> **Normative.** Beside the level ADR-0371 §5:1 records, every text carries its **say**, whose say
> it was written under: a set of people the hub admits, those people and a stranger, or **none**.
> Code records it when the text is written or arrives, and it is fixed after.

> **Normative.** A message carries its writer's say: a person's where code establishes its writer
> as a person the hub admits (ADR-0368 §2:6), and a stranger's otherwise.

> **Normative.** What a work writes, each kind ADR-0371 §5:1 names, carries the say of its context
> (§3:1) when written; a task's instruction carries the say of the work that set it.

> **Normative.** A record a producer writes after a work has ended, or a run of upkeep writes
> (ADR-0384), carries the say of every record it was written from, taken together. One written
> before its say could be recorded carries its home's people's (ADR-0390 §3:5), never a stranger's.

> **Normative.** Findings (ADR-0371 §4:1), a typed value (§3:2) and a value code sets (§5:2) add
> no one to a say: each is a new block, at the level ADR-0371 gives it.

> **Normative.** Forwarded, quoted or relayed words ADR-0351 §6:2 leaves with no authority, whose
> writer §5:2 does not establish, carry none.

> **Normative.** What a vouched source read directly carries is for the further decision ADR-0371
> §3:6 names, before which no source is read directly.

§2:5 keeps ADR-0371 §4 as merged, its findings at §4:3's level, which is the parked point (§10).
§2:2 and §2:3 close both gaps above.

### 3. A work's say, and what it bounds

> **Normative.** A work's **say** is everyone whose say the blocks in its context carry, each as it
> counts in that work (§8:2), taken together, with a stranger where any carries one; it is none
> where any counts as none. Code keeps it from the work's record, it only falls, and no model sets
> it.

> **Normative.** The check (ADR-0367 §4:1) runs, at the level of the work's context (ADR-0371
> §6:2), for each person in its say and, where it holds a stranger, for a member of anyone alone; a
> call is done only where allowed for every one. A work whose say is none carries no authority
> (ADR-0368 §7:5).

> **Normative.** Where the check allows a call for each person whose authority the work carries,
> and for anyone else in its say, a person or a stranger, its outcome is not done or needs a yes, the
> call is not refused: it needs a yes from those whose authority the work carries, on ADR-0367 §5:3's
> card, and the call under its ticket is checked for the tapper alone (ADR-0367 §5:5). A call the
> check does not allow for each of those people stays as ADR-0367 §4 and §5 rule it.

> **Normative.** A work reads no more than each person in its say may see and, where its say holds
> a stranger or is none, no more than anyone may see (ADR-0369 §10:4, ADR-0390 §5:3). The filter
> applies this as the say falls (ADR-0369 §10:5), and what it withholds is absent (ADR-0369 §10:6).

> **Normative.** A fall in a work's say takes nothing out of what it was shown, and its mark keeps
> what it read (ADR-0370 §4:2); only later reads and calls are bounded by it.

> **Normative.** Code keeps two facts on every work beside ADR-0368 §2's: its say, which bounds what
> it may do and read, and its mark (ADR-0370 §4), which bounds whom it may tell. Each call is checked
> against both, as ADR-0367 §4:1 and ADR-0370 §5:1 rule, and neither lifts the other.

> **Normative.** Once §2 and §3 are built, a person's writing that code establishes as theirs is not
> a source in another person's work (ADR-0371 §2:4, §2:5): it is shown as their own text and carries
> their say.

> **Normative.** ADR-0371 §8:3 stands: a work acts on another person's words only where they were
> said in a place whose audience then took in each of its senders (ADR-0372 §4:1), and any other
> person's answer reaches the asker only as ADR-0371 §8:3 and ADR-0367 §11 rule.

The owner's option 3 is ADR-0370 as merged with ADR-0372's start level; §3:4 is what they added
to it. §3:3 is the owner's "bypass" of "too low": a read through an account is a call (ADR-0369
§10:7) and takes it, and a read through the filter asks no one. So Sam's work beside Ana's earlier
message in the family chat does and reads only what both may, unless the re-run (§8) leaves it out.

### 4. Signals and messages

> **Normative.** An input no person sent, whose author is a service or that has none, carries a
> stranger's say at none: only grants to anyone apply to its work (ADR-0367 §2:3, §5:2), among them
> those whose conditions it meets. It is for whoever its connection belongs to (ADR-0368 §3:5).

> **Normative.** A message a connection brings into a person's own account, such as an email in
> their mailbox, is such an input whose text has a writer: it carries its writer's say (§2:2) at the
> level its route establishes (ADR-0366 §5:2), and is for whoever the account belongs to.

> **Normative.** A work §4:1 or §4:2 starts asks no one for a yes until a further decision rules
> whom it asks, and a call in it that needs one is not done, saying why (ADR-0368 §7:4).

> **Normative.** A signal or a message counts as someone else's say only where a grant made
> beforehand says so, "a permission like any other, starting with the owner" (ADR-0367 §3:1, §7:2).
> Its what, who may make one and whose say it may lend are a further decision's; ADR-0368 §3:6's
> standing rule stands as one such grant.

What anyone may do is what grants to anyone allow at none. Every default grant the hub declares
has a bar of weak or normal, so a signal's work may make no call until a person makes a line to
anyone at none. A mail sender stays claimed (ADR-0368 §9:8), so every email §4:2 reaches is a
stranger's.

### 5. Pasted and forwarded text

> **Normative.** Words a person pastes or types into their own message are their own and carry
> their say (§2:2). A model may lower what they count at in its work, by the relay mark (ADR-0351
> §5:6), as §8:2 rules; nothing raises them.

> **Normative.** Words a medium marks as forwarded or quoted carry their original writer's say
> where the medium establishes that writer as a person the hub admits, at the most its kind declares
> for such a writer (ADR-0366 §5:2), and none otherwise. A kind that declares none establishes no
> one, so ADR-0351 §4:2's claimed sender holds for it.

> **Normative.** The forwarder's own words in the same input carry the forwarder's say, and the
> work holds both (§3:1).

### 6. A reply

> **Normative.** No message is outside the check. A **reply**, a message into a place one of the
> work's own inputs came from, is a call like any other: the check runs on it at the level of the
> work's context, and it is checked against the mark as every send is (ADR-0370 §5:1 to §5:6).

> **Normative.** A **reply line** is a grant of ADR-0367 §3:1's shape: who, anyone; what, a reply
> into one place; how, allowed; its bar; no condition. Each kind of place declares its default, and
> whoever a place belongs to changes it for that place, and for a person by naming them, as any line
> on their own things (ADR-0367 §6:1, §6:2).

> **Normative.** A place of a chat with the assistant's own account, the system's own chat or the
> line's chat, has a reply line at a bar of none by default. A place of an account that is a
> person's own (ADR-0367 §6:3), such as their mailbox, has none. Every other kind declares its own,
> and one that declares none, or takes no message, has none.

> **Normative.** In a work that carries no authority, the check runs for a reply alone as for a
> member of anyone at none, so a reply line covers it as it covers a stranger's work.

> **Normative.** A reply no line covers is not done, saying why (ADR-0367 §4:2); one a line covers
> but for its bar takes ADR-0367 §5:3's card. No reply is moved to another place: telling the
> person elsewhere is a send like any other (ADR-0367 §12:1).

Nothing obliges a work to reply: that is the home of the owner's parked point that in a group chat
"the assistant need not respond to every text".

### 7. A task's fetch

> **Normative.** A task's work, and a standing rule's, is not a work with no sender for ADR-0370
> §3:3: it fetches no more than its author may see and §3:4 allows, its instruction's say (§2:3)
> among it, checked at the level its task records (ADR-0368 §6:2, §6:3).

> **Normative.** What it fetches meets its mark when shown (ADR-0370 §4:2), and a send beyond that
> mark needs its author's yes or standing approval (ADR-0370 §5:3, §6).

### 8. Machinery, and one re-run for both scores

> **Normative.** No code and no model changes the say or the level an existing block counts at.
> They make new blocks only, such as findings, a typed value or a replacement (ADR-0371 §6:4), each
> carrying its own; only a person's act changes what an existing block counts at.

> **Normative.** A model's relay mark (§5:1) lowers what an input counts at in that work alone, to
> none, as ADR-0351 §6:5 has it, and the say recorded on the text is unchanged.

> **Normative.** A block is also below a work's cut, a ground ADR-0372 §6:11 admits, where its say
> names a person or a stranger that neither the story's say nor the work's own inputs' names, or is
> none where neither is. A story's say is its members' episodes' taken together, and with no story
> linked only the inputs' counts. A work's own inputs are never below the cut.

> **Normative.** Where a work re-ran, its say is counted from what its second pass and every later
> stage are shown, as ADR-0372 §6:8 counts its mark, and its sight is made again from its inputs
> and that say, not met with the sight its first pass held (ADR-0383 §6:6).

§8:1 is the authority side alone: a model may still narrow an audience label (ADR-0372 §3:6), and
§8:2 reconciles the owner's later "unless the model decides" with it.

### 9. Two credits corrected

- **ADR-0367 §18** credits §4:7 to "the owner's 'a work can always answer its own sender'
  (2026-11-21)". The words were the coordinator's (walk chat, 2026-11-22 00:04:55 UTC, line 82):
  "except that it can always answer its own sender inside the mark". The owner's reply (00:09:08,
  line 93): "ok nice, and I think that usually it shouldnt take any authority for the assistant to
  message a person individually, but this can be a default setting than can be adjusted in the
  profile." ADR-0370 §5's note and Consequences, and ADR-0371 §8's note, rest on that credit.
- **ADR-0367 §11's** "The owner's example: 'Ask Sam if he's free Friday, and add it to the calendar
  if so.'" is the coordinator's wording (07:28:52 UTC, line 956). The owner's (07:22:01, line 901):
  "I tell the assistant to ask Sam if hes free Friday and to add to the calender if so".

### 10. The two points the owner parked: the coordinator's picks, NOT RULED

> **Normative.** ADR-0371 §4:3 to §4:5 and §7 stand as merged, nothing in this section replaces
> them, and no lane builds ADR-0371 §7 before the owner rules on it.

Parked by the owner on 2026-11-22: "let come back to this later, maybe I need to think about it
more." The coordinator puts both picks to the owner; neither binds until a ruling replaces this.

**Seen by a person (ADR-0371 §7:1, §7:2).** The owner: "Firstly, I didnt mean that seen by a person
makes it clean, I meant, a person can make it clean by reviewing it. But if they just saw it and
didnt review it, that shouldnt make it clean." The pick, replacing §7:1 and §7:2:

> A person makes a text a work delivered to them count at their own say, at the level of their act,
> by an explicit act of review, a tap on that text. A later message in the place cleans nothing.
> This is §8:1's person changing what an existing block counts at.

Beside it, asked on 2026-11-23 whether a person's review of a story's summary should be how a long
story gets its score back, the owner answered "No I think this is fine, right?".

**The open write-up (ADR-0371 §4:3, §4:4).** The owner: "The open write-up I thought was clean
because it would go through some digest/checker". The pick, narrowing §4:3 and §4:4 in the addition:

> An open write-up stays weak. A person may hold a line of ADR-0367 §3:1's shape, off by default,
> by which a checked write-up in their own works counts at the level of the work that asked.

It needs no vouching detail; which checks qualify and the bar of making it would be the owner's.

### 11. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0306,
> ADR-0351, ADR-0356, ADR-0367, ADR-0368, ADR-0369, ADR-0370, ADR-0371 and ADR-0383 and in a dated
> header note on each, atomically with this ADR under ADR-0070 and ADR-0082, preserving their
> ratified bodies. The replacements take effect on this ADR's ratification.

| Clause | Becomes |
| --- | --- |
| ADR-0367 §4:7, a message into its input's place outside the check | Whole: a reply passes the check (§6) |
| ADR-0367 §4:2, no grant means no and asks no one | In the addition alone: a no or a limit for one in a work's say whose authority it does not carry asks, as §3:3 rules |
| ADR-0306 §4:7 and ADR-0356 §7:7, checked by its place alone | In the addition alone: a reply also passes the check (§6:1) |
| ADR-0370 §5:7, outside the grant check; §5:8, "every other send" | §5:7's first limb: a reply passes the grant check, its mark check standing. §5:8 reads every send |
| ADR-0371 §8:2, a reply meets no level | Whole: §6 |
| ADR-0368 §3:5, a signal carries no authority | In whose authority: a stranger's or its writer's say (§4:1, §4:2). Whom it is for stands |
| ADR-0368 §3:2, its parties the person alone | In the addition alone: an established forward's writer (§5:2) |
| ADR-0368 §7:1 and §7:5, whom the check runs for; a work carrying none | §7:1 and its table, in the addition alone: everyone in its say (§3:2). §7:5's exception for ADR-0367 §4:7 becomes §6:4 |
| ADR-0351 §4:2 and §6:2, a forward's sender claimed and carrying none | In the addition alone: a writer a kind establishes (§5:2) |
| ADR-0371 §2:1, a source has no say | For a person's text, which carries its writer's (§2:2, §3:1) |
| ADR-0371 §2:4 and §2:5, a person's writing a source | Once §2 and §3 are built: a person's established writing is their own text in every work, carrying their say (§3:7, §1:4) |
| ADR-0371 §2:6, forwarded words carry none | Whole: §5 |
| ADR-0371 §5:1 and §5:4, what is written carries a level | In the addition alone: and a say (§2:3) |
| ADR-0369 §10:2 and §10:3, what a sender's or a task's work reads | In the addition alone: within its say (§3:4) |
| ADR-0370 §3:3 and §3:4, a work with no sender; a fetch's ceiling | §3:3, for a task's or a rule's work: §7. §3:4's ceiling for a fetch: within this decision's §3:4. §14's reading of a task's ceiling goes with them |
| ADR-0383 §6:4 and §6:5, a work's sight | In the addition alone: a person bound for each person in its say, and an anyone bound where it holds a stranger or is none, made again as §6:6 has it when its say falls (§3:4, §4:1) |
| ADR-0383 §6:6, a sight never widens within a work | Save after a re-run: the sight is made again from the inputs and the second pass's say (§8:4) |

Read through and standing: ADR-0366 §5's levels and the default bars; ADR-0371 §3, §4, §6, §7,
§8:3 (§3:8) and §9; ADR-0372 §3 to §7, with this decision's §8:3 ground under its §6:11; ADR-0368
§3:6, §6 and §9:8; ADR-0351 §5:6, §6:3 and §6:5; ADR-0367 §5, §6:3, §11 and §12; ADR-0379 §3:3,
which turns each outcome as ADR-0367 §4 and §5 and ADR-0368 §7 rule, as amended here; and ADR-0382
§2:1, which keeps an approval's outcome message outside the check as its own rule
([#3796](https://github.com/leonapivato/ai-assistant/issues/3796) parks bringing it under §6).

### 12. What is built today, and what becomes of it

| Built | Cites | Becomes, once built |
| --- | --- | --- |
| `started` in `orchestration/work_facts.py`: an event's work carries none | ADR-0368 §3:5 | A stranger's say at none (§4:1) |
| `check_runs_for` there: a forward's or relayed work runs for no one | ADR-0351 §6:2, §6:5 | The same, save an established forward (§5:2) and a reply (§6:4) |
| `_message_checked` in `orchestration/authorizer.py`, `orchestration/could_use.py`, `_input_places` in `orchestration/phase_path.py`, `places_inputs_came_from` in `orchestration/channel_kinds.py`: a message into an input's place outside the check | ADR-0367 §4:7 | Checked under the reply line (§6) |
| A work's sight (ADR-0383 §6:4, §6:5): senders, whom it is for, its author | ADR-0369 §10 | Also everyone in its say (§3:4) |

For one owner on their own chats, once built, one thing changes: an event's work, and a work
holding a forward or relayed words, reads only what anyone may see, not what the owner may. Every
reply they get is in a chat with the assistant's own account, at a bar of none.

### 13. What building it needs

Named so the build is scoped, and made by none of this decision. A new Protocol ships as a triad.

- **`core/types.py`:** a say value (people, a stranger, none) beside the level ADR-0371 §13 names on
  every note, message, summary, episode, memory, task instruction and call's recorded values; a
  work's say on the activation's state and frozen episode; `ScheduledTask` recording its
  instruction's say; `WorkAuthority` carrying a stranger for a signal (§4:1).
- **Orchestration:** `started` and `check_runs_for` reading the say (§3:2, §4); the bypass card
  (§3:3); the reply check (§6:1, §6:4) in place of ADR-0367 §4:7's exemption at each site §12
  names; the re-run reading §8:3's ground.
- **Lines:** the reply line (§6:2) is a default declared by a kind of place and naming a place as
  its thing, which ADR-0376 §3:1's tool-only default grant cannot carry, so the building lane's
  decision amends ADR-0376 §3; `ConnectionKind` declaring each kind's reply bar or none (§6:3), and
  its most for a forward's writer (§5:2).
- **Stores and formats:** a work's sight taking a bound per person in its say, remade as it falls
  (§3:4), seeing beside ADR-0390 §5:4's score; every store ADR-0383 §3 gives a home recording the
  say beside each record, as ADR-0390 §10 has the score, a format step for each, with an upgrade
  reading earlier records under §2:4.
- **Wire:** the activation and episode views, and the line members, carrying the say and the reply
  line: the `PROTOCOL_VERSION` step, with ADR-0390 §10's if they are built together.

### 14. What this decision leaves to others

- **The owner:** §10's picks; "how sure", whether a say carries a level of its own; every bar
  beyond §6:3's defaults.
- **A further decision:** the "set up prior" permission's shape, standing rules and whom a work §4
  starts asks (§4:3, §4:4); vouching's details (§2:7); the money guard; how long-lived text written
  under a low say is cleaned beyond §10
  ([#2798](https://github.com/leonapivato/ai-assistant/issues/2798)); every group ruling of the
  review; how a mail channel establishes a sender (ADR-0368 §9:8). The audience side is ADR-0390's.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 15. Whose each point is

The owner's words are verbatim, from the walk chat (local, by UTC day, time and line) and from the
review log of 2026-11-26 (local, `review-log.md`, by line).

| Point | The owner's words | Where |
| --- | --- | --- |
| Text carries its write-time say; a work's is the least of its inputs (§2, §3:1, §3:2) | "The difference is authority at input and output. At input, the authority is the least authority of all of its inputs. At output, its just the authority it had at write-time." | 11-22, 17:30:12, line 2213 |
| The same, earlier | "an inputs effect on authority should be the least privilege of that inputs authority" | 11-22, 17:06:16, line 2142 |
| Option 3 (§3, ADR-0370) | "start every input at the audience authority instead of the write-time authority, with the potential to upgrade authority if needed. Then to write to an audience with less authority, require a card" | 11-22, 17:47:18, line 2297 |
| The read ceiling (§3:4, §3:5) | "also its important that it can only grow to the lowest write-time authority of all of its inputs." | 11-22, 17:54:51, line 2360 |
| Ruled, the rows above | "Yes, record it as ruled", to "Record as ruled: option 3, with the read ceiling at the lowest say of all inputs?" | 11-22, 17:56:15, line 2393 |
| One check, two facts (§3:6), as said | "But authority is still the main driver." | 11-22, 17:34:23, line 2253 |
| The bypass card (§3:3), agreed in chat | "Then there is also cards that just bypass a mismatch in the authority, right?"; "Is a read not just an act? The scenarios would be then, bypass too high and too low." | 11-22, 20:07:18 and 20:41:41, lines 2513 and 2616 |
| Machinery makes new blocks (§8:1), ruled | "Yes, could the same trick work for the understanding to recall itself without blocks that are not needed and may raise authority?", to "Do you agree with the first difference as a rule: machinery only ever makes a new block, and only a person changes what an existing block counts at?" | 11-23, 02:52:13, line 38 |
| One re-run for both scores (§8:3, §8:4), agreed in chat | "if i can it should, right, why not." | 11-23, 03:02:51, line 71 |
| "How sure" parked | "maybe we can park the how sure for now too" | 11-23, 04:22:38, line 425 |
| A signal and a message (§4:1, §4:2) | "authorless signal should be treated equal to an anyone author (or someone else if setup prior). Then a message with a writer is treated as that writer (or someone else if setup prior), that simple." | review log, lines 65 to 67 |
| The setup (§4:4) | "This should just be a permission like any other, starting with the owner" | review log, line 84 |
| No free reply (§6) | "I think the rule that a work can always answer its own sender where the requied arrived is just wrong"; then "Yes, replace it" | review log, lines 86 to 87, 106 |
| A task's fetch (§7) | "If it follows what we talked about and ends up with a high enough score, it should, right?"; then "Good on all of them." | review log, lines 18, 27 |
| Pasted text (§5:1) | "If you mean copy and pasted in my own input, then there is no way to verify it? so it should be treated at my authority unless the model decides that this shouldnt be. right?"; then "Good on all of them." | review log, lines 17, 27 |

Forwarded text (§5:2) is the review session's wording, accepted by "Good on all of them.". The
milestone-23 plan ("Yes, milestone 23, and dont worry about the cleanup", 2026-11-26) is the
coordinator's record, not checked here. **This decision's own, not ruled:** §1:4; the say as
people, a stranger or none (§2:1), and what a producer's, an earlier, a finding's and a forward's
text carries, an upkeep run's included (§2:4 to §2:6, §5:2, §5:3); the bypass card's addressee
(§3:3), the filter applying §3:4, §3:6's wording, §3:7 and §3:8; §4:2's account's person and
§4:3; the reply line's shape, defaults and changer, §6:4 and §6:5; §7's reading of ADR-0368 §6;
§8:2, and the form of §8:3 and §8:4; the sight's addition and ADR-0382 §2:1 standing (§11).

## Consequences

- Another person's text caps a work to what they could do and see; an email cannot act as its
  mailbox's person; a forward costs a work its person's records. **Revisit** if bypass cards become
  habit, or once §10 is ruled.
- **Set aside:** a person's text as a source at a level alone (it misses whose say steers);
  nobody's text as a stranger's (a forward's refusals would become cards; §6:4 covers its reply).
