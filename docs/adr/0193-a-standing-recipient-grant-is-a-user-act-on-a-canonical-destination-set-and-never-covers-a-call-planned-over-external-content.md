# 193. A standing recipient grant is a user act on a canonical destination set, and never covers a call planned over external content

- Status: Proposed
- Date: 2026-08-24
- Decides: the standing recipient grant ADR-0021 §6 defers as "a store, not a
  field" and ADR-0148 §3's third clause reserves — what a grant is, how the user
  establishes one, what it covers, where route (b) is evaluated, how
  `PermissionRuling.authorised_by` is made resolvable, and how a grant is
  revoked, expires and is exported.
- **Partially supersedes ADR-0154** — §4's standing-authorisation floor, item
  (ii)'s first clause, in the single respect that a user-established recipient
  grant may now cover an egress call at the designated seam under §§3–8 below.
  Everything else in ADR-0154 stands, its fourteen attestations included (§12).
- Requires **new `core` contract surface** and lands none of it (§14). Flagged
  under golden rule 5.
- Answers, in its own text and by name, the three questions ADR-0148 §3's fifth
  clause forbids this ADR to inherit: ADR-0021 §3's named precondition (§6),
  ADR-0098 §3's last clause (§4), and ADR-0146 §8's second clause (§5).
- Does **not** designate a boundary, add a condition to ADR-0017 §3's list,
  relax one, or attest that any of them is satisfied. It changes which limb of
  condition 3 is available and nothing about the condition.

## Context

### The clause that names this ADR, and the three things it says this ADR must decide itself

ADR-0148 §3's first clause permits an `ALLOW` on an egress request only where
every member of the canonical destination set is covered by **(a)** a recorded
user resolution of a `CONFIRM` about *this* request, or **(b)** a standing user
policy established by a recorded act of the user. Its third clause then closes
limb (b):

> No standing user policy authorises an egress recipient until an ADR
> establishes standing grants (ADR-0021 §6). Until it does, route (a) is the
> only available route, and no lane reads limb (b) above as ratifying, narrowing
> or pre-shaping ADR-0021 §6.

This is that ADR. Its fifth clause fixes three things it may not leave to
inference — ADR-0021 §3's named precondition on making the second source of an
`authorised_by` resolvable, ADR-0098 §3's last clause, and ADR-0146 §8's second
clause — and forbids inheriting an answer to any of them "from this ADR, from
this ADR's silence, or from limb (b)'s existence". §§4, 5 and 6 answer them.

ADR-0021 §6 states the shape and the cost: standing grants need "durable,
per-user policy state with its own data-rights obligations — a store, not a
field", the deferral is "load-bearing" because §5's disclosure floor "sends most
real tools to `CONFIRM`", and "until it lands, a disclosing tool prompts every
time, which is the correct default and a poor steady state."

### The floor this ADR lifts, and the precondition ADR-0154 put on lifting it

ADR-0154 §4, under item (ii), does not merely inherit ADR-0148 §3's closure — it
states a floor of its own and the condition for lifting it:

> **Normative.** No standing authorisation — an ADR-0021 §6 standing grant, or a
> standing user policy in ADR-0017 §3's third condition — covers any egress call
> through this seam. Every egress call is authorised by a decision of the user
> about **that** call, on ADR-0148 §3's route (a).

> **Normative.** The ADR that would permit a standing authorisation to cover an
> egress call at this seam first establishes a **recorded origin** the authoriser
> evaluates at the moment it rules — a fact the request carries, never an
> inference about how a model produced it (ADR-0098 §5, §12) — and states its
> rule over that fact. Until such a surface exists and an ADR rests on it, the
> clause above holds as written.

**The surface exists and nothing rests on it yet.** ADR-0181 §3 puts
`planned_with_external_content` on `EgressBinding`, required with no default,
fixed in the `ActionRequest` before the ruling and transcribed verbatim into the
recorded decision; ADR-0154's own dated note of 2026-08-23 records that the
precondition's first half is therefore met, that ADR-0181 "expressly declines to
lift this floor", and that "a lane citing ADR-0181 as having opened standing
authorisation has misread both". This ADR is the one that rests on it, so §4
states its rule over that fact and §12 records the partial supersession that
follows.

ADR-0181 §5 adds the floor beneath any such ADR — no standing authorisation
covers a call carrying `planned_with_external_content`, "whatever a later ADR
permits for calls that do not carry it". §4 honours it, restates it in this ADR's
own text as ADR-0148 §3's fifth clause requires, and answers the part of
ADR-0098 §3's question that ADR-0181 §5 does not reach.

### The tree, read rather than assumed

Every claim below was checked against `origin/main` at `46c5134b` while writing,
and re-checked at `9b4bd9d9`: no file this section reads had changed between the
two.

- **The binding is already at the ruling point.** `ActionRequest.egress_binding`
  carries an `EgressBinding` or `None`, and `EgressBinding.canonical_destination_set`
  is a derived property over the spans' occurrences, falling back to the connected
  account under ADR-0148 §2's third clause. So the canonical destination set is a
  fact the policy holds, by value, before it rules.
- **That derived set is already in one total order, fixed in `core`.**
  `EgressBinding.canonical_destination_set` returns
  `tuple(sorted(members, key=_destination_order))`, and `_destination_order` puts
  account members first, then selected recipients by `protocol` and then by
  `canonical` form, every string compared by Unicode code point. Its docstring
  states why the order is total: the property must be single-valued, "so a
  decision read back from the record recomputes an identical tuple". §1 adopts
  that order rather than inventing one.
- **The corpus already has the digest shape this ADR needs.** `Sha256Hex` in
  `ai_assistant.core.types` is a validated lowercase SHA-256 hex string;
  `_canonical_bytes` pins "the exact JSON form ADR-0021 §1 pins for a digest";
  and `SemanticMemory.proposal_fingerprint` is a **derived property** — not a
  stored field — taking `sha256(_canonical_bytes(projection)).hexdigest()` over a
  `model_dump(mode="json")` projection of the record's own values. §1's
  `subject_digest` is that shape, unchanged, on a second record.
- **The policy already reads the binding, but not the set.**
  `ai_assistant.permissions.policy.ThresholdActionPolicy` reads
  `request.egress_binding` for one purpose only — `_planned_with_external_content`,
  ADR-0181 §5's antecedent. It consults no grant seam, and `decide`'s own docstring
  states that "`authorised_by` is always unset: standing grants are deferred".
- **`_DISCLOSURE_FLOOR` is a module constant no constructor argument reaches**, so
  every tool with a non-empty `discloses` reaches `CONFIRM`, which under ADR-0148
  §8's second clause is every tool registered at the seam.
- **The route-(b) pointer is unvalidated, not forbidden.** In
  `ai_assistant.permissions.audit`, `_check_authorisation` requires an `ALLOW`'s
  `authorised_by` to equal its `resolves` — but it is reached only from
  `_check_resolution`, which `record` calls only where `snapshot.resolves is not
  None`. A **non-resolving** `ALLOW` carrying an `authorised_by` is therefore
  written today with no check of any kind. That is precisely the hole ADR-0021 §3's
  precondition names — "a `str` field naming an authorisation is one a policy could
  fabricate" — and §6 is where it is closed.
- **Canonicalisation is built and is not re-decided here.**
  `ai_assistant.tools.destinations` holds one canonicaliser per
  `DestinationProtocol` with RFC 5321's case rules; `CanonicalDestination` in
  `ai_assistant.core.types` has exactly two shapes, a selected recipient or the
  connected account, with equality over every field and no comparison across
  protocols; `ai_assistant.tools.egress_binder.EgressBindingSeam` derives the whole
  binding and accepts no part of it (ADR-0152 §5).
- **The grant shape has a precedent with a working split.** `SourceGrants` is the
  query face and `SourceGrantStore` the durable one; a revocation is an appended
  record carrying `revokes`, never an edit; `SourceGrant` embeds the scope it
  authorises rather than pointing at it.

### What five other runtimes do, and the one thing none of them does

#1548 surveys OpenAI's Agents SDK, LangGraph/LangChain, MCP, Claude Code and
OpenClaw against this seam. Its finding for this decision is that **no surveyed
runtime authorises a semantic recipient at all**: every standing grant is keyed on
a tool name or on a host. OpenAI's `RunContextWrapper.approve_tool(...,
always_approve=True)` records approval by tool name, so one "always" on a send
covers every future recipient; Claude Code's `allowedDomains` and OpenAI's hosted
`allowed_domains` authorise a host. Both are entries on ADR-0148 §3's list of
near-misses, and the second is #68's own attack written as a feature. Nothing
here is copied.

Four things are worth taking, and each is cited at the clause it shaped.
OpenClaw's exec approvals bind "cwd, exact argv, env binding when present, and
pinned executable path" and, where the binding cannot be fully identified,
"refuse to mint an approval-backed run rather than pretend full coverage" (§2's
sixth clause). Its allowlist entries "can only tighten config-derived
security/ask, never loosen", and Claude Code's rules evaluate deny → ask → allow
with "specificity doesn't change the order" — the monotonicity §3's fifth clause
states. Claude Code's `injectHosts` and OpenAI's `domain_secrets` bind a
credential to the hosts it may travel to *independently* of the destination
allowlist, which is the two-key shape §3's first clause takes. And OpenAI's
`_ApprovalRecord.approved: bool | list[str]` makes a standing grant and a
per-call approval different shapes in the record, which is #68's first comment
satisfied by construction and is what §6's discriminator clause does with
`resolves`.

One shape is refused by name. LangChain's `HumanInTheLoopMiddleware` admits an
`edit` decision in which the human rewrites the call's arguments and the edited
call then runs under the approval that was asked about the original. §2's seventh
clause refuses it.

### Why the source-grant precedent half transfers, argued once and not rebuilt

ADR-0148 §3 already did this work and this ADR consumes it. The half that
transfers is **the record** — a user act, stored, prospective, per-use rather
than per-source. The half that does not is **the reach**: a source grant fully
determines what is reached, whereas "after a grant over *my Gmail account*, a
model determines who receives the bytes". That asymmetry is the whole reason
limb (b) is bound to the canonical destination set rather than to the tool or the
account, and §3 below is that binding made concrete.

ADR-0097 §7's prohibition is untouched and is not a template: a `SourceGrant` may
never be cited as `PermissionRuling.authorised_by` and no `ActionPolicy` may
consult a `SourceGrants` or a `SourceGrantStore`. Nothing here relaxes that, and
the seam §7 introduces is a different one holding different records.

### What this ADR is not allowed to settle, and refuses in §13

Designation (ADR-0017 §2 and ADR-0154 §1 own it); the establishing surface's
wire and rendering contracts (ADR-0177, ADR-0178 and ADR-0186 own theirs); the
consume-on-execution step and the invocation record (ADR-0016 §7's debt, the
lane numbered ADR-0192); the transport capability (ADR-0191); a per-span origin
marker, which ADR-0181 §2's third clause forbids anyone to add on the strength of
that fact; and #1154's and #75's detection questions, which §5 names as this
decision's stated residue rather than as work it does.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

The decision in one sentence: **a standing recipient grant is a durable record of
a user act naming a canonical destination set for one declared tool until a
stated instant; it authorises the recipient and never the payload; it is
unavailable on any call this system recorded as planned over external content;
and the `ALLOW` it sources names it, so the trail says which of ADR-0017 §2's two
bases authorised the send.**

Throughout, **grant** means a `RecipientGrant` under §1, **covered** means covered
under §3, and **egress call** carries ADR-0148's meaning unchanged.

### 1. The store: three faces, one record, and no field anywhere

> **Normative.** A standing recipient grant is a durable record, `RecipientGrant`,
> in `ai_assistant.core.types`. It carries: its own `id`; the `ToolDefinition` it
> was established about, **by value**; the `BoundAccount` it was established
> against, by value; the canonical destination set it names, as a non-empty,
> duplicate-free, canonically ordered tuple of `CanonicalDestination`; the instant
> the user decided; the instant it ceases to be live; on a **granting** record,
> the `id` of the recorded `PermissionDecision` the establishing act rode
> (`established_by`); and, on a **revoking** record, the `id` of the grant it
> revokes. It carries no other field, and in particular no credential value and
> no payload.

> **Normative.** `established_by` is set on a granting record and unset on a
> revoking one, and `RecipientGrant` refuses either mispairing at construction: a
> granting record without it names no act, and a revoking record with it claims an
> establishment it is not. It is the `id` of the answered `CONFIRM`'s recorded
> decision — the same decision §2 transcribes the `tool` and the binding from —
> so a grant says **which** user act made it and not merely that one did.

> **Normative.** `established_by` is a **pointer into the audit trail** and this
> store validates it against nothing: a grant store that could read the trail
> would be a second component holding both halves of an invariant, which §1
> refuses for the trail in the other direction and for the same reason. It is
> transcribed by the caller that records, exactly as `decided_at` is, and it is
> covered by the digest rather than by a lookup.

> **Normative.** Nothing re-resolves `established_by`, at any later read, in any
> component. `AuditTrail.record`'s seven checks do not read it; no surface renders
> the act it names, resolves it, or states that the decision it names still
> exists; and no lane adds a read that does. After the user clears the **audit
> trail** it names nothing, which is the same posture §9 takes when the user
> clears the **grant** store and the same one ADR-0021 §3 states about
> `authorised_by` in terms: *"It is a pointer this contract does not verify."*
> What `established_by` is for is the **digest**, and the digest is a comparison
> between two records rather than a resolution of either.

> **Normative.** `destinations` is held in **one canonical order, validated at
> construction**, and a tuple in any other order is refused. The order is not this
> ADR's invention: it is the total order `EgressBinding.canonical_destination_set`
> already produces in `core` — account members first, then selected recipients by
> `protocol` and then by `canonical` form, every string compared by Unicode code
> point (the Context's tree reading). The canonical spelling is therefore the
> **only** spelling a grant's destination set has.

> **Normative.** Coverage stays **set membership** (§3) and is not restated over
> the order. What the order fixes is every rule stated over *identity* rather than
> over coverage — the duplicate refusal below, `record`'s subject match (§6) and
> the subject digest — each of which is written as tuple equality and each of
> which, because of this clause, means set equality. No lane repairs one of the
> three by re-stating it "as sets"; the repair is here, once.

> **Normative.** `RecipientGrant` carries a **derived** `subject_digest`, typed
> `Sha256Hex`, computed as `sha256(_canonical_bytes(projection)).hexdigest()` over
> the encoding `_canonical_bytes` already pins for `parameters_digest`, where the
> projection is this record's own `model_dump(mode="json")` with **exactly one
> key removed**, `id`. Every other field is in it — `tool`, `account`,
> `destinations`, `decided_at`, `expires_at`, `established_by` and `revokes` — and
> a field added to `RecipientGrant` by a later ADR is in it too unless that ADR
> removes it by name.
> It is a **property and never a stored field**, for the reason
> `EgressBinding.canonical_destination_set` is one: a stored digest can be read
> back disagreeing with the fields it was computed from, and nothing downstream
> would catch it. It reads no clock, no store and no seam; it is total and never
> raises.

> **Normative.** The rule is stated as **removal from the whole dump** rather than
> as a list of members, and a lane that implements it as a hand-written list has
> not implemented this clause. A list goes stale silently the first time a field is
> added; a removal cannot. §14 pins the roster mechanically, so a seventh field
> cannot go undigested without a red test.

> **Normative.** `id` is the one removal, and it is removed because the digest
> exists to be checked **against** an id: a fingerprint that included its own
> pointer would match only where the pointer already matched, which is the
> comparison the digest is meant to be independent of.

**Three earlier exclusions were wrong, and adversarial and architecture review
converged on them at round 10.** An earlier draft digested `tool`, `destinations`
and `decided_at` alone, on the ground that `expires_at` and `revokes` are
"liveness a fingerprint must not freeze" and that `account` is "already compared
exactly". Both grounds are false and the consequences are real.

*Liveness is not in these fields.* A granting record is **immutable once
appended**: revocation is a *separate* record naming it (§9), so this record's
`expires_at` never changes and its own `revokes` is `None` for as long as it
exists. Nothing a revocation does can change a granting record's digest, so
including `expires_at` freezes nothing. Excluding it, on the other hand, aliased
two genuinely different authorisations — the same recipients granted until March
and the same recipients granted until 2040 — into one fingerprint.

*And "already compared exactly" answers the wrong question.* §6 does compare the
account whole and by value, but it does so **at the write**, which is exactly the
moment the digest is not needed. The digest's whole job is the later read, where
§6's comparison is not being run by anybody; a fingerprint that omits a coverage
key is one an after-the-fact check cannot use to distinguish a grant over the
user's work account from an otherwise identical grant over their personal one —
which §3's first clause says are different authorisations and which
`BoundAccount`'s own declaration says "a standing grant would cover a record the
user never granted" about. Digesting the whole record but its pointer costs
nothing and closes both.

**`established_by` is in the record because the digest needed a durable act
identity, and architecture review was right that the timestamp is not one.** Round
11's blocker put the case plainly: `decided_at` is caller-supplied, ADR-0021 §4
already contemplates equal instants from a coarse clock, and ids are recyclable
after a `clear` — so two *legitimate* confirmations can produce grants identical
in every digested field, and the later one then satisfies both the old pointer and
the old digest while being a different user act. The reviewer's own direction is
the fix taken: name the establishing decision on the record. Its id is minted by
the caller that records **into the audit trail**, a store with no `delete(id)`
whose erasure is a separate act of the user's (ADR-0021 §4), so it is an identity
the grant store cannot recycle by clearing itself — which is exactly what the
coordinator's ruling said no scheme *inside* this store could achieve.

**It is not unforgeable and is not claimed to be, and round 12 raised the case
that shows where the line is.** A user who clears their **audit trail** leaves
every `established_by` naming nothing, and an id reused there afterwards names a
different act. That is real, and it is not a defect this ADR can close: the trail
is the user's to burn (ADR-0021 §4 — "the user may burn the book; nobody may tear
out a page"), and a grant store that refused to authorise until it could resolve a
decision in the trail would be an authorisation store acquiring a **veto over a
data right**, which is the inversion §9 already refuses in the other direction and
for the same reason. The reviewer's direction — "act evidence whose identity
cannot be rebound by an independent clear" — describes a thing this system does
not have and cannot mint: every identifier here is caller-supplied and every store
is wholesale-erasable, which is the same ground on which round 3's tombstone died.

**What the field does buy is bounded and is what it was added for.** Two *honest*
confirmations now produce different digests, which was round 11's blocker and is
the case that arises without anybody doing anything unusual. The remaining cases
all require a deliberate act by a component that could already falsify the record
in easier ways — a recording caller hand-authoring a grant (§1's residual), or a
user erasing their own trail and a caller then reusing an id from it. Neither is
an attacker the fields on this record were ever going to stop, and §6's own
statement of what is left unclosed says so about the identical boundary.

**What remains is one residual, and it is stated rather than engineered away.** A
**recording caller** that hand-authors a whole grant — the same declaration, the
same account, the same destinations, the same instants and an `established_by`
copied from a decision it did not answer — reaches an identical digest. That is a
caller falsifying its own store, which is the boundary ADR-0018 §3 drew for
detachment and which route (a) sits behind identically: a caller that chooses a
`decided_at` to fall inside an expired grant's window is already doing the same
thing one field over (§6). What the digest closes is every case that arises without a
deliberate erasure and re-mint — round 11's two honest confirmations among them —
and the cases it does not close all begin with the user destroying a store and a
caller re-using an identifier out of it (§6's one-directional clause). The two
directions offered instead stay unavailable: a store-enforced non-rebindable id
cannot survive `clear`, and preserving the grant's snapshot with the decision is
round 6's embedded value, refused for storage amplification and for having no
honest channel.

**A digest is a fingerprint under one record schema, and the ADR says so rather
than promising more.**

> **Normative.** A `subject_digest` is computed under the field set of
> `RecipientGrant` and of every value it embeds **as they stand when it is
> computed**. This ADR fixes no scheme for comparing across a change to that field
> set. An ADR that adds, removes or renames a field of `RecipientGrant`, of
> `ToolDefinition`, of `BoundAccount` or of `CanonicalDestination` decides in its
> own text what becomes of digests computed before it — preserving the earlier
> projection, versioning the digest, or accepting that the comparison loses reach
> across that boundary — and until one does, the comparison is defined between a
> row and a record under one schema.

> **Normative.** A mismatch therefore means "**not the same record under the same
> schema**", and no lane reports it as proof of a rebinding. A check that cannot
> establish that both sides stand under one schema reports **not comparable** and
> never "mismatch": the fail-safe direction for evidence is to decline the claim,
> not to make an accusation the evidence does not carry.

> **Normative.** No standing recipient authorisation exists anywhere else. It is
> not a field on a `ToolDefinition`, on a `PermissionDecision`, on a `Settings`
> value, on a connection record, or on any registry — ADR-0021 §6's "a store, not
> a field", read at this seam. A lane that adds an "always allow" flag to any of
> those has not implemented this ADR. §6's `authorised_subject` is not such a
> field and is not an exception to this clause: it is evidence **about** a grant
> the store holds, it authorises nothing on its own, and a decision carrying one
> is refused unless the store holds the grant it fingerprints.

> **Normative.** The seam is **three** Protocols in
> `ai_assistant.core.protocols`, on ADR-0097 §3's split and for its reason.
> `RecipientGrants` is the policy's query face and can create nothing;
> `RecipientGrantResolution` is the trail's resolution face and carries one
> member; `RecipientGrantStore` is the durable face and carries the append, the
> queries, the resolution, the standing and recent reads, the export and the
> wholesale erase. An `ActionPolicy` implementation is given the query face and
> never the store; an `AuditTrail` implementation is given the resolution face
> and never the store.

> **Normative.** The surface is exactly the following, and a contract that adds a
> member, widens an argument or changes a return is changing this decision rather
> than implementing it. The block is display, not a mark (ADR-0089 §2); the
> clauses below it are the obligations.

```python
class RecipientGrant(BaseModel):                       # core/types.py
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: DurableIdentifier                   # minted by the caller that records
    tool: ToolDefinition                    # by value, detached (§1)
    account: BoundAccount                   # by value; identity *and* reference
    destinations: tuple[CanonicalDestination, ...]   # non-empty, no duplicates, canonical order
    decided_at: UtcInstant
    expires_at: UtcInstant                  # required; no unbounded spelling (§9)
    established_by: DurableIdentifier | None = None   # set iff revokes is None
    revokes: DurableIdentifier | None = None

    @property
    def subject_digest(self) -> Sha256Hex: ...       # derived, never stored (§1)


class RecipientGrants(Protocol):                       # core/protocols.py
    async def covering(self, request: ActionRequest) -> RecipientGrant | None: ...


class RecipientGrantResolution(Protocol):              # core/protocols.py
    async def outstanding(self, grant_id: str) -> RecipientGrant | None: ...


class RecipientGrantStore(Protocol):                   # core/protocols.py
    async def record(self, grant: RecipientGrant) -> str: ...
    async def covering(self, request: ActionRequest) -> RecipientGrant | None: ...
    async def outstanding(self, grant_id: str) -> RecipientGrant | None: ...
    async def standing(self) -> list[RecipientGrant]: ...
    async def recent(self, *, limit: int = 50) -> list[RecipientGrant]: ...
    async def export(self) -> list[RecipientGrant]: ...
    async def clear(self) -> int: ...
```

> **Normative.** `covering` takes the whole `ActionRequest` and returns the
> **record** rather than a boolean, so the caller can name what authorised the
> `ALLOW` it is about to author. It returns the live grant matching **four** of
> §3's five comparisons — liveness, tool equality by value, account equality by
> value, and containment of the request's canonical destination set — and `None`
> where none matches. `None` means exactly that and never that the store could not
> be read; `RecipientGrantError` says the second. A request whose `egress_binding`
> is `None` is answered `None`.

> **Normative.** Where **several** live grants match, `covering` returns the one
> with the greatest `decided_at`, ties broken by the least `id` under code-point
> order. Overlapping grants are permitted — a grant over `{Alice}` and one over
> `{Alice, Bob}` are two things a user may reasonably have said — so the
> selection must be **total**, or two conforming stores record different
> `authorised_by` values for one state and one request. Latest-decided is the
> user's most recent expression of the same intent; the `id` tie-break makes the
> order total rather than mostly determined, which is ADR-0021 §4's argument for
> `recent`'s own tie-break.

> **Normative.** `covering` does **not** read `planned_with_external_content`, and
> §4's bar is not stated on this seam. That clause is an obligation of the
> `ActionPolicy` contract — ADR-0181 §5's ninth clause puts the neighbouring one
> there in terms — so the policy applies it to `covering`'s answer, and §3's
> coverage is the conjunction of the two. A safety rule stated in both places
> would be two statements to keep in step, and the one that drifted would be the
> one nobody was reading.

> **Normative.** `covering` is the **only** member on `RecipientGrants`. A policy
> asks about the one request it is ruling on; a policy that could enumerate the
> store is one that could log or leak the user's recipient set, which is ADR-0097
> §3's argument for keeping `SourceGrants` at one member, read one store over.
> `standing` and `recent` are on the wider face, for the surface that shows the
> user what they have granted.

> **Normative.** `outstanding` is the **only** member on
> `RecipientGrantResolution`, and it answers one question: the **granting**
> record with this id, if the store holds it and no revoking record names it, and
> `None` otherwise. `None` means exactly that and never that the store could not
> be read; `RecipientGrantError` says the second. It reads **no clock** —
> outstanding is a fact about two records (§9) — evaluates no coverage, ranks
> nothing, and returns a detached snapshot as every other query does.

> **Normative.** The resolution face is given to `AuditTrail` implementations and
> to nothing else. No `ActionPolicy`, no surface, no `EgressBinder` and no
> `interfaces/` adapter holds one; the query face carries no `outstanding` and the
> resolution face carries no `covering`, so neither component can ask the other's
> question. `record` is the only place a recorded `authorised_by` is ever resolved
> against this store, and it does so once, at the **resolution read inside
> `record`** (§6) — never at render time (§11) and never at any later read.

> **Normative.** `outstanding` is on the durable face too and is the same
> operation. The narrow Protocol exists so that what an `AuditTrail` *names* is a
> read it cannot widen, not so that a second implementation is written: one
> concrete store satisfies all three faces structurally, exactly as one concrete
> store satisfies `SourceGrants` and `SourceGrantStore` today.

> **Normative.** Every query returns a **detached snapshot** — the list, the
> records in it, and everything mutable those reach — on ADR-0018 §3's rule as
> ADR-0021 §4 applies it to a second store. `recent` is ordered by `decided_at`
> descending, ties broken by `id` ascending, and `limit` must be strictly
> positive: a non-positive value raises `ValueError` rather than being clamped or
> passed through, for the reason ADR-0021 §4 gives — `LIMIT ?` against SQLite
> turns `-1` into no limit at all, and this is a Tier 1 store.

> **Normative.** `standing` returns every **live** grant and `export` returns
> every record, live or not; `export` is what discharges ADR-0004 §6's
> portability obligation for this store, so it may omit nothing.

> **Normative.** A deployment configures a ceiling on how many **outstanding
> granting records** this store holds — `Settings.recipient_grant_max_outstanding`,
> an integer setting read through `core.config.Settings` and supplied to the
> concrete store at construction — and `record` **refuses** a granting record that
> would take the count above it, raising `InvalidRecipientGrantError`. The refusal
> is not a truncation, an eviction or a silent no-op: nothing already recorded is
> removed, narrowed or expired to make room, and no looser grant is minted in its
> place (§2's sixth clause, read on a second refusal ground).

> **Normative.** The ceiling **fails closed at the establishing act**. A surface
> offering the act refuses it with a reason visible to the user, naming that the
> ceiling was reached and that the recourse is to revoke a grant they hold; it
> does not offer the act and then drop it, and it does not present the refusal as
> a fault of the call being confirmed. The confirmation itself is unaffected — the
> user may still approve *that* call; what they cannot do is make it standing.

**No ceiling is stated on a record's own size**, and the unbounded read that
question is really about — the one `SourceGrantStore.standing()` has identically —
is **#1551**'s, answered there for the pair rather than for one of them here.

> **Normative.** A **revoking** record is never refused on this ground, whatever
> the count. A ceiling that could block a revocation would trap a user above it
> with no way down, which inverts the clause's purpose.

> **Normative.** The ceiling is a non-negative integer, and **zero is meaningful
> rather than a misconfiguration**: a deployment setting it to zero has turned
> route (b) off, because no grant can be established and `covering` therefore
> answers `None` for every request. That is the **only** switch this ADR provides
> for turning route (b) off — no lane adds a second boolean beside it, and no lane
> reads a non-zero ceiling as licence to skip any other clause of this ADR. This
> ADR fixes **no default**: the number is a deployment shape like every other
> `_IntegerSetting` in `core.config`, and §13 records it as undecided here. What
> the clause fixes is that a ceiling exists, that it is read from `Settings`, and
> that reaching it refuses rather than widens.

> **Normative.** `recipient_grant_max_outstanding` of **zero** is admitted and is
> the way a deployment declines route (b): no granting record can be recorded, so
> a deployment that has never established one never reaches a route-(b) `ALLOW`.
> It is **admission-only like every other value** and is not a kill switch: a
> store already holding live grants keeps them, `covering` keeps returning them,
> and the rows they source keep being written. Zero forbids the *next* grant and
> retracts none. No lane adds a second switch beside it, and no lane reads a
> non-zero ceiling as licence to skip any other clause of this ADR.

> **Normative.** The way to make an existing grant stop covering is the way it has
> always been: the user **revokes** it, or clears the store (§9). No lane makes a
> `Settings` value do that work. A configuration that silently stopped honouring
> authorisations the user had given — without a record, without an act, and
> without anything in the trail to show it — is the shape ADR-0097 §8 refuses when
> it forbids a grant minted from configuration, read in the other direction: what
> may not be created by configuration may not be destroyed by it either.

**The ceiling is stated over *outstanding* rather than over *live*, and the
substitution is deliberate and in the tighter direction.** Live is outstanding
plus the clock, and `record` reads no clock — the same constraint that decides the
duplicate rule below, for the same reason and after the same two dead drafts.
Outstanding is a superset of live, so a ceiling counted over it is at least as
tight as one counted over live and never looser. What it costs is that an expired
grant occupies a slot until it is revoked, which is exactly the shape the
duplicate rule already has — an expired grant "is still outstanding, so it can
still be revoked and it still blocks an identical new one until it is" — and the
recourse is the revocation §9 already gives the user, on any surface that shows
them their grants. A ceiling evaluated against a caller-supplied `decided_at`
instead is the round-4 draft, breakable by clock skew in both directions at once.

> **Normative.** The ceiling governs **admission and never eviction**. Lowering
> it deletes nothing, expires nothing, hides nothing, and omits nothing
> from `standing`, `recent` or `export`. A store holding records a newly lowered
> ceiling would not admit is a **legal** state: every record in it was admitted
> under the ceiling in force at the time. A query that hid records to make the
> current setting look satisfied would be lying to the user about their own
> standing policy, which is the failure the totality clause exists to prevent.

> **Normative.** Lowering `recipient_grant_max_outstanding` refuses **every** new
> granting record while the outstanding count is at or above it, and the count
> falls only as the user revokes; that is the recourse, and a revoking record is
> never refused for the count (above), so the way down is always open.

**The ceiling bounds the rows and is not claimed to bound the bytes, and the
difference is the whole of what this ADR says about the unbounded read.**
Adversarial review raised `standing`'s unbounded materialisation of a Tier 1 store
across rounds 8 to 11, and every form of the finding was right about something
different: a count ceiling does not bound one grant's size, a *destination* count
does not bound one destination's, and an earlier draft's claim that "ADR-0018 and
ADR-0148 bound their sizes" was false — asserted rather than read. What this ADR
therefore states is only what the establishment route obtains: at most
`recipient_grant_max_outstanding` records, under the ceiling **in force when each
was admitted**, each of them a record a user made by answering a confirmation
about a real call. It does not state a byte bound, and an earlier draft's attempt
at one is withdrawn: the axis it was on belongs to **#1551**, which asks the
question of `SourceGrantStore.standing()` and this store together, and answering
it for one of them inside an ADR about recipients would leave the pair
inconsistent and the corpus-wide question still open.

**What is not bounded at all is `export`, and that is stated rather than
repaired.** `recent` is bounded by its `limit`, which is why it exists and why a
non-positive value raises. `export` is bounded by nothing: revoked grants and
revoking records accumulate *outside* the outstanding count, and truncating them
is not available, because `export` is what discharges ADR-0004 §6's portability
obligation and a portable snapshot that omits records is not one. A store the user
never clears grows there, and the recourse is `clear` (§9), which is the user's.

> **Normative.** Every member is cancellable under `core/protocols.py`'s
> cancellation clause (ADR-0060) and observes no caller-owned container
> (ADR-0065), as the neighbouring store Protocols do.

> **Normative.** The store is **append-only**. A grant is never edited, narrowed,
> re-scoped or extended in place; changing what a user has authorised is a
> revocation followed by a new grant, and both records are kept (ADR-0097 §2's
> shape, read one store over).

> **Normative.** Ids, instants and `established_by` are supplied by the caller
> that records, as `PermissionDecision`'s and `SourceGrant`'s are, and are `DurableIdentifier` and
> `UtcInstant` as theirs are. A store mints no id and reads no clock on the write
> path (ADR-0021 §3). The only source of a `revokes` value is the `id` of a record
> the store already holds.

> **Normative.** `clear` retains **nothing**: no record, no id, no tombstone, no
> derived value. An id this store held before a `clear` may be recorded again
> afterwards, and what that can and cannot do is stated exactly, because an
> earlier draft of this clause overstated it.
>
> It cannot mislead a **reader**: nothing ever re-resolves an already-recorded
> `authorised_by`, at render time or at any later read (§6, §11), so no component
> asks this store what a recorded pointer means. It cannot widen what a row
> **authorised**: `record` compared the resolved grant's tool, account and
> destination set against that decision's own before appending (§6), so the row
> rests on a grant that covered it at the instant it was validated.
>
> What it **can** do is leave a row naming an id that later resolves to a
> different grant — a `clear` and a re-record landing between `record`'s
> resolution read and its append, or at any time after it. What that **cannot** do
> is make the row say something false, because the row does not rest on the id
> alone: it carries the `subject_digest` of the grant it was actually validated
> against (§6). A re-recorded grant satisfies that digest only where **every field
> the record carries but its `id`** is the same value — the same declaration, the
> same account, the same destinations, the same establishment instant and the same
> expiry, which is the same user act in everything the record says about it.
> Anything else fails the digest at every later read, by anyone holding the row and
> the record, with no privileged access and no live store. The timing window is still the one §9
> states, and it is still not one a tombstone would close: round 3's tombstone made
> ids unrecyclable, which is a different property from making the read and the
> append one act.

> **Normative.** Two words are used precisely and are not interchangeable. A
> granting record is **outstanding** while no revoking record names it — a fact
> about the store's own contents, needing no clock. It is **live** while it is
> outstanding **and** the instant read from the clock is **at or after its
> `decided_at` and strictly before its `expires_at`** — outstanding plus the
> clock, over the whole interval and not only its upper end. `record` decides over
> *outstanding*; `covering` and `standing` answer over *live* (§9).

> **Normative.** Liveness is bounded **below as well as above**, and the two ends
> match §6's exactly: a grant whose `decided_at` is in the future covers nothing
> and is returned by neither `covering` nor `standing`. Without that half the two
> seams disagree — the store would call a future-dated grant live, the policy would
> author an `ALLOW` on it, and `record` would refuse that `ALLOW` because the grant
> post-dates the decision. Adversarial review found exactly that at round 15, and
> the repair is here rather than at `record`, because a rule the store applies is
> one the policy cannot skip. Instants are caller-supplied and a host clock can be
> corrected backwards (§1), so a future-dated grant is a state this store can
> genuinely hold and not a hypothetical.

> **Normative.** `record` refuses a **granting** record whose `tool`, `account`
> and `destinations` all equal those of an **outstanding** granting record.
> Expiry does not enter it, so the write path reads no clock and no
> caller-supplied instant decides anything. This is `SourceGrantStore.record`'s
> "at most one live grant per source" with ADR-0097 §4's own liveness — derived
> from the revocation relation alone — read on this store's subject.

> **Normative.** Overlapping grants over *different* destination sets stay
> permitted and are what `covering`'s precedence is for. What is refused is a
> second grant that **is** the first, because revoking one would leave the other
> standing and the user would have revoked nothing. Re-granting a triple whose
> grant has expired is a **revocation followed by a new grant**, both appended and
> both kept, which is the operation §1 already requires for every other change to
> what a user has authorised.

> **Normative.** `record` is **write-once and atomic**, on `AuditTrail.record`'s
> and `SourceGrantStore.record`'s shape and for their reason. Re-recording an id
> already present raises rather than overwriting; the duplicate-id check, the
> duplicate-**subject** refusal, the **ceiling count**, the revocation
> invariants and the append are **one** operation, not a read followed by a
> write, so two concurrent writes cannot both observe the store as they found
> it. The ceiling is named explicitly because a count read outside the
> operation is the one that fails the way a duplicate-id check does not: two
> writers of **different** subjects at one below the ceiling both see room, both
> append, and the store ends one over — a race the duplicate-subject refusal
> cannot catch, because the two subjects differ. It stores a detached, validated snapshot, recursively over reachable state,
> and never retains the caller's object.

> **Normative.** A **revoking** record transcribes verbatim every field of the
> grant it revokes except `id`, `decided_at`, `established_by` and `revokes`, and
> `record` refuses it
> unless the named grant is present, is itself a granting record, is not already
> revoked, and matches every transcribed field. A revocation is **never refused for
> its timestamp**, including one that predates the grant it revokes, for the reason
> `SourceGrantStore.record` gives: `decided_at` is caller-supplied and this store
> reads no clock on the write path, so a host clock corrected backwards would
> otherwise make a grant permanently unrevokable.

> **Normative.** Both refusals raise `InvalidRecipientGrantError`, and a store
> that cannot be read or written raises `RecipientGrantError`, its base — two
> classes in `ai_assistant.core.errors`, on `InvalidGrantError`'s "one class rather
> than three" reasoning, because the caller's recourse is identical in every
> refusing case. They are **not** `GrantError` and `InvalidGrantError`, whose
> stated subject is the source-grant store: one handler catching both would join
> the two seams ADR-0097 §7 keeps apart, and they fail closed onto different
> things.

> **Normative.** A component that cannot get an answer from this seam **fails
> closed**. A `RecipientGrantError` raised by a query is not a grant, and no
> policy proceeds on a stale answer, an earlier lookup or an absent one
> (`GrantError`'s own clause, read one store over).

**The order is validated rather than merely documented, because a set-based
coverage rule with an order-sensitive identity rule is a hole, and adversarial
review found it.** `(Alice, Bob)` and `(Bob, Alice)` cover exactly the same calls,
so a duplicate refusal over ordinary tuple equality admits both — and revoking one
leaves the other standing, which is a user revoking and nothing being revoked, in
a rule whose entire job is that revocation revokes. Stating the duplicate rule
over membership instead was the other available repair and it is the weaker one:
it leaves **three** rules comparing destination sets — the duplicate refusal,
`record`'s subject match (§6) and the subject digest — each of which would then
have to say "as sets", and any one of which could drift back into tuple equality
without a test noticing. Pinning one spelling at construction fixes all three at
once.

**And it costs an honest caller nothing, because the value it is transcribing is
already in that order.** §2 admits exactly one route to a grant, and it takes
`destinations` from the confirmed decision's binding's `canonical_destination_set`
**by value** — a property `core` already returns as
`tuple(sorted(members, key=_destination_order))` (the Context's tree reading). A
grant established the only way §2 permits is therefore in canonical order before
the validator looks at it, and §2's by-value equality with that property is
*served* by this clause rather than strained by it: one order on both sides is
what makes "equal by value" and "equal as sets" the same statement. What the
validator refuses is a hand-built tuple, which is the case the finding was about.

**The duplicate rule is stated over *outstanding* rather than over *live*
because expiry is the half that needs a clock, and two drafts died finding that
out.** A refusal over "already live" obliges `record` to read one; a refusal that
substituted the caller's `decided_at` for the clock — the round-4 draft — is
breakable by skew in both directions at once, which round 5 showed: a
forward-skewed instant admits a second grant that is live immediately, and a
backward-skewed one refuses a renewal after the first has genuinely expired.
Neither repair was available inside a clock-free write path, because neither was
a fact about two records.

**Outstanding is such a fact, and it is ADR-0097 §4's own liveness.** A source
grant's liveness "is derived from `revokes` alone", and that is exactly the
predicate a write path can evaluate: does the store hold a revoking record naming
this one. So `record` decides over it, and the cost is that re-granting an expired
triple takes a revocation first — one extra append, in the operation §1 already
requires for every other change to what a user has authorised, and the direction
that fails toward asking rather than toward two authorisations the user thinks
are one.

**The declaration is embedded by value rather than named by id, and that is
ADR-0021 §1's ruling applied to a record that outlives the call.** ADR-0021 §1
embeds the whole `ToolDefinition` in a decision because an id can be rebound —
#54 — and "the worst available" failure is "executing an implementation whose
risk declaration is not the one the user approved" (ADR-0016 §7). A standing
grant is exposed to that hazard for as long as it is live rather than for the
length of one invocation, so a grant keyed on `tool_id` would be strictly worse
than a decision keyed the same way, which the corpus already refused.

**The cost is real and is accepted in the safe direction.** Because coverage
compares the declaration by value (§3), any edit to a registered declaration —
including one that only rewords a description — leaves every grant established
about the previous declaration covering nothing, and the user is asked again.
That is a re-prompt on an upgrade, which is the same cost ADR-0021 §5 accepted
in writing when it called over-prompting "the safe direction", and it is the only
version of the rule that does not make a declaration edit a silent widening of
what the user authorised.

**Two faces rather than one, because the establishing act is the only thing that
may create a grant.** ADR-0097 §3's argument transfers without modification: a
component handed the whole store can mint its own authorisation, and "nothing
about the resulting record looks wrong afterwards". A policy holding
`RecipientGrantStore` is one `record` call away from authorising the send it is
ruling on. Removing the capability from the type the policy names is a static
guarantee `mypy --strict` enforces over `src` and `tests`, which is what ADR-0097
§3 already says it is and is not — a concrete store still satisfies all three
faces structurally, and what a policy cannot do is *name* `record`.

**The trail gets a third face for the same reason, and that is also why the two
record kinds are not put in one store.** §6 makes `AuditTrail.record` verify a
route-(b) pointer against the grant records, so the trail must be able to read
them. The obvious alternative — one concrete store satisfying `AuditTrail` and
`RecipientGrantStore` at once, so the check and the append share a transaction —
is refused, because it makes the component that *validates* a grant the component
that can *mint* one, which is the capability ADR-0097 §3 removes by splitting and
which this section has already removed from the policy. A trail that could append
a grant is one `record` call away from authorising the row it is about to
validate, and nothing about the resulting store would look wrong afterwards.

**What the fusion would buy is atomicity between `record`'s resolution read and
its own append, and that is a real thing to give up rather than nothing.** Round
8 of this review found the giving-up on both lenses, and the ADR now says it: a
revocation or a `clear` landing in that interval is not seen by the check, so §6
states its guarantee over the resolution read rather than over the append, and §9
carries the residual window. One store would close that interval. It is refused
anyway, for three reasons.

*The capability.* The trade is microseconds of window against a component that
can both mint and validate the same record. This corpus has decided that
direction twice already — ADR-0097 §3 for the source-grant store, and this
section for the policy — and neither time was the reason that the race mattered
less than the capability; it was that "nothing about the resulting record looks
wrong afterwards".

*It would not deliver the property a reader would assume from it.* The policy's
`covering` read is strictly earlier than `record` in every route-(b) flow, so "a
revocation stops a call not yet executed" is unavailable under either shape. What
one store buys is a smaller instance of a window that has to be stated either
way, and a stated window is what §9 already is.

*There was never a single-use guarantee here to protect.* Route (a) needed
atomicity because two racing resolutions of one `CONFIRM` must not both succeed
(ADR-0021 §4). A standing grant is many-use by construction, so no transaction is
protecting an invariant that a second write would break. The two stores also stay
separately erasable, which §9 requires and which ADR-0007 §4's cross-tier
coordinator has not yet decided.

### 2. A grant is established only by a user act that names the recipient

> **Normative.** A `RecipientGrant` is created by exactly one thing: a user
> **answering a recorded `CONFIRM` about an egress call** and, in the same act,
> asking that that call's recipients be remembered. The grant's `established_by`
> is that recorded decision's own `id` — the act is named on the record and not
> only in this clause (§1). Its `tool` is transcribed from the confirmed
> **decision**'s own `tool`; its `account` and
> `destinations` from that decision's `egress_binding` — the binding's `account`
> and its derived `canonical_destination_set`. All three by value and unchanged,
> and nothing is typed, parsed, canonicalised or **reordered** at the establishing
> surface — the order is part of the value now (§1), so a surface that rebuilt the
> tuple in the order it happened to render it in would be minting a grant
> `RecipientGrant`'s own validator refuses. Which surfaces offer the act, and how
> they carry it, is not decided here (§13).

> **Normative.** There is **no out-of-call establishment**. No command, setting,
> configuration file or standalone surface creates a grant from a recipient the
> user names outside a confirmation about a real call. **Revocation is not so
> limited**: a user may revoke a grant from any surface that shows them their
> grants, because a revocation names a record the user is looking at and asserts
> nothing about a call.

> **Normative.** Nothing else creates one. Not a prior call, not a recipient that
> has appeared before, not a credential's scope or audience, not a configured base
> URL or host, not an account the user connected, not an allowlist the system
> assembled, not a `Settings` value, not a first run, not an upgrade or a
> migration, and not a destination this system extracted from a span it selected.
> This is ADR-0148 §3's second clause and ADR-0097 §8's first clause read together
> on this store, and no lane reads the establishing act's existence as licence for
> any of them.

> **Normative.** No grant is established from a confirmation whose recorded
> `egress_binding` carries `planned_with_external_content` as true, and none from
> one carrying an `OriginUnrecordedBinding`. A user answering such a confirmation
> may approve the call; they may not, in that act, make the recipients standing.

> **Normative.** A surface on which the user establishes a grant renders, before
> it collects the act: the connected account's identity, the canonical destination
> set in **both** supplied and canonical forms, and the payload description — that
> is ADR-0148 §8's fourth clause, unchanged, and this clause adds no exception to
> it; the tool the grant is about, by the declaration's own identifier and
> capability, read from the declaration and never from a registry; the instant the
> grant ceases to be live; and a statement that calls this grant covers will **not
> be put to the user**, so the payload description of those calls is not shown
> again. Every value is inserted as data, neutralised for that target on render
> (ADR-0042 §4).

> **Normative.** The establishing surface renders `planned_with_external_content`
> under ADR-0181 §6, in all its states, unchanged and in full. The third clause
> above means the act is unavailable in one of those states; that is a fact about
> the act, and no surface renders it as a detection, a score or a warning that the
> call was malicious (ADR-0181 §7).

> **Normative.** No grant is established where any member of the destination set
> the act names has no canonical form under ADR-0148 §2 — a form the protocol's
> canonicaliser refuses, or a name that has not been resolved. The act is refused
> and **no looser grant is minted in its place**: not one over the supplied form,
> not one over the account, not one over a subset. This is ADR-0148 §1's third
> clause read at establishment rather than at the ruling, and it is the discipline
> #1548 records OpenClaw stating for a different binding — "refuses to mint an
> approval-backed run rather than pretend full coverage".

> **Normative.** The establishing act is refused, with a reason visible to the
> user, where the store already holds the configured maximum of outstanding
> granting records (§1's ceiling). The refusal is the
> act's alone: the user may still approve the call they were asked about, and no
> grant is evicted, expired, truncated or narrowed to admit theirs. This is the second thing that refuses an act a user
> asked for, and it takes the first's shape — say so, name the recourse, and mint
> nothing looser in its place.

> **Normative.** A user who **amends** a call while answering a confirmation is
> issuing a new request. No grant, and no answer, carries across the amendment:
> the amended call is bound, ruled and — if the user wants it standing —
> established afresh. No surface offers an establishing act attached to an edit of
> the call it was asked about.

**Establishment rides a confirmation because the content floor below cannot be
met anywhere else, and an earlier draft of this section did not notice.** That
draft also admitted "a command on the command-line or gateway surface naming the
recipients", and architecture review found on round 2 that such a surface has no
payload description and no `planned_with_external_content` to render — both are
properties of a **call**, and neither exists for a recipient typed in the
abstract. The available repairs were a second, weaker content contract for the
out-of-call route, or removing the route. The second is right: a weaker contract
would be a surface rendering a *fabricated* call-level fact, which is the
unobtainable bound ADR-0098 §6's second clause forbids, and the route would also
put a user-typed string where §2's sixth clause and ADR-0148 §2's canonicaliser
have to meet — reopening from the surface the question the seam already closed.
What is lost is pre-authorisation, and the cost is one confirmation: the user
sends to the recipient once, answering about that call, and says "and remember
this" in the same breath. That is also the only moment at which they have been
shown what such a call actually looks like.

**§2's sixth clause is nearly vacuous under the second clause, and it is kept as
a floor anyway.** A binding the seam derived has already canonicalised every
member or the request was refused before the ruling (ADR-0148 §1's third clause),
so an uncanonicalisable destination cannot reach a confirmation. The clause is
retained because it states the rule over the *act* rather than over the route,
and a later ADR that opens a second route inherits it rather than having to
rediscover it.

**The third clause is the one that closes the composition, and it is cheaper
here than anywhere else.** §4 bars a grant from *covering* such a call. Without
this clause the same end is reached one step earlier: a model that has read
external content proposes a send to an address of the attacker's choosing, the
user is asked, the fact is on the card — and the user, approving the one call,
also blesses the recipient for every call after it, on which the origin fact will
be false. That is ADR-0154 §4 item (ii)'s "external content … choosing the
recipient of a call the grant already covers" with the grant created by the very
call the origin fact was recorded on. Both clauses are needed and neither implies
the other.

**The fourth clause's last limb is the honest half, and it is stated as an
obligation rather than left to a surface's taste.** A standing grant's whole
effect is that ADR-0148 §8's fourth clause stops being reached for covered calls
— the account, the destination set and the payload description are put to the
user once and then not again. A user who is not told that has been asked a
different question from the one they answered. It is stated over what the surface
*contains*, not over what the user understands, for the reason ADR-0098 §3
records learning twice.

**The seventh clause refuses a shape that ships in a comparable runtime.** #1548
records LangChain's `HumanInTheLoopMiddleware` admitting an `edit` decision in
which "the human rewrites the arguments and the edited call runs under the
approval that was asked about the original". Our binding is whole or absent and
`PermissionDecision.authorises` compares the fixed request, so the edited call
already fails that comparison (ADR-0150 §1). The clause is stated anyway, because
a grant makes the same shape reachable through a different door: an edit that
changed only the recipient, offered beside "and remember this recipient", would
mint a grant over an address nobody was asked about.

**`OriginUnrecordedBinding` needs no new mechanism and is named anyway.**
`ActionRequest.egress_binding` never carries one, and `ActionPolicy.resolve`
already returns no `ALLOW` on a confirmation that does (ADR-0184 §8). The clause
is stated because the establishing act is a *second* thing a user does with a
confirmation, and a rule that held only for the answer would leave the second
unruled.

### 3. What a grant covers: five comparisons, all over recorded values

> **Normative.** A grant covers an egress request when **all five** hold: the
> grant is **live** (§9); the request's `tool` equals the grant's `ToolDefinition`
> by value; the request's binding's `account` equals the grant's `BoundAccount` by
> value — both facts, identity and connection reference, never one; **every**
> member of the request's canonical destination set is a member of the grant's,
> compared as `CanonicalDestination` compares — every field, never across
> protocols; and the request's binding does not carry
> `planned_with_external_content` (§4). A grant that fails any of the five covers
> nothing about that request. The first four are `RecipientGrants.covering`'s and
> the fifth is the policy's (§1, §7); coverage is their conjunction and no
> component treats either half as the whole.

> **Normative.** Coverage is a comparison of recorded values and is never an
> inference. No component widens a grant by folding case, by matching a domain, by
> treating an account member as covering a recipient member or the reverse, by
> treating a grant's larger set as covering a request's set under any relation
> other than membership, or by re-canonicalising either side. A canonicaliser is
> ADR-0148 §2's, at the seam, and there is not a second one here.

> **Normative.** A grant may name the **connected account** as a member — the
> `CanonicalDestination` shape carrying an account and neither a protocol nor a
> canonical form — and such a member covers exactly the calls whose arguments
> select no recipient beyond the service the call is made to (ADR-0148 §2's third
> clause). It covers no selected recipient, whatever strings the two hold.

> **Normative.** A grant authorises the **recipient** and nothing else. It does
> not widen `discloses`, does not raise or lower any ceiling ADR-0016 §3 states,
> does not satisfy ADR-0148 §8's third-clause floor about the payload description,
> does not exempt a call from any other floor a policy owes, and does not
> authorise a call the seam would refuse to describe (ADR-0152 §6).

> **Normative.** A grant's **only** effect on an outcome is to discharge the
> recipient-authorisation ground of ADR-0148 §3's first clause and ADR-0148 §8's
> third clause, for a request it covers wholly under the five comparisons above.
> It discharges nothing else. It never widens a declared reach, never lowers or
> reads a threshold, never converts a `DENY` into anything, never affects a
> request it does not cover, and never satisfies a floor stated over any fact
> other than recipient authorisation — ADR-0148 §8's third clause's second limb
> about the payload description among them.

> **Normative.** ADR-0021 §5's monotonicity obligation is unchanged and is not
> stated over this. A grant is "an input the policy was given, not a severity
> axis" (ADR-0021 §5), so monotonicity continues to compare requests "equal in
> every other respect including that one": raising `risk_level`, raising
> `reversibility` or widening `discloses` must still never produce a less
> restrictive outcome, **with the grants in the store held equal**. No
> implementation reads either clause as forbidding the `CONFIRM` → `ALLOW`
> transition this ADR exists to permit.

**The account is compared because a destination set alone is a key with a
duplicate, and the corpus had already found the hole before the survey named
it.** `BoundAccount`'s own declaration says so in terms: it carries two facts
rather than one because "two connectable records can hold one identity, so an
identity-only account compares equal across them and **a standing grant would
cover a record the user never granted**". #1548 arrives at the same two-key rule
from the other side — Claude Code's `injectHosts` and OpenAI's `domain_secrets`
bind a credential to its hosts independently of the destination allowlist, so
neither key alone authorises. A grant over `alice@example.com` established
against the user's work account does not cover a send to the same address
through a personal one, and there is no reading of the comparison in which it
does.

**Set membership rather than any looser relation, because every looser relation
has been tried somewhere and fails on the same axis.** A grant "for
`example.com`" covers an address the user has never seen; a grant "for these
three plus anything in the same thread" covers whoever the thread later
contains; a grant keyed on the tool covers every recipient of every later call,
which is what OpenAI's `always_approve` does today and what #1548 names as the
shape to avoid. ADR-0148 §2's exactness default exists because "a rule that let an
implementation choose would choose the first, because the first is the one that
makes a demo work", and a matching rule is where that choice would reappear after
canonicalisation had closed it.

**The account member is what #68's carve-out becomes, and it is not a carve-out.**
#68's second comment reserves host- or credential-scoped authorisation for an
operation that "cannot disclose onward", and warns that the property "is itself
something someone has to declare or derive, and getting it wrong reopens the
hole". ADR-0148 §2's third clause dissolved that by ruling over what the arguments
*select*, and §10 below records that this ADR does not re-open it. A grant over the
account is then an ordinary grant over an ordinary member: a user who says "stop
asking me before you look at my own calendar" gets exactly that and nothing wider,
because a member that is the account equals no member that is a recipient.

### 4. ADR-0098 §3's last clause, decided: no, and the rule is stated over the recorded fact

> **Normative.** No `RecipientGrant` covers an egress request whose binding
> carries `planned_with_external_content` as true. On such a request an
> `ActionPolicy` returns no `ALLOW` on route (b), whatever grants exist, and route
> (a) — a decision of the user about *that* request — is the only route to an
> `ALLOW`.

> **Normative.** The clause above is stated over the fact ADR-0181 §2 records and
> over nothing else. It is **not** a claim that a call carrying the fact as false
> was uninfluenced by external content, nor that one carrying it as true was: no
> lane, ADR or surface reads this section as detecting external content in text
> whose recorded origin is not external (ADR-0181 §2's second clause, ADR-0098 §5,
> ADR-0106 §1's second clause).

> **Normative.** This section decides ADR-0098 §3's last clause for standing
> **recipient** grants at the designated `tools/` egress seam, and for nothing
> else. ADR-0021 §6's standing grants for other actions stay deferred and
> unnarrowed, and no lane reads this section as deciding anything about a seam
> this ADR does not name.

> **Normative.** No lane reads this section as licence to widen the fact, to
> compute a per-span variant of it, to derive it from a span's content, or to make
> a grant conditional on any origin fact this corpus does not record.

**ADR-0098 §3 asks its question over an unrecoverable relation, and this is the
strongest answer that is not a guess.** Its clause asks whether a standing
authorisation "may cover an action a model selected while reading external
content", and ADR-0098 §5 establishes that "produced from external content" is
not recoverable once a model's output has been recorded truthfully. ADR-0154 §4
records adversarial review falsifying exactly that shape at round 6, and ADR-0098
§12 states the constraint in terms: "whatever is decided has to be decidable from
recorded origin". The recorded fact is `planned_with_external_content`, and the
answer is stated over it because that is the only fact an authoriser holds.

**So the honest reading of the answer is narrower than the question, and saying
so is the point.** For a call the predicate marks true, this ADR answers ADR-0098
§3 with a flat no, and that no is enforceable at the ruling point with no new
surface. For a call the predicate marks false, this ADR permits route (b) while
claiming nothing about whether external content was involved — the predicate is a
disjunction over records *this system selected*, and ADR-0181 §6's third clause
already forbids reading its `False` as an assurance. A reader wanting the
stronger bound is wanting the one ADR-0098 §5 says cannot be had, and ADR-0098 §6's
second clause forbids buying it from something that cannot deliver it.

**The cost of the no is a prompt, and that is the whole cost.** A call carrying
the fact is confirmed per call exactly as every egress call is confirmed today,
so the clause takes nothing away from anyone; it declines to hand something back.
That asymmetry is why it is cheap now and expensive later, which is ADR-0098 §3's
own reason for ruling early and ADR-0154 §4's for repeating it.

**It also honours ADR-0181 §5's floor verbatim rather than by implication.** That
section's last clause binds "an ADR that later lifts ADR-0154's floor" not to lift
it for such a call. This is that ADR; §12 records the lift and this section is the
part of the floor left standing.

### 5. ADR-0146 §8's second clause, decided: yes for the recipient, never for the payload

> **Normative.** A `RecipientGrant` may authorise a call that forwards
> user-authored content to a third-party recipient, where that recipient is a
> member of the grant's canonical destination set and **all four** of §3's other
> comparisons hold — liveness, tool equality, account equality and the absence of
> `planned_with_external_content`. That is the whole of what it authorises.

> **Normative.** A grant states nothing about the payload and authorises no
> content. It does not classify a span, does not raise a span's tier, does not
> excuse a span from ADR-0146 §5's description rules, does not make a tier-bearing
> span describable as tier-free, and does not license a component to place into a
> span anything ADR-0155 §3 forbids it to place there.

> **Normative.** No lane, ADR or surface states or implies that a grant bounds,
> filters, inspects or attests **what** is sent to a granted recipient. The grant
> is a fact about the recipient, and this corpus records no mechanism that
> inspects the payload (ADR-0155 §4, #1154, #75).

**Yes, because a no makes route (b) vacuous rather than safe.** ADR-0146 §1 rules
every outbound span either user-authored or system-selected, so a rule that a
grant may not cover user-authored content leaves it able to cover a send with no
content in it. A clause with no live subject that also removes the feature is not
a conservative reading of ADR-0146 §8; it is a refusal wearing one's clothes, and
ADR-0021 §6 already recorded that a disclosing tool prompting every time is "a
poor steady state" rather than a target.

**And the loss the yes causes is stated rather than glossed, because two open
issues say the confirmation is the only thing standing in its place.** #1154
records that nothing distinguishes an egress span drawn from the assistant's own
store, that ADR-0155 §4 forbids any lane from claiming otherwise, and — in terms
— that "the owner's `CONFIRM` is therefore the only control". #75 records the same
shape for a Tier 0 secret a user typed into a message: no egress-side detection
exists, and the confirmation is where a user could notice. A covered call is not
confirmed, so for granted recipients that control is gone, and neither issue
acquires a mechanism here.

**What bounds the loss is what the corpus can actually obtain, and it is three
things.** The grant names the recipients, so the class of calls that lose the
confirmation is one the user chose by name rather than one a system widened
(§3). The user is told at establishment that they will not be shown those calls
(§2's fourth clause), so the loss is disclosed at the moment it is consented to
rather than discovered afterwards. And a call planned over external content keeps
its confirmation whatever grants exist (§4), which is the case in which an
attacker rather than the user is choosing what the payload says. None of the
three is detection, and this section claims none.

**Revisiting is named with its trigger and not left to memory.** Should a
mechanism land that distinguishes a span drawn from the assistant's own store —
#1154's — or an egress-side Tier 0 detection — #75's — a later ADR may narrow
what a grant covers over the recorded fact that mechanism produces. It may not
narrow it over an inference, for §4's second clause's reason.

### 6. ADR-0021 §3's named precondition, discharged: the records live where the trail can read them

> **Normative.** The second source of a `PermissionRuling.authorised_by` is a
> `RecipientGrant.id`, and the records live in the `RecipientGrantStore` (§1) —
> local, durable and never written to a remote service, on ADR-0004 §2's residency
> clause as ADR-0021 §4 applies it to the trail.

> **Normative.** A route-(b) `ALLOW` carries **two** values about its
> authorisation and no third: the grant's `id`, in `authorised_by`, and the
> grant's `subject_digest` (§1), in a new field. Both are on `PermissionRuling`,
> which is the one record a policy authors, and
> `PermissionDecision.from_request` transcribes the ruling whole
> (`ruling.model_copy(deep=True)`) — so both reach the durable record along the
> path that exists today, with no reconstruction by the caller, no second lookup,
> no parameter added to `from_request` and no widened `ActionPolicy` return.

> **Normative.** The new field is `PermissionRuling.authorised_subject`, typed
> `Sha256Hex | None` and defaulting to `None`. **`PermissionDecision` gains no
> field of its own**, `ActionPolicy` and `AuditTrail` gain no member, no argument
> and no widened return, and this one optional field is the whole of what this ADR
> adds to any type the corpus already has.

```python
class PermissionRuling(BaseModel):                     # core/types.py — added field
    ...
    authorised_by: DurableIdentifier | None = None     # unchanged (ADR-0021 §3)
    authorised_subject: Sha256Hex | None = None        # the grant's subject_digest
```

> **Normative.** Nothing about the grant travels **by value**: not the destination
> set, not the declaration, not the account, not the expiry, not the establishing
> act. A digest is a fixed sixty-four hex characters whatever the grant's size, so
> a grant naming ten thousand recipients adds sixty-four characters to a decision
> and not ten thousand destination entries — ADR-0004 §7's minimisation is served,
> and the storage amplification round 7 found in the embedded-grant draft stays
> closed.

> **Normative.** `PermissionRuling` refuses an `authorised_subject` set where
> `authorised_by` is unset — the same shape as its existing refusal of an
> `authorised_by` on a non-`ALLOW`, and for the same reason: a fingerprint of the
> authorisation is incoherent on a ruling that names none. It does **not** require
> the converse, because a route-(a) `ALLOW` sets `authorised_by` and has no grant
> to fingerprint. Which of the two shapes is owed is decided at `record`, the only
> component that can see `resolves` and `egress_binding`, and it is stated below.

> **Normative.** A policy sets `authorised_subject` **only** to the
> `subject_digest` of the record `covering` returned, recomputed from that record
> and never carried from anywhere else. A policy constructed with no
> `RecipientGrants` leaves both fields unset, exactly as ADR-0021 §3 requires
> today.

> **Normative.** `AuditTrail` implementations are constructed with a
> `RecipientGrantResolution` (§1), and `record` resolves the pointer against it.
> The trail therefore holds a read and nothing else: it cannot append a grant,
> revoke one, enumerate the user's recipients or erase the store. `ActionPolicy` is
> unchanged, `AuditTrail`'s own Protocol gains no member, no argument and no
> widened return, and what ADR-0021 §4 gains is an invariant rather than a
> signature.

> **Normative.** An `ALLOW` sourced by route (b) is a **non-resolving** decision:
> its `resolves` is unset and its `authorised_by` is the covering grant's `id`. An
> `ALLOW` sourced by route (a) keeps its existing shape exactly — `resolves` set
> and `authorised_by` equal to it (ADR-0021 §3). The two are therefore told apart
> by whether `resolves` is set — a discriminator the records already carry, with
> **no field added to carry the basis itself**.

> **Normative.** The invariant below is scoped to **route-(b) egress decisions**,
> and to nothing else: a non-resolving `ALLOW` whose `egress_binding` is not
> `None`. A decision with no binding is not an egress call, and this ADR states no
> rule about one. ADR-0021 §6's standing grants **for other actions stay deferred
> and unnarrowed**: such a decision carries no `egress_binding`, so it falls
> outside this invariant's scope entirely rather than needing an exception inside
> it, and the ADR that opens one states its own scope beside this one without
> finding `PermissionDecision` already shaped against it. This scoping is stated
> so that no lane reads the invariant as a general rule about `authorised_by`.

> **Normative.** Route-(b) **egress** authorisation is reserved to **this** store.
> On a decision in scope, `authorised_by` names a `RecipientGrant` and
> `RecipientGrantResolution` is the seam it resolves against, and there is no
> second reading. A later ADR that wants a *different* standing source for egress
> is making a **contract change** to how a row in this scope is read — it decides
> how the reference is told apart, whether by tagging it, by a second field, or by
> narrowing this scope — and it does not inherit an "add your own arm" permission
> from this ADR.

**That reservation is a claim withdrawn rather than a limit added, and the reason
is worth keeping.** An earlier draft said a later egress standing source "does the
same" — adds an arm to this check — and architecture review found at round 12 that
it cannot: with two egress grant stores, a bare `DurableIdentifier` and a bare
`Sha256Hex` do not say which seam `record` should ask, so the second ADR would
have to reject a valid pointer, probe both stores, or change the shared record
after all. The reviewer offered a tagged reference as the alternative, and this
ADR declines it for the reason it declined a one-member discriminated union at
round 10: a tag with one value today is a surface with no consumer (ADR-0045 §1),
and the second value would arrive with its own ADR anyway. What was wrong was the
*promise*, not the shape — so the promise goes.

> **Normative.** `AuditTrail.record` refuses a non-resolving `ALLOW` whose
> `egress_binding` is not `None` and whose `authorised_by` is set unless **all
> eight** hold: `outstanding(authorised_by)` returns a record — which is the
> existence, the kind and the unrevoked check at once, since it answers only for a
> granting record no revoking record names; that record's `decided_at` is **at or
> before** the decision's; that record's `expires_at` is strictly after the
> decision's `decided_at`; its `ToolDefinition` equals the decision's
> `tool` by value; its `BoundAccount` equals the decision's binding's `account` by
> value, both facts and not one; its canonical destination set contains every
> member of the decision's; the decision's `egress_binding` is an
> **`EgressBinding`** whose `planned_with_external_content` **is `False`**; and
> the decision's ruling's `authorised_subject` is set and equals that record's
> `subject_digest`, **recomputed by `record` over the record the store returned**.
> Six of them are §3's five comparisons, taken over the record the store holds
> rather than over the policy's account of it — with liveness split in two,
> because its unrevoked half is a fact about two records and its expiry half is a
> fact about two instants. The ordering check is stated below; the digest is
> stated below that and is the only one of the eight that outlives the write.

> **Normative.** A grant is **live over an interval**, and both of its ends are
> checked against the decision's `decided_at`: `expires_at` strictly after it, and
> the grant's own `decided_at` at or before it. **Equality is permitted** at the
> lower end — ADR-0021 §4 already contemplates a coarse clock stamping two records
> alike, and a grant established and spent in the same instant is an ordinary
> thing rather than a suspicious one. What the clause refuses is a decision
> resting on a grant established **after** the ruling was made, which is not a
> stale authorisation but a **backdated** one: the policy could not have read a
> record that did not exist when it ruled, so a row claiming it did is describing
> a lookup that never happened. Adversarial review found at round 14 that the
> upper end was checked and the lower was not, and it is the same two-recorded-
> instants comparison ADR-0021 §4 makes when it refuses a resolution predating its
> confirmation. `record` still reads no clock.

> **Normative.** The digest is **never taken on the decision's word**. `record`
> computes `subject_digest` from the record `outstanding` returned and compares;
> it does not read the decision's value as evidence of anything, and an
> implementation that compared a decision's `authorised_subject` against itself,
> or against a value derived from the decision rather than from the store, has not
> implemented this clause. That is the same discipline as the six comparisons
> above and the same one ADR-0021 §3 states as the standard: *nothing is taken on
> trust*.

> **Normative.** `record` refuses a **resolving** `ALLOW` whose
> `authorised_subject` is set, by the same error. Route (a) rests on a recorded
> confirmation, which is not a grant and has no subject digest, so a resolving
> decision carrying one is a decision claiming an authorisation of a kind it does
> not have. This is the pairing rule `PermissionRuling` cannot state on its own.

> **Normative.** The **origin** check is stated over the binding's **arm**, not only
> over a field's value. `PermissionDecision.egress_binding` is
> `EgressBinding | OriginUnrecordedBinding | None`, and only the first carries
> `planned_with_external_content` at all — so a decision in scope whose binding is
> an `OriginUnrecordedBinding` is refused by name. That arm's whole meaning is that
> the origin was never recorded (ADR-0184 §2), which is not a binding that "does
> not carry" the fact; a validator reading the check as a field test would accept
> it, which is §4's floor bypassed by a missing field rather than by a false one.

> **Normative.** Expiry is decided **against the decision's own `decided_at`**,
> never against a clock. `record` reads no clock, exactly as ADR-0021 §4's "a
> resolution may not predate its confirmation" compares two recorded instants. The
> question the trail asks is whether the grant was live **at the moment the ruling
> was made**, which is the only question about liveness a durable record answers
> identically on every later read. A grant that expires between the ruling and the
> write therefore does not retract an honest `ALLOW`, and an expired grant can
> never source a new one. The instant compared is one the **policy** does not
> supply: ADR-0021 §3 removed clock-reading and id-minting from `decide` precisely
> so that `decided_at` belongs to the caller that records, and the policy is the
> component this invariant is defending against.

> **Normative.** Revocation, by contrast, is decided at the **resolution read
> inside `record`** — the instant `outstanding` answers — because `outstanding` is
> a fact about two records and needs no clock, and because ordering a revocation
> against the decision's `decided_at` would be unsound: a revoking record's own
> `decided_at` is caller-supplied and may legitimately predate the grant it
> revokes (§1).

> **Normative.** `record`'s guarantee is stated over that instant and **not over
> the append**, because the resolution read and the append are two awaits and this
> ADR builds no linearisation point across the two stores (§1). What `record`
> guarantees is exactly this: **at the instant the pointer was resolved, it named
> an outstanding grant covering this decision.** A revocation or a `clear` landing
> before that read refuses the write, and under ADR-0037 §2's decide → record →
> read back → claim the call then does not happen — the fail-closed direction, and
> what a user who revokes expects. One landing between that read and the append
> does not refuse it. No clause of this ADR claims a stronger ordering; §9 states
> the window that remains, and it is the same window for a revocation and for a
> `clear`.

> **Normative.** A `RecipientGrantError` from the resolution face is **not** an
> accepted write. `record` refuses, raising `InvalidAuthorisationError` chained
> from it (`raise … from`), so a caller keeps the one handler `AuditError` already
> gives it while an operator keeps the two facts apart — "the pointer named no
> outstanding grant" and "the seam could not be read" — in the message and in
> `__cause__`. A component that cannot get an answer from this seam fails closed
> (§1's last clause), and the trail is such a component.

> **Normative.** The refusal is `InvalidAuthorisationError`, a third sibling under
> `AuditError` in `ai_assistant.core.errors`, beside `DuplicateDecisionError` and
> `InvalidResolutionError`. Its stated subject is that a decision's standing
> authorisation was **not validated** — the pointer named no outstanding grant, the
> grant it named does not cover the decision, or the seam could not be read. It is
> its own class for the reason those two are — a replayed write, a substituted
> resolution subject and an unvalidated standing pointer are three facts an
> operator must be able to tell apart — and no lane widens
> `InvalidResolutionError`'s stated subject to cover it.

> **Normative.** `record` checks existence, kind, unrevokedness, liveness as of the
> ruling, and subject match, and **nothing else**. It does not re-rule, does not
> consult a clock, does not call `covering`, does not rank grants, and returns no
> outcome. ADR-0021 §3's division is unchanged: the policy rules, the caller
> records, the trail validates what it holds both halves of.

> **Normative.** An `ActionPolicy` constructed with no `RecipientGrants` returns
> `authorised_by is None` from `decide`, exactly as ADR-0021 §3 requires today. A
> policy given one may set it, and only to the `id` of a grant it read from that
> seam and found covering under §3.

**This is the check ADR-0021 §4 already runs, at the same place and to the same
standard.** That section put the resolution invariant in `record` "because it is
the only place both records are in hand", and enumerates what it compares: "the
referenced id is present, its ruling was `CONFIRM`, no other recorded decision
already resolves it, and its `tool`, `parameters_digest` and `step_id` match the
incoming decision's exactly." ADR-0021 §3 states in one sentence the standard
that invariant meets, and it is the standard this section had to meet too:
**"Nothing is taken on trust."** The same section asked the standing-grant ADR to
make the second source "resolvable — to a recorded user decision that actually
covers this tool — and … say where those records live". §1 says where;
this section resolves it there, against the record, and not against the policy's
word for it. As the Context records, `record` today applies no check at all to a
non-resolving `ALLOW`.

**Three earlier drafts of this section did something weaker, and the record of
why is worth keeping.** The pointer began as a bare `str` the trail did not check.
Round 3 minted an opaque id type to make it unforgeable, and round 5 found that
thirty-two hex characters encode sixteen bytes of anything a caller chooses. Round
6 moved the whole grant into the decision by value, and round 7 found both that a
policy can author that value as easily as it could author the string, and that no
conforming path could populate it anyway — `decide` returns a `PermissionRuling`,
the query face lives inside the policy, and the recorder has nothing to
reconstruct it from. Each repair moved the *evidence* without moving the
*authority* for it. Reading the store adds the one thing none of them had: a
record the trail consults that the policy did not write.

**Embedding the grant by value is refused, and its two costs are why.** A covering
grant may name a large superset of one call's recipients — as many as
nothing in this ADR bounds (§1, #1551) — so copying it into every decision
multiplies a Tier 1 store against ADR-0004 §7's minimisation rule: a
grant over ten thousand recipients spent on ten thousand single-recipient calls
writes a hundred million destination entries into the trail, nearly all of them
unrelated to the call each row is about. The ceiling bounds that product; it does
not make it proportionate, and a fingerprint of fixed size does. And a
value the recording caller must supply is a value it has no honest way to obtain:
a second lookup by the recorder answers a different question than the one the
policy ruled on, and an overlapping newer grant appearing between the two would
leave it unable to recover the id the policy returned. The pointer is what
ADR-0021 §3 asked for in the first place, and it is the one shape that needs no
new channel.

**Reading the store inside `record` is not the race an earlier round rejected.**
Round 6 rejected a liveness check at `record` on the ground that a revocation
landing between the ruling and the write would make an honest `ALLOW`
unrecordable. That is true, and it is the correct behaviour rather than a defect:
the user revoked, and the call does not happen. What round 6 was right about is
that the check must not *retroactively* invalidate a row already written — and it
does not. `record` decides **once, at the resolution read**, over the store as it
stands at that instant, and no component re-evaluates it afterwards (§9). Expiry
is decided over the decision's own `decided_at` for that reason, so the only fact
read from the store there is the monotone one: a grant once revoked is never
un-revoked, so a "revoked" answer is never stale, and a "not revoked" answer is
stale only toward the window §9 states and bounds.

**Id reuse after a `clear` is closed twice over, and the second closure is the
one that took a round to get right.** A `clear` followed by a re-recorded id can
put a different grant behind the same pointer, because ids are caller-minted
`DurableIdentifier`s and `clear` erases the history that would have made one
unrecyclable. The half `record` itself decides was already closed: the pointer is resolved
at the resolution read and the resolved grant's tool, account and destination set
are compared against the decision's own, so no row was ever appended on a grant
that did not cover it. Architecture review's ninth-round blocker was about the
other half, and the objection was right — a durable pointer that later resolves to
a grant which did not authorise this decision is a **false record**, and
forbidding later reads makes it unread rather than true.

**The digest gives the pointer a falsifier, which the bare pointer did not have.**
The row carries the fingerprint of the grant it was validated against, over every
field the record carries but its `id`, so a rebound id resolves to a record whose
`subject_digest` differs and the difference is conclusive. That is the direction
that matters and it is the one the objection was about: a pointer that could
resolve to a different grant with **nothing on the row to contradict it** is a
false record, and a pointer whose row carries a fingerprint that the different
grant fails is not.

> **Normative.** The guarantee is **one-directional**, and no lane states it as
> more. A **mismatch** is conclusive: this record is not the one the row rested
> on. A **match** establishes only that this record agrees with the row in every
> field a `RecipientGrant` carries but its `id` — which is the same user act
> where neither store has been cleared and an id reused since the row was
> written, and may not be where either has. The report for a match is therefore
> **consistent**, never "verified" or "proven", and no surface, export format or
> later ADR renders it as the stronger word.

**Where the check is available, and where it is deliberately not performed.** No
component of this system re-resolves a recorded `authorised_by` — not a surface
(§11), not a policy, not the trail after its own write — and this ADR adds no such
read. What it adds is the *evidence*: the trail's `export` carries the decision,
which carries the ruling, which carries the digest, and the grant store's `export`
carries every record, from which `subject_digest` recomputes. A user holding both
exports, or a later ADR that decides an operator wants an integrity pass, can
falsify a rebound pointer — and, under the clause above, can say a sound one is
consistent rather than proven. That is ADR-0004 §6's portability doing the work,
and it needs no store read inside the render path and no capability any component
gains today.

**Architecture review pressed this across four rounds and the ADR ends where the
evidence does.** Round 9 said forbidding later reads does not make a pointer
true; round 11 said a caller-supplied instant is not an act identity; round 12
said an independently cleared trail leaves `established_by` dangling; round 13
said that with **both** stores cleared and both ids reused inside one clock
instant, every digested field can be made to agree. Each is right, and each
narrowed the claim rather than the mechanism: what is left is a fingerprint that
cannot be made to *disagree* with the act it was taken over and cannot be made to
*prove* agreement across the user's own erasures. Both halves are stated. The
alternative — a durable establishment generation no clear can rebind — would have
to live in a store the user may erase, which is where round 3's tombstone died and
what the ruling on this seam already excluded.

**The three directions the reviewer offered are each one this loop has ruled on,
and the digest is none of them.** Non-rebindable identity is round 3's tombstone,
killed in round 5 when the opaque id type turned out to encode sixteen bytes of
anything a caller chooses. Preserving the whole grant with the decision is round
6's embedded value, killed in round 7 for storage amplification and again because
no conforming path could populate it. Coordinating validation and append is the
one store §1 refuses on capability grounds. A digest keeps the third's *evidence*
without its cost, needs no cross-store lock, and — unlike a tombstone — survives
`clear` on the only side that matters, because it is carried by the row rather
than by the store the user is entitled to erase.

**Subject match is not a re-ruling.** It compares recorded values, exactly as the
resolving check compares `tool`, `parameters_digest` and `step_id`, and it authors
no outcome.

**An optional field rather than a discriminated evidence variant, and the reason
is the same one round 7's third blocker gave.** The alternative shape is a union —
`RecipientGrantEvidence | ...` — carrying the digest inside an arm typed to this
ADR's record. Three things are wrong with it here. It would be a union with
**one member today**, which is the surface-with-no-consumer shape ADR-0045 §1
tests against, and the second member would arrive as a breaking change to
everything that had pattern-matched on the first — the very outcome round 7's
blocker #3 was raised to avoid, one field over. It would name a recipient-specific
type on `PermissionRuling`, which is what made `authorising_grant: RecipientGrant`
narrow ADR-0021 §6's still-deferred standing grants for other actions; a
`Sha256Hex` names nothing and narrows nothing, and the ADR that opens the next
standing source sets the same field to a digest over *its* record's subject and
adds its own arm to `record`'s check. And `authorised_by` beside it is already an
optional field with exactly this shape — present where an authorisation is cited,
absent otherwise — so a second optional field is one spelling of one fact rather
than two carriages of it (ADR-0150 §1). What the union would have bought is a
type-level guarantee that the digest and the id agree about *which store*, and
that guarantee is unavailable anyway: `resolves` and `egress_binding` are what
discriminate the route (§6's discriminator clause), and they are on the decision
rather than on the ruling.

**What is left unclosed is stated rather than glossed.** A policy that read a
grant and whose `ALLOW` reached `record` before a revocation landed is inside §9's
window and is accepted there. A **recording caller** that hand-authors a decision
— a `decided_at` chosen to fall inside an expired grant's window, say — is
falsifying its own trail, which is the boundary ADR-0018 §3 drew for detachment
and which route (a) sits behind identically. What is **not** left open any longer
is the failure ADR-0021 §3 named: a policy can no longer satisfy §5's floor "by
writing something in a box", because the box is now checked against a record the
policy cannot write.

**Single use is not claimed and is not this ADR's to claim.** ADR-0021 §4 is
explicit that the trail "bounds resolutions, not executions", and that making an
approval single-use "needs an atomic consume-on-execution step, which belongs to
the invocation contract (ADR-0016 §7)". A standing grant is by construction
many-use, so nothing here needs that step; the invocation record lane (ADR-0192)
owns it and this ADR neither supplies nor pre-shapes it.

**Why the discriminator is `resolves` and not a new field.** #68's first comment
requires that "the audit record must capture the resolved destination plus which
of the two authorised it". The resolved destination is already captured — the
binding is transcribed into the decision by `PermissionDecision.from_request` and
compared whole by `authorises`. Which of the two authorised it is then a function
of two fields the record already carries, and it is total: a route-(a) `ALLOW`
cannot have `resolves` unset, because `resolve` is the only path that sets
`authorised_by` from a confirmation and `record` refuses a resolving `ALLOW` whose
pointer is not its own `resolves`. A third field would be a second spelling of a
fact the record already determines, and ADR-0150 §1's argument against a second
carriage applies unchanged. `authorised_subject` is not that field: it says
**which grant**, not **which route**, and the route is still read off `resolves`
by a component that never looks at the digest.

#1548 records the one surveyed runtime that gets this right and how: OpenAI's
`_ApprovalRecord.approved` is `bool | list[str]`, so a permanent approval and a
per-call one are different *shapes* in the record and an auditor can tell them
apart without a flag. `resolves` is that discriminator here, already recorded,
already validated, and already total.

### 7. The check point is `ActionPolicy.decide`, and the seam is not offered one

> **Normative.** Route (b) is evaluated in `permissions/`, by an `ActionPolicy`
> implementation, inside `decide`. Nothing in `tools/` consults a grant, holds a
> `RecipientGrants` or a `RecipientGrantStore`, or reaches an authorisation
> conclusion of its own.

> **Normative.** `ActionPolicy` gains no method, no argument and no widened
> return. The query face is a constructor dependency of an implementation, and an
> implementation that does not take one is a conforming policy that reaches no
> route-(b) `ALLOW`.

> **Normative.** `EgressBinder` is unchanged. It derives the binding whole and
> accepts no part of it (ADR-0152 §5), and no clause here adds a grant read, a
> coverage test or an authorisation outcome to that seam or to `rebind`.

**Four reasons, and the first is decisive on its own.** `authorised_by` is a field
of `PermissionRuling`, and ADR-0021 §3 splits the ruling from the decision
precisely so that only a policy may author one — "everything describing *what was
ruled on* is transcribed from the request". A binding seam that reached an
authorisation conclusion would either have to author a ruling, which it cannot,
or hand a conclusion to something that does, which is the same capability with a
longer name.

Second, ADR-0148 §8's first clause names `ActionPolicy` as "the authority to
refuse an egress call", so the authority that may refuse is where the rule that
may permit belongs; splitting them puts half of one decision in each of two
subsystems.

Third, golden rule 1. `permissions/` may not import `tools/`, and `tools/` has no
business holding the user's standing policy state. A grant read at the binding
seam would put an authorisation store inside the subsystem being authorised —
the shape ADR-0097 §3 removed for readers, and the shape #83 names on the
transport axis: "if each integration builds its own client, this is unenforceable
by construction."

Fourth, the facts are already there. The seam derives the binding *before* the
ruling (ADR-0148 §1, ADR-0152 §5) and `ActionRequest.egress_binding` carries it,
so `decide` holds the canonical destination set, the declaration and
`planned_with_external_content` by value, with no I/O and no second derivation.
The policy today reads the binding for ADR-0181 §5's antecedent; §3's comparisons
read the same value.

> **Normative.** `decide` writes nothing, mints no id, reads no clock, resolves
> **no id against any registry or store**, and consults exactly **one** injected
> read seam — `RecipientGrants.covering`, which takes the whole request and
> returns a record. It reaches no second seam and caches no answer between calls:
> the seam is consulted **at most once per ruling**, and its answer is used or
> discarded within that ruling.

> **Normative.** The lookup happens **after** every ground for the outcome that
> the request alone settles — §4's origin bar among them — so a request already
> refused on its own facts reaches no seam at all. Where the lookup does happen,
> `None` and `RecipientGrantError` both fail closed (§1's last clause) and the
> ruling proceeds without a route-(b) `ALLOW`. An earlier draft of this clause
> said the policy "reads nothing on a path that does not lead to a route-(b)
> `ALLOW`", which adversarial review found unsatisfiable at round 11 and was
> right about: whether the path leads there is not knowable until the seam has
> answered. What the clause can require, and now does, is that the read be last,
> single, and fail-closed.

**What the policy still may not do is unchanged.** It consults no `AuditTrail`,
no `SourceGrants`, no `SourceGrantStore` and no registry; it mints no id and
reads no clock (§9 puts the clock in the store, on ADR-0007 §2's precedent); and
`decide` stays a function of its argument and its injected seams, which is what
keeps ADR-0021 §5's monotonicity obligations checkable.

**The clause above is written because ADR-0021 §3's purity framing has a subject,
and it is worth naming which part of it survives untouched.** That section makes
the request self-contained "so a policy never consults a registry", and gives the
reason in the next breath: "a policy that resolved an id would be reintroducing
the rebinding hazard inside the very subsystem meant to close it". `covering`
resolves no id. It takes the request and returns the record; `RecipientGrants`
carries no read-by-id member and §1 forbids adding one; the resolution face that
*does* resolve an id is held by the trail and by nothing else. So the hazard the
purity clause was written against is closed by this ADR's own §1, not merely left
alone by it — which is why §15 classifies the seam as a stacked addition rather
than as a supersession.

### 8. A partially covered set is one `CONFIRM` about the whole set

> **Normative.** Where some members of a request's canonical destination set are
> covered and some are not, the request is **not** `ALLOW`ed on route (b). The
> ruling is `CONFIRM` about the whole call, and the confirmation names the whole
> canonical destination set under ADR-0148 §8's fourth clause — covered members
> included.

> **Normative.** No component removes an uncovered member, narrows the set to the
> covered members, constructs a second request from either part, splits a call
> into a covered and an uncovered half, or offers such a narrowing to the user in
> place of the confirmation. This is ADR-0148 §4's second clause and nothing here
> weakens it.

**`CONFIRM` rather than `DENY`, and the difference matters.** ADR-0148 §4 says
the call is "refused" where a member is uncovered under §3 — and §3's route (a)
is a resolution that does not exist before the ruling, so "uncovered" at `decide`
time is the ordinary state of every egress call today, answered by asking. A
policy that returned `DENY` on partial coverage would make a grant over one of
two recipients strictly worse than no grant at all, which is the shape a user
would learn to avoid by never granting.

**And the confirmation names the whole set, not the remainder.** A card asking
about the two recipients the user has not blessed, for a message going to four,
is ADR-0148 §4's silent narrowing arriving at the surface instead of at the
transport: "a message approved as *to Alice and Bob* is a different message from
the same text *to Alice only*". The user is answering about a call, and the call
has four recipients.

### 9. Revocation is prospective, expiry is stated, and the store carries the data rights

> **Normative.** A grant is withdrawn by the user, by an appended record naming
> the grant it revokes. Revocation is **whole** — there is no partial revocation
> and no in-place narrowing — and it retracts no decision already made. A recorded
> `ALLOW` stays recorded and stays true about the moment it was made (ADR-0186
> §8's first clause).

> **Normative.** Revocation is **prospective, and it bites twice**: it governs
> every `covering` read that begins after it is recorded, and it refuses the write
> of any route-(b) `ALLOW` whose **resolution read inside `record`** (§6) begins
> after it is recorded. It retracts no decision already recorded, and it does not
> order itself against a resolution read that had already answered — so an `ALLOW`
> validated an instant before a revocation is still appended, and may still be
> executed. No clause of this ADR claims a stronger ordering, and no lane states
> or implies one.

> **Normative.** The residual window therefore runs from **`record`'s resolution
> read** to the execution. It is strictly smaller than the window a check at the
> policy's lookup alone would leave, because that lookup is strictly earlier; it
> is not zero, and no clause here rounds it to zero. A `clear` racing that same
> interval has the same effect and is the same window (§1). No lane closes what
> remains by re-reading the grant seam at the seam that runs the tool, or by a
> linearisation across the two stores; a later ADR that wants a stronger ordering
> decides it explicitly and with an implementation in hand, and it may not be
> inferred from this section's silence.

> **Normative.** Every grant carries an instant after which it is not live, and
> there is **no unbounded spelling** of it: no null, no sentinel, no "forever".
> The user chooses the instant in the establishing act.

> **Normative.** On a **granting** record, `expires_at` is **strictly after**
> `decided_at`, refused at construction otherwise. A record expiring at or before
> the instant it was decided is never live for any duration, so it authorises
> nothing while still occupying an outstanding slot (§1's count ceiling) and
> blocking an identical grant until the user performs a revocation they had no
> reason to expect. It is a grant in shape and nothing in effect, and refusing it
> at construction is cheaper than every clause that would otherwise have to
> tolerate it. A **revoking** record is unaffected: it is never live and its
> instants are ordered by no rule (§1).

> **Normative.** Liveness is a property of **granting** records only — those whose
> `revokes` is `None`. A revoking record is never live, is never returned by
> `covering` or `standing`, and is never a valid `authorised_by`; it appears in
> `recent` and `export` as the record of an act, which is what it is.

> **Normative.** A granting record is **outstanding** when no revoking record
> names it, and **live** when it is outstanding and the clock stands at or after
> its `decided_at` and strictly before its `expires_at` (§1). An expired grant —
> and a future-dated one — is still outstanding, so it can still be revoked
> and it still blocks an identical new one until it is. Liveness is evaluated by
> the store at read time, so the store reads the clock and the policy does not
> (ADR-0021 §3, ADR-0007 §2's read-time enforcement). `outstanding` and
> `AuditTrail.record` read **no** clock at all: outstanding is a fact about two
> records, and the trail decides expiry against the decision's own `decided_at`
> (§1, §6).

> **Normative.** A query that **evaluates liveness** — `covering` and `standing`,
> and no others — reads the clock **exactly once** and evaluates every record it
> considers against that one instant. A `standing` that read an advancing clock per
> row could return one of two grants sharing an `expires_at` and omit the other,
> which is a set true at no real instant. `outstanding` reads **no** clock and is
> not an exception to this clause but outside it (§1); `recent` and `export`
> evaluate no liveness and read none either.

> **Normative.** An expired or revoked grant is **not deleted** by expiry, by
> revocation, or by any operation but `clear`. It stays in the store, outstanding
> or not, so a user can see and revoke what they once granted and `export` can
> carry it.

> **Normative.** The store's records are **Tier 1** (ADR-0004): a canonical
> destination is a recipient of the user's, and the store is durable, ordered and
> rendered to the user. It persists locally only, `export` returns a portable
> snapshot of every record, and `clear` erases the store wholesale and returns the
> count. There is no `delete(id)`.

> **Normative.** `clear` on this store **retracts, invalidates and re-opens
> nothing**. A recorded `ALLOW` stays recorded, stays true about the moment it was
> made, and still names the grant it rested on; §11's second state is read from
> the row and does not change. What is lost is the grant's **own text** — its other
> members, its expiry, its establishment act — because the row carries the pointer
> and a fingerprint rather than the value, and nothing re-resolves it (§6). The
> `authorised_subject` survives the erase and is not read as a claim that the
> record it fingerprints still exists: after a `clear` it matches nothing, which
> is the same statement the pointer makes and not a second one. The trail still carries the
> whole binding: the resolved destination set, the account and the payload
> description are on the decision by ADR-0148 §6 and ADR-0150 §1, not fetched from
> the grant. What `clear` also destroys is the user's ability to see, revoke or
> renew that grant.

> **Normative.** `record`'s check (§6) is performed **once**, at its resolution
> read. No component re-evaluates it later, treats a subsequently erased, expired
> or revoked grant as invalidating a recorded decision, or refuses to render such
> a row. The `authorised_subject` the row carries is likewise never re-checked by
> this system; it is evidence a holder of both exports can check, not a gate any
> component runs again (§6).

> **Normative.** No lane makes this store's `clear` conditional on, coordinated
> with, or transactional against the audit trail's. Cross-tier erasure is
> ADR-0007 §4's deferred coordinator and is not decided here; what is decided is
> that each store's own wholesale erase is the user's to perform and that the
> consequence above is disclosed rather than designed around.

**The window is stated because it is real and bounded, and §6 makes it smaller
than earlier drafts of this section did without making it vanish.** Between a
`covering` read returning a grant and the resulting `ALLOW` reaching `record`, a
revocation can land — and because the trail resolves the pointer again, that
`ALLOW` is now **refused** rather than recorded. What that moves is the boundary,
from the policy's lookup to `record`'s resolution read. It does not move it to
the append: those are two awaits, and round 8 of this review blocked on an earlier
draft of this section that said otherwise. Closing the remainder would take a
re-read at the seam that runs the tool, or a linearisation across the grant store
and the trail: the first puts an authorisation conclusion in `tools/` (§7), and
the second is the cross-store transaction this section and ADR-0007 §4 both
decline to invent for erasure, refused for the three reasons §1 gives.

**What the window contains is stated exactly, because an earlier draft said "one
call" and that was false.** Adversarial review found on round 4 that one event
loop runs many concurrent tasks, so the set that passes after a revocation is
**every ruling whose resolution read had already answered and whose execution has
not yet run** — bounded by the rulings in flight at that instant and by nothing
this ADR states. There is no per-grant serialisation, no reservation and no cap,
and no clause here claims one. What is *not* in the window is any ruling whose
resolution read begins after the revocation is recorded, and any widening: every
call that passes goes to a recipient of the grant the user had authorised, under
the same declaration and the same account, with nothing in it moving after the
ruling (ADR-0148 §1, §4).

**And it is the prospectivity the corpus already ships.** ADR-0097 §4 delivers
revocation in exactly this sense for source grants — liveness computed at the
read — and a producer already reading a source when the grant is withdrawn
finishes that read. A user who needs a send to stop *now* has the recourse they
have for anything already in flight, which is not this ADR's to supply.

**The bound the expiry clause obtains is that the user chose an end, and it is
not that the end is near.** A user may name a date decades out and the clause is
satisfied; nothing here claims otherwise, and no lane reads it as a retention
policy. What it removes is the spelling that lets a surface, a migration or a
default create a grant nobody ever revisits — the same reason ADR-0185 §6 refused an
unlimited spelling for the read trail's bound, and the reason ADR-0097 §8 refuses a
grant minted from configuration. The asymmetry with `SourceGrant`, which has no
expiry, is deliberate and is the one this corpus keeps drawing: a source grant
authorises reading *in*, and this authorises sending *out*.

**The erasure clauses are the resolution of a real tension, and it is resolved
toward the data right.** §6 makes a route-(b) pointer meaningful by resolving it
into this store; §9 lets the user destroy this store. Both must hold, and the
only question is which gives. It is the resolvability, because the alternative is
a store the user cannot erase because an audit row points into it — an audit
trail acquiring a veto over a data right, which is precisely inverted. ADR-0021
§4 drew the same line for the trail itself: "the user may burn the book; nobody
may tear out a page." Burning this book leaves the trail's rows intact, still
saying which route authorised them and still carrying the whole binding — the
resolved destination set, the account and the payload description are on the
*decision*, by ADR-0148 §6 and ADR-0150 §1, not fetched from the grant. What is
lost is the grant's own text, and §11's rendering clause says so on the row
rather than leaving a reader to infer it.

**Selective deletion is refused for a reason that is not the audit trail's.**
ADR-0021 §4 refuses a `delete(id)` on the trail because "selective erasure of an
audit trail is indistinguishable from tampering with it". The grant store's
reason is narrower and is stated on its own: an `authorised_by` in the trail
points into this store, so deleting the record it points at makes a recorded
`ALLOW` unexplainable while leaving it looking complete. Revocation is the act a
user wants and it is available; erasure is a data right and it is available
wholesale. That is ADR-0004 §6 discharged without a hole in the middle of it.

### 10. #68's remaining open question is dissolved, not answered, and this ADR declines to re-open it

> **Normative.** Whether an operation "cannot disclose onward" is neither declared
> per tool nor derived. No `RecipientGrant`, `ToolDefinition`, declaration
> vocabulary or policy rule carries such a property, and no lane adds one citing
> #68 or this ADR.

> **Normative.** The question is settled by ADR-0148 §2's third clause, which this
> ADR consumes unchanged: a call whose arguments select no recipient beyond the
> service it is made to has the connected account as its whole canonical
> destination set, and is authorised against that. A grant naming the account
> member (§3) is how a user makes such calls standing.

**#68's second comment asked for the property and warned about it in the same
breath** — "whether an operation can disclose onward is itself a property someone
has to declare or derive, and getting it wrong reopens the hole." ADR-0148 §2
answered by removing the need for it: the rule is stated over what the arguments
*select*, so the carve-out "is not an exemption from authorisation but an answer
about what is being authorised", and a mis-declaration is "a defect in the same
class as a mis-declared `discloses`". Re-introducing the property here would give
a grant a second thing to be conditional on, and the second thing would be the
one nobody can check.

### 11. What the audit surface renders, and what it still may not

> **Normative.** A surface rendering a decision under ADR-0186 §1 renders, for a
> row whose ruling is `ALLOW`, **what authorised it**, in exactly **three** states,
> each distinct from the other two and none rendered as any other: a decision of
> the user about *that* call (`resolves` set, `authorised_by` equal to it); **a
> standing authorisation this row names** (`resolves` unset, `authorised_by`
> set); or **the policy's own rules, resting on no user decision**
> (`authorised_by` unset). This extends ADR-0186 §7 by one fact and changes none
> of its others; every clause of §7 and §8 holds unchanged over such a row.

> **Normative.** Every state is derived from **the row alone**. No surface reads
> the grant store, holds a `RecipientGrants` or a `RecipientGrantStore`, resolves
> an `authorised_by`, or acquires any operation ADR-0186 §1 does not already
> promote. That is golden rule 3 and ADR-0186 §1's own limit: a renderer given the
> store face would hold `record` and `clear`, and a remote client could not
> perform the read at all without a second contract.

> **Normative.** The second state asserts **exactly what the row says and nothing
> more**: that this decision names a standing authorisation. No surface states or
> implies that the named grant exists, is held by the store, is live, is
> unrevoked, has not expired, was validated, or covers anything now — ADR-0186
> §8's first clause, which names a grant in terms, read on this fact.

> **Normative.** The bar on "was validated" is a bar on the **surface** asserting
> it of the row in front of it, and it does not contradict §6, which requires
> `record` to validate every route-(b) row it writes. The two hold together
> because a surface cannot tell the two kinds of row apart: a row written before
> this ADR's implementation was validated by nothing (the Context's tree reading),
> the row carries no mark saying which it is, and no surface has a read with which
> to find out. So what §6 makes true of every row written *after* the
> implementation is a fact about the system, and it is not a claim any renderer is
> entitled to make about a particular row.

> **Normative.** The row also carries `authorised_subject` (§6), and a surface
> renders it as **opaque** or not at all. No surface presents it as a
> verification, a match, a badge, an assurance or a difference from another row;
> none decodes it, compares it against anything, or resolves the grant to compare
> it against; and none states or implies that a row carrying one is more
> trustworthy than a route-(a) row, which carries none because it rests on a
> confirmation instead. The comparison the digest makes possible is an
> out-of-band one over two exports (§6), not a rendering, and no lane reads this
> clause as licence to move it into the render path.

> **Normative.** The three states are total over `ALLOW` rows and none is a
> residual or an error. ADR-0021 §5's floor bars an auto-granted `ALLOW` only for a
> **non-empty `discloses`**, so a non-disclosing, known-cost action reaching
> `ALLOW` with `authorised_by` unset is conforming and ordinary, and ADR-0186 §1's
> operations return every decision rather than only egress ones. A surface that
> forced such a row into another state would be asserting a user decision that was
> never taken.

> **Normative.** No surface distinguishes, on a second-state row, a grant the
> store still holds from one the user has erased, from one that expired, or from a
> pointer written before this ADR's implementation validated any. It has no read
> with which to, by the clause above, and it would not be entitled to assert the
> difference if it had one.

> **Normative.** No surface renders the third state as an omission, a blank, a
> failure to record, or anything a reader could mistake for either of the first
> two — ADR-0186 §7's three-origin-state discipline, read on this second
> three-state fact.

> **Normative.** No surface derives liveness from the row. It states that the
> decision **names** a standing authorisation — never that a grant existed, was
> the basis in fact, is current, still covers anything, or has not been revoked.
> That is ADR-0186 §8's first clause, which names a grant explicitly, read on the
> fact this section adds, and it is the strongest claim a row supports: `record`
> validated the pointer **at its resolution read** for every row written after
> this ADR's implementation, and for a row written before it validated nothing
> (the Context's tree reading). In neither case does the row say anything about
> the grant's state now.

> **Normative.** No surface renders the basis as an approval control, an
> assurance, a risk signal, or a reason to suppress, reorder or de-emphasise any
> part of ADR-0186 §7. It is a fact about the decision, rendered as data and
> neutralised for its target on render.

**A row written before this ADR's implementation says the same thing as one
written after, and that is the honest reading rather than a gap.** On
`origin/main` no conforming policy produces a non-resolving `ALLOW` carrying an
`authorised_by` — `ThresholdActionPolicy.decide` documents that the field is
"always unset", and `resolve` sets it equal to `resolves` — but `record` accepts
the shape today without a check (the Context's tree reading), so the corpus
cannot assert that no such row exists. The second state is stated over what the row carries: this
decision **names** a standing authorisation. That is true of a validated row and
true of an unvalidated one, and it is the strongest claim available without a
read the surface is not entitled to. ADR-0184 made the same move for the same
shape one field over — the absence is its own value, not a spelling of a present
one — and it needs no migration, no backfill and no rewriting of an append-only
store.

**Aliasing is closed twice, and this section carries the half that is a bar
rather than a mechanism.** Round 2 of this review raised a recorded
`authorised_by` being rebound to a different future grant after a `clear`, and
round 3's repair was a tombstone of every id the store had ever held, with an
opaque minted id type to keep that tombstone free of the user's data. Round 5
found the type could not deliver that — thirty-two hex characters encode sixteen
bytes of anything a caller chooses — and the tombstone was removed rather than
hardened. What stands in its place is this section's second clause and §6's
digest, and they answer different halves. **No surface resolves a recorded
`authorised_by` at all**, so no *rendered* claim can be misled by a rebinding;
that is the bar, it is stated here, and it needs no machinery. Whether the stored
pointer is nevertheless *true* is the other half, and forbidding the read does not
settle it — architecture review was right about that on round 9. §6's
`subject_digest` is what answers that half, **in one direction and not two**: the
row fingerprints the grant it was validated against, so a rebound id resolves to a
record that fails the comparison, for anyone who ever makes it. It does not
establish the converse, and §6's own clause says so — a record that matches is
*consistent* with the row rather than proven to be its authoriser, because a user
who clears both stores and reuses both ids can make every digested field agree. No
lane reads this paragraph as stating more than that clause does. An id stays an
ordinary `DurableIdentifier`, as `PermissionDecision`'s and `SourceGrant`'s are;
what the row gained is a falsifier, not a new kind of identity.

**Three states rather than two, and the third is what makes the pair honest.**
An earlier draft of this section rendered "which of ADR-0017 §2's two bases
authorised it" over every `ALLOW`, which architecture review found unsatisfiable
on round 1: neither basis is true of a policy-granted `ALLOW`, and ADR-0186's
listing is not scoped to egress. Scoping the clause to egress rows would have
been the other repair and is the worse one — it leaves a reader of a non-egress
`ALLOW` with no statement at all about what authorised it, when the record
already determines the answer. The discriminator is total because
`authorised_by` and `resolves` are, and §6's discriminator clause is what makes the
first two unambiguous.

**#68's first comment is the whole reason this section exists**: "the audit record
must capture the resolved destination plus which of the two authorised it —
otherwise nobody can distinguish an authorised recipient from a defaulted one
after the fact." The resolved destination is already rendered under ADR-0186 §7's
second clause. The basis was previously constant and therefore unrenderable as a
distinction; from the moment route (b) exists it is a fact with two values, and a
history that showed them alike would be answering #68's question wrongly rather
than not at all.

**It is one fact and not a grant projection.** The row does not carry the grant's
own text, its expiry, its other members or its establishment act, and no clause
here asks a surface to render them. `authorised_subject` is not a counter-example
and is the reason this is worth saying: it is a digest **over** those values —
`established_by` among them since round 12 — and it carries none of them. A digest
is not a projection, and nothing can be read back out of it. ADR-0186 §8's bar on deriving liveness from
history is exactly the reason: a surface that rendered the grant would be
rendering a record whose current state it must not assert.

**A round of this review was spent going the wrong way, and the record is worth
keeping.** Round 2 found that this section's prose ("no clause asks a surface to
fetch") contradicted a clause requiring the row to say whether its grant was
still held, and the repair taken was to permit the fetch. Round 3 found what that
bought: a renderer holding `RecipientGrantStore` holds `record` and `clear` too,
which is golden rule 3 breached to render a column, and ADR-0186 §1 promotes two
decision operations and no store read, so a remote client could not do it at all.
The contradiction was real and the other half was the one to repair. The states
are row-derived, the surface reads nothing, and the resolution face (§1) exists
for §6's write-path check alone — held by the trail, named by no renderer, and
carrying neither `record` nor `clear` for one to reach.

### 12. ADR-0154 §4's floor, partially superseded, and precisely which clause

> **Normative.** ADR-0154 §4 item (ii)'s **first** clause — "No standing
> authorisation … covers any egress call through this seam. Every egress call is
> authorised by a decision of the user about **that** call, on ADR-0148 §3's route
> (a)" — is **partially superseded** by this ADR, in exactly one respect: a
> `RecipientGrant` covering a request under §3 may source an `ALLOW`. Every egress
> call not so covered is still authorised by a decision of the user about that
> call.

> **Normative.** Item (ii)'s **second** clause is satisfied, not superseded. This
> ADR establishes its rule over the recorded origin fact ADR-0181 §3 put on the
> binding, evaluated by the authoriser at the moment it rules (§4), which is what
> that clause requires of "the ADR that would permit a standing authorisation".

> **Normative.** Nothing else in ADR-0154 changes. §1's designation, §2's clauses,
> §4's fourteen attestations and their verdicts, §5's transition and §7's limits
> all stand. ADR-0154 §2's clause that no *configuration* grants a standing
> authorisation for a recipient is untouched and is reinforced by §2's second
> clause above.

> **Normative.** ADR-0017 §3's condition 3 is unchanged and is not narrowed,
> widened or re-attested here. It offers two acceptable sources; ADR-0154
> satisfied it by the first alone and said so; this ADR makes the second available
> and neither adds a condition to §3's list nor relaxes one.

> **Normative.** The lane that implements this ADR re-attests ADR-0154 §4's
> condition 3 in the same change, under §4's own rule that "a later change that
> falsifies any subsection's stated property … either restores the property in the
> same change or opens an ADR reconsidering the designation". What that lane owes
> is a dated amendment note on ADR-0154 recording that condition 3 now holds by
> both limbs of ADR-0017 §3's disjunct rather than by the first alone. It does not
> owe an ADR reconsidering designation, because the condition itself is unfalsified.

**This ADR lands no code, so it falsifies nothing today.** ADR-0154 §4's
attestation is stated over what is "satisfied in code at `origin/main`", and its
condition 3 subsection's stated limit — "route (a) is the only available route
today" — is true of the tree this ADR merges into and stays true until the
implementing lane lands. The obligation therefore rides with that lane, which is
where §4's own clause puts it.

**Why supersession and not amendment for the first clause.** ADR-0070 §1's test
is whether a reader acting on the earlier ADR would act identically before and
after. A reader holding ADR-0154 §4 alone would refuse a grant-sourced `ALLOW`;
after this ADR they must permit one under §3. That is a change to what was
decided, so it takes a new ADR that supersedes — partially, scoped to the one
clause, with ADR-0154's `Status` line taking the leading `Partially superseded by`
token and the record living in its appended dated note (ADR-0082 §2).

### 13. What this ADR does not decide

> **Normative.** No lane cites this ADR toward designating any boundary, toward
> ADR-0124's boundaries, toward a change to `models/`, or as authorising any
> transmission. It supplies a mechanism; nothing here attests that anything holds
> in code.

> **Normative.** No lane cites this ADR toward the consume-on-execution step, the
> invocation record, exactly-once execution, spend accumulation, a budget ceiling,
> or a transport capability. Those are other lanes' and this ADR neither supplies
> nor pre-shapes them.

> **Normative.** No lane reads this ADR as deciding **which** surfaces offer the
> establishing act, what the wire carries for it, or how a browser or
> command-line surface lays it out. What §2 decides is that the act rides an
> answer to a recorded `CONFIRM` and what any surface offering it must show; the
> surfaces themselves, and the revocation surface §9 assumes, are ADR-0177's,
> ADR-0178's and ADR-0186's to decide.

> **Normative.** No lane reads this ADR as deciding anything about `SourceGrant`,
> `SourceGrants` or `SourceGrantStore`. ADR-0097 §7 stands verbatim: a source
> grant may never be cited as `PermissionRuling.authorised_by`, and no
> `ActionPolicy` may consult either source-grant seam.

> **Normative.** This ADR does not fix the **value** of
> `Settings.recipient_grant_max_outstanding`, nor a default for it. §1 decides
> that the ceiling exists, is configured, is counted inside `record`'s atomic
> operation, governs admission rather than eviction, and never refuses a
> revocation; the number a deployment chooses is a deployment's, and no lane reads
> §1 as naming one. Nor does this ADR decide any migration for a store holding
> records a lowered ceiling would not admit: §1 says such a store is legal and
> stays whole, and anything beyond that is a later decision with an
> implementation in hand.

> **Normative.** This ADR decides **no bound on the size of a record**, and no
> lane reads §1's count ceiling as one. The unbounded materialisation of a grant
> store's `standing` is **#1551**'s, asked of `SourceGrantStore` and this store
> together; a lane answering it answers it for both.

> **Normative.** This ADR decides nothing about detection (#75), nothing about a
> span's origin within the assistant's own store (#1154), nothing about residency
> (#95), and nothing about the reader-side adversary model.

### 14. What the implementing lane owes

The list below is unmarked and supplies no obligation; the marked clauses in it
are the obligations (ADR-0089 §3).

The implementation is **wave 2** and is sequenced behind the invocation-record
lane, because both write the audit surface. It is a Protocol triad under ADR-0137
§3 — three Protocols, so **three** conformance suites — and lands
`RecipientGrant`, `RecipientGrants`, `RecipientGrantResolution`,
`RecipientGrantStore`, those suites and the canonical fake in
`ai_assistant.testing`, together with `PermissionRuling.authorised_subject` (§6),
`Settings.recipient_grant_max_outstanding` (§1), and the `ActionPolicy` and
`AuditTrail` obligations §6 and §7 state, in one change. **One** fake serves all three faces,
as one fake serves `SourceGrants` and `SourceGrantStore` today: the faces are
narrowings of one store, not three implementations.

> **Normative.** The lane ships a test asserting that an `ActionPolicy`
> constructed with a `RecipientGrants` returns no `ALLOW` on a request whose
> binding carries `planned_with_external_content`, with a live grant covering
> every member of its canonical destination set in place. A test asserting only
> that the grant is consulted does not satisfy this clause.

> **Normative.** The lane ships a test for **each** of §6's refusal grounds
> against `AuditTrail.record`, each asserting `InvalidAuthorisationError` **by
> type** rather than that something was raised: an `authorised_by` the store
> resolves to nothing; one naming a **revoking** record; one naming a grant a
> revoking record already names; one naming a grant whose `expires_at` is at or
> before the decision's `decided_at`; one whose grant's `ToolDefinition` differs;
> one whose grant's `BoundAccount` differs; one whose grant's destination set does
> not contain every member of the decision's; and one whose `egress_binding` is an
> `EgressBinding` carrying `planned_with_external_content` as `True`. It ships one
> for a decision whose `egress_binding` is an `OriginUnrecordedBinding`, refused by
> the same error rather than escaping as an `AttributeError` or passing a field
> test that finds no field; and one for a resolution face that raises
> `RecipientGrantError`, asserting both the refusal and that the
> `RecipientGrantError` is its `__cause__`.

> **Normative.** The lane ships a test pinning §6's **scope**: a non-resolving
> `ALLOW` whose `egress_binding` is `None` and whose `authorised_by` is set is
> recorded, and the resolution face is **not consulted at all** in the course of
> recording it. It fails against an implementation that wrote the invariant as a
> general rule about `authorised_by` — the shape that would make ADR-0021 §6's
> other standing sources a breaking change to `PermissionDecision` rather than an
> added arm here.

> **Normative.** The lane ships the pair that separates §6's two liveness rules,
> which no other test in this section reaches: a grant that expires **after** the
> ruling and **before** `record` runs is still recorded, and a revocation recorded
> before `record`'s resolution read refuses the write. The first fails against an
> implementation that read a clock; the second fails against one that decided
> revocation as of the decision's `decided_at`.

> **Normative.** The lane ships the test that pins §6's stated **linearisation
> point**, and the ADR is falsified rather than the test adjusted if it cannot be
> written: a revocation landing between `record`'s resolution read and its append
> leaves the decision **recorded**, not refused. It is the counterpart of the
> clause above and it asserts the limit rather than the guarantee, so that a later
> lane cannot read §6 as promising atomicity across the two stores. The same test
> is owed for a `clear` and a re-record of the id in that interval (§1's `clear`
> clause).

> **Normative.** The lane ships **detachment** tests for every query on all three
> faces: a caller mutating a returned list, a returned `RecipientGrant` through
> its `__dict__`, or anything mutable those reach, changes nothing a later query
> returns (§1's detached-snapshot clause). A fake that hands back its own objects
> passes every other test in this section, and a grant whose `destinations` or
> `expires_at` could be rewritten in place after a query is a widening of what the
> user authorised.

> **Normative.** The lane ships the **successful handoff** test, which is the one
> that pins the production path end to end and which no other test in this section
> reaches: a policy given a `RecipientGrants` holding a grant covering the request
> returns an `ALLOW` whose `authorised_by` equals **that grant's `id`** and whose
> `authorised_subject` equals **that grant's recomputed `subject_digest`**, and the
> decision built from that ruling is then **recorded** by an `AuditTrail` over the
> matching resolution face without refusal. A policy stamping a fixed well-formed
> digest passes every origin, error and call-count test in this section while
> making every ordinary route-(b) decision unrecordable, and every audit-side
> digest test in this section can be satisfied with hand-built rulings that never
> exercise a policy at all — so the two halves are only joined here.

> **Normative.** The lane ships a test asserting that an `ActionPolicy` whose
> `RecipientGrants.covering` raises `RecipientGrantError` returns **no** `ALLOW`
> on route (b), and does not answer from a cached, earlier or absent result (§1's
> last clause). An implementation that reuses the last successful lookup passes
> every other policy test in this section.

> **Normative.** The lane ships the **call-count** tests for §7's lookup clause,
> against a seam that records its calls and fails the test if called: on every
> path the request alone settles — a binding carrying
> `planned_with_external_content`, and a request with no `egress_binding` —
> `covering` is called **zero** times; and on a path where a grant could apply it
> is called **at most once**, asserted over the recorded count rather than over
> the outcome. `OriginUnrecordedBinding` is **not** among the policy's cases and
> the lane does not write one: `ActionRequest.egress_binding` is
> `EgressBinding | None` and `core/types.py` records that arm as
> "unconstructable from any live path", so a policy test reaching it could only do
> so by forcing a frozen model and would prove nothing about a conforming input.
> Its coverage is owed at `AuditTrail.record`, where a `PermissionDecision`
> legitimately admits the arm, and that test is already required above. Without the zero-call half, an
> implementation that consults the seam first and then refuses on the request's
> own facts passes every other policy test here while letting a store failure
> disturb an outcome the request had already settled.

> **Normative.** The lane ships construction tests for `RecipientGrant`'s
> `destinations`: an empty tuple and one carrying a duplicate are refused at
> construction; a tuple whose members are **not in canonical order** is refused,
> asserted over a **reversed** two-member tuple whose canonical form the same test
> constructs successfully, so the pair fails against an implementation that
> accepted either spelling; a valid one round-trips through
> `model_dump(mode="json")` with its order preserved, and order is preserved on
> read back from the store. The annotation enforces none of them (§1's first
> clause), and every other test in this section can be written with valid
> fixtures.

> **Normative.** The lane ships a test asserting that a grant transcribed from a
> confirmed decision's binding under §2 is in canonical order **without the
> establishing surface sorting anything** — the value comes from
> `EgressBinding.canonical_destination_set` already ordered — and that a surface
> which rebuilt the tuple in another order is refused by the same validator. It
> fails against an implementation that re-canonicalises or re-sorts at the
> surface, which §2's first clause forbids for a different reason and this one
> pins mechanically.

> **Normative.** The lane ships an `export` **completeness** test in the shared
> conformance suite: a store seeded with a live grant, an expired-but-unrevoked
> grant, a revoked grant and the revoking record that revoked it returns **all
> four** from `export`, each exactly once, with no record of any kind omitted or
> repeated. It fails against an implementation that delegates `export` to
> `standing`, which passes every query test in this section while silently
> dropping three of the four (§1's portability clause).

> **Normative.** The lane ships the `subject_digest` tests: two `RecipientGrant`s
> differing **only** in `id` share a digest; two differing in **any other single
> field** — `tool`, `account`, `destinations`, `decided_at`, `expires_at` or
> `established_by` — do not, asserted one field at a time so no exclusion can
> survive unnoticed; a grant round-tripped through `model_dump(mode="json")` and
> reconstructed recomputes an
> **identical** digest, which is the property a stored field would not have had;
> and the digest is absent from `model_dump()` output, because it is a property
> and not a field.

> **Normative.** The lane ships a **roster** test over `RecipientGrant`, in the
> shape `tests/readers/test_calendar_duration_settings.py`'s
> `test_the_roster_is_every_calendar_duration_setting` already uses for a field set
> that must not drift unnoticed: the roster is read off `model_fields` rather than
> hand-written, and the test asserts that the digest's projection is exactly that
> set less `id`. An eighth field added later without deciding its place in the
> digest is then a **red test** rather than a silent exclusion, and an
> implementation that lists the members by hand fails it.

> **Normative.** The lane ships the digest's enforcement tests against
> `AuditTrail.record`, each asserting `InvalidAuthorisationError` by type: a
> route-(b) decision whose `authorised_subject` is **unset**; one whose
> `authorised_subject` is a well-formed digest of a *different* grant; and a
> **resolving** `ALLOW` carrying an `authorised_subject` at all (§6's pairing
> clause). It ships the `PermissionRuling` construction test for the half the type
> can state — an `authorised_subject` set with `authorised_by` unset is refused —
> and a positive test that a route-(a) `ALLOW` with `authorised_by` set and
> `authorised_subject` unset is recorded unchanged.

> **Normative.** The lane ships the test that pins the digest's whole reason for
> existing: a route-(b) decision is recorded; the grant store is `clear`ed; a
> **different** grant is recorded under the **same id**; and resolving that id
> afterwards yields a record whose `subject_digest` does **not** equal the
> decision's `authorised_subject`. It ships the near-miss beside it — a
> re-recorded grant identical in `tool`, `account` and `destinations` but
> established at a different instant also fails the digest — because that is the
> case §6's subject match alone accepts and the case `decided_at` is in the digest
> for.

> **Normative.** The lane ships the count-ceiling tests: `record` refuses a
> granting record that would take the count of **outstanding granting records**
> above `Settings.recipient_grant_max_outstanding`, raising
> `InvalidRecipientGrantError`; it accepts one after a revocation has brought the
> count back under; it refuses on the same ground where the records at the ceiling
> are **expired but unrevoked**, which is the outstanding-not-live substitution
> stated rather than assumed; and it **never** refuses a revoking record on this
> ground, asserted at and above the ceiling.

> **Normative.** The lane ships a **concurrent** test for the count ceiling, and
> it is not the concurrent duplicate test one clause up: with the store one below
> the ceiling, two granting records of **distinct** subjects are recorded at once
> and exactly one succeeds, the store holding exactly the ceiling afterwards. It
> fails against an implementation that counts outside the atomic operation — which
> the duplicate-subject test cannot catch, because those two subjects differ and
> that invariant never fires (§1's atomicity clause).

> **Normative.** The lane ships the `Settings` construction tests for the
> ceiling, over **three** values: `recipient_grant_max_outstanding` refuses a
> negative, accepts one, and **accepts** zero. The negative case is named because
> an implementation special-casing only zero satisfies every other assertion here
> while accepting `-1`, which would refuse every granting write for a reason no
> message explains.

> **Normative.** The lane ships the zero ceiling over a **populated** store, and
> the empty-store case alone does not satisfy this clause: a store holding a live
> grant, reopened at zero, still returns it from `covering` and `standing`, still
> sources a recordable route-(b) `ALLOW`, and refuses every **new** granting
> record. It fails against an implementation that read zero as a kill switch —
> which would be a `Settings` value retracting an authorisation the user gave,
> with no act and nothing in the trail to show it (§1).

> **Normative.** The lane ships the `expires_at` ordering tests: a **granting**
> record whose `expires_at` equals its `decided_at` is refused at construction, one
> whose `expires_at` precedes it is refused, and one an instant after it is
> accepted; a **revoking** record is accepted at any ordering, including an
> `expires_at` transcribed from a grant that has since expired (§9).

> **Normative.** The lane ships the **other end** of the interval against
> `AuditTrail.record`, three cases over one boundary (§6): a decision whose
> `decided_at` is an instant **before** the grant's is refused by
> `InvalidAuthorisationError`; one **equal** to the grant's is recorded; and one
> after it is recorded. The equal case is the one that fails against an
> implementation reaching for a strict comparison on both ends by symmetry, and
> the interval is deliberately closed below and open above.

> **Normative.** The lane ships the test that pins the digest guarantee's
> **direction** (§6): a record differing from the row's grant in any digested
> field yields a mismatch, and a record agreeing in all of them yields equality
> that the test asserts as *consistency* and not as identity — written so that no
> later lane reads the suite as certifying that a matching record **is** the
> authorising act. The comment on that test names the sequence it cannot exclude:
> both stores cleared, both ids reused, one clock instant.

> **Normative.** The lane ships the **lowered-ceiling** test, which is the one no
> other test in this section reaches: a store admitted under a high ceiling and
> reopened against `Settings` carrying a lower one still returns **every** record
> from `standing`, `recent` and `export`, accepts a revocation throughout, refuses
> every new granting record while the outstanding count is at or above the new
> value, and accepts one once revocations have brought the count below it. It
> fails against an implementation that evicts, hides or truncates to make the
> current setting look satisfied — which would be the store telling the user they
> had authorised less than they had (§1's admission-not-eviction clause).

> **Normative.** The lane ships `clear`'s **returned count** in the shared
> conformance suite: `0` on an empty store, and on a mixed store holding live,
> expired, revoked and revoking records the count of **every** record removed, not
> of the live ones. An implementation that erases correctly and returns `0`
> satisfies every other `clear` test in this section (§9).

> **Normative.** The lane ships `established_by`'s construction tests: a granting
> record without it is refused, a revoking record with it is refused, and two
> granting records identical in every other field but established from **two
> different** recorded decisions have **different** `subject_digest`s. The last is
> the round-11 blocker as a test: without the field, two legitimate confirmations
> a coarse clock stamped alike were one fingerprint.

> **Normative.** The lane ships a test asserting that a request whose canonical
> destination set is partly covered draws `CONFIRM` and that the confirmation
> names every member of the set (§8).

> **Normative.** The lane ships a test asserting that a grant whose destination
> set covers the request's, established against a **different** `BoundAccount`,
> covers nothing — and one asserting the same for a grant differing only in the
> account's connection reference (§3's first clause). It ships the same pair
> against `AuditTrail.record`'s refusal, because the policy and the trail are two
> enforcement points and a test of one is not a test of the other.

> **Normative.** The lane ships the same pair for the **declaration**, and it is
> owed for the same reason and reaches a different failure: `covering` returns
> `None` for a request whose `tool` differs from the grant's
> `ToolDefinition` **by value alone** — the same identifier, the same capability,
> one reworded description — and the policy returns no route-(b) `ALLOW` on it. An
> implementation comparing only the declaration's identifier passes every account,
> destination, liveness and precedence test in this section, returns a grant after
> the declaration it was established about has changed, and produces the `ALLOW`
> where §3 requires a `CONFIRM`. Only `AuditTrail.record` would then catch it, and
> it would catch it **after** the ruling — so §1's whole "embedded by value, and a
> declaration edit re-prompts" argument would rest on a comparison no test reached.
> The trail-side half of the pair is owed too, as it is for the account.

> **Normative.** The lane ships tests over **liveness**: a revoked grant covers
> nothing; a grant covers nothing at and after its `expires_at` and covers
> normally before it; a **future-dated** grant — one whose `decided_at` is after
> the instant the query reads — covers nothing and is absent from `standing`,
> which fails against an implementation that bounded liveness only above and
> would otherwise hand the policy a grant `AuditTrail.record` must refuse (§1, §6); and a read concurrent with a revocation returns one answer
> or the other and never a torn one. Every one of them is a test the policy tests
> above pass without.

> **Normative.** The lane ships a test asserting that `RecipientGrantStore.record`
> refuses a duplicate id, refuses a **granting** record duplicating an
> **outstanding** grant's `tool`, `account` and `destinations`, refuses a revocation naming an absent,
> already-revoked or differently-transcribed grant, and does **not** refuse a
> revocation whose `decided_at` predates the grant it revokes (§1).

> **Normative.** The lane ships a **concurrent** test for the duplicate-grant
> refusal: two identical granting records, distinct ids, recorded at once, of
> which exactly one write succeeds. A sequential test passes an implementation
> whose check and insert are two operations, which is the race ADR-0021 §4's
> atomicity argument is about.

> **Normative.** The lane ships a test asserting `covering`'s **precedence**:
> with two live grants covering one request, the greater `decided_at` wins; with
> two sharing a `decided_at`, the lesser `id` wins. A store returning the first
> match it finds passes every other test in this section.

> **Normative.** The lane ships a test driving a **clock that advances on every
> read** against two records sharing an `expires_at`, asserting that one query
> returns both or neither (§9's single-read clause).

> **Normative.** The lane ships a test asserting that `clear` retains nothing:
> an id recorded before it is accepted again after it, and again after a restart
> of the store (§1's `clear` clause). It ships one asserting that a route-(b)
> decision recorded **before** that `clear` still renders and explains itself
> afterwards, with no read of the grant store anywhere in the render path (§9,
> §11) — and one asserting that a **new** decision naming a re-recorded id is
> refused where the re-recorded grant's subject differs from the decision's (§6's
> subject match, which with the digest stands in for round 3's tombstone).

> **Normative.** The lane ships a shared conformance test for
> `RecipientGrantResolution.outstanding`: it returns a granting record the store
> holds and no revoking record names; `None` for an absent id, for a revoking
> record's own id, and for a revoked grant; the **expired but unrevoked** grant
> itself rather than `None`, because expiry is not this member's question (§1,
> §6); and it raises `RecipientGrantError` rather than returning `None` where the
> store cannot be read.

> **Normative.** The lane ships tests asserting that
> `RecipientGrantStore.recent` raises `ValueError` for `limit=0` and for a
> negative `limit`, in the shared conformance suite. The rule exists because
> `LIMIT ?` against SQLite turns `-1` into an unbounded read of a Tier 1 store,
> which is the one failure the bounded read exists to prevent, and no other test
> in this section reaches it.

> **Normative.** The lane ships the **wide positive limit** in the same suite:
> `recent(limit=2**63)` returns every record available and raises nothing. The
> contract admits every strictly positive integer, and a store passing the value
> straight to SQLite raises `OverflowError` on it while passing the zero and
> negative cases above. This is not a new rule: `SourceGrantStore`'s own shared
> suite pins exactly this boundary
> (`tests/permissions/source_grant_contract.py`, `recent(limit=2**63)`), as
> `AuditTrail`'s does, and a third grant-shaped store that omitted it would be the
> one implementation free to have the bug.

> **Normative.** The lane ships a test asserting that `record` refuses an
> identical granting record while the first is **outstanding but expired**, and
> accepts one once the first has been revoked — the two sides of §1's
> outstanding-not-live rule.

> **Normative.** The lane re-attests ADR-0154 §4's condition 3 in the same change
> (§12's fifth clause).

> **Normative.** The lane adds no "always allow" affordance keyed on a tool alone,
> on a host, on a credential or on a connected account (§1's second clause, §2's
> second clause), and no route by which a grant is created from anything but an
> answer to a recorded `CONFIRM` (§2's second clause).

> **Normative.** The lane ships the two **negative** establishment tests for §2's
> third clause, asserting over the **store's contents** that no grant was recorded
> — not over what the surface returned: no grant is established from a
> confirmation whose recorded `egress_binding` carries
> `planned_with_external_content` as `True`, and none from one carrying an
> `OriginUnrecordedBinding`. Nothing else in this section reaches the clause, and
> what it guards is a seeding path rather than a tidiness one: a surface that
> recorded such a grant leaves a live authorisation over recipients an attacker's
> content chose, which every *later* call carrying `False` then spends — with §4's
> bar satisfied on each of them, because the origin fact is about that call and is
> true. §2's third clause and §4's are both needed and neither implies the other,
> and this is the test that says so.

> **Normative.** The lane ships a test asserting that an established grant's
> `tool` equals the confirmed **decision**'s `tool` by value, that its
> `account` and `destinations` equal that decision's binding's `account` and
> derived `canonical_destination_set` by value — not merely equivalent, and not
> re-derived at the establishing surface — and that its `established_by` **equals
> that decision's own `id`** (§2's first clause). The last is asserted by equality
> and not by presence, with a failing case in which the surface writes some other
> id: a surface that copies the three subject values correctly and stamps a fixed
> or invented `established_by` passes every other assertion here, and the field's
> whole purpose is that it names *this* act.

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Unmarked throughout; the classification is a statement about this change, not an
obligation (ADR-0089 §1).

- **ADR-0154 — partially superseded**, §4 item (ii)'s first clause, scoped as §12
  states. A reader acting on that clause would act differently, which is ADR-0070
  §1's test coming out on the supersession side. The record goes on ADR-0154's
  `Status` line, which takes the leading `Partially superseded by ADR-0193
  (<scope>)` token, and in an appended dated note; under ADR-0082 §2 no amendment
  qualifier is written on a line carrying that token.
- **ADR-0148 — neither amended nor superseded.** §3's third clause is written
  with its own condition — "until an ADR establishes standing grants" — and this
  ADR satisfies that condition rather than changing the clause. A reader holding
  ADR-0148 reads the same sentence before and after and reaches a different
  conclusion because a fact about the world changed, which is the clause working
  and not the clause being amended (ADR-0147 §11's precedent, in terms). §3's
  fifth clause is likewise discharged rather than altered: it demanded three
  explicit decisions and §§4–6 make them.
- **ADR-0021 — neither amended nor superseded.** §3's precondition on "the ADR
  that introduces standing grants" is met by §6. §5's floor is satisfied rather
  than relaxed: it forbids an `ALLOW` with `authorised_by` **unset** for a
  non-empty `discloses`, and every route-(b) `ALLOW` sets it. §5's own text
  already names this as "how a standing grant will work". §6's deferral is
  discharged for egress recipients and stays open for standing grants over other
  actions, which §6's scoping clause keeps unnarrowed. **`PermissionDecision`
  gains no field, `ActionPolicy` and `AuditTrail` gain no member, no argument and
  no widened return, and `PermissionRuling` gains exactly one optional field**,
  `authorised_subject: Sha256Hex | None = None` (§6). What is added is that field,
  one invariant inside `record`, one constructor dependency on `AuditTrail`
  implementations, one `Settings` value, and three classes in `core/errors.py` —
  **stacked additions** under ADR-0082 §1, because no sentence of ADR-0021 becomes
  false or wider. §1's transcription rules, §4's write-once, atomicity, detachment
  and resolution invariants, and `authorises`'s conjuncts all hold unchanged, and
  §4 already names `record` as the place an invariant over two records is
  enforced. ADR-0021 §4's shared `AuditTrail` conformance suite gains a factory
  that accepts a resolution seam; that is an addition to a suite, not a change to
  a Protocol.
- **The added field is a stacked addition and not an amendment, tested clause by
  clause.** It is optional with a default, so every `PermissionRuling` valid
  before this ADR is valid after it and constructs identically. It is governed by
  ADR-0021 §3's *own* two rules rather than escaping them: a policy with no
  authorisation source sets neither field, and `PermissionRuling` refuses the
  digest where the pointer is unset. It names no subsystem's type — a `Sha256Hex`
  is a string — so it neither narrows ADR-0021 §6's deferred standing grants for
  other actions nor makes the ADR that opens one a breaking change, which is
  exactly what `authorising_grant: RecipientGrant` would have done and what round
  7's third blocker was raised about. And it adds nothing a policy is "entitled to
  author" that it could not already assert: a policy could always set
  `authorised_by`, and ADR-0021 §3 says so in terms — "it is a pointer this
  contract does not verify". §6 is the first clause in the corpus that *does*
  verify it, and the digest is verified in the same breath, against the same
  record, by the same component.

**Why the injected read seam is not a supersession of ADR-0021 §3's purity
clauses.** Review has raised this at rounds 9, 11 and 15, on two different
groundings, and it has been ruled **rejected**; the grounds are in ADR-0021's and
ADR-0097's own text and are recorded here so it does not have to be re-argued at
every later reading. A reader meeting the question again should read the four
bullets below before treating it as open.

- **The clause carries its own condition.** §3's first bullet is "**`decide` must
  return `authorised_by is None`** from a policy constructed **with no
  authorisation source**. Today that is *every* policy". A policy constructed
  *with* one is the case that sentence contemplates and exempts; ADR-0147 §11's
  precedent names that shape the clause **working** rather than the clause being
  amended, and §15's ADR-0148 bullet applies the same test one ADR over.
- **The same ADR names this mechanism as the intended relief.** §5: the floor "is
  written against the distinction that matters rather than against a proxy for
  it, which is what keeps §6's relief valve reachable **without amending this
  clause**", and "the relief valve is deliberately **not** a policy quietly
  deciding on the user's behalf: it is the standing grant (§6)". An ADR is not
  superseded by the thing its own text says should happen next.
- **The purity framing has a named hazard, and §1 closes it rather than reopening
  it.** "The request is **self-contained**: it carries the definition rather than
  an id, so a policy never consults a registry … a policy that resolved an id
  would be reintroducing the rebinding hazard inside the very subsystem meant to
  close it." `RecipientGrants.covering` takes the whole request and returns a
  record; the face carries no read-by-id member and §1 forbids adding one; the
  member that *does* resolve an id is held by the trail alone. §7's purity clause
  states this as an obligation rather than leaving it to be inferred.
- **The I/O cost is stated as a testability cost, and it is paid rather than
  denied.** §3's rejected alternatives say "**A pure policy is a testable
  policy.** `decide` as a function of its argument is what lets §5's monotonicity
  obligations be checked at all; a policy that performs I/O on every call is one
  whose conformance suite has to mock a store to ask a question about ranking."
  That is a cost sentence inside an argument about injecting an `AuditTrail` — a
  **write** seam — whose conclusion ("the policy does not write to the audit
  trail, and the caller does") is untouched here. The cost is now real: a
  grant-holding policy's monotonicity suite stands up a fake `RecipientGrants`,
  and §14's canonical fake is what it stands up. ADR-0070 §1's test is whether a
  reader acting on ADR-0021 would act differently, and this reader would not —
  they would read the condition, find it no longer holds of a policy given a
  source, and reach the outcome ADR-0021 §5 already describes.
- **ADR-0181 — neither amended nor superseded.** §5's second clause is honoured
  by §4's first, and §5's last clause bound this ADR specifically; §6 is extended
  by no clause here — §2's fifth clause applies it to a second surface without
  changing what it requires.
- **ADR-0186 — a stacked addition, recorded here and nowhere else.** §11 adds one
  rendered fact. No sentence of ADR-0186 §7 or §8 becomes false or over-wide: §7
  enumerates what a surface renders and does not say that enumeration is
  exhaustive of every fact a row may carry, and §8's bars all continue to hold
  over the added fact — §11's second clause states one of them explicitly. Under
  ADR-0082 §1 that is a stacked addition and no record is owed on ADR-0186.
- **ADR-0097 — neither amended nor superseded, and the sentence review keeps
  finding is unmarked supporting text.** §3's *marked* output is that the source
  seam is **two Protocols beside `ActionPolicy`**, in `core/protocols.py`, each
  with its own triad — and this ADR takes that shape exactly: `RecipientGrants`
  is a Protocol **beside** `ActionPolicy`, not a widening of it, and §7's first
  clauses state that `ActionPolicy` gains no method, no argument and no widened
  return. §7 of ADR-0097 — its rule about policies and grant stores that *is*
  marked — says a source grant may never be an action authorisation and no
  `ActionPolicy` may consult either source-grant seam; §13 restates it verbatim
  and this ADR consults neither.
- **The sentence itself, engaged rather than waved at.** ADR-0097 §3's discussion
  of "why not one generalised permission surface" says "`ActionPolicy` is a pure
  function by ratified design, and a grant is a store … A surface that must read
  durable state to answer cannot be that function." Three things about it. It is
  **unmarked**, and ADR-0097's own header note already rules on what that means
  for this ADR: §2's "unmarked supporting text … obligate nothing under ADR-0089
  §3; they read as evidence of the marked clause's meaning and move with it
  rather than being separately superseded". It is a ground for **rejecting a
  merged surface**, and the thing it rejects — one contract answering about
  sources and actions at once — is not what this ADR builds. And its own citation
  is ADR-0021 §3, whose reading is settled two bullets up: the purity clause
  carries its own condition, names the standing grant as the relief valve, and
  states the I/O as a testability cost. ADR-0070 §1's test asks whether a reader
  acting on ADR-0097 would act differently, and this reader would not: they would
  put a second Protocol in `core` beside `ActionPolicy`, ship its triad, and keep
  the source seams out of `decide` — which is what §1, §7, §13 and §14 do.
- **ADR-0016, ADR-0017, ADR-0146, ADR-0098, ADR-0152, ADR-0150,
  ADR-0155, ADR-0184 — untouched.** Each is cited and none has a clause this ADR
  makes false or wider. ADR-0016 §7 in particular defers invocation, exactly-once
  execution, per-call data reach, parameter validation, selection, tool
  enablement, a persistent registry, namespacing and transacted cost — none of
  which is a destination policy, and none of which this ADR touches.

### 16. Marking, review and ratification

Unmarked; a record of route rather than an obligation.

This ADR is marked under ADR-0089: the block-quoted clauses are the whole of what
it obliges. It is contract-surface (§14 lands three Protocols, a shared type and
one optional field on an existing one),
so both required reviews apply under ADR-0015 §1 — adversarial and architecture,
green on one tree — and it is ratified only after that, by the one-line
`Proposed` → `Accepted` flip ADR-0165 exempts.

## Consequences

- **The `CONFIRM` on every send stops being the only steady state.** ADR-0021 §6
  called the current behaviour "the correct default and a poor steady state"; a
  user who sends to the same three people can now say so once, on the record,
  with an end date, and be asked again the moment anything about the call changes
  — the tool's declaration, the recipient set, or the recorded origin of the plan.
- **Two safety systems stay unjoined.** A source grant still cannot authorise a
  send and a recipient grant cannot authorise a read; the two stores hold
  different records, are consulted by different components, and neither Protocol
  is reachable from the other's holder.
- **The audit trail answers #68's question for the first time.** Every `ALLOW`
  now says what authorised it, in §11's three states: a decision about that
  call, a standing authorisation the row names, or the policy's own rules — each
  read off the row, with no store consulted, at render time or at any later read.
  A route-(b) row **names** the grant it rested on and **fingerprints** it, and
  the trail resolved that pointer against the store at its resolution read, to the
  standard ADR-0021 §4 already sets for route (a): *nothing is taken on trust*.
  After the grant store is cleared the row still says which route authorised it
  and still carries the whole binding; what is no longer recoverable is the
  grant's own text (§9).
- **A declaration edit re-prompts.** Because coverage compares the declaration by
  value, shipping a changed `ToolDefinition` invalidates the grants established
  about the old one. That is the accepted cost of not keying a long-lived
  authorisation on a rebindable id, and a lane that finds it painful should
  supersede this clause rather than key the grant on `tool_id`.
- **The confirmation's payload disclosure is lost for granted recipients, and
  two open issues say nothing replaces it.** #1154 and #75 both record that the
  user's confirmation is the only control against a span drawn from the
  assistant's own store or a Tier 0 secret in free text. §5 discloses the loss to
  the user at the moment they consent to it and names the triggers for revisiting;
  it does not close either issue and no lane may say it does.
- **`AuditTrail` implementations gain a read-only dependency and a refusal.**
  The trail becomes an active participant in a second invariant, which means a
  second way for `record` to refuse and a second thing a caller must handle — the
  cost ADR-0021 §4 already accepted for the resolution invariant, taken again for
  the same reason. The dependency is one member wide and cannot append, revoke or
  enumerate, so the trail can validate a grant and can never author one.
- **A route-(b) row can be falsified after the fact, not merely left unread.**
  The row carries the `subject_digest` of the grant it was validated against, so a
  pointer whose id was recycled after a `clear` resolves to a record that fails
  the digest, and the failure is legible to anyone holding the trail's export and
  the grant store's. That is sixty-four characters per route-(b) decision, and the
  guarantee is one-directional and stated as such: a mismatch is conclusive, a
  match is *consistency* rather than proof, because a user who clears both stores
  and reuses both ids can make every digested field agree (§6). What the row no
  longer is is a pointer with nothing on it to contradict a rebinding, which is
  the distinction architecture review blocked on and the one an earlier draft
  answered by forbidding the read instead. Nothing in this system performs the
  check; what this ADR ships is the evidence for it, and a later ADR that wants an
  integrity pass has it without a migration.
- **A policy given a grant seam performs one read per ruling, and its conformance
  suite pays for it.** `decide` stays a function of its argument **and its
  injected seams**, which is the form ADR-0021 §5's monotonicity comparison is
  already written in — "with the grants in the store held equal" is that sentence
  read on this input — so the obligations are checkable exactly as before, against
  a fake `RecipientGrants` standing up in the suite (§14). ADR-0021 §3 named this
  cost when it called a pure policy a testable one, and the bill is that fake. The
  seam is one read-only member taking the whole request and resolving no id, so
  the hazard the purity framing was written against — a policy consulting a
  registry, rebinding an id inside the subsystem meant to close that — stays
  closed (§7, §15).
- **A deployment can be at its ceiling, and the user is told.** With
  `recipient_grant_max_outstanding` reached, the establishing act is refused with
  a visible reason and the recourse named, the call itself is still approvable,
  and nothing is evicted or narrowed to make room. The bound is counted over
  outstanding records rather than live ones, so an expired grant occupies its slot
  until it is revoked — which is the same shape the duplicate rule already has,
  and the price of a write path that reads no clock.
- **A revocation stops a call already ruled on but not yet validated by the
  trail.** The check at `record` moves the boundary from the policy's lookup to
  `record`'s resolution read, so the window §9 states runs from that read to the
  execution rather than from the lookup. It does not run from the *append*: the
  read and the append are two awaits, and this ADR builds no linearisation point
  across the two stores and says why (§1). The cost of the boundary it does move
  is that an honest `ALLOW` overtaken by a revocation becomes unrecordable and the
  call does not happen — the direction that fails closed. Beyond it, this is the
  same prospectivity ADR-0097 §4 delivers for source grants, and a later ADR
  wanting more decides it with an implementation in hand.
- **Revisit if** a mechanism lands that makes a payload's provenance recordable
  (#1154), if egress-side Tier 0 detection lands (#75), if a second egress
  boundary is designated and needs its own answer, or if a per-recipient
  authorisation shape emerges that set membership cannot express.
