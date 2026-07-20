# 17. Egress boundaries: `models/` is not the only one

- Status: Proposed
- Date: 2026-07-19
- Supersedes **on acceptance**: ADR-0004 §2's egress clause ("The **only**
  component permitted to send user data off-device is the `models/` layer…
  Every other egress is a bug"), as amended 2026-07-19. While this ADR is
  `Proposed`, that clause remains the live rule. The rest of ADR-0004 — §1 and
  §§3–7, and §2's residency and telemetry clauses — stands unchanged either way.

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
calendar is not a design; it is a contradiction ADR-0004 has carried since
ratification.

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

**User data may leave the device only from `models/` or from a designated
integration seam inside `tools/`; every other egress is a bug. `models/`
continues under the permission ADR-0004 §2 already grants. The `tools/` seam is
approved here but transmits nothing until it is designated, which requires the
conditions in §3 to hold in code and a later ADR to ratify that they do.**

That is the whole decision. It replaces ADR-0004 §2's "only component" clause
and nothing else — the residency clause, the telemetry clause, and the
configured-set amendment governing which recipients `models/` may reach all
remain ADR-0004's, untouched.

Two things it deliberately does not do. It does not restate recipient
authorisation as a rule of its own: that is ADR-0004 §2's for `models/`, and
paraphrasing it here would widen by assertion the very clause this ADR is
careful to supersede narrowly. And it does not certify that either boundary
already satisfies everything one might want of it — §2 records where `models/`
does not.

One reading of the residency clause is worth stating, since authorising tool
egress makes it live: it governs where the assistant keeps **its own** data —
memory, user model, audit trail — not what a user's connected service holds
because the user asked for an action. Creating a calendar event puts data in
Google's calendar; that is the user's account doing what they asked, not the
assistant electing cloud storage. Read otherwise the clause would forbid every
write-capable integration, which is plainly not what ADR-0004 — whose §3
provisions credentials for exactly those integrations — decided.

### 2. The two boundaries

**`models/` — continuing.** It transmits under ADR-0004 §2's existing
permission and has since ratification. This ADR neither re-authorises nor
certifies it and adds no precondition to it. It must declare what it sends, and
does: generation inputs, embedding inputs, the provider credential, request
configuration and protocol metadata, and the model artifact fetch a local
embedding backend performs on first use. Recipients for user data remain the
configured providers (ADR-0004 §2).

Three controls it does not have today, all **pre-existing** — they hold
identically right now under ADR-0004 §2 and would remain exactly as open if this
ADR were rejected. This ADR did not create them; writing down what `models/`
transmits is what made them visible:

- nothing pins its transport endpoint, so a hostile base URL or cross-host
  redirect would carry conversation *and* credential elsewhere (issue #83);
- nothing gates its Tier 0 credential read against ADR-0004 §7 (issue #74);
- the model artifact fetch reaches a host nothing pins, and the *default*
  embedder is the on-device one — "on-device" describes where inference runs,
  not where the model came from (issue #89).

They are named rather than fixed here because gating `models/` on them would
prohibit every model call the product runs on, to close gaps that stay open if
this ADR is rejected. What this ADR contributes is that all three are now
written down with issues against them.

**`tools/` — approved, undesignated.** On acceptance it may transmit *in
principle* and nothing in practice. It becomes designated when every condition
in §3 holds in code **and** a later ADR names the seam module, attests each
condition is satisfied and how, and records the transition. Not a status
amendment: a second operational egress boundary is a substantive decision, and
ADR-0001 reserves those to a new ADR.

The seam is a **named module inside** `tools/`, not the package — `tools/` also
owns definitions and the registry, and neither has any business holding a
network client. Naming it is the integration ADR's job, precise enough for an
import-linter contract to pin the module (issue #66).

### 3. Conditions on designating the `tools/` seam

None is discharged today. Each is a property that must hold, not a design; the
invocation and `permissions/` ADRs own the mechanisms and may satisfy any of
them however they judge best. What they may not do is designate the boundary
with one unsatisfied.

- **A named seam and an import-linter contract pinning it** (issue #66). The
  contract today forbids four provider SDKs outside `models/`, not network
  clients generally.
- **Per-call gating that runs before transmission**, not merely a declared
  ceiling (ADR-0016 §3).
- **Recipient authorisation that traces to a user decision or a standing user
  policy**, bound to the resolved destination. A `permissions/` grant alone
  does not suffice — ADR-0016 permits auto-granting, which says nothing about
  where the bytes went. Destination means the semantic recipient the arguments
  select, not the transport endpoint: authorising `googleapis.com` would let a
  send reach any address (issue #68).
- **Credential access gated, not just transmission.** ADR-0004 §7 gates access
  to Tier 0 data, so reading the token is what needs gating; otherwise an
  implementation reads it, then checks, then stops (issue #74).
- **Transport pinned to the connected service**, with redirects unable to carry
  the request or its credential to another host (issue #83).
- **The payload bound before transmission and described inspectably after it** —
  which records, how many, at what tiers. A digest binds the payload while
  leaving an auditor unable to tell one memory record from the whole database
  (issue #57).
- **A named approver able to refuse.** An inspectable record makes an overbroad
  send visible, not refusable. Which combinations `permissions/` refuses is its
  ADR's to write; that the decision exists and can say no is required here.
- **The detailed obligations in issue #93** — binding envelope and credential
  references, multi-recipient sets, per-protocol canonicalisation, resolution
  as a gated call, audit outcome states, and the failure-path test matrix.

A boundary meeting these in a document but not in code is approved, not
designated, and an approved boundary transmits nothing.

### 4. Why this preserves what ADR-0004 §2 protects

The configured-set amendment found that §2's rationale is about **who** receives
data, never **how many**. The equivalent line for components is that it is about
egress being **accountable** — few, named, and answerable for what it sends —
never about the number of accountable places. "One" was never argued for in
ADR-0004; it was a count of the subsystems that existed. What the ADR argues
for, in §2 and §7, is that data must not leave from somewhere nobody designated,
in a quantity nobody declared, without a check nobody ran.

A second boundary costs that nothing, and `tools/` is held to a stricter
standard than `models/` on every axis: declaration per tool rather than once in
a document, recipient authorisation per call rather than per configuration, and
§3's conditions required before it sends anything rather than tracked as debt.
That asymmetry is deliberate. A boundary that has never transmitted can be held
to the standard we would want everywhere, without prohibiting calls the product
already makes.

**Honest accounting.** A second exit point is a second thing that can be got
wrong. And the mechanical enforcement backing "designated" is weaker than the
word suggests: **an import contract is a net, not a proof.** It matches module
names, so it cannot see a subsystem reaching the network through `urllib`, a raw
socket, a library added after the contract was written, or an internal wrapper.
What it reliably catches is the realistic accident — `httpx` appearing in
`memory/` — not a determined bypass. The enforcement this ultimately wants is an
injected transport capability only designated boundaries hold (issue #85, and §8
below on why it is not adopted now).

### 5. Why a superseding ADR rather than an in-place amendment

ADR-0001 reserves changing a past decision to a new ADR that supersedes the old
one and updates its status. Nothing grants an exception. CONTRIBUTING's "trivial
ADRs (amendments, status changes, supersedes) skip both the separate PR and the
review" is about **review cost** — which ceremony a change warrants — not
authority to change a decision in place. It never claimed the power ADR-0001
reserves, so there is no conflict between the documents: the authority was never
granted.

This does change a decision. An earlier draft argued that ADR-0004 is internally
inconsistent as ratified, so resolving it merely determines what was decided.
That is sound as far as it goes, and it is why the contradiction is worth fixing
at all. But this ADR also designates a new boundary, closes the list, and forces
corrections to ADR-0006 and ADR-0016. A change that ripples into two other
ratified ADRs is decision-shaped, not editorial.

### 6. The prior amendment's declining clause

ADR-0004 §2's configured-set amendment closes by declining exactly this
widening — "the amendment widens *which* providers are legitimate recipients,
not *which components* may transmit. `models/` remains the only one."

That sentence is **left exactly as ratified**, with a dated note appended at the
end of ADR-0004 §2 rather than any edit to it. It does two jobs: as a record of
what that amendment did and deliberately declined to do, it is accurate and
worth preserving — a reader should see the component prohibition was examined
and left standing on that date, not overlooked. As a statement about the rule
this ADR proposes, it would be out of date on acceptance. Rewriting it would
erase the first to fix the second.

### 7. What happens to ADR-0004 on acceptance

ADR-0001 requires the superseded ADR's status to change, not merely gain a note.
While this ADR is `Proposed`, ADR-0004 is untouched and its §2 is the live rule.
**On acceptance**:

- **Edit exactly one line:** ADR-0004's `Status` becomes `- Status: Accepted,
  partially superseded by ADR-0017 (§2's egress clause)`. That is the status
  update ADR-0001 requires and the only edit it authorises. The form follows the
  precedent ADR-0018 set for ADR-0016; a second ADR inventing a second format is
  how a vocabulary stops being one. Its weakness — anything matching a leading
  `Accepted` misses the qualifier — is issue #87's to settle repo-wide.
- **Append, do not rewrite, everywhere else.** The dated notes in ADR-0004's
  header and §2 stay as merged, still reading "proposed", because that is what
  was true when written. Acceptance adds a new dated note beside each.
- **Nothing else moves.** ADR-0004 §2's text, the configured-set amendment, and
  the notes in ADR-0006 and ADR-0016 remain as written.

### 8. Rejected alternative: a dedicated injected egress capability

The stronger enforcement is an outbound-transport capability in `core`, injected
into the boundaries allowed to use it, so a subsystem never handed it cannot
connect regardless of what it imports — testable, contract-based, and squarely
golden rule 1. Deferred, not dismissed:

- **It does not fit `models/`.** Provider SDKs open their own sockets, so the
  capability could not cover the one boundary transmitting today. A rule
  enforced at one boundary and not the other is roughly what import contracts
  already give, at much higher cost.
- **Its shape depends on the invocation contract that does not exist** —
  ratifying it now would bless a seam with no implementation contact.
- **The decisions are independent.** Which boundaries may transmit, and what
  enforces that, are separate questions; settling the first unblocks the
  invocation ADR and the second can land later without reopening it.

Issue #85.

### 9. What is not decided here

Tool egress becomes *permissible in principle*; no particular tool, destination
or payload is authorised, and by itself nothing transmits. Also out of scope and
tracked: how outbound content is classified by provenance, including Tier 0 a
user typed into a conversation (issue #94); the detailed invocation obligations
(#93); and ADR-0004 §7's minimisation rule, which is written about the model
provider and stays as scoped — the equivalent obligation on tool payloads is
imposed by §3 rather than read into §7.

## Consequences

- **ADR-0004 §2's egress clause is superseded on acceptance**, not before, per
  §7. Everything else in ADR-0004 stands.
- **ADR-0006 §2 and ADR-0016 keep their ratified wording**; each gains a dated
  note. ADR-0006 §2 said cloud embedding is "like all egress, confined to the
  `models/` layer" — a passing restatement of ADR-0004 §2 that would otherwise
  have left two ratified ADRs asserting incompatible egress rules. ADR-0016's
  Consequences bullet recording that ADR-0004 §2 "still reads as forbidding all
  tool egress" gains a note pointing here. Neither decision changes and neither
  sentence is rewritten: ADR-0001's append-only rule permits a status update and
  an appended note, not an edit to accepted text.
- **The import-linter contract ADR-0004's Consequences provision for is now
  load-bearing** and only partly written (issue #66). For `models/` that is
  debt; for `tools/` the module-pinning contract is a §3 condition, because
  there it is what gives the approval a concrete extent.
- **The invocation ADR inherits the complete §3 list**, not a summary, and a
  later ADR ratifies the designation. It no longer inherits a prohibition it
  would have had to overturn on its way.
- **`tools/` still transmits nothing.** No behaviour changes on ratification.
- **ADR-0004's configured-set amendment remains an in-place amendment**, which
  §5's strict reading makes retroactively irregular. Deliberately left as-is —
  the pattern is fixed forward, not retrofitted. Issue #71.
