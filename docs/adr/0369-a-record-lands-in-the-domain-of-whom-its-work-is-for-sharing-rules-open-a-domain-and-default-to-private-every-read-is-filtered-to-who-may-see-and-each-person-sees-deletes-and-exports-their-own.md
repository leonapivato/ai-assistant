# 369. A record lands in the domain of whom its work is for, sharing rules open a domain and default to private, every read is filtered to who may see, and each person sees, deletes and exports their own

- Status: Partially superseded by ADR-0372 (§3:4, §6:1 and §6:3, each in the addition alone: what is said in a place may be seen by its audience then, and a record by those inside its audience label)
- Date: 2026-11-22
- Scope: lane 5 of the seven decisions the people, authority, audience and outside content
  proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)), the lane
  [ADR-0365](0365-one-hub-serves-several-people-each-is-the-top-of-their-own-domain-and-separate-households-keep-separate-hubs.md)
  §6 names fifth: sharing rules and a person's own data. It decides where a record lands (§2);
  the six kinds of thing a sharing rule names, and what a rule says (§3); reduced forms (§4); one
  item against its rule (§5); who may see a record (§6); what a record's reach becomes (§7);
  taking a rule back (§8); joining and leaving a group (§9); what a work may read, through one
  filter (§10); passing on (§11); a person's own data (§12); and the access log (§13). §14 reads
  ADR-0366's views and merges and ADR-0099's rendering floor across domains, §15 records what it
  does to earlier decisions, §16 names the contract changes it would need, §17 what it leaves to
  others, and §18 what it settled where the rulings left a point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the
  coordinator. Their words, verbatim, all of 2026-11-21. On where a record lands and the kinds of
  thing, to the coordinator's question 1 of the audience walk: "Yes" (§2, §3:1, §3:2). On what a
  sharing rule says: "yes, looks straightfoward, anything non-trivial here?" (§3, §4). On taking
  a rule back: "a) what if revoking just prevented future access, nthing to do about the past.
  Similar to how human interaction works. Is this a plausable alternative?" (§8). On joining and
  leaving a group: "b) Looks good, any other real alternatives." (§9). On widening and narrowing:
  "c) Yes, again any othe alternatives?" (§5). On what a work reads: "I leaning towards filtering
  reads for the work. It would have anything thats available to it. We can figure out what gets
  pulled vs pushed when we go of the prompts." (§10). On passing on: "its just like if I trust
  someone with infomration, and they tell people. By trusting someone with infomration, im
  subjecting myself to that risk." (§11). On nothing resting on a model: "I thought the idea is
  that it doesnt tell because its filtered out of the context, not because we rely on it?"
  (§10:6, §10:8). In one numbered reply to the coordinator's questions, on things learned from
  several people, "2.  yea" (§2:5, §7:5), and on a person's own data, "4. yeah" (§12, §13). The
  coordinator assigned 0369 and ratifies it, under the owner's delegation, once its reviews are
  green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides whose each record is, who may see it and what a work may read, which bounds
  the `core` types the build makes, so it takes the adversarial and the architecture review.
  Building it is a breaking change under golden rule 5, through the `core` changes §16 names, none
  of which is made here. It dispatches no implementation (§1:2).
- **Partially supersedes**
  [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md)
  (§1:2, in `OWNER`'s denotation, and §1:9, in `OWNER` keeping it; §1:4's table, §3:1's second
  item and §3:3, in the addition alone; §3:6, §3:7 and §3:9, in which sides supply a setter and an
  instant; §2:5's *no new site* half, in the addition alone; §3:1's first item and §3:14, in who
  makes the act), as §15 records.
- Partially superseded: 2026-11-22 by [ADR-0372](0372-a-place-has-a-start-level-that-what-is-said-there-carries-and-a-work-re-runs-once-without-what-is-narrower-than-its-story.md) — §6:1, in the addition alone: what is said in a place, by a person or by a work, may be seen by whoever was in that place's audience when it was said, someone who joins later getting only what came after; and a record of another domain by whoever was inside the audience label it carries when it was said or written; each under §6:1's reach and limits (ADR-0372 §4:1 to §4:4). §3:4, in the addition alone: the default is private save as those cases provide (ADR-0372 §4:3). §6:3, in the addition alone: code decides those cases from the label and the audience as they were (ADR-0372 §4:6). Every other clause stands. This replacement takes effect on ratification of ADR-0372. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

ADR-0365 let one hub serve several people under three principles: least privilege (ADR-0365
§3:1), permission from whoever a thing belongs to (§3:2), and sharing as telling someone (§3:3).
It gave each independent person a domain, "their linked accounts and their private records", in
which they hold the data rights (ADR-0365 §4:1), kept a fact about another person with whoever
learned it (§4:4), and made the software and an access log the protection of a domain (§5:2).
ADR-0366 kept what a domain knows of a person as that domain's view, "held in that domain, under
that domain's sharing rules" (ADR-0366 §7:1). ADR-0367 made what a person may do a set of lines
and said every later kind of line, "such as a sharing rule", has a grant's or a limit's shape
(ADR-0367 §3:4). ADR-0368 recorded on every work whom it is for: one person, one group, or no one
(ADR-0368 §2:1). Each left this lane its part (ADR-0365 §6, ADR-0366 §12, ADR-0367 §17, ADR-0368
§12). ADR-0367 §1:4 makes this lane one of the decisions that must merge before a person other
than the owner is admitted.

**The code today** knows one person. No stored record names whose it is, since every record is
the owner's. Each memory carries a `Placement` (`core/types.py`) whose reach, `PlacementReach`, is
`ANYONE`, "every person", or `OWNER`, "the set whose one member is the owner" (ADR-0217 §1:2).
ADR-0217 calls that pair "the vocabulary as it stands, not a cardinality this ADR fixes", lets a
later decision add denotations "named people, circles" (§1:9), and has such a decision owe "the
meet for every pair it makes reachable, and a representation for a meet that is **empty**"
(§1:10). A producer deriving a record "writes the **narrowest** reach over every record it was
supplied" (ADR-0217 §3:3, §3:5), which ADR-0329 §12:6 applies to the observer. `MemoryStore`'s
`delete`, `clear` and `export` (ADR-0007) are the owner's data rights over the whole store, and
ADR-0101's two operations scoped by whom a record is about wait for the owner's forgetting design
(ADR-0320 §4:1).

**What the owner decided.** In the audience walk of 2026-11-21 the owner ruled that a record lands
in the domain of whoever the work is for, the six kinds of thing a sharing rule names, and what a
rule says. They proposed that taking a rule back stop only future access, "Similar to how human
interaction works", and agreed the rules for joining and leaving a group and for widening and
narrowing one item. They chose to filter what a work reads over filtering what it says, and
deferred what is put in front of a model and what it fetches: "We can figure out what gets pulled
vs pushed when we go of the prompts." They ruled that the person something was shared with may
pass it on, that things learned from several people need no new rule, and that each person can
see, delete and export their own domain, with an access log.

**Words.** A **domain** is ADR-0365 §4:1's for a person; a group has one too (§2:1). The **hub's
shared things** are the records of a work for no one, which the owner manages. A **kind** is one of
§3:1's six kinds of thing. A **sharing rule** is a line on a kind or an account of a domain (§3),
and a **line on a record** is a line on one named record (§5). A record's **reduced form** is the
fixed form code builds for its kind (§4). A **reach** is ADR-0217's (§7). A **line**, **grant**,
**limit**, **bar**, **condition**, **power** and **the check** are ADR-0367's (§3:1, §3:2, §3:3,
§4:1, §7:1). A **work**, its **senders**, **identified** and **unidentified**, and a **level** are
ADR-0368's. A group's **manager** is a person holding the power to manage it (ADR-0367 §7:1); the
owner holds it over every group (ADR-0367 §7:2). A domain's **person** is the person whose domain
it is; for a group's domain it is read as whoever holds the power to set the group's lines
(ADR-0367 §6:2), and for the hub's shared things as the owner. The **data rights** over a domain are §12's: to
see, delete and export it. A **producer** is ADR-0217's: what writes a memory from records it was
supplied. **Admits** is ADR-0365's word. **Lane 6** and **lane 7** are the later decisions of
#3629 on the audience mark and on outside content (ADR-0365 §6), neither of which has a number
yet. In this document a bare section reference, such as §6:1, is to this decision's own clauses.

## Decision

We will land every record in the domain of whom its work is for, keep each domain private until
its person opens part of it by a sharing rule, state who may see a record in one rule that code
applies wherever records leave the stores, let a record made from others be seen by no one who
could not see them, and give each person the power to see, delete and export their own domain,
with a log of every read of it by another's work.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and when, is
> the owner's planning call, made after it merges.

> **Normative.** Until §2 and §10 are built, every record is the owner's and every read is as it
> is today, and nothing in this decision changes what the running hub stores, reads, shows or
> allows.

> **Normative.** This decision admits no one. It is one of the later decisions ADR-0367 §1:4 names
> as conditions before a person other than the owner is admitted, and what it rules a second
> person needs built is: §2's domain on every record; §10's filter, applying §6:1 as far as it
> reaches with no sharing rule and no line on a record made; §7:1's reading of `OWNER`; §12's
> data rights, with the export and deletion at leaving and at removal; and §13's access log.

> **Normative.** §9 is built before any work is for a group, and §13's log before any sharing
> rule, line on a record or manager's power over a managed person can be used.

Sharing rules, reduced forms, lines on a record and §7:5's reach need not be built before a second
person is admitted: until they are, every domain is private, which is least privilege's default
(ADR-0365 §3:1). ADR-0365 §1:3 keeps the owner the only person a hub admits until a later decision
provides for admitting another and that provision is built; this decision is part of that
provision, not the whole of it, and lane 6 remains among ADR-0367 §1:4's conditions.

### 2. Where a record lands

> **Normative.** Every record a work writes lands in the domain of whom the work is for (ADR-0368
> §2:1): a person's, a group's, or, for a work for no one, the hub's shared things.

> **Normative.** A record a producer writes from a work's episode after the work has ended, such as
> the observer's (ADR-0329, ADR-0338 §2:5), lands where that work's records land. A record brought
> in outside any work, from a connection, account or source, lands in the domain of whoever that
> connection, account or source belongs to (ADR-0367 §6:1).

> **Normative.** A record about a person lands where §2:1 and §2:2 put it, whoever it is about. Its
> subject gains no right over it by being its subject: no data right, no say in its sharing, and
> no sight of it beyond what §6 gives anyone.

> **Normative.** A record's domain, the holders of its supports (ADR-0345 §2) and the people it is
> about (ADR-0100, ADR-0345 §9) are three facts, and none is read as another.

> **Normative.** Things learned from several people take no rule of their own: each record lands
> by §2:1 and §2:2, and a record made from other records takes its reach by §7:5.

> **Normative.** A write changes only records of the domain it lands in. A person's assertion
> (ADR-0368 §9:6) retires, stops or changes no belief of another domain, including another
> domain's belief about that person.

> **Normative.** A producer places a proposal (ADR-0345 §4) only against memories of the domain its
> write lands in, and the writer refuses, with nothing written, a placed proposal naming a memory
> of another domain.

> **Normative.** The owner holds the data rights over the hub's shared things and sets their
> sharing rules, as a person does over their own domain.

The owner's ruling keeps ADR-0099's framing, as ADR-0365 §4 restates it: a fact about another
person "still belongs to whoever learned it", and the person it is about has no say. §2:4 is
ADR-0099 §2:1's separation of principal from subject, with the holder beside them: in Ana's domain, Sam's "the
wall is blue" is Ana's record, held by Sam and about the wall. §2:6 is what ADR-0368 §9 left this
lane, "Which beliefs a person's assertion reaches": only those of the domain its work writes
into. ADR-0099 §4:1 and ADR-0345 §3 stand inside each domain. A write changes nothing of another
domain, so a domain is never changed except by its own works and its own person.

### 3. The six kinds, and what a sharing rule says

> **Normative.** A sharing rule names one of six kinds of thing of its domain, a closed set added to
> and never renamed: **conversations**, with the record of each work in them; **memories**;
> **people**, the domain's views (ADR-0366 §7:1); **accounts**; **matters and tasks**, the
> domain's stories (ADR-0289) and scheduled tasks (ADR-0350); and the **profile**, its person
> model (ADR-0338).

> **Normative.** A sharing rule on accounts names one account, and each account takes a rule of its
> own. Approval cards are no kind: a card goes to whoever holds the power to answer it (ADR-0367
> §10:1), and no sharing rule opens one.

> **Normative.** A sharing rule is a line of ADR-0367 §3:1's or §3:2's shape: who, a person or a
> group; what, one of two actions, to see or to see in its reduced form, on a kind or one named
> account of the domain; any conditions; and who set it. A rule that says nothing is a limit on
> both actions.

> **Normative.** The default is private: where no line lets a person see a record of another
> domain, they may not see it.

> **Normative.** A sharing rule is a grant that allows and never one that allows with approval. A
> read through §10's filter asks no one.

> **Normative.** A sharing rule opens records to be seen and never lets anyone act through an
> account. Acting through an account takes a grant of its own (ADR-0367 §6:1, §6:3).

> **Normative.** Only a domain's person makes a line that opens any of it to anyone, save as
> ADR-0367 §7:7 lets a managed person's manager (ADR-0367 §6:2, §7:7).

> **Normative.** Where sharing rules or lines on a record conflict, ADR-0367 §7:6 decides: the
> line set by whoever stands first in its order holds, and between lines one person set, a limit
> holds over a grant.

A sharing rule is not a new kind of rule. It is a grant, so it carries a bar and conditions as any
line does (ADR-0367 §3:1, §3:3), and the check's rules apply to it as they apply to every line.
Where a rule's bar sits when its person sets none is left as every bar is (ADR-0367 §4:4, §17).
"How much" in the proposal's table, all, a reduced form or nothing, is carried by the action: to
see, to see in its reduced form, or a limit. Someone above a person may limit what that person's
rules open, since a limit only takes away (ADR-0365 §3:2, ADR-0367 §7:7); no one but the domain's
person opens it. A group's domain is open to its members by §9, without a rule, and its person,
under this document's words, is whoever holds the power to set the group's lines: the owner's
ruling names the group's manager, and ADR-0367 §6:2 says who makes lines about a group's things.
Topics are not a kind: the owner left them, for now, to lines on a record.

### 4. Reduced forms

> **Normative.** Code fixes one reduced form for each kind that has one: busy or free for a
> calendar account, a view's name alone for people, and a matter's or task's existence and title
> for matters and tasks.

> **Normative.** Conversations, memories, an email account and the profile have no reduced form,
> nor has any account whose kind of account code fixes none for. A line letting someone see the
> reduced form of a record that has none lets them see nothing of it.

> **Normative.** A reduced form is a value code builds from the record for its kind, and no model
> builds or chooses it. Where a person may see a record's reduced form and not the record, the
> filter gives back the reduced form alone (§10:4).

A reduced form is a value of its own, not the record with parts masked, so ADR-0217 §2:4's bar on
composing a value and then blanking part of it is not reached: a record its reach or the rules
withhold is absent (§10:6), and a reduced form is given only where a line lets it be.

### 5. One item against its rule

> **Normative.** One record can go against its kind's rule in either direction, by a line on that
> record: one that narrows, a limit on seeing it, with or without a grant to see its reduced form;
> or one that widens, a grant to see it or its reduced form.

> **Normative.** Narrowing is always free. The default grant (ADR-0367 §4:3) of the call that makes
> a line only narrowing a record covers the record's domain's person, with a bar of none, for a
> record the work may read (§10).

> **Normative.** Widening is a call the check runs on the domain's person's own authority. The
> default grant of the call that makes a line widening a record covers that person alone, with a
> bar of normal.

> **Normative.** No widening, and no sharing rule, lets anyone see a record outside its reach
> (§7).

The owner's ruling accepted narrowing at any sureness and put widening at normal or above, and
asked as well for approval where the work had read outside content. That half is lane 7's. A grant
to a named person applies only where they are identified, at weak or above (ADR-0367 §5:2), so a
narrowing is made at every level at which a sender is that person, and a sender claimed or unknown
narrows nothing. Where every other bar sits is not ruled (ADR-0367 §17), and this decision sets
none. A person may make or remove any of these lines by their own act on a surface, as any line
(ADR-0367 §3:5). Under ADR-0367 §7:6 a widening of one record does not
hold against a limit its person set on the record's kind: they lift that limit, or pass the record
on by their own act (§11).

### 6. Who may see a record

This is the one rule lanes 6 and 7 build on, and it is numbered here and nowhere else.

> **Normative.** A person may see a record exactly where it is in their own domain, or, for the
> owner, in the hub's shared things; or where they are in its reach (§7) and one of these holds:
>
> - it is in the domain of a group they are a member of, §9 opens it to them, and no limit
>   covering them bears on it;
> - a line lets them, or a group they are in, see its kind or its account; where it was made from
>   other records of its own domain, a line lets them see each kind or account §7:6 records for
>   it, in the form recorded; and no limit covering them bears on it that holds over those lines
>   under ADR-0367 §7:6;
> - a line on the record itself lets them, or a group they are in, see it, and no limit covering
>   them bears on it that holds over that line under ADR-0367 §7:6;
> - they are its group domain's manager (§12:2), or the manager of its domain's managed person and
>   the powers stated when that person was added name seeing their domain (§12:3).
>
> A limit bears on a record where it is on the record, on its kind or its account, or on a kind or
> account §7:6 records for it.

> **Normative.** A person may see a record's reduced form where they may not see the record and
> §6:1 would let them if the lines it reads on the record itself, or on its kind or its account,
> let them see its reduced form in place of the record. The lines §6:1 reads for the kinds and
> accounts §7:6 records are read as it reads them, in the forms recorded.

> **Normative.** Code decides who may see a record from its domain, its reach and the lines as they
> stand when it is read, and no model decides it or takes part.

The owner sees another person's domain only as §6:1 lets anyone (ADR-0365 §4:2). §6:1 is about a
person; what a work may read is §10, which applies §6:1 to each person whose sight bounds the work
and applies each line at its bar and conditions. A person's own domain is theirs without a line
(ADR-0365 §3:1), and no reach keeps them from it.

### 7. What a record's reach becomes

A memory's reach (ADR-0217 §1:2) stays the record's own cap on who may see it. With domains it
needs to say "no one beyond this record's domain", which `OWNER` said while the owner was the only
person, and to name people for a record made from another domain's records.

> **Normative.** `OWNER` denotes the people of its record's own domain: its person, or a group's
> members as §9 opens the group's domain to each, or, for the hub's shared things, the owner; and
> whoever holds the data rights over it (§12:2, §12:3).

> **Normative.** A reach may also name people and groups, each group denoting its members when the
> record is read. `ANYONE` keeps its denotation, every person, the set "anyone" denotes (ADR-0367
> §2:3).

> **Normative.** The meet of two reaches is as follows. `ANYONE` met with any reach is that reach.
> Otherwise the meet names each group both reaches name, and by name each other person both
> denote when the meet is taken, `OWNER` being read for the meet as naming its record's domain:
> its person, its group or, for the hub's shared things, the owner. A meet that names exactly the
> domain of the record it is written on is written `OWNER`, and one that denotes no one is written
> as a reach naming no one.

> **Normative.** No meet is rounded up to a wider reach (ADR-0217 §1:10).

> **Normative.** A record a work or a producer writes from what it read takes, as its reach, the
> meet of: the reach of each record it read (ADR-0217 §3:3, §3:5); the people who could see, in the
> form it was read, each record it read of another domain; and the people who could see each
> record it read of its own domain that a line on that record narrowed. Each is taken when the
> record is written, and the narrowing the last two supply is written with setter `DERIVED`.

> **Normative.** A record made from records of its own domain also records the kinds and accounts
> of those records, with the form it read each in, and every kind, account and form each of them
> records, which §6:1 reads. A fold keeps every kind, account and form either side records.

> **Normative.** Where ADR-0217 §3:1 and §3:14 name the owner's explicit act on a record, for a
> record outside the owner's domain and the hub's shared things it is the act of whoever holds the
> data rights over its domain (§12). An act that narrows is free as §5:2 says, and one that
> widens, made by a work, is checked as §5:3 says.

> **Normative.** §10's filter reads a record's reach where records leave the stores, as one of
> §6:1's conditions.

> **Normative.** Every record a work or a producer writes carries a reach, whatever its kind, as
> ADR-0217 §1:1 has every memory carry one. A record that carries none is read as reach `ANYONE`.

> **Normative.** The setter of a meet's result is the strongest, in ADR-0217 §3:16's order, among
> the eligible sides whose reach is not `ANYONE`, or among all of them where every side's reach is
> `ANYONE`; and its instant follows ADR-0217 §3:9's rule over those of them that carry that setter.
> On `ANYONE` and `OWNER` alone this is ADR-0217 §3:6, §3:7 and §3:9 as written.

`OWNER` keeps the set it denotes today, since today every record is the owner's. What it means in
another person's domain changes: a model's proposed narrowing of a record in Sam's domain
(ADR-0217 §3:15) keeps it within Sam's domain rather than giving it to the owner alone. The
meet is the one ADR-0217 §1:10 owes before a later denotation can be folded, and a reach naming no
one is its representation for an empty meet. That a record made from other records takes the
narrowest of its sources when it is written is the proposal's, and the corpus already rules it:
ADR-0217 §3:3 and §3:5's ratchet, which §7:5 widens from memories to everything a work read, and
§7:9 from memories to every record a work writes, its messages included. For records of another
domain, the people who could see them are fixed when the record is written: what another person's
work learned stays theirs, and no copy is seen more widely than its source could be at the time.
For records of its own domain, §7:6 fixes when it is written which of the domain's kinds bind the
record, and §6:1 reads the domain's rules on them as they stand. A private calendar therefore
cannot reach the flat through a memory made from it, and a record made before its person shared
anything can still be shared once they share its sources. `DERIVED` is not lifted by any act (ADR-0217 §3:13), so a
narrowing taken from another person's record is never undone by the person who learned it.

ADR-0217 §2's rule for what an output channel may carry stands as written, with the reach as this
section gives it. What a work may say where is lane 6's.

### 8. Taking a rule back

The owner proposed it: "what if revoking just prevented future access, nthing to do about the
past. Similar to how human interaction works."

> **Normative.** Removing a sharing rule or a line on a record (ADR-0367 §3:5) stops every read that
> rested on it from then on: §10's filter reads the lines as they stand when a record is read.

> **Normative.** Removing a line changes no record. What a work already read, and every record
> written from it, stays where it landed, with the reach it was written with.

Checking, at every read, whether the sources of a record are still open to its reader was set
aside: more machinery, to pull back what people already know. What a record made from another
domain's records keeps is §7:5's reach, fixed when it was written.

### 9. Joining and leaving a group

> **Normative.** A member of a group sees the records of the group's domain written since they
> joined.

> **Normative.** The group's earlier records open to a member only by a line letting them see them,
> made by whoever holds the power to set the group's lines (ADR-0367 §6:2).

> **Normative.** A member who leaves a group sees its domain no more, keeps their own domain, and
> keeps every record their own works already wrote into it (§8:2).

> **Normative.** For §9:1 and §9:2, a record made from records of its own group's domain counts as
> written when the earliest of them counts as written, and a fold counts as written when the
> earlier of its sides does.

The owner's ruling has the group's manager open the past. Opening it is a line on the group's
domain, so ADR-0367 §6:2 says who makes it: the owner, or a person holding the power to set the
group's lines. A group's domain holds the records of works for the group (ADR-0368 §2:1, §4:6).
§9:4 keeps a member who joined later from seeing an earlier record through a record made from it:
what they may see of the group's past is what the group's lines open to them.

### 10. What a work may read, through one filter

The owner's words: "I leaning towards filtering reads for the work. It would have anything thats
available to it."

> **Normative.** A work reads no more than whom it is for may see: for a person, what §6 lets them
> see; for a group, the records of its domain, and a record of another domain that a line lets the
> group see and whose reach takes in each of its members; for no one, the records of the hub's
> shared things, and what anyone may see.

> **Normative.** A work reads no more than each of its senders may see, and a work with an
> unidentified sender, no more than anyone may see (ADR-0368 §3:4, §4:4).

> **Normative.** A work carrying a person's authority in advance, a task's or a standing rule's
> (ADR-0368 §6), reads no more than that person may see.

> **Normative.** What anyone may see is what §6 lets a member of anyone (ADR-0367 §2:3) see: a
> record whose reach is `ANYONE` that a line lets anyone see. A line applies to a work's read only
> where the work's level is at or above the line's bar and the line's conditions hold for the work
> (ADR-0367 §5:1, ADR-0368 §4:2, §6:4), and a reduced form is given where only a reduced form is
> open.

> **Normative.** Code applies §10:1 to §10:4 in one filter, where records leave the stores, to
> every read a work's stages make, recall, every look-up, the People section (ADR-0366 §9:7), the
> matters list and the person block included, and to every read a producer makes for a work after
> it has ended.

> **Normative.** A record the filter withholds is absent: nothing marks, counts or names it, and
> nothing is fetched in its place.

> **Normative.** A look-up through an account is a call the check runs (ADR-0367 §4:1). A sharing
> rule or a line on the account is the grant that covers the read, and the filter gives back what
> it lets the work see.

> **Normative.** No model takes part in the filter, and no rule rests on a model keeping back
> something it was shown (ADR-0365 §5:1).

§10:1 to §10:3 are the most a work may read. What narrows it further by the place its stimulus
arrived in is lane 6's, and which of the records a work may read are put in front of its model and
which it fetches is the next prompt review's: "We can figure out what gets pulled vs pushed when we
go of the prompts." The owner on a model keeping a secret: "I thought the idea is that it doesnt
tell because its filtered out of the context, not because we rely on it?" A model asked about
something withheld answers as it would about anything it does not know; how that is worded is the
next prompt review's. ADR-0368 §8 filters the tool list and the Connections section to a work's
authority; this section filters records. A work for no one reads the hub's shared things, where
its records land (§2:1), as the owner's ruling has every work read its own domain and what sharing
rules open to it. A work with no sender at all reads what whom it is for may see, and lane 6
narrows it by place.

### 11. Passing on

> **Normative.** A person may pass on what they may see, by their own act. How that act is made, and
> what a send needs, are lane 6's.

> **Normative.** No code passes a record to anyone by itself: no record is written into, or opened
> to, a domain other than the one §2 lands it in, save by a person's own act or a call a work makes
> on a person's authority that the check allows (ADR-0367 §3:5).

The owner's words: "By trusting someone with infomration, im subjecting myself to that risk."
This is ADR-0365 §3:3 applied to records. Passing on is telling, not sharing: it widens no
record's reach, and a sharing rule never opens a record past it (§5:4).

### 12. A person's own data

> **Normative.** Each person may see, delete and export the records of their own domain, by their
> own act. No one else may, save as §12:2 and §12:3 say.

> **Normative.** A group's manager may see, delete and export the group's domain, seeing and
> exporting what §6:1 lets them see of it. The owner may do the same for the hub's shared things.

> **Normative.** A managed person's manager may do for them what §12:1 lets them do, where the
> powers stated when they were added name it (ADR-0365 §4:3, ADR-0367 §8:2), and each such act is
> entered in the managed person's access log (§13).

> **Normative.** Each delete and export acts on one domain, named in the act, and no value of it
> means every domain (ADR-0101 §1:5). Once a person other than the owner is admitted, no surface
> offers any person a delete or an export reaching beyond what §12:1 to §12:3 give them.

> **Normative.** Deleting a record of a domain deletes it there alone. What another domain's works
> already wrote from it stays theirs (§8:2).

> **Normative.** A person who leaves the hub is offered an export of their domain, and then their
> domain is deleted.

> **Normative.** A person the owner removes is offered an export of their domain for a period, and
> their domain is deleted when it ends. Nothing of it is deleted before then.

> **Normative.** From a person's leaving or removal, no one reads their domain, the owner included,
> save to make their export, and no one keeps any of it once it is deleted.

> **Normative.** A surface shows a person only records §6 lets them see.

How long the period after removal lasts is not ruled and is the owner's to set. Removing a person
also ends every line and power they hold (ADR-0367 §7:11) and every task they authored (ADR-0368
§6:6). What other people's works already learned from a domain stays theirs, as the owner's ruling
says. ADR-0007's store operations stand as operations of the store; §12:4 rules what a person is
offered over them. ADR-0101's operations scoped by whom a record is about stay deferred to the
owner's forgetting design (ADR-0320 §4:1), and this decision does not build or reshape them.

### 13. The access log

> **Normative.** Each person has an access log, held in their domain, which they may see. It has an
> entry for each work not for them that read a record of their domain under a sharing rule or a
> line on a record, naming the work, whom it was for, its senders, the line, the records and when;
> and an entry for each use of a manager's power over them, naming the act and when.

> **Normative.** Code writes each entry when the read or the act is made, and no model writes or
> changes one.

> **Normative.** No one deletes or changes an entry of an access log, its person, their manager and
> the owner included. The log ends only when its domain is deleted (§12:6, §12:7).

The log is what ADR-0365 §5:2 names as a domain's protection beside the software: "an access log
its person can see". ADR-0367 §8 left this lane who sees a log of a manager's use of their powers:
the managed person, in their own log. A person's own works are not entered: the log is of reads by
others' works.

### 14. Views, merges and the rendering floor

> **Normative.** A view (ADR-0366 §7:1) is a record of the people kind in its domain. A line letting
> a person see it lets them see the view whole: the name that domain uses, the relation and the
> facts; its reduced form is that name alone.

> **Normative.** A person may see a view of an identity, for ADR-0366 §7:5 and §7:6, where §6 lets
> them see that view or its reduced form. A suggested merge shows them nothing of either view
> beyond that.

> **Normative.** A merge moves no view out of its domain and, as attaching does (ADR-0366 §7:4),
> shows no domain anything of another's view.

> **Normative.** Where a surface shows a belief of one domain to a person of another, ADR-0099
> §4:2 reads as follows: the surface presents it as held in its domain, never as the viewer's own
> belief, and never as its subject's own word or a report from them save where a holder of its
> supports (ADR-0345 §2) is that subject. An asserted belief is shown as the assertion of whoever
> asserted it (ADR-0368 §9:6).

These are what ADR-0366 §12 and ADR-0365 §6 left this lane: what a view shows another domain under
a sharing rule, who may see both sides of a merge, and how ADR-0099 §4:2 reads across domains.
ADR-0099 §4:2's floor, that a surface never lends a belief a warrant it does not have, is unchanged;
§14:4 says whose the belief is when there are several people to lend it to.

### 15. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on ADR-0217's status line and in a
> dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving ADR-0217's
> ratified body. The replacements take effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0217 §1:2, `OWNER` "denoting the set whose one member is the owner", and §1:9, in `OWNER` keeping that denotation | `OWNER` denotes the people of its record's own domain (§7:1), the same set today. `ANYONE`'s denotation, and the rest of both clauses, stand |
| ADR-0217 §1:4's table, `DERIVED` with "`OWNER` only" | In the addition alone: `DERIVED` may also carry a reach naming people or groups, or naming no one (§7:2, §7:3, §7:5) |
| ADR-0217 §3:1's second item and §3:3, the derivation and the ratchet over "every record it was supplied" | In the addition alone: the derivation also meets the people who could see each record read of another domain, and of its own domain where a line on it narrowed it, as `DERIVED` (§7:5) |
| ADR-0217 §3:6, §3:7 and §3:9, a setter and an instant taken from the sides that carry the surviving reach | In which sides supply them: every eligible side whose reach is not `ANYONE`, so a meet no side carries has a setter and an instant and folds in any order. On the two shipped reaches the rule is unchanged (§7:10) |
| ADR-0217 §2:5's *no new site* half | In the addition alone: the reach is also read by §10's filter where records leave the stores (§7:8) |
| ADR-0217 §3:1's first item and §3:14, the owner's explicit act | In who makes it: for a record outside the owner's domain and the hub's shared things, whoever holds the data rights over its domain (§7:7) |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0217 §1:9 and §1:10, further denotations and the meet they owe | §7:2 to §7:4: people and groups as denotations, the meet, and a reach naming no one for an empty meet |
| ADR-0217 §1:1, a placement on every memory | §7:9 puts a reach on every record a work or a producer writes, beside it, as a stacked addition |
| ADR-0365 §6's lane 5: where a record lands (§4:4), the data rights and the access log (§4:1, §5:2), ADR-0099 §4:2 across domains | §2, §12, §13 and §14:4 |
| ADR-0366 §7's and §12's lane 5: what a view shows another domain, who may see both sides of a merge | §14:1 to §14:3 |
| ADR-0367 §17's lane 5: sharing rules, where a record lands and whose it is, the data rights and the access log; its §6 and §8 notes; its §15 row for ADR-0217 §1 | §2, §3, §7, §12 and §13 |
| ADR-0368 §12's lane 5: where a work's records land, sharing rules, what a work for a person or a group may read, which beliefs an assertion reaches | §2:1, §2:6, §3 and §10 |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0217 §1:1, §1:3 and §2:1 to §2:4 | A reach is still on every memory, and still a conjunct (§2:2): §6:1 reads it beside the domain and the lines. Emission on a channel is lane 6's |
| ADR-0217 §3:13 and ADR-0204 §5 | No act lifts a `DERIVED` narrowing, including one §7:5 writes |
| ADR-0217 §3:15 and §7's acts | A model only narrows, and to `OWNER` as §7:1 reads it. The engine members are unchanged; whose act calls them is §7:7's |
| ADR-0329 §12:6 | The observer takes the narrowest placement over its run's supply, now under §7:5 |
| ADR-0286's open episode, `OWNER` with `DERIVED` until it freezes | `OWNER` as §7:1 reads it; the freezing write takes the derivation's reach, now under §7:5 |
| ADR-0099 §2:1, §4:1 and §4:2 | §2:4 keeps the axes apart; supersession works inside each domain (§2:6); §14:4 reads the floor across domains |
| ADR-0345 §2:5 and §2:9; §3; §4:4 and §4:7 | Holders are §2:4's second fact. A memory changes only in its holder's beliefs, inside its domain (§2:6); §2:7 adds a refusal beside §4:7's |
| ADR-0338 §2:1 and §2:5 | The profile is a kind in its person's domain (§3:1); the observer's writes land where §2:2 says |
| ADR-0007; ADR-0101 §1:5; ADR-0320 §4 | The store's operations stand; §12:4 bounds what a person is offered; the subject operations stay deferred |
| ADR-0366 §7:1 to §7:9 | §14 rules only who may see, not how views attach or merge |
| ADR-0367 §3 to §7, §10 | A sharing rule and a line on a record are lines; cards follow the power to answer |

### 16. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made by the
lane the owner's planning dispatches, under this decision once merged. A new Protocol ships as a
triad.

- **A record's domain:** a value naming a person, a group or the hub's shared things, on every
  stored record a work or a producer writes or a connection brings in (§2), set by code; and the
  instant each record was written, for §9.
- **Sharing rules and lines on a record:** the two actions and the six kinds (§3:1, §3:3) and a line
  on one named record (§5), as kinds of ADR-0367 §16's line.
- **Reduced forms:** code that builds each kind's reduced form (§4).
- **The reach:** `PlacementReach` able to name people and groups, or no one (§7:2, §7:3);
  `Placement`'s legal states admitting `DERIVED` with such a reach (§15); the meet (§7:3); the kinds
  and forms §7:6 records; and a reach on every kind of record a work or a producer writes (§7:9).
- **The filter:** each store a work reads takes the people whose sight bounds the read, or every
  read passes one seam that applies §10; which, is the build's.
- **Groups:** when each member joined (§9:1), and the instant each record of a group's domain
  counts as written (§9:4).
- **The data rights:** engine members for a person to see, delete and export one domain, to leave,
  and for the export and deletion at removal (§12).
- **The access log:** a Protocol and a store for it, written by code and kept until its domain is
  deleted (§13).

### 17. What this decision leaves to others

Each is left, by ADR-0365 §6's cut or by the owner:

- **Lane 6:** what narrows a work's reads by the place its stimulus arrived in; the audience mark;
  how a person passes something on, and what a send needs; standing approvals; which place a signal
  lands in; and what ADR-0217 §2's rule for an output channel becomes.
- **Lane 7:** outside content, including the approval the owner's ruling asks for when a work that
  read outside content widens a record (§5:3); vouching for a source.
- **The owner:** where each bar sits, a sharing rule's included (§3); how long the period after
  removal lasts (§12:7).
- **The next prompt review:** which records a work may read are put in front of its model and which
  it fetches; the wording when something is out of view.
- **A further decision:** what becomes of a group's domain when the group is removed; whether a
  group's domain has an access log; topics as something a rule names, which the owner left to lines
  on a record for now.
- **Left out by the owner:** forgetting and retention, including ADR-0101's operations (ADR-0320
  §4); two equal owners; per-person encryption (ADR-0365 §5).

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 18. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3 to §1:5**: nothing changes until built; what a second person needs built, and that sharing
  rules need not be; §9 before a work for a group, and §13 before anything it logs.
- **§2:2**: a producer's record after a work lands where the work's do, and a record brought in
  outside a work lands with whoever its connection, account or source belongs to. **§2:4**, the
  three facts. **§2:6 and §2:7**: a write changes only its own domain, and a placed proposal names
  only memories of it. **§2:8**: the owner holds the data rights over the hub's shared things.
- **§3:3's** reading of "how much" as two actions and a limit; **§3:5**, that a sharing rule never
  allows with approval; **§3:6**, that it never lets anyone act through an account; and, in §3:7
  and the words, that whoever holds the power to set a group's lines opens its domain, where the
  ruling names the group's manager, from ADR-0367 §6:2.
- **§4:2's** "nor has any account whose kind of account code fixes none for", and **§4:3**, that a
  reduced form is code's value and not a masked record.
- **§5:1**, that an item against its rule is a line on that record; **§5:2 and §5:3** as default
  grants, with narrowing at a bar of none, which ADR-0367 §5:2 makes weak for a named person, and
  for a record the work may read; **§5:4**, that no widening passes the reach.
- **§6:1's** shape: the own-domain case, the reach as a condition on every other, a limit holding
  against a membership, the limits that bear on a record through its sources' kinds, and a
  manager's sight; **§6:2**, reduced forms, which reduce only the record and never its sources.
- **§7**: `OWNER` read as the record's domain; people and groups as denotations; the meet; §7:5's
  contributions; and **§7:6**, that a record made from its own domain's records follows that
  domain's rules on its sources' kinds as they stand. That is this decision's reading of the
  proposal's rule that a record made from others takes the narrowest of its sources when it is
  written: what is fixed when it is written is which sources bind, by people for another domain's
  records and by kind for its own. **§7:7**, whose act ADR-0217's owner's act is in another domain.
  **§7:9**, a reach on every record a work writes, so that the rule reaches messages and pages as
  well as memories. **§7:10**, the setter and instant of a meet taken over every side that narrowed
  it, so that folds stay order-free. §7:6's kinds are
  carried through every derivation and fold.
- **§9:1** reads the day a member joined as the moment they joined, and **§9:4** dates a record
  made from the group's records by the earliest of them.
- **§10:1's** reading for a group, its reading for no one being the ruling's; **§10:3**, a task's
  author; **§10:4**, what anyone may see; **§10:5's** list beyond the four ruled reads; **§10:7**, a
  look-up through an account.
- **§11:2**, that no code writes into or opens another domain by itself.
- **§12:2's** "seeing and exporting what §6:1 lets them see of it"; **§12:3's** "where the powers
  stated name it", from ADR-0365 §4:3; **§12:4**; **§12:7**: the period was in the question the
  owner answered ("4. yeah"), and that nothing is deleted before it ends, and that its length is the
  owner's to set, are this decision's; **§12:8's** "save to make their export".
- **§13's** entries, and that no one deletes one; that a person's own works are not logged.
- **§14:1 to §14:3**, and **§14:4's** reading of ADR-0099 §4:2.

## Consequences

- Lanes 6 and 7 can build on one rule for who may see a record (§6:1) and on §10's most a work may
  read, each citing them by clause.
- A second person's domain is private from the day they are admitted, the owner included, and the
  first thing a domain is protected by is code that never hands a record to a work that may not
  read it.
- Sharing is one line per kind or account, and one per record for an exception. Taking a rule back
  is immediate for every later read and reaches nothing already learned.
- A record made from another person's record carries, for good, the people who could see that
  record when it was made, so the ratchet ADR-0217 §3 states can narrow what a domain shares faster
  than its person expects. A record made from one's own records follows one's own rules.
- Each person can take their domain with them and have it deleted, and can see every read of it by
  another person's work.
- Nothing changes in the running hub until the owner's planning dispatches the build (§1:3), and no
  second person is admitted until ADR-0367 §1:4's conditions are met.
- **Revisit** if the ratchet leaves shared domains too narrow to be useful, or once forgetting is
  designed, since deleting by whom a record is about meets §12 there.

## Alternatives considered

- **Read everything and filter what is said.** Set aside by the owner: it relies on a model keeping
  a secret it was shown (§10).
- **Taking a rule back checks every source at read time.** Set aside: more machinery, to pull back
  what people already know. Taken: future access only, the owner's proposal (§8).
- **A record made from others fixes, when it is written, the people who could see every one of
  them, its own domain's included.** Set aside here: a record made before its person shared anything
  could never be shared, since no act lifts a `DERIVED` narrowing. Taken: people for another domain's
  records, kinds for its own (§7:5, §7:6).
- **A new member sees a group's whole past.** Not taken: the rule the owner agreed has a member see
  it from when they joined, unless the past is opened (§9).
- **The subject of a record has a say in it.** Set aside by ADR-0365 §4:4: a fact about another
  person belongs to whoever learned it (§2:3).
- **Approval cards as a seventh kind.** Not taken, in the kinds the owner agreed: a card follows the
  power to answer it (§3:2).
