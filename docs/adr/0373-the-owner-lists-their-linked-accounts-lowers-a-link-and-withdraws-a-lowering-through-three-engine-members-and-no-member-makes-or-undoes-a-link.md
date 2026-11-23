# 373. The owner lists their linked accounts, lowers a link and withdraws a lowering through three engine members, and no member makes or undoes a link

- Status: Proposed
- Date: 2026-11-23
- Scope: the contract lane of milestone 20, "The hub knows who is speaking" (acceptance
  [#3642](https://github.com/leonapivato/ai-assistant/issues/3642), lanes
  [#3643](https://github.com/leonapivato/ai-assistant/issues/3643)). It decides what
  `AssistantEngine` and the wire gain so the owner can see their links and lower them by their
  own act, under
  [ADR-0366](0366-a-person-is-one-identity-the-hub-links-accounts-to-code-decides-who-sent-an-input-and-how-sure-it-is-and-a-persons-label-holds-for-one-work.md)
  §2:1, §3:1 to §3:3, §5:3 and §5:5: the three members (§2), what the listing shows (§3), whose
  act they are and who may call them (§4), the path that always withdraws a lowering (§5), how a
  link is made in this milestone (§6) and the wire (§7). §8 records what it does to earlier
  decisions, §9 names the contract changes it would need, §10 what it leaves to others, and §11
  what it settled where the rulings left a point open.
- Authorization: the owner's words, verbatim, all of 2026-11-23: "can we make a plan for
  implemented our decisions?"; "Yes, scope milestone 1", to "Do you accept the five-milestone order
  for the build plan?"; "looks good, any questions for me before starting?", on milestone 20's
  scope as the coordinator set it out; and "yes to all three, go ahead and create it", to three
  questions the coordinator asked, each with a pick: build the four levels now as ADR-0366 §5 has
  them (pick: yes); linked accounts are managed from the `assistant` command line only for now
  (pick: yes); and the coordinator's session stays the only one that dispatches (pick: yes). The
  last answer accepted those three picks and nothing more. The coordinator assigned 0373 and
  ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides members of `AssistantEngine`, the promoted surface the wire carries, so it
  takes the adversarial and the architecture review. Building it is a breaking change under golden
  rule 5, through the changes §9 names, none of which is made here.
- **Partially supersedes**
  [ADR-0298](0298-the-gateway-names-a-browser-device-on-each-request-and-the-hub-checks-every-request-by-one-table.md)
  (§5:1's table, in the addition alone: the three members in the command-or-query row), as §8
  records.

## Context

ADR-0366 made a person one identity with the accounts linked to it (§2:1), had code decide who
sent an input from the link it arrived by (§4:1), and gave every link a level: its kind's declared
most, or the lowest any standing lowering sets (§5:3). "The owner, or the person a link
identifies, may lower that link's level. Each lowering stands until whoever made it withdraws it"
(§5:5). Only the owner links, and only to the owner's own identity (§3:3, held by ADR-0367 §1:5).
No model links, sets or lowers a level (§3:2, §5:7). ADR-0366 §11 names the store for identities
and links that the build adds; milestone 20 builds it, and acceptance #3642 asks that the owner
list their linked accounts, lower the Telegram link and withdraw the lowering, from the
`assistant` command line.

**The surface today.** `AssistantEngine` (`core/protocols.py`) has no member for links or levels.
Its members that are the owner's own acts, such as `guard`, `revoke`, `set_profile_field` and
`tap_approval`, take no caller argument: every member of ADR-0298 §5:1's command-or-query row is
reached only by the hub's own machine, which holds every role on the owner-only local socket
(ADR-0084 §1, ADR-0298 §3:2), or by a device holding the command role, which only the owner
assigns, at the hub (ADR-0298 §4:14), on a device enrolled by the owner's act at the hub
(ADR-0124 §6:1) that carries the owner's single principal (ADR-0124 §5:4). A browser request
reaches only the operations ADR-0177 §1:1 enumerates. ADR-0151 §13:1 already keeps the connection
operations from every tool, plan step and model-authored argument.

**Today's acts that name an account as the owner's.** Setting `telegram_user_id` is the user's act
that creates the line (ADR-0323 §3:3); in relayed mode that act is the person's link at the relay,
which the setting carries out (ADR-0330 §11:4). A device is enrolled only by the owner's explicit
act at the hub (ADR-0124 §6:1). A hosted hub configures its person's account at the edge as
`gateway_edge_subject` (ADR-0327 §13:1).

**Words.** A **link**, a **kind**, a **level** and an **identity** are ADR-0366's. A **lowering**
is one act under ADR-0366 §5:5, standing on one link until withdrawn. The **store** is the store
for identities and links ADR-0366 §11's first bullet names. The **owner's identity** is the one
ADR-0345 §2:5's identifier names (ADR-0366 §2:5). A bare section reference, such as §4:2, is to
this decision's own clauses.

## Decision

We will give `AssistantEngine` three members, one listing every link with its level and the
lowerings that stand on it, one lowering a link and one withdrawing a lowering; place them in the
command-or-query row, so every call to them is the owner's own act; keep them from every model,
work and page; give no member that makes or undoes a link; and advance the protocol version.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** Until the three members are built, nothing in this decision changes what the
> running hub allows, asks, shows or records.

> **Normative.** This decision admits no one, gives no person other than the owner any act, and
> is not among the provisions ADR-0365 §1:3 and ADR-0367 §1:4 name for admitting another person.

The lane #3643 names L3 builds it, after this decision merges and after the store is built.

### 2. The three members

> **Normative.** `AssistantEngine` gains exactly three members for links and levels:
> `linked_accounts`, `lower_link` and `withdraw_lowering`, and no other.

> **Normative.** `linked_accounts` takes no argument and is not paged. It returns every link to
> the owner's identity, as one entry each (§3), in no contractual order, complete or refused with
> `OversizedValueError` and never truncated, as `connected_accounts` is (ADR-0139 §2).

> **Normative.** `lower_link` takes a link's identifier as its positional subject and a `level`,
> one of ADR-0366 §5:1's four, as a keyword-only argument with no default. It records a lowering
> at that level, standing on that link and made by the owner (§4:3), and returns the outcome
> `lowered` with the lowering it recorded and the link's entry as it stands after the act.

> **Normative.** `lower_link` writes nothing and returns the outcome `refused`, with the reason
> `unknown_link`, where no link to the owner's identity has that identifier, and with the reason
> `not_a_lowering`, where the level is not below the link's kind's declared most (ADR-0366 §5:2,
> §5:3).

> **Normative.** Where a lowering the owner made at that level already stands on that link,
> `lower_link` writes nothing and returns the outcome `unchanged`, with that lowering and the
> link's entry, so repeating the call makes no second lowering.

> **Normative.** `withdraw_lowering` takes a lowering's identifier as its positional subject. It
> ends that lowering and returns the outcome `withdrawn` with the link's entry as it stands after
> the act; where no standing lowering has that identifier, because none was made or it was
> already withdrawn, it writes nothing and returns the outcome `not_standing`, which is not an
> error.

> **Normative.** A blank identifier, and a `level` that is not one of the four, are refused with
> `ValueError` before any I/O, as `AssistantEngine`'s clauses 2 and 4 rule for every member. A
> store that cannot be read or written raises the error the store's contract declares for that,
> and every refusal of an act is an outcome the member returns, never an error.

> **Normative.** The store gives each link and each lowering a stable identifier, never reused,
> and the three members name links and lowerings by these identifiers alone.

> **Normative.** A lowering or a withdrawal bears only on the level of inputs that arrive by the
> link after it is recorded. It changes no level an input already records (ADR-0368 §2:6), no fact
> a work already records (ADR-0368 §2:4) and no task's recorded level (ADR-0368 §6:3).

> **Normative.** Each value the three members take or return is a frozen pydantic model or an
> enumeration in `core/types.py`, reachable from the surface (ADR-0084 §4, ADR-0085 §5), and its
> outcomes and reasons are closed sets of exactly the members this section names.

The type names are the implementing lane's. A refused or repeated act is an outcome rather than an
error for the reason `PersonModelStoreError`'s documentation gives: a refusal is not a fault.

### 3. What the listing shows

> **Normative.** Each entry of `linked_accounts` carries the link's identifier, the identity it
> ties to, its kind, the account identifier the link holds, its kind's declared most as the
> running build declares it, each lowering standing on it with that lowering's identifier, its
> level and the identity of whoever made it, and the level that results under ADR-0366 §5:3.

> **Normative.** The hub computes each entry's resulting level, and no client computes or
> recomputes it.

> **Normative.** No entry carries a credential, an enrolment's verifier, a token, or any other
> secret the hub holds for an account or a connection.

> **Normative.** An entry shows only the lowerings that stand. Whether the store keeps a withdrawn
> lowering is the build's.

A kind with no declaration gives none (ADR-0366 §5:2), so its entry shows none as its most and as
its level. How the command line words an entry is the implementing lane's.

### 4. Whose act, and who may call

> **Normative.** No tool, capability or plan step binds any of the three members, no work, model,
> task or upkeep calls one, and no model-authored value becomes an argument to one.

> **Normative.** The three members are classified in ADR-0298 §5:1's command-or-query row, so a
> request from a device without the command role is refused before dispatch (ADR-0298 §5:6).

> **Normative.** A call to `lower_link` or `withdraw_lowering` is the owner's own act (ADR-0366
> §3:1, §5:5), and the store records the owner's identity as the maker of every lowering
> `lower_link` makes.

> **Normative.** No member lets a person other than the owner lower a link or withdraw a lowering.

Every lowering is the owner's (§4:3), so `withdraw_lowering` meets ADR-0366 §5:5's second sentence
for every lowering it can name without a check of its own. The decision that lets another person
lower a link says how a withdrawal checks its maker.

> **Normative.** No level, lowering or link gates a call to the three members: the
> command-or-query row alone admits one.

> **Normative.** In this milestone only the `assistant` command line calls the three members.
> ADR-0177 §1:1's enumeration does not gain them, no gateway route or page panel reaches them,
> and neither the Telegram line nor any spoke calls one.

§4:3 rests on the decisions the surface's other acts rest on, named in the Context: every caller
of a command-or-query member is the hub's own machine or a device whose command role the owner
gave it, at the hub. On a hub hosted for a person, the operator holds the box, and what keeps the
operator from acting as that person is the operator's terms, not a mechanism (ADR-0327 §13). These
members change nothing in that.

### 5. A lowering can always be withdrawn

> **Normative.** The hub's own machine, on the local socket, reaches `linked_accounts` and
> `withdraw_lowering` whatever level any link stands at, and no lowering changes that.

The hub's own machine holds every role there (ADR-0298 §3:2) and is never enrolled or registered
(ADR-0298 §3:4), so it is reached by no link a lowering stands on, and §4:5 keeps every level off
the route. Once the readers take the sender from the link, a link lowered to none makes what
arrives by it an unidentified sender's (ADR-0366 §5:3, §5:6; ADR-0368 §9:4): the Telegram line,
lowered to none, can no longer ask the assistant for anything as the owner. Nothing is meant to be
asked of the assistant here, since no model lowers or raises a level (ADR-0366 §5:7). The command
line is the path, and an enrolled device with the command role reaches it too, whatever its own
link's level.

### 6. Making and undoing a link

> **Normative.** No member of `AssistantEngine` makes or undoes a link, adds or removes an account
> identifier, or changes the identity a link ties to.

> **Normative.** Until a later decision adds an act that makes a link, a link is recorded only
> from an act the owner has made under a ratified decision that names an account or a device as
> the owner's, such as setting `telegram_user_id` (ADR-0323 §3:3, ADR-0330 §11:4), enrolling a
> device (ADR-0124 §6:1) or configuring `gateway_edge_subject` (ADR-0327 §13:1), and only to the
> owner's identity (ADR-0366 §3:3).

> **Normative.** A link recorded from such an act stands only while the act it was recorded from
> stands: once its setting names another account or none, or its device's enrolment is revoked,
> the link no longer stands and nothing arrives by it.

Which of these acts the store records as links, under which kind, and how it follows them, is the
build's under ADR-0366 §11. So the owner links no account by a new act in this milestone: the acts
that name their accounts today are the linking acts. Who may undo a link in general is ADR-0367
§7:10's.

### 7. The wire

> **Normative.** The change that adds the three members advances `PROTOCOL_VERSION`, in that same
> change (ADR-0124 §9:2), whether or not another change in the same release also advances it.

The handshake matches the version exactly (ADR-0084 §3), so every `assistant` client and every
gateway on another machine is upgraded with the hub, as for every earlier bump. A gateway calls
none of the three, but it speaks the wire, so its version moves too.

### 8. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacement on ADR-0298's status line and in a
> dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving ADR-0298's
> ratified body. The replacement takes effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0298 §5:1's table, in the addition alone | Its command-or-query row also names `linked_accounts`, `lower_link` and `withdraw_lowering` (§4:2), as ADR-0302 and ADR-0332 added theirs. No other row changes |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0366 §5:5's first sentence | The owner's lowering, by `lower_link` (§2:3, §4:3) |
| ADR-0366 §5:5's second sentence | The withdrawal, by `withdraw_lowering`, of a lowering the owner made (§2:6, §4:4) |
| ADR-0366 §2:1 and §5:3 | What a listing shows: the account a link holds and the level that results (§3) |
| ADR-0366 §3:1 to §3:3 | No member links (§6:1); a link is recorded only from the owner's own act, to the owner (§6:2) |

Read through and standing, each as written: ADR-0151 §13 (the connection operations, which are not
links); ADR-0177 §1:1 (which gains nothing, §4:6); and ADR-0367 §7:10 (who may undo a link).

### 9. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. A new Protocol ships as a triad.

- **`AssistantEngine`:** the three members (§2), documented with their outcomes and refusals,
  implemented by the engine and the wire client alike, with conformance tests.
- **`core/types.py`:** the listing's entry, a standing lowering as the entry shows it, and each
  member's outcome with its closed reasons (§2:10), all wire-carried.
- **The store:** members to list the owner's links, record a lowering with its maker and end one,
  with stable identifiers (§2:8). Where the store's Protocol lacks one, it is added under
  ADR-0366 §11's first bullet.
- **The wire:** the three methods in `METHODS` and in the command row of the route table
  (`wire/routes.py`), and `PROTOCOL_VERSION` advanced (§7:1).
- **The command line:** `assistant` commands that list, lower and withdraw, worded by the lane.

### 10. What this decision leaves to others

- **ADR-0367 and the decisions it waits on:** who holds the power to link, who may undo a link,
  what a level permits, and any act for a person other than the owner.
- **The build of the store (ADR-0366 §11):** which of today's acts it records as links, under
  which kind, and whether it keeps a withdrawn lowering.
- **A later decision:** an act that makes a link, a link suggested by the system (ADR-0366 §3:2),
  views and merges (ADR-0366 §7), and these acts on the web page or any surface but the command
  line.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 11. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§2's shapes:** three members and no more; a lowering below the kind's most only; a repeated
  lowering unchanged; a withdrawal of nothing not an error; refusals as outcomes.
- **§2:8**, stable identifiers for links and lowerings, which the store's build provides.
- **§2:9**, that an act is prospective.
- **§3**, what an entry carries, and that the hub computes its level.
- **§4:3 and §4:4**, that a call through the command-or-query row is the owner's own act, and that
  the maker check waits for a second person who can lower.
- **§4:5 and §5:1**, that no level gates these members and the hub's own machine always reaches
  them.
- **§6:2 and §6:3**, that today's acts naming the owner's accounts are the linking acts, and that
  a link stands only while its act does.
- **§8's supersession** of ADR-0298 §5:1's table, in the addition, following ADR-0302 and ADR-0332.

## Consequences

- The owner sees every account linked to them with its level and the lowerings on it, and lowers
  or restores a link from the command line, with no model and no message able to do either.
- Nothing about who may act at the surface changes: the three members ride the same row and the
  same ground as every other act of the owner's there.
- A Telegram link lowered to none stops the line counting as the owner once the readers switch,
  and the hub's own machine always undoes it.
- Every client and gateway upgrades with the hub at the version bump.
- **Revisit** when a second person may lower a link, when a level comes to bear on an act at this
  surface, or when the web page is to manage links.

## Alternatives considered

- **A member that links an account.** Set aside: today's acts already name every account the
  owner has, and a new linking act is a decision about the power to link, which is ADR-0367's.
- **Lowering by setting a link's level directly.** Set aside: ADR-0366 §5:5 makes each lowering
  its own act standing until its maker withdraws it, so a single settable value would lose who
  made which.
- **Unknown links and lowerings as errors.** Set aside: a refused or repeated act is not a fault,
  and an error would make a repeated withdrawal fail.
- **The listing on the web page now.** Set aside by the owner's pick: the command line only, for
  now.
