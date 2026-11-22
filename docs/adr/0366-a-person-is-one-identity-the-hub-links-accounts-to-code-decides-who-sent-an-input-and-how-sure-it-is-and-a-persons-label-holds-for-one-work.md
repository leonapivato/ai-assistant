# 366. A person is one identity the hub links accounts to, code decides who sent an input and how sure it is, and a person's label holds for one work

- Status: Proposed
- Date: 2026-11-22
- Scope: lane 2 of the seven decisions the people, authority, audience and outside content
  proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)), the lane
  [ADR-0365](0365-one-hub-serves-several-people-each-is-the-top-of-their-own-domain-and-separate-households-keep-separate-hubs.md)
  §6 names first. It decides what a person is to the hub (§2), linking an account as a
  privileged act (§3), that code decides who sent an input (§4), the four levels of sureness
  (§5), that an account is only as sure as it is exclusive (§6), a person's identity apart
  from what each domain knows of them (§7), a person's label as a handle for one work (§8),
  and understanding resolving the people a stimulus mentions (§9). §10 records what it does
  to earlier decisions, §11 the contract changes it would need, §12 what it leaves to
  others, and §13 what it settled where the rulings left a point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the
  coordinator. Their words, verbatim. On sureness: "Yes but also not fully. An email from me
  is likely me, but also more likely to be faked or hacked then if I was standing in my home
  using the home device with voice and face recognition.", then, to the design, "yes record
  it" (2026-11-19; §3 to §5). On exclusivity: "yes record both — for the account is only as
  sure as it is exclusive, I agree, this seems like a binary right?", and on the kids texting
  from mom's phone, "Im leaning towards not supporting it" (2026-11-19; §6). On resolving
  mentions: "its understandings job to connect mentions of people to UUIDs right, so if I say
  tell Sam something, then it connecst Sam to my roommate, not my long lost cousin."; "yeah,
  and it can just give top candidates for this user regarless of what the input message is
  anyway right?"; "I think understanding should still attempt first though, then planner
  doesnt have to waste rounds when its easy, what do you think?"; "planning should just get a
  new context section given from the system for the related users, no?" (2026-11-19; §9). On
  what the People section holds and how labels are given out: "It can change per person too,
  so I guess the specifics dont need to be flushed out right now. Well do that when we revist
  the prompts" (2026-11-19; §8:5, §9:7). On labels, after asking "what is the label for?":
  "Yes, per work" (2026-11-22; §8). On person records: "I agree with all of them except for
  the domain one" (2026-11-21; §2, §7:7); on the domain point, "its just in scenarios where
  both users know the person, but the person only sits in 1 domain, just because only one
  user has mentioned them, it can get confusing" and "I think the important thing is pre-set
  rules. So each individual has their own rules on what is shared and with who? what do you
  think" (2026-11-21); and on identity apart from each domain's view, "Yes, adopt it"
  (2026-11-22; §7). The coordinator assigned 0366 and ratifies it, under the owner's
  delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type,
  field or code. It decides what a person is to the hub and how the hub tells who it is
  dealing with, which bounds the `core` types the later lanes and the build make, so it takes
  the adversarial and the architecture review. Building it is a breaking change under golden
  rule 5, through the `core` changes §11 names; some of them wait on a further decision
  (§9:8), and none is made here. It dispatches no implementation (§1:2).
- **Partially supersedes**
  [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md)
  (§4:1, in its second sentence), as §10 records.

## Context

ADR-0365 let one hub serve several people and left lane 2 "what a person record is, linked
accounts and linking, and how sure the hub is of who sent an input" (ADR-0365 §6). It also
kept §1:3: "This decision alone admits no one."

**The code today** has one person. `OWNER_PERSON_ID` in `core/types.py` is "The one person's
id: the owner's, the one person the store holds before a decision on members". `Person` is
keyed by it, with a `PersonRole` whose one member is `OWNER`. `activation_person` in
`orchestration/person_block.py` returns `OWNER_PERSON_ID` where the trigger's kind
establishes the user, was pushed by a connected source or is the owner's task, and `None`
otherwise. `LabelKind.PERSON` is documented as "A person, ``P1`` the owner, a stable label
over ADR-0345 §2:5's identifier, the same in every work", and planning's briefing mints it
first in every work: "ADR-0364 §4:1: ``P1`` is the owner, the same in every work, so it is
minted first."

**What the corpus waits on.** Several ratified clauses name a later decision on people:

- ADR-0099 §5 deferred "Person identity, enrolment, and speaker identification" to the voice
  work (#691). ADR-0365 §7 fired its identity and enrolment half for this lane and kept
  speaker identification with the voice work.
- ADR-0345 §2:5: "Until a decision on identified people adds others, the one person a holder
  names is the owner, and the identifier that names the owner is a composition-root
  constant." ADR-0345 §2:9 holds "which person an identifier belongs to" as "a link held
  outside the support, by a later decision on identified people", and ADR-0345 §9:3 holds
  which subject names are one person the same way. ADR-0351 §3:2 limits an input's person
  party to the owner on the same condition. (ADR-0365 §6 and §7 cite the phrase as ADR-0345
  §2:1; it stands in §2:5, §2:9 and §9:3.)
- ADR-0338 §2:1: "The store holds one person, the owner, … and no lane adds another person
  before a decision on members does".
- ADR-0100 §6 stores a belief's subject label verbatim, "resolving to nothing", and reserves
  matching and resolving labels to "a later ADR"; ADR-0101 §3 lifts that for comparison alone
  and forbids subject matching from consulting "a person record, a registry, an alias or
  nickname table". ADR-0101 §10 says the rest "Fires with whatever ADR decides person
  identity".
- ADR-0364 §4:1 made `P1` the owner in every work, and ADR-0364 §4:4 left "understanding
  resolving who a mention means" to "its own decision".
- ADR-0292 §5:3 gives every input's author a **how sure**: established, claimed or unknown.
  ADR-0351 §6:1 gives an input the user's authority only where its author is established as
  the user. The owner, ratifying that, kept it "all or nothing" "for now", "but eventually I
  think there can be levels to authority".

**What the owner decided.** In the walk of 2026-11-19 the owner ruled that a person is a
record with linked accounts, that only a person with the power to links one, and that code
decides the sender. They ruled that being established comes in levels: "An email from me is
likely me, but also more likely to be faked or hacked then if I was standing in my home using
the home device with voice and face recognition." They ruled that an account is only as sure
as it is exclusive, and asked "this seems like a binary right?". They gave understanding the
job of resolving mentions, "so if I say tell Sam something, then it connecst Sam to my
roommate, not my long lost cousin", and planning a section of its own for the people a work
relates to. On 2026-11-21 they agreed the person records design except its domain point, and
on 2026-11-22 adopted keeping who someone is apart from what each domain knows of them. On
labels they asked "what is the label for?" and ruled "Yes, per work".

**Words.** An **identity** is the hub's record that one real person exists (§2). An **account
identifier** is a hard identifier an account is known by, such as a phone number, an email
address or a messaging account's id. A **link** ties an account to an identity, so that what
arrives by that account is from that person (§3). A **view** is what one domain knows about a
person (§7). **Sureness** is how sure the hub is of who something comes from (§5). A **kind**
is a kind of channel, as ADR-0292 uses the word. The **work** is the activation planning
plans, as ADR-0364 uses the word. **Admits** is ADR-0365's word. A **later decision** is one
of lanes 3 to 7 of #3629, none of which has a number yet. In this document a bare section
reference, such as §5:2, is to this decision's own clauses.

## Decision

We will make a person one identity for the whole hub, with the accounts linked to it, have
code alone decide who sent an input and how sure it is on a scale of four levels, keep what
each domain knows of a person apart from the identity, make a person's label a handle for one
work, and give understanding the job of resolving the people a stimulus mentions.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and
> when, is the owner's planning call, made after it merges.

> **Normative.** This decision admits no one and does not provide for admitting another
> person under ADR-0365 §1:3, and no lane cites it as doing either.

Who may add a person and what a new person starts with are lane 3's, and whose work a work is,
lane 4's. A person other than the owner can be identified by a link only once a later decision
says who may link one (§3:3), and admitted only once ADR-0365 §1:3's provision is made and
built.

### 2. A person is an identity

> **Normative.** Every person the hub knows of, admitted or merely mentioned, is one
> identity: a stable identifier and the account identifiers known to be that person's.

> **Normative.** An identity holds no name, relation or other fact about its person, and
> belongs to no one's domain. What a domain knows of the person is that domain's view (§7).

> **Normative.** An identity's identifier never changes and is never reused. Linking an
> account and admitting the person keep it; a merge (§7) keeps both identifiers, each then
> naming the merged identity, and undoing the merge returns each to its own.

> **Normative.** Code creates an identity for someone merely mentioned, automatically, with
> no link and no grant. Creating one admits no one and needs no person's act.

> **Normative.** The owner's identity is named by the identifier ADR-0345 §2:5 names, so no
> record written under it is rewritten.

> **Normative.** An identity is not a person in ADR-0338 §2:1's sense. Creating one adds no
> person model, and ADR-0338 §2:1's bar on adding a person stands until a later decision
> provides for admitting another and that provision is built.

### 3. Linking is a privileged act

> **Normative.** A link is made only by a person who holds the power to make it, by their
> own act. Making an identity one the hub admits is the same.

> **Normative.** The system may suggest a link, by an approval card (ADR-0361) to a person
> who holds the power, and never makes one. No model links, and no code links by itself.

> **Normative.** Until a later decision says who holds the power §3:1 names, only the owner
> links, and only accounts to the owner's own identity.

Who holds the power, how it is handed on, and who may undo a link are lane 3's. Attaching two
views on a matching account identifier (§7:2) is not a link, and makes no one a sender.

### 4. Code decides who sent an input

> **Normative.** Code decides who sent an input from the account it arrived by: the person
> whose identity a link ties that account to, and no identified person where no link does.

> **Normative.** No model decides or changes who sent an input, and nothing an input says,
> such as a signature or "it's the cleaner", counts toward it (ADR-0292 §5:8).

Which parties an input records, whether its author is established or claimed under ADR-0292
§5:3 and ADR-0351 §3, whom a work is for and whose authority it carries are not changed here
(§10). Lane 4 decides what a work carries.

### 5. Sureness, in four levels

Being established comes in levels. The owner's words: "An email from me is likely me, but
also more likely to be faked or hacked then if I was standing in my home using the home
device with voice and face recognition."

| Level | Meaning | Examples |
| --- | --- | --- |
| None | Claimed or unknown | "It's the cleaner" from an unlinked number |
| Weak | Established by a linked account, or other means, whose sender can be faked or that is commonly broken into | Email, SMS |
| Normal | Established by a linked account, or other means, behind its own login | A messaging account, an enrolled phone |
| Strong | Several independent signals at once, or a fresh check | A home device with voice and face; a fingerprint just now |

> **Normative.** Sureness has four levels, ordered from least to most: none, weak, normal and
> strong, each meaning what the table's row for it says. Every decision that names a level
> names one of these four.

> **Normative.** Each kind declares the most sureness it can give, in code, beside how it
> establishes authors (ADR-0292 §5:4). A kind with no such declaration gives none.

> **Normative.** A link's level is its kind's declared most, or the lowest level any lowering
> that stands on it sets (§5:5), whichever is lower. Nothing raises it above that most.

> **Normative.** Independent signals for one person that arrive together, such as a linked
> device and an enrolled voice, combine by one fixed rule in code. No model takes part in it,
> its result is never above strong, and it reaches strong only as the table's row for strong
> describes.

> **Normative.** The owner, or the person a link identifies, may lower that link's level.
> Each lowering stands until whoever made it withdraws it.

> **Normative.** Code sets an input's level, as identifying who sent it, from the link it
> arrived by, combined by §5:4's rule with any independent signal for the same person that
> arrived with it. An input that arrived by no link is at none.

> **Normative.** No model sets, raises or lowers a level, and nothing an input says counts
> toward one.

> **Normative.** A level is a fact about how sure the hub is of who something comes from. What
> a level permits, what a work carries, and what a shortfall does are not decided here, and
> no lane reads them out of this decision.

This decision gives levels to links and to the inputs a person sends. It gives nothing else
one, and a later decision may use the same scale for other things, such as what is read from
outside. A spoke's evidence counts as a signal only where ADR-0292 §5:10 lets it. Sureness
that fades with time is left out by the owner.

### 6. An account is only as sure as it is exclusive

> **Normative.** An account someone other than its person may send through cannot establish
> its person. A link to such an account gives none while the hub holds any record of that
> use.

> **Normative.** Every account linked to identify someone is, by default, that person's own
> only: the link records no one else as sending through it. The default is not a marking
> anyone sets.

> **Normative.** An input from an account is the input of the person its link names.
> Speaking for someone else from their account, such as "this is the kids talking" from
> mom's phone, is not supported, and nothing an input says makes it another person's.

The owner asked "this seems like a binary right?": an account is exclusive or it is not.
Where access the hub cannot see makes it less than exclusive, such as a passcode another
person knows or an address several people share, the owner or its person lowers the link
under §5:5. How a grant bears on an account that is its person's own only is lane 3's.

### 7. Identity apart from what each domain knows

> **Normative.** A view is what one domain knows about a person: the name that domain uses,
> the relation and the facts. It is held in that domain, under that domain's sharing rules,
> and is never part of the identity.

> **Normative.** Two views attach to one identity where both hold the same account
> identifier and no record the hub holds marks that identifier as used by more than one
> person. Code attaches them, silently, and never on a name, a relation or any other fact;
> no model attaches them.

> **Normative.** A match that would join two identities each of which has a link, or is one
> the hub admits, is never attached silently. It is a merge, under §7:5 and §7:7.

> **Normative.** Attaching two views shows neither domain anything of the other's view.

> **Normative.** Two identities §7:2 does not join stay two until a person who may see a view
> of each confirms a merge, by their own act.

> **Normative.** The system suggests a merge only to a person who may see a view of each
> identity, and only from what that person can already see.

> **Normative.** A merge that joins an identity with a link, or one the hub admits, is also a
> privileged act under §3:1.

> **Normative.** A merge can be undone. Undoing it restores the two identities, with the
> account identifiers, links and views each held before.

> **Normative.** The person whose domain holds a view that code attached may detach it, which
> leaves that view on an identity of its own.

An account identifier several people share, such as a household's landline or a business's
address, is what §7:2's second condition keeps from joining two people, and §7:9 undoes a
wrong attachment the hub had no record to prevent. What a person may see of another domain,
and so who may confirm a merge, is lane 5's. The
owner's worry, "both users know the person, but the person only sits in 1 domain, just
because only one user has mentioned them", is what the split answers: each domain has its own
view, and the identity behind them is one.

### 8. A person's label is a handle for one work

A label is how a model points at one exact person in a form code can check.

> **Normative.** A person's label is a label under ADR-0307 §5, as every other kind is: it
> holds for one work, the hub maps it to the stored identifier, and a call naming a person's
> label the work was not shown is refused as ADR-0307 §5:3 rules.

> **Normative.** Code swaps a person's label for the stored identifier in anything a work
> writes, save the record of the work's own exchange as handed in (ADR-0356 §13:6), which keeps
> its labels beside the identifiers they name (ADR-0307 §5:7).

> **Normative.** A later work shown anything an earlier work wrote, that work's exchange
> included, is shown each person by the later work's own label, through the stored
> identifier.

> **Normative.** Only the stored identifier is stable. No person's label is the same in
> every work by rule, and no decision relies on one being so.

> **Normative.** This decision rules nothing about which label a person gets in a work, the
> order labels are given out in, or what is shown beside one.

The owner deferred the last to the next prompt review: "It can change per person too, so I
guess the specifics dont need to be flushed out right now. Well do that when we revist the
prompts". `G` labels for groups are lane 3's.

### 9. Understanding resolves the people a stimulus mentions

> **Normative.** Understanding resolves each person its stimulus mentions to a stored
> identifier, with one of three outcomes: a clear pick; a probable pick, with the runner-up
> and the reason; or unknown.

> **Normative.** The candidates understanding picks among are found by code, with no model
> call, from the sender's most frequent people, names matched against a names table, people
> already labelled in the context understanding is shown, and the input's own metadata.

> **Normative.** Understanding picks among the candidates code gave it, and code maps the
> pick to the stored identifier. A pick that names no candidate is unknown.

> **Normative.** Understanding attempts every mention in its stimulus before planning runs.

> **Normative.** Planning has a people look-up, run by code, to resolve further a mention
> understanding left probable or unknown.

> **Normative.** A resolution only picks a target. Whatever check a call is subject to runs
> on the person the call actually names, never on the resolution, so a wrong pick is a
> mistake and never a way round a rule.

> **Normative.** Planning is given a People section in its briefing, built by code. What it
> holds, beyond naming the people the work relates to, is not decided here.

> **Normative.** No lane builds §9:1 to §9:7 before a further decision settles what
> understanding and planning are shown of the candidates, how understanding's reply carries a
> resolution and what the people look-up's call is, and amends ADR-0353 §2:1, §3:6, §9:1 and
> §9:2 and the decisions on planning's briefing and tools as it needs. Until it merges,
> understanding's input and reply stay as ADR-0353 rules.

The owner's words: "I think understanding should still attempt first though, then planner
doesnt have to waste rounds when its easy". Candidates come only from what the work may read,
which is lane 4's and lane 5's to rule; this decision widens no read. Whose words may teach
the hub a name, a relation or a correction is lane 7's. ADR-0353 has understanding's input be
its sections "and nothing else" (§2:1) and its reply "exactly the six keys" (§9:1), and the
owner left "what is put in front of a model and what it fetches" to the next prompt review, so
§9:8 leaves the shapes to a further decision rather than superseding those clauses here.

### 10. Relationship to earlier decisions

> **Normative.** No identity, view, names table or resolution is consulted to resolve, alias
> or match a belief's subject label or a memory's subject or involved name. ADR-0100 §6,
> ADR-0101 §3 and ADR-0345 §9:3 stand, and this decision does not lift their reservation.

> **Normative.** This numbered draft records its replacement on ADR-0364's status line and
> in a dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> ADR-0364's ratified body. The replacement takes effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0364 §4:1, its second sentence: "`P1` is the owner, a stable label over ADR-0345 §2:5's identifier, the same in every work." | Superseded by §8. Its first sentence, the `P` label kind in `LabelKind` as `PERSON`, stands |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0099 §5's third deferral | Person identity (§2) and enrolment (§3). Speaker identification stays with the voice work (#691): what a voice or face signal is and how an utterance is attributed by one. Once built, linking such a signal to a person is a link under §3 and its kind declares its most under §5:2 |
| ADR-0364 §4:4, "understanding resolving who a mention means" | §9 is the decision it names. §4:4's bar on building it under ADR-0364 stands, and `G` labels stay lane 3's |
| ADR-0345 §2:9, "a link held outside the support" | §3's link: an identifier a holder carries belongs to the person whose identity a link ties that account to. A view's account identifier attributes no holder |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0345 §2:5, and ADR-0351 §3:2's second sentence | §1:3 adds no one, and §3:3 links no account to anyone but the owner. Each stands until a person other than the owner is linked under a power a later decision provides. The owner's identifier stays the constant ADR-0345 §2:5 names (§2:5) |
| ADR-0345 §2:7, a claimed source "becomes the same only by the owner's act linking the two" | The owner's act is §3's link, which only the owner makes until a later decision (§3:3). Lane 3 records whether it becomes the act of whoever holds the power |
| ADR-0345 §9:3, ADR-0100 §6 and ADR-0101 §3 and §10 | §10:1. ADR-0101 §10's deferral fires with this decision, which decides person identity, and takes none of it: aliasing and resolving a subject label to a person stay reserved |
| ADR-0338 §2:1 to §2:5 | §2:6 for §2:1. Whom an activation is for is lane 4's |
| ADR-0292 §5:3, §5:4, §5:5 and §5:10; ADR-0351 §3:3 and §6 | A level is a fact about identification (§5:8). How the levels bear on an author's established or claimed, on an input's parties and on authority, including whether a linked mail account's weak names its person rather than a claimed source, is lane 4's |
| ADR-0124 §5 and ADR-0094 §10 | A device's identity is not its person's (ADR-0099 §5). A device linked to a person is a link under §3 |

### 11. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made
by the lane the owner's planning dispatches, under this decision once merged, or under a
further decision where its shape is not settled here. A new Protocol ships as a triad.

- **An identity and its links:** a type for an identity (§2:1), its account identifiers, and
  each link's kind and standing lowerings (§5:3, §5:5), with a store for them, a new Protocol
  or members of `PersonModelStore`. `OWNER_PERSON_ID` keeps its value (§2:5).
- **The levels:** a closed enumeration of the four levels (§5:1), and each kind's declared
  most beside its declarations in `core/channel_validation.py` (§5:2). Where an input or a
  work records its level is lane 4's.
- **A view** (§7:1), which waits on lane 5's domain and sharing types.
- **Understanding's resolution:** `ProposedActivationUnderstanding` and
  `ActivationUnderstanding` gain a resolution per mention (§9:1), retained with the episode
  as the understanding is, and understanding's input gains its candidates. Both wait on §9:8's
  further decision, which amends ADR-0353's reply and input.
- **Planning:** a people look-up tool (§9:5) and a People section in the briefing (§9:7),
  each waiting on §9:8's further decision; and, needing none, the label book stops minting
  the owner's label first, and `LabelKind.PERSON`'s documentation stops calling `P1` stable
  (§8).

### 12. What this decision leaves to others

Each is left, by ADR-0365 §6's cut or by the owner:

- **Lane 3:** who holds the power to link and to admit (§3:1), how it is handed on, who may
  undo a link, how a grant bears on an account that is its person's own only (§6:2), what
  level a grant accepts and the card when a level falls short, groups and `G` labels.
- **Lane 4:** what a work carries, including how sure it is and whom it is for, and the
  amendments to ADR-0351 §6 and ADR-0338 §2 that would follow; how a level bears on ADR-0292
  §5:3 and ADR-0351 §3; that the People section, the tool list and the connections are
  filtered to the work's authority.
- **Lane 5:** sharing rules, so what a view shows another domain and who may see both sides
  of a merge (§7).
- **Lane 7:** whose words teach the hub a name, relation or correction, and whether outside
  content takes a level on §5:1's scale.
- **The next prompt review:** which label a person gets, and what the People section holds
  (§8:5, §9:7).
- **Left out by the owner:** sureness that fades with time; voice and who is present in a
  room, with speaker identification staying with the voice work (#691); two equal owners.

> **Normative.** This decision may not be cited to settle any matter the list above leaves
> to another.

### 13. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3**, that this decision does not provide for admitting another person: from the
  coordinator's brief, since who may add a person is lane 3's.
- **§2:2's "belongs to no one's domain"** read as the identity being outside every domain's
  sharing rules, and **§2:3**, that a merge keeps both identifiers and its undoing returns
  each to its own.
- **§2:5 and §2:6**: the owner's identity takes ADR-0345 §2:5's identifier, and an identity is
  not a person model.
- **§3:3**, that until lane 3 only the owner links, and only to the owner.
- **The meaning column of §5's table** worded so that a level is not only ever a connection's:
  "a linked account, or other means".
- **§5:3 and §5:5's second sentence**: a link's level is the lower of its kind's most and the
  lowerings that stand, and each lowering is withdrawn only by whoever made it. Which fixed
  rule §5:4 is, is the build's.
- **§5:6**, that an input arriving by no link is at none.
- **§6:1's "while the hub holds any record of that use"**, as how code knows of a use.
- **§7:2's second condition and §7:3**, that an identifier on record as shared joins no one
  and that a match between two linked or admitted identities is a merge; **§7:4**, that
  attaching shows neither domain the other's view; **§7:8's** content of an undo; and
  **§7:9**, detaching a view.
- **§8:1**, returning a person's label to ADR-0307 §5's rules for every label, and **§8:2's**
  exception for the exchange recorded as handed in.
- **§9:2's list** as the starting sources, from the proposal; **§9:3**, that code maps
  understanding's pick and a pick off the list is unknown; **§9:7**, that a People section
  exists while its contents wait for the prompt review; and **§9:8**, leaving the shapes of
  understanding's input and reply, the People section and the look-up to a further decision.
- **§10:1**, keeping the subject axis as it stands.
- **When code creates an identity for someone mentioned** (§2:4) is the build's.

## Consequences

- A person other than the owner now has a shape: an identity, the accounts linked to it, and
  a view in each domain that knows them. Lane 3 can say who may link and admit, and lane 4
  what a work carries, each citing §5:1's levels without redefining them.
- Code, not a model, says who sent an input and how sure it is. A wrong guess by understanding
  picks a wrong target and gets past no rule (§9:6).
- Every person's label holds for one work, so the numbering reveals nothing about people a
  work may not see, and nothing the build writes depends on `P1` being the owner.
- Nothing changes in the running hub: §1:3 adds no one, §3:3 links nothing new, and nothing
  is built until the owner's planning dispatches it.
- Mentioned people get identities automatically, so the same person can be two identities
  until a merge. That is the cost of never joining on a name.
- **Revisit** if a kind needs sureness that fades with time, or once the voice work builds
  speaker identification, which will declare its signals' most under §5:2.

## Alternatives considered

- **A model decides who sent an input.** Set aside: a model can be talked into anything, and
  the corpus already has content never establish an author (ADR-0292 §5:8).
- **Established or not, as ADR-0351 §6 has it today.** Set aside for identification: the
  owner's email and the owner at a home device with voice and face are not equally sure.
  Authority stays lane 4's.
- **A person's label: one fixed number per person.** Set aside: gaps in the numbering show
  how many people a work may not see. Taken: a handle for one work.
- **The same person known to two people: a record per domain, never joined.** Set aside:
  sharing then shows the person twice. **One shared record with visibility per field.** Set
  aside: whoever wrote first sets the name. Taken: one identity, a view per domain.
- **Supporting speech for someone else from their account**, such as the kids from mom's
  phone, with the lower of both people. Set aside by the owner: a message from an account is
  its person's.
