# 371. Outside text holds no grants, code sorts every read by its source, raw text is read only in work that cannot act, and text carries its level

- Status: Accepted
- Date: 2026-11-22
- Scope: lane 7, the last, of the seven decisions the people, authority, audience and outside
  content proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)), the lane
  [ADR-0365](0365-one-hub-serves-several-people-each-is-the-top-of-their-own-domain-and-separate-households-keep-separate-hubs.md)
  §6 names seventh: outside content. It decides that outside text is a stranger's voice, and
  sender against source (§2); that code sorts every read before it happens (§3); separate work
  and what its findings carry (§4); that text carries its level (§5); a work's level as the
  lowest of what it holds now (§6); text seen by a person (§7); what a work may do once its level
  drops (§8); and vouching for a source (§9). §10 says what it replaces, §11 answers what the
  earlier lanes left it, §12 records what it does to earlier decisions, §13 names the contract
  changes it would need, §14 what it leaves to others, and §15 what it settled where the rulings
  left a point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the
  coordinator. Their words, verbatim. On outside content as a voice: "so yes, what if it was
  outside content can be trated as one more voice in the work, on that holds no gratas, so its as
  if a stranger walked up and told it information. So this would lower the mark to its lowest
  level everytime right, no twin mark needed?" (2026-11-21; §2). Against a record of calls being
  clean: "why are calls it made clean? writing to itself, and saying things to a person are just
  calls. A call for searching the web would contain free text, as would many other calls. I think
  the better solution is the undoing of the mark via a digest, or never letting it drop
  authority. The undoing can be a sergical context replacement, which may help right"
  (2026-11-21; §4 to §6). On the side branch, with their condition: "yes I like it, but it should
  also be pairing with the source verification and trusting." (2026-11-21; §3, §4). On the branch
  as a spawn: "yes, summarize, and also the branch can just be a spawn right?" (2026-11-21; §4:2).
  On verifying a source: "and why not a way of verifying a source before readng it so it doesnt
  drop the mark, or digest not necesarilly being question oriented, or just having a seperate
  content verifing call" (2026-11-21; §3, §4:4). On levels by route, "Yes" (2026-11-21; §3 to §6),
  to the coordinator's proposal to reuse the sureness levels, so that reading outside text lowers
  the level a work carries by the route it came in, with a model's judgment alone never giving
  full authority. On sender and source, and the request that depends on another's answer: "i like
  it, I dont know if the card should necesarilly be a fallback, it should be just whatever
  settings the profile has" (2026-11-22; §2, §8:3). On the six details of vouching: "Yes, all
  six" (2026-11-22; §9). The coordinator assigned 0371 and ratifies it, under the owner's
  delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides what reading another's text does to a work and what every call is then
  checked at, which bounds the `core` types the build makes, so it takes the adversarial and the
  architecture review. Building it is a breaking change under golden rule 5, through the `core`
  changes §13 names; some wait on a further decision (§3:6, §4:6), and none is made here. It dispatches
  no implementation (§1:2).
- **Partially supersedes**
  [ADR-0181](0181-an-egress-call-records-whether-it-was-planned-over-external-content.md)
  (§5:2, and §5:3, §5:4 and §5:8 to §5:10 as they apply it, for the calls the phases run once
  §10:1 retires the stand-in),
  [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md)
  (§4:1's stand-in and §4:4, whole, once §10:1 retires it; §4:6, in what reaches a rule of
  authorizing) and
  [ADR-0368](0368-every-work-records-whom-it-is-for-whose-authority-it-carries-and-how-sure-the-hub-is-and-an-instruction-given-in-advance-carries-its-authors.md)
  (§6:1, §6:3 and §7:1, each in the addition alone), as §12 records.

## Context

ADR-0365 let one hub serve several people under three principles: least privilege (ADR-0365
§3:1), permission from whoever a thing belongs to (§3:2), and sharing as telling someone (§3:3).
It left lane 7 outside content (ADR-0365 §6), and each later lane left this one its part: whose
words teach the hub a name, relation or correction, and whether outside content takes a level on
ADR-0366 §5:1's scale (ADR-0366 §12); vouching for a source, a line of ADR-0367 §3's shape, and
where outside content sets a work's level (ADR-0367 §17); how text read from a source bears on a
work's level or authority, and sender against source (ADR-0368 §12); the approval the owner's
ruling asks for when a work that read outside content widens a record (ADR-0369 §17); and who has
had a say in a work, and what reading outside text does to a send (ADR-0370 §13).

**What the corpus and the code do today.** Every call is checked "in this order: the policy; the
outside-content stand-in; and, for a message, the message place" (ADR-0306 §4:1), with the grant
check first once built (ADR-0367 §4:5) and the mark for a send (ADR-0370 §5:1). The stand-in "is
the built lineage rule, ADR-0181 §5:2 with ADR-0247 §3's exception for a search at the configured
provider: a call to a capability that leaves the hub, planned in an activation that has read
outside content, gets no standing permission and needs the user, with its values shown" (ADR-0306
§4:4). "An activation has read outside content when its record says so: an outside trigger,
digested evidence, or a marked summary or note" (ADR-0306 §4:5), computed over its whole record
(§4:6) by `read_outside_content` in `orchestration/authorizer.py`, and reaching the policy as
`planned_with_external_content` on the call's `EgressBinding`, where ADR-0181 §5:2 lets no
standing grant cover it. A note written where that holds is marked (ADR-0303 §3:1, ADR-0307 §4:3),
a summary rewritten over a marked one stays marked (ADR-0303 §3:4), and a marked one read counts
again (ADR-0303 §3:6). So one fact covers a whole activation and spreads to later works, tasks and
matters: [#2798](https://github.com/leonapivato/ai-assistant/issues/2798) records a story's
summary gating every later action, and
[#2856](https://github.com/leonapivato/ai-assistant/issues/2856) the episode window carrying the
mark into unrelated conversations, so that after one web search the user's own statements cannot
be remembered.

Planning "never reads raw outside content" (ADR-0307 §9:2). Text someone other than the user or
the assistant wrote goes to a digest (ADR-0306 §5:14): "one model call, with no tools" that
"answers the call's *looking for* argument ... and nothing else" (ADR-0308 §4:1, §4:3), whose
evidence is a list of text items marked as from outside (ADR-0308 §5:1). The work's own relayed
stimulus is the one exception: planning is shown its words, and the work counts as having read
outside content (ADR-0356 §3:7). A party in what an author forwards or relays carries no
authority, and a relayed input carries none (ADR-0351 §6:2, §6:5), which ADR-0368 §3 kept.

**What the owner decided.** In the walk of 2026-11-21 the owner proposed treating outside content
as "one more voice in the work, on that holds no gratas, so its as if a stranger walked up and
told it information", and asked "no twin mark needed?". The same message asked whether this
"would lower the mark to its lowest level everytime", and a later one put "the undoing of the
mark via a digest" as one way out. Both were said before the design settled and are quoted for
where the idea came from: the ruled design has no outside mark; a work's level is what drops, and
a work that can act never falls below weak by reading. The owner then asked for "a way of
verifying a source before readng it", and answered "Yes" to the coordinator's proposal to reuse
the sureness levels by route. That version still let a raw read take a work to none. Their
correction of the coordinator ("why are calls it made clean? ... A call for searching the web
would contain free text, as would many other calls.") replaced it with a side branch that alone
reads raw text, which they ruled "yes I like it, but it should also be pairing with the source
verification and trusting.", and asked "the branch can just be a spawn right?". On 2026-11-22
they ruled sender and source, and the six details of vouching. This decision states the rule as
those last rulings give it.

**Words.** A work **acts for** the people whose authority it carries (ADR-0368 §2:2), the people
the check runs for (ADR-0368 §7:1 to §7:3): its senders, or a task's author in advance. A
**sender** is ADR-0368's. A **source** is anyone whose text a work reads and whom it does not act
for, a hub person included; **outside text** is a source's text. A **read** is any way a source's
text reaches a model of a work: a call's result, a look-up, recall, or what code puts in front of
the work. A work's **context** is everything its models hold now. A **level** is one of ADR-0366
§5:1's; a work's **sureness** is ADR-0368 §2:3's. To **lower nothing** is to carry no level that
counts toward §6:1. A **line**, a **grant**, a **bar**, **the check** and a **card** are ADR-0367's,
a **yes** a tap on Approve, the **mark** ADR-0370's, and a **place** and its **audience**
ADR-0370 §2's. **Separate work**, **findings**, a **typed value** and a **vouch** are §4:1, §4:1,
§3:2 and §9:1's. **Admits** is ADR-0365's word. In this document a bare section reference, such
as §6:1, is to this decision's own clauses.

## Decision

We will treat a source's text as a stranger's voice that holds no grant, sort every read by its
source in code before it happens, let raw text that is neither typed nor vouched be read only in
separate work that cannot act, have everything a work writes carry the lowest level it held when
writing, check every call at the lowest level a work holds now, and let each person decide through
their own grants what a work at that level may do.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and when, is
> the owner's planning call, made after it merges.

> **Normative.** Until the check runs at the level of a work's context (§6:2), every call is
> checked as it is today, the outside-content stand-in (ADR-0306 §4:4) included for every work,
> and nothing in this decision changes what the running hub reads, shows, allows or asks.

> **Normative.** This decision admits no one. Before a person other than the owner is admitted,
> §2:5 is built; nothing else of this decision is among what ADR-0365 §1:3's provision needs.

ADR-0367 §1's note keeps the stand-in for every work until this decision lands, and that holds
for all of it but §2:5. Without §2:5, an admitted person's own text, read by a work that does not
act for them, would count as "the person's own": planning would be shown it raw, and neither the
digest nor the stand-in would reach it. That is a work acting on another person's words its
sender has not seen (§8:3). ADR-0367 §1:4 names necessary conditions, and §1:4 adds one beside
them, under ADR-0365 §1:3.

### 2. A stranger's voice: sender and source

> **Normative.** A source holds no grant and has no say in a work. Nothing its text says is an
> instruction, carries authority, adds or removes a grant, or counts toward whom a work is for,
> whose authority it carries or its sureness (ADR-0368 §2:4).

> **Normative.** A source's text bears on a work only through the level it carries there, by the
> route it came in (§3 to §7), and on the mark only as ADR-0370 §4:3 counts a record it is read
> from.

> **Normative.** No mark beside the audience mark is added for outside text. What reading it
> does to a call is carried by levels alone (§5, §6).

> **Normative.** A person's writing is a source in every work that does not act for them,
> whatever account it came by, a hub person's linked account included.

> **Normative.** Where an earlier decision reads text as the user's or the person's own, or as
> written by someone other than them, to route it, to withhold it from planning, or to decide
> whether an activation has read outside content (ADR-0306 §4:5, §5:14, §5:16; ADR-0351 §5:1 to
> §5:3; ADR-0356 §3:6), a person's text is their own only in a work that acts for them, and a
> source's in every other.

> **Normative.** The person who forwards, quotes or relays words is the input's sender (ADR-0351
> §4:2), and the words are a source's, whoever wrote them. They carry none wherever they are
> shown, and ADR-0351 §6:2 and §6:5 stand: such an input carries no authority.

§2:1 is the owner's voice that holds no grants: a stranger who walks up and says
something is heard and is not obeyed. §2:3 is "no twin mark needed": the audience mark records
who may see what a work was shown, and no new mark beside it records that a work read a stranger.
§2:5 leaves holders where ADR-0345 §2 puts them: who holds a support and what level a text
carries are two facts, and neither is read as the other. A work holding a forward or a relayed
input holds no grant (ADR-0368 §7:5), so the raw words its planning is shown under ADR-0356 §3:7
reach a work that can do nothing with them but answer its sender (§8:2), and a later work is
shown them withheld (ADR-0356 §3:6) or, if at all, at none.

### 3. Code sorts every read before it happens

> **Normative.** Before a source's text reaches a model of a work, code sorts it by its source,
> with no model, under exactly one of §3:2 to §3:4.

> **Normative.** A **typed value**, a value code reads into a type that can hold no free text,
> such as a time, an amount or a status from a closed set, where the tool's declaration names it
> as typed, is read directly and lowers nothing. Free text in the same result, such as a title,
> is not a typed value.

> **Normative.** A source that a vouch (§9) covers as §9:6 requires, and that code verifies is
> that source when it reads it, is read directly, at the most the route it came by can establish
> (§3:5).

> **Normative.** Any other source's text, and any text code cannot verify, is read only in
> separate work (§4).

> **Normative.** Each kind of connection a source is read through declares in code the most it
> can establish, as ADR-0366 §5:2 has a channel's kind declare it. Where it declares none, or
> declares nothing, a source read through it is sorted under §3:4, whatever vouch covers it.

> **Normative.** No lane builds a direct read §3:2 or §3:3 allows before §6:2 is built and a
> further decision says how such a read reaches planning and amends the clauses that let outside
> text reach planning only as a digest's evidence, among them ADR-0306 §5:14 and §5:16, ADR-0307
> §6:6 and §9:2, ADR-0308 §3:3 and §4:1, ADR-0324 §2:3, ADR-0329 §4:2 and ADR-0356 §5:4. Until
> it merges they stand, and none is amended here.

A forecast's temperature and an appointment's start are typed values; an invite's title and a
web page are not. ADR-0306 set aside a result's shape as what decides digesting, because "shape
mislabels your own free-text notes and an invite's outside title"; §3:2 is about one value's type,
not a result's shape, and leaves an invite's title where ADR-0306 put it. A source read directly
under §3:3 is held at the level its route establishes, so the owner's vouched mailbox, at weak,
holds a work at weak as an email from the owner would (ADR-0366 §5). The owner's "verifying a
source before readng it" is §3:3; their "seperate content verifing call" is a model's check, which
§4:4 rules on. §3:6 holds the direct reads back twice over: before the check reads levels, a
direct read would escape the stand-in, which counts only an outside trigger, digested evidence or
a marked record (ADR-0306 §4:5); and the clauses that keep raw outside text from planning are
spread across the decisions on planning's briefing, whose shapes a further decision owns, as
ADR-0366 §9:8 leaves the shapes of resolving mentions to one.

### 4. Separate work, and what its findings carry

> **Normative.** **Separate work** is a model's reading of a source's text that makes no call
> whose effect, as ADR-0306 §2:1 declares it, is not none, and whose only output to the
> work that asked is its **findings**. The work that asked never holds the text.

> **Normative.** Once built, separate work is a spawn limited to look-ups: it may explore over
> several rounds, making only calls whose effect is none, each checked as every call is, and only
> its findings return to the work that asked.

> **Normative.** Findings in a shape the asking work fixed before the read, which holds no free
> text, lower nothing where code finds them in that shape. Every other finding, an open write-up
> included, carries weak.

> **Normative.** A model's check softens a drop and never undoes it: an open summary or a content
> check carries weak, and passing it through any number of further summaries or checks changes
> nothing.

> **Normative.** Until the spawn is built, the digest (ADR-0308 §4) is the separate work. Its
> evidence is an open write-up and carries weak.

> **Normative.** No lane builds §4:2, the fixed shapes of §4:3 or §6:4's replacement before a
> further decision decides a spawn limited to look-ups, what it is handed, how its findings
> return to the work that asked and in what shapes, how code checks a shape, and how a passage a
> work holds is replaced; and amends ADR-0349 and ADR-0350 as it needs, and ADR-0356 §5:2's
> append-only exchange for a replacement. None of them is amended here.

The digest is the one-round form of separate work the corpus already has: a model call with no
tools over the raw text, whose evidence alone reaches planning (ADR-0307 §9:2, ADR-0308 §5).
It is what the owner meant by "digest", and it is a model's check: its evidence softens the
drop to weak and never undoes it, because it answers in free text. A spawn widens it to several
rounds with look-ups, and a fixed shape, such as a date, an amount, a yes or no, or a pick among
values the asking work gave, is what lets findings lower nothing. A spawn holds the raw text, so
its own level is none (§6:1), and its look-ups are checked there, which is where their bars
decide what it may do.

What the spawn needs and does not have today, as the proposal records: a spawn limited to
look-ups, and findings that return to the asking work in a declared shape. `spawn_task` sets up a
scheduled task (ADR-0350), whose work carries its author's authority (ADR-0368 §6:1) and speaks
only where ADR-0364 §9:4 lets it; neither limit exists. The proposal places it "with ADR-0349's
operations between activations", and §4:6 bars it as ADR-0367 §11:5 bars the grant for one call.

### 5. Text carries its level

> **Normative.** Whatever a work writes, a call's arguments, a message, a note, a summary, a
> task's instruction or a memory, carries the level of the work's context (§6:1) when it is
> written, recorded by code beside it.

> **Normative.** A value code sets, such as an outcome, a time, an identifier or a label, carries
> no level and lowers nothing.

> **Normative.** A record written before its level could be recorded carries weak where it is
> marked as resting on outside content or is an outside episode (ADR-0303 §3, ADR-0307 §4:3,
> ADR-0308 §5:3), and lowers nothing otherwise.

> **Normative.** The level a task records for the work that set it (ADR-0368 §6:1, §6:3) is the
> level its instruction carries under §5:1.

The owner's correction is §5:1: writing to itself and saying things to a person "are just calls",
and their text is written after the read, so it carries what its writer held. A level on what is
written is what keeps a stranger's words from reaching a later work through a note or a task
dressed as the assistant's own.

### 6. A work's level is the lowest of what it holds now

> **Normative.** The **level of a work's context** is the lowest of its sureness (ADR-0368 §2:3)
> and the level each thing in its context carries now: an input its own (ADR-0368 §2:6), what was
> written §5's, a source's text §3's or §4's, and a source's text shown to it otherwise none.

> **Normative.** The check runs at the level of the work's context wherever ADR-0367 §4:1 and
> ADR-0368 §7 have it run at the work's level, and that level is never above the work's sureness.

> **Normative.** Code keeps the level of a work's context from the work's record as what its
> models hold changes, and no model sets, raises or lowers it.

> **Normative.** Where a passage a work holds is replaced by findings about it in a fixed shape
> (§4:3), the passage no longer counts toward §6:1.

Reading never takes a work that can act below weak: text that is neither typed nor vouched
reaches it only as findings (§4), and a source read directly is at weak or above (§3:5). Its
level falls below weak only by its own inputs (ADR-0368 §4:1), or where it is shown a source's
text no rule let it read, which §6:1 counts as none. A ticket's call is checked for its tapper at
the level the tap came by, whatever the work held (ADR-0367 §5:5): the person saw the exact call.
§6:4 is the owner's "sergical context replacement", and its machinery is §4:6's.

### 7. Seen by a person

> **Normative.** Text a work delivered into a place whose audience includes a person (ADR-0370
> §2:1), followed by a later message from that person in that place, counts toward §6:1, in a
> work that acts for that person, at the higher of its own level and the level of that later
> message (ADR-0368 §2:6); in a work that acts for several people, at the lowest of what it counts
> at for each of them.

> **Normative.** Code decides that text was seen so from the records of the delivery and of the
> later message, with no model.

Research then runs as people expect: look around, report, and act on the reply. The person has
read what the work said and spoken again, so what is acted on next is what they were shown, not
what a stranger wrote. The reply is only as sure as its own level: a reply by email, at weak,
lifts the report no higher than weak, since an email reply can be faked (ADR-0366 §5).

### 8. What a work may do once its level drops

> **Normative.** No rule but the check reads the level of a work's context for a call. What a
> work at weak may do is what the grants that apply to the people it acts for allow at weak
> (ADR-0367 §5:1), each set as any line is.

> **Normative.** A work's reply to its own sender in the place the request arrived meets no level,
> whatever the work read: it stays outside the grant check (ADR-0367 §4:7) and is checked against
> the mark (ADR-0370 §5:7).

> **Normative.** A work never acts on another person's words its sender has not seen. Where a
> request depends on another person's answer, that person's own work makes the call under the
> grant for one call (ADR-0367 §11:1, §11:2), or it reaches the asker as a card under their
> profile setting (ADR-0367 §11:4), and no work of the asker's acts on the answer.

Each person decides what weak may do through the grants they already have. A summarised web page
and a possibly faked email then mean the same thing: the instruction might not really be theirs.
Any other call whose grant's bar is above the level of the work's context needs a yes, as
ADR-0367 §5:3 rules, on a card to whose authority the work carries, showing the exact call. §8:2
is ADR-0370 §5:7, "a work can always answer its own sender in the place the request arrived,
inside the mark", carried to levels. §8:3 is why the proposal set aside making another hub person a voice
whose grants the work is cut down to: an asker's *put it in my calendar if Sam says yes* would
then fail, since Sam cannot write that calendar. Until ADR-0367 §11:5's further decision lands, such a
request goes back to the asker.

### 9. Vouching for a source

> **Normative.** A **vouch** is a grant of ADR-0367 §3:1's shape: who, the person or group whose
> works it covers; what, to read one named source directly; how; its bar; its conditions; and who
> set it.

> **Normative.** A vouch is made in a person's own domain, by that person, and covers works that
> carry their authority; or in a group's domain, by a person holding the power to set the group's
> lines (ADR-0367 §6:2), and covers works for that group.

> **Normative.** Only a source code can verify can be vouched for: a web address by its domain, an
> email sender by its signature, the person's own files, or a hub person's linked account
> (ADR-0366 §3). A display name, a claimed sender (ADR-0345 §2:7) or anything else code cannot
> verify never can be.

> **Normative.** A vouch takes ADR-0367 §3:3's conditions and ADR-0370 §6:2's condition of one
> task. Removing it, or its ending, stops reads from then on and changes nothing already read or
> written from it (ADR-0369 §8).

> **Normative.** By default each person's own writing is vouched for in their domain, by a
> default line they may change (ADR-0367 §9:4), and a preset may add vouches (ADR-0367 §9:1).

> **Normative.** A work reads a source directly only where a vouch covers it for every person
> whose authority the work carries, and, for a work for a group, where one in the group's domain
> covers it as well.

> **Normative.** Adding or widening a vouch is a widening: the default grant of the call that
> makes it covers the person of the domain it is made in alone, as ADR-0369 reads a domain's
> person, with a bar of normal, and its how, allowed or allowed with approval, is that person's
> profile setting.

> **Normative.** A vouch covers the whole source, including what it passes along, such as a
> site's readers' comments.

A vouch is the voucher's accepted risk, the comments under an article included, since code cannot
tell an article from its comments on most sites. A work at weak cannot vouch for what it just
read: it falls short of normal and gets a card (ADR-0367 §5:3), and the tap makes the vouch the
person's at the level the tap came by. The bar of normal is the one bar this decision rules;
where every other tool's bar sits stays the owner's (ADR-0367 §4:4). A vouch is a grant under
ADR-0367 §3 and not a source grant: ADR-0097's record lets the hub's reader read a source for a
use, and a vouch says a work may hold a source's text directly (ADR-0367 §14:2).

### 10. What this replaces

> **Normative.** Once the check runs at the level of a work's context (§6:2) for every call the
> stand-in reaches, the outside-content stand-in (ADR-0306 §4:4) retires, and no call is checked
> by ADR-0181 §5:2's lineage floor.

> **Normative.** From then, neither whether an activation has read outside content (ADR-0306
> §4:5) nor any mark saying so of a note, a summary, evidence or an episode decides a call. They
> stand as records of what was read and as what is shown.

A call that leaves the hub, planned over outside text, is then checked as every call is: where
the work holds weak findings and the call's bar is normal, its card goes to the person, showing
the exact call, which is what the stand-in did for every such call; where the bar is weak, it
goes. ADR-0247 §3's exception for a search at the configured provider has nothing left to except,
and whether such a search asks is where its bar sits. This decision lifts no floor of ADR-0154
§4: an egress call at the designated seam is still authorised as ADR-0154 §4:3 rules.

**#2798 and #2856.** This decision answers #2798's authority question: a story's marked summary
stops gating calls, and bears on a work by the level it carries, which separate work can keep a
work from holding. It does not take #2798's line-level marks. It answers #2856's first question,
for calls: an episode shown in the window counts by the level its text carries, which a person's
having seen it (§7) or a fixed-shape replacement (§6:4) lifts. Its second question, whether
remembering the user's own statement inherits the activation's lineage, turns on the memory gate
(ADR-0106 §6:1), which reads the activation-wide fact and is left to a further decision (§14).
Closing either issue is the coordinator's.

### 11. What the earlier lanes left this one

**ADR-0366 §12.** Outside text takes a level on §5:1's scale: the same four, by route (§3 to §6).

> **Normative.** A domain learns a person's name or relation, or a correction to one, only by a
> write a work makes on the authority it carries, checked at the level of its context as any call
> is (§6:2). A source's words reach that write only as §3 and §4 sort them, never as a sender's.

**ADR-0368 §12.** Text read from a source bears on a work's level and never on its authority
(§2:1, §2:2); a sender is someone the work acts for and a source someone whose text it reads;
a forwarded or relayed input is §2:6's.

**ADR-0369 §17.**

> **Normative.** The approval the owner asked for when a work that read outside content widens a
> record (ADR-0369 §5) is ADR-0367 §5:3's card, asked where the level of the work's context is
> below the widening's bar of normal (ADR-0369 §5:3). No other approval is added for having read
> outside text.

**ADR-0370 §13.** Only those a work acts for have a say in it (§2:1). Reading outside text bears
on a send only through the level, in the grant check, and on the mark only as ADR-0370 §4:3
already counts a record (§2:2); a reply to the sender where the request arrived meets no level
(§8:2).

**ADR-0370 §6:4 and ADR-0367 §4:5.** Each keeps something from lifting the stand-in. Once §10:1
retires it, what reading did to a call is a level falling short of a grant's bar, inside the grant
check, which a standing approval never answers (ADR-0370 §6:4) and which no grant answers below
its own bar (ADR-0367 §5:1). Neither clause needs a change.

### 12. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0181,
> ADR-0306 and ADR-0368 and in a dated header note on each, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0181 §5:2, the lineage floor at the egress ruling point, and §5:3, §5:4 and §5:8 to §5:10 as they state and enforce it | For the calls the phases run, once §10:1 retires the stand-in: no ruling reads `planned_with_external_content`, and the level of the work's context, read by the grant check, takes its place (§6:2). §4's computation of the field stands while the field does |
| ADR-0306 §4:1, the stand-in among the checks | Once §10:1 retires it, the stand-in leaves the order. The other checks and their order stand |
| ADR-0306 §4:4, the stand-in | Whole, once §10:1 retires it |
| ADR-0306 §4:6, the fact reaching the policy | In what reaches a rule of authorizing: once §10:1, the fact reaches none, and the check reads the level of the work's context (§6:2) |
| ADR-0368 §6:1 and §6:3, the level a task records | In the addition alone: the level its instruction carries (§5:4), never above the setting work's sureness |
| ADR-0368 §7:1 and its table's level, what the check runs at | In the addition alone: the level of the work's context (§6:2), never above its sureness |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0365 §6's lane 7, outside content | The whole of it |
| ADR-0366 §12's lane 7: whose words teach a name, relation or correction; a level for outside content | §11:1, and §3 to §6 on §5:1's scale |
| ADR-0367 §17's lane 7: vouching, a line of §3's shape; where outside content sets a work's level | §9 and §6. Its §5 note, where a work's own level comes from, is §6:1 |
| ADR-0368 §12's lane 7: how a source's text bears on level or authority; sender against source | §2 and §6 |
| ADR-0369 §17's lane 7: the approval when a work that read outside content widens; vouching | §11:2 and §9 |
| ADR-0370 §13's lane 7: who has had a say; what reading outside text does to a send | §2:1, §2:2 and §8:2 |
| ADR-0306's open question, how a value's source is traced, replacing the stand-in | §5, §6 and §10 |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0306 §4:5; ADR-0303 §3; ADR-0307 §4:3; ADR-0308 §5:3 and §5:4; ADR-0349 §6:13; ADR-0351 §5:13; ADR-0356 §3:7 and §3:8 | Each says when an activation has read outside content or marks what rests on it. They stand as records and as what is shown, and once §10:1 they decide no call (§10:2). ADR-0349 §6:13's last sentence holds while the stand-in does |
| ADR-0306 §4:7 | The message into its input's place stays outside the grant check and meets no level (§8:2) |
| ADR-0306 §5:14 to §5:16; ADR-0307 §6:6 and §9:2; ADR-0308 §3:3, §4 and §5:1; ADR-0324 §2:3; ADR-0329 §4:2; ADR-0356 §5:4 | Outside text still reaches planning only as a digest's evidence; the digest is the present separate work (§4:5), its evidence at weak. §3:6's further decision amends them for the direct reads |
| ADR-0356 §5:2 | The exchange stays append-only; §6:4's replacement waits on §4:6's further decision, which amends it as it needs |
| ADR-0351 §6:2 and §6:5; ADR-0356 §3:6 | §2:6: forwarded or relayed words are a source's, carry none, and give no authority; a later work is shown them withheld |
| ADR-0345 §2 | A support's holder is a fact apart from a text's level (§2) |
| ADR-0366 §5:8 | A text's level says how sure the hub is that what it holds is its people's own, which is about whom something comes from |
| ADR-0367 §4:5 and ADR-0370 §6:4 | Their stand-in limbs hold while the stand-in does, and need no change after (§11) |
| ADR-0367 §11 | §8:3 rests on it; §11:5's bar stands |
| ADR-0247 §3 | Its exception has nothing to except once §10:1; §3:2's retirement of the coverage exception is untouched |
| ADR-0154 §4 | Untouched: no floor of it is lifted (§10) |
| ADR-0106 §6:1 | The memory gate keeps reading the activation-wide fact until a further decision (§14) |

### 13. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made by
the lane the owner's planning dispatches, under this decision once merged, or under the further
decision §4:6 names. A new Protocol ships as a triad.

- **A level on what is written:** beside each note, message, summary, call's recorded values,
  task instruction and memory, set by code (§5). The enumeration is ADR-0366 §11's.
- **The level of a work's context:** kept on the activation's state and its episode (§6), read by
  the check beside what ADR-0367 §16 and ADR-0368 §11 give it. With the stand-in's retirement,
  ADR-0181 §5's floor leaves `ActionPolicy` and `ActionPolicyContract`, and no rule of authorizing
  reads `planned_with_external_content` on `EgressBinding`.
- **Sorting:** a tool's declaration naming which of its result's values are typed, beside ADR-0306
  §2's result property (§3:2); each kind of connection's declared most (§3:5), beside ADR-0366
  §11's; and code's verification of a source by domain, signature, file owner or account (§9:3).
  Each waits on §3:6's further decision for how a direct read reaches planning.
- **Vouches:** a kind of ADR-0367 §16's line, with §9:5's default line and §9:7's profile setting.
- **Seen by a person:** a record linking delivered text to a later message from its person in that
  place (§7).
- **The spawn and fixed shapes:** wait on §4:6's further decision.

### 14. What this decision leaves to others

- **A further decision:** how a direct read reaches planning, amending the clauses §3:6 names;
  the spawn limited to look-ups, what it is handed, its findings and their
  shapes, how code checks a shape, and replacing a passage (§4:6), amending ADR-0349 and ADR-0350;
  whether the memory gate (ADR-0106 §6:1) reads levels in place of the activation-wide fact, which
  #2856's second question needs; how a standing rule's work reads an outside signal's text
  (ADR-0368 §12); how a mail channel establishes a sender (ADR-0351 §3:3, ADR-0368 §9:8), which
  §9:3's email signature does not decide; whether ADR-0154 §4's floor is lifted (ADR-0154 §4:4);
  and a shared place's own history ([#3636](https://github.com/leonapivato/ai-assistant/issues/3636)),
  on ADR-0369's ground.
- **The owner:** where every bar but a vouch's sits (ADR-0367 §4:4); the vouches presets hold
  (§9:5); the default of §9:7's profile setting.
- **The next prompt review:** how earlier text that carries weak and has not been seen is shown,
  how a level, findings or a withheld source are shown, and the wording.
- **Left out by the owner:** injection hardening beyond this decision; the public web door;
  forgetting; two equal owners.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 15. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3 and §1:4**: nothing changes until the check reads levels, and §2:5 is built before a
  second person is admitted, as the one part of this decision that provision needs.
- **§2:2**: a source bears on the mark only as ADR-0370 §4:3 already counts. **§2:5**, whose
  text is a person's own when there are several people. **§2:6**:
  forwarded or relayed words carry none, and ADR-0351 §6:2 and §6:5 stand rather than giving
  such an input its sender's authority at a lower level.
- **§3:6**: the direct reads wait on the check reading levels and on a further decision that
  amends the routing clauses, rather than this decision superseding each of them.
- **§3:2's** typed value as a value whose type holds no free text, named in the tool's
  declaration. **§3:5**: each kind of connection declares its most, and a route at none is not
  read directly even when vouched, since it verifies nothing.
- **§4:1's** separate work as a reading that makes no call with an effect; **§4:3's** fixed shape
  as one that holds no free text, checked by code; **§4:5**, the digest as today's separate work,
  its evidence at weak; and what **§4:6** leaves to the further decision.
- **§5:3**, the level of a record written before levels: weak where marked, nothing otherwise.
  **§5:4**, a task's level as its instruction's.
- **§6:1's** term, the level of a work's context, kept apart from ADR-0368 §2:3's sureness so that
  sureness is not redefined; and a source's text shown with no rule letting it at none.
- **§7:1's** narrowing of "seen by a person" to the people a later work acts for, each of them,
  and its cap at the level the person's later message came by.
- **§8:1** as the replacement of the stand-in by the check alone.
- **§9:2**: a person's vouch covers works carrying their authority and a group's covers works for
  the group; **§9:5's** default as a line its person may change; **§9:6's** reading of "for a
  group's domain its manager vouches" as a further vouch, beside every person's own; and
  **§9:7's** default grant, by ADR-0369 §5:3's pattern.
- **§10:2**: the activation-wide fact and the marks stay records and stop deciding calls, rather
  than being removed, and the memory gate is not reached. **§11:1**: a name, relation or correction is
  taught by a write at its context's level. **§11:2**: the approval for a widening is the
  shortfall card, and no other.
- **Which header records**: none on ADR-0349 or ADR-0350, whose amendment the spawn's further
  decision makes, so ADR-0349 §6:13 is read through rather than superseded; and §4:6 naming
  ADR-0356 §5:2 among what that decision amends, for a replacement.

## Consequences

- A stranger's words, a web page, a possibly faked email and another person's message all reach a
  work in one way: sorted by code, read directly only where typed or vouched, and otherwise only as
  findings. No work that can act holds raw text it may not trust.
- The mark that covered a whole activation and spread to later works, tasks and matters no longer
  decides calls. A work holds weak only while it holds weak text, and a person's reply or a
  fixed-shape replacement lifts it.
- Each person decides what a work at weak may do for them, through bars on their own grants, with
  no rule of its own. The vouch's widening at normal is the one bar ruled here.
- Research works as people expect: look around, report, act on the reply.
- What a work writes carries what it held, so a task, a note or a summary written after a read
  cannot pass a stranger's words off as the assistant's own.
- Until the spawn's further decision lands, the digest is the only separate work, so findings are
  open and a work that read anything unvouched holds weak.
- Nothing changes in the running hub until the owner's planning dispatches the build (§1:3), and
  no second person is admitted before §2:5 is built (§1:4).
- **Revisit** if cards from works at weak become a habit people tap through, or once the spawn's
  fixed shapes show which questions they can answer.

## Alternatives considered

- **Raw outside text: read it and carry on with reduced authority.** Set aside: whatever that
  work then writes carries the stranger forward. Taken: read only in work that cannot act (§4).
- **A record of calls is clean.** Set aside by the owner: "why are calls it made clean?". Taken:
  text carries its level (§5).
- **A twin mark for outside content beside the audience mark.** Set aside by the owner's "no twin
  mark needed": levels carry it (§2:3).
- **Another hub person's text: a voice whose grants the work is cut down to.** Set aside: an
  asker's *put it in my calendar if Sam says yes* then fails, since Sam cannot write that
  calendar. Taken: a source (§2:4, §8:3).
- **What a vouch covers: only the source's own words.** Set aside: code cannot tell an article
  from its comments on most sites. Taken: the whole source (§9:8).
- **A model's check restores the level.** Set aside: a model's judgment alone never gives the
  level back; it softens a drop to weak (§4:4).
