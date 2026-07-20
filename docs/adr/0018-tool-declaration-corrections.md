# 18. Corrections to the tool declaration and registry contract

- Status: Proposed
- Date: 2026-07-20
- Supersedes: ADR-0016 §1 (the `id`/`capability` types and the `description`
  rule) and §5 (query results and the spent-id rule). The rest of ADR-0016
  stands unchanged.
- **Breaking**: changes the `ToolRegistry` Protocol's contract and two `core`
  types (golden rule 5). See "Compatibility" below.

## Context

ADR-0016 ratified `ToolDefinition` and the `ToolRegistry` contract. It was
ratified, as the workflow requires, **before** the registry existed: it merged
as its own PR (#47) ahead of the implementation PR (#67) that depends on it.

Writing that implementation found five places where the ratified contract was
wrong or under-specified. **All five came from implementation contact**, and
that provenance is the point rather than an embarrassment. CONTRIBUTING says it
directly:

> A contract ratified with no implementation contact is how a seam that does not
> survive first use gets blessed.

ADR-0016 had none. It was argued from two named consumers rather than
demonstrated by one, and its own Consequences said so: *"the metadata's fitness
is argued from its two named consumers rather than demonstrated by one."* This
ADR is what first use found. The lesson for the next contract ADR is to **spike
harder before ratifying**, not to ratify faster — a throwaway branch against the
proposed shape would have surfaced most of these five before #47 merged.

These corrections were initially made by editing ADR-0016 in place, on the
implementation branch, on the argument that CONTRIBUTING's exemption for trivial
ADRs ("amendments, status changes, supersedes") covered them. **It does not.**
That exemption is about *review cost* — which changes are not worth a round-trip
through architecture review — and is not a grant of authority to change a
ratified decision in place. ADR-0001 §16 is the governing rule and it is
unambiguous:

> ADRs are append-only: to change a past decision, write a new ADR that
> supersedes the old one and update the old one's status.

Four of the five changes are also substantive by any reading: one adds a new
`core` type, one adds an obligation an ADR-0016-conforming registry can fail,
one **reverses** a rule ADR-0016 states explicitly, and one binds how `tools/`
registers. So this is a substantive contract ADR taking the
full path, which is the whole point of writing it.

## Decision

We will supersede five clauses of ADR-0016. Everything else in that ADR — the
no-defaults rule, the severity scales, the tier reach as a ceiling, the cost and
idempotency vocabularies, the query-only registry, the deferred invocation — is
untouched and remains in force.

| ADR-0016 clause | Change | Kind |
| --- | --- | --- |
| §1, field list | `id`/`capability`: `Identifier` → `VisibleIdentifier` | New `core` surface |
| §1, `description` | "non-blank" → "contains something that renders" | Tightening |
| §5, query results | Adds: every query returns a detached snapshot | New Protocol obligation (**breaking**) |
| §5, registration | Adds: registration re-validates rather than copies | New `tools/` invariant (not a Protocol change) |
| §5, spent ids | Identical re-registration under a deregistered id: idempotent → **refused**; scope corrected to per-registry | **Reverses a ratified rule** (**breaking**) |

### Compatibility

**This is a breaking Protocol change** (golden rule 5), even though no method
signature moves. A `ToolRegistry` implementation that satisfied ADR-0016 can
fail this contract in two ways, and neither is visible to a type checker:

- returning its own list or its own stored definitions from `get`, `find` or
  `all_tools` — previously unspecified, now forbidden (§3);
- accepting an identical definition under a deregistered id — previously
  *required* to be idempotent, now required to raise (§5).

§4 (registration re-validates) is **not** in that list: registration is not on
the Protocol, so that clause binds `tools/` internally and no consumer of
`ToolRegistry` can be broken by it.

The `core` types change too: `ToolDefinition.id` and `.capability` narrow from
`Identifier` to `VisibleIdentifier`, and `description` narrows. All three are
*narrowings*, so every definition that is valid after this ADR was valid before
it; the reverse does not hold, and a tool declaring an invisible id or
description now fails to construct where it previously loaded.

**Migration cost today is nil.** The only implementations are
`InMemoryToolRegistry` and `FakeToolRegistry`, both in the unmerged PR #67, and
both already conform. The obligations are enforced by the shared conformance
suite rather than the signatures, so the practical migration instruction for any
future implementation is: run the suite.

### 1. `description` must render, not merely be non-blank (supersedes §1)

ADR-0016 §1 required a non-blank `description`, rejected at construction like
`Goal.statement`. `strip()` is what "non-blank" means in this codebase, and it
is not enough.

A zero-width space (U+200B), a byte-order mark (U+FEFF) and a variation selector
(U+FE0F) are *format* and *combining-mark* characters, not whitespace. They
survive `strip()`. A description built entirely from them satisfied every rule
ADR-0016 stated while showing the user nothing at all — in the one prompt the
whole design exists to serve, and the moment a user is most likely to approve out
of confusion.

The rule becomes: **at least one character carrying visible content of its own**
— a letter, number, punctuation mark or symbol (Unicode major categories `L`,
`N`, `P`, `S`).

This is deliberately a **whitelist**. The first attempt was a blocklist
enumerating the invisible categories, and it missed the combining marks
(`Mn`/`Me`) — a variation selector or a combining grapheme joiner with no base
character renders as nothing. Listing what counts as visible cannot be defeated
by a category nobody thought of; listing what does not, can.

**A known residual gap.** Two characters in *permitted* categories still render
blank: U+2800 BRAILLE PATTERN BLANK (`So`, a symbol) and U+3164 HANGUL FILLER
(`Lo`, a letter). Both pass this rule. Patching in two codepoints is the same
whack-a-mole that made the blocklist fail, and there is no general "renders as
something" oracle without a font and a shaping engine. The gap is recorded as
issue #62, whose canonical-identifier-syntax direction excludes them by
construction. It is accepted here because a description is free text that must
admit arbitrary Unicode, and because a blank-looking description is visible to
whoever approves the tool.

### 2. `id` and `capability` use `VisibleIdentifier` (supersedes §1)

ADR-0016 §1 typed both as ADR-0014's `Identifier`, which only refuses a blank.
That is inconsistent with §1 above in a way that defeats it: a tool's `id` and
`capability` are shown to the user in the *same* approval prompt as the
description and written into the *same* audit records. An invisible id undoes the
description rule from beside it, and two invisible ids are indistinguishable to
whoever is approving them.

`core/types.py` therefore gains:

```python
type VisibleIdentifier = Annotated[str, AfterValidator(_visible_identifier)]
```

— an identifier stripped and required to contain visible text by the same test
as §1.

**Deliberately not a change to `Identifier` itself.** That type is shared with
`planning` (ADR-0014: `Goal.id`, `PlanStep.id`, `capability`, `bound_tool`,
`approval_ref`), so tightening it is a cross-lane change affecting a subsystem
this lane does not own, and it is mildly breaking for anything already
constructing loose ids. It is tracked as issue #62, where the right answer is
probably a canonical syntax that would let `VisibleIdentifier` collapse back into
`Identifier`.

The cost of not doing that now is a second identifier type in `core` whose
existence is a stopgap. That is stated rather than hidden.

### 3. Every query returns a detached snapshot (supersedes §5)

ADR-0016 §5 specified `find` and `all_tools` as returning `list`, ordered by id,
and said nothing about ownership of what came back.

`list` is mutable. A conforming implementation could return its own backing
collection, and a caller's `result.clear()` would then **deregister every tool
through a query method** — routing around both the registration lifecycle §5
keeps internal to `tools` and the spent-id rule that depends on it. A read
operation that can empty the registry is a strange enough failure that leaving it
unstated was not a defensible silence.

The contract therefore requires: **every query returns a detached snapshot —
the list *and* the definitions in it.**

The definitions are included because `frozen=True` refuses
`tool.risk_level = ...` but not `tool.__dict__["risk_level"] = ...`, so handing
back a shared instance would let a caller rewrite a registered security control
in place. This is the reasoning ADR-0014 already applied to stored plans; it
applies at least as strongly to tool metadata, which is what a permission
decision is made against.

**This is registry-state isolation, and nothing more. It does not make tool
metadata tamper-proof**, and the ADR should not be read as claiming it does. A
caller still owns the copy it was handed, and

```python
definition = await registry.get("smtp")
definition.__dict__["risk_level"] = RiskLevel.LOW
```

produces an object a permission check would then rule on. What detachment
guarantees is that this reaches *no other reader*: the registry still holds
`CRITICAL`, and the next query returns it. The guarantee is about what the
registry **produces**, not about what a caller subsequently does with its own
copy — exactly the boundary ADR-0014 drew for `PlanStore`, and for the same
reason: closing it would mean freezing an object graph the caller owns, which no
producer can do.

Closing it properly needs a **verification seam** rather than a stronger copy:
the permission decision must pin the definition it ruled on — a digest or a
version — and execution must check that pin against the registry before acting,
so a definition altered anywhere between the two is detected rather than
trusted. That is already recorded as issue #54, which arrived at the same seam
from the cross-restart direction, and it is a precondition on the invocation ADR
rather than something this one can settle: there is no permission contract and
no invocation contract yet to carry the pin. Until then, VISION §7's
"deterministic services own permissions" holds only as far as callers pass along
what they were given.

Return types stay `list`, matching `MemoryStore.search` and
`PlanStore.active_executions`, rather than becoming `tuple`. Switching them would
enforce half of this mechanically while doing nothing about the definitions
inside, and would break the convention the other Protocols set for a partial
guarantee. The conformance suite tests both halves instead.

### 4. Registration re-validates rather than copies (supersedes §5)

The same `__dict__` bypass exists on the way *in*, and ADR-0016 said nothing
about it either.

A definition can reach `register` in a state the type would refuse to construct:
`side_effecting` flipped to `False` while `discloses` stays non-empty — an
**inert email tool**, declaring it transmits personal data and has no side
effect. `model_copy` preserves that state faithfully, so a registry that copies
stores the contradiction as authoritative and serves it to every consumer.

The contract therefore requires **registration to rebuild the definition through
validation**, not to copy it — so a definition that could not have been
constructed cannot be registered either.

This is arguably implied by ADR-0016's threat model, which already treats
`frozen=True` as insufficient. But "arguably implied" is not a contract: an
implementation that copied satisfied every word ADR-0016 wrote, so this is a new
obligation and is listed as one.

**It catches internally inconsistent definitions, and nothing else.** An earlier
draft of this clause claimed it also caught a tampered-but-valid definition — a
`CRITICAL` tool downgraded to `LOW` through `__dict__`. It does not, and the
claim was wrong in a way worth recording, because it is the kind of error that
makes a security property look stronger than it is. Rebuilding a `LOW` definition
through validation *succeeds*: `LOW` is a perfectly valid `risk_level`, and the
registry holds no trusted original to compare it against. Validation can only
ever answer "could this have been constructed?", never "is this what the author
declared?".

What actually refuses that downgrade in the implementation is the **conflicting
redefinition** rule (§5): the id is already bound to the `CRITICAL` definition,
so a different one is rejected. That protection therefore depends on the id
already being registered — a tampered-but-valid definition registered under a
*fresh* id is accepted, and no mechanism in this ADR detects it.

Distinguishing an authorised declaration from a validly tampered one needs a
provenance boundary this contract does not have: a signature, or a factory that
is the only way to mint a definition, or the pinned digest issue #54 already
proposes for the approval path. That is out of scope here and is named so the
gap is not mistaken for coverage.

**Scope: a `tools/` invariant, not a Protocol obligation.** Registration is
deliberately off `ToolRegistry` (ADR-0016 §5) so its lifecycle can evolve inside
`tools/`, and this clause does not change that — it is **not** a breaking change
to the cross-subsystem contract, and a consumer depending only on the Protocol
is unaffected. It binds the registration convention the two implementations
share.

The shared suite tests it because `FakeToolRegistry` must not diverge from
`InMemoryToolRegistry` on registration: a fake that accepted a definition the
real registry refused would let a consumer's tests pass against behaviour
production rejects. That is fidelity between two stand-ins for each other, which
is what a canonical fake is for — not an extension of the Protocol, and if the
registration lifecycle later changes inside `tools/`, this clause changes with
it and no consumer contract moves.

**Migration.** An implementation that copies must rebuild through validation
instead — one line. The suite's case for it is the inert-email definition above;
the `risk_level` case in the suite exercises the §5 conflict rule, not this
one.

### 5. The spent-id rule: reversal and rescoping (supersedes §5)

**This clause reverses a rule ADR-0016 states.** Merged ADR-0016 §5 reads, in
full:

> **A tool id, once registered, is bound to that definition for the life of the
> process — permanently, and `deregister` does not free it.** Re-registering an
> identical definition is idempotent; registering a *different* one under a used
> id is refused with `ToolRegistrationError`, whether or not the id was
> deregistered in between.

Two problems, one of them a genuine contradiction.

**(a) The text contradicts itself, and the resolution reverses one half.** The
refusal is scoped to a *different* definition, "whether or not the id was
deregistered in between" — which by direct implication permits an **identical**
definition under a deregistered id, as idempotent. But the same paragraph says
the id is bound "permanently" and `deregister` "does not free it". Both cannot
hold.

Resolved toward revocation: **registering anything under a deregistered id is
refused, an identical definition included.** Sameness is not a licence to
un-revoke. A rule permitting the identical case would mean revocation held only
until someone replayed the original registration — which is precisely what a
composition root re-running would do, so the guarantee would evaporate in the
most ordinary circumstance rather than an exotic one.

The rule in full is now:

- re-registering an **identical** definition under a **live** id is idempotent,
  so a composition root may run twice without special-casing;
- registering a **different** definition under a live id is refused;
- registering **anything** under a **deregistered** id is refused.

The motivating failure is unchanged from ADR-0016 and is worth restating, since
it is the reason to prefer the strict reading. ADR-0014 records `bound_tool` as
an *id*, and `approval_ref` points at a permission decision made against whatever
that id meant at the time. If an id can be rebound, then between "the user
approved `send_message`, which is `REVERSIBLE`" and "the executor runs
`send_message`", the definition can become an `IRREVERSIBLE` one — and every
record involved still reads as consistent.

**(b) "For the life of the process" is wrong; the scope is the registry.** The
spent-id ledger belongs to a registry instance. Two registries in one process
each keep their own, so `"smtp"` can mean one thing in the first and another in
the second — and a permission decision taken against the first followed by
execution against the second reassembles the substitution above out of two
individually-compliant halves.

What forecloses that is ADR-0016 §7's constraint that **this registry is the only
one**: a decision about composition, enforced by whoever wires the system, not by
the type. The wording is corrected to "for the life of the registry" so the
guarantee is not overstated.

Making the ledger process-global would enforce it mechanically and is
**rejected**. It would put mutable, ever-growing state on a class, so every test
that registered a tool would poison every later one; and it would make any future
context where two independent registries are legitimate — a second user, a
sandbox — unrepresentable, in order to catch a composition mistake that a single
line in a composition root already prevents.

## Consequences

- **The tool contract survives its own first implementation**, which is the
  thing ADR-0016 could not demonstrate about itself.
- **Three concrete failure paths close**, each found by writing the code rather
  than by reading the ADR: an inert-email definition is now unrepresentable
  (§4, registration re-validates), a query can no longer deregister (§3, results
  are detached), and an id cannot be rebound within a registry's life (§5).
- **Validation is not authentication, and the ADR now says so.** Re-validation
  answers "could this have been constructed?", never "is this what the author
  declared?" — so a tampered-but-valid definition under a fresh id is accepted.
  Closing that needs a provenance boundary (signature, minting factory, or #54's
  pinned digest) that no contract here provides.
- **A fourth path does not close, and is named rather than implied.** A caller can
  still tamper with the copy a query handed it and pass that downstream (§3).
  Detachment isolates *registry state*; it does not make metadata tamper-proof,
  and no amount of copying would — that needs a pinned digest checked at
  execution, which is issue #54 and belongs to the permission and invocation
  contracts that do not exist yet.
- **`core` carries a second identifier type** (`VisibleIdentifier`) whose
  existence is a stopgap until #62 settles a canonical identifier syntax. Two
  types that differ in a subtlety is a real readability cost, accepted over a
  cross-lane change to `planning`'s shared type from a tools lane.
- **A description can still be made to render blank** with U+2800 or U+3164
  (§1). The whitelist narrows the attack from "any invisible character" to "two
  known codepoints in visible categories", and #62 closes it properly.
- **`ToolRegistry` gains an obligation that is not expressible in its
  signatures.** "Returns a detached snapshot" lives in the docstring and the
  conformance suite, not the types, so it holds only for implementations that
  actually run the suite. That is the same footing as every other behavioural
  clause in these contracts, and it is why the triad is mandatory — and it is
  why this counts as a breaking change despite no signature moving: a
  conforming implementation can be broken by it without anything failing to
  compile.
- **ADR-0016 is now partially superseded**, so a reader must consult both. The
  alternative — restating ADR-0016 whole — would make the diff between the two
  decisions much harder to see, which is the thing a superseding ADR most needs
  to convey.
- **The workflow lesson is the durable one.** ADR-0016 was ratified with no
  implementation contact, exactly as the process permits, and five corrections
  followed within a day. The next substantive contract ADR should be spiked
  against a throwaway implementation before ratification, not merely reviewed
  harder. Review caught none of these five; writing the code caught all of them.
- **Revisit when** #62 lands a canonical identifier syntax (at which point
  `VisibleIdentifier` should collapse into `Identifier` and §1–2 here become
  redundant), or when tool invocation lands and the registration seam changes
  shape.
