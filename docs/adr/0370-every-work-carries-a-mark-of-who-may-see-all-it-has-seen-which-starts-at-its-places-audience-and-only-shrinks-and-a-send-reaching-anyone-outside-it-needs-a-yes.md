# 370. Every work carries a mark of who may see all it has seen, which starts at its place's audience and only shrinks, and a send reaching anyone outside it needs a yes

- Status: Partially superseded by ADR-0372 (§3:1, in a message's and a signal's floor; §3:2 and §3:4, for the first pass and in reading the cut; §4:1, §4:2 and §4:5, each in the addition alone; §4:3, in who may see a message: a place's start level, audience labels and the re-run by story) and ADR-0382 (§5:7 and §5:8, each in the addition alone: an approval's work's message into a place an input of the asking activation came from is checked as §5:7 checks one into a place the work's own input came from, and is not among §5:8's other sends)
- Date: 2026-11-22
- Scope: lane 6 of the seven decisions the people, authority, audience and outside content
  proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)), the lane
  [ADR-0365](0365-one-hub-serves-several-people-each-is-the-top-of-their-own-domain-and-separate-households-keep-separate-hubs.md)
  §6 names sixth: the audience mark. It decides what a place's audience is (§2); a work's floor,
  what is put in front of it without its asking, and what a work with no sender may fetch (§3);
  the mark every work carries (§4); how a send is checked against it, how that check meets the
  grant check, and what a card is (§5); the two standing approvals (§6); which place a signal
  lands in (§7); and the same person from a second place (§8). §9 works the proposal's cases,
  §10 says what ADR-0361 §7:4 and ADR-0217 §2 become, §11 records what it does to earlier
  decisions, §12 names the contract changes it would need, §13 what it leaves to others, and §14
  what it settled where the rulings left a point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the
  coordinator. Their words, verbatim, all of 2026-11-21. That a work is not tied to its place:
  "how do you know its going to reply to me in that exact chat? I believe we decided the
  activation is serpate than the place it arrived on" (§4:1). The idea that became the mark: "it
  can fetch that, and now any tool that writes into a space with family or other audience
  requires approval. But without that fetch it wouldnt require that." (§3:2, §5:2, §5:3). Where
  the mark starts: "maybe a mark shouldnt start as {you} in a private chat, it starts as wide as
  possible based on the current context its given and fetches" (§4:2). What it is computed from:
  "the mark should be computed from whats infront of the model, and the place, and maybe the
  instruction no?" (§4:1, §4:3). Floor and ceiling: "So the "who its for" is the ceiling for the
  marks, is that the right way to put it? And the place is the floor, and depending on the place,
  the floor can be lower or higher?" (§3:1, §3:3, §4:2). To the rule as read back to them, and on
  a signal's place: "looks good, for the no sender case, I think this is right, but it could be
  set where doorbell is directed under house level, right?" (§3:3, §7:1). On passing on: "its just
  like if I trust someone with infomration, and they tell people. By trusting someone with
  infomration, im subjecting myself to that risk." (§5:5). The coordinator assigned 0370 and
  ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides what every work carries and what every send is checked against, which
  bounds the `core` types the build makes, so it takes the adversarial and the architecture
  review. Building it is a breaking change under golden rule 5, through the `core` changes §12
  names, none of which is made here. It dispatches no implementation (§1:2).
- **Partially supersedes**
  [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md)
  (§2:1 and §2:5's *no new site* half, each in the addition alone),
  [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md)
  (§9:6, in who declares a bounded audience and what it names),
  [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md)
  (§4:1 and §4:7, each in the addition alone),
  [ADR-0324](0324-a-pull-is-the-assistant-asking-a-channels-sensor-and-the-calendar-and-the-weather-come-back-as-pulls.md)
  (§4:6, in what the offer reads),
  [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md)
  (§7:7, in the addition alone),
  [ADR-0358](0358-planning-keeps-memory-only-on-purpose-a-matter-that-has-changed-is-tidied-in-the-background-and-planning-can-search-past-episodes-read-one-whole-and-read-its-origins-older-history.md)
  (§6:2, §6:3 and §7:3, in what a look-up reads),
  [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md)
  (§2:6, in the addition alone; §7:4, whole),
  [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md)
  (§9:3, in its last sentence) and
  [ADR-0368](0368-every-work-records-whom-it-is-for-whose-authority-it-carries-and-how-sure-the-hub-is-and-an-instruction-given-in-advance-carries-its-authors.md)
  (§6:3, in the addition alone), as §11 records.
- Partially superseded: 2026-11-22 by [ADR-0372](0372-a-place-has-a-start-level-that-what-is-said-there-carries-and-a-work-re-runs-once-without-what-is-narrower-than-its-story.md) — §3:1, in a message's and an input no person sent's floor: the audience label it carries, its place's start level when said (ADR-0372 §5:1). §3:2 and §3:4, for the first pass of understanding, which they do not bound, and after it in reading the work's cut where they read its floor (ADR-0372 §6:1, §6:5). §4:1, §4:2 and §4:5, each in the addition alone: a first pass that was re-run counts toward no mark (ADR-0372 §6:8). §4:3, in who may see a message, an input no person sent and a window's message: those inside the audience label it carries (ADR-0372 §5:2). Every other clause stands. This replacement takes effect on ratification of ADR-0372. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

ADR-0365 let one hub serve several people under three principles, the third of which is that
sharing is like telling someone: "What a person has been shown, they know, and they may pass it
on by their own act. The system never passes anything on by itself" (ADR-0365 §3:3). ADR-0368
recorded on every work whom it is for, whose authority it carries and how sure the hub is
(ADR-0368 §2). ADR-0369 ruled who may see a record (ADR-0369 §6:1) and the most a work may read
(ADR-0369 §10), and left this lane "what narrows a work's reads by the place its stimulus arrived
in", how a person passes something on and what a send needs, standing approvals, which place a
signal lands in, and "what ADR-0217 §2's rule for an output channel becomes" (ADR-0369 §17).
ADR-0367 left it "the audience mark, and standing approvals for it" (ADR-0367 §17), and ADR-0368
"how it shrinks, including for a work holding one person's inputs from several places" (ADR-0368
§12). ADR-0367 §1:4 makes this lane one of the decisions that must merge before a person other
than the owner is admitted.

**What the corpus says of audience.** ADR-0199 decided what may be said by "the audience of the
output channel", bounded or unbounded (ADR-0199 §1:1), an undeclared one unbounded (§1:2), and
ADR-0217 stated it over sets: "A record is emitted on an output channel only if **every person
who can perceive that channel's emission is a member of the record's placement**" (ADR-0217
§2:1), applied at supply (§2:4) and "at the sites the channel's audience is read today, and at no
new site" (§2:5). ADR-0292 §9 reads that audience from the place, for a hosted medium, as "its own
record" (ADR-0292 §9:5), declared by the user (§9:6). The sites that apply it read "the pass's
audience", the audience of the place a work began in: recall, the news and the short view filter
what is put in front of a work by it (ADR-0281 §4:2, ADR-0359 §5:1, ADR-0356
§9:5), and so do planning's look-ups (ADR-0358 §6:2, §6:3) and the offer of a calendar pull
(ADR-0324 §4:6). What a message may carry was never checked: ADR-0361 §7:4 added "No audience
check ... for a join from another place, for a message into a taken input's place, or for a card",
since "Every place today reaches only the owner", and ADR-0364 §9:3 says "Code checks no audience
yet".

**The code today** knows one person. A channel kind declares its places' audience as
`Audience.PRIVATE`, "The user alone", or `UNDECLARED` (`orchestration/channel_kinds.py`), and the
engine creates every live pass with a `BoundedAudienceSupply` (`orchestration/engine.py`), so the
audience checks that exist never refuse anything.

**The argument.** A work is not tied to the place its stimulus arrived in (ADR-0349 §2:1: "No
activation has a home place"), so what it may say cannot be decided by where it will reply. It
is decided by what it has seen. The owner, to the first rule put to them, which read by where
the reply would go: "how do you know its going to reply to me in that exact chat? I believe we
decided the activation is serpate than the place it arrived on". Their own idea took its place:
let a work fetch what its sender may see, and then "any tool that writes into a space with
family or other audience requires approval. But without that fetch it wouldnt require that."
So a work starts at what everyone in its place may see, narrows as it fetches, and a send that
would reach someone outside what it has seen needs a person to pass it on, by a tap on a card
showing the exact text. That is the mark.

**What the owner decided.** On 2026-11-21 the owner ruled the mark as the coordinator read it
back to them: fetching, what is put in front of a work at the start, the mark, sending, the two
standing approvals, an uncertain audience, a work with no sender, the floor and the ceiling, and
a signal's place, answering "looks good". The floor and the ceiling were their framing. They had
asked whether the instruction should count ("so would it be better if it was just the place and
the context, not the instuction that determines the mark?"), and the rule read back counts it.

**Words.** A **work** is an activation, as ADR-0364 uses the word; its **inputs**, a **sender**,
**identified** and **unidentified**, and whom a work **is for**, are ADR-0368's (ADR-0368 §2:1).
A **place** is ADR-0349's and ADR-0292's, and a **connection** ADR-0364's: an entry of the
Connections section is a connection with one place, or one place of a many-place connection
(ADR-0364 §3:2). What a connection **belongs to** is ADR-0367 §6:1's. A place's **audience** is
§2's. **May see** is ADR-0369 §6:1's, or §6:2's for a reduced form, and a **meet** is ADR-0369
§7:3's. A **line**, a **grant**, a **bar**, **the check** (the grant check) and a **card** are
ADR-0367's; a **yes** is a tap on Approve. To **put in front of** a work is to show any of its
models something it did not ask for by a call; to **fetch** is to be shown something by a call
planning makes. A work's **floor** is §3:1's. A work's **ceiling** is its senders, an
unidentified one counting as a member of anyone alone (ADR-0368 §7:2); a work with no sender has
its floor as its ceiling. A **send** is a call that writes into a place, a message or any other
call whose effect lands where that place's audience can perceive it, and a card, to the people it
is shown to (§5:9); a write into the hub's own stores, such as a record, a task or an approval
request, is not one. A send's **audience** is the audience of the place it writes into, and the
people every card its call needs is shown to. **Admits** is ADR-0365's word. **Lane 7** is the
later decision of #3629 on outside content (ADR-0365 §6). In this document a bare section
reference, such as §5:3, is to this decision's own clauses.

## Decision

We will give every place an audience that names its people, start each work at its place's
audience and put in front of it only what that whole audience may see, have it carry a mark of
everyone who may see all it has been shown, which only shrinks, and check every send against that
mark: a send whose audience is inside it goes, and one that reaches anyone outside it goes only on
a yes from whom the work is for, on a card showing the exact text, or under a standing approval
that person chose.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and when, is
> the owner's planning call, made after it merges.

> **Normative.** Until the mark (§4) and its check (§5:1) are built, every read and every send is
> checked as it is today, and nothing in this decision changes what the running hub reads, shows,
> sends or asks.

> **Normative.** This decision admits no one. It is one of the later decisions ADR-0367 §1:4 names
> as conditions before a person other than the owner is admitted, and what it rules a second
> person needs built is: §2's audience on every place; §3's floor, its bound on what is put in
> front of a work, its bound on what a work with no sender fetches, and its reading of the pass's
> audience; §4's mark on every work, with the mark a task and an approval request record; and
> §5's check on every send and every card.

Standing approvals (§6) and rules for a signal's place (§7) need not be built before a second
person is admitted: until they are, every send beyond a mark asks, and a signal lands where it
does today. ADR-0365 §1:3 keeps the owner the only person a hub admits until a later decision
provides for admitting another and that provision is built. This decision is the last of the
decisions ADR-0367 §1:4 names, and none of them admits anyone.

### 2. A place's audience

> **Normative.** A place's audience (ADR-0292 §9:1) is a set of people: anyone, where it is
> unbounded (ADR-0199 §1:1, §1:2); or, where it is bounded, the people and groups its declaration
> names, each group denoting its members when the audience is read.

> **Normative.** A bounded audience is declared, as ADR-0292 §9:4 and §9:6 have it, by whoever the
> place's connection belongs to, or, for a group's connection, by a person holding the power to
> set its lines (ADR-0367 §6:1, §6:2), by their own act, and it names everyone who can perceive the
> place.

> **Normative.** A kind's declaration that its places are private names, for each place, the
> person its connection belongs to.

> **Normative.** Where a person outside a place's declared audience sends from it, the
> declaration stops holding: the place's audience is anyone until it is declared again.

> **Normative.** Where code cannot bound who perceives a place, such as a speaker in a room, its
> audience is anyone, until the decision that builds voice rules who is present.

A place's audience is who perceives it, not whose it is. Whom a work in a shared place is for
stays ADR-0368 §4:6's, "the person or group its connection belongs to (ADR-0367 §6:1), until a
later decision records a place as someone's of its own", and this decision is not that later
decision. An audience is stated as a reach is (ADR-0369 §7:2): anyone, or named people and
groups. ADR-0364 §3:3's "who it reaches", shown on each Connections entry, is this audience.

### 3. The floor, and what is put in front of a work

The owner: "the place is the floor, and depending on the place, the floor can be lower or
higher".

> **Normative.** Every work has a **floor**, a set of people code fixes from its inputs: for a
> message, the audience of the place it came from; for an input no person sent, the audience of
> the place §7:1 sets for it; for a task's occurrence, the mark its task records (§4:6); and for an
> approval's outcome, the mark its request records (§4:6). A work holding several inputs has as
> its floor the meet of theirs.

> **Normative.** What is put in front of a work, at its start or on any later round, is only what
> every person in its floor may see, within what ADR-0369 §10 lets the work read. Anything
> narrower reaches it only by a fetch.

> **Normative.** A work with no sender fetches only what every person in its floor may see.

> **Normative.** Where an earlier decision filters or offers what a work is shown by the pass's
> audience or its audience posture, as ADR-0281 §4:2, ADR-0324 §4:6, ADR-0356 §9:5, ADR-0358
> §6:2, §6:3 and §7:3, ADR-0359 §5:1 and ADR-0360 §6:1 do, it reads, for what is put in front of
> the work, the work's floor, and for a fetch, or the offer of one, the work's ceiling.

§3:2 is what ADR-0369 §17 left this lane, what narrows a work's reads by the place its stimulus
arrived in: it narrows what is put in front of the work, and leaves the most it may fetch to
ADR-0369 §10. A work with senders fetches no more than each of them may see (ADR-0369 §10:2), so
it may fetch what is narrower than its floor and its mark then shrinks; a work with no sender
cannot (§3:3): with no sender, the ceiling is the floor. Which of the records within §3:2's
bound are put in front of a work and which it fetches is the next prompt review's, as the owner
left it (ADR-0369 §10). §3:4 keeps today's reach: every live pass is bounded to the owner alone,
and with one person the floor and the ceiling are both the owner. A work the system's own upkeep
runs has no input from a place and makes no send: its calls are the ones code lists for its job, none of which leaves the hub
(ADR-0368 §3:7).

### 4. The mark

The owner: "the mark should be computed from whats infront of the model, and the place, and maybe
the instruction no?"

> **Normative.** Every work carries a **mark**: the set of people who may see everything its
> models have been shown so far, which is each input it holds, its task's instruction where it
> has one, the history it was shown, what was put in front of it and what it fetched. Nothing a
> model was shown is exempt, its instruction, the stimulus or its task's, included.

> **Normative.** The mark starts as the work's floor, and each thing a model of the work is shown
> meets it, taken when it is shown. Nothing widens it, a yes included.

> **Normative.** For the mark, the people who may see a thing are: for a record, and for a section
> or a result code builds from records, those who may see each of those records in the form it
> was shown; for a message or an input no person sent, and for a message shown from a place's
> window, the audience of the place it was said in or arrived in; for a task's occurrence and its
> instruction, the mark its task records; and for an approval's outcome, the mark its request
> records.

> **Normative.** Nothing counts toward the mark under this decision but what §4:3 names and the
> text code ships or the owner sets for every work alike, such as a model's instructions
> (ADR-0334) and the tools' descriptions, which counts as seen by anyone.

> **Normative.** Code keeps the mark, from what the work's episode records its models were shown.
> No model sets or changes it.

> **Normative.** A task records the mark its setting work carried when it set the task, and an
> approval request records the mark the asking work carried when it asked.

> **Normative.** A task or an approval request written before it could record a mark is read as
> recording the person it is for.

The proposal's line:

```text
the sender  ⊆  the mark  ⊆  the audience of the place the stimulus arrived in
```

The floor is where the mark starts and the widest it can be. The ceiling is the narrowest it can
get: a work fetches only what its senders may see (ADR-0369 §10:2), and every place a sender's
input came from has them in its audience (§2:4), so its senders stay in its mark however far it
shrinks. These are sets of people, not points on a line: two fetches from two groups leave only
the people in both. A work with several senders has all of them as its ceiling. A work with no
sender has its floor as its ceiling, so its mark stays its floor.

The mark is about who may see. Outside text has no audience and no mark of its own here: where it
is read from a record, the record counts under §4:3, and what reading outside text does to a work,
and who has had a say in it, are lane 7's. Whether a model is shown its mark or its floor, and in
what words, is the next prompt review's.

### 5. Sending

> **Normative.** Code checks every send against the mark of the work that makes it, with no model,
> before it runs. This check joins ADR-0306 §4:1's checks: a send runs only where every check
> allows it, and neither this check nor a grant lifts the other.

> **Normative.** A send whose whole audience is inside the mark passes it.

> **Normative.** A send whose audience reaches anyone outside the mark needs a yes from whom its
> work is for (ADR-0368 §2:1). It runs nothing and comes back as ADR-0361 §2:4 has a call ruled
> to need the person, and its card is ADR-0361 §2:11's, whose exact line shows the text the send
> carries.

> **Normative.** Where whom the work is for is not in its mark, a send beyond the mark is not
> done, saying why.

> **Normative.** That person's yes makes the send their own act of passing on (ADR-0365 §3:3,
> ADR-0369 §11:1): the call under its ticket is checked for them as ADR-0367 §5:5 rules and passes
> the mark, and the yes covers a further card that call needs only where that card shows nothing
> beyond what the person's own card showed, the same exact call and the same `why`. It widens
> neither the mark nor any record's reach.

> **Normative.** Where a work is not a person's (ADR-0368 §9:5), a send beyond its mark is not
> done, saying why, until the further decision ADR-0368 §7:4 waits on rules how such a work asks
> and from whom.

> **Normative.** A message into a place one of a work's own inputs came from stays outside the
> grant check (ADR-0367 §4:7) and is checked against the mark as every send is: it goes where
> that place's whole audience is inside the mark, and otherwise as §5:3 to §5:6 rule.

> **Normative.** Every other send passes both the grant check (ADR-0367 §4:1) and the mark. Where
> both need a yes, the mark's is asked first.

> **Normative.** A card is a send to the people it is shown to. A card that asks for a yes under
> §5:3 passes the mark, and any other card is shown only to people inside the mark of the work
> that asks, or once a yes under §5:5 covers it.

§5:7 carries to the mark what ADR-0367 §18 recorded for the grant check, that a work can always
answer its own sender: a work can always answer its own sender in the place the request arrived,
inside the mark. The two checks ask different things. The grant check asks whether whoever the work acts for
may make the call at all (ADR-0367 §4); the mark asks whether what the work has seen may reach the
people the call reaches. A reply where the request arrived needs no grant, and still carries only
what everyone there may see; and since the sender's own private place has only them in its
audience, a work can always answer them there as far as the mark is concerned, whether that place
also passes the grant check being ADR-0367's. Where a call needs both a yes for the mark and a
yes another person's grant asks for (ADR-0367 §5:6, §6:3, §10:1), the mark's comes first, from
whom the work is for, so the card that person sees later shows only what was passed on to them.

A send beyond the mark is not refused: the owner's words were "requires approval". Its card is
ADR-0361's, a request for one exact call, written by `request_approval` and answered by a tap
(ADR-0361 §2, §4), and its yes is a ticket the work runs once (ADR-0361 §5). The person it goes to
is ADR-0361 §2:6's, whom the asking work is for. That is the sender for a sender's work, the
task's person for a task's (ADR-0350 §6:4), and, for a signal no person sent, whoever its
connection belongs to (ADR-0368 §3:5), the person who manages that connection.
The yes is what ADR-0365 §8 left this lane, how a person passes something on: by their own act, on
a card. What reading outside text does to a send is lane 7's.

### 6. Standing approvals

Two standing approvals keep cards from becoming a habit, each a grant the person chose.

> **Normative.** A standing approval is a grant of ADR-0367 §3:1's shape that stands in for one
> person's yes under §5:3: who, that person; what, to send into one named place beyond the mark of
> a work for them; how, allowed; its bar, set as every bar is (ADR-0367 §4:4); its conditions; and
> who set it, that person.

> **Normative.** There are two kinds: "always, for this task and this place", whose condition is
> one task, offered on the card of a send by that task's work; and a switch per person and place,
> with no such condition.

> **Normative.** Only the person a standing approval names makes or removes it, by their own act:
> a tap on the card that offers it, or an act on a surface. No work makes one.

> **Normative.** A standing approval stands in for the mark's yes alone. It covers no card, never
> answers the grant check, never turns the policy's deny into anything else, never lifts the
> outside-content stand-in (ADR-0306 §4:4), and widens no mark and no reach.

> **Normative.** A send a standing approval covers passes the mark with no yes asked.

A task's condition is a kind of condition ADR-0367 §3:4 lets a later decision add, and the switch
uses the place as a line's thing. A person who never wants to be asked when they tell the
assistant to post in the flat's chat turns on the switch; a weekly rota set from a private chat and posted in the flat's chat asks on its first run
and offers the other. Each is the person's choice made once, as an instruction given in advance is
theirs (ADR-0368 §6).

### 7. Which place a signal lands in

> **Normative.** The place an input no person sent arrives in is set by a rule on its connection,
> made by whoever the connection belongs to, or, for a group's connection, by a person holding the
> power to set its lines (ADR-0367 §6:1, §6:2), by their own act. With no such rule, it arrives
> where it does today.

The owner: "it could be set where doorbell is directed under house level". So a doorbell ring can
land in a place whose audience is the house, and its work starts at the house: it may be shown and
fetch what the house may see, and tell the house. A conversation at the door is a different
input, from a person, in a place whose audience is anyone. A rule on a connection routes its
signals; it is not a line and gives no one anything. A work with no sender asks whom it is for,
whoever its connection belongs to, where it may ask at all (§5:3, §5:6), so a ring on a group's
connection asks no one until ADR-0368 §7:4's further decision.

### 8. The same person from a second place

ADR-0368 §4 left this lane "What it does to the audience mark". An input that joins a work from a
second place meets its floor (§3:1) and its mark (§4:3) with that place's audience, so the mark
shrinks to the people in both places' audiences, which always includes the sender (§2:4). No
further rule is needed, as ADR-0368 §4's note has it for the level and the grants. A work with several senders in one shared place
(ADR-0368 §4:3) has that place's audience as its floor and all of them as its ceiling.

### 9. Worked cases

The proposal's cases, with the clause that settles each. The last two are from the rulings.

| What happens | The mark | Outcome |
| --- | --- | --- |
| A roommate asks in the flat's chat when bin day is | The flat | Answered there, no card (§5:7) |
| You ask in the flat's chat when your dentist appointment is | The flat, then you alone once your calendar is fetched | Answered privately, no card (§5:2). Saying it in the flat's chat needs your tap (§5:3) |
| You say privately "tell the flat I'll be late with rent" | You alone: the instruction counts (§4:1) | A card with the text (§5:3), unless your switch for the flat's chat covers it (§6:2) |
| A roommate asks in the flat's chat when your appointment is | The flat; nothing is fetched | Their work may not read your calendar (ADR-0369 §10:2) |
| A weekly task set from the flat's chat posts the rota there | The flat (§3:1, §4:6) | No card |
| The same task, set from your private chat | You alone | A card on the first run, with "always for this task and place" (§6:2) |
| A courier at the door asks where to leave a parcel | Anyone | Answered there under what anyone holds at the door (ADR-0368 §3:4); nothing narrower can be fetched (ADR-0369 §10:2) |
| The doorbell rings, and its connection's rule lands it at the house | The house (§7:1) | It may tell the house; nothing narrower can be fetched (§3:3) |
| That work would speak through the door's speaker | The house; the door is anyone | Beyond the mark: a yes from whom it is for (§5:3), where it may ask at all (§5:6) |

### 10. What ADR-0361 §7:4 and ADR-0217 §2 become

**ADR-0361 §7:4** said no audience check was added for three things, and that the audience design
"narrows each of them when it lands". Each becomes:

| ADR-0361 §7:4 named | Becomes |
| --- | --- |
| A join from another place | No check on the join itself. The input joins as ADR-0349 and ADR-0361 §7:1 rule, and meets the work's floor and mark with its place's audience (§3:1, §4:3, §8) |
| A message into a taken input's place | A send into a place one of the work's own inputs came from: outside the grant check and checked against the mark (§5:7) |
| A card | A send to the people it is shown to (§5:9): a card asking for the mark's yes goes to whom the work is for, who is in its mark (§5:4); any other card only to people inside the mark, or once the mark's yes covers it |

**ADR-0217 §2's rule** is the same rule over more records, at one more moment, with one addition.
It says a record is emitted on an output channel only where everyone who can perceive it is in
the record's placement, and the sites that apply it read the pass's audience, the audience of the
place the work began in. Since a work is not tied to that place, this decision applies the rule twice.
What is put in front of a work is filtered to the place it began in (§3:2), which is what those
sites do today, now with ADR-0369 §6:1's domains and lines beside the reach. What a work fetches is
bounded by ADR-0369 §10, not by that place (§3:4), and the rule moves to the send: a send whose
audience is inside the mark reaches only people who may see everything the work was shown, each
record's reach included, since ADR-0369 §6:1 makes the reach a condition of seeing. The addition is
the card: a send beyond the mark may carry what the work was shown, on the yes of whom the work is
for, which is their act of passing it on, telling and not sharing, so it widens no reach (ADR-0369
§11). The rule's conjunction with ADR-0199 §3's classes (ADR-0217 §2:2), its reduction today
(§2:3) and its withholding at supply (§2:4) stand for what is put in front of a work.

### 11. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0217,
> ADR-0292, ADR-0306, ADR-0324, ADR-0356, ADR-0358, ADR-0361, ADR-0364 and ADR-0368 and in a dated
> header note on each, atomically with this ADR under ADR-0070 and ADR-0082, preserving their
> ratified bodies. The replacements take effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0217 §2:1, a record emitted only where every perceiver is in its placement | In the addition alone: a send beyond its work's mark may carry what the work was shown, on the yes of whom the work is for or under their standing approval (§5:3, §5:5, §6:5) |
| ADR-0217 §2:5's *no new site* half | In the addition alone: the mark is checked at every send (§5:1) |
| ADR-0292 §9:6, the user declares every bounded audience | In who declares and what it names: whoever the place's connection belongs to, or a person holding the power to set its lines, naming the people and groups it is bounded to; a kind's private names the connection's person; and a declaration stops holding when someone outside it sends from the place (§2:1 to §2:4). An undeclared audience is still unbounded |
| ADR-0306 §4:1, the checks a call passes | In the addition alone: the mark, for a send, once built (§5:1). Its other checks and their order stand |
| ADR-0306 §4:7 and ADR-0356 §7:7, a message into its input's place checked by its place alone | In the addition alone: it is also checked against the mark (§5:7). It stays outside the grant check |
| ADR-0324 §4:6, the calendar pull offered on no pass of unbounded audience | In what the offer reads: the work's ceiling, a fetch's (§3:4) |
| ADR-0358 §6:2, §6:3 and §7:3, a look-up under the pass's audience | In what a look-up reads: the work's ceiling, not the audience of the place its stimulus arrived in (§3:4). What it shows then meets the mark (§4:2) |
| ADR-0361 §2:6, what a request records | In the addition alone: the mark the asking work carried when it asked (§4:6) |
| ADR-0361 §7:4, no audience check for a join, a message into a taken input's place or a card | Whole: §5:7, §5:9 and §8, as §10 sets out |
| ADR-0364 §9:3's last sentence, "Code checks no audience yet" | Code checks every send against its work's mark, once built (§5:1). The rest of §9:3 stands |
| ADR-0368 §6:3, what a task records | In the addition alone: the mark the work that set it carried when it set the task (§4:6). It still records no list of actions or calls |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0365 §6's lane 6, and its §8 note that how a person passes something on is lane 6's | §4 to §6: a yes on a card showing the exact text (§5:5), or a standing approval (§6) |
| ADR-0367 §17's lane 6, the audience mark and standing approvals; its §12 note, what a message may carry | §4, §5 and §6. A standing approval is a line of ADR-0367 §3's shape (§6:1), as ADR-0367 §3:4 provides |
| ADR-0368 §12's lane 6: the mark and how it shrinks, for one person's inputs from several places; which place a signal lands in | §4, §8 and §7:1 |
| ADR-0369 §17's lane 6: what narrows a work's reads by the place its stimulus arrived in; how a person passes something on and what a send needs; standing approvals; which place a signal lands in; ADR-0217 §2 | §3:2 to §3:4, §5, §6, §7:1 and §10. ADR-0369 §11:1's passing on is §5:5 |
| ADR-0349 §11's, ADR-0350's and ADR-0332's rows for the audience where a message lands (#2590) | §5. ADR-0364's consequence that the audience design lands before a second person's connection does is §1:4 |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0367 §4:7 | A message into a place a work's own input came from stays outside the grant check. The mark is a check beside it (§5:7), not a change to it |
| ADR-0367 §3 to §5 | A standing approval is a line; a ticket's call is checked for its tapper (ADR-0367 §5:5); the mark adds no bar |
| ADR-0368 §2, §3, §4:6, §7:4 and §9:5 | Read as given: whom a work is for is whom the mark's card goes to; a work that is not a person's asks for nothing |
| ADR-0369 §6:1, §6:2, §10 and §11 | Read as given: §6 is who may see each thing for the mark; §10 is the most a work may fetch, which §3:2 narrows only for what is put in front of it and §3:3 for a work with no sender |
| ADR-0349 §2:1 | No activation has a home place: the floor is where a work began, and ties it to nothing |
| ADR-0292 §9:1 to §9:5 and §9:7; ADR-0199 §1 and §3 | An audience is still read from the place and never derived from admission; undeclared is still unbounded; classes stay a conjunct |
| ADR-0217 §2:2 to §2:4 | They hold for what is put in front of a work (§10) |
| ADR-0281 §4:2, ADR-0356 §9:5, ADR-0359 §5:1 and ADR-0360 §6:1 | Each filters what is put in front of a work, and reads the floor (§3:4) |
| ADR-0350 §6:7, ADR-0361 §6:7 and ADR-0364 §9:4 | Where a task's or an approval's work may send stands; each send also passes the mark |
| ADR-0350 §3:10 | Where a task was set stays data, puts no place on a list and decides no one; the mark a task records is a set of people (§4:6) |
| ADR-0361 §2:4, §2:11, §4 and §5 | The mark's card is an ordinary request and ticket for one exact call |
| ADR-0364 §3:3 | "Who it reaches" is the connection's audience (§2) |

### 12. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made by
the lane the owner's planning dispatches, under this decision once merged. A new Protocol ships as
a triad.

- **A place's audience:** a value naming anyone, or people and groups, on each place's record
  (ADR-0292 §9:5), replacing the kind-level `Audience` of `orchestration/channel_kinds.py` as what
  is read, with the act that declares it (§2:2) and its lapse (§2:4). The shape of a reach naming
  people and groups is ADR-0369 §16's.
- **The floor and the mark:** values on the activation's state and its frozen episode, kept by
  code (§3:1, §4:5), with the meet of ADR-0369 §7:3.
- **What is put in front of a work and what it fetches:** the pass's audience posture
  (`TurnSupply`, `BoundedAudienceSupply`) replaced by the floor for what is put in front of a work
  and the ceiling for a fetch (§3:2 to §3:4), passed to the filter ADR-0369 §16 names.
- **The check:** the authorizer reads a send's audience and its work's mark and rules a send beyond
  the mark to need whom the work is for (§5:1, §5:3), and a card's audience before it is posted
  (§5:9).
- **Tasks and requests:** `ScheduledTask` and the approval request each record a mark (§4:6).
- **Standing approvals:** two kinds of ADR-0367 §16's line, with a condition naming one task (§6).
- **A signal's place:** the rule on a connection naming the place its signals land in (§7:1).

### 13. What this decision leaves to others

Each is left, by ADR-0365 §6's cut or by the owner:

- **Lane 7:** outside content: who has had a say in a work, and what reading outside text does to
  a send.
- **The next prompt review:** which records within §3:2's bound are put in front of a work and
  which it fetches; the order "say it in the shared place, then fetch"; whether and how a model is
  shown its mark or floor; the wording of a card and of a send's outcome.
- **A further decision:** how a work that is not a person's asks for a yes, and from whom
  (ADR-0368 §7:4); a standing rule and how it covers a signal (ADR-0368 §12); a place recorded as
  someone's of its own (ADR-0368 §4:6).
- **The decision that builds voice:** who is present in a room (§2:5).
- **The owner:** where the bars of standing approvals sit (ADR-0367 §4:4).
- **Left out by the owner:** forgetting and retention; voice and who is present in a room; two
  equal owners.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 14. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3 and §1:4**: nothing changes until built, and what a second person needs built; standing
  approvals and signal rules need not be.
- **§2**: an audience as a set of people stated as a reach is; who declares a bounded one (§2:2);
  that a kind's "private" names the connection's person (§2:3); that a declaration lapses when
  someone outside it sends from the place (§2:4), which keeps the senders inside the floor. §2:5
  reads the ruling's widest audience as anyone.
- **§3:1**: the floor for each kind of input. A task's floor is the mark its task records, and an
  approval's the mark its request records, so a task set from the flat's chat starts at the flat and
  one set privately starts at its person, as the proposal's cases have them; a work with several
  inputs takes the meet of their floors.
- **§3:2's "on any later round"**, beyond the ruling's "at the start".
- **The ceiling**: the owner's phrase is "who its for", and the proposal's the sender. Where
  ADR-0368 makes them differ, this decision takes the narrowest reading. An unidentified sender
  counts as a member of anyone alone; a task's work, a standing rule's and an approval's have no
  sender in ADR-0368's sense, so their ceiling is their floor (§3:3), and nothing narrower than it
  can be fetched. A task set privately therefore keeps its person's private things within reach,
  through its floor, and one set in the flat's chat fetches only what the flat may see.
- **§3:4**, reading the pass's audience as the floor for what is put in front of a work and the
  ceiling for a fetch.
- **§4:2's "taken when it is shown"**, so a rule removed later does not widen what was already seen
  (ADR-0369 §8); **§4:3**, who may see an input, a window's message and a task's instruction;
  **§4:4**, that the text shipped or set for every work alike, a model's instructions included,
  counts as seen by anyone, and nothing else counts; **§4:6**, the mark a task and a request record, and
  **§4:7**, what one written before records.
- **§5's words** for a send, including a call whose effect a place's audience perceives and a card;
  that a write into the hub's own stores is not a send.
- **§5:3**: the yes comes from whom the work is for, which is the sender for a sender's work and,
  for a work with no sender, whoever its connection belongs to; **§5:4**, that where that
  person is outside the mark the send is not done; **§5:5's** last clauses, that the yes covers a
  further card its call needs only where that card shows nothing it did not, and widens nothing.
- **§5:8**, that the mark's yes is asked before a grant's, and **§5:9**, that a card is a send.
- **§6:1**, each standing approval's shape; **§6:3**, that only its person makes one, by their own
  act, and no work does; **§6:4**, what it never covers.
- **§7:1**: who sets a signal's rule, and that with none a signal lands where it does today.

## Consequences

- A second person can be admitted without a work telling one person what another said privately:
  what a work has seen decides where it may speak, and a person passes on more only by their own
  tap.
- A work answers a question in the place it was asked without a card, as long as it has fetched
  nothing narrower than that place; fetching something private and answering privately needs no
  card either.
- Every send is checked by code, so what a model says cannot widen who learns something; the risk
  that remains is the person's own, when they tap yes on the exact text.
- Lane 7 can rest on §5:7, that a work can always answer its own sender in the place the request
  arrived, inside the mark, and decide what outside text does to a send on top of it.
- A work with no sender is limited to what everyone in its floor may see, so a doorbell can tell the
  house and nothing more private.
- Planning's look-ups may now return what is narrower than the place a work began in, which they
  could not under the pass's audience; the mark, not the look-up, is what keeps it from that place.
- Nothing changes in the running hub until the owner's planning dispatches the build (§1:3), and no
  second person is admitted until ADR-0367 §1:4's conditions are met.
- **Revisit** once voice is built and code can tell who is present in a room (§2:5), or if cards for
  sends beyond the mark become a habit people tap through.

## Alternatives considered

- **Decide what a work may say by where it will reply**, as ADR-0217 §2 and ADR-0199 read the
  output channel. Set aside by the owner: "how do you know its going to reply to me in that exact
  chat? I believe we decided the activation is serpate than the place it arrived on".
- **Fix a work's reads at the start by where its stimulus arrived, and use private things from a
  shared place only by starting a new work in the person's private place.** Set aside for the
  owner's idea: fetch, and ask before a send that would reach anyone the fetch did not cover.
- **Start the mark at the sender**, so every send from a private chat asks. Set aside by the owner:
  "maybe a mark shouldnt start as {you} in a private chat, it starts as wide as possible based on
  the current context its given and fetches". Taken: the floor (§4:2).
- **The instruction and the mark: exempt it.** Set aside, in the proposal: exempting it "saves one
  tap per task and leaves private detail in an instruction unchecked". Taken: it counts (§4:1).
- **A refusal for a send beyond the mark.** Set aside: the owner's rule is that it "requires
  approval", and passing on is the person's to do (ADR-0365 §3:3).
- **A mark that records whose records narrowed it**, so only their owner could pass them on. Set
  aside by the owner's ruling on passing on: the person something was shared with may pass it on,
  and the mark is a set of people.
