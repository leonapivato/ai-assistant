# 17. Egress boundaries: `models/` is not the only one

- Status: Proposed
- Date: 2026-07-19
- Supersedes **on acceptance**: ADR-0004 §2's egress clause ("The **only**
  component permitted to send user data off-device is the `models/` layer…
  Every other egress is a bug"), as amended 2026-07-19. While this ADR is
  `Proposed`, that clause remains the live rule. The rest of ADR-0004 — §1 and
  §§3–7, and §2's residency and telemetry clauses — stands unchanged either
  way.

## Context

ADR-0004 §2 names `models/` as the *only* component permitted to send user data
off-device and calls "every other egress" a bug. That was written when `models/`
was the only subsystem in the repository with a reason to open a socket.

The rest of that same ADR already plans for a second. Its §3 has `tools/`
reading credentials for external services through `SecretStore`; its §7 gates
"every side-effecting tool call" — which for an integration layer overwhelmingly
means calling a remote service; and its Consequences provision for "the
designated `tools/` integration boundary" importing network clients alongside
`models/`. A tool layer that may hold a calendar token but may not reach the
calendar is not a design; it is a contradiction ADR-0004 has been carrying since
it was ratified.

Nothing violates the rule today: ADR-0016 ships no callable tool, so nothing
transmits anything. It becomes blocking when invocation lands, and ADR-0016 §7
records reconciling ADR-0004 §2 as a precondition on the invocation ADR — the
first tool that sends a byte must do so under a rule that permits it. This ADR
discharges that precondition ahead of the invocation contract, so that contract
inherits a settled rule rather than negotiating one.

This is the second time ADR-0004 §2's egress clause has needed widening. The
first (2026-07-19, the configured-set amendment) read "**the** model provider"
as the configured *set*, enabling ADR-0013 routing. That one explicitly declined
to touch the axis this ADR changes.

## Decision

### 1. The rule

**Outbound application-layer content may leave the device only from a boundary
this ADR authorises to transmit, and any such boundary must declare what it
transmits before it transmits. User data carries the further restriction that
its recipients are limited as §2 sets out per boundary.**

Two clauses, because they have different scopes. The **boundary and declaration**
requirement covers everything the system sends, user data or not — otherwise a
request carrying no user data would fall outside the rule entirely and could originate anywhere undeclared, which is the
gap this ADR exists to close. The **recipient** restriction applies to user
data, and is ADR-0004 §2's for `models/` and §3's for `tools/`.

Approval is not authorisation to transmit. §2 defines two authorising statuses
and there are no others: `models/` is **continuing** — it transmits under the
permission ADR-0004 §2 already grants — and `tools/` transmits only once it is
**designated**, which approval alone never makes it. An approved but
undesignated boundary sends nothing, however complete its tools' declarations
may be.

"Application-layer" is the scope, and it is a real limit rather than a
technicality: contacting any host discloses source IP, timing and request sizes
to that host and to intermediaries, and an IP identifies the user well enough to
be Tier 1. No declaration covers that, because the system does not choose to
send it and cannot choose not to — §2 gives the consequence, which is that the
only reliable control over transport metadata is not making the request.

**This replaces ADR-0004 §2's "only component" clause and nothing else.** The
rest of §2 — the residency clause (all persistent data local, no cloud storage
by default), the telemetry clause (off by default, no observability egress), and
the configured-set amendment governing *which recipients* `models/` may reach —
is untouched and remains ADR-0004's.

One reading of the residency clause is worth stating, since authorising tool
egress makes it live: it governs **where the assistant keeps its own data** —
memory, user model, audit trail — and commits those to the user's machine. It
does not govern data a user's connected service holds as a result of an action
the user authorised. Creating a calendar event puts data in Google's calendar;
that is the user's own account doing what the user asked, not the assistant
electing cloud storage for its state. Read otherwise, the clause would forbid
every write-capable integration, which is plainly not what ADR-0004 — whose §3
provisions credentials for exactly such integrations — decided. This is a
reading, not an amendment; no clause changes.

That last point is the important one, and it is why this rule says nothing about
recipient authorisation. The obvious temptation was to restate recipient
authorisation as a universal clause here, covering both boundaries. That would
have been a mistake twice over: it would rewrite, by paraphrase, a rule ADR-0004
already states and this ADR has no mandate to touch — the exact
widening-by-assertion ADR-0001 forbids and this ADR exists to avoid — and any
paraphrase strong enough to be worth stating would have been false at `models/`,
where nothing validates that the endpoint contacted is the provider configured.

So recipient authorisation is left where it lives:

- **For `models/`** — ADR-0004 §2 governs, exactly as written and as amended.
  This ADR neither strengthens nor weakens it, and takes no position on how well
  it is enforced. §2 below records, as ADR-0004's open gaps, that endpoint
  validation and credential-access gating are missing there.
- **For `tools/`** — this ADR imposes its own recipient, payload and transport
  rules in §3, binding on that boundary only. They are stronger than anything
  ADR-0004 states, deliberately: a boundary that has never transmitted can be
  held to the standard we would want everywhere, without prohibiting the calls
  the product already makes.

What §1 asserts universally is therefore only what is universally true and
universally checkable: egress happens at approved boundaries, and an approved
boundary declares its payload.

### 2. The boundaries

Two boundaries are approved for egress, each with an explicit status. The list
is closed; adding a third requires another ADR.

**`models/` — continuing.** It transmits under the permission ADR-0004 §2
already grants and has exercised since ratification. This ADR neither
re-authorises it nor certifies it, and adds no precondition to it. Its complete
continuing terms are:

- it transmits only the payload classes declared below, which are documentation
  of what it already sends rather than a new grant;
- its recipients for user data are the model providers the user explicitly
  configured (ADR-0004 §2's configured-set amendment, which stands unamended);
- ADR-0004 §7's minimisation rule binds the content of each call;
- the two controls it does not yet satisfy — transport pinning and
  credential-access gating — are named below, unchanged by this ADR, and
  tracked as ADR-0004's to resolve.

Nothing about that status is new. It is written down here because a rule about
egress boundaries that did not say where `models/` stands would be incomplete.

**`tools/` — approved, and designated only when §3 holds.** This is the
boundary this ADR adds, and the new status applies to it:

- **Approved** — permitted to transmit *in principle*. Approval alone never
  authorises a byte.
- **Designated** — approved *and* every precondition in §3 discharged **in
  code**, not merely in a document. Only then may it transmit.

The gate applies to `tools/` because `tools/` has never transmitted: requiring
the controls first costs nothing and prevents the gaps `models/` now carries
from being recreated at a second boundary. Applying the same gate retroactively
to `models/` would prohibit every model call to close nothing (below).

There is one transition, §3 is its complete condition, and **it does not happen
by itself.** Meeting the conditions makes `tools/` eligible; it does not make it
designated. The flip requires a **later ADR** that names the seam module, attests each §3
item is satisfied and says how, and records the transition. Not a status
amendment to this one: moving `tools/` from transmitting nothing to being a
second operational egress boundary changes a substantive decision, and ADR-0001
reserves that to a new ADR. Treating it as status maintenance would be the same
shortcut this ADR exists to correct, taken one step further along. Designation is the moment
user data starts leaving from a second place in the system, and something that
consequential should not be an inference somebody draws from the state of the
codebase. It also gives review a single artifact to check the attestation
against, rather than asking each reader to re-derive whether the conditions hold.

**On acceptance** `tools/` enters the approved-and-undesignated state and stays
there until that act; while this ADR is `Proposed` it is neither approved nor
designated, and ADR-0004 §2's unamended clause forbids its egress outright.
enforcement tooling should read approved-and-undesignated as "still
prohibited", and should read `models/` as permitted on the continuing terms
above.

This is a rule code must obey, backed by the strongest enforcement currently
available — not a proof that undesignated code cannot reach the network. §4
condition 1 is explicit that an import contract is a net rather than a proof,
and until outbound I/O runs through an injected capability (issue #85) a
subsystem determined to bypass the boundary can.

**Why `models/` is not put through the `tools/` gate.** It would fail it today,
on three counts:

- nothing pins its transport endpoint (issue #83);
- nothing gates its Tier 0 credential read against ADR-0004 §7 (issue #74);
- its model artifact fetch reaches a host nothing pins (issue #89, and see the
  payload class below).

All three are **pre-existing and unchanged by this ADR** — they hold identically
right now under ADR-0004 §2 and would remain exactly as open if this ADR were
rejected. This ADR did not create them; writing down what `models/` transmits is
what made them visible.

So designating `models/` would be certifying a compliance this ADR cannot
demonstrate, and gating it would prohibit every model call the product runs on
in order to close nothing. It does neither. `models/` keeps the permission
ADR-0004 §2 already gives it, on the terms ADR-0004 already sets, and the three
gaps stay ADR-0004's to resolve — #74 in particular is a question about §7's
meaning that this ADR has no standing to answer. What this ADR contributes is
that all three are now written down with issues against them instead of being
undocumented.

Because what the two send differs in kind, this ADR fixes the *granularity* at
which each discharges its obligations. The granularity is part of the
approval — not an implementer's choice, and not something a boundary may weaken
for itself:

- **`models/`** — to model providers the user has explicitly configured. Its
  declaration is **static and made here**, because its payload classes are
  fixed by the boundary's purpose rather than varying per caller. They are:

  - **generation inputs** — conversation content and assembled context
    (Tier 1);
  - **embedding inputs** — the text being indexed or queried, which for memory
    content is Tier 1. Only when the user has opted into a cloud embedder;
    the default embedder is on-device and transmits nothing (ADR-0006 §2);
  - **the provider credential** for the endpoint being called (Tier 0), sent
    as authentication and required to reach only the provider it belongs to
    (ADR-0004 §3). "Required to" and not "guaranteed to": a provider SDK
    configured with a hostile base URL, or following a cross-host redirect,
    would carry both the conversation and the credential elsewhere. The
    transport pinning §3 requires of `tools/` is the same obligation here, and
    is recorded as debt for `models/` on the same grounds as the import-linter
    gap — `models/` transmits today under ADR-0004 §2, and making it a
    precondition would prohibit every model call until the work lands. Issue
    #83 covers both boundaries;
  - **model artifact fetches** (Tier 2) — the request for a named model file
    when a local backend downloads its weights on first use (`fastembed`'s ONNX
    model, ADR-0006 §2). Easy to miss, because the *default* embedder is the
    on-device one and "on-device" describes where inference runs, not where the
    model came from. **Its recipient is governed here**, not by ADR-0004 §2:
    that rule limits where *user data* may go, and this request carries none,
    so stating a rule for it widens nothing and needs no amendment. The rule is
    that it may reach only the artifact repository serving the configured
    model, and carry no user data — with pinning and verification of that host
    outstanding (issue #89), which is why it appears above as a gap. ADR-0006's
    claim that memory content never leaves the device to be indexed is
    unaffected: a different request carrying different content;
  - **request configuration and protocol metadata** (Tier 2) — the model
    identifier, generation parameters such as temperature and token limits, and
    the headers the transport requires. Every call carries some of this and it
    is not user data: it is configuration the system chose. Bounded
    accordingly — this class may carry no Tier 0 or Tier 1 content, so it is
    not a lane for smuggling context into a "settings" field.

  That list *is* the declaration, and it is exhaustive **over what the system
  puts in the request**: a payload class not listed here is not authorised at
  this boundary, and adding one — multimodal attachments, tuning corpora,
  anything else — requires amending this ADR.

  **It does not cover what the network reveals by itself.** Contacting any
  remote host discloses the source IP address, timing, and request sizes to the
  provider and to intermediaries, and an IP identifies the user well enough to
  be Tier 1 under ADR-0004 §1. That is not a payload class — the system does
  not choose to send it and cannot choose not to — so declaring it would be
  declaring the existence of networking. The declaration covers application-
  layer content; transport-level exposure is a property of egress as such.

  **Accepted, and it is the real argument for local-first.** Every byte that
  never leaves also never reveals that the user was awake at 3am asking
  something. This is why ADR-0004 §2's residency rule and ADR-0006's on-device
  default matter more than any per-payload control: the only reliable way to
  not disclose transport metadata is to not make the request. The same holds at
  the `tools/` boundary, and it is one more reason the approved list is closed.

  Recipient authorisation is **per configuration** — the explicitly-configured
  provider set of ADR-0004 §2's configured-set amendment, which stands — not
  per call. ADR-0004 §7's minimisation rule binds the content of each call.

  **The declaration constrains what the *system* discloses, not what the user
  says.** Generation input has two parts, and they are not alike:

  - **User-authored content** — what the user typed or pasted into the
    conversation. Authorised as submitted, whatever it contains. The user is
    the discloser here: authoring the message and sending it to a provider they
    configured is one act, and the system is a conduit, not a party deciding on
    their behalf. A pasted credential does not make the call non-compliant —
    the user disclosed it, deliberately, perhaps to ask about it.
  - **System-assembled context** — memory records, retrieved facts, anything
    `orchestration` adds that the user did not write into this message
    (Tier 1). Here the system *is* deciding, so ADR-0004 §7's minimisation rule
    binds it, and Tier 0 the system holds — credentials in the keyring — is
    never included.

  The tier claims above are **provenance-scoped**, and the distinction matters
  because ADR-0004 §1 classifies by content, not by who typed it. A credential
  the user pastes into a message is Tier 0 under §1 and stays Tier 0; it is not
  reclassified by sitting in a conversation. What the provenance rule says is
  narrower: the *system* did not select it, so no system-side authorisation
  covers it and none is claimed. Precisely, then — the only Tier 0 the **system
  selects and sends** at this boundary is the provider credential, to the
  provider that issued it. Tier 0 that the user authored travels as part of
  their content, disclosed by them.

  Embedding inputs read the same way: content the user wrote is theirs to
  disclose; content the system selected for indexing is the system's decision
  and is bounded by minimisation.

  This is the line that keeps the rule enforceable. A rule forbidding secrets
  in user-authored content would be violated by every ordinary model call the
  moment someone pastes a key, and no mechanism exists to detect it —
  ADR-0004 §5's redaction net is keyed on field names and cannot see inside a
  message body. Declaring such calls non-compliant would make the rule false on
  the day it is accepted. Whether the assistant should nonetheless *warn* a
  user who appears to be pasting a secret is a real question and a good
  feature — it is a product and safety decision, not an egress-compliance one,
  and it is issue #75.

  **The credential is declared here; its recipient is ADR-0004's to govern.**
  Listing it satisfies §1's declaration requirement, which is all §1 asks. Which
  endpoint it may reach is the configured-provider rule of ADR-0004 §2, untouched
  by this ADR — as is the fact that nothing yet validates the endpoint against
  that rule (below).

  A separate question, which this ADR also does not answer, is whether ADR-0004
  §7's gating of "access to Tier 0/1 data" applies to `models/` reading that key
  from the keyring before the call. That is an **internal access** question:
  §1 governs what leaves a boundary, not how a subsystem obtains data it
  holds. §7 and §3 (`SecretStore`) are untouched and
  neither is superseded here, so nothing above exempts `models/` from them.
  The tension predates this ADR — every model call has always needed a
  credential — and is merely made visible by declaring the payload. Issue #74.
  It should be settled before the same question reaches `tools/`, where the
  credential goes to a third-party service rather than to the model provider.
- **the `tools/` integration boundary** — to external services the user has
  explicitly connected. Its declaration is **per tool**, and its recipient
  authorisation is **per call**. Both are stronger than `models/`, and
  necessarily so: `models/` has a fixed set of payload classes and one purpose,
  so they can be enumerated once in this ADR, while tool egress is
  heterogeneous and nothing about it can be inferred from the boundary itself.

  **Passing through `permissions/` is not by itself recipient authorisation.**
  ADR-0016 §3 leaves grant policy undecided and permits auto-granting without a
  prompt, so a call can clear the gate with no user decision about *where* it
  is sending data — and the recipient is a call argument, so it can be a
  destination the user has never seen. To satisfy §1, the authorisation must
  trace to one of two things, bound to the **resolved** destination and not to
  the tool in the abstract:

  - an explicit user decision for this call, or
  - a standing user-established policy that covers that destination — the
    account the user connected, an allowlist they configured.

  **"Destination" means the semantic recipient the call's arguments select, not
  the transport endpoint.** A Gmail send resolves to the addressees in its `to`
  field, not to `googleapis.com`; a Slack post resolves to the channel; a
  calendar invite resolves to its attendee list. Authorising the *host* would
  be close to vacuous — one compromised or mistaken argument sends the user's
  data to an address they never approved, over a connection that is entirely
  legitimate, and every check still passes. Host- or credential-scoped
  authorisation is sufficient only for an operation that cannot disclose onward
  to a recipient chosen by argument — a read, or a write whose effect stays
  inside the connected account.

  **The destination is the stable logical recipient, not a membership
  snapshot.** Where that recipient fans out — a channel, a distribution list, a
  group — authorisation binds to the channel or list itself, not to an
  enumeration of who is in it. Requiring the membership to be authorised would
  be requiring something unimplementable: these services offer no atomic
  "authorise this membership and send to exactly it" operation, so a member
  joining between resolution and delivery would make every send retroactively
  non-compliant. **Accepted cost, stated rather than hidden:** authorising a
  post to `#team` authorises delivery to whoever is in `#team` when it lands,
  which may not be who was in it when the user approved. That is the same trust
  the user extends by connecting the account, and the mitigation is that the
  channel is one the user named. An operation whose fan-out the user cannot
  reasonably anticipate — a list the assistant selected rather than the user —
  is not covered by this and needs the explicit per-call decision.

  **A destination is identified by the strongest identity its protocol
  offers**, which differs by destination type:

  - **Service-scoped resources** — a Slack channel, a Drive folder, a connected
    account — have a service-issued immutable id. Authorisation and audit bind
    to that id plus the connected account it belongs to, never to a display
    name. Binding a standing policy to the string `#team` authorises whatever
    `#team` names later: an administrator renames the channel, a new `#team`
    takes the name, and a call still matches the authorised string while
    sending to a different room. That is not the accepted membership-drift cost
    above — the logical recipient itself has been substituted, the same
    rebinding failure ADR-0016 §5 avoids by spending a tool id on first use.
  - **Address-based protocols** — email to `alice@example.com`, an external
    calendar attendee — have no issued identifier; the address *is* the
    identity. Authorisation binds to the normalised address, and normalisation
    has to be specified rather than assumed, since case handling and provider
    aliasing decide whether two strings are the same recipient.

  **Accepted cost for the second kind:** an address can be reassigned, and
  nothing in the protocol reveals that it changed hands. A standing
  authorisation for `alice@example.com` follows the address, not the person. No
  mechanism can close this — it is a property of email, and the same one every
  user already lives with — so it is recorded rather than engineered around.
  Requiring an immutable id here would be requiring something that does not
  exist, and would make ordinary email and calendar operations permanently
  unable to satisfy §3.

  A grant justified only by the tool's declared metadata does not qualify
  either. The audit record must capture the resolved destinations and which of
  the two bases authorised them, or after the fact nobody can tell an
  authorised recipient from a defaulted one. Working this out is the invocation
  ADR's, with issue #68.

  What is approved is a *named module seam inside* `tools/`, not the package:
  `tools/` also owns tool definitions and the registry, and neither has any
  business holding a network client. Which module is the seam is the
  integration/invocation ADR's to name, and it must be named there precisely
  enough for the import-linter contract to pin that module rather than the
  package (issue #66). Until it is named the approval has no concrete extent;
  naming it discharges one of §3's preconditions, and the boundary becomes
  designated only when they all hold.

Egress from anywhere else is a bug, and adding a third approved boundary
requires a further ADR — it is a closed list, not a category a subsystem can
argue its way into.

### 3. This ADR is not self-executing

It removes a categorical prohibition; it does not make any transmission legal.
This section is the **complete and only** precondition list, it applies to
`tools/`, and every item must hold **in code** — none is a property this ADR
asserts is already in place. It does not apply to `models/`, which this ADR
does not gate at all (§2): `models/` transmits under ADR-0004 §2's existing
permission, and nothing here adds a condition to it or removes one.

**These are decisions, and it is worth being straight about that.** Calling
them "just preconditions" would understate what this section does. §3 settles,
for the `tools/` boundary:

- that recipient authorisation must trace to a user decision or standing user
  policy, so a bare `permissions/` grant does not suffice — narrowing the grant
  policy ADR-0016 §3 left open, without saying which grants are given;
- that a destination is the semantic recipient at the stable logical level,
  identified by service-issued id where one exists and normalised address where
  none does, with exact comparison wherever equivalence is unproven;
- that a resolution lookup is itself a tool call, not a privileged side channel;
- that the payload must be bound before transmission and described inspectably
  after it, which is a partial answer to ADR-0016 §7's deferred per-call data
  reach (issue #57) — it fixes the *obligation* while leaving the artifact open;
- that the audit record needs outcomes, not just intents;
- that these hold in code, evidenced by failure-path tests.

**What remains deferred is implementation shape and grant policy**: how each
obligation is constructed, and which combinations `permissions/` actually
approves or refuses. Where an item names specifics — the contents of a binding
envelope, the entries in the test matrix — read it as a floor the owning ADR
must cover, not a schema it must adopt. This ADR does not amend ADR-0016; it
constrains what the invocation and `permissions/` ADRs may ratify, which is
what a precondition is for. What they may not do is designate the boundary with
an item unsatisfied.

None of it is discharged today, which is why `tools/` is approved,
undesignated, and permitted no egress at all:

- the named seam and the import-linter contract pinning it (§4 condition 1,
  issue #66);
- a ratified invocation contract that gates each call through `permissions/`
  and records it in the audit trail *before* the call transmits, rather than
  relying on the definition's declared ceiling alone (§4 condition 3);
- the destination rules — recipient authorisation must bind to the semantic
  recipient the call's arguments select, not the transport endpoint, at the
  granularity of the stable logical destination (§2), and trace to a user
  decision or standing user policy, bound to the strongest identity the
  destination's protocol offers — a service-issued id where one exists, a
  normalised address where none does (§2); the audit record must capture that
  identifier, the connected account, and that basis.
- the credential-access rules — ADR-0004 §7 gates access to Tier 0 data, not
  only its transmission, so reading an integration's token from `SecretStore`
  is itself gated and audited. Nothing above covers this: an implementation
  could read the token, then run the per-call check and stop when denied, and
  satisfy every other precondition while having already accessed Tier 0 data
  ungated. The invocation ADR must resolve §7's applicability (issue #74) and
  gate the read, not just the send. `models/` carries this as debt because it
  already transmits (§2); `tools/` does not, so here it is a precondition.
- the transport rules — the endpoint the seam actually opens a connection to
  must be pinned to the service the user connected, and a redirect must not
  carry the request or its credential to another host. Authorising a semantic
  recipient says nothing about *which server* received the bytes: a
  configurable API base URL or a followed cross-host redirect delivers both the
  payload and the bearer token somewhere else while the audit record still
  reads `alice@example.com`. Semantic recipient and transport endpoint are
  independent, and both have to be constrained. Worse than a data leak: the
  credential travels too, so the attacker gets durable access rather than one
  message. Issue #83. A `permissions/` grant alone does
  not satisfy §1, and neither does a credential-scoped host for an operation
  that can disclose onward (ADR-0016 §3, §7; issue #68).
- the per-call payload rules. A tool's declared reach is a *ceiling over
  tiers*, and a ceiling authorises nothing: a tool declaring it may disclose
  Tier 1 satisfies its declaration whether it sends one selected memory record
  or the entire memory database. Tier validation, destination authorisation and
  the audit fields above would all pass in both cases. So the invocation ADR
  must additionally bind **what** is sent: the payload must be fixed and
  approved *before* transmission, and the audit record must describe it
  **inspectably** — which records or fields were selected, how many, and at
  what tiers. Binding alone is not enough. A SHA-256 of the request body is
  perfectly deterministic and pins the payload exactly, while leaving an
  auditor unable to tell one memory record from the whole database — which is
  the only question the record exists to answer. "The minimum necessary"
  has to be checkable against the record, not merely fixed by it. Issue #57.

  **This is a rule this ADR states, not ADR-0004 §7 restated.** §7's
  minimisation clause says to "send the minimum necessary context **to the
  model provider**" — it is written about that boundary and this ADR does not
  supersede it. Rather than quietly reading §7 as though it already covered
  tools, the obligation above is imposed here, on `tools/`, by this ADR. The
  effect is the same and the provenance is honest; widening someone else's
  clause by assertion is what ADR-0001 forbids.

  That description is itself Tier 1 and belongs in the audit trail, which
  ADR-0004 §7 already makes a Tier 1 store — so this is a storage obligation,
  not a reason to record less.

  **"Approved" requires a named approver and stated inputs.** Recording the
  payload inspectably makes an overbroad send *visible*; it does not make it
  *refused*. A tool could select the whole memory database, describe that
  faithfully in the audit record, clear a standing recipient policy, and
  satisfy every mechanical condition above while disclosing far more than the
  task needed. So the precondition is not met by a record alone: a ratified
  contract must say **who** decides a payload is minimal — `permissions/`, on
  what policy inputs — and that decision must be able to refuse. Which
  combinations it refuses is `permissions/`'s ADR to write (ADR-0016 §3 reserves
  exactly this) and this ADR does not pre-empt it; what this ADR requires is
  that the decision exist, be ratified, and be capable of saying no before
  `tools/` is designated.

  This ADR states the requirement and deliberately does not design the
  artifact: what that payload description is, and how a gate binds to it,
  depends on the invocation contract's shape and is that ADR's to settle.

- the binding rules — what execution transmits must be the thing that was
  authorised, immutably bound at authorisation time and consumed unchanged.
  Where a call has several recipients — an email to three addressees, an invite
  to a list — they are authorised and bound as **one set**, and an unauthorised
  member fails the whole call rather than being dropped from it. Sending to the
  authorised subset silently would deliver a message the user never approved
  the shape of, and partial success is the hardest failure to notice
  afterwards. Binding at least the connected account, the canonical
  destination set, the approved payload description and the decision itself; whether that is one
  envelope object or another construction is the invocation ADR's call.
  **Credential values are excluded from what is bound**: bind a stable
  reference to the credential, not the secret, and fetch the value only after
  approval, sending it only over the pinned transport. Otherwise the binding
  artifact and every audit record derived from it become Tier 0 stores, and a
  design meant to make disclosure reviewable would put secrets in the review
  trail. Without it the
  payload is bound (above) while the destination is not: a call can resolve and
  authorise `alice@example.com`, then have a mutable argument re-resolved to
  `bob@example.com` before the send, with the audit still reading Alice. This
  is the same substitution ADR-0016 §5 refuses for tool ids, applied to the
  recipient.
- the canonicalisation rules — how a destination is reduced to the form a
  standing policy is matched against, **per protocol**. This is
  security-critical and currently unspecified: lowercasing an address whose
  local part the protocol treats as case-sensitive lets a grant for one address
  authorise a different one, and provider-specific aliasing produces the
  inverse failure. The contract must default to **exact comparison wherever
  equivalence cannot be proven**, and the audit record must carry both the
  supplied and the canonical form.
- the resolution rules — resolving a user-supplied name to the immutable
  identifier the rules above require may itself need a remote call (`#team` to
  a Slack channel id). That lookup is egress and this ADR does not exempt it:
  a resolution lookup is **itself a tool call** and must be declared,
  registered, gated and audited under ADR-0016 like any other — not a privileged
  side channel the invocation contract exempts. Its own recipient is the
  connected account's service, its declared disclosure is whatever the query
  carries, and only once it returns may the consequential call be authorised
  against the resolved destination. The alternative the invocation ADR may
  prefer is to forbid remote resolution entirely and require destinations to
  come from data already obtained through such a call. What it may not do is
  leave resolution ungated: that would reintroduce, as a back door, exactly the
  unauthorised egress this section exists to prevent. Without one of the two,
  the preconditions are unsatisfiable for ordinary integrations — a tool could
  not look up the id it is required to bind to without transmitting first.
- the outcome rules — a pre-transmission audit record states an intent, not a
  result. It must carry an attempt identifier and an explicit outcome —
  pending, succeeded, failed, indeterminate — with a stated path for
  reconciling records left pending by a crash. Otherwise a provider timeout is
  indistinguishable from a successful disclosure, and a crash after the service
  accepted the request leaves nobody able to say whether the side effect
  happened, which is precisely the transparency ADR-0004 §7's audit trail
  exists to provide.
- **conformance tests for every condition above**, not prose alone, and
  failure-path tests specifically — the happy path passing proves almost
  nothing here. The matrix must cover at least:

  - **denial** performs no credential read and no network I/O;
  - **transport diversion** — a hostile base URL and a cross-host redirect are
    both refused, and the credential does not travel with either;
  - **canonicalisation boundaries** — addresses differing only in case or by a
    provider alias resolve as the protocol says, not as convenience suggests,
    and unproven equivalence compares exactly;
  - **resolution** is gated and audited on its own, and an unresolved or failed
    lookup does not fall through to a send;
  - **mutation races** — destination, payload and transport cannot change
    between authorisation and transmission, including a recipient added to the
    set after the decision;
  - **partial authorisation** — a multi-recipient call with one unauthorised
    member fails entirely and delivers to none of them;
  - **crash and outcome reconciliation** — a record left pending by a crash is
    reconcilable, and a timeout is distinguishable from a success.

  A precondition nothing tests is a precondition nobody can show holds, and §2
  requires these to hold *in code*. The invocation ADR may extend this matrix;
  it may not ship without it.

A boundary that meets the conditions in a document but not in the code is
approved, not designated, and an approved boundary does not transmit. Meeting
them all in code makes `tools/` *eligible*; the ratifying act in §2 is what
designates it. If the invocation ADR cannot supply every one of them, `tools/`
does not get to transmit on the strength of this ADR.

### 4. Why this preserves what ADR-0004 §2 protects

The configured-set amendment found that §2's rationale is about **who** receives
data, never **how many**. The equivalent line for components is that §2's
rationale is about egress being **accountable** — few, named, and answerable for
what it sends — never about the number of places that are accountable. "One" was
never argued for anywhere in ADR-0004; it was a count of the subsystems that
existed. What ADR-0004 actually argues for, in §2 and §7, is that data must not
leave from somewhere nobody designated, in a quantity nobody declared, without a
check nobody ran. A second boundary costs that property nothing as long as it
meets all three conditions, and `tools/` is held to all three:

1. **Designated.** The boundary is *named*, not merely described, and backed by
   mechanical enforcement rather than convention. This ADR approves the
   category — a seam inside `tools/` — and does not name the module; the
   ratifying act in §2 does that, and the import-linter contract ADR-0004's
   Consequences provision for then permits network clients in `models/` and
   that named module, and nowhere else.

   **An import contract is a net, not a proof**, and this ADR does not claim
   otherwise. It matches module names, so it cannot see a subsystem reaching
   the network through `urllib`, a raw `socket`, a library added after the
   contract was written, or an internal wrapper that imports the client on its
   behalf. What it reliably catches is the realistic accident — someone adding
   `httpx` to `memory/` without thinking — not a determined bypass.

   Closing that gap properly means outbound I/O going through a transport
   capability only designated boundaries hold: *injected*, as `ModelProvider`,
   `Embedder` and `SecretStore` already are, so a subsystem never handed it
   cannot connect regardless of what it imports, and a test can prove the
   property directly. That is issue #85, and it is the enforcement this
   condition ultimately wants; the import contracts are defence in depth in the
   meantime.
2. **Declaring.** Every tool states, as a required and fail-closed property of
   its definition, which data tiers a call transmits off-device (ADR-0016 §3).
   A tool whose author does not say what leaves cannot be defined at all. This
   is the per-tool granularity §2 fixes, and it is strictly more than `models/`
   owes — not because `tools/` is less trusted, but because a fixed set of
   payload classes can be enumerated once in a document, each still distinct,
   while a heterogeneous one cannot be declared anywhere but at each tool.
3. **Authorised before transmitting.** ADR-0004 §7 already requires that every
   side-effecting tool call pass `permissions/` and land in the audit trail,
   and a tool that transmits is side-effecting by construction (ADR-0016 §3).
   That gate is necessary but not sufficient: §2 additionally requires the
   authorisation to trace to a user decision or a standing user policy bound to
   the resolved destination, because ADR-0016 permits auto-granting and an
   auto-grant on tool metadata says nothing about where the bytes went. With
   that constraint the granularity is finer than `models/`, whose recipients
   the user authorises once by configuring them — but it is finer only if the
   invocation ADR supplies it, which is why §3 lists it as a precondition
   rather than an accomplished fact.

**Honest accounting.** Condition 1 is a genuine widening, and this ADR does not
pretend otherwise — a second exit point is a second thing that can be got wrong,
and mechanical enforcement of the contract in condition 1 is what keeps
"designated" from decaying into "whatever imported `httpx`". Against that, the
`tools/` boundary is held to a *stricter* granularity on conditions 2 and 3 than
the boundary ADR-0004 §2 was written to describe. This ADR does not lower the
bar to admit `tools/`; it writes down the bar `models/` was implicitly clearing,
and sets a higher one where the weaker form would not be meaningful.

### 5. Why a superseding ADR rather than an in-place amendment

ADR-0001 reserves changing a past decision to a new ADR that supersedes the old
one and updates its status. Nothing grants an exception. CONTRIBUTING's
"Trivial ADRs (amendments, status changes, supersedes) skip both the separate PR
and the review" is a statement about **review cost** — which ceremony a change
of a given size warrants — not a grant of authority to change a decision in
place. It never claimed the power ADR-0001 reserves, so there is no conflict
between the two documents to resolve: the authority was simply never granted.

The question is therefore only whether this changes a decision. It does. An
earlier draft argued that ADR-0004 is internally inconsistent as ratified — §2's
clause and the Consequences clause cannot both be true — and that resolving the
inconsistency determines what ADR-0004 decided rather than replacing it. That
argument is sound as far as it goes, and it is why the *contradiction* is worth
fixing at all. But this ADR does more than disambiguate: it designates a new
egress boundary, closes the list, and fixes per-boundary granularity that
ADR-0004 never specified for either boundary. It also forces corrections to
ADR-0006 §2 and ADR-0016. A change that ripples into two other ratified ADRs is
decision-shaped, not editorial.

### 6. The prior amendment's declining clause

ADR-0004 §2's configured-set amendment closes by declining exactly this
widening — "the amendment widens *which* providers are legitimate recipients,
not *which components* may transmit. `models/` remains the only one."

That sentence is **left exactly as ratified**, with a dated note appended at the
end of ADR-0004 §2 rather than any edit to the sentence itself. It does two
different jobs. As a scope statement about what *that* amendment did, it is
accurate and worth preserving: a reader should be able to see that the component
prohibition was examined and deliberately left standing on that date, not
overlooked. As a statement about the rule this ADR proposes, it would be
out of date on acceptance. Rewriting it would erase the first to fix the second,
and an ADR is an append-only record of what was decided when. So the note
carries the pointer, and the accepted text carries none of it.

### 7. What happens to ADR-0004 on acceptance

ADR-0001 requires the superseded ADR's status to be updated, not merely
annotated. While this ADR is `Proposed`, ADR-0004 is untouched and its §2 is
the live rule. **On acceptance of this ADR**, and as part of ratifying it:

- **Edit exactly one line:** ADR-0004's `Status` field becomes
  `- Status: Accepted, partially superseded by ADR-0017 (§2's egress clause)`.
  That is the status update ADR-0001 requires and the only edit to ADR-0004 it
  authorises. ADR-0004 has one status field and keeps one; the dated notes are
  notes, not competing status declarations.

  `template.md` offers only `Proposed | Accepted | Superseded by ADR-XXXX`, all
  of which assume supersession is total, and neither fits ADR-0004: plain
  `Accepted` understates it, while `Superseded by ADR-0017` would falsely
  retire an entire privacy policy over one clause. The form above **follows the
  precedent ADR-0018 set** for its partial supersession of ADR-0016, because a
  second ADR inventing a second format is how a vocabulary stops being one.

  Recorded as a known weakness rather than silently accepted: a reader or tool
  matching on the leading `Accepted` can still miss the qualifier, and leading
  with the supersession would not have that failure. Which form becomes
  canonical — and whether partial supersession should be discouraged in favour
  of splitting the clause into an ADR that can be superseded whole — is
  issue #87's to settle for the whole repository, not this ADR's to decide by
  diverging.
- **Append, do not rewrite, everywhere else.** The existing dated notes — in
  ADR-0004's header and at the end of its §2 — stay exactly as merged, still
  reading "proposed", because that is what was true when they were written.
  Acceptance adds a new dated note beside each recording that ADR-0017 was
  accepted and the supersession is in force. Flipping the old notes from
  "proposed" to "in force" would erase what they recorded, which is the same
  append-only violation this ADR exists to avoid committing.
- **Nothing else moves.** ADR-0004's §2 text and its configured-set amendment,
  and the notes in ADR-0006 and ADR-0016, remain as written. The ADR-0006 and
  ADR-0016 notes are already phrased conditionally and need no change.

Stated here so acceptance is a defined operation rather than a judgement call
by whoever merges it.

### 8. What is not decided here

This ADR makes tool egress *permissible in principle*; it authorises no
particular tool, destination, or payload, and by itself no transmission at all.
Destination-level policy — which recipients are approved — remains
parameter-level and deferred (ADR-0016 §7; issues #57, #68). Nor does it touch
ADR-0004 §7's minimisation rule, which is written about the model provider and
stays exactly as scoped; the equivalent obligation on tool payloads is imposed
by §3 of this ADR rather than read into §7. The invocation ADR still owes the seam, the gating
contract, and the rules deciding which declared disclosures `permissions/`
grants. What it no longer owes is a prior decision permitting the category to
exist.

### 9. Rejected alternative: a dedicated injected egress capability

The stronger enforcement shape is an outbound-transport capability in `core`,
injected into the boundaries allowed to use it, so a subsystem never handed it
cannot connect regardless of what it imports. That is testable, contract-based,
and squarely golden rule 1 — and §4 condition 1 concedes it is what mechanical
enforcement here ultimately wants. It is deferred rather than adopted, for
reasons worth stating since it is the better end state:

- **It does not fit `models/`.** Provider SDKs (`pydantic-ai`, `anthropic`,
  `openai`) open their own sockets. Routing `models/` through our transport
  would mean either not using those SDKs or wrapping them at a seam they do not
  expose, so the capability could not cover the one boundary transmitting
  today. A rule enforced at one boundary and not the other is roughly what we
  already have with import contracts, at much higher cost.
- **Its shape depends on the invocation contract that does not exist.** Whether
  it is HTTP-shaped or lower-level, and what it must expose for retries,
  streaming and timeouts, are answerable once something calls it and not
  before. Ratifying it now would bless a seam with no implementation contact —
  the failure CONTRIBUTING explicitly warns about, and the one ADR-0016 §5
  avoided by keeping registration internal.
- **The decisions are independent.** Which boundaries may transmit, and what
  mechanism enforces that, are separate questions. Settling the first now
  unblocks the invocation ADR; the second can land later without reopening it,
  because nothing here depends on enforcement being import-based.

The cost of deferring is stated plainly in §2 and §4 rather than hidden: until
the capability exists, "designated" is a rule backed by a net, not a proof.
Issue #85 carries it.

## Consequences

- **ADR-0004 §2's egress clause is superseded on acceptance**, not before. Its
  header and the end of its §2 carry dated notes recording the proposal; no
  text above those notes is altered, and until this ADR is accepted §2 remains
  the live rule. Everything else in ADR-0004 stands regardless, including §2's
  residency and telemetry clauses and the configured-set amendment.
- **ADR-0006 §2 and ADR-0016 keep their ratified wording**; each gains a dated
  note only. ADR-0006 §2 says cloud embedding is "like all egress, confined to
  the `models/` layer" — a passing restatement of ADR-0004 §2 — and its note
  records that this ADR would narrow the citation to *model-provider* egress.
  ADR-0016's Consequences bullet recording that ADR-0004 §2 "still reads as
  forbidding all tool egress" gains a note pointing here. Neither ADR's own
  decision changes, and neither sentence is rewritten: ADR-0001's append-only
  rule permits a status update and an appended note, not an edit to accepted
  text — the same discipline §6 applies to the configured-set amendment.
- **The import-linter contract ADR-0004's Consequences provision for is now
  load-bearing** and only partly written. What exists forbids four named
  provider SDKs outside `models/`; what is missing is a contract over network
  clients generally, and one that can pin the `tools/` seam by module once it
  is named (issue #66).

  For `models/` this is **debt**, not a condition on anything — this ADR does
  not gate that boundary (§2), so widening the contract strengthens enforcement
  of a permission ADR-0004 already grants. For `tools/` the module-pinning
  contract *is* a §3 precondition, because there the contract is what gives the
  approval a concrete extent in the first place.
- **The invocation ADR inherits the complete §3 list**, not a summary of it,
  and must discharge every item before the first tool transmits — then a later
  ADR ratifies the designation (§2). The list is deliberately not abbreviated
  here: each item exists because a review round found a concrete way to satisfy
  the others and still leak, and a three-line précis is how one of them gets
  quietly dropped. What the invocation ADR no longer inherits is a prohibition
  it would have had to overturn on its way.
- **`tools/` still transmits nothing.** No behaviour changes on ratification;
  this is a docs-only decision about what will be permitted.
- **ADR-0004's earlier configured-set amendment remains an in-place amendment**,
  which the strict reading adopted in §5 makes retroactively irregular. It is
  deliberately left as-is: the pattern is fixed forward, not retrofitted. Issue
  #71 records the discrepancy.
