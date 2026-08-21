# 172. A browser holds its web session outside the keyring, and its admission is recorded in place of a gate

- Status: Proposed
- Date: 2026-08-21

- **This is the prerequisite ADR-0168 §6 names**, for `track:web-client`
  milestone 13 (#1230). ADR-0168 ruled the gateway seat and the web session, found
  ADR-0004 §3 and §7 engaged by it, and made "one narrowly scoped supersession
  covering both" a prerequisite of the implementing lane — its own ADR, merged
  before any gateway ships. This is that ADR, and it is the whole of what
  discharges that clause.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` and no `core/types.py` surface**, so golden
  rule 5 is not triggered. It adds no `Settings` field either — ADR-0168 §8
  already names the ten this milestone owes, and this ADR adds no eleventh.
- **It partially supersedes ADR-0004 three times, each narrowly** — §3's keyring
  clause (§2), §6's Tier 0 purge clause (§4) and §7's gating clause (§3), each
  only as it reaches the web-session credential class §1 defines. One record
  carrying all three lands on ADR-0004 in this same change (ADR-0070 §1,
  ADR-0082 §1, ADR-0083 §15). §8 below applies ADR-0070 §1's test clause by clause
  to every other ADR a reader might expect this to reach, and finds no further
  record owed.
- **ADR-0168 §6 named two of those clauses and not the third.** §6 is engaged
  because §2 authorises a Tier 0 credential that lives outside the keyring and
  outlives no gateway — so a delete at the hub cannot reach it, exactly as
  ADR-0124 §8 and ADR-0126 §6 each found for a different unreachable holder. The
  engagement is created by this ADR's own ruling, and ADR-0070 §1 is categorical
  that creating it is what obliges the record; leaving it engaged and unmet is the
  instrument ADR-0124 §6 refused. §4 carries the argument and names why ADR-0126's
  supersession of the same sentence does not extend to this class.
- **It rules the one question ADR-0168 §6 left to this lane by name**: whether a
  successful Tier 0 read on the admission path is recorded. **It is not** (§5),
  and the reason is not that the record costs too much — it is that the record
  cannot distinguish the case it would exist to reveal.

## Context

### What ADR-0168 decided, and the one thing it deliberately did not write

ADR-0168 put the browser behind a **gateway**: an ordinary spoke of the client
profile that enrols as a device, reaches the hub over ADR-0084's framed wire, and
binds a **loopback TCP** listener for browsers on its own machine. A browser
cannot be enrolled under ADR-0124 §6 — it has no keyring, no `SecretStore` and no
overlay identity — so the gateway is an **amplifier**: it holds one device
credential and answers whoever reaches its port with the device's whole
authority. ADR-0168 §3 and §4 are the control for that: a **web session** the
gateway mints, holds in process memory, and destroys when its process ends, and
which is the only thing that admits a browser request.

ADR-0168 §6 makes a session **two values** — a `HttpOnly` cookie half and a
header half the front end holds in origin-scoped browser storage — because a
cookie is scoped to a host and not to a port, so one value alone would be
presented to any other local service on `127.0.0.1`. It then classifies both
halves and the single-use bootstrap value as **Tier 0 under ADR-0004 §1**, and
declares two of ADR-0004's clauses engaged:

- **§3**, because the values are held by the browser rather than in the OS
  keyring; and
- **§7**, because the gateway reads and verifies them on the admission path,
  which `permissions/` cannot gate and the hub's audit trail does not record.

**A third clause is engaged that ADR-0168 did not name, and it is engaged by this
ADR rather than by that one.** Once §2 below authorises a Tier 0 credential
outside the keyring, §6's purge clause has a holder no delete act at the hub can
reach — the same discovery ADR-0124 §8 and ADR-0126 §6 each made about a different
custodian. §4 carries it.

ADR-0168 wrote neither supersession. It could not: nothing implements there, so
nothing ran unmet in the interval, and the corpus's ordinary shape for a
dependent ratified decision is a separate change merged first. What it did
instead was name the replacements the writing lane should start from, and hand
that lane one open question with both halves of it visible. This ADR takes both.

### What ADR-0004 §3 and §7 actually say

§3's first bullet is the one this reaches:

> Tier 0 secrets are stored in the **OS keyring** via the `keyring` library —
> never in the memory database, never in a committed file. `.env` is for local
> developer convenience only and is git-ignored.

§3's second bullet — the `SecretStore` reader clause — was already replaced by
ADR-0125 §8 and is untouched here (this ADR's §8 classifies it).

§7's first bullet:

> Access to Tier 0/1 data and every side-effecting tool call is gated by the
> `permissions/` layer and recorded in an **audit trail**, making the
> assistant's behaviour transparent and reviewable (a Tier 1 store itself).

§7's second bullet — data minimisation — is untouched.

### What the tree has, so the supersession speaks about something real

Both clauses are implemented, and neither implementation has a subject inside a
browser.

`secret_store/` is a leaf package holding one class. `KeyringSecretStore`
composes an injective, length-prefixed coordinate — `_coordinate` builds
`service` from the installation and the `SecretScope`, and `username` from the
name's key — and calls the `keyring` library on a thread. `select_backend`
(`secret_store/backend.py`) admits only a backend whose module lies under one of
five prefixes in `PROTECTED_BACKEND_MODULES`, expanding chains so a wrapper
cannot smuggle a plaintext backing through, and raises `SecretStoreUnavailableError`
for anything else. **There is no fallback path at all** — not a file, not an
environment variable, not an in-memory map. That is ADR-0125 §7 in code, and it
is why §3's rule cannot simply be *applied* to a browser: there is no admissible
backend on the browser's side of the wire, and the code is right to have none.

`permissions/` is the other half. `ThresholdActionPolicy` decides an
`ActionRequest` as a pure function of the tool it names; `SqliteAuditTrail` is
the Tier 1 store the ruling is recorded on, opened by the hub at
`<data_dir>/audit.db` (`app/composition.py` builds it from the resolved data
directory) with owner-only permissions set before the first statement. Both live
inside the hub process, under ADR-0083's exclusivity. Nothing outside that
process reaches either store; what an enrolled device reaches is the
permission-shaped *operations* on `AssistantEngine` — `pending_confirmations`,
`resume`, `grant`, `revoke` — never the trail itself.

And the browser-facing half does not exist yet. `interfaces/` holds one adapter,
the CLI; there is no HTTP server anywhere in `src/`, no `gateway_*` field in
`core/config.py`, and nothing a browser could speak to. The tree does bind one
TCP listener — `service/remote.py`'s overlay listener, off by default, refused at
settings load unless its address is an overlay address and refused at bind unless
the local agent attests it — so the accurate statement is not "nothing binds a
TCP port" but that **nothing binds one a browser can reach**, which is exactly the
door ADR-0168 §2 authorises and this ADR provisions the credential for.

### Why no browser design escapes either clause

This is ADR-0168 §6's finding and it is worth restating, because the instinct on
reading a supersession of a privacy floor is to look for the design that would
not have needed one.

Whatever admits a returning browser is a value **the browser holds**, and a
browser holds it in a browser's storage. A cookie is no more the OS keyring than
web storage is, a token in memory dies with the tab and is not a session, and a
value the owner retypes per request is not a design anybody lives in. So §3 is
engaged by every candidate. And whatever verifies that value does so **before**
the request can reach the hub — that is what admission means — so `permissions/`
and the audit trail, which are both behind the connection being admitted, cannot
gate it. §7 is engaged by every candidate too. The question was never which
mechanism avoids the clauses; it is whether they are left engaged and unmet.

ADR-0124 §6 settled the instrument for that, and this ADR does not reopen it:
filing it as a gap "was the wrong instrument", because "a known violation does
not authorise adding another" and "creating an access that a ratified clause
requires to be gated, and shipping it ungated, changes what that clause governs".
Read for storage instead of access, the same sentence covers §3. ADR-0070 §1 is
categorical about what the instrument then is, and it is this document.

### The two precedents, and how far each carries

ADR-0124 §6 and ADR-0126 §11 are the corpus's two existing narrow supersessions
of §7, and both are built the same way: the clause is superseded for exactly one
access, three replacements stand in its place, an implementation omitting any of
them does not have the exemption, and the shortfall against the original clause
is stated rather than smoothed over. This ADR takes that shape whole, which is
what ADR-0168 §6 asked for when it named the replacements the lane "should start
from, so it rules rather than re-derives".

Where this case differs from both is worth naming in advance, because it is what
§4 turns on.

- **ADR-0124 §6's exemption is one read of one durable value.** A client reads
  the device credential out of the OS keyring on the connect path, once per
  connection. The custody it substitutes for the gate is the keyring's own — the
  mechanism ADR-0004 §3 itself chose. Here the value is not in a keyring at all,
  and the substitution has to be made on other ground.
- **ADR-0126 §11's exemption is one act with no policy layer running.** The hub
  is stopped by construction, and the audit residue is *forbidden* rather than
  merely absent, because a durable record that the owner destroyed everything is
  Tier 1 data surviving in a system asked to hold nothing. Nothing here is
  forbidden from being recorded; ADR-0168 §6 already requires a record. The
  question §4 answers is how much of one.
- **Neither is weakened, widened or cited as authority.** This is a third access
  with its own argument, and if the argument is rejected this exemption falls
  with it rather than resting on either of theirs.

### The question ADR-0168 §6 delegated, with both halves

ADR-0168 §6's record clause has the gateway record its own **admission
decisions** and nothing else: a session minted, and a request refused on a
condition of that ADR's §3, §4, §5, §6 or §7 — a refused mint included — with refusals
rate-bounded per pair of request class and refusal condition. Nothing is recorded
for a request a live session admits.

That clause arrived at its shape through both review lenses pulling in opposite
directions, and ADR-0168 §6 records the collision rather than hiding it.
**Architecture review** had an earlier draft's record-per-request clause narrowed
away as unbounded: a caller able to drive refusals obliged a write per attempt,
which is the failure ADR-0084 §3 spends its ceilings on and more edge state than
ADR-0094 §9's permission contemplates. **Adversarial review** then named, on the
eighth round, the shortfall the narrowing left: the record covers a session's
admission rather than each Tier 0 read the live session makes, so an auditor sees
that a session was minted and sees every attempt that failed, but not the
successful verifications behind it.

ADR-0168 §6 states both and closes neither: "Which of the two costs more is a
real question, and it belongs to the lane that writes the supersession — with
both halves of it visible here rather than one." §5 below is the ruling.

## Decision

We will supersede ADR-0004 §3's keyring clause, §6's Tier 0 purge clause and
§7's gating clause **for the web-session credential class and for nothing else**,
put named replacements in the place of each, make every exemption conditional on
ADR-0168's own storage and record clauses being obeyed, and rule that a
successful read on the admission path is **not** recorded — stating the shortfall
that leaves rather than closing it.

### 1. The class, and its edges

> **Normative.** The **web-session credential class** is exactly three kinds of
> value, and it is closed: the **cookie half** and the **header half** of a web
> session (ADR-0168 §6), and the **bootstrap value** a gateway process mints and
> discloses once (ADR-0168 §5).

> **Normative.** Nothing else is in the class. The device credential and the
> enrolled hub identity a gateway holds to reach the hub are **not** — they stay
> exactly where ADR-0124 §4 and §6 put them, in the OS keyring, read through the
> Protocol ADR-0125 §8 hands the client, under ADR-0124 §6's own exemption and no
> part of this one.

> **Normative.** A **verifier** the gateway retains is not in the class and is not
> Tier 0. ADR-0124 §6 rules that retaining "only a verifier from which the
> credential cannot be recovered" means the retaining process "holds no device's
> Tier 0 secret at rest", ADR-0168 §4 takes that verbatim for the gateway, and
> ADR-0168 §6 classifies "both halves and the bootstrap value" as Tier 0 and no
> fourth thing. No clause of this ADR reaches a verifier, and ADR-0168 §4's
> prohibition on writing one anywhere is applied rather than narrowed.

> **Normative.** No lane may cite this ADR to place any other Tier 0 value outside
> the OS keyring, to exempt any other Tier 0 access from ADR-0004 §7, or to widen
> this class by resemblance. A value that is not one of the three above is outside
> it however much it looks like one, and admitting a fourth kind takes its own
> ratified decision.

**The class is defined by what mints the value rather than by what holds it, and
that is deliberate.** "A secret in a browser" would have been the shorter
definition and it is the wrong one: it grows silently the moment any later
milestone puts a second value in a browser — a preference, a draft, a cached
answer — and it would invite a lane to read a value's *location* as the thing
that earns the exemption. What earns it is the argument in §2 and §3, and that
argument is about a value this system mints for one purpose, bounded by a
process's life. So the class enumerates.

**The device credential is called out by name because it is the one value most
likely to be swept in by accident.** It sits in the same process as the session
halves, on the same admission path, in the same milestone's implementation. It is
also durable, keyring-held, and already governed — and ADR-0124 §6's exemption
"covers that read and expressly nothing else". A lane that read this ADR as
covering the gateway's own credential read would have widened two exemptions at
once, neither of which permits it.

### 2. ADR-0004 §3's keyring clause is superseded for that class

> **Normative.** ADR-0004 §3's first bullet — "Tier 0 secrets are stored in the
> **OS keyring** via the `keyring` library" — is superseded **only** as it reaches
> the web-session credential class §1 defines, and for nothing else. Every other
> Tier 0 secret in this system, on the hub, on a device and in a gateway alike,
> stays under §3 unchanged.

> **Normative.** The remainder of that same bullet is **not** superseded and is
> applied: no value in the class is written to the memory database or to any other
> database this system opens, and none is ever committed. §3's `.env` sentence is
> untouched and authorises nothing here.

> **Normative.** ADR-0004 §3's second bullet — the reader clause, as ADR-0125 §8
> replaced it — is not superseded, not read more widely and not read more
> narrowly. No value in the class travels through `Secrets` or `SecretStore`, so
> neither Protocol gains a consumer, and ADR-0125 §7's refusal of a backend
> without the operating system's own access control is applied rather than
> narrowed: it governs the keyring seam, and the keyring seam is not where these
> values live.

> **Normative.** Four replacements stand in this exemption's place, and an
> implementation that omits any of them does not have it.
>
> **(a) One purpose, one path.** A value in the class is minted for admission,
> read on the admission path, and read for no other purpose. Nothing else in the
> gateway reads one, none is passed to the promoted engine surface, and none
> appears in any frame the gateway sends the hub.
>
> **(b) Nothing at rest on this system's side.** On the gateway's side the values
> never leave process memory, and the gateway retains verifiers rather than the
> values themselves (ADR-0168 §4). Where ADR-0004 §3 requires a Tier 0 secret to
> be in a place this system chose, this class is in none: nothing this system
> writes holds it. That is a stronger posture than the clause it replaces on the
> side this system controls, and it says nothing about the browser's side, which
> replacement (c) governs and §4 takes as the reason §6 is engaged.
>
> **(c) Custody by the operating system, where a keyring does not exist.** On the
> browser's side custody is the browser profile's own file permissions, which is
> the operating system's own access control on that platform — the mechanism §3
> itself chose, applied at the one door where the `keyring` library has no
> subject.
>
> **(d) Bounded power rather than durable custody.** Every value in the class is
> minted by this system rather than held on behalf of a third party, admits only
> what the owner sitting at that machine can already do, and **ceases to admit
> anything** no later than the end of the gateway process. A session half
> additionally ceases at ADR-0168 §8's absolute or idle bound, whichever comes
> first; the bootstrap value additionally ceases on its single use (ADR-0168 §5).
> ADR-0004 §3's protection of a long-lived third-party secret is replaced by a
> value whose power does not outlive the process that minted it.

> **Normative.** Replacement (d) binds the value's **capacity to admit**, never
> the persistence of its bytes, and no implementation is obliged to make a browser
> forget anything. Bytes a browser retains past that point are not class members
> in a live position: ADR-0168 §4 has the gateway reconstruct no session from
> anything a browser presents after a restart, so they verify against nothing.

> **Normative.** This exemption does not authorise a **durable** browser-held
> credential — one that still admits after a gateway restart, or is minted to.
> Replacement (d) is a condition of the exemption and not a description of the
> current implementation, so a design that removes the bound loses the exemption
> rather than inheriting it, and owes its own ratified decision.

**Replacement (d) is the one doing the real work, and stating why keeps the next
lane from mistaking it for filler.** §3's examples are "OAuth tokens, API keys,
refresh tokens" — values a third party issued, that outlive every process here,
that grant reach the owner cannot revoke by restarting anything, and whose loss is
not observable. The keyring is the right custody for exactly that shape. A web
session half is the opposite on all four counts, and the substitution is not "a
weaker place because a stronger one is unavailable" but "a different kind of
value, whose exposure is bounded by a process's life rather than by a custodian".

**(d) states the bound per value, because ADR-0168 gives the two kinds different
ones and an earlier draft flattened them.** That draft put every value under
"ADR-0168 §8's absolute and idle expiry", which is a **session's** pair of bounds:
`gateway_session_ttl` and `gateway_session_idle_timeout` govern a session, and
ADR-0168 supplies no clock origin and no idle event for a bootstrap value that has
never been exchanged. Two conforming gateways could therefore have differed — one
accepting it until process exit, one expiring it a session-lifetime after start —
which is the underdetermination ADR-0168 §8 opens by refusing. Adversarial review
found it on the third round. What actually bounds an unexchanged bootstrap value
is ADR-0168 §5's own pair: one value per process life, consumed by its single use.
This ADR supplies no further bound and requires none; a lane that wants one owes
the figure, on ADR-0084 §3's ground, and **#1329** records the question against
ADR-0168 rather than answering it here.

**(d) binds the value's power and not its bytes, and an earlier draft got that
wrong in a way worth recording.** It said every value in the class "dies with the
gateway process" — which is false of the half a browser holds, and unsatisfiable
as a condition. ADR-0168 §6 says so in terms: a browser configured to restore its
previous session "can carry both a session cookie and the origin's storage across
a close and reopen", and that section forbids any clause "making a browser's own
behaviour part of the guarantee". So an implementation could not have satisfied
the condition as drafted, and an implementation that tried would have been in
breach of the ADR the condition cites. Adversarial review found it on the first
round. What survives the process is inert: the gateway reconstructs no session
from it (ADR-0168 §4), so it verifies against nothing, and the thing §3 protects
— a secret that still opens something — is exactly what has ended. This ADR's §7
had the right formulation for ADR-0004 §6 while §2 had the wrong one for the same
fact, which is the ordinary way a document contradicts itself.

**That is an argument about the value and not about the browser, which is why (c)
alone would not have been enough.** A browser profile's file permissions are real
custody — the same operating-system control a file-backed keyring gives on that
platform — but they are custody the owner's own browser can be induced to spend,
and ADR-0168 §6 states the residual plainly: script running on the gateway's own
origin defeats both halves without reading either. If the values were durable,
that residual would compound over a machine's lifetime. Bounded, it is bounded
too.

**§3's "never in the memory database, never in a committed file" half is kept
rather than superseded, and the split matters.** What made §3 the right rule was
never the word *keyring* on its own; it was that a Tier 0 secret must not end up
somewhere a backup, a sync, a `git add` or a support bundle sweeps up. None of
that is relaxed here, and ADR-0168 §4 already forbids more than §3 does — no
database, no file, no log record, no audit record, no error message, no
diagnostic. Superseding the place clause while keeping the prohibition is what
makes this narrow instead of a hole.

### 3. ADR-0004 §7's gating clause is superseded for a web session's admission

> **Normative.** ADR-0004 §7's gating clause — "Access to Tier 0/1 data and every
> side-effecting tool call is gated by the `permissions/` layer and recorded in an
> **audit trail**" — is superseded **only** for a gateway's reads and
> verifications of the web-session credential class on the admission path, and for
> nothing else. Every other Tier 0 and Tier 1 access, in the hub, in the offline
> tools, on every device and elsewhere in a gateway, stays under §7 unchanged.

> **Normative.** ADR-0004 §7's second bullet — data minimisation — is not
> superseded and is not read either way.

> **Normative.** Three replacements stand in this exemption's place, and an
> implementation that omits any of them does not have it: the read is confined to
> one purpose and one path — this ADR's §2, replacement (a), which serves both
> exemptions;
> custody is the operating system's own control, on the browser profile at one end
> and on process memory at the other, so the access is gated by the OS where it
> cannot be gated by `permissions/`; and the **session's admission** is
> **recorded** under ADR-0168 §6's record clause — the mint that created it, and
> every refusal, a failed verification of the halves included.

> **Normative.** The third replacement reaches an **admission and not a use**. No
> implementation and no later lane may state, present or rely on it as the latter:
> it makes no successful Tier 0 read on the admission path reviewable, and this
> ADR's §5 rules that none is recorded.

> **Normative.** The third replacement reaches the record's **emission and not its
> retention**. ADR-0168 §6 has the gateway retain none of what it emits, so where
> a record lands and how long it survives is the operator's — exactly as it
> already is for the hub's and the CLI's records. No implementation and no later
> lane may present this replacement as a durable or reviewable trail, and no
> implementation acquires a retention obligation from this ADR.

> **Normative.** Nothing in this ADR decides whether this system's logging should
> carry a retention policy. ADR-0168 §6 declines that as a project-wide question
> rather than a gateway one, and it stays declined here; a lane that wants the
> admission record durable owes that decision rather than reading one into this
> exemption.

> **Normative.** This ADR does not cite ADR-0124 §6's exemption, does not widen
> it, and does not rest on it; the same for ADR-0126 §11's. Each stays confined to
> the access it names. This is a third access with its own argument, and if that
> argument is rejected this exemption falls rather than surviving on theirs.

> **Normative.** No lane may cite this clause toward a fourth exemption. A further
> Tier 0 access that cannot be gated by `permissions/` owes its own ratified
> decision, on its own argument, however closely it resembles this one.

**Both halves of §7 are structurally unavailable here, and neither is unavailable
by choice.** `permissions/` runs inside the hub and the audit trail is
`<data_dir>/audit.db`, a Tier 1 store the hub owns exclusively (ADR-0083). The
access this exemption covers is the one by which a browser becomes able to reach
the hub at all, so gating it at the hub is circular in ADR-0124 §6's exact sense:
the browser would have to be admitted in order to earn the right to be admitted.

**And it is worse here than in ADR-0124's case, on a ground ADR-0124 did not
have.** ADR-0168 §9 requires the gateway to start and serve its listener **whether
or not the hub is reachable**, so that a browser reaching a running gateway learns
that the hub is down rather than that nothing is there. A hub-gated admission
would make "the hub is down" an answer the browser could never be told — the
gateway could not admit the request that would carry the message. That is
ADR-0083's ruling 4 failure produced by the gate itself, and it is why the
circularity here is not merely awkward but self-defeating.

**A second policy layer inside the gateway is not the escape, and it was
considered.** A spoke holds nothing authoritative (ADR-0094 §9), an authority on
the edge is the architecture this system is not, and ADR-0168 §1 forbids the
gateway authoring a permission ruling in terms. What such a layer would evaluate
is a request from the owner, at their own machine, presenting a value this same
process minted for them minutes ago — ceremony consuming a decision nobody asked
for, which is ADR-0126 §11's finding about its own case arriving again.

**The replacements are weaker than ADR-0004 §7 in three distinct ways, and each
is stated rather than smoothed over.**

- **Emission, not retention.** The gateway's record is emitted through the
  logging this system already configures and **retained nowhere** — ADR-0168 §6's
  own words — where §7 names an audit trail, a Tier 1 store. On the ordinary
  arrangement, standard output to a terminal nobody collects, a mint is emitted
  and then gone: an auditor arriving later has neither that record nor an
  `audit.db` entry. So the third replacement supplies a record at the moment of
  the decision and supplies no trail, and where it lands is the operator's,
  exactly as it already is for the hub's and the CLI's records.
- **Custody, not a policy decision.** Browser-profile permissions and process
  memory are custody, not a ruling traceable to an answer the owner gave about
  *this* access — ADR-0124 §6's own statement of its own shortfall, and it
  transfers whole.
- **Admission, not use.** A record of a session's admission is not a record of
  the reads that session then makes, which is this ADR's §5 subject.

**The first of the three was an over-claim in an earlier draft, and it is the
same defect ADR-0168 §6 warned this lane about one level down.** That draft said
the admission was "auditable". Adversarial review found on the first round that
the word claims a coverage the mechanism does not have: the condition can be
satisfied in full while nothing is reviewable afterwards, because the record's
survival is not a property of any implementation this ADR governs. ADR-0168 §6
told the writing lane to say "auditable admission" rather than "auditable use"
because "the shorter phrase would claim a coverage the record does not have" —
and the instruction turns out to bite twice, on the *use* half and on the
*auditable* half alike. The clauses above now name what the replacement actually
delivers, which is a recorded decision, and name the two things it does not.

### 4. ADR-0004 §6's Tier 0 purge clause is superseded for that class, and the act that removes it is stopping the gateway

> **Normative.** ADR-0004 §6's clause that "deleting the user's data purges Tier 0
> (keyring entries) and Tier 1 (database rows) together" is superseded **only** as
> it reaches the web-session credential class §1 defines, and for nothing else.
> Everything else §6 grants — view, export, delete, retention rules, and the purge
> of every Tier 1 artifact and every keyring-held Tier 0 artifact a delete act does
> reach — is untouched.

> **Normative.** Two replacements stand in this exemption's place, and an
> implementation that omits either does not have it. **The act that removes the
> class is stopping the gateway process**, performed at the machine that runs it
> and needing no hub, after which every session has ended (ADR-0168 §4) and what a
> browser still holds verifies against nothing. And a delete act that cannot
> perform it **names the class as not purged** and names that act; it may not
> describe Tier 0 as purged.

> **Normative.** Nothing in this ADR obliges a delete act to reach a gateway, to
> stop one, or to enumerate one. ADR-0168 §3 forbids anything about a browser
> reaching the hub's machinery, a gateway ordinarily runs on a different machine
> from the hub (ADR-0168 §2), and ADR-0126 §2 requires the offline delete act to
> run with the hub stopped — so an act that could reach a gateway is a mechanism
> no ADR provisions, and this one does not provision it either.

**A record is owed here, and ADR-0126's supersession of the same sentence does
not cover it.** ADR-0126 §6 took this clause too, and its scope reaches "a Tier 0
credential held **on the hub's own machine** outside the OS keyring", naming its
subject as "exactly one thing: the model provider credential". Two things keep
that from reaching a web session. ADR-0168 §2's ordinary arrangement puts the
gateway on the *browsing* device, so the class is typically not on the hub's own
machine at all. And ADR-0126's replacement is written for its own subject — its
report clause describes "a credential the operator holds in their environment or a
shell profile" — so even where a gateway does run on the hub's machine, that
report does not describe this class. ADR-0126 also forbids any lane citing it "to
hold a new credential outside" the keyring, which is what this ADR's §2 does on
its own argument. So this is a **third scope on §6's sentence**, not a widening of
ADR-0126's.

**Two ADRs have already superseded that sentence for two different unreachable
places, and neither recorded anything on the other.** ADR-0124 §8 took it for an
enrolled device's keyring entry, because a delete at the hub cannot reach another
machine. ADR-0126 §6 took it for a credential in the operator's own environment —
another custodian, one machine closer. Both wrote their record on ADR-0004 alone.
A third subject is that same operation a third time, which is why §8 writes
nothing on either of them.

**An earlier draft found no record owed here, and the argument it used is the one
ADR-0126 had already refused.** It said there is "nothing at rest for a purge to
miss", and that a session surviving the delete admits nothing useful because the
hub is gone. Both halves are wrong. The half a browser holds *is* at rest, in a
browser profile no delete act reaches, and while its gateway runs it still admits
— ADR-0168 §9 has the gateway serve its listener whether or not the hub is
reachable, so what the browser gets is a served request carrying a legible
hub-down answer, not the silence of a dead credential. And "not useful" is
precisely the reasoning ADR-0126 §6 rejected on its own credential: ADR-0004 §1
defines Tier 0 by what a value *is* rather than by where it sits or what it can
still open, and an act that leaves one exactly where it found it has not purged
it. Adversarial review found it on the second round.

**What this supersession costs is small, and that is a fact about the class rather
than a mitigation of the record.** The act that ends the class is one the owner can
perform locally, without the hub, and it ends *every* session at once; after it the
residue is inert. That is a better position than either precedent — an enrolled
device's keyring entry needs an act at that device, an environment credential an
act at the place the operator set it, and neither becomes inert on its own. What
all three share is the only thing the record is about: the delete act cannot
perform the act that removes the value, so it says so instead of claiming a purge
it did not do.

### 5. A successful read is not recorded, and the shortfall is stated rather than closed

> **Normative.** No record is written for a Tier 0 read or verification that a
> live web session admits. The record ADR-0168 §6 requires — a mint, and every
> refusal — is the whole of what this ADR's §3 supplies in its third
> replacement, and this ADR adds no obligation to it.

> **Normative.** No clause of this ADR is satisfied by, and no lane may cite it
> toward, a record written per admitted request.

> **Normative.** This ruling is scoped to a web session whose power ends with its
> gateway process (ADR-0168 §4). A design in which a session still admits after a
> restart reopens it and may not inherit it, and owes the question its own answer
> in the ratified decision that authorises the durable session.

**The ruling is not that the record costs too much. It is that the record cannot
distinguish the case it would exist to reveal**, and that is the reason worth
writing down, because the cost argument alone would have been the weaker half of
a real trade.

Ask what a per-request record is *for*. §7's stated purpose is making the
assistant's behaviour "transparent and reviewable"; the question an auditor brings
to a session credential is whether anyone other than the owner used it. Now ask
what could produce such a use. ADR-0168 §6 names the residual precisely: **script
running on the gateway's own origin defeats both halves, because it need not read
either — it can simply issue requests the browser will authenticate.** Every
request that attacker makes is issued by the owner's own browser, over the owner's
own connection, carrying the owner's own two halves, to the origin the owner is
sitting on. A record per admitted request records it as ordinary use. It
increments identically whether the owner typed the question or a careless render
of model output did, and it is by construction unable to say which. That is not
an audit of the access; it is a request counter with an audit's name on it.

**What that leaves is a shortfall, and it is stated rather than argued away.** An
auditor sees that a session was minted and sees every attempt that failed — a
mistyped bootstrap value, a replaced cookie, an expired session, a refusal at the
ceiling — and does not see the successful verifications behind a live session. A
rider on a live session is invisible in the record. Adversarial review of ADR-0168
named that on the eighth round and it was right to; ruling that no record closes
it is not a finding that it does not exist.

**Three further reasons stand behind the ruling, none of them sufficient alone.**

- **The audit unit is the admission, at all three doors, and that is now a
  pattern rather than a coincidence.** ADR-0124 §7 has the hub record "each
  admission and each refusal with the device it named" — of a *connection*, not of
  every request carried on one. ADR-0168 §6 audits a session's mint and its
  refusals, a session being this door's connection. §7's own text asks for access
  to be recorded, and the corpus has twice answered that, for an admission
  credential, at admission granularity. A third answer at a different granularity
  would need a reason specific to this door, and the paragraph above is why there
  is none.
- **What the gateway does per request is a comparison, not a read out of
  custody.** It compares a value the caller just supplied against an in-memory
  verifier, in constant time. The custody read §7 is really about — the browser
  reading its own storage — happens inside the browser, where nothing this system
  writes could observe it. So the record adversarial wanted would not have
  recorded the unaudited event; it would have recorded that a request arrived
  afterwards.
- **The alternative is the shape architecture review already removed, and
  removing it was right.** ADR-0168 §6 narrowed a record-per-request clause on
  ADR-0094 §9 and ADR-0084 §3's grounds: a resident process that a caller can
  oblige to write is the failure those ceilings exist for. The narrowing's force
  is smaller on the *admitted* path than on the refused one — an admitted browser
  is the owner's own, and its request rate is bounded by a person rather than by
  an adversary — which is why this reason is stated third and not first. It is
  corroboration, not the ground.

**Consistency with ADR-0124 §6 is the last check, and it comes out the same
way.** That section accepted the identical shortfall for a *stronger* credential:
"a hub-side record of an admission tells an auditor the credential was used, never
that it was read — a device that reads it and never connects leaves no trace
anywhere." The device credential is durable, keyring-held, and carries a whole
device's authority across restarts. A web session half is ephemeral, admits
nothing once its process ends, and carries no more than the gateway already has. Ruling harder here
would put the stricter obligation on the weaker value, which is a rule nobody
could explain to the lane that has to obey it.

**What actually bounds the residual is stated, so that "not recorded" is not read
as "not defended".** ADR-0168's content-security-policy and text-not-markup
clauses (ADR-0168 §6) are what keep the origin's script trustworthy in the first
place; the session's absolute and idle expiry (ADR-0168 §8) bound how long a
rider can ride; the ceiling and death with the process (ADR-0168 §4) bound how
many sessions exist and the whole exposure to one gateway's lifetime. Those are the defences. The
record was never one of them.

### 6. The exemption is conditional on ADR-0168's own clauses

> **Normative.** An implementation has neither exemption above unless it satisfies
> ADR-0168 §4's storage clauses — the session table is process memory alone, no
> value or verifier is written to any database, file, log record, audit record,
> error message or diagnostic, and every session ends when the gateway process
> ends — and ADR-0168 §6's admission-record clause and the enumeration of Tier 2
> facts it permits.

> **Normative.** This ADR restates none of those clauses and modifies none of
> them. It makes them conditions, so ADR-0168 remains the single statement of what
> they require and this ADR cannot drift from it.

**Making the exemption conditional rather than descriptive is what stops it
becoming self-certifying.** Replacement (b) above says the values are nowhere at
rest; that sentence is true only because another ADR forbids writing them. Stated
as a fact about the implementation, it would be an exemption that survives the
implementation changing. Stated as a condition, an implementation that starts
persisting a session table loses the exemption at the moment it does so, and is
then in breach of ADR-0004 §3 as written — which is the correct and legible
outcome.

**Restating the clauses instead was the alternative and it is the trap.** Two
documents stating the same obligation in slightly different words is the drift
ADR-0089 §2 records finding *in the section defining the prevention*. ADR-0168 is
ratified and its text is settled; pointing at it costs a citation and cannot
diverge from it.

### 7. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface, adds no `Settings` field, and changes no wire member. A lane
> implementing milestone 13 that finds it needs any of those stops and owes its own
> contract ADR, merged first (golden rule 5, ADR-0015 §5) — exactly as ADR-0168
> §12 already requires.

> **Normative.** This ADR decides nothing ADR-0168 §12 defers, adds no clause to
> ADR-0168, and does not reopen any ruling of it. Where a reader finds this ADR
> and ADR-0168 addressing the same subject, ADR-0168 governs and this one supplies
> only the ADR-0004 exemption ADR-0168 §6 requires.

**Deferred, and untouched, by name:**

- **The browser-facing surface** — request shapes, paths, the document, whether a
  push carrier is among them. ADR-0168 §12 leaves it to the implementing lane and
  nothing here reaches it.
- **A durable browser credential and a session that survives a restart.**
  ADR-0168 §5 and §12 defer it to milestone 16. §2 and §4 above make the bound a
  condition of the exemption rather than a description, so that milestone starts
  from a ruling it must supersede rather than from silence it could read as
  permission.
- **#74 — whether §7's gate reaches the model provider credential.** Untouched
  and open on its own subject. That credential is read from the process
  environment by the provider SDK, is pre-existing, and is outside this ADR's §1
  class.
  ADR-0125 §8 records it as not authorised by that ADR, and this one authorises it
  no more.
- **Whether the gateway's log, or this system's logging in general, carries a
  retention policy.** ADR-0168 §6 declines it as a project-wide question rather
  than a gateway one, and this ADR decides nothing about it.
- **Anything about `tools/` egress, residency, or the boundaries.** ADR-0017 §1
  as ADR-0124 §1 replaced it, and ADR-0155's residency and covered-content
  clauses, are not engaged: a loopback listener transmits nothing off the device,
  and no value in this ADR's §1 class is covered content or reaches an egress
  span.

### 8. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**Two clauses are superseded and their record lands in this change. No record is
owed on any of the rest.**

- **ADR-0004 §3's first bullet — superseded, narrowly (§2).** A reader holding
  only §3 believes every Tier 0 secret in this system's world sits in the OS
  keyring, and after this ADR's §2 that is wrong of the web-session credential
  class. The
  record is ADR-0004's `Status` line and an appended dated note. That line is a
  grandfathered `Accepted, partially superseded …` value with no leading token, so
  ADR-0082 §2's exclusion does not apply and the qualifier goes on the line beside
  the note, accumulating as ADR-0070 §4 requires without dropping the five pairs
  already there. The scope names a clause and carries no `ADR-NNNN` token, so
  ADR-0070 §4's target-extraction invariant holds.
- **ADR-0004 §7's first bullet — superseded, narrowly (§3).** A reader holding
  only §7 believes every Tier 0 access is gated by `permissions/` and recorded in
  the audit trail, and after this ADR's §3 that is wrong of a web session's
  admission. Same
  record, same line, one pair naming both scopes — which is what ADR-0168 §6
  required when it made "**one** narrowly scoped supersession covering both" the
  prerequisite, and which ADR-0124's own pair on that line (`§6's delete clause
  and §7's gating clause`) is the established form for.
- **ADR-0004 §1 — used as given.** The class is Tier 0 *because* §1 says so, and
  ADR-0168 §6 already classified it there. Nothing reclassifies a value out of a
  tier, which would have been the way to avoid this ADR and is refused in
  Alternatives.
- **ADR-0004 §2, §4 and §5 — untouched.** §2's residency, egress and telemetry
  clauses are not reached by a loopback listener. §4's at-rest posture governs the
  memory database, which no value here enters. §5 is applied rather than narrowed:
  "logs are Tier 2 only" is what makes ADR-0168 §6's record an enumeration of
  permitted Tier 2 facts, and §2's replacement (b) keeps every value in the class
  out of every log.
- **ADR-0004 §6's Tier 0 purge clause — superseded, narrowly (§4).** A reader
  holding only §6 believes deleting their data purges Tier 0 with Tier 1, and
  after §2 that is wrong of a class whose holder is a browser profile and a live
  gateway process that no delete act reaches. It is the third unreachable holder
  that sentence has acquired, after ADR-0124 §8's enrolled device and ADR-0126
  §6's operator environment, and it takes the same instrument both took. **This is
  a clause ADR-0168 §6 did not name**, and this ADR writes the record because its
  own §2 is what creates the engagement — ADR-0070 §1 is categorical that creating
  it obliges the record, and ADR-0124 §6 already ruled that filing it as a gap is
  the wrong instrument. §6's other grants — view, export, delete, retention rules,
  and the purge of every Tier 1 artifact and every keyring-held Tier 0 artifact a
  delete act reaches — are untouched.
- **ADR-0126 §6 and §11 — examined, and no record is owed.** Every sentence
  stays true. Its self-limiting clause says it "authorises no new credential to be
  held outside" the keyring, and that holds exactly: ADR-0126 authorises none, and
  this ADR's §2 is what authorises this one, on its own argument rather than by
  citing that one. Its supersession scope reaches a credential "on the hub's own
  machine", which §4 shows this class ordinarily is not, and its report clause
  describes the operator's environment credential, which this class is not either
  — so §4 is a **third scope on ADR-0004 §6's sentence** rather than a widening of
  ADR-0126's, and it takes nothing from it. The one sentence overtaken is the
  population observation "today that is exactly one thing", a state claim about
  ADR-0126's own moment rather than a decision, so nothing is rewritten. **The
  precedent for writing no record is exact**: ADR-0124 §8 and ADR-0126 §6
  superseded that same ADR-0004 sentence for two different unreachable holders,
  and neither wrote anything on the other. §11's §7 exemption is neither cited nor
  widened.
- **ADR-0124 §6 — examined, and no record is owed.** Its exemption "covers that
  read and expressly nothing else", and §1 above puts the device credential
  outside this class in terms, so a reader holding only ADR-0124 still confines
  it to a client's bootstrap credential read. Its requirement that the credential
  be held in the keyring and read through the Protocol is applied to the gateway
  unchanged. Its stacked addition of a third `SecretStore` consumer is untouched,
  and this ADR adds no fourth — no value in this ADR's §1 class travels through
  that seam at all.
- **ADR-0125 §7, §8 and §9 — used as given (§2).** A reader holding only ADR-0125
  still builds a `SecretStore` that refuses a file, an environment variable or a
  backend without the operating system's own access control, and still hands
  `models/` and `tools/` the reading face alone. `select_backend`'s five-prefix
  allow-list is the clause in code and nothing here relaxes it. ADR-0125 §9's
  statement that it gates nothing and discharges no condition is unaffected.
- **ADR-0168 §4, §5, §6 and §9 — used as given, and §5 above makes two of them —
  §4's storage clauses and §6's record clause — conditions of this exemption.**
  Nothing is added to any of them and nothing is read more widely. In particular §6's record clause is relied on exactly as
  written: this ADR's §5 rules the same way it does — nothing recorded for a
  request a live session admits — so it imposes no obligation §6 does not already
  carry, and no record is owed on ADR-0168. §6's fourth replacement bullet
  instructs the writing lane to state the third replacement as auditable
  *admission* rather than auditable *use*, and this ADR's §3 states it as an
  admission and not a use, forbidding the shorter phrase. §3 additionally holds
  the replacement to the record's **emission** rather than its retention, which
  is ADR-0168 §6's own "the gateway retains none of it" restated as a limit on
  what this exemption may be said to supply — a narrowing of this ADR's own
  claim, not of ADR-0168's clause.
- **ADR-0083 — used as given.** The audit trail is a Tier 1 store the hub owns
  exclusively, and §3 above relies on that exclusivity rather than qualifying it.
  No second audit store is created anywhere, which is also why replacement (b)
  can say the gateway holds nothing at rest.
- **ADR-0094 §9 — used as given.** ADR-0168 §13 already tested the session table
  and the interval counters against it and found both bounded in size and in age,
  destroyed continuously, and never authoritative. This ADR adds no edge state at
  all — it writes no clause requiring the gateway to hold anything — so there is
  nothing further to test.
- **ADR-0017 §1 and §3, and ADR-0155 §1 and §3.** Not engaged. Nothing here
  transmits, designates a seam, attests a condition or reaches an egress span, and
  no clause of either is read in either direction.
- **ADR-0097 and ADR-0099 §1.** Untouched. ADR-0168 §4 already refuses to present
  a web session as a grant or a principal, and this ADR creates no grant, adds no
  principal, and reads neither ADR more widely.
- **Golden rules 2, 3 and 5.** Applied, not amended. `core` gains nothing, the
  gateway stays an adapter that authors nothing, and no Protocol or `core` type is
  decided here.

## Consequences

- **ADR-0168 §6's prerequisite is discharged**, so the milestone-13 gateway
  implementation lane is unblocked. That lane may now implement ADR-0168 §6 — and
  it inherits this ADR's §6, so an implementation that persists a session table or
  drops ADR-0168 §6's record does not have any exemption here and is in breach of
  ADR-0004 §3, §6 and §7 as written.
- **ADR-0004 gains a sixth partial supersession**, and its `Status` line a sixth
  pair — carrying **three** scopes, since ADR-0168 §6 required one supersession
  covering §3 and §7 and this ADR's own §2 then engaged §6 as well. The record and
  its dated note land in this change, per ADR-0070 §1, ADR-0082 §1 and ADR-0083
  §15.
- **ADR-0004 §6's purge clause now has three unreachable holders** — an enrolled
  device's keyring entry (ADR-0124 §8), the operator's environment credential
  (ADR-0126 §6), and a live web session (§4) — each recorded separately on that
  sentence and each answered with the same instrument: name what was not purged,
  and name the act that removes it. The third is the mildest of them, because its
  act is local, needs no hub, and leaves inert bytes behind.
- **A Tier 0 value now exists in this system's world that is not in the OS
  keyring**, deliberately and for the first time. That is the honest cost: a
  reader of ADR-0004 §3 can no longer act on it alone, and every later lane
  holding a Tier 0 value has one more document to check before concluding the
  keyring is not where its value belongs. §1's closed class and §2's prohibition on
  widening by resemblance are what keep the answer short for all of them — the
  class is three values, and anything else is still §3's.
- **ADR-0004 §7 now carries three narrow exemptions** — ADR-0124 §6's, ADR-0126
  §11's, and this one — each with its own argument, each forbidding the others
  being cited to widen it. Three is the number at which the pattern is worth
  looking at rather than extending again: whether §7's clause should be *restated*
  to say what it requires of an access no policy layer can reach, instead of
  exempted a fourth time, is a question this ADR does not answer and files as
  **#1321**.
- **The corpus now has an answer to "is a successful read recorded" for an
  admission credential**, and it is the same answer at all three doors: the audit
  unit is the admission. That is stated with its shortfall (§5) rather than as a
  clean property, so a later lane inherits both halves.
- **What becomes harder:** a rider on a live web session leaves no trace in any
  record. Nothing this milestone ships detects it, and the defences are
  ADR-0168's content-security-policy, expiry, ceiling and process-lifetime
  clauses rather than an audit. An owner who suspects one restarts the gateway,
  which ends every session.
- **Revisit when** milestone 16 asks for session persistence, which reopens §4's
  ruling on its own terms and may not inherit it (§2, §4); when a browsing device
  cannot host a gateway, which ADR-0168 §2 already sends to a fourth-egress-boundary
  decision and which would put a session credential on a wire between two
  machines; or when a fourth access needs an exemption from ADR-0004 §7, at which
  point #1321's question is due rather than optional.

## Alternatives considered

- **Leave §3 and §7 engaged and unmet, and file the gap as an issue.** The
  cheapest path, and the one an earlier ADR-0124 draft took. *Rejected* on
  ADR-0124 §6's own ruling about the instrument: a known violation does not
  authorise adding another, and creating an access a ratified clause requires to
  be gated and shipping it ungated changes what that clause governs. ADR-0070 §1
  is categorical about what the instrument then is.
- **Reclassify the session halves out of Tier 0**, so neither clause is engaged.
  Superficially the cleanest escape. *Rejected*: ADR-0168 §6 classifies them Tier
  0 under ADR-0004 §1 in a normative clause, so this would supersede ADR-0168 as
  well, and the classification is right on its merits — a value that admits a
  request carrying the device's whole authority is a credential whatever else it
  is called. Reclassification to avoid a clause is the move ADR-0070 §1's test
  exists to catch.
- **Put the browser's half in the OS keyring**, so §3 holds unchanged. *Not
  available.* A browser has no keyring, no `SecretStore` and no path to
  `select_backend`, and `secret_store/` correctly refuses every backend that is
  not one of the five operating-system keyrings. There is nothing to wire.
- **A durable browser credential the owner types, held in the gateway's
  keyring**, so the Tier 0 value that persists is one §3 already covers.
  *Rejected*, and twice over. ADR-0168 §5 already declined it for this milestone —
  it is a second Tier 0 secret whose entropy a human chose, the shape ADR-0124 §6
  spent a clause arguing against — and it does not even solve this problem: the
  browser still holds something it presents on every request, so §3 is engaged by
  the browser's half exactly as before. It buys a durable secret and no exemption.
- **Record every successful read, closing adversarial review's shortfall.**
  *Rejected in §4*, on the ground that the record cannot distinguish the case it
  would exist to reveal — a rider on a live session issues requests through the
  owner's own browser, and the record increments identically — rather than
  primarily on its cost. Its cost is real too: it is the record-per-request shape
  architecture review had ADR-0168 §6 narrowed away from, and it would have
  obliged the two lenses to be answered by contradicting one of them.
- **Record an interval-bounded count of admitted requests**, a middle path that
  is bounded in the way ADR-0168 §6's refusal records are. Genuinely attractive,
  and considered at length. *Rejected* for the same reason and one more: the count
  increments for the owner and the rider alike, so it is a load metric rather than
  an audit; and it would contradict ADR-0168 §6's clause that the gateway records
  its admission decisions "and nothing else", which is a ratified normative clause
  this ADR has no standing to supersede and no argument that would justify it.
- **A gateway-side audit store, so §7's "audit trail" is met literally.**
  *Rejected.* It is durable state on the edge, which ADR-0094 §9 permits only
  bounded and continuously destroyed; it is a second Tier 1 store outside the one
  process ADR-0083 gives exclusive ownership of them; and ADR-0168 §6 already
  ruled that the gateway retains none of what it emits. Meeting the letter of §7
  by building the thing the architecture forbids is not meeting it.
- **Gate the admission at the hub, so §7 holds unchanged.** *Rejected in §3.* It
  is circular — the browser must be admitted to earn admission — and ADR-0168 §9
  makes it self-defeating besides: a hub-gated admission cannot deliver the
  message that the hub is down, which is half of milestone 13's exit test.
- **Wholly supersede ADR-0004 §3, or §7, or both.** *Rejected.* ADR-0070 §3 makes
  partial supersession first-class precisely so a clause's live remainder is not
  collateral, and the remainder here is the part with the teeth: every other Tier 0
  secret in the keyring, every other Tier 0 and Tier 1 access gated and recorded.
- **Find no record owed on ADR-0004 §6**, on the ground that a session is never at
  rest and that one surviving a delete admits nothing useful. The position an
  earlier draft took. *Rejected in §4* on both halves: the browser's half **is** at
  rest in a profile no delete act reaches, and while its gateway runs it still
  admits — ADR-0168 §9 has that gateway answer rather than fall silent. "Not
  useful" is also the argument ADR-0126 §6 refused on its own credential, since
  ADR-0004 §1 defines Tier 0 by what a value is and not by what it can still open.
- **Read ADR-0126 §6's supersession as already covering the class**, so no third
  scope is owed. *Rejected in §4*: ADR-0126's scope reaches a credential "on the
  hub's own machine", which the ordinary gateway arrangement is not, its report
  clause describes the operator's environment credential specifically, and it
  forbids any lane citing it to hold a new credential outside the keyring — which
  is what this ADR does.
- **One ADR per superseded clause.** *Rejected.* ADR-0168 §6 requires "one
  narrowly scoped supersession covering both" of the clauses it named, and all
  three engagements share one subject, one class and one argument — §2's
  replacement (a) serves the §3 and §7 exemptions alike, and §4's replacements
  rest on §2's bound. Splitting them would put a third of the argument in each
  document and none would be readable alone.
- **Defer the question §4 answers to the implementing lane.** *Rejected.* It is a
  ruling about what the §7 exemption's third replacement *is*, so an implementation
  cannot be judged against the exemption without it, and ADR-0168 §6 assigned it
  here by name. Deferring it would leave the implementing lane choosing between two
  review lenses' positions with no ratified text to point at, which is the
  situation this document exists to end.
