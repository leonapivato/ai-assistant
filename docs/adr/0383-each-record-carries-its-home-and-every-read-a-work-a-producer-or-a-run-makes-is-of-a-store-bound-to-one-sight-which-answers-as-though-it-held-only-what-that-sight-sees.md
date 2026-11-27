# 383. Each record carries its home, and every read a work, a producer or a run makes is of a store bound to one sight, which answers as though it held only what that sight sees

- Status: Partially superseded by ADR-0385 (§6:10 and §9:2, each in the addition alone: a sight is also made by a `core` constructor for an owner's own act, in the engine's members; §7:10, in its reach: a store bound to an owner's act's sight withholds from the build that first binds it) and ADR-0386 (§12:2, in its reach: it does not reach the clauses ADR-0386 supersedes in part, which hold as ADR-0386 leaves them) and ADR-0387 (§7:7, §7:9, §8:2 and §9:1, each in the addition alone: a work's own turn is written into the places its inputs came through outside the filter) and ADR-0388 (§4:8 and §6:4, each in the addition alone: a withholding memory store refuses a name a write adds that resolves to no record it holds; a work whose facts were not recorded has a work's sight of an anyone bound and its activation) and ADR-0389 (§3:3, in its reach, and §7:2 and §9:3, each in the addition alone: a conversation store bound to the owner's sight holds "my devices" and the device rows of each conversation it holds; §3's table, its conversations row, in the addition alone: a conversation's deletion in the change stream carries its conversation's home) and ADR-0390 (§6:1 and §6:2, in the addition alone: a bound also sees a stored record by its audience score; §8:3, in its ground: a record that names one a reader does not see is withheld from them)
- Date: 2026-11-26
- Scope: decision D1 of milestone 22, "Every record has a home" (acceptance
  [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)). For a hub that admits the
  owner alone, it decides the value that names a record's home (§2); which stores carry it (§3);
  how a write sets it and what a write refuses (§4); what a record from before the upgrade and a
  record with no home mean (§5); the sight a read is bounded by, and how a work's facts make it
  (§6); where the filter sits (§7); what "absent" means wherever a store answers (§8); how a read
  that goes round the filter is caught (§9); what it does to today's audience machinery (§10); and
  what the first deploy counts (§11). §12 records what it does to earlier decisions, §13 the `core`
  changes it would need, §14 what it leaves to others, and §15 what it settled.
- Authorization: the owner's words, verbatim. On 2026-11-23, "Yes, scope milestone 1", to "Do you
  accept the five-milestone order for the build plan?"; the order is in #3709's first paragraph.
  On 2026-11-25, "Yes, draft it", to "Shall I draft the scope of the next milestone for you to
  agree". On 2026-11-26, "Yes, agreed", to "Do you agree this scope: "Yes, agreed" or "Change
  something"?", the scope being what #3709 records with six picks of the coordinator's, which that
  answer accepted and nothing more; among them, that every record from before the upgrade becomes
  the owner's, that an unidentified sender's work reads nothing, the earlier messages of its own
  chat included, and that there are two deploys with real use between them. The owner has ruled
  nothing about the value, the stores or the seam: every rule below is this decision's (§15). The
  coordinator assigned 0383 and ratifies it, under the owner's delegation, once its reviews are
  green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides `core` types and members of seven Protocols (§13), so it takes the
  adversarial and the architecture review. Building it is a breaking change under golden rule 5.
  It supersedes nothing (§12).
- Partially superseded: 2026-11-26 by [ADR-0385](0385-the-owners-acts-read-through-a-sight-of-their-own-seeing-and-deleting-keep-their-members-and-one-new-member-exports-one-named-domain-whole.md) — §6:10, in the addition alone: a sight is also made by the `core` constructor for an owner's own act, from the domain the act names or none rather than from recorded facts (ADR-0385 §3:3); §9:2, in the addition alone: the engine's members make that sight through that constructor, and the named test admits them; §7:10, in its reach: its "the build that first binds the stores counts" does not reach a store bound to an owner's act's sight, which withholds from the build that first binds it (ADR-0385 §3:5), and its first half binds such a store as written. Every other clause stands. These replacements take effect on ratification of ADR-0385. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Amended: 2026-11-26 (§3's first row, §5:4 and §13 — the place named for the memory store's
  home). In §3's first row, §5:4 and §13, the required home is a field of `EpisodicMemory` and
  `Memory`, the two kinds the memory store holds, and not of `RecordEnvelope`: `SemanticMemory`
  sits on the same envelope, and no store holds one (ADR-0328 §2:4). A minted record carries no
  home. Naming the envelope rested on its holding only stored records, which the tree at the
  decision's date did not bear out: a stale phrase of its own text, corrected as an appended note
  with no `Status` edit (ADR-0070 §1; ADR-0082 §1 and its 2026-07-31 note). It changes nothing
  decided: every record the memory store holds carries a required home (§3:1, §5:4). Applied by
  the lane that builds the memory store's home.
- Partially superseded: 2026-11-26 by [ADR-0386](0386-a-records-home-joins-the-fields-the-reads-and-the-minting-members-earlier-decisions-closed.md) — §12:2, in its reach: it does not reach the clauses ADR-0386 supersedes in part (ADR-0289 §2:1, §3:1, §3:10 and §3:14; ADR-0215 §7:1; ADR-0074 §1 and §9; ADR-0293 §5:2; ADR-0306 §6:1), each of which holds as ADR-0386 leaves it. §12:1 stays true of this decision: the supersession is ADR-0386's (ADR-0386 §7). Every other clause stands. These replacements take effect on ratification of ADR-0386. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-11-26 by [ADR-0387](0387-a-works-own-turn-is-written-into-the-places-its-inputs-came-through-outside-the-filter-and-nothing-of-those-places-reaches-the-work-by-it.md) — §7:7, in the addition alone: whether one of a work's own places still stands is not a read of its bound store (ADR-0387 §4:2); §7:9, in the addition alone: each place a work's input came through reaches it with that input, named by it, and the engine writes the work's turn there outside the filter (ADR-0387 §3:1, §4:1); §8:2, in the addition alone: those writes and that answer are also outside it; §9:1, in the addition alone: the holders that make them may hold the conversation store unbound, and the named test admits them. Every other clause stands. These replacements take effect on ratification of ADR-0387. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-11-26 by [ADR-0388](0388-before-the-stores-withhold-a-name-a-write-adds-must-resolve-a-limit-counts-what-the-store-holds-and-a-story-start-the-pin-pass-the-upcoming-event-producer-and-a-work-with-no-facts-each-read-by-a-sight.md) — §4:8, in the addition alone: a memory store bound to a sight in the withholding mode also refuses a write adding a name that resolves to no record it holds once the write is made, a withheld name and a name never written alike, with `UnresolvedEvidenceError`, save the takeover lineage a work's capture writes on its own episode (ADR-0388 §2). §6:4, in the addition alone: a work whose facts were not recorded has a work's sight of an anyone bound alone and its activation, so its own records are its own (ADR-0388 §5). Every other clause stands. These replacements take effect on ratification of ADR-0388. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-11-26 by [ADR-0389](0389-a-store-bound-to-the-owners-sight-holds-the-devices-of-what-it-holds-so-a-devices-listing-and-the-chats-changes-read-through-it-as-today.md) — §3:3, in its reach: it does not reach a conversation store bound to a sight `Sight.of_owners_act` made, which holds "my devices" and, for each conversation it holds, that conversation's devices and the sets the change stream recorded for it (ADR-0389 §2:1, §2:2); §7:2 and §9:3, each in the addition alone: what such a store holds, and the store its answers are compared with, include those device rows; §3's table, its conversations row, in the addition alone: a conversation's deletion in the change stream also carries a home, its conversation's, in the store's file, and every bound store gives it back where its sight sees that home, whether or not the conversation's row still stands (ADR-0389 §3). Every other clause stands, §3:3 for every other sight included. These replacements take effect on ratification of ADR-0389. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-11-27 by [ADR-0390](0390-each-stored-record-carries-one-audience-score-set-when-it-is-written-and-changed-afterwards-only-by-a-person-and-anyone-means-anyone.md) — §6:1 and §6:2, in the addition alone: a read gives back a stored record where each bound sees it by its home or by its audience score, a person bound where they are inside the score, a no-one or anyone bound where it is anyone, a group bound where it takes in each member, and a domain bound by its home alone (ADR-0390 §5:4). §8:3, in its ground: once a sight sees part of a home by a score, a stored record that names another is given back only to a reader who sees every record it names, so no record a reader is shown names a withheld one (ADR-0390 §5:5). Every other clause stands. These replacements take effect on ratification of ADR-0390. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

[ADR-0369](0369-a-record-lands-in-the-domain-of-whom-its-work-is-for-sharing-rules-open-a-domain-and-default-to-private-every-read-is-filtered-to-who-may-see-and-each-person-sees-deletes-and-exports-their-own.md)
lands every record in a domain (§2:1, §2:2), lets a person see their own domain and the owner also
the hub's shared things (§6:1), bounds what a work reads by whom it is for, by each of its senders
and by a person whose authority it carries in advance (§10:1 to §10:3), and has code apply that in
"one filter, where records leave the stores" (§10:5), under which a withheld record "is absent:
nothing marks, counts or names it, and nothing is fetched in its place" (§10:6). Its §16 names the
contract changes and leaves one choice open: "each store a work reads takes the people whose sight
bounds the read, or every read passes one seam that applies §10; which, is the build's."
[ADR-0384](0384-upkeep-of-a-persons-records-runs-for-that-person-a-run-tends-one-domain-reads-what-its-person-may-see-through-the-filter-and-writes-only-there.md)
rules whose sight bounds the three upkeep jobs and leaves the value and the seam here (§12).

**The code today** (`origin/main` at `3638aac0d`). No stored record says whose it is. A memory
record carries the people it is about (`MemoryBase.about_person`, `Memory.subjects`,
`Memory.involved`) and the holders of its supports (`MemorySupport.holder`); an episode carries
its work's facts (`EpisodeProcessingRecord.facts`, a `WorkFacts`); a scheduled task and an
approval request carry `person`, whom each is for; the person model is keyed by `person_id`.
Stories, conversations and their messages, effects, observations and notifications name no
person. No store read takes a person or an audience: `MemoryStore.search`'s `person` and
`as_subject` select by whom a memory is about. The stages are built once by the composition root,
each holding the stores it reads. Each pass carries a posture, `TurnSupply` in
`orchestration/disclosure.py`, and an `owner_records` flag; every pass the engine starts mints
`BoundedAudienceSupply` and sets `owner_records=True` (`Engine._phases_turn`, `Engine._line_turn`,
`Engine._phases_event`, `PhasePath.begin_task`, `PhasePath.begin_approval`), so
`admitted_to_understanding` withholds nothing in production, and its `_speakable` is the only
read of a record's `PlacementReach`.

**Words.** A **domain**, the **hub's shared things**, **the filter** and a **producer** are
ADR-0369's; a **work**, its **senders**, **identified** and **unidentified** are ADR-0368's; a
**run** and **tends** are ADR-0384's. A record's **home** is the domain it landed in. A **sight**
is the value that says what a read may give back (§6). A **bound store** is a store bound to one
sight (§7). A **reader** is whoever reads through a bound store: a work's stage, a producer for a
work that has ended, or an ADR-0384 run. A bare section reference, such as §7:2, is to this
decision's own clauses.

## Decision

We will put on every record a store keeps for a domain its home, as a value naming a person, a
group or the hub's shared things; write the owner's home into every record from before the
upgrade; make each reader's sight from the facts that bound it; and have each store answer a
reader only through a binding to that sight, under which the store answers every member as though
it held only the records the sight sees.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules a hub that admits the owner alone (ADR-0369 §1:4): the
> owner's domain and the hub's shared things are the only homes, and no sharing rule or line on a
> record exists. A group's domain, another person's, and what lines open, are milestone 5's.

> **Normative.** Until the build lanes it scopes have merged, nothing in this decision changes
> what the running hub stores, reads, shows or allows.

### 2. The value that names a home

> **Normative.** A home is one value of a new `core/types.py` model beside `WorkFor`: a kind,
> one of a closed enumeration added to and never renamed, holding **person**, **group** and
> **shared**; and an identifier, a person's or a group's identity id for the first two and none
> for shared.

> **Normative.** A record stores its home as both the kind and the identifier, so that naming
> another person or a group later changes no stored shape.

> **Normative.** In this milestone every writer refuses a home other than the owner's domain
> (person, `OWNER_PERSON_ID`) or the hub's shared things, a group's included, through one `core`
> function that names the homes a write may carry, and no other place decides it.

The type expresses a group and any person, as `WorkFor` does, so milestone 5 changes the one
function and no stored record. A home is not `WorkFor`: a work for no one lands in the shared
things (ADR-0369 §2:1), and §5:1 gives a home to records whose work was for no one.

### 3. Which stores carry it

Every store the composition root opens, and the device store the service opens:

| Store (file) | Its home in this milestone |
| --- | --- |
| Memory (`memory.db`): episodes, memories | **Carries one**, on `RecordEnvelope`. `about_person`, `subjects` and `involved` are the people it is about; `MemorySupport.holder` is a holder; an episode's `facts.for_whom` is whom its work was for. None is its home |
| Stories (`stories.db`): stories, notes, summaries, log | **Carries one**, on the story. A note, a summary, a version and a log line are its story's and take its home |
| Conversations (`conversations.db`): conversations, messages | **Carries one**, on the conversation and on each message. Device rows carry none: devices are not records of a domain, and `DeviceChecks` reads them as today |
| Plans (`plans.db`): effects, observations | **Carries one**, on each `ActivationEffect` and `ObservationRecord` |
| Plans: scheduled tasks, approval requests | **Already records it**: `ScheduledTask.person` and `ApprovalRequest.person`, whom each is for, name a person whose domain is its home. `author_person` is whose authority it carries, and `ApprovalTap.person` who tapped; neither is its home |
| Plans: stop records | **None**: an activation's id alone, read to stop and settle works |
| Person model (`person_model.db`) | **Already records it**: `person_id` names whose profile, pins, marks and suggestions they are, and that person's domain is their home |
| Notifications (`notifications.db`) | **Carries one**, on `HeldNotification`, for ADR-0384 §3:4 and §7:1 |
| Identities, permission lines, thing records | **None** (below) |
| Audit trail, source grants, source-read trail, traces, outbox, Telegram intake, connections, keyring, bookings, devices; the diagnostic record | **None** (below) |

> **Normative.** The stores the table marks as carrying a home carry it on every record they hold,
> in the place the table names, and the stores it marks as already recording one read that field
> as the record's home and gain no second field for it.

> **Normative.** A note, summary, version or log line of a story, and every other part a table row
> names as taking its parent's home, has its parent's home, and no write puts into a parent a part
> of another home.

> **Normative.** A record of a store or kind the table marks as carrying none is given back,
> counted and named by no member of a bound store (§7); a write's own checks still read it (§7:11).

The stores that carry none are read only by code that decides something, whose answer is the
decision and never the record: the check and the Connections section's filter read lines and
thing records (ADR-0367 §4:1, ADR-0381 §6), admission reads links (ADR-0366 §4:1), authorizing
reads back its own trail entry, a driver reads a source grant, and the engine stops a work by its
stop record. The rest are trails of what the hub did, operator stores, or a provider's stand-in,
and no work's stage, producer or run reads them. None hands a record to a reader, so none is a read
the filter must bound, and §3:3 keeps a reader that reaches one through a bound store from seeing
any of it. Whose each of their records is, for an export (ADR-0369 §12) or an access log (§13), is
left (§14). `IdentityStore`'s links already name their person (ADR-0381 §2:3), and a thing
record's `person` is whose the thing is, which §4:3 uses through the one rule ADR-0368 §3:3 is read
by.

### 4. Setting a home on a write

> **Normative.** A record a work writes takes the home that whom the work is for gives, by
> ADR-0368 §2:1 and ADR-0369 §2:1, as the work's facts stand when it writes: a person's domain for a
> work for a person, and the hub's shared things for a work for no one. A work for a group writes
> nothing in this milestone (§2:3).

> **Normative.** A record a producer writes from a work's episode after the work has ended takes
> that episode's home (ADR-0369 §2:2), never one made again from the episode's facts.

> **Normative.** A record brought in outside any work, a message a device or a line takes in, a
> conversation a device starts, an event a source pushes and a notification a producer makes from
> a source, takes the home of whoever its connection, account or source belongs to (ADR-0369 §2:2),
> read by the one rule the code reads ADR-0368 §3:3's "whoever the connection it came by belongs
> to" by: in this milestone, the owner's.

> **Normative.** An unidentified sender's work writes into the domain of whom it is for, which
> ADR-0368 §3:3 makes whoever its connection belongs to: in this milestone, the owner's.

> **Normative.** A record an ADR-0384 run writes takes the home of the domain the run tends
> (ADR-0384 §4:1). A record an owner's own act writes outside any work takes the owner's domain,
> and an act that changes a record leaves its home as it was.

> **Normative.** No write changes a record's home, and no model sets, proposes or changes one.

> **Normative.** The writer refuses, with nothing written: a write that changes a record of a home
> other than its own (ADR-0369 §2:6); a placed proposal naming a memory of another home (§2:7); a
> record that names another record of another home, as a member, a link, a pin, a mark, a reply, a
> lineage, an evidence pointer or a placement target; and a home §2:3 does not allow. The writer is
> the store where both homes are in its own file, and otherwise the code that writes the name.

> **Normative.** Where the record a refused write names is one the writer's sight does not see,
> the refusal is the one the writer would get had that record never existed.

§4:7's third item is ADR-0369 §2:6 as ADR-0384 §5 reads it, "no link joins two domains' records",
and it is what lets §8 hold record by record: a record a reader sees names only records of its own
home, which the reader then sees too.

### 5. Records from before the upgrade, and a record with no home

> **Normative.** Each store that carries a home writes the owner's domain into every record it
> holds, in the upgrade that adds the home (ADR-0326 §4:1), whatever the record's facts say of whom
> its work was for, so every record from before the upgrade is the owner's. Nothing asks the owner
> anything.

> **Normative.** A store whose home is a field it already records writes nothing for this, and
> reads that field's person as the record's home.

> **Normative.** Once a store's upgrade has run, a stored record with no home, or with one the store
> cannot read, is the home of no one: no bound store gives it back, it is never read as the owner's
> or as anyone else's, and it is withheld from every sight.

> **Normative.** A home is a required field of each `core` model §3 puts it on, so no write can
> leave it out.

§5:3 holds ADR-0380 §2:1's ground for an absent value: absence refuses, and never reads as wider
than the owner's own domain. What the owner's own acts show of such a record is left (§14).

### 6. The sight

> **Normative.** A sight is one value of a new `core/types.py` model: a non-empty set of bounds,
> and, where it is a work's, that work's activation. A read through it gives back a record only
> where every bound sees the record's home, or, for a work's sight, where the record is that
> work's own (§7:4).

> **Normative.** A bound is one of: a **person**, who sees their own domain and, for the owner,
> the hub's shared things (ADR-0369 §6:1); **no one**, which sees the hub's shared things
> (ADR-0369 §10:1); **anyone**, which sees what anyone may see (ADR-0369 §10:4), nothing while no
> line can open a record; a **group**, which sees nothing in this milestone (ADR-0369 §1:5); and
> **one domain**, which sees that domain alone.

> **Normative.** A sight with no bound is refused where it is made. No value sees every record.

> **Normative.** A work's sight has a bound for whom it is for (ADR-0369 §10:1): the person, the
> group, or no one; a person bound for each identified sender, and an anyone bound where any sender
> is unidentified (§10:2); and a person bound for the person whose authority it carries in advance
> (§10:3). The senders are every sender of every input it holds, as its inputs record them, and
> never only those whose authority it carries.

> **Normative.** A work with no sender, an approval's outcome's, a signal's, or a task's whose
> author is the assistant, has the bound for whom it is for, and the person bound of an author in
> advance where it carries one.

> **Normative.** A work's sight is made when its facts are first recorded and made again each time
> they are recorded again (ADR-0368 §2:4), as the meet of the sight it had and the one its facts now
> give, so it never widens within a work.

> **Normative.** A producer reads for an ended work by the sight §6:4 makes from the facts and
> senders its episode records, with no activation, so nothing is its own. Where the episode records
> no facts, its sight is an anyone bound alone, which sees nothing.

> **Normative.** An ADR-0384 run reads by a one-domain bound for the domain it tends and a person
> bound for that domain's person, the owner for the shared things (ADR-0384 §3:1, §3:2); a tidy-up a
> work asks for, by that work's sight with a one-domain bound for the story's domain (ADR-0384
> §6:1).

> **Normative.** No level, bar or sureness enters a sight. A person bound sees the same records at
> every level its person is identified at.

> **Normative.** The sight is made by code from recorded facts alone, by `core` constructors for a
> work, for a producer and for a run, and no model makes, chooses or changes it (ADR-0369 §10:8).

Three cases, as the build would meet them:

| Work | Its facts | Its bounds | It reads |
| --- | --- | --- | --- |
| The owner's message in the hub chat, at normal or lowered to weak | for the owner; sender the owner, identified | person owner | the owner's domain and the shared things, as today |
| A message from an unidentified sender, or by a link lowered to none | for the owner, whose connection it came by (ADR-0368 §3:3); one sender, unidentified | person owner, anyone | nothing but its own records (§7:4), its chat's earlier messages withheld |
| A task's occurrence, set by the owner | for the owner (`ScheduledTask.person`); no sender; the owner's authority in advance | person owner | the owner's domain and the shared things |

A forward an unidentified sender sent carries no authority (ADR-0351 §6:2), so §6:4 reads its
senders from its inputs and not from `WorkAuthority`: by authority alone it would read the owner's
whole domain.

### 7. Where the filter sits

> **Normative.** The filter sits in each store that carries a home. `MemoryStore`, `StoryStore`,
> `ConversationStore`, `PlanStore`, `PersonModelStore`, `NotificationStore` and `MemoryWriter` each
> gain one member that takes a sight and returns the same Protocol bound to it, and no read member
> of any of them gains an argument.

> **Normative.** Save a write's own checks (§7:11), a bound store answers every member as the same
> store would answer it if it held only the records its sight sees: the same records in the same
> order, the same totals and counts, the same pages and whether more follow, and, for a named
> record it does not hold, the same outcome, returned or raised, as for a record never written. It
> applies the sight before it ranks, orders, limits, pages or counts.

> **Normative.** Each store decides what its sight sees by the one `core` predicate the sight
> type carries, and by nothing else; a store may express it in its own query only where its
> answers equal the predicate's on every record.

> **Normative.** A bound store also holds the records it records as made by its sight's
> activation: that activation's episode, its effects, and the approval requests it asked.

> **Normative.** A write through a bound store carries its own home on its record (§4), and a
> write that changes a record the bound store does not give back is refused as a write to one the
> store does not hold.

> **Normative.** A bound `MemoryWriter` makes every read it makes for a write, its conflict search
> and its fetch of a placed proposal's memories included, through the memory store bound to the same
> sight.

> **Normative.** Every read a work's stages make, recall's two runs, the windows its channel's
> reader reads for it, every look-up,
> the matters list, the person block, authorizing's reads of the plan and story stores and, once
> built, the People section included; every read a producer makes for an ended work; and every read
> an ADR-0384 run makes, is a read of a bound store, under the sight §6 gives that reader.

> **Normative.** A caller that is not one of §7:7's readers binds a store to the sight its own
> decision gives it. The owner's own acts are D3's; and the jobs ADR-0384 §2's table leaves
> unchanged, a sensor's finding of what is due, the engine's start and `DeviceChecks` read as they
> do today.

> **Normative.** A work's own inputs, its trigger's and each joined input's, reach it as its inputs
> and not through the filter. Every other record, its chat's earlier messages included, reaches it
> only through its bound store, and a channel's reader reads a work's window only once that work's
> sight is made.

> **Normative.** Whether a bound store withholds or only counts is a value its construction fixes,
> set by the composition root and read from no `Settings` field and no running act; the build that
> first binds the stores counts (§11), and a later build switches it to withhold.

> **Normative.** A bound store decides a write's own checks over every record the store holds, as
> the unbound store does: whether a stop record stands for its activation (ADR-0306 §6:2), whether
> a record already has its identifier (ADR-0046), and whether a revision is the one held. A new
> record's identifier is one code minted for it, never one taken from a model's output or an
> input's text, so no reader can steer a check onto a record it does not see.

> **Normative.** The observer's finding of what is due reads episodes and observation records
> unbound, by occurrence, state, home and recorded facts and senders alone (ADR-0329 §16:2), and
> hands a run nothing of them but which episode is due and its observation record's state and
> revision.

> **Normative.** In a build whose bound stores withhold, the finding of what is due hands no run an
> episode whose home the sight §6:7 makes for it does not see. It sets the episode aside as stuck
> under a code-owned reason of its own (ADR-0329 §16:5), keeping every attempt, model call, finding
> and outcome its observation record holds, and nothing reads them for a run. In a build whose bound
> stores count, such an episode is processed as today, and §11's event counts what its run's reads
> would have withheld.

The choice ADR-0369 §16 left is taken this way for three reasons. **Absence holds by
construction.** A store applies the sight before it limits or counts, so a page of ten is the ten
the reader may see and a total counts only those; a seam above the store would see only a store's
answers, and could only cut them short, leave totals counting what it withheld, or fetch again in
the withheld record's place, each of which §10:6 forbids. **No read site and no earlier clause
moves.** No read member gains an argument, so the stages call what they call now on a store they
are handed per read, and every earlier clause fixing a member's arguments, or what a store returns,
holds of a bound store over the records it holds (§12:2), ADR-0275 §10:2's rule that `episodes` has
"the same names, arguments and return types at both seams" among them. **One rule.** §7:3 puts the
predicate in `core` and §9:3 proves each store applies it alike.

### 8. Withheld means absent, wherever a store answers

> **Normative.** No total, count, page size, "more follows" hint, cursor's next page or flag a
> bound store gives back counts or reflects a record it does not hold, and `ChannelEpisodePage`'s
> `total` among them.

> **Normative.** Save §7:11's checks, a look-up, fetch or write that names a record its reader
> does not see gives the reader exactly what naming a record never written gives: a `get` its
> `None`, a `get_many` the id left out, a store error the same error, a tool result the same
> result. ADR-0282 §2:8's "an id with no record" is that outcome.

> **Normative.** No record a reader sees names a record of another home, by §4:7, and a sight
> sees every record of a home or none of them, so no member, link, pin, mark, lineage, reply or
> evidence a reader is shown names a withheld record, and no view marks one forgotten, missing or
> withheld. What a work read before a join narrowed its sight (§6:6) stays in it (§14).

> **Normative.** A label, a referent, a count of items or an order a rendering gives a reader is
> made from what the reader's bound stores gave back, never from what an unbound store holds.

> **Normative.** A store-wide figure that counts writes rather than giving back records,
> `StoryStore.position` and `PlanStore.observer_calls_since` among them, answers alike bound or
> not, and no stage shows it to a model or a surface, or reads it as a number of records.

§8:1 to §8:5 are what ADR-0369 §10:6 asks of the places a store can leak a withheld record's
existence: a total, a page hint, a label, a "not found" that differs from "withheld", a name
carried by a visible record, and a global figure. What a model is told when it asks for something
out of view stays the next prompt review's (ADR-0369 §10).

### 9. Catching a read that goes round the filter

> **Normative.** No class or function under `orchestration/`, save the holder that binds stores
> for a pass and the holders §7:8, §7:12 and §7:13 name, takes or holds one of the six store
> Protocols of §7:1 or `MemoryWriter` unbound; a stage holds a holder that gives a store only for a
> sight. The build ships a named test that fails where any other does.

> **Normative.** No code makes a sight save through §6's `core` constructors, and no stage makes
> one at all: a stage reads the sight its pass, its producer's run or its upkeep run carries. The
> build ships a named test that fails where a module under `orchestration/` constructs a sight
> outside the places that hold one by §6:4 to §6:8.

> **Normative.** Each conformance suite of §7:1's Protocols gains one shared obligation: for every
> read member, the answer of the store bound to a sight equals the answer of the same store holding
> only the records that sight sees, totals, pages and "not found" included. The canonical fakes
> pass it, and a store that leaks fails the gate.

### 10. Today's audience machinery

> **Normative.** The posture stands untouched: `TurnSupply`, `BoundedAudienceSupply`,
> `UnboundedAudienceSupply`, `admitted_to_understanding` with `_speakable`, `admits_owner_placed`,
> `SuppliedRecords.withheld` and the placement each episode is stamped with. It is ADR-0199 §1's
> and ADR-0217 §2's rule for who perceives a channel, the place half milestone 4 builds on, and it
> applies, as a conjunct, to what a bound store gave back.

> **Normative.** The filter reads no posture, no `owner_records` and, in this milestone, no
> `PlacementReach`: ADR-0369 §7:8 reads a reach as a condition of §6:1's cases through a line or
> a group, and none can hold.

> **Normative.** `owner_records` answers only ADR-0307 §6:4's question, whether the pass's audience
> may be shown what is placed for its record's own domain (ADR-0369 §7:1), and never whose records a
> pass may read, which the sight alone decides. At each of the five passes that set it to `True` it
> is made from the pass's posture by `admits_owner_placed`, from the build that switches the filter
> on.

> **Normative.** Where `owner_records` defaults to `False` today, the understanding stage's
> projected episodes, the matters list's entry and the two upkeep jobs' projections, it stays as it
> is (ADR-0312 §4:3).

> **Normative.** `DeviceChecks`, the per-device scoping of conversations (ADR-0298 §5), stands as
> it is, and a device's reads of a conversation pass both it and, where a reader is a work, the
> filter.

> **Normative.** `persons_work`, `_ADMITTED` and `MemoryStore.search`'s `person` and `as_subject`
> stand: the first two say whose a work is and whom the hub admits, the last selects by whom a
> memory is about (ADR-0369 §2:4), and none is a sight or a home.

The filter replaces nothing that filters today, since nothing reads whose a record is. It ends the
reading #3709 gives the five literals, "give back the owner's records without asking whose sight
bounds the read", by making the flag the posture's. On today's hub that changes nothing a pass is
shown, since every pass's posture is bounded.

### 11. The first deploy's count

> **Normative.** In a build whose bound stores count, every read through a bound store answers as
> the unbound store does, and writes one log event: the store, the member, how many records it gave
> back, how many the sight would have withheld, by reason, and the reader's kind and bounds as codes.

> **Normative.** The reasons are codes: another home, no home (§5:3), and a bound that sees nothing.
> The reader's kind is work, producer or run, and its bounds are their kinds, with whether a person
> bound is the owner.

> **Normative.** The event carries no record's text, no person's words and no identifier of a record,
> an activation's, an episode's, a story's and a conversation's included, and goes to the hub's log
> alone: to no store, no trace, no diagnostic record, no stage and no surface.

> **Normative.** The writes and refusals of §4 and §5 take effect in that build; only what reads
> give back waits for the switch.

> **Normative.** An operator's count in the hub's log is not ADR-0369 §10:6's: that clause bounds
> what reaches a reader, a model and a surface, and the log reaches none of them.

The evidence #3709 asks for between the two deploys is that no event of a work whose bounds are the
owner's alone counts anything withheld. Whether a later build keeps the event once a second person
can read the hub's log is milestone 5's.

### 12. Relationship to earlier decisions

> **Normative.** This decision supersedes nothing.

> **Normative.** Every earlier clause on what a store holds, returns, counts, pages, filters by or
> omits, or on the arguments of its members, holds of a bound store as written, read over the
> records that bound store holds (§7:2); an unbound store meets it exactly as it does today.

| Clause | How it stands |
| --- | --- |
| ADR-0369 §16's open choice | Taken: each store, behind one binding member (§7) |
| ADR-0369 §2:1, §2:2, §2:6 to §2:8, §6:1, §7:1, §7:8, §10:1 to §10:6, §10:8 | Built by §4 to §9 for one person; no record |
| ADR-0384 §3, §4, §5, §6, §7:1 | Its sights and refusals are §6:8 and §4:5 to §4:7; no record |
| ADR-0275 §10:2, §10:3; ADR-0114 §1:5; ADR-0281 §3:2; ADR-0283 §3:1, §3:5, §4:2, §8:1; ADR-0284 §6:1; ADR-0286 §7:2, §12:1; ADR-0289 §3:14; ADR-0306 §6:5; ADR-0342 §3:1, §4:1; ADR-0347 §2:4 | Read through by §12:2: no member gains an argument, and each holds of a bound store over its records. The owner's digest and deletion (ADR-0283 §4:2, §8:1) and closing open episodes (ADR-0286 §7:2) are not §7:7's readers |
| ADR-0276 §4:1, §4:3; ADR-0282 §2:4 | Read through: the selector and `MemoryStore` gain nothing for the selector; the windows read a bound store |
| ADR-0217 §2:1 to §2:5; ADR-0199 §1; ADR-0203 §2:1; ADR-0204; ADR-0276 §4:9; ADR-0282 §2:8 | Stand (§10:1): the posture's predicate applies after the filter, and no subtraction moves into a store |
| ADR-0289 §1:3, §4:5; ADR-0306 §6:3 | Stand: each store decides from its own records' homes (§3), and §8:3 leaves no withheld member to mark forgotten |
| ADR-0307 §6:4; ADR-0312 §4:3 | Stand: `owner_records` is their posture flag (§10:3, §10:4) |
| ADR-0381 §3:1, §5:1, §6:4 | Read through: the home is no field "for this", and no thing record is read for it (§4:3) |
| ADR-0326 §4:1, §4:2, §4:7 | Bind each upgrade §13 names; no label advances to refuse an older file |
| ADR-0380 §2:1 | Its ground held by §5:3 |

### 13. The `core` changes building it would need

Named so the build is scoped, and made by none of this decision. Golden rule 5 makes each breaking.

- **`core/types.py`:** the home, its kind enumeration and §2:3's function (§2); the sight, its
  bounds and their kind enumeration, its predicate and its constructors for a work, a producer and
  a run (§6). A required home field on `RecordEnvelope`, `StoryHeader`, `Conversation`,
  `TranscriptMessage` and `NewMessage`, `ActivationEffect`, `ObservationRecord` and
  `HeldNotification` (§3, §5:4).
- **`core/protocols.py`:** one binding member on each of `MemoryStore`, `StoryStore`,
  `ConversationStore`, `PlanStore`, `PersonModelStore`, `NotificationStore` and `MemoryWriter`
  (§7:1), and the obligations of §4:7, §7:2, §7:4 and §7:11 on their writes and reads. No new Protocol
  is owed, so no triad: each changed Protocol's conformance suite gains §9:3's obligation and its
  canonical fake meets it.
- **`core/errors.py`:** an error for §4:7's refusal where the writer sees the record it names.
- **Version labels:** `MEMORY_RECORD_FORMAT`, the story store's `user_version`,
  `CONVERSATION_RECORD_FORMAT` and the plan store's schema version each advance once, with
  ADR-0326 §4:1's upgrade writing §5:1's home and §4:2's test; `notifications.db` gains its first
  label, its upgrade starting from the unlabelled file. No other store's label moves.
- **The wire:** `PROTOCOL_VERSION` advances once, in the lane that adds the home to models the wire
  carries.

The names of the types, members, functions, tests, events and holders are the build's.

### 14. What this decision leaves to others

- **D3:** the owner's acts to see, delete and export (ADR-0369 §12), which sight or domain each
  reads by, and what they show of a record with no home, never wider than the owner's domain.
  An export reads one domain (ADR-0369 §12:4).
- **ADR-0384:** whose sight its runs read by; this decision gives the value only (§6:8).
- **Milestone 4:** a place's audience, the mark and sends (ADR-0370, ADR-0372), what the posture
  becomes, and what a work does with what it read before a join narrowed its sight.
- **Milestone 5:** another person's or a group's home; what a line opens and the reach it reads; a
  name of a record of another domain, for a record made from another domain's records (ADR-0369
  §7:5); a home for the stores §3 gives none, the trails' for an access log among them; and whether
  §11's event survives a second person.
- **The next prompt review:** what a model is told of something out of view.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 15. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling: the home as its own type with three kinds (§2); the
store table, notifications carrying a home for ADR-0384 and stop records and device rows carrying
none (§3); a part taking its parent's home (§3:2); the producer's home from the episode's home
(§4:2); "whoever the connection belongs to" read by ADR-0368 §3:3's rule (§4:3); the refusal of a
name across homes, and of a refusal that tells (§4:7, §4:8); the upgrade writing the owner's home
over facts for no one, and a record with no home as no one's (§5); the sight's bounds, their meet,
senders from inputs, no level in a sight, and a producer's and a run's sights (§6); the filter in
each store behind one binding member, the equivalence rule, a work's own records, count or
withhold fixed at construction, a write's checks over every record, and the observer's finding of
what is due and its setting aside (§7); §8's places; §9's tests; §10's reading of `owner_records`;
§11's event; and §12:2's reading of earlier clauses over a bound store.

Of the coordinator's readings: the filter goes by person, not level (§6:9, from ADR-0369 §6:1 and
§10:4, which put bars on lines alone); the conversation window is a read the filter covers, so
conversations and messages carry a home (§3, §7:9); every pass the engine starts sets
`owner_records` to `True` (the five passes), though four projections default it to `False` and
stay so (§10:4); a view handed to the stages in place of the store is taken, minted by the store
itself rather than wrapped over it (§7); and `DeviceChecks` stays (§10:5).

## Consequences

- Every record a work, a producer, a run or a connection writes says whose it is, and the upgrade
  makes every earlier one the owner's with nothing for the owner to do.
- Every work for the owner reads what it reads today. An unidentified sender's work reads its own
  records alone: its chat's history, its line's earlier episodes and the conversations its
  Connections section would list are withheld.
- Once the filter withholds, the observer reads nothing of an unidentified sender's work, its
  episode included, and sets it aside (§7:13). So it does for an episode from before the upgrade
  whose facts say it was for no one, which §5:1 makes the owner's while §6:7 keeps its producer to
  the shared things, and for an episode that records no facts; the first deploy's count shows
  whether any is still due.
- Stages are handed stores per read, which moves where each holds them; no read site's call changes.
- **Revisit** when a second person, a group or a sharing rule is built, or if a store cannot answer
  a bound read at the cost the unbound one has.

## Alternatives considered

- **Each read member takes the sight as an argument.** A type catches a call with none, but some
  fifty members gain an argument, and sixteen earlier clauses fixing their arguments or answers
  would each need a partial supersession. Set aside for one binding member, with §9 to catch what
  the type no longer does.
- **One seam above the stores, filtering their answers.** Set aside: it sees answers after the
  limit, so pages come short and totals count what it withheld, or it fetches again in the
  withheld record's place (ADR-0369 §10:6).
- **No home field: a record's home read from its facts or its person.** Set aside: memories,
  stories, conversations and notifications record no fact that is their home, and an episode's
  facts can say "no one" where the owner chose every old record to be theirs.
- **A record with no home read as the owner's.** Set aside: it would make a write that drops the
  home land silently in the owner's domain, which with a second person is a leak (ADR-0380 §2:1).
