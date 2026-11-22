# People, authority, audience and outside content on one hub

**The question.** When a hub serves more than one person, how does it know who
it is dealing with, what each of them may do and see, and what reading someone
else's text does to the work that read it?

This is the record of three design walks the owner ran with the coordinator on
2026-11-19 and 2026-11-21. Each ruling below was made in chat; the points the
owner has not ruled are listed under "What it leaves open".

## The baseline

Wiki pages read at revision `84f20c8`:
[Permission and approval](https://github.com/leonapivato/ai-assistant/wiki/Permission-and-approval),
[Authorizing](https://github.com/leonapivato/ai-assistant/wiki/Authorizing),
[Outside content lineage](https://github.com/leonapivato/ai-assistant/wiki/Outside-content-lineage),
[Digesting](https://github.com/leonapivato/ai-assistant/wiki/Digesting),
[User profile](https://github.com/leonapivato/ai-assistant/wiki/User-profile) and
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels).

The decisions whose clauses this would touch:

| Decision | What it says today | What would change |
| --- | --- | --- |
| ADR-0099 §1, §3 | "A hub has exactly one principal: the owner." "A second person in the household is served by their own hub." | One hub may serve several people, and each holds the data rights over their own domain. A hub each stays the answer for separate households. |
| ADR-0351 §6 | An input carries the user's authority or none. The owner kept it so "for now", adding "eventually I think there can be levels to authority". | Authority has levels (sureness). |
| ADR-0350 §3 | "A scheduled task carries no authority, whoever set it." | A task's work carries its author's authority, checked at each call. |
| ADR-0345 §2 | The owner is the one person a holder names "until a decision on identified people adds others". | This is that decision. |
| ADR-0338 §2 | "Code resolves the person an activation is for from its recorded trigger." | Kept, and widened: a person, a group or no one; and two more facts beside it. |
| ADR-0364 §4 | "`P1` is the owner, a stable label … the same in every work." | Open: labels may become handles for one work only. |
| ADR-0361 §7 | "No audience check is added for a join from another place, for a message into a taken input's place, or for a card." | The audience check below. |
| ADR-0217 §1, §2 | A record's reach is one of two sets, anyone or the owner. | Reach names people and groups. |
| ADR-0306 §4 | "An activation has read outside content when its record says so", and a call leaving the hub then needs the user. | Replaced by a level carried on text, and by where raw text may be read at all. |
| ADR-0307 §9, ADR-0308 §4 | "Planning never reads raw outside content." | Largely kept. The reader stops being limited to one question. |
| ADR-0356 §15 | Whose side planning takes in a household is listed as deferred "while the owner holds full control". | Settled by who a work is for. |

In the code today the only person is a constant for the owner, the person a
work is for is computed from the channel type and is the owner or nobody,
authority is one true or false value, and the authorizer takes no person at
all. Every live pass is created with the owner's records open, so the audience
checks that exist never refuse anything.

## Three principles the owner set

- **Least privilege.** No grant means no. A new person starts with nothing.
  Every grant is as narrow as the need.
- **Permission comes from whoever a thing belongs to; limits come from above.**
  The owner can limit and remove a person, but cannot act through their
  accounts or read their records. The owner's reason: "Why would mom feel
  comfortable putting her email there if the owner can just pretend to be her
  and send anythign from her email?"
- **Sharing is like telling someone.** What a person was shown, they know, and
  they may pass it on. The system never passes anything on by itself.

Code enforces all of it. The models see outcomes, never the rules.

## Part 1: people and authority

**People, groups and grants, not ranks.** The design has to serve one person
alone, a family, friends, roommates, a house cleaner, a mail carrier and a
stranger, so it has no household roles in code.

- A **grant** says who (a person or group) may do what (an action on a tool,
  a connection or a kind of record), how (allowed, or allowed with approval),
  and who set it. A limit is the same line saying no. Grants take conditions:
  a time window, an end date, one connection.
- **Groups** are sets the owner defines. One is built in, "anyone", for people
  who are not identified. It is normally granted things on one connection only,
  such as the door.
- **Powers can be handed on in part,** each as its own grant scoped to one
  group or thing: set grants for a group, answer its approval cards, manage a
  thing, change a group's membership, add and remove people. Nobody hands on
  more than they hold, and handing a power on is itself a power, off by default.
- **Presets** make "starts with nothing" usable: a preset is a list of ordinary
  grants applied in one step when a person is added, shown to the owner first
  and editable afterwards. The code only ever reads grants. A shipped limit,
  such as never claiming to be human (#3600), is a default the owner can remove.

**Domains.** Each independent person has a domain: their linked accounts and
their private records. Inside it they are the top. A managed person, such as a
child, is the exception: their manager holds stated powers over their domain,
set when they are added and visible to them.

**Knowing who someone is.** A person is a record with a stable identifier and
linked accounts. Linking is a privileged act; the system may suggest a link by
approval card and never makes one. Code decides who sent an input from the
account it arrived by. A model never does.

Being established comes in levels. The owner's words: "An email from me is
likely me, but also more likely to be faked or hacked then if I was standing in
my home using the home device with voice and face recognition."

| Sureness | Meaning | Examples |
| --- | --- | --- |
| None | Claimed or unknown | "It's the cleaner" from an unlinked number |
| Weak | A linked account whose sender can be faked or is commonly broken into | Email, SMS |
| Normal | A linked account behind its own login | A messaging account, an enrolled phone |
| Strong | Several independent signals at once, or a fresh check | A home device with voice and face; a fingerprint just now |

Each kind of connection declares the most it can give. A grant names the least
it accepts. A shortfall is not a refusal: it becomes an approval card on a
stronger connection of the same person, using the cards of ADR-0361.

An account is only as sure as it is exclusive. An account anyone else may send
through cannot establish its person, so "the person's own only" is the default
for any account that identifies someone.

**Whose work it is.** Code records three facts on every work when it starts.

| Fact | Values | Read by |
| --- | --- | --- |
| Who it is for | A person, a group, or no one | Recall, the person block, planning's goal, approvals, tasks, the observer, notifications |
| Whose authority it carries | A sender now, a person in advance (a task or a standing rule), or none | The authorizer on every call, the tool list, the task manager, memory, the audit trail |
| Sureness | The four levels | The authorizer, approvals, memory |

- A message from an established person is for them and carries their authority.
- A message from someone claimed or unknown is for whoever the connection
  belongs to, and carries only what "anyone" holds on that connection.
- A signal nobody sent, such as a doorbell ring, carries no authority. Only a
  standing rule a person set up can act on it.
- The system's own upkeep is for no one and may only do what the code allows
  that job inside the system.
- An input from a second sender may join a work. The work then holds only what
  every sender holds, area by area, and the lowest sureness.
- There is no acting on another person's behalf. "Remind Sam" is the sender
  messaging Sam on the sender's own authority.
- A shared approval card goes to those who hold the power to answer it. The
  first tap wins, and a yes gives no more than the tapper holds.

**Instructions given in advance are not a special case.** The owner asked why
they should be. A task or a standing rule carries the authority and sureness of
whoever set it, and each call is checked against that person's grants at the
moment it runs.

**What the models see.** Understanding gains one job: resolve the people a
stimulus mentions to stored identifiers, or say probably, or unknown.
Candidates are found without a model call: the sender's most frequent people,
names matched against a table, people already labelled in the context shown,
and the message's own metadata. Planning gets a People section built by code,
and digs further with a look-up when understanding was unsure. The tool list,
the connections and the People section are filtered to what the work's
authority could use. A resolution only picks a target; the grant check runs on
whoever is actually named in the call.

**Person records.** A record for someone merely mentioned is created
automatically and carries no account and no grants. Linking an account later
keeps the identifier. Two records are merged on a person's yes, or by code
when both carry the same account identifier.

## Part 2: audience and privacy

**Whose a record is.** A record lands in the domain of whoever the work is for:
a person's, a group's, or the hub's shared things, which the owner manages.

**Sharing rules.** Each person sets, in advance, who may see what of their
domain. The default is private.

| Part | Choices |
| --- | --- |
| Who | A person or a group |
| What | Conversations, memories, people, one named account, matters and tasks, or the profile |
| How much | All, a reduced form, or nothing |

A reduced form is fixed by code for each kind: busy or free for a calendar,
names only for people, existence and title for matters and tasks. One item can
go against its rule in either direction. Narrowing is always free. Widening is
a call the authorizer checks on the person's own authority.

Taking a rule back stops future access to the source. What another person's
work already learned stays theirs. A record made from other records takes the
narrowest of its sources when it is written, which the code already does.

A new member of a group sees its domain from the day they joined, unless its
manager opens the past. A person who leaves loses the group's domain and keeps
their own.

**The mark.** A work is not tied to the place its stimulus arrived in, so what
it may say cannot be decided by where it will reply. It is decided by what it
has seen.

1. A work may fetch what its sender may see: their domain, and what others'
   rules open to them.
2. What is put in front of it at the start is only what everyone in the place
   the stimulus arrived in may see. Anything narrower has to be fetched.
3. The work carries a mark: everyone who may see everything the model has seen
   so far, the instruction included. It only shrinks.
4. A send to a place whose whole audience is inside the mark goes. A send that
   reaches anyone outside it needs a card to the sender, showing the exact text.

```text
the sender  ⊆  the mark  ⊆  the audience of the place the stimulus arrived in
```

The place is the floor and the sender is the ceiling. These are sets of people,
not points on a line: two fetches from two groups leave only the people in both.

| What happens | The mark | Outcome |
| --- | --- | --- |
| A roommate asks in the flat's chat when bin day is | The flat | Answered there, no card |
| You ask in the flat's chat when your dentist appointment is | The flat, then you alone once your calendar is fetched | Answered privately, no card. Saying it in the flat's chat needs your tap |
| You say privately "tell the flat I'll be late with rent" | You alone | A card with the text |
| A roommate asks in the flat's chat when your appointment is | The flat; nothing is fetched | Their work may not read your calendar |
| A weekly task set from the flat's chat posts the rota there | The flat | No card |
| The same task, set from your private chat | You alone | A card on the first run, with "always for this task and place" |
| A courier at the door asks where to leave a parcel | Anyone | The standing rule answers; nothing narrower can be fetched |

Two standing approvals keep cards from becoming a habit, each a grant the
person chose: "always, for this task and this place", and a switch per person
and place.

Messaging a hub person in their own chat needs no grant by default, and each
person can change that in their profile. Which place a signal lands in is set
by a rule on its connection, so a doorbell ring can be the house's business
while a conversation at the door is public.

**A person's own data.** Each person can see, delete and export their own
domain, and has a log of when it was read under a sharing rule or a manager's
power. On leaving, they take an export and the domain is deleted.

Nothing here relies on a model keeping a secret. A record a work may not read
is absent from it.

## Part 3: outside content

Outside text is one more voice in the work, and it holds no grants. The rule
for a second sender already says what follows: the work holds only what every
voice in it holds. No separate mark is needed.

**Code sorts every read before it happens.**

| The source is | How it is read | Level |
| --- | --- | --- |
| Typed data: a forecast, a time, a status | Directly | Clean |
| A hub person's linked account | Directly | That person's voice, at that link's sureness |
| A source the sender has vouched for, verified by code | Directly | What that kind of connection can establish |
| Anything else | In separate work that cannot cause effects | Its findings: clean if their shape was fixed beforehand, weak if open |

- **The separate work is a spawn limited to look-ups.** It may explore freely
  over several rounds. Only its findings come back to the work that asked, so
  the asking work never holds the raw text and nothing has to be removed from
  it. A work that can act therefore never falls below weak.
- **Text carries its level.** Whatever a work writes, in a call's arguments, a
  note or a message, carries the lowest level in its context at that moment.
  Only fields set by code are clean.
- **A work's level is the lowest of what is in its context now.** A weak
  passage in an earlier episode can be replaced by a constrained answer about
  it, which raises the level again.
- **Seen by a person makes it clean:** delivered to them, and followed by a
  later message from them in that place. Research then runs as people expect:
  look around, report, act on the reply.
- **A model's check softens a drop and never undoes it.** An open summary or a
  content check brings the level to weak, not to clean, and stacking them
  changes nothing.
- **A work can always answer its own sender** inside the mark.
- **Vouching for a source is a grant** in the person's own domain. The default
  is only their own writing. Adding a source needs their authority at normal
  sureness, so a weak work can never vouch for what it just read.

Each person decides what weak may do through the grants they already have. A
summarised web page and a possibly faked email then mean the same thing: the
instruction might not really be theirs.

This would replace the mark that covers a whole activation and spreads to
later works, tasks and matters (#2798), and the interim rule in the authorizer.

## Options considered

| Choice | Taken | Set aside, and why |
| --- | --- | --- |
| Several people | One hub | A hub each: a hierarchy across hubs needs federation, which is not designed |
| The hierarchy | People, groups, grants | Ranks, or a tree: one number bundles what a person may use with whom they may rule |
| The owner's power | Limit and remove, never take over | Full root: nobody would link an account the owner could use as them |
| Advance instructions | Same rule as any instruction | Carrying no authority: every recurring task asks each run, which trains people to tap yes |
| Taking a rule back | Future access only | Checking every source at read time: more machinery, to pull back what people already know |
| Privacy | Filter what a work reads | Read everything and filter what is said: relies on a model keeping a secret it was shown |
| The instruction and the mark | It counts | Exempting it: saves one tap per task and leaves private detail in an instruction unchecked |
| Raw outside text | Read only in work that cannot act | Read it and carry on with reduced authority: whatever that work then writes carries the stranger forward |

## What it leaves open

Suggested by the coordinator and not ruled:

- Another sender's input joins a work only in a shared place.
- Labels are handles for one work; the stored identifier is the stable thing.
- One hub-wide identity per real person, with a view per domain, joined only on
  a matching account identifier.
- After a read at weak, a message to anyone but the sender needs a card.
- The details of vouching beyond "paired with source verification".

Deferred by the owner to the next prompt review: what is put in front of a
model and what it fetches, the contents of the People section, the wording when
something is out of view, and the order "say it in the shared place, then
fetch".

Outside this proposal: forgetting and retention, two equal owners, voice and
who is present in a room, and sureness that fades with time.

What the spawn needs and does not have today: a spawn limited to look-ups, and
findings that return to the asking work in a declared shape. That belongs with
ADR-0349's operations between activations.

## How it could be decided

This is too much for one decision. A possible cut, each its own ADR and merged
before anything implements against it: the amendment to ADR-0099 first, since
the rest stands on it; then people and sureness; grants and delegated powers;
the three facts on a work, with the amendments to ADR-0351 and ADR-0350;
domains and sharing rules; the mark; and outside content.

Refs: #691, #2590, #2856, #2798, #3600
