"""The promoted engine surface is closed under ``core`` (ADR-0085 §5).

ADR-0084 §4 bounds the promoted set by "the *transitive closure* of what the
Protocol's methods name, not just the types they return", and gives the mechanical
reason: promote a type while something its fields reach stays in `orchestration`,
and ``core`` imports `orchestration`, which golden rule 2 forbids and
``lint-imports`` fails.

**``lint-imports`` catches that one type at a time and only once someone writes the
import.** This catches it as a property: it walks the declared field graph out from
every signature on it and asserts every type it reaches is declared in
``core.types``. A type left behind fails here naming itself, rather than as an
architecture violation several edits later.

**It is a walk rather than a list, deliberately.** ADR-0085 §4c records what
happened to the one field list that ADR: it was falsified in a single review round,
having missed ``MemoryBase.id`` and ``Provenance.evidence`` — "a rule over 'every
string' survives, and a list of fields rots". The same argument applies one level
up, so the closure is checked by walking rather than by an enumeration this module
would have to maintain. The names the corpus has promoted are asserted *reachable*,
which is a different claim: it catches a type an ADR promoted and an implementation
forgot, and it cannot go stale in the direction that matters, because a type nobody
reaches is caught by the walk being closed.

**The set the corpus has promoted is now two ADRs' and not one's.** ADR-0085 §5
gathered twenty-four for fifteen methods; ADR-0102 §3 adds ``GrantableSource`` for
the four grant operations, and §13 applies ADR-0070 §1's test to ADR-0085 §1's "and
nothing else" and concludes no supersession is owed — what that exclusion excludes
is *lifecycle*, named in the paragraph it introduces, and the closed graph the
title claims is a property of the **types** rather than of the method count.
ADR-0102 §3 shows the walk from ``GrantableSource`` terminating in ``core`` on
every branch, and the assertions below are what check that claim rather than take
it.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Sequence
from types import UnionType
from typing import Final, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel

from ai_assistant.core import protocols as protocols_module
from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import AssistantEngine

#: ``core/protocols.py`` imports the promoted types under ``TYPE_CHECKING``, so the
#: names in its annotations are not in its module globals at runtime. Resolving them
#: needs ``core.types``' namespace handed in explicitly.
_NAMESPACE: Final = {**vars(core_types), **vars(protocols_module)}

#: The thirty-three the corpus has promoted. Twenty-four are ADR-0085 §5's own walk:
#: thirteen from ``engine.py`` (of which ``BeliefSummary`` is new, §4a), six from
#: ``questions.py``, one from ``runner.py``, one from ``loop.py``, two from
#: ``observation.py`` and one from ``conversations.py``. The twenty-fifth is
#: ADR-0102 §3's ``GrantableSource``, which the four grant operations name. The last
#: eight are ADR-0130 §9's, which the five notification operations name: the held
#: record, the candidate it carries, the two enumerations naming a ruling, the
#: standing-preferences value, its per-class row, the reach level that row holds, and
#: the quiet window. §9 promotes them by requiring the five methods to be
#: ``AssistantEngine`` members — "These are contract surface, because
#: ``AssistantEngine`` is a Protocol in ``core/protocols.py``" — so the same walk
#: that caught ``GrantableSource`` is what makes them checkable rather than asserted.
#:
#: ``SourceGrant`` and ``GrantScope`` are **not** here and that is not an omission:
#: they predate this block (ADR-0097 §2) and are ``core`` leaves the walk terminates
#: at, exactly as :func:`_declared_by_this_change` sorts them.
PROMOTED: Final[frozenset[str]] = frozenset(
    {
        "ContinuationToken",
        "Confirmation",
        "StepOutcome",
        "TurnOutcome",
        "LearnDecision",
        "QueueOutcome",
        "QueuedQuestion",
        "IngestSummary",
        "LearnOutcome",
        "Evidence",
        "BeliefSummary",
        "Belief",
        "ConversationSummary",
        "QuestionState",
        "Retirement",
        "SuccessorLink",
        "Question",
        "AnswerKind",
        "AnswerOutcome",
        "Disposition",
        "TurnResult",
        "ObservedProposal",
        "ObservationReport",
        "ConversationDigest",
        "GrantableSource",
        "HeldNotification",
        "NotificationCandidate",
        "NotificationCondition",
        "NotificationDispositionKind",
        "NotificationPreferences",
        "ClassReach",
        "NotificationReach",
        "QuietWindow",
    }
)

#: The modules a reached type may legitimately be declared in. ``builtins`` covers
#: ``bool``/``int``/``str``, and the two stdlib modules cover ``datetime`` and
#: ``timedelta``, which :data:`~ai_assistant.core.types.UtcInstant` and the
#: ``timeout`` argument reach.
_ALLOWED_MODULES: Final[frozenset[str]] = frozenset(
    {"builtins", "datetime", "enum", "types", "typing"}
)


def _method_names() -> list[str]:
    """Every public method the Protocol declares."""
    return sorted(name for name in vars(AssistantEngine) if not name.startswith("_"))


def _reachable() -> set[type]:
    """Walk the declared field graph out from every signature on the surface.

    The walk follows a field's **annotation to its declared type**, stops at
    anything it has already seen, and **never follows a method** — which is what
    makes it terminate and what leaves the projection helpers behind (ADR-0085 §5,
    §6a). ``MemoryRecord``'s four-member union is followed through
    :func:`typing.get_args` rather than enumerated, for the same reason.
    """
    seen: set[type] = set()
    pending: list[object] = []
    for name in _method_names():
        method = getattr(AssistantEngine, name)
        pending.extend(get_type_hints(method, globalns=_NAMESPACE).values())
    while pending:
        annotation = pending.pop()
        origin = get_origin(annotation)
        if origin in {UnionType, typing.Union} or origin in {tuple, list, Sequence}:
            pending.extend(get_args(annotation))
            continue
        if get_args(annotation):  # Annotated[...] and every other parameterised form
            pending.extend(get_args(annotation))
            continue
        if not isinstance(annotation, type) or annotation in seen:
            continue
        seen.add(annotation)
        if issubclass(annotation, BaseModel):
            pending.extend(get_type_hints(annotation, globalns=_NAMESPACE).values())
    return seen


def test_every_type_the_surface_reaches_is_declared_in_core() -> None:
    """The closure is closed, which is what golden rule 2 needs it to be.

    A promoted type whose field reached back into `orchestration` would put
    ``core -> orchestration`` in the import graph. This says so as a property of
    the graph rather than waiting for the import to be written.
    """
    stray = sorted(
        f"{reached.__module__}.{reached.__qualname__}"
        for reached in _reachable()
        if reached.__module__ != core_types.__name__
        and reached.__module__.split(".")[0] not in _ALLOWED_MODULES
    )
    assert not stray, f"the surface reaches types outside core.types: {stray}"


def test_the_walk_reaches_every_promoted_type() -> None:
    """Every promoted type is really on the surface.

    The complement of the test above: that one catches a type left behind, this
    one catches a type the ADR promoted and an implementation never wired up — a
    ``Question`` that no method returns is a type nobody can obtain.
    """
    reached = {kind.__name__ for kind in _reachable()}
    missing = sorted(PROMOTED - reached)
    assert not missing, (
        f"ADR-0085 §5 promotes these and the surface reaches none of them: {missing}"
    )


def test_the_promoted_set_is_the_one_the_adrs_gathered() -> None:
    """No further type slipped onto the surface unreviewed.

    ADR-0085 §5's walk is the *complete* graph, and ADR-0015 §5's point is that no
    lane authors ``core`` contract surface unreviewed. A type reachable from these
    signatures that no ADR named is exactly that, so it fails here rather than
    merely growing ``core/types.py`` — which is what caught ``GrantableSource``
    when ADR-0102 added it, and is why this check earns its keep rather than
    merely restating :data:`PROMOTED`.

    The pre-existing ``core`` leaves the walk terminates at are excluded by name
    from the comparison rather than listed: they are whatever ``core.types`` held
    before this change, which is a fact the tree carries and not a list this module
    maintains.
    """
    surface = {kind.__name__ for kind in _reachable() if kind.__module__ == core_types.__name__}
    unexpected = sorted(surface & _declared_by_this_change() - PROMOTED)
    assert not unexpected, (
        f"these reach the surface and ADR-0085 §5 does not name them: {unexpected}"
    )


def _declared_by_this_change() -> set[str]:
    """The names ADR-0085 §5 moved, as the source line order records them.

    Everything declared **after** :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`
    is the promoted block; everything before it predates this change and is a leaf
    the walk terminates at (ADR-0085 §5: "``core`` is already closed under its own
    field graph, which is exactly what ADR-0068 established").
    """
    source = inspect.getsource(core_types)
    boundary = source.index("DEFAULT_PAGE_SIZE: Final[int] = 50")
    tail = source[boundary:]
    return {
        name
        for name, value in vars(core_types).items()
        if isinstance(value, type)
        and value.__module__ == core_types.__name__
        and f"class {name}(" in tail
    }


@pytest.mark.parametrize("name", sorted(PROMOTED))
def test_no_promoted_type_was_left_behind_in_orchestration(name: str) -> None:
    """A type declared in both places is two types, and the wire would see both.

    ADR-0084 §4's "relocating an enum is not redefining it" holds only if the
    relocation is a *move*. A leftover declaration in `orchestration` would be a
    second class with the same name and the same member values, ``!=`` to the
    promoted one, and a client validating against the wrong one would refuse a
    perfectly good payload.
    """
    from ai_assistant import orchestration  # noqa: PLC0415 — asserted about, not used

    assert not hasattr(orchestration, name)


def test_the_walk_really_is_transitive() -> None:
    """The recursion goes past the first level, which is the whole claim (§5).

    A walk that stopped at the returned types would pass every assertion above
    while proving nothing: the twenty-four are all directly named, so a one-level
    walk reaches them too. These five are reachable **only** through two or more
    field hops — ``StepFailure`` and ``ToolFailureKind`` through
    ``StepOutcome.state -> ExecutionState -> StepExecution``, ``Provenance`` and
    ``Validity`` through ``TurnOutcome.turn -> TurnResult.memories ->
    MemoryRecord``, and ``PlanStep`` through ``TurnResult.plan -> ActionPlan``.
    """
    reached = {kind.__name__ for kind in _reachable()}
    assert {"StepFailure", "ToolFailureKind", "Provenance", "Validity", "PlanStep"} <= reached


def test_the_surface_carries_the_methods_the_adrs_fixed() -> None:
    """The count, which the conformance suite needs a number to be complete against.

    ``start`` and ``aclose`` are ruled off the Protocol by ADR-0084 §5, so the
    promoted surface is what the contract ADRs put on it and nothing else:
    ADR-0085 §1's fifteen, plus ADR-0102 §1's four, plus ADR-0130 §9's five —
    a read of the held notifications, a dismissal, a per-notification delete, and
    a read and a write of the standing preferences. **Reconsideration is not among
    them and may not become one**: ADR-0130 §5 puts it on the concrete
    ``orchestration`` engine, where ADR-0083 §8 puts a maintenance surface, and
    states that "no client asks for it and no interface adapter may drive it". ADR-0085 §11b recorded fifteen as
    a correction of ADR-0084 §5's "around nineteen" — a count, not a decision, and
    §5's argument did not rest on the figure. It does not rest on this one either;
    what the number is for is making a *complete* suite something a reader can
    check, since a method nobody bound to the shared contract is a method no
    implementation is held to.
    """
    assert len(_method_names()) == 24


#: ADR-0085 §6b's twelve derived predicates. **The list is normative there** — "a
#: triad implementation that carried a subset would leave the CLI reading an
#: attribute that is not there" — so it is spelled out rather than derived, which
#: is the one place in this module an enumeration is the right shape.
DERIVED_PREDICATES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("IngestSummary", "stored"),
        ("LearnOutcome", "stored"),
        ("Evidence", "lost"),
        ("Belief", "evidence_count"),
        ("Belief", "lost_evidence"),
        ("Belief", "unsupported"),
        ("BeliefSummary", "unsupported"),
        ("ObservedProposal", "stored"),
        ("ObservedProposal", "evidence_count"),
        ("ObservedProposal", "inspectable"),
        ("ObservationReport", "stored"),
        ("ObservationReport", "discarded"),
    }
)


@pytest.mark.parametrize(("owner", "predicate"), sorted(DERIVED_PREDICATES))
def test_every_derived_predicate_is_a_plain_property(owner: str, predicate: str) -> None:
    """§6b: a ``@property``, and deliberately **not** a ``computed_field``.

    A ``computed_field`` would put the value on the wire, which is two sources of
    truth for a fact the fields already carry — and a client that trusted the
    transmitted copy over its own recomputation would be trusting a value nothing
    validates. It also moves the boundary: a value a client can compute exactly but
    one implementation sends and another omits makes the same call measure two
    different sizes against the contract limit.
    """
    model = getattr(core_types, owner)
    assert isinstance(getattr(model, predicate), property), (
        f"{owner}.{predicate} must exist and be a plain property"
    )
    assert predicate not in model.model_computed_fields
    assert predicate not in model.model_fields


@pytest.mark.parametrize("name", sorted(PROMOTED))
def test_no_promoted_model_serialises_a_derived_value(name: str) -> None:
    """The rule behind the list: **nothing** on this surface is a computed field.

    Stated over every promoted model rather than over the twelve, so a thirteenth
    predicate added as a ``computed_field`` fails here even though no list names
    it — which is the failure mode ADR-0085 §4c records an enumeration having.
    """
    model = getattr(core_types, name)
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return  # a StrEnum has no fields to serialise
    assert model.model_computed_fields == {}
