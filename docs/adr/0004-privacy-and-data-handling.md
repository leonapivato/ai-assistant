# 4. Privacy and data handling

- Status: Accepted, partially superseded by ADR-0017 (§2's egress clause), ADR-0124 (§6's delete clause and §7's gating clause, each only as it reaches a device the owner has enrolled), ADR-0125 (§3's reader clause) and ADR-0126 (§6's Tier 0 purge clause as it reaches a credential held outside the keyring, and §7's gating clause, each only for the offline whole-installation delete)
- Date: 2026-07-16
- Amended: 2026-07-19 (§2 — egress is permitted to the user-configured *set* of
  model providers, not exactly one, enabling ADR-0013 routing; see the amendment)
- Partially superseded: 2026-08-09 by ADR-0124 — **two clauses, each narrowly, and
  both because a second machine now exists.** ADR-0124 ratifies the hop off the
  device: the hub may serve a client on another device the owner enrolled, and the
  hub may not dial that device.

  **Replaced — §6's delete clause, only as it reaches an enrolled device.**
  "Deleting the user's data purges Tier 0 (keyring entries) and Tier 1 (database
  rows) together." That was written when one machine held everything. An enrolled
  device holds a Tier 0 credential in its own keyring, and a delete performed at
  the hub cannot reach it. In its place ADR-0124 §8 puts an **unenrolment act at
  the device** that purges that device's entry and needs no hub, a **hub-side
  delete that revokes every enrolment** so no device is left holding a credential
  to a store that is gone, and an obligation that the delete surface **report the
  devices it could not purge** rather than presenting itself as complete.
  Everything else §6 grants — view, export, delete, retention rules, and the purge
  of every Tier 0 and Tier 1 artifact on the hub's own machine — is untouched.

  **Replaced — §7's gating clause, only for a client's bootstrap credential
  read.** "Access to Tier 0/1 data and every side-effecting tool call is gated by
  the `permissions/` layer and recorded in an **audit trail**." A client reads its
  credential in order to reach the hub, and `permissions/` and the audit trail live
  behind that connection, so the gate is circular for that one read and for no
  other. ADR-0124 §6 exempts exactly it, against three replacements it requires
  together: the read is confined to one purpose and one path; custody is the
  operating system's own control on the keyring, the mechanism §3 below already
  chose; and every *use* of the credential is recorded at the hub, admissions and
  refusals alike. ADR-0124 states plainly that these are weaker than §7 — an OS
  prompt is custody rather than a policy decision about this access, and a device
  that reads the credential and never connects leaves no trace anywhere.

  **Not replaced — everything else, which is nearly all of it.** §1's tiers; §2's
  residency and telemetry clauses, ADR-0124 §3 finding every sentence of both still
  true and sending the residual question about residency's *intent* to **#95**;
  §3's keyring rule, which ADR-0124 §6 applies rather than narrows and to which it
  adds a third `SecretStore` consumer as a stacked addition; §4's at-rest posture;
  §5's redaction; §6's other rights; and **§7's minimisation clause and its gate
  over every other Tier 0 and Tier 1 access**, on the hub and on the device alike.
  ADR-0124 forbids citing its exemption to widen it to a second access. #74, which
  asks whether §7's gate reaches the model provider credential, is untouched and
  stays open on that subject.
- Partially superseded: 2026-08-09 by ADR-0125 — **one clause, and it is about
  which Protocol a reader is handed rather than about the keyring.** ADR-0125
  declares the `SecretStore` Protocol §3 provisions and has never had, splitting
  the seam into a reading face and a writing one.

  **Replaced — §3's reader clause.** "The `models/` and `tools/` layers read
  credentials through a small `SecretStore` Protocol (added to
  `core/protocols.py`) so the keyring backing can be faked in tests and swapped
  per platform." Those two layers only read, so ADR-0125 §8 hands them `Secrets` —
  the reading face — and states that neither holds `SecretStore`. A reader holding
  only §3 would wire them with the wider Protocol, which is ADR-0070 §1's first
  limb. The sentence's stated purpose is carried unchanged: `Secrets` is in
  `core/protocols.py`, is fakeable in tests, is swappable per platform, and is the
  only path either layer has to the keyring. What the split buys is that a layer
  which only reads cannot overwrite or delete the credential it reads.

  **Not replaced — everything else of §3, which is the part with the teeth.** Tier
  0 secrets still live in the OS keyring via the `keyring` library, never in the
  memory database and never in a committed file; ADR-0125 §7 applies that rule by
  forbidding any fallback to a file, an environment variable or a backend without
  the operating system's own access control, and requiring a visible refusal
  instead. §3's third consumer, the stacked addition ADR-0124 §12 recorded, is
  untouched and ADR-0125 adds no fourth — its scope enum is closed at three, so a
  fourth consumer owes its own ADR. §1's tiers, §2's residency and telemetry
  clauses, §4's at-rest posture, §5's redaction, §6's rights and §7 are all
  untouched: ADR-0125 §9 states that it gates nothing, discharges no ADR-0017 §3
  condition, and does not widen ADR-0124 §6's exemption. **#74 stays open on its
  own subject**, and ADR-0125 §8 records that the existing environment read of the
  provider key is pre-existing and not authorised by it.
- Partially superseded: 2026-08-10 by ADR-0126 — **one clause, one act, and the
  act is the one that gives §6's delete right a surface.** ADR-0126 rules that
  "deleting the owner's data at the hub" is the destruction of the contents of
  `Settings.data_dir`, performed by an offline console entry point in `service/`
  under the hub's instance lock with the hub stopped.

  **Replaced — §6's Tier 0 purge clause, only as it reaches a credential held
  outside the keyring.** "Deleting the user's data purges Tier 0 (keyring entries)
  and Tier 1 (database rows) together." §1 defines Tier 0 by what a value *is* —
  "OAuth tokens, API keys, refresh tokens" — and the parenthetical "(keyring
  entries)" is §3's assumption rather than §6's scope. On the hub's machine today
  that assumption does not hold for one value: the model provider credential the
  provider SDK reads from the process environment, which ADR-0125 §8 records as
  pre-existing and not authorised by it and which **#74** is open on. The act
  cannot reach a shell profile this system did not write, so ADR-0126 §6 requires
  it to **name that credential as not purged** and to name the act at which the
  owner removes it, and forbids it describing Tier 0 as purged. This is the same
  instrument ADR-0124 §8 used on this same sentence for an enrolled device's
  keyring entry — one unreachable custodian, named to the owner rather than
  silently missed — and it is **self-limiting**: it lapses for any credential a
  later lane moves into the keyring under §3, and authorises no new credential to
  be held outside one. **#909** carries the separate question of how a hub-side
  delete would reach a keyring entry at all, given that ADR-0125 §5 puts the
  deletion path on the consumer and §8 keeps `service` out of the seam.

  **Replaced — §7's gating clause, only for that act.** "Access to Tier 0/1 data
  and every side-effecting tool call is gated by the `permissions/` layer and
  recorded in an **audit trail**." Both halves are structurally unavailable to it:
  `permissions/` runs inside the hub and this act requires the hub stopped, and the
  audit trail is `<data_dir>/audit.db`, a file the act destroys — so a record of the
  act would be written into the thing being removed. ADR-0126 §11 puts three
  replacements in its place, and an implementation that omits any of them does not
  have the exemption: the act is confined to one purpose and one path; custody is
  the operating system's own control on an owner-only data directory and on the
  instance lock; and the owner confirms against the resolved path before anything
  is destroyed.

  **The audit residue is forbidden rather than merely absent, and that is why this
  is a supersession rather than an unmet obligation.** A durable record saying the
  owner destroyed everything is Tier 1 data about the owner surviving in a system
  they asked to hold nothing — §6's purge and §7's record cannot both hold for the
  act that empties the installation, and ADR-0126 §11 rules that the one giving way
  is the one whose purpose is to make *later* accesses reviewable.

  **Not replaced — everything else, which is nearly all of both sections.** §7's
  minimisation clause; §7's gate over every other Tier 0 and Tier 1 access, in the
  hub, in the other offline tools and on every device; §1's tiers; §2, §3, §4 and
  §5. And nearly all of §6: the user can still view, export and delete, `memory/`
  still exposes both, retention rules stand, and the act performs the purge of
  every Tier 1 artifact on the hub's own machine and of every Tier 0 artifact that
  is in the keyring — which today is none, because nothing writes one there yet.
  ADR-0126 §11 states that it does not cite, rest on or widen ADR-0124 §6's
  exemption, which stays confined to a client's bootstrap credential read; **#74**
  is untouched and this ADR's §3 keyring rule is applied rather than narrowed.
- Note (2026-07-20): **§2's egress clause is superseded by ADR-0017.** That
  clause named `models/` the only component permitted to send user data
  off-device; ADR-0017 §1 replaces it with `models/` plus a designated
  integration seam inside `tools/`. This is a note, not a status — the `Status`
  line above is this ADR's only status field. Everything else here stands: §1,
  §§3–7, and §2's residency and telemetry clauses. See the note at the end
  of §2.
- Note (2026-07-26): §2's configured-set amendment (2026-07-19, an in-place
  amendment) predates ADR-0070's amend-vs-supersede test and is left as-is — it
  is **not precedent** for in-place decision changes, which ADR-0070 §1 now
  governs. Retrofitting it would itself violate append-only (ADR-0070
  Consequences; issue #71). Appended note, not a status change.

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
  Every other egress is a bug. (Singular here reflects the single-adapter
  `models/` of the time; see the **Amendment** below, which reads this as the
  configured *set*.)
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
unchanged, and "every other egress is a bug" still holds — the amendment widens
*which* providers are legitimate recipients, not *which components* may transmit.
`models/` remains the only one.

**Note (2026-07-20) — §2's egress clause is superseded by ADR-0017.**
Appended without altering anything above it. The clause above is **no longer
the live rule**: user data may leave the device from `models/` or from a
designated integration seam inside `tools/`, per **ADR-0017 §1**. ADR-0017
argues that the clause contradicted the tool layer §3, §7 and this ADR's
Consequences already provision for. Read the clause above as the historical
rule and ADR-0017 for the current one.

Two things this does not change. `tools/` transmits nothing today — its seam is
approved in principle and stays undesignated until ADR-0017 §3's conditions
hold in code and a later ADR ratifies that they do. And the configured-set
amendment's closing sentence ("`models/` remains the only one") stands as
written, an accurate record of what that amendment decided and deliberately
declined to decide; ADR-0017 §6 explains why it is annotated rather than
rewritten.

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
