# 152. The binding is derived at one seam, never supplied to it, and a call it cannot describe is refused

- Status: Accepted
- Date: 2026-08-14
- **Decides surface (b) of ADR-0148 §11** — the seam by which the egress binding
  is obtained from `tools/` before `ActionPolicy.decide` is reached. §11's second
  clause requires that surface to be decided in a contract ADR of its own,
  ratified and merged before anything implements against it (golden rule 5,
  ADR-0015 §5). This is that ADR, and it is the last of §11's two.
- **Consumes ADR-0150's value and redefines no part of it.** `EgressBinding`,
  `EgressSpan`, `EgressDestination`, `CanonicalDestination`, `BoundAccount`,
  `DestinationProtocol` and `DiscloserProvenance` are ADR-0150's, used exactly as
  it defines them — `EgressBinding` is **carried** by the value §1 returns, not
  amended by it. §2 fixes the `core` names this ADR is authorised to add, and
  they are six.
- **Discharges every obligation ADR-0150 §11 and §6 route here**, each in §5, §6,
  §7 or §9, and §14 maps them one by one so a reader can check the routing was
  spent rather than cited.
- **Decides ADR-0150 §11's undecided structural option** — whether a
  destination-bearing declaration is constrained to a decomposable flat shape.
  §4 takes the constraint, with the argument in text and the producer's flat
  declarations as the evidence ADR-0073 §4 asks for.
- **Designates nothing and authorises no byte.** ADR-0017 §2 reserves designation
  to a later ADR that names the seam module and attests each §3 condition is
  satisfied **in code**; this ADR supplies a seam. `tools/` still transmits
  nothing, and `send_email` is still registered nowhere.
- **No implementation lands with it.** No `src/`, no `tests/`, no
  `pyproject.toml`. §13 says what the implementing lane owes, and ADR-0150 §11's
  last paragraph puts the triad obligation here: surface (b) **is** a seam, so its
  Protocol, its shared conformance suite and its canonical fake ride with the
  primary production implementation as one lane (ADR-0137 §2).
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-14**,
  the durability form ADR-0100 established and ADR-0149, ADR-0150 and ADR-0151
  each applied. This decision rests most heavily on ADR-0150 and ADR-0148, and on
  ADR-0146 §2 and ADR-0145 §9 and §11.
- **Reads at most one thing, and ADR-0148 §6 is what obliges the read.** §10 fixes
  that this seam performs no network I/O, reads no clock and resolves nothing. Its
  whole read budget is one connection record — **exactly** one where the tool has an
  egress registration, for connectability and the account identity, and **none**
  where it has not, since there is then no reference to name one. ADR-0148 §11's unmarked "performs no
  I/O" is read narrowly against ADR-0148 §6's **marked** connectability clause,
  which names seam (b) and forbids carrying connectability over from an earlier
  moment; §8, §10 and §15 carry the whole of that reading.
- **Records owed on other ADRs: none, and §15 shows the working** rather than
  asserting it, including the three near misses — ADR-0037 §2's five-step sequence,
  §4's resume sequence, and ADR-0148 §11's no-I/O sentence — each of which a
  reviewer is entitled to contest by naming the sentence that becomes false. No
  `Status` line moves and no ratified text is rewritten anywhere.

## Context

### What ADR-0148 §11 fixed about (b), and what it left open

ADR-0148 §11 flags (b) as `core` surface the corpus does not have, forbids any
lane from adding it on that ADR's strength alone, and states why it is forced:

> **(b) is forced by §1's earliness, and it is the surface a reader is most
> likely to miss.** ADR-0037 §2 has `StepRunner`, in `orchestration`, build the
> `ActionRequest` from "the tool, the step's parameters and the step id". Under §1
> that request must already carry the whole binding, every part of which is
> integration-specific knowledge living in `tools/` — which `orchestration` may
> reach only through a Protocol (golden rule 1). Neither `ToolRegistry` nor
> `ToolInvoker` answers that question, and ADR-0029 §1 is explicit that how the
> callable is reached "is `tools/`-internal, and this ADR does not contract it".
> So a seam is genuinely missing.

It then fixes four properties and leaves the signature open: (b) is consulted
**before** the ruling and never after; it **performs no I/O**, so it cannot become
the resolution path §5 governs; it **refuses** rather than guessing (§1's third
clause); and its description is **deterministic** (§6). "A contract ADR that
satisfies those is free to choose the signature; one that does not is changing
this decision." §1, §5 and §10 below satisfy them and §15 checks each.

### What ADR-0150 routes here, and why each landed here rather than there

ADR-0150 decided surface (a) — the value — and routed to this ADR every check
whose triggering fact `core` cannot see. Its §11 lists five things (b) owes and
adds two refusals and a test; its §6 adds one more; and its §11's last
undecided clause is a structural option it declines to settle without a
declaration vocabulary in hand. The whole set is enumerated in §14.

They share one shape, and ADR-0150 §4's family paragraph names it: each check
depends on **the bound tool's declaration**, and the declaration vocabulary is
what ADR-0150 §6 deferred to this ADR precisely because "splitting it across two
ADRs would produce two half-decided keyword sets". `core` reads no declaration,
so `core` cannot perform any of them; this seam reads one, so it is the first
component with the mechanism. Routing them here was not a preference — it is
ADR-0146 §7's posture, "do not buy a bound from a mechanism that cannot carry
it", applied to a component that did not exist yet.

### The producer, and what it makes decidable

PR #1120 built the inert half of the first egress integration inside `tools/`:
`destinations.py` (the per-protocol canonicaliser), `destination_arguments.py`
(the destination-bearing declaration and `select_destinations`),
`payload_description.py` (the deterministic description builder) and
`send_email.py` (a `ToolDefinition` registered nowhere whose callable raises).
Its description carries eleven observations under "What this producer wants from
the contract surfaces"; ADR-0150 §14 maps all eleven, four of which it answered
and three of which it forwarded here — observations 6, 8 and 11.

The producer is what makes §3 and §4 decidable rather than guessed. It has four
declared facts per argument across two declarations (`DestinationArgument`'s
`protocol`, `multiple` and `required`; `PayloadArgument`'s `establishes_tier` and
`multiple`), and §3 finds that ADR-0150 §4 has since decided two of them, so the
vocabulary this ADR fixes is **two keywords**, not four. It also declares every
recipient argument as a flat array of strings, which is the evidence §4 spends.

### The failure this ADR is named after

ADR-0150 is named for two shapes that had to agree arriving separately. This one
is named for its neighbour: **a value that is derived in one place and accepted in
another**. PR #1120's round-1 blocker was `describe_payload` taking the
destinations as an argument beside the parameters they were supposed to come
from — "a caller could hand over an empty tuple, or one naming a recipient the
arguments never selected, and get back a description that passed every check in
this module". The repair was to derive them, and the module's docstring states
the general rule: "a recipient set handed in beside the arguments is bound by
nothing and re-derivable by nobody."

The same choice arrives here twice, once on each of this seam's two operations,
and it is answered the same way both times. Nothing is accepted that can be
derived; what genuinely cannot be derived — a span's recorded origin — is
carried, is never invented, and is the one thing §7 transcribes.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none. §16 records the regime.

The decision in one sentence: **one Protocol in `core/protocols.py` with two
operations, both of which derive the whole binding from the bound tool's
declaration and the call's arguments and accept none of it, refuse rather than
describe a call they cannot describe wholly, and fail with one error class that
no reader can mistake for a denial.**

### 1. One Protocol, two operations, and what each is given

> **Normative.** `core/protocols.py` gains **one** Protocol, `EgressBinder`, the
> seam by which `orchestration` obtains an egress binding — together with the call it
> was derived under — from `tools/` before `ActionPolicy.decide` is reached. It
> carries exactly two members and no others:

```python
@runtime_checkable
class EgressBinder(Protocol):
    async def bind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        provenance: CarriedProvenance,
    ) -> BoundEgressCall | None: ...

    async def rebind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        approved: EgressBinding | None,
    ) -> BoundEgressCall | None: ...
```

**Docstrings are omitted here and are not optional in the Protocol**, the form
ADR-0085 §3, ADR-0102 §2 and ADR-0151 §2 each state for their own block. The
subject is positional and everything else is keyword-only, ADR-0085 §2's
convention.

> **Normative.** `bind` answers "what binding does this call have", for a call
> reaching the permission stage for the first time. `rebind` answers "what binding
> does this call have, and is it the one that was approved", for a call resuming
> from a parked `CONFIRM` (§7). Neither takes a step id, an execution id, a
> decision, a ruling or a timeout: what it is given is the bound tool and the
> arguments, which are the two things ADR-0148 §6's determinism clause makes the
> description a function of, plus the third thing that clause names and the seam
> cannot derive.

> **Normative.** Both members take the **`ToolDefinition`** and never a tool id.
> The declaration the seam reads is recoverable from that definition (§3), which
> is the same object the `ActionRequest` carries, the policy rules on and the
> decision embeds verbatim (ADR-0021 §1) — so the declaration the binding was
> derived under and the declaration bound into the request are one object rather
> than two lookups that must agree.

> **Normative.** Both members **refuse** a `tool` that is not equal to the
> definition the implementation holds registered under `tool.id`. This is ADR-0029
> §1's registry-original check performed one stage earlier and for the same stated
> reason — the seam is the only place the caller's definition and an untampered
> original meet — and it is not a substitute for that one, which still runs at
> `invoke`. Where the implementation holds **no** registration for that id, this
> clause is not reached and §8 governs the answer, subject to the revalidation clause
> below, which runs ahead of it.

> **Normative.** `parameters` is the `FrozenJsonMapping` the `ActionRequest` will
> carry, unaltered. Neither member amends them, defaults a value into them or reports
> a substitute for them: what a member hands back on the egress path is the **same**
> mapping it derived under, carried on the `BoundEgressCall` below rather than left
> for the caller to supply again. A binding derived from one argument mapping and
> bound beside another is the whole of what ADR-0150 §4's parameter-relative
> invariants exist to refuse, one stage before they can refuse it — and returning the
> pair together is what makes that refusal unnecessary rather than merely stated.

> **Normative.** Both members return a **`BoundEgressCall`**: a frozen pydantic model
> in `core/types.py` with `extra="forbid"`, `frozen=True`,
> `hide_input_in_errors=True` and `revalidate_instances="always"`, carrying exactly
> **three** fields and no others — `binding`, the `EgressBinding` the seam derived;
> `tool`, the **detached** `ToolDefinition` the derivation read; and `parameters`, the
> **detached** `FrozenJsonMapping` it read. It carries **no** provenance field: a
> span's provenance is already inside `binding`, and a second copy beside it would be
> two shapes of one fact — the duplication ADR-0150 is named against, and the
> objection this section's locator clauses already answer. `rebind` has no `provenance`
> argument at all, so such a field would also be filled from a different source per
> member, for no consumer.

> **Normative.** The caller builds its `ActionRequest` from the returned
> `BoundEgressCall`'s fields — its `tool`, its `parameters` and its `binding` — and
> **never** from objects it retained across the call. This replaces the weaker rule an
> earlier draft stated, "no caller builds an `ActionRequest` from parameters other
> than the ones it passed here", which a caller could satisfy to the letter while the
> mapping it retained had moved underneath it.

> **Normative.** No `await` sits between a member returning and the caller
> constructing the `ActionRequest` from what it returned. The system composes on one
> event loop, so with no suspension point between them nothing else interleaves there
> and the returned copies cannot be reached or replaced before the request is built.
> The residual obligation is therefore **one** clause on **one** site, discharged by
> the absence of a suspension rather than by trusting a caller to be careful.

> **Normative.** Where `bind` returns `None` (§8) the caller builds its
> `ActionRequest` as it does today, from its own `tool` and `parameters`, with
> `egress_binding=None`. There is no binding, so there is no pair to hold together and
> no divergence to falsify anything — which is what keeps §8's claim that no behaviour
> of any non-egress call changes exactly true rather than nearly true.

**The binding and the call it describes are returned together, and the two
alternatives were refused for different reasons.** Adversarial review found that
detaching inside the seam (above) makes the seam derive from its own copies while the
caller builds the request from its objects, so a mutation across §10's one await
produces exactly the mismatched pair the `parameters` clause says must not exist.
Three shapes answer it and only one is sound. **Returning the pair** is taken.
**Passing a pre-detached call snapshot in** is refused as *unsound* rather than merely
inferior: a snapshot the caller constructs stays caller-reachable across the await, so
it reproduces the same divergence one level up, and it moves detachment to every
caller besides. **Leaving the surface alone and obliging the caller by rule** is
refused on this section's own ground — it is a rule where a type will do, which is the
objection this section makes below against a single two-mode member, and which
ADR-0150 §1's fifteen partial states are the corpus's worked instance of. What makes
the taken shape sound is that the seam's detached copies are created **before** the one
await and are unreachable from outside the seam until they are returned: a mutation
bypass needs a reference, and during the suspension nothing outside the seam holds one.
That is why the residual rule is narrower than any alternative's — it governs one
construction site with no suspension inside it, rather than an object's whole lifetime.

> **Normative.** `provenance` is a `CarriedProvenance`: a frozen pydantic model in
> `core/types.py` with `extra="forbid"`, `frozen=True` and
> `hide_input_in_errors=True`, carrying exactly **one** field, `spans`, an
> **immutable** mapping from `EgressSpanLocator` to `DiscloserProvenance`. It
> validates every key and every value **on construction**, refusing a key that is not
> a well-formed locator and a value that is not one of ADR-0146 §1's two members, and
> it **detaches** the caller's mapping at validation so that the value it holds
> cannot be rewritten afterwards (ADR-0018 §3, and the frozen-mapping idiom
> `core/types.py` already applies to `FrozenJsonMapping`).

> **Normative.** `spans` has **no default** and the `provenance` argument has none
> either: a caller holding no recorded origin constructs a `CarriedProvenance` over
> an empty mapping and passes it deliberately. This is ADR-0150 §5's no-default
> reasoning applied at the seam that would otherwise inherit the permissive answer
> for free.

> **Normative.** `CarriedProvenance` and `EgressSpanLocator` each set
> `revalidate_instances="always"`, the mechanism `core/types.py` already uses on
> `SecretName` for this reason: `model_construct` builds an instance without running
> validators, and it is public.

> **Normative.** Both members **revalidate every argument whose annotation carries
> validation**, before reading any field of it, and refuse with an
> `EgressBindingError` chained from the **`ValidationError`** that revalidation
> raises. That is the whole of what this clause converts: an exception of any other
> type raised from inside a validator this seam invokes is not turned into an
> `EgressBindingError` here, and §12 names the one such exception the corpus already
> records and routes it. The set is exhaustive per member and no argument is exempt:
> on `bind` it is `tool`, `parameters` and `provenance`; on `rebind` it is `tool`,
> `parameters` and `approved` where `approved` is not `None`. This is ADR-0029 §2's
> step 1 at a second seam, whose rule is already written: "a revalidation failure
> carrying the underlying `ValidationError` as its cause". No lane omits it for any
> argument on the ground that the annotation says the value is valid:
> `model_construct` is a documented escape hatch, `object.__setattr__` defeats
> `frozen=True` (ADR-0018 §3), and neither is detectable from a type.

> **Normative.** Both members **detach every argument they revalidate**. Each takes
> the **revalidated copy** revalidation produced, captures it before it awaits
> anything, and reads every field from that copy thereafter; the caller's objects are
> never read again — not `tool`, not `parameters`, not `provenance`, and not
> `rebind`'s `approved`. This is ADR-0029 §2's step 1 applied **whole** rather than in
> half. That step obliges a call to be "**revalidated and detached** — first", and
> states the consequence this clause transcribes: "Every subsequent check reads the
> revalidated copy, never the argument."

> **Normative.** Every clause of this ADR that reads `tool`, `parameters` or the
> provenance carrier reads the **detached copy** of that argument and never the
> caller's object. This binds, without exception: §1's registry-original comparison;
> §3's declaration read; §5's derivation, its `SYSTEM_SELECTED` write and its
> absent-span refusal; every refusal condition in §6; §7's re-derivation, its equality
> comparison and its provenance match; §8's partition condition; and §10's read
> budget. No clause of this ADR is satisfied by a read of a caller-held object, and no
> lane reads a section's own wording as licensing one.

> **Normative.** The detachment closes a **suspension** window, and the window is
> real: both members are `async`, §10 permits exactly one await — the connection-record
> read — and it falls between §1's registry-original comparison and §5's derivation.
> Without detachment a caller could hand in a registry-equal definition, let it
> revalidate and compare, suspend the seam on that read, then replace the declaration
> with `object.__setattr__` — which defeats `frozen=True` (ADR-0018 §3), and which the
> revalidation clause above already concedes is undetectable from a type — and have
> the binding derived under a declaration no longer equal to the registered original,
> with the ruling recorded before `invoke`'s check ever runs. That is the "closes the
> door and leaves the window open" position ADR-0018 §3 names, and ADR-0029 §2 refused
> it at the seam one stage on.

**`approved` was the first argument found to need this, and it is no longer the only
one.** An earlier draft detached `approved` alone, justified as "the one argument on
this seam that arrives from outside and is then compared". Adversarial review found
that justification false against its own neighbour: `tool` also arrives from outside
and is also compared — against the registered original, by the registry-original
clause four clauses above — and `parameters` and the carrier are read across the same
await. The clauses above generalise rather than patch, which is what ADR-0029 §2 had
already decided for the seam one stage on; §13 pins one detachment case per argument.

> **Normative.** Past the revalidation above, the seam reads the **detached**
> carrier's keys and values **on trust** and performs no `isinstance` check of its own
> over either — on trust as to their *types*, which the carrier validated, and from
> the detached copy as to their *values*, which the clauses above bind. The
> defence is one call to the type, not a hand-written check per field — which is the
> distinction ADR-0150 §8 draws, and what keeps this from being PR #1120's eight
> rounds re-opened. What the seam still refuses beyond it is a **relational** fact no
> model can see: a locator naming a span this call does not carry (§5).

> **Normative.** `EgressBinder` is decorated `@runtime_checkable`, as every
> Protocol in `core/protocols.py` is. `tests/core/test_protocol_triad.py` reaches a
> Protocol's implementations through `isinstance`, so an undecorated Protocol raises
> `TypeError` there and the triad §13 requires cannot pass — the convention is a
> mechanism rather than a style, and a lane that omits the decorator fails the gate.

> **Normative.** Both members are `async`. That is not permission to await
> anything: §10 fixes exactly what may be read, and everything else is closed.

> **Normative.** `EgressSpanLocator` is a frozen pydantic model in `core/types.py`
> with `extra="forbid"`, `frozen=True` and `hide_input_in_errors=True`, hashable, and
> carrying exactly **two** fields and no others: `argument` and `index`. Each field
> has the **same type and the same validation** as the field of the same name on
> ADR-0150 §4's `EgressSpan`, and `index` is optional and absent by default in the
> same way. This ADR fixes no type for either field beyond that identity: `EgressSpan`
> owns them, ADR-0150 §2's authorisation list is not extended, and a locator that
> could be well-formed where the span it names could not would be a second answer to
> one question.

> **Normative.** Two locators are equal exactly when both fields are equal, and a
> locator names the span of an `EgressBinding` whose `argument` and `index` equal its
> own. It carries **no** provenance, extent, tier or destination, holds no reference
> to a binding or a span, and is not a span: it is a mapping key, it is durable
> nowhere, and it enters no `ActionRequest` and no `PermissionDecision`.

> **Normative.** No lane adds a field to `EgressSpanLocator`, and no lane adds a
> locator field to `EgressSpan` or replaces that model's `argument` and `index` with
> one. ADR-0150 §2 fixes `EgressSpan`'s shape and this ADR authorises no change to it
> (§2).

**A validating carrier rather than a bare mapping, and this is ADR-0150 §8's own
argument arriving at the one argument it did not reach.** Two drafts of this section
got it wrong in the same direction. The first keyed the provenance by
`tuple[str, int | None]`, which mints nothing and hands the seam keys that validate
nothing. The second minted `EgressSpanLocator` and annotated the argument
`Mapping[EgressSpanLocator, DiscloserProvenance]` — and architecture review found on
round 2 that an annotation is not a constructor: Python builds no locator for a
mapping key, so `{object(): object()}` crosses the boundary exactly as before and the
seam must either re-check by hand or raise something it never declared. ADR-0150 §8
settles the question in terms, quoting issue #1122: "The shape that would end the
class rather than move it is **not** more `isinstance` calls: it is making these
values pydantic models in `core/types.py`, which validate their own fields on
construction." A mapping cannot be such a model; a model holding the mapping can, and
`CarriedProvenance` is it. This is also PR #1120's `_checked_provenance` — thirty
lines of hand-written key and value checks, found necessary on that lane's round 4 —
replaced by a type rather than inherited, which is what that lane asked (b) to do.

**The locator's duplication objection is answered rather than dodged.** That it
restates `EgressSpan`'s first two fields is real, and is why the clauses above bind
it to them rather than re-specifying them: there is one definition of what an
argument name and an index are, in `EgressSpan`, and the locator is a projection used
as a key. It is durable nowhere — no `ActionRequest`, no `PermissionDecision`, no
audit row holds one — so no record can hold a locator that disagrees with the span it
names, which is the property that makes this unlike the duplications ADR-0150 is
named against, every one of which was two *stored* shapes.

**Two members rather than one, because one member with two modes is the partial
state this family refuses.** The alternative considered was a single `bind` with
`provenance` and `approved` both optional and a rule that exactly one is
supplied. That is four constructible states of which two are ill-formed, policed
by a rule rather than by a type — ADR-0150 §1's fifteen partial states in
miniature, on a surface where the ill-formed states are "resume without checking
what was approved" and "authorise afresh with a stored binding". ADR-0151 §4
refused a discriminator where one optional field carried a distinction
unambiguously; here neither shape is unambiguous, so the distinction is two
members. Two is also the whole surface: ADR-0085 §8 makes surface size a contract
concern, and nothing else about egress crosses this boundary.

**`bind` and `rebind` follow ADR-0151 §10's `provision`/`reprovision` idiom**, and
they are named short for its stated reason: `EgressBinder`'s whole subject is
egress bindings, so its members need no disambiguator.

### 2. Exactly which `core` names change

This section is a classification of the change being made and is not normative
(ADR-0089 §1). The obligations are in the sections it points at.

| Name | Where | What |
|---|---|---|
| `EgressBinder` | `core/protocols.py`, new | The seam, with exactly the two members §1 lists. |
| `BoundEgressCall` | `core/types.py`, new | What both members return: a frozen model carrying the derived `EgressBinding` beside the **detached** `tool` and `parameters` it was derived from, so the caller builds its `ActionRequest` from that pair rather than from objects of its own (§1). |
| `EgressSpanLocator` | `core/types.py`, new | A span's key on this seam: a frozen, hashable model carrying the `argument` and `index` ADR-0150 §4 identifies a span by, with those fields' types and validation taken from `EgressSpan` (§1). |
| `CarriedProvenance` | `core/types.py`, new | The validating carrier for the recorded origins crossing this seam: one immutable, validated mapping from locator to provenance (§1). |
| `EgressBindingError` | `core/errors.py`, new | The one refusal class both members raise (§9). |
| `Disposition.EGRESS_UNBINDABLE` | `core/types.py`, changed | One new member of an existing enum, returned when the seam refused (§9). |
| `EgressBinding`, `EgressSpan`, `EgressDestination`, `CanonicalDestination`, `BoundAccount`, `DestinationProtocol`, `DiscloserProvenance` | — | **Not this ADR's.** ADR-0150 §2 adds them. This ADR consumes each unchanged, adds no field to any, and authorises no change to any. |
| `ActionRequest`, `PermissionDecision`, `from_request`, `authorises` | — | **Not this ADR's.** ADR-0150 §2's list is the whole of what changes on them. This ADR adds no field, no validator and no conjunct, and reads `ActionRequest.egress_binding` as ADR-0150 §1 defines it. |
| `ConnectedAccount`, `ConnectionAct`, `ProvisioningState`, `ConnectionProvisioner`, `ACCOUNT_IDENTITY_MAX_BYTES`, `CONNECTION_REFERENCE_MAX_BYTES` | — | **Not this ADR's.** ADR-0151 §4, §5, §10 and §11 add them. This ADR relies on each unchanged, imports none of them into this surface, and in particular does not substitute `ConnectedAccount` where ADR-0150 §7 names `BoundAccount` (§10). |
| ADR-0151 §2a's seven `core/errors.py` classes | — | **Not this ADR's.** `ConnectionStoreError` is **declared** as a failure of both members (§9), which is using it; no class is added, subclassed, renamed or given a field, and the other six are neither declared nor raised here. |
| `ToolDefinition`, `ToolRegistry`, `ToolInvoker`, `ToolCall`, `ToolResult` | — | **Unchanged.** No field is added to any, no member is added to either Protocol, and §3 states the constraint that keeps `ToolDefinition` that way. |
| `SkipReason`, `PermissionRuling`, `PermissionOutcome`, `StepStatus` | — | **Unchanged.** §9 says why the refusal is a `Disposition` member and not a `SkipReason`, and why it writes no state. |
| `SecretName`, `Secrets`, `SecretStore`, `SecretScope` | — | **Unchanged.** No credential value and no credential slot enters this seam in either direction (§10). |

> **Normative.** The `core` names this ADR authorises a lane to add or change are
> exactly these and no others: one new Protocol `EgressBinder` in
> `core/protocols.py`, `@runtime_checkable`, with exactly the two members §1 states;
> three new types in `core/types.py` — `BoundEgressCall` with exactly the three fields
> §1 states, `EgressSpanLocator` with exactly the two fields §1 states, and
> `CarriedProvenance` with exactly the one field §1 states; one new
> class `EgressBindingError` in
> `core/errors.py`; and one new member `EGRESS_UNBINDABLE` on the existing
> `Disposition` enum in `core/types.py`. No other `core` name changes: no field is
> added to `ToolDefinition`, `ActionRequest`, `PermissionDecision`, `ToolCall`,
> `PermissionRuling` or any type ADR-0150 §2 or ADR-0151 §4 adds; no member is
> added to `ToolRegistry`, `ToolInvoker`, `ActionPolicy`, `AuditTrail`,
> `AssistantEngine` or `ConnectionProvisioner`; and no member is added to
> `SkipReason`, `DestinationProtocol`, `DiscloserProvenance`, `DataTier`,
> `SecretScope` or `ProvisioningState`. A change beyond this list is a change to
> this decision and needs its own ADR (golden rule 5).

> **Normative.** This ADR claims **no** name in the purge, retention or routing
> territory ADR-0126, ADR-0149 §8 and issue #909 opened — neither in the part
> ADR-0153 has since decided, whose one `core` name is its `ConnectionPurger`, nor in
> the part that stays open, which ADR-0153 §8 confines to every `SecretScope` member
> other than `INTEGRATION`. No lane cites this ADR toward either. Nothing here
> forecloses a seam, a member or a type that territory's own ADR places.

**The intersection was checked rather than assumed, and re-checked when the sixth
name was added.** Against ADR-0150 §2: every name it authorises appears above as a
non-authorisation row, and the six names this ADR claims appear on none of its lists.
Against ADR-0151 §15: it authorises five `AssistantEngine` methods, one Protocol,
three types, two constants and seven error classes, and this ADR claims none of them
and adds nothing to any. Against **ADR-0153 §7**, which merged while this ADR was in
review: it authorises exactly one `core` name, the Protocol `ConnectionPurger`, and
states in terms that it adds no type to `core/types.py`, no class to `core/errors.py`
and no enum member. The two authorisation lists are therefore disjoint, and that
decision sits on the `service`→`tools` boundary this ADR does not reach. ADR-0153
also partially supersedes ADR-0126; nothing this ADR relies on comes from either of
the limbs it replaced, which are the delete act's keyring reach and its injection
boundary, and §12 records that the territory's decided half changes nothing here.
The one shared word is `Egress`, which prefixes ADR-0150's value types and this
ADR's seam, locator and returned call; the one shared concept is the connected
account, and §10 states in terms which of the two account types this surface holds.
`BoundEgressCall` and ADR-0150 §2's `BoundAccount` share a prefix and are not near
neighbours in ADR-0102 §2's sense: the head nouns differ and name different things —
an account bound **into** a binding, and the call the binding **describes** — and
neither is constructible where the other is expected.

### 3. The declaration vocabulary is two keywords, and ADR-0150 §4 is why it is not four

ADR-0150 §6 defers the vocabulary to this ADR and constrains it twice: it is
recoverable from the embedded `ToolDefinition`, and it does not make a schema
unreadable under ADR-0145 §5 and §6.

> **Normative.** The declaration rides in the tool's `parameters_schema`, in
> **two** keywords and no others, each read **only** on the immediate subschema of
> a key of that schema's top-level `properties` object:
> - `x-egress-destination`, whose value is the `DestinationProtocol` member's own
>   string value, present exactly on a **destination-bearing** argument
>   (ADR-0148 §2);
> - `x-egress-tier`, whose value is the `DataTier` member's own string value,
>   present exactly where the argument's field **establishes** that tier in
>   ADR-0146 §5's sense.
>
> No other keyword declares anything to this seam, and no field is added to
> `ToolDefinition` for either.

> **Normative.** Either keyword appearing anywhere else in a `parameters_schema`
> — nested inside `items`, inside a subschema of a subschema, inside
> `additionalProperties`, `patternProperties`, `propertyNames`, `$defs`, or in any
> applicator such as `allOf`, `anyOf`, `oneOf`, `not` or `if`/`then`/`else` — is
> **refused** rather than ignored. Ignoring it would let an author believe they had
> declared a recipient argument while the seam described a body span, which is the
> mis-declaration ADR-0148 §2's third clause names arriving through the mechanism
> meant to prevent it.

> **Normative.** A value of either keyword that does not name a member of its enum
> is **refused**, and no lane reads an unrecognised value as "no declaration". A
> keyword naming a `DestinationProtocol` member for which the seam holds no
> canonicaliser is likewise refused, which is ADR-0148 §1's third clause and not a
> pass-through.

> **Normative.** An argument marked destination-bearing **states a tier** — it
> carries `x-egress-tier` as well — and a declaration marking one without a tier is
> refused. A recipient is a value whose field establishes its tier by ADR-0146 §5's
> own worked example, and the destinations are what ADR-0148 §8's fourth clause
> requires the confirmation to name, so a description stating none for them
> under-describes the span the approver most needs. **Which** tier it is stays the
> author's declaration: this ADR classifies no protocol's addresses and adds no
> member to `DataTier`.

> **Normative.** Nothing in this vocabulary declares whether an argument's value
> **decomposes**, and no lane adds a keyword for it. ADR-0150 §4 decides
> decomposition from the value — "where an argument's value is a JSON array, its
> elements are its spans; where it is any other JSON value, it is one span" — so a
> `multiple` flag would be a second statement of one fact, which is the defect
> ADR-0150 is named against arriving in the vocabulary that ADR routed here.

> **Normative.** Nothing in this vocabulary declares whether an argument is
> **transmitted**, and no lane adds a keyword for it. ADR-0150 §4 decides that
> coverage is over **the arguments** rather than over what the call transmits, and
> states its own reason — a per-argument transmission declaration "is a declaration
> a tool could get wrong and nothing could detect".

> **Normative.** Nothing in this vocabulary declares whether an argument is
> **required**, and no lane adds a keyword for it. JSON Schema's own `required`
> states it, ADR-0145 §1 evaluates it before the ruling and before this seam is
> reached, and a second statement would be one more pair that has to agree.

**Two keywords rather than the producer's four is a result rather than a
simplification.** PR #1120 carried `protocol`, `multiple` and `required` on a
destination-bearing argument and `establishes_tier` and `multiple` on a
transmitted one, across two declarations bound into a third value so that a
caller could not pair one tool's recipients with another's payload. ADR-0150 §4
has since removed three of the five and the pairing hazard with them: the
decomposition is the value's, the coverage is total over the arguments, and both
declarations collapse into the one schema the definition already carries. What is
left is exactly the two facts the schema cannot state — which arguments bear
destinations, and which fields establish a tier — and neither is derivable from
anything, which is ADR-0016 §1's "declared, not inferred" holding at the two
places it still bites.

**Riding in `parameters_schema` rather than on a new `ToolDefinition` field is
ADR-0150 §6's constraint and is also the cheaper shape.** That field is already a
`FrozenJsonMapping` (ADR-0016 §4), already stored by value in every decision, and
already the thing ADR-0145 reads — so the declaration reaches the recorded
decision with no new carriage, and a tool whose declaration and whose schema
disagreed about which keys exist is not constructible, because they are one
document. ADR-0150 §13 records the same conclusion from the other side: "§6's
declaration rides inside a field already declared to hold arbitrary JSON, which is
that field being used rather than widened."

**An `x-` prefix, and unknown keywords are readable rather than merely
tolerated.** JSON Schema draft 2020-12 treats a keyword it does not know as an
annotation and ignores it for validation, so a schema carrying these two validates
exactly as the same schema without them and ADR-0145 §5's one-dialect rule and
§6's readability refusal are both untouched — §13 makes the implementing lane pin
that rather than assert it. The `x-` prefix is chosen over a bare name because
`$`-prefixed names are reserved to the specification and an unprefixed `egress`
could collide with a future keyword, at which point a schema would mean two things
at once.

**Reading the keywords only on a top-level property's own subschema is what keeps
a locator a locator.** ADR-0150 §4 keys a span by `(argument, index)` where
`argument` is a top-level key of `parameters`, and §4's locator clause forbids
reading anything about a span's content off its argument name. A keyword nested
deeper would be declaring something about a value **inside** a span, which this
surface has no field to carry and §4's depth rule forbids describing — so it is
refused rather than read, and refused rather than ignored for the reason the
clause gives.

### 4. A destination-bearing argument is flat, and this is ADR-0150 §11's structural option taken

ADR-0150 §11 leaves this ADR the question and neither requires nor forbids the
answer:

> Whether (b)'s declaration vocabulary closes §4's family **structurally** — by
> constraining a destination-bearing declaration to a **decomposable** shape, a
> JSON string or an array of JSON strings, so that no destination can sit inside a
> span unable to carry it — is **not decided here**.

It is taken.

> **Normative.** An argument may be marked destination-bearing **only** where its
> subschema is a **flat declaration**, which is exactly one of two forms and no
> other: `"type": "string"`, or `"type": "array"` whose `items` is a subschema whose
> own `"type"` is `"string"`. A subschema declaring no `type`, a union of types, a
> `$ref`, or an applicator (`allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else`) in
> place of a type is **not** a flat declaration, and a declaration marking such an
> argument destination-bearing is **refused** when the declaration is read, before
> any call is made.

> **Normative.** A **call** in which a declared destination-bearing argument carries
> a value that is not a JSON string and not a JSON array of JSON strings — a JSON
> object, an array holding a non-string element, a number, a boolean or `null` — is
> **refused** before the ruling, **whether or not** the clause above has already
> refused the declaration.

> **Normative.** The seam **assumes nothing** about what a caller checked before
> reaching it. It re-establishes from the `tool` and the `parameters` it was handed
> every shape any clause of this ADR depends on, and no lane weakens a clause on the
> ground that the ordinary path would have refused the input earlier (§10).

> **Normative.** These clauses are the whole of the constraint. They bind the
> shape of a **destination-bearing** argument and nothing else: an argument that
> bears no destination carries any JSON value ADR-0150 §4 admits, decomposes by §4's
> own rule, and is described as §4 describes it. No lane reads this section as
> constraining a payload argument, a schema, or the `parameters` of a non-egress
> call.

> **Normative.** Widening this constraint to admit a structured destination-bearing
> argument is a change to this decision and needs its own ratified ADR, on the terms
> ADR-0150 §3 fixes for widening `SMTP`: that ADR arrives with the producer whose
> recipient shape forces it, and it states how a supplied form is located inside
> that shape and how the check ADR-0150 §4 could not perform is then performed. No
> lane widens it by building a seam that accepts more.

**What the constraint buys is that two of ADR-0150 §4's three under-representation
failures stop being reachable for a destination, rather than being refused.** §4's
family paragraph enumerates them: total omission, partial omission, and
mis-representation. Under this section a destination-bearing argument's value is a
string or an array of strings, so §4's decomposition puts **exactly one recipient
in exactly one span** in every case; a span cannot hold two recipients, so partial
omission has no instance, and a supplied form is never extracted from inside a
structured value, so mis-representation has none either. `core`'s own
supplied-form invariant — which ADR-0150 §4 states over "a JSON string" and "a
JSON array whose element at `index` is a JSON string" — is then **total** over
every destination this seam can produce. That is the residue ADR-0150 §11 routed
here as an obligation, closed by removing the case rather than by adding a check,
which is the corpus's stated preference in ADR-0021 §3's words: "removing the
capability rather than forbidding it".

**Total omission stays reachable and is exactly what §6's second refusal is
for.** The constraint says nothing about whether a span carries its occurrence,
only about whether it *could*. That is the one member of the family a declaration
vocabulary cannot close structurally, and ADR-0150 §11's second refusal is written
for it.

**The per-call clause is not redundant beside the declaration clause, and the
reason it survives is not the one an earlier draft gave.** That draft argued from
ADR-0145 §9 — a tool with no schema, or a schema describing no key — and adversarial
review found on round 3 that the argument refutes itself: the keywords live inside
`properties`, so a tool with no `properties` declares no destination-bearing
argument at all, and where one *is* declared the declaration clause has already
forced a flat schema that ADR-0145 evaluates before the runner reaches this seam.
The finding is right and the clause's ground is different. It is that **this seam
does not assume its caller validated anything**: it is a Protocol, its conformance
suite calls it directly, and ADR-0029 §2 already puts a revalidation at a second
seam for exactly this — `invoke` re-checks a request the ordinary path has validated
because "a request built by a bypass reaches the seam" (ADR-0145 §3). PR #1120 spent
eight consecutive adversarial rounds on callers reaching its functions with values
their annotations forbade; a seam whose refusals were reachable only through the
happy path would be that class re-opened at the boundary ADR-0150 §8 built its
validating models to close. §10 states the posture and §13 puts the tests where they
are reachable.

**The producer costs nothing and the alternative costs a check with no producer.**
`send_email` declares `to`, `cc` and `bcc` as `{"type": "array", "items": {"type":
"string"}}`, so every destination it can name already sits in a span that can carry
it and this constraint refuses none of its calls. ADR-0150 §11's own paragraph
records that as "evidence about one producer rather than a decision", and it is
right: what makes the decision is the other side of the ledger. The case that would
cost something is a later egress tool with a `{"email": …, "name": …}` recipient,
and there is no such producer — so admitting the shape now means writing the check
ADR-0150 §4 could not write, against a value shape nobody has, which is a bound
with no mechanism behind it. ADR-0150 §6 declines exactly that twice and ADR-0098
§3 records itself making the mistake. ADR-0073 §4's test cuts one way here: the
producer in hand wants flat, and the producer that wants structured does not
exist, so the constraint is the decision the evidence supports and the widening is
the decision that waits for evidence.

**The asymmetry is the same one ADR-0150 §3 spent on `SMTP`'s closed grammar, and
it comes out the same way.** Refusing a shape costs a recoverable error a tool
author sees at declaration time, before anything is registered; admitting it costs
a description narrower than the payload, which ADR-0148 §6 names as the one thing
an approver may never be shown, reached by a recipient sitting inside a value the
description could not decompose. ADR-0017 §4's argument applies with full force —
"a boundary that has never transmitted can be held to the standard we would want
everywhere" — because nothing is registered at this seam and no author is being
asked to change a declaration they already wrote.

**What it does *not* do is make ADR-0150 §12's mandated tests unshippable, and
this is the objection worth answering in advance.** §12 requires the lane landing
(b) to ship the multi-recipient structured span case: a call whose
destination-bearing argument holds an undecomposable value naming two recipients
"is **refused** rather than described by a binding carrying one of them, and the
test asserts that refusal fires". Under this section that call is refused — by the
per-call clause above, for carrying a value of the wrong shape rather than for
carrying two recipients in one span, and reached at the seam's own boundary rather
than through the runner (§10, §13). The test is satisfiable in the terms §12
states it, because §12 states it over the outcome (a refusal, not a binding
carrying one recipient) rather than over which clause produced it. ADR-0150 §11
anticipated precisely this and pre-blessed it: "a vocabulary that could not express
those shapes would make the refusals unreachable rather than wrong."

### 5. The seam derives the binding whole and accepts no part of it

> **Normative.** `bind` **derives** every field of the binding it produces. It
> accepts no destination, no canonical form, no span, no extent, no tier, no
> canonical destination set and no binding from any caller, and there is no
> argument through which one could be supplied.

> **Normative.** Every derivation in this section reads the **detached** `tool`,
> `parameters` and provenance carrier §1 captured, never the caller's objects. The
> derivation is the one step of the call that runs **after** §10's awaited read, so it
> is the step the suspension window §1 names would otherwise reach, and a binding
> derived under a declaration or a payload swapped during that await is exactly the
> outcome §1's detachment exists to make unreachable.

> **Normative.** Every `EgressDestination` the seam produces carries the canonical
> form that **this seam's own canonicaliser for that occurrence's protocol**
> computes from its supplied form. This is the check ADR-0150 §3 routes here, and
> it is discharged by the clause above rather than by a comparison: an occurrence
> the seam computed cannot disagree with the computation that produced it, and a
> caller has no route by which to present one that does. On the resuming path,
> where an occurrence does arrive from outside, §7's equality is what performs it.

> **Normative.** For each protocol, the seam reaches **one** canonicaliser, and no
> integration, declaration, configuration or registration supplies a second for a
> protocol the seam already canonicalises. This is ADR-0148 §2's sixth clause
> relied on unchanged, and this ADR neither relocates that computation into `core`
> nor duplicates it here.

> **Normative.** The seam **refuses** a supplied form for which its canonicaliser
> asserts no canonical form, and never passes the supplied form through as its own
> canonical form. This is ADR-0148 §1's third clause, and ADR-0150 §3's acceptance
> clauses are what decide which forms a protocol asserts.

> **Normative.** The one thing `bind` does **not** derive is a span's
> `provenance`, which is carried (ADR-0146 §2, ADR-0150 §5). The seam writes
> `SYSTEM_SELECTED` for every span the `provenance` argument does not name, and
> that write is the discharge of ADR-0146 §2's fail-closed rule — performed by the
> component building the span, never by a field default. The seam **refuses** a
> `provenance` entry naming a span the call does not carry, rather than dropping
> it: a caller and this derivation disagreeing about what the payload is, is
> exactly what a silent drop would hide.

> **Normative.** How the caller obtained a recorded origin is **not decided here**,
> which is where ADR-0150 §5 left it. No lane reads this ADR as deciding that path,
> as excusing it, or as authorising any component to invent a provenance it was not
> given.

**Deriving rather than accepting is the repair PR #1120 already paid for, applied
one boundary out.** Its round-1 blocker was a description builder that took the
destinations as an argument, and the module's own docstring states the rule the
repair yielded: "a recipient set handed in beside the arguments is bound by
nothing and re-derivable by nobody." A seam that accepted occurrences would put
that defect back at the one place the value becomes durable, since ADR-0148 §3's
first clause binds a standing grant to the canonical destination set and ADR-0150
§9 compares the binding whole.

**It is strictly stronger than the check ADR-0150 §3 asked for, and saying so is
not a way of not doing it.** §3's words are "the check that every occurrence the
seam hands over carries the form that seam's own canonicaliser computes". A seam
that computes them satisfies the predicate universally rather than testably, and
§13 keeps the test reachable by putting it where an occurrence really does arrive
from outside: §7's resuming path, where the occurrence comes out of a recorded
decision and the seam has something to disagree with.

**Today's fail-closed provenance is a residue, and it is named rather than
smoothed over.** Nothing in the tree records a span's origin, so every caller
passes an empty mapping and every span the first implementation describes is
`SYSTEM_SELECTED`. That is the conservative direction and it is ADR-0146 §2's own
answer — but it means ADR-0148 §14's carried-provenance pair is satisfied by a
seam nobody yet feeds, and a user's own words are described as the system's until
the origin path lands. The lane that first records an origin is the lane that
closes it; no clause here bounds when, and no lane records this surface as
carrying real provenance before then.

### 6. The six refusals

> **Normative.** `bind` and `rebind` each **refuse** — raising rather than
> returning, §9 — in each of the following cases, and refusing is a refusal of the
> whole call: the binding is not produced, the `ActionRequest` is not built, and no
> ruling is sought (ADR-0148 §1's third clause).

> **Normative.** Every condition below is evaluated over the **detached** `tool`,
> `parameters` and provenance carrier §1 captured, never the caller's objects. A
> refusal condition read off a caller-held object could be satisfied at the moment it
> was read and false at the moment the binding is produced, which would make each of
> these refusals a check rather than a guarantee.

> **Normative. The undescribed key.** The seam refuses a call carrying a top-level
> key of `parameters` that the bound tool's `parameters_schema` does not
> **statically name** — that is, a key that is not a key of that schema's top-level
> `properties` object. A key admitted only by an open-ended form —
> `additionalProperties`, `patternProperties`, `propertyNames`, or any other
> construct matching keys it does not enumerate — is **not** statically named,
> however validly the call type-checks against it. This is ADR-0150 §11's first
> routed refusal, and its test is **authorship, not validity**: a locator is
> persisted into the recorded decision, so it must be text the tool's author wrote
> and not text a caller chose.

> **Normative.** A tool at this seam with no `parameters_schema`, or with one
> carrying no top-level `properties` object, statically names **no** key. A call to
> it carrying any parameter is refused; a call carrying none is not. No lane reads
> ADR-0145 §9's "an absent schema declares no constraint" as admitting a key here,
> and no lane closes this by requiring `additionalProperties: false`, which would
> add a rule with no effect the clause above does not already have.

> **Normative. The omitted destination.** The seam refuses to produce a binding in
> which a span of an argument the declaration marks **destination-bearing** carries
> no `EgressDestination`. This is ADR-0150 §11's second routed refusal. No lane
> reads such a span as the call having selected no recipient, which is the reading
> ADR-0150 §3's account substitution would otherwise take and the reading its
> condition clause forbids.

> **Normative. The unshaped destination.** The seam refuses a call in which a
> declared destination-bearing argument carries a value that is not a JSON string
> or a JSON array of JSON strings (§4), and refuses a declaration that marks such
> an argument at all (§4).

> **Normative. The unusable declaration.** The seam refuses a declaration that
> breaches §3: a keyword outside a top-level property's own subschema, a keyword
> value naming no member of its enum, a protocol it holds no canonicaliser for, or
> a destination-bearing argument stating no tier. A declaration that cannot
> describe a call does not bind, which is ADR-0016 §1's "a tool that does not
> declare its reach does not load" at the one seam that reads a declaration the
> registry does not.

> **Normative. The unconnectable reference.** The seam refuses a call whose bound
> tool's egress registration names a reference that is not **connectable** at the
> moment the call is bound — its connection record is absent, or is `pending` rather
> than `active` (ADR-0148 §6). This is ADR-0148 §6's connectability clause
> discharged at the moment it names, and §8 and §10 state the read it requires and
> the whole of what that read is for.

> **Normative. The uncompletable call.** The seam refuses a call for which it
> cannot produce a whole, well-formed binding for any other reason — a supplied
> form with no canonical form (§5), a `provenance` entry naming a span the call
> does not carry (§5), a registered egress tool it holds no connected account or
> transport endpoint for (§10), a definition unequal to its registered original
> (§1), or an `EgressBinding` its own construction refuses under ADR-0150 §3, §4 or
> §8. It never returns a partial binding, never returns a `BoundEgressCall` whose
> `tool` or `parameters` is other than the one the binding it carries was derived
> under, and never returns `None` to signal a failure.

**Five named refusals and a residual clause, rather than an enumeration presented
as closed.** **The uncompletable call** is the residual one and the boundary; the
five named refusals above it are the instances the corpus has argued for, each with
an ADR behind it. The read-binding clause is not a refusal and does not enter the
count — it fixes what every condition here is evaluated over.
ADR-0150 §3 records why a list of known-bad shapes is not a boundary:
"one implementation splits at the final `@` and canonicalises it while another
refuses it". The same is true one level up — a seam whose refusals were an
enumeration would let two implementations disagree about a case nobody listed.

**Every one of them fires before a ruling and commits nothing.** That is ADR-0148
§1's third clause, and it is what makes §9's disposition honest: at the point this
seam runs, selection has committed nothing (ADR-0144 §6, ADR-0145 §4), no request
exists, no decision exists, no claim has been made and the step is still `PENDING`.

**Why the undescribed-key refusal is not closed one stage earlier, and cannot be.**
ADR-0145 §11 records that a schema omitting `additionalProperties` "permits keys it
never described, and those keys travel in an authorised payload", and ADR-0145 §9
admits an empty schema over "a parameter mapping with keys". So schema validation
passes such a call by design, and ADR-0150 §4's coverage invariant then requires a
span for the key, whose `argument` reaches the durable decision — the `X-Secret`
shape ADR-0145's own message tests are written against, and the
credential-in-a-key breach ADR-0150 §7's prohibition names and §13 there records as
"a breach of this clause that nothing detects". This clause is what detects it.
Issue #1127 carries the fail-closed alternative and why it rides here.

### 7. `rebind` re-derives everything but the provenance, and refuses what the approval did not cover

ADR-0037 §4's resume sequence rebuilds the `ActionRequest` "from the
**confirmation's own embedded `ToolDefinition`** and the step's parameters", and
a second ruling — `ActionPolicy.resolve` — is taken on it. Under ADR-0148 §1 that
request must carry the whole binding before that ruling too, and nothing today
compares the rebuilt request's binding against the one the parked confirmation
carries.

> **Normative.** `rebind` derives the binding afresh from `tool` and `parameters`,
> exactly as `bind` does and subject to every clause of §5 and §6, and takes from
> `approved` **exactly one** thing: each span's `provenance`, matched to the
> derived span by locator. Nothing else in `approved` is read into the result.

> **Normative.** `rebind` **refuses** unless the binding it derived is **equal** to
> `approved` — equal as ADR-0150 §9 compares a binding, whole and by value. The
> `BoundEgressCall` it returns carries the binding it **derived**, never the one it
> was given, so the rebuilt request carries a value this seam produced rather than one
> read back out of a store — and it carries that binding beside the detached `tool`
> and `parameters` it was derived under, so ADR-0037 §4's rebuilt request is built
> from the same pair on the resuming path as on the first (§1).

> **Normative.** `rebind` **refuses** a `provenance` in `approved` it cannot match:
> a derived span whose locator names no span of `approved`, and a span of
> `approved` whose locator names no derived span, are each a refusal. No lane fills
> an unmatched span with `SYSTEM_SELECTED` here — that default is `bind`'s answer
> for an origin nobody recorded, and using it on this path would silently convert a
> disagreement about the payload into an approved-looking description.

> **Normative.** `rebind` called with `approved` **not** `None` for a tool this
> seam holds no egress registration for **refuses**, and does not return `None`.
> A recorded decision stating an egress call and a registry stating a non-egress
> tool disagree about what was authorised, and the answer to a disagreement here is
> a refusal, not the weaker of the two readings.

> **Normative.** `rebind` called with `approved` of `None` returns `None` on
> exactly the condition §8 states for `bind` — §1's revalidation of its arguments
> succeeded, no egress registration for `tool.id` **and** neither §3 keyword on its
> schema — and refuses on §8's other limb. The gloss restates §8's condition and does
> not narrow it: where the two differ, §8's clause governs. The two members answer the
> no-registration case identically; §8's partition and its revalidation ordering govern
> both, and nothing in this section states a second condition for it.

**Re-deriving and comparing is ADR-0148 §6's determinism clause being used, not
worked around, and the distinction is the one a reviewer should check first.** §6
forbids two things: "nothing in it is derived after the ruling and nothing in it is
re-derived at the seam". *Derived after the ruling*: this derivation happens
**before** `ActionPolicy.resolve` is reached, which is the ruling that authorises
the resumed call, so it is §1's earliness on the second ruling exactly as `bind` is
on the first. *Re-derived at the seam*: "the seam" in that sentence is the
transmitting seam — the callable reached by `invoke`, which ADR-0148 §6's four-way
refusal governs and which this ADR touches not at all. And §6 states the positive
form of what this section does, in terms: the description is deterministic so that
"two derivations of the description for one request agree" and "the approver, the
seam and a later auditor can each re-derive and compare". This is that comparison,
performed by the component that has both values.

**Transcribing the provenance is forced, and a seam that re-derived it would refuse
every resumed egress call.** Provenance is carried and never inferred (ADR-0146 §2,
ADR-0150 §5), and the recorded origin of a span is a fact about an act that
happened before the confirmation was parked — plausibly before a restart, which
ADR-0148 §6 names as "exactly when a parked `CONFIRM` is answered". A `rebind` that
took a fresh `provenance` argument would receive an empty one, describe every span
as `SYSTEM_SELECTED`, and compare unequal to an `approved` binding whose spans said
`USER_AUTHORED` — so every resumed call whose user typed anything would be refused,
and the fix a lane would reach for is to stop comparing. Taking it from `approved`
makes the comparison total on every field that *can* be re-derived, and leaves the
one field that cannot exactly where the trail put it.

**This is where ADR-0150 §12's forged-canonical case becomes reachable, which is
what §5's by-construction discharge would otherwise have cost.** §12 requires "an
occurrence whose canonical form is not what that seam's canonicaliser computes from
its supplied form is refused **before** a ruling is sought". On the `bind` path no
caller can present one. On this path one can: a decision read back out of the trail
carrying a forged occurrence is compared against a freshly derived binding, the two
are unequal, and `rebind` refuses before `resolve` is reached. The same comparison
refuses a stored binding with an omitted destination, a mis-stated extent, a
substituted tier, or a swapped account — every field, because ADR-0150 §9's
equality is over the whole value.

**The account and the endpoint are re-derived too, and a registry rebuilt under a
different configuration therefore refuses here rather than at the callable.**
ADR-0148 §6's fourth clause already makes that call refuse at transmission — "a
registry rebuilt under a different configuration — across a restart, which is
exactly when a parked `CONFIRM` is answered — refuses the call rather than
performing it against another account or another endpoint". This section reaches
the same answer one stage earlier and before a second ruling is recorded, which is
the whole direction ADR-0148 §1 records the design as moving in: "the design work
is therefore almost entirely about **moving facts earlier**, not about adding
checks later." The callable's refusal is not thereby redundant and is not relaxed:
it is the check that runs after the second ruling, on a fact that can move between
the ruling and the transmission.

### 8. A tool with no connected account is not an egress call, and the non-egress path is untouched

> **Normative.** `bind` returns `None` **exactly when** §1's revalidation of its
> arguments **succeeded**, the seam holds no egress registration for `tool.id` — that
> is, no connected account bound to it — **and** `tool.parameters_schema` carries
> neither §3 keyword. `None` is the whole answer for such a call: it is not an egress
> call, it carries no binding, and every refusal in §6 is inapplicable to it. `None`
> never signals a failure, and no lane reads it as one.

> **Normative.** §1's revalidation runs **ahead of** the condition above, and the
> ordering is forced rather than chosen: evaluating that condition reads `tool.id` and
> `tool.parameters_schema`, which are fields of an argument §1 revalidates before any
> field of it is read. A call whose arguments fail revalidation is therefore
> **refused**, on this branch exactly as on every other, and never reaches the
> condition at all. `None` is an answer about a **non-egress tool** and never an answer
> about a malformed argument, and no lane reads §1's revalidation as inapplicable to a
> tool this seam holds no registration for.

> **Normative.** What makes a tool an egress tool is the **connected account it is
> registered against** (ADR-0148 §6's one-account clause), and not the presence of a
> declaration keyword. A tool bound to an account whose schema carries neither §3
> keyword is a well-formed egress call selecting no onward recipient, whose canonical
> destination set is the account alone (ADR-0148 §2's third clause, ADR-0150 §3) —
> which is the shape a resolution call under ADR-0148 §5 takes.

> **Normative.** The seam **refuses** a tool for which it holds no egress
> registration but whose `parameters_schema` carries either §3 keyword. A tool
> declaring destinations or tiers to this seam while registered against no account
> is mis-registered, and returning `None` would silently discard a declaration its
> author wrote. This clause and the `None` clause above **partition** the
> no-egress-registration case **for a call whose arguments revalidated**: exactly one
> of the two applies to any such tool, and no tool is both returned `None` for and
> refused **under this section**. A revalidation refusal (§1) is neither limb of that
> partition and precedes both, so it neither widens the refusing limb nor narrows the
> `None` one.

> **Normative.** A caller receiving `None` builds its `ActionRequest` from its own
> `tool` and `parameters`, with `egress_binding=None`, which is ADR-0150 §1's default
> and its stated `None` semantics. §1's build-from-the-returned-value clause governs
> the egress path and this one governs here, because there is no binding and so no
> pair to hold together. No behaviour of any non-egress call changes: `authorises` compares
> `None == None`, `from_request` transcribes nothing, and the ruling is the ruling
> that is taken today. `current_time` owes this seam nothing beyond one call
> returning `None`.

**One call rather than a query and a call, and the reason is a substitution rather
than a round trip.** The shape a lane reaches for first is `is_egress(tool)`
followed by `bind(tool, …)`. It is worse in the way this family is always worse:
two answers that must agree, obtained separately, with a window between them in
which a registration could differ. One call answers both questions from one read,
and `None` is unambiguous because every failure raises.

> **Normative.** Where the seam holds an egress registration, it reads the
> **connection record** the registration's reference names, at the moment the call
> is bound, and **refuses** unless that reference is **connectable** — its record
> exists and is `active` (ADR-0148 §6). It takes from that record exactly two
> things: the connectability, and the account **identity** it puts in the binding's
> `BoundAccount`. It takes no credential slot, no revision and no state into the
> binding, and it reads nothing else from any store.

> **Normative.** Connectability is read **at this moment** and never carried over
> from registration or from an earlier call, which is ADR-0148 §6's connectability
> clause in its own words. `rebind` reads it afresh too (§7): a reference that went
> pending while a `CONFIRM` was parked is refused before the resolving ruling, not
> resumed against a state read before the user was asked.

> **Normative.** The **transport endpoint** and the account **reference** are the
> registration's and are not read per call: ADR-0148 §6 makes the endpoint the one
> the tool "is configured to use", and the reference is what the registration
> names. Only the identity moves, which is why only the identity is re-read.

**The connection-record read is obliged rather than permitted, and it is the one
place this ADR reads ADR-0148 §11 narrowly.** §11's unmarked prose says (b)
"performs no I/O (§2's fifth clause), so it cannot become the resolution path §5
governs", and an earlier draft of this ADR took that as a flat prohibition and
made the account a registration snapshot. Adversarial review found on round 1 that
the snapshot design lets a ruling be taken against a reference that has since gone
pending — and it is right, because ADR-0148 §6 carries a **marked** clause naming
this seam by name: "A reference that is not connectable takes no part in an egress
call at any stage: no `ActionRequest` is built against it — **§11's seam (b)
refuses**, which is §1's third clause — no ruling is sought for one, and no
callable transmits under it. Connectability is read at each of those moments and is
never carried over from an earlier one." A seam obliged to read a fact at a moment
cannot be a seam forbidden to read anything, so the two sentences settle each other
under ADR-0089 §3: ADR-0148 is in the marked regime, §11's paragraph is unmarked
prose that "never supplies an obligation" and is read to determine what a marked
clause means, and §6's clause is marked. §10 states the reading, and §15 records
why no ADR-0082 §1 record is owed for taking it.

**The narrow reading is also the one §11's own parenthetical directs.** It grounds
the property in ADR-0148 §2's fifth clause, whose whole subject is a canonicaliser
"that needs to ask a remote service what a name denotes", and whose stated purpose
is that the seam cannot become ADR-0148 §5's resolution path. Reading a local
connection record asks no remote service what any name denotes and resolves no
destination, so the property §11 was protecting is untouched — §10's clause keeps
every part of it that bites.

**The one-account clause is still what keeps this to a single record read.**
ADR-0148 §6 binds a registered tool to at most one connected account, so there is
exactly one reference per registered egress tool and no lookup, no search and no
enumeration. The residual staleness is the ruling-to-transmission window, and that
cost is already ruled: ADR-0148 §6's fourth clause makes the callable refuse
unless the identity **currently recorded** for that reference equals the identity
the binding carries — which is now a check over a window measured in the time a
user takes to answer, rather than over the life of a registry.

### 9. One failure class, and one `Disposition` member

> **Normative.** `core/errors.py` gains **one** class, `EgressBindingError`, a
> direct subclass of `AssistantError`. Both members of `EgressBinder` declare it,
> and every refusal in §6, §7 and §8 raises it. This ADR adds no other error class
> and no subclass of this one.

> **Normative.** A refusal is **raised**, never returned. The return type carries a
> `BoundEgressCall` or `None`, and neither can express "this call cannot be completed" —
> which is what ADR-0150 §11's first routed obligation and PR #1120's eighth
> observation each ask for, and what a union return would have answered by making
> the caller branch on a value it cannot act on.

> **Normative.** `EgressBindingError` carries no structured state: no reference, no
> argument name, no destination, no tier and no count. What a refusal says is its
> message, bound by §11.

> **Normative.** Both members additionally declare **`ConnectionStoreError`**
> (ADR-0151 §2a), raised when the connection record §8 reads could not be read at
> all. This ADR neither adds that class nor changes it; it declares it, which
> ADR-0085 §9 makes part of the contract.

> **Normative.** A `ConnectionStoreError` is **never** translated into an
> `EgressBindingError`, into `Disposition.EGRESS_UNBINDABLE`, or into any other
> refusal or disposition. It **propagates** out of the runner stage, which has
> committed nothing at that point: no ruling was requested, no audit record written,
> no claim made, and the step stays `PENDING` at its stored version. No lane
> suppresses it, retries it inside the seam, or falls back to a cached
> connectability, a cached identity or a previous read.

**A store outage is not an unbindable call, and conflating them writes a falsehood
into a returned value.** `EGRESS_UNBINDABLE` asserts that this call **cannot be
completed** — a declaration that cannot describe it, a destination with no canonical
form, a reference that is not connectable. A store that could not be read asserts
nothing about the call: it may be perfectly bindable a second later, and the remedy
is not a different call. That is exactly the line ADR-0145 §3 draws between a schema
mismatch and a `ToolFailure` — "the arguments **are** the ones that would have been
authorised" — and the corpus already answers this shape by raising: `AuditError` and
`PlanningError` propagate out of the runner stage for the same reason, an
infrastructure fault rather than a step outcome. It is also the only answer that
keeps retryability honest, since a caller cannot tell a transient fault from a
permanent one through an enum member whose whole meaning is that the call is wrong.

> **Normative.** `Disposition` gains exactly one member, `EGRESS_UNBINDABLE`,
> returned by the runner stage when this seam refused. It commits nothing: no ruling
> is requested, no audit record is written, no claim is made, and the step stays
> `PENDING`. It is terminal for the turn that met it and for nothing beyond it.

> **Normative.** No lane reports this refusal as `DENIED`, as `INVALID_PARAMETERS`,
> as `NO_CAPABLE_TOOL`, or through any `SkipReason`. No `SkipReason` is added and no
> durable state is written.

**One error class rather than a family, and ADR-0145 §4's argument is the one that
decides it.** ADR-0151 §2a declares seven classes for five operations, and that is
right there because a caller acts differently on each — a displaced act, an
incomplete provisioning and an unknown reference lead to different remedies. Here
they do not: every refusal in §6 ends the turn having disclosed nothing, asked
nobody, written nothing and claimed nothing, and every one of them is corrected the
same way, by a different call or a corrected declaration. ADR-0145 §4's sentence
transfers unchanged: "A second member would be a distinction visible to a client
that cannot act on it differently."

**A new `Disposition` member rather than reusing `INVALID_PARAMETERS`, and this is
the choice most worth arguing.** The reuse is tempting: both commit nothing, both
leave the step `PENDING`, both are terminal for the turn. It is refused because
`INVALID_PARAMETERS` has a ratified definition with **one definition and two
causes** (ADR-0145 §4), both of them about a schema evaluation over capable
candidates — and most of §6's refusals are not about the parameters at all. A
declaration marking a keyword in the wrong place, a tool registered against no
account, a definition unequal to its registered original: reporting any of those as
"the step's parameters were not established as acceptable to any tool that could
have run them" writes a falsehood into a returned value, and widening
`INVALID_PARAMETERS` to a third cause would amend ADR-0145 §4 and owe a record
against it. ADR-0037 §1's argument is the corpus's own and it transfers: "writing a
falsehood into durable state to make a return value tidier is the failure ADR-0014
§4's `_LEGAL_SKIP_REASONS` table exists to prevent." `AMBIGUOUS_CAPABILITY` and
`INVALID_PARAMETERS` were each minted on that argument, and this is the third
instance of it.

**The connectability refusal is the strongest case for a second member, and it is
declined on this family's own rule rather than on ADR-0145 §4's alone.** A call
refused because its reference went pending has a remedy a client could state — run
the provisioning act again, which ADR-0151 §4 obliges a surface rendering a pending
record to say. What makes a second `Disposition` member the wrong place to say it
is that ADR-0151 §9's `connected_accounts` already answers it, as a first-class
engine operation returning a `ConnectedAccount` whose `state` **is** `PENDING`
(ADR-0151 §4). A client that wants the remedy reads the listing that owns the fact;
a disposition member would be a second, weaker statement of it, arriving on the one
turn that happened to hit it and silent on every reference that is pending and
untouched. The refusal's message names the reference (§11), which is what a client
needs to join the two.

**Distinguishable from a denial is the property PR #1120's eighth observation asked
for, and the member is where it is cashed.** A `DENY` means the policy refused, is
recorded in the trail, and moves the step to `SKIPPED`/`APPROVAL_DENIED` naming a
decision. This refusal has no decision to name, because it happens before one
exists. A client that could not tell them apart would report "the assistant
declined to send this" for a tool whose declaration is malformed, which is a
falsehood about the user's own policy.

**Adding a member is additive on the wire**, ADR-0145 §4's own reasoning
unchanged: `Disposition`'s values are `StrEnum` strings a client reads (ADR-0084
§4), the hub is loopback-only and ships with its client from one install, so the
exhaustive readers are in this repository and §13 makes finding them the
implementing lane's obligation.

### 10. Where the seam sits, and what this ADR does not contract

> **Normative.** `EgressBinder` is placed in `core/protocols.py` immediately after
> `ToolInvoker` and before `ActionPolicy`, which is where the pipeline reaches it:
> it is the third face `tools/` presents and the last thing consulted before the
> permission stage.

> **Normative.** It is implemented in **`tools/`**, and consumed in
> **`orchestration`** by the runner stage ADR-0037 §2 and §4 govern — `bind` after
> selection and before the `ActionRequest` is built, `rebind` after the parked
> confirmation is authenticated and before the request is rebuilt. `orchestration`
> reaches it through this Protocol and never through an injected concrete, and
> imports no module of `tools/` (golden rule 1). The composition root wires the one
> implementation.

> **Normative.** Whether one object in `tools/` presents this Protocol alongside
> `ToolRegistry` and `ToolInvoker`, or a second object presents it, is
> `tools/`-internal and **not contracted here**. So is how a tool comes to be
> registered against a connected account, how a declaration is read out of a
> schema, where a canonicaliser lives, and how the callable is reached — the last
> of which ADR-0029 §1 states in terms is `tools/`-internal and uncontracted, and
> which no clause of this ADR narrows.

> **Normative.** Neither member performs **network** I/O of any kind, reads a
> clock, reads configuration, or resolves anything. Neither can become the
> resolution path ADR-0148 §5 governs, and a lane that finds it needs to ask a
> remote service what a name denotes is building a resolution call, which is a
> registered tool with its own declaration, its own request and its own ruling.

> **Normative.** The seam's read budget is **at most one** read per call, and it is
> the connection record §8 names: the record for the reference the tool's egress
> registration carries, for its connectability and its account identity and for
> nothing else. Where the seam holds an egress registration for `tool.id` and the
> call's arguments revalidated (§1) it reads **exactly** that one record; where it
> holds none — §8's `None` path and §8's keyword refusal alike — it reads **none**,
> because there is no reference to name one. A call refused by §1's revalidation
> reads **none** either way, since that refusal precedes the registration lookup;
> the budget is a ceiling and no refusal raises it. It reads no keyring, no memory store, no plan store, no audit trail, no grant
> store, no notification store and no second connection record, and it performs no
> write of any kind anywhere. A lane that finds it needs a second read is changing
> this decision.

> **Normative.** That read supplies **nothing that enters a span**. The spans,
> their extents, their tiers, their provenance and every `EgressDestination` are
> derived from the arguments, the declaration and the carried provenance alone,
> with no store read — which is ADR-0148 §6's determinism clause and ADR-0150 §4's
> decomposition clause, each of which is stated over the description rather than
> over the whole binding, and neither of which this section widens or narrows.

> **Normative.** How the seam reaches that record — through the component ADR-0149
> §1 places, through the store ADR-0151 §10's provisioner holds, or through another
> object in `tools/` — is `tools/`-internal and **not contracted here**. This ADR
> adds no holder, no face, no write, no field and no lifecycle to ADR-0149's
> connection record, and confers no keyring face on anything (ADR-0149 §8).

> **Normative.** No credential value and no credential **slot** crosses this seam
> in either direction. A `SecretName`, a `SecretName`'s `name`, and any string
> identifying a keyring entry appear in no argument, no return value and no refusal
> message. The implementation holds no `Secrets` and no `SecretStore` face
> (ADR-0125 §8, ADR-0149 §9), and holding this seam is not holding one (ADR-0149
> §8).

> **Normative.** The account this surface carries is ADR-0150 §7's `BoundAccount`
> and never ADR-0151 §4's `ConnectedAccount`. No lane substitutes one for the
> other, and no lane implements this seam by importing the live connection record
> into a binding: `revision` and `state` move while a parked ruling stands, which is
> the failure ADR-0150 §7 states its separate type against.

> **Normative.** On the **ordinary path** this seam is reached after ADR-0145's
> schema check, which ADR-0144 §7's eligibility filter performs during selection.
> That is an ordering of the runner stage and **not a precondition this seam
> assumes**: no clause of this ADR is discharged, weakened or made unreachable by it,
> and every shape a clause depends on is re-established here from the `tool` and the
> `parameters` handed over. This is ADR-0029 §2's revalidation posture at a second
> seam — `invoke` revalidates a request the ordinary path has already validated,
> precisely because "a request built by a bypass reaches the seam" (ADR-0145 §3).

> **Normative.** A conformance suite for this Protocol therefore exercises every
> refusal **directly**, against a subject handed inputs no runner would produce. An
> implementation that refuses only what the runner would already have refused does
> not satisfy this contract.

**A third Protocol rather than a member on `ToolRegistry`, and ADR-0016 §5's own
sentence is the reason.** ADR-0029 §1 records it for `invoke`: "the surface should
not widen to cover a concern its consumers do not have. `ToolRegistry` answers
questions — the selection stage asks which tools satisfy a capability, and needs no
power to run one." A binder is a third capability with a third consumer set: the
selection stage needs it not at all, and the executor needs it not at all. Adding
`bind` to `ToolRegistry` would hand every holder of a lookup the ability to
materialise an account reference and a transport endpoint, which is the direction
ADR-0017 §8 wants to move away from. The split is the same capability distinction,
made a second time on the same object, and it is why the object in `tools/` may
present all three faces while the contracts stay three.

**Taking a `ToolDefinition` does not contract registration, and the line is worth
drawing.** ADR-0029 §1 keeps registration inside `tools/` on ADR-0008's precedent —
"a `ContextProvider` crosses the boundary while the `ContextSource` seam that
populates it stays inside `context/`". Nothing in §1's signature names a callable,
a registration act, an account record or a canonicaliser; the definition crosses
because the caller already holds it and because ADR-0150 §6 requires the
declaration to be recoverable from it. What the seam does with `tool.id` internally
is the populated side of ADR-0008's split, unchanged.

### 11. The refusal-message discipline

> **Normative.** No message any refusal on this surface raises renders an argument
> value, a supplied or canonical destination form, an **account identity**, a
> credential slot, or any part of a span's content. It may name the tool id, an
> argument name **the bound tool's declaration statically names**, a zero-based
> index, a count, a field name and an error type.

> **Normative.** A refusal **may** name the **connection reference** the tool's
> egress registration carries, and the connectability refusal (§6) does. That is
> ADR-0149 §3's split between a loggable handle and a Tier 1 value and ADR-0151
> §2a's rule for the neighbouring surface — "names the reference where the call
> carries one, and **never** names the identity" — applied here at both limbs.

> **Normative.** A key of `parameters` that the declaration does **not** statically
> name is **never** interpolated into a message. A refusal for such a key states
> the count and the declared names, and nothing of the key itself.

> **Normative.** An `EgressSpanLocator`'s `argument` reaching this seam from a
> caller is caller-supplied text and is bound by the clause above: it is named only
> once it is known to be an argument the declaration statically names, and reported
> without interpolation otherwise.

**This is PR #1120's ninth observation stated as the rule its rounds 5 and 6
produced, at the surface that inherits it.** A declaration is the tool author's
text and may be named once it is known to be text; a call's arguments and a carried
provenance key are not, and are never named. The trap the observation names is
specific and applies here in full: `tools/builtin.py` names the unexpected keys it
refuses, and may, because it runs **inside** a callable after ADR-0145 has already
refused anything outside `additionalProperties: false`. This seam runs before the
request exists, where a key is a string a model can write as freely as a value —
and where §6's first refusal exists precisely because such a key can be there.

**A refusal message reaches a log, which is why this is a clause rather than a
convention.** `core/logging.py` names the leak and `tools/invocation.py` declines
to make it with `str(exc)`. ADR-0150 §8's second clause imposes the same rule on
every model of surface (a) and gives the reason in one line — "the value it would
append is a recipient address". The same address reaches this seam one step
earlier.

### 12. What this ADR does not decide

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's
form).

> **Normative.** This ADR **designates nothing**, attests no ADR-0017 §3 condition
> and discharges none. `ai_assistant.tools.egress` stays approved and undesignated
> (ADR-0017 §2), no tool is registered at it, and no lane cites this ADR toward
> designation.

> **Normative.** How a **recorded origin** reaches the caller of `bind` is not
> decided here (§5), which is where ADR-0150 §5 left it.

> **Normative.** ADR-0146 §5's third clause — a value the system already tiered,
> carried into a field that establishes none — is **not** discharged here, and the
> `x-egress-tier` keyword does not discharge it. ADR-0150 §6 names the lane that
> owes it and the ADR-0148 §6 clause that lane will amend, and this ADR neither
> narrows nor anticipates that.

> **Normative.** Nothing here decides the provisioning act, a keyring face, a
> connection record's storage, its schema, its lifecycle, or how a tool comes to be
> registered against a connected account. ADR-0149 and ADR-0151 own the first five
> and §10 leaves the sixth `tools/`-internal. **Reading** a record is not deciding
> one: §8 and §10 state what is read and what is taken from it, and no lane cites
> this ADR toward a field, a holder, a write or a lifecycle ADR-0149 §3 does not
> already carry.

> **Normative.** Nothing here decides what a **transport endpoint** must be, what a
> redirect may do, or how a client is constructed. ADR-0150 §7 left that to #83 and
> this ADR consumes the endpoint without constraining it.

> **Normative.** Nothing here decides a **rendering** of a description, which
> ADR-0150 §10's fourth clause keeps off the surface, nor what a confirmation shows,
> which ADR-0148 §8's fourth clause and ADR-0150 §10's third clause own.

> **Normative.** Nothing here adds a `DestinationProtocol` member, widens `SMTP`'s
> acceptance boundary, or authorises a canonicaliser for a protocol ADR-0150 §3 has
> not admitted. Each of those needs its own ratified ADR on ADR-0150 §3's terms.

> **Normative.** Nothing here decides the purge, retention or routing seam ADR-0126,
> ADR-0149 §8's fourth clause and issue #909 opened, and no lane cites this ADR
> toward one. ADR-0153 has since decided the `INTEGRATION` routing and partially
> superseded ADR-0126 in doing so; that changes nothing above, because this ADR
> decided no part of that territory before and decides none of it now.

> **Normative.** A **`RecursionError`** raised by `_deep_freeze` in `core/types.py`
> while §1's revalidation freezes an argument annotated `FrozenJsonMapping` — whether
> the caller passed an already-frozen mapping or a raw one — is
> **not** converted by this seam into an `EgressBindingError`, into
> `Disposition.EGRESS_UNBINDABLE`, or into any other refusal or disposition. It
> propagates unconverted, exactly as §9's `ConnectionStoreError` does, and §1's
> revalidation clause promises the chained refusal for a `ValidationError` and for
> nothing else. This ADR neither creates that hazard nor fixes it — it is ADR-0145
> §14's unbounded `_deep_freeze` at the shared frozen-JSON ingress, tracked as
> **#1107** — so no lane cites this ADR toward a depth bound, a stack-safe
> revalidation path or a bounded parameter walk, and §13 states no test obligation
> for the deep-mapping case.

**The depth hazard is one stage earlier than this seam and is unchanged by it.**
ADR-0145 §6 records that a deep mapping "exhausts the stack on the way in, today,
with no schema evaluation anywhere in the picture", because `_deep_freeze` runs for
every `FrozenJsonMapping` — `PlanStep.parameters` and `ToolResult.output` as much as
`ActionRequest.parameters`. Two callers reach this seam and neither makes the
exposure its own. **On the runner's path** the mapping is already frozen, so a
payload deep enough to raise during revalidation raised once already at the ingress
that built it. **A direct caller may pass a raw mapping** — `FrozenJsonMapping` is an
`Annotated` alias and Python enforces no annotation at runtime, which is the whole
reason §1 revalidates rather than trusting the signature — and then this seam's
revalidation is the first `_deep_freeze` over that structure. The exposure is
identical either way, because the same value goes on to `ActionRequest`
construction, which runs the same unbounded `_deep_freeze` over the same structure:
a call that exhausts the stack here exhausts it there instead, one stage later, with
or without the revalidation §1 requires. What the seam changes is which frame the
stack runs out in, and #1107 is what closes that for every holder at once. The
exposure is therefore neither widened nor narrowed here, which is why the clause
routes rather than answers.
Answering it is a `core`-wide instance bound that ADR-0145 §14 already ruled is its
own decision — "Changing it reaches `PlanStep`, `ToolResult` and every other holder"
— and it reaches types §2's authorisation list does not claim and this ADR is
therefore not authorised to change. It would also be the weaker half of that fix,
giving one holder of the type
a tidy refusal while every other holder kept the ugly one: the "second bound that
runs after the recursion it exists to prevent" ADR-0145 §6 declined for itself, on
reasoning that transfers here whole.

**The semantic half of PR #1120's eleventh observation stays open, and this ADR
narrows it without closing it.** The observation is that "nothing anywhere
establishes that the declaration describes the tool": a declaration naming a body
field as destination-bearing is well-formed and wrong. §3 and §4 close the
*structural* half — a keyword in the wrong place, a value naming no enum member, a
shape that cannot carry a recipient — and none of that reaches a declaration that
is well-formed and false. ADR-0148 §2's third clause already classes it, "a defect
in the same class as a mis-declared `discloses`", ADR-0148 §8 records that "nothing
in ADR-0016 detects a declaration that understates", and ADR-0021 §1 states the
general case: "no producer can prevent it". Naming it here is ADR-0146 §7's posture
rather than a gap discovered late.

### 13. What the implementing lane owes

> **Normative.** Surface (b) is a **seam**, so ADR-0137 §2's widening applies whole
> and ADR-0150 §11's last paragraph places it here: `EgressBinder`'s **triad** —
> the Protocol in `core/protocols.py` together with the three types §2 authorises in
> `core/types.py`, which are the types it exchanges, its shared conformance suite, and its
> canonical fake in `ai_assistant.testing` with the concrete `Test…Contract`
> subclass that runs the suite against it — lands in **one lane and one PR**
> together with its **primary production implementation** in `tools/` and the
> `orchestration` consumer that reaches it. No lane splits the triad (ADR-0137 §3),
> and no lane lands the Protocol ahead of the implementation that shapes it.

> **Normative.** ADR-0150's surface must have merged first. That lane lands
> `EgressBinding` and its types (ADR-0150 §12); this seam returns one, so nothing
> here is implementable before it (golden rule 5, ADR-0015 §5).

> **Normative.** That lane ships the **`None` regression pin**: an existing
> non-egress call — a tool this seam holds no egress registration for — runs the
> whole runner stage with `bind` returning `None`, builds a request with
> `egress_binding=None`, and produces byte-identical durable state to the same call
> before this seam existed. §8's claim that no non-egress behaviour changes is
> demonstrated rather than asserted.

> **Normative.** That lane ships the **forged-canonical** case ADR-0150 §12 states,
> in the terms §7 makes it reachable: a parked confirmation whose binding carries an
> occurrence whose canonical form is not what the seam's canonicaliser computes from
> its supplied form is **refused** by `rebind` before `resolve` is reached, and no
> resolving decision is recorded. A test asserting only that a correctly-built
> occurrence is accepted does not reach it, and no lane records the check as
> satisfied by `core`'s validators, which ADR-0150 §3 states in terms do not perform
> it.

> **Normative.** That lane ships the **omitted-destination** case ADR-0150 §12
> states: a call whose declaration marks an argument destination-bearing and whose
> derivation would produce that argument's span with no `EgressDestination` is
> refused before a ruling is sought, so no decision is recorded holding an
> account-only canonical destination set for it. A case whose binding is also
> malformed under ADR-0150 §4 demonstrates nothing, and one built from a call whose
> declaration marks no argument destination-bearing does not reach the check.

> **Normative.** That lane ships the **multi-recipient structured span** case
> ADR-0150 §12 states, refused under §4's per-call clause: a call whose declared
> destination-bearing argument holds an undecomposable value naming two recipients —
> the `{"recipients": {"to": ["alice@example.com", "mallory@example.com"]}}` shape —
> is **refused** rather than described by a binding carrying one of them, and the
> test asserts the refusal fires rather than asserting that a structured value naming
> **one** recipient is accepted. It is exercised **at the seam**, by calling `bind`
> with that value against a tool whose declaration is flat and well-formed — which is
> §10's posture in a test, and the only place the case is reachable now that §4's
> declaration clause refuses the schema that would carry it and ADR-0145 refuses the
> value against the schema that survives. A test routing it through the runner
> asserts ADR-0145's refusal and not this one.

> **Normative.** That lane ships the **live failure-path** test ADR-0150 §11 states
> for the undescribed key: a call whose `parameters` carry a top-level key the bound
> tool's schema never statically named — the `X-Secret` shape, and the
> credential-in-a-key shape ADR-0150 §7's prohibition reaches — built against a seam
> that otherwise supplies a binding, asserting the refusal fires **and** asserting
> what the recorded decision holds when it does not. Issue #1127 carries the
> fail-closed alternative.

> **Normative.** That lane ships a **declaration-refusal** case for each clause of
> §3 and §4: a keyword on a nested subschema; a keyword in `$defs`, in
> `additionalProperties` and inside an applicator; a keyword value naming no enum
> member; a `DestinationProtocol` the seam holds no canonicaliser for; a
> destination-bearing argument stating no tier; and a destination-bearing argument
> whose declared shape is neither a string nor an array of strings. A test
> exercising only a well-formed declaration satisfies none of these.

> **Normative.** That lane ships the **schema-readability** pin: a
> `parameters_schema` carrying both §3 keywords is readable under ADR-0145 §6, and
> validates a given argument mapping **identically** to the same schema with the
> keywords removed. §3's claim that an unknown keyword is an annotation is
> demonstrated against the repository's own evaluator rather than against the
> specification.

> **Normative.** That lane ships the **connectability** cases §6, §8 and §10 are
> stated for: `bind` refuses where the bound reference's connection record is
> `PENDING`, and again where it is absent, in each case before an `ActionRequest` is
> built and with no ruling sought; a record that becomes `PENDING` **after** a
> registration was built is refused, which is the case a registration snapshot would
> have passed and is what ADR-0148 §6's "never carried over from an earlier one"
> demands; `rebind` refuses a resumed call whose reference has gone `PENDING` since
> the `CONFIRM` was parked; and a binding derived for an `ACTIVE` reference whose
> identity has changed since registration carries the **currently recorded**
> identity. A test that only exercises an `ACTIVE` reference satisfies none of these.

> **Normative.** That lane ships the **carrier** cases §1 is stated for: a
> `CarriedProvenance` constructed over a mapping whose key is not a well-formed
> locator is refused at construction, and so is one whose value is not a
> `DiscloserProvenance`, each exercised separately; a `CarriedProvenance` built over
> a caller's mutable mapping does not change when that mapping is mutated afterwards;
> and a construction omitting `spans` raises. A test that only constructs a
> well-formed carrier over a non-empty mapping satisfies none of these.

> **Normative.** That lane ships the **bypass** cases §1's revalidation clause is
> stated for, exercised by calling `bind` and `rebind` **directly**: a carrier built
> by `CarriedProvenance.model_construct` over a mapping whose keys and values are
> neither a locator nor a provenance; a carrier whose `spans` was replaced by
> `object.__setattr__` after construction; a locator built by `model_construct` with
> an `argument` its validator would refuse; a `tool` built the same way; a
> `parameters` mapping carrying a value `FrozenJsonMapping` would refuse; and — on
> `rebind` — an `approved` binding built by `EgressBinding.model_construct` and one
> whose field was replaced by `object.__setattr__` after construction. Each is
> refused with an `EgressBindingError` **chained from** the underlying
> `ValidationError`, and never with an `AttributeError`, a `TypeError`, a bare
> `ValidationError` or a binding. Each is exercised against a tool this seam holds
> **no** egress registration for and whose schema carries neither §3 keyword, as well
> as against a registered one: that is the branch §8 would otherwise answer with
> `None`, so it is where the revalidation ordering §8 states is actually pinned, and a
> suite exercising only the egress branch leaves it unpinned. A test that constructs
> its inputs ordinarily reaches none of these, and one covering `bind`'s arguments
> alone leaves `rebind`'s untested.

> **Normative.** That lane ships the **pairing** pin §1's return clauses are stated
> for, over **all three** returned fields and for **both** members: the
> `ActionRequest` the runner builds carries `parameters` **equal** to the returned
> `BoundEgressCall`'s `parameters`, a `tool` equal to its `tool`, **and an
> `egress_binding` equal to its `binding`** — asserted on a call where the runner's own
> retained objects were **mutated across §10's awaited read** so that they are
> *unequal* to the returned ones. The divergence is what makes the first two
> discriminating: without it, equality holds whichever object the runner used and the
> test pins nothing.

> **Normative.** The `rebind` limb of that pin is exercised **separately and on the
> resuming path**: a parked `CONFIRM` resumed while the retained confirmation `tool`
> and step `parameters` are mutated across `rebind`'s own connection-record await, with
> the same three assertions over the **rebuilt** request ADR-0037 §4 constructs. A
> lane satisfies this only by rebuilding that request from the returned
> `BoundEgressCall` rather than from what it had retained. §7's equality cases do
> **not** reach it: they compare the derived binding against `approved` inside the
> seam, and say nothing about which objects the request built after the seam returned
> was built from — so a lane passing every one of them can still hand
> `ActionPolicy.resolve` a request the seam never described. A pin covering `bind`
> alone leaves the resuming path untested, which is the path a second ruling is taken
> on.

> **Normative.** The binding limb is asserted with a **distinguishable** binding — one
> whose spans, destinations or account differ from any other binding reachable in the
> test — so that a request built with `egress_binding=None`, or with a stale or
> substituted binding, fails it. `egress_binding` is optional and defaults to `None`
> (ADR-0150 §1), so a pin over `tool` and `parameters` alone passes a runner that
> carried the right payload and dropped the binding, which would put an apparently
> non-egress request in front of the policy and hide from it every destination and
> account the seam derived. That is the same falsehood-in-a-returned-value §9 refuses,
> reached through an omission rather than a substitution.

> **Normative.** That assertion is **equality, not identity**, and the reason is
> mechanical rather than stylistic: `FrozenJsonMapping` carries an `AfterValidator`
> that rebuilds the mapping through `_deep_freeze` in `core/types.py`, which
> constructs a fresh `FrozenDict` unconditionally, so constructing an `ActionRequest`
> cannot preserve the identity of `parameters` and an identity assertion could never
> pass. No lane weakens the clause to equality **without** the divergence, and no lane
> strengthens it to identity on `tool` alone, which would split one rule into two on
> the accident of which field's validator happens to rebuild.

> **Normative.** That lane ships the **detachment** cases §1's detachment clauses are
> stated for — **one per validated argument**, each exercised by mutating the caller's
> object with `object.__setattr__` while the member is suspended on §10's awaited
> connection-record read. Mutating `tool` changes neither the declaration the binding
> is derived under, nor the registry-original comparison, nor what is returned;
> mutating `parameters` changes neither the spans derived nor any refusal condition of
> §6; mutating the `provenance` carrier changes neither the provenance written into a
> span nor §5's absent-span refusal; and mutating `rebind`'s `approved` changes
> neither what §7 compares against nor what it returns. A test that mutates a copy
> satisfies none of these; one that mutates before the await tests revalidation rather
> than detachment; and one covering `approved` alone leaves every argument the
> suspension window actually exposes untested.

> **Normative.** That lane ships the **locator** cases §1 is stated for: an
> `EgressSpanLocator` is hashable and usable as a mapping key; two locators with
> equal fields are equal and hash equally; one carrying an `argument` or an `index`
> that `EgressSpan` would refuse is itself refused at construction, exercised for
> each field; and a locator matches the span of a binding whose `argument` and
> `index` equal its own and no other. A test that only constructs a well-formed
> locator satisfies none of these.

> **Normative.** That lane ships the **read-budget** pin: binding one egress call
> reads the one connection record its registration names and no other store, and
> reads no keyring; binding a **non-egress** call reads **no** connection record at
> all. Asserted against instrumented doubles rather than by inspection, and asserted
> for `rebind` as well as `bind`.

> **Normative.** That lane ships the **store-outage** case §9 is stated for: a
> connection store that raises `ConnectionStoreError` makes `bind` and `rebind` each
> raise it rather than `EgressBindingError`, the runner stage propagates it, and the
> assertion is over the **durable state** as well as the exception — no audit record,
> no claim, and the step still `PENDING` at its stored version. A test asserting only
> that something raised satisfies neither limb, and one asserting
> `Disposition.EGRESS_UNBINDABLE` asserts the behaviour this clause forbids.

> **Normative.** That lane ships the **refusal-message** cases §11 is stated for:
> a refusal for an undescribed key names neither the key nor its value; a refusal
> naming an argument names only one the declaration statically names; no refusal on
> this surface renders a destination form or an account **identity**; and the
> connectability refusal **does** name the connection reference. A test asserting a
> refusal type without asserting its message satisfies none of these.

> **Normative.** That lane ships the **disposition** cases §9 is stated for: a
> refusal from either member yields `Disposition.EGRESS_UNBINDABLE`, writes no audit
> record, makes no claim, and leaves the step `PENDING` at its stored version; and it
> is distinguishable from `DENIED` and from `INVALID_PARAMETERS` at the client. It
> also finds and updates every exhaustive reader of `Disposition` in this repository,
> which ADR-0145 §13 made an obligation for the same reason.

> **Normative.** That lane ships the **`rebind` equality** cases §7 is stated for:
> a resumed call whose derived binding equals the approved one proceeds and carries
> the **derived** value; one differing in exactly one span's extent, in one
> occurrence's supplied form, in the account's identity, in the account's reference,
> and in the transport endpoint is refused in each case separately; and a resumed
> call whose approved binding carries `USER_AUTHORED` on a span proceeds with that
> provenance intact, which is the case a `rebind` re-deriving provenance would fail.

> **Normative.** No lane satisfies any clause of this section with a test that
> exercises only a well-formed binding on a happy path.

### 14. Every obligation ADR-0150 routed here, and where each lands

This section is a classification and is not normative (ADR-0089 §1). It exists so
that a reader can check the routing was spent rather than cited.

| # | What ADR-0150 routed | Where it lands |
|---|---|---|
| 1 | §11: a way for the seam to **fail distinguishably from a denial** | **§9.** One raised `EgressBindingError`, and `Disposition.EGRESS_UNBINDABLE` with the argument for not reusing `DENIED` or `INVALID_PARAMETERS`. |
| 2 | §11 and §6: the **declaration vocabulary** | **§3.** Two keywords in `parameters_schema`, read only on a top-level property's own subschema, with the three the producer carried and ADR-0150 §4 has since removed. |
| 3 | §11: the **structured-value supplied-form** check `core` cannot perform | **§4.** Closed structurally rather than by a check: a destination-bearing argument is a string or an array of strings, so a supplied form is never extracted from inside a structured value and ADR-0150 §4's invariant is total. |
| 4 | §11 and §3: the **correspondence** check | **§5** by construction on the deriving path — the seam computes occurrences and accepts none — and **§7** by equality on the resuming path, which is where ADR-0150 §12's forged-canonical test lands. |
| 5 | §11: the **refusal-message discipline** for a component running before ADR-0145 refused anything | **§11.** Stated as PR #1120's rounds 5 and 6 produced it, with the `tools/builtin.py` trap named. |
| 6 | §11: **a refusal** for the undescribed key, on the authorship test | **§6**'s first clause, with the no-schema and no-`properties` case stated and `additionalProperties: false` explicitly not required. |
| 7 | §11: the **live failure-path test** for that shape (#1127) | **§13.** |
| 8 | §11: **a second refusal**, for a declared destination-bearing argument whose span carries no destination | **§6**'s omitted-destination clause, with §13's test. |
| 9 | §11: the **flat-shapes structural option**, undecided | **§4.** Taken, with the argument, the producer's evidence, the widening route, and the answer to why ADR-0150 §12's structured-span test stays shippable. |
| 10 | §6: the check that a stated **tier** matches the declaration | **§5** by construction — the tier is derived from `x-egress-tier` and accepted from nobody — and **§7** by equality on the resuming path. |
| 11 | §11: the **triad** obligation, which "lands there whole" | **§13.** Protocol, suite, fake and the primary production implementation as one lane and one PR (ADR-0137 §2). |

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text and fixes its form: a
record is owed on an earlier ADR exactly where this ADR **amends a named clause**
of it — where "a reader holding only the earlier ADR now acts differently, or reads
one of its clauses more widely than it now holds". Where the answer is no, the
change is "a **stacked addition**: it is recorded in the ADR that makes it, and
nowhere else". ADR-0148 §12, ADR-0149 §12, ADR-0150 §13 and ADR-0151 §17 are the
worked precedents for this section's form.

**The conclusion first: no record is owed against any ADR, and none is written.**
This ADR's diff is one new file. What follows is the working, ADR by ADR, and a
disagreement with it takes ADR-0082 §1's own form — naming the sentence that does,
or does not, become false or over-wide.

**ADR-0037 §2 and §4 — no record owed, and this is the nearest miss, so the working
is explicit and the contrary case is stated first.** §2's numbered sequence begins
"build the `ActionRequest` from the tool, the step's parameters and the step id",
and §4's begins "rebuild the `ActionRequest` from the confirmation's own embedded
`ToolDefinition` and the step's parameters". This ADR puts a call before each and,
on §4's path, a refusal. Read as closed enumerations, both sentences would become
incomplete, and that is the reading a reviewer is entitled to press.

They are not closed enumerations, and three things establish it rather than
assert it. **First, both were already exceeded without a record.** ADR-0044 §1
added `execution_id` as a fourth constructor input to §2's step 1 and wrote no note
on ADR-0037; ADR-0150 §13 rules on that precedent in terms — "a fifth conjunct
added later does not make it false, and nothing in §1 there claims the list is
closed". §4's own prose likewise describes `_check_parked` and the freshness check
after its six-step list, so the list is illustrative on its own page. **Second, two
ADRs have since inserted whole stages ahead of §2's step 1 and neither recorded
against §2**: ADR-0144's selection ordering and ADR-0145's eligibility filter both
run between capability resolution and the request, and ADR-0145 §12's note on
ADR-0037 is written against a sentence of **§1** — "the parameters flow into the
`ActionRequest` unvalidated" — which had stopped describing the system, and against
nothing in §2. That is the discipline working: a record where a sentence became
false, and none where a sequence grew. **Third, ADR-0144's own supersession entry
states what survives**, and it is what this ADR relies on: "§2's decide → record →
read back → claim order, §3's read-back and identity check, §4's parking and
`resume`" stand unchanged. Every one of those is relied on here unchanged — the
order is untouched, recording still precedes the claim on every branch, the
executor still receives the trail's copy, and a `CONFIRM` still parks durably with
no answer invented. §7's refusal is a refusal **before anything is authored**,
which is the class §4's own step 2 already contains.

**ADR-0148 §11 — no record owed, and this ADR is that clause working.** §11 defers
(b) and says in terms that "a contract ADR that satisfies those is free to choose
the signature; one that does not is changing this decision". Choosing it is the
deferral working, the shape ADR-0147 §11 found for ADR-0017 §2's seam-naming and
ADR-0150 §13 for §11's other half: "that deferral working as designed, not a
supersession" (ADR-0029 §9). Three of §11's four fixed properties are satisfied
without qualification: consulted before the ruling and never after (§1, §7, §10's
ordering clause); refuses rather than guessing (§6); deterministic (§5, and §7's
comparison is what makes the determinism checkable).

**The fourth property — "it performs no I/O" — is read narrowly, and no record is
owed for reading it that way, for two independent reasons.** *First, it is not a
clause.* ADR-0148 carries marked clauses throughout §11, and the sentence in
question is in the unmarked paragraph beginning "What is fixed here rather than
deferred is every property either surface must have". ADR-0089 §3 governs a marked
ADR: "the marked clauses are the whole of what it obligates" and unmarked text
"never supplies an obligation". ADR-0082 §1's test is stated over a **clause** being
amended, and there is no clause here to amend — §11's four marked clauses are about
the two surfaces existing, each being decided in its own contract ADR, no credential
value appearing, and neither surface owning the provisioning act, and this ADR
touches none of the four. *Second, the reading is the one ADR-0148's own marked text
compels.* §6 carries a marked clause naming this seam by name and obliging it to
refuse a reference that is not connectable, with connectability "read at each of
those moments and never carried over from an earlier one". A marked clause and an
unmarked sentence cannot both be read to their widest extent, and ADR-0089 §3 says
which one yields: unmarked text is read "to determine what a marked clause
*means*". §11's own parenthetical points the same way, grounding the property in
ADR-0148 §2's fifth clause, whose subject is a canonicaliser asking a remote service
what a name denotes. So a reader holding only ADR-0148 finds the marked clause
obliging the read, finds the unmarked sentence forbidding the class of read that
would make this seam a resolution path, and acts exactly as §10 above says. Nothing
of §11 becomes false or over-wide, and §10's clauses keep every part of the property
that bites — no network, no clock, no configuration, no resolution, one record read
and no other.

**Adversarial review found this on round 1 and it is recorded rather than
smoothed.** An earlier draft made the account a registration snapshot on a flat
reading of §11's sentence, which would have let a ruling be taken — and a
confirmation shown — against a reference that had since gone pending. That is
ADR-0148 §6's connectability clause defeated at the one moment it names, and §16
records the round.

**ADR-0148 §1, §2 and §6 — no record owed.** §1's third clause is **used** five
times over, once per refusal in §6, which is that clause operating rather than
being narrowed. §2's first, second, third, fourth and sixth clauses are relied on
unchanged: the seam computes a canonical form for every destination-bearing
argument before the request is built, folds nothing, reads the account-only case as
§2's third clause and ADR-0150 §3 leave it, carries both forms, and reaches one
canonicaliser per protocol without supplying a second. §2's fifth clause — no I/O
in canonicalisation — is extended to the whole seam by §10, which is ADR-0148 §11's
own statement of the property rather than a widening of §2. §6's determinism clause
is consumed with the three inputs it names and no fourth: §5 derives from the
arguments and the declaration and carries the provenance, and §3's vocabulary is
how "the registry's definition for the bound tool" supplies its half. §6's
"nothing in it is re-derived at the seam" is answered in §7 at length, and the
answer is that the sentence's "seam" is the transmitting one; §6's own following
sentence — the approver, the seam and a later auditor "can each re-derive and
compare" — is the clause §7 relies on, so §6 is what obliges the comparison rather
than what forbids it. §6's fourth clause, the callable's four-way refusal, is
untouched and §7 states in terms that it is not made redundant. §6's
**connectability** clause is **used** rather than narrowed: it names §11's seam (b)
as the component that refuses where no `ActionRequest` may be built, and §6 above is
that refusal; its "read at each of those moments and never carried over from an
earlier one" is exactly what §8's per-call read discharges and what an earlier
draft's registration snapshot would have breached. §6's clauses on the revision, the
provisioning order, the slot and the compare-and-swap are untouched — this seam
reads a record, writes nothing anywhere, and carries neither a slot nor a revision
into a binding.

**ADR-0150 §3, §4, §6 and §11 — no record owed, and every routed obligation is
discharged rather than narrowed.** §11's clauses are addressed to "(b)'s ADR" by
name; this is that ADR, and §14 maps each. §3's routed correspondence check is
discharged **more strongly** than it asked for, which is not a narrowing: its own
sentence — "no lane states that a carried canonical form has been verified against
anything" until (b) lands — becomes satisfiable, which is the condition it named.
§4's supplied-form residue is closed by §4 above removing the case; §11's clause
routing it says "the check §4's supplied-form invariant cannot perform where a
supplied form is extracted from inside a structured value", and a vocabulary in
which no supplied form is so extracted discharges it in its premise, the shape
ADR-0145 §12 used against ADR-0037 §1. §11's undecided structural clause says the
judgement "belongs to the lane holding the declaration vocabulary and a producer,
which is (b)'s", so deciding it is that sentence working. §6's vocabulary deferral
fixed two constraints and §3 above satisfies both, with §13's readability pin
making the second checkable.

**ADR-0150 §1, §2, §5, §7, §8, §9, §10 and §12 — no record owed.** §1's `None`
semantics are consumed exactly (§8), and §2's authorisation list is not extended:
§2 above adds six names none of which appears on it, and §13's non-substitution
clause for `ConnectedAccount` is restated here rather than relaxed. In particular
**`BoundEgressCall` carries an `EgressBinding` without touching one**: it adds no
field to that model, reinterprets none, stores no second copy of one and mints no
alternative to it, so ADR-0150 §9's whole-value equality still compares the same
shape and a reader holding only ADR-0150 finds every one of its types exactly as it
defined them. A type that *holds* another is not a change to the held one, which is
the same reading ADR-0150 §7's `BoundAccount` already relies on. §5's
carried-not-derived rule is applied at the seam and §5 above discharges its
fail-closed default by having the builder **write** `SYSTEM_SELECTED`, which is §5
there in terms. §5's third clause — the origin's path is not decided — is relied on
and §12 above restates it as undecided. §7's credential and slot prohibitions are
restated for this seam by §10, and §7's residue on a caller-authored key is what
§6's first refusal closes, which is where §7 there routed it. §8's validating-model
discipline is what makes §1's signature able to take these values on trust, and §1
above applies it to the one argument ADR-0150 could not reach: a `Mapping`
annotation constructs nothing, so `CarriedProvenance` is that discipline extended to
a carrier rather than an exception to it, and PR #1120's tenth observation comes out
the way it predicted. §9's whole-value
equality is what §7 compares by, unchanged. §10's no-rendering clause is restated as
out of scope. §12's tests owed by "the lane that lands surface (b)" are restated in
§13 with the shapes that make each reachable.

**ADR-0146 §1, §2, §5 and §6 — no record owed.** §1's two answers stay two. §2's
carried-not-inferred rule and its fail-closed default are both applied and neither
is relaxed — §5 above refuses a provenance entry naming an absent span rather than
dropping it, which is stricter. §5's first clause supplies the meaning of
`x-egress-tier` and is not extended: which fields establish a tier stays the
author's declaration and this ADR classifies nothing. §5's third clause is the one
§12 above explicitly declines to discharge, and declining leaves it exactly as
binding — ADR-0150 §13's own form, "the condition is not made false or over-wide by
being answered", read in the negative. §6's recording obligation on the designating
lane is untouched.

**ADR-0145 §1, §3, §4, §5, §6, §9, §11 and §14 — no record owed.** §1's pre-ruling check
is relied on and §10 states that the ordinary path reaches this seam after it —
as an ordering rather than as a precondition, which is §3's own bypass reasoning
("a request built by a bypass reaches the seam") used rather than narrowed. §4's `INVALID_PARAMETERS`
keeps its one definition and its two causes: §9 above declines to add a third and
mints a separate member instead, and ADR-0150 §13's ruling on ADR-0044 §1 covers
the enum growing — a member added later does not make §4's sentence false, and
nothing in §4 claims the enum is closed. §5's one-dialect rule is untouched and §3
adds no dialect. §6's readability refusal is untouched, and §3 binds the vocabulary
not to breach it, with §13's pin. §9's "an absent schema declares no constraint" is
relied on **as true** and is why §6's second clause is needed: the seam adds a
constraint of its own where the schema declares none, which is an obligation stacked
beside §9 rather than a re-reading of it. §11's record that a schema
"permits keys it never described" is likewise relied on as true and is the premise
of §6's first refusal. §14's **depth-bound** bullet — the unbounded `_deep_freeze`
at the shared frozen-JSON ingress, ruled "a pre-existing hazard this ADR neither
creates nor fixes" and tracked as #1107 — is relied on **as ruled** and left exactly
where ADR-0145 put it: §12 above routes this seam's `RecursionError` to that bullet
rather than answering it, which is a scope-out being honoured rather than narrowed,
and §6's record of the window it leaves open is neither widened nor closed here. A
reader holding only ADR-0145 finds the same hazard, at the same ingress, with the
same issue against it, and acts no differently for this ADR existing.

**ADR-0016 §1, §4, §5 and §7 — no record owed.** §1's declared-not-inferred posture
is applied to the two facts §3 keeps, and §3 above adds no safety field and no
default. §4's `parameters_schema` stays a `FrozenJsonMapping` and §3 uses it rather
than widening it, which is ADR-0150 §13's ruling on the same field. §5's
query-only registry is unchanged: no member is added to `ToolRegistry`, and §10
above states the capability argument §5 and ADR-0029 §1 each made. §7's deferral of
population is untouched.

**ADR-0029 §1, §2, §7 and §8 — no record owed.** §2's step 1 is the precedent §1
above applies at a second seam, and it is applied **whole**: step 1 is that "the call
is **revalidated and detached** — first", and §2 states the consequence in terms —
"Every subsequent check reads the revalidated copy, never the argument." §1 above
transcribes both halves, for every argument this seam validates rather than for one,
and §1's read-binding clause is that sentence restated over this ADR's own sections.
An earlier draft took only the revalidation half and detached `approved` alone;
adversarial review found the gap, and closing it is that step being **used** rather
than extended or narrowed — the rule is ADR-0029's, applied where ADR-0029's own
reasoning already reached. The failure rule — "a revalidation failure carrying the
underlying `ValidationError` as its cause" — is likewise restated for this seam's own
error class, and the three checks `invoke` performs are neither moved, relaxed nor
duplicated: they still run, over the same call, for the reason §2 gives.
§1's biconditional is untouched:
this seam registers nothing, invokes nothing, and adds no route to a callable.
§1's "how the callable is reached is `tools/`-internal, and this ADR does not
contract it" is relied on **and restated** by §10 above, which is the sentence
holding rather than being narrowed. §1's registry-original check is applied a
second time at a second seam, which is that check being used; the one at `invoke`
is unchanged and §1 above says so. §2's three seam checks are untouched. §7's
scope-out of designation is honoured by §12. §8's `approval_ref` obligation is
untouched, and §9 above commits nothing that could reach it.

**ADR-0018 §3 — no record owed.** Its detachment discipline is **applied** at every
argument either member of this seam validates (§1) — `tool`, `parameters`, the
provenance carrier and `rebind`'s `approved` — and, by ADR-0150 §9, at the binding
`ActionRequest` already detaches. That is the discipline used rather than altered,
applied more widely than an earlier draft of §1 applied it rather than differently:
§3's own record of what `frozen=True` does not stop is both what §1's revalidation
clause relies on and what makes the detachment necessary across §10's one await.

**ADR-0021 §1, §3 and §5 — no record owed.** §1's digest still binds the arguments
while storing none of them, and this seam stores nothing at all. §3's rule that a
policy returns a `PermissionRuling` is relied on unchanged: this seam runs before
`decide` and hands the policy nothing. §5's floors are untouched and ADR-0148 §8's
two additional floors are neither relaxed nor restated here.

**ADR-0149 §1, §3, §5, §8 and §9 — no record owed, and the record read is the
paragraph worth showing.** §3's connection record is **read** and nothing about it
changes: no field is added, no holder is named, no write is performed, no lifecycle
is touched, and §10 above leaves the route to it `tools/`-internal. A reader holding
only ADR-0149 finds the same record with the same fields, held by the same
component, and acts no differently — what they additionally find, here, is a second
reader inside the same subsystem, which is a stacked addition contradicting no
sentence ADR-0149 wrote. §3's split between a loggable handle and a Tier 1 value is
relied on unchanged and is what §11 above cites for naming the reference and never
the identity. §8's tenth clause — "holding such a seam is not holding a keyring
face" — is relied on and restated in §10, and this seam holds neither face and reads
no slot. §9's placement of the act and §5's removal entry are untouched.

**ADR-0151 §2a, §4, §9, §10 and §15 — no record owed, and the overlap is one
concept rather than one name.** §4's `ConnectedAccount` gains no field, loses none
and means what it meant — and §8 above reads a **connection record**, not that
model, taking from it only what ADR-0150 §7's `BoundAccount` carries; §9's two
listings are relied on unchanged and §9 above cites `connected_accounts` as the
route by which a client learns a reference is pending, which is that operation
being used rather than extended. §10's `ConnectionProvisioner` gains no member; §2a's seven
error classes are untouched — `ConnectionStoreError` is **declared** by both members
of `EgressBinder` (§9), which is ADR-0085 §9's per-method declaration using an
existing class rather than changing it, and `EgressBindingError` is neither a
subclass of nor a sibling within that family; §15's normative list of what that ADR authorises is
disjoint from §2 above. A reader holding only ADR-0151 still finds five operations,
one Protocol, three types, two constants and seven classes, and acts no differently
for this ADR existing. What they additionally find, here, is a seam that consumes a
snapshot of the account rather than the record — which ADR-0150 §7 already decided
and this ADR only restates as a prohibition on substitution.

**ADR-0017 §2, §3 and §8 — no record owed.** §2's reservation of designation is
honoured and stated in this ADR's header and in §12. §3's conditions get a
mechanism and no attestation, and §3's own sentence that later ADRs "may satisfy any
of them however they judge best" is the sentence this is working under. §8's
injected-capability direction is cited in §10 as an argument for the split, which
is using it rather than deciding it.

**ADR-0137 §2 and §3 — no record owed, and §13 invokes §2 rather than widening it.**
§2's widening is for a slice cut at a contract seam whose implementation would
otherwise put new machinery into two subsystems; this is exactly that slice, and
ADR-0150 §11 already states the conclusion — "Surface (b) **is** a seam, so (b)'s
ADR is where the triad obligation lands, and it lands there whole." §3's rule that
the triad is never split is relied on and restated in §13.

**ADR-0004 §1 and §7, ADR-0125 §2 and §8, ADR-0084 §4, ADR-0085 §2, §3
and §8, ADR-0102 §2, ADR-0008, ADR-0014 §4, ADR-0144 §6 and §7 — no record owed.**
Each is used for what it is: `DataTier` as the tier vocabulary; §7's minimisation
scope untouched; no `SecretName` and no keyring face; `StrEnum` additivity on the wire; the
positional-subject convention, the spelled-out annotations and the surface-size
concern; the near-neighbour naming caution; ADR-0008's populate-inside precedent;
the transition table, unamended and unreached; and the selection stage's
commits-nothing property, relied on for §9's disposition.

**Nothing is superseded and nothing is amended, so
`docs/adr/0152-…md` is the only file this change touches.** No accepted text is
rewritten anywhere (ADR-0070 §1).

### 16. Marking, review and ratification

**Marked under ADR-0089**, so this ADR is in the marked regime: its unmarked prose
supplies no obligation and exists to determine what the marked clauses mean (§3
there). Marking is forward-only (§5), and nothing ratified before it is drawn into
the regime by it.

**The required set is adversarial *and* architecture.** This ADR decides a contract
surface in the sense `CONTRIBUTING.md` → "Stop when the required reviews are green"
gives — it is the ADR that authorises the `core` additions §2 enumerates, including
a new Protocol — and both are run while it stands `Proposed` so that a finding can
still change the decision. `CONTRIBUTING.md` → "Finishing an ADR PR" owns the
sequence; this section points at it rather than re-deriving it, and the outcome is
recorded here on ratification.

**The outcome, recorded on ratification.** The required set is adversarial and
architecture. Both were run while this ADR stood `Proposed`, both returned
**APPROVE** on **one** tree, and the status was flipped only then — with both re-run
on the flipped tree, which is coverage rather than a re-triage.
`CONTRIBUTING.md` → "Finishing an ADR PR" owns that sequence and this line points at
it rather than re-deriving it, as ADR-0130 §12 and ADR-0136 §7 each do.

**No finding was waived, none stands contested, and no issue was filed.** Every
finding was folded. One is worth naming because what was folded is narrower than what
was asked: an adversarial `blocker` held that revalidating `parameters` can raise a
`RecursionError` the seam does not convert. The mechanism is true and §1 and §12 above
carry it — §1 promises the chained refusal for a `ValidationError` and for nothing
else, §12 routes the `RecursionError`. The finding's **direction**, which was to
specify a bounded parameter-validation path here, was declined: that is a `core`-wide
instance depth bound over every holder of `FrozenJsonMapping`, which ADR-0145 §14
already ruled is its own decision and tracked as **#1107**, and §15 records that
bullet as relied on as ruled. Declining a direction while folding its mechanism is not
a waiver, and nothing about this seam's exposure changed either way.

**Two decisions moved materially under review**, both recorded where they bind rather
than only here: the seam reads the connection record **per call** rather than carrying
a registration snapshot (§8, §10, with §15 showing why ADR-0148 §11's unmarked no-I/O
prose yields to ADR-0148 §6's marked connectability clause under ADR-0089 §3); and
both members return a **`BoundEgressCall`** rather than a bare binding, so the binding
and the call it describes cannot drift apart between this seam and the request (§1).
The second is why §2 authorises six names rather than five.

## Consequences

- **ADR-0148 §11's second deferred surface is decided, and both are now decided.**
  Nothing implements against either until both have merged; a request cannot be
  built without the value ADR-0150 supplies, and the value cannot be obtained
  without the seam this ADR supplies.
- **The declaration a tool writes is two keywords, and three of the producer's five
  facts turned out to belong to ADR-0150 §4 rather than to a vocabulary.** A tool
  author declares which arguments bear destinations and which fields establish a
  tier, and nothing else; decomposition, coverage and requiredness are decided by
  the value, by the coverage rule and by JSON Schema respectively.
- **A destination-bearing argument is flat, and the cost is a later integration
  with structured recipients that needs an ADR before it can declare one.** The cost
  is real and the route out is named rather than left to erosion: §4 makes widening
  an ADR on the same terms ADR-0150 §3 fixed for widening `SMTP`, so the shape comes
  back with an argument about how a supplied form is located inside it rather than as
  a patch to a seam. What is bought is that two of ADR-0150 §4's three
  under-representation failures have no instance for a destination rather than being
  refused, and `core`'s own supplied-form invariant becomes total.
- **The seam derives and never accepts, so the correspondence check is satisfied
  universally on one path and by equality on the other.** ADR-0150 §12's
  forged-canonical test is reachable because `rebind` is the one place an occurrence
  arrives from outside — out of a recorded decision, where a tampered trail row is
  exactly what it is written for.
- **A pending connection stops a call one stage before the confirmation, which is
  where ADR-0148 §6 always said it should stop.** The seam reads connectability per
  call rather than carrying a registration snapshot, so a reference half-provisioned
  by an interrupted act shows up as a tool that cannot be called until provisioning
  is re-run — ADR-0148 §6's own stated intent, "rather than as a confirmation the
  user grants and a send that then fails". The cost is one store read per egress
  call, and §10 bounds it to exactly one.
- **A parked `CONFIRM` is now checked against what was approved before the second
  ruling, and not only at the callable.** ADR-0148 §6's four-way refusal at
  transmission is unchanged and unrelaxed; what changes is that a resumed egress
  call whose account, endpoint, recipients, extents or tiers have moved is refused
  before a resolving decision is recorded, which is ADR-0148 §1's stated direction of
  moving facts earlier.
- **`Disposition` grows by one member and no durable state changes.** A refusal
  commits nothing and leaves the step `PENDING`, which is `AMBIGUOUS_CAPABILITY`'s
  and `INVALID_PARAMETERS`' shape and ADR-0037 §1's argument for the third time. Every
  exhaustive reader of the enum in this repository is the implementing lane's to find.
- **The seam returns the call it bound, not only the binding.** Both members hand
  back the derived binding beside the detached `tool` and `parameters` it was derived
  under, and the runner builds its `ActionRequest` from that value. The cost is one
  more `core` type and a sixth claimed name; what it buys is that the binding and the
  payload it describes cannot drift apart between the seam and the request — a
  property a rule obliging the caller could state but not enforce, which is why the
  two rule-shaped alternatives were refused (§1).
- **The non-egress path is untouched and the lane must prove it.** `None` in, `None`
  out, `None == None`, and §13's regression pin demands byte-identical durable state
  rather than a claim.
- **One residue is opened explicitly and given no deadline.** Nothing in the tree
  records a span's origin, so every span this seam describes today is
  `SYSTEM_SELECTED` — the fail-closed answer, and an under-statement of what a user
  typed. The lane that first records an origin closes it, and no lane records this
  surface as carrying real provenance before then.
- **The semantic half of the declaration stays unverified, as three ratified ADRs
  already say it must.** A declaration that is well-formed and false — a body field
  marked destination-bearing, a recipient argument unmarked — is undetectable here,
  and §12 names it rather than claiming a protection this seam does not have.
- **Nothing here authorises a byte.** The seam remains approved and undesignated, no
  tool is registered at it, and this ADR supplies a way to obtain a binding for a
  call that still cannot be made.
