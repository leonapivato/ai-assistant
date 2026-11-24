# 376. A line names the owner or anyone, one capability and at most one connection, and the owner lists, makes and removes lines through four engine members

- Status: Proposed
- Date: 2026-11-24
- Scope: the first decision lane, D1, of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)). It names the first kinds of
  what a line names, which
  [ADR-0367](0367-grants-say-who-may-do-what-and-how-sure-the-hub-must-be-every-call-is-checked-against-them-and-powers-are-handed-on-in-part.md)
  §3:4 leaves to a later decision: who, an action, a thing and a condition (§2); how a tool's
  default grant is a line (§3); and what `AssistantEngine` and the wire gain so the owner can
  list, make and remove lines by their own act (§4 to §7). §8 records what it does to earlier
  decisions, §9 the contract changes it would need, §10 what it leaves to others, and §11 what
  it settled where the rulings left a point open.
- Authorization: the owner's words, verbatim. 2026-11-23: "Yes, scope milestone 1", to "Do you
  accept the five-milestone order for the build plan?" (the order #3678's first paragraph
  gives). 2026-11-24: "Yes, keep driving and draft the scope", to the coordinator's offer to
  draft this milestone's scope; "yes agreed, but its milestone 21 right, not 2", to the scope as
  #3678 records it with six picks of the coordinator's, which that answer accepted and nothing
  more: among them, the default grants (look-ups, answering and the person's own reminders,
  notes, memory and matters for any identified sender; anything that leaves the system, changes
  a permission or links an account at normal), "anyone" getting an answer in the place it wrote
  and no tool, and the owner listing, adding and removing permissions and limits from the
  command line; and "Yes, go", to "Shall I post the batch issue and start D1, D2, D3 and B1".
  The coordinator assigned 0376 and ratifies it, under the owner's delegation, once its reviews
  are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides what a line names, which bounds the type and store ADR-0367 §16 has the
  build make, and members of `AssistantEngine`, the promoted surface the wire carries, so it
  takes the adversarial and the architecture review. Building it is a breaking change under
  golden rule 5, through the changes §9 names, none of which is made here.
- **Partially supersedes**
  [ADR-0298](0298-the-gateway-names-a-browser-device-on-each-request-and-the-hub-checks-every-request-by-one-table.md)
  (§5:1's table, in the addition alone: the four members in the command-or-query row), as §8
  records.

## Context

ADR-0367 made what a person may do a set of **lines**: a grant is "who (a person or a group);
what (an action on a thing); how (allowed, or allowed with approval); its bar ...; any
conditions; and who set it" (§3:1), and a limit is the same line saying no, with no how and no
bar (§3:2). Conditions are drawn from a time window, an end date and one connection (§3:3).
The "what" is open on purpose, and a later decision "may add kinds of action, thing and
condition" (§3:4). Every tool declares a default grant where it is declared, "a line like any
other" (§4:3). Lines are made and removed only by a person's own act or by a checked call on
their authority, and every making and removal is kept (§3:5), in a store of `permissions/`
under stable identifiers never reused (§3:6). ADR-0367 §16 names, among the changes its build
needs, the line type and its store, each tool's default grant on `ToolDefinition`, and "engine
members for a person's own act to ... make and remove lines".

Milestone 21 builds ADR-0367 §2:3, §3 to §5, §6:1 to §6:2 and §9:4, and ADR-0368 §5 to §8,
on a hub that admits only the owner (ADR-0367 §1:4). Its build lane for the store cannot type a
line, and its check cannot say which line covers a call, until the first kinds are named.

**The calls today.** Every capability a work may call is declared by a `ToolDefinition`, in
`tools/` or in `orchestration/`. A call names a connection only by an `L` label (ADR-0364
§3:3): `send_text`'s `connection` (ADR-0364 §9:1) and `send_email`'s `from`, "an `L` label
naming an email account connection the work was shown" (ADR-0364 §9:11). An `L` label names a
place, `<channel type>:<instance id>` (`place_of` in `orchestration/channel_kinds.py`), or an
account connection, `account:` and its reference (`AccountConnection.place`). The system's own
chat is one connection whose places are its conversations, each with its own entry (ADR-0364
§3:2). `search_web` and `read_forecast` act through the one search and forecast account the
composition root registers, which no value of their call names; `booking_availability` and
`book_stay` reach an endpoint the hub records as no connection; `spawn_task` names connections
its task's work may speak in, and sends nothing itself; and every other declared call reads or
writes the assistant's own records, or nothing.

**The surface today.** `AssistantEngine` has no member for lines. Its `grant`, `revoke` and
`standing_grants` are ADR-0102's, over ADR-0097's source grants, which ADR-0367 §14:2 keeps
apart from lines. ADR-0373 gave the owner three members over links, placed in ADR-0298 §5:1's
command-or-query row, and rested "the owner's own act" on who can reach that row (ADR-0373 §4).

**Words.** A **line**, a **grant**, a **limit**, a **bar**, a **level**, **anyone**, **the
check** and a **work** are ADR-0367's. A **capability** is a `ToolDefinition`'s `capability`, and a
tool the running hub **declares** is one whose declaration it holds for its works to call, in the
tool registry or among orchestration's own calls. A call's **thing** is the connection the call acts through (§2:3). A **default line** is a tool's
default grant (ADR-0367 §4:3); a **made line** is one a person made by an act under ADR-0367
§3:5. The **store** is ADR-0367 §3:6's. The **owner's identity** is the one ADR-0345 §2:5's
identifier names. A bare section reference, such as §4:2, is to this decision's own clauses.

## Decision

We will have a line name the owner or anyone, exactly one capability, at most one connection as
its thing, and on a grant at most one connection as its condition; derive a call's thing in
code from the values that name a connection; make each tool's default grant a line to anyone
held by its declaration; give `AssistantEngine` four members to list the lines that stand, make
a grant, make a limit and remove a made line, in the command-or-query row; let no tool make or
remove a line; and advance the protocol version.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** Until the line store and the four members are built, nothing in this decision
> changes what the running hub allows, asks, shows or records.

> **Normative.** This decision admits no one, gives no person other than the owner any act, and
> is not among the provisions ADR-0365 §1:3 and ADR-0367 §1:4 name for admitting another person.

### 2. What a line names

> **Normative.** A line's who is the owner's identity or anyone (ADR-0367 §2:3), and nothing else
> until a decision for milestone 5 adds groups and other people.

> **Normative.** A line's action is exactly one capability, named by its `capability` value.
> It is never named by a tool's id or by any other value of its declaration, so a change in a
> declaration that keeps its capability leaves every line naming it as it was (ADR-0364 §8:7).

> **Normative.** Code derives a call's thing from the call's own values, with no model: for
> `send_text`, the connection its `connection` names; for `send_email`, the account connection
> its `from` names; and for every other capability declared on the day this decision is
> ratified, none. A change that adds or changes a capability whose call acts through a connection
> one of its values names says which value names it, and until a ratified decision or that
> change says so, that capability's calls have no thing.

> **Normative.** A line names a connection by a stable identifier for what an `L` label names
> (ADR-0364 §3:3): one place, or one account connection by its reference (ADR-0151 §3). The
> system's own chat is named as one connection, never by one of its conversations. The schedule
> and the approvals (ADR-0364 §3:2) are named by no line.

> **Normative.** A line's thing is one connection or none. A line with no thing covers a call
> whatever the call's thing; a line whose thing is a connection covers only a call whose thing is
> that connection.

> **Normative.** In this milestone a line's only condition is one connection, on a grant alone,
> named as §2:4 names a connection, and met as ADR-0368 §4:2 and §6:4 rule. No line names a time
> window or an end date, and no limit carries a condition.

> **Normative.** A line covers a call where its who includes the person the check runs for, its
> action is the call's capability, its thing covers the call's under §2:5, and its condition,
> where it has one, is met. A line's bar is not part of whether it covers a call: ADR-0367 §5:1
> and §5:3 read it of a grant that covers one.

> **Normative.** A line whose action no tool the running hub declares has, or whose thing or
> condition names a connection the hub no longer has, stands and covers no call. A change that
> renames a capability says what becomes of the lines that name its old name.

So "who may send from one account" (DO-02) is a line's thing, and "who may ask through one
connection" (WORK-14) is a grant's condition: the first is what the call acts through, the
second where the work's senders' inputs came by. Today's declared capabilities fall as follows.

| Calls | Their thing |
| --- | --- |
| `send_text` | The connection `connection` names. A text into a place one of the work's inputs came from stays outside the check (ADR-0367 §4:7), whatever line names it |
| `send_email` | The email account `from` names |
| `search_web`, `read_forecast` | None: their account is the composition root's, and no value names it |
| `booking_availability`, `book_stay` | None: their endpoint is no connection the hub records |
| `spawn_task` | None: its `connections` are where its task's work may speak, each text checked when sent (ADR-0368 §6:2) |
| The look-ups, the memory, profile, matter, task, reliance, stop and offer calls, `request_approval`, `report_current_time` | None: each reads or writes the assistant's own records, or nothing |

`run_approved` is not a call of its own: what it runs is its ticket's call, checked as ADR-0367
§5:5 rules. Where ADR-0367 §6:1 also names accounts and sources: no call acts through an account
linked to identify its person (ADR-0366 §6:2), and readers read sources under source grants,
never by a call (ADR-0367 §14:2), so neither is a call's thing in this milestone.

Two worked lines. The owner's choice gives look-ups to "any identified sender": `search_memories`'
default line names anyone, the action `search_memories`, no thing, allowed, a bar of weak, no
condition, set by its tool's declaration; ADR-0367 §5:1 lets it apply only at weak or above, so
an unidentified sender's work, at none, gets no `search_memories`. DO-02's limit names the owner,
the action `send_email` and the thing the one email account: it covers every `send_email` call
whose `from` names that account, at every level (ADR-0367 §3:2), and no call from another account.

### 3. A tool's default grant

> **Normative.** A tool's default grant is a line naming anyone, its tool's capability, no thing,
> the how and the bar its declaration gives, and no condition. It is set by its tool's
> declaration, not by any person.

> **Normative.** A default line covers only calls made through the tool that declares it.

> **Normative.** A default line is held by its tool's declaration and not by the store, has no
> identifier in the store, and is named in no `PermissionRuling.authorised_by` (ADR-0367 §4:6).

> **Normative.** No member changes or removes a default line in this milestone. The owner
> narrows what one allows by making a limit, and allows more by making a grant of their own.

> **Normative.** No tool declares a default limit in this milestone. The change that ships the
> first one decides how a person holding the power over its thing removes it and how the store
> records that removal (ADR-0367 §3:5, §9:4).

### 4. The four members

> **Normative.** `AssistantEngine` gains exactly four members for lines: `permission_lines`,
> `make_grant`, `make_limit` and `remove_line`, and no other.

> **Normative.** `permission_lines` takes no argument and is not paged. It returns every line that
> stands, one entry each (§5): each made line not removed, and the default line of each tool the
> running hub declares. It is in no contractual order, complete or refused with
> `OversizedValueError` and never truncated, as `linked_accounts` is (ADR-0373 §2:2).

> **Normative.** `make_grant` takes, keyword-only and each with no default, a `who`, an `action`,
> a `how` and a `bar`, and, keyword-only and absent by default, a `thing` and a `condition`, each
> a connection. It records a grant with those parts, made by the owner (§6:3), and returns the
> outcome `made` with the line as the store recorded it.

> **Normative.** `make_limit` takes, keyword-only, a `who` and an `action`, each with no default,
> and a `thing`, absent by default. It records a limit with those parts, made by the owner, and
> returns the outcome `made` with the line as the store recorded it.

> **Normative.** `make_grant` and `make_limit` decide their outcome in this order, writing
> nothing in the first five: the outcome `refused` with the reason `unknown_who` where `who` is
> neither the owner's identity nor anyone; `refused`, `unknown_action`, where no tool the running
> hub declares has the capability; `refused`, `no_thing`, where a thing is given and the action's
> calls have none (§2:3); `refused`, `unknown_connection`, where a thing or condition names no
> connection a line may name (§2:4) that the hub has; `unchanged`, with the standing line, where a
> made line of the same kind with exactly the same parts stands, so repeating the call makes no
> second line; and otherwise `made`.

> **Normative.** `remove_line` takes a line's identifier as its positional subject. It removes
> that made line and returns the outcome `removed` with the line as it stood. Where no standing
> made line has that identifier, because none was made or it was already removed, it writes
> nothing and returns the outcome `not_standing`, which is not an error.

> **Normative.** A blank identifier, and a `bar` or `how` that is not one of its values, are
> refused with `ValueError` before any I/O, as ADR-0373 §2:7 rules. A store that cannot be read or
> written raises the error the store's contract declares for that, and every refusal of an act is
> an outcome the member returns, never an error.

> **Normative.** The store keeps each made line under a stable identifier never reused, records
> who made it and when, and records each removal, by whom and when, keeping the removed line's
> record, so that an identifier a ruling names resolves to its line after the line is removed
> (ADR-0367 §3:5, §3:6, §4:6).

> **Normative.** A making or a removal bears only on calls the check checks after it is
> recorded, those of works already running and of tasks included (ADR-0368 §6:2). It changes no
> ruling already made and no capability already offered (ADR-0368 §8:1).

> **Normative.** Each value the four members take or return is a frozen pydantic model or an
> enumeration in `core/types.py`, reachable from the surface (ADR-0084 §4, ADR-0085 §5), and its
> outcomes and reasons are closed sets of exactly the members this section names.

The type names are the implementing lane's, as are `who`'s spelling of anyone and the spelling of
a connection's identifier, under §2:1 and §2:4.

### 5. What the listing shows

> **Normative.** Each entry of `permission_lines` carries whether the line is a grant or a limit;
> its who, its action and its thing or none; for a grant, its how, its bar and its condition or
> none; and either, for a made line, its identifier and the identity of whoever made it, or, for a
> default line, the id of the tool that declares it and no identifier.

> **Normative.** No entry carries a credential, a token or any other secret the hub holds for a
> connection, and no entry says whether its line has covered any call.

How the command line words an entry, and how it lets the owner name a connection, are the
implementing lane's.

### 6. Whose act, and who may call

> **Normative.** No tool, capability or plan step binds any of the four members, no work, model,
> task or upkeep calls one, and no model-authored value becomes an argument to one. No tool makes
> or removes a line in this milestone.

> **Normative.** The four members are classified in ADR-0298 §5:1's command-or-query row, so a
> request from a device without the command role is refused before dispatch (ADR-0298 §5:6).

> **Normative.** A call to `make_grant`, `make_limit` or `remove_line` is the owner's own act
> (ADR-0367 §3:5), and the store records the owner's identity as the maker of every line the
> first two make and the remover of every line the third removes.

> **Normative.** No member lets a person other than the owner make or remove a line.

> **Normative.** No line, level or lowering gates a call to the four members: the
> command-or-query row alone admits one, and the hub's own machine on the local socket reaches
> `permission_lines` and `remove_line` whatever lines stand.

> **Normative.** In this milestone only the `assistant` command line calls the four members.
> ADR-0177 §1:1's enumeration does not gain them, no gateway route or page panel reaches them,
> and neither the Telegram line nor any spoke calls one.

§6:3 rests where ADR-0373 §4:3 rests: every caller of a command-or-query member is the hub's own
machine, which holds every role on the owner-only local socket (ADR-0084 §1, ADR-0298 §3:2), or
a device whose command role only the owner assigns, at the hub (ADR-0298 §4:14), on a device the
owner enrolled there (ADR-0124 §6:1) carrying the owner's single principal (ADR-0124 §5:4). The
lines are not calls a work makes, so ADR-0367 §4:1 does not check them, and a limit the owner
sets cannot keep the owner from removing it. ADR-0367 §3:5 also allows a line made by a checked
call on a person's authority; §6:1 leaves that route unbuilt, so DO-09's "you ask the assistant
to change who may do something" changes nothing in this milestone. The owner's choice of normal
for a tool that "changes a permission" has no tool to apply to until one is added.

### 7. The wire

> **Normative.** The change that adds the four members advances `PROTOCOL_VERSION`, in that same
> change (ADR-0124 §9:2), whether or not another change in the same release also advances it.

The handshake matches the version exactly (ADR-0084 §3), so every `assistant` client and every
gateway on another machine is upgraded with the hub. A gateway calls none of the four, but it
speaks the wire, so its version moves too. No client computes what a line covers.

### 8. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacement on ADR-0298's status line and in a
> dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving ADR-0298's
> ratified body. The replacement takes effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0298 §5:1's table, in the addition alone | Its command-or-query row also names `permission_lines`, `make_grant`, `make_limit` and `remove_line` (§6:2), as ADR-0302, ADR-0332 and ADR-0373 added theirs. No other row changes |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0367 §3:1's "what (an action on a thing)", and §3:4 | The first kinds: one capability (§2:2) and one connection or none (§2:3 to §2:5) |
| ADR-0367 §3:3 | Of its three conditions, one connection on a grant (§2:6) |
| ADR-0367 §3:5, a person's own act | The owner's, by the three acts (§4, §6:3) |
| ADR-0367 §4:3 | A default line's shape (§3:1 to §3:3) |
| ADR-0367 §16's acts bullet, in making and removing lines | §4 |

Read through and standing, each as written: ADR-0367 §3:6 (the store holds the lines people
make; §3:3 reads a default line as its declaration's, as ADR-0367 §4:3, §4:6 and §16 have it);
ADR-0367 §7:6 (with the owner the only person who makes a line, and ADR-0367 §4:2 ruling that a
call a limit covers is not done); ADR-0367 §9:4 (§3:5); ADR-0364 §8:7 (§2:2); ADR-0102 and
ADR-0367 §14 (source grants, which none of the four touches); and ADR-0373 §4 (§6).

### 9. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. A new Protocol ships as a triad.

- **`core/types.py`:** a line, with its who, action, thing, how, bar, condition, kind, identifier
  and maker (ADR-0367 §16's first bullet); the identifier for anyone; a connection's identifier
  (§2:4); the listing's entry (§5:1); and each member's outcome with its closed reasons (§4:10),
  all wire-carried.
- **The store** (ADR-0367 §16's first bullet): members to list the standing made lines, record a
  making, record a removal, and read one line by its identifier, removed or not (§4:8).
- **`ToolDefinition`:** each tool's default grant, its how and its bar (ADR-0367 §16's default
  grants bullet); its who and thing are §3:1's.
- **`AssistantEngine`:** the four members (§4), documented with their outcomes and refusals,
  implemented by the engine and the wire client alike, with conformance tests.
- **The wire:** the four methods in `METHODS` and in the command row of the route table
  (`wire/routes.py`), and `PROTOCOL_VERSION` advanced (§7:1).
- **The command line:** `assistant` commands that list, grant, limit and remove, worded by the
  lane.

### 10. What this decision leaves to others

- **The check (milestone 21's build, under ADR-0367 §4 and §5):** which of several grants that
  cover one call applies, and which one a ruling names (ADR-0367 §4:6).
- **Milestone 5:** lines naming other groups or people; whether a default line to anyone covers a
  call whose thing belongs to someone other than the person it runs for (ADR-0367 §6:1, §6:3);
  powers over lines (ADR-0367 §7).
- **A later decision:** time windows and end dates on a line (ADR-0367 §3:3); a condition on a
  limit; actions naming more than one capability; a call's thing where its wiring, not its
  values, picks its connection; a tool that makes or removes a line (ADR-0367 §3:5); changing or
  removing a default line; and these acts on the web page or any surface but the command line.
- **The change that ships the first default limit:** how it is removed and recorded (§3:5).
- **The owner:** each tool's default how and bar (ADR-0367 §4:4).

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 11. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§2:1 to §2:8:** a who of the owner or anyone; an action of one capability by its name; a
  call's thing derived from its values, today only for the two message tools; a connection named
  by what an `L` label names, the system's own chat as one; a connection condition on a grant
  only; coverage apart from the bar; and a line naming what is gone covering nothing.
- **§3:1 to §3:5:** a default line names anyone and no thing, is its declaration's and not the
  store's, covers only its own tool's calls, and is neither changed nor removed in this
  milestone, which ships no default limit.
- **§4's shapes:** four members and no more; refusals and repeats as outcomes, as ADR-0373 §2
  has them; a removal of nothing not an error; acts that are prospective.
- **§5:** what an entry carries, default lines included.
- **§6:** the four in the command-or-query row as the owner's own acts, on ADR-0373 §4's ground;
  no tool makes a line; the hub's own machine always reaches the listing and the removal.

## Consequences

- The line store's lane can type a line, and the check can say which lines cover a call, with
  nothing left to guess about what a line names.
- The owner sees every line that stands, the tools' defaults among them, and makes and removes
  their own from the command line; no model and no message can do either.
- DO-02's limit on one account is one line naming that account, and WORK-14's grant through one
  connection is one line naming it as its condition.
- A default line is changed only by a new build, and the owner overrides one by a line of their
  own rather than by removing it.
- Every client and gateway upgrades with the hub at the version bump.
- **Revisit** when a second person may make lines, when a call's thing is picked by its wiring,
  or when the owner needs to remove a default line.

## Alternatives considered

- **A line names a tool by its id, or by its declaration.** Set aside: a declaration's value
  changes with any description, which would end every line naming it (ADR-0364 §8:7), and one
  capability may be served by several tools, such as one per email account (ADR-0148 §6).
- **A connection as a call's thing wherever the call reaches one.** Set aside for this milestone:
  for `search_web`, `read_forecast` and the booking calls nothing in the call names it, and a line
  by action already covers them; it is left to a later decision (§10).
- **Default lines stored and removable.** Set aside: their bars are the build's declaration, a
  stored copy would drift from it, and an owner's limit or grant already narrows or widens one.
  DO-16 waits on the first shipped limit (§3:5).
- **One member making either kind of line.** Set aside: a limit has no how and no bar (ADR-0367
  §3:2), and two members keep each argument list exactly what its kind holds.
- **A tool that makes lines now.** Set aside: no acceptance row needs one, and the command line
  is the owner's chosen surface.
