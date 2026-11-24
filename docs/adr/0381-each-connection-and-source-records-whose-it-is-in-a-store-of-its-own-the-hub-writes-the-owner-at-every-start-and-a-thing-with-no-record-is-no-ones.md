# 381. Each connection and source records whose it is in a store of its own, the hub writes the owner at every start, and a thing with no record is no one's

- Status: Proposed
- Date: 2026-11-24
- Scope: decision D6 of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)). It decides, for a hub that
  admits only the owner, which things record whose they are (§2), where that record lives and
  what it holds (§3), when it is written (§4), what a thing with no record means (§5), who reads
  it (§6) and that nothing changes it (§7). §8 records what it does to earlier decisions, §9 the
  contract changes it would need, §10 what it leaves to others, and §11 what it settled.
- Authorization: the owner's words, verbatim, of 2026-11-24: "yes agreed, but its milestone 21
  right, not 2", to the scope #3678 records, among it the row "Every connection, account and
  source records the person it belongs to. Today each is the owner's (ADR-0367 §6:1)." The owner
  has ruled nothing about where the record lives: every rule below is this decision's (§11). The
  coordinator assigned 0381 and ratifies it, under the owner's delegation, once its reviews are
  green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides a `core` Protocol and its types (§9), so it takes the adversarial and the
  architecture review. It supersedes nothing (§8).

## Context

[ADR-0367](0367-grants-say-who-may-do-what-and-how-sure-the-hub-must-be-every-call-is-checked-against-them-and-powers-are-handed-on-in-part.md)
§6:1 rules that every connection, account and source the hub acts through or reads belongs to one
person or one group, "recorded with it", and that permission to act through it or read it comes
from whoever it belongs to. Its §16 names the change in one line. Today the kinds have unlike
homes. An account connection is a `ConnectedAccount` row in `connections.db`, a type ADR-0151 §4:1
fixes at exactly four fields; the composition root registers from `Settings` the ones the hub acts
through (`_account_connections`). The line's place and the system's own chat are wiring, with no
stored record. A source is a reader's declared identity, a constant (ADR-0097 §1:1). An account
linked to identify its person is a link in the identity store, naming that person (ADR-0366 §6:2).

[ADR-0376](0376-a-line-names-the-owner-or-anyone-one-capability-and-at-most-one-connection-and-the-owner-lists-makes-and-removes-lines-through-four-engine-members.md)
§2:3 gives a call a thing only where `send_text`'s `connection` or `send_email`'s `from` names one,
and its §10 leaves to milestone 5 whether a default line covers a call through another's thing.
[ADR-0379](0379-a-limit-that-covers-a-call-decides-it-otherwise-the-grants-that-apply-at-its-level-decide-it-alike-and-a-ruling-names-the-made-grant-it-rests-on.md)
§3 turns *needs a yes: a grant allows with approval* into "the yes of whoever the call's thing
belongs to (ADR-0367 §5:6)".

**Words.** A **thing** here is a connection or a source; a **record** is the one saying whose a
thing is; a thing's **person** is whom its record names. A **line**, **grant**, **check** and
**yes** are ADR-0367's; a call's **thing** is ADR-0376's. A bare section reference, such as §5:2,
is to this decision's own clauses.

## Decision

We will keep one record per connection and source, in a store of its own keyed by the thing,
naming the owner; have the hub write it at every start for each thing it holds; read a thing with
no record as no one's, which can only refuse; and read it, in this milestone, only to say whose yes
a grant that asks needs.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** Until the store is built, nothing in this decision changes what the running hub
> allows, asks, shows or records.

> **Normative.** This decision rules only while the hub admits the owner alone (ADR-0367 §1:4). A
> record naming anyone but the owner, and any act that changes a record, wait on milestone 5.

### 2. Which things carry a record

> **Normative.** Each connection the system has (ADR-0364 §3:2) carries one record: the system's
> own chat as one connection, never per conversation (ADR-0376 §2:4); the line's place and each
> other place; each account connection the hub registers; and the schedule and the approvals,
> which ADR-0364 §3:2 counts among them though no line names them.

> **Normative.** Each source carries one record, keyed by its reader's declared identity
> (ADR-0097 §1:1).

> **Normative.** An account linked to identify its person carries no record here: its standing
> link in the identity store names its person (ADR-0366 §6:2, ADR-0365 §4:1), and nothing writes a
> second record that could disagree with it.

### 3. Where it lives and what it holds

> **Normative.** Records live in one store of their own, in `permissions/`, in a file of its own
> under `Settings.data_dir`, and nowhere else. No field is added to `ConnectedAccount`, to
> `SourceGrant` or to any other stored record for this.

> **Normative.** A record is keyed by its thing: whether it is a connection or a source, and its
> identifier, a connection spelled as a line spells one (ADR-0376 §2:4) and the schedule and the
> approvals as their places are. A thing has at most one record.

> **Normative.** A record holds its key, whose the thing is as a person's or a group's identifier,
> and when it was recorded. In this milestone the store refuses any identifier but the owner's
> identity, anyone's included.

> **Normative.** Each write is one atomic step that writes only where no record stands, so a
> repeated write writes nothing. Every record is carried by the store's export (ADR-0004 §6).

### 4. When it is written

> **Normative.** At every start, in the step that opens the store and before the hub admits any
> work, the hub writes a record naming the owner for each thing of §2:1 and §2:2 it then holds that
> has none. The start after the upgrade that builds the store writes every one of them.

> **Normative.** A thing the hub comes to hold while running has its record written, naming the
> owner, before the hub first acts through it, reads it or shows it to a work.

> **Normative.** Nothing asks the owner to set up, confirm or name whose any thing is.

### 5. A thing with no record

> **Normative.** A thing with no record belongs to no one. It is never read as the owner's or as
> anyone else's, and a record the store cannot read is read as none.

> **Normative.** Where an outcome needs the yes of whoever a call's thing belongs to and that
> thing has no record, the call is not done, saying why, and no card is made for anyone.

> **Normative.** A record, or its absence, never changes the check's outcome (ADR-0379 §2) and
> never lets a call through: it only names whose yes is needed.

### 6. Who reads it in this milestone

> **Normative.** The outcome *needs a yes: a grant allows with approval*, for a call that has a
> thing, sends its card to the person its thing's record names (ADR-0379 §3, ADR-0367 §5:6), or,
> under §5:2, sends none. For the system's own chat, the record read is the one of §2:1.

> **Normative.** For a call with no thing, no record is read, and the yes is asked of the person
> ADR-0361 §2:6 names.

> **Normative.** The Connections section (ADR-0368 §8:2) reads a record only as §6:1 and §5:2 turn
> an outcome: a connection on which a call could be allowed only by its person's yes, and which has
> no record, is not one the work could use.

> **Normative.** Nothing else reads a record in this milestone: not the check's outcome, not a
> source grant or a reader, not a briefing, and no member of `AssistantEngine`.

A shortfall's card goes to the person whose authority the work carries (ADR-0367 §5:3), and a work
that is not a person's asks for no yes (ADR-0368 §7:4), so neither reads a record. A source's
record waits for ADR-0367 §14:3 and milestone 5.

### 7. Nothing changes it

> **Normative.** No member, tool, plan, model, reader, upkeep job or `Settings` value writes,
> changes or removes a record, save §4's writes where none stands. A record stands after its thing
> is gone, and nothing reads it then.

The store lives in the data directory, so the owner's delete (ADR-0126), which destroys it with
the connection store, leaves no ledger of what the owner once connected (ADR-0151 §3:3).

### 8. Relationship to earlier decisions

> **Normative.** This decision supersedes nothing.

| Clause | What this decision does |
| --- | --- |
| ADR-0367 §6:1, §16's whose-a-thing-is bullet | Takes them: "recorded with it" as a record keyed by the thing (§3), "beside their declarations" set aside (§11) |
| ADR-0379 §3's table, a grant that asks | Takes its "whoever the call's thing belongs to" (§6:1) |
| ADR-0151 §4:1, ADR-0016 §1, ADR-0097 §1:1 | Read through: no field is added to any record they fix (§3:1) |
| ADR-0366 §6:2 | Read through: a link is its account's record (§2:3) |
| ADR-0361 §2:6 | Read through, for a call with no thing (§6:2) |
| ADR-0326 §4:1 | Read through: a new store, so no earlier file to upgrade |

### 9. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Golden rule 5 makes it breaking.

- **`core/protocols.py`:** a new Protocol for §3's store, with members to read one thing's record,
  write one where none stands (§3:4) and export every record, shipped as a triad.
- **`core/types.py`:** the record and its key (§3:2, §3:3); **`core/errors.py`:** the store's
  error.

The names, the file's name and the reading code are the building lane's.

### 10. What this decision leaves to others

- **Milestone 5 (ADR-0367 §6:2, §6:3, §7):** a record naming a group or another person; a person's
  own act to change whose a thing is, and whether a record keeps its history; whether a default
  line covers a call through another's thing (ADR-0376 §10).
- **ADR-0367 §14:3:** a source grant's maker, and who may make one.
- **B3 (ADR-0368 §6):** a task's author.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 11. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling: one store of its own rather than a field per kind,
since three of the four kinds have no stored record to hold one (§3:1); the schedule and the
approvals recorded (§2:1); a link standing as its account's record (§2:3); the start writing the
owner (§4); no record read as no one's (§5); the readers (§6); and ADR-0367 §16's "beside their
declarations", which is unmarked and so binds nothing, set aside for §3.

## Consequences

- Every connection and source records the owner with nothing for the owner to do, and a card for a
  grant that asks has a person to go to. A missing record costs a refusal, never an allowed call.
- No stored record changes shape, so no store upgrades.
- **Revisit** when a second person is admitted or a thing can change hands.

## Alternatives considered

- **A field on each kind's record.** Set aside: places, the own chat and sources have no stored
  record, and `ConnectedAccount` would need ADR-0151 §4:1 superseded.
- **Members on the identity store or the line store.** Set aside: the first answers who sent an
  input and the second keeps what people make by an act; this record is the hub's, written at start.
- **A computed rule, every thing the owner's; or no record read as the owner's.** Set aside: §6:1
  says "recorded", milestone 5 needs the records in place, and either would name a person no record
  names.
