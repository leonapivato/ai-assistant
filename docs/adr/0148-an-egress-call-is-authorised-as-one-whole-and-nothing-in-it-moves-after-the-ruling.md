# 148. An egress call is authorised as one whole, and nothing in it moves after the ruling

- Status: Proposed
- Date: 2026-08-13
- Decides: the `permissions/`-side mechanisms ADR-0017 §3 reserves to "the
  invocation and `permissions/` ADRs" — how an egress call is **authorised**,
  **bound** and **audited**. §10 states, condition by condition, which of §3's
  fourteen this ADR gives a mechanism to and which it leaves.
- Does **not** designate the `tools/` egress seam. ADR-0017 §2 reserves that to a
  later ADR that names the module, attests each §3 condition **is satisfied in
  code** and records the transition. This ADR supplies mechanisms; attesting they
  hold is not a statement a prose ADR can make (§13).
- Is **not** the ADR ADR-0147 §4's fourth and fifth clauses require before an MCP
  server is connected to over a stdio transport, and does not become it by
  ratification (§13).
- Requires **new `core` contract surface** and lands none of it (§11). Flagged
  under golden rule 5.

## Context

### What ADR-0017 §3 asks for, and what has and has not answered it

ADR-0017 §1 permits user data to leave from "a designated integration seam inside
`tools/`" and §2 leaves that seam **approved and undesignated**: it "transmits
nothing until it is designated, which requires the conditions in §3 to hold in
code and a later ADR to ratify that they do". §3 lists fourteen conditions,
states that "none is discharged today", and — this is the sentence this ADR is
written under — that "each is a property that must hold, not a design; the
invocation and `permissions/` ADRs own the mechanisms and may satisfy any of them
however they judge best. What they may not do is designate the boundary with one
unsatisfied."

The invocation half exists. ADR-0029 is the invocation ADR, and it says in its own
header that it "does **not** designate the `tools/` egress seam", inheriting §3's
list "unabridged and undischarged". Two of §3's fourteen have since been answered
by ADRs of their own: outbound payload classification by ADR-0146 (closing #94),
and the seam's *name* by ADR-0147 §3 — which ADR-0147 §11 is careful to record as
"§2 working rather than §2 being amended".

What has no decision is the middle: **how an egress call is authorised, bound and
audited.** ADR-0021 §6 lists "Recipient authorisation (ADR-0017 §3, issue #68)"
among its deferrals and names the trigger — "It needs resolved destinations, which
need arguments interpreted per tool, which needs invocation." Invocation landed in
ADR-0029. The trigger has fired and nothing has taken it up.

### The five ways to satisfy every other condition and still leak

Each of the following came out of adversarial review of PR #72 and is recorded in
the issue named beside it. They are the shape of the problem and each is answered
by a section below.

- **Tier is not destination** (#68). A tool declaring it may disclose `PERSONAL`
  satisfies its declaration whether the bytes go to the calendar the user
  connected or to an address supplied as a parameter. A `permissions/` grant is
  not recipient authorisation: ADR-0016 §3 permits auto-granting, "which says
  nothing about where the bytes went".
- **Credential-scoped is not recipient-scoped** (#68's third comment). A Gmail
  `send` is authorised because `googleapis.com` is credential-scoped, while its
  `to` argument names an address the user never approved. The connection is
  legitimate, the credential is the right one, every check passes.
- **Read-then-check-then-stop** (#74). An implementation reads an integration's
  OAuth token from the keyring, *then* runs the per-call check and stops when
  denied — satisfying every other condition having already accessed Tier 0
  ungated. ADR-0004 §7 gates access, so the read is what needs gating.
- **The ceiling is not a measurement** (#57). A tool declares it may disclose
  Tier 1, obtains authorisation for the resolved destination, records it — and
  sends the user's entire memory database instead of the one selected record.
  Every audit field required so far is populated, and nothing binds *what* was
  sent. #57's own comments sharpen the requirement from a digest to an
  inspectable description: "which records, how many, at what tiers".
- **Resolution as a back door** (#93 item 4). Turning `#team` into a channel id
  needs a remote call. If that lookup is not itself gated, the preconditions are
  unsatisfiable — a tool cannot look up the id it is required to bind to without
  transmitting first — and unauthorised egress returns as a side channel.

### What is already ratified and is consumed rather than rebuilt

The corpus is further along than ADR-0017 §3's list reads, and most of this ADR is
joining what exists rather than inventing:

- **ADR-0029 §2** makes an unauthorised call unconstructable: `ToolCall`'s
  validator runs `PermissionDecision.authorises`, and `invoke` re-runs three
  checks in a fixed order — revalidate and detach, match the registry's own
  definition, re-evaluate `authorises` on the detached copy.
- **ADR-0021 §1** embeds the whole `ToolDefinition` by value and binds the
  arguments by `parameters_digest` while storing none of them; §4 makes the trail
  append-only, write-once and validating; §5 forbids auto-granting any non-empty
  `discloses`, "written against auto-granting, not against the outcome".
- **ADR-0037 §2** fixes the order — decide → record → **read back** → claim — and
  §3 makes the authority handed to the executor the trail's own copy.
- **ADR-0014 §4** already carries a claim committed before the tool runs, an
  `approval_ref` without which `→ RUNNING` is refused, a durable `INDETERMINATE`,
  and a recovery scan that reconciles a step left `RUNNING` by a crash.
- **ADR-0125 §8** gives `tools/` the `Secrets` face "at the tool that needs one,
  by injection", `INTEGRATION`-scoped, and §9 states that seam "does not gate" and
  is shaped so #74 can land into it.
- **ADR-0146** settles classification: a value's tier never moves with provenance,
  every outbound span is user-authored or system-selected, and §4's third clause
  rules that at the `tools/` seam **authorisation is owed on every call**
  whatever determined the recipient.
- **ADR-0145** puts argument checking *before* anyone is asked — a schema
  violation is refused at construction, "before the ruling and before the claim".
  §1 below occupies the same slot for destinations.

### What this ADR is not allowed to settle

Four things, and each is refused in §13 with its reason rather than left silent:
designation itself (ADR-0017 §2); transport pinning's *implementation* (#83); the
payload manifest *artifact* (#57); and the stdio-server authorisation ADR-0147 §4
demands. To those ADR-0098 §3's last clause adds a fifth, reserved by its own words
to "the lane that designates an actuation seam" — whether a **standing**
authorisation may cover an action a model selected while reading external content —
and ADR-0146 §8's second clause holds the neighbouring one for standing grants.
Neither is answered here.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

The decision in one sentence: **an egress call is authorised as one whole — one
tool bound to one connected account, one canonical destination set, one payload
description, one decision — and every part of that whole is fixed before the
ruling and moves for nothing afterwards.**

Throughout, **egress call** means an invocation, through the module ADR-0147 §3
names as the seam, that transmits off the device under ADR-0124 §1's second
boundary; and **destination-bearing argument** means an argument of such a call
from which a semantic recipient **of that same call** is determined. The scope
matters where a call's whole purpose is to interpret a name: the key a resolution
call sends to a lookup service is an argument of that call and not a destination
of it, so that call's own destination set is the connected account under §2's
third clause and §1's refusal of an unresolved destination does not reach it (§5).

### 1. The unit of authorisation is the whole call, and it is complete before the ruling

> **Normative.** No component transmits through the seam except from a callable
> reached by `ToolInvoker.invoke` on a `ToolCall` (ADR-0029 §2) whose decision
> authorises the request being performed. There is no second route to the seam,
> and none may be added by configuration, by a declaration, or by an integration
> constructing its own client.

> **Normative.** The `ActionRequest` a policy rules on for an egress call is
> already complete. It fixes the registered tool, every destination-bearing
> argument in both its supplied and its canonical form (§2), and the payload
> description (§6). Nothing in it is resolved, canonicalised, defaulted, expanded
> or added after `ActionPolicy.decide` has been reached.

> **Normative.** A request that cannot be completed in that sense — a destination
> that will not canonicalise, a name that has not been resolved, a description
> that cannot be derived — is **refused before the ruling**, and no ruling is
> sought for it. It is never sent in an incomplete form and never completed
> afterwards.

**The whole of this ADR rests on the second clause, and the reason is that every
other condition is stated over something that has to exist at ruling time.**
Recipient authorisation "bound to the resolved destination" (ADR-0017 §3) is
vacuous if the destination resolves later; a payload "bound before transmission
and described inspectably" is vacuous if the description is computed from
arguments the ruling did not see. ADR-0021 §1 already binds the arguments by
digest and ADR-0029 §2 already re-evaluates that binding at the seam — so
everything placed in the request before the ruling is bound end to end by
machinery that is ratified, implemented and re-checked, and everything placed in
it afterwards is bound by nothing at all. The design work is therefore almost
entirely about **moving facts earlier**, not about adding checks later.

**ADR-0145 is the precedent and the slot is the same one.** It refuses a schema
violation "at construction, before the ruling and before the claim", on the
ground that a check after the ruling asks the user about an action that cannot be
performed. A destination that resolves after the ruling is the sharper case: the
user was asked about an action, and a different one was performed.

**The third clause is the fail-closed direction, and it is stated because the
permissive reading is the one an implementation drifts into.** Where a
canonicaliser has no rule for a protocol, the tempting behaviour is to pass the
supplied form through and let the upstream sort it out. That is exactly how a
grant for one address comes to authorise another (#93 item 3). Refusing costs a
recoverable error the user sees; proceeding costs a disclosure nobody can detect
afterwards, which is the asymmetry ADR-0029 §5 used for its own fail-closed
window rule.

### 2. Destinations are canonicalised per protocol, before the ruling, and exact where equivalence is unproven

> **Normative.** For every destination-bearing argument of an egress call, a
> **canonical form** is computed under the rules of the protocol that names that
> destination, before the `ActionRequest` is built. The canonical destination set
> of the call is the set of canonical forms of every semantic recipient its
> arguments select.

> **Normative.** Where the protocol does not establish that two distinct supplied
> forms denote the same recipient, the canonical form is the supplied form
> unchanged and comparison against it is byte-exact. No canonicaliser folds case,
> strips, reorders or rewrites a form on any ground weaker than the protocol
> saying those two forms are one recipient.

> **Normative.** Where an egress call's arguments select no recipient beyond the
> service the call is made to, its canonical destination set is the **connected
> account** alone (§6), and it is authorised against that.

> **Normative.** Both the supplied and the canonical form of every
> destination-bearing argument are carried in the request and appear in the
> payload description (§6), so that both are in the audit record.

> **Normative.** Canonicalisation performs no I/O of any kind. A canonicaliser
> that needs to ask a remote service what a name denotes is performing the
> resolution §5 governs, and is subject to §5 rather than to this section.

> **Normative.** For each protocol, the canonical form of a supplied form is
> computed in **one** place at the seam. No integration supplies its own
> canonicaliser for a protocol the seam already canonicalises, so that two
> integrations speaking one protocol cannot disagree about whether two
> destinations are the same recipient.

**The exactness default is the whole of this section's security content, and it
is stated as a default rather than as advice because both directions of the error
are live.** #93 item 3 names them: "lowercasing an address whose local part the
protocol treats as case-sensitive lets a grant for one address authorise another;
provider aliasing gives the inverse failure." The first is a disclosure and the
second is a refusal, and a rule that let an implementation choose would choose the
first, because the first is the one that makes a demo work. RFC 5321 makes the
local part of an SMTP address case-sensitive and leaves the domain not; a
canonicaliser that knows that may fold the domain and must not fold the local
part, and one that does not know it folds nothing.

**One canonicaliser per protocol, rather than one per integration, for #83's
reason applied on the destination axis.** #83 asks "whether the HTTP client is
constructed centrally at the seam so the policy cannot be bypassed per
integration. If each integration builds its own client, this is unenforceable by
construction." The same sentence is true of canonicalisation with "client"
replaced by "comparison": two integrations speaking SMTP that disagree about
address equivalence make a standing authorisation mean different things in
different tools, and no test of either one detects it.

**The third clause is what keeps a read from needing a recipient it does not
have.** #68's third comment carves out operations that "cannot disclose onward to
an argument-chosen recipient — a read, or a write whose effect stays inside the
connected account", and then warns that the carve-out "needs care: whether an
operation can disclose onward is itself a property someone has to declare or
derive, and getting it wrong reopens the hole." This ADR does not declare or
derive it. It states the rule over what the arguments *select*: a call whose
arguments select no onward recipient has the connected account as its whole
destination set, so the carve-out is not an exemption from authorisation but an
answer about what is being authorised. An integration that believed its operation
selects nothing while an argument in fact names a recipient has mis-declared its
destination-bearing arguments, which is a defect in the same class as a
mis-declared `discloses` and is not made safe by a separate carve-out.

**The no-I/O clause exists because it is the join between this section and §5.**
A canonicaliser that resolved would be an ungated egress call performed while
building the request the gate has not yet ruled on — the back door #93 item 4
describes, arriving through the one component nobody would think to look at.

### 3. Recipient authorisation traces to a user act, and today there is exactly one route

> **Normative.** A ruling may be `ALLOW` on an egress request only where every
> member of its canonical destination set is covered by one of two things: **(a)**
> a decision of the user recorded in the `AuditTrail` as the resolution of a
> `CONFIRM` about *this* request, under ADR-0021 §4's resolution invariant; or
> **(b)** a **standing user policy** established by a recorded act of the user.
> `PermissionRuling.authorised_by` (ADR-0021 §3) names which.

> **Normative.** None of the following is a user act and none authorises a
> recipient: a tool's own declaration, the scope or audience of a credential, a
> configured base URL or host, an allowlist the system assembled, a recipient
> appearing in a prior call, and a destination this system extracted from a span
> it selected (ADR-0146 §1, §2). A recipient that first appears in the user's own
> words is authorised by the user answering about *this* call, not by having been
> typed (ADR-0146 §4's fourth clause and the paragraph it is stated for).

> **Normative.** No standing user policy authorises an egress recipient until an
> ADR establishes standing grants (ADR-0021 §6). Until it does, route (a) is the
> only available route, and no lane reads limb (b) above as ratifying, narrowing
> or pre-shaping ADR-0021 §6.

> **Normative.** A `SourceGrant` (ADR-0097) is never limb (b). ADR-0097 §7
> forbids citing one as `PermissionRuling.authorised_by` and forbids an
> `ActionPolicy` from consulting either grant seam; nothing here relaxes that,
> and no lane reads limb (b) as an opening for it.

> **Normative.** The ADR that establishes standing grants for egress recipients
> decides, explicitly and in its own text: ADR-0021 §3's named precondition —
> that the second source of an `authorised_by` be resolvable to a recorded user
> decision that actually covers this call, and where those records live — bound
> to the canonical destination set rather than to the tool; ADR-0098 §3's last
> clause; and ADR-0146 §8's second clause. It may not inherit an answer to any of
> the three from this ADR, from this ADR's silence, or from limb (b)'s existence.

**Limb (b) is written now and left unusable now, and that is deliberate rather
than untidy.** ADR-0021 §5's disclosure floor sends every egress tool to `CONFIRM`
— §8 below makes that universal at the seam — and §6 there records the cost in
terms: "Until it lands, a disclosing tool prompts every time, which is the correct
default and a poor steady state." Writing the authorisation rule with only limb
(a) would make the standing grant a *relaxation* of this ADR when it arrives,
which is the shape ADR-0021 §5 went out of its way to avoid when it wrote its
floor "against the distinction that matters rather than against a proxy for it,
which is what keeps §6's relief valve reachable without amending this clause."
The same reasoning applies one level up, and the third clause is what stops the
valve being opened by anyone but the ADR that owns it.

**Why tool egress does not reuse the source-grant shape, and which half of it it
does.** ADR-0097 is the nearest ratified precedent for a recorded user act
authorising an ongoing reach: a grant is a recorded act on a **named source**,
revocation is prospective, and ADR-0133 adds that a producer's read is a *third*
use of the same source which the user grants separately, per use rather than per
source. The corpus has already ruled the two apart — ADR-0097 §7 says a
`SourceGrant` "may never be cited as `PermissionRuling.authorised_by`" and that
ADR-0021 §5's floor "is neither relaxed nor satisfied by anything in this ADR",
naming the hazard precisely: "a calendar-read grant silently authorising an
off-device transmission — the floor satisfied by a consent the user gave about
something else entirely." The fourth clause above is that ruling read forward onto
this seam. But the prohibition is a conclusion, and the reasons behind it are
what a standing-grant ADR will need. Two properties make the grant shape work
there and neither holds here.

- **The subject is enumerable in advance and the user chose it.** A source is a
  thing the user picked from a list the hub can offer, and ADR-0139 goes further
  — the standing grant is "read from the store, not from the sources the hub can
  offer", so even the offer set does not define it. An egress recipient is chosen
  **per call, from arguments a model produced**. There is no set to enumerate and
  no moment at which the user could have been shown one.
- **Nothing downstream of the grant chooses.** After a source grant, a producer
  reads that source; the grant fully determines what is reached. After a grant
  over "my Gmail account", a model determines who receives the bytes — which is
  precisely #68's third comment, where the credential-scoped host is legitimate
  and the `to` argument is the attack.

So the half that transfers is **the record**: a user act, stored, prospective,
and per-use rather than per-source — ADR-0133's granularity argument is the right
one to carry, and it is why limb (b) says "a standing user policy" and not "a
connected account". The half that does not transfer is **the reach**: a grant over
a source authorises the reads that follow it, and a grant over an account cannot
authorise the recipients that follow it, because those are not the account's and
are not the user's choice. That is the whole reason limb (b) is bound to the
canonical destination set by the first clause rather than to the tool or the
account, and the reason the standing-grant ADR has a real design problem to solve
rather than a precedent to copy.

**The second clause is the list of near-misses, and every entry on it is a way a
real system has been built.** Each is refused for the same reason: it is a fact
about the system's own configuration or about a model's output, and ADR-0146 §2
rules that provenance is "decided by recorded origin, never by inspecting a span
and never by matching it against anything the user wrote." An address a model
lifted out of the user's message is a span this system selected, and letting it
authorise its own send "would let any address a model lifted out of text authorise
its own send, which is §2's inference problem arriving at the one place it costs
the most" (ADR-0146 §4). ADR-0146 routes that case here; this is where it lands,
and the answer is that the user is asked about the resolved destination, per call.

### 4. A multi-recipient call is one set, and a member is never dropped to make it fit

> **Normative.** The canonical destination set is authorised as a **single**
> value. A ruling is about the set, never about a member, and there is no
> partial `ALLOW`.

> **Normative.** Where any member of the set is not covered under §3, the whole
> call is refused. No component removes the uncovered member, narrows the set, or
> constructs a second request from the remainder, and no such narrowing is offered
> to the user as an alternative to the refusal without a fresh ruling on the
> narrower set.

> **Normative.** No component adds to, removes from, substitutes within or
> reorders the canonical destination set between the ruling and transmission. The
> callable transmits to every member of the bound set and to no other recipient.

**Silent narrowing is the failure worth spending a clause on, and it is worth
being precise about why it is worse than the refusal.** #93 item 2: "Delivering to
the authorised subset silently sends a message the user never approved the shape
of, and partial success is the hardest failure to notice afterwards." A message
approved as *to Alice and Bob* is a different message from the same text *to Alice
only* — a reply-all that quietly becomes a reply is a disclosure decision made by
a filter — and the audit record of the narrowed call is perfectly consistent with
itself.

**The third clause is enforced rather than exhorted, and this is where §1's
earliness pays.** The set is in the request; the request is bound by
`parameters_digest`; `authorises` compares that digest; and ADR-0029 §2 makes
`invoke` re-run the comparison on a **revalidated, detached** copy, in that order,
before the callable is reached. So a member added after the decision — including
by the `__dict__` write ADR-0029 §2 treats as in scope — produces a different
digest, `authorises` answers `False`, and the seam raises `ToolBindingError`
rather than transmitting. Nothing new is needed for it, and the clause is written
so that a later lane cannot satisfy it by re-deriving the set at the seam.

**What this does not claim is delivery.** An upstream that accepts a message for
three recipients and delivers to two has produced an outcome, not an
authorisation defect, and ADR-0029 §3's result taxonomy is where it is reported.
A tool that cannot establish which of the two happened returns
`INDETERMINATE` under ADR-0029 §4's rule, and §9 below is where that becomes the
attempt's recorded outcome.

### 5. Resolving a name to an identifier is a call like any other, never a side channel

> **Normative.** Obtaining an identifier for a destination by asking a remote
> service is itself an **egress call**: a registered tool with its own
> declaration, its own `ActionRequest`, its own decision, its own claimed step
> (§9) and its own audit record, subject to every clause of this ADR. No component
> performs such a lookup outside that route.

> **Normative.** A destination reaching an egress call comes from exactly one of
> three places: it was supplied by the user in the act that authorises it (§3), it
> was obtained by a resolution call under the clause above, or it was read from
> data this system already obtained through a gated path. There is no fourth
> source, and a destination whose source is not one of these is refused before the
> ruling (§1).

> **Normative.** A resolution that fails, is refused, or is denied never falls
> through to a send. The request that would have consumed its result is refused
> before the ruling, and no component substitutes the unresolved name, a cached
> value, or a default.

**"Or is forbidden" is the branch ADR-0017 §3 offers and this ADR declines, and
the reason is that forbidding it is not actually the conservative choice.** §3's
condition reads "**or** is forbidden, with destinations required to come from data
already obtained that way". Taken literally that is buildable — but the data
"already obtained that way" has to have been obtained somehow, and an integration
that cannot look up a channel id will be given one by a configuration file, an
operator, or a model that has seen one before. Each of those is an unaudited
destination arriving through a path with no decision attached, which is the same
hole with the gate moved outside the system. Making resolution a first-class
egress call keeps every destination on the record, and it costs a second prompt
rather than a second mechanism — the resolution call's own destination set is the
connected account (§2's third clause), so it is exactly the case ADR-0021 §5's
floor was drafted for.

**The three-source clause is what makes the first one enforceable.** Without it
the rule is "resolution is gated", which an implementation satisfies by never
calling it — and then accepts a channel id from wherever. With it, a destination
has a provenance the audit record can state, and the failure mode of an
integration that wants an ungated shortcut is a refusal rather than a silent
alternate path.

### 6. The binding: four facts, each with a holder, and no credential value among them

ADR-0017 §3 requires that "what is transmitted is bound to what was authorised,
immutably, and consumed unchanged — covering at minimum the connected account,
the canonical destination set, the approved payload description and the decision",
with credential *values* excluded. The decision is bound by machinery that already
exists; the other three travel together in one value the request carries.

> **Normative.** The **decision** is bound by its id: `ToolCall.decision` carries
> the decision the trail returned (ADR-0037 §3) and the committed `approval_ref`
> equals `call.decision.id` (ADR-0029 §8). No egress call is performed under a
> decision the executor did not read back out of the trail.

> **Normative.** The remaining three facts travel together as one value, the
> **egress binding**: the canonical destination set with the supplied form each
> member came from (§2), the **connected account** as both its identity and its
> connection reference (below), the **transport endpoint**, and the **payload
> description**. It is fixed in the `ActionRequest` before the ruling, is compared
> by `PermissionDecision.authorises` alongside the tool, the parameters digest and
> the step, and is transcribed verbatim into the recorded decision. Nothing in it
> is derived after the ruling and nothing in it is re-derived at the seam.

> **Normative.** The connected account is bound by **two** non-secret facts, not
> one: its **identity** — the durable, user-recognisable name of the account
> itself, recorded when that account was connected — and its **connection
> reference**, which names that account's **connection record** and nothing else.
> A connection reference is **not** a `SecretName`: `SecretName` (ADR-0125 §2) is
> reserved here for a **credential slot**, which is per provisioning act and
> therefore not stable enough for a binding (below). Neither bound fact is a
> secret and both may be held in a Tier 1 store (ADR-0125 §2). An account whose
> identity was never recorded is not connectable, no tool is registered against
> it, and no identity is inferred from a credential, a slot, a name or an endpoint.

> **Normative.** A tool registered at the seam is bound to **at most one connected
> account**. An integration serving several registers one tool per account.

> **Normative.** Before transmitting, the callable refuses unless **all four**
> hold: the bound reference is **connectable** (below); the transport endpoint the
> binding carries is the one it is configured to use; the connection reference the
> binding carries names the connection record it consults, and it reads under the
> slot that record names (below); and
> the account identity **currently recorded for that reference** equals the
> identity the binding carries. A registry rebuilt under a different configuration
> — across a restart, which is exactly when a parked `CONFIRM` is answered —
> refuses the call rather than performing it against another account or another
> endpoint, and so does a reference re-provisioned for a different account.

> **Normative.** A reference's connection record carries a **monotonic revision**,
> incremented by **every** provisioning act on that reference — including one that
> leaves the identity unchanged. A revision is never reused and never decreases.

> **Normative.** A connection record carries a **provisioning state**, which is
> **pending** or **active**, and the **credential slot** — a `SecretName`
> (ADR-0125 §2) — that the act which wrote the record wrote its credential to. A
> provisioning act writes **its own slot**, never a slot an earlier act wrote, and
> a slot is never written by two acts.

> **Normative.** Provisioning or re-provisioning a connected account is **three
> writes in a fixed order**: the connection record **first**, as *pending*,
> carrying the identity, the incremented revision and this act's slot; the
> **credential second**, into that slot; and the record marked **active third**.
> No other order is permitted. The activation is part of the same provisioning act
> and changes neither the identity, the revision nor the slot, so a completed act
> increments the revision exactly once. No transaction spans the keyring and the
> connection record, and none is required.

> **Normative.** The **connection reference** the binding carries names the
> connection record; the **slot** is what the callable reads under, and it is
> obtained from that record in the same step as the identity and the revision.
> The reference is therefore stable across a rotation, which is what keeps a
> parked `CONFIRM` answerable after one (ADR-0125 §4), while the slot moves with
> every act. No binding carries a slot and no lane compares one against a binding.

> **Normative.** A slot no live connection record names holds nothing any call
> reads. A provisioning act deletes the slot its predecessor named once its own
> activation has landed, and a deletion that fails leaves an unreferenced slot
> rather than an incorrect one — the failure is reported and never suppressed.

> **Normative.** **At most one provisioning act owns a connection record at a
> time**, and the record itself is what confers ownership. An act *takes* it by a
> single **compare-and-swap** on that record — from the identity, revision and
> state it observed, to *pending* with the incremented revision and its own slot —
> and an act whose compare-and-swap fails never held it and writes nothing,
> neither the credential nor the activation. This is ADR-0014 §5's compare-and-swap
> applied to the one store that can offer it; nothing of the kind is asked of the
> keyring, which ADR-0125 §4 rules never refuses a `set`.

> **Normative.** Ownership is over the **record**, not over the act's own
> execution: a displaced act's ownership ends the instant the displacing act's
> compare-and-swap lands, and a keyring write it had already begun is neither
> stopped nor waited for. Two acts may therefore overlap in time — one owning the
> record, one finishing a write it started while it owned the record — and that is
> the permitted interleaving §14 requires a test for, not a violation of this
> clause. What may never overlap is ownership.

> **Normative.** Before the credential write, and again before the activation, a
> provisioning act re-reads the connection record and **abandons** — performing
> neither write — unless it still carries the identity and revision that act's own
> first write recorded. Each re-read is **one step** with the write it precedes, in
> the sense the clause below gives. An abandoned act rolls nothing back: the record
> it found belongs to the act that displaced it.

> **Normative.** A displaced act's credential write, already in flight when it is
> displaced, lands in **that act's own slot** — which no live record then names, so
> no call reads it. `Secrets.set` never refuses and the keyring offers no
> compare-and-swap (ADR-0125 §4), and neither is needed: the write that decides
> which credential is live is the **activation**, a single write to the connection
> record, and the record is the store the compare-and-swap above already governs.

> **Normative.** A reference is **connectable** only while its connection record
> exists and is **active**. A reference that is not connectable takes no part in an
> egress call at any stage: no `ActionRequest` is built against it — §11's seam (b)
> refuses, which is §1's third clause — no ruling is sought for one, and no
> callable transmits under it. Connectability is read at each of those moments and
> is never carried over from an earlier one.

> **Normative.** A provisioning act interrupted before its third write leaves the
> reference **pending**, and therefore not connectable, whichever of the first two
> writes had landed — the record ahead of the keyring, or both written and the act
> unfinished. That state is refused rather than reconciled: the call does not
> transmit, and the remedy is to run the provisioning act again, which increments
> the revision and re-enters at *pending*. No lane resolves it by trusting the
> keyring, by rolling the record back, by activating a record whose credential
> write it did not itself perform, or by inferring an identity from the credential.

> **Normative.** The check and the credential read are **one step**: no `await`
> occurs between reading the identity, revision, provisioning state and slot
> recorded for the bound reference and calling `Secrets.get` for **that slot**.
> This is ADR-0097 §5a's rule for a
> grant and a read, transposed onto the pair this section binds.

> **Normative.** After the credential is in hand and **before any byte is
> transmitted**, the callable re-reads the recorded identity, revision and
> provisioning state and **discards** the credential without transmitting unless
> the record is **still active**, the identity still
> equals the one the binding carries **and** the revision equals the one read
> before the credential read. A read that cannot be answered is treated as a
> changed one.

> **Normative.** The revision is compared **only** before against after, across
> the credential read; it is never compared against a value the binding carries.
> A **completed** rotation between the ruling and the resume therefore refuses
> nothing on the revision's account — the identity is unchanged and no revision was
> read yet — while one landing *inside* the read refuses that read. A rotation
> still in flight at the resume is refused, but by connectability rather than by
> the revision.

> **Normative.** A provisioning act landing **after** the post-read check has
> passed neither retracts the authorisation nor stops a transmission already
> begun. **No lane holds a lease or a lock from that check across the transport's
> write**, and no surface presents a re-provisioning as having stopped a send in
> flight.

> **Normative.** What the clauses above guarantee is that no byte is transmitted
> under a credential read across any provisioning act on its reference, none under
> an identity other than the bound one, and none under a reference whose
> provisioning act has not completed. They do **not** guarantee that no
> credential is ever read for a call that is then refused, nor that no byte is
> transmitted after a provisioning act is recorded, and no lane states them as
> guaranteeing either.

> **Normative.** No credential value enters an `ActionRequest`, a
> `PermissionDecision`, an egress binding, a payload description, an audit record
> or any value derived from one. Only the identity and the reference are bound.

> **Normative.** This section **binds** the transport endpoint; it does not
> **pin** it. What the endpoint must be, and what a redirect may do, is #83's and
> is not decided here (§13).

> **Normative.** The request carries, for **every span the description covers**,
> that span's recorded discloser provenance (ADR-0146 §1). It is carried rather
> than derived: no component decides a span's provenance by reading its value, its
> field or its shape, which is the inference ADR-0146 §2 forbids. Where it rides
> inside the request is ADR-0146 §8's deferred marker and is not decided here
> (§11); **that** it reaches the request before the ruling is decided here, because
> nothing downstream of the ruling may add it. This clause adds **no field** to
> `ActionRequest`, and no lane adds one on the strength of it: whatever carries the
> provenance is inside §11(a)'s deferred surface, so each shape ADR-0146 §6's own
> prose names — "a `core` type", "a wrapper the seam constructs", "the payload
> description itself" — remains that surface's contract ADR to choose, under the
> one constraint that it is in the request before `ActionPolicy.decide` is reached.
> What is consumed here is ADR-0146 §6's **requirement** that each span's provenance
> be recorded with the payload it binds before transmission — a ratified obligation,
> not the deferral beside it — and §1's earliness is only what moves that recording
> ahead of the ruling rather than after it.

> **Normative.** The payload description is **deterministic**: it is a function of
> exactly three things — the request's own arguments, each destination-bearing one
> in **both** the supplied and the canonical form the request already carries for
> it (§1's second clause, §2's fourth), the provenance the request carries for
> their spans, and the registry's definition for the bound tool — and of nothing
> else: no clock, no configuration, no store read, no network. Two derivations of
> the description for one request agree, and two requests whose supplied forms
> differ are two different inputs however their canonical forms compare.

> **Normative.** The description covers **every span the call transmits**, and a
> span transmitted but not covered is a defect rather than a permitted omission.
> A request whose description does not cover every span it would transmit cannot
> be completed and is refused **before the ruling** (§1's third clause); a callable
> that finds itself about to transmit a span the description does not cover
> refuses instead, and no approver is shown a description narrower than the
> payload. This is what makes the description an account of the call rather than a
> summary of part of it.

> **Normative.** The payload description states, for every span it covers, that
> span's **discloser provenance** (ADR-0146 §1) and its extent; it states **no
> tier** for a user-authored free-text span (ADR-0146 §5); and it states the tier
> of every value whose field establishes one. Its remaining content — the
> granularity at which records and fields are named — is #57's and is not decided
> here (§13).

**The one-account clause keeps an account from becoming a destination by the back
door.** ADR-0016 §5 already argues for declaring one tool per operation rather
than merging operations into one conservative declaration, and this extends the
same granularity to the account axis for one reason: a tool serving two accounts
has an account chosen at call time from an argument, and an account chosen from an
argument is a destination in everything but name — canonicalisable, authorisable,
and answerable only by the user. One registration per account costs an integration
a line of configuration and removes the case entirely. This binds tools registered
at the designated seam and no others.

**An earlier draft claimed the account was bound by the registry alone, and it was
wrong in the way this whole ADR is written to prevent.** That draft said the
account "is therefore fixed by the registry's own binding from id to definition
and callable, and is bound by ADR-0029 §1's two checks". Adversarial review found
on round 1 that ADR-0029 §1's two checks are that the id is bound and that the
*definition* matches, and a definition carries no account: ADR-0016 §6 makes the
registry in-memory and rebuilt each run from configuration, so a `CONFIRM`
answered after a restart — which is the ordinary case, since ADR-0037 §4 parks the
step and ADR-0029 §5 makes recoverability across a restart the property that
"makes it worth anything" — can resume against an id rebound to a second account
with a byte-identical declaration. `authorises` succeeds, the seam's checks
succeed, and the user's approval executes against an account they never saw. That
is ADR-0021 §1's own #54 argument one field further down, and the draft had
asserted a binding out of machinery that does not provide it — the shape ADR-0147
§13 records about its own §4, arrived at in a document that quotes it. The repair
is not a stronger claim about the registry; it is putting the reference where
every other bound fact already is, and adding the callable's own refusal so the
binding is checked by the party that holds the truth.

**A keyring slot is not an account, and the draft that repaired the first
defect got that wrong too.** That draft bound the account by its `SecretName`
alone, and adversarial review found on round 2 that a `SecretName` names a
**keyring slot**, not an account: ADR-0125 §4 rules that `set` "stores `value`
under `name`, creating the entry or replacing whatever it held" and "never refuses
on the ground that an entry already exists" — ratified deliberately, because
"rotation is the case that matters". So a confirmation taken against
`SecretName(INTEGRATION, "gmail")` while it held account A's token can be resumed
after that slot is re-provisioned with account B's, with the reference and the
endpoint both matching. The repair binds the account's own identity beside a
**connection reference** — which names the connection record rather than a keyring
slot — and has the callable compare the identity *currently* recorded there. That
keeps ADR-0125 §4's rotation case working exactly as it was ratified to (same
account, new token, same identity, call proceeds) while refusing the substitution.
This is the same lesson as the first defect one level down: a name that resolves
to the right thing today is not a binding to that thing. The round-10 repair below
is the last step of the same argument — once the slot moves per act, a binding
that named a slot would have been a binding to the wrong kind of thing again.

**A check and a read are two moments, and the third draft left a window between
them.** `Secrets.get` is `async` — ADR-0125 §1 makes every method on both faces
so, because a locked keyring prompts the owner — and "the system composes on one
event loop" (`CONTRIBUTING.md`) is precisely the setting in which an `await`
between a check and a use is an interleaving point. Adversarial review found on
round 3 that a callable could verify identity A, suspend, have the slot
re-provisioned as B, resume and send under B's token. **The corpus has ratified
the answer to this exact shape**: ADR-0097 §5a requires that "no `await` may occur
between the `live()` result a driver gates on and its call to `Reader.read()`",
that the driver "re-checks the grant when `read()` returns" and discards the
reading if it has gone, and that it "fails closed on an unanswerable check". The
clauses above are that rule transposed onto the credential, with the last stating
the residue in §5a's own honest form rather than claiming the window is gone.

**The provisioning clause asks for an order, not a transaction, and an earlier
draft asked for the transaction.** That draft required the credential, the
identity and the revision to be "written together" with "no state observable in
which they disagree". Adversarial found on round 6 that nothing can provide it:
the credential lives in the OS keyring behind ADR-0125's seam, which stores one
value per `SecretName` and offers no transaction, and the connection record lives
in a store beside it. The finding's direction was a further contract ADR for a
transactional provisioning abstraction; that is not needed, because the property
the checks actually require is weaker and is bought without one. Write the
record first and the window is one in which the record is **ahead** of the
keyring — identity B or revision r+1 recorded while the keyring still holds A's
token — which is a state a check can be given something to see. Write the
credential first and the window has the keyring ahead of the record, which is
precisely the state no check here can see at all: it reads A and passes while
`get` returns B's token. So the order is necessary, and the reverse order is a
defect nothing below repairs. It is not on its own sufficient, which is what round
7 found next.

**This is ADR-0037 §2's argument on a different pair.** There, "recording precedes
the claim" because "an audit trail with an entry for an action that did not happen
is strictly better than an action with no entry" — order the two writes so the
crash window errs in the direction the reader can detect. Here a connection record
describing a credential that is not yet in the keyring is strictly better than a
credential in the keyring that no record describes, and for the same reason: the
first is visible to a check and the second is not. The earlier draft's own prose
had already identified the direction — it said a provisioning act "that wrote the
token and then the identity would leave an observable state in which a re-check
reads the old identity beside the new token" — while the clause beside it asked
for atomicity, which is both stronger than needed and unobtainable. Naming the
order is the repair for the direction it names; it is not the whole of the repair.

**The order alone was not enough, and round 7 found its mirror.** Ordering the
writes refuses a call bound to the *old* identity: the record names B, the binding
names A, the pre-read check compares the two and refuses. It does nothing for a
call built *inside* that window, which is bound to B by the record it has just
read — its pre-check sees `(B, r+1)`, `Secrets.get` returns A's token because the
credential write has not landed, its post-check sees `(B, r+1)` again, both checks
pass, and the bytes go out under A's credential while every record says B. The
checks compare the record against the binding and the record against itself;
neither inspects the credential's own account, and neither can, because a
credential is opaque and asking the service whose it is would be an egress call of
its own (§5). So record-first is not safe alone and credential-first is not safe
alone — each closes one direction and opens the other — and what was missing is
not a better order but a **third state**. Marking the record *pending* until the
credential write lands makes the half-finished state say what it is rather than
impersonate a finished one, and a state that says what it is can be refused by a
check that never has to guess. That is the revision's move one level up: the
revision makes "unchanged since I looked" answerable and the pending state makes
"finished" answerable, each replacing an inference with a recorded fact. It also
costs no transaction, which is what round 6 had asked for and what nothing
available can provide.

**Two provisioning acts are a third interleaving, and round 8 found that the state
alone does not order them.** Nothing above stopped a second act beginning on a
reference a first had left *pending*: act B writes pending `(B, r1)` and pauses,
act C writes pending `(C, r2)`, writes C's credential and activates, and B then
writes B's credential into the same slot — leaving an *active* record naming C over
a keyring holding B's token, which every check passes. The connection record is the
only store here that can arbitrate, so it does: an act begins by a compare-and-swap
on it and re-checks it before each of its two remaining writes. That gives a
pending record two jobs at once — it is the state a call refuses on, and it is the
token an act holds — which is why the ordering rule and the state come out as one
mechanism rather than two. C's takeover is what turns B's resume into an
abandonment, and taking over is deliberately **permitted** rather than forbidden,
because forbidding it would strand a reference left pending by an act that died,
while the remedy this section names is to run the provisioning act again.

**A sliver survived that, and round 10 is why it is closed here rather than
named and deferred.** If B's `Secrets.set` is already in flight when C activates,
no re-check either of them can perform sees it: the write lands in a store that
cannot refuse it and cannot be asked what it now holds. An earlier draft stated
that as an accepted residue and routed the mechanism that closes it — a credential
slot **per provisioning act**, with the record resolving the stable reference to
the current slot — to the ADR that decides the provisioning surface. Adversarial
found on round 10 that the residue is not one this ADR is entitled to accept: it
leaves an *active* record naming C over a keyring holding B's token, reached
through a **conforming** path rather than by an operator writing to the keyring
directly, and a call bound to C then passes every check and sends as B. That
contradicts this section's own guarantee clause in terms. A document whose
guarantee and whose residue disagree has not decided anything, and the honest
repair is not a softer guarantee — it is the mechanism.

**Per-act slots cost nothing this section was relying on, which is what makes
them the right size of answer.** The reference in the binding stays stable, so
ADR-0125 §4's rotation case survives exactly as it was ratified — a parked
`CONFIRM` is still answerable after a rotation, because what the binding names is
the record and not the slot. Nothing is asked of the keyring that ADR-0125 §4
declines to provide: no compare-and-swap, no refusal, no transaction. The write
that decides which credential is live becomes the **activation** — one write, to
the one store the compare-and-swap above already governs — and a displaced act's
late `set` lands where nothing points. This is the standing shape for exactly this
problem: write the new thing somewhere of its own, then move the pointer, so that
the only ordering that matters happens inside a single store. It is also what
ADR-0037 §2's argument recommends one more time, since the crash window it leaves
is an unreferenced slot rather than a live credential nobody described.

**Not connectable is stated over the whole call, not only over the send, because
§1 is where a refusal is cheapest.** A pending reference could have been refused
at the seam alone and the bytes would still not leave — but the user would then be
asked to confirm a call that cannot be performed, which is exactly what §1's third
clause and ADR-0145's precedent refuse to do. Reading the state when the request
is built also makes the ordinary case legible: a connection half-provisioned by an
interrupted act shows up as a tool that cannot be called until provisioning is
re-run, rather than as a confirmation the user grants and a send that then fails.

**Comparing the identity alone was not enough, and the revision is what closes
it.** Adversarial found on round 4 that A → B → A defeats an identity comparison:
the read is issued while A is provisioned, B lands, `get` returns B's token, A is
provisioned again, and the re-check sees A and passes. That is the ABA problem,
and the window is not theoretical here — ADR-0125 §1 argues its own `async` on
exactly this ground, that "a *locked* store prompts the owner, so the call's
duration is bounded by a human rather than by I/O". A value that never repeats is
the standing answer to ABA, and this corpus already uses one: ADR-0014 §5's
compare-and-swap version, whose whole job is to make "unchanged since I looked"
answerable. The revision is that, scoped to one reference.

**The chain stops at the post-read check, and stopping there is a decision with
two ratified precedents behind it.** Adversarial asked on round 5 for a lease
covering the final check through the transport's first write, on the ground that a
provisioning act could land in between. It could — and the send that follows is
still the one that was authorised, because the credential in hand is the bound
identity's and was verified unchanged across its own read. Nothing about a later
provisioning act makes an already-authorised send wrong; treating it as though it
did would be requiring the system to abandon an act the user approved because the
user subsequently changed an unrelated setting.

**The requested mechanism is one the corpus examined and refused, with its
reason.** ADR-0097 §5a: "**A lease held across the read was considered and
refused** … Holding a source-scoped guard from the check until the read released
it would make a revocation either block or fail while a read is in flight — a
permission withdrawal waiting on the thing it is withdrawing." Held across a
*transport write* rather than a file read, on a system that "composes on one event
loop", it is worse: a re-provisioning would block for as long as a remote service
takes to answer. ADR-0102 §9 states the same boundary where a user reads it —
`revoke` "does not wait for, cancel, or report a read already in flight, and no
client may present a revocation as having stopped one" — and ADR-0097 §12 files
the linearising mechanism as a deferred item needing its own ADR and a new seam.
So the clause above states the boundary rather than closing it, which is the
posture ADR-0146 §7 takes for its own residual: name what is not detected, and do
not buy a bound from a mechanism that cannot carry it.

**A lock would not close it either, which is the part worth being plain about.**
The bytes reach the wire before the far end has acted on them, so there is always
an instant at which a provisioning act is concurrent with a disclosure already
committed. A mechanism that shrank the window while reading as though it had
removed it would be exactly the overclaim ADR-0102 §9 forbids a client from
making, relocated into an ADR.

**The revision is deliberately not part of the binding, and that asymmetry is the
decision.** Binding it would make every rotation invalidate every parked
confirmation — the user re-authorising a send because their token was refreshed,
which is the friction ADR-0021 §5 already worries about and which ADR-0125 §4
ratified `set`'s replace-in-place behaviour specifically to avoid. What must not
change across the ruling is *whose account this is*, and that is the identity. What
must not change across the *read* is anything at all, and that is the revision.

**What none of it closes, said rather than glossed.** The identity is recorded
when the account is connected and is not re-verified against the service on each
call; verifying it would be a remote lookup, which §5 makes an egress call of its
own and which would then need one per send. So a party that writes account B's
credential directly into the keyring under a slot recorded as account A defeats
the check. That party is the operator or the user, which is ADR-0021 §1's line
exactly — "a caller falsifying its own audit trail, not a policy subverting a
gate, and no producer can prevent it" — and stating it is better than a clause
that reads as though the account were attested.

**The endpoint moved into the binding for the same reason, and the earlier
draft's version of it was a bound with nothing behind it.** That draft required
the endpoint to be "recorded beside the canonical destination set" and to not
change between ruling and transmission — while leaving it outside the request, so
nothing compared it and no refusal could fire. §1's own argument condemns it:
what is placed in the request is bound end to end, and "everything placed in it
afterwards is bound by nothing at all". Adversarial review found it on round 1.
Stating an immutability nothing enforces is precisely what ADR-0098 §3 records
itself doing twice and what §13 below quotes against a different clause; a
document that cites that lesson and then repeats it has learned nothing from it.

**Determinism is what lets the description be checked rather than merely
trusted.** The description is now bound directly, so nothing rests on deriving it
twice — but a description that is a function of the request and the registry's
definition alone is one the approver, the seam and a later auditor can each
re-derive and compare, which is what turns an inspectable record into a
verifiable one. It is also what stops the description becoming a second,
divergent account of the call: a builder free to consult a clock, a store or the
network could describe one payload and transmit another.

**Storing the description is a departure from ADR-0021 §1's posture, and it is
the right one here.** §1 stores the digest and none of the arguments, deliberately,
because "a durable record holding them verbatim would make the trail a second copy
of the user's most sensitive material". A description is not the arguments: it
states extent, provenance, tiers and destinations rather than content, which is
exactly the artifact that is safe to keep where the content is not. Without it an
auditor holds a digest and can verify a description they cannot see, which is the
failure #57's second comment names in one sentence — "a hash defeats the purpose".

**Excluding credential values is not a precaution here; it is already the
strongest available position.** ADR-0029 §6 rules that "no credential value
crosses this seam, in either direction, ever", ADR-0021 §1 forbids a Tier 0 value
in `parameters`, and ADR-0125 §8 gives the tool its own `Secrets` face by
injection. So there is nothing for a digest to be taken over and nothing for a
record to inherit, and #93 item 1's failure — "the binding artifact and every
audit record derived from it become Tier 0 stores, and a mechanism meant to make
disclosure reviewable puts secrets in the review trail" — is closed by
construction rather than by rule. The clause is written anyway because §11 adds a
record that did not exist when those rules were made, and a new record is exactly
where an old exclusion gets forgotten.

### 7. Credential access is gated by position, and a denial reads nothing and sends nothing

> **Normative.** An `INTEGRATION`-scoped credential (ADR-0125 §2, §8) is read only
> from inside a callable reached by `ToolInvoker.invoke` on a `ToolCall`, and only
> after ADR-0029 §2's three seam checks have passed. No component reads one
> **outside that position**: not to decide whether it may be read, not to construct
> a client for a call not yet ruled on, not to canonicalise a destination (§2), not
> to resolve one while a request is being built (§5), not to build a payload
> description (§6), and on no path a refusal can reach.

> **Normative.** A **resolution call's own callable is inside that position**, not
> an exception to it. §5 makes a resolution a call ruled on like any other, so its
> credential read is a read from inside a callable whose own `ToolCall` passed the
> three checks, and an authenticated resolver conforms by being invoked rather than
> by being exempted. What the clause above forbids is reading a credential to
> resolve a destination for **another** request — one still being built and not yet
> ruled on — which is the ungated lookup §2's no-I/O clause and §5's one-route
> clause each refuse from their own side.

> **Normative.** The decision that authorises an egress call **is** the gate on
> the credential read that call performs, and is the record ADR-0004 §7 requires
> for that access. No second decision is sought and no second audit record is
> written for the read itself.

> **Normative.** §6's discard clause is not an exception to the clause above.
> That clause governs a call that was **refused** — a `DENY`, which constructs no
> `ToolCall` and reaches no callable, so nothing is read. §6's discard governs a
> call that was **authorised** and whose account changed under it after the read,
> where the credential is in hand and the rule is that it is not used.

> **Normative.** This settles #74 for `tools/` and for nothing else. `models/`'s
> ungated provider-credential read is pre-existing debt (ADR-0017 §2, ADR-0125
> §8's last clause), is untouched, and no lane cites this ADR toward keeping it or
> toward closing it.

> **Normative.** No lane adds a path to an `INTEGRATION`-scoped credential outside
> the `Secrets` face ADR-0125 §8 injects, and this ADR adds none.

**Gating by position rather than by a second check is what actually closes #74's
attack, and a second check would not.** #74's comment describes an implementation
that "could read an integration's OAuth token from `SecretStore`, *then* run the
per-call permission check and stop when denied — satisfying every other
precondition while having already accessed Tier 0 data ungated." A rule saying
"check before you read" is a rule an implementation can satisfy at one site and
miss one file over, which is the failure ADR-0029 §2 refused to accept for
`authorises` and answered by making the unauthorised value unconstructable. The
same answer is available here for free: **a `DENY` produces no `ToolCall`**
(ADR-0029 §2), so no callable runs, so nothing on the far side of `invoke` reads
anything. The property "a denial performs no credential read and no network I/O"
— ADR-0017 §3's first failure-path test and #93 item 6's first row — is then a
consequence of where the read is, not a rule anyone has to remember.

**The second clause is the substantive answer to #74's question and it is worth
stating what it does and does not claim.** #74 asks whether ADR-0004 §7's "access
to Tier 0 data" bites per call on a credential the user configured, and observes
that "the same question lands on `tools/` the moment invocation exists, and there
the stakes are higher". The answer for `tools/` is: **yes, it bites, and it is
already paid.** §7 requires the access to be gated by `permissions/` and recorded
in an audit trail; it does not require a decision *per access event*, and a
decision that authorises this call to this destination set — taken before the
read, recorded before the claim (ADR-0037 §2), read back before the call
(ADR-0037 §3) — is a gate on the read in §7's own terms, recorded in §7's own
store. What is refused is the other reading, under which a per-read decision would
be sought: that would double every trail entry with a record whose subject nobody
can rule on differently, since a policy asked "may this call read the credential
it needs to make the call you just authorised" has exactly one honest answer.

**ADR-0125 §9 is where this lands, and it lands without moving a signature.** That
section states that a gating implementation "is an object that implements
`Secrets`, consults `permissions/` and delegates to the concrete store", that if
#74 rules a read is a permission subject "the gate arrives as a decorator at the
composition root and **no signature in `core/protocols.py` changes**", and that if
it rules otherwise "nothing is built and nothing is left dangling." This ADR takes
the second branch for `tools/` on the narrow question of a *separate* decision,
and the first on the question of whether the read is gated at all — the gate
exists, and it is positional rather than decorative. A lane that later wants the
decorator as belt-and-braces may build one; it satisfies no clause of this ADR
that is not already satisfied, and it may not be cited as satisfying one.

### 8. The approver, the two refusals a policy owes, and what the user is shown

> **Normative.** The authority to refuse an egress call is `ActionPolicy`, in
> `permissions/` (ADR-0021 §3). The named approver whose refusal it must be able
> to carry is **the user**, reached by a `CONFIRM` that parks the step
> (ADR-0037 §4) and answered through an interface, never by the turn on the
> user's behalf.

> **Normative.** A tool registered at the seam that transmits declares a
> **non-empty `discloses`**, so ADR-0021 §5's floor applies to every egress call
> and no egress call is auto-granted.

> **Normative.** Two refusals every conforming policy makes on an egress request,
> as floors in ADR-0021 §5's sense: it does not return `ALLOW` where any member of
> the canonical destination set is uncovered under §3; and it does not return
> `ALLOW` where the request carries no canonical destination set, no payload
> description, or a description that is not the deterministic derivation §6
> requires for that request's own arguments. A policy may be stricter; it may not
> be more permissive than these.

> **Normative.** What is put to the user for a `CONFIRM` on an egress call names
> the connected account's **identity** (§6), the canonical destination set in both
> forms (§2), and the payload description (§6). It names neither the connection
> reference nor a credential slot: neither is something a user can recognise an
> account by. A confirmation that names the tool and not the
> recipients is not a confirmation of an egress call.

**ADR-0017 §3 asks for "a named approver able to refuse" and gives the reason:
"An inspectable record makes an overbroad send visible, not refusable."** It also
scopes the question — "Which combinations `permissions/` refuses is its ADR's to
write; that the decision exists and can say no is required here." This *is* that
ADR, so it writes the two combinations that are not matters of taste. They are
deliberately the same shape as ADR-0021 §5's existing floors — a floor is what a
conformance suite can check "on any implementation without knowing its rules" —
and they are deliberately only two, because §5's own closing paragraph is right
that "choosing the thresholds between them is the default policy's job, not the
contract's".

**The non-empty `discloses` clause is a small rule that carries the whole approver
argument.** ADR-0021 §5's floor is stated over a non-empty `discloses`, "any tier,
not merely `SECRET` or `PERSONAL`", and forbids `ALLOW` with `authorised_by`
unset. Requiring a transmitting tool to declare one makes that floor bite on every
egress call, which is what makes the user the approver rather than a policy
setting. It also removes an evasion that would otherwise be available and
undetectable: a tool that transmits while declaring `discloses=()` would clear
§5's floor and reach `ALLOW` with no user in the loop, and nothing in ADR-0016
detects a declaration that understates. The cost is the one ADR-0021 §5 already
accepted in writing — over-prompting, "the safe direction" — and its relief valve
is §3's limb (b), not a weaker floor.

**The fourth clause is where ADR-0146 §5 is cashed.** ADR-0146 argues that "the
decision that remains is the user's, taken against a truthful description", that
"only the user can tell whether their own paste contained a key", and that
ADR-0017 §3's approver "is the surface where that is decidable, and a description
saying *your words, to this recipient* puts the question where it can be answered."
That sentence is an obligation on this ADR and this is the clause discharging it.
It is stated over what the *confirmation* contains rather than over what a user
understands, because the second is not obtainable — the discipline ADR-0098 §3
records learning twice.

### 9. Every egress attempt is a claimed step, and the four outcomes are the step's

> **Normative.** Every transmission through the seam happens under a committed
> `→ RUNNING` claim on a plan step whose `approval_ref` is the authorising
> decision's id (ADR-0014 §4, ADR-0029 §8). The **attempt identifier** ADR-0017
> §3 requires is that step execution. There is no egress outside a claimed step.

> **Normative.** `PermissionDecision.step_id` is set on every egress decision, so
> the trail's record and the plan record resolve to each other in both directions.

> **Normative.** The four outcomes ADR-0017 §3 requires are the step's and no
> others: **pending** is the durable `RUNNING` claim, and **succeeded**,
> **failed** and **indeterminate** are ADR-0029 §3's `SUCCEEDED`, `FAILED` and
> `INDETERMINATE` as ADR-0029 §8 maps them. No egress attempt records an outcome
> outside these four, and none is inferred from the absence of a record.

> **Normative.** The reconciliation path for an attempt left pending by a crash is
> ADR-0014 §4's recovery scan, which finds a durable `RUNNING` and records
> `INDETERMINATE`. A designated seam adds no reconciliation path of its own,
> relaxes none of ADR-0014 §4's treatment of `INDETERMINATE`, and never resolves a
> pending attempt by guessing.

**This condition is discharged by joining two ratified records rather than by
adding a third, and the join is already mandatory.** ADR-0017 §3 asks for "an
attempt identifier and an explicit outcome — pending, succeeded, failed,
indeterminate — with a path for reconciling records left pending by a crash.
Otherwise a timeout is indistinguishable from a successful disclosure." Every
element of that already exists and none of it is in the audit trail: the trail is
append-only and write-once with no `update` (ADR-0021 §4), so an outcome that
moves from pending to succeeded **cannot** live there, and an implementation that
tried would be rewriting an audit record. The plan store is where a state moves,
under compare-and-swap (ADR-0014 §5), and it already holds exactly the four states
asked for, already refuses `→ RUNNING` without an `approval_ref`, and already has
the crash path — "recovery finds a durable `RUNNING` and records `INDETERMINATE`"
(ADR-0029 §4, quoting ADR-0014 §4).

**What this ADR adds is only that the two records must point at each other, and
that there is no egress outside the join.** ADR-0029 §8 already requires
`approval_ref == call.decision.id`; the second clause supplies the other
direction, because `PermissionDecision.step_id` is `Identifier | None` and a
decision with none has an attempt nobody can find. With both, an auditor holding a
trail entry can find the attempt and its outcome, and an auditor holding an
`INDETERMINATE` step can find what was authorised — which is the question
ADR-0017 §3's condition exists to make answerable.

**The no-egress-outside-a-claimed-step clause is the load-bearing one, and it is
worth being honest about what it does not close.** ADR-0037 §3 records that
`StepExecutor` "is exported and takes any valid `ToolCall`", so a caller that
hand-builds an `ALLOW` decision can construct a call and have its id committed;
that is issue #259 and this ADR does not close it. What the clause does is make an
egress transmission with no attempt record a **rule violation** rather than an
unremarked possibility, so the designating ADR has something to attest and the
implementing lane has something to test. ADR-0021 §1 already ruled on this shape:
"a caller falsifying its own audit trail, not a policy subverting a gate, and no
producer can prevent it."

### 10. What this ADR gives a mechanism to, and what it leaves — ADR-0017 §3, condition by condition

This section is a classification of the change being made and is not normative
(ADR-0089 §1). §3's conditions are listed in its own order.

| # | ADR-0017 §3 condition | This ADR |
|---|---|---|
| 1 | A named seam and an import-linter contract pinning it (#66) | **Leaves.** ADR-0147 §3 supplies the name; the contract is code and attesting it is a statement about the tree, reserved by ADR-0017 §2 to the designating ADR. |
| 2 | Per-call gating that runs before transmission | **Mechanism.** §1's first two clauses and §7's first: the only route to the seam is `invoke` on a `ToolCall`, which a `DENY` cannot construct. |
| 3 | Recipient authorisation tracing to a user decision or standing user policy, bound to the resolved destination (#68) | **Mechanism.** §3, with limb (b) written and closed until ADR-0021 §6's successor opens it. |
| 4 | Credential access gated, not just transmission (#74) | **Mechanism.** §7, for `tools/` only. `models/` is untouched debt. |
| 5 | Transport pinned to the connected service; redirects (#83) | **Leaves the pin; binds the endpoint.** §6 puts the endpoint in the binding, so a change between ruling and transmission is refused by the callable. What the endpoint must *be*, and what a redirect may do, is #83's (§13). |
| 6 | The payload bound before transmission and described inspectably after it (#57) | **Mechanism for the authorisation-time face** — §6's binding, determinism, provenance and no-tier clauses, and §8's fourth. The artifact's granularity stays #57's (§13). |
| 7 | A named approver able to refuse | **Mechanism.** §8, including the two floors and the universal `CONFIRM` that ADR-0021 §5's floor produces. |
| 8 | What is transmitted bound to what was authorised, immutably, credential values excluded | **Mechanism.** §6: the decision by id, and the other three facts as one egress binding compared by `authorises` and transcribed into the record. Needs surface (a) of §11. |
| 9 | Multi-recipient calls authorised as one set | **Mechanism.** §4. |
| 10 | Destinations canonicalised per protocol, exact where equivalence unproven, both forms audited | **Mechanism.** §2. |
| 11 | Name-to-identifier resolution is a gated audited call, or forbidden | **Mechanism.** §5, taking the first branch and saying why the second is not the conservative one. |
| 12 | Attempt identifier, explicit outcome, crash reconciliation | **Mechanism.** §9, by joining ADR-0021 §4's trail to ADR-0014's plan record. |
| 13 | Outbound payload classification settled (#94) | **Consumes.** Settled by ADR-0146; §6 and §8 consume it and attest nothing. |
| 14 | Failure paths tested, not just the happy path | **Fixes the matrix, leaves the tests.** §14's clause binds the implementing lane to ADR-0017 §3's own list and to the rows this ADR adds; the tests are code and are that lane's. |

Nine mechanisms, one consumption, one matrix, three left — and none of the three
is left because it is hard. Condition 1 and condition 14 are statements about code
that a prose ADR cannot truthfully make, condition 5's remainder wants an HTTP
client in hand, and condition 6's remainder is a real artifact #57 has open
questions about. **No condition is discharged by this ADR**, in ADR-0017 §2's
sense of the word: discharge is attestation that a property holds in code, and
supplying a mechanism is not that.

### 11. New `core` contract surface this decision requires, flagged and not landed here

> **Normative.** This decision cannot be implemented without contract surface that
> `core` does not have. Two things are needed, both flagged here under golden rule
> 5 and neither added by this ADR: **(a)** the **egress binding** of §6 — a value
> carried as a field of `ActionRequest`, compared by `PermissionDecision.
> authorises`, and transcribed verbatim into `PermissionDecision` by
> `from_request`; and **(b)** a seam by which that binding is obtained from
> `tools/` before `ActionPolicy.decide` is reached.

> **Normative.** Each is decided in a contract ADR of its own, ratified and merged
> before anything implements against it (golden rule 5, ADR-0015 §5), and the
> triad then rides with the primary production implementation as one lane
> (ADR-0137 §2). No lane adds either surface on the strength of this ADR alone.

> **Normative.** Whatever shape either takes, no credential value appears in it
> (§6's fifth clause), and the description it carries states provenance and no
> tier for a user-authored free-text span (ADR-0146 §5, §6).

> **Normative.** Neither surface is the **provisioning act's owner**, and this ADR
> gives no component a keyring face. Who holds an `INTEGRATION`-scoped
> `SecretStore` (ADR-0125 §1, §2) to perform §6's credential write and its
> predecessor deletion, and where a connection record lives, are ADR-0125 §12's
> undecided provisioning surface and are not decided here (§13). No lane reads §6
> as authorising a component to hold a face ADR-0125 §8 does not give it, and no
> lane implements a provisioning act before the ADR that names its owner has
> merged.

**(a) cannot be avoided, and it is worth saying exactly why, because an earlier
draft of §6 tried three cheaper routes and each failed.** The binding cannot ride
in `parameters`: `ActionRequest` is `extra="forbid"` and ADR-0145 validates
`parameters` against the tool's declared `parameters_schema`, so an account
reference or an endpoint placed among the arguments is refused at construction and
a canonical form placed *over* the supplied one destroys the second form §2
requires. It cannot ride on the registry, because a definition carries no account
and the registry is rebuilt each run (§6). And it cannot be left derived-but-unstored,
because ADR-0021 §1 stores the digest and none of the arguments, so an auditor
would hold a hash of a description nobody can read — "a hash defeats the purpose"
(#57's second comment). So the value is a field, and being a field of
`ActionRequest` is what makes `authorises` able to compare it, which is what makes
every immutability clause in §4 and §6 enforced rather than exhorted.

**What (a)'s own ADR still has to choose.** Whether the binding is one nested
model or several fields; whether the payload description inside it is that ADR's
or a projection of #57's richer artifact; how `authorises` expresses the new
conjunct; and how ADR-0004 §6's deletion rules reach a description that names
memory records, which #57 already carries as an open question. Those want a
producer in hand — ADR-0073 §4's standing test, applied here for the reason
ADR-0146 §8 and ADR-0125 §9 each applied it — and nothing at this seam transmits,
so there is no producer.

**(b) is forced by §1's earliness, and it is the surface a reader is most likely
to miss.** ADR-0037 §2 has `StepRunner`, in `orchestration`, build the
`ActionRequest` from "the tool, the step's parameters and the step id". Under §1
that request must already carry the whole binding, every part of which is
integration-specific knowledge living in `tools/` — which `orchestration` may
reach only through a Protocol (golden rule 1). Neither `ToolRegistry` nor
`ToolInvoker` answers that question, and ADR-0029 §1 is explicit that how the
callable is reached "is `tools/`-internal, and this ADR does not contract it". So
a seam is genuinely missing, and the shape it wants depends on what a real
integration's canonicaliser and description-builder need — again a producer
question.

**What is fixed here rather than deferred is every property either surface must
have**, which is what keeps this from being a deferral wearing a decision's
clothes: (b) is consulted **before** the ruling and never after; it performs no
I/O (§2's fifth clause), so it cannot become the resolution path §5 governs; it
**refuses** rather than guessing (§1's third clause); its description is
deterministic (§6); and (a) is compared by `authorises`, is transcribed into the
recorded decision, holds no credential value, and states no tier for a
user-authored free-text span. A contract ADR that satisfies those is free to
choose the signature; one that does not is changing this decision.

**Note what is deliberately *not* on this list.** ADR-0146 §8 defers "the marker
that carries a span's discloser provenance to an egress boundary" and names its
trigger as "the lane that designates the `tools/` seam" — the lane with a
producer, a payload description and an approver. That marker is plausibly the same
surface as (a) or rides inside it, and this ADR neither merges them nor rules they
are distinct: it is the same lane's decision, made with the same producer in hand,
and prejudging it here would be exactly the guess ADR-0146 §8 declined.

**§6's determinism clause names the marker as one of its three inputs, and that
is what keeps this from being a ruling on the marker's shape.** The clause forbids
a clock, a store read or a network call, so that two derivations agree and an
auditor can re-derive one; it does **not** rule that provenance is recoverable
from an argument's value, which would be ADR-0146 §2's forbidden inference
arriving late, and it does not rule that the marker rides inside `parameters`. An
earlier draft listed only two inputs and was incoherent for it — adversarial found
on round 13 that two calls identical in arguments and definition, differing only
in whether the user typed a span or the system selected it, would owe different
descriptions from identical inputs. The repair is to admit the carried provenance
as an input rather than to weaken either clause. What stays ADR-0146 §8's is
**where it rides and what type it is**; what this ADR fixes is that it is carried
rather than inferred, that it is in the request before the ruling, and that the
description is a function of it. Architecture review read the earlier clause as
prejudging the marker, which is the reading this paragraph exists to close.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, and it is made here.
Its test is whether a reader holding only the earlier ADR "would now act
differently, or read one of its clauses more widely than it now holds". Where the
answer is no, "no record is owed against it at all, on `Status` or in a note", and
the change "is recorded in the ADR that makes it, **and nowhere else**". ADR-0146
§10 and ADR-0147 §11 are the worked precedents for this section's form.

**ADR-0017 §2 and §3 — no record owed, and this is the one that needs the
argument.** §3 reserves these mechanisms to "the invocation and `permissions/`
ADRs" and says they "may satisfy any of them however they judge best". Supplying a
mechanism is that sentence working, which is the shape ADR-0147 §11 found for §2's
seam-naming and ADR-0146 §10 for §3's classification condition: "The condition is
not made false or over-wide by being answered." A lane holding only ADR-0017 still
finds fourteen conditions, still finds none discharged, and still needs the later
ADR §2 requires. §10 above says so in terms, and this ADR attests nothing about
code. What would have owed a record and is deliberately not done: attesting that
any condition holds, or naming the seam module — the first is reserved by §2 to
the designating ADR and the second was ADR-0147's.

**ADR-0021 §5 and §6 — no record owed.** §6 defers recipient authorisation and
names its own trigger — it "needs resolved destinations, which need arguments
interpreted per tool, which needs invocation". Invocation landed in ADR-0029, so
taking the deferral up is "that deferral working as designed, not a supersession"
(ADR-0029 §9), and §6's bullet remains a true record of what was deferred and
when it would fire. §5's floors are relied on exactly as written and §8 above adds
two beside them rather than relaxing either; §8's `discloses` clause makes §5's
existing floor bite more often, which is a rule about tool declarations at one
seam and changes no sentence of §5. §6's **standing grants** bullet is untouched:
§3's third clause states that limb (b) is unavailable until that ADR lands and
that nothing here pre-shapes it, so a reader holding only ADR-0021 §6 finds the
same deferral, with the same relief-valve role, and acts identically.

**ADR-0021 §1 — a record *is* owed, and it is written.** The clause is §1's
"**the decision binds the payload and holds none of it**". §6 above fixes the
egress binding in the `ActionRequest` before the ruling and has it **transcribed
verbatim into the recorded decision**, and that binding carries the supplied form
of every destination — an argument value, and "a recipient" is one of the three
examples §1 gives of what it declines to store. A reader holding only ADR-0021 §1
therefore reads that sentence more widely than it now holds, which is ADR-0070
§1's test coming out **yes**, so under ADR-0082 §1 the record goes on ADR-0021's
`Status` line and in an appended dated note at the end of its §1. It is an
**amendment** and not a supersession: `parameters_digest` stands, `parameters`
store nothing and still admit no Tier 0 value, and what §1 decided about *the
arguments* is untouched — the sentence is over-wide rather than replaced.

**An earlier draft of this section cleared that clause, and the argument it used
is worth recording as wrong.** It reasoned that §11 routes the surface to a
contract ADR of its own, that "this ADR adds none of it", and that the record is
therefore owed by the ADR that makes the change rather than by the one saying a
change will be needed. Architecture review found the flaw: ADR-0082 §1 applies
ADR-0070 §1's test "to the earlier ADR's **text**", not to a tree, and the
substance is decided *here* — §6's transcription clause is marked and normative on
ratification, while §11 defers only the surface's **shape**. The later contract
ADR will choose fields; it will not choose whether the recorded decision holds a
destination form, because this ADR already has. ADR-0044 is the worked precedent
in the other direction: its note sits on ADR-0021 §1 from the day ADR-0044 merged,
ahead of the implementation that followed it. Nor is the storage avoidable by
redesign, which is what makes this an amendment rather than a preference:
ADR-0017 §3's tenth condition and §2's fourth clause above each require **both**
the supplied and the canonical form to reach the audit record.

**ADR-0021 §4 — no record owed.** Its append-only, write-once rule is not merely
preserved but is §9's whole reason for putting the attempt's outcome in the plan
record rather than in the trail.

**ADR-0029 §1, §2, §5, §6 and §8 — no record owed.** The biconditional, the three
seam checks and their order, the derived idempotency key, the credential rule and
the executor's `approval_ref` obligation are all consumed as written. §6 above
adds constraints on what a *request* carries, which ADR-0029 §2 already
re-verifies without change, and §9 above adds that `step_id` is set for an egress
decision, which is a rule about a field ADR-0021 §1 already declares optional and
does not alter the field. ADR-0029 §7's scope-out — "Designating the `tools/`
egress seam … This contract is a precondition for that ADR, not a substitute for
it" — is true of this ADR in exactly the same words, and §13 says so.

**ADR-0037 §2 and §3 — no record owed, and §3 is the near miss worth showing.**
The order and the read-back are relied on; §1's earliness sits inside step 1 of
§2's five-step sequence ("build the `ActionRequest`"), which §2 already places
before `decide`. Nothing is added to `StepRunner`'s sequence and nothing is
reordered. §3 is where the ADR-0021 §1 amendment above could plausibly have
reached a second clause, since it is the section that says what the trail must
return — and it clears on its own sentence: the equality check "is total over the
fields, **so a field added to `PermissionDecision` later is covered without anyone
remembering to extend a list**". A clause that provided for this addition in
advance is not made false or over-wide by it; §3's guarantee is unchanged and
strictly cheaper to keep than a field list would have been.

**ADR-0014 §4 and §5 — no record owed.** §9 above reads the transition table and
the recovery scan and applies them; §6 above takes §5's compare-and-swap as a
*pattern* and applies it to a different store, which adds nothing to the plan
record and leaves §5's own version, its holder and its conflict behaviour exactly
as ratified. No legal move is added or removed, and no
trigger column becomes wrong — ADR-0029 §9 already recorded the second trigger for
`RUNNING → INDETERMINATE` as a note on ADR-0014, and this ADR adds no third.

**ADR-0125 §2 and §4 — no record owed.** §2's `SecretName` is used for what it
is, and §6 above adds a second one per provisioning act rather than changing what
one means. §4's replace-in-place rule is neither relied on for the account case
nor contradicted by declining to rely on it: `set` still creates or replaces and
still never refuses, and a reader holding only §4 finds the same behaviour and the
same rotation argument. What §6 does with §4 is stop *depending* on a replacement
being safe, which §4 never claimed — its own sentence is about what `set` does,
not about what a caller may conclude from it.

**ADR-0125 §8 and §9 — no record owed.** §9 there states the seam "does not gate"
and is "shaped so that #74 can land into it", and names both branches the answer
could take. §7 above takes one of those branches for `tools/`; a deferral naming
its own landing shapes is not narrowed by something landing in one of them. §8's
clause that `tools/` holds `Secrets` "at the tool that needs one" is relied on
unchanged, and §7's fourth clause restates its no-second-path rule rather than
extending it. **§6's provisioning act adds no holder and no path either**, which is
the reading architecture review tested: the act needs a component holding an
`INTEGRATION`-scoped `SecretStore` to write its own slot and delete its
predecessor's, §8 gives that to nobody, and §12 there already records why — it
scopes out "a provisioning surface", saying in terms that nothing in that ADR
"mints a command that sets a provider key **or an integration credential**" and
naming `SecretStore` as the seam such a command would use. A reader holding only §8
therefore finds the same holders as before and finds no new one here: §6 fixes what
such an act must do **if one is performed**, §11's fourth clause refuses to name its
owner, and a lane that lands one takes up ADR-0125 §12's deferral rather than
reading §8 more widely.

**ADR-0146 §4, §5, §6 and §8 — no record owed.** §4's third clause says
authorisation is owed on every call at this seam and §4's fourth routes the
user-named-destination case to ADR-0017 §3's condition; §3 above is where both
land, which is the routing working. §6's recording obligation on "the lane that
designates the `tools/` seam" is carried into §6 and §8 above and is neither
widened nor narrowed — its `models/` exemption is untouched. §8's second clause,
which leaves open whether a standing policy may authorise forwarding
user-authored content to a third party, is honoured by §3's third and fourth
clauses rather than answered. §8's **first** deferral — the marker carrying a
span's provenance to an egress boundary — is honoured rather than spent: §6's
provenance clause is ADR-0146 §6's *requirement* being consumed, which §6's own
prose contemplates landing "on the payload description itself", and §11 above
declines to rule whether that marker and surface (a) are one. §6 requires the
provenance to be **carried** into the request rather than inferred, and names it
among the description's inputs; both are restatements of ADR-0146 §2 and §6 for
this seam, and neither chooses where it rides or what type it is, which is the
whole of what §8 deferred.

**ADR-0147 §3, §4 and §12 — no record owed.** §3's seam name is used. §4's fifth
clause binds "the ADR that authorises a stdio server"; this ADR is not that ADR
and §13 says so, so the obligation stays exactly where §4 put it and is neither
inherited nor discharged. §12's scope-out list names recipient authorisation,
credential-read gating, canonicalisation, multi-recipient sets and attempt
identifiers as "inherited unabridged and undischarged" — undischarged is what
they remain (§10).

**ADR-0098 §3 — no record owed.** Its actuator clause is applied: nothing here
lets external content select, parameterise or confirm an egress call, and §3
above refuses a destination this system extracted from a span it selected as an
authorisation. Its last clause is left unanswered on purpose, by the same reading
ADR-0147 §11 took — it is reserved to "the lane that designates an actuation
seam", and §3's fifth clause above routes it to the standing-grant ADR rather
than answering it.

**ADR-0004 §7 — no record owed, and this one deserves the sentence.** §7 requires
Tier 0 access to be gated by `permissions/` and recorded in an audit trail. §7
above supplies a gate and a record for the `tools/` credential read; it does not
exempt anything, does not narrow "access", and leaves #74's `models/` half exactly
where ADR-0017 §2 and ADR-0125 §8 left it. A reader holding only ADR-0004 §7 still
reads that the read must be gated and recorded, and finds it is. What such a reader
does **not** find in §7 is a requirement of one decision per access event, and §7
above says why the other reading is refused rather than assuming it away.

**ADR-0097 §7 and ADR-0133 — no record owed.** §7's two clauses are read forward
and applied, not narrowed: §3's fourth clause above restates the first for this
seam, and the second — that ADR-0021 §6's standing grants for actions "stay
deferred, with the precondition ADR-0021 §3 places on the ADR that introduces
them unspent" — is honoured, since §3's fifth clause above spends nothing and
names that precondition as the successor ADR's. A reader holding only ADR-0097
finds a grant that authorises "no tool call, no transmission … and nothing
outside the assistant" and acts identically. ADR-0133 is read for its per-use
granularity argument and is otherwise untouched; no `GrantScope` member is added,
implied or reinterpreted, and nothing here makes a source's grant reach an
egress recipient.

**ADR-0021 §3 — no record owed.** Its precondition on "the ADR that introduces
standing grants" is neither met nor spent here: §3's third clause above keeps
limb (b) closed, and its fifth restates the precondition with the addition that
what must be covered is the canonical destination set. Adding to what a later ADR
owes is ADR-0098 §3's form and is recorded here rather than on ADR-0021, exactly
as ADR-0147 §11 recorded its own stacked addition rather than writing it onto
ADR-0017.

**ADR-0124 §1 — no record owed.** Its enumeration is read and applied: the calls
this ADR governs are the second of its three boundaries, and nothing here widens
the set or cites §1 toward designating the seam, which its own marked clause
forbids.

**Exactly one ADR is amended and none is superseded**, so `docs/adr/0021-…md` is
the only file besides this one that this change touches: its `Status` line gains
the qualifier in the shape ADR-0082 §2 keeps permitted on a line with no leading
token, and its §1 gains an appended dated note. No accepted text is rewritten
anywhere, here or there (ADR-0070 §1). Under ADR-0082 §1 a
reviewer "may not demand a record, or its removal, on book-keeping grounds
alone", and may require one by "naming the sentence of the earlier ADR that does,
or does not, become false or over-wide" — which is the form a disagreement with
this section takes.

### 13. Explicitly out of scope

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's
form).

- **Designating the `tools/` egress seam.** ADR-0017 §2 requires a later ADR to
  name the module, attest each §3 condition **is satisfied in code**, and record
  the transition. Attestation is a statement about the tree, and a prose ADR
  proposing mechanisms nothing has implemented cannot truthfully make one. §10 is
  the inventory that ADR will work from; it is not the attestation. Saying it
  loudly is the point, because a document that supplies nine mechanisms reads like
  permission to transmit, and it is not: `tools/` still transmits nothing.
- **The ADR ADR-0147 §4 requires before an MCP server is connected to over a
  stdio transport.** This is not it, and the reason is structural rather than a
  matter of appetite: every mechanism above takes a destination the *arguments
  select*, and a subprocess is not selected by an argument. ADR-0147 §4 says the
  same in its own words — "recipient authorisation, destination canonicalisation,
  multi-recipient sets and transport pinning are all about a destination chosen at
  call time from arguments", so ADR-0017 §3's conditions "have no subject on a
  subprocess". What that ADR owes is what bounds a recipient this repository did
  not write, whose open input is containment (**#1112**), and specifying
  containment from a prose ADR would be the bound-with-no-mechanism-behind-it
  defect ADR-0098 §3 records itself making twice. ADR-0147 §4's fifth clause
  stands undischarged and this ADR adds nothing to it and relaxes none of it.
- **Transport pinning's implementation** — **#83**. What pins the endpoint to the
  connected service, and what a redirect may do, wants an HTTP client in hand: #83
  asks where the pin lives (per integration, beside the credential, or in the
  seam's client construction), whether same-host or same-suffix redirects must be
  allowed for real APIs, and what each provider SDK exposes. Those are answers to
  find with code, and §6 fixes the authorisation-time half — the endpoint is in
  the binding, appears beside the semantic destination in the record, and the
  callable refuses to connect to a different one — which is the half #83's own
  last bullet asks for.
- **The payload manifest artifact** — **#57**. §6 and §8 fix its authorisation-time
  face: deterministic, per-span provenance, no tier for user-authored free text,
  both destination forms, no credential value, and what a confirmation must name.
  Its granularity — record ids and field names against counts per tier — its
  interaction with ADR-0004 §6's deletion rules, and whether it is what
  `permissions/` approves or a projection of something richer are open questions
  #57 states in its own comments, and answering them wants a real integration's
  arguments to describe.
- **Standing grants** (ADR-0021 §6). They need "durable, per-user policy state
  with its own data-rights obligations — a store, not a field", and §3's fourth
  clause adds two questions that ADR must answer before an egress recipient may
  rest on one. Writing it here would be designing a store for a feature whose
  hardest question — what a standing authorisation means for a recipient a model
  chose — belongs with the lane that has both.
- **ADR-0098 §3's last clause**, whether a standing authorisation may cover an
  action a model selected while reading external content. Reserved by that clause
  to "the lane that designates an actuation seam", left open by ADR-0147 §11 in a
  marked clause, and routed by §3's fifth clause above to the standing-grant ADR.
  No lane reads this ADR's silence as an answer in either direction.
- **`models/`'s ungated credential read (#74) and unpinned endpoint (#83).** Both
  are pre-existing debt that ADR-0017 §2 named and deliberately did not gate,
  because "gating `models/` on them would prohibit every model call the product
  runs on, to close gaps that stay open if this ADR is rejected". Unchanged here.
- **The shape of the two `core` surfaces §11 names.** Each is a contract ADR of
  its own, decided with a producer in hand (ADR-0073 §4).
- **Who performs a provisioning act, and where a connection record lives.** §6
  fixes the act's *shape* — three writes in a fixed order, a compare-and-swap on
  the record, a slot per act — because that shape is precisely what the
  authorisation-time checks read, and an act performed any other way makes those
  checks unsound. It names no owner. ADR-0125 §12 already scopes out "a
  provisioning surface" for exactly this, in terms that reach an integration
  credential and not only a provider key, and granting any component a keyring face
  is that ADR's to do rather than this one's — §11's fourth clause says so
  normatively. The owner also wants the producer §11 defers for: what writes a
  connection record depends on where an integration is connected from, which is a
  question no component in the tree currently answers.
- **ADR-0004 §7's minimisation rule**, which stays scoped to the model provider
  exactly as ADR-0017 §9 and ADR-0146 §8 left it. §6's description is what makes
  minimisation *checkable* for a tool call; it does not extend §7's own sentence.
- **An injected transport capability** (#85, ADR-0017 §8). Deferred there with
  three reasons and not reopened; §1's single-route clause is the weaker,
  reviewable form of the same property, and ADR-0017 §4 is candid that an import
  contract "is a net, not a proof".
- **Retention of the audit trail** (#108) and richer audit queries (ADR-0021 §4).
  Unaffected, and a description that is stored is subject to whatever #108 rules.

### 14. What the implementing lanes owe

> **Normative.** The lane that implements these mechanisms ships the failure-path
> matrix ADR-0017 §3's last condition lists and #93 item 6 restates, plus a test
> for each of: a resolution refused or failed does not fall through to a send
> (§5); a canonicaliser performs no I/O (§2); a request whose destination set or
> description is absent draws no `ALLOW` (§8); a member added to the destination
> set after the ruling is refused by the seam rather than transmitted (§4); a tool
> registered at the seam declaring an empty `discloses` is refused at registration
> (§8); a transmission attempted outside a claimed step is refused (§9); a decision
> recorded while an id was bound to one connected account is refused after a
> restart that rebinds the same id, with a byte-identical declaration, to another
> (§6); the same for a transport endpoint that differs from the bound one (§6);
> and a connection reference **re-provisioned** for a different account
> between the ruling and the resume, which is refused, while a rotation of the
> same account's credential at that reference is not (ADR-0125 §4, §6). The
> rotation half asserts *which slot is read*: the parked approval resumes against
> the slot the record now names, not against any slot bound or read earlier, and
> an implementation that reads a slot carried in the binding fails it.

> **Normative.** That lane also ships two interleaving cases §6's one-step,
> revision and re-check clauses exist for: a re-provisioning landing **after** the
> check and during the credential read, and a deterministic **A → B → A** sequence
> across that read that restores the original identity. Both are caught, the
> credential is discarded, and no byte is transmitted. A test that reprovisions
> only between the ruling and the start of invocation satisfies neither, and one
> that compares the identity alone cannot pass the second.

> **Normative.** That lane also ships the interrupted-provisioning case in **both**
> directions, because closing one of them is what opened the other (§6). A
> provisioning act that writes the connection record and then fails before the
> credential is written leaves a call bound to the **old** identity refused rather
> than transmitted; and in that same interval a request bound to the **new**
> identity — record `(B, r+1)`, keyring still holding `A`'s credential — is refused
> when it is built and again at the seam, rather than transmitting `A`'s credential
> under `B`'s name. A provisioning implementation that writes the credential before
> the record fails its own test, and so does one that leaves the reference
> connectable between the record write and the credential write, or one that marks
> a record active without having performed that act's credential write.

> **Normative.** That lane also ships the **two-act** case: a second provisioning
> act beginning on a reference a first left *pending* takes the reference over, and
> the first, resuming afterwards, writes neither its credential nor its activation.
> A provisioning implementation whose act begins without a compare-and-swap on the
> connection record, or which writes its credential or activates without re-reading
> that record first, fails that test.

> **Normative.** That lane also ships the **late-`set`** case, which is the one the
> per-act slot exists for: a displaced act whose `Secrets.set` was already in
> flight completes that write *after* the displacing act has activated, and a call
> made afterwards still reads the displacing act's credential and transmits under
> the identity the record names. An implementation in which two provisioning acts
> can write one slot fails this test, and a test that exercises the interleaving
> without asserting which credential the following call reads does not satisfy it.

> **Normative.** That lane also ships the **omitted-span** case, and it covers
> **both** span kinds in one mixed payload: a payload carrying a described benign
> span, an undescribed **selected record**, *and* an undescribed **user-authored
> free-text argument** is refused — before the ruling where the request is built
> that way (§1's third clause), and at the seam where the callable would otherwise
> transmit it — rather than sent with a description and an audit record that
> account for some of its spans and not the others. The refusal is
> **deterministic**: the same request refuses on every derivation of its
> description. An implementation that tracks only one of the two span kinds fails
> this test, so a case carrying one omission alone does not satisfy it, and neither
> does a test that exercises only descriptions which happen to be complete.

> **Normative.** That lane also ships the **carried-provenance** pair, which is
> what §6's determinism clause names its second input for: two requests with
> byte-identical arguments and the same registry definition, differing only in the
> provenance the request carries for one span, produce **different** descriptions,
> each stating that request's own carried provenance. An implementation that
> decides a span's provenance by reading its value, its field or its shape derives
> one description for both and fails this pair — the inference ADR-0146 §2 forbids
> — and so does one that labels every covered span with a single provenance. A case
> built from one request alone distinguishes neither.

> **Normative.** That lane also ships the **alias** case, which is where the
> supplied form is easiest to lose: two calls whose destination-bearing arguments
> were supplied in different forms that canonicalise to one recipient produce
> descriptions and audit records each stating its **own** supplied form beside the
> shared canonical one (§2's fourth clause). An implementation that records only
> the canonical form fails this case, and so does one that reconstructs a supplied
> form from it.

> **Normative.** A test asserting only that the happy path transmits satisfies no
> clause of this section.

### 15. Marking, review and ratification

**Marked under ADR-0089**, so this ADR is in the marked regime: its unmarked prose
supplies no obligation and exists to determine what the marked clauses mean (§3
there). Marking is forward-only (§5), and nothing ratified before it is drawn into
the regime by it.

**The required set is adversarial *and* architecture.** This ADR decides a
contract surface in the sense `CONTRIBUTING.md` → "Stop when the required reviews
are green" gives — it is the ADR that authorises the `core` additions §11 names —
and it is run while the ADR stands `Proposed` so that a finding can still change
the decision. `CONTRIBUTING.md` → "Finishing an ADR PR" owns the sequence, this
section points at it rather than re-deriving it, and the outcome is recorded here
on ratification.

**Two findings changed the decision rather than its wording, and both are recorded
where they bit rather than only here.** Adversarial found on round 1 that §6's
first draft bound the **connected account** to nothing durable — the registry is
rebuilt each run and a definition carries no account, so a `CONFIRM` answered
after a restart could execute against a second account under a byte-identical
declaration — and that the **transport endpoint** was required not to move while
sitting outside the request, where nothing compares it. Both were bounds asserted
out of machinery that does not provide them, in a document whose §1 argues that
only what is in the request before the ruling is bound at all. Round 2 then found that the repair's account half bound a
**keyring slot** rather than an account, since ADR-0125 §4 lets `set` replace a
value in place for rotation; round 3 that the identity check and the credential
read are two `await`-separated moments with a window between them; and round 4
that comparing the identity across that window is defeated by an A → B → A
re-provisioning. Round 5's finding — a lease from the post-read check across the
transport's write — was **contested rather than folded**: §6 now states that
boundary as a decision, on ADR-0097 §5a's refusal of a lease and ADR-0102 §9's
in-flight rule, because the send that follows an already-passed check is the one
that was authorised and the requested mechanism is one the corpus examined and
declined. Round 6 found that the provisioning clause demanded a transaction across
the keyring and the connection record that no contract provides; its direction was
a further contract ADR, and the repair taken instead was an **ordering rule** —
record first, credential second — which buys the property the checks need with no
new surface, on ADR-0037 §2's argument that two writes are ordered so the crash
window errs in the direction a reader can detect. Round 7 then found that repair's
own mirror: ordering refuses a call bound to the *old* identity, and passes one
built inside the window and bound to the *new* one, whose checks see the new
record while the keyring still holds the old credential. The repair is a **third
provisioning state** — the record written *pending*, marked *active* only after
the credential write, and not connectable until it is — which makes the
half-finished state say what it is instead of impersonating a finished one, and
needs no transaction either. Round 8 found the third interleaving in the same
family — two *provisioning acts* on one reference rather than an act against a
call — and the repair keeps the arbitration in the one store that can offer it: an
act begins by a **compare-and-swap** on the connection record and re-reads it
before each of its two remaining writes, so a displaced act abandons instead of
writing a credential the record no longer describes. Round 10 then refused the
sliver that repair left — a `Secrets.set` already in flight when another act
activates — on the ground that it is reached by a **conforming** path and leaves
an active record over another account's token, contradicting this section's own
guarantee clause. The draft had named the mechanism that closes it and routed it
away; the repair is to take it: each act writes **its own credential slot** and
the record names the live one, so the write that decides which credential is live
is the activation, a single write to the store the compare-and-swap already
governs. The binding still carries the stable reference, so ADR-0125 §4's rotation
case is untouched.

**Round 8's second finding was assessed as resting on a misreading and was
answered by tightening a definition rather than a decision.** It read §1's refusal
of "a name that has not been resolved" as reaching the resolution call §5
requires, making that call unauthorisable. It does not: a resolution call's
arguments select no recipient beyond the service it is made to, so §2's third
clause already gives it a canonical destination set — the connected account — and
§5's prose already said so. What the finding did expose is that the term
**destination-bearing argument** did not say *whose* recipient it means, and a key
sent to a lookup service determines a recipient of a later call. The definition now
carries that scope. No clause changed.

**Architecture's first round changed §12, which is the section it was always most
likely to reach.** It found that §12 cleared ADR-0021 §1 wrongly: §6 has the
egress binding transcribed verbatim into the recorded decision, that binding
carries every destination's supplied form, and §1 names "a recipient" among the
argument values it declines to store — so "the decision binds the payload and
holds none of it" is over-wide, and the record is owed **here**, because ADR-0082
§1 applies its test to the earlier ADR's text rather than to a tree and §11 defers
only the surface's shape. The record is now written: a `Status` qualifier and a
dated note on ADR-0021, and the judgement declared in §12. Re-running §12's sweep
after that reversal found no second clause caught by the same test; the nearest
neighbour, ADR-0037 §3, clears on its own sentence that its equality check covers
"a field added to `PermissionDecision` later". The round's other finding — that
§6's provenance clause spends ADR-0146 §8's deferred marker — was assessed as
reaching a real ambiguity by the wrong route: ADR-0146 §6 states the requirement
and its own prose names the payload description as a place the mechanism may land,
so §6 consumes it rather than deciding it. What the finding did expose is that
§6's determinism clause could be read as ruling on where provenance comes from,
which would prejudge the marker. §11 now scopes it to a builder's inputs. The
finding's direction — remove the carriage, or make this the designating ADR — is
refused: the second is reserved by ADR-0017 §2 and disclaimed in this ADR's own
header, and the first would drop an obligation ADR-0146 §6 already binds.
§6 now carries the account's identity beside its connection reference, the
endpoint alongside both, the callable's four-way refusal behind all of them, and
ADR-0097 §5a's one-step/re-check/fail-closed discipline over the read, a
monotonic revision on the connection record so the re-check answers "unchanged"
rather than "equal", and a pending/active provisioning state — begun and held by a
compare-and-swap — so that "finished" is recorded rather than inferred, and a
credential slot per provisioning act so that two acts on one reference are ordered
by the one store that can order them and a late write lands where nothing points
— with each surviving residue stated in §5a's own honest form rather than papered
over. §11 states the
surface that costs, and §6's own prose says what each draft got wrong and why.
**That is the one worth remembering**: the defect is ADR-0147 §13's — stating a
hazard and then admitting the thing anyway — reproduced in a draft that quotes
ADR-0147 §13 approvingly, which is the best evidence available that the pull
toward it is a property of the subject rather than of any draft.

## Consequences

- **ADR-0017 §3's list stands at fourteen, none discharged.** Nine now have a
  ruled mechanism, one is consumed from ADR-0146, one has its test matrix fixed,
  and three are left with reasons (§10). Designation still needs the ADR §2
  requires, and `tools/` still transmits nothing.
- **The `permissions/` half of tool egress is decided, and most of it is joinery.**
  The decision's identity, the argument binding, the re-check at the seam, the
  read-back and the attempt record are all already ratified in ADR-0021, ADR-0029,
  ADR-0037 and ADR-0014. What is genuinely new is §1's constraint — every fact
  must be in the request before the ruling — and the value §6 needs to carry
  them, which is §11's surface (a).
- **Two `core` additions are authorised in principle and neither is landed**
  (§11). Each is its own contract ADR under golden rule 5 before its triad, and
  the triad then rides with its primary production implementation as one lane
  (ADR-0137 §2). A lane that starts the implementation before those merge is
  building against an unratified contract. Surface (a) touches `ActionRequest`,
  `PermissionDecision` and `authorises` — the most-consumed values in the
  pipeline — so it is a breaking change and its lane inherits the ADR-0082 §1
  record against ADR-0021 §1.
- **Every egress call reaches the user today.** §8's `discloses` clause plus
  ADR-0021 §5's floor plus §3's closed limb (b) means there is exactly one route
  to an `ALLOW`, and it runs through a `CONFIRM` the user answers. That is the
  correct default and the poor steady state ADR-0021 §6 already named; the relief
  valve is the standing-grant ADR, and §3's fifth clause makes it a valve with
  three questions attached rather than a switch.
- **An integration becomes more expensive to write**, and this is the honest cost.
  It registers one tool per connected account, declares its destination-bearing
  arguments, canonicalises through the seam's per-protocol canonicaliser rather
  than its own, resolves names as first-class gated calls, and produces a
  deterministic description of its own payload. ADR-0017 §4 chose that asymmetry
  deliberately — "a boundary that has never transmitted can be held to the
  standard we would want everywhere" — and this is what the standard costs when
  written out.
- **#68 and #74 have their tool-side answers and stay open for `models/`.** #68's
  three open questions — which authorisation form each integration uses, where the
  check runs, and how a destination is canonicalised — are answered by §3, §1 and
  §2 respectively. #74's tools-side question is answered by §7 and its `models/`
  half is untouched.
- **#57 and #83 are narrowed rather than closed**, each to the half that wants
  code in hand, and each keeps its issue.
- **Nothing here authorises a byte.** Ratification changes no behaviour: the seam
  remains approved and undesignated, and this ADR is a precondition for the ADR
  that designates it, not a substitute for it.
