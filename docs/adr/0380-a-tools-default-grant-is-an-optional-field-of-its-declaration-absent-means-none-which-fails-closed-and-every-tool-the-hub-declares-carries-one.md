# 380. A tool's default grant is an optional field of its declaration: absent means none, which fails closed, and every tool the hub declares carries one

- Status: Accepted
- Date: 2026-11-24
- Scope: decision D5 of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)). It decides whether the default
  grant [ADR-0367](0367-grants-say-who-may-do-what-and-how-sure-the-hub-must-be-every-call-is-checked-against-them-and-powers-are-handed-on-in-part.md)
  §4:3 and §16 put on `ToolDefinition` is required, what its absence means (§2), how a declaration
  recorded before it reads (§3), and what holds every tool to §4:3 (§4). §5 records what it does to
  earlier decisions and §6 what it leaves to others.
- Authorization: the coordinator's ruling, not the owner's. Build lane B2 weighed three shapes:
  optional and absent by default; required but nullable, with an upgrade writing null into three
  stores; required and never null. The coordinator ruled the first. The owner has ruled nothing
  here; #3678 records, of the scope the owner agreed, "Every tool declares a default grant where it
  is declared (§4:3)". The coordinator assigned 0380 and ratifies it, under the owner's delegation,
  once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides the presence rule of a field the build adds to `ToolDefinition`, so it takes
  the adversarial and the architecture review.
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md) (§1's `ToolDefinition`
  field list, in the addition of the default grant alone, and its required-field clause, in the
  application to that one field alone; §5:1).

## Context

ADR-0016 §1 reads "Every field that a permission decision depends on is required", and the check
reads a tool's default grant. But a `ToolDefinition` is stored by value in records written before
the field exists: `PermissionDecision.tool` in the audit trail, `RequestedCall.tool` in the plan
store's approval requests, and `AskedCall.tool` in an `EpisodeProcessingRecord`'s rounds. A
required field would refuse every one of them, and no upgrade can give an old record a true value:
no default grant existed when it was written. ADR-0306 §2:2 could make five fields required with no
default because ADR-0306 §6:7 read no earlier record; ADR-0326 §3:4 now leaves a fresh data
directory to the owner alone.

Five fields met this before, each by a scoped partial supersession of ADR-0016 §1: ADR-0254
(`system_supplied`), ADR-0266 (`bounded_arguments`), ADR-0267 (`quoted_output`), ADR-0262
(`postconditions`) and ADR-0271 (`charged_output`). Each takes its exception on its own ground, and
ADR-0016's header says no lane reads them as licence to default another. Neither ADR-0367 nor
[ADR-0376](0376-a-line-names-the-owner-or-anyone-one-capability-and-at-most-one-connection-and-the-owner-lists-makes-and-removes-lines-through-four-engine-members.md)
says whether this one is required.

**Words.** A **line**, **grant**, **limit**, **bar** and **the check** are ADR-0367's; **covers**,
**default line** and a tool the running hub **declares** are ADR-0376's. A bare section reference,
such as §2:1, is to this decision's own clauses.

## Decision

We will make the default grant an optional field of `ToolDefinition` whose absence means the
declaration has no default grant, take that as one further scoped exception to ADR-0016 §1 on the
ground that it fails closed, and hold every tool the running hub declares to carry one by a test.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules only whether the default grant is present on a declaration
> and what its absence means. The field's name and type, each tool's value and the wire version
> are the building lane's; what a line names and which line decides are ADR-0376's and
> [ADR-0379](0379-a-limit-that-covers-a-call-decides-it-otherwise-the-grants-that-apply-at-its-level-decide-it-alike-and-a-ruling-names-the-made-grant-it-rests-on.md)'s.

### 2. Absent means none, and none fails closed

> **Normative.** `ToolDefinition`'s default grant is optional and absent by default. It is not
> required, and its absence is not read as any how or any bar.

> **Normative.** A declaration with no default grant has no default line. The check adds no line
> of its own to those that cover a call through it, and `permission_lines` lists none for it
> (ADR-0376 §4:2, §5:1).

The ground is that absence can only refuse. With no default line, a call through that tool is
covered only by a grant a person made; where none covers it, ADR-0379 §2:6 decides it *not done:
no grant covers it* and ADR-0367 §4:2 asks no one. Where a default would have covered it at a bar
the level falls short of, absence turns ADR-0379 §2:5's card into that refusal. Nothing in ADR-0376
§3 or ADR-0379 §2 reads an absent default as a line: each reads a default line only where a
declaration gives one. So an absent value can cost a refusal or a card, and can never authorise a
call: the direction ADR-0016 §1 exists to protect, the ground ADR-0267 took for its field.

> **Normative.** §2:1 to §2:2 reach a default grant alone. A change that lets a declaration carry
> a default limit (ADR-0376 §3:5) takes no part of this decision's exception, since a limit's
> absence widens what is allowed.

### 3. A declaration recorded before the field

> **Normative.** A `ToolDefinition` encoded before the field existed, stored or on the wire,
> decodes unchanged as one with no default grant.

> **Normative.** Each store holding a `ToolDefinition` by value reads its earlier records
> unchanged: its upgrade is empty and its label stays, and the change that adds the field still
> ships, for each such store, the test ADR-0326 §4:2 owes against a file the previous release
> wrote.

> **Normative.** The check reads the default grant of the declaration the running hub declares
> for a call, and never the absence in one an earlier record holds. Such a record is a record of a
> past ruling, question or request.

### 4. What holds every tool to ADR-0367 §4:3

> **Normative.** Every declaration of a tool the running hub declares, in the tool registry or
> among orchestration's own calls, carries a default grant.

> **Normative.** The change that adds the field ships a test that fails where any such declaration
> has none, so a later change adding a tool without one fails the gate.

So ADR-0367 §4:3's "No tool is outside the check" is held by §4:1 and its test, and is not left to
what an absent field means.

### 5. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0016 §1 in one scope: its `ToolDefinition`
> field list, in the addition of the default grant alone, and its required-field clause, in the
> application to that one field alone, as a sixth recorded exception taken on §2's fail-closed
> ground. Every other field a permission decision depends on stays required with no default,
> every other clause of ADR-0016 binds entire, and no lane reads this record, alone or with the
> five before it, as licence to default another safety field.

| Clause | What this decision does |
| --- | --- |
| ADR-0016 §1 | Partially supersedes it, in §5:1's scope alone |
| ADR-0367 §4:3, §16's default-grants bullet | Takes them: the field may be absent on a record, never on a tool the hub declares (§4) |
| ADR-0376 §3:1, §4:2, §5:1 | Read through: a default line exists only where a declaration gives one (§2:2) |
| ADR-0379 §2:5, §2:6 | Read through: no default line leaves a refusal or a card, never an allow |
| ADR-0326 §4:1, §4:2 | Takes them: an empty upgrade, and the test still owed (§3:2) |

### 6. What this decision leaves to others

- **Build lane B2:** the field's name and type, each tool's value, the test's form, whether the
  registry also refuses a declaration with none, and the `PROTOCOL_VERSION` advance (ADR-0124 §9:2).
- **#3684:** changing or removing a default line.
- **The change that ships the first default limit:** how it is carried (§2:3).

## Consequences

- No stored record is refused, and no store needs a conversion its records cannot honestly carry.
- A fixture that does not exercise the check may declare a tool with no default grant; the running
  hub may not.
- An approval request recorded before the field holds a declaration unequal to the one the hub then
  declares. Today `AuthorizingStage._rebuilt` runs a ticket only where the registry still offers the
  declaration its card showed, so such a ticket is not run and the person asks again, as after any
  declaration edit.
- **Revisit** if a default line can be changed (#3684), or a declaration can carry a default limit.

## Alternatives considered

- **Required but nullable, with an upgrade writing null into three stores.** Set aside: null and
  absent would mean the same thing, and three store upgrades would carry no fact the absence lacks.
- **Required and never null.** Set aside: every record written before the field would either be
  refused, which ADR-0326 §4:4 leaves to the owner's ruling, or be given a default grant it never
  had, which nothing could truthfully supply.
- **Defaulted to a how and a bar.** Set aside: a default grant supplied by the type is a claim no
  declaration made, the one ADR-0016 §1 refuses, and it could allow a call.
