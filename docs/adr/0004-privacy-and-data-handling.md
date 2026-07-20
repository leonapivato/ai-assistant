# 4. Privacy and data handling

- Status: Accepted
- Date: 2026-07-16
- Amended: 2026-07-19 (§2 — egress is permitted to the user-configured *set* of
  model providers, not exactly one, enabling ADR-0013 routing; see the amendment)
- Amended: 2026-07-19 (§2 — egress is permitted from *designated, declaring,
  gated* boundaries rather than from `models/` alone, admitting the `tools/`
  integration boundary the rest of this ADR already provisions for; see the
  amendment. This one supersedes the closing clause of the amendment above.)

## Context

The assistant's value comes from knowing its user deeply: goals, routines,
relationships, communication style, and — via tool integrations — access tokens
for calendars, email, GitHub, messaging, and smart-home devices. That makes the
data it holds among the most sensitive a person owns. Trust is a core product
pillar (see `README.md`), and `memory/`, `tools`, and `permissions` all depend
on how we classify, store, protect, and expose this data. We need a ratified
policy before those subsystems are built, rather than retrofitting one.

ADR-0002 already commits us to a **local-first** architecture (SQLite by
default) and confines model access to the `models/` layer. This ADR builds the
data-handling rules on top of that foundation.

## Decision

### 1. Data classification

Every piece of stored data is one of three tiers, and its tier determines how it
is handled:

- **Tier 0 — Secrets/credentials:** OAuth tokens, API keys, refresh tokens.
- **Tier 1 — Personal data:** user-model facts, memories, conversation history,
  anything identifying the user or third parties (PII).
- **Tier 2 — Operational:** non-sensitive settings, caches, logs (which must
  never contain Tier 0/1 data — see §5).

### 2. Residency and egress (local-first, minimal egress)

- All persistent data lives on the user's machine, under a single
  platform-appropriate data directory (resolved via `platformdirs`, e.g.
  `~/.local/share/ai-assistant/` on Linux). No cloud storage by default.
- The **only** component permitted to send user data off-device is the
  `models/` layer, and only to the model provider the user has configured.
  Every other egress is a bug. (Both absolutes here reflect the codebase of
  the time — a single-adapter `models/` and no tool layer. See the
  **Amendments** below: the first reads "the model provider" as the configured
  *set*; the second replaces "the only component" with a designated set of
  egress boundaries.)
- **Telemetry is off by default and there is no data egress for
  observability.** pydantic-ai's `logfire-api` is a no-op unless Logfire is
  explicitly installed and configured; instrumentation that transmits data
  requires a documented, opt-in setting.

**Amendment (2026-07-19): "the model provider" becomes the configured set.** The
egress rule above was written when `models/` held a single adapter and no way to
choose between providers. Its wording — "only to **the** model provider the user
has configured" — therefore reads as *exactly one*. ADR-0013 adds routing and
fallback, where a failure at one provider re-sends the conversation (Tier 1) to
the next candidate, which that wording forbids.

The rule is amended to: **user data may be sent only to model providers the user
has explicitly configured.** Singular becomes a set; nothing else changes.

The property this ADR is protecting is *minimal egress to endpoints the user
chose*, and that is untouched — "explicitly configured" carries the same weight
for the fifth provider as for the first. What the original wording additionally
implied, accidentally, was a cardinality limit, and no argument in this ADR
supports one: §2's rationale is about **who** receives data, never **how many**.

Constraints that make the plural safe live in **ADR-0013 §6** and are binding
here:

- A route list may contain only providers the user explicitly configured;
  fallback is not permission to reach a provider the user never chose.
- `RoutingProvider` never acquires a provider — it receives fully-constructed
  ones by injection, so it cannot widen the set of reachable endpoints, only
  re-send to one already wired in. The obligation therefore falls on whoever
  composes the pipeline (`orchestration`).
- A configured route must require its own credential, so a provider the user has
  not set up cannot become a silent fallback.

**Accepted cost.** A user who configured a fallback and then forgot may not
expect a prompt to reach it during an outage. Which provider answered a request
is not currently surfaced anywhere; ADR-0013 §6 records that as an open gap to
close once there is an interface to report it. Until then the mitigation is that
every provider in a route list is one the user deliberately configured and
credentialed.

**Scope.** This amends the wording of §2 only. §1 (tiers), §3 (secrets), §4
(encryption at rest), §5 (logging and redaction) and §6 (data rights) are
unchanged, and "every other egress is a bug" still holds — *this* amendment
widens *which* providers are legitimate recipients, not *which components* may
transmit. At this date `models/` remained the only one. [**Superseded in part**
by the egress-boundaries amendment below, which widens exactly the axis this
paragraph declined to touch. The sentence stands as the record of what *this*
amendment did and did not do; only its claim about the current state of the
rule is out of date.]

**Amendment (2026-07-19): egress boundaries — `models/` is not the only one.**
The rule above names `models/` as the *only* component permitted to transmit and
calls "every other egress" a bug. That was written when `models/` was the only
subsystem in the repository with a reason to open a socket. The rest of this
same ADR already plans for a second: §3 has `tools/` reading credentials for
external services through `SecretStore`, §7 gates "every side-effecting tool
call" — which for an integration layer overwhelmingly means calling a remote
service — and the Consequences provision for "the designated `tools/`
integration boundary" importing network clients alongside `models/`. A tool
layer that may hold a calendar token but may not reach the calendar is not a
design; it is a contradiction the ADR has been carrying since it was ratified.

The rule is amended to: **user data may leave the device only from a boundary
this ADR designates for egress, and only where that boundary declares what it
transmits and is gated before it transmits.** Two boundaries are designated
today:

- **`models/`** — to model providers the user has explicitly configured (per
  the amendment above).
- **the `tools/` integration boundary** — to external services the user has
  explicitly connected, per tool and per call.

Egress from anywhere else is still a bug, and adding a third designated
boundary requires amending this section again — it is a closed list, not a
category a subsystem can argue its way into.

**Why this preserves what §2 protects.** The prior amendment found that §2's
rationale is about **who** receives data, never **how many**. The equivalent
line for components is that §2's rationale is about egress being **accountable**
— few, named, and answerable for what it sends — never about the number of
places that are accountable. "One" was never argued for anywhere in this ADR; it
was a count of the subsystems that existed. What the ADR actually argues for,
here and in §7, is that data must not leave from somewhere nobody designated,
in a quantity nobody declared, without a check nobody ran. A second boundary
costs that property nothing as long as it meets all three conditions, and the
`tools/` boundary is held to all three:

1. **Designated.** The boundary is named here and enforced mechanically, not by
   convention: the import-linter contract this ADR's Consequences already
   provision for permits network/provider clients in `models/` and the
   designated `tools/` integration boundary and nowhere else. Egress stays an
   enumerable list a reader can audit by grepping one contract.
2. **Declaring.** Every tool states, as a required and fail-closed property of
   its definition, which data tiers a call transmits off-device (ADR-0016 §3).
   This is the condition `models/` gets for free and `tools/` cannot: what
   `models/` sends is homogeneous and obvious — the prompt — whereas tool egress
   is heterogeneous, so it must be *stated* rather than inferred from the
   integration's name. A tool whose author does not say what leaves cannot be
   defined at all.
3. **Gated.** §7 already requires that every side-effecting tool call pass
   `permissions/` and land in the audit trail, and a tool that transmits is
   side-effecting by construction (ADR-0016 §3). Every byte leaving through
   `tools/` is therefore approved and recorded per call.

Honest accounting: condition 1 is a genuine widening, and this amendment does
not pretend otherwise — a second exit point is a second thing that can be got
wrong, and mechanical enforcement of the contract in condition 1 is what keeps
"designated" from decaying into "whatever imported `httpx`". Against that, the
`tools/` boundary is *more* constrained than the one §2 was written to describe:
`models/` egress is neither declared per call nor gated per call, while tool
egress is both. The amendment does not lower the bar to admit `tools/`; it
writes down the bar `models/` was implicitly clearing and finds that `tools/`
clears a higher one.

**Why amend rather than supersede.** The contradiction is confined to one
clause of one bullet. Every other clause of §2 — local-first residency, minimal
egress, telemetry off by default — is unchanged and still correct, and a new
ADR superseding §2 would have to restate all of it to fix a phrase. Nor is the
tool layer's egress a new decision this ADR never made: §3, §7 and the
Consequences made it. This amendment reconciles §2's wording with the rest of
its own text rather than deciding anything new.

**Reconciling the prior amendment.** The configured-set amendment closes by
declining exactly this widening — "the amendment widens *which* providers are
legitimate recipients, not *which components* may transmit. `models/` remains
the only one." That sentence has been annotated in place rather than rewritten
or deleted, because it is doing two different jobs. As a scope statement about
what *that* amendment did, it is accurate and worth preserving: a future reader
should be able to see that the component prohibition was examined and
deliberately left standing on that date, not overlooked. As a statement about
the current rule, it is now false. Rewriting it would erase the first to fix
the second, and an ADR is an append-only record of what was decided when.
The annotation therefore marks only the stale clause, and this amendment is
where the decision to widen is argued and recorded.

**What is not decided here.** This amendment authorises egress from `tools/`;
it does not authorise any particular tool, destination, or payload.
Destination-level policy — which recipients are approved — remains parameter-
level and deferred (ADR-0016 §7, issue #57 for per-call reach). Nor does it
weaken §7's minimisation rule: "send the minimum necessary" now reads against
both designated boundaries. The invocation ADR still owes the rules that decide
which declared disclosures `permissions/` grants; what it no longer owes is a
prior amendment permitting the category to exist. Discharging that precondition
(ADR-0016 §7) is this amendment's only purpose.

**Scope.** This amends the wording of §2 only, and supersedes the final clause
of the configured-set amendment above. §1 (tiers), §3 (secrets), §4 (encryption
at rest), §5 (logging and redaction), §6 (data rights) and §7 (permissions,
audit, minimisation) are unchanged. No component gains egress by
implication: only the two boundaries listed above are designated, and both
remain subject to every other rule in this ADR.

### 3. Secrets/credentials (Tier 0)

- Tier 0 secrets are stored in the **OS keyring** via the `keyring` library —
  never in the memory database, never in a committed file. `.env` is for local
  developer convenience only and is git-ignored.
- The `models/` and `tools/` layers read credentials through a small
  `SecretStore` Protocol (added to `core/protocols.py`) so the keyring backing
  can be faked in tests and swapped per platform.

### 4. Encryption at rest (Tier 1)

- The memory database is created with owner-only file permissions (`0600`) in
  the user's data directory.
- **Baseline** protection assumes the host uses OS full-disk encryption; this
  assumption is documented for the user.
- **Application-level encryption of the memory store is supported and
  configurable** (via SQLCipher), with the key held in the OS keyring. It is
  **off by default** and opt-in: for a single-user local app the baseline
  (OS full-disk encryption + `0600` perms) is adequate, and default-on
  encryption would impose real key-management/recovery burden (a lost key means
  unrecoverable memory). Users who cannot rely on disk encryption can enable it.

### 5. Logging and redaction

- Logs are Tier 2 only. Tier 0/1 data must never be logged.
- structlog is configured with a redaction processor that drops/masks known
  sensitive keys (tokens, secrets, message bodies, PII fields) as a safety net;
  redaction failing closed is preferred over leaking.

### 6. User data rights (retention, export, deletion)

- The user can **view, export, and delete** their data. `memory/` exposes
  export (portable JSON) and delete operations from day one.
- Memory supports **retention rules** (e.g. TTLs, size caps) so data does not
  accumulate indefinitely; specifics are set per memory type when `memory/` is
  designed.
- Deleting the user's data purges Tier 0 (keyring entries) and Tier 1 (database
  rows) together.

### 7. Permissions, audit, and minimization

- Access to Tier 0/1 data and every side-effecting tool call is gated by the
  `permissions/` layer and recorded in an **audit trail**, making the
  assistant's behaviour transparent and reviewable (a Tier 1 store itself).
- **Data minimization:** collect and store only what a capability needs, and
  send the minimum necessary context to the model provider. Prefer references
  over copies where practical.

## Consequences

- New dependencies when the relevant subsystems land: `keyring` (Tier 0) and,
  if application-level encryption is adopted, a SQLCipher binding — each with a
  fake for tests.
- `core/protocols.py` gains a `SecretStore` Protocol; `memory/` must implement
  export/delete/retention and owner-only file permissions; `tools/` must read
  credentials only via `SecretStore`; `permissions/` owns the audit trail.
- We will add an import-linter contract asserting that only `models/` (and the
  designated `tools/` integration boundary) imports network/provider clients, so
  the minimal-egress rule is mechanically enforced like the other boundaries.
- Application-level encryption remains available but off by default; users
  relying on it accept that a lost keyring key means unrecoverable memory.
- Building for user data rights (export/delete/retention) from the start is
  cheaper than retrofitting them into a populated store later.
