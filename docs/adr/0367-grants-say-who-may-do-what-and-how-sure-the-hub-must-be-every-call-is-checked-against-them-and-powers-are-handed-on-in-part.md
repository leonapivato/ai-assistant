# 367. Grants say who may do what and how sure the hub must be, every call is checked against them, and powers are handed on in part

- Status: Partially superseded by ADR-0382 (§4:7, in the addition alone: in an approval's work, a message into a place an input of the asking activation came from also stays outside the check) and ADR-0391 (§4:2, in the addition alone: a no or a limit for one in a work's say whose authority it does not carry asks the work's people; §4:7, whole: a reply is a call the check runs, allowed by a reply line) and ADR-0392 (§4:6's last sentence, in its reach alone: not a text call to a person the hub admits, into their own chat)
- Date: 2026-11-22
- Scope: lane 3 of the seven decisions the people, authority, audience and outside content
  proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)), the lane
  [ADR-0365](0365-one-hub-serves-several-people-each-is-the-top-of-their-own-domain-and-separate-households-keep-separate-hubs.md)
  §6 names third. It decides people, groups and "anyone" (§2); what a grant and a limit are
  (§3); that no grant means no and no call is outside the check (§4); the level a grant accepts
  and the card when a level falls short (§5); whose a thing is and what is a person's own only
  (§6); powers handed on in part, the power to link and to admit among them (§7); independent
  and managed people (§8); presets (§9); shared approval cards (§10); the grant for one call
  (§11); messaging a hub person (§12); group labels (§13); and how its grants stand to
  ADR-0097's (§14). §15 records what it does to earlier decisions, §16 the contract changes it
  would need, §17 what it leaves to others, and §18 what it settled where the rulings left a
  point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the
  coordinator. Their words, verbatim. On ranks: "Is it better to not necesarilly have a 1
  dimensional hierachy, but maybe pemissions more similar to how linux users work, or what do
  you think?" (2026-11-19; §2, §3). On who it must serve: "it hsould work beyond just families
  tho, roomates, friends, individuals, house cleaners, mailmen, annoynmous, etc." (2026-11-19;
  §2). On powers in part: "is there a way to give someone some power, without giving them full
  root, there is right" (2026-11-19; §7). On least privilege: "yes record it, and remember,
  least privilege principle" (2026-11-19; §3, §4). On what is a person's own only: "2. Some
  things should require the permissions of that person, so it cant be on their behalf"
  (2026-11-19; §6:3). On shared cards: "4. Maybe there can be shared approvals, it just gets
  sent to everyone in the group, whoever replies first wins." (2026-11-19; §10). On presets:
  "Yes, presets" (2026-11-19; §9). On messaging: "I think that usually it shouldnt take any
  authority for the assistant to message a person individually, but this can be a default
  setting than can be adjusted in the profile." (2026-11-21; §12). On every tool: "makes sense,
  does this more generally apply to tools in general, since messaging is just a tool?", then, to
  the general form, "Yes, record it that way" (2026-11-22; §4, §5). On the grant for one call:
  "What if the errand essentially allows Sams activation to add to the calender or not in the
  specific block. Or at least send a card to me, but from sams perspective thats enough.", then
  "i like it, I dont know if the card should necesarilly be a fallback, it should be just
  whatever settings the profile has" (2026-11-22; §11). The coordinator assigned 0367 and
  ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type,
  field or code. It decides what a person may do on a hub of several people and how code checks
  it, which bounds the `core` types the build makes, so it takes the adversarial and the
  architecture review. Building it is a breaking change under golden rule 5, through the `core`
  changes §16 names; one of them waits on a further decision (§11:5), and none is made here. It
  dispatches no implementation (§1:2).
- **Partially supersedes**
  [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md)
  (§4:1, in the addition alone),
  [ADR-0345](0345-a-memory-records-who-holds-it-when-it-lapses-what-it-is-for-and-whom-it-is-about-and-its-producer-places-it-among-what-is-stored.md)
  (§2:7's *the owner's act*),
  [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md)
  (§7:7, in the addition alone),
  [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md)
  (§2:6, §4:2, §4:6, §4:8, §4:9, §5:3 and §6:1, in the scopes §15 names) and
  [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md)
  (§9:3, in the addition alone), as §15 records.
- Partially superseded: 2026-11-27 by [ADR-0391](0391-every-text-carries-the-say-it-was-written-under-a-work-may-do-and-read-only-what-everyone-whose-say-it-holds-may-a-signal-is-anyones-and-a-reply-is-a-send-like-any-other.md) — §4:2, in the addition alone: where the check allows a call for each person whose authority a work carries, a no or a limit for anyone else in its say makes the call need their yes rather than refusing it (ADR-0391 §3:3). §4:7, whole: no message is outside the check; a reply into a place one of the work's own inputs came from is allowed by a reply line, a default grant each kind of place declares (ADR-0391 §6). ADR-0391 §9 also records that §18's credit of §4:7 to the owner, and §11's "The owner's example", are the coordinator's words. Every other clause stands. This replacement takes effect on ratification of ADR-0391. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-11-27 by [ADR-0392](0392-two-checks-on-a-call-and-one-card-for-the-first-and-the-mark-every-tool-within-the-authority-a-work-carries-unestablished-words-a-strangers-and-memories-outside-the-rule-along-names.md) — §4:6's last sentence, in its reach alone: ADR-0021 §5's floor does not reach a `text` call to a person the hub admits, into their own chat (§12:1), which takes no card for being allowed by a default grant alone (ADR-0392 §3:3). Every other clause, and the floor for every call the policy rules, stands. This replacement takes effect on ratification of ADR-0392. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

ADR-0365 let one hub serve several people and set three principles: least privilege, "no
grant means no" (ADR-0365 §3:1); permission comes from whoever a thing belongs to and limits
come from above (§3:2); and sharing is like telling someone (§3:3). It gave each independent
person a domain the owner cannot enter (§4:1, §4:2) and made a managed person the exception
(§4:3). ADR-0366 made a person one identity with linked accounts and gave the hub four levels
of how sure it is of who sent an input (ADR-0366 §5:1). Both left this lane grants, groups,
powers handed on, presets, who counts as independent or managed, the power to link, to admit
and to merge, what level a grant accepts, the card when a level falls short, and `G` labels
(ADR-0365 §6, ADR-0366 §12). ADR-0365 §1:3 keeps the owner the only person a hub admits until
a later decision provides for admitting another and that provision is built.

**The code today** checks every call by rule (ADR-0306 §4:1): the policy, `ActionPolicy`,
implemented by `ThresholdActionPolicy` in `permissions/policy.py` as a table over a call's
declared fields; then the outside-content stand-in; then, for a message, its place. The policy
takes no person. ADR-0021 §5's floor keeps a disclosing call from an `ALLOW` the policy reaches
by itself: `PermissionRuling.authorised_by` must name the user decision it rests on, and today
only a yes does. ADR-0021 §6 deferred **standing grants for actions** as "the only sanctioned
way to stop asking", and ADR-0021 §3 set a precondition on the ADR that brings them: it "must
make the *other* source resolvable — to a recorded user decision that actually covers this
tool — and must say where those records live". ADR-0097 §7:2 kept that deferral and that
precondition unspent. Recipient grants, the one standing grant ever built, retired with
ADR-0321 §7:1: "Their establishing act is not redone: scoped delegations replace it, on a later
design."

A yes is a tap on an approval card (ADR-0361): planning asks with `request_approval`, a person
taps Approve on the line or the hub page, and the yes is a one-time **ticket** for the exact
call (ADR-0361 §5:1). A tap is carried out only where it comes from the request's person
(ADR-0361 §4:8), and records who answered as the `ApprovalGiver` of its surface (§4:9), which
names a surface and not a person.

**The word "grant" is taken.** ADR-0097 decided "A grant is a recorded user act naming one
source instance and what it authorises": a reader's permission to read one source for a use,
built as `SourceGrant` and `SqliteSourceGrantStore` in `permissions/grants.py`, with the
client operations of `orchestration/grants.py` (ADR-0102). Its §12 deferred **Who granted** to
"the first multi-user deployment". The owner's word in every ruling below is "grant", for
something wider.

**What the owner decided.** On 2026-11-19 the owner asked for permissions "more similar to how
linux users work" than a one-dimensional hierarchy, and for a design that works "beyond just
families". They ruled people, groups and grants, least privilege, powers handed on in part,
that some things need their person's own permission, shared approvals, and presets. On
2026-11-21 they ruled that messaging a person needs no authority by default, adjustable in the
profile, and on 2026-11-22 generalized it: every tool has a default grant that names the least
sureness it accepts, and a work that falls short gets a card. The same day they ruled that a
request that depends on another person's answer is a grant to that person for one call, with
whether it goes straight through being "whatever settings the profile has". They ruled on
2026-11-19 that no floor holds against everyone.

**Words.** A **thing** is what a grant is about: a tool, a connection or an account, a kind of
record, or one named record. A **line** is a grant or a limit (§3). A person's **level** is how
sure the hub is of them, on ADR-0366 §5:1's scale. A grant's **bar** is the least level it
accepts. **The check** is §4:1's. A **power** is a grant whose thing is other people's grants,
cards or membership (§7). A **card** is an approval card under ADR-0361, and a **yes** a tap on
Approve. **Admits** is ADR-0365's word; a **work** is an activation, as ADR-0364 uses the word.
A **later decision** is one of lanes 4 to 7 of #3629, none of which has a number yet. In this
document a bare section reference, such as §5:2, is to this decision's own clauses.

## Decision

We will give a person only what grants give them, as lines saying who may do what, how and at
what level, check every call against them in code, turn a shortfall in level into a card
rather than a refusal, let powers be handed on one at a time and never beyond what the giver
holds, and keep ADR-0097's source grants a thing of their own.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and
> when, is the owner's planning call, made after it merges.

> **Normative.** Until grants and the check are built, every call is checked as it is today,
> and nothing in this decision changes what the running hub allows or asks.

> **Normative.** This decision makes part of the provision ADR-0365 §1:3 names: who may admit
> a person (§7:1) and what a newly admitted person holds (§9:1). It is not the whole of it.
> No build admits a person other than the owner until the later decisions ADR-0365 §6 assigns
> to lanes 4, 5 and 6 have merged, and until ADR-0366's identities and links, this decision's
> grants, check and act of admitting, and what those later decisions rule a second person
> needs, are built.

> **Normative.** Until §1:4's conditions are met, ADR-0366 §3:3 holds as written: only the
> owner links, and only accounts to the owner's own identity, whoever §7:1 says holds the
> power.

Lane 7, outside content, is not among §1:4's conditions: until it lands, the outside-content
stand-in (ADR-0306 §4:4) holds for every work. ADR-0365 §7 has "the later decision that
provides for admitting a second" record what changes in ADR-0124 §5, ADR-0131, ADR-0199 §7 and
ADR-0296. This decision is not that one in full and records none of it: those clauses describe
devices and notifications, whose people the later decisions on what a work carries and on the
mark rule.

### 2. People, groups and "anyone"

> **Normative.** Code holds no rank, role or household position for a person. Outside their
> own domain (ADR-0365 §4:1), what a person may do is the lines that apply to them (§3) and
> the powers they hold (§7), and nothing else is read. The owner's powers are §7:2's.

> **Normative.** A group is a set of people with a stable identifier, never reused. Its
> members are people, never groups. Only the owner makes or removes a group, and its members
> change only by the owner or a person holding the power to change them (§7:1).

> **Normative.** One group is built in: **anyone**. Every person, identified or not, is in
> it; it cannot be removed and its membership cannot be changed.

A person at none, claimed or unknown, holds only what is granted to anyone (§5:2). A grant to
anyone is normally limited to one connection, such as the door. "Anyone" denotes the same set
as ADR-0217's `ANYONE` reach; how a record's reach names people and groups is lane 5's.

### 3. A grant and a limit

> **Normative.** A **grant** is one line: who (a person or a group); what (an action on a
> thing); how (allowed, or allowed with approval); its bar (one of ADR-0366 §5:1's levels);
> any conditions; and who set it.

> **Normative.** A **limit** is the same line saying no. It has no how and no bar, and holds
> at every level.

> **Normative.** A line's conditions are drawn from: a time window, an end date, and one
> connection. A condition only narrows the line it is on.

> **Normative.** Every kind of line a later decision adds, such as a sharing rule, a standing
> approval or a vouch, has §3:1's or §3:2's shape and follows §3 to §7. A later decision may
> add kinds of action, thing and condition, and changes no part of that shape.

> **Normative.** A line is made and removed only by a person's own act, or by a call a work
> makes on a person's authority that the check allows, and each making and removal is
> recorded and kept. No model makes or removes a line by any other route.

> **Normative.** Lines live in a store of the hub's `permissions/` subsystem, local to the hub
> under `Settings.data_dir`, each under a stable identifier, never reused, by which a ruling
> resting on it names it.

> **Normative.** A model is told a call's outcome and never the lines behind it.

The "what" is open on purpose. Lane 5's sharing rule ("my contacts: the flat may see them"),
lane 6's standing approvals and lane 7's vouch are each a grant in the owner's rulings, and
§3:4 is what lets each be one without amending this decision.

### 4. No grant means no, and no call is outside the check

> **Normative.** Code checks every call a work makes against lines, with no model, before it
> runs: for the person whose authority the work carries, at the level the work carries. Whose
> authority and what level a work carries are the later decision's on what a work carries
> (ADR-0365 §6), and the check reads them as given.

> **Normative.** No grant means no. A call that no grant covers, or that a limit covers, is
> not done, with its reason, and asks no one, save under §6:3.

> **Normative.** No tool is outside the check. Every tool declares a default grant, where the
> tool is declared: who it covers, how, and its bar. It is a line like any other, and whoever
> holds the power over its thing may change it as they may any line (§7).

> **Normative.** Where each tool's bar sits is set where the tool is declared and in the
> presets (§9). This decision sets no value.

> **Normative.** The check joins ADR-0306 §4:1's checks, first. A call runs only where every
> check allows it. A grant never turns the policy's deny into anything else, and never lifts
> the outside-content stand-in (ADR-0306 §4:4).

> **Normative.** A grant that allows, set by a person under §3:5 and covering the call's
> tool, is a standing grant in ADR-0021 §6's sense: a ruling resting on it names it in
> `PermissionRuling.authorised_by`, resolvable to its record in §3:6's store. A default grant
> names nothing there, so ADR-0021 §5's floor still sends to approval a disclosing call that
> only a default grant allows.

> **Normative.** A message call is a call like any other and passes the check, save one into a
> place one of the work's own inputs came from, which stays checked by its place alone (ADR-0306
> §4:7, ADR-0356 §7:7). A text into any other connection (ADR-0364 §9:3) passes the check as
> well.

A person's own domain is theirs without a grant from anyone (ADR-0365 §3:1), and a tool's
default grant covers its thing's person. Its bar still applies there: the owner's email, at
weak, falls short of a bar of normal on the owner's own account, and gets the card §5:3 rules.

### 5. The level a grant accepts, and the card when it falls short

> **Normative.** A grant applies to a call only where the call's level is at or above the
> grant's bar.

> **Normative.** A grant to a named person, or to a group other than anyone, applies only where
> that person is identified at weak or above. At none, only grants to anyone apply.

> **Normative.** A shortfall is not a refusal. Where a grant would cover a call but for its
> bar, the call needs a yes, as ADR-0361 §2:4 has a call ruled to need the person, and its card
> goes to the person whose authority the work carries, showing the exact call.

> **Normative.** A shortfall's card is offered only on surfaces that can establish its person
> at the grant's bar, and a tap answers it only where its surface establishes them at that bar.
> A tap below it changes nothing.

> **Normative.** A call run under a ticket is checked for the person whose tap approved it, at
> the level that tap came by: their tap makes the call theirs.

> **Normative.** A call covered only by a grant that allows with approval needs the yes of
> whoever its thing belongs to (§6:1): its person, or, for a group's thing, the people §10:1
> names.

Where a person has no surface at the bar, the card cannot be answered and expires as ADR-0361
§3:5 has every card. A call that needs a yes on two grounds gets them in turn: the ticket's
call is checked again (§5:5), and a remaining need for its thing's person's yes comes back as
a new request. Where a work's own level comes from is lane 4's and lane 7's.

### 6. Whose a thing is, and what is a person's own only

> **Normative.** Every connection, account and source the hub acts through or reads belongs to
> one person or one group, recorded with it. Permission to act through it, or read it, comes
> from whoever it belongs to (ADR-0365 §3:2).

> **Normative.** A person makes and removes lines about their own things on their own
> authority, without the owner. Lines about a group's things are made by the owner or a person
> holding the power to set them (§7:1).

> **Normative.** An account linked to identify its person (ADR-0366 §6:2) is that person's own
> only. No grant lets anyone else act through it. A call by another person's work to act
> through it is not done; it becomes a card to its person showing the exact call, and their
> yes makes the call theirs (§5:5).

> **Normative.** §6:3 yields only to a managed person's manager, and only where the powers
> stated when the managed person was added name acting through that account (ADR-0365 §4:3).

A manager who does act through such an account makes it one "someone other than its person
may send through", so by ADR-0366 §6:1 its link gives none while the hub holds the record of
that use. What records belong to whom is lane 5's.

### 7. Powers handed on in part

> **Normative.** Each power is its own grant, scoped to one group or one thing: to set lines
> for it; to answer its cards; to manage it; to change a group's members; to add and remove
> people, which is also the power ADR-0366 §3:1 names to link an account and to make an
> identity one the hub admits, and the power ADR-0366 §7:7 needs for a merge; and to hand a
> power on.

> **Normative.** The owner holds every power over every group and every group's things. Each
> person holds every power over their own things save adding and removing people. No one else
> holds a power until it is handed to them.

> **Normative.** A power handed on does not include handing it on, unless that is handed on
> too.

> **Normative.** Nobody hands on more than they hold. A line or power one person gives another
> is no wider, in its what, conditions and bar, than what the giver holds, and lapses as far as
> the giver stops holding it.

> **Normative.** The owner sees, and may undo, every power handed on over a group or a group's
> thing.

> **Normative.** Where lines set by different people conflict over a call, the line set by
> whoever stands first in this order holds: the owner; the manager of the group whose thing it
> is; the person. Between lines one person set, a limit holds over a grant.

> **Normative.** No power handed on, and no line set by anyone but a person, gives anyone
> anything inside that person's domain, save a managed person's manager's stated powers (§8:2).
> A limit only takes away (ADR-0365 §4:2).

> **Normative.** No power handed on reaches the owner's own lines or domain.

> **Normative.** A link to the identity of a person the hub admits, made by anyone else, takes
> effect only on that person's yes, on a card on a connection already linked to them. The link
> made when they are admitted needs none.

> **Normative.** A link may be undone by the person it identifies, or by a person holding the
> power to make it.

> **Normative.** Removing a person ends every line and power they hold, and with them, under
> §7:4, every grant and power they gave. The limits they set stand, each changeable by whoever
> holds the power over its thing, and the record of every line is kept (§3:5).

> **Normative.** A claimed source holder becomes the same as an established one (ADR-0345
> §2:7) by the act of a person holding the power to make that link, in place of the owner's.

### 8. Independent and managed people

> **Normative.** Every person the hub admits is independent unless they were added as managed.

> **Normative.** A person is added as managed by whoever holds the power to add them, who names
> at that moment their manager, an independent person the hub admits, and the powers the
> manager holds over the managed person's domain. Those powers are shown to the managed person
> (ADR-0365 §4:3).

> **Normative.** No independent person is made managed. A managed person is made independent
> by a person holding the power to add and remove people over them, which ends every power their
> manager held.

> **Normative.** A manager's powers change only by a person holding the power to add and remove
> people over the managed person, and each change is shown to the managed person.

An independent person who wants someone to act for them grants it, as any line, and can take it
back. Who sees a log of a manager's use of their powers is lane 5's.

### 9. Presets

> **Normative.** A preset is a list of ordinary lines applied in one step when a person is
> added, shown to whoever adds them before it is applied, and each line changeable or removable
> afterwards. A newly admitted person holds their domain, the lines applied, and what is
> granted to the groups they are in, and nothing else.

> **Normative.** A preset is not a role. No check reads which preset a person was added with.

> **Normative.** Applying a preset is the act of whoever adds the person, and gives no more than
> they hold (§7:4).

> **Normative.** A limit the hub ships is a default line, which a person holding the power over
> its thing may remove. No line holds against everyone.

Presets might be an independent adult, a managed child, a guest, a service, or anyone on a
public connection. What each holds, and each tool's bar within them, is the owner's to rule and
not ruled here (§4:4). Never claiming to be human, if #3600 makes it a limit, is such a line.

### 10. Shared approval cards

> **Normative.** A card that needs a group's yes goes to every person who holds the power to
> answer that group's cards.

> **Normative.** The first tap to land wins (ADR-0361 §4:9), and from that tap the person who
> tapped stands as the request's person in ADR-0361 §5 and §6.

> **Normative.** A yes gives no more than the tapper holds: the call under its ticket is
> checked against the tapper's lines under §5:5, and runs nothing they could not have made.

> **Normative.** A tap records the person who tapped, beside its surface.

The owner ruled "sent to everyone in the group, whoever replies first wins". That a card goes to
those who hold the power to answer it, and that a yes gives no more than the tapper holds, are
the coordinator's, accepted with the proposal and not ruled on their own (§18).

### 11. The grant for one call

> **Normative.** A request that depends on another person's answer is made by a grant to that
> person: one exact call, as its capability and values, usable once, with an end date, made by
> the asker's work on the asker's authority under §3:5 and §7:4.

> **Normative.** The call is made by the answerer's own work, as the answerer, checked against
> that grant at that work's level. No work of the asker's makes it or waits for the answer.

> **Normative.** The grant is spent by the call it covers. Code tells the asker when it is
> used, and when it ends unused.

> **Normative.** Whether the call goes straight through or becomes a card to the asker is set
> by the asker's profile setting for that kind of call, which gives the grant its how. It is
> not a rule.

> **Normative.** No lane builds §11:1 to §11:4 before a further decision decides a grant that
> names one exact call and is spent on use, and the notice to its giver. Neither ADR-0349 nor
> ADR-0350 is amended here.

The owner's example: "Ask Sam if he's free Friday, and add it to the calendar if so." The
asker's work asks Sam and grants him that one calendar entry; Sam's own work reads Sam's answer
and makes the call. ADR-0361's ticket has the shape, one exact call run once, but only the work
holding its approval's input uses it (ADR-0361 §5:6), and it is not something one person hands
to another. How Sam's work learns that it holds the grant is lane 4's, with what a work is
shown.

### 12. Messaging a hub person

> **Normative.** Messaging a person the hub admits, in their own chat, is covered by a default
> grant in that person's profile, to anyone, with a bar of normal, which they may change as any
> line on their own things.

A reply into a place the work's own input came from stays outside the check (§4:7), and what a
message may carry is lane 6's.

### 13. Group labels

> **Normative.** A group is named to a model by a label of a new kind, `G1`, `G2`…, under
> ADR-0307 §5, as ADR-0366 §8:1 to §8:4 rule a person's: it holds for one work, the hub maps it
> to the group's stored identifier, a call naming one the work was not shown is refused, and no
> group's label is the same in every work by rule.

> **Normative.** This decision rules nothing about which label a group gets in a work, the
> order labels are given out in, or what is shown beside one.

### 14. The word "grant", and ADR-0097's source grants

> **Normative.** ADR-0097's record is a **source grant**. In a decision after this one, a bare
> "grant" means a grant under §3.

> **Normative.** A source grant is not a grant under §3, and a grant under §3 is not a source
> grant. Neither is read, cited or checked as the other, and ADR-0097 §7 stands.

> **Normative.** Once a person other than the owner is admitted, a source grant records the
> person who made it, and only whoever its source belongs to (§6:1), or for a group's source a
> person holding the power to set its lines, makes or revokes one.

They are two things because they answer two questions. A source grant lets the hub's own reader
read a source for a use, for no one in particular; a grant under §3 says what one person or
group may do. Widening ADR-0097's record would have made a reader's permission a person's, and
undone the separation ADR-0097 §7 exists for.

### 15. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of
> ADR-0306, ADR-0345, ADR-0356, ADR-0361 and ADR-0364 and in a dated header note on each,
> atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0306 §4:1, the checks a call passes | In the addition alone: the check, first, once built (§4:5). Its other checks and its order stand |
| ADR-0356 §7:7, a `text` call "checked by its place alone" | In the addition alone: a text into a place none of the work's own inputs came from also passes the check (§4:7) |
| ADR-0364 §9:3, a text into any connection the work was shown | In the addition alone: into a place none of the work's own inputs came from, it also passes the check (§4:7) |
| ADR-0345 §2:7, "becomes the same only by the owner's act linking the two" | By the act of a person holding the power to link (§7:12) |
| ADR-0361 §2:6, the request's person "is the person the asking activation is for" | In the addition alone: a request may be for the person a thing belongs to (§5:6, §6:3) or for a group's answerers (§10:1) |
| ADR-0361 §4:2 and §4:6, the card in the line's chat and the panel | In the addition alone: a card for a person other than the owner is posted and shown to that person, on surfaces that reach them |
| ADR-0361 §4:8, a tap from the request's person | In who may tap: also a person §10:1 names; and, for a shortfall, only at the bar (§5:4) |
| ADR-0361 §4:9, who answered | In the addition alone: the person who tapped (§10:4) |
| ADR-0361 §5:3 and §6:1, the request's person | In the addition alone: on a shared card, the person whose tap landed (§10:2) |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0021 §6's standing grants for actions, and §3's precondition on the ADR that brings them | §4:6: a grant a person set is a standing grant; it is resolvable by its identifier to its record, which lives in §3:6's store. ADR-0097 §7:2 kept the precondition for this |
| ADR-0097 §12, **Who granted** | §14:3. Its condition, the first multi-user deployment, is a person other than the owner admitted |
| ADR-0321 §7:1, "scoped delegations replace it, on a later design" | §7's powers and §3's lines. No recipient grant is redone |
| ADR-0364 §4:4, `G` labels "take their own decision" | §13. §4:4's bar on building them under ADR-0364 stands |
| ADR-0366 §3:1 and §7:7, the power to link, to admit and to merge; its §3 note, who may undo a link | §7:1, §7:2, §7:9 and §7:10. ADR-0366 §3:3 holds until §1:4 (§1:5) |
| ADR-0366 §5:8's "what a shortfall does", and §6's note on how a grant bears on an account that is its person's own only | §5:3 to §5:5 and §6:3 |
| ADR-0365 §6's lane 3: who counts as independent or managed, and who may manage one | §8 |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0021 §3's purity of `decide`, and §5's floor and monotonicity | The check reads the store, not the policy (§16); a grant is an input the policy is handed, and §4:6 satisfies the floor rather than relaxing it |
| ADR-0097 §1, §7, §8 and §9; ADR-0102; ADR-0133 | Source grants, as §14 keeps them |
| ADR-0306 §4:2, §4:4 and §4:7 | Standing grants count in the policy (§4:6); the stand-in is never lifted by a grant (§4:5); a message into a place the work's own input came from stays checked by its place alone (§4:7) |
| ADR-0361 §5:1 to §5:7 | A ticket runs as ruled, checked as §5:5 says |
| ADR-0345 §2:5 and ADR-0338 §2:1 | Each stands until a person other than the owner is linked or admitted, which waits on §1:4 |
| ADR-0217 §1 and `PlacementReach` | A record's reach is lane 5's; "anyone" denotes the same set as `ANYONE` (§2:3) |
| ADR-0351 §6 and ADR-0350 §3 | Whose authority a work carries is lane 4's; §4:1 reads it as given |
| ADR-0036's "records that a human answered, not which human" (#113) | It describes the first confirmation path. A card's tap names its person under §10:4 |

### 16. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made by
the lane the owner's planning dispatches, under this decision once merged. A new Protocol ships
as a triad.

- **Lines and their store:** a type for a line (§3:1, §3:2), with its conditions and its
  identifier, and a Protocol for §3:6's store, which keeps every making and removal (§3:5).
- **Groups:** a type and store for a group and its members, with "anyone" built in (§2:2, §2:3).
- **Whose a thing is:** the person or group each connection, account and source belongs to
  (§6:1), beside their declarations.
- **Default grants:** each tool's default grant beside its declaration on `ToolDefinition`
  (§4:3).
- **The check:** `ActionRequest` gains the line a call rests on, read by the authorizer, so
  `ActionPolicy` reads no store and stays a function of its argument (ADR-0021 §3), and
  `PermissionRuling.authorised_by` names that line (§4:6). The person and level the check runs
  for come from wherever lane 4 records them on a work.
- **Approvals:** an approval request may be for a person other than the asking work's, or for a
  group's answerers; a tap records its person and the level its surface established (§5:4,
  §10:4).
- **Managed people:** a person's manager and the stated powers, on the person record ADR-0366
  §11 names.
- **Labels:** `LabelKind` gains a member for `G` (§13:1).
- **Acts:** engine members for a person's own act to add and remove a person, apply a preset and
  make and remove lines, as ADR-0102 gives source grants theirs.
- **Source grants:** `SourceGrant` gains who made it, an optional field, as ADR-0097 §12 named it
  (§14:3).
- **The grant for one call:** waits on §11:5's further decision.

### 17. What this decision leaves to others

Each is left, by ADR-0365 §6's cut or by the owner:

- **Lane 4:** what a work carries, so the person and level the check runs for (§4:1); the tool
  list, the connections and the People section filtered to a work's authority; instructions
  given in advance.
- **Lane 5:** sharing rules, each a line of §3's shape (§3:4); where a record lands and whose it
  is; the data rights and the access log, including a log of a manager's use of their powers.
- **Lane 6:** the audience mark, and standing approvals for it.
- **Lane 7:** vouching for a source, a line of §3's shape; where outside content sets a work's
  level.
- **The owner:** where each tool's bar sits and what each preset holds (§4:4, §9); the default of
  §11:4's profile setting.
- **A further decision:** the grant for one call's machinery (§11:5).
- **The next prompt review:** which label a group gets (§13:2), and how an outcome is worded.
- **Left out by the owner:** two equal owners; sureness that fades with time.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 18. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **The coordinator's additions to shared cards**, accepted with the proposal and never ruled on
  their own: a card goes to those who hold the power to answer it (§10:1), and a yes gives no
  more than the tapper holds (§10:3). §10:2's tapper standing as the request's person, and
  §10:4's record of them, follow.
- **§1:4**, that this decision is part of ADR-0365 §1:3's provision, and what else must merge and
  be built; and **§1:5**, keeping ADR-0366 §3:3 until then.
- **§2:2**: groups are flat, and only the owner makes one. **§2:3**: "anyone" includes identified
  people, so a grant to anyone with a bar of normal (§12:1) means anyone identified at normal.
- **§3:4 to §3:7**: later kinds keep the shape; a line is made by a person's act or by a checked
  call on their authority; lines live in `permissions/`, which ADR-0021 §3's precondition asks
  to be said; and a model sees outcomes only.
- **§4:5 to §4:7**: the check runs first and never lifts the policy's deny or the stand-in; a
  person's grant sources `authorised_by` and a default grant does not; a message call passes the
  check save one into a place the work's own input came from, which keeps the owner's "a work can
  always answer its own sender" (2026-11-21).
- **§5:2's "weak or above"** for established; **§5:4 and §5:5**, the tap's level; **§5:6**, whose
  yes a grant with approval needs.
- **§6:1**, that a reader's source also belongs to someone, and **§6:4**, the manager's exception.
- **§7:2 and §7:3**: who holds powers at the start, and that handing on is not included unless
  handed on. **§7:4's** lapse when the giver stops holding. **§7:6's** last sentence: between one
  person's lines, a limit holds. **§7:9 to §7:11**: a link to an admitted person needs their yes;
  who may undo a link; what removal ends.
- **§8:1 to §8:4**: independent by default, the manager named at adding, no independent person
  made managed, and who changes a manager's powers.
- **§9:1's** what a new person holds, and **§9:2**, that no check reads a preset.
- **§14**, the word "grant", and that Who granted fires on a second person admitted.

## Consequences

- A second person has a shape for what they may do: the lines that apply to them, checked in
  code at the level the hub is sure of them, with no role anywhere.
- Every call has a bar. A work that is not sure enough of its person asks them on a surer
  connection instead of failing, and their tap is what makes the call theirs.
- A person can hand on one power without handing on all of them, and never more than they hold.
  The owner's power over others stays ADR-0365's: admit, limit and remove.
- Lanes 5, 6 and 7 can each make their rule a grant of §3's shape without amending this one.
- ADR-0021's long-deferred standing grant has its decision, so a disclosing tool can stop asking
  once a person has said so on the record.
- Nothing changes in the running hub until the owner's planning dispatches the build (§1:3), and
  no second person is admitted until §1:4's conditions are met.
- The grant for one call waits on its machinery (§11:5), so "ask Sam, and add it if so" still
  goes back to the asker until that decision lands.
- **Revisit** if a deployment needs two equal owners, or nested groups.

## Alternatives considered

- **Ranks, or a tree.** Set aside: one number bundles what a person may use with whom they may
  rule, and the people a hub serves are not all family (ADR-0365 §1:2). Taken: people, groups and
  grants, as Linux users and groups.
- **The owner as root over every person.** Set aside by ADR-0365 §4:2: nobody would link an
  account the owner could use as them.
- **A request that waits on someone's answer: the asker's work waits and reads the answer.** Set
  aside: it needs a record tying answer to question, cannot hold a mixed or conditional reply, and
  lets another person's words steer a work with the asker's authority. Taken: a grant for one call
  to the person asked (§11).
- **ADR-0097's grant widened to cover these.** Set aside: a source grant is a reader's permission
  for no one in particular, and ADR-0097 §7 keeps it from ever authorizing an action (§14).
- **A shortfall refused outright.** Set aside by the owner: it becomes a card (§5:3).
- **A fixed floor that holds against everyone**, such as never claiming to be human. Set aside by
  the owner on 2026-11-19: a shipped limit is a default someone can remove (§9:4).
