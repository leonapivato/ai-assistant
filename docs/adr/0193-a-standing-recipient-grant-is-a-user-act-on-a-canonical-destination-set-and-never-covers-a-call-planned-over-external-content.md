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

Every claim below was checked against `origin/main` at `46c5134b` while writing.

- **The binding is already at the ruling point.** `ActionRequest.egress_binding`
  carries an `EgressBinding` or `None`, and `EgressBinding.canonical_destination_set`
  is a derived property over the spans' occurrences, falling back to the connected
  account under ADR-0148 §2's third clause. So the canonical destination set is a
  fact the policy holds, by value, before it rules.
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
satisfied by construction and is what §6's second clause does with `resolves`.

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

### 1. The store: two Protocols, one record, and no field anywhere

> **Normative.** A standing recipient grant is a durable record, `RecipientGrant`,
> in `ai_assistant.core.types`. It carries: its own `id`; the `ToolDefinition` it
> was established about, **by value**; the `BoundAccount` it was established
> against, by value; the canonical destination set it names, as a non-empty,
> duplicate-free, ordered tuple of `CanonicalDestination`; the instant the user
> decided; the instant it ceases to be live; and, on a revoking record, the `id`
> of the grant it revokes. It carries no other field, and in particular no
> credential value and no payload.

> **Normative.** No standing recipient authorisation exists anywhere else. It is
> not a field on a `ToolDefinition`, on a `PermissionDecision`, on a `Settings`
> value, on a connection record, or on any registry — ADR-0021 §6's "a store, not
> a field", read at this seam. A lane that adds an "always allow" flag to any of
> those has not implemented this ADR.

> **Normative.** The seam is **two** Protocols in `ai_assistant.core.protocols`,
> on ADR-0097 §3's split and for its reason. `RecipientGrants` is the query face
> and can create nothing; `RecipientGrantStore` is the durable face and carries
> the append, the query, the standing and recent reads, the export and the
> wholesale erase. An `ActionPolicy` implementation is given the query face and
> never the store.

> **Normative.** The surface is exactly the following, and a contract that adds a
> member, widens an argument or changes a return is changing this decision rather
> than implementing it. The block is display, not a mark (ADR-0089 §2); the
> clauses below it are the obligations.

```python
class RecipientGrant(BaseModel):                       # core/types.py
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: DurableIdentifier
    tool: ToolDefinition                    # by value, detached (§1)
    account: BoundAccount                   # by value; identity *and* reference
    destinations: tuple[CanonicalDestination, ...]   # non-empty, no duplicates, ordered
    decided_at: UtcInstant
    expires_at: UtcInstant                  # required; no unbounded spelling (§9)
    revokes: DurableIdentifier | None = None


class RecipientGrants(Protocol):                       # core/protocols.py
    async def covering(self, request: ActionRequest) -> RecipientGrant | None: ...


class RecipientGrantStore(Protocol):                   # core/protocols.py
    async def record(self, grant: RecipientGrant) -> str: ...
    async def covering(self, request: ActionRequest) -> RecipientGrant | None: ...
    async def get(self, grant_id: str) -> RecipientGrant | None: ...
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

> **Normative.** `get` answers by id **without** regard to liveness, and it is a
> separate member for that reason: §6's `record` check and §11's rendering both
> need a record a `covering` read would decline to return. It is on the store face
> alone, so no policy holds it.

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

> **Normative.** Every member is cancellable under `core/protocols.py`'s
> cancellation clause (ADR-0060) and observes no caller-owned container
> (ADR-0065), as the neighbouring store Protocols do.

> **Normative.** The store is **append-only**. A grant is never edited, narrowed,
> re-scoped or extended in place; changing what a user has authorised is a
> revocation followed by a new grant, and both records are kept (ADR-0097 §2's
> shape, read one store over).

> **Normative.** Ids and instants are supplied by the caller that records, as
> `PermissionDecision`'s and `SourceGrant`'s are. A store mints no id and reads no
> clock on the write path.

> **Normative.** `record` is **write-once and atomic**, on `AuditTrail.record`'s
> and `SourceGrantStore.record`'s shape and for their reason. Re-recording an id
> already present raises rather than overwriting; the duplicate-id check, the
> revocation invariants and the append are **one** operation, not a read followed
> by a write, so two concurrent writes cannot both observe the store as they found
> it. It stores a detached, validated snapshot, recursively over reachable state,
> and never retains the caller's object.

> **Normative.** A **revoking** record transcribes verbatim every field of the
> grant it revokes except `id`, `decided_at` and `revokes`, and `record` refuses it
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
§3 already says it is and is not — a concrete store still satisfies both
Protocols structurally, and what a policy cannot do is *name* `record`.

### 2. A grant is established only by a user act that names the recipient

> **Normative.** A `RecipientGrant` is created by exactly one thing: an act of the
> user that names the canonical destination set and the tool, taken on a surface
> that shows them what §2's fourth clause requires. Answering a `CONFIRM` about a
> call and, in the same act, asking that the recipients be remembered is such an
> act; a command on the command-line or gateway surface naming the recipients is
> such an act. Which surfaces offer it is not decided here (§13).

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

> **Normative.** A user who **amends** a call while answering a confirmation is
> issuing a new request. No grant, and no answer, carries across the amendment:
> the amended call is bound, ruled and — if the user wants it standing —
> established afresh. No surface offers an establishing act attached to an edit of
> the call it was asked about.

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

### 3. What a grant covers: four comparisons, all over recorded values

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

### 6. ADR-0021 §3's named precondition, discharged: where the records live, and what refuses a fabricated pointer

> **Normative.** The second source of a `PermissionRuling.authorised_by` is a
> `RecipientGrant.id`, and the records live in the `RecipientGrantStore` (§1) —
> local, durable and never written to a remote service, on ADR-0004 §2's residency
> clause as ADR-0021 §4 applies it to the trail.

> **Normative.** An `ALLOW` sourced by route (b) is a **non-resolving** decision:
> its `resolves` is unset and its `authorised_by` is the covering grant's `id`. An
> `ALLOW` sourced by route (a) keeps its existing shape exactly — `resolves` set
> and `authorised_by` equal to it (ADR-0021 §3). The two are therefore told apart
> by whether `resolves` is set, on the records as they already exist, and **no
> field is added to any recorded type to carry the basis.**

> **Normative.** `AuditTrail.record` refuses a **non-resolving** `ALLOW` whose
> `authorised_by` is set unless **all six** hold: a record with that `id` exists
> in the grant store; it is a granting record rather than a revoking one; its
> `ToolDefinition` equals the decision's `tool` by value; its `BoundAccount`
> equals the decision's binding's `account` by value, both facts and not one; its
> canonical destination set contains every member of the decision's; and the
> decision's binding does not carry `planned_with_external_content`. That is
> §3's five comparisons less liveness, which is the one of them that is not a
> fact about two recorded values.

> **Normative.** The refusal is `InvalidAuthorisationError`, a third sibling under
> `AuditError` in `ai_assistant.core.errors`, beside `DuplicateDecisionError` and
> `InvalidResolutionError`. It is its own class for the reason those two are —
> a replayed write, a substituted resolution subject and a fabricated standing
> pointer are three facts an operator must be able to tell apart — and no lane
> widens `InvalidResolutionError`'s stated subject to cover it.

> **Normative.** `record` checks existence, kind and subject match, and **nothing
> else**. It does not evaluate liveness, does not consult a clock, does not
> re-rule, and returns no outcome. ADR-0021 §3's division is unchanged: the policy
> rules, the caller records, the trail validates what it holds both halves of.

> **Normative.** An `ActionPolicy` constructed with no `RecipientGrants` returns
> `authorised_by is None` from `decide`, exactly as ADR-0021 §3 requires today. A
> policy given one may set it, and only to the `id` of a grant it read from that
> seam and found covering under §3.

**This is the analogue of the check ADR-0021 §4 already runs, at the same place
and for the same stated reason.** That section put the resolution invariant in
`record` "because it is the only place both records are in hand", and enumerates
what it compares: "the referenced id is present, its ruling was `CONFIRM`, no
other recorded decision already resolves it, and its `tool`, `parameters_digest`
and `step_id` match the incoming decision's exactly." Route (b)'s pointer needs
the same treatment for the same reason ADR-0021 §3 gives — without it, "a `str`
field naming an authorisation is one a policy could fabricate, which would make
§5's floor satisfiable by writing something in a box" — and, as the Context
records, `record` today applies no check at all to a non-resolving `ALLOW`.

**Existence, kind and subject match, and deliberately not liveness.** Liveness is
a fact about *now* and the decision is a fact about *then*. A revocation recorded
between the ruling and the write would make an honest `ALLOW` unrecordable, and
ADR-0037 §2's order — decide, record, read back, claim — turns an unrecordable
decision into a call that does not happen, so the trail would be silently
retracting decisions on a race rather than recording them. Prospectivity is
already delivered where it belongs: the next `decide` reads the store and sees the
revocation (§9). Subject match is a different thing from liveness and is not a
re-ruling — it compares two recorded values, exactly as the resolving check
compares `tool`, `parameters_digest` and `step_id`.

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
carriage applies unchanged.

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

**What the policy still may not do is unchanged.** It consults no `AuditTrail`,
no `SourceGrants`, no `SourceGrantStore` and no registry; it mints no id and
reads no clock (§9 puts the clock in the store, on ADR-0007 §2's precedent); and
`decide` stays a function of its argument and its injected seams, which is what
keeps ADR-0021 §5's monotonicity obligations checkable.

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
> and no in-place narrowing — and it is **prospective**: it governs every ruling
> made after it and retracts no decision already made. A recorded `ALLOW` stays
> recorded and stays true about the moment it was made (ADR-0186 §8's first
> clause).

> **Normative.** Every grant carries an instant after which it is not live, and
> there is **no unbounded spelling** of it: no null, no sentinel, no "forever".
> The user chooses the instant in the establishing act.

> **Normative.** A grant is live when a revoking record for it does not exist and
> the instant above has not passed. Liveness is evaluated by the store at read
> time, so the store reads the clock and the policy does not (ADR-0021 §3,
> ADR-0007 §2's read-time enforcement).

> **Normative.** An expired or revoked grant is **not deleted** by expiry, by
> revocation, or by any operation but `clear`. It stays in the store and is not
> live, so an `authorised_by` recorded while it was live still names a readable
> record for **as long as the store holds records**.

> **Normative.** The store's records are **Tier 1** (ADR-0004): a canonical
> destination is a recipient of the user's, and the store is durable, ordered and
> rendered to the user. It persists locally only, `export` returns a portable
> snapshot of every record, and `clear` erases the store wholesale and returns the
> count. There is no `delete(id)`.

> **Normative.** `clear` on this store **takes the explanations with it**, and no
> clause of this ADR is read as promising otherwise. A recorded `ALLOW` whose
> `authorised_by` names a grant the user has since erased stays recorded and stays
> true about the moment it was made; §11's basis is still route (b), because
> `resolves` is unset and `authorised_by` is present, and the surface renders it
> as a standing-grant `ALLOW` **whose grant the store no longer holds** — never as
> a route-(a) decision, never as `authorised_by` unset, and never as a defect.

> **Normative.** `record`'s refusal (§6) is evaluated at the moment of the write
> and is a statement about the store as it then stood. No component re-evaluates
> it later, treats a subsequently erased or revoked grant as invalidating a
> recorded decision, or refuses to render such a row.

> **Normative.** No lane makes this store's `clear` conditional on, coordinated
> with, or transactional against the audit trail's. Cross-tier erasure is
> ADR-0007 §4's deferred coordinator and is not decided here; what is decided is
> that each store's own wholesale erase is the user's to perform and that the
> consequence above is disclosed rather than designed around.

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
> the user about *that* call (`resolves` set, `authorised_by` equal to it); a
> standing recipient grant the user established (`resolves` unset,
> `authorised_by` set); or **the policy's own rules, resting on no user decision**
> (`authorised_by` unset). This extends ADR-0186 §7 by one fact and changes none
> of its others; every clause of §7 and §8 holds unchanged over such a row.

> **Normative.** The three states are total over `ALLOW` rows and the third is not
> a residual or an error. ADR-0021 §5's floor bars an auto-granted `ALLOW` only
> for a **non-empty `discloses`**, so a non-disclosing, known-cost action reaching
> `ALLOW` with `authorised_by` unset is conforming and ordinary, and ADR-0186 §1's
> operations return every decision rather than only egress ones. A surface that
> forced such a row into one of the first two would be asserting a user decision
> that was never taken.

> **Normative.** No surface renders the third state as an omission, a blank, a
> failure to record, or anything a reader could mistake for either of the first
> two — ADR-0186 §7's three-origin-state discipline, read on this second
> three-state fact.

> **Normative.** No surface derives liveness from the row. It states that a grant
> was the basis when the ruling was made, never that the grant is current, that it
> still covers anything, or that it has not been revoked — ADR-0186 §8's first
> clause, which names a grant explicitly, read on the fact this section adds.

> **Normative.** No surface renders the basis as an approval control, an
> assurance, a risk signal, or a reason to suppress, reorder or de-emphasise any
> part of ADR-0186 §7. It is a fact about the decision, rendered as data and
> neutralised for its target on render.

**Three states rather than two, and the third is what makes the pair honest.**
An earlier draft of this section rendered "which of ADR-0017 §2's two bases
authorised it" over every `ALLOW`, which architecture review found unsatisfiable
on round 1: neither basis is true of a policy-granted `ALLOW`, and ADR-0186's
listing is not scoped to egress. Scoping the clause to egress rows would have
been the other repair and is the worse one — it leaves a reader of a non-egress
`ALLOW` with no statement at all about what authorised it, when the record
already determines the answer. The discriminator is total because
`authorised_by` and `resolves` are, and §6's second clause is what makes the
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
here asks a surface to fetch them. ADR-0186 §8's bar on deriving liveness from
history is exactly the reason: a surface that rendered the grant would be
rendering a record whose current state it must not assert.

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

> **Normative.** No lane reads this ADR as deciding which surfaces offer the
> establishing act, what the wire carries for it, or how a browser or
> command-line surface lays it out. §2's fourth clause is a content floor on any
> surface that offers it, and the surfaces themselves are ADR-0177's, ADR-0178's
> and ADR-0186's to decide.

> **Normative.** No lane reads this ADR as deciding anything about `SourceGrant`,
> `SourceGrants` or `SourceGrantStore`. ADR-0097 §7 stands verbatim: a source
> grant may never be cited as `PermissionRuling.authorised_by`, and no
> `ActionPolicy` may consult either source-grant seam.

> **Normative.** This ADR decides nothing about detection (#75), nothing about a
> span's origin within the assistant's own store (#1154), nothing about residency
> (#95), and nothing about the reader-side adversary model.

### 14. What the implementing lane owes

The list below is unmarked and supplies no obligation; the marked clauses in it
are the obligations (ADR-0089 §3).

The implementation is **wave 2** and is sequenced behind the invocation-record
lane, because both write the audit surface. It is a Protocol triad under ADR-0137
§3 — two Protocols, so **two** triads — and lands `RecipientGrant`,
`RecipientGrants`, `RecipientGrantStore`, their shared conformance suites and
their canonical fakes in `ai_assistant.testing`, together with the
`ActionPolicy` and `AuditTrail` obligations §6 and §7 state, in one change.

> **Normative.** The lane ships a test asserting that an `ActionPolicy`
> constructed with a `RecipientGrants` returns no `ALLOW` on a request whose
> binding carries `planned_with_external_content`, with a live grant covering
> every member of its canonical destination set in place. A test asserting only
> that the grant is consulted does not satisfy this clause.

> **Normative.** The lane ships a test asserting that `AuditTrail.record` refuses
> a non-resolving `ALLOW` whose `authorised_by` names no grant, and one asserting
> that it refuses a non-resolving `ALLOW` whose named grant's destination set does
> not contain every member of the decision's.

> **Normative.** The lane ships a test asserting that a request whose canonical
> destination set is partly covered draws `CONFIRM` and that the confirmation
> names every member of the set (§8).

> **Normative.** The lane ships a test asserting that a grant whose destination
> set covers the request's, established against a **different** `BoundAccount`,
> covers nothing — and one asserting the same for a grant differing only in the
> account's connection reference (§3's first clause). It ships the same pair
> against `AuditTrail.record`'s refusal (§6's third clause), because the policy
> and the trail are two enforcement points and a test of one is not a test of the
> other.

> **Normative.** The lane ships tests over **liveness**: a revoked grant covers
> nothing; a grant covers nothing at and after its `expires_at` and covers
> normally before it; and a read concurrent with a revocation returns one answer
> or the other and never a torn one. Every one of them is a test the policy tests
> above pass without.

> **Normative.** The lane ships a test asserting that `RecipientGrantStore.record`
> refuses a duplicate id, refuses a revocation naming an absent, already-revoked or
> differently-transcribed grant, and does **not** refuse a revocation whose
> `decided_at` predates the grant it revokes (§1).

> **Normative.** The lane re-attests ADR-0154 §4's condition 3 in the same change
> (§12's fifth clause).

> **Normative.** The lane adds no "always allow" affordance keyed on a tool alone,
> on a host, on a credential or on a connected account (§1's second clause, §2's
> second clause).

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
  actions (§4's third clause).
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
- **ADR-0097, ADR-0016, ADR-0017, ADR-0146, ADR-0098, ADR-0152, ADR-0150,
  ADR-0155, ADR-0184 — untouched.** Each is cited and none has a clause this ADR
  makes false or wider. ADR-0016 §7 in particular defers invocation, exactly-once
  execution, per-call data reach, parameter validation, selection, tool
  enablement, a persistent registry, namespacing and transacted cost — none of
  which is a destination policy, and none of which this ADR touches.

### 16. Marking, review and ratification

Unmarked; a record of route rather than an obligation.

This ADR is marked under ADR-0089: the block-quoted clauses are the whole of what
it obliges. It is contract-surface (§14 lands two Protocols and a shared type),
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
  now says which of ADR-0017 §2's two bases authorised it, without a new field,
  and every route-(b) pointer resolves to a record `record` refused to write
  without.
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
- **`AuditTrail` implementations gain a dependency and a refusal.** The trail
  becomes an active participant in a second invariant, which means a second way
  for `record` to refuse and a second thing a caller must handle — the cost
  ADR-0021 §4 already accepted for the resolution invariant, taken again for the
  same reason.
- **Revisit if** a mechanism lands that makes a payload's provenance recordable
  (#1154), if egress-side Tier 0 detection lands (#75), if a second egress
  boundary is designated and needs its own answer, or if a per-recipient
  authorisation shape emerges that set membership cannot express.
