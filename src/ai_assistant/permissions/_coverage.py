"""One request, read once and detached, for the policy that rules on it (ADR-0065).

:func:`coverage_subject` reads off an
:class:`~ai_assistant.core.types.ActionRequest` every value
:class:`~ai_assistant.permissions.policy.ThresholdActionPolicy` rules on, **before
the ruling's first suspension**, and :class:`CoverageSubject` carries them across
it. The policy decides about that observation rather than the caller's object, and
before it hands the request to the recipient-grant seam it reads the request again
and buys no grant where the two differ.

**What is left of a larger module.** This file also held ADR-0254's coverage
comparison — whether a live goal authorization covers a request, by ADR-0266 §7's
evidence and argument routes — which had no caller left once the policy's route (d)
retired. ADR-0309 §5 retires goal authorizations, quotes and coverage, and the
authority milestone redoes them, so the comparison retired with the goal-authorization
store. The subject stays because the policy still takes it on ``decide``'s
first executed line.

**A module function rather than a method**, so nothing here holds a store, a clock
or a seam: everything the capture needs is in its argument.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from pydantic import TypeAdapter

from ai_assistant.core.types import (
    BoundAccount,
    CanonicalDestination,
    FrozenJsonMapping,
    ToolDefinition,
)
from ai_assistant.permissions._detachment import field_state

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import (
        ActionRequest,
        FrozenJson,
        SpanCoverage,
    )


#: ``ActionRequest.parameters``' own annotated type, so the capture below is
#: **rebuilt through the same validation the field is** rather than copied.
#:
#: A ``dict(request.parameters)`` would detach the top level and leave every nested
#: value shared: :class:`~ai_assistant.core.types.FrozenDict` holds its pairs in one
#: ``__slots__`` attribute and refuses assignment, which
#: ``object.__setattr__(nested, "_items", …)`` goes straight past — so a caller
#: could rewrite ``parameters["prefs"]["x"]`` while the grant seam was out and
#: the subject would hold the rewritten value. ``_freeze_json`` rebuilds
#: every container beneath the root, which is ``recipient_grants.py``'s *"detached
#: **recursively**, which is what ``field_state`` buys over a copy of ``__dict__``"*
#: reaching the one field on this request that is not a model.
#:
#: **It is not ADR-0145 §1's schema evaluation**, which is what makes this cheaper
#: than rebuilding the whole :class:`~ai_assistant.core.types.ActionRequest`: the
#: walk here is the freeze the field already runs at construction, and no schema is
#: consulted.
_PARAMETERS: Final[TypeAdapter[Mapping[str, FrozenJson]]] = TypeAdapter(FrozenJsonMapping)


class CoverageSubject(NamedTuple):
    """One request as a ruling sees it, read in a **single** observation.

    Built by :func:`coverage_subject` **before the ruling's first suspension** and
    consulted afterwards in the request's place, so that one ruling is decided about
    one request (ADR-0065). A sourced ruling suspends — ``RecipientGrants.covering``
    is a durable read — and a frozen model is rewritable through ``__dict__``, so a
    caller can replace the request's fields while that seam is out. The policy reads
    the request again before it hands it to the seam, and a subject unequal to this
    one buys no grant, so **every field here is one a rewrite of is caught**.

    ``permissions/recipient_grants.py``'s ``_coverage_subject`` is the model this
    follows one seam over, and the values are **detached as well as captured**:
    capturing the objects alone leaves the same rewrite available one level down.
    Rebuilt through validation and never deep-copied, which is
    ``core.types._detached_tool``'s own discipline continued across a suspension
    rather than a new one.

    **Narrower than a whole validated** :class:`~ai_assistant.core.types.ActionRequest`
    **snapshot, deliberately.** Rebuilding the request would re-run ADR-0145 §1's
    schema evaluation on every ruling.
    """

    goal: str | None
    """``request.goal``, carried so that a rewrite of it is a changed request."""

    intended_action: str | None
    """``request.intended_action``, carried so that a rewrite of it is a changed
    request."""

    tool: ToolDefinition
    """The declaration by value, which ``decide`` reads its rule table off."""

    parameters: Mapping[str, FrozenJson]
    """The call's arguments.

    **Rebuilt through ``FrozenJsonMapping``'s own validation and therefore detached
    all the way down** (:data:`_PARAMETERS`), because a top-level copy would leave
    every nested value shared with the caller."""

    parameters_digest: str
    """``request.parameters_digest``: the request's own property over ADR-0021 §1's
    encoding, and never a second canonicalisation of :attr:`parameters`."""

    account: BoundAccount | None
    """The binding's connected account, and ``None`` exactly where the request
    carries no ``egress_binding`` at all."""

    destinations: tuple[CanonicalDestination, ...]
    """The binding's canonical destination set, empty where the request carries no
    binding."""

    coverage: SpanCoverage | None
    """The binding's ``coverage``, and ``None`` where the request carries no
    binding."""


def coverage_subject(request: ActionRequest) -> CoverageSubject:
    """Read off ``request`` everything a ruling compares, once and detached.

    **Called on ``decide``'s first executed line**, before anything is awaited.
    Every line before the first suspension is already one observation — nothing else
    runs on this loop between two statements that do not await — so what this buys
    is not the reading but the **carrying**: the values survive the suspension the
    grant seam takes, and everything after it is decided over them rather than over
    the caller's object.

    **A request this cannot read is an argument fault and not a ruling**, which is
    why nothing here is guarded. ``decide`` reads ``request.tool`` for its own rule
    table on the same unsuspended stretch, so a request whose ``__dict__`` has been
    emptied already fails there; what this closes is the window a **suspension**
    opens, which is the one nothing above it can see.

    Args:
        request: The action being ruled on.

    Returns:
        The values the ruling is decided over.
    """
    binding = request.egress_binding
    return CoverageSubject(
        goal=request.goal,
        intended_action=request.intended_action,
        tool=ToolDefinition.model_validate(field_state(ToolDefinition, request.tool)),
        parameters=_PARAMETERS.validate_python(request.parameters),
        parameters_digest=request.parameters_digest,
        account=(
            None
            if binding is None
            else BoundAccount.model_validate(field_state(BoundAccount, binding.account))
        ),
        destinations=(
            ()
            if binding is None
            else tuple(
                CanonicalDestination.model_validate(field_state(CanonicalDestination, destination))
                for destination in binding.canonical_destination_set
            )
        ),
        coverage=None if binding is None else binding.coverage,
    )


__all__ = [
    "CoverageSubject",
    "coverage_subject",
]
