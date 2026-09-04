# 233. The approver is shown the bytes that would leave, and that is the whole of what makes a model-composed span approvable

- Status: Proposed
- Date: 2026-09-04
- **Partially supersedes** [ADR-0155](0155-residency-governs-the-assistants-own-store-and-that-store-is-never-externalised.md)
  — **§3's third clause, to the extent §9 below states, and nothing else in ADR-0155.**
  That clause forbids an egress span carrying covered content all of whose covered
  paths contain a model call; reserves to an owner ruling the choice between **(a)**
  ratifying it as permanent and **(b)** commissioning a later ADR designing a
  content-bearing approval surface; and closes *"An owner ruling alone does not relax
  this clause; relaxation requires the commissioned ADR and its approval surface,
  ratified, and **until then every lane implements the prohibition as written**."* The
  owner ruled arm **(b)** on 2026-09-04 and this is the ADR that arm commissions.
  **Two of the clause's sentences move, and the instrument is supersession rather than
  amendment because a reader acts differently on both** (ADR-0070 §1, whose line is the
  decision and not the size of the edit). The closing sentence's "until then" stops
  running. And the **prohibition sentence itself** acquires the exception §9 below
  states: a call meeting all four of §9's conditions may carry content of that class, so
  a reader holding only ADR-0155 would read "may not carry" more widely than it now
  holds. ADR-0082 §1's test is met on those two sentences and on nothing else in
  ADR-0155.
  **The clause's own reservation is not a licence to record this as a discharge.** §3
  reserves the *route* — under arm (b) "a relaxation **could then be considered**" —
  and says relaxation "requires the commissioned ADR and its approval surface,
  ratified". Stating a posture an earlier ADR obliges leaves that ADR's sentences true
  (§14 classifies ADR-0199 §3 that way); **effecting** a relaxation does not, and this
  ADR effects one. The distinction is drawn here rather than left for a reader to make.
  **What the supersession does not reach is nearly all of §3, and every other ruling of
  §3 is untouched and load-bearing here.** §3's first clause — the definition of
  covered content, its
  propagation through every operation without exception, and its three-valued
  per-supply character — is the class this whole decision is stated over and is
  quoted in §3 below. §3's **second** clause, the absolute prohibition on a span
  carrying covered content some covered path of which contains no model call, is
  **not relaxed by one word**: §6 below refuses it earlier and harder than ADR-0155
  could, and §7 argues at length why the surface is not a route around it. §3's
  fourth clause — no authorisation cures either prohibition — binds entire, and §9
  is stated so as not to breach it. §3's fifth and sixth clauses reserve the export
  ADR, and this ADR is not it and is not read as it. §4's marked clause (nothing
  states that §3 is enforced mechanically) is discharged in part and *only* in part
  by §6 below, which says exactly how far.
- **Partially supersedes** [ADR-0184](0184-a-decision-recorded-before-the-origin-field-is-legible-history-and-the-absence-is-its-own-value.md)
  — **§1's exception roster, three sentences of §2, §3's discrimination sentence and
  §9's first clause; those, and no others.** The instrument is supersession for the
  reason it is on ADR-0155: each of these sentences is one a lane **acts on
  differently** once this ADR stands, which is ADR-0070 §1's line. That is also how the
  corpus has recorded every widening of a roster clause — ADR-0181 partially superseded
  ADR-0178 §2's exactly-two-fields clause and ADR-0152 §7's exactly-one-thing clause,
  and ADR-0184 itself partially superseded ADR-0150 §1's clause typing
  `PermissionDecision.egress_binding` — so the label follows the test rather than the
  size of the edit (ADR-0082 §1: "the test controls, not the label").
  §9 deferred a stored payload version and named its firing condition — "the next member added required-with-no-default to a
  model the trail stores" — obliging "the ADR adding that member" to choose "between a
  second sibling and a version, in its own text". §4 below is that member and §14 makes
  that choice: **a second sibling**, because a version key names a schema and supplies
  no representable value for a row lacking a required field. Adding a member to
  `EgressBinding` and a third shape to the union moves five sentences, each named here
  because ADR-0082 §1 puts the naming in this ADR's text, and each stated in its
  repaired form in §14:
  **§1** recognises a row by its carrying "every member `EgressBinding` requires
  **except** `planned_with_external_content`" — an exception list that must now carry
  two names, since a genuine pre-origin row lacks `coverage` as well, and which read
  unrepaired would make the first epoch's own rows unrecognisable.
  **§2's first clause** describes `OriginUnrecordedBinding` as carrying "every member
  `EgressBinding` carries **but** `planned_with_external_content`", for the same reason.
  **§2's third clause** states that "`EgressBinding` is unchanged … no member is added
  to it"; §4 below adds `coverage`, which is that sentence and not a reading of it.
  **§2's fifth clause** types `PermissionDecision.egress_binding` as
  `EgressBinding | OriginUnrecordedBinding | None`; §14 makes it a three-shape union.
  **§3's** clause that "a stored object carrying `planned_with_external_content`
  validates as `EgressBinding` **and as nothing else**" stops being true: such an object
  lacking `coverage` validates as `CoverageUnrecordedBinding`. §3's *property* —
  structural, total and mutually exclusive, with no discriminator field — is preserved
  exactly and is why the ladder works; it is the two-shape **sentence** that is replaced
  by a three-rung one, and §14 states it.
  **§9's first clause** ("No lane adds a second sibling to this union") is the clause
  §9's second clause licenses this ADR to spend.
  **Everything else stands and is relied on**: §2's declare-each-member-once rule is
  obeyed by a private base chain, §2's fourth clause keeps
  `ActionRequest.egress_binding` narrow and §14 does not widen it, §2's sixth clause is
  scoped "**by this ADR**" and so is a statement about ADR-0184's own reach rather than
  a standing prohibition on later ones — §4's `SpanCoverage` and its
  `ConfirmationEgress` member breach nothing there — §4's
  nothing-is-written rule and §5's five readers bind unchanged, and §7's floor is
  extended **by cause** for §7's own reason. §11 is untouched, and its own partial
  supersession of ADR-0150 §1 is why no second pair is owed there (§14).
- **Also partially supersedes [ADR-0152](0152-the-binding-is-derived-at-one-seam-never-supplied-to-it-and-a-call-it-cannot-describe-is-refused.md)
  and [ADR-0178](0178-a-confirmation-carries-the-egress-it-is-about-and-its-absence-is-the-discriminator.md),
  each on a clause ADR-0181 already partially superseded and this ADR narrows again by
  one**, by the same test and the same precedent. ADR-0152 §7's clause on what `rebind` takes from `approved` went from one thing
  to two; §4 below makes it three. ADR-0178 §2's clause fixing `ConfirmationEgress`'s
  fields went from two to three; §4 below makes it four, and §10's `model_fields` roster
  test moves by one further entry with it. Both pairs accumulate on a `Status` line that
  already carries the leading token, which is ADR-0070 §4's accumulation rule and
  ADR-0082 §2's placement rule; §14 states the extent of each.
- **No record is owed on ADR-0148, ADR-0150, ADR-0181, ADR-0193, ADR-0199,
  ADR-0203, ADR-0207, ADR-0146 or ADR-0106**, and §14 applies ADR-0082 §1's
  test to each rather than asserting it. In particular: ADR-0148 §6's determinism
  clause is **not** amended, because §4 below puts the new fact on the **binding** and
  not in the description, exactly as ADR-0181 §3 did and for the same reason; and
  ADR-0150 §10's per-span enumeration is **not** amended, because the description gains
  nothing. "It holds no content" is kept rather than superseded, and §2 below is the
  whole argument for how a content-bearing surface is compatible with it.

## Context

### The fork, and the ruling that opened it

ADR-0155 §3 partitions covered content — everything this system's stores touch, and
everything any operation supplied with it produces — into two prohibitions on an
egress span. Its **second** clause is absolute: a span may not carry covered content
where *some* covered path of it contains no model call. Its **third** clause is the
one this ADR exists for. It is a marked clause in that document; the mark is dropped
in this quotation so that quoting it is not making one (ADR-0089 §2):

> An egress span may not carry covered content **all of whose covered
> paths contain a model call** — wherever on a path that model call sits, upstream or
> downstream of any other operation. What is reserved to an owner ruling is whether to
> **(a)** ratify this clause as permanent, or **(b)** commission a later ADR that
> designs a content-bearing approval surface compatible with ADR-0150 §10 and states
> its privacy consequences, under which a relaxation could then be considered. **An
> owner ruling alone does not relax this clause; relaxation requires the commissioned
> ADR and its approval surface, ratified, and until then every lane implements the
> prohibition as written.** No lane, reviewer or later ADR makes that choice without an
> owner ruling, and this clause is deliberately the more restrictive reading.

The owner ruled **(b)** on 2026-09-04, on #1996, in these words:

> **Fork (b) is opened now, in parallel.** A separate ADR lane designs the
> **content-bearing approval surface** ADR-0155 §3(b) names — the user sees the
> literal content about to leave (an email body, a search query) on the channel they
> are on and confirms against it — compatible with ADR-0150 §10, with its privacy
> consequences stated. Its first customers are memory-drawn email (the interim's "a
> recall-then-send turn cannot draft egress arguments", which the owner called a
> large limitation) and memory-enriched search. It does not block milestone 29; a
> follow-on lane widens search once it is ratified and implemented.

The first customer is stated by ADR-0155's own Consequences and is what the interim
costs:

> **A recall-then-send turn cannot draft egress arguments under the interim**: once
> recalled records are supplied to the planner's model call, its output is covered
> content all of whose covered paths run through that call, and §3's third clause
> forbids it reaching a span. A QA send therefore composes from turn content only.

This ADR sits on `track:world`'s seam by subject — `tools/egress*`, `permissions/`
and the confirmation surfaces are that track's ground. It is dispatched from #1996
for sequencing only, because the owner's ruling that opened the fork was made on that
batch's thread; nothing here decides a milestone-29 question and nothing here is
cited toward one.

### What the approver is shown today, read rather than assumed

Read at `origin/main` = `e66caa85`. This subsection is an account of the tree and is
**not normative** (ADR-0089 §1).

**The description holds no content, and that half of ADR-0155 §3's premise is exact.**
`EgressSpan` (`ai_assistant.core.types`) carries `argument`, `index`, `provenance`,
`extent`, `tier` and `destination`. `EgressBindingSeam._spans_of` in
`ai_assistant.tools.egress_binder` builds every span from the argument's decomposed
value and keeps **one** number from it — `_extent` — discarding the value. The two
surfaces render exactly that: `_egress_span_line` in `interfaces/cli.py` and
`spanWords` in `interfaces/gateway/assets/app.js`, whose own comment reads *"A
description, never the payload."*

**But the `Confirmation` already carries the content, and both surfaces already
render it.** `Confirmation.parameters` is `FrozenJsonMapping`, described in the tree
as *"The arguments the tool would run with, as structured data."* `renderParameters`
in `app.js` prints `It would run with these arguments, as the assistant wrote them:`
and then one line per key of the form `${one.key} = ${one.value}`;
`_render_confirmation` in `cli.py` prints `With:` and then `key = value` for each,
each through `_safe()`. ADR-0178 §7's first clause takes this as read — it says a
surface that renders "the tool, the parameters and the reason **and stops**" has not
put ADR-0148 §8's question, which is a statement that rendering them is not
*sufficient*, not that it is forbidden.

**And the record already binds those exact bytes.** `ActionRequest.parameters_digest`
is `sha256` over ADR-0021 §1's canonical encoding of `parameters`;
`PermissionDecision.parameters_digest` is *"Binds the payload without storing it"*;
`PermissionDecision.authorises` compares `request.parameters_digest ==
self.parameters_digest` alongside the tool, the step, the execution and the whole
binding; and `AuditTrail._check_resolution` refuses a resolution whose
`parameters_digest` differs from the decision it resolves, with the message *"a
confirmation must answer the question that was asked"*.

**What no component does is read where an argument's text came from.**
`DiscloserProvenance` has two members, `USER_AUTHORED` and `SYSTEM_SELECTED`, and
neither is "obtained from this system's own store". `StepRunner._bound` in
`orchestration/runner.py` still passes `CarriedProvenance(spans={}, …)`, so every
span the seam describes today is `SYSTEM_SELECTED` regardless of who wrote it.
(ADR-0154, ADR-0155 and ADR-0181 each call that method `AttemptRunner._bound`. No
such class exists or ever has — the class has been `StepRunner` since the commit
that introduced it, `95ffaac3`. This ADR names what is in the tree; correcting the
three standing texts is #2036, and nothing decided on top of the old name is
affected, because the site it points at is the right one.) And
the one content-shaped check after the ruling is by length:
`SmtpEgressTransport._check_spans_cover` compares a **multiset of code-point counts**
against the description's extents, which the neighbouring docstring in
`tools/egress.py` already concedes — *"two texts of equal length are
indistinguishable to such a check, so a message substituted after the ruling — same
lengths, different words — passed every one of them."*

**Two facts ADR-0155 §4 states about the tree have since stopped holding, and
neither is a normative clause.** §4 wrote that "No tool is registered at the seam:
`build_default_registry` … returns `CURRENT_TIME` and `RECALL_MEMORY` and nothing
else". Both halves have moved: `build_send_email_integration` registers `send_email`
in `tools/builtin.py` and is wired in `app/composition.py`, and `recall_memory` was
removed by ADR-0208 §1. #1154's own comment of 2026-09-02 records the first and
states that its trigger — "the first lane that registers an integration whose
declared arguments admit free text" — has **fired**. That is why the mechanism §4
declined to specify is specified here rather than deferred again.

### The half of ADR-0155 §3's premise that does not hold, and what it changes

ADR-0155 §3's prose gives the reason arm (b) had to commission a *mechanism* rather
than offer a relaxation:

> Architecture review found on round 17 that the premise contradicts the corpus:
> ADR-0150 §10 makes the payload description hold no content, so the confirmation
> carries spans, extents, provenance and destinations and never the body. An owner
> cannot recognise their own memory in a body they are not shown …

The first clause of that sentence is exact and stays exact. The second — "the
confirmation … never the body" — is **false of `Confirmation`** and was true only of
`ConfirmationEgress`. `Confirmation.parameters` is the body, and has been since
ADR-0042 §4. The mistake is a natural one: ADR-0150 §10 is stated over the
*description*, ADR-0148 §8's fourth clause names the description as what a
confirmation must carry, and it is easy to read the conjunction as a bound on the
whole carrier. It is not one.

This is worth stating precisely because it changes the size of the decision and not
its direction. **Nothing about the prohibition moves**: §3's third clause is stated
over what may be *in a span*, and §3's fourth clause says no authorisation cures it,
so a surface that showed the body would still not have made the send lawful. What
changes is that the mechanism arm (b) commissions does not need a new artifact, a new
carriage or a supersession of "it holds no content". It needs three things the tree
does not have: an **obligation** that the content be shown span by span before the
answer is collected; a **recorded fact** about the call saying which of §3's two
clauses governs what it would carry, without which nothing can tell an approvable
call from an absolutely forbidden one; and a **statement of the conditions** under
which the third clause's prohibition lifts.

### What this ADR is not allowed to settle

- **ADR-0155 §3's second clause.** No owner ruling opened a fork on it; it has none.
  Its only stated exception is the export ADR §3's fifth clause reserves, and §3's
  sixth clause forbids reading any document — this one included — as being it.
- **Whether a description should carry a record identifier.** ADR-0150 §10's second
  clause says no, and #57's granularity question is left exactly where ADR-0148 §13,
  ADR-0150 §11 and ADR-0155 §7 leave it.
- **ADR-0150 §6's tier residue.** A neighbouring absence with the same shape, and
  §12 below states in a marked clause that this ADR discharges no part of it.
- **Egress-side Tier 0 detection (#75).** The owner's reading recorded on that issue
  is that user-authored content is authorised as submitted and the question is a
  product one rather than a compliance gap; the 2026-09-02 census closed it as "not a
  defect". §12 defers it by name and this surface claims no detection of any kind.
- **The frame-limit compaction (#1379).** Its firing condition is a measurement, and
  §12 records what this ADR does and does not add to the arithmetic.
- **Whether any particular integration may be registered, and against what.**
  ADR-0154 §7 leaves that to the registration lane and this ADR adds nothing.

## Decision

### 1. The fork is answered, this ADR is what arm (b) commissions, and it relaxes nothing on its own

> **Normative.** This ADR is the ADR ADR-0155 §3's third clause reserves under arm
> **(b)**, taken on the owner's ruling of 2026-09-04 recorded on #1996. It designs
> the content-bearing approval surface that clause names, states its privacy
> consequences in §11, and states in §9 the conditions under which §3's third clause
> ceases to forbid a span. It is not the export ADR §3's fifth clause reserves, is
> not cited toward one, and decides nothing about ADR-0155 §1 or §2.

> **Normative.** Ratifying this ADR relaxes nothing for any call. §9's condition is a
> property of a **call** and not of a date, a tree state or a merged PR: a call whose
> binding does not carry §4's `coverage`, or whose confirmation did not put §8's
> question, does not meet it, and §3's third clause forbids that call exactly as
> written. Until the surface §5 to §8 describe exists in code, no call can meet the
> condition, so nothing is relaxed by this document alone and no lane reads it as a
> permission.

> **Normative.** No lane cites this ADR toward a designation, a registration, a
> destination, a `DestinationProtocol` member, a standing authorisation or a
> dependency. ADR-0154 §2's single route and §4's standing-authorisation floor are
> untouched and unlifted.

**Stating the effectiveness as a property of the call is the substance, not a
formality.** The alternative — "this relaxation takes effect when the implementing
lane merges, recorded by a note on ADR-0155 that the implementation PR carries" —
was considered and refused for two reasons. It puts a change to a ratified document
in a PR no reviewer reads as an ADR change, which is the instrument ADR-0082 §2 does
not offer; and it makes the question "has the mechanism landed yet?" a matter of
judgement, which is exactly the kind of question ADR-0155 §3 spent twelve rounds
learning not to leave open. Stated over the call, it is self-enforcing: a request
whose binding carries no coverage cannot be built at all once §4's field exists, and
cannot exist at all before it does. The ADR-0082 §1 record on ADR-0155 is therefore
made **here**, by this change, because it is this document that makes §3's closing
sentence over-wide.

### 2. No second artifact is minted, because the content is already carried once

> **Normative.** The content the approver reads is `Confirmation.parameters` — the
> arguments the request already carries, which ADR-0150 §4 makes the spans themselves.
> No lane mints a content-bearing projection of the binding, adds a content member to
> `EgressBinding`, `ConfirmationEgress` or `PermissionDecision`, or derives a second
> renderable artifact beside the description.

> **Normative.** The payload description continues to **hold no content**, and
> ADR-0150 §10's second clause is kept in that respect entire. `EgressSpan.extent`
> stays the number of Unicode code points ADR-0150 §4 defines and is never widened to
> carry, prefix, excerpt or digest the value it counts.

> **Normative.** Showing `parameters` beside the description is not showing "a value
> derived beside the binding rather than the binding's own" in ADR-0150 §10's fourth
> clause's sense, and no lane reads it as one. The relation runs the other way: the
> description is derived **from** `parameters`, and `ActionRequest` already refuses
> any binding whose spans do not decompose that same mapping under ADR-0150 §4 — every
> span's `argument` a top-level key of `parameters`, every array's indices exactly
> `0` through `n-1`, and every span's `extent` **recomputed from `parameters`** rather
> than taken as supplied. The two cannot come apart, and the recomputation is the join.

**This is the whole reason the surface costs no new shape.** ADR-0150's title is
against *state stated twice*, and its §10 refuses a projection because "two artifacts
that must agree, one bound and one shown, is the defect PR #1120's first three rounds
found". A content-bearing projection would be exactly that defect arriving at the one
field whose purpose is to be believed. What this ADR shows instead is not a second
artifact at all: it is the request's own arguments, which the description is a
function of and which `ActionRequest`'s validator ties to the description span by span
and code point by code point. There is nothing for a second shape to disagree with.

**And the corpus has already justified carrying the two together, once.**
`BoundEgressCall` in `core/types.py` carries `binding`, `tool` and `parameters` as one
value at the seam, for the reason ADR-0148 §6's callable-side clause needs both: you
cannot check that a description covers a payload without the payload. This section is
that same pairing arriving at the surface, and the surface is the one place where
having both is the point rather than a means.

**What ADR-0148 §8's fourth clause names is unchanged and is not enough on its own.**
That clause fixes what is *put to the user* — the account identity, the canonical
destination set in both forms, and the payload description — and ADR-0155 §3's prose
reads the resulting question as *"send this many characters, from these arguments, to
these recipients"*. That reading is right about the description and wrong about the
carrier, and §5 below is what makes the fuller question owed rather than merely
possible.

### 3. The class this decision is stated over is ADR-0155 §3's, unchanged

> **Normative.** "Covered content", "covered path" and their three-valued
> per-supply-site character are ADR-0155 §3's first clause and are neither restated,
> narrowed nor widened here. This ADR adds no second definition, no second decision
> procedure and no test of its own, and every clause below that says "covered" means
> what that clause means.

> **Normative.** Nothing here is decided by inspecting a span's content, its field,
> its shape, its resemblance to a stored value, or by matching it against anything the
> user wrote. That is ADR-0098 §5's unrecoverable relation and ADR-0146 §2's forbidden
> inference, and this ADR obtains no bound from either.

ADR-0155 §3's own words, quoted so that §4's field has a stated subject rather than a
remembered one:

> A **covered path** of a piece of covered content is a path by which it derives from
> such a store: the value itself, where a component obtained it from the store; and
> otherwise, for an operation's output, each path continuing back through each covered
> input that operation was supplied. Content may have several covered paths, and they
> need not be alike. Membership and the character of each path are decided at each
> supply site from recorded origin — a component that knows its inputs' membership
> knows their paths' character, which is three-valued at every supply: covered with a
> model call on the path, covered with none, or not covered …

### 4. The `core` surface: one three-valued fact about the call, on the binding

> **Normative.** `core/types.py` gains `SpanCoverage`, a `StrEnum` with **exactly
> three** members, one per state ADR-0155 §3's first clause names: `NOT_COVERED` — no
> covered path, so nothing the call would carry is covered content at all;
> `MODEL_ON_EVERY_PATH` — covered, and every covered path of everything the call would
> carry contains a model call, which is ADR-0155 §3's third clause's subject; and
> `PATH_WITHOUT_MODEL` — covered, and at least one covered path of something the call
> would carry contains no model call, which is §3's second clause's subject. No lane
> adds a fourth member, an "unknown" member or a `None`-valued absence.

> **Normative.** `EgressBinding` gains `coverage: SpanCoverage`, **required with no
> default**: the state ADR-0155 §3's first clause gives, over **every** span the call
> would transmit, to the material the components composing this request's arguments
> supplied to the operations that produced them.

> **Normative.** Where the spans differ, the binding carries the **strongest** of their
> states under the total order `NOT_COVERED` < `MODEL_ON_EVERY_PATH` <
> `PATH_WITHOUT_MODEL`. That order is not this ADR's invention: it is ADR-0155 §3's own
> ruling that "The overlap falls to the absolute clause", because "one non-model path
> suffices to keep content under the absolute clause **forever**". A call is therefore
> governed by the most restrictive clause any part of it reaches, which is strictly
> conservative and is the direction §3 already chose.

> **Normative.** `CarriedProvenance` gains `coverage: SpanCoverage`, **required with no
> default**, and `CarriedProvenance.spans` is **untouched** — its key type, its value
> type `DiscloserProvenance`, its detachment validator and its serializer all stand.
> The seam writes the binding's value from the carrier's, unchanged, exactly as
> ADR-0181 §3 makes it write `planned_with_external_content`.

> **Normative.** `coverage` is **not** discloser provenance, is not a tier, and is not
> `planned_with_external_content`. `EgressSpan` gains **no** field, so ADR-0150 §5's
> "the marker **is** the `provenance` field of `EgressSpan`" and its no-second-carriage
> rule are untouched at the field they govern, ADR-0150 §10's per-span enumeration is
> unchanged, and ADR-0148 §6's three determinism inputs stay three — the description is
> not a function of this fact, because this fact is not in the description. No lane
> reads one of the three axes off another, at any site.

> **Normative.** `PermissionDecision.authorises` compares `coverage` with the rest of
> the binding as one whole. No lane compares it separately, exempts it from the
> comparison, or re-derives it after the ruling. `EgressBinder.rebind` takes it from
> `approved`, matched to the binding it re-derived, exactly as ADR-0152 §7 and ADR-0181
> §3 make it take a span's `provenance` and the binding's origin, and for the identical
> reason: the fact is about a composition made before the confirmation was parked,
> plausibly before a restart, and `rebind` receives nothing to recompute it from. This
> narrows ADR-0152 §7's count from two to three and narrows nothing else there.

> **Normative.** `ConfirmationEgress` gains `coverage: SpanCoverage`, **required with
> no default**, populated from the recorded decision's `egress_binding` at both
> assembly sites and by no other route (ADR-0178 §5). It is a transcription and not a
> second carriage (ADR-0150 §1), it mints no type, and it is not a
> `ConfirmationDestination`.

> **Normative.** No field is added to `EgressSpan`, `Provenance`, `MemoryBase`,
> `ContextFacet`, `ToolDefinition`, `ToolCall`, `Confirmation`,
> `ConfirmationDestination`, `PermissionDecision`, `PermissionRuling`,
> `EgressDestination`, `BoundAccount` or `CanonicalDestination` by this ADR, and no
> `DataTier`, `DiscloserProvenance`, `DestinationProtocol` or `PermissionOutcome`
> member is added, removed or re-described.

**Three members rather than a boolean, because the two prohibitions are different
prohibitions.** A boolean "is this covered" cannot tell the absolutely forbidden case
from the approvable one, and a boolean "is this approvable" would put the partition's
own reasoning inside a field name where no reviewer can check it against ADR-0155 §3.
The members are named for the quantifier each clause carries — *every* path versus
*some* path — because the quantifiers are what ADR-0155 §3 says make the partition
exhaustive, and a name that dropped them would be the first thing to drift.

**On the binding rather than on the span, and an earlier draft of this ADR had it the
other way.** Per-span is the more informative shape and it is not the one the corpus
can carry. Three things decide it. ADR-0181 §2's third clause **refuses to mint** a
per-span externality marker and ADR-0181 §6's fifth clause forbids a surface
presenting a call-level fact as a span-level claim, so a per-span origin axis arriving
beside it would invite exactly the conflation those clauses exist to prevent. ADR-0150
§10's second clause enumerates what a description states per span and ADR-0148 §6
fixes the description's inputs at three, so a per-span field costs two amendments to
ratified contract clauses — and buys, on top of §8's floor, only a label beside bytes
the user is already reading whole. And ADR-0150 §6's residue reserves the per-span
*classification* mechanism to the ADR that closes the **tier** axis; taking that shape
here for a different axis would half-build it. The binding is where ADR-0181 §3 put
the neighbouring fact, for the reason it gave — "a call-level fact on a span would look
like a span-level claim" — and this fact is a call-level fact in exactly the same
sense: the two prohibitions ADR-0155 §3 states are about what an egress call may carry,
and a call carrying one forbidden span is a forbidden call.

**What the coarser fact costs, stated rather than glossed.** A user reading a
confirmation learns that *something* in this call was composed by a model that had been
shown things they told this system, and not *which* argument. That is a real loss
against the per-span shape, and it is bounded by the thing this ADR is actually for:
the user is reading the bytes, all of them, before they answer. The label is context
for a reading, not a substitute for one.

**No default, and the argument is ADR-0181 §3's, quoted rather than re-derived.**
"A defaulted field is what a lane forgets: an implementation that never wires
provenance through would get `SYSTEM_SELECTED` for free, its payloads would look
correct." Here the safe-looking default is `NOT_COVERED`, which asserts that nothing
in the call came from anywhere near this system's stores — a claim about a supply the
defaulting lane never made, and the exact claim §3's whole partition exists to stop
anyone making by accident.

**And a component with no recorded origin answers `PATH_WITHOUT_MODEL`.** ADR-0146
§2's fail-closed rule is the precedent — a span for which no origin was recorded is
`SYSTEM_SELECTED` — and the direction is chosen the same way, by asking which mistake
is survivable. A component that wrongly says `PATH_WITHOUT_MODEL` gets its call
refused at construction (§6) and someone notices immediately. One that wrongly says
`NOT_COVERED` sends the user's accumulated model to a third party and nobody notices
at all. The asymmetry is total, so the fail-closed value is the one that refuses.

### 5. Computed by whoever composed the arguments, never inferred, and never cleared

> **Normative.** `coverage` is computed by the component that **composed the call's
> arguments**, from the membership and path character of what it supplied to the
> operations that produced them, and is written onto `CarriedProvenance` before the
> request reaches `EgressBinder.bind`. Any value a model, a tool, a tool declaration or
> a plan emitted for it is **discarded, not merged**.

> **Normative.** No component derives it by inspecting an argument's value, its name,
> its field, its shape or its resemblance to anything, and no seam invents one where a
> caller did not supply it. This is ADR-0146 §2's forbidden inference and ADR-0098 §5's
> unrecoverable relation, read on this axis.

> **Normative.** Where a request's arguments were composed by more than one component,
> over more than one supply, the value is the strongest of their states under §4's
> order. No component and no later step of a plan weakens a value an earlier one
> recorded, and no re-composition, re-planning, re-rendering, translation,
> summarisation, excerpting or round trip through a model improves one.

**Monotonicity is stated because the laundering path would otherwise simply move**,
and the corpus has watched it move twice. ADR-0106 §4 found it on the memory marker —
"No fold, merge, reinforcement, or supersession clears `derived_from_external`" — and
ADR-0181 §4 found it again one seam over: *"plan a step over tainted material, then
have a second step re-plan over clean material and watch the fact clear. A warrant is
never un-received, and neither is a selection."* Here the move would be shorter and
more tempting: hand a `PATH_WITHOUT_MODEL` value to a model, take its output, and call
the result `MODEL_ON_EVERY_PATH` because a model call is now on the path. ADR-0155 §3
already forecloses it — the overlap "falls to the absolute clause", because one
non-model path suffices "**forever**" — and this clause is that sentence stated where
a component could otherwise get it wrong.

### 6. The absolute clause gets its first mechanism: the binding refuses at construction

> **Normative.** `EgressBinding` **refuses at construction** a `coverage` of
> `PATH_WITHOUT_MODEL`. The refusal is unconditional: no argument, no tool, no account,
> no configuration, no policy and no user act admits one, and no lane adds a parameter,
> a flag or a subclass through which one could be admitted.

> **Normative.** No `ActionPolicy` floor is added for this case and no lane adds one.
> A request carrying that value is **unconstructable**, so a policy clause would be a
> second statement of one invariant with nothing to rule on — the shape ADR-0150 is
> named against. A policy may of course be stricter about anything (ADR-0021 §5).

> **Normative.** This is stated at construction rather than at the ruling because
> ADR-0155 §3's fourth clause makes authorisation irrelevant to it: "No authorisation
> makes a transmission either prohibition above forbids lawful." A refusal a policy
> could be replaced out of is not the refusal that clause asks for.

> **Normative.** This discharges ADR-0155 §4's marked clause **only to the extent the
> value was honestly recorded**, and no lane, ADR or surface states or implies more.
> Nothing here detects a component that records `NOT_COVERED` for a call that carries a
> store value, nothing inspects content to check a recorded state against it, and no
> bound in this corpus is obtained from a claim that something does. What changes is
> that the fact is now **recordable and recorded**, which is what #1154 asked for; what
> does not change is that the rule still binds an author who could lie to it.

**The whole call is refused rather than the span, and that is the conservative
direction rather than a compromise.** ADR-0155 §3's clauses are stated over a span, so
a per-span refusal would let the rest of a call through. Refusing the call refuses a
superset, and it never admits a span either clause forbids. It also matches what the
seam can actually do: ADR-0150 §4 makes the spans the arguments, and a send missing an
argument is not a narrower send but a different one (ADR-0148 §4's own rule about a
recipient set, one member over).

**"Refused before the surface" is the answer to the sharpest question this ADR
faces**, and it is worth putting plainly: a call carrying a verbatim store value in an
email body never reaches a confirmation at all. The user is not asked, because the
question is not the user's to answer. §7 argues why.

### 7. What stays forbidden, and why the user's eyes do not cure it

> **Normative.** ADR-0155 §3's **second** clause is not relaxed, narrowed, conditioned
> or reachable by any route this ADR opens. A span carrying covered content some
> covered path of which contains no model call is forbidden absolutely, whatever the
> approval surface shows, whatever the user read, whatever the user answered and
> whatever a policy or a grant says. Only the model-composed subclass — §3's third
> clause's own subject — becomes approvable, and only under §9.

> **Normative.** No lane reads this ADR, ADR-0004 §6, ADR-0073 §10's deferred `export`
> command, ADR-0007's `MemoryStore.export` or ADR-0123's backup artifact as being, or
> as authorising, the export ADR ADR-0155 §3's fifth clause reserves. ADR-0155 §3's
> sixth clause is restated here because this is the document a later lane is most
> likely to mistake for it.

**The texts settle this before any argument is needed.** The owner's ruling took arm
(b) of §3's **third** clause. §3's second clause has no fork, no arm and no
reservation; its only stated exception is the export ADR, and §3's sixth clause
forbids reading anything else as that ADR. A relaxation of the second clause would
therefore need an owner ruling nobody has been asked for, on a question nobody has
put, in an ADR whose subject is a different one.

**The substantive argument runs the same way, and is worth recording because it is the
argument that will be made against this section.** The case for relaxing the second
clause is that a user who reads a memory record in a body and presses *yes* has
consented to sending it, so the distinction between a recited record and a composed
paragraph stops mattering once both are on the screen. Three things defeat it.

- **The question is not the same question.** ADR-0155 §3's prose already draws the
  line, and it draws it about consent rather than about visibility: the question a
  confirmation puts is *send this message*, and the question the second clause is
  about is *relocate part of your accumulated model into a service you do not
  administer, permanently, beyond the reach of the delete right ADR-0004 §6 gives
  you.* "Those are different decisions with different consequences and different
  durations, and the first does not contain the second." Reading the bytes tells the
  user what this message says. It does not tell them that a second custodian now holds
  a piece of their model that ADR-0126's destruction of `Settings.data_dir` cannot
  reach. ADR-0097 §7 already named and refused this shape on a neighbouring seam — "the
  floor satisfied by a consent the user gave about something else entirely".
- **The relaxation would not stay bounded.** ADR-0155 §3 records why the quantifiers
  are written as they are: because one non-model path keeps content under the absolute
  clause forever, "a relaxation of the reserved clause can never carry a direct store
  record out with it", and the owner relaxing it "relaxes the whole of what they were
  asked about and only that". Extending this surface to the second clause would make
  the boundary the surface's own rendering rather than a recorded fact — and a
  boundary that depends on a rendering is one #1154's whole finding says nothing can
  enforce.
- **A verbatim value in a send is the laundering the corpus already refuses.**
  ADR-0181 §4's monotonicity and ADR-0106 §4's exist because a fact that can be
  cleared by another operation is a fact an author can route around. If a
  `PATH_WITHOUT_MODEL` value became sendable by being shown, the route is: read the
  store, put the value in a body, show it, press yes. That is #95's case with a screen
  in front of it, and #95 is the question ADR-0155 was written to answer.

**The counter-case is real and is not dismissed.** An owner who wants a memory record
in a message can compose it themselves — a `USER_AUTHORED`, `NOT_COVERED` span,
outside §3 in both directions, which ADR-0155 §2's second clause admits in terms — or
can ask for the export ADR §3's fifth clause reserves. What they may not have is the
system doing it for them under a per-send approval, because the per-send approval is
not the thing that decision needs.

### 8. The floor every surface owes: the bytes, span by span, whole, before the answer

> **Normative.** A surface rendering a `Confirmation` whose `egress` is present
> renders, **before it collects the user's answer** and in addition to ADR-0178 §7's
> floor and ADR-0181 §6's origin: for every span the `spans` tuple carries, that
> span's own value, taken from `Confirmation.parameters` under ADR-0150 §4's
> decomposition — the argument's whole value where `index` is absent, and that
> argument's value's element at `index` otherwise.

> **Normative.** The values are rendered **whole**: not truncated, not elided, not
> abbreviated, not summarised, not paraphrased, not collapsed behind a control the
> user must operate to see them, and not reordered so as to bury one. A surface that
> cannot render a value whole renders **no** confirmation and says so, which is
> ADR-0178 §9's second clause read one member over: a partial content-bearing
> confirmation is worse than none, because it looks like a whole one.

> **Normative.** No surface renders a summary, an excerpt, a description or any other
> derivation **in place of** a value. A summary of covered content is itself the output
> of an operation supplied covered content and is therefore covered content
> (ADR-0155 §3's first clause), and it is not what would be sent — so a user answering
> against it has answered about something else. A surface may render additional
> framing around a value; it may never render framing instead of one.

> **Normative.** The values are rendered **beside** the description and never in place
> of any part of it. ADR-0178 §7's floor is unreduced: the account identity, every
> occurrence with the argument it was selected by, both destination forms where an
> occurrence carries one, the canonical destination set as `core` derived it, and the
> payload description. ADR-0178 §7's sixth clause — "No surface renders the payload
> description as though it were the payload" — binds harder here than before, because
> both are now on the screen and a surface that merged them would be claiming the
> description states what the value says.

> **Normative.** A surface renders the call's `coverage` before it collects the answer,
> beside the values rather than in place of any of them, in **all three** states, as a
> statement about **the call** and at the strength the recorded fact carries: that
> nothing this call would send is drawn from what this system stores; or that some of
> what it would send was composed by a model that had been shown something this system
> stores; or — a state no confirmation can reach, since §6 refuses it at construction —
> that it carries something taken from this system's stores directly. It names **no
> record**, no record identifier, no episode, no store-side key, no field name of any
> store's schema and no memory (ADR-0150 §10's second clause, kept), and it names no
> kind of source.

> **Normative.** No surface renders it as a statement about a **span**. It is not
> attributed to an argument, a position or a destination, and no surface says or
> implies that any particular value is the covered one. This is ADR-0181 §6's fifth
> clause read one axis over, and it is stated for the same reason: the recorded fact is
> a disjunction over the call, so a per-span rendering would assert a marker §4
> deliberately does not mint.

> **Normative.** No surface renders `NOT_COVERED` as an assurance. It states that no
> covered path was recorded for this call, never that nothing in it relates to anything
> the user has told this system, and never that the send is safe. This is ADR-0181 §6's
> third clause read one axis over.

> **Normative.** No surface presents `coverage` as a detection, a score, a risk level,
> a recommendation or a warning that the call is malicious, and no surface conflates it
> with `planned_with_external_content`. The two answer different questions — where what
> this call would send came from, and whether the material selected into the planning
> call carried the external mark — and a surface that rendered one as the other would
> be asserting a marker neither ADR mints.

> **Normative.** No surface offers a control that answers more than one confirmation,
> pre-selects an affirmative answer, defaults to one, or presents approval as the
> lower-effort path: no "approve all", no pre-checked box, no affirmative default on a
> prompt, and no control that both reveals a value and approves it. Where a surface has
> an order, the values precede the controls.

> **Normative.** Every value is inserted into the surface's output as **data**,
> neutralised for that target on render (ADR-0042 §4, ADR-0178 §7's seventh clause).
> Being the argument the user is about to send relaxes nothing, and a multi-line value
> carrying terminal control sequences, markup or a line that mimics the surface's own
> framing is the case this clause exists for.

> **Normative.** A surface rendering a `Confirmation` whose `egress` is `None` owes
> none of this and asserts none of it.

**Stated over what the confirmation carries and what the surface renders, never over
what the user understood.** ADR-0148 §8's fourth clause is explicit about why — the
second "is not obtainable", "the discipline ADR-0098 §3 records learning twice" — and
§11 below says plainly what that leaves undelivered. What a floor can buy is that the
bytes were on the screen, unabridged, before the control was offered, and that is what
this section buys.

**Rendering all three states rather than only the interesting one.** ADR-0181 §6's
fourth clause gives the argument and it transfers exactly: "a fact shown only when it
is alarming is a fact a user learns to read as an alarm, and its absence as
clearance". The third state is rendered even though §6 makes it unreachable in a
confirmation, so that a surface's rendering is total over the enum rather than over the
states a lane believes it will meet.

**The no-summary clause is the one most likely to be argued with, and it is the one
that carries the decision.** A long body is genuinely unpleasant to read on a phone,
and the obvious kindness is to show a précis with the full text a tap away. That
kindness is what makes the approval meaningless: the user would be answering about the
précis, the précis is itself covered content composed by a model over the same inputs,
and the bytes that leave are the ones they did not read. #1548's survey found that no
surveyed runtime shows the content that is about to leave at all, and the one that
comes closest — LangChain's `HumanInTheLoopMiddleware` `edit` decision — is filed
there under **Avoid** for a different reason §9 below adopts. There is no prior art to
copy here, and the kindness is the failure mode.

### 9. When a model-composed span may be carried, stated as a condition on the call

> **Normative.** An egress call whose binding carries `coverage` of
> `MODEL_ON_EVERY_PATH` may carry covered content **only** where all four hold: the
> binding carries that value under §4, written by the component that composed the
> arguments under §5; the ruling on that request is a `CONFIRM` answered by the user
> under ADR-0148 §3's route (a), on **that** request; the `Confirmation` put to the
> user carried every span's own value in `parameters`, and the surface that rendered it
> owed and met §8's floor; and the recorded decision binds those exact bytes by
> `parameters_digest`, which `PermissionDecision.authorises` compares before the seam
> transmits. Where any of the four fails, ADR-0155 §3's third clause forbids the span
> exactly as written.

> **Normative.** No standing authorisation, standing policy, standing recipient grant,
> configuration, connected account, tool declaration or approved payload description
> covers such a call, ever. ADR-0154 §4's floor is unlifted, ADR-0181 §5's second
> clause binds unchanged, and ADR-0193 §5's ruling — a grant reaches the recipient and
> **never** the payload — is the reason "remember this recipient" means here exactly
> what it already means: the next send to the same recipient asks again about its own
> content, because the content is what was approved and the content is new.

> **Normative.** Nothing in this section makes a transmission ADR-0155 §3's **second**
> clause forbids lawful, and no lane reads the four conditions as an authorisation of
> any kind. They are the conditions under which the third clause's prohibition does not
> apply to a span; a span the second clause reaches is not reached by this section at
> all, and §6 refuses it before any of the four can be evaluated.

> **Normative.** No component "checks" the second condition's surface half at the
> ruling, and no lane widens `ActionPolicy`, `EgressBinding` or the seam so that it
> could. §8's floor binds surfaces and is enforced the way ADR-0178 §7's floor is
> enforced — by tests over each surface, named in §13 — and a lane that renders a
> confirmation without meeting it has breached this ADR whether or not any code
> noticed. That is the same posture ADR-0155 §4 takes about §3 itself, applied to the
> surface, and it is stated rather than dressed up.

**Why the four conditions are stated together rather than as one gate.** Three of
them are already true of every egress call in this tree — the ruling is a `CONFIRM`
because ADR-0148 §8's `discloses` floor makes it one and ADR-0154 §4 admits no
standing route; the confirmation carries `parameters` because ADR-0042 §4 puts them
there; and the digest binds the bytes because `authorises` compares it. Naming them
anyway is what makes the relaxation legible as a *conjunction* rather than as a new
permission: a lane reading §9 in isolation must satisfy all four, and a later ADR
removing any one of them removes the ground this relaxation stands on.

**And the fourth condition is what stops the surface being decorative.** Without the
digest, a content-bearing confirmation would show one body and send another, and the
only check downstream is `_check_spans_cover`'s multiset of code-point counts — which
the tree's own commentary records as unable to tell two equal-length texts apart. With
it, the bytes the user read and the bytes the seam transmits are the same bytes or the
call is refused. #1548's survey records one runtime doing something of this shape:
OpenClaw binds an approved run to "cwd, exact argv, env binding when present, and
pinned executable path", hashes a shell script's file operand, and denies the run
rather than "executing drifted content". This corpus got there first, by a different
route, and §9 is where it is finally spent on content.

### 10. An edit is a new request, and it clears nothing

> **Normative.** Where a surface offers the user an edit before sending, the edit
> produces a **new** `ActionRequest`: new `parameters`, a newly derived binding, a new
> `parameters_digest`, a new ruling and a new `Confirmation` carrying the edited bytes
> under §8's floor. No component mutates a parked request, amends an approval, or
> resumes a parked step with parameters other than the ones its recorded decision
> binds.

> **Normative.** An edit **never** weakens the new request's `coverage`. A request
> whose values were edited from a `MODEL_ON_EVERY_PATH` call carries
> `MODEL_ON_EVERY_PATH`, and one edited from a `PATH_WITHOUT_MODEL` call carries
> `PATH_WITHOUT_MODEL` and is therefore refused at construction exactly as its
> predecessor was. No component decides otherwise by comparing the edited text to the
> original, by measuring how much changed, or by any other inspection: that is §5's
> forbidden inference, and it is where the laundering route would reappear if it were
> admitted.

> **Normative.** This ADR decides that an edit has that shape **if** a surface offers
> one; it does not oblige any surface to offer one, and §13 leaves that to the
> implementing lanes. A surface offering none is conformant.

> **Normative.** A surface offering an edit reports which act landed, on ADR-0139 §4's
> three-valued discipline: the original confirmation was declined and the new one
> asked, or it is known not to have been, or the outcome is not known. No surface
> presents an edit as atomic, as amending an approval, or as leaving the original
> question open.

**This is the one place the survey found prior art and the prior art is the mistake.**
#1548 records LangChain's `HumanInTheLoopMiddleware` admitting an `edit` decision in
which "the human rewrites the arguments and the edited call runs under the approval
that was asked about the original", and files it under **Avoid** with the reason this
section adopts: "Our binding is whole-or-absent and `authorises` compares the fixed
request (ADR-0150 §1); an edit is a new request and owes a new ruling. Say so … rather
than leave it to be discovered." It is said here.

**The coverage clause is the substantive half, and it is deliberately unkind.** The
intuitive rule is that a body the user rewrote is the user's own words and so is
outside §3 — and for a body the user wrote from nothing, that is exactly right, and
the composing component records `NOT_COVERED` because that is what it supplied. What
the rule cannot be is a *test on the edit*, because the edit's input was covered
content this system put in front of the user, so every path of the result still runs
back through the model call that composed it. Admitting the intuitive rule would make
"draft it from my memory, change one character, send" a lawful route to everything §3
forbids, and would make the boundary a similarity judgement — the unrecoverable
relation ADR-0098 §5 forbids deciding on and ADR-0155 §3 was corrected for twice.

**What this ADR deliberately does not decide is the edited span's *discloser*
provenance.** That is ADR-0146's axis, ADR-0150 §5 makes it carried and never derived,
and the component building the new request answers it from its own recorded origin as
it does for every other span. Nothing here changes ADR-0146 §1, ADR-0146 §2 or
ADR-0150 §5, and no lane reads this section as deciding that a user's edit makes a
span `USER_AUTHORED`.

### 11. Per channel: the browser, the terminal, and a channel of unbounded audience

> **Normative.** §8's floor is stated over "a surface" and binds every surface that
> renders a `Confirmation` whose `egress` is present, including one this ADR does not
> name. A third adapter inherits it without a third decision (ADR-0073 §4, ADR-0139
> §3, ADR-0178 §7).

> **Normative.** The browser page and the terminal are the two surfaces that owe it on
> the day it lands. Both already render `Confirmation.parameters` and neither renders
> it under an obligation; §13 names what each owes.

> **Normative.** This ADR states the posture ADR-0199 §3's sixth clause obliges it to
> state, for the content this surface renders: an egress argument's value, and any
> rendering, excerpt, summary, paraphrase or description of one, is **withheld** from
> a channel of unbounded audience. It is placed as speakable on no such channel, by
> this ADR or by any silence in it.

> **Normative.** No spoken confirmation surface is created, and none may be created by
> reading this ADR. ADR-0207 §2's fixed sentence — `I need you to confirm something on
> your screen.` — remains the whole of what a live confirmation park says on
> `converse_spoken`, and ADR-0207's placement "reaches that one constant and nothing
> else". A memory-drawn email is approved on a screen or it is not approved.

> **Normative.** No summary of an egress argument is spoken in its place. A summary of
> covered content is covered content (ADR-0155 §3's first clause), it is withheld by
> the clause above, and it would not be the thing approved in any case (§8).

> **Normative.** An ADR that admits a spoken or otherwise audible channel whose
> audience is **bounded** decides in its own text whether this content is placed as
> speakable there, on ADR-0199 §5's terms and its own. This ADR neither places it nor
> forecloses that ADR, and no lane reads this section as having decided a bounded
> channel's posture either way.

**The owner's phrase "on the channel they are on" is honoured on the channels that
can carry it, and the one that cannot is named.** For the browser and the terminal it
is exactly what §8 requires. For `converse_spoken` it is not available: ADR-0200 §3
declares that channel's audience unbounded, ADR-0203 subtracts the withheld classes
from the turn's supply before it plans, and ADR-0199 §3's sixth clause forbids settling
a new producer's posture by silence. Reading a full email body — composed over the
owner's memory, addressed to a named third party — aloud into a room is the disclosure
ADR-0199 exists to refuse, and it is refused for whoever else is in the room rather
than for the owner. Reading a *summary* aloud is worse, not better: it discloses the
same class and approves the wrong bytes.

**What that costs is real and is stated rather than minimised.** In a deployment whose
only surface is voice, the first customer of this ADR is unreachable: a memory-drawn
email cannot be approved at all, and the turn parks until the owner reaches a screen.
That is ADR-0207's existing behaviour applied to a new case rather than a new
restriction, and the alternative — a channel-specific carve-out for one content class
— is the shape ADR-0199 §3 was written to refuse.

### 12. The privacy consequences, stated in terms

ADR-0155 §3's arm (b) requires this ADR to state its privacy consequences. This
section is that statement. Its clauses bind what may be claimed; the account around
them is argument (ADR-0089 §1).

> **Normative.** No lane, ADR or surface states or implies that this surface makes a
> send safe, that a confirmed send was read, that a user who approved understood what
> they approved, or that the approval establishes anything beyond what
> `PermissionDecision` records: that this user, at this instant, answered `yes` to a
> question carrying these bytes to these destinations.

> **Normative.** No lane, ADR or surface states or implies that this surface detects a
> credential, a secret, a Tier 0 value or any other class inside an argument's text.
> It performs no scan of any kind, and #75's question is untouched (§13).

> **Normative.** No bound in this corpus is obtained from a claim that a user reads
> what is rendered to them.

**What the owner buys, and what it costs, in one paragraph each.**

**The capability.** The assistant may draft outbound content from what it knows about
its owner — an email that recalls the thing the owner asked it to recall, a search
query enriched by what the turn already established — and the owner sees the words
before they go. That is the "large limitation" the owner named lifted, and it is
lifted for exactly the class ADR-0155 §3's third clause reserved and for nothing
adjacent to it.

**The blast radius, stated at its widest rather than at its typical.** The moment the
user confirms, those bytes are in the recipient's hands and — because a model composed
them — were already in the model provider's. ADR-0155 §5's third clause says what
follows: "the recipients' providers persist copies for as long as their own policies
say, and neither this system nor the owner's delete right can reach them." A memory
the user has forgotten they told this system can be exposed by a send they approved
without reading, and nothing in this design prevents that. And nothing in this design
bounds *how much* of the accumulated model one approved message may carry: a model
asked to write everything it knows about its owner to a named recipient produces one
span, one confirmation and one approval. **That is the trade the owner made, and it is
the honest statement of it.**

**What bounds it, and each bound is a mechanism rather than a hope.** ADR-0155 §3's
second clause keeps every direct store value out permanently, and §6 now refuses one
at construction rather than trusting an author. Every send is a fresh per-call decision
with no standing route (ADR-0148 §8, ADR-0154 §4, ADR-0181 §5, ADR-0193 §5). The bytes
are fixed between the question and the send by `parameters_digest`, so what was read
is what leaves. And the description names no record and holds no content, so the trail
records that a span of some extent went to some recipient under a call of some
coverage, and never *which* memory and never what was said — which is why ADR-0150
§10's deletion answer survives this decision unchanged.

**What is not bounded, and is named so that nobody claims otherwise.** Reading. The
surface can put the bytes above the controls, whole and unabridged, with no affirmative
default and no "approve all"; it cannot make anyone read them, and a long body on a
small screen is the case where it most matters and is least likely. ADR-0148 §8's
fourth clause chose to state the obligation over the confirmation's contents rather
than over the user's understanding "because the second is not obtainable", and that
choice is inherited here rather than improved on. This is the residue this decision
leaves, and it is the residue arm (a) would not have had.

**Why arm (b) is still the better trade, given all of that.** Arm (a) — ratifying the
prohibition permanently — has a cost ADR-0155 named precisely: it is the "false on the
day it is written" shape, a system that knows its owner and may not use that knowledge
to write to anyone on the owner's behalf. Arm (b)'s cost is the paragraph above, and
it falls on a decision the owner takes one message at a time with the words in front
of them. Both are real; the owner ruled; this section records what was bought.

### 13. What is not decided here, each with its reason

> **Normative.** Beyond the marked clauses §16 enumerates, this ADR decides nothing.
> It registers no tool, designates no seam, adds no `DestinationProtocol` member,
> changes no Protocol signature, authorises no dependency or destination, and attests,
> relaxes or adds no condition of ADR-0017 §3 or ADR-0154 §4.

> **Normative.** This ADR discharges **no part** of ADR-0150 §6's tier residue. A
> value this system already holds at a tier, carried into a field that establishes
> none, is still described with no tier; `SpanCoverage` is not a tier, states nothing
> about one, and no lane cites it, or this ADR, as discharging ADR-0146 §5's third
> clause. ADR-0150 §6's own clause — that the closing mechanism is a recorded per-span
> classification whose ADR amends ADR-0148 §6 — remains owed for the tier axis, and is
> now owed by an ADR whose own choice between a per-span carriage and a call-level
> one is untouched by §4's, since §4 puts its fact on the binding and adds nothing to
> the description.

Named individually:

- **#75 — Tier 0 inside user-authored content.** Deferred by name and not by silence.
  The issue's own 2026-07-20 reframe rules that user-authored content "is authorised as
  submitted, whatever it contains" and that the remaining question is "a product and
  safety question" rather than a compliance gap; the 2026-09-02 census closed it as
  "owner ruling — not a defect". This surface is therefore **not** where egress-side
  secret detection lands, and §12's second clause forbids claiming it is. Its trigger,
  if it ever fires, is an owner ruling that the assistant should warn — which is a
  decision about a feature, not about this floor.
- **#1379 — the confirmation payload exceeding the frame limit.** Not answered, and
  the arithmetic is stated rather than denied. §4 adds **one** short enum value to the
  **binding**, once per call, and nothing to `EgressSpan` and nothing to the payload
  description — so #1379's product term, `EgressSpan.argument` repeated once per span,
  is untouched and the confirmation grows by a constant. It adds **no content to the
  frame** either, because `Confirmation.parameters` already travels (ADR-0042 §4) and
  the payload the wire measures already includes it. ADR-0178 §9's figures do not move,
  its no-truncation clause is reinforced by §8's whole-rendering clause, and the
  compact-locator decision #1379 asks for stays where its firing condition leaves it. What this ADR does add is a reason to expect a
  *larger* `parameters` in practice, since a model-composed body is longer than the
  test payloads the seam has carried so far; that is an operator's
  `hub_max_frame_bytes` question and is named here rather than discovered.
- **#57 — the payload manifest's granularity.** Untouched, and untouched more
  completely than an earlier draft of this ADR would have left it: §4 adds **nothing**
  to the payload description, so the granularity question arrives at ADR-0150 §10
  exactly as ADR-0148 §13 and ADR-0155 §7 left it, and §10's fifth clause governs a
  richer artifact if one is ever built.
- **#1154 — the enforcement point.** Partly discharged and honestly so. §4 makes the
  fact recordable, §5 says who records it, and §6 refuses on it; what remains open is
  everything §6's fourth clause names — nothing detects a component that records the
  fact wrongly. The issue stays open with that narrower subject.
- **Whether the browser or the terminal offers an edit at all.** §10 fixes the shape
  of one if it is offered and leaves the offer to the implementing lanes, because it
  is a product question about two surfaces with different affordances and neither
  answer breaks anything here.
- **The owner's export of their own accumulated model into a service they name.**
  ADR-0155 §3's fifth clause reserves it, §7 above restates that this is not it, and
  ADR-0073 §10's local `export` and ADR-0123's backup artifact are untouched.
- **Whether a standing authorisation may ever cover an egress call.** ADR-0154 §4
  answered no at this seam and named the condition for revisiting; §9's second clause
  adds a floor beneath it for this class and reopens nothing.

### 14. Every other ADR classified under ADR-0082 §1, and the history epoch decided

The header records the partial supersessions this ADR makes and names every clause each
one reaches. This section applies ADR-0082 §1's test to every *other* ADR a reader
might expect a record on, states the extent of the two records the header does not
argue in full, and states why nothing is owed on the rest — the judgement being made in
this ADR's text, which is where it is reviewed. It carries no count of its own: §16
enumerates the marked clauses, and an ordinal restated here is the drift this ADR has
already corrected twice.

- **ADR-0178. A record is owed, and on one clause only: §2's field count.** §2 fixes
  `ConfirmationEgress`'s fields — "exactly two fields, both required with no default" —
  which ADR-0181 §3 already narrowed to three and recorded there as a partial
  supersession. §4 above adds `coverage` as a fourth, by the identical route and for the
  identical reason, so the same clause is narrowed again by one and this ADR's pair
  accumulates beside ADR-0181's on the leading-token line (ADR-0070 §4). §10's
  `model_fields` roster test moves by one further entry with it, exactly as ADR-0181's
  own record says it moved by one — the test keeps its subject, which is that no field
  of `ConfirmationEgress` is named or typed for a connection reference, a transport
  endpoint, a `BoundAccount` or a `SecretName`, and `coverage` is none of those.
  **No record is owed on §7**, and the distinction is the point of ADR-0082 §1: §7's
  floor is a floor, and §8 above adds an obligation on top of it without making any
  sentence of §7 false. Every clause of §7 still holds of every surface, and §7's sixth
  clause ("No surface renders the payload description as though it were the payload") is
  not merely intact but is quoted and relied on. That is a **stacked addition**,
  recorded in the ADR that makes it and nowhere else. §9's size clauses likewise stay
  true (§13), and `Confirmation` gains no member, so §10's seven-field roster test on it
  keeps its count.
- **ADR-0181.** No record. §6 rules what a surface shows about
  `planned_with_external_content`; §8 above adds a different fact on a different axis
  and forbids conflating them. No sentence of §6 becomes false or over-wide: it says
  nothing about what else a surface may render, and its fifth clause — that the
  *external* marker is never a per-span claim — is obeyed exactly, since `coverage` is
  not that marker. §5's gate and §4's monotonicity are read across, not amended.
- **ADR-0193.** No record. §9's second clause restates a consequence ADR-0193 §5 and
  ADR-0154 §4 already rule — a grant reaches the recipient and never the payload — and
  ADR-0082 §1 is explicit that "Absent a clause that fails §1's test, there is nothing
  to record". No clause of ADR-0193 becomes false, and no grant's coverage changes.
- **ADR-0207.** No record. §11 above states a posture for a producer ADR-0207 does not
  produce and leaves ADR-0207 §2's sentence, its placement and its scope exactly as
  ratified. ADR-0207's placement "reaches that one constant and nothing else", which
  is a statement that stays true.
- **ADR-0199 and ADR-0203.** No record. ADR-0199 §3's sixth clause **obliges** a new
  producer's ADR to state its posture in its own text, and §11 states it. Discharging
  an obligation an earlier ADR imposes is not amending it.
- **ADR-0150 §5, specifically.** No record, and the corpus has already ruled this
  exact question once. §5's first clause — "There is no separate marker type, no
  second carriage of provenance in the request, and no field on `ActionRequest`
  outside the binding that states it" — governs **discloser provenance** and not every
  axis, which ADR-0150's own dated note of 2026-08-23 states in terms when ADR-0181
  added the externality axis: "**§5's first clause is not narrowed and must not be
  read as breached.**" `SpanCoverage` is a third axis on the same footing. That note's
  closing observation — "`EgressSpan` gains nothing" — is true of §4 above too: the
  new axis rides the **binding**, exactly where ADR-0181 put the externality axis and
  for the reason it gave, so §5's field is untouched at every site and the question
  that note answered does not arise a second time.
- **ADR-0146 and ADR-0106.** No record. `SpanCoverage` is a third axis beside the
  discloser axis and the externality axis; ADR-0146 §1's two members and §2's
  carried-not-inferred rule are unchanged and are the model §5 copies, and ADR-0106
  §4's monotonicity is read across rather than restated over its own field.
- **ADR-0184.** A record **is** owed and the header states its extent clause by clause:
  §1's exception roster, §2's first, third and fifth clauses, §3's discrimination
  sentence and §9's first clause. Two things are *not* owed there. One is a record about
  §9's *deferral*, which is unmarked prose in a marked ADR (ADR-0089 §3) and is
  discharged rather than superseded. The other is any record on §4, §5, §6, §7 or §8:
  each stays true and each is relied on below. §4's write-path refusal, §5's readers and
  §8's refusals speak of the *origin*-unrecorded shape and keep speaking of it exactly;
  the clauses below state the parallel rules for the new sibling in this ADR's own text
  rather than widening theirs, which is the same instrument §7's floor is extended by.
  **§3 is the one to read carefully, because half of it is superseded and half is
  load-bearing.** Its *property* — that `extra="forbid"` makes the union total and
  mutually exclusive with no discriminator field, no tag, no version key and no
  `Literal` member — is not touched by one word and is precisely what makes a third rung
  representable. Its *sentence* naming which shape a `planned_with_external_content`-
  bearing object validates as is the half that stops being true, and the header records
  that half alone.
- **ADR-0150 §1's union clause, specifically, and why no second pair is owed there.**
  §1 types `PermissionDecision.egress_binding` as `EgressBinding | None`, and that clause
  is **already** partially superseded by ADR-0184 — it is the scope named on ADR-0150's
  own `Status` line. The clause a reader of ADR-0150 is sent to for the current type is
  therefore ADR-0184 §2's fifth, which is exactly the sentence this ADR supersedes and
  records. Adding a second pair to ADR-0150 would record the same move twice and point a
  reader at a clause ADR-0150 no longer states; the chain ADR-0150 → ADR-0184 → this ADR
  is complete without it, and ADR-0070 §4's precedence rule already gives the later ADR
  the overlap. This is classified here rather than left silent, because "no record" and
  "nobody looked" read identically on a `Status` line.
- **ADR-0152. A record is owed on §7's count, and an earlier draft of this section said
  the opposite on a precedent that does not exist.** §7 rules that `rebind` "takes from
  `approved` **exactly one** thing"; ADR-0181 §3 made it two. That draft asserted
  ADR-0181 had recorded the narrowing "in its own text rather than on ADR-0152" — it did
  not. ADR-0152's `Status` line has read "Partially superseded by … ADR-0181 (§7's
  clause that `rebind` takes exactly one thing from `approved`)" since 2026-08-23, with
  the dated note beneath it. §4 above narrows the same count from two to three by the
  identical route and for the identical reason — the fact is about a composition made
  before the confirmation was parked and `rebind` receives nothing to recompute it
  from — so the record is owed on the same clause and this ADR's pair accumulates beside
  ADR-0181's. **Nothing else in §7 moves**: the afresh derivation, the whole-value
  equality refusal, both unmatched-locator refusals, the no-`SYSTEM_SELECTED`-fill rule
  and the two `None` limbs all stand.
  The correction is recorded rather than quietly made, because the false claim was the
  *ground* the no-record classification stood on, and a reader who checked the ground
  would have found the classification unsupported before finding it wrong.
- **ADR-0042 and ADR-0085.** No record. `Confirmation.parameters` is used as ADR-0042
  §4 already provides it, and no figure of ADR-0085 §8 moves (§13).

> **Normative.** ADR-0184 §9's deferral **fires with this ADR and is answered here**:
> §4 adds a member required with no default to a `core` model the audit trail stores,
> and the choice §9 puts to it — a second sibling, or the deferred stored payload
> version for the trail's `data` column — is decided in favour of a **second sibling**.
> `core/types.py` gains `CoverageUnrecordedBinding`: the value a decision recorded
> between `planned_with_external_content`'s arrival and `coverage`'s reads back as,
> carrying every member `EgressBinding` carries **but** `coverage`, each required with
> no default, satisfying every invariant `EgressBinding` enforces over those members.

> **Normative.** Each member is still declared **exactly once**, on a private base
> chain the three models inherit — the three shared members on the base ADR-0184 §2
> already puts them on, `planned_with_external_content` on a second private base
> beneath it that `EgressBinding` and `CoverageUnrecordedBinding` share, and `coverage`
> on `EgressBinding` alone. No model restates a member, a validator or the derived
> `canonical_destination_set`, which is ADR-0184 §2's rule obeyed rather than narrowed.

> **Normative.** `PermissionDecision.egress_binding` becomes
> `EgressBinding | CoverageUnrecordedBinding | OriginUnrecordedBinding | None`, still
> one field, still named `egress_binding`, still defaulting to `None`, and `None` keeps
> exactly the meaning ADR-0150 §1's second clause gives it. `ActionRequest.egress_binding`
> stays `EgressBinding | None` and no lane widens it (ADR-0184 §2's fourth clause).

> **Normative.** The discrimination stays **structural, total and mutually exclusive**
> (ADR-0184 §3) and is a **ladder rather than a matrix**, because the epochs are totally
> ordered in time: a row lacking `planned_with_external_content` necessarily lacks
> `coverage` too, so the three shapes form a chain and no fourth combination exists to
> represent. Stated as the rule ADR-0184 §3's two-shape sentence is replaced by, and
> ADR-0184 §1's exception roster with it: a stored object carrying **both**
> `planned_with_external_content` and `coverage` validates as `EgressBinding` and as
> nothing else; one carrying `planned_with_external_content` but **not** `coverage`
> validates as `CoverageUnrecordedBinding` and as nothing else; one carrying **neither**
> validates as `OriginUnrecordedBinding` and as nothing else — that shape being the one
> carrying every member `EgressBinding` requires except those two, which is ADR-0184
> §1's roster with the second name added and its narrowness untouched. Still no tag, no
> version key, no `Field(discriminator=...)` and no `Literal` member: `extra="forbid"`
> does the whole job on three models as it did on two. A row missing a member in any
> other way, or faulty at any other position, satisfies none of the three and still
> raises, so the tolerance stays exactly as many shapes wide as there are epochs. No lane mints one, and no lane adds a further member to this union on the
> strength of this ADR — an ADR adding another member required with no default to a
> model the trail stores makes ADR-0184 §9's choice again, in its own text, with three
> data points.

> **Normative.** Nothing is written, in either direction. A recorded row is never
> rewritten, never backfilled, and never re-interpreted as though a coverage had been
> recorded for it (ADR-0184 §4). ADR-0184 §7's floor is extended **by cause**:
> `ActionPolicy.resolve` returns no `ALLOW` on a `confirmed` whose `egress_binding` is
> a `CoverageUnrecordedBinding`, whatever `approved` says, for §7's own reason — the
> fact the ruling would rest on was never recorded. The clause is stated on the
> `ActionPolicy` Protocol and asserted in `ActionPolicyContract`, beside ADR-0184 §7's,
> and no signature moves.

> **Normative.** The write path is closed to it as well, and ADR-0184 §4's second
> clause is extended **by cause** exactly as §7's floor is: `AuditTrail.record`
> refuses a decision whose `egress_binding` is a `CoverageUnrecordedBinding`, with the
> trail's existing `AuditError` for a decision that is not a valid record and no new
> error class, asserted in the shared `AuditTrailContract` suite beside ADR-0184 §4's.
> This shape too is only ever **read** out of a store and never minted into one.
> `PermissionDecision.from_request` gains no route to it either, because the clause
> above leaves `ActionRequest.egress_binding` narrow — so every live path is closed by
> construction and `record` is the floor for a caller that assembles a decision by
> hand.

> **Normative.** The park route is closed to this epoch too, by cause rather than by
> re-argument. `AuditTrail.pending_confirmation` answers `None` for a decision whose
> `egress_binding` is a `CoverageUnrecordedBinding`, detected on the decoded value's
> type and carrying its own condition name in the log; the step stays durably
> `AWAITING_APPROVAL` with its `CONFIRM` unresolved and its row intact, nothing is
> written, and nothing here makes such a park resumable (ADR-0184 §5's second and third
> clauses). The four history readers return the row as history exactly as §5's first
> clause already makes them, and `EgressBinder.rebind` never receives one (ADR-0184
> §8's third clause).

> **Normative.** Both `ConfirmationEgress` assembly sites narrow the union and
> **refuse** a `CoverageUnrecordedBinding`, which is ADR-0184 §8's fourth clause
> applied one epoch on — every site reading a decision's `egress_binding` refuses the
> unrecorded case rather than assuming it away, whatever the reachability argument
> says. No lane mints a coverage-unrecorded confirmation shape, gives
> `ConfirmationEgress.coverage` a default or a nullable member, or renders a
> confirmation for such a row (ADR-0184 §8's second clause, read the same way).

**The origin guard does not catch this epoch, which is why the refusal is stated and
not inherited.** `_egress_of` in `orchestration/engine.py` refuses an
`OriginUnrecordedBinding` before it composes anything, and its own docstring rests the
floor on `pending_confirmation` answering `None` for such a row. A coverage-unrecorded
row does not trip that `isinstance`: it **has** `planned_with_external_content`, so it
falls past the origin guard and reaches the constructor, where a required `coverage`
can be neither transcribed from a binding that does not carry it nor honestly
invented — the fabrication ADR-0184 exists to avoid, at the surface where the user is
being asked to approve something. The two clauses close it at both ends: the first
keeps the row from reaching the site, the second refuses it there regardless.

**The sibling rather than the version, and the reason is a fact ADR-0184 §9 did not
have.** §9 offered the version as the answer that "would make the next epoch cheap",
and adversarial review of this ADR's first round found why it cannot be the answer at
all: **a version key names the schema a row stands under and supplies no representable
value for it.** A stored binding missing a required field still decodes into no type,
so a row at an older version would be neither typed nor legible — the failure ADR-0184
is titled against. A version is a good answer to *which* schema and no answer to
*what value*, and this question is the second one.

**§9's objection to accumulating siblings does not bite here, and the reason is
structural rather than a plea.** §9 warned that "three siblings is six pairwise
discriminations to reason about and a union every consumer must exhaust". Six pairwise
discriminations is the cost of *unordered* variants. These are ordered: every epoch
strictly precedes the next, so each shape is the next one minus a field, and the
discrimination is two field-presence tests taken in one direction. A consumer
exhausting the union writes three arms, and each arm names exactly which fact it does
not have — which is §9's own stated reason for preferring a named absence to a general
one ("a reader meeting it learns something specific").

**And an earlier draft of this section chose the version, which is worth recording
rather than quietly repairing.** It reached for the version on §9's own words and did
not check that the version could produce a value; ADR-0089's neighbours are full of the
same shape, and ADR-0155 §3 records its own document making a related mistake twice.
The finding is kept here as evidence rather than summarised away.

### 15. What the implementing lanes owe

This section is direction for the lanes that build it, and it binds them as marked.

> **Normative.** The `core` change lands **before** anything implements against it and
> in its own PR: `SpanCoverage`; `coverage` on `EgressBinding`, `CarriedProvenance` and
> `ConfirmationEgress`; `EgressBinding`'s construction refusal; and
> `CoverageUnrecordedBinding` with the widened union and the private base chain §14
> decides. Golden rule 5 and ADR-0015 §5 govern the sequencing.

> **Normative.** "Before anything implements against it" bounds that PR by a test and
> not by a list: outside `core` it carries exactly what this ADR's own clauses make
> unsatisfiable, or the tree unbuildable, without it — and nothing else. As this ADR
> stands that is five things. The fail-closed `PATH_WITHOUT_MODEL` at every existing
> construction site whose composer does not yet compute the value, because `coverage`
> is required with no default and the tree must build. §4's transcription of
> `coverage` from the recorded decision's `egress_binding` at both `ConfirmationEgress`
> assembly sites, because §4 admits no other route and a constant there would be a
> second carriage. The `PROTOCOL_VERSION` move the next clause requires. The
> `ActionPolicyContract` assertion the clause after it requires. §14's
> `AuditTrailContract` assertion of the `record` refusal, for the same reason as the
> `ActionPolicy` one: the type it refuses lands in this PR and nothing later is owed
> it. Two things it does
> **not** carry, and they are what the first sentence is for: the composer's
> computation of the value, which is the lane below, and any change to a rendering
> surface, which is §8's lanes. A lane that finds a further thing the contract makes
> unavoidable carries it under this test and records that it did, rather than reading
> these five as exhaustive.

> **Normative.** `PROTOCOL_VERSION` moves, because `ConfirmationEgress` gains a member
> and that value crosses the wire (ADR-0178 §6's rule).

> **Normative.** The `ActionPolicy` clause §14's fifth clause states is stated on the
> Protocol and asserted in the shared `ActionPolicyContract` suite, beside ADR-0184
> §7's, in the same change as the type. No method is added, no argument widened and no
> return annotation changed.

> **Normative.** `coverage` is written by the component that composes a call's
> arguments, in the lane that **follows** the `core` change and not in the `core`
> change itself. `StepRunner._bound`'s `CarriedProvenance(spans={}, …)` in
> `orchestration/runner.py` is the site: the `core` PR leaves it passing the
> fail-closed constant its own clause allows, and this lane makes it compute. The
> corpus stops there at its peril — a field that lands with nothing writing it leaves
> a seam answering `PATH_WITHOUT_MODEL` and refusing every send, which is the
> fail-closed direction working and an unfinished job, so a batch that defers this
> lane files the issue that owns it rather than leaving it unowned.

> **Normative.** Each surface's lane pins §8's rendering floor with tests over that
> surface's own output: every span's value appears, whole and untruncated, before the
> control, and a value carrying that surface's own framing characters is neutralised.

> **Normative.** Each surface's lane pins §8's coverage floor with tests over that
> surface's own output: all three states render, none renders as an assurance, a
> warning or a per-span claim, and none is conflated with the origin line ADR-0181 §6
> already requires.

> **Normative.** Each surface's lane pins §8's control floor with tests over that
> surface's own output: no control answers more than one confirmation, none defaults
> to approval, and none both reveals a value and approves it.

> **Normative.** The **browser** lane additionally drives the page at a desktop width
> and at a phone-class viewport and records what it saw, because "before the control"
> is a claim about a rendering that no assertion over the bytes can check. No other
> surface's lane owes that observation.

Representative inputs the implementation is measured against, each named so a lane
builds the case rather than inventing one:

- A memory-drawn email body is rendered **verbatim** in the confirmation, and the send
  transmits exactly those bytes; a body altered between the confirmation and the resume
  is refused by `authorises` before the seam is reached.
- Two decisions differing in `coverage` **alone** — same tool, same parameters, same
  step, same execution, same spans, same destinations, one `MODEL_ON_EVERY_PATH` and
  one `NOT_COVERED` — do not authorise each other's requests, and `authorises` refuses
  before the seam is reached. The altered-body and edit cases above both move
  `parameters_digest`, so an implementation that left `coverage` out of §4's whole-
  binding comparison would pass them both; this is the case that fails it.
- A confirmation on a call carrying `MODEL_ON_EVERY_PATH` renders the coverage line in
  its own right; one carrying `NOT_COVERED` renders it too, and the rendered text is
  not an assurance.
- A request whose composed arguments carry a covered path with no model call is refused
  at `EgressBinding` construction — **no confirmation is ever built for it**, and the
  test asserts the absence of a confirmation rather than a denial.
- A declined confirmation sends nothing and records the `DENY`, with the same
  four-outcome discipline ADR-0148 §9 already fixes.
- An edit produces a second `CONFIRM` carrying the edited bytes, whose recorded digest
  differs from the first, whose binding carries the same `coverage`, and which the
  first decision does not authorise.
- A confirmation on `converse_spoken` speaks `SPOKEN_PARK_SENTENCE` and no part of the
  content, exactly as ADR-0207 §2 already requires.
- A `PermissionDecision` assembled by hand around a `CoverageUnrecordedBinding` is
  refused by `AuditTrail.record` with `AuditError`, so the shape cannot be minted into
  a trail and back-dated as history it is not.
- A `CONFIRM` **persisted** before `coverage` existed is not offered by
  `pending_confirmation`, no `Confirmation` is assembled from it at either site, and
  the step stays `AWAITING_APPROVAL` with its row intact — the shape ADR-0184 §5 gives
  the origin epoch, asserted over a row read back from storage rather than over a
  value constructed in the test.
- A decision recorded before `coverage` reads back as a `CoverageUnrecordedBinding`,
  renders its account, destinations and description as legible history, and `resolve`
  returns no `ALLOW` on it.

> **Normative.** No lane widens the relaxation while implementing it. §9's four
> conditions are conjunctive, and a lane that finds one of them awkward files an issue
> rather than dropping it.

### 16. Marking, review and ratification

This ADR is in **ADR-0089's marked regime**: the marked clauses are the whole of what
it obligates, and the prose beside them determines what they mean and supplies no
obligation of its own (ADR-0089 §3). Marking is forward-only, so nothing this ADR
cites is retro-marked (§5). What binds is **seventy-three clauses**: §1's three, §2's
three, §3's two, §4's eight, §5's three, §6's four, §7's two, §8's eleven, §9's four,
§10's four, §11's six, §12's three, §13's two, §14's eight and §15's ten. Each is a
block quote at column 0 preceded by a blank line, stating one obligation with its own
scope (§2); passages stating two separable obligations were split in drafting for that
reason. §13's first clause states the same bound by pointing here rather than by
restating this list, so the enumeration has one home and cannot drift out of step with
itself — which it twice did while this ADR was under review.

The Context's account of the tree, §12's argument about what the owner bought, §14's
ADR-0082 §1 classifications and every argument in this document are deliberately
unmarked: they are argument and attestation, which ADR-0089 §1 classifies as
non-normative however load-bearing.

**The ADR-0082 §1 records this ADR owes are made by this change, while it is
`Proposed`, and that is the corpus's own practice rather than a convenience.**
Architecture review asked twice for them to be deferred to a PR after ratification.
Three things decide it the other way. ADR-0082 §1 puts the judgement "in the later
ADR's text, which is where it is reviewed", and a record written in a later PR is a
record no reviewer of the decision ever saw. ADR-0165 §2 makes the ratification flip
**one ADR file and one changed line**, so the flip cannot carry them and a third PR
would be a second lane for one decision. And the practice is uniform: ADR-0230's own
authoring commit `6c148a29` wrote its records onto ADR-0092, ADR-0226 and ADR-0228 in
the same change, and ADR-0228's `Status` line has read "amended by ADR-0230" since —
written while ADR-0230 was `Proposed`. A record made by a `Proposed` ADR states what
that ADR decides, and its ratification is what makes the decision binding; the note on
ADR-0155 says so in terms, and §1's second clause is what makes the distinction have
no operational consequence in the meantime.

**Required reviews: adversarial *and* architecture.** This is a contract-surface change
in `CONTRIBUTING.md`'s sense on both available grounds — §4 decides `core/types.py`
surface, and the document moves the clause every egress decision in the corpus is
measured against. ADR-0155 declared both lenses for the decision this one answers,
ADR-0154 and ADR-0150 declared both for the neighbouring decisions on the same
boundary, and ADR-0015 §1 makes a prose-only PR owe them where the prose decides that
surface.

## Consequences

- **ADR-0155 §3's reserved fork is closed.** Arm (b) was taken by the owner and its
  ADR exists; the reservation stops being a question a reader has to hold open, and
  §3's second clause stops being the thing people reach for when they mean the third.
- **The assistant may draft outbound content from what it knows about its owner, once
  the surface is built.** That is the capability the interim cost and the owner named
  as a large limitation. It is bought with a per-call reading of the exact bytes, and
  with nothing else.
- **ADR-0155 §3's second clause acquires its first mechanism, and it is a construction
  refusal rather than a policy floor.** A verbatim store value in an egress span
  becomes unconstructable rather than merely forbidden, which is a strictly stronger
  posture than the one ADR-0155 §4 could describe — and it is the first time any
  clause of §3 is enforced by code rather than by review.
- **#1154 narrows rather than closes, and the remaining subject is stated.** The fact
  is recordable and recorded; what still nothing detects is a component that records it
  wrongly, which is the residue ADR-0146 §7's posture requires be named rather than
  claimed away.
- **A confirmation becomes larger and, for the first time, worth reading.** The
  approver sees the words. Nothing makes them read the words, and §12 says so in a
  marked clause rather than leaving the gap to be assumed shut.
- **A memory-drawn email cannot be approved by voice.** ADR-0207's park sentence is
  the whole spoken surface and this ADR does not widen it; a voice-only deployment
  waits for a screen. That is a real product cost of ADR-0199's audience rule and it is
  paid here rather than carved around.
- **The trail gains a third binding shape, and ADR-0184 §9's deferred payload version
  stays deferred.** §9's choice is made at the epoch §9 named and made the other way:
  `CoverageUnrecordedBinding`, because a version key names a schema and supplies no
  value for a row missing a required field. What the union buys is that every arm names
  the fact it does not have; what it costs is one more arm, and a fourth `core` field
  on a stored model puts §9's choice again — with three data points, and with the
  representability finding this loop produced already on the record.
- **The egress binding now carries two call-level facts and the corpus knows what each
  is for.** Whether the material selected into the planning call was marked as external
  (ADR-0181), and where what this call would send came from (this ADR). The per-span
  axes are unchanged — ADR-0146's discloser marker, and ADR-0150 §6's tier residue,
  which is still under-answered for a moved value and which §13 says this ADR does not
  answer.
- **Revisit trigger.** The first measurement of how often an approver's confirmation
  carries a body large enough that a surface would want to abbreviate it. §8 forbids
  abbreviating; the moment a real deployment finds that unusable is the moment this
  decision's central bet — that the reading is what makes the send lawful — is being
  tested against a person rather than against a corpus, and a later ADR should have the
  measurement rather than the intuition.
