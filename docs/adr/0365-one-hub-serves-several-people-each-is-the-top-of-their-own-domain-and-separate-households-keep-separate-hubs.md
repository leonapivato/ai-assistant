# 365. One hub serves several people, each is the top of their own domain, and separate households keep separate hubs

- Status: Proposed
- Date: 2026-11-22
- Scope: lane 1 of the seven decisions the people, authority, audience and outside content
  proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)). It lifts ADR-0099's bar on a
  second person on one hub (§1), keeps a hub each for separate households (§2), states the three
  principles the owner set (§3), gives each person a domain (§4), and states the limit of what
  protects it (§5). It leaves every mechanism to the later decisions of the batch (§6) and records
  what it replaces in ADR-0099 (§7). §8 lists what it settled where the rulings left a point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the coordinator.
  Their words, verbatim. On one hub: "Yes, one hub" (2026-11-19; §1). On least privilege: "yes
  record it, and remember, least privilege principle" (2026-11-19; §3:1). On who it must serve: "it
  hsould work beyond just families tho, roomates, friends, individuals, house cleaners, mailmen,
  annoynmous, etc." (2026-11-19; §1:2). On domains: "Why would mom feel comfortable putting her
  email there if the owner can just pretend to be her and send anythign from her email? or send
  from her email without pretending to be her. Maybe there can be domains where certain users how
  more power.", then, to the domains design, "Yes, adopt it" (2026-11-19; §3:2, §4). On sharing: "its
  just like if I trust someone with infomration, and they tell people. By trusting someone with
  infomration, im subjecting myself to that risk." (2026-11-21; §3:3). The coordinator assigned
  0365 and ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; adds no surface.** No Protocol, no type, no field and no code changes.
  It decides who a hub's principals may be, which bounds every `core` decision the later lanes
  make, so it takes the adversarial and the architecture review, as ADR-0099 did.
- **Partially supersedes** [ADR-0099](0099-one-hub-one-principal-and-a-household-member-is-a-subject.md)
  (§1:1 and §3:1, whole; §1:2, restated as §4:4), as §7 records.

## Context

ADR-0099 ruled that a hub has exactly one principal, the owner (ADR-0099 §1:1), and that a second
person in the household is served by their own hub (ADR-0099 §3:1). It named its cost: two hubs
share nothing until federation is designed, and "a household that wants 'what does my partner's
calendar say' gets nothing from this decision today". The code still has that shape:
`OWNER_PERSON_ID` in `core/types.py` is the only person, and `activation_person` in
`orchestration/person_block.py` returns it or no one.

On 2026-11-19 the owner walked people and authority with the coordinator and chose one hub for
several people. A hierarchy across hubs would need federation, which is not designed. The people
it must serve are not only a family. And the owner rejected the obvious shape, the owner as root:
nobody would link an account to a hub whose owner could use it as them. So each person keeps a
domain the owner cannot enter.

`VISION.md` → "Then a household" already describes one assistant serving a household, and "Each
household is its own" keeps households apart: "One household's data never mixes with another's."

**Words.** A person a hub **admits** is one it serves as a principal in ADR-0099 §2's sense: whose
hub it is, not only someone its records are about. The **later decisions** are lanes 2 to 7 of
#3629, none of which has a number yet. In this document a bare section reference, such as §4:2, is
to this decision's own clauses.

## Decision

We will let one hub serve several people under one owner, give each independent person a domain in
which they are the top, keep separate households on separate hubs, and leave every mechanism to the
later decisions.

### 1. One hub, several people, one owner

> **Normative.** A hub has exactly one owner and may admit other people. Every person it admits is
> a principal in ADR-0099 §2's sense, not only a subject of the owner's model.

> **Normative.** No decision built on this one may assume that the people a hub deals with are a
> family. A hub deals with one person alone as well as with a family, roommates, friends, people
> who work in the home or come to the door, and people it cannot identify.

> **Normative.** Until the later decisions §6 names have merged and been built, the owner stays the
> only person a hub admits, and no lane admits another on the strength of this decision alone.

This decision lifts a bar and sets principles. It obliges no code.

### 2. Separate households keep separate hubs

> **Normative.** Separate households are served by separate hubs. No decision may serve two
> households from one hub.

> **Normative.** No hub reads or writes the store of another household's hub.

Who is of a household is the owner's call, made by whom they admit; it is not a kind of record.
How hubs might meet is still ADR-0099 §5's federation deferral, unchanged.

### 3. Three principles

Each later decision cites these and builds the mechanism.

> **Normative.** Least privilege. Outside their own domain (§4:1), a person holds nothing on a hub
> that they have not been granted: no grant means no, a newly admitted person starts with nothing
> beyond their domain, and each grant is as narrow as its need.

> **Normative.** Permission comes from whoever a thing belongs to, and limits come from above.
> Someone above a person may narrow or take away what that person holds, and never grants in that
> person's place.

> **Normative.** Sharing is like telling someone. What a person has been shown, they know, and they
> may pass it on by their own act. The system never passes anything on by itself.

### 4. Domains

> **Normative.** Each independent person a hub admits has a domain: their linked accounts and their
> private records. Inside it they are the top: they hold the data rights over it, and permission to
> act through it or read it comes from them.

> **Normative.** The owner may admit, limit and remove a person. The owner may not act through
> another person's domain, or read it, without that person's grant.

> **Normative.** A managed person, such as a child, is the exception. The person managing them holds
> over their domain the powers that were stated when they were added, and no others, and those
> powers are visible to the managed person.

> **Normative.** Every belief the store holds is held on behalf of someone the hub admits, a belief
> in a person's domain on that person's, and never purports to record what is true of another
> person independently of whoever it is held for.

The last clause is ADR-0099 §1:2 restated for several principals. A fact about another person
still belongs to whoever learned it, as ADR-0099 framed it; what changes is that "whoever" need not
be the owner.

### 5. The honest limit

The owner runs the machine and can read its disk. What protects a domain from the owner is the
software and a record of access, not cryptography. Stronger guarantees, such as per-person
encryption or a hosted hub, are later work.

> **Normative.** §3's principles and §4's domains are enforced by code. No model's instruction is
> what keeps a person from what they may not do or see.

> **Normative.** A domain's protection from the owner is the software and an access log its person
> can see, not encryption. No surface or document tells a person their domain is protected from the
> owner by more than that.

### 6. What this decision leaves to the later decisions

Each is left to a lane of #3629:

- **Lane 2:** what a person record is, linked accounts and linking, and how sure the hub is of who
  sent an input. This is where ADR-0345 §2:1's "a decision on identified people" and the person
  identity and enrolment half of ADR-0099 §5's third deferral (#691) are taken.
- **Lane 3:** grants, groups, delegated powers and presets, including who counts as an independent
  or a managed person and who may manage one (§4:1, §4:3), and ADR-0097 §12's **Who granted**.
- **Lane 4:** whose work it is and whose authority it carries, including whose assertion
  ADR-0099 §4:1 reads as the user's.
- **Lane 5:** sharing rules and a person's own data: where a record lands (§4:4), what the data
  rights over a domain are and the access log (§4:1, §5:2), and how ADR-0099 §4:2 reads when a
  belief in one person's domain is shown to another.
- **Lane 6:** the audience mark.
- **Lane 7:** outside content.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to a
> later decision.

### 7. Relationship to ADR-0099 and to the decisions resting on it

| ADR-0099 | Becomes |
| --- | --- |
| §1:1, one principal and the bar on a second | Superseded whole: §1:1 and §4:1 here. Whose word counts as the user's and whose grants are recorded go to lanes 4 and 3 |
| §1:2, every belief is the owner's model | Superseded, restated as §4:4 for several principals |
| §2:1, principal and subject are orthogonal | Stands, and applies to this decision (§7:1) |
| §3:1, a second household member is a second hub | Superseded whole: §1 and §2 here |
| §4:1, supersession does not move | Stands. Whose assertion it is goes to lane 4 |
| §4:2, the rendering floor | Stands. Its reading across domains goes to lane 5 |

ADR-0099 §5's deferrals: the subject axis and subject-scoped delete and export were discharged by
ADR-0100 and ADR-0101 and fire nothing new. Person identity and enrolment fire now, for lane 2;
speaker identification stays with the voice work (#691), outside this batch. Bystander consent and
federation do not fire. ADR-0099 §7's `VISION.md` amendment was owed with §3:1's federation, and
`VISION.md` → "Each household is its own" already says what §2 decides.

> **Normative.** ADR-0099 §2:1 applies to this decision as it applies to ADR-0099 §1: that a person
> is a principal here may never be cited to argue that a belief is about them, to refuse a subject
> axis, or to narrow what a later decision may model about a third party.

> **Normative.** This numbered draft records its replacements on ADR-0099's status line and in a
> dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving ADR-0099's
> ratified body. The replacements take effect on this ADR's ratification.

Read through and not superseded. Each stands as written, and none reads more widely, because §1:3
keeps the owner the only person a hub admits until the later decisions are built:

| Decision | Why it stands |
| --- | --- |
| ADR-0124 §5's device clauses, and the decisions that cite ADR-0099 §1's single principal as their ground (ADR-0131, ADR-0199 §7, ADR-0296) | Each still describes a hub with one admitted person. The later decision that admits a second records what changes in them |
| ADR-0097 §12, **Who granted** | Its condition is "the first multi-user deployment", which §1:3 defers. Lane 3 |
| ADR-0345 §2:1 | Its condition is "a decision on identified people", which this is not. Lane 2 |
| ADR-0058's revisit condition, quoted in ADR-0099 §1 | ADR-0058 is superseded whole by ADR-0319, so the condition no longer binds |

### 8. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3's wording** as a bar on lanes, from the coordinator's brief that the hub runs as it does
  today until the later decisions are built.
- **§2:2**, that "never mixes" means no hub reads or writes another household's store, and §2's
  note that a household is whoever one owner admits.
- **§3:1's "outside their own domain"**: least privilege was ruled before domains, and a person's
  own domain is theirs by §4:1, not by a grant.
- **§3:3's "by their own act"**: how a person passes something on, a card or otherwise, is lane 6's.
- **§4:4**, ADR-0099 §1:2 restated as a belief held on behalf of whoever it is held for.
- **§5:2's second sentence**, that no surface overstates the protection, from `VISION.md`'s "the
  assistant is honest with each person about who can see what".
- **§7:1**, applying ADR-0099 §2:1 to this decision.
- **Which lane takes** ADR-0099 §4's readings, ADR-0097 §12 and who counts as independent or
  managed (§6). The cut into lanes is the coordinator's (#3629).

## Consequences

- A second person on one hub is no longer a supersession of ADR-0099 to argue. It is the later
  decisions' work, each citing §3 and §4 by clause.
- The owner's power over other people is bounded from the start: admit, limit, remove, and no more,
  except over a managed person by stated powers.
- Nothing changes in the running hub until those decisions merge and are built (§1:3).
- A person's domain is only as safe from the owner as the software and its log. A person who needs
  more needs per-person encryption or a hub of their own, and §5:2 makes the hub say so.
- **Revisit** if a deployment arrives where the owner should not run the machine, such as a hosted
  hub for several households: §2 and §5 would move with it.

## Alternatives considered

- **A hub each, as ADR-0099 ruled.** Set aside: the people of one household get no shared view, and
  any hierarchy across hubs needs federation, which is not designed.
- **The owner as root over every person.** Set aside: nobody would link an account the owner could
  use as them, which is the owner's own reason for domains.
- **Several owners as equals.** Not taken: it needs a rule for disagreement, and is outside the
  proposal.
