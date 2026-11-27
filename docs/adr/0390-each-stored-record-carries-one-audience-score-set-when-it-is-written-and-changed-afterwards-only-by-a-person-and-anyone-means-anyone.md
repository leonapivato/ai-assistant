# 390. Each stored record carries one audience score, set when it is written and changed afterwards only by a person, and anyone means anyone

- Status: Proposed
- Date: 2026-11-27
- Scope: an amending decision on the audience side of
  [ADR-0369](0369-a-record-lands-in-the-domain-of-whom-its-work-is-for-sharing-rules-open-a-domain-and-default-to-private-every-read-is-filtered-to-who-may-see-and-each-person-sees-deletes-and-exports-their-own.md)
  and
  [ADR-0372](0372-a-place-has-a-start-level-that-what-is-said-there-carries-and-a-work-re-runs-once-without-what-is-narrower-than-its-story.md),
  made before milestone 23 is scoped: one audience score for each stored record, and what
  "anyone" means. §11 says whose each point is.
- Authorization: the owner's rulings of 2026-11-26, given in the review of ADR-0365 to ADR-0372,
  quoted in §11. Every other rule here is the coordinator's proposal, marked in §11 as this
  decision's. The coordinator assigned 0390 and ratifies it under the owner's delegation once its
  reviews are green.
- **Contract-surface decision; a decision only.** It changes no Protocol, type, field or code. It
  decides what every stored record carries and who may see it, which bounds the `core` types a
  build makes, so it takes the adversarial and the architecture review. Building it is a breaking
  change under golden rule 5, through what §10 names.
- **Partially supersedes**, as §9 records: ADR-0369 (§2:5, §3:1, §4:1, §5:1 to §5:4, §6:1 to
  §6:3, §7:2 to §7:6, §7:8 to §7:10, §8:1, §9:4, §10:1, §10:4, §14:1 and §14:2, each for a stored
  record); ADR-0372 (§3:2, in the addition alone, §3:5, §3:8, §4:1 and §4:3, each for a stored
  record, §4:5 and §6:9);
  [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md) (§1:2,
  §2:1, §3:13 and §3:14, each for a stored record's score); and
  [ADR-0383](0383-each-record-carries-its-home-and-every-read-a-work-a-producer-or-a-run-makes-is-of-a-store-bound-to-one-sight-which-answers-as-though-it-held-only-what-that-sight-sees.md)
  (§6:1 and §6:2, in the addition alone; §8:3, in its ground).

## Context

Beside its home, ADR-0369 gave a stored record a reach, fixed when it is written as the meet of
what it was made from (ADR-0369 §7:5), and its domain's sharing rules, read as they stand at each
read (§6:1, §6:3, §8:1) through the kinds and accounts it recorded it was made from (§7:6).
ADR-0372 then gave every block and record an audience label, set when said or written (ADR-0372
§3), as a further case of who may see (§4:2). A record so had three answers. Reviewing those
decisions on 2026-11-26, the owner expected one, set at write time, adopted one score per stored
record with live sharing kept for accounts alone, and said that "anyone" means literally anyone.

**Words.** A **stored record** is a record of a store ADR-0383 §3 gives a home, whatever its
kind: memories and episodes, stories with their notes and summaries, conversations and messages,
plan effects and observations, scheduled tasks and approval requests, the person model, and held
notifications. A record ADR-0383 §3 gives no home is not one, nor is an account's content, which a
work reads through the account (ADR-0369 §10:7).
A record's **home** is ADR-0383's; its **home's people** are those ADR-0369 §7:1 says `OWNER`
denotes for it. A **mark**, **domain**, **sharing rule**, **line**, **reach** and **audience
label** are ADR-0370's, ADR-0369's and ADR-0372's. A bare section reference, such as §4:1, is to
this decision's own clauses.

## Decision

We will give every stored record one audience score, set when it is written and changed afterwards
only by a person, keep live sharing for accounts alone, and read "anyone" as everyone.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation, and until it is built every read,
> write and send runs as it does today, what milestone 22 built included.

> **Normative.** This decision moves nothing of a record's home: where a record lands, and who
> sees, deletes and exports a domain by it, stay as ADR-0369 §2 and §12, ADR-0383 and ADR-0386
> rule them.

### 2. One score on every stored record

> **Normative.** Every stored record carries exactly one **audience score**: a set of people,
> stated as an audience label is (ADR-0372 §3:5), anyone at the widest. It is the record's
> ADR-0372 §3 audience label.

> **Normative.** No stored record carries a reach beside its score. Wherever a clause reads a
> stored record's reach or placement as the people who may see or receive it, it reads the score
> (ADR-0217 §1:2, §2:1; ADR-0369 §6:1, §7:8).

> **Normative.** A score, an audience label or a place's audience naming anyone takes in every
> person, identified or not, whether or not the hub admits them, as ADR-0367 §2:3 has it.

### 3. Set when it is written

> **Normative.** A stored record's score is set when it is written, as ADR-0372 §3:1 to §3:5 set
> its audience label: for a message a person says, the place's start level (§3:1); for a message
> a work sends, its mark with that place's audience (§3:2); for every other record a work writes,
> its mark, the narrowest of what was in front of the work (§3:3, ADR-0370 §4:1); and for a
> producer's record, the meet §3:4 takes.

> **Normative.** A write that changes or folds a stored record, other than an act under §4, gives
> it the meet of the score it had and the score the write's own rule gives.

> **Normative.** A run of upkeep (ADR-0384) scores what it writes as ADR-0372 §3:4 scores a
> producer's record.

> **Normative.** A record brought in outside any work (ADR-0369 §2:2) is scored, when it is
> written, for the people who may then see what it was brought from: for an account, its home's
> people and those the account's sharing rule lets see it whole; for any other source, its home's
> people.

> **Normative.** A stored record that carries no score, as every record written before scores
> could be recorded, is read as scored for its home's people, and never as anyone.

### 4. Only a person changes it

> **Normative.** After a stored record is written, its score changes only by an act of whoever
> holds the data rights over its domain (ADR-0369 §7:7, §12:1 to §12:3), made on a surface or by a
> call a work makes on that person's authority that the check allows (ADR-0367 §3:5), and by a
> model's narrowing as ADR-0372 §3:6 has it.

> **Normative.** The call that only narrows a score is free, and the call that widens one is
> checked, each as ADR-0369 §5:2 and §5:3 have the call that makes a line on a record.

> **Normative.** A person's act may widen a score whatever narrowed it, a narrowing written
> `DERIVED` included. ADR-0217 §3:17's floors and ADR-0199 §3's placing of classes stand whatever
> the score.

> **Normative.** No change to an account's sharing rule, to a place's start level or to any record
> a stored record was written from changes that record's score, save the narrowing §5:5 makes
> when a record it names is narrowed.

A score widened on a record written from another domain's record is that person passing it on
(ADR-0369 §11:1), in the owner's words of 2026-11-21: "By trusting someone with infomration, im
subjecting myself to that risk."

### 5. Who may see a stored record

> **Normative.** For a stored record, ADR-0369 §6:1 reads its score where it reads its reach, its
> two cases through a line, on a kind or an account and on the record itself, do not apply, and no
> line or limit is read for it.

> **Normative.** A stored record has no reduced form: ADR-0369 §4:1's forms for a view and for a
> matter or task, §6:2 and the reduced form of §14:1 and §14:2 do not apply to it.

> **Normative.** For a stored record of another domain, ADR-0369 §10:1 lets a work for a group
> read it where its score takes in each of the group's members; and what anyone may see under
> §10:4 is, of stored records, those scored anyone.

> **Normative.** A read through a bound store (ADR-0383 §6:1) gives back a stored record only where
> each bound sees it, by its home as ADR-0383 §6:2 has it or by its score: a person bound where
> they are inside the score; a no-one bound or an anyone bound
> where the score is anyone; a group bound where the score takes in each of the group's members;
> and a domain bound by its home alone.

> **Normative.** A stored record's score lies inside the score of each stored record it names as a
> member, link, pin, mark, lineage, reply or evidence does (ADR-0383 §8:3), each held by its own
> writes and acts: the write that adds a name gives the naming record the meet of its score and
> the named one's; every write or act that narrows a record, a fold, a change under §3:2 and the
> meet this clause takes included, narrows each record naming it in the same step;
> and an act that widens a record widens it no further than the score of each record it names,
> save as the same act widens those. A named record no longer held bounds nothing.

> **Normative.** Code decides who may see a stored record from its home and its score as it
> stands, and no model decides it or takes part (ADR-0369 §6:3, ADR-0372 §4:6).

> **Normative.** For a stored record, ADR-0372 §4:1 is read through its score, which takes in the
> place's audience when it was said (ADR-0372 §3:1, §3:2) save as a narrowing, §5:5's included,
> has since taken someone out; no reader sees a stored record by having been in that audience
> alone.

### 6. Accounts keep live sharing

> **Normative.** A sharing rule names one account. No sharing rule, and no line on a record, is
> made on conversations, memories, people, matters and tasks or the profile.

> **Normative.** For an account, ADR-0369 §3:2 to §3:8, §4's forms, §6:1's case through a line on
> its account, §6:2, §8 and §10:7 stand as written, the rule read as it stands at each read
> through the account.

### 7. The offer when a person changes sharing

> **Normative.** When a person changes an account's sharing rule or a place's start level, the
> assistant offers them, in the same step, to change the scores of the existing records written
> from that account or said in that place that they may change under §4:1.

> **Normative.** The offer changes nothing until the person accepts it, and each change they accept
> is their own act under §4.

### 8. What is built today

> **Normative.** Each built mechanism the table below names takes the disposition it gives, in
> the build of §10, and none changes before.

| Built | Decided by | Becomes |
| --- | --- | --- |
| `RecordHome` and the sight filter: a record seen where every bound sees its home | ADR-0383, ADR-0386 | Stays as built; the build adds each bound's sight by the score (§5:4), and no store reads another for it |
| `Placement`, `PlacementReach`, `PlacementSetter` on every memory and episode | ADR-0217 §1 | The score: `OWNER` the home's people, `ANYONE` anyone, widened to the sets a label names and put on every stored record |
| `Placement.narrowest_of`, the observer's narrowest placement | ADR-0217 §3:3, ADR-0329 §12:6 | §3:1's meet of scores |
| `guard` and `unguard` on `AssistantEngine` | ADR-0217 §7 | §4's acts on a memory's score, to the home's people and to anyone; `unguard` widens a `DERIVED` score too (§4:3) |
| The posture: `TurnSupply`, its two supplies, `admitted_to_understanding` with `_speakable` | ADR-0199 §1, ADR-0217 §2, ADR-0383 §10:1 | Stays as who perceives a channel; `_speakable` reads the score |
| `owner_records`, `admits_owner_placed`, `SummaryVisibility` | ADR-0307 §6:4, ADR-0304 §4, ADR-0383 §10:3 | Retired once notes and summaries carry a score: one is shown where the pass's audience is inside its score |
| Sharing rules, lines on a record, ADR-0369 §7's reach naming people and §7:6's kinds | ADR-0369 §3, §5, §7 | Not built; retired for stored records |

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0217,
> ADR-0369, ADR-0372 and ADR-0383 and in a dated header note on each, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

Superseded, each for a stored record:

| Clause | Becomes |
| --- | --- |
| ADR-0369 §3:1, six kinds a rule names; §5:1, a line on a record | A rule names an account (§6:1); a person changes a record's score (§4) |
| ADR-0369 §5:2 and §5:3, the calls that make a line on a record | In what the call makes: a narrowed or widened score (§4:2) |
| ADR-0369 §5:4, no widening passes the reach; §7:2 to §7:6, §7:9 and §7:10, the reach, its meet, its setter and the kinds recorded | The score alone (§2, §3); a record with no score is its home's people's, not anyone's (§3:5) |
| ADR-0369 §2:5's *takes its reach by §7:5*; §9:4, dating a derived record by its earliest source | Its score, set when it is written (§3:1) |
| ADR-0369 §6:1, §6:3 and §7:8, the reach and the lines read live; §8:1's live reading | The score as it stands (§5:1, §5:4); live only for an account (§6:2) |
| ADR-0369 §4:1, §6:2, §14:1 and §14:2, reduced forms of stored kinds | None for a stored record (§5:2) |
| ADR-0369 §10:1's and §10:4's reach and lines | The score (§5:3) |
| ADR-0372 §3:5's *nothing widens it*; §3:8's sharing rule and line on a record | Save a person's act (§4:1); a rule on an account alone (§6:1) |
| ADR-0372 §4:3's reach and limits; §6:9's placement | The score (§2:2, §5:1) |
| ADR-0372 §4:1, what was said seen by the place's audience then | Through its score, which takes that audience in unless narrowed since (§5:7) |
| ADR-0372 §4:5's first sentence, anyone as each person admitted | Anyone literally (§2:3); its second sentence stands, read with §5:3 |
| ADR-0217 §1:2's reach and §2:1's placement, for who may receive a stored record | The score (§2:2) |
| ADR-0217 §3:13 and §3:14's *narrows only*, on a `DERIVED` placement | A person widens a score whatever narrowed it, under ADR-0217 §3:17 (§4:3) |
| ADR-0383 §6:1 and §6:2, a record seen where every bound sees its home | In the addition alone: or where each bound sees it by its score (§5:4) |
| ADR-0383 §8:3's ground, that a sight sees every record of a home or none | A record's score lies inside each named record's, so its conclusion holds (§5:5) |
| ADR-0372 §3:2, a work's message its mark with the place's audience | In the meet with each record it names (§5:5) |

Read through and standing: ADR-0369 §1, §2, §3:2 to §3:8 and §8:2 for accounts, §7:1, §7:7, §9:1
to §9:3, §10:2, §10:3, §10:5 to §10:8, §11 to §13; ADR-0372 §2, §3:1, §3:3, §3:4, §3:6, §3:7,
§4:1 save for a stored record, §4:2, §4:4, §4:6, §5 to §7; ADR-0370 §2 to §6, its "reach" in §5:5
and §6:4 read as the score; ADR-0307 §6:4, its "placed for the owner alone" read as scored for
the home's people; ADR-0217 §2:2 to §2:6, §3:3, §3:15 to §3:17.

**The record's list, against the texts.** Each clause the record of the rulings names says what it
takes it to say: §3's rules on the five stored kinds of §3:1's six, §5:4, §7:5, §7:6, §8:1 and
§9:4. Four more had to move for its rule to hold, which it does not name: §7:9's second sentence,
which reads a record with no reach as `ANYONE` and with anyone meaning strangers would open every
record written before scores to them; ADR-0372 §3:5 and §3:8, which let nothing but a standing
change widen a label; ADR-0217 §3:13, under which no person's act could open a record made from a
calendar later shared; and the reduced forms, which a rule on a stored kind alone could open. And
ADR-0383 §6:1, §6:2 and §8:3, written for a sight that sees a home whole, had to admit a score.

### 10. What building it needs

Named so milestone 23 is scoped; none is made here.

- **`core` types:** the score on every record type ADR-0383 §3 gives a home and on every memory,
  as `Placement`'s reach widened under ADR-0217 §1:9 and §1:10 to the sets a label names or as one
  field replacing it; a record with none decoded as its home's people (§3:5); `PlacementSetter`'s
  precedence admitting a widened `DERIVED` (§4:3).
- **Stores:** each writes the score with the record, set at each write site by §3; the bound
  stores' sight (ADR-0383 §6) sees by each bound's home or score, each store reading its own
  records alone (§5:4); and, for §5:5, the engine or the run that narrows or widens a record finds
  the records that name it, in each store by that store's own reads, in the same step.
- **Engine members:** a person's acts to narrow and widen one record's score in their domain, at
  ADR-0369 §5:2's and §5:3's bars, `guard` and `unguard` becoming the owner's two on a memory;
  and, for the offer, a way to find the records written from an account or said in a place, read
  for the offer alone and never for who may see (§7).
- **The wire and the formats:** `PROTOCOL_VERSION`, under ADR-0124 §9:2, and each store's format
  that gains the score.

### 11. Whose each point is

**The owner's, 2026-11-26.** On a record made from the calendar: "This depends on the scores
right. If it only has the calender as one of the context blocks, than it has the same audience as
the calender, but if it has the calender and something more sensitive, it follows the same rules
as the audience score, right?" On a start level: "yes, follows the same audience authority score
idea, where a message has the scores at write-time, you know". Then "Yes, adopt it", to "Adopt one
score per record, with live sharing kept only for accounts?", adopting the proposal put to them
with it: one score per record set when written and changed afterwards only by a person; live
sharing for an account alone; the offer when a person changes sharing; the two costs, that sharing
later does not open what was written earlier and taking it back does not close what was written
while it was shared, unless the person changes those records; and, in the record's write-up of the
ruling, the home as milestone 22 built it (§2:1, §3:1, §4:1, §6, §7, §1:3). On a person's act on one record: "ok" (§4:1). On summaries:
"this can follow the idea of the group changing when someone is adding, and the scores, right?"
(§9, ADR-0369 §9:4). On anyone: "I thought anyone meant literally anyone? how they access it is
different, but it gets treated as if its a stranger, no?" (§2:3).

**This decision's, not an owner ruling:** §1:2; §2:2, that no reach stays beside the score; §3:2
to §3:5, a change or fold, a run, a record brought in, and a record with no score; that §4:1's
person is whoever holds the data rights, and that a model's narrowing under ADR-0372 §3:6 stands
beside a person's act; §4:2's bars; §4:3, that a `DERIVED` narrowing widens; §4:4; §5, that no
line, limit on a stored kind or reduced form is read for a stored record, how each bound sees by
the score, §5:5's rule that a record's score lies inside each named record's, and §5:7's reading
of ADR-0372 §4:1 through the score; that §6:2 keeps ADR-0369
§3 and §8 whole for an account; which changes of sharing bring the offer (§7:1); §8's
dispositions; and every row of §9 beyond the six clauses the record names.

### 12. What this decision leaves to others

- **The decision on groups:** a group as a set and its minimum, making groups, whose a shared
  place is, and what someone who leaves keeps (ADR-0369 §9:1 to §9:3, §6:1's case through a group,
  ADR-0372 §4:2's *and still are*), none of which this decision reads.
- **The authority side, a later amending decision:** signals and messages, the reply, a task's fetch, and pasted
  and forwarded text.
- **The access log:** whether a read through a score is entered (ADR-0369 §13, ADR-0372 §11), and
  a log per thing and optional, ruled by the owner on 2026-11-26.
- **An account's rule allowed with approval** (ADR-0369 §3:5), ruled by the owner on 2026-11-26.
- **The next prompt review:** how the offer is worded, and how a model is told a score.
- **The build:** surfaces for §4's acts and §7's offer.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

## Consequences

- Who may see a stored record is its home and one score fixed when written; sharing an account
  later opens nothing written earlier, and taking it back closes nothing, unless the person
  changes those records, which they are offered.
- Every record today stays its home's people's until a person widens it.
- From milestone 23 a work with an unidentified sender reads what is scored anyone, where it reads
  nothing today; ADR-0372 §8's courier is shown what was said in a chat set to anyone.
- No one can be shown a matter's title alone: a stored record is seen whole or not at all.
- **Revisit** if people need a stored record seen in part, or if widening a `DERIVED` score proves
  a way to disclose what a class should keep back.

## Alternatives considered

- **Keep live sharing rules on stored kinds beside the score.** Set aside by the owner's ruling.
- **Keep `DERIVED` unliftable for ADR-0204 §2's own ground.** Not taken: the ruling has a person
  change any score, and ADR-0217 §3:17 and ADR-0199 §3 keep the classes back whatever it is.
- **Withhold, at read, a record that names one its reader may not see.** Not taken: each store
  would have to read the others' scores (ADR-0289 §1:3), and deleted evidence would hide the
  memory it supported. **Show it with the name left out:** composes a value and then removes part
  of it, which ADR-0217 §2:4 bars.
- **A second score for a reduced form.** Not taken: it is two scores on one record.
- **A record with no score read as anyone,** as ADR-0369 §7:9 has it. Not taken: anyone now takes
  in strangers.
