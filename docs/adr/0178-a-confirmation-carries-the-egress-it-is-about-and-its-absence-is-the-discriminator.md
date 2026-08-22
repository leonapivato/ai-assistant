# 178. A confirmation carries the egress it is about, and its absence is the discriminator

- Status: Proposed
- Date: 2026-08-22

- **This closes #1366**, the contract question `track:web-client` milestone 15's
  control-surface decision filed rather than answered (batch #1365, #1230).
  ADR-0148 §8's fourth clause — that what is put to the user for a `CONFIRM` on an
  egress call names the connected account's **identity**, the canonical destination
  set **in both forms**, and the **payload description** — is met by no surface in
  this tree, the command line included, and cannot be met from `Confirmation`'s five
  members. This decision supplies the members.
- **It decides `core/types.py` surface, so golden rule 5 is engaged.** One member on
  `Confirmation`, two new types beside it. **No implementation lands with it** — no
  `src/`, no `tests/` — and it is ratified and merged as its own PR before anything
  implements against it (ADR-0015 §5). It decides no `core/protocols.py` surface: no
  method is added, removed or re-signed (§11).
- **Its required review set is adversarial *and* architecture**, the set
  `CONTRIBUTING.md` requires of "the ADR deciding that surface", and the set
  ADR-0085, ADR-0102, ADR-0149, ADR-0150 and ADR-0151 each took for the same reason.
- **It moves `PROTOCOL_VERSION` from 9 to 10, and that is stated up front rather
  than found by the implementing lane** (§6). ADR-0124 §9's second limb, on
  ADR-0170 §3's precedent exactly: `Confirmation` is `extra="forbid"` and
  `wire/surface.py`'s `return_adapter` validates a result against the method's
  declared return annotation, so a version 9 client handed a version 10
  `Confirmation` fails on the new member and a confirmation it asked for arrives as
  a decode error.
- **It partially supersedes three ADRs, and every record rides this change**
  (ADR-0070 §1, ADR-0082 §1, ADR-0083 §15): **ADR-0177 §8's four-member rendering
  clause and its no-claim clause**, each only as it reaches a surface rendering a
  `Confirmation` that carries the member §1 adds; **ADR-0085 §4's Group A field row
  for `Confirmation`**, which enumerates five fields where there are now six; and
  **three clauses of ADR-0150 §3** — its member-type, account-member and
  derived-property clauses — only as they reach the canonical destination set a
  `Confirmation` names — the one place ADR-0150 §3 and
  ADR-0148 §8's fourth clause cannot both be obeyed, resolved in §8's favour at that
  surface and nowhere else. §12 shows the working for all three.
- **One amendment rides it and changes no decision**: a dated header note on
  ADR-0148 recording that §8's fourth clause now has a carrier. Not a supersession —
  §8's obligation is word-for-word what it was, and a reader acting on it acts
  identically before and after (ADR-0070 §1's second limb).
- **It discharges ADR-0177 §8's precondition on its own terms, on both limbs — on
  ratification, not on proposal.** §8 blocks a browser confirmation surface "before a
  **ratified** decision supplies what ADR-0148 §8's fourth clause requires … **or**
  supplies a discriminator by which a surface can refuse an egress confirmation it
  cannot render". This supplies the content (§2) *and*, as a consequence of the shape
  rather than as a second mechanism, the discriminator (§4). Discharge by satisfaction
  is not amendment: §8's clause names its own firing condition and this meets it —
  **when this document is ratified and merged, and not while it stands `Proposed`**
  (§8).
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-22**, the
  durability form ADR-0100 established. Refs #1366, #1365, #1230, #1159.

## Context

### The clause, and the five members that cannot meet it

ADR-0148 §8's fourth clause is the content rule for an egress confirmation:

> What is put to the user for a `CONFIRM` on an egress call names the connected
> account's **identity** (§6), the canonical destination set in both forms (§2), and
> the payload description (§6). It names neither the connection reference nor a
> credential slot: neither is something a user can recognise an account by. A
> confirmation that names the tool and not the recipients is not a confirmation of an
> egress call.

`Confirmation` in `core/types.py` carries five members and `extra="forbid"`:
`tool_id`, `tool_description`, `parameters`, `reason`, `token`. Read against the
tree rather than against the corpus:

- `tool_id` and `tool_description` are `recorded.tool.id` and
  `recorded.tool.description`, from the `ToolDefinition` embedded in the recorded
  `CONFIRM` (`Engine._confirmation`).
- `parameters` is `turn.plan.steps[0].parameters` — the driven step's own arguments.
- `reason` is `recorded.ruling.reason`, and `ThresholdActionPolicy.decide` states in
  its own docstring that no rule there consults the parameters, so nothing derived
  from a payload reaches it.
- `token` is the opaque continuation ADR-0042 §4 fixes.

Everything the clause names lives on `EgressBinding` instead:
`BoundAccount.identity` for the account, `EgressBinding.canonical_destination_set`
for the set, `EgressBinding.spans` for the description (ADR-0150 §4, §10).
`EgressBinding` hangs off `ActionRequest` and `PermissionDecision`, and
`PermissionDecision` is exactly what ADR-0042 §6 forbids an adapter to read — which
is why `Confirmation` exists at all. The adapter cannot reach the facts by reading
harder; there is no route.

### Both renderers, checked rather than remembered

`interfaces/cli.py`'s `_render_confirmation` prints a heading, the tool id and
description, each entry of `parameters` as a bare `key = value` line, and the
reason. That is `Confirmation`'s four content members and nothing else. The flat
destination the user typed appears there incidentally, as an argument value; the
canonical form, the protocol tag and the connected account do not appear at all.
**#1159's exit test ran at that terminal**, and met §8's fourth clause no better than
a browser would.

ADR-0177 §8 is what stopped the gap acquiring a second surface. It decided the
browser CONFIRM prompt in full and then blocked shipping it: "No lane ships a
browser surface that answers a confirmation before a ratified decision supplies what
ADR-0148 §8's fourth clause requires … or supplies a discriminator by which a
surface can refuse an egress confirmation it cannot render." §11 named the shape
that would close it — "structural members on `Confirmation`, a promoted read of the
binding, or a discriminator — all `core/types.py`" — and put it here.

### What ADR-0150 §10 asks for that ADR-0148 §8 does not spell out

The content question is larger than the three nouns in §8's fourth clause, and
missing this would produce a contract that satisfies the letter and understates the
call. ADR-0150 §10's third clause:

> The confirmation ADR-0148 §8's fourth clause requires additionally names, for
> **every occurrence the binding carries**, the argument that occurrence was selected
> by. It is stated over occurrences and not over members of the derived set: one
> recipient named by `to` and again by `bcc` is **one** member and **two** disclosures,
> and a confirmation naming one argument for that member has understated the call.

So a member carrying only `canonical_destination_set` — the deduplicated derived
value — would be a contract that fails ADR-0150 §10 while passing ADR-0148 §8. What
the confirmation needs is the **occurrences**, from which the set derives, and the
argument each came from. Both of those already live on one value: `EgressSpan`
carries `argument`, `index` and a `destination` holding `protocol`, `supplied` and
`canonical`, and `EgressBinding.spans` is the ordered tuple of them.

### The facts are already in hand at both assembly sites, and that is what makes this cheap

`Engine._confirmation` builds a `Confirmation` from `disposition.decision` — the
recorded `CONFIRM` the runner already read back and carried on its disposition —
and `Engine._recovered_confirmation` builds one from the `PermissionDecision` the
trail returned for a durably-parked binding. **Both hold a whole
`PermissionDecision`**, so both hold `egress_binding` where there is one, and
neither needs a new read, a new store, a new seam or a new failure mode.

**#1366's worry about the recovery path does not hold, and this was checked.** It
asks "what a `pending_confirmations` recovery can carry, since the trail holds only
a `parameters_digest`". The digest bounds the *payload*, not the binding:
`PermissionDecision.egress_binding` is a stored field transcribed verbatim by
`from_request` (ADR-0150 §9), and `permissions/audit.py`'s `_revalidated` rebuilds
the whole decision through `PermissionDecision.model_validate` /
`model_validate_json`. So the binding round-trips durably, and **the recovery path
carries exactly the egress content the live path carries.** There is no reduced
recovered form to design, which removes the hardest thing #1366 anticipated.

### One fact this decision leans on, verified at the seam

`EgressBinder.bind`'s `parameters` argument is contracted as "The arguments the
`ActionRequest` will carry, **unaltered**. Nothing is amended, defaulted into them
or substituted for them: what comes back on the egress path is the **same** mapping
the binding was derived under". `StepRunner`'s `_requested` builds the request from
`bound.parameters`, and the plan step it passed in is the same step whose
`parameters` reach `Confirmation.parameters`. So a span's `(argument, index)`
locator indexes into the very mapping the confirmation already carries — the two
members describe one call rather than two, and §10 makes that a test obligation
rather than a hope.

### What this ADR is not allowed to settle

It may not reopen ADR-0148 §1's whole-call unit or §2's canonicalisation, may not
touch ADR-0042 §6, decides nothing about the credential's hop or the browser's
transport (ADR-0177 §3), and ships no code. §11 states the whole of it.

## Decision

We will add **one member** to `Confirmation`, carrying the egress facts ADR-0148 §8
and ADR-0150 §10 require, populated by the engine from the recorded decision;
**absent** on a non-egress `CONFIRM`, which is the discriminator ADR-0177 §8 named;
move `PROTOCOL_VERSION` to **10**; and bind every surface that renders a
`Confirmation` to render it.

### 1. `Confirmation` gains one member, and it is one nested value rather than four fields

> **Normative.** `Confirmation` gains exactly one field: `egress:
> ConfirmationEgress | None`. No other member of `Confirmation` is added, removed,
> renamed, re-typed or re-defaulted, and `extra="forbid"` and `frozen=True` are
> unchanged.

> **Normative.** The field carries **no default**. Every construction site states it,
> including a construction site building a non-egress confirmation, which states
> `None`.

**One nested value rather than four fields, for ADR-0150 §1's reason applied one
level up.** Four independent optional members — an identity, a destination set, a
span tuple, a flag — admit fifteen partial states of which fourteen name recipients
and no account, or an account and no description. ADR-0148 §8's fourth clause makes
those a *floor*, so an implementation that reaches a partial state is precisely what
the floor defends against. One value is either whole or absent, and the absent case
is a fact about the call rather than a state to reason about. This is the argument
`EgressBinding`'s own docstring makes, and it does not stop being true because the
consumer is an adapter instead of a policy.

**No default, against `PermissionDecision.egress_binding`'s precedent, and the
difference is who constructs the value.** `PermissionDecision.egress_binding`
defaults to `None` because `from_request` is its construction path and transcribes
it from the request — no caller can forget a field no caller fills. `Confirmation`
is constructed at two sites in `orchestration/engine.py`, in the canonical fakes, and
in every test that builds one, so a default here is exactly ADR-0150 §5's "a
defaulted field is what a lane forgets": an implementation that never wired the
binding through would get a well-formed non-egress confirmation for free, and its
egress prompts would look correct. Requiring the field costs one token at each site
and puts a reviewer's eye on every one of them.

**A member on `Confirmation`, not a promoted read of the binding.** #1366 offers
both. A second engine operation — `egress_for(token)` or similar — is a sixteenth
promoted method by ADR-0085 §3's count and a further round trip, and it creates a
state this decision exists to make unreachable: a surface holding a `Confirmation`
it has not yet fetched the egress for, able to render and answer it. A confirmation
whose recipients arrive separately is a confirmation that can be shown without them,
which is the sentence ADR-0148 §8 ends on. The facts are in hand at assembly; a
second call would fetch what the first already had.

### 2. What the member carries, and the three things it must not

> **Normative.** `ConfirmationEgress` is a frozen `core/types.py` model with
> `extra="forbid"` and exactly two fields, both required with no default:
> `account_identity`, the connected account's identity as the ruling fixed it; and
> `spans`, the binding's payload description — the same `tuple[EgressSpan, ...]` the
> binding carries, member for member and in the binding's own order.

> **Normative.** `spans` is the binding's own value and **not a second description
> derived beside it**. No lane builds a parallel span type for a confirmation,
> re-derives a description from `parameters`, filters, reorders, truncates or
> summarises the tuple, or omits a span. ADR-0150 §10's first clause — "no lane binds
> one artifact and shows another" — is the rule this discharges, and reuse is how it
> is discharged.

> **Normative.** `ConfirmationEgress` carries **no connection reference, no
> credential slot, no `SecretName` and no string identifying a keyring entry**, and
> no field is added to it through which one could travel. It carries no
> `transport_endpoint`. It carries no `BoundAccount`, and no lane substitutes one for
> `account_identity` on the ground that the type already exists.

> **Normative.** `account_identity` is typed as the identity is typed on
> `BoundAccount` — text that renders as something, byte for byte as supplied — and
> the value is transcribed unchanged. Nothing normalises, trims, truncates or
> case-folds it between the ruling and the surface.

**The excluded three are why this is a new type and not `EgressBinding` itself.**
Carrying the binding whole would be the smallest diff and is the wrong answer.
`BoundAccount.reference` is barred from the confirmation by ADR-0148 §8's fourth
clause in terms, and `BoundAccount`'s own field description says so: "Never shown to
the user — ADR-0148 §6 says it is not something an account can be recognised by, and
§8's fourth clause bars it from the confirmation." A contract that hands the adapter
the reference and forbids it to render it is a rule where a type will do, and it
hands a value across ADR-0042 §6's boundary that §6 exists to keep on the engine's
side. `transport_endpoint` is excluded on a different ground: ADR-0150 §7 constrains
its scheme, host, port and path not at all and routes what it must be to #83, so it
is a value no surface can say anything true about, and §8's fourth clause does not
ask for it.

**And `spans` is reused rather than mirrored, for the reason the exclusions are
enforced by type.** A confirmation-side span type would be a second shape of one
fact that must agree with the first, which is the failure ADR-0150 is named after
and the defect PR #1120's first three rounds found. `EgressSpan` carries nothing
§8 bars: `argument` and `index` are locators, `provenance`, `extent` and `tier`
describe without holding content (ADR-0150 §10's second clause: "It holds no
content"), and `destination` carries `protocol`, `supplied` and `canonical` — the
"both forms" ADR-0148 §2 requires. Reuse is what makes the shown artifact the bound
one.

**Nothing new is disclosed to the adapter by this member, and that is checkable
rather than asserted.** `Confirmation.parameters` already carries the call's whole
argument mapping, which is where the supplied destination forms and every payload
value already are. What `spans` adds is the *canonical* form, the protocol tag, the
provenance and the extent — facts about the arguments the adapter already holds —
plus the account identity, which §8 requires it to show. The disclosure moves in the
direction §8 asks for and in no other.

### 3. The canonical destination set is derived here, exactly as it is derived on the binding

> **Normative.** `ConfirmationEgress` exposes the canonical destination set as a
> **derived property** over its own `spans` and `account_identity`, computed by the
> rule `EgressBinding.canonical_destination_set` states: one member per distinct
> destination the spans carry, deduplicated, in that property's total order; and
> where the spans carry none, exactly one member — the connected account. It is
> **never empty** and it is **never stored**.

> **Normative.** Its members are `ConfirmationDestination`, a frozen `core/types.py`
> model with `extra="forbid"` and ADR-0150 §3's **two shapes and no third**: a
> *selected recipient*, carrying a protocol and a canonical form and no account
> identity; or *the connected account*, carrying an account identity and neither of
> the other two. Every other combination is refused at construction.

> **Normative.** For every `EgressBinding`, the set this property derives corresponds
> **member for member and in the same order** to the set
> `EgressBinding.canonical_destination_set` derives from the same spans and account —
> the two differing only in that the account member carries the identity here and the
> whole `BoundAccount` there. No lane ships a derivation that can disagree.

> **Normative.** No lane stores this set as a field, transmits it as one, or supplies
> it from outside. A surface receives the spans and computes it; a producer that sent
> a materialised set would be sending a value that could disagree with the
> occurrences it was computed from.

> **Normative.** A `ConfirmationDestination` is a **rendering value and never an
> authorising one**. No lane compares two of them to decide anything, matches one
> against a grant, a standing grant, a policy rule or a recorded decision, passes one
> to `PermissionDecision.authorises`, treats one as a `CanonicalDestination`, or
> carries one on an `ActionRequest`, a `PermissionDecision`, an `EgressBinding`, a
> grant record or an audit row. Its only consumer is a surface rendering the
> `Confirmation` it arrived on.

> **Normative.** This narrows **three** clauses of ADR-0150 §3, each **only** for the
> set a `Confirmation` names: its member-type clause ("A member of a canonical
> destination set is a `CanonicalDestination`…"), its account-member clause ("An account
> member carries the account **whole** … No lane reduces an account member to its
> identity"), and its derived-property clause ("ADR-0148 §2's canonical destination set
> is a single derived property of `EgressBinding`"), which this section makes a second
> property of the same shape on a second type. `EgressBinding`'s own derived set is
> untouched: its members stay `CanonicalDestination`, its account arm still carries the
> whole `BoundAccount`, its equality is still over both fields, and the set on that type
> is still the single derived property of it.

> **Normative.** Every other thing ADR-0150 §3's derived-property clause says is
> **adopted rather than replaced** and binds here too: never a stored field, one member
> per distinct destination the spans carry, exactly one member — the account — where the
> spans carry none, never empty, the same total order, and never accepted from a caller.
> Two computations of one rule, and no second rule.

**Derived rather than stored is the same decision `EgressBinding` took and for the
same reason, and it also happens to be free on the wire.** A stored set is a second
representation of one fact, and the two disagreeing is authoritative rather than
cosmetic. Here the disagreement would be worse than on the binding, because the
binding is compared by `authorises` and the confirmation is compared by a human: a
set that disagreed with the occurrences beside it would put a recipient on screen
that the call does not send to, or hide one it does. And because a Python property
is not a pydantic field, nothing about it reaches the frame — the wire carries the
occurrences once, and both ends compute the same set from them.

**A third type rather than reusing `CanonicalDestination`, and this is where two
ratified clauses actually meet.** (§12 records all three §3 clauses this narrows; the
argument below is about the one that carries the safety reason.) `CanonicalDestination`'s account arm carries a whole
`BoundAccount`, which carries `reference` — and **ADR-0148 §8's fourth clause bars the
connection reference from the confirmation in terms**, while **ADR-0150 §3 requires an
account member to carry the account whole** and says in as many words that "No lane
reduces an account member to its identity". Both are ratified, and at this one surface
they cannot both hold: a confirmation naming ADR-0148 §2's set either carries a member
with a reference in it or carries a reduced member. This decision resolves that in
ADR-0148 §8's favour **at the confirmation and nowhere else**, and records the
narrowing on ADR-0150 rather than leaving a reader to find it (§12).

**Why the reduction is safe here and would be unsafe on the binding, which is what
ADR-0150 §3's clause is actually about.** §3 gives its own reason for the whole
account: "an identity alone is shared by two connection records the moment one account
is connected twice, and a reference alone survives its own re-provisioning to a
different account, so either alone is a destination that two different accounts can
satisfy." That is a statement about **comparison** — `PermissionDecision.authorises`
compares whole values (ADR-0150 §9), a standing grant covers what it compares, and an
ambiguous member there would let one account's authorisation cover another's. A
confirmation's set is compared by nobody: it is rendered, read by a person and
discarded; the authorisation stays the binding's, and `resume` binds the answer to one
parked decision by its token rather than by anything the surface saw. The clause above
is what keeps that true by construction rather than by observation — a
`ConfirmationDestination` is forbidden every comparison and every carrier that would
make its ambiguity matter. **Nothing about `EgressBinding`'s set changes**, so the
hazard §3 names stays closed exactly where §3 closed it.

**And the reduction gives up less than it looks like.** `BoundAccount`'s own field
description says the reference is "Never shown to the user", so the whole account was
never renderable at this surface in the first place; what the reduced member drops is a
value the surface was already forbidden to display. What it keeps is the fact ADR-0148
§8's fourth clause names, and `BoundAccount.identity`'s description says why that is the
renderable one: it is "Visible text because ADR-0148 §8's fourth clause shows it to the
user at the moment they decide".

**The account substitution is inherited whole, including its caveat.** Where the
spans carry no destination the set is the account, which is ADR-0148 §2's third
clause and is why the property is never empty. `EgressBinding`'s own docstring
records that this is conditional on the spans being complete and that `core` cannot
check completeness — ADR-0150 §11 routes that to surface (b). Nothing here narrows
that: **no lane reads an account-only set on a confirmation as evidence that the
call selected no recipient**, exactly as no lane may read it that way on the binding.

### 4. Absent, not empty — and the absence is ADR-0177 §8's discriminator

> **Normative.** A `CONFIRM` on a call for which the recorded decision carries no
> `egress_binding` carries `egress=None`. It does **not** carry a
> `ConfirmationEgress` with an empty span tuple, an empty-string identity, a
> placeholder identity, or any other populated-looking value. Absence is the state,
> and the type is what expresses it.

> **Normative.** `egress is None` is the discriminator ADR-0177 §8's second limb
> asks for: a surface may branch on it, and a surface that cannot render an egress
> confirmation may refuse **that** confirmation on it, rather than refusing every
> confirmation or rendering an egress one it cannot describe.

> **Normative.** What the discriminator states is that **the ruling was taken over an
> egress binding**, and nothing more. No lane reads `egress is None` as a warrant
> that the call transmits nothing, discloses nothing, or reaches no recipient. A
> surface that wants to say "this call sends nothing" does not have that fact and does
> not assert it.

**Absent rather than empty, because an empty value is a claim and an absent one is
not.** An empty span tuple is a well-formed payload description meaning "this call's
arguments are empty or hold nothing but empty JSON arrays" (ADR-0150 §4) — a
statement about a call that *is* an egress call. Using it for "not an egress call"
would give one shape two meanings and would leave `account_identity` with nothing
truthful to hold; an empty-string identity is worse, since the identity's own type
refuses text that renders as nothing, for the reason `BoundAccount` states: "an
identity that rendered as nothing would leave the confirmation with nothing to say
about whose account this is." `None` is the shape `PermissionDecision.egress_binding`
already uses for the same distinction, and using the same shape keeps the mapping
between them one-to-one.

**The third clause is the honest limit of the discriminator and is why it is stated
rather than assumed.** `egress` is populated exactly where the runner reached
`EgressBinder` and it returned a binding; it is `None` where the bound tool carries
no egress registration. That is a fact about the *seam's* view of the call, and
ADR-0150 §11 has already deferred to surface (b) the check that a
destination-bearing argument really yielded its occurrences. So the discriminator
supports the branch ADR-0177 §8 wanted and supports no claim about disclosure — the
same floor-and-gate shape ADR-0073 §4 uses for a citation it cannot resolve, and
ADR-0177 §8 applies to a rendering it cannot warrant.

### 5. Where the members come from: the recorded decision, in the engine, on both paths

> **Normative.** The engine populates `egress` from the **recorded** `PermissionDecision`
> the confirmation is about: `account_identity` from that decision's
> `egress_binding.account.identity`, and `spans` from its `egress_binding.spans`.
> Where `egress_binding` is `None`, `egress` is `None`.

> **Normative.** It is populated at **both** assembly sites and identically:
> `Engine._confirmation`, from the recorded decision the runner carried on its
> disposition; and `Engine._recovered_confirmation`, from the decision
> `AuditTrail.pending_confirmation` returned. Neither site derives a binding, reads a
> connection record, reads a store, calls a seam, or reads a clock to build it.

> **Normative.** No lane reaches this content by any other route. `ActionPolicy`,
> `EgressBinder`, `ToolInvoker` and the audit trail gain no member, no argument and
> no obligation for it; `interfaces/` gains no read of a `PermissionDecision`,
> a `ToolCall`, an `ActionRequest` or an `EgressBinding`; and ADR-0042 §6's
> prohibition stands word for word.

> **Normative.** A recovered confirmation carries the **same** egress content a live
> one carries for the same parked step. There is no reduced, digested or partial
> recovered form, and no lane ships one.

**This is the shape ADR-0042 §4 already chose, extended by one fact rather than
altered.** §4's whole argument is that the adapter is forbidden the registry, the
trail and the decision, so "the *engine* is what assembles them into the result".
The engine already assembles four content members out of the recorded decision at
these two sites; a fifth from the same object is the existing mechanism carrying one
more fact, not a new mechanism. It is also why **no fallible work is added between
parking a step and offering its token** (#287): `_confirmation`'s docstring records
that everything which could raise happens before `run` commits `AWAITING_APPROVAL`,
and reading two fields off a decision already in hand raises nothing.

**"The recorded decision" rather than "the request" is deliberate and is ADR-0148
§1.** The binding a confirmation shows is the one the ruling was taken over, fixed
before the ruling and not moving after it. Reading it from the recorded decision is
what makes the shown value the authorised value; reading it from anything the runner
still holds would be a second source that could differ.

**The fourth clause is what #1366 asked for and the answer is the easy one.** The
recovery path's binding is durable, whole and revalidated, so the recovered
confirmation is not a degraded rendering of a live one. A surface therefore needs
one renderer, not two, and `pending_confirmations` after a restart puts the same
question to the user that the turn did.

### 6. `PROTOCOL_VERSION` moves from 9 to 10, and here is the rule that says so

> **Normative.** The lane implementing this decision moves `PROTOCOL_VERSION` from
> **9** to **10**, in that same change, and records the ground in the constant's own
> commentary as every prior bump has.

> **Normative.** Nothing else under `wire/` changes for it. The connect exchange
> gains no member, no frame's encoding changes, no `FrameKind` is added, and the
> promoted surface's method set is untouched (ADR-0084 §3's permanent freeze, ADR-0085
> §3's fifteen-plus signatures). A result payload takes the shape of the method's own
> declared return annotation (ADR-0085 §10), so the member crosses without a second
> declaration and nothing transcribes it into a wire-side schema.

> **Normative.** A version 9 peer and a version 10 peer do not interoperate, and no
> lane adds a compatibility shim, an optional-member negotiation, a per-member
> capability flag or a lenient decode to make them. ADR-0084 §3's exact-match
> handshake is the mechanism, and the refusal naming both versions is the intended
> user-visible outcome.

**ADR-0124 §9's second limb, and it bites rather than merely applying — verified in
the tree.** The rule is "a change to a wire-carried `core` type that makes a value
one peer emits invalid for the other, whether the change widens or narrows the
type". `Confirmation` sets `extra="forbid"`; `wire/surface.py`'s `return_adapter`
builds a `TypeAdapter` over the method's declared return annotation and the client
validates every result through it; and `wire/codec.py`'s `project` renders a model
by `model_dump()`, which includes a `None` member rather than omitting it. So a
version 10 hub emits `"egress": null` on **every** confirmation, egress or not, and a
version 9 client fails with `extra_forbidden` on it — a confirmation it asked for
arriving as a decode error. Both delivery routes are affected, because
`Confirmation` reaches a client on `TurnOutcome.step.confirmation` (`converse`,
`converse_streaming`) and as the element type of `pending_confirmations`.

**ADR-0170 §3's bump is the precedent and it is the same shape exactly.** That
change added `reply` and `reply_degraded` to `TurnOutcome`, moved the number from 7
to 8 on this same limb, and left the rest of `wire/` alone for this same reason.
ADR-0122's optional `FeedbackEvent.memory_kind` is the case ADR-0124 §9 itself cites
for a widening an old peer refuses. Nothing here is novel; what is novel is only
that the bump is stated in the deciding ADR rather than discovered by the lane.

**The operational cost is one redeployment and it is named rather than minimised.**
An installation running a version 9 hub does not answer a version 10 client and vice
versa, so the hub and its clients upgrade together — which is what ADR-0084 §3's
exact-match rule exists to make legible, and what ADR-0124 §9 calls "the honest
consequence rather than an oversight". The deployed hub of `track:web-client`
milestone 14 is in exactly that position and the milestone-15 implementation lane
carries the redeployment.

### 7. The floor every surface rendering a `Confirmation` now owes

> **Normative.** A surface that renders a `Confirmation` whose `egress` is present
> renders, **before it collects the user's answer**: the `account_identity`; every
> occurrence the `spans` carry, each with the argument it was selected by, its
> `supplied` form and its `canonical` form; and the payload description. A surface
> that renders the tool, the parameters and the reason and stops has not put ADR-0148
> §8's question.

> **Normative.** The canonical destination set is rendered **as the derived set**,
> from §3's property, and not inferred by the surface from the occurrences with a
> rule of its own. Where that set is the connected account — the spans carrying no
> destination — the surface names the account as the destination rather than showing
> no recipients.

> **Normative.** Occurrences are rendered **whole**: every span the tuple carries,
> none omitted, none truncated silently, and none ordered so as to hide one. One
> recipient named by two arguments is rendered as two disclosures, which is ADR-0150
> §10's third clause and the reason the occurrences travel at all.

> **Normative.** No surface reconstructs a `supplied` form from a `canonical` one, or
> presents a canonical form as the form the user or the model wrote. ADR-0148 §14
> names that reconstruction as a failure in terms; the binding carries both forms so
> that neither has to be guessed.

> **Normative.** No surface renders the payload description as though it were the
> payload. A span states an argument, a position, a provenance, an extent and
> sometimes a tier; it holds no content, and a surface that presented an extent as
> the text, or a `SYSTEM_SELECTED` marker as an assertion about what the text says,
> would be claiming a warrant the value does not carry (ADR-0073 §4's floor,
> ADR-0099 §4's before it).

> **Normative.** Every value this member carries is inserted into the surface's
> output as **data**, neutralised for that target on render, exactly as
> `Confirmation`'s existing members are (ADR-0042 §4, ADR-0175 §9). Being derived
> from a binding relaxes nothing: `argument` is a caller-influenced key (ADR-0150
> §13), and a `supplied` form is a string a model produced.

> **Normative.** A surface that renders a `Confirmation` whose `egress` is `None`
> owes none of the above and asserts none of it. It renders the four content members
> as it does today and makes no statement about recipients.

**Two surfaces owe this on the day it lands, and one of them is not the browser.**
`interfaces/cli.py`'s `_render_confirmation` is the surface #1159's exit test ran
against, and the clause it fails is ADR-0148 §8's, ratified since 2026-08-13. The
implementation lane closes both — the CLI because the breach is live, the browser
because ADR-0177 §8 blocks it until this lands. Stating the floor over "a surface"
rather than over either one is deliberate: the third adapter inherits it without a
third decision, which is the form ADR-0073 §4 and ADR-0139 §3 already use.

**Rendering the set *and* the occurrences is not redundancy.** They answer different
questions. The set is what the policy ruled over and what §8's fourth clause names;
the occurrences are what ADR-0150 §10 requires so the user can tell `to` from `bcc`.
A surface showing only the set has hidden a disclosure; a surface showing only the
occurrences has shown a list the user must deduplicate in their head to know how many
recipients there are. Both, and the arithmetic is done by `core`.

### 8. What ADR-0177 §8 now says, and what stays exactly as written

> **Normative.** ADR-0177 §8's rendering clause — "carrying all four of its content
> members — `tool_id`, `tool_description`, `parameters` and `reason`" — is replaced,
> only as it reaches a surface rendering a `Confirmation` that carries §1's member.
> A browser turn that parks renders **all** of that confirmation's content members,
> which are now five, and §7 above governs the fifth.

> **Normative.** ADR-0177 §8's no-claim clause — "**The surface does not claim that
> what it rendered is ADR-0148 §8's confirmation content**" — is replaced on the same
> scope. A surface that has rendered §7's floor **has** rendered §8's content and may
> say so. Its three sub-clauses are **not** replaced and bind unchanged: the rendered
> arguments are still not the canonical destination set, a flat destination appearing
> among the parameters is still not a canonical one, and a connected account the
> surface was not given is still one it may not name — that last now being a clause
> about a `Confirmation` whose `egress` is `None`.

> **Normative.** ADR-0177 §8's precondition is **discharged rather than replaced**, on
> its own stated firing condition, and it is discharged **by this ADR's ratification
> and merge and not before**. While this document stands `Proposed`, §8's block on a
> browser surface that answers a confirmation is unaffected and no lane cites this
> section as lifting it. Once it is ratified and merged, no further ADR is owed before
> that surface ships, and the browser lane's remaining obligations are §8's other
> clauses plus §7 above.

> **Normative.** Everything else in ADR-0177 §8 binds unchanged: the token relayed
> opaquely and parsed by nobody; `resume` answered with `approved` and nothing else,
> `timeout` staying the gateway's; every value inserted as text through the
> document's own text node; `parameters` rendered whole; and `pending_confirmations`
> as the one recovery route.

**The precondition is discharged by satisfaction and that is not a supersession —
and satisfaction means ratified, which is why the clause says so.** ADR-0177 §8 blocks
the surface "before a **ratified** decision supplies…", and ADR-0165 makes ratification
a commit of its own after the required reviews are green. A document that called itself
the ratified decision while standing `Proposed` would be asserting the very fact the
gate turns on, and a lane reading only that sentence could ship against a proposal that
was later withdrawn (ADR-0127's path is live). So the clause is written against the
event rather than against this document's intent.
§8 wrote its own firing condition — "before a ratified decision supplies what
ADR-0148 §8's fourth clause requires … or supplies a discriminator" — and a clause
that names the event which ends it is not amended by that event. This is the
treatment ADR-0177 §12 itself gave ADR-0151 §14 ("satisfied rather than relaxed")
and the treatment ADR-0083 §15 fixes for a deferral discharged by the milestone it
names.

**The two replaced sentences are replaced and not merely narrowed, because a reader
holding only them builds the wrong surface.** "All four of its content members" is a
count, and after §1 it is a count of five; a browser built to it renders an egress
confirmation without its recipients, which is the sentence ADR-0148 §8 ends on. And
the no-claim clause was written for a surface that *could not* have the content; a
surface that now has it and still refuses to say so would be telling the user their
confirmation is less than it is. Both are ADR-0070 §1's first limb.

**The three sub-clauses surviving is the load-bearing half.** ADR-0177 §8's argument
for them — "A browser rendering `to = alice@example.com` beside a heading that says
'recipients' would be asserting that the user is looking at the bound canonical set,
when what they are looking at is the argument the model produced before binding" — is
untouched by this decision. `parameters` is still the pre-binding arguments; the
canonical set now arrives *beside* it rather than instead of it, so the confusion
those clauses forbid is if anything easier to make. They stay.

### 9. The size limit does not move and this is not a new worst case

> **Normative.** ADR-0085 §8's figures are untouched: the contract limit stays
> `hub_max_frame_bytes - 512`, applied to the whole serialised payload; §8b's
> 512-byte envelope reserve is unchanged and is not recomputed; and §8d's 1024-byte
> floor stands. No lane adds a second limit, a per-member bound, or a truncation rule
> for this member.

> **Normative.** No lane resolves an over-limit confirmation by omitting spans,
> abbreviating a canonical form or dropping the account identity. A payload over the
> limit is refused as any other is, and a surface that received nothing renders
> nothing rather than rendering a partial confirmation.

**The member adds a term and does not add a factor, which is the distinction §8f
turns on.** §8f's answer to "which payload is largest" is `beliefs()`, because its
evidence payload is a *product* — beliefs × citations × content. A confirmation's
egress member is bounded by the call's own arguments: at most one span per top-level
key plus one per array element, each a handful of scalars and at most one destination
whose two string forms are already substrings of values `parameters` carries in the
same payload. So the payload of an egress confirmation roughly doubles and stays
linear in the arguments that were already there. Nothing multiplies, and the belief
page remains the worst case §8f names.

**The second clause exists because truncation is the tempting fix and it is the one
that breaks the floor.** §7 forbids a surface from silently truncating what it
renders; this forbids the engine from silently truncating what it sends, which is
where the pressure would actually land if a large recipient list met a small
`hub_max_frame_bytes`. A confirmation missing recipients is worse than a confirmation
that did not arrive, because only one of the two is visible to the user.

### 10. What the implementing lane owes, clause by clause

The lane is `core/types.py` plus the engine, the CLI and `wire/envelope.py`'s
constant — one contract change with its adaptation, briefed after this merges.
Obligations, each traceable to a clause above:

- **§1.** A test that `Confirmation` carries exactly six fields and that the sixth is
  required: constructing one without `egress` raises, and constructing one with an
  unknown member still raises (`extra="forbid"` unchanged).
- **§2.** A test that `ConfirmationEgress` refuses an extra member and refuses a
  missing one; a test that its `spans` value is **equal** to the source binding's
  `spans`, tuple for tuple, for a binding with several arguments and several array
  elements; a test that no field of `ConfirmationEgress` or
  `ConfirmationDestination` is named or typed for a connection reference, a
  transport endpoint, a `BoundAccount` or a `SecretName` — asserted over
  `model_fields`, so a seventh field cannot be added unnoticed.
- **§2.** A test that `account_identity` refuses text that renders as nothing, and
  that a value carrying leading, trailing or interior whitespace survives byte for
  byte.
- **§3.** The correspondence test, which is the clause that would otherwise rot:
  for a set of bindings spanning no destination, one destination, several
  destinations, an aliased pair that deduplicates, and destinations across the
  ordering boundary, `ConfirmationEgress`'s derived set corresponds member for
  member and in order to `EgressBinding.canonical_destination_set` from the same
  spans and account, the account member differing only by carrying the identity.
- **§3.** A test that the derived set is never empty, including for a binding whose
  spans carry no destination, where it is exactly the account; and a test that
  `ConfirmationDestination` refuses every combination but the two shapes.
- **§4.** A test that a non-egress `CONFIRM` yields `egress=None` — asserted on the
  `Confirmation` the engine builds, not only on the type — and a test that no code
  path constructs a `ConfirmationEgress` with an empty span tuple standing for a
  non-egress call.
- **§5.** Engine tests on **both** sites: a parked egress `CONFIRM` from `converse`
  carries the recorded decision's identity and spans; the same parked step recovered
  through `pending_confirmations` after the handle table is emptied carries the
  **same** values, asserted by equality against the live one rather than field by
  field. This is the clause #1366 was least sure of and the one a later change is
  most likely to break.
- **§5.** An architecture test that `interfaces/` still imports no subsystem concrete
  module and reads no `PermissionDecision` — `lint-imports` already carries the
  first, and the CLI change must not acquire the second.
- **§6.** A test pinning `PROTOCOL_VERSION == 10`, and a round-trip test that a
  `Confirmation` carrying an egress member survives `project` → canonical JSON →
  `return_adapter` validation with every member intact, including a `tier` of `None`
  and an `index` of `None`.
- **§7.** CLI rendering tests: an egress confirmation's output names the account
  identity, every occurrence with its argument and both forms, and the derived set;
  the account-only case names the account as the destination; a confirmation whose
  `egress` is `None` renders as it does today. Values carrying control sequences or
  markup are neutralised on the way out, as `_safe` already does for the existing
  members.
- **§9.** No test asserts a size figure that this change did not move; a lane finding
  itself editing one has changed something §9 says is unchanged.

**The conformance suite is where the correspondence obligation belongs**, not a
single unit test beside the model, because §3's clause binds any producer of a
`ConfirmationEgress` and the canonical fake in `ai_assistant.testing` is one
(`CONTRIBUTING.md` → "Adding a Protocol"). This adds no Protocol, so no triad is
owed; what is owed is that the existing engine fake builds a `Confirmation` the same
way the real engine does, and that the suite says so.

### 11. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` surface. No method is added
> to `AssistantEngine`, none is removed, and no method's arguments or return
> annotation changes. `EgressBinder`, `ActionPolicy`, `ToolInvoker`, `ToolRegistry`
> and `AuditTrail` are untouched.

> **Normative.** It changes no clause of ADR-0148. §1's whole-call unit, §2's
> canonicalisation and its third clause, §4's no-movement rule, §5's resolution
> route, §6's four facts and §8's own four clauses are used as given, and §8's fourth
> clause is **obeyed rather than read more widely**.

> **Normative.** It changes no clause of ADR-0042. §4's assembly rule is the
> mechanism it extends by one fact; §6's prohibition on an adapter reading a
> `PermissionDecision`, a `ToolCall` or the token's internals is unchanged, and no
> clause here is a route around it.

> **Normative.** It decides nothing about the credential's hop from a device to the
> hub (ADR-0151 §13), nothing about ADR-0177 §3's browser-to-gateway hop, and
> nothing about which transport a confirmation surface is reached over.

**Deferred, by name, each with the condition that fires it:**

- **What a policy does with the description.** ADR-0150 §6 defers the declaration
  vocabulary by which a tier is established, and ADR-0150 §11 defers surface (b)'s
  refusals to the seam. This ADR moves a description to a *renderer* and takes no
  position on either; it fires with those decisions, not with this one.
- **#57's richer audit artifact.** ADR-0150 §10's last clause already rules that such
  an artifact does not replace the description and that this value stays what is
  bound, compared, transcribed and shown. A surface built to §7 is unaffected when
  that ADR lands, which is the point of that clause.
- **#83's transport-endpoint question.** Untouched, and §2's exclusion of
  `transport_endpoint` is not a reading of it: the endpoint is excluded because §8's
  fourth clause does not ask for it, not because #83 is unsettled.
- **A per-surface confirmation layout, ordering or vocabulary.** §7 fixes what must
  be rendered and what must not be claimed, and fixes no words, no order and no
  markup. ADR-0150 §10's fourth clause is explicit that "two consumers may render one
  description differently"; that stands.
- **Whether a surface may refuse to render an egress confirmation at all.** §4 gives
  it the discriminator to do so; whether a particular surface *should* is that
  surface's decision. ADR-0177 §8's browser lane, having §7's content, has no reason
  to.
- **`Confirmation`'s five existing members.** None is re-typed, re-described or
  re-sourced. In particular `parameters` stays the driven step's own arguments,
  pre-binding, and §7's surviving sub-clauses are what keep a surface from calling
  them something else.
- **Any second consumer of `ConfirmationEgress`.** It is a confirmation's member. No
  lane routes a policy, a store, a trace or a notification through it, and a
  consumer wanting the binding reads the binding.

### 12. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**Six clauses across three ADRs are superseded and this change writes every
record** — each ADR's
`Status` line and an appended dated note, in the scope the line names.

- **ADR-0177 §8's rendering clause**, in the words §8 above quotes, and **ADR-0177
  §8's no-claim clause**, each only as it reaches a surface rendering a
  `Confirmation` that carries §1's member. A reader holding only §8 builds a browser
  prompt that renders four members and refuses to claim it has met ADR-0148 §8 —
  after this decision, a prompt that omits the recipients and understates itself.
  That is ADR-0070 §1's first limb in both directions. **Nothing else of §8 moves**,
  and §8's own precondition is discharged on its own terms rather than replaced,
  which §8 above states and this section does not restate as a supersession.
- **ADR-0085 §4's Group A field row for `Confirmation`**, which reads `tool_id:
  Identifier`, `tool_description: str`, `parameters: FrozenJsonMapping`, `reason:
  str`, `token: ContinuationToken`. A reader holding only §4 builds a five-field
  model and an implementation generated from that row rejects a conforming hub's
  frame. ADR-0107's partial supersession of §4's rows for `Belief` and
  `BeliefSummary` is the precedent for treating a row this way, and this follows it.
- **ADR-0150 §3's member-type clause and its account-member clause**, each only as
  they reach the canonical destination set a `Confirmation` names. "A member of a
  canonical destination set is a `CanonicalDestination`…" and "An account member
  carries the account **whole** … No lane reduces an account member to its identity"
  are both ratified, and at a confirmation they meet ADR-0148 §8's fourth clause, which
  bars the connection reference from that surface in terms. A reader holding only §3
  either carries the reference to an adapter — breaching ADR-0148 §8 and handing across
  ADR-0042 §6's boundary a value §6 exists to keep behind it — or refuses to build the
  set at all, leaving §8's fourth clause unmeetable. That is ADR-0070 §1's first limb,
  and §3 above is the replacement: `ConfirmationDestination`, identity-only on its
  account arm, forbidden every comparison and every carrier. **`EgressBinding`'s own
  set is not touched** — its members stay `CanonicalDestination`, its account arm
  carries the whole `BoundAccount`, and §3's stated hazard ("either alone is a
  destination that two different accounts can satisfy") is a fact about comparison,
  which is exactly what the replacement forbids.
- **ADR-0150 §3's derived-property clause**, "ADR-0148 §2's **canonical destination
  set** is a single **derived property** of `EgressBinding` and is not a stored field",
  on the same scope and **only as to where that property may live**. A `Confirmation`
  cannot reach an `EgressBinding` — ADR-0042 §6 is why — so a reader holding only this
  clause concludes the set is unavailable at a confirmation and builds a surface that
  cannot name it. §3 above puts a second property of the same shape on
  `ConfirmationEgress` and **adopts everything else the clause says**: never stored, one
  member per distinct destination, the account where the spans carry none, never empty,
  the same total order, never accepted from a caller — and requires the two to
  correspond member for member. Two computations of one rule, not two rules, which is
  the distinction ADR-0150's own title turns on. **Every other clause of ADR-0150 §3
  stands**: the occurrence rule, the function-of-supplied-form refusal, the
  no-canonicalisation-in-`core` rule, the two-shape refusal itself, the never-empty
  rule, the total order, the field-wise equality, ADR-0148 §8's third floor and the
  conditional account substitution.

**One amendment is recorded and changes no decision**, in ADR-0070 §1's second limb —
an ADR reconciled with a fact that postdates it, such that a reader acting on it acts
identically before and after. It rides this change as an appended dated header note.

- **ADR-0148** gains a note recording that §8's fourth clause now has a carrier: the
  identity, the destination set in both forms and the description reach the surface as
  `Confirmation.egress`, populated by the engine from the recorded decision. §8's
  obligation is word for word what it was — this decision changes what a surface *can*
  do, not what it *must* — so a reader acting on §8 acts identically, and §11 of ADR-0148
  is the section that flagged this surface as owed rather than a clause that moves.

**No record is owed on:**

- **ADR-0085 §3, §5, §8, §10.** §3's signatures are untouched and the method set is
  unchanged. **§5's walk gains an edge and its conclusion does not move**: `Confirmation`
  now reaches `ConfirmationEgress`, which is authored in `core/types.py`, so §5's own
  stated rule — "follow a field's annotation to its declared type, stop at anything
  already in `core`" — terminates there, and "the twenty-four that promote" is a count
  of types moving out of `orchestration`, which none of these do. §8's figures are
  unmoved (§9) and §10's per-method mapping is unchanged.
- **ADR-0084 §3 and §4.** Its permanent freeze is respected — no change to the length
  prefix, the codec or the connect frame's version member, and no member added to the
  connect exchange — and §4's rule that the size limit is contract rather than transport
  is used as given.
- **ADR-0124 §9.** **Applied, not amended.** §6 above is the rule's second limb reaching
  a change, and §9's own closing clause — that compliance "is a review obligation on any
  change to `core/types.py`" — is what this ADR discharges in advance for its
  implementing lane. #891's mechanical check is unaffected and is not a precondition here.
- **ADR-0150 §§1–2, §§4–13.** Used as given, and §10 is used most heavily: its first
  clause is what §2 discharges by reuse, its second is why the description can be shown
  at all, its third is what §7's occurrence clause meets, and its fourth is why §7 fixes
  no rendering. §4's span identity and structural invariants are unchanged, §5's carried
  provenance is transported and not re-derived, §7's exclusions are the reason §2
  excludes the reference, §9's `authorises` conjunct and its deep-copy transcription are
  untouched, and §11's deferrals to surface (b) are restated as standing rather than
  discharged. §3 is the one section that moves, and it is recorded above.
- **ADR-0042 §4 and §6.** §4's assembly rule is used exactly as written — the engine
  assembles because the adapter may not read the decision — and its enumeration of
  confirmation content was already exceeded for an egress call by ADR-0148 §8's fourth
  clause in 2026-08-13, which left no record on ADR-0042 and needed none. §6's forbidden
  list is unchanged and §5's clause is untouched.
- **ADR-0052 §1 and §3.** Used as given. `pending_confirmations` stays the recovery read,
  each recovered confirmation is rendered before it is answered, and §5's fourth clause
  above makes the recovered value equal to the live one rather than changing what
  recovery is.
- **ADR-0021 §1, §3, §4, §5.** Untouched. No ruling is authored anywhere new, the
  approver is unchanged, the trail's append-only rule is unchanged, and §5's floors are
  neither widened nor relaxed. `PermissionDecision` gains no field.
- **ADR-0152 §§1–15.** Untouched. The seam's two members, its one read, its detachment
  rule and its refusals are all unchanged; this decision reads the binding *after* the
  ruling, from the record, and adds no argument, no return member and no obligation to
  either member of `EgressBinder`.
- **ADR-0146 §1, §2, §5.** Used as given. Provenance rides the span and is carried
  rather than derived; §7's fifth clause forbids a surface from reading a provenance
  marker as an assertion about content, which is §2's fail-closed discipline at a
  renderer rather than an extension of it.
- **ADR-0073 §4 and ADR-0099 §4.** Used as given, and §7's fifth and last clauses are
  those floors applied to a confirmation, which is the use ADR-0177 §8 already made of
  ADR-0073 §4.
- **ADR-0175 §9.** Used as given. Its rendering obligation binds this member exactly as
  it binds a reply and the existing four, and §7's neutralisation clause is that
  obligation restated at the value it now reaches, not a relaxation for a derived one.
- **ADR-0054.** Not engaged. This decision adds no `Settings` field and moves none.
  `hub_max_frame_bytes` is read and not changed (§9).
- **ADR-0165.** Its exempt commit shape is available to this PR's ratification exactly
  as to any other, and nothing here is a reading of it.
- **Golden rules 1, 2, 3 and 5.** Rule 2 is why both new types are authored in
  `core/types.py`. Rule 3 is what §5's third clause and §7 keep true: the adapter still
  only renders and adapts. Rule 5 is engaged and answered by this ADR existing and
  merging first. Rule 1 is untouched: no subsystem imports another for this.

## Consequences

**ADR-0148 §8's fourth clause becomes meetable, and then met at two surfaces.** The
CLI's breach — live since the clause was ratified, and the reason #1159's exit test
passed against a prompt that named the tool and not the recipients — is closed by the
implementing lane. ADR-0177 §8's block on the browser confirmation surface lifts, and
`track:web-client` milestone 15's exit test, which #1159 item 5 puts a real CONFIRM in
front of, becomes reachable from a browser.

**Every installation upgrades hub and clients together, once.** `PROTOCOL_VERSION` 10
does not interoperate with 9, by design, and the milestone-15 lane carries the
redeployment of the hub #1230's milestone 14 left running. The failure mode if someone
forgets is the one ADR-0084 §3 built: a handshake refusal naming both versions, not a
silent divergence.

**A confirmation's payload grows and stays linear.** An egress confirmation carries the
call's arguments and a description of them; §9 shows this adds a term rather than a
factor and moves no figure. A very large recipient list against a small
`hub_max_frame_bytes` is refused rather than truncated, which is a legible failure and
is the direction §9's second clause chooses deliberately.

**Two new `core` types is the ongoing cost.** `ConfirmationEgress` and
`ConfirmationDestination` are surface that must be kept in step with `EgressBinding`
and `CanonicalDestination`, and §3's correspondence clause is what makes the drift
detectable rather than silent. The alternative — reusing `CanonicalDestination` — was
cheaper by one type and would have put a connection reference on the adapter's side of
ADR-0042 §6.

**What would trigger revisiting this.** A second consumer wanting the binding at a
surface would be evidence that the member should have been the binding itself; §11
forbids routing one through this member precisely so that such a consumer arrives as a
new decision rather than as a widening. A #57 richer artifact landing would test
ADR-0150 §10's last clause rather than this one. And a surface finding that the derived
set and the occurrences are redundant in practice would be evidence against §7's
two-rendering rule — but ADR-0150 §10's third clause is a ratified reason they are not,
so that evidence would have to be about rendering rather than about content.

## Alternatives considered

**A promoted read of the binding, as a sixteenth engine operation.** #1366 offers it
and it is the shape that touches `Confirmation` not at all. Rejected because it creates
the state this decision exists to make unreachable: a surface holding a confirmation it
can render and answer before it has fetched the recipients. It also costs a method on
the promoted surface — ADR-0124 §9's *first* limb, so it bumps `PROTOCOL_VERSION` too —
a round trip, and a new failure mode when the second call fails after the first
succeeded. The facts are in hand at assembly; fetching them again is work to be able to
skip them.

**A discriminator alone.** ADR-0177 §8 admits it as a discharge: give a surface a way
to know it is looking at an egress confirmation and let it refuse. Rejected as a
*destination* rather than as a step — it leaves ADR-0148 §8's fourth clause permanently
unmet, converts the CLI's live breach into a permanent refusal to confirm egress calls
at a terminal, and would make #1159's exit test unpassable at any surface rather than
just at a browser. §4 supplies the discriminator anyway, as a consequence of the shape,
which is the outcome where both limbs of §8's precondition are met by one member.

**Carrying `EgressBinding` itself as the member.** The smallest diff, no new types, and
guaranteed agreement with the bound value. Rejected on §2's grounds: it hands the
adapter `BoundAccount.reference`, which ADR-0148 §8's fourth clause bars from the
confirmation in terms and which `BoundAccount`'s own field description says is never
shown to the user. A contract that carries a value across ADR-0042 §6's boundary and
then forbids rendering it is a rule where a type will do, which is the objection
ADR-0150 §1's fifteen partial states are the corpus's worked instance of.

**Four flat members on `Confirmation` — identity, set, spans, and a flag.** Rejected in
§1: fifteen partial states, of which fourteen name recipients and no account or an
account and no description, against a clause ADR-0148 §8 makes a floor.

**Leaving the derived set off the member entirely, and letting the surface work from
the occurrences alone.** It is the shape that touches ADR-0150 §3 not at all, and it is
the reason the supersession above was not taken lightly. Rejected on two grounds. The
deduplication is *information* — a user shown `to: alice@example.com` and `cc:
Alice@Example.com` cannot tell from the occurrences that those are one recipient, and
ADR-0148 §8's fourth clause names the **set**, not the occurrences, precisely because
"how many people is this going to" is the question a confirmation answers. And
somebody must deduplicate: with no derived value in `core`, the rule moves into
`interfaces/`, where two adapters would implement it separately and could disagree —
business logic in an adapter (golden rule 3, ADR-0042 §6) and a second derivation of
one fact (ADR-0150 §1). A variant that returned only the *recipient* members, with the
account-only case signalled by an empty tuple, fails harder: it is a value that
disagrees with `EgressBinding.canonical_destination_set`'s never-empty guarantee for
the same binding, which is the disagreement §3 above exists to make impossible.

**Storing the canonical destination set on the member.** Rejected in §3. It is a second
representation of a fact the occurrences already carry, and here a disagreement between
them would put a recipient on a screen that the call does not send to. Deriving it costs
nothing on the wire because a property is not a field.

**A confirmation-side span type, narrower than `EgressSpan`.** Considered on the ground
that a renderer needs less than a policy does. Rejected: `EgressSpan` already holds no
content, so there is nothing to narrow away, and a second shape of one fact is the
failure ADR-0150 is named after — with ADR-0150 §10's "no lane binds one artifact and
shows another" naming this exact instance of it.

**Defaulting `egress` to `None`.** Cheaper at every construction site and consistent with
`PermissionDecision.egress_binding`. Rejected in §1: an implementation that never wired
the binding through would produce well-formed non-egress confirmations for every egress
call and its prompts would look correct — ADR-0150 §5's argument for a defaultless
`provenance`, which is the same hazard at the same distance from the reviewer.
