# 379. A limit that covers a call decides it, otherwise the grants that apply at its level decide it alike, and a ruling names the made grant it rests on

- Status: Proposed
- Date: 2026-11-24
- Scope: decision D4 of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)). It decides what
  [ADR-0376](0376-a-line-names-the-owner-or-anyone-one-capability-and-at-most-one-connection-and-the-owner-lists-makes-and-removes-lines-through-four-engine-members.md)
  §10 leaves to the check: the check's outcome for one call, one person and one level, given the
  lines that cover the call (§2); the closed set of those outcomes (§3); and which line a ruling
  names (§4). §5 says what the owner cannot do with lines as they are, §6 records what it does to
  earlier decisions, §7 the contract changes it would need, §8 what it leaves to others, and §9
  what it settled where the rulings left a point open.
- Authorization: the owner's words, verbatim, both of 2026-11-24: "yes agreed, but its milestone
  21 right, not 2", to the scope as #3678 records it, put with six picks of the coordinator's (the
  default grants and "anyone" among them, as #3678 has them), which that answer accepted and
  nothing more; and "Yes, go", to "Shall I post the batch issue and start D1, D2, D3 and B1". The
  owner has ruled nothing about which line decides a call: every rule below is this decision's
  (§9). The coordinator assigned 0379 and ratifies it, under the owner's delegation, once its
  reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides what `PermissionRuling.authorised_by` names, so it takes the adversarial and
  the architecture review. It supersedes nothing.

## Context

[ADR-0367](0367-grants-say-who-may-do-what-and-how-sure-the-hub-must-be-every-call-is-checked-against-them-and-powers-are-handed-on-in-part.md)
gives the pieces of the check's outcome but not the rule that joins them. A call that no grant
covers, or that a limit covers, is not done (§4:2). A grant applies only at or above its bar
(§5:1), and one to a named person only at weak or above (§5:2). Where a grant would cover a call
but for its bar, the call needs a yes (§5:3). A call covered only by a grant that allows with
approval needs the yes of its thing's person (§5:6). A grant a person set that allows names
itself in `PermissionRuling.authorised_by`, and a default grant names nothing, so ADR-0021 §5's
floor still asks about a disclosing call only a default allows (§4:6). Between one person's lines,
a limit holds over a grant (§7:6).

ADR-0376 §2:7 says when a line covers a call, apart from its bar, and §10 leaves to the check
"which of several grants that cover one call applies, and which one a ruling names". Several lines
covering one call is the ordinary case: every tool has a default line to anyone (ADR-0376 §3:1),
and the owner's grant or limit sits beside it. A default line is no person's and names nothing in
a ruling (ADR-0376 §3:1, §3:3). In this milestone the owner makes every made line (ADR-0376 §6:3,
§6:4). [ADR-0377](0377-a-cards-tap-and-the-lines-stop-are-read-through-the-link-they-arrived-by-a-tap-answers-only-at-the-level-its-call-needs-and-an-answer-records-who-tapped-and-how-sure.md)
§3:2 already reads a card's level for every card but a shortfall's as "the least level at which
the check ... finds a grant covering the request's call", and a shortfall's as "the grant's bar".

**Words.** A **line**, **grant**, **limit**, **bar**, **level**, **anyone**, **the check**,
**card** and **yes** are ADR-0367's; **covers**, **default line** and **made line** are
ADR-0376's. A grant **applies** at a level where ADR-0367 §5:1 and §5:2 both let it. A grant
**allows** where its how is allowed, and **asks** where its how is allowed with approval. A bare
section reference, such as §2:3, is to this decision's own clauses.

## Decision

We will have a covering limit decide a call; otherwise weigh every grant that applies at the level
alike, default or made, the most permissive deciding; turn a call that grants cover but none at
its level into a shortfall at the least level at which one would apply; and have a ruling name a
made grant that allows, never a default.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** Until the check is built, nothing in this decision changes what the running hub
> allows, asks, shows or records.

> **Normative.** This decision rules the check's outcome for one call, one person and one level,
> and only where every made line is the owner's. Where a person other than the owner may make a
> line, a later decision says how §2 stands with ADR-0367 §7:6's order between people.

### 2. Which line decides

> **Normative.** The check's outcome for a call is decided by the lines that cover it (ADR-0376
> §2:7) and the level, by §2:2 to §2:6 in that order, the first that applies deciding.

> **Normative.** Where a limit covers the call, the outcome is *not done: a limit covers it*,
> whatever grants also cover it.

> **Normative.** Otherwise, where a grant that allows applies, the outcome is *allowed*, even where
> a grant that asks also applies: *resting on a made grant* where a made grant that allows
> applies, and *on no line* where only default lines allow.

> **Normative.** Otherwise, where a grant that asks applies, the outcome is *needs a yes: a grant
> allows with approval* (ADR-0367 §5:6).

> **Normative.** Otherwise, where a grant covers the call and none applies at the level, the
> outcome is *needs a yes: a shortfall*, carrying as its bar the least level at which one of the
> covering grants would apply under ADR-0367 §5:1 and §5:2, a grant that asks counted alike.

> **Normative.** Otherwise the outcome is *not done: no grant covers it*.

> **Normative.** A default line and a made grant are weighed alike in §2:3 to §2:5. They differ
> only in what an outcome names (§2:8, §4).

> **Normative.** Where an outcome names a line and several qualify, it names the one whose making
> the store recorded first, and of two recorded at the same moment the one whose identifier sorts
> first, so the same standing lines always name the same line.

> **Normative.** A grant that covers the call but does not apply at the level bears on the outcome
> only under §2:5: it never makes a call that another grant decides under §2:3 or §2:4 need a yes.

ADR-0367 §5:3's "a shortfall is not a refusal" is read as the case where, but for the bar, the
call would otherwise not be done: a grant falling short beside one that applies changes nothing
(§2:9). A named grant whose bar is none would apply at weak (ADR-0367 §5:2), so §2:5's bar is never
below weak, and agrees with ADR-0377 §3:2's "weak where that level is none".

### 3. The outcomes

> **Normative.** The check's outcome is exactly one of six, and no other: *allowed, on no line*;
> *allowed, resting on a made grant*, carrying that grant's identifier; *needs a yes: a
> shortfall*, carrying its bar; *needs a yes: a grant allows with approval*; *not done: a limit
> covers it*, carrying, where a made limit covers the call, the identifier of one, chosen as §2:8
> has it; and *not done: no grant covers it*.

> **Normative.** Every call the check checks gets one outcome, and the check's record of a call
> carries it whole, whether the check decides or is recorded beside today's rules.

> **Normative.** Each outcome is turned into what ADR-0367 §4 and §5 and ADR-0368 §7 rule for it,
> and into nothing they do not rule. An allowed outcome is the check's alone: the call still passes
> every other check (ADR-0367 §4:5).

What those clauses make of each:

| Outcome | What it becomes |
| --- | --- |
| Allowed, on no line | The check allows, and gives a ruling no line to name (§4:1) |
| Allowed, resting on a made grant | The check allows, and a ruling that names a line names that grant (§4:1, ADR-0367 §4:6) |
| Needs a yes: a shortfall | A card at its bar, to the person whose authority the work carries (ADR-0367 §5:3, §5:4); in a work that is not a person's, not done (ADR-0368 §7:4) |
| Needs a yes: a grant allows with approval | The yes of whoever the call's thing belongs to (ADR-0367 §5:6); in a work that is not a person's, not done (ADR-0368 §7:4) |
| Not done: a limit covers it | Not done, with its reason, asking no one (ADR-0367 §4:2) |
| Not done: no grant covers it | Not done, with its reason, asking no one (ADR-0367 §4:2) |

Three worked calls, each for the owner, with the default line for `send_email` naming anyone, its
how allowed and its bar normal (#3678's "anything that leaves the system: normal"). At normal, under
the default alone, the outcome is *allowed, on no line*; `send_email` discloses, so ADR-0021 §5's
floor still sends it to the owner's yes, as today. At normal with the owner's own grant for
`send_email`, allowed at normal, the outcome is *allowed, resting on* that grant; the floor is met,
and whether the policy's other rules still ask is the policy's (ADR-0306 §4:2). At weak with the
owner's limit on account A, a call whose `from` names A is *not done: a limit covers it*, with no
card; one from account B is *needs a yes: a shortfall* at normal, because the default covers it and
does not apply at weak.

### 4. What a ruling names

> **Normative.** The line a call rests on, in ADR-0367 §4:6 and §16, is the made grant the check's
> outcome names, and there is none where the outcome is any other. A ruling whose
> `PermissionRuling.authorised_by` names a line names that grant (ADR-0376 §3:3).

> **Normative.** A made grant that asks is never named, though it applies, and a default line is
> never named, though it allows.

So, where the owner's grant and a default both allow, the ruling names the owner's grant, and
ADR-0021 §5's floor permits, without requiring, an `ALLOW` for a disclosing call. Where only a
default allows, the floor still sends a disclosing call to the person's yes.

### 5. What the owner cannot do with lines as they are

A grant only adds and a limit only forbids (ADR-0367 §7:7). With §2, the owner can forbid a call
outright with a limit, or allow more with a grant of their own, but cannot make a call that a
default allows at the level need more: not a higher bar, and not a yes. A grant of the owner's that
asks, beside a default that allows at the same level, changes nothing (§2:3). Raising a default's
bar, or making it ask, waits on changing a default line
([#3684](https://github.com/leonapivato/ai-assistant/issues/3684)), which this decision does not
decide.

### 6. Relationship to earlier decisions

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0376 §10, the check's first bullet | §2 and §4 |
| ADR-0367 §4:2, §5:1 to §5:3 and §5:6 | Joined in one order (§2:1 to §2:6), §5:3 read as §2:9 has it |
| ADR-0367 §4:6 | Which made grant a ruling names (§2:8, §4) |
| ADR-0367 §7:6's last sentence | A limit holds over a grant: over the owner's and a default line alike (§2:2) |
| ADR-0377 §3:2, "the grant's bar" of a shortfall's card | The bar §2:5 carries |

Read through and standing, each as written: ADR-0367 §3:7, so no outcome's line or bar is shown to
a model; ADR-0367 §4:5 and ADR-0306 §4:1 to §4:2, the other checks and the policy; ADR-0368 §7, who
the check runs for and at what level, a work with no authority holding no grant; ADR-0021 §5's
floor; and ADR-0247 §2's route for a search at the configured provider.

### 7. The contract changes building it would need

None of its own. The check's outcome, where it crosses a subsystem boundary, is a value in
`core/types.py` with §3:1's six members, and the line a call rests on reaches the policy on
`ActionRequest`, as ADR-0367 §16 names. Both are the building lane's, made by none of this decision.

### 8. What this decision leaves to others

- **ADR-0368 §7:3:** how the outcomes for several senders join.
- **A later decision, with milestone 5:** how §2 stands with ADR-0367 §7:6 where lines are set by
  different people (§1:3).
- **#3684:** changing or removing a default line, and so raising its bar.
- **The building lane, under ADR-0247 §2 and ADR-0021 §3:** what `authorised_by` names where the
  policy's route at the configured provider and a made grant both support an `ALLOW`.
- **ADR-0367 §5:4, §5:5 and ADR-0377:** where a card is shown, when a tap answers, and how a call
  run under a ticket is checked.
- **The next prompt review:** how each outcome is worded to a model (ADR-0367 §3:7).

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 9. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3:** the rule holds while the owner makes every made line.
- **§2:1, §2:2:** a covering limit decides first, whatever grants cover.
- **§2:3, §2:4, §2:7:** the grants that apply are weighed alike, default or made, and the most
  permissive decides.
- **§2:5, §2:9:** a shortfall arises only where no covering grant applies, at the least level at
  which one would, a grant that asks counted.
- **§2:8:** the earliest-made line is named among several.
- **§3:** the six outcomes, and the record carrying them whole.
- **§4:2:** a made grant that asks is never named.

## Consequences

- The check has one outcome for every call, which its build records beside today's rules and later
  turns into what ADR-0367 rules, with nothing left to guess.
- A grant the owner makes can only widen what defaults allow, and a limit always holds.
- A disclosing call stops asking only where the owner's own grant allows it.
- **Revisit** when a second person may make lines, or when a default line can be changed.

## Alternatives considered

- **The least permissive applying grant decides.** Set aside: it would let a default that asks undo
  a grant the owner made to stop asking, and ADR-0367 §5:6 asks for a yes only of a call covered
  *only* by a grant that asks.
- **A made grant outranks a default.** Set aside: a default is "a line like any other" (ADR-0367
  §4:3), and weighing them alike keeps the outcome a function of the lines alone. What a ruling
  names is the only place the two differ (§4).
- **Any covering grant that falls short makes a shortfall.** Set aside: it would ask for a yes on a
  call another grant allows at the level, and so make a grant that falls short take away, which only
  a limit does (ADR-0367 §7:7).
- **A shortfall's bar is the highest among the covering grants.** Set aside: ADR-0377 §3:2 already
  reads the least level for every other card, and a yes at the least such level is one a covering
  grant already accepts.
