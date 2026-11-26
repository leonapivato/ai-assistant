# 385. The owner's acts read through a sight of their own: seeing and deleting keep their members, and one new member exports one named domain whole

- Status: Proposed
- Date: 2026-11-26
- Scope: decision D3 of milestone 22, "Every record has a home" (acceptance
  [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)), its row "The owner's own
  data". For a hub that admits the owner alone, it decides which domains an owner's act may name
  (§2); the sight each owner's act reads by (§3); what seeing is (§4); what each delete acts on
  (§5); the one new member that exports a domain, and what an export holds (§6); whose act each
  is and who may call it (§7); and the wire (§8). §9 says what becomes of what exists already,
  §10 what it does to earlier decisions, §11 the contract changes it would need, §12 what it
  leaves to others, and §13 what it settled. It takes
  [#1502](https://github.com/leonapivato/ai-assistant/issues/1502).
- Authorization: the owner's words, verbatim. On 2026-11-23, "Yes, scope milestone 1", to "Do you
  accept the five-milestone order for the build plan?"; the order is in #3709's first paragraph.
  On 2026-11-26, "Yes, agreed", to "Do you agree this scope: "Yes, agreed" or "Change
  something"?", the scope being what #3709 records with six picks of the coordinator's, which that
  answer accepted and nothing more; among them, that one new act exports everything of a domain,
  that deleting stays item by item as today, that deleting a whole domain comes with a person
  leaving in the last of the five milestones, that there is no access log now, and that these acts
  are on the command line only, the web page later. The owner ruled nothing about members, sights
  or what an export holds: every rule below is this decision's (§13). The coordinator assigned
  0385 and ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides a member of `AssistantEngine`, the promoted surface the wire carries, a
  member of `StoryStore` and a `core` constructor of the sight (§11), so it takes the adversarial
  and the architecture review. Building it is a breaking change under golden rule 5.
- **Partially supersedes**
  [ADR-0298](0298-the-gateway-names-a-browser-device-on-each-request-and-the-hub-checks-every-request-by-one-table.md)
  (§5:1's table, in the addition alone: `export_domain` in the command-or-query row) and
  [ADR-0383](0383-each-record-carries-its-home-and-every-read-a-work-a-producer-or-a-run-makes-is-of-a-store-bound-to-one-sight-which-answers-as-though-it-held-only-what-that-sight-sees.md)
  (§6:10 and §9:2, each in the addition alone: a constructor of the sight for an owner's own act,
  and the engine's members as the place that makes it; §7:10, in its reach: a store bound for an
  owner's act withholds from the build that binds it), as §10 records.

## Context

[ADR-0369](0369-a-record-lands-in-the-domain-of-whom-its-work-is-for-sharing-rules-open-a-domain-and-default-to-private-every-read-is-filtered-to-who-may-see-and-each-person-sees-deletes-and-exports-their-own.md)
gives each person the power to see, delete and export the records of their own domain, by their
own act, and the owner the same over the hub's shared things (§12:1, §12:2); has each delete and
export act on one domain, named in the act, with no value meaning every domain (§12:4); and has a
surface show a person only records §6 lets them see (§12:9). Its §16 names "engine members for a
person to see, delete and export one domain". ADR-0383 gives every record a home and has each
store answer a reader only through a binding to a sight (§7:1, §7:2). A caller that is not a work,
a producer or a run "binds a store to the sight its own decision gives it. The owner's own acts are
D3's" (§7:8); and it leaves here what they show of a record with no home, "never wider than the
owner's domain" (§14).

**The surface today** (`origin/main` at `23f569c53`). `AssistantEngine` has three exports, each one
store's: `export_decisions` and `export_invocations` of the audit trail and `export_reads` of the
source-read trail (ADR-0186), each with an `assistant` command. It has five deletes of the owner's
records, each of one item and each with a command: `forget` (a memory, `assistant forget`),
`forget_notification`, `forget_conversation` (the episodes on a conversation's place, ADR-0293
§2:4), `delete_message` and `delete_conversation`. Every other member that gives back a record is a
listing or an inspection: `episodes`, `episode_chunk`, `beliefs`, `belief`, `stories`, `story`,
`story_log`, `story_summary`, `recent_conversations`, `conversation`, `transcript`,
`notifications`, `person_model`, `profile_changes`, `approvals` and the rest. None reads by a person:
each reads its store whole. `MemoryStore`, `PlanStore`, `ConversationStore`, `NotificationStore`
and `PersonModelStore` each have an `export` with no surface, and so do the identity, thing-record,
source-grant and Telegram-intake stores; `StoryStore` has none. #1502 records that the composed
"export my data" ADR-0004 §6 and ADR-0074 §9 rule reaches no user; the composing method it names,
`ConversationLifecycle.export`, and its `DataExport` type are no longer in the tree.

**Words.** A **domain**, the **hub's shared things** and the **data rights** are ADR-0369's; a
**home**, a **sight**, a **bound**, a **bound store** and a **reader** are ADR-0383's. The **seven
stores** are the six store Protocols ADR-0383 §7:1 names and `MemoryWriter`. An **owner's act** is
a call to a member of `AssistantEngine` other than `receive` (§3:5). The **owner's sight** is the
sight §3:2 makes for one. A bare section reference, such as §6:2, is to this decision's own clauses.

## Decision

We will have every owner's act read and write the seven stores through a sight made for it alone;
keep seeing and deleting on the members the owner has, each acting inside one domain; and add one
member, `export_domain`, that takes one named domain and returns everything the stores hold of it,
whole.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules a hub that admits the owner alone, whose only homes are the
> owner's domain and the hub's shared things (ADR-0383 §1:2). A manager's acts (ADR-0369 §12:2's
> first sentence, §12:3), and deleting a whole domain, leaving and removal (§12:6 to §12:8), are
> not its.

> **Normative.** Until the lane that builds it has merged, nothing in this decision changes what the
> running hub stores, reads, shows or allows.

### 2. The domains an act may name

> **Normative.** An owner's act may name as its domain the owner's domain (the person home of
> `OWNER_PERSON_ID`) or the hub's shared things (ADR-0369 §12:1, §12:2, §2:8), and no other. One
> `core` function names these, and no other place decides it.

> **Normative.** An act that names any other value of ADR-0383 §2's home, a group's domain or
> another person's included, is refused from the value alone, before any store is read, and the
> refusal is the same whatever any store holds.

> **Normative.** No value of a domain an act takes means every domain or more than one, and no act
> takes a domain with a default (ADR-0369 §12:4, ADR-0101 §1:5).

### 3. The owner's sight

> **Normative.** Every read and write an owner's act makes of one of the seven stores is made
> through that store bound, by ADR-0383 §7:1's binding member, to the owner's sight §3:2 makes from
> the domain the act names, or from none where it names none, save as §5:4 says.

> **Normative.** The owner's sight is made by one `core` constructor for an owner's own act, from
> the domain the act names or from none, and by nothing else: from none, a person bound for the
> owner alone; from a domain §2:1 allows, a person bound for the owner and a one-domain bound for
> that domain. The constructor refuses any other domain.

By ADR-0383 §6:1 and §6:2, the first sees the owner's domain and the shared things, which is
ADR-0369 §6:1 for the owner with no line made; the second sees the one domain named. Neither sees a
record with no home (ADR-0383 §5:3).

> **Normative.** The owner's sight carries no activation, so nothing is an act's own (ADR-0383
> §7:4), and no level, link, lowering or line enters it (ADR-0383 §6:9).

> **Normative.** A store bound to the owner's sight withholds from the build that first binds it,
> and writes no event of ADR-0383 §11:1.

> **Normative.** `receive` is not an owner's act: it runs a work, and what that work reads is by
> the work's sight (ADR-0383 §7:7).

§3:4 is why the owner's acts cannot wait for ADR-0383's switch. A store that only counts answers as
the unbound store does (ADR-0383 §11:1), so an export of the shared things built before the switch
would hold the owner's whole domain. With one person, the owner's sight from none withholds only a
record with no home, which ADR-0383 §5:1 and §5:4 leave none of, so seeing gives back what it gives
back today.

### 4. Seeing

> **Normative.** No member is added for seeing. Each member of `AssistantEngine` that gives back
> records of the seven stores takes the arguments it takes today, names no domain, and gives back
> only what the owner's sight from none sees (ADR-0369 §12:9).

> **Normative.** No member gives back, counts or names a record with no home (ADR-0383 §5:3), and
> no member says whether one exists.

Seeing on the command line is therefore every command that calls such a member. Today those are:

| Store | Commands | Members |
| --- | --- | --- |
| Memory | `episodes`, `episode`, `beliefs` | `episodes`, `episode_chunk`, `beliefs`, `belief` |
| Stories | `story list`, `story show`, `story summary`, `story standing`, `episode` | `stories`, `story`, `story_log`, `story_summary`, `story_standing`, `activation_stories` |
| Conversations | `conversations`, `conversation`, `chat` | `recent_conversations`, `conversation`, `transcript`, `follow_chat` |
| Notifications | `notifications` | `notifications` |
| Person model | `about show`, `about log` | `person_model`, `profile_changes` |

A member a later decision adds that gives back such records is bound by §4:1 too. Whether a command
prints a record's home is the build's.

### 5. Deleting

> **Normative.** No delete is added. The deletes of the owner's records at the engine surface are
> `forget`, `forget_notification`, `forget_conversation`, `delete_message` and
> `delete_conversation`, and each takes the arguments it takes today.

> **Normative.** `forget`, `forget_notification`, `delete_message` and `delete_conversation` each
> act on one domain, the home of the item they name, which the act names by naming the item. Each
> reads and writes by the owner's sight from none, and changes records of that home alone (ADR-0369
> §12:5, ADR-0383 §4:7).

> **Normative.** Where the item named is one the owner's sight does not see, the member answers
> exactly as for an item never written (ADR-0383 §8:2): `forget`, `forget_notification` and
> `delete_conversation` return `False`; `delete_message` raises `UnknownConversationError` where
> the conversation is not seen, and returns `False` where only the message is not.

> **Normative.** `forget_conversation` acts on the owner's domain alone. It reads and forgets by the
> owner's sight from the owner's domain, so it forgets the episodes of that domain on the
> conversation's place and none of another home, whether or not the conversation still stands
> (ADR-0293 §2:5).

In this milestone every conversation is the owner's (ADR-0383 §4:3), so §5:4 forgets what the
member forgets today, save a record with no home. An item is deleted where its home is the owner's
domain or the shared things alike, since both are the owner's to delete (ADR-0369 §12:2).

### 6. The export

> **Normative.** `AssistantEngine` gains exactly one member for the data rights: `export_domain`.

> **Normative.** `export_domain` takes one positional argument, `domain`, a value of ADR-0383 §2's
> home, with no default. Where §2:1 allows it, it returns the outcome `exported` with the domain's
> export; otherwise the outcome `refused` with the reason `not_offered`, having read nothing (§2:2).

> **Normative.** `export_domain` reads by the owner's sight from the domain named, through each
> bound store's own read, and composes what they give back into one value. No part is filtered
> against another, and no record is read that the sight does not see.

> **Normative.** An export holds, of the domain named and of nothing else: the memory records,
> episodes and memories, that the bound `MemoryStore.export` gives back; every story, with its
> members, notes, summary versions and log lines, that the `StoryStore` export §11 names gives
> back; the conversations and their standing messages that the bound `ConversationStore.export`
> gives back; the effects, observations, scheduled tasks and approval requests that the bound
> `PlanStore.export` gives back, and no stop record; what the bound `PersonModelStore.export` gives
> back; and the held notifications the bound `NotificationStore.export` gives back.

> **Normative.** Each part is exactly that store's export, carrying and omitting what its contract
> says, over the records its bound store holds (ADR-0383 §12:2): expired memories and deleted
> conversations stay out, and no embedding or walk position is carried.

> **Normative.** An export holds nothing of a store ADR-0383 §3 gives no home: the audit trail, the
> source grants, the source-read trail, the traces, the outbox, the Telegram intake, the
> connections, the keyring, the bookings, the devices, the identities, the permission lines, the
> thing records and the diagnostic record.

> **Normative.** An export is whole, or refused with `OversizedValueError` where its encoding passes
> ADR-0085 §8c's limit; it is never truncated, sampled or split, as `export_decisions` is (ADR-0186
> §3:2). A domain the stores hold nothing of is `exported` with every part empty.

> **Normative.** Each value `export_domain` takes or returns is a frozen pydantic model or an
> enumeration in `core/types.py`, reachable from the surface (ADR-0084 §4, ADR-0085 §5); its
> outcomes and reasons are closed sets of exactly those §6:2 names; and the export carries the
> domain it was made for and the instant it was made.

> **Normative.** A blank or malformed `domain` is refused with `ValueError` before any I/O. A store
> that cannot be read raises the error its contract declares, and nothing is returned in part.

> **Normative.** The export crosses the wire whole, as the member's result. The hub writes no file
> for it, and the command line writes it as one JSON document on standard output and nothing else
> there, as ADR-0186 §9:2 rules for the trail's export.

The parts are read one after another, so an export is an account taken over an interval, not at an
instant, as ADR-0074 §9 has the composed export. Since ADR-0383 §4:7 refuses any record naming one
of another home, nothing in an export of one domain names a record of another. A domain that
outgrows the frame limit is exported once an operator raises `hub_max_frame_bytes`, which the
connect reply carries to the client (ADR-0084 §3).

### 7. Whose act, and who may call

> **Normative.** No tool, capability or plan step binds `export_domain` or a delete of §5:1, no
> work, model, task or upkeep calls one, and no model-authored value becomes an argument to one. No
> tool exports or deletes a domain.

> **Normative.** `export_domain` is classified in ADR-0298 §5:1's command-or-query row, so a request
> from a device without the command role is refused before dispatch (ADR-0298 §5:6).

> **Normative.** A call to `export_domain`, and to each member §4 and §5 name, is the owner's own act
> (ADR-0369 §12:1), on the ground ADR-0373 §4 and ADR-0376 §6 rest theirs on.

> **Normative.** In this milestone only the `assistant` command line calls `export_domain`. ADR-0177
> §1:1's enumeration does not gain it, and no gateway route, page panel, line or spoke calls it.

> **Normative.** `export_domain` is served on the hub's loopback and remote listeners, as
> `export_decisions` is (ADR-0186 §5:1), and no lane adds a per-listener restriction for it.

§7:3 rests where ADR-0373 §4:3 and ADR-0376 §6:3 rest: every caller of a command-or-query member is
the hub's own machine, which holds every role on the owner-only local socket (ADR-0298 §3:2), or a
device whose command role only the owner assigns, at the hub (ADR-0298 §4:14), on a device the
owner enrolled there (ADR-0124 §6:1) carrying the owner's single principal (ADR-0124 §5:4). The
members §4 and §5 name keep their rows; each caller of them is the owner or a device of the owner's.

### 8. The wire

> **Normative.** The change that adds `export_domain` advances `PROTOCOL_VERSION`, in that same
> change (ADR-0124 §9:2), whether or not another change in the same release also advances it.

No member §4 or §5 names changes its arguments or its result's shape here, so nothing else moves the
version. A gateway calls `export_domain` never, but it speaks the wire, so it upgrades with the hub.

### 9. What exists already, and what becomes of it

| What | What becomes of it |
| --- | --- |
| `export` of the memory, plan, conversation, person-model and notification stores | Stand as store operations; `export_domain` reads each through its bound store (§6:4). None gains a surface of its own |
| `export` of the identity, thing-record, source-grant and Telegram-intake stores | Stand, with no surface; outside every export (§6:6) |
| `export_decisions`, `export_reads`, `export_invocations` | Stand beside, unchanged (ADR-0186 §1:1). They read stores with no home, so none is an export of a domain, and the owner is shown them as today |
| The five deletes | Stand, each acting in one domain (§5) |
| #1502's question | Answered: the composed export is an engine member, not a console script, and the trails' exports stand beside it. The lane that builds this decision closes #1502 |
| ADR-0074 §9's composed export | Built by §6: composed in `orchestration`, one artifact. Its filter of turns against episodes has had no object since ADR-0283 retired the export's turns |
| The offline tools, ADR-0126's whole-installation delete among them | Not this decision's (ADR-0384 §12) |

### 10. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0298 §5:1's table, in the addition alone:
> its command-or-query row also names `export_domain` (§7:2), as ADR-0373 and ADR-0376 added theirs.
> No other row changes.

> **Normative.** This decision partially supersedes ADR-0383 §6:10, in the addition alone: a sight
> is also made by the `core` constructor for an owner's own act (§3:2), from the domain the act
> names or none rather than from recorded facts.

> **Normative.** This decision partially supersedes ADR-0383 §9:2, in the addition alone: the
> engine's members make the owner's sight through that constructor, and the named test admits them.

> **Normative.** This decision partially supersedes ADR-0383 §7:10, in its reach: its "the build
> that first binds the stores counts" does not reach a store bound to the owner's sight (§3:4). Its
> first half binds it as written.

> **Normative.** This numbered draft records its replacements on ADR-0298's and ADR-0383's status
> lines and in a dated header note on each, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving their ratified bodies. The replacements take effect on this ADR's ratification.

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0369 §12:1, §12:2's second sentence, §12:4, §12:5, §12:9 | §2, §4, §5, §6 for one person |
| ADR-0369 §16's data-rights bullet, in seeing, deleting and exporting one domain | §4 to §6 |
| ADR-0383 §7:8's "The owner's own acts are D3's", and its §14's D3 bullet | §3; a record with no home is shown by no act (§4:2) |
| ADR-0004 §6's view, export and delete | §4 to §6, for the stores that carry a home |

Read through and standing, each as written: ADR-0383 §9:1 (the engine's owner's acts are a holder
§7:8 names); ADR-0383 §11 (no event for the owner's sight, §3:4); ADR-0186 §1:1, §9:2 and §9:4 (the
trails' exports stand, the command writes standard output, and the bare name `export` stays
reserved, so the build names this command otherwise); ADR-0101 §1:5 (no default widens a delete);
ADR-0007 (the store operations); ADR-0293 §2:4 and §2:5 (§5:4 narrows `forget_conversation` to one
domain and leaves both); ADR-0373 §4 and ADR-0376 §6 (§7).

### 11. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Golden rule 5 makes each breaking.

- **`core/types.py`:** the function naming the domains an owner's act may name (§2:1); the sight's
  constructor for an owner's own act (§3:2); the domain export, its outcome and its closed reason
  (§6:2, §6:8); and a story store's export: every story with each part ADR-0383 §3:2 gives it its
  home, and nothing store-wide (ADR-0383 §8:5). All are wire-carried.
- **`core/protocols.py`:** `AssistantEngine.export_domain`, documented with its outcomes and
  refusals, implemented by the engine and the wire client alike, with conformance tests; and
  `StoryStore.export`, whose conformance suite gains its obligation and whose canonical fake meets
  it. No new Protocol, so no triad. Each member §4 and §5 name is documented as reading by the
  owner's sight.
- **The engine:** each owner's act binds the stores it reads and writes per call (§3:1).
- **The wire:** `export_domain` in `METHODS` and in the command row of the route table
  (`wire/routes.py`), and `PROTOCOL_VERSION` advanced (§8:1).
- **The command line:** a command that takes a domain and writes its export (§6:10), named by the
  build but not bare `export`.

No store's version label moves: the story store's export reads and stores nothing new.

### 12. What this decision leaves to others

- **ADR-0383's build lanes:** the home, the sight, its bounds and the binding member.
- **Milestone 5:** another person's domain and a group's; a manager's acts; deleting a whole domain,
  leaving and removal; whose each record of the stores with no home is, and what a domain's export
  then takes of them (ADR-0383 §14); which domain `forget_conversation` acts on once a conversation
  can be of another; and whether an offline tool may reach a domain other than its runner's
  (ADR-0384 §12).
- **The decision that builds sharing rules:** the access log (ADR-0369 §13).
- **A later decision:** these acts on the web page or any surface but the command line; an import;
  an export streamed or split, should a domain outgrow any frame an operator sets.
- **The owner's forgetting design:** forgetting by whom a record is about (ADR-0101, ADR-0320 §4).

> **Normative.** This decision may not be cited to settle any matter §12's list leaves to another.

### 13. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling: the two domains an act may name and the refusal of
any other from the value alone (§2); the owner's sight, its constructor, that it withholds from its
first build, and that `receive` is no owner's act (§3); seeing as today's members bound to that
sight, and a record with no home shown by no member (§4); an item delete's domain as its item's
home, and `forget_conversation` on the owner's domain (§5); one member, `export_domain`, what it
holds store by store, nothing of the stores with no home, whole or refused, refusals as outcomes,
and its form on standard output (§6); the member's row, listeners and the command line only (§7);
what stands beside it (§9); and the three partial supersessions of ADR-0383 (§10).

Of the coordinator's readings: an export is the owner's act, bounded by ADR-0369 §12 and not §10,
taken (§3, §7); one act composing the stores, as ADR-0074 §9 meant, taken (§6:3); seeing needs no
new member, taken, with every seeing member bound so that it holds (§4:1); and a record with no
home is shown to the owner by no act, taken, with no rule here on the offline tools (§4:2, §9).

## Consequences

- The owner exports their own domain, or the shared things, as one JSON document from the command
  line, and sees and deletes item by item as today, with no model or message able to do any of it.
- Every owner's act reads by a sight from its first build, so an export never holds two domains,
  and a record with no home is reached by no act: it can arise only from a defect, and stays until
  an operator's tool or a later decision reaches it.
- The trails, the connections and the identities stay outside the domain export until milestone 5
  gives their records a home; the owner still exports the trails by their own commands.
- Every client and gateway upgrades with the hub at the version bump.
- **Revisit** when a second person or a group is admitted, when these acts reach the web page, or
  when a domain's export does not fit any frame an operator will set.

## Alternatives considered

- **One export command per store.** Set aside: ADR-0074 §9 has the user's export composed into one
  artifact, and #3709's scope is one act exporting a whole domain.
- **Every delete takes a domain argument.** Set aside: an item has one home, so the argument could
  only repeat it or name a domain the item is absent from; it adds a refusal and no protection, and
  changes five members' wire shapes.
- **The owner's acts count before the switch, as the work's reads do.** Set aside: a counting store
  answers as the unbound one, so an export would hold every domain until the switch (§3:4).
- **Seeing members gain a domain filter.** Set aside: §12:9 needs only that no member shows a record
  the owner may not see, which the owner's sight from none gives; a filter by domain is a feature
  no ruling asks for.
- **The export written as a file on the hub's machine.** Set aside: an enrolled device's command
  line could not reach it, and a path a client names is a write the hub would make for it. The
  trails' exports already go to standard output (ADR-0186 §9:2).
- **The trails inside the domain export.** Set aside for this milestone: their records have no home
  (ADR-0383 §3), so an export of one domain could not say which rows are its, and their own exports
  already reach the owner.
