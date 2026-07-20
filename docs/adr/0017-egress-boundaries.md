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

- **Approved** — this ADR permits the boundary to transmit. The list of
  approved boundaries is closed; adding a third requires another ADR.
- **Designated** — approved *and* concretely identified: a named module, pinned
  by the import-linter contract, so "which code may open a socket" has a
  mechanical answer. Only a designated boundary may actually transmit.

`models/` is **designated** on acceptance — it is an existing package and the
contract can name it today. The `tools/` seam is **approved but not yet
designated**: no module exists to name. It becomes designated when the
integration ADR names the seam and the contract pins it (§3, issue #66) — a
mechanical activation, not a further decision about whether tool egress is
permitted. Until then `tools/` transmits nothing, and enforcement tooling
should read the approved-but-undesignated state as "still prohibited".

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
    (ADR-0004 §3).

  That list *is* the declaration, and it is exhaustive: a payload class not
  listed here is not authorised at this boundary, and adding one — multimodal
  attachments, tuning corpora, anything else — requires amending this ADR.

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
  authorisation is **per call**, through `permissions/`. Both are stronger than
  `models/`, and necessarily so: `models/` has one payload class and one
  purpose, while tool egress is heterogeneous, so nothing about it can be
  inferred from the boundary itself.

  What is approved is a *named module seam inside* `tools/`, not the package:
  `tools/` also owns tool definitions and the registry, and neither has any
  business holding a network client. Which module is the seam is the
  integration/invocation ADR's to name, and it must be named there precisely
  enough for the import-linter contract to pin that module rather than the
  package (issue #66). Naming it is what turns this approval into a
  designation; until then the approval has no concrete extent and nothing
  under `tools/` may transmit.

Egress from anywhere else is a bug, and adding a third approved boundary
requires a further ADR — it is a closed list, not a category a subsystem can
argue its way into.

### 3. This ADR is not self-executing

It removes a categorical prohibition; it does not make any transmission legal.
The conditions in §4 are preconditions on the *first byte* that leaves through
`tools/`, not properties this ADR asserts are already in place. Today none is
fully discharged, and no egress from `tools/` is permitted. What must exist
first:

- the named seam and the import-linter contract pinning it (§4 condition 1,
  issue #66);
- a ratified invocation contract that gates each call through `permissions/`
  and records it in the audit trail *before* the call transmits, rather than
  relying on the definition's declared ceiling alone (§4 condition 3);
- the destination and per-call payload rules — a tool's declared reach is a
  *ceiling* over tiers, not proof that a given call's actual recipient and
  actual bytes were approved (ADR-0016 §3, §7; issues #57, #68).

A boundary that meets the conditions in a document but not in the code is
approved, not designated, and an approved boundary does not transmit. If the
invocation ADR cannot supply all three, `tools/` does not get to transmit on
the strength of this ADR.

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

1. **Designated.** The boundary is named here and enforced mechanically, not by
   convention: the import-linter contract ADR-0004's Consequences already
   provision for permits network/provider clients in `models/` and the
   designated `tools/` seam once it exists, and nowhere else. Egress stays an
   enumerable list a reader can audit by grepping one contract.
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
   Every byte leaving through `tools/` is therefore approved and recorded per
   call — again more than `models/`, whose recipients the user authorises once
   by configuring them.

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
  load-bearing** and still unwritten. Until it exists and pins a named module,
  "designated" is a claim in a document rather than an enforced property
  (issue #66).
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
