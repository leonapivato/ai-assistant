# 4. Privacy and data handling

- Status: Accepted
- Date: 2026-07-16
- Amended: 2026-07-19 (§2 — egress is permitted to the user-configured *set* of
  model providers, not exactly one, enabling ADR-0013 routing; see the amendment)
- Superseded in part: 2026-07-19 by **ADR-0017**, which replaces §2's egress
  clause ("the **only** component permitted…") with a designated set of egress
  boundaries, admitting the `tools/` integration boundary the rest of this ADR
  already provisions for. **§2's egress clause below is no longer the live
  rule — read it with ADR-0017.** Everything else here stands: §1, §§3–7, §2's
  residency and telemetry clauses, and the configured-set amendment above.

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
  the time — a single-adapter `models/` and no tool layer. Neither is the live
  rule: the **Amendment** below reads "the model provider" as the configured
  *set*, and **ADR-0017** replaces "the only component" with a designated set
  of egress boundaries.)
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
by **ADR-0017**, which widens exactly the axis this paragraph declined to
touch. The sentence stands as the record of what *this* amendment did and did
not do — the component prohibition was examined here and deliberately left
standing — and only its claim about the current state of the rule is out of
date. ADR-0017 §6 explains why it is annotated rather than rewritten.]

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
