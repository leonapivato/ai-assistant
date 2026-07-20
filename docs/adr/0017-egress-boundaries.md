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

**User data may leave the device only from a boundary designated for egress;
every designated boundary must have what it transmits declared, and its
recipients authorised by the user, before it transmits.**

This replaces ADR-0004 §2's "only component" clause. Its residency clause (all
persistent data local, no cloud storage by default) and its telemetry clause
(off by default, no observability egress) are unaffected and remain ADR-0004's.

### 2. The boundaries

Two boundaries are **approved** for egress by this ADR, and they are in
different states. The distinction is load-bearing, so it is named:

- **Approved** — this ADR permits the boundary to transmit *in principle*. The
  list of approved boundaries is closed; adding a third requires another ADR.
  Approval alone never authorises a byte.
- **Designated** — approved *and* every precondition in §3 discharged **in
  code**, not merely in a document. Only a designated boundary may transmit.

There is one transition and §3 is its complete condition. A boundary is
designated exactly when it is approved here and every item in §3's list holds
for it; short of that it is approved and must not transmit, whatever partial
progress exists. Naming the seam is one precondition among several, not the
transition itself.

The two boundaries have different precondition lists, and §3 states each.

`models/` is **designated** on acceptance. Its declaration is complete in §2,
its recipients are authorised by configuration, and its mechanical pin is the
existing "provider SDKs are confined to the models layer" contract. That pin is
narrower than this ADR wants — it forbids four named SDKs rather than network
clients generally, so nothing today stops an unrelated subsystem importing
`httpx` — and closing that gap is §3's one outstanding item for `models/`. It
is a strengthening, not a gate: `models/` transmits today under ADR-0004 §2,
this ADR does not narrow that permission, and making designation wait on a
contract that has never existed would prohibit the model calls the product is
built on. Issue #66.

The `tools/` seam is **approved and undesignated**, and stays that way until
every item in §3's `tools/` list is discharged. Enforcement tooling should read
approved-and-undesignated as "still prohibited".

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
    as authentication and only ever to the provider it belongs to
    (ADR-0004 §3);
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
    never included. The only Tier 0 leaving this boundary is the provider
    credential, to the provider that issued it.

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

  **The credential satisfies §1 on its own terms.** Its declaration is the
  entry above, and its recipient authorisation is direct: it goes to the
  provider that issued it and to no one else, and the user authorised that
  recipient by configuring that provider — the same act that authorises the
  Tier 1 payloads. There is no open question about the credential's *egress*.

  A separate question, which this ADR does not answer, is whether ADR-0004 §7's
  gating of "access to Tier 0/1 data" applies to `models/` reading that key
  from the keyring before the call. That is an **internal access** question,
  not a recipient question: §1 governs what leaves and to whom, not how a
  subsystem obtains data it holds. §7 and §3 (`SecretStore`) are untouched and
  neither is superseded here, so nothing above exempts `models/` from them.
  The tension predates this ADR — every model call has always needed a
  credential — and is merely made visible by declaring the payload. Issue #74.
  It should be settled before the same question reaches `tools/`, where the
  credential goes to a third-party service rather than to the model provider.
- **the `tools/` integration boundary** — to external services the user has
  explicitly connected. Its declaration is **per tool**, and its recipient
  authorisation is **per call**. Both are stronger than `models/`, and
  necessarily so: `models/` has one payload class and one purpose, while tool
  egress is heterogeneous, so nothing about it can be inferred from the
  boundary itself.

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
Each boundary has its own exhaustive precondition list, and every item must
hold **in code** — none is a property this ADR asserts is already in place.

**For `models/`,** one item: widen the import-linter contract from the four
named provider SDKs it forbids today to network clients generally. `models/` is
designated on acceptance regardless (§2) — it transmits today under ADR-0004
§2 and this ADR does not narrow that — so this strengthens an existing pin
rather than gating the boundary. Issue #66.

**For `tools/`,** the list below, none of it discharged today, which is why
`tools/` is approved, undesignated, and permitted no egress at all:

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
  must additionally bind **what** is sent: the concrete payload — or a
  deterministic description of it — must be fixed and approved *before*
  transmission and represented in the audit record, so that "the minimum
  necessary" (ADR-0004 §7) is a checkable claim about a specific call rather
  than a principle nothing tests. Issue #57.

  This ADR states the requirement and deliberately does not design the
  artifact: what that payload description is, and how a gate binds to it,
  depends on the invocation contract's shape and is that ADR's to settle.

A boundary that meets the conditions in a document but not in the code is
approved, not designated, and an approved boundary does not transmit. If the
invocation ADR cannot supply every one of them, `tools/` does not get to
transmit on the strength of this ADR.

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

1. **Designated.** The boundary is named here and backed by mechanical
   enforcement rather than convention: the import-linter contract ADR-0004's
   Consequences provision for permits network/provider clients in `models/` and
   the designated `tools/` seam once it exists, and nowhere else.

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
   owes — not because `tools/` is less trusted, but because a single fixed
   payload class can be declared once in a document while a heterogeneous one
   cannot be declared anywhere but at each tool.
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
  `- Status: Accepted (partially superseded by ADR-0017 — §2's egress clause)`.
  That is the status update ADR-0001 requires and the only edit to ADR-0004 it
  authorises. ADR-0004 has one status field and keeps one; the dated notes are
  notes, not competing status declarations.
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
parameter-level and deferred (ADR-0016 §7; issues #57, #68). Nor does it weaken
ADR-0004 §7's minimisation rule: "send the minimum necessary" now reads against
every approved boundary. The invocation ADR still owes the seam, the gating
contract, and the rules deciding which declared disclosures `permissions/`
grants. What it no longer owes is a prior decision permitting the category to
exist.

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
  is named. Until both land, "designated" leans on a narrower pin than the word
  implies for `models/`, and is unreachable for `tools/` (issue #66).
- **The invocation ADR inherits three obligations** it must discharge before the
  first tool transmits: name the seam, gate per call before transmitting, and
  constrain destination and per-call payload. It no longer inherits a
  prohibition it would have had to overturn on its way.
- **`tools/` still transmits nothing.** No behaviour changes on ratification;
  this is a docs-only decision about what will be permitted.
- **ADR-0004's earlier configured-set amendment remains an in-place amendment**,
  which the strict reading adopted in §5 makes retroactively irregular. It is
  deliberately left as-is: the pattern is fixed forward, not retrofitted. Issue
  #71 records the discrepancy.
