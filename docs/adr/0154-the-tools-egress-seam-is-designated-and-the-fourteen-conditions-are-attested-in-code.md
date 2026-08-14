# 154. The `tools/` egress seam is designated, and the fourteen conditions are attested in code

- Status: Accepted
- Date: 2026-08-14
- **Note (2026-08-14): ratified.** `Proposed` → `Accepted`, after **both** required
  reviews came back green on one tree — adversarial **APPROVE with no findings** and
  architecture **APPROVE with no findings**, both at tree `4d3d68f974a2`, printed
  round 7, churn ratio 1.1 — and with both re-run on the flipped tree for coverage.
  That is the outcome ADR-0070 §1 requires the ratifying edit to record, and the
  route `CONTRIBUTING.md` → "Finishing an ADR PR" fixes (ADR-0130 §12, ADR-0136 §7
  and ADR-0146, ADR-0147 and ADR-0148's own notes are the worked precedents).
  **What the ratifying commit edits:** the `Status` line, this note, and §8's
  unmarked record of the route and the rounds — nothing else, and **no normative
  clause acquires, loses or alters an obligation**, which is ADR-0070 §1's own test
  applied to the ratifying edit itself. Both lenses were required because this is
  the ADR deciding an egress boundary's status (§8).
- **This is the ADR ADR-0017 §2 has required since 2026-07-19.** That section
  leaves the `tools/` egress boundary **approved and undesignated** and reserves
  designation to "a later ADR" that does three things and no fewer: **names the
  seam module**, **attests each condition** of §3 "is satisfied and how", and
  **records the transition**. This ADR is that one. §1 names, §4 attests, §5
  records.
- **On this ADR's merge, `ai_assistant.tools.egress` may transmit.** That is the
  whole of the status change, and §2 states what it does **not** authorise: no
  tool is registered, no destination is approved, and no byte moves until a
  registration lane and a per-call ruling both happen. A boundary that may
  transmit is not a boundary that has.
- **Attestation is a statement about the tree, and every row of §4 is one.** Each
  names the mechanism, the code, and the evidence — a module, a test, or a check —
  and each was verified against `origin/main` at `a9c315c5` by reading the artifact
  or running it. No row rests on a claim made in a pull request, in an issue, or in
  a prior ADR's summary of its own reach.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-14**,
  the durability form ADR-0100 established and ADR-0125, ADR-0126, ADR-0149,
  ADR-0151 and ADR-0153 each followed. Seven of the ADRs this one attests against
  were ratified in the last two days; a citation that silently means "whatever
  this ADR says when you read it" is not checkable, and this is the one document
  in the corpus where that would matter most.
- **Amends no ADR and supersedes none.** ADR-0017 §3 stands exactly as written —
  it is *satisfied* here, not replaced — and the single edit this change makes to
  ADR-0017 is one appended dated note, its `Status` line being left alone under
  ADR-0082 §2 (§5). Refs #93, #1096.

## Context

### What ADR-0017 left open, and for how long

ADR-0017 §1 widened ADR-0004 §2's egress rule from one component to two: user data
may leave the device from `models/` **or from a designated integration seam inside
`tools/`**. It then withheld the second half of what it granted. §2's closing
paragraph:

> **`tools/` — approved, undesignated.** It may now transmit *in principle* and
> nothing in practice: acceptance of this ADR authorises no byte. It becomes
> designated — and only then transmits — when every condition in §3 holds in code
> **and** a later ADR names the seam module, attests each condition is satisfied
> and how, and records the transition. Not a status amendment: a second
> operational egress boundary is a substantive decision, and ADR-0001 reserves
> those to a new ADR.

§3 then lists fourteen conditions and closes:

> A boundary meeting these in a document but not in code is approved, not
> designated, and an approved boundary transmits nothing.

That sentence is why this ADR exists and why it is shaped as it is. Fourteen
mechanisms have since been decided across eight ratified ADRs, and **not one of
them discharges a condition**, because each says so in its own marked clause. What
was missing was never a mechanism. It was a document willing to state, about a
tree, that the properties hold.

### The corpus that supplies the mechanisms, and why none of it could do this

Eight ADRs bear on §3's list. Each disclaims attestation, in nearly identical
language, and the uniformity is deliberate rather than incidental:

| ADR | What it supplies | Its own disclaimer |
|---|---|---|
| ADR-0146 | Outbound content classified by discloser; provenance never moves a tier | §8: "No lane reads this ADR as adding a condition to ADR-0017 §3's list, as relaxing one, or as attesting that any of them is satisfied." |
| ADR-0147 | The seam's **name**, and the enumerated import contract's shape | §3: "This ADR designates nothing, attests no condition of ADR-0017 §3, and authorises **no byte** … no lane may cite this ADR toward any of them." |
| ADR-0148 | Nine of the fourteen mechanisms; §10's own condition table | §10: "**No condition is discharged by this ADR** … discharge is attestation that a property holds in code, and supplying a mechanism is not that." |
| ADR-0149 | The connection record and the provisioning component | Consumed here; attests nothing. |
| ADR-0150 | The `EgressBinding` value — surface (a) | §11: "This ADR designates nothing, attests no ADR-0017 §3 condition, and discharges none." |
| ADR-0151 | The connection surface; the minted reference | Consumed here; attests nothing. |
| ADR-0152 | The binding seam — surface (b) | §12: "This ADR **designates nothing**, attests no ADR-0017 §3 condition and discharges none." |
| ADR-0153 | The integration purge in the offline delete act | Consumed here; attests nothing. |

ADR-0147 §11 is the sharpest statement of the gap, and it names this ADR's job
without knowing its number:

> Note what would have owed a record and is deliberately not done: attesting
> condition one — "a named seam and an import-linter contract pinning it" — is a
> statement about code, reserved by §2 to the designating ADR, and this ADR makes
> no such statement.

ADR-0148 §13 says the same about itself, and adds the reason it matters:

> Saying it loudly is the point, because a document that supplies nine mechanisms
> reads like permission to transmit, and it is not: `tools/` still transmits
> nothing.

### What makes this decision the most consequential status change in the corpus

Before this ADR, exactly one subsystem in the repository could send user data to a
party the user did not personally address: `models/`, to a configured provider,
under ADR-0004 §2. ADR-0124 added the hub's remote transport — a hop to a device
the owner enrolled, which is the owner's own machine. This ADR admits the first
boundary that can send a user's data to **an arbitrary third party the arguments
of a call select**, and it does so on a seam whose recipients are chosen per call
from arguments a model produced.

ADR-0017 §4 is candid about what that costs and about the weakness of what
enforces it:

> A second exit point is a second thing that can be got wrong. And the mechanical
> enforcement backing "designated" is weaker than the word suggests: **an import
> contract is a net, not a proof.**

Nothing here upgrades that. What §4's attestation establishes is that the fourteen
properties §3 asked for hold in the tree, not that the boundary is beyond defeat —
and §6 carries every residue the corpus leaves open rather than absorbing it into
a claim of completeness.

## Decision

### 1. The seam, named and designated

> **Normative.** The `tools/` integration egress seam ADR-0017 §1 approved and §2
> left undesignated is the module `ai_assistant.tools.egress`, and on this ADR's
> merge it is **designated**. It may transmit user data off the device, under
> ADR-0017 §1's rule as ADR-0124 §1 restates it, and it is the only module under
> `ai_assistant.tools` that may.

> **Normative.** No other module, package or component acquires egress permission
> from this ADR. `ai_assistant.tools.egress` is designated by name; a module added
> beside it later is not designated by proximity, by being imported from it, or by
> holding transport of its own, and a lane that needs a second designated module
> needs an ADR that designates it.

> **Normative.** Designation is of the module as ADR-0147 §3's first clause fixes
> it — **one module, not a package**, holding outbound transport and nothing else.
> A lane that converts `ai_assistant.tools.egress` into a package, or moves
> transport out of it into a neighbour, has moved the designated boundary and
> needs an ADR to do so.

The name is ADR-0147 §3's, which is where ADR-0017 §2 assigned it ("Naming it is
the integration ADR's job"). What this section adds to that name is the status
ADR-0147 §3's fifth clause expressly withheld.

### 2. What designation does not authorise

This is the section a reader in a hurry will misread, so it is stated before the
attestation rather than after it.

> **Normative.** Designation registers no tool. `ai_assistant.tools.send_email`
> remains a declaration bound to no connected account and absent from
> `build_default_registry`, and its callable continues to refuse until a lane
> registers a tool against a connected account. No lane reads this ADR as
> registering one, and no tool becomes registered by this ADR's merge.

> **Normative.** Designation approves no destination, no recipient, no account and
> no payload. Every send remains subject to ADR-0148's per-call machinery whole:
> §1's single route through `ToolInvoker.invoke`, §3's recipient authorisation
> tracing to a user act, §4's whole-set rule, §7's positional credential gate,
> §8's approver and the two floors, and §9's claimed step. This ADR relaxes none
> of them and is cited toward none of them.

> **Normative.** Designation lifts no obligation ADR-0016 imposes on a tool
> declaration. A tool registered at this seam declares its reach under ADR-0016
> §1, declares a non-empty `discloses` under ADR-0148 §8's second clause, and is
> gated by ADR-0021 §5's floor on every call. A declaration that would not have
> loaded before this ADR does not load after it.

> **Normative.** The first send from any integration is gated exactly as every
> later send is. There is no first-use exemption, no configuration that grants a
> standing authorisation for a recipient, and no route by which designation
> pre-authorises anything.

> **Normative.** No lane cites this ADR toward a change to `models/`. ADR-0017
> §2's three pre-existing `models/` gaps — the unpinned transport endpoint (#83's
> `models/` half), the ungated Tier 0 credential read (#74), and the unpinned
> model-artifact fetch (#89) — are untouched, neither closed nor made worse, and
> this ADR asserts nothing about them.

**The practical consequence, stated plainly.** After this merge the tree still
transmits nothing, because nothing is registered. What changes is that a
registration lane is no longer blocked by ADR-0017 §2 — it is blocked only by its
own work. That lane is the exit-QA registration lane and it follows this merge.

### 3. How this attestation was made, and what a row of §4 means

This section is a description of method and is **not normative** (ADR-0089 §1).

Each row of §4 states three things:

- **Mechanism** — the ratified decision the property is required by, cited to its
  ADR and section.
- **Code** — the module, class, function or test at `origin/main` in which the
  property holds. Cited as ADR-0088 §5 requires: the enclosing symbol, never a
  line number.
- **Evidence** — how it was checked. Where a test is the discharge, the test was
  run and its result is stated. Where a check is the discharge, the check was run.
  Where the discharge is the *absence* of something, the search that established
  the absence is named.

**A row says the property holds; it does not say the property is unbreakable.**
Condition 1's contract is a net (ADR-0017 §4), condition 5's pin rests on the
platform trust store, and condition 12's reconciliation depends on a recovery scan
running. Each row that has such a limit states it in the row rather than in a
footnote.

**Citation discipline, because three of the source ADRs forbid the obvious move.**
ADR-0147 §3 says "no lane may cite this ADR toward any of them"; ADR-0150 §11 says
"it supplies the `core` value conditions 8 and 10 need and no lane cites it
further"; ADR-0152 §12 says "no lane cites this ADR toward designation". Those
clauses forbid citing a *document* as a condition's discharge, which is exactly the
error §3's closing sentence is written against. They are honoured here as follows:
**what discharges a condition is always the code.** A prior ADR is named in the
*Mechanism* column, as the decision the code implements and against which the code
was read — which is the use ADR-0017 §3 itself contemplates when it says "the
invocation and `permissions/` ADRs own the mechanisms and may satisfy any of them
however they judge best". No row names a document in its *Code* or *Evidence*
column, and no row would survive if its ADR were the only thing behind it.

### 4. The fourteen conditions, attested

| # | ADR-0017 §3 condition (its own words) | Verdict |
|---|---|---|
| 1 | A named seam and an import-linter contract pinning it (#66) | **HELD** |
| 2 | Per-call gating that runs before transmission, not merely a declared ceiling | **HELD** |
| 3 | Recipient authorisation that traces to a user decision or a standing user policy, bound to the resolved destination (#68) | **HELD** |
| 4 | Credential access gated, not just transmission (#74) | **HELD** |
| 5 | Transport pinned to the connected service, redirects unable to carry the request or its credential to another host (#83) | **HELD** |
| 6 | The payload bound before transmission and described inspectably after it (#57) | **HELD** |
| 7 | A named approver able to refuse | **HELD** |
| 8 | What is transmitted is bound to what was authorised, immutably, and consumed unchanged | **HELD** |
| 9 | Multi-recipient calls are authorised as one set | **HELD** |
| 10 | Destinations are canonicalised per protocol, defaulting to exact comparison | **HELD** |
| 11 | Resolving a name to an identifier is itself a gated, audited call — or is forbidden | **HELD** (forbidden branch) |
| 12 | Audit records carry an attempt identifier and an explicit outcome | **HELD** |
| 13 | Outbound payload classification is settled (#94) | **HELD** |
| 14 | Failure paths are tested, not just the happy path | **HELD** |

> **Normative.** Each of ADR-0017 §3's fourteen conditions is satisfied in code at
> `origin/main` as the subsections below attest, and the seam is designated on that
> basis and on no other. A later change that falsifies any subsection's stated
> property removes the ground on which designation rests: the lane that makes it
> either restores the property in the same change or opens an ADR reconsidering
> the designation.

#### Condition 1 — a named seam and an import-linter contract pinning it

**Mechanism.** ADR-0017 §2 requires a named module "precise enough for an
import-linter contract to pin the module" (#66). ADR-0147 §3's first clause names
`ai_assistant.tools.egress`; its third clause fixes the contract's shape — an
enumerated forbidden set, "at minimum `socket`, `ssl`, `http`, `urllib`,
`subprocess`, `asyncio.subprocess`, and every transport-bearing third-party package
this repository depends on", extended by any lane adding a transport-bearing
dependency.

**Code.** The module `ai_assistant.tools.egress` exists and holds outbound
transport and nothing else. The contract is `network transports are confined to
the tools egress seam` in `pyproject.toml`'s `[[tool.importlinter.contracts]]`. It
enumerates every module under `ai_assistant.tools` **except** the seam as a source,
with `as_packages = "false"` so that naming `ai_assistant.tools` does not pull the
seam in as a descendant.

**Evidence.** `uv run lint-imports` reports `network transports are confined to
the tools egress seam KEPT`, within `Contracts: 19 kept, 0 broken`. The
enumeration's own upkeep is itself tested: `tests/tools/test_egress_seam.py`
carries `test_the_contract_exempts_the_seam_and_nothing_else`,
`test_the_contract_forbids_the_transports_the_adr_enumerates`,
`test_every_runtime_dependency_is_classified`,
`test_the_contract_forbids_every_transport_bearing_dependency` and
`test_every_forbidden_name_is_a_module_that_exists` — so the source list and the
modules on disk cannot silently diverge, and a runtime dependency nobody classified
fails the gate. `test_exactly_one_place_in_the_seam_opens_a_connection` establishes
that `asyncio.open_connection` is named in exactly one function of the seam, and
that function is `open_smtp_channel`.

**Its stated limit.** ADR-0017 §4's "a net, not a proof" is untouched, and
ADR-0147 §3 states the universal prohibition and the contract as two clauses for
that reason. Two routes §3 names are outside the net by construction and the
contract's own comment says so: `asyncio.subprocess` is squashed into `asyncio`,
which `ai_assistant.tools.invocation` legitimately imports for ADR-0029 §4's
deadline; and `os.system` is a *call* rather than an import. The source-reading
scanner in `tests/tools/test_egress_seam.py`
(`test_no_other_tools_module_names_a_transport`,
`test_the_scanner_catches_each_form_a_launch_is_written_in`) is a second net over
both, and is not a proof either. What holds beyond both nets is ADR-0147 §3's
first clause, binding an author and a reviewer.

#### Condition 2 — per-call gating that runs before transmission

**Mechanism.** ADR-0148 §1's first clause: "No component transmits through the
seam except from a callable reached by `ToolInvoker.invoke` on a `ToolCall`
(ADR-0029 §2) whose decision authorises the request being performed. There is no
second route to the seam." §7's first clause makes a `DENY` reach no callable at
all, because a `DENY` constructs no `ToolCall`.

**Code.** `ToolRegistry.invoke` in `ai_assistant.tools.registry` runs ADR-0029 §2's
three checks before the callable is reached, in a fixed order and each against the
revalidated copy rather than the argument: `revalidated_call` first; then the
registry's own binding for the id; then `binding.definition != checked.request.tool`,
which is the registry-original comparison; then
`checked.decision.authorises(checked.request)`. Only then is `run_bound_call`
reached. `PermissionDecision.authorises` in `ai_assistant.core.types` requires
`ruling.outcome is PermissionOutcome.ALLOW`, so a `CONFIRM` or a `DENY` fails the
third check and no callable runs.

**Evidence.** `tests/tools/test_egress_failure_paths.py` opens with
`test_a_denial_performs_no_credential_read_and_no_network_io`, which is §3's own
first failure-path row, and
`test_the_undesignated_callable_still_refuses_without_reading_anything`. The
registry's own checks are covered by `tests/tools/tool_invoker_contract.py` and
`tests/tools/test_registry.py`. Full run of `tests/tools/`: **692 passed**.

**What makes this "not merely a declared ceiling".** ADR-0016 §3's `discloses` is a
ceiling declared once per tool; the gate here runs per call and reads the call's
own binding, which condition 8 fixes and condition 7's floor rules on.

#### Condition 3 — recipient authorisation traced to a user act, bound to the resolved destination

**Mechanism.** ADR-0148 §3's first clause: a ruling may be `ALLOW` only where every
member of the canonical destination set is covered by **(a)** a recorded user
decision resolving a `CONFIRM` about *this* request, or **(b)** a standing user
policy. Its second clause forecloses the near-misses by name — "a tool's own
declaration, the scope or audience of a credential, a configured base URL or host,
an allowlist the system assembled, a recipient appearing in a prior call, and a
destination this system extracted from a span it selected". Its third clause closes
limb (b) until an ADR establishes standing grants, so **route (a) is the only
available route today**.

**Code.** The destination set is bound to the ruling rather than to the tool:
`EgressBinding.canonical_destination_set` in `ai_assistant.core.types` is a derived
property over the spans' occurrences, `PermissionDecision.authorises` compares
`request.egress_binding == self.egress_binding` whole and by value, and
`PermissionDecision.from_request` transcribes the binding by deep copy so a
decision cannot name a binding the policy did not see. Limb (b) is closed in code
as well as in prose: `ThresholdActionPolicy` in `ai_assistant.permissions.policy`
consults no grant seam, and `_DISCLOSURE_FLOOR` returns `CONFIRM` for any tool with
a non-empty `discloses`, so no egress call is auto-granted and every one resolves
through a user answer.

**Evidence.** `tests/tools/egress_binder_contract.py` carries
`test_the_binding_covers_every_argument_and_carries_derived_destinations`, which
asserts the derived occurrences and their canonical forms, and
`test_the_currently_recorded_identity_is_the_one_carried`. The whole-value
comparison is exercised by the `authorises` tests in `tests/core/`. The floor is
`_DISCLOSURE_FLOOR`, a module constant no constructor argument reaches — verified
by reading `ThresholdActionPolicy.__init__`, which appends only the four
threshold rules to `list(_FLOORS)`.

**Its stated limit — and it is condition 3's whole remainder.** Issue **#68** stays
open, and this attestation does not close it. What holds today is route (a): the
user answers about *this* call, and the answer is bound to the resolved destination
set. What #68 asks about — a standing policy that could authorise a recipient
without a per-call answer — has no mechanism, and ADR-0148 §3's fifth clause fixes
what the ADR establishing one must decide before it may. Designation therefore
rests on the *stricter* half of the condition: every egress recipient is authorised
by a fresh user decision, because nothing else can authorise one.

#### Condition 4 — credential access gated, not just transmission

**Mechanism.** ADR-0017 §3: "ADR-0004 §7 gates access to Tier 0 data, so reading
the token is what needs gating; otherwise an implementation reads it, then checks,
then stops." ADR-0148 §7 gates it **by position**: an `INTEGRATION`-scoped
credential "is read only from inside a callable reached by `ToolInvoker.invoke` on
a `ToolCall`, and only after ADR-0029 §2's three seam checks have passed", and its
third clause makes the authorising decision itself the gate on that read, so no
second decision is sought.

**Code.** The only read of an `INTEGRATION`-scoped credential in the system is
`SmtpEgressTransport.transmit` in `ai_assistant.tools.egress`, which calls
`self._secrets.get(slot)` from inside the callable's own frame. That class holds a
`Secrets` face — the reading face — and never a `SecretStore`; the docstring states
why, and the constructor's annotation enforces it. The only `SecretStore` face in
`tools/` is `ai_assistant.tools.provisioning`, which **writes and deletes and never
reads**. `ai_assistant.tools.egress_binder` holds neither face, names no
`SecretName`, and reads no slot from the record it consults — it takes
connectability and identity only. `ai_assistant.tools.send_email` holds no face and
refuses before reaching any position at all.

**Evidence.** `tests/tools/test_connection_provisioner.py` carries
`test_the_provisioner_never_reads_a_credential`, which is what makes "the only read
is at the seam" a tested property rather than an observation.
`tests/tools/test_egress_failure_paths.py` carries
`test_a_denial_performs_no_credential_read_and_no_network_io`. The positional
property was additionally verified by reading every occurrence of `Secrets`,
`SecretStore` and `_secrets` across `src/ai_assistant/tools/`: the reading face
appears in `egress.py` alone.

**Its stated limit.** ADR-0148 §7's fifth clause: "This settles #74 for `tools/`
and for nothing else." Issue **#74** stays open for `models/`'s ungated
provider-credential read, which ADR-0017 §2 named as pre-existing debt and
deliberately did not gate. §2 above forbids citing this ADR toward it in either
direction.

#### Condition 5 — transport pinned to the connected service

**Mechanism.** ADR-0148 §6's last clause **binds** the endpoint and states in terms
that it does not **pin** it: "What the endpoint must be, and what a redirect may
do, is #83's and is not decided here." ADR-0150 §7 says the same about the value.
ADR-0148 §13 explains the deferral — the pin "wants an HTTP client in hand". The
pin is therefore a property of the transport module and of nothing else, and this
is the condition on which the designating ADR does the most work.

**Code.** `SmtpEgressTransport._pinned` in `ai_assistant.tools.egress` performs two
of ADR-0148 §6's four pre-transmission refusals: it refuses a binding whose
`account.reference` is not the registration's — so the record consulted is the one
the ruling was taken over — and it refuses a `transport_endpoint` that is not the
registration's, **compared as text before it is parsed**, so two spellings of one
host are two endpoints. `parse_smtp_endpoint` then refuses every form this seam
will not pin: a scheme other than `smtps` or `smtp+starttls` (there is no cleartext
form), userinfo, a path, a query, a fragment, an empty host, or a port that is not
a TCP port number. `open_smtp_channel` opens to that host and port and performs **no
MX lookup**, so no recipient's domain selects the host a credential is presented
to. `_tls_context` states `check_hostname` and `CERT_REQUIRED` explicitly rather
than relying on the default. `_SmtpSession.open` refuses to proceed where
`smtp+starttls` is required and `STARTTLS` is not advertised — there is no
cleartext fallback — and `_SmtpSession.authenticate` reads `ByteChannel.is_secure`
rather than inferring TLS from command order, so the credential is presented only
over a completed handshake. `_SmtpSession.envelope` refuses RFC 5321 §3.4's `251`
and `551` forward-path replies rather than following them; they name a mailbox at
another host and are SMTP's only in-protocol analogue of a redirect.

**Evidence.** `tests/tools/test_egress_failure_paths.py` §3-row-two carries
`test_a_bound_endpoint_that_is_not_the_configured_one_is_refused`,
`test_a_cross_host_forward_path_is_refused_and_never_followed` and
`test_the_other_forward_path_reply_is_refused_the_same_way`; the transport suite
`tests/tools/test_egress_transport.py` covers the TLS requirement and the
downgrade refusal. All pass in the 692-test `tests/tools/` run.

**Its stated limits, said rather than glossed.** #83 is written about an HTTP
client — "a configurable API base URL, or … a cross-host redirect" — and SMTP has
neither. The two rows above are the nearest protocol analogues and are tested as
what they are, not dressed as the HTTP shapes. Three residues stand: TLS
verification rests on the **platform trust store**, and no certificate pinning is
attempted, so a mis-issuing certificate authority defeats it; the transport cannot
verify that the *account* whose credential it presents is the account the identity
names, which is ADR-0148 §6's own stated residue and is not narrowed here; and
issue **#1147** records three defects in `parse_smtp_endpoint`'s port handling — a
trailing colon defaults instead of refusing, a non-ASCII digit `int()` cannot parse
escapes as a bare `ValueError`, and one it *can* parse is silently accepted. #1147
is bounded rather than closed: the endpoint is compared as **text** against the
registration before it is parsed, so a mis-parsed port cannot reach a host the
registration did not name.

#### Condition 6 — the payload bound before transmission, described inspectably after it

**Mechanism.** ADR-0148 §6's three description clauses: the request carries each
span's recorded discloser provenance; the description is **deterministic**, a
function of the arguments, both destination forms, the carried provenance and the
registry's definition, and of nothing else — "no clock, no configuration, no store
read, no network"; and it covers **every span the call transmits**, with a
callable that finds itself about to transmit an uncovered span refusing instead.
ADR-0150 §4, §5, §6 and §10 fix the value: what a span is, how an argument
decomposes, what `extent` counts, and that the description "holds no content".

**Code.** `EgressSpan` and `EgressBinding` in `ai_assistant.core.types`; the
derivation is `EgressBindingSeam._spans_of` in
`ai_assistant.tools.egress_binder`, which is reached only after the detached copies
are captured and which reads no clock, no configuration and no network — its one
suspension is the connection-record read. The description's **authorisation-time**
face is therefore fixed before the ruling. The **callable-side** half is
`SmtpEgressTransport._check_spans_cover`, which refuses a message carrying a text
span the approved description does not cover, and `smtp_message`, which refuses an
argument key the seam does not transmit — so an undescribed span cannot reach the
wire through an unexpected argument either. `ActionRequest`'s validator holds the
parameter-relative invariants, including that every span's `extent` is
**recomputed from `parameters`** rather than taken as supplied.

**Evidence.** `tests/tools/egress_binder_contract.py`:
`test_the_binding_covers_every_argument_and_carries_derived_destinations`,
`test_an_undescribed_key_is_refused_and_never_rendered`,
`test_a_key_admitted_only_by_additional_properties_is_still_refused`,
`test_a_named_span_carries_its_origin_and_every_other_is_system_selected`.
`tests/tools/test_egress_failure_paths.py`:
`test_a_payload_span_the_description_does_not_cover_is_refused`,
`test_a_second_undescribed_span_cannot_borrow_another_spans_extent`, and
`test_the_payload_is_the_arguments_and_there_is_no_second_copy_to_substitute` —
the last of which is the one that matters most, because it holds the property that
there is no independently mutable rendered payload beside the binding.

**Its stated limit.** ADR-0148 §13 and §10 both leave the **artifact's
granularity** to issue **#57** — "record ids and field names against counts per
tier", its interaction with ADR-0004 §6's deletion rules, and whether it is what
`permissions/` approves or a projection of something richer. #57 stays open. What
is attested here is §3's own words: the payload is **bound before transmission**
(the binding is fixed in the request before `ActionPolicy.decide`) and **described
inspectably after it** (the description is transcribed into the recorded decision
and states, per span, its argument, position, provenance, extent, tier where its
field establishes one, and both destination forms). §3's parenthetical worry — "a
digest binds the payload while leaving an auditor unable to tell one memory record
from the whole database" — is answered: the description is per-span and carries
extents and provenance, not one digest.

#### Condition 7 — a named approver able to refuse

**Mechanism.** ADR-0148 §8's first clause names the authority and the approver:
"The authority to refuse an egress call is `ActionPolicy`, in `permissions/`. The
named approver whose refusal it must be able to carry is **the user**, reached by a
`CONFIRM` that parks the step and answered through an interface, never by the turn
on the user's behalf." Its second clause requires a tool registered at the seam to
declare a **non-empty `discloses`**, so ADR-0021 §5's floor bites on every egress
call.

**Code.** `_DISCLOSURE_FLOOR` in `ai_assistant.permissions.policy` is a `_Rule`
whose `applies` is `lambda tool: bool(tool.discloses)` and whose outcome is
`PermissionOutcome.CONFIRM`. It is a **module-level constant**, and
`ThresholdActionPolicy.__init__` builds its rule list as `list(_FLOORS)` plus the
four configurable threshold rules — so no constructor argument can reach it and no
deployment can configure it away. The combination is a maximum over outcomes, so
the floor cannot be diluted by a more permissive threshold. `SEND_EMAIL` in
`ai_assistant.tools.send_email` declares `discloses=(DataTier.PERSONAL,)`,
non-empty.

**Evidence.** `tests/tools/test_egress_failure_paths.py` closes with
`test_the_tool_the_registry_would_bind_still_declares_what_it_discloses`, which its
own docstring explains is there because otherwise "the approver ADR-0017 §3
requires is nobody". The floor's un-configurability was verified by reading
`ThresholdActionPolicy.__init__` and `_FLOORS` directly: `_FLOORS` is a
module-level tuple and appears in the constructor only as `list(_FLOORS)`.

**What makes this "able to refuse" rather than merely "informed".** ADR-0017 §3 is
explicit that "an inspectable record makes an overbroad send visible, not
refusable". The refusal is real because the outcome is `CONFIRM`, which parks the
step rather than proceeding, and the step resumes only on a recorded resolution.

#### Condition 8 — what is transmitted is bound to what was authorised, immutably, and consumed unchanged

**Mechanism.** ADR-0148 §6 binds the decision by id and the other three facts as one
value. ADR-0150 §1 makes the binding **one** value rather than four fields; §8
makes every model in the surface `frozen=True` with `extra="forbid"`; §9 adds
exactly one conjunct to `authorises`, compared **whole and by value**, and makes
`from_request` transcribe by deep copy while `ActionRequest` detaches at
validation. ADR-0152 §5 makes the seam **derive** every field and accept none, and
§7 makes `rebind` refuse unless the binding it derived **equals** the approved one.

**Code.** `EgressBinding`, `EgressSpan`, `EgressDestination`,
`CanonicalDestination` and `BoundAccount` in `ai_assistant.core.types`, each
`frozen=True`, `extra="forbid"`, `hide_input_in_errors=True`.
`PermissionDecision.authorises` carries the conjunct
`request.egress_binding == self.egress_binding` as the fifth of five.
`PermissionDecision.from_request` transcribes it. `EgressBindingSeam.bind` and
`.rebind` in `ai_assistant.tools.egress_binder` derive it and accept no part of it —
there is no argument through which a destination, span, extent, tier or binding
could be supplied. At the seam, `SmtpEgressTransport.transmit` reads the account,
the endpoint and the authorised destination set **from the binding** and re-derives
none of them, and §3's "at minimum" list is covered exactly: the connected account
(`BoundAccount`, identity **and** reference), the canonical destination set (derived
from the carried occurrences), the approved payload description (`spans`), and the
decision (by id, via `ToolCall.decision`).

**Credential values excluded**, which §3 requires in terms: `BoundAccount` carries
identity and reference only; ADR-0150 §7 forbids a `SecretName`, its `name` or any
keyring-identifying string anywhere in the surface; and the slot is obtained from
the connection record at read time and is **never carried in the binding**, so
nothing compares one against a binding. `SmtpEgressTransport._slot_of` reads it from
the record.

**Evidence.** `tests/tools/egress_binder_contract.py` carries the substitution and
bypass battery:
`test_a_tool_mutated_during_the_read_changes_neither_derivation_nor_result`,
`test_parameters_mutated_during_the_read_change_no_span_and_no_refusal`,
`test_an_approved_binding_mutated_during_the_read_changes_nothing_it_decides`,
`test_an_approved_binding_built_by_model_construct_is_refused`,
`test_an_approved_binding_rewritten_after_construction_is_refused`,
`test_the_returned_call_carries_the_tool_and_parameters_it_derived_under`.
`tests/tools/test_egress_failure_paths.py` carries the seam's half:
`test_a_binding_naming_another_connection_is_refused_on_the_same_identity`,
`test_a_transport_endpoint_that_moved_is_refused`,
`test_a_reprovisioning_landing_inside_the_credential_read_discards_it`,
`test_an_a_to_b_to_a_sequence_across_the_read_is_caught_by_the_revision`,
`test_a_second_read_that_cannot_be_answered_is_treated_as_a_change`.

**Its stated limit.** ADR-0148 §6's own last-but-one clause is honoured rather than
improved on: the clauses guarantee that no byte is transmitted under a credential
read across a provisioning act, none under an identity other than the bound one,
and none under an incomplete act — they do **not** guarantee that no credential is
ever read for a call later refused, nor that no byte is transmitted after a
provisioning act is recorded. The implementation is in fact stricter on the first
point (every refusal decidable from the binding and arguments alone runs before the
credential read, in `transmit`'s own ordering), and that strictness is a property of
the code rather than a bound the clause gives.

#### Condition 9 — multi-recipient calls are authorised as one set

**Mechanism.** ADR-0148 §4's three clauses: the canonical destination set is
authorised as a **single** value with no partial `ALLOW`; where any member is
uncovered the **whole** call is refused, with no narrowing offered as an
alternative; and no component adds to, removes from, substitutes within or reorders
the set between the ruling and transmission — "the callable transmits to every
member of the bound set and to no other recipient".

**Code.** `EgressBinding.canonical_destination_set` is one derived, deduplicated,
totally ordered tuple; `authorises` compares the binding whole, so a set that moved
fails the comparison rather than a member being examined.
`SmtpEgressTransport._authorised_message` reads the check as a **set equality in
both directions** — `if set(envelope) != bound` — so a member added after the ruling
and a member silently dropped from it fail alike. `_SmtpSession.envelope` issues one
`RCPT TO` per bound recipient and, on a refusal of any one, raises rather than
proceeding: **no `DATA` follows a refused `RCPT`**, so the remainder is never
delivered to.

**Evidence.** `tests/tools/test_egress_failure_paths.py`:
`test_a_recipient_added_after_the_ruling_is_refused_rather_than_transmitted`,
`test_a_recipient_dropped_after_the_ruling_is_refused_too`,
`test_a_far_end_refusing_one_recipient_fails_the_whole_call`, and
`test_no_narrower_set_is_constructed_from_the_remainder`. The last is the one §3's
words most directly ask for — "an unauthorised member fails the whole call rather
than being silently dropped from it" — and #93 item 2's reason is the one the test
docstring gives: "partial success is the hardest failure to notice afterwards".

**One detail worth stating, because it is easy to get wrong.** `bcc` recipients are
envelope recipients and are authorised like any other:
`OutboundEmail.recipients` concatenates `to`, `cc` and `bcc`, and `send_email`'s
schema marks all three `x-egress-destination`. A blind copy is blind to the other
recipients, never to the approver.

#### Condition 10 — destinations canonicalised per protocol, exact where equivalence is unproven

**Mechanism.** ADR-0148 §2's second clause: "Where the protocol does not establish
that two distinct supplied forms denote the same recipient, the canonical form is
the supplied form unchanged and comparison against it is byte-exact." Its fourth
clause requires **both** forms to be carried and to appear in the description; its
sixth puts the computation in **one** place per protocol. ADR-0150 §3 fixes
`DestinationProtocol`'s membership at `SMTP` alone and states exactly what `SMTP`
asserts: local parts **byte-identical**, domains equal after **ASCII lowercasing**.

**Code.** `ai_assistant.tools.destinations` is the one canonicaliser; `canonicalise`
lowercases the domain and copies the local part byte for byte.
`_check_smtp_local_part` refuses everything RFC 5321 §2.4 leaves to the receiving
host — a quoted local part, a comment, an address literal, a local part outside RFC
5322 §3.2.3's atext, a leading, trailing or doubled dot — rather than guessing at an
equivalence. `EgressDestination` carries `supplied` and `canonical` as separate
required fields, so both are in the request and both reach the record.
`EgressBinding._one_supplied_form_canonicalises_one_way` refuses a binding carrying
two occurrences that canonicalise one supplied form two ways. The seam and the
binder reach the *same* function: `SmtpEgressTransport._canonical` and `_sender` both
call `ai_assistant.tools.destinations.canonicalise`, so the answer at transmission
is the answer the binder got.

**Evidence.** `tests/tools/test_egress_failure_paths.py` §3-row-three:
`test_canonicalisation_folds_the_domain_and_never_the_local_part`
(parametrised `domain-folds`, `domain-folds-whole`, `local-part-does-not`),
`test_a_form_whose_equivalence_is_unproven_has_no_canonical_form` (parametrised
`a-name-needing-resolution`, `quoted-local-part`, `address-literal`, `two-in-one`,
`display-name`), and
`test_the_wire_carries_the_canonical_form_and_the_record_keeps_the_supplied_one`.
`tests/tools/egress_binder_contract.py` adds
`test_every_implementation_canonicalises_the_corpus_identically` and
`test_every_implementation_refuses_the_same_forms`, which hold the production
canonicaliser and the canonical fake to one corpus — necessary because
`lint-imports` forbids `testing` to import `tools`, so the two are independent by
design.

**Its stated limit.** ADR-0150 §3 routes the supplied↔canonical **correspondence**
check to surface (b), and ADR-0152 §5 discharges it *by construction* rather than by
comparison — the seam derives every occurrence with its own canonicaliser, so a
caller has no route by which to present one that disagrees, and on the resuming path
`rebind`'s whole-value equality performs it. Both halves were verified in code.
Adding a further `DestinationProtocol` member needs a ratified contract ADR of its
own (ADR-0150 §3), and this ADR adds none and widens `SMTP` not at all.

#### Condition 11 — resolving a name to an identifier is a gated audited call, or is forbidden

**Mechanism.** ADR-0017 §3 offers two branches. ADR-0148 §5 takes the **first** —
resolution is itself an egress call, "a registered tool with its own declaration,
its own `ActionRequest`, its own decision, its own claimed step and its own audit
record" — and its second clause fixes the three permitted sources of a destination,
with "no fourth source". Its third clause forbids a fall-through: "A resolution that
fails, is refused, or is denied never falls through to a send."

**Code.** In the tree as designated, the **second** branch holds as a matter of
fact: **no resolver exists**. `ai_assistant.tools.egress_binder` performs no network
I/O, reads no clock and resolves nothing (ADR-0152 §10's clause, enforced by the
module holding no such call); `open_smtp_channel` performs no MX lookup, so no
recipient's domain selects a host; and `ai_assistant.tools.destinations` **refuses** a
form whose equivalence is unproven rather than looking it up — a bare name has no
canonical form and is refused before the ruling. There is therefore no ungated side
channel, because there is no channel.

**Evidence.** The absence was established by searching every module under
`src/ai_assistant/tools/` for a resolution, lookup or name-service call: the only
occurrences of "resolve"/"lookup" are a registry id lookup, a store's
latest-entry lookup, and prose in docstrings stating that no MX lookup is
performed. Positively:
`test_a_form_whose_equivalence_is_unproven_has_no_canonical_form[a-name-needing-resolution]`
and `test_an_unresolved_name_cannot_reach_the_wire_even_in_an_argument` in
`tests/tools/test_egress_failure_paths.py` — the second being §3's own fourth row,
"a failed resolution does not fall through to a send".

**What this attests, precisely.** Not that ADR-0148 §5's gated-call route is
implemented — it is not, because no resolution call exists to implement. What is
attested is §3's condition as written, which is satisfied by **either** branch: no
name-to-identifier resolution happens at all, and a destination that would need one
is refused. A lane that later adds a resolver must build it as ADR-0148 §5's first
branch requires; it does not inherit permission from this row.

#### Condition 12 — audit records carry an attempt identifier and an explicit outcome

**Mechanism.** ADR-0148 §9: "Every transmission through the seam happens under a
committed `→ RUNNING` claim on a plan step whose `approval_ref` is the authorising
decision's id. The **attempt identifier** ADR-0017 §3 requires is that step
execution." Its third clause fixes the four outcomes as the step's, and its fourth
names the reconciliation path: "ADR-0014 §4's recovery scan, which finds a durable
`RUNNING` and records `INDETERMINATE`. A designated seam adds no reconciliation path
of its own."

**Code.** `StepExecution` in `ai_assistant.core.types` carries `step_id`, `attempts`,
`approval_ref` and `status`; `StepStatus` carries `PENDING`, `SUCCEEDED`, `FAILED`
and `INDETERMINATE`, which are §3's four. `StepExecution._claimed_step_is_authorised`
requires `approval_ref`, `bound_tool`, `started_at` and at least one attempt on any
claimed step, so an attempt that may have caused an effect is correlatable with the
decision that authorised it — including an automatic grant, which §3's concern about
a silent action needs. `PermissionDecision.step_id` is set on every egress decision,
so the trail's record and the plan record resolve to each other in both directions.
The reconciliation is `ai_assistant.planning.execution`'s recovery step, whose
docstring is "Mark every `RUNNING` step `INDETERMINATE`, for crash recovery."

**The seam's own half** is the distinction §3 names — "otherwise a timeout is
indistinguishable from a successful disclosure". `IndeterminateTransmissionError` in
`ai_assistant.tools.egress` is raised in exactly one window: the payload and its
terminating `.` have been written and the server's verdict could not be read. It is
deliberately **not** a subclass of `EgressTransportError`, every member of which is
a refusal that transmitted nothing — so an unknown disclosure cannot be caught and
read as one that did not happen. `_SmtpSession.data` catches `OSError` there and
nowhere else in the class, for the same reason.

**Evidence.** `tests/tools/test_egress_failure_paths.py` §3-row-seven:
`test_a_send_interrupted_after_the_payload_is_indeterminate`,
`test_indeterminate_is_not_a_refusal_and_cannot_be_caught_as_one`,
`test_a_refused_send_is_distinguishable_from_an_indeterminate_one`,
`test_a_non_250_verdict_after_the_payload_is_also_indeterminate`,
`test_a_read_that_raises_after_the_payload_is_indeterminate_too` (parametrised
`reset`, `timeout`, `oserror`),
`test_a_write_that_fails_while_sending_the_payload_is_indeterminate` (parametrised
`reset`, `timeout`), and — the control that makes the others mean something —
`test_a_socket_error_before_the_payload_stays_a_failure`.

#### Condition 13 — outbound payload classification is settled

**Mechanism.** ADR-0017 §3 states this condition as a question about the corpus —
classification "**is settled**" — and §9 confirms it is a condition rather than a
mere deferral. ADR-0146 settles it, and its header says so in terms: it "**settles**
ADR-0017 §3's outbound-payload-classification condition and **discharges nothing
else**". Issue **#94 is closed**.

**The named attack, and why it is blocked.** §3's own words: "an implementation
could classify a pasted OAuth token as Tier 1 because it arrived in conversation,
pass inspection, and disclose a credential under weaker policy." ADR-0146 blocks
each step. §1's first clause: a value's tier "is not changed by who disclosed it, by
the medium it arrived in, or by which subsystem holds it" — so the token is not
reclassified. §5's fourth clause: "A payload description or an audit record states
**no tier** for a user-authored free-text span … and it does not report the span as
Tier 1" — so it never acquires the Tier 1 claim the attack needs. §5's fifth clause:
"No gate, policy or approval treats a user-authored free-text span as having cleared
a tier check" — so there is no inspection for it to pass.

**Code.** `DiscloserProvenance` in `ai_assistant.core.types` carries ADR-0146 §1's two
members with **no default**, so a lane that never wired provenance through cannot get
the safe answer for free. `EgressSpan.tier` is `DataTier | None`, absent exactly where
the field establishes no tier. `ai_assistant.tools.egress_declaration`'s `TIER_KEYWORD`
is read only on the immediate subschema of a top-level property, and
`ai_assistant.tools.send_email`'s schema states it on `to`, `cc` and `bcc` and
**omits it on `subject` and `body`** — which is ADR-0146 §5's own worked example
("a message body, a note, a subject line" establishes none).
`EgressBindingSeam._spans_of` writes `DiscloserProvenance.SYSTEM_SELECTED` for every
span the carried provenance does not name, which is ADR-0146 §2's fail-closed rule
discharged by a component writing it rather than by a field default. And the
"weaker policy" the attack ends in does not exist: `_DISCLOSURE_FLOOR` returns
`CONFIRM` for `send_email` unconditionally, reading `discloses` and never a span's
tier, so no span's tier — stated or absent — can clear anything.

**Evidence.** `tests/tools/egress_binder_contract.py`
`test_the_binding_covers_every_argument_and_carries_derived_destinations` asserts
`located[("body", None)].tier is None` beside `first.tier is DataTier.PERSONAL` for
a recipient span — the two halves of ADR-0146 §5's field test in one case.
`test_a_named_span_carries_its_origin_and_every_other_is_system_selected` holds the
carried-never-derived rule, and
`test_a_provenance_entry_naming_no_span_is_refused_rather_than_dropped` holds the
refusal that keeps a caller and the derivation from disagreeing silently.
`tests/tools/test_send_email.py`
`test_every_recipient_argument_declares_both_keywords_and_no_other_does` asserts the
keyword map over the **whole** `properties` object, so an argument added later
without a declaration fails there rather than reaching the seam undeclared.

**ADR-0146 §6's obligation on this lane, discharged.** §6's first clause binds "the
lane that designates the `tools/` seam" to record each span's discloser provenance
with the payload it binds before transmission and to carry it into the audit record.
It is discharged by the shape ADR-0150 §5 chose: the provenance **is** a field of
`EgressSpan`, the spans are the binding, the binding is fixed in the `ActionRequest`
before `ActionPolicy.decide`, and `PermissionDecision.from_request` transcribes it
into the recorded decision, which `ai_assistant.permissions.audit` persists and
`_revalidated` round-trips. No separate carriage and no join were needed, which is
what §6 left open and ADR-0150 §5 closed.

**Its stated limits — three, and the first was found by writing this ADR.**

**(a) ADR-0146 §9's required test is not in the tree — issue #1150.** §9 carries one
marked clause, obliging "a lane that implements §5 for a payload description" to ship
a test that a user-authored free-text span **carrying a well-formed credential** is
described with its provenance and no tier, and that no gate treats it as tier-cleared;
it adds that "a test asserting only that the span is present does not satisfy this
clause". No test in the tree satisfies it. The two halves exist in two different tests
over two different spans, with no credential in either: the `tier is None` assertion
sits on a `SYSTEM_SELECTED` span, and the `USER_AUTHORED` case collects `provenance`
and never asserts `tier`. `grep -rn "ADR-0146"` across `src/` and `tests/` returns
twenty-seven hits and **none cites §9**.

This is recorded as debt rather than as a failure of condition 13, on three
independent grounds, each stated rather than assumed.

**It is a different lane's obligation, and §9 says whose in its own list.** The
marked clause's subject is "a lane that implements §5 **for a payload description**"
— the binder lanes that built the description (#1120, #1131, #1135). §9's prose then
enumerates what each lane owes, and the entry for **this** lane names three things
and does not name the test: "**The lane that designates the `tools/` seam** owes §6
in full, owes §4's third and fourth clauses their enforcement point in the per-call
authorisation, and owes the choice between a caller-stamped and a producer-declared
provenance marker an argument against ADR-0094 §5's rule that a producer may not
declare its own standing." All three are discharged below.

**Reading it as a fifteenth designation condition is forbidden by ADR-0146 itself.**
§8's first marked clause: "No lane reads this ADR as **adding a condition to
ADR-0017 §3's list**, as relaxing one, or as attesting that any of them is
satisfied." ADR-0017 §2 fixes the criteria exhaustively — "every condition in §3
holds in code **and** a later ADR names the seam module, attests each condition is
satisfied and how, and records the transition" — and §3's list is fourteen. An
unmet obligation elsewhere in the corpus is debt against the lane that owed it, not
a bar on this one.

**The property the clause asks a test for holds, and was verified here directly.**
The free-text spans carry no tier (the schema omits `x-egress-tier` on `subject` and
`body`), and §5's fifth clause holds *structurally* rather than by policy —
`grep -rn "\.tier"` across `src/ai_assistant/permissions/` and
`src/ai_assistant/orchestration/` returns **nothing**, and `.spans` is read nowhere
outside `core/types.py`, `tools/egress*` and `testing/egress.py`. **No gate in the
tree reads a span's tier at all**, so no span — tiered or untiered — can clear one.
What #1150 asks for is the artifact, not the behaviour, and adding it would be a
change under `tests/` that this lane's fence excludes.

**(b) No `USER_AUTHORED` span is reachable on the live path.**
`AttemptRunner._bound` in `ai_assistant.orchestration.runner` passes
`CarriedProvenance(spans={})` unconditionally, and says why in its own docstring:
ADR-0152 §5's named residue, "nothing in this tree records a span's origin, so every
span the seam describes today is `SYSTEM_SELECTED`". That is the fail-closed answer
ADR-0146 §2 requires and an under-statement of what a user typed. It is safe in the
direction that matters and is carried in §6.

**(c) ADR-0146 §5's third clause is undischarged in code**, and two ratified ADRs say
so in marked clauses: ADR-0150 §6 ("no lane cites this ADR, or the `tier` field, as
discharging it") and ADR-0152 §12 ("the `x-egress-tier` keyword does not discharge
it"). A value this system holds as Tier 1 and places into `body` is described with an
extent and a provenance and **no tier**, so an approver does not learn its tier.

**None of the three defeats this condition**, for reasons stated rather than assumed:
§3 writes the condition as classification **being settled**, and ADR-0146 settles it
(#94 is closed); and the attack §3 names is blocked at three independent points above,
none of which depends on (a), (b) or (c). What (c) costs is information to the
approver, not a gate — every such call is still `CONFIRM`, and the span is still
described and counted.

#### Condition 14 — failure paths are tested, not just the happy path

**Mechanism.** ADR-0017 §3's own seven rows, quoted in full at the head of the test
module. ADR-0148 §10 classifies its own contribution as "**Fixes the matrix, leaves
the tests**", and §14 binds the implementing lane to §3's list and to the rows
ADR-0148 adds.

**Code and evidence.** `tests/tools/test_egress_failure_paths.py` is organised as
**seven sections in §3's own order, named after its own words**, so that this ADR
could walk the list rather than reconstruct it. Its module docstring quotes §3's
condition verbatim as a block quote. Run at `origin/main`:

```text
tests/tools/test_egress_failure_paths.py ....................... [100%]
51 passed in 0.46s
```

Row by row, with the test that carries it:

| §3's row | Test |
|---|---|
| denial performs no credential read and no network I/O | `test_a_denial_performs_no_credential_read_and_no_network_io` |
| a hostile base URL … refused without the credential travelling | `test_a_bound_endpoint_that_is_not_the_configured_one_is_refused` |
| … and a cross-host redirect | `test_a_cross_host_forward_path_is_refused_and_never_followed`, `test_the_other_forward_path_reply_is_refused_the_same_way` |
| canonicalisation boundaries resolve as the protocol says | `test_canonicalisation_folds_the_domain_and_never_the_local_part`, `test_a_form_whose_equivalence_is_unproven_has_no_canonical_form` |
| a failed resolution does not fall through to a send | `test_an_unresolved_name_cannot_reach_the_wire_even_in_an_argument` |
| destination, payload and transport cannot change between authorisation and transmission | `test_a_recipient_added_after_the_ruling_is_refused_rather_than_transmitted`, `test_a_payload_span_the_description_does_not_cover_is_refused`, `test_a_transport_endpoint_that_moved_is_refused` |
| a multi-recipient call with one unauthorised member fails entirely | `test_a_far_end_refusing_one_recipient_fails_the_whole_call`, `test_no_narrower_set_is_constructed_from_the_remainder` |
| a crash-pending record is reconcilable | `test_a_send_interrupted_after_the_payload_is_indeterminate` and the six `INDETERMINATE` tests beside it, with `ai_assistant.planning.execution`'s recovery step as the reconciliation |

**Two rows are stated differently for SMTP than #83 states them for HTTP**, and the
test module says so rather than papering over it: SMTP has no base URL and no
redirect, so the nearest thing to a hostile base URL is a bound endpoint that is not
the tool's configured one, and the nearest thing to a redirect is RFC 5321 §3.4's
forward-path reply. Both are tested as what they are.

**The wider suite.** `tests/tools/` runs **692 passed** at `origin/main`. ADR-0148
§14's additional rows bind *its* implementing lanes rather than being ADR-0017 §3
conditions, and this ADR attests §3's list; the corresponding tests were verified to
exist across `tests/tools/egress_binder_contract.py`,
`tests/tools/connection_provisioner_contract.py` and
`tests/tools/test_connection_provisioner.py` — the displacement, re-read,
interrupted-act and never-reads-a-credential cases among them — and none is claimed
here as an ADR-0017 §3 discharge.

#### ADR-0146 §9's three obligations on *this* lane, discharged

§9's list names exactly three things "the lane that designates the `tools/` seam"
owes. They are not ADR-0017 §3 conditions, and they are discharged here because §9
assigns them to this lane by name.

**(i) §6 in full.** Its first clause obliges this lane to record each span's
discloser provenance with the payload it binds before transmission and to carry it
into the audit record, "so that a later reader can tell user-disclosed content from
system-selected content in a transmitted payload without re-reading the content".
Discharged by the shape ADR-0150 §5 chose rather than by anything this ADR adds:
provenance **is** a field of `EgressSpan`, the spans are the binding, the binding is
fixed in the `ActionRequest` before `ActionPolicy.decide`, and
`PermissionDecision.from_request` transcribes it by deep copy into the recorded
decision, which `ai_assistant.permissions.audit` persists and `_revalidated`
round-trips. No separate carriage and no join were needed — which is exactly what §6
left open and ADR-0150 §5 closed, and it is why the audit record can answer the
question without holding content. §6's second clause ("that obligation binds no
boundary that transmits today, and `models/` acquires no precondition") is honoured
by §2 above, which forbids citing this ADR toward `models/`.

**(ii) §4's third and fourth clauses, their enforcement point.** The third clause:
"No clause of this ADR excuses a transmission from the `tools/` seam from the
recipient authorisation ADR-0017 §3 conditions that seam on — whatever determined
the recipient, and a configured endpoint, a destination that first appeared in the
user's own words, and a destination the arguments select alike." The fourth:
"User-authored provenance is **not transitive** to a recipient determined from
content this system selected. At the `tools/` seam the recipient is the semantic
recipient the arguments select, so a user-authored span forwarded there is disclosed
by this system in respect of that recipient."

Their enforcement point in the per-call authorisation is **condition 3's ground, and
it is unconditional on provenance**: `_DISCLOSURE_FLOOR` in
`ai_assistant.permissions.policy` reads `ToolDefinition.discloses` and nothing else,
so every egress call is `CONFIRM`; and `PermissionDecision.authorises` compares the
whole binding, whose `canonical_destination_set` is derived from the occurrences the
arguments selected. **No branch anywhere in the path consults a span's provenance to
decide a recipient's authorisation** — the same search that established (a) shows
`.tier` and `.spans` are read by no gate, and `provenance` likewise reaches no
policy. So §4's conduit cannot open at this seam by construction rather than by a
rule someone has to remember: there is no code path in which a span being
`USER_AUTHORED` weakens, skips or shortens the recipient authorisation, and a
user-authored body sent to a recipient the arguments select is authorised exactly as
a system-selected one is.

**(iii) The marker is caller-stamped, and that is the argument ADR-0094 §5 asks
for.** ADR-0094 §5's rule is that "a spoke may not decide, claim, or influence the
band of what it submits, and a claim carried in a submission is not evidence of the
standing it claims" — a producer may not declare its own standing. The marker
ADR-0150 §5 fixed is **caller-stamped**, and the shape is what makes it comply: the
provenance arrives as `CarriedProvenance`, an argument to
`EgressBinder.bind` supplied by the **caller** (`AttemptRunner._bound` in
`ai_assistant.orchestration.runner`), and `EgressBindingSeam._spans_of` writes
`DiscloserProvenance.SYSTEM_SELECTED` for every span the carrier does not name. The
**tool** — the producer of the payload — has no field, keyword or argument through
which to claim `USER_AUTHORED` for its own span: `x-egress-tier` and
`x-egress-destination` are the only two declaration keywords, and neither carries
provenance. A producer-declared marker would have been ADR-0094 §5's failure exactly
— a claim carried in the submission, taken as evidence of the standing it claims.

Two further properties make the compliance more than nominal. The seam **refuses** a
carrier entry naming a span the call does not carry rather than dropping it
(`_refuse_unlocated_provenance`), so a caller and the derivation cannot disagree
silently. And the default runs in the **conservative** direction: an unnamed span
becomes `SYSTEM_SELECTED`, which is the answer that makes *this system* the discloser
and therefore keeps the recipient-authorisation obligation on us — ADR-0146 §2's
fail-closed rule discharged by a component writing the value, never by a field
default, which is why `EgressSpan.provenance` has no default at all.

#### ADR-0098 §3's two obligations on this lane, decided

ADR-0098 §3 binds this lane twice, and it is the only document outside ADR-0017
that imposes a *decision* on the designating ADR rather than a mechanism. Both are
answered here because §3 says they are this lane's, and architecture review was
right that neither could be left to silence.

**(i) The actuator clause is applied at this seam.** §3's second clause: "The clause
above binds the later ADR that designates an actuation **or egress** seam" — the
only clause in the corpus whose subject names an egress seam explicitly, which is
this one. The clause it binds is: "No actuator is selected, parameterised, or
confirmed by external content."

> **Normative.** No egress call through the designated seam is selected,
> parameterised or confirmed by external content, in ADR-0098 §1's sense of a
> recorded external span. A tool registered at this seam is not chosen by a span
> this system ingested, its arguments are not set or altered by one, and no
> confirmation of an egress call is answered by one — a `CONFIRM` is answered by
> the user through an interface (ADR-0148 §8), never by the turn and never by
> content the turn read.

What already enforces it, so the clause is not a bound with nothing behind it:
ADR-0098 §1's first clause makes a recorded external span unable to "select a code
path, set or alter a parameter, or change a policy decision"; ADR-0148 §3's second
clause refuses "a destination this system extracted from a span it selected" as an
authorisation; and the approver is the user by ADR-0148 §8's first clause. This
clause adds no condition to ADR-0017 §3's list and relaxes none, exactly as
ADR-0098 §3's second clause requires.

**(ii) The standing-authorisation question, decided rather than routed onward.**
§3's last clause: "Whether a **standing** authorisation … may cover an action a
model selected while reading external content is **not settled here**. The lane
that designates an actuation seam decides it explicitly, and may not inherit an
answer from a rule written before any actuator existed." ADR-0147 §11 repeats it in
a marked clause — "still open, still the designating lane's to answer" — and
ADR-0148 §13 records that it declined for the same reason.

**Two ratified clauses point it at this lane and one points elsewhere.** ADR-0148
§3's fifth clause routes it to "the ADR that establishes standing grants". The
tension is real and is resolved by deciding rather than by adjudicating whose it
was: an answer given here satisfies ADR-0098 §3 and ADR-0147 §11 directly, and does
not offend ADR-0148 §3's fifth clause, whose prohibition is on the standing-grant
ADR *inheriting* an answer from **ADR-0148**, its silence, or its limb (b). Nothing
forbids this ADR from setting the floor, and leaving it unanswered is what two
marked clauses forbid.

**The answer has to be decidable from recorded origin, and that is what fixes its
shape.** A first draft of this section stated the floor over the call "whose
destination, or whose payload, was selected by a model while reading external
content", and adversarial review found on round 6 that such a floor cannot be
implemented: for two identical `send_email` calls, nothing durable distinguishes a
planner run whose prompt carried an external span from one that did not, so an
authoriser could only guess. ADR-0098 made and corrected the same mistake in its own
drafting, and §12 states the constraint in terms: "§5's unobtainability argument is
an input: an answer phrased over 'output produced from external content' is not
checkable, so **whatever is decided has to be decidable from recorded origin**."
§5's finding is that "produced from external content" is "**not recoverable** once a
model's output has been recorded truthfully", and §3's own discussion adds that
stating a bound over it is "the unobtainable bound §6's second clause forbids anyone
from stating".

So the answer is **no**, stated over a fact any authoriser can evaluate — the
absence of the authorisation itself — with the condition for revisiting named:

> **Normative.** No standing authorisation — an ADR-0021 §6 standing grant, or a
> standing user policy in ADR-0017 §3's third condition — covers any egress call
> through this seam. Every egress call is authorised by a decision of the user about
> **that** call, on ADR-0148 §3's route (a).

> **Normative.** The ADR that would permit a standing authorisation to cover an
> egress call at this seam first establishes a **recorded origin** the authoriser
> evaluates at the moment it rules — a fact the request carries, never an inference
> about how a model produced it (ADR-0098 §5, §12) — and states its rule over that
> fact. Until such a surface exists and an ADR rests on it, the clause above holds
> as written.

**This is a restriction at this seam, and it is declared rather than glossed.**
ADR-0017 §3's third condition permits recipient authorisation to trace to "a user
decision **or** a standing user policy"; the clauses above satisfy it by the first
limb alone and close the second at this seam. That satisfies the condition rather
than narrowing it — §3 offers the two as acceptable sources and requires neither to
be available — but it *is* stricter than §3 obliges, and saying so is the half
ADR-0098's own faulted draft omitted when "§11 claimed it narrowed neither". It
supersedes nothing: ADR-0021 §6's standing grants are untouched everywhere else, and
ADR-0148 §3's third clause already closes route (b) for egress until a standing-grant
ADR opens it, so this clause restricts nothing that exists.

**Why no rather than yes.** Letting a standing authorisation cover such a call is
the composition ADR-0098 exists to prevent, arriving one seam later: external content
cannot select an actuator directly, but a standing grant would let it select one
*indirectly*, by choosing the recipient of a call the grant already covers. ADR-0098
§1's first clause says a recorded external span may not "change a policy decision",
and a standing authorisation is a policy decision whose extent that span would be
choosing. Answering yes would need the very predicate §5 says is unrecoverable;
answering no needs nothing. And it is far cheaper to state now than to retrofit onto
a standing-grant ADR that has already shipped a store — ADR-0098 §3's own reason for
ruling its actuator clause early, "free now and expensive later".

### 5. The transition, recorded

> **Normative.** `ai_assistant.tools.egress` passes from **approved and
> undesignated** to **designated** on this ADR's merge, and not before. Nothing
> implements against that status change until the merge (ADR-0015 §5, golden rule
> 5), and an unmerged `Accepted` on this branch designates nothing.

This ADR makes exactly **one** edit outside its own file: **one appended dated note**
in ADR-0017's header, recording that §3's fourteen conditions were attested here and
that the seam is designated. **No accepted text of ADR-0017 is rewritten**, and §3's
conditions are left exactly as ratified — a reader must still be able to see the list
as it was written, because that is what this ADR's §4 is an attestation *against*.

**ADR-0017's `Status` line is deliberately not touched, and that is ADR-0082 §2 rather
than an omission.** A first draft of this change added a `;`-joined qualifier after the
ADR-0124 pair — "`§2's tools/ seam designated by ADR-0154 (…)`" — and adversarial review
caught it on round 2. ADR-0082 §2's first clause is exactly on point: "Where an ADR's
`Status` carries the leading `Partially superseded by` token, no amendment qualifier is
written on that line. The record §1 owes is the appended dated note ADR-0070 §1 already
requires, and that is the whole of it." ADR-0017's line carries that leading token, and
ADR-0070 §4's ratified extraction invariant is what makes the qualifier actively wrong
rather than merely unnecessary: "a scope names a clause, not another ADR: it carries no
`ADR-NNNN` token, so **every `ADR-NNNN` after the leading `Partially superseded by` is a
target**." A consumer built on that sentence would have read ADR-0154 as a
partial-supersession target of ADR-0017 — which it is not, and which this ADR's own
header denies. ADR-0082's §2 discussion names the construct by shape: "a `;`-joined
qualifier after the pairs — puts an `ADR-NNNN` after the leading token that is not a
target."

So the whole record of the designation lives in the dated note, which is where
ADR-0082 §2 puts it, and the `Status` line keeps the one machine-legible fact it is
for. Nothing is lost: the note carries more than a qualifier could, and ADR-0017 §7's
own precedent — "Exactly one line of ADR-0004 was edited" — is a rule about *ADR-0001's
minimum*, not a requirement that a status line move on every occasion.

**Why ADR-0017 gets a note rather than an amendment.** ADR-0017 §2 says designation
is "Not a status amendment: a second operational egress boundary is a substantive
decision, and ADR-0001 reserves those to a new ADR." This ADR *is* that new ADR, so
the substantive act lives here; what goes on ADR-0017 is the record that it
happened, which is ADR-0070 §1's appended dated note — "reconciling an ADR with a
fact that postdates it". No decision of ADR-0017 changes, so no supersession
arises.

### 6. Residues carried forward, explicitly

Every one of these is open, is named here rather than absorbed into §4's verdicts,
and none is closed by designation.

> **Normative.** No lane reads this ADR as closing, narrowing or answering any
> residue named in this section. Each stays open on its own terms, and a lane that
> needs one resolved resolves it in its own change.

- **#57 — the payload manifest's granularity.** ADR-0148 §13's own words: record
  ids and field names against counts per tier, the interaction with ADR-0004 §6's
  deletion rules, and whether the description is what `permissions/` approves or a
  projection of something richer. Condition 6 is attested on §3's words, not on
  #57's answers.
- **#85 — an injected transport capability.** ADR-0017 §8 deferred it with three
  reasons; ADR-0148 §13 declined to reopen it, calling §1's single-route clause
  "the weaker, reviewable form of the same property". Designation does not make the
  import contract a proof, and ADR-0017 §4's honest accounting stands unamended.
- **#68 — approved-recipient policy.** Route (b) of ADR-0148 §3 is written and
  closed; only a per-call user answer authorises an egress recipient today. The ADR
  that opens standing grants owes the three decisions ADR-0148 §3's fifth clause
  names.
- **#74 — `models/`'s ungated credential read.** Settled for `tools/` by ADR-0148
  §7 and attested in condition 4; untouched for `models/`.
- **#83's `models/` half and #89** — the unpinned provider endpoint and the
  unpinned model-artifact fetch, both named by ADR-0017 §2 as pre-existing and both
  unchanged.
- **#95 — ADR-0004's residency clause, and where it actually becomes live.**
  ADR-0017 §1 declined to read it and sent the question to #95: "a write-capable
  integration puts data in a remote service by design — but answering it here would
  be narrowing a ratified clause this ADR does not supersede, which is the move §5
  exists to refuse." That reasoning is unchanged by designation and is not this
  ADR's to overturn; ADR-0124 §3 took the same route for the analogous question
  rather than narrowing or widening the clause.

  **Architecture review raised this as a blocker, and the part of it that is right
  is the timing.** ADR-0017 §1's ground for deferring was "Nothing turns on it yet:
  no tool transmits, and the seam stays undesignated until §3 holds." Half of that
  ground is now spent. The other half is not: designation **registers no tool**
  (§2), so nothing transmits on this merge and no data reaches a remote service.
  What makes the question live is a **registration**, not a designation — and that
  is the point at which it is answered, by the lane that reaches it. The clause
  binding that lane is stated at the end of this section, where a mark is a mark.
- **#1141 — ADR-0151's credential plaintext site in `orchestration`.** Open, and
  neither relied on nor closed by any row of §4.
- **#1147 — `parse_smtp_endpoint`'s port grammar.** Three defects, bounded by the
  endpoint being compared as text against the registration before it is parsed
  (condition 5).
- **#1148 — evaluating a library for the SMTP exchange.** The exchange is
  hand-written because `smtplib` is synchronous and a runtime dependency was outside
  the transport lane's fence; ADR-0147 §12 leaves the library choice to ADR-0003's
  ordinary route, with the failure-path suite as the conformance bar.
- **#1150 — ADR-0146 §9's required test is not in the tree.** Filed by this lane, on
  discovering it while verifying condition 13 rather than transcribing a prior
  table. The property holds and was verified directly; the artifact §9 obliges is
  missing. Condition 13's stated limit (a) carries the whole finding, including the
  structural ground — no gate in the tree reads a span's tier at all.
- **ADR-0152 §5's provenance residue** — nothing in the tree records a span's origin,
  so `AttemptRunner._bound` passes an empty carrier and every span the seam describes
  today is `SYSTEM_SELECTED`. Fail-closed, and an under-statement of what a user
  typed. The lane that first records an origin is the lane that closes it.
- **ADR-0146 §5's third clause** — a value the system already tiered, carried into a
  field that establishes none. Undischarged in code, said so by ADR-0150 §6 and
  ADR-0152 §12, and carried here with its consequence stated in condition 13.
- **ADR-0147 §4's fifth clause** — the ADR required before an MCP server is
  connected to over a stdio transport. Undischarged. This ADR designates a module
  for **network** transport under ADR-0017; it does not authorise a subprocess, and
  ADR-0148 §13 explains why §3's conditions "have no subject on a subprocess".
- **ADR-0152 §12's semantic residue** — a declaration naming a body field as
  destination-bearing is well-formed and wrong. Open.
- **#93** — the tracking issue for these obligations. It may be closed as tracking,
  but ADR-0017 §3's own sentence governs: "the obligations are the list above — an
  issue can be edited or closed narrowly, and the decision record has to stand
  in-repo (ADR-0001)."

**The one residue that binds a later lane rather than merely being recorded** is
#95's, because it is the only one whose subject arrives with a registration:

> **Normative.** A lane registering an integration at this seam states in its own
> change whether that integration's ordinary operation places the owner's data into
> a third-party service in the sense ADR-0004 §2's residency clause is about, and
> on what reading of that clause.

> **Normative.** Where that statement is yes, or is unclear on the residency
> clause's text, the lane does not register the integration until an ADR has
> answered #95.

> **Normative.** No lane reads an answer to #95 out of this ADR, out of ADR-0017
> §1's deferral of it, or out of the seam having been designated.

This binds the question to the moment it acquires a subject rather than settling it
here — settling it is what ADR-0017 §5 forbids, and a design fork the corpus has not
resolved is not one to decide in passing.

### 7. What is not decided here

**This ADR decides three things, and they are worth listing once** — a document
whose bulk is attestation reads as though it decides only the first. §1's
**designation** of the seam; §4's **standing-authorisation floor**, which ADR-0098
§3's last clause and ADR-0147 §11 both assign to the designating lane; and §6's
**residency gating on registration**, which binds a later lane to face #95 rather
than answering it. What follows is what this ADR does *not* decide.

> **Normative.** Beyond §1's designation, the three clauses §4 decides under
> ADR-0098 §3, and §6's three residency clauses, this ADR decides nothing. It
> registers no tool, adds no `core` name, changes no Protocol, adds no
> `DestinationProtocol` member, designates no second seam, and authorises no
> dependency. A lane needing any of those needs its own change and, where golden
> rule 5 reaches it, its own ADR.

> **Normative.** No lane reads §4's standing-authorisation floor or §6's residency
> clauses as deciding anything beyond their own terms. The floor rules on standing
> authorisation **at this seam** and settles no question about standing grants
> elsewhere, which stay ADR-0021 §6's and ADR-0148 §3's; the residency clauses
> oblige a registering lane to face #95 and answer neither #95 nor ADR-0004 §2's
> residency clause.

- **Who registers `send_email`, against which account, and how.** ADR-0152 §10
  leaves registration `tools/`-internal and uncontracted; the exit-QA registration
  lane follows this merge and is briefed against it.
- **A second designated seam, or a second protocol.** Neither follows from this
  one.
- **Anything about `models/` or about ADR-0124's hop.** §2 forbids citing this ADR
  toward either.

## Consequences

- **`ai_assistant.tools.egress` may transmit**, and it is the only module under
  `ai_assistant.tools` that may. ADR-0017 §1's rule as ADR-0124 §1 restates it now
  has all three of its boundaries operational rather than two.
- **The tree still transmits nothing on this merge.** No tool is registered, and
  `SendEmail` still raises `UndesignatedSeamError`. What changes is that the
  registration lane is unblocked; the refusal's message names ADR-0017 §2 and will
  need updating by whichever lane registers a tool, which is that lane's edit and
  not this one's.
- **ADR-0017 gains one appended dated note and no `Status` edit**, per §5 and
  ADR-0082 §2, and its §3 is left exactly as ratified. No other ADR is edited: the
  eight that supply the mechanisms are cited, not amended, and a designating ADR
  that edited its own evidence would be rewriting the record it attests against.
- **§4 becomes the thing a later change is measured against.** Its own marked
  clause makes falsifying a subsection's property a change that either restores it
  or reopens the designation. That is deliberately a heavier obligation than a
  passing test carries, because the fourteen were conditions on a permission rather
  than on a feature.
- **The conditions stay in-repo and stay the obligation**, ADR-0017 §3's closing
  paragraph having anticipated exactly the failure of treating a tracking issue as
  the record.
- **Nothing in §6's residues is closed.** A boundary that transmits under a
  complete attestation and an honest list of what remains open is what ADR-0017 §4
  asked for when it said the honest accounting is part of the decision.

### 8. Marking, review and ratification

This ADR is **marked** under ADR-0089: every obligation it imposes is a marked
clause, and unmarked text supplies none. §3, §4's table and every *Mechanism*,
*Code*, *Evidence* and *stated limit* paragraph are unmarked deliberately — they are
an attestation and an argument, which ADR-0089 §1 classifies as non-normative
however load-bearing they are. What binds is nineteen clauses: §1's three, §2's five,
§4's attestation clause plus the three ADR-0098 §3 decides, §5's one, §6's four, and
§7's two. Every one of them is a block quote at column 0 preceded by a blank line,
which ADR-0089 §2 requires — an indented one is not a mark, and one clause was moved
out of a list item in review for exactly that reason.

**Required reviews: adversarial *and* architecture.** This is a contract-surface
change in `CONTRIBUTING.md`'s sense — not because it touches `core/protocols.py` or
`core/types.py`, which it does not, but because it is the ADR deciding an egress
boundary's status, which is the surface ADR-0017 §1 and ADR-0124 §1 state. It was
drafted, reviewed and revised as `Proposed`, and the route is `CONTRIBUTING.md` →
"Finishing an ADR PR", with ADR-0130 §12, ADR-0136 §7 and ADR-0146, ADR-0147 and
ADR-0148's own notes as the worked precedents. The status flipped only once both
required reviews returned clean on **one** tree, and both were re-run on the flipped
tree for coverage. The ratification note in this ADR's header records the set that
ran and the outcome it got.

**The rounds, because an attestation ADR's review history is part of its evidence.**
Seven printed rounds, churn ratio 1.1 — the loop converged rather than reworking
itself, and four of the five findings changed the document in ways worth recording:

| Round | Lens | Finding | Disposition |
|---|---|---|---|
| 1 | adversarial | `blocker`: designating while ADR-0146 §9's required test is absent | **Contested** — §9's own list assigns that test to the lane implementing §5 for a payload description and names three *different* things the designating lane owes. Checking it surfaced that those three were unaddressed, so §4 gained the subsection discharging them. Issue **#1150** filed for the missing test. |
| 2 | adversarial | `blocker`: the `;`-joined qualifier added to ADR-0017's `Status` line | **Fixed.** ADR-0082 §2 forbids a qualifier on a line carrying the leading `Partially superseded by` token, and ADR-0070 §4's extraction invariant would have made a consumer read ADR-0154 as a supersession target. Status line left untouched; §5 records why. |
| 3 | adversarial | none | APPROVE. |
| 3 | architecture | `blocker` ×2: ADR-0098 §3's last clause undecided; ADR-0004's residency clause unresolved | **One fixed, one contested.** §4 gained the ADR-0098 §3 subsection and decided the standing-authorisation question; the residency blocker is contested on ADR-0017 §1 and §5 — settling #95 here would narrow a clause this ADR does not supersede — but its *timing* half was right, so §6 gained the clauses binding a registering lane to face it. |
| 4 | architecture | `major`: one clause stating three separable obligations | **Fixed.** Split, per ADR-0089 §2. |
| 5 | architecture | `major`: §7's "designation and nothing else" contradicted the new policy clauses | **Fixed.** §7 now names the three decisions and bounds the two new ones. |
| 6 | adversarial | `blocker`: the standing-authorisation floor stated over an unrecoverable relation | **Fixed, and it is the finding that most improved the document.** ADR-0098 §5 holds "produced from external content" unrecoverable and §12 requires an answer "decidable from recorded origin"; the floor was restated over the absence of the authorisation itself, with the recorded-origin surface named as the condition for revisiting. |
| 7 | both | none | APPROVE, APPROVE — terminal, on one tree. |

**No `blocker` or `major` was waived.** Two `blocker`s were contested with grounds
stated in the document rather than only in the pull request — round 1's on ADR-0146
§8 and §9's own assignment of obligations, and round 3's residency half on ADR-0017
§1 and §5 — and each still changed the ADR where the finding had located a real
absence beside its stated claim.
