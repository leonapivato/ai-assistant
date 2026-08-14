# 150. The egress binding is one validating value, and nothing in it is stated twice

- Status: Proposed
- Date: 2026-08-14
- **Decides surface (a) of ADR-0148 §11** — the **egress binding**: a value
  carried as a field of `ActionRequest`, compared by
  `PermissionDecision.authorises`, and transcribed verbatim into
  `PermissionDecision` by `from_request`. §11's second clause requires that
  surface to be decided in a contract ADR of its own, ratified and merged before
  anything implements against it (golden rule 5, ADR-0015 §5). This is that ADR.
- **Decides ADR-0146 §8's deferred provenance marker** — the marker that carries
  a span's discloser provenance to an egress boundary. ADR-0148 §11's last
  paragraph declined to rule whether that marker and surface (a) are one, on the
  ground that it "is the same lane's decision, made with the same producer in
  hand". The producer is now in hand (PR #1120), so §5 rules it: the marker
  **rides inside (a)**, as a field of each span of the payload description, and
  there is no separate marker type and no separate carriage.
- **Does not decide surface (b)** — the seam by which the binding is obtained
  from `tools/` before `ActionPolicy.decide` is reached. That is its own contract
  ADR under the same clause, and §11 below states what this decision leaves it,
  including one obligation the producer discovered that (b) cannot avoid.
- **Designates nothing and authorises no byte.** ADR-0017 §2 reserves designation
  to a later ADR that names the seam module and attests each §3 condition is
  satisfied **in code**; this ADR supplies a value. `tools/` still transmits
  nothing.
- **No implementation lands with it.** No `src/`, no `tests/`, no
  `pyproject.toml`. §12 says what the implementing lane owes and §2 fixes exactly
  which `core` names it is authorised to change — the whole of that authorisation
  and no more.
- **No `core/protocols.py` change is authorised by this ADR**, and none is
  needed: (a) is a value, not a seam. §11 records what follows for ADR-0137 §2's
  triad.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-14**,
  the durability form ADR-0100 established and ADR-0149 last applied. This
  decision rests most heavily on ADR-0148 and ADR-0146, and on ADR-0021 §1 as
  ADR-0148 §6 amended it; a citation that silently means "whatever that ADR says
  when you read it" is not checkable.
- **Records owed on other ADRs: none, and §13 shows the working** rather than
  asserting it. In particular the ADR-0082 §1 record ADR-0148's Consequences
  anticipate against ADR-0021 §1 is **already written** — ADR-0148 §12 wrote it
  and the note on ADR-0021 §1 names every argument value this binding stores — so
  this ADR adds nothing there. No `Status` line moves and no ratified text is
  rewritten anywhere.

## Context

### What is deferred to here, in ADR-0148's own words

ADR-0148 decides how an egress call is authorised, bound and audited, and its §6
puts three of ADR-0017 §3's four bound facts into one value:

> The remaining three facts travel together as one value, the **egress binding**:
> the canonical destination set with the supplied form each member came from
> (§2), the **connected account** as both its identity and its connection
> reference (below), the **transport endpoint**, and the **payload description**.
> It is fixed in the `ActionRequest` before the ruling, is compared by
> `PermissionDecision.authorises` alongside the tool, the parameters digest and
> the step, and is transcribed verbatim into the recorded decision.

§11 then flags that value as `core` surface the corpus does not have, forbids any
lane from adding it on ADR-0148's strength alone, and fixes the properties it must
have while explicitly leaving the shape open:

> (a) is compared by `authorises`, is transcribed into the recorded decision,
> holds no credential value, and states no tier for a user-authored free-text
> span. A contract ADR that satisfies those is free to choose the signature; one
> that does not is changing this decision.

And it lists four questions it leaves to this ADR by name: whether the binding is
one nested model or several fields; whether the payload description inside it is
this ADR's or a projection of #57's richer artifact; how `authorises` expresses
the new conjunct; and how ADR-0004 §6's deletion rules reach a description that
names memory records. §1, §10, §9 and §10 below answer them in that order.

**Why the value cannot be avoided is settled and is not re-argued here.** ADR-0148
§11 records that three cheaper routes were tried and each failed: it cannot ride in
`parameters` (`ActionRequest` is `extra="forbid"` and ADR-0145 validates
`parameters` against the declared schema, so an account reference is refused at
construction and a canonical form written *over* a supplied one destroys the second
form ADR-0148 §2 requires); it cannot ride on the registry (a definition carries no
account and ADR-0016 §6 rebuilds the registry each run); and it cannot be left
derived-but-unstored, because ADR-0021 §1 stores a digest and none of the arguments,
so an auditor would hold "a hash of a description nobody can read" (#57's second
comment). This ADR takes that as decided and chooses the value's shape.

### The producer this decision was waiting for

ADR-0148 §11 deferred (a) on ADR-0073 §4's standing test — a contract of this shape
is decided "**with a producer in hand**", not guessed — and recorded that at the
time there was none, because nothing at the seam transmits. PR #1120 has since built
the inert half of the first egress integration inside `tools/`: a per-protocol
canonicaliser, a destination-argument declaration, a deterministic payload
description builder, and a `send_email` `ToolDefinition` that is registered nowhere
and whose callable raises. It transmits nothing, which is what keeps ADR-0017 §2
intact, and it is a producer, which is what ADR-0073 §4 asks for.

Its description carries eleven observations under "What this producer wants from
the contract surfaces", each recorded as something the code hit rather than
something anticipated. **They are the evidence this decision is made on**, and §14
maps every one of them to where it lands. Four shaped the value directly and are
answered by name in §3, §4, §6 and §7.

The producer also spent **eight consecutive adversarial rounds** (7 through 14) on
one class of finding — a caller reaching its functions with values their annotations
forbid — closing twelve sites and then waiving the thirteenth with rationale in
issue **#1122**. That issue's own closing paragraph is the shortest statement of
what §7 below decides:

> The shape that would end the class rather than move it is **not** more
> `isinstance` calls: it is making these values pydantic models in
> `core/types.py`, which validate their own fields on construction — which is what
> surface (a) does anyway under ADR-0148 §11.

### The failure this ADR is named after

Three of PR #1120's blocking findings — rounds 1, 2 and 3 — are one failure at three
depths: **two shapes that had to agree, arriving separately, compared by whatever
the callee remembered to compare.** A description builder took the destination
occurrences beside the parameters they were supposed to come from and checked no
relation between the two, so an empty tuple, or one naming a recipient the arguments
never selected, produced a description the module considered valid. One level down,
two declarations that had to agree arrived separately; the round-2 repair (compare
the `tool_id`s) was walked past by round 3 (a declaration claiming the same id), and
the repair that held was a single value holding both halves and checking them
against each other **when it is built**.

That is the same defect ADR-0021 §1 closed for the parameters digest — "a `str`
field that each caller filled in would be a canonicalisation per caller, and two
that disagreed would produce a false mismatch at execution, which reads as an attack
rather than as a bug" — and the same one ADR-0148 §6 closed for the connected
account, twice, when a draft bound an account by the registry and then by a keyring
slot. Every choice below is made against it: **one stored shape per fact, derived
properties where a second shape is wanted, and an invariant checked at construction
wherever `core` holds both sides.**

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none. §15 records the regime.

The decision in one sentence: **the egress binding is a single validating `core`
model carried whole, compared whole and transcribed whole; every fact it states is
either carried once or derived from what it carries; and no consumer is offered a
second shape of anything in it.**

### 1. One nested value, not several fields

> **Normative.** The egress binding is **one** value. `ActionRequest` gains
> exactly one field for it and `PermissionDecision` gains exactly one, both named
> `egress_binding`, both typed `EgressBinding | None`, both defaulting to `None`.
> No lane spreads the binding's facts across several fields of either model, and
> no lane adds a second field to either model on the strength of this ADR.

> **Normative.** `None` means the request is not an egress call and carries no
> binding. A binding is either whole or absent: there is no partially populated
> `EgressBinding`, and every field §2 names is required on it.

**ADR-0148 §6 already calls it "one value", and §11 still leaves the representation
open, so the choice is made here rather than inherited.** Three reasons decide it,
and the third is the one that would be hard to recover from.

- **`authorises` gains one conjunct rather than four.** ADR-0037 §3 records why
  that matters in a neighbouring place: its equality check "is total over the
  fields, **so a field added to `PermissionDecision` later is covered without
  anyone remembering to extend a list**". `authorises` is not total over the
  fields — it is an explicit conjunction — so every field added to it is a line
  someone has to remember. One field is one line; four fields are four chances to
  ship three.
- **A partial binding stops being expressible.** Four independent optional fields
  admit fifteen partial states, of which fourteen are a request that names a
  destination set and no account, or an account and no description. ADR-0148 §8's
  third clause makes a policy refuse `ALLOW` on a request carrying no destination
  set or no description — a floor, which means an implementation that gets it wrong
  is the thing the floor is defending against. With one value, the state does not
  exist to be ruled on.
- **The facts are only meaningful together.** A canonical destination set with no
  connected account is not authorisable — ADR-0148 §2's third clause makes the
  account the destination set where the arguments select nothing, so the two are
  read against each other — and a payload description with no destinations is
  ADR-0146 §5's "your words, to this recipient" with the second half missing. This
  is ADR-0021 §1's own argument for embedding the whole `ToolDefinition` by value
  rather than a name, one field further down.

**The `None` default is what keeps this from being a breaking change in practice
while remaining one in principle.** Every request and decision in the tree today
carries no binding, `None == None` is `True`, and §9's conjunct therefore returns
exactly the answer it returns now for every non-egress call. ADR-0148's Consequences
call surface (a) "a breaking change" because it touches "the most-consumed values in
the pipeline", and that is true of the *surface*: the models grow a field, the
factory grows a transcription, the comparison grows a conjunct, and every consumer
of those values is now consuming a wider type. What it is not is a **behaviour**
change for anything that exists: §12 requires the implementing lane to pin that as a
test rather than leave it as a claim.

### 2. Exactly which `core` names change

This section is a classification of the change being made and is not normative
(ADR-0089 §1). The obligations are in the sections it points at.

| Name | Where | What |
|---|---|---|
| `DestinationProtocol` | `core/types.py`, new | `StrEnum`, one member `SMTP`. The protocol under whose rules a destination's canonical form was computed (§3). |
| `DiscloserProvenance` | `core/types.py`, new | `StrEnum`, two members, ADR-0146 §1's two answers (§5). |
| `EgressDestination` | `core/types.py`, new | The two forms of one recipient and the protocol that relates them (§3). |
| `EgressSpan` | `core/types.py`, new | One described span of the payload: where it came from, who disclosed it, how much of it there is, its tier if its field establishes one, and its destination if it is one (§4, §5, §6). |
| `ConnectedAccount` | `core/types.py`, new | The account's identity and its connection reference (§7). |
| `CanonicalDestination` | `core/types.py`, new | One member of ADR-0148 §2's canonical destination set, in one of two validated shapes: a protocol-qualified recipient, or the connected account whole (§3). |
| `EgressBinding` | `core/types.py`, new | The whole binding: spans, account, transport endpoint; ADR-0148 §2's canonical destination set as a derived property (§1, §3, §7). |
| `ActionRequest` | `core/types.py`, changed | Gains `egress_binding`, an optional `EgressBinding` defaulting to `None`, detached at validation; gains one model validator for the invariants §4 states against `parameters`. |
| `PermissionDecision` | `core/types.py`, changed | Gains `egress_binding`, an optional `EgressBinding` defaulting to `None`. |
| `PermissionDecision.from_request` | `core/types.py`, changed | Transcribes the binding by deep copy. **Its signature does not change** (§9). |
| `PermissionDecision.authorises` | `core/types.py`, changed | Gains one conjunct (§9). |
| `core/protocols.py` | — | **Unchanged.** No Protocol is added, changed or removed. |
| `ToolDefinition` | — | **Unchanged.** No field is added to it, and §6 states the constraint that keeps it that way. |

> **Normative.** The `core` names this ADR authorises a lane to add or change are
> exactly these and no others: the new types `DestinationProtocol`,
> `DiscloserProvenance`, `EgressDestination`, `CanonicalDestination`, `EgressSpan`,
> `ConnectedAccount` and `EgressBinding`, all in `core/types.py`; one new optional field named
> `egress_binding` on `ActionRequest` and one on `PermissionDecision`, each holding
> an `EgressBinding` or nothing; that field's transcription in
> `PermissionDecision.from_request`; the conjunct §9 adds to
> `PermissionDecision.authorises`; and the model validator §4 requires on
> `ActionRequest`. No other `core` name changes: no field is added to
> `ToolDefinition`, `PermissionRuling` or `ToolCall`, and `core/protocols.py` is
> unchanged. A change beyond this list is a change to this decision and needs its
> own ADR (golden rule 5).

### 3. A destination is an occurrence; what it selects is derived, never supplied

This is PR #1120's first observation, and it is stated there exactly:

> §2's first clause defines the canonical destination set as a *set of canonical
> forms*; §2's fourth requires **both** forms of **every** destination-bearing
> argument in the record. Those come apart the moment one call names one recipient
> twice: `to: ["Alice@Example.com"]`, `cc: ["alice@example.com"]` is **one** member
> of the set and **two** supplied forms that must both survive.

> **Normative.** The binding **carries occurrences**. Each destination is carried on
> the span it occupies (§4) as an `EgressDestination` with exactly three fields: the
> `DestinationProtocol` under whose rules the canonical form was computed, the
> `supplied` form as the arguments carry it, and the `canonical` form ADR-0148 §2
> computed from it. The span it rides on carries which argument and which position
> it came from, so no occurrence repeats them.

> **Normative.** A canonicaliser is a **function** of the supplied form, so
> `EgressBinding` **refuses at construction** a binding carrying two occurrences that
> share a `protocol` and a `supplied` form and differ in their `canonical` form. This
> is the part of ADR-0148 §2's sixth clause that is visible from inside one value —
> two derivations of one form disagreeing — and it is checked here rather than assumed.

> **Normative.** `core` does **not** check an occurrence's `canonical` form against its
> `supplied` form, and no lane reads that absence as licence to leave the check
> unbuilt. ADR-0148 §2's sixth clause puts that computation "in **one** place at the
> seam", so the rule relating the two forms is not a thing this value holds; **(b)'s
> ADR owes the check** that every occurrence the seam hands over carries the form that
> seam's own canonicaliser computes. Until it lands, no lane states that a carried
> canonical form has been verified against anything. No lane closes this by moving
> canonicalisation into `core`: that is a change to where ADR-0148 §2 says it happens
> and needs an ADR superseding that clause, not a validator.

> **Normative.** A member of a canonical destination set is a `CanonicalDestination`,
> one `core` type with three fields and exactly two well-formed shapes, which it
> **refuses at construction** to depart from: a **selected recipient**, carrying a
> `DestinationProtocol` and a canonical form of non-blank visible text and no
> account; or the **connected account** the call is made to, carrying a
> `ConnectedAccount` (§7) and neither of the other two. No member carries all three,
> none carries neither shape, and there is no third kind.

> **Normative.** An account member carries the account **whole** — its identity and
> its connection reference, which is the pair ADR-0148 §6 binds an account by — and
> its equality is over both. No lane reduces an account member to its identity, to
> its reference, or to any single string: an identity alone is shared by two
> connection records the moment one account is connected twice, and a reference alone
> survives its own re-provisioning to a different account, so either alone is a
> destination that two different accounts can satisfy.

> **Normative.** ADR-0148 §2's **canonical destination set** is a single **derived
> property** of `EgressBinding` and is not a stored field. It is the deduplicated
> tuple of `CanonicalDestination` holding one member per distinct destination the
> binding's spans carry — and, where the spans carry **none**, exactly one member:
> the binding's own connected account, which is ADR-0148 §2's third clause. It is
> therefore **never empty**. It is totally ordered: account members first, then
> selected recipients by protocol and then by canonical form, each string compared by
> Unicode code point. No lane stores it beside the occurrences, accepts it from a
> caller, or lets a caller supply a tuple the occurrences and the account do not
> produce.

> **Normative.** Two members are equal when and only when **every** field is equal.
> A canonical form is never compared across protocols; no lane treats two protocols'
> canonical forms as comparable because the strings match; and an account member
> never equals a selected recipient, whatever strings the two hold.

> **Normative.** No policy refuses on ADR-0148 §8's third floor — "the request
> carries no canonical destination set" — on the ground that a binding's spans carry
> no destination. That request carries a set of exactly one member and is ruled on
> against it. No lane synthesises a destination *occurrence* from the account, writes
> one into the spans, or treats the account member as an argument the call selected.

**One derived property with one member type, arrived at over two review rounds, and
both drafts it replaces are worth recording because they failed in opposite
directions.** The first called the derived property "the canonical destination set"
and defined it to be empty exactly where ADR-0148 §2's third clause says that set is
the connected account — one name with two values for one request. Architecture review
found on round 3 that a policy reading ADR-0148 §8's third floor literally would then
refuse an account-only call for carrying no destination set, which is the opposite of
what §2 rules and would make every resolution call under ADR-0148 §5 unauthorisable,
since a resolution call's own set is the account. The second draft split the name in
two — an onward tuple, plus a rule saying what ADR-0148's set is in terms of it — and
round 4 found that this leaves the set itself with **no value shape at all**: an
onward call yields pairs and an account-only call yields an account, so every consumer
branches and invents its own comparison. That is this document's own title failing on
the document, and the second draft was worse than the first for it, because the first
at least had one type.

**The repair is to make the account a member rather than an alternative to the
members**, and it is a validated two-variant shape rather than a bag of optional
fields. The distinction §1 draws against partial states is about facts that are only
meaningful together and can arrive apart; here the variants are exactly two, a
validator makes every other combination unconstructable, and the type is total for a
consumer that never has to ask which case it is in before comparing. This destination
is the account the call is made to, which is not named under any protocol that
establishes equivalences between supplied forms, and saying so with an absent protocol
avoids minting a `DestinationProtocol` member for "the account" — a member that would
then have to state which equivalences it establishes (§3's membership clause) and has
none to state.

**The account member carries the account whole, and round 5 is why.** A first version
of it carried the identity alone, on the ground that the identity is what ADR-0148 §8's
fourth clause shows the user. Architecture review found that this drops the half
ADR-0148 §6 spent two adversarial rounds adding: "The connected account is bound by
**two** non-secret facts, not one." Two connectable records can hold one identity, so
identity-only account members compare equal across them — and a standing grant, which
ADR-0148 §3's first and fifth clauses bind to the canonical destination set rather than
to the tool or the account, would then cover a record the user never granted. The
inverse is equally true and is why the reference alone is not the answer either: a
reference is stable across a rotation *by design* (ADR-0148 §6), which is exactly what
makes it survive a re-provisioning to a different account. Both facts, or the member is
a destination two different accounts satisfy.

**What a policy compares and what a user reads are deliberately different fields.**
The set member holds the reference, which is not something a user can recognise an
account by — ADR-0148 §6 says so and §8's fourth clause bars it from the confirmation.
The confirmation names `ConnectedAccount.identity`, from the binding's own account
field (§7, §10). Neither substitutes for the other, and the reason they are not one
field is that they answer different questions: "is this the same connection" and "whose
account is this".

**Carrying occurrences and deriving the set, rather than the reverse, is the whole
of the answer, and the reason is §1's failure.** Both shapes are needed: ADR-0148 §4
authorises "the set" as a single value with no partial `ALLOW`, and ADR-0148 §2's
fourth clause requires both forms of every argument to reach the audit record. Only
one of the two can be reconstructed from the other. Occurrences yield the set by
deduplication; the set yields nothing, because an alias pair collapses on the way in
and ADR-0148 §14's alias case names reconstruction as a failure in terms — "an
implementation that records only the canonical form fails this case, and so does one
that reconstructs a supplied form from it". So the occurrences are what is stored,
and this is the same shape as `parameters_digest`: a derived property computed where
both sides are in hand, rather than a field each caller fills in.

**The forged canonical form is a real hole, it is (b)'s to close, and the two review
lenses disagreed about that in a way worth recording.** Adversarial review found on
round 10 that a caller could build `supplied="Alice@EXAMPLE.com"` beside
`canonical="mallory@example.com"` over `parameters={"to": "Alice@EXAMPLE.com"}`: §4's
supplied-form invariant passes, §4's extent check passes, and the
`CanonicalDestination` it yields is well-formed because the forged string is non-blank
visible text. Since ADR-0148 §3's first clause binds a standing grant to the canonical
destination set, that is a call to Alice carrying a grant boundary drawn around
Mallory. A draft answered it by making `canonical` a derived property and putting
`SMTP`'s rule on this type; architecture review found on round 12 that this
contradicts two ratified clauses at once — ADR-0148 §2's fourth, which carries **both**
forms in the request, and its sixth, which computes the canonical form "in one place at
the seam", where `tools/destinations.py` already computes it. A ratified clause is not
this ADR's to relocate, so the draft was withdrawn whole.

**What is left is a line worth drawing explicitly, because §4 recomputes two things and
this section recomputes none.** The checks §4 adds are relations between two things
`core` holds on one object — a supplied form against `parameters`, an extent against
`parameters` — and an invariant `core` can see is one it must not leave to a component
further out. The canonical relation is between the binding and a **rule**, and
ADR-0148 §2 put that rule at the seam deliberately, on #83's construction argument: one
canonicaliser per protocol rather than one per integration, "unenforceable by
construction" otherwise. A copy of it in `core` would be a second canonicaliser and
would defeat the clause it was meant to serve. So this section refuses what it can see
— a binding whose own two occurrences canonicalise one form two ways — routes the
correspondence check to (b) beside §6's `tier` and §4's structured-value supplied form,
and forbids reading that routing as licence. The residual exposure is bounded by §4:
the supplied form is pinned to `parameters`, so a forged canonical form cannot change
what the callable transmits, only what a grant is matched against — and matching is
performed by the same surface that owes the check.

**Protocol-qualifying the set is not decoration, and leaving it out would be a
silent widening later.** ADR-0148 §2's second clause makes comparison byte-exact
where the protocol does not establish that two forms denote one recipient, and its
sixth makes canonicalisation per protocol precisely so that "two integrations
speaking one protocol cannot disagree about whether two destinations are the same
recipient". A bare string set gives up the other half of that: two protocols whose
canonical forms coincide as strings would be one member. It also matters downstream
— ADR-0148 §3's first clause binds a future standing user policy to the canonical
destination set, and a grant for a recipient under one protocol authorising the same
string under another is exactly the substitution ADR-0148 §3's second clause spends a
list of near-misses refusing.

**`DestinationProtocol` is an enum rather than a string for ADR-0021 §1's
canonicalisation-per-caller reason.** A `str` field admits `"smtp"` and `"SMTP"` as
two protocols, and two integrations that disagreed would produce a false mismatch at
execution, which "reads as an attack rather than as a bug".

**A member is a safety claim, which is why one lands here and each of the rest needs
its own ADR.** An earlier draft let the lane adding a canonicaliser add its member,
and fixed no initial membership at all — so the enum this ADR authorises would have
landed empty and grown by implementation. Architecture review found on round 3 that
this is a substantive `core` contract change delegated to a lane, against golden rule
5 and ADR-0015 §5, and the corpus has been consistent the other way: `Disposition`
gained `INVALID_PARAMETERS` by ADR-0145 §4 and `GrantScope` gained `NOTIFY` by
ADR-0133 §1. The reason bites harder here than for either of those. A member's whole
content is a ruling about **which two supplied forms are one recipient** — RFC 5321
makes an SMTP local part case-sensitive and leaves the domain not (RFC 4343), so
`SMTP` means "fold the domain, never the local part", and ADR-0148 §2's own prose
names both directions of getting that wrong: "lowercasing an address whose local part
the protocol treats as case-sensitive lets a grant for one address authorise another;
provider aliasing gives the inverse failure." That is a decision with an ADR's worth
of argument behind it, not a line in an enum, and a member added without one is a
grant boundary drawn by whoever needed a canonicaliser that afternoon.

**`SMTP` lands here rather than with (b) because this ADR has the evidence for it,
and its content is marked because an unmarked version of it would bind nobody.** An
earlier draft stated the rules in this paragraph and left the clause above saying only
that the member exists. Adversarial review found on round 6 that ADR-0089 §3 then
makes those rules explanatory text — so one canonicaliser could refuse a quoted local
part and another keep it, both conforming, both deriving different bindings for one
request, which is ADR-0148 §2's sixth clause failing at the one place it was written
for. The rules are now clauses.

**Refusing is stricter than ADR-0148 §2's second clause requires and is not in tension
with it, and the distinction is worth being exact about because adversarial review read
it the other way on round 7.** That clause says the canonical form of an
unproven-equivalence pair "is the supplied form unchanged", which — read as an
obligation to *accept* — would have `SMTP` canonicalise a quoted local part to itself.
Read that way it would also contradict ADR-0148 §1's third clause in the same document,
which names "a destination that will not canonicalise" as refused before the ruling, and
whose own argument is that where a canonicaliser has no rule, "the tempting behaviour is
to pass the supplied form through and let the upstream sort it out. That is exactly how a
grant for one address comes to authorise another." The two clauses divide the question
rather than answering it twice: §2's second clause forbids **rewriting** a form that is
accepted, and §1's third clause governs whether it is accepted at all. This ADR's
membership clause puts the second half where the corpus already puts it — with the
protocol's own ADR — and every refusal below lands on the conservative side of §2's own
asymmetry, since a refusal is "a recoverable error the user sees" and the alternative it
forecloses is a disclosure. §13 records the ADR-0082 §1 judgement on both clauses.

**The boundary is stated as a grammar rather than as a list of refusals, and round 8
is why.** An earlier draft enumerated six refused shapes and stated the positive rule
as "everything before the final `@`". Adversarial review found that `a@b@example.com`
is ASCII, carries no whitespace, quote, literal or trailing dot, and is on none of the
six — so one implementation splits at the final `@` and canonicalises it while another
refuses it as the producer does, and the same request yields a binding in one and a
refusal at the seam in the other. A list of known-bad shapes is not an acceptance
boundary, and ADR-0148 §2's sixth clause — one canonicaliser per protocol, so two
integrations "cannot disagree about whether two destinations are the same recipient" —
is worth nothing if they can disagree about whether a string is an address at all. The
grammar closes it: everything not matched is refused, and the six become instances
worth naming rather than the definition.

**Each named refusal is also a case where the protocol does not settle equivalence, so
folding would be inventing one.** RFC 5321 §2.4 makes an SMTP local part case-sensitive and
leaves the domain not (RFC 4343), which is why the two halves are treated differently
and why the local part is copied byte for byte — "MUST BE interpreted and assigned
semantics only by the host specified in the domain part". A **quoted** local part has
escaping rules whose unquoted equivalent the protocol does not establish. A
**non-ASCII** address is refused because IDNA2003 and IDNA2008 disagree about U-label
and A-label equivalence, so there is no single answer to fold to. An **address
literal** names an equivalence class belonging to the IP stack rather than to this
seam. A **trailing dot** is a DNS root marker whose equivalence to the dotless form is
a resolver's rule, not the address grammar's. **Whitespace** is refused rather than
trimmed because trimming is a rewrite, which ADR-0148 §2's second clause forbids on any
ground weaker than the protocol saying the two forms are one recipient. PR #1120 built
and reviewed exactly this canonicaliser, which is the evidence ADR-0073 §4 asks for and
the reason this member is decidable here at all.

> **Normative.** `DestinationProtocol` has exactly **one** member, `SMTP`, and this
> ADR fixes that membership. Adding it authorises nothing: it neither implies a
> canonicaliser exists, nor registers a tool, nor permits any transmission.

> **Normative.** `SMTP` asserts exactly these equivalences and no others. Two
> supplied forms denote one recipient when their **local parts** — everything before
> the final `@` — are **byte-identical**, and their **domains** — everything after it
> — are equal after **ASCII lowercasing**. The canonical form is the supplied form
> with the domain ASCII-lowercased and the local part copied unchanged. No
> canonicaliser folds, strips, trims, reorders or otherwise rewrites a local part on
> any ground.

> **Normative.** `SMTP` **accepts** exactly the following supplied forms and
> **refuses every other string**, and the boundary is closed rather than a list of
> known-bad shapes. An accepted form is entirely ASCII and carries **exactly one**
> `@`, before which is the local part and after which is the domain.
> - The **local part** is 1 to 64 characters (RFC 5321 §4.5.3.1.1), and is one or
>   more *atoms* separated by single `.` characters, with no leading, trailing or
>   repeated `.`. An atom is one or more of `A-Z`, `a-z`, `0-9` and
>   ``!#$%&'*+-/=?^_`{|}~`` — RFC 5321's `Dot-string` of RFC 5322 `atext`.
> - The **domain** is 1 to 255 characters (RFC 5321 §4.5.3.1.2) and is one or more
>   labels separated by single `.` characters, with no trailing `.`. A label is 1 to
>   63 characters (RFC 1035 §2.3.4) of `A-Z`, `a-z`, `0-9` and `-`, beginning and
>   ending with a letter or digit.

> **Normative.** A refusal is ADR-0148 §1's third clause: the request is not built and
> no ruling is sought. The forms the boundary above excludes include, each for a reason
> §3's prose gives and none by accident: a **quoted** local part; any address carrying
> a character **outside ASCII**; an **address literal**, whose domain is an IP address
> rather than a name; a **trailing dot** on the domain; an address carrying
> **whitespace** anywhere, which is refused and never trimmed; a string with **more
> than one** `@`, or with **none**; and an empty local part or domain. No lane treats
> that list as the boundary — the grammar above is — and no lane accepts a form
> because it is absent from the list.

> **Normative.** A refusal under the clause above is **not a canonical form** and is
> not a rewrite. ADR-0148 §2's second clause governs what a canonicaliser does to a
> form it **accepts** — it forbids folding, stripping, reordering or rewriting one —
> and ADR-0148 §1's third clause is what governs a form it does not accept, naming "a
> destination that will not canonicalise" as refused before the ruling. Which forms a
> protocol accepts is what that protocol's member asserts, and asserting it is what
> this clause and the one below are for. No lane reads a refusal here as folding, and
> no lane reads ADR-0148 §2's second clause as obliging a canonicaliser to accept
> every string a caller supplies.

> **Normative.** Widening `SMTP` to accept a form the clause above refuses is a change
> to what that member asserts and needs its own ratified ADR, on the same terms as
> adding a member: it states which equivalences the newly accepted forms do and do not
> establish. No lane widens it by building a canonicaliser that accepts more.

> **Normative.** Every further member is added by a **ratified contract ADR of its
> own**, merged before any canonicaliser, integration or lane implements against it
> (golden rule 5, ADR-0015 §5). That ADR states which equivalences the protocol
> establishes between two supplied forms and which it does not, because that is what
> the member means under ADR-0148 §2's second clause. No lane adds a member as part
> of building a canonicaliser, an integration or a test.

### 4. A span is keyed to where it came from, and the binding covers everything the arguments carry

This is PR #1120's third observation:

> ADR-0146 §1 puts provenance on a span and §8 defers the marker. A recipient list
> is the mixed case in miniature: one address the user typed beside one the model
> pulled from memory. This lane keys provenance by `(argument, index)`. Whatever (a)
> chooses must be able to say that, or the §14 carried-provenance pair is
> unsatisfiable for list-valued arguments.

> **Normative.** A span is identified by the pair `(argument, index)`. `argument` is
> a top-level key of the request's `parameters`. `index` is the zero-based position
> of the span within an ordered decomposition of that argument's value, and is
> **absent** exactly where the span's value is the argument's whole value.

> **Normative.** How an argument's value decomposes into spans is determined by the
> bound tool's declaration and by that value, and by nothing else — no clock, no
> configuration, no store read, no network. This is ADR-0148 §6's determinism clause
> applied to the decomposition rather than to the description built over it, and it
> is what keeps two derivations of one request's description in agreement when an
> argument carries several recipients.

> **Normative.** The decomposition goes **at most one array level deep and never
> further**. Where an argument's value is a JSON array, its elements are its spans,
> whatever those elements are; where it is any other JSON value, it is one span.
> A span's own value is never decomposed: a span whose value is a JSON object or a
> nested array is one span, and the extent, provenance and tier it states are that
> whole value's.

> **Normative.** `EgressSpan.extent` is a non-negative integer, and it is the number
> of **Unicode code points** — in the span's value where that value is a JSON string,
> and otherwise in that value's canonical JSON encoding, which is ADR-0021 §1's
> `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False` form, the same
> encoding `parameters_digest` is taken over. It is never a count of bytes, of UTF-16
> units, of grapheme clusters, or of rendered columns, and no configuration selects
> between them.

> **Normative.** `EgressBinding` **refuses at construction**, and `ActionRequest`
> refuses a binding for which any of the following fails against its own
> `parameters`:
> - every span's `argument` is a top-level key of `parameters`;
> - every top-level key of `parameters` whose value is not an **empty JSON array** is
>   the `argument` of at least one span, and a key whose value **is** an empty JSON
>   array is the `argument` of **no** span;
> - for each argument that carries spans, either exactly one span with `index`
>   absent, or spans whose indices are exactly `0` through `k-1` for some `k ≥ 1`;
> - where that argument's value is a JSON array of length `n ≥ 1`, the second form
>   holds with `k == n`;
> - where that argument's value is **not** a JSON array, the **first** form holds: it
>   carries exactly one span, and that span's `index` is **absent**;
> - no two spans share an `(argument, index)` pair;
> - the spans are ordered by `argument` and then by `index`, absent sorting first,
>   with `argument` compared by Unicode code point;
> - where the argument's value is a JSON string and the span's `index` is absent, a
>   destination on that span carries that string as its `supplied` form; and where
>   the argument's value is a JSON array whose element at `index` is a JSON string, a
>   destination on that span carries that element as its `supplied` form;
> - every span's `extent` equals the number of Unicode code points in that span's
>   value, counted under this section's unit rule and **recomputed from `parameters`**
>   rather than taken as supplied — the argument's whole value where the span's
>   `index` is absent, and that argument's value's element at `index` otherwise.

> **Normative.** A builder holding two values of **differing provenance** inside one
> undecomposable span — inside a JSON object, or inside a nested array — cannot
> describe them and **refuses** rather than choosing one, which is ADR-0148 §1's
> third clause. No lane satisfies ADR-0146 §1 for that case by labelling the whole
> span with either answer.

**The empty array carries no span because there is nothing to describe, and stating
it costs a clause rather than an exception.** An argument whose value is `[]`
transmits no value, so a span for it would have to state an extent and a discloser
provenance for a thing that does not exist — and `SYSTEM_SELECTED`, §5's fail-closed
answer, would be a disclosure record for nothing disclosed. It is also the shape
ADR-0148 §2's third clause reaches most naturally: a call whose recipient arguments
are present and empty selects no recipient beyond the service the call is made to, so
its canonical destination set is the connected account alone (§3), and the binding for
it is well-formed with no destination-carrying span at all. The alternative — an indexless span standing for
an absent element — would make `to: []` and `to: ""` indistinguishable in the record.

**One array level and no more, because the alternative is a key that recurses and a
rule with a precedence question in it.** An earlier draft of this section stated the
per-element rule for arrays and, separately, that a value nesting more deeply than one
array level was covered as a single span at its top-level argument. Adversarial review
found on round 2 that `{"recipients": [["a"], ["b"]]}` satisfies both antecedents and
no binding satisfies both consequents. The repair is to make the depth a property of
the **decomposition** rather than of the value: an argument decomposes into its
elements if it is an array, and a span never decomposes at all. `(argument, index)`
then stays the whole key — the producer's key, and the one PR #1120's third
observation says anything coarser makes unsatisfiable — instead of growing into a path
that would need RFC 6901's escaping rules and a rendering for the user. What it costs
is stated in the clause above and routed in §11: mixed provenance inside one
undecomposable span is a refusal, not a description.

**Extent is code points, and fixing the unit is not pedantry — an unfixed unit is a
false mismatch at execution.** `é` is **one** code point composed (U+00E9) and **two**
decomposed (`e` followed by U+0301), and two UTF-8 bytes in the first form; an emoji
with a modifier is one grapheme cluster and several of everything else. Two components that measured differently would build unequal bindings
for one request, `authorises` would answer `False`, and ADR-0021 §1 already named what
that looks like from the outside: a false mismatch "reads as an attack rather than as a
bug". Code points are chosen over bytes because the count is shown to a user beside
their own words (ADR-0146 §5's "the user's own words, verbatim, N characters"), and the
canonical JSON form is reused for non-strings rather than invented because the codebase
already has exactly one canonical encoding and a second one would be a second thing to
get wrong. **Extent discloses a length**, including the length of a span the user may
have pasted a credential into, and that is accepted rather than overlooked: ADR-0146 §5
states the honest description in those terms, and a description that withheld the size
would leave the approver with less to decide on.

**Extent is recomputed rather than believed, and unlike the supplied form it leaves no
residue for (b).** An earlier draft fixed extent's *unit* and left its relationship to
the value it measures unstated, so a binding stating `extent=0` over a three-character
`body` satisfied every other invariant on this list: the argument exists, is covered
once by an indexless span, and is ordered. Adversarial review found it on round 9. An
approver could then be shown a description of a zero-character payload while the
callable received three characters — a description narrower than the payload, which is
the one outcome ADR-0148 §6 forbids in terms, and reached without anything having to
move after the ruling. The repair is the same shape as the supplied-form invariant
above, and for the same reason: `core` holds `parameters` and the binding on one
object, so it recomputes rather than believes, and an invariant it *can* check is not
left to a component further out. **Where the two differ is what is left over.** A
supplied form can be extracted from inside a structured value — a
`{"email": ..., "name": ...}` recipient — which `core` cannot see into, so §11 owes
that check to (b). An extent has no such case: it is stated over the span's **whole**
value, the decomposition clause above admits exactly two shapes for a span, and both
are locatable from `parameters` — an indexless span's value is the argument's whole
value, and an indexed span's is an element of a JSON array. The invariant requiring a
non-array argument to carry exactly one indexless span is what makes that enumeration
**exhaustive rather than merely usual**: it puts into the checked list what the
decomposition clause had already decided, and without it an indexed span on a
string-valued argument would be constructable, unlocatable, and a residue this section
would have had to invent an owner for.

**Coverage is checked in `core` because `core` is where both sides are in hand, and
that is what makes ADR-0148 §14's omitted-span case unconstructable rather than
merely forbidden.** §14 requires the implementing lane to ship a mixed payload — a
described benign span, an undescribed selected record, and an undescribed
user-authored free-text argument — refused before the ruling and again at the seam.
The second and third of those are now refused by the type: an argument with no span
is not a request that gets ruled on, it is a request that does not exist. That is
ADR-0029 §2's answer to the same problem shape — "the same answer is available here
for free: a `DENY` produces no `ToolCall`" — and it is the reason ADR-0148 §14's
omission case is worth spending a validator on rather than a rule.

**Coverage is over the arguments, not over "what the call transmits", and the
difference is deliberate.** ADR-0148 §6 states the description covers "every span
the call transmits". `core` cannot know which arguments a callable transmits and
which merely steer it — a `draft: true` flag is an argument that goes nowhere — and
the only way to teach it would be a per-argument declaration saying so, which is a
declaration a tool could get wrong and nothing could detect (PR #1120's eleventh
observation). Requiring coverage of every argument **over-describes** in that case:
the description states a provenance and an extent for a value that did not leave.
Over-describing is the conservative direction here for the same reason ADR-0148 §1's
third clause gives — the alternative is a description narrower than the payload,
which ADR-0148 §6 names as the thing an approver may never be shown.

**The supplied-form invariant is the one that closes round 1's finding at the type
level.** A
description "naming a recipient the arguments never selected" is what PR #1120's
first blocker was, and where the argument's own value is a string or an array of
strings, `core` now holds both sides and refuses the mismatch. Where the supplied
form is extracted from inside a structured value — a `{"email": ..., "name": ...}`
recipient — `core` cannot check it, and §11 records that as an obligation on (b)
rather than pretending the check is total.

### 5. Discloser provenance rides on the span — ADR-0146 §8's marker, decided

ADR-0146 §8 deferred "the marker that carries a span's discloser provenance to an
egress boundary" with the trigger "the lane that designates the `tools/` seam ...
the first lane with a producer, a payload description and an approver". ADR-0148 §11
then declined to rule whether that marker is surface (a) or rides inside it, on the
ground that "it is the same lane's decision, made with the same producer in hand,
and prejudging it here would be exactly the guess ADR-0146 §8 declined". The producer
arrived first. This is that decision.

> **Normative.** The marker **is** the `provenance` field of `EgressSpan`, typed
> `DiscloserProvenance` with ADR-0146 §1's two members and **no default**. There is
> no separate marker type, no second carriage of provenance in the request, and no
> field on `ActionRequest` outside the binding that states it. A lane that wants a
> span's provenance reads it off that span.

> **Normative.** The field is **carried, not derived**. No component decides a
> span's provenance by reading its value, its field, its shape, or by matching it
> against anything the user wrote (ADR-0146 §2). ADR-0146 §2's fail-closed rule — a
> span for which no origin was recorded is system-selected — is discharged by the
> component building the span **writing** `SYSTEM_SELECTED`, and never by a field
> default.

> **Normative.** How a recorded origin reaches the component that builds a span is
> **not decided here**. That path runs from receipt through the subsystems that
> compose an argument, and no lane reads this ADR as deciding it, as excusing it, or
> as authorising a component to invent a provenance it was not given.

**One carriage rather than two, for §1's reason and for a sharper one.** ADR-0146 §6
requires provenance to be recorded "with the payload it binds before transmission"
and carried into the audit record. The payload description **is** the thing bound and
**is** transcribed verbatim into the recorded decision (ADR-0148 §6). A marker riding
anywhere else would have to be joined to the description by something, and the join
is a second shape that must agree — the failure this ADR is named after, arriving at
the one field whose whole purpose is to be believed.

**This is one of the three landing places ADR-0146 §6 named for itself**, so
deciding it spends the deferral by the route the deferral offered rather than around
it. §6 there wrote that "whether provenance rides on a `core` type, on a wrapper the
seam constructs, or **on the payload description itself** is a contract decision",
and ADR-0148 §12 read it the same way. §13 below applies ADR-0082 §1's test to that
sentence and to ADR-0146 §8's trigger.

**No default is the substance and not a style choice.** A defaulted field is what a
lane forgets: an implementation that never wires provenance through would get
`SYSTEM_SELECTED` for free, its payloads would look correct, and ADR-0146 §2's own
warning about the opposite default — "a lane that has not wired provenance through
gets 'user-authored' for free and its payloads stop looking like disclosures" —
applies to the safe default too, one step weaker. Requiring the field forces every
builder to answer, and a builder with no recorded origin answers `SYSTEM_SELECTED`
because §2 tells it to, in code a reviewer can see.

**Determinism is not made circular by this.** ADR-0148 §6 makes the description a
function of three inputs, the second being "the provenance the request carries for
their spans". Under this section that carried provenance and the description's
provenance are the same bytes, so the function is the identity on that component and
is a derivation on the others. ADR-0148 §14's carried-provenance pair — two requests
with byte-identical arguments and the same definition, differing only in carried
provenance, producing **different** descriptions — is then satisfied by construction
rather than by discipline, which is the strongest form available for it.

### 6. A tier is stated where the field establishes one, and the moved-value case is a named residue

> **Normative.** `EgressSpan` carries `tier: DataTier | None`. It states the tier of
> the span's value where the field that value occupies **establishes** that tier in
> ADR-0146 §5's sense, and states **none** otherwise — which includes every
> user-authored free-text span (ADR-0146 §5's fourth clause, ADR-0148 §11's third).

> **Normative.** Which fields establish a tier is a property of the **bound tool's
> declaration**, and that declaration is recoverable from the `ToolDefinition` the
> request carries and the decision embeds verbatim. It rides inside
> `parameters_schema`, which is already a `FrozenJsonMapping` (ADR-0016 §4) and is
> already stored by value in every decision. **No field is added to
> `ToolDefinition`** for it, and no lane reads a tier off a store, a configuration
> or a registry lookup.

> **Normative.** The vocabulary by which that declaration is written into
> `parameters_schema` — its keywords and their form — is **not decided here**. It is
> one vocabulary with the destination-bearing declaration surface (b) reads, and
> splitting it across two ADRs would produce two half-decided keyword sets. (b)'s
> ADR fixes it, subject to two constraints this ADR does fix: it is recoverable from
> the embedded `ToolDefinition`, and it does not make a schema unreadable under
> ADR-0145 §5 and §6.

> **Normative.** `core` validates that `tier` is a `DataTier` or absent, and does
> **not** check it against the declaration, because the vocabulary is not fixed here.
> No lane reads that absence as licence to leave the check unbuilt: (b)'s ADR owes
> it, and until it lands no lane states that a described tier has been verified
> against anything.

> **Normative.** A span's tier, and the absence of one, states nothing about
> `ToolDefinition.discloses`. `discloses` remains ADR-0016 §3's ceiling, and no lane
> reads a description as narrowing it, contradicting it, or discharging ADR-0004
> §7's minimisation rule, which stays scoped as ADR-0017 §9, ADR-0146 §8 and
> ADR-0148 §13 left it.

**PR #1120's fourth observation names a real gap and this section does not close
it.** Its words:

> ADR-0148 §6's clause states no tier for a *user-authored* free-text span and the
> tier "of every value whose field establishes one" — silent on a system-selected
> span in a field that establishes none (a memory record pasted into a body). This
> lane states no tier there, which is conformant and arguably under-describes a Tier
> 1 record.

It is worse than "arguably", and worth stating exactly, because ADR-0146 §5's **third
clause** already rules on it: "Surrounding a value whose field establishes its tier
with prose, **or moving it into a field that establishes none**, does not make it
free text and does not relieve the implementation of describing it at its tier." So a
memory record's content carried verbatim into a body field must be described at its
tier — and ADR-0148 §6's three determinism inputs cannot produce that tier, because
the field establishes none and the value is not the definition's to classify.

> **Normative.** This ADR's description does **not** discharge ADR-0146 §5's third
> clause for a value the system already tiered and then carried into a field that
> establishes no tier. No lane cites this ADR, or the `tier` field, as discharging
> it, and no lane reads a stated-no-tier span as an assertion that the span carries
> no tiered value.

> **Normative.** The lane that first composes an egress argument from a value this
> system already holds at a tier owes the mechanism that closes it: a **recorded**
> per-span classification travelling from selection into the request, on ADR-0146
> §2's carried-not-inferred discipline. That mechanism is a **fourth** input to
> ADR-0148 §6's determinism clause, so that lane's ADR amends that clause and
> records it under ADR-0082 §1. No lane adds a carried tier to this surface before
> that ADR merges.

**Why the residue is named rather than closed, and why it is not refused either.**
Closing it needs a producer that records a value's classification at selection and
carries it through to the seam, and nothing in the tree does — which is ADR-0073 §4's
test failing, on this ADR's own terms, one surface further in. Refusing the case
instead was considered and declined: detecting that a span carries an
already-tiered value requires exactly the same recorded-origin machinery that
carrying its tier requires, so a clause refusing it would be a bound with no
mechanism behind it — the defect ADR-0098 §3 records itself making twice and
ADR-0148 §13 quotes against a different clause. Naming it is ADR-0146 §7's own
posture: "name what is not detected, and do not buy a bound from a mechanism that
cannot carry it."

**The cost is bounded today and will not be bounded later, which is why the trigger
is written now.** Nothing transmits, so nothing is under-described yet. The moment an
integration composes a body out of retrieved memory, it is, and the lane that does it
is the one with both halves in hand.

### 7. The connected account, its reference, and the transport endpoint

> **Normative.** `EgressBinding` carries the connected account as one
> `ConnectedAccount` with exactly two fields, both required and both non-blank
> visible text: `identity`, the durable, user-recognisable name of the account
> recorded when it was connected, and `reference`, which names that account's
> connection record (ADR-0148 §6, ADR-0149).

> **Normative.** `EgressBinding` carries `transport_endpoint` as required non-blank
> visible text. This ADR constrains its scheme, host, port and path **not at all**,
> and no lane reads that absence as permission: what the endpoint must be, and what a
> redirect may do, is #83's and is not decided here or by ADR-0148 §6's own last
> clause on the point.

> **Normative.** No credential value, and no credential **slot**, enters an
> `EgressBinding` or any value inside one. A `SecretName` (ADR-0125 §2), a
> `SecretName`'s `name`, and any string identifying a keyring entry are forbidden in
> `reference` and in every other field of this surface. `core` cannot distinguish a
> slot name from a reference — both are strings — so this is a rule checked where
> the connection record is read (ADR-0148 §6's four-way refusal), not a type.

**`identity` is required to be visible text for ADR-0021 §1's `reason` reason.**
ADR-0148 §8's fourth clause requires the confirmation to name the account's identity,
and §6 there says why the reference and the slot are not shown: "neither is something
a user can recognise an account by". An identity that rendered as nothing would leave
the confirmation with nothing to say about whose account this is — the same failure
ADR-0018 §1's `_has_visible_text` test was written for and ADR-0021 §1 applied to
`reason` at the moment the user is deciding.

**Two fields for the account rather than one is ADR-0148 §6's round-2 finding and is
consumed rather than re-argued.** A `SecretName` names a keyring slot, `set` replaces
in place and never refuses (ADR-0125 §4), so a confirmation taken while a slot held
account A's token can be resumed after the slot holds B's. The repair there was the
identity beside a connection reference, with the callable comparing the identity
*currently* recorded. This surface carries both and carries no slot, which is the
whole of what ADR-0148 §6's stability argument asks of it: the reference survives a
rotation, so a parked `CONFIRM` is still answerable, while the slot moves per
provisioning act and would have invalidated it.

**PR #1120's sixth observation is now answered by a ratified ADR rather than by this
one.** It recorded that the connected-account-only case "has no expressible form in
`tools/` today", because the account is bound by facts living in a connection record
whose owner ADR-0125 §12 left undecided. ADR-0149 has since decided it — one
component in `tools/` provisions a connection and the record is the hub's — so the
case is buildable, and §3's account-member clauses above are what make it
expressible in the binding: no span carries a destination, and the derived canonical
destination set is the account alone.

### 8. Every value in this surface is a validating model, and no message it raises renders an argument

This is PR #1120's tenth observation and it is the one the producer paid the most for:

> Seven review rounds went on a caller reaching this lane's functions with values
> their annotations forbid. The durable answer is not `isinstance` calls at a seam:
> it is that the values crossing it are pydantic models in `core/types.py`, which
> validate themselves ... If (a) makes the egress binding a `core` model, (b) can
> take it on trust and this whole class disappears; if it makes it a plain dataclass,
> (b) inherits the class instead.

> **Normative.** `EgressBinding`, `EgressSpan`, `EgressDestination`,
> `CanonicalDestination` and `ConnectedAccount` are pydantic models in
> `core/types.py`, each with `extra="forbid"` and `frozen=True`, and each validating
> every field it declares — `CanonicalDestination` included, and its two-shape
> invariant (§3) is one of the things it validates. None is a dataclass, a
> `TypedDict`, a `NamedTuple` or an unvalidated container.

> **Normative.** Every model in this surface sets `hide_input_in_errors=True`, and
> no message any of them raises renders an argument value, a supplied or canonical
> destination form, a connection reference, an account identity, or any part of a
> span's content. A field name, an argument name, an index and an error type may be
> named; a value may not.

> **Normative.** Every field of this surface is serialisable, and a binding survives
> a `model_dump(mode="json")` round trip as an equal value. A binding that could not
> would make the decision that carries it worthless across exactly the restart
> ADR-0021 §1 and issue #54 are about.

**The decision goes the producer's way and the argument is theirs, sharpened by what
this surface actually is.** #1122's finding is that
`Destination(DestinationProtocol.SMTP, "a@example.com", 1)` is constructible at
runtime and that combining it with a well-formed destination makes `sorted()` raise
`TypeError`. On a `tools/`-internal dataclass that is a caller who silenced mypy
getting a Python error instead of a package's refusal, which the corpus has ruled is
not a producer's to prevent (ADR-0021 §1). On **this** value it is three things
worse, and each is a reason on its own:

- **It is the value a ruling is taken over.** ADR-0148 §4 makes the canonical
  destination set "authorised as a **single** value" with no partial `ALLOW`. A
  derived property that raises rather than returns is a gate that fails by
  exception, and an exception is caught somewhere.
- **`authorises` must be total.** It is called by `ToolCall`'s validator and re-run
  by `invoke` on a detached copy (ADR-0029 §2), in that order, before the callable is
  reached. A comparison that raises on a malformed field is not a comparison that
  answered `False`.
- **The invariants §4 states are only expressible in a validating model.** Ordering,
  contiguity, uniqueness, coverage, and recomputation of a stated form or extent
  against `parameters`, are not annotations; they are checks, and a dataclass has
  nowhere to put them. Choosing the dataclass would not merely inherit
  #1122's class — it would forfeit the mechanism that makes ADR-0148 §14's
  omitted-span case unconstructable.

**`hide_input_in_errors` is PR #1120's ninth observation arriving where it bites
hardest, and it would be easy to lose.** That lane's rounds 5 and 6 established the
rule — "a declaration is the tool author's text and may be named once it is known to
be text; a call's arguments and a carried provenance key are not, and are never
named" — because a refusal message reaches a log. `ActionRequest` already sets the
flag, for exactly this reason and with the reasoning in its own comment; pydantic's
config is **per model**, so a nested model that omits it appends `input_value=` to
its own errors, and the value it would append is a recipient address. Setting it on
the outer model and not the inner ones would be the leak wearing the fix's clothes.

### 9. `authorises` gains one conjunct, and `from_request` transcribes by deep copy

> **Normative.** `PermissionDecision.authorises` gains exactly one conjunct:
> `request.egress_binding == self.egress_binding`. It compares the binding **whole**
> and by value. No lane compares it field by field, compares only its derived
> derived canonical destination set, compares only its account, or admits any
> comparison
> weaker than equality of the whole value.

> **Normative.** The conjunct is `None`-safe in both directions and neither
> direction is an exemption. A request carrying a binding is not authorised by a
> decision carrying none, and a request carrying none is not authorised by a
> decision carrying one.

> **Normative.** `PermissionDecision.from_request` transcribes the binding from the
> request, **deep-copying** it exactly as it already deep-copies `tool`. Its
> signature does not change: the binding is transcribed, never supplied by a caller,
> so a decision cannot name a binding the policy did not see.

> **Normative.** `ActionRequest` **detaches** the binding at validation, the
> discipline `tool` already carries under ADR-0018 §3, so the request does not hold
> the caller's object.

**Comparing the whole value is strictly stronger than comparing the set, and the
strength is where ADR-0148 §4's third clause is cashed.** That clause forbids any
component from adding to, removing from, substituting within or reordering the
canonical destination set between the ruling and transmission. Comparing occurrences
refuses all four *and* refuses a change of supplied form that leaves the canonical set
identical — the alias case moving from `Alice@Example.com` to `alice@example.com`
after the user approved the first. ADR-0148 §2's fourth clause requires both forms in
the record precisely because they are different facts; a comparison that saw only the
set would record one and bind the other.

**The deep copy is not symmetry and its absence is a live rewrite.** `from_request`'s
existing docstring states the defect for `tool` in terms: pydantic passes an
already-valid model instance through without copying, so the decision would hold the
*same* object the request does, and an `object.__setattr__` on it "would then rewrite
what the policy is recorded as having approved, while `authorises` went on answering
`True` because both sides moved together". A binding is a nested model reached the
same way, holds the recipients, and is the one field whose rewrite ADR-0148 §4's
third clause exists to make impossible. Copying it is that clause's enforcement, not
its restatement.

**Both `None` directions are stated because only one of them is obvious.** A request
with a binding meeting a decision without one is plainly a mismatch. The reverse — a
decision recorded for an egress call being offered a request with no binding — is the
substitution that would let an approval for a described, destined send authorise a
call that describes and destines nothing, and `None`-safety in one direction only is
how a comparison acquires that hole.

### 10. The description is what is approved, it names no record, and #57's richer artifact projects onto it

ADR-0148 §11 asks whether the description inside the binding is this ADR's or "a
projection of #57's richer artifact", and separately how ADR-0004 §6's deletion rules
reach a description that names memory records. Both are decided.

> **Normative.** The payload description carried in the binding is **this ADR's
> value** — the `spans` of `EgressBinding`, as §4, §5 and §6 define them. It is what
> `permissions/` rules on, what ADR-0148 §8's fourth clause requires the confirmation
> to name, and what is transcribed into the recorded decision. It is not a projection
> of anything, and no lane binds one artifact and shows another.

> **Normative.** A description states **no record identifier** — no memory record id,
> no episode id, no store-side key of any kind — and no field name of any store's
> schema. It states, per span, the argument and position it came from, its discloser
> provenance, its extent, its tier where its field establishes one, and its
> destination forms where it is one. It holds no content.

> **Normative.** The confirmation ADR-0148 §8's fourth clause requires additionally
> names, for **every occurrence the binding carries**, the argument that occurrence
> was selected by. It is stated over occurrences and not over members of the derived
> set: one recipient named by `to` and again by `bcc` is **one** member and **two**
> disclosures, and a confirmation naming one argument for that member has
> understated the call. `to` and `bcc` are the same recipient set and a materially
> different disclosure, and a confirmation that does not distinguish them has not put
> the question the user is being asked to answer.

> **Normative.** This surface carries **no rendering**. Two consumers may render one
> description differently; what neither may do is treat a rendering as the bound
> artifact, or show the user a value derived beside the binding rather than the
> binding's own.

> **Normative.** A later ADR that designs #57's richer artifact does not replace
> this value. If such an artifact exists, this description is derived from it
> deterministically, and what is bound, compared, transcribed and shown remains this
> value. That ADR states the derivation, and if it wants record identifiers in the
> richer structure it owes ADR-0004 §6's deletion answer for them in its own text.

**"This ADR's, not a projection" is settled by what a projection would cost, and the
cost is this document's title.** Two artifacts that must agree, one bound and one
shown, is the defect PR #1120's first three rounds found and the reason ADR-0148 §6
stores the description instead of a digest. #57's own second comment names the same
thing from the auditor's side — "a hash defeats the purpose" — and #57's first comment
records that deferral is safe in this direction because "the declared tuple is a
ceiling, so any later mechanism only ever narrows it. There is no migration hazard in
deferring this."

**ADR-0004 §6's deletion rules do not reach this description, and that is a decision
rather than an omission.** #57 states the question — "deleting a memory should
presumably not leave its content described in an audit row" — and lists the tension it
comes from: "Ids make the record verifiable but couple it to memory's identifiers."
This ADR takes the other branch. A description naming no record identifier and holding
no content leaves nothing behind when a memory record is deleted: there is no row that
describes *that* record, only a row saying that a span of some extent, of some
provenance, went to some recipient. So the question does not arise for this artifact,
which is a cleaner answer than a retention rule, and it is available precisely because
this surface is deliberately narrow.

**What the trail does hold about destinations is already routed and is unchanged.**
The supplied and canonical forms of every recipient are argument values in a Tier 1
store, governed by ADR-0021 §4's append-only rule and its wholesale erasure, and by
whatever #108 rules about retention — which ADR-0148 §13 already records: "a
description that is stored is subject to whatever #108 rules". Nothing here narrows or
widens that.

### 11. What this ADR does not decide

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's form).

> **Normative.** Surface (b) of ADR-0148 §11 — the seam by which the binding is
> obtained from `tools/` before `ActionPolicy.decide` is reached — is **not decided
> here**, and no lane reads this ADR's value as fixing that seam's signature, its
> holder or its error behaviour.

> **Normative.** (b)'s ADR owes four things this decision leaves it, and none is
> inherited from here by silence: a way for the seam to **fail distinguishably from
> a denial**, because this value cannot express "this call cannot be completed" and
> deliberately does not try; the declaration vocabulary §6 constrains but does not
> fix; the check §4's supplied-form invariant cannot perform where a supplied form is
> extracted from inside a structured value; the check §3 routes here, that every
> occurrence carries the canonical form the seam's own canonicaliser computes from its
> supplied form under its protocol; and the refusal-message discipline
> ADR-0146 §2 and PR #1120's ninth observation impose on a component that runs
> **before** ADR-0145 has refused anything outside the schema.

> **Normative.** This ADR designates nothing, attests no ADR-0017 §3 condition, and
> discharges none. It supplies the `core` value conditions 8 and 10 need and no lane
> cites it further.

> **Normative.** Nothing here decides the provisioning act, a keyring face, a
> connection record's storage or its lifecycle. ADR-0149 owns those and this surface
> consumes its reference without extending it.

**ADR-0137 §2's triad has no Protocol to carry here, and saying so is not a
loophole.** ADR-0148 §11's second clause says the triad "rides with the primary
production implementation as one lane". A triad is a Protocol, its shared conformance
suite and its canonical fake in `ai_assistant.testing` (`CONTRIBUTING.md` → "Adding a
Protocol"). Surface (a) adds no Protocol — it is a value in `core/types.py` — so what
rides with the primary production implementation is these types and their tests, and
the exemption ADR-0137 §2 grants for a triad is not the exemption that lane needs.
Surface (b) **is** a seam, so (b)'s ADR is where the triad obligation lands, and it
lands there whole.

### 12. What the implementing lanes owe

> **Normative.** The lane that lands this surface ships, beyond the ordinary
> coverage of each field: a **regression pin** that every request and decision
> carrying no binding compares exactly as it does today, so §1's `None` default is
> demonstrated rather than asserted; and a **round-trip** case showing a populated
> binding survives `model_dump(mode="json")` and reconstruction as an equal value.

> **Normative.** That lane also ships the **alias pair at the `core` level**: two
> spans whose supplied forms differ and whose canonical forms and protocol are
> identical are **two occurrences** and **one** member of the derived canonical
> destination set, with both supplied forms surviving on the binding. An
> implementation whose derived set carries two members, or whose occurrences carry one supplied form, fails it, and
> so does one that reconstructs a supplied form from a canonical one (ADR-0148 §14).

> **Normative.** That lane also ships the **substitution pair**: two bindings
> differing in exactly one span's supplied form, with identical derived sets, are
> unequal, and a decision recorded for either does not authorise a request carrying
> the other. The same for two bindings differing only in one span's `provenance`,
> which is ADR-0148 §14's carried-provenance pair reaching `authorises` rather than
> the description builder.

> **Normative.** That lane also ships the **rewrite** case: an `object.__setattr__`
> performed on the request's binding after the decision was made changes nothing in
> the decision, and `authorises` then answers `False`. A test that mutates a copy
> does not satisfy it.

> **Normative.** That lane also ships the **construction refusals**, one case each,
> for every invariant §4 states: an argument with no span; a span naming an argument
> `parameters` does not carry; a duplicate `(argument, index)`; a mis-ordered span
> tuple; an array argument of length `n` described by `k ≠ n` spans; a **non-array**
> argument described by an indexed span; a string-valued argument whose span's
> destination carries a different supplied form; a span over a JSON **string** whose
> `extent` is not that string's code-point count; and a span over a **non-string**
> value whose `extent` is not the code-point count of that value's canonical JSON
> encoding. The last two are exercised on a binding that is otherwise well-formed: a
> case whose extent is wrong **and** whose coverage or ordering is wrong demonstrates
> neither check, because either refusal alone produces the same outcome.

> **Normative.** That lane also ships the **`None`-asymmetry** pair in both
> directions (§9), the **account-only** case of §3 — a binding whose spans carry no
> destination is well-formed and its derived canonical destination set is exactly one
> member, the bound connected account, which no selected recipient equals — the
> **empty-array** case of §4, in which an argument whose value is `[]` carries no
> span and the binding is still well-formed, and a case asserting that a construction
> omitting `provenance` **raises**, which is what §5's no-default clause is worth.

> **Normative.** That lane also ships the **extent** boundary cases §4 fixes the unit
> for: a span whose value is a JSON string containing a character outside the Basic
> Multilingual Plane, and one containing a combining sequence, each state an extent in
> **Unicode code points**. A test whose only string is ASCII distinguishes no unit and
> satisfies neither.

> **Normative.** That lane also ships the **nested** construction cases §4's depth
> rule fixes: an argument whose value is an array of arrays is described by one span
> per top-level element, and an argument whose value is a JSON object by one indexless
> span, each stating that whole value's extent. A binding that decomposes either
> further is refused.

> **Normative.** That lane also ships a **construction refusal for every ill-formed
> `CanonicalDestination`** §3's two-shape clause excludes: a member carrying a
> protocol, a canonical form **and** an account; one carrying an account and exactly
> one of the other two; one carrying a protocol and no canonical form, or a canonical
> form and no protocol; and one carrying none of the three. A test exercising only the
> two well-formed shapes satisfies none of these.

> **Normative.** That lane also ships the **account-member** pair: two bindings whose
> accounts share an identity and differ in their connection reference derive
> **unequal** canonical destination sets, and two whose accounts share a reference and
> differ in identity likewise. An implementation whose account member holds one of the
> two facts passes one of these and fails the other (§3).

> **Normative.** The lane that implements the seam's `SMTP` canonicaliser ships a case
> for **each** equivalence and **each** refusal §3 states: a pair differing only in
> domain case canonicalises to one form; a pair differing only in local-part case
> canonicalises to **two**; and a quoted local part, a non-ASCII address, an address
> literal, a trailing dot, an address carrying whitespace, a string with **two** `@`
> characters, a string with none, a local part with a leading, trailing or doubled
> `.`, a local part over 64 characters, a domain label beginning or ending with `-`,
> a domain with an empty label, and a domain over 255 characters are each **refused**
> rather than canonicalised or passed through. A canonicaliser that lowercases the
> whole address passes the first and fails the second, and one that splits at the
> final `@` passes every refusal case except the two-`@` one.

> **Normative.** The lane that lands **this** surface also ships the
> **disagreeing-derivation** case §3 refuses: one binding carrying two occurrences that
> share a protocol and a supplied form and differ in their canonical form is refused at
> construction. A case whose two occurrences differ in their supplied forms as well
> demonstrates nothing, because the alias clause above already accepts that shape.

> **Normative.** The lane that closes §3's routed correspondence check — the lane that
> lands surface (b) — ships the **forged-canonical** case in the terms §3 states it: an
> occurrence whose canonical form is not what that seam's canonicaliser computes from
> its supplied form is refused **before** a ruling is sought, and a test asserting only
> that a correctly-built occurrence is accepted does not reach it. No lane records that
> check as satisfied by `core`'s validators, which §3 states in terms do not perform it.

> **Normative.** The lane that builds an egress `CONFIRM` ships the
> **duplicate-across-arguments** case §10's third clause is stated for: one recipient
> selected by two arguments produces a confirmation naming **both** arguments beside
> that recipient's forms. A confirmation that names one argument per member of the
> derived canonical destination set fails it, and a case built from a call whose
> recipients are each selected once does not reach it.

> **Normative.** No lane satisfies any clause of this section with a test that
> exercises only a well-formed binding on a happy path.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text and fixes its form: a
record is owed on an earlier ADR exactly where this ADR **amends a named clause** of
it — where "a reader holding only the earlier ADR now acts differently, or reads one
of its clauses more widely than it now holds". Where the answer is no, the change is
"a **stacked addition**: it is recorded in the ADR that makes it, and nowhere else",
and no record is owed "on `Status` or in a note". ADR-0146 §10, ADR-0147 §11, ADR-0148
§12 and ADR-0149 §12 are the worked precedents for this section's form.

**The conclusion first: no record is owed against any ADR, and none is written.**
This ADR's diff is one new file. What follows is the working, ADR by ADR, and a
disagreement with it takes ADR-0082 §1's own form — naming the sentence that does, or
does not, become false or over-wide.

**ADR-0148 §1 and §2 — no record owed, and this is the pair adversarial review
contested on round 7, so the working is explicit.** §1's third clause is *used*: §3's
`SMTP` refusals and §4's undecomposable-span refusal are both requests refused before
the ruling, which is that clause operating rather than being narrowed. §2's second
clause — "the canonical form is the supplied form unchanged and comparison against it
is byte-exact" — stays true of every form `SMTP` accepts, and its prohibition on
folding, stripping, reordering and rewriting is neither relaxed nor qualified: §3
forbids folding a local part in the same terms and refuses whitespace precisely
*because* trimming would be a rewrite. What §3 adds is a rule about which forms are
accepted, which §2's second clause does not speak to and §1's third clause reserves. A
reader holding only ADR-0148 §2 still finds the same instruction about what to do with
a form in hand, and still may not fold one; what they additionally find, in this ADR,
is that `SMTP` hands them fewer forms. That is ADR-0082 §1's stacked addition — an
obligation contradicting no sentence the earlier ADR wrote — "recorded in the ADR that
makes it, and nowhere else". §2's **fourth** clause is relied on unchanged and is why
`EgressDestination` stores both forms rather than deriving one: a draft that derived
the canonical form was withdrawn on review for contradicting it. §2's **sixth** clause
(one canonical form per protocol, computed in one place at the seam) is likewise relied
on unchanged, and is both the reason the member's assertion is stated once, here,
rather than per integration, **and** the reason §3 routes the correspondence check to
the seam instead of performing it in `core` — a `core` copy of the rule would be the
second canonicaliser that clause exists to forbid. Neither clause is narrowed, extended
or qualified, and a reader holding only ADR-0148 §2 finds both sentences doing exactly
what they say.

**ADR-0148 §6 and §11 — no record owed, and this is the one the whole ADR turns on.**
§11's clause defers the shape and its unmarked prose says in terms that "a contract
ADR that satisfies those is free to choose the signature". Choosing it is that
sentence working, not that sentence being narrowed — the shape ADR-0147 §11 found for
ADR-0017 §2's seam-naming and ADR-0148 §12 for ADR-0021 §6's deferral: "that deferral
working as designed, not a supersession" (ADR-0029 §9). Every property §11's last
paragraph fixes is satisfied and none is traded: the binding is compared by
`authorises` (§9), transcribed into the recorded decision (§9), holds no credential
value (§7), and states no tier for a user-authored free-text span (§6). §6's
determinism clause is consumed with **three** inputs and no fourth: §5 makes the
carried provenance and the description's provenance the same bytes rather than a new
input, and §6 above explicitly refuses to add a carried tier, routing it to a later
ADR that will amend that clause and record it. §6's prohibition on showing an approver
"a description narrower than the payload" is consumed the same way rather than
narrowed: §4's extent invariant recomputes each span's stated extent from `parameters`
and refuses the mismatch, which is that prohibition enforced at construction, not a
rule added beside it. §11's unmarked observation that "there
is no producer" is a statement of fact ADR-0148 itself made contingent — it deferred
"with a producer in hand" — and PR #1120 arriving is the condition ADR-0148 named,
not a sentence of it becoming false.

**ADR-0146 §8 — no record owed, and this is the one a reviewer is most likely to
challenge, so the working is shown twice.** The sentence in question is §8's
"**Trigger: the lane that designates the `tools/` seam**, which is the first lane with
a producer, a payload description and an approver, and therefore the first with
evidence about the shape the field wants." §5 above decides the marker before that
lane exists, so the question is live.

- **The first limb: it is not a clause.** ADR-0146 §11 puts that ADR in ADR-0089's
  marked regime, in which "the marked clauses are the whole of what it obligates" and
  "unmarked text ... never supplies an obligation" (ADR-0089 §3). The trigger sentence
  is unmarked prose. ADR-0082 §1's test is stated over a clause being amended, and
  there is no clause here to amend; ADR-0146's marked clauses in §8 are about not
  adding conditions to ADR-0017 §3, standing grants, and not citing that ADR toward
  designation, and this ADR touches none of the three.
- **The second limb: nothing a reader would do changes.** ADR-0146 §6's **marked**
  clause binds "the lane that designates the `tools/` seam" to record each span's
  provenance with the payload it binds and carry it into the audit record. That
  obligation is untouched, is still owed by that lane, and is now easier to discharge
  rather than differently scoped. §8's own prose named the route this decision took —
  the marker "is contract surface and so is its own PR (golden rule 5, ADR-0015 §5)"
  — and this is that PR. A deferral discharged by the route the deferral named is the
  deferral working.
- **What the trigger sentence turns out to have got wrong is a prediction, not an
  obligation**: it predicted which lane would first hold a producer. ADR-0148 §11's
  last paragraph had already read it that way, reassigning the judgement to "the same
  lane's decision, made with the same producer in hand", and ADR-0148 §12 recorded "no
  record owed" against §8 while doing so. Under ADR-0082 §1 a stale prediction in
  unmarked prose is recorded in the ADR that overtakes it — which is §5 above, by
  name — and nowhere else.

**ADR-0021 §1 — a record is owed and it is already written; this ADR adds nothing.**
ADR-0148 §12 ruled the test out **yes** for §1's "the decision binds the payload and
holds none of it", and wrote both halves: the `Status` qualifier and the dated note
appended to §1. ADR-0148's Consequences say surface (a)'s lane "inherits the ADR-0082
§1 record against ADR-0021 §1", which is an inheritance conditional on this surface
widening past what that note records. It does not, and the check is exhaustive rather
than asserted. The note names what the recorded decision now holds: "the canonical
destination set with the supplied form each member came from, the connected account's
identity and **connection reference** ... the transport endpoint, and a payload
*description*", and adds that the description "states extent, provenance, tiers and
destinations rather than content". Every field this ADR adds is inside that sentence:

- `EgressDestination.supplied` and `.canonical` — named verbatim.
- `EgressDestination.protocol` — not an argument value; it names which canonicaliser
  related the two forms.
- `ConnectedAccount.identity` and `.reference`, `transport_endpoint` — named verbatim.
- `EgressSpan.provenance`, `.tier`, `.extent` — "extent, provenance, tiers" verbatim.
- `EgressSpan.argument` and `.index` — an argument **name** is part of
  `parameters_schema` and is therefore already stored verbatim in every decision
  (ADR-0021 §1's `tool` clause); an index is a position. Neither is an argument value,
  and §1's sentence declines to store *values*.

So no field of this surface stores an argument value the note does not already name,
and ADR-0082 §1's rule that a record is written "in the ADR that makes it, and nowhere
else" means a second note recording the same substance would be the book-keeping the
section forbids.

**ADR-0021 §3, §4 and §5 — no record owed.** §3's rule that a policy returns a
`PermissionRuling` and never a `PermissionDecision` is relied on unchanged: the binding
is transcribed from the request by `core`, so a policy has no field in which to name
one. §4's append-only, write-once trail is unchanged and holds a wider record, which is
not a change to how it holds records. §5's floors are untouched; ADR-0148 §8's two
additional floors are stated over this value and neither is relaxed.

**ADR-0029 §1, §2 and §8 — no record owed.** §2's three seam checks re-run
`authorises` on a revalidated, detached copy; a fifth conjunct makes that check
strictly stronger without changing its shape or its order. §1's biconditional and §8's
`approval_ref` obligation are untouched. ADR-0037 §3's equality check is the near miss
and clears on its own sentence, exactly as ADR-0148 §12 found for its own addition: it
"is total over the fields, **so a field added to `PermissionDecision` later is covered
without anyone remembering to extend a list**".

**ADR-0044 §1 — no record owed.** Its note on ADR-0021 §1 records `execution_id`
becoming "a **fourth conjunct**". That is a true record of what ADR-0044 did; a fifth
conjunct added later does not make it false, and nothing in §1 there claims the list
is closed.

**ADR-0016 §3, §4 and §6 — no record owed.** `discloses` stays a ceiling and §6 above
forbids reading a description as narrowing it. `parameters_schema` stays a
`FrozenJsonMapping` and no field is added to `ToolDefinition`; §6's declaration rides
inside a field already declared to hold arbitrary JSON, which is that field being used
rather than widened. §6 there — the registry rebuilt in memory each run — is the reason
the account is bound in the request and not on the registry, which is ADR-0148 §6's
finding consumed, not ADR-0016's rule changed.

**ADR-0145 §5 and §6 — no record owed, and §6 above adds a constraint rather than an
exception.** The dialect rule and the refusal of an unreadable schema both stand;
§6 above binds (b)'s vocabulary to not breach either. Nothing here permits a second
dialect, a per-tool option, or a schema this repository declares and cannot read.

**ADR-0146 §1, §2, §5 and §6 — no record owed.** §1's two provenance answers become an
enum with those two members. §2's carried-not-inferred rule and its fail-closed default
are restated for this field and are neither widened nor relaxed — §5 above discharges
the default by requiring the builder to write it rather than by defaulting the field,
which is stricter. §5's third clause is the one §6 above declines to discharge, and
declining to discharge a clause leaves it exactly as binding: ADR-0148 §12's own form,
"the condition is not made false or over-wide by being answered", read in the negative.
§6's recording obligation on the designating lane is untouched.

**ADR-0004 §1, §6 and §7 — no record owed.** `DataTier` is used for what it is. §6's
deletion rules do not reach a description that names no record (§10), which is an
answer to #57's open question and not a change to §6. §7's minimisation rule stays
scoped to the model provider, as ADR-0017 §9, ADR-0146 §8 and ADR-0148 §13 each left
it; a per-call description makes minimisation *checkable* without extending §7's own
sentence.

**ADR-0125 §2 and §4, and ADR-0149 — no record owed.** No slot enters this surface
(§7), which is ADR-0148 §6's rule restated for a new value rather than a new rule.
ADR-0149's connection record and its reference are consumed exactly as it defined
them; nothing here adds a holder, a face, a write or a lifecycle.

**ADR-0017 §2 and §3 — no record owed.** §2's reservation of designation is honoured
and stated in this ADR's header. §3's conditions 8 and 10 get the `core` value their
mechanism needs; supplying it discharges nothing, and ADR-0017 §3's own sentence that
the later ADRs "may satisfy any of them however they judge best" is the sentence this
is working under.

**ADR-0018 §3 and ADR-0059 §1 — no record owed.** §3's detachment discipline is
extended to one more field of `ActionRequest`, which is the discipline applied, not
altered. ADR-0059 §1 fixes `from_request`'s signature — the recorder-supplied `id`,
`decided_at`, `resolves` and `expires_at` — and §9 above adds no parameter to it,
which is the point of transcription.

**ADR-0137 §2 — no record owed.** §11 above records that (a) adds no Protocol, so
§2's widening has no triad to carry here; it is neither invoked nor narrowed.

**Nothing is superseded and nothing is amended, so `docs/adr/0150-…md` is the only
file this change touches.** No accepted text is rewritten anywhere (ADR-0070 §1).

### 14. PR #1120's eleven observations, and where each lands

This section is a classification and is not normative (ADR-0089 §1). It exists so that
a reader can check that the producer's evidence was spent rather than cited.

| # | The producer's observation | Where it lands |
|---|---|---|
| 1 | A destination set has two shapes | **§3.** Occurrences are carried; the set is derived and protocol-qualified. |
| 2 | The selecting argument is part of what the user approves | **§4** carries it on every span; **§10**'s third clause puts it in the confirmation. |
| 3 | Per-span provenance needs a span identity | **§4.** `(argument, index)`, with the index rule stated so it is derivable. |
| 4 | A system-selected free-text span has no ruled tier | **§6.** Named as a residue against ADR-0146 §5's third clause, with the closing lane and its ADR-0082 §1 duty named. Not closed. |
| 5 | `discloses` cannot express what an egress tool transmits | **§6**'s last clause: the description is the per-call measure, `discloses` stays the ceiling, and neither is read as the other. |
| 6 | The connected-account-only case is not expressible | Answered by **ADR-0149**, which merged after that observation was written; **§3**'s account-member clauses and **§7** make it expressible here. |
| 7 | A description nobody can render is not inspectable | **§10**'s fourth clause: no rendering rides here, and no rendering is the bound artifact. |
| 8 | (b)'s signature must be able to fail | **§11**'s second clause, routed to (b) and not decided. |
| 9 | A refusal message is a Tier 1 hazard | **§8**'s second clause, per model rather than per package. |
| 10 | (b)'s inputs need checking and (a)'s should not | **§8.** Validating `core` models, which is what closes **#1122** rather than moving it. |
| 11 | The declaration is what the checks are worth, and it is unverified | **§4** closes the arithmetic half in `core`; the semantic half — a body field declared destination-bearing — stays open, in ADR-0148 §2's class of "a defect in the same class as a mis-declared `discloses`". §11 routes the remainder to (b). |

### 15. Marking, review and ratification

**Marked under ADR-0089**, so this ADR is in the marked regime: its unmarked prose
supplies no obligation and exists to determine what the marked clauses mean (§3
there). Marking is forward-only (§5), and nothing ratified before it is drawn into the
regime by it.

**The required set is adversarial *and* architecture.** This ADR decides a contract
surface in the sense `CONTRIBUTING.md` → "Stop when the required reviews are green"
gives — it is the ADR that authorises the `core` additions §2 enumerates — and both are
run while it stands `Proposed` so that a finding can still change the decision.
`CONTRIBUTING.md` → "Finishing an ADR PR" owns the sequence; this section points at it
rather than re-deriving it, and the outcome is recorded here on ratification.

## Consequences

- **ADR-0148 §11's first deferred surface is decided and none of it is landed.**
  Surface (b) is still owed, and until it merges nothing implements against either:
  ADR-0148 §11's second clause and ADR-0015 §5 both say so, and a request cannot be
  built without the seam that supplies its binding.
- **ADR-0146 §8's marker is spent, by the route §8 named.** It rides inside the
  payload description as a field of each span, so there is one carriage, one place to
  read it, and no join to get wrong. ADR-0146 §6's recording obligation on the
  designating lane is unchanged and is now discharged by writing a span rather than by
  designing a mechanism.
- **`ActionRequest` and `PermissionDecision` grow by one field each and change
  behaviour for nothing that exists.** The surface is breaking in ADR-0148's sense —
  the most-consumed values in the pipeline are wider, and every consumer now consumes
  the wider type — and §12 requires the pin that proves the `None` path is unchanged
  rather than leaving it as a claim.
- **Two of ADR-0148 §14's mandated cases become unconstructable rather than
  forbidden.** An omitted span and a description naming an argument the call does not
  carry are refused by `ActionRequest`'s own validator, in the same way ADR-0029 §2
  made an unauthorised `ToolCall` unconstructable. The other cases in §14 stay tests,
  because they are about what a callable does.
- **#1122 is closed by this surface rather than moved.** Its own disposition said so:
  the shape that ends the unchecked-input class is a validating `core` model, and §8
  is that model. The `tools/`-internal value types PR #1120 defined are superseded by
  it when the implementing lane lands, and that lane is where the issue closes.
- **#57 is narrowed again and stays open.** Its authorisation-time face is now a
  concrete value with a stated shape; its granularity question, its richer-structure
  question and its deletion question are answered *for this artifact* — no record
  identifiers, so no deletion interaction — and stay open for anything richer, which
  §10's last clause binds to projecting onto this one.
- **One gap is opened explicitly and given an owner.** ADR-0146 §5's third clause —
  a value the system already tiered, carried into a field that establishes none — is
  not discharged by this description, is not detectable without machinery nothing has,
  and is not refused, because refusing it would be a bound with no mechanism behind
  it. §6 names the lane that owes it and the ADR-0148 §6 clause that lane will amend.
- **`SMTP` accepts less than RFC 5321 admits, and the cost is a user who cannot yet
  email an internationalised address.** Six forms are refused rather than carried
  byte-exact, each because the protocol does not settle its equivalence and this ADR
  would rather spend a recoverable error than an undetectable disclosure — ADR-0017
  §4's asymmetry argument, that "a boundary that has never transmitted can be held to
  the standard we would want everywhere". The acceptance boundary is a **closed
  grammar** rather than a list of refusals, so a form nobody thought of is refused
  rather than silently canonicalised by whichever implementation saw it first. The
  cost is real and the route out is named rather than left to erosion: §3 makes widening `SMTP` an ADR, on the same
  terms as adding a protocol, so the forms come back with an argument about what
  equivalences they establish rather than as a patch to a canonicaliser.
- **Nothing here authorises a byte.** The seam remains approved and undesignated, no
  tool is registered at it, and this ADR supplies a value for a decision that has
  nothing to rule on yet.
