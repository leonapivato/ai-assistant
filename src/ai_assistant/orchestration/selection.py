"""The selection rule: prefer the least severe capable declaration (ADR-0144).

ADR-0016 §5 refused ranking to the registry — *"the registry does not choose"* —
and ADR-0016 §7 deferred it here by name; ADR-0037 §1 declined to invent it and
left the step ``PENDING`` whenever ``find`` returned more than one candidate.
ADR-0144 is that rule arriving, and this module is it: a **total preorder** over
declarations, computed from the candidates and the ADR-0144 §4 preference
sequence alone, whose *unique* minimum runs.

Four properties carry the design and each is a correctness requirement rather
than tidiness.

- **The minimum must be unique, not merely first** (§1). "Take the first minimum
  found" is one word shorter and resolves ties by whichever order ``find``
  listed, which is by ``id`` — the rule ADR-0037 §1 refused, because it would
  *"silently prefer `a_deleter` over `b_archiver` for the same capability"*. So a
  tie is a genuine outcome (:attr:`Selection.tied`) rather than a case this
  absorbs.
- **Every key is total** (§1). A key that declined to compare some pairs would
  make the composed ordering non-transitive, and which candidate came out
  minimal would then depend on the traversal. Absence is therefore *ordered*
  rather than left incomparable — an undeclared ``latency`` sorts last (§3), an
  id nobody named sorts last (§4).
- **No key reads ``id`` as a value** (§1). Key 6 matches an id against a sequence
  a deployment stated and orders by the *position*, so two ids adjacent in the
  alphabet get no relationship from it.
- **Argument fit binds before the ranking, never inside it** (ADR-0144 §7,
  ADR-0145 §2). :func:`eligible_candidates` is the filter; a candidate whose
  schema the arguments do not satisfy is removed before any key is applied, so a
  well-declared candidate that cannot accept the arguments can never outrank one
  that can.

Nothing here is injectable and nothing here is a hook. ADR-0037 §1 rejected *"a
`select` hook or an injected ranker"* on ADR-0036 §1's ground, and ADR-0144 §4
answers that rejection rather than evading it: what a deployment supplies is a
*datum* consumed at one position the rule defines, after every preceding key has
already found the candidates equal — never a rule about what "better" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import CostBasis, DataTier, parameter_violations

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import FrozenJson, ParameterViolation, ToolDefinition

#: Stands in for a `latency` nobody declared, paired with the flag that already
#: sorted it last — so the second component never decides anything on its own.
_UNDECLARED_LATENCY: Final = timedelta(0)

#: ADR-0144 §2 key 3: **the reverse of ``DataTier``'s declaration order**, so the
#: *less sensitive* tier is the lesser — ``OPERATIONAL`` < ``PERSONAL`` <
#: ``SECRET``. ADR-0016 §3 declares the type most-sensitive-first deliberately,
#: which is why this cannot be taken by symmetry with keys 1 and 2: an earlier
#: draft of ADR-0144 said "under ``DataTier``'s declaration order" and thereby
#: preferred the ``SECRET``-disclosing candidate over the ``PERSONAL``-disclosing
#: one — an inverted comparison in the safety direction, the same shape as the
#: ``RiskLevel.CRITICAL < RiskLevel.LOW`` trap ADR-0016 §2 disarmed on the type.
#: Derived from the declaration order rather than transcribed, so a member
#: inserted in the middle cannot be given a rank contradicting where it reads;
#: the *direction* is pinned by a test naming the three tiers literally, which is
#: what ADR-0144 §8 requires of this key and of no other.
_TIER_ORDER: Final[tuple[DataTier, ...]] = tuple(reversed(tuple(DataTier)))

#: ADR-0144 §2 key 4: ``FREE`` < ``PER_CALL`` < ``UNKNOWN``. Its top end is
#: ADR-0021 §5's floor read as a preference — an ``UNKNOWN`` cost is never
#: auto-granted, so a candidate that declared can run without a prompt — and its
#: lower end is a plain economic preference this ADR asserts on its own
#: authority, carrying **no** monotonicity guarantee. Amounts are never compared
#: (§2): two ``PER_CALL`` candidates are equal here whatever they cost, because
#: cross-currency comparison is out of scope (ADR-0016 §4) and a key that ranked
#: within a currency only would be the partial comparison §1 forbids.
_COST_ORDER: Final[tuple[CostBasis, ...]] = tuple(CostBasis)

#: The whole ordering key, applied lexicographically: severity block (§2), then
#: latency (§3), then the deployment's preference (§4). Every component is a
#: total function of one declaration onto a totally ordered value.
SelectionKey = tuple[int, int, tuple[int, ...], int, tuple[int, timedelta], int]


def validated_preference(preference: Sequence[str], /) -> tuple[str, ...]:
    """Take ADR-0144 §4's construction-time snapshot of the preference sequence.

    **The snapshot is what makes the duplicate check worth anything.** A caller
    passing a list and mutating it afterwards — including while ``run`` is
    suspended at ``find``'s ``await`` — would otherwise hand the stage a sequence
    it never validated, and §1's order-independence would be gone with it: two
    selections over one candidate set could differ with nothing in the
    declarations having changed. The corpus makes this move wherever it matters
    (``PlanStep`` deep-freezes its parameters, ``ToolCost`` is frozen in its own
    right), so taking the copy is the established shape rather than a new
    precaution.

    **A duplicate id is refused rather than resolved.** ``(a, a, b)`` gives ``a``
    two positions, and an implementation taking the first would order it before
    ``b`` while one taking the last would order it after — two conforming
    implementations selecting different tools from one candidate set. Defining
    "first occurrence wins" would close that; refusing closes it better, because
    a duplicated id is a mistake in the deployment's configuration and ADR-0016
    §1's posture on the type this stage consumes is that a malformed declaration
    does not load.

    **An id naming no registered tool is permitted and simply matches nothing**
    (§4). A sequence is written against the tools a deployment expects and a
    registry is populated at startup from whatever registers, so refusing an
    unmatched id would make the sequence a second registration manifest that has
    to be kept in step with the first.

    Args:
        preference: The ordered tool ids the composition root supplies.

    Returns:
        The immutable snapshot every later selection reads.

    Raises:
        ValueError: If any id appears more than once.
    """
    snapshot = tuple(preference)
    seen: set[str] = set()
    repeated: set[str] = set()
    for entry in snapshot:
        if entry in seen:
            repeated.add(entry)
        seen.add(entry)
    if repeated:
        msg = (
            f"the tool preference sequence names {', '.join(repr(one) for one in sorted(repeated))}"
            " more than once, so which occurrence ranks it is undefined; name each at most once"
        )
        raise ValueError(msg)
    return snapshot


def selection_key(candidate: ToolDefinition, preference: tuple[str, ...], /) -> SelectionKey:
    """The six keys of ADR-0144 §§2-4, in the order they are applied.

    Lower is preferred throughout, and the composition is lexicographic: an
    earlier key that separates two candidates settles them whatever the later
    keys say.

    1. ``risk_level``, ascending under ``RiskLevel``'s declaration order.
    2. ``reversibility``, ascending under ``Reversibility``'s declaration order.
       Keys 1 and 2 lead because they are the axes ADR-0014 §2 and ADR-0016 §7
       both name as the point of having a selection stage.
    3. ``discloses``, elementwise, under :data:`_TIER_ORDER`. Tuple comparison
       gives both readings of "discloses less" at once: the most sensitive tier
       dominates, and a proper prefix beats its own extension.
    4. ``cost.basis``, under :data:`_COST_ORDER`.
    5. ``latency``, ascending, with an undeclared one **after** every declared
       value (§3). Last rather than first because first would reward omission,
       inverting the incentive ADR-0016 §1 built the type around; and ordered
       rather than incomparable because §1 forbids a partial key.
    6. The candidate's position in ``preference``, with an unnamed id after every
       named one (§4).

    Keys 1 through 3 are the axes ADR-0021 §5 constrains every conforming policy
    over, which is what discharges ADR-0016 §7's "informed by ``permissions``"
    **by agreement rather than by consultation**: where one candidate is less
    severe on one of them and equal on everything else, no conforming policy
    rules on it more restrictively. That is §5's own hypothesis, so the guarantee
    is its clause rather than an extension of it — and it does not reach key 4,
    whose lower half carries no monotonicity guarantee at all.

    ``reads``, ``writes``, ``side_effecting``, ``idempotency``,
    ``idempotency_window``, ``description`` and ``parameters_schema`` are keys at
    no position (§2): a key on an axis the policy contract does not constrain is
    a key whose direction nothing checks, which is ADR-0036 §1's ground for
    declining the same fields as policy clauses.
    """
    latency = candidate.latency
    return (
        candidate.risk_level.severity,
        candidate.reversibility.severity,
        tuple(_TIER_ORDER.index(tier) for tier in candidate.discloses),
        _COST_ORDER.index(candidate.cost.basis),
        (1, _UNDECLARED_LATENCY) if latency is None else (0, latency),
        preference.index(candidate.id) if candidate.id in preference else len(preference),
    )


@dataclass(frozen=True, slots=True)
class Selection:
    """What the ordering made of a non-empty set of eligible candidates.

    Attributes:
        tool: The strictly least candidate under the whole key, or ``None`` where
            the least was not unique.
        tied: The ids of the candidates that tied, sorted, and empty where one
            was selected. Sorted for reporting only — ADR-0144 §1 forbids ``id``
            as an ordering *value*, and this is the report of a decision already
            made, not a term in it.
    """

    tool: ToolDefinition | None
    tied: tuple[str, ...] = ()


def select(candidates: Sequence[ToolDefinition], preference: tuple[str, ...], /) -> Selection:
    """Order ``candidates`` and return the unique minimum, or the tie (ADR-0144 §1).

    **The result does not depend on the order ``candidates`` arrive in**, on how
    many times this is called, or on any clock, random source or stored state:
    every component of :func:`selection_key` is a total function of one
    declaration and the snapshot, so the minimum is a property of the set.

    Args:
        candidates: The eligible declarations, which must be non-empty —
            emptiness is ADR-0145 §4's ``INVALID_PARAMETERS`` and is the caller's
            to report, since only the caller knows whether the set was empty
            because ``find`` returned nothing or because the fit filter emptied
            it.
        preference: The validated snapshot from :func:`validated_preference`.

    Returns:
        The selection, or the tie that ADR-0144 §6 leaves for
        ``AMBIGUOUS_CAPABILITY``.

    Raises:
        ValueError: If ``candidates`` is empty.
    """
    if not candidates:
        msg = "selection needs at least one candidate; an empty set is the caller's to dispose of"
        raise ValueError(msg)
    keyed = [(selection_key(candidate, preference), candidate) for candidate in candidates]
    least = min(key for key, _ in keyed)
    minimal = [candidate for key, candidate in keyed if key == least]
    if len(minimal) == 1:
        return Selection(minimal[0])
    return Selection(None, tuple(sorted(candidate.id for candidate in minimal)))


@dataclass(frozen=True, slots=True)
class Eligibility:
    """What the argument-fit filter made of the capable candidates (ADR-0145 §2).

    Attributes:
        eligible: The candidates whose schema the arguments satisfy, in the order
            they were considered. Empty where every capable candidate reported
            violations, which is ADR-0145 §4's first cause.
        violations: What the arguments missed, across the candidates that
            reported anything, exact duplicates dropped and the per-candidate
            order preserved. Reported alongside an empty ``eligible`` (§4) and
            empty on :attr:`failure`, which is §7's second cause and reports
            none.
        failure: The **type name** of the exception an evaluation raised, or
            ``None``. Nothing else derived from it may be carried: ADR-0145 §7
            forbids ``str()``, ``args``, ``__cause__`` and ``__notes__`` alike,
            because a schema that raises on demand would otherwise be the one
            path on which an untrusted document makes the argument values arrive
            in a log.
    """

    eligible: tuple[ToolDefinition, ...] = ()
    violations: tuple[ParameterViolation, ...] = ()
    failure: str | None = None


def eligible_candidates(
    parameters: Mapping[str, FrozenJson], candidates: Sequence[ToolDefinition], /
) -> Eligibility:
    """Drop the candidates ``parameters`` cannot satisfy, before any key is applied.

    ADR-0144 §7 legislated for this in advance — *"a candidate whose schema the
    step's parameters do not satisfy is **ineligible** and is removed from the
    candidate set before any key of §2 through §4 is applied. It is never a key, a
    penalty or a tie-break term"* — and ADR-0145 §2 binds the obligation
    candidate-wise and ahead of the ranking cut. The reason is the same on both
    sides: argument fit answers a question about *eligibility*, and folding it
    into an ordering would let a candidate that cannot accept the arguments
    outrank one that can.

    **A raise refuses the step, not the candidate that raised** (ADR-0145 §7).
    Ineligibility is a statement that the parameters *do not satisfy* a schema,
    and an evaluation that raised establishes no such fact — so continuing to
    rank over the remainder would be selecting under an unknown. The walk stops
    at the first raise and reports nothing but the exception's type.

    **The evaluator is ``core``'s and is never substituted** (ADR-0145 §2): the
    rule that decides whether a mapping satisfies a schema is implemented once,
    because `orchestration` needs the answer to decide whether to request a
    ruling at all and `tools` needs the same rule to hold at the seam, and golden
    rule 1 forbids either importing the other.

    Args:
        parameters: The step's arguments, exactly as planned — nothing here
            modifies them, so the mapping evaluated is the same canonical form
            ``ActionRequest.parameters_digest`` is taken over (ADR-0145 §7).
        candidates: Every capable declaration ``find`` returned, non-empty.

    Returns:
        The surviving candidates, what the rest missed, and whether an evaluation
        raised.
    """
    eligible: list[ToolDefinition] = []
    reported: list[ParameterViolation] = []
    for candidate in candidates:
        try:
            violations = parameter_violations(candidate.parameters_schema, parameters)
        except Exception as exc:
            return Eligibility(failure=type(exc).__name__)
        if violations:
            reported.extend(one for one in violations if one not in reported)
        else:
            eligible.append(candidate)
    return Eligibility(tuple(eligible), tuple(reported))


__all__ = [
    "Eligibility",
    "Selection",
    "SelectionKey",
    "eligible_candidates",
    "select",
    "selection_key",
    "validated_preference",
]
